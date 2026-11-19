import copy
import json
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from azure.core.credentials import AccessToken
from openai import OpenAIError

from bc_api import foundry_evaluation as evaluation
from bc_api.models import JOURNEY_IDS

SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"


def captured(policy):
    rows = []
    for case in policy["cases"]:
        history = []
        for number, turn in enumerate(case["turns"], 1):
            history.append({"role": "user", "content": turn["query"]})
            response = f"SYNTHETIC-RESPONSE-{case['id']}-{number}"
            rows.append(
                {
                    "id": f"{case['id']}:{number}",
                    "query": json.dumps(history),
                    "response": response,
                    "expected_behavior": turn["expectedBehavior"],
                }
            )
            history.append({"role": "assistant", "content": response})
    return {
        "schemaVersion": 1,
        "origin": policy["origin"],
        "deterministicPassed": True,
        "rows": rows,
    }


def candidate():
    def binding(name, journey_id=None):
        result = {"name": name, "version": "1", "modelDeployment": "fixture-deployment"}
        if journey_id:
            result["journeyId"] = journey_id
        return result

    return {
        "FOUNDRY_PROJECT_ENDPOINT": "https://fixture.services.ai.azure.com/api/projects/fixture",
        "FOUNDRY_AGENTS": json.dumps([binding(f"agent-{key}", key) for key in sorted(JOURNEY_IDS)]),
        "FOUNDRY_GENERAL_AGENT": json.dumps(binding("general")),
        "FOUNDRY_CONVERSATION_AGENT": json.dumps(binding("planner")),
        "AI_CONVERSATION_ENABLED": "true",
        "TASK_ASSISTANCE_ENABLED": "true",
        "AI_CONVERSATION_PRIVACY_REVIEWED": "true",
        "GROUNDED_CONVERSATION_ENABLED": "false",
        "LOCAL_EVIDENCE_EVALUATION_ENABLED": "false",
        "AZURE_SEARCH_ENDPOINT": "https://fixture.search.windows.net",
        "AZURE_SEARCH_INDEX": "fixture-index",
        "AZURE_OPENAI_EMBEDDING_DIMENSIONS": "",
    }


def cloud_result(rows):
    run = {
        "id": "run_fixture",
        "eval_id": "eval_fixture",
        "status": "completed",
        "report_url": "https://ai.azure.com/build/evaluation/fixture",
        "result_counts": {"total": len(rows), "passed": len(rows), "failed": 0, "errored": 0},
    }
    items = [
        {
            "id": f"output_{index}",
            "created_at": 1,
            "object": "eval.run.output_item",
            "sample": {},
            "eval_id": run["eval_id"],
            "run_id": run["id"],
            "datasource_item_id": index,
            "datasource_item": row,
            "status": "pass",
            "results": [
                {"name": name, "score": 4.0, "passed": True, "reason": "PRIVATE-JUDGE-REASON"}
                for name in ("relevance", "task_outcome")
            ],
        }
        for index, row in enumerate(rows)
    ]
    return run, items


def sdk_object(value):
    return SimpleNamespace(**value, model_dump=lambda: value)


def fake_client(rows, status="completed"):
    run, items = cloud_result(rows)
    run["status"] = status
    runs = SimpleNamespace(
        create=Mock(return_value=sdk_object(run)),
        retrieve=Mock(return_value=sdk_object(run)),
        cancel=Mock(),
        output_items=SimpleNamespace(
            list=Mock(return_value=[sdk_object(item) for item in items]),
        ),
    )
    return SimpleNamespace(
        evals=SimpleNamespace(
            create=Mock(return_value=SimpleNamespace(id=run["eval_id"])),
            runs=runs,
        )
    )


def report_for(policy):
    return {
        "candidateSha": "a" * 40,
        "policySha256": evaluation.digest(policy),
        "candidateConfigSha256": "b" * 64,
        "passed": False,
    }


