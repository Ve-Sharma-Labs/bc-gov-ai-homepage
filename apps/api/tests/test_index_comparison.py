import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE = Path(__file__).resolve().parents[3] / "scripts" / "compare-search-indexes.py"
spec = importlib.util.spec_from_file_location("search_index_comparison", MODULE)
comparison = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = comparison
spec.loader.exec_module(comparison)


def schema(name, metadata):
    required = (
        comparison.SELECT_FIELDS + comparison.METADATA_FIELDS
        if metadata
        else comparison.SELECT_FIELDS
    )
    filterable = comparison.COMMON_FILTER_FIELDS | (
        comparison.METADATA_FILTER_FIELDS if metadata else set()
    )
    fields = [
        SimpleNamespace(
            name=field,
            type=comparison.REQUIRED_TYPES[field],
            retrievable=True,
            filterable=field in filterable,
        )
        for field in required
    ]
    return SimpleNamespace(
        name=name,
        fields=fields,
        semantic_search=SimpleNamespace(
            configurations=[SimpleNamespace(name=comparison.SEMANTIC_CONFIGURATION)]
        ),
    )


def metadata_row():
    return {
        "id": "chunk-one",
        "documentId": "document-one",
        "documentVersion": "version-one",
        "sourceId": "health",
        "metadataVersion": 1,
        "sourceIds": ["health"],
        "documentType": "guidance",
        "language": "en-CA",
        "contentHash": "a" * 64,
        "extractionHash": "b" * 64,
        "reviewHash": "c" * 64,
        "rightsStatus": "candidate-acquisition-permitted",
        "rightsReviewId": "reviewed-rights",
        "rightsHash": "d" * 64,
    }


class Search:
    def __init__(self, rows):
        self.rows = rows
        self.options = []

    async def search(self, **options):
        self.options.append(options)

        async def values():
            for row in self.rows:
                yield row

        return values()


def test_v2_schema_validation_covers_every_application_selected_field():
    value = schema(comparison.V2_INDEX, metadata=True)
    assert comparison.schema_issues(value, comparison.V2_INDEX, metadata=True) == []
    selected = set(comparison.SELECT_FIELDS + comparison.METADATA_FIELDS)
    assert selected <= {field.name for field in value.fields}

    value.fields = [field for field in value.fields if field.name != "rightsHash"]
    issues = comparison.schema_issues(value, comparison.V2_INDEX, metadata=True)
    assert "Missing selected field: rightsHash." in issues


def test_schema_validation_rejects_wrong_types_and_nonfilterable_contract_fields():
    value = schema(comparison.V2_INDEX, metadata=True)
    next(field for field in value.fields if field.name == "metadataVersion").type = "Edm.String"
    next(field for field in value.fields if field.name == "rightsStatus").filterable = False
    issues = comparison.schema_issues(value, comparison.V2_INDEX, metadata=True)
    assert any("metadataVersion has type Edm.String" in issue for issue in issues)
    assert "Required filter field rightsStatus is not filterable." in issues


async def test_comparison_sends_identical_queries_and_filters_and_validates_v2_metadata():
    case = comparison.ComparisonCase(
        "health",
        "How do I enrol in MSP?",
        ("health",),
        "health-coverage",
    )
    v1 = Search([{"id": "chunk-one"}])
    v2 = Search([metadata_row()])
    results = await comparison.compare_cases(v1, v2, (case,), {"health"})
    assert results[0]["sameQueryAndFilter"]
    assert results[0]["sameRankedChunks"]
    assert results[0]["v2MetadataErrors"] == []
    assert v1.options[0]["search_text"] == v2.options[0]["search_text"]
    assert v1.options[0]["filter"] == v2.options[0]["filter"]
    assert "journeyIds/any(j: j eq 'health-coverage')" in v1.options[0]["filter"]
    assert "metadataVersion" not in v1.options[0]["select"]
    assert "metadataVersion" in v2.options[0]["select"]


async def test_comparison_reports_invalid_v2_rights_metadata_without_treating_it_as_evidence():
    row = metadata_row()
    row["rightsStatus"] = "review-required"
    case = comparison.ComparisonCase("health", "How do I enrol in MSP?", ("health",))
    results = await comparison.compare_cases(
        Search([{"id": "chunk-one"}]),
        Search([row]),
        (case,),
        {"health"},
    )
    assert results[0]["v2MetadataErrors"]
    assert "rights provenance" in results[0]["v2MetadataErrors"][0]["error"]


def test_comparison_defaults_to_review_only_without_network(tmp_path, monkeypatch, capsys):
    output = tmp_path / "comparison.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["compare-search-indexes", "--output", str(output)],
    )
    monkeypatch.setattr(
        comparison,
        "SearchIndexClient",
        lambda *args, **kwargs: pytest.fail("Unexpected network client"),
    )
    comparison.main()
    report = json.loads(capsys.readouterr().out)
    assert report["networkRequests"] == 0
    assert report["mutationOperations"] == []
    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_case_file_rejects_filter_injection(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "bad",
                    "query": "Question",
                    "sourceIds": ["health' or true"],
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        comparison.load_cases(path)
