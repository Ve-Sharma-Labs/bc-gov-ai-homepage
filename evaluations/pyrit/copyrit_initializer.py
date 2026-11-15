"""Activate only from a trusted local CoPyRIT configuration after staging approval."""

import os
from pathlib import Path

from pyrit.registry import TargetRegistry
from pyrit.setup.pyrit_initializer import PyRITInitializer

from bc_pyrit.manual import create_manual_target


class BCGovStagingInitializer(PyRITInitializer):
    @property
    def required_env_vars(self) -> list[str]:
        return ["BC_PYRIT_MANUAL_CONFIG"]

    async def initialize_async(self) -> None:
        target = await create_manual_target(Path(os.environ["BC_PYRIT_MANUAL_CONFIG"]))
        TargetRegistry.get_registry_singleton().instances.register(
            target, name="bc-gov-staging", replace=False
        )
