from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("phase10_test_module", ROOT / "scripts" / "phase10.py")
assert SPEC and SPEC.loader
phase10 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = phase10
SPEC.loader.exec_module(phase10)


def rows(relative: str) -> list[dict[str, str]]:
    with (ROOT / relative).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class Phase10DataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.decisions = rows("data/phase10/raw/OWNER_REVIEW_DECISIONS.csv")
        cls.metrics = rows("data/phase10/processed/COMMITTEE_METRICS.csv")
        cls.metric = {(r["metric_name"], r["scenario_or_period"]): r for r in cls.metrics}
        cls.risks = rows("data/phase10/processed/RISK_MITIGANT_MATRIX.csv")
        cls.conditions = rows("data/phase10/processed/CONDITIONS_AND_MONITORING.csv")
        cls.ledger = rows("docs/phase-10/SOURCE_LEDGER.csv")

    def test_starting_checkpoint(self) -> None:
        row = rows("data/phase10/raw/STARTING_CHECKPOINT.csv")[0]
        self.assertEqual(row["repository"], "owencchapman24/quanex-credit-underwriting")
        self.assertEqual(row["branch"], "main")
        self.assertEqual(row["approved_phase9_commit"], phase10.APPROVED_PHASE9_COMMIT)
        self.assertEqual(row["local_head"], phase10.APPROVED_PHASE9_COMMIT)

    def test_owner_review_topics_and_status(self) -> None:
        self.assertGreaterEqual(len(self.decisions), 15)
        self.assertEqual(len(self.decisions), 18)
        self.assertTrue(all(r["review_status"] == phase10.RECOMMENDATION_STATUS for r in self.decisions))

    def test_all_phase10_decisions_are_owner_reviewed(self) -> None:
        self.assertEqual(phase10.RECOMMENDATION_STATUS, "owner_reviewed")
        self.assertTrue(all(r["review_status"] == "owner_reviewed" for r in self.decisions))

    def test_required_review_topics(self) -> None:
        required = {
            "recommendation", "recommended facilities", "bank hold", "transaction rationale",
            "fallback alternative", "decisive strengths", "decisive risks", "conditions precedent",
            "distribution restrictions", "monitoring and escalation", "risk-grade wording",
            "recovery wording", "residual refinancing dependency", "strongest counterargument",
            "final memo language",
        }
        self.assertTrue(required.issubset({r["topic"] for r in self.decisions}))

    def test_selected_facilities_and_hold(self) -> None:
        self.assertEqual(Decimal(self.metric[("term_facility", "selected")]["value"]), Decimal("635"))
        self.assertEqual(Decimal(self.metric[("revolver_commitment", "selected")]["value"]), Decimal("300"))
        self.assertEqual(Decimal(self.metric[("bank_hold_cap", "selected")]["value"]), Decimal("50"))

    def test_conditional_source_is_not_debt_funded(self) -> None:
        facility = next(r for r in self.decisions if r["topic"] == "recommended facilities")
        fallback = next(r for r in self.decisions if r["topic"] == "fallback alternative")
        self.assertIn("do not substitute incremental debt", facility["working_decision"])
        self.assertIn("retain or amend", fallback["working_decision"].lower())

    def test_opening_anchors(self) -> None:
        expected = {
            ("opening_funded_debt", "selected"): "727.51671875",
            ("opening_gross_leverage", "selected"): "3.228471664433044589605225788",
            ("base_all_in_liquidity", "selected"): "263.90228125",
            ("sources_less_uses", "selected"): "0",
        }
        for key, value in expected.items():
            self.assertEqual(Decimal(self.metric[key]["value"]), Decimal(value))

    def test_historical_ebitda_anchors(self) -> None:
        self.assertEqual(Decimal(self.metric[("lender_base_ebitda", "FY2024")]["value"]), Decimal("179.358"))
        self.assertEqual(Decimal(self.metric[("lender_base_ebitda", "FY2025")]["value"]), Decimal("225.344"))

    def test_historical_cash_paid_interest_is_separate_and_sourced(self) -> None:
        expected = {
            "FY2024": (Decimal("10.910"), Decimal("16.43978001833181")),
            "FY2025": (Decimal("52.630"), Decimal("4.281664449933498")),
        }
        generated = {
            (row["metric_name"], row["scenario_or_period"]): row
            for row in phase10.committee_metrics()
        }
        for year, (paid, coverage) in expected.items():
            for metric_set in (generated, self.metric):
                paid_row = metric_set[("cash_interest_paid_disclosed", year)]
                coverage_row = metric_set[("historical_lender_ebitda_to_disclosed_cash_interest_paid", year)]
                self.assertEqual(Decimal(paid_row["value"]), paid)
                self.assertAlmostEqual(float(coverage_row["value"]), float(coverage), places=12)
                self.assertEqual(paid_row["source_ids"], "SRC-001")
                self.assertIn("SRC-001", coverage_row["source_ids"])
                self.assertIn("S2B-", coverage_row["source_ids"])
                self.assertIn("S2S-", coverage_row["source_ids"])
                self.assertIn("not a closing-LTM", paid_row["limitations"])
                self.assertIn("diagnostic", coverage_row["limitations"].lower())

    def test_scenario_anchors(self) -> None:
        expected = {
            ("unsupported_maturity_gap", "BASE"): "324.77970512014787",
            ("unsupported_maturity_gap", "MODERATE_UNMITIGATED"): "408.3752156813583",
            ("unsupported_maturity_gap", "MODERATE_MITIGATED"): "381.1325753758992",
            ("unsupported_maturity_gap", "SEVERE_UNMITIGATED"): "604.2580066325874",
            ("unsupported_maturity_gap", "SEVERE_MITIGATED"): "554.7181887062254",
        }
        for key, value in expected.items():
            self.assertAlmostEqual(float(self.metric[key]["value"]), float(value), places=6)

    def test_downside_event_ordering(self) -> None:
        self.assertEqual(self.metric[("first_warning", "MODERATE_UNMITIGATED")]["value"], "2026-10-31")
        self.assertEqual(self.metric[("first_breach", "MODERATE_UNMITIGATED")]["value"], "2026-10-31")
        self.assertEqual(self.metric[("first_mandatory_payment_failure", "SEVERE_UNMITIGATED")]["value"], "2027-12-31")

    def test_maturity_horizons_are_qualified(self) -> None:
        for candidate in ("STR-001", "STR-003", "STR-008"):
            limitation = self.metric[("unsupported_maturity_gap", candidate)]["limitations"]
            self.assertIn("horizons differ", limitation)

    def test_common_horizon_balances_and_differences(self) -> None:
        expected = {
            ("common_horizon_total_funded_debt", "existing"): "495.3682812067100176549274129",
            ("common_horizon_total_funded_debt", "reference"): "507.9536592508711071826688285",
            ("common_horizon_total_funded_debt", "selected"): "514.753707786180339509466437",
            ("selected_minus_existing_common_horizon_debt", "2029-07-31"): "19.3854265794703218545390241",
            ("selected_minus_reference_common_horizon_debt", "2029-07-31"): "6.8000485353092323267976085",
        }
        for key, value in expected.items():
            self.assertEqual(Decimal(self.metric[key]["value"]), Decimal(value))
            self.assertEqual(self.metric[key]["measurement_horizon"], "2029-07-31")
        for key in (("common_horizon_total_funded_debt", "existing"), ("common_horizon_total_funded_debt", "reference"), ("common_horizon_total_funded_debt", "selected")):
            self.assertEqual(self.metric[key]["measurement_basis"], "point_in_time_total_funded_debt")

    def test_opening_debt_comparisons_use_explicit_dates(self) -> None:
        expected = {
            ("opening_total_funded_debt", "existing_actual"): ("703.869", "2025-10-31", "historical_actual_point_in_time"),
            ("opening_total_funded_debt", "existing_projected"): ("732.51671875", "2026-01-31", "projected_closing_point_in_time"),
            ("opening_total_funded_debt", "reference_projected"): ("742.51671875", "2026-01-31", "projected_closing_point_in_time"),
            ("opening_total_funded_debt", "selected_projected"): ("727.51671875", "2026-01-31", "projected_closing_point_in_time"),
        }
        for key, (value, horizon, basis) in expected.items():
            row = self.metric[key]
            self.assertEqual(Decimal(row["value"]), Decimal(value))
            self.assertEqual((row["measurement_horizon"], row["measurement_basis"]), (horizon, basis))
        self.assertEqual(Decimal(self.metric[("selected_minus_existing_projected_closing_debt", "2026-01-31")]["value"]), Decimal("-5"))

    def test_forecast_horizons_are_explicit(self) -> None:
        generated = {
            (row["metric_name"], row["scenario_or_period"]): row
            for row in phase10.committee_metrics()
        }
        scenarios = {
            "BASE", "MODERATE_UNMITIGATED", "MODERATE_MITIGATED",
            "SEVERE_UNMITIGATED", "SEVERE_MITIGATED",
        }
        for scenario in scenarios:
            nine_month = generated[("fy2026_post_closing_nine_month_lender_ebitda", scenario)]
            self.assertEqual(
                (nine_month["measurement_horizon"], nine_month["measurement_basis"]),
                ("2026-02-01 through 2026-10-31", "post_closing_nine_month_period"),
            )
            self.assertIn("not an annual figure", nine_month["limitations"])
        for name in ("modeled_operating_cash", "cfads", "cash_interest", "scheduled_principal", "ecf_sweep_realized"):
            row = self.metric[(name, "BASE")]
            self.assertEqual(row["measurement_horizon"], "2026-02-01 through 2031-01-31")
            self.assertEqual(row["measurement_basis"], "cumulative_model_period")
        self.assertEqual(self.metric[("minimum_cash_interest_coverage", "BASE")]["measurement_basis"], "minimum_over_forecast")
        self.assertEqual(self.metric[("unsupported_maturity_gap", "BASE")]["measurement_basis"], "point_in_time_bank_debt_maturity_gap")

        q1 = next(
            row for row in rows("data/phase5/processed/FY2026_PERIOD_PRESENTATION.csv")
            if row["presentation_id"] == "PP-001"
        )
        full_year = next(
            row for row in rows("data/phase5/processed/FY2026_PERIOD_PRESENTATION.csv")
            if row["presentation_id"] == "PP-004"
        )
        base_nine_month = Decimal(
            generated[("fy2026_post_closing_nine_month_lender_ebitda", "BASE")]["value"]
        )
        self.assertLessEqual(
            abs(base_nine_month + Decimal(q1["lender_base_ebitda"]) - Decimal(full_year["lender_base_ebitda"])),
            Decimal("0.000000000001"),
        )
        moderate_nine_month = Decimal(
            generated[("fy2026_post_closing_nine_month_lender_ebitda", "MODERATE_UNMITIGATED")]["value"]
        )
        self.assertAlmostEqual(
            float(moderate_nine_month + Decimal(q1["lender_base_ebitda"])),
            183.02510750838724,
            places=10,
        )

    def test_moderate_breach_anchors(self) -> None:
        expected = {
            ("maximum_quarterly_test_leverage", "MODERATE_UNMITIGATED"): "4.489250193362221",
            ("maximum_quarterly_test_leverage", "MODERATE_MITIGATED"): "4.467006108046972",
            ("minimum_cash_interest_coverage", "MODERATE_UNMITIGATED"): "3.210373832256529",
            ("minimum_cash_interest_coverage", "MODERATE_MITIGATED"): "3.2168340672059608",
            ("all_in_minimum_liquidity", "MODERATE_UNMITIGATED"): "165.07840972377255",
            ("all_in_minimum_liquidity", "MODERATE_MITIGATED"): "168.9369195595644",
        }
        for key, value in expected.items():
            self.assertAlmostEqual(float(self.metric[key]["value"]), float(value), places=6)
        for scenario in ("MODERATE_UNMITIGATED", "MODERATE_MITIGATED"):
            self.assertEqual(self.metric[("first_warning", scenario)]["value"], "2026-10-31")
            self.assertEqual(self.metric[("first_breach", scenario)]["value"], "2026-10-31")
            self.assertEqual(self.metric[("first_mandatory_payment_failure", scenario)]["value"], "N/D")

    def test_recovery_cases_remain_alternatives(self) -> None:
        recovery = [r for r in self.metrics if r["category"] == "recovery"]
        self.assertEqual(len([r for r in recovery if r["metric_name"].endswith("_recovery")]), 7)
        self.assertEqual(self.metric[("official_facility_recovery", "public_information")]["value"], "N/D")
        self.assertTrue(all(r["classification"] != "official_recovery" for r in recovery))

    def test_risk_grade_is_project_specific_and_separate(self) -> None:
        row = self.metric[("borrower_risk_grade", "project_specific")]
        self.assertEqual(row["value"], "Elevated")
        self.assertIn("Project-specific qualitative", row["limitations"])

    def test_risk_matrix_is_complete(self) -> None:
        self.assertEqual(len(self.risks), 13)
        self.assertTrue(all(r["evidence"] and r["credit_consequence"] and r["residual_risk"] for r in self.risks))

    def test_condition_categories_remain_distinct(self) -> None:
        self.assertEqual(
            {r["category"] for r in self.conditions},
            {"condition_precedent", "ongoing_covenant", "monitoring_requirement", "analyst_warning", "unresolved_diligence"},
        )

    def test_conditions_are_open(self) -> None:
        self.assertEqual(len(self.conditions), 26)
        self.assertTrue(all(r["status"] == "open_not_satisfied_from_public_information" for r in self.conditions))

    def test_cutoff_and_source_hashes(self) -> None:
        self.assertTrue(all(r["cutoff_status"] == "within_cutoff" for r in self.ledger))
        for row in self.ledger:
            self.assertEqual(hashlib.sha256((ROOT / row["source_path"]).read_bytes()).hexdigest(), row["sha256"])

    def test_metric_lineage(self) -> None:
        self.assertEqual(len({r["metric_id"] for r in self.metrics}), len(self.metrics))
        self.assertTrue(all(r["source_path"] and r["classification"] and r["review_status"] for r in self.metrics))

    def test_deterministic_data_regeneration(self) -> None:
        tracked = [
            ROOT / "data/phase10/raw/OWNER_REVIEW_DECISIONS.csv",
            ROOT / "data/phase10/processed/COMMITTEE_METRICS.csv",
            ROOT / "data/phase10/processed/CONDITIONS_AND_MONITORING.csv",
            ROOT / "docs/phase-10/METHODOLOGY.md",
            ROOT / "reports/credit_memo.md",
            ROOT / "reports/committee_brief.md",
        ]
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
        phase10.build_data()
        after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
        self.assertEqual(before, after)


