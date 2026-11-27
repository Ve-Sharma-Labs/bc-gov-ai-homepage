"""Run the bounded acceptance selection with process-wide network denial."""

import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


TESTS = (
    "test_operation_rights.OperationRightsTests",
    "test_jurisdiction",
    "test_pdf",
    "test_vectors",
    "test_source_adapters",
    "test_ingestion.PolicyTests",
    "test_programme.ProgrammeFixtures.test_resume_keeps_totals_and_does_not_refetch_finished_documents",
    "test_programme.ProgrammeFixtures.test_resume_cannot_change_or_reset_budget_or_review",
    "test_programme.ProgrammeFixtures.test_rights_can_be_bound_after_offline_review_but_not_invented",
    "test_programme.ProgrammeFixtures.test_rights_binding_rechecks_only_the_exact_hold_clearing_route",
    "test_checkpoint_scale.CheckpointScaleTests.test_hot_reservation_save_does_not_load_or_upload_cold_documents",
    "test_checkpoint_scale.CheckpointScaleTests.test_bounded_review_page_and_lazy_exact_hash_validation",
    "test_checkpoint_scale.CheckpointScaleTests.test_replay_sequence_corruption_is_fatal_not_a_quota_reset",
)


def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--original-90", action="store_true")
    modes.add_argument("--subprocess-only", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(root / "ingestion"), str(root / "ingestion" / "tests")]
    from test_operation_rights import NETWORK_GUARDS

    selected = [] if args.subprocess_only else list(TESTS)
    if not args.original_90:
        selected.append("test_operation_rights.NetworkIsolationTests")
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {"JURISDICTION": "bc", "PYTHONDONTWRITEBYTECODE": "1"}))
        for target in NETWORK_GUARDS:
            stack.enter_context(patch(target, side_effect=AssertionError("Acceptance tests forbid live DNS/HTTP")))
        suite = unittest.defaultTestLoader.loadTestsFromNames(selected)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
