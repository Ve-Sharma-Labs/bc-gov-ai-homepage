"""Deployment-owned jurisdiction packs. Selection is never a request parameter."""

import json
import os
import re
import shutil
from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import cached_property, lru_cache
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

CONTENT_KEYS = (
    "catalog", "groundingPacks", "personas", "programmeRules", "sourceProgramme", "provenance"
)
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
HOST = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$")


def repository_root() -> Path:
    # Installed wheels have no repository ancestry. Docker retains packs under /app;
    # cwd ancestry also permits installed local packages without relying on PRODUCT.md.
    for base in (Path(__file__).resolve(), Path.cwd().resolve(), Path("/app")):
        for parent in (base, *base.parents):
            if (parent / "jurisdictions").is_dir():
                return parent
    raise ValueError("Jurisdiction packs are missing; package jurisdictions under /app.")


def content_path(relative: str, root: Path) -> Path:
    if (
        not isinstance(relative, str)
        or not relative
        or "\\" in relative
        or ":" in relative
        or any(part in ("", ".", "..") for part in relative.split("/"))
    ):
        raise ValueError("Jurisdiction content paths must remain relative to the repository.")
    candidate = root.joinpath(*relative.split("/")).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError("Jurisdiction content path escapes the repository.")
    return candidate


def read_json(path: Path) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate jurisdiction JSON property: {key}.")
            result[key] = value
        return result

    try:
        if path.stat().st_size > 2_000_000:
            raise ValueError("Jurisdiction file exceeds its size limit.")
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
        if not isinstance(value, dict):
            raise ValueError("Jurisdiction files must be JSON objects.")
        return value
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Required jurisdiction file unavailable or invalid: {path}.") from exc


