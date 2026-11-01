"""Bounded, application-authored discovery before source-backed service guidance."""

import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ag_ui.core import RunAgentInput

from bc_api.catalog import CatalogRepository
from bc_api.config import Settings
from bc_api.context_flows.guardianship import URGENT_SAFETY_TEXT
from bc_api.dialogue import (
    FOLLOW_UP,
    ApplicationReply,
    dialogue_reply,
    source_handoff,
    source_topics,
)
from bc_api.discovery_content import (
    DECLINED,
    DIRECT_FACT,
    GENERAL,
    GOALS,
    QUESTIONS,
    UNCERTAIN,
    URGENT,
    detect_goal,
    normalize,
    question_copy,
)
from bc_api.discovery_store import DiscoveryStore, StoredDiscovery, discovery_ref
from bc_api.errors import ApiError
from bc_api.input import parse_options
from bc_api.models import (
    DiscoveryCommand,
    DiscoveryFact,
    DiscoveryFactKey,
    DiscoveryGoalId,
    DiscoveryQuestion,
    DiscoverySummary,
    PathwaySuggestion,
    PreparationArtifact,
)
from bc_api.security import Run

_PRIVATE_NUMBER = re.compile(r"\b(?:\d[ -]?){8,}\b")
_OTHER_PERSON = re.compile(
    r"\b(?:for (?:my|our|a) (?:child|son|daughter|parent|mother|father|partner|friend)|"
    r"my (?:son|daughter|child|parent|mother|father|partner) (?:is|needs|wants)|"
    r"someone else|helping|care for|caring for)\b",
    re.I,
)


def _fact(key: DiscoveryFactKey, value: str | None, status: str = "provided") -> DiscoveryFact:
    return DiscoveryFact.model_validate(
        {
            "key": key,
            "label": QUESTIONS[key].label,
            "value": value,
            "status": status,
            "provenance": "citizen-answer",
        }
    )


def _answer(key: DiscoveryFactKey, text: str, goal_id: DiscoveryGoalId) -> DiscoveryFact | None:
    value = normalize(text).strip(" .!?")
    if DECLINED.search(value):
        return _fact(key, None, "declined")
    if UNCERTAIN.search(value):
        return _fact(key, None, "unknown")
    if key == "age":
        value = re.sub(r"^(?:i(?:'ll| will) be|i(?:'m| am)|about|around)\s+", "", value)
        value = re.sub(r"\s+(?:years? old|next year|when i start)$", "", value)
        if re.fullmatch(r"\d{1,3}", value) and 1 <= int(value) <= 120:
            return _fact(key, str(int(value)))
        match = re.fullmatch(r"(\d{1,3})\s*(?:-|to)\s*(\d{1,3})", value)
        if match and 1 <= int(match[1]) <= int(match[2]) <= 120:
            return _fact(key, f"{int(match[1])} to {int(match[2])}")
        if value in ("under 19", "19 or older"):
            return _fact(key, value.capitalize())
    elif key == "licence-experience":
        if goal_id == "motorcycle" and re.search(
            r"\b(?:car|class [457]|driver's) licen[cs]e\b", value
        ):
            return None
        if re.fullmatch(
            r"(?:no|nope|my first(?: one)?|first(?: one)?|not yet)", value
        ) or re.search(
            r"\b(?:first (?:motorcycle )?licen[cs]e|never (?:had|held) (?:one|a licence))\b",
            value,
        ):
            return _fact(key, "First licence of this kind")
        if re.fullmatch(
            r"(?:yes|yep|yes,? i do|i do|i already have one|already licensed)", value
        ) or re.search(r"\b(?:already (?:have|hold)|have a) (?:motorcycle )?licen[cs]e\b", value):
            return _fact(key, "Already has this kind of licence")
    elif key == "timeframe":
        if re.search(r"\bnext year\b", value):
            return _fact(key, "Next year")
        if re.search(r"\b(?:soon|now|this (?:week|month)|right away)\b", value):
            return _fact(key, "Soon")
        if re.search(r"\b(?:later|further ahead|in the future)\b", value):
            return _fact(key, "Later")
    elif key == "phn-status":
        if re.fullmatch(r"(?:yes|yep|yes,? i do|i do|i have one)", value):
            return _fact(key, "Yes")
        if re.fullmatch(
            r"(?:no|nope|no,? i don't|not yet|i don't|i do not|i don't have one)", value
        ):
            return _fact(key, "No")
    elif key == "bc-residency":
        if re.search(r"\b(?:planning (?:a|to) move|moving to|not (?:yet )?in)\b", value):
            return _fact(key, "Planning a move")
        if re.search(
            r"\b(?:live|living|already|currently) in (?:b\.?c\.?|british columbia)\b", value
        ):
            return _fact(key, "Living in B.C.")
    elif key == "support-for":
        if re.fullmatch(r"(?:an? )?adult", value):
            return _fact(key, "An adult")
        if re.fullmatch(r"(?:a )?(?:child|minor)", value):
            return _fact(key, "A child")
    elif key == "priority":
        if value == "both" and "Both" in GOALS[goal_id].priorities:
            return _fact(key, "Both")
        if goal_id in ("rent", "job-loss"):
            if goal_id == "rent" and re.search(r"\b(?:tenancy|tenant|landlord|rights)\b", value):
                return _fact(key, "Tenancy rights")
            if re.search(
                r"\b(?:pay(?:ing)?|afford|help with|help for|worried about).*\brent\b", value
            ):
                return _fact(key, "Help paying rent")
            if value in ("rent", "help with rent", "help paying rent"):
                return _fact(key, "Help paying rent")
            if goal_id == "job-loss" and re.search(
                r"\b(?:find(?:ing)? (?:work|a job)|job search)\b", value
            ):
                return _fact(key, "Finding work")
            if goal_id == "rent" and re.search(r"\bfind(?:ing)? (?:housing|a home)\b", value):
                return _fact(key, "Finding housing")
        if goal_id == "caregiving":
            if re.search(r"\b(?:legal|guardianship|power of attorney)\b", value):
                return _fact(key, "Legal planning")
            if re.search(r"\bpractical (?:help|support)\b", value):
                return _fact(key, "Practical support")
        if goal_id == "disability":
            if re.search(r"\b(?:application|applying|apply)\b", value):
                return _fact(key, "Application guidance")
            if re.search(r"\b(?:work|daily (?:life|support))\b", value):
                return _fact(key, "Work and daily support")
    return None


