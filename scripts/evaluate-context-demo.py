"""Read-only deterministic evaluation for the synthetic citizen-context demo."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from bc_api.catalog import CatalogRepository
from bc_api.config import Settings
from bc_api.context_audit import (
    ContextAuditTrail,
    InMemoryContextAuditRepository,
)
from bc_api.context_flows import (
    FLOW_OPTIONAL_SCOPES,
    FLOW_REQUIRED_SCOPES,
)
from bc_api.context_flows.disability import clarify_request
from bc_api.context_flows.guardianship import resolve_guardianship_intent
from bc_api.context_sessions import InMemoryContextSessionRepository
from bc_api.context_tools import ContextAgentService
from bc_api.demo_personas import DemoPersonaRepository
from bc_api.demo_rules import (
    DemoProgramRuleEngine,
    DemoProgramRuleRepository,
    DemoRuleEvaluationError,
    RuleEvaluationEvidence,
    default_demo_catalog_path,
    reviewed_source_versions,
)
from bc_api.errors import ApiError
from bc_api.synthetic_context import ConsentChangeRequest, SyntheticContextService

EXPECTED_ARTIFACT_ORDER = [
    "context-summary",
    "program-matches",
    "application-preview",
    "consent-request",
    "audit-receipt",
]
EXPECTED_COMPARISON_IDS = {
    "maya-guardianship",
    "alex-disability-support",
    "sam-job-loss",
}
EXPECTED_RED_TEAM_IDS = {
    "reveal-other-persona",
    "bypass-consent",
    "replay-old-consent",
    "forge-client-facts",
    "prompt-injection-fact",
    "mutate-rule-status",
    "submit-or-confirm",
    "guardianship-overreach",
    "disability-overreach",
    "job-loss-overreach",
}
PAGE_TOKEN = "context-evaluation-page-00000001"


def _read_cases(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The evaluation case file is unavailable or invalid.") from exc
    if type(value) is not dict or set(value) != {
        "schemaVersion",
        "suiteId",
        "syntheticOnly",
        "remoteModelCallsAllowed",
        "measurementBoundary",
        "artifactOrder",
        "comparisonCases",
        "redTeamCases",
        "browserMatrix",
    }:
        raise ValueError("The evaluation case file has an unsupported shape.")
    if (
        value["schemaVersion"] != 1
        or value["syntheticOnly"] is not True
        or value["remoteModelCallsAllowed"] is not False
        or value["artifactOrder"] != EXPECTED_ARTIFACT_ORDER
    ):
        raise ValueError("The evaluation case file changed a release boundary.")
    comparisons = value["comparisonCases"]
    red_team = value["redTeamCases"]
    if (
        type(comparisons) is not list
        or {case.get("id") for case in comparisons} != EXPECTED_COMPARISON_IDS
        or type(red_team) is not list
        or {case.get("id") for case in red_team} != EXPECTED_RED_TEAM_IDS
    ):
        raise ValueError("The independent comparison or red-team case set is incomplete.")
    browser = value["browserMatrix"]
    if (
        type(browser) is not dict
        or browser.get("projects") != ["desktop", "mobile"]
        or browser.get("themes") != ["light", "dark"]
        or not all(
            browser.get(key) is True
            for key in ("reducedMotion", "keyboardFocus", "automatedAccessibility")
        )
        or browser.get("surfaces") != [
            "selector",
            "consent-sheet",
            "context-drawer",
            *EXPECTED_ARTIFACT_ORDER,
        ]
    ):
        raise ValueError("The browser evaluation matrix is incomplete.")
    return value


def _entry_questions(flow_id: str, question: str, persona_id: str) -> tuple[int, int]:
    if flow_id == "guardianship-intake":
        anonymous = resolve_guardianship_intent(question)
        contextual = resolve_guardianship_intent(question, persona_id=persona_id)
        return (
            1 if anonymous.clarification_question else 0,
            1 if contextual.clarification_question else 0,
        )
    if flow_id == "disability-support":
        clarification = clarify_request()
        return (
            1 if clarification.requires_clarification else 0,
            1 if clarification.requires_clarification else 0,
        )
    return 0, 0


def _anonymous_missing(flow_id: str, evaluated_at: datetime) -> tuple[int, list[str]]:
    repository = DemoProgramRuleRepository()
    rule_set = repository.get()
    evaluation_date = evaluated_at.date()
    matches = DemoProgramRuleEngine(repository).evaluate(
        flow_id=flow_id,
        context_facts=[],
        evidence=RuleEvaluationEvidence(
            rule_set_version=rule_set.rule_set_version,
            policy_effective_date=evaluation_date,
            evaluated_at=evaluation_date,
            source_versions=reviewed_source_versions(rule_set),
        ),
    )
    keys = sorted({key for match in matches for key in match.missing_facts})
    return len(keys), keys


async def _contextual_metrics(
    case: dict[str, Any], evaluated_at: datetime
) -> dict[str, Any]:
    settings = Settings(
        app_env="development",
        content_catalog_path=default_demo_catalog_path(),
        synthetic_context_enabled=True,
        synthetic_context_session_ttl_seconds=300,
        synthetic_context_consent_ttl_seconds=180,
    )
    audit_logger = logging.getLogger(f"context-evaluation.{case['id']}")
    audit_logger.handlers = [logging.NullHandler()]
    audit_logger.propagate = False
    audit_logger.addHandler(logging.NullHandler())
    audit_logger.setLevel(logging.CRITICAL)
    service = SyntheticContextService(
        settings,
        DemoPersonaRepository(),
        InMemoryContextSessionRepository(settings.api_max_sessions),
        clock=lambda: evaluated_at,
        audit=ContextAuditTrail(
            InMemoryContextAuditRepository(
                settings.synthetic_context_audit_max_events,
                settings.synthetic_context_audit_max_bytes,
            ),
            logger=audit_logger,
        ),
    )
    owner = f"evaluation-owner-{case['id']}"
    _, token = await service.create_session(
        owner,
        PAGE_TOKEN,
        None,
        case["personaId"],
    )
    await service.change_consent(
        owner,
        PAGE_TOKEN,
        token,
        ConsentChangeRequest(action="grant", scopes=case["contextualScopes"]),
    )
    agent = ContextAgentService(CatalogRepository(settings.catalog_path), service)
    plan = await agent.authorize(
        owner,
        PAGE_TOKEN,
        token,
        run_id=f"evaluation-{case['id']}",
    )
    summary = plan.artifacts[0].payload
    matches = plan.artifacts[1].payload
    preview = plan.artifacts[2].payload
    audit = await agent.complete_run(plan, "finished")
    kinds = [artifact.kind for artifact in plan.artifacts]
    kinds.append(audit.value["kind"])
    return {
        "entryClarifyingQuestions": _entry_questions(
            case["flowId"],
            case["sampleQuestion"],
            case["personaId"],
        )[1],
        "ruleClarifyingQuestions": len(
            {key for match in matches for key in match.missing_facts}
        ),
        "contextFactsUsed": len(summary.facts),
        "programArtifacts": len(matches),
        "programStatuses": [match.status for match in matches],
        "previewAvailable": True,
        "previewPopulatedFields": sum(
            field.source != "missing" for field in preview.fields
        ),
        "previewMissingItems": len(preview.missing_items),
        "artifactOrder": kinds,
    }


async def evaluate(path: Path, *, snapshot_date: date | None = None) -> dict[str, Any]:
    evaluated_at = (
        datetime.combine(snapshot_date, datetime.min.time(), tzinfo=UTC)
        if snapshot_date is not None
        else datetime.now(UTC)
    )
    suite = _read_cases(path)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for case in suite["comparisonCases"]:
        flow_id = case["flowId"]
        required = list(FLOW_REQUIRED_SCOPES[flow_id])
        optional = list(FLOW_OPTIONAL_SCOPES[flow_id])
        if case["requiredScopes"] != required or case["optionalScopes"] != optional:
            failures.append(
                {
                    "caseId": case["id"],
                    "field": "consentScopes",
                    "expected": {"required": required, "optional": optional},
                    "actual": {
                        "required": case["requiredScopes"],
                        "optional": case["optionalScopes"],
                    },
                }
            )
        anonymous_count, anonymous_keys = _anonymous_missing(flow_id, evaluated_at)
        anonymous_entry, _ = _entry_questions(
            flow_id,
            case["sampleQuestion"],
            case["personaId"],
        )
        contextual = await _contextual_metrics(case, evaluated_at)
        actual = {
            "anonymousEntryClarifyingQuestions": anonymous_entry,
            "anonymousRuleClarifyingQuestions": anonymous_count,
            "anonymousContextFactsUsed": 0,
            "anonymousProgramArtifacts": 0,
            "anonymousPreviewAvailable": False,
            "contextualEntryClarifyingQuestions": contextual[
                "entryClarifyingQuestions"
            ],
            "contextualRuleClarifyingQuestions": contextual[
                "ruleClarifyingQuestions"
            ],
            "contextualContextFactsUsed": contextual["contextFactsUsed"],
            "contextualProgramArtifacts": contextual["programArtifacts"],
            "contextualPreviewAvailable": contextual["previewAvailable"],
            "contextualPreviewPopulatedFields": contextual[
                "previewPopulatedFields"
            ],
            "contextualPreviewMissingItems": contextual["previewMissingItems"],
        }
        if actual != case["expected"]:
            failures.append(
                {
                    "caseId": case["id"],
                    "field": "measurements",
                    "expected": case["expected"],
                    "actual": actual,
                }
            )
        if contextual["artifactOrder"] != EXPECTED_ARTIFACT_ORDER:
            failures.append(
                {
                    "caseId": case["id"],
                    "field": "artifactOrder",
                    "expected": EXPECTED_ARTIFACT_ORDER,
                    "actual": contextual["artifactOrder"],
                }
            )
        results.append(
            {
                "caseId": case["id"],
                "personaId": case["personaId"],
                "flowId": flow_id,
                "sampleQuestion": case["sampleQuestion"],
                "anonymous": {
                    "mode": "general",
                    "entryClarifyingQuestions": anonymous_entry,
                    "deterministicMissingFactQuestions": anonymous_count,
                    "deterministicMissingFactKeys": anonymous_keys,
                    "contextFactsUsed": 0,
                    "programArtifacts": 0,
                    "previewAvailable": False,
                },
                "contextual": {
                    "mode": "contextual-demo",
                    **contextual,
                },
            }
        )
    return {
        "schemaVersion": 1,
        "suiteId": suite["suiteId"],
        "passed": not failures,
        "syntheticOnly": True,
        "remoteModelCalls": 0,
        "fixtureAsOf": DemoProgramRuleRepository().get().reviewed_at,
        "currentSourceReadinessVerified": False,
        "evaluationMode": "snapshot" if snapshot_date is not None else "current",
        "evaluatedAt": evaluated_at.isoformat(),
        "measurementBoundary": suite["measurementBoundary"],
        "cases": results,
        "failures": failures,
    }


def snapshot_date_argument(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use a valid YYYY-MM-DD snapshot date.") from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("Use a valid YYYY-MM-DD snapshot date.")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        type=Path,
        default=ROOT / "data" / "citizen-context-evaluation-cases.json",
    )
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument(
        "--snapshot-date",
        type=snapshot_date_argument,
        help="Evaluate a historical YYYY-MM-DD snapshot, not current readiness.",
    )
    args = parser.parse_args()
    try:
        result = asyncio.run(
            evaluate(args.cases.resolve(), snapshot_date=args.snapshot_date)
        )
    except (ApiError, DemoRuleEvaluationError) as exc:
        message = exc.message if isinstance(exc, ApiError) else exc.safe_message
        print(
            json.dumps({
                "passed": False,
                "evaluationMode": "snapshot" if args.snapshot_date is not None else "current",
                "error": {"code": exc.code.upper().replace("-", "_"), "message": message},
            }),
            file=sys.stderr,
        )
        return 1
    except (AssertionError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}), file=sys.stderr)
        return 1
    print(
        json.dumps(
            result,
            indent=2 if args.pretty else None,
            sort_keys=True,
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
