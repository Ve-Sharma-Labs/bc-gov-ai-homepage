"""Page-bound, expiring discovery state with replica-safe compare-and-set."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field, ValidationError
from redis.asyncio import Redis
from redis.auth.err import RequestTokenErr
from redis.exceptions import RedisError

from bc_api.context_sessions import bound_context_owner
from bc_api.errors import ApiError
from bc_api.models import DiscoveryGoalId, DiscoverySummary, Identifier, PageSummary, WireModel

DISCOVERY_PAGE_HEADER = "x-bc-discovery-page"


class PageState(WireModel):
    summary: PageSummary


class StoredDiscovery(PageState):
    summary: DiscoverySummary
    counts: dict[DiscoveryGoalId, Annotated[int, Field(ge=0, le=3)]] = Field(
        default_factory=dict, max_length=11
    )
    previous_revision: Annotated[int, Field(ge=0)]
    input_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    reply: Annotated[str, Field(max_length=8000)] | None = None
    public_query: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    reply_kind: Literal["dialogue", "handoff"] = "dialogue"
    run_id: Identifier


_SAVE = """
local current = redis.call('GET', KEYS[1])
if current then
  local decoded = cjson.decode(current)
  if decoded.closed or decoded.summary.revision ~= tonumber(ARGV[1]) then return 0 end
elseif tonumber(ARGV[1]) ~= 0 then return 0 end
local now = tonumber(redis.call('TIME')[1])
if tonumber(ARGV[3]) <= now then return 0 end
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now)
if not current and redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[4]) then return -1 end
redis.call('SET', KEYS[1], ARGV[2], 'EXAT', ARGV[3])
redis.call('ZADD', KEYS[2], ARGV[3], ARGV[5])
return 1
"""

_CLOSE = """
local current = redis.call('GET', KEYS[1])
if current then
  local expiry = redis.call('TTL', KEYS[1])
  if expiry > 0 then
    redis.call('SET', KEYS[1], '{"closed":true}', 'EX', expiry)
    return 1
  end
end
local now = tonumber(redis.call('TIME')[1])
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now)
if redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[1]) then return -1 end
redis.call('SET', KEYS[1], '{"closed":true}', 'EX', ARGV[2])
redis.call('ZADD', KEYS[2], now + tonumber(ARGV[2]), ARGV[3])
return 1
"""


def discovery_ref(owner: str, page: str | None) -> str:
    bound = bound_context_owner(owner, page)
    if bound is None:
        raise ApiError(
            422, "DISCOVERY_PAGE_REQUIRED", "Start a new conversation in this browser page."
        )
    return hashlib.sha256(f"discovery:{bound}".encode()).hexdigest()


def _expiry(state: PageState) -> float:
    return datetime.fromisoformat(state.summary.expires_at.replace("Z", "+00:00")).timestamp()


def _unavailable() -> ApiError:
    return ApiError(
        503,
        "DISCOVERY_UNAVAILABLE",
        "Your conversation context couldn't be updated. Please try again or start over.",
    )


class PageStateStore[StateT: PageState]:
    def __init__(
        self,
        max_sessions: int,
        *,
        state_type: type[StateT],
        redis: Redis | None = None,
        prefix: str = "bc-pilot",
        ttl_seconds: int = 1800,
        namespace: str = "discovery",
    ) -> None:
        self.max_sessions = max_sessions
        self.redis = redis
        self.prefix = f"{prefix}:{namespace}"
        self.state_type = state_type
        self.ttl_seconds = ttl_seconds
        self._states: dict[str, tuple[float, StateT | None]] = {}
        self._lock = asyncio.Lock()

    def _purge(self) -> None:
        now = datetime.now(UTC).timestamp()
        self._states = {key: value for key, value in self._states.items() if value[0] > now}

    async def get(self, ref: str) -> StateT | None:
        if self.redis is not None:
            try:
                raw = await self.redis.get(f"{self.prefix}:{ref}")
                if raw is None:
                    return None
                data = json.loads(raw)
                if data == {"closed": True}:
                    raise ApiError(
                        410, "DISCOVERY_EXPIRED", "This context was cleared. Start over."
                    )
                state = self.state_type.model_validate(data)
                return state if _expiry(state) > datetime.now(UTC).timestamp() else None
            except RedisError, RequestTokenErr, ValueError, TypeError, ValidationError:
                raise _unavailable() from None
        async with self._lock:
            self._purge()
            stored = self._states.get(ref)
            if stored is None:
                return None
            if stored[1] is None:
                raise ApiError(410, "DISCOVERY_EXPIRED", "This context was cleared. Start over.")
            return stored[1].model_copy(deep=True)

    async def save(self, ref: str, expected_revision: int, state: StateT) -> bool:
        if state.summary.revision != expected_revision + 1:
            raise ValueError("A discovery transition advances exactly one revision.")
        if self.redis is not None:
            try:
                result = await self.redis.eval(
                    _SAVE,
                    2,
                    f"{self.prefix}:{ref}",
                    f"{self.prefix}:sessions",
                    expected_revision,
                    state.model_dump_json(by_alias=True),
                    int(_expiry(state)),
                    self.max_sessions,
                    ref,
                )
                if result == -1:
                    raise ApiError(429, "SESSION_LIMIT", "The preview is busy. Please try again.")
                return result == 1
            except RedisError, RequestTokenErr:
                raise _unavailable() from None
        async with self._lock:
            self._purge()
            previous = self._states.get(ref)
            if previous is not None and previous[1] is None:
                return False
            revision = previous[1].summary.revision if previous and previous[1] else 0
            if revision != expected_revision or _expiry(state) <= datetime.now(UTC).timestamp():
                return False
            if previous is None and len(self._states) >= self.max_sessions:
                raise ApiError(429, "SESSION_LIMIT", "The preview is busy. Please try again.")
            self._states[ref] = (_expiry(state), state.model_copy(deep=True))
            return True

    async def clear(self, ref: str) -> None:
        # A tombstone prevents an already-running request from recreating cleared context.
        if self.redis is not None:
            try:
                result = await self.redis.eval(
                    _CLOSE,
                    2,
                    f"{self.prefix}:{ref}",
                    f"{self.prefix}:sessions",
                    self.max_sessions,
                    self.ttl_seconds,
                    ref,
                )
                if result == -1:
                    raise ApiError(429, "SESSION_LIMIT", "The preview is busy. Please try again.")
                return
            except RedisError, RequestTokenErr:
                raise _unavailable() from None
        async with self._lock:
            self._purge()
            previous = self._states.get(ref)
            if previous is not None:
                self._states[ref] = (previous[0], None)
            else:
                if len(self._states) >= self.max_sessions:
                    raise ApiError(429, "SESSION_LIMIT", "The preview is busy. Please try again.")
                self._states[ref] = (datetime.now(UTC).timestamp() + self.ttl_seconds, None)


class DiscoveryStore(PageStateStore[StoredDiscovery]):
    def __init__(
        self,
        max_sessions: int,
        *,
        redis: Redis | None = None,
        prefix: str = "bc-pilot",
        ttl_seconds: int = 1800,
    ) -> None:
        super().__init__(
            max_sessions,
            state_type=StoredDiscovery,
            redis=redis,
            prefix=prefix,
            ttl_seconds=ttl_seconds,
        )
