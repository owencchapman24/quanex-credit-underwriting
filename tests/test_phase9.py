"""Decision-relevant tests for Phase 9 recovery, risk and monitoring."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import phase9  # noqa: E402

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships", "p": "http://schemas.openxmlformats.org/package/2006/relationships"}


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class Phase9Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assumptions = rows(phase9.RAW / "RECOVERY_ASSUMPTIONS.csv")
        cls.decisions = rows(phase9.RAW / "OWNER_REVIEW_DECISIONS.csv")
        cls.cases = rows(phase9.PROCESSED / "RECOVERY_CASE_REGISTER.csv")
        cls.waterfall = rows(phase9.PROCESSED / "RECOVERY_WATERFALL.csv")
        cls.claims = rows(phase9.PROCESSED / "CLAIM_PRIORITY_REGISTER.csv")
        cls.facility = rows(phase9.PROCESSED / "FACILITY_RECOVERY_ASSESSMENT.csv")
        cls.risk = rows(phase9.PROCESSED / "BORROWER_RISK_ASSESSMENT.csv")
        cls.monitors = rows(phase9.PROCESSED / "MONITORING_SCHEDULE.csv")
        cls.ledger = rows(phase9.DOCS / "SOURCE_LEDGER.csv")
        cls.validation = rows(phase9.PROCESSED / "VALIDATION_RESULTS.csv")
        cls.archive = zipfile.ZipFile(phase9.MODEL)
        workbook = ET.fromstring(cls.archive.read("xl/workbook.xml"))
        rels = ET.fromstring(cls.archive.read("xl/_rels/workbook.xml.rels"))
        targets = {item.attrib["Id"]: item.attrib["Target"] for item in rels.findall("p:Relationship", NS)}
        cls.sheet_paths = {}
        for item in workbook.findall("m:sheets/m:sheet", NS):
            target = targets[item.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]].lstrip("/")
            cls.sheet_paths[item.attrib["name"]] = target if target.startswith("xl/") else f"xl/{target}"
        styles = ET.fromstring(cls.archive.read("xl/styles.xml"))
        cls.custom_formats = {
            int(item.attrib["numFmtId"]): item.attrib["formatCode"]
            for item in styles.findall("m:numFmts/m:numFmt", NS)
        }
        cls.cell_formats = [int(item.attrib.get("numFmtId", "0")) for item in styles.findall("m:cellXfs/m:xf", NS)]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.archive.close()

    @classmethod
    def sheet_text(cls, sheet: str) -> str:
        return cls.archive.read(cls.sheet_paths[sheet]).decode("utf-8")

    @classmethod
    def formula(cls, sheet: str, address: str) -> str:
        root = ET.fromstring(cls.archive.read(cls.sheet_paths[sheet]))
        cell = root.find(f".//m:c[@r='{address}']", NS)
        if cell is None:
            return ""
        formula = cell.find("m:f", NS)
        return "" if formula is None else formula.text or ""

    @classmethod
    def cell_xml(cls, sheet: str, address: str) -> ET.Element:
        root = ET.fromstring(cls.archive.read(cls.sheet_paths[sheet]))
        cell = root.find(f".//m:c[@r='{address}']", NS)
        if cell is None:
            raise AssertionError(f"Missing cell {sheet}!{address}")
        return cell

    @classmethod
    def number_format(cls, sheet: str, address: str) -> str:
        cell = cls.cell_xml(sheet, address)
        style_id = int(cell.attrib.get("s", "0"))
        num_fmt_id = cls.cell_formats[style_id]
        return cls.custom_formats.get(num_fmt_id, str(num_fmt_id))

    def test_01_checkpoint_and_cutoff(self) -> None:
        checkpoint = rows(phase9.RAW / "STARTING_CHECKPOINT.csv")[0]
        self.assertEqual(checkpoint["approved_phase8_commit"], phase9.APPROVED_PHASE8_COMMIT)
        self.assertEqual(checkpoint["phase8_normalized_fingerprint"], phase9.PHASE8_FINGERPRINT)
        self.assertEqual(checkpoint["information_cutoff"], "2025-12-15")

    def test_02_assumption_register_complete_and_classified(self) -> None:
        self.assertEqual(len(self.assumptions), 28)
        self.assertEqual(len({r["assumption_id"] for r in self.assumptions}), 28)
        self.assertTrue(all(r["classification"] in {"reported", "calculated", "proposed_assumption", "not_determinable"} for r in self.assumptions))
        self.assertTrue(all(r["source_or_ids"] and r["rationale"] and r["limitation"] for r in self.assumptions))

    def test_03_owner_review_is_complete_without_changing_classification(self) -> None:
        proposed = [r for r in self.assumptions if r["classification"] == "proposed_assumption"]
        self.assertTrue(proposed)
        self.assertTrue(all(r["review_status"] == phase9.REVIEW for r in proposed))
        self.assertEqual(len(self.decisions), 16)
        self.assertTrue(all(r["review_status"] == phase9.REVIEW for r in self.decisions))
        self.assertEqual(phase9.REVIEW, "owner_reviewed")

    def test_04_recovery_date_and_exposure(self) -> None:
        self.assertTrue(all(r["valuation_date"] == "2027-12-31" for r in self.cases))
        self.assertTrue(all(r["scenario_id"] == "SEVERE_UNMITIGATED" for r in self.cases))
        claims = {r["claim_name"]: r["amount"] for r in self.claims}
        self.assertEqual(Decimal(claims["Term loan principal"]), Decimal("551.65625"))
        self.assertEqual(Decimal(claims["Revolver principal"]), Decimal("293.8"))

    def test_05_recovery_methods_are_alternatives(self) -> None:
        self.assertEqual({r["method"] for r in self.cases}, {"going_concern", "asset_realization"})
        self.assertEqual(len(self.cases), 6)
        self.assertIn("alternatives", self.facility[0]["limitations"].lower())

    def test_06_every_case_has_required_metadata(self) -> None:
        required = {"valuation_date", "scenario_id", "facility_claim", "valuation_basis", "official_status", "review_status"}
        self.assertTrue(all(all(r[field] for field in required) for r in self.cases))

    def test_07_waterfall_arithmetic_and_no_double_deductions(self) -> None:
        self.assertEqual(len(self.waterfall), 42)
        for case in self.cases:
            case_rows = [r for r in self.waterfall if r["case_id"] == case["case_id"]]
            self.assertEqual(sum(r["step"] == "less_realization_costs" for r in case_rows), 1)
            self.assertEqual(sum(r["step"] == "less_other_funded_obligations" for r in case_rows), 1)
            self.assertEqual(len(case_rows), 7)

    def test_08_nonnegative_and_claim_capped(self) -> None:
        for case in self.cases:
            self.assertGreaterEqual(Decimal(case["illustrative_bank_allocation"]), 0)
            self.assertLessEqual(Decimal(case["illustrative_bank_allocation"]), Decimal(case["facility_claim"]))
            self.assertLessEqual(Decimal(case["illustrative_facility_recovery_percent"]), 100)

    def test_09_goodwill_and_intangibles_excluded(self) -> None:
        decision = next(r for r in self.decisions if r["decision_id"] == "P9D-010")
        self.assertIn("zero", decision["proposed_treatment"].lower())
        shared = self.archive.read("xl/sharedStrings.xml").decode("utf-8")
        self.assertIn("Goodwill", shared)
        self.assertIn("Intangible", shared)

    def test_10_unknown_claims_are_not_zero(self) -> None:
        unknown = next(r for r in self.claims if r["claim_id"] == "P9CL-005")
        self.assertEqual(unknown["amount"], "N/D")

    def test_10a_owner_revised_recovery_terminology(self) -> None:
        p9d11 = next(r for r in self.decisions if r["decision_id"] == "P9D-011")
        p9d12 = next(r for r in self.decisions if r["decision_id"] == "P9D-012")
        self.assertIn("other-funded-obligations", p9d11["judgment"].lower())
        self.assertIn("no legal ranking", p9d11["proposed_treatment"].lower())
        self.assertIn("full consolidated-access ceiling", p9d12["judgment"].lower())
        self.assertIn("not expected lender access", p9d12["proposed_treatment"].lower())
        retained = next(r for r in self.claims if r["claim_id"] == "P9CL-004")
        self.assertEqual(retained["priority_status"], "ranking_not_determinable_deducted_for_sensitivity")

    def test_11_official_recovery_is_not_determinable(self) -> None:
        self.assertEqual(self.facility[0]["official_facility_recovery"], "N/D")
        for concept in ("guarantor", "collateral", "priority", "appraisal", "access"):
            self.assertIn(concept, self.facility[0]["reasons_not_determinable"].lower())

    def test_12_maturity_sensitivity_separate(self) -> None:
        self.assertEqual(self.facility[0]["primary_recovery_date"], "2027-12-31")
        self.assertEqual(self.facility[0]["maturity_sensitivity_date"], "2031-01-31")
        self.assertIn("alternatives", self.facility[0]["limitations"].lower())

    def test_13_risk_grade_uses_approved_scale(self) -> None:
        self.assertEqual(self.risk[0]["provisional_grade"], "Elevated")
        self.assertEqual(self.risk[0]["review_status"], phase9.REVIEW)
        self.assertEqual(self.risk[0]["scale_status"], "approved_five_grade_scale")

    def test_14_grade_rationale_is_complete(self) -> None:
        required = {"base_case", "moderate_case", "severe_case", "execution_quality", "management_dependence", "information_limits", "next_better_grade_case", "next_worse_grade_case", "change_evidence"}
        self.assertTrue(all(self.risk[0][field] for field in required))

    def test_15_default_and_recovery_are_separate(self) -> None:
        self.assertIn("default risk only", self.risk[0]["default_recovery_separation"])
        self.assertIn("do not improve", self.risk[0]["default_recovery_separation"])

    def test_16_no_pd_or_agency_mapping_fields(self) -> None:
        self.assertFalse({"probability_of_default", "agency_rating", "external_rating_mapping"}.intersection(self.risk[0]))

    def test_17_monitoring_maps_all_13_drivers(self) -> None:
        mapped = {item for row in self.monitors for item in row["risk_driver_ids"].split(";") if item.startswith("DRV-")}
        self.assertEqual(mapped, {f"DRV-{i:03d}" for i in range(1, 14)})

    def test_18_monitoring_records_complete(self) -> None:
        self.assertEqual(len(self.monitors), 26)
        required = ("metric_or_event", "exact_definition", "frequency", "required_report_or_source", "warning_threshold", "lender_action", "escalation_timing", "severity_classification", "review_status")
        self.assertTrue(all(all(r[field] for field in required) for r in self.monitors))

    def test_19_warning_and_contractual_thresholds_distinct(self) -> None:
        leverage = next(r for r in self.monitors if r["monitor_id"] == "MON-013")
        self.assertNotEqual(leverage["warning_threshold"], leverage["covenant_or_contractual_threshold"])

    def test_20_escalation_classes_complete(self) -> None:
        classes = {r["severity_classification"] for r in rows(phase9.PROCESSED / "ESCALATION_ACTION_REGISTER.csv")}
        self.assertEqual(classes, {"analyst_warning", "reporting_exception", "contractual_covenant_breach", "payment_default", "liquidity_failure", "maturity_refinancing_risk", "legal_or_documentation_exception"})

    def test_21_maturity_monitoring_starts_early(self) -> None:
        item = next(r for r in self.monitors if r["monitor_id"] == "MON-026")
        self.assertIn("24 months", item["warning_threshold"])
        self.assertIn("12 months", item["warning_threshold"])

    def test_22_source_ledger_and_cutoff(self) -> None:
        self.assertEqual(len(self.ledger), 12)
        self.assertTrue(all(r["cutoff_status"] == "within_cutoff" for r in self.ledger))
        self.assertTrue(all((ROOT / r["source_path"]).is_file() for r in self.ledger))

    def test_23_validation_controls_pass(self) -> None:
        self.assertEqual(len(self.validation), 37)
        self.assertTrue(all(r["status"] == "PASS" for r in self.validation))

    def test_24_sheet_order_and_external_links(self) -> None:
        self.assertEqual(list(self.sheet_paths), ["Credit Summary", "Assumptions", "Scenario Comparison", "Historicals", "Credit Adjustments", "Transaction", "Forecast", "Debt Schedule", "Liquidity", "Covenants", "Recovery", "Sensitivities", "Sources", "Checks"])
        self.assertFalse([n for n in self.archive.namelist() if n.startswith("xl/externalLinks/")])

    def test_24a_recovery_multiple_inputs_are_numeric_and_not_percent_formatted(self) -> None:
        for address, expected in (("I32", Decimal("3")), ("J32", Decimal("4")), ("K32", Decimal("5"))):
            cell = self.cell_xml("Assumptions", address)
            value = cell.find("m:v", NS)
            self.assertIsNotNone(value)
            self.assertEqual(Decimal(value.text or "0"), expected)
            number_format = self.number_format("Assumptions", address)
            self.assertIn("x", number_format.lower())
            self.assertNotIn("%", number_format)

    def test_25_recovery_contains_native_formulas(self) -> None:
        text = self.sheet_text("Recovery")
        self.assertGreaterEqual(text.count("<f"), 70)
        self.assertIn("Assumptions", text)

    def test_26_phase8_compatibility_formula_preserved(self) -> None:
        self.assertTrue(self.formula("Checks", "G20").startswith("IF(OR("))
        self.assertNotIn("COUNTIF({", self.formula("Checks", "G20").upper())

    def test_27_checks_remain_terminal(self) -> None:
        for sheet, path in self.sheet_paths.items():
            if sheet != "Checks":
                self.assertNotIn("Checks!", self.archive.read(path).decode("utf-8"), sheet)

    def test_28_single_scenario_selector_preserved(self) -> None:
        root = ET.fromstring(self.archive.read(self.sheet_paths["Assumptions"]))
        validations = root.findall(".//m:dataValidation", NS)
        self.assertEqual(len(validations), 1)
        self.assertEqual(validations[0].attrib.get("sqref"), "D4")

    def test_29_prior_anchors_unchanged(self) -> None:
        parity = rows(ROOT / "data" / "phase8" / "processed" / "FORMULA_PARITY_RESULTS.csv")
        values = {r["metric"]: Decimal(r["excel_value"]) for r in parity}
        self.assertEqual(values["fy2024_lender_base_ebitda"], Decimal("179.358"))
        self.assertEqual(values["fy2025_lender_base_ebitda"], Decimal("225.344"))
        self.assertEqual(values["opening_total_funded_debt"], Decimal("727.51671875"))
        self.assertEqual(values["selected_maturity_gap"], Decimal("324.779705120148"))

    def test_30_only_permitted_prior_phase_artifacts_changed(self) -> None:
        result = subprocess.run(["git", "diff", "--name-only", "--", "data/phase1", "data/phase2", "data/phase3", "data/phase4", "data/phase5", "data/phase6", "data/phase7", "data/phase8", "docs/phase-0", "docs/phase-1", "docs/phase-2", "docs/phase-3", "docs/phase-4", "docs/phase-5", "docs/phase-6", "docs/phase-7", "docs/phase-8"], cwd=ROOT, text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout.strip(), "")

    def test_31_dynamic_workbook_behavior(self) -> None:
        report = phase9.dynamic()
        self.assertEqual(report["dynamic_status"], "PASS")
        self.assertEqual(report["test_count"], 37)
        self.assertEqual(report["phase9_check_failures"], 0)
        self.assertEqual(report["recovery_parity_failures"], 0)

    def test_32_deterministic_data_regeneration(self) -> None:
        tracked = [phase9.RAW / "RECOVERY_ASSUMPTIONS.csv", phase9.PROCESSED / "RECOVERY_CASE_REGISTER.csv", phase9.PROCESSED / "MONITORING_SCHEDULE.csv", phase9.PROCESSED / "WORKBOOK_INPUTS.json"]
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
        phase9.build_data()
        after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
