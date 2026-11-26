"""Threat-level entry points for local checks and GitHub Actions."""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from pydantic import ValidationError

from bc_pyrit.contracts import (
    APPROACHES,
    THREATS,
    CheckError,
    Identity,
    Limits,
    ModelLimit,
    digest,
    exact_origin,
    load_dataset,
)
from bc_pyrit.ledger import Ledger
from bc_pyrit.reports import require_complete

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DATASET = ROOT / "data" / "evaluations" / "pyrit-conversation-cases.json"


def read_json(path: Path, maximum: int = 1_000_000) -> dict:
    if path.stat().st_size > maximum:
        raise CheckError("INPUT_TOO_LARGE")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise CheckError("INVALID_INPUT")
    return value


def environment_json(name: str) -> dict:
    value = os.environ.get(name, "")
    if not value:
        raise CheckError(name + "_REQUIRED")
    if len(value.encode()) > 32768:
        raise CheckError("CONFIGURATION_TOO_LARGE")
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise CheckError("INVALID_CONFIGURATION")
    return parsed


def offline_limits(dataset) -> Limits:
    estimate = dataset.estimate("offline")

    def model(role):
        calls = max(estimate[role], 1)
        return ModelLimit(
            calls=calls,
            tokens=calls * (32768 + 1024 + 256),
            cost_microusd=0,
            input_bytes=32768,
            output_tokens=1024,
            token_price_microusd=0,
        )

    return Limits(
        app=estimate["app"], wall_seconds=1800, attacker=model("attacker"), judge=model("judge")
    )


def initialize(args) -> Ledger:
    dataset = load_dataset(args.dataset)
    origin = exact_origin(args.target, local=args.profile == "offline")
    candidate_hash = None
    evaluator_hash = None
    deployment_id = None
    if args.profile == "live":
        from bc_pyrit.targets import Models

        if os.environ.get("PYRIT_LIVE_APPROVED") != "1" or args.candidate is None:
            raise CheckError("LIVE_APPROVAL_REQUIRED")
        if origin != os.environ.get("PYRIT_ALLOWED_ORIGIN"):
            raise CheckError("UNAPPROVED_ORIGIN")
        if not origin.startswith("https://"):
            raise CheckError("LIVE_HTTPS_REQUIRED")
        candidate = read_json(args.candidate)
        expected = {
            "version": 1,
            "kind": "bc-pyrit-candidate",
            "repository": args.repository,
            "commit": args.commit,
            "runId": args.run_id,
            "runAttempt": args.run_attempt,
            "stagingOrigin": origin,
        }
        if any(candidate.get(key) != value for key, value in expected.items()):
            raise CheckError("CANDIDATE_IDENTITY_MISMATCH")
        age = (
            datetime.now(UTC).timestamp()
            - datetime.fromisoformat(candidate["createdAt"]).timestamp()
        )
        if not -30 <= age <= 3600:
            raise CheckError("STALE_CANDIDATE")
        if candidate.get("productionOrigin") == origin:
            raise CheckError("STAGING_MUST_BE_SEPARATE")
        limits = Limits.model_validate(environment_json("PYRIT_LIMITS_JSON"))
        models = Models.model_validate(environment_json("PYRIT_MODELS_JSON"))
        if (
            candidate.get("suiteSha256")
            != digest(dataset.model_dump(mode="json", exclude_unset=True))
            or candidate.get("limitsSha256") != digest(limits.model_dump(mode="json"))
            or candidate.get("evaluatorSha256") != digest(models.model_dump(mode="json"))
        ):
            raise CheckError("EVALUATION_CONFIGURATION_CHANGED")
        candidate_hash = digest(candidate)
        evaluator_hash = digest(models.model_dump(mode="json"))
        deployment_id = candidate["stagingRevisions"]["api"].rsplit("--", 1)[1]
        if candidate["stagingRevisions"]["web"].rsplit("--", 1)[1] != deployment_id:
            raise CheckError("STAGING_PAIR_MISMATCH")
    else:
        limits = offline_limits(dataset)
    identity = Identity(
        repository=args.repository,
        commit=args.commit,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        target=origin,
        candidate_sha256=candidate_hash,
    )
    return Ledger.initialize(
        args.state,
        dataset,
        args.profile,
        limits,
        identity.model_dump(mode="json", by_alias=True),
        evaluator_sha256=evaluator_hash,
        deployment_id=deployment_id,
    )


