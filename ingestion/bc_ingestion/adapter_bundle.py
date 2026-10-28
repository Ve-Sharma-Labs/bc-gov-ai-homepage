"""Persist offline source-adapter candidates through the shared review ledger."""

from pathlib import Path

from .extract import chunk_document
from .pipeline import Ledger, save_json
from .policy import AcquisitionError
from .source_adapters import AdaptedDocument


def write_adapter_bundle(
    adapted: AdaptedDocument | list[AdaptedDocument],
    output: Path,
) -> dict:
    documents = [adapted] if isinstance(adapted, AdaptedDocument) else list(adapted)
    if not documents:
        raise AcquisitionError("At least one adapted document is required")
    output.mkdir(parents=True, exist_ok=True)
    ledger = Ledger()
    chunks = []
    for item in documents:
        ledger.record(
            item.response,
            item.source_id,
            item.publisher,
            document=item.document,
            acquisition_mode="source-adapter",
            origin="source-adapter",
            adapter_id=item.adapter_id,
        )
        entry = ledger.find(item.document.url)
        version = entry["versions"][-1]
        for index, chunk in enumerate(chunk_document(item.document)):
            chunks.append({
                "id": f"{version['documentVersion']}-{index}",
                "documentId": entry["documentId"],
                "documentVersion": version["documentVersion"],
                "adapterId": item.adapter_id,
                "sourceIdentity": item.source_identity,
                "sourceId": item.source_id,
                "url": item.document.url,
                "title": item.document.title,
                "documentType": item.document.metadata.get("documentType"),
                "content": chunk["content"],
                "section": chunk["section"],
                "sectionLocators": chunk["locators"],
                "containsExceptions": chunk["containsExceptions"],
                "chunkPart": chunk.get("partIndex", 1),
                "chunkParts": chunk.get("partCount", 1),
            })
    state_path = output / "state.json"
    review_path = output / "review-required.json"
    chunks_path = output / "chunks.json"
    identities = {
        item.document.url: item.source_identity
        for item in documents if item.source_identity is not None
    }
    review_documents = ledger.review_candidates()
    for candidate in review_documents:
        if candidate["url"] in identities:
            candidate["sourceIdentity"] = identities[candidate["url"]]
    save_json(state_path, ledger.state)
    save_json(review_path, {
        "publisherPermissionConfirmed": False,
        "notice": (
            "Source-adapter candidates only. Exact hashes, publisher permission, "
            "freshness and source-specific holds require accountable review."
        ),
        "adapters": sorted({item.adapter_id for item in documents}),
        "adapterReviewFlags": sorted({
            flag for item in documents for flag in item.review_notes
        }),
        "documents": review_documents,
    })
    save_json(chunks_path, {
        "publicationApproved": False,
        "documentCount": len(documents),
        "chunkCount": len(chunks),
        "chunks": chunks,
    })
    return {
        "mode": "candidate-only",
        "documents": len(documents),
        "chunks": len(chunks),
        "ledger": str(state_path),
        "reviewCandidates": str(review_path),
        "chunkArtifact": str(chunks_path),
        "publicationApproved": False,
    }
