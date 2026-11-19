import hashlib
import json
import shutil

import pytest
from pyrit.memory import CentralMemory, SQLiteMemory
from pyrit.models import AttackOutcome, SeedPrompt
from pyrit.registry import ScenarioPresetRegistry, ScenarioRegistry
from pyrit.scenario.core import DatasetAttackConfiguration
from test_manual import FixtureApp, configuration, make_target

from bc_pyrit.catalog import ROOT, import_catalog, load_catalog, prepare_sources
from bc_pyrit.contracts import CheckError, digest
from bc_pyrit.ledger import Ledger
from bc_pyrit.local import prepare, renew_window, target_config, window_status
from bc_pyrit.local_scenarios import BCGovFixed, register_local_components
from bc_pyrit.manual import ManualSettings


@pytest.fixture
def local_root(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    data = root / "data" / "evaluations"
    data.mkdir(parents=True)
    shutil.copyfile(
        ROOT / "data" / "evaluations" / "pyrit-conversation-cases.json",
        data / "pyrit-conversation-cases.json",
    )
    pack = json.loads((ROOT / "data" / "evaluations" / "pyrit-local-pack.json").read_bytes())
    raw = (
        b"prompt,type,note,focus\nA benign fixture question,safe,,\n"
        b"A contrast fixture,contrast_test,,\n"
    )
    pack["xstest"]["sha256"] = hashlib.sha256(raw).hexdigest()
    pack["xstest"]["rows"] = 2
    (data / "pyrit-local-pack.json").write_text(json.dumps(pack))
    cache = root / ".cache" / "copyrit" / "datasets"
    cache.mkdir(parents=True)
    (cache / "xstest.csv").write_bytes(raw)

    def forbidden(*_, **__):
        raise AssertionError("Setup must not download when its pinned cache is present")

    monkeypatch.setattr("bc_pyrit.catalog.httpx.stream", forbidden)
    return root


@pytest.fixture
async def local_memory(tmp_path, monkeypatch):
    instance = SQLiteMemory.__new__(SQLiteMemory)
    instance.__init__(db_path=str(tmp_path / "memory.sqlite"), silent=True)
    monkeypatch.setattr(CentralMemory, "get_memory_instance", lambda: instance)
    ScenarioPresetRegistry.reset_registry_singleton()
    ScenarioRegistry.reset_registry_singleton()
    ScenarioPresetRegistry.get_registry_singleton().configure_source(str(tmp_path / "presets"))
    yield instance
    await instance.dispose_engine_async()
    ScenarioPresetRegistry.reset_registry_singleton()
    ScenarioRegistry.reset_registry_singleton()


def test_shared_suite_hash_and_fixed_subset_keep_original_semantics(local_root):
    catalog = load_catalog(local_root)
    assert catalog.suite_hash == "ca4adda22bde3bfbe2662fe4c8bd850bffb0bbb13925a93063e56fa4844f15be"
    assert len(catalog.suite.expected("offline")) == 24
    assert len(catalog.suite.expected("live")) == 22
    groups = catalog.groups(catalog.fixed_name)
    assert len(groups) == 17
    assert len(catalog.skipped) == 5
    assert not any(
        seed.metadata.get("case", {}).get("offline_check")
        for seed in catalog.datasets[0].seeds
    )
    for group in groups:
        metadata = group.objective.metadata
        case = next(c for c in catalog.suite.cases if c.id == metadata["case_id"])
        variant = next(v for v in case.variants if v.id == metadata["variant_id"])
        assert [p.value for p in group.prompts] == variant.prompts
        assert metadata["case"]["safe_behavior"] == case.safe_behavior
        assert metadata["repetitions"] == case.repetitions
    assert sum(g.objective.metadata["repetitions"] for g in groups) == 19


async def test_import_restart_is_idempotent_and_preserves_user_data(local_root, local_memory):
    await local_memory.add_seeds_to_memory_async(
        seeds=[SeedPrompt(value="User-owned fixture", data_type="text", dataset_name="my-data")],
        added_by="test-user",
    )
    first = await import_catalog(local_memory, load_catalog(local_root))
    second = await import_catalog(local_memory, load_catalog(local_root))
    assert first == second
    assert sorted(x["examples"] for x in first["datasets"].values()) == [2, 3, 17]
    summaries = {x.dataset_name: x for x in await local_memory.get_seed_dataset_summaries_async()}
    assert summaries["my-data"].seed_pieces == 1


@pytest.mark.parametrize("corrupt", ["suite", "cache"])
def test_corrupt_inputs_fail_before_any_import(local_root, corrupt):
    path = (
        local_root / "data" / "evaluations" / "pyrit-conversation-cases.json"
        if corrupt == "suite" else local_root / ".cache" / "copyrit" / "datasets" / "xstest.csv"
    )
    if corrupt == "suite":
        value = json.loads(path.read_bytes())
        value["cases"][0]["safe_behavior"] += " changed"
        path.write_text(json.dumps(value))
    else:
        path.write_bytes(b"partial")
    with pytest.raises(CheckError, match="HASH_MISMATCH"):
        prepare_sources(local_root)


async def test_preparing_components_sends_nothing_and_preserves_edited_presets(
    local_root, local_memory
):
    catalog = load_catalog(local_root)
    await import_catalog(local_memory, catalog)
    summary = register_local_components(catalog)
    presets = ScenarioPresetRegistry.get_registry_singleton()
    entry = presets.get_preset(name=summary["presets"][0])
    updated = entry.preset.model_copy(update={"description": "User edit"})
    presets.save_preset(preset=updated, expected_version=entry.version)
    register_local_components(catalog)
    assert presets.get_preset(name=updated.name).preset.description == "User edit"
    metadata = ScenarioRegistry.get_registry_singleton().get_all_registered_class_metadata()
    assert [item.registry_name for item in metadata] == ["bcgov.fixed"]
    assert not presets.check_preset(preset=updated)
    assert not await local_memory.get_attack_results_async()


async def test_native_script_execution_uses_live_replies_and_cleans_session(
    local_root, local_memory, tmp_path
):
    catalog = load_catalog(local_root)
    await import_catalog(local_memory, catalog)
    register_local_components(catalog)
    group = next(
        g for g in catalog.groups(catalog.fixed_name)
        if g.objective.metadata["case_id"] == "non-bc-conversation"
    )
    fixture = FixtureApp()
    target, ledger = make_target(tmp_path, fixture)
    registry = ScenarioRegistry.get_registry_singleton()
    metadata = registry.get_registered_class_metadata("bcgov.fixed")
    scenario = BCGovFixed()
    scenario.set_params_from_args(args={
        "objective_target": target, "max_concurrency": 10,
        "scenario_techniques": [metadata.technique_class("bcgov_fixed_script")],
        "dataset_config": DatasetAttackConfiguration(seed_groups=[group], max_total=1),
    })
    await scenario.initialize_async()
    assert not fixture.sent
    assert scenario.params["max_concurrency"] == 1
    await scenario.run_async()
    assert len(fixture.sent) == 3
    revisions = [b["forwardedProps"]["bc"]["conversation"]["revision"] for b, _ in fixture.sent]
    assert revisions == [0, 1, 2]
    assert not target._conversations
    assert any(method == "DELETE" for method, *_ in fixture.controls)
    results = await local_memory.get_attack_results_async()
    assert results and all(r.outcome == AttackOutcome.UNDETERMINED for r in results)
    assert ledger.state()["stop"] is None


def test_canonical_identity_does_not_inject_defaults(local_root):
    path = local_root / "data" / "evaluations" / "pyrit-conversation-cases.json"
    raw = json.loads(path.read_bytes())
    catalog = load_catalog(local_root)
    assert digest(raw) == catalog.suite_hash
    assert digest(catalog.suite.model_dump(mode="json", exclude_unset=True)) == catalog.suite_hash
    assert digest(catalog.suite.model_dump(mode="json")) != catalog.suite_hash


def expired_window(root, monkeypatch):
    runtime = root / ".cache" / "copyrit"
    path = runtime / "old-window" / "target.json"
    path.parent.mkdir()
    settings = ManualSettings.model_validate(configuration(wall_seconds=3600))
    path.write_text(settings.model_dump_json())
    ledger = Ledger.open_manual(
        path.parent / "manual-budget.sqlite", limits=settings.limits(), identity=settings.identity()
    )
    ledger.charge("app")
    started = ledger.state()["started"]
    monkeypatch.setattr("bc_pyrit.local.time.time", lambda: started + 3601)
    (runtime / ".env.local").write_text(f"BC_PYRIT_MANUAL_CONFIG='{path}'\n")
    return path, ledger


def test_reload_and_decline_never_reset_old_window(local_root, monkeypatch):
    path, ledger = expired_window(local_root, monkeypatch)
    before = ledger.path.read_bytes()
    report = prepare(local_root, port=18765, browse_only=True)
    assert not report["window"]["ready"]
    assert report["window"]["renewable"]
    assert target_config(local_root) == path
    assert ledger.path.read_bytes() == before
    assert "BC_PYRIT_BROWSE_ONLY='true'" in (
        local_root / ".cache" / "copyrit" / "local-pack.env"
    ).read_text()


def test_explicit_renewal_creates_separate_window_without_erasing_charges(
    local_root, monkeypatch
):
    old, ledger = expired_window(local_root, monkeypatch)
    before = ledger.path.read_bytes()
    new = renew_window(old, local_root / ".cache" / "copyrit")
    assert new != old and new.is_file()
    assert not (new.parent / "manual-budget.sqlite").exists()
    assert window_status(new)["ready"]
    assert json.loads(new.read_bytes())["request_limit"] == 20
    assert ledger.path.read_bytes() == before


def test_changed_identity_cannot_be_used_to_renew_old_budget(local_root, monkeypatch):
    path, _ = expired_window(local_root, monkeypatch)
    settings = json.loads(path.read_bytes())
    settings["release_commit"] = "b" * 40
    path.write_text(json.dumps(settings))
    with pytest.raises(CheckError, match="MANUAL_BUDGET_CHANGED"):
        renew_window(path, local_root / ".cache" / "copyrit")


async def test_fixed_batch_rejects_insufficient_budget_before_sending(
    local_root, local_memory, tmp_path
):
    catalog = load_catalog(local_root)
    register_local_components(catalog)
    group = next(
        g for g in catalog.groups(catalog.fixed_name)
        if g.objective.metadata["repetitions"] == 3
    )
    fixture = FixtureApp()
    target, _ = make_target(tmp_path, fixture, requests=1)
    scenario = BCGovFixed()
    scenario.set_params_from_args(args={
        "objective_target": target, "max_concurrency": 1, "max_retries": 0,
        "dataset_config": DatasetAttackConfiguration(seed_groups=[group], max_total=1),
    })
    with pytest.raises(CheckError, match="INSUFFICIENT_APP_BUDGET"):
        await scenario.initialize_async()
    assert not fixture.sent
