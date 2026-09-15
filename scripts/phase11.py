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
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "phase11"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
DOCS = ROOT / "docs" / "phase-11"
MODEL = ROOT / "model" / "Quanex_Credit_Underwriting.xlsx"
MEMO = ROOT / "reports" / "credit_memo.pdf"
BRIEF = ROOT / "reports" / "committee_brief.pdf"
# Historical Phase 11 starting checkpoint.  Release verification resolves the
# commit selected by the caller and never treats this historical SHA as the
# current release candidate.
APPROVED_PHASE10_COMMIT = "ce656ebfca67f2bd34a78273f72367e39c0c2037"
APPROVED_PHASE10_PARENT = "9fca23a949d1f8d8dee6f37906cb086ec6cda994"
APPROVED_WORKBOOK_SHA = "6e31a259aebe14b4e9a379348d4b686f6a1148a6db743c72646a783321167454"
APPROVED_WORKBOOK_SIZE = 301_362
APPROVED_WORKBOOK_FINGERPRINT = "4d927e955f1cc9ede829aab41b26e43f62cfe23812d5018f54c12b73028b923a"
EXPECTED_FORMULA_COUNT = 3473
APPROVED_MEMO_SHA = "dea0465ae7ee29be0c993c1ac4f57ac396b872763b2c657fded1edcb9c5e95b8"
APPROVED_BRIEF_SHA = "af8d3799f511daa77df202274b4d7dde670e2e6b04c0c4c98f482b896a5627d6"
INFORMATION_CUTOFF = "2025-12-15"
RELEASE_STATUS = "GO_TO_OWNER_REVIEW"
RELEASE_MODE = "clean_release"
OVERLAY_MODE = "precommit_overlay_review"
PHASE11_GENERATED_OUTPUT_PATHS = frozenset({
    "data/phase11/processed/ARTIFACT_MANIFEST.csv",
    "data/phase11/processed/DEPENDENCY_INVENTORY.csv",
    "data/phase11/processed/LINK_CHECK_RESULTS.csv",
    "data/phase11/processed/REPRODUCIBILITY_RESULTS.csv",
    "data/phase11/processed/VALIDATION_RESULTS.csv",
    "docs/phase-11/SOURCE_LEDGER.csv",
})
EXCEL_PHASE8_REQUIRED_PROBE_CASES = frozenset({
    "base",
    "spread_plus_100bp",
    "amortization_10_percent",
    "fy2026_q2_ebitda_plus_10_percent",
    "dso_plus_10_days",
    "combined_rate_amortization_ebitda_dso",
    "tight_liquidity",
    "no_waiver_stress",
    "balanced_funding_signature_collision",
    "warning_threshold_equalities",
})
EXCEL_PHASE9_REQUIRED_METHODS = frozenset({
    "none", "ribbon_calculate_now", "calculate_sheet", "f9",
    "ctrl_alt_f9", "ctrl_alt_shift_f9",
})
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


def git_config_digest(root: Path = ROOT) -> str:
    """Hash repository-local, global, and system Git configuration read-only.

    Only the digest is retained so release evidence can prove that verification
    did not mutate Git configuration without exposing identity or credential
    helper settings in logs.
    """
    digest = hashlib.sha256()
    for scope in ("--local", "--global", "--system"):
        result = subprocess.run(
            ["git", "config", scope, "--null", "--list"], cwd=root,
            capture_output=True, check=False,
        )
        digest.update(scope.encode("ascii"))
        digest.update(b"\0")
        digest.update(str(result.returncode).encode("ascii"))
        digest.update(b"\0")
        digest.update(result.stdout)
        digest.update(b"\0")
        digest.update(result.stderr)
        digest.update(b"\0")
    return digest.hexdigest()


def generation_git_status(root: Path) -> str:
    """Return status under the documented Windows generated-text semantics."""
    return run([
        "git", "-c", "core.autocrlf=true", "status", "--porcelain=v1", "-uall",
    ], cwd=root)


def changed_paths(root: Path = ROOT) -> list[str]:
    paths: list[str] = []
    for line in git_status(root).splitlines():
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path.replace("\\", "/"))
    return paths


def git_head(root: Path = ROOT) -> str:
    return run(["git", "rev-parse", "HEAD"], cwd=root)


def resolve_commit(root: Path, commitish: str) -> str:
    """Resolve an explicitly selected commit without fetching from a remote."""
    if not commitish:
        raise Phase11Error("A commit must be selected explicitly")
    return run(["git", "rev-parse", "--verify", f"{commitish}^{{commit}}"], cwd=root)


def read_overlay_manifest(path: Path) -> frozenset[str]:
    """Read an explicit one-repository-path-per-line pre-commit overlay."""
    if not path.is_file():
        raise Phase11Error(f"Overlay manifest does not exist: {path}")
    paths: list[str] = []
    for number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        raw = raw_line.strip()
        if not raw or raw.startswith("#"):
            continue
        candidate = raw.replace("\\", "/")
        parsed = PurePosixPath(candidate)
        if (
            parsed.is_absolute()
            or re.match(r"^[A-Za-z]:", candidate)
            or any(part in {"", ".", ".."} for part in parsed.parts)
            or (parsed.parts and parsed.parts[0].lower() == ".git")
            or candidate != parsed.as_posix()
        ):
            raise Phase11Error(f"Invalid overlay path on line {number}: {raw}")
        paths.append(candidate)
    if not paths:
        raise Phase11Error("Overlay manifest is empty")
    duplicates = sorted({path for path in paths if paths.count(path) > 1})
    if duplicates:
        raise Phase11Error("Overlay manifest contains duplicate paths: " + ", ".join(duplicates))
    return frozenset(paths)


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
    ("P11A-031", "data/phase9/processed/PHASE8_BASELINE_VERIFICATION.csv", "pre-overlay Phase 8 semantic and source-state verification", "audit remediation", "python -B scripts/phase9.py all", "required"),
    ("P11A-032", "data/phase10/processed/FINAL_WORKBOOK_PHASE8_DYNAMIC_EVIDENCE.csv", "Phase 10 final-workbook Phase 8 integration evidence", "audit remediation", "python -B scripts/phase10.py all", "required"),
    ("P11A-033", "data/phase10/processed/FINAL_WORKBOOK_PHASE9_DYNAMIC_EVIDENCE.csv", "Phase 10 final-workbook Phase 9 recovery evidence", "audit remediation", "python -B scripts/phase10.py all", "required"),
)

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