def _volunteered(
    text: str, goal_id: DiscoveryGoalId, *, someone_else: bool
) -> dict[DiscoveryFactKey, DiscoveryFact]:
    facts: dict[DiscoveryFactKey, DiscoveryFact] = {}
    allowed = GOALS[goal_id].questions
    for key in ("timeframe", "priority", "bc-residency"):
        if key == "bc-residency" and someone_else:
            continue
        if key in allowed and (fact := _answer(key, text, goal_id)) is not None:
            if fact.status == "provided":
                facts[key] = fact
    if "age" in allowed:
        pattern = (
            r"\b(?:my (?:son|daughter|child|partner)|they|he|she) (?:is|will be) (\d{1,3})\b"
            if someone_else
            else r"\bi(?:'m| am|'ll be| will be) (\d{1,3})\b"
        )
        ages = set(re.findall(pattern, text, re.I))
        if len(ages) > 1:
            facts["age"] = _fact("age", None, "disputed")
        elif ages:
            fact = _answer("age", next(iter(ages)), goal_id)
            if fact is not None:
                facts["age"] = fact
    if not someone_else and "licence-experience" in allowed:
        if re.search(r"\bi (?:already (?:have|hold)|have a).*motorcycle licen[cs]e\b", text, re.I):
            fact = _answer("licence-experience", text, goal_id)
            if fact is not None:
                facts["licence-experience"] = fact
        elif re.search(
            r"\b(?:my first (?:motorcycle )?licen[cs]e|never (?:had|held) "
            r"(?:a )?(?:motorcycle )?licen[cs]e)\b",
            text,
            re.I,
        ):
            facts["licence-experience"] = _fact("licence-experience", "First licence of this kind")
    if not someone_else and "phn-status" in allowed:
        match = re.search(
            r"\bi (have|already have|don't have|do not have) (?:a |an? )?"
            r"(?:phn|personal health number)\b",
            text,
            re.I,
        )
        if match:
            facts["phn-status"] = _fact(
                "phn-status", "No" if "not" in match[1] or "don't" in match[1] else "Yes"
            )
    return facts


