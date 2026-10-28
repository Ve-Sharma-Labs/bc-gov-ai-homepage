"""Read-only, matched-query validation of the v1 and metadata-aware v2 indexes."""

import argparse
import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from azure.identity.aio import AzureCliCredential, ManagedIdentityCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexClient
from azure.search.documents.models import QueryType
from bc_api.catalog import CatalogRepository
from bc_api.config import default_catalog_path
from bc_api.foundry import configure_safe_logging
from bc_api.retrieval import (
    METADATA_FIELDS,
    SELECT_FIELDS,
    evidence_metadata,
    legal_day,
)

V1_INDEX = "bc-pilot-public"
V2_INDEX = "bc-pilot-public-v2"
SEMANTIC_CONFIGURATION = "bc-public-guidance"
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
REQUIRED_TYPES = {
    "id": "Edm.String",
    "documentId": "Edm.String",
    "sourceId": "Edm.String",
    "title": "Edm.String",
    "publisher": "Edm.String",
    "url": "Edm.String",
    "content": "Edm.String",
    "section": "Edm.String",
    "checkedAt": "Edm.DateTimeOffset",
    "publisherUpdatedAt": "Edm.DateTimeOffset",
    "status": "Edm.String",
    "documentVersion": "Edm.String",
    "journeyIds": "Collection(Edm.String)",
    "metadataVersion": "Edm.Int32",
    "sourceIds": "Collection(Edm.String)",
    "documentType": "Edm.String",
    "language": "Edm.String",
    "contentHash": "Edm.String",
    "extractionHash": "Edm.String",
    "reviewHash": "Edm.String",
    "rightsStatus": "Edm.String",
    "rightsReviewId": "Edm.String",
    "rightsHash": "Edm.String",
    "legalStatus": "Edm.String",
    "effectiveFrom": "Edm.String",
    "effectiveTo": "Edm.String",
    "consolidationDate": "Edm.String",
    "repealedAt": "Edm.String",
    "legalSectionId": "Edm.String",
    "isHistorical": "Edm.Boolean",
}
COMMON_FILTER_FIELDS = {"sourceId", "status", "journeyIds"}
METADATA_FILTER_FIELDS = {
    "metadataVersion",
    "sourceIds",
    "documentType",
    "reviewHash",
    "rightsStatus",
    "rightsReviewId",
    "rightsHash",
    "legalStatus",
    "effectiveFrom",
    "effectiveTo",
    "repealedAt",
    "isHistorical",
}


@dataclass(frozen=True)
class ComparisonCase:
    case_id: str
    query: str
    source_ids: tuple[str, ...]
    journey_id: str | None = None

    @property
    def filter(self) -> str:
        source_filter = " or ".join(
            f"sourceId eq '{source_id}'" for source_id in sorted(self.source_ids)
        )
        value = f"status eq 'active' and ({source_filter})"
        if self.journey_id:
            value += f" and journeyIds/any(j: j eq '{self.journey_id}')"
        return value


DEFAULT_CASES = (
    ComparisonCase(
        "bc-content", "What B.C. government services are available?", ("bc-content",)
    ),
    ComparisonCase("service-bc", "Where is a Service BC location?", ("service-bc",)),
    ComparisonCase(
        "housing-tenancy",
        "What rights does a tenant have with a landlord?",
        ("housing-tenancy",),
    ),
    ComparisonCase("health", "How do I enrol in MSP?", ("health",)),
    ComparisonCase(
        "family-social-supports",
        "How do I apply for disability assistance?",
        ("family-social-supports",),
    ),
    ComparisonCase(
        "employment-business",
        "What are B.C. employment standards for wages?",
        ("employment-business",),
    ),
    ComparisonCase("taxes", "What provincial tax credits are available?", ("taxes",)),
    ComparisonCase("bc-housing", "What is the SAFER programme?", ("bc-housing",)),
    ComparisonCase("icbc", "What ICBC vehicle guidance is available?", ("icbc",)),
    ComparisonCase("workbc", "What WorkBC training is available?", ("workbc",)),
    ComparisonCase(
        "healthlink-bc",
        "How do I use the Health Connect Registry?",
        ("healthlink-bc",),
    ),
    ComparisonCase("bc-laws", "Where can I read B.C. statutes?", ("bc-laws",)),
    ComparisonCase(
        "overlap-rental",
        "Compare rental assistance with tenant rights.",
        ("bc-housing", "housing-tenancy"),
    ),
)


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _field_type(field: Any) -> str:
    value = _value(field, "type")
    return str(getattr(value, "value", value))


