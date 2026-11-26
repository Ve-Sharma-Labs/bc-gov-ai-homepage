from bc_pyrit.contracts import CheckError, Dataset, Result


def require_complete(report: dict, dataset: Dataset) -> None:
    expected = dataset.expected(report["profile"])
    if (
        report["status"] != "pass"
        or report["stopCode"] is not None
        or report["expectedCases"] != len(expected)
        or report["completedCases"] != len(expected)
        or len(report["results"]) != len(expected)
    ):
        raise CheckError("INCOMPLETE_OR_FAILED_COVERAGE")
    seen = set()
    required = {"app": 0, "judge": 0, "attacker": 0}
    for raw in report["results"]:
        result = Result.model_validate(raw)
        case = expected.get(result.id)
        if case is None or result.id in seen:
            raise CheckError("UNDECLARED_OR_DUPLICATED_CASE")
        seen.add(result.id)
        variant_id = result.id.split("/")[1]
        variant = next(item for item in case.variants if item.id == variant_id)
        turns = case.application_turns(variant)
        if (
            result.status != "pass"
            or result.threat != case.threat
            or result.approach != case.approach
            or result.turns != turns
        ):
            raise CheckError("INCOMPLETE_TURN_COVERAGE")
        required["app"] += turns
        required["judge"] += 0 if case.offline_check else turns - int(case.isolation_probe)
        required["attacker"] += case.max_turns if case.approach == "adaptive-multi-turn" else 0
    for role, calls in required.items():
        if report["usage"][role]["calls"] != calls:
            raise CheckError("INCOMPLETE_MODEL_OR_REQUEST_COVERAGE")
