"""Independent economic-semantic controls for the post-Phase 11 remediation."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
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
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "p": "http://schemas.openxmlformats.org/package/2006/relationships"}


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


phase8 = load("phase8_audit_tests", "scripts/phase8.py")


def rows(relative: str) -> list[dict[str, str]]:
    with (ROOT / relative).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class AuditRemediationInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.opening = rows("data/phase8/processed/OPENING_DEBT_COMPARISON.csv")
        cls.sizing = rows("data/phase8/processed/TERM_SIZING_SENSITIVITY.csv")
        cls.amort = rows("data/phase8/processed/AMORTIZATION_SENSITIVITY_RESULTS.csv")
        cls.dynamic = rows("data/phase8/processed/DYNAMIC_TEST_EVIDENCE.csv")
        cls.validation = rows("data/phase8/processed/WORKBOOK_VALIDATION_RESULTS.csv")

    def test_01_opening_alternatives_share_projected_date(self) -> None:
        projected = [r for r in self.opening if r["comparison_group"] == "projected_closing_alternatives"]
        self.assertEqual(len(projected), 3)
        self.assertEqual({r["comparison_date"] for r in projected}, {"2026-01-31"})

    def test_02_october_actual_is_separate_historical_reference(self) -> None:
        historical = [r for r in self.opening if r["comparison_group"] == "historical_reference"]
        self.assertEqual(len(historical), 1)
        self.assertEqual(historical[0]["comparison_date"], "2025-10-31")
        self.assertEqual(Decimal(historical[0]["total_funded_debt"]), Decimal("703.869"))
        self.assertEqual(historical[0]["status"], "historical_reference_only")

    def test_03_every_feasible_or_conditional_sizing_row_balances(self) -> None:
        for row in self.sizing:
            rebuilt = Decimal(row["term_amount"]) + Decimal(row["opening_revolver"]) + Decimal(row["non_debt_source"])
            self.assertEqual(rebuilt, Decimal(row["total_sources"]), row["candidate_id"])
            if row["case_status"] != "unbalanced_diagnostic":
                self.assertLessEqual(abs(Decimal(row["total_sources"]) - Decimal(row["total_uses"])), Decimal("0.002"), row["candidate_id"])
                self.assertLessEqual(abs(Decimal(row["sources_less_uses"])), Decimal("0.002"), row["candidate_id"])

    def test_04_selected_balances_without_debt_substitution(self) -> None:
        selected = next(r for r in self.sizing if r["candidate_id"] == "STR-008")
        self.assertEqual(Decimal(selected["term_amount"]), Decimal("635"))
        self.assertEqual(Decimal(selected["opening_revolver"]), Decimal("29.89771875"))
        self.assertEqual(Decimal(selected["non_debt_source"]), Decimal("15"))
        self.assertEqual(Decimal(selected["sources_less_uses"]), Decimal("0"))

    def test_05_amortization_paths_are_integrated_and_selected_parity_holds(self) -> None:
        required = {"average_modeled_bank_debt", "cumulative_cash_interest", "peak_revolver",
                    "minimum_operating_cash", "minimum_usable_liquidity", "cumulative_ecf_sweep",
                    "ending_bank_debt", "common_horizon_total_funded_debt", "unsupported_maturity_gap",
                    "maximum_quarterly_test_leverage", "minimum_complete_ltm_coverage"}
        self.assertTrue(required.issubset(self.amort[0]))
        self.assertTrue(all("Phase7 integrated engine" in r["upstream_ids"] for r in self.amort))
        selected = next(r for r in self.amort if Decimal(r["annual_amortization_percent"]) == Decimal("7.5"))
        covenant_base = next(
            r for r in rows(ROOT / "data" / "phase7" / "processed" / "COVENANT_SUMMARY.csv")
            if r["scenario_id"] == "BASE"
        )
        structure_base = next(
            r for r in rows(ROOT / "data" / "phase7" / "processed" / "STRUCTURE_COMPARISON.csv")
            if r["candidate_id"] == "STR-008" and r["scenario_id"] == "BASE"
        )
        self.assertLess(abs(Decimal(selected["peak_revolver"]) - Decimal(structure_base["peak_revolver_including_opening"])), Decimal("0.002"))
        self.assertLess(abs(Decimal(selected["maximum_quarterly_test_leverage"]) - Decimal(covenant_base["maximum_gross_funded_leverage"])), Decimal("0.000001"))
        self.assertLess(abs(Decimal(selected["minimum_usable_liquidity"]) - Decimal("263.90228125")), Decimal("0.002"))
        self.assertLess(abs(Decimal(selected["common_horizon_total_funded_debt"]) - Decimal("514.753707786")), Decimal("0.002"))
        self.assertLess(abs(Decimal(selected["unsupported_maturity_gap"]) - Decimal("324.779705120")), Decimal("0.002"))

    def test_06_incomplete_ltm_is_nd(self) -> None:
        evidence = {r["test_name"]: r for r in self.dynamic}
        for name in ("incomplete April 2026 LTM is N/D", "incomplete July 2026 LTM is N/D"):
            self.assertEqual(evidence[name]["status"], "PASS")
            self.assertIn("N/D", evidence[name]["observed"])

    def test_07_complete_nonpositive_ebitda_is_nm(self) -> None:
        evidence = {r["test_name"]: r for r in self.dynamic}
        self.assertEqual(evidence["zero EBITDA with complete inputs is N/M"]["status"], "PASS")
        self.assertEqual(evidence["negative EBITDA with complete inputs is N/M"]["status"], "PASS")

    def test_08_unrun_dynamic_gate_cannot_pass(self) -> None:
        dynamic = next(r for r in self.validation if r["validation_id"] == "P8V-012")
        self.assertEqual(dynamic["status"], "PASS")
        self.assertNotIn("not_run", dynamic["observed"].lower())
        self.assertTrue(self.dynamic)
        self.assertTrue(all(r["status"] == "PASS" for r in self.dynamic))

    def test_09_common_horizon_disadvantage_is_preserved(self) -> None:
        common = rows("data/phase7/processed/COMMON_HORIZON_COMPARISON.csv")
        value = {
            r["candidate_id"]: Decimal(r["ending_total_funded_debt"])
            for r in common
            if r["scenario_id"] == "BASE" and r["ending_total_funded_debt"]
        }
        self.assertLess(abs((value["STR-008"] - value["STR-001"]) - Decimal("19.3854265794703")), Decimal("0.002"))

    def test_10_unpaid_or_curtailed_borrowing_is_not_improvement(self) -> None:
        combined = "\n".join((ROOT / p).read_text(encoding="utf-8") for p in (
            "reports/credit_memo.md", "reports/committee_brief.md", "README.md"))
        self.assertIn("Lower debt caused by curtailed borrowing or unpaid obligations is not improvement", combined)

    def test_11_verification_helpers_are_nonmutating_by_construction(self) -> None:
        source = (ROOT / "scripts/phase11.py").read_text(encoding="utf-8")
        self.assertIn("isolated_clone", source)
        self.assertIn("before_manifest", source)
        self.assertIn("after_manifest", source)
        self.assertIn("Final isolated verification modified repository", source)

    def test_12_decision_outputs_agree_on_dates_and_conclusions(self) -> None:
        texts = [(ROOT / p).read_text(encoding="utf-8") for p in (
            "README.md", "reports/credit_memo.md", "reports/committee_brief.md")]
        for text in texts:
            self.assertIn("January 31, 2026", text)
            self.assertIn("$5.000m", text)
            self.assertIn("$19.385m", text)
            self.assertNotIn("near-term debt expansion", text.lower())


class DynamicEvidenceStateTests(unittest.TestCase):
    def test_not_run_and_missing_evidence_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            target = Path(name) / "evidence.csv"
            with mock.patch.object(phase8, "DYNAMIC_EVIDENCE", target):
                self.assertEqual(phase8.dynamic_evidence_state()[0], "NOT_RUN")
                target.write_text("evidence_id,status\n", encoding="utf-8")
                self.assertEqual(phase8.dynamic_evidence_state()[0], "NOT_RUN")

    def test_failed_and_verified_dynamic_evidence_have_explicit_states(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            target = Path(name) / "evidence.csv"
            script_hash = hashlib.sha256((ROOT / "scripts/recalculate-phase8.py").read_bytes()).hexdigest()
            builder_hash = hashlib.sha256((ROOT / "scripts/build-phase8.mjs").read_bytes()).hexdigest()
            header = "evidence_id,test_name,status,observed,engine,final_scenario,dynamic_script_sha256,workbook_builder_sha256,source_input_signature,tested_artifact\n"
            def content(status: str) -> str:
                return header + f'P8DE-001,gate,{status},ok,LibreOffice 26.8.0.3,Base,{script_hash},{builder_hash},signature,disposable copy\n'
            with mock.patch.object(phase8, "DYNAMIC_EVIDENCE", target), mock.patch.object(phase8, "source_signature", return_value="signature"):
                target.write_text(content("FAIL"), encoding="utf-8")
                self.assertEqual(phase8.dynamic_evidence_state()[0], "FAIL")
                target.write_text(content("PASS"), encoding="utf-8")
                self.assertEqual(phase8.dynamic_evidence_state()[0], "PASS")


if __name__ == "__main__":
    unittest.main()
