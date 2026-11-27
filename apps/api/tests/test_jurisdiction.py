import copy
import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from ag_ui.core import (
    RunAgentInput,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from azure.core.exceptions import ResourceNotFoundError
from fastapi.testclient import TestClient
from pydantic import ValidationError

from bc_api.agent_policy import general_instructions, instructions_for
from bc_api.agents import agent_definitions, general_agent_definition
from bc_api.catalog import CatalogRepository
from bc_api.config import Settings
from bc_api.controls import SharedControls
from bc_api.demo_personas import DemoPersonaFixtureError, load_demo_persona_fixture
from bc_api.demo_rules import DemoRuleSetError, load_demo_program_rule_set
from bc_api.errors import ApiError
from bc_api.foundry import FoundryRuntime
from bc_api.grounding_packs import load_grounding_packs
from bc_api.jurisdiction import content_path, load_jurisdiction, pack_scope, repository_root
from bc_api.local_evidence import LocalEvidenceProvider, fetch_named_source, load_snapshots
from bc_api.main import create_app
from bc_api.models import Catalog, Evidence, EvidenceBundle, Journey, SourceHealth, SourceReference
from bc_api.output import OutputGate
from bc_api.protocol import progress_event
from bc_api.retrieval import EvidenceLedger
from bc_api.security import Run
from bc_api.source_conflicts import SGI_RENEWAL_URL, sgi_renewal_fee_conflict
from bc_api.urls import official_url, validate_public_destination


def test_source_progress_uses_the_selected_jurisdiction():
    with pack_scope(load_jurisdiction("sk")):
        assert progress_event("retrieving").value["message"] == (
            "Checking official Saskatchewan sources..."
        )
    with pack_scope(load_jurisdiction("bc")):
        assert progress_event("retrieving").value["message"] == "Checking official BC sources..."


def test_saskatchewan_source_free_navigation_cannot_include_model_facts():
    sk = load_jurisdiction("sk")
    question = "Which Saskatchewan government service would you like help finding?"
    with pack_scope(sk):
        repository = CatalogRepository(sk.path("catalog"))
        for text, allowed in ((question, True), (question + " The stock will rise.", False)):
            gate = OutputGate(repository, EvidenceLedger(), allow_clarification=True)
            gate.hold(TextMessageStartEvent(message_id="answer", role="assistant"))
            gate.hold(TextMessageContentEvent(message_id="answer", delta=text))
            gate.hold(TextMessageEndEvent(message_id="answer"))
            if allowed:
                assert gate.finish()
                assert gate.response_kind == "dialogue"
            else:
                with pytest.raises(ApiError, match="CITATION_REQUIRED"):
                    gate.finish()


def sgi_renewal_evidence(evidence, total="108"):
    source = evidence.evidence[0].model_copy(deep=True)
    source.reference = source.reference.model_copy(
        update={"source_id": "sk-sgi-content", "url": SGI_RENEWAL_URL}
    )
    source.content = (
        f"The total will be ${total}: $25 in year 1, and $27 in years 2 through 5."
    )
    return EvidenceBundle(evidence=[source])


@pytest.mark.parametrize(
    ("query", "total", "expected"),
    [
        ("How much does renewing my Saskatchewan driver's licence cost?", "108", True),
        ("How much does renewing my Saskatchewan driver's licence cost?", "133", False),
        ("How do I renew my Saskatchewan driver's licence?", "108", False),
        ("How much does a hunting licence renewal cost?", "108", False),
    ],
)
def test_sgi_fee_handoff_requires_a_relevant_question_and_a_real_conflict(
    evidence, query, total, expected
):
    bundle = sgi_renewal_evidence(evidence, total)
    assert (sgi_renewal_fee_conflict(query, bundle.evidence) is not None) is expected


def test_conflicting_sgi_payment_quote_is_withheld_even_when_exact(evidence):
    sk = load_jurisdiction("sk")
    with pack_scope(sk):
        repository = CatalogRepository(sk.path("catalog"), sk)
        for total, allowed in (("108", False), ("133", True)):
            bundle = sgi_renewal_evidence(evidence, total)
            ledger = EvidenceLedger()
            ledger.add(bundle)
            gate = OutputGate(repository, ledger)
            gate.hold(TextMessageStartEvent(message_id="answer", role="assistant"))
            gate.hold(
                TextMessageContentEvent(
                    message_id="answer",
                    delta=f"{bundle.evidence[0].content} [SGI]({SGI_RENEWAL_URL})",
                )
            )
            gate.hold(TextMessageEndEvent(message_id="answer"))
            if allowed:
                assert gate.finish()
            else:
                with pytest.raises(ApiError, match="CRITICAL_CLAIM_UNVERIFIED"):
                    gate.finish()


async def test_sgi_fee_conflict_returns_a_source_handoff_without_model_work(
    monkeypatch, configured, evidence, run_input
):
    from bc_api.models import AgentBinding
    from bc_api.streaming import stream_run

    sk = load_jurisdiction("sk")
    with pack_scope(sk):
        repository = CatalogRepository(sk.path("catalog"), sk)
        settings = configured.model_copy(
            update={
                "jurisdiction": "sk",
                "foundry_general_agent": AgentBinding(name="test-general", version="1"),
            }
        )
        bundle = sgi_renewal_evidence(evidence)
        retriever = SimpleNamespace(retrieve=AsyncMock(return_value=bundle))
        monkeypatch.setattr("bc_api.foundry.AzureRetriever", lambda *args: retriever)
        runtime = FoundryRuntime(settings, repository, project=object(), search=object())
        runtime.ensure_general_ready = AsyncMock()
        run_input["messages"][-1]["content"] = (
            "How much does renewing my Saskatchewan driver's licence cost?"
        )
        run_input["forwardedProps"] = {"bc": {"version": 2, "mode": "general"}}
        request = RunAgentInput.model_validate(run_input)
        run = Run(request.run_id, request.thread_id, "owner")
        run.finish = AsyncMock(return_value="finished")
        events = [
            json.loads(frame.removeprefix("data: ").strip())
            async for frame in stream_run(request, run, runtime, repository, settings)
            if frame.startswith("data: ")
        ]
    text = "".join(event.get("delta", "") for event in events)
    assert "inconsistent" in text and SGI_RENEWAL_URL in text and "$" not in text
    assert events[-1]["type"] == "RUN_FINISHED"
    assert run.response_kind == "handoff" and run.response_origin == "application"
    run.finish.assert_awaited_once_with("finished", 0)


@pytest.fixture(autouse=True)
def pending_pack_fixture(monkeypatch):
    """Exercise pending activation explicitly rather than depend on the live operator pack."""
    root = repository_root() / "jurisdictions" / "sk"
    manifest_path = root / "jurisdiction.json"
    programme_path = root / "content" / "source-programme.json"
    catalogue_path = root / "content" / "pilot-catalog.json"
    original_text, original_bytes = Path.read_text, Path.read_bytes

    def read_text(path, *args, **kwargs):
        text = original_text(path, *args, **kwargs)
        if path == manifest_path:
            value = json.loads(text)
            value["researchHosts"] = ["www.saskatchewan.ca"]
            value["sourcePolicy"]["approvalStatus"] = "pending-rag-permission"
            value["sourcePolicy"].pop("operationReview", None)
            return json.dumps(value)
        if path == programme_path:
            value = json.loads(text)
            value["publicationPolicy"] = "exact-hash-human-review"
            value["sources"] = [source for source in value["sources"]
                                if source["host"] == "www.saskatchewan.ca"]
            value["accessObservations"] = [item for item in value["accessObservations"]
                                          if item["host"] == "www.saskatchewan.ca"]
            return json.dumps(value)
        return text

    def read_bytes(path):
        if path == catalogue_path:
            return json.dumps({
                "schemaVersion": 1, "jurisdiction": "sk", "asOf": datetime.now(UTC).isoformat(),
                "sources": [], "journeys": [], "locations": [],
            }).encode()
        return original_bytes(path)

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)


