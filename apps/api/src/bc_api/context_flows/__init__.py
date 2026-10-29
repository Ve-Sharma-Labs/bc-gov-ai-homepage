"""Flow-specific contextual-demo policy registry."""

from collections.abc import Iterable, Sequence

from bc_api.models import (
    ApplicationPreview,
    ConsentScope,
    ContextFact,
    ContextFlowId,
    DemoPersonaId,
    ProgramMatch,
)

from .disability import (
    DISABILITY_FLOW,
    MEDICAL_BOUNDARY,
    build_application_package,
    ordered_program_matches,
)
from .guardianship import (
    GUARDIANSHIP_AGENT_INSTRUCTIONS,
    GUARDIANSHIP_FLOW,
    build_guardianship_preview,
    ordered_guardianship_matches,
)
from .job_loss import JOB_LOSS_FLOW

PERSONA_FLOW: dict[DemoPersonaId, ContextFlowId] = {
    "maya-caregiver": "guardianship-intake",
    "alex-disability-support": "disability-support",
    "sam-job-loss": "job-loss",
}

FLOW_REQUIRED_SCOPES: dict[ContextFlowId, tuple[ConsentScope, ...]] = {
    "guardianship-intake": GUARDIANSHIP_FLOW.required_scopes,
    "disability-support": DISABILITY_FLOW.consent.required,
    "job-loss": JOB_LOSS_FLOW.required_scopes,
}

FLOW_OPTIONAL_SCOPES: dict[ContextFlowId, tuple[ConsentScope, ...]] = {
    "guardianship-intake": GUARDIANSHIP_FLOW.optional_scopes,
    "disability-support": DISABILITY_FLOW.consent.optional,
    "job-loss": JOB_LOSS_FLOW.optional_scopes,
}

FLOW_ALL_SCOPES: dict[ContextFlowId, tuple[ConsentScope, ...]] = {
    flow_id: (*FLOW_REQUIRED_SCOPES[flow_id], *FLOW_OPTIONAL_SCOPES[flow_id])
    for flow_id in FLOW_REQUIRED_SCOPES
}

FLOW_PREVIEW_FACT_KEYS: dict[ContextFlowId, tuple[str, ...]] = {
    "guardianship-intake": tuple(item.fact_key for item in GUARDIANSHIP_FLOW.preview_fields),
    "disability-support": tuple(item.fact_key for item in DISABILITY_FLOW.preview_fields),
    "job-loss": tuple(item.fact_key for item in JOB_LOSS_FLOW.preview_fields),
}

FLOW_DESTINATION_SOURCE: dict[ContextFlowId, str] = {
    "guardianship-intake": "family-social-supports",
    "disability-support": "family-social-supports",
    "job-loss": "employment-business",
}

FLOW_DESTINATION_NAME: dict[ContextFlowId, str] = {
    "guardianship-intake": "B.C. family and social supports",
    "disability-support": DISABILITY_FLOW.handoff.destination_name,
    "job-loss": "B.C. employment and business services",
}

DISABILITY_AGENT_INSTRUCTIONS = f"""Flow: disability-support.
Clarify which kind of disability support the citizen means before using the provincial
demo flow. Use only deterministic rule results and public-safe missing-fact prompts.
{MEDICAL_BOUNDARY} Never diagnose, judge functional capacity, impersonate a practitioner,
calculate a benefit, decide eligibility, submit an application, or claim approval.
"""

JOB_LOSS_AGENT_INSTRUCTIONS = """Flow: job-loss.
Keep federal, provincial, municipal, and Crown service boundaries explicit. Use the
server-owned program order and ask only one public-safe missing-fact question at a time.
Never claim Employment Insurance or another benefit is approved, calculate an amount or
deadline, access an official account, submit an application, or invent a confirmation.
"""

FLOW_AGENT_INSTRUCTIONS = "\n\n".join(
    (
        GUARDIANSHIP_AGENT_INSTRUCTIONS,
        DISABILITY_AGENT_INSTRUCTIONS,
        JOB_LOSS_AGENT_INSTRUCTIONS,
    )
)


def consented_flow_scopes(
    flow_id: ContextFlowId,
    consented: Iterable[ConsentScope],
) -> tuple[ConsentScope, ...]:
    selected = set(consented)
    return tuple(scope for scope in FLOW_ALL_SCOPES[flow_id] if scope in selected)


def ordered_flow_matches(
    flow_id: ContextFlowId,
    matches: Sequence[ProgramMatch],
) -> tuple[ProgramMatch, ...]:
    if flow_id == "guardianship-intake":
        return ordered_guardianship_matches(matches)
    if flow_id == "disability-support":
        return ordered_program_matches(matches)
    return JOB_LOSS_FLOW.ordered_matches(matches)


def build_flow_preview(
    flow_id: ContextFlowId,
    facts: Iterable[ContextFact],
    *,
    preview_id: str,
    expires_at: str,
) -> ApplicationPreview:
    if flow_id == "guardianship-intake":
        return build_guardianship_preview(
            facts,
            preview_id=preview_id,
            expires_at=expires_at,
        )
    if flow_id == "disability-support":
        return build_application_package(
            facts,
            preview_id=preview_id,
            expires_at=expires_at,
        ).preview
    return JOB_LOSS_FLOW.build_preview(
        facts,
        preview_id=preview_id,
        expires_at=expires_at,
    )


__all__ = [
    "FLOW_AGENT_INSTRUCTIONS",
    "FLOW_ALL_SCOPES",
    "FLOW_DESTINATION_NAME",
    "FLOW_DESTINATION_SOURCE",
    "FLOW_OPTIONAL_SCOPES",
    "FLOW_PREVIEW_FACT_KEYS",
    "FLOW_REQUIRED_SCOPES",
    "PERSONA_FLOW",
    "build_flow_preview",
    "consented_flow_scopes",
    "ordered_flow_matches",
]
