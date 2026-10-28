"""A fail-closed planning boundary. There is deliberately no Web IQ transport."""

from typing import Literal

from bc_api.config import Settings
from bc_api.errors import ApiError
from bc_api.models import JourneyId, WireModel

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
            "zero_query_logging": self.settings.webiq_zero_query_logging_approved,
            "transient_handling": self.settings.webiq_transient_handling_verified,
            # No setting can claim that a reviewed transport has been implemented.
            "reviewed_transport": False,
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
