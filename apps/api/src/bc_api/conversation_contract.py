"""Strict AI proposals are data; only the application authorizes a conversation turn."""

import json
import logging
from collections import Counter
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StrictBool, ValidationError, model_validator

from bc_api.conversation_grounding import AnswerTopic, ProgrammeId
from bc_api.models import (
    ConversationFactKey,
    DemoPersonaId,
    Identifier,
    JourneyId,
    PageSummary,
    WireModel,
    require_unique,
)
from bc_api.task_assistance import TaskAction, TaskSnapshot

ConversationGoal = Literal[
    "licence-renewal",
    "road-test-booking",
    "rental-assistance",
    "health-coverage",
    "pharmacare-registration",
    "primary-care",
    "service-bc",
    "motorcycle",
    "tenancy",
    "job-loss",
    "caregiving",
    "disability",
    "business",
    "bceid",
    "taxes",
    "laws",
    "general",
    "unknown",
]
AnswerValue = Literal[
    "bc",
    "other",
    "car",
    "motorcycle",
    "rent",
    "tenancy",
    "housing",
    "msp",
    "pharmacare",
    "both",
    "find-provider",
    "contact-provider",
    "licensing",
    "income-support",
    "identity",
    "general-service",
    "under-19",
    "19-or-older",
    "yes",
    "no",
    "moving",
    "adult",
    "child",
    "work",
]
InformationFocus = Literal[
    "overview",
    "requirements",
    "documents",
    "fees",
    "timing",
    "locations",
    "application",
    "comparison",
    "contact",
]
FactStatus = Literal["provided", "unknown", "declined", "disputed"]
Subject = Literal["you", "someone-else", "unspecified"]
ServiceQuestionKey = Literal["licence-route", "guardianship-scope", "disability-kind"]
ServiceAnswerValue = Literal[
    "renew-original",
    "get-bc",
    "adult",
    "child",
    "provincial-assistance",
    "provincial-designation",
    "federal-benefits",
    "workplace-accommodation",
    "other",
]


class AnswerState(WireModel):
    value: str | None
    status: FactStatus

    @model_validator(mode="after")
    def explicit_answer(self) -> Self:
        if (self.status == "provided") != (self.value is not None):
            raise ValueError("Only provided answers may have a value.")
        return self


class ProposedFact(AnswerState):
    key: ConversationFactKey
    value: AnswerValue | None
    quote: Annotated[str, Field(min_length=1, max_length=160)]


class ProposedServiceAnswer(AnswerState):
    key: ServiceQuestionKey
    value: ServiceAnswerValue | None
    quote: Annotated[str, Field(min_length=1, max_length=160)]


class ConversationProposal(WireModel):
    goal: ConversationGoal
    intent: Literal["task", "information", "social", "ambiguous"]
    subject: Subject
    action: Literal["ask", "guide", "answer", "handoff", "social"]
    question_key: ConversationFactKey | None
    candidates: list[ConversationGoal] = Field(
        max_length=3,
        description="Empty for a known goal. Only list alternatives for an intent question.",
    )
    updates: list[ProposedFact] = Field(
        max_length=8,
        description="Only facts explicitly stated in currentMessage. Missing information "
        "is NOT an update. Quote an exact substring including the user's original spelling.",
    )
    focus: InformationFocus
    tone: Literal["warm", "supportive", "thanks", "correction", "neutral"]
    task_action: TaskAction = "continue"
    step_id: Identifier | None = None
    progress_quote: Annotated[str, Field(min_length=1, max_length=160)] | None = None
    municipality: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    change_task: StrictBool = False
    service_answer: ProposedServiceAnswer | None = None

    @model_validator(mode="after")
    def unique_proposal(self) -> Self:
        require_unique([fact.key for fact in self.updates], "Proposed facts")
        require_unique(self.candidates, "Candidate goals")
        if self.question_key is not None and self.action != "ask":
            raise ValueError("Only ask can propose a question.")
        if self.candidates and (self.action != "ask" or self.question_key is not None):
            raise ValueError("Candidates are only for an intent question.")
        return self


