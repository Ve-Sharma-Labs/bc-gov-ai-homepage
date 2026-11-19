"""Prepare/reload CoPyRIT data and report readiness. Never launch an attack."""

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
import uuid
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml
from dotenv import dotenv_values
from pyrit.memory import CentralMemory
from pyrit.registry import TargetRegistry

from bc_pyrit.catalog import ROOT, import_catalog, load_catalog, prepare_sources
from bc_pyrit.contracts import CheckError
from bc_pyrit.local_scenarios import register_local_components
from bc_pyrit.manual import create_manual_target, load_settings


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def runtime_path(root: Path) -> Path:
    return root / ".cache" / "copyrit"


def setup_hash(root: Path) -> str:
    files = sorted((root / "evaluations" / "pyrit" / "src" / "bc_pyrit").glob("*.py"))
    files.extend([
        root / "evaluations" / "pyrit" / "copyrit_local_initializer.py",
        root / "scripts" / "pyrit-local.ps1",
    ])
    return hashlib.sha256(b"".join(path.read_bytes() for path in files)).hexdigest()


def target_config(root: Path) -> Path | None:
    runtime = runtime_path(root)
    for name in ("local-pack.env", ".env.local"):
        env = runtime / name
        if env.is_file():
            path = dotenv_values(env).get("BC_PYRIT_MANUAL_CONFIG")
            if path:
                return Path(path)
    return None


def window_status(path: Path | None) -> dict:
    if path is None:
        return {"ready": False, "reason": "TARGET_NOT_CONFIGURED", "renewable": False}
    settings = load_settings(path)
    ledger = path.parent / "manual-budget.sqlite"
    if not ledger.is_file():
        return {
            "ready": True, "reason": None, "renewable": False,
            "requestsLeft": settings.request_limit,
        }
    with sqlite3.connect(ledger.resolve().as_uri() + "?mode=ro", uri=True) as db:
        state = {key: json.loads(value) for key, value in db.execute("SELECT key,value FROM state")}
        used = db.execute("SELECT COUNT(*) FROM charges WHERE role='app'").fetchone()[0]
    if (
        state.get("profile") != "manual" or state["identity"] != settings.identity()
        or state["limits"] != settings.limits().model_dump(mode="json")
    ):
        raise CheckError("MANUAL_BUDGET_CHANGED")
    expires = state["started"] + state["limits"]["wall_seconds"]
    reason = state["stop"]
    if reason is None and (time.time() >= expires or time.time() < state["started"]):
        reason = "WALL_BUDGET_EXHAUSTED"
    if reason is None and used >= settings.request_limit:
        reason = "APP_BUDGET_EXHAUSTED"
    return {
        "ready": reason is None, "reason": reason,
        "renewable": reason in ("WALL_BUDGET_EXHAUSTED", "APP_BUDGET_EXHAUSTED"),
        "requestsLeft": max(0, settings.request_limit - used),
        "expiresAt": datetime.fromtimestamp(expires, UTC).isoformat(),
    }


def renew_window(path: Path, runtime: Path) -> Path:
    status = window_status(path)
    if not status["renewable"]:
        raise CheckError("WINDOW_RENEWAL_NOT_APPLICABLE")
    settings = load_settings(path)
    # New explicitly approved window, never a rewrite/reset of the old ledger.
    config = settings.model_dump(mode="json", exclude_none=True)
    config.update(request_limit=min(settings.request_limit, 20), wall_seconds=3600)
    destination = runtime / f"manual-{uuid.uuid4().hex}" / "target.json"
    atomic_text(destination, json.dumps(config, indent=2) + "\n")
    return destination


