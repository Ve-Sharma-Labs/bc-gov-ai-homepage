"""The network and Azure operations are explicit subcommands, never import effects."""

import argparse
import json
import os
import sys
from pathlib import Path

from .catalog import load_catalog
from .fetch import Fetcher, Response, utc_now
from .manifest import JsonManifestStore, LocalResponseStore, ProgrammeLimits
from .metadata import digest, iso_datetime
from .pipeline import Ledger, build_publish_plan, guarded_output, save_json
from .policy import PUBLISHERS, AcquisitionError, canonicalize, validate_url

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = PROJECT_ROOT / "data" / "pilot-catalog.json"
DEFAULT_PROGRAMME = PROJECT_ROOT / "data" / "source-programme.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "ingestion" / ".generated"


def display_path(value: str | Path) -> str:
    return str(Path(value).resolve().relative_to(PROJECT_ROOT))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Bounded public-source pilot ingestion; no transactions")
    result.add_argument(
        "command",
        choices=(
            "dry-run",
            "discover",
            "extract",
            "reextract",
            "open-data-service-bc",
            "adapt-source",
            "blob-inspect",
            "rights-upload",
            "publish",
            "validate",
            "index-schema",
            "shadow-index",
            "programme",
        ),
    )
    result.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    result.add_argument("--url", action="append", default=[], metavar="SOURCE_ID=HTTPS_URL",
                        help="An explicit public page; repeat up to the 25-request run budget")
    result.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    result.add_argument("--max-pages", type=int, default=25)
    result.add_argument("--review-manifest", type=Path)
    result.add_argument("--review-page-size", type=int, default=100, help="Bounded Blob candidate-review export page")
    result.add_argument("--review-after", default="", help="Continue a Blob review export after this document ID")
    result.add_argument("--execute", action="store_true")
    result.add_argument("--approved", action="store_true")
    result.add_argument("--create-index", action="store_true")
    result.add_argument("--stage-blob", action="store_true")
    result.add_argument("--index-name", default="bc-pilot-public")
    result.add_argument("--vector-dimensions", type=int)
    result.add_argument("--existing-schema", type=Path, help="Offline additive migration from an exported Search schema")
    result.add_argument("--search-endpoint", help="HTTPS Azure AI Search service endpoint; defaults to AZURE_SEARCH_ENDPOINT")
    result.add_argument("--shadow-action", choices=("get", "validate", "create"), default="validate")
    result.add_argument("--shadow-index-name", default="bc-pilot-public-v2")
    result.add_argument("--live-index-name", default="bc-pilot-public")
    result.add_argument("--programme", type=Path, default=DEFAULT_PROGRAMME)
    result.add_argument("--programme-manifest", type=Path, help="Separate full-programme manifest.json; never the sample ledger")
    result.add_argument("--programme-store", choices=("local", "azure-blob"), default="local")
    result.add_argument("--blob-account-url", help="HTTPS account endpoint only; no keys, SAS or connection strings")
    result.add_argument("--candidate-container", help="Existing writable private candidate container")
    result.add_argument("--run-prefix", help="Stable Blob object prefix; reuse it on every ephemeral execution")
    result.add_argument("--initialize", action="store_true", help="Conditionally create a new Blob run; never reset an existing one")
    result.add_argument("--rights-container", help="Separate read-only rights-review container")
    result.add_argument("--rights-blob", help="Current rights-review object name, not a signed URL")
    result.add_argument("--rights-sha256", help="Exact SHA-256 of the read-only rights file bytes")
    result.add_argument("--rights-file", type=Path, help="Local canonical rights JSON for the publisher-only upload command")
    result.add_argument("--from-ledger", type=Path, help="Read-only source ledger for archived HTML re-extraction")
    result.add_argument("--document-id", help="Exact canonical document ID for archived re-extraction")
    result.add_argument("--snapshot-version", help="Exact archived version; defaults to the active or latest snapshot")
    result.add_argument("--response-file", type=Path, help="Archived publisher HTML whose hash must match the source snapshot")
    result.add_argument(
        "--adapter",
        choices=(
            "icbc-rendered", "icbc-feed", "workbc-static", "workbc-feed",
            "bc-laws-civix",
        ),
        help="Explicit offline source adapter; never fetches or publishes",
    )
    result.add_argument("--source-url", help="Exact official URL represented by an offline adapter fixture")
    result.add_argument("--checked-at", help="Explicit ISO acquisition/check timestamp for an offline adapter fixture")
    result.add_argument("--evidence-url", help="Official evidence URL for legal/feed provenance")
    result.add_argument("--allow-historical", action="store_true", help="Parse explicit non-current legal XML without claiming it is current")
    result.add_argument("--rights-review", type=Path, help="Exact programme-bound publisher/path/format permission evidence")
    result.add_argument("--acquire", action="store_true", help="Explicitly acquire candidates; programme defaults to offline review")
    result.add_argument("--resume", action="store_true", help="Resume without resetting cumulative budgets or review identity")
    result.add_argument("--pause", action="store_true", help="Request a durable pause at the next request boundary")
    result.add_argument("--request-budget", type=int)
    result.add_argument("--byte-budget", type=int)
    result.add_argument("--max-candidates", type=int)
    result.add_argument("--max-retries", type=int)
    result.add_argument("--batch-requests", type=int, default=25)
    result.add_argument("--run-seconds", type=int, default=120)
    result.add_argument("--credential", choices=("managed-identity", "azure-cli"),
                        default="managed-identity", help="Explicit publisher identity; never an automatic fallback")
    return result


