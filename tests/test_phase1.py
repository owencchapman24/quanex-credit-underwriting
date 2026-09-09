"""Material-risk controls for the Phase 1 evidence foundation."""

from __future__ import annotations

import copy
import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import phase1  # noqa: E402


class Phase1ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = phase1.read_sources()

    def test_complete_generated_foundation_passes(self) -> None:
        stats = phase1.validate_all()
        self.assertEqual(stats["manual_overrides"], 0)
        self.assertEqual(stats["sources"], 9)
        self.assertGreaterEqual(stats["historical_reported"], 150)

    def test_duplicate_fact_is_rejected(self) -> None:
        rows = phase1.read_csv(phase1.RAW_DIR / "SOURCE_FACTS.csv")
        with self.assertRaisesRegex(phase1.Phase1Error, "Duplicate"):
            phase1.validate_fact_rows(rows + [copy.deepcopy(rows[0])], self.sources,
                                      "reported_historical")

    def test_wrong_fiscal_period_is_rejected(self) -> None:
        rows = phase1.read_csv(phase1.RAW_DIR / "SOURCE_FACTS.csv")
        damaged = copy.deepcopy(rows)
        damaged[0]["period_start"] = "2024-10-01"
        with self.assertRaisesRegex(phase1.Phase1Error, "Wrong fiscal period"):
            phase1.validate_fact_rows(damaged, self.sources, "reported_historical")

    def test_instant_duration_mismatch_is_rejected(self) -> None:
        rows = phase1.read_csv(phase1.RAW_DIR / "SOURCE_FACTS.csv")
        damaged = copy.deepcopy(rows)
        instant = next(row for row in damaged if row["period_type"] == "instant")
        instant["period_start"] = "2025-10-01"
        with self.assertRaisesRegex(phase1.Phase1Error, "Instant fact"):
            phase1.validate_fact_rows(damaged, self.sources, "reported_historical")

    def test_post_cutoff_source_is_rejected(self) -> None:
        rows = phase1.read_csv(phase1.RAW_DIR / "SOURCE_FACTS.csv")
        damaged_sources = dict(self.sources)
        damaged_sources["SRC-001"] = replace(
            damaged_sources["SRC-001"], publication_or_filing_date="2025-12-16"
        )
        with self.assertRaisesRegex(phase1.Phase1Error, "Post-cutoff"):
            phase1.validate_source_references(rows[:1], damaged_sources, "source_id")

    def test_amended_filing_is_rejected_for_explicit_resolution(self) -> None:
        manifest = phase1.read_csv(phase1.RAW_DIR / "SOURCE_MANIFEST.csv")
        damaged = copy.deepcopy(manifest)
        damaged[0]["document_type"] = "SEC 10-K/A"
        with self.assertRaisesRegex(phase1.Phase1Error, "source replacement|Amended filing"):
            phase1.validate_manifest(damaged, self.sources)

    def test_silent_source_replacement_is_rejected(self) -> None:
        manifest = phase1.read_csv(phase1.RAW_DIR / "SOURCE_MANIFEST.csv")
        damaged = copy.deepcopy(manifest)
        damaged[0]["source_url"] = "https://example.invalid/replacement"
        with self.assertRaisesRegex(phase1.Phase1Error, "Silent source replacement"):
            phase1.validate_manifest(damaged, self.sources)

    def test_incomplete_manual_override_is_rejected(self) -> None:
        override = {field: "" for field in phase1.OVERRIDE_FIELDS}
        override.update({"override_id": "OV-001", "status": "active"})
        with self.assertRaisesRegex(phase1.Phase1Error, "Unsupported manual override"):
            phase1.validate_overrides([override], {"RF-0001"})

    def test_expense_sign_error_is_rejected(self) -> None:
        rows = phase1.read_csv(phase1.PROCESSED_DIR / "historical_facts.csv")
        damaged = copy.deepcopy(rows)
        expense = next(row for row in damaged if row["metric_name"] == "interest_expense")
        expense["normalized_value"] = expense["normalized_value"].lstrip("-")
        with self.assertRaisesRegex(phase1.Phase1Error, "Expense sign error"):
            phase1.validate_processed(damaged)

    def test_unresolved_hidden_debt_conflict_is_rejected(self) -> None:
        rows = phase1.read_csv(phase1.PROCESSED_DIR / "debt_terms.csv")
        damaged = [row for row in rows if row["status"] != "conflicting_source"]
        with self.assertRaisesRegex(phase1.Phase1Error, "Conflict is not fully visible"):
            phase1.validate_debt(damaged, self.sources)

    def test_pro_forma_layer_cannot_enter_reported_history(self) -> None:
        rows = phase1.read_csv(phase1.RAW_DIR / "SOURCE_FACTS.csv")
        damaged = copy.deepcopy(rows)
        damaged[0]["layer"] = "company_disclosed_pro_forma"
        with self.assertRaisesRegex(phase1.Phase1Error, "Incorrect layer"):
            phase1.validate_fact_rows(damaged, self.sources, "reported_historical")

    def test_known_pro_forma_conflict_must_remain_visible(self) -> None:
        rows = phase1.read_csv(phase1.RAW_DIR / "PRO_FORMA_FACTS.csv")
        damaged = [row for row in rows if not (
            row["metric_name"] == "net_income" and row["fiscal_year"] == "FY2023"
            and row["source_id"] == "SRC-008"
        )]
        with self.assertRaisesRegex(phase1.Phase1Error, "rounding conflict"):
            phase1.validate_pro_forma_variants(damaged)


if __name__ == "__main__":
    unittest.main()
