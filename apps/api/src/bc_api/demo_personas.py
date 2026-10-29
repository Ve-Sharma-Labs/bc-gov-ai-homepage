import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
FIXTURE_ID = "citizen-context-demo-v1"
MAX_FIXTURE_BYTES = 256_000

PERSONA_IDS = (
    "maya-caregiver",
    "alex-disability-support",
    "sam-job-loss",
)
PERSONA_DISPLAY_NAMES = {
    "maya-caregiver": "Maya",
    "alex-disability-support": "Alex",
    "sam-job-loss": "Sam",
}
CONTEXT_CATEGORIES = (
    "identity-residency",
    "household-dependants",
    "employment-income",
    "disability-caregiving",
    "existing-programs",
    "region-preferences",
)
CONSENT_SCOPE_BY_CATEGORY = {
    "identity-residency": "identity.read",
    "household-dependants": "household.read",
    "employment-income": "employment.read",
    "disability-caregiving": "disability-caregiving.read",
    "existing-programs": "existing-programs.read",
    "region-preferences": "region-preferences.read",
}
SOURCE_BY_CATEGORY = {
    "identity-residency": "synthetic-demo-identity-registry",
    "household-dependants": "synthetic-demo-household-registry",
    "employment-income": "synthetic-demo-employment-system",
    "disability-caregiving": "synthetic-demo-care-support-system",
    "existing-programs": "synthetic-demo-program-registry",
    "region-preferences": "synthetic-demo-service-preferences",
}
SENSITIVITIES = frozenset({"personal", "protected-a", "protected-b"})
FACT_KEY = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
SUSPICIOUS_PII = (
    re.compile(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", re.IGNORECASE),
    re.compile(r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}"),
    re.compile(
        r"\b[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTVWXYZ][ -]?\d"
        r"[ABCEGHJ-NPRSTVWXYZ]\d\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d{9,12}\b"),
    re.compile(
        r"\b\d{1,5}\s+(?:[a-z]+\s+){0,3}"
        r"(?:street|st|road|rd|avenue|ave|boulevard|blvd|drive|dr|lane|ln)\b",
        re.IGNORECASE,
    ),
)

_ROOT_KEYS = {
    "schemaVersion",
    "fixtureId",
    "synthetic",
    "notice",
    "fixtureProvenance",
    "personas",
}
_PROVENANCE_KEYS = {"origin", "productionDataUsed", "intendedUse", "reviewedAt"}
_PERSONA_KEYS = {"id", "displayName", "publicSummary", "categoryFacts"}
_GROUP_KEYS = {"category", "facts", "missingFactKeys"}
_FACT_KEYS = {
    "key",
    "value",
    "category",
    "source",
    "provenance",
    "verifiedAt",
    "sensitivity",
    "consentScope",
    "mutableByCitizen",
}

JsonScalar = str | int | bool


class DemoPersonaFixtureError(ValueError):
    """The repository-owned synthetic fixture failed closed validation."""


class DemoPersonaSelectionError(ValueError):
    """A caller attempted to select anything other than an allowlisted persona ID."""


@dataclass(frozen=True, slots=True)
class DemoContextFact:
    key: str
    value: JsonScalar
    category: str
    source: str
    provenance: str
    verified_at: str
    sensitivity: str
    consent_scope: str
    mutable_by_citizen: bool


@dataclass(frozen=True, slots=True)
class DemoFactGroup:
    category: str
    facts: tuple[DemoContextFact, ...]
    missing_fact_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PublicPersonaSummary:
    id: str
    display_name: str
    summary: str
    available_categories: tuple[str, ...]
    synthetic: bool = True

    def as_dict(self) -> dict[str, str | bool | list[str]]:
        return {
            "id": self.id,
            "displayName": self.display_name,
            "summary": self.summary,
            "availableCategories": list(self.available_categories),
            "synthetic": self.synthetic,
        }


@dataclass(frozen=True, slots=True)
class DemoPersona:
    id: str
    display_name: str
    public_summary: str
    category_facts: tuple[DemoFactGroup, ...]

    def public(self) -> PublicPersonaSummary:
        return PublicPersonaSummary(
            id=self.id,
            display_name=self.display_name,
            summary=self.public_summary,
            available_categories=tuple(
                group.category for group in self.category_facts if group.facts
            ),
        )

    def fact(self, key: str) -> DemoContextFact | None:
        return next(
            (fact for group in self.category_facts for fact in group.facts if fact.key == key),
            None,
        )


@dataclass(frozen=True, slots=True)
class DemoPersonaFixture:
    schema_version: int
    fixture_id: str
    notice: str
    provenance_origin: str
    intended_use: str
    reviewed_at: str
    personas: tuple[DemoPersona, ...]


def default_demo_personas_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data" / "demo-personas.json"
        if candidate.is_file() or (parent / "PRODUCT.md").is_file():
            return candidate
    return Path("/app/data/demo-personas.json")


def _invalid(path: str, message: str) -> DemoPersonaFixtureError:
    return DemoPersonaFixtureError(f"{path}: {message}")


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DemoPersonaFixtureError("JSON contains a duplicate object property.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise DemoPersonaFixtureError(f"JSON contains unsupported constant {value}.")


def parse_demo_persona_json(payload: bytes) -> DemoPersonaFixture:
    if len(payload) > MAX_FIXTURE_BYTES:
        raise DemoPersonaFixtureError("Synthetic persona fixture exceeds its size limit.")
    try:
        document = json.loads(
            payload,
            object_pairs_hook=_strict_object_pairs,
            parse_constant=_reject_json_constant,
        )
    except DemoPersonaFixtureError:
        raise
    except UnicodeDecodeError, json.JSONDecodeError:
        raise DemoPersonaFixtureError(
            "Synthetic persona fixture is not valid UTF-8 JSON."
        ) from None
    return validate_demo_persona_document(document)


def load_demo_persona_fixture(path: Path | None = None) -> DemoPersonaFixture:
    fixture_path = path or default_demo_personas_path()
    try:
        payload = fixture_path.read_bytes()
    except OSError:
        raise DemoPersonaFixtureError("Synthetic persona fixture is unavailable.") from None
    return parse_demo_persona_json(payload)


def _object(value: Any, path: str, expected_keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict:
        raise _invalid(path, "must be an object")
    keys = set(value)
    if keys != expected_keys:
        raise _invalid(path, "contains unsupported or missing properties")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if type(value) is not list:
        raise _invalid(path, "must be an array")
    return value


def _string(value: Any, path: str, *, minimum: int = 1, maximum: int = 160) -> str:
    if (
        type(value) is not str
        or not minimum <= len(value) <= maximum
        or not value.isprintable()
        or value != value.strip()
    ):
        raise _invalid(path, "must be a bounded printable string")
    return value


def _timestamp(value: Any, path: str) -> str:
    text = _string(value, path, maximum=20)
    if not text.endswith("Z"):
        raise _invalid(path, "must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(text.removesuffix("Z") + "+00:00")
    except ValueError:
        raise _invalid(path, "must be a valid timestamp") from None
    if parsed.tzinfo != UTC or parsed.microsecond:
        raise _invalid(path, "must be a second-precision UTC timestamp")
    if parsed.isoformat(timespec="seconds").replace("+00:00", "Z") != text:
        raise _invalid(path, "must use canonical ISO 8601 UTC format")
    return text


def _fact_key(value: Any, path: str) -> str:
    key = _string(value, path, maximum=80)
    if not FACT_KEY.fullmatch(key):
        raise _invalid(path, "must use a namespaced lower-case fact key")
    return key


def _safe_public_text(value: Any, path: str) -> str:
    text = _string(value, path, minimum=40, maximum=220)
    if "fictional" not in text.casefold():
        raise _invalid(path, "must explicitly say that the persona is fictional")
    if any(pattern.search(text) for pattern in SUSPICIOUS_PII):
        raise _invalid(path, "must not contain contact, address, or identifier-like data")
    return text


def _scalar(value: Any, path: str) -> JsonScalar:
    if type(value) is bool:
        return value
    if type(value) is int and 0 <= value <= 120:
        return value
    if type(value) is str:
        text = _string(value, path, maximum=80)
        if any(pattern.search(text) for pattern in SUSPICIOUS_PII):
            raise _invalid(path, "contains identifier-like data")
        return text
    raise _invalid(path, "must be a bounded string, boolean, or small non-negative integer")


def _parse_fact(value: Any, path: str, group_category: str) -> DemoContextFact:
    item = _object(value, path, _FACT_KEYS)
    category = _string(item["category"], f"{path}.category", maximum=40)
    if category != group_category:
        raise _invalid(f"{path}.category", "must match its containing category")
    expected_scope = CONSENT_SCOPE_BY_CATEGORY[group_category]
    consent_scope = _string(item["consentScope"], f"{path}.consentScope", maximum=40)
    if consent_scope != expected_scope:
        raise _invalid(f"{path}.consentScope", "is not allowed for this category")
    source = _string(item["source"], f"{path}.source", maximum=80)
    if source != SOURCE_BY_CATEGORY[group_category]:
        raise _invalid(f"{path}.source", "is not the synthetic source for this category")
    provenance = _string(item["provenance"], f"{path}.provenance", maximum=40)
    if provenance != "synthetic-government-record":
        raise _invalid(f"{path}.provenance", "must be synthetic-government-record")
    sensitivity = _string(item["sensitivity"], f"{path}.sensitivity", maximum=20)
    if sensitivity not in SENSITIVITIES:
        raise _invalid(f"{path}.sensitivity", "is not supported")
    if type(item["mutableByCitizen"]) is not bool:
        raise _invalid(f"{path}.mutableByCitizen", "must be a boolean")
    return DemoContextFact(
        key=_fact_key(item["key"], f"{path}.key"),
        value=_scalar(item["value"], f"{path}.value"),
        category=category,
        source=source,
        provenance=provenance,
        verified_at=_timestamp(item["verifiedAt"], f"{path}.verifiedAt"),
        sensitivity=sensitivity,
        consent_scope=consent_scope,
        mutable_by_citizen=item["mutableByCitizen"],
    )


def _parse_group(value: Any, path: str) -> DemoFactGroup:
    item = _object(value, path, _GROUP_KEYS)
    category = _string(item["category"], f"{path}.category", maximum=40)
    if category not in CONTEXT_CATEGORIES:
        raise _invalid(f"{path}.category", "is not an approved consent category")
    facts = tuple(
        _parse_fact(fact, f"{path}.facts[{index}]", category)
        for index, fact in enumerate(_list(item["facts"], f"{path}.facts"))
    )
    missing = tuple(
        _fact_key(key, f"{path}.missingFactKeys[{index}]")
        for index, key in enumerate(_list(item["missingFactKeys"], f"{path}.missingFactKeys"))
    )
    fact_keys = tuple(fact.key for fact in facts)
    if not facts and not missing:
        raise _invalid(path, "must contain a known or explicitly missing fact")
    if len(set(fact_keys)) != len(fact_keys):
        raise _invalid(f"{path}.facts", "contains duplicate fact keys")
    if len(set(missing)) != len(missing):
        raise _invalid(f"{path}.missingFactKeys", "contains duplicate fact keys")
    if set(fact_keys) & set(missing):
        raise _invalid(path, "cannot mark the same fact as both known and missing")
    if fact_keys != tuple(sorted(fact_keys)) or missing != tuple(sorted(missing)):
        raise _invalid(path, "fact keys must use deterministic lexical ordering")
    return DemoFactGroup(category=category, facts=facts, missing_fact_keys=missing)


def _parse_persona(value: Any, path: str) -> DemoPersona:
    item = _object(value, path, _PERSONA_KEYS)
    persona_id = _string(item["id"], f"{path}.id", maximum=40)
    if persona_id not in PERSONA_IDS:
        raise _invalid(f"{path}.id", "is not in the fixed persona allowlist")
    display_name = _string(item["displayName"], f"{path}.displayName", maximum=20)
    if display_name != PERSONA_DISPLAY_NAMES[persona_id]:
        raise _invalid(f"{path}.displayName", "does not match the fixed persona")
    groups = tuple(
        _parse_group(group, f"{path}.categoryFacts[{index}]")
        for index, group in enumerate(_list(item["categoryFacts"], f"{path}.categoryFacts"))
    )
    categories = tuple(group.category for group in groups)
    if len(set(categories)) != len(categories):
        raise _invalid(f"{path}.categoryFacts", "contains duplicate categories")
    if categories != CONTEXT_CATEGORIES:
        raise _invalid(
            f"{path}.categoryFacts",
            "must contain every approved category in deterministic order",
        )
    known_keys = [fact.key for group in groups for fact in group.facts]
    missing_keys = [key for group in groups for key in group.missing_fact_keys]
    if len(set(known_keys)) != len(known_keys):
        raise _invalid(f"{path}.categoryFacts", "contains duplicate fact keys")
    if len(set(missing_keys)) != len(missing_keys):
        raise _invalid(f"{path}.categoryFacts", "contains duplicate missing fact keys")
    if set(known_keys) & set(missing_keys):
        raise _invalid(f"{path}.categoryFacts", "contains facts that are both known and missing")
    if not known_keys or not missing_keys:
        raise _invalid(path, "must exercise both known-context and missing-information branches")
    return DemoPersona(
        id=persona_id,
        display_name=display_name,
        public_summary=_safe_public_text(item["publicSummary"], f"{path}.publicSummary"),
        category_facts=groups,
    )


def validate_demo_persona_document(value: Any) -> DemoPersonaFixture:
    document = _object(value, "$", _ROOT_KEYS)
    if type(document["schemaVersion"]) is not int or document["schemaVersion"] != SCHEMA_VERSION:
        raise _invalid("$.schemaVersion", "is not supported")
    fixture_id = _string(document["fixtureId"], "$.fixtureId", maximum=60)
    if fixture_id != FIXTURE_ID:
        raise _invalid("$.fixtureId", "is not supported")
    if document["synthetic"] is not True:
        raise _invalid("$.synthetic", "must be true")
    notice = _string(document["notice"], "$.notice", minimum=40, maximum=180)
    normalized_notice = notice.casefold()
    if (
        "synthetic" not in normalized_notice
        or "no real government records" not in normalized_notice
    ):
        raise _invalid("$.notice", "must clearly state the synthetic and no-records boundary")

    provenance = _object(document["fixtureProvenance"], "$.fixtureProvenance", _PROVENANCE_KEYS)
    origin = _string(provenance["origin"], "$.fixtureProvenance.origin", maximum=60)
    if origin != "hand-authored-fictional-fixture":
        raise _invalid("$.fixtureProvenance.origin", "must identify the fictional origin")
    if provenance["productionDataUsed"] is not False:
        raise _invalid("$.fixtureProvenance.productionDataUsed", "must be false")
    intended_use = _string(
        provenance["intendedUse"],
        "$.fixtureProvenance.intendedUse",
        minimum=40,
        maximum=180,
    )
    reviewed_at = _timestamp(
        provenance["reviewedAt"],
        "$.fixtureProvenance.reviewedAt",
    )

    personas = tuple(
        _parse_persona(persona, f"$.personas[{index}]")
        for index, persona in enumerate(_list(document["personas"], "$.personas"))
    )
    persona_ids = tuple(persona.id for persona in personas)
    if len(set(persona_ids)) != len(persona_ids):
        raise _invalid("$.personas", "contains duplicate persona IDs")
    if persona_ids != PERSONA_IDS:
        raise _invalid("$.personas", "must contain exactly the three fixed personas in order")
    return DemoPersonaFixture(
        schema_version=SCHEMA_VERSION,
        fixture_id=fixture_id,
        notice=notice,
        provenance_origin=origin,
        intended_use=intended_use,
        reviewed_at=reviewed_at,
        personas=personas,
    )


class DemoPersonaRepository:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_demo_personas_path()
        self._version: tuple[int, int] | None = None
        self._fixture: DemoPersonaFixture | None = None

    def fixture(self) -> DemoPersonaFixture:
        try:
            stat = self.path.stat()
        except OSError:
            self._fixture = None
            raise DemoPersonaFixtureError("Synthetic persona fixture is unavailable.") from None
        version = (stat.st_mtime_ns, stat.st_size)
        if self._fixture is None or self._version != version:
            self._fixture = None
            self._fixture = load_demo_persona_fixture(self.path)
            self._version = version
        return self._fixture

    def all(self) -> tuple[DemoPersona, ...]:
        return self.fixture().personas

    def public_summaries(self) -> tuple[PublicPersonaSummary, ...]:
        return tuple(persona.public() for persona in self.all())

    def get(self, persona_id: str) -> DemoPersona:
        if persona_id not in PERSONA_IDS:
            raise DemoPersonaSelectionError("Select one of the fixed synthetic personas.")
        return next(persona for persona in self.all() if persona.id == persona_id)

    def resolve_client_persona(self, value: object) -> DemoPersona | None:
        if value is None:
            return None
        if type(value) is not str:
            raise DemoPersonaSelectionError(
                "Only an allowlisted persona ID may select synthetic context."
            )
        return self.get(value)
