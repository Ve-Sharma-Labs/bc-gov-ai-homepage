"""Bounded, model-free comparison of Direct Search and GA Foundry IQ retrieval."""

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import time
from pathlib import Path

import httpx
from azure.identity.aio import AzureCliCredential, ManagedIdentityCredential
from azure.search.documents.aio import SearchClient
from bc_api.catalog import CatalogRepository
from bc_api.config import Settings
from bc_api.errors import ApiError
from bc_api.foundry import configure_safe_logging
from bc_api.retrieval import SELECT_FIELDS, AzureRetriever
from dotenv import dotenv_values

VERSION = "2026-04-01"
SOURCE = "bc-eval-43db33f0-source"
BASE = "bc-eval-43db33f0"
CASES = (
    ("service-bc", "Where is the official Service BC page?"),
    ("health-coverage", "What is the difference between MSP and Fair PharmaCare?"),
    ("source-gap", "What rental assistance is available in B.C.?"),
)


class Rows:
    def __init__(self, values):
        self.values = values

    async def __aiter__(self):
        for value in self.values:
            yield value


class IQSearch:
    def __init__(self, client):
        self.client = client
        self.activity = []
        self.filter_preserved = False
        self.error = None

    async def search(self, **options):
        try:
            return await self.retrieve(**options)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            raise

    async def retrieve(self, **options):
        response = await self.client.post(
            f"/knowledgebases('{BASE}')/retrieve",
            params={"api-version": VERSION},
            json={
                "intents": [{"type": "semantic", "search": options["search_text"]}],
                "includeActivity": True,
                "maxOutputSizeInTokens": 16384,
                "maxRuntimeInSeconds": 15,
                "knowledgeSourceParams": [
                    {
                        "knowledgeSourceName": SOURCE,
                        "kind": "searchIndex",
                        "filterAddOn": options["filter"],
                        "includeReferences": True,
                        "includeReferenceSourceData": True,
                    }
                ],
            },
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"IQ retrieval returned HTTP {response.status_code}; not a complete result."
            )
        if len(response.content) > 2_000_000:
            raise RuntimeError("IQ response exceeded the comparison limit.")
        data = response.json()
        activity = data.get("activity", [])
        if any(str(item.get("type", "")).startswith("model") for item in activity):
            raise RuntimeError("The GA comparison unexpectedly invoked a retrieval model.")
        searches = [item for item in activity if item.get("type") == "searchIndex"]
        self.filter_preserved = bool(searches) and all(
            item.get("knowledgeSourceName") == SOURCE
            and item.get("searchIndexArguments", {}).get("filter") == options["filter"]
            for item in searches
        )
        self.activity = [
            {
                key: item[key]
                for key in ("type", "count", "elapsedMs", "reasoningTokens")
                if key in item
            }
            for item in activity
        ]
        used = []
        for message in data.get("response", []):
            for content in message.get("content", []):
                if content.get("type") != "text":
                    raise RuntimeError("Non-extractive IQ output.")
                chunks = json.loads(content["text"])
                if not isinstance(chunks, list):
                    raise RuntimeError("Unexpected extractive response shape.")
                for chunk in chunks:
                    if not isinstance(chunk, dict):
                        raise RuntimeError("Unidentified extractive chunk.")
                    key = chunk.get("ref_id")
                    # GA extractive ref_id values are integers; reference ids are strings.
                    if type(key) is int and key >= 0:
                        key = str(key)
                    if not isinstance(key, str) or not key:
                        raise RuntimeError("Unidentified extractive chunk.")
                    if key not in used:
                        used.append(key)
        references = data.get("references", [])
        if len(references) > 200:
            raise RuntimeError("IQ returned too many references.")
        by_id = {item["id"]: item for item in references}
        rows = []
        for key in used:
            reference = by_id[key]
            row = reference.get("sourceData")
            if (
                reference.get("type") != "searchIndex"
                or not isinstance(row, dict)
                or row.get("id") != reference.get("docKey")
            ):
                raise RuntimeError("IQ reference lacks verifiable indexed source data.")
            rows.append(row)
        return Rows(rows)


async def fingerprint(client):
    results = await client.search(
        search_text="*",
        filter="status eq 'active'",
        top=1000,
        select=["id", "documentId", "documentVersion", "contentHash", "status"],
        logging_enable=False,
    )
    rows = [dict(row) async for row in results]
    if len(rows) >= 1000:
        raise RuntimeError("Use a reviewed publication fingerprint for a larger corpus.")
    values = [
        {key: row[key] for key in ("id", "documentId", "documentVersion", "contentHash", "status")}
        for row in rows
    ]
    encoded = json.dumps(sorted(values, key=lambda row: row["id"]), sort_keys=True).encode()
    return {"activeChunks": len(rows), "sha256": hashlib.sha256(encoded).hexdigest()}


async def measure(retriever, query):
    start = time.monotonic()
    try:
        evidence = await retriever.retrieve(query)
        keys = sorted(item.reference.chunk_id for item in evidence.evidence)
        outcome = "evidence"
    except ApiError as exc:
        if exc.code != "SOURCES_UNAVAILABLE":
            if isinstance(retriever.client, IQSearch) and retriever.client.error:
                raise RuntimeError(retriever.client.error) from None
            raise
        keys, outcome = [], "source-gap"
    return {
        "outcome": outcome,
        "chunkIds": keys,
        "elapsedMs": round((time.monotonic() - start) * 1000, 1),
    }


