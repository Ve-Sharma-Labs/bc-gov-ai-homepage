"""Project-local checkpoints with single-writer locking and compare-and-swap revisions."""

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from .paths import PROJECT_ROOT
from .policy import AcquisitionError


class AcquisitionPaused(AcquisitionError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class CheckpointError(AcquisitionError):
    """Fatal storage failure: never turn it into a publisher retry or a new run."""


def atomic_json(path: Path, value) -> None:
    staged = path.with_suffix(path.suffix + ".new")
    try:
        with staged.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


class ManifestStore(Protocol):
    """A remote adapter must also provide exclusive ownership and revision/ETag CAS."""

    def load(self) -> dict | None: ...
    def save(self, state: dict) -> None: ...
    def pause_requested(self) -> bool: ...
    def clear_pause(self) -> None: ...


class ResponseStore(Protocol):
    def put(self, body: bytes) -> str: ...
    def get(self, key: str) -> bytes: ...


class LocalResponseStore:
    """Immutable, content-addressed publisher responses, separate from review decisions."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        if not self.root.is_relative_to(PROJECT_ROOT) or ".generated" not in self.root.parts:
            raise AcquisitionError("Candidate responses must stay in a project .generated directory")
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, body: bytes) -> str:
        key = hashlib.sha256(body).hexdigest()
        path = self.root / (key + ".body")
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != key:
                raise AcquisitionError("An immutable candidate response has been modified")
        else:
            staged = path.with_suffix(".new")
            try:
                with staged.open("wb") as handle:
                    handle.write(body)
                    handle.flush()
                    os.fsync(handle.fileno())
                staged.replace(path)
            finally:
                staged.unlink(missing_ok=True)
        return key

    def get(self, key: str) -> bytes:
        import re
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
            raise AcquisitionError("Invalid immutable response key")
        body = (self.root / (key + ".body")).read_bytes()
        if hashlib.sha256(body).hexdigest() != key:
            raise AcquisitionError("An immutable candidate response has been modified")
        return body


class JsonManifestStore:
    def __init__(self, path: Path):
        self.path = path.resolve()
        if not self.path.is_relative_to(PROJECT_ROOT) or ".generated" not in self.path.parts:
            raise AcquisitionError("Manifests must stay in a project .generated directory")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = None
        self.pause_path = self.path.with_name("pause-request.json")

    def __enter__(self):
        self.lock = self.path.with_suffix(".lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.lock.seek(0, os.SEEK_END)
                if self.lock.tell() == 0:
                    self.lock.write(b"\0")
                    self.lock.flush()
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.lock.close()
            self.lock = None
            raise AcquisitionError("Manifest is owned by another worker; do not run parallel host crawlers") from exc
        return self

    def __exit__(self, *_):
        if self.lock:
            if os.name == "nt":
                import msvcrt
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock.fileno(), fcntl.LOCK_UN)
            self.lock.close()
            self.lock = None

    def load(self) -> dict | None:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else None

    def save(self, state: dict) -> None:
        if self.lock is None:
            raise AcquisitionError("A manifest write requires exclusive worker ownership")
        live = self.load()
        revision = live.get("revision", 0) if live else 0
        if state.get("revision", 0) != revision:
            raise AcquisitionError("Stale manifest revision; reload rather than overwrite another checkpoint")
        updated = {**state, "revision": revision + 1}
        atomic_json(self.path, updated)
        state["revision"] = updated["revision"]

    def request_pause(self) -> None:
        # Independent of the worker lock: the next request boundary observes this signal.
        atomic_json(self.pause_path, {"reason": "operator-pause"})

    def pause_requested(self) -> bool:
        return self.pause_path.exists()

    def clear_pause(self) -> None:
        if self.lock is None:
            raise AcquisitionError("Only an explicitly resumed worker can clear a pause")
        self.pause_path.unlink(missing_ok=True)


@dataclass(frozen=True)
class ProgrammeLimits:
    total_requests: int = 20_000
    total_bytes: int = 1_000_000_000
    max_candidates: int = 100_000
    max_retries: int = 2
    response_bytes: int = 4_000_000
    timeout: float = 25
    host_delay: float = 1

    def __post_init__(self):
        for name, lower, upper in (
            ("total_requests", 1, 1_000_000), ("total_bytes", 2, 100_000_000_000),
            ("max_candidates", 1, 1_000_000), ("max_retries", 0, 5),
            ("response_bytes", 1, 8_000_000),
        ):
            if type(getattr(self, name)) is not int or not lower <= getattr(self, name) <= upper:
                raise AcquisitionError(f"Invalid bounded programme limit: {name}")
        if not 0 < self.timeout <= 60 or not 1 <= self.host_delay <= 3600:
            raise AcquisitionError("Invalid timeout or host pacing limit")

    def to_dict(self) -> dict:
        return asdict(self)


class RequestController:
    """Charges before dispatch; interrupted/failed reads conservatively retain their reservation."""

    def __init__(self, state: dict, store: ManifestStore, limits: ProgrammeLimits, *,
                 batch_requests=25, run_seconds=120, clock=time.time, sleep=time.sleep,
                 rights_check=lambda: None, max_document_requests=None):
        if type(batch_requests) is not int or not 1 <= batch_requests <= 1000 or not 1 <= run_seconds <= 3600:
            raise AcquisitionError("An invocation needs bounded requests and runtime")
        self.state, self.store, self.limits = state, store, limits
        self.clock, self.sleep, self.rights_check = clock, sleep, rights_check
        self.start_requests = state["budget"]["requests"]
        self.batch_requests, self.deadline = batch_requests, clock() + run_seconds
        self.candidate_id = None
        self.max_document_requests = max_document_requests

    def before_request(self, url: str, *, limit: int, delay: float, robots: bool) -> int:
        from urllib.parse import urlsplit
        self.rights_check()
        if self.store.pause_requested():
            raise AcquisitionPaused("operator-pause")
        budget = self.state["budget"]
        if not robots and self.max_document_requests is not None and budget["documentRequests"] >= self.max_document_requests:
            raise AcquisitionPaused("durable-manual-sample-cap-exhausted; use a separately reviewed full programme")
        if budget["requests"] >= self.limits.total_requests:
            raise AcquisitionPaused("total-request-budget-exhausted")
        if budget["requests"] - self.start_requests >= self.batch_requests:
            raise AcquisitionPaused("invocation-request-checkpoint")
        remaining = self.limits.total_bytes - budget["chargedBytes"]
        if remaining < 2:
            raise AcquisitionPaused("total-byte-budget-exhausted")
        host = urlsplit(url).hostname
        next_allowed = budget["hosts"].get(host, {}).get("nextAllowedAt", 0)
        wait = max(0, next_allowed - self.clock())
        if self.clock() + wait >= self.deadline:
            raise AcquisitionPaused("host-delay" if wait else "invocation-time-checkpoint")
        if wait:
            self.sleep(wait)
        self.rights_check()
        if self.store.pause_requested():
            raise AcquisitionPaused("operator-pause")
        # Include transport's one-byte overflow probe in the worst-case reservation.
        allowed = min(limit, remaining - 1)
        budget["requests"] += 1
        budget["robotsRequests" if robots else "documentRequests"] += 1
        budget["chargedBytes"] += allowed + 1
        budget["hosts"][host] = {"nextAllowedAt": self.clock() + max(delay, self.limits.host_delay)}
        budget["inFlight"] = {
            "url": url, "candidateId": self.candidate_id, "reservedBytes": allowed + 1,
            "requestNumber": budget["requests"], "robots": robots,
        }
        self.store.save(self.state)
        return allowed

    def after_request(self, response=None, error=None) -> None:
        budget = self.state["budget"]
        reservation = budget.pop("inFlight", None)
        if reservation is None:
            raise AcquisitionError("Missing durable request reservation")
        if response is not None:
            used = len(response.body)
            if used >= reservation["reservedBytes"]:
                budget["inFlight"] = reservation
                raise AcquisitionError("Transport violated the reserved response-byte bound")
            budget["chargedBytes"] -= reservation["reservedBytes"] - used
            budget["responseBytes"] += used
        self.state["events"].append({
            "type": "request", **reservation,
            "status": response.status if response is not None else "failed",
            "bytes": len(response.body) if response is not None else None,
            "reason": type(error).__name__ if error is not None else None,
        })
        self.store.save(self.state)

    def defer_host(self, host: str, until: float) -> None:
        hosts = self.state["budget"]["hosts"]
        hosts[host] = {"nextAllowedAt": max(until, hosts.get(host, {}).get("nextAllowedAt", 0))}
        self.store.save(self.state)
