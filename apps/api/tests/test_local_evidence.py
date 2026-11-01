import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpcore
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from bc_api import local_evidence
from bc_api.config import Settings
from bc_api.errors import ApiError
from bc_api.local_evidence import (
    CANADA_TERMS,
    KPL_NOTICE,
    SOURCES,
    LocalEvidenceProvider,
    PinnedBackend,
    SnapshotDocument,
    fetch_named_source,
    load_snapshots,
    parse_source,
    snapshot_evidence,
)
from bc_api.retrieval import model_evidence_json
from bc_api.security import PreviewControls, SecurityMiddleware

NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)


def legal_html(key="adult", *, currency="October 27, 2026", regulation=False):
    """Synthetic HTML shaped like CiviX, not legal guidance."""
    spec = SOURCES[key]
    date = (
        f'<span class="regCurrency"><strong>Current to {currency}.</strong></span>'
        if regulation
        else f'<div id="act:currency">Current to {currency}.</div>'
    )
    sections = "".join(
        f'<div class="section"><a name="section{number}"></a><h4>Fixture heading</h4>'
        f'<p class="sec"><span class="secnum">{number}</span>'
        "Synthetic primary rule for a parser fixture.</p>"
        '<p class="sub"><span class="num">(2)</span>'
        "Exception: retain this entire subsection and its qualifications.</p></div>"
        for number in spec.sections
    )
    return (
        f'<title>{spec.title}</title>{date}<a href="/standards/Licence.html">Licence</a>' + sections
    ).encode()


def snapshot(key="ei-overview", acquired=NOW):
    return SnapshotDocument(
        key=key,
        url=SOURCES[key].url,
        title=SOURCES[key].title + " - Canada.ca",
        publisher="Employment and Social Development Canada",
        acquired_at=acquired.isoformat(),
        publisher_updated_at="2026-10-19",
        sections=[
            {
                "heading": "Synthetic source section",
                "content": "Synthetic public guidance for parser tests, not resident advice. " * 7,
            }
        ],
    )


def snapshot_file(tmp_path, document=None):
    document = document or snapshot()
    body = json.dumps(
        {
            "version": 1,
            "use_scope": "local-noncommercial-evaluation",
            "acquisition_method": "read-only-web-fetch",
            "documents": [document.model_dump()],
        }
    ).encode()
    path = tmp_path / "evaluation-snapshot.json"
    path.write_bytes(body)
    return path, hashlib.sha256(body).hexdigest()


def local_settings(**changes):
    return Settings(
        _env_file=None,
        **{
            "app_env": "development",
            "grounded_conversation_enabled": True,
            "ai_conversation_enabled": True,
            "task_assistance_enabled": True,
            "local_evidence_evaluation_enabled": True,
            "api_allowed_hosts": "127.0.0.1,localhost,::1",
            **changes,
        },
    )


@pytest.mark.parametrize("key,regulation", [("adult", False), ("pwd-application", True)])
def test_statutory_sections_keep_qualifiers_and_truthful_currency(key, regulation):
    result = parse_source(SOURCES[key], legal_html(key, regulation=regulation), NOW)
    assert len(result.evidence) == len(SOURCES[key].sections)
    for item in result.evidence:
        assert "Exception: retain this entire subsection" in item.content
        assert item.reference.metadata.consolidation_date == "2026-10-27"
        assert item.reference.metadata.legal_status == "publisher-current-collection"
        assert item.reference.metadata.human_reviewed is False
        assert item.reference.metadata.notice == KPL_NOTICE
        assert item.reference.metadata.content_hash == item.reference.document_version
        assert "effectiveFrom" not in item.reference.metadata.model_dump(by_alias=True)


def test_model_view_omits_boilerplate_without_changing_user_provenance():
    bundle = parse_source(SOURCES["adult"], legal_html(), NOW)
    model = json.loads(model_evidence_json(bundle))
    metadata = model["evidence"][0]["reference"]["metadata"]
    assert "notice" not in metadata and "attribution" not in metadata
    assert metadata["consolidationDate"] == "2026-10-27"
    assert metadata["humanReviewed"] is False
    assert bundle.evidence[0].reference.metadata.notice == KPL_NOTICE
    assert bundle.evidence[0].reference.metadata.licence_url


