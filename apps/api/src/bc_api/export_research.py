"""Export reviewable Foundry IQ definitions. No network, resource writes or billing changes."""

import json
import sys

from pydantic import ValidationError

from bc_api.agents import research_agent_definition
from bc_api.config import Settings
from bc_api.foundry_iq import knowledge_definitions


def main() -> int:
    try:
        settings = Settings()
        definitions = knowledge_definitions(settings)
        binding = settings.foundry_research_agent
        if binding is None:
            raise ValueError("Select the isolated research answer agent.")
        definitions["answerAgent"] = research_agent_definition(
            prefix="bc-service",
            model_deployment=binding.model_deployment,
        )
        definitions["answerAgent"]["name"] = binding.name
        definitions["mode"] = "review-only"
        definitions["requiresSeparateApproval"] = [
            "preview release",
            "Search-to-model inference permission and network reachability",
            "API read-only knowledge definition access",
            "agentic retrieval billing and budgets",
            "matched quality/cost/latency evaluation",
        ]
        print(json.dumps(definitions, indent=2))
    except ValueError, ValidationError:
        print("Research export needs complete, reviewed existing bindings.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