# Phase 0 is validated, not regenerated, by BUILD_SEQUENCE.  These two
# documents are also raw-byte Phase 10 provenance inputs, so converting them
# to a platform checkout profile would change only the downstream source
# signature and ledger rather than reproducing a generated artifact.
PHASE0_STATIC_SOURCE_TEXT_PATHS = frozenset({
    "docs/phase-0/CASE_CHARTER.md",
    "docs/phase-0/EXISTING_FINANCING.md",
})
WINDOWS_GENERATED_TEXT_SUFFIXES = frozenset({".md", ".json"})


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
        ("data/phase9/processed/PHASE8_BASELINE_VERIFICATION.csv", "technical workbook-lineage evidence", "repository_control", "not_analytical", "not_applicable"),
        ("data/phase10/processed/FINAL_WORKBOOK_PHASE8_DYNAMIC_EVIDENCE.csv", "final-workbook technical validation evidence", "repository_control", "not_analytical", "not_applicable"),
        ("data/phase10/processed/FINAL_WORKBOOK_PHASE9_DYNAMIC_EVIDENCE.csv", "final-workbook technical validation evidence", "repository_control", "not_analytical", "not_applicable"),
        ("model/Quanex_Credit_Underwriting.xlsx", "approved Phase 10 artifact", "approved_output", INFORMATION_CUTOFF, "within_cutoff"),
        ("reports/credit_memo.pdf", "approved Phase 10 artifact", "approved_output", INFORMATION_CUTOFF, "within_cutoff"),
        ("reports/committee_brief.pdf", "approved Phase 10 artifact", "approved_output", INFORMATION_CUTOFF, "within_cutoff"),
        ("README.md", "release-control input", "repository_control", "not_analytical", "not_applicable"),
        ("scripts/phase2.py", "historical-interest evidence correction", "repository_control", "not_analytical", "not_applicable"),
        ("tests/test_phase2.py", "historical-interest regression input", "repository_control", "not_analytical", "not_applicable"),
        ("scripts/remediation_controls.py", "byte-exact prior-phase remediation authorization", "repository_control", "not_analytical", "not_applicable"),
        ("scripts/phase6.py", "paid-versus-payable coverage correction", "repository_control", "not_analytical", "not_applicable"),
        ("tests/test_phase6.py", "paid-versus-payable regression input", "repository_control", "not_analytical", "not_applicable"),
        ("scripts/phase7.py", "covenant and warning-boundary correction", "repository_control", "not_analytical", "not_applicable"),
        ("tests/test_phase7.py", "covenant regression input", "repository_control", "not_analytical", "not_applicable"),
        ("scripts/phase8.py", "workbook evidence and release-control implementation", "repository_control", "not_analytical", "not_applicable"),
        ("scripts/build-phase8.mjs", "workbook integration implementation", "repository_control", "not_analytical", "not_applicable"),
        ("scripts/recalculate-phase8.py", "LibreOffice live-input probe implementation", "repository_control", "not_analytical", "not_applicable"),
        ("scripts/validate-phase8-excel.ps1", "Excel live-input probe implementation", "repository_control", "not_analytical", "not_applicable"),
        ("tests/test_phase8.py", "workbook integration regression input", "repository_control", "not_analytical", "not_applicable"),
        ("scripts/phase9.py", "recovery evidence and workbook-lineage implementation", "repository_control", "not_analytical", "not_applicable"),
        ("scripts/validate-phase9-excel.ps1", "Excel recovery interaction probe implementation", "repository_control", "not_analytical", "not_applicable"),
        ("tests/test_phase9.py", "recovery and lineage regression input", "repository_control", "not_analytical", "not_applicable"),
        ("scripts/workbook_semantics.py", "semantic workbook comparison implementation", "repository_control", "not_analytical", "not_applicable"),
        ("tests/test_workbook_semantics.py", "semantic workbook comparison regression input", "repository_control", "not_analytical", "not_applicable"),
        ("scripts/xlsx_package.py", "deterministic XLSX package canonicalization", "repository_control", "not_analytical", "not_applicable"),
        ("tests/test_xlsx_package.py", "deterministic XLSX package regression input", "repository_control", "not_analytical", "not_applicable"),
        ("scripts/phase10.py", "release-control input", "repository_control", "not_analytical", "not_applicable"),
        ("scripts/build-phase10.mjs", "final-workbook overlay implementation", "repository_control", "not_analytical", "not_applicable"),
        ("scripts/render-phase10.py", "final-document renderer", "repository_control", "not_analytical", "not_applicable"),
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
    exact_suffixes = {".csv", ".json", ".md", ".png", ".pdf", ".xlsx"}
    selected = []
    for relative in repository_paths(root):
        path = Path(relative)
        if path.suffix.lower() not in exact_suffixes:
            continue
        if relative in {"README.md", "model/Quanex_Credit_Underwriting.xlsx"} or relative.startswith("reports/"):
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

# These files are written by the named build steps and are part of a fresh
# reproduction claim.  Compare them immediately after their owning step so a
# later build cannot overwrite a discrepancy and no restoration can hide it.
FRESH_VALIDATION_BY_STEP: dict[str, tuple[str, ...]] = {
    "phase8": ("data/phase8/processed/WORKBOOK_VALIDATION_RESULTS.csv",),
    "phase9": ("data/phase9/processed/VALIDATION_RESULTS.csv",),
    "phase10_build": (
        "data/phase10/processed/VALIDATION_RESULTS.csv",
        "data/phase10/processed/FINAL_WORKBOOK_PHASE8_DYNAMIC_EVIDENCE.csv",
        "data/phase10/processed/FINAL_WORKBOOK_PHASE9_DYNAMIC_EVIDENCE.csv",
    ),
    "phase10_validate": ("data/phase10/processed/VALIDATION_RESULTS.csv",),
}


