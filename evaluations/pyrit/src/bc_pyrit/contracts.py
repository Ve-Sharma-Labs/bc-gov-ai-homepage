"""Case and result contracts shared by the CLI and Actions steps."""

import hashlib
import json
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

Threat = Literal[
    "direct-injection",
    "indirect-injection",
    "false-completion",
    "high-stakes",
    "grounding",
    "privacy",
    "conversation",
    "resource-exhaustion",
]
Approach = Literal[
    "fixed-single-turn",
    "fixed-multi-turn",
    "adaptive-multi-turn",
    "prompt-variations",
    "repeated-attempts",
]
Profile = Literal["offline", "live"]
Verdict = Literal["pass", "fail", "needs-review", "incomplete"]
THREATS = {
    "direct-injection": "Direct prompt injection / jailbreak",
    "indirect-injection": "Indirect prompt injection",
    "false-completion": "False completion",
    "high-stakes": "High-stakes overreach",
    "grounding": "Grounding manipulation",
    "privacy": "Privacy / session isolation",
    "conversation": "Conversation manipulation",
    "resource-exhaustion": "Resource exhaustion",
}
LIVE_THREATS = set(THREATS) - {"indirect-injection", "resource-exhaustion"}
APPROACHES = {
    "fixed-single-turn",
    "fixed-multi-turn",
    "adaptive-multi-turn",
    "prompt-variations",
    "repeated-attempts",
}


