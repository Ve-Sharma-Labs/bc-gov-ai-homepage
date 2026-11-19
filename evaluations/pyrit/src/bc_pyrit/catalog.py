"""Pinned data shared with CI, translated to native PyRIT seeds without execution."""

import csv
import hashlib
import io
import json
import uuid
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

import httpx
import pyrit
from pyrit.memory import MemoryInterface
from pyrit.models import AttackSeedGroup, SeedDataset, SeedObjective, SeedPrompt

from bc_pyrit.contracts import Case, CheckError, Dataset, digest, load_dataset

ROOT = Path(__file__).resolve().parents[4]
MAX_SOURCE_BYTES = 512_000


def fixed_blocker(case: Case) -> str | None:
    if "live" not in case.profiles or case.offline_check:
        return "Offline fixture only; not a live prompt"
    if case.approach == "adaptive-multi-turn":
        return "Requires an approved attacker and judge model"
    if case.sharing_probe or case.isolation_probe:
        return "Requires CI sharing/session-isolation controls"
    return None


@dataclass
class Catalog:
    suite: Dataset
    suite_hash: str
    pack_hash: str
    datasets: list[SeedDataset]
    templates: list[SeedPrompt]
    skipped: dict[str, str]
    converters: list[str]

    @property
    def fixed_name(self) -> str:
        return f"bcgov-fixed-{self.suite_hash[:12]}"

    @property
    def names(self) -> list[str]:
        return [dataset.dataset_name for dataset in self.datasets]

    def groups(self, name: str) -> list[AttackSeedGroup]:
        dataset = next(d for d in self.datasets[:2] if d.dataset_name == name)
        return [AttackSeedGroup(seeds=group.seeds) for group in dataset.seed_groups]

    def summary(self) -> dict:
        return {
            "suiteSha256": self.suite_hash,
            "packSha256": self.pack_hash,
            "datasets": {
                dataset.dataset_name: len(dataset.seed_groups)
                for dataset in self.datasets
            },
            "skippedCases": self.skipped,
            "scoring": "Review required; no semantic pass/fail or CI qualification",
            "helperModels": "Not configured; adaptive attacks and AI scoring are not ready",
        }


def _checked_bytes(path: Path, expected: str) -> bytes:
    if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
        raise CheckError("DATA_SOURCE_MISSING_OR_TOO_LARGE")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected:
        raise CheckError("DATA_SOURCE_HASH_MISMATCH")
    return content


def prepare_sources(root: Path = ROOT, *, download: bool = True) -> dict:
    pack_path = root / "data" / "evaluations" / "pyrit-local-pack.json"
    pack = json.loads(pack_path.read_bytes())
    if pack["version"] != 1 or version("pyrit") != pack["pyrit_version"]:
        raise CheckError("PYRIT_VERSION_MISMATCH")
    converters = pack["converters"]
    if (
        not isinstance(converters, list) or len(set(converters)) != len(converters)
        or not set(converters) <= {"base64", "rot13", "char_swap", "leetspeak"}
    ):
        raise CheckError("UNSUPPORTED_LOCAL_CONVERTER")
    suite_path = pack_path.parent / pack["suite_file"]
    if suite_path.parent != pack_path.parent or suite_path.suffix != ".json":
        raise CheckError("INVALID_SUITE_PATH")
    load_dataset(suite_path)
    if digest(json.loads(suite_path.read_bytes())) != pack["suite_sha256"]:
        raise CheckError("SUITE_HASH_MISMATCH")
    cache = root / ".cache" / "copyrit" / "datasets" / "xstest.csv"
    source = pack["xstest"]
    if not cache.exists():
        if not download:
            raise CheckError("STARTER_CACHE_MISSING")
        # Only the reviewed public data URL is fetched, never code or model weights.
        if not source["url"].startswith(
            "https://raw.githubusercontent.com/paul-rottger/exaggerated-safety/"
        ):
            raise CheckError("UNAPPROVED_DATA_SOURCE")
        try:
            with httpx.stream("GET", source["url"], timeout=45, follow_redirects=False) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    if len(content) + len(chunk) > MAX_SOURCE_BYTES:
                        raise CheckError("DATA_SOURCE_MISSING_OR_TOO_LARGE")
                    content.extend(chunk)
        except httpx.HTTPError:
            raise CheckError("DATA_DOWNLOAD_FAILED") from None
        if hashlib.sha256(content).hexdigest() != source["sha256"]:
            raise CheckError("DATA_SOURCE_HASH_MISMATCH")
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_suffix(".tmp")
        temporary.write_bytes(content)
        temporary.replace(cache)
    _checked_bytes(cache, source["sha256"])
    return pack


