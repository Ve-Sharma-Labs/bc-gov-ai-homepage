"""Value-free, bounded audit storage for synthetic contextual sessions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from pydantic import Field, ValidationError, model_validator
from redis.asyncio import Redis
from redis.auth.err import RequestTokenErr
from redis.exceptions import RedisError

from bc_api.errors import ApiError
from bc_api.models import (
    AuditAction,
    AuditOutcome,
    ConsentScope,
    ContextAuditTool,
    ContextCategory,
    ContextFlowId,
    DemoPersonaId,
    IsoDateTime,
    ProgramSourceVersion,
    WireModel,
)

AUDIT_TELEMETRY_FIELDS = frozenset(
    {
        "event",
        "eventId",
        "occurredAt",
        "sequence",
        "traceRef",
        "runRef",
        "sessionRef",
        "subjectRef",
        "personaId",
        "consentId",
        "consentScopes",
        "actorLabel",
        "tool",
        "action",
        "flowId",
        "ruleSetVersion",
        "ruleId",
        "ruleVersion",
        "sourceVersions",
        "category",
        "outcome",
        "errorCode",
    }
)

_APPEND_SCRIPT = """
local t = redis.call('TIME')
local now = tonumber(t[1])
local expires_at = tonumber(ARGV[4])
if expires_at <= now then return {-2, 0} end
if redis.call('EXISTS', KEYS[1]) == 0 then
  redis.call('HSET', KEYS[1],
    'expires_at', ARGV[4],
    'count', '0',
    'bytes', '0',
    'sequence', '0')
else
  if redis.call('HGET', KEYS[1], 'expires_at') ~= ARGV[4] then return {-3, 0} end
end
local idempotency_field = 'idem:' .. ARGV[1]
local existing = redis.call('HGET', KEYS[1], idempotency_field)
if existing then return {0, tonumber(existing)} end
local count = tonumber(redis.call('HGET', KEYS[1], 'count'))
local bytes = tonumber(redis.call('HGET', KEYS[1], 'bytes'))
local payload_bytes = tonumber(ARGV[7])
if count >= tonumber(ARGV[5]) or bytes + payload_bytes > tonumber(ARGV[6]) then
  return {-1, 0}
