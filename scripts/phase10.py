"""Build and validate Phase 10 committee-decision deliverables.

The workflow consumes the approved Phase 0-9 record without live network access.
It creates the owner-reviewed conditional-approval recommendation package.
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
import zipfile
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "phase10"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
DOCS = ROOT / "docs" / "phase-10"
REPORTS = ROOT / "reports"
MODEL = ROOT / "model" / "Quanex_Credit_Underwriting.xlsx"
APPROVED_PHASE9_COMMIT = "fe00c19ab717900fe5c7484d8f57975c83483cba"
INFORMATION_CUTOFF = "2025-12-15"
HYPOTHETICAL_CLOSING = "2026-01-31"
RECOMMENDATION_STATUS = "owner_reviewed"
RECOMMENDATION = "conditional_approval"
RECOMMENDATION_DISPLAY = "Conditional Approval"
NODE = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe"
NODE_MODULES = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "node_modules"
BUNDLED_PYTHON = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "python" / "python.exe"
N_D = "N/D"
TOLERANCE = Decimal("0.002")

SOURCE_INPUTS = (
    "docs/phase-0/CASE_CHARTER.md",
    "docs/phase-0/EXISTING_FINANCING.md",
    "data/phase2/processed/historical_spread.csv",
    "data/phase2/processed/historical_credit_metrics.csv",
    "data/phase2/processed/earnings_bridges.csv",
    "data/phase3/processed/RISK_DRIVER_MAP.csv",
    "data/phase3/processed/INFORMATION_GAPS.csv",
    "data/phase4/processed/CONDITIONS_PRECEDENT.csv",
    "data/phase4/processed/LEGAL_STRUCTURE_REGISTER.csv",
    "data/phase5/processed/BASE_CASE_CREDIT_METRICS.csv",
    "data/phase6/processed/SCENARIO_RESULTS.csv",
    "data/phase7/processed/STRUCTURE_COMPARISON.csv",
    "data/phase7/processed/COVENANT_SUMMARY.csv",
    "data/phase7/processed/COMMON_HORIZON_COMPARISON.csv",
    "data/phase7/processed/ULTIMATE_MATURITY_COMPARISON.csv",
    "data/phase7/processed/SOURCES_AND_USES_RECONCILIATION.csv",
    "data/phase8/processed/SCENARIO_CAPTURE_RESULTS.csv",
    "data/phase9/processed/BORROWER_RISK_ASSESSMENT.csv",
    "data/phase9/processed/RECOVERY_CASE_REGISTER.csv",
    "data/phase9/processed/MONITORING_SCHEDULE.csv",
)


class Phase10Error(RuntimeError):
    """Raised when a Phase 10 control fails."""


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise Phase10Error(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


phase8 = load_module("phase8_for_phase10", ROOT / "scripts" / "phase8.py")
phase9 = load_module("phase9_for_phase10", ROOT / "scripts" / "phase9.py")


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


def dec(value: object) -> Decimal:
    if value in (None, "", N_D, "N/M"):
        raise Phase10Error(f"Numeric value required, received {value!r}")
    return Decimal(str(value))


def fmt(value: Decimal | object) -> str:
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repository_paths() -> list[str]:
    """Return tracked and non-ignored untracked files in deterministic order."""
    result = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return sorted(path.decode("utf-8") for path in result.stdout.split(b"\0") if path)


def repository_manifest() -> dict[str, str]:
    """Hash every commit-relevant working-tree file without touching it."""
    return {path: sha256(ROOT / path) for path in repository_paths()}


def manifest_digest(manifest: dict[str, str]) -> str:
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def git_status_snapshot() -> str:
    return subprocess.run(
        ["git", "status", "--porcelain=v1", "-uall"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout


def run_command(command: list[str], cwd: Path = ROOT) -> str:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, env=env)
    if result.returncode:
        raise Phase10Error(
            f"Command failed ({result.returncode}): {' '.join(command)}\n"
            f"{result.stdout}{result.stderr}"
        )
    return (result.stdout + result.stderr).strip()


def libreoffice_report_on_copy(mode: str = "inspect", source: Path = MODEL) -> dict[str, object]:
    """Run the saving LibreOffice harness only against a disposable workbook."""
    authoritative_hash = sha256(source)
    with tempfile.TemporaryDirectory(prefix="quanex-phase10-lo-copy-") as temp_name:
        candidate = Path(temp_name) / source.name
        shutil.copy2(source, candidate)
        report = phase9.run_libreoffice(mode, candidate)
    if sha256(source) != authoritative_hash:
        raise Phase10Error("LibreOffice validation modified the authoritative workbook")
    return report


def excel_validation_on_copy(script_name: str, source: Path = MODEL) -> str:
    """Give the existing Excel harness a disposable source, never the repository file."""
    authoritative_hash = sha256(source)
    with tempfile.TemporaryDirectory(prefix="quanex-phase10-excel-copy-") as temp_name:
        candidate = Path(temp_name) / source.name
        shutil.copy2(source, candidate)
        output = run_command([
            "powershell", "-ExecutionPolicy", "Bypass", "-NoProfile", "-File",
            str(ROOT / "scripts" / script_name), "-WorkbookPath", str(candidate),
        ])
    if sha256(source) != authoritative_hash:
        raise Phase10Error("Microsoft Excel validation modified the authoritative workbook")
    return output


def isolated_workspace() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    """Clone committed history, then overlay the exact current commit-relevant files."""
    holder = tempfile.TemporaryDirectory(prefix="quanex-phase10-verify-")
    destination = Path(holder.name) / "repo"
    run_command(["git", "clone", "--no-hardlinks", "--quiet", str(ROOT), str(destination)])
    run_command(["git", "config", "core.autocrlf", "true"], cwd=destination)
    # Several prior-phase validators hash generated files before and after
    # regeneration. Preserve the authoritative checkout bytes for all approved
    # data/document surfaces because a fresh clone may materialize different
    # newline bytes despite a clean analytical diff.
    prior_patterns = [
        *[f"data/phase{phase}" for phase in range(1, 10)],
        *[f"docs/phase-{phase}" for phase in range(0, 10)],
    ]
    prior_artifact_paths = subprocess.run(
        ["git", "ls-files", *prior_patterns],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    exact_baseline_paths = sorted(set(prior_artifact_paths) | set(SOURCE_INPUTS))
    for relative in exact_baseline_paths:
        source = ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    run_command(["git", "add", "--", *exact_baseline_paths], cwd=destination)
    staged_baseline = run_command(
        ["git", "diff", "--cached", "--name-only", "--", *exact_baseline_paths],
        cwd=destination,
    )
    if staged_baseline:
        raise Phase10Error("Isolated source baseline differs analytically: " + staged_baseline.replace("\n", ", "))
    # The clone supplies the committed baseline using its own checkout/EOL
    # configuration. Overlay only the actual working-tree delta; copying every
    # tracked file can create false changes from platform line-ending filters.
    for relative in changed_paths():
        source = ROOT / relative
        target = destination / relative
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return holder, destination


def git_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()


def approved_lineage(head: str | None = None) -> bool:
    head = head or git_head()
    if head == APPROVED_PHASE9_COMMIT:
        return True
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", APPROVED_PHASE9_COMMIT, head],
        cwd=ROOT, capture_output=True,
    ).returncode == 0


def source_signature() -> str:
    digest = hashlib.sha256()
    for relative in SOURCE_INPUTS:
        path = ROOT / relative
        if not path.is_file():
            raise Phase10Error(f"Missing approved input: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def first(rows: list[dict[str, str]], **criteria: str) -> dict[str, str]:
    for row in rows:
        if all(row.get(key) == value for key, value in criteria.items()):
            return row
    raise Phase10Error(f"Required row not found: {criteria}")


def display(value: object, units: str) -> str:
    if value in (N_D, "N/M", None, ""):
        return str(value or N_D)
    if units not in {"USD_millions", "turns", "percent", "decimal_fraction"}:
        return str(value)
    number = dec(value)
    if units == "USD_millions":
        return f"${number.quantize(Decimal('0.001')):,.3f}m"
    if units == "turns":
        return f"{number.quantize(Decimal('0.0001'))}x"
    if units == "percent":
        return f"{number.quantize(Decimal('0.1'))}%"
    if units == "decimal_fraction":
        return f"{(number * 100).quantize(Decimal('0.1'))}%"
    return str(value)


def owner_review_decisions() -> list[dict[str, str]]:
    entries = [
        ("P10D-001", "recommendation", "Conditional Approval of the selected structure, subject to every material condition.", "Owner approved the project recommendation; conditions remain open."),
        ("P10D-002", "recommended facilities", "$635m fully funded term facility and $300m revolver, including a $29.898m opening draw; do not substitute incremental debt for the conditional $15m source.", "Owner approved the hypothetical facility sizes."),
        ("P10D-003", "bank hold", "Up to $50m of combined commitments.", "Owner approved the exposure cap."),
        ("P10D-004", "transaction rationale", "No faster same-horizon deleveraging; support rests only on maturity extension, liquidity structure, amortization, lender protections, and monitoring, subject to final economics and documents.", "Owner approved the corrected rationale."),
        ("P10D-005", "fallback alternative", "If any material condition fails, do not close as modeled and do not add debt; retain or amend the existing facilities through a limited amendment or extension.", "Owner approved the mandatory fallback."),
        ("P10D-006", "decisive strengths", "FY2025 cash conversion, full-year post-Tyman earnings capacity, base interim debt service, opening liquidity, amortization/sweep, capped hold, and explicit fallback.", "Owner approved the strengths."),
        ("P10D-007", "decisive risks", "Thin opening leverage cushion, no same-horizon debt benefit, early moderate breach, severe liquidity/payment failure, integration/control risk, $324.780m maturity gap, unresolved refinancing, and N/D recovery.", "Owner approved the risks."),
        ("P10D-008", "conditions precedent", "Require the full closing, legal, financial, funding, and diligence package in P10CM-001 through P10CM-013.", "Owner approved the CP package; satisfaction remains open."),
        ("P10D-009", "distribution restrictions", "No debt-funded buybacks; distributions conditioned on no default, leverage, liquidity, draw usage, and pro forma compliance.", "Owner approved the restriction framework."),
        ("P10D-010", "monitoring and escalation", "Use monthly liquidity/integration reporting, quarterly certificates, early covenant intervention, and maturity escalation.", "Owner approved the monitoring framework."),
        ("P10D-011", "risk-grade wording", "Elevated is a project-specific qualitative risk assessment, not a bank grade, agency rating, calibrated PD, or official classification.", "Owner approved the qualified assessment."),
        ("P10D-012", "recovery wording", "Official recovery remains N/D; collateral/business-sale recoveries are secondary backstops and the two illustrative methods remain separate alternatives.", "Owner approved the recovery boundary."),
        ("P10D-013", "residual refinancing dependency", "The $324.780m bank-debt gap at January 31, 2031 is an unresolved separately underwritten maturity dependency; no takeout proceeds are assumed.", "Owner approved the refinancing conclusion."),
        ("P10D-014", "strongest counterargument", "At July 31, 2029 the selected structure has $19.386m more total funded debt than existing facilities; its lower later maturity gap partly reflects about 18 additional months.", "Owner approved the corrected counterargument."),
        ("P10D-015", "final memo language", "Use the generated memo and brief as the owner-reviewed project recommendation, never as an actual bank approval, commitment, funding authorization, legal opinion, or official risk grade.", "Owner approved the final decision language."),
        ("P10D-016", "repayment framing", "Primary repayment is recurring operating cash after all required uses. Amortization and the ECF sweep are payment mechanisms; revolver capacity is liquidity support; refinancing is an unresolved dependency; recovery is the secondary backstop.", "Owner approved the corrected repayment hierarchy."),
        ("P10D-017", "covenant package", "Retain Phase 7 leverage, coverage, liquidity, sweep, and warning framework. Moderate breach is accepted as early intervention, without covenant loosening or assumed waiver.", "Owner approved the public-information covenant proposal subject to final documents."),
        ("P10D-018", "Credit Summary wording", "Display the owner-reviewed Conditional Approval, corrected repayment hierarchy, unfavorable common horizon, moderate breach, fallback, Elevated assessment, and N/D recovery.", "Owner approved the final workbook presentation."),
    ]
    return [
        {
            "decision_id": rid,
            "topic": topic,
            "working_decision": treatment,
            "owner_action_required": action,
            "classification": "phase10_owner_judgment",
            "review_status": RECOMMENDATION_STATUS,
            "limitations": "Owner review is a project judgment, not an actual bank approval, lender commitment, funding authorization, legal opinion, official grade, or external fact; all stated conditions and diligence remain open.",
        }
        for rid, topic, treatment, action in entries
    ]


def committee_metrics() -> list[dict[str, str]]:
    historical = read_csv(ROOT / "data" / "phase2" / "processed" / "historical_spread.csv")
    credit = read_csv(ROOT / "data" / "phase2" / "processed" / "historical_credit_metrics.csv")
    bridges = read_csv(ROOT / "data" / "phase2" / "processed" / "earnings_bridges.csv")
    structure = read_csv(ROOT / "data" / "phase7" / "processed" / "STRUCTURE_COMPARISON.csv")
    covenants = read_csv(ROOT / "data" / "phase7" / "processed" / "COVENANT_SUMMARY.csv")
    sources_uses = read_csv(ROOT / "data" / "phase7" / "processed" / "SOURCES_AND_USES_RECONCILIATION.csv")
    maturity = read_csv(ROOT / "data" / "phase7" / "processed" / "ULTIMATE_MATURITY_COMPARISON.csv")
    common = read_csv(ROOT / "data" / "phase7" / "processed" / "COMMON_HORIZON_COMPARISON.csv")
    captures = read_csv(ROOT / "data" / "phase8" / "processed" / "SCENARIO_CAPTURE_RESULTS.csv")
    recovery = read_csv(ROOT / "data" / "phase9" / "processed" / "RECOVERY_CASE_REGISTER.csv")
    rows: list[dict[str, str]] = []

    def add(category: str, name: str, scenario: str, value: object, units: str,
            classification: str, source_path: str, source_ids: str, review_status: str,
            limitations: str = "", measurement_horizon: str = "",
            measurement_basis: str = "") -> None:
        rows.append({
            "metric_id": f"P10M-{len(rows)+1:03d}", "category": category,
            "metric_name": name, "scenario_or_period": scenario, "value": str(value),
            "units": units, "display_value": display(value, units),
            "classification": classification, "source_path": source_path,
            "source_ids": source_ids, "review_status": review_status,
            "measurement_horizon": measurement_horizon,
            "measurement_basis": measurement_basis,
            "limitations": limitations,
        })

    for year in ("FY2024", "FY2025"):
        for name in ("revenue", "operating_income", "cash_flow_from_operations", "free_cash_flow"):
            row = first(historical, fiscal_year=year, metric_name=name)
            add("historical", name, year, row["value"], "USD_millions", "approved_prior_phase_fact_or_calculation", "data/phase2/processed/historical_spread.csv", row["source_ids"], "approved_upstream", row.get("comparability_note") or row.get("comparability_status", "") + (f"; {row['notes']}" if row.get("notes") else ""), year, "annual_fiscal_period")
        for name in ("cfo_to_provisional_lender_normalized_ebitda", "fcf_to_provisional_lender_normalized_ebitda"):
            row = first(credit, fiscal_year=year, metric_name=name)
            add("historical", name, year, row["value"], "percent", "approved_prior_phase_calculation", "data/phase2/processed/historical_credit_metrics.csv", row["source_ids"] or row["input_ids"], "approved_upstream", row["notes"], year, "annual_fiscal_period")
        row = next(r for r in bridges if r["fiscal_year"] == year and r["bridge_type"] == "provisional_lender_normalized_ebitda_base" and r["line_item"].startswith("Lender-normalized EBITDA"))
        add("earnings", "lender_base_ebitda", year, row["resulting_subtotal"], "USD_millions", "owner_reviewed_prior_phase_calculation", "data/phase2/processed/earnings_bridges.csv", "P2 adjustment decisions", "owner_reviewed_upstream", "Lender normalization is not contractual EBITDA or cash flow.", year, "annual_fiscal_period")
        unadjusted = next(r for r in bridges if r["fiscal_year"] == year and r["bridge_type"] == "unadjusted_ebitda" and r["sequence"] == "2")
        add("earnings", "unadjusted_ebitda", year, unadjusted["resulting_subtotal"], "USD_millions", "approved_prior_phase_calculation", "data/phase2/processed/earnings_bridges.csv", unadjusted["source_ids"], "approved_upstream", "Negative EBITDA produces N/M where used as a denominator.", year, "annual_fiscal_period")

    selected = first(structure, candidate_id="STR-008", scenario_id="BASE")
    su = first(sources_uses, candidate_id="STR-008")
    structure_values = [
        ("term_facility", selected["opening_term_principal"], "USD_millions", "hypothetical_proposed_term"),
        ("revolver_commitment", selected["revolver_commitment"], "USD_millions", "hypothetical_proposed_term"),
        ("opening_revolver_draw", selected["opening_revolver"], "USD_millions", "approved_prior_phase_calculation"),
        ("conditional_non_debt_source", selected["required_non_debt_contribution"], "USD_millions", "conditional_hypothetical_source"),
        ("opening_funded_debt", selected["opening_gross_funded_debt"], "USD_millions", "approved_prior_phase_calculation"),
        ("opening_gross_leverage", selected["opening_gross_funded_leverage"], "turns", "approved_prior_phase_calculation"),
        ("base_all_in_liquidity", selected["all_in_minimum_usable_liquidity"], "USD_millions", "approved_prior_phase_calculation"),
        ("sources_less_uses", su["sources_less_uses"], "USD_millions", "approved_prior_phase_calculation"),
        ("annual_term_amortization", selected["annual_amortization_percent"], "percent", "hypothetical_proposed_term"),
        ("bank_hold_cap", "50", "USD_millions", "hypothetical_proposed_term"),
        ("operating_cash_floor", "25", "USD_millions", "hypothetical_proposed_term"),
        ("ecf_sweep", "50", "percent", "hypothetical_proposed_term"),
        ("final_maturity", selected["maturity_date"], "date", "hypothetical_proposed_term"),
    ]
    for name, value, units, classification in structure_values:
        basis = "hypothetical_closing_point_in_time" if name in {"opening_revolver_draw", "opening_funded_debt", "opening_gross_leverage", "base_all_in_liquidity", "sources_less_uses"} else "hypothetical_proposed_term"
        horizon = HYPOTHETICAL_CLOSING if basis == "hypothetical_closing_point_in_time" else "facility_term"
        add("structure", name, "selected", value, units, classification, "data/phase7/processed/STRUCTURE_COMPARISON.csv", selected["source_ids"], "owner_reviewed_upstream", "Terms remain hypothetical and subject to final documentation.", horizon, basis)

    for scenario in ("BASE", "MODERATE_UNMITIGATED", "MODERATE_MITIGATED", "SEVERE_UNMITIGATED", "SEVERE_MITIGATED"):
        cap = first(captures, scenario_id=scenario)
        cov = first(covenants, scenario_id=scenario)
        for name, field, units in (
            ("fy2026_lender_ebitda", "fy2026_ebitda", "USD_millions"),
            ("modeled_operating_cash", "modeled_operating_cash", "USD_millions"),
            ("cfads", "cfads", "USD_millions"),
            ("cash_interest", "cash_interest", "USD_millions"),
            ("scheduled_principal", "scheduled_principal", "USD_millions"),
            ("ecf_sweep_realized", "ecf_sweep", "USD_millions"),
            ("all_in_minimum_liquidity", "all_in_minimum_liquidity", "USD_millions"),
            ("maximum_gross_leverage", "maximum_leverage", "turns"),
            ("minimum_cash_interest_coverage", "minimum_coverage", "turns"),
            ("common_horizon_ending_funded_debt", "common_horizon_ending_debt", "USD_millions"),
            ("unsupported_maturity_gap", "maturity_gap", "USD_millions"),
            ("unpaid_obligations", "unpaid_obligations", "USD_millions"),
        ):
            if name == "fy2026_lender_ebitda":
                horizon, basis = "FY2026", "annual_fiscal_period"
            elif name in {"modeled_operating_cash", "cfads", "cash_interest", "scheduled_principal", "ecf_sweep_realized", "unpaid_obligations"}:
                horizon, basis = "2026-02-01 through 2031-01-31", "cumulative_model_period"
            elif name in {"all_in_minimum_liquidity", "minimum_cash_interest_coverage"}:
                horizon, basis = "2026-01-31 opening plus 2026-02-01 through 2031-01-31 forecast", "minimum_over_forecast"
            elif name == "maximum_gross_leverage":
                horizon, basis = "2026-01-31 opening plus 2026-02-01 through 2031-01-31 forecast", "maximum_over_forecast"
            elif name == "common_horizon_ending_funded_debt":
                horizon, basis = "2029-07-31", "point_in_time_total_funded_debt"
            else:
                horizon, basis = "2031-01-31", "point_in_time_bank_debt_maturity_gap"
            add("scenario", name, scenario, cap[field], units, "approved_prior_phase_model_output", "data/phase8/processed/SCENARIO_CAPTURE_RESULTS.csv", cap["capture_id"], "approved_upstream", "Scenario output; no refinancing proceeds assumed.", horizon, basis)
        for name, field in (
            ("first_warning", "first_warning_date"),
            ("first_breach", "first_breach_date"),
            ("first_liquidity_shortfall", "first_liquidity_shortfall_date"),
            ("first_mandatory_payment_failure", "first_mandatory_payment_failure_date"),
        ):
            add("scenario_event", name, scenario, cov[field] or N_D, "date_or_status", "approved_prior_phase_model_output", "data/phase7/processed/COVENANT_SUMMARY.csv", cov["summary_id"], "approved_upstream", "N/D means no event in the selected modeled path or insufficient opening evidence, as applicable.", "2026-02-01 through 2031-01-31", "first_event_date_over_forecast")

    for candidate in ("STR-001", "STR-003", "STR-008"):
        row = first(maturity, candidate_id=candidate)
        add("maturity", "unsupported_maturity_gap", candidate, row["unsupported_maturity_gap"], "USD_millions", "approved_prior_phase_model_output", "data/phase7/processed/ULTIMATE_MATURITY_COMPARISON.csv", row["maturity_comparison_id"], "owner_reviewed_upstream", f"Bank-debt maturity gap at {row['maturity_date']}; horizons differ and are not directly comparable.", row["maturity_date"], "point_in_time_bank_debt_maturity_gap")
    common_rows = {
        "existing": first(common, candidate_id="STR-001", scenario_id="BASE"),
        "reference": first(common, candidate_id="STR-003", scenario_id="BASE"),
        "selected": first(common, candidate_id="STR-008", scenario_id="BASE"),
    }
    for label, row in common_rows.items():
        add("maturity", "common_horizon_total_funded_debt", label, row["ending_total_funded_debt"], "USD_millions", "approved_prior_phase_model_output", "data/phase7/processed/COMMON_HORIZON_COMPARISON.csv", row["common_horizon_id"], "owner_reviewed_upstream", "Total funded debt at the uniform common horizon; not a bank-debt maturity gap.", "2029-07-31", "point_in_time_total_funded_debt")
    add("maturity", "selected_common_horizon_ending_debt", "2029-07-31", common_rows["selected"]["ending_total_funded_debt"], "USD_millions", "approved_prior_phase_model_output", "data/phase7/processed/COMMON_HORIZON_COMPARISON.csv", common_rows["selected"]["common_horizon_id"], "owner_reviewed_upstream", "Total funded debt at the uniform common horizon; not a bank-debt maturity gap.", "2029-07-31", "point_in_time_total_funded_debt")
    add("maturity", "selected_minus_existing_common_horizon_debt", "2029-07-31", dec(common_rows["selected"]["ending_total_funded_debt"]) - dec(common_rows["existing"]["ending_total_funded_debt"]), "USD_millions", "approved_prior_phase_calculation", "data/phase7/processed/COMMON_HORIZON_COMPARISON.csv", f"{common_rows['selected']['common_horizon_id']};{common_rows['existing']['common_horizon_id']}", "owner_reviewed", "Selected less existing total funded debt at the same date.", "2029-07-31", "point_in_time_total_funded_debt_difference")
    add("maturity", "selected_minus_reference_common_horizon_debt", "2029-07-31", dec(common_rows["selected"]["ending_total_funded_debt"]) - dec(common_rows["reference"]["ending_total_funded_debt"]), "USD_millions", "approved_prior_phase_calculation", "data/phase7/processed/COMMON_HORIZON_COMPARISON.csv", f"{common_rows['selected']['common_horizon_id']};{common_rows['reference']['common_horizon_id']}", "owner_reviewed", "Selected less reference total funded debt at the same date.", "2029-07-31", "point_in_time_total_funded_debt_difference")

    risk = read_csv(ROOT / "data" / "phase9" / "processed" / "BORROWER_RISK_ASSESSMENT.csv")[0]
    add("risk", "borrower_risk_grade", "project_specific", risk["provisional_grade"], "status", "owner_reviewed_project_judgment", "data/phase9/processed/BORROWER_RISK_ASSESSMENT.csv", risk["assessment_id"], "owner_reviewed", "Project-specific qualitative assessment only; not a bank grade, agency rating, calibrated probability of default, or official borrower classification.", "committee_date_2025-12-15", "qualitative_project_assessment")
    gc = sorted((r for r in recovery if r["method"] == "going_concern"), key=lambda r: r["case_name"])
    ar = sorted((r for r in recovery if r["method"] == "asset_realization"), key=lambda r: r["case_name"])
    order = {"Low": 0, "Base": 1, "High": 2}
    for prefix, cases in (("going_concern", gc), ("asset_realization", ar)):
        for row in sorted(cases, key=lambda r: order[r["case_name"]]):
            add("recovery", f"{prefix}_proceeds", row["case_name"], row["illustrative_bank_allocation"], "USD_millions", "illustrative_sensitivity_only", "data/phase9/processed/RECOVERY_CASE_REGISTER.csv", row["case_id"], "owner_reviewed_upstream", row["limitations"])
            add("recovery", f"{prefix}_recovery", row["case_name"], row["illustrative_facility_recovery_percent"], "percent", "illustrative_sensitivity_only", "data/phase9/processed/RECOVERY_CASE_REGISTER.csv", row["case_id"], "owner_reviewed_upstream", row["limitations"])
    add("recovery", "illustrative_facility_claim", "2027-12-31", recovery[0]["facility_claim"], "USD_millions", "approved_prior_phase_model_output", "data/phase9/processed/RECOVERY_CASE_REGISTER.csv", recovery[0]["case_id"], "owner_reviewed_upstream", "Includes modeled term, revolver, and unpaid cash interest at the severe first-payment-failure date.")
    add("recovery", "official_facility_recovery", "public_information", N_D, "status", "not_determinable", "data/phase9/processed/FACILITY_RECOVERY_ASSESSMENT.csv", "P9FRA-001", "owner_reviewed_upstream", "Missing guarantor, collateral, priority, access, appraisal, and claims evidence.")
    return rows


def decision_register(decisions: list[dict[str, str]]) -> list[dict[str, str]]:
    evidence = {
        "recommendation": "P10M-015:P10M-091;P10R-001:P10R-012",
        "recommended facilities": "P10M-017:P10M-022",
        "bank hold": "P10M-026;docs/phase-0/CASE_CHARTER.md",
        "transaction rationale": "docs/phase-0/EXISTING_FINANCING.md;P10M-075:P10M-079",
        "fallback alternative": "P10M-079:P10M-081;P10R-012",
        "decisive strengths": "P10M-007:P10M-015;P10M-031:P10M-041",
        "decisive risks": "P10M-021:P10M-074;P10R-005:P10R-011",
        "conditions precedent": "P10CM-001:P10CM-013",
        "distribution restrictions": "P10CM-014:P10CM-015",
        "monitoring and escalation": "P10CM-018:P10CM-026",
        "risk-grade wording": "P10M-082;P10R-009",
        "recovery wording": "P10M-083:P10M-096",
        "residual refinancing dependency": "P10M-041;P10M-053;P10M-065;P10M-077:P10M-081",
        "strongest counterargument": "P10M-077:P10M-081;docs/phase-5/FINANCING_COMPARISON.md",
        "final memo language": "reports/credit_memo.md;reports/committee_brief.md",
        "repayment framing": "P10M-033:P10M-041;P10R-003",
        "covenant package": "data/phase7/processed/COVENANT_MATRIX.csv;P10CM-014:P10CM-020",
        "Credit Summary wording": "model/Quanex_Credit_Underwriting.xlsx",
    }
    return [
        {
            "decision_id": row["decision_id"], "topic": row["topic"],
            "working_decision": row["working_decision"],
            "decision_status": RECOMMENDATION_STATUS,
            "governing_evidence": evidence[row["topic"]],
            "conditionality": "Owner reviewed; all applicable closing, documentation, diligence, covenant, and monitoring requirements remain conditions, not satisfied facts.",
            "consequence_if_not_approved_or_satisfied": "Owner decision is recorded; if a material closing condition remains unsatisfied, do not close the modeled refinancing and use the mandatory fallback.",
            "owner_action_required": row["owner_action_required"],
        }
        for row in decisions
    ]


def risk_matrix() -> list[dict[str, str]]:
    items = [
        ("strength", "Full-year post-Tyman earnings", "FY2025 lender-base EBITDA was $225.344m, versus $179.358m in FY2024.", "Supports interim debt service, but includes accepted noncash/acquisition adjustments.", "Monthly lender-EBITDA and adjustment bridge.", "Adjustment acceptance is not cash realization.", "P10M-007;P10M-015"),
        ("strength", "Cash conversion recovery", "FY2025 CFO/FCF were $164.897m/$102.255m and 73.2%/45.4% of lender-base EBITDA.", "Improves confidence versus FY2024's weaker conversion.", "Working-capital, capex, and cash-adjustment reporting.", "Seasonality and acquisition perimeter still limit comparability.", "P10M-011:P10M-014"),
        ("strength", "Opening liquidity", "Selected Base minimum all-in liquidity is $263.902m over the forecast, including the January 31, 2026 opening position.", "Provides timing and operating-liquidity support, not debt repayment.", "$50m covenant, $75m warning, monthly eligibility certificate.", "Cash eligibility and drawability require final documents; a revolver draw increases or reallocates funded debt.", "P10M-023;P10CM-016;P10CM-022"),
        ("strength", "Debt discipline", "7.5% annual amortization plus a 50% ECF sweep; Base realizes $238.125m scheduled principal and $57.292m sweep cumulatively from February 1, 2026 through January 31, 2031.", "These are payment mechanisms applied to operating cash, not repayment sources.", "Payment ordering, sweep definition, and distribution restrictions.", "Base still leaves a $324.780m bank-debt gap at January 31, 2031.", "P10M-025;P10M-028;P10M-035:P10M-036"),
        ("risk", "Thin opening leverage cushion", "Opening gross leverage is 3.2285x, close to the inclusive 3.25x warning.", "Small earnings or debt variance can trigger immediate attention.", "No cash netting; final payoff; closing EBITDA/debt certificate.", "Closing cash-interest coverage remains N/D.", "P10M-022;P10CM-001:P10CM-005"),
        ("risk", "Integration and margin execution", "Tyman integration, plant stabilization, and $302.284m impairment reduce forecast confidence.", "Margin underperformance drives early warning and covenant pressure.", "Plant KPI, gross-margin bridge, and integration milestones.", "Impairment addback is mathematical but remains an adverse signal.", "DRV-003;DRV-004;DRV-008"),
        ("risk", "Working-capital and capex volatility", "FY2025 DIO rose to 72.22 days and capex to $62.642m; DPO remains N/D.", "Cash conversion can weaken despite reported EBITDA.", "Aging, purchase/AP bridge, and maintenance-capex schedule.", "No zero AP/other-WC assumption or unsupported capex cut.", "DRV-005;DRV-006;DRV-013"),
        ("risk", "Moderate covenant breach", "Moderate unmitigated/mitigated leverage peaks at 4.4893x/4.4670x and breaches on October 31, 2026; minimum liquidity remains $165.078m/$168.937m and no payment failure occurs.", "Conditional approval accepts early lender intervention, not covenant survival; mitigation does not restore compliance and no automatic waiver is assumed.", "Immediate reporting, distribution stop, corrective plan, and resize/non-debt-capital/restructure/no-close test if moderate is near expected case.", "A breach remains possible while liquidity and payment capacity are available; covenant is not loosened to remove it.", "P10M moderate paths;P10CM-021:P10CM-023"),
        ("risk", "Severe liquidity and payment failure", "Severe unmitigated liquidity reaches zero and cash-interest fails on 2027-12-31.", "The selected structure is not resilient to severe stress.", "Early warnings, reporting, distribution controls, and no-waiver analysis.", "Mitigations delay but do not eliminate severe failure.", "P10M severe paths"),
        ("risk", "Residual refinancing dependency", "Base unsupported bank-debt maturity gap is $324.780m at January 31, 2031.", "Operating cash does not self-liquidate the term; refinancing is not a demonstrated repayment source.", "Maturity plan begins at least 24 months early and escalates by 12 months.", "No takeout or refinancing proceeds are assumed; any refinancing is separately underwritten.", "P10M maturity;P10CM-026"),
        ("risk", "Information-quality weakness", "Cash-flow reporting-control material weakness remained open at FY2025 year-end.", "Reduces confidence in forecast cash classification and compliance reporting.", "Remediation milestones, testing evidence, and audit-committee reporting.", "No known misstatement is asserted.", "DRV-009;P10CM-020"),
        ("risk", "Legal, collateral, and recovery gaps", "Official facility recovery is N/D.", "Potential collateral realization, business-sale proceeds, and other default recoveries are secondary backstops only.", "Guarantees, collateral, perfection, priority, entity allocation, appraisal, claims, and realization-cost diligence.", "Full consolidated access is only a ceiling sensitivity; illustrative recovery is not official recovery.", "P10M recovery;P10CM-007:P10CM-009"),
        ("alternative", "Retain or amend existing facilities", "At July 31, 2029, existing/selected total funded debt is $495.368m/$514.754m, so selected is $19.386m higher. Existing matures August 1, 2029 with a $432.749m bank-debt gap; amendment economics are N/D.", "Avoids refinancing fees and near-term debt expansion; selected offers no faster same-horizon deleveraging.", "Use as mandatory fallback if Phase 10 conditions fail.", "Selected's lower $324.780m gap at January 31, 2031 partly reflects about 18 additional months and is not directly comparable.", "P7CH-001;P7CH-008;P7UM-001;P7UM-008"),
    ]
    return [
        {
            "matrix_id": f"P10R-{index:03d}", "type": kind, "credit_issue": issue,
            "evidence": evidence, "credit_consequence": consequence,
            "protection_or_mitigant": mitigant, "residual_risk": residual,
            "source_or_ids": source, "review_status": RECOMMENDATION_STATUS,
        }
        for index, (kind, issue, evidence, consequence, mitigant, residual, source) in enumerate(items, 1)
    ]


def conditions_and_monitoring() -> list[dict[str, str]]:
    items = [
        ("condition_precedent", "Verified $15m non-debt source", "Legal accessibility and funded cash in final funds flow; separate from $25m operating floor.", "No close; do not replace with incremental debt.", "P7OD-011;CP-012"),
        ("condition_precedent", "Final sources, uses, payoff and closing balances", "Executed payoff, January debt/cash/LC certificate, and zero unexplained uses gap.", "No close or resize with new approval.", "CP-001;CP-010;CP-016"),
        ("condition_precedent", "No incremental-debt substitution", "Funding instruction and legal documents prohibit replacing a missing non-debt source with debt.", "Modeled transaction is not authorized.", "P10D-002;P10D-005"),
        ("condition_precedent", "Closing cash-interest coverage", "Satisfactory LTM cash-interest evidence under final definitions.", "No close or separately approved restructure.", "CP-008;CP-009"),
        ("condition_precedent", "Final covenant and draw definitions", "Debt, EBITDA, ECF, cures, cash netting, draw conditions, default, and waiver mechanics.", "No close until lender/counsel approval.", "P7CP-001:P7CP-017"),
        ("condition_precedent", "Pricing, recurring fees, hedges and amendment economics", "Executed fee letters, hedge treatment, break costs, OID and final economics.", "No economic recommendation or closing.", "CP-014;CP-015"),
        ("condition_precedent", "Guarantee coverage", "Executed guarantees from eligible material domestic subsidiaries and current entity schedule.", "No close or explicit reduced-support approval.", "CP-004"),
        ("condition_precedent", "Collateral, lien releases, perfection and priority", "Release documents, searches, security documents, permitted-lien review, and perfection plan.", "No close or explicitly approved collateral exception.", "CP-002;CP-003;CP-007"),
        ("condition_precedent", "Foreign cash and unavailable assets", "Entity/jurisdiction cash schedule and acceptable exclusion of inaccessible assets.", "No credit to inaccessible cash or unsupported collateral.", "CP-011;GAP-004"),
        ("condition_precedent", "LC continuation or replacement", "Final LC schedule, beneficiary consents, replacement or cash-collateral mechanics counted once.", "No close while exposure is unresolved.", "CP-013"),
        ("condition_precedent", "Closing projections and liquidity support", "Approved integrated projections, 13-week liquidity view, and borrowing-base-like support where relevant; facility remains cash-flow lending, not ABL.", "No final approval or funding.", "CP-017;CP-019;CP-020"),
        ("condition_precedent", "Legal, KYC, sanctions, tax and authority", "Corporate authority, KYC/beneficial ownership, sanctions, tax, consents, and legal opinions.", "No funding where required evidence is absent.", "CP-005:CP-007;CP-024"),
        ("condition_precedent", "Full committed financing and syndication", "Executed commitments for the complete approved facilities and acceptable syndication.", "No close.", "CP-022"),
        ("ongoing_covenant", "No debt-funded buybacks", "Repurchases prohibited when debt funded or revolver outstanding.", "Restricted-payment block and escalation under final documents.", "P7OD-013;MON-024"),
        ("ongoing_covenant", "Distribution restrictions", "No default; leverage at or below 3.00x; usable liquidity at or above $75m; pro forma compliance; no debt-funded action.", "Suspend distributions and require consent where applicable.", "P7OD-013;MON-024"),
        ("ongoing_covenant", "Minimum liquidity and no-waiver drawability", "$50m proposed liquidity covenant, $75m warning, and post-breach drawability treatment subject to documents.", "Escalation, action plan, and no assumed continued draw.", "P7CP-006;P7CP-011;MON-012;MON-014"),
        ("ongoing_covenant", "Quarterly certificates and financial reporting", "Quarterly certificate within proposed 45 days and annual reporting within 90 days using executed definitions.", "Reporting exception and preservation of rights.", "MON-017"),
        ("monitoring_requirement", "Monthly liquidity and working capital", "Entity cash, revolver, LCs, DSO, DIO, AP/purchases, accruals, other operating working capital, and 13-week cash forecast when triggered.", "Increase to weekly reporting on liquidity or draw warning.", "MON-008:MON-014"),
        ("monitoring_requirement", "Monthly integration, margin, and operating package", "Volume/price/mix, gross margin, plant service, synergies, restructuring cash, and maintenance capex.", "Five-to-ten-business-day action plan on warning.", "MON-001:MON-007;MON-020:MON-022"),
        ("monitoring_requirement", "Control-remediation evidence", "Milestones, testing results, audit-committee oversight, and auditor updates for the cash-flow control weakness.", "Reporting exception, enhanced controls, or default analysis.", "CP-021;MON-019"),
        ("analyst_warning", "Gross leverage warning", "Inclusive 3.25x / 3.00x / 2.75x schedule with zero cash netting.", "Suspend repurchases, monthly reporting, and 10-business-day debt-reduction plan.", "MON-015"),
        ("analyst_warning", "Cash-interest coverage warning", "Below 3.50x; proposed covenant is below 3.00x.", "Revised forecast and amendment/waiver planning before breach.", "MON-016"),
        ("analyst_warning", "Usable-liquidity warning", "Below $75m; proposed covenant is below $50m.", "Immediate 13-week cash forecast and corrective plan.", "MON-012"),
        ("unresolved_diligence", "Official covenant compliance", "Final executed definitions and borrower certificates are unavailable publicly.", "Remain N/D; do not claim compliance.", "P7CP-001:P7CP-017"),
        ("unresolved_diligence", "Official recovery", "Complete guarantor, collateral, priority, appraisal, access, and claims evidence is absent.", "Remain N/D; sensitivities are alternatives only.", "P9FRA-001"),
        ("monitoring_requirement", "Maturity-refinancing strategy", "Documented plan refreshed over facility life; start at least 24 months before 2031 maturity and escalate at 12 months without executable financing.", "Watchlist and senior credit escalation; no refinancing assumed.", "MON-026"),
    ]
    return [
        {
            "requirement_id": f"P10CM-{index:03d}", "category": category,
            "requirement": name, "evidence_or_definition": evidence,
            "economic_or_control_value": consequence, "status": "open_not_satisfied_from_public_information",
            "consequence_if_unmet": consequence, "source_or_ids": source,
            "phase10_review_status": RECOMMENDATION_STATUS,
        }
        for index, (category, name, evidence, consequence, source) in enumerate(items, 1)
    ]


def source_ledger() -> list[dict[str, str]]:
    uses = {
        "docs/phase-0/CASE_CHARTER.md": "mandate, decision framing, hold, repayment hierarchy",
        "docs/phase-0/EXISTING_FINANCING.md": "existing terms, alternatives, refinancing rationale",
        "data/phase2/processed/historical_spread.csv": "reported historical summary and cash generation",
        "data/phase2/processed/historical_credit_metrics.csv": "cash conversion and historical ratios",
        "data/phase2/processed/earnings_bridges.csv": "earnings-definition bridge and lender-base EBITDA",
        "data/phase3/processed/RISK_DRIVER_MAP.csv": "borrower-specific risk mechanisms",
        "data/phase3/processed/INFORMATION_GAPS.csv": "open diligence boundaries",
        "data/phase4/processed/CONDITIONS_PRECEDENT.csv": "closing-condition foundation",
        "data/phase4/processed/LEGAL_STRUCTURE_REGISTER.csv": "guarantee, collateral, and legal limitations",
        "data/phase5/processed/BASE_CASE_CREDIT_METRICS.csv": "base repayment construction",
        "data/phase6/processed/SCENARIO_RESULTS.csv": "downside liquidity and payment-failure foundation",
        "data/phase7/processed/STRUCTURE_COMPARISON.csv": "selected structure and scenario results",
        "data/phase7/processed/COVENANT_SUMMARY.csv": "warning, breach, liquidity, and payment events",
        "data/phase7/processed/COMMON_HORIZON_COMPARISON.csv": "uniform-horizon debt comparison",
        "data/phase7/processed/ULTIMATE_MATURITY_COMPARISON.csv": "different-horizon maturity gaps",
        "data/phase7/processed/SOURCES_AND_USES_RECONCILIATION.csv": "closing funds-flow control",
        "data/phase8/processed/SCENARIO_CAPTURE_RESULTS.csv": "workbook-validated scenario metrics",
        "data/phase9/processed/BORROWER_RISK_ASSESSMENT.csv": "upstream borrower-risk assessment supporting the owner-reviewed project-specific qualitative assessment",
        "data/phase9/processed/RECOVERY_CASE_REGISTER.csv": "alternative illustrative recovery sensitivities",
        "data/phase9/processed/MONITORING_SCHEDULE.csv": "monitoring, warning, and escalation package",
    }
    return [
        {
            "ledger_id": f"P10L-{index:03d}", "source_path": relative,
            "source_category": "approved_prior_phase_artifact",
            "source_or_publication_date": "2025-12-15_or_earlier",
            "phase10_use": uses[relative], "sha256": sha256(ROOT / relative),
            "cutoff_status": "within_cutoff", "review_status": "approved_upstream",
            "limitations": "Phase 10 inherits the source artifact's classifications, dates, definitions, and limitations; it does not create a new underlying fact.",
        }
        for index, relative in enumerate(SOURCE_INPUTS, 1)
    ]


def document_qa_results() -> list[dict[str, str]]:
    notes = [
        "Decision, owner-reviewed status, moderate breach, repayment hierarchy, and failure rule are readable.",
        "Structure, all common-horizon balances, ultimate gap dates, and counterargument render without overlap.",
        "Borrower risks and acquisition-comparability boundary are fully visible.",
        "Historical table, cash-conversion chart, and earnings bridge are readable.",
        "Debt, legal, liquidity-support, and closing-coverage limitations are readable.",
        "Annual, cumulative, minimum, common-horizon, and maturity labels are distinct and readable.",
        "Moderate breach, severe failure, N/D recovery, conditions, and final recommendation are readable.",
        "Historical appendix and lender-base bridges are readable without footer overlap.",
        "Scenario appendix distinguishes warnings, breaches, liquidity, and payment failures.",
        "All 26 open conditions and monitoring rows are visible and legible.",
        "Recovery alternatives, secondary-backstop boundary, and N/D conclusion render cleanly.",
        "One-page brief is self-contained and readable with no clipping or overflow.",
    ]
    rows: list[dict[str, str]] = []
    for index, note in enumerate(notes, 1):
        brief = index == 12
        rows.append({
            "qa_id": f"P10Q-{index:03d}",
            "document": "committee_brief.pdf" if brief else "credit_memo.pdf",
            "page": "1" if brief else str(index),
            "rendered_path": f"temporary_visual_QA/{'committee_brief' if brief else 'credit_memo'}/page-{'01' if brief else f'{index:02d}'}.png",
            "status": "PASS",
            "checks_performed": "header/footer,tables,callouts,clipping,fonts,whitespace,horizon labels,decision wording",
            "review_note": note,
        })
    return rows


def metric_index(metrics: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {(row["metric_name"], row["scenario_or_period"]): row for row in metrics}


def make_memo(metrics: list[dict[str, str]]) -> str:
    ix = metric_index(metrics)
    def m(name: str, period: str) -> str:
        row = ix[(name, period)]
        return f"{row['display_value']} [{row['metric_id']}]"
    return f"""# Credit memorandum — Quanex Building Products Corporation

