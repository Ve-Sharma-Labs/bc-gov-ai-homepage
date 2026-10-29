from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from bc_api.models import JOURNEY_IDS, LEGACY_JOURNEY_IDS, AgentBinding
from bc_api.urls import azure_endpoint


def default_catalog_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data" / "pilot-catalog.json"
        if candidate.is_file() or (parent / "PRODUCT.md").is_file():
            return candidate
    return Path("/app/data/pilot-catalog.json")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        populate_by_name=True,
        case_sensitive=False,
        hide_input_in_errors=True,
        env_ignore_empty=True,
    )
    app_env: Literal["development", "production"] = "development"
    content_catalog_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("CONTENT_CATALOG_PATH", "SOURCE_CATALOG_PATH"),
    )
    foundry_project_endpoint: str = ""
    foundry_agent_name: str = ""
    foundry_agent_version: str = ""
    foundry_agents: list[AgentBinding] = Field(default_factory=list, max_length=7)
    foundry_general_agent: AgentBinding | None = None
    foundry_contextual_agent: AgentBinding | None = None
    azure_client_id: str | None = None
    azure_search_endpoint: str = ""
    azure_search_index: str = ""
    azure_search_semantic_config: str = ""
    azure_search_vector_enabled: bool = False
    azure_search_metadata_enabled: bool = False
    azure_search_metadata_reviewed: bool = False
    azure_openai_endpoint: str = ""
    azure_openai_embedding_deployment: str = ""
    azure_openai_embedding_dimensions: int | None = Field(default=None, ge=1, le=3072)
    search_max_age_days: int = Field(default=7, ge=1, le=30)
    api_allowed_origins: str = ""
    api_allowed_hosts: str = "localhost,127.0.0.1,::1,api"
    api_max_request_bytes: int = Field(default=65536, ge=1024, le=262144)
    api_max_messages: int = Field(default=24, ge=1, le=48)
    api_max_message_chars: int = Field(default=4000, ge=1, le=8000)
    api_max_total_message_chars: int = Field(default=16000, ge=1, le=32000)
    api_max_concurrent_runs: int = Field(default=4, ge=1, le=8)
    api_requests_per_minute: int = Field(default=180, ge=10, le=1000)
    api_agent_runs_per_minute: int = Field(default=8, ge=1, le=30)
    api_run_timeout_seconds: float = Field(default=60, ge=1, le=120)
    api_upstream_timeout_seconds: float = Field(default=15, ge=1, le=30)
    azure_cli_process_timeout_seconds: int = Field(default=15, ge=5, le=30)
    api_max_sessions: int = Field(default=1000, ge=1, le=10000)
    synthetic_context_enabled: bool = False
    synthetic_context_session_ttl_seconds: int = Field(default=1800, ge=60, le=3600)
    synthetic_context_consent_ttl_seconds: int = Field(default=900, ge=60, le=1800)
    synthetic_context_audit_max_events: int = Field(default=100, ge=1, le=100)
    synthetic_context_audit_max_bytes: int = Field(default=65536, ge=512, le=262144)
    redis_endpoint: str = ""
    redis_client_id: str | None = None
    api_control_namespace: str = Field(default="bc-pilot", pattern=r"^[a-z0-9-]{1,48}$")
    api_auth_tenant_id: str = Field(default="", pattern=r"^(?:|[0-9a-fA-F-]{36})$")
    api_auth_audience: str = ""
    api_auth_callers: list[str] = Field(default_factory=list, max_length=10)
    api_daily_run_limit: int = Field(default=0, ge=0, le=1000000)
    api_daily_token_limit: int = Field(default=0, ge=0, le=1000000000)
    api_daily_cost_limit_microusd: int = Field(default=0, ge=0, le=1000000000000)
    api_token_price_microusd: int = Field(default=0, ge=0, le=1000000)
    api_model_calls_per_run: int = Field(default=5, ge=1, le=5)
    api_model_input_byte_budget: int = Field(default=131072, ge=1024, le=262144)
    api_model_output_tokens: int = Field(default=1600, ge=100, le=4000)
    api_tool_output_bytes: int = Field(default=65536, ge=1024, le=65536)
    api_metrics_enabled: bool = False
    applicationinsights_connection_string: str = ""
    webiq_enabled: bool = False
    webiq_app_id: str = ""
    webiq_privacy_approval_id: str = ""
    webiq_terms_approval_id: str = ""
    webiq_egress_approved: bool = False
    webiq_zero_query_logging_approved: bool = False
    webiq_transient_handling_verified: bool = False

    @model_validator(mode="after")
    def complete_agent_registry(self) -> Self:
        journey_ids = {binding.journey_id for binding in self.foundry_agents}
        if self.foundry_agents and (
            journey_ids not in (LEGACY_JOURNEY_IDS, JOURNEY_IDS)
            or len({binding.name for binding in self.foundry_agents}) != len(journey_ids)
            or any(not binding.model_deployment for binding in self.foundry_agents)
        ):
            raise ValueError(
                "FOUNDRY_AGENTS must pin either the five legacy bindings or all seven "
                "journey bindings, with distinct names and model deployments."
            )
        if self.foundry_general_agent is not None:
            general = self.foundry_general_agent
            if (
                general.journey_id is not None
                or not general.model_deployment
                or any(binding.name == general.name for binding in self.foundry_agents)
            ):
                raise ValueError(
                    "FOUNDRY_GENERAL_AGENT must pin a distinct general agent and model "
                    "deployment without a journey scope."
                )
        if self.foundry_contextual_agent is not None:
            contextual = self.foundry_contextual_agent
            reserved_names = {binding.name for binding in self.foundry_agents} | (
                {self.foundry_general_agent.name}
                if self.foundry_general_agent is not None
                else set()
            )
            if self.foundry_agent_name:
                reserved_names.add(self.foundry_agent_name)
            if (
                contextual.journey_id is not None
                or not contextual.model_deployment
                or contextual.name in reserved_names
            ):
                raise ValueError(
                    "FOUNDRY_CONTEXTUAL_AGENT must pin a distinct contextual-demo agent "
                    "and model deployment without a journey scope."
                )
        return self

    @model_validator(mode="after")
    def reviewed_metadata_index(self) -> Self:
        selected = self.azure_search_index == "bc-pilot-public-v2"
        if any(
            (
                selected,
                self.azure_search_metadata_enabled,
                self.azure_search_metadata_reviewed,
            )
        ) and not all(
            (
                selected,
                self.azure_search_metadata_enabled,
                self.azure_search_metadata_reviewed,
            )
        ):
            raise ValueError(
                "The metadata-aware index, metadata mode and reviewed-schema flag "
                "must be enabled together."
            )
        return self

    @model_validator(mode="after")
    def bounded_synthetic_context(self) -> Self:
        if self.synthetic_context_consent_ttl_seconds > self.synthetic_context_session_ttl_seconds:
            raise ValueError("Synthetic context consent cannot outlive its server-owned session.")
        return self

    @field_validator("foundry_project_endpoint")
    @classmethod
    def foundry_url(cls, value: str) -> str:
        return azure_endpoint(value, service="foundry") if value else ""

    @field_validator("azure_search_endpoint")
    @classmethod
    def search_url(cls, value: str) -> str:
        return azure_endpoint(value, service="search") if value else ""

    @field_validator("azure_openai_endpoint")
    @classmethod
    def embedding_url(cls, value: str) -> str:
        return azure_endpoint(value, service="embedding") if value else ""

    @property
    def hybrid_configured(self) -> bool:
        return not self.azure_search_vector_enabled or bool(
            self.azure_openai_endpoint
            and self.azure_openai_embedding_deployment
            and self.azure_openai_embedding_dimensions
        )

    @property
    def run_token_reservation(self) -> int:
        return (
            self.api_model_input_byte_budget
            + self.api_model_calls_per_run * self.api_model_output_tokens
            + 8192
        )

    @property
    def production_controls_ready(self) -> bool:
        return bool(
            self.redis_endpoint
            and self.api_auth_tenant_id
            and self.api_auth_audience
            and self.api_auth_callers
            and self.api_daily_run_limit
            and self.api_daily_token_limit
            and self.api_daily_cost_limit_microusd
            and self.api_token_price_microusd
        )

    @property
    def catalog_path(self) -> Path:
        return self.content_catalog_path or default_catalog_path()

    @property
    def origins(self) -> tuple[str, ...]:
        raw = self.api_allowed_origins
        if not raw and self.app_env == "development":
            raw = "http://localhost:3000,http://127.0.0.1:3000"
        origins = tuple(origin.strip() for origin in raw.split(",") if origin.strip())
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                "*" in origin
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path
                or parsed.scheme not in ("http", "https")
                or (self.app_env == "production" and parsed.scheme != "https")
            ):
                raise ValueError("Configure exact trusted web origins; production requires HTTPS.")
        return origins

    @property
    def foundry_configured(self) -> bool:
        return all(
            (
                self.foundry_project_endpoint,
                self.foundry_agents
                or (
                    self.app_env == "development"
                    and self.foundry_agent_name
                    and self.foundry_agent_version
                ),
                self.azure_search_endpoint,
                self.azure_search_index,
            )
        )

    @property
    def general_agent_configured(self) -> bool:
        return bool(self.foundry_project_endpoint and self.foundry_general_agent)

    @property
    def contextual_agent_configured(self) -> bool:
        return bool(
            self.synthetic_context_enabled
            and self.foundry_project_endpoint
            and self.foundry_contextual_agent
            and self.search_configured
        )

    @property
    def search_configured(self) -> bool:
        return bool(self.azure_search_endpoint and self.azure_search_index)
