"""Decision-relevant controls for Phase 4 debt and closing mechanics."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import phase1  # noqa: E402
import phase2  # noqa: E402
import phase3  # noqa: E402
import phase4  # noqa: E402


class Phase4ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.checkpoint = phase4.read_csv(phase4.RAW / "STARTING_CHECKPOINT.csv")[0]
        cls.inputs = phase4.read_csv(phase4.RAW / "CLOSING_CASE_INPUTS.csv")
        cls.terms = phase4.read_csv(phase4.RAW / "PROPOSED_TERM_INPUTS.csv")
        cls.instruments = phase4.read_csv(phase4.PROCESSED / "DEBT_INSTRUMENT_REGISTER.csv")
        cls.legal = phase4.read_csv(phase4.PROCESSED / "LEGAL_STRUCTURE_REGISTER.csv")
        cls.bridges = phase4.read_csv(phase4.PROCESSED / "CLOSING_BRIDGE.csv")
        cls.sources_uses = phase4.read_csv(phase4.PROCESSED / "SOURCES_AND_USES.csv")
        cls.schedule = phase4.read_csv(phase4.PROCESSED / "DEBT_SCHEDULE.csv")
        cls.maturities = phase4.read_csv(phase4.PROCESSED / "MATURITY_SCHEDULE.csv")
        cls.comparison = phase4.read_csv(phase4.PROCESSED / "FINANCING_COMPARISON.csv")
        cls.economics = phase4.read_csv(phase4.PROCESSED / "REFINANCING_ECONOMICS.csv")
        cls.conditions = phase4.read_csv(phase4.PROCESSED / "CONDITIONS_PRECEDENT.csv")
        cls.phase5 = phase4.read_csv(phase4.PROCESSED / "PHASE5_OPENING_INPUTS.csv")
        cls.ledger = phase4.read_csv(phase4.DOCS / "SOURCE_LEDGER.csv")
        cls.results = phase4.calculate_closing_cases(cls.inputs)

    def test_01_starting_checkpoint(self) -> None:
        self.assertEqual(self.checkpoint["repository"], "owencchapman24/quanex-credit-underwriting")
        self.assertEqual(self.checkpoint["branch"], "main")
        for field in ("local_head", "tracked_origin_main", "live_remote_main"):
            self.assertEqual(self.checkpoint[field], phase4.APPROVED_PHASE3_COMMIT)
        self.assertEqual((self.checkpoint["ahead"], self.checkpoint["behind"]), ("0", "0"))
        self.assertEqual(self.checkpoint["working_tree_clean_before_work"], "yes")

    def test_02_existing_bank_principal(self) -> None:
        by_id = {row["instrument_id"]: row for row in self.instruments}
        total = Decimal(by_id["EX-TERM-A"]["principal_balance"]) + Decimal(by_id["EX-REVOLVER"]["principal_balance"])
        self.assertEqual(total, Decimal("641.25"))

    def test_03_existing_revolver_commitment_bridge(self) -> None:
        rev = next(row for row in self.instruments if row["instrument_id"] == "EX-REVOLVER")
        self.assertEqual(Decimal(rev["commitment"]), Decimal("475"))
        self.assertEqual(Decimal(rev["drawn_amount"]) + Decimal(rev["letters_of_credit"]) + Decimal(rev["undrawn_availability"]), Decimal("475"))

    def test_04_reported_availability(self) -> None:
        rev = next(row for row in self.instruments if row["instrument_id"] == "EX-REVOLVER")
        self.assertEqual(Decimal(rev["undrawn_availability"]), Decimal("296.3"))

    def test_05_letters_of_credit_counted_once(self) -> None:
        for case in self.inputs:
            result = self.results[case["case_id"]]
            self.assertFalse(Decimal(result["lc_replacement"]) > 0 and Decimal(result["lc_cash_collateral"]) > 0)
        lc = next(row for row in self.instruments if row["instrument_id"] == "EX-LC")
        self.assertEqual((lc["principal_balance"], lc["letters_of_credit"]), ("0", "6.2"))
        pressure = self.results["CC-HIGH"]
        self.assertEqual((pressure["lc_replacement"], pressure["lc_cash_collateral"]),
                         (Decimal("0"), Decimal("6.2")))

    def test_06_principal_and_carrying_value_separate(self) -> None:
        term = next(row for row in self.instruments if row["instrument_id"] == "EX-TERM-A")
        fees = next(row for row in self.instruments if row["instrument_id"] == "EX-DEFERRED-FEES")
        self.assertEqual(term["carrying_value"], "not_determinable_by_instrument")
        self.assertEqual(Decimal(fees["principal_balance"]), 0)
        self.assertEqual(Decimal(fees["carrying_value"]), Decimal("-11.04"))

    def test_07_refinanced_and_retained_debt_not_duplicated(self) -> None:
        use_names = {row["item"] for row in self.sources_uses if row["category"] == "use"}
        self.assertNotIn("Retained finance leases and other debt", use_names)
        self.assertNotIn("Retained operating lease liabilities", use_names)
        retained = {row["instrument_id"] for row in self.instruments if row["lifecycle"] == "retained_post_close"}
        self.assertEqual(retained, {"EX-FIN-LEASE", "EX-OTHER-DEBT", "EX-OPERATING-LEASE"})

    def test_08_january_amortization_timing_explicit(self) -> None:
        self.assertEqual({row["amortization_timing"] for row in self.inputs}, {
            "before_closing", "at_closing_embedded_in_payoff", "after_closing_cancelled_by_payoff"
        })
        ref = next(row for row in self.inputs if row["case_id"] == "CC-REF")
        self.assertEqual(ref["at_closing_scheduled_amortization_component"], "6.25")
        self.assertEqual(self.results["CC-REF"]["term_payoff"], Decimal("468.75"))

    def test_09_every_case_starts_from_october_balances(self) -> None:
        for row in self.inputs:
            self.assertEqual((row["opening_term_principal"], row["opening_revolver_borrowings"]), ("468.75", "172.5"))

    def test_10_sources_uses_reconcile_or_gap(self) -> None:
        for cid in ("CC-LOW", "CC-REF", "CC-HIGH"):
            rows = [row for row in self.sources_uses if row["case_id"] == cid]
            uses = sum((Decimal(row["amount"]) for row in rows if row["category"] == "use"), Decimal(0))
            sources = sum((Decimal(row["amount"]) for row in rows if row["category"] == "source"), Decimal(0))
            gap = next(Decimal(row["amount"]) for row in rows if row["category"] == "gap")
            self.assertEqual(sources + gap, uses)
            self.assertEqual(next(Decimal(row["amount"]) for row in rows if row["category"] == "control"), 0)

    def test_11_no_unexplained_funding_plug(self) -> None:
        self.assertFalse(any(row["item"].lower() == "plug" for row in self.sources_uses))
        revolver = [row for row in self.sources_uses if row["item"] == "Opening new-revolver draw"]
        self.assertTrue(all("Residual supported use" in row["calculation"] for row in revolver))
        self.assertTrue(all("not an unexplained plug" in row["notes"] for row in revolver))

    def test_12_new_term_cap(self) -> None:
        self.assertTrue(all(Decimal(result["term_funding"]) <= Decimal("650") for result in self.results.values()))

    def test_13_new_revolver_cap_including_lcs(self) -> None:
        for result in self.results.values():
            self.assertLessEqual(Decimal(result["new_revolver"]) + Decimal(result["lc_replacement"]), Decimal("300"))

    def test_14_cash_contribution_limited_to_accessible_cash(self) -> None:
        for row in self.inputs:
            self.assertLessEqual(Decimal(row["borrower_cash_contribution"]), Decimal(row["identified_accessible_cash"]))
            self.assertEqual(row["identified_accessible_cash"], "0")

    def test_15_minimum_cash_not_accessible_funding(self) -> None:
        self.assertFalse(any(row["item"] == "Minimum operating cash" for row in self.sources_uses))
        cash = next(row for row in self.phase5 if row["input_name"] == "accessible_cash_determination")
        self.assertEqual(cash["reference_case_value"], "")
        self.assertEqual(cash["input_status"], "pending_information")

    def test_16_closing_costs_remain_separate(self) -> None:
        required = {"Accrued interest", "Hedge and interest-period break cost", "Financing fees", "Legal, advisory and administrative expenses"}
        for cid in ("CC-LOW", "CC-REF", "CC-HIGH"):
            self.assertTrue(required.issubset({row["item"] for row in self.sources_uses if row["case_id"] == cid}))

    def test_17_principal_schedule_quarterly_rates(self) -> None:
        expected = {"AMORT-5": Decimal("1.25"), "AMORT-10": Decimal("2.5"), "AMORT-15": Decimal("3.75")}
        for row in self.schedule:
            if row["structure"] != "proposed":
                continue
            self.assertEqual(Decimal(row["quarterly_amortization_percent"]), expected[row["amortization_case"]])
        existing = [row for row in self.schedule if row["structure"] == "existing"]
        self.assertTrue(all(Decimal(row["quarterly_amortization_percent"]) == Decimal("1.25") for row in existing))

    def test_18_maturity_balloons_reconcile(self) -> None:
        groups: dict[tuple[str, str], list[dict[str, str]]] = {}
        for row in self.schedule:
            if row["structure"] == "proposed":
                groups.setdefault((row["case_id"], row["amortization_case"]), []).append(row)
        self.assertEqual(len(groups), 9)
        for rows in groups.values():
            self.assertEqual(len(rows), 20)
            original = Decimal(rows[0]["original_principal"])
            self.assertEqual(sum((Decimal(row["total_principal_due"]) for row in rows), Decimal(0)), original)
            self.assertEqual(Decimal(max(rows, key=lambda row: int(row["installment_number"]))["ending_principal"]), 0)
        existing = [row for row in self.schedule if row["structure"] == "existing"]
        self.assertEqual(len(existing), 16)
        self.assertEqual(sum((Decimal(row["total_principal_due"]) for row in existing), Decimal(0)), Decimal("468.75"))

    def test_19_retained_leases_and_other_debt_remain(self) -> None:
        by_id = {row["instrument_id"]: row for row in self.instruments}
        self.assertEqual(Decimal(by_id["EX-FIN-LEASE"]["principal_balance"]) + Decimal(by_id["EX-OTHER-DEBT"]["principal_balance"]), Decimal("62.619"))
        self.assertEqual(Decimal(by_id["EX-OPERATING-LEASE"]["carrying_value"]), Decimal("160.905"))

    def test_20_actual_maturity_dates(self) -> None:
        for iid in ("EX-TERM-A", "EX-REVOLVER"):
            self.assertEqual(next(row for row in self.instruments if row["instrument_id"] == iid)["maturity"], "2029-08-01")
        for iid in ("NEW-TERM", "NEW-REV"):
            self.assertEqual(next(row for row in self.instruments if row["instrument_id"] == iid)["maturity"], "2031-01-31")

    def test_21_proposed_pricing_is_hypothetical(self) -> None:
        pricing = next(row for row in self.terms if row["term_name"] == "term_and_drawn_revolver_margin")
        self.assertEqual(pricing["source_or_hypothetical_status"], "hypothetical_owner_reviewed_for_phase5_testing")
        self.assertIn("no spread is a lender quote", pricing["notes"])
        self.assertTrue(all("No spread is a lender quote" in row["notes"] for row in self.economics if row["analysis_type"] == "spread_and_upfront_fee_break_even"))

    def test_22_proposed_covenants_are_not_existing_terms(self) -> None:
        covenants = [row for row in self.terms if row["category"] == "covenants"]
        self.assertEqual(len(covenants), 3)
        self.assertTrue(all(row["source_or_hypothetical_status"] == "hypothetical_initial_analytical_test_threshold" for row in covenants))

    def test_23_public_legal_evidence_and_confirmation_are_distinct(self) -> None:
        for row in self.legal:
            self.assertTrue(row["exact_contractual_or_reported_language"])
            self.assertTrue(row["analyst_interpretation"])
            self.assertTrue(row["unresolved_private_diligence"])

    def test_24_non_guarantor_and_foreign_assets_not_assumed_accessible(self) -> None:
        combined = " ".join(" ".join(row.values()) for row in self.legal).lower()
        self.assertIn("structurally", combined)
        self.assertIn("not automatically available", combined)
        self.assertIn("foreign", combined)

    def test_25_every_proposed_term_has_owner_review(self) -> None:
        by_name = {row["term_name"]: row for row in self.terms}
        self.assertTrue(all(by_name[name]["owner_review_status"] == phase4.OWNER_PHASE5
                            for name in phase4.PHASE5_TERM_NAMES))
        self.assertTrue(all(by_name[name]["owner_review_status"] == phase4.OWNER_THRESHOLD
                            for name in phase4.THRESHOLD_TERM_NAMES))

    def test_26_every_condition_has_consequence(self) -> None:
        self.assertTrue(all(row["consequence_if_unmet"] for row in self.conditions))
        self.assertTrue(all(row["owner_review_status"] == phase4.OWNER_METHODOLOGY for row in self.conditions))
        self.assertEqual(len(self.conditions), 24)
        self.assertEqual(sum("essential" in row["public_or_hypothetical_status"] for row in self.conditions), 20)

    def test_27_existing_proposed_comparison_is_complete(self) -> None:
        names = {row["item"] for row in self.comparison}
        for item in ("Opening undrawn availability", "Annual scheduled term amortization", "Final maturity",
                     "Upfront and transaction costs", "Post-installment term balloon",
                     "Total funded principal due on maturity date",
                     "Total funded principal payments in final 12 months to maturity"):
            self.assertIn(item, names)

    def test_28_phase2_ebitda_unchanged(self) -> None:
        self.assertEqual(phase4.phase2_lender_base_ebitda(), Decimal("225.344"))

    def test_29_phase3_methodology_unchanged(self) -> None:
        self.assertEqual(phase4.prior_phase_changes(), ["scripts/phase3.py"])
        result = phase4.subprocess.run(
            ["git", "diff", "--name-only", phase4.APPROVED_PHASE3_COMMIT, "--", "docs/phase-3/METHODOLOGY.md"],
            cwd=ROOT, text=True, capture_output=True, check=True,
        )
        self.assertEqual(result.stdout.strip(), "")

    def test_30_cutoff_compliance(self) -> None:
        catalog = phase4.source_catalog()
        for row in self.ledger:
            for sid in filter(None, row["source_ids"].split(";")):
                self.assertIn(sid, catalog)
                self.assertLessEqual(datetime.strptime(catalog[sid]["publication"], "%Y-%m-%d").date(), phase4.CUTOFF)

    def test_31_deterministic_regeneration(self) -> None:
        before = phase4.fingerprints()
        phase4.build()
        self.assertEqual(before, phase4.fingerprints())

    def test_32_prior_phase_python_validations_pass(self) -> None:
        self.assertEqual(phase1.validate_all()["manual_overrides"], 0)
        self.assertEqual(phase2.validate()["owner_reviewed_adjustments"], 11)
        self.assertEqual(phase3.validate()["drivers"], 13)

    def test_33_changed_paths_are_phase4_only(self) -> None:
        phase4.validate_changed_paths()

    def test_34_closing_case_results(self) -> None:
        self.assertEqual(self.results["CC-LOW"]["total_uses"], Decimal("640"))
        self.assertEqual(self.results["CC-REF"]["total_uses"], Decimal("679.89771875"))
        self.assertEqual(self.results["CC-HIGH"]["total_uses"], Decimal("735.0191875"))
        self.assertEqual(self.results["CC-REF"]["new_revolver"], Decimal("29.89771875"))
        self.assertEqual(self.results["CC-HIGH"]["new_revolver"], Decimal("85.0191875"))

    def test_35_term_is_not_automatically_funded_to_cap(self) -> None:
        self.assertEqual(self.results["CC-LOW"]["term_funding"], Decimal("640"))
        self.assertLess(self.results["CC-LOW"]["term_funding"], Decimal("650"))

    def test_36_reference_availability_and_term_only_gap(self) -> None:
        ref = self.results["CC-REF"]
        self.assertEqual(ref["term_only_gap"], Decimal("29.89771875"))
        self.assertEqual(ref["remaining_availability"], Decimal("263.90228125"))
        self.assertEqual(ref["funding_gap"], 0)

    def test_37_contractual_ebitda_not_presented_as_official(self) -> None:
        phase5 = (phase4.DOCS / "PHASE5_HANDOFF.md").read_text(encoding="utf-8")
        self.assertIn("partial contractual reconstruction", phase5)
        self.assertIn("official compliance EBITDA", phase5)

    def test_38_book_cash_remains_nonaccessible_pending_diligence(self) -> None:
        bridge_cash = [row for row in self.bridges if row["item"] == "Closing cash"]
        self.assertTrue(all(row["closing_value"] == "" and row["status"] == "pending_information" for row in bridge_cash))
        self.assertTrue(all(row["borrower_cash_contribution"] == "0" for row in self.inputs))

    def test_39_lease_maturities_preserve_measurement_basis(self) -> None:
        finance = [row for row in self.maturities if row["structure"] == "existing_and_retained" and row["obligation_category"] == "finance_leases_and_other_contractual_payments"]
        operating = [row for row in self.maturities if row["structure"] == "existing_and_retained" and row["obligation_category"] == "operating_lease_contractual_payments"]
        self.assertEqual(sum((Decimal(row["amount"]) for row in finance), Decimal(0)), Decimal("87.493"))
        self.assertEqual(sum((Decimal(row["amount"]) for row in operating), Decimal(0)), Decimal("220.207"))
        self.assertTrue(all("undiscounted" in row["measurement_basis"] for row in finance + operating))

    def test_40_refinancing_economics_do_not_assume_savings(self) -> None:
        spread = [row for row in self.economics if row["analysis_type"] == "spread_and_upfront_fee_break_even"]
        positive = [row for row in spread if Decimal(row["annual_spread_savings_or_cost"]) > 0]
        self.assertEqual(len(positive), 3)
        self.assertTrue(all(row["existing_margin_bps"] == "275" and row["proposed_margin_bps"] == "250" for row in positive))
        self.assertEqual(sum(1 for row in positive if row["within_five_year_tenor"] == "yes"), 1)

    def test_41_complete_phase4_validation_passes(self) -> None:
        stats = phase4.validate()
        self.assertEqual(stats["closing_cases"], 3)
        self.assertEqual(stats["phase2_lender_base_ebitda"], "225.344")
        self.assertEqual(stats["post_cutoff_sources"], 0)

    def test_42_existing_maturity_definitions(self) -> None:
        def amount(bucket: str, category: str) -> Decimal:
            row = next(row for row in self.maturities
                       if row["structure"] == "existing"
                       and row["amortization_case"] == "EXISTING-EXECUTED"
                       and row["fiscal_bucket"] == bucket
                       and row["obligation_category"] == category)
            return Decimal(row["amount"])
        bucket = "FY2029_maturity_reporting_year"
        self.assertEqual(amount(bucket, "scheduled_term_principal_payments_during_period"), Decimal("18.75"))
        self.assertEqual(amount(bucket, "final_scheduled_term_installment_due_on_maturity_date"), 0)
        self.assertEqual(amount(bucket, "post_installment_term_balloon"), Decimal("375"))
        self.assertEqual(amount(bucket, "total_funded_principal_due_on_maturity_date"), Decimal("547.5"))
        self.assertEqual(amount(bucket, "total_funded_principal_payments_during_period"), Decimal("566.25"))

    def test_43_reference_proposed_maturity_definitions(self) -> None:
        def amount(bucket: str, category: str) -> Decimal:
            row = next(row for row in self.maturities
                       if row["structure"] == "proposed" and row["case_id"] == "CC-REF"
                       and row["amortization_case"] == "AMORT-10"
                       and row["fiscal_bucket"] == bucket
                       and row["obligation_category"] == category)
            return Decimal(row["amount"])
        fy = "FY2031_maturity_reporting_year"
        self.assertEqual(amount(fy, "final_scheduled_term_installment_due_on_maturity_date"), Decimal("16.25"))
        self.assertEqual(amount(fy, "post_installment_term_balloon"), Decimal("325"))
        self.assertEqual(amount(fy, "total_term_principal_due_on_maturity_date"), Decimal("341.25"))
        self.assertEqual(amount(fy, "total_funded_principal_due_on_maturity_date"), Decimal("371.14771875"))
        self.assertEqual(amount("FINAL_12M_TO_2031-01-31", "total_funded_principal_payments_during_period"),
                         Decimal("419.89771875"))

    def test_44_all_cases_and_amortization_maturity_measures_exist(self) -> None:
        required = {"term_principal_outstanding_at_beginning_of_period",
                    "scheduled_term_principal_payments_during_period",
                    "final_scheduled_term_installment_due_on_maturity_date",
                    "post_installment_term_balloon", "total_term_principal_due_on_maturity_date",
                    "revolver_principal_due_on_maturity_date",
                    "total_funded_principal_due_on_maturity_date",
                    "total_funded_principal_payments_during_period",
                    "retained_finance_leases_and_other_debt_maturities",
                    "revolver_unchanged_through_maturity_assumption"}
        for cid in ("CC-LOW", "CC-REF", "CC-HIGH"):
            for amort in ("AMORT-5", "AMORT-10", "AMORT-15"):
                rows = [row for row in self.maturities if row["structure"] == "proposed"
                        and row["case_id"] == cid and row["amortization_case"] == amort]
                for bucket in ("FY2031_maturity_reporting_year", "FINAL_12M_TO_2031-01-31"):
                    self.assertTrue(required.issubset({row["obligation_category"] for row in rows
                                                       if row["fiscal_bucket"] == bucket}))

    def test_45_fcf_and_accrued_interest_not_double_counted(self) -> None:
        ref = next(row for row in self.inputs if row["case_id"] == "CC-REF")
        self.assertEqual(ref["revolver_movement_role"], "principal_balance_sensitivity_not_cash_forecast")
        self.assertEqual(ref["accrued_interest_role"], "separate_unpaid_payoff_interest_sensitivity")
        self.assertIn("integrated cash and interest", ref["fcf_interest_double_counting_control"])
        self.assertIn("not an October-to-January cash forecast", ref["sensitivity_basis"])

    def test_46_pressure_lc_creates_restricted_nonusable_cash(self) -> None:
        row = next(row for row in self.bridges if row["case_id"] == "CC-HIGH"
                   and row["item"] == "Restricted cash created by LC collateralization")
        self.assertEqual(Decimal(row["closing_value"]), Decimal("6.2"))
        self.assertEqual(row["classification"], "restricted_asset_excluded_from_usable_liquidity")
        pressure_input = next(row for row in self.phase5
                              if row["input_name"] == "pressure_case_restricted_cash_from_lc_collateral")
        self.assertEqual(Decimal(pressure_input["reference_case_value"]), Decimal("6.2"))
        self.assertIn("excluded from usable liquidity", pressure_input["calculation_or_basis"])

    def test_47_descendant_ancestry_is_insufficient_for_phase3_integrity(self) -> None:
        protected = "data/phase3/processed/RISK_DRIVER_MAP.csv"
        self.assertIn(protected, phase3.PROTECTED_PHASE3_PATHS)
        with self.assertRaises(phase3.Phase3Error):
            phase3.validate_protected_phase3_artifacts([protected])
        phase3.validate_protected_phase3_artifacts([])

    def test_48_owner_review_is_not_final_approval(self) -> None:
        covenants = [row for row in self.terms if row["category"] == "covenants"]
        self.assertTrue(all(row["owner_review_status"] == phase4.OWNER_THRESHOLD for row in covenants))
        self.assertTrue(all("not an approved final covenant" in row["notes"] for row in covenants))
        handoff = (phase4.DOCS / "PHASE5_HANDOFF.md").read_text(encoding="utf-8")
        self.assertIn("refinancing is not approved", handoff.replace("\n", " ").lower())


if __name__ == "__main__":
    unittest.main()
