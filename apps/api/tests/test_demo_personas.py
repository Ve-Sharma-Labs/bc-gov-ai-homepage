import copy
import json
import re

import pytest

from bc_api.demo_personas import (
    CONTEXT_CATEGORIES,
    PERSONA_IDS,
    DemoPersonaFixtureError,
    DemoPersonaRepository,
    DemoPersonaSelectionError,
    default_demo_personas_path,
    load_demo_persona_fixture,
    parse_demo_persona_json,
    validate_demo_persona_document,
)


def _raw_fixture() -> dict:
    return json.loads(default_demo_personas_path().read_text(encoding="utf-8"))


def _all_strings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_strings(item)
    elif isinstance(value, str):
        yield value


def test_fixture_contains_exactly_three_fixed_personas_and_no_anonymous_record():
    fixture = load_demo_persona_fixture()
    assert fixture.schema_version == 1
    assert tuple(persona.id for persona in fixture.personas) == PERSONA_IDS
    assert len(fixture.personas) == 3
    assert "anonymous" not in {persona.id for persona in fixture.personas}
    assert all(
        any(group.facts for group in persona.category_facts)
        and any(group.missing_fact_keys for group in persona.category_facts)
        for persona in fixture.personas
    )


def test_public_summaries_are_safe_redacted_and_deterministic():
    repository = DemoPersonaRepository()
    first = [summary.as_dict() for summary in repository.public_summaries()]
    second = [summary.as_dict() for summary in repository.public_summaries()]
    assert first == second
    assert [item["id"] for item in first] == list(PERSONA_IDS)
    assert all(
        set(item)
        == {
            "id",
            "displayName",
            "summary",
            "availableCategories",
            "synthetic",
        }
        for item in first
    )
    assert all(item["synthetic"] is True for item in first)
    assert all("fictional" in item["summary"].casefold() for item in first)
    public_json = json.dumps(first)
    assert all(
        forbidden not in public_json
        for forbidden in ("categoryFacts", "verifiedAt", "consentScope", "mutableByCitizen")
    )


def test_fixture_has_no_contact_address_or_identifier_patterns():
    patterns = (
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
    assert not [
        text
        for text in _all_strings(_raw_fixture())
        if any(pattern.search(text) for pattern in patterns)
    ]


def test_category_fact_and_missing_key_order_is_canonical():
    fixture = load_demo_persona_fixture()
    for persona in fixture.personas:
        assert tuple(group.category for group in persona.category_facts) == CONTEXT_CATEGORIES
        for group in persona.category_facts:
            fact_keys = tuple(fact.key for fact in group.facts)
            assert fact_keys == tuple(sorted(fact_keys))
            assert group.missing_fact_keys == tuple(sorted(group.missing_fact_keys))


def test_anonymous_is_absence_and_arbitrary_client_facts_are_rejected():
    repository = DemoPersonaRepository()
    assert repository.resolve_client_persona(None) is None
    assert repository.resolve_client_persona("maya-caregiver").display_name == "Maya"
    with pytest.raises(DemoPersonaSelectionError):
        repository.resolve_client_persona(
            {"personaId": "maya-caregiver", "facts": [{"key": "forged", "value": True}]}
        )
    with pytest.raises(DemoPersonaSelectionError):
        repository.resolve_client_persona("anonymous")
    with pytest.raises(DemoPersonaSelectionError):
        repository.resolve_client_persona("arbitrary-persona")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["personas"].append(copy.deepcopy(data["personas"][0])),
        lambda data: data["personas"][0].update(id="unreviewed-persona"),
        lambda data: data["personas"][0].update(
            publicSummary=(
                "A fictional resident with an unsafe contact value of person@example.com."
            )
        ),
        lambda data: data["personas"][0]["categoryFacts"].append(
            copy.deepcopy(data["personas"][0]["categoryFacts"][0])
        ),
        lambda data: data["personas"][0]["categoryFacts"][0]["facts"].append(
            copy.deepcopy(data["personas"][0]["categoryFacts"][0]["facts"][0])
        ),
        lambda data: data["personas"][0]["categoryFacts"][0]["facts"][0].update(
            category="household-dependants"
        ),
        lambda data: data["personas"][0]["categoryFacts"][0]["facts"][0].update(
            consentScope="household.read"
        ),
        lambda data: data["personas"][0]["categoryFacts"][1]["missingFactKeys"].append(
            "household.shared-residence"
        ),
        lambda data: data.update(unreviewed=True),
    ],
)
def test_strict_validation_rejects_duplicates_categories_scopes_and_extra_fields(mutate):
    data = _raw_fixture()
    mutate(data)
    with pytest.raises(DemoPersonaFixtureError):
        validate_demo_persona_document(data)


def test_json_parser_rejects_duplicate_object_properties():
    with pytest.raises(DemoPersonaFixtureError, match="duplicate object property"):
        parse_demo_persona_json(b'{"schemaVersion": 1, "schemaVersion": 1}')
