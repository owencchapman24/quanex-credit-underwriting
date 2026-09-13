from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
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

    def test_forecast_horizons_are_explicit(self) -> None:
        annual = self.metric[("fy2026_lender_ebitda", "BASE")]
        self.assertEqual((annual["measurement_horizon"], annual["measurement_basis"]), ("FY2026", "annual_fiscal_period"))
        for name in ("modeled_operating_cash", "cfads", "cash_interest", "scheduled_principal", "ecf_sweep_realized"):
            row = self.metric[(name, "BASE")]
            self.assertEqual(row["measurement_horizon"], "2026-02-01 through 2031-01-31")
            self.assertEqual(row["measurement_basis"], "cumulative_model_period")
        self.assertEqual(self.metric[("minimum_cash_interest_coverage", "BASE")]["measurement_basis"], "minimum_over_forecast")
        self.assertEqual(self.metric[("unsupported_maturity_gap", "BASE")]["measurement_basis"], "point_in_time_bank_debt_maturity_gap")

    def test_moderate_breach_anchors(self) -> None:
        expected = {
            ("maximum_gross_leverage", "MODERATE_UNMITIGATED"): "4.489250193362221",
            ("maximum_gross_leverage", "MODERATE_MITIGATED"): "4.467006108046972",
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
        rationale = "The proposed refinancing is not justified by faster same-horizon debt reduction. It is supportable only for its maturity extension, liquidity structure, amortization, lender protections, and monitoring package, subject to acceptable final economics and documentation."
        counter = "At the July 31, 2029 common horizon, the selected structure leaves approximately $19.4 million more total funded debt than retaining the existing facilities. Quanex could therefore avoid refinancing fees and near-term debt expansion by retaining or amending its current financing. The lower selected maturity gap is achieved partly because the proposed facility remains outstanding approximately 18 months longer."
        moderate = "The proposed covenant is intended to create early lender intervention while liquidity and payment capacity remain available. Conditional approval accepts the possibility of an early moderate-case covenant breach only because the structure preserves substantial liquidity, separates breach from payment failure, mandates reporting and corrective action, and does not assume an automatic waiver."
        for text in (memo, brief):
            self.assertIn(rationale, text)
            self.assertIn(counter, text)
            self.assertIn(moderate, text)

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
        self.assertEqual(meta["formula_count"], 2902)
        self.assertEqual(meta["chart_count"], 7)
        self.assertEqual(meta["saved_scenario"], "Base")
        self.assertEqual(meta["external_links"], 0)
        self.assertEqual(meta["formula_errors"], 0)
        self.assertEqual(meta["checks_dependencies"], 0)

    def test_credit_summary_content(self) -> None:
        self.assertIn("Conditional Approval", phase10.xlsx_cell_text("Credit Summary", "C5"))
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
        result = subprocess.run(
            ["git", "diff", "--name-only", "--", "data/phase1", "data/phase2", "data/phase3", "data/phase4",
             "data/phase5", "data/phase6", "data/phase7", "data/phase8", "data/phase9", "docs/phase-0",
             "docs/phase-1", "docs/phase-2", "docs/phase-3", "docs/phase-4", "docs/phase-5", "docs/phase-6",
             "docs/phase-7", "docs/phase-8", "docs/phase-9"],
            cwd=ROOT, text=True, capture_output=True, check=True,
        )
        self.assertEqual(result.stdout.strip(), "")

    def test_phase10_working_tree_is_unstaged(self) -> None:
        staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=ROOT, text=True, capture_output=True, check=True)
        self.assertEqual(staged.stdout.strip(), "")

    def test_prior_phase_validation_csvs_match_committed_head(self) -> None:
        for relative in (
            "data/phase8/processed/WORKBOOK_VALIDATION_RESULTS.csv",
            "data/phase9/processed/VALIDATION_RESULTS.csv",
        ):
            result = subprocess.run(
                ["git", "diff", "--quiet", "HEAD", "--", relative],
                cwd=ROOT,
            )
            self.assertEqual(result.returncode, 0, relative)

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
        self.assertEqual(before, after)

    def test_excel_harnesses_copy_before_open_and_save_elsewhere(self) -> None:
        for name in ("validate-phase8-excel.ps1", "validate-phase9-excel.ps1"):
            text = (ROOT / "scripts" / name).read_text(encoding="utf-8-sig")
            self.assertIn("Copy-Item -LiteralPath $source", text)
            self.assertRegex(text, r"Workbooks\.Open\(\$(candidate|saved)\)")
            self.assertNotIn("Workbooks.Open($source)", text)
            self.assertIn("SaveAs($saved", text)

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
