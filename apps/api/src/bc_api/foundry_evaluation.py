"""Approved synthetic application checks and independent Foundry quality evaluations."""

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from azure.ai.projects import AIProjectClient
from azure.core.exceptions import AzureError
from azure.identity import AzureCliCredential
from openai import OpenAIError

from bc_api.config import Settings, default_catalog_path
from bc_api.foundry import configure_safe_logging
from bc_api.models import JOURNEY_IDS

ROOT = default_catalog_path().parent.parent
POLICY_PATH = ROOT / "data" / "evaluations" / "foundry-release-policy.json"
CANDIDATE_KEYS = (
    "FOUNDRY_PROJECT_ENDPOINT",
    "FOUNDRY_AGENTS",
    "FOUNDRY_GENERAL_AGENT",
    "FOUNDRY_CONVERSATION_AGENT",
    "AI_CONVERSATION_ENABLED",
    "TASK_ASSISTANCE_ENABLED",
    "AI_CONVERSATION_PRIVACY_REVIEWED",
    "GROUNDED_CONVERSATION_ENABLED",
    "LOCAL_EVIDENCE_EVALUATION_ENABLED",
    "AZURE_SEARCH_ENDPOINT",
    "AZURE_SEARCH_INDEX",
    "AZURE_SEARCH_METADATA_ENABLED",
    "AZURE_SEARCH_METADATA_REVIEWED",
    "AZURE_SEARCH_METADATA_INDEX",
    "AZURE_SEARCH_SEMANTIC_CONFIG",
    "AZURE_SEARCH_VECTOR_ENABLED",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
    "AZURE_OPENAI_EMBEDDING_DIMENSIONS",
    "API_MODEL_CALLS_PER_RUN",
    "API_MODEL_INPUT_BYTE_BUDGET",
    "API_MODEL_OUTPUT_TOKENS",
    "API_TOOL_OUTPUT_BYTES",
    "API_RUN_TIMEOUT_SECONDS",
    "API_UPSTREAM_TIMEOUT_SECONDS",
    "SEARCH_MAX_AGE_DAYS",
    "CONVERSATION_CONTEXT_TTL_SECONDS",
)


class EvaluationFailure(RuntimeError):
    """A fixed diagnostic code, never a provider message or conversation."""


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_policy() -> dict:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if (
        not isinstance(policy, dict)
        or type(policy.get("schemaVersion")) is not int
        or policy["schemaVersion"] != 1
        or policy.get("origin") != "independently-authored-public-questions"
        or not isinstance(policy.get("rubric"), str)
        or not policy["rubric"].strip()
        or not isinstance(policy.get("cases"), list)
        or not policy["cases"]
        or not isinstance(policy.get("thresholds"), dict)
        or set(policy["thresholds"]) != {"relevance", "task_outcome"}
    ):
        raise EvaluationFailure("invalid_policy")
    for threshold in policy["thresholds"].values():
        if (
            type(threshold) not in (int, float)
            or not math.isfinite(threshold)
            or not 1 <= threshold <= 5
        ):
            raise EvaluationFailure("invalid_threshold")
    ids = set()
    total = 0
    for case in policy["cases"]:
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("id"), str)
            or not re.fullmatch(r"[a-z]+(?:-[a-z]+)*", case["id"])
            or case["id"] in ids
            or not isinstance(case.get("turns"), list)
            or not case["turns"]
        ):
            raise EvaluationFailure("invalid_cases")
        ids.add(case["id"])
        total += len(case["turns"])
        for turn in case["turns"]:
            if not isinstance(turn, dict) or any(
                not isinstance(turn.get(key), str) or not 1 <= len(turn[key].strip()) <= 4000
                for key in ("query", "expectedBehavior")
            ):
                raise EvaluationFailure("invalid_turn")
    if not 1 <= total <= 18:
        raise EvaluationFailure("turn_budget_exceeded")
    return policy


