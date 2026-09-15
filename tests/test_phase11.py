from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("phase11_test_module", ROOT / "scripts" / "phase11.py")
assert SPEC and SPEC.loader
phase11 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = phase11
SPEC.loader.exec_module(phase11)

ISOLATED_PRIOR_AUTHORIZATION = dict(phase11.phase10.PHASE10_PRIOR_AUTHORIZED_SHA256)


def rows(relative: str) -> list[dict[str, str]]:
    with (ROOT / relative).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def git_config_snapshot(scope: str) -> tuple[int, bytes, bytes]:
    result = subprocess.run(
        ["git", "config", scope, "--get", "core.autocrlf"],
        cwd=ROOT, capture_output=True, check=False,
    )
    return result.returncode, result.stdout, result.stderr


def valid_excel_phase8_report() -> dict[str, object]:
    identity_cases = {
        "base", "spread_plus_100bp", "amortization_10_percent",
        "fy2026_q2_ebitda_plus_10_percent", "dso_plus_10_days",
        "combined_rate_amortization_ebitda_dso", "tight_liquidity",
        "no_waiver_stress",
    }
    probes: list[dict[str, object]] = []
    for case in sorted(phase11.EXCEL_PHASE8_REQUIRED_PROBE_CASES):
        row: dict[str, object] = {"case": case, "status": "PASS"}
        if case in identity_cases:
            row["max_identity_difference"] = 0.0
        if case in {
            "base", "fy2026_q2_ebitda_plus_10_percent", "dso_plus_10_days",
            "combined_rate_amortization_ebitda_dso",
        }:
            row["q2_cfads_difference"] = 0.0
        if case == "spread_plus_100bp":
            row["february_cash_identity"] = 0.0
            row["april_cash_identity"] = 0.0
        elif case == "amortization_10_percent":
            row["april_cash_identity"] = 0.0
        elif case == "balanced_funding_signature_collision":
            row["stale_status"] = "STALE"
        elif case == "warning_threshold_equalities":
            row["coverage_threshold"] = 3.5
            row["liquidity_threshold"] = 75.0
            row["coverage_status"] = "WARNING"
            row["liquidity_status"] = "WARNING"
        probes.append(row)
    return {
        "status": "PASS", "excel_version": "16.0", "excel_build": "20326",
        "formula_count": phase11.EXPECTED_FORMULA_COUNT,
        "live_input_probes": probes, "final_scenario": "Base", "recovery_logs": 0,
        "freshness_checkpoints": [
            {
                "checkpoint": checkpoint,
                "status": "PASS",
                "current_capture_count": 9,
                "stale_capture_count": 0,
                "checks_freshness_status": "PASS",
                "checks_stale_status": "PASS",
            }
            for checkpoint in (
                "initial_full_calculation",
                "pre_save_base_reset",
                "save_reopen_full_calculation",
            )
        ],
    }


