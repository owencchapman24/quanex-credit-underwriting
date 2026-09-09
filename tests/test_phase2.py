"""Decision-relevant controls for the Phase 2 historical credit analysis."""

from __future__ import annotations

import copy
import sys
import unittest
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import phase1  # noqa: E402
import phase2  # noqa: E402


class Phase2ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spread = phase2.read_csv(phase2.PHASE2_PROCESSED / "historical_spread.csv")
        cls.bridges = phase2.read_csv(phase2.PHASE2_PROCESSED / "earnings_bridges.csv")
        cls.decisions = phase2.read_csv(phase2.PHASE2_PROCESSED / "adjustment_decisions.csv")
        cls.metrics = phase2.read_csv(phase2.PHASE2_PROCESSED / "historical_credit_metrics.csv")
        cls.recons = phase2.read_csv(phase2.PHASE2_PROCESSED / "reconciliation_results.csv")
        cls.values = phase2.spread_index(cls.spread)

    def test_01_five_year_period_coverage(self) -> None:
        self.assertEqual({row["fiscal_year"] for row in self.spread}, set(phase2.YEARS))
        for year in phase2.YEARS:
            for row in (item for item in self.spread if item["fiscal_year"] == year):
                self.assertEqual(row["period_end"], phase2.period(year)[1])
                if row["period_type"] == "instant":
                    self.assertEqual(row["period_start"], "")
                else:
                    self.assertEqual(row["period_type"], "duration")
                    self.assertEqual(row["period_start"], phase2.period(year)[0])

    def test_02_units_and_sign_conventions(self) -> None:
        self.assertTrue(all(row["units"] == "USD_millions" for row in self.spread))
        expense_metrics = {
            "cost_of_sales_excluding_depreciation_and_amortization",
            "selling_general_and_administrative", "depreciation_and_amortization",
            "interest_expense", "income_tax_expense", "capital_expenditures",
            "dividends_paid", "share_repurchases",
        }
        for row in self.spread:
            if row["metric_name"] in expense_metrics and row["value"]:
                self.assertLessEqual(Decimal(row["value"]), 0, row["spread_id"])

    def test_03_required_fields_present_or_explicitly_missing(self) -> None:
        required = {
            "revenue", "gross_profit", "operating_income", "net_income",
            "cash_flow_from_operations", "capital_expenditures", "free_cash_flow",
            "total_assets", "total_liabilities", "shareholders_equity",
            "total_debt_principal", "acquisition_cash_flows",
        }
        for year in phase2.YEARS:
            rows = {row["metric_name"]: row for row in self.spread if row["fiscal_year"] == year}
            self.assertFalse(required - rows.keys())
            for metric in required:
                self.assertTrue(rows[metric]["value"] or rows[metric]["status"].startswith("not_"))

    def test_04_balance_sheet_reconciliation(self) -> None:
        rows = [row for row in self.recons if row["description"] == "Assets = liabilities + equity"]
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row["status"] == "PASS" and Decimal(row["difference"]) == 0 for row in rows))

    def test_05_cfo_and_fcf_construction(self) -> None:
        rows = [row for row in self.recons if row["description"] in {
            "Detailed CFO bridge = reported CFO", "CFO plus capex = free cash flow"
        }]
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(row["status"] == "PASS" for row in rows))

    def test_06_historical_cash_movement(self) -> None:
        rows = [row for row in self.recons if "cash change" in row["description"] or
                "Beginning cash plus" in row["description"]]
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(row["status"] == "PASS" for row in rows))

    def test_07_debt_principal_vs_carrying_value(self) -> None:
        rows = [row for row in self.recons if row["description"].startswith("Gross funded principal less")]
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row["status"] == "PASS" for row in rows))

    def test_08_current_plus_long_term_debt(self) -> None:
        rows = [row for row in self.recons if row["description"].startswith("Current plus long-term debt")]
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row["status"] == "PASS" for row in rows))

    def test_09_instrument_level_debt_reconciliation(self) -> None:
        rows = [row for row in self.recons if row["description"].startswith("Instrument principal")]
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row["status"] == "PASS" for row in rows))

    def test_10_dna_consistency(self) -> None:
        rows = [row for row in self.recons if "D&A" in row["description"]]
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row["status"] == "PASS" for row in rows))

    def test_11_pro_forma_and_reported_layers_remain_separate(self) -> None:
        self.assertFalse(any(row["classification"] == "reported_pro_forma" for row in self.spread))
        rows = [row for row in self.recons if row["category"] == "acquisition_comparability"]
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row["status"] == "DISTINCT_LAYER" for row in rows))

    def test_12_adjustment_bridge_arithmetic(self) -> None:
        grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in self.bridges:
            grouped[(row["fiscal_year"], row["bridge_type"])].append(row)
        for key, rows in grouped.items():
            ordered = sorted(rows, key=lambda row: int(row["sequence"]))
            previous = Decimal(0)
            for position, row in enumerate(ordered):
                if not row["resulting_subtotal"]:
                    continue
                amount = Decimal(row["amount"] or 0)
                subtotal = Decimal(row["resulting_subtotal"])
                if position == 0:
                    self.assertEqual(subtotal, amount, key)
                else:
                    self.assertEqual(subtotal, previous + amount, key)
                previous = subtotal

    def test_13_no_duplicated_adjustments(self) -> None:
        self.assertEqual(len(self.decisions), 11)
        self.assertEqual(len({row["adjustment_id"] for row in self.decisions}), 11)
        grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
        for row in self.bridges:
            if row["adjustment_id"]:
                grouped[(row["fiscal_year"], row["bridge_type"])].append(row["adjustment_id"])
        for ids in grouped.values():
            self.assertEqual(len(ids), len(set(ids)))

    def test_14_accepted_amount_never_exceeds_support(self) -> None:
        for row in self.decisions:
            supported = Decimal(row["reported_amount"])
            cases = [Decimal(row[field]) for field in (
                "accepted_amount_low", "accepted_amount_base", "accepted_amount_high"
            )]
            if supported >= 0:
                self.assertGreaterEqual(min(cases), 0)
                self.assertLessEqual(max(cases), supported)
            else:
                self.assertTrue(all(value == supported for value in cases))

    def test_15_every_adjustment_has_human_review_status(self) -> None:
        self.assertTrue(all(row["human_review_status"] == "owner_reviewed"
                            for row in self.decisions))
        expected = {
            "AC-001": ("accepted", "302.284", "302.284", "302.284"),
            "AC-002": ("pending_information", "0", "0", "1.432"),
            "AC-003": ("pending_information", "0", "0", "0.221"),
            "AC-004": ("accepted", "9.007", "9.007", "9.007"),
            "AC-005": ("pending_information", "0", "0", "10.263"),
            "AC-006": ("partial_accept", "4.561", "4.561", "10.191"),
            "AC-007": ("not_applicable", "0", "0", "0"),
            "AC-008": ("pending_information", "0", "0", "3.025"),
            "AC-009": ("accepted", "-4.196", "-4.196", "-4.196"),
            "AC-010": ("accepted", "29.076", "29.076", "29.076"),
            "AC-011": ("accepted", "39.324", "39.324", "39.324"),
        }
        for row in self.decisions:
            self.assertEqual(
                (row["lender_recommendation"], row["accepted_amount_low"],
                 row["accepted_amount_base"], row["accepted_amount_high"]),
                expected[row["adjustment_id"]],
            )

    def test_16_working_capital_denominators_are_consistent(self) -> None:
        dso = [row for row in self.metrics if row["metric_name"] == "days_sales_outstanding"]
        dio = [row for row in self.metrics if row["metric_name"] == "days_inventory_outstanding"]
        dpo = [row for row in self.metrics if row["metric_name"] == "days_payables_outstanding"]
        self.assertTrue(all("revenue" in row["calculation"] for row in dso))
        self.assertTrue(all("cost of sales" in row["calculation"] for row in dio))
        self.assertTrue(all(row["failure_flag"] == "MISSING_PURCHASES_DENOMINATOR" for row in dpo))

    def test_17_negative_and_zero_ebitda_handling(self) -> None:
        negative = next(row for row in self.metrics if row["fiscal_year"] == "FY2025" and
                        row["metric_name"] == "gross_funded_debt_to_unadjusted_ebitda")
        self.assertEqual((negative["display_value"], negative["failure_flag"]),
                         ("N/M", "NONPOSITIVE_EBITDA"))
        damaged = copy.deepcopy(self.spread)
        next(row for row in damaged if row["fiscal_year"] == "FY2025" and
             row["metric_name"] == "unadjusted_ebitda")["value"] = "0"
        metrics = phase2.build_metrics(damaged, self.bridges)
        zero = next(row for row in metrics if row["fiscal_year"] == "FY2025" and
                    row["metric_name"] == "gross_funded_debt_to_unadjusted_ebitda")
        self.assertEqual((zero["display_value"], zero["failure_flag"]),
                         ("N/M", "NONPOSITIVE_EBITDA"))

    def test_18_raw_to_processed_lineage(self) -> None:
        valid_inputs = {row["fact_id"] for row in phase2.read_csv(phase2.PHASE1_FACTS)}
        valid_inputs |= {row["record_id"] for row in phase2.read_csv(
            phase2.PHASE2_RAW / "SUPPLEMENTAL_FACTS.csv")}
        valid_inputs |= {row["adjustment_id"] for row in self.decisions}
        for row in self.spread:
            for input_id in row["input_ids"].split(";"):
                if input_id:
                    self.assertIn(input_id, valid_inputs | {r["spread_id"] for r in self.spread})

    def test_19_source_ids_are_valid(self) -> None:
        for collection in (self.spread, self.bridges, self.recons):
            for row in collection:
                for source_id in row.get("source_ids", "").split(";"):
                    if source_id:
                        self.assertIn(source_id, phase2.VALID_SOURCES)

    def test_20_information_cutoff_compliance(self) -> None:
        manifest = phase2.read_csv(phase2.PHASE1_MANIFEST)
        for row in manifest:
            filing_date = datetime.strptime(row["publication_or_filing_date"], "%Y-%m-%d").date()
            self.assertLessEqual(filing_date, phase2.CUTOFF)
            self.assertEqual(row["cutoff_status"], "ALLOWED")

    def test_21_deterministic_regeneration(self) -> None:
        before = phase2.fingerprints()
        phase2.build()
        after = phase2.fingerprints()
        self.assertEqual(before, after)

    def test_22_phase1_validation_still_passes(self) -> None:
        stats = phase1.validate_all()
        self.assertEqual(stats["manual_overrides"], 0)
        self.assertEqual(stats["historical_reported"], 174)

    def test_23_acquisition_missing_values_are_not_zero(self) -> None:
        for year in ("FY2021", "FY2022"):
            row = self.values[(year, "acquisition_cash_flows")]
            self.assertEqual(row["value"], "")
            self.assertEqual(row["status"], "not_determinable_not_zero")

    def test_24_company_adjusted_ebitda_reconciles(self) -> None:
        final = phase2.final_bridge_values(self.bridges, "company_adjusted_ebitda")
        self.assertEqual(final["FY2024"], Decimal("182.383"))
        self.assertEqual(final["FY2025"], Decimal("242.89"))
        self.assertIsNone(final["FY2021"])

    def test_25_contractual_ebitda_is_not_presented_as_official(self) -> None:
        contract_rows = [row for row in self.bridges if
                         row["bridge_type"] == "contractual_ebitda_public_reconstruction"]
        self.assertFalse(any(row["status"] == "official" for row in contract_rows))
        final = phase2.final_bridge_values(self.bridges, "contractual_ebitda_public_reconstruction")
        self.assertEqual(final["FY2025"], Decimal("229.642"))
        self.assertTrue(all(final[year] is None for year in phase2.YEARS[:-1]))

    def test_26_complete_phase2_validation_passes(self) -> None:
        stats = phase2.validate()
        self.assertEqual(stats["adjustments"], 11)
        self.assertEqual(stats["post_cutoff_sources"], 0)
        self.assertEqual(stats["owner_reviewed_adjustments"], 11)

    def test_27_owner_reviewed_base_and_cash_treatment(self) -> None:
        final = phase2.final_bridge_values(
            self.bridges, "provisional_lender_normalized_ebitda_base"
        )
        self.assertEqual(final["FY2024"], Decimal("179.358"))
        self.assertEqual(final["FY2025"], Decimal("225.344"))
        leverage = {
            row["fiscal_year"]: Decimal(row["value"])
            for row in self.metrics
            if row["metric_name"] == "gross_funded_debt_to_provisional_lender_normalized_ebitda"
        }
        self.assertEqual(leverage["FY2024"], Decimal("776.926") / Decimal("179.358"))
        self.assertEqual(leverage["FY2025"], Decimal("703.869") / Decimal("225.344"))
        ac011 = next(row for row in self.decisions if row["adjustment_id"] == "AC-011")
        self.assertEqual(ac011["cash_noncash_status"], "cash")
        self.assertTrue(ac011["contractual_eligibility"].startswith("not_determinable"))
        self.assertEqual(self.values[("FY2024", "acquisition_cash_flows")]["value"], "-398.554")


if __name__ == "__main__":
    unittest.main()
