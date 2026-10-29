import json
from datetime import UTC, datetime, timedelta

import fakeredis
import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient
from starlette.responses import Response

from bc_api.context_sessions import (
    CONTEXT_COOKIE,
    InMemoryContextSessionRepository,
    RedisContextSessionRepository,
)
from bc_api.demo_personas import DemoPersonaRepository
from bc_api.errors import ApiError
from bc_api.main import create_app
from bc_api.models import ConsentReceipt, ContextSummary
from bc_api.security import SESSION_COOKIE
from bc_api.synthetic_context import (
    ConsentChangeRequest,
    SyntheticContextService,
    set_context_cookie,
)

ORIGIN = "http://localhost:3000"
PAGE_TOKEN = "context-api-page-00000001"
HEADERS = {"Origin": ORIGIN, "X-BC-Context-Page": PAGE_TOKEN}


def enabled(settings, **updates):
    return settings.model_copy(
        update={
            "synthetic_context_enabled": True,
            "synthetic_context_session_ttl_seconds": 300,
            "synthetic_context_consent_ttl_seconds": 180,
            **updates,
        }
    )


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 29, 5, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


class RecordingInvalidator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def invalidate(self, session_ref: str, reason: str) -> None:
        self.calls.append((session_ref, reason))


def contextual_client(settings, *, service=None):
    return TestClient(
        create_app(enabled(settings), context_service=service),
        headers=HEADERS,
    )


def select_persona(client: TestClient, persona_id: str = "sam-job-loss"):
    response = client.post("/api/demo/session", json={"personaId": persona_id})
    assert response.status_code == 201
    return response


def grant(client: TestClient, *scopes: str):
    response = client.post(
        "/api/context/consents",
        json={"action": "grant", "scopes": list(scopes)},
    )
    assert response.status_code == 200
    return response


def test_capability_is_explicit_and_never_claims_real_identity(client, settings):
    disabled = client.get("/api/capabilities")
    assert disabled.status_code == 200
    assert disabled.json()["syntheticContextAvailable"] is False
    assert disabled.json()["realIdentityIntegrated"] is False
    assert disabled.json()["realCitizenIdentityConfigured"] is False
    assert client.get("/api/demo/personas").status_code == 503
    assert client.delete("/api/demo/session").status_code == 204

    with contextual_client(settings) as context_client:
        advertised = context_client.get("/api/capabilities")
        assert advertised.status_code == 200
        assert advertised.json()["syntheticContextAvailable"] is True
        assert advertised.json()["realIdentityIntegrated"] is False
        assert advertised.json()["realCitizenIdentityConfigured"] is False


def test_public_persona_catalogue_is_redacted_and_does_not_create_a_session(settings):
    with contextual_client(settings) as client:
        response = client.get("/api/demo/personas")
        assert response.status_code == 200
        assert "set-cookie" not in response.headers
        personas = response.json()
        assert [persona["id"] for persona in personas] == [
            "maya-caregiver",
            "alex-disability-support",
            "sam-job-loss",
        ]
        assert all(
            set(persona)
            == {
                "id",
                "displayName",
                "summary",
                "availableCategories",
                "synthetic",
            }
            for persona in personas
        )
        public_payload = json.dumps(personas)
        assert all(
            forbidden not in public_payload
            for forbidden in (
                "categoryFacts",
                "consentScope",
                "mutableByCitizen",
                "verifiedAt",
                "recently-ended",
            )
        )


