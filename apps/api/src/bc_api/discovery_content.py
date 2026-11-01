"""Reviewed navigation questions, not eligibility rules or a citizen profile."""

import re
from dataclasses import dataclass

from bc_api.models import DemoPersonaId, DiscoveryFactKey, DiscoveryGoalId, JourneyId


@dataclass(frozen=True)
class QuestionCopy:
    label: str
    text: str
    reason: str
    choices: tuple[str, ...] = ()


QUESTIONS: dict[DiscoveryFactKey, QuestionCopy] = {
    "age": QuestionCopy(
        "Age when you plan to start",
        "How old will you be when you expect to start riding? An age range is fine.",
        "This is optional planning context, not a decision about licensing eligibility. "
        "Please don't share your date of birth.",
        ("Under 19", "19 or older", "Not sure"),
    ),
    "licence-experience": QuestionCopy(
        "Licensing experience",
        "Would this be your first licence of this kind, or do you already have one?",
        "I'll distinguish getting started from an existing licence. "
        "Please don't share a licence number.",
        ("My first one", "I already have one", "Not sure"),
    ),
    "timeframe": QuestionCopy(
        "When you are planning",
        "Are you hoping to get started soon, or planning further ahead?",
        "This helps organize your next steps. You don't need to give an exact date.",
        ("Soon", "Later", "Next year", "Not sure"),
    ),
    "priority": QuestionCopy(
        "What matters first",
        "What would you like to focus on first?",
        "We can work through one need at a time, without deciding your eligibility.",
    ),
    "bc-residency": QuestionCopy(
        "B.C. living situation",
        "Are you living in B.C. now, or planning a move?",
        "I'll keep the guidance focused on your situation. No address is needed.",
        ("Living in B.C.", "Planning a move", "Not sure"),
    ),
    "phn-status": QuestionCopy(
        "Whether you have a PHN",
        "Do you already have a Personal Health Number? Just yes, no, or not sure - "
        "please don't share the number itself.",
        "This is only to help organize health-service preparation, not to check a health record.",
        ("Yes", "No", "Not sure"),
    ),
    "support-for": QuestionCopy(
        "Who the support is for",
        "Are you helping an adult or a child?",
        "I'll keep their situation separate from yours. No name or date of birth is needed.",
        ("An adult", "A child", "Not sure"),
    ),
}


@dataclass(frozen=True)
class DiscoveryGoal:
    label: str
    pattern: str
    acknowledgment: str
    questions: tuple[DiscoveryFactKey, ...]
    public_query: str
    source_ids: tuple[str, ...]
    journeys: tuple[JourneyId, ...] = ()
    demo_id: DemoPersonaId | None = None
    priorities: tuple[str, ...] = ()
    priority_question: str = "What would you like to focus on first?"


