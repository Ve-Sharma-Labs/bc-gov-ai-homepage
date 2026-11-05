"""Explicit metrics only: never auto-instrument prompts, HTTP bodies or tool results."""

import json
import logging
import time
from datetime import UTC, datetime

from bc_api.config import Settings
from bc_api.models import SourceHealth
from bc_api.security import Run

PHASES = frozenset(
    {
        "admitted",
        "readiness_started",
        "readiness_completed",
        "retrieval_started",
        "retrieval_completed",
        "model_started",
        "first_model_text",
    }
)


class Telemetry:
    def __init__(self, settings: Settings):
        self.provider = None
        self.credential = None
        self.duration = None
        self.first_content = None
        self.runs = None
        self.tokens = None
        self.phases = None
        self.source_checks = None
        self.source_documents = None
        self.source_expiry = None
        self.logger = logging.getLogger("bc_api.operations")
        if not self.logger.handlers:
            self.logger.addHandler(logging.StreamHandler())
        self.logger.propagate = False
        self.logger.setLevel(logging.INFO)
        if not settings.api_metrics_enabled:
            return
        if not settings.applicationinsights_connection_string:
            raise ValueError(
                "Metrics export requires the approved Application Insights connection."
            )
        from azure.identity import AzureCliCredential, ManagedIdentityCredential
        from azure.monitor.opentelemetry.exporter import AzureMonitorMetricExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource

        self.credential = (
            ManagedIdentityCredential(client_id=settings.azure_client_id)
            if settings.app_env == "production"
            else AzureCliCredential(process_timeout=settings.azure_cli_process_timeout_seconds)
        )
        exporter = AzureMonitorMetricExporter(
            connection_string=settings.applicationinsights_connection_string,
            credential=self.credential,
            disable_offline_storage=True,
        )
        self.provider = MeterProvider(
            resource=Resource(
                {
                    "service.name": "bc-service-assistant",
                    "service.namespace": settings.api_control_namespace,
                }
            ),
            metric_readers=[PeriodicExportingMetricReader(exporter)],
        )
        meter = self.provider.get_meter("bc_api", "1")
        self.duration = meter.create_histogram("bc.run.duration", unit="ms")
        self.first_content = meter.create_histogram("bc.run.first_validated_content", unit="ms")
        self.runs = meter.create_counter("bc.run.count")
        self.tokens = meter.create_counter("bc.run.tokens")
        self.phases = meter.create_histogram("bc.run.phase_elapsed", unit="ms")
        self.source_checks = meter.create_counter("bc.sources.checks")
        self.source_documents = meter.create_histogram("bc.sources.usable_documents")
        self.source_expiry = meter.create_histogram("bc.sources.hours_to_expiry", unit="h")

    def sources(self, health: SourceHealth) -> None:
        event = {"event": "bc.sources.checked", **health.model_dump(mode="json", by_alias=True)}
        level = logging.INFO if health.status == "ready" else logging.WARNING
        self.logger.log(level, json.dumps(event))
        attributes = {"status": health.status, "error.code": health.error_code or "none"}
        if self.source_checks is not None:
            self.source_checks.add(1, attributes)
            self.source_documents.record(health.usable_documents, attributes)
            if health.next_expiry_at is not None:
                hours = (
                    datetime.fromisoformat(health.next_expiry_at) - datetime.now(UTC)
                ).total_seconds() / 3600
                self.source_expiry.record(max(0, hours), attributes)

    def finish(self, run: Run) -> None:
        duration = max(0, (time.monotonic() - run.created) * 1000)
        first = (
            (run.first_content_at - run.created) * 1000
            if run.first_content_at is not None
            else None
        )
        event = {
            "event": "bc.run.completed",
            "traceRef": run.trace_ref,
            "status": run.status,
            "durationMs": round(duration),
            "firstValidatedContentMs": round(first) if first is not None else None,
            "responseKind": run.response_kind,
            "responseOrigin": run.response_origin,
            "firstResponseMs": (
                round(max(0, (run.first_response_at - run.created) * 1000))
                if run.first_response_at is not None
                else None
            ),
            "phasesMs": {
                phase: round(max(0, (at - run.created) * 1000))
                for phase, at in run.phase_times.items()
                if phase in PHASES
            },
        }
        self.logger.info(json.dumps(event))
        attributes = {
            "outcome": run.status,
            "response.kind": run.response_kind or "none",
            "response.origin": run.response_origin or "none",
        }
        if self.runs is not None:
            self.runs.add(1, attributes)
            self.duration.record(duration, attributes)
            if first is not None:
                self.first_content.record(first, attributes)
            if run.usage_tokens is not None and run.usage_valid:
                self.tokens.add(run.usage_tokens, attributes)
            for phase, elapsed in event["phasesMs"].items():
                self.phases.record(elapsed, {**attributes, "phase": phase})

    def close(self) -> None:
        if self.provider is not None:
            self.provider.shutdown()
        if self.credential is not None:
            self.credential.close()
