import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("attack", ["traversal", "duplicate", "oversized"])
def test_report_archive_does_not_extract_or_accept_unbounded_members(tmp_path, attack):
    archive_path = tmp_path / "input.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.json", json.dumps({"fixture": True}))
        archive.writestr("candidate.json", " " * 1_000_001 if attack == "oversized" else "{}")
        if attack == "traversal":
            archive.writestr("../escaped.txt", "untrusted")
        elif attack == "duplicate":
            with pytest.warns(UserWarning):
                archive.writestr("report.json", "{}")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "read-pyrit-artifact.py"), str(archive_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "INVALID_PYRIT_ARTIFACT" in result.stderr
    assert not (tmp_path.parent / "escaped.txt").exists()


def test_report_archive_returns_only_the_required_json_members(tmp_path):
    archive_path = tmp_path / "input.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("report.json", '{"version": 1}')
        archive.writestr("candidate.json", '{"version": 1}')
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "read-pyrit-artifact.py"), str(archive_path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert json.loads(result.stdout) == {
        "report.json": {"version": 1},
        "candidate.json": {"version": 1},
    }