async def compare(args):
    env = (
        os.environ
        if args.credential == "managed-identity"
        else dotenv_values(Path(".azure") / "bc-pilot" / ".env")
    )
    settings = Settings(
        azure_search_endpoint=env["AZURE_SEARCH_ENDPOINT"],
        azure_search_index=env["AZURE_SEARCH_INDEX"],
        azure_search_semantic_config="bc-public-guidance",
        api_upstream_timeout_seconds=30,
    )
    source = {
        "name": SOURCE,
        "kind": "searchIndex",
        "description": "Evaluation only; existing approved BC index; no production agent binding.",
        "searchIndexParameters": {
            "searchIndexName": settings.azure_search_index,
            "semanticConfigurationName": settings.azure_search_semantic_config,
            "sourceDataFields": [{"name": name} for name in SELECT_FIELDS],
        },
    }
    base = {
        "name": BASE,
        "description": "Evaluation-only GA extractive retrieval. No query-planning or answering model.",
        "knowledgeSources": [{"name": SOURCE}],
    }
    report = {
        "apiVersion": VERSION,
        "productionPathChanged": False,
        "answerModelInvocations": 0,
        "answerModel": json.loads(env["FOUNDRY_GENERAL_AGENT"])["modelDeployment"],
        "scope": "Retrieval-only comparison; no claim of matched generated-answer quality.",
        "results": [],
        "definitionsAttempted": [],
    }
    created = []
    identity = (
        ManagedIdentityCredential(client_id=env.get("AZURE_CLIENT_ID"))
        if args.credential == "managed-identity"
        else AzureCliCredential(process_timeout=15)
    )
    async with identity as credential:
        token = await credential.get_token("https://search.azure.com/.default")
        async with (
            httpx.AsyncClient(
                base_url=settings.azure_search_endpoint,
                headers={"Authorization": "Bearer " + token.token},
                timeout=30,
            ) as client,
            SearchClient(
                settings.azure_search_endpoint,
                settings.azure_search_index,
                credential,
                logging_enable=False,
            ) as search,
        ):
            try:
                definitions = (
                    ()
                    if args.query_only
                    else (
                        ("knowledgesources", source),
                        ("knowledgebases", base),
                    )
                )
                for collection, definition in definitions:
                    route = f"/{collection}/{definition['name']}"
                    existing = await client.get(route, params={"api-version": VERSION})
                    if existing.status_code != 404:
                        raise RuntimeError(
                            f"Evaluation definition already exists or cannot be inspected: {collection}."
                        )
                    if not args.setup:
                        raise RuntimeError(
                            "Explicit --setup is required to create evaluation-only definitions."
                        )
                    report["definitionsAttempted"].append(route)
                    result = await client.put(
                        route,
                        params={"api-version": VERSION},
                        json=definition,
                        headers={"If-None-Match": "*"},
                    )
                    if result.status_code not in (200, 201):
                        raise RuntimeError(
                            f"Definition creation returned HTTP {result.status_code}: {collection}."
                        )
                    etag = result.headers.get("etag") or result.json().get("@odata.etag")
                    if not etag:
                        raise RuntimeError("Definition creation returned no concurrency token.")
                    created.append((route, etag))
                report["corpusBefore"] = await fingerprint(search)
                catalog = CatalogRepository(settings.catalog_path)
                direct = AzureRetriever(settings, catalog, search)
                adapter = IQSearch(client)
                candidate = AzureRetriever(settings, catalog, adapter)
                for repetition in range(args.repetitions):
                    for case_id, query in CASES:
                        first = await measure(direct, query)
                        second = await measure(candidate, query)
                        report["results"].append(
                            {
                                "caseId": case_id,
                                "repetition": repetition,
                                "direct": first,
                                "iq": second,
                                "sameEvidence": first["chunkIds"] == second["chunkIds"],
                                "filterPreserved": adapter.filter_preserved,
                                "iqActivity": adapter.activity,
                            }
                        )
                report["corpusAfter"] = await fingerprint(search)
                if report["corpusAfter"] != report["corpusBefore"]:
                    raise RuntimeError("The corpus changed during comparison.")
                report["summary"] = {
                    "pairs": len(report["results"]),
                    "directMedianMs": statistics.median(
                        row["direct"]["elapsedMs"] for row in report["results"]
                    ),
                    "iqMedianMs": statistics.median(
                        row["iq"]["elapsedMs"] for row in report["results"]
                    ),
                    "allFiltersPreserved": all(row["filterPreserved"] for row in report["results"]),
                    "allEvidenceMatched": all(row["sameEvidence"] for row in report["results"]),
                }
                report["decision"] = (
                    "Retain Direct Search; any future adoption also needs reviewed answer-quality evaluation."
                )
            finally:
                report["definitionsCreated"] = [route for route, _ in created]
                report["cleanupCompleted"] = not report["definitionsAttempted"]
                if args.cleanup:
                    for route, etag in reversed(created):
                        response = await client.delete(
                            route,
                            params={"api-version": VERSION},
                            headers={"If-Match": etag},
                        )
                        if response.status_code not in (200, 204):
                            raise RuntimeError(
                                f"Evaluation definition cleanup was not confirmed: HTTP {response.status_code}."
                            )
                    report["cleanupCompleted"] = len(created) == len(report["definitionsAttempted"])
                args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--query-only", action="store_true")
    parser.add_argument(
        "--credential", choices=("azure-cli", "managed-identity"), default="azure-cli"
    )
    parser.add_argument("--repetitions", type=int, choices=range(1, 4), default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.query_only and (args.setup or args.cleanup):
        parser.error("Query-only evaluation cannot create or remove definitions.")
    if not args.execute:
        print(
            json.dumps(
                {
                    "mode": "review-only",
                    "pairedRetrievals": len(CASES) * args.repetitions,
                    "modelInvocations": 0,
                    "definitions": [SOURCE, BASE],
                    "networkRequests": 0,
                }
            )
        )
        return
    configure_safe_logging()
    print(json.dumps(asyncio.run(compare(args)), indent=2))


if __name__ == "__main__":
    main()
