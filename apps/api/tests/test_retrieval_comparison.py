import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

MODULE = Path(__file__).resolve().parents[3] / "scripts" / "compare-retrieval.py"
spec = importlib.util.spec_from_file_location("retrieval_comparison", MODULE)
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


def payload(filter_value):
    return {
        "response": [
            {
                "role": "assistant",
                "content": [{"type": "text", "text": '[{"ref_id":"one","content":"test"}]'}],
            }
        ],
        "references": [
            {
                "id": "one",
                "type": "searchIndex",
                "docKey": "chunk-one",
                "sourceData": {"id": "chunk-one"},
            },
            {
                "id": "unused",
                "type": "searchIndex",
                "docKey": "other",
                "sourceData": {"id": "other"},
            },
        ],
        "activity": [
            {
                "type": "searchIndex",
                "knowledgeSourceName": comparison.SOURCE,
                "searchIndexArguments": {"filter": filter_value},
                "count": 2,
                "elapsedMs": 12,
            }
        ],
    }


async def test_ga_comparison_preserves_filters_and_only_uses_returned_grounding():
    where = "status eq 'active' and sourceId eq 'service-bc'"

    def transport(request):
        assert request.url.params["api-version"] == "2026-04-01"
        data = json.loads(request.content)
        assert data["knowledgeSourceParams"][0]["filterAddOn"] == where
        assert data["knowledgeSourceParams"][0]["includeReferenceSourceData"]
        assert "models" not in data and "retrievalReasoningEffort" not in data
        assert data["intents"] == [{"type": "semantic", "search": "Public question"}]
        return httpx.Response(200, json=payload(where))

    async with httpx.AsyncClient(
        base_url="https://example.search.windows.net", transport=httpx.MockTransport(transport)
    ) as client:
        adapter = comparison.IQSearch(client)
        rows = await adapter.search(search_text="Public question", filter=where)
        assert [row async for row in rows] == [{"id": "chunk-one"}]
        assert adapter.filter_preserved


@pytest.mark.parametrize("reference_id", [0, 1, "one"])
async def test_ga_extracts_integer_or_string_reference_identifiers(reference_id):
    result = payload("status eq 'active'")
    result["response"][0]["content"][0]["text"] = json.dumps(
        [{"ref_id": reference_id, "content": "test"}]
    )
    result["references"][0]["id"] = str(reference_id)
    async with httpx.AsyncClient(
        base_url="https://example.search.windows.net",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=result)),
    ) as client:
        rows = await comparison.IQSearch(client).search(
            search_text="Question", filter="status eq 'active'"
        )
        assert [row async for row in rows] == [{"id": "chunk-one"}]


@pytest.mark.parametrize("reference_id", [True, False, -1, 0.5, None, "", [], {}])
async def test_invalid_reference_identifiers_cannot_be_coerced_into_valid_ids(reference_id):
    result = payload("status eq 'active'")
    result["response"][0]["content"][0]["text"] = json.dumps(
        [{"ref_id": reference_id, "content": "test"}]
    )
    async with httpx.AsyncClient(
        base_url="https://example.search.windows.net",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=result)),
    ) as client:
        with pytest.raises(RuntimeError, match="Unidentified extractive chunk"):
            await comparison.IQSearch(client).search(
                search_text="Question", filter="status eq 'active'"
            )


@pytest.mark.parametrize("failure", ["partial", "model", "wrong-key"])
async def test_partial_synthesized_or_unverifiable_iq_output_cannot_pass(failure):
    def transport(request):
        result = payload("status eq 'active'")
        if failure == "model":
            result["activity"].append({"type": "modelQueryPlanning"})
        if failure == "wrong-key":
            result["references"][0]["docKey"] = "not-the-source-data-key"
        return httpx.Response(206 if failure == "partial" else 200, json=result)

    async with httpx.AsyncClient(
        base_url="https://example.search.windows.net", transport=httpx.MockTransport(transport)
    ) as client:
        with pytest.raises(RuntimeError):
            await comparison.IQSearch(client).search(
                search_text="Question", filter="status eq 'active'"
            )


def test_comparison_defaults_to_no_network_or_resource_changes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv", ["compare-retrieval", "--output", str(tmp_path / "result.json")]
    )
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *args, **kwargs: pytest.fail("Unexpected network")
    )
    comparison.main()
    result = json.loads(capsys.readouterr().out)
    assert result["networkRequests"] == 0
    assert result["modelInvocations"] == 0
    assert result["pairedRetrievals"] == 6