def test_dry_run_never_constructs_cloud_clients_or_reads_azure(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Review-only mode must not contact Azure or start the application.")

    monkeypatch.setattr(evaluation, "AIProjectClient", forbidden)
    monkeypatch.setattr(evaluation, "read_candidate", forbidden)
    monkeypatch.setattr(evaluation, "collect_candidate", forbidden)
    monkeypatch.setattr(sys, "argv", ["foundry_evaluation"])
    assert evaluation.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["networkRequests"] == 0
    assert result["syntheticTurns"] == 16
    assert result["judgeScores"] == 32


@pytest.mark.parametrize("approvals", [[], ["--approved"], ["--storage-approved"]])
def test_execution_requires_both_approvals_before_any_azure_call(monkeypatch, tmp_path, approvals):
    monkeypatch.setattr(evaluation, "read_candidate", lambda *args: pytest.fail("No approval."))
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "foundry_evaluation",
            "--execute",
            "--output",
            str(output),
            *approvals,
        ],
    )
    assert evaluation.main() == 1
    report = json.loads(output.read_text())
    assert report["passed"] is False
    assert report["code"] == "live_and_cloud_storage_approval_required"


def test_only_complete_reviewed_synthetic_dialogue_can_be_uploaded():
    policy = evaluation.load_policy()
    payload = captured(policy)
    assert len(evaluation.validate_rows(payload, policy)) == 16
    mutations = [
        lambda value: value.update(origin="resident-transcripts"),
        lambda value: value.update(deterministicPassed=False),
        lambda value: value["rows"].pop(),
        lambda value: value["rows"].__setitem__(1, copy.deepcopy(value["rows"][0])),
        lambda value: value["rows"][0].update(response=" "),
        lambda value: value["rows"][0].update(response="x" * 16001),
        lambda value: value["rows"][0].update(expected_behavior="Different rubric"),
        lambda value: value["rows"][1].update(query='[{"role":"user","content":"Yes"}]'),
        lambda value: value["rows"][0].update(cookie="not-allowed"),
    ]
    for mutate in mutations:
        invalid = copy.deepcopy(payload)
        mutate(invalid)
        with pytest.raises(evaluation.EvaluationFailure):
            evaluation.validate_rows(invalid, policy)


def test_candidate_uses_the_deployed_bindings_but_not_ambient_secrets_or_experiments(monkeypatch):
    values = candidate()
    monkeypatch.setenv("WEBIQ_ENABLED", "true")
    environment = evaluation.candidate_environment(
        values,
        SUBSCRIPTION,
        8123,
        {
            "PATH": "fixture-path",
            "REDIS_ENDPOINT": "not-used",
            "API_AUTH_AUDIENCE": "not-used",
            "APPLICATIONINSIGHTS_CONNECTION_STRING": "not-used",
            "API_METRICS_ENABLED": "true",
            "WEBIQ_ENABLED": "true",
            "SYNTHETIC_CONTEXT_ENABLED": "true",
            "LOCAL_EVIDENCE_EVALUATION_ENABLED": "true",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "not-used",
            "SOURCE_CATALOG_PATH": "not-used",
            "FOUNDRY_GENERAL_AGENT": "not-used",
        },
    )
    assert environment["FOUNDRY_GENERAL_AGENT"] == values["FOUNDRY_GENERAL_AGENT"]
    assert environment["FOUNDRY_CONVERSATION_AGENT"] == values["FOUNDRY_CONVERSATION_AGENT"]
    assert environment["AZURE_CLI_SUBSCRIPTION"] == SUBSCRIPTION
    assert environment["APP_ENV"] == "development"
    assert environment["API_ALLOWED_HOSTS"] == "127.0.0.1"
    assert environment["API_ALLOWED_ORIGINS"] == "http://127.0.0.1:8123"
    assert environment["PATH"] == "fixture-path"
    assert "not-used" not in json.dumps(environment)
    assert "WEBIQ_ENABLED" not in environment
    assert "SYNTHETIC_CONTEXT_ENABLED" not in environment


@pytest.mark.parametrize(
    "change",
    [
        {"AI_CONVERSATION_ENABLED": "false"},
        {"TASK_ASSISTANCE_ENABLED": "false"},
        {"AI_CONVERSATION_PRIVACY_REVIEWED": "false"},
        {"GROUNDED_CONVERSATION_ENABLED": "true"},
        {"LOCAL_EVIDENCE_EVALUATION_ENABLED": "true"},
        {"FOUNDRY_AGENTS": "[]"},
        {"FOUNDRY_CONVERSATION_AGENT": ""},
    ],
)
def test_candidate_cannot_silently_change_protocol_or_enable_missing_bindings(change):
    with pytest.raises((evaluation.EvaluationFailure, ValueError)):
        evaluation.candidate_environment(candidate() | change, SUBSCRIPTION, 8123, {})


