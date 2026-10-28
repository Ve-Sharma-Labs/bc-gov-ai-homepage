import time
from types import SimpleNamespace
from unittest.mock import Mock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.datastructures import Headers

from bc_api.authentication import ApiAuthenticator
from bc_api.errors import ApiError

TENANT = "11111111-1111-4111-8111-111111111111"
CALLER = "22222222-2222-4222-8222-222222222222"
AUDIENCE = "33333333-3333-4333-8333-333333333333"


@pytest.fixture
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(key, **overrides):
    now = int(time.time())
    claims = {
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "tid": TENANT,
        "oid": CALLER,
        "aud": AUDIENCE,
        "iat": now,
        "nbf": now,
        "exp": now + 60,
        **overrides,
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "fixture"})


async def test_only_the_expected_service_identity_and_audience_are_accepted(settings, signing_key):
    settings = settings.model_copy(
        update={
            "api_auth_audience": AUDIENCE,
            "api_auth_tenant_id": TENANT,
            "api_auth_callers": [CALLER],
        }
    )
    keys = SimpleNamespace(
        get_signing_key_from_jwt=Mock(return_value=SimpleNamespace(key=signing_key.public_key()))
    )
    auth = ApiAuthenticator(settings, keys=keys)
    await auth.authorize(Headers({"authorization": "Bearer " + token(signing_key)}))
    for changes in (
        {"oid": "44444444-4444-4444-8444-444444444444"},
        {"aud": "another-service"},
        {"iss": "https://untrusted.example/"},
        {"exp": int(time.time()) - 1},
    ):
        with pytest.raises(ApiError, match="SERVICE_AUTH_FAILED"):
            await auth.authorize(
                Headers(
                    {
                        "authorization": "Bearer " + token(signing_key, **changes),
                    }
                )
            )


async def test_public_headers_do_not_substitute_for_service_authentication(settings):
    settings = settings.model_copy(update={"app_env": "production"})
    auth = ApiAuthenticator(settings)
    with pytest.raises(ApiError, match="SERVICE_AUTH_REQUIRED"):
        await auth.authorize(Headers({"x-bc-client": "a" * 64}))