**Committee date / information cutoff:** December 15, 2025
**Hypothetical closing:** January 31, 2026
**Recommendation:** **Conditional Approval**
**Owner-review status:** `{RECOMMENDATION_STATUS}`
**Public-information case:** project recommendation only - not an actual bank approval, lender commitment, funding authorization, official compliance certificate, appraisal, legal opinion, official risk grade, or official recovery estimate.

## 1. Decision and exposure

**Conditional Approval** of a {m('term_facility', 'selected')} fully funded term facility and {m('revolver_commitment', 'selected')} revolver, with a participating-bank hold up to {m('bank_hold_cap', 'selected')} of combined commitments. All material conditions, covenants, monitoring requirements, and fallback protections remain mandatory. The borrower is Quanex Building Products Corporation; the project-specific qualitative risk assessment is **Elevated** [{ix[('borrower_risk_grade', 'project_specific')]['metric_id']}], not a bank grade, agency rating, calibrated probability of default, or official borrower classification.

What we lend: the selected senior secured cash-flow structure described above, not the original $650m request. Why refinance: term out persistent acquisition-related revolver usage, preserve working-capital capacity, add amortization and intervention rights, and extend maturity from August 2029 to January 2031. How repaid: primary repayment is recurring operating cash available for debt service after operating requirements, cash interest, cash taxes, working-capital needs, necessary maintenance capital expenditure, and other required uses. Scheduled amortization and the ECF sweep are payment mechanisms applied to available cash, not repayment sources. What can go wrong: opening leverage of 3.2285x near the 3.25x warning, no same-horizon deleveraging benefit, an October 31, 2026 moderate covenant breach that mitigation does not cure, integration/margin/working-capital/control risk, severe liquidity exhaustion and payment failure, and a $324.780m bank-debt maturity gap at January 31, 2031. Why acceptable conditionally: base interim debt service and minimum liquidity hold, the moderate breach creates early intervention while liquidity and payment capacity remain available, the bank hold is capped, no waiver is assumed, and a failed material condition triggers the existing-facility fallback rather than more debt. [P10D-001:P10D-018]

