"""Authenticate the web service, not an anonymous resident identity."""

import asyncio

import jwt
from jwt import PyJWKClient
from starlette.datastructures import Headers

from bc_api.config import Settings
from bc_api.errors import ApiError


class ApiAuthenticator:
    def __init__(self, settings: Settings, *, keys: PyJWKClient | None = None):
        self.settings = settings
        self.keys = keys
        self.callers = {caller.lower() for caller in settings.api_auth_callers}
        if self.keys is None and settings.api_auth_tenant_id:
            self.keys = PyJWKClient(
                f"https://login.microsoftonline.com/{settings.api_auth_tenant_id}/discovery/v2.0/keys",
                cache_keys=True,
                max_cached_keys=16,
                lifespan=300,
                timeout=5,
            )

    def _validate(self, token: str) -> None:
        header = jwt.get_unverified_header(token)
        if (
            header.get("alg") != "RS256"
            or not isinstance(header.get("kid"), str)
            or len(header["kid"]) > 128
        ):
            raise jwt.InvalidTokenError("Unsupported signature header")
        if self.keys is None:
            raise ApiError(503, "API_AUTH_UNAVAILABLE", "Service authentication is not configured.")
        key = self.keys.get_signing_key_from_jwt(token).key
        tenant = self.settings.api_auth_tenant_id
        claims = jwt.decode(
            token,
            key=key,
            algorithms=["RS256"],
            audience=self.settings.api_auth_audience,
            issuer=[
                f"https://sts.windows.net/{tenant}/",
                f"https://login.microsoftonline.com/{tenant}/v2.0",
            ],
            options={"require": ["exp", "iat", "nbf", "iss", "aud", "tid", "oid"]},
        )
        if claims.get("tid") != tenant or str(claims.get("oid", "")).lower() not in self.callers:
            raise jwt.InvalidTokenError("Unapproved service identity")

    async def authorize(self, headers: Headers) -> None:
        if not self.settings.api_auth_audience and self.settings.app_env == "development":
            return
        authorization = headers.get("authorization", "")
        if not authorization.startswith("Bearer ") or not 1 <= len(authorization) <= 16384:
            raise ApiError(401, "SERVICE_AUTH_REQUIRED", "Use the assistant through its website.")
        try:
            await asyncio.to_thread(self._validate, authorization.removeprefix("Bearer "))
        except jwt.PyJWKClientConnectionError:
            raise ApiError(
                503, "API_AUTH_UNAVAILABLE", "Service authentication is unavailable."
            ) from None
        except jwt.InvalidTokenError, jwt.PyJWKClientError:
            raise ApiError(401, "SERVICE_AUTH_FAILED", "Service authentication failed.") from None
