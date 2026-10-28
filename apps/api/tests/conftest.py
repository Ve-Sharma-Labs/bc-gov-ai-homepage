import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from bc_api.catalog import CatalogRepository
from bc_api.config import Settings
from bc_api.main import create_app
from bc_api.models import JOURNEY_IDS, Evidence, EvidenceBundle, SourceReference

TEST_URL = "https://www2.gov.bc.ca/gov/content/test-fixture"


@pytest.fixture
def catalog_data():
    """Synthetic test data only; the application never loads these fixtures."""
    timestamp = datetime.now(UTC).isoformat()
    source = {
        "id": "test-source",
        "title": "Test fixture guidance",
        "publisher": "Government of British Columbia",
        "url": TEST_URL,
        "description": "Synthetic source for offline tests, not production evidence.",
        "checkedAt": timestamp,
        "publisherUpdatedAt": None,
        "status": "available",
        "topics": ["test"],
    }
    journeys = [
        {
            "id": key,
            "title": "Test preparation journey",
            "prompt": "How do I prepare?",
            "summary": "An explicitly synthetic guided test plan.",
            "category": "Testing",
            "notice": "Curated test fixture; not live availability.",
            "sourceIds": ["test-source"],
            "steps": [
                {
                    "id": "prepare",
                    "title": "Prepare",
                    "description": "Read the official preparation instructions.",
                    "sourceIds": ["test-source"],
                }
            ],
            "handoffs": [
                {
                    "label": "Official service",
                    "url": TEST_URL + "/handoff",
                    "description": "The resident must complete the next step on the official site.",
                    "sourceIds": ["test-source"],
                }
            ],
        }
        for key in sorted(JOURNEY_IDS)
    ]
    common = {
        "address": "A published test office address",
        "hours": "Consult published hours; not live availability.",
        "sourceIds": ["test-source"],
        "checkedAt": timestamp,
    }
    return {
        "schemaVersion": 1,
        "asOf": timestamp,
        "sources": [source],
        "journeys": journeys,
        "locations": [
            {
                **common,
                "id": "office-yes",
                "name": "Supported test office",
                "municipality": "Victoria",
                "services": ["icbc-licensing", "bceid"],
                "excludedServices": [],
            },
            {
                **common,
                "id": "office-no",
                "name": "Excluded test office",
                "municipality": "Vancouver",
                "services": ["icbc-licensing", "bceid"],
                "excludedServices": ["icbc-licensing"],
            },
            {
                **common,
                "id": "office-unknown",
                "name": "No evidence of support",
                "municipality": "Vancouver",
                "services": [],
                "excludedServices": [],
            },
        ],
    }


@pytest.fixture
def catalog_path(tmp_path, catalog_data):
    path = tmp_path / "test-catalog.json"
    path.write_text(json.dumps(catalog_data), encoding="utf-8")
    return path


@pytest.fixture
def settings(catalog_path):
    return Settings(
        content_catalog_path=catalog_path,
        app_env="development",
        foundry_project_endpoint="",
        foundry_agent_name="",
        foundry_agent_version="",
        azure_search_endpoint="",
        azure_search_index="",
        api_allowed_hosts="localhost,127.0.0.1,testserver",
        api_allowed_origins="http://localhost:3000",
    )


@pytest.fixture
def configured(settings):
    return settings.model_copy(
        update={
            "foundry_project_endpoint": "https://test.services.ai.azure.com/api/projects/test",
            "foundry_agent_name": "test-agent",
            "foundry_agent_version": "1",
            "azure_search_endpoint": "https://test.search.windows.net",
            "azure_search_index": "approved-test-index",
        }
    )


@pytest.fixture
def repository(settings):
    return CatalogRepository(settings.catalog_path)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), headers={"Origin": "http://localhost:3000"}) as client:
        yield client


@pytest.fixture
def run_input():
    return {
        "threadId": "test-thread",
        "runId": "test-run",
        "messages": [{"id": "test-message", "role": "user", "content": "How do I prepare?"}],
        "tools": [],
        "context": [],
        "state": {},
        "forwardedProps": {},
    }


@pytest.fixture
def evidence():
    return EvidenceBundle(
        evidence=[
            Evidence(
                reference=SourceReference(
                    source_id="test-source",
                    document_id="test-document",
                    document_version="test-version",
                    title="Test fixture guidance",
                    publisher="Government of British Columbia",
                    url=TEST_URL,
                    checked_at=datetime.now(UTC).isoformat(),
                    publisher_updated_at=None,
                    section="Preparation",
                ),
                content="Bring accepted identification to the office. The fee is $75.",
            )
        ]
    )
