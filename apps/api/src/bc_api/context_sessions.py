"""Opaque, bounded synthetic-context session metadata repositories."""

import asyncio
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol, cast

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.auth.err import RequestTokenErr
from redis.exceptions import RedisError

from bc_api.demo_personas import PERSONA_IDS
from bc_api.errors import ApiError
from bc_api.models import ConsentReceipt, ConsentScope, DemoPersonaId

CONTEXT_COOKIE = "bc_synthetic_context"
CONTEXT_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")
CONTEXT_PAGE_HEADER = "x-bc-context-page"
CONTEXT_PAGE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{19,127}$")
NOTICE_VERSION = "synthetic-context-v1"

_STATE_FIELDS = {
    "revision",
    "persona_id",
    "expires_at",
    "consent_id",
    "purpose",
    "scopes",
    "subject_hash",
    "notice_version",
    "granted_at",
    "consent_expires_at",
    "revoked_at",
}

_CREATE_SCRIPT = """
local t = redis.call('TIME')
local now = tonumber(t[1])
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', now)
if redis.call('EXISTS', KEYS[2]) == 1 then return -2 end
local replaced = 0
if ARGV[1] ~= '' then
  replaced = redis.call('EXISTS', KEYS[1])
  redis.call('DEL', KEYS[1])
  redis.call('ZREM', KEYS[3], ARGV[1])
end
if redis.call('ZCARD', KEYS[3]) >= tonumber(ARGV[3]) then return -1 end
redis.call('HSET', KEYS[2],
  'revision', '0',
  'persona_id', ARGV[4],
  'expires_at', ARGV[5],
  'consent_id', '',
  'purpose', '',
  'scopes', '',
  'subject_hash', '',
  'notice_version', '',
  'granted_at', '',
  'consent_expires_at', '',
  'revoked_at', '')
redis.call('EXPIREAT', KEYS[2], tonumber(ARGV[6]))
redis.call('ZADD', KEYS[3], tonumber(ARGV[6]), ARGV[2])
return replaced
"""

_SAVE_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 0 then return -1 end
if redis.call('HGET', KEYS[1], 'revision') ~= ARGV[1] then return 0 end
if redis.call('HGET', KEYS[1], 'persona_id') ~= ARGV[3]
  or redis.call('HGET', KEYS[1], 'expires_at') ~= ARGV[4] then return -2 end
redis.call('HSET', KEYS[1],
  'revision', ARGV[2],
  'persona_id', ARGV[3],
  'expires_at', ARGV[4],
  'consent_id', ARGV[5],
  'purpose', ARGV[6],
  'scopes', ARGV[7],
  'subject_hash', ARGV[8],
  'notice_version', ARGV[9],
  'granted_at', ARGV[10],
  'consent_expires_at', ARGV[11],
  'revoked_at', ARGV[12])
