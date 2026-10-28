"""Bounded Azure embedding enrichment of already reviewed publication documents."""

import json
import math
import re

from .policy import AcquisitionError


def validate_dimensions(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 3072:
        raise AcquisitionError("Embedding dimensions must be explicitly configured between 1 and 3072")
    return value


def validate_vectors(values: list, count: int, dimensions: int) -> list[list[float]]:
    validate_dimensions(dimensions)
    if not isinstance(values, list) or len(values) != count:
        raise AcquisitionError("The embedding result count does not match the reviewed input")
    result = []
    for vector in values:
        if (
            not isinstance(vector, list) or len(vector) != dimensions
            or any(type(value) not in (int, float) or abs(value) > 3.4028235e38
                   or not math.isfinite(value) for value in vector)
            or not any(vector)
        ):
            raise AcquisitionError("The embedding response has invalid or mismatched vectors")
        result.append([float(value) for value in vector])
    return result


def enrich_documents(documents: list[dict], embed, dimensions: int) -> list[dict]:
    validate_dimensions(dimensions)
    enriched = []
    for start in range(0, len(documents), 16):
        batch = documents[start:start + 16]
        if any(
            document.get("status") != "active"
            or not isinstance(document.get("content"), str)
            or not document["content"].strip()
            or len(document["content"]) > 4000
            for document in batch
        ):
            raise AcquisitionError("Only intact, reviewed API-compatible chunks can be embedded")
        vectors = validate_vectors(embed([document["content"] for document in batch]),
                                   len(batch), dimensions)
        enriched.extend({**document, "contentVector": vector}
                        for document, vector in zip(batch, vectors, strict=True))
    return enriched


def azure_embedder(endpoint: str, deployment: str, dimensions: int, credential, session):
    validate_dimensions(dimensions)
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}", deployment):
        raise AcquisitionError("A reviewed embedding deployment name is required")

    def embed(texts: list[str]) -> list[list[float]]:
        import requests
        token = credential.get_token("https://cognitiveservices.azure.com/.default").token
        try:
            with session.post(
                endpoint + "/openai/v1/embeddings",
                headers={"Authorization": f"Bearer {token}"},
                json={"model": deployment, "input": texts,
                      "dimensions": dimensions, "encoding_format": "float"},
                timeout=20, allow_redirects=False, stream=True,
            ) as response:
                if response.status_code != 200:
                    raise AcquisitionError("Azure embedding failed; no replacement vectors were generated")
                content = bytearray()
                for chunk in response.iter_content(65536):
                    content.extend(chunk)
                    if len(content) > 2_000_000:
                        raise AcquisitionError("The embedding response exceeded its byte limit")
                data = json.loads(content)
            if not isinstance(data, dict):
                raise AcquisitionError("The embedding response is not a valid result object")
            rows = data.get("data")
            if not isinstance(rows, list) or len(rows) != len(texts):
                raise AcquisitionError("The embedding response is incomplete")
            indexed = {}
            for row in rows:
                if not isinstance(row, dict) or type(row.get("index")) is not int:
                    raise AcquisitionError("Invalid embedding response index")
                index = row["index"]
                if index in indexed or not 0 <= index < len(texts):
                    raise AcquisitionError("Duplicate or unexpected embedding response index")
                indexed[index] = row.get("embedding")
            return validate_vectors([indexed[index] for index in range(len(texts))],
                                    len(texts), dimensions)
        except (requests.RequestException, ValueError, KeyError, TypeError):
            raise AcquisitionError("Azure embedding could not be verified; check the approved deployment") from None

    return embed
