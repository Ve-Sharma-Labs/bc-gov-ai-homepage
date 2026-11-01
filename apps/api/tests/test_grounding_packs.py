import pytest
from pydantic import ValidationError

from bc_api.conversation_grounding import PROGRAMMES
from bc_api.grounding_packs import GroundingPacks, load_grounding_packs
from bc_api.urls import official_url, validate_public_destination


def test_blueprints_are_not_an_acquisition_or_publication_approval():
    packs = load_grounding_packs()
    coverage = packs.coverage()
    assert {item["programmeId"] for item in coverage} == set(PROGRAMMES)
    assert all(item["status"] == "blocked" and not item["publicationApproved"] for item in coverage)
    assert packs.contains_source_content is False
    assert all(
        pack.rights_review is None and pack.publication_review is None for pack in packs.packs
    )


def test_blueprint_cannot_be_promoted_by_adding_a_fake_approval():
    data = load_grounding_packs().model_dump(by_alias=True)
    data["packs"][0]["rightsReview"] = {"approved": True, "reviewer": "agent"}
    with pytest.raises(ValidationError):
        GroundingPacks.model_validate(data)


def test_child_coverage_does_not_borrow_adult_pgt_material():
    child = next(
        item
        for item in load_grounding_packs().coverage()
        if item["programmeId"] == "guardianship-child"
    )
    assert "application" in child["missingCandidateTopics"]
    assert "contact" in child["missingCandidateTopics"]


def test_required_topics_cannot_be_silently_removed_by_a_scope_mismatch():
    data = load_grounding_packs().model_dump(by_alias=True)
    data["packs"][0]["requiredTopics"].append("professional-sections")
    with pytest.raises(ValidationError, match="Required topics"):
        GroundingPacks.model_validate(data)


async def test_official_link_permission_is_not_fetch_permission():
    url = "https://www.canada.ca/en/services/benefits/ei/ei-regular-benefit.html"
    assert official_url(url) == url
    with pytest.raises(ValueError, match="outside the approved scope"):
        await validate_public_destination(url)
    with pytest.raises(ValueError):
        official_url("https://canada.ca.evil.example/ei")
