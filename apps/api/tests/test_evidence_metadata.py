import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bc_api.catalog import CatalogRepository
from bc_api.config import Settings
from bc_api.errors import ApiError
from bc_api.retrieval import AzureRetriever, evidence_metadata, legal_day


def guidance_row(evidence):
    return {
        **evidence.evidence[0].reference.model_dump(by_alias=True),
        "id": "legal-fixture",
        "content": "Synthetic reviewed evidence.",
        "status": "active",
        "metadataVersion": 1,
        "sourceIds": ["test-source"],
        "documentType": "guidance",
        "contentHash": "a" * 64,
        "extractionHash": "b" * 64,
        "reviewHash": "c" * 64,
        "rightsHash": "d" * 64,
        "rightsReviewId": "fixture-reviewed-rights",
        "rightsStatus": "candidate-acquisition-permitted",
        "language": "en",
    }


def legal_row(evidence):
    return {
        **guidance_row(evidence),
        "content": "Synthetic statutory evidence, not a real law.",
        "documentType": "legal",
        "legalStatus": "in-force",
        "effectiveFrom": "2020-01-01",
        "effectiveTo": None,
        "consolidationDate": "2026-01-01",
        "isHistorical": False,
    }


def test_british_columbia_calendar_day_is_not_the_utc_day():
    assert legal_day(datetime(2026, 10, 27, 1, tzinfo=UTC)) == "2026-10-26"
    assert legal_day(datetime(2026, 10, 27, 9, tzinfo=UTC)) == "2026-10-27"


def test_metadata_mode_rejects_legacy_rows_and_undated_statutes(evidence):
    with pytest.raises(ValueError):
        evidence_metadata({"sourceId": "test-source"}, {"test-source"}, "2026-10-26")
    with pytest.raises(ValueError):
        evidence_metadata({"sourceId": "bc-laws"}, {"bc-laws"}, "2026-10-26")
    row = legal_row(evidence)
    result = evidence_metadata(row, {"test-source"}, "2026-10-26")
    assert result.effective_from == "2020-01-01"
    assert result.consolidation_date == "2026-01-01"
    assert result.rights_review_id == "fixture-reviewed-rights"


@pytest.mark.parametrize(
    "change",
    [
        {"remove": "metadataVersion"},
        {"remove": "rightsStatus"},
        {"rightsStatus": "review-required"},
        {"remove": "rightsReviewId"},
        {"rightsReviewId": ""},
        {"rightsReviewId": " reviewed-with-spaces "},
        {"remove": "rightsHash"},
        {"rightsHash": "not-a-sha256"},
        {"remove": "reviewHash"},
        {"reviewHash": "not-a-sha256"},
        {"remove": "contentHash"},
        {"remove": "extractionHash"},
        {"sourceIds": []},
        {"documentType": None},
    ],
)
def test_missing_or_invalid_v2_rights_and_provenance_fail_closed(evidence, change):
    row = guidance_row(evidence)
    if "remove" in change:
        row.pop(change["remove"])
    else:
        row.update(change)
    with pytest.raises(ValueError):
        evidence_metadata(row, {"test-source"}, "2026-10-26")


@pytest.mark.parametrize(
    "change",
    [
        {"metadataVersion": True},
        {"metadataVersion": 2},
        {"rightsStatus": "review-required"},
        {"reviewHash": None},
        {"sourceIds": ["unregistered-source"]},
        {"effectiveFrom": None},
        {"effectiveFrom": "2027-01-01"},
        {"effectiveTo": "2026-10-26"},
        {"effectiveTo": "2010-01-01"},
        {"repealedAt": "2026-10-26"},
        {"legalStatus": "historical"},
        {"legalStatus": "not-yet-in-force"},
        {"isHistorical": True},
        {"isHistorical": None},
        {"effectiveFrom": "2020-01-01T00:00:00Z"},
    ],
)
def test_unreviewed_unknown_or_noncurrent_legal_versions_are_withheld(evidence, change):
    with pytest.raises(ValueError):
        evidence_metadata({**legal_row(evidence), **change}, {"test-source"}, "2026-10-26")


