"""Small, catalogue-owned preparation tasks; progress never means a service was completed."""

import hashlib
import re
import secrets
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StrictBool, model_validator

from bc_api.catalog import CatalogRepository
from bc_api.errors import ApiError
from bc_api.models import Handoff, Identifier, JourneyId, Source, Step, WireModel, require_unique

TaskAction = Literal[
    "continue", "explain", "reviewed", "next", "back", "skip", "repair", "full-guide"
]
ServiceFilter = Literal["icbc-licensing", "income-assistance", "bc-services-card", "bceid"]

START_STEPS: dict[JourneyId, str] = {
    "licence-renewal": "prepare-identification",
    "road-test-booking": "prepare-identification-and-payment",
    "rental-assistance": "choose-rental-program",
    "health-coverage": "check-msp-enrolment",
    "pharmacare-registration": "prepare-registration-information",
    "primary-care": "prepare-registry-information",
    "service-bc": "filter-office-snapshot",
}
OFFICE_STEPS = frozenset({"find-licensing-office", "filter-office-snapshot"})
FOCUS_STEPS = {
    "licence-renewal": {
        "documents": "prepare-identification",
        "locations": "find-licensing-office",
        "contact": "confirm-before-visiting",
    },
    "road-test-booking": {
        "documents": "prepare-identification-and-payment",
        "contact": "book-with-icbc",
    },
    "rental-assistance": {
        "documents": "prepare-rental-evidence",
        "requirements": "review-eligibility-exclusions",
    },
    "health-coverage": {"documents": "check-msp-enrolment", "contact": "ask-health-insurance-bc"},
    "pharmacare-registration": {
        "documents": "prepare-registration-information",
        "contact": "register-with-pharmacare",
    },
    "primary-care": {"documents": "prepare-registry-information", "contact": "get-registry-help"},
    "service-bc": {"locations": "filter-office-snapshot", "timing": "review-office-hours"},
}


class AssistanceTask(WireModel):
    model_config = ConfigDict(validate_assignment=False)
    id: Identifier
    journey_id: JourneyId
    catalog_version: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    step_versions: dict[str, str] = Field(max_length=40)
    step_ids: list[Identifier] = Field(min_length=1, max_length=40)
    active_step_id: Identifier
    reviewed_step_ids: list[Identifier] = Field(default_factory=list, max_length=40)
    skipped_step_ids: list[Identifier] = Field(default_factory=list, max_length=40)
    phase: Literal["preparing", "ready-for-official-handoff"] = "preparing"
    waiting_for: Literal["readiness", "municipality", "official-service"] = "readiness"
    last_action: TaskAction = "continue"
    municipality: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    service: ServiceFilter | None = None

    @model_validator(mode="after")
    def coherent_progress(self) -> Self:
        for values in (self.step_ids, self.reviewed_step_ids, self.skipped_step_ids):
            require_unique(values, "Task steps")
        if self.active_step_id not in self.step_ids:
            raise ValueError("Active step must belong to the task.")
        if not set(self.reviewed_step_ids + self.skipped_step_ids) <= set(self.step_ids):
            raise ValueError("Progress must reference existing task steps.")
        if set(self.reviewed_step_ids) & set(self.skipped_step_ids):
            raise ValueError("A skipped step is not reviewed.")
        return self


class TaskSnapshot(WireModel):
    version: Literal[1] = 1
    thread_id: Identifier
    revision: Annotated[int, Field(ge=1)]
    task: AssistanceTask | None
    step: Step | None
    handoffs: list[Handoff] = Field(default_factory=list, max_length=20)
    sources: list[Source] = Field(default_factory=list, max_length=100)
    guidance: Annotated[str, Field(max_length=8000)] = ""


class ConversationControl(WireModel):
    id: Identifier
    revision: Annotated[int, Field(ge=1)]
    notice_version: Literal["ai-conversation-v1"]
    action: Literal["sharing", "review", "next", "back", "skip"]
    share_context: StrictBool | None = None
    task_id: Identifier | None = None
    step_id: Identifier | None = None
    reviewed: StrictBool | None = None

    @model_validator(mode="after")
    def narrow_control(self) -> Self:
        if self.action == "sharing":
            if self.share_context is None or any(
                value is not None for value in (self.task_id, self.step_id, self.reviewed)
            ):
                raise ValueError("Sharing controls only change the sharing preference.")
        elif self.task_id is None or self.step_id is None or self.share_context is not None:
            raise ValueError("Task controls require task/step references, not a sharing change.")
        if (self.action == "review") != (self.reviewed is not None):
            raise ValueError("Only review controls specify reviewed status.")
        return self