class CheckError(RuntimeError):
    """A fixed code safe to include in public evaluation reports."""

    def __init__(self, code: str):
        if not 1 <= len(code) <= 64 or not all(
            char.isupper() or char.isdigit() or char == "_" for char in code
        ):
            raise ValueError("Invalid evaluation error code.")
        self.code = code
        super().__init__(code)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class Identity(Contract):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    run_id: str = Field(pattern=r"^(?:local|[1-9][0-9]*)$")
    run_attempt: int = Field(ge=1)
    target: str
    candidate_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class Variant(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    prompts: list[str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def bounded_prompts(self) -> Self:
        if any(not text.strip() or len(text) > 4000 for text in self.prompts):
            raise ValueError("Prompts must be nonempty and fit the application limit.")
        return self


class Case(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    threat: Threat
    approach: Approach
    profiles: list[Profile] = Field(min_length=1, max_length=2)
    objective: str = Field(min_length=1, max_length=1600)
    safe_behavior: str = Field(min_length=1, max_length=2400)
    variants: list[Variant] = Field(min_length=1, max_length=8)
    max_turns: int = Field(default=1, ge=1, le=8)
    repetitions: int = Field(default=1, ge=1, le=3)
    benign: bool = False
    handoff: str | None = None
    expected_goal: str | None = None
    expected_facts: dict[str, str] = Field(default_factory=dict)
    sharing_probe: bool = False
    isolation_probe: bool = False
    offline_check: Literal["indirect-injection", "resource-exhaustion"] | None = None

    @model_validator(mode="after")
    def valid_case(self) -> Self:
        if len(set(self.profiles)) != len(self.profiles):
            raise ValueError("Duplicate execution profile.")
        if len({item.id for item in self.variants}) != len(self.variants):
            raise ValueError("Duplicate variant.")
        if self.offline_check and self.profiles != ["offline"]:
            raise ValueError("Fault injection is offline only.")
        if self.threat not in LIVE_THREATS and "live" in self.profiles:
            raise ValueError("This threat uses offline fixtures.")
        if self.approach == "adaptive-multi-turn" and self.max_turns < 2:
            raise ValueError("An adaptive case must permit a follow-up.")
        if self.approach == "fixed-multi-turn" and any(
            len(item.prompts) < 2 for item in self.variants
        ):
            raise ValueError("A multi-turn case needs a script.")
        if self.approach == "prompt-variations" and len(self.variants) < 2:
            raise ValueError("A variations case needs distinct variants.")
        if self.approach == "repeated-attempts" and self.repetitions < 2:
            raise ValueError("A repeated case needs multiple attempts.")
        if self.handoff:
            url = urlsplit(self.handoff)
            if url.scheme != "https" or url.username or url.password or url.fragment:
                raise ValueError("Handoffs must be exact reviewed HTTPS URLs.")
        return self

    def attempts(self) -> list[tuple[str, Variant]]:
        return [
            (f"{self.id}/{variant.id}/{repeat}", variant)
            for variant in self.variants
            for repeat in range(1, self.repetitions + 1)
        ]

    def application_turns(self, variant: Variant) -> int:
        if self.offline_check:
            return 0
        turns = self.max_turns if self.approach == "adaptive-multi-turn" else len(variant.prompts)
        return turns + int(self.isolation_probe)


class Dataset(Contract):
    version: Literal[1]
    rubric_version: str = Field(pattern=r"^[a-z0-9-]{1,48}$")
    cases: list[Case] = Field(min_length=8, max_length=80)

    @model_validator(mode="after")
    def complete_coverage(self) -> Self:
        if len({item.id for item in self.cases}) != len(self.cases):
            raise ValueError("Duplicate case.")
        for profile, required in (("offline", set(THREATS)), ("live", LIVE_THREATS)):
            selected = self.for_profile(profile)
            if {item.threat for item in selected} != required:
                raise ValueError("The manifest must cover every required threat.")
            if {item.approach for item in selected} != APPROACHES:
                raise ValueError("The manifest must cover all five approaches.")
            if not any(item.benign for item in selected):
                raise ValueError("Benign controls are required.")
        return self

    def for_profile(self, profile: Profile) -> list[Case]:
        return [item for item in self.cases if profile in item.profiles]

    def expected(self, profile: Profile) -> dict[str, Case]:
        return {key: case for case in self.for_profile(profile) for key, _ in case.attempts()}

    def estimate(self, profile: Profile) -> dict[str, int]:
        cases = self.for_profile(profile)
        app = sum(
            case.application_turns(variant) for case in cases for _, variant in case.attempts()
        )
        attacker = sum(
            case.max_turns
            for case in cases
            if case.approach == "adaptive-multi-turn"
            for _ in case.attempts()
        )
        return {"app": app, "attacker": attacker, "judge": app}


class ModelLimit(Contract):
    calls: int = Field(ge=0, le=1000)
    tokens: int = Field(ge=0, le=10_000_000)
    cost_microusd: int = Field(ge=0, le=1_000_000_000)
    input_bytes: int = Field(ge=1024, le=65536)
    output_tokens: int = Field(ge=64, le=4096)
    token_price_microusd: int = Field(ge=0, le=1000)

    @property
    def reservation(self) -> int:
        return self.input_bytes + self.output_tokens + 256


class Limits(Contract):
    app: int = Field(ge=1, le=500)
    wall_seconds: int = Field(ge=30, le=3600)
    attacker: ModelLimit
    judge: ModelLimit

    def require_capacity(self, estimate: dict[str, int], profile: Profile) -> None:
        if self.app < estimate["app"]:
            raise CheckError("INSUFFICIENT_APP_BUDGET")
        for role in ("attacker", "judge"):
            limit: ModelLimit = getattr(self, role)
            needed = estimate[role] * limit.reservation
            if limit.calls < estimate[role] or limit.tokens < needed:
                raise CheckError("INSUFFICIENT_MODEL_BUDGET")
            if profile == "live" and (
                limit.token_price_microusd <= 0
                or limit.cost_microusd < needed * limit.token_price_microusd
            ):
                raise CheckError("UNAPPROVED_MODEL_BUDGET")


class Result(Contract):
    id: str = Field(pattern=r"^[a-z0-9-]+/[a-z0-9-]+/[1-3]$")
    threat: Threat
    approach: Approach
    status: Verdict
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    turns: int = Field(ge=0, le=500)


def digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def load_dataset(path: Path) -> Dataset:
    if path.stat().st_size > 256_000:
        raise CheckError("MANIFEST_TOO_LARGE")
    return Dataset.model_validate_json(path.read_bytes())


def exact_origin(value: str, *, local: bool = False) -> str:
    url = urlsplit(value)
    loopback = url.hostname in ("localhost", "127.0.0.1", "::1")
    if (
        not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in ("", "/")
        or url.scheme not in ("http", "https")
        or (url.scheme != "https" and not loopback)
        or (local and not loopback)
    ):
        raise CheckError("UNAPPROVED_ORIGIN")
    return f"{url.scheme}://{url.netloc}"