def require_fresh_validation_outputs(
    root: Path,
    baseline: dict[str, str],
    step: str,
    paths: tuple[str, ...],
) -> list[dict[str, str]]:
    """Fail on a fresh validation difference before any later step can mask it."""
    records: list[dict[str, str]] = []
    for relative in paths:
        path = root / relative
        if relative not in baseline or not path.is_file():
            raise Phase11Error(
                f"Fresh validation output is unavailable: step={step}; path={relative}"
            )
        expected = baseline[relative]
        observed = sha256(path)
        records.append({
            "step": step,
            "path": relative,
            "expected_sha256": expected,
            "observed_sha256": observed,
            "status": "PASS" if observed == expected else "FAIL",
        })
        if observed != expected:
            raise Phase11Error(
                "Fresh validation output differs before any restoration or later overwrite: "
                f"step={step}; path={relative}; expected_sha256={expected}; "
                f"observed_sha256={observed}"
            )
    return records


def reproduction_in_current_clone() -> dict[str, object]:
    """Regenerate Phase 0-10 in the current disposable clone and compare outputs."""
    baseline_paths = deterministic_prior_paths(ROOT)
    before = {relative: sha256(ROOT / relative) for relative in baseline_paths}
    wb_before = phase10.workbook_metadata()
    steps: dict[str, str] = {}
    fresh_validation: list[dict[str, str]] = []
    for label, command in BUILD_SEQUENCE:
        output = run(command)
        steps[label] = output.splitlines()[-1] if output else "PASS"
        fresh_validation.extend(require_fresh_validation_outputs(
            ROOT, before, label, FRESH_VALIDATION_BY_STEP.get(label, ()),
        ))
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
    return {
        "status": "PASS", "network_analytical_requests": 0,
        "exact_paths_compared": len(baseline_paths), "exact_differences": 0,
        "workbook_raw_sha_before": wb_before["sha256"], "workbook_raw_sha_after": wb_after["sha256"],
        "workbook_raw_equal": wb_before["sha256"] == wb_after["sha256"],
        "workbook_normalized_before": wb_before["normalized_fingerprint"],
        "workbook_normalized_after": wb_after["normalized_fingerprint"],
        "workbook_semantic_differences": 0,
        "fresh_validation_outputs_compared": len(fresh_validation),
        "fresh_validation_outputs": fresh_validation,
        "validation_snapshots_restored": 0,
        "steps": steps,
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


def require_exact_overlay_inventory(root: Path, paths: frozenset[str]) -> None:
    """Reject missing or extra paths against the caller-declared overlay."""
    actual = frozenset(changed_paths(root))
    if actual != paths:
        missing = sorted(paths - actual)
        unexpected = sorted(actual - paths)
        raise Phase11Error(
            "Disposable overlay inventory differs from the explicitly declared inventory; "
            f"missing={missing}; unexpected={unexpected}"
        )


def validate_isolation_request(
    root: Path,
    *,
    mode: str,
    selected_commit: str,
    overlay_paths: frozenset[str],
) -> str:
    """Validate release or overlay preconditions and return the resolved commit."""
    if mode not in {RELEASE_MODE, OVERLAY_MODE}:
        raise Phase11Error(f"Unsupported verification mode: {mode}")
    resolved = resolve_commit(root, selected_commit)
    source_head = git_head(root)
    if resolved != source_head:
        raise Phase11Error(
            f"Selected commit is not the source checkout HEAD: selected={resolved}; HEAD={source_head}"
        )
    actual = frozenset(changed_paths(root))
    if mode == RELEASE_MODE:
        if overlay_paths:
            raise Phase11Error("Clean-release verification does not permit an overlay")
        if actual:
            raise Phase11Error(
                "Clean-release verification requires a pristine source checkout; changed="
                + ", ".join(sorted(actual))
            )
    else:
        if not overlay_paths:
            raise Phase11Error("Pre-commit overlay review requires an explicit non-empty overlay")
        require_exact_overlay_inventory(root, overlay_paths)
    return resolved


def phase11_build_change_inventory(
    declared_overlay: frozenset[str],
) -> frozenset[str]:
    """Return the current build inventory without widening the caller's scope.

    ``all`` may make only its fixed, deterministic Phase 11 output paths newly
    dirty.  Every other changed path must remain exactly the caller-declared
    pre-generation overlay.  ``verify-overlay`` does not use this allowance;
    it continues to require a refreshed manifest that exactly matches status.
    """

    actual = frozenset(changed_paths())
    unexpected = actual - declared_overlay - PHASE11_GENERATED_OUTPUT_PATHS
    missing_declared = (
        declared_overlay - PHASE11_GENERATED_OUTPUT_PATHS - actual
    )
    if unexpected or missing_declared:
        raise Phase11Error(
            "Phase 11 generation changed paths outside its fixed output inventory; "
            f"missing_declared={sorted(missing_declared)}; "
            f"unexpected={sorted(unexpected)}"
        )
    return actual


def _copy_current_tree_to_clone(
    destination: Path,
    *,
    source_root: Path,
    overlay_paths: frozenset[str],
) -> None:
    """Copy the fixed approved overlay byte-for-byte into the disposable clone."""
    source_root_resolved = source_root.resolve()
    destination_resolved = destination.resolve()
    for relative in sorted(overlay_paths):
        source = source_root / relative
        resolved_source = source.resolve()
        if (
            source.is_symlink()
            or not source.is_file()
            or source_root_resolved not in resolved_source.parents
        ):
            raise Phase11Error(f"Approved overlay path is not a file: {relative}")
        target = destination / relative
        resolved_target = target.resolve()
        if destination_resolved not in resolved_target.parents:
            raise Phase11Error(f"Unsafe disposable overlay target: {relative}")
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


def _is_windows_generated_text_path(relative: str) -> bool:
    """Return whether a Phase 0-10 generator rewrites this Markdown/JSON path."""

    if relative in PHASE0_STATIC_SOURCE_TEXT_PATHS:
        return False
    suffix = PurePosixPath(relative).suffix.lower()
    if suffix not in WINDOWS_GENERATED_TEXT_SUFFIXES:
        return False
    if relative == "README.md" or relative.startswith("reports/"):
        return True
    match = re.match(r"^(?:data/phase|docs/phase-)(\d+)(?:/|$)", relative)
    return bool(match and int(match.group(1)) <= 10)


def _materialize_windows_generation_eols(
    destination: Path,
    *,
    overlay_paths: frozenset[str],
) -> list[str]:
    """Create the documented Windows generated-text checkout from Git only.

    Regenerating Phase 0-10 Python outputs writes their Markdown and JSON with
    Windows newlines, while CSV writers explicitly use LF.  Start from
    canonical blobs, then ask Git to materialize only text paths actually
    rewritten by the build with command-scoped ``core.autocrlf=true``.  Static
    Phase 0 evidence hashed by Phase 10 and maintained Phase 11 sources remain
    byte-identical to their Git blobs.  No bytes or path choices come from the
    live source checkout, and comparisons remain byte-exact.
    """
    tracked_result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=destination,
        capture_output=True, check=True,
    )
    paths = sorted(
        relative for item in tracked_result.stdout.split(b"\0") if item
        for relative in [item.decode("utf-8")]
        if relative not in overlay_paths
        and _is_windows_generated_text_path(relative)
    )
    canonical = {relative: (destination / relative).read_bytes() for relative in paths}
    for relative, content in canonical.items():
        if b"\r\n" in content:
            raise Phase11Error(f"Canonical Git blob unexpectedly contains CRLF: {relative}")
        target = (destination / relative).resolve()
        if destination.resolve() not in target.parents:
            raise Phase11Error(f"Unsafe disposable generated-text path: {relative}")
        target.unlink()
    if paths:
        run([
            "git", "-c", "core.autocrlf=true", "checkout", "--force", "HEAD", "--",
            *paths,
        ], cwd=destination)
    mismatches = [
        relative for relative in paths
        if (destination / relative).read_bytes()
        != canonical[relative].replace(b"\n", b"\r\n")
    ]
    if mismatches:
        raise Phase11Error(
            "Git Windows generated-text materialization mismatch: " + ", ".join(mismatches)
        )
    return paths