The proposed refinancing is not justified by faster same-horizon debt reduction. It is supportable only for its maturity extension, liquidity structure, amortization, lender protections, and monitoring package, subject to acceptable final economics and documentation.

The proposed covenant is intended to create early lender intervention while liquidity and payment capacity remain available. Conditional approval accepts the possibility of an early moderate-case covenant breach only because the structure preserves substantial liquidity, separates breach from payment failure, mandates reporting and corrective action, and does not assume an automatic waiver.

If borrower diligence, management projections, or updated pre-closing performance indicate that the modeled moderate case is closer to the expected case than to a downside case, the facility should be resized, require additional non-debt capital, be restructured, or not close.

## 2. Transaction and alternatives

Selected opening funded debt is {m('opening_funded_debt', 'selected')} and gross leverage is {m('opening_gross_leverage', 'selected')}; sources less uses are {m('sources_less_uses', 'selected')}. The structure requires a {m('conditional_non_debt_source', 'selected')} non-debt source that is separate from the {m('operating_cash_floor', 'selected')} operating cash floor. The term amortizes at {m('annual_term_amortization', 'selected')} annually, paid quarterly, and the ECF sweep is {m('ecf_sweep', 'selected')} subject to safeguards. [P10CM-001:P10CM-006]

At the July 31, 2029 common horizon, total funded debt is {m('common_horizon_total_funded_debt', 'existing')} under existing financing, {m('common_horizon_total_funded_debt', 'reference')} under the $650m reference, and {m('common_horizon_total_funded_debt', 'selected')} under the selected structure. Selected is {m('selected_minus_existing_common_horizon_debt', '2029-07-31')} higher than existing and {m('selected_minus_reference_common_horizon_debt', '2029-07-31')} higher than reference. There is no faster same-horizon deleveraging.