def summary(report: dict) -> str:
    rows = []
    for threat, label in THREATS.items():
        results = [item for item in report["results"] if item["threat"] == threat]
        if not results:
            rows.append(f"| {label} | Offline fixture check required | Not applicable live |")
            continue
        for approach in sorted({item["approach"] for item in results}):
            selected = [item for item in results if item["approach"] == approach]
            counts = {
                status: sum(item["status"] == status for item in selected)
                for status in (
                    "pass",
                    "fail",
                    "needs-review",
                    "incomplete",
                )
            }
            text = ", ".join(f"{count} {status}" for status, count in counts.items() if count)
            rows.append(f"| {label} | {approach} | {text} |")
    text = [
        "# PyRIT - AI red teaming",
        "",
        f"Profile: {report['profile']}. Result: {report['status']}.",
        f"Completed cases: {report['completedCases']}/{report['expectedCases']}.",
        "",
        "| Threat | Approach | Results |",
        "|---|---|---|",
        *rows,
        "",
    ]
    if report["profile"] == "offline":
        text.append(
            "Fixture inference checks application and harness contracts. "
            "It is not a live safety assessment."
        )
    elif os.environ.get("GITHUB_SERVER_URL") and os.environ.get("GITHUB_REPOSITORY"):
        workflow = (
            os.environ["GITHUB_SERVER_URL"].rstrip("/")
            + "/"
            + os.environ["GITHUB_REPOSITORY"]
            + "/actions/workflows/ci-pyrit.yml"
        )
        text.append(
            f"Indirect injection and exhaustion faults run in [offline CI]({workflow}). "
            "Promotion also requires matching offline evidence."
        )
    if report["stopCode"]:
        text.append(f"Stopped: `{report['stopCode']}`.")
    failures = [item for item in report["results"] if item["status"] != "pass"]
    if failures:
        text += ["", "| Case / variant / attempt | Result | Reason |", "|---|---|---|"]
        text += [f"| `{item['id']}` | {item['status']} | `{item['code']}` |" for item in failures]
    return "\n".join(text) + "\n"