def valid_excel_phase9_report() -> dict[str, object]:
    return {
        "status": "PASS", "excel_version": "16.0", "excel_build": "20326",
        "calculation_methods": [
            {"method": method, "status": "PASS"}
            for method in sorted(phase11.EXCEL_PHASE9_REQUIRED_METHODS)
        ],
        "final_scenario": "Base", "workbook_error_cells": 0, "recovery_logs": 0,
    }


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
        self.assertEqual(metadata["sheet_count"], 14)
        self.assertGreaterEqual(metadata["formula_count"], 2880)
        self.assertEqual(metadata["chart_count"], 7)
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
        self.assertEqual(len(checks), 14)
        self.assertTrue(all(row["status"] == "PASS" for row in checks))
        self.assertTrue(all("No new analytical evidence" in row["notes"] for row in checks))
        self.assertEqual(len({row["verification_mode"] for row in checks}), 1)
        self.assertIn(checks[0]["verification_mode"], {phase11.RELEASE_MODE, phase11.OVERLAY_MODE})

    def test_phase11_control_source_hashes_are_current(self) -> None:
        ledger = {row["source_path"]: row for row in rows("docs/phase-11/SOURCE_LEDGER.csv")}
        required = (
            "scripts/phase2.py", "tests/test_phase2.py", "scripts/phase6.py", "tests/test_phase6.py",
            "scripts/phase7.py", "tests/test_phase7.py", "scripts/phase8.py", "scripts/build-phase8.mjs",
            "scripts/recalculate-phase8.py", "scripts/validate-phase8-excel.ps1", "tests/test_phase8.py",
            "scripts/phase9.py", "scripts/validate-phase9-excel.ps1", "tests/test_phase9.py", "scripts/remediation_controls.py", "scripts/workbook_semantics.py",
            "tests/test_workbook_semantics.py", "scripts/xlsx_package.py", "tests/test_xlsx_package.py", "scripts/phase10.py", "scripts/build-phase10.mjs",
            "scripts/render-phase10.py", "tests/test_phase10.py", "scripts/phase11.py", "tests/test_phase11.py",
        )
        for relative in required:
            self.assertIn(relative, ledger)
            current = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(ledger[relative]["sha256"], current)
            self.assertEqual(ledger[relative]["classification"], "repository_control")
            self.assertEqual(ledger[relative]["cutoff_status"], "not_applicable")

    def test_canonical_lf_disposable_clone_and_phase3_regeneration(self) -> None:
        global_before = git_config_snapshot("--global")
        system_before = git_config_snapshot("--system")
        source_config_before = phase11.git_config_digest(ROOT)
        current_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            capture_output=True, check=True,
        ).stdout.strip()
        current_changes = frozenset(phase11.changed_paths())
        if current_changes:
            self.skipTest(
                "clean-release integration requires a committed candidate; "
                "pre-commit overlays must be supplied explicitly to the CLI"
            )
        release_source = ROOT
        with mock.patch.dict(os.environ, phase11.GIT_WINDOWS_TEXT_ENV, clear=False):
            release_manifest_before = phase11.repository_manifest(release_source)
            release_status_before = phase11.git_status(release_source)
            holder, destination = phase11.isolated_clone(
                source_root=release_source, mode=phase11.RELEASE_MODE,
                selected_commit=current_head, overlay_paths=frozenset(),
            )
        disposable_root = Path(holder.name)
        try:
            self.assertTrue((destination / ".git").is_dir())
            self.assertNotEqual((destination / ".git").resolve(), (release_source / ".git").resolve())
            self.assertFalse(os.path.samefile(
                release_source / phase11.REPRESENTATIVE_LF_CSV,
                destination / phase11.REPRESENTATIVE_LF_CSV,
            ))
            local = subprocess.run(
                ["git", "config", "--local", "--get", "core.autocrlf"],
                cwd=destination, text=True, capture_output=True, check=True,
            ).stdout.strip()
            self.assertEqual(local, "false")
            branch = subprocess.run(
                ["git", "branch", "--show-current"], cwd=destination,
                text=True, capture_output=True, check=True,
            ).stdout.strip()
            self.assertEqual(branch, "main")
            for relative in phase11.PHASE3_PRESERVED_PATHS:
                checkout = (destination / relative).read_bytes()
                blob = subprocess.run(
                    ["git", "show", f"HEAD:{relative}"], cwd=destination,
                    capture_output=True, check=True,
                ).stdout
                self.assertEqual(checkout, blob, relative)
                self.assertNotIn(b"\r\n", checkout, relative)
            for relative in phase11.PHASE0_STATIC_SOURCE_TEXT_PATHS:
                checkout = (destination / relative).read_bytes()
                blob = subprocess.run(
                    ["git", "show", f"HEAD:{relative}"], cwd=destination,
                    capture_output=True, check=True,
                ).stdout
                self.assertEqual(checkout, blob, relative)
                self.assertNotIn(b"\r\n", checkout, relative)
            checkpoint = phase11.phase10.read_csv(
                destination / "data/phase10/raw/STARTING_CHECKPOINT.csv"
            )[0]
            with mock.patch.object(phase11.phase10, "ROOT", destination):
                self.assertEqual(
                    phase11.phase10.source_signature(),
                    checkpoint["source_input_signature"],
                )
            before = phase11.exact_path_hashes(destination, list(phase11.PHASE3_PRESERVED_PATHS))
            result = subprocess.run(
                [sys.executable, "-B", "scripts/phase3.py", "validate"],
                cwd=destination, text=True, capture_output=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **phase11.GIT_WINDOWS_TEXT_ENV}, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASS", result.stdout + result.stderr)
            after = phase11.exact_path_hashes(destination, list(phase11.PHASE3_PRESERVED_PATHS))
            self.assertEqual(before, after)
        finally:
            holder.cleanup()
        self.assertFalse(disposable_root.exists())
        self.assertEqual(phase11.repository_manifest(release_source), release_manifest_before)
        self.assertEqual(phase11.git_status(release_source), release_status_before)
        self.assertEqual(git_config_snapshot("--global"), global_before)
        self.assertEqual(git_config_snapshot("--system"), system_before)
        self.assertEqual(phase11.git_config_digest(ROOT), source_config_before)

    def test_raw_byte_comparison_detects_eol_numeric_and_text_mutations(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quanex-phase11-raw-byte-test-") as temp_name:
            root = Path(temp_name)
            path = root / "sample.csv"
            path.write_bytes(b"metric,value\nRevenue,100\n")
            baseline = phase11.exact_path_hashes(root, ["sample.csv"])
            path.write_bytes(b"metric,value\r\nRevenue,100\r\n")
            self.assertEqual(phase11.exact_path_differences(baseline, root), ["sample.csv"])
            path.write_bytes(b"metric,value\nRevenue,101\n")
            self.assertEqual(phase11.exact_path_differences(baseline, root), ["sample.csv"])
            path.write_bytes(b"metric,value\nSales,100\n")
            self.assertEqual(phase11.exact_path_differences(baseline, root), ["sample.csv"])

    def test_overlay_copy_is_byte_exact_and_fixed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quanex-phase11-overlay-source-") as source_name, tempfile.TemporaryDirectory(prefix="quanex-phase11-overlay-target-") as target_name:
            source = Path(source_name)
            target = Path(target_name)
            relative = "nested/sample.csv"
            payload = b"metric,value\nRevenue,100\n"
            (source / relative).parent.mkdir(parents=True)
            (source / relative).write_bytes(payload)
            phase11._copy_current_tree_to_clone(
                target, source_root=source, overlay_paths=frozenset({relative}),
            )
            self.assertEqual((target / relative).read_bytes(), payload)
            self.assertNotIn(b"\r\n", (target / relative).read_bytes())

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
        for token in ("Conditional Approval — proceed with diligence and definitive documentation.", "No final commitment or funding authorization exists until all material conditions are satisfied.", "owner_reviewed", "$5.000m", "July 31, 2029 common horizon", "October 31, 2026", "refinancing remains a material"):
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

    def test_clean_release_preflight_accepts_only_selected_clean_head(self) -> None:
        selected = "a" * 40
        with mock.patch.object(phase11, "resolve_commit", return_value=selected), mock.patch.object(
            phase11, "git_head", return_value=selected,
        ), mock.patch.object(phase11, "changed_paths", return_value=[]):
            self.assertEqual(
                phase11.validate_isolation_request(
                    ROOT, mode=phase11.RELEASE_MODE,
                    selected_commit=selected, overlay_paths=frozenset(),
                ),
                selected,
            )
            with self.assertRaisesRegex(phase11.Phase11Error, "does not permit an overlay"):
                phase11.validate_isolation_request(
                    ROOT, mode=phase11.RELEASE_MODE,
                    selected_commit=selected, overlay_paths=frozenset({"README.md"}),
                )

    def test_clean_release_preflight_rejects_dirty_source_and_wrong_commit(self) -> None:
        selected = "a" * 40
        with mock.patch.object(phase11, "resolve_commit", return_value=selected), mock.patch.object(
            phase11, "git_head", return_value=selected,
        ), mock.patch.object(phase11, "changed_paths", return_value=["README.md"]):
            with self.assertRaisesRegex(phase11.Phase11Error, "pristine source checkout"):
                phase11.validate_isolation_request(
                    ROOT, mode=phase11.RELEASE_MODE,
                    selected_commit=selected, overlay_paths=frozenset(),
                )
        with mock.patch.object(phase11, "resolve_commit", return_value=selected), mock.patch.object(
            phase11, "git_head", return_value="b" * 40,
        ):
            with self.assertRaisesRegex(phase11.Phase11Error, "not the source checkout HEAD"):
                phase11.validate_isolation_request(
                    ROOT, mode=phase11.RELEASE_MODE,
                    selected_commit=selected, overlay_paths=frozenset(),
                )

    def test_overlay_review_requires_exact_explicit_inventory(self) -> None:
        selected = "a" * 40
        declared = frozenset({"README.md", "scripts/phase11.py"})
        with mock.patch.object(phase11, "resolve_commit", return_value=selected), mock.patch.object(
            phase11, "git_head", return_value=selected,
        ), mock.patch.object(phase11, "changed_paths", return_value=sorted(declared)):
            self.assertEqual(
                phase11.validate_isolation_request(
                    ROOT, mode=phase11.OVERLAY_MODE,
                    selected_commit=selected, overlay_paths=declared,
                ),
                selected,
            )
            with self.assertRaisesRegex(phase11.Phase11Error, "unexpected=.*scripts/phase11.py"):
                phase11.validate_isolation_request(
                    ROOT, mode=phase11.OVERLAY_MODE,
                    selected_commit=selected, overlay_paths=frozenset({"README.md"}),
                )

    def test_overlay_manifest_is_explicit_normalized_and_unique(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quanex-phase11-manifest-") as temp_name:
            manifest = Path(temp_name) / "overlay.txt"
            manifest.write_text("# reviewed paths\nREADME.md\nscripts/phase11.py\n", encoding="utf-8")
            self.assertEqual(
                phase11.read_overlay_manifest(manifest),
                frozenset({"README.md", "scripts/phase11.py"}),
            )
            manifest.write_text("README.md\nREADME.md\n", encoding="utf-8")
            with self.assertRaisesRegex(phase11.Phase11Error, "duplicate paths"):
                phase11.read_overlay_manifest(manifest)
            manifest.write_text("../outside.txt\n", encoding="utf-8")
            with self.assertRaisesRegex(phase11.Phase11Error, "Invalid overlay path"):
                phase11.read_overlay_manifest(manifest)
            manifest.write_text(".git/config\n", encoding="utf-8")
            with self.assertRaisesRegex(phase11.Phase11Error, "Invalid overlay path"):
                phase11.read_overlay_manifest(manifest)
            manifest.write_text(".GIT/config\n", encoding="utf-8")
            with self.assertRaisesRegex(phase11.Phase11Error, "Invalid overlay path"):
                phase11.read_overlay_manifest(manifest)

    def test_verification_clone_start_distinguishes_release_and_overlay_heads(self) -> None:
        selected = "a" * 40
        overlay_head = "b" * 40
        self.assertEqual(
            phase11.validate_verification_clone_start(
                ROOT, mode=phase11.RELEASE_MODE, resolved_commit=selected,
                clone_head=selected, clone_status="",
            ),
            selected,
        )
        with self.assertRaisesRegex(phase11.Phase11Error, "exact-candidate"):
            phase11.validate_verification_clone_start(
                ROOT, mode=phase11.RELEASE_MODE, resolved_commit=selected,
                clone_head=overlay_head, clone_status="",
            )
        with mock.patch.object(phase11, "resolve_commit", return_value=selected) as resolve:
            self.assertEqual(
                phase11.validate_verification_clone_start(
                    ROOT, mode=phase11.OVERLAY_MODE, resolved_commit=selected,
                    clone_head=overlay_head, clone_status="",
                ),
                selected,
            )
            resolve.assert_called_once_with(ROOT, f"{overlay_head}^")
        with self.assertRaisesRegex(phase11.Phase11Error, "did not begin clean"):
            phase11.validate_verification_clone_start(
                ROOT, mode=phase11.RELEASE_MODE, resolved_commit=selected,
                clone_head=selected, clone_status=" M README.md",
            )

    def test_fresh_validation_difference_fails_before_restoration(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quanex-phase11-fresh-validation-") as temp_name:
            root = Path(temp_name)
            relative = "data/phase8/processed/WORKBOOK_VALIDATION_RESULTS.csv"
            target = root / relative
            target.parent.mkdir(parents=True)
            target.write_bytes(b"validation_id,status\nP8V-001,PASS\n")
            baseline = phase11.exact_path_hashes(root, [relative])
            changed = b"validation_id,status\nP8V-001,FAIL\n"
            target.write_bytes(changed)
            with self.assertRaisesRegex(
                phase11.Phase11Error,
                "Fresh validation output differs before any restoration or later overwrite",
            ):
                phase11.require_fresh_validation_outputs(
                    root, baseline, "phase8", (relative,),
                )
            self.assertEqual(target.read_bytes(), changed)

    def test_fresh_validation_exact_match_records_step_and_raw_hash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quanex-phase11-fresh-validation-") as temp_name:
            root = Path(temp_name)
            relative = "data/phase10/processed/VALIDATION_RESULTS.csv"
            target = root / relative
            target.parent.mkdir(parents=True)
            target.write_bytes(b"validation_id,status\nP10V-001,PASS\n")
            baseline = phase11.exact_path_hashes(root, [relative])
            records = phase11.require_fresh_validation_outputs(
                root, baseline, "phase10_validate", (relative,),
            )
            self.assertEqual(records[0]["status"], "PASS")
            self.assertEqual(records[0]["step"], "phase10_validate")
            self.assertEqual(records[0]["expected_sha256"], records[0]["observed_sha256"])

    def test_git_config_digest_detects_repository_local_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quanex-phase11-config-") as temp_name:
            root = Path(temp_name)
            subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
            subprocess.run(["git", "config", "--local", "core.autocrlf", "false"], cwd=root, check=True)
            before = phase11.git_config_digest(root)
            subprocess.run(["git", "config", "--local", "core.autocrlf", "true"], cwd=root, check=True)
            self.assertNotEqual(phase11.git_config_digest(root), before)

    def test_phase8_excel_gate_requires_complete_unique_executed_probes(self) -> None:
        report = valid_excel_phase8_report()
        summary = phase11.validate_phase8_excel_report(report)
        self.assertEqual(summary["probe_count"], 10)
        self.assertEqual(summary["maximum_identity_difference"], 0.0)
        self.assertEqual(summary["maximum_reconciliation_difference"], 0.0)

        missing = valid_excel_phase8_report()
        missing["live_input_probes"] = list(missing["live_input_probes"])[1:]
        with self.assertRaisesRegex(phase11.Phase11Error, "probe inventory"):
            phase11.validate_phase8_excel_report(missing)

        duplicate = valid_excel_phase8_report()
        duplicate["live_input_probes"] = list(duplicate["live_input_probes"]) + [dict(list(duplicate["live_input_probes"])[0])]
        with self.assertRaisesRegex(phase11.Phase11Error, "probe inventory"):
            phase11.validate_phase8_excel_report(duplicate)

        failed = valid_excel_phase8_report()
        list(failed["live_input_probes"])[0]["status"] = "FAIL"
        with self.assertRaisesRegex(phase11.Phase11Error, "did not pass"):
            phase11.validate_phase8_excel_report(failed)

        residual = valid_excel_phase8_report()
        spread = next(row for row in list(residual["live_input_probes"]) if row["case"] == "spread_plus_100bp")
        spread["february_cash_identity"] = 0.507588746
        with self.assertRaisesRegex(phase11.Phase11Error, "did not reconcile"):
            phase11.validate_phase8_excel_report(residual)

        changed_threshold = valid_excel_phase8_report()
        warning = next(row for row in list(changed_threshold["live_input_probes"]) if row["case"] == "warning_threshold_equalities")
        warning["coverage_threshold"] = 3.5001
        with self.assertRaisesRegex(phase11.Phase11Error, "freshness, warning-boundary"):
            phase11.validate_phase8_excel_report(changed_threshold)

        stale_saved = valid_excel_phase8_report()
        stale_saved["freshness_checkpoints"][2]["stale_capture_count"] = 9
        with self.assertRaisesRegex(phase11.Phase11Error, "saved capture-freshness"):
            phase11.validate_phase8_excel_report(stale_saved)

    def test_phase8_excel_script_declares_required_probes_and_robust_com_cleanup(self) -> None:
        text = (ROOT / "scripts/validate-phase8-excel.ps1").read_text(encoding="utf-8-sig")
        for case in phase11.EXCEL_PHASE8_REQUIRED_PROBE_CASES:
            self.assertIn(f'case = "{case}"', text)
        self.assertIn("GetWindowThreadProcessId", text)
        self.assertIn("StartTime.ToUniversalTime()", text)
        self.assertIn("Get-ChildItem -Path $tempRoot", text)
        self.assertIn('Assert-CapturesCurrent $scenarioComparison $checks "initial_full_calculation"', text)
        self.assertIn('Assert-CapturesCurrent $scenarioComparison2 $checks2 "save_reopen_full_calculation"', text)
        self.assertNotIn("Get-ChildItem -Path ([IO.Path]::GetTempPath())", text)

    def test_phase9_excel_gate_requires_all_documented_calculation_methods(self) -> None:
        report = valid_excel_phase9_report()
        summary = phase11.validate_phase9_excel_report(report)
        self.assertEqual(summary["method_count"], 6)
        missing = valid_excel_phase9_report()
        missing["calculation_methods"] = list(missing["calculation_methods"])[1:]
        with self.assertRaisesRegex(phase11.Phase11Error, "method inventory"):
            phase11.validate_phase9_excel_report(missing)
        wrong_engine = valid_excel_phase9_report()
        wrong_engine["excel_build"] = "unknown"
        with self.assertRaisesRegex(phase11.Phase11Error, "undocumented engine"):
            phase11.validate_phase9_excel_report(wrong_engine)

    def test_phase9_excel_script_uses_scoped_cleanup_and_its_own_process_id(self) -> None:
        text = (ROOT / "scripts/validate-phase9-excel.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("GetWindowThreadProcessId", text)
        self.assertIn("Get-ChildItem -Path $tempRoot", text)
        self.assertNotIn("Get-ChildItem -Path ([IO.Path]::GetTempPath())", text)
        self.assertNotIn("$beforePids", text)
        self.assertNotIn("Where-Object { $beforePids -notcontains $_.Id }", text)
        self.assertIn("StartTime.ToUniversalTime()", text)

    def test_engine_gates_reject_repository_status_or_config_mutation(self) -> None:
        common = (
            mock.patch.object(phase11, "sha256", return_value="model-hash"),
            mock.patch.object(phase11.phase10, "libreoffice_report_on_copy", return_value={"engine": "LibreOffice 26.8.0.3"}),
            mock.patch.object(
                phase11.phase10, "excel_validation_on_copy",
                side_effect=[json.dumps(valid_excel_phase8_report()), json.dumps(valid_excel_phase9_report())],
            ),
            mock.patch.object(phase11, "run", return_value=json.dumps({"status": "PASS"})),
            mock.patch.object(phase11.phase10, "pdf_metadata", return_value={}),
        )
        with common[0], common[1], common[2], common[3], common[4], mock.patch.object(
            phase11, "git_status", side_effect=["", " M workbook.xlsx"],
        ), mock.patch.object(phase11, "git_head", return_value="a" * 40), mock.patch.object(
            phase11, "git_config_digest", return_value="config-hash",
        ):
            with self.assertRaisesRegex(phase11.Phase11Error, "changed repository status"):
                phase11.engine_gates()

        with mock.patch.object(phase11, "sha256", return_value="model-hash"), mock.patch.object(
            phase11.phase10, "libreoffice_report_on_copy", return_value={"engine": "LibreOffice 26.8.0.3"},
        ), mock.patch.object(
            phase11.phase10, "excel_validation_on_copy",
            side_effect=[json.dumps(valid_excel_phase8_report()), json.dumps(valid_excel_phase9_report())],
        ), mock.patch.object(phase11, "run", return_value=json.dumps({"status": "PASS"})), mock.patch.object(
            phase11.phase10, "pdf_metadata", return_value={},
        ), mock.patch.object(phase11, "git_status", return_value=""), mock.patch.object(
            phase11, "git_head", return_value="a" * 40,
        ), mock.patch.object(phase11, "git_config_digest", side_effect=["before", "after"]):
            with self.assertRaisesRegex(phase11.Phase11Error, "changed Git configuration"):
                phase11.engine_gates()

    def test_reproduction_fails_at_the_step_that_changes_validation_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quanex-phase11-reproduction-") as temp_name:
            root = Path(temp_name)
            relative = "data/phase8/processed/WORKBOOK_VALIDATION_RESULTS.csv"
            target = root / relative
            target.parent.mkdir(parents=True)
            target.write_bytes(b"validation_id,status\nP8V-001,PASS\n")
            model = root / "model.xlsx"
            model.write_bytes(b"fixture workbook")

            def changed_run(command: list[str], **kwargs: object) -> str:
                target.write_bytes(b"validation_id,status\nP8V-001,FAIL\n")
                return "synthetic phase8 PASS"

            metadata = {
                "sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
                "normalized_fingerprint": "fixture",
            }
            with mock.patch.object(phase11, "ROOT", root), mock.patch.object(
                phase11, "MODEL", model,
            ), mock.patch.object(
                phase11, "deterministic_prior_paths", return_value=[relative],
            ), mock.patch.object(
                phase11, "BUILD_SEQUENCE", (("phase8", ["synthetic"]),),
            ), mock.patch.object(
                phase11, "FRESH_VALIDATION_BY_STEP", {"phase8": (relative,)},
            ), mock.patch.object(
                phase11, "run", side_effect=changed_run,
            ), mock.patch.object(
                phase11.phase10, "workbook_metadata", return_value=metadata,
            ):
                with self.assertRaisesRegex(
                    phase11.Phase11Error,
                    "step=phase8; path=data/phase8/processed/WORKBOOK_VALIDATION_RESULTS.csv",
                ):
                    phase11.reproduction_in_current_clone()
            self.assertIn(b"FAIL", target.read_bytes())

    def test_phase10_prior_phase_remediation_guard_remains_bounded(self) -> None:
        authorization = phase11.phase10.PHASE10_PRIOR_AUTHORIZED_SHA256
        self.assertEqual(authorization, ISOLATED_PRIOR_AUTHORIZATION)
        self.assertEqual(len(authorization), 45)
        expected_counts = {
            "data/phase2/": 4, "docs/phase-2/": 3,
            "data/phase6/": 3, "docs/phase-6/": 2,
            "data/phase7/": 5, "docs/phase-7/": 3,
            "data/phase8/": 10, "docs/phase-8/": 5,
            "data/phase9/": 7, "docs/phase-9/": 3,
        }
        for prefix, expected in expected_counts.items():
            self.assertEqual(
                sum(path.startswith(prefix) for path in authorization),
                expected,
                prefix,
            )
        self.assertEqual(set(phase11.phase10.authorized_prior_paths()), set(authorization))

    def test_unrelated_prior_phase_change_is_rejected(self) -> None:
        unrelated = "data/phase7/processed/UNRELATED_ANALYTICAL_CHANGE.csv"
        baseline_paths = phase11.phase10.isolation_baseline_paths([unrelated])
        self.assertIn(unrelated, baseline_paths)
        with self.assertRaisesRegex(
            phase11.phase10.Phase10Error,
            "Isolated source baseline differs analytically",
        ):
            phase11.phase10.require_clean_isolated_baseline(unrelated)
        with mock.patch.object(phase11, "changed_paths", return_value=[unrelated]):
            with self.assertRaisesRegex(phase11.Phase11Error, "unexpected=.*UNRELATED_ANALYTICAL_CHANGE"):
                phase11.require_exact_overlay_inventory(ROOT, frozenset())

    def test_phase3_files_are_never_remediation_exceptions(self) -> None:
        self.assertTrue(set(phase11.PHASE3_PRESERVED_PATHS).isdisjoint(ISOLATED_PRIOR_AUTHORIZATION))

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
                "formula_count": phase11.EXPECTED_FORMULA_COUNT, "chart_count": 7, "saved_scenario": "Base",
                "external_links": 0, "formula_errors": 0, "checks_dependencies": 0,
            },
        ):
            checks = phase11.validate(allowed_changes=frozenset(phase11.changed_paths()))
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

    def test_phase11_build_expands_only_its_fixed_generated_inventory(self) -> None:
        declared = frozenset({"README.md"})
        current = set(declared)
        events: list[str] = []

        def preflight(*args: object, **kwargs: object) -> str:
            self.assertEqual(current, set(declared))
            events.append("preflight")
            return "a" * 40

        def reproduce(*args: object, **kwargs: object) -> dict[str, object]:
            self.assertEqual(current, set(declared))
            events.append("reproduce")
            return {"exact_paths_compared": 1}

        def write(path: Path, *args: object, **kwargs: object) -> None:
            self.assertIn("reproduce", events)
            current.add(path.relative_to(ROOT).as_posix())
            events.append("write")

        validation_inventories: list[frozenset[str]] = []

        def validate(*, write_output: bool, allowed_changes: frozenset[str]) -> list[dict[str, object]]:
            self.assertTrue(write_output)
            self.assertEqual(allowed_changes, frozenset(current))
            validation_inventories.append(allowed_changes)
            current.add("data/phase11/processed/VALIDATION_RESULTS.csv")
            return [{"status": "PASS"}]

        one_row = [{"status": "PASS"}]
        with mock.patch.object(phase11, "validate_isolation_request", side_effect=preflight), mock.patch.object(
            phase11, "run_isolated_reproduction", side_effect=reproduce,
        ), mock.patch.object(phase11, "repository_paths", return_value=[]), mock.patch.object(
            phase11, "changed_paths", side_effect=lambda root=ROOT: sorted(current),
        ), mock.patch.object(phase11, "write_csv", side_effect=write), mock.patch.object(
            phase11, "dependency_rows", return_value=one_row,
        ), mock.patch.object(phase11, "link_rows", return_value=one_row), mock.patch.object(
            phase11, "source_ledger_rows", return_value=one_row,
        ), mock.patch.object(phase11, "artifact_rows", return_value=one_row), mock.patch.object(
            phase11, "reproduction_rows", return_value=one_row,
        ), mock.patch.object(phase11, "validate", side_effect=validate):
            result = phase11.build_outputs(base_commit="a" * 40, overlay_paths=declared)

        self.assertEqual(events[:2], ["preflight", "reproduce"])
        self.assertEqual(len(validation_inventories), 2)
        self.assertEqual(
            frozenset(current) - declared,
            phase11.PHASE11_GENERATED_OUTPUT_PATHS,
        )
        self.assertEqual(result["status"], "PASS")

    def test_phase11_build_inventory_rejects_arbitrary_new_path(self) -> None:
        declared = frozenset({"README.md"})
        with mock.patch.object(
            phase11, "changed_paths",
            return_value=["README.md", "unreviewed-output.txt"],
        ):
            with self.assertRaisesRegex(phase11.Phase11Error, "outside its fixed output inventory"):
                phase11.phase11_build_change_inventory(declared)

    def test_phase11_build_protects_maintained_phase11_sources(self) -> None:
        declared = frozenset({"README.md"})
        one_row = [{"status": "PASS"}]
        protected = "docs/phase-11/METHODOLOGY.md"
        with mock.patch.object(
            phase11, "validate_isolation_request", return_value="a" * 40,
        ), mock.patch.object(
            phase11, "run_isolated_reproduction",
            return_value={"exact_paths_compared": 1},
        ), mock.patch.object(
            phase11, "repository_paths", return_value=[protected],
        ), mock.patch.object(
            phase11, "sha256", side_effect=["before", "after"],
        ), mock.patch.object(
            phase11, "changed_paths", return_value=sorted(declared),
        ), mock.patch.object(phase11, "write_csv"), mock.patch.object(
            phase11, "dependency_rows", return_value=one_row,
        ), mock.patch.object(phase11, "link_rows", return_value=one_row), mock.patch.object(
            phase11, "source_ledger_rows", return_value=one_row,
        ), mock.patch.object(phase11, "artifact_rows", return_value=one_row), mock.patch.object(
            phase11, "reproduction_rows", return_value=one_row,
        ), mock.patch.object(phase11, "validate", return_value=one_row):
            with self.assertRaisesRegex(phase11.Phase11Error, "modified protected files"):
                phase11.build_outputs(base_commit="a" * 40, overlay_paths=declared)

    def test_clean_clone_eol_profile_preserves_phase11_source_blobs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quanex-phase11-eol-scope-") as temp_name:
            root = Path(temp_name)
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            files = {
                "README.md": b"# Readme\nline\n",
                "reports/credit_memo.md": b"# Memo\nline\n",
                "data/phase10/processed/input.json": b'{"value": 1}\n',
                "docs/phase-10/METHODOLOGY.md": b"# Phase 10\nline\n",
                "docs/phase-0/CASE_CHARTER.md": b"# Charter\nline\n",
                "docs/phase-0/EXISTING_FINANCING.md": b"# Financing\nline\n",
                "docs/phase-11/METHODOLOGY.md": b"# Phase 11\nline\n",
            }
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
            subprocess.run(
                ["git", "-c", "user.name=Release Test", "-c", "user.email=release@example.invalid",
                 "commit", "-m", "fixture"],
                cwd=root, check=True, capture_output=True,
            )
            phase11_blob = subprocess.run(
                ["git", "show", "HEAD:docs/phase-11/METHODOLOGY.md"],
                cwd=root, check=True, capture_output=True,
            ).stdout

            converted = phase11._materialize_windows_generation_eols(
                root, overlay_paths=frozenset(),
            )

            self.assertNotIn("docs/phase-11/METHODOLOGY.md", converted)
            self.assertEqual(
                (root / "docs/phase-11/METHODOLOGY.md").read_bytes(),
                phase11_blob,
            )
            self.assertNotIn(b"\r\n", phase11_blob)
            for relative in files:
                if (
                    relative.startswith("docs/phase-11/")
                    or relative in phase11.PHASE0_STATIC_SOURCE_TEXT_PATHS
                ):
                    blob = subprocess.run(
                        ["git", "show", f"HEAD:{relative}"], cwd=root,
                        check=True, capture_output=True,
                    ).stdout
                    self.assertNotIn(relative, converted)
                    self.assertEqual((root / relative).read_bytes(), blob)
                    continue
                self.assertIn(relative, converted)
                self.assertIn(b"\r\n", (root / relative).read_bytes())

    def test_reproduction_requires_raw_workbook_exactness_without_restoration(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quanex-phase11-xlsx-exact-") as temp_name:
            root = Path(temp_name)
            model = root / "model" / "Quanex_Credit_Underwriting.xlsx"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"approved-canonical-workbook")
            metadata = {
                "sha256": "0" * 64, "size_bytes": 1,
                "normalized_fingerprint": "approved-fingerprint",
                "sheet_count": 14, "formula_count": 3473, "chart_count": 7,
                "saved_scenario": "Base", "external_links": 0,
                "formula_errors": 0, "checks_dependencies": 0,
            }

            def mutate(command: list[str], **kwargs: object) -> str:
                model.write_bytes(b"different-workbook-package")
                return "PASS"

            with mock.patch.object(phase11, "ROOT", root), mock.patch.object(
                phase11, "MODEL", model,
            ), mock.patch.object(
                phase11, "deterministic_prior_paths",
                return_value=["model/Quanex_Credit_Underwriting.xlsx"],
            ), mock.patch.object(
                phase11, "BUILD_SEQUENCE", (("workbook", ["fixture"]),),
            ), mock.patch.object(
                phase11, "FRESH_VALIDATION_BY_STEP", {},
            ), mock.patch.object(
                phase11, "run", side_effect=mutate,
            ), mock.patch.object(
                phase11.phase10, "workbook_metadata", return_value=metadata,
            ), mock.patch.object(
                phase11, "APPROVED_WORKBOOK_FINGERPRINT", "approved-fingerprint",
            ):
                with self.assertRaisesRegex(phase11.Phase11Error, "Exact reproducibility failed"):
                    phase11.reproduction_in_current_clone()
            self.assertEqual(model.read_bytes(), b"different-workbook-package")

    def test_deterministic_release_paths_include_canonical_workbook(self) -> None:
        candidates = [
            "README.md", "model/Quanex_Credit_Underwriting.xlsx",
            "reports/credit_memo.pdf", "scripts/phase11.py",
        ]
        with mock.patch.object(phase11, "repository_paths", return_value=candidates):
            selected = phase11.deterministic_prior_paths(ROOT)
        self.assertIn("model/Quanex_Credit_Underwriting.xlsx", selected)
        self.assertNotIn("scripts/phase11.py", selected)

    def test_phase10_fresh_output_inventory_excludes_prior_phase_validation_records(self) -> None:
        phase10_outputs = set(phase11.FRESH_VALIDATION_BY_STEP["phase10_build"])
        self.assertEqual(phase10_outputs, {
            "data/phase10/processed/VALIDATION_RESULTS.csv",
            "data/phase10/processed/FINAL_WORKBOOK_PHASE8_DYNAMIC_EVIDENCE.csv",
            "data/phase10/processed/FINAL_WORKBOOK_PHASE9_DYNAMIC_EVIDENCE.csv",
        })
        self.assertNotIn(
            "data/phase8/processed/WORKBOOK_VALIDATION_RESULTS.csv",
            phase10_outputs,
        )
        self.assertNotIn(
            "data/phase9/processed/VALIDATION_RESULTS.csv",
            phase10_outputs,
        )

    def test_validation_results_pass(self) -> None:
        checks = rows("data/phase11/processed/VALIDATION_RESULTS.csv")
        self.assertTrue(checks)
        self.assertTrue(all(row["status"] == "PASS" for row in checks))


if __name__ == "__main__":
    unittest.main()
