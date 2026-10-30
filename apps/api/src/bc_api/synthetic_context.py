"""Server-owned synthetic persona selection, consent, and redacted summaries."""

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, Self, cast

from pydantic import Field, model_validator
from starlette.responses import Response

from bc_api.config import Settings
from bc_api.context_audit import (
    ContextAuditRecord,
    ContextAuditTrail,
    InMemoryContextAuditRepository,
)
from bc_api.context_flows import FLOW_ALL_SCOPES, PERSONA_FLOW
from bc_api.context_sessions import (
    CONTEXT_COOKIE,
    NOTICE_VERSION,
    ContextSessionRepository,
    ContextSessionState,
    StoredConsent,
    bound_context_owner,
    context_session_ref,
)
from bc_api.demo_personas import (
    CONSENT_SCOPE_BY_CATEGORY,
    CONTEXT_CATEGORIES,
    DemoContextFact,
    DemoPersona,
    DemoPersonaFixtureError,
    DemoPersonaRepository,
    DemoPersonaSelectionError,
    JsonScalar,
)
from bc_api.errors import ApiError
from bc_api.models import (
    AuditAction,
    AuditOutcome,
    ConsentReceipt,
    ConsentScope,
    ContextAuditTool,
    ContextCategory,
    ContextSummary,
    ContextSummaryFact,
    DemoPersonaId,
    DemoPersonaSummary,
    IsoDateTime,
    WireModel,
)

PERSONA_PURPOSES: dict[DemoPersonaId, str] = {
    "maya-caregiver": "personalize-guardianship-navigation",
    "alex-disability-support": "personalize-disability-support",
    "sam-job-loss": "personalize-job-loss-navigation",
}
SCOPE_ORDER = tuple(CONSENT_SCOPE_BY_CATEGORY[category] for category in CONTEXT_CATEGORIES)
CATEGORY_BY_SCOPE = {scope: category for category, scope in CONSENT_SCOPE_BY_CATEGORY.items()}
CONTEXT_API_ACTOR = "bc-context-api:1"


class DemoSessionRequest(WireModel):
    persona_id: DemoPersonaId


class DemoSessionResponse(WireModel):
    persona: DemoPersonaSummary
    expires_at: IsoDateTime
    synthetic: Literal[True] = True


class ConsentChangeRequest(WireModel):
    action: Literal["grant", "revoke"]
    scopes: list[ConsentScope] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def unique_scopes(self) -> Self:
        if len(self.scopes) != len(set(self.scopes)):
            raise ValueError("Consent scopes must be unique.")
        return self


ContextInvalidationReason = Literal["citizen-request", "persona-changed", "session-reset"]


class ContextInvalidationHook(Protocol):
    async def invalidate(self, session_ref: str, reason: ContextInvalidationReason) -> None: ...


class NullContextInvalidationHook:
    async def invalidate(self, session_ref: str, reason: ContextInvalidationReason) -> None:
        del session_ref, reason


@dataclass(frozen=True, slots=True)
class FactPresentation:
    label: str
    values: tuple[tuple[JsonScalar, str], ...]


