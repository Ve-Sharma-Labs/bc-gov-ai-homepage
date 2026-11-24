from pathlib import Path

import pytest

from bc_pyrit.contracts import Limits, ModelLimit, load_dataset
from bc_pyrit.ledger import Ledger

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def dataset():
    return load_dataset(ROOT / "data" / "evaluations" / "pyrit-conversation-cases.json")


@pytest.fixture
def limits():
    model = ModelLimit(
        calls=500,
        tokens=10_000_000,
        cost_microusd=0,
        input_bytes=16384,
        output_tokens=1024,
        token_price_microusd=0,
    )
    return Limits(app=500, wall_seconds=600, attacker=model, judge=model)


@pytest.fixture
def ledger(tmp_path, dataset, limits):
    return Ledger.initialize(
        tmp_path / "run.sqlite", dataset, "offline", limits, {"commit": "a" * 40}
    )
