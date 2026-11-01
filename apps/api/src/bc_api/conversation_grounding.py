"""Public programme vocabulary and place resolution, not personal eligibility rules."""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from bc_api.discovery_content import normalize

ProgrammeId = Literal[
    "licence-renewal",
    "ei-regular",
    "guardianship-adult",
    "guardianship-child",
    "disability-assistance",
    "pwd-designation",
    "comparison",
]

COMMON_TOPICS: tuple[AnswerTopic, ...] = (
    "overview",
    "requirements",
    "additional-items",
    "documents",
    "fees",
    "timing",
    "locations",
    "application",
    "contact",
)
AnswerTopic = Literal[
    "overview",
    "requirements",
    "additional-items",
    "documents",
    "fees",
    "timing",
    "locations",
    "application",
    "contact",
    "missing-roe",
    "existing-claim",
    "reporting",
    "professional-sections",
    "legal-help",
]


@dataclass(frozen=True)
class Programme:
    goal: str
    title: str
    query: str
    source_ids: tuple[str, ...]
    handoff: str
    topics: tuple[AnswerTopic, ...]

    @property
    def allowed_topics(self) -> tuple[AnswerTopic, ...]:
        return tuple(dict.fromkeys((*COMMON_TOPICS, *self.topics)))


PROGRAMMES: dict[ProgrammeId, Programme] = {
    "licence-renewal": Programme(
        "licence-renewal",
        "Renew a B.C. driver's licence",
        "ICBC driver licence renewal",
        ("icbc",),
        "https://www.icbc.com/driver-licensing/getting-licensed/Renew-your-licence-or-ID",
        (
            "overview",
            "requirements",
            "additional-items",
            "documents",
            "fees",
            "timing",
            "locations",
            "application",
            "contact",
        ),
    ),
    "ei-regular": Programme(
        "job-loss",
        "Employment Insurance (EI) regular benefits",
        "Canada Employment Insurance EI regular benefits",
        ("employment-insurance",),
        "https://www.canada.ca/en/services/benefits/ei/ei-regular-benefit/apply.html",
        (
            "overview",
            "requirements",
            "documents",
            "timing",
            "application",
            "contact",
            "missing-roe",
            "existing-claim",
            "reporting",
        ),
    ),
    "guardianship-adult": Programme(
        "caregiving",
        "Adult guardianship information",
        "British Columbia adult guardianship committeeship preparation legal help",
        ("family-social-supports", "public-guardian-trustee"),
        "https://www2.gov.bc.ca/gov/content/family-social-supports/seniors/"
        "financial-legal-matters/substitute-decision-making",
        ("overview", "requirements", "documents", "application", "contact", "legal-help"),
    ),
    "guardianship-child": Programme(
        "caregiving",
        "Child guardianship information",
        "British Columbia child guardianship parents non parents application legal help",
        ("child-guardianship",),
        "https://www2.gov.bc.ca/gov/content/life-events/divorce/family-justice/"
        "family-law/parenting-apart/am-i-a-guardian",
        ("overview", "requirements", "documents", "application", "contact", "legal-help"),
    ),
    "disability-assistance": Programme(
        "disability",
        "B.C. disability assistance",
        "British Columbia disability assistance application",
        ("disability-assistance",),
        "https://www2.gov.bc.ca/gov/content/family-social-supports/"
        "services-for-people-with-disabilities/disability-assistance",
        (
            "overview",
            "requirements",
            "documents",
            "application",
            "contact",
            "professional-sections",
        ),
    ),
    "pwd-designation": Programme(
        "disability",
        "Persons with Disabilities (PWD) designation",
        "British Columbia Persons with Disabilities PWD designation application",
        ("disability-assistance",),
        "https://www2.gov.bc.ca/gov/content/family-social-supports/"
        "services-for-people-with-disabilities/disability-assistance",
        (
            "overview",
            "requirements",
            "documents",
            "application",
            "contact",
            "professional-sections",
        ),
    ),
}