def _public_query(
    text: str, goal_id: DiscoveryGoalId | None, previous_query: str | None = None
) -> str | None:
    if goal_id:
        query = GOALS[goal_id].public_query
    else:
        topics = source_topics(text)
        if not topics:
            if previous_query and FOLLOW_UP.search(text):
                query = previous_query
            else:
                return None
        else:
            query = "B.C. public service information " + " ".join(topics)
    # Only allowlisted intent terms, never citizen answers, reach retrieval or embeddings.
    for pattern, intent in (
        (r"\b(?:fees?|costs?|prices?|how much)\b", "published fees"),
        (r"\b(?:deadline|when|how long)\b", "published timing"),
        (r"\b(?:apply|application|register)\b", "application preparation"),
        (r"\b(?:hours|office|location|where)\b", "official locations and hours"),
        (r"\b(?:what is|what are|explain|define)\b", "overview and purpose"),
        (r"\b(?:phn|personal health number)\b", "Personal Health Number purpose"),
    ):
        if re.search(pattern, text, re.I):
            if intent not in query:
                query += " " + intent
    return query[:512]


@dataclass
class DiscoveryRun:
    ref: str
    base_revision: int
    summary: DiscoverySummary | None = None
    state: StoredDiscovery | None = None
    reply: ApplicationReply | None = None
    public_query: str | None = None
    artifacts: list[PreparationArtifact] = field(default_factory=list)