def _entries(values, catalog):
    from urllib.parse import urlsplit
    sources = {source["id"]: source for source in catalog["sources"]}
    entries = []
    for value in values:
        if "=" not in value:
            raise AcquisitionError("--url must be SOURCE_ID=HTTPS_URL")
        source_id, url = value.split("=", 1)
        if source_id not in sources:
            raise AcquisitionError("Unknown acquisition source id")
        normalized = canonicalize(url)
        if urlsplit(normalized).hostname != urlsplit(sources[source_id]["url"]).hostname:
            raise AcquisitionError("Acquisition source reference must match its publisher host")
        entries.append((source_id, normalized))
    return entries


def _adapt_source(args):
    if (
        not all((args.adapter, args.response_file, args.source_url))
        or any((
            args.execute, args.approved, args.create_index, args.stage_blob, args.url,
            args.review_manifest, args.rights_review, args.acquire, args.resume,
            args.pause, args.initialize,
        ))
    ):
        raise AcquisitionError(
            "Offline source adaptation requires only --adapter, --response-file, "
            "--source-url and optional timestamp/evidence arguments"
        )
    checked_at = args.checked_at or utc_now()
    iso_datetime(checked_at)
    if args.allow_historical and args.adapter != "bc-laws-civix":
        raise AcquisitionError("--allow-historical applies only to the BC Laws CiviX adapter")
    body = args.response_file.read_bytes()
    source_url = canonicalize(args.source_url)
    exclusions = []
    if args.adapter == "icbc-rendered":
        from .source_adapters import adapt_icbc_rendered_html
        adapted = adapt_icbc_rendered_html(
            Response(source_url, 200, {"content-type": "text/html"}, body, checked_at),
            complete_main=True,
        )
    elif args.adapter == "icbc-feed":
        from .source_adapters import adapt_icbc_publisher_feed
        adapted = adapt_icbc_publisher_feed(
            Response(source_url, 200, {"content-type": "application/feed+json"}, body, checked_at)
        )
    elif args.adapter == "workbc-static":
        from .source_adapters import adapt_workbc_static_html
        adapted = adapt_workbc_static_html(
            Response(source_url, 200, {"content-type": "text/html"}, body, checked_at)
        )
    elif args.adapter == "workbc-feed":
        from .source_adapters import adapt_workbc_publisher_feed
        feed = adapt_workbc_publisher_feed(
            Response(source_url, 200, {"content-type": "application/feed+json"}, body, checked_at)
        )
        adapted, exclusions = feed.documents, feed.excluded
        if not adapted:
            raise AcquisitionError("WorkBC feed contains no approved static guidance records")
    else:
        from .legal_xml import parse_bc_laws_civix
        adapted = parse_bc_laws_civix(
            Response(source_url, 200, {"content-type": "application/xml"}, body, checked_at),
            evidence_url=args.evidence_url or source_url,
            require_current=not args.allow_historical,
        )
    from .adapter_bundle import write_adapter_bundle
    output = guarded_output(args.output) / "source-adapters" / args.adapter
    result = write_adapter_bundle(adapted, output)
    for key in ("ledger", "reviewCandidates", "chunkArtifact"):
        result[key] = display_path(result[key])
    result["adapter"] = args.adapter
    if exclusions:
        result["excludedRecords"] = exclusions
    return result


