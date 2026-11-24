import pytest
from pydantic import ValidationError

from bc_pyrit.contracts import CheckError, Dataset, exact_origin


@pytest.mark.parametrize("removed", ["privacy", "indirect-injection", "resource-exhaustion"])
def test_missing_threat_cannot_shrink_required_coverage(dataset, removed):
    value = dataset.model_dump(mode="json")
    value["cases"] = [case for case in value["cases"] if case["threat"] != removed]
    with pytest.raises(ValidationError, match="every required threat"):
        Dataset.model_validate(value)


def test_offline_faults_cannot_be_enabled_live(dataset):
    value = dataset.model_dump(mode="json")
    fault = next(case for case in value["cases"] if case["offline_check"])
    fault["profiles"] = ["offline", "live"]
    with pytest.raises(ValidationError, match="offline"):
        Dataset.model_validate(value)


def test_repetitions_and_scripted_turns_are_in_preflight_estimate(dataset):
    case = next(case for case in dataset.cases if case.approach == "repeated-attempts")
    assert len(case.attempts()) == 3
    expected = sum(
        case.application_turns(variant)
        for case in dataset.for_profile("live")
        for _, variant in case.attempts()
    )
    assert dataset.estimate("live")["app"] == expected
    assert expected > 12


def test_budget_must_cover_all_required_attempts(dataset, limits):
    limits.app = 12
    with pytest.raises(CheckError, match="INSUFFICIENT_APP_BUDGET"):
        limits.require_capacity(dataset.estimate("live"), "live")


def test_live_judges_need_explicit_price_and_spending_approval(dataset, limits):
    with pytest.raises(CheckError, match="UNAPPROVED_MODEL_BUDGET"):
        limits.require_capacity(dataset.estimate("live"), "live")


@pytest.mark.parametrize(
    "value",
    [
        "https://name:secret@example.com",
        "https://example.com/api",
        "https://example.com/?token=secret",
        "http://example.com",
        "https://example.com/#fragment",
    ],
)
def test_targets_cannot_smuggle_credentials_paths_or_insecure_remote_origins(value):
    with pytest.raises(CheckError, match="UNAPPROVED_ORIGIN"):
        exact_origin(value)


def test_offline_targets_are_loopback_only():
    assert exact_origin("http://127.0.0.1:8123/", local=True) == "http://127.0.0.1:8123"
    with pytest.raises(CheckError, match="UNAPPROVED_ORIGIN"):
        exact_origin("https://example.com", local=True)