def validate_rows(payload: dict, policy: dict) -> list[dict]:
    if (
        not isinstance(payload, dict)
        or type(payload.get("schemaVersion")) is not int
        or payload["schemaVersion"] != 1
        or payload.get("origin") != policy["origin"]
        or payload.get("deterministicPassed") is not True
        or not isinstance(payload.get("rows"), list)
    ):
        raise EvaluationFailure("invalid_synthetic_capture")
    rows = payload["rows"]
    expected_count = sum(len(case["turns"]) for case in policy["cases"])
    if len(rows) != expected_count:
        raise EvaluationFailure("incomplete_synthetic_capture")
    by_id = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"id", "query", "response", "expected_behavior"}
            or any(not isinstance(value, str) or not value.strip() for value in row.values())
            or len(row["response"]) > 16000
            or len(row["query"]) > 64000
            or row["id"] in by_id
        ):
            raise EvaluationFailure("invalid_synthetic_row")
        by_id[row["id"]] = row
    expected_ids = set()
    for case in policy["cases"]:
        history = []
        for number, expected in enumerate(case["turns"], 1):
            identifier = f"{case['id']}:{number}"
            expected_ids.add(identifier)
            row = by_id.get(identifier)
            history.append({"role": "user", "content": expected["query"]})
            if (
                row is None
                or row["expected_behavior"] != expected["expectedBehavior"]
                or json.loads(row["query"]) != history
            ):
                raise EvaluationFailure("capture_does_not_match_reviewed_queries")
            history.append({"role": "assistant", "content": row["response"]})
    if set(by_id) != expected_ids:
        raise EvaluationFailure("unexpected_synthetic_rows")
    return rows


