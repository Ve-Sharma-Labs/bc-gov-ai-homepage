"""Optional official Azure SDK adapter. Importing this module never authenticates."""

import hashlib
import json
import os
import re
from copy import deepcopy

from .metadata import MAX_CHUNK_CHARS
from .policy import AcquisitionError
from .vectors import azure_embedder, enrich_documents, validate_dimensions


LIVE_INDEX_NAME = "bc-pilot-public"
SHADOW_INDEX_NAME = "bc-pilot-public-v2"
SEMANTIC_CONFIGURATION_NAME = "bc-public-guidance"


def build_index(name: str, vector_dimensions: int | None = None):
    from azure.search.documents.indexes.models import (
        SearchField, SearchFieldDataType, SearchIndex, SearchableField, SimpleField,
        SemanticConfiguration, SemanticField, SemanticPrioritizedFields, SemanticSearch,
        HnswAlgorithmConfiguration, VectorSearch, VectorSearchProfile,
    )
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SimpleField(name="documentId", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="sourceId", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="title", type=SearchFieldDataType.String),
        SimpleField(name="publisher", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="url", type=SearchFieldDataType.String),
        SearchableField(name="content", type=SearchFieldDataType.String, analyzer_name="en.microsoft"),
        SearchableField(name="section", type=SearchFieldDataType.String),
        SimpleField(name="checkedAt", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
        SimpleField(name="publisherUpdatedAt", type=SearchFieldDataType.DateTimeOffset, filterable=True),
        SimpleField(name="status", type=SearchFieldDataType.String, filterable=True),
        SearchField(name="topics", type=SearchFieldDataType.Collection(SearchFieldDataType.String),
                    searchable=True, filterable=True, facetable=True),
        SearchField(name="journeyIds", type=SearchFieldDataType.Collection(SearchFieldDataType.String),
                    searchable=True, filterable=True, facetable=True),
        SimpleField(name="documentVersion", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="contentHash", type=SearchFieldDataType.String),
    ]
    for field_name in (
        "canonicalUrl", "sourceUrl", "language", "documentType", "mediaType", "extractionMethod",
        "extractionHash", "responseHash", "rightsStatus", "rightsReviewId", "rightsHash", "licenceUrl",
        "legalStatus", "legalSectionId", "reviewHash",
    ):
        fields.append(SimpleField(name=field_name, type=SearchFieldDataType.String, filterable=True))
    # These are publisher calendar dates, not guessed midnight-UTC effective instants.
    for field_name in ("effectiveFrom", "effectiveTo", "consolidationDate", "repealedAt"):
        fields.append(SimpleField(name=field_name, type=SearchFieldDataType.String, filterable=True, sortable=True))
    for field_name in ("sourceIds", "aliasUrls", "amendmentIds", "sectionLocators"):
        fields.append(SearchField(name=field_name, type=SearchFieldDataType.Collection(SearchFieldDataType.String),
                                  searchable=True, filterable=True, facetable=True))
    for field_name in ("metadataVersion", "chunkPart", "chunkParts"):
        fields.append(SimpleField(name=field_name, type=SearchFieldDataType.Int32, filterable=True))
    for field_name in ("isHistorical", "containsExceptions"):
        fields.append(SimpleField(name=field_name, type=SearchFieldDataType.Boolean, filterable=True))
    fields.append(SimpleField(name="fetchedAt", type=SearchFieldDataType.DateTimeOffset, filterable=True))
    vector_search = None
    if vector_dimensions is not None:
        validate_dimensions(vector_dimensions)
        fields.append(SearchField(
            name="contentVector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True, hidden=True,
            vector_search_dimensions=vector_dimensions,
            vector_search_profile_name="bc-vector-profile",
        ))
        vector_search = VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="bc-hnsw")],
            profiles=[VectorSearchProfile(name="bc-vector-profile",
                                          algorithm_configuration_name="bc-hnsw")],
        )
    return SearchIndex(
        name=name, fields=fields,
        vector_search=vector_search,
        semantic_search=SemanticSearch(configurations=[
            SemanticConfiguration(
                name=SEMANTIC_CONFIGURATION_NAME,
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="title"),
                    content_fields=[SemanticField(field_name="content")],
                    keywords_fields=[SemanticField(field_name="section")],
                ),
                ranking_order="BoostedRerankerScore",
            ),
        ]),
    )


