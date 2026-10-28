"""Commit independently validated sections without exposing unchecked model tokens."""

import math
import re
from urllib.parse import urldefrag

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)

from bc_api.catalog import CatalogRepository
from bc_api.dialogue import is_model_clarification
from bc_api.errors import ApiError
from bc_api.models import ResponseKind
from bc_api.protocol import validate_artifact
from bc_api.retrieval import EvidenceLedger
from bc_api.tools import TOOL_NAMES
from bc_api.urls import official_url

# Guard financial terms and obligations, not category names such as "dispensing fees".
CRITICAL = re.compile(
    r"[$\u00a3\u20ac\u00a5]\s*\d|\b(?:CAD|dollars?|deadline|percent)\b|\d\s*%"
    r"|\b(?:fees?|costs?|charges?|premiums?)\s*:"
    r"|\b(?:fees?|costs?|charges?|premiums?)\s+(?:[a-z'-]+\s+){0,4}"
    r"(?:is|are|will|would|must|apply|applies|required|waived|covered|due|payable|imposed)\b"
    r"|\b(?:no|zero|without|lower|higher|reduced|discounted|waived)\s+"
    r"(?:[a-z'-]+\s+){0,3}(?:fees?|costs?|charges?|premiums?)\b"
    r"|\bcomplimentary\b|(?<!feel )\bfree\b(?![- ]form)"
    r"|\b(?:there\s+(?:is|are)|has|have)\s+(?:a\s+|an\s+)?(?:fees?|charges?|premiums?)\b"
    r"|\b(?:you|residents?|applicants?)\s+(?:must\s+|will\s+|have to\s+)?(?:pay|owe)\b"
    r"|\b(?:costs?|charges?)\s+(?:you\s+)?(?:nothing|one|two|three|four|five|six|seven|eight|nine|ten|\d)\b"
    r"|\b(?:charges?|incurs?|requires?|collects?)\s+(?:[a-z'-]+\s+){0,3}fees?\b"
    r"|\b\d{4}-\d{2}-\d{2}\b|\b(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d"
    r"|\b(?:you|applicants?)\s+(?:qualify|qualifies|must earn|must have|"
    r"(?:are|is)\s+(?:eligible|required|entitled))\b"
    r"|\b(?:must|need to|have to)\s+(?:be|earn|reside|live)\b",
    re.IGNORECASE,
)
TRANSACTION_CLAIMS = re.compile(
    r"\b(?:I|we|the assistant)\s+(?:have\s+)?(?:renewed|submitted|booked|paid|registered|enrolled)"
    r"|\byour\s+(?:licen[cs]e|application|appointment|registration)\s+"
    r"(?:is|has been|was)\s+(?:renewed|submitted|booked|approved|completed)"
    r"|\byou\s+(?:are|have been)\s+(?:eligible|approved|enrolled|registered)\b",
    re.IGNORECASE,
)
SENTENCE_BOUNDARY = re.compile(r"""(?<=[.!?])["”']?\s+|\n+""")


def normalize_quote(value: str) -> str:
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"\s+([,;:!?])", r"\1", value)
    return " ".join(value.strip(' \t\r\n*>"“”').split()).rstrip(".").casefold()