def read_candidate(resource_group: str, app_name: str, subscription: str) -> dict[str, str]:
    if not re.fullmatch(r"[a-zA-Z0-9._()-]{1,90}", resource_group) or not re.fullmatch(
        r"[a-z][a-z0-9-]{0,31}", app_name
    ):
        raise EvaluationFailure("invalid_candidate_target")
    executable = shutil.which("az")
    if not executable:
        raise EvaluationFailure("azure_cli_unavailable")
    names = " || ".join(f"name=='{name}'" for name in CANDIDATE_KEYS)
    query = (
        "{containerCount:length(properties.template.containers),"
        f"env:properties.template.containers[0].env[?{names}]"
        ".{name:name,value:value,secretRef:secretRef}}"
    )
    result = subprocess.run(
        [
            executable,
            "containerapp",
            "show",
            "--resource-group",
            resource_group,
            "--name",
            app_name,
            "--subscription",
            subscription,
            "--query",
            query,
            "--output",
            "json",
            "--only-show-errors",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    document = json.loads(result.stdout)
    if (
        not isinstance(document, dict)
        or document.get("containerCount") != 1
        or not isinstance(document.get("env"), list)
    ):
        raise EvaluationFailure("ambiguous_candidate_container")
    values = {}
    for item in document["env"]:
        if (
            not isinstance(item, dict)
            or item.get("name") not in CANDIDATE_KEYS
            or item["name"] in values
            or not isinstance(item.get("value"), str)
            or item.get("secretRef")
        ):
            raise EvaluationFailure("invalid_candidate_configuration")
        values[item["name"]] = item["value"]
    return values


def candidate_environment(
    values: dict[str, str], subscription: str, port: int, parent: dict[str, str]
) -> dict[str, str]:
    required = (
        "FOUNDRY_PROJECT_ENDPOINT",
        "FOUNDRY_AGENTS",
        "FOUNDRY_GENERAL_AGENT",
        "FOUNDRY_CONVERSATION_AGENT",
        "AZURE_SEARCH_ENDPOINT",
        "AZURE_SEARCH_INDEX",
        "AI_CONVERSATION_ENABLED",
        "TASK_ASSISTANCE_ENABLED",
        "AI_CONVERSATION_PRIVACY_REVIEWED",
    )
    if any(not values.get(key) for key in required):
        raise EvaluationFailure("missing_candidate_configuration")
    overrides = {
        **{key.lower(): value for key, value in values.items() if value},
        "app_env": "development",
        "api_allowed_hosts": "127.0.0.1",
        "api_allowed_origins": f"http://127.0.0.1:{port}",
        "content_catalog_path": default_catalog_path(),
        "azure_cli_subscription": subscription,
        "api_max_concurrent_runs": 1,
    }
    for key in ("foundry_agents", "foundry_general_agent", "foundry_conversation_agent"):
        overrides[key] = json.loads(overrides[key])
    defaults = {
        name: field.get_default(call_default_factory=True)
        for name, field in Settings.model_fields.items()
    }
    # Explicit defaults prevent a developer's ambient experiments or telemetry
    # settings from entering the isolated, synthetic baseline.
    settings = Settings(**(defaults | overrides))
    if (
        not settings.foundry_configured
        or not settings.general_agent_configured
        or not settings.conversation_agent_configured
        or not settings.task_assistance_enabled
        or not settings.ai_conversation_privacy_reviewed
        or {binding.journey_id for binding in settings.foundry_agents} != JOURNEY_IDS
        or settings.grounded_conversation_enabled
        or settings.local_evidence_evaluation_enabled
        or not settings.hybrid_configured
    ):
        raise EvaluationFailure("unsupported_candidate_profile")
    application_keys = {name.upper() for name in Settings.model_fields} | {
        "SOURCE_CATALOG_PATH",
        "CONTENT_CATALOG_PATH",
    }
    environment = {
        key: value
        for key, value in parent.items()
        if key.upper() not in application_keys and not key.upper().startswith("OTEL_")
    }
    environment.update(values)
    environment.update(
        {
            "APP_ENV": "development",
            "API_ALLOWED_HOSTS": "127.0.0.1",
            "API_ALLOWED_ORIGINS": f"http://127.0.0.1:{port}",
            "CONTENT_CATALOG_PATH": str(default_catalog_path()),
            "AZURE_CLI_SUBSCRIPTION": subscription,
            "API_MAX_CONCURRENT_RUNS": "1",
            "PYTHONPATH": str(ROOT / "apps" / "api" / "src"),
        }
    )
    return environment


def verify_revision(expected: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{40}", expected):
        raise EvaluationFailure("invalid_candidate_sha")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    ).stdout.strip()
    changes = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    ).stdout.strip()
    if head != expected or changes:
        raise EvaluationFailure("candidate_checkout_mismatch")


def collect_candidate(values: dict[str, str], subscription: str, policy: dict) -> list[dict]:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    environment = candidate_environment(values, subscription, port, dict(os.environ))
    origin = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="bc-foundry-eval-") as directory:
        capture = Path(directory) / "synthetic.json"
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "bc_api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--workers",
                "1",
                "--no-access-log",
            ],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 90
            with httpx.Client(timeout=2, trust_env=False, follow_redirects=False) as client:
                while True:
                    if process.poll() is not None:
                        raise EvaluationFailure("candidate_start_failed")
                    try:
                        response = client.get(f"{origin}/healthz")
                        if response.status_code == 200 and response.json() == {"status": "ok"}:
                            break
                    except httpx.TransportError:
                        pass
                    if time.monotonic() >= deadline:
                        raise EvaluationFailure("candidate_start_timed_out")
                    time.sleep(0.5)
            subprocess.run(
                [
                    "node",
                    str(ROOT / "scripts" / "collect-foundry-evaluation.mjs"),
                    "--url",
                    origin,
                    "--output",
                    str(capture),
                    "--approved",
                ],
                cwd=ROOT,
                check=True,
                timeout=900,
            )
            if capture.stat().st_size > 1024 * 1024:
                raise EvaluationFailure("capture_budget_exceeded")
            return validate_rows(json.loads(capture.read_text(encoding="utf-8")), policy)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def evaluation_definition(policy: dict, model: str) -> dict:
    return {
        "name": "BC Gov App - Foundry Evals (Relevance & Task Outcomes)",
        "data_source_config": {
            "type": "custom",
            "item_schema": {
                "type": "object",
                "properties": {
                    key: {"type": "string"}
                    for key in ("id", "query", "response", "expected_behavior")
                },
                "required": ["id", "query", "response", "expected_behavior"],
                "additionalProperties": False,
            },
        },
        "testing_criteria": [
            {
                "type": "azure_ai_evaluator",
                "name": "relevance",
                "evaluator_name": "builtin.relevance",
                "initialization_parameters": {"model": model},
                "data_mapping": {"query": "{{item.query}}", "response": "{{item.response}}"},
            },
            {
                "type": "score_model",
                "name": "task_outcome",
                "model": model,
                "range": [1, 5],
                "pass_threshold": policy["thresholds"]["task_outcome"],
                "input": [
                    {"role": "system", "content": policy["rubric"]},
                    {
                        "role": "user",
                        "content": "Conversation through the latest user turn:\n{{item.query}}\n"
                        "Latest assistant response:\n{{item.response}}\n"
                        "Expected behaviour:\n{{item.expected_behavior}}",
                    },
                ],
            },
        ],
    }


