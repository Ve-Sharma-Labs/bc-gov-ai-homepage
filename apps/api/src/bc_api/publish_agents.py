"""Export by default; create immutable remote agent versions only with explicit approval."""

import argparse
import asyncio
import json
import sys

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import FunctionTool, PromptAgentDefinition
from azure.core.exceptions import AzureError
from azure.identity.aio import AzureCliCredential
from pydantic import ValidationError

from bc_api.agents import agent_definitions, general_agent_definition
from bc_api.catalog import CatalogRepository
from bc_api.config import Settings
from bc_api.errors import ApiError
from bc_api.foundry import configure_safe_logging
from bc_api.models import AgentBinding
from bc_api.urls import azure_endpoint


async def publish(definitions: list[dict], endpoint: str) -> list[dict]:
    endpoint = azure_endpoint(endpoint, service="foundry")
    registered: list[dict] = []
    async with AzureCliCredential() as credential:
        async with AIProjectClient(
            endpoint=endpoint, credential=credential, retry_total=0, logging_enable=False
        ) as project:
            for entry in definitions:
                definition = entry["definition"]
                version = await project.agents.create_version(
                    agent_name=entry["name"],
                    definition=PromptAgentDefinition(
                        model=definition["model"],
                        instructions=definition["instructions"],
                        tools=[FunctionTool(**tool) for tool in definition["tools"]],
                    ),
                    metadata={
                        "journey": entry["journeyId"] or "general",
                        "contract": "1" if entry["journeyId"] else "2",
                    },
                    draft=False,
                )
                registered.append(
                    AgentBinding(
                        journey_id=entry["journeyId"],
                        name=version.name,
                        version=version.version,
                        model_deployment=definition["model"],
                    ).model_dump(by_alias=True)
                )
                print(f"Registered {version.name} version {version.version}.", file=sys.stderr)
    return registered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="bc-service")
    parser.add_argument("--model-deployment", required=True)
    parser.add_argument("--project-endpoint")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--approved", action="store_true")
    parser.add_argument("--general-only", action="store_true")
    args = parser.parse_args()
    if args.publish and (not args.approved or not args.project_endpoint):
        parser.error("Publishing requires --approved and a user-confirmed --project-endpoint.")
    configure_safe_logging()
    try:
        catalog = CatalogRepository(Settings().catalog_path)
        definitions = (
            [
                general_agent_definition(
                    catalog, prefix=args.prefix, model_deployment=args.model_deployment
                )
            ]
            if args.general_only
            else agent_definitions(
                catalog, prefix=args.prefix, model_deployment=args.model_deployment
            )
        )
        if args.publish:
            endpoint = azure_endpoint(args.project_endpoint, service="foundry")
            label = "general agent" if args.general_only else "seven-agent bundle"
            print(f"Publishing the reviewed {label} to {endpoint}.", file=sys.stderr)
            result = asyncio.run(publish(definitions, endpoint))
            print(
                json.dumps(
                    {"FOUNDRY_GENERAL_AGENT": result[0]}
                    if args.general_only
                    else {"FOUNDRY_AGENTS": result},
                    indent=2,
                )
            )
        else:
            print(json.dumps({"mode": "review-only", "agents": definitions}, indent=2))
    except AzureError, ApiError, ValidationError, ValueError:
        print(
            "Agent publication/export failed. Check the target, permissions and reviewed model "
            "deployment. Previously created versions were not deleted; review the reported names "
            "before retrying.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