def prepare(root: Path, *, port: int, renew: bool = False, browse_only: bool = False) -> dict:
    prepare_sources(root)
    catalog = load_catalog(root)
    runtime = runtime_path(root)
    config = target_config(root)
    if renew:
        if config is None or browse_only:
            raise CheckError("WINDOW_RENEWAL_NOT_APPLICABLE")
        config = renew_window(config, runtime)
    status = window_status(config)
    old_initializer = root / "evaluations" / "pyrit" / "copyrit_initializer.py"
    new_initializer = root / "evaluations" / "pyrit" / "copyrit_local_initializer.py"
    yaml_path = runtime / "copyrit.yaml"
    configuration = yaml.safe_load(yaml_path.read_text()) if yaml_path.is_file() else {}
    if not isinstance(configuration, dict):
        raise CheckError("INVALID_LOCAL_CONFIGURATION")
    scripts = configuration.get("initialization_scripts") or []
    scripts = [p for p in scripts if Path(p).resolve() != old_initializer.resolve()]
    if str(new_initializer) not in scripts:
        scripts.append(str(new_initializer))
    env_path = runtime / "local-pack.env"
    env_files = list(configuration.get("env_files") or [])
    if str(env_path) in env_files:
        env_files.remove(str(env_path))
    env_files.append(str(env_path))
    configuration.update(
        memory_db_type="sqlite", initialization_scripts=scripts, env_files=env_files,
        allow_custom_initializers=False, enable_live_reinitialization=False, silent=True,
    )
    configuration.setdefault("initializers", [{"name": "technique"}])
    configuration.setdefault("server", {})["url"] = f"http://127.0.0.1:{port}"
    if yaml_path.exists():
        backup = runtime / "copyrit.before-local.yaml"
        if not backup.exists():
            backup.write_bytes(yaml_path.read_bytes())
    values = {
        "BC_PYRIT_LOCAL_ROOT": str(root),
        "BC_PYRIT_BROWSE_ONLY": str(browse_only).lower(),
    }
    if config is not None:
        values["BC_PYRIT_MANUAL_CONFIG"] = str(config.resolve())
    if any("\n" in value or "\r" in value for value in values.values()):
        raise CheckError("INVALID_LOCAL_CONFIGURATION")
    atomic_text(env_path, "".join(f"{key}='{value}'\n" for key, value in values.items()))
    atomic_text(yaml_path, yaml.safe_dump(configuration, sort_keys=False))
    return {**catalog.summary(), "window": status, "browseOnly": browse_only}


async def initialize_local(root: Path) -> dict:
    catalog = load_catalog(root)
    report = await import_catalog(CentralMemory.get_memory_instance(), catalog)
    report.update(register_local_components(catalog))
    config = target_config(root)
    report["window"] = window_status(config)
    report["targetReady"] = False
    report["targetReason"] = report["window"]["reason"]
    if os.environ.get("BC_PYRIT_BROWSE_ONLY") == "true":
        report["targetReason"] = "BROWSE_ONLY"
    elif report["window"]["ready"] and config is not None:
        try:
            target = await create_manual_target(config)
        except CheckError as error:
            report["targetReason"] = error.code
        else:
            TargetRegistry.get_registry_singleton().instances.register(
                target, name="bc-gov-staging", replace=False
            )
            report["targetReady"] = True
            report["targetReason"] = None
    if not report["targetReady"]:
        logging.getLogger(__name__).warning(
            "Local data loaded; staging target unavailable: %s", report["targetReason"]
        )
    report.update(
        processId=os.getpid(), preparedAt=datetime.now(UTC).isoformat(),
        setupSha256=setup_hash(root), startId=os.environ.get("BC_PYRIT_START_ID"),
    )
    atomic_text(runtime_path(root) / "local-status.json", json.dumps(report, indent=2) + "\n")
    return report


def check(root: Path, port: int) -> dict:
    path = runtime_path(root) / "local-status.json"
    if not path.is_file():
        raise CheckError("LOCAL_PACK_NOT_PREPARED")
    report = json.loads(path.read_bytes())
    catalog = load_catalog(root)
    if report["packSha256"] != catalog.pack_hash or report["setupSha256"] != setup_hash(root):
        raise CheckError("LOCAL_PACK_CHANGED_RELOAD_REQUIRED")
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=15) as client:
        compat = client.get("/compatibility.json")
        compat.raise_for_status()
        client.headers["PyRIT-Compatibility-ID"] = compat.json()["compatibility_id"]
        response = client.get("/api/health")
        response.raise_for_status()
        if not response.json().get("ready") or response.json().get("state") != "ready":
            raise CheckError("LOCAL_UI_NOT_READY")
        response = client.get("/api/datasets", params={"loaded_only": True})
        response.raise_for_status()
        datasets = {item["name"]: item for item in response.json()["items"]}
        for name, counts in report["datasets"].items():
            if name not in datasets or datasets[name]["seed_pieces"] != counts["pieces"]:
                raise CheckError("DATASET_IMPORT_INCOMPLETE")
        response = client.get("/api/scenario-presets", params={"include_estimates": True})
        response.raise_for_status()
        presets = {item["preset"]["name"]: item for item in response.json()["items"]}
        if not set(report["presets"]) <= presets.keys():
            raise CheckError("PRESET_IMPORT_INCOMPLETE")
        report["presetIssues"] = {
            name: presets[name]["issues"] for name in report["presets"] if presets[name]["issues"]
        }
        response = client.get("/api/converters")
        response.raise_for_status()
        converters = {item["converter_id"]: item for item in response.json()["items"]}
        if any(
            name not in converters or converters[name]["is_llm_based"]
            for name in report["converterNames"]
        ):
            raise CheckError("CONVERTER_IMPORT_INCOMPLETE")
        response = client.get("/api/scorers")
        response.raise_for_status()
        scorers = {item["scorer_registry_name"] for item in response.json()["items"]}
        if report["scorer"] not in scorers:
            raise CheckError("SCORER_IMPORT_INCOMPLETE")
        response = client.get("/api/targets")
        response.raise_for_status()
        if report["targetReady"] and "bc-gov-staging" not in {
            item["target_registry_name"] for item in response.json()["items"]
        }:
            report["targetReady"] = False
            report["targetReason"] = "TARGET_NOT_REGISTERED"
    report["window"] = window_status(target_config(root))
    if not report["window"]["ready"]:
        report["targetReady"] = False
        report["targetReason"] = report["window"]["reason"]
    report["url"] = f"http://127.0.0.1:{port}"
    return report


