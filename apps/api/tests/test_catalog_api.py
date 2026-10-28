import copy
import json

import pytest
from pydantic import ValidationError

from bc_api.catalog import CatalogRepository
from bc_api.config import Settings, default_catalog_path
from bc_api.models import JOURNEY_IDS, Catalog, GuidedPlan


def test_real_catalog_contract():
    catalog = CatalogRepository(default_catalog_path()).get()
    assert {journey.id for journey in catalog.journeys} == JOURNEY_IDS
    assert len(catalog.sources) == 12
    assert len(catalog.locations) == 7
    road_test = next(item for item in catalog.journeys if item.id == "road-test-booking")
    pharmacare = next(
        item for item in catalog.journeys if item.id == "pharmacare-registration"
    )
    assert road_test.handoffs[0].url.endswith("/Book-a-road-test")
    assert "cannot authenticate, book" in road_test.notice
    assert pharmacare.handoffs[0].url.endswith("/fair-pharmacare-plan")
    assert "PHNs, SINs and tax information" in pharmacare.notice
    assert all(not plan.transactions_enabled for plan in (
        CatalogRepository(default_catalog_path()).plan("road-test-booking"),
        CatalogRepository(default_catalog_path()).plan("pharmacare-registration"),
    ))


def test_health_and_catalog_are_honest(client, catalog_data):
    assert client.get("/healthz").json() == {"status": "ok"}
    result = client.get("/api/catalog")
    assert result.status_code == 200
    assert result.json() == catalog_data
    assert result.headers["cache-control"] == "no-store"
    assert result.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("journey_id", sorted(JOURNEY_IDS))
def test_seven_journeys(client, journey_id):
    result = client.get("/api/journeys/" + journey_id)
    assert result.status_code == 200
    assert result.json()["id"] == journey_id
    assert result.json()["sourceIds"] == ["test-source"]


def test_schema_validated_plan(repository):
    plan = repository.plan("licence-renewal")
    assert GuidedPlan.model_validate_json(plan.model_dump_json(by_alias=True)) == plan
    assert plan.mode == "guided" and not plan.transactions_enabled
    assert len(plan.sources) == 1


def test_unknown_journey_and_route_are_contract_errors(client):
    for path in ("/api/journeys/no-such-journey", "/api/fetch?url=https://example.com"):
        response = client.get(path)
        assert response.status_code == 404
        assert set(response.json()) == {"error"}


def test_explicit_services_exclusions_override_and_no_assumptions(client):
    response = client.get("/api/locations?service=icbc-licensing")
    assert [item["id"] for item in response.json()["locations"]] == ["office-yes"]
    assert client.get("/api/locations?service=income-assistance").json() == {"locations": []}
    assert client.get("/api/locations?service=icbc-licensing&municipality=Vancouver").json() == {
        "locations": []
    }
    assert (
        client.get("/api/locations?municipality=vIcToRiA").json()["locations"][0]["id"]
        == "office-yes"
    )
    assert client.get("/api/locations?municipality=NoSuchTown").json() == {"locations": []}


@pytest.mark.parametrize(
    "query,code",
    [
        ("service=unapproved", 400),
        ("service=", 400),
        ("municipality=", 400),
        ("municipality=%00", 400),
        ("service=bceid&service=icbc-licensing", 422),
        ("url=https://evil.example", 422),
    ],
)
def test_invalid_location_inputs(client, query, code):
    response = client.get("/api/locations?" + query)
    assert response.status_code == code
    assert set(response.json()["error"]) == {"code", "message"}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["journeys"][0]["sourceIds"].append("missing"),
        lambda data: data["journeys"][0]["steps"][0]["sourceIds"].append("missing"),
        lambda data: data["journeys"][0]["handoffs"][0]["sourceIds"].append("missing"),
        lambda data: data["locations"][0]["sourceIds"].append("missing"),
        lambda data: data["sources"][0].update(checkedAt="2026-02-30"),
        lambda data: data["locations"][0].update(checkedAt="yesterday"),
        lambda data: data["sources"][0].update(url="http://www2.gov.bc.ca/"),
        lambda data: data["sources"][0].update(url="https://evil.example/"),
        lambda data: data["journeys"][0]["handoffs"][0].update(url="javascript:alert(1)"),
        lambda data: data["sources"].append(copy.deepcopy(data["sources"][0])),
        lambda data: data["journeys"][0].update(id="transactions"),
        lambda data: data["sources"][0].update(publisherUpdatedAt=0),
    ],
)
def test_invalid_catalog_is_not_published(catalog_data, mutate):
    mutate(catalog_data)
    with pytest.raises(ValidationError):
        Catalog.model_validate(catalog_data)


def test_invalid_replacement_never_serves_cached_catalog(client, catalog_path, catalog_data):
    assert client.get("/api/catalog").status_code == 200
    catalog_data["sources"][0]["url"] = "https://evil.example/invalid-replacement"
    catalog_path.write_text(json.dumps(catalog_data), encoding="utf-8")
    response = client.get("/api/catalog")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CATALOG_INVALID"
    assert str(catalog_path) not in response.text


def test_missing_catalog(client, catalog_path):
    catalog_path.unlink()
    assert client.get("/api/catalog").status_code == 503
    assert client.get("/healthz").json() == {"status": "ok"}


def test_env_override_is_independent_of_cwd(monkeypatch, catalog_path, tmp_path):
    monkeypatch.setenv("CONTENT_CATALOG_PATH", str(catalog_path))
    monkeypatch.chdir(tmp_path)
    assert Settings().catalog_path == catalog_path
    assert default_catalog_path().name == "pilot-catalog.json"