def _schema_value(value):
    return getattr(value, "value", value)


def _field_inventory(field) -> dict:
    return {
        "name": field.name,
        "type": str(field.type),
        "key": bool(field.key),
        "retrievable": not bool(field.hidden),
        "searchable": bool(field.searchable),
        "filterable": bool(field.filterable),
        "sortable": bool(field.sortable),
        "facetable": bool(field.facetable),
        "analyzer": _schema_value(field.analyzer_name),
        "searchAnalyzer": _schema_value(field.search_analyzer_name),
        "indexAnalyzer": _schema_value(field.index_analyzer_name),
        "normalizer": _schema_value(field.normalizer_name),
        "synonymMaps": sorted(field.synonym_map_names or []),
        "dimensions": field.vector_search_dimensions,
        "vectorSearchProfile": field.vector_search_profile_name,
    }


def _semantic_inventory(index) -> dict | None:
    semantic = index.semantic_search
    if semantic is None:
        return None
    configurations = []
    for configuration in semantic.configurations or []:
        prioritized = configuration.prioritized_fields
        configurations.append({
            "name": configuration.name,
            "titleField": (
                prioritized.title_field.field_name
                if prioritized is not None and prioritized.title_field is not None
                else None
            ),
            "contentFields": sorted(
                field.field_name for field in (prioritized.content_fields or [])
            ) if prioritized is not None else [],
            "keywordFields": sorted(
                field.field_name for field in (prioritized.keywords_fields or [])
            ) if prioritized is not None else [],
            "rankingOrder": _schema_value(configuration.ranking_order),
        })
    return {
        "defaultConfiguration": semantic.default_configuration_name,
        "configurations": sorted(configurations, key=lambda value: value["name"]),
    }


def _vector_inventory(index):
    if index.vector_search is None:
        return None
    return index.vector_search.serialize()


def index_inventory(index) -> dict:
    schema = {
        "fields": sorted(
            (_field_inventory(field) for field in index.fields),
            key=lambda value: value["name"],
        ),
        "semantic": _semantic_inventory(index),
        "vectorSearch": _vector_inventory(index),
    }
    encoded = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
    return {
        "name": index.name,
        "etag": index.e_tag,
        "fieldCount": len(index.fields),
        "schemaSha256": hashlib.sha256(encoded).hexdigest(),
        **schema,
    }


def schema_diff(existing, desired) -> dict:
    expected = index_inventory(desired)
    if existing is None:
        return {
            "compatible": False,
            "status": "missing",
            "nameMatches": False,
            "missingFields": sorted(field["name"] for field in expected["fields"]),
            "unexpectedFields": [],
            "changedFields": {},
            "semantic": {"matches": False, "expected": expected["semantic"], "actual": None},
            "vectorSearch": {
                "matches": False,
                "expected": expected["vectorSearch"],
                "actual": None,
            },
        }
    actual = index_inventory(existing)
    expected_fields = {field["name"]: field for field in expected["fields"]}
    actual_fields = {field["name"]: field for field in actual["fields"]}
    changed = {
        name: {"expected": expected_fields[name], "actual": actual_fields[name]}
        for name in sorted(expected_fields.keys() & actual_fields.keys())
        if expected_fields[name] != actual_fields[name]
    }
    missing = sorted(expected_fields.keys() - actual_fields.keys())
    unexpected = sorted(actual_fields.keys() - expected_fields.keys())
    semantic_matches = actual["semantic"] == expected["semantic"]
    vector_matches = actual["vectorSearch"] == expected["vectorSearch"]
    name_matches = actual["name"] == expected["name"]
    compatible = not missing and not unexpected and not changed and semantic_matches \
        and vector_matches and name_matches
    return {
        "compatible": compatible,
        "status": "compatible" if compatible else "incompatible",
        "nameMatches": name_matches,
        "missingFields": missing,
        "unexpectedFields": unexpected,
        "changedFields": changed,
        "semantic": {
            "matches": semantic_matches,
            "expected": expected["semantic"],
            "actual": actual["semantic"],
        },
        "vectorSearch": {
            "matches": vector_matches,
            "expected": expected["vectorSearch"],
            "actual": actual["vectorSearch"],
        },
    }