def isolated_clone(
    *,
    mode: str,
    selected_commit: str,
    overlay_paths: frozenset[str],
    source_root: Path = ROOT,
) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    """Create an independent selected-commit clone for release or overlay review."""
    resolved_commit = validate_isolation_request(
        source_root, mode=mode, selected_commit=selected_commit,
        overlay_paths=overlay_paths,
    )
    holder = tempfile.TemporaryDirectory(prefix="quanex-phase11-verify-")
    destination = Path(holder.name) / "repo"
    try:
        run([
            "git", "clone", "--no-hardlinks", "--quiet", "--no-checkout",
            "--config", "core.autocrlf=false",
            str(source_root), str(destination),
        ], cwd=source_root, extra_env=GIT_CANONICAL_TEXT_ENV)
        if not (destination / ".git").is_dir() or (destination / ".git").resolve() == (source_root / ".git").resolve():
            raise Phase11Error("Disposable clone does not have independent Git metadata")
        local_autocrlf = run(["git", "config", "--local", "--get", "core.autocrlf"], cwd=destination)
        if local_autocrlf.lower() != "false":
            raise Phase11Error(f"Disposable clone core.autocrlf is not false: {local_autocrlf}")
        # Materialize the selected commit as the disposable clone's local
        # ``main`` branch.  Earlier phase builders intentionally require
        # ``main``; resetting only this throw-away local branch preserves that
        # governance check while still proving the exact selected commit.
        run(["git", "checkout", "--quiet", "-B", "main", resolved_commit], cwd=destination, extra_env=GIT_CANONICAL_TEXT_ENV)
        head = run(["git", "rev-parse", "HEAD"], cwd=destination)
        if head != resolved_commit:
            raise Phase11Error(f"Disposable clone began at unexpected commit: {head}")
        _verify_canonical_checkout(destination)
        _materialize_windows_generation_eols(
            destination, overlay_paths=overlay_paths,
        )
        if run(["git", "config", "--local", "--get", "core.autocrlf"], cwd=destination).lower() != "false":
            raise Phase11Error("Disposable checkout changed clone-local core.autocrlf")
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
            if staged != overlay_paths:
                raise Phase11Error(
                    "Disposable clone staged overlay differs from the explicitly declared inventory"
                )
            if staged:
                run(["git", "-c", "core.autocrlf=true", "commit", "--quiet", "-m", "temporary Phase 11 verification overlay"], cwd=destination)
        if run(["git", "-c", "core.autocrlf=true", "status", "--porcelain=v1", "-uall"], cwd=destination):
            raise Phase11Error("Disposable verification clone is not clean after overlay")
    except Exception:
        holder.cleanup()
        raise
    return holder, destination


def run_isolated_reproduction(
    *,
    mode: str,
    selected_commit: str,
    overlay_paths: frozenset[str],
) -> dict[str, object]:
    resolved_commit = resolve_commit(ROOT, selected_commit)
    holder, destination = isolated_clone(
        mode=mode, selected_commit=resolved_commit, overlay_paths=overlay_paths,
    )
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
    result["verification_mode"] = mode
    result["selected_commit"] = resolved_commit
    result["overlay_paths"] = len(overlay_paths)
    result["independent_git_metadata"] = independent_metadata
    result["no_hardlinks"] = no_hardlinks
    return result