def test_session_allowlist_rejects_facts_and_sets_secure_opaque_cookie(settings):
    with contextual_client(settings) as client:
        marker = "must-not-be-reflected"
        invalid = client.post(
            "/api/demo/session",
            json={
                "personaId": "sam-job-loss",
                "facts": [{"key": "employment.status", "value": marker}],
            },
        )
        assert invalid.status_code == 422
        assert marker not in invalid.text
        assert CONTEXT_COOKIE not in client.cookies
        assert client.post(
            "/api/demo/session", json={"personaId": "arbitrary-persona"}
        ).status_code == 422
        assert client.post(
            "/api/demo/session", json={"personaId": {"id": "sam-job-loss"}}
        ).status_code == 422
        assert client.post(
            "/api/demo/session?facts=forged",
            json={"personaId": "sam-job-loss"},
        ).status_code == 422

        response = select_persona(client)
        assert set(response.json()) == {"persona", "expiresAt", "synthetic"}
        assert set(response.json()["persona"]) == {
            "id",
            "displayName",
            "summary",
            "availableCategories",
            "synthetic",
        }
        cookies = response.headers.get_list("set-cookie")
        context_cookie = next(cookie for cookie in cookies if cookie.startswith(CONTEXT_COOKIE))
        assert "HttpOnly" in context_cookie
        assert "SameSite=strict" in context_cookie
        assert "Path=/api" in context_cookie
        assert "Max-Age=300" in context_cookie
        assert "Secure" not in context_cookie
        assert len(client.cookies[CONTEXT_COOKIE]) == 43

    production_response = Response()
    set_context_cookie(
        production_response,
        "x" * 43,
        enabled(settings).model_copy(update={"app_env": "production"}),
    )
    assert "Secure" in production_response.headers["set-cookie"]


def test_consent_is_typed_minimized_and_summary_only_discloses_granted_categories(settings):
    with contextual_client(settings) as client:
        select_persona(client)
        denied = client.post(
            "/api/context/consents",
            json={"action": "grant", "scopes": ["disability-caregiving.read"]},
        )
        assert denied.status_code == 422
        assert denied.json()["error"]["code"] == "CONSENT_SCOPE_DENIED"
        assert client.post(
            "/api/context/consents",
            json={"action": "grant", "scopes": ["employment.read", "employment.read"]},
        ).status_code == 422
        assert client.post(
            "/api/context/consents",
            json={"action": "grant", "scopes": ["*"]},
        ).status_code == 422
        marker = "arbitrary-context-value"
        forged = client.post(
            "/api/context/consents",
            json={
                "action": "grant",
                "scopes": ["employment.read"],
                "facts": [{"value": marker}],
            },
        )
        assert forged.status_code == 422
        assert marker not in forged.text
        assert client.get("/api/context/summary?personaId=maya-caregiver").status_code == 422

        receipt = ConsentReceipt.model_validate(
            grant(client, "employment.read").json()
        )
        assert receipt.purpose == "personalize-job-loss-navigation"
        assert receipt.scopes == ["employment.read"]
        assert receipt.revoked_at is None

        summary_response = client.get("/api/context/summary")
        assert summary_response.status_code == 200
        summary = ContextSummary.model_validate(summary_response.json())
        assert summary.synthetic is True
        assert summary.categories == ["employment-income"]
        assert {fact.category for fact in summary.facts} == {"employment-income"}
        assert {fact.key for fact in summary.facts} == {
            "employment.end-date-band",
            "employment.record-of-employment",
            "employment.status",
            "income.change",
        }
        assert "household.dependant-count" not in summary_response.text
        assert "region.service-area" not in summary_response.text


@pytest.mark.parametrize(
    ("persona_id", "expected_categories", "denied_scope"),
    [
        (
            "maya-caregiver",
            [
                "household-dependants",
                "disability-caregiving",
                "existing-programs",
                "region-preferences",
            ],
            "identity.read",
        ),
        (
            "alex-disability-support",
            [
                "identity-residency",
                "employment-income",
                "disability-caregiving",
                "existing-programs",
                "region-preferences",
            ],
            "household.read",
        ),
        (
            "sam-job-loss",
            [
                "identity-residency",
                "household-dependants",
                "employment-income",
                "existing-programs",
                "region-preferences",
            ],
            "disability-caregiving.read",
        ),
    ],
)
def test_public_categories_and_consent_are_limited_to_each_flow_contract(
    settings,
    persona_id,
    expected_categories,
    denied_scope,
):
    with contextual_client(settings) as client:
        selected = select_persona(client, persona_id)
        assert selected.json()["persona"]["availableCategories"] == expected_categories
        denied = client.post(
            "/api/context/consents",
            json={"action": "grant", "scopes": [denied_scope]},
        )
        assert denied.status_code == 422
        assert denied.json()["error"]["code"] == "CONSENT_SCOPE_DENIED"