class Phase10DeliverableTests(unittest.TestCase):
    def test_memo_and_brief_status(self) -> None:
        for name in ("credit_memo.md", "committee_brief.md"):
            text = (ROOT / "reports" / name).read_text(encoding="utf-8")
            self.assertIn("owner_reviewed", text)
            self.assertNotIn("provisional_pending_owner_review", text)
            self.assertIn("conditional approval", text.lower())
            self.assertIn("retain or amend", text.lower())

    def test_repayment_hierarchy_is_correct(self) -> None:
        combined = "\n".join((ROOT / "reports" / name).read_text(encoding="utf-8") for name in ("credit_memo.md", "committee_brief.md")).lower()
        self.assertIn("primary repayment is recurring operating cash", combined)
        self.assertIn("payment mechanisms", combined)
        self.assertIn("liquidity support only", combined)
        self.assertIn("refinancing is an unresolved", combined)
        self.assertIn("secondary backstop", combined)
        self.assertNotIn("refinancing remains secondary", combined)
        self.assertNotIn("secondary support is drawable revolver", combined)

    def test_required_owner_wording(self) -> None:
        memo = (ROOT / "reports" / "credit_memo.md").read_text(encoding="utf-8")
        brief = (ROOT / "reports" / "committee_brief.md").read_text(encoding="utf-8")
        moderate = "The proposed covenant is intended to create early lender intervention while liquidity and payment capacity remain available. Conditional approval accepts the possibility of an early moderate-case covenant breach only because the structure preserves substantial liquidity, separates breach from payment failure, mandates reporting and corrective action, and does not assume an automatic waiver."
        for text in (memo, brief):
            for token in ("January 31, 2026", "$727.517m", "$732.517m", "$5.000m", "$19.385", "approximately 18 additional months"):
                self.assertIn(token, text)
            self.assertRegex(text, r"conditional \$15(?:\.000)?m")
            self.assertRegex(text.lower(), r"(?:moderate.{0,120}breach|breach.{0,120}moderate)")
            self.assertIn(moderate, text)
            self.assertIn(phase10.NO_FINAL_AUTHORIZATION, text)
            self.assertNotIn("near-term debt expansion", text.lower())

    def test_memo_required_sections(self) -> None:
        text = (ROOT / "reports/credit_memo.md").read_text(encoding="utf-8")
        for heading in (
            "Decision and exposure", "Transaction and alternatives", "Borrower and business risk",
            "Historical performance and earnings quality", "Debt, legal structure, and liquidity",
            "Base repayment and refinancing", "Downside and covenant intervention",
            "Recovery and risk assessment", "Conditions, monitoring, and conclusion",
        ):
            self.assertIn(heading, text)

    def test_brief_is_standalone(self) -> None:
        text = (ROOT / "reports/committee_brief.md").read_text(encoding="utf-8")
        for token in ("$635.000m", "$300.000m", "$50.000m", "$15m", "N/D", "December 15, 2025"):
            self.assertIn(token, text)

    def test_pdf_page_counts_and_boundaries(self) -> None:
        meta = phase10.pdf_metadata()
        self.assertEqual(meta["credit_memo_pages"], 11)
        self.assertEqual(meta["credit_memo_body_pages"], 7)
        self.assertEqual(meta["credit_memo_appendix_pages"], 4)
        self.assertEqual(meta["committee_brief_pages"], 1)
        self.assertTrue(meta["memo_required_sections"])
        self.assertTrue(meta["brief_disclaimer"])
        self.assertTrue(meta["cutoff_present"])
        self.assertTrue(meta["closing_present"])

    def test_rendered_page_qa(self) -> None:
        qa = rows("data/phase10/processed/DOCUMENT_QA_RESULTS.csv")
        self.assertEqual(len(qa), 12)
        self.assertTrue(all(r["status"] == "PASS" for r in qa))

    def test_workbook_structure(self) -> None:
        meta = phase10.workbook_metadata()
        self.assertEqual(meta["sheet_count"], 14)
        self.assertGreaterEqual(meta["formula_count"], 2880)
        self.assertEqual(meta["chart_count"], 7)
        self.assertEqual(meta["saved_scenario"], "Base")
        self.assertEqual(meta["external_links"], 0)
        self.assertEqual(meta["formula_errors"], 0)
        self.assertEqual(meta["checks_dependencies"], 0)

    def test_credit_summary_content(self) -> None:
        self.assertIn(phase10.RECOMMENDATION_DISPLAY, phase10.xlsx_cell_text("Credit Summary", "C5"))
        self.assertIn(phase10.NO_FINAL_AUTHORIZATION, phase10.xlsx_cell_text("Credit Summary", "C6"))
        self.assertIn(phase10.RECOMMENDATION_STATUS, phase10.xlsx_cell_text("Credit Summary", "I48"))
        self.assertIn("$635m term / $300m revolver", phase10.xlsx_cell_text("Credit Summary", "I49"))
        self.assertIn("Up to $50m", phase10.xlsx_cell_text("Credit Summary", "J49"))
        self.assertIn("$495.368m", phase10.xlsx_cell_text("Credit Summary", "I52"))
        self.assertIn("4.4893x/4.4670x", phase10.xlsx_cell_text("Credit Summary", "I53"))
        self.assertIn("limited amendment/extension", phase10.xlsx_cell_text("Credit Summary", "J54"))
        self.assertIn("N/D", phase10.xlsx_cell_text("Credit Summary", "I55"))

    def test_workbook_phase10_check(self) -> None:
        self.assertEqual(phase10.xlsx_cell_text("Checks", "D55"), phase10.RECOMMENDATION_STATUS)
        self.assertEqual(phase10.xlsx_cell_text("Checks", "E55"), phase10.RECOMMENDATION_STATUS)

    def test_checks_g20_keeps_compatible_formula(self) -> None:
        with zipfile.ZipFile(phase10.MODEL) as archive:
            xml = archive.read("xl/worksheets/sheet14.xml").decode("utf-8")
        self.assertIn('r="G20"', xml)
        self.assertIn("IF(OR(", xml)

    def test_no_external_links_or_formula_errors(self) -> None:
        structure = phase10.phase8.workbook_structure()
        self.assertFalse(structure["external_links"])
        self.assertFalse(structure["formula_errors"])
        self.assertFalse(structure["excel_formula_compatibility_issues"])

    def test_consistency_results_all_pass(self) -> None:
        checks = rows("data/phase10/processed/DELIVERABLE_CONSISTENCY_RESULTS.csv")
        self.assertTrue(checks)
        self.assertTrue(all(r["status"] == "PASS" for r in checks))

    def test_validation_results_all_pass(self) -> None:
        checks = rows("data/phase10/processed/VALIDATION_RESULTS.csv")
        self.assertTrue(checks)
        self.assertTrue(all(r["status"] == "PASS" for r in checks))

    def test_no_phase12_implementation(self) -> None:
        for path in (ROOT / "data/phase12", ROOT / "docs/phase-12", ROOT / "scripts/phase12.py", ROOT / "tests/test_phase12.py"):
            self.assertFalse(path.exists())

    def test_prior_analytical_artifacts_unchanged(self) -> None:
        prefixes = tuple(
            [f"data/phase{phase}" for phase in range(1, 10)]
            + [f"docs/phase-{phase}" for phase in range(0, 10)]
        )
        changed = [
            path for path in phase10.changed_paths()
            if any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)
        ]
        self.assertEqual(
            phase10.unapproved_paths(
                ROOT, changed, phase10.PHASE10_PRIOR_AUTHORIZED_SHA256,
            ),
            [],
        )

    def test_audit_remediation_baseline_exceptions_are_bounded(self) -> None:
        exceptions = phase10.PHASE10_PRIOR_AUTHORIZED_SHA256
        self.assertEqual(len(exceptions), 45)
        expected_counts = {
            "data/phase2/": 4, "docs/phase-2/": 3,
            "data/phase6/": 3, "docs/phase-6/": 2,
            "data/phase7/": 5, "docs/phase-7/": 3,
            "data/phase8/": 10, "docs/phase-8/": 5,
            "data/phase9/": 7, "docs/phase-9/": 3,
        }
        for prefix, expected in expected_counts.items():
            self.assertEqual(sum(path.startswith(prefix) for path in exceptions), expected, prefix)
        self.assertTrue({
            "data/phase2/raw/SUPPLEMENTAL_FACTS.csv",
            "data/phase6/processed/MONTHLY_LIQUIDITY_STRESS.csv",
            "data/phase7/processed/COVENANT_SUMMARY.csv",
            "data/phase8/processed/DYNAMIC_TEST_EVIDENCE.csv",
            "data/phase9/processed/DYNAMIC_RECOVERY_TEST_EVIDENCE.csv",
            "data/phase8/raw/MODEL_PERIOD_INPUTS.csv",
            "data/phase9/processed/PHASE8_BASELINE_VERIFICATION.csv",
        }.issubset(exceptions))
        self.assertFalse(any(
            path.startswith(("data/phase1/", "data/phase3/", "data/phase4/", "data/phase5/"))
            or path.startswith(("docs/phase-0/", "docs/phase-1/", "docs/phase-3/", "docs/phase-4/", "docs/phase-5/"))
            for path in exceptions
        ))
        self.assertFalse(any(path.startswith(("scripts/", "tests/")) for path in exceptions))
        self.assertEqual(set(phase10.authorized_prior_paths()), set(exceptions))

    def test_altered_reviewed_path_is_retained_for_baseline_rejection(self) -> None:
        reviewed = "data/phase8/processed/DYNAMIC_TEST_EVIDENCE.csv"
        self.assertNotIn(reviewed, phase10.isolation_baseline_paths([reviewed]))
        with mock.patch.object(phase10, "authorized_prior_paths", return_value=frozenset()):
            self.assertIn(reviewed, phase10.isolation_baseline_paths([reviewed]))

    def test_phase10_covenant_rollup_checks_missing_before_nonmeaningful(self) -> None:
        builder = (ROOT / "scripts" / "build-phase10.mjs").read_text(encoding="utf-8")
        line = next(
            item for item in builder.splitlines()
            if "cv.getRange(`V${row}`)" in item
        )
        self.assertLess(line.index('X${row}="INCOMPLETE"'), line.index('L${row}="N/M"'))
        self.assertIn('"N/D"', line)

    def test_unrelated_prior_phase_baseline_change_is_rejected(self) -> None:
        unrelated = "data/phase7/processed/UNRELATED_ANALYTICAL_CHANGE.csv"
        baseline_paths = phase10.isolation_baseline_paths([unrelated])
        self.assertIn(unrelated, baseline_paths)
        with self.assertRaisesRegex(
            phase10.Phase10Error,
            "Isolated source baseline differs analytically",
        ):
            phase10.require_clean_isolated_baseline(unrelated)

    def test_phase10_working_tree_is_unstaged(self) -> None:
        staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=ROOT, text=True, capture_output=True, check=True)
        self.assertEqual(staged.stdout.strip(), "")

    def test_prior_phase_validation_csvs_show_executed_dynamic_gates(self) -> None:
        for relative in (
            "data/phase8/processed/WORKBOOK_VALIDATION_RESULTS.csv",
            "data/phase9/processed/VALIDATION_RESULTS.csv",
        ):
            validation = rows(relative)
            dynamic = [row for row in validation if "dynamic" in row["test_name"].lower()]
            self.assertEqual(len(dynamic), 1, relative)
            self.assertEqual(dynamic[0]["status"], "PASS", relative)
            self.assertNotIn("not_run", dynamic[0]["observed"].lower(), relative)

    def test_libreoffice_validation_uses_disposable_copy(self) -> None:
        authoritative_hash = hashlib.sha256(phase10.MODEL.read_bytes()).hexdigest()
        observed: dict[str, Path] = {}

        def fake_run(mode: str, workbook: Path) -> dict[str, object]:
            observed["workbook"] = workbook
            workbook.write_bytes(workbook.read_bytes() + b"disposable-test")
            return {"engine": "LibreOffice 26.8.0.3"}

        with mock.patch.object(phase10.phase9, "run_libreoffice", side_effect=fake_run):
            phase10.libreoffice_report_on_copy("inspect")
        self.assertNotEqual(observed["workbook"], phase10.MODEL)
        self.assertFalse(observed["workbook"].exists())
        self.assertEqual(hashlib.sha256(phase10.MODEL.read_bytes()).hexdigest(), authoritative_hash)

    def test_read_only_phase10_validation_preserves_repository_files(self) -> None:
        protected = [
            phase10.MODEL,
            ROOT / "data/phase8/processed/WORKBOOK_VALIDATION_RESULTS.csv",
            ROOT / "data/phase9/processed/VALIDATION_RESULTS.csv",
            phase10.PHASE8_FINAL_DYNAMIC_EVIDENCE,
            phase10.PHASE9_FINAL_DYNAMIC_EVIDENCE,
            ROOT / "data/phase10/processed/DELIVERABLE_CONSISTENCY_RESULTS.csv",
            ROOT / "data/phase10/processed/VALIDATION_RESULTS.csv",
        ]
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
        engine = {
            "engine": "LibreOffice 26.8.0.3",
            "recovery_parity_failures": 0,
            "phase9_check_failures": 0,
        }
        controls = phase10.validate(engine, write_outputs=False)
        after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
        self.assertTrue(all(row["status"] == "PASS" for row in controls))
        lineage = next(
            row for row in controls
            if row["test_name"] == "approved Phase 9 lineage"
        )
        self.assertEqual(lineage["observed"], "approved ancestor confirmed")
        self.assertEqual(
            lineage["expected"], f"{phase10.APPROVED_PHASE9_COMMIT} is an ancestor",
        )
        self.assertEqual(before, after)

    def test_phase10_final_checks_do_not_own_phase8_or_phase9_validation_records(self) -> None:
        source = (ROOT / "scripts/phase10.py").read_text(encoding="utf-8")
        all_body = source.split("def all_workflow", 1)[1].split("def _test_count", 1)[0]
        self.assertEqual(all_body.count("write_outputs=False"), 2)
        self.assertNotIn("run_libreoffice", all_body)
        verify_body = source.split("def verify_isolated", 1)[1].split("def verify_commit_time", 1)[0]
        phase8_call = verify_body.split('validation_outputs["phase8"]', 1)[1].split(
            "fresh_records.extend(records)", 1,
        )[0]
        phase9_call = verify_body.split('validation_outputs["phase9"]', 1)[1].split(
            "fresh_records.extend(records)", 1,
        )[0]
        self.assertNotIn("WORKBOOK_VALIDATION_RESULTS.csv", phase8_call)
        self.assertNotIn("VALIDATION_RESULTS.csv", phase9_call)
        self.assertIn('"scripts/recalculate-phase9.py"', source)
        self.assertIn('"scripts/validate-phase9-excel.ps1"', source)

    def test_fresh_validation_difference_is_not_masked_by_restoration(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "data/phase8/processed/WORKBOOK_VALIDATION_RESULTS.csv"
            output.parent.mkdir(parents=True)
            output.write_text("status\nPASS\n", encoding="utf-8")

            def mutate(_command: list[str], **_kwargs: object) -> str:
                output.write_text("status\nFAIL\n", encoding="utf-8")
                return "validator completed"

            with mock.patch.object(phase10, "ROOT", root), mock.patch.object(
                phase10, "run_command", side_effect=mutate
            ):
                with self.assertRaisesRegex(phase10.Phase10Error, "Fresh phase8 validation output differs"):
                    phase10.run_fresh_validation(
                        "phase8",
                        ["fixture-validator"],
                        ("data/phase8/processed/WORKBOOK_VALIDATION_RESULTS.csv",),
                    )
            self.assertEqual(output.read_text(encoding="utf-8"), "status\nFAIL\n")

    def test_phase10_uses_current_regenerated_workbook_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "current.xlsx"
            target = Path(folder) / "baseline.xlsx"
            source.write_bytes(b"current-regenerated-phase9-workbook")
            with mock.patch.object(phase10, "MODEL", source):
                phase10.phase9_baseline(target)
            self.assertEqual(target.read_bytes(), source.read_bytes())
        source_text = (ROOT / "scripts/phase10.py").read_text(encoding="utf-8")
        baseline_body = source_text.split("def phase9_baseline", 1)[1].split("def build_workbook", 1)[0]
        self.assertNotIn("git\", \"show", baseline_body)

    def test_final_dynamic_evidence_is_phase10_owned_and_preserves_stage_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quanex-p10-dynamic-evidence-") as folder:
            root = Path(folder)
            stage8 = root / "phase8-stage.csv"
            stage9 = root / "phase9-stage.csv"
            final8 = root / "phase10-final-phase8.csv"
            final9 = root / "phase10-final-phase9.csv"
            stage8.write_bytes(b"phase8-stage-evidence")
            stage9.write_bytes(b"phase9-stage-evidence")

            def run_phase8(*, evidence_path: Path, tested_artifact: str) -> dict[str, object]:
                self.assertEqual(evidence_path, final8)
                self.assertEqual(tested_artifact, phase10.PHASE8_FINAL_DYNAMIC_ARTIFACT)
                evidence_path.write_bytes(b"phase10-final-phase8")
                return {"dynamic_status": "PASS"}

            def run_phase9(*, evidence_path: Path, tested_artifact: str) -> dict[str, object]:
                self.assertEqual(evidence_path, final9)
                self.assertEqual(tested_artifact, phase10.PHASE9_FINAL_DYNAMIC_ARTIFACT)
                evidence_path.write_bytes(b"phase10-final-phase9")
                return {"dynamic_status": "PASS"}

            with mock.patch.object(phase10.phase8, "DYNAMIC_EVIDENCE", stage8), mock.patch.object(
                phase10.phase9, "DYNAMIC_EVIDENCE", stage9,
            ), mock.patch.object(
                phase10, "PHASE8_FINAL_DYNAMIC_EVIDENCE", final8,
            ), mock.patch.object(
                phase10, "PHASE9_FINAL_DYNAMIC_EVIDENCE", final9,
            ), mock.patch.object(
                phase10.phase8, "dynamic", side_effect=run_phase8,
            ), mock.patch.object(
                phase10.phase9, "dynamic", side_effect=run_phase9,
            ):
                phase10.run_final_artifact_dynamic_evidence()

            self.assertEqual(stage8.read_bytes(), b"phase8-stage-evidence")
            self.assertEqual(stage9.read_bytes(), b"phase9-stage-evidence")
            self.assertEqual(final8.read_bytes(), b"phase10-final-phase8")
            self.assertEqual(final9.read_bytes(), b"phase10-final-phase9")

    def test_final_dynamic_evidence_gate_rejects_mismatched_artifact(self) -> None:
        states = {
            "phase8": ("FAIL", "custom evidence does not identify current workbook"),
            "phase9": ("PASS", "73 required cases passed"),
        }
        with mock.patch.object(
            phase10, "final_artifact_dynamic_evidence_state", return_value=states,
        ), self.assertRaisesRegex(
            phase10.Phase10Error, "does not identify current workbook",
        ):
            phase10.require_final_artifact_dynamic_evidence()

    def test_excel_harnesses_copy_before_open_and_save_elsewhere(self) -> None:
        for name in ("validate-phase8-excel.ps1", "validate-phase9-excel.ps1"):
            text = (ROOT / "scripts" / name).read_text(encoding="utf-8-sig")
            self.assertIn("Copy-Item -LiteralPath $source", text)
            self.assertIn("return $books.Open($path)", text)
            self.assertRegex(text, r"Open-Workbook \$(excel|application) \$candidate")
            self.assertRegex(text, r"Open-Workbook \$(excel|application) \$saved")
            self.assertNotIn("Workbooks.Open($source)", text)
            self.assertIn("SaveAs($saved", text)
        phase8_text = (ROOT / "scripts" / "validate-phase8-excel.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("$value -is [string]", phase8_text)
        self.assertIn("$range.Value2 = [double]$value", phase8_text)
        self.assertIn("Assert-CapturesCurrent", phase8_text)

    def test_isolated_workspace_has_independent_files_and_git_metadata(self) -> None:
        holder, destination = phase10.isolated_workspace()
        try:
            self.assertTrue((destination / ".git").is_dir())
            self.assertEqual(
                hashlib.sha256((destination / "model/Quanex_Credit_Underwriting.xlsx").read_bytes()).hexdigest(),
                hashlib.sha256(phase10.MODEL.read_bytes()).hexdigest(),
            )
            root_readme = hashlib.sha256((ROOT / "README.md").read_bytes()).hexdigest()
            (destination / "README.md").write_bytes((destination / "README.md").read_bytes() + b"\n")
            self.assertEqual(hashlib.sha256((ROOT / "README.md").read_bytes()).hexdigest(), root_readme)
        finally:
            holder.cleanup()

    def test_repository_manifest_covers_authoritative_validation_surface(self) -> None:
        manifest = phase10.repository_manifest()
        for relative in (
            "model/Quanex_Credit_Underwriting.xlsx",
            "data/phase8/processed/WORKBOOK_VALIDATION_RESULTS.csv",
            "data/phase9/processed/VALIDATION_RESULTS.csv",
            "data/phase10/processed/FINAL_WORKBOOK_PHASE8_DYNAMIC_EVIDENCE.csv",
            "data/phase10/processed/FINAL_WORKBOOK_PHASE9_DYNAMIC_EVIDENCE.csv",
            "data/phase10/processed/VALIDATION_RESULTS.csv",
        ):
            self.assertIn(relative, manifest)
        self.assertFalse(any(path.startswith(".git/") for path in manifest))

    def test_repository_pdf_attributes_disable_text_filters(self) -> None:
        self.assertEqual((ROOT / ".gitattributes").read_text(encoding="utf-8"), "*.pdf -diff -merge -text\n")
        result = subprocess.run(
            ["git", "check-attr", "diff", "merge", "text", "--", "reports/credit_memo.pdf", "reports/committee_brief.pdf"],
            cwd=ROOT, text=True, capture_output=True, check=True,
        )
        observed = set(result.stdout.splitlines())
        expected = {
            f"{path}: {attribute}: unset"
            for path in ("reports/credit_memo.pdf", "reports/committee_brief.pdf")
            for attribute in ("diff", "merge", "text")
        }
        self.assertEqual(observed, expected)


if __name__ == "__main__":
    unittest.main()