def _semantic_names(index: Any) -> set[str]:
    semantic = _value(index, "semantic_search")
    if semantic is None:
        semantic = _value(index, "semanticSearch")
    configurations = (
        _value(semantic, "configurations", []) if semantic is not None else []
    )
    return {
        name
        for configuration in configurations
        if (name := _value(configuration, "name")) is not None
    }


def schema_issues(index: Any, expected_name: str, *, metadata: bool) -> list[str]:
    issues = []
    if _value(index, "name") != expected_name:
        issues.append(f"Expected index {expected_name}.")
    fields = {_value(field, "name"): field for field in _value(index, "fields", [])}
    required = SELECT_FIELDS + METADATA_FIELDS if metadata else SELECT_FIELDS
    for name in required:
        field = fields.get(name)
        if field is None:
            issues.append(f"Missing selected field: {name}.")
            continue
        expected_type = REQUIRED_TYPES[name]
        if _field_type(field) != expected_type:
            issues.append(
                f"Selected field {name} has type {_field_type(field)}, expected {expected_type}."
            )
        if _value(field, "retrievable", True) is False:
            issues.append(f"Selected field {name} is not retrievable.")
    filter_fields = COMMON_FILTER_FIELDS | (
        METADATA_FILTER_FIELDS if metadata else set()
    )
    for name in sorted(filter_fields):
        if name in fields and _value(fields[name], "filterable", False) is not True:
            issues.append(f"Required filter field {name} is not filterable.")
    if SEMANTIC_CONFIGURATION not in _semantic_names(index):
        issues.append(f"Missing semantic configuration: {SEMANTIC_CONFIGURATION}.")
    return issues


def load_cases(path: Path | None) -> tuple[ComparisonCase, ...]:
    if path is None:
        return DEFAULT_CASES
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("The case file must contain a nonempty JSON array.")
    cases = []
    for item in raw:
        if not isinstance(item, dict) or set(item) - {
            "id",
            "query",
            "sourceIds",
            "journeyId",
        }:
            raise ValueError("Every comparison case must use the documented fields.")
        case_id = item.get("id")
        query = item.get("query")
        source_ids = item.get("sourceIds")
        journey_id = item.get("journeyId")
        if (
            not isinstance(case_id, str)
            or not IDENTIFIER.fullmatch(case_id)
            or not isinstance(query, str)
            or not query.strip()
            or len(query) > 512
            or not isinstance(source_ids, list)
            or not source_ids
            or len(source_ids) != len(set(source_ids))
            or any(
                not isinstance(value, str) or not IDENTIFIER.fullmatch(value)
                for value in source_ids
            )
            or (
                journey_id is not None
                and (
                    not isinstance(journey_id, str)
                    or not IDENTIFIER.fullmatch(journey_id)
                )
            )
        ):
            raise ValueError(
                "Comparison cases need bounded queries and valid unique identifiers."
            )
        cases.append(ComparisonCase(case_id, query, tuple(source_ids), journey_id))
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Comparison case identifiers must be unique.")
    return tuple(cases)


async def _search(
    client: SearchClient, case: ComparisonCase, select: list[str]
) -> tuple:
    options = {
        "search_text": case.query,
        "filter": case.filter,
        "top": 10,
        "select": select,
        "query_type": QueryType.SEMANTIC,
        "semantic_configuration_name": SEMANTIC_CONFIGURATION,
        "logging_enable": False,
    }
    results = await client.search(**options)
    return [dict(row) async for row in results], options


def _keys(rows: list[dict]) -> list[str]:
    return [
        str(row.get("id") or f"{row.get('documentId')}:{row.get('documentVersion')}")
        for row in rows
    ]


async def compare_cases(
    v1: SearchClient,
    v2: SearchClient,
    cases: tuple[ComparisonCase, ...],
    catalogue_source_ids: set[str],
) -> list[dict]:
    day = legal_day(datetime.now(UTC))
    results = []
    for case in cases:
        v1_rows, v1_options = await _search(v1, case, SELECT_FIELDS)
        v2_rows, v2_options = await _search(v2, case, SELECT_FIELDS + METADATA_FIELDS)
        metadata_errors = []
        for row in v2_rows:
            try:
                evidence_metadata(row, catalogue_source_ids, day)
            except (KeyError, TypeError, ValueError) as exc:
                metadata_errors.append({"id": row.get("id"), "error": str(exc)})
        results.append(
            {
                "caseId": case.case_id,
                "query": case.query,
                "filter": case.filter,
                "sameQueryAndFilter": (
                    v1_options["search_text"] == v2_options["search_text"]
                    and v1_options["filter"] == v2_options["filter"]
                ),
                "v1ChunkIds": _keys(v1_rows),
                "v2ChunkIds": _keys(v2_rows),
                "sameRankedChunks": _keys(v1_rows) == _keys(v2_rows),
                "v2MetadataErrors": metadata_errors,
            }
        )
    return results


