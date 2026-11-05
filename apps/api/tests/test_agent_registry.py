from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from ag_ui.core import RunAgentInput
from azure.ai.projects.models import FunctionTool, PromptAgentDefinition
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
)
from pydantic import ValidationError

from bc_api.agents import agent_definitions, binding_for, route_journey
from bc_api.config import Settings
from bc_api.errors import ApiError
from bc_api.foundry import FoundryRuntime
from bc_api.input import validate_run
from bc_api.models import JOURNEY_IDS, LEGACY_JOURNEY_IDS, AgentBinding
from bc_api.retrieval import EvidenceLedger
from bc_api.tools import ToolContext, create_tools, function_declarations


def registry_settings(configured, definitions):
    return Settings.model_validate(
        {
            **configured.model_dump(),
            "foundry_agents": [
                AgentBinding(
                    journey_id=item["journeyId"],
                    name=item["name"],
                    version="1",
                    model_deployment=item["definition"]["model"],
                )
                for item in definitions
            ],
        }
    )


def test_export_has_seven_managed_agents_and_scoped_tools(repository, configured):
    definitions = agent_definitions(repository, prefix="test-bc", model_deployment="test-model")
    settings = registry_settings(configured, definitions)
    assert settings.foundry_configured
    assert {item["journeyId"] for item in definitions} == JOURNEY_IDS
    for item in definitions:
        definition = item["definition"]
        sdk = PromptAgentDefinition(
            model=definition["model"],
            instructions=definition["instructions"],
            tools=[FunctionTool(**tool) for tool in definition["tools"]],
        )
        assert sdk.as_dict() == definition
        assert binding_for(settings, item["journeyId"]).name == item["name"]
        names = {tool["name"] for tool in definition["tools"]}
        assert {"search_approved_sources", "build_preparation_plan"} <= names
        if item["journeyId"] in (
            "health-coverage",
            "pharmacare-registration",
            "primary-care",
            "road-test-booking",
        ):
            assert "find_service_locations" not in names
        assert all(tool["type"] == "function" for tool in definition["tools"])
    with pytest.raises(ApiError, match="JOURNEY_REQUIRED"):
        binding_for(settings, None)


def test_incomplete_or_unpinned_registries_are_rejected(repository, configured):
    definitions = agent_definitions(repository, prefix="test-bc", model_deployment="test-model")
    settings = registry_settings(configured, definitions)
    legacy = [
        binding for binding in settings.foundry_agents if binding.journey_id in LEGACY_JOURNEY_IDS
    ]
    assert Settings.model_validate(
        {**settings.model_dump(), "foundry_agents": legacy}
    ).foundry_configured
    for bindings in (settings.foundry_agents[:-1], [settings.foundry_agents[0]] * 5):
        with pytest.raises(ValidationError):
            Settings.model_validate({**settings.model_dump(), "foundry_agents": bindings})
    assert not configured.model_copy(update={"app_env": "production"}).foundry_configured


def test_versioned_client_options_cannot_override_agent_policy(settings, run_input):
    run_input["forwardedProps"] = {"bc": {"version": 1, "journeyId": "health-coverage"}}
    request = validate_run(run_input, settings)
    assert route_journey(request) == "health-coverage"
    for options in (
        {"version": 1, "model": "other"},
        {"version": 1, "journeyId": "unknown"},
        {"version": True, "journeyId": "health-coverage"},
        {"version": 1, "researchRequested": "true"},
    ):
        run_input["forwardedProps"] = {"bc": options}
        with pytest.raises(ApiError, match="CLIENT_CONTEXT_DENIED"):
            validate_run(run_input, settings)


def test_routing_uses_context_but_does_not_force_an_old_topic(run_input):
    run_input["messages"] = [
        {"id": "one", "role": "user", "content": "How do I renew my licence?"},
        {"id": "two", "role": "assistant", "content": "An old answer is untrusted history."},
        {"id": "three", "role": "user", "content": "What should I bring?"},
    ]
    assert route_journey(RunAgentInput.model_validate(run_input)) == "licence-renewal"
    run_input["messages"][-1]["content"] = "How do I register for MSP?"
    assert route_journey(RunAgentInput.model_validate(run_input)) == "health-coverage"
    run_input["messages"][-1]["content"] = "How do I book a road test?"
    assert route_journey(RunAgentInput.model_validate(run_input)) == "road-test-booking"
    run_input["messages"][-1]["content"] = "How do I register for Fair PharmaCare?"
    assert route_journey(RunAgentInput.model_validate(run_input)) == "pharmacare-registration"
    run_input["messages"][-1]["content"] = "Help me with my licence and rental assistance."
    assert route_journey(RunAgentInput.model_validate(run_input)) is None