@pytest.mark.parametrize(
    "change,code",
    [
        (
            lambda body: body.replace(b"Patients Property Act", b"Unexpected page"),
            "SOURCE_IDENTITY_INVALID",
        ),
        (lambda body: body.replace(b"act:currency", b"untrusted-date"), "LEGAL_CURRENCY_MISSING"),
        (lambda body: body.replace(b"October 27", b"October 1"), "LEGAL_SOURCE_STALE"),
        (lambda body: body.replace(b"October 27", b"November 2"), "LEGAL_SOURCE_STALE"),
        (
            lambda body: body.replace(b"/standards/Licence.html", b"/unknown"),
            "SOURCE_LICENCE_MISSING",
        ),
        (
            lambda body: body.replace(b'name="section3"', b'name="changed3"'),
            "SOURCE_SECTION_MISSING",
        ),
    ],
)
def test_changed_or_stale_legal_sources_fail_closed(change, code):
    with pytest.raises(ApiError) as failure:
        parse_source(SOURCES["adult"], change(legal_html()), NOW)
    assert failure.value.code == code


@pytest.mark.parametrize("heading", ["Fee $", "ITEM COLUMN 1 MATTER COLUMN 2 FEE $"])
def test_complete_fee_group_keeps_term_and_age_distinctions(heading):
    rows = [
        "4 DRIVERS' LICENCES AND DRIVERS' TESTS",
        "(a) DRIVERS' LICENCES",
        "The fee for a driver's licence is as follows:",
        "(i) issued for more than 4 years 75",
        "(ii) issued for 4 years or less 35",
        "(iii) synthetic age distinction 17",
        "(iv) synthetic learner distinction 10",
        "(v) synthetic duplicate distinction 17",
        "(vi) synthetic exception 0",
        "(b) LICENCES WITH INDICATION",
        "Unrelated plate fees 100",
    ]
    body = (
        "<title>Motor Vehicle Fees Regulation</title>"
        '<span class="regCurrency">Current to October 27, 2026.</span>'
        '<a href="/standards/Licence.html">Licence</a><table>'
        f"<tr><th>{heading}</th></tr>"
        + "".join(f"<tr><td>{row}</td></tr>" for row in rows)
        + '</table><div class="section"><a name="section2"></a><h4>Fees</h4>'
        '<p class="sec"><span class="secnum">2</span>'
        "The fees set out in the synthetic fixture are prescribed for this parser test.</p></div>"
    ).encode()
    result = parse_source(SOURCES["fees"], body, NOW)
    assert result.evidence[0].reference.section == "Section 2"
    assert "\nThe fees set out" in result.evidence[0].content
    text = result.evidence[1].content
    assert "more than 4 years" in text and "4 years or less" in text
    assert "age distinction" in text and "synthetic exception 0" in text
    assert "plate fees" not in text
    structured = body.replace(
        b"<td>(i) issued for more than 4 years 75</td>",
        b"<td></td><td>(i)</td><td>issued for more than 4 years</td><td>75</td>",
    )
    normalized = parse_source(SOURCES["fees"], structured, NOW).evidence[1]
    assert "(i)\nissued for more than 4 years: $75." in normalized.content
    assert "normalized rows" in normalized.reference.section
    for malformed in (
        body.replace(b"(b) LICENCES WITH INDICATION", b"Unexpected end"),
        body.replace(heading.encode(), b"Unknown column"),
    ):
        with pytest.raises(ApiError, match="SOURCE_TABLE_INCOMPLETE"):
            parse_source(SOURCES["fees"], malformed, NOW)


def test_canada_reader_keeps_checklist_labels_but_not_interactive_state():
    body = (
        "<title>EI regular benefits: Apply</title>"
        '<meta name="author" content="Employment and Social Development Canada">'
        '<meta name="dcterms.modified" content="2026-10-19">'
        "<main><p>Synthetic public preparation guidance, not actual benefits advice.</p>"
        "<fieldset><label>your social insurance number (SIN)</label>"
        "<label>records of employment</label></fieldset>"
        '<div class="success-message hidden">You are ready to apply</div>'
        "<script>UNTRUSTED_SCRIPT</script><nav>UNRELATED_NAVIGATION</nav>"
        + "<p>A synthetic paragraph retaining all its qualifications for this fixture.</p>" * 5
        + "</main>"
    ).encode()
    result = parse_source(SOURCES["ei-apply"], body, NOW)
    text = result.evidence[0].content
    assert "social insurance number" in text and "records of employment" in text
    assert "ready to apply" not in text and "UNTRUSTED_SCRIPT" not in text
    assert "UNRELATED_NAVIGATION" not in text
    metadata = result.evidence[0].reference.metadata
    assert metadata.licence_url == CANADA_TERMS and metadata.human_reviewed is False
    with pytest.raises(ApiError, match="SOURCE_LIST_MISSING"):
        parse_source(SOURCES["ei-apply"], body.replace(b"social insurance number", b"absent"), NOW)