FACT_PRESENTATIONS: dict[str, FactPresentation] = {
    "identity.is-adult": FactPresentation("Age group", ((True, "Adult"),)),
    "residency.bc-status": FactPresentation(
        "B.C. residency status",
        (("resident", "B.C. resident"),),
    ),
    "household.relationship-to-care-recipient": FactPresentation(
        "Relationship to person receiving care",
        (("adult-child", "Adult child"),),
    ),
    "caregiving.care-recipient-age-years": FactPresentation(
        "Care recipient age group",
        ((79, "Older adult"),),
    ),
    "caregiving.care-recipient-bc-resident": FactPresentation(
        "Care recipient residency",
        ((True, "B.C. resident"),),
    ),
    "caregiving.cognitive-impairment-recorded": FactPresentation(
        "Cognitive impairment information",
        ((True, "High-level fictional record present"),),
    ),
    "caregiving.immediate-safety-event": FactPresentation(
        "Immediate safety event",
        ((False, "No immediate safety event recorded"),),
    ),
    "authority.power-of-attorney-recorded": FactPresentation(
        "Power of attorney record",
        ((False, "No record present in the fictional fixture"),),
    ),
    "authority.representation-agreement-recorded": FactPresentation(
        "Representation agreement record",
        ((False, "No record present in the fictional fixture"),),
    ),
    "preferences.output-format": FactPresentation(
        "Preferred output format",
        (("plain-language-checklist", "Plain-language checklist"),),
    ),
    "region.service-area": FactPresentation(
        "Service region",
        (
            ("Victoria service region", "Victoria service region"),
            ("Interior service region", "Interior service region"),
        ),
    ),
    "household.dependant-count": FactPresentation(
        "Dependants",
        ((0, "No dependants"), (2, "Two dependants")),
    ),
    "household.living-arrangement": FactPresentation(
        "Living arrangement",
        (("one-adult-household", "One-adult household"),),
    ),
    "employment.status": FactPresentation(
        "Employment status",
        (
            ("part-time", "Part-time"),
            ("recently-ended", "Employment recently ended"),
        ),
    ),
    "income.current-band": FactPresentation(
        "Current income band",
        (("low-to-moderate", "Low-to-moderate band"),),
    ),
    "disability.duration-band": FactPresentation(
        "Disability duration",
        (("long-term", "Long-term"),),
    ),
    "disability.functional-capacity": FactPresentation(
        "Functional capacity",
        (("reduced", "Reduced"),),
    ),
    "disability.mobility-support-needed": FactPresentation(
        "Mobility support",
        ((True, "Mobility support needed"),),
    ),
    "disability.practitioner-access": FactPresentation(
        "Practitioner access",
        ((True, "Practitioner access available"),),
    ),
    "programs.provincial-disability-assistance": FactPresentation(
        "Provincial disability assistance",
        (("not-receiving", "Not receiving"),),
    ),
    "preferences.accessible-transit-needed": FactPresentation(
        "Accessible transit",
        ((True, "Accessible transit needed"),),
    ),
    "preferences.service-channel": FactPresentation(
        "Preferred service channel",
        (
            ("online-with-assisted-option", "Online with an assisted option"),
            ("online-and-phone", "Online and phone"),
        ),
    ),
    "housing.tenure": FactPresentation(
        "Housing tenure",
        (("renter", "Renter"),),
    ),
    "employment.end-date-band": FactPresentation(
        "Employment end date",
        (("within-last-four-weeks", "Within the last four weeks"),),
    ),
    "employment.record-of-employment": FactPresentation(
        "Record of Employment",
        (("available", "Available"),),
    ),
    "income.change": FactPresentation(
        "Household income change",
        (("material-decrease", "Material decrease"),),
    ),
    "programs.provincial-income-assistance": FactPresentation(
        "Provincial income assistance",
        (("not-receiving", "Not receiving"),),
    ),
}


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ordered_scopes(scopes: set[ConsentScope]) -> tuple[ConsentScope, ...]:
    return tuple(cast(ConsentScope, scope) for scope in SCOPE_ORDER if scope in scopes)


def _display_value(fact: DemoContextFact) -> tuple[str, str]:
    presentation = FACT_PRESENTATIONS.get(fact.key)
    if presentation is None:
        raise ApiError(
            503,
            "CONTEXT_PRESENTATION_UNAVAILABLE",
            "Synthetic context cannot be presented safely.",
        )
    for source_value, display_value in presentation.values:
        if type(fact.value) is type(source_value) and fact.value == source_value:
            return presentation.label, display_value
    raise ApiError(
        503,
        "CONTEXT_PRESENTATION_UNAVAILABLE",
        "Synthetic context cannot be presented safely.",
    )


def set_context_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        CONTEXT_COOKIE,
        token,
        max_age=settings.synthetic_context_session_ttl_seconds,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="strict",
        path="/api",
    )


def clear_context_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        CONTEXT_COOKIE,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="strict",
        path="/api",
    )