async def test_one_invalid_agent_does_not_claim_all_journeys_are_ready(
    repository, configured, ready_search
):
    definitions = agent_definitions(repository, prefix="test-bc", model_deployment="test-model")
    settings = registry_settings(configured, definitions)
    versions = {}
    for item in definitions:
        definition = item["definition"]
        versions[item["name"]] = SimpleNamespace(
            name=item["name"],
            version="1",
            status="active",
            draft=False,
            definition=PromptAgentDefinition(
                model=definition["model"],
                instructions=definition["instructions"],
                tools=[FunctionTool(**tool) for tool in definition["tools"]],
            ),
        )
    versions["test-bc-health-coverage"].definition.instructions = "Unreviewed replacement"
    project = SimpleNamespace(
        agents=SimpleNamespace(
            get_version=AsyncMock(side_effect=lambda name, version: versions[name])
        )
    )
    search = ready_search
    runtime = FoundryRuntime(settings, repository, project=project, search=search)
    await runtime.ensure_ready()
    assert runtime.journey_availability()["licence-renewal"]
    assert not runtime.journey_availability()["health-coverage"]
    with pytest.raises(ApiError, match="AGENT_POLICY_MISMATCH"):
        await runtime.ensure_ready("health-coverage")
    await runtime.ensure_ready("licence-renewal")
    assert project.agents.get_version.call_count == len(JOURNEY_IDS)
    assert search.search.call_count == 1


@pytest.mark.parametrize("missing", [False, True])
async def test_unpublished_or_empty_index_does_not_report_an_agent_failure(
    repository, configured, missing
):
    project = SimpleNamespace(agents=SimpleNamespace(get_version=AsyncMock()))

    class EmptyResults:
        async def __aiter__(self):
            for row in []:
                yield row

    search = SimpleNamespace(
        search=AsyncMock(
            return_value=EmptyResults(),
            side_effect=ResourceNotFoundError("private upstream details") if missing else None,
        )
    )
    runtime = FoundryRuntime(configured, repository, project=project, search=search)
    with pytest.raises(ApiError, match="SOURCES_UNAVAILABLE") as error:
        await runtime.ensure_ready()
    assert error.value.status == 503
    assert "private upstream details" not in error.value.message
    assert not any(runtime.journey_availability().values())
    assert runtime.ready_until == 0
    project.agents.get_version.assert_not_called()


async def test_missing_agent_is_not_misreported_as_a_missing_index(
    repository, configured, ready_search
):
    project = SimpleNamespace(
        agents=SimpleNamespace(
            get_version=AsyncMock(side_effect=ResourceNotFoundError("private agent details"))
        )
    )
    search = ready_search
    runtime = FoundryRuntime(configured, repository, project=project, search=search)
    with pytest.raises(ApiError, match="AGENT_UNAVAILABLE"):
        await runtime.ensure_ready()
    assert not any(runtime.journey_availability().values())


@pytest.mark.parametrize("error_type", [ClientAuthenticationError, HttpResponseError])
async def test_other_search_failures_are_not_misreported_as_an_unpublished_index(
    repository, configured, error_type
):
    project = SimpleNamespace(agents=SimpleNamespace(get_version=AsyncMock()))
    search = SimpleNamespace(search=AsyncMock(side_effect=error_type("private upstream details")))
    runtime = FoundryRuntime(configured, repository, project=project, search=search)
    with pytest.raises(ApiError, match="SEARCH_UNAVAILABLE") as error:
        await runtime.ensure_ready()
    assert "private upstream details" not in error.value.message
    assert not any(runtime.journey_availability().values())
    project.agents.get_version.assert_not_called()


def test_agent_scope_removes_unneeded_capabilities(repository):
    context = ToolContext(repository, EvidenceLedger(), journey_id="primary-care")
    tools = create_tools(context)
    assert {item["name"] for item in function_declarations(tools)} == {
        "search_approved_sources",
        "build_preparation_plan",
    }