@pytest.mark.parametrize(
    ("persona_id", "scopes"),
    [
        (
            "maya-caregiver",
            [
                "household.read",
                "disability-caregiving.read",
                "existing-programs.read",
                "region-preferences.read",
            ],
        ),
        (
            "alex-disability-support",
            [
                "identity.read",
                "employment.read",
                "disability-caregiving.read",
                "existing-programs.read",
                "region-preferences.read",
            ],
        ),
        (
            "sam-job-loss",
            [
                "identity.read",
                "household.read",
                "employment.read",
                "existing-programs.read",
                "region-preferences.read",
            ],
        ),
    ],
)
def test_every_server_fixture_has_an_allowlisted_redacted_summary(
    settings, persona_id, scopes
):
    with contextual_client(settings) as client:
        select_persona(client, persona_id)
        grant(client, *scopes)
        response = client.get("/api/context/summary")
        assert response.status_code == 200
        summary = ContextSummary.model_validate(response.json())
        assert summary.facts
        assert all(fact.display_value for fact in summary.facts)
        assert all(fact.category in summary.categories for fact in summary.facts)


def test_revocation_fails_closed_clears_hooks_and_can_be_regranted(settings):
    context_settings = enabled(settings)
    clock = MutableClock()
    invalidator = RecordingInvalidator()
    service = SyntheticContextService(
        context_settings,
        DemoPersonaRepository(),
        InMemoryContextSessionRepository(context_settings.api_max_sessions),
        clock=clock,
        invalidation_hook=invalidator,
    )
    with TestClient(
        create_app(context_settings, context_service=service),
        headers=HEADERS,
    ) as client:
        select_persona(client)
        grant(client, "identity.read", "employment.read")
        partial = client.post(
            "/api/context/consents",
            json={"action": "revoke", "scopes": ["employment.read"]},
        )
        assert partial.status_code == 200
        assert partial.json()["scopes"] == ["identity.read"]
        assert partial.json()["revokedAt"] is None
        minimized = client.get("/api/context/summary")
        assert minimized.status_code == 200
        assert minimized.json()["categories"] == ["identity-residency"]
        assert "employment.status" not in minimized.text

        complete = client.post(
            "/api/context/consents",
            json={"action": "revoke", "scopes": ["identity.read"]},
        )
        assert complete.status_code == 200
        assert complete.json()["revokedAt"] == clock.value.isoformat().replace(
            "+00:00", "Z"
        )
        denied = client.get("/api/context/summary")
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "CONSENT_REQUIRED"
        assert [reason for _, reason in invalidator.calls] == [
            "citizen-request",
            "citizen-request",
        ]

        grant(client, "identity.read")
        assert client.get("/api/context/summary").status_code == 200


def test_context_is_bound_to_both_opaque_cookies_and_cannot_cross_sessions(settings):
    app = create_app(enabled(settings))
    headers = HEADERS
    with TestClient(app, headers=headers) as owner, TestClient(app, headers=headers) as other:
        select_persona(owner)
        grant(owner, "employment.read")
        assert owner.get("/api/context/summary").status_code == 200
        stolen_context = owner.cookies[CONTEXT_COOKIE]

        first_attempt = other.get("/api/context/summary")
        assert first_attempt.status_code == 401
        assert SESSION_COOKIE in other.cookies
        other.cookies.set(CONTEXT_COOKIE, stolen_context, path="/api")
        second_attempt = other.get("/api/context/summary")
        assert second_attempt.status_code == 401
        assert second_attempt.json()["error"]["code"] == "CONTEXT_SESSION_REQUIRED"
        assert owner.get("/api/context/summary").status_code == 200