def score_results(run: dict, items: list[dict], rows: list[dict], thresholds: dict) -> list[dict]:
    counts = run.get("result_counts")
    if (
        run.get("status") != "completed"
        or not isinstance(counts, dict)
        or any(
            type(counts.get(key)) is not int or counts[key] < 0
            for key in ("total", "passed", "failed", "errored")
        )
        or counts["total"] != len(rows)
        or counts["passed"] + counts["failed"] + counts["errored"] != len(rows)
        or counts["errored"] != 0
        or len(items) != len(rows)
    ):
        raise EvaluationFailure("incomplete_cloud_results")
    expected = {row["id"]: row for row in rows}
    seen = set()
    scores = []
    for item in items:
        source = item.get("datasource_item")
        identifier = source.get("id") if isinstance(source, dict) else None
        if (
            not isinstance(identifier, str)
            or identifier not in expected
            or identifier in seen
            or source != expected[identifier]
            or item.get("eval_id") != run.get("eval_id")
            or item.get("run_id") != run.get("id")
            or item.get("status") not in ("pass", "fail")
            or not isinstance(item.get("results"), list)
        ):
            raise EvaluationFailure("invalid_cloud_item")
        seen.add(identifier)
        metrics = {}
        passed = item["status"] == "pass"
        for result in item["results"]:
            if not isinstance(result, dict):
                raise EvaluationFailure("invalid_grader_result")
            name, score = result.get("name"), result.get("score")
            if (
                not isinstance(name, str)
                or name not in thresholds
                or name in metrics
                or type(score) not in (int, float)
                or not math.isfinite(score)
                or not 1 <= score <= 5
                or type(result.get("passed")) is not bool
                or result.get("error")
            ):
                raise EvaluationFailure("invalid_grader_result")
            metrics[name] = score
            passed = passed and result["passed"] and score >= thresholds[name]
        if set(metrics) != set(thresholds):
            raise EvaluationFailure("missing_grader_result")
        scores.append({"id": identifier, "passed": passed, "scores": metrics})
    if sum(item["status"] == "pass" for item in items) != counts["passed"]:
        raise EvaluationFailure("inconsistent_cloud_counts")
    return scores


def report_url(value: object) -> str | None:
    if not isinstance(value, str) or re.search(r"[\s<>]", value):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme == "https"
        and parsed.hostname in ("ai.azure.com", "ai.azure.us")
        and not parsed.username
        and not parsed.password
        and port in (None, 443)
    ):
        return value
    return None


def cloud_identifier(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,160}", value):
        raise EvaluationFailure("invalid_cloud_identifier")
    return value