@dataclass(frozen=True)
class JurisdictionPack:
    root: Path
    manifest: dict

    @property
    def id(self) -> str:
        return self.manifest["id"]

    @property
    def guided_journeys(self) -> bool:
        return self.manifest["features"]["guidedJourneys"]

    @property
    def synthetic_context(self) -> bool:
        return self.manifest["features"]["syntheticContext"]

    @property
    def rag_pending(self) -> bool:
        return self.id != "bc" and (
            self.manifest["sourcePolicy"]["approvalStatus"] != "reviewed-operation-grants"
        )

    @property
    def identity(self) -> dict:
        from bc_ingestion.metadata import digest

        return {"jurisdictionId": self.id, "manifestHash": digest(self.manifest)}

    @property
    def pending_identity(self) -> dict | None:
        if self.rag_pending or self.id != "sk":
            return None
        from bc_ingestion.metadata import digest

        pending = deepcopy(self.manifest)
        pending["sourcePolicy"]["approvalStatus"] = "pending-rag-permission"
        pending["sourcePolicy"].pop("operationReview", None)
        return {"jurisdictionId": self.id, "manifestHash": digest(pending)}

    @property
    def research_hosts(self) -> tuple[str, ...]:
        return tuple(self.manifest["researchHosts"])

    def output(self, requested: Path) -> Path:
        path = requested.resolve()
        base = self.root / "jurisdictions" / self.id
        if not any(
            path.is_relative_to((base / folder).resolve()) for folder in ("content", "ingestion")
        ):
            raise ValueError("Operation review/evidence must remain in the selected pack.")
        return path

    def rights_path(self, requested: Path) -> Path:
        return self.output(requested)

    @cached_property
    def operation_provider(self):
        from bc_ingestion.operation_rights import OperationRightsProvider

        locator = self.manifest["sourcePolicy"].get("operationReview")
        if not isinstance(locator, dict) or set(locator) != {"path"}:
            raise ValueError("Reviewed source policy requires operationReview with only a path.")
        path = self.output(content_path(locator["path"], self.root))
        pin = os.environ.get("OPERATION_RIGHTS_REVIEW_SHA256", "")
        if not re.fullmatch(r"[a-f0-9]{64}", pin):
            raise ValueError(
                "Reviewed source policy requires independent OPERATION_RIGHTS_REVIEW_SHA256."
            )
        stamp = self.root / "jurisdictions" / ".operation-rights-review.sha256"
        if stamp.is_file() and stamp.read_text(encoding="utf-8").strip() != pin:
            raise ValueError("Operation rights pin does not match this image's baked review.")
        provider = OperationRightsProvider(
            path, pin, self, read_json(self.path("sourceProgramme"))
        )
        if not any(
            all(grant["decisions"][operation]["status"] == "granted"
                for operation in ("rag", "generated-summary", "publication"))
            for grant in provider.grants.values()
        ):
            raise ValueError(
                "Reviewed source policy has no explicit RAG/summary/publication grant."
            )
        return provider

    def authorize_source(
        self, url: str, *, document_format: str | None = None, embedding: bool = False,
    ) -> None:
        if self.id == "bc":
            return
        if self.rag_pending:
            raise ValueError("pending-rag-permission: no factual source activation is permitted.")
        provider = self.operation_provider
        provider.assert_binding(self, read_json(self.path("sourceProgramme")))
        if document_format is not None and document_format not in {"html", "pdf"}:
            raise ValueError("Only a validated reviewed document format may select source grants.")
        # Catalogue/bootstrap checks have no acquired document. They establish
        # scope availability only; retrieved evidence always supplies validated provenance.
        formats = (
            (document_format,) if document_format is not None else tuple(
                format for format in ("html", "pdf")
                if format in provider.grants.get(urlsplit(url).hostname, {}).get("formats", [])
            )
        )
        if not formats:
            raise ValueError("No exact-publisher reviewed HTML/PDF operation format grant.")
        failure = None
        for format in formats:
            try:
                for operation in ("rag", "generated-summary", "publication"):
                    provider.authorize(operation, url, format=format)
                if embedding:
                    provider.authorize("embedding", url, format=format)
            except ValueError as exc:
                failure = exc
            else:
                return
        raise failure

    def path(self, key: str) -> Path:
        path = content_path(self.manifest["content"][key], self.root)
        if self.id != "bc" and not path.is_relative_to(
            (self.root / "jurisdictions" / self.id / "content").resolve()
        ):
            raise ValueError("Non-BC content must belong to the selected jurisdiction pack.")
        return path

    def prompt(self, name: str) -> str:
        if name not in ("agent", "general", "dialogue"):
            raise ValueError("Unknown jurisdiction prompt.")
        path = self.root / "jurisdictions" / self.id / "prompts" / f"{name}.txt"
        if not path.resolve().is_relative_to(
            (self.root / "jurisdictions" / self.id).resolve()
        ):
            raise ValueError("Jurisdiction prompt path escapes the selected pack.")
        try:
            if path.stat().st_size > 100_000:
                raise ValueError("Jurisdiction prompt exceeds its size limit.")
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"Required jurisdiction prompt missing: {path}.") from exc

    def flow_registry(self) -> tuple[str, ...]:
        if not self.guided_journeys and not self.synthetic_context:
            return ()
        registry_path = self.root / "jurisdictions" / self.id / "flows" / "registry.json"
        if not registry_path.resolve().is_relative_to(
            (self.root / "jurisdictions" / self.id).resolve()
        ):
            raise ValueError("Jurisdiction flow registry escapes the selected pack.")
        registry = read_json(registry_path)
        if registry.get("jurisdiction") != self.id or registry.get("schemaVersion") != 1:
            raise ValueError("Jurisdiction flow registry mismatch.")
        flows = registry.get("flows")
        if not isinstance(flows, list) or any(not isinstance(item, str) for item in flows):
            raise ValueError("Invalid jurisdiction flow registry.")
        return tuple(flows)

    def validate_disabled_content(self, key: str) -> dict:
        value = read_json(self.path(key))
        collection = {"personas": "personas", "programmeRules": "rules"}[key]
        if value != {
            "schemaVersion": 1, "jurisdiction": self.id, "available": False, collection: []
        }:
            raise ValueError(f"{key} must be an honest empty disabled jurisdiction inventory.")
        return value


