"""Deterministic, server-owned screening rules for the synthetic context demo."""

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from pydantic.alias_generators import to_camel

from bc_api.models import (
    SCREENING_NOTICE,
    Catalog,
    ContextFact,
    ProgramMatch,
    ProgramMatches,
    ProgramSourceVersion,
)

SCHEMA_VERSION = 1
RULE_SET_ID = "citizen-context-demo-program-screening"
MAX_RULE_SET_BYTES = 512_000
MAX_CATALOG_BYTES = 2_000_000
FLOW_ORDER = ("guardianship-intake", "disability-support", "job-loss")
SUPPORTED_OPERATORS = frozenset({"equals", "in", "at-least"})
REVIEWED_COVERAGE = "reviewed-navigation-only"
MISSING_COVERAGE = "missing"
MISSING_FACT_BEHAVIOR = "needs-information-unless-not-indicated"

_IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$")
_FACT_KEY = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_POSITIVE_DECISION_WORDING = re.compile(
    r"\b(?:eligible|approved|entitled|guaranteed|qualifies|qualification confirmed)\b",
    re.IGNORECASE,
)


class DemoRuleSetError(ValueError):
    """A server-owned rule or source-review file failed closed validation."""


class DemoRuleEvaluationError(RuntimeError):
    """A public-safe deterministic evaluation failure."""

    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        program_id: str | None = None,
        missing_fact_keys: Sequence[str] = (),
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.program_id = program_id
        self.missing_fact_keys = tuple(missing_fact_keys)


