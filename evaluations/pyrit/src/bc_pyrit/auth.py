"""Origin-bound staging authentication using the operator's existing Azure CLI sign-in."""

import asyncio
from collections.abc import AsyncGenerator
from time import time

import httpx
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import CredentialUnavailableError
from azure.identity.aio import AzureCliCredential

from bc_pyrit.contracts import CheckError


class AzureCliAuth(httpx.Auth):
    def __init__(self, *, origin: str, subscription_id: str, client_id: str):
        self.origin = httpx.URL(origin)
        if self.origin.scheme != "https":
            raise CheckError("STAGING_AUTH_CONFIGURATION_INVALID")
        self.subscription_id = subscription_id
        self.scope = f"api://{client_id}/.default"
        self._token: AccessToken | None = None
        self._lock = asyncio.Lock()

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        if (
            request.url.scheme != self.origin.scheme
            or request.url.host != self.origin.host
            or request.url.port != self.origin.port
        ):
            raise CheckError("STAGING_AUTH_ORIGIN_MISMATCH")
        async with self._lock:
            if self._token is None or self._token.expires_on <= time() + 120:
                try:
                    async with (
                        asyncio.timeout(20),
                        AzureCliCredential(
                            subscription=self.subscription_id, process_timeout=15
                        ) as credential,
                    ):
                        token = await credential.get_token(self.scope)
                except ClientAuthenticationError, CredentialUnavailableError, TimeoutError:
                    raise CheckError("STAGING_SIGN_IN_REQUIRED") from None
                if not token.token or token.expires_on <= time() + 30:
                    raise CheckError("STAGING_SIGN_IN_REQUIRED")
                self._token = token
            request.headers["Authorization"] = f"Bearer {self._token.token}"
        yield request