redis.call('EXPIREAT', KEYS[1], tonumber(ARGV[13]))
return 1
"""

_DELETE_SCRIPT = """
local removed = redis.call('DEL', KEYS[1])
redis.call('ZREM', KEYS[2], ARGV[1])
return removed
"""


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed.astimezone(UTC).replace(microsecond=0)


def context_session_ref(owner_token: str, context_token: str | None) -> str | None:
    if context_token is None or not CONTEXT_TOKEN.fullmatch(context_token):
        return None
    return hashlib.sha256(f"{owner_token}.{context_token}".encode()).hexdigest()


def bound_context_owner(owner_token: str, page_token: str | None) -> str | None:
    """Bind a durable anonymous session to one in-memory browser page instance."""

    if page_token is None or not CONTEXT_PAGE_TOKEN.fullmatch(page_token):
        return None
    return hashlib.sha256(f"{owner_token}.{page_token}".encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class StoredConsent:
    consent_id: str
    purpose: str
    scopes: tuple[ConsentScope, ...]
    subject_hash: str
    notice_version: str
    granted_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    def active(self, now: datetime) -> bool:
        return self.revoked_at is None and self.granted_at <= now < self.expires_at

    def receipt(self) -> ConsentReceipt:
        return ConsentReceipt(
            consent_id=self.consent_id,
            purpose=self.purpose,
            scopes=list(self.scopes),
            subject_hash=self.subject_hash,
            notice_version=self.notice_version,
            granted_at=_iso(self.granted_at),
            expires_at=_iso(self.expires_at),
            revoked_at=_iso(self.revoked_at) if self.revoked_at is not None else None,
        )


@dataclass(frozen=True, slots=True)
class ContextSessionState:
    revision: int
    persona_id: DemoPersonaId
    expires_at: datetime
    consent: StoredConsent | None = None


@dataclass(frozen=True, slots=True)
class CreatedContextSession:
    token: str
    state: ContextSessionState
    replaced: bool


SaveResult = Literal["saved", "conflict", "missing"]


class ContextSessionRepository(Protocol):
    async def create(
        self,
        owner_token: str,
        previous_token: str | None,
        persona_id: DemoPersonaId,
        *,
        now: datetime,
        expires_at: datetime,
    ) -> CreatedContextSession: ...

    async def get(
        self,
        owner_token: str,
        context_token: str | None,
        *,
        now: datetime,
    ) -> ContextSessionState | None: ...

    async def save(
        self,
        owner_token: str,
        context_token: str,
        *,
        expected_revision: int,
        state: ContextSessionState,
        now: datetime,
    ) -> SaveResult: ...

    async def delete(self, owner_token: str, context_token: str | None) -> bool: ...


class InMemoryContextSessionRepository:
    """Single-process preview repository with atomic compare-and-set updates."""

    def __init__(self, max_sessions: int) -> None:
        self.max_sessions = max_sessions
        self._states: dict[str, ContextSessionState] = {}
        self._lock = asyncio.Lock()

    def _purge(self, now: datetime) -> None:
        self._states = {
            key: state for key, state in self._states.items() if state.expires_at > now
        }

    async def create(
        self,
        owner_token: str,
        previous_token: str | None,
        persona_id: DemoPersonaId,
        *,
        now: datetime,
        expires_at: datetime,
    ) -> CreatedContextSession:
        old_ref = context_session_ref(owner_token, previous_token)
        async with self._lock:
            self._purge(now)
            replaced = old_ref is not None and self._states.pop(old_ref, None) is not None
            if len(self._states) >= self.max_sessions:
                raise ApiError(
                    429,
                    "SESSION_LIMIT",
                    "The local preview is busy. Please try again later.",
                )
            for _ in range(3):
                token = secrets.token_urlsafe(32)
                ref = context_session_ref(owner_token, token)
                if ref is not None and ref not in self._states:
                    state = ContextSessionState(
                        revision=0,
                        persona_id=persona_id,
                        expires_at=expires_at,
                    )
                    self._states[ref] = state
                    return CreatedContextSession(token=token, state=state, replaced=replaced)
        raise ApiError(
            503,
            "CONTEXT_STORE_UNAVAILABLE",
            "Synthetic context session creation is unavailable.",
        )

    async def get(
        self,
        owner_token: str,
        context_token: str | None,
        *,
        now: datetime,
    ) -> ContextSessionState | None:
        ref = context_session_ref(owner_token, context_token)
        if ref is None:
            return None
        async with self._lock:
            self._purge(now)
            return self._states.get(ref)

    async def save(
        self,
        owner_token: str,
        context_token: str,
        *,
        expected_revision: int,
        state: ContextSessionState,
        now: datetime,
    ) -> SaveResult:
        ref = context_session_ref(owner_token, context_token)
        if ref is None:
            return "missing"
        async with self._lock:
            self._purge(now)
            current = self._states.get(ref)
            if current is None:
                return "missing"
            if current.revision != expected_revision:
                return "conflict"
            if (
                state.revision != expected_revision + 1
                or state.persona_id != current.persona_id
                or state.expires_at != current.expires_at
            ):
                raise ValueError("Context session immutable fields cannot change.")
            self._states[ref] = state
            return "saved"

    async def delete(self, owner_token: str, context_token: str | None) -> bool:
        ref = context_session_ref(owner_token, context_token)
        if ref is None:
            return False
        async with self._lock:
            return self._states.pop(ref, None) is not None


class RedisContextSessionRepository:
    """Replica-safe metadata repository backed by the existing shared-control Redis."""

    def __init__(self, client: Redis, prefix: str, max_sessions: int) -> None:
        self.client = client
        self.prefix = prefix
        self.max_sessions = max_sessions

    def _key(self, ref: str) -> str:
        return self.prefix + "context-session:" + ref

    @property
    def _index_key(self) -> str:
        return self.prefix + "context-sessions"

    async def _eval(self, script: str, keys: list[str], *args: object) -> object:
        try:
            async with asyncio.timeout(5):
                return await self.client.eval(script, len(keys), *keys, *args)
        except (RedisError, RequestTokenErr, TimeoutError):
            raise ApiError(
                503,
                "CONTEXT_STORE_UNAVAILABLE",
                "Synthetic context controls are unavailable. Please try again later.",
            ) from None

    async def create(
        self,
        owner_token: str,
        previous_token: str | None,
        persona_id: DemoPersonaId,
        *,
        now: datetime,
        expires_at: datetime,
    ) -> CreatedContextSession:
        del now
        old_ref = context_session_ref(owner_token, previous_token)
        old_key = self._key(old_ref or "unused")
        for _ in range(3):
            token = secrets.token_urlsafe(32)
            ref = context_session_ref(owner_token, token)
            if ref is None:
                continue
            result = await self._eval(
                _CREATE_SCRIPT,
                [old_key, self._key(ref), self._index_key],
                old_ref or "",
                ref,
                self.max_sessions,
                persona_id,
                _iso(expires_at),
                int(expires_at.timestamp()),
            )
            if result == -2:
                continue
            if result == -1:
                raise ApiError(
                    429,
                    "SESSION_LIMIT",
                    "The assistant is busy. Please try again later.",
                )
            if result not in (0, 1):
                raise ApiError(
                    503,
                    "CONTEXT_STORE_UNAVAILABLE",
                    "Synthetic context session creation could not be verified.",
                )
            state = ContextSessionState(
                revision=0,
                persona_id=persona_id,
                expires_at=expires_at,
            )
            return CreatedContextSession(token=token, state=state, replaced=result == 1)
        raise ApiError(
            503,
            "CONTEXT_STORE_UNAVAILABLE",
            "Synthetic context session creation is unavailable.",
        )

    async def get(
        self,
        owner_token: str,
        context_token: str | None,
        *,
        now: datetime,
    ) -> ContextSessionState | None:
        ref = context_session_ref(owner_token, context_token)
        if ref is None:
            return None
        try:
            async with asyncio.timeout(5):
                values = await self.client.hgetall(self._key(ref))
        except (RedisError, RequestTokenErr, TimeoutError):
            raise ApiError(
                503,
                "CONTEXT_STORE_UNAVAILABLE",
                "Synthetic context controls are unavailable. Please try again later.",
            ) from None
        if not values:
            return None
        try:
            state = _parse_state(values)
        except (TypeError, ValueError, ValidationError, json.JSONDecodeError):
            await self.delete(owner_token, context_token)
            raise ApiError(
                503,
                "CONTEXT_STORE_UNAVAILABLE",
                "Synthetic context session metadata could not be verified.",
            ) from None
        if state.expires_at <= now:
            await self.delete(owner_token, context_token)
            return None
        return state

    async def save(
        self,
        owner_token: str,
        context_token: str,
        *,
        expected_revision: int,
        state: ContextSessionState,
        now: datetime,
    ) -> SaveResult:
        del now
        ref = context_session_ref(owner_token, context_token)
        if ref is None:
            return "missing"
        consent = state.consent
        if consent is None:
            consent_values: tuple[object, ...] = ("", "", "", "", "", "", "", "")
        else:
            consent_values = (
                consent.consent_id,
                consent.purpose,
                json.dumps(list(consent.scopes), separators=(",", ":")),
                consent.subject_hash,
                consent.notice_version,
                _iso(consent.granted_at),
                _iso(consent.expires_at),
                _iso(consent.revoked_at) if consent.revoked_at is not None else "",
            )
        result = await self._eval(
            _SAVE_SCRIPT,
            [self._key(ref)],
            expected_revision,
            state.revision,
            state.persona_id,
            _iso(state.expires_at),
            *consent_values,
            int(state.expires_at.timestamp()),
        )
        if result == 1:
            return "saved"
        if result == 0:
            return "conflict"
        if result == -1:
            return "missing"
        raise ApiError(
            503,
            "CONTEXT_STORE_UNAVAILABLE",
            "Synthetic context session metadata could not be verified.",
        )

    async def delete(self, owner_token: str, context_token: str | None) -> bool:
        ref = context_session_ref(owner_token, context_token)
        if ref is None:
            return False
        result = await self._eval(
            _DELETE_SCRIPT,
            [self._key(ref), self._index_key],
            ref,
        )
        if result not in (0, 1):
            raise ApiError(
                503,
                "CONTEXT_STORE_UNAVAILABLE",
                "Synthetic context session cleanup could not be verified.",
            )
        return result == 1


def _parse_state(values: dict[str, str]) -> ContextSessionState:
    if set(values) != _STATE_FIELDS:
        raise ValueError("invalid state fields")
    revision = int(values["revision"])
    if revision < 0 or values["persona_id"] not in PERSONA_IDS:
        raise ValueError("invalid state identity")
    expires_at = _datetime(values["expires_at"])
    consent_id = values["consent_id"]
    if not consent_id:
        if any(
            values[field]
            for field in (
                "purpose",
                "scopes",
                "subject_hash",
                "notice_version",
                "granted_at",
                "consent_expires_at",
                "revoked_at",
            )
        ):
            raise ValueError("incomplete empty consent")
        consent = None
    else:
        scopes = json.loads(values["scopes"])
        receipt = ConsentReceipt.model_validate(
            {
                "consentId": consent_id,
                "purpose": values["purpose"],
                "scopes": scopes,
                "subjectHash": values["subject_hash"],
                "noticeVersion": values["notice_version"],
                "grantedAt": values["granted_at"],
                "expiresAt": values["consent_expires_at"],
                "revokedAt": values["revoked_at"] or None,
            }
        )
        consent = StoredConsent(
            consent_id=receipt.consent_id,
            purpose=receipt.purpose,
            scopes=tuple(cast(list[ConsentScope], receipt.scopes)),
            subject_hash=receipt.subject_hash,
            notice_version=receipt.notice_version,
            granted_at=_datetime(receipt.granted_at),
            expires_at=_datetime(receipt.expires_at),
            revoked_at=_datetime(receipt.revoked_at) if receipt.revoked_at else None,
        )
    return ContextSessionState(
        revision=revision,
        persona_id=cast(DemoPersonaId, values["persona_id"]),
        expires_at=expires_at,
        consent=consent,
    )
