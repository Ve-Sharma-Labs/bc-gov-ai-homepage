"""Public errors never contain provider response bodies or submitted input."""

from dataclasses import dataclass


@dataclass
class ApiError(Exception):
    status: int
    code: str
    message: str
    retry_after: int | None = None

    def payload(self) -> dict[str, dict[str, str]]:
        return {"error": {"code": self.code, "message": self.message}}


def unavailable() -> ApiError:
    return ApiError(
        503,
        "FOUNDRY_NOT_CONFIGURED",
        "AI answers are not connected. Choose a guided journey for sourced preparation steps.",
    )
