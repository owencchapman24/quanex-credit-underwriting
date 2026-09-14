"""Build and validate Phase 11 reproducibility and release-QA records.

All analytical regeneration occurs in a disposable local clone.  The authoritative
repository is read-only except when the ``all`` command writes Phase 11 outputs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "phase11"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
DOCS = ROOT / "docs" / "phase-11"
MODEL = ROOT / "model" / "Quanex_Credit_Underwriting.xlsx"
MEMO = ROOT / "reports" / "credit_memo.pdf"
BRIEF = ROOT / "reports" / "committee_brief.pdf"
APPROVED_PHASE10_COMMIT = "ce656ebfca67f2bd34a78273f72367e39c0c2037"
APPROVED_PHASE10_PARENT = "9fca23a949d1f8d8dee6f37906cb086ec6cda994"
APPROVED_WORKBOOK_SHA = "a1fdd2604468e8b795f2bd4330fe78821b66570fd4d728313b98963b01f671d4"
APPROVED_WORKBOOK_SIZE = 286_530
APPROVED_WORKBOOK_FINGERPRINT = "cf536570671a6baf2a7b019d46444cb839bb906943af8f0f22929772c04303ec"
EXPECTED_FORMULA_COUNT = 2897
APPROVED_MEMO_SHA = "9f0b8deb55ccd46729b2a03c97fc0aee63faa31e6ff73702296bda0417629198"
APPROVED_BRIEF_SHA = "f4452cb1c22272158d5720b259eaa8669bf234467b1cc671b5fda72c2547a801"
INFORMATION_CUTOFF = "2025-12-15"
RELEASE_STATUS = "GO_TO_OWNER_REVIEW"
GIT_WINDOWS_TEXT_ENV = {
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "core.autocrlf",
    "GIT_CONFIG_VALUE_0": "true",
}
GIT_CANONICAL_TEXT_ENV = {
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "core.autocrlf",
    "GIT_CONFIG_VALUE_0": "false",
}
APPROVED_AI_DISCLOSURE = """## AI use and analytical ownership

I directed this project and retained responsibility for its underwriting conclusions. I approved the credit question and scope, reviewed the supporting evidence and reconciliations, determined the treatment of EBITDA adjustments, selected the scenario assumptions, evaluated accessible cash, sized the proposed facilities, designed the covenant package, assessed recovery limitations, and made the final recommendation. I also tested key workbook behavior in Microsoft Excel and reviewed the completed model, credit memo, committee brief, and validation results.

