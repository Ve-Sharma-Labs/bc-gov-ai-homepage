"""Loopback-only real API with fixture inference for the offline PyRIT check."""

import argparse
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import uvicorn

from bc_api.catalog import CatalogRepository
from bc_api.config import Settings
from bc_api.conversation_contract import ConversationProposal
from bc_api.foundry import FoundryRuntime
from bc_api.main import create_app
from bc_api.model_budget import ModelBudget
from bc_api.models import JOURNEY_IDS, AgentBinding, SourceHealth

ROOT = Path(__file__).resolve().parents[3]


class FixtureRuntime(FoundryRuntime):
    def _initialize(self):
        raise RuntimeError("The offline fixture cannot initialize a provider.")

    async def warm(self):
        await self.ensure_sources_ready()

    async def ensure_ready(self, journey_id=None):
        return None

    async def ensure_general_ready(self):
        return None

    async def ensure_conversation_ready(self):
        return None

    async def ensure_sources_ready(self):
        self.source_health = SourceHealth(
            status="ready",
            checked_at=datetime.now(UTC).isoformat(),
            usable_documents=4,
            next_expiry_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
            covered_source_ids=["health", "healthlink-bc", "service-bc"],
        )

    def journey_availability(self):
        return {key: True for key in JOURNEY_IDS}

    async def decide_conversation(self, data, context):
        value = json.loads(data)
        text = value["currentMessage"]
        current = value["context"].get("goal", "unknown")
        goal = "disability" if re.search(r"disabil|PWD", text, re.I) else "licence-renewal"
        updates = []
        issuer = re.search(r"\b(?:B\.C\.|BC\b|British Columbia\b)", text, re.I)
        if goal == "licence-renewal" and issuer:
            updates.append(
                {
                    "key": "licence-jurisdiction",
                    "value": "bc",
                    "quote": issuer.group(),
                    "status": "provided",
                }
            )
        context.model_budget = context.model_budget or ModelBudget(self.settings, context, 100)
        context.model_budget.reserve(len(data.encode()))
        context.decision_tokens = 50
        return ConversationProposal.model_validate(
            {
                "goal": goal,
                "intent": "task",
                "subject": "you",
                "action": "guide",
                "questionKey": None,
                "candidates": [],
                "updates": updates,
                "focus": "application",
                "tone": "neutral",
                "changeTask": current not in ("unknown", goal),
            }
        )


def fixture_app(port: int):
    settings = Settings(
        app_env="development",
        content_catalog_path=ROOT / "data" / "pilot-catalog.json",
        api_allowed_origins=f"http://127.0.0.1:{port}",
        api_allowed_hosts="127.0.0.1,localhost",
        api_agent_runs_per_minute=30,
        api_requests_per_minute=1000,
        api_metrics_enabled=False,
        ai_conversation_enabled=True,
        task_assistance_enabled=True,
        grounded_conversation_enabled=False,
        local_evidence_evaluation_enabled=False,
        conversation_discovery_enabled=False,
        synthetic_context_enabled=False,
        redis_endpoint="",
        azure_client_id=None,
        foundry_project_endpoint="https://offline-fixture.services.ai.azure.com/api/projects/test",
        foundry_general_agent=AgentBinding(
            name="offline-general", version="1", model_deployment="offline-model"
        ),
        foundry_conversation_agent=AgentBinding(
            name="offline-planner", version="1", model_deployment="offline-model"
        ),
        foundry_agents=[],
        foundry_contextual_agent=None,
        azure_search_endpoint="https://offline-fixture.search.windows.net",
        azure_search_index="offline-fixture",
        foundry_iq_enabled=False,
        webiq_enabled=False,
    )
    return create_app(
        settings, runtime=FixtureRuntime(settings, CatalogRepository(settings.catalog_path))
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8012)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose an unoccupied unprivileged loopback port.")
    uvicorn.run(fixture_app(args.port), host="127.0.0.1", port=args.port, access_log=False)
