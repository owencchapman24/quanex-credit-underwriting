"""Decision-relevant workbook tests for Phase 8."""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import phase8  # noqa: E402
import remediation_controls  # noqa: E402


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

    def test_08a_historical_cash_interest_is_a_separate_diagnostic(self) -> None:
        text = "\n".join(self.shared)
        self.assertIn("Cash interest paid (disclosed historical diagnostic)", text)
        self.assertIn("historical lender ebitda to disclosed cash interest paid", text.lower())

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

    def test_11b_live_financing_chain_reconciles_operating_and_cash_inputs(self) -> None:
        cfads = self.formula("Debt Schedule", "I12")
        self.assertIn("Assumptions!$D$21", cfads)
        self.assertIn("Assumptions!$D$23", cfads)
        self.assertIn("$F12", cfads)
        self.assertIn("$G12", cfads)
        self.assertIn("AE12", self.formula("Debt Schedule", "T12"))
        self.assertIn("AM12", self.formula("Debt Schedule", "P12"))
        self.assertIn("AN12", self.formula("Debt Schedule", "P12"))
        cash_identity = self.formula("Debt Schedule", "AP12")
        for address in ("I12", "P12", "T12", "U12", "K12", "V12", "Q12", "L12", "M12", "W12"):
            self.assertIn(address, cash_identity)

    def test_11c_covenant_linked_event_state_is_live_and_follows_the_test_period(self) -> None:
        february = self.formula("Debt Schedule", "AD12")
        november = self.formula("Debt Schedule", "AD21")
        self.assertIn('RIGHT(', november)
        self.assertIn('"_PHASE7_COVENANT_NO_WAIVER"', november)
        for column in ("L", "R", "T"):
            self.assertIn(f"${column}$8:${column}$11", november)
            self.assertIn(f"COUNTIF(Covenants!${column}$8", february)
        self.assertIn('"*_shutoff_active"', november)
        self.assertNotIn('"*shutoff*"', november)
        self.assertIn("Covenants", self.formula("Scenario Comparison", "S5"))
        self.assertIn("Covenants", self.formula("Scenario Comparison", "T5"))
        self.assertIn("Debt Schedule", self.formula("Scenario Comparison", "U5"))
        self.assertIn("Debt Schedule", self.formula("Scenario Comparison", "V5"))
        for address in ("S5", "T5", "U5", "V5"):
            self.assertNotIn("Assumptions!$B", self.formula("Scenario Comparison", address))

    def test_11d_due_paid_and_shortfall_columns_are_distinct(self) -> None:
        interest_due = self.formula("Debt Schedule", "AE12")
        self.assertIn("AH", interest_due)
        self.assertIn("O12+O12", interest_due)
        self.assertNotIn("AO12", interest_due)
        self.assertIn("MAX(0,AE12-T12)", self.formula("Debt Schedule", "AF12"))
        self.assertIn("MAX(0,AG12-K12)", self.formula("Debt Schedule", "AH12"))
        self.assertIn("MAX(0,AI12-U12)", self.formula("Debt Schedule", "AJ12"))
        self.assertIn("MAX(0,AK12-M12)", self.formula("Debt Schedule", "AL12"))
        self.assertIn("Debt Schedule'!$AE$12:$AE$47", self.formula("Covenants", "M12"))
        self.assertIn("Debt Schedule'!$T$12:$T$47", self.formula("Forecast", "D23"))
        self.assertIn("period-end draws and repayments affect later periods", "\n".join(self.shared))

    def test_11e_post_closing_ebitda_period_is_explicit(self) -> None:
        text = "\n".join(self.shared)
        self.assertIn("FY2026 post-closing nine-month EBITDA (Feb. 1-Oct. 31, 2026)", text)
        self.assertIn("FY2026 post-closing nine-month lender-base EBITDA (Feb. 1-Oct. 31, 2026)", text)

    def test_12_covenant_step_downs_and_boundary_formulas(self) -> None:
        formula = self.formula("Covenants", "J8")
        self.assertIn("DATE(2027,10,31)", formula)
        self.assertIn("DATE(2028,10,31)", formula)
        self.assertIn(">J8", self.formula("Covenants", "L8"))
        self.assertIn("<=Q12", self.formula("Covenants", "R12"))
        self.assertIn("<=Assumptions!$D$34", self.formula("Covenants", "T12"))
        self.assertIn("<=Assumptions!$D$34", self.formula("Liquidity", "R13"))
        self.assertTrue(self.formula("Covenants", "V12").startswith('IF(X12="INCOMPLETE","N/D"'))

    def test_13_nd_and_nm_are_distinct(self) -> None:
        formula = self.formula("Covenants", "O12")
        self.assertIn('"N/D"', formula)
        self.assertIn('"N/M"', formula)

    def test_14_negative_ebitda_cannot_produce_favorable_leverage(self) -> None:
        self.assertIn("G8<=0", self.formula("Covenants", "H8"))
        self.assertIn('"N/M"', self.formula("Covenants", "I8"))

    def test_15_snapshot_stale_formula_uses_current_signature(self) -> None:
        stale = self.formula("Scenario Comparison", "AE12")
        self.assertIn("EXACT(AC12,AD12)", stale)
        self.assertIn("EXACT(AA12,Assumptions!$D$6)", stale)
        self.assertIn("EXACT(AB12,Assumptions!$D$8)", stale)
        input_state = self.formula("Assumptions", "D7")
        self.assertIn("ISBLANK($D$12)", input_state)
        self.assertIn('"number:"', input_state)
        self.assertIn('TEXT(ROUND($D$12,12),"0.000000000000000")', input_state)
        self.assertNotIn("$D$12*1", input_state)
        self.assertEqual(len(self.captures), 9)

    def test_16_all_in_liquidity_includes_opening_position(self) -> None:
        self.assertEqual(self.formula("Liquidity", "D7"), "MIN(Q13:Q47)")
        self.assertIn("MATCH(D7,Q13:Q47,0)", self.formula("Liquidity", "D8"))
        self.assertEqual(self.formula("Liquidity", "D9"), "MIN(D6,D7)")
        self.assertIn("Q13<Assumptions!$D$31", self.formula("Liquidity", "R13"))

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

    def test_26_official_recovery_remains_not_determinable(self) -> None:
        text = "\n".join(self.shared)
        self.assertIn("Official facility recovery", text)
        self.assertIn("Official recovery N/D", text)
        self.assertEqual(self.displayed_value("Recovery", "D45"), "N/D")
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
        self.assertEqual(
            remediation_controls.unapproved_paths(
                ROOT,
                list(changed),
                remediation_controls.PHASE2_AUTHORIZED_SHA256,
                remediation_controls.PHASE6_AUTHORIZED_SHA256,
                remediation_controls.PHASE7_AUTHORIZED_SHA256,
            ),
            [],
        )

    def test_29a_readme_regeneration_replaces_stale_phase8_section(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quanex-p8-readme-") as directory:
            root = Path(directory)
            readme = root / "README.md"
            readme.write_text(
                "# Test\n\nCurrent recommendation: **Conditional Approval**.\n\n"
                "## Phase 8 Excel underwriting model\n\n"
                "Recovery analysis remains pending Phase 9, and no final credit recommendation is made.\n\n"
                "## Current release\n\nRetain this section.\n",
                encoding="utf-8",
            )
            with mock.patch.object(phase8, "ROOT", root):
                phase8.update_readme()
            regenerated = readme.read_text(encoding="utf-8")
        self.assertEqual(regenerated.count("## Phase 8 Excel underwriting model"), 1)
        self.assertIn("Current recommendation: **Conditional Approval**", regenerated)
        self.assertIn("historical phase boundaries do not supersede the current **Conditional Approval**", regenerated)
        self.assertNotIn("Recovery analysis remains pending Phase 9, and no final credit recommendation is made.", regenerated)
        self.assertIn("## Current release\n\nRetain this section.", regenerated)

    def test_30_external_engine_dynamic_behavior(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quanex-p8-engine-evidence-") as directory:
            report = phase8.dynamic(Path(directory) / "dynamic.csv")
        self.assertEqual(report["dynamic_status"], "PASS")
        self.assertEqual(report["test_count"], len(phase8.REQUIRED_DYNAMIC_CASES))

    def test_31_dynamic_validation_has_separate_evidence(self) -> None:
        dynamic = next(row for row in self.validations if row["validation_id"] == "P8V-012")
        self.assertEqual(dynamic["status"], "PASS")
        self.assertNotEqual(dynamic["observed"], "not_run")
        evidence = rows(phase8.DYNAMIC_EVIDENCE)
        self.assertEqual(len(evidence), len(phase8.REQUIRED_DYNAMIC_CASES))
        self.assertTrue(all(row["status"] == "PASS" for row in evidence))


class Phase8DynamicEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.evidence = Path(self.temp.name) / "dynamic.csv"
        self.patch = mock.patch.object(phase8, "DYNAMIC_EVIDENCE", self.evidence)
        self.patch.start()
        self.report = {
            "dynamic_status": "PASS",
            "tests": [
                {"test": case["test_name"], "status": "PASS", "observed": {"case": case["case_id"]}}
                for case in phase8.REQUIRED_DYNAMIC_CASES
            ],
            "engine": phase8.DYNAMIC_TEST_ENGINE,
            "final_scenario": "Base",
            "tested_artifact": phase8.DYNAMIC_TESTED_ARTIFACT,
            "tested_artifact_sha256": phase8.sha256(phase8.MODEL),
            "tested_artifact_semantic_fingerprint": phase8.normalized_fingerprint(),
        }

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp.cleanup()

    def write_valid(self) -> list[dict[str, str]]:
        phase8.write_dynamic_evidence(self.report)
        return rows(self.evidence)

    def replace_rows(self, evidence_rows: list[dict[str, str]], fields: list[str] | None = None) -> None:
        phase8.write_csv(self.evidence, evidence_rows, fields or list(phase8.DYNAMIC_EVIDENCE_FIELDS))

    def test_complete_versioned_registry_passes_with_full_metadata(self) -> None:
        evidence_rows = self.write_valid()
        self.assertEqual(len(evidence_rows), len(phase8.REQUIRED_DYNAMIC_CASES))
        self.assertEqual({row["case_id"] for row in evidence_rows}, {case["case_id"] for case in phase8.REQUIRED_DYNAMIC_CASES})
        self.assertTrue(all(row["test_definition_version"] == phase8.DYNAMIC_TEST_DEFINITION_VERSION for row in evidence_rows))
        self.assertTrue(all(all(row[field] for field in phase8.DYNAMIC_EVIDENCE_FIELDS) for row in evidence_rows))
        self.assertEqual(phase8.dynamic_evidence_state()[0], "PASS")

    def test_missing_or_unexpected_schema_field_fails(self) -> None:
        valid = self.write_valid()
        fields = [field for field in phase8.DYNAMIC_EVIDENCE_FIELDS if field != "input_scope"]
        self.replace_rows(valid, fields)
        self.assertEqual(phase8.dynamic_evidence_state()[0], "FAIL")

    def test_truncated_duplicate_and_extra_case_sets_fail(self) -> None:
        valid = self.write_valid()
        variants = {
            "truncated": valid[:-1],
            "duplicate": valid[:-1] + [dict(valid[0])],
            "extra": valid + [{**valid[-1], "evidence_id": "P8DE-999", "case_id": "P8DT-999", "test_name": "undeclared test"}],
        }
        for label, evidence_rows in variants.items():
            with self.subTest(label=label):
                self.replace_rows(evidence_rows)
                self.assertEqual(phase8.dynamic_evidence_state()[0], "FAIL")

    def test_failed_not_run_and_unknown_statuses_cannot_pass(self) -> None:
        valid = self.write_valid()
        for status, expected in (("FAIL", "FAIL"), ("NOT_RUN", "NOT_RUN"), ("N/D", "FAIL")):
            with self.subTest(status=status):
                changed = [dict(row) for row in valid]
                changed[0]["status"] = status
                self.replace_rows(changed)
                self.assertEqual(phase8.dynamic_evidence_state()[0], expected)

    def test_blank_or_stale_metadata_fails(self) -> None:
        valid = self.write_valid()
        for field, value in (
            ("stage", ""),
            ("evidence_id", "P8DE-999"),
            ("scenario", "wrong scenario"),
            ("input_scope", "wrong input"),
            ("engine", "different engine"),
            ("dynamic_script_sha256", "0" * 64),
            ("workbook_builder_sha256", "0" * 64),
            ("semantic_comparator_sha256", "0" * 64),
            ("source_input_signature", "0" * 64),
            ("test_definition_version", "obsolete"),
            ("test_definition_sha256", "0" * 64),
            ("tested_artifact", "different.xlsx"),
            ("tested_artifact_sha256", "0" * 64),
            ("tested_artifact_semantic_fingerprint", "0" * 64),
        ):
            with self.subTest(field=field):
                changed = [dict(row) for row in valid]
                changed[0][field] = value
                self.replace_rows(changed)
                self.assertEqual(phase8.dynamic_evidence_state()[0], "FAIL")

    def test_writer_rejects_incomplete_duplicate_failed_or_unobserved_reports(self) -> None:
        original = list(self.report["tests"])
        variants = {
            "incomplete": original[:-1],
            "duplicate": original[:-1] + [dict(original[0])],
            "failed": [{**item, "status": "FAIL"} if index == 0 else item for index, item in enumerate(original)],
            "not_run": [{**item, "status": "NOT_RUN"} if index == 0 else item for index, item in enumerate(original)],
            "missing_observed": [{key: value for key, value in item.items() if key != "observed"} if index == 0 else item for index, item in enumerate(original)],
        }
        for label, test_rows in variants.items():
            with self.subTest(label=label):
                self.report["tests"] = test_rows
                with self.assertRaises(phase8.Phase8Error):
                    phase8.write_dynamic_evidence(self.report)
                self.assertFalse(self.evidence.exists())
        self.report["tests"] = original

    def test_custom_evidence_is_separate_and_must_match_current_artifact(self) -> None:
        self.evidence.write_bytes(b"preserve stage evidence")
        stage_before = self.evidence.read_bytes()
        custom = Path(self.temp.name) / "phase10-final-dynamic.csv"
        label = "model/Quanex_Credit_Underwriting.xlsx (Phase 10 final artifact)"
        report = dict(self.report)
        report["tested_artifact"] = label
        phase8.write_dynamic_evidence(
            report, evidence_path=custom, tested_artifact=label,
        )
        self.assertEqual(self.evidence.read_bytes(), stage_before)
        self.assertEqual(
            phase8.dynamic_evidence_state(custom, tested_artifact=label)[0],
            "PASS",
        )
        evidence_rows = rows(custom)
        for row in evidence_rows:
            row["tested_artifact_sha256"] = "0" * 64
        phase8.write_csv(custom, evidence_rows, list(phase8.DYNAMIC_EVIDENCE_FIELDS))
        self.assertEqual(
            phase8.dynamic_evidence_state(custom, tested_artifact=label)[0],
            "FAIL",
        )

    def test_read_only_validation_does_not_rewrite_phase8_records(self) -> None:
        failing_report = {"engine": "fixture", "checks": [], "parity": {}}
        with mock.patch.object(phase8, "write_csv") as writer:
            with self.assertRaises(phase8.Phase8Error):
                phase8.validate_workbook(failing_report, write_outputs=False)
            writer.assert_not_called()
        with mock.patch.object(phase8, "write_csv") as writer:
            with self.assertRaises(phase8.Phase8Error):
                phase8.validate_workbook(failing_report)
            self.assertEqual(writer.call_count, 2)


if __name__ == "__main__":
    unittest.main()
