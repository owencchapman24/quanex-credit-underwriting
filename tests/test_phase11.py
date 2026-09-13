from __future__ import annotations

import csv
import hashlib
import importlib.util
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("phase11_test_module", ROOT / "scripts" / "phase11.py")
assert SPEC and SPEC.loader
phase11 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = phase11
SPEC.loader.exec_module(phase11)


def rows(relative: str) -> list[dict[str, str]]:
    with (ROOT / relative).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class Phase11ReleaseTests(unittest.TestCase):
    def test_starting_checkpoint(self) -> None:
        row = rows("data/phase11/raw/STARTING_CHECKPOINT.csv")[0]
        self.assertEqual(row["repository"], "owencchapman24/quanex-credit-underwriting")
        self.assertEqual(row["branch"], "main")
        self.assertEqual(row["local_head"], phase11.APPROVED_PHASE10_COMMIT)
        self.assertEqual(row["tracked_origin_main"], phase11.APPROVED_PHASE10_COMMIT)
        self.assertEqual(row["live_remote_main"], phase11.APPROVED_PHASE10_COMMIT)
        self.assertEqual(row["sole_parent"], phase11.APPROVED_PHASE10_PARENT)
        self.assertEqual((row["ahead"], row["behind"]), ("0", "0"))

    def test_phase10_decisions_remain_owner_reviewed(self) -> None:
        decisions = rows("data/phase10/raw/OWNER_REVIEW_DECISIONS.csv")
        self.assertEqual(len(decisions), 18)
        self.assertTrue(all(row["review_status"] == "owner_reviewed" for row in decisions))

    def test_approved_artifact_hashes_and_pages(self) -> None:
        self.assertEqual(hashlib.sha256(phase11.MODEL.read_bytes()).hexdigest(), phase11.APPROVED_WORKBOOK_SHA)
        self.assertEqual(hashlib.sha256(phase11.MEMO.read_bytes()).hexdigest(), phase11.APPROVED_MEMO_SHA)
        self.assertEqual(hashlib.sha256(phase11.BRIEF.read_bytes()).hexdigest(), phase11.APPROVED_BRIEF_SHA)
        pdfs = phase11.phase10.pdf_metadata()
        self.assertEqual(pdfs["credit_memo_pages"], 11)
        self.assertEqual(pdfs["committee_brief_pages"], 1)

    def test_workbook_semantic_anchors(self) -> None:
        metadata = phase11.phase10.workbook_metadata()
        self.assertEqual(metadata["size_bytes"], phase11.APPROVED_WORKBOOK_SIZE)
        self.assertEqual(metadata["normalized_fingerprint"], phase11.APPROVED_WORKBOOK_FINGERPRINT)
        self.assertEqual((metadata["sheet_count"], metadata["formula_count"], metadata["chart_count"]), (14, 2902, 7))
        self.assertEqual(metadata["saved_scenario"], "Base")
        self.assertEqual(metadata["external_links"], 0)
        self.assertEqual(metadata["formula_errors"], 0)

    def test_manifest_is_current_and_complete(self) -> None:
        manifest = rows("data/phase11/processed/ARTIFACT_MANIFEST.csv")
        self.assertEqual(len(manifest), len(phase11.ARTIFACTS))
        self.assertTrue(all(row["release_status"] == phase11.RELEASE_STATUS for row in manifest))
        self.assertTrue(all(row["reproducibility_result"] == "PASS" for row in manifest))
        for row in manifest:
            path = ROOT / row["relative_path"]
            self.assertTrue(path.is_file(), row["relative_path"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row["sha256"])

    def test_dependency_inventory_reports_actual_chain(self) -> None:
        dependencies = rows("data/phase11/processed/DEPENDENCY_INVENTORY.csv")
        self.assertEqual(len(dependencies), 14)
        index = {row["component"]: row for row in dependencies}
        self.assertEqual(index["Python"]["tested_version"], "3.14.7")
        self.assertEqual(index["Node.js"]["tested_version"], "24.19.0")
        self.assertEqual(index["LibreOffice"]["tested_version"], "26.8.0.3")
        self.assertEqual(index["Microsoft Excel for Microsoft 365"]["tested_version"], "16.0 build 20326")
        self.assertEqual(index["pypdfium2 / PDFium"]["tested_version"], "5.13.0 / 153.0.7999.0")
        self.assertIn("standard library", index["Python"]["notes"])

    def test_reproducibility_controls_pass(self) -> None:
        checks = rows("data/phase11/processed/REPRODUCIBILITY_RESULTS.csv")
        self.assertEqual(len(checks), 6)
        self.assertTrue(all(row["status"] == "PASS" for row in checks))
        self.assertTrue(all("No new analytical evidence" in row["notes"] for row in checks))

    def test_internal_links_and_readme_deliverables_resolve(self) -> None:
        checks = rows("data/phase11/processed/LINK_CHECK_RESULTS.csv")
        self.assertTrue(all(row["status"] == "PASS" for row in checks if row["link_type"] == "internal"))
        readme_targets = {row["target"] for row in checks if row["source_path"] == "README.md"}
        self.assertTrue({"reports/credit_memo.pdf", "reports/committee_brief.pdf", "model/Quanex_Credit_Underwriting.xlsx", "reports/charts/maturity_gap_comparison.png"}.issubset(readme_targets))

    def test_readme_section_order_and_public_claims(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        headings = [
            "## Credit question and final recommendation", "## Transaction snapshot", "## Decisive findings",
            "## Deliverables", "## Overview visual", "## What differentiates the project",
            "## Methodology and tools", "## Reproduction and validation commands", "## Limitations",
            "## AI-use disclosure", "## Repository navigation",
        ]
        positions = [text.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))
        for token in ("Conditional Approval", "owner_reviewed", "July 31, 2029 common horizon", "October 31, 2026", "refinancing remains a material"):
            self.assertIn(token, text)
        self.assertNotIn("official contractual compliance", text.lower())

    def test_limitations_are_decision_specific(self) -> None:
        text = (ROOT / "docs/phase-11/LIMITATIONS.md").read_text(encoding="utf-8")
        for token in ("public-information", "December 15, 2025", "January 31, 2026", "$15 million", "Severe", "refinancing dependency", "N/D", "not appraisals", "probability-of-default", "spreadsheet"):
            self.assertIn(token, text)

    def test_full_ai_disclosure_matches_owner_approved_text(self) -> None:
        text = (ROOT / "docs/phase-11/AI_USE_DISCLOSURE.md").read_text(encoding="utf-8")
        self.assertEqual(text, phase11.APPROVED_AI_DISCLOSURE)

    def test_readme_ai_section_leads_with_owner_analytical_ownership(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        section = text.split("## AI-use disclosure", 1)[1].split("## Repository navigation", 1)[0].strip()
        self.assertTrue(section.startswith("I directed the project and retain responsibility"))
        self.assertLess(section.index("I directed the project"), section.index("AI tools accelerated"))

    def test_readme_links_to_full_ai_disclosure(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("[full AI-use and analytical-ownership disclosure](docs/phase-11/AI_USE_DISCLOSURE.md)", text)

    def test_disclosure_separates_owner_judgment_from_implementation_assistance(self) -> None:
        text = (ROOT / "docs/phase-11/AI_USE_DISCLOSURE.md").read_text(encoding="utf-8")
        for token in ("I directed this project", "I approved the credit question and scope", "determined the treatment of EBITDA adjustments", "made the final recommendation", "I reviewed and validated those outputs"):
            self.assertIn(token, text)
        self.assertIn("AI tools accelerated portions of the implementation", text)
        self.assertIn("AI did not independently make the credit decision", text)

    def test_disclosure_does_not_claim_unaided_authorship(self) -> None:
        text = (ROOT / "docs/phase-11/AI_USE_DISCLOSURE.md").read_text(encoding="utf-8")
        self.assertIn("AI tools accelerated", text)
        for phrase in ("unaided", "without assistance", "personally typed every line", "solely authored"):
            self.assertNotIn(phrase, text.lower())

    def test_disclosure_does_not_reduce_project_to_prompting(self) -> None:
        disclosure = (ROOT / "docs/phase-11/AI_USE_DISCLOSURE.md").read_text(encoding="utf-8").lower()
        readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
        self.assertNotIn("prompting", disclosure)
        self.assertNotIn("prompting", readme)

    def test_phase11_ai_disclosure_decision_is_owner_reviewed(self) -> None:
        decisions = rows("data/phase11/raw/OWNER_REVIEW_DECISIONS.csv")
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["review_status"], "owner_reviewed")
        self.assertEqual(decisions[0]["decision_record"], "docs/phase-11/AI_USE_DISCLOSURE.md")
        self.assertTrue(decisions[0]["analytical_effect"].startswith("None"))

    def test_license_status_is_explicit_and_no_license_added(self) -> None:
        license_files = [p for p in ROOT.iterdir() if p.is_file() and re.match(r"(?i)^(LICENSE|COPYING|NOTICE)(\.|$)", p.name)]
        self.assertFalse(license_files)
        text = (ROOT / "docs/phase-11/RELEASE_CHECKLIST.md").read_text(encoding="utf-8")
        self.assertIn("all-rights-reserved", text)
        self.assertIn("explicit owner decision", text)
        self.assertIn("- [ ] Choose the code, report, and data licensing treatment.", text)
        self.assertIn("- [x] AI-use disclosure reviewed and approved by the owner (`owner_reviewed`).", text)

    def test_reproducibility_claim_is_bounded_to_tested_environment(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        details = (ROOT / "docs/phase-11/REPRODUCIBILITY.md").read_text(encoding="utf-8")
        self.assertIn("Full regeneration is established only for the documented Windows environment", readme)
        self.assertIn("do not claim universal, platform-independent reproducibility", details)
        for token in ("Windows", "Python", "Node.js", "@oai/artifact-tool", "Microsoft Excel", "LibreOffice", "PowerShell"):
            self.assertIn(token, readme)
            self.assertIn(token, details)

    def test_no_absolute_local_paths_credentials_or_residue(self) -> None:
        absolute = re.compile(
            r"(?i)([A-Z]:[\\/]" + "Users" + r"[\\/]|/" + "home/|file:" + "//)"
        )
        credential = re.compile(r"(?i)(api[_-]?key\s*[:=]|password\s*[:=]|secret\s*[:=]|bearer\s+[A-Za-z0-9_-]{12,}|-----BEGIN [A-Z ]+PRIVATE KEY-----)")
        for path in phase11._text_release_paths():
            text = path.read_text(encoding="utf-8", errors="ignore")
            self.assertIsNone(absolute.search(text), str(path))
            self.assertIsNone(credential.search(text), str(path))
        residue = re.compile(r"(^|/)(__pycache__|\.pytest_cache|node_modules|\.venv|venv)(/|$)|(^|/)(~\$|\.~lock\.)|\.(tmp|bak|pyc)$", re.I)
        self.assertFalse([path for path in phase11.repository_paths() if residue.search(path)])

    def test_pdf_binary_attributes_remain_repository_local(self) -> None:
        self.assertEqual((ROOT / ".gitattributes").read_text(encoding="utf-8"), "*.pdf -diff -merge -text\n")
        output = subprocess.run(
            ["git", "check-attr", "diff", "merge", "text", "--", "reports/credit_memo.pdf", "reports/committee_brief.pdf"],
            cwd=ROOT, text=True, capture_output=True, check=True,
        ).stdout.splitlines()
        self.assertTrue(output)
        self.assertTrue(all(line.endswith("unset") for line in output))

    def test_phase0_to_10_analytical_artifacts_unchanged(self) -> None:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--", "data/phase1", "data/phase2", "data/phase3", "data/phase4", "data/phase5", "data/phase6", "data/phase7", "data/phase8", "data/phase9", "data/phase10", "docs/phase-0", "docs/phase-1", "docs/phase-2", "docs/phase-3", "docs/phase-4", "docs/phase-5", "docs/phase-6", "docs/phase-7", "docs/phase-8", "docs/phase-9", "docs/phase-10", "model", "reports"],
            cwd=ROOT, text=True, capture_output=True, check=True,
        )
        self.assertEqual(result.stdout.strip(), "")

    def test_phase12_is_absent(self) -> None:
        for path in (ROOT / "data/phase12", ROOT / "docs/phase-12", ROOT / "scripts/phase12.py", ROOT / "tests/test_phase12.py"):
            self.assertFalse(path.exists())

    def test_build_sequence_has_no_network_command(self) -> None:
        flattened = " ".join(" ".join(command) for _, command in phase11.BUILD_SEQUENCE).lower()
        for token in ("curl", "wget", "invoke-webrequest", "http://", "https://", "git fetch", "git pull"):
            self.assertNotIn(token, flattened)

    def test_validation_is_read_only(self) -> None:
        before = phase11.repository_manifest()
        with mock.patch.object(phase11.phase10, "pdf_metadata", return_value={"credit_memo_pages": 11, "committee_brief_pages": 1}), mock.patch.object(
            phase11.phase10, "workbook_metadata", return_value={
                "sha256": phase11.APPROVED_WORKBOOK_SHA, "size_bytes": phase11.APPROVED_WORKBOOK_SIZE,
                "normalized_fingerprint": phase11.APPROVED_WORKBOOK_FINGERPRINT, "sheet_count": 14,
                "formula_count": 2902, "chart_count": 7, "saved_scenario": "Base",
                "external_links": 0, "formula_errors": 0, "checks_dependencies": 0,
            },
        ):
            checks = phase11.validate()
        after = phase11.repository_manifest()
        self.assertTrue(all(row["status"] == "PASS" for row in checks))
        self.assertEqual(before, after)

    def test_spreadsheet_engine_helpers_use_disposable_copies(self) -> None:
        phase10_text = (ROOT / "scripts/phase10.py").read_text(encoding="utf-8")
        self.assertIn("libreoffice_report_on_copy", phase10_text)
        self.assertIn("excel_validation_on_copy", phase10_text)
        for name in ("validate-phase8-excel.ps1", "validate-phase9-excel.ps1"):
            text = (ROOT / "scripts" / name).read_text(encoding="utf-8-sig")
            self.assertIn("Copy-Item -LiteralPath $source", text)
            self.assertNotIn("Workbooks.Open($source)", text)

    def test_validation_results_pass(self) -> None:
        checks = rows("data/phase11/processed/VALIDATION_RESULTS.csv")
        self.assertTrue(checks)
        self.assertTrue(all(row["status"] == "PASS" for row in checks))


if __name__ == "__main__":
    unittest.main()