class SyntheticContextService:
    def __init__(
        self,
        settings: Settings,
        personas: DemoPersonaRepository,
        sessions: ContextSessionRepository,
        *,
        clock: Callable[[], datetime] | None = None,
        invalidation_hook: ContextInvalidationHook | None = None,
        audit: ContextAuditTrail | None = None,
    ) -> None:
        self.settings = settings
        self.personas = personas
        self.sessions = sessions
        self.clock = clock or (lambda: datetime.now(UTC))
        self.invalidation_hook = invalidation_hook or NullContextInvalidationHook()
        self.audit = audit or ContextAuditTrail(
            InMemoryContextAuditRepository(
                settings.synthetic_context_audit_max_events,
                settings.synthetic_context_audit_max_bytes,
            )
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            raise RuntimeError("Synthetic context clocks must be timezone aware.")
        return value.astimezone(UTC).replace(microsecond=0)

    def available(self) -> bool:
        if not self.settings.synthetic_context_enabled:
            return False
        try:
            self.personas.fixture()
        except DemoPersonaFixtureError:
            return False
        return True

    def _ensure_available(self) -> None:
        if not self.settings.synthetic_context_enabled:
            raise ApiError(
                503,
                "SYNTHETIC_CONTEXT_UNAVAILABLE",
                "Synthetic citizen context is not enabled.",
            )
        try:
            self.personas.fixture()
        except DemoPersonaFixtureError:
            raise ApiError(
                503,
                "SYNTHETIC_CONTEXT_UNAVAILABLE",
                "Synthetic citizen context is unavailable.",
            ) from None

    def _persona(self, persona_id: str) -> DemoPersona:
        try:
            return self.personas.get(persona_id)
        except DemoPersonaSelectionError:
            raise ApiError(
                422,
                "PERSONA_NOT_ALLOWED",
                "Select one of the available synthetic personas.",
            ) from None
        except DemoPersonaFixtureError:
            raise ApiError(
                503,
                "SYNTHETIC_CONTEXT_UNAVAILABLE",
                "Synthetic citizen context is unavailable.",
            ) from None

    @staticmethod
    def _public(persona: DemoPersona) -> DemoPersonaSummary:
        public = persona.public().as_dict()
        available = {
            group.category
            for group in persona.category_facts
            if group.facts
        }
        public["availableCategories"] = [
            CATEGORY_BY_SCOPE[scope]
            for scope in FLOW_ALL_SCOPES[PERSONA_FLOW[cast(DemoPersonaId, persona.id)]]
            if CATEGORY_BY_SCOPE[scope] in available
        ]
        return DemoPersonaSummary.model_validate(public)

    @staticmethod
    def _allowed_scopes(persona: DemoPersona) -> set[ConsentScope]:
        return set(FLOW_ALL_SCOPES[PERSONA_FLOW[cast(DemoPersonaId, persona.id)]])

    @staticmethod
    def bound_owner(owner_token: str, page_token: str | None) -> str:
        owner = bound_context_owner(owner_token, page_token)
        if owner is None:
            raise ApiError(
                422,
                "CONTEXT_PAGE_REQUIRED",
                "Synthetic context must be used from the page that created it.",
            )
        return owner

    async def _record_api_event(
        self,
        state: ContextSessionState,
        session_ref: str,
        *,
        occurred_at: datetime,
        action: AuditAction,
        outcome: AuditOutcome,
        idempotency_key: str,
        tool: ContextAuditTool,
        consent: StoredConsent | None = None,
        scopes: tuple[ConsentScope, ...] | None = None,
        error_code: str | None = None,
    ) -> None:
        current = consent if consent is not None else state.consent
        await self.audit.append(
            ContextAuditRecord(
                occurred_at=_iso(occurred_at),
                session_ref=session_ref,
                subject_ref=session_ref,
                persona_id=state.persona_id,
                consent_id=current.consent_id if current is not None else None,
                consent_scopes=list(
                    scopes if scopes is not None else current.scopes if current is not None else ()
                ),
                actor_label=CONTEXT_API_ACTOR,
                tool=tool,
                action=action,
                outcome=outcome,
                error_code=error_code,
            ),
            expires_at=state.expires_at,
            idempotency_key=idempotency_key,
            now=occurred_at,
        )

    async def _record_denial(
        self,
        state: ContextSessionState,
        session_ref: str,
        *,
        now: datetime,
        error_code: str,
        scopes: tuple[ConsentScope, ...] = (),
    ) -> None:
        try:
            await self._record_api_event(
                state,
                session_ref,
                occurred_at=now,
                action="access-denied",
                outcome="denied",
                idempotency_key=(
                    f"change-consent-denied:{state.revision}:{error_code}:"
                    + ",".join(scopes)
                ),
                tool="change-consent",
                scopes=scopes,
                error_code=error_code,
            )
        except ApiError as exc:
            logging.getLogger("bc_api.context_audit").warning(
                "Context audit denial could not be stored: %s", exc.code
            )

    async def _record_cleanup(
        self,
        state: ContextSessionState,
        session_ref: str,
        *,
        now: datetime,
        outcome: Literal["session-reset", "persona-changed"],
    ) -> None:
        try:
            await self._record_api_event(
                state,
                session_ref,
                occurred_at=now,
                action="session-cleared",
                outcome=outcome,
                idempotency_key=f"session-cleared:{outcome}:{state.revision}",
                tool="clear-context",
            )
        except ApiError as exc:
            logging.getLogger("bc_api.context_audit").warning(
                "Context cleanup audit could not be stored: %s", exc.code
            )

    async def _invalidate(
        self,
        owner_token: str,
        context_token: str | None,
        reason: ContextInvalidationReason,
    ) -> None:
        ref = context_session_ref(owner_token, context_token)
        if ref is not None:
            await self.invalidation_hook.invalidate(ref, reason)

    async def _state(
        self,
        owner_token: str,
        context_token: str | None,
        *,
        now: datetime,
    ) -> ContextSessionState:
        state = await self.sessions.get(owner_token, context_token, now=now)
        if state is None:
            raise ApiError(
                401,
                "CONTEXT_SESSION_REQUIRED",
                "Select a synthetic persona before using contextual information.",
            )
        return state

    def public_personas(self) -> list[DemoPersonaSummary]:
        self._ensure_available()
        try:
            return [self._public(persona) for persona in self.personas.all()]
        except DemoPersonaFixtureError:
            raise ApiError(
                503,
                "SYNTHETIC_CONTEXT_UNAVAILABLE",
                "Synthetic citizen context is unavailable.",
            ) from None

    async def create_session(
        self,
        owner_token: str,
        page_token: str | None,
        previous_token: str | None,
        persona_id: DemoPersonaId,
    ) -> tuple[DemoSessionResponse, str]:
        self._ensure_available()
        owner_token = self.bound_owner(owner_token, page_token)
        persona = self._persona(persona_id)
        now = self._now()
        previous_ref = context_session_ref(owner_token, previous_token)
        previous_state = (
            await self.sessions.get(owner_token, previous_token, now=now)
            if previous_ref is not None
            else None
        )
        expires_at = now + timedelta(
            seconds=self.settings.synthetic_context_session_ttl_seconds
        )
        created = await self.sessions.create(
            owner_token,
            previous_token,
            persona_id,
            now=now,
            expires_at=expires_at,
        )
        if created.replaced:
            if previous_ref is not None and previous_state is not None:
                await self._record_cleanup(
                    previous_state,
                    previous_ref,
                    now=now,
                    outcome="persona-changed",
                )
            await self._invalidate(owner_token, previous_token, "persona-changed")
            if previous_ref is not None:
                try:
                    await self.audit.clear(previous_ref)
                except ApiError as exc:
                    logging.getLogger("bc_api.context_audit").warning(
                        "Replaced context audit cleanup failed: %s", exc.code
                    )
        return (
            DemoSessionResponse(
                persona=self._public(persona),
                expires_at=_iso(created.state.expires_at),
            ),
            created.token,
        )

    async def clear_session(
        self,
        owner_token: str,
        page_token: str | None,
        context_token: str | None,
    ) -> None:
        if context_token is None and bound_context_owner(owner_token, page_token) is None:
            return
        owner_token = self.bound_owner(owner_token, page_token)
        now = self._now()
        ref = context_session_ref(owner_token, context_token)
        state = (
            await self.sessions.get(owner_token, context_token, now=now)
            if ref is not None
            else None
        )
        if ref is not None and state is not None:
            await self._record_cleanup(
                state,
                ref,
                now=now,
                outcome="session-reset",
            )
        removed = await self.sessions.delete(owner_token, context_token)
        if removed:
            await self._invalidate(owner_token, context_token, "session-reset")
        if ref is not None:
            try:
                await self.audit.clear(ref)
            except ApiError as exc:
                logging.getLogger("bc_api.context_audit").warning(
                    "Context audit cleanup failed: %s", exc.code
                )

    def _active_consent(
        self,
        state: ContextSessionState,
        persona: DemoPersona,
        now: datetime,
    ) -> StoredConsent | None:
        consent = state.consent
        if consent is None or not consent.active(now):
            return None
        expected_purpose = PERSONA_PURPOSES[state.persona_id]
        allowed_scopes = self._allowed_scopes(persona)
        if consent.purpose != expected_purpose or not set(consent.scopes) <= allowed_scopes:
            raise ApiError(
                503,
                "CONTEXT_STATE_INVALID",
                "Synthetic context authorization could not be verified.",
            )
        return consent

    async def change_consent(
        self,
        owner_token: str,
        page_token: str | None,
        context_token: str | None,
        change: ConsentChangeRequest,
    ) -> ConsentReceipt:
        self._ensure_available()
        owner_token = self.bound_owner(owner_token, page_token)
        if context_token is None:
            raise ApiError(
                401,
                "CONTEXT_SESSION_REQUIRED",
                "Select a synthetic persona before changing consent.",
            )
        requested = set(change.scopes)
        for _ in range(4):
            now = self._now()
            state = await self._state(owner_token, context_token, now=now)
            persona = self._persona(state.persona_id)
            allowed = self._allowed_scopes(persona)
            ref = context_session_ref(owner_token, context_token)
            if ref is None:
                raise ApiError(
                    401,
                    "CONTEXT_SESSION_REQUIRED",
                    "Select a synthetic persona before changing consent.",
                )
            if not requested <= allowed:
                await self._record_denial(
                    state,
                    ref,
                    now=now,
                    error_code="CONSENT_SCOPE_DENIED",
                    scopes=_ordered_scopes(requested),
                )
                raise ApiError(
                    422,
                    "CONSENT_SCOPE_DENIED",
                    "Only available typed context scopes may be selected.",
                )
            current = self._active_consent(state, persona, now)
            purpose = PERSONA_PURPOSES[state.persona_id]
            if change.action == "grant":
                active = set(current.scopes) if current is not None else set()
                granted = active | requested
                if current is not None and granted == active:
                    await self._record_api_event(
                        state,
                        ref,
                        occurred_at=current.granted_at,
                        action="consent-granted",
                        outcome="active-consent",
                        idempotency_key=f"consent-granted:{current.consent_id}",
                        tool="change-consent",
                        consent=current,
                    )
                    return current.receipt()
                consent = StoredConsent(
                    consent_id="consent-" + secrets.token_urlsafe(18),
                    purpose=purpose,
                    scopes=_ordered_scopes(granted),
                    subject_hash=ref,
                    notice_version=NOTICE_VERSION,
                    granted_at=now,
                    expires_at=min(
                        state.expires_at,
                        now
                        + timedelta(
                            seconds=self.settings.synthetic_context_consent_ttl_seconds
                        ),
                    ),
                )
            else:
                if current is None:
                    await self._record_denial(
                        state,
                        ref,
                        now=now,
                        error_code="CONSENT_REQUIRED",
                        scopes=_ordered_scopes(requested),
                    )
                    raise ApiError(
                        409,
                        "CONSENT_REQUIRED",
                        "There is no active consent receipt to change.",
                    )
                active = set(current.scopes)
                if not requested <= active:
                    await self._record_denial(
                        state,
                        ref,
                        now=now,
                        error_code="CONSENT_SCOPE_DENIED",
                        scopes=_ordered_scopes(requested),
                    )
                    raise ApiError(
                        422,
                        "CONSENT_SCOPE_DENIED",
                        "Only active typed context scopes may be revoked.",
                    )
                remaining = active - requested
                consent = (
                    StoredConsent(
                        consent_id="consent-" + secrets.token_urlsafe(18),
                        purpose=purpose,
                        scopes=_ordered_scopes(remaining),
                        subject_hash=current.subject_hash,
                        notice_version=current.notice_version,
                        granted_at=now,
                        expires_at=current.expires_at,
                    )
                    if remaining
                    else replace(current, revoked_at=now)
                )
            next_state = replace(
                state,
                revision=state.revision + 1,
                consent=consent,
            )
            result = await self.sessions.save(
                owner_token,
                context_token,
                expected_revision=state.revision,
                state=next_state,
                now=now,
            )
            if result == "saved":
                if change.action == "grant":
                    await self._record_api_event(
                        next_state,
                        ref,
                        occurred_at=consent.granted_at,
                        action="consent-granted",
                        outcome="active-consent",
                        idempotency_key=f"consent-granted:{consent.consent_id}",
                        tool="change-consent",
                        consent=consent,
                    )
                else:
                    revoked = _ordered_scopes(requested)
                    await self._record_api_event(
                        next_state,
                        ref,
                        occurred_at=now,
                        action="consent-revoked",
                        outcome=(
                            "revoked-partial"
                            if consent.revoked_at is None
                            else "revoked-complete"
                        ),
                        idempotency_key=(
                            f"consent-revoked:{current.consent_id}:"
                            + ",".join(revoked)
                        ),
                        tool="change-consent",
                        consent=current,
                        scopes=revoked,
                    )
                    if consent.revoked_at is None:
                        await self._record_api_event(
                            next_state,
                            ref,
                            occurred_at=consent.granted_at,
                            action="consent-granted",
                            outcome="active-consent",
                            idempotency_key=f"consent-granted:{consent.consent_id}",
                            tool="change-consent",
                            consent=consent,
                        )
                if change.action == "revoke":
                    await self._invalidate(owner_token, context_token, "citizen-request")
                return consent.receipt()
            if result == "missing":
                raise ApiError(
                    401,
                    "CONTEXT_SESSION_REQUIRED",
                    "The synthetic context session is no longer active.",
                )
        raise ApiError(
            409,
            "CONTEXT_CHANGED",
            "Synthetic context changed during this request. Please try again.",
        )

    async def summary(
        self,
        owner_token: str,
        page_token: str | None,
        context_token: str | None,
    ) -> ContextSummary:
        return await self.summary_for_owner(
            self.bound_owner(owner_token, page_token),
            context_token,
        )

    async def summary_for_owner(
        self,
        owner_token: str,
        context_token: str | None,
    ) -> ContextSummary:
        self._ensure_available()
        now = self._now()
        state = await self._state(owner_token, context_token, now=now)
        persona = self._persona(state.persona_id)
        consent = self._active_consent(state, persona, now)
        if consent is None:
            raise ApiError(
                403,
                "CONSENT_REQUIRED",
                "Grant an approved context scope before viewing synthetic context.",
            )
        categories = [
            cast(ContextCategory, CATEGORY_BY_SCOPE[scope])
            for scope in SCOPE_ORDER
            if scope in consent.scopes
        ]
        category_set = set(categories)
        facts: list[ContextSummaryFact] = []
        missing_facts: list[str] = []
        for group in persona.category_facts:
            if group.category not in category_set:
                continue
            for fact in group.facts:
                label, display_value = _display_value(fact)
                facts.append(
                    ContextSummaryFact(
                        key=fact.key,
                        label=label,
                        category=cast(ContextCategory, fact.category),
                        display_value=display_value,
                        provenance=fact.provenance,
                        verified_at=fact.verified_at,
                        mutable_by_citizen=fact.mutable_by_citizen,
                        used_by=[],
                    )
                )
            missing_facts.extend(group.missing_fact_keys)
        summary = ContextSummary(
            persona_label=persona.display_name,
            synthetic=True,
            purpose=consent.purpose,
            categories=categories,
            facts=facts,
            missing_facts=missing_facts,
            consent_expires_at=_iso(consent.expires_at),
        )
        checked_at = self._now()
        latest = await self.sessions.get(owner_token, context_token, now=checked_at)
        latest_consent = (
            self._active_consent(latest, persona, checked_at) if latest is not None else None
        )
        if (
            latest is None
            or latest.revision != state.revision
            or latest_consent is None
            or latest_consent.consent_id != consent.consent_id
        ):
            raise ApiError(
                409,
                "CONTEXT_CHANGED",
                "Synthetic context changed during this request. Please try again.",
            )
        return summary