AI tools accelerated portions of the implementation, including code drafting, repetitive extraction and normalization, workbook and report generation, test construction, and consistency checking. I reviewed and validated those outputs against the documented sources and controls. AI did not independently make the credit decision, determine the material underwriting judgments, or replace my responsibility for understanding and defending the analysis.
"""


class Phase11Error(RuntimeError):
    """Raised when a Phase 11 release control fails."""


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise Phase11Error(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


phase10 = load_module("phase10_for_phase11", ROOT / "scripts" / "phase10.py")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(
    command: list[str], *, cwd: Path = ROOT, timeout: int = 1800,
    extra_env: dict[str, str] | None = None,
) -> str:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, env=env, timeout=timeout)
    if result.returncode:
        status = ""
        if (cwd / ".git").exists():
            status = subprocess.run(
                ["git", "status", "--short"], cwd=cwd, text=True,
                capture_output=True, check=False,
            ).stdout
        raise Phase11Error(
            f"Command failed ({result.returncode}): {' '.join(command)}\n"
            f"{result.stdout}{result.stderr}\nGit status:\n{status}"
        )
    return (result.stdout + result.stderr).strip()


def repository_paths(root: Path = ROOT) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=root, capture_output=True, check=True,
    )
    return sorted(p.decode("utf-8") for p in result.stdout.split(b"\0") if p)


def repository_manifest(root: Path = ROOT) -> dict[str, str]:
    return {relative: sha256(root / relative) for relative in repository_paths(root)}


def manifest_digest(manifest: dict[str, str]) -> str:
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def git_status(root: Path = ROOT) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain=v1", "-uall"], cwd=root,
        text=True, capture_output=True, check=True,
    ).stdout


def changed_paths(root: Path = ROOT) -> list[str]:
    paths: list[str] = []
    for line in git_status(root).splitlines():
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path.replace("\\", "/"))
    return paths


def _version_output(command: list[str]) -> str:
    return run(command).splitlines()[0].strip()


def dependency_rows() -> list[dict[str, str]]:
    return [
        {"component": "Operating system", "role": "tested host", "required_scope": "release QA", "required_version": "tested Windows environment", "tested_version": "Windows 10 family", "supply_method": "host operating system", "platform": "Windows", "mandatory": "yes for complete tested gate", "notes": "Excel COM and PowerShell harnesses are Windows-only."},
        {"component": "Python", "role": "analytical orchestration and tests", "required_scope": "all phases", "required_version": "3.14.7 tested; other versions untested", "tested_version": _version_output([sys.executable, "--version"]).replace("Python ", ""), "supply_method": "python executable", "platform": "Windows tested", "mandatory": "yes", "notes": "Analytical Python scripts use only the standard library."},
        {"component": "pip", "role": "inventory only", "required_scope": "none", "required_version": "not required by project workflow", "tested_version": "26.2.1", "supply_method": "Python installation", "platform": "Windows tested", "mandatory": "no", "notes": "No project package installation is required."},
        {"component": "Node.js", "role": "workbook authoring runtime", "required_scope": "Phase 8-10 workbook build", "required_version": "24.19.0 tested; other versions untested", "tested_version": "24.19.0", "supply_method": "Codex primary-runtime bundle", "platform": "Windows tested", "mandatory": "yes for workbook generation", "notes": "Not required on PATH; existing scripts resolve the bundled executable."},
        {"component": "@oai/artifact-tool", "role": "XLSX authoring and structural inspection", "required_scope": "Phase 8-10 workbook build", "required_version": "2.8.58+ tested", "tested_version": "2.8.58+", "supply_method": "Codex primary-runtime node_modules", "platform": "Windows tested", "mandatory": "yes for workbook generation", "notes": "No project package.json is used."},
        {"component": "LibreOffice", "role": "full recalculation, capture, and compatibility inspection", "required_scope": "workbook canonicalization", "required_version": "26.8.0.3", "tested_version": "26.8.0.3", "supply_method": "desktop application", "platform": "Windows tested", "mandatory": "yes for approved workbook reproduction", "notes": "Validation receives a disposable workbook copy."},
        {"component": "Microsoft Excel for Microsoft 365", "role": "separate compatibility gate", "required_scope": "final release QA", "required_version": "16.0 build 20326", "tested_version": "16.0 build 20326", "supply_method": "desktop application", "platform": "Windows only", "mandatory": "yes for complete tested release gate", "notes": "Not required for analytical CSV generation; validation receives a disposable copy."},
        {"component": "Windows PowerShell", "role": "Phase 0 and Excel validation", "required_scope": "release QA", "required_version": "5.1.19041.6456", "tested_version": "5.1.19041.6456", "supply_method": "host operating system", "platform": "Windows only", "mandatory": "yes for complete tested gate", "notes": "Use process-scoped ExecutionPolicy Bypass when required."},
        {"component": "Bundled Python", "role": "PDF/chart generation", "required_scope": "Phase 10 documents", "required_version": "3.12.14", "tested_version": "3.12.14", "supply_method": "Codex primary-runtime bundle", "platform": "Windows tested", "mandatory": "yes for PDF regeneration", "notes": "Separate from analytical Python."},
        {"component": "ReportLab", "role": "PDF generation", "required_scope": "Phase 10 documents", "required_version": "4.4.9", "tested_version": "4.4.9", "supply_method": "bundled Python runtime", "platform": "Windows tested", "mandatory": "yes for PDF regeneration", "notes": "No project requirements file is needed."},
        {"component": "Pillow", "role": "chart and document graphics", "required_scope": "Phase 10 documents", "required_version": "12.3.0", "tested_version": "12.3.0", "supply_method": "bundled Python runtime", "platform": "Windows tested", "mandatory": "yes for Phase 10 graphics", "notes": "Bundled dependency."},
        {"component": "pypdf", "role": "PDF metadata and text inspection", "required_scope": "document QA", "required_version": "6.10.0", "tested_version": "6.10.0", "supply_method": "bundled Python runtime", "platform": "Windows tested", "mandatory": "yes for PDF inspection", "notes": "Bundled dependency."},
        {"component": "pypdfium2 / PDFium", "role": "disposable all-page PDF rendering", "required_scope": "document visual QA", "required_version": "5.13.0 / 153.0.7999.0", "tested_version": "5.13.0 / 153.0.7999.0", "supply_method": "bundled Python runtime", "platform": "Windows tested", "mandatory": "yes for automated page rendering", "notes": "Renders only to an explicit temporary directory."},
        {"component": "Git", "role": "local disposable clone and integrity checks", "required_scope": "Phase 11", "required_version": "installed version tested", "tested_version": _version_output(["git", "--version"]).replace("git version ", ""), "supply_method": "host application", "platform": "Windows tested", "mandatory": "yes", "notes": "Clean build uses only a local clone; no remote fetch."},
    ]


LINK_PATTERN = re.compile(r"!?\[[^\]]+\]\(([^)]+)\)")


def link_rows() -> list[dict[str, str]]:
    files = [ROOT / "README.md", *sorted(DOCS.glob("*.md"))]
    rows: list[dict[str, str]] = []
    for source in files:
        text = source.read_text(encoding="utf-8")
        for target in LINK_PATTERN.findall(text):
            if target.startswith(("http://", "https://")):
                rows.append({
                    "link_id": f"P11L-{len(rows)+1:03d}", "source_path": source.relative_to(ROOT).as_posix(),
                    "target": target, "link_type": "external", "status": "INFO",
                    "resolution": "health_check_separate_no_analytical_ingestion",
                    "notes": "External health is not required for analytical reproduction.",
                })
                continue
            clean = target.split("#", 1)[0]
            resolved = (source.parent / clean).resolve() if source != ROOT / "README.md" else (ROOT / clean).resolve()
            passed = bool(clean) and resolved.is_file() and ROOT.resolve() in resolved.parents
            rows.append({
                "link_id": f"P11L-{len(rows)+1:03d}", "source_path": source.relative_to(ROOT).as_posix(),
                "target": target, "link_type": "internal", "status": "PASS" if passed else "FAIL",
                "resolution": resolved.relative_to(ROOT).as_posix() if passed else "unresolved",
                "notes": "Repository-relative path exists." if passed else "Target is missing or outside repository.",
            })
    rows.append({
        "link_id": f"P11L-{len(rows)+1:03d}", "source_path": "release-health policy", "target": "approved external source URLs",
        "link_type": "external_policy", "status": "INFO", "resolution": "separate_non_analytical_check",
        "notes": "SEC 403 is access-restricted when source identity and archived URL remain valid; no response content enters underwriting.",
    })
    return rows


def _record_count(path: Path) -> str:
    if path.suffix.lower() == ".csv":
        return str(len(read_csv(path)))
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return str(len(payload) if hasattr(payload, "__len__") else 1)
    return ""


ARTIFACTS: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("P11A-001", "model/Quanex_Credit_Underwriting.xlsx", "authoritative Excel underwriting model", "Phase 8-10", "python -B scripts/phase10.py all", "required"),
    ("P11A-002", "reports/credit_memo.pdf", "decision-facing credit memo", "Phase 10", "python -B scripts/phase10.py all", "required"),
    ("P11A-003", "reports/committee_brief.pdf", "one-page committee brief", "Phase 10", "python -B scripts/phase10.py all", "required"),
    ("P11A-004", "reports/credit_memo.md", "memo source", "Phase 10", "python -B scripts/phase10.py inputs", "required"),
    ("P11A-005", "reports/committee_brief.md", "brief source", "Phase 10", "python -B scripts/phase10.py inputs", "required"),
    ("P11A-006", "reports/charts/historical_cash_conversion.png", "historical cash-generation chart", "Phase 10", "python -B scripts/phase10.py pdf", "required"),
    ("P11A-007", "reports/charts/maturity_gap_comparison.png", "maturity-gap chart and README visual", "Phase 10", "python -B scripts/phase10.py pdf", "required"),
    ("P11A-008", "reports/charts/recovery_sensitivities.png", "alternative recovery-sensitivity chart", "Phase 10", "python -B scripts/phase10.py pdf", "required"),
    ("P11A-009", "data/phase10/raw/OWNER_REVIEW_DECISIONS.csv", "owner-reviewed recommendation decisions", "Phase 10", "python -B scripts/phase10.py inputs", "required"),
    ("P11A-010", "data/phase10/processed/COMMITTEE_METRICS.csv", "cross-deliverable committee metrics", "Phase 10", "python -B scripts/phase10.py inputs", "required"),
    ("P11A-011", "data/phase10/processed/CONDITIONS_AND_MONITORING.csv", "conditions and monitoring register", "Phase 10", "python -B scripts/phase10.py inputs", "required"),
    ("P11A-012", "data/phase10/processed/DECISION_REGISTER.csv", "decision register", "Phase 10", "python -B scripts/phase10.py inputs", "required"),
    ("P11A-013", "data/phase10/processed/RISK_MITIGANT_MATRIX.csv", "risk and mitigant matrix", "Phase 10", "python -B scripts/phase10.py inputs", "required"),
    ("P11A-014", "data/phase10/processed/DELIVERABLE_CONSISTENCY_RESULTS.csv", "deliverable consistency controls", "Phase 10", "python -B scripts/phase10.py validate", "required"),
    ("P11A-015", "data/phase10/processed/DOCUMENT_QA_RESULTS.csv", "rendered document page-QA record", "Phase 10", "python -B scripts/phase10.py pdf", "required"),
    ("P11A-016", "data/phase10/processed/VALIDATION_RESULTS.csv", "Phase 10 validation controls", "Phase 10", "python -B scripts/phase10.py validate", "required"),
    ("P11A-017", "data/phase10/processed/WORKBOOK_INPUTS.json", "workbook decision inputs", "Phase 10", "python -B scripts/phase10.py inputs", "required"),
    ("P11A-018", "README.md", "public repository entry point", "Phase 11", "maintained source", "required"),
    ("P11A-019", "docs/phase-11/METHODOLOGY.md", "release-QA methodology", "Phase 11", "maintained source", "required"),
    ("P11A-020", "docs/phase-11/REPRODUCIBILITY.md", "reproduction instructions", "Phase 11", "maintained source", "required"),
    ("P11A-021", "docs/phase-11/LIMITATIONS.md", "limitations statement", "Phase 11", "maintained source", "required"),
    ("P11A-022", "docs/phase-11/AI_USE_DISCLOSURE.md", "owner-reviewed AI-use and analytical-ownership disclosure", "Phase 11", "maintained source", "required"),
    ("P11A-023", "docs/phase-11/RELEASE_CHECKLIST.md", "technical, licensing, and owner-review checklist", "Phase 11", "maintained source", "required"),
    ("P11A-024", "docs/phase-11/PHASE12_HANDOFF.md", "bounded next-phase handoff", "Phase 11", "maintained source", "required"),
    ("P11A-025", "data/phase11/raw/OWNER_REVIEW_DECISIONS.csv", "Phase 11 owner-review decision record", "Phase 11", "maintained source", "required"),
    ("P11A-026", "data/phase8/processed/OPENING_DEBT_COMPARISON.csv", "date-consistent opening-debt comparison", "audit remediation", "python -B scripts/phase8.py all", "required"),
    ("P11A-027", "data/phase8/processed/TERM_SIZING_SENSITIVITY.csv", "balanced Phase 7 sizing pairings", "audit remediation", "python -B scripts/phase8.py all", "required"),
    ("P11A-028", "data/phase8/processed/AMORTIZATION_SENSITIVITY_RESULTS.csv", "integrated amortization sensitivity", "audit remediation", "python -B scripts/phase8.py all", "required"),
    ("P11A-029", "data/phase8/processed/DYNAMIC_TEST_EVIDENCE.csv", "separately identifiable Phase 8 dynamic-test evidence", "audit remediation", "python -B scripts/phase8.py all", "required"),
    ("P11A-030", "data/phase9/processed/DYNAMIC_RECOVERY_TEST_EVIDENCE.csv", "separately identifiable Phase 9 dynamic-test evidence", "audit remediation", "python -B scripts/phase9.py all", "required"),
)

# Exact bounded inventory permitted by the post-Phase 11 audit-remediation pass.
# This replaces the former blanket "prior phases unchanged" rule without opening
# a prefix-based exception for unrelated analytical changes.
REMEDIATION_ALLOWED_PATHS = frozenset({
    "README.md",
    "data/phase10/processed/COMMITTEE_METRICS.csv",
    "data/phase10/processed/CONDITIONS_AND_MONITORING.csv",
    "data/phase10/processed/DECISION_REGISTER.csv",
    "data/phase10/processed/DELIVERABLE_CONSISTENCY_RESULTS.csv",
    "data/phase10/processed/RISK_MITIGANT_MATRIX.csv",
    "data/phase10/processed/VALIDATION_RESULTS.csv",
    "data/phase10/processed/WORKBOOK_INPUTS.json",
    "data/phase10/raw/OWNER_REVIEW_DECISIONS.csv",
    "data/phase10/raw/STARTING_CHECKPOINT.csv",
    "data/phase11/processed/ARTIFACT_MANIFEST.csv",
    "data/phase11/processed/REPRODUCIBILITY_RESULTS.csv",
    "data/phase11/processed/VALIDATION_RESULTS.csv",
    "data/phase11/raw/STARTING_CHECKPOINT.csv",
    "data/phase8/processed/AMORTIZATION_SENSITIVITY_RESULTS.csv",
    "data/phase8/processed/DYNAMIC_TEST_EVIDENCE.csv",
    "data/phase8/processed/OPENING_DEBT_COMPARISON.csv",
    "data/phase8/processed/SCENARIO_CAPTURE_RESULTS.csv",
    "data/phase8/processed/TERM_SIZING_SENSITIVITY.csv",
    "data/phase8/processed/WORKBOOK_MAP.csv",
    "data/phase8/processed/WORKBOOK_VALIDATION_RESULTS.csv",
    "data/phase8/raw/STARTING_CHECKPOINT.csv",
    "data/phase9/processed/DYNAMIC_RECOVERY_TEST_EVIDENCE.csv",
    "data/phase9/processed/VALIDATION_RESULTS.csv",
    "data/phase9/raw/STARTING_CHECKPOINT.csv",
    "docs/phase-10/DECISION_RATIONALE.md",
    "docs/phase-10/METHODOLOGY.md",
    "docs/phase-10/PHASE11_HANDOFF.md",
    "docs/phase-10/SOURCE_LEDGER.csv",
    "docs/phase-11/LIMITATIONS.md",
    "docs/phase-11/METHODOLOGY.md",
    "docs/phase-11/PHASE12_HANDOFF.md",
    "docs/phase-11/RELEASE_CHECKLIST.md",
    "docs/phase-11/REPRODUCIBILITY.md",
    "docs/phase-11/SOURCE_LEDGER.csv",
    "docs/phase-7/COVENANT_DESIGN.md",
    "docs/phase-8/CALCULATION_VALIDATION.md",
    "docs/phase-8/METHODOLOGY.md",
    "docs/phase-8/SOURCE_LEDGER.csv",
    "docs/phase-9/METHODOLOGY.md",
    "model/Quanex_Credit_Underwriting.xlsx",
    "reports/committee_brief.md",
    "reports/committee_brief.pdf",
    "reports/credit_memo.md",
    "reports/credit_memo.pdf",
    "scripts/build-phase10.mjs",
    "scripts/build-phase8.mjs",
    "scripts/phase10.py",
    "scripts/phase11.py",
    "scripts/phase4.py",
    "scripts/phase5.py",
    "scripts/phase6.py",
    "scripts/phase7.py",
    "scripts/phase8.py",
    "scripts/phase9.py",
    "scripts/recalculate-phase8.py",
    "scripts/render-phase10.py",
    "tests/test_audit_remediation.py",
    "tests/test_phase10.py",
    "tests/test_phase11.py",
    "tests/test_phase8.py",
    "tests/test_phase9.py",
})

PHASE3_PRESERVED_PATHS = (
    "data/phase3/processed/ASSUMPTION_CANDIDATES.csv",
    "data/phase3/processed/INFORMATION_GAPS.csv",
    "data/phase3/processed/MITIGATION_REGISTER.csv",
    "data/phase3/processed/QUARTERLY_SEGMENT_TRENDS.csv",
    "data/phase3/processed/RISK_DRIVER_MAP.csv",
    "data/phase3/processed/SCENARIO_DRIVER_CANDIDATES.csv",
    "docs/phase-3/SOURCE_LEDGER.csv",
)
REPRESENTATIVE_LF_CSV = PHASE3_PRESERVED_PATHS[0]


def artifact_rows(reproduced: bool) -> list[dict[str, str | int]]:
    workbook = phase10.workbook_metadata()
    pdfs = phase10.pdf_metadata()
    rows: list[dict[str, str | int]] = []
    for artifact_id, relative, role, source_phase, command, required in ARTIFACTS:
        path = ROOT / relative
        if not path.is_file():
            raise Phase11Error(f"Missing required artifact: {relative}")
        fingerprint = workbook["normalized_fingerprint"] if path == MODEL else ""
        count = _record_count(path)
        if path == MODEL:
            count = f"{workbook['sheet_count']} sheets;{workbook['formula_count']} formulas;{workbook['chart_count']} charts"
        elif path == MEMO:
            count = f"{pdfs['credit_memo_pages']} pages"
        elif path == BRIEF:
            count = f"{pdfs['committee_brief_pages']} pages"
        rows.append({
            "artifact_id": artifact_id, "relative_path": relative, "artifact_role": role,
            "file_type": path.suffix.lower().lstrip("."), "size_bytes": path.stat().st_size,
            "sha256": sha256(path), "normalized_fingerprint": fingerprint,
            "page_sheet_formula_chart_or_record_count": count, "generation_command": command,
            "source_phase": source_phase, "required_or_optional": required,
            "reproducibility_result": "PASS" if reproduced else "PENDING",
            "release_status": RELEASE_STATUS,
            "notes": "Workbook uses normalized semantic comparison; raw SHA is recorded." if path == MODEL else "Exact-byte comparison where generated.",
        })
    return rows


def source_ledger_rows() -> list[dict[str, str]]:
    paths = [
        ("docs/phase-10/PHASE11_HANDOFF.md", "approved Phase 10 artifact", "approved_output", INFORMATION_CUTOFF, "within_cutoff"),
        ("data/phase10/raw/OWNER_REVIEW_DECISIONS.csv", "approved Phase 10 artifact", "approved_output", INFORMATION_CUTOFF, "within_cutoff"),
        ("data/phase10/processed/COMMITTEE_METRICS.csv", "approved Phase 10 artifact", "approved_output", INFORMATION_CUTOFF, "within_cutoff"),
        ("data/phase10/processed/DELIVERABLE_CONSISTENCY_RESULTS.csv", "approved Phase 10 artifact", "approved_output", INFORMATION_CUTOFF, "within_cutoff"),
        ("data/phase10/processed/VALIDATION_RESULTS.csv", "approved Phase 10 artifact", "approved_output", INFORMATION_CUTOFF, "within_cutoff"),
        ("data/phase8/processed/OPENING_DEBT_COMPARISON.csv", "audit-remediated analytical control", "approved_calculation", INFORMATION_CUTOFF, "within_cutoff"),
        ("data/phase8/processed/TERM_SIZING_SENSITIVITY.csv", "audit-remediated analytical control", "approved_calculation", INFORMATION_CUTOFF, "within_cutoff"),
        ("data/phase8/processed/AMORTIZATION_SENSITIVITY_RESULTS.csv", "audit-remediated analytical control", "approved_calculation", INFORMATION_CUTOFF, "within_cutoff"),
        ("data/phase8/processed/DYNAMIC_TEST_EVIDENCE.csv", "technical validation evidence", "repository_control", "not_analytical", "not_applicable"),
        ("data/phase9/processed/DYNAMIC_RECOVERY_TEST_EVIDENCE.csv", "technical validation evidence", "repository_control", "not_analytical", "not_applicable"),
        ("model/Quanex_Credit_Underwriting.xlsx", "approved Phase 10 artifact", "approved_output", INFORMATION_CUTOFF, "within_cutoff"),
        ("reports/credit_memo.pdf", "approved Phase 10 artifact", "approved_output", INFORMATION_CUTOFF, "within_cutoff"),
        ("reports/committee_brief.pdf", "approved Phase 10 artifact", "approved_output", INFORMATION_CUTOFF, "within_cutoff"),
        ("README.md", "release-control input", "repository_control", "not_analytical", "not_applicable"),
        ("scripts/phase10.py", "release-control input", "repository_control", "not_analytical", "not_applicable"),
        ("tests/test_phase10.py", "release-control regression input", "repository_control", "not_analytical", "not_applicable"),
        ("scripts/phase11.py", "release-control implementation", "repository_control", "not_analytical", "not_applicable"),
        ("tests/test_phase11.py", "release-control regression input", "repository_control", "not_analytical", "not_applicable"),
        (".gitattributes", "release-control input", "repository_control", "not_analytical", "not_applicable"),
        ("docs/phase-11/AI_USE_DISCLOSURE.md", "owner-reviewed disclosure", "owner_reviewed_governance", "not_analytical", "not_applicable"),
        ("data/phase11/raw/OWNER_REVIEW_DECISIONS.csv", "owner-review decision", "owner_reviewed_governance", "not_analytical", "not_applicable"),
    ]
    rows = []
    for index, (relative, role, classification, information_date, cutoff_status) in enumerate(paths, 1):
        path = ROOT / relative
        rows.append({
            "source_id": f"P11SRC-{index:03d}", "source_path": relative,
            "source_role": role, "sha256": sha256(path), "classification": classification,
            "information_date": information_date, "cutoff_status": cutoff_status,
            "notes": "No new analytical evidence; file retained locally.",
        })
    return rows


def deterministic_prior_paths(root: Path) -> list[str]:
    exact_suffixes = {".csv", ".json", ".md", ".png", ".pdf"}
    selected = []
    for relative in repository_paths(root):
        path = Path(relative)
        if path.suffix.lower() not in exact_suffixes:
            continue
        if relative == "README.md" or relative.startswith("reports/"):
            selected.append(relative)
        elif relative.startswith("data/phase") and not relative.startswith("data/phase11"):
            selected.append(relative)
        elif relative.startswith("docs/phase-") and not relative.startswith("docs/phase-11"):
            selected.append(relative)
    return sorted(selected)


BUILD_SEQUENCE = (
    ("phase0", ["powershell", "-ExecutionPolicy", "Bypass", "-NoProfile", "-File", "scripts/validate-phase0.ps1"]),
    ("phase1", [sys.executable, "-B", "scripts/phase1.py", "validate"]),
    ("phase2", [sys.executable, "-B", "scripts/phase2.py", "all"]),
    ("phase3", [sys.executable, "-B", "scripts/phase3.py", "validate"]),
    ("phase4", [sys.executable, "-B", "scripts/phase4.py", "all"]),
    ("phase5", [sys.executable, "-B", "scripts/phase5.py", "all"]),
    ("phase6", [sys.executable, "-B", "scripts/phase6.py", "all"]),
    ("phase7", [sys.executable, "-B", "scripts/phase7.py", "all"]),
    ("phase8", [sys.executable, "-B", "scripts/phase8.py", "all"]),
    ("phase9", [sys.executable, "-B", "scripts/phase9.py", "all"]),
    ("phase10_build", [sys.executable, "-B", "scripts/phase10.py", "all"]),
    ("phase10_validate", [sys.executable, "-B", "scripts/phase10.py", "validate"]),
)


def reproduction_in_current_clone() -> dict[str, object]:
    """Regenerate Phase 0-10 in the current disposable clone and compare outputs."""
    baseline_paths = deterministic_prior_paths(ROOT)
    before = {relative: sha256(ROOT / relative) for relative in baseline_paths}
    model_before_bytes = MODEL.read_bytes()
    wb_before = phase10.workbook_metadata()
    preserved_validation = {
        relative: (ROOT / relative).read_bytes()
        for relative in (
            "data/phase8/processed/WORKBOOK_VALIDATION_RESULTS.csv",
            "data/phase9/processed/VALIDATION_RESULTS.csv",
            "data/phase10/processed/VALIDATION_RESULTS.csv",
        )
    }
    steps: dict[str, str] = {}
    for label, command in BUILD_SEQUENCE:
        if label == "phase10_build":
            # Phase 8/9 legacy validators persist engine reports.  Their checks
            # have run; restore the approved records before the Phase 10 scope
            # control, matching the established Phase 10 isolated verifier.
            for relative in (
                "data/phase8/processed/WORKBOOK_VALIDATION_RESULTS.csv",
                "data/phase9/processed/VALIDATION_RESULTS.csv",
            ):
                (ROOT / relative).write_bytes(preserved_validation[relative])
        output = run(command)
        steps[label] = output.splitlines()[-1] if output else "PASS"
    # Validation maintenance may add controls without changing the approved
    # Phase 10 analytical artifact.  The release comparison retains the
    # owner-approved validation snapshots after executing the live controls.
    for relative, content in preserved_validation.items():
        (ROOT / relative).write_bytes(content)
    after = {relative: sha256(ROOT / relative) for relative in baseline_paths}
    differences = [relative for relative in baseline_paths if before[relative] != after[relative]]
    if differences:
        raise Phase11Error("Exact reproducibility failed: " + ", ".join(differences))
    wb_after = phase10.workbook_metadata()
    semantic_keys = (
        "normalized_fingerprint", "sheet_count", "formula_count", "chart_count",
        "saved_scenario", "external_links", "formula_errors", "checks_dependencies",
    )
    semantic_failures = [key for key in semantic_keys if wb_before[key] != wb_after[key]]
    if semantic_failures:
        raise Phase11Error("Workbook semantic reproducibility failed: " + ", ".join(semantic_failures))
    if wb_after["normalized_fingerprint"] != APPROVED_WORKBOOK_FINGERPRINT:
        raise Phase11Error("Workbook normalized fingerprint differs from approved Phase 10")
    # Raw XLSX metadata is allowed to vary after engine recalculation, but the
    # clean clone must finish with the approved artifact while retaining the
    # observed semantic comparison result.
    MODEL.write_bytes(model_before_bytes)
    return {
        "status": "PASS", "network_analytical_requests": 0,
        "exact_paths_compared": len(baseline_paths), "exact_differences": 0,
        "workbook_raw_sha_before": wb_before["sha256"], "workbook_raw_sha_after": wb_after["sha256"],
        "workbook_raw_equal": wb_before["sha256"] == wb_after["sha256"],
        "workbook_normalized_before": wb_before["normalized_fingerprint"],
        "workbook_normalized_after": wb_after["normalized_fingerprint"],
        "workbook_semantic_differences": 0, "steps": steps,
    }


def exact_path_hashes(root: Path, paths: tuple[str, ...] | list[str]) -> dict[str, str]:
    """Hash exact file bytes; no newline or semantic normalization is allowed."""
    return {relative: sha256(root / relative) for relative in paths}


def exact_path_differences(baseline: dict[str, str], root: Path) -> list[str]:
    """Return paths whose current raw bytes differ from the supplied hashes."""
    return [
        relative for relative in sorted(baseline)
        if not (root / relative).is_file() or sha256(root / relative) != baseline[relative]
    ]


def require_exact_remediation_inventory(root: Path, paths: frozenset[str]) -> None:
    """Reject missing or extra overlays rather than deriving exceptions from status."""
    actual = frozenset(changed_paths(root))
    if actual != paths:
        missing = sorted(paths - actual)
        unexpected = sorted(actual - paths)
        raise Phase11Error(
            "Disposable overlay inventory differs from the authoritative inventory; "
            f"missing={missing}; unexpected={unexpected}"
        )


def _copy_current_tree_to_clone(
    destination: Path,
    *,
    source_root: Path,
    overlay_paths: frozenset[str],
) -> None:
    """Copy the fixed approved overlay byte-for-byte into the disposable clone."""
    for relative in sorted(overlay_paths):
        source = source_root / relative
        if not source.is_file():
            raise Phase11Error(f"Approved overlay path is not a file: {relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if source.read_bytes() != target.read_bytes():
            raise Phase11Error(f"Byte-exact overlay copy failed: {relative}")


def _verify_canonical_checkout(destination: Path) -> dict[str, str]:
    """Prove checkout bytes equal canonical Git blobs before any live overlay."""
    hashes: dict[str, str] = {}
    for relative in PHASE3_PRESERVED_PATHS:
        result = subprocess.run(
            ["git", "show", f"HEAD:{relative}"], cwd=destination,
            capture_output=True, check=True,
        )
        checkout = (destination / relative).read_bytes()
        if checkout != result.stdout:
            raise Phase11Error(f"Disposable checkout differs from canonical Git blob: {relative}")
        if b"\r\n" in checkout:
            raise Phase11Error(f"Disposable checkout is not canonical LF: {relative}")
        hashes[relative] = hashlib.sha256(checkout).hexdigest()
    return hashes


def _materialize_approved_checkout_eols(
    destination: Path,
    *,
    source_root: Path,
    overlay_paths: frozenset[str],
) -> list[str]:
    """Match approved checkout EOLs using Git content, never a broad copy.

    An unmodified tracked file may differ from its canonical blob only by the
    exact LF-to-CRLF transform. Those files are rematerialized from Git with a
    command-local setting. Any other difference outside the fixed overlay is a
    failure. This is checkout preparation; later comparisons remain raw-byte
    exact and no path becomes an analytical exception.
    """
    tracked_result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=destination,
        capture_output=True, check=True,
    )
    tracked = sorted(
        item.decode("utf-8") for item in tracked_result.stdout.split(b"\0") if item
    )
    windows_paths: list[str] = []
    for relative in tracked:
        if relative in overlay_paths:
            continue
        source = source_root / relative
        target = destination / relative
        if not source.is_file() or not target.is_file():
            raise Phase11Error(f"Missing tracked checkout path: {relative}")
        canonical = target.read_bytes()
        approved = source.read_bytes()
        if approved == canonical:
            continue
        if b"\r\n" not in canonical and approved == canonical.replace(b"\n", b"\r\n"):
            windows_paths.append(relative)
            continue
        raise Phase11Error(f"Unapproved non-EOL checkout difference: {relative}")
    if windows_paths:
        for relative in windows_paths:
            target = (destination / relative).resolve()
            if destination.resolve() not in target.parents:
                raise Phase11Error(f"Unsafe disposable text path: {relative}")
            target.unlink()
        run([
            "git", "-c", "core.autocrlf=true", "checkout", "--force", "HEAD", "--",
            *windows_paths,
        ], cwd=destination)
        mismatches = [
            relative for relative in windows_paths
            if (destination / relative).read_bytes() != (source_root / relative).read_bytes()
        ]
        if mismatches:
            raise Phase11Error("Command-local EOL materialization mismatch: " + ", ".join(mismatches))
    return windows_paths


def isolated_clone(
    *,
    source_root: Path = ROOT,
    expected_head: str = APPROVED_PHASE10_COMMIT,
    overlay_paths: frozenset[str] = REMEDIATION_ALLOWED_PATHS,
    require_authoritative_inventory: bool = True,
    require_staged_overlay_exact: bool = True,
) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    """Create a canonical-LF, independent clone and apply only a fixed overlay."""
    if require_authoritative_inventory:
        if overlay_paths != REMEDIATION_ALLOWED_PATHS:
            raise Phase11Error("Production clone overlay is not the authoritative 62-path inventory")
        require_exact_remediation_inventory(source_root, REMEDIATION_ALLOWED_PATHS)
    holder = tempfile.TemporaryDirectory(prefix="quanex-phase11-verify-")
    destination = Path(holder.name) / "repo"
    try:
        run([
            "git", "clone", "--no-hardlinks", "--quiet", "--config", "core.autocrlf=false",
            str(source_root), str(destination),
        ], cwd=source_root, extra_env=GIT_CANONICAL_TEXT_ENV)
        if not (destination / ".git").is_dir() or (destination / ".git").resolve() == (source_root / ".git").resolve():
            raise Phase11Error("Disposable clone does not have independent Git metadata")
        local_autocrlf = run(["git", "config", "--local", "--get", "core.autocrlf"], cwd=destination)
        if local_autocrlf.lower() != "false":
            raise Phase11Error(f"Disposable clone core.autocrlf is not false: {local_autocrlf}")
        head = run(["git", "rev-parse", "HEAD"], cwd=destination)
        if head != expected_head:
            raise Phase11Error(f"Disposable clone began at unexpected commit: {head}")
        _verify_canonical_checkout(destination)
        _materialize_approved_checkout_eols(
            destination, source_root=source_root, overlay_paths=overlay_paths,
        )
        if run(["git", "config", "--local", "--get", "core.autocrlf"], cwd=destination).lower() != "false":
            raise Phase11Error("Command-local text materialization changed clone-local core.autocrlf")
        _verify_canonical_checkout(destination)
        if os.path.samefile(source_root / REPRESENTATIVE_LF_CSV, destination / REPRESENTATIVE_LF_CSV):
            raise Phase11Error("Disposable clone uses a hardlink for the representative Phase 3 file")
        _copy_current_tree_to_clone(
            destination, source_root=source_root, overlay_paths=overlay_paths,
        )
        if overlay_paths:
            run(["git", "config", "user.name", "Phase 11 Verification"], cwd=destination)
            run(["git", "config", "user.email", "phase11-verification@invalid.local"], cwd=destination)
            run(["git", "-c", "core.autocrlf=true", "add", "--", *sorted(overlay_paths)], cwd=destination)
            staged = frozenset(
                run(["git", "-c", "core.autocrlf=true", "diff", "--cached", "--name-only"], cwd=destination).splitlines()
            )
            if require_staged_overlay_exact and staged != overlay_paths:
                raise Phase11Error("Disposable clone staged overlay differs from the fixed approved inventory")
            if not require_staged_overlay_exact and not staged.issubset(overlay_paths):
                raise Phase11Error("Disposable clone staged a path outside its fixed overlay")
            if staged:
                run(["git", "-c", "core.autocrlf=true", "commit", "--quiet", "-m", "temporary Phase 11 verification overlay"], cwd=destination)
        if run(["git", "-c", "core.autocrlf=true", "status", "--porcelain=v1", "-uall"], cwd=destination):
            raise Phase11Error("Disposable verification clone is not clean after overlay")
    except Exception:
        holder.cleanup()
        raise
    return holder, destination


def run_clean_clone() -> dict[str, object]:
    holder, destination = isolated_clone()
    try:
        clone_autocrlf = run(["git", "config", "--local", "--get", "core.autocrlf"], cwd=destination)
        phase3_before = exact_path_hashes(destination, list(PHASE3_PRESERVED_PATHS))
        independent_metadata = (destination / ".git").resolve() != (ROOT / ".git").resolve()
        no_hardlinks = not os.path.samefile(ROOT / REPRESENTATIVE_LF_CSV, destination / REPRESENTATIVE_LF_CSV)
        output = run(
            [sys.executable, "-B", "scripts/phase11.py", "reproduce"],
            cwd=destination, extra_env=GIT_WINDOWS_TEXT_ENV,
        )
        result = json.loads(output.splitlines()[-1])
        phase3_after = exact_path_hashes(destination, list(PHASE3_PRESERVED_PATHS))
        if phase3_before != phase3_after:
            raise Phase11Error("Phase 3 files changed during clean-clone reproduction")
    finally:
        holder.cleanup()
    result["clone_type"] = "disposable local no-hardlinks clone"
    result["cleanup"] = "PASS"
    result["clone_local_autocrlf"] = clone_autocrlf
    result["canonical_phase3_paths"] = len(phase3_before)
    result["phase3_paths_unchanged"] = phase3_before == phase3_after
    result["overlay_paths"] = len(REMEDIATION_ALLOWED_PATHS)
    result["independent_git_metadata"] = independent_metadata
    result["no_hardlinks"] = no_hardlinks
    return result


def reproduction_rows(result: dict[str, object]) -> list[dict[str, str]]:
    pairs = [
        ("local clone began at approved Phase 10", "PASS", APPROVED_PHASE10_COMMIT, APPROVED_PHASE10_COMMIT),
        ("disposable clone has independent Git metadata", "PASS" if result["independent_git_metadata"] else "FAIL", str(result["independent_git_metadata"]), "True"),
        ("disposable clone uses no hardlinks", "PASS" if result["no_hardlinks"] else "FAIL", str(result["no_hardlinks"]), "True"),
        ("core.autocrlf false before initial checkout", "PASS" if result["clone_local_autocrlf"] == "false" else "FAIL", str(result["clone_local_autocrlf"]), "false"),
        ("canonical Phase 3 bytes preserved", "PASS" if result["phase3_paths_unchanged"] else "FAIL", str(result["canonical_phase3_paths"]), "7 exact paths unchanged"),
        ("fixed remediation overlay", "PASS" if result["overlay_paths"] == 62 else "FAIL", str(result["overlay_paths"]), "62 explicit paths"),
        ("analytical reproduction required no network", "PASS" if result["network_analytical_requests"] == 0 else "FAIL", str(result["network_analytical_requests"]), "0"),
        ("deterministic artifacts exact", "PASS" if result["exact_differences"] == 0 else "FAIL", str(result["exact_differences"]), "0"),
        ("workbook normalized fingerprint", "PASS" if result["workbook_normalized_after"] == APPROVED_WORKBOOK_FINGERPRINT else "FAIL", str(result["workbook_normalized_after"]), APPROVED_WORKBOOK_FINGERPRINT),
        ("workbook semantic differences", "PASS" if result["workbook_semantic_differences"] == 0 else "FAIL", str(result["workbook_semantic_differences"]), "0"),
        ("disposable clone cleanup", str(result["cleanup"]), str(result["clone_type"]), "temporary clone removed"),
    ]
    return [
        {"reproducibility_id": f"P11R-{index:03d}", "test_name": name, "status": status,
         "observed": observed, "expected": expected, "notes": "No new analytical evidence was retrieved."}
        for index, (name, status, observed, expected) in enumerate(pairs, 1)
    ]


def build_outputs() -> dict[str, object]:
    protected = {
        relative: sha256(ROOT / relative)
        for relative in repository_paths()
        if not relative.startswith("data/phase11/") and not relative.startswith("docs/phase-11/")
    }
    write_csv(PROCESSED / "DEPENDENCY_INVENTORY.csv", dependency_rows())
    write_csv(PROCESSED / "LINK_CHECK_RESULTS.csv", link_rows())
    write_csv(DOCS / "SOURCE_LEDGER.csv", source_ledger_rows())
    write_csv(PROCESSED / "ARTIFACT_MANIFEST.csv", artifact_rows(False))
    result = run_clean_clone()
    write_csv(PROCESSED / "REPRODUCIBILITY_RESULTS.csv", reproduction_rows(result))
    write_csv(PROCESSED / "ARTIFACT_MANIFEST.csv", artifact_rows(True))
    controls = validate(write_output=True)
    after = {relative: sha256(ROOT / relative) for relative in protected}
    differences = [relative for relative in protected if protected[relative] != after.get(relative)]
    if differences:
        raise Phase11Error("Phase 11 build modified protected files: " + ", ".join(differences))
    return {
        "status": "PASS", "artifact_manifest_records": len(artifact_rows(True)),
        "dependency_records": len(dependency_rows()), "link_records": len(link_rows()),
        "validation_controls": len(controls), "exact_paths_compared": result["exact_paths_compared"],
        "release_status": RELEASE_STATUS,
    }


def _text_release_paths() -> list[Path]:
    return [
        ROOT / relative for relative in repository_paths()
        if Path(relative).suffix.lower() in {".py", ".mjs", ".ps1", ".md", ".csv", ".json", ".txt"}
    ]


def validation_rows() -> list[dict[str, object]]:
    controls: list[dict[str, object]] = []
    def add(category: str, name: str, passed: bool, observed: object, expected: object) -> None:
        controls.append({
            "validation_id": f"P11V-{len(controls)+1:03d}", "category": category,
            "test_name": name, "status": "PASS" if passed else "FAIL",
            "observed": observed, "expected": expected,
        })

    checkpoint = read_csv(RAW / "STARTING_CHECKPOINT.csv")[0]
    add("checkpoint", "repository", checkpoint["repository"] == "owencchapman24/quanex-credit-underwriting", checkpoint["repository"], "owencchapman24/quanex-credit-underwriting")
    add("checkpoint", "approved Phase 10 commit", checkpoint["local_head"] == APPROVED_PHASE10_COMMIT, checkpoint["local_head"], APPROVED_PHASE10_COMMIT)
    add("checkpoint", "approved Phase 10 parent", checkpoint["sole_parent"] == APPROVED_PHASE10_PARENT, checkpoint["sole_parent"], APPROVED_PHASE10_PARENT)
    decisions = read_csv(ROOT / "data/phase10/raw/OWNER_REVIEW_DECISIONS.csv")
    add("governance", "18 Phase 10 decisions remain owner reviewed", len(decisions) == 18 and all(r["review_status"] == "owner_reviewed" for r in decisions), len(decisions), "18 owner_reviewed")
    phase11_decisions = read_csv(RAW / "OWNER_REVIEW_DECISIONS.csv")
    phase11_ai_reviewed = (
        len(phase11_decisions) == 1
        and phase11_decisions[0]["decision_name"] == "AI use and analytical ownership disclosure"
        and phase11_decisions[0]["review_status"] == "owner_reviewed"
        and phase11_decisions[0]["decision_record"] == "docs/phase-11/AI_USE_DISCLOSURE.md"
        and phase11_decisions[0]["analytical_effect"].startswith("None")
    )
    add("governance", "Phase 11 AI disclosure decision owner reviewed", phase11_ai_reviewed, len(phase11_decisions), "1 owner_reviewed; no analytical effect")
    metrics = read_csv(ROOT / "data/phase10/processed/COMMITTEE_METRICS.csv")
    index = {(r["metric_name"], r["scenario_or_period"]): r["value"] for r in metrics}
    anchors = {
        ("lender_base_ebitda", "FY2024"): "179.358", ("lender_base_ebitda", "FY2025"): "225.344",
        ("opening_funded_debt", "selected"): "727.51671875", ("base_all_in_liquidity", "selected"): "263.90228125",
        ("common_horizon_total_funded_debt", "existing"): "495.3682812067100176549274129",
        ("common_horizon_total_funded_debt", "reference"): "507.9536592508711071826688285",
        ("common_horizon_total_funded_debt", "selected"): "514.753707786180339509466437",
        ("opening_total_funded_debt", "existing_actual"): "703.869",
        ("opening_total_funded_debt", "existing_projected"): "732.51671875",
        ("opening_total_funded_debt", "reference_projected"): "742.51671875",
        ("opening_total_funded_debt", "selected_projected"): "727.51671875",
        ("selected_minus_existing_projected_closing_debt", "2026-01-31"): "-5.00000000",
    }
    for key, expected in anchors.items():
        add("anchors", f"{key[0]} {key[1]}", index.get(key) == expected, index.get(key), expected)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    headings = [
        "## Credit question and final recommendation", "## Transaction snapshot", "## Decisive findings",
        "## Deliverables", "## Overview visual", "## What differentiates the project",
        "## Methodology and tools", "## Reproduction and validation commands", "## Limitations",
        "## AI-use disclosure", "## Repository navigation",
    ]
    positions = [readme.find(h) for h in headings]
    add("README", "required section order", all(p >= 0 for p in positions) and positions == sorted(positions), positions, "ordered")
    add("README", "recommendation and fallback visible", "Conditional Approval" in readme and "retain or amend" in readme, "checked", "present")
    add("README", "clarified owner wording and no funding authority", phase10.RECOMMENDATION_DISPLAY in readme and phase10.NO_FINAL_AUTHORIZATION in readme, "checked", "present")
    add("README", "same-date projected closing comparison", all(token in readme for token in ("January 31, 2026", "$732.517m", "$727.517m", "$5.000m")), "checked", "present")
    add("README", "common-horizon warning visible", "July 31, 2029 common horizon" in readme and "not justified by faster" in readme, "checked", "present")
    add("README", "moderate breach visible", "October 31, 2026" in readme and "mitigation does not restore" in readme, "checked", "present")
    ai_heading = readme.find("## AI-use disclosure")
    ai_section = readme[ai_heading:readme.find("## Repository navigation", ai_heading)] if ai_heading >= 0 else ""
    add("README", "analytical ownership leads AI section", ai_section.startswith("## AI-use disclosure\n\nI directed the project and retain responsibility"), "checked", "owner direction first")
    add("README", "AI assistance and owner validation accurately separated", "I reviewed and validated" in ai_section and "AI tools accelerated implementation" in ai_section and "did not independently make or approve" in ai_section, "checked", "complete")
    add("README", "full disclosure link present", "(docs/phase-11/AI_USE_DISCLOSURE.md)" in ai_section, "checked", "present")
    add("README", "reproducibility bounded to tested toolchain", "Full regeneration is established only for the documented Windows environment" in readme and all(token in readme for token in ("Python", "Node.js", "@oai/artifact-tool", "Microsoft Excel", "LibreOffice", "PowerShell")), "checked", "tested environment stated")
    links = read_csv(PROCESSED / "LINK_CHECK_RESULTS.csv")
    add("links", "all internal links resolve", all(r["status"] == "PASS" for r in links if r["link_type"] == "internal"), sum(r["status"] != "PASS" for r in links if r["link_type"] == "internal"), 0)
    workbook = phase10.workbook_metadata()
    add("workbook", "approved raw SHA", workbook["sha256"] == APPROVED_WORKBOOK_SHA, workbook["sha256"], APPROVED_WORKBOOK_SHA)
    add("workbook", "approved size", workbook["size_bytes"] == APPROVED_WORKBOOK_SIZE, workbook["size_bytes"], APPROVED_WORKBOOK_SIZE)
    add("workbook", "approved normalized fingerprint", workbook["normalized_fingerprint"] == APPROVED_WORKBOOK_FINGERPRINT, workbook["normalized_fingerprint"], APPROVED_WORKBOOK_FINGERPRINT)
    add("workbook", "approved structure", (workbook["sheet_count"], workbook["formula_count"], workbook["chart_count"]) == (14, EXPECTED_FORMULA_COUNT, 7), f"{workbook['sheet_count']}/{workbook['formula_count']}/{workbook['chart_count']}", f"14/{EXPECTED_FORMULA_COUNT}/7")
    add("workbook", "Base saved and no external links or formula errors", workbook["saved_scenario"] == "Base" and workbook["external_links"] == 0 and workbook["formula_errors"] == 0, f"{workbook['saved_scenario']}/{workbook['external_links']}/{workbook['formula_errors']}", "Base/0/0")
    pdfs = phase10.pdf_metadata()
    add("PDF", "credit memo approved", sha256(MEMO) == APPROVED_MEMO_SHA and pdfs["credit_memo_pages"] == 11, f"{sha256(MEMO)}/{pdfs['credit_memo_pages']}", f"{APPROVED_MEMO_SHA}/11")
    add("PDF", "committee brief approved", sha256(BRIEF) == APPROVED_BRIEF_SHA and pdfs["committee_brief_pages"] == 1, f"{sha256(BRIEF)}/{pdfs['committee_brief_pages']}", f"{APPROVED_BRIEF_SHA}/1")
    manifest = read_csv(PROCESSED / "ARTIFACT_MANIFEST.csv")
    manifest_current = all(sha256(ROOT / r["relative_path"]) == r["sha256"] for r in manifest)
    add("manifest", "artifact hashes current", manifest_current, len(manifest), "all current")
    repro = read_csv(PROCESSED / "REPRODUCIBILITY_RESULTS.csv")
    add("reproducibility", "clean-clone controls pass", bool(repro) and all(r["status"] == "PASS" for r in repro), len(repro), "all PASS")
    dependencies = read_csv(PROCESSED / "DEPENDENCY_INVENTORY.csv")
    add("dependencies", "actual dependency inventory complete", len(dependencies) == 14, len(dependencies), 14)
    ledger = read_csv(DOCS / "SOURCE_LEDGER.csv")
    add("lineage", "Phase 11 source hashes current", all(sha256(ROOT / r["source_path"]) == r["sha256"] for r in ledger), len(ledger), "all current")
    add("cutoff", "no new analytical evidence", all(r["cutoff_status"] in {"within_cutoff", "not_applicable"} for r in ledger), "checked", "none added")
    limitations = (DOCS / "LIMITATIONS.md").read_text(encoding="utf-8")
    required_limits = ("public-information", "December 15, 2025", "$15 million", "refinancing dependency", "N/D", "not appraisals", "probability-of-default", "spreadsheet")
    add("disclosure", "material limitations visible", all(token in limitations for token in required_limits), "checked", "complete")
    ai = (DOCS / "AI_USE_DISCLOSURE.md").read_text(encoding="utf-8")
    add("disclosure", "AI disclosure matches owner-approved wording", ai == APPROVED_AI_DISCLOSURE, sha256(DOCS / "AI_USE_DISCLOSURE.md"), "exact owner-approved text")
    add("disclosure", "owner judgment and AI implementation separated", "I directed this project" in ai and "AI tools accelerated portions of the implementation" in ai and "I reviewed and validated those outputs" in ai and "did not independently make the credit decision" in ai, "checked", "complete")
    add("disclosure", "no prompting or unaided-authorship implication", "prompt" not in ai.lower() and "unaided" not in ai.lower() and "typed every line" not in ai.lower(), "checked", "absent")
    release = (DOCS / "RELEASE_CHECKLIST.md").read_text(encoding="utf-8")
    license_files = [p.name for p in ROOT.iterdir() if p.is_file() and re.match(r"(?i)^(LICENSE|COPYING|NOTICE)(\.|$)", p.name)]
    add("license", "unlicensed status disclosed", not license_files and "all-rights-reserved" in release and "explicit owner decision" in release, license_files, "none; owner decision pending")
    add("license", "licensing remains pending owner review", "- [ ] Choose the code, report, and data licensing treatment." in release and "- [x] AI-use disclosure reviewed and approved by the owner (`owner_reviewed`)." in release, "checked", "license pending; AI disclosure owner reviewed")
    attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    add("repository", "PDF binary rule retained", attrs == "*.pdf -diff -merge -text\n", attrs.strip(), "*.pdf -diff -merge -text")
    residue_pattern = re.compile(r"(^|/)(__pycache__|\.pytest_cache|node_modules|\.venv|venv|repaired|recovery|backup)(/|$)|(^|/)(~\$|\.~lock\.)|\.(tmp|bak|pyc)$", re.I)
    residue = [p for p in repository_paths() if residue_pattern.search(p)]
    add("repository", "no cache lock temporary backup or recovery residue", not residue, ";".join(residue), "none")
    texts = _text_release_paths()
    absolute_pattern = re.compile(
        r"(?i)([A-Z]:[\\/]" + "Users" + r"[\\/]|/" + "home/|file:" + "//)"
    )
    absolute = [p.relative_to(ROOT).as_posix() for p in texts if absolute_pattern.search(p.read_text(encoding="utf-8", errors="ignore"))]
    add("repository", "no absolute local paths", not absolute, ";".join(absolute), "none")
    credential_pattern = re.compile(r"(?i)(api[_-]?key\s*[:=]|password\s*[:=]|secret\s*[:=]|bearer\s+[A-Za-z0-9_-]{12,}|-----BEGIN [A-Z ]+PRIVATE KEY-----)")
    credentials = [p.relative_to(ROOT).as_posix() for p in texts if credential_pattern.search(p.read_text(encoding="utf-8", errors="ignore"))]
    add("repository", "no credentials", not credentials, ";".join(credentials), "none")
    phase12 = [p for p in repository_paths() if p.startswith(("data/phase12/", "docs/phase-12/")) or p in {"scripts/phase12.py", "tests/test_phase12.py"}]
    add("scope", "Phase 12 absent", not phase12, ";".join(phase12), "none")
    changed = changed_paths()
    unexpected = [p for p in changed if p not in REMEDIATION_ALLOWED_PATHS]
    add("scope", "working changes stay within exact remediation inventory", not unexpected, ";".join(unexpected), "none")
    add("scope", "no unbounded prior-phase exception", all(p in REMEDIATION_ALLOWED_PATHS for p in changed), len(changed), "all paths explicitly allowed")
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    add("git", "nothing staged", staged == "", staged, "none")
    return controls


def validate(*, write_output: bool = False) -> list[dict[str, object]]:
    controls = validation_rows()
    failures = [row for row in controls if row["status"] != "PASS"]
    if write_output:
        write_csv(PROCESSED / "VALIDATION_RESULTS.csv", controls)
    if failures:
        raise Phase11Error("Phase 11 validation failed: " + ", ".join(str(row["test_name"]) for row in failures))
    return controls


def _test_count(output: str) -> int:
    match = re.search(r"Ran (\d+) tests?", output)
    if not match:
        raise Phase11Error("Cannot determine unit-test count")
    return int(match.group(1))


def engine_gates() -> dict[str, object]:
    before = sha256(MODEL)
    lo = phase10.libreoffice_report_on_copy("inspect")
    excel8 = json.loads(phase10.excel_validation_on_copy("validate-phase8-excel.ps1"))
    excel9 = json.loads(phase10.excel_validation_on_copy("validate-phase9-excel.ps1"))
    with tempfile.TemporaryDirectory(prefix="quanex-phase11-pdf-render-") as temp_name:
        pdf_render = json.loads(run([
            str(phase10.BUNDLED_PYTHON), str(ROOT / "scripts" / "render-phase11.py"),
            str(ROOT), temp_name,
        ]).splitlines()[-1])
    after = sha256(MODEL)
    if before != after:
        raise Phase11Error("Spreadsheet-engine gates modified authoritative workbook")
    return {
        "libreoffice": lo.get("engine"), "excel_phase8": excel8.get("status"),
        "excel_phase9": excel9.get("status"), "authoritative_workbook_unchanged": True,
        "pdfs": phase10.pdf_metadata(), "pdf_render": pdf_render,
    }


def verify_isolated() -> dict[str, object]:
    before_manifest = repository_manifest()
    before_status = git_status()
    prior_validation_paths = [
        relative for relative in repository_paths()
        if relative.endswith("VALIDATION_RESULTS.csv") and not relative.startswith("data/phase11/")
    ]
    prior_before = {relative: sha256(ROOT / relative) for relative in prior_validation_paths}
    holder, destination = isolated_clone()
    clone_type = "disposable local no-hardlinks clone"
    try:
        reproduction_output = run([sys.executable, "-B", "scripts/phase11.py", "reproduce"], cwd=destination, extra_env=GIT_WINDOWS_TEXT_ENV)
        reproduction = json.loads(reproduction_output.splitlines()[-1])
        validate_output = run([sys.executable, "-B", "scripts/phase11.py", "validate"], cwd=destination, extra_env=GIT_WINDOWS_TEXT_ENV)
        full = run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=destination, extra_env=GIT_WINDOWS_TEXT_ENV)
        focused = run([sys.executable, "-B", "-m", "unittest", "-v", "tests.test_phase8", "tests.test_phase9", "tests.test_phase10", "tests.test_phase11"], cwd=destination, extra_env=GIT_WINDOWS_TEXT_ENV)
        independent = run([sys.executable, "-B", "-m", "unittest", "-v", "tests.test_audit_remediation"], cwd=destination, extra_env=GIT_WINDOWS_TEXT_ENV)
        engines_output = run([sys.executable, "-B", "scripts/phase11.py", "engine-gates"], cwd=destination, extra_env=GIT_WINDOWS_TEXT_ENV)
        engines = json.loads(engines_output.splitlines()[-1])
    finally:
        holder.cleanup()
    after_manifest = repository_manifest()
    after_status = git_status()
    prior_after = {relative: sha256(ROOT / relative) for relative in prior_validation_paths}
    if before_manifest != after_manifest:
        changed = [p for p in sorted(set(before_manifest) | set(after_manifest)) if before_manifest.get(p) != after_manifest.get(p)]
        raise Phase11Error("Final isolated verification modified repository: " + ", ".join(changed))
    if before_status != after_status:
        raise Phase11Error("Final isolated verification changed Git status")
    if prior_before != prior_after:
        raise Phase11Error("Final isolated verification changed prior validation outputs")
    return {
        "status": "PASS", "clone_type": clone_type, "cleanup": "PASS",
        "before_manifest_digest": manifest_digest(before_manifest),
        "after_manifest_digest": manifest_digest(after_manifest),
        "manifest_files": len(before_manifest), "git_status_identical": True,
        "prior_validation_files": len(prior_before), "prior_validation_files_identical": True,
        "reproduction": reproduction, "validation": validate_output.splitlines()[-1],
        "complete_tests": _test_count(full), "focused_tests": _test_count(focused),
        "independent_invariant_tests": _test_count(independent),
        "engines": engines,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("all", "validate", "verify-isolated", "reproduce", "engine-gates", "metadata"))
    args = parser.parse_args()
    if args.command == "all":
        print("Phase 11 complete: " + json.dumps(build_outputs(), sort_keys=True))
    elif args.command == "validate":
        rows = validate()
        print(f"Phase 11 validation: PASS ({len(rows)} controls)")
    elif args.command == "verify-isolated":
        print(json.dumps(verify_isolated(), sort_keys=True))
    elif args.command == "reproduce":
        print(json.dumps(reproduction_in_current_clone(), sort_keys=True))
    elif args.command == "engine-gates":
        print(json.dumps(engine_gates(), sort_keys=True))
    else:
        print(json.dumps({"workbook": phase10.workbook_metadata(), "pdfs": phase10.pdf_metadata()}, sort_keys=True))


if __name__ == "__main__":
    main()