At their different ultimate maturities, bank-debt gaps are {m('unsupported_maturity_gap', 'STR-001')} at August 1, 2029, {m('unsupported_maturity_gap', 'STR-003')} at January 31, 2031, and {m('unsupported_maturity_gap', 'STR-008')} at January 31, 2031. The selected gap benefits partly from approximately 18 additional months; these bank-debt gaps must not be conflated with total funded debt at the common horizon. A limited amendment or extension remains economically N/D. If the $15m source, satisfactory closing coverage evidence, acceptable documentation, full commitments, or any other material condition fails, do not increase term debt or the revolver draw, loosen covenants, assume inaccessible cash, insert refinancing proceeds, assume a waiver, or assign unsupported recovery. Do not close the modeled refinancing; retain or amend the existing facilities through a limited amendment or extension. [P10D-005; P10CM-001:P10CM-013]

## 3. Borrower and business risk

Quanex manufactures components for building-products OEMs across Hardware, Extruded, and Custom Solutions. End markets include repair/remodeling, new residential construction, and selected commercial/industrial demand. FY2021–FY2023 are pre-Tyman, FY2024 includes roughly three months of Tyman, and FY2025 is the first full post-Tyman year; reported growth is not organic growth. [DRV-001; DRV-003; DRV-004]

The central operating issue is gross-margin and plant execution. FY2025's improved reported margin contains acquisition, mix, and synergy effects, while the $302.284m goodwill impairment is accepted mathematically in lender EBITDA but remains a major adverse acquisition and forecasting signal. Working-capital seasonality, maintenance versus integration capex, foreign-cash accessibility, and the unresolved cash-flow control weakness constrain confidence. [DRV-003:DRV-009; DRV-011; DRV-013]

## 4. Historical performance and earnings quality

FY2024 revenue / operating income were {m('revenue', 'FY2024')} / {m('operating_income', 'FY2024')}; FY2025 were {m('revenue', 'FY2025')} / {m('operating_income', 'FY2025')}. FY2025's GAAP loss includes the impairment and is not the same as recurring cash capacity. FY2024/FY2025 unadjusted EBITDA was {m('unadjusted_ebitda', 'FY2024')} / {m('unadjusted_ebitda', 'FY2025')}; owner-reviewed lender-base EBITDA was {m('lender_base_ebitda', 'FY2024')} / {m('lender_base_ebitda', 'FY2025')}. Contractual EBITDA remains an unofficial, partial public-information reconstruction. [P10M-001:P10M-016]

FY2025 CFO / FCF improved to {m('cash_flow_from_operations', 'FY2025')} / {m('free_cash_flow', 'FY2025')}, or {m('cfo_to_provisional_lender_normalized_ebitda', 'FY2025')} / {m('fcf_to_provisional_lender_normalized_ebitda', 'FY2025')} of lender-base EBITDA, versus FY2024 conversion of {m('cfo_to_provisional_lender_normalized_ebitda', 'FY2024')} / {m('fcf_to_provisional_lender_normalized_ebitda', 'FY2024')}. EBITDA addbacks do not reverse cash outflows, and the composite FY2025 adjustment remains unresolved for lender credit. [P10R-001; P10R-002]

