"""Validate candidate coverage blueprints; this module grants no acquisition or publication."""

import argparse
import json
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from bc_api.config import default_catalog_path
from bc_api.conversation_grounding import PROGRAMMES, AnswerTopic, ProgrammeId
from bc_api.models import Identifier, OfficialUrl, WireModel, require_unique


class CandidateSource(WireModel):
    id: Identifier
    source_id: Identifier
    url: OfficialUrl
    topics: list[AnswerTopic] = Field(min_length=1, max_length=14)


class GroundingPack(WireModel):
    id: Literal["licence", "ei", "guardianship", "disability"]
    programmes: list[ProgrammeId] = Field(min_length=1, max_length=2)
    required_topics: list[AnswerTopic] = Field(min_length=1, max_length=14)
    rights_state: Literal["publisher-permission-required", "use-classification-review-required"]
    rights_review: None
    publication_review: None
    policy_references: list[OfficialUrl] = Field(min_length=1, max_length=5)
    gap: str = Field(min_length=1, max_length=1000)
    sources: list[CandidateSource] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def scoped_blueprint(self) -> Self:
        require_unique(self.programmes, "Pack programmes")
        require_unique(self.required_topics, "Required topics")
        require_unique([source.id for source in self.sources], "Candidate source IDs")
        topics = {
            topic for programme in self.programmes for topic in PROGRAMMES[programme].allowed_topics
        }
        if not set(self.required_topics) <= topics:
            raise ValueError("Required topics must belong to the pack's programmes.")
        for source in self.sources:
            require_unique(source.topics, "Candidate topics")
            if not set(source.topics) <= topics:
                raise ValueError("Candidate topics must belong to the pack's programmes.")
        allowed = {key for programme in self.programmes for key in PROGRAMMES[programme].source_ids}
        if any(source.source_id not in allowed for source in self.sources):
            raise ValueError("A candidate source must belong to this programme's source scope.")
        return self


class GroundingPacks(WireModel):
    version: Literal[1]
    purpose: Literal["grounded-conversation"]
    publication_policy: Literal["exact-hash-human-review"]
    contains_source_content: Literal[False]
    packs: list[GroundingPack] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def complete_programme_inventory(self) -> Self:
        require_unique([pack.id for pack in self.packs], "Pack IDs")
        programmes = [programme for pack in self.packs for programme in pack.programmes]
        require_unique(programmes, "Programme ownership")
        if set(programmes) != set(PROGRAMMES):
            raise ValueError("The candidate inventory must cover every declared programme.")
        return self

    def coverage(self) -> list[dict]:
        result = []
        for pack in self.packs:
            for programme in pack.programmes:
                supported = set(PROGRAMMES[programme].allowed_topics)
                required = set(pack.required_topics) & supported
                represented = {
                    topic
                    for source in pack.sources
                    if source.source_id in PROGRAMMES[programme].source_ids
                    for topic in source.topics
                }
                result.append(
                    {
                        "programmeId": programme,
                        "title": PROGRAMMES[programme].title,
                        "status": "blocked",
                        "rightsState": pack.rights_state,
                        "publicationApproved": False,
                        "missingCandidateTopics": sorted(required - represented),
                        "reason": pack.gap,
                    }
                )
        return result


def load_grounding_packs(path: Path | None = None) -> GroundingPacks:
    selected = path or default_catalog_path().parent / "conversation-grounding-packs.json"
    if selected.stat().st_size > 100_000:
        raise ValueError("Grounding blueprint exceeds the metadata size limit.")
    return GroundingPacks.model_validate_json(selected.read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path)
    arguments = parser.parse_args()
    print(
        json.dumps(
            {"candidateOnly": True, "coverage": load_grounding_packs(arguments.path).coverage()},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