@pytest.mark.parametrize(
    "head,changes",
    [
        ("b" * 40, ""),
        ("a" * 40, " M apps/api/src/bc_api/foundry.py"),
        ("a" * 40, "?? scripts/unreviewed.mjs"),
    ],
)
def test_revision_gate_rejects_stale_sha_and_uncommitted_candidate(monkeypatch, head, changes):
    monkeypatch.setattr(
        evaluation.subprocess,
        "run",
        Mock(
            side_effect=[
                SimpleNamespace(stdout=head),
                SimpleNamespace(stdout=changes),
            ]
        ),
    )
    with pytest.raises(evaluation.EvaluationFailure, match="candidate_checkout_mismatch"):
        evaluation.verify_revision("a" * 40)


def test_scores_are_per_turn_not_averages_and_never_contain_transcripts_or_judge_reasons():
    policy = evaluation.load_policy()
    rows = captured(policy)["rows"]
    run, items = cloud_result(rows)
    results = evaluation.score_results(run, items, rows, policy["thresholds"])
    assert all(item["passed"] for item in results)
    assert "PRIVATE-JUDGE-REASON" not in json.dumps(results)
    assert "SYNTHETIC-RESPONSE" not in json.dumps(results)
    items[0]["results"][0]["score"] = 3.99
    results = evaluation.score_results(run, items, rows, policy["thresholds"])
    assert results[0]["passed"] is False
    assert all(item["passed"] for item in results[1:])


@pytest.mark.parametrize(
    "mutation",
    [
        lambda run, items: run.update(status="failed"),
        lambda run, items: run["result_counts"].update(total=0),
        lambda run, items: run["result_counts"].update(errored=1, passed=0),
        lambda run, items: items.clear(),
        lambda run, items: items.append(copy.deepcopy(items[0])),
        lambda run, items: items[0].update(status="error"),
        lambda run, items: items[0].update(run_id="another_run"),
        lambda run, items: items[0]["datasource_item"].update(response="not-the-sent-answer"),
        lambda run, items: items[0]["results"].pop(),
        lambda run, items: items[0]["results"].append(copy.deepcopy(items[0]["results"][0])),
        lambda run, items: items[0]["results"][0].update(score=float("nan")),
        lambda run, items: items[0]["results"][0].update(score=True),
        lambda run, items: items[0]["results"][0].update(score=6),
        lambda run, items: items[0]["results"][0].update(passed="true"),
        lambda run, items: items[0]["results"][0].update(error="provider-error"),
    ],
)
def test_missing_malformed_failed_and_misattributed_results_fail_closed(mutation):
    policy = evaluation.load_policy()
    rows = captured(policy)["rows"][:1]
    run, items = cloud_result(copy.deepcopy(rows))
    mutation(run, items)
    with pytest.raises(evaluation.EvaluationFailure):
        evaluation.score_results(run, items, rows, policy["thresholds"])


