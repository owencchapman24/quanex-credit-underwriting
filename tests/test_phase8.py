"""Decision-relevant workbook tests for Phase 8."""

from __future__ import annotations

import csv
import subprocess
import sys
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import phase8  # noqa: E402


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"m": MAIN_NS, "r": REL_NS, "p": PKG_NS}


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class Phase8WorkbookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.archive = zipfile.ZipFile(phase8.MODEL)
        cls.workbook = ET.fromstring(cls.archive.read("xl/workbook.xml"))
        rels = ET.fromstring(cls.archive.read("xl/_rels/workbook.xml.rels"))
        cls.rel_targets = {
            item.attrib["Id"]: item.attrib["Target"] for item in rels.findall("p:Relationship", NS)
        }
        cls.sheet_paths: dict[str, str] = {}
        for item in cls.workbook.findall("m:sheets/m:sheet", NS):
            target = cls.rel_targets[item.attrib[f"{{{REL_NS}}}id"]].lstrip("/")
            cls.sheet_paths[item.attrib["name"]] = target if target.startswith("xl/") else f"xl/{target}"
        cls.shared = []
        if "xl/sharedStrings.xml" in cls.archive.namelist():
            root = ET.fromstring(cls.archive.read("xl/sharedStrings.xml"))
            cls.shared = ["".join(node.itertext()) for node in root.findall("m:si", NS)]
        cls.parity = rows(phase8.PROCESSED / "FORMULA_PARITY_RESULTS.csv")
        cls.validations = rows(phase8.PROCESSED / "WORKBOOK_VALIDATION_RESULTS.csv")
        cls.captures = rows(phase8.PROCESSED / "SCENARIO_CAPTURE_RESULTS.csv")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.archive.close()

    @classmethod
    def xml(cls, sheet: str) -> ET.Element:
        return ET.fromstring(cls.archive.read(cls.sheet_paths[sheet]))

    @classmethod
    def xml_text(cls, sheet: str) -> str:
        return cls.archive.read(cls.sheet_paths[sheet]).decode("utf-8")

    @classmethod
    def cell(cls, sheet: str, address: str) -> ET.Element:
        item = cls.xml(sheet).find(f".//m:c[@r='{address}']", NS)
        if item is None:
            raise AssertionError(f"Missing {sheet}!{address}")
        return item

    @classmethod
    def formula(cls, sheet: str, address: str) -> str:
        formula = cls.cell(sheet, address).find("m:f", NS)
        return "" if formula is None else formula.text or ""

    @classmethod
    def displayed_value(cls, sheet: str, address: str) -> str:
        item = cls.cell(sheet, address)
        value = item.find("m:v", NS)
        if value is None:
            return ""
        if item.attrib.get("t") == "s":
            return cls.shared[int(value.text or "0")]
        return value.text or ""

    @classmethod
    def font_color(cls, sheet: str, address: str) -> str:
        style_index = int(cls.cell(sheet, address).attrib.get("s", "0"))
        styles = ET.fromstring(cls.archive.read("xl/styles.xml"))
        xfs = styles.find("m:cellXfs", NS)
        fonts = styles.find("m:fonts", NS)
        assert xfs is not None and fonts is not None
        font_id = int(list(xfs)[style_index].attrib.get("fontId", "0"))
        color = list(fonts)[font_id].find("m:color", NS)
        return "" if color is None else color.attrib.get("rgb", "")[-6:].upper()

    def test_01_starting_checkpoint(self) -> None:
        checkpoint = rows(phase8.RAW / "STARTING_CHECKPOINT.csv")[0]
        self.assertEqual(checkpoint["repository"], "owencchapman24/quanex-credit-underwriting")
        self.assertEqual(checkpoint["branch"], "main")
        self.assertEqual(checkpoint["approved_phase8_commit"], phase8.APPROVED_PHASE8_COMMIT)
        self.assertIn(checkpoint["local_head"], {phase8.APPROVED_PHASE7_COMMIT, phase8.APPROVED_PHASE8_COMMIT})
        self.assertEqual(checkpoint["information_cutoff"], "2025-12-15")

    def test_02_workbook_opens_and_has_exact_sheet_order(self) -> None:
        self.assertEqual(list(self.sheet_paths), [
            "Credit Summary", "Assumptions", "Scenario Comparison", "Historicals",
            "Credit Adjustments", "Transaction", "Forecast", "Debt Schedule",
            "Liquidity", "Covenants", "Recovery", "Sensitivities", "Sources", "Checks",
        ])

    def test_03_no_external_workbook_links(self) -> None:
        self.assertFalse([name for name in self.archive.namelist() if name.startswith("xl/externalLinks/")])

    def test_03a_sheet14_is_checks_and_formulas_are_excel_compatible(self) -> None:
        structure = phase8.workbook_structure()
        self.assertEqual(structure["sheet_paths"]["Checks"], "xl/worksheets/sheet14.xml")
        if (ROOT / "data" / "phase9").exists():
            self.assertGreaterEqual(structure["formula_counts_by_sheet"]["Checks"], 66)
        else:
            self.assertEqual(structure["formula_counts_by_sheet"]["Checks"], 66)
        self.assertEqual(structure["excel_formula_compatibility_issues"], [])
        selector_check = self.formula("Checks", "G20")
        self.assertTrue(selector_check.startswith("IF(OR("))
        self.assertNotIn("COUNTIF({", selector_check.upper())

    def test_04_native_formula_population(self) -> None:
        if (ROOT / "data" / "phase9").exists():
            self.assertGreaterEqual(phase8.workbook_structure()["formula_count"], 2742)
        else:
            self.assertEqual(phase8.workbook_structure()["formula_count"], 2742)
        for sheet in ("Transaction", "Forecast", "Debt Schedule", "Liquidity", "Covenants"):
            self.assertIn("<f", self.xml_text(sheet), sheet)

    def test_05_summary_links_to_supporting_schedules(self) -> None:
        self.assertIn("Transaction", self.formula("Credit Summary", "D13"))
        self.assertIn("Scenario Comparison", self.formula("Credit Summary", "D17"))
        self.assertIn("Scenario Comparison", self.formula("Credit Summary", "D28"))

    def test_06_single_selector_and_validation_options(self) -> None:
        validations = self.xml("Assumptions").findall(".//m:dataValidation", NS)
        self.assertEqual(len(validations), 1)
        self.assertEqual(validations[0].attrib.get("sqref"), "D4")
        self.assertEqual(self.displayed_value("Assumptions", "D5"), "BASE")
        source = (ROOT / "scripts" / "build-phase8.mjs").read_text(encoding="utf-8")
        for scenario, _ in phase8.SCENARIOS:
            self.assertIn(scenario, source)

    def test_07_active_scenario_links_appear_on_required_sheets(self) -> None:
        for sheet, cell in {
            "Credit Summary": "D4", "Scenario Comparison": "D3", "Forecast": "D4",
            "Debt Schedule": "D4", "Liquidity": "D4", "Covenants": "D4", "Sensitivities": "D4",
        }.items():
            self.assertIn("Assumptions", self.formula(sheet, cell), sheet)

    def test_08_historicals_are_not_scenario_driven(self) -> None:
        self.assertNotIn("Assumptions", self.xml_text("Historicals"))

    def test_09_sources_and_uses_is_formula_driven(self) -> None:
        self.assertIn("SUM", self.formula("Transaction", "D11"))
        self.assertIn("G10", self.formula("Transaction", "D12"))

    def test_10_debt_roll_forward_formulas_copy_across_horizon(self) -> None:
        for address in ("I12", "I30", "I47", "N12", "N30", "N47"):
            self.assertTrue(self.formula("Debt Schedule", address), address)

    def test_11_cash_roll_forward_formulas_copy_across_horizon(self) -> None:
        for address in ("N13", "N30", "N48", "Q13", "Q30", "Q48"):
            self.assertIn("Debt Schedule", self.formula("Liquidity", address), address)

    def test_11a_forecast_signs_and_cash_flow_construction(self) -> None:
        self.assertEqual(self.formula("Forecast", "D17"), "D14+D16")
        self.assertIn("D21", self.formula("Forecast", "D24"))
        self.assertNotIn("D20", self.formula("Forecast", "D24"))
        self.assertEqual(self.formula("Forecast", "D25"), "D24+D20")

    def test_12_covenant_step_downs_and_boundary_formulas(self) -> None:
        formula = self.formula("Covenants", "J8")
        self.assertIn("DATE(2027,10,31)", formula)
        self.assertIn("DATE(2028,10,31)", formula)
        self.assertIn(">J8", self.formula("Covenants", "L8"))

    def test_13_nd_and_nm_are_distinct(self) -> None:
        formula = self.formula("Covenants", "O12")
        self.assertIn('"N/D"', formula)
        self.assertIn('"N/M"', formula)

    def test_14_negative_ebitda_cannot_produce_favorable_leverage(self) -> None:
        self.assertIn("G8<=0", self.formula("Covenants", "H8"))
        self.assertIn('"N/M"', self.formula("Covenants", "I8"))

    def test_15_snapshot_stale_formula_uses_current_signature(self) -> None:
        self.assertIn("AC12-AD12", self.formula("Scenario Comparison", "AE12"))
        self.assertEqual(len(self.captures), 9)

    def test_16_all_in_liquidity_includes_opening_position(self) -> None:
        self.assertEqual(self.formula("Liquidity", "D9"), "MIN(D6,D7)")

    def test_17_unpaid_obligations_remain_visible(self) -> None:
        self.assertIn("MAX(0,-W12)", self.formula("Debt Schedule", "AC12"))
        self.assertIn("Debt Schedule", self.formula("Liquidity", "W13"))

    def test_18_checks_is_terminal(self) -> None:
        structure = phase8.workbook_structure()
        self.assertFalse(structure["checks_dependencies"])

    def test_19_print_areas_and_repeated_headers(self) -> None:
        names = self.workbook.findall("m:definedNames/m:definedName", NS)
        print_areas = [item for item in names if item.attrib.get("name") == "_xlnm.Print_Area"]
        print_titles = [item for item in names if item.attrib.get("name") == "_xlnm.Print_Titles"]
        self.assertEqual(len(print_areas), 14)
        self.assertGreaterEqual(len(print_titles), 8)

    def test_20_freeze_panes_exist_where_useful(self) -> None:
        for sheet in ("Assumptions", "Scenario Comparison", "Historicals", "Forecast", "Debt Schedule", "Liquidity", "Covenants", "Sources", "Checks"):
            self.assertIsNotNone(self.xml(sheet).find(".//m:pane", NS), sheet)

    def test_21_native_charts_have_bound_series(self) -> None:
        chart_paths = [name for name in self.archive.namelist() if name.startswith("xl/charts/chart") and name.endswith(".xml")]
        self.assertGreaterEqual(len(chart_paths), 5)
        for path in chart_paths:
            text = self.archive.read(path).decode("utf-8")
            self.assertIn("<c:ser", text, path)
            self.assertIn("<c:f>", text, path)

    def test_22_formula_colors_follow_model_convention(self) -> None:
        self.assertEqual(self.font_color("Assumptions", "D12"), "0000FF")
        self.assertEqual(self.font_color("Debt Schedule", "I12"), "008000")
        self.assertEqual(self.font_color("Checks", "G7"), "000000")

    def test_23_calculation_mode_and_cached_values(self) -> None:
        structure = phase8.workbook_structure()
        self.assertIn(structure["calculation_mode"], {"auto", "automatic", ""})
        self.assertFalse(structure["formula_errors"])

    def test_24_python_to_workbook_parity(self) -> None:
        self.assertEqual(len(self.parity), 15)
        self.assertTrue(all(row["status"] == "PASS" for row in self.parity))
        values = {row["metric"]: Decimal(row["excel_value"]) for row in self.parity}
        self.assertEqual(values["fy2025_lender_base_ebitda"], Decimal("225.344"))
        self.assertLess(abs(values["selected_maturity_gap"] - Decimal("324.779705120148")), phase8.TOLERANCE)

    def test_25_final_workbook_is_saved_in_base(self) -> None:
        self.assertEqual(self.displayed_value("Assumptions", "D4"), "Base")

    def test_26_recovery_remains_pending_phase9(self) -> None:
        text = "\n".join(self.shared)
        if (ROOT / "data" / "phase9").exists():
            self.assertIn("Official facility recovery remains N/D", text)
            self.assertIn("Recovery analysis", text)
        else:
            self.assertIn("Pending Phase 9", text)
            self.assertIn("No recovery percentage presented", text)
            self.assertNotIn("recovery percentage calculated", text.lower())

    def test_27_source_ledger_respects_cutoff(self) -> None:
        ledger = rows(phase8.DOCS / "SOURCE_LEDGER.csv")
        self.assertTrue(ledger)
        self.assertTrue(all(row["cutoff_status"] == "within_cutoff" for row in ledger))
        evidence = rows(ROOT / "docs" / "phase-0" / "EVIDENCE_INVENTORY.csv")
        self.assertTrue(all(row["publication_or_filing_date"] <= "2025-12-15" for row in evidence))

    def test_28_workbook_map_covers_all_sheets(self) -> None:
        workbook_map = rows(phase8.PROCESSED / "WORKBOOK_MAP.csv")
        self.assertEqual([row["sheet_name"] for row in workbook_map], list(self.sheet_paths))

    def test_29_prior_phase_analytical_artifacts_are_unchanged(self) -> None:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--", "data/phase1", "data/phase2", "data/phase3",
             "data/phase4", "data/phase5", "data/phase6", "data/phase7", "docs/phase-0",
             "docs/phase-1", "docs/phase-2", "docs/phase-3", "docs/phase-4", "docs/phase-5",
             "docs/phase-6", "docs/phase-7"],
            cwd=ROOT, text=True, capture_output=True, check=True,
        )
        changed = {line for line in result.stdout.splitlines() if line}
        self.assertLessEqual(changed, {"docs/phase-7/COVENANT_DESIGN.md"})

    def test_30_external_engine_dynamic_behavior(self) -> None:
        report = phase8.dynamic()
        self.assertEqual(report["dynamic_status"], "PASS")
        self.assertEqual(report["test_count"], 28)

    def test_31_dynamic_validation_has_separate_evidence(self) -> None:
        dynamic = next(row for row in self.validations if row["validation_id"] == "P8V-012")
        self.assertEqual(dynamic["status"], "PASS")
        self.assertNotEqual(dynamic["observed"], "not_run")
        evidence = rows(phase8.DYNAMIC_EVIDENCE)
        self.assertEqual(len(evidence), 28)
        self.assertTrue(all(row["status"] == "PASS" for row in evidence))


if __name__ == "__main__":
    unittest.main()