end
local sequence = redis.call('HINCRBY', KEYS[1], 'sequence', 1)
redis.call('RPUSH', KEYS[2], tostring(sequence) .. '\t' .. ARGV[2])
redis.call('HINCRBY', KEYS[1], 'count', 1)
redis.call('HINCRBY', KEYS[1], 'bytes', payload_bytes)
redis.call('HSET', KEYS[1], idempotency_field, tostring(sequence))
redis.call('EXPIREAT', KEYS[1], expires_at)
redis.call('EXPIREAT', KEYS[2], expires_at)
return {1, sequence}
"""

_CLEAR_SCRIPT = """
return redis.call('DEL', KEYS[1], KEYS[2])
"""


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _event_id(session_ref: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"{session_ref}\x1f{idempotency_key}".encode()).hexdigest()
    return "evt-" + digest[:32]


def audit_run_ref(run_id: str) -> str:
    """Hash a caller-provided run ID before it reaches audit storage."""

    return hashlib.sha256(f"context-run\x1f{run_id}".encode()).hexdigest()


class ContextAuditRecord(WireModel):
    occurred_at: IsoDateTime
    trace_ref: str | None = Field(
        default=None,
        min_length=16,
        max_length=128,
        pattern=r"^[a-f0-9]+$",
    )
    run_ref: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    session_ref: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    subject_ref: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    persona_id: DemoPersonaId
    consent_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$",
    )
    consent_scopes: list[ConsentScope] = Field(default_factory=list, max_length=6)
    actor_label: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:@-]*$",
    )
    tool: ContextAuditTool | None = None
    action: AuditAction
    flow_id: ContextFlowId | None = None
    rule_set_version: str | None = Field(
        default=None,
        max_length=100,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$",
    )
    rule_id: str | None = Field(
        default=None,
        max_length=100,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$",
    )
    rule_version: str | None = Field(
        default=None,
        max_length=100,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$",
    )
    source_versions: list[ProgramSourceVersion] = Field(default_factory=list, max_length=20)
    category: ContextCategory | None = None
    outcome: AuditOutcome
    error_code: str | None = Field(
        default=None,
        max_length=80,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )

    @model_validator(mode="after")
    def coherent_value_free_event(self):
        if self.subject_ref != self.session_ref:
            raise ValueError("Synthetic audit subjects must use the bound session reference.")
        if len(self.consent_scopes) != len(set(self.consent_scopes)):
            raise ValueError("Audit consent scopes must be unique.")
        source_ids = [item.source_id for item in self.source_versions]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Audit source versions must be unique.")
        if self.action == "context-category-accessed" and self.category is None:
            raise ValueError("Context access audit events require a category.")
        if self.action == "rule-evaluated" and (
            self.rule_id is None
            or self.rule_version is None
            or self.rule_set_version is None
            or not self.source_versions
        ):
            raise ValueError("Rule audit events require pinned rule and source versions.")
        if self.action == "preview-generated" and self.flow_id is None:
            raise ValueError("Preview audit events require a flow.")
        if self.action == "access-denied" and self.error_code is None:
            raise ValueError("Denied audit events require an error code.")
        if self.action == "context-run-completed" and (
            self.trace_ref is None or self.run_ref is None
        ):
            raise ValueError("Run completion audit events require opaque run and trace references.")
        return self


class ContextAuditEvent(ContextAuditRecord):
    event_id: str = Field(pattern=r"^evt-[a-f0-9]{32}$")
    sequence: int = Field(ge=1)


@dataclass(frozen=True, slots=True)
class AuditAppendResult:
    event: ContextAuditEvent
    inserted: bool


class ContextAuditRepository(Protocol):
    async def append(
        self,
        record: ContextAuditRecord,
        *,
        expires_at: datetime,
        idempotency_key: str,
        now: datetime,
    ) -> AuditAppendResult: ...

    async def events(
        self,
        session_ref: str,
        *,
        now: datetime,
    ) -> tuple[ContextAuditEvent, ...]: ...

    async def clear(self, session_ref: str) -> None: ...


@dataclass(slots=True)
class _AuditBucket:
    expires_at: datetime
    events: list[ContextAuditEvent]
    bytes_used: int
    idempotency: dict[str, int]


class InMemoryContextAuditRepository:
    """Single-process audit storage with strict count, byte, and expiry bounds."""

    def __init__(self, max_events: int, max_bytes: int) -> None:
        self.max_events = max_events
        self.max_bytes = max_bytes
        self._buckets: dict[str, _AuditBucket] = {}
        self._lock = asyncio.Lock()

    def _purge(self, now: datetime) -> None:
        self._buckets = {
            key: bucket
            for key, bucket in self._buckets.items()
            if bucket.expires_at > now
        }

    async def append(
        self,
        record: ContextAuditRecord,
        *,
        expires_at: datetime,
        idempotency_key: str,
        now: datetime,
    ) -> AuditAppendResult:
        if expires_at <= now:
            raise ApiError(
                409,
                "CONTEXT_SESSION_EXPIRED",
                "The synthetic context session is no longer active.",
            )
        event_id = _event_id(record.session_ref, idempotency_key)
        payload = record.model_dump(mode="json", by_alias=True)
        payload["eventId"] = event_id
        payload_bytes = len(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        )
        key = hashlib.sha256(idempotency_key.encode()).hexdigest()
        async with self._lock:
            self._purge(now)
            bucket = self._buckets.get(record.session_ref)
            if bucket is None:
                bucket = _AuditBucket(expires_at, [], 0, {})
                self._buckets[record.session_ref] = bucket
            elif bucket.expires_at != expires_at:
                raise ApiError(
                    503,
                    "AUDIT_STORE_UNAVAILABLE",
                    "Context audit retention could not be verified.",
                )
            sequence = bucket.idempotency.get(key)
            if sequence is not None:
                return AuditAppendResult(bucket.events[sequence - 1], False)
            if (
                len(bucket.events) >= self.max_events
                or bucket.bytes_used + payload_bytes > self.max_bytes
            ):
                raise ApiError(
                    503,
                    "AUDIT_LIMIT_REACHED",
                    "The bounded context audit trail is full for this session.",
                )
            event = ContextAuditEvent.model_validate(
                {
                    **payload,
                    "sequence": len(bucket.events) + 1,
                }
            )
            bucket.events.append(event)
            bucket.bytes_used += payload_bytes
            bucket.idempotency[key] = event.sequence
            return AuditAppendResult(event, True)

    async def events(
        self,
        session_ref: str,
        *,
        now: datetime,
    ) -> tuple[ContextAuditEvent, ...]:
        async with self._lock:
            self._purge(now)
            bucket = self._buckets.get(session_ref)
            return tuple(bucket.events) if bucket is not None else ()

    async def clear(self, session_ref: str) -> None:
        async with self._lock:
            self._buckets.pop(session_ref, None)


class RedisContextAuditRepository:
    """Replica-safe audit storage using the existing shared-control Redis."""

    def __init__(self, client: Redis, prefix: str, max_events: int, max_bytes: int) -> None:
        self.client = client
        self.prefix = prefix
        self.max_events = max_events
        self.max_bytes = max_bytes

    def _meta_key(self, session_ref: str) -> str:
        return self.prefix + "context-audit:" + session_ref

    def _events_key(self, session_ref: str) -> str:
        return self.prefix + "context-audit-events:" + session_ref

    async def _eval(self, script: str, keys: list[str], *args: object) -> object:
        try:
            async with asyncio.timeout(5):
                return await self.client.eval(script, len(keys), *keys, *args)
        except (RedisError, RequestTokenErr, TimeoutError):
            raise ApiError(
                503,
                "AUDIT_STORE_UNAVAILABLE",
                "Context audit controls are unavailable. Please try again later.",
            ) from None

    async def append(
        self,
        record: ContextAuditRecord,
        *,
        expires_at: datetime,
        idempotency_key: str,
        now: datetime,
    ) -> AuditAppendResult:
        del now
        event_id = _event_id(record.session_ref, idempotency_key)
        payload = record.model_dump(mode="json", by_alias=True)
        payload["eventId"] = event_id
        serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        idempotency_ref = hashlib.sha256(idempotency_key.encode()).hexdigest()
        result = await self._eval(
            _APPEND_SCRIPT,
            [self._meta_key(record.session_ref), self._events_key(record.session_ref)],
            idempotency_ref,
            serialized,
            hashlib.sha256(serialized.encode()).hexdigest(),
            int(expires_at.timestamp()),
            self.max_events,
            self.max_bytes,
            len(serialized.encode()),
        )
        if not isinstance(result, list) or len(result) != 2:
            raise ApiError(
                503,
                "AUDIT_STORE_UNAVAILABLE",
                "Context audit storage could not be verified.",
            )
        inserted = int(result[0])
        sequence = int(result[1])
        if inserted == -1:
            raise ApiError(
                503,
                "AUDIT_LIMIT_REACHED",
                "The bounded context audit trail is full for this session.",
            )
        if inserted == -2:
            raise ApiError(
                409,
                "CONTEXT_SESSION_EXPIRED",
                "The synthetic context session is no longer active.",
            )
        if inserted == -3 or inserted not in (0, 1) or sequence < 1:
            raise ApiError(
                503,
                "AUDIT_STORE_UNAVAILABLE",
                "Context audit retention could not be verified.",
            )
        event = ContextAuditEvent.model_validate({**payload, "sequence": sequence})
        return AuditAppendResult(event, inserted == 1)

    async def events(
        self,
        session_ref: str,
        *,
        now: datetime,
    ) -> tuple[ContextAuditEvent, ...]:
        try:
            async with asyncio.timeout(5):
                meta, entries = await asyncio.gather(
                    self.client.hgetall(self._meta_key(session_ref)),
                    self.client.lrange(self._events_key(session_ref), 0, self.max_events),
                )
        except (RedisError, RequestTokenErr, TimeoutError):
            raise ApiError(
                503,
                "AUDIT_STORE_UNAVAILABLE",
                "Context audit controls are unavailable. Please try again later.",
            ) from None
        if not meta and not entries:
            return ()
        try:
            expires_at = datetime.fromtimestamp(int(meta["expires_at"]), UTC)
            if expires_at <= now:
                await self.clear(session_ref)
                return ()
            count = int(meta["count"])
            bytes_used = int(meta["bytes"])
            if (
                count != len(entries)
                or count > self.max_events
                or bytes_used > self.max_bytes
            ):
                raise ValueError("invalid audit bounds")
            events: list[ContextAuditEvent] = []
            observed_bytes = 0
            for expected, entry in enumerate(entries, start=1):
                sequence_text, serialized = entry.split("\t", 1)
                sequence = int(sequence_text)
                if sequence != expected:
                    raise ValueError("invalid audit ordering")
                observed_bytes += len(serialized.encode())
                events.append(
                    ContextAuditEvent.model_validate(
                        {
                            **json.loads(serialized),
                            "sequence": sequence,
                        }
                    )
                )
            if observed_bytes != bytes_used:
                raise ValueError("invalid audit size")
            return tuple(events)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, ValidationError):
            await self.clear(session_ref)
            raise ApiError(
                503,
                "AUDIT_STORE_UNAVAILABLE",
                "Context audit storage could not be verified.",
            ) from None

    async def clear(self, session_ref: str) -> None:
        result = await self._eval(
            _CLEAR_SCRIPT,
            [self._meta_key(session_ref), self._events_key(session_ref)],
        )
        if not isinstance(result, int) or result not in (0, 1, 2):
            raise ApiError(
                503,
                "AUDIT_STORE_UNAVAILABLE",
                "Context audit cleanup could not be verified.",
            )


class ContextAuditTrail:
    """Persist strict events and emit only an explicit telemetry allowlist."""

    def __init__(
        self,
        repository: ContextAuditRepository,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self.repository = repository
        self.logger = logger or logging.getLogger("bc_api.context_audit")
        if not self.logger.handlers:
            self.logger.addHandler(logging.StreamHandler())
        self.logger.propagate = False
        self.logger.setLevel(logging.INFO)
        self._ephemeral: set[str] = set()
        self._ephemeral_lock = asyncio.Lock()

    @staticmethod
    def _telemetry(event: ContextAuditEvent) -> dict[str, object]:
        payload: dict[str, object] = {
            "event": "bc.context.audit",
            "eventId": event.event_id,
            "occurredAt": event.occurred_at,
            "sequence": event.sequence,
            "traceRef": event.trace_ref,
            "runRef": event.run_ref,
            "sessionRef": event.session_ref,
            "subjectRef": event.subject_ref,
            "personaId": event.persona_id,
            "consentId": event.consent_id,
            "consentScopes": event.consent_scopes,
            "actorLabel": event.actor_label,
            "tool": event.tool,
            "action": event.action,
            "flowId": event.flow_id,
            "ruleSetVersion": event.rule_set_version,
            "ruleId": event.rule_id,
            "ruleVersion": event.rule_version,
            "sourceVersions": [
                item.model_dump(mode="json", by_alias=True) for item in event.source_versions
            ],
            "category": event.category,
            "outcome": event.outcome,
            "errorCode": event.error_code,
        }
        return {key: value for key, value in payload.items() if value is not None}

    def _log(self, event: ContextAuditEvent) -> None:
        payload = self._telemetry(event)
        if not set(payload) <= AUDIT_TELEMETRY_FIELDS:
            raise RuntimeError("Context audit telemetry exceeded its field allowlist.")
        self.logger.info(json.dumps(payload, separators=(",", ":"), sort_keys=True))

    async def append(
        self,
        record: ContextAuditRecord,
        *,
        expires_at: datetime,
        idempotency_key: str,
        now: datetime,
    ) -> ContextAuditEvent:
        result = await self.repository.append(
            record,
            expires_at=expires_at,
            idempotency_key=idempotency_key,
            now=now,
        )
        if result.inserted:
            self._log(result.event)
        return result.event

    async def emit_unstored(
        self,
        record: ContextAuditRecord,
        *,
        idempotency_key: str,
    ) -> None:
        """Log a terminal event after its owning session was already cleared."""

        event_id = _event_id(record.session_ref, idempotency_key)
        async with self._ephemeral_lock:
            if event_id in self._ephemeral:
                return
            if len(self._ephemeral) >= 4096:
                self._ephemeral.clear()
            self._ephemeral.add(event_id)
        event = ContextAuditEvent.model_validate(
            {
                **record.model_dump(mode="json", by_alias=True),
                "eventId": event_id,
                "sequence": 1,
            }
        )
        self._log(event)

    async def events(
        self,
        session_ref: str,
        *,
        now: datetime,
    ) -> tuple[ContextAuditEvent, ...]:
        return await self.repository.events(session_ref, now=now)

    async def clear(self, session_ref: str) -> None:
        await self.repository.clear(session_ref)


def audit_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def new_trace_ref() -> str:
    return secrets.token_hex(16)
