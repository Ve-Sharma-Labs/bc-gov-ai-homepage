"""Explicitly configured, budgeted manual conversations through the staging BFF."""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, ValidationError, model_validator
from pyrit.models import Message, construct_response_from_request
from pyrit.prompt_target import PromptTarget, TargetCapabilities, TargetConfiguration

from bc_pyrit.auth import AzureCliAuth
from bc_pyrit.client import AppClient, AppSession
from bc_pyrit.contracts import CheckError, Contract, Limits, ModelLimit, exact_origin
from bc_pyrit.ledger import Ledger


class ManualAuthentication(Contract):
    provider: Literal["azure-cli"]
    subscription_id: str = Field(pattern=r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$")
    client_id: str = Field(pattern=r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$")


class ManualSettings(Contract):
    version: Literal[1]
    origin: str
    release_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    deployment_id: str = Field(pattern=r"^staging-[a-z0-9][a-z0-9-]{0,55}$")
    live_use_approved: Literal[True]
    request_limit: int = Field(ge=1, le=500)
    wall_seconds: int = Field(ge=30, le=3600)
    max_conversations: int = Field(default=8, ge=1, le=32)
    authentication: ManualAuthentication | None = None

    @model_validator(mode="after")
    def staging_origin(self) -> Self:
        self.origin = exact_origin(self.origin)
        if urlsplit(self.origin).scheme != "https":
            raise ValueError("Manual staging requires HTTPS.")
        return self

    def limits(self) -> Limits:
        disabled = ModelLimit(
            calls=0, tokens=0, cost_microusd=0, input_bytes=1024,
            output_tokens=64, token_price_microusd=0,
        )
        return Limits(
            app=self.request_limit, wall_seconds=self.wall_seconds,
            attacker=disabled, judge=disabled,
        )

    def identity(self) -> dict[str, object]:
        value: dict[str, object] = {
            "origin": self.origin,
            "commit": self.release_commit,
            "deployment": self.deployment_id,
        }
        if self.authentication:
            value["authentication"] = self.authentication.model_dump()
        return value


def load_settings(path: Path) -> ManualSettings:
    try:
        if path.stat().st_size > 16_384:
            raise CheckError("MANUAL_CONFIGURATION_TOO_LARGE")
        return ManualSettings.model_validate_json(path.read_bytes())
    except OSError, ValidationError:
        raise CheckError("MANUAL_CONFIGURATION_INVALID") from None


def history_digest(messages: list[Message]) -> str:
    values = [
        (message.get_piece().role, message.get_piece().converted_value)
        for message in messages
    ]
    return hashlib.sha256(json.dumps(values, ensure_ascii=True).encode()).hexdigest()


@dataclass
class Conversation:
    session: AppSession
    history: str


class ManualAppTarget(PromptTarget):
    _DEFAULT_CONFIGURATION = TargetConfiguration(
        capabilities=TargetCapabilities(supports_multi_turn=True)
    )

    def __init__(self, *, app: AppClient, max_conversations: int = 8):
        if not 1 <= max_conversations <= 32:
            raise CheckError("INVALID_CONVERSATION_LIMIT")
        super().__init__(endpoint=app.origin, model_name="bc-service-assistant")
        self.app = app
        self.max_conversations = max_conversations
        self._conversations: dict[str, Conversation] = {}
        self._send_lock = asyncio.Lock()

    async def _send_prompt_to_target_async(
        self, *, normalized_conversation: list[Message]
    ) -> list[Message]:
        if not normalized_conversation or len(normalized_conversation) > 1001:
            raise CheckError("UNSUPPORTED_HISTORY")
        for message in normalized_conversation:
            if len(message.message_pieces) != 1:
                raise CheckError("UNSUPPORTED_MESSAGE")
            piece = message.get_piece()
            if piece.role not in ("user", "assistant") or piece.converted_value_data_type != "text":
                raise CheckError("UNSUPPORTED_MESSAGE")
        request = normalized_conversation[-1].get_piece()
        if request.role != "user" or not request.conversation_id:
            raise CheckError("UNSUPPORTED_MESSAGE")
        conversation_id = request.conversation_id

        async with self._send_lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is None:
                if len(normalized_conversation) != 1:
                    raise CheckError("NEW_CONVERSATION_REQUIRED")
                if len(self._conversations) >= self.max_conversations:
                    raise CheckError("ACTIVE_CONVERSATION_LIMIT")
                conversation = Conversation(self.app.session(), history_digest([]))
                self._conversations[conversation_id] = conversation
            if history_digest(normalized_conversation[:-1]) != conversation.history:
                raise CheckError("CONVERSATION_HISTORY_CHANGED")
            try:
                turn = await conversation.session.send(request.converted_value)
                if turn.summary["shareContext"]:
                    self.app.ledger.stop("UNEXPECTED_CONTEXT_SHARING")
                    raise CheckError("UNEXPECTED_CONTEXT_SHARING")
                response = construct_response_from_request(
                    request=request, response_text_pieces=[turn.text]
                )
                conversation.history = history_digest([*normalized_conversation, response])
                return [response]
            except CheckError, asyncio.CancelledError:
                self._conversations.pop(conversation_id, None)
                cleanup = asyncio.create_task(conversation.session.close())
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    await cleanup
                    raise
                raise

    async def reset_conversation_async(self, *, conversation_id: str) -> None:
        async with self._send_lock:
            conversation = self._conversations.pop(conversation_id, None)
            if conversation is not None:
                await conversation.session.close()

    async def close_async(self) -> None:
        outcomes = await asyncio.gather(*[
            self.reset_conversation_async(conversation_id=conversation_id)
            for conversation_id in list(self._conversations)
        ], return_exceptions=True)
        failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
        if failures:
            raise BaseExceptionGroup("Manual conversation cleanup failed.", failures)


async def create_manual_target(path: Path) -> ManualAppTarget:
    settings = load_settings(path)
    identity = settings.identity()
    auth = None
    if settings.authentication:
        auth = AzureCliAuth(
            origin=settings.origin,
            subscription_id=settings.authentication.subscription_id,
            client_id=settings.authentication.client_id,
        )
    ledger = Ledger.open_manual(
        path.parent / "manual-budget.sqlite",
        limits=settings.limits(),
        identity=identity,
    )
    app = AppClient(
        settings.origin, ledger,
        expected_commit=settings.release_commit,
        expected_deployment=settings.deployment_id,
        auth=auth,
    )
    await app.preflight()
    return ManualAppTarget(app=app, max_conversations=settings.max_conversations)
