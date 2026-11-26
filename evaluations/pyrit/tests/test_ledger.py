import json

import pytest

from bc_pyrit.contracts import CheckError, Result
from bc_pyrit.ledger import Ledger


def result(key, case, status="pass"):
    return Result(
        id=key,
        threat=case.threat,
        approach=case.approach,
        status=status,
        code="CHECKED" if status == "pass" else "POLICY_VIOLATION",
        turns=1,
    )


def test_new_step_keeps_existing_charges_and_cannot_reset_run(ledger, dataset, limits):
    ledger.charge("app")
    resumed = Ledger(ledger.path)
    assert resumed.report()["usage"]["app"]["calls"] == 1
    with pytest.raises(CheckError, match="RUN_ALREADY_INITIALIZED"):
        Ledger.initialize(ledger.path, dataset, "offline", limits, {})
    assert resumed.report()["usage"]["app"]["calls"] == 1


def test_exhausted_reservation_stops_later_steps_without_refunding(ledger):
    with ledger.transaction() as connection:
        value = ledger._state(connection)["limits"]
        value["app"] = 1
        connection.execute("UPDATE state SET value = ? WHERE key = 'limits'", (json.dumps(value),))
    ledger.charge("app")
    with pytest.raises(CheckError, match="APP_BUDGET_EXHAUSTED"):
        ledger.charge("app")
    resumed = Ledger(ledger.path)
    with pytest.raises(CheckError, match="APP_BUDGET_EXHAUSTED"):
        resumed.charge("judge", input_bytes=10)
    report = resumed.report()
    assert report["usage"]["app"]["calls"] == 1
    assert report["usage"]["judge"]["calls"] == 0
    assert report["status"] == "incomplete"


def test_interrupted_attempt_remains_incomplete_and_cannot_be_retried_until_pass(ledger, dataset):
    key = next(iter(dataset.expected("offline")))
    ledger.begin_case(key)
    assert Ledger(ledger.path).report()["completedCases"] == 0
    with pytest.raises(CheckError, match="CASE_ALREADY_ATTEMPTED"):
        ledger.begin_case(key)
    assert ledger.report()["status"] == "incomplete"


def test_failed_repetition_survives_later_passes_and_refuses_overwrite(ledger, dataset):
    expected = dataset.expected("offline")
    failed_key = next(key for key, case in expected.items() if case.approach == "repeated-attempts")
    for key, case in expected.items():
        ledger.begin_case(key)
        ledger.finish_case(result(key, case, "fail" if key == failed_key else "pass"))
    assert ledger.report()["status"] == "fail"
    with pytest.raises(CheckError, match="CASE_RESULT_ALREADY_RECORDED"):
        ledger.finish_case(result(failed_key, expected[failed_key]))
    assert ledger.report()["status"] == "fail"


def test_complete_pass_requires_every_case_and_cleanup(ledger, dataset):
    expected = dataset.expected("offline")
    for key, case in expected.items():
        ledger.begin_case(key)
        ledger.finish_case(result(key, case))
    assert ledger.report()["status"] == "pass"
    ledger.stop("CLEANUP_FAILED")
    assert ledger.report()["status"] == "incomplete"


def test_report_rejects_case_metadata_substitution(ledger, dataset):
    key, case = next(iter(dataset.expected("offline").items()))
    ledger.begin_case(key)
    substituted = result(key, case).model_copy(update={"threat": "privacy"})
    with pytest.raises(CheckError, match="CASE_IDENTITY_MISMATCH"):
        ledger.finish_case(substituted)
    assert ledger.report()["status"] == "incomplete"