def _group(
    *, name: str, key: str, objective: str, prompts: list[str], metadata: dict, source: str
) -> AttackSeedGroup:
    group_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{name}/{key}")
    common = {
        "dataset_name": name, "prompt_group_id": group_id, "metadata": metadata,
        "source": source, "added_by": "bc-pyrit-local",
    }
    return AttackSeedGroup(seeds=[
        SeedObjective(value=objective, **common),
        *[
            SeedPrompt(
                value=text, data_type="text", role="user", sequence=index, **common,
            )
            for index, text in enumerate(prompts)
        ],
    ])


def load_catalog(root: Path = ROOT) -> Catalog:
    pack = prepare_sources(root, download=False)
    suite_path = root / "data" / "evaluations" / pack["suite_file"]
    suite = load_dataset(suite_path)
    suite_hash = digest(json.loads(suite_path.read_bytes()))
    name = f"bcgov-fixed-{suite_hash[:12]}"
    groups = []
    skipped = {}
    for case in suite.cases:
        reason = fixed_blocker(case)
        if reason:
            skipped[case.id] = reason
            continue
        for variant in case.variants:
            metadata = {
                "suite_sha256": suite_hash, "case_id": case.id, "variant_id": variant.id,
                "case": case.model_dump(mode="json", exclude_unset=True),
                "repetitions": case.repetitions,
            }
            groups.append(_group(
                name=name, key=f"{case.id}/{variant.id}", objective=case.objective,
                prompts=variant.prompts, metadata=metadata,
                source="data/evaluations/pyrit-conversation-cases.json",
            ))
    datasets = [SeedDataset(dataset_name=name, seeds=[s for g in groups for s in g.seeds])]
    raw = _checked_bytes(
        root / ".cache" / "copyrit" / "datasets" / "xstest.csv", pack["xstest"]["sha256"]
    )
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if len(rows) != pack["xstest"]["rows"]:
        raise CheckError("DATASET_COUNT_MISMATCH")
    starter = []
    for index, row in enumerate(rows):
        prompt = row["prompt"]
        if not prompt.strip() or len(prompt) > 4000:
            raise CheckError("UNSUPPORTED_STARTER_PROMPT")
        starter.append(_group(
            name=f"bcgov-xstest-{pack['xstest']['sha256'][:12]}", key=str(index),
            objective="Review the response against the XSTest safe/contrast annotation.",
            prompts=[prompt],
            metadata={
                "source_sha256": pack["xstest"]["sha256"], "row": index,
                "type": row["type"], "note": row.get("note", ""), "focus": row.get("focus", ""),
                "license": pack["xstest"]["license"], "authors": pack["xstest"]["attribution"],
            },
            source=pack["xstest"]["url"],
        ))
    datasets.append(SeedDataset(
        dataset_name=starter[0].objective.dataset_name,
        seeds=[s for g in starter for s in g.seeds],
    ))
    templates = []
    for entry in pack["templates"]:
        if Path(entry["file"]).name != entry["file"]:
            raise CheckError("INVALID_TEMPLATE_PATH")
        path = Path(pyrit.__file__).parent / "datasets" / "jailbreak" / "templates" / entry["file"]
        _checked_bytes(path, entry["sha256"])
        template = SeedPrompt.from_yaml_file(path)
        if template.parameters != ["prompt"]:
            raise CheckError("UNSUPPORTED_TEMPLATE_PARAMETERS")
        template.dataset_name = f"bcgov-templates-{digest(pack)[:12]}"
        template.name = entry["file"].removesuffix(".yaml")
        template.metadata = {
            **(template.metadata or {}), "license": pack["template_license"],
            "source_sha256": entry["sha256"], "template_only": True,
            "source_commit": pack["pyrit_source_commit"],
        }
        templates.append(template)
    datasets.append(SeedDataset(dataset_name=templates[0].dataset_name, seeds=templates))
    return Catalog(
        suite, suite_hash, digest(pack), datasets, templates, skipped, pack["converters"]
    )


async def import_catalog(memory: MemoryInterface, catalog: Catalog) -> dict:
    # Validate/prepare every source before any write, then use native idempotent imports.
    await memory.add_seed_datasets_to_memory_async(
        datasets=catalog.datasets, added_by="bc-pyrit-local"
    )
    summaries = {
        item.dataset_name: item for item in await memory.get_seed_dataset_summaries_async()
    }
    for dataset in catalog.datasets:
        summary = summaries.get(dataset.dataset_name)
        if summary is None or summary.seed_pieces != len(dataset.seeds):
            raise CheckError("DATASET_IMPORT_INCOMPLETE")
    result = catalog.summary()
    result["datasets"] = {
        name: {
            "examples": summaries[name].logical_examples,
            "pieces": summaries[name].seed_pieces,
        }
        for name in catalog.names
    }
    return result