def _get_index(indexes, name: str):
    from azure.core.exceptions import ResourceNotFoundError
    try:
        return indexes.get_index(name)
    except ResourceNotFoundError:
        return None


def _require_compatible_shadow(existing, desired) -> dict:
    diff = schema_diff(existing, desired)
    if not diff["compatible"]:
        details = []
        if diff["missingFields"]:
            details.append("missing=" + ",".join(diff["missingFields"]))
        if diff["unexpectedFields"]:
            details.append("unexpected=" + ",".join(diff["unexpectedFields"]))
        if diff["changedFields"]:
            details.append("changed=" + ",".join(diff["changedFields"]))
        if not diff["semantic"]["matches"]:
            details.append("semantic")
        if not diff["vectorSearch"]["matches"]:
            details.append("vectorSearch")
        raise AcquisitionError(
            "Existing shadow index schema is incompatible; refusing any update"
            + (": " + "; ".join(details) if details else "")
        )
    return diff


def _preserved_live_index(before, after) -> bool:
    if before is None or after is None or not before.e_tag or not after.e_tag:
        return False
    first = index_inventory(before)
    second = index_inventory(after)
    return (
        first["name"] == second["name"]
        and first["etag"] == second["etag"]
        and first["schemaSha256"] == second["schemaSha256"]
    )


def ensure_shadow_index(indexes, desired, live_index_name: str = LIVE_INDEX_NAME):
    """Create a missing exact shadow index; never update, replace, or delete an index."""
    from azure.core.exceptions import ResourceExistsError

    if desired.name == live_index_name:
        raise AcquisitionError("The shadow index name must not equal the live index name")
    if desired.vector_search is not None or any(
        field.vector_search_dimensions is not None for field in desired.fields
    ):
        raise AcquisitionError("The initial shadow index must keep vector search disabled")
    live_before = _get_index(indexes, live_index_name)
    if live_before is None:
        raise AcquisitionError("The live index must be readable before creating its shadow")
    if not live_before.e_tag:
        raise AcquisitionError("Live-index preservation requires its Azure Search ETag")
    existing = _get_index(indexes, desired.name)
    created = False
    if existing is None:
        try:
            indexes.create_index(desired)
            created = True
        except ResourceExistsError:
            # A concurrent creator won the create-only race. Read and validate it;
            # never convert the race into an upsert.
            pass
        existing = _get_index(indexes, desired.name)
        if existing is None:
            raise AcquisitionError("Azure did not return the shadow index after create")
    diff = _require_compatible_shadow(existing, desired)
    live_after = _get_index(indexes, live_index_name)
    if not _preserved_live_index(live_before, live_after):
        raise AcquisitionError(
            "The live index ETag or schema changed during the shadow operation; "
            "no live-index write was attempted"
        )
    return existing, created, live_before, live_after, diff


def _read_shadow_index(indexes, desired, live_index_name: str):
    if desired.name == live_index_name:
        raise AcquisitionError("The shadow index name must not equal the live index name")
    live_before = _get_index(indexes, live_index_name)
    if live_before is None or not live_before.e_tag:
        raise AcquisitionError("The live index and its ETag must be readable")
    shadow = _get_index(indexes, desired.name)
    live_after = _get_index(indexes, live_index_name)
    if not _preserved_live_index(live_before, live_after):
        raise AcquisitionError("The live index changed while the shadow inventory was read")
    return shadow, live_before, live_after, schema_diff(shadow, desired)


def _index_statistics(indexes, name: str) -> dict:
    values = indexes.get_index_statistics(name)
    return {
        "documentCount": int(values["document_count"]),
        "storageSize": int(values["storage_size"]),
        "vectorIndexSize": int(values.get("vector_index_size", 0)),
    }


