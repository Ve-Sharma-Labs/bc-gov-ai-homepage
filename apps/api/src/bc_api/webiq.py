"""Opt-in, transient public research. This transport never fetches a publisher directly."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

import httpx
from azure.core.credentials_async import AsyncTokenCredential
from pydantic import ValidationError

from bc_api.catalog import CatalogRepository
from bc_api.config import Settings
from bc_api.errors import ApiError
from bc_api.research import require_research, research_query
from bc_api.research_contract import ResearchDescriptor, ResearchEvidence, WebResearchReference
from bc_api.research_http import provider_json
from bc_api.retrieval import INJECTION_MARKERS


def provider_date(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Invalid provider timestamp.")
    parsed = datetime.fromisoformat(value)
    # A missing timezone is unknown, not permission to invent one.
    return parsed if parsed.tzinfo is not None else None


class WebIQ:
    def __init__(
        self,
        settings: Settings,
        catalog: CatalogRepository,
        credential: AsyncTokenCredential,
        client: httpx.AsyncClient,
    ):
        self.settings, self.catalog = settings, catalog
        self.credential, self.client = credential, client
        self.attempts = 0

    async def retrieve(
        self,
        descriptor: ResearchDescriptor,
        geography: str,
        authorize: Callable[[], Awaitable[None]],
        mark_started: Callable[[], None],
    ) -> list[ResearchEvidence]:
        require_research(self.settings, "web-check")
        sources = {
            source.id: source
            for source in self.catalog.get().sources
            if source.id in descriptor.source_ids and source.status in ("available", "limited")
        }
        permissions = [
            permission
            for permission in self.settings.webiq_sources
            if permission.source_id in sources
            and urlsplit(permission.url_prefix).hostname
            == urlsplit(sources[permission.source_id].url).hostname
        ]
        if not permissions:
            raise ApiError(
                503, "RESEARCH_SOURCE_GAP", "No public pages are approved for this topic."
            )
        query = research_query(descriptor, geography)
        token = (await self.credential.get_token("https://api.microsoft.ai/.default")).token
        deadline = time.monotonic() + self.settings.api_upstream_timeout_seconds

        async def request(path: str, body: dict, *, retry_pending: bool = False) -> dict:
            await authorize()
            if self.attempts >= 3:
                raise ApiError(
                    502, "RESEARCH_LIMIT", "The public research request limit was reached."
                )
            self.attempts += 1
            mark_started()
            status, data = await provider_json(
                self.client,
                "POST",
                "https://api.microsoft.ai/v3/"
                + path
                + "?APPID="
                + quote(self.settings.webiq_app_id, safe=""),
                token=token,
                body=body,
                pending=path == "browse",
            )
            if status == 202:
                try:
                    retry = provider_date(data.get("retryAfter"))
                except ValueError:
                    retry = None
                delay = (retry - datetime.now(UTC)).total_seconds() if retry else -1
                if (
                    retry_pending
                    or delay < 0
                    or delay >= deadline - time.monotonic()
                    or self.attempts >= 3
                    or data.get("url") not in (None, body.get("url"))
                ):
                    raise ApiError(
                        503,
                        "WEBIQ_PENDING",
                        "The page is not available within this research request. "
                        "Open the official page.",
                    )
                await asyncio.sleep(delay)
                return await request(path, body, retry_pending=True)
            return data

        known_urls = [
            handoff.url
            for topic in descriptor.topics
            for handoff in self.catalog.journey(topic).handoffs
            if any(permission.allows(handoff.url) for permission in permissions)
        ]
        method = "search"
        if (
            len(descriptor.topics) == 1
            and known_urls
            and self.settings.webiq_browse_source_identity_approved
        ):
            method = "browse"
            data = await request(
                "browse",
                {
                    "url": known_urls[0],
                    "query": query,
                    "contentFormat": "passage",
                    "maxLength": 3000,
                    "liveCrawl": "fallback",
                },
            )
            if data.get("url") != known_urls[0]:
                raise ApiError(
                    502, "WEBIQ_SOURCE_CHANGED", "The page source could not be verified."
                )
            rows = [data]
        else:
            hosts = sorted({urlsplit(permission.url_prefix).hostname for permission in permissions})
            query += " (" + " OR ".join(f"site:{host}" for host in hosts) + ")"
            if len(query) > 1000:
                raise ApiError(422, "RESEARCH_SCOPE_LIMIT", "Choose a narrower public topic.")
            data = await request(
                "search/web",
                {
                    "query": query,
                    "contentFormat": "passage",
                    "maxResults": 5,
                    "maxLength": 3000,
                    "safeSearch": "strict",
                },
            )
            rows = data.get("webResults", [])
        await authorize()
        if not isinstance(rows, list) or len(rows) > 5:
            raise ApiError(
                502, "WEBIQ_RESPONSE_INVALID", "Public research exceeded its result limit."
            )
        evidence = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ApiError(502, "WEBIQ_RESPONSE_INVALID", "Invalid public research evidence.")
            url = row.get("url")
            permission = next(
                (item for item in permissions if isinstance(url, str) and item.allows(url)), None
            )
            if permission is None or url in seen or row.get("isAdult") is True:
                continue
            content = row.get("content")
            title = row.get("title")
            if (
                not isinstance(content, str)
                or not content.strip()
                or not isinstance(title, str)
                or not title.strip()
            ):
                continue
            if INJECTION_MARKERS.search(content) or INJECTION_MARKERS.search(title):
                raise ApiError(
                    502, "SOURCE_CONTENT_REJECTED", "Untrusted source instructions were withheld."
                )
            try:
                evidence.append(
                    ResearchEvidence(
                        reference=WebResearchReference(
                            source_id=permission.source_id,
                            url=url,
                            title=sources[permission.source_id].title,
                            publisher=sources[permission.source_id].publisher,
                            retrieved_at=datetime.now(UTC),
                            crawled_at=provider_date(row.get("crawledAt")),
                            publisher_updated_at=provider_date(row.get("lastUpdatedAt")),
                            method=method,
                            quote_limit=permission.quote_limit,
                        ),
                        content=content,
                    )
                )
            except ValueError, ValidationError:
                raise ApiError(
                    502, "WEBIQ_RESPONSE_INVALID", "Public evidence metadata could not be verified."
                ) from None
            seen.add(url)
        if not evidence:
            raise ApiError(
                503,
                "RESEARCH_SOURCE_GAP",
                "No permitted public evidence was returned. "
                "Use the original answer or official page.",
            )
        return evidence