def load_jurisdiction(value: str | None = None, root: Path | None = None) -> JurisdictionPack:
    selected = value if value is not None else os.environ.get("JURISDICTION", "bc")
    if not isinstance(selected, str) or not IDENTIFIER.fullmatch(selected):
        raise ValueError("JURISDICTION must be a lowercase jurisdiction identifier.")
    root = (root or repository_root()).resolve()
    baked = os.environ.get("BAKED_JURISDICTION")
    marker = root / "jurisdictions" / ".selected"
    if marker.is_file():
        stamped = marker.read_text(encoding="utf-8").strip()
        if baked and baked != stamped:
            raise ValueError("Baked jurisdiction environment and image stamp mismatch.")
        baked = stamped
    if baked and selected != baked:
        raise ValueError("JURISDICTION does not match this image's baked jurisdiction.")
    path = root / "jurisdictions" / selected / "jurisdiction.json"
    if not path.is_file():
        raise ValueError(f"Unknown jurisdiction pack: {selected}.")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Jurisdiction manifest escapes the repository.")
    manifest = read_json(path)
    if (
        type(manifest.get("schemaVersion")) is not int
        or manifest["schemaVersion"] != 1 or manifest.get("id") != selected
    ):
        raise ValueError("Jurisdiction manifest version or identity mismatch.")
    for key in (
        "name", "shortName", "inlineName", "siteTitle", "description", "locale", "timeZone"
    ):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise ValueError(f"Jurisdiction manifest requires {key}.")
    ZoneInfo(manifest["timeZone"])
    for key in ("officialDomains", "researchHosts"):
        hosts = manifest.get(key)
        if not isinstance(hosts, list) or not hosts or any(
            not isinstance(host, str) or not HOST.fullmatch(host) for host in hosts
        ):
            raise ValueError(f"Jurisdiction manifest requires valid {key}.")
    help_channel = manifest.get("helpChannel", {})
    help_url = urlsplit(help_channel.get("url", ""))
    if (
        not help_channel.get("name") or help_url.scheme != "https"
        or help_url.username or help_url.password or help_url.port
        or not any(
            help_url.hostname == domain or (help_url.hostname or "").endswith("." + domain)
            for domain in manifest["officialDomains"]
        )
    ):
        raise ValueError("Jurisdiction help channel must use an approved HTTPS publisher.")
    brand = manifest.get("brand", {})
    if (
        not isinstance(brand, dict)
        or not isinstance(brand.get("logo"), str)
        or not re.fullmatch(r"/brand/[a-z0-9-]+\.png", brand["logo"])
        or any(
            type(brand.get(key)) is not int or brand[key] < 1
            for key in ("logoWidth", "logoHeight")
        )
    ):
        raise ValueError("Jurisdiction manifest requires a valid brand asset.")
    if not isinstance(manifest.get("content"), dict):
        raise ValueError("Jurisdiction manifest requires content paths.")
    for key in CONTENT_KEYS:
        content_path(manifest["content"].get(key), root)
    features = manifest.get("features", {})
    policy = manifest.get("sourcePolicy", {})
    if (
        any(type(features.get(key)) is not bool for key in ("guidedJourneys", "syntheticContext"))
        or policy.get("trainingAllowed") is not False
        or not isinstance(policy.get("approvalStatus"), str)
    ):
        raise ValueError("Jurisdiction feature and source policy flags are required.")
    status = policy["approvalStatus"]
    supported = (
        {"existing-reviewed-snapshots-only"} if selected == "bc"
        else {"pending-rag-permission", "reviewed-operation-grants"}
    )
    if status not in supported:
        raise ValueError(
            "Unsupported sourcePolicy approvalStatus; publisher rights remain unapproved."
        )
    pack = JurisdictionPack(root, manifest)
    for key in CONTENT_KEYS:
        if not pack.path(key).is_file():
            raise ValueError(f"Required jurisdiction content file missing: {key}.")
    pack.flow_registry()
    if status == "reviewed-operation-grants":
        pack.operation_provider.assert_current()
    return pack


_active_pack: ContextVar[JurisdictionPack | None] = ContextVar("jurisdiction_pack", default=None)


def current_pack() -> JurisdictionPack:
    return _active_pack.get() or _default_pack(
        os.environ.get("JURISDICTION", "bc"), os.environ.get("BAKED_JURISDICTION", ""),
        str(Path.cwd()),
    )


@lru_cache(maxsize=8)
def _default_pack(selected: str, baked: str, cwd: str) -> JurisdictionPack:
    del baked, cwd
    return load_jurisdiction(selected)