async def test_only_current_bc_laws_evidence_survives_retrieval(
    catalog_data, catalog_path, configured, evidence
):
    catalog_data["sources"].append(
        {
            **catalog_data["sources"][0],
            "id": "bc-laws",
            "title": "Synthetic BC Laws fixture",
            "url": "https://www.bclaws.gov.bc.ca/",
            "status": "available",
        }
    )
    catalog_path.write_text(json.dumps(catalog_data), encoding="utf-8")
    base = {
        **legal_row(evidence),
        "sourceId": "bc-laws",
        "sourceIds": ["bc-laws"],
        "publisher": "Government of British Columbia",
        "url": "https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/test",
    }
    rows = [
        {
            **base,
            "id": "historical",
            "documentId": "historical-law",
            "legalStatus": "historical",
            "isHistorical": True,
            "content": "Historical statutory fixture.",
        },
        {
            **base,
            "id": "repealed",
            "documentId": "repealed-law",
            "legalStatus": "repealed",
            "isHistorical": True,
            "repealedAt": "2025-01-01",
            "content": "Repealed statutory fixture.",
        },
        {
            **base,
            "id": "current",
            "documentId": "current-law",
            "content": "Current statutory fixture.",
        },
    ]

    class Rows:
        async def __aiter__(self):
            for row in rows:
                yield row

    search = SimpleNamespace(search=AsyncMock(return_value=Rows()))
    settings = configured.model_copy(
        update={
            "azure_search_index": "bc-pilot-public-v2",
            "azure_search_metadata_enabled": True,
            "azure_search_metadata_reviewed": True,
        }
    )
    bundle = await AzureRetriever(
        settings,
        CatalogRepository(catalog_path),
        search,
    ).retrieve("What does B.C. law say?")
    assert [item.reference.chunk_id for item in bundle.evidence] == ["current"]
    filters = search.search.call_args.kwargs["filter"]
    assert "sourceId eq 'bc-laws'" in filters
    assert "legalStatus eq 'in-force'" in filters
    assert "isHistorical eq false" in filters
    assert "repealedAt eq null or repealedAt gt" in filters


async def test_metadata_selection_is_explicit_and_filters_are_rechecked(
    configured, repository, evidence
):
    class Rows:
        def __init__(self, row):
            self.row = row

        async def __aiter__(self):
            yield self.row

    row = legal_row(evidence)
    search = SimpleNamespace(search=AsyncMock(return_value=Rows(row)))
    settings = configured.model_copy(
        update={
            "azure_search_index": "bc-pilot-public-v2",
            "azure_search_metadata_enabled": True,
            "azure_search_metadata_reviewed": True,
        }
    )
    bundle = await AzureRetriever(settings, repository, search).retrieve(
        "A statutory test question"
    )
    assert bundle.evidence[0].reference.metadata.legal_status == "in-force"
    options = search.search.call_args.kwargs
    assert "metadataVersion" in options["select"]
    assert "isHistorical eq false" in options["filter"]
    assert "effectiveTo gt" in options["filter"]
    assert "status eq 'active'" in options["filter"]
    row["effectiveTo"] = "2020-01-02"
    with pytest.raises(ApiError, match="SOURCES_UNAVAILABLE"):
        await AzureRetriever(settings, repository, search).retrieve("A statutory test question")
    legacy = {
        **evidence.evidence[0].reference.model_dump(by_alias=True),
        "id": "legacy",
        "content": evidence.evidence[0].content,
        "status": "active",
        "metadataVersion": 2,
        "rightsStatus": "review-required",
        "rightsReviewId": "",
        "rightsHash": "invalid",
    }
    search.search.return_value = Rows(legacy)
    legacy_bundle = await AzureRetriever(configured, repository, search).retrieve(
        "Legacy schema question"
    )
    assert legacy_bundle.evidence[0].reference.metadata is None
    legacy_options = search.search.call_args.kwargs
    assert "metadataVersion" not in legacy_options["select"]
    assert "rightsStatus" not in legacy_options["filter"]


@pytest.mark.parametrize(
    "values",
    [
        {"azure_search_index": "bc-pilot-public-v2"},
        {
            "azure_search_index": "bc-pilot-public-v2",
            "azure_search_metadata_enabled": True,
        },
        {
            "azure_search_index": "bc-pilot-public",
            "azure_search_metadata_enabled": True,
            "azure_search_metadata_reviewed": True,
        },
        {"azure_search_metadata_reviewed": True},
    ],
)
def test_metadata_index_configuration_must_switch_atomically(values):
    with pytest.raises(ValueError, match="must be enabled together"):
        Settings(**values)


def test_reviewed_v2_metadata_configuration_is_accepted():
    settings = Settings(
        azure_search_index="bc-pilot-public-v2",
        azure_search_metadata_enabled="true",
        azure_search_metadata_reviewed="1",
    )
    assert settings.azure_search_index == "bc-pilot-public-v2"