def _programme(args, catalog, *, publishing=False):
    if args.max_pages != 25:
        raise AcquisitionError("--max-pages is the manual sample cap, not a full-programme override; use --request-budget")
    if not publishing and (args.execute or args.approved or args.create_index or args.stage_blob):
        raise AcquisitionError("Programme acquisition never publishes; use the separate review-gated publish command")
    if args.programme_store == "azure-blob":
        from .azure_blob import blob_runtime
        if args.programme_manifest or args.rights_review:
            raise AcquisitionError("Blob mode does not read local manifest/rights files; specify the durable run and read-only rights blob")
        if args.initialize and (args.resume or args.pause or publishing):
            raise AcquisitionError("--initialize cannot resume, pause or publish an existing run")
        if (args.acquire or publishing) and not all((args.rights_container, args.rights_blob, args.rights_sha256)):
            raise AcquisitionError("Blob acquisition/publication requires the separate pinned read-only rights input")
        with blob_runtime(
            args.blob_account_url or os.environ.get("AZURE_STORAGE_ACCOUNT_URL"),
            args.candidate_container, args.run_prefix,
            credential_mode=args.credential, initialize=args.initialize,
            rights_container=args.rights_container, rights_blob=args.rights_blob,
            rights_sha256=args.rights_sha256,
        ) as (store, rights):
            return _run_programme(args, catalog, store, rights, publishing=publishing, remote=True)
    if any((args.blob_account_url, args.candidate_container, args.run_prefix, args.initialize,
            args.rights_container, args.rights_blob, args.rights_sha256)):
        raise AcquisitionError("Blob arguments require explicit --programme-store azure-blob")
    manifest_path = args.programme_manifest or args.output / "programme" / "manifest.json"
    if manifest_path.name != "manifest.json":
        raise AcquisitionError("Full programme state must use a separate manifest.json, never state.json or a review file")
    store = JsonManifestStore(manifest_path)
    rights = json.loads(args.rights_review.read_text(encoding="utf-8")) if args.rights_review else None
    return _run_programme(args, catalog, store, rights, publishing=publishing)


