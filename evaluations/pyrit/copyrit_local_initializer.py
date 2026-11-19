"""Load the reviewed local pack without executing attacks or weakening administrator access."""

import os
from pathlib import Path

from pyrit.setup.pyrit_initializer import PyRITInitializer

from bc_pyrit.catalog import ROOT
from bc_pyrit.local import initialize_local


class BCGovLocalInitializer(PyRITInitializer):
    async def initialize_async(self) -> None:
        await initialize_local(Path(os.environ.get("BC_PYRIT_LOCAL_ROOT", str(ROOT))))