class DiscoveryService:
    def __init__(
        self, settings: Settings, catalog: CatalogRepository, store: DiscoveryStore
    ) -> None:
        self.settings = settings
        self.catalog = catalog
        self.store = store
        self._runs: dict[str, list[Run]] = {}

    def ensure_available(self) -> None:
        if not self.settings.conversation_discovery_enabled:
            raise ApiError(
                503,
                "DISCOVERY_DISABLED",
                "Context-first conversation is not enabled. General guidance is still available.",
            )

    async def summary(self, owner: str, page: str | None) -> DiscoverySummary | None:
        self.ensure_available()
        state = await self.store.get(discovery_ref(owner, page))
        return state.summary if state else None

    async def clear(self, owner: str, page: str | None) -> None:
        ref = discovery_ref(owner, page)
        for run in self._runs.pop(ref, []):
            run.cancellation.set()
        await self.store.clear(ref)

    def track(self, plan: DiscoveryRun, run: Run) -> None:
        self._runs.setdefault(plan.ref, []).append(run)

    def untrack(self, plan: DiscoveryRun, run: Run) -> None:
        remaining = [item for item in self._runs.get(plan.ref, []) if item is not run]
        if remaining:
            self._runs[plan.ref] = remaining
        else:
            self._runs.pop(plan.ref, None)

    async def assert_current(self, plan: DiscoveryRun) -> None:
        current = await self.store.get(plan.ref)
        revision = current.summary.revision if current else 0
        if revision != plan.base_revision:
            raise ApiError(
                409,
                "DISCOVERY_CHANGED",
                "Your context changed. Refresh it before sending another answer.",
            )

    async def commit(self, plan: DiscoveryRun) -> None:
        await self.assert_current(plan)
        if plan.state is not None:
            if not await self.store.save(plan.ref, plan.base_revision, plan.state):
                raise ApiError(409, "DISCOVERY_CHANGED", "Your context changed. Please refresh it.")
            plan.base_revision = plan.state.summary.revision

    def _plan(self, summary: DiscoverySummary, prefix: str = "") -> DiscoveryRun:
        goal_id = summary.goal_id
        result = DiscoveryRun("", 0, summary=summary)
        if goal_id is None:
            result.reply = ApplicationReply(
                prefix + "What would you like help figuring out? You can start with your goal."
            )
            return result
        goal = GOALS[goal_id]
        facts = {fact.key: fact for fact in summary.facts}
        priority = facts.get("priority")
        journeys = goal.journeys
        source_ids = goal.source_ids
        if (
            goal_id == "rent"
            and priority
            and priority.value in ("Tenancy rights", "Finding housing")
        ):
            journeys = ()
            if priority.value == "Tenancy rights":
                source_ids = ("housing-tenancy",)
        if goal_id == "job-loss" and priority and priority.value in ("Help paying rent", "Both"):
            journeys = ("rental-assistance",)
            if priority.value == "Help paying rent":
                source_ids = ("bc-housing",)
        summary.suggestions = [
            PathwaySuggestion(
                journey_id=journey,
                reason=f"An optional preparation path for {goal.label.lower()}, "
                "not a decision about eligibility.",
            )
            for journey in journeys
        ]
        summary.suggested_demo_id = goal.demo_id
        for journey_id in journeys:
            plan = self.catalog.plan(journey_id)
            result.artifacts.append(
                PreparationArtifact(
                    id=f"discovery-{summary.revision}-{journey_id}",
                    journey=plan.journey,
                    sources=plan.sources,
                )
            )
        missing = any(fact.status != "provided" for fact in summary.facts)
        text = prefix + "Here's a starting point. "
        if goal_id == "motorcycle":
            licence = facts.get("licence-experience")
            if licence and licence.value == "Already has this kind of licence":
                text += (
                    "You mentioned already having a motorcycle licence. "
                    "Let's focus on preparing for the purchase "
                    "and the questions to check with ICBC. "
                )
            elif licence and licence.value == "First licence of this kind":
                text += "You're looking at your first motorcycle licence, rather than a renewal. "
            text += (
                "We can organize your motorcycle planning around licensing, learning to ride, "
                "and insurance and ownership costs.\n\n"
                "I don't have reviewed motorcycle-specific rules here, so I won't guess "
                "about age requirements, fees, or which licence you can get. "
                "Check those details with ICBC before making a decision."
            )
        elif result.artifacts:
            if goal_id in ("health", "pharmacare", "primary-care"):
                phn = facts.get("phn-status")
                if phn and phn.value == "No":
                    text += (
                        "You said you don't have a PHN. Keep that as a question for the "
                        "official service; there's no need to enter any number here. "
                    )
                residency = facts.get("bc-residency")
                if residency and residency.value == "Planning a move":
                    text += (
                        "We'll treat this as preparation for your move, not existing enrolment. "
                    )
            text += (
                "The preparation guide below is a reviewed starting point, not a decision "
                "about your eligibility. You can choose a pathway or keep exploring here."
            )
        else:
            text += (
                "Let's use the official service as the next step rather than guess about "
                "requirements this preview hasn't reviewed."
            )
        if missing:
            text += "\n\nWe'll keep anything you skipped or weren't sure about general."
        sources = {source.id: source for source in self.catalog.get().sources}
        links = [
            f"[{re.sub(r'[][()<>`!*_\\]', '', sources[key].title)}]({sources[key].url})"
            for key in source_ids
            if key in sources
        ]
        if links:
            text += "\n\nOfficial starting points: " + " | ".join(links) + "."
        text += (
            "\n\nNothing has been submitted or booked. "
            "You can change the context or explore another option."
        )
        result.reply = ApplicationReply(text, "handoff")
        return result

    async def prepare(self, owner: str, page: str | None, request: RunAgentInput) -> DiscoveryRun:
        self.ensure_available()
        options = parse_options(request.forwarded_props)
        command = options.discovery
        if options.version != 4 or command is None:
            raise ValueError("Discovery requires the version 4 contract.")
        text = request.messages[-1].content
        assert isinstance(text, str)
        if _PRIVATE_NUMBER.search(text):
            raise ApiError(
                422,
                "PERSONAL_DATA_NOT_SUPPORTED",
                "Please leave out ID numbers and contact details. "
                "A short category or age range is enough.",
            )
        ref = discovery_ref(owner, page)
        current = await self.store.get(ref)
        revision = current.summary.revision if current else 0
        if current and current.summary.thread_id != request.thread_id:
            raise ApiError(
                409, "DISCOVERY_CHANGED", "Start over before changing this conversation."
            )
        fingerprint = hashlib.sha256(
            json.dumps([command.model_dump(), normalize(text)], sort_keys=True).encode()
        ).hexdigest()
        if (
            current
            and command.revision == current.previous_revision
            and fingerprint == current.input_hash
            and current.reply is not None
        ):
            replay = (
                self._plan(current.summary.model_copy(deep=True))
                if current.summary.phase == "plan"
                else DiscoveryRun("", 0)
            )
            replay.ref, replay.base_revision = ref, revision
            replay.summary = current.summary
            replay.reply = ApplicationReply(current.reply, current.reply_kind)
            return replay
        if command.revision != revision:
            raise ApiError(
                409 if current else 410,
                "DISCOVERY_CHANGED" if current else "DISCOVERY_EXPIRED",
                "Your context changed or expired. Refresh it or start over before answering.",
            )
        normalized = normalize(text)
        goal_id = detect_goal(normalized)
        if current is not None:
            current_goal = current.summary.goal_id
            pending = current.summary.question
            answers_pending = (
                pending is not None
                and current_goal is not None
                and not DIRECT_FACT.search(normalized)
                and _answer(pending.fact_key, normalized, current_goal) is not None
            )
            explicit_topics = set(source_topics(normalized))
            different_public_topic = (
                current_goal is not None
                and explicit_topics
                and not explicit_topics.intersection(GOALS[current_goal].source_ids)
            )
            if command.action != "respond" or answers_pending:
                goal_id = current_goal
            elif goal_id is None and not different_public_topic:
                goal_id = current_goal
        now = datetime.now(UTC)
        summary = (
            current.summary.model_copy(deep=True)
            if current
            else DiscoverySummary(
                thread_id=request.thread_id,
                revision=1,
                phase="understand",
                goal_label="Your next step",
                question_count=0,
                expires_at=(now + timedelta(seconds=self.settings.conversation_context_ttl_seconds))
                .replace(microsecond=0)
                .isoformat(),
            )
        )
        counts = dict(current.counts) if current else {}
        summary.revision = revision + 1
        previous_question = summary.question
        changed_goal = goal_id != summary.goal_id
        recipient = (
            "someone-else"
            if _OTHER_PERSON.search(text)
            else ("you" if re.search(r"\b(?:for me|for myself|my own)\b", text, re.I) else None)
        )
        changed_target = recipient is not None and recipient != summary.about
        changed_context = changed_goal or changed_target
        if changed_context:
            summary.question = None
            summary.suggestions = []
            summary.suggested_demo_id = None
            summary.facts = []
            summary.phase = "understand"
            summary.about = recipient or "you"
            summary.goal_id = goal_id
            summary.goal_label = GOALS[goal_id].label if goal_id else "Your next step"
            summary.question_count = counts.get(goal_id, 0) if goal_id else 0

        result = DiscoveryRun(ref, revision)
        if URGENT.search(text):
            summary.question, summary.phase = None, "plan"
            summary.suggestions, summary.suggested_demo_id = [], None
            result.reply = ApplicationReply(URGENT_SAFETY_TEXT, "handoff")
        elif command.action == "explore":
            summary.goal_id, summary.goal_label = None, "Your next step"
            summary.facts, summary.suggestions, summary.suggested_demo_id = [], [], None
            summary.question, summary.question_count, summary.phase = None, 0, "understand"
            summary.about = "unspecified"
            result.reply = ApplicationReply(
                "Of course. What would you like help figuring out next?"
            )
        elif command.action in ("correct", "remove"):
            result = self._edit(summary, command, normalized)
        elif command.action == "respond" and (social := dialogue_reply(text)) is not None:
            result.reply = social
        elif DIRECT_FACT.search(normalized) and command.action == "respond":
            summary.question, summary.phase = None, "plan"
            result.public_query = _public_query(
                text, goal_id, current.public_query if current else None
            )
            if result.public_query is None:
                result.reply = source_handoff("", self.catalog)
        elif goal_id is None:
            result.reply = dialogue_reply(text)
            if result.reply is None:
                result.public_query = _public_query(
                    text, None, current.public_query if current else None
                )
                if result.public_query is None:
                    result.reply = ApplicationReply(
                        "I can help you navigate B.C. public services, but I don't have a "
                        "supported pathway for that request. "
                        + source_handoff("", self.catalog).text,
                        "handoff",
                    )
                summary.phase = "plan"
        else:
            result = self._discover(
                summary,
                command,
                normalized,
                previous_question if not changed_context else None,
                counts,
                first=changed_context,
            )
        result.ref, result.base_revision, result.summary = ref, revision, summary
        public_query = result.public_query or (
            GOALS[summary.goal_id].public_query if summary.goal_id else None
        )
        if (
            public_query is None
            and current is not None
            and command.action == "respond"
            and dialogue_reply(text) is not None
        ):
            public_query = current.public_query
        result.state = StoredDiscovery(
            summary=summary,
            counts=counts,
            previous_revision=revision,
            input_hash=fingerprint,
            reply=result.reply.text if result.reply else None,
            public_query=public_query,
            reply_kind=result.reply.kind if result.reply else "dialogue",
            run_id=request.run_id,
        )
        return result

    def _edit(
        self, summary: DiscoverySummary, command: DiscoveryCommand, text: str
    ) -> DiscoveryRun:
        key = command.fact_key
        if key is None or summary.goal_id is None or not any(f.key == key for f in summary.facts):
            raise ApiError(422, "DISCOVERY_FACT_INVALID", "Choose a fact shown in your context.")
        fact = (
            _fact(key, None, "declined")
            if command.action == "remove"
            else _answer(key, text, summary.goal_id)
        )
        if fact is None:
            raise ApiError(
                422,
                "DISCOVERY_ANSWER_INVALID",
                "Please use a short answer or choose not sure. No ID numbers are needed.",
            )
        summary.facts = [fact if item.key == key else item for item in summary.facts]
        summary.question, summary.phase = None, "plan"
        result = self._plan(summary)
        result.reply = ApplicationReply(
            "I've removed that from the context I use. We'll keep that part general."
            if command.action == "remove"
            else "Thanks - I've updated what I understand. We can keep refining the next steps."
        )
        return result

    def _discover(
        self,
        summary: DiscoverySummary,
        command: DiscoveryCommand,
        text: str,
        pending: DiscoveryQuestion | None,
        counts: dict[DiscoveryGoalId, int],
        *,
        first: bool,
    ) -> DiscoveryRun:
        goal_id = summary.goal_id
        assert goal_id is not None
        goal = GOALS[goal_id]
        facts = {fact.key: fact for fact in summary.facts}
        if (
            not first
            and command.question_id is not None
            and (pending is None or command.question_id != pending.id)
        ):
            raise ApiError(
                409, "DISCOVERY_CHANGED", "That question is no longer active. Refresh your context."
            )
        if pending and command.action in ("respond", "skip") and command.question_id != pending.id:
            raise ApiError(
                409, "DISCOVERY_CHANGED", "Answer the current question or refresh your context."
            )
        skip = command.action == "skip"
        general = command.action == "general" or bool(
            GENERAL.search(text)
            or (DECLINED.search(text) and command.action != "skip" and text.strip(".!?") != "skip")
        )
        unrecognized = False
        if pending and command.action == "respond" and not general:
            answer = _answer(pending.fact_key, text, goal_id)
            if (
                summary.about == "someone-else"
                and pending.fact_key in ("age", "phn-status", "bc-residency", "licence-experience")
                and re.match(r"i\b", text)
            ):
                answer = None
            unrecognized = answer is None
            facts[pending.fact_key] = answer or _fact(pending.fact_key, None, "unknown")
        elif pending and (skip or general):
            facts[pending.fact_key] = _fact(pending.fact_key, None, "declined")
        volunteered = _volunteered(text, goal_id, someone_else=summary.about == "someone-else")
        for key, fact in volunteered.items():
            if key not in facts or facts[key].status != "declined":
                facts[key] = fact
        summary.facts = list(facts.values())
        summary.question = None
        if general or (summary.phase == "plan" and command.action != "refine"):
            summary.phase = "plan"
            if general:
                return self._plan(summary, "No problem - we can keep it general. ")
            public_query = _public_query(text, goal_id)
            return DiscoveryRun("", 0, public_query=public_query)
        next_key = next((key for key in goal.questions if key not in facts), None)
        if next_key is None or counts.get(goal_id, 0) >= 3:
            summary.phase = "plan"
            return self._plan(
                summary,
                goal.acknowledgment + " "
                if first
                else "I couldn't use that detail confidently, so we'll leave it open. "
                if unrecognized
                else "Thanks - let's bring that together. ",
            )
        copy = question_copy(goal_id, next_key)
        counts[goal_id] = counts.get(goal_id, 0) + 1
        summary.question_count = counts[goal_id]
        summary.suggestions, summary.suggested_demo_id = [], None
        summary.phase = "understand"
        question_text = copy.text
        if summary.about == "someone-else":
            question_text = {
                "age": (
                    "How old will they be when they expect to start riding? An age range is fine."
                ),
                "licence-experience": (
                    "Do they already have a motorcycle licence, or would this be their first one?"
                ),
                "phn-status": (
                    "Do they already have a Personal Health Number? Just yes, no, or not sure - "
                    "please don't share the number."
                ),
                "bc-residency": "Are they living in B.C. now, or planning a move?",
            }.get(next_key, copy.text)
        summary.question = DiscoveryQuestion(
            id="question-" + secrets.token_urlsafe(16),
            fact_key=next_key,
            text=question_text,
            reason=copy.reason,
            choices=list(copy.choices),
        )
        prefix = (
            goal.acknowledgment
            if first
            else "I couldn't use that detail confidently, so I'll leave it open."
            if unrecognized
            else (
                "That's okay - we can leave that open."
                if pending
                and facts.get(pending.fact_key)
                and facts[pending.fact_key].status != "provided"
                else "Thanks."
            )
        )
        return DiscoveryRun("", 0, reply=ApplicationReply(f"{prefix} {question_text}"))