def _run_programme(args, catalog, store, rights, *, publishing=False, remote=False):
    from .programme import ProgrammeRun
    from .programme_policy import ProgrammePolicy
    if args.pause:
        if args.acquire or args.resume or publishing or (not remote and store.load() is None):
            raise AcquisitionError("Pause targets an existing programme and cannot also acquire or publish")
        store.request_pause()
        return {"mode": "full-programme", "pauseRequested": True}
    if publishing and rights is None:
        raise AcquisitionError("Programme publishing requires its explicit --rights-review; omission is not a withdrawal decision")
    programme = json.loads(args.programme.read_text(encoding="utf-8"))
    policy = ProgrammePolicy(programme, catalog, rights)
    with store:
        existing = store.load()
        if publishing and existing is None:
            raise AcquisitionError("No candidate manifest exists; publication cannot create acquisition state")
        overrides = {
            key: value for key, value in {
                "total_requests": args.request_budget, "total_bytes": args.byte_budget,
                "max_candidates": args.max_candidates, "max_retries": args.max_retries,
            }.items() if value is not None
        }
        limits = ProgrammeLimits(**{
            **(existing["limits"] if existing else ProgrammeLimits().to_dict()), **overrides,
        }) if overrides else None
        selected = _entries(args.url, catalog)
        runner = ProgrammeRun(
            policy, store, limits=limits, seeds=[url for _, url in selected] if selected else None,
            response_store=store.objects if remote else LocalResponseStore(store.path.parent / "responses"),
        )

        def artifact(name, value):
            if remote:
                key = store.objects.put_json(value)
                runner.state.setdefault("artifacts", {})[name] = key
                runner.state.setdefault("artifactOrigins", {})[name] = {
                    "sourceRevision": runner.state["revision"],
                    "kind": "scope-input" if name.startswith("inputs/") else "derived-report",
                }
                return store.objects.uri(key)
            target = store.path.parent.joinpath(*name.split("/"))
            guarded_output(target.parent)
            save_json(target, value)
            return display_path(target)

        if remote:
            artifact("inputs/programme.json", programme)
            artifact("inputs/catalog.json", catalog)
            runner._save()
        result = runner.report() if publishing else runner.run(
            acquire=args.acquire, resume=args.resume,
            batch_requests=args.batch_requests, run_seconds=args.run_seconds,
        )
        if remote:
            review_candidates, review_next = store.review_page(args.review_page_size, args.review_after)
        else:
            review_candidates, review_next = runner.ledger.review_candidates(), None
        review_candidates_path = artifact("review-required.json", {
            "publisherPermissionConfirmed": False,
            "notice": "Candidates only. This file is not an approval; an accountable owner must review exact hashes.",
            "documents": review_candidates,
            **({"scope": "bounded-index-page", "nextAfter": review_next,
                "sourceRevision": runner.state["revision"],
                "hashValidation": "Cached extraction identities; publication still recomputes exact content and review hashes"}
               if remote else {}),
        })
        if args.review_manifest or publishing:
            from .azure_publish import publish
            review = json.loads(args.review_manifest.read_text(encoding="utf-8")) if args.review_manifest else None
            if args.execute and review is None:
                raise AcquisitionError("Execution requires an exact-hash --review-manifest")
            plan = build_publish_plan(runner.ledger, catalog, review, programme_policy=policy)
            result["reviewPlan"] = artifact("plans/" + digest(plan) + ".json", plan)
            if review is not None:
                reviewed = {
                    "reviewManifestHash": digest(review),
                    "approvedDocuments": sorted({doc["documentId"] for doc in plan["uploads"]}),
                    "approvedVersions": sorted({doc["documentVersion"] for doc in plan["uploads"]}),
                    "planHash": digest(plan),
                }
                if reviewed not in runner.state["reviewPlans"]:
                    runner.state["reviewPlans"].append(reviewed)
            runner._save()
            result["publication"] = publish(
                plan, execute=args.execute if publishing else False, approved=args.approved,
                create_index=args.create_index, stage_blob=args.stage_blob, credential_mode=args.credential,
            )
            if result["publication"]["mode"] == "published":
                runner.ledger.acknowledge(plan)
            runner._save()
        coverage = runner.report()
        coverage_path = artifact("coverage.json", coverage)
        runner._save()
        return {
            **result, **coverage, "programmeStore": args.programme_store,
            "reviewCandidates": review_candidates_path, "coverage": coverage_path,
            **({"manifest": store.container.url.rstrip("/") + "/" + store.prefix + "/manifest.json",
                "storage": dict(store.metrics)} if remote else {}),
        }


