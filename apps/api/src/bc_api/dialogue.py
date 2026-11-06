"""Application-authored conversation, never an escape hatch for generated facts."""

import re
from dataclasses import dataclass
from typing import Literal

from ag_ui.core import RunAgentInput

from bc_api.catalog import CatalogRepository

GREETING_ONLY = re.compile(
    r"(?i)^(?:(?:hi|hello|hey|hiya|howdy)(?:\s+there)?|greetings|"
    r"good\s+(?:morning|afternoon|evening))(?:\s+(?:assistant|friend))?[!,.?]*$"
)
THANKS_ONLY = re.compile(
    r"(?i)^(?:thanks|thank you|thankyou|cheers)(?:\s+(?:very much|so much|a lot))?[!,.?]*$"
)
HELP_ONLY = re.compile(
    r"(?i)^(?:help(?: me)?|i need help|can you help(?: me)?|"
    r"what can you (?:do|help (?:me )?with))[!,.?]*$"
)
MODEL_CLARIFICATIONS = (
    "Which B.C. government service or programme would you like help with?",
    "What would you like to know about that service?",
    "Are you looking for general information, application guidance, or an official contact?",
)
DRIVER_LICENCE = r"\bdriver(?:['\u2019]?s)?\s+licen[cs](?:e|ing)\b"
SOURCE_TOPICS = (
    (
        "bc-content",
        r"\bb\.?c\.?\s+government\b|\bbritish columbia government\b|"
        r"\bprovincial services?\b|\bgovernment services?\b",
    ),
    ("service-bc", r"\bservice ?bc\b|\bgovernment office\b"),
    (
        "icbc",
        rf"\bicbc\b|{DRIVER_LICENCE}|\bbcid\b|\bvehicle\b|\bcar insurance\b",
    ),
    ("bc-housing", r"\bbc housing\b|\brental assistance\b|\bsafer\b|\brent subsidy\b"),
    ("housing-tenancy", r"\btenan(?:t|cy)\b|\blandlord\b|\brent(?:al)?\b|\bhousing\b"),
    (
        "health",
        r"\bmsp\b|\bpharmacare\b|\bhealth coverage\b|\bpublic health\b|"
        r"\bphn\b|\bpersonal health number\b",
    ),
    ("healthlink-bc", r"\bhealthlink\b|\bdoctor\b|\bprimary care\b|\bhealth connect\b"),
    (
        "family-social-supports",
        r"\bchildcare\b|\bchild care\b|\bdisability\b|\bincome assistance\b",
    ),
    ("employment-business", r"\bemployment standards\b|\bbusiness\b|\bemployer\b|\bwages?\b"),
    ("workbc", r"\bworkbc\b|\bcareer\b|\bjob\b|\btraining\b"),
    ("taxes", r"\btax(?:es)?\b|\btax credits?\b|\bexemptions?\b"),
    ("bc-laws", r"\bstatutes?\b|\blegislation\b|\blaws?\b|\bregulations?\b|\blegal\b"),
)
FOLLOW_UP = re.compile(
    r"(?i)\b(?:it|that|this|those|they|them)\b|"
    r"^(?:what (?:should|do) i bring|how do i apply|where (?:can|do) i (?:apply|go)|"
    r"tell me more)[?.!]*$"
)


@dataclass(frozen=True)
class ApplicationReply:
    text: str
    kind: Literal["dialogue", "handoff"] = "dialogue"


def dialogue_reply(text: str) -> ApplicationReply | None:
    normalized = " ".join(text.strip().split())
    if GREETING_ONLY.fullmatch(normalized):
        return ApplicationReply(
            "Hi! What would you like help figuring out about B.C. government services?"
        )
    if THANKS_ONLY.fullmatch(normalized):
        return ApplicationReply("You're welcome. We can take the next step whenever you're ready.")
    if HELP_ONLY.fullmatch(normalized):
        return ApplicationReply(MODEL_CLARIFICATIONS[0])
    return None


def is_model_clarification(text: str) -> bool:
    return " ".join(text.split()) in MODEL_CLARIFICATIONS


def source_topics(text: str) -> list[str]:
    topics = [key for key, pattern in SOURCE_TOPICS if re.search(pattern, text, re.I)]
    if (
        "icbc" in topics
        and "service-bc" not in topics
        and re.search(r"\boffices?\b|\blocations?\b|\bwhere\b", text, re.I)
    ):
        topics.append("service-bc")
    return topics


def search_query_for(
    request: RunAgentInput, catalog: CatalogRepository, journey_id: str | None
) -> str:
    query = request.messages[-1].content
    assert isinstance(query, str)
    if journey_id:
        return f"{catalog.journey(journey_id).title}: {query}"[:512]
    if not source_topics(query) and FOLLOW_UP.search(query):
        for message in reversed(request.messages[:-1]):
            if message.role == "user" and isinstance(message.content, str):
                if dialogue_reply(message.content) is None:
                    return f"{message.content[:256]}\n{query[:255]}"[:512]
    return query[:512]


def source_handoff(query: str, catalog: CatalogRepository) -> ApplicationReply:
    if re.search(r"\brenew(?:al|ing)?\b", query, re.I) and re.search(
        rf"{DRIVER_LICENCE}|\bbcid\b", query, re.I
    ):
        journey = catalog.journey("licence-renewal")
        links = [
            f"[{re.sub(r'[][()<>`!*_\\\\]', '', link.label)}]({link.url})"
            for link in journey.handoffs[:2]
        ]
        return ApplicationReply(
            "I can help you prepare for renewal. If this is a B.C.-issued licence or BCID, "
            "start with ICBC's official renewal and identification guidance:\n\n"
            + "\n\n".join(links)
            + "\n\nThe pilot's preparation guide is a dated snapshot. I don't have current "
            "verified evidence for additional requirements, so confirm those with ICBC. "
            "I cannot renew a licence, book a visit, or take payment here.",
            "handoff",
        )
    sources = {source.id: source for source in catalog.get().sources}
    selected = [sources[key] for key in source_topics(query) if key in sources][:2]
    if not selected and "bc-content" in sources:
        selected = [sources["bc-content"]]
    text = "I don't have current, reviewed source information to answer that reliably."
    if selected:
        links = [
            f"[{re.sub(r'[][()<>`!*_\\\\]', '', source.title)}]({source.url})"
            for source in selected
        ]
        text += " You can check " + " or ".join(links) + " on the official website."
    else:
        text += " Please check the relevant official service, or choose a guided pathway."
    return ApplicationReply(text, "handoff")