def shadow_index_operation(
    endpoint: str,
    *,
    operation: str,
    shadow_index_name: str = SHADOW_INDEX_NAME,
    live_index_name: str = LIVE_INDEX_NAME,
    execute: bool = False,
    credential_mode: str = "managed-identity",
) -> dict:
    """Get, validate, or create the empty metadata-aware shadow index."""
    from azure.core.exceptions import AzureError
    from azure.identity import AzureCliCredential, ManagedIdentityCredential
    from azure.search.documents.indexes import SearchIndexClient

    if operation not in ("get", "validate", "create"):
        raise AcquisitionError("Choose shadow-index operation get, validate, or create")
    if operation == "create" and not execute:
        raise AcquisitionError("Shadow index creation requires --execute")
    if operation != "create" and execute:
        raise AcquisitionError("--execute is only valid for shadow-index create")
    if credential_mode not in ("managed-identity", "azure-cli"):
        raise AcquisitionError("Choose an explicit shadow-index credential mode")
    endpoint = _endpoint(endpoint, "search")
    for label, name in (("shadow", shadow_index_name), ("live", live_index_name)):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,126}[a-z0-9]", name):
            raise AcquisitionError(f"A valid {label} Search index name is required")
    desired = build_index(shadow_index_name)
    identity = os.environ.get("AZURE_CLIENT_ID")
    options = {"client_id": identity} if identity else {}
    selected = (
        ManagedIdentityCredential(**options)
        if credential_mode == "managed-identity"
        else AzureCliCredential(process_timeout=10)
    )
    try:
        with selected as credential:
            with SearchIndexClient(endpoint, credential) as indexes:
                if operation == "create":
                    shadow, created, live_before, _, diff = ensure_shadow_index(
                        indexes, desired, live_index_name
                    )
                else:
                    shadow, live_before, _, diff = _read_shadow_index(
                        indexes, desired, live_index_name
                    )
                    created = False
                live = {
                    "exists": True,
                    **index_inventory(live_before),
                    **_index_statistics(indexes, live_index_name),
                }
                shadow_inventory = (
                    {
                        "exists": True,
                        **index_inventory(shadow),
                        **_index_statistics(indexes, shadow_index_name),
                    }
                    if shadow is not None
                    else {"exists": False, "name": shadow_index_name}
                )
    except AzureError:
        permission = (
            "Search Service Contributor on the Azure AI Search service "
            "(indexes/read, indexes/write, and index statistics)"
            if operation == "create"
            else "Search Service Contributor on the Azure AI Search service "
            "(indexes/read and index statistics)"
        )
        raise AcquisitionError(
            f"Azure Search {operation} requires {permission} for the selected identity"
        ) from None
    valid = shadow is not None and diff["compatible"]
    empty = bool(shadow is not None and shadow_inventory["documentCount"] == 0)
    if operation == "create" and not empty:
        raise AcquisitionError(
            "The shadow index schema is valid but it is not empty; content was not modified"
        )
    return {
        "operation": operation,
        "service": endpoint.removeprefix("https://").removesuffix(".search.windows.net"),
        "liveIndex": live,
        "shadowIndex": shadow_inventory,
        "schemaDiff": diff,
        "created": created,
        "valid": valid,
        "empty": empty,
        "vectorsEnabled": False,
        "semanticConfiguration": SEMANTIC_CONFIGURATION_NAME,
        "livePreserved": True,
        "destructiveMigration": False,
        "contentPublished": False,
    }


def merge_index_schema(existing, desired):
    """Add fields/configurations on a copy; reject incompatible in-place migrations."""
    if existing.name != desired.name:
        raise AcquisitionError("Index migration cannot rename an existing index")
    result = deepcopy(existing)
    fields = {field.name: field for field in result.fields}
    for proposed in desired.fields:
        live = fields.get(proposed.name)
        if live is None:
            result.fields.append(deepcopy(proposed))
            continue
        for attribute in (
            "type", "analyzer_name", "search_analyzer_name", "index_analyzer_name",
            "vector_search_dimensions", "vector_search_profile_name",
        ):
            wanted = getattr(proposed, attribute, None)
            if wanted is not None and getattr(live, attribute, None) != wanted:
                raise AcquisitionError(f"Incompatible Search field {proposed.name}.{attribute}; use a separately reviewed new index")
        for attribute in ("key", "searchable", "filterable", "sortable", "facetable"):
            if getattr(proposed, attribute, False) and not getattr(live, attribute, False):
                raise AcquisitionError(f"Incompatible Search field {proposed.name}.{attribute}; no destructive migration is allowed")
    if desired.semantic_search is not None:
        if result.semantic_search is None:
            result.semantic_search = deepcopy(desired.semantic_search)
        else:
            configurations = result.semantic_search.configurations or []
            names = {config.name for config in configurations}
            configurations.extend(deepcopy(config) for config in desired.semantic_search.configurations if config.name not in names)
            result.semantic_search.configurations = configurations
    if desired.vector_search is not None:
        if result.vector_search is None:
            result.vector_search = deepcopy(desired.vector_search)
        else:
            for attribute in ("algorithms", "profiles"):
                live_values = getattr(result.vector_search, attribute) or []
                named = {item.name: item for item in live_values}
                for item in getattr(desired.vector_search, attribute) or []:
                    if item.name not in named:
                        live_values.append(deepcopy(item))
                    elif attribute == "profiles" and named[item.name].algorithm_configuration_name != item.algorithm_configuration_name:
                        raise AcquisitionError("Existing vector profile is incompatible; no in-place replacement")
                    elif attribute == "algorithms" and named[item.name].kind != item.kind:
                        raise AcquisitionError("Existing vector algorithm is incompatible; no in-place replacement")
                setattr(result.vector_search, attribute, live_values)
    return result


