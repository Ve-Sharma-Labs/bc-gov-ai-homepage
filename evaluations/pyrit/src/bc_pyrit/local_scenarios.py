"""Native, user-launched fixed scripts. No attacker or judge model is constructed."""

import logging
from dataclasses import replace
from functools import cache
from typing import ClassVar

from pyrit.converter import (
    Base64Converter,
    CharSwapConverter,
    LeetspeakConverter,
    PromptTemplateConverter,
    ROT13Converter,
)
from pyrit.executor.attack import MultiPromptSendingAttack
from pyrit.executor.attack.multi_turn.multi_prompt_sending import MultiPromptSendingAttackParameters
from pyrit.models import (
    AttackSeedGroup,
    DatasetFetchPolicy,
    ScenarioDatasetRequest,
    ScenarioPreset,
    ScenarioRunSizeComponent,
    ScenarioRunSizeEstimateStatus,
    Scorable,
    Score,
    ScoringExpectation,
)
from pyrit.registry import (
    AttackTechniqueRegistry,
    ConverterRegistry,
    ScenarioPresetRegistry,
    ScenarioRegistry,
    ScorerRegistry,
)
from pyrit.scenario.core import (
    AtomicAttack,
    AttackTechnique,
    AttackTechniqueFactory,
    BaselineAttackPolicy,
    DatasetAttackConfiguration,
    Scenario,
)
from pyrit.scenario.core.dataset_configuration import DatasetSource
from pyrit.scenario.core.scenario_context import ScenarioContext
from pyrit.score import TrueFalseScorer

from bc_pyrit.catalog import Catalog
from bc_pyrit.contracts import CheckError
from bc_pyrit.manual import ManualAppTarget


class ReviewRequiredScorer(TrueFalseScorer):
    """Records that a human review is needed; never infers safety from a non-error reply."""

    def _build_identifier(self):
        return self._create_identifier(params={"mode": "human-review-only"})

    async def _score_scorable_async(
        self, *, scorable: Scorable, expectation: ScoringExpectation | None
    ) -> list[Score]:
        return [self._build_undetermined_score(
            rationale="Review required. No AI judge is configured; this is not CI qualification.",
            scorable=scorable,
            message_piece_id=self._piece_id_from_scorable(scorable),
            objective=expectation.objective if expectation else None,
        )]


class FixedScriptParameters(MultiPromptSendingAttackParameters):
    @classmethod
    async def from_seed_group_async(
        cls, seed_group, *, adversarial_chat=None, objective_scorer=None, **overrides
    ):
        # PyRIT 1.2's scenario executor supplies operation_id, but its script parser rejects it.
        operation_id = overrides.pop("operation_id", None)
        params = await super().from_seed_group_async(
            seed_group, adversarial_chat=adversarial_chat,
            objective_scorer=objective_scorer, **overrides,
        )
        return replace(params, operation_id=operation_id)


class FixedScriptAttack(MultiPromptSendingAttack):
    """Send an ordered script with real replies, then close only its application session."""

    FIXED_PARAMS_TYPE = FixedScriptParameters

    async def _teardown_async(self, *, context) -> None:
        target = self.get_objective_target()
        if isinstance(target, ManualAppTarget) and context.session:
            await target.reset_conversation_async(conversation_id=context.session.conversation_id)
        await super()._teardown_async(context=context)


def fixed_factory() -> AttackTechniqueFactory:
    return AttackTechniqueFactory(
        name="bcgov_fixed_script",
        description="Ordered text messages, real replies, no helper model; human review required.",
        attack_class=FixedScriptAttack,
        technique_tags=["fixed", "no_helper_model"],
    )


@cache
def fixed_technique_class():
    return AttackTechniqueRegistry.build_technique_class_from_factories(
        class_name="BCGovFixedTechnique", factories=[fixed_factory()],
        default_names={"bcgov_fixed_script"},
    )


