"""Shared project-root resolution for source and packaged runtimes."""

import os
from pathlib import Path


def resolve_project_root() -> Path:
    configured = os.environ.get("BC_INGESTION_PROJECT_ROOT")
    if configured:
        root = Path(configured).expanduser()
        if not root.is_absolute():
            raise RuntimeError("BC_INGESTION_PROJECT_ROOT must be an absolute path")
        return root.resolve()
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = resolve_project_root()
