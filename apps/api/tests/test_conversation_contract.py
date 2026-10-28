import pytest
from pydantic import ValidationError

from bc_api.config import Settings
from bc_api.errors import ApiError
from bc_api.input import parse_options, validate_run
from bc_api.models import JOURNEY_IDS, AgentBinding, ResponseContext
from bc_api.output import OutputGate
from bc_api.protocol import response_context_event
from bc_api.retrieval import EvidenceLedger


def test_legacy_options_remain_supported():
    assert parse_options({}).version == 1
    options = parse_options({"bc": {"version": 1, "journeyId": "service-bc"}})
    assert options.journey_id == "service-bc"
    assert options.mode is None


@pytest.mark.parametrize(
    "options",
    [
        {"version": 2, "mode": "general"},
        {"version": 2, "mode": "general", "journeyId": None},
        {"version": 2, "mode": "pathway", "journeyId": "health-coverage"},
    ],
)
def test_explicit_general_and_pathway_requests_are_valid(settings, run_input, options):
    run_input["forwardedProps"] = {"bc": options}
    request = validate_run(run_input, settings)
    parsed = parse_options(request.forwarded_props)
    assert parsed.version == 2
    assert parsed.mode == options["mode"]


@pytest.mark.parametrize(
    "options",
    [
        {"version": 1, "mode": "general"},
        {"version": 1, "mode": None},
        {"version": 2},
        {"version": 2, "mode": "general", "journeyId": "service-bc"},
        {"version": 2, "mode": "pathway"},
        {"version": 2, "mode": "pathway", "journeyId": None},
        {"version": 2, "mode": "other"},
        {"version": 2, "mode": "general", "researchRequested": "false"},
        {"version": 2, "mode": "general", "responseKind": "dialogue"},
        {"version": 2, "mode": "general", "origin": "application"},
        {"version": 2, "mode": "general", "sourceIds": ["unreviewed"]},
        {"version": True, "mode": "general"},
    ],
)
def test_client_cannot_mix_scopes_or_choose_response_authority(options):
    with pytest.raises(ApiError, match="CLIENT_CONTEXT_DENIED"):
        parse_options({"bc": options})


def test_general_binding_and_retrieval_configuration_are_distinct(configured):
    settings = Settings(
        foundry_project_endpoint=configured.foundry_project_endpoint,
        foundry_general_agent=AgentBinding(
            name="test-general", version="1", model_deployment="test-model"
        ),
    )
    assert settings.general_agent_configured
    assert not settings.search_configured
    assert not settings.foundry_configured
    assert settings.foundry_agents == []


@pytest.mark.parametrize(
    "binding",
    [
        {"name": "test-general", "version": "1"},
        {
            "name": "test-general",
            "version": "1",
            "modelDeployment": "test-model",
            "journeyId": "service-bc",
        },
    ],
)
def test_general_binding_must_pin_a_model_without_a_pathway(binding):
    with pytest.raises(ValidationError):
        Settings(foundry_general_agent=binding)


def test_general_and_journey_bindings_cannot_share_an_agent_name():
    bindings = [
        AgentBinding(
            journey_id=journey,
            name=f"test-{journey}",
            version="1",
            model_deployment="test-model",
        )
        for journey in sorted(JOURNEY_IDS)
    ]
    with pytest.raises(ValidationError):
        Settings(
            foundry_agents=bindings,
            foundry_general_agent=AgentBinding(
                name=bindings[0].name, version="1", model_deployment="test-model"
            ),
        )


def test_response_context_is_typed_and_server_owned(repository):
    event = response_context_event("dialogue", "application")
    assert event.name == "bc.response"
    assert event.value == {"version": 1, "kind": "dialogue", "origin": "application"}
    with pytest.raises(ValidationError):
        ResponseContext(kind="dialogue", origin="application", trusted=True)
    with pytest.raises(ApiError, match="OUTPUT_INVALID"):
        OutputGate(repository, EvidenceLedger()).hold(event)
