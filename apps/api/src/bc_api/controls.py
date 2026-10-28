"""Atomic, transient admission and cancellation shared by API replicas."""

import asyncio
import hashlib
import re
import secrets
import time
from urllib.parse import urlsplit

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.auth.err import RequestTokenErr
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis_entraid.cred_provider import create_from_managed_identity
from redis_entraid.identity_provider import ManagedIdentityIdType, ManagedIdentityType

from bc_api.config import Settings
from bc_api.errors import ApiError
from bc_api.security import Run, Session

SESSION_SCRIPT = """
local t = redis.call('TIME')
local now = tonumber(t[1])
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now)
local existing = redis.call('EXISTS', KEYS[1])
if existing == 0 and ARGV[3] == '0' then return -1 end
if existing == 0 and redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[2]) then return -2 end
redis.call('SET', KEYS[1], '1', 'EX', 3600)
redis.call('ZADD', KEYS[2], now + 3600, ARGV[1])
return existing
"""

RATE_SCRIPT = """
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now - 60)
if redis.call('EXISTS', KEYS[1]) == 0 and redis.call('ZCARD', KEYS[2]) >= 4096 then return 0 end
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - 60)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then return 0 end
redis.call('ZADD', KEYS[1], now, ARGV[2])
redis.call('EXPIRE', KEYS[1], 60)
redis.call('ZADD', KEYS[2], now, KEYS[1])
return 1
"""

RESERVE_SCRIPT = """
local t = redis.call('TIME')
local now = tonumber(t[1])
local day = math.floor(now / 86400)
if redis.call('EXISTS', KEYS[1]) == 1 then return -1 end
if redis.call('EXISTS', KEYS[5]) == 0 then return -5 end
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now)
if redis.call('EXISTS', KEYS[3]) == 1 then return -2 end
if redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[4]) then return -3 end
local billable = ARGV[10] ~= '0'
if billable and redis.call('HGET', KEYS[4], 'blocked') == '1' then return -4 end
if tonumber(redis.call('HGET', KEYS[4], 'day') or '-1') ~= day then
  redis.call('HSET', KEYS[4], 'day', day, 'runs', 0, 'tokens', 0, 'cost', 0)
end
local tokens = billable and tonumber(ARGV[5]) or 0
local price = billable and tonumber(ARGV[9]) or 0
local cost = tokens * price
if billable then
if tonumber(ARGV[6]) <= 0 or tonumber(ARGV[7]) <= 0
  or tonumber(ARGV[8]) <= 0 or price <= 0 then return -4 end
if tonumber(redis.call('HGET', KEYS[4], 'runs')) + 1 > tonumber(ARGV[6])
  or tonumber(redis.call('HGET', KEYS[4], 'tokens')) + tokens > tonumber(ARGV[7])
  or tonumber(redis.call('HGET', KEYS[4], 'cost')) + cost > tonumber(ARGV[8]) then return -4 end
redis.call('HINCRBY', KEYS[4], 'runs', 1)
redis.call('HINCRBY', KEYS[4], 'tokens', tokens)
redis.call('HINCRBY', KEYS[4], 'cost', cost)
end
redis.call('HSET', KEYS[1], 'owner', ARGV[1], 'status', 'running', 'cancel', 0,
  'day', day, 'reserved', tokens, 'price', price)
redis.call('EXPIRE', KEYS[1], 600)
redis.call('SET', KEYS[3], ARGV[2], 'EX', ARGV[3])
redis.call('ZADD', KEYS[2], now + tonumber(ARGV[3]), ARGV[2])
return 1
"""

CANCEL_SCRIPT = """
if redis.call('HGET', KEYS[1], 'owner') ~= ARGV[1] then return -1 end
local status = redis.call('HGET', KEYS[1], 'status')
if status == 'finished' or status == 'failed' then return -2 end
if status == 'cancelled' then return 1 end
redis.call('HSET', KEYS[1], 'cancel', 1)
return 2
"""

