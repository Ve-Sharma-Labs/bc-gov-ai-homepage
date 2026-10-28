"""Print the local policy/declarations for operator review; never publish them."""

import json

from bc_api.agent_policy import AGENT_INSTRUCTIONS
from bc_api.catalog import CatalogRepository
from bc_api.config import Settings
from bc_api.models import EvidenceBundle, GuidedPlan, LocationsResponse
from bc_api.retrieval import EvidenceLedger
from bc_api.tools import ToolContext, create_tools, function_declarations


def main() -> None:
    tools = create_tools(ToolContext(CatalogRepository(Settings().catalog_path), EvidenceLedger()))
    print(
        json.dumps(
            {
                "instructions": AGENT_INSTRUCTIONS,
                "tools": function_declarations(tools),
                "outputSchemas": {
                    "search_approved_sources": EvidenceBundle.model_json_schema(by_alias=True),
                    "build_preparation_plan": GuidedPlan.model_json_schema(by_alias=True),
                    "find_service_locations": LocationsResponse.model_json_schema(by_alias=True),
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