def test_snapshots_are_digest_pinned_dated_copies_not_live_or_human_approvals(tmp_path):
    path, digest = snapshot_file(tmp_path)
    loaded = load_snapshots(path, digest)
    item = snapshot_evidence(loaded["ei-overview"], NOW).evidence[0]
    assert item.reference.checked_at == NOW.isoformat()
    assert item.reference.metadata.retrieval_origin == "official-snapshot"
    assert item.reference.metadata.human_reviewed is False
    assert "copy of the version available" in item.reference.metadata.notice
    assert item.reference.metadata.use_scope == "local-noncommercial-evaluation"
    assert loaded["ei-overview"].title in item.reference.metadata.attribution
    with pytest.raises(ApiError, match="SOURCE_SNAPSHOT_INVALID"):
        load_snapshots(path, "0" * 64)
    with pytest.raises(ApiError, match="SOURCE_SNAPSHOT_INVALID"):
        load_snapshots(path, None)


@pytest.mark.parametrize("age", [timedelta(days=8), timedelta(seconds=-1)])
def test_expired_or_future_snapshots_cannot_be_presented_as_current(age):
    with pytest.raises(ApiError, match="SOURCE_SNAPSHOT_STALE"):
        snapshot_evidence(snapshot(acquired=NOW - age), NOW)


def test_snapshot_route_cannot_relabel_restricted_or_foreign_content(tmp_path):
    document = snapshot().model_copy(update={"url": "https://www.icbc.com/restricted"})
    path, digest = snapshot_file(tmp_path, document)
    with pytest.raises(ApiError, match="SOURCE_SNAPSHOT_INVALID"):
        load_snapshots(path, digest)


