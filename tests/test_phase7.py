"""Decision-relevant tests for Phase 7 covenant mechanics and sizing."""

from __future__ import annotations

import csv
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import phase7  # noqa: E402


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class Phase7Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.candidates = read_csv(phase7.RAW / "STRUCTURE_CANDIDATES.csv")
        cls.proposals = read_csv(phase7.RAW / "COVENANT_PROPOSALS.csv")
        cls.owner = read_csv(phase7.RAW / "OWNER_REVIEW_DECISIONS.csv")
        cls.comparison = read_csv(phase7.PROCESSED / "STRUCTURE_COMPARISON.csv")
        cls.final = read_csv(phase7.PROCESSED / "FINAL_FINANCING_ASSUMPTIONS.csv")
        cls.matrix = read_csv(phase7.PROCESSED / "COVENANT_MATRIX.csv")
        cls.covenant_tests = read_csv(phase7.PROCESSED / "COVENANT_TEST_RESULTS.csv")
        cls.headroom = read_csv(phase7.PROCESSED / "COVENANT_HEADROOM.csv")
        cls.timeline = read_csv(phase7.PROCESSED / "BREACH_INTERVENTION_TIMELINE.csv")
        cls.sizing = read_csv(phase7.PROCESSED / "SIZING_RESULTS.csv")
        cls.distributions = read_csv(phase7.PROCESSED / "DISTRIBUTION_RESTRICTION_TESTS.csv")
        cls.common_horizon = read_csv(phase7.PROCESSED / "COMMON_HORIZON_COMPARISON.csv")
        cls.ultimate_maturity = read_csv(phase7.PROCESSED / "ULTIMATE_MATURITY_COMPARISON.csv")
        cls.sources_uses = read_csv(phase7.PROCESSED / "SOURCES_AND_USES_RECONCILIATION.csv")
        cls.covenant_summary = read_csv(phase7.PROCESSED / "COVENANT_SUMMARY.csv")
        cls.leverage_comparison = read_csv(phase7.PROCESSED / "LEVERAGE_COVENANT_COMPARISON.csv")
        cls.phase8 = read_csv(phase7.PROCESSED / "PHASE8_MODEL_INPUTS.csv")
        cls.validations = read_csv(phase7.PROCESSED / "VALIDATION_RESULTS.csv")
        cls.ledger = read_csv(phase7.DOCS / "SOURCE_LEDGER.csv")
        cls.candidate_index = {row["candidate_id"]: row for row in cls.candidates}
        cls.final_index = {row["assumption_name"]: row for row in cls.final}
        cls.sizing_index = {row["sizing_id"]: row for row in cls.sizing}

    def test_01_starting_checkpoint(self) -> None:
        row = read_csv(phase7.RAW / "STARTING_CHECKPOINT.csv")[0]
        self.assertEqual(row["repository"], "owencchapman24/quanex-credit-underwriting")
        self.assertEqual(row["branch"], "main")
        self.assertTrue(all(row[field] == phase7.APPROVED_PHASE6_COMMIT for field in (
            "local_head", "tracked_origin_main", "live_remote_main",
        )))
        self.assertEqual((row["ahead"], row["behind"]), ("0", "0"))

    def test_02_candidate_set(self) -> None:
        self.assertEqual(len(self.candidates), 11)
        self.assertIn("existing_retention", {row["alternative_type"] for row in self.candidates})
        self.assertIn("amend_extend", {row["alternative_type"] for row in self.candidates})

    def test_03_reference_structure_exact(self) -> None:
        row = self.candidate_index["STR-003"]
        self.assertEqual(phase7.dec(row["opening_term_principal"]), Decimal("650"))
        self.assertEqual(phase7.dec(row["opening_revolver"]), Decimal("29.89771875"))
        self.assertEqual(phase7.dec(row["revolver_commitment"]), Decimal("300"))
        self.assertEqual(phase7.dec(row["letters_of_credit"]), Decimal("6.2"))

    def test_04_amendment_remains_not_determinable(self) -> None:
        row = self.candidate_index["STR-002"]
        self.assertEqual(row["quantitative_status"], "qualitative_only")
        comparison = next(item for item in self.comparison if item["candidate_id"] == "STR-002")
        self.assertEqual(comparison["overall_path_status"], phase7.N_D)
        self.assertEqual(comparison["opening_term_principal"], "")

    def test_05_required_amortization_cases(self) -> None:
        values = {row["annual_amortization_percent"] for row in self.candidates}
        self.assertTrue({"5", "7.5", "10", "15"}.issubset(values))

    def test_06_lower_debt_has_real_source(self) -> None:
        selected = self.candidate_index["STR-008"]
        difference = Decimal("650") - phase7.dec(selected["opening_term_principal"])
        self.assertEqual(difference, phase7.dec(selected["required_non_debt_contribution"]))
        self.assertIn("may not consume", selected["limitations"])

    def test_07_selected_opening_leverage_boundary(self) -> None:
        row = next(item for item in self.comparison if item["candidate_id"] == "STR-008" and item["scenario_id"] == "BASE")
        self.assertLess(phase7.dec(row["opening_gross_funded_leverage"]), Decimal("3.25"))
        self.assertEqual(row["zero_cash_net_leverage"], row["opening_gross_funded_leverage"])

    def test_08_reference_phase6_base_parity(self) -> None:
        row = next(item for item in self.comparison if item["candidate_id"] == "STR-003" and item["scenario_id"] == "BASE")
        phase6 = next(item for item in read_csv(phase7.PHASE6_RESULTS) if item["structure"] == "proposed" and item["scenario_id"] == "BASE")
        self.assertLessEqual(abs(
            phase7.dec(row["all_in_minimum_usable_liquidity"])
            - phase7.dec(phase6["minimum_usable_liquidity"])
        ), phase7.TOLERANCE)
        for field in ("cumulative_cash_interest", "unsupported_maturity_gap"):
            self.assertLessEqual(abs(phase7.dec(row[field]) - phase7.dec(phase6[field])), phase7.TOLERANCE)

    def test_09_reference_phase6_scenario_parity(self) -> None:
        phase6_index = {(row["scenario_id"], row["structure"]): row for row in read_csv(phase7.PHASE6_RESULTS)}
        for row in self.comparison:
            if row["candidate_id"] != "STR-003":
                continue
            control = phase6_index[(row["scenario_id"], "proposed")]
            self.assertEqual(row["first_cash_floor_failure"], control["first_cash_floor_failure"])
            self.assertEqual(row["first_mandatory_payment_failure_date"], control["first_mandatory_payment_failure_date"])

    def test_10_severe_failures_not_weakened(self) -> None:
        row = next(item for item in self.comparison if item["candidate_id"] == "STR-008" and item["scenario_id"] == "SEVERE_UNMITIGATED")
        self.assertEqual(row["overall_path_status"], "MANDATORY_PAYMENT_FAILURE")
        self.assertTrue(row["first_cash_floor_failure"])
        self.assertTrue(row["revolver_capacity_exhaustion_date"])

    def test_11_three_frameworks_separate(self) -> None:
        frameworks = {row["framework"] for row in self.proposals}
        self.assertTrue({"existing_contractual", "proposed_contractual", "analyst_warning"}.issubset(frameworks))

    def test_12_existing_covenant_not_rewritten(self) -> None:
        row = next(item for item in self.proposals if item["proposal_id"] == "P7CP-001")
        self.assertEqual(row["threshold"], "3.25")
        self.assertIn("Net Leverage", row["metric_or_term"])
        self.assertEqual(row["evidence_status"], "partial_public_reconstruction")

    def test_13_proposed_leverage_is_gross_and_zero_cash(self) -> None:
        rows = [row for row in self.proposals if row["proposal_id"] in {"P7CP-002", "P7CP-003", "P7CP-004"}]
        self.assertTrue(all(row["cash_netting"] == "none" for row in rows))
        self.assertTrue(all("drawn revolver" in row["numerator"] or "Same as" in row["numerator"] for row in rows))

    def test_14_proposed_leverage_schedule(self) -> None:
        self.assertEqual([row["threshold"] for row in self.proposals if row["proposal_id"] in {"P7CP-002", "P7CP-003", "P7CP-004"}], ["3.50", "3.25", "3.00"])

    def test_15_coverage_covenant(self) -> None:
        row = next(item for item in self.proposals if item["proposal_id"] == "P7CP-005")
        self.assertEqual(row["threshold"], "3.00")
        self.assertIn("cash interest", row["denominator"])

    def test_16_liquidity_covenant(self) -> None:
        row = next(item for item in self.proposals if item["proposal_id"] == "P7CP-006")
        self.assertEqual(row["threshold"], "50")
        self.assertIn("outstanding LCs", row["numerator"])

    def test_17_cash_floor_is_separate(self) -> None:
        self.assertEqual(self.final_index["operating_cash_floor"]["value"], "25")
        self.assertEqual(self.final_index["minimum_usable_liquidity"]["value"], "50")
        self.assertIn("not covenant eligible cash", self.final_index["operating_cash_floor"]["definition_or_formula"])

    def test_18_warnings_more_conservative(self) -> None:
        for row in self.covenant_tests:
            self.assertLessEqual(phase7.dec(row["analyst_leverage_warning"]), phase7.dec(row["contractual_leverage_limit"]))
            self.assertGreater(phase7.dec(row["analyst_coverage_warning"]), phase7.dec(row["contractual_interest_coverage_minimum"]))
            self.assertGreater(phase7.dec(row["analyst_liquidity_warning"]), phase7.dec(row["contractual_minimum_liquidity"]))

    def test_19_leverage_headroom_formula(self) -> None:
        for row in self.headroom:
            if row["metric"] not in {"gross_funded_leverage", "analyst_leverage_warning"} or row["actual"] in {phase7.N_M, phase7.N_D_VALUE}:
                continue
            self.assertLessEqual(abs(
                phase7.dec(row["ratio_or_amount_headroom"])
                - (phase7.dec(row["threshold"]) - phase7.dec(row["actual"]))
            ), phase7.TOLERANCE)

    def test_20_debt_headroom_formula(self) -> None:
        for row in self.covenant_tests:
            if row["ttm_lender_base_ebitda"]:
                expected = phase7.dec(row["contractual_leverage_limit"]) * phase7.dec(row["ttm_lender_base_ebitda"]) - phase7.dec(row["gross_funded_debt"])
                self.assertLessEqual(abs(expected - phase7.dec(row["leverage_debt_headroom"])), phase7.TOLERANCE)

    def test_21_break_even_ebitda_formula(self) -> None:
        for row in self.covenant_tests:
            expected = phase7.dec(row["gross_funded_debt"]) / phase7.dec(row["contractual_leverage_limit"])
            self.assertLessEqual(abs(expected - phase7.dec(row["leverage_break_even_ebitda"])), phase7.TOLERANCE)

    def test_22_negative_zero_ebitda_handling(self) -> None:
        self.assertEqual(phase7.ratio(Decimal("10"), Decimal("0")), phase7.N_M)
        self.assertEqual(phase7.ratio(Decimal("10"), Decimal("-1")), phase7.N_M)

    def test_23_opening_coverage_not_determinable(self) -> None:
        rows = [row for row in self.covenant_tests if row["quarter"] == "closing_test"]
        self.assertTrue(rows)
        self.assertTrue(all(row["interest_coverage"] == phase7.N_D_VALUE for row in rows))
        self.assertTrue(all(row["coverage_status"] == phase7.N_D for row in rows))

    def test_24_book_cash_diagnostic_only(self) -> None:
        self.assertTrue(all(
            row["cash_eligibility_status"] == "pending_information_diagnostic_only"
            for row in self.comparison if row["scenario_id"] != "NOT_MODELED"
        ))
        self.assertEqual(self.final_index["contractual_cash_netting"]["value"], "0")

    def test_25_ecf_sweep_and_ordering(self) -> None:
        row = next(item for item in self.proposals if item["proposal_id"] == "P7CP-013")
        self.assertEqual(row["threshold"], "50")
        self.assertIn("after revolver repayment", row["definition"])
        self.assertIn("No deduction for dividends", row["exclusions"])

    def test_26_ecf_no_stepdown(self) -> None:
        row = next(item for item in self.proposals if item["proposal_id"] == "P7CP-013")
        self.assertIn("No step-down", row["stepups"])

    def test_27_distribution_narrow_and_broad_tests(self) -> None:
        names = {row["test_name"] for row in self.distributions}
        self.assertIn("debt_funded_share_repurchase", names)
        self.assertIn("share_repurchase_while_revolver_outstanding", names)

    def test_28_distribution_credit_not_taken(self) -> None:
        self.assertTrue(all(row["cash_flow_credit_taken_in_phase7"] == "0" for row in self.distributions))

    def test_29_base_revolver_repurchase_restriction_flags(self) -> None:
        rows = [row for row in self.distributions if row["scenario_id"] == "BASE" and "share_repurchase" in row["test_name"]]
        self.assertTrue(any(row["test_result"] == "FAIL_IN_PHASE6_CASH_PATH" for row in rows))

    def test_30_no_waiver_and_continued_paths(self) -> None:
        paths = {row["path_convention"] for row in self.timeline}
        self.assertIn("CONTINUED_DRAW_OR_WAIVER_SENSITIVITY", paths)
        self.assertIn("PHASE7_COVENANT_LINKED_NO_WAIVER", paths)
        self.assertIn("PHASE6_ANALYTICAL_SHUTOFF_SENSITIVITY", paths)

    def test_31_no_waiver_has_shutoff(self) -> None:
        rows = [row for row in self.timeline if row["path_convention"] == "PHASE7_COVENANT_LINKED_NO_WAIVER"]
        self.assertTrue(all(row["first_drawability_shutoff_date"] for row in rows))
        self.assertTrue(all(row["first_proposed_covenant_breach_date"] < row["first_drawability_shutoff_date"] for row in rows))

    def test_32_warning_precedes_breach(self) -> None:
        for row in self.timeline:
            if row["first_analyst_warning_date"] and row["first_proposed_covenant_breach_date"]:
                self.assertLessEqual(row["first_analyst_warning_date"], row["first_proposed_covenant_breach_date"])
                self.assertGreaterEqual(int(row["warning_lead_days_to_breach"]), 0)

    def test_33_maturity_shortfalls_preserved(self) -> None:
        self.assertTrue(all(phase7.dec(row["unsupported_maturity_gap"]) > 0 for row in self.comparison if row["unsupported_maturity_gap"]))

    def test_34_no_refinancing_assumed(self) -> None:
        handoff = (phase7.DOCS / "PHASE8_HANDOFF.md").read_text(encoding="utf-8")
        self.assertIn("do not assume refinancing", handoff)

    def test_35_reference_325_shortfall(self) -> None:
        row = self.sizing_index["P7SZ-001"]
        self.assertEqual(phase7.dec(row["headroom_or_shortfall"]), Decimal("-10.14871875"))
        self.assertEqual(row["status"], "FAIL_SHORTFALL")

    def test_36_selected_sizing_formula(self) -> None:
        row = self.sizing_index["P7SZ-004"]
        self.assertEqual(phase7.dec(row["analytical_term_capacity"]), Decimal("639.85128125"))
        self.assertEqual(phase7.dec(row["required_non_debt_contribution"]), Decimal("10.14871875"))
        self.assertEqual(phase7.dec(row["resulting_leverage"]), Decimal("3.25"))

    def test_37_capped_cash_sizing_is_diagnostic(self) -> None:
        row = self.sizing_index["P7SZ-003"]
        self.assertEqual(row["status"], "DIAGNOSTIC_ONLY")
        self.assertEqual(phase7.dec(row["headroom_or_shortfall"]), Decimal("14.85128125"))

    def test_38_selected_structure_has_covenant_headroom(self) -> None:
        row = self.sizing_index["P7SZ-007"]
        self.assertEqual(phase7.dec(row["initial_term_funding"]), Decimal("635"))
        self.assertEqual(phase7.dec(row["required_non_debt_contribution"]), Decimal("15"))
        self.assertGreater(phase7.dec(row["headroom_or_shortfall"]), Decimal("4.8"))

    def test_39_all_judgments_are_owner_reviewed(self) -> None:
        for collection in (self.proposals, self.owner, self.final, self.sizing, self.distributions):
            self.assertTrue(all(row["owner_review_status"] == phase7.REVIEW for row in collection))
        self.assertEqual(len(self.owner), 21)
        self.assertTrue(all(row["human_review_status"] == "owner_reviewed" for row in self.owner))
        self.assertTrue(all(row["review_note"] == phase7.OWNER_REVIEW_NOTE for row in self.owner))

    def test_40_no_approved_or_lender_committed_phase7_terms(self) -> None:
        text = "\n".join((phase7.DOCS / name).read_text(encoding="utf-8") for name in (
            "METHODOLOGY.md", "COVENANT_DESIGN.md", "SIZING_RATIONALE.md",
            "FINAL_PROPOSED_TERM_SHEET.md", "PHASE8_HANDOFF.md",
        ))
        self.assertIn("not a lender quote", text)
        self.assertNotIn("owner_approved", text)

    def test_41_final_conditions_retained(self) -> None:
        row = self.final_index["required_conditions"]
        self.assertEqual(row["value"], "CP-001:CP-024")

    def test_42_phase8_handoff_complete(self) -> None:
        self.assertEqual(len(self.phase8), len(self.final))
        self.assertTrue(all(row["phase8_model_location"] for row in self.phase8))
        self.assertTrue(all(row["upstream_ids"].startswith("P7FA-") for row in self.phase8))

    def test_43_missing_values_not_zero(self) -> None:
        amendment = next(row for row in self.comparison if row["candidate_id"] == "STR-002")
        self.assertEqual(amendment["opening_term_principal"], "")
        self.assertEqual(amendment["overall_path_status"], phase7.N_D)

    def test_44_source_ids_valid(self) -> None:
        manifest = phase7.source_manifest()
        for row in self.ledger:
            for source_id in row["source_ids"].split(";"):
                if source_id:
                    self.assertIn(source_id, manifest)

    def test_45_cutoff_compliance(self) -> None:
        self.assertTrue(all(row["cutoff_status"] == "within_cutoff" for row in self.ledger))
        self.assertEqual({sid for row in self.ledger for sid in row["source_ids"].split(";") if sid}, {"SRC-001", "SRC-002", "SRC-003"})

    def test_46_validation_controls_pass(self) -> None:
        self.assertGreaterEqual(len(self.validations), 45)
        self.assertTrue(all(row["status"] == "PASS" for row in self.validations))

    def test_47_prior_phase_artifacts_unchanged(self) -> None:
        self.assertEqual(phase7.prior_analytical_artifact_changes(), [])

    def test_48_changed_paths_are_phase7_scoped(self) -> None:
        phase7.validate_changed_paths()
        phase7.phase6.validate_changed_paths()

    def test_49_deterministic_regeneration(self) -> None:
        before = phase7.fingerprints()
        phase7.build()
        after = phase7.fingerprints()
        self.assertEqual(before, after)

    def test_50_phase8_not_started(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", phase7.APPROVED_PHASE7_COMMIT],
            cwd=ROOT, text=True, capture_output=True, check=True,
        ).stdout.splitlines()
        self.assertFalse(any(path == "scripts/phase8.py" or path.startswith(("data/phase8/", "docs/phase-8/")) for path in tracked))

    def test_51_no_excel_workbook(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", phase7.APPROVED_PHASE7_COMMIT],
            cwd=ROOT, text=True, capture_output=True, check=True,
        ).stdout.splitlines()
        self.assertFalse(any(path.lower().endswith(".xlsx") for path in tracked))

    def test_52_validate_entry_point(self) -> None:
        self.assertEqual(phase7.validate()["status"], "PASS")

    def test_53_warning_boundary_below(self) -> None:
        result = phase7.maximum_measure_status(
            Decimal("3.249999"), Decimal("3.25"), Decimal("3.50"),
        )
        self.assertEqual(result, "compliant")

    def test_54_warning_boundary_equal(self) -> None:
        result = phase7.maximum_measure_status(
            Decimal("3.25"), Decimal("3.25"), Decimal("3.50"),
        )
        self.assertEqual(result, "warning")

    def test_55_warning_boundary_above(self) -> None:
        result = phase7.maximum_measure_status(
            Decimal("3.250001"), Decimal("3.25"), Decimal("3.50"),
        )
        self.assertEqual(result, "warning")

    def test_56_covenant_boundary_equal(self) -> None:
        result = phase7.maximum_measure_status(
            Decimal("3.50"), Decimal("3.25"), Decimal("3.50"),
        )
        self.assertEqual(result, "warning")

    def test_57_covenant_boundary_above(self) -> None:
        result = phase7.maximum_measure_status(
            Decimal("3.500001"), Decimal("3.25"), Decimal("3.50"),
        )
        self.assertEqual(result, "breached")

    def test_58_missing_zero_negative_denominators_are_distinct(self) -> None:
        self.assertEqual(phase7.coverage_ratio(Decimal("10"), None), phase7.N_D_VALUE)
        self.assertEqual(phase7.coverage_ratio(Decimal("10"), Decimal("0")), phase7.N_M)
        self.assertEqual(phase7.coverage_ratio(Decimal("10"), Decimal("-1")), phase7.N_M)

    def test_59_selected_term_commitment_has_no_unused_term(self) -> None:
        selected = self.candidate_index["STR-008"]
        self.assertEqual(selected["term_commitment"], selected["opening_term_principal"])
        self.assertEqual(selected["undrawn_term_commitment"], "0")
        self.assertIn("no delayed-draw", selected["unused_term_commitment_treatment"])

    def test_60_total_debt_capacity_is_not_term_capacity(self) -> None:
        total = phase7.dec(self.final_index["analytical_total_funded_debt_capacity"]["value"])
        bank = phase7.dec(self.final_index["analytical_bank_debt_capacity"]["value"])
        term = phase7.dec(self.final_index["analytical_term_capacity_at_reference_revolver"]["value"])
        retained = phase7.phase5_value("P5A-032")
        revolver = phase7.phase5_value("P5A-026")
        self.assertEqual(total - retained, bank)
        self.assertEqual(bank - revolver, term)

    def test_61_term_revolver_reallocation_preserves_total_debt(self) -> None:
        exact = self.candidate_index["STR-009"]
        reallocated = self.candidate_index["STR-011"]
        exact_bank = phase7.dec(exact["opening_term_principal"]) + phase7.dec(exact["opening_revolver"])
        reallocated_bank = phase7.dec(reallocated["opening_term_principal"]) + phase7.dec(reallocated["opening_revolver"])
        self.assertEqual(exact_bank, reallocated_bank)
        self.assertNotEqual(exact["opening_term_principal"], reallocated["opening_term_principal"])

    def test_62_all_proposed_sources_equal_uses(self) -> None:
        proposed = [row for row in self.sources_uses if row["initial_term_funding"]]
        self.assertTrue(proposed)
        self.assertTrue(all(abs(phase7.dec(row["sources_less_uses"])) <= phase7.TOLERANCE for row in proposed))

    def test_63_rounded_640_exception_is_visible(self) -> None:
        row = self.sizing_index["P7SZ-005"]
        self.assertEqual(row["status"], "MARGINAL_SIZING_EXCEPTION")
        self.assertLess(phase7.dec(row["headroom_or_shortfall"]), Decimal("0"))

    def test_64_common_horizon_is_uniform(self) -> None:
        self.assertTrue(all(row["period_end"] == "2029-07-31" for row in self.common_horizon))
        comparable = [row for row in self.common_horizon if row["comparison_status"] == "common_horizon_comparable"]
        self.assertTrue(comparable)
        self.assertTrue(all(row["unpaid_mandatory_obligations"] != "" for row in comparable))

    def test_65_ultimate_maturity_is_separate(self) -> None:
        quantitative = [row for row in self.ultimate_maturity if row["comparison_status"] != phase7.N_D]
        self.assertGreater(len({row["maturity_date"] for row in quantitative}), 1)
        self.assertTrue(all(row["comparison_status"] == "different_contractual_horizon_not_directly_comparable" for row in quantitative))

    def test_66_complete_quarterly_covenant_fields(self) -> None:
        required = {
            "ttm_lender_base_ebitda", "gross_funded_debt", "gross_funded_leverage",
            "contractual_leverage_limit", "analyst_leverage_warning",
            "leverage_ratio_headroom", "leverage_debt_headroom",
            "leverage_break_even_ebitda", "ltm_cash_interest", "interest_coverage",
            "contractual_interest_coverage_minimum", "analyst_coverage_warning",
            "usable_liquidity", "contractual_minimum_liquidity",
            "analyst_liquidity_warning", "operating_cash", "operating_cash_floor",
            "overall_warning_status", "overall_covenant_status", "drawability_status",
            "input_completeness_status",
        }
        self.assertTrue(required.issubset(self.covenant_tests[0]))
        quarterly = [row for row in self.covenant_tests if row["quarter"] != "closing_test"]
        self.assertTrue(quarterly)
        self.assertTrue(all(row["gross_funded_debt"] and row["usable_liquidity"] for row in quarterly))

    def test_67_covenant_summary_covers_every_path(self) -> None:
        test_paths = {row["scenario_id"] for row in self.covenant_tests}
        summary_paths = {row["scenario_id"] for row in self.covenant_summary}
        self.assertEqual(test_paths, summary_paths)

    def test_68_warning_does_not_terminate_draws(self) -> None:
        for row in self.timeline:
            if row["path_convention"] != "PHASE7_COVENANT_LINKED_NO_WAIVER":
                continue
            self.assertTrue(row["first_proposed_covenant_breach_date"])
            self.assertGreater(row["first_drawability_shutoff_date"], row["first_proposed_covenant_breach_date"])

    def test_69_inherited_phase6_shutoff_is_explicit_sensitivity(self) -> None:
        inherited = [row for row in self.timeline if row["path_convention"] == "PHASE6_ANALYTICAL_SHUTOFF_SENSITIVITY"]
        self.assertTrue(inherited)
        self.assertTrue(all("not a Phase 7 legal default" in row["no_waiver_treatment"] for row in inherited))

    def test_70_continued_draw_requires_consent(self) -> None:
        continued = [row for row in self.timeline if row["path_convention"] == "CONTINUED_DRAW_OR_WAIVER_SENSITIVITY"]
        self.assertTrue(continued)
        self.assertTrue(all("consent" in row["continued_drawability_treatment"] for row in continued))

    def test_71_lower_debt_from_shutoff_not_characterized_as_favorable(self) -> None:
        text = (phase7.DOCS / "FINAL_PROPOSED_TERM_SHEET.md").read_text(encoding="utf-8")
        self.assertIn("not favorable performance", text)

    def test_72_initial_covenant_comparison_complete(self) -> None:
        self.assertEqual(
            {row["covenant_case"] for row in self.leverage_comparison},
            {"proposed_3.50x_initial", "alternative_3.25x_initial"},
        )
        self.assertEqual({row["scenario_family"] for row in self.leverage_comparison}, {"moderate", "severe"})

    def test_73_selected_structure_below_warning(self) -> None:
        source_use = next(row for row in self.sources_uses if row["candidate_id"] == "STR-008")
        self.assertLess(phase7.dec(source_use["closing_gross_leverage"]), Decimal("3.25"))
        self.assertEqual(source_use["warning_status"], "compliant")

    def test_74_exact_capacity_activates_warning_not_breach(self) -> None:
        source_use = next(row for row in self.sources_uses if row["candidate_id"] == "STR-009")
        self.assertEqual(phase7.dec(source_use["closing_gross_leverage"]), Decimal("3.25"))
        self.assertEqual(source_use["warning_status"], "warning")
        self.assertEqual(source_use["covenant_status"], "compliant")

    def test_75_common_and_ultimate_outputs_keep_alternatives(self) -> None:
        common_ids = {row["candidate_id"] for row in self.common_horizon}
        maturity_ids = {row["candidate_id"] for row in self.ultimate_maturity}
        self.assertTrue({"STR-001", "STR-002"}.issubset(common_ids))
        self.assertTrue({"STR-001", "STR-002"}.issubset(maturity_ids))

    def test_76_covenant_linked_shutoff_has_no_circular_liquidity_trigger(self) -> None:
        for timeline in self.timeline:
            if timeline["path_convention"] != "PHASE7_COVENANT_LINKED_NO_WAIVER":
                continue
            breach = next(
                row for row in self.covenant_tests
                if row["scenario_id"] == timeline["scenario_id"]
                and row["period_end"] == timeline["first_proposed_covenant_breach_date"]
            )
            self.assertEqual(breach["leverage_status"], "breached")
            self.assertNotEqual(breach["liquidity_status"], "breached")
            self.assertGreater(timeline["first_drawability_shutoff_date"], breach["period_end"])

    def test_77_curtailed_draw_path_is_not_better_performance(self) -> None:
        continued = next(
            row for row in self.comparison
            if row["candidate_id"] == "STR-008" and row["scenario_id"] == "SEVERE_UNMITIGATED"
        )
        shutoff = next(
            row for row in self.comparison
            if row["candidate_id"] == "STR-008"
            and row["scenario_id"] == "SEVERE_PHASE7_COVENANT_NO_WAIVER"
        )
        self.assertLess(
            phase7.dec(shutoff["unsupported_maturity_gap"]),
            phase7.dec(continued["unsupported_maturity_gap"]),
        )
        self.assertLess(
            shutoff["first_mandatory_payment_failure_date"],
            continued["first_mandatory_payment_failure_date"],
        )
        self.assertIn("not improved performance", shutoff["limitations"])

    def test_78_all_in_liquidity_is_lower_of_opening_and_subsequent(self) -> None:
        for collection in (self.comparison, self.common_horizon, self.sizing, self.covenant_summary):
            for row in collection:
                if not row.get("opening_usable_liquidity"):
                    continue
                self.assertEqual(
                    phase7.dec(row["all_in_minimum_usable_liquidity"]),
                    min(
                        phase7.dec(row["opening_usable_liquidity"]),
                        phase7.dec(row["subsequent_minimum_usable_liquidity"]),
                    ),
                )

    def test_79_opening_position_label_when_opening_is_minimum(self) -> None:
        for candidate_id in ("STR-001", "STR-008"):
            row = next(
                item for item in self.common_horizon
                if item["candidate_id"] == candidate_id
            )
            self.assertEqual(row["all_in_minimum_liquidity_date"], "OPENING_POSITION")
            self.assertEqual(row["all_in_minimum_usable_liquidity"], row["opening_usable_liquidity"])

    def test_80_reference_later_minimum_and_phase5_reconciliation(self) -> None:
        row = next(item for item in self.common_horizon if item["candidate_id"] == "STR-003")
        phase5_row = next(
            item for item in read_csv(phase7.PHASE5_COMMON_HORIZON)
            if item["metric_name"] == "minimum_usable_liquidity"
        )
        self.assertEqual(row["all_in_minimum_liquidity_date"], row["subsequent_minimum_liquidity_date"])
        self.assertNotEqual(row["all_in_minimum_liquidity_date"], "OPENING_POSITION")
        self.assertLessEqual(abs(
            phase7.dec(row["all_in_minimum_usable_liquidity"])
            - phase7.dec(phase5_row["proposed_value"])
        ), phase7.TOLERANCE)

    def test_81_expected_base_liquidity_presentation(self) -> None:
        existing = next(item for item in self.common_horizon if item["candidate_id"] == "STR-001")
        selected = next(item for item in self.common_horizon if item["candidate_id"] == "STR-008")
        self.assertLessEqual(abs(phase7.dec(existing["opening_usable_liquidity"]) - Decimal("261.40228125")), phase7.TOLERANCE)
        self.assertLessEqual(abs(phase7.dec(existing["subsequent_minimum_usable_liquidity"]) - Decimal("267.813895")), phase7.TOLERANCE)
        self.assertLessEqual(abs(phase7.dec(selected["opening_usable_liquidity"]) - Decimal("263.90228125")), phase7.TOLERANCE)
        self.assertLessEqual(abs(phase7.dec(selected["subsequent_minimum_usable_liquidity"]) - Decimal("270.341345")), phase7.TOLERANCE)

    def test_82_no_ambiguous_minimum_liquidity_field(self) -> None:
        for collection in (self.comparison, self.common_horizon, self.sizing, self.covenant_summary):
            self.assertNotIn("minimum_usable_liquidity", collection[0])
        text = "\n".join(
            (phase7.DOCS / name).read_text(encoding="utf-8")
            for name in ("COVENANT_DESIGN.md", "SIZING_RATIONALE.md", "PHASE8_HANDOFF.md")
        )
        self.assertNotIn("| Minimum liquidity |", text)

    def test_83_phase8_inputs_include_corrected_liquidity_fields(self) -> None:
        phase8_index = {row["input_name"]: row for row in self.phase8}
        for name in (
            "opening_usable_liquidity", "subsequent_minimum_usable_liquidity",
            "subsequent_minimum_liquidity_date", "all_in_minimum_usable_liquidity",
            "all_in_minimum_liquidity_date",
        ):
            self.assertIn(name, phase8_index)
        self.assertEqual(phase8_index["all_in_minimum_liquidity_date"]["value"], "OPENING_POSITION")

    def test_84_no_unreviewed_owner_decision_remains(self) -> None:
        stale_status = "pending_owner_" + "decision"
        for path in phase7.generated_files():
            self.assertNotIn(stale_status, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