class OutputGate:
    def __init__(
        self,
        catalog: CatalogRepository,
        ledger: EvidenceLedger,
        *,
        allow_clarification: bool = False,
    ) -> None:
        self.catalog = catalog
        self.ledger = ledger
        self.events: list[BaseEvent] = []
        self.text: dict[str, str] = {}
        self.size = 0
        self.committed: dict[str, int] = {}
        self.started: set[str] = set()
        self.sent_artifacts: set[str] = set()
        self.output_bytes = 0
        self.message_ids: set[str] = set()
        self.message_ends: set[str] = set()
        self.allow_clarification = allow_clarification
        self.response_kind: ResponseKind = "grounded"

    def hold(self, event: BaseEvent) -> None:
        self.size += len(event.model_dump_json().encode("utf-8"))
        if self.size > 262144 or len(self.events) >= 1000:
            raise ApiError(502, "OUTPUT_LIMIT", "The response exceeded the pilot output limit.")
        kind = event.type
        if kind.startswith("REASONING"):
            return
        if kind == "RAW":
            raise ApiError(502, "OUTPUT_INVALID", "Unsupported provider output was withheld.")
        data = event.model_dump(by_alias=True)
        if kind == "TEXT_MESSAGE_START":
            if (
                data.get("role", "assistant") != "assistant"
                or data["messageId"] in self.message_ids
            ):
                raise ApiError(502, "OUTPUT_INVALID", "Unsupported message framing was withheld.")
            self.message_ids.add(data["messageId"])
        if kind == "TEXT_MESSAGE_CONTENT":
            message_id = data["messageId"]
            if message_id not in self.message_ids or message_id in self.message_ends:
                raise ApiError(502, "OUTPUT_INVALID", "Unexpected answer content was withheld.")
            self.text[message_id] = self.text.get(message_id, "") + data["delta"]
        if kind == "TEXT_MESSAGE_END":
            if data["messageId"] not in self.message_ids or data["messageId"] in self.message_ends:
                raise ApiError(502, "OUTPUT_INVALID", "Unexpected answer completion was withheld.")
            self.message_ends.add(data["messageId"])
        if kind == "TOOL_CALL_START" and data["toolCallName"] not in TOOL_NAMES:
            raise ApiError(502, "TOOL_DENIED", "The agent requested an unapproved capability.")
        if kind == "STATE_SNAPSHOT" and data["snapshot"] not in (None, {}):
            raise ApiError(502, "OUTPUT_INVALID", "Unvalidated state changes were withheld.")
        if kind == "STATE_DELTA":
            raise ApiError(502, "OUTPUT_INVALID", "Unvalidated state changes were withheld.")
        if kind == "CUSTOM" and data.get("name") == "usage":
            if not isinstance(data.get("value"), dict) or any(
                not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0
                for value in data["value"].values()
            ):
                raise ApiError(502, "OUTPUT_INVALID", "Unvalidated usage metadata was withheld.")
        elif kind == "CUSTOM" and data.get("name") == "bc.artifact":
            event = validate_artifact(data.get("value"), self.catalog)
        elif kind == "CUSTOM" and data.get("name") != "annotations":
            raise ApiError(502, "OUTPUT_INVALID", "Unvalidated generated components were withheld.")
        self.events.append(event)

    def _account(self, events: list[BaseEvent]) -> list[BaseEvent]:
        self.output_bytes += sum(len(event.model_dump_json().encode()) for event in events)
        if self.output_bytes > 524288:
            raise ApiError(502, "OUTPUT_LIMIT", "The response exceeded the pilot output limit.")
        return events

    def flush_sections(self) -> list[BaseEvent]:
        """Use the same final validator for each complete, self-contained prefix."""
        ready: list[BaseEvent] = []
        for event in self.events:
            if event.type == "CUSTOM" and getattr(event, "name", None) == "bc.artifact":
                artifact_id = event.value["id"]
                if artifact_id not in self.sent_artifacts:
                    self.sent_artifacts.add(artifact_id)
                    ready.append(event)
        ended = {event.message_id for event in self.events if event.type == "TEXT_MESSAGE_END"}
        for message_id, text in self.text.items():
            offset = self.committed.get(message_id, 0)
            boundaries = [match.end() for match in re.finditer(r"\n[ \t]*\n", text)]
            if message_id in ended:
                boundaries.append(len(text))
            for boundary in sorted(set(boundaries)):
                if boundary <= offset:
                    continue
                section = text[offset:boundary]
                if not section.strip():
                    continue
                probe = OutputGate(self.catalog, self.ledger)
                probe.hold(TextMessageStartEvent(message_id=message_id, role="assistant"))
                probe.hold(TextMessageContentEvent(message_id=message_id, delta=section))
                probe.hold(TextMessageEndEvent(message_id=message_id))
                if offset == 0 and boundary == len(text) and message_id in ended:
                    for event in self.events:
                        if (
                            event.type == "CUSTOM"
                            and getattr(event, "name", None) == "annotations"
                            and isinstance(event.value, dict)
                            and event.value.get("messageId") == message_id
                        ):
                            probe.hold(event)
                try:
                    checked = probe.finish()
                except ApiError as exc:
                    if exc.code == "CITATION_REQUIRED":
                        continue
                    raise
                if message_id not in self.started:
                    ready.append(TextMessageStartEvent(message_id=message_id, role="assistant"))
                    self.started.add(message_id)
                ready.extend(event for event in checked if event.type == "CUSTOM")
                ready.append(TextMessageContentEvent(message_id=message_id, delta=section))
                offset = boundary
                self.committed[message_id] = boundary
        return self._account(ready)

    def finish(self) -> list[BaseEvent]:
        text = "\n".join(self.text.values())
        if not text.strip():
            raise ApiError(502, "EMPTY_ANSWER", "The AI service did not return a sourced answer.")
        if re.search(r"</?[a-z][a-z0-9]*(?:\s|/?>)|```|!\[", text, re.I):
            raise ApiError(502, "OUTPUT_INVALID", "Unsafe answer formatting was withheld.")
        if TRANSACTION_CLAIMS.search(text):
            raise ApiError(
                502,
                "TRANSACTION_CLAIM_BLOCKED",
                "An unsupported service-action claim was withheld.",
            )

        evidence = {}
        for item in self.ledger.items.values():
            evidence.setdefault(urldefrag(item.reference.url)[0], []).append(item)
        handoffs = {
            urldefrag(handoff.url)[0]
            for journey in self.catalog.get().journeys
            for handoff in journey.handoffs
        }
        cited: set[str] = set()
        result: list[BaseEvent] = []
        annotated_ids: set[str] = set()
        for event in self.events:
            if event.type == "CUSTOM" and getattr(event, "name", None) == "annotations":
                data = event.model_dump(by_alias=True)
                value = data.get("value")
                if (
                    not isinstance(value, dict)
                    or value.get("messageId") not in self.text
                    or not isinstance(value.get("annotations"), list)
                    or len(value["annotations"]) > 100
                ):
                    raise ApiError(
                        502, "CITATION_INVALID", "The answer citations could not be verified."
                    )
                enriched = []
                for annotation in value["annotations"]:
                    url = annotation.get("url") if isinstance(annotation, dict) else None
                    if not isinstance(url, str) or urldefrag(url)[0] not in evidence:
                        raise ApiError(
                            502, "CITATION_INVALID", "The answer cited an unverified source."
                        )
                    refs = evidence[urldefrag(url)[0]]
                    for item in refs:
                        enriched.append({**annotation, **item.reference.model_dump(by_alias=True)})
                    cited.add(urldefrag(url)[0])
                annotated_ids.add(value["messageId"])
                result.append(
                    event.model_copy(update={"value": {**value, "annotations": enriched}})
                )
            else:
                result.append(event)
        for url in re.findall(r"\[[^\]]*\]\(([^)\s]+)\)", text):
            try:
                official_url(url)
            except ValueError:
                raise ApiError(
                    502, "CITATION_INVALID", "An unapproved answer link was withheld."
                ) from None
        urls = re.findall(r"https?://[^\s<>\])\"']+", text)
        for url in urls:
            url = url.rstrip(".,;")
            base = urldefrag(url)[0]
            if base not in evidence and base not in handoffs:
                raise ApiError(502, "CITATION_INVALID", "An unverified answer link was withheld.")
            if base in evidence:
                cited.add(base)
        dialogue = (
            not cited
            and self.allow_clarification
            and not self.committed
            and is_model_clarification(text)
        )
        if not cited and not dialogue:
            raise ApiError(
                502, "CITATION_REQUIRED", "The answer did not include verifiable source citations."
            )
        self.response_kind = "dialogue" if dialogue else "grounded"

        quotes = {
            normalize_quote(sentence)
            for url in cited
            for item in evidence[url]
            for sentence in SENTENCE_BOUNDARY.split(item.content)
        }
        for sentence in SENTENCE_BOUNDARY.split(text):
            normalized = normalize_quote(sentence)
            if CRITICAL.search(normalized):
                if not normalized or normalized not in quotes:
                    raise ApiError(
                        502,
                        "CRITICAL_CLAIM_UNVERIFIED",
                        "A fee, deadline or eligibility claim needs review. "
                        "Consult the official source.",
                    )
        for message_id, content in self.text.items():
            if message_id not in annotated_ids:
                refs = [
                    {
                        "type": "citation",
                        **item.reference.model_dump(by_alias=True),
                    }
                    for url in sorted(cited)
                    if url in content
                    for item in evidence[url]
                ]
                if refs:
                    result.append(
                        CustomEvent(
                            name="annotations", value={"messageId": message_id, "annotations": refs}
                        )
                    )
        output: list[BaseEvent] = []
        offsets: dict[str, int] = {}
        for event in result:
            kind = event.type
            if kind.startswith("TOOL_CALL"):
                continue
            if kind == "TEXT_MESSAGE_START":
                if event.message_id in self.started:
                    continue
                self.started.add(event.message_id)
            elif kind == "TEXT_MESSAGE_CONTENT":
                start = offsets.get(event.message_id, 0)
                offsets[event.message_id] = start + len(event.delta)
                skip = max(0, self.committed.get(event.message_id, 0) - start)
                if skip >= len(event.delta):
                    continue
                event = event.model_copy(update={"delta": event.delta[skip:]})
            elif kind == "CUSTOM" and getattr(event, "name", None) == "bc.artifact":
                if event.value["id"] in self.sent_artifacts:
                    continue
            output.append(event)
        return self._account(output)