def migrate_index(indexes, desired):
    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceNotFoundError
    try:
        existing = indexes.get_index(desired.name)
    except ResourceNotFoundError:
        # create_index cannot overwrite an index that appeared after the 404.
        return indexes.create_index(desired)
    merged = merge_index_schema(existing, desired)
    if not existing.e_tag:
        raise AcquisitionError("Search schema migration requires the live ETag")
    return indexes.create_or_update_index(
        merged, match_condition=MatchConditions.IfNotModified, allow_index_downtime=False,
    )


def _endpoint(value: str | None, service: str) -> str:
    suffixes = {
        "search": r"search\.windows\.net",
        "blob": r"blob\.core\.windows\.net",
        "embedding": r"(?:openai\.azure\.com|services\.ai\.azure\.com)",
    }
    if service not in suffixes:
        raise AcquisitionError("Unsupported Azure service endpoint")
    suffix = suffixes[service]
    if not value or not re.fullmatch(r"https://[a-z0-9][a-z0-9-]{1,61}[a-z0-9]\." + suffix + r"/?", value):
        raise AcquisitionError(f"Expected an HTTPS Azure {service} endpoint, without secrets or paths")
    return value.rstrip("/")


def _vector_configuration() -> tuple[int | None, str | None, str | None]:
    enabled = os.environ.get("AZURE_SEARCH_VECTOR_ENABLED", "false").casefold()
    if enabled not in ("true", "false"):
        raise AcquisitionError("AZURE_SEARCH_VECTOR_ENABLED must be true or false")
    if enabled == "false":
        return None, None, None
    try:
        dimensions = validate_dimensions(int(os.environ["AZURE_OPENAI_EMBEDDING_DIMENSIONS"]))
    except (KeyError, ValueError):
        raise AcquisitionError("Hybrid publishing needs explicit embedding dimensions") from None
    endpoint = _endpoint(os.environ.get("AZURE_OPENAI_ENDPOINT"), "embedding")
    deployment = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}", deployment):
        raise AcquisitionError("Hybrid publishing needs an approved embedding deployment")
    return dimensions, endpoint, deployment


def verify_results(results, ids: list[str], operation: str) -> None:
    if (
        not isinstance(results, list)
        or len(results) != len(ids)
        or {result.key for result in results} != set(ids)
        or any(not result.succeeded for result in results)
    ):
        raise AcquisitionError(f"The {operation} batch was not fully acknowledged; retry the reviewed plan idempotently")


def publish(plan: dict, *, execute: bool = False, approved: bool = False,
            create_index: bool = False, stage_blob: bool = False,
            credential_mode: str = "managed-identity") -> dict:
    summary = {"mode": "dry-run", "uploadChunks": len(plan["uploads"]),
               "deleteChunks": len(plan["deleteIds"]), "withheldDocuments": len(plan["withheld"])}
    if not execute:
        return summary
    if credential_mode not in ("managed-identity", "azure-cli"):
        raise AcquisitionError("Choose an explicit publishing credential mode")
    if not approved or os.environ.get("INGESTION_PUBLISH_ENABLED") != "true":
        raise AcquisitionError("Publishing requires --approved and INGESTION_PUBLISH_ENABLED=true")
    endpoint = _endpoint(os.environ.get("AZURE_SEARCH_ENDPOINT"), "search")
    name = os.environ.get("AZURE_SEARCH_INDEX", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,126}[a-z0-9]", name):
        raise AcquisitionError("A valid AZURE_SEARCH_INDEX is required")
    if not plan["uploads"] and not plan["deleteIds"]:
        raise AcquisitionError("No reviewed uploads or tombstones; nothing will be published")
    if len({document["id"] for document in plan["uploads"]}) != len(plan["uploads"]):
        raise AcquisitionError("A reviewed publish plan cannot contain duplicate chunk IDs")
    if any(not isinstance(document.get("content"), str) or not 1 <= len(document["content"]) <= MAX_CHUNK_CHARS
           for document in plan["uploads"]):
        raise AcquisitionError("Every reviewed upload must contain at most 8000 characters; truncation is forbidden")
    from azure.core.exceptions import AzureError
    try:
        _execute(plan, endpoint, name, create_index=create_index, stage_blob=stage_blob,
                 credential_mode=credential_mode)
    except AzureError:
        raise AcquisitionError("Azure operation failed; check scoped resource access and diagnostics") from None
    return {**summary, "mode": "published"}