async def run(args: argparse.Namespace, cases: tuple[ComparisonCase, ...]) -> dict:
    endpoint = args.endpoint.rstrip("/")
    identity = (
        ManagedIdentityCredential(client_id=args.client_id)
        if args.credential == "managed-identity"
        else AzureCliCredential(process_timeout=15)
    )
    async with (
        identity as credential,
        SearchIndexClient(endpoint, credential, logging_enable=False) as indexes,
        SearchClient(endpoint, args.v1_index, credential, logging_enable=False) as v1,
        SearchClient(endpoint, args.v2_index, credential, logging_enable=False) as v2,
    ):
        v1_schema = await indexes.get_index(args.v1_index)
        v2_schema = await indexes.get_index(args.v2_index)
        v1_issues = schema_issues(v1_schema, args.v1_index, metadata=False)
        v2_issues = schema_issues(v2_schema, args.v2_index, metadata=True)
        results = []
        if not v1_issues and not v2_issues:
            catalog = CatalogRepository(args.catalog).get()
            results = await compare_cases(
                v1,
                v2,
                cases,
                {source.id for source in catalog.sources},
            )
    all_metadata_valid = bool(results) and all(
        not result["v2MetadataErrors"] for result in results
    )
    all_v2_populated = bool(results) and all(result["v2ChunkIds"] for result in results)
    all_requests_matched = bool(results) and all(
        result["sameQueryAndFilter"] for result in results
    )
    all_chunks_matched = bool(results) and all(
        result["sameRankedChunks"] for result in results
    )
    ready = (
        not v1_issues
        and not v2_issues
        and all_metadata_valid
        and all_v2_populated
        and all_requests_matched
        and (all_chunks_matched or not args.require_match)
    )
    return {
        "readOnly": True,
        "operations": ["get_index", "search"],
        "mutationOperations": [],
        "v1Index": args.v1_index,
        "v2Index": args.v2_index,
        "semanticConfiguration": SEMANTIC_CONFIGURATION,
        "schema": {"v1Issues": v1_issues, "v2Issues": v2_issues},
        "results": results,
        "summary": {
            "cases": len(cases),
            "allRequestsMatched": all_requests_matched,
            "allV2MetadataValid": all_metadata_valid,
            "allV2CasesPopulated": all_v2_populated,
            "allRankedChunksMatched": all_chunks_matched,
            "requireMatch": args.require_match,
            "readyForCutoverReview": ready,
        },
    }


def emit(report: dict, output: Path | None) -> None:
    value = json.dumps(report, indent=2)
    if output is not None:
        output.write_text(value + "\n", encoding="utf-8")
    print(value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--endpoint", default=os.environ.get("AZURE_SEARCH_ENDPOINT", "")
    )
    parser.add_argument("--v1-index", default=V1_INDEX)
    parser.add_argument("--v2-index", default=V2_INDEX)
    parser.add_argument("--catalog", type=Path, default=default_catalog_path())
    parser.add_argument("--case-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-match", action="store_true")
    parser.add_argument(
        "--credential",
        choices=("azure-cli", "managed-identity"),
        default="azure-cli",
    )
    parser.add_argument("--client-id", default=os.environ.get("AZURE_CLIENT_ID"))
    args = parser.parse_args()
    cases = load_cases(args.case_file)
    if not args.execute:
        emit(
            {
                "mode": "review-only",
                "readOnly": True,
                "networkRequests": 0,
                "mutationOperations": [],
                "v1Index": args.v1_index,
                "v2Index": args.v2_index,
                "cases": len(cases),
            },
            args.output,
        )
        return
    if not args.endpoint:
        parser.error("--endpoint or AZURE_SEARCH_ENDPOINT is required with --execute.")
    configure_safe_logging()
    report = asyncio.run(run(args, cases))
    emit(report, args.output)
    if not report["summary"]["readyForCutoverReview"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
