"""Bound the model work before each native client invocation."""

from collections.abc import Awaitable, Callable

from agent_framework import ChatContext, ChatMiddleware

from bc_api.config import Settings
from bc_api.errors import ApiError
from bc_api.tools import ToolContext


class ModelBudget(ChatMiddleware):
    def __init__(self, settings: Settings, tool_context: ToolContext, overhead_bytes: int):
        self.settings = settings
        self.tool_context = tool_context
        self.overhead_bytes = overhead_bytes + 2048
        self.calls = 0
        self.input_bytes = 0

    async def process(self, context: ChatContext, call_next: Callable[[], Awaitable[None]]) -> None:
        if self.tool_context.failure is not None:
            raise self.tool_context.failure
        self.calls += 1
        self.input_bytes += self.overhead_bytes + sum(
            len(message.to_json().encode("utf-8")) for message in context.messages
        )
        if (
            self.calls > self.settings.api_model_calls_per_run
            or self.input_bytes > self.settings.api_model_input_byte_budget
        ):
            self.tool_context.failure = ApiError(
                429,
                "MODEL_BUDGET_EXCEEDED",
                "This question needs more processing than the pilot allows. "
                "Please ask a more focused question.",
            )
            raise self.tool_context.failure
        context.options["max_tokens"] = self.settings.api_model_output_tokens
        self.tool_context.model_work_started = True
        self.tool_context.mark_phase("model_started")
        await call_next()