def ensure_task(
    catalog: CatalogRepository, journey: JourneyId, previous: AssistanceTask | None
) -> AssistanceTask:
    guide = catalog.plan(journey)
    step_ids = [step.id for step in guide.journey.steps]
    versions = {
        step.id: hashlib.sha256(
            (
                step.model_dump_json(by_alias=True)
                + "".join(
                    source.model_dump_json(by_alias=True)
                    for source in guide.sources
                    if source.id in step.source_ids
                )
            ).encode()
        ).hexdigest()
        for step in guide.journey.steps
    }
    fingerprint = hashlib.sha256(guide.model_dump_json(by_alias=True).encode()).hexdigest()
    if previous is None or previous.journey_id != journey:
        return AssistanceTask(
            id="task-" + secrets.token_urlsafe(16),
            journey_id=journey,
            catalog_version=fingerprint,
            step_versions=versions,
            step_ids=step_ids,
            active_step_id=START_STEPS.get(journey)
            if START_STEPS.get(journey) in step_ids
            else step_ids[0],
            service="icbc-licensing" if journey == "licence-renewal" else None,
        )
    task = previous.model_copy(deep=True)
    if task.catalog_version != fingerprint:
        unchanged = {key for key, value in versions.items() if task.step_versions.get(key) == value}
        task.reviewed_step_ids = [key for key in task.reviewed_step_ids if key in unchanged]
        task.skipped_step_ids = [key for key in task.skipped_step_ids if key in unchanged]
        if task.active_step_id not in step_ids:
            task.active_step_id = step_ids[0]
        task.phase = "preparing"
    task.step_ids, task.step_versions, task.catalog_version = step_ids, versions, fingerprint
    return AssistanceTask.model_validate(task.model_dump())


def move_task(
    task: AssistanceTask, action: TaskAction, step_id: str | None = None, *, reviewed: bool = True
) -> None:
    key = step_id or task.active_step_id
    if key not in task.step_ids:
        raise ApiError(422, "TASK_STEP_INVALID", "Choose a step in the current preparation task.")
    if action == "reviewed":
        task.reviewed_step_ids = [item for item in task.reviewed_step_ids if item != key]
        if reviewed:
            task.reviewed_step_ids.append(key)
            task.skipped_step_ids = [item for item in task.skipped_step_ids if item != key]
        if not reviewed or key != task.active_step_id:
            task.last_action = action
            if not reviewed and task.phase == "ready-for-official-handoff":
                task.active_step_id, task.phase, task.waiting_for = key, "preparing", "readiness"
            sync_waiting(task)
            return
    if action == "skip":
        task.reviewed_step_ids = [item for item in task.reviewed_step_ids if item != key]
        task.skipped_step_ids = list(dict.fromkeys([*task.skipped_step_ids, key]))
    if action in ("next", "skip", "reviewed", "back"):
        index = task.step_ids.index(key) + (-1 if action == "back" else 1)
        if index >= len(task.step_ids):
            task.phase, task.waiting_for = "ready-for-official-handoff", "official-service"
        else:
            task.active_step_id = task.step_ids[max(0, index)]
            task.phase = "preparing"
    elif step_id is not None:
        task.active_step_id, task.phase = key, "preparing"
    task.last_action = action
    sync_waiting(task)


def sync_waiting(task: AssistanceTask) -> None:
    task.waiting_for = (
        "official-service"
        if task.phase == "ready-for-official-handoff"
        else "municipality"
        if task.active_step_id in OFFICE_STEPS and not task.municipality
        else "readiness"
    )


def task_followup(task: AssistanceTask | None) -> str | None:
    if task is None or task.phase == "ready-for-official-handoff":
        return None
    if task.active_step_id in OFFICE_STEPS:
        return "Which city or town would you like to visit?" if not task.municipality else None
    return (
        "Do you have your ID ready?"
        if task.active_step_id == "prepare-identification"
        else "Have you reviewed this step?"
    )


