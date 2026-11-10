"""Public, per-answer research contracts; never conversation or personal-context storage."""

import re
from typing import Annotated, Literal
from urllib.parse import unquote, urlsplit

from pydantic import AwareDatetime, Field, model_validator

from bc_api.models import (
    Identifier,
    JourneyId,
    OfficialUrl,
    SourceReference,
    WireModel,
)
from bc_api.urls import PUBLIC_RESEARCH_HOSTS, https_url

ResearchAction = Literal["corpus-explore", "web-check"]
Geography = Literal[
    "british-columbia", "vancouver", "victoria", "kelowna", "kamloops", "prince-george"
]
RESEARCH_PAGE_HEADER = "x-bc-research-page"


class WebResearchPermission(WireModel):
    source_id: Identifier
    url_prefix: OfficialUrl
    quote_limit: int = Field(default=200, strict=True, ge=1, le=200)

    @model_validator(mode="after")
    def bounded_destination(self):
        parsed = urlsplit(self.url_prefix)
        if (
            parsed.hostname not in PUBLIC_RESEARCH_HOSTS
            or parsed.query
            or parsed.fragment
            or any(part in (".", "..") for part in unquote(parsed.path).split("/"))
        ):
            raise ValueError("Research permission requires a reviewed official host and path.")
        return self

    def allows(self, url: str) -> bool:
        try:
            https_url(url)
        except ValueError:
            return False
        parsed, allowed = urlsplit(url), urlsplit(self.url_prefix)
        path = parsed.path
        for _ in range(3):
            path = unquote(path)
        prefix = unquote(allowed.path).rstrip("/")
        return (
            parsed.netloc == allowed.netloc
            and not parsed.query
            and not parsed.fragment
            and not any(part in (".", "..") for part in path.split("/"))
            and (path == prefix or path.startswith(prefix + "/"))
        )


class ResearchRequest(WireModel):
    version: Literal[1]
    action: ResearchAction
    run_id: Identifier
    thread_id: Identifier
    parent_run_id: Identifier
    parent_message_id: Identifier
    geography: Geography = "british-columbia"

    @model_validator(mode="after")
    def cancellable_identifiers(self):
        if any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", value) for value in (
            self.run_id, self.thread_id, self.parent_run_id,
        )):
            raise ValueError("Research identifiers must support the run cancellation contract.")
        return self


class ResearchDescriptor(WireModel):
    page_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    thread_id: Identifier
    parent_message_id: Identifier
    topics: list[JourneyId] = Field(min_length=1, max_length=3)
    source_ids: list[Identifier] = Field(min_length=1, max_length=30)
    expires_at: AwareDatetime


class ResearchOffer(WireModel):
    version: Literal[1] = 1
    parent_run_id: Identifier
    parent_message_id: Identifier
    thread_id: Identifier
    topics: list[JourneyId] = Field(min_length=1, max_length=3)
    actions: list[ResearchAction] = Field(min_length=1, max_length=2)
    expires_at: AwareDatetime


class IndexedResearchReference(WireModel):
    kind: Literal["indexed"] = "indexed"
    reference: SourceReference
    retrieved_at: AwareDatetime

    @property
    def url(self) -> str:
        return self.reference.url


class WebResearchReference(WireModel):
    kind: Literal["web"] = "web"
    source_id: Identifier
    title: str = Field(min_length=1, max_length=500)
    publisher: str = Field(min_length=1, max_length=500)
    url: OfficialUrl
    retrieved_at: AwareDatetime
    crawled_at: AwareDatetime | None = None
    publisher_updated_at: AwareDatetime | None = None
    method: Literal["search", "browse"]
    human_reviewed: Literal[False] = False
    quote_limit: int = Field(default=200, strict=True, ge=1, le=200)


ResearchReference = Annotated[
    IndexedResearchReference | WebResearchReference, Field(discriminator="kind")
]


class ResearchEvidence(WireModel):
    reference: ResearchReference
    content: str = Field(min_length=1, max_length=8000)

    @model_validator(mode="after")
    def bounded_passage(self):
        if self.reference.kind == "web" and len(self.content) > 3000:
            raise ValueError("Web research requires a bounded passage.")
        return self


class ResearchResult(WireModel):
    version: Literal[1] = 1
    action: ResearchAction
    run_id: Identifier
    parent_run_id: Identifier
    parent_message_id: Identifier
    text: str = Field(min_length=1, max_length=12000)
    citations: list[ResearchReference] = Field(min_length=1, max_length=5)
    notice: str = Field(max_length=600)

    @model_validator(mode="after")
    def matching_provenance(self):
        kind = "web" if self.action == "web-check" else "indexed"
        if any(reference.kind != kind for reference in self.citations):
            raise ValueError("Research evidence must match the explicitly chosen provider.")
        return self