def run_cloud(client, rows: list[dict], policy: dict, model: str, report: dict, persist) -> None:
    evaluation = client.evals.create(
        **evaluation_definition(policy, model),
        metadata={
            "candidate_sha": report["candidateSha"],
            "policy_sha256": report["policySha256"],
            "configuration_sha256": report["candidateConfigSha256"],
        },
    )
    evaluation_id = cloud_identifier(getattr(evaluation, "id", None))
    report["evalId"] = evaluation_id
    report["submission"] = "not-confirmed"
    persist()
    run = client.evals.runs.create(
        eval_id=evaluation_id,
        name=f"release-{report['candidateSha'][:12]}",
        data_source={
            "type": "jsonl",
            "source": {"type": "file_content", "content": [{"item": row} for row in rows]},
        },
    )
    run_id = cloud_identifier(getattr(run, "id", None))
    report["runId"] = run_id
    report["submission"] = "confirmed"
    terminal = False
    try:
        persist()
        deadline = time.monotonic() + 600
        while True:
            run = client.evals.runs.retrieve(run_id=run_id, eval_id=evaluation_id)
            run_data = run.model_dump()
            if run_data.get("id") != run_id or run_data.get("eval_id") != evaluation_id:
                raise EvaluationFailure("cloud_run_identity_changed")
            status = run_data.get("status")
            if status not in (
                "queued",
                "in_progress",
                "completed",
                "failed",
                "canceled",
                "cancelled",
            ):
                raise EvaluationFailure("unknown_cloud_status")
            report["cloudStatus"] = status
            terminal = status in ("completed", "failed", "canceled", "cancelled")
            link = report_url(run_data.get("report_url"))
            if link:
                report["reportUrl"] = link
            if terminal:
                break
            if time.monotonic() >= deadline:
                raise EvaluationFailure("cloud_evaluation_timed_out")
            time.sleep(5)
        if status != "completed":
            raise EvaluationFailure("cloud_evaluation_unsuccessful")
        items = []
        for item in client.evals.runs.output_items.list(run_id=run_id, eval_id=evaluation_id):
            items.append(item.model_dump())
            if len(items) > len(rows):
                raise EvaluationFailure("unexpected_cloud_items")
        report["results"] = score_results(run_data, items, rows, policy["thresholds"])
        if not all(item["passed"] for item in report["results"]):
            raise EvaluationFailure("quality_threshold_failed")
    finally:
        if not terminal:
            try:
                client.evals.runs.cancel(run_id=run_id, eval_id=evaluation_id)
                report["cancellation"] = "requested"
            except OpenAIError, AzureError, httpx.HTTPError:
                report["cancellation"] = "unconfirmed"
                raise EvaluationFailure("cloud_cancellation_unconfirmed") from None
        persist()


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_summary(report: dict) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    lines = [
        "## BC Gov App - Foundry Evals (Relevance & Task Outcomes)",
        "",
        f"**{'PASS' if report['passed'] else 'FAIL'}**",
        "Evaluation only. BC Gov App deployment is a separate workflow "
        "and is not blocked by this result.",
        f"Candidate: `{report.get('candidateSha', 'not resolved')}`",
        f"Phase: `{report['phase']}`",
        "Every synthetic turn must pass relevance and task outcome; scores are not legal review.",
    ]
    if report.get("code"):
        lines.append(f"Failure: `{report['code']}`")
    if report.get("evalId"):
        lines.append(
            f"Foundry evaluation: `{report['evalId']}` / `{report.get('runId', 'not created')}`"
        )
    if report.get("reportUrl"):
        lines.append(f"[Open the Foundry report](<{report['reportUrl']}>)")
    if report.get("cancellation"):
        lines.append(
            f"Remote cancellation: **{report['cancellation']}**. Confirm status in Foundry."
        )
    if report.get("results"):
        lines.extend(["", "| Turn | Relevance | Task outcome | Passed |", "|---|---:|---:|---|"])
        for item in report["results"]:
            lines.append(
                f"| {item['id']} | {item['scores']['relevance']} | "
                f"{item['scores']['task_outcome']} | {item['passed']} |"
            )
    with Path(summary).open("a", encoding="utf-8") as output:
        output.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approved", action="store_true")
    parser.add_argument("--storage-approved", action="store_true")
    parser.add_argument("--resource-group")
    parser.add_argument("--app-name")
    parser.add_argument("--subscription", default=os.environ.get("AZURE_SUBSCRIPTION_ID"))
    parser.add_argument("--candidate-sha", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument(
        "--model-deployment", default=os.environ.get("FOUNDRY_EVALUATION_MODEL_DEPLOYMENT")
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "test-results" / "foundry-evaluation.json"
    )
    args = parser.parse_args()
    configure_safe_logging()
    report = {"schemaVersion": 1, "passed": False, "phase": "configuration"}
    try:
        policy = load_policy()
        count = sum(len(case["turns"]) for case in policy["cases"])
        if not args.execute:
            print(
                json.dumps(
                    {
                        "mode": "review-only",
                        "networkRequests": 0,
                        "syntheticTurns": count,
                        "judgeScores": count * len(policy["thresholds"]),
                        "thresholds": policy["thresholds"],
                        "policySha256": digest(policy),
                    }
                )
            )
            return 0
        if not args.approved or not args.storage_approved:
            raise EvaluationFailure("live_and_cloud_storage_approval_required")
        if (
            not args.resource_group
            or not args.app_name
            or not args.candidate_sha
            or not args.subscription
            or not re.fullmatch(r"[a-fA-F0-9-]{36}", args.subscription)
            or not args.model_deployment
            or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", args.model_deployment)
        ):
            raise EvaluationFailure("missing_execution_configuration")
        verify_revision(args.candidate_sha)
        report.update(
            {
                "candidateSha": args.candidate_sha,
                "policySha256": digest(policy),
                "catalogSha256": hashlib.sha256(default_catalog_path().read_bytes()).hexdigest(),
                "judgeDeployment": args.model_deployment,
                "thresholds": policy["thresholds"],
                "plannedSyntheticTurns": count,
                "plannedJudgeScores": count * 2,
                "phase": "candidate-configuration",
            }
        )
        values = read_candidate(args.resource_group, args.app_name, args.subscription)
        report["candidateConfigSha256"] = digest(values)
        report["phase"] = "application-checks"
        write_report(args.output, report)
        rows = collect_candidate(values, args.subscription, policy)
        report["deterministicPassed"] = True
        report["phase"] = "foundry-judges"
        with (
            AzureCliCredential(process_timeout=15, subscription=args.subscription) as credential,
            AIProjectClient(
                endpoint=values["FOUNDRY_PROJECT_ENDPOINT"],
                credential=credential,
                retry_total=0,
                logging_enable=False,
            ) as project,
            project.get_openai_client() as base_client,
        ):
            run_cloud(
                base_client.with_options(timeout=30, max_retries=0),
                rows,
                policy,
                args.model_deployment,
                report,
                lambda: write_report(args.output, report),
            )
        report["phase"] = "candidate-recheck"
        verify_revision(args.candidate_sha)
        if read_candidate(args.resource_group, args.app_name, args.subscription) != values:
            raise EvaluationFailure("candidate_configuration_changed")
        report.update(passed=True, phase="completed")
        return 0
    except EvaluationFailure as error:
        report["code"] = str(error)
        return 1
    except KeyboardInterrupt:
        report["code"] = "interrupted"
        return 1
    except (
        AzureError,
        OpenAIError,
        httpx.HTTPError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ):
        report["code"] = "evaluation_operation_failed"
        return 1
    finally:
        if args.execute:
            write_report(args.output, report)
            write_summary(report)
            print(json.dumps(report, allow_nan=False))
        elif "code" in report:
            print(json.dumps(report), file=sys.stderr)


if __name__ == "__main__":

    def interrupt(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    raise SystemExit(main())
