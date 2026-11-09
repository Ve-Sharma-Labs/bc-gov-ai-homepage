"""Bounded provider responses without redirects, automatic retries or body logging."""

import json

import httpx

from bc_api.errors import ApiError


async def provider_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    token: str,
    body: dict | None = None,
    pending: bool = False,
) -> tuple[int, dict]:
    try:
        async with client.stream(
            method,
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {token}", "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
            follow_redirects=False,
        ) as response:
            if response.status_code not in ((200, 202) if pending else (200,)):
                raise ApiError(
                    502,
                    "RESEARCH_PROVIDER_UNAVAILABLE",
                    "The research provider returned an incomplete or unavailable result.",
                )
            content = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=16384):
                content.extend(chunk)
                if len(content) > 131072:
                    raise ApiError(502, "RESEARCH_LIMIT", "Research exceeded its response limit.")
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError("Expected an object.")
            return response.status_code, data
    except httpx.TimeoutException:
        raise ApiError(504, "RESEARCH_TIMEOUT", "Optional research timed out.") from None
    except httpx.HTTPError, ValueError, UnicodeError:
        raise ApiError(
            502, "RESEARCH_RESPONSE_INVALID", "The research response could not be verified."
        ) from None