@contextmanager
def pack_scope(pack: JurisdictionPack):
    token = _active_pack.set(pack)
    try:
        yield
    finally:
        _active_pack.reset(token)


def stage_jurisdiction(selected: str, root: Path, destination: Path) -> JurisdictionPack:
    """Copy one validated pack and its exact content references into an empty image tree."""
    root, destination = root.resolve(), destination.resolve()
    if destination.is_relative_to(root) or root.is_relative_to(destination):
        raise ValueError("Jurisdiction staging source and destination must not overlap.")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Jurisdiction staging destination must be empty.")
    pack = load_jurisdiction(selected, root)
    pack_root = root / "jurisdictions" / pack.id
    if pack_root.is_symlink():
        raise ValueError("Selected jurisdiction pack must not be a symlink.")
    for name in ("agent", "general", "dialogue"):
        pack.prompt(name)
    files = {}
    for source in pack_root.rglob("*"):
        if source.is_symlink() or not source.resolve().is_relative_to(pack_root.resolve()):
            raise ValueError("Jurisdiction staging cannot follow symlinks or foreign pack files.")
        if source.is_file():
            files[source.relative_to(root)] = source
    for key in CONTENT_KEYS:
        source = pack.path(key)
        relative = Path(*pack.manifest["content"][key].split("/"))
        if (root / relative).is_symlink() or (root / relative).resolve() != root / relative:
            raise ValueError("Jurisdiction content must not be a symlink.")
        files[relative] = source
    for relative, source in files.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    stamp = destination / "jurisdictions" / ".selected"
    stamp.write_text(pack.id, encoding="utf-8")
    if pack.manifest["sourcePolicy"]["approvalStatus"] == "reviewed-operation-grants":
        (destination / "jurisdictions" / ".operation-rights-review.sha256").write_text(
            os.environ["OPERATION_RIGHTS_REVIEW_SHA256"], encoding="utf-8"
        )
    return load_jurisdiction(pack.id, destination)


class JurisdictionMiddleware:
    def __init__(self, app, pack: JurisdictionPack) -> None:
        self.app = app
        self.pack = pack

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket", "lifespan"):
            await self.app(scope, receive, send)
            return

        async def jurisdiction_send(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-jurisdiction", self.pack.id.encode("ascii")),
                ]
            await send(message)

        with pack_scope(self.pack):
            if scope["type"] == "http":
                from starlette.datastructures import Headers, QueryParams
                from starlette.responses import JSONResponse

                query = QueryParams(scope.get("query_string", b""))
                headers = Headers(scope=scope)
                expected = headers.getlist("x-expected-jurisdiction")
                if expected and (len(expected) != 1 or expected[0] != self.pack.id):
                    await JSONResponse(
                        {"error": {
                            "code": "JURISDICTION_MISMATCH",
                            "message": "The backend jurisdiction does not match this application.",
                        }},
                        status_code=409,
                    )(scope, receive, jurisdiction_send)
                    return
                selection = {"jurisdiction", "index", "indexName"} & set(query)
                if selection or "x-jurisdiction" in headers:
                    await JSONResponse(
                        {"error": {
                            "code": "CLIENT_CONTEXT_DENIED",
                            "message": "Jurisdiction and index selection belong to the deployment.",
                        }},
                        status_code=422,
                    )(scope, receive, jurisdiction_send)
                    return
                if self.pack.id != "bc" and scope["path"].startswith((
                    "/api/demo/session", "/api/context", "/api/conversation",
                    "/api/discovery", "/api/research",
                )):
                    await JSONResponse(
                        {"error": {
                            "code": "JURISDICTION_CAPABILITY_UNAVAILABLE",
                            "message": "This jurisdiction has no approved advanced "
                            "flows or research.",
                        }},
                        status_code=503,
                    )(scope, receive, jurisdiction_send)
                    return

            await self.app(scope, receive, jurisdiction_send)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Stage only one validated jurisdiction pack.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--jurisdiction", default=os.environ.get("JURISDICTION", "bc"))
    args = parser.parse_args()
    stage_jurisdiction(args.jurisdiction, args.root, args.stage)