def _calendar_date(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Use a canonical calendar date.")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError("Use a valid calendar date.") from None
    return value


def _trimmed_text(value: str) -> str:
    if value != value.strip() or not value.isprintable():
        raise ValueError("Use bounded printable text without surrounding whitespace.")
    return value


Identifier = Annotated[
    StrictStr,
    Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$"),
]
FactKey = Annotated[
    StrictStr,
    Field(min_length=3, max_length=100, pattern=r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$"),
]
RuleText = Annotated[
    StrictStr,
    Field(min_length=3, max_length=400),
    AfterValidator(_trimmed_text),
]
CalendarDate = Annotated[StrictStr, AfterValidator(_calendar_date)]
Sha256 = Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{64}$")]
JsonScalar = StrictStr | StrictInt | StrictFloat | StrictBool
FlowId = Literal["guardianship-intake", "disability-support", "job-loss"]
Coverage = Literal["reviewed-navigation-only", "missing"]
CatalogStatus = Literal["available", "limited", "pending", "blocked", "absent"]
Operator = Literal["equals", "in", "at-least"]
DiscoveryRole = Literal["primary-navigation", "related-navigation"]


def _parsed_date(value: str) -> date:
    return date.fromisoformat(value)


def _unique(values: Sequence[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique.")


def _same_scalar(left: object, right: object) -> bool:
    return type(left) is type(right) and left == right


def _scalar_identity(value: JsonScalar) -> tuple[type[object], object]:
    return (type(value), value)


class _RuleDataModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=False,
        extra="forbid",
        frozen=True,
    )


class SourceReview(_RuleDataModel):
    source_id: Identifier
    catalog_status: CatalogStatus
    catalog_checked_at: StrictStr | None
    coverage: Coverage
    reviewed_at: CalendarDate
    review_due: CalendarDate
    missing_coverage_reason: RuleText | None

    @model_validator(mode="after")
    def coherent_review(self) -> Self:
        if _parsed_date(self.review_due) < _parsed_date(self.reviewed_at):
            raise ValueError("Source review due date cannot precede its review date.")
        if self.coverage == REVIEWED_COVERAGE:
            if self.catalog_status not in ("available", "limited"):
                raise ValueError("Reviewed navigation coverage requires a usable catalogue status.")
            if self.catalog_checked_at is None or self.missing_coverage_reason is not None:
                raise ValueError("Reviewed source coverage requires a version and no gap reason.")
            if (
                len(self.catalog_checked_at) > 40
                or not self.catalog_checked_at.isprintable()
                or not _IDENTIFIER.fullmatch(self.catalog_checked_at)
            ):
                raise ValueError("Source versions must be bounded identifiers.")
        elif self.missing_coverage_reason is None:
            raise ValueError("Missing source coverage requires an explicit reason.")
        return self


class RequiredFact(_RuleDataModel):
    fact_key: FactKey
    public_missing_fact_key: Identifier


class RuleCondition(_RuleDataModel):
    fact_key: FactKey
    operator: Operator
    expected: JsonScalar | tuple[JsonScalar, ...]
    satisfied_label: Identifier
    not_satisfied_label: Identifier

    @model_validator(mode="after")
    def coherent_condition(self) -> Self:
        if self.operator == "in":
            if type(self.expected) is not tuple or not self.expected:
                raise ValueError("The in operator requires a non-empty scalar list.")
            identities = [_scalar_identity(value) for value in self.expected]
            if len(identities) != len(set(identities)):
                raise ValueError("Condition values must be unique.")
        elif type(self.expected) is tuple:
            raise ValueError("Only the in operator accepts a list.")
        if self.operator == "at-least" and (
            type(self.expected) not in (int, float) or isinstance(self.expected, bool)
        ):
            raise ValueError("The at-least operator requires a numeric boundary.")
        return self


class DemoProgramRule(_RuleDataModel):
    order: Annotated[StrictInt, Field(gt=0, le=100)]
    rule_id: Identifier
    program_id: Identifier
    program_display_name: RuleText
    flow_id: FlowId
    discovery_role: DiscoveryRole
    owner: RuleText
    version: Identifier
    effective_from: CalendarDate
    effective_to: CalendarDate | None
    reviewed_at: CalendarDate
    review_due: CalendarDate
    source_ids: tuple[Identifier, ...]
    source_coverage: Coverage
    missing_source_coverage_reason: RuleText | None
    required_facts: tuple[RequiredFact, ...]
    conditions: tuple[RuleCondition, ...]
    optional_conditions: tuple[RuleCondition, ...]
    already_enrolled_condition: RuleCondition | None
    missing_fact_behavior: Literal["needs-information-unless-not-indicated"]
    navigation_rationale: RuleText
    screening_notice: Literal["This is a screening indicator, not an eligibility decision."]
    rule_hash: Sha256

    @model_validator(mode="after")
    def coherent_rule(self) -> Self:
        effective_from = _parsed_date(self.effective_from)
        if self.effective_to is not None and _parsed_date(self.effective_to) <= effective_from:
            raise ValueError("Rule effective end dates are exclusive.")
        if _parsed_date(self.review_due) < _parsed_date(self.reviewed_at):
            raise ValueError("Rule review due date cannot precede its review date.")
        if not self.source_ids:
            raise ValueError("Rules require source IDs.")
        _unique(self.source_ids, "Rule source IDs")

        fact_keys = tuple(item.fact_key for item in self.required_facts)
        public_keys = tuple(item.public_missing_fact_key for item in self.required_facts)
        if not fact_keys:
            raise ValueError("Rules require public-safe fact requirements.")
        _unique(fact_keys, "Required fact keys")
        _unique(public_keys, "Public missing-fact keys")

        condition_keys = tuple(item.fact_key for item in self.conditions)
        optional_keys = tuple(item.fact_key for item in self.optional_conditions)
        if not condition_keys:
            raise ValueError("Rules require at least one deterministic condition.")
        _unique(condition_keys, "Required condition fact keys")
        _unique(optional_keys, "Optional condition fact keys")
        if not set(condition_keys) <= set(fact_keys):
            raise ValueError("Required conditions may consume only declared required facts.")
        if set(optional_keys) & set(fact_keys):
            raise ValueError("Optional conditions must not make a required fact implicit.")
        used_required_keys = set(condition_keys)
        if self.already_enrolled_condition is not None:
            if self.already_enrolled_condition.fact_key not in fact_keys:
                raise ValueError("Enrollment conditions must consume a declared required fact.")
            used_required_keys.add(self.already_enrolled_condition.fact_key)
        if used_required_keys != set(fact_keys):
            raise ValueError("Every required fact must have deterministic rule behavior.")

        all_conditions = (
            *self.conditions,
            *self.optional_conditions,
            *((self.already_enrolled_condition,) if self.already_enrolled_condition else ()),
        )
        all_labels = tuple(
            label
            for condition in all_conditions
            for label in (condition.satisfied_label, condition.not_satisfied_label)
        )
        _unique(all_labels, "Condition rationale labels")
        if set(all_labels) & set(public_keys):
            raise ValueError("Rationale and public missing-fact keys must not overlap.")

        rationale = self.navigation_rationale.casefold()
        expected_prefix = (
            "potential related navigation only:"
            if self.discovery_role == "related-navigation"
            else "potential navigation only:"
        )
        if not rationale.startswith(expected_prefix):
            raise ValueError("Navigation rationale must identify its discovery role.")
        if "not a formal eligibility assessment" not in rationale:
            raise ValueError("Navigation rationale must retain the non-decision boundary.")
        for text in (self.program_display_name, self.navigation_rationale):
            if _POSITIVE_DECISION_WORDING.search(text):
                raise ValueError("Rule text must not make a positive eligibility claim.")

        if self.source_coverage == REVIEWED_COVERAGE:
            if self.missing_source_coverage_reason is not None:
                raise ValueError("Reviewed rule coverage cannot carry a missing-source reason.")
        elif self.missing_source_coverage_reason is None:
            raise ValueError("Missing rule coverage requires an explicit reason.")
        return self


class DemoProgramRuleSet(_RuleDataModel):
    schema_version: Literal[1]
    rule_set_id: Literal["citizen-context-demo-program-screening"]
    rule_set_version: Identifier
    owner: RuleText
    catalog_as_of: StrictStr
    effective_from: CalendarDate
    effective_to: CalendarDate | None
    reviewed_at: CalendarDate
    review_due: CalendarDate
    screening_notice: Literal["This is a screening indicator, not an eligibility decision."]
    source_reviews: tuple[SourceReview, ...]
    rules: tuple[DemoProgramRule, ...]
    rule_set_hash: Sha256

    @model_validator(mode="after")
    def coherent_rule_set(self) -> Self:
        effective_from = _parsed_date(self.effective_from)
        if self.effective_to is not None and _parsed_date(self.effective_to) <= effective_from:
            raise ValueError("Rule-set effective end dates are exclusive.")
        if _parsed_date(self.review_due) < _parsed_date(self.reviewed_at):
            raise ValueError("Rule-set review due date cannot precede its review date.")
        if (
            not self.catalog_as_of
            or len(self.catalog_as_of) > 40
            or not self.catalog_as_of.isprintable()
        ):
            raise ValueError("Catalogue version must be bounded printable text.")

        source_ids = tuple(review.source_id for review in self.source_reviews)
        if not source_ids or source_ids != tuple(sorted(source_ids)):
            raise ValueError("Source reviews must use deterministic lexical ordering.")
        _unique(source_ids, "Source review IDs")

        if not self.rules:
            raise ValueError("The demo rule set cannot be empty.")
        if tuple(rule.order for rule in self.rules) != tuple(range(1, len(self.rules) + 1)):
            raise ValueError("Rule order must be contiguous and deterministic.")
        _unique(tuple(rule.rule_id for rule in self.rules), "Rule IDs")
        if any(rule.version != self.rule_set_version for rule in self.rules):
            raise ValueError("Every rule must use the pinned rule-set version.")

        source_id_set = set(source_ids)
        if any(not set(rule.source_ids) <= source_id_set for rule in self.rules):
            raise ValueError("Every rule source must have a source-review record.")

        review_by_id = {review.source_id: review for review in self.source_reviews}
        for rule in self.rules:
            coverages = {review_by_id[source_id].coverage for source_id in rule.source_ids}
            if rule.source_coverage == REVIEWED_COVERAGE and coverages != {REVIEWED_COVERAGE}:
                raise ValueError("Reviewed rules may use only reviewed source coverage.")
            if rule.source_coverage == MISSING_COVERAGE and MISSING_COVERAGE not in coverages:
                raise ValueError("A source-gap rule must identify missing source coverage.")

        flow_positions = tuple(FLOW_ORDER.index(rule.flow_id) for rule in self.rules)
        if flow_positions != tuple(sorted(flow_positions)):
            raise ValueError("Rules must be grouped in deterministic flow order.")
        for flow_id in FLOW_ORDER:
            flow_rules = tuple(rule for rule in self.rules if rule.flow_id == flow_id)
            roles = {rule.discovery_role for rule in flow_rules}
            if roles != {"primary-navigation", "related-navigation"}:
                raise ValueError("Every flow requires primary and related navigation examples.")
            _unique(tuple(rule.program_id for rule in flow_rules), "Flow program IDs")
            role_positions = tuple(
                0 if rule.discovery_role == "primary-navigation" else 1 for rule in flow_rules
            )
            if role_positions != tuple(sorted(role_positions)):
                raise ValueError("Primary navigation must precede related navigation.")
        return self

    def flow_rules(self, flow_id: str) -> tuple[DemoProgramRule, ...]:
        return tuple(rule for rule in self.rules if rule.flow_id == flow_id)


@dataclass(frozen=True, slots=True)
class RuleEvaluationEvidence:
    rule_set_version: str
    policy_effective_date: date
    evaluated_at: date
    source_versions: tuple[ProgramSourceVersion, ...]


def default_demo_program_rules_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data" / "demo-program-rules.json"
        if candidate.is_file() or (parent / "PRODUCT.md").is_file():
            return candidate
    return Path("/app/data/demo-program-rules.json")


def default_demo_catalog_path() -> Path:
    return default_demo_program_rules_path().with_name("pilot-catalog.json")


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DemoRuleSetError("Rule JSON contains a duplicate object property.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise DemoRuleSetError(f"Rule JSON contains unsupported constant {value}.")


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _without_key(value: dict[str, Any], key: str) -> dict[str, Any]:
    return {item_key: item for item_key, item in value.items() if item_key != key}


def _validate_hashes(document: dict[str, Any]) -> None:
    rules = document.get("rules")
    if type(rules) is not list:
        raise DemoRuleSetError("Rule set contains an invalid rules collection.")
    for rule in rules:
        if type(rule) is not dict or type(rule.get("ruleHash")) is not str:
            raise DemoRuleSetError("Rule set contains an invalid rule hash.")
        if _canonical_hash(_without_key(rule, "ruleHash")) != rule["ruleHash"]:
            raise DemoRuleSetError("A demo program rule failed its integrity check.")
    if type(document.get("ruleSetHash")) is not str:
        raise DemoRuleSetError("Rule set contains an invalid rule-set hash.")
    if _canonical_hash(_without_key(document, "ruleSetHash")) != document["ruleSetHash"]:
        raise DemoRuleSetError("The demo program rule set failed its integrity check.")


def _validate_catalog(rule_set: DemoProgramRuleSet, catalog: Catalog) -> None:
    if catalog.as_of != rule_set.catalog_as_of:
        raise DemoRuleSetError("The pinned catalogue version is unavailable.")
    catalog_sources = {source.id: source for source in catalog.sources}
    for review in rule_set.source_reviews:
        source = catalog_sources.get(review.source_id)
        if source is None:
            if review.coverage != MISSING_COVERAGE or review.catalog_status != "absent":
                raise DemoRuleSetError("A source review does not resolve in the pinned catalogue.")
            continue
        if source.status != review.catalog_status or source.checked_at != review.catalog_checked_at:
            raise DemoRuleSetError("A source review does not match the pinned catalogue version.")
        if review.coverage == REVIEWED_COVERAGE and source.status not in (
            "available",
            "limited",
        ):
            raise DemoRuleSetError("A reviewed source is not available for navigation.")
        if review.coverage == MISSING_COVERAGE and source.status in ("available", "limited"):
            raise DemoRuleSetError("A missing source marker conflicts with the catalogue.")


def parse_demo_program_rule_json(
    payload: bytes,
    *,
    catalog_payload: bytes,
) -> DemoProgramRuleSet:
    if len(payload) > MAX_RULE_SET_BYTES:
        raise DemoRuleSetError("Demo program rule data exceeds its size limit.")
    if len(catalog_payload) > MAX_CATALOG_BYTES:
        raise DemoRuleSetError("The source catalogue exceeds its size limit.")
    try:
        document = json.loads(
            payload,
            object_pairs_hook=_strict_object_pairs,
            parse_constant=_reject_json_constant,
        )
    except DemoRuleSetError:
        raise
    except UnicodeDecodeError, json.JSONDecodeError:
        raise DemoRuleSetError("Demo program rule data is not valid UTF-8 JSON.") from None
    if type(document) is not dict:
        raise DemoRuleSetError("Demo program rule data must be a JSON object.")
    _validate_hashes(document)
    try:
        rule_set = DemoProgramRuleSet.model_validate(
            document,
            by_alias=True,
            by_name=False,
        )
        catalog = Catalog.model_validate_json(
            catalog_payload,
            by_alias=True,
            by_name=False,
        )
    except ValidationError, ValueError:
        raise DemoRuleSetError("Demo program rule or source data failed validation.") from None
    _validate_catalog(rule_set, catalog)
    return rule_set


def load_demo_program_rule_set(
    path: Path | None = None,
    catalog_path: Path | None = None,
) -> DemoProgramRuleSet:
    rule_path = path or default_demo_program_rules_path()
    source_path = catalog_path or default_demo_catalog_path()
    try:
        payload = rule_path.read_bytes()
        catalog_payload = source_path.read_bytes()
    except OSError:
        raise DemoRuleSetError("Demo program rule or source data is unavailable.") from None
    return parse_demo_program_rule_json(payload, catalog_payload=catalog_payload)


class DemoProgramRuleRepository:
    def __init__(
        self,
        path: Path | None = None,
        catalog_path: Path | None = None,
    ) -> None:
        self.path = path or default_demo_program_rules_path()
        self.catalog_path = catalog_path or default_demo_catalog_path()
        self._version: tuple[int, int, int, int] | None = None
        self._rule_set: DemoProgramRuleSet | None = None

    def get(self) -> DemoProgramRuleSet:
        try:
            rule_stat = self.path.stat()
            catalog_stat = self.catalog_path.stat()
        except OSError:
            self._rule_set = None
            raise DemoRuleSetError("Demo program rule or source data is unavailable.") from None
        version = (
            rule_stat.st_mtime_ns,
            rule_stat.st_size,
            catalog_stat.st_mtime_ns,
            catalog_stat.st_size,
        )
        if self._rule_set is None or self._version != version:
            self._rule_set = None
            self._rule_set = load_demo_program_rule_set(self.path, self.catalog_path)
            self._version = version
        return self._rule_set


def reviewed_source_versions(rule_set: DemoProgramRuleSet) -> tuple[ProgramSourceVersion, ...]:
    return tuple(
        ProgramSourceVersion(source_id=review.source_id, version=review.catalog_checked_at)
        for review in rule_set.source_reviews
        if review.coverage == REVIEWED_COVERAGE and review.catalog_checked_at is not None
    )


def _evaluation_failure(
    code: str,
    message: str,
    *,
    program_id: str | None = None,
    missing_fact_keys: Sequence[str] = (),
) -> DemoRuleEvaluationError:
    return DemoRuleEvaluationError(
        code,
        message,
        program_id=program_id,
        missing_fact_keys=missing_fact_keys,
    )


def _active_on(start: str, end: str | None, value: date) -> bool:
    return _parsed_date(start) <= value and (end is None or value < _parsed_date(end))


def _condition_matches(condition: RuleCondition, actual: object) -> bool:
    if condition.operator == "equals":
        return _same_scalar(actual, condition.expected)
    if condition.operator == "in":
        if type(condition.expected) is not tuple:
            raise _evaluation_failure(
                "unsupported-operator",
                "A configured screening condition is unavailable.",
            )
        return any(_same_scalar(actual, expected) for expected in condition.expected)
    if condition.operator == "at-least":
        if (
            type(actual) not in (int, float)
            or isinstance(actual, bool)
            or type(condition.expected) not in (int, float)
            or isinstance(condition.expected, bool)
        ):
            return False
        return actual >= condition.expected
    raise _evaluation_failure(
        "unsupported-operator",
        "A configured screening condition is unavailable.",
    )


def _collect_facts(
    context_facts: Iterable[ContextFact],
    citizen_answers: Iterable[ContextFact],
) -> dict[str, ContextFact]:
    collected: dict[str, ContextFact] = {}
    for items, expected_provenance in (
        (context_facts, "synthetic-government-record"),
        (citizen_answers, "citizen-answer"),
    ):
        try:
            facts = tuple(items)
        except TypeError:
            raise _evaluation_failure(
                "invalid-fact-input",
                "Screening facts must use the approved typed fact contract.",
            ) from None
        for fact in facts:
            if not isinstance(fact, ContextFact) or fact.provenance != expected_provenance:
                raise _evaluation_failure(
                    "invalid-fact-input",
                    "Screening facts must use the approved typed fact contract.",
                )
            if fact.key in collected:
                raise _evaluation_failure(
                    "duplicate-fact",
                    "A screening fact was supplied more than once.",
                )
            collected[fact.key] = fact
    return collected


def _source_version_map(
    source_versions: Sequence[ProgramSourceVersion],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for source_version in source_versions:
        if not isinstance(source_version, ProgramSourceVersion):
            raise _evaluation_failure(
                "source-version-unavailable",
                "Reviewed source evidence is unavailable.",
            )
        if source_version.source_id in result:
            raise _evaluation_failure(
                "source-version-unavailable",
                "Reviewed source evidence is unavailable.",
            )
        result[source_version.source_id] = source_version.version
    return result


def _select_rules(
    rule_set: DemoProgramRuleSet,
    flow_id: str,
    program_ids: Sequence[str] | None,
) -> tuple[DemoProgramRule, ...]:
    if flow_id not in FLOW_ORDER:
        raise _evaluation_failure("unknown-flow", "Choose a supported demo screening flow.")
    flow_rules = rule_set.flow_rules(flow_id)
    if program_ids is None:
        return flow_rules
    if isinstance(program_ids, (str, bytes)):
        raise _evaluation_failure(
            "unknown-program",
            "Choose a supported program for this demo screening flow.",
        )
    requested = tuple(program_ids)
    if not requested or any(type(program_id) is not str for program_id in requested):
        raise _evaluation_failure(
            "unknown-program",
            "Choose a supported program for this demo screening flow.",
        )
    if len(requested) != len(set(requested)):
        raise _evaluation_failure(
            "duplicate-program",
            "Each program may be screened only once.",
        )
    available = {rule.program_id for rule in flow_rules}
    if not set(requested) <= available:
        raise _evaluation_failure(
            "unknown-program",
            "Choose a supported program for this demo screening flow.",
        )
    requested_set = set(requested)
    return tuple(rule for rule in flow_rules if rule.program_id in requested_set)


def _verify_evidence(
    rule_set: DemoProgramRuleSet,
    rules: Sequence[DemoProgramRule],
    evidence: RuleEvaluationEvidence,
) -> dict[str, str]:
    if not isinstance(evidence, RuleEvaluationEvidence):
        raise _evaluation_failure(
            "rule-version-unavailable",
            "Pinned screening evidence is unavailable.",
        )
    if (
        type(evidence.policy_effective_date) is not date
        or type(evidence.evaluated_at) is not date
        or evidence.rule_set_version != rule_set.rule_set_version
    ):
        raise _evaluation_failure(
            "rule-version-unavailable",
            "Pinned screening evidence is unavailable.",
        )
    if not _active_on(
        rule_set.effective_from,
        rule_set.effective_to,
        evidence.policy_effective_date,
    ):
        raise _evaluation_failure(
            "policy-out-of-date",
            "The requested screening policy version is not in effect.",
        )
    if not (
        _parsed_date(rule_set.reviewed_at)
        <= evidence.evaluated_at
        <= _parsed_date(rule_set.review_due)
    ):
        raise _evaluation_failure(
            "policy-out-of-date",
            "The screening rule review is not current.",
        )

    source_versions = _source_version_map(evidence.source_versions)
    reviews = {review.source_id: review for review in rule_set.source_reviews}
    for rule in rules:
        if rule.version != evidence.rule_set_version:
            raise _evaluation_failure(
                "rule-version-unavailable",
                "Pinned screening evidence is unavailable.",
                program_id=rule.program_id,
            )
        if not _active_on(rule.effective_from, rule.effective_to, evidence.policy_effective_date):
            raise _evaluation_failure(
                "policy-out-of-date",
                "A requested screening rule is not in effect.",
                program_id=rule.program_id,
            )
        if not (
            _parsed_date(rule.reviewed_at) <= evidence.evaluated_at <= _parsed_date(rule.review_due)
        ):
            raise _evaluation_failure(
                "policy-out-of-date",
                "A requested screening rule review is not current.",
                program_id=rule.program_id,
            )
        if rule.source_coverage != REVIEWED_COVERAGE:
            raise _evaluation_failure(
                "required-evidence-unavailable",
                "Reviewed source coverage is unavailable for this navigation.",
                program_id=rule.program_id,
            )
        for source_id in rule.source_ids:
            review = reviews[source_id]
            if review.coverage != REVIEWED_COVERAGE:
                raise _evaluation_failure(
                    "required-evidence-unavailable",
                    "Reviewed source coverage is unavailable for this navigation.",
                    program_id=rule.program_id,
                )
            if not (
                _parsed_date(review.reviewed_at)
                <= evidence.evaluated_at
                <= _parsed_date(review.review_due)
            ):
                raise _evaluation_failure(
                    "source-version-unavailable",
                    "A required source review is not current.",
                    program_id=rule.program_id,
                )
            if source_versions.get(source_id) != review.catalog_checked_at:
                raise _evaluation_failure(
                    "source-version-unavailable",
                    "Reviewed source evidence is unavailable.",
                    program_id=rule.program_id,
                )
    return source_versions


def _evaluate_rule(
    rule: DemoProgramRule,
    facts: dict[str, ContextFact],
    evidence: RuleEvaluationEvidence,
    source_versions: dict[str, str],
) -> ProgramMatch:
    enrollment = rule.already_enrolled_condition
    if enrollment is not None:
        enrollment_fact = facts.get(enrollment.fact_key)
        if enrollment_fact is not None and _condition_matches(enrollment, enrollment_fact.value):
            return ProgramMatch(
                program_id=rule.program_id,
                status="already-enrolled",
                rule_id=rule.rule_id,
                rule_version=rule.version,
                policy_effective_date=evidence.policy_effective_date.isoformat(),
                satisfied_conditions=[enrollment.satisfied_label],
                missing_facts=[],
                disqualifying_facts=[],
                source_ids=list(rule.source_ids),
                source_versions=[
                    ProgramSourceVersion(source_id=source_id, version=source_versions[source_id])
                    for source_id in rule.source_ids
                ],
                notice=SCREENING_NOTICE,
            )

    missing = tuple(item for item in rule.required_facts if item.fact_key not in facts)
    satisfied: list[str] = []
    disqualifying: list[str] = []
    for condition in rule.conditions:
        fact = facts.get(condition.fact_key)
        if fact is None:
            continue
        if _condition_matches(condition, fact.value):
            satisfied.append(condition.satisfied_label)
        else:
            disqualifying.append(condition.not_satisfied_label)
    for condition in rule.optional_conditions:
        fact = facts.get(condition.fact_key)
        if fact is not None and _condition_matches(condition, fact.value):
            satisfied.append(condition.satisfied_label)

    if disqualifying:
        status = "not-indicated"
    elif missing:
        if rule.missing_fact_behavior != MISSING_FACT_BEHAVIOR:
            raise _evaluation_failure(
                "rule-unavailable",
                "The configured missing-information behavior is unavailable.",
                program_id=rule.program_id,
            )
        status = "needs-information"
    else:
        status = "potential-match"

    return ProgramMatch(
        program_id=rule.program_id,
        status=status,
        rule_id=rule.rule_id,
        rule_version=rule.version,
        policy_effective_date=evidence.policy_effective_date.isoformat(),
        satisfied_conditions=satisfied,
        missing_facts=[item.public_missing_fact_key for item in missing],
        disqualifying_facts=disqualifying,
        source_ids=list(rule.source_ids),
        source_versions=[
            ProgramSourceVersion(source_id=source_id, version=source_versions[source_id])
            for source_id in rule.source_ids
        ],
        notice=SCREENING_NOTICE,
    )


_PROGRAM_MATCHES = TypeAdapter(ProgramMatches)


class DemoProgramRuleEngine:
    def __init__(self, repository: DemoProgramRuleRepository | None = None) -> None:
        self._repository = repository or DemoProgramRuleRepository()

    def evaluate(
        self,
        *,
        flow_id: str,
        context_facts: Iterable[ContextFact],
        citizen_answers: Iterable[ContextFact] = (),
        evidence: RuleEvaluationEvidence,
        program_ids: Sequence[str] | None = None,
    ) -> list[ProgramMatch]:
        rule_set = self._repository.get()
        rules = _select_rules(rule_set, flow_id, program_ids)
        source_versions = _verify_evidence(rule_set, rules, evidence)
        facts = _collect_facts(context_facts, citizen_answers)
        try:
            matches = [_evaluate_rule(rule, facts, evidence, source_versions) for rule in rules]
            return _PROGRAM_MATCHES.validate_python(matches)
        except DemoRuleEvaluationError:
            raise
        except ValidationError, ValueError, KeyError:
            raise _evaluation_failure(
                "rule-result-invalid",
                "The screening result failed its strict output contract.",
            ) from None


_DEFAULT_ENGINE = DemoProgramRuleEngine()


def evaluate_program_rules(
    *,
    flow_id: str,
    context_facts: Iterable[ContextFact],
    citizen_answers: Iterable[ContextFact] = (),
    evidence: RuleEvaluationEvidence,
    program_ids: Sequence[str] | None = None,
) -> list[ProgramMatch]:
    """Evaluate the repository-owned rules without interpreting conversation text."""

    return _DEFAULT_ENGINE.evaluate(
        flow_id=flow_id,
        context_facts=context_facts,
        citizen_answers=citizen_answers,
        evidence=evidence,
        program_ids=program_ids,
    )