def print_status(report: dict) -> None:
    counts = report["datasets"]
    total = sum(item["examples"] for item in counts.values())
    print(f"CoPyRIT: {report['url']}")
    print(
        f"Loaded {total} examples/templates in {len(counts)} datasets, "
        f"{report['converters']} converters and {len(report['presets'])} fixed presets."
    )
    if report["targetReady"]:
        print(
            f"BC staging ready: {report['window']['requestsLeft']} requests left; "
            f"window expires {report['window'].get('expiresAt', 'after first initialization')}."
        )
    else:
        print(f"Data browsing ready; staging is unavailable: {report['targetReason']}.")
    if report.get("presetIssues"):
        print("Some presets need review; use npm run pyrit:status -- -Json for details.")
    print("Review required. Adaptive attacks/AI scoring are not configured. Setup ran no attacks.")


def serve(root: Path, *, port: int, no_browser: bool) -> None:
    runtime = runtime_path(root)
    source = runtime / "source"
    environment = dict(os.environ)
    environment.setdefault("AZURE_CONFIG_DIR", str(Path.home() / ".azure"))
    environment.update(
        USERPROFILE=str(runtime / "home"), HOME=str(runtime / "home"),
        PYTHONUTF8="1", PYRIT_AUTH_MODE="local", PYRIT_ALLOW_UNAUTHENTICATED_ADMIN="false",
        PYRIT_DEV_MODE="false", PYRIT_CORS_ORIGINS=f"http://127.0.0.1:{port}",
        OTEL_SDK_DISABLED="true", HF_HUB_DISABLE_TELEMETRY="1",
        BC_PYRIT_START_ID=uuid.uuid4().hex,
    )
    if source.is_dir():
        environment["PYTHONPATH"] = str(source)
    for key in (
        "ENTRA_TENANT_ID", "ENTRA_CLIENT_ID",
        "ENTRA_ALLOWED_GROUP_IDS", "ENTRA_ADMIN_GROUP_ID",
    ):
        environment.pop(key, None)
    (runtime / "home").mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [sys.executable, "-m", "pyrit.backend.pyrit_backend", "--auth-mode", "local",
         "--host", "127.0.0.1", "--port", str(port),
         "--config-file", str(runtime / "copyrit.yaml"), "--log-level", "WARNING"],
        cwd=source if source.is_dir() else runtime, env=environment,
    )
    try:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise CheckError("LOCAL_SERVER_START_FAILED")
            try:
                report = check(root, port)
            except (httpx.HTTPError, CheckError):
                time.sleep(2)
                continue
            if report["startId"] != environment["BC_PYRIT_START_ID"]:
                time.sleep(2)
                continue
            print_status(report)
            sys.stdout.flush()
            if not no_browser:
                webbrowser.open(report["url"])
            process.wait()
            if process.returncode:
                raise CheckError("LOCAL_SERVER_STOPPED_WITH_ERROR")
            return
        raise CheckError("LOCAL_SERVER_START_TIMEOUT")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=20)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("sources", "window", "prepare", "check", "serve"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--renew-window", action="store_true")
    parser.add_argument("--browse-only", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use a non-privileged loopback port.")
    try:
        if args.action == "sources":
            prepare_sources(args.root)
            result = load_catalog(args.root).summary()
        elif args.action == "window":
            result = window_status(target_config(args.root))
        elif args.action == "prepare":
            result = prepare(
                args.root, port=args.port, renew=args.renew_window, browse_only=args.browse_only
            )
        elif args.action == "check":
            result = check(args.root, args.port)
        else:
            serve(args.root, port=args.port, no_browser=args.no_browser)
            return 0
        if args.action == "check" and not args.json:
            print_status(result)
        else:
            print(json.dumps(result, indent=2))
        return 0
    except KeyboardInterrupt:
        print("Owned PyRIT server stopped. Data and limits were preserved.")
        return 0
    except (CheckError, httpx.HTTPError, OSError, ValueError, sqlite3.Error) as error:
        code = error.code if isinstance(error, CheckError) else type(error).__name__
        print(f"PyRIT setup failed: {code}. No attacks were launched.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
