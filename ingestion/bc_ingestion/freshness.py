"""Metadata-only reporting and explicitly authorized, durable source refreshes."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

from .catalog import load_catalog
from .fetch import Fetcher, transport
from .manifest import (
    AcquisitionPaused, CheckpointError, JsonManifestStore, ProgrammeLimits, RequestController, atomic_json,
)
from .metadata import digest, iso_datetime
from .paths import PROJECT_ROOT
from .policy import AcquisitionError, canonicalize, validate_url
from .programme_policy import ProgrammeGate, ProgrammePolicy
from .programme import retry_at


LIMITS = ProgrammeLimits(total_requests=1000, total_bytes=64_000_000, response_bytes=1_000_000)
HASH = re.compile(r"[0-9a-f]{64}")
STALE_DAYS = 30


def targets(catalog, provenance):
    if not isinstance(provenance, dict) or not isinstance(provenance.get("documents"), list):
        raise AcquisitionError("Freshness requires a provenance document inventory")
    sources = {source["id"]: source for source in catalog["sources"]}
    selected = {}
    for source in sources.values():
        url = canonicalize(source["url"])
        selected[(source["id"], url)] = {
            "sourceId": source["id"], "url": url, "checkedAt": source["checkedAt"],
            "baselineHash": None,
        }
    for document in provenance["documents"]:
        source_id = document.get("sourceId")
        if source_id not in sources:
            raise AcquisitionError("Provenance references an unknown catalogue source")
        url = canonicalize(document["url"])
        if urlsplit(url).hostname != urlsplit(sources[source_id]["url"]).hostname:
            raise AcquisitionError("Provenance publisher does not match the catalogue")
        baseline = document.get("responseSha256")
        if not isinstance(baseline, str) or not HASH.fullmatch(baseline):
            raise AcquisitionError("Provenance requires an exact response SHA-256")
        selected[(source_id, url)] = {
            "sourceId": source_id, "url": url, "checkedAt": document.get("checkedAt"),
            "baselineHash": baseline,
        }
    if len(selected) > 100:
        raise AcquisitionError("Freshness inventory exceeds the bounded 100-page scope")
    return list(selected.values())


def offline_findings(catalog, provenance, now):
    rows = []
    for target in targets(catalog, provenance):
        findings = []
        checked = target["checkedAt"]
        if checked is None:
            findings.append("missing-check-date")
        else:
            timestamp = iso_datetime(checked if len(checked) > 10 else checked + "T00:00:00Z")
            if timestamp > now:
                raise AcquisitionError("Source check date is in the future")
            if now - timestamp >= timedelta(days=STALE_DAYS):
                findings.append("stale-check")
        try:
            validate_url(target["url"])
        except AcquisitionError:
            findings.append("source-access-hold")
        if target["baselineHash"] is None:
            findings.append("missing-baseline")
        rows.append({
            **target,
            "journeyIds": sorted(
                journey["id"] for journey in catalog["journeys"]
                if target["sourceId"] in journey["sourceIds"]
            ),
            "findings": findings,
            "refresh": "not-requested",
        })
    return rows


def validate_state(state, programme_hash):
    if (
        not isinstance(state, dict) or state.get("schemaVersion") != 1
        or state.get("kind") != "official-source-freshness"
        or state.get("programmeHash") != programme_hash or state.get("limits") != LIMITS.to_dict()
        or not isinstance(state.get("observations"), dict) or not isinstance(state.get("events"), list)
        or not isinstance(state.get("holds"), dict)
    ):
        raise AcquisitionError("Invalid freshness checkpoint or changed programme/limits")
    budget = state.get("budget")
    if not isinstance(budget, dict) or type(state.get("revision")) is not int or state["revision"] < 1:
        raise AcquisitionError("Invalid freshness checkpoint revision or budget")
    for key in ("requests", "documentRequests", "robotsRequests", "chargedBytes", "responseBytes"):
        if type(budget.get(key)) is not int or budget[key] < 0:
            raise AcquisitionError("Invalid freshness checkpoint accounting")
    if (
        budget["requests"] != budget["documentRequests"] + budget["robotsRequests"]
        or budget["requests"] > LIMITS.total_requests or budget["chargedBytes"] > LIMITS.total_bytes
        or budget["responseBytes"] > budget["chargedBytes"] or not isinstance(budget.get("hosts"), dict)
    ):
        raise AcquisitionError("Freshness checkpoint counters are inconsistent")
    for host, timing in budget["hosts"].items():
        if not isinstance(host, str) or not isinstance(timing, dict):
            raise AcquisitionError("Invalid publisher pacing checkpoint")
        deadline = timing.get("nextAllowedAt")
        if type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline < 0:
            raise AcquisitionError("Invalid publisher pacing deadline")
    for url, observation in state["observations"].items():
        canonicalize(url)
        if not isinstance(observation, dict) or not HASH.fullmatch(observation.get("responseHash", "")):
            raise AcquisitionError("Invalid freshness observation")
        iso_datetime(observation.get("checkedAt"))
    return state


def initial_state(programme_hash):
    return {
        "schemaVersion": 1, "kind": "official-source-freshness",
        "programmeHash": programme_hash, "limits": LIMITS.to_dict(),
        "observations": {}, "events": [], "holds": {},
        "budget": {
            "requests": 0, "documentRequests": 0, "robotsRequests": 0,
            "chargedBytes": 0, "responseBytes": 0, "hosts": {},
        },
    }


class FreshnessStore(JsonManifestStore):
    def save(self, state):
        try:
            super().save(state)
        except (AcquisitionError, OSError) as exc:
            raise CheckpointError("Freshness checkpoint could not be persisted") from exc


def refresh_rows(rows, policy, store, *, initialize=False, request=transport,
                 clock=time.time, sleep=time.sleep):
    state = store.load()
    if state is None:
        if not initialize:
            for row in rows:
                row["refresh"] = "checkpoint-required"
            return None
        state = initial_state(policy.programme_hash)
        store.save(state)
    else:
        if initialize:
            raise AcquisitionError("Initialization cannot replace an existing freshness checkpoint")
        validate_state(state, policy.programme_hash)
    controller = RequestController(
        state, store, LIMITS, batch_requests=25, run_seconds=90,
        rights_check=policy.assert_current_rights, clock=clock, sleep=sleep,
    )

    def authorized(url, **kwargs):
        # A reviewed candidate route cannot override the narrow public-page holds.
        validate_url(url, robots=kwargs.get("robots", False))
        return policy.validate_url(url, **kwargs)

    def paced_request(url, **kwargs):
        response = request(url, **kwargs)
        if response.headers.get("retry-after"):
            host = urlsplit(url).hostname
            try:
                deadline = retry_at(response.headers["retry-after"], clock(), 1)
            except AcquisitionError:
                state["holds"][host] = "invalid-retry-after"
                store.save(state)
                raise
            controller.defer_host(host, deadline)
        return response

    fetcher = Fetcher(
        max_pages=None, max_bytes=LIMITS.response_bytes, timeout=15,
        request_controller=controller, url_validator=authorized, request=paced_request,
        clock=clock, sleep=sleep,
    )
    # Resume in oldest-observation order so invocation bounds do not starve later pages.
    ordered = sorted(rows, key=lambda row: state["observations"].get(row["url"], {}).get("checkedAt", ""))
    paused = False
    for row in ordered:
        if urlsplit(row["url"]).hostname in state["holds"]:
            row["refresh"] = "publisher-review-required"
            continue
        if paused:
            row["refresh"] = "deferred-budget"
            continue
        try:
            authorized(row["url"])
            response = fetcher.fetch(row["url"])
            row["httpStatus"] = response.status
            row["lastAttemptAt"] = response.checked_at
            if response.status == 200:
                content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if content_type not in {"text/html", "application/xhtml+xml"}:
                    row["refresh"] = "unsupported-content-type"
                else:
                    row["observedHash"] = response.digest
                    row["refresh"] = (
                        "unchanged" if response.digest == row["baselineHash"] else "changed"
                        if row["baselineHash"] else "baseline-unavailable"
                    )
                    if row["refresh"] == "changed":
                        row["findings"].append("source-changed")
                    if row["refresh"] == "unchanged":
                        row["findings"] = [
                            code for code in row["findings"] if code not in {"stale-check", "missing-check-date"}
                        ]
                    state["observations"][row["url"]] = {
                        "checkedAt": response.checked_at, "responseHash": response.digest,
                    }
            elif response.status in (404, 410):
                row["refresh"] = "withdrawn"
                row["findings"].append("source-withdrawn")
            elif response.status == 304:
                # This monitor never sends validators: 304 cannot prove unchanged evidence.
                row["refresh"] = "unverifiable-304"
            else:
                row["refresh"] = "http-unavailable"
            if row["refresh"] not in {"unchanged", "changed", "baseline-unavailable", "withdrawn"}:
                row["findings"].append("refresh-unavailable")
        except CheckpointError:
            raise
        except ProgrammeGate as exc:
            row["refresh"] = exc.code
        except AcquisitionPaused:
            paused = True
            row["refresh"] = "deferred-budget"
        except AcquisitionError:
            row["refresh"] = "access-or-network-unavailable"
            row["findings"].append("refresh-unavailable")
        finally:
            # Do not retain response bodies, private review fields or exception messages.
            store.save(state)
    return state


def collect(catalog, provenance, programme, *, now=None, rights=None, refresh=False,
            store=None, initialize=False, request=transport, clock=time.time, sleep=time.sleep):
    now = now or datetime.now(timezone.utc)
    rows = offline_findings(catalog, provenance, now)
    try:
        policy = ProgrammePolicy(programme, catalog, rights, clock=lambda: now)
        if refresh:
            policy.assert_current_rights()
    except ProgrammeGate as exc:
        for row in rows:
            row["refresh"] = exc.code
    else:
        if refresh:
            if store is None:
                raise AcquisitionError("Authorized refresh requires a durable checkpoint store")
            # Recheck real time at every request boundary, not a frozen invocation timestamp.
            policy.clock = lambda: datetime.fromtimestamp(clock(), timezone.utc)
            refresh_rows(
                rows, policy, store, initialize=initialize, request=request, clock=clock, sleep=sleep,
            )
    report = {
        "schemaVersion": 1, "kind": "official-source-freshness",
        "checkedAt": now.isoformat(), "staleDays": STALE_DAYS, "sources": rows,
    }
    for row in rows:
        row["findings"] = sorted(set(row["findings"]))
    report["fingerprint"] = digest([
        {key: value for key, value in row.items() if key not in {"lastAttemptAt"}}
        for row in rows
    ])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "ingestion/.generated/freshness")
    args = parser.parse_args(argv)
    if args.initialize and not args.refresh:
        parser.error("--initialize requires --refresh")
    from .pipeline import guarded_output
    output = guarded_output(args.output)
    try:
        catalog = load_catalog(PROJECT_ROOT / "data/pilot-catalog.json")
        provenance = json.loads((PROJECT_ROOT / "data/provenance.json").read_text(encoding="utf-8"))
        programme = json.loads((PROJECT_ROOT / "data/source-programme.json").read_text(encoding="utf-8"))
        raw_rights = os.environ.get("SOURCE_WATCHDOG_RIGHTS_JSON", "")
        rights = None
        if raw_rights:
            expected = os.environ.get("SOURCE_WATCHDOG_RIGHTS_SHA256", "")
            if not HASH.fullmatch(expected) or hashlib.sha256(raw_rights.encode()).hexdigest() != expected:
                raise AcquisitionError("Watchdog rights input does not match its independently pinned SHA-256")
            rights = json.loads(raw_rights)
        with FreshnessStore(output / "checkpoint.json") as store:
            report = collect(
                catalog, provenance, programme, rights=rights, refresh=args.refresh,
                store=store, initialize=args.initialize,
            )
        atomic_json(output / "report.json", report)
        print(json.dumps({"status": "reported", "sources": len(report["sources"])}))
        return 0
    except (AcquisitionError, OSError, ValueError, KeyError, TypeError):
        # Input/storage failures do not expose private rights fields or publisher bodies.
        print("Freshness collection failed: invalid input, policy, or checkpoint; no clean result.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