FINISH_SCRIPT = """
if redis.call('HGET', KEYS[1], 'owner') ~= ARGV[1] then return 'missing' end
local previous = redis.call('HGET', KEYS[1], 'status')
if previous ~= 'running' then return previous end
local status = ARGV[3]
if status == 'not-started' then status = 'failed' end
if redis.call('HGET', KEYS[1], 'cancel') == '1' then status = 'cancelled' end
local reserved = tonumber(redis.call('HGET', KEYS[1], 'reserved'))
local price = tonumber(redis.call('HGET', KEYS[1], 'price'))
local charged = tonumber(ARGV[4])
if ARGV[3] == 'not-started' then charged = 0
elseif status ~= 'finished' or charged < 0 then charged = reserved end
if charged > reserved then redis.call('HSET', KEYS[4], 'blocked', 1) end
if redis.call('HGET', KEYS[4], 'day') == redis.call('HGET', KEYS[1], 'day') then
  redis.call('HINCRBY', KEYS[4], 'tokens', charged - reserved)
  redis.call('HINCRBY', KEYS[4], 'cost', (charged - reserved) * price)
end
redis.call('HSET', KEYS[1], 'status', status, 'charged', charged)
redis.call('EXPIRE', KEYS[1], 600)
redis.call('ZREM', KEYS[2], ARGV[2])
if redis.call('GET', KEYS[3]) == ARGV[2] then redis.call('DEL', KEYS[3]) end
return status
"""


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SharedControls:
    def __init__(self, settings: Settings, *, client: Redis | None = None):
        self.settings = settings
        self.prefix = f"bc:{{{settings.api_control_namespace}}}:"
        if client is not None:
            self.client = client
            return
        endpoint = urlsplit(settings.redis_endpoint)
        if (
            endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
            or endpoint.path not in ("", "/")
        ):
            raise ValueError("Redis endpoints must not contain credentials or extra components.")
        local = (
            settings.app_env == "development"
            and endpoint.scheme == "redis"
            and endpoint.hostname in ("127.0.0.1", "localhost", "::1")
        )
        if not local and (
            endpoint.scheme != "rediss"
            or not endpoint.hostname
            or not endpoint.hostname.endswith(".redis.azure.net")
        ):
            raise ValueError(
                "Use a TLS Azure Managed Redis endpoint, or loopback Redis in development."
            )
        options = {
            "host": endpoint.hostname,
            "port": endpoint.port or (6379 if local else 10000),
            "decode_responses": True,
            "socket_connect_timeout": 2,
            "socket_timeout": 2,
            "retry": Retry(NoBackoff(), 0),
        }
        if not local:
            provider = create_from_managed_identity(
                identity_type=(
                    ManagedIdentityType.USER_ASSIGNED
                    if settings.redis_client_id
                    else ManagedIdentityType.SYSTEM_ASSIGNED
                ),
                resource="https://redis.azure.com",
                id_type=ManagedIdentityIdType.CLIENT_ID if settings.redis_client_id else None,
                id_value=settings.redis_client_id or "",
            )
            options.update(
                ssl=True,
                ssl_cert_reqs="required",
                ssl_check_hostname=True,
                credential_provider=provider,
            )
        self.client = Redis(**options)

    async def _eval(self, script: str, keys: list[str], *args):
        try:
            async with asyncio.timeout(5):
                return await self.client.eval(script, len(keys), *keys, *args)
        except RedisError, RequestTokenErr, TimeoutError:
            raise ApiError(
                503,
                "CONTROL_STORE_UNAVAILABLE",
                "The assistant cannot verify its request controls. Please try later.",
            ) from None

    async def session(self, token: str | None, *, create: bool = True) -> tuple[Session, bool]:
        if token and re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            owner = token_hash(token)
            existing = await self._eval(
                SESSION_SCRIPT,
                [self.prefix + "session:" + owner, self.prefix + "sessions"],
                owner,
                self.settings.api_max_sessions,
                0,
            )
            if existing == 1:
                return Session(token, time.monotonic()), False
        if not create:
            raise ApiError(404, "RUN_NOT_FOUND", "No cancellable run was found for this session.")
        token = secrets.token_urlsafe(32)
        owner = token_hash(token)
        created = await self._eval(
            SESSION_SCRIPT,
            [self.prefix + "session:" + owner, self.prefix + "sessions"],
            owner,
            self.settings.api_max_sessions,
            1,
        )
        if created < 0:
            raise ApiError(429, "SESSION_LIMIT", "The assistant is busy. Please try again later.")
        return Session(token, time.monotonic()), True

    async def check_rate(self, key: str, limit: int) -> None:
        result = await self._eval(
            RATE_SCRIPT,
            [self.prefix + "rate:" + key, self.prefix + "rates"],
            limit,
            secrets.token_hex(16),
        )
        if result != 1:
            raise ApiError(
                429, "RATE_LIMITED", "Too many requests. Please wait before trying again."
            )

    async def reserve(
        self, run_id: str, thread_id: str, token: str, *, model_work: bool = True
    ) -> Run:
        owner = token_hash(token)
        run_key = self.prefix + "run:" + run_id
        keys = [
            run_key,
            self.prefix + "active",
            self.prefix + "owner:" + owner,
            self.prefix + "budget",
            self.prefix + "session:" + owner,
        ]
        lease = int(
            self.settings.api_run_timeout_seconds + self.settings.api_upstream_timeout_seconds + 30
        )
        result = await self._eval(
            RESERVE_SCRIPT,
            keys,
            owner,
            run_id,
            lease,
            self.settings.api_max_concurrent_runs,
            self.settings.run_token_reservation,
            self.settings.api_daily_run_limit,
            self.settings.api_daily_token_limit,
            self.settings.api_daily_cost_limit_microusd,
            self.settings.api_token_price_microusd,
            int(model_work),
        )
        errors = {
            -1: (409, "RUN_CONFLICT", "Use a new run identifier for each request."),
            -2: (409, "SESSION_BUSY", "Stop the current response before starting another."),
            -3: (429, "RUN_LIMIT", "The assistant is busy. Please try again shortly."),
            -5: (
                409,
                "SESSION_EXPIRED",
                "Refresh the connection before submitting another question.",
            ),
        }
        if result == -4:
            retry_after = max(1, int(86400 - (time.time() % 86400)))
            raise ApiError(
                429,
                "BUDGET_EXHAUSTED",
                "The pilot has reached its daily processing allowance. "
                "Guided plans remain available.",
                retry_after,
            )
        if result in errors:
            raise ApiError(*errors[result])
        if result != 1:
            raise ApiError(
                503, "CONTROL_STORE_UNAVAILABLE", "Request admission could not be verified."
            )
        run = Run(run_id, thread_id, owner)

        async def finish(status: str, usage: int | None) -> str:
            result = await self._eval(
                FINISH_SCRIPT,
                keys[:4],
                owner,
                run_id,
                status,
                usage if status == "finished" and usage is not None else -1,
            )
            if result not in ("finished", "failed", "cancelled"):
                raise ApiError(
                    503, "CONTROL_STORE_UNAVAILABLE", "Run completion could not be recorded."
                )
            return result

        async def watch() -> None:
            while run.status == "running":
                try:
                    async with asyncio.timeout(5):
                        state = await self.client.hmget(run_key, "owner", "cancel", "status")
                    if state[0] != owner:
                        raise ApiError(503, "CONTROL_STORE_UNAVAILABLE", "Run ownership expired.")
                    if state[1] == "1" or state[2] != "running":
                        run.cancellation.set()
                        return
                except RedisError, RequestTokenErr, TimeoutError:
                    run.control_failure = ApiError(
                        503, "CONTROL_STORE_UNAVAILABLE", "Request controls became unavailable."
                    )
                    run.cancellation.set()
                    return
                except ApiError as exc:
                    run.control_failure = exc
                    run.cancellation.set()
                    return
                await asyncio.sleep(0.25)

        run.finish = finish
        run.watch = watch
        return run

    async def cancel(self, run_id: str, token: str) -> str:
        result = await self._eval(CANCEL_SCRIPT, [self.prefix + "run:" + run_id], token_hash(token))
        if result == -1:
            raise ApiError(404, "RUN_NOT_FOUND", "No cancellable run was found for this session.")
        if result == -2:
            raise ApiError(409, "RUN_FINISHED", "That response has already ended.")
        if result not in (1, 2):
            raise ApiError(503, "CONTROL_STORE_UNAVAILABLE", "Cancellation could not be verified.")
        return "cancelled" if result == 1 else "cancelling"

    async def cancellation_requested(self, run_id: str) -> bool:
        result = await self._eval(
            "return redis.call('HGET', KEYS[1], 'cancel')",
            [self.prefix + "run:" + run_id],
        )
        return result == "1"

    async def close(self) -> None:
        await self.client.aclose()
