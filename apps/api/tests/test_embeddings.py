import json
import time

import httpx
import pytest
from azure.core.credentials import AccessToken
from azure.identity.aio import get_bearer_token_provider
from openai import AsyncOpenAI

from bc_api.embeddings import AzureEmbeddings
from bc_api.errors import ApiError


@pytest.mark.parametrize("vector", [[0.25, 0.5, 0.75], [0.0, 0.0, 0.0], [0.25]])
async def test_real_native_embedding_transport(configured, vector):
    scopes_seen = []

    class Credential:
        async def get_token(self, *scopes, **kwargs):
            scopes_seen.extend(scopes)
            return AccessToken("offline-test-token", int(time.time()) + 3600)

    configured = configured.model_copy(
        update={
            "azure_search_vector_enabled": True,
            "azure_openai_endpoint": "https://test.openai.azure.com",
            "azure_openai_embedding_deployment": "approved-deployment",
            "azure_openai_embedding_dimensions": 3,
        }
    )

    async def handler(request):
        assert request.url.path == "/openai/v1/embeddings"
        assert json.loads(request.content) == {
            "input": "Public query",
            "model": "approved-deployment",
            "dimensions": 3,
            "encoding_format": "float",
        }
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "approved-deployment",
                "data": [{"object": "embedding", "index": 0, "embedding": vector}],
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
        )

    credential = Credential()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = AsyncOpenAI(
            base_url=configured.azure_openai_endpoint + "/openai/v1/",
            api_key=get_bearer_token_provider(credential, "https://ai.azure.com/.default"),
            http_client=http,
            max_retries=0,
        )
        embedder = AzureEmbeddings(configured, credential, client=client)
        if len(vector) != 3 or not any(vector):
            with pytest.raises(ApiError) as error:
                await embedder.embed("Public query")
            assert error.value.code == "EMBEDDING_UNAVAILABLE"
        else:
            assert await embedder.embed("Public query") == vector
        assert scopes_seen == ["https://ai.azure.com/.default"]
        await embedder.close()
