"""Trusted routing and deployment-ready, managed Foundry prompt-agent definitions."""

from ag_ui.core import RunAgentInput

from bc_api.agent_policy import GENERAL_INSTRUCTIONS, instructions_for
from bc_api.catalog import CatalogRepository
from bc_api.config import Settings
from bc_api.context_agent_policy import CONTEXTUAL_INSTRUCTIONS
from bc_api.context_tools import create_context_tools, schema_context
from bc_api.errors import ApiError
from bc_api.input import parse_options
from bc_api.models import JOURNEY_IDS, AgentBinding
from bc_api.retrieval import EvidenceLedger, journey_matches
from bc_api.tools import ToolContext, create_tools, function_declarations


def bindings_for(settings: Settings) -> list[AgentBinding]:
    if settings.foundry_agents:
        return settings.foundry_agents
    if (
        settings.app_env == "development"
        and settings.foundry_agent_name
        and settings.foundry_agent_version
    ):
        return [
            AgentBinding(name=settings.foundry_agent_name, version=settings.foundry_agent_version)
        ]
    return []


def route_journey(
    request: RunAgentInput,
    *,
    contextual_enabled: bool = False,
) -> str | None:
    options = parse_options(request.forwarded_props)
    if options.version == 3:
        if not contextual_enabled:
            raise ApiError(
                503,
                "CONTEXTUAL_DEMO_UNAVAILABLE",
                "Synthetic citizen context is not enabled in this release.",
            )
        return None
    if options.version == 2:
        return options.journey_id
    matches = journey_matches(request.messages[-1].content)
    if len(matches) == 2 and "service-bc" in matches:
        matches.remove("service-bc")
    if len(matches) > 1:
        return None
    if matches:
        return matches[0]
    preferred = parse_options(request.forwarded_props).journey_id
    if preferred:
        return preferred
    for message in reversed(request.messages[:-1]):
        if message.role == "user":
            matches = journey_matches(message.content)
            if len(matches) == 1:
                return matches[0]
            if matches:
                return None
    return None


def binding_for_request(settings: Settings, request: RunAgentInput) -> AgentBinding:
    mode = parse_options(request.forwarded_props).mode
    if mode == "contextual-demo":
        if settings.contextual_agent_configured:
            assert settings.foundry_contextual_agent is not None
            return settings.foundry_contextual_agent
        raise ApiError(
            503,
            "CONTEXT_AGENT_NOT_CONFIGURED",
            "The synthetic contextual assistant is not connected.",
        )
    if mode == "general":
        if settings.general_agent_configured:
            assert settings.foundry_general_agent is not None
            return settings.foundry_general_agent
        raise ApiError(
            503,
            "GENERAL_AGENT_NOT_CONFIGURED",
            "General AI chat is not connected. The guided pathways remain available.",
        )
    return binding_for(settings, route_journey(request))


def binding_for(settings: Settings, journey_id: str | None) -> AgentBinding:
    for binding in bindings_for(settings):
        if binding.journey_id is None or binding.journey_id == journey_id:
            return binding
    raise ApiError(
        422,
        "JOURNEY_REQUIRED",
        "Choose a service so I can use the right official sources for your question.",
    )


def agent_definitions(
    catalog: CatalogRepository, *, prefix: str, model_deployment: str
) -> list[dict]:
    result = []
    for journey_id in sorted(JOURNEY_IDS):
        binding = AgentBinding(
            journey_id=journey_id,
            name=f"{prefix}-{journey_id}",
            version="1",
            model_deployment=model_deployment,
        )
        context = ToolContext(catalog, EvidenceLedger(), journey_id=journey_id)
        result.append(
            {
                "journeyId": journey_id,
                "name": binding.name,
                "definition": {
                    "kind": "prompt",
                    "model": model_deployment,
                    "instructions": instructions_for(journey_id),
                    "tools": function_declarations(create_tools(context)),
                },
            }
        )
    return result


def general_agent_definition(
    catalog: CatalogRepository, *, prefix: str, model_deployment: str
) -> dict:
    binding = AgentBinding(name=f"{prefix}-general", version="1", model_deployment=model_deployment)
    context = ToolContext(catalog, EvidenceLedger())
    return {
        "journeyId": None,
        "name": binding.name,
        "definition": {
            "kind": "prompt",
            "model": model_deployment,
            "instructions": GENERAL_INSTRUCTIONS,
            "tools": function_declarations(create_tools(context)),
        },
    }


def contextual_agent_definition(
    catalog: CatalogRepository,
    *,
    prefix: str,
    model_deployment: str,
) -> dict:
    binding = AgentBinding(
        name=f"{prefix}-contextual-demo",
        version="1",
        model_deployment=model_deployment,
    )
    tools = create_context_tools(schema_context(catalog))
    return {
        "journeyId": None,
        "mode": "contextual-demo",
        "name": binding.name,
        "definition": {
            "kind": "prompt",
            "model": model_deployment,
            "instructions": CONTEXTUAL_INSTRUCTIONS,
            "tools": function_declarations(tools),
        },
    }
