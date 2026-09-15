"""Decision-relevant tests for Phase 6 downside and liquidity analysis."""

from __future__ import annotations

import csv
import sys
import unittest
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import phase6  # noqa: E402


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class Phase6Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assumptions = read_csv(phase6.RAW / "SCENARIO_ASSUMPTIONS.csv")
        cls.mitigations = read_csv(phase6.RAW / "MITIGATION_DECISIONS.csv")
        cls.results = read_csv(phase6.PROCESSED / "SCENARIO_RESULTS.csv")
        cls.monthly = read_csv(phase6.PROCESSED / "MONTHLY_LIQUIDITY_STRESS.csv")
        cls.quarterly = read_csv(phase6.PROCESSED / "QUARTERLY_STRESS_FORECAST.csv")
        cls.debt = read_csv(phase6.PROCESSED / "SCENARIO_DEBT_SCHEDULE.csv")
        cls.events = read_csv(phase6.PROCESSED / "FIRST_DISTRESS_EVENTS.csv")
        cls.thresholds = read_csv(phase6.PROCESSED / "ANALYTICAL_THRESHOLD_TESTS.csv")
        cls.drawability = read_csv(phase6.PROCESSED / "DRAWABILITY_PATHS.csv")
        cls.mitigation_results = read_csv(phase6.PROCESSED / "MITIGATION_RESULTS.csv")
        cls.reverse = read_csv(phase6.PROCESSED / "REVERSE_STRESS_RESULTS.csv")
        cls.grids = read_csv(phase6.PROCESSED / "SENSITIVITY_GRIDS.csv")
        cls.timing = read_csv(phase6.PROCESSED / "TIMING_SENSITIVITY_RESULTS.csv")
        cls.validations = read_csv(phase6.PROCESSED / "VALIDATION_RESULTS.csv")
        cls.ledger = read_csv(phase6.DOCS / "SOURCE_LEDGER.csv")
        cls.result_index = {(row["scenario_id"], row["structure"]): row for row in cls.results}

    def test_01_required_scenarios(self) -> None:
        self.assertEqual({config.scenario_id for config in phase6.SCENARIOS}, {
            "BASE", "MODERATE_UNMITIGATED", "SEVERE_UNMITIGATED",
            "MODERATE_MITIGATED", "SEVERE_MITIGATED",
            "MODERATE_NO_WAIVER", "SEVERE_NO_WAIVER",
        })

    def test_02_scenario_assumption_count(self) -> None:
        self.assertEqual(len(self.assumptions), 84)

    def test_03_mitigation_count(self) -> None:
        self.assertEqual(len(self.mitigations), 8)

    def test_04_exact_scenario_values_are_owner_reviewed_for_testing(self) -> None:
        selected = [row for row in self.assumptions if row["scenario_id"] != "BASE"]
        self.assertTrue(all(row["review_status"] == "owner_reviewed_for_phase6_testing" for row in selected))

    def test_05_base_operating_parity(self) -> None:
        base = phase6.build_operating(phase6.scenario_by_id("BASE"))
        committed = read_csv(phase6.PHASE5_OPERATING)
        for left, right in zip(base, committed, strict=True):
            for field in ("revenue", "gross_profit", "lender_base_ebitda", "cash_tax_proxy", "working_capital_cash_flow", "capital_expenditures", "cfads_before_cash_interest"):
                self.assertLessEqual(abs(phase6.dec(left[field]) - phase6.dec(right[field])), phase6.TOLERANCE)

    def test_06_opening_debt_parity(self) -> None:
        self.assertEqual(phase6.dec(self.result_index[("BASE", "proposed")]["opening_bank_debt"]), Decimal("679.89771875"))
        self.assertEqual(phase6.dec(self.result_index[("BASE", "existing")]["opening_bank_debt"]), Decimal("669.89771875"))

    def test_07_base_minimum_liquidity_parity(self) -> None:
        self.assertLessEqual(abs(phase6.dec(self.result_index[("BASE", "proposed")]["minimum_usable_liquidity"]) - Decimal("253.8458349441112245272416091")), phase6.TOLERANCE)
        self.assertLessEqual(abs(phase6.dec(self.result_index[("BASE", "existing")]["minimum_usable_liquidity"]) - Decimal("261.40228125")), phase6.TOLERANCE)

    def test_08_base_maturity_gap_parity(self) -> None:
        self.assertEqual(phase6.dec(self.result_index[("BASE", "proposed")]["unsupported_maturity_gap"]), Decimal("340.9478312215931607465924833"))
        self.assertEqual(phase6.dec(self.result_index[("BASE", "existing")]["unsupported_maturity_gap"]), Decimal("432.7492812067100176549274129"))

    def test_09_base_distribution_parity_common_horizon(self) -> None:
        rows = [row for row in self.monthly if row["scenario_id"] == "BASE" and row["structure"] == "proposed" and row["month_end"] <= "2029-07-31"]
        direct = sum((phase6.dec(row["repurchase_revolver_draw_caused"]) for row in rows), Decimal("0"))
        broad = sum((phase6.dec(row["repurchase_paid_while_revolver_outstanding"]) for row in rows), Decimal("0"))
        self.assertAlmostEqual(float(direct), 6.753542803967386, places=9)
        self.assertEqual(broad, Decimal("17.50000000000000000000000007"))

    def test_10_moderate_no_stronger_than_severe(self) -> None:
        moderate = phase6.scenario_by_id("MODERATE_UNMITIGATED")
        severe = phase6.scenario_by_id("SEVERE_UNMITIGATED")
        self.assertLessEqual(abs(moderate.volume_percent), abs(severe.volume_percent))
        self.assertLessEqual(abs(moderate.margin_bps), abs(severe.margin_bps))
        self.assertLessEqual(moderate.dso_days, severe.dso_days)
        self.assertLessEqual(moderate.dio_days, severe.dio_days)

    def test_11_moderate_timing_and_recovery(self) -> None:
        config = phase6.scenario_by_id("MODERATE_UNMITIGATED")
        self.assertEqual(phase6.shock_factor(config, "FY2026", "Q1"), 0)
        self.assertEqual(phase6.shock_factor(config, "FY2026", "Q2"), 1)
        self.assertEqual(phase6.shock_factor(config, "FY2027", "Q1"), 1)
        self.assertEqual(phase6.shock_factor(config, "FY2027", "Q2"), Decimal("0.75"))
        self.assertEqual(phase6.shock_factor(config, "FY2028", "Q1"), 0)

    def test_12_severe_timing_and_recovery(self) -> None:
        config = phase6.scenario_by_id("SEVERE_UNMITIGATED")
        self.assertEqual(phase6.shock_factor(config, "FY2028", "Q1"), 1)
        self.assertEqual(phase6.shock_factor(config, "FY2028", "Q2"), Decimal("0.8"))
        self.assertEqual(phase6.shock_factor(config, "FY2029", "Q2"), 0)

    def test_13_volume_transmission(self) -> None:
        base = phase6.build_operating(phase6.scenario_by_id("BASE"))[1]
        moderate = phase6.build_operating(phase6.scenario_by_id("MODERATE_UNMITIGATED"))[1]
        self.assertLessEqual(abs(phase6.dec(moderate["revenue"]) - phase6.dec(base["revenue"]) * Decimal("0.935")), phase6.TOLERANCE)

    def test_14_margin_transmission(self) -> None:
        row = phase6.build_operating(phase6.scenario_by_id("MODERATE_UNMITIGATED"))[1]
        expected = phase6.dec(row["revenue"]) * phase6.dec(row["gross_margin_percent"]) / 100
        self.assertLessEqual(abs(phase6.dec(row["gross_profit"]) - expected), phase6.TOLERANCE)

    def test_15_no_fixed_cost_double_counting(self) -> None:
        self.assertTrue(all("gross-margin shock includes fixed-cost deleverage" in row["double_counting_control"] for row in phase6.build_operating(phase6.scenario_by_id("SEVERE_UNMITIGATED"))))

    def test_16_working_capital_days_change_balances(self) -> None:
        base = phase6.build_operating(phase6.scenario_by_id("BASE"))[1]
        severe = phase6.build_operating(phase6.scenario_by_id("SEVERE_UNMITIGATED"))[1]
        self.assertGreater(phase6.dec(severe["days_sales_outstanding"]), phase6.dec(base["days_sales_outstanding"]))
        self.assertGreater(phase6.dec(severe["days_inventory_outstanding"]), phase6.dec(base["days_inventory_outstanding"]))

    def test_17_no_generic_working_capital_plug(self) -> None:
        self.assertTrue(all("generic working-capital plug" in row["double_counting_control"] for row in phase6.build_operating(phase6.scenario_by_id("SEVERE_UNMITIGATED"))))

    def test_18_remediation_cash_only(self) -> None:
        rows = phase6.build_operating(phase6.scenario_by_id("SEVERE_UNMITIGATED"))
        self.assertEqual(sum((phase6.dec(row["additional_remediation_cash_use"]) for row in rows), Decimal("0")), Decimal("-10"))

    def test_19_cash_tax_never_positive(self) -> None:
        for config in phase6.SCENARIOS:
            self.assertTrue(all(phase6.dec(row["cash_tax_proxy"]) <= 0 for row in phase6.build_operating(config)))

    def test_20_rate_shock_transmission(self) -> None:
        row = next(row for row in self.monthly if row["scenario_id"] == "MODERATE_UNMITIGATED" and row["structure"] == "proposed" and row["month_end"] == "2026-02-28")
        self.assertEqual(phase6.dec(row["all_in_rate_percent"]), Decimal("7.57"))

    def test_21_additional_borrowing_increases_later_interest(self) -> None:
        rows = [row for row in self.monthly if row["scenario_id"] == "SEVERE_UNMITIGATED" and row["structure"] == "proposed"]
        self.assertGreater(phase6.dec(rows[1]["cash_interest_due"]), phase6.dec(rows[0]["cash_interest_due"]))

    def test_22_unmitigated_distributions_remain(self) -> None:
        rows = [row for row in self.monthly if "UNMITIGATED" in row["scenario_id"]]
        self.assertTrue(all(row["base_planned_dividend"] == row["planned_dividend_after_mitigation"] and row["base_planned_repurchase"] == row["planned_repurchase_after_mitigation"] for row in rows))

    def test_23_mitigations_start_after_lag(self) -> None:
        rows = [row for row in self.monthly if row["scenario_id"].endswith("MITIGATED") and row["month_end"] < "2026-05-01"]
        self.assertTrue(all(phase6.dec(row["dividend_suspended"]) == 0 and phase6.dec(row["repurchase_suspended"]) == 0 for row in rows))

    def test_24_mitigation_implementation_costs(self) -> None:
        credited = [row for row in self.mitigations if row["modeled_credit"] == "yes"]
        self.assertTrue(all(phase6.dec(row["implementation_cost"]) == 0 for row in credited))

    def test_25_maintenance_capex_preserved(self) -> None:
        self.assertTrue(all(phase6.dec(row["capital_expenditures"]) < 0 for row in self.monthly))

    def test_26_mitigation_caps(self) -> None:
        self.assertTrue(all(phase6.dec(row["repurchase_suspended"]) <= phase6.dec(row["base_planned_repurchase"]) for row in self.monthly))
        self.assertTrue(all(phase6.dec(row["dividend_suspended"]) <= phase6.dec(row["base_planned_dividend"]) for row in self.monthly))

    def test_27_mitigated_does_not_overwrite_unmitigated(self) -> None:
        self.assertIn(("SEVERE_UNMITIGATED", "proposed"), self.result_index)
        self.assertIn(("SEVERE_MITIGATED", "proposed"), self.result_index)
        self.assertNotEqual(self.result_index[("SEVERE_UNMITIGATED", "proposed")]["unsupported_maturity_gap"], self.result_index[("SEVERE_MITIGATED", "proposed")]["unsupported_maturity_gap"])

    def test_28_no_unsupported_proceeds(self) -> None:
        for row in self.monthly:
            constructed = sum((phase6.dec(row[field]) for field in ("lender_base_ebitda", "cash_tax_proxy", "working_capital_cash_flow", "capital_expenditures", "other_operating_cash_uses")), Decimal("0"))
            self.assertLessEqual(abs(constructed - phase6.dec(row["cfads_before_cash_interest"])), phase6.TOLERANCE)

    def test_29_cash_floor_calculation(self) -> None:
        for row in self.monthly:
            expected = max(Decimal("0"), phase6.dec(row["operating_cash_floor"]) - phase6.dec(row["ending_cash"]))
            self.assertEqual(phase6.dec(row["cash_floor_shortfall"]), expected)

    def test_30_liquidity_boundary(self) -> None:
        self.assertEqual(phase6.analytical_liquidity_test(Decimal("50")), (False, "PASS"))
        self.assertTrue(phase6.analytical_liquidity_test(Decimal("49.999999"))[0])

    def test_31_letters_of_credit_counted_once(self) -> None:
        for row in self.monthly:
            if row["maturity_event"] != "yes":
                expected = phase6.dec(row["revolver_commitment"]) - phase6.dec(row["letters_of_credit"]) - phase6.dec(row["ending_revolver"])
                self.assertEqual(phase6.dec(row["nominal_revolver_availability"]), expected)

    def test_32_restricted_cash_not_assumed(self) -> None:
        self.assertTrue(all("eligible cash" in row["limitations"] for row in self.monthly))

    def test_33_revolver_commitment_limit(self) -> None:
        self.assertTrue(all(phase6.dec(row["ending_revolver"]) <= phase6.dec(row["revolver_commitment"]) - phase6.dec(row["letters_of_credit"]) + phase6.TOLERANCE for row in self.monthly))

    def test_34_no_negative_revolver_or_availability(self) -> None:
        self.assertTrue(all(phase6.dec(row["ending_revolver"]) >= 0 and phase6.dec(row["usable_revolver_availability"]) >= 0 for row in self.monthly))

    def test_35_no_post_maturity_drawability(self) -> None:
        maturity = [row for row in self.monthly if row["maturity_event"] == "yes"]
        self.assertTrue(all(phase6.dec(row["usable_revolver_availability"]) == 0 for row in maturity))

    def test_36_scheduled_payment_order(self) -> None:
        paid, shortfall, resources = phase6.allocate_payment(Decimal("5"), Decimal("7"))
        self.assertEqual((paid, shortfall, resources), (Decimal("5"), Decimal("2"), Decimal("0")))

    def test_37_interest_failure_flag(self) -> None:
        failures = [row for row in self.monthly if phase6.dec(row["cash_interest_shortfall"]) > phase6.TOLERANCE]
        self.assertTrue(failures)
        self.assertTrue(all(row["model_status"] == "MANDATORY_PAYMENT_FAILURE" for row in failures))

    def test_38_principal_failure_flag(self) -> None:
        failures = [row for row in self.monthly if phase6.dec(row["scheduled_principal_shortfall"]) > phase6.TOLERANCE]
        self.assertTrue(failures)
        self.assertTrue(all(row["model_status"] == "MANDATORY_PAYMENT_FAILURE" for row in failures))

    def test_39_maturity_shortfall(self) -> None:
        self.assertTrue(all(phase6.dec(row["unsupported_maturity_gap"]) > 0 for row in self.results))

    def test_40_waiver_no_waiver_divergence(self) -> None:
        waiver = self.result_index[("MODERATE_UNMITIGATED", "proposed")]
        no_waiver = self.result_index[("MODERATE_NO_WAIVER", "proposed")]
        self.assertGreater(phase6.dec(waiver["minimum_usable_liquidity"]), phase6.dec(no_waiver["minimum_usable_liquidity"]))

    def test_41_exact_325_leverage_boundary(self) -> None:
        ratio, failed, status = phase6.analytical_leverage_test(Decimal("325"), Decimal("100"), Decimal("3.25"))
        self.assertEqual((ratio, failed, status), (Decimal("3.25"), False, "PASS"))

    def test_42_one_unit_around_325_boundary(self) -> None:
        self.assertFalse(phase6.analytical_leverage_test(Decimal("324"), Decimal("100"), Decimal("3.25"))[1])
        self.assertTrue(phase6.analytical_leverage_test(Decimal("326"), Decimal("100"), Decimal("3.25"))[1])

    def test_43_exact_300_leverage_boundary(self) -> None:
        self.assertFalse(phase6.analytical_leverage_test(Decimal("300"), Decimal("100"), Decimal("3.00"))[1])

    def test_44_exact_300_coverage_boundary(self) -> None:
        self.assertFalse(phase6.analytical_coverage_test(Decimal("300"), Decimal("100"))[1])
        self.assertTrue(phase6.analytical_coverage_test(Decimal("299.999"), Decimal("100"))[1])

    def test_45_zero_and_negative_ebitda(self) -> None:
        self.assertEqual(phase6.analytical_leverage_test(Decimal("1"), Decimal("0"), Decimal("3.25"))[2], "N/M_FAILURE")
        self.assertEqual(phase6.analytical_leverage_test(Decimal("1"), Decimal("-1"), Decimal("3.25"))[2], "N/M_FAILURE")

    def test_46_missing_contractual_inputs(self) -> None:
        self.assertEqual(phase6.formal_contractual_compliance(None, Decimal("100")), "NOT_DETERMINABLE")
        self.assertEqual(phase6.formal_contractual_compliance(Decimal("10"), None), "NOT_DETERMINABLE")

    def test_47_analytical_not_contractual_labels(self) -> None:
        self.assertTrue(all(row["formal_contractual_compliance"] == "NOT_DETERMINABLE" for row in self.thresholds))
        self.assertTrue(all("analytical" in row["classification"] for row in self.thresholds))

    def test_48_drawability_shutoff_timing(self) -> None:
        rows = [row for row in self.monthly if row["scenario_id"] == "MODERATE_NO_WAIVER" and row["structure"] == "proposed"]
        trigger = next(row for row in rows if row["analytical_leverage_failure_flag"] == "yes")
        shutoff = next(row for row in rows if row["drawability_status"] == "no_waiver_drawability_shutoff")
        self.assertEqual(date.fromisoformat(shutoff["month_start"]), phase6.next_month_start(date.fromisoformat(trigger["month_end"])))

    def test_49_reverse_search_bounds_and_tolerances(self) -> None:
        for row in self.reverse:
            self.assertLessEqual(phase6.dec(row["lower_bound"]), phase6.dec(row["upper_bound"]))
            self.assertGreater(phase6.dec(row["search_tolerance"]), 0)

    def test_50_reverse_search_statuses(self) -> None:
        allowed = {
            "threshold_already_failed", "not_reached_within_bounds",
            "approximated_first_failure",
            "not_applicable_existing_analytical_warning_only",
        }
        self.assertTrue(all(row["threshold_status"] in allowed for row in self.reverse))

    def test_51_reverse_search_not_reached(self) -> None:
        row = next(row for row in self.reverse if row["structure"] == "existing" and row["test_name"].startswith("volume decline"))
        self.assertEqual(row["threshold_status"], "not_reached_within_bounds")

    def test_52_reverse_search_first_failure_period(self) -> None:
        row = next(row for row in self.reverse if row["structure"] == "proposed" and row["test_name"].startswith("rate increase"))
        config = phase6.constant_config("VERIFY-RATE", rate_bps=phase6.dec(row["result_value"]))
        result = phase6.failure_snapshot(phase6.run_case(config, "proposed"), "interest_coverage")
        self.assertTrue(result[0])
        self.assertEqual(result[1], row["first_failure_date"])

    def test_53_reverse_results_do_not_overstate_precision(self) -> None:
        for row in self.reverse:
            if row["result_value"]:
                value = phase6.dec(row["result_value"])
                tolerance = phase6.dec(row["search_tolerance"])
                self.assertEqual(value, value.quantize(tolerance))

    def test_54_grid_monotonicity_volume_margin(self) -> None:
        rows = [row for row in self.grids if row["grid_name"] == "volume_vs_gross_margin" and row["structure"] == "proposed" and row["y_value"] == "300"]
        rows.sort(key=lambda row: phase6.dec(row["x_value"]))
        liquidities = [phase6.dec(row["minimum_usable_liquidity"]) for row in rows]
        self.assertEqual(liquidities, sorted(liquidities, reverse=True))

    def test_55_monthly_to_quarterly_reconciliation(self) -> None:
        groups: dict[tuple[str, str, str, str], Decimal] = defaultdict(Decimal)
        for row in self.monthly:
            groups[(row["scenario_id"], row["structure"], row["fiscal_year"], row["quarter"])] += phase6.dec(row["cfads_before_cash_interest"])
        index = {(row["scenario_id"], row["structure"], row["fiscal_year"], row["quarter"]): phase6.dec(row["cfads_before_cash_interest"]) for row in self.quarterly}
        self.assertTrue(all(abs(value - index[key]) <= phase6.TOLERANCE for key, value in groups.items()))

    def test_56_quarterly_to_annual_reconciliation(self) -> None:
        monthly_groups: dict[tuple[str, str, str], Decimal] = defaultdict(Decimal)
        quarterly_groups: dict[tuple[str, str, str], Decimal] = defaultdict(Decimal)
        for row in self.monthly:
            monthly_groups[(row["scenario_id"], row["structure"], row["fiscal_year"])] += phase6.dec(row["revenue"])
        for row in self.quarterly:
            quarterly_groups[(row["scenario_id"], row["structure"], row["fiscal_year"])] += phase6.dec(row["revenue"])
        self.assertTrue(all(abs(value - quarterly_groups[key]) <= phase6.TOLERANCE for key, value in monthly_groups.items()))

    def test_57_same_operating_stress_both_structures(self) -> None:
        groups: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        for row in self.quarterly:
            groups[(row["scenario_id"], row["fiscal_year"], row["quarter"])].add(row["lender_base_ebitda"])
        self.assertTrue(all(len(values) == 1 for values in groups.values()))

    def test_58_traceable_scenario_and_mitigation_ids(self) -> None:
        self.assertTrue(all(row["upstream_ids"] for row in self.results))
        self.assertTrue(all(row["mitigation_id"].startswith("MIT-") for row in self.mitigations))

    def test_59_source_ids_valid_and_within_cutoff(self) -> None:
        manifest = phase6.phase5.source_manifest()
        for row in self.ledger:
            self.assertEqual(row["cutoff_status"], "within_cutoff")
            for source_id in row["source_ids"].split(";"):
                if source_id:
                    self.assertIn(source_id, manifest)

    def test_60_all_validation_controls_pass(self) -> None:
        self.assertTrue(self.validations)
        self.assertTrue(all(row["status"] == "PASS" for row in self.validations))

    def test_61_protected_prior_artifacts_unchanged(self) -> None:
        self.assertEqual(phase6.prior_analytical_artifact_changes(), [])

    def test_62_changed_paths_are_phase6_scoped(self) -> None:
        phase6.validate_changed_paths()

    def test_63_deterministic_regeneration(self) -> None:
        before = phase6.fingerprints()
        phase6.build()
        after = phase6.fingerprints()
        self.assertEqual(before, after)

    def test_64_descendant_aware_validation_checkpoint(self) -> None:
        self.assertEqual(
            phase6.APPROVED_PHASE6_COMMIT,
            "b5554f8848e1622ae1de1e371b974c886f3e33db",
        )
        self.assertFalse(phase6.approved_phase6_contains_phase7())
        phase6.validate_changed_paths()

    def test_65_validate_entry_point(self) -> None:
        self.assertEqual(phase6.validate()["status"], "PASS")

    def test_66_zero_shock_monthly_schedule_matches_phase5(self) -> None:
        control = next(row for row in self.validations if row["test_name"] == "Phase 5 first-24-month zero-shock schedule")
        self.assertEqual(control["status"], "PASS")

    def test_67_opening_revolver_exceeds_all_later_balances(self) -> None:
        rows = [
            {"month_end": "2026-02-28", "opening_revolver": "10", "ending_revolver": "9", "revolver_draw": "0", "revolver_repayment": "1"},
            {"month_end": "2026-03-31", "opening_revolver": "9", "ending_revolver": "8", "revolver_draw": "0", "revolver_repayment": "1"},
        ]
        measures = phase6.revolver_path_measures(rows)
        self.assertEqual(measures["peak_revolver_including_opening"], Decimal("10"))
        self.assertEqual(measures["peak_revolver_date"], "OPENING_POSITION")

    def test_68_later_revolver_exceeds_opening(self) -> None:
        rows = [
            {"month_end": "2026-02-28", "opening_revolver": "10", "ending_revolver": "9", "revolver_draw": "0", "revolver_repayment": "1"},
            {"month_end": "2026-03-31", "opening_revolver": "9", "ending_revolver": "12", "revolver_draw": "3", "revolver_repayment": "0"},
        ]
        measures = phase6.revolver_path_measures(rows)
        self.assertEqual(measures["peak_revolver_including_opening"], Decimal("12"))
        self.assertEqual(measures["peak_revolver_date"], "2026-03-31")

    def test_69_opening_and_subsequent_peak_equal(self) -> None:
        rows = [
            {"month_end": "2026-02-28", "opening_revolver": "10", "ending_revolver": "10", "revolver_draw": "0", "revolver_repayment": "0"},
        ]
        measures = phase6.revolver_path_measures(rows)
        self.assertEqual(measures["peak_subsequent_period_end_revolver"], Decimal("10"))
        self.assertEqual(measures["peak_revolver_date"], "OPENING_POSITION")

    def test_70_base_headline_peak_matches_phase5(self) -> None:
        phase5_common = {row["metric_name"]: row for row in read_csv(phase6.PHASE5_COMMON)}
        for structure in ("proposed", "existing"):
            self.assertLessEqual(abs(
                phase6.dec(self.result_index[("BASE", structure)]["peak_revolver_including_opening"])
                - phase6.dec(phase5_common["peak_revolver_usage"][f"{structure}_value"])
            ), phase6.TOLERANCE)

    def test_71_existing_base_headline_peak_is_opening(self) -> None:
        row = self.result_index[("BASE", "existing")]
        self.assertEqual(phase6.dec(row["opening_revolver_balance"]), Decimal("207.39771875"))
        self.assertEqual(row["peak_revolver_date"], "OPENING_POSITION")
        self.assertGreater(phase6.dec(row["peak_revolver_including_opening"]), phase6.dec(row["peak_subsequent_period_end_revolver"]))

    def test_72_peak_definition_reaches_grid_reverse_and_mitigation_outputs(self) -> None:
        for row in self.grids:
            self.assertGreaterEqual(phase6.dec(row["peak_revolver_including_opening"]), phase6.dec(row["opening_revolver_balance"]))
            self.assertGreaterEqual(phase6.dec(row["peak_revolver_including_opening"]), phase6.dec(row["peak_subsequent_period_end_revolver"]))
        for row in self.reverse:
            if row["opening_revolver_balance"]:
                self.assertGreaterEqual(phase6.dec(row["peak_revolver_including_opening"]), phase6.dec(row["opening_revolver_balance"]))
        for row in self.mitigation_results:
            self.assertGreaterEqual(phase6.dec(row["peak_revolver_including_opening_unmitigated"]), phase6.dec(row["opening_revolver_balance"]))
            self.assertGreaterEqual(phase6.dec(row["peak_revolver_including_opening_mitigated"]), phase6.dec(row["opening_revolver_balance"]))

    def test_73_opening_exposure_is_not_incremental_draw(self) -> None:
        self.assertTrue(all(row["first_incremental_post_closing_draw_date"] != "OPENING_POSITION" for row in self.results))

    def test_74_repayment_then_later_incremental_draw(self) -> None:
        row = self.result_index[("BASE", "existing")]
        self.assertEqual(row["first_revolver_repayment_date"], "2026-02-28")
        self.assertEqual(row["first_incremental_post_closing_draw_date"], "2026-11-30")

    def test_75_no_incremental_post_closing_draw(self) -> None:
        rows = [
            {"month_end": "2026-02-28", "opening_revolver": "10", "ending_revolver": "9", "revolver_draw": "0", "revolver_repayment": "1"},
        ]
        self.assertEqual(phase6.revolver_path_measures(rows)["first_incremental_post_closing_draw_date"], "")

    def test_76_scheduled_suspension_is_not_realized_cash(self) -> None:
        row = next(row for row in self.mitigation_results if row["severity"] == "severe" and row["structure"] == "proposed")
        self.assertGreater(phase6.dec(row["distributions_formally_suspended_in_mitigated_case"]), phase6.dec(row["incremental_cash_preserved_by_mitigation"]))
        self.assertEqual(phase6.dec(row["distributions_unpaid_due_to_prior_cash_or_capacity_failure"]), Decimal("13"))

    def test_77_mitigation_cash_uses_actual_payments(self) -> None:
        for row in self.mitigation_results:
            self.assertEqual(
                phase6.dec(row["incremental_cash_preserved_by_mitigation"]),
                phase6.dec(row["distributions_actually_paid_unmitigated"])
                - phase6.dec(row["distributions_actually_paid_mitigated"]),
            )

    def test_78_mitigation_reconciliation_has_no_unexplained_residual(self) -> None:
        self.assertTrue(all(abs(phase6.dec(row["mitigation_reconciliation_difference"])) <= phase6.TOLERANCE for row in self.mitigation_results))

    def test_79_interest_savings_follow_actual_cash_preservation(self) -> None:
        self.assertTrue(all(phase6.dec(row["incremental_interest_saved"]) >= 0 for row in self.mitigation_results))
        self.assertTrue(all(row["other_timing_or_waterfall_explanation"] != "" for row in self.mitigation_results))

    def test_80_partial_and_full_distribution_outcomes_are_visible(self) -> None:
        self.assertTrue(any(phase6.dec(row["dividend_paid"]) > 0 and phase6.dec(row["dividend_unpaid"]) > 0 for row in self.monthly))
        mitigated = [row for row in self.monthly if row["scenario_id"] == "SEVERE_MITIGATED" and row["structure"] == "proposed" and row["month_end"] >= "2026-05-01"]
        self.assertTrue(all(phase6.dec(row["planned_repurchase_after_mitigation"]) == 0 for row in mitigated))

    def test_81_mandatory_failure_identifies_exact_obligation(self) -> None:
        row = self.result_index[("SEVERE_UNMITIGATED", "proposed")]
        self.assertEqual(row["first_mandatory_payment_failure_date"], "2027-07-31")
        self.assertEqual(row["failed_obligation_type"], "SCHEDULED_TERM_PRINCIPAL")
        self.assertEqual(
            phase6.dec(row["failed_obligation_amount_due"])
            - phase6.dec(row["failed_obligation_amount_paid"]),
            phase6.dec(row["failed_obligation_unpaid_amount"]),
        )

    def test_82_multiple_mandatory_failures_in_one_month_retain_priority(self) -> None:
        row = next(row for row in self.monthly if row["scenario_id"] == "SEVERE_UNMITIGATED" and row["structure"] == "proposed" and row["month_end"] == "2027-08-31")
        self.assertEqual(row["failed_mandatory_obligation_type"], "CASH_INTEREST")
        self.assertEqual(row["failed_mandatory_obligation_types"], "CASH_INTEREST;RETAINED_MANDATORY_OBLIGATION")

    def test_83_missed_distribution_is_not_mandatory_default(self) -> None:
        row = next(row for row in self.monthly if phase6.dec(row["dividend_unpaid"]) > 0 and row["mandatory_payment_failure_flag"] == "no")
        self.assertNotEqual(row["model_status"], "MANDATORY_PAYMENT_FAILURE")

    def test_84_cash_floor_and_commitment_exhaustion_do_not_imply_immediate_payment_failure(self) -> None:
        severe_existing = [row for row in self.monthly if row["scenario_id"] == "SEVERE_UNMITIGATED" and row["structure"] == "existing"]
        cash_floor = next(row for row in severe_existing if phase6.dec(row["cash_floor_shortfall"]) > 0)
        self.assertEqual(cash_floor["mandatory_payment_failure_flag"], "no")
        severe_proposed = [row for row in self.monthly if row["scenario_id"] == "SEVERE_UNMITIGATED" and row["structure"] == "proposed"]
        exhaustion = next(row for row in severe_proposed if row["commitment_exhaustion_flag"] == "yes")
        self.assertEqual(exhaustion["mandatory_payment_failure_flag"], "no")

    def test_85_maturity_shortfall_is_separate(self) -> None:
        maturity_events = [row for row in self.events if row["event_type"].endswith("MATURITY_SHORTFALL") and row["status"] == "MATURITY_SHORTFALL"]
        self.assertTrue(maturity_events)
        self.assertTrue(all(row["failed_obligation_type"] == "MATURITY_PRINCIPAL" for row in maturity_events))
        self.assertTrue(all(row["interim_failure_or_maturity_shortfall"] == "maturity_shortfall" for row in maturity_events))

    def test_86_payment_failure_month_counts_reconcile(self) -> None:
        for result in self.results:
            count = sum(1 for row in self.monthly if row["scenario_id"] == result["scenario_id"] and row["structure"] == result["structure"] and row["mandatory_payment_failure_flag"] == "yes")
            self.assertEqual(int(result["mandatory_payment_failure_months"]), count)

    def test_87_equal_timing_rows_cover_required_cases(self) -> None:
        self.assertEqual(len(self.timing), 16)
        self.assertEqual({row["timing_case"] for row in self.timing}, {"equal", "adverse"})

    def test_88_approved_adverse_timing_patterns(self) -> None:
        for row in self.timing:
            if row["timing_case"] == "adverse":
                expected = "20%_30%_50%" if row["scenario_family"] == "moderate" else "10%_25%_65%"
                self.assertEqual(row["timing_pattern"], expected)

    def test_89_equal_and_adverse_preserve_quarterly_totals(self) -> None:
        config = phase6.scenario_by_id("SEVERE_UNMITIGATED")
        adverse = phase6.run_case(config, "proposed")
        equal = phase6.run_case(phase6.replace(config, timing_convention="equal"), "proposed")
        for field in ("revenue", "lender_base_ebitda", "cfads_before_cash_interest"):
            adverse_totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
            equal_totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
            for row in adverse:
                adverse_totals[(row["fiscal_year"], row["quarter"])] += phase6.dec(row[field])
            for row in equal:
                equal_totals[(row["fiscal_year"], row["quarter"])] += phase6.dec(row[field])
            self.assertTrue(all(abs(value - equal_totals[key]) <= phase6.TOLERANCE for key, value in adverse_totals.items()))

    def test_90_timing_changes_only_intraquarter_allocation(self) -> None:
        config = phase6.scenario_by_id("MODERATE_UNMITIGATED")
        adverse_operating = phase6.build_operating(config)
        equal_operating = phase6.build_operating(phase6.replace(config, timing_convention="equal"))
        for adverse, equal in zip(adverse_operating, equal_operating, strict=True):
            for field in ("revenue", "lender_base_ebitda", "cfads_before_cash_interest"):
                self.assertEqual(adverse[field], equal[field])

    def test_91_timing_event_dates_recalculate_and_are_labeled(self) -> None:
        pair = [row for row in self.timing if row["scenario_id"] == "SEVERE_MITIGATED" and row["structure"] == "existing"]
        dates = {row["timing_case"]: row["first_50m_analytical_liquidity_warning"] for row in pair}
        self.assertNotEqual(dates["equal"], dates["adverse"])
        self.assertTrue(all(row["classification"] == "monthly_timing_sensitivity_not_observed_seasonality" for row in pair))

    def test_92_timing_case_ids_and_equal_differences(self) -> None:
        self.assertEqual(len({row["timing_sensitivity_id"] for row in self.timing}), len(self.timing))
        for row in self.timing:
            self.assertTrue(row["upstream_ids"])
            if row["timing_case"] == "equal":
                self.assertEqual(phase6.dec(row["minimum_liquidity_difference_from_equal"]), 0)
                self.assertEqual(row["event_date_comparison_from_equal"], "reference_equal_allocation")

    def test_93_owner_reviewed_mitigations_and_no_waiver_labels(self) -> None:
        credited = [row for row in self.mitigations if row["modeled_credit"] == "yes"]
        self.assertTrue(all(row["owner_review_status"] == "owner_reviewed_for_phase6_testing" for row in credited))
        no_waiver = [row for row in self.drawability if "NO_WAIVER" in row["scenario_id"] and row["structure"] == "proposed"]
        self.assertTrue(all("not_legal_conclusion" in row["classification"] for row in no_waiver))

    def test_94_first_distress_event_has_obligation_details(self) -> None:
        event = next(row for row in self.events if row["scenario_id"] == "SEVERE_UNMITIGATED" and row["structure"] == "proposed" and row["event_type"] == "FIRST_MANDATORY_PAYMENT_FAILURE")
        self.assertEqual(event["failed_obligation_type"], "SCHEDULED_TERM_PRINCIPAL")
        self.assertTrue(event["amount_due"] and event["amount_paid"] and event["unpaid_amount"])
        self.assertEqual(event["interim_failure_or_maturity_shortfall"], "interim_mandatory_payment_failure")

    def test_95_lower_debt_from_failure_is_not_presented_as_improvement(self) -> None:
        text = (ROOT / "docs" / "phase-6" / "LIQUIDITY_AND_REVERSE_STRESS.md").read_text(encoding="utf-8")
        self.assertIn(
            "A lower debt or maturity balance caused by curtailed borrowing, unpaid obligations, or liquidity failure is not improved credit performance.",
            text,
        )

    def test_96_interest_due_paid_and_arrears_are_separate(self) -> None:
        rows = phase6.run_case(phase6.scenario_by_id("SEVERE_NO_WAIVER"), "proposed")
        previous_arrears = Decimal("0")
        for row in rows:
            due = phase6.dec(row["cash_interest_due"])
            paid = phase6.dec(row["cash_interest_paid"])
            shortfall = phase6.dec(row["cash_interest_shortfall"])
            arrears = phase6.dec(row["cash_interest_arrears_balance"])
            self.assertLessEqual(abs(due - paid - shortfall), phase6.TOLERANCE)
            self.assertLessEqual(abs(arrears - previous_arrears - shortfall), phase6.TOLERANCE)
            previous_arrears = arrears
        self.assertGreater(previous_arrears, 0)

    def test_97_ebitda_coverage_uses_due_while_cash_waterfall_uses_paid(self) -> None:
        rows = phase6.run_case(phase6.scenario_by_id("SEVERE_NO_WAIVER"), "proposed")
        target_index = next(i for i, row in enumerate(rows) if row["month_end"] == "2028-01-31")
        target = rows[target_index]
        window = rows[target_index - 11:target_index + 1]
        ltm_due = sum((phase6.dec(row["cash_interest_due"]) for row in window), Decimal("0"))
        ltm_paid = sum((phase6.dec(row["cash_interest_paid"]) for row in window), Decimal("0"))
        self.assertEqual(phase6.dec(target["ltm_cash_interest_due_or_payable"]), ltm_due)
        self.assertEqual(phase6.dec(target["ltm_cash_interest_paid"]), ltm_paid)
        self.assertGreater(ltm_due, ltm_paid)
        self.assertLessEqual(abs(
            phase6.dec(target["ebitda_cash_interest_coverage"])
            - phase6.dec(target["ttm_lender_base_ebitda"]) / ltm_due
        ), phase6.TOLERANCE)
        self.assertLessEqual(abs(
            phase6.dec(target["cfads_cash_interest_coverage"])
            - sum((phase6.dec(row["cfads_before_cash_interest"]) for row in window), Decimal("0")) / ltm_paid
        ), phase6.TOLERANCE)

    def test_98_fully_paid_and_unavailable_ltm_interest_cases(self) -> None:
        rows = phase6.run_case(phase6.scenario_by_id("BASE"), "proposed")
        self.assertTrue(all(
            row["ltm_cash_interest_due_or_payable"] == ""
            and row["ltm_cash_interest_paid"] == ""
            and row["ebitda_cash_interest_coverage"] == ""
            for row in rows[:11]
        ))
        first_ltm = rows[11]
        self.assertEqual(
            first_ltm["ltm_cash_interest_due_or_payable"],
            first_ltm["ltm_cash_interest_paid"],
        )
        self.assertTrue(first_ltm["ebitda_cash_interest_coverage"])


if __name__ == "__main__":
    unittest.main()