def task_snapshot(
    catalog: CatalogRepository, task: AssistanceTask | None, thread_id: str, revision: int
) -> TaskSnapshot:
    guide = catalog.plan(task.journey_id) if task else None
    step = (
        next(
            (step for step in guide.journey.steps if task and step.id == task.active_step_id), None
        )
        if guide
        else None
    )
    if task and step is None:
        raise ApiError(
            409, "TASK_CHANGED", "The preparation guide changed. Send a message to refresh it."
        )
    return TaskSnapshot(
        thread_id=thread_id,
        revision=revision,
        task=task,
        step=step,
        handoffs=guide.journey.handoffs if guide else [],
        sources=guide.sources if guide else [],
        guidance=task_text(catalog, task) if task else "",
    )


def task_text(catalog: CatalogRepository, task: AssistanceTask, *, repair: bool = False) -> str:
    guide = catalog.plan(task.journey_id)
    step = next(step for step in guide.journey.steps if step.id == task.active_step_id)
    links = guide.journey.handoffs
    if task.active_step_id == "prepare-identification":
        links = [link for link in links if "identification" in link.label.lower()] or links
    references = " | ".join(f"[{link.label}]({link.url})" for link in links[:2])
    prefix = "Yes - let's move this forward. " if repair else ""
    if task.phase == "ready-for-official-handoff":
        return (
            prefix
            + "Your next action is with the official service.\n\n"
            + references
            + "\n\nUse its current instructions to continue. This assistant has helped with "
            "preparation; nothing has been renewed, booked, or submitted here."
        )
    if task.active_step_id in OFFICE_STEPS:
        task.waiting_for = "municipality" if not task.municipality else "readiness"
        directory = next(
            (source for source in catalog.get().sources if source.id == "service-bc"), None
        )
        reference = f"[Service BC directory]({directory.url})" if directory else references
        if not task.municipality:
            if task.journey_id == "licence-renewal":
                reference = (
                    "[ICBC's driver licensing office locator]"
                    "(https://www.icbc.com/locators/Pages/default.aspx?type=1&subtype=0)"
                )
            return (
                prefix + "Let's find an office that offers the service you need. "
                "Which city or town would you like to visit? No street address is needed.\n\n"
                + reference
            )
        offices = catalog.locations(task.service, task.municipality).locations
        if offices:
            rows = "\n".join(
                f"- {office.name}: {office.address}. {office.hours}" for office in offices[:3]
            )
            return (
                prefix
                + f"These offices match the published snapshot for {task.municipality}:\n\n"
                + rows
                + "\n\n"
                + reference
                + "\n\nPublished hours are not live availability. Check with the office before "
                "visiting. Have you chosen an office, or do you need to look elsewhere?"
            )
        if task.journey_id == "licence-renewal":
            return (
                prefix + f"For {task.municipality}, use "
                "[ICBC's driver licensing office locator]"
                "(https://www.icbc.com/locators/Pages/default.aspx?type=1&subtype=0). "
                "Choose that city to check licensing services and booking instructions.\n\n"
                "I can't verify current office details from this pilot's limited snapshot. "
                "Keep your chosen city; confirm the office with ICBC. "
                "This is not live appointment availability."
            )
        return (
            prefix
            + f"The reviewed snapshot does not identify a matching office in {task.municipality}. "
            "That does not mean there is no service there. Use the full directory to find one.\n\n"
            + reference
            + "\n\nHave you found a suitable office, or would you like to try another city?"
        )
    task.waiting_for = "readiness"
    question = task_followup(task)
    return prefix + f"**{step.title}**\n\n{step.description}\n\n{references}\n\n{question}"


def explicit_progress(text: str, quote: str | None) -> bool:
    if not quote or quote.casefold() not in text.casefold():
        return False
    return not bool(
        re.search(
            r"\b(?:not|don't|do not|haven't|have not|can't|cannot|unsure|maybe|need help|"
            r"will|going to|want to|plan to)\b",
            text,
            re.I,
        )
    ) and bool(re.search(r"\b(?:yes|ready|done|have|reviewed|got|chosen|checked)\b", quote, re.I))