def main(argv=None) -> int:
    if argv is None and os.environ.get("BC_INSPECT_CONTROL") == "1":
        argv = ["blob-inspect"]
    args = parser().parse_args(argv)
    try:
        if args.command == "adapt-source":
            print(json.dumps(_adapt_source(args), indent=2))
            return 0
        if args.command == "shadow-index":
            if any((
                args.approved,
                args.create_index,
                args.stage_blob,
                args.vector_dimensions is not None,
                args.existing_schema,
                args.url,
                args.review_manifest,
                args.programme_manifest,
                args.rights_review,
                args.acquire,
                args.resume,
                args.pause,
                args.initialize,
            )):
                raise AcquisitionError(
                    "Shadow index operations accept only endpoint, live/shadow names, "
                    "action, credential, and --execute for create; they never publish content"
                )
            from .azure_publish import shadow_index_operation
            result = shadow_index_operation(
                args.search_endpoint or os.environ.get("AZURE_SEARCH_ENDPOINT"),
                operation=args.shadow_action,
                shadow_index_name=args.shadow_index_name,
                live_index_name=args.live_index_name,
                execute=args.execute,
                credential_mode=args.credential,
            )
            print(json.dumps(result, indent=2))
            return 0 if args.shadow_action == "get" or result["valid"] else 2
        catalog = load_catalog(args.catalog)
        if args.command == "rights-upload":
            if (
                not all((
                    args.blob_account_url,
                    args.rights_container,
                    args.rights_blob,
                    args.rights_sha256,
                    args.run_prefix,
                ))
                or args.credential != "managed-identity"
                or any((
                    args.approved,
                    args.create_index,
                    args.stage_blob,
                    args.url,
                    args.review_manifest,
                    args.rights_review,
                    args.programme_manifest,
                    args.from_ledger,
                    args.document_id,
                    args.snapshot_version,
                    args.response_file,
                    args.adapter,
                    args.source_url,
                    args.checked_at,
                    args.evidence_url,
                    args.allow_historical,
                    args.acquire,
                    args.resume,
                    args.pause,
                    args.initialize,
                ))
            ):
                raise AcquisitionError(
                    "Rights upload accepts only the explicit Blob target, run prefix, exact hash, "
                    "canonical input, managed identity and optional --execute"
                )
            from .rights_upload import upload_rights_review

            programme = json.loads(args.programme.read_text(encoding="utf-8"))
            print(
                json.dumps(
                    upload_rights_review(
                        args.blob_account_url,
                        args.rights_container,
                        args.rights_blob,
                        args.run_prefix,
                        args.rights_sha256,
                        programme,
                        catalog,
                        rights_file=args.rights_file,
                        execute=args.execute,
                    ),
                    indent=2,
                )
            )
            return 0
        if args.rights_file:
            raise AcquisitionError("--rights-file applies only to the publisher-only rights-upload command")
        if args.command != "programme" and (args.acquire or args.resume or args.pause or args.initialize):
            raise AcquisitionError("--acquire/--resume/--pause/--initialize only apply to the explicit programme command")
        if args.command == "programme" or (args.command == "publish" and (args.programme_manifest or args.programme_store == "azure-blob")):
            result = _programme(args, catalog, publishing=args.command == "publish")
            print(json.dumps(result, indent=2))
            return 1 if result.get("status") == "paused" else 0
        if args.command == "reextract":
            from .pipeline import reextract_snapshot
            if not all((args.from_ledger, args.document_id, args.response_file)) or args.execute or args.programme_store != "local":
                raise AcquisitionError("Offline re-extraction needs --from-ledger, --document-id and --response-file; it never acquires or publishes")
            result = reextract_snapshot(
                args.from_ledger, args.document_id, args.response_file, catalog, args.output,
                snapshot_version=args.snapshot_version,
            )
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "open-data-service-bc":
            if not args.execute or any(
                (
                    args.approved,
                    args.create_index,
                    args.stage_blob,
                    args.url,
                    args.review_manifest,
                    args.rights_review,
                    args.acquire,
                    args.resume,
                    args.pause,
                    args.initialize,
                )
            ):
                raise AcquisitionError(
                    "Service BC open-data acquisition requires only explicit --execute; "
                    "it creates an unapproved candidate artifact and never publishes"
                )
            from .open_data import acquire_service_bc_candidate

            output = guarded_output(args.output) / "open-data"
            output.mkdir(parents=True, exist_ok=True)
            candidate = acquire_service_bc_candidate()
            target = output / f"service-bc-office-locations-{candidate['reviewHash'][:12]}.json"
            save_json(target, candidate)
            bundle = None
            if candidate.get("records"):
                from .adapter_bundle import write_adapter_bundle
                from .service_directory import build_service_bc_directory_document
                bundle = write_adapter_bundle(
                    build_service_bc_directory_document(candidate),
                    output / "service-directory",
                )
            print(
                json.dumps(
                    {
                        "mode": "candidate-only",
                        "sourceId": "service-bc",
                        "records": candidate["recordCount"],
                        "reviewHash": candidate["reviewHash"],
                        "contentHash": candidate["contentHash"],
                        "artifact": display_path(target),
                        "publicationApproved": False,
                        **({"serviceDirectoryReview": {
                            key: (
                                display_path(value)
                                if key in {"ledger", "reviewCandidates", "chunkArtifact"}
                                else value
                            )
                            for key, value in bundle.items()
                        }} if bundle else {}),
                    },
                    indent=2,
                )
            )
            return 0
        if args.command == "blob-inspect":
            account_url = args.blob_account_url or os.environ.get("AZURE_STORAGE_ACCOUNT_URL")
            candidate_container = args.candidate_container or os.environ.get(
                "BC_CANDIDATE_CONTAINER"
            )
            run_prefix = args.run_prefix or os.environ.get("BC_RUN_PREFIX")
            if (
                not all((account_url, candidate_container, run_prefix))
                or any(
                    (
                        args.execute,
                        args.approved,
                        args.create_index,
                        args.stage_blob,
                        args.url,
                        args.review_manifest,
                        args.rights_review,
                        args.acquire,
                        args.resume,
                        args.pause,
                        args.initialize,
                    )
                )
            ):
                raise AcquisitionError(
                    "Blob inspection requires only the explicit Azure Blob account, "
                    "candidate container, stable run prefix and credential mode"
                )
            from .azure_blob import inspect_blob_control

            print(
                json.dumps(
                    inspect_blob_control(
                        account_url,
                        candidate_container,
                        run_prefix,
                        credential_mode=args.credential,
                    ),
                    indent=2,
                )
            )
            return 0
        if args.command == "validate":
            print(json.dumps({"valid": True, "sources": len(catalog["sources"]),
                              "journeys": len(catalog["journeys"]), "locations": len(catalog["locations"])}))
            return 0
        if args.command == "index-schema":
            from .azure_publish import build_index, merge_index_schema
            schema = build_index(args.index_name, args.vector_dimensions)
            if args.existing_schema:
                from azure.search.documents.indexes.models import SearchIndex
                current = SearchIndex.deserialize(json.loads(args.existing_schema.read_text(encoding="utf-8")))
                schema = merge_index_schema(current, schema)
            print(json.dumps(schema.serialize(), indent=2))
            return 0
        if args.command == "publish":
            from .azure_publish import publish
            output = guarded_output(args.output)
            ledger = Ledger.load(output / "state.json")
            review = json.loads(args.review_manifest.read_text(encoding="utf-8")) if args.review_manifest else None
            if args.execute and review is None:
                raise AcquisitionError("Execution requires an exact-hash --review-manifest")
            plan = build_publish_plan(ledger, catalog, review)
            save_json(output / "publish-plan.json", plan)
            result = publish(plan, execute=args.execute, approved=args.approved,
                             create_index=args.create_index, stage_blob=args.stage_blob,
                             credential_mode=args.credential)
            if result["mode"] == "published":
                ledger.acknowledge(plan)
                save_json(output / "state.json", ledger.state)
            print(json.dumps(result))
            return 0
        entries = _entries(args.url, catalog)
        if args.command == "dry-run":
            Fetcher(max_pages=args.max_pages)
            planned = []
            for source_id, url in entries:
                try:
                    validate_url(url)
                    planned.append({"sourceId": source_id, "url": url, "status": "robots-and-review-required"})
                except AcquisitionError as exc:
                    planned.append({"sourceId": source_id, "url": url, "status": "blocked", "reason": str(exc)})
            print(json.dumps({
                "mode": "dry-run", "networkRequests": 0, "maxDocumentRequests": args.max_pages,
                "bulkApproved": False, "publishEnabled": False, "urls": planned,
                "publisherHolds": {host: p.hold for host, p in PUBLISHERS.items() if p.hold},
            }, indent=2))
            return 0
        if not entries:
            raise AcquisitionError("Discover/extract requires explicitly selected --url entries; no recursive crawl")
        output = guarded_output(args.output)
        ledger = Ledger.load(output / "state.json")
        result = ledger.acquire(entries, catalog, output, Fetcher(max_pages=args.max_pages))
        if args.command == "discover":
            candidates = {}
            for entry in ledger.state["documents"].values():
                if not entry["versions"]:
                    continue
                for link in entry["versions"][-1]["document"]["links"]:
                    try:
                        normalized = validate_url(link["url"])
                    except AcquisitionError:
                        continue
                    candidates[normalized] = {"url": normalized, "label": link["label"],
                                              "status": "candidate-not-fetched-or-approved"}
            result["candidates"] = list(candidates.values())[:100]
            save_json(output / "discovery.json", result)
        print(json.dumps(result, indent=2))
        return 1 if any(x["status"] == "blocked" for x in result["results"]) else 0
    except (AcquisitionError, OSError, json.JSONDecodeError, ImportError) as exc:
        message = "Optional SDK missing; install the declared [azure] extra." if isinstance(exc, ImportError) else str(exc)
        print(json.dumps({"error": message}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