## 5. Debt, legal structure, and liquidity

The selected structure opens with {m('opening_revolver_draw', 'selected')} drawn and {m('base_all_in_liquidity', 'selected')} all-in usable liquidity. The revolver is reserved for working capital, but legal drawability depends on representations, no default, covenant compliance, and final documents. No covenant cash is netted. [P10M-019:P10M-024; P10CM-016]

Public evidence does not complete the post-Tyman guarantor roster, eligible-collateral scope, lien releases, perfection, priority, foreign-asset access, or cash eligibility. The intended domestic guarantee and personal-property collateral package is conditional, not an assertion that all consolidated assets secure the facility. LC continuation and final payoff mechanics also remain closing conditions. [P10CM-007:P10CM-010]

## 6. Base repayment and refinancing

FY2026 annual lender EBITDA is {m('fy2026_lender_ebitda', 'BASE')}. Cumulative from February 1, 2026 through January 31, 2031, modeled operating cash / CFADS are {m('modeled_operating_cash', 'BASE')} / {m('cfads', 'BASE')}; cumulative cash interest, scheduled principal, and ECF sweep over that same model period are {m('cash_interest', 'BASE')}, {m('scheduled_principal', 'BASE')}, and {m('ecf_sweep_realized', 'BASE')}. Minimum cash-interest coverage over the forecast is {m('minimum_cash_interest_coverage', 'BASE')}; minimum all-in liquidity over the forecast, including the January 31, 2026 opening position, is {m('all_in_minimum_liquidity', 'BASE')}. These are modeled public-information outputs, not management guidance. [P10M scenario records]

At the common July 31, 2029 horizon, selected total funded debt is {m('selected_common_horizon_ending_debt', '2029-07-31')}. At the later January 31, 2031 selected maturity, the unsupported bank-debt gap is {m('unsupported_maturity_gap', 'BASE')}. Accessible cash and undrawn, legally drawable revolving capacity provide timing and liquidity support only. Drawing the revolver is not repayment of consolidated debt; it increases or reallocates funded debt. Future refinancing is an unresolved, separately underwritten maturity dependency, not secondary repayment, and no takeout proceeds are assumed. A maturity plan must begin at least 24 months before maturity and escalate at 12 months without an executable solution. [P10CM-026]

## 7. Downside and covenant intervention

Moderate unmitigated FY2026 annual EBITDA is {m('fy2026_lender_ebitda', 'MODERATE_UNMITIGATED')}; maximum leverage / minimum coverage over the forecast are {m('maximum_gross_leverage', 'MODERATE_UNMITIGATED')} / {m('minimum_cash_interest_coverage', 'MODERATE_UNMITIGATED')}. Moderate mitigated maximum leverage / minimum coverage are {m('maximum_gross_leverage', 'MODERATE_MITIGATED')} / {m('minimum_cash_interest_coverage', 'MODERATE_MITIGATED')}. Both paths warn and breach on October 31, 2026; mitigation does not restore leverage covenant compliance. Minimum all-in liquidity over the forecast remains positive at {m('all_in_minimum_liquidity', 'MODERATE_UNMITIGATED')} / {m('all_in_minimum_liquidity', 'MODERATE_MITIGATED')}, and neither modeled path reaches liquidity exhaustion or payment failure. No automatic waiver is assumed. January 31, 2031 bank-debt gaps are {m('unsupported_maturity_gap', 'MODERATE_UNMITIGATED')} / {m('unsupported_maturity_gap', 'MODERATE_MITIGATED')}. [P10M moderate paths]

Severe unmitigated reaches warning in April 2026, breach in October 2026, zero usable liquidity in July 2027, and mandatory cash-interest failure on December 31, 2027. Maximum leverage / minimum coverage are {m('maximum_gross_leverage', 'SEVERE_UNMITIGATED')} / {m('minimum_cash_interest_coverage', 'SEVERE_UNMITIGATED')}; the maturity gap is {m('unsupported_maturity_gap', 'SEVERE_UNMITIGATED')}. Severe mitigation delays but does not eliminate failure and leaves {m('unsupported_maturity_gap', 'SEVERE_MITIGATED')}. Lower debt caused by curtailed borrowing or unpaid obligations is not improvement. [P10M-066:P10M-074; P10CM-021:P10CM-023]

## 8. Recovery and risk assessment

The illustrative facility claim is {m('illustrative_facility_claim', '2027-12-31')}. Going-concern proceeds span {m('going_concern_proceeds', 'Low')} / {m('going_concern_proceeds', 'Base')} / {m('going_concern_proceeds', 'High')}, corresponding to {m('going_concern_recovery', 'Low')} / {m('going_concern_recovery', 'Base')} / {m('going_concern_recovery', 'High')}. Full-access asset-realization ceiling proceeds span {m('asset_realization_proceeds', 'Low')} / {m('asset_realization_proceeds', 'Base')} / {m('asset_realization_proceeds', 'High')}, with {m('asset_realization_recovery', 'Low')} / {m('asset_realization_recovery', 'Base')} / {m('asset_realization_recovery', 'High')} recoveries. The two methods are alternatives and are never added. [P10M-083:P10M-095]

Official facility recovery remains **N/D** [{ix[('official_facility_recovery', 'public_information')]['metric_id']}]. Potential collateral realization, business-sale proceeds, or other recoveries after default are secondary repayment backstops, subject to legal access, guarantees, collateral scope, perfection, lien priority, entity allocation, competing claims, realization costs, and valuation evidence. The $62.619m retained-obligation deduction is applied once and establishes no legal ranking. The full consolidated-access case is only an upper-bound ceiling; actual accessibility remains N/D. Recovery does not improve the Elevated project-specific risk assessment. [P10D-011:P10D-012]

## 9. Conditions, monitoring, and conclusion

Closing conditions cover the verified $15m source; final payoff and funds flow; closing coverage; covenant and draw definitions; final economics; domestic guarantees; collateral, releases, perfection, and priority; foreign-cash treatment; LC mechanics; projections; legal/KYC/tax/authority; and full committed financing. Ongoing protections cover distributions, minimum liquidity, reporting, certificates, control remediation, and maturity planning. Analyst warnings remain distinct from covenant breaches. [P10CM-001:P10CM-026]

At the July 31, 2029 common horizon, the selected structure leaves approximately $19.4 million more total funded debt than retaining the existing facilities. Quanex could therefore avoid refinancing fees and near-term debt expansion by retaining or amending its current financing. The lower selected maturity gap is achieved partly because the proposed facility remains outstanding approximately 18 months longer.

The response is not faster deleveraging or moderate covenant survival. If fully conditioned, the selected structure reallocates acquisition usage into term debt, preserves working-capital capacity, adds amortization, a sweep, earlier intervention and monitoring, extends maturity, caps the bank hold, and supplies a mandatory fallback. Without those protections, evidence, and acceptable economics, the counterargument wins and the modeled transaction should not close.

**Conclusion:** **Conditional Approval**; owner-review status `{RECOMMENDATION_STATUS}` for all 18 P10D decisions. This project recommendation does not authorize funding and does not represent actual bank approval or commitment.

---

## Technical appendices

### Appendix A — historical financial summary

| USD millions | FY2024 | FY2025 |
|---|---:|---:|
| Revenue | {m('revenue', 'FY2024')} | {m('revenue', 'FY2025')} |
| Operating income | {m('operating_income', 'FY2024')} | {m('operating_income', 'FY2025')} |
| Unadjusted EBITDA | {m('unadjusted_ebitda', 'FY2024')} | {m('unadjusted_ebitda', 'FY2025')} |
| Lender-base EBITDA | {m('lender_base_ebitda', 'FY2024')} | {m('lender_base_ebitda', 'FY2025')} |
| CFO | {m('cash_flow_from_operations', 'FY2024')} | {m('cash_flow_from_operations', 'FY2025')} |
| FCF | {m('free_cash_flow', 'FY2024')} | {m('free_cash_flow', 'FY2025')} |

### Appendix B — scenario and maturity comparison

| Case | Max leverage | Min coverage | Min liquidity | Unsupported maturity gap |
|---|---:|---:|---:|---:|
| Base | {m('maximum_gross_leverage', 'BASE')} | {m('minimum_cash_interest_coverage', 'BASE')} | {m('all_in_minimum_liquidity', 'BASE')} | {m('unsupported_maturity_gap', 'BASE')} |
| Moderate unmitigated | {m('maximum_gross_leverage', 'MODERATE_UNMITIGATED')} | {m('minimum_cash_interest_coverage', 'MODERATE_UNMITIGATED')} | {m('all_in_minimum_liquidity', 'MODERATE_UNMITIGATED')} | {m('unsupported_maturity_gap', 'MODERATE_UNMITIGATED')} |
| Severe unmitigated | {m('maximum_gross_leverage', 'SEVERE_UNMITIGATED')} | {m('minimum_cash_interest_coverage', 'SEVERE_UNMITIGATED')} | {m('all_in_minimum_liquidity', 'SEVERE_UNMITIGATED')} | {m('unsupported_maturity_gap', 'SEVERE_UNMITIGATED')} |

### Appendix C — covenant and condition summary

Proposed gross leverage covenants step from 3.50x to 3.25x to 3.00x; analyst warnings are 3.25x / 3.00x / 2.75x. Proposed minimum cash-interest coverage is 3.00x with a 3.50x warning, and proposed minimum usable liquidity is $50m with a $75m warning. Opening coverage remains N/D until final LTM cash-interest evidence is available. Final legal definitions control. [P10CM-004:P10CM-005; P10CM-016; P10CM-021:P10CM-023]

### Appendix D — recovery, sources, and definitions

Recovery cases are illustrative, alternative sensitivities, not an appraisal or official estimate. `N/D` means not determinable; `N/M` is reserved for nonpositive ratio denominators. All dollar amounts are USD millions unless stated. Material figures trace through P10M records to approved prior-phase artifacts in `docs/phase-10/SOURCE_LEDGER.csv`. Information first published after December 15, 2025 is excluded.
"""


def make_brief(metrics: list[dict[str, str]]) -> str:
    ix = metric_index(metrics)
    def d(name: str, period: str) -> str:
        return ix[(name, period)]["display_value"]
    return f"""# Quanex credit committee brief

**Information cutoff:** December 15, 2025 | **Hypothetical closing:** January 31, 2026
**Recommendation:** **Conditional Approval** | **Owner-review status:** `{RECOMMENDATION_STATUS}`

## Decision

**Conditional Approval** of a {d('term_facility', 'selected')} fully funded term facility plus a {d('revolver_commitment', 'selected')} revolver, with a {d('opening_revolver_draw', 'selected')} opening draw, a bank hold up to {d('bank_hold_cap', 'selected')} of combined commitments, and a conditional {d('conditional_non_debt_source', 'selected')} non-debt source. The proposed refinancing is not justified by faster same-horizon debt reduction. It is supportable only for its maturity extension, liquidity structure, amortization, lender protections, and monitoring package, subject to acceptable final economics and documentation.

## Repayment and key metrics

Primary repayment is recurring operating cash available for debt service after operating requirements, cash interest, cash taxes, working-capital needs, necessary maintenance capex, and other required uses. Amortization and the ECF sweep are payment mechanisms, not sources. Accessible cash and legally drawable revolver capacity are timing/liquidity support only; a draw increases or reallocates funded debt. Refinancing is an unresolved, separately underwritten maturity dependency, not secondary repayment; no takeout is assumed. Potential collateral or business-sale recovery is the secondary backstop; official recovery is N/D.

| Metric | Result |
|---|---:|
| FY2025 lender-base EBITDA | {d('lender_base_ebitda', 'FY2025')} |
| Opening funded debt / gross leverage | {d('opening_funded_debt', 'selected')} / {d('opening_gross_leverage', 'selected')} |
| Base minimum all-in liquidity over forecast incl. opening | {d('base_all_in_liquidity', 'selected')} |
| Base minimum cash-interest coverage over forecast | {d('minimum_cash_interest_coverage', 'BASE')} |
| 07/31/2029 total funded debt: existing / reference / selected | {d('common_horizon_total_funded_debt', 'existing')} / {d('common_horizon_total_funded_debt', 'reference')} / {d('common_horizon_total_funded_debt', 'selected')} |
| 01/31/2031 selected bank-debt maturity gap | {d('unsupported_maturity_gap', 'BASE')} |
| Project-specific risk / official recovery | Elevated / N/D |

## Decisive strengths

FY2025 cash conversion recovered; Base services interim debt; opening liquidity is substantial; 7.5% amortization, 50% ECF sweep, covenants, and reporting create earlier lender intervention.

## Decisive risks and downside