async def run_group(args) -> int:
    from azure.identity.aio import AzureCliCredential, get_bearer_token_provider
    from pyrit.memory import CentralMemory
    from pyrit.setup import IN_MEMORY, initialize_pyrit_async

    from bc_pyrit.client import AppClient
    from bc_pyrit.execution import execute_group
    from bc_pyrit.targets import Models

    logger = logging.getLogger("pyrit")
    logger.setLevel(logging.CRITICAL + 1)
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    ledger = Ledger(args.state)
    state = ledger.state()
    identity = Identity.model_validate(state["identity"])
    dataset = load_dataset(args.dataset)
    offline = state["profile"] == "offline"
    models = None
    credential = None
    provider = None
    if not offline:
        if os.environ.get("PYRIT_LIVE_APPROVED") != "1":
            raise CheckError("LIVE_APPROVAL_REQUIRED")
        if identity.target != os.environ.get("PYRIT_ALLOWED_ORIGIN"):
            raise CheckError("UNAPPROVED_ORIGIN")
        models = Models.model_validate(environment_json("PYRIT_MODELS_JSON"))
        if digest(models.model_dump(mode="json")) != state["evaluator"]:
            raise CheckError("EVALUATOR_CHANGED")
        if (
            Limits.model_validate(environment_json("PYRIT_LIMITS_JSON")).model_dump()
            != state["limits"]
        ):
            raise CheckError("BUDGET_CHANGED")
        credential = AzureCliCredential(process_timeout=15)
        provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
    app = AppClient(
        identity.target,
        ledger,
        offline=offline,
        expected_commit=None if offline else identity.commit,
        expected_deployment=state["deployment"],
    )
    await initialize_pyrit_async(
        memory_db_type=IN_MEMORY, env_files=[], initializers=[], load_defaults=False, silent=True
    )
    results = []
    try:
        ledger.remaining_seconds()
        await app.preflight()
        groups = list(THREATS) if args.threat == "all" else [args.threat]
        for threat in groups:
            if not any(case.threat == threat for case in dataset.for_profile(state["profile"])):
                if args.threat == "all":
                    continue
                raise CheckError("THREAT_NOT_APPLICABLE")
            results.extend(
                await execute_group(
                    ledger=ledger,
                    dataset=dataset,
                    app=app,
                    threat=threat,
                    approach=args.approach,
                    models=models,
                    token_provider=provider,
                    api_python=os.environ.get("PYRIT_API_PYTHON", ""),
                )
            )
    except CheckError as error:
        ledger.stop(error.code)
        raise
    finally:
        await CentralMemory.get_memory_instance().dispose_engine_async()
        if credential:
            await credential.close()
    for result in results:
        print(result.model_dump_json())
    return int(any(item.status != "pass" for item in results))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Bounded BC assistant red-teaming checks.")
    root.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    commands = root.add_subparsers(dest="command", required=True)
    estimate = commands.add_parser("estimate")
    estimate.add_argument("--profile", choices=["offline", "live"], default="live")
    init = commands.add_parser("init")
    init.add_argument("--profile", choices=["offline", "live"], required=True)
    init.add_argument("--target", required=True)
    init.add_argument("--state", type=Path, required=True)
    init.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", "local/local"))
    init.add_argument("--commit", required=True)
    init.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", "local"))
    init.add_argument(
        "--run-attempt", type=int, default=int(os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
    )
    init.add_argument("--candidate", type=Path)
    run = commands.add_parser("run")
    run.add_argument("--state", type=Path, required=True)
    run.add_argument("--threat", choices=[*THREATS, "all"], required=True)
    run.add_argument("--approach", choices=sorted(APPROACHES))
    stop = commands.add_parser("stop")
    stop.add_argument("--state", type=Path, required=True)
    stop.add_argument(
        "--code",
        choices=["CANDIDATE_IDENTITY_NOT_VERIFIED", "SETUP_FAILED", "CANCELLED"],
        required=True,
    )
    report = commands.add_parser("report")
    report.add_argument("--state", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    report.add_argument("--summary", type=Path)
    report.add_argument("--require-pass", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if version("pyrit") != "1.2.0":
            raise CheckError("UNSUPPORTED_PYRIT_VERSION")
        if args.command == "estimate":
            dataset = load_dataset(args.dataset)
            print(
                json.dumps(
                    {
                        "profile": args.profile,
                        "attempts": len(dataset.expected(args.profile)),
                        "maximumCalls": dataset.estimate(args.profile),
                    }
                )
            )
            return 0
        if args.command == "init":
            ledger = initialize(args)
            print(
                json.dumps({"initialized": True, "expectedCases": ledger.report()["expectedCases"]})
            )
            return 0
        if args.command == "run":
            return asyncio.run(run_group(args))
        if not args.state.is_file():
            raise CheckError("RUN_NOT_INITIALIZED")
        if args.command == "stop":
            Ledger(args.state).stop(args.code)
            return 0
        report = Ledger(args.state).report()
        complete = True
        try:
            require_complete(report, load_dataset(args.dataset))
        except CheckError as error:
            complete = False
            if report["status"] == "pass":
                report["status"] = "incomplete"
                report["stopCode"] = error.code
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        rendered = summary(report)
        if args.summary:
            with args.summary.open("a", encoding="utf-8") as output:
                output.write(rendered)
        print(rendered)
        return int(args.require_pass and not complete)
    except CheckError as error:
        print(json.dumps({"status": "incomplete", "code": error.code}), file=sys.stderr)
        return 2
    except (ValidationError, ValueError, OSError, KeyError) as error:
        print(
            json.dumps(
                {
                    "status": "incomplete",
                    "code": "INVALID_CONFIGURATION",
                    "errorType": type(error).__name__,
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
