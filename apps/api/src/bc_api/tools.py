"""Local implementations only; nothing here registers or creates a remote agent."""

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from ag_ui.core import CustomEvent
from agent_framework import FunctionTool, tool
from pydantic import BaseModel, ConfigDict, Field

from bc_api.agent_policy import LOCATION_JOURNEYS
from bc_api.catalog import CatalogRepository
from bc_api.errors import ApiError
from bc_api.models import (
    EvidenceBundle,
    JourneyId,
    LocationsArtifact,
    PreparationArtifact,
)
from bc_api.protocol import LOCATION_NOTICE
from bc_api.retrieval import AzureRetriever, EvidenceLedger

TOOL_NAMES = frozenset(
    {"search_approved_sources", "build_preparation_plan", "find_service_locations"}
)


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchInput(ToolInput):
    query: Annotated[str, Field(min_length=1, max_length=512)]
    journey_id: JourneyId | None


class PlanInput(ToolInput):
    journey_id: JourneyId


class LocationInput(ToolInput):
    service: Literal[
        "icbc-licensing",
        "income-assistance",
        "bc-services-card",
        "bceid",
    ] | None
    municipality: Annotated[str, Field(min_length=1, max_length=100)] | None


@dataclass
class ToolContext:
    catalog: CatalogRepository
    ledger: EvidenceLedger
    retriever: AzureRetriever | None = None
    failure: ApiError | None = None
    pending_events: list[CustomEvent] = field(default_factory=list)
    journey_id: str | None = None
    output_byte_limit: int = 65536
    model_work_started: bool | None = None
    search_results: dict[tuple[str, str | None], EvidenceBundle] = field(default_factory=dict)
    phase_times: dict[str, float] = field(default_factory=dict)

    def mark_phase(self, phase: str) -> None:
        self.phase_times.setdefault(phase, time.monotonic())


def create_tools(context: ToolContext) -> list[FunctionTool]:
    def bounded_output(value: BaseModel) -> str:
        payload = value.model_dump_json(by_alias=True)
        if len(payload.encode()) > context.output_byte_limit:
            context.failure = ApiError(
                502, "TOOL_OUTPUT_LIMIT", "The result is too large. Please narrow your question."
            )
            raise RuntimeError("The tool result exceeded its output limit.")
        return payload

    def scoped_journey(journey_id: str | None) -> str | None:
        if context.journey_id and journey_id not in (None, context.journey_id):
            context.failure = ApiError(
                403, "TOOL_SCOPE_DENIED", "That operation belongs to a different service journey."
            )
            raise RuntimeError("The requested journey is outside this agent's scope.")
        return context.journey_id or journey_id

    @tool(
        schema=SearchInput,
        max_invocations=3,
        max_invocation_exceptions=1,
        description=(
            "Search the approved BC corpus. Returns versioned evidence, never web research."
        ),
    )
    async def search_approved_sources(query: str, journey_id: str | None) -> str:
        journey_id = scoped_journey(journey_id)
        if context.retriever is None:
            context.failure = ApiError(
                503, "SEARCH_UNAVAILABLE", "Official sources are unavailable."
            )
            raise RuntimeError("Official sources are unavailable.")
        try:
            key = (" ".join(query.split()).casefold(), journey_id)
            bundle = context.search_results.get(key)
            if bundle is None:
                bundle = await context.retriever.retrieve(query, journey_id)
                context.search_results[key] = bundle
            payload = bounded_output(bundle)
            context.ledger.add(bundle)
            return payload
        except ApiError as exc:
            context.failure = exc
            raise RuntimeError("Official-source retrieval did not succeed.") from None

    @tool(
        schema=PlanInput,
        max_invocations=2,
        max_invocation_exceptions=1,
        description=(
            "Return a deterministic, cited preparation plan and official handoffs. No transactions."
        ),
    )
    async def build_preparation_plan(journey_id: str) -> str:
        scoped_journey(journey_id)
        try:
            plan = context.catalog.plan(journey_id)
            payload = bounded_output(plan)
            artifact = PreparationArtifact(
                id=f"plan-{journey_id}", journey=plan.journey, sources=plan.sources
            )
            context.pending_events.append(
                CustomEvent(name="bc.artifact", value=artifact.model_dump(by_alias=True))
            )
            return payload
        except ApiError as exc:
            context.failure = exc
            raise RuntimeError("The guided plan is unavailable.") from None

    @tool(
        schema=LocationInput,
        max_invocations=2,
        max_invocation_exceptions=1,
        description=(
            "Filter the curated office snapshot by explicit services and exclusions, "
            "then municipality."
        ),
    )
    async def find_service_locations(service: str | None, municipality: str | None) -> str:
        try:
            result = context.catalog.locations(service, municipality)
            payload = bounded_output(result)
            if len(result.locations) > 100:
                raise ApiError(
                    422, "LOCATION_LIMIT", "Choose a municipality to narrow the office results."
                )
            source_ids = {key for location in result.locations for key in location.source_ids}
            fingerprint = hashlib.sha256(
                json.dumps([service, municipality], ensure_ascii=True).encode()
            ).hexdigest()[:16]
            artifact = LocationsArtifact(
                id=f"offices-{fingerprint}",
                locations=result.locations,
                sources=[
                    source for source in context.catalog.get().sources if source.id in source_ids
                ],
                notice=LOCATION_NOTICE,
            )
            context.pending_events.append(
                CustomEvent(name="bc.artifact", value=artifact.model_dump(by_alias=True))
            )
            return payload
        except ApiError as exc:
            context.failure = exc
            raise RuntimeError("The location query could not be completed.") from None

    functions = [search_approved_sources, build_preparation_plan]
    if context.journey_id is None or context.journey_id in LOCATION_JOURNEYS:
        functions.append(find_service_locations)
    return functions


def function_declarations(tools: list[FunctionTool]) -> list[dict[str, Any]]:
    return [
        {"type": "function", **item.to_json_schema_spec()["function"], "strict": True}
        for item in tools
    ]


def normalized_schema(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: normalized_schema(item) for key, item in value.items() if key not in {"title"}}
    if isinstance(value, list):
        return [normalized_schema(item) for item in value]
    return value


def verify_tool_declarations(actual: list[dict[str, Any]], tools: list[FunctionTool]) -> None:
    expected = {item["name"]: item for item in function_declarations(tools)}
    if len(actual) != len(expected) or any(item.get("type") != "function" for item in actual):
        raise ApiError(
            503, "AGENT_POLICY_MISMATCH", "The configured agent has unapproved tool capabilities."
        )
    if {item.get("name") for item in actual} != expected.keys():
        raise ApiError(
            503, "AGENT_POLICY_MISMATCH", "The configured agent tools do not match the pilot."
        )
    for declaration in actual:
        name = declaration["name"]
        fields = {key: declaration.get(key) for key in expected[name]}
        if normalized_schema(fields) != normalized_schema(expected[name]):
            raise ApiError(
                503, "AGENT_POLICY_MISMATCH", "The configured agent tool schema is not approved."
            )
        if declaration.get("defer_loading") or declaration.get("allowed_callers"):
            raise ApiError(
                503, "AGENT_POLICY_MISMATCH", "Deferred or delegated tools are not approved."
            )