def _execute(plan: dict, endpoint: str, name: str, *, create_index: bool, stage_blob: bool,
             credential_mode: str = "managed-identity") -> None:
    from azure.identity import AzureCliCredential, ManagedIdentityCredential
    from azure.search.documents import SearchClient
    from azure.search.documents.indexes import SearchIndexClient

    identity = os.environ.get("AZURE_CLIENT_ID")
    options = {"client_id": identity} if identity else {}
    selected = (ManagedIdentityCredential(**options) if credential_mode == "managed-identity"
                else AzureCliCredential(process_timeout=5))
    with selected as credential:
        with SearchClient(endpoint, name, credential) as search:
            # Apply withdrawals before optional enrichment/staging, so their failure cannot
            # leave already-known withdrawn content active in the search index.
            for start in range(0, len(plan["deleteIds"]), 100):
                ids = plan["deleteIds"][start:start + 100]
                results = search.delete_documents([{"id": key} for key in ids])
                verify_results(results, ids, "withdrawal")
            if not plan["uploads"]:
                return
            dimensions, embedding_endpoint, deployment = _vector_configuration()
            if create_index or dimensions is not None:
                with SearchIndexClient(endpoint, credential) as indexes:
                    schema = (migrate_index(indexes, build_index(name, dimensions))
                              if create_index else indexes.get_index(name))
                    if dimensions is not None:
                        field = next((field for field in schema.fields if field.name == "contentVector"), None)
                        if field is None or field.vector_search_dimensions != dimensions:
                            raise AcquisitionError("The approved Search index does not match the embedding dimensions")
            documents = []
            for chunk in plan["uploads"]:
                doc = dict(chunk)
                for field in ("checkedAt", "publisherUpdatedAt", "fetchedAt"):
                    if isinstance(doc.get(field), str) and len(doc[field]) == 10:
                        doc[field] += "T00:00:00Z"
                documents.append(doc)
            if dimensions is not None and documents:
                import requests
                with requests.Session() as session:
                    embed = azure_embedder(embedding_endpoint, deployment, dimensions, credential, session)
                    documents = enrich_documents(documents, embed, dimensions)
            if stage_blob:
                from azure.storage.blob import BlobServiceClient, ContentSettings
                blob_url = _endpoint(os.environ.get("AZURE_STORAGE_ACCOUNT_URL"), "blob")
                container = os.environ.get("AZURE_STORAGE_CONTAINER", "")
                if not re.fullmatch(r"[a-z0-9](?:[a-z0-9]|-(?!-)){1,61}[a-z0-9]", container):
                    raise AcquisitionError("A valid pre-existing AZURE_STORAGE_CONTAINER is required")
                with BlobServiceClient(blob_url, credential=credential) as blobs:
                    for chunk in documents:
                        client = blobs.get_blob_client(container, f"reviewed/{chunk['id']}.json")
                        client.upload_blob(
                            json.dumps(chunk, ensure_ascii=False).encode("utf-8"), overwrite=True,
                            content_settings=ContentSettings(content_type="application/json"),
                            metadata={"origin": "direct-publisher", "sourceid": chunk["sourceId"]},
                        )
            for start in range(0, len(documents), 100):
                batch = documents[start:start + 100]
                results = search.upload_documents(batch)
                verify_results(results, [document["id"] for document in batch], "indexing")
