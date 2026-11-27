"""Optional Azure integration tests for the exact source-health alert query."""

import json
import os
from pathlib import Path
import subprocess
import unittest
from uuid import UUID


WORKSPACE = os.environ.get("AZURE_LOG_ANALYTICS_TEST_WORKSPACE")
TEMPLATE = Path(__file__).resolve().parents[1] / "sk-source-health-alert.bicep"


@unittest.skipUnless(WORKSPACE, "Set AZURE_LOG_ANALYTICS_TEST_WORKSPACE to run KQL integration tests")
class SourceHealthAlertTests(unittest.TestCase):
    def test_strict_and_legacy_modes(self):
        workspace = str(UUID(WORKSPACE))
        template = TEMPLATE.read_text(encoding="utf-8")
        query = template.split("query: replace(replace('''", 1)[1].split(
            "''', 'APP_INSIGHTS_RESOURCE_ID'", 1
        )[0].replace("APP_INSIGHTS_RESOURCE_ID", "/test/insights")
        rows = [
            ("bc.sources.checks", 1, "ready"),
            ("bc.sources.usable_documents", 42, ""),
            ("bc.sources.expired_documents", 0, ""),
            ("bc.sources.missing_sources", 0, ""),
            ("bc.sources.hours_to_expiry", 73, ""),
        ]
        cases = {
            "healthy": rows,
            "expiry-boundary": [*rows[:-1], ("bc.sources.hours_to_expiry", 72, "")],
            "expired-documents": [*rows[:2], ("bc.sources.expired_documents", 1, ""), *rows[3:]],
            "missing-sources": [*rows[:3], ("bc.sources.missing_sources", 1, ""), rows[4]],
            "zero-documents": [rows[0], ("bc.sources.usable_documents", 0, ""), *rows[2:]],
            "unhealthy": [("bc.sources.checks", 1, "unavailable"), *rows[1:]],
            "missing-partial-count": [*rows[:2], *rows[3:]],
            "no-telemetry": [],
            "legacy-healthy": [rows[0], rows[1], rows[4]],
            "legacy-expiry": [rows[0], rows[1], ("bc.sources.hours_to_expiry", 72, "")],
            "legacy-unhealthy": [("bc.sources.checks", 1, "unavailable"), rows[1], rows[4]],
            "legacy-missing-expiry": [rows[0], rows[1]],
        }
        for strict in (True, False):
            for name, data in cases.items():
                with self.subTest(strict=strict, case=name):
                    values = ", ".join(
                        f"'{metric}', {value}.0, dynamic({{'status':'{status}'}})"
                        for metric, value, status in data
                    )
                    table = (
                        f"datatable(Name:string, Value:real, Properties:dynamic) [{values}]"
                        " | extend TimeGenerated=now(), _ResourceId='/test/insights', "
                        "AppRoleName='skassist-rywtikimq4.bc-service-assistant', Min=Value, Max=Value"
                    )
                    branch = (
                        query.replace("AppMetrics", f"({table})", 1)
                        .replace("REQUIRE_PARTIAL_LOSS_METRICS", str(strict))
                        .strip().replace("\n", " ")
                    )
                    result = subprocess.run(
                        [
                            "az", "monitor", "log-analytics", "query", "--workspace",
                            workspace, "--analytics-query", branch, "-o", "json",
                            "--only-show-errors",
                        ],
                        capture_output=True, text=True, shell=os.name == "nt", check=True,
                    )
                    expected = name != "healthy" and (
                        strict or name not in {"missing-partial-count", "legacy-healthy"}
                    )
                    self.assertEqual(bool(json.loads(result.stdout)), expected)


if __name__ == "__main__":
    unittest.main()
