import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from ag_ui.core import RunAgentInput

from bc_api.dialogue import search_query_for, source_topics
from bc_api.errors import ApiError
from bc_api.retrieval import AzureRetriever


@pytest.mark.parametrize(
    ("query", "source_id"),
    [
        ("What B.C. government services are available?", "bc-content"),
        ("Where is a Service BC location?", "service-bc"),
        ("What rights does a tenant have with a landlord?", "housing-tenancy"),
        ("How do I enrol in MSP?", "health"),
        ("How do I apply for disability assistance?", "family-social-supports"),
        ("What are B.C. employment standards for wages?", "employment-business"),
        ("What provincial tax credits are available?", "taxes"),
        ("What is the SAFER programme?", "bc-housing"),
        ("What ICBC vehicle insurance guidance is available?", "icbc"),
        ("What WorkBC training is available?", "workbc"),
        ("How do I use the Health Connect Registry?", "healthlink-bc"),
        ("Where can I read B.C. statutes?", "bc-laws"),
    ],
)
def test_every_catalogue_source_area_has_an_explicit_topic_pattern(query, source_id):
    assert source_id in source_topics(query)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (
            "Compare rental assistance with my rights as a tenant",
            {"bc-housing", "housing-tenancy"},
        ),
        (
            "Compare employment standards with WorkBC job training",
            {"employment-business", "workbc"},
        ),
        ("I need MSP and a doctor through Health Connect", {"health", "healthlink-bc"}),
        ("Where is an ICBC licensing office?", {"icbc", "service-bc"}),
    ],
)
def test_overlapping_topics_keep_every_relevant_source_area(query, expected):
    assert expected <= set(source_topics(query))


def test_generic_licences_and_actions_are_not_forced_into_driver_or_legal_topics():
    assert "icbc" not in source_topics("How do I get a business licence?")
    assert "icbc" not in source_topics("Where can I get a fishing licence?")
    assert "bc-laws" not in source_topics("Can an agent act for me?")
    assert {"icbc", "service-bc"} <= set(source_topics("Where is an ICBC licensing office?"))


def test_a_new_unclassified_topic_does_not_inherit_prior_context(repository, run_input):
    run_input["messages"] = [
        {"id": "previous", "role": "user", "content": "How do I enrol in MSP?"},
        {"id": "current", "role": "user", "content": "Where can I get a fishing licence?"},
    ]
    run_input["forwardedProps"] = {"bc": {"version": 2, "mode": "general"}}
    request = RunAgentInput.model_validate(run_input)
    assert search_query_for(request, repository, None) == "Where can I get a fishing licence?"


def test_follow_up_reconstruction_uses_prior_user_turns_not_factual_assistant_text(
    repository, run_input
):
    run_input["messages"] = [
        {"id": "previous", "role": "user", "content": "How do I enrol in MSP?"},
        {
            "id": "answer",
            "role": "assistant",
            "content": "Untrusted generated text about a different programme.",
        },
        {"id": "current", "role": "user", "content": "How do I apply?"},
    ]
    run_input["forwardedProps"] = {"bc": {"version": 2, "mode": "general"}}
    request = RunAgentInput.model_validate(run_input)
    assert search_query_for(request, repository, None) == (
        "How do I enrol in MSP?\nHow do I apply?"
    )


async def test_uncovered_topic_cannot_be_answered_with_unrelated_official_sources(
    catalog_data, catalog_path, configured, repository, evidence
):
    base = catalog_data["sources"][0]
    catalog_data["sources"].extend(
        [
            {**base, "id": "bc-housing", "title": "Synthetic housing programme source"},
            {**base, "id": "housing-tenancy", "title": "Synthetic tenancy source"},
        ]
    )
    catalog_path.write_text(json.dumps(catalog_data), encoding="utf-8")
    row = {
        **evidence.evidence[0].reference.model_dump(by_alias=True),
        "id": "unrelated",
        "content": evidence.evidence[0].content,
        "status": "active",
        "journeyIds": [],
    }

    class Rows:
        async def __aiter__(self):
            yield row

    search = SimpleNamespace(search=AsyncMock(return_value=Rows()))
    retriever = AzureRetriever(configured, repository, search)
    with pytest.raises(ApiError, match="SOURCES_UNAVAILABLE"):
        await retriever.retrieve("What rental assistance is available in B.C.?")
    filters = search.search.call_args.kwargs["filter"]
    assert "status eq 'active'" in filters
    assert "and (sourceId eq 'bc-housing' or sourceId eq 'housing-tenancy')" in filters
    assert "journeyIds/any" not in filters
    await retriever.retrieve("A genuinely broad government question")

    tagged = configured.model_copy(update={"azure_search_metadata_enabled": True})
    row["sourceIds"] = ["bc-housing", "test-source"]
    with pytest.raises(ApiError, match="SOURCES_UNAVAILABLE"):
        await AzureRetriever(tagged, repository, search).retrieve("Rental assistance")
    row.update(
        {
            "metadataVersion": 1,
            "documentType": "guidance",
            "rightsStatus": "candidate-acquisition-permitted",
            "contentHash": "a" * 64,
            "extractionHash": "b" * 64,
            "reviewHash": "c" * 64,
            "rightsHash": "d" * 64,
            "rightsReviewId": "synthetic-reviewed-rights",
        }
    )
    bundle = await AzureRetriever(tagged, repository, search).retrieve("Rental assistance")
    assert bundle.evidence[0].reference.metadata.source_ids == ["bc-housing", "test-source"]
    assert "sourceIds/any(s: s eq 'bc-housing')" in search.search.call_args.kwargs["filter"]