def test_sdk_serialization_and_paginated_results_use_existing_app_outputs():
    policy = evaluation.load_policy()
    rows = captured(policy)["rows"][:2]
    run, items = cloud_result(rows)
    requests = []

    def transport(request):
        requests.append(request)
        if request.method == "POST" and request.url.path.endswith("/evals"):
            body = json.loads(request.content)
            assert body["data_source_config"]["type"] == "custom"
            assert body["testing_criteria"][0]["evaluator_name"] == "builtin.relevance"
            assert body["testing_criteria"][1]["pass_threshold"] == 4
            return httpx.Response(200, json={"id": run["eval_id"], **body})
        if request.method == "POST" and request.url.path.endswith("/runs"):
            body = json.loads(request.content)
            assert body["data_source"]["type"] == "jsonl"
            assert body["data_source"]["source"]["content"] == [{"item": row} for row in rows]
            assert "target" not in body["data_source"]
            return httpx.Response(200, json=run)
        if request.url.path.endswith("/output_items"):
            index = 1 if request.url.params.get("after") else 0
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [items[index]],
                    "has_more": index == 0,
                    "first_id": items[index]["id"],
                    "last_id": items[index]["id"],
                },
            )
        return httpx.Response(200, json=run)

    report = report_for(policy)
    credential = SimpleNamespace(
        get_token=lambda *args, **kwargs: AccessToken(
            "synthetic-test-token", int(time.time()) + 3600
        ),
    )
    with (
        httpx.Client(transport=httpx.MockTransport(transport)) as http_client,
        evaluation.AIProjectClient(
            endpoint="https://fixture.services.ai.azure.com/api/projects/fixture",
            credential=credential,
            logging_enable=False,
        ) as project,
        project.get_openai_client(http_client=http_client, max_retries=0) as client,
    ):
        evaluation.run_cloud(client, rows, policy, "fixture-judge", report, lambda: None)
    assert len(report["results"]) == 2
    assert all(item["passed"] for item in report["results"])
    assert sum(request.url.path.endswith("/output_items") for request in requests) == 2
    assert "SYNTHETIC-RESPONSE" not in json.dumps(report)
    assert "PRIVATE-JUDGE-REASON" not in json.dumps(report)


@pytest.mark.parametrize("status", ["failed", "canceled", "cancelled"])
def test_unsuccessful_terminal_cloud_runs_cannot_pass(status):
    policy = evaluation.load_policy()
    rows = captured(policy)["rows"][:1]
    client = fake_client(rows, status)
    with pytest.raises(evaluation.EvaluationFailure, match="cloud_evaluation_unsuccessful"):
        evaluation.run_cloud(
            client, rows, policy, "fixture-judge", report_for(policy), lambda: None
        )
    client.evals.runs.cancel.assert_not_called()
    client.evals.runs.output_items.list.assert_not_called()


@pytest.mark.parametrize("cancel_fails", [False, True])
def test_timeout_requests_cancellation_without_resubmitting(monkeypatch, cancel_fails):
    policy = evaluation.load_policy()
    rows = captured(policy)["rows"][:1]
    client = fake_client(rows, "in_progress")
    if cancel_fails:
        client.evals.runs.cancel.side_effect = OpenAIError("PRIVATE-PROVIDER-ERROR")
    monkeypatch.setattr(evaluation.time, "monotonic", Mock(side_effect=[0, 601]))
    report = report_for(policy)
    code = "cloud_cancellation_unconfirmed" if cancel_fails else "cloud_evaluation_timed_out"
    with pytest.raises(evaluation.EvaluationFailure, match=code):
        evaluation.run_cloud(client, rows, policy, "fixture-judge", report, lambda: None)
    client.evals.runs.create.assert_called_once()
    client.evals.runs.cancel.assert_called_once_with(run_id="run_fixture", eval_id="eval_fixture")
    assert report["cancellation"] == ("unconfirmed" if cancel_fails else "requested")
    assert "PRIVATE-PROVIDER-ERROR" not in json.dumps(report)


def test_judge_failure_stops_the_gate_even_when_the_builtin_default_label_passes():
    policy = evaluation.load_policy()
    rows = captured(policy)["rows"][:1]
    client = fake_client(rows)
    items = client.evals.runs.output_items.list.return_value
    items[0].results[0]["score"] = 3
    report = report_for(policy)
    with pytest.raises(evaluation.EvaluationFailure, match="quality_threshold_failed"):
        evaluation.run_cloud(client, rows, policy, "fixture-judge", report, lambda: None)
    assert report["results"][0]["passed"] is False


def test_provider_links_and_identifiers_cannot_inject_content_into_github_reports():
    assert evaluation.report_url("https://ai.azure.com/build/evaluation/fixture")
    for link in [
        "https://untrusted.example/report",
        "https://user:password@ai.azure.com/",
        "https://ai.azure.com:8443/",
        "https://ai.azure.com:not-a-port/",
        "https://ai.azure.com/>\nINJECTED",
        None,
    ]:
        assert evaluation.report_url(link) is None
    for identifier in ["private content", "[click](https://untrusted.example)", None]:
        with pytest.raises(evaluation.EvaluationFailure):
            evaluation.cloud_identifier(identifier)


