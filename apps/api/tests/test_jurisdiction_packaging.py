import json
import shutil
from uuid import uuid4

import pytest

from bc_api.jurisdiction import CONTENT_KEYS, load_jurisdiction, repository_root, stage_jurisdiction


@pytest.fixture
def packaging_tree():
    repository = repository_root()
    fixture = repository / "apps" / "api" / f".pack-staging-fixture-{uuid4().hex}"
    source = fixture / "source"
    try:
        for selected in ("bc", "sk"):
            shutil.copytree(
                repository / "jurisdictions" / selected,
                source / "jurisdictions" / selected,
            )
        sk_manifest_path = source / "jurisdictions" / "sk" / "jurisdiction.json"
        sk_manifest = json.loads(sk_manifest_path.read_text(encoding="utf-8"))
        sk_manifest["sourcePolicy"]["approvalStatus"] = "pending-rag-permission"
        sk_manifest["sourcePolicy"].pop("operationReview", None)
        sk_manifest_path.write_text(json.dumps(sk_manifest), encoding="utf-8")
        (source / "data").mkdir()
        for key in CONTENT_KEYS:
            path = load_jurisdiction("bc", repository).path(key)
            shutil.copyfile(path, source / "data" / path.name)
        shutil.copytree(source / "jurisdictions" / "sk", source / "jurisdictions" / "zz")
        third = source / "jurisdictions" / "zz"
        manifest = json.loads((third / "jurisdiction.json").read_text(encoding="utf-8"))
        manifest["id"] = "zz"
        manifest["name"] = manifest["shortName"] = "Synthetic offline third jurisdiction"
        for key in CONTENT_KEYS:
            manifest["content"][key] = manifest["content"][key].replace(
                "jurisdictions/sk/", "jurisdictions/zz/"
            )
        (third / "jurisdiction.json").write_text(json.dumps(manifest), encoding="utf-8")
        for name in ("pilot-catalog", "conversation-grounding-packs", "demo-personas",
                     "demo-program-rules"):
            path = third / "content" / f"{name}.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["jurisdiction"] = "zz"
            path.write_text(json.dumps(document), encoding="utf-8")
        yield source, fixture / "output"
    finally:
        shutil.rmtree(fixture, ignore_errors=True)


@pytest.mark.parametrize("selected", ["bc", "sk", "zz"])
def test_staging_packages_only_selected_pack_and_manifest_content(packaging_tree, selected):
    source, output = packaging_tree
    pack = stage_jurisdiction(selected, source, output)
    assert pack.id == selected
    assert (output / "jurisdictions" / ".selected").read_text(encoding="utf-8") == selected
    assert {
        entry.name for entry in (output / "jurisdictions").iterdir() if entry.is_dir()
    } == {selected}
    original = load_jurisdiction(selected, source)
    for key in CONTENT_KEYS:
        assert pack.path(key).read_bytes() == original.path(key).read_bytes()
    assert (output / "data").exists() == (selected == "bc")
    if selected == "bc":
        assert pack.path("catalog") == output / "data" / "pilot-catalog.json"
        assert len(list((output / "data").iterdir())) == len(CONTENT_KEYS)


def test_staging_rejects_foreign_manifest_content_before_writing(packaging_tree):
    source, output = packaging_tree
    manifest_path = source / "jurisdictions" / "zz" / "jurisdiction.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["content"]["catalog"] = "data/pilot-catalog.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="selected jurisdiction pack"):
        stage_jurisdiction("zz", source, output)
    assert not output.exists()