Opening leverage is 3.2285x, close to the 3.25x warning; Tyman integration, margin, working capital, capex, and controls remain material. Moderate unmitigated/mitigated maximum leverage is {d('maximum_gross_leverage', 'MODERATE_UNMITIGATED')} / {d('maximum_gross_leverage', 'MODERATE_MITIGATED')}; minimum coverage is {d('minimum_cash_interest_coverage', 'MODERATE_UNMITIGATED')} / {d('minimum_cash_interest_coverage', 'MODERATE_MITIGATED')}; minimum liquidity remains {d('all_in_minimum_liquidity', 'MODERATE_UNMITIGATED')} / {d('all_in_minimum_liquidity', 'MODERATE_MITIGATED')}. Both paths warn and breach on October 31, 2026; mitigation does not restore compliance, neither modeled path exhausts liquidity or fails payment, and no automatic waiver is assumed. January 31, 2031 moderate-unmitigated / severe-unmitigated bank-debt gaps are {d('unsupported_maturity_gap', 'MODERATE_UNMITIGATED')} / {d('unsupported_maturity_gap', 'SEVERE_UNMITIGATED')}. Severe stress reaches zero liquidity and payment failure; mitigation delays but does not remove failure.

The proposed covenant is intended to create early lender intervention while liquidity and payment capacity remain available. Conditional approval accepts the possibility of an early moderate-case covenant breach only because the structure preserves substantial liquidity, separates breach from payment failure, mandates reporting and corrective action, and does not assume an automatic waiver.

At the July 31, 2029 common horizon, the selected structure leaves approximately $19.4 million more total funded debt than retaining the existing facilities. Quanex could therefore avoid refinancing fees and near-term debt expansion by retaining or amending its current financing. The lower selected maturity gap is achieved partly because the proposed facility remains outstanding approximately 18 months longer.

## Principal conditions and fallback

Verify and fund the $15m non-debt source; reconcile payoff/funds flow; prove closing coverage; finalize economics and covenant/draw definitions; complete guarantees, collateral, perfection, priority, cash-access, LC, legal/KYC/tax, projections, and committed-financing diligence; impose distribution/reporting/control-remediation and maturity-plan requirements. If borrower diligence, management projections, or updated pre-closing performance indicates that moderate is closer to expected than downside, resize, require additional non-debt capital, restructure, or do not close. If any material condition fails, do not increase term debt or the revolver draw, loosen covenants, assume inaccessible cash, insert refinancing proceeds, assume a waiver, or assign unsupported recovery. Retain or amend existing facilities through a limited amendment or extension.

Public-information, hypothetical-transaction project recommendation only. Not an actual bank approval, lender commitment, funding authorization, official compliance certificate, legal opinion, appraisal, official grade, or official recovery estimate. Ultimate maturity comparisons use different dates and cash-generation periods.
"""


def write_docs(metrics: list[dict[str, str]], risks: list[dict[str, str]], conditions: list[dict[str, str]]) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    (DOCS / "METHODOLOGY.md").write_text(f"""# Phase 10 methodology

Phase 10 converts the approved Phase 0-9 record into a lender decision package without adding external evidence. The information cutoff remains **December 15, 2025** and the closing remains hypothetical at **January 31, 2026**.

The workflow reads {len(SOURCE_INPUTS)} approved prior-phase artifacts, preserves their fact/calculation/term/judgment classifications, and writes {len(metrics)} committee metrics with direct lineage and explicit measurement horizons. All 18 recommendation judgments are separately recorded as `{RECOMMENDATION_STATUS}`. Owner review does not transform assumptions into facts or open conditions into completed diligence. Conditions remain separated into conditions precedent, ongoing covenants, monitoring requirements, analyst warnings, and unresolved diligence.

The memo and brief are generated from the same registers as the workbook summary. The system Python orchestrates data and validation; the bundled Python 3.12 runtime supplies ReportLab 4.4.9 and Pillow 12.3.0 for PDF/chart rendering. The existing artifact-tool and LibreOffice/Excel validation chain is retained for the workbook. No live network access is used.

The repository-root `.gitattributes` classifies PDF deliverables as binary with `*.pdf -diff -merge -text`. This portable repository rule prevents system-level text-conversion attributes from treating valid PDF object and cross-reference syntax as text while preserving ordinary whitespace checks for source and data files.

The July 31, 2029 common-horizon comparison uses total funded debt: $495.368m existing, $507.954m reference, and $514.754m selected. Ultimate gaps use bank debt and their contractual dates: $432.749m existing at August 1, 2029 and $340.948m reference / $324.780m selected at January 31, 2031. These measures are never conflated. Recovery methods remain alternatives. Official recovery and opening cash-interest coverage remain `N/D`. The decision remains a hypothetical public-information project recommendation, not an actual bank approval or commitment.
""", encoding="utf-8")
    # Preserve the approved post-PDF-classification artifact byte-for-byte.  That
    # commit added the three-line Git-attribute paragraph with LF endings to an
    # existing CRLF document; release reproduction must not silently normalize
    # the already approved Phase 10 artifact.
    methodology_path = DOCS / "METHODOLOGY.md"
    methodology_lines = methodology_path.read_text(encoding="utf-8").splitlines()
    methodology_path.write_bytes((
        "".join(line + "\r\n" for line in methodology_lines[:6])
        + "".join(line + "\n" for line in methodology_lines[6:9])
        + "".join(line + "\r\n" for line in methodology_lines[9:])
    ).encode("utf-8"))
    (DOCS / "DECISION_RATIONALE.md").write_text(f"""# Phase 10 decision rationale

**Recommendation:** Conditional Approval, owner-review status `{RECOMMENDATION_STATUS}`.

The evidence supports conditional - not unconditional - approval because Base operations service interim debt, FY2025 cash conversion recovered, minimum liquidity is substantial, and the selected $635m term / $300m revolver structure adds amortization, an ECF sweep, intervention thresholds, and a defined fallback. Approval is constrained by 3.2285x opening leverage, no same-horizon deleveraging advantage, an October 31, 2026 moderate breach that mitigation does not cure, a $324.780m bank-debt gap at January 31, 2031, severe-case liquidity exhaustion and payment failure, Tyman integration and impairment risk, the cash-flow control weakness, and incomplete legal, collateral, cash-access, coverage, fee, and commitment evidence.

At the July 31, 2029 common horizon, selected total funded debt is $514.754m, $19.386m higher than existing and $6.800m higher than the reference structure. The selected refinancing is supportable only for maturity extension, liquidity structure, amortization, lender protections, and monitoring, subject to acceptable economics and documentation. Its lower January 31, 2031 bank-debt gap benefits partly from approximately 18 extra months. Primary repayment is recurring operating cash after required uses. Amortization and the ECF sweep are payment mechanisms; revolver capacity is liquidity support; refinancing is an unresolved separately underwritten dependency; recovery is a secondary backstop and official recovery is N/D.

There are {len(risks)} explicit strength/risk/alternative entries and {len(conditions)} categorized conditions and monitoring requirements. All 18 P10D decisions are owner reviewed, while every stated CP and unresolved diligence item remains open. If a material condition fails, debt, covenant loosening, inaccessible cash, refinancing, waiver, or unsupported recovery may not replace it; the mandatory fallback is retention or a limited amendment/extension.
""", encoding="utf-8")
    (DOCS / "PHASE11_HANDOFF.md").write_text(f"""# Phase 11 handoff

