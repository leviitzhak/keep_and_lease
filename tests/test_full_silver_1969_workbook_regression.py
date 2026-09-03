"""Opt-in full-engine comparison against the reviewed 1969 workbook fixture."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile


ROOT = Path(__file__).parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "workbooks"
    / "full_silver_long_gradual_1969_golden.xlsx"
)
RUN_FULL_REGRESSION = os.getenv(
    "KEEP_AND_LEASE_RUN_FULL_WORKBOOK_REGRESSION"
) == "1"


@unittest.skipUnless(
    RUN_FULL_REGRESSION,
    "set KEEP_AND_LEASE_RUN_FULL_WORKBOOK_REGRESSION=1 after large changes",
)
class FullSilverWorkbookRegressionTests(unittest.TestCase):
    def test_full_silver_long_gradual_1969_matches_reviewed_workbook(self):
        with tempfile.TemporaryDirectory(prefix="keep-lease-workbook-") as directory:
            temporary = Path(directory)
            result_path = temporary / "result.json"
            workbook_path = temporary / "generated.xlsx"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "generate-full-silver-1969-result.py"),
                    "--output",
                    str(result_path),
                ],
                cwd=ROOT,
                env={**os.environ, "PYTHONPATH": str(ROOT)},
                check=True,
            )
            subprocess.run(
                [
                    "node",
                    str(ROOT / "scripts" / "generate-backtest-workbook.mjs"),
                    "--result",
                    str(result_path),
                    "--start",
                    "1969-01-01",
                    "--end",
                    "1969-12-31",
                    "--output",
                    str(workbook_path),
                ],
                cwd=ROOT,
                check=True,
            )
            self.assertTrue(FIXTURE.is_file(), "reviewed golden workbook is missing")
            with ZipFile(FIXTURE) as expected, ZipFile(workbook_path) as actual:
                expected_names = sorted(expected.namelist())
                actual_names = sorted(actual.namelist())
                self.assertEqual(expected_names, actual_names)
                for name in expected_names:
                    self.assertEqual(
                        expected.read(name),
                        actual.read(name),
                        f"generated workbook entry changed: {name}",
                    )


if __name__ == "__main__":
    unittest.main()