def test_context_grant_is_bound_to_one_page_instance_and_reload_binding_loss_fails_closed(
    settings,
):
    app = create_app(enabled(settings))
    with TestClient(app, headers=HEADERS) as client:
        select_persona(client)
        grant(client, "employment.read")
        assert client.get("/api/context/summary").status_code == 200

        client.headers["X-BC-Context-Page"] = "context-api-page-00000002"
        reloaded = client.get("/api/context/summary")
        assert reloaded.status_code == 401
        assert reloaded.json()["error"]["code"] == "CONTEXT_SESSION_REQUIRED"

        client.headers.pop("X-BC-Context-Page")
        missing_binding = client.get("/api/context/summary")
        assert missing_binding.status_code == 422
        assert missing_binding.json()["error"]["code"] == "CONTEXT_PAGE_REQUIRED"

        client.headers["X-BC-Context-Page"] = "context-api-page-00000002"
        replacement = select_persona(client, "alex-disability-support")
        assert replacement.json()["persona"]["id"] == "alex-disability-support"
        grant(
            client,
            "identity.read",
            "employment.read",
            "disability-caregiving.read",
            "existing-programs.read",
        )
        assert client.get("/api/context/summary").status_code == 200


def test_replace_delete_and_anonymous_fallback_clear_all_context(settings, run_input):
    context_settings = enabled(settings)
    invalidator = RecordingInvalidator()
    service = SyntheticContextService(
        context_settings,
        DemoPersonaRepository(),
        InMemoryContextSessionRepository(context_settings.api_max_sessions),
        invalidation_hook=invalidator,
    )
    with TestClient(
        create_app(context_settings, context_service=service),
        headers=HEADERS,
    ) as client:
        select_persona(client)
        grant(client, "employment.read")
        previous = client.cookies[CONTEXT_COOKIE]
        owner = client.cookies[SESSION_COOKIE]
        replacement = select_persona(client, "maya-caregiver")
        assert replacement.json()["persona"]["id"] == "maya-caregiver"
        current = client.cookies[CONTEXT_COOKIE]
        assert current != previous
        assert client.get("/api/context/summary").status_code == 403
        assert invalidator.calls[-1][1] == "persona-changed"

        client.cookies.clear()
        client.cookies.set(
            SESSION_COOKIE, owner, domain="testserver.local", path="/api"
        )
        client.cookies.set(
            CONTEXT_COOKIE, previous, domain="testserver.local", path="/api"
        )
        assert client.get("/api/context/summary").status_code == 401
        client.cookies.clear()
        client.cookies.set(
            SESSION_COOKIE, owner, domain="testserver.local", path="/api"
        )
        client.cookies.set(
            CONTEXT_COOKIE, current, domain="testserver.local", path="/api"
        )

        deleted = client.delete("/api/demo/session")
        assert deleted.status_code == 204
        assert CONTEXT_COOKIE not in client.cookies
        assert "Max-Age=0" in deleted.headers["set-cookie"]
        assert invalidator.calls[-1][1] == "session-reset"
        assert client.delete("/api/demo/session").status_code == 204
        assert client.get("/api/context/summary").status_code == 401

        run_input["messages"][-1]["content"] = "Hi"
        run_input["forwardedProps"] = {"bc": {"version": 2, "mode": "general"}}
        anonymous = client.post("/api/agent", json=run_input)
        assert anonymous.status_code == 200


def test_session_and_consent_expiry_fail_closed(settings):
    clock = MutableClock()
    short_settings = enabled(
        settings,
        synthetic_context_session_ttl_seconds=120,
        synthetic_context_consent_ttl_seconds=60,
    )
    service = SyntheticContextService(
        short_settings,
        DemoPersonaRepository(),
        InMemoryContextSessionRepository(short_settings.api_max_sessions),
        clock=clock,
    )
    with TestClient(
        create_app(short_settings, context_service=service),
        headers=HEADERS,
    ) as client:
        select_persona(client)
        grant(client, "employment.read")
        assert client.get("/api/context/summary").status_code == 200
        clock.advance(61)
        expired_consent = client.get("/api/context/summary")
        assert expired_consent.status_code == 403
        assert expired_consent.json()["error"]["code"] == "CONSENT_REQUIRED"
        grant(client, "employment.read")
        clock.advance(60)
        expired_session = client.get("/api/context/summary")
        assert expired_session.status_code == 401
        assert expired_session.json()["error"]["code"] == "CONTEXT_SESSION_REQUIRED"


