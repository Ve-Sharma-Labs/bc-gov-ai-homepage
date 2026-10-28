import math

from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import get_bearer_token_provider
from openai import AsyncOpenAI

from bc_api.config import Settings
from bc_api.errors import ApiError


class AzureEmbeddings:
    def __init__(
        self,
        settings: Settings,
        credential: AsyncTokenCredential,
        *,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or AsyncOpenAI(
            base_url=settings.azure_openai_endpoint + "/openai/v1/",
            api_key=get_bearer_token_provider(credential, "https://ai.azure.com/.default"),
            timeout=settings.api_upstream_timeout_seconds,
            max_retries=1,
        )

    async def embed(self, text: str) -> list[float]:
        if not self.settings.azure_search_vector_enabled or not self.settings.hybrid_configured:
            raise ApiError(
                503, "EMBEDDING_NOT_CONFIGURED", "Hybrid retrieval is not fully configured."
            )
        try:
            response = await self.client.embeddings.create(
                model=self.settings.azure_openai_embedding_deployment,
                input=text,
                dimensions=self.settings.azure_openai_embedding_dimensions,
                encoding_format="float",
            )
            if len(response.data) != 1:
                raise ValueError("Unexpected embedding count.")
            vector = response.data[0].embedding
            if (
                len(vector) != self.settings.azure_openai_embedding_dimensions
                or not all(math.isfinite(item) for item in vector)
                or not any(vector)
            ):
                raise ValueError("Invalid embedding.")
            return vector
        except Exception:
            raise ApiError(
                503,
                "EMBEDDING_UNAVAILABLE",
                "Hybrid source retrieval is unavailable. No substitute embedding was generated.",
            ) from None

    async def close(self) -> None:
        await self.client.close()