def reproduction_rows(result: dict[str, object]) -> list[dict[str, str]]:
    mode = str(result["verification_mode"])
    overlay_count = int(result["overlay_paths"])
    expected_overlay_count = 0 if mode == RELEASE_MODE else overlay_count
    expected_fresh_comparisons = sum(
        len(paths) for paths in FRESH_VALIDATION_BY_STEP.values()
    )
    pairs = [
        ("verification mode explicit", "PASS" if mode in {RELEASE_MODE, OVERLAY_MODE} else "FAIL", mode, f"{RELEASE_MODE} or {OVERLAY_MODE}"),
        ("selected commit resolved exactly", "PASS", str(result["selected_commit"]), str(result["selected_commit"])),
        ("disposable clone has independent Git metadata", "PASS" if result["independent_git_metadata"] else "FAIL", str(result["independent_git_metadata"]), "True"),
        ("disposable clone uses no hardlinks", "PASS" if result["no_hardlinks"] else "FAIL", str(result["no_hardlinks"]), "True"),
        ("core.autocrlf false before initial checkout", "PASS" if result["clone_local_autocrlf"] == "false" else "FAIL", str(result["clone_local_autocrlf"]), "false"),
        ("canonical Phase 3 bytes preserved", "PASS" if result["phase3_paths_unchanged"] else "FAIL", str(result["canonical_phase3_paths"]), "7 exact paths unchanged"),
        ("overlay inventory matches verification mode", "PASS" if overlay_count == expected_overlay_count else "FAIL", str(overlay_count), str(expected_overlay_count)),
        ("fresh validation outputs compared before later overwrite", "PASS" if result["fresh_validation_outputs_compared"] == expected_fresh_comparisons else "FAIL", str(result["fresh_validation_outputs_compared"]), f"{expected_fresh_comparisons} step-specific comparisons"),
        ("validation snapshots restored", "PASS" if result["validation_snapshots_restored"] == 0 else "FAIL", str(result["validation_snapshots_restored"]), "0"),
        ("analytical reproduction required no network", "PASS" if result["network_analytical_requests"] == 0 else "FAIL", str(result["network_analytical_requests"]), "0"),
        ("deterministic artifacts exact", "PASS" if result["exact_differences"] == 0 else "FAIL", str(result["exact_differences"]), "0"),
        ("workbook normalized fingerprint", "PASS" if result["workbook_normalized_after"] == APPROVED_WORKBOOK_FINGERPRINT else "FAIL", str(result["workbook_normalized_after"]), APPROVED_WORKBOOK_FINGERPRINT),
        ("workbook semantic differences", "PASS" if result["workbook_semantic_differences"] == 0 else "FAIL", str(result["workbook_semantic_differences"]), "0"),
        ("disposable clone cleanup", str(result["cleanup"]), str(result["clone_type"]), "temporary clone removed"),
    ]
    return [
        {"reproducibility_id": f"P11R-{index:03d}", "test_name": name, "status": status,
         "observed": observed, "expected": expected, "verification_mode": mode,
         "notes": "No new analytical evidence; pre-commit overlay review is not clean-release verification." if mode == OVERLAY_MODE else "No new analytical evidence; clean selected-commit verification used zero overlays."}
        for index, (name, status, observed, expected) in enumerate(pairs, 1)
    ]


def build_outputs(*, base_commit: str, overlay_paths: frozenset[str]) -> dict[str, object]:
    # Establish the caller's exact authority before producing any output.  The
    # isolated clone repeats this check, so a concurrent source-tree change is
    # rejected rather than silently joining the overlay.
    validate_isolation_request(
        ROOT, mode=OVERLAY_MODE, selected_commit=base_commit,
        overlay_paths=overlay_paths,
    )
    protected = {
        relative: sha256(ROOT / relative)
        for relative in repository_paths()
        if relative not in PHASE11_GENERATED_OUTPUT_PATHS
    }
    result = run_isolated_reproduction(
        mode=OVERLAY_MODE, selected_commit=base_commit, overlay_paths=overlay_paths,
    )
    write_csv(PROCESSED / "DEPENDENCY_INVENTORY.csv", dependency_rows())
    write_csv(PROCESSED / "LINK_CHECK_RESULTS.csv", link_rows())
    write_csv(DOCS / "SOURCE_LEDGER.csv", source_ledger_rows())
    write_csv(PROCESSED / "ARTIFACT_MANIFEST.csv", artifact_rows(False))
    write_csv(PROCESSED / "REPRODUCIBILITY_RESULTS.csv", reproduction_rows(result))
    write_csv(PROCESSED / "ARTIFACT_MANIFEST.csv", artifact_rows(True))

    # Only the fixed Phase 11 output inventory may be newly dirty.  The first
    # validation write can add VALIDATION_RESULTS.csv; if it does, immediately
    # rerun the read/validation pass against that now-complete internal
    # inventory so the saved scope control describes the final generated tree.
    effective_overlay = phase11_build_change_inventory(overlay_paths)
    controls = validate(write_output=True, allowed_changes=effective_overlay)
    final_overlay = phase11_build_change_inventory(overlay_paths)
    if final_overlay != effective_overlay:
        controls = validate(write_output=True, allowed_changes=final_overlay)
        stable_overlay = phase11_build_change_inventory(overlay_paths)
        if stable_overlay != final_overlay:
            raise Phase11Error(
                "Phase 11 generated-output inventory did not stabilize after validation"
            )
    after = {relative: sha256(ROOT / relative) for relative in protected}
    differences = [relative for relative in protected if protected[relative] != after.get(relative)]
    if differences:
        raise Phase11Error("Phase 11 build modified protected files: " + ", ".join(differences))
    return {
        "status": "PASS", "artifact_manifest_records": len(artifact_rows(True)),
        "dependency_records": len(dependency_rows()), "link_records": len(link_rows()),
        "validation_controls": len(controls), "exact_paths_compared": result["exact_paths_compared"],
        "release_status": RELEASE_STATUS, "verification_mode": OVERLAY_MODE,
    }


def _text_release_paths() -> list[Path]:
    return [
        ROOT / relative for relative in repository_paths()
        if Path(relative).suffix.lower() in {".py", ".mjs", ".ps1", ".md", ".csv", ".json", ".txt"}
    ]


def validation_rows(
    *, allowed_changes: frozenset[str] | None = None,
) -> list[dict[str, object]]:
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
    repro_modes = {r.get("verification_mode", "") for r in repro}
    add("reproducibility", "isolated reproduction controls pass", bool(repro) and all(r["status"] == "PASS" for r in repro), len(repro), "all PASS")
    add("reproducibility", "reproduction mode explicitly classified", len(repro_modes) == 1 and repro_modes <= {RELEASE_MODE, OVERLAY_MODE}, ";".join(sorted(repro_modes)), "one explicit verification mode")
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
    changed = frozenset(changed_paths())
    if changed:
        declared = allowed_changes is not None and changed == allowed_changes
        missing = sorted((allowed_changes or frozenset()) - changed)
        unexpected = sorted(changed - (allowed_changes or frozenset()))
        add(
            "scope", "dirty-tree changes match explicit overlay manifest", declared,
            f"missing={missing};unexpected={unexpected}", "exact declared overlay",
        )
    else:
        add(
            "scope", "clean tree requires no overlay exceptions",
            allowed_changes in (None, frozenset()), len(changed), "0",
        )
    add("scope", "no inferred working-tree exceptions", allowed_changes is not None or not changed, len(changed), "clean tree or explicit overlay")
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    add("git", "nothing staged", staged == "", staged, "none")
    return controls


def validate(
    *,
    write_output: bool = False,
    allowed_changes: frozenset[str] | None = None,
) -> list[dict[str, object]]:
    controls = validation_rows(allowed_changes=allowed_changes)
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