TOPIC_QUERIES: dict[AnswerTopic, str] = {
    "overview": "purpose and how to start",
    "requirements": "published requirements and exceptions",
    "additional-items": "what else to prepare besides accepted identification, "
    "including the driver licence renewal fee and visit preparation",
    "documents": "documents to prepare privately",
    "fees": "published fees and accepted payment methods",
    "timing": "application timing deadlines and exceptions",
    "locations": "official office services and locations",
    "application": "how to apply next steps",
    "contact": "official contact and application help",
    "missing-roe": "apply without record of employment ROE missing documents",
    "existing-claim": "reactivating existing claim versus new claim",
    "reporting": "after applying reports and checking claim",
    "professional-sections": "practitioner medical and assessor sections application help",
    "legal-help": "qualified legal help and official process",
    "comparison": "compare programme purpose and application routes",
}


def programme_handoffs(programme: ProgrammeId | None) -> tuple[str, ...]:
    spec = PROGRAMMES.get(programme)
    if spec is None:
        return ()
    if programme == "ei-regular":
        return (
            spec.handoff,
            "https://www.canada.ca/en/services/benefits/apply-privacy.html",
            "https://www.canada.ca/en/employment-social-development/"
            "corporate/contact/ei-individual.html",
            "https://www.canada.ca/en/employment-social-development/services/my-account.html",
        )
    return (spec.handoff,)


def public_queries(programme: ProgrammeId, topics: list[AnswerTopic]) -> tuple[str, ...]:
    spec = PROGRAMMES[programme]
    selected = list(dict.fromkeys(topics or ["overview"]))
    if len(selected) > 3 or any(topic not in spec.allowed_topics for topic in selected):
        raise ValueError("The requested topics do not belong to this programme.")
    return tuple(
        f"{spec.query} "
        + (
            "additional preparation requirements beyond items already discussed"
            if topic == "additional-items" and programme != "licence-renewal"
            else TOPIC_QUERIES[topic]
        )
        for topic in selected
    )


def explicit_ei_rejection(text: str) -> bool:
    value = normalize(text)
    return bool(
        re.search(
            r"\b(?:not|don't|do not|isn't|rather than|instead of)\s+"
            r"(?:want(?:ing)?(?: to)?\s+|need(?: to)?\s+|mean\s+|asking(?: about)?\s+|"
            r"apply(?:ing)? for\s+|claim\s+|about\s+|my\s+|the\s+)*"
            r"(?:ei|employment insurance)\b",
            value,
        )
    )


def explicit_ei_request(text: str) -> bool:
    return bool(
        re.search(r"\b(?:ei|employment insurance)\b", normalize(text))
    ) and not explicit_ei_rejection(text)


@dataclass(frozen=True)
class PlaceResolution:
    name: str | None
    candidates: tuple[str, ...] = ()
    corrected: bool = False


def resolve_municipality(text: str, names: set[str]) -> PlaceResolution:
    """Resolve only approved names; unknown/ambiguous places are never invented."""
    value = normalize(text).strip(" .!?")
    if not value or len(value) > 100 or re.search(r"\d|[^\w .'-]", value):
        return PlaceResolution(None)
    canonical = {normalize(name): name for name in names}
    if value in canonical:
        return PlaceResolution(canonical[value])
    ranked = sorted(
        ((SequenceMatcher(None, value, key).ratio(), name) for key, name in canonical.items()),
        reverse=True,
    )
    plausible = [(score, name) for score, name in ranked if score >= 0.84]
    if not plausible:
        return PlaceResolution(None)
    score, name = plausible[0]
    if score >= 0.9 and (len(plausible) == 1 or score - plausible[1][0] >= 0.08):
        return PlaceResolution(name, corrected=True)
    return PlaceResolution(None, tuple(name for _, name in plausible[:3]))