@pytest.mark.parametrize("passed", [False, True])
def test_summary_identifies_foundry_evals_without_claiming_to_block_deployment(
    monkeypatch, tmp_path, passed
):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    evaluation.write_summary(
        {
            "passed": passed,
            "candidateSha": "a" * 40,
            "phase": "completed" if passed else "foundry-judges",
            "results": [
                {
                    "id": "renewal:1",
                    "passed": passed,
                    "scores": {"relevance": 4 if passed else 3, "task_outcome": 4},
                }
            ],
        }
    )
    text = summary.read_text()
    assert text.startswith("## BC Gov App - Foundry Evals (Relevance & Task Outcomes)\n")
    assert ("**PASS**" if passed else "**FAIL**") in text
    assert "deployment is a separate workflow and is not blocked by this result" in text
    assert "release gate" not in text and "**BLOCKED**" not in text


@pytest.mark.parametrize("changed", [False, True])
def test_orchestration_rechecks_configuration_after_scoring_before_passing(
    monkeypatch,
    tmp_path,
    changed,
):
    policy = evaluation.load_policy()
    initial = candidate()
    final = initial | {"AZURE_SEARCH_INDEX": "another-index"} if changed else initial
    read = Mock(side_effect=[initial, final])
    revision = Mock()
    base_client = SimpleNamespace(with_options=lambda **kwargs: object())
    project = SimpleNamespace(get_openai_client=lambda: nullcontext(base_client))
    monkeypatch.setattr(evaluation, "read_candidate", read)
    monkeypatch.setattr(evaluation, "verify_revision", revision)
    monkeypatch.setattr(evaluation, "collect_candidate", lambda *args: captured(policy)["rows"])
    monkeypatch.setattr(evaluation, "AzureCliCredential", lambda **kwargs: nullcontext(object()))
    monkeypatch.setattr(evaluation, "AIProjectClient", lambda **kwargs: nullcontext(project))
    cloud = Mock()
    monkeypatch.setattr(evaluation, "run_cloud", cloud)
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "foundry_evaluation",
            "--execute",
            "--approved",
            "--storage-approved",
            "--resource-group",
            "fixture-rg",
            "--app-name",
            "fixture-api",
            "--subscription",
            SUBSCRIPTION,
            "--candidate-sha",
            "a" * 40,
            "--model-deployment",
            "fixture-judge",
            "--output",
            str(output),
        ],
    )
    assert evaluation.main() == (1 if changed else 0)
    result = json.loads(output.read_text())
    assert result["passed"] is not changed
    assert result["deterministicPassed"] is True
    if changed:
        assert result["code"] == "candidate_configuration_changed"
    assert read.call_count == 2
    assert revision.call_count == 2
    cloud.assert_called_once()


def test_failed_collection_stops_its_owned_api_and_removes_temporary_dialogue(
    monkeypatch, tmp_path
):
    process = SimpleNamespace(poll=lambda: None, terminate=Mock(), wait=Mock(), kill=Mock())
    monkeypatch.setattr(evaluation.subprocess, "Popen", Mock(return_value=process))
    http = SimpleNamespace(
        get=lambda url: SimpleNamespace(
            status_code=200,
            json=lambda: {"status": "ok"},
        )
    )
    monkeypatch.setattr(evaluation.httpx, "Client", lambda **kwargs: nullcontext(http))
    temporary_directory = evaluation.tempfile.TemporaryDirectory
    monkeypatch.setattr(
        evaluation.tempfile,
        "TemporaryDirectory",
        lambda **kwargs: temporary_directory(dir=tmp_path, **kwargs),
    )
    captures = []

    def failed_collector(command, **kwargs):
        capture = Path(command[command.index("--output") + 1])
        capture.write_text("SYNTHETIC-DIALOGUE-TO-REMOVE")
        captures.append(capture)
        raise evaluation.subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(evaluation.subprocess, "run", failed_collector)
    with pytest.raises(evaluation.subprocess.CalledProcessError):
        evaluation.collect_candidate(candidate(), SUBSCRIPTION, evaluation.load_policy())
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=15)
    assert captures and all(not path.exists() for path in captures)