class BCGovFixed(Scenario):
    """Run shared BC or XSTest scripts serially. Human review is required."""

    VERSION = 1
    BASELINE_ATTACK_POLICY: ClassVar[BaselineAttackPolicy] = BaselineAttackPolicy.Forbidden
    catalog: ClassVar[Catalog | None] = None

    @classmethod
    def supported_parameters(cls):
        return [
            parameter.model_copy(update={"default": 1})
            if parameter.name == "max_concurrency" else parameter
            for parameter in super().supported_parameters()
        ]

    def __init__(self, *, scenario_result_id: str | None = None):
        if self.catalog is None:
            raise CheckError("LOCAL_CATALOG_NOT_INITIALIZED")
        super().__init__(
            version=self.VERSION, technique_class=fixed_technique_class(),
            default_dataset_config=DatasetAttackConfiguration(
                sources=[DatasetSource(
                    name=self.catalog.fixed_name, fetch=DatasetFetchPolicy.NEVER
                )],
                max_total=1,
            ),
            objective_scorer=ReviewRequiredScorer(),
            scenario_result_id=scenario_result_id,
            uses_default_adversarial_target=False,
        )

    def _validate_runtime_configuration(self) -> None:
        super()._validate_runtime_configuration()
        if self._max_retries not in (None, 0) or (
            self._max_concurrency is not None and self._max_concurrency < 1
        ):
            raise CheckError("FIXED_RUN_REQUIRES_SERIAL_NO_RETRY")
        if self._max_concurrency not in (None, 1):
            logging.getLogger(__name__).warning(
                "The local fixed profile caps requested concurrency %s at one.",
                self._max_concurrency,
            )
        if self._technique_converters:
            raise CheckError("USE_CONVERTERS_IN_MANUAL_CHAT")
        self._max_concurrency = 1
        self.params["max_concurrency"] = 1
        self._max_retries = 0

    async def _estimate_run_size_async(self, *, budget):
        estimate = await super()._estimate_run_size_async(budget=budget)
        if estimate.total_attack_count is None:
            return estimate
        maximum = estimate.total_attack_count * 3
        return estimate.model_copy(update={
            "status": ScenarioRunSizeEstimateStatus.Approximate,
            "total_attack_count": maximum,
            "components": [ScenarioRunSizeComponent(
                label="Selected scripts, at most three declared repetitions each", count=maximum
            )],
            "note": (
                "Conservative bound: each selected variant can repeat up to three times. "
                "A script can contain several turns. Exact app allowance is checked before sending."
            ),
        })

    async def _build_atomic_attacks_async(self, *, context: ScenarioContext) -> list[AtomicAttack]:
        if not isinstance(context.objective_target, ManualAppTarget) or self.catalog is None:
            raise CheckError("MANUAL_STAGING_TARGET_REQUIRED")
        approved = {
            group.objective.prompt_group_id: group
            for dataset in self.catalog.datasets[:2]
            for group in self.catalog.groups(dataset.dataset_name)
        }
        selected: list[tuple[AttackSeedGroup, int]] = []
        for group in context.seed_groups:
            source = approved.get(group.objective.prompt_group_id)
            if (
                source is None or group.objective.value != source.objective.value
                or group.objective.metadata != source.objective.metadata
                or [(p.value, p.sequence, p.role) for p in group.prompts]
                != [(p.value, p.sequence, p.role) for p in source.prompts]
            ):
                raise CheckError("UNREVIEWED_FIXED_SEED")
            repetitions = source.objective.metadata.get("repetitions", 1)
            selected.append((group, repetitions))
        target = context.objective_target
        target.app.ledger.remaining_seconds()
        required = sum(len(group.user_messages) * repetitions for group, repetitions in selected)
        with target.app.ledger.transaction() as connection:
            state = target.app.ledger._state(connection)
            used = connection.execute("SELECT COUNT(*) FROM charges WHERE role='app'").fetchone()[0]
        if not selected or required > state["limits"]["app"] - used:
            raise CheckError("INSUFFICIENT_APP_BUDGET")
        return [
            AtomicAttack(
                atomic_attack_name=f"bcgov-{group.objective.prompt_group_id}-{repeat}",
                display_group=group.objective.metadata.get("case_id", "XSTest"),
                technique_name="bcgov_fixed_script",
                attack_technique=AttackTechnique(attack=FixedScriptAttack(objective_target=target)),
                seed_groups=[group],
                memory_labels={
                    **context.memory_labels,
                    "bcgov_scope": "fixed-unscored-subset",
                    "suite_sha256": self.catalog.suite_hash,
                    "attempt": str(repeat),
                },
            )
            for group, repetitions in selected
            for repeat in range(1, repetitions + 1)
        ]


class LocalScenarioRegistry(ScenarioRegistry):
    """Fixed-only profile: upstream metadata eagerly constructs model-backed defaults."""

    def _discover(self) -> None:
        self.register_class(BCGovFixed, name="bcgov.fixed")


def register_local_components(catalog: Catalog) -> dict:
    BCGovFixed.catalog = catalog
    # Use the public registry replacement hook, not dummy credentials or patched upstream code.
    ScenarioRegistry.set_registry_singleton(LocalScenarioRegistry())
    AttackTechniqueRegistry.get_registry_singleton().register_from_factories([fixed_factory()])
    scorers = ScorerRegistry.get_registry_singleton().instances
    if "bcgov_review_required" not in scorers:
        scorers.register(ReviewRequiredScorer(), name="bcgov_review_required")
    converters = ConverterRegistry.get_registry_singleton().instances
    constructors = {
        "base64": Base64Converter, "rot13": ROT13Converter,
        "char_swap": CharSwapConverter, "leetspeak": LeetspeakConverter,
    }
    converter_names = []
    for name in catalog.converters:
        key = f"bcgov_{name}"
        converter_names.append(key)
        if key not in converters:
            converters.register(constructors[name](), name=key)
    for template in catalog.templates:
        key = f"bcgov_{template.name}"
        converter_names.append(key)
        if key not in converters:
            converters.register(
                PromptTemplateConverter(template=template.value), name=key
            )
    presets = ScenarioPresetRegistry.get_registry_singleton()
    names = []
    for label, dataset in (
        ("fixed", catalog.fixed_name), ("xstest", catalog.datasets[1].dataset_name)
    ):
        name = f"bcgov_{label}_{catalog.pack_hash[:12]}"
        presets.ensure_preset(preset=ScenarioPreset(
            name=name, scenario_name="bcgov.fixed",
            description=(
                "Start with one example. Ordered scripts and repetitions are retained. "
                "No AI judge: inspect the response and expected behavior yourself. "
                "Execution is capped at concurrency 1; retries must be 0. Not a full CI run."
            ),
            techniques=["bcgov_fixed_script"], include_baseline=False,
            datasets=ScenarioDatasetRequest.model_validate({
                "sources": [{"name": dataset, "fetch": "never"}], "max_total": 1,
            }),
        ))
        names.append(name)
    return {
        "presets": names, "converters": len(converter_names),
        "converterNames": converter_names, "scorer": "bcgov_review_required",
    }