def test_context_routes_keep_origin_auth_size_and_public_control_guards(settings):
    context_settings = enabled(settings, api_max_request_bytes=1024)
    app = create_app(context_settings)
    with TestClient(app, headers=HEADERS) as client:
        assert client.post(
            "/api/demo/session",
            json={"personaId": "sam-job-loss"},
            headers={"Origin": "https://evil.example"},
        ).status_code == 403
        oversized = client.post(
            "/api/demo/session",
            content=json.dumps(
                {"personaId": "sam-job-loss", "padding": "x" * 2000}
            ),
            headers={"Content-Type": "application/json"},
        )
        assert oversized.status_code == 413
        preflight = client.options(
            "/api/demo/session",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "DELETE",
            },
        )
        assert preflight.status_code == 200
        assert "DELETE" in preflight.headers["access-control-allow-methods"]

    with TestClient(create_app(context_settings)) as no_origin:
        assert no_origin.post(
            "/api/demo/session", json={"personaId": "sam-job-loss"}
        ).status_code == 403

    auth_settings = context_settings.model_copy(
        update={"api_auth_audience": "api://synthetic-context-test"}
    )
    with TestClient(create_app(auth_settings)) as protected:
        response = protected.get("/api/demo/personas")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "SERVICE_AUTH_REQUIRED"

    rate_settings = enabled(settings, api_requests_per_minute=1)
    with TestClient(create_app(rate_settings), headers={"Origin": ORIGIN}) as limited:
        assert limited.get("/api/demo/personas").status_code == 200
        response = limited.get("/api/demo/personas")
        assert response.status_code == 429
        assert response.headers["retry-after"] == "60"

    production = context_settings.model_copy(
        update={
            "app_env": "production",
            "api_allowed_origins": "https://assistant.example.gov.bc.ca",
        }
    )
    with TestClient(
        create_app(production),
        headers={"Origin": "https://assistant.example.gov.bc.ca"},
    ) as public:
        response = public.get("/api/demo/personas")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "PUBLIC_CONTROLS_REQUIRED"


async def test_shared_repository_is_replica_safe_and_stores_metadata_only(settings):
    server = fakeredis.FakeServer()
    first_client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    second_client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    prefix = "bc:{context-test}:"
    first_repository = RedisContextSessionRepository(first_client, prefix, 100)
    second_repository = RedisContextSessionRepository(second_client, prefix, 100)
    context_settings = enabled(settings)
    clock = MutableClock()
    clock.value = datetime.now(UTC).replace(microsecond=0)
    first = SyntheticContextService(
        context_settings,
        DemoPersonaRepository(),
        first_repository,
        clock=clock,
    )
    second = SyntheticContextService(
        context_settings,
        DemoPersonaRepository(),
        second_repository,
        clock=clock,
    )
    _, token = await first.create_session(
        "anonymous-owner",
        PAGE_TOKEN,
        None,
        "sam-job-loss",
    )
    receipt = await second.change_consent(
        "anonymous-owner",
        PAGE_TOKEN,
        token,
        ConsentChangeRequest(action="grant", scopes=["employment.read"]),
    )
    assert receipt.scopes == ["employment.read"]
    assert (await first.summary("anonymous-owner", PAGE_TOKEN, token)).categories == [
        "employment-income"
    ]
    with pytest.raises(ApiError, match="CONTEXT_SESSION_REQUIRED"):
        await second.summary("different-owner", PAGE_TOKEN, token)

    keys = await first_client.keys(prefix + "context-session:*")
    assert len(keys) == 1
    stored = json.dumps(await first_client.hgetall(keys[0]))
    assert "employment.status" not in stored
    assert "recently-ended" not in stored
    assert "categoryFacts" not in stored

    await second.change_consent(
        "anonymous-owner",
        PAGE_TOKEN,
        token,
        ConsentChangeRequest(action="revoke", scopes=["employment.read"]),
    )
    with pytest.raises(ApiError, match="CONSENT_REQUIRED"):
        await first.summary("anonymous-owner", PAGE_TOKEN, token)
    await first_client.aclose()
    await second_client.aclose()
