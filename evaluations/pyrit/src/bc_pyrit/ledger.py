"""Durable metadata and conservative reservations across sequential Actions steps."""

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from bc_pyrit.contracts import CheckError, Dataset, Limits, Profile, Result, digest


class Ledger:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def transaction(self):
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @classmethod
    def initialize(
        cls,
        path: Path,
        dataset: Dataset,
        profile: Profile,
        limits: Limits,
        identity: dict[str, object],
        evaluator_sha256: str | None = None,
        deployment_id: str | None = None,
    ) -> Ledger:
        limits.require_capacity(dataset.estimate(profile), profile)
        return cls._initialize_state(path, {
            "dataset": dataset.model_dump(mode="json", exclude_unset=True),
            "profile": profile,
            "limits": limits.model_dump(mode="json"),
            "identity": identity,
            "evaluator": evaluator_sha256,
            "deployment": deployment_id,
            "started": time.time(),
            "lastAppAt": 0.0,
            "stop": None,
        })

    @classmethod
    def open_manual(cls, path: Path, *, limits: Limits, identity: dict[str, object]) -> Ledger:
        if limits.attacker.calls or limits.judge.calls:
            raise CheckError("MANUAL_HELPER_MODELS_DISABLED")
        if path.exists():
            ledger = cls(path)
            state = ledger.state()
            if (
                state.get("profile") != "manual"
                or state.get("identity") != identity
                or state.get("limits") != limits.model_dump(mode="json")
            ):
                raise CheckError("MANUAL_BUDGET_CHANGED")
            return ledger
        return cls._initialize_state(path, {
            "dataset": None,
            "profile": "manual",
            "limits": limits.model_dump(mode="json"),
            "identity": identity,
            "started": time.time(),
            "lastAppAt": 0.0,
            "stop": None,
        })

    @classmethod
    def _initialize_state(cls, path: Path, state: dict[str, object]) -> Ledger:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise CheckError("RUN_ALREADY_INITIALIZED") from None
        os.close(descriptor)
        ledger = cls(path)
        with ledger.transaction() as connection:
            connection.execute("CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute(
                "CREATE TABLE charges (role TEXT NOT NULL, tokens INTEGER NOT NULL, "
                "cost INTEGER NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE cases (id TEXT PRIMARY KEY, result TEXT, started INTEGER NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO state VALUES (?, ?)",
                [(key, json.dumps(value)) for key, value in state.items()],
            )
        return ledger

    @staticmethod
    def _state(connection: sqlite3.Connection) -> dict:
        return {
            row["key"]: json.loads(row["value"])
            for row in connection.execute("SELECT key, value FROM state")
        }

    def state(self) -> dict:
        with self.transaction() as connection:
            return self._state(connection)

    def stop(self, code: str) -> None:
        CheckError(code)
        with self.transaction() as connection:
            connection.execute(
                "UPDATE state SET value = ? WHERE key = 'stop' AND value = 'null'",
                (json.dumps(code),),
            )

    def remaining_seconds(self) -> float:
        state = self.state()
        if state["stop"]:
            raise CheckError(state["stop"])
        elapsed = time.time() - state["started"]
        remaining = state["limits"]["wall_seconds"] - elapsed
        if elapsed < 0 or remaining <= 0:
            self.stop("WALL_BUDGET_EXHAUSTED")
            raise CheckError("WALL_BUDGET_EXHAUSTED")
        return remaining

    def charge(self, role: Literal["app", "attacker", "judge"], *, input_bytes: int = 0) -> None:
        failure = None
        with self.transaction() as connection:
            state = self._state(connection)
            limits = Limits.model_validate(state["limits"])
            if state["stop"]:
                raise CheckError(state["stop"])
            elapsed = time.time() - state["started"]
            if elapsed < 0 or elapsed >= limits.wall_seconds:
                failure = "WALL_BUDGET_EXHAUSTED"
            usage = connection.execute(
                "SELECT COUNT(*) AS calls, COALESCE(SUM(tokens), 0) AS tokens, "
                "COALESCE(SUM(cost), 0) AS cost FROM charges WHERE role = ?",
                (role,),
            ).fetchone()
            tokens = cost = 0
            if role == "app":
                if usage["calls"] >= limits.app:
                    failure = "APP_BUDGET_EXHAUSTED"
            else:
                limit = getattr(limits, role)
                tokens = limit.reservation
                cost = tokens * limit.token_price_microusd
                if input_bytes < 0 or input_bytes > limit.input_bytes:
                    failure = "MODEL_INPUT_LIMIT"
                elif (
                    usage["calls"] >= limit.calls
                    or usage["tokens"] + tokens > limit.tokens
                    or usage["cost"] + cost > limit.cost_microusd
                ):
                    failure = "MODEL_BUDGET_EXHAUSTED"
            if failure:
                connection.execute(
                    "UPDATE state SET value = ? WHERE key = 'stop'", (json.dumps(failure),)
                )
            else:
                connection.execute("INSERT INTO charges VALUES (?, ?, ?)", (role, tokens, cost))
                if role == "app":
                    connection.execute(
                        "UPDATE state SET value = ? WHERE key = 'lastAppAt'",
                        (json.dumps(time.time()),),
                    )
        if failure:
            raise CheckError(failure)

    def begin_case(self, key: str) -> None:
        with self.transaction() as connection:
            state = self._state(connection)
            dataset = Dataset.model_validate(state["dataset"])
            if key not in dataset.expected(state["profile"]):
                raise CheckError("UNDECLARED_CASE")
            if connection.execute("SELECT 1 FROM cases WHERE id = ?", (key,)).fetchone():
                raise CheckError("CASE_ALREADY_ATTEMPTED")
            connection.execute("INSERT INTO cases VALUES (?, NULL, 1)", (key,))

    def finish_case(self, result: Result) -> None:
        with self.transaction() as connection:
            state = self._state(connection)
            expected = Dataset.model_validate(state["dataset"]).expected(state["profile"])
            case = expected.get(result.id)
            if case is None or case.threat != result.threat or case.approach != result.approach:
                raise CheckError("CASE_IDENTITY_MISMATCH")
            updated = connection.execute(
                "UPDATE cases SET result = ? WHERE id = ? AND result IS NULL",
                (result.model_dump_json(), result.id),
            )
            if updated.rowcount != 1:
                raise CheckError("CASE_RESULT_ALREADY_RECORDED")

    def report(self) -> dict:
        with self.transaction() as connection:
            state = self._state(connection)
            if state.get("profile") == "manual":
                raise CheckError("MANUAL_SESSION_IS_NOT_A_CAMPAIGN")
            dataset = Dataset.model_validate(state["dataset"])
            recorded = {
                row["id"]: Result.model_validate_json(row["result"])
                for row in connection.execute(
                    "SELECT id, result FROM cases WHERE result IS NOT NULL"
                )
            }
            results = [
                recorded.get(
                    key,
                    Result(
                        id=key,
                        threat=case.threat,
                        approach=case.approach,
                        status="incomplete",
                        code="NOT_COMPLETED",
                        turns=0,
                    ),
                ).model_dump(mode="json")
                for key, case in dataset.expected(state["profile"]).items()
            ]
            usage = {
                role: dict(
                    connection.execute(
                        "SELECT COUNT(*) AS calls, COALESCE(SUM(tokens), 0) AS tokens, "
                        "COALESCE(SUM(cost), 0) AS costMicrousd FROM charges WHERE role = ?",
                        (role,),
                    ).fetchone()
                )
                for role in ("app", "attacker", "judge")
            }
        statuses = {result["status"] for result in results}
        status = (
            "fail"
            if "fail" in statuses
            else "incomplete"
            if state["stop"] or "incomplete" in statuses
            else "needs-review"
            if "needs-review" in statuses
            else "pass"
        )
        return {
            "version": 1,
            "kind": "bc-pyrit",
            "profile": state["profile"],
            "status": status,
            "suiteSha256": digest(state["dataset"]),
            "rubricVersion": dataset.rubric_version,
            "identity": state["identity"],
            "startedAt": state["started"],
            "finishedAt": time.time(),
            "expectedCases": len(results),
            "completedCases": len(recorded),
            "results": results,
            "usage": usage,
            "limits": state["limits"],
            "stopCode": state["stop"],
        }
