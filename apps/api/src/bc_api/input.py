import re
from typing import Any

from ag_ui.core import RunAgentInput
from pydantic import ValidationError

from bc_api.config import Settings
from bc_api.errors import ApiError
from bc_api.models import RunOptions

RUN_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,99}$")
SENSITIVE_INPUT = re.compile(
    r"\b(?:PHN|SIN|licen[cs]e\s*(?:number|no\.?)|personal health number)"
    r"\s*(?:(?:number|no\.?|is|equals?)\s*)?[:#=-]?\s*\d{5,}"
    r"|\b\d{3}[- ]\d{3}[- ]\d{3}\b"
    r"|[\w.+-]+@[\w.-]+\.[a-z]{2,}",
    re.IGNORECASE,
)


def parse_options(value: Any) -> RunOptions:
    if value is None or value == {}:
        return RunOptions(version=1)
    if (
        not isinstance(value, dict)
        or set(value) != {"bc"}
        or not isinstance(value["bc"], dict)
        or type(value["bc"].get("version")) is not int
    ):
        raise ApiError(
            422, "CLIENT_CONTEXT_DENIED", "Only versioned BC conversation options are supported."
        )
    try:
        return RunOptions.model_validate(value["bc"], by_alias=True, by_name=False)
    except ValidationError:
        raise ApiError(
            422, "CLIENT_CONTEXT_DENIED", "The conversation options are not supported."
        ) from None


def validate_run(raw: Any, settings: Settings) -> RunAgentInput:
    if not isinstance(raw, dict) or raw.keys() - {
        "threadId",
        "runId",
        "parentRunId",
        "messages",
        "tools",
        "context",
        "state",
        "forwardedProps",
        "resume",
    }:
        raise ApiError(422, "INVALID_REQUEST", "Use the supported AG-UI request format.")
    if (
        raw.get("tools")
        or raw.get("context")
        or raw.get("state") not in (None, {})
        or raw.get("parentRunId")
        or raw.get("resume")
    ):
        raise ApiError(
            422,
            "CLIENT_CONTEXT_DENIED",
            "Client instructions, tools, state and resume controls are not allowed.",
        )
    parse_options(raw.get("forwardedProps"))
    for key in ("threadId", "runId"):
        if not isinstance(raw.get(key), str) or not RUN_ID.fullmatch(raw[key]):
            raise ApiError(422, "INVALID_ID", "Provide valid thread and run identifiers.")
    messages = raw.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= settings.api_max_messages:
        raise ApiError(422, "MESSAGE_LIMIT", "Use a shorter conversation.")
    total = 0
    ids: set[str] = set()
    for message in messages:
        if not isinstance(message, dict) or message.keys() - {"id", "role", "content"}:
            raise ApiError(
                422, "INVALID_MESSAGE", "Only plain-text conversation messages are supported."
            )
        if message.get("role") not in ("user", "assistant"):
            raise ApiError(
                422, "ROLE_NOT_ALLOWED", "Only user and assistant conversation roles are supported."
            )
        message_id = message.get("id")
        if not isinstance(message_id, str) or not RUN_ID.fullmatch(message_id) or message_id in ids:
            raise ApiError(422, "INVALID_MESSAGE_ID", "Message IDs must be valid and unique.")
        ids.add(message_id)
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ApiError(422, "INVALID_MESSAGE", "A non-empty plain-text message is required.")
        if len(content) > settings.api_max_message_chars:
            raise ApiError(422, "MESSAGE_LIMIT", "Please shorten your message.")
        if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", content):
            raise ApiError(422, "INVALID_MESSAGE", "Unsupported characters in the message.")
        if SENSITIVE_INPUT.search(content):
            raise ApiError(
                422,
                "PERSONAL_DATA_NOT_SUPPORTED",
                "Do not include personal identifiers or contact details. "
                "Ask a general service question.",
            )
        total += len(content)
    if total > settings.api_max_total_message_chars:
        raise ApiError(422, "MESSAGE_LIMIT", "Start a new, shorter conversation.")
    if messages[-1]["role"] != "user":
        raise ApiError(422, "USER_MESSAGE_REQUIRED", "End the request with your question.")
    try:
        return RunAgentInput.model_validate(raw)
    except ValidationError:
        raise ApiError(422, "INVALID_REQUEST", "Use the supported AG-UI request format.") from None