class GroundedConversationProposal(ConversationProposal):
    programme_id: ProgrammeId | None = None
    answer_question: StrictBool = False
    answer_topics: list[AnswerTopic] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def distinct_answer_topics(self) -> Self:
        require_unique(self.answer_topics, "Answer topics")
        if self.answer_topics and not self.answer_question:
            raise ValueError("Answer topics require a current information request.")
        return self


def parse_grounded_proposal(raw: str) -> GroundedConversationProposal:
    payload = json.loads(raw)
    if isinstance(payload, dict):
        if payload.get("action") in ("guide", "answer", "handoff", "social"):
            payload["questionKey"], payload["candidates"] = None, []
        elif payload.get("action") == "ask" and payload.get("questionKey") is not None:
            payload["candidates"] = []
        if payload.get("answerQuestion") is False:
            payload["answerTopics"] = []
        for key in ("answerTopics", "candidates"):
            values = payload.get(key)
            if (
                isinstance(values, list)
                and len(values) <= 3
                and all(isinstance(value, str) for value in values)
            ):
                payload[key] = list(dict.fromkeys(values))
        withheld = False
        updates = payload.get("updates")
        if isinstance(updates, list) and len(updates) <= 8:
            checked = []
            for update in updates:
                try:
                    checked.append(ProposedFact.model_validate(update))
                except ValidationError:
                    withheld = True
            counts = Counter(update.key for update in checked)
            withheld |= any(count > 1 for count in counts.values())
            payload["updates"] = [
                update.model_dump(by_alias=True) for update in checked if counts[update.key] == 1
            ]
        if payload.get("serviceAnswer") is not None:
            try:
                ProposedServiceAnswer.model_validate(payload["serviceAnswer"])
            except ValidationError:
                payload["serviceAnswer"] = None
                withheld = True
        if withheld:
            logging.getLogger("bc_api.conversation").warning(
                "Unverifiable optional fact proposals withheld; no answer was assumed."
            )
    return GroundedConversationProposal.model_validate(payload)


class ConversationFact(WireModel):
    key: ConversationFactKey
    label: Annotated[str, Field(min_length=1, max_length=100)]
    value: AnswerValue | None
    display_value: Annotated[str, Field(min_length=1, max_length=100)]
    status: FactStatus
    subject: Subject
    provenance: Literal["citizen-answer"] = "citizen-answer"
    personal: StrictBool


class ConversationQuestion(WireModel):
    id: Identifier
    kind: Literal["intent", "context"]
    fact_key: ConversationFactKey | None
    text: Annotated[str, Field(min_length=1, max_length=500)]
    reason: Annotated[str, Field(min_length=1, max_length=500)]
    choices: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(max_length=5)
    candidates: list[ConversationGoal] = Field(default_factory=list, max_length=3)
    personal: StrictBool = False


class ConversationSummary(PageSummary):
    # A turn is staged atomically and revalidated before storage or emission.
    model_config = ConfigDict(validate_assignment=False)
    version: Literal[1] = 1
    notice_version: Literal["ai-conversation-v1"] = "ai-conversation-v1"
    goal: ConversationGoal
    goal_label: Annotated[str, Field(min_length=1, max_length=100)]
    subject: Subject
    phase: Literal["clarify", "guide", "answer", "handoff", "social"]
    question_count: Annotated[int, Field(ge=0, le=3)]
    question: ConversationQuestion | None
    facts: list[ConversationFact] = Field(max_length=11)
    share_context: StrictBool
    journey_id: JourneyId | None
    suggested_demo_id: DemoPersonaId | None
    limitation: Literal[
        "none", "uncertain-intent", "missing-context", "source-coverage", "outside-scope"
    ]
    decision_origin: Literal["model", "application"]

    @model_validator(mode="after")
    def coherent_context(self) -> Self:
        require_unique([fact.key for fact in self.facts], "Conversation facts")
        if not self.share_context and any(fact.personal for fact in self.facts):
            raise ValueError("Personal context requires sharing.")
        if (self.phase == "clarify") != (self.question is not None):
            raise ValueError("Clarification requires one pending question.")
        if self.question and self.question.personal and not self.share_context:
            raise ValueError("Do not ask personal questions without optional sharing.")
        return self


class ConversationControlResponse(WireModel):
    summary: ConversationSummary
    task: TaskSnapshot
    notice: Annotated[str, Field(min_length=1, max_length=500)]
