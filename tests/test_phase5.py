"""Decision-relevant tests for the Phase 5 integrated base case."""

from __future__ import annotations

import sys
import subprocess
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import phase1  # noqa: E402
import phase2  # noqa: E402
import phase3  # noqa: E402
import phase4  # noqa: E402
import phase5  # noqa: E402


class Phase5ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.checkpoint = phase5.read_csv(phase5.RAW / "STARTING_CHECKPOINT.csv")[0]
        cls.assumptions = phase5.read_csv(phase5.RAW / "MODEL_ASSUMPTIONS.csv")
        cls.amap = phase5.assumption_map(cls.assumptions)
        cls.operating = phase5.read_csv(phase5.PROCESSED / "QUARTERLY_OPERATING_FORECAST.csv")
        cls.monthly = phase5.read_csv(phase5.PROCESSED / "MONTHLY_LIQUIDITY_SCHEDULE.csv")
        cls.waterfall = phase5.read_csv(phase5.PROCESSED / "CASH_FLOW_WATERFALL.csv")
        cls.debt = phase5.read_csv(phase5.PROCESSED / "DEBT_SCHEDULE.csv")
        cls.metrics = phase5.read_csv(phase5.PROCESSED / "BASE_CASE_CREDIT_METRICS.csv")
        cls.sensitivities = phase5.read_csv(phase5.PROCESSED / "DEBT_CAPACITY_SENSITIVITIES.csv")
        cls.comparison = phase5.read_csv(phase5.PROCESSED / "FINANCING_ALTERNATIVE_COMPARISON.csv")
        cls.opening_bridge = phase5.read_csv(phase5.PROCESSED / "OPENING_POSITION_BRIDGE.csv")
        cls.distributions = phase5.read_csv(phase5.PROCESSED / "DISTRIBUTION_ANALYSIS.csv")
        cls.common_horizon = phase5.read_csv(phase5.PROCESSED / "COMMON_HORIZON_COMPARISON.csv")
        cls.period_presentation = phase5.read_csv(phase5.PROCESSED / "FY2026_PERIOD_PRESENTATION.csv")
        cls.validations = phase5.read_csv(phase5.PROCESSED / "VALIDATION_RESULTS.csv")
        cls.ledger = phase5.read_csv(phase5.DOCS / "SOURCE_LEDGER.csv")
        cls.proposed_full = phase5.run_monthly_model("proposed", cls.operating, cls.assumptions)
        cls.existing_full = phase5.run_monthly_model("existing", cls.operating, cls.assumptions)

    def test_01_starting_checkpoint(self) -> None:
        self.assertEqual(self.checkpoint["repository"], "owencchapman24/quanex-credit-underwriting")
        self.assertEqual(self.checkpoint["branch"], "main")
        for field in ("local_head", "tracked_origin_main", "live_remote_main"):
            self.assertEqual(self.checkpoint[field], phase5.APPROVED_PHASE4_COMMIT)
        self.assertEqual((self.checkpoint["ahead"], self.checkpoint["behind"]), ("0", "0"))
        self.assertEqual(self.checkpoint["working_tree_clean_before_work"], "yes")

    def test_02_period_coverage(self) -> None:
        self.assertEqual(len(self.operating), 21)
        self.assertEqual((self.operating[0]["period_start"], self.operating[0]["period_end"]),
                         ("2025-11-01", "2026-01-31"))
        self.assertEqual(self.operating[-1]["period_end"], "2031-01-31")

    def test_03_quarterly_annual_aggregation(self) -> None:
        grouped: dict[str, list[dict[str, str]]] = {}
        for row in self.operating:
            grouped.setdefault(row["fiscal_year"], []).append(row)
        self.assertTrue(all(len(grouped[f"FY{year}"]) == 4 for year in range(2026, 2031)))
        self.assertEqual(len(grouped["FY2031"]), 1)

    def test_04_revenue_formula(self) -> None:
        for row in self.operating:
            expected = (
                Decimal(row["prior_year_same_quarter_revenue"])
                * (1 + Decimal(row["underlying_volume_growth_percent"]) / 100)
                * (1 + Decimal(row["price_mix_growth_percent"]) / 100)
            )
            self.assertAlmostEqual(Decimal(row["revenue"]), expected)

    def test_05_gross_margin_formula(self) -> None:
        for row in self.operating:
            self.assertAlmostEqual(Decimal(row["revenue"]) + Decimal(row["cost_of_sales"]),
                                   Decimal(row["gross_profit"]))
            self.assertAlmostEqual(Decimal(row["gross_profit"]) / Decimal(row["revenue"]) * 100,
                                   Decimal(row["gross_margin_percent"]))

    def test_06_ebitda_build_not_growth_shortcut(self) -> None:
        for row in self.operating:
            self.assertEqual(Decimal(row["lender_base_ebitda"]),
                             Decimal(row["gross_profit"]) + Decimal(row["cash_operating_expenses"]))
            self.assertNotIn("EBITDA growth", row["calculation"])

    def test_07_annual_ebitda_margin_validation_band(self) -> None:
        for row in phase5.annual_operating_rows(self.operating):
            if row["coverage"] == "full_year":
                self.assertGreaterEqual(Decimal(row["margin"]), Decimal("12"))
                self.assertLessEqual(Decimal(row["margin"]), Decimal("13"))

    def test_08_working_capital_calculation(self) -> None:
        for row in self.operating:
            expected = (
                Decimal(row["accounts_receivable"]) + Decimal(row["inventory"])
                + Decimal(row["other_operating_current_assets"])
                - Decimal(row["accounts_payable"])
                - Decimal(row["other_operating_current_liabilities"])
            )
            self.assertEqual(Decimal(row["operating_net_working_capital"]), expected)

    def test_09_no_zero_payables_or_other_working_capital(self) -> None:
        fields = ("accounts_payable", "other_operating_current_assets",
                  "other_operating_current_liabilities")
        self.assertTrue(all(Decimal(row[field]) > 0 for row in self.operating for field in fields))

    def test_10_dpo_remains_not_determinable(self) -> None:
        self.assertFalse(any("dpo" in field.lower() for field in phase5.OPERATING_FIELDS))
        assumption = next(row for row in self.assumptions
                          if row["assumption_name"] == "accounts_payable_to_cost_of_sales")
        self.assertIn("not DPO", assumption["limitation_or_rationale"])

    def test_11_cfads_bridge(self) -> None:
        for row in self.operating:
            expected = (
                Decimal(row["lender_base_ebitda"]) + Decimal(row["cash_tax_proxy"])
                + Decimal(row["working_capital_cash_flow"])
                + Decimal(row["capital_expenditures"])
                + Decimal(row["other_necessary_operating_cash_uses"])
            )
            self.assertEqual(Decimal(row["cfads_before_cash_interest"]), expected)

    def test_12_cash_tax_and_capex_signs(self) -> None:
        self.assertTrue(all(Decimal(row["cash_tax_proxy"]) <= 0 for row in self.operating))
        self.assertTrue(all(Decimal(row["capital_expenditures"]) < 0 for row in self.operating))

    def test_13_no_forecast_adjustment_addbacks(self) -> None:
        text = " ".join(row["calculation"] for row in self.operating).lower()
        self.assertNotIn("addback", text)
        self.assertNotIn("unrealized synergy", text)

    def test_14_monthly_output_24_months_per_structure(self) -> None:
        self.assertEqual(len([row for row in self.monthly if row["structure"] == "proposed"]), 24)
        self.assertEqual(len([row for row in self.monthly if row["structure"] == "existing"]), 24)

    def test_15_monthly_aggregation_to_quarter(self) -> None:
        qrow = next(row for row in self.operating if row["fiscal_year"] == "FY2026"
                    and row["quarter"] == "Q2")
        months = [row for row in self.proposed_full if row["quarter_period_id"] == qrow["forecast_id"]]
        self.assertEqual(len(months), 3)
        for field in ("revenue", "lender_base_ebitda", "cfads_before_cash_interest"):
            difference = sum(Decimal(row[field]) for row in months) - Decimal(qrow[field])
            self.assertLessEqual(abs(difference), Decimal("1E-24"))

    def test_16_cash_roll_forward(self) -> None:
        for row in self.proposed_full + self.existing_full:
            ending = (
                Decimal(row["opening_cash"]) + Decimal(row["cfads_before_cash_interest"])
                + Decimal(row["cash_interest"])
                + Decimal(row["retained_finance_and_other_debt_payment"])
                + Decimal(row["dividends"]) + Decimal(row["share_repurchases"])
                - Decimal(row["scheduled_term_principal"]) + Decimal(row["revolver_draw"])
                - Decimal(row["revolver_repayment"]) - Decimal(row["cash_sweep"])
                - Decimal(row["cash_applied_at_maturity"])
            )
            self.assertEqual(ending, Decimal(row["ending_cash"]))

    def test_17_term_roll_forward(self) -> None:
        for row in self.proposed_full + self.existing_full:
            ending = (
                Decimal(row["opening_term_principal"])
                - Decimal(row["scheduled_term_principal"]) - Decimal(row["cash_sweep"])
                - Decimal(row["maturity_term_payment"])
            )
            self.assertEqual(ending, Decimal(row["ending_term_principal"]))

    def test_18_revolver_roll_forward(self) -> None:
        for row in self.proposed_full + self.existing_full:
            ending = (
                Decimal(row["opening_revolver"]) + Decimal(row["revolver_draw"])
                - Decimal(row["revolver_repayment"]) - Decimal(row["maturity_revolver_payment"])
            )
            self.assertEqual(ending, Decimal(row["ending_revolver"]))

    def test_19_interest_responds_to_debt_and_spread(self) -> None:
        low = phase5.run_monthly_model("proposed", self.operating, self.assumptions,
                                       Decimal("250"), Decimal("10"))
        high = phase5.run_monthly_model("proposed", self.operating, self.assumptions,
                                        Decimal("350"), Decimal("10"))
        self.assertLess(phase5.model_summary(low)["cumulative_interest"],
                        phase5.model_summary(high)["cumulative_interest"])

    def test_19b_recurring_financing_fees_are_not_silent_zeroes(self) -> None:
        fee_assumption = self.amap["P5A-042"]
        self.assertEqual(fee_assumption["value"], "")
        self.assertEqual(fee_assumption["review_status"], "pending_information")
        self.assertTrue(all(row["recurring_financing_fees"] == "" for row in self.monthly))
        self.assertTrue(all(
            row["recurring_financing_fees_status"] == "not_determinable_excluded_not_zero"
            for row in self.monthly
        ))

    def test_20_quarterly_amortization_reference(self) -> None:
        payments = [Decimal(row["scheduled_term_principal"]) for row in self.proposed_full
                    if Decimal(row["scheduled_term_principal"]) > 0]
        self.assertEqual(len(payments), 20)
        self.assertEqual(set(payments), {Decimal("16.25")})
        annual = {
            year: sum(Decimal(row["scheduled_term_principal"])
                      for row in self.proposed_full if row["fiscal_year"] == year)
            for year in ("FY2026", "FY2027", "FY2028", "FY2029", "FY2030", "FY2031")
        }
        self.assertEqual(annual["FY2026"], Decimal("48.75"))
        self.assertEqual({annual[year] for year in ("FY2027", "FY2028", "FY2029", "FY2030")},
                         {Decimal("65")})
        self.assertEqual(annual["FY2031"], Decimal("16.25"))

    def test_21_existing_quarterly_amortization(self) -> None:
        payments = [Decimal(row["scheduled_term_principal"]) for row in self.existing_full
                    if Decimal(row["scheduled_term_principal"]) > 0]
        self.assertEqual(len(payments), 14)
        self.assertEqual(set(payments), {Decimal("6.25")})

    def test_22_annual_sweep_after_revolver(self) -> None:
        for row in self.proposed_full:
            if Decimal(row["cash_sweep"]) > 0:
                self.assertEqual(row["month_end"][5:7], "10")
                self.assertEqual(Decimal(row["ending_revolver"]), 0)
                self.assertGreaterEqual(Decimal(row["usable_liquidity"]), Decimal("50"))

    def _boundary_quarter(self, cfads: Decimal = Decimal("0")) -> dict[str, str]:
        row = dict(self.operating[1])
        for field in ("revenue", "lender_base_ebitda", "cash_tax_proxy",
                      "working_capital_cash_flow", "capital_expenditures",
                      "other_necessary_operating_cash_uses"):
            row[field] = "0"
        row["cfads_before_cash_interest"] = str(cfads)
        return row

    def _boundary_params(self, maturity: date = date(2031, 1, 31)) -> dict[str, Decimal | date]:
        return {
            "opening_term": Decimal("0"), "opening_revolver": Decimal("0"),
            "commitment": Decimal("300"), "lc": Decimal("6.2"),
            "all_in_rate": Decimal("0"), "quarterly_principal": Decimal("0"),
            "maturity": maturity,
        }

    def test_23_exact_cash_floor(self) -> None:
        result = phase5.model_one_month(
            "proposed", date(2026, 2, 28), self._boundary_quarter(
                Decimal("6.96275")
            ), 1,
            Decimal("25"), Decimal("0"), Decimal("0"), self._boundary_params(),
            self.amap, phase5.retained_payment_by_year(self.amap),
        )
        self.assertEqual(result["ending_cash"], Decimal("25"))
        self.assertEqual(result["revolver_draw"], 0)
        self.assertEqual(result["cash_floor_shortfall"], 0)

    def test_24_cash_one_unit_above_floor(self) -> None:
        result = phase5.model_one_month(
            "proposed", date(2026, 2, 28), self._boundary_quarter(
                Decimal("6.96275")
            ), 1,
            Decimal("26"), Decimal("0"), Decimal("0"), self._boundary_params(),
            self.amap, phase5.retained_payment_by_year(self.amap),
        )
        self.assertEqual(result["ending_cash"], Decimal("26"))
        self.assertEqual(result["revolver_draw"], 0)

    def test_25_cash_one_unit_below_floor_draws(self) -> None:
        result = phase5.model_one_month(
            "proposed", date(2026, 2, 28), self._boundary_quarter(
                Decimal("6.96275")
            ), 1,
            Decimal("24"), Decimal("0"), Decimal("0"), self._boundary_params(),
            self.amap, phase5.retained_payment_by_year(self.amap),
        )
        self.assertEqual(result["ending_cash"], Decimal("25"))
        self.assertEqual(result["revolver_draw"], Decimal("1"))

    def test_26_exact_revolver_commitment_boundary(self) -> None:
        result = phase5.model_one_month(
            "proposed", date(2026, 2, 28), self._boundary_quarter(
                Decimal("6.96275")
            ), 1,
            Decimal("25"), Decimal("0"), Decimal("293.8"), self._boundary_params(),
            self.amap, phase5.retained_payment_by_year(self.amap),
        )
        self.assertEqual(result["availability"], 0)
        self.assertEqual(result["commitment_breach"], 0)

    def test_27_revolver_exhaustion_visible(self) -> None:
        result = phase5.model_one_month(
            "proposed", date(2026, 2, 28), self._boundary_quarter(Decimal("-10")), 1,
            Decimal("25"), Decimal("0"), Decimal("293.8"), self._boundary_params(),
            self.amap, phase5.retained_payment_by_year(self.amap),
        )
        self.assertGreater(result["cash_floor_shortfall"], 0)
        self.assertEqual(result["model_status"], "CASH_FLOOR_FAILURE")

    def test_28_negative_availability_visible(self) -> None:
        result = phase5.model_one_month(
            "proposed", date(2026, 2, 28), self._boundary_quarter(
                Decimal("6.96275")
            ), 1,
            Decimal("25"), Decimal("0"), Decimal("294"), self._boundary_params(),
            self.amap, phase5.retained_payment_by_year(self.amap),
        )
        self.assertEqual(result["availability"], Decimal("-0.2"))
        self.assertEqual(result["commitment_breach"], Decimal("0.2"))

    def test_29_sweep_blocked_with_revolver_outstanding(self) -> None:
        result = phase5.model_one_month(
            "proposed", date(2026, 10, 31), self._boundary_quarter(Decimal("5")), 3,
            Decimal("25"), Decimal("100"), Decimal("20"), self._boundary_params(),
            self.amap, phase5.retained_payment_by_year(self.amap),
        )
        self.assertGreater(result["ending_revolver"], 0)
        self.assertEqual(result["sweep"], 0)

    def test_30_sweep_zero_when_cash_equals_floor(self) -> None:
        result = phase5.model_one_month(
            "proposed", date(2026, 10, 31), self._boundary_quarter(
                Decimal("6.96275")
            ), 3,
            Decimal("25"), Decimal("100"), Decimal("0"), self._boundary_params(),
            self.amap, phase5.retained_payment_by_year(self.amap),
        )
        self.assertEqual(result["ending_cash"], Decimal("25"))
        self.assertEqual(result["sweep"], 0)

    def test_31_zero_and_negative_ebitda_ratio_handling(self) -> None:
        self.assertEqual(phase5.safe_ratio(Decimal("10"), Decimal("0"))[1:], ("N/M", "NONPOSITIVE_DENOMINATOR"))
        self.assertEqual(phase5.safe_ratio(Decimal("10"), Decimal("-1"))[1:], ("N/M", "NONPOSITIVE_DENOMINATOR"))

    def test_32_maturity_balloon_and_gap(self) -> None:
        result = phase5.model_one_month(
            "proposed", date(2031, 1, 31), self._boundary_quarter(
                Decimal("6.96275")
            ), 3,
            Decimal("25"), Decimal("100"), Decimal("10"), self._boundary_params(),
            self.amap, phase5.retained_payment_by_year(self.amap),
        )
        self.assertEqual(result["unsupported_gap"], Decimal("110"))
        self.assertEqual(result["availability"], 0)

    def test_33_existing_maturity_without_refinancing(self) -> None:
        last = self.existing_full[-1]
        self.assertEqual(last["maturity_event"], "yes")
        self.assertEqual(last["revolver_availability"], "0")
        self.assertGreater(Decimal(last["unsupported_maturity_funding_gap"]), 0)

    def test_34_reference_opening_balances(self) -> None:
        first = self.proposed_full[0]
        self.assertEqual(Decimal(first["opening_term_principal"]), Decimal("650"))
        self.assertEqual(Decimal(first["opening_revolver"]), Decimal("29.89771875"))
        self.assertEqual(Decimal(first["revolver_commitment"]), Decimal("300"))
        self.assertEqual(phase5.model_summary(self.existing_full)["peak_revolver"],
                         Decimal("207.39771875"))
        self.assertEqual(phase5.model_summary(self.existing_full)["min_availability"],
                         Decimal("261.40228125"))
        self.assertEqual(Decimal(first["letters_of_credit"]), Decimal("6.2"))

    def test_35_letters_of_credit_counted_once(self) -> None:
        for row in self.proposed_full:
            if row["maturity_event"] != "yes":
                self.assertEqual(
                    Decimal(row["revolver_availability"]),
                    Decimal(row["revolver_commitment"]) - Decimal(row["ending_revolver"])
                    - Decimal(row["letters_of_credit"]),
                )

    def test_36_restricted_and_book_cash_excluded(self) -> None:
        self.assertEqual(self.amap["P5A-017"]["value"], "0")
        self.assertIn("not evidence", self.amap["P5A-017"]["limitation_or_rationale"])

    def test_37_financing_fees_not_double_counted(self) -> None:
        self.assertEqual(self.amap["P5A-040"]["value"], "10")
        self.assertFalse(any("financing_fee" in row for row in self.proposed_full))

    def test_38_retained_obligations_consistent(self) -> None:
        self.assertTrue(all(Decimal(row["retained_finance_and_other_debt_opening_proxy"])
                            == Decimal("62.619") for row in self.debt))
        self.assertTrue(all(Decimal(row["retained_finance_and_other_debt_ending_proxy"])
                            == Decimal("62.619") for row in self.debt))

    def test_39_sources_and_uses_alignment(self) -> None:
        ref = [row for row in phase4.read_csv(phase4.PROCESSED / "CLOSING_BRIDGE.csv")
               if row["case_id"] == "CC-REF"]
        term = next(row for row in ref if row["item"] == "New term funding")
        revolver = next(row for row in ref if row["item"] == "Opening new-revolver draw")
        self.assertEqual(Decimal(term["closing_value"]), Decimal("650"))
        self.assertEqual(Decimal(revolver["closing_value"]), Decimal("29.89771875"))
        maturity_year = next(
            row for row in self.comparison
            if row["metric_name"] == "Phase 4 contractual funded principal payments in maturity fiscal year"
        )
        rolling_12 = next(
            row for row in self.comparison
            if row["metric_name"] == "Phase 4 contractual final rolling-12-month funded payments"
        )
        self.assertEqual(Decimal(maturity_year["existing_value"]), Decimal("566.25"))
        self.assertEqual(Decimal(rolling_12["existing_value"]), Decimal("572.5"))

    def test_40_same_operating_case_both_alternatives(self) -> None:
        for field in ("revenue", "lender_base_ebitda", "cfads_before_cash_interest"):
            proposed_q2 = sum(Decimal(row[field]) for row in self.proposed_full
                              if row["fiscal_year"] == "FY2026" and row["quarter"] == "Q2")
            existing_q2 = sum(Decimal(row[field]) for row in self.existing_full
                              if row["fiscal_year"] == "FY2026" and row["quarter"] == "Q2")
            self.assertEqual(proposed_q2, existing_q2)

    def test_41_amortization_sensitivities(self) -> None:
        values = {Decimal(row["annual_amortization_percent"]) for row in self.sensitivities
                  if row["sensitivity_dimension"] == "amortization"}
        self.assertEqual(values, {Decimal("5"), Decimal("10"), Decimal("15")})

    def test_42_pricing_sensitivities(self) -> None:
        values = {Decimal(row["spread_basis_points"]) for row in self.sensitivities
                  if row["sensitivity_dimension"] == "pricing"}
        self.assertEqual(values, {Decimal("250"), Decimal("300"), Decimal("350")})

    def test_43_no_formal_covenant_compliance(self) -> None:
        control = next(row for row in self.validations
                       if row["test_name"] == "formal_covenant_compliance_not_asserted")
        self.assertEqual(control["status"], "NOT_DETERMINABLE")
        docs = " ".join(path.read_text(encoding="utf-8") for path in phase5.DOCS.glob("*.md")).lower()
        self.assertNotIn("official covenant compliance: pass", docs)

    def test_44_source_ids_and_cutoff(self) -> None:
        catalog = phase5.source_manifest()
        for row in self.ledger:
            for source_id in filter(None, row["source_ids"].split(";")):
                self.assertIn(source_id, catalog)
                self.assertLessEqual(catalog[source_id]["publication_or_filing_date"], "2025-12-15")

    def test_45_raw_to_processed_lineage(self) -> None:
        assumption_ids = {row["assumption_id"] for row in self.assumptions}
        self.assertTrue(all(set(filter(None, row["assumption_ids"].split(";"))) <= assumption_ids
                            for row in self.operating))
        self.assertTrue(all(row["upstream_artifact"] for row in self.ledger))

    def test_46_all_validation_controls_pass_or_are_explicit_nd(self) -> None:
        self.assertFalse(any(row["status"] == "FAIL" for row in self.validations))
        self.assertEqual(sum(row["status"] == "NOT_DETERMINABLE" for row in self.validations), 7)

    def test_47_protected_prior_artifacts(self) -> None:
        self.assertEqual(phase5.protected_prior_changes(), [])
        phase4.validate()

    def test_48_deterministic_regeneration(self) -> None:
        before = phase5.fingerprints()
        phase5.build()
        self.assertEqual(before, phase5.fingerprints())

    def test_49_complete_validation(self) -> None:
        counts = phase5.validate()
        self.assertEqual(counts["post_cutoff_sources"], 0)
        self.assertEqual(counts["prior_phase_changes"], 0)

    def test_50_owner_reviewed_testing_assumptions(self) -> None:
        expected = {
            "P5A-001": "-0.5", "P5A-002": "0.5", "P5A-003": "27",
            "P5A-004": "14.9041", "P5A-005": "5.6292", "P5A-006": "41.5",
            "P5A-007": "72.5", "P5A-008": "9.8106", "P5A-009": "1.9673",
            "P5A-010": "5.8353", "P5A-011": "3.5", "P5A-012": "25",
            "P5A-013": "0.7", "P5A-014": "14.5", "P5A-015": "5",
            "P5A-017": "0", "P5A-018": "3.57", "P5A-019": "300",
            "P5A-020": "6.57", "P5A-022": "50", "P5A-038": "6.146",
            "P5A-041": "365",
        }
        for aid, value in expected.items():
            self.assertEqual(self.amap[aid]["value"], value)
            self.assertEqual(self.amap[aid]["review_status"],
                             "owner_reviewed_for_phase5_testing")
        for aid in ("P5A-023", "P5A-024", "P5A-039"):
            self.assertEqual(self.amap[aid]["review_status"],
                             "owner_reviewed_for_phase5_testing")

    def test_51_same_timestamp_opening_bridge(self) -> None:
        same_point = {"Ending term debt", "Ending revolver debt", "Ending total bank debt",
                      "Ending cash", "Available revolver capacity after LCs"}
        self.assertTrue(all(row["as_of_or_period"] == "2026-02-01_00:00"
                            for row in self.opening_bridge if row["item"] in same_point))
        docs = (phase5.DOCS / "METHODOLOGY.md").read_text(encoding="utf-8")
        self.assertIn("immediately before", docs)

    def test_52_january_installment_and_accrued_interest_once(self) -> None:
        bridge = {row["item"]: row for row in self.opening_bridge}
        self.assertEqual(Decimal(bridge["January 31 Term A installment"]["existing_value"]),
                         Decimal("6.25"))
        accrued = bridge["Accrued interest through closing timestamp"]
        self.assertEqual((Decimal(accrued["existing_value"]), Decimal(accrued["proposed_value"])),
                         (Decimal("3.64771875"), Decimal("3.64771875")))
        self.assertEqual(self.amap["P5A-027"]["value"], "462.5")
        self.assertEqual(self.amap["P5A-028"]["value"], "207.39771875")

    def test_53_fee_once_and_phase4_sources_uses_unchanged(self) -> None:
        bridge = {row["item"]: row for row in self.opening_bridge}
        self.assertEqual(Decimal(bridge["Refinancing fees"]["proposed_value"]), Decimal("10"))
        p4 = phase5.phase4_reference_closing_values()
        self.assertEqual(p4["new_term"], Decimal("650"))
        self.assertEqual(p4["new_revolver"], Decimal("29.89771875"))
        self.assertFalse(any("financing_fee" in row for row in self.proposed_full))

    def test_54_opening_debt_difference_fully_explained(self) -> None:
        bridge = {row["item"]: row for row in self.opening_bridge}
        prior = bridge["Previously reported opening bank debt"]
        self.assertEqual(Decimal(prior["proposed_value"]) - Decimal(prior["existing_value"]),
                         Decimal("19.89771875"))
        ending = bridge["Ending total bank debt"]
        self.assertEqual(Decimal(ending["existing_value"]), Decimal("669.89771875"))
        self.assertEqual(Decimal(ending["proposed_value"]), Decimal("679.89771875"))
        self.assertEqual(Decimal(ending["proposed_value"]) - Decimal(ending["existing_value"]),
                         Decimal("10"))

    def test_55_mandatory_debt_service_before_distributions(self) -> None:
        for row in self.proposed_full + self.existing_full:
            expected = (
                Decimal(row["opening_cash"]) + Decimal(row["cfads_before_cash_interest"])
                + Decimal(row["cash_interest"])
                + Decimal(row["retained_finance_and_other_debt_payment"])
                - Decimal(row["scheduled_term_principal"])
            )
            self.assertEqual(
                expected,
                Decimal(row["cash_after_mandatory_debt_service_before_distributions"]),
            )
            self.assertEqual(row["scheduled_principal_priority_status"],
                             "mandatory_before_distributions")

    def test_56_distribution_no_revolver_and_draw_boundaries(self) -> None:
        cash_funded = phase5.distribution_funding(
            "proposed", Decimal("50"), Decimal("25"), Decimal("0"),
            Decimal("0"), Decimal("5"),
        )
        self.assertEqual(cash_funded["repurchase_cash_funded"], Decimal("5"))
        self.assertEqual(cash_funded["repurchase_draw_caused"], Decimal("0"))
        draw_funded = phase5.distribution_funding(
            "proposed", Decimal("25"), Decimal("25"), Decimal("0"),
            Decimal("0"), Decimal("5"),
        )
        self.assertEqual(draw_funded["repurchase_draw_caused"], Decimal("5"))
        self.assertEqual(draw_funded["debt_funded_buyback_flag"], "yes")
        self.assertEqual(draw_funded["provisional_compliance"],
                         "not_compliant_debt_funded_buyback")

    def test_57_buyback_while_revolver_outstanding_is_visible(self) -> None:
        result = phase5.distribution_funding(
            "proposed", Decimal("50"), Decimal("25"), Decimal("10"),
            Decimal("0"), Decimal("5"),
        )
        self.assertEqual(result["repurchase_draw_caused"], Decimal("0"))
        self.assertEqual(result["repurchase_paid_while_revolver"], Decimal("5"))
        self.assertEqual(result["provisional_compliance"],
                         "pending_information_buyback_while_revolver_outstanding")

    def test_58_dividend_debt_funding_flag(self) -> None:
        result = phase5.distribution_funding(
            "proposed", Decimal("24"), Decimal("25"), Decimal("0"),
            Decimal("2"), Decimal("0"),
        )
        self.assertEqual(result["dividend_draw_caused"], Decimal("2"))
        self.assertEqual(result["debt_funded_dividend_flag"], "yes")

    def test_59_distribution_reduction_not_implemented(self) -> None:
        self.assertTrue(all(Decimal(row["planned_repurchase"]) > 0
                            for row in self.distributions))
        self.assertTrue(any(Decimal(row["amount_to_suspend_or_fund_differently"]) > 0
                            for row in self.distributions if row["structure"] == "proposed"))

    def test_60_existing_pricing_grid_and_rate_neutral_label(self) -> None:
        grid = [row for row in self.sensitivities
                if row["sensitivity_dimension"] == "existing_contractual_pricing_grid"]
        self.assertEqual({Decimal(row["spread_basis_points"]) for row in grid},
                         {Decimal("200"), Decimal("225"), Decimal("250"), Decimal("275")})
        self.assertEqual({Decimal(row["all_in_rate_percent"]) for row in grid},
                         {Decimal("5.57"), Decimal("5.82"), Decimal("6.07"), Decimal("6.32")})
        neutral = next(row for row in self.sensitivities
                       if row["case_name"] == "6.57_percent_rate_neutral")
        self.assertEqual(neutral["rate_case_type"],
                         "rate_neutral_not_actual_or_representative")
        self.assertEqual(neutral["pricing_tier_status"],
                         "not_a_contractual_tier_selection")

    def test_61_existing_pricing_tier_and_fees_remain_not_determinable(self) -> None:
        nd = {row["test_name"] for row in self.validations
              if row["status"] == "NOT_DETERMINABLE"}
        self.assertIn("applicable_existing_pricing_tier", nd)
        self.assertIn("recurring_financing_fees", nd)
        self.assertEqual(self.amap["P5A-042"]["value"], "")

    def test_62_common_horizon_and_proposed_tail_are_separate(self) -> None:
        common = [row for row in self.common_horizon if row["segment"] == "common_horizon"]
        tail = [row for row in self.common_horizon if row["segment"] == "proposed_extension_tail"]
        self.assertTrue(all((row["period_start"], row["period_end"])
                            == ("2026-02-01", "2029-07-31") for row in common))
        self.assertTrue(all(row["measurement_event"] == "existing_maturity_2029-08-01"
                            for row in common))
        self.assertTrue(all((row["period_start"], row["period_end"])
                            == ("2029-08-01", "2031-01-31") for row in tail))
        self.assertTrue(all(row["existing_value"] == "not_applicable" for row in tail))

    def test_63_ultimate_maturity_gaps_and_no_post_maturity_availability(self) -> None:
        tail_gap = next(row for row in self.common_horizon
                        if row["segment"] == "proposed_extension_tail"
                        and row["metric_name"] == "unsupported_maturity_funding_gap")
        self.assertEqual(Decimal(tail_gap["proposed_value"]),
                         Decimal(self.proposed_full[-1]["unsupported_maturity_funding_gap"]))
        self.assertGreater(Decimal(self.existing_full[-1]["unsupported_maturity_funding_gap"]), 0)
        self.assertEqual(Decimal(self.existing_full[-1]["revolver_availability"]), 0)
        self.assertEqual(Decimal(self.proposed_full[-1]["revolver_availability"]), 0)

    def test_64_fy2026_period_presentation_reconciles(self) -> None:
        rows = {row["period_label"] + "|" + row["structure"]: row
                for row in self.period_presentation}
        q1 = rows["FY2026_Q1_pre_closing_operations|common_operating"]
        q2 = rows["FY2026_Q2_Q4_post_closing|existing"]
        full = rows["FY2026_full_year_operating|common_operating"]
        for field in ("revenue", "lender_base_ebitda", "cfads_before_cash_interest"):
            self.assertEqual(Decimal(q1[field]) + Decimal(q2[field]), Decimal(full[field]))
        for structure in ("existing", "proposed"):
            row = rows[f"FY2026_full_year_financing|{structure}"]
            self.assertEqual(row["status"], "not_determinable_incomplete_q1_financing")
            self.assertEqual((row["cash_interest"], row["cfo_proxy"], row["fcf_proxy"]),
                             ("", "", ""))

    def test_65_fy2031_q1_seasonality_explanation(self) -> None:
        analysis = (phase5.DOCS / "BASE_CASE_ANALYSIS.md").read_text(encoding="utf-8")
        self.assertIn("seasonal-quarter output", analysis)
        last = self.operating[-1]
        self.assertLess(Decimal(last["lender_base_ebitda_margin_percent"]), Decimal("12"))

    def test_66_phase6_not_embedded_in_approved_phase5_commit(self) -> None:
        tree = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", phase5.APPROVED_PHASE5_COMMIT],
            cwd=ROOT, text=True, capture_output=True, check=True,
        ).stdout.splitlines()
        self.assertFalse(any(path == "scripts/phase6.py" for path in tree))
        self.assertFalse(any(path.startswith("data/phase6/") for path in tree))
        self.assertFalse(any(path.startswith("docs/phase-6/") for path in tree))


if __name__ == "__main__":
    unittest.main()