def sk_settings(**overrides):
    return Settings(
        jurisdiction="sk",
        api_allowed_hosts="localhost,127.0.0.1,testserver",
        api_allowed_origins="http://localhost:3000",
        **overrides,
    )


@pytest.fixture
def sk_client():
    with TestClient(
        create_app(sk_settings()), headers={"Origin": "http://localhost:3000"}
    ) as client:
        yield client


def test_security_rejection_preserves_backend_jurisdiction_header(sk_client):
    response = sk_client.get("/api/catalog", headers={"Origin": "https://untrusted.invalid"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_DENIED"
    assert response.headers["X-Jurisdiction"] == "sk"


@pytest.mark.parametrize("selected", ["../bc", "BC", "/bc", "sk\\..\\bc", "unknown"])
def test_unknown_and_traversal_pack_rejected(selected):
    with pytest.raises(ValueError, match="identifier|Unknown jurisdiction"):
        load_jurisdiction(selected)


@pytest.mark.parametrize("path", [
    "../data/pilot-catalog.json", "/data/pilot-catalog.json",
    "data\\pilot-catalog.json", "C:/data/pilot-catalog.json", "data//catalog.json",
])
def test_content_traversal_rejected(path):
    with pytest.raises(ValueError, match="relative|escapes"):
        content_path(path, repository_root())


def test_installed_package_discovers_working_directory_packs(monkeypatch):
    import bc_api.jurisdiction as loader

    root = repository_root()
    monkeypatch.setattr(loader, "__file__", str(root.anchor + "installed\\bc_api\\jurisdiction.py"))
    monkeypatch.chdir(root / "apps" / "api")
    assert repository_root() == root
    assert load_jurisdiction("sk").path("catalog").is_file()


def test_installed_docker_app_discovery(monkeypatch):
    import bc_api.jurisdiction as loader

    root = repository_root()
    real_path = Path

    def mapped_path(value):
        return root if value == "/app" else real_path(value)

    mapped_path.cwd = lambda: real_path(root.anchor)
    monkeypatch.setattr(loader, "__file__", root.anchor + "installed\\bc_api\\jurisdiction.py")
    monkeypatch.setattr(loader, "Path", mapped_path)
    assert loader.repository_root() == root


def test_baked_pack_runtime_mismatch_rejected(monkeypatch):
    monkeypatch.setenv("BAKED_JURISDICTION", "sk")
    with pytest.raises(ValueError, match="baked jurisdiction"):
        Settings(jurisdiction="bc")
    assert sk_settings().jurisdiction == "sk"


def test_cached_pack_does_not_survive_a_different_selection(monkeypatch):
    settings = Settings()
    assert settings.pack.id == "bc"
    assert settings.model_copy(update={"jurisdiction": "sk"}).pack.id == "sk"
    monkeypatch.setenv("BAKED_JURISDICTION", "sk")
    with pytest.raises(ValueError, match="baked jurisdiction"):
        create_app(settings)


def test_image_stamp_cannot_be_bypassed_by_changing_environment(monkeypatch):
    root = repository_root()
    original_file, original_read = Path.is_file, Path.read_text
    marker = root / "jurisdictions" / ".selected"
    monkeypatch.setattr(
        Path, "is_file", lambda self: True if self == marker else original_file(self)
    )
    monkeypatch.setattr(
        Path, "read_text",
        lambda self, *a, **kw: "sk" if self == marker else original_read(self, *a, **kw),
    )
    monkeypatch.delenv("BAKED_JURISDICTION", raising=False)
    with pytest.raises(ValueError, match="baked jurisdiction"):
        load_jurisdiction("bc", root)
    assert load_jurisdiction("sk", root).id == "sk"


def test_manifest_identity_and_foreign_content_rejected(monkeypatch):
    import bc_api.jurisdiction as loader

    real_read = loader.read_json

    def wrong_identity(path):
        document = real_read(path)
        if path.name == "jurisdiction.json":
            document["id"] = "bc"
        return document

    monkeypatch.setattr(loader, "read_json", wrong_identity)
    with pytest.raises(ValueError, match="identity mismatch"):
        load_jurisdiction("sk")
    monkeypatch.setattr(loader, "read_json", real_read)
    manifest = copy.deepcopy(load_jurisdiction("sk").manifest)
    manifest["content"]["catalog"] = "data/pilot-catalog.json"
    monkeypatch.setattr(
        loader, "read_json",
        lambda path: manifest if path.name == "jurisdiction.json" else real_read(path),
    )
    with pytest.raises(ValueError, match="selected jurisdiction pack"):
        load_jurisdiction("sk")


@pytest.mark.parametrize("status", ["approved", "reviewed", "pending-rag-permisson",
                                   "existing-reviewed-snapshots-only"])
def test_unknown_or_legacy_non_bc_source_status_never_grants_rights(monkeypatch, status):
    import bc_api.jurisdiction as loader

    original = loader.read_json
    manifest = copy.deepcopy(load_jurisdiction("sk").manifest)
    manifest["sourcePolicy"]["approvalStatus"] = status
    monkeypatch.setattr(
        loader, "read_json",
        lambda path: manifest if path.name == "jurisdiction.json" else original(path),
    )
    with pytest.raises(ValueError, match="Unsupported sourcePolicy"):
        load_jurisdiction("sk")


def test_recognized_reviewed_status_without_evidence_is_not_permission(monkeypatch):
    import bc_api.jurisdiction as loader

    original = loader.read_json
    manifest = copy.deepcopy(load_jurisdiction("sk").manifest)
    manifest["sourcePolicy"]["approvalStatus"] = "reviewed-operation-grants"
    monkeypatch.setattr(
        loader, "read_json",
        lambda path: manifest if path.name == "jurisdiction.json" else original(path),
    )
    with pytest.raises(ValueError, match="requires operationReview"):
        load_jurisdiction("sk")


@pytest.mark.parametrize("override", [
    {"content_catalog_path": repository_root() / "data" / "pilot-catalog.json"},
    {"azure_search_index": "bc-pilot-public-v2"},
    {"azure_search_metadata_index": "bc-pilot-public-v2"},
    {"api_control_namespace": "bcassist-pilot"},
    {"foundry_general_agent": {
        "name": "bc-general", "version": "1", "model_deployment": "model",
    }},
    {"azure_search_endpoint": "https://bcassist-pilot.search.windows.net"},
])
def test_sk_rejects_foreign_data_resources_and_state(override):
    with pytest.raises(ValueError, match="selected jurisdiction|JURISDICTION|namespace"):
        sk_settings(**override)


@pytest.mark.parametrize("override", [
    {"foundry_general_agent": {
        "name": "sk-general", "version": "1", "model_deployment": "model",
    }},
    {"azure_search_index": "sk-unapproved-index"},
    {"azure_search_endpoint": "https://skassist-pilot.search.windows.net"},
    {"azure_openai_embedding_deployment": "sk-embedding"},
    {"azure_search_vector_enabled": True},
    {"foundry_iq_enabled": True},
    {"webiq_enabled": True},
    {"local_evidence_snapshot_path": Path("snapshot.json")},
])
def test_pending_rag_rights_cannot_be_bypassed(override):
    with pytest.raises(ValueError, match="pending-rag-permission"):
        sk_settings(**override)


@pytest.mark.parametrize("override", [
    {"synthetic_context_enabled": True},
    {"ai_conversation_enabled": True},
    {"conversation_discovery_enabled": True},
])
def test_legacy_capabilities_cannot_be_enabled_for_sk(override):
    with pytest.raises(ValueError, match="not registered|no registered"):
        sk_settings(**override)


def test_sk_control_namespace_and_content_are_manifest_selected():
    settings = sk_settings()
    assert settings.api_control_namespace == "sk-pilot"
    assert settings.azure_search_metadata_index == "sk-pilot-public"
    assert settings.azure_search_index == "sk-pilot-public"
    assert settings.azure_search_semantic_config == "sk-public-guidance"
    assert not settings.search_configured
    assert settings.catalog_path == settings.pack.path("catalog")
    assert sk_settings(api_control_namespace="skassist-pilot").api_control_namespace == (
        "skassist-pilot"
    )
    assert SharedControls(settings, client=SimpleNamespace()).prefix == "sk:{sk-pilot}:"
    assert SharedControls(Settings(), client=SimpleNamespace()).prefix == "bc:{bc-pilot}:"


def test_sk_bootstrap_is_empty_and_does_not_probe_model(sk_client):
    runtime = sk_client.app.state.runtime
    runtime.ensure_ready = AsyncMock(side_effect=AssertionError("No model readiness probe"))
    catalog = sk_client.get("/api/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["jurisdiction"] == "sk"
    assert catalog.headers["x-jurisdiction"] == "sk"
    assert all(catalog.json()[key] == [] for key in ("sources", "journeys", "locations"))
    capabilities = sk_client.get("/api/capabilities").json()
    assert capabilities["jurisdiction"] == "sk"
    assert capabilities["sourcePolicyStatus"] == "pending-rag-permission"
    assert capabilities["registeredFlows"] == []
    assert not any(capabilities[key] for key in (
        "aiConfigured", "retrievalReady", "syntheticContextAvailable",
        "discoveryAvailable", "conversationAvailable", "guidedJourneysAvailable",
    ))
    assert sk_client.get("/api/demo/personas").json() == []
    assert sk_client.get("/api/locations").json() == {"locations": []}
    assert sk_client.get("/api/locations?service=icbc-licensing").status_code == 400
    assert sk_client.get("/api/journeys/licence-renewal").status_code == 404


@pytest.mark.parametrize("text", ["Hello", "I need disability benefits", "renew my BCID"])
def test_sk_chat_never_replays_bc_facts(sk_client, run_input, text):
    run_input["messages"][-1]["content"] = text
    run_input["forwardedProps"] = {"bc": {"version": 2, "mode": "general"}}
    response = sk_client.post("/api/agent", json=run_input)
    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert events[-1]["type"] == "RUN_FINISHED", events
    output = "".join(event.get("delta", "") for event in events)
    assert "Saskatchewan" in output
    assert all(foreign not in output for foreign in (
        "B.C.", "Service BC", "British Columbia", "gov.bc.ca", "ICBC",
    ))
    if text != "Hello":
        assert "https://www.saskatchewan.ca/contact-us" in output
        assert "permission" in output


@pytest.mark.parametrize("path", [
    "/api/conversation", "/api/discovery", "/api/research", "/api/context/summary",
])
def test_sk_advanced_routes_are_closed(sk_client, path):
    response = sk_client.get(path)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "JURISDICTION_CAPABILITY_UNAVAILABLE"
    assert response.headers["cache-control"] == "no-store"


def test_client_cannot_choose_pack_or_replay_bc_pathway(sk_client, run_input):
    assert sk_client.get("/api/catalog?jurisdiction=bc").status_code == 422
    assert sk_client.get("/api/capabilities?index=bc-pilot-public-v2").status_code == 422
    run_input["forwardedProps"] = {
        "bc": {"version": 2, "mode": "pathway", "journeyId": "licence-renewal"},
    }
    assert sk_client.post("/api/agent", json=run_input).status_code == 503
    run_input["forwardedProps"] = {"bc": {"version": 2, "mode": "general", "jurisdiction": "bc"}}
    assert sk_client.post("/api/agent", json=run_input).status_code == 422


def test_mismatched_stream_expectation_rejected_before_route_or_model(sk_client, run_input):
    runtime = sk_client.app.state.runtime
    runtime.events = AsyncMock(side_effect=AssertionError("Mismatched request cannot run a model"))
    run_input["forwardedProps"] = {"bc": {"version": 2, "mode": "general"}}
    response = sk_client.post(
        "/api/agent", json=run_input, headers={"X-Expected-Jurisdiction": "bc"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JURISDICTION_MISMATCH"
    assert response.headers["x-jurisdiction"] == "sk"
    assert response.headers["cache-control"] == "no-store"
    assert sk_client.app.state.runs.runs == {}
    runtime.events.assert_not_called()
    assert sk_client.get(
        "/api/conversation", headers={"X-Expected-Jurisdiction": "bc"}
    ).json()["error"]["code"] == "JURISDICTION_MISMATCH"


def test_matching_expectation_is_not_client_selection(sk_client, run_input):
    assert sk_client.get(
        "/api/catalog", headers={"X-Expected-Jurisdiction": "sk"}
    ).json()["jurisdiction"] == "sk"
    assert sk_client.get(
        "/api/catalog", headers={"X-Jurisdiction": "sk"}
    ).status_code == 422
    run_input["messages"][-1]["content"] = "Hello"
    run_input["forwardedProps"] = {"bc": {"version": 2, "mode": "general"}}
    response = sk_client.post(
        "/api/agent", json=run_input, headers={"X-Expected-Jurisdiction": "sk"}
    )
    assert response.status_code == 200
    assert response.headers["x-jurisdiction"] == "sk"


def test_foreign_catalog_contents_and_cache_fail_closed(monkeypatch, catalog_data):
    pack = load_jurisdiction("sk")
    repository = CatalogRepository(pack.path("catalog"), pack)
    assert repository.get().sources == []
    original_stat = Path.stat
    original_read = Path.read_bytes
    target = pack.path("catalog")
    monkeypatch.setattr(
        Path, "stat",
        lambda self, *a, **kw: (
            SimpleNamespace(st_mtime_ns=1, st_size=100)
            if self == target else original_stat(self, *a, **kw)
        ),
    )
    monkeypatch.setattr(
        Path, "read_bytes",
        lambda self: json.dumps(catalog_data).encode() if self == target else original_read(self),
    )
    with pytest.raises(ApiError, match="source validation"):
        repository.get()
    assert repository._catalog is None
    with pack_scope(pack), pytest.raises(ValidationError):
        Catalog.model_validate({**catalog_data, "jurisdiction": "sk"})
    with pack_scope(pack), pytest.raises(ValidationError):
        Catalog.model_validate({
            "schemaVersion": 1, "asOf": "2026-11-23T00:00:00Z",
            "sources": [], "journeys": [], "locations": [],
        })


async def test_publishers_and_research_are_scoped_without_global_leakage():
    bc, sk = load_jurisdiction("bc"), load_jurisdiction("sk")
    with pack_scope(sk):
        assert official_url("https://www.saskatchewan.ca/contact-us")
        with pytest.raises(ValueError, match="official publisher"):
            official_url("https://www2.gov.bc.ca/gov/content/home")
        with pytest.raises(ValueError, match="approved scope"):
            await validate_public_destination("https://www.icbc.com/")
        assert load_grounding_packs().coverage() == []
        with pytest.raises(DemoPersonaFixtureError, match="not registered"):
            load_demo_persona_fixture(bc.path("personas"))
        with pytest.raises(DemoRuleSetError, match="not registered"):
            load_demo_program_rule_set(bc.path("programmeRules"), bc.path("catalog"))
        assert "B.C." not in general_instructions(sk)
        with pytest.raises(ValueError, match="does not register"):
            instructions_for("licence-renewal", sk)
    with pack_scope(bc):
        assert official_url("https://www2.gov.bc.ca/gov/content/home")
        with pytest.raises(ValueError, match="official publisher"):
            official_url("https://www.saskatchewan.ca/contact-us")


async def test_sk_local_evidence_and_agent_export_escape_hatches_are_closed():
    pack = load_jurisdiction("sk")
    repository = CatalogRepository(pack.path("catalog"), pack)
    with pack_scope(pack):
        with pytest.raises(ApiError, match="another jurisdiction"):
            LocalEvidenceProvider(repository)
        with pytest.raises(ApiError, match="BC-only"):
            load_snapshots(None, None)
        with pytest.raises(ApiError, match="not registered"):
            await fetch_named_source("https://www.bclaws.gov.bc.ca/")
        for export in (agent_definitions, general_agent_definition):
            with pytest.raises(ValueError, match="pending-rag-permission"):
                export(repository, prefix="sk-pilot", model_deployment="model")


def test_sk_environment_selection_and_activation_gate(monkeypatch):
    monkeypatch.setenv("JURISDICTION", "sk")
    assert Settings().jurisdiction == "sk"
    monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", "https://skassist-pilot.search.windows.net")
    with pytest.raises(ValueError, match="pending-rag-permission"):
        Settings()


def test_empty_environment_selection_is_not_a_silent_bc_fallback(monkeypatch):
    monkeypatch.setenv("JURISDICTION", "")
    with pytest.raises(ValueError, match="identifier"):
        Settings()


def test_bc_runtime_and_state_cannot_be_injected_into_sk(settings, repository):
    from bc_api.foundry import FoundryRuntime

    with pytest.raises(ValueError, match="another jurisdiction"):
        create_app(sk_settings(), runtime=FoundryRuntime(settings, repository))
    with pytest.raises(ValueError, match="another jurisdiction namespace"):
        create_app(
            sk_settings(), control_store=SharedControls(settings, client=SimpleNamespace())
        )


def test_shared_journey_contract_accepts_pack_owned_identifiers(catalog_data):
    document = copy.deepcopy(catalog_data["journeys"][0])
    document["id"] = "future-reviewed-journey"
    assert Journey.model_validate(document).id == "future-reviewed-journey"
    invalid_bc = {**catalog_data, "journeys": [document]}
    with pytest.raises(ValidationError, match="seven approved journeys"):
        Catalog.model_validate(invalid_bc)


@pytest.fixture
def offline_reviewed_sk(monkeypatch, request):
    """Simulate a rights-cleared pack only in memory; shipped rights/data remain untouched."""
    from bc_ingestion.metadata import digest
    from bc_ingestion.operation_rights import OPERATIONS

    import bc_api.jurisdiction as loader

    original_read = loader.read_json
    manifest = copy.deepcopy(load_jurisdiction("sk").manifest)
    fixture = (
        repository_root() / "jurisdictions" / "sk" / "content"
        / f".offline-rights-fixture-{uuid4().hex}"
    )
    fixture.mkdir()
    request.addfinalizer(lambda: shutil.rmtree(fixture, ignore_errors=True))
    review_path = fixture / "review.json"
    manifest["sourcePolicy"]["approvalStatus"] = "reviewed-operation-grants"
    manifest["sourcePolicy"]["operationReview"] = {
        "path": review_path.relative_to(repository_root()).as_posix()
    }
    now = datetime.now(UTC)
    permitted = {"rag", "generated-summary", "publication"}
    publisher_evidence = []
    for key, body in {
        "terms": b"SYNTHETIC TEST TERMS ONLY",
        "robots": b"User-agent: BCPilotIngest\nAllow: /\n",
        "permission": b"SYNTHETIC TEST PERMISSION ONLY; NOT ACTUAL PUBLISHER RIGHTS",
    }.items():
        (fixture / f"{key}.txt").write_bytes(body)
        publisher_evidence.append({
            "id": key, "kind": "publisher-written-permission" if key == "permission" else key,
            "host": "www.saskatchewan.ca",
            "url": None if key == "permission" else (
                "https://www.saskatchewan.ca/robots.txt" if key == "robots"
                else "https://www.saskatchewan.ca/terms"
            ),
            "file": f"{key}.txt", "sha256": hashlib.sha256(body).hexdigest(),
            "capturedAt": (now - timedelta(minutes=2)).isoformat(),
            "mediaType": "text/plain", "publisherReference": f"synthetic-test:{key}",
            "permittedOperations": sorted(permitted) if key == "permission" else [],
        })
    review = {
        "schemaVersion": 3, "jurisdictionId": "sk",
        "programmeHash": digest(original_read(
            repository_root() / manifest["content"]["sourceProgramme"]
        )),
        "packIdentity": {"jurisdictionId": "sk", "manifestHash": digest(manifest)},
        "reviewId": "synthetic-offline-review", "reviewer": "SYNTHETIC TEST REVIEWER",
        "reviewedAt": (now - timedelta(minutes=1)).isoformat(),
        "expiresAt": (now + timedelta(days=1)).isoformat(),
        "revocation": {
            "status": "active", "reference": "synthetic-test:revocation", "revokedAt": None
        },
        "evidence": publisher_evidence,
        "grants": [{
            "host": "www.saskatchewan.ca", "pathPrefixes": ["/"], "formats": ["html", "robots"],
            "decisions": {
                operation: {
                    "status": "granted" if operation in permitted else (
                        "denied" if operation in {"training", "fine-tuning"} else "pending"
                    ),
                    "evidenceIds": ["permission"] if operation in permitted else [],
                } for operation in OPERATIONS
            },
        }],
    }
    review_bytes = json.dumps(review).encode()
    review_path.write_bytes(review_bytes)
    monkeypatch.setenv("OPERATION_RIGHTS_REVIEW_SHA256", hashlib.sha256(review_bytes).hexdigest())
    monkeypatch.setattr(
        loader, "read_json",
        lambda path: (
            copy.deepcopy(manifest)
            if path == repository_root() / "jurisdictions" / "sk" / "jurisdiction.json"
            else original_read(path)
        ),
    )
    timestamp = datetime.now(UTC).isoformat()
    url = "https://www.saskatchewan.ca/offline-synthetic-fixture"
    document = {
        "schemaVersion": 1, "jurisdiction": "sk", "asOf": timestamp,
        "sources": [{
            "id": "sk-offline-fixture", "title": "Offline synthetic source",
            "publisher": "Offline Saskatchewan test fixture", "url": url,
            "description": "Synthetic offline evidence, not actual government guidance.",
            "checkedAt": timestamp, "publisherUpdatedAt": None,
            "status": "available", "topics": ["offline-testing"],
        }],
        "journeys": [], "locations": [],
    }
    path = repository_root() / "jurisdictions" / "sk" / "content" / "pilot-catalog.json"
    original_bytes = Path.read_bytes
    monkeypatch.setattr(
        Path, "read_bytes",
        lambda self: json.dumps(document).encode() if self == path else original_bytes(self),
    )
    settings = sk_settings(
        foundry_project_endpoint="https://skassist-fixture.services.ai.azure.com/api/projects/pilot",
        foundry_general_agent={
            "name": "sk-fixture-general", "version": "1", "model_deployment": "offline-model",
        },
        azure_search_endpoint="https://skassist-fixture.search.windows.net",
    )
    with pack_scope(settings.pack):
        evidence = EvidenceBundle(evidence=[Evidence(
            reference=SourceReference(
                source_id="sk-offline-fixture", document_id="sk-fixture-document",
                document_version="sk-fixture-v1", title="Offline synthetic source",
                publisher="Offline Saskatchewan test fixture", url=url,
                checked_at=timestamp, publisher_updated_at=None, section="Offline testing",
            ),
            content="This synthetic fixture demonstrates a reviewed-source answer path.",
        )])
    try:
        yield settings, evidence
    finally:
        shutil.rmtree(fixture)


def test_reviewed_sk_accepts_infrastructure_resource_names(offline_reviewed_sk):
    settings = sk_settings(
        azure_search_endpoint="https://srch-skassist-fixture.search.windows.net",
        azure_openai_endpoint="https://ai-skassist-fixture.openai.azure.com",
        foundry_project_endpoint="https://ai-skassist-fixture.services.ai.azure.com/api/projects/pilot",
    )
    assert settings.search_configured


@pytest.mark.parametrize("override", [
    {"azure_search_endpoint": "https://srch-bcassist-fixture.search.windows.net"},
    {"azure_openai_endpoint": "https://ai-bcassist-fixture.openai.azure.com"},
    {"foundry_project_endpoint": "https://ai-bcassist-fixture.services.ai.azure.com/api/projects/pilot"},
    {"azure_search_endpoint": "https://srch-skassistevil.search.windows.net"},
])
def test_reviewed_sk_rejects_foreign_infrastructure_resource_names(offline_reviewed_sk, override):
    with pytest.raises(ValueError, match="jurisdiction namespace"):
        sk_settings(**override)


def test_reviewed_sk_pack_accepts_same_pending_user_attestation(offline_reviewed_sk, monkeypatch):
    settings, _ = offline_reviewed_sk
    pack = settings.pack
    path = pack.root / pack.manifest["sourcePolicy"]["operationReview"]["path"]
    review = json.loads(path.read_text(encoding="utf-8"))
    review["packIdentity"] = pack.pending_identity
    review["reviewId"] = "user-attestation:synthetic"
    review["evidence"][-1]["kind"] = "user-attestation"
    review["evidence"][-1]["publisherReference"] = "user-attestation:synthetic"
    body = json.dumps(review).encode()
    path.write_bytes(body)
    monkeypatch.setenv("OPERATION_RIGHTS_REVIEW_SHA256", hashlib.sha256(body).hexdigest())
    reviewed_pack = type(pack)(pack.root, copy.deepcopy(pack.manifest))
    reviewed_pack.authorize_source("https://www.saskatchewan.ca/offline-synthetic-fixture")
    assert reviewed_pack.operation_provider.report()["authorizationBasis"] == "user-attested"


def test_reviewed_non_bc_capabilities_and_generic_answer_path(offline_reviewed_sk, run_input):
    settings, evidence = offline_reviewed_sk
    repository = CatalogRepository(settings.catalog_path, settings.pack)
    text = (
        "This synthetic fixture demonstrates a reviewed-source answer path. "
        f"[Offline source]({evidence.evidence[0].reference.url})"
    )

    class OfflineRuntime(FoundryRuntime):
        model_calls = 0

        async def _events(self, request, context, *, context_plan=None):
            self.model_calls += 1
            context.model_work_started = True
            context.ledger.add(evidence)
            yield RunStartedEvent(run_id=request.run_id, thread_id=request.thread_id)
            yield TextMessageStartEvent(message_id="sk-answer", role="assistant")
            yield TextMessageContentEvent(message_id="sk-answer", delta=text)
            yield TextMessageEndEvent(message_id="sk-answer")
            yield RunFinishedEvent(run_id=request.run_id, thread_id=request.thread_id)

    runtime = OfflineRuntime(settings, repository)
    runtime.source_health = SourceHealth(status="ready", usable_documents=1)
    runtime.ensure_general_ready = AsyncMock()
    runtime.ensure_sources_ready = AsyncMock()
    runtime.ensure_ready = AsyncMock(side_effect=AssertionError("No legacy BC pathway probe"))
    run_input["messages"][-1]["content"] = "Explain the offline synthetic fixture."
    run_input["forwardedProps"] = {"bc": {"version": 2, "mode": "general"}}
    with TestClient(
        create_app(settings, runtime=runtime), headers={"Origin": "http://localhost:3000"}
    ) as client:
        capabilities = client.get("/api/capabilities").json()
        assert capabilities["jurisdiction"] == "sk"
        assert capabilities["aiConfigured"]
        assert capabilities["generalChatConfigured"] and capabilities["retrievalReady"]
        assert capabilities["journeys"] == {}
        assert capabilities["requestVersions"] == [2]
        assert not capabilities["guidedJourneysAvailable"]
        response = client.post("/api/agent", json=run_input)
        assert response.status_code == 200
        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines() if line.startswith("data: ")
        ]
        assert events[-1]["type"] == "RUN_FINISHED", events
        assert "".join(event.get("delta", "") for event in events) == text
        assert runtime.model_calls == 1
        runtime.ensure_general_ready.assert_awaited()
        runtime.ensure_sources_ready.assert_awaited()
        runtime.ensure_ready.assert_not_awaited()
    definition = general_agent_definition(repository, prefix="sk-fixture", model_deployment="model")
    tools = definition["definition"]["tools"]
    assert [tool["name"] for tool in tools] == ["search_approved_sources"]
    assert tools[0]["parameters"]["properties"]["journey_id"]["type"] == "null"
    assert "BC" not in tools[0]["description"]


def test_reviewed_rights_do_not_grant_embeddings_or_out_of_scope_urls(offline_reviewed_sk):
    settings, evidence = offline_reviewed_sk
    url = evidence.evidence[0].reference.url
    settings.pack.authorize_source(url)
    with pytest.raises(ValueError, match="embedding has no affirmative publisher grant"):
        settings.pack.authorize_source(url, embedding=True)
    with pytest.raises(ValueError, match="exact-publisher"):
        settings.pack.authorize_source("https://www2.gov.bc.ca/gov/content/home")


def test_pinned_publisher_evidence_changes_revoke_runtime_access(offline_reviewed_sk):
    settings, evidence = offline_reviewed_sk
    provider = settings.pack.operation_provider
    provider.evidence_paths["permission"].write_bytes(b"CHANGED SYNTHETIC PERMISSION")
    with pytest.raises(ValueError, match="rights-evidence-changed"):
        settings.pack.authorize_source(evidence.evidence[0].reference.url)


def reviewed_sk_row(settings, bundle):
    from bc_ingestion.metadata import EXTRACTION_METHOD

    reference = bundle.evidence[0].reference
    return {
        **reference.model_dump(by_alias=True), "id": "synthetic-chunk", "status": "active",
        "content": bundle.evidence[0].content, "metadataVersion": 1,
        "sourceIds": [reference.source_id], "documentType": "guidance",
        "contentHash": "a" * 64, "extractionHash": "b" * 64, "reviewHash": "c" * 64,
        "rightsStatus": "candidate-acquisition-permitted",
        "rightsReviewId": settings.pack.operation_provider.review["reviewId"],
        "rightsHash": settings.pack.operation_provider.review_hash,
        "mediaType": "text/html", "extractionMethod": EXTRACTION_METHOD,
        "responseHash": "d" * 64,
    }


def test_retrieved_non_bc_chunks_require_bound_operation_and_snapshot_metadata(offline_reviewed_sk):
    from bc_api.retrieval import validate_evidence_row

    settings, bundle = offline_reviewed_sk
    row = reviewed_sk_row(settings, bundle)
    repository = CatalogRepository(settings.catalog_path, settings.pack)
    allowed = {source.id: source for source in repository.get().sources}
    with pack_scope(settings.pack):
        result, reason = validate_evidence_row(
            row, allowed, set(allowed), settings, datetime.now(UTC), None
        )
        assert result is not None and reason is None
        for invalid in (
            {**row, "rightsHash": "f" * 64},
            {**row, "rightsReviewId": "another-publisher-review"},
            {**row, "metadataVersion": None},
            {**row, "url": "https://www2.gov.bc.ca/gov/content/home"},
        ):
            result, reason = validate_evidence_row(
                invalid, allowed, set(allowed), settings, datetime.now(UTC), None
            )
            assert result is None and reason == "invalid"


def reviewed_sk_formats(settings, formats, monkeypatch, **overrides):
    provider = settings.pack.operation_provider
    review = json.loads(provider.path.read_bytes())
    review["grants"][0]["formats"] = [*formats, "robots"]
    body = json.dumps(review).encode()
    provider.path.write_bytes(body)
    monkeypatch.setenv("OPERATION_RIGHTS_REVIEW_SHA256", hashlib.sha256(body).hexdigest())
    return Settings(**{**settings.model_dump(), **overrides})


def reviewed_sk_pdf_row(settings, bundle):
    from bc_ingestion.metadata import PDF_EXTRACTION_METHOD

    return {
        **reviewed_sk_row(settings, bundle), "metadataVersion": 2,
        "mediaType": "application/pdf", "extractionMethod": PDF_EXTRACTION_METHOD,
        "responseHash": "a" * 64, "pageCount": 2,
        "contentHashBasis": "original-response-bytes", "section": "Page 1",
    }


@pytest.mark.parametrize(("formats", "change", "accepted"), [
    (["html"], {}, False),
    (["html"], {"format": "html"}, False),
    (["pdf"], {}, True),
    (["pdf"], {"url": "https://www.saskatchewan.ca/offline-fixture.pdf"}, True),
    (["pdf"], {"mediaType": "text/html"}, False),
    (["pdf"], {"metadataVersion": 1}, False),
    (["pdf"], {"extractionMethod": "direct-publisher-html/section-aware-v2"}, False),
    (["pdf"], {"responseHash": "d" * 64}, False),
    (["pdf"], {"pageCount": True}, False),
    (["pdf"], {"pageCount": 101}, False),
    (["pdf"], {"contentHashBasis": "extracted-text"}, False),
    (["pdf"], {"rightsHash": "f" * 64}, False),
    (["pdf"], {"rightsReviewId": "another-review"}, False),
])
def test_reviewed_pdf_format_cannot_borrow_html_grants(
    offline_reviewed_sk, monkeypatch, formats, change, accepted,
):
    from bc_api.retrieval import validate_evidence_row

    settings, bundle = offline_reviewed_sk
    settings = reviewed_sk_formats(settings, formats, monkeypatch)
    row = {**reviewed_sk_pdf_row(settings, bundle), **change}
    repository = CatalogRepository(settings.catalog_path, settings.pack)
    allowed = {source.id: source for source in repository.get().sources}
    with pack_scope(settings.pack):
        result, reason = validate_evidence_row(
            row, allowed, set(allowed), settings, datetime.now(UTC), None
        )
    assert (result is not None) is accepted
    assert reason == (None if accepted else "invalid")


@pytest.mark.parametrize(("formats", "change", "accepted"), [
    (["html"], {}, True),
    (["pdf"], {}, False),
    (["html"], {"url": "https://www.saskatchewan.ca/misleading.pdf"}, False),
    (["pdf"], {"url": "https://www.saskatchewan.ca/misleading.pdf"}, False),
    (["html", "pdf"], {"url": "https://www.saskatchewan.ca/misleading.pdf"}, False),
    (["html"], {"mediaType": "application/pdf"}, False),
    (["html"], {"extractionMethod": "direct-publisher-pdf/page-text-v1"}, False),
    (["html"], {"pageCount": 2}, False),
    (["html"], {"contentHashBasis": "original-response-bytes"}, False),
])
def test_reviewed_html_format_does_not_inherit_pdf_url_rights(
    offline_reviewed_sk, monkeypatch, formats, change, accepted,
):
    from bc_api.retrieval import validate_evidence_row

    settings, bundle = offline_reviewed_sk
    settings = reviewed_sk_formats(settings, formats, monkeypatch)
    row = {**reviewed_sk_row(settings, bundle), **change}
    repository = CatalogRepository(settings.catalog_path, settings.pack)
    allowed = {source.id: source for source in repository.get().sources}
    with pack_scope(settings.pack):
        result, reason = validate_evidence_row(
            row, allowed, set(allowed), settings, datetime.now(UTC), None
        )
    assert (result is not None) is accepted
    assert reason == (None if accepted else "invalid")


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata_enabled", [False, True])
async def test_generic_retrieval_and_health_accept_reviewed_extensionless_pdf(
    offline_reviewed_sk, monkeypatch, metadata_enabled,
):
    from bc_api.retrieval import DOCUMENT_FORMAT_FIELDS, AzureRetriever

    settings, bundle = offline_reviewed_sk
    settings = reviewed_sk_formats(
        settings, ["pdf"], monkeypatch, azure_search_metadata_enabled=metadata_enabled,
        azure_search_metadata_reviewed=metadata_enabled,
    )
    row = reviewed_sk_pdf_row(settings, bundle)
    calls = []

    async def search(**options):
        calls.append(options)

        async def rows():
            yield row
        return rows()

    repository = CatalogRepository(settings.catalog_path, settings.pack)
    retriever = AzureRetriever(settings, repository, SimpleNamespace(search=search))
    with pack_scope(settings.pack):
        health = await retriever.inspect_sources()
        answer = await retriever.retrieve("Synthetic extensionless PDF")
    assert health.usable_documents == 1 and health.status == "ready"
    assert len(answer.evidence) == 1 and answer.evidence[0].reference.section == "Page 1"
    for call in calls:
        assert set(DOCUMENT_FORMAT_FIELDS) <= set(call["select"])
    if metadata_enabled:
        assert "(metadataVersion eq 1 or metadataVersion eq 2)" in calls[-1]["filter"]


def test_expired_operation_review_blocks_source_access(offline_reviewed_sk):
    settings, evidence = offline_reviewed_sk
    settings.pack.operation_provider.clock = lambda: datetime.now(UTC) + timedelta(days=2)
    with pytest.raises(ValueError, match="rights-expired-or-revoked"):
        settings.pack.authorize_source(evidence.evidence[0].reference.url)


def test_reviewed_pack_staging_preserves_independent_review_pin(offline_reviewed_sk):
    from bc_api.jurisdiction import stage_jurisdiction

    settings, _ = offline_reviewed_sk
    fixture = repository_root() / f".rs-{uuid4().hex[:8]}"
    source, output = fixture / "s", fixture / "o"
    try:
        shutil.copytree(
            settings.pack.root / "jurisdictions" / "sk", source / "jurisdictions" / "sk"
        )
        (source / "jurisdictions" / "sk" / "jurisdiction.json").write_text(
            json.dumps(settings.pack.manifest), encoding="utf-8"
        )
        (source / settings.pack.manifest["content"]["sourceProgramme"]).write_text(
            settings.pack.path("sourceProgramme").read_text(encoding="utf-8"), encoding="utf-8"
        )
        staged = stage_jurisdiction("sk", source, output)
        assert staged.operation_provider.review_hash == settings.pack.operation_provider.review_hash
        assert (output / "jurisdictions" / ".operation-rights-review.sha256").read_text(
            encoding="utf-8"
        ) == settings.pack.operation_provider.expected_sha256
        assert staged.operation_provider.evidence_paths["permission"].is_file()
    finally:
        shutil.rmtree(fixture, ignore_errors=True)


def test_node_source_policy_helper_validates_and_rejects_tampered_review(offline_reviewed_sk):
    settings, _ = offline_reviewed_sk
    root = repository_root()
    fixture = root / f".nj-{uuid4().hex[:8]}"
    source = fixture / "s"
    script = """
        import { pathToFileURL } from "node:url";
        const { loadJurisdiction, assertReviewedSourcePolicy } =
          await import(pathToFileURL(process.argv[1]).href);
        const pack = loadJurisdiction("sk", process.argv[2]);
        assertReviewedSourcePolicy(pack, process.env, process.argv[2]);
        console.log("accepted");
    """
    node = shutil.which("node")
    assert node is not None, "Node interpreter is unavailable for source-policy integration."
    try:
        shutil.copytree(
            root / "jurisdictions" / "sk", source / "jurisdictions" / "sk"
        )
        (source / "jurisdictions" / "sk" / "jurisdiction.json").write_text(
            json.dumps(settings.pack.manifest), encoding="utf-8"
        )
        (source / settings.pack.manifest["content"]["sourceProgramme"]).write_text(
            settings.pack.path("sourceProgramme").read_text(encoding="utf-8"), encoding="utf-8"
        )

        def verify():
            return subprocess.run(
                [
                    node, "--input-type=module", "-e", script,
                    str(root / "scripts" / "jurisdiction.mjs"), str(source),
                ],
                cwd=root, env=dict(os.environ), capture_output=True, text=True, timeout=30,
            )

        accepted = verify()
        assert accepted.returncode == 0, (
            "Actual Node/Python source-policy verification failed; check interpreter/dependencies: "
            + accepted.stderr
        )
        assert accepted.stdout.strip() == "accepted"
        review = source.joinpath(
            *settings.pack.manifest["sourcePolicy"]["operationReview"]["path"].split("/")
        )
        original_review = review.read_bytes()
        review.write_bytes(original_review + b"\n")
        rejected = verify()
        assert rejected.returncode != 0
        assert "Reviewed source policy verification failed" in rejected.stderr
        assert "accepted" not in rejected.stdout
        review.write_bytes(original_review)
        evidence = settings.pack.operation_provider.evidence_paths["permission"]
        (source / evidence.relative_to(root)).write_bytes(b"TAMPERED SYNTHETIC TEST EVIDENCE")
        rejected = verify()
        assert rejected.returncode != 0
        assert "Reviewed source policy verification failed" in rejected.stderr
        assert "accepted" not in rejected.stdout
    finally:
        shutil.rmtree(fixture, ignore_errors=True)


def test_reviewed_but_unavailable_sources_are_not_reported_as_ready(offline_reviewed_sk, run_input):
    from bc_api.dialogue import source_handoff

    settings, _ = offline_reviewed_sk
    repository = CatalogRepository(settings.catalog_path, settings.pack)
    runtime = FoundryRuntime(
        settings, repository,
        project=SimpleNamespace(close=AsyncMock()),
        search=SimpleNamespace(
            search=AsyncMock(side_effect=ResourceNotFoundError()), close=AsyncMock(),
        ),
    )
    runtime.ensure_general_ready = AsyncMock()
    runtime.ensure_sources_ready = AsyncMock(
        side_effect=ApiError(503, "SOURCES_UNAVAILABLE", "Offline source unavailable.")
    )
    runtime.warm = AsyncMock()
    with TestClient(
        create_app(settings, runtime=runtime), headers={"Origin": "http://localhost:3000"}
    ) as client:
        capabilities = client.get("/api/capabilities").json()
        assert not capabilities["aiConfigured"] and not capabilities["generalChatConfigured"]
        assert not capabilities["retrievalReady"]
        assert "pending" not in capabilities["message"]
        run_input["messages"][-1]["content"] = "Explain the offline source."
        run_input["forwardedProps"] = {"bc": {"version": 2, "mode": "general"}}
        response = client.post("/api/agent", json=run_input)
        assert response.status_code == 200
        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines() if line.startswith("data: ")
        ]
        assert events[-1]["type"] == "RUN_FINISHED", events
        output = "".join(event.get("delta", "") for event in events)
        assert "https://www.saskatchewan.ca/contact-us" in output
        assert "pending" not in output
        runtime.search.search.assert_awaited_once()
    handoff = source_handoff("offline fixture", repository)
    assert "pending" not in handoff.text
    assert "https://www.saskatchewan.ca/contact-us" in handoff.text
