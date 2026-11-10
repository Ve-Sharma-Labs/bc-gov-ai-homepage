"""Public research policy. Only the explicit research endpoint can invoke providers."""

import hashlib
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Literal

from bc_api.catalog import CatalogRepository
from bc_api.config import Settings
from bc_api.errors import ApiError
from bc_api.models import JourneyId, ResearchAvailability, ResearchCapabilities, WireModel
from bc_api.research_contract import (
    ResearchAction,
    ResearchDescriptor,
    ResearchOffer,
)

TOPICS = {
    "licence-renewal": "ICBC driver licence renewal preparation and official office information",
    "road-test-booking": "ICBC road-test preparation and official booking guidance",
    "rental-assistance": "BC Housing rental assistance official programme guidance",
    "health-coverage": "British Columbia MSP administrative guidance",
    "pharmacare-registration": "British Columbia Fair PharmaCare registration guidance",
    "primary-care": "HealthLink BC Health Connect Registry service navigation",
    "service-bc": "Service BC office services and published opening hours",
}
GEOGRAPHY = {
    "british-columbia": "British Columbia",
    "vancouver": "Vancouver",
    "victoria": "Victoria",
    "kelowna": "Kelowna",
    "kamloops": "Kamloops",
    "prince-george": "Prince George",
}


class PublicResearchTopic(WireModel):
    topic: JourneyId
    geography: Literal[
        "british-columbia", "vancouver", "victoria", "kelowna", "kamloops", "prince-george"
    ] = "british-columbia"

    def query(self) -> str:
        return f"{TOPICS[self.topic]} — {GEOGRAPHY[self.geography]}"


class WebIqPolicy:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def unmet_gates(self) -> tuple[str, ...]:
        requirements = {
            "enabled": self.settings.webiq_enabled,
            "app_id": self.settings.webiq_app_id,
            "privacy_review": self.settings.webiq_privacy_approval_id,
            "terms_review": self.settings.webiq_terms_approval_id,
            "egress_review": self.settings.webiq_egress_approved,
            "query_logging_review": self.settings.webiq_zero_query_logging_approved
            or self.settings.webiq_public_query_logging_approved,
            "transient_handling": self.settings.webiq_transient_handling_verified,
            "release_review": self.settings.webiq_release_approval_id,
            "source_review": self.settings.webiq_source_approval_id,
            "approved_paths": self.settings.webiq_sources,
        }
        return tuple(key for key, satisfied in requirements.items() if not satisfied)

    @property
    def enabled(self) -> bool:
        return not self.unmet_gates

    async def research(self, topic: PublicResearchTopic) -> None:
        raise ApiError(
            503,
            "WEBIQ_DISABLED",
            "Public-web research is planned, not enabled. Use the curated official sources.",
        )


def page_hash(value: str | None) -> str:
    if value is None or not re.fullmatch(r"[a-zA-Z0-9_-]{16,128}", value):
        raise ApiError(422, "RESEARCH_PAGE_REQUIRED", "Open research from the current answer.")
    return hashlib.sha256(value.encode()).hexdigest()


def research_gates(settings: Settings, action: ResearchAction) -> tuple[str, ...]:
    price, limit = settings.research_allowance(action)
    common = {
        "answer_agent": settings.foundry_research_agent and settings.foundry_project_endpoint,
        "public_mode": not settings.local_evidence_evaluation_enabled,
        "metering": price > 0 and limit >= price and settings.research_daily_run_limit > 0,
        "reserved_chat_capacity": settings.api_max_concurrent_runs > 1,
    }
    if action == "web-check":
        missing = WebIqPolicy(settings).unmet_gates
    else:
        common.update(
            enabled=settings.foundry_iq_enabled,
            search=settings.search_configured,
            knowledge_base=settings.foundry_iq_knowledge_base,
            knowledge_source=settings.foundry_iq_knowledge_source,
            planning_model=settings.foundry_iq_model_deployment
            and settings.foundry_iq_model_name
            and settings.azure_openai_endpoint,
            preview_review=settings.foundry_iq_preview_approval_id,
            contract_review=settings.foundry_iq_contract_approval_id,
            budget_review=settings.foundry_iq_budget_approval_id,
        )
        missing = ()
    return (*missing, *(key for key, value in common.items() if not value))


def require_research(settings: Settings, action: ResearchAction) -> None:
    if research_gates(settings, action):
        raise ApiError(
            503,
            "RESEARCH_DISABLED",
            "This optional research is not approved or configured. "
            "Your original answer is unchanged.",
        )


def research_capabilities(settings: Settings) -> ResearchCapabilities:
    def availability(action: ResearchAction) -> ResearchAvailability:
        available = not research_gates(settings, action)
        return ResearchAvailability(
            available=available,
            preview=action == "corpus-explore",
            reason=(
                "Optional preview research over approved indexed sources."
                if action == "corpus-explore"
                else "Optional research on approved public pages."
            )
            if available
            else "Unavailable pending configuration and separate release approval.",
        )

    return ResearchCapabilities(
        foundry_iq=availability("corpus-explore"), web_iq=availability("web-check")
    )


def research_query(descriptor: ResearchDescriptor, geography: str) -> str:
    return "; ".join(TOPICS[topic] for topic in descriptor.topics) + " - " + GEOGRAPHY[geography]


def make_research_offer(
    *,
    settings: Settings,
    catalog: CatalogRepository,
    run_id: str,
    thread_id: str,
    parent_message_id: str,
    page: str,
    created: float,
    topics: list[JourneyId],
) -> tuple[ResearchDescriptor, ResearchOffer] | None:
    actions: list[ResearchAction] = [
        action for action in ("corpus-explore", "web-check") if not research_gates(settings, action)
    ]
    if not actions or not topics or not page:
        return None
    topics = list(dict.fromkeys(topics))[:3]
    source_ids = sorted(
        {
            source_id
            for topic in topics
            for source_id in catalog.journey(topic).source_ids
            if any(
                source.id == source_id and source.status in ("available", "limited")
                for source in catalog.get().sources
            )
        }
    )
    if not source_ids:
        return None
    expires = datetime.now(UTC) + timedelta(seconds=max(0, 600 - (time.monotonic() - created)))
    descriptor = ResearchDescriptor(
        page_hash=page,
        thread_id=thread_id,
        parent_message_id=parent_message_id,
        topics=topics,
        source_ids=source_ids,
        expires_at=expires,
    )
    return descriptor, ResearchOffer(
        parent_run_id=run_id,
        parent_message_id=parent_message_id,
        thread_id=thread_id,
        topics=topics,
        actions=actions,
        expires_at=expires,
    )