def validate_phase8_excel_report(report: dict[str, object]) -> dict[str, object]:
    """Require the complete executed Q-009/Q-007/Q-005 Excel probe set."""
    if report.get("status") != "PASS":
        raise Phase11Error(f"Phase 8 Excel gate did not pass: {report.get('status')}")
    if str(report.get("excel_version", "")) != "16.0" or str(report.get("excel_build", "")) != "20326":
        raise Phase11Error(
            "Phase 8 Excel gate used an undocumented engine: "
            f"version={report.get('excel_version')}; build={report.get('excel_build')}"
        )
    if int(report.get("formula_count", -1)) != EXPECTED_FORMULA_COUNT:
        raise Phase11Error(
            "Phase 8 Excel gate formula count differs from the approved workbook: "
            f"observed={report.get('formula_count')}; expected={EXPECTED_FORMULA_COUNT}"
        )
    probes = report.get("live_input_probes")
    if not isinstance(probes, list) or not all(isinstance(row, dict) for row in probes):
        raise Phase11Error("Phase 8 Excel gate did not return structured live-input probes")
    identities = [str(row.get("case", "")) for row in probes]
    duplicates = sorted({case for case in identities if identities.count(case) > 1})
    observed = frozenset(identities)
    if duplicates or observed != EXCEL_PHASE8_REQUIRED_PROBE_CASES:
        raise Phase11Error(
            "Phase 8 Excel probe inventory is incomplete or non-unique: "
            f"missing={sorted(EXCEL_PHASE8_REQUIRED_PROBE_CASES - observed)}; "
            f"unexpected={sorted(observed - EXCEL_PHASE8_REQUIRED_PROBE_CASES)}; "
            f"duplicates={duplicates}"
        )
    failed = sorted(
        str(row.get("case", "")) for row in probes if row.get("status") != "PASS"
    )
    if failed:
        raise Phase11Error("Phase 8 Excel probes did not pass: " + ", ".join(failed))
    indexed = {str(row["case"]): row for row in probes}
    freshness = report.get("freshness_checkpoints")
    if not isinstance(freshness, list) or not all(isinstance(row, dict) for row in freshness):
        raise Phase11Error("Phase 8 Excel gate did not return structured capture-freshness checkpoints")
    freshness_index = {str(row.get("checkpoint", "")): row for row in freshness}
    required_freshness = {
        "initial_full_calculation",
        "pre_save_base_reset",
        "save_reopen_full_calculation",
    }
    if set(freshness_index) != required_freshness or len(freshness) != len(required_freshness):
        raise Phase11Error("Phase 8 Excel capture-freshness checkpoint inventory is incomplete or non-unique")
    if any(
        row.get("status") != "PASS"
        or int(row.get("current_capture_count", -1)) != 9
        or int(row.get("stale_capture_count", -1)) != 0
        or row.get("checks_freshness_status") != "PASS"
        or row.get("checks_stale_status") != "PASS"
        for row in freshness
    ):
        raise Phase11Error("Phase 8 Excel saved capture-freshness control failed")
    identity_rows = [
        row for row in probes if "max_identity_difference" in row
    ]
    if len(identity_rows) != 8:
        raise Phase11Error(
            f"Phase 8 Excel gate returned {len(identity_rows)} financing-identity probes; expected 8"
        )
    maximum_identity_difference = max(
        abs(float(row["max_identity_difference"])) for row in identity_rows
    )
    spread = indexed["spread_plus_100bp"]
    try:
        anchor_differences = [
            abs(float(spread["february_cash_identity"])),
            abs(float(spread["april_cash_identity"])),
            abs(float(indexed["amortization_10_percent"]["april_cash_identity"])),
            abs(float(indexed["base"]["q2_cfads_difference"])),
            abs(float(indexed["fy2026_q2_ebitda_plus_10_percent"]["q2_cfads_difference"])),
            abs(float(indexed["dso_plus_10_days"]["q2_cfads_difference"])),
            abs(float(indexed["combined_rate_amortization_ebitda_dso"]["q2_cfads_difference"])),
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise Phase11Error(f"Phase 8 Excel probe omitted a required reconciliation anchor: {exc}") from exc
    maximum_reconciliation_difference = max(
        [maximum_identity_difference, *anchor_differences]
    )
    if maximum_reconciliation_difference > 0.000001:
        raise Phase11Error(
            "Phase 8 Excel live-input financing identities did not reconcile: "
            f"maximum={maximum_reconciliation_difference}"
        )
    warning_probe = indexed["warning_threshold_equalities"]
    try:
        coverage_warning_threshold = float(warning_probe["coverage_threshold"])
        liquidity_warning_threshold = float(warning_probe["liquidity_threshold"])
    except (KeyError, TypeError, ValueError) as exc:
        raise Phase11Error(f"Phase 8 Excel warning probe omitted an approved threshold: {exc}") from exc
    if (
        indexed["balanced_funding_signature_collision"].get("stale_status") != "STALE"
        or not abs(coverage_warning_threshold - 3.5) <= 0.000001
        or not abs(liquidity_warning_threshold - 75.0) <= 0.000001
        or warning_probe.get("coverage_status") != "WARNING"
        or warning_probe.get("liquidity_status") != "WARNING"
        or report.get("final_scenario") != "Base"
        or int(report.get("recovery_logs", -1)) != 0
    ):
        raise Phase11Error("Phase 8 Excel freshness, warning-boundary, saved-state, or recovery-log control failed")
    return {
        "status": "PASS",
        "probe_count": len(probes),
        "probe_cases": sorted(observed),
        "maximum_identity_difference": maximum_identity_difference,
        "maximum_reconciliation_difference": maximum_reconciliation_difference,
        "final_scenario": report.get("final_scenario"),
        "freshness_checkpoints": sorted(freshness_index),
        "recovery_logs": report.get("recovery_logs"),
        "excel_version": report.get("excel_version"),
        "excel_build": report.get("excel_build"),
    }


def validate_phase9_excel_report(report: dict[str, object]) -> dict[str, object]:
    """Require all documented Phase 9 Excel interaction methods and engine."""
    if report.get("status") != "PASS":
        raise Phase11Error(f"Phase 9 Excel gate did not pass: {report.get('status')}")
    if str(report.get("excel_version", "")) != "16.0" or str(report.get("excel_build", "")) != "20326":
        raise Phase11Error(
            "Phase 9 Excel gate used an undocumented engine: "
            f"version={report.get('excel_version')}; build={report.get('excel_build')}"
        )
    methods = report.get("calculation_methods")
    if not isinstance(methods, list) or not all(isinstance(row, dict) for row in methods):
        raise Phase11Error("Phase 9 Excel gate did not return structured calculation methods")
    identities = [str(row.get("method", "")) for row in methods]
    duplicates = sorted({method for method in identities if identities.count(method) > 1})
    observed = frozenset(identities)
    failed = sorted(str(row.get("method", "")) for row in methods if row.get("status") != "PASS")
    if duplicates or observed != EXCEL_PHASE9_REQUIRED_METHODS or failed:
        raise Phase11Error(
            "Phase 9 Excel method inventory is incomplete, non-unique, or failed: "
            f"missing={sorted(EXCEL_PHASE9_REQUIRED_METHODS - observed)}; "
            f"unexpected={sorted(observed - EXCEL_PHASE9_REQUIRED_METHODS)}; "
            f"duplicates={duplicates}; failed={failed}"
        )
    if (
        report.get("final_scenario") != "Base"
        or int(report.get("workbook_error_cells", -1)) != 0
        or int(report.get("recovery_logs", -1)) != 0
    ):
        raise Phase11Error("Phase 9 Excel saved-state, workbook-error, or recovery-log control failed")
    return {
        "status": "PASS", "method_count": len(methods),
        "methods": sorted(observed), "excel_version": report.get("excel_version"),
        "excel_build": report.get("excel_build"),
    }


def engine_gates() -> dict[str, object]:
    before = sha256(MODEL)
    before_status = git_status()
    before_head = git_head()
    before_git_config = git_config_digest()
    try:
        lo = phase10.libreoffice_report_on_copy("inspect")
        if lo.get("engine") != "LibreOffice 26.8.0.3":
            raise Phase11Error(f"LibreOffice gate used an undocumented engine: {lo.get('engine')}")
        excel8_report = json.loads(phase10.excel_validation_on_copy("validate-phase8-excel.ps1"))
        excel8 = validate_phase8_excel_report(excel8_report)
        excel9_report = json.loads(phase10.excel_validation_on_copy("validate-phase9-excel.ps1"))
        excel9 = validate_phase9_excel_report(excel9_report)
        with tempfile.TemporaryDirectory(prefix="quanex-phase11-pdf-render-") as temp_name:
            pdf_render = json.loads(run([
                str(phase10.BUNDLED_PYTHON), str(ROOT / "scripts" / "render-phase11.py"),
                str(ROOT), temp_name,
            ]).splitlines()[-1])
    finally:
        after = sha256(MODEL)
        after_status = git_status()
        after_head = git_head()
        after_git_config = git_config_digest()
        if before != after:
            raise Phase11Error("Spreadsheet-engine gates modified authoritative workbook")
        if before_status != after_status:
            raise Phase11Error("Spreadsheet-engine gates changed repository status")
        if before_head != after_head:
            raise Phase11Error("Spreadsheet-engine gates changed repository HEAD")
        if before_git_config != after_git_config:
            raise Phase11Error("Spreadsheet-engine gates changed Git configuration")
    return {
        "libreoffice": lo.get("engine"), "excel_phase8": excel8.get("status"),
        "excel_phase8_probe_count": excel8["probe_count"],
        "excel_phase8_probe_cases": excel8["probe_cases"],
        "excel_phase8_maximum_identity_difference": excel8["maximum_identity_difference"],
        "excel_phase8_maximum_reconciliation_difference": excel8["maximum_reconciliation_difference"],
        "excel_phase8_version": f"{excel8['excel_version']} build {excel8['excel_build']}",
        "excel_phase9": excel9.get("status"),
        "excel_phase9_method_count": excel9["method_count"],
        "excel_phase9_methods": excel9["methods"],
        "excel_phase9_version": f"{excel9['excel_version']} build {excel9['excel_build']}",
        "authoritative_workbook_unchanged": True,
        "repository_status_unchanged": True,
        "repository_head_unchanged": True,
        "git_config_unchanged": True,
        "pdfs": phase10.pdf_metadata(), "pdf_render": pdf_render,
    }


def validate_verification_clone_start(
    destination: Path,
    *,
    mode: str,
    resolved_commit: str,
    clone_head: str,
    clone_status: str,
) -> str:
    """Validate the clean exact-candidate or explicit overlay-review commit."""
    if clone_status:
        raise Phase11Error(
            "Disposable verification checkout did not begin clean: "
            f"HEAD={clone_head}; status={clone_status!r}"
        )
    if mode == RELEASE_MODE:
        if clone_head != resolved_commit:
            raise Phase11Error(
                "Disposable exact-candidate checkout did not begin at the selected commit: "
                f"HEAD={clone_head}; selected={resolved_commit}"
            )
        return resolved_commit
    if mode == OVERLAY_MODE:
        clone_base = resolve_commit(destination, f"{clone_head}^")
        if clone_base != resolved_commit:
            raise Phase11Error(
                "Disposable overlay-review commit does not have the selected base: "
                f"parent={clone_base}; selected={resolved_commit}"
            )
        return clone_base
    raise Phase11Error(f"Unsupported verification mode: {mode}")


def verify_isolated(
    *,
    mode: str,
    selected_commit: str,
    overlay_paths: frozenset[str],
) -> dict[str, object]:
    resolved_commit = validate_isolation_request(
        ROOT, mode=mode, selected_commit=selected_commit,
        overlay_paths=overlay_paths,
    )
    before_manifest = repository_manifest()
    before_status = git_status()
    before_head = git_head()
    before_git_config = git_config_digest()
    prior_validation_paths = [
        relative for relative in repository_paths()
        if relative.endswith("VALIDATION_RESULTS.csv") and not relative.startswith("data/phase11/")
    ]
    prior_before = {relative: sha256(ROOT / relative) for relative in prior_validation_paths}
    holder, destination = isolated_clone(
        mode=mode, selected_commit=resolved_commit, overlay_paths=overlay_paths,
    )
    clone_type = "disposable local no-hardlinks clone"
    try:
        clone_head_before = git_head(destination)
        clone_status_before = generation_git_status(destination)
        clone_git_config_before = git_config_digest(destination)
        clone_base_before = validate_verification_clone_start(
            destination, mode=mode, resolved_commit=resolved_commit,
            clone_head=clone_head_before, clone_status=clone_status_before,
        )
        reproduction_output = run([sys.executable, "-B", "scripts/phase11.py", "reproduce"], cwd=destination, extra_env=GIT_WINDOWS_TEXT_ENV)
        reproduction = json.loads(reproduction_output.splitlines()[-1])
        validate_output = run([sys.executable, "-B", "scripts/phase11.py", "validate"], cwd=destination, extra_env=GIT_WINDOWS_TEXT_ENV)
        full = run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=destination, extra_env=GIT_WINDOWS_TEXT_ENV)
        focused = run([sys.executable, "-B", "-m", "unittest", "-v", "tests.test_phase8", "tests.test_phase9", "tests.test_phase10", "tests.test_phase11"], cwd=destination, extra_env=GIT_WINDOWS_TEXT_ENV)
        independent = run([sys.executable, "-B", "-m", "unittest", "-v", "tests.test_audit_remediation"], cwd=destination, extra_env=GIT_WINDOWS_TEXT_ENV)
        engines_output = run([sys.executable, "-B", "scripts/phase11.py", "engine-gates"], cwd=destination, extra_env=GIT_WINDOWS_TEXT_ENV)
        engines = json.loads(engines_output.splitlines()[-1])
        clone_head_after = git_head(destination)
        clone_status_after = generation_git_status(destination)
        clone_git_config_after = git_config_digest(destination)
        if clone_head_after != clone_head_before:
            raise Phase11Error(
                "Disposable verification changed candidate HEAD: "
                f"before={clone_head_before}; after={clone_head_after}"
            )
        if clone_status_after:
            raise Phase11Error(
                "Disposable verification did not reproduce the committed candidate exactly; status="
                + clone_status_after
            )
        if clone_git_config_after != clone_git_config_before:
            raise Phase11Error("Disposable verification changed Git configuration")
    finally:
        try:
            holder.cleanup()
        finally:
            after_manifest = repository_manifest()
            after_status = git_status()
            after_head = git_head()
            after_git_config = git_config_digest()
            prior_after = {relative: sha256(ROOT / relative) for relative in prior_validation_paths}
            if before_manifest != after_manifest:
                changed = [p for p in sorted(set(before_manifest) | set(after_manifest)) if before_manifest.get(p) != after_manifest.get(p)]
                raise Phase11Error("Final isolated verification modified repository: " + ", ".join(changed))
            if before_status != after_status:
                raise Phase11Error("Final isolated verification changed Git status")
            if before_head != after_head or before_head != resolved_commit:
                raise Phase11Error(
                    f"Final isolated verification changed or mismatched source HEAD: before={before_head}; "
                    f"after={after_head}; selected={resolved_commit}"
                )
            if prior_before != prior_after:
                raise Phase11Error("Final isolated verification changed prior validation outputs")
            if before_git_config != after_git_config:
                raise Phase11Error("Final isolated verification changed source Git configuration")
    return {
        "status": "PASS", "verification_mode": mode,
        "selected_commit": resolved_commit, "overlay_paths": len(overlay_paths),
        "clone_type": clone_type, "cleanup": "PASS",
        "before_manifest_digest": manifest_digest(before_manifest),
        "after_manifest_digest": manifest_digest(after_manifest),
        "manifest_files": len(before_manifest), "git_status_identical": True,
        "source_head_before": before_head, "source_head_after": after_head,
        "source_git_config_before_digest": before_git_config,
        "source_git_config_after_digest": after_git_config,
        "source_git_config_identical": True,
        "clone_head_before": clone_head_before, "clone_head_after": clone_head_after,
        "clone_base_commit": clone_base_before,
        "clone_git_status_before": clone_status_before,
        "clone_git_status_after": clone_status_after,
        "clone_git_config_before_digest": clone_git_config_before,
        "clone_git_config_after_digest": clone_git_config_after,
        "clone_git_config_identical": True,
        "prior_validation_files": len(prior_before), "prior_validation_files_identical": True,
        "reproduction": reproduction, "validation": validate_output.splitlines()[-1],
        "complete_tests": _test_count(full), "focused_tests": _test_count(focused),
        "independent_invariant_tests": _test_count(independent),
        "engines": engines,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "all", "validate", "verify-release", "verify-overlay",
            "verify-isolated", "reproduce", "engine-gates", "metadata",
        ),
    )
    parser.add_argument("--commit", help="explicit commit for clean-release verification")
    parser.add_argument("--base", help="explicit base commit for pre-commit overlay review")
    parser.add_argument("--overlay-manifest", type=Path, help="one explicit repository-relative overlay path per line")
    args = parser.parse_args()
    overlay_paths = read_overlay_manifest(args.overlay_manifest) if args.overlay_manifest else None
    if args.command == "all":
        if not args.base or overlay_paths is None or args.commit:
            parser.error("all requires --base and --overlay-manifest for explicit pre-commit generation")
        print("Phase 11 complete: " + json.dumps(build_outputs(
            base_commit=args.base, overlay_paths=overlay_paths,
        ), sort_keys=True))
    elif args.command == "validate":
        if args.commit or args.base:
            parser.error("validate accepts only optional --overlay-manifest")
        rows = validate(allowed_changes=overlay_paths)
        print(f"Phase 11 validation: PASS ({len(rows)} controls)")
    elif args.command in {"verify-release", "verify-isolated"}:
        if not args.commit or args.base or overlay_paths is not None:
            parser.error(f"{args.command} requires --commit and permits no overlay")
        print(json.dumps(verify_isolated(
            mode=RELEASE_MODE, selected_commit=args.commit,
            overlay_paths=frozenset(),
        ), sort_keys=True))
    elif args.command == "verify-overlay":
        if not args.base or overlay_paths is None or args.commit:
            parser.error("verify-overlay requires --base and --overlay-manifest")
        print(json.dumps(verify_isolated(
            mode=OVERLAY_MODE, selected_commit=args.base,
            overlay_paths=overlay_paths,
        ), sort_keys=True))
    elif args.command == "reproduce":
        print(json.dumps(reproduction_in_current_clone(), sort_keys=True))
    elif args.command == "engine-gates":
        print(json.dumps(engine_gates(), sort_keys=True))
    else:
        print(json.dumps({"workbook": phase10.workbook_metadata(), "pdfs": phase10.pdf_metadata()}, sort_keys=True))


if __name__ == "__main__":
    main()
