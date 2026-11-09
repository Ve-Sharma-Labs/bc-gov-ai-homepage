"""Opt-in preview retrieval from exactly one existing approved Search index."""

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import httpx
from azure.core.credentials_async import AsyncTokenCredential

from bc_api.catalog import CatalogRepository
from bc_api.config import Settings
from bc_api.errors import ApiError
from bc_api.models import EvidenceBundle
from bc_api.research import require_research, research_query
from bc_api.research_contract import (
    IndexedResearchReference,
    ResearchDescriptor,
    ResearchEvidence,
)
from bc_api.research_http import provider_json
from bc_api.retrieval import (
    METADATA_FIELDS,
    SELECT_FIELDS,
    EvidenceLedger,
    add_metadata_filter,
    diversify_evidence,
    legal_day,
    validate_evidence_row,
)

API_VERSION = "2026-08-01-preview"


def knowledge_definitions(settings: Settings) -> dict:
    if not all(
        (
            settings.search_configured,
            settings.foundry_iq_knowledge_base,
            settings.foundry_iq_knowledge_source,
            settings.foundry_iq_model_deployment,
            settings.foundry_iq_model_name,
            settings.azure_openai_endpoint,
        )
    ):
        raise ValueError("Select the existing index and the approved knowledge/model bindings.")
    fields = SELECT_FIELDS + (METADATA_FIELDS if settings.azure_search_metadata_enabled else [])
    return {
        "apiVersion": API_VERSION,
        "knowledgeSource": {
            "name": settings.foundry_iq_knowledge_source,
            "kind": "searchIndex",
            "searchIndexParameters": {
                "searchIndexName": settings.azure_search_index,
                "semanticConfigurationName": settings.azure_search_semantic_config,
                "sourceDataFields": [{"name": name} for name in fields],
            },
        },
        "knowledgeBase": {
            "name": settings.foundry_iq_knowledge_base,
            "knowledgeSources": [{"name": settings.foundry_iq_knowledge_source}],
            "models": [
                {
                    "kind": "azureOpenAI",
                    "azureOpenAIParameters": {
                        "resourceUri": settings.azure_openai_endpoint,
                        "deploymentId": settings.foundry_iq_model_deployment,
                        "modelName": settings.foundry_iq_model_name,
                    },
                }
            ],
            "retrievalReasoningEffort": {"kind": "low"},
            "outputMode": "extractiveData",
        },
    }


