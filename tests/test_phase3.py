"""Decision-relevant controls for the Phase 3 driver-evidence layer."""

from __future__ import annotations

import copy
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


class Phase3ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = phase3.read_csv(phase3.RAW / "SOURCE_ADDITIONS.csv")
        cls.evidence = phase3.read_csv(phase3.RAW / "DRIVER_EVIDENCE.csv")
        cls.owner_decisions = phase3.read_csv(phase3.RAW / "OWNER_REVIEW_DECISIONS.csv")
        cls.trends = phase3.read_csv(phase3.PROCESSED / "QUARTERLY_SEGMENT_TRENDS.csv")
        cls.drivers = phase3.read_csv(phase3.PROCESSED / "RISK_DRIVER_MAP.csv")
        cls.assumptions = phase3.read_csv(phase3.PROCESSED / "ASSUMPTION_CANDIDATES.csv")
        cls.scenarios = phase3.read_csv(phase3.PROCESSED / "SCENARIO_DRIVER_CANDIDATES.csv")
        cls.mitigations = phase3.read_csv(phase3.PROCESSED / "MITIGATION_REGISTER.csv")
        cls.gaps = phase3.read_csv(phase3.PROCESSED / "INFORMATION_GAPS.csv")
        cls.ledger = phase3.read_csv(phase3.DOCS / "SOURCE_LEDGER.csv")

    def test_01_starting_checkpoint_and_head_are_preserved(self) -> None:
        checkpoint = phase3.read_csv(phase3.RAW / "STARTING_CHECKPOINT.csv")[0]
        self.assertEqual(checkpoint["local_head"], phase3.APPROVED_PHASE2_COMMIT)
        self.assertEqual(checkpoint["tracked_origin_main"], phase3.APPROVED_PHASE2_COMMIT)
        self.assertEqual(checkpoint["live_remote_main"], phase3.APPROVED_PHASE2_COMMIT)
        self.assertEqual((checkpoint["ahead"], checkpoint["behind"]), ("0", "0"))
        self.assertEqual(checkpoint["working_tree_clean_before_work"], "yes")

    def test_02_cutoff_compliance(self) -> None:
        for row in self.sources:
            self.assertLessEqual(
                datetime.strptime(row["publication_date"], "%Y-%m-%d").date(),
                phase3.CUTOFF,
            )
            self.assertEqual(row["cutoff_status"], "ALLOWED")
        for row in self.evidence:
            self.assertLessEqual(
                datetime.strptime(row["publication_date"], "%Y-%m-%d").date(),
                phase3.CUTOFF,
            )

    def test_03_observation_and_publication_dates_are_distinct(self) -> None:
        industry = [row for row in self.evidence if row["topic"] == "industry_indicator"]
        self.assertTrue(industry)
        self.assertTrue(all(row["observation_date"] != row["publication_date"] for row in industry))

    def test_04_external_vintage_and_revision_fields(self) -> None:
        industry = [row for row in self.evidence if row["topic"] == "industry_indicator"]
        self.assertTrue(all(row["vintage"].startswith("release_vintage_") for row in industry))
        self.assertTrue(all(row["historical_range_used"] for row in industry))
        self.assertTrue(all(row["relationship_to_quanex"] in {"direct", "indirect", "contextual"}
                            for row in industry))
        revisable = [row for row in industry if row["source_ids"] in {"SRC-023", "SRC-025"}]
        self.assertTrue(all(row["revision_risk"] == "revisable_flagged" for row in revisable))

    def test_05_every_material_claim_has_source(self) -> None:
        self.assertTrue(all(row["claim"] and row["source_ids"] for row in self.evidence))
        self.assertTrue(all(row["source_ids"] for row in self.drivers))

    def test_06_new_source_provenance_and_hashes(self) -> None:
        required = set(phase3.SOURCE_FIELDS) - {"notes"}
        for row in self.sources:
            self.assertTrue(all(row[field] for field in required), row["source_id"])
            self.assertEqual(len(row["extract_sha256"]), 64)
            self.assertGreater(int(row["extract_bytes"]), 0)
        self.assertEqual([row["source_id"] for row in self.sources],
                         [f"SRC-{number:03d}" for number in range(17, 26)])

    def test_07_identifiers_are_unique(self) -> None:
        for rows, field in (
            (self.sources, "source_id"), (self.evidence, "evidence_id"),
            (self.trends, "trend_id"), (self.drivers, "driver_id"),
            (self.assumptions, "assumption_id"),
            (self.scenarios, "scenario_candidate_id"),
            (self.mitigations, "mitigation_id"), (self.gaps, "gap_id"),
            (self.owner_decisions, "decision_id"),
        ):
            values = [row[field] for row in rows]
            self.assertEqual(len(values), len(set(values)))

    def test_07b_relationship_evidence_ids_are_valid_and_unique(self) -> None:
        valid = {row["evidence_id"] for row in self.evidence}
        for rows, field in (
            (self.drivers, "supporting_evidence_ids"),
            (self.assumptions, "evidence_ids"),
            (self.scenarios, "evidence_ids"),
            (self.mitigations, "evidence_ids"),
        ):
            for row in rows:
                values = [value for value in row[field].split(";") if value]
                self.assertEqual(len(values), len(set(values)))
                self.assertFalse(set(values) - valid)

    def test_08_quarterly_figures_reconcile_to_annual(self) -> None:
        q = {(row["fiscal_year"], row["quarter"], row["metric_name"]): Decimal(row["value"])
             for row in self.trends if row["quarter"] and row["classification"] == "reported"}
        annual = {(row["fiscal_year"], row["metric_name"]): Decimal(row["value"])
                  for row in phase3.read_csv(phase3.PHASE2_SPREAD) if row["value"]}
        for fy in ("FY2024", "FY2025"):
            for metric in ("revenue", "gross_profit", "cash_flow_from_operations",
                           "capital_expenditures", "free_cash_flow"):
                self.assertEqual(sum(q[(fy, quarter, metric)] for quarter in ("Q1", "Q2", "Q3", "Q4")),
                                 annual[(fy, metric)])
        self.assertEqual(sum(q[("FY2025", quarter, "company_adjusted_ebitda")]
                             for quarter in ("Q1", "Q2", "Q3", "Q4")), Decimal("242.890"))

    def test_09_pre_and_post_tyman_perimeters_are_distinct(self) -> None:
        quarterly = [row for row in self.trends if row["quarter"] and row["metric_name"] == "revenue"]
        p = {(row["fiscal_year"], row["quarter"]): row["perimeter"] for row in quarterly}
        self.assertTrue(all(p[("FY2024", quarter)] == "legacy_pre_tyman" for quarter in ("Q1", "Q2", "Q3")))
        self.assertEqual(p[("FY2024", "Q4")], "mixed_three_months_tyman")
        self.assertTrue(all(p[("FY2025", quarter)] == "full_post_tyman" for quarter in ("Q1", "Q2", "Q3", "Q4")))

    def test_10_current_segments_are_not_fabricated_backwards(self) -> None:
        segment = [row for row in self.trends if row["segment"] not in {"", "Consolidated"}]
        self.assertTrue(segment)
        self.assertTrue(all(row["fiscal_year"] in {"FY2024", "FY2025"} for row in segment))
        self.assertTrue(all(row["perimeter"] == "company_recast_current_segments" for row in segment))

    def test_11_material_drivers_have_analytical_consequence(self) -> None:
        self.assertEqual(len(self.drivers), 13)
        for row in self.drivers:
            self.assertTrue(row["primary_forecast_line"] or row["potential_diligence_condition"]
                            or row["potential_monitoring_metric"])
            self.assertTrue(row["cash_flow_transmission"])

    def test_12_every_scenario_maps_to_driver(self) -> None:
        valid = {row["driver_id"] for row in self.drivers}
        self.assertTrue(all(row["driver_id"] in valid for row in self.scenarios))

    def test_13_moderate_and_severe_ranges_are_ordered(self) -> None:
        for row in self.scenarios:
            fields = ("moderate_low", "moderate_high", "severe_low", "severe_high")
            if all(row[field] for field in fields):
                ml, mh, sl, sh = (Decimal(row[field]) for field in fields)
                self.assertLessEqual(ml, mh)
                self.assertLessEqual(sl, sh)
                if row["scenario_candidate_id"] in {"SCN-001", "SCN-002"}:
                    self.assertGreaterEqual(abs(sl), abs(ml))

    def test_14_units_are_explicit_and_not_mixed(self) -> None:
        self.assertTrue(all(row["units"] in phase3.VALID_UNITS for row in self.evidence))
        self.assertTrue(all(row["units"] in phase3.VALID_UNITS for row in self.assumptions))
        self.assertTrue(all(row["units"] in phase3.VALID_UNITS for row in self.scenarios))

    def test_15_volume_and_margin_double_counting_is_controlled(self) -> None:
        volume = next(row for row in self.scenarios if row["scenario_candidate_id"] == "SCN-001")
        margin = next(row for row in self.scenarios if row["scenario_candidate_id"] == "SCN-002")
        self.assertIn("fixed-cost deleverage", volume["overlap_control"])
        self.assertIn("fixed-cost deleverage", margin["overlap_control"])

    def test_16_mitigations_are_separate_from_unmitigated_stress(self) -> None:
        self.assertTrue(all(row["embedded_in_unmitigated_stress"] == "no" for row in self.mitigations))
        for row in self.scenarios:
            self.assertEqual(row["unmitigated_distribution_treatment"],
                             "retain_selected_base_distribution_policy")
            self.assertEqual(row["mitigated_distribution_treatment"],
                             "separate_mitigation_register_only")
        distributions = next(row for row in self.scenarios
                             if row["scenario_candidate_id"] == "SCN-007")
        self.assertIn("both unmitigated cases", distributions["transmission_mechanism"])
        self.assertNotIn("No discretionary distributions", distributions["transmission_mechanism"])
        mitigation_actions = {row["action"] for row in self.mitigations}
        self.assertIn("Suspend share repurchases", mitigation_actions)
        self.assertIn("Reduce or suspend dividends", mitigation_actions)

    def test_17_speculative_mitigations_receive_no_credit(self) -> None:
        speculative = [row for row in self.mitigations if row["availability_status"] == "speculative"]
        self.assertEqual(len(speculative), 1)
        self.assertIn("No credit", speculative[0]["potential_cash_benefit"])

    def test_18_maintenance_capex_is_not_assumed_removable(self) -> None:
        capex = next(row for row in self.scenarios if row["scenario_candidate_id"] == "SCN-008")
        self.assertEqual(capex["moderate_low"], "")
        self.assertEqual(capex["severe_low"], "")
        self.assertIn("maintenance", capex["transmission_mechanism"])

    def test_19_missing_information_is_not_zero(self) -> None:
        self.assertTrue(all(row["status"] == "pending_information" for row in self.gaps))
        restructuring = next(row for row in self.assumptions if row["assumption_id"] == "ASM-009")
        self.assertEqual(restructuring["proposed_high"], "")
        fx = next(row for row in self.assumptions if row["assumption_id"] == "ASM-013")
        self.assertEqual((fx["proposed_low"], fx["proposed_high"]), ("", ""))
        for aid in ("ASM-015", "ASM-016"):
            row = next(item for item in self.assumptions if item["assumption_id"] == aid)
            self.assertEqual((row["proposed_low"], row["proposed_high"]), ("", ""))
            self.assertEqual(row["status"], "pending_information")

    def test_20_owner_review_decisions_are_preserved(self) -> None:
        self.assertTrue(all(row["owner_review_status"] == "owner_reviewed"
                            for row in self.assumptions))
        self.assertTrue(all(row["owner_review_status"] == "owner_reviewed"
                            for row in self.scenarios))
        self.assertTrue(all(row["owner_review_status"] == "owner_reviewed"
                            for row in self.mitigations))
        self.assertEqual(len(self.owner_decisions), 33)

    def test_21_phase2_ebitda_and_adjustments_are_unchanged(self) -> None:
        _, lender = phase3.phase2_values()
        self.assertEqual(lender, {"FY2024": Decimal("179.358"), "FY2025": Decimal("225.344")})
        decisions = phase3.read_csv(phase3.PHASE2_DECISIONS)
        expected = {"AC-001": "302.284", "AC-002": "0", "AC-003": "0", "AC-004": "9.007",
                    "AC-005": "0", "AC-006": "4.561", "AC-007": "0", "AC-008": "0",
                    "AC-009": "-4.196", "AC-010": "29.076", "AC-011": "39.324"}
        self.assertEqual({row["adjustment_id"]: row["accepted_amount_base"] for row in decisions}, expected)

    def test_22_prior_phase_python_validations_pass(self) -> None:
        self.assertEqual(phase1.validate_all()["manual_overrides"], 0)
        self.assertEqual(phase2.validate()["owner_reviewed_adjustments"], 11)

    def test_23_deterministic_regeneration(self) -> None:
        before = phase3.fingerprints()
        phase3.build()
        self.assertEqual(before, phase3.fingerprints())

    def test_24_q2_adjusted_ebitda_difference_remains_visible(self) -> None:
        rows = [row for row in self.evidence if row["fiscal_year"] == "FY2025"
                and row["quarter"] == "Q2" and row["metric_name"] == "company_adjusted_ebitda"]
        self.assertEqual(len(rows), 2)
        selected = next(row for row in rows if row["acceptance_status"] == "accepted")
        original = next(row for row in rows if row["acceptance_status"] != "accepted")
        self.assertEqual(Decimal(selected["value"]) - Decimal(original["value"]), Decimal("1.222"))
        self.assertEqual(original["revision_risk"], "visible_within_cutoff_presentation_difference")

    def test_25_complete_phase3_validation_passes(self) -> None:
        stats = phase3.validate()
        self.assertEqual(stats["post_cutoff_sources"], 0)
        self.assertEqual(stats["owner_reviewed_assumptions"], 13)
        self.assertEqual(stats["drivers"], 13)

    def test_26_payables_method_does_not_fabricate_dpo(self) -> None:
        payables = next(row for row in self.assumptions if row["assumption_id"] == "ASM-015")
        self.assertIn("purchases", payables["calculation_method"])
        self.assertIn("cannot be labeled DPO", payables["rationale"])
        self.assertNotEqual(payables["proposed_direction_or_range"], "0")
        scenario = next(row for row in self.scenarios
                        if row["scenario_candidate_id"] == "SCN-009")
        self.assertIn("Do not use DPO without purchases", scenario["overlap_control"])

    def test_27_ebitda_margin_is_validation_only(self) -> None:
        row = next(item for item in self.assumptions if item["assumption_id"] == "ASM-004")
        self.assertEqual(row["assumption_role"], "validation_band")
        self.assertEqual(row["forecast_override_permitted"], "no")
        self.assertIn("flag", row["calculation_method"])
        self.assertIn("cannot override", row["rationale"])

    def test_28_monitoring_observability_and_reporting_sources(self) -> None:
        valid = {"publicly_observable", "available_through_required_borrower_reporting",
                 "dependent_on_private_diligence", "not_currently_measurable"}
        for row in self.drivers:
            self.assertIn(row["monitoring_observability"], valid)
            if row["monitoring_observability"] != "publicly_observable":
                self.assertTrue(row["required_reporting_source"])
        by_id = {row["driver_id"]: row for row in self.drivers}
        for did in ("DRV-001", "DRV-003", "DRV-004", "DRV-006", "DRV-009",
                    "DRV-012", "DRV-013"):
            self.assertTrue(by_id[did]["required_reporting_source"])

    def test_29_census_vintage_excludes_january_release(self) -> None:
        census = next(row for row in self.sources if row["source_id"] == "SRC-023")
        self.assertIn("latest actual", census["notes"])
        self.assertIn("2026-01-09", census["notes"])
        self.assertIn("excluded", census["notes"])
        self.assertFalse(any("2026-01-09" in "|".join(row.values()) for row in self.evidence))


if __name__ == "__main__":
    unittest.main()