GOALS: dict[DiscoveryGoalId, DiscoveryGoal] = {
    "motorcycle": DiscoveryGoal(
        "Planning for a motorcycle",
        r"\bmotor(?:cycle|bike)s?\b",
        "That sounds exciting - let's work out where to start.",
        ("age", "licence-experience", "timeframe"),
        "ICBC motorcycle licensing learning to ride insurance preparation",
        ("icbc",),
    ),
    "pharmacare": DiscoveryGoal(
        "Preparing for PharmaCare",
        r"\bpharmacare\b|\bprescription (?:costs?|coverage)\b",
        "Let's work through the preparation together.",
        ("phn-status",),
        "Fair PharmaCare registration preparation official guidance",
        ("health",),
        ("pharmacare-registration",),
    ),
    "primary-care": DiscoveryGoal(
        "Finding primary care",
        r"\b(?:family doctor|primary care|health connect|find a doctor|need a doctor)\b",
        "Let's find a useful starting point.",
        ("phn-status",),
        "Health Connect Registry primary care registration preparation",
        ("healthlink-bc",),
        ("primary-care",),
    ),
    "health": DiscoveryGoal(
        "Understanding health coverage",
        r"\bmsp\b|\bhealth (?:coverage|insurance)\b",
        "We can take the health-coverage steps one at a time.",
        ("bc-residency", "phn-status"),
        "MSP health coverage enrolment preparation official guidance",
        ("health",),
        ("health-coverage",),
    ),
    "job-loss": DiscoveryGoal(
        "Next steps after job loss",
        r"\b(?:lost my job|lost a job|laid off|layoff|unemployed|out of work)\b",
        "I'm sorry you're dealing with that. We can take this one step at a time.",
        ("priority",),
        "Employment support WorkBC housing rental assistance official starting points",
        ("workbc", "bc-housing"),
        demo_id="sam-job-loss",
        priorities=("Help with rent", "Finding work", "Both"),
        priority_question="Would you like to start with help for rent or finding work?",
    ),
    "caregiving": DiscoveryGoal(
        "Helping someone you care for",
        r"\b(?:caregiv(?:er|ing)|guardianship|power of attorney|caring for|care for my)\b",
        "That can be a lot to navigate. Let's work through it together.",
        ("support-for", "priority"),
        "Caregiving guardianship adult child official service navigation",
        ("family-social-supports",),
        demo_id="maya-caregiver",
        priorities=("Practical support", "Legal planning", "Both"),
        priority_question="Would practical support or legal planning be more useful to start with?",
    ),
    "disability": DiscoveryGoal(
        "Exploring disability support",
        r"\bdisability\b|\bdisabilit(?:y|ies) support\b",
        "Let's focus on the support you're looking for, without needing your medical history.",
        ("priority",),
        "Disability support application preparation official service navigation",
        ("family-social-supports",),
        demo_id="alex-disability-support",
        priorities=("Application guidance", "Work and daily support", "Not sure"),
        priority_question=(
            "Are you looking for application guidance or support with work and daily life?"
        ),
    ),
    "rent": DiscoveryGoal(
        "Finding housing or rental guidance",
        r"\brent(?:al)?\b|\btenan(?:t|cy)\b|\blandlord\b|\bhousing\b",
        "Let's work out which kind of housing help would be useful.",
        ("priority",),
        "BC Housing rental assistance housing tenancy official guidance",
        ("bc-housing", "housing-tenancy"),
        ("rental-assistance",),
        priorities=("Help paying rent", "Tenancy rights", "Finding housing", "Not sure"),
        priority_question="Is your main concern paying rent, tenancy rights, or finding housing?",
    ),
    "road-test": DiscoveryGoal(
        "Preparing for a road test",
        r"\broad test\b|\bdriving test\b",
        "Let's get your preparation organized.",
        ("timeframe",),
        "ICBC road test booking preparation official handoff",
        ("icbc",),
        ("road-test-booking",),
    ),
    "licence": DiscoveryGoal(
        "Preparing to renew a licence",
        r"\brenew\w*\b.*\b(?:licen[cs]e|bcid)\b|\b(?:licen[cs]e|bcid)\b.*\brenew\w*\b",
        "Let's make the preparation a little easier.",
        ("timeframe",),
        "ICBC driver licence BCID renewal preparation accepted identification",
        ("icbc", "service-bc"),
        ("licence-renewal",),
    ),
    "service-bc": DiscoveryGoal(
        "Finding Service BC help",
        r"\bservice ?bc\b|\bgovernment office\b",
        "Let's find the right kind of help.",
        (),
        "Service BC office directory services exclusions official guidance",
        ("service-bc",),
        ("service-bc",),
    ),
}

DIRECT_FACT = re.compile(
    r"^(?:what (?:is|are|does|do)\b|how (?:much|long)\b|"
    r"when (?:is|does|do)\b|where (?:is|are)\b|"
    r"(?:define|explain)\b|(?:can|do) (?:you|they)\b)",
    re.I,
)
DECLINED = re.compile(
    r"\b(?:skip|prefer not|rather not|don't want to (?:say|share|answer)|"
    r"do not want to (?:say|share|answer)|not comfortable|private)\b",
    re.I,
)
GENERAL = re.compile(
    r"\b(?:keep (?:it|this) general|general (?:answer|guidance|information)|"
    r"just (?:answer|give me)|no (?:more )?questions)\b",
    re.I,
)
UNCERTAIN = re.compile(r"\b(?:not sure|don't know|do not know|unsure|maybe)\b", re.I)
URGENT = re.compile(
    r"\b(?:in immediate danger|in danger right now|not safe right now|"
    r"someone is (?:hurt|unconscious)|can't breathe|cannot breathe|"
    r"(?:house|home) is on fire)\b",
    re.I,
)


def normalize(text: str) -> str:
    return " ".join(text.replace("\u2019", "'").casefold().split())


def detect_goal(text: str) -> DiscoveryGoalId | None:
    for goal_id, goal in GOALS.items():
        if re.search(goal.pattern, text, re.I):
            return goal_id
    return None


def question_copy(goal_id: DiscoveryGoalId, key: DiscoveryFactKey) -> QuestionCopy:
    if key == "priority":
        goal = GOALS[goal_id]
        return QuestionCopy(
            QUESTIONS[key].label, goal.priority_question, QUESTIONS[key].reason, goal.priorities
        )
    if key == "licence-experience" and goal_id == "motorcycle":
        question = QUESTIONS[key]
        return QuestionCopy(
            question.label,
            "Do you already have a motorcycle licence, or would this be your first one?",
            question.reason,
            question.choices,
        )
    return QUESTIONS[key]