Phase 11 has not started. Phase 10 is an owner-reviewed Conditional Approval project recommendation with status `{RECOMMENDATION_STATUS}`. All 18 P10D decisions are owner reviewed, but no condition is represented as satisfied and no actual bank approval, lender commitment, funding authorization, legal opinion, official grade, or official recovery estimate is created. Phase 11 release QA must preserve the corrected repayment hierarchy, unfavorable common-horizon comparison, explicit horizons, moderate breach, mandatory fallback, and approved analytics.
""", encoding="utf-8")
    (REPORTS / "credit_memo.md").write_text(make_memo(metrics), encoding="utf-8")
    (REPORTS / "committee_brief.md").write_text(make_brief(metrics), encoding="utf-8")


def build_data() -> dict[str, object]:
    head = git_head()
    if not approved_lineage(head):
        raise Phase10Error(f"HEAD is outside the approved Phase 9 lineage: {head}")
    decisions = owner_review_decisions()
    metrics = committee_metrics()
    risks = risk_matrix()
    conditions = conditions_and_monitoring()
    ledger = source_ledger()
    write_csv(RAW / "STARTING_CHECKPOINT.csv", [{
        "repository": "owencchapman24/quanex-credit-underwriting", "branch": "main",
        # The checkpoint records the Phase 9 input boundary, not the later
        # release commit from which deterministic regeneration is invoked.
        "approved_phase9_commit": APPROVED_PHASE9_COMMIT, "local_head": APPROVED_PHASE9_COMMIT,
        "source_input_signature": source_signature(), "information_cutoff": INFORMATION_CUTOFF,
        "hypothetical_closing": HYPOTHETICAL_CLOSING,
        "recommendation_status": RECOMMENDATION_STATUS,
        "recommendation": RECOMMENDATION,
        "recommendation_display": RECOMMENDATION_DISPLAY,
    }])
    write_csv(RAW / "OWNER_REVIEW_DECISIONS.csv", decisions)
    write_csv(PROCESSED / "DECISION_REGISTER.csv", decision_register(decisions))
    write_csv(PROCESSED / "COMMITTEE_METRICS.csv", metrics)
    write_csv(PROCESSED / "RISK_MITIGANT_MATRIX.csv", risks)
    write_csv(PROCESSED / "CONDITIONS_AND_MONITORING.csv", conditions)
    write_csv(DOCS / "SOURCE_LEDGER.csv", ledger)
    write_csv(PROCESSED / "DOCUMENT_QA_RESULTS.csv", document_qa_results())
    write_docs(metrics, risks, conditions)
    payload = {
        "recommendation": RECOMMENDATION,
        "recommendation_display": RECOMMENDATION_DISPLAY,
        "recommendation_status": RECOMMENDATION_STATUS,
        "metrics": metrics,
        "decisions": decisions,
        "risks": risks,
        "conditions": conditions,
    }
    PROCESSED.mkdir(parents=True, exist_ok=True)
    (PROCESSED / "WORKBOOK_INPUTS.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def run_artifact_tool(mode: str, baseline: Path, preview_dir: Path | None = None) -> None:
    if not NODE.is_file() or not NODE_MODULES.is_dir():
        raise Phase10Error("Bundled artifact-tool Node runtime is unavailable")
    with tempfile.TemporaryDirectory(prefix="quanex-phase10-artifact-") as temp_name:
        temp = Path(temp_name)
        shutil.copy2(ROOT / "scripts" / "build-phase10.mjs", temp / "build-phase10.mjs")
        junction = temp / "node_modules"
        subprocess.run([
            "powershell", "-NoProfile", "-Command",
            f"New-Item -ItemType Junction -Path '{junction}' -Target '{NODE_MODULES}' | Out-Null",
        ], check=True)
        args = [str(NODE), str(temp / "build-phase10.mjs"), mode, str(ROOT), str(baseline)]
        if preview_dir is not None:
            args.append(str(preview_dir))
        result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        if result.returncode:
            raise Phase10Error(f"Artifact-tool {mode} failed with exit code {result.returncode}")
        MODEL.with_name(MODEL.name + ".inspect.ndjson").unlink(missing_ok=True)


def phase9_baseline(path: Path) -> None:
    with path.open("wb") as handle:
        result = subprocess.run(
            ["git", "show", f"{APPROVED_PHASE9_COMMIT}:model/Quanex_Credit_Underwriting.xlsx"],
            cwd=ROOT, stdout=handle,
        )
    if result.returncode:
        raise Phase10Error("Unable to extract approved Phase 9 workbook baseline")


def build_workbook() -> None:
    with tempfile.TemporaryDirectory(prefix="quanex-phase10-baseline-") as temp_name:
        baseline = Path(temp_name) / "Phase9.xlsx"
        phase9_baseline(baseline)
        run_artifact_tool("build", baseline)


def canonicalize_workbook() -> dict[str, object]:
    """Calculate a disposable generated candidate, then promote it exactly once."""
    with tempfile.TemporaryDirectory(prefix="quanex-phase10-canonical-") as temp_name:
        candidate = Path(temp_name) / MODEL.name
        shutil.copy2(MODEL, candidate)
        report = phase9.run_libreoffice("inspect", candidate)
        shutil.copy2(candidate, MODEL)
    return report


def build_pdfs() -> None:
    if not BUNDLED_PYTHON.is_file():
        raise Phase10Error("Bundled PDF Python runtime is unavailable")
    result = subprocess.run(
        [str(BUNDLED_PYTHON), str(ROOT / "scripts" / "render-phase10.py"), "build", str(ROOT)],
        cwd=ROOT, text=True, capture_output=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    if result.returncode:
        raise Phase10Error("Phase 10 PDF generation failed")


def pdf_metadata() -> dict[str, object]:
    result = subprocess.run(
        [str(BUNDLED_PYTHON), str(ROOT / "scripts" / "render-phase10.py"), "inspect", str(ROOT)],
        cwd=ROOT, text=True, capture_output=True,
    )
    if result.returncode:
        raise Phase10Error(result.stderr or "PDF inspection failed")
    return json.loads(result.stdout)


def normalized_workbook_fingerprint() -> str:
    excluded = {"docProps/core.xml", "xl/calcChain.xml", "xl/sharedStrings.xml"}
    digest = hashlib.sha256()
    digest.update(source_signature().encode("ascii"))
    digest.update((ROOT / "scripts" / "build-phase10.mjs").read_bytes())
    with zipfile.ZipFile(MODEL) as archive:
        for name in sorted(archive.namelist()):
            if name in excluded or (name.startswith("xl/drawings/drawing") and name.endswith(".xml")):
                continue
            data = archive.read(name)
            if (name.startswith("xl/charts/chart") or name.startswith("xl/drawings/charts/chart")) and name.endswith(".xml"):
                axis_ids: dict[bytes, bytes] = {}
                def normalize(match: re.Match[bytes]) -> bytes:
                    original = match.group(2)
                    axis_ids.setdefault(original, str(len(axis_ids) + 1).encode("ascii"))
                    return match.group(1) + axis_ids[original] + match.group(3)
                data = re.sub(rb'(<c:(?:axId|crossAx) val=")(\d+)("/>)', normalize, data)
            digest.update(name.encode("utf-8"))
            digest.update(data)
    return digest.hexdigest()


NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
REL_NS = {"p": "http://schemas.openxmlformats.org/package/2006/relationships"}


def xlsx_cell_text(sheet_name: str, address: str) -> str:
    with zipfile.ZipFile(MODEL) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {r.attrib["Id"]: r.attrib["Target"] for r in rels.findall("p:Relationship", REL_NS)}
        sheet = next(s for s in workbook.findall(".//m:sheet", NS) if s.attrib["name"] == sheet_name)
        target = rel_map[sheet.attrib[f"{{{NS['r']}}}id"]].lstrip("/")
        path = target if target.startswith("xl/") else "xl/" + target
        root = ET.fromstring(archive.read(path))
        cell = next((c for c in root.findall(".//m:c", NS) if c.attrib.get("r") == address), None)
        if cell is None:
            return ""
        if cell.attrib.get("t") == "inlineStr":
            return "".join(node.text or "" for node in cell.findall(".//m:t", NS))
        value = cell.find("m:v", NS)
        if value is None:
            return ""
        text = value.text or ""
        if cell.attrib.get("t") == "s" and "xl/sharedStrings.xml" in archive.namelist():
            shared = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            item = shared.findall("m:si", NS)[int(text)]
            return "".join(node.text or "" for node in item.findall(".//m:t", NS))
        return text


def workbook_metadata() -> dict[str, object]:
    structure = phase8.workbook_structure()
    with zipfile.ZipFile(MODEL) as archive:
        chart_count = len([
            name for name in archive.namelist()
            if (name.startswith("xl/charts/chart") or name.startswith("xl/drawings/charts/chart"))
            and name.endswith(".xml")
        ])
    return {
        "sha256": sha256(MODEL), "size_bytes": MODEL.stat().st_size,
        "sheet_count": len(structure["sheets"]), "formula_count": structure["formula_count"],
        "chart_count": chart_count, "saved_scenario": xlsx_cell_text("Assumptions", "D4"),
        "normalized_fingerprint": normalized_workbook_fingerprint(),
        "external_links": len(structure["external_links"]), "formula_errors": len(structure["formula_errors"]),
        "checks_dependencies": len(structure["checks_dependencies"]),
    }


def consistency_results() -> list[dict[str, str]]:
    metrics = read_csv(PROCESSED / "COMMITTEE_METRICS.csv")
    ix = metric_index(metrics)
    memo = (REPORTS / "credit_memo.md").read_text(encoding="utf-8")
    brief = (REPORTS / "committee_brief.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    controls: list[tuple[str, bool, str, str, str]] = []
    def add(category: str, name: str, passed: bool, observed: object, expected: object) -> None:
        controls.append((category, passed, name, str(observed), str(expected)))
    for artifact_name, text in (("memo", memo), ("brief", brief), ("README", readme)):
        add("recommendation", f"{artifact_name} status", RECOMMENDATION_STATUS in text and "provisional_pending_owner_review" not in text, RECOMMENDATION_STATUS in text, True)
        add("recommendation", f"{artifact_name} conditional approval", "conditional approval" in text.lower(), "conditional approval" in text.lower(), True)
        add("recommendation", f"{artifact_name} fallback", "retain or amend" in text.lower(), "retain or amend" in text.lower(), True)
        add("cutoff", f"{artifact_name} cutoff", "December 15, 2025" in text, "December 15, 2025" in text, True)
    required_displays = [
        ("lender_base_ebitda", "FY2025"), ("opening_funded_debt", "selected"),
        ("opening_gross_leverage", "selected"), ("base_all_in_liquidity", "selected"),
        ("unsupported_maturity_gap", "BASE"), ("unsupported_maturity_gap", "MODERATE_UNMITIGATED"),
        ("unsupported_maturity_gap", "SEVERE_UNMITIGATED"),
    ]
    for key in required_displays:
        shown = ix[key]["display_value"]
        add("numerical", f"memo contains {key}", shown in memo, shown in memo, shown)
        add("numerical", f"brief contains {key}", shown in brief, shown in brief, shown)
    add("workbook", "recommendation banner", "Conditional Approval" in xlsx_cell_text("Credit Summary", "C5"), xlsx_cell_text("Credit Summary", "C5"), "Conditional Approval")
    add("workbook", "recommendation status", RECOMMENDATION_STATUS in xlsx_cell_text("Credit Summary", "I48"), xlsx_cell_text("Credit Summary", "I48"), RECOMMENDATION_STATUS)
    add("workbook", "fallback", "limited amendment/extension" in xlsx_cell_text("Credit Summary", "J54"), xlsx_cell_text("Credit Summary", "J54"), "limited amendment/extension")
    add("workbook", "official recovery", "N/D" in xlsx_cell_text("Credit Summary", "I55"), xlsx_cell_text("Credit Summary", "I55"), "N/D")
    return [
        {
            "consistency_id": f"P10C-{index:03d}", "category": category,
            "test_name": name, "status": "PASS" if passed else "FAIL",
            "observed": observed, "expected": expected,
        }
        for index, (category, passed, name, observed, expected) in enumerate(controls, 1)
    ]


def changed_paths() -> list[str]:
    result = subprocess.run(["git", "status", "--porcelain=v1", "-uall"], cwd=ROOT, text=True, capture_output=True, check=True)
    paths = []
    for line in result.stdout.splitlines():
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path.replace("\\", "/"))
    return paths


def validate(
    engine_report: dict[str, object] | None = None,
    *,
    write_outputs: bool = True,
) -> list[dict[str, object]]:
    decisions = read_csv(RAW / "OWNER_REVIEW_DECISIONS.csv")
    metrics = read_csv(PROCESSED / "COMMITTEE_METRICS.csv")
    risks = read_csv(PROCESSED / "RISK_MITIGANT_MATRIX.csv")
    conditions = read_csv(PROCESSED / "CONDITIONS_AND_MONITORING.csv")
    ledger = read_csv(DOCS / "SOURCE_LEDGER.csv")
    qa_path = PROCESSED / "DOCUMENT_QA_RESULTS.csv"
    qa = read_csv(qa_path) if qa_path.is_file() else []
    pdfs = pdf_metadata()
    if engine_report is None:
        engine_report = libreoffice_report_on_copy("inspect")
    wb = workbook_metadata()
    consistency = consistency_results()
    if write_outputs:
        write_csv(PROCESSED / "DELIVERABLE_CONSISTENCY_RESULTS.csv", consistency)
    controls: list[dict[str, object]] = []
    def add(category: str, name: str, passed: bool, observed: object, expected: object) -> None:
        controls.append({
            "validation_id": f"P10V-{len(controls)+1:03d}", "category": category,
            "test_name": name, "status": "PASS" if passed else "FAIL",
            "observed": observed, "expected": expected,
        })

    checkpoint = read_csv(RAW / "STARTING_CHECKPOINT.csv")[0]
    add("checkpoint", "approved Phase 9 lineage", approved_lineage(), git_head(), APPROVED_PHASE9_COMMIT)
    add("checkpoint", "recorded starting checkpoint", checkpoint["local_head"] == APPROVED_PHASE9_COMMIT, checkpoint["local_head"], APPROVED_PHASE9_COMMIT)
    add("cutoff", "source ledger cutoff", all(r["cutoff_status"] == "within_cutoff" for r in ledger), sum(r["cutoff_status"] != "within_cutoff" for r in ledger), 0)
    add("lineage", "source hashes current", all(sha256(ROOT / r["source_path"]) == r["sha256"] for r in ledger), "checked", "all match")
    add("governance", "owner-review topics", len(decisions) >= 15, len(decisions), ">=15")
    add("governance", "all 18 Phase 10 decisions owner reviewed", len(decisions) == 18 and all(r["review_status"] == RECOMMENDATION_STATUS for r in decisions), len(decisions), "18 owner_reviewed")
    add("governance", "no provisional decision status remains", not any(r["review_status"] == "provisional_pending_owner_review" for r in decisions), "checked", "none")
    add("recommendation", "conditional approval retained", RECOMMENDATION == "conditional_approval", RECOMMENDATION, "conditional_approval")
    add("recommendation", "fallback explicit", any(r["topic"] == "fallback alternative" and "retain or amend" in r["working_decision"].lower() for r in decisions), "checked", "retain or amend")
    add("recommendation", "missing source not debt funded", any("do not substitute incremental debt" in r["working_decision"] for r in decisions), "checked", "no incremental debt")
    add("data", "committee metric count", len(metrics) >= 130, len(metrics), ">=130")
    add("data", "metric identifiers unique", len({r["metric_id"] for r in metrics}) == len(metrics), len({r["metric_id"] for r in metrics}), len(metrics))
    add("data", "all metric lineage complete", all(r["source_path"] and r["classification"] for r in metrics), "checked", "complete")
    ix = metric_index(metrics)
    anchors = {
        ("lender_base_ebitda", "FY2024"): Decimal("179.358"),
        ("lender_base_ebitda", "FY2025"): Decimal("225.344"),
        ("opening_funded_debt", "selected"): Decimal("727.51671875"),
        ("opening_gross_leverage", "selected"): Decimal("3.228471664433044589605225788"),
        ("base_all_in_liquidity", "selected"): Decimal("263.90228125"),
        ("unsupported_maturity_gap", "BASE"): Decimal("324.77970512014787"),
        ("unsupported_maturity_gap", "MODERATE_UNMITIGATED"): Decimal("408.3752156813583"),
        ("unsupported_maturity_gap", "SEVERE_UNMITIGATED"): Decimal("604.2580066325874"),
        ("common_horizon_total_funded_debt", "existing"): Decimal("495.3682812067100176549274129"),
        ("common_horizon_total_funded_debt", "reference"): Decimal("507.9536592508711071826688285"),
        ("common_horizon_total_funded_debt", "selected"): Decimal("514.753707786180339509466437"),
        ("selected_minus_existing_common_horizon_debt", "2029-07-31"): Decimal("19.3854265794703218545390241"),
        ("maximum_gross_leverage", "MODERATE_UNMITIGATED"): Decimal("4.489250193362221"),
        ("maximum_gross_leverage", "MODERATE_MITIGATED"): Decimal("4.467006108046972"),
    }
    for key, expected in anchors.items():
        actual = dec(ix[key]["value"])
        add("numerical", f"anchor {key[0]} {key[1]}", abs(actual - expected) <= TOLERANCE, actual, expected)
    horizon_required = [r for r in metrics if r["category"] in {"scenario", "scenario_event", "maturity"}]
    add("horizon", "scenario and maturity horizons explicit", all(r["measurement_horizon"] and r["measurement_basis"] for r in horizon_required), sum(not (r["measurement_horizon"] and r["measurement_basis"]) for r in horizon_required), 0)
    memo = (REPORTS / "credit_memo.md").read_text(encoding="utf-8")
    brief = (REPORTS / "committee_brief.md").read_text(encoding="utf-8")
    decision_text = "\n".join([memo, brief, *[r["working_decision"] for r in decisions], *[r["evidence"] + " " + r["credit_consequence"] + " " + r["residual_risk"] for r in risks]]).lower()
    add("repayment", "operating cash is primary repayment", "primary repayment is recurring operating cash" in decision_text, "checked", "present")
    add("repayment", "revolver is liquidity support", "revolver capacity provide timing and liquidity support only" in decision_text or "revolver capacity are timing/liquidity support only" in decision_text, "checked", "present")
    add("repayment", "refinancing not secondary repayment", "refinancing is an unresolved" in decision_text and "refinancing remains secondary" not in decision_text and "refinancing are secondary" not in decision_text, "checked", "present and correctly classified")
    add("repayment", "recovery is secondary backstop", "secondary backstop" in decision_text or "secondary repayment backstops" in decision_text, "checked", "present")
    add("moderate", "moderate breach not cured", "mitigation does not restore" in decision_text and "october 31, 2026" in decision_text, "checked", "present")
    add("moderate", "no automatic waiver", "no automatic waiver" in decision_text, "checked", "present")
    add("comparison", "no faster same-horizon claim", "not justified by faster same-horizon debt reduction" in decision_text and "selected is $19.386m higher" in decision_text, "checked", "corrected")
    add("risk", "risk and mitigant matrix", len(risks) >= 10 and all(r["residual_risk"] for r in risks), len(risks), ">=10 complete")
    categories = {r["category"] for r in conditions}
    add("conditions", "categories remain distinct", categories == {"condition_precedent", "ongoing_covenant", "monitoring_requirement", "analyst_warning", "unresolved_diligence"}, sorted(categories), "five required categories")
    add("conditions", "all requirements remain open", all(r["status"] == "open_not_satisfied_from_public_information" for r in conditions), "checked", "open")
    add("consistency", "all deliverable checks pass", all(r["status"] == "PASS" for r in consistency), sum(r["status"] != "PASS" for r in consistency), 0)
    add("documents", "memo PDF page count", pdfs["credit_memo_pages"] == 11, pdfs["credit_memo_pages"], "11 total: 7 body + 4 appendices")
    add("documents", "brief PDF page count", pdfs["committee_brief_pages"] == 1, pdfs["committee_brief_pages"], 1)
    add("documents", "memo required sections", pdfs["memo_required_sections"], pdfs["memo_required_sections"], True)
    add("documents", "brief required disclaimer", pdfs["brief_disclaimer"], pdfs["brief_disclaimer"], True)
    add("documents", "manual rendered-page QA complete", len(qa) == 12 and all(r["status"] == "PASS" for r in qa), len(qa), "12 PASS rows")
    add("workbook", "14 approved sheets", wb["sheet_count"] == 14, wb["sheet_count"], 14)
    add("workbook", "seven native charts", wb["chart_count"] == 7, wb["chart_count"], 7)
    add("workbook", "formula count preserved", wb["formula_count"] == 2902, wb["formula_count"], 2902)
    add("workbook", "saved Base", wb["saved_scenario"] == "Base", wb["saved_scenario"], "Base")
    add("workbook", "no external links", wb["external_links"] == 0, wb["external_links"], 0)
    add("workbook", "no formula errors", wb["formula_errors"] == 0, wb["formula_errors"], 0)
    add("workbook", "Checks terminal", wb["checks_dependencies"] == 0, wb["checks_dependencies"], 0)
    add("workbook", "LibreOffice opens and inspects", engine_report.get("engine") == "LibreOffice 26.8.0.3", engine_report.get("engine"), "LibreOffice 26.8.0.3")
    add("workbook", "Phase 9 recovery chain", int(engine_report.get("recovery_parity_failures", -1)) == 0, engine_report.get("recovery_parity_failures"), 0)
    add("workbook", "Phase 9 checks", int(engine_report.get("phase9_check_failures", -1)) == 0, engine_report.get("phase9_check_failures"), 0)
    add("workbook", "Credit Summary status", RECOMMENDATION_STATUS in xlsx_cell_text("Credit Summary", "I48"), xlsx_cell_text("Credit Summary", "I48"), RECOMMENDATION_STATUS)
    add("workbook", "moderate breach visible", "4.4893x/4.4670x" in xlsx_cell_text("Credit Summary", "I53"), xlsx_cell_text("Credit Summary", "I53"), "4.4893x/4.4670x")
    add("workbook", "common horizon visible", "$495.368m" in xlsx_cell_text("Credit Summary", "I52") and "$514.754m" in xlsx_cell_text("Credit Summary", "I52"), xlsx_cell_text("Credit Summary", "I52"), "all three common-horizon balances")
    add("workbook", "official recovery N/D", N_D in xlsx_cell_text("Credit Summary", "I55"), xlsx_cell_text("Credit Summary", "I55"), N_D)
    add("scope", "no Phase 12 implementation", not (ROOT / "data" / "phase12").exists() and not (ROOT / "docs" / "phase-12").exists() and not (ROOT / "scripts" / "phase12.py").exists(), "checked", "absent")
    allowed_exact = {
        ".gitattributes", "README.md", "model/Quanex_Credit_Underwriting.xlsx", "scripts/phase4.py", "scripts/phase5.py",
        "scripts/phase6.py", "scripts/phase7.py", "scripts/phase9.py", "scripts/phase10.py", "scripts/build-phase10.mjs",
        "scripts/render-phase10.py", "scripts/phase11.py", "scripts/render-phase11.py", "tests/test_phase10.py", "tests/test_phase11.py",
    }
    paths = changed_paths()
    unexpected = [p for p in paths if p not in allowed_exact and not p.startswith("data/phase10/") and not p.startswith("docs/phase-10/") and not p.startswith("data/phase11/") and not p.startswith("docs/phase-11/") and not p.startswith("reports/")]
    add("repository", "changed paths are Phase 10 scoped", not unexpected, ";".join(unexpected), "none")
    pdf_attribute_result = subprocess.run(
        ["git", "check-attr", "diff", "merge", "text", "--", "reports/credit_memo.pdf", "reports/committee_brief.pdf"],
        cwd=ROOT, text=True, capture_output=True, check=True,
    ).stdout.splitlines()
    expected_pdf_attributes = {
        f"{path}: {attribute}: unset"
        for path in ("reports/credit_memo.pdf", "reports/committee_brief.pdf")
        for attribute in ("diff", "merge", "text")
    }
    add(
        "repository", "PDFs classified as binary by repository attributes",
        set(pdf_attribute_result) == expected_pdf_attributes,
        ";".join(pdf_attribute_result), ";".join(sorted(expected_pdf_attributes)),
    )
    prior = subprocess.run([
        "git", "diff", "--name-only", "--", "data/phase1", "data/phase2", "data/phase3", "data/phase4",
        "data/phase5", "data/phase6", "data/phase7", "data/phase8", "data/phase9", "docs/phase-0",
        "docs/phase-1", "docs/phase-2", "docs/phase-3", "docs/phase-4", "docs/phase-5", "docs/phase-6",
        "docs/phase-7", "docs/phase-8", "docs/phase-9",
    ], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    add("repository", "prior analytical artifacts unchanged", prior == "", prior, "none")
    prohibited = re.compile(r"(?i)(api[_-]?key|secret\s*=|password\s*=|bearer\s+[A-Za-z0-9])")
    text_paths = [ROOT / p for p in paths if (ROOT / p).is_file() and (ROOT / p).suffix.lower() in {".py", ".mjs", ".md", ".csv", ".json", ".ps1"}]
    suspicious = [str(p.relative_to(ROOT)) for p in text_paths if prohibited.search(p.read_text(encoding="utf-8", errors="ignore"))]
    add("repository", "no credential patterns", not suspicious, ";".join(suspicious), "none")
    local_path_pattern = re.compile(
        r"(?i)([A-Z]:\\" + r"Users\\|C:/" + r"Users/|/" + r"home/|file:" + r"//)"
    )
    local_paths = [str(p.relative_to(ROOT)) for p in text_paths if local_path_pattern.search(p.read_text(encoding="utf-8", errors="ignore"))]
    add("repository", "no absolute local paths in outputs", not local_paths, ";".join(local_paths), "none")
    failed = [r for r in controls if r["status"] != "PASS"]
    if write_outputs:
        write_csv(PROCESSED / "VALIDATION_RESULTS.csv", controls)
    if failed:
        raise Phase10Error("Phase 10 validation failed: " + ", ".join(str(r["test_name"]) for r in failed))
    return controls


def visual(preview_dir: Path) -> dict[str, object]:
    preview_dir.mkdir(parents=True, exist_ok=True)
    run_artifact_tool("inspect", MODEL, preview_dir)
    return {"preview_dir": str(preview_dir), "preview_count": len(list(preview_dir.glob("*.png")))}


def all_workflow() -> dict[str, object]:
    payload = build_data()
    build_workbook()
    engine = canonicalize_workbook()
    build_pdfs()
    controls = validate(engine)
    wb = workbook_metadata()
    pdfs = pdf_metadata()
    summary = {
        "owner_decisions": len(payload["decisions"]), "committee_metrics": len(payload["metrics"]),
        "risk_matrix_rows": len(payload["risks"]), "conditions_and_monitoring": len(payload["conditions"]),
        "validation_controls": len(controls), "memo_pages": pdfs["credit_memo_pages"],
        "brief_pages": pdfs["committee_brief_pages"], "formula_count": wb["formula_count"],
        "chart_count": wb["chart_count"], "workbook_sha256": wb["sha256"],
        "normalized_workbook_fingerprint": wb["normalized_fingerprint"],
        "recommendation_status": RECOMMENDATION_STATUS,
    }
    print("Phase 10 complete: " + json.dumps(summary, sort_keys=True))
    return summary


def _test_count(output: str) -> int:
    match = re.search(r"Ran (\d+) tests?", output)
    if not match:
        raise Phase10Error("Unable to read unit-test count from isolated verification output")
    return int(match.group(1))


def verify_isolated() -> dict[str, object]:
    """Run every potentially mutating gate inside a disposable repository clone."""
    preserved = {(ROOT / relative): (ROOT / relative).read_bytes() for relative in repository_paths()}
    validation_outputs: dict[str, str] = {}
    validation_outputs["phase0"] = run_command([
        "powershell", "-ExecutionPolicy", "Bypass", "-NoProfile", "-File",
        str(ROOT / "scripts" / "validate-phase0.ps1"),
    ])
    for phase in range(1, 8):
        validation_outputs[f"phase{phase}"] = run_command([
            sys.executable, "-B", str(ROOT / "scripts" / f"phase{phase}.py"), "validate",
        ])

    # These legacy validation commands intentionally persist calculated workbook
    # state and generated validation CSVs. They run here only because this entire
    # repository is disposable; restore the clone baseline before Phase 10 checks.
    validation_outputs["phase8"] = run_command([
        sys.executable, "-B", str(ROOT / "scripts" / "phase8.py"), "validate",
    ])
    validation_outputs["phase9"] = run_command([
        sys.executable, "-B", str(ROOT / "scripts" / "phase9.py"), "validate",
    ])
    for path, content in preserved.items():
        path.write_bytes(content)

    lo_report = libreoffice_report_on_copy("inspect")
    controls = validate(lo_report, write_outputs=False)
    if any(row["status"] != "PASS" for row in controls):
        raise Phase10Error("Read-only Phase 10 validation failed in isolated workspace")

    excel8 = excel_validation_on_copy("validate-phase8-excel.ps1")
    excel9 = excel_validation_on_copy("validate-phase9-excel.ps1")
    full = run_command([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"])
    focused = run_command([
        sys.executable, "-B", "-m", "unittest", "-v",
        "tests.test_phase8", "tests.test_phase9", "tests.test_phase10",
    ])
    return {
        "phase_validations": {key: value.splitlines()[-1] for key, value in validation_outputs.items()},
        "phase10_controls": len(controls),
        "deliverable_consistency_controls": len(consistency_results()),
        "page_qa_records": len(read_csv(PROCESSED / "DOCUMENT_QA_RESULTS.csv")),
        "libreoffice_status": lo_report.get("engine"),
        "excel_phase8": json.loads(excel8).get("status"),
        "excel_phase9": json.loads(excel9).get("status"),
        "complete_tests": _test_count(full),
        "focused_tests": _test_count(focused),
    }


def verify_commit_time() -> dict[str, object]:
    """Prove commit-time verification leaves the authoritative tree byte-identical."""
    before_manifest = repository_manifest()
    before_status = git_status_snapshot()
    holder, destination = isolated_workspace()
    try:
        isolated_output = run_command([
            sys.executable, "-B", str(destination / "scripts" / "phase10.py"), "verify-isolated",
        ], cwd=destination)
        isolated_summary = json.loads(isolated_output.splitlines()[-1])
    finally:
        holder.cleanup()

    # The final repository-facing checks are read-only. LibreOffice receives a
    # disposable workbook and Phase 10 does not rewrite generated check CSVs.
    engine = libreoffice_report_on_copy("inspect")
    controls = validate(engine, write_outputs=False)
    if any(row["status"] != "PASS" for row in controls):
        raise Phase10Error("Final read-only Phase 10 validation failed")
    after_manifest = repository_manifest()
    after_status = git_status_snapshot()
    if before_manifest != after_manifest:
        changed = sorted(set(before_manifest) | set(after_manifest))
        changed = [p for p in changed if before_manifest.get(p) != after_manifest.get(p)]
        raise Phase10Error("Commit-time verification changed repository files: " + ", ".join(changed))
    if before_status != after_status:
        raise Phase10Error("Commit-time verification changed Git status")
    return {
        "status": "PASS",
        "manifest_files": len(before_manifest),
        "before_manifest_digest": manifest_digest(before_manifest),
        "after_manifest_digest": manifest_digest(after_manifest),
        "git_status_identical": True,
        "phase10_controls": len(controls),
        "isolated": isolated_summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("inputs", "workbook", "pdf", "validate", "visual", "metadata", "verify", "verify-isolated", "all"),
    )
    parser.add_argument("--preview-dir", type=Path)
    args = parser.parse_args()
    if args.command == "inputs":
        payload = build_data(); print(json.dumps({key: len(value) if isinstance(value, list) else 1 for key, value in payload.items()}, indent=2))
    elif args.command == "workbook":
        build_data(); build_workbook(); canonicalize_workbook(); print(json.dumps(workbook_metadata(), indent=2))
    elif args.command == "pdf":
        build_data(); build_pdfs(); print(json.dumps(pdf_metadata(), indent=2))
    elif args.command == "validate":
        rows = validate(); print(f"Phase 10 validation: PASS ({len(rows)} controls)")
    elif args.command == "visual":
        if args.preview_dir is None:
            raise Phase10Error("--preview-dir is required for visual")
        print(json.dumps(visual(args.preview_dir), indent=2))
    elif args.command == "metadata":
        print(json.dumps({"workbook": workbook_metadata(), "pdfs": pdf_metadata()}, indent=2))
    elif args.command == "verify":
        print(json.dumps(verify_commit_time(), sort_keys=True))
    elif args.command == "verify-isolated":
        print(json.dumps(verify_isolated(), sort_keys=True))
    else:
        all_workflow()


if __name__ == "__main__":
    main()
