"""PyRIT targets for the application and separately budgeted Azure judge/attacker."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Literal
from urllib.parse import urlsplit

import httpx
import jsonschema
from azure.core.exceptions import ClientAuthenticationError
from pydantic import Field, model_validator
from pyrit.models import Message, construct_response_from_request
from pyrit.prompt_target import PromptTarget, TargetCapabilities, TargetConfiguration
from pyrit.prompt_target.common.chat_completions_message_builder import build_response_format

from bc_pyrit.client import AppSession
from bc_pyrit.contracts import Case, CheckError, Contract, Limits
from bc_pyrit.ledger import Ledger


class ModelSettings(Contract):
    endpoint: str
    deployment: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
    response_model: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def approved_azure_endpoint(self):
        url = urlsplit(self.endpoint)
        if (
            url.scheme != "https"
            or not url.hostname
            or not url.hostname.endswith((".openai.azure.com", ".services.ai.azure.com"))
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.port not in (None, 443)
            or url.path.rstrip("/") != "/openai/v1"
        ):
            raise ValueError("Select the reviewed Azure OpenAI v1 endpoint.")
        return self


class Models(Contract):
    attacker: ModelSettings
    judge: ModelSettings


class AppTarget(PromptTarget):
    _DEFAULT_CONFIGURATION = TargetConfiguration(
        capabilities=TargetCapabilities(supports_multi_turn=True)
    )

    def __init__(self, *, session: AppSession, case: Case):
        super().__init__(endpoint=session.app.origin, model_name="bc-service-assistant")
        self.session = session
        self.case = case
        self.conversation_id: str | None = None
        self.responses: list[Message] = []

    async def _send_prompt_to_target_async(
        self, *, normalized_conversation: list[Message]
    ) -> list[Message]:
        request = normalized_conversation[-1]
        if len(request.message_pieces) != 1:
            raise CheckError("UNSUPPORTED_MESSAGE")
        piece = request.message_pieces[0]
        if piece.role != "user" or piece.converted_value_data_type != "text":
            raise CheckError("UNSUPPORTED_MESSAGE")
        if self.conversation_id is None:
            self.conversation_id = piece.conversation_id
        elif self.conversation_id != piece.conversation_id:
            raise CheckError("ATTACK_HISTORY_CHANGED")
        if self.case.sharing_probe and len(self.responses) in (1, 2):
            await self.session.sharing(len(self.responses) == 1)
        turn = await self.session.send(piece.converted_value)
        response = construct_response_from_request(
            request=piece,
            response_text_pieces=[turn.text],
        )
        self.responses.append(response)
        return [response]


class AzureModelTarget(PromptTarget):
    _DEFAULT_CONFIGURATION = TargetConfiguration(
        capabilities=TargetCapabilities(
            supports_multi_turn=True,
            supports_editable_history=True,
            supports_system_prompt=True,
            supports_json_schema=True,
            supports_json_output=True,
        )
    )

    def __init__(
        self,
        *,
        role: Literal["attacker", "judge"],
        settings: ModelSettings,
        ledger: Ledger,
        token_provider: Callable[[], Awaitable[str]],
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        super().__init__(endpoint=settings.endpoint, model_name=settings.response_model)
        self.role = role
        self.settings = settings
        self.ledger = ledger
        self.token_provider = token_provider
        self.limit = getattr(Limits.model_validate(ledger.state()["limits"]), role)
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(90, connect=15), follow_redirects=False, transport=transport
        )

    async def _send_prompt_to_target_async(
        self, *, normalized_conversation: list[Message]
    ) -> list[Message]:
        messages = []
        for message in normalized_conversation:
            if len(message.message_pieces) != 1:
                raise CheckError("UNSUPPORTED_MODEL_MESSAGE")
            piece = message.message_pieces[0]
            if piece.converted_value_data_type != "text" or piece.role not in (
                "system",
                "user",
                "assistant",
                "developer",
            ):
                raise CheckError("UNSUPPORTED_MODEL_MESSAGE")
            messages.append({"role": piece.role, "content": piece.converted_value})
        request = normalized_conversation[-1].message_pieces[0]
        config = self._get_json_response_config(message_piece=request)
        body = {
            "model": self.settings.deployment,
            "messages": messages,
            "max_completion_tokens": self.limit.output_tokens,
            "store": False,
            "service_tier": "default",
            "response_format": build_response_format(json_config=config) or {"type": "json_object"},
        }
        encoded = json.dumps(body, ensure_ascii=False).encode()
        try:
            async with asyncio.timeout(min(15, self.ledger.remaining_seconds())):
                token = await self.token_provider()
        except ClientAuthenticationError, TimeoutError:
            self.ledger.stop("MODEL_AUTH_FAILED")
            raise CheckError("MODEL_AUTH_FAILED") from None
        self.ledger.charge(self.role, input_bytes=len(encoded))
        try:
            async with (
                asyncio.timeout(min(95, self.ledger.remaining_seconds())),
                self.client.stream(
                    "POST",
                    self.settings.endpoint.rstrip("/") + "/chat/completions",
                    content=encoded,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                ) as response,
            ):
                if response.status_code != 200:
                    self.ledger.stop("MODEL_UNAVAILABLE")
                    raise CheckError("MODEL_UNAVAILABLE")
                content = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    if len(content) + len(chunk) > 262_144:
                        raise CheckError("MODEL_RESPONSE_SIZE_LIMIT")
                    content.extend(chunk)
            value = json.loads(content)
            choice = value["choices"][0]
            text = choice["message"]["content"]
            usage = value["usage"]
            if (
                value["model"] != self.settings.response_model
                or choice["finish_reason"] != "stop"
                or not isinstance(text, str)
                or type(usage["total_tokens"]) is not int
                or not 0 < usage["total_tokens"] <= self.limit.reservation
                or type(usage["completion_tokens"]) is not int
                or not 0 < usage["completion_tokens"] <= self.limit.output_tokens
            ):
                raise CheckError("MODEL_REPLY_INVALID")
            decoded = json.loads(text)
            if not isinstance(decoded, dict):
                raise CheckError("MODEL_REPLY_INVALID")
            if self.role == "attacker" and (
                not isinstance(decoded.get("next_message"), str)
                or not decoded["next_message"].strip()
                or len(decoded["next_message"]) > 3000
            ):
                raise CheckError("MODEL_REPLY_INVALID")
            if self.role == "judge" and (
                type(decoded.get("score_value")) is not bool
                or any(
                    not isinstance(decoded.get(key), str)
                    for key in ("description", "rationale", "metadata")
                )
            ):
                raise CheckError("MODEL_REPLY_INVALID")
            if config.json_schema:
                jsonschema.validate(decoded, config.json_schema)
        except httpx.HTTPError, TimeoutError:
            self.ledger.stop("MODEL_TRANSPORT_FAILED")
            raise CheckError("MODEL_TRANSPORT_FAILED") from None
        except ValueError, KeyError, TypeError, IndexError, jsonschema.ValidationError:
            self.ledger.stop("MODEL_REPLY_INVALID")
            raise CheckError("MODEL_REPLY_INVALID") from None
        except CheckError as error:
            self.ledger.stop(error.code)
            raise
        return [construct_response_from_request(request=request, response_text_pieces=[text])]

    async def close(self) -> None:
        await self.client.aclose()