@pytest.mark.asyncio
async def test_source_cache_is_bounded_and_cancelled_reads_do_not_commit(repository):
    fetcher = AsyncMock(return_value=legal_html(currency=datetime.now(UTC).strftime("%B %d, %Y")))
    provider = LocalEvidenceProvider(repository, fetcher=fetcher)
    first, second = await asyncio.gather(provider.source("adult"), provider.source("adult"))
    assert first == second
    fetcher.assert_awaited_once_with(SOURCES["adult"].url, 15)
    provider.clear()
    started, wait = asyncio.Event(), asyncio.Event()

    async def blocked(url, read_timeout):
        started.set()
        await wait.wait()
        return legal_html()

    provider.fetcher = blocked
    task = asyncio.create_task(provider.source("adult"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not provider.cache
    assert not provider.locks["adult"].locked()


@pytest.mark.asyncio
async def test_topic_selection_keeps_ei_exceptions_and_never_sends_private_text(repository):
    provider = LocalEvidenceProvider(repository)
    bundle = snapshot_evidence(snapshot(), NOW)
    provider.source = AsyncMock(return_value=bundle)
    await provider.retrieve("ei-regular", ["requirements", "missing-roe", "reporting"])
    keys = [call.args[0] for call in provider.source.await_args_list]
    assert keys == ["ei-eligibility", "ei-temporary", "ei-overview", "ei-after", "ei-apply"]
    provider.source.reset_mock()
    with pytest.raises(ApiError, match="SOURCE_TOPIC_INVALID"):
        await provider.retrieve("ei-regular", ["professional-sections"])
    provider.source.assert_not_awaited()
    with pytest.raises(ApiError, match="SOURCE_PROGRAMME_INVALID"):
        await provider.retrieve("comparison", ["overview"])


@pytest.mark.asyncio
async def test_named_fetch_rejects_arbitrary_urls_and_private_dns(monkeypatch):
    resolver = AsyncMock(return_value=["127.0.0.1"])
    monkeypatch.setattr(local_evidence, "resolve_addresses", resolver)
    with pytest.raises(ApiError, match="SOURCE_NOT_PERMITTED"):
        await fetch_named_source("https://www.icbc.com/driver-licensing")
    resolver.assert_not_awaited()
    with pytest.raises(ApiError, match="SOURCE_ADDRESS_DENIED"):
        await fetch_named_source(SOURCES["adult"].url)
    resolver.assert_awaited_once_with("www.bclaws.gov.bc.ca")


@pytest.mark.asyncio
async def test_network_backend_pins_only_the_registered_tls_host(monkeypatch):
    connection = AsyncMock()
    monkeypatch.setattr(httpcore, "AnyIOBackend", lambda: SimpleNamespace(connect_tcp=connection))
    backend = PinnedBackend("www.bclaws.gov.bc.ca", "142.34.0.1")
    await backend.connect_tcp("www.bclaws.gov.bc.ca", 443, timeout=4)
    assert connection.await_args.args == ("142.34.0.1", 443)
    for host, port in (("attacker.invalid", 443), ("www.bclaws.gov.bc.ca", 80)):
        with pytest.raises(OSError):
            await backend.connect_tcp(host, port)
    assert connection.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,headers,size,code",
    [
        (302, [(b"content-type", b"text/html")], 0, "SOURCE_RESPONSE_INVALID"),
        (200, [(b"content-type", b"application/pdf")], 0, "SOURCE_RESPONSE_INVALID"),
        (
            200,
            [(b"content-type", b"text/html"), (b"content-encoding", b"gzip")],
            0,
            "SOURCE_ENCODING_INVALID",
        ),
        (200, [(b"content-type", b"text/html")], 2_000_001, "SOURCE_SIZE_LIMIT"),
    ],
)
async def test_network_response_limits(monkeypatch, status, headers, size, code):
    monkeypatch.setattr(local_evidence, "resolve_addresses", AsyncMock(return_value=["142.34.0.1"]))

    async def chunks():
        yield b"x" * size

    @asynccontextmanager
    async def stream(*args, **kwargs):
        assert "Cookie" not in kwargs["headers"] and "Authorization" not in kwargs["headers"]
        yield SimpleNamespace(status=status, headers=headers, aiter_stream=chunks)

    @asynccontextmanager
    async def pool(**kwargs):
        assert isinstance(kwargs["network_backend"], PinnedBackend)
        yield SimpleNamespace(stream=stream)

    monkeypatch.setattr(httpcore, "AsyncConnectionPool", pool)
    with pytest.raises(ApiError) as error:
        await fetch_named_source(SOURCES["adult"].url)
    assert error.value.code == code


@pytest.mark.parametrize(
    "change",
    [
        {"app_env": "production"},
        {"grounded_conversation_enabled": False},
        {"api_allowed_hosts": "127.0.0.1,public.example"},
        {"api_allowed_hosts": "0.0.0.0"},
        {"api_allowed_origins": "https://public.example"},
        {
            "local_evidence_snapshot_path": "relative.json",
            "local_evidence_snapshot_sha256": "a" * 64,
        },
    ],
)
def test_local_evaluation_cannot_be_configured_as_a_public_service(change):
    with pytest.raises(ValidationError):
        local_settings(**change)


@pytest.mark.parametrize(
    "peer,headers,allowed",
    [
        ("127.0.0.1", {"x-bc-evaluation-scope": "local-noncommercial"}, True),
        ("127.0.0.1", {}, False),
        ("192.0.2.1", {"x-bc-evaluation-scope": "local-noncommercial"}, False),
        (
            "127.0.0.1",
            {
                "x-bc-evaluation-scope": "local-noncommercial",
                "x-forwarded-for": "127.0.0.1",
            },
            False,
        ),
    ],
)
def test_requests_require_loopback_peers_and_the_evaluation_proxy(peer, headers, allowed):
    settings = local_settings()
    app = Starlette(routes=[Route("/api/catalog", lambda request: JSONResponse({"ok": True}))])
    secured = SecurityMiddleware(app, settings=settings, controls=PreviewControls(settings))
    with TestClient(secured, base_url="http://127.0.0.1", client=(peer, 10000)) as client:
        response = client.get("/api/catalog", headers=headers)
    assert response.status_code == (200 if allowed else 403)
    if not allowed:
        assert response.json()["error"]["code"] == "LOCAL_EVALUATION_ONLY"