class FoundryIQ:
    def __init__(
        self,
        settings: Settings,
        catalog: CatalogRepository,
        credential: AsyncTokenCredential,
        client: httpx.AsyncClient,
    ):
        self.settings, self.catalog = settings, catalog
        self.credential, self.client = credential, client
        self.reasoning_units: int | None = None
        self.planning_tokens: int | None = None
        self.attempts = 0

    async def retrieve(
        self,
        descriptor: ResearchDescriptor,
        geography: str,
        authorize: Callable[[], Awaitable[None]],
        mark_started: Callable[[], None],
    ) -> list[ResearchEvidence]:
        settings = self.settings
        require_research(settings, "corpus-explore")
        allowed = {
            source.id: source
            for source in self.catalog.get().sources
            if source.id in descriptor.source_ids
            and source.status in ("available", "limited")
            and (source.id != "bc-laws" or settings.azure_search_metadata_enabled)
        }
        if set(allowed) != set(descriptor.source_ids):
            raise ApiError(409, "RESEARCH_SCOPE_CHANGED", "Approved source availability changed.")
        token = (await self.credential.get_token("https://search.azure.com/.default")).token
        root = settings.azure_search_endpoint
        base_name, source_name = (
            settings.foundry_iq_knowledge_base,
            settings.foundry_iq_knowledge_source,
        )

        async def read(path: str) -> dict:
            await authorize()
            self.attempts += 1
            _, result = await provider_json(
                self.client,
                "GET",
                f"{root}/{path}?api-version={API_VERSION}",
                token=token,
            )
            return result

        base = await read(f"knowledgebases('{base_name}')")
        source = await read(f"knowledgesources('{source_name}')")
        params = source.get("searchIndexParameters", {})
        models = base.get("models", [])
        sources = base.get("knowledgeSources")
        source_reference_valid = (
            isinstance(sources, list)
            and len(sources) == 1
            and isinstance(sources[0], dict)
            and sources[0].get("name") == source_name
            and set(sources[0]) <= {"name", "enableImageServing", "enableFreshness"}
            and all(
                sources[0].get(key) is None or sources[0].get(key) is False
                for key in ("enableImageServing", "enableFreshness")
            )
        )
        fields = SELECT_FIELDS + (METADATA_FIELDS if settings.azure_search_metadata_enabled else [])
        if (
            base.get("name") != base_name
            or not source_reference_valid
            or source.get("name") != source_name
            or source.get("kind") != "searchIndex"
            or not isinstance(params, dict)
            or params.get("searchIndexName") != settings.azure_search_index
            or params.get("semanticConfigurationName") != settings.azure_search_semantic_config
            or not isinstance(params.get("sourceDataFields"), list)
            or not set(fields)
            <= {item.get("name") for item in params["sourceDataFields"] if isinstance(item, dict)}
            or not isinstance(models, list)
            or len(models) != 1
            or not isinstance(models[0], dict)
            or models[0].get("kind") != "azureOpenAI"
        ):
            raise ApiError(503, "IQ_CONTRACT_MISMATCH", "The preview knowledge contract changed.")
        model = models[0].get("azureOpenAIParameters", {})
        if (
            not isinstance(model, dict)
            or model.get("resourceUri", "").rstrip("/") != settings.azure_openai_endpoint
            or model.get("deploymentId") != settings.foundry_iq_model_deployment
            or model.get("modelName") != settings.foundry_iq_model_name
        ):
            raise ApiError(503, "IQ_CONTRACT_MISMATCH", "The approved planning model changed.")
        now = datetime.now(UTC)
        day = legal_day(now) if settings.azure_search_metadata_enabled else None
        source_filter = " or ".join(f"sourceId eq '{key}'" for key in sorted(allowed))
        filters = add_metadata_filter(f"status eq 'active' and ({source_filter})", day)
        await authorize()
        mark_started()
        self.attempts += 1
        _, payload = await provider_json(
            self.client,
            "POST",
            f"{root}/knowledgebases('{base_name}')/retrieve?api-version={API_VERSION}",
            token=token,
            body={
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": research_query(descriptor, geography)}
                        ],
                    }
                ],
                "retrievalReasoningEffort": {"kind": "low"},
                "outputMode": "extractiveData",
                "includeActivity": True,
                "maxRuntimeInSeconds": max(1, int(settings.api_upstream_timeout_seconds)),
                "maxOutputSize": 8192,
                "knowledgeSourceParams": [
                    {
                        "knowledgeSourceName": source_name,
                        "kind": "searchIndex",
                        "filterAddOn": filters,
                        "includeReferences": True,
                        "includeReferenceSourceData": True,
                    }
                ],
            },
        )
        await authorize()
        return self.parse(payload, allowed, filters, now, day)

    def parse(self, payload: dict, allowed: dict, filters: str, now: datetime, day: str | None):
        try:
            activity = payload["activity"]
            if not isinstance(activity, list) or len(activity) > 50:
                raise ValueError("Invalid activity.")
            searches = {}
            planning = 0
            for item in activity:
                if not isinstance(item, dict) or item.get("type") not in (
                    "searchIndex",
                    "agenticReasoning",
                    "modelQueryPlanning",
                ):
                    raise ValueError("Unapproved retrieval activity.")
                if item["type"] == "modelQueryPlanning":
                    planning += 1
                    if planning > 1:
                        raise ValueError("Unexpected additional planning.")
                    counts = [item.get("inputTokens"), item.get("outputTokens")]
                    if all(type(count) is int and count >= 0 for count in counts):
                        self.planning_tokens = sum(counts)
                if item["type"] == "agenticReasoning":
                    units = item.get("reasoningTokens")
                    if type(units) is int and units >= 0:
                        self.reasoning_units = (self.reasoning_units or 0) + units
                    effort = item.get("retrievalReasoningEffort", {}).get("kind", "low")
                    if effort != "low":
                        raise ValueError("Unexpected reasoning effort.")
                if item["type"] == "searchIndex":
                    if item.get(
                        "knowledgeSourceName"
                    ) != self.settings.foundry_iq_knowledge_source or item.get(
                        "searchIndexArguments", {}
                    ).get("filter") not in (filters, f"({filters})"):
                        raise ValueError("Source filters changed.")
                    searches[item["id"]] = item
            if not searches:
                raise ValueError("No verifiable source activity.")
            references = payload["references"]
            if not isinstance(references, list) or len(references) > 20:
                raise ValueError("Invalid references.")
            by_id = {}
            for reference in references:
                if (
                    not isinstance(reference, dict)
                    or reference.get("type") != "searchIndex"
                    or not isinstance(reference.get("id"), str)
                    or reference["id"] in by_id
                    or reference.get("activitySource") not in searches
                    or not isinstance(reference.get("sourceData"), dict)
                    or reference["sourceData"].get("id") != reference.get("docKey")
                ):
                    raise ValueError("Unverifiable source identity.")
                by_id[reference["id"]] = reference["sourceData"]
            used = []
            for message in payload["response"]:
                for content in message["content"]:
                    if content["type"] != "text":
                        raise ValueError("Non-extractive output.")
                    chunks = json.loads(content["text"])
                    if not isinstance(chunks, list) or len(chunks) > 20:
                        raise ValueError("Invalid extractive data.")
                    for chunk in chunks:
                        key = chunk["ref_id"]
                        if type(key) is int:
                            key = str(key)
                        if not isinstance(key, str) or key not in by_id:
                            raise ValueError("Unknown evidence.")
                        if key not in used:
                            used.append(key)
            evidence = []
            for key in used:
                item, reason = validate_evidence_row(
                    by_id[key],
                    allowed,
                    {source.id for source in self.catalog.get().sources},
                    self.settings,
                    now,
                    day,
                )
                if item is None or reason is not None:
                    raise ValueError("Evidence failed existing publication checks.")
                evidence.append(item)
            if not evidence:
                raise ApiError(
                    503,
                    "RESEARCH_SOURCE_GAP",
                    "No additional approved evidence was found. The original answer is unchanged.",
                )
            ledger = EvidenceLedger()
            for item in evidence:
                ledger.add(EvidenceBundle(evidence=[item]))
            return [
                ResearchEvidence(
                    reference=IndexedResearchReference(reference=item.reference, retrieved_at=now),
                    content=item.content,
                )
                for item in diversify_evidence(list(ledger.items.values()))
            ]
        except KeyError, TypeError, ValueError, AttributeError:
            raise ApiError(
                502,
                "IQ_EVIDENCE_INVALID",
                "The preview evidence or source scope was not verifiable.",
            ) from None
