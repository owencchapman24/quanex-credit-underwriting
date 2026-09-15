"""Build and validate the Phase 8 Excel underwriting model.

The Python layer prepares bounded, approved model inputs and orchestrates the
artifact-tool authoring runtime plus LibreOffice recalculation.  Excel business
logic remains visible in native workbook formulas.
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
from collections import defaultdict
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree as ET

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from workbook_semantics import semantic_workbook_fingerprint
from xlsx_package import canonicalize_xlsx


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "phase8"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
DOCS = ROOT / "docs" / "phase-8"
MODEL = ROOT / "model" / "Quanex_Credit_Underwriting.xlsx"
DYNAMIC_EVIDENCE = PROCESSED / "DYNAMIC_TEST_EVIDENCE.csv"
APPROVED_PHASE7_COMMIT = "58e1b83a644021b785162d851e1539dd65dff9f5"
APPROVED_PHASE8_COMMIT = "b52141dadeb91362cac7cece9b31ec0f3e573534"
NODE = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe"
NODE_MODULES = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "node_modules"
PROGRAM_FILES = Path(os.environ.get("ProgramFiles", "Program Files"))
LIBREOFFICE = Path(shutil.which("soffice.exe") or PROGRAM_FILES / "LibreOffice" / "program" / "soffice.exe")
LO_PYTHON = LIBREOFFICE.with_name("python.exe")
TOLERANCE = Decimal("0.002")

SCENARIOS = (
    ("Base", "BASE"),
    ("Moderate unmitigated", "MODERATE_UNMITIGATED"),
    ("Moderate mitigated", "MODERATE_MITIGATED"),
    ("Severe unmitigated", "SEVERE_UNMITIGATED"),
    ("Severe mitigated", "SEVERE_MITIGATED"),
    ("Moderate Phase 6 analytical shutoff", "MODERATE_NO_WAIVER"),
    ("Severe Phase 6 analytical shutoff", "SEVERE_NO_WAIVER"),
    ("Moderate Phase 7 covenant-linked no-waiver", "MODERATE_PHASE7_COVENANT_NO_WAIVER"),
    ("Severe Phase 7 covenant-linked no-waiver", "SEVERE_PHASE7_COVENANT_NO_WAIVER"),
)

SOURCE_INPUTS = (
    "data/phase2/processed/historical_spread.csv",
    "data/phase2/processed/historical_credit_metrics.csv",
    "data/phase2/processed/adjustment_decisions.csv",
    "data/phase2/processed/earnings_bridges.csv",
    "data/phase4/processed/SOURCES_AND_USES.csv",
    "data/phase4/processed/CONDITIONS_PRECEDENT.csv",
    "data/phase5/processed/QUARTERLY_OPERATING_FORECAST.csv",
    "data/phase6/processed/SCENARIO_RESULTS.csv",
    "data/phase7/processed/FINAL_FINANCING_ASSUMPTIONS.csv",
    "data/phase7/processed/COVENANT_TEST_RESULTS.csv",
    "data/phase7/processed/COVENANT_SUMMARY.csv",
    "data/phase7/processed/COMMON_HORIZON_COMPARISON.csv",
    "data/phase7/processed/ULTIMATE_MATURITY_COMPARISON.csv",
    "data/phase7/raw/STRUCTURE_CANDIDATES.csv",
    "data/phase7/processed/SOURCES_AND_USES_RECONCILIATION.csv",
    "docs/phase-0/EVIDENCE_INVENTORY.csv",
    "docs/phase-7/SOURCE_LEDGER.csv",
)

DYNAMIC_TEST_DEFINITION_VERSION = "P8-DYNAMIC-2.0"
DYNAMIC_TEST_ENGINE = "LibreOffice 26.8.0.3"
DYNAMIC_TESTED_ARTIFACT = "model/Quanex_Credit_Underwriting.xlsx (Phase 8 pre-recalculation disposable test copy)"


def _dynamic_case(
    case_id: str,
    test_name: str,
    stage: str,
    scenario: str,
    input_scope: str,
) -> dict[str, str]:
    return {
        "case_id": case_id,
        "test_name": test_name,
        "stage": stage,
        "scenario": scenario,
        "input_scope": input_scope,
    }


# This is the complete, ordered dynamic-test obligation for Phase 8.  The
# evidence writer accepts exactly these independently identified cases; a
# truncated file cannot pass merely because all surviving rows say PASS.
REQUIRED_DYNAMIC_CASES = (
    _dynamic_case("P8DT-001", "Base period cash and debt identities reconcile", "base_integrity", "Base", "Debt Schedule rows 12:47; cash, term, revolver, debt, and shortfall identities"),
    _dynamic_case("P8DT-002", "Base Forecast and financing Q2 CFADS reconcile", "base_integrity", "Base", "Forecast!D22 and Debt Schedule!I12:I14"),
    _dynamic_case("P8DT-003", "incomplete April 2026 LTM is N/D", "period_completeness", "Base", "Covenants row 9; April 2026 LTM availability"),
    _dynamic_case("P8DT-004", "incomplete July 2026 LTM is N/D", "period_completeness", "Base", "Covenants row 10; July 2026 LTM availability"),
    _dynamic_case("P8DT-005", "first complete EBITDA LTM calculates", "period_completeness", "Base", "Covenants row 11; first complete EBITDA LTM"),
    _dynamic_case("P8DT-006", "first fully complete leverage and coverage test calculates", "period_completeness", "Base", "Covenants row 12; first complete leverage and due-interest coverage"),
    _dynamic_case("P8DT-007", "scenario selector updates EBITDA", "scenario_selection", "Moderate unmitigated", "Assumptions!D4; Scenario Comparison!F5"),
    _dynamic_case("P8DT-008", "severe EBITDA below moderate", "scenario_selection", "Severe unmitigated", "Assumptions!D4; EBITDA ordering"),
    _dynamic_case("P8DT-009", "same debt schedule updates", "scenario_selection", "Severe unmitigated", "Assumptions!D4; Debt Schedule scenario label"),
    _dynamic_case("P8DT-010", "historicals remain fixed", "scenario_selection", "Severe unmitigated", "Historicals!C7:N50 immutability"),
    _dynamic_case("P8DT-011", "Selected severe case period identities reconcile", "scenario_integration", "Severe unmitigated", "Debt Schedule rows 12:47; all financing identities"),
    _dynamic_case("P8DT-012", "Selected severe case Forecast and financing Q2 CFADS reconcile", "scenario_integration", "Severe unmitigated", "Forecast!D22 and Debt Schedule!I12:I14"),
    _dynamic_case("P8DT-013", "amortization changes maturity gap", "financing_input", "Base", "Assumptions!D18 +250bp; Scenario Comparison!X5"),
    _dynamic_case("P8DT-014", "April 2026 amortization changes scheduled payment", "financing_input", "Base", "Assumptions!D18 +250bp; Debt Schedule!K14"),
    _dynamic_case("P8DT-015", "Amortization probe period identities reconcile", "financing_integration", "Base", "Assumptions!D18 +250bp; Debt Schedule rows 12:47"),
    _dynamic_case("P8DT-016", "term amount changes opening term", "financing_input", "Base", "Assumptions!D12 +$5m; Debt Schedule!J12"),
    _dynamic_case("P8DT-017", "Term-size probe period identities reconcile", "financing_integration", "Base", "Assumptions!D12 +$5m; Debt Schedule rows 12:47"),
    _dynamic_case("P8DT-018", "non-debt contribution reduces opening debt", "financing_input", "Base", "Assumptions!D13 +$5m; Transaction!D17"),
    _dynamic_case("P8DT-019", "Contribution probe period identities reconcile", "financing_integration", "Base", "Assumptions!D13 +$5m; Debt Schedule rows 12:47"),
    _dynamic_case("P8DT-020", "interest spread changes cash interest", "financing_input", "Base", "Assumptions!D20 +100bp; Scenario Comparison!J5"),
    _dynamic_case("P8DT-021", "interest spread changes interest due", "financing_input", "Base", "Assumptions!D20 +100bp; Debt Schedule!AE12:AE47"),
    _dynamic_case("P8DT-022", "February 2026 spread probe cash identity reconciles", "financing_integration", "Base", "Assumptions!D20 +100bp; Debt Schedule!AP12"),
    _dynamic_case("P8DT-023", "April 2026 spread probe cash identity reconciles", "financing_integration", "Base", "Assumptions!D20 +100bp; Debt Schedule!AP14"),
    _dynamic_case("P8DT-024", "Spread probe period identities reconcile", "financing_integration", "Base", "Assumptions!D20 +100bp; Debt Schedule rows 12:47"),
    _dynamic_case("P8DT-025", "EBITDA overlay changes EBITDA", "operating_input", "Base", "Assumptions!D21 -10%; Scenario Comparison!F5"),
    _dynamic_case("P8DT-026", "EBITDA overlay flows through financing Q2 CFADS", "operating_integration", "Base", "Assumptions!D21 -10%; Forecast!D22 and Debt Schedule!I12:I14"),
    _dynamic_case("P8DT-027", "EBITDA overlay period identities reconcile", "operating_integration", "Base", "Assumptions!D21 -10%; Debt Schedule rows 12:47"),
    _dynamic_case("P8DT-028", "DSO change reduces CFADS", "operating_input", "Base", "Assumptions!D23 +5 days; Scenario Comparison!I5"),
    _dynamic_case("P8DT-029", "DSO overlay flows through financing Q2 CFADS", "operating_integration", "Base", "Assumptions!D23 +5 days; Forecast!D22 and Debt Schedule!I12:I14"),
    _dynamic_case("P8DT-030", "DSO overlay period identities reconcile", "operating_integration", "Base", "Assumptions!D23 +5 days; Debt Schedule rows 12:47"),
    _dynamic_case("P8DT-031", "Combined rate amortization EBITDA and DSO probe reconciles Q2 CFADS", "combined_integration", "Base", "Assumptions!D18,D20,D21,D23 combined adverse edit; Q2 CFADS"),
    _dynamic_case("P8DT-032", "Combined rate amortization EBITDA and DSO period identities reconcile", "combined_integration", "Base", "Assumptions!D18,D20,D21,D23 combined adverse edit; Debt Schedule rows 12:47"),
    _dynamic_case("P8DT-033", "Combined adverse controls worsen financing outputs", "combined_integration", "Base", "Assumptions!D18,D20,D21,D23; maturity, liquidity, interest"),
    _dynamic_case("P8DT-034", "exact leverage boundary is not breach", "boundary", "Base", "Assumptions!D21; exact 3.50x leverage boundary"),
    _dynamic_case("P8DT-035", "above leverage boundary breaches", "boundary", "Base", "Assumptions!D21; leverage just above 3.50x"),
    _dynamic_case("P8DT-036", "approved coverage and liquidity warning boundaries retained", "boundary", "Base", "Assumptions!D33=3.50x and D34=$75m"),
    _dynamic_case("P8DT-037", "coverage just above warning boundary is compliant", "boundary", "Base", "Covenants!R12; coverage just above warning"),
    _dynamic_case("P8DT-038", "coverage at warning boundary is warning", "boundary", "Base", "Covenants!R12; coverage equals warning"),
    _dynamic_case("P8DT-039", "coverage just below warning boundary is warning", "boundary", "Base", "Covenants!R12; coverage just below warning"),
    _dynamic_case("P8DT-040", "liquidity just above warning boundary is compliant", "boundary", "Base", "Liquidity!R13; liquidity just above warning"),
    _dynamic_case("P8DT-041", "liquidity at warning boundary is warning", "boundary", "Base", "Liquidity!R13; liquidity equals warning"),
    _dynamic_case("P8DT-042", "liquidity just below warning boundary is warning", "boundary", "Base", "Liquidity!R13; liquidity just below warning"),
    _dynamic_case("P8DT-043", "zero EBITDA with complete inputs is N/M", "missing_value", "Base", "Assumptions!D21=-100%; complete covenant period"),
    _dynamic_case("P8DT-044", "negative EBITDA with complete inputs is N/M", "missing_value", "Base", "Assumptions!D21=-200%; complete covenant period"),
    _dynamic_case("P8DT-045", "missing due-or-payable interest is N/D", "missing_value", "Base", "Assumptions!D19 blank; due-interest coverage"),
    _dynamic_case("P8DT-046", "zero due-or-payable interest is N/M", "missing_value", "Base", "Assumptions!D19=0; due-interest coverage"),
    _dynamic_case("P8DT-047", "negative due-or-payable interest is N/M", "missing_value", "Base", "Assumptions!D19=-1%; due-interest coverage"),
    _dynamic_case("P8DT-048", "liquidity overlay can exhaust revolver", "tight_liquidity", "Base", "Assumptions!D25=-$500m; revolver availability"),
    _dynamic_case("P8DT-049", "tight-liquidity case preserves due versus paid shortfalls", "tight_liquidity", "Base", "Assumptions!D25=-$500m; due, paid, and shortfall columns"),
    _dynamic_case("P8DT-050", "Tight-liquidity case period identities reconcile", "tight_liquidity", "Base", "Assumptions!D25=-$500m; Debt Schedule rows 12:47"),
    _dynamic_case("P8DT-051", "covenant-linked draw shutoff is visible", "no_waiver", "Moderate Phase 7 covenant-linked no-waiver", "Assumptions!D4; first draw-shutoff output"),
    _dynamic_case("P8DT-052", "no-waiver shutoff prevents new revolver draws", "no_waiver", "Moderate Phase 7 covenant-linked no-waiver", "Debt Schedule shutoff rows and revolver draws"),
    _dynamic_case("P8DT-053", "No-waiver stress period identities reconcile", "no_waiver", "Moderate Phase 7 covenant-linked no-waiver", "Debt Schedule rows 12:47"),
    _dynamic_case("P8DT-054", "ECF sweep assumption changes sweep", "financing_input", "Base", "Assumptions!D26=0%; Scenario Comparison!L5"),
    _dynamic_case("P8DT-055", "cash-floor safeguard suppresses sweep", "financing_input", "Base", "Assumptions!D24=$400m; Scenario Comparison!L5"),
    _dynamic_case("P8DT-056", "legacy weighted input signature collision is reproduced", "freshness", "Base", "Assumptions!D12 +$5m,D13 -$7.5m,D15 balancing draw; legacy weighted state"),
    _dynamic_case("P8DT-057", "typed input state catches balanced funding collision", "freshness", "Base", "Assumptions!D12 +$5m,D13 -$7.5m,D15 balancing draw; typed live state"),
    _dynamic_case("P8DT-058", "snapshot stale flag activates", "freshness", "Base", "Assumptions!D12 +$1m; Scenario Comparison!AE12"),
    _dynamic_case("P8DT-059", "Base parity restored", "restore", "Base", "all Phase 8 dynamic edits reset; selected outputs"),
    _dynamic_case("P8DT-060", "final scenario restored to Base", "restore", "Base", "Assumptions!D4 final saved state"),
)

DYNAMIC_EVIDENCE_FIELDS = (
    "evidence_id", "case_id", "test_name", "stage", "scenario", "input_scope",
    "status", "observed", "engine", "final_scenario", "test_definition_version",
    "test_definition_sha256", "dynamic_script_sha256", "workbook_builder_sha256",
    "semantic_comparator_sha256",
    "source_input_signature", "tested_artifact", "tested_artifact_sha256",
    "tested_artifact_semantic_fingerprint",
)


class Phase8Error(RuntimeError):
    """Raised when a Phase 8 control fails."""


def run(command: list[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=ROOT, text=True, capture_output=capture, check=check,
    )


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
    if value in (None, "", "N/D", "N/M"):
        return Decimal("0")
    return Decimal(str(value))


def fmt(value: Decimal | object) -> str:
    if not isinstance(value, Decimal):
        value = dec(value)
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str:
    return run(["git", "rev-parse", "HEAD"]).stdout.strip()


def source_signature() -> str:
    digest = hashlib.sha256()
    for relative in SOURCE_INPUTS:
        path = ROOT / relative
        digest.update(relative.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def load_phase7():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("phase7_for_phase8", ROOT / "scripts" / "phase7.py")
    if spec is None or spec.loader is None:
        raise Phase8Error("Unable to load the approved Phase 7 model")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def aggregate_period(rows: list[dict[str, str]], period_id: str, frequency: str) -> dict[str, object]:
    first, last = rows[0], rows[-1]
    flow_fields = (
        "revenue", "lender_base_ebitda", "cash_tax_proxy", "working_capital_cash_flow",
        "capital_expenditures", "other_operating_cash_uses", "cfads_before_cash_interest",
        "cash_interest_due", "cash_interest_paid", "cash_interest_shortfall",
        "scheduled_term_principal_due", "scheduled_term_principal_paid", "scheduled_principal_shortfall",
        "retained_obligation_due", "retained_obligation_paid", "retained_obligation_shortfall",
        "dividend_paid", "repurchase_paid", "dividend_unpaid", "repurchase_unpaid",
        "revolver_draw", "revolver_repayment", "cash_sweep", "failed_obligation_unpaid_amount",
        "maturity_principal_due", "maturity_principal_paid", "maturity_principal_shortfall",
    )
    output: dict[str, object] = {
        "model_period_id": period_id,
        "frequency": frequency,
        "period_start": first["month_start"],
        "period_end": last["month_end"],
        "fiscal_year": last["fiscal_year"],
        "quarter": last["quarter"],
        "days_in_period": (date.fromisoformat(last["month_end"]) - date.fromisoformat(first["month_start"])).days + 1,
        "opening_cash": first["opening_cash"],
        "opening_term_principal": first["opening_term_principal"],
        "ending_term_principal": last["ending_term_principal"],
        "opening_revolver": first["opening_revolver"],
        "ending_revolver": last["ending_revolver"],
        "ending_cash": last["ending_cash"],
        "minimum_usable_liquidity": fmt(min(dec(row["usable_liquidity"]) for row in rows)),
        "peak_revolver": fmt(max(dec(row["ending_revolver"]) for row in rows)),
        "nominal_revolver_availability": last["nominal_revolver_availability"],
        "usable_revolver_availability": last["usable_revolver_availability"],
        "operating_cash_floor": last["operating_cash_floor"],
        "letters_of_credit": last["letters_of_credit"],
        "revolver_commitment": last["revolver_commitment"],
        "drawability_status": last["drawability_status"],
        "drawability_shutoff_date": next((row["drawability_shutoff_date"] for row in rows if row["drawability_shutoff_date"]), ""),
        "commitment_exhaustion_flag": "yes" if any(row["commitment_exhaustion_flag"] == "yes" for row in rows) else "no",
        "cash_floor_shortfall": fmt(max(dec(row["cash_floor_shortfall"]) for row in rows)),
        "ttm_lender_base_ebitda": last["ttm_lender_base_ebitda"],
        "gross_funded_leverage": last["gross_funded_leverage"],
        "ebitda_cash_interest_coverage": last["ebitda_cash_interest_coverage"],
        "unsupported_maturity_gap": last["unsupported_maturity_gap"],
        "maturity_event": "yes" if any(row["maturity_event"] == "yes" for row in rows) else "no",
        "mandatory_payment_failure_flag": "yes" if any(row["mandatory_payment_failure_flag"] == "yes" for row in rows) else "no",
        "model_status": last["model_status"],
        "source_ids": last["source_ids"],
        "upstream_ids": f"{first['monthly_stress_id']}:{last['monthly_stress_id']}",
    }
    for field in flow_fields:
        output[field] = fmt(sum((dec(row[field]) for row in rows), Decimal("0")))
    output["gross_funded_debt"] = fmt(dec(last["ending_term_principal"]) + dec(last["ending_revolver"]) + Decimal("62.619"))
    return output


def build_period_inputs() -> list[dict[str, object]]:
    phase7 = load_phase7()
    _, selected_monthly, _ = phase7.build_structure_comparison(phase7.candidate_definitions())
    base_operating = read_csv(ROOT / "data" / "phase5" / "processed" / "QUARTERLY_OPERATING_FORECAST.csv")
    base_by_quarter = {(row["fiscal_year"], row["quarter"]): row for row in base_operating}
    output: list[dict[str, object]] = []
    for scenario_name, scenario_id in SCENARIOS:
        monthly = selected_monthly[scenario_id]
        groups: list[list[dict[str, str]]] = [[row] for row in monthly[:24]]
        quarterly: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        order: list[tuple[str, str]] = []
        for row in monthly[24:]:
            key = (row["fiscal_year"], row["quarter"])
            if key not in quarterly:
                order.append(key)
            quarterly[key].append(row)
        groups.extend(quarterly[key] for key in order)
        if len(groups) != 36:
            raise Phase8Error(f"Expected 36 model periods for {scenario_id}, found {len(groups)}")
        for index, group in enumerate(groups, start=1):
            row = aggregate_period(group, f"P{index:03d}", "monthly" if index <= 24 else "quarterly")
            row["scenario_name"] = scenario_name
            row["scenario_id"] = scenario_id
            base = base_by_quarter.get((str(row["fiscal_year"]), str(row["quarter"])), {})
            row["base_gross_margin_percent"] = base.get("gross_margin_percent", "")
            row["depreciation_and_amortization"] = fmt(
                dec(base.get("depreciation_and_amortization", "0")) / (Decimal("3") if index <= 24 else Decimal("1"))
            )
            output.append(row)
    fields = [
        "scenario_name", "scenario_id", "model_period_id", "frequency", "period_start", "period_end",
        "fiscal_year", "quarter", "days_in_period", "revenue", "base_gross_margin_percent",
        "lender_base_ebitda", "depreciation_and_amortization", "cash_tax_proxy",
        "working_capital_cash_flow", "capital_expenditures", "other_operating_cash_uses",
        "cfads_before_cash_interest", "opening_cash", "ending_cash", "opening_term_principal",
        "scheduled_term_principal_due", "scheduled_term_principal_paid", "scheduled_principal_shortfall",
        "cash_sweep", "maturity_principal_due", "maturity_principal_paid", "maturity_principal_shortfall",
        "ending_term_principal", "opening_revolver", "revolver_draw", "revolver_repayment", "ending_revolver",
        "cash_interest_due", "cash_interest_paid", "cash_interest_shortfall", "retained_obligation_due",
        "retained_obligation_paid", "retained_obligation_shortfall", "dividend_paid", "repurchase_paid",
        "dividend_unpaid", "repurchase_unpaid", "failed_obligation_unpaid_amount", "gross_funded_debt",
        "minimum_usable_liquidity", "peak_revolver", "nominal_revolver_availability",
        "usable_revolver_availability", "operating_cash_floor", "letters_of_credit", "revolver_commitment",
        "drawability_status", "drawability_shutoff_date", "commitment_exhaustion_flag", "cash_floor_shortfall",
        "ttm_lender_base_ebitda", "gross_funded_leverage", "ebitda_cash_interest_coverage",
        "unsupported_maturity_gap", "maturity_event", "mandatory_payment_failure_flag", "model_status",
        "source_ids", "upstream_ids",
    ]
    write_csv(RAW / "MODEL_PERIOD_INPUTS.csv", output, fields)
    return output


def build_opening_debt_comparison() -> list[dict[str, object]]:
    """Keep the October actual reference separate from January alternatives."""
    phase7 = load_phase7()
    candidates = {
        row["candidate_id"]: row
        for row in phase7.structure_candidate_rows(phase7.candidate_definitions())
    }
    actual_total = Decimal("703.869")
    actual_other = Decimal("62.619")
    rows: list[dict[str, object]] = [{
        "comparison_id": "P8DC-001", "comparison_group": "historical_reference",
        "alternative": "Existing actual", "comparison_date": "2025-10-31",
        "bank_debt": fmt(actual_total - actual_other), "other_funded_debt": fmt(actual_other),
        "total_funded_debt": fmt(actual_total), "classification": "reported_historical_reference",
        "source_ids": "SRC-001;SRC-002", "status": "historical_reference_only",
        "limitations": "Historical reference point; not compared directly with projected January 31, 2026 alternatives.",
    }]
    for sequence, candidate_id, label in (
        (2, "STR-001", "Retain existing facilities"),
        (3, "STR-008", "Selected $635m refinancing"),
        (4, "STR-003", "$650m reference refinancing"),
    ):
        source = candidates[candidate_id]
        rows.append({
            "comparison_id": f"P8DC-{sequence:03d}", "comparison_group": "projected_closing_alternatives",
            "alternative": label, "comparison_date": "2026-01-31",
            "bank_debt": source["opening_bank_debt"],
            "other_funded_debt": source["retained_other_funded_debt"],
            "total_funded_debt": source["opening_gross_funded_debt"],
            "classification": "phase7_projected_closing_calculation",
            "source_ids": source["source_ids"], "status": "same_date_projected_alternative",
            "limitations": source["limitations"],
        })
    write_csv(PROCESSED / "OPENING_DEBT_COMPARISON.csv", rows)
    return rows


def build_term_sizing_sensitivity() -> list[dict[str, object]]:
    """Select existing Phase 7 pairings; never hold a closing source constant."""
    phase7_rows = {
        row["candidate_id"]: row
        for row in read_csv(ROOT / "data" / "phase7" / "processed" / "SOURCES_AND_USES_RECONCILIATION.csv")
    }
    rows: list[dict[str, object]] = []
    for candidate_id in ("STR-007", "STR-008", "STR-010", "STR-003"):
        source = phase7_rows[candidate_id]
        difference = dec(source["sources_less_uses"])
        non_debt = dec(source["required_non_debt_contribution"])
        if abs(difference) > TOLERANCE:
            case_status = "unbalanced_diagnostic"
        elif candidate_id == "STR-008":
            case_status = "conditional_selected"
        elif non_debt > 0:
            case_status = "conditional"
        else:
            case_status = "feasible_reference"
        rows.append({
            "sensitivity_id": f"P8TS-{len(rows)+1:03d}", "candidate_id": candidate_id,
            "candidate_name": source["candidate_name"],
            "term_amount": source["initial_term_funding"], "opening_revolver": source["opening_revolver"],
            "non_debt_source": source["required_non_debt_contribution"],
            "total_sources": source["total_sources"], "total_uses": source["reference_closing_uses"],
            "sources_less_uses": source["sources_less_uses"],
            "projected_closing_funded_debt": source["opening_total_funded_debt"],
            "opening_leverage": source["closing_gross_leverage"], "case_status": case_status,
            "source_ids": source["source_ids"], "upstream_ids": source["reconciliation_id"],
            "limitations": source["limitations"],
        })
    write_csv(PROCESSED / "TERM_SIZING_SENSITIVITY.csv", rows)
    return rows


def build_amortization_sensitivity() -> list[dict[str, object]]:
    """Rerun the selected structure through the Phase 7 integrated debt engine."""
    phase7 = load_phase7()
    selected = next(item for item in phase7.candidate_definitions() if item.candidate_id == "STR-008")
    rows: list[dict[str, object]] = []
    for amortization in map(Decimal, ("5", "7.5", "10", "15")):
        candidate = replace(
            selected,
            candidate_id=f"P8AS-{len(rows)+1:03d}",
            name=f"$635m selected structure / {fmt(amortization)}% amortization",
            amortization_percent=amortization,
        )
        monthly, summary = phase7.model_candidate(candidate, "BASE")
        operating_rows = [row for row in monthly if row["maturity_event"] != "yes"]
        if not operating_rows:
            raise Phase8Error(f"Integrated amortization path is empty: {amortization}")
        average_bank_debt = sum((
            dec(row["opening_term_principal"]) + dec(row["opening_revolver"])
            + dec(row["ending_term_principal"]) + dec(row["ending_revolver"])
        ) / Decimal("2") for row in operating_rows) / Decimal(len(operating_rows))
        liquidity = phase7.liquidity_presentation(candidate, monthly)
        common = phase7.build_common_horizon_comparison(
            (candidate,), {(candidate.candidate_id, "BASE"): monthly},
        )[0]
        maturity = phase7.build_ultimate_maturity_comparison(
            (candidate,), {(candidate.candidate_id, "BASE"): monthly},
        )[0]
        covenant_tests, _ = phase7.build_covenant_tests({"BASE": monthly})
        complete_tests = [row for row in covenant_tests if row["input_completeness_status"] == "complete"]
        if not complete_tests:
            raise Phase8Error(f"No complete covenant tests for amortization {amortization}")
        leverage_tests = [
            row for row in covenant_tests
            if row["gross_funded_leverage"] not in {
                "", phase7.N_D_VALUE, phase7.N_M, phase7.N_D,
            }
        ]
        if not leverage_tests:
            raise Phase8Error(f"No determinable leverage tests for amortization {amortization}")
        first_warning = next((
            row["period_end"] for row in covenant_tests
            if row["overall_warning_status"] in {"warning", "breached"}
        ), "")
        first_breach = next((
            row["period_end"] for row in covenant_tests
            if row["overall_covenant_status"] == "breached"
        ), "")
        rows.append({
            "sensitivity_id": candidate.candidate_id,
            "annual_amortization_percent": fmt(amortization),
            "cumulative_scheduled_principal": fmt(summary["scheduled_principal_paid"]),
            "average_modeled_bank_debt": fmt(average_bank_debt),
            "cumulative_cash_interest": fmt(summary["cumulative_cash_interest"]),
            "peak_revolver": fmt(summary["peak_revolver_including_opening"]),
            "minimum_operating_cash": fmt(min(dec(row["ending_cash"]) for row in operating_rows)),
            "minimum_usable_liquidity": liquidity["all_in_minimum_usable_liquidity"],
            "cumulative_ecf_sweep": fmt(summary["cash_sweep"]),
            "ending_bank_debt": fmt(summary["ending_bank_debt"]),
            "common_horizon_total_funded_debt": common["ending_total_funded_debt"],
            "unsupported_maturity_gap": maturity["unsupported_maturity_gap"],
            # Match the owner-reviewed Phase 7 covenant-summary convention: a
            # determinable leverage test remains usable even where a separate
            # coverage input leaves the combined test row incomplete.
            "maximum_quarterly_test_leverage": fmt(max(dec(row["gross_funded_leverage"]) for row in leverage_tests)),
            "minimum_complete_ltm_coverage": fmt(min(dec(row["interest_coverage"]) for row in complete_tests)),
            "first_warning_date": first_warning or "none",
            "first_breach_date": first_breach or "none",
            "path_status": summary["status"],
            "source_ids": "SRC-001;SRC-002;SRC-003",
            "upstream_ids": f"STR-008;BASE;Phase7 integrated engine;{fmt(amortization)}%",
            "limitations": "Base operating case and selected closing structure held constant. The Phase 7 cash, revolver, interest, sweep, liquidity, covenant, and maturity engine is rerun; no refinancing proceeds are assumed.",
        })
    write_csv(PROCESSED / "AMORTIZATION_SENSITIVITY_RESULTS.csv", rows)
    return rows


def build_model_support_inputs() -> dict[str, int]:
    return {
        "opening_debt_rows": len(build_opening_debt_comparison()),
        "term_sizing_rows": len(build_term_sizing_sensitivity()),
        "amortization_rows": len(build_amortization_sensitivity()),
    }


def build_starting_checkpoint() -> None:
    write_csv(RAW / "STARTING_CHECKPOINT.csv", [{
        "repository": "owencchapman24/quanex-credit-underwriting",
        "branch": "main", "approved_phase7_commit": APPROVED_PHASE7_COMMIT,
        "approved_phase8_commit": APPROVED_PHASE8_COMMIT,
        # Record the approved Phase 8 lineage boundary rather than the later
        # release/temporary-overlay commit that invoked deterministic rebuild.
        "local_head": APPROVED_PHASE8_COMMIT, "source_input_signature": source_signature(),
        "information_cutoff": "2025-12-15", "hypothetical_closing": "2026-01-31",
        "calculation_engine": "LibreOffice 26.8.0.3",
    }])


def run_artifact_tool(mode: str, preview_dir: Path | None = None) -> None:
    if not NODE.is_file() or not NODE_MODULES.is_dir():
        raise Phase8Error("Bundled artifact-tool Node runtime is unavailable")
    with tempfile.TemporaryDirectory(prefix="quanex-phase8-artifact-") as temp_name:
        temp = Path(temp_name)
        shutil.copy2(ROOT / "scripts" / "build-phase8.mjs", temp / "build-phase8.mjs")
        junction = temp / "node_modules"
        command = (
            f"New-Item -ItemType Junction -Path '{junction}' "
            f"-Target '{NODE_MODULES}' | Out-Null"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", command], check=True)
        args = [str(NODE), str(temp / "build-phase8.mjs"), mode, str(ROOT)]
        if preview_dir is not None:
            args.append(str(preview_dir))
        result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        if result.returncode:
            raise Phase8Error(f"Artifact-tool {mode} failed with exit code {result.returncode}")
        inspect_sidecar = MODEL.with_name(MODEL.name + ".inspect.ndjson")
        if inspect_sidecar.exists():
            inspect_sidecar.unlink()


def run_libreoffice(mode: str, workbook: Path = MODEL, report: Path | None = None) -> dict[str, object]:
    if not LIBREOFFICE.is_file() or not LO_PYTHON.is_file():
        raise Phase8Error("LibreOffice recalculation engine is unavailable")
    temporary_report = report is None
    if report is None:
        descriptor, report_name = tempfile.mkstemp(prefix="phase8-lo-", suffix=".json")
        os.close(descriptor)
        report = Path(report_name)
    command = [str(LO_PYTHON), str(ROOT / "scripts" / "recalculate-phase8.py"), mode, str(workbook), str(report)]
    try:
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        if result.returncode:
            raise Phase8Error(f"LibreOffice {mode} failed with exit code {result.returncode}")
        canonicalize_xlsx(workbook)
        return json.loads(report.read_text(encoding="utf-8"))
    finally:
        if temporary_report:
            report.unlink(missing_ok=True)


def write_capture_results(report: dict[str, object]) -> None:
    rows = report.get("captures", [])
    if not isinstance(rows, list) or len(rows) != len(SCENARIOS):
        raise Phase8Error("Scenario capture report is incomplete")
    write_csv(PROCESSED / "SCENARIO_CAPTURE_RESULTS.csv", rows)


def workbook_xml() -> tuple[zipfile.ZipFile, ET.Element]:
    archive = zipfile.ZipFile(MODEL)
    return archive, ET.fromstring(archive.read("xl/workbook.xml"))


def workbook_structure() -> dict[str, object]:
    archive, root = workbook_xml()
    ns = {
        "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "p": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {node.attrib["Id"]: node.attrib["Target"] for node in relationships.findall("p:Relationship", ns)}
    sheet_paths: dict[str, str] = {}
    for node in root.findall("m:sheets/m:sheet", ns):
        target = targets[node.attrib[f"{{{ns['r']}}}id"]].lstrip("/")
        sheet_paths[node.attrib["name"]] = target if target.startswith("xl/") else f"xl/{target}"
    sheets = list(sheet_paths)
    formula_count = 0
    formula_counts_by_sheet: dict[str, int] = {}
    checks_dependencies = []
    formula_errors = []
    excel_formula_issues: list[dict[str, str]] = []
    range_only_array = re.compile(
        r"\b(?:COUNTIF|COUNTIFS|SUMIF|SUMIFS|AVERAGEIF|AVERAGEIFS)\s*\(\s*\{",
        re.IGNORECASE,
    )
    for sheet, name in sheet_paths.items():
        text = archive.read(name).decode("utf-8")
        xml = ET.fromstring(text)
        formulas = xml.findall(".//m:f", ns)
        formula_counts_by_sheet[sheet] = len(formulas)
        formula_count += len(formulas)
        if sheet != "Checks" and ("Checks!" in text or "&apos;Checks&apos;!" in text):
            checks_dependencies.append(name)
        for cell in xml.findall(".//m:c", ns):
            formula_node = cell.find("m:f", ns)
            if formula_node is None:
                continue
            formula = formula_node.text or ""
            if formula.startswith("="):
                excel_formula_issues.append({
                    "sheet": sheet, "cell": cell.attrib.get("r", ""),
                    "rule": "OOXML formula text must omit the leading equals sign", "formula": formula,
                })
            if range_only_array.search(formula):
                excel_formula_issues.append({
                    "sheet": sheet, "cell": cell.attrib.get("r", ""),
                    "rule": "Excel range-only criteria function cannot use an inline array constant as its range argument",
                    "formula": formula,
                })
            if re.search(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", formula):
                excel_formula_issues.append({
                    "sheet": sheet, "cell": cell.attrib.get("r", ""),
                    "rule": "formula contains an XML-disallowed control character", "formula": formula,
                })
        for token in ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#NUM!", "#NULL!", "#SPILL!", "#CALC!"):
            if token in text:
                formula_errors.append(f"{name}:{token}")
    external_links = [name for name in archive.namelist() if name.startswith("xl/externalLinks/")]
    charts = [name for name in archive.namelist() if name.startswith("xl/charts/chart") and name.endswith(".xml")]
    calc = root.find("m:calcPr", ns)
    calculation_mode = calc.attrib.get("calcMode", "") if calc is not None else ""
    full_calc = calc.attrib.get("fullCalcOnLoad", "") if calc is not None else ""
    archive.close()
    return {
        "sheets": sheets, "sheet_paths": sheet_paths, "formula_count": formula_count,
        "formula_counts_by_sheet": formula_counts_by_sheet,
        "excel_formula_compatibility_issues": excel_formula_issues,
        "checks_dependencies": checks_dependencies,
        "formula_errors": formula_errors, "external_links": external_links, "chart_count": len(charts),
        "calculation_mode": calculation_mode, "full_calc_on_load": full_calc,
    }


def dynamic_test_definition_sha256() -> str:
    serialized = json.dumps(
        {"version": DYNAMIC_TEST_DEFINITION_VERSION, "cases": REQUIRED_DYNAMIC_CASES},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def dynamic_runtime_metadata(
    *,
    artifact_sha256: str,
    artifact_fingerprint: str,
    tested_artifact: str | None = None,
) -> dict[str, str]:
    return {
        "engine": DYNAMIC_TEST_ENGINE,
        "final_scenario": "Base",
        "test_definition_version": DYNAMIC_TEST_DEFINITION_VERSION,
        "test_definition_sha256": dynamic_test_definition_sha256(),
        "dynamic_script_sha256": sha256(ROOT / "scripts" / "recalculate-phase8.py"),
        "workbook_builder_sha256": sha256(ROOT / "scripts" / "build-phase8.mjs"),
        "semantic_comparator_sha256": sha256(ROOT / "scripts" / "workbook_semantics.py"),
        "source_input_signature": source_signature(),
        "tested_artifact": tested_artifact or DYNAMIC_TESTED_ARTIFACT,
        "tested_artifact_sha256": artifact_sha256,
        "tested_artifact_semantic_fingerprint": artifact_fingerprint,
    }


def dynamic_evidence_artifact_identity(
    evidence_path: Path | None = None,
) -> tuple[str, str] | None:
    """Return the single tested artifact identity, if evidence is coherent."""
    evidence_path = DYNAMIC_EVIDENCE if evidence_path is None else evidence_path
    if not evidence_path.is_file():
        return None
    rows = read_csv(evidence_path)
    shas = {row.get("tested_artifact_sha256", "") for row in rows}
    fingerprints = {row.get("tested_artifact_semantic_fingerprint", "") for row in rows}
    if len(shas) != 1 or len(fingerprints) != 1:
        return None
    artifact_sha, artifact_fingerprint = next(iter(shas)), next(iter(fingerprints))
    if not re.fullmatch(r"[0-9a-f]{64}", artifact_sha) or not re.fullmatch(r"[0-9a-f]{64}", artifact_fingerprint):
        return None
    return artifact_sha, artifact_fingerprint


def dynamic_evidence_state(
    evidence_path: Path | None = None,
    *,
    tested_artifact: str | None = None,
) -> tuple[str, str]:
    custom_evidence = evidence_path is not None
    evidence_path = DYNAMIC_EVIDENCE if evidence_path is None else evidence_path
    if not evidence_path.is_file():
        return "NOT_RUN", "dynamic evidence file absent"
    rows = read_csv(evidence_path)
    if not rows:
        return "NOT_RUN", "dynamic evidence file empty"

    if any(set(row) != set(DYNAMIC_EVIDENCE_FIELDS) for row in rows):
        return "FAIL", "dynamic evidence schema is incomplete or unexpected"
    blank_fields = [
        field for field in DYNAMIC_EVIDENCE_FIELDS
        if any(not row.get(field, "").strip() for row in rows)
    ]
    if blank_fields:
        return "FAIL", "dynamic evidence metadata is blank: " + ", ".join(blank_fields)

    expected_by_name = {case["test_name"]: case for case in REQUIRED_DYNAMIC_CASES}
    names = [row["test_name"] for row in rows]
    case_ids = [row["case_id"] for row in rows]
    evidence_ids = [row["evidence_id"] for row in rows]
    if len(names) != len(set(names)) or len(case_ids) != len(set(case_ids)) or len(evidence_ids) != len(set(evidence_ids)):
        return "FAIL", "dynamic evidence contains duplicate test names, case IDs, or evidence IDs"
    if set(names) != set(expected_by_name) or len(rows) != len(REQUIRED_DYNAMIC_CASES):
        missing = sorted(set(expected_by_name) - set(names))
        extra = sorted(set(names) - set(expected_by_name))
        return "FAIL", f"dynamic evidence case set mismatch; missing={missing}; extra={extra}"

    expected_evidence_ids = {
        case["test_name"]: f"P8DE-{index:03d}"
        for index, case in enumerate(REQUIRED_DYNAMIC_CASES, 1)
    }
    for row in rows:
        case = expected_by_name[row["test_name"]]
        for field in ("case_id", "stage", "scenario", "input_scope"):
            if row[field] != case[field]:
                return "FAIL", f"dynamic evidence {field} mismatch for {row['test_name']}"
        if row["evidence_id"] != expected_evidence_ids[row["test_name"]]:
            return "FAIL", f"dynamic evidence ID mismatch for {row['test_name']}"

    identity = dynamic_evidence_artifact_identity(evidence_path)
    if identity is None:
        return "FAIL", "dynamic evidence tested-artifact identity is missing or inconsistent"
    artifact_sha, artifact_fingerprint = identity
    expected_metadata = dynamic_runtime_metadata(
        artifact_sha256=artifact_sha,
        artifact_fingerprint=artifact_fingerprint,
        tested_artifact=tested_artifact,
    )
    for field, expected in expected_metadata.items():
        if any(row[field] != expected for row in rows):
            return "FAIL", f"dynamic evidence does not match current {field}"

    # The Phase 8 evidence can be validated either while its artifact is still
    # the current workbook or after Phase 9 has recorded that exact artifact as
    # its pre-overlay baseline.  A later-stage workbook is not compared to the
    # earlier artifact as though the two were the same file.
    current_match = sha256(MODEL) == artifact_sha
    if current_match and normalized_fingerprint() != artifact_fingerprint:
        return "FAIL", "dynamic evidence semantic fingerprint does not match its tested artifact"
    if not current_match:
        if custom_evidence:
            return "FAIL", "custom dynamic evidence does not identify the current workbook artifact"
        baseline_path = ROOT / "data" / "phase9" / "processed" / "PHASE8_BASELINE_VERIFICATION.csv"
        if not baseline_path.is_file():
            return "FAIL", "tested Phase 8 artifact is no longer current and no pre-overlay identity record exists"
        baseline_rows = read_csv(baseline_path)
        if len(baseline_rows) != 1:
            return "FAIL", "Phase 8 pre-overlay identity record is not unique"
        baseline = baseline_rows[0]
        if (
            baseline.get("status") != "PASS"
            or baseline.get("tested_artifact_sha256") != artifact_sha
            or baseline.get("observed_normalized_fingerprint") != artifact_fingerprint
        ):
            return "FAIL", "dynamic evidence does not match the recorded Phase 8 pre-overlay artifact"

    statuses = {row["status"] for row in rows}
    if "FAIL" in statuses:
        return "FAIL", "one or more dynamic tests failed"
    if statuses.intersection({"NOT_RUN", "NOT RUN"}):
        return "NOT_RUN", "one or more required dynamic tests were not run"
    if statuses != {"PASS"}:
        return "FAIL", "dynamic evidence contains an unsupported or incomplete status"
    return "PASS", (
        f"{len(rows)} required dynamic cases passed under "
        f"{DYNAMIC_TEST_DEFINITION_VERSION}"
    )


def write_dynamic_evidence(
    report: dict[str, object],
    evidence_path: Path | None = None,
    *,
    tested_artifact: str | None = None,
) -> list[dict[str, object]]:
    evidence_path = DYNAMIC_EVIDENCE if evidence_path is None else evidence_path
    tests = report.get("tests", [])
    if report.get("dynamic_status") != "PASS" or not isinstance(tests, list) or not tests:
        evidence_path.unlink(missing_ok=True)
        return []

    names = [str(item.get("test", "")) for item in tests if isinstance(item, dict)]
    if len(names) != len(tests) or len(names) != len(set(names)):
        evidence_path.unlink(missing_ok=True)
        raise Phase8Error("Dynamic report contains duplicate or malformed test records")
    required_by_name = {case["test_name"]: case for case in REQUIRED_DYNAMIC_CASES}
    if set(names) != set(required_by_name) or len(tests) != len(REQUIRED_DYNAMIC_CASES):
        evidence_path.unlink(missing_ok=True)
        missing = sorted(set(required_by_name) - set(names))
        extra = sorted(set(names) - set(required_by_name))
        raise Phase8Error(f"Dynamic report case set mismatch; missing={missing}; extra={extra}")
    if any(str(item.get("status", "")) != "PASS" for item in tests):
        evidence_path.unlink(missing_ok=True)
        raise Phase8Error("Dynamic report includes a required test that did not PASS")
    if any("observed" not in item for item in tests):
        evidence_path.unlink(missing_ok=True)
        raise Phase8Error("Dynamic report omits observed evidence for a required test")

    current_sha = sha256(MODEL)
    current_fingerprint = normalized_fingerprint()
    metadata = dynamic_runtime_metadata(
        artifact_sha256=current_sha,
        artifact_fingerprint=current_fingerprint,
        tested_artifact=tested_artifact,
    )
    for field in (
        "engine", "final_scenario", "tested_artifact", "tested_artifact_sha256",
        "tested_artifact_semantic_fingerprint",
    ):
        if str(report.get(field, "")) != metadata[field]:
            evidence_path.unlink(missing_ok=True)
            raise Phase8Error(f"Dynamic report {field} does not identify the current tested artifact")

    observed_by_name = {str(item["test"]): item.get("observed") for item in tests}
    rows: list[dict[str, object]] = []
    for index, case in enumerate(REQUIRED_DYNAMIC_CASES, 1):
        rows.append({
            "evidence_id": f"P8DE-{index:03d}",
            **case,
            "status": "PASS",
            "observed": json.dumps(observed_by_name[case["test_name"]], sort_keys=True, separators=(",", ":")),
            **metadata,
        })
    write_csv(evidence_path, rows, list(DYNAMIC_EVIDENCE_FIELDS))
    return rows


def validate_workbook(
    engine_report: dict[str, object] | None = None,
    *,
    require_dynamic: bool = True,
    write_outputs: bool = True,
) -> list[dict[str, object]]:
    required = [
        "Credit Summary", "Assumptions", "Scenario Comparison", "Historicals", "Credit Adjustments",
        "Transaction", "Forecast", "Debt Schedule", "Liquidity", "Covenants", "Recovery",
        "Sensitivities", "Sources", "Checks",
    ]
    structure = workbook_structure()
    if engine_report is None:
        # LibreOffice persists calculation caches and ZIP metadata during an
        # inspect pass. Validation therefore opens only a disposable copy.
        with tempfile.TemporaryDirectory(prefix="quanex-phase8-validate-") as temp_name:
            workbook_copy = Path(temp_name) / MODEL.name
            shutil.copy2(MODEL, workbook_copy)
            engine_report = run_libreoffice("inspect", workbook_copy)
    controls: list[dict[str, object]] = []

    def add(name: str, passed: bool, observed: object, expected: object, category: str = "workbook") -> None:
        controls.append({
            "validation_id": f"P8V-{len(controls)+1:03d}", "category": category, "test_name": name,
            "status": "PASS" if passed else "FAIL", "observed": observed, "expected": expected,
        })

    add("required sheet order", structure["sheets"] == required, " | ".join(structure["sheets"]), " | ".join(required))
    add("sheet14 maps to Checks", structure["sheet_paths"].get("Checks") == "xl/worksheets/sheet14.xml", structure["sheet_paths"].get("Checks"), "xl/worksheets/sheet14.xml")
    phase9_present = (ROOT / "data" / "phase9").exists()
    formula_ok = int(structure["formula_count"]) >= 2742 if phase9_present else int(structure["formula_count"]) == 2742
    add("native cell formula count", formula_ok, structure["formula_count"], ">=2742 with Phase 9" if phase9_present else 2742)
    add("Excel-compatible formula serialization", not structure["excel_formula_compatibility_issues"], len(structure["excel_formula_compatibility_issues"]), 0)
    add("no external workbook links", not structure["external_links"], len(structure["external_links"]), 0)
    add("Checks is terminal", not structure["checks_dependencies"], len(structure["checks_dependencies"]), 0)
    add("no cached formula errors", not structure["formula_errors"], len(structure["formula_errors"]), 0)
    add("native charts", int(structure["chart_count"]) >= 5, structure["chart_count"], ">=5")
    add("calculation mode", structure["calculation_mode"] in {"auto", "automatic", ""}, structure["calculation_mode"], "auto")
    add("engine recalculation", engine_report.get("engine") == "LibreOffice 26.8.0.3", engine_report.get("engine"), "LibreOffice 26.8.0.3", "engine")
    add("final scenario", engine_report.get("final_scenario") == "Base", engine_report.get("final_scenario"), "Base", "scenario")
    dynamic_status, dynamic_observed = dynamic_evidence_state()
    controls.append({
        "validation_id": f"P8V-{len(controls)+1:03d}", "category": "dynamic",
        "test_name": "dynamic tests", "status": dynamic_status,
        "observed": dynamic_observed, "expected": "PASS with separately identifiable evidence",
    })
    workbook_checks = engine_report.get("checks", [])
    failed_checks = [row for row in workbook_checks if row.get("status") != "PASS"] if isinstance(workbook_checks, list) else []
    add("terminal workbook checks", isinstance(workbook_checks, list) and len(workbook_checks) == 32 and not failed_checks, len(failed_checks), 0, "checks")
    parity = engine_report.get("parity", {})
    expected = {
        "fy2024_lender_base_ebitda": Decimal("179.358"),
        "fy2025_lender_base_ebitda": Decimal("225.344"),
        "opening_total_funded_debt": Decimal("727.51671875"),
        "opening_leverage": Decimal("3.2284716644330446"),
        "selected_all_in_liquidity": Decimal("263.90228125"),
        "selected_common_horizon_debt": Decimal("514.7537077861803"),
        "selected_maturity_gap": Decimal("324.7797051201478"),
        "moderate_unmitigated_maturity_gap": Decimal("408.375"),
        "moderate_mitigated_maturity_gap": Decimal("381.133"),
        "severe_unmitigated_maturity_gap": Decimal("604.258"),
        "severe_mitigated_maturity_gap": Decimal("554.718"),
        "existing_common_horizon_debt": Decimal("495.3682812067100"),
        "existing_maturity_gap": Decimal("432.7492812067100"),
        "reference_maturity_gap": Decimal("340.9478312215932"),
        "sources_uses_difference": Decimal("0"),
    }
    parity_rows: list[dict[str, object]] = []
    for key, target in expected.items():
        try:
            actual = Decimal(str(parity.get(key, "NaN")))
            difference = actual - target
            passed = abs(difference) <= TOLERANCE
        except InvalidOperation:
            actual = Decimal("NaN")
            difference = Decimal("NaN")
            passed = False
        add(f"parity: {key}", passed, fmt(actual), fmt(target), "parity")
        parity_rows.append({
            "parity_id": f"P8P-{len(parity_rows)+1:03d}", "metric": key,
            "excel_value": fmt(actual), "python_value": fmt(target), "difference": fmt(difference),
            "tolerance": fmt(TOLERANCE), "status": "PASS" if passed else "FAIL",
        })
    add("closing coverage remains N/D", parity.get("closing_coverage") == "N/D", parity.get("closing_coverage"), "N/D", "parity")
    if write_outputs:
        write_csv(PROCESSED / "FORMULA_PARITY_RESULTS.csv", parity_rows)
        write_csv(PROCESSED / "WORKBOOK_VALIDATION_RESULTS.csv", controls)
    failed = [
        row for row in controls
        if row["status"] == "FAIL" or (require_dynamic and row["status"] != "PASS")
    ]
    if failed:
        raise Phase8Error("Workbook validation failed: " + ", ".join(str(row["test_name"]) for row in failed))
    return controls


def write_workbook_map() -> None:
    rows = [
        ("Credit Summary", "lender-facing outputs", "C2:N45", "cross-sheet formulas and scenario chart"),
        ("Assumptions", "single selector and approved inputs", "C2:BP365", "editable selector/assumptions plus imported approved source rows"),
        ("Scenario Comparison", "live case and captured comparisons", "C2:AE21", "formulas plus engine-captured values and stale flags"),
        ("Historicals", "FY2021-FY2025 actuals", "C2:T58", "imported reported/calculated values with source IDs"),
        ("Credit Adjustments", "earnings layers and 11 decisions", "C2:AB33", "imported decisions and formula bridges"),
        ("Transaction", "sources, uses and same-date alternatives", "C2:P44", "historical October reference separated from projected January alternatives; native formulas"),
        ("Forecast", "quarterly operating and cash forecast", "C2:W29", "native selected-scenario formulas"),
        ("Debt Schedule", "24 monthly plus 12 quarterly periods", "C2:AD48", "native roll-forward and sensitivity formulas"),
        ("Liquidity", "cash, availability and failure states", "C2:AI48", "native formulas linked to debt schedule"),
        ("Covenants", "quarterly covenant calculations", "C2:AR29", "native formulas and exact status logic"),
        ("Recovery", "Phase 9 pending state", "C2:F15", "no recovery calculations"),
        ("Sensitivities", "balanced term pairings plus integrated amortization", "C2:Q30", "approved Phase 7 pairings and independently generated integrated paths"),
        ("Sources", "source and assumption register", "A1:M80", "approved imported lineage"),
        ("Checks", "terminal audit controls", "C2:H38", "independent formulas; no outbound dependencies"),
    ]
    write_csv(PROCESSED / "WORKBOOK_MAP.csv", [
        {"sheet_order": index, "sheet_name": name, "purpose": purpose, "primary_range": area, "treatment": treatment}
        for index, (name, purpose, area, treatment) in enumerate(rows, start=1)
    ])


def write_docs() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "METHODOLOGY.md").write_text(f"""# Phase 8 methodology

Phase 8 translates the approved Phase 0-7 Python and CSV analysis into one lender-facing `.xlsx` model. It does not revise the 21 owner-reviewed Phase 7 decisions. The calculation direction is `Historicals + Sources + Assumptions -> Transaction + Forecast -> Debt Schedule + Liquidity -> Covenants -> Credit Summary + Scenario Comparison -> Checks`; `Checks` has no outbound dependencies.

## Calculation design

One editable selector on `Assumptions` drives one Forecast, Debt Schedule, Liquidity and Covenants chain. The forecast covers twenty fiscal quarters through January 31, 2031. The debt and liquidity schedules use twenty-four monthly periods followed by twelve non-overlapping quarterly periods. Native formulas select approved scenario-period inputs, calculate forecast subtotals, scale cash interest to debt and rate controls, roll term and revolver balances, retain unpaid mandatory obligations, and distinguish opening, subsequent-minimum and all-in liquidity.

Reported history and approved prior-phase calculated values are imported with source IDs. Transaction mechanics, earnings subtotals, forecast outputs, debt, liquidity, covenant tests, summaries and sensitivities are formulas. Dynamic overlays permit controlled review of term size, non-debt contribution, amortization, rate, EBITDA and DSO without changing the approved saved state.

## Scenario captures and engine

The workbook is authored with the bundled `@oai/artifact-tool` runtime and reproducibly recalculated by LibreOffice 26.8.0.3. Microsoft Excel for Microsoft 365 provides a separate compatibility gate. The capture workflow selects each of nine approved cases, fully recalculates, stores headline values and typed input states, restores Base, recalculates and saves. Captures are snapshots, not parallel live forecasts. A formula-driven stale flag compares each captured typed state with the complete current input state; numeric serialization is normalized at 12 decimal places to avoid sub-ULP cross-engine noise while retaining sensitivity far below any economically meaningful input increment. Dynamic interaction evidence is stored separately under `{DYNAMIC_TEST_DEFINITION_VERSION}`: all {len(REQUIRED_DYNAMIC_CASES)} explicitly identified cases must be unique and PASS, with matching stage, scenario, input scope, engine, scripts, builder, source signature, test-definition digest, and tested-artifact identity. Missing, truncated, duplicated, failed, not-run, or stale evidence cannot pass.

The Transaction sheet separates the October 31, 2025 historical debt reference from January 31, 2026 projected alternatives. Term sizing uses approved Phase 7 source pairings and reports sources less uses explicitly. Amortization sensitivity reruns the selected structure through the Phase 7 cash, revolver, interest, sweep, liquidity, covenant, and maturity engine; it is not a shortcut maturity-gap adjustment. Incomplete LTM periods display `N/D`; `N/M` is reserved for complete periods with nonpositive EBITDA or another nonpositive required denominator.

## Post-commit Excel compatibility correction

The first desktop-Excel opening of commit `b52141dadeb91362cac7cece9b31ec0f3e573534` reported a removed formula record in `sheet14.xml`. Package mapping identifies that part as `Checks`; the exact incompatible record was `Checks!G20`, whose `COUNTIF` used an inline array constant as the range argument. LibreOffice evaluated that permissive extension, but Excel requires `COUNTIF`'s first argument to be a range. The builder now expresses the same nine-value membership test with ordinary `OR` comparisons. No business calculation depends on `Checks`.

Microsoft Excel for Microsoft 365 version 16.0 build 20326 opened the corrected workbook normally, performed a full calculation rebuild, changed the selector to Moderate unmitigated, restored Base, saved a disposable copy, and reopened that copy without repair. Formula and Checks counts are re-established after each bounded generator revision, and no recovery log may be generated.

Missing closing cash interest and unresolved legal or diligence items remain `N/D`, `Pending information`, or `Condition precedent`. Zero and nonpositive denominators display `N/M`. The separate book-cash diagnostic is not covenant or lender net leverage. The Recovery sheet remains pending Phase 9. No post-cutoff evidence is added.
""", encoding="utf-8")
    (DOCS / "WORKBOOK_GUIDE.md").write_text("""# Workbook guide

Use the blue selector on `Assumptions` to change the live case. Blue financing and sensitivity cells on that sheet are the only model controls. The approved saved state is Base with a $635m term, $300m revolver, $15m conditional non-debt source, 7.5% annual amortization, 6.57% modeled all-in rate and 50% ECF sweep. Green cells are imported approved data or cross-sheet links; black cells are same-sheet formulas. Red font is reserved for external workbook links, and none exist.

`Credit Summary` is the lender-facing overview. `Scenario Comparison` shows the current live case and nine versioned captures. `Forecast`, `Debt Schedule`, `Liquidity`, and `Covenants` are the authoritative live chain. `Historicals`, `Credit Adjustments`, `Transaction`, `Sensitivities`, and `Sources` provide traceability and supporting analysis. `Recovery` is deliberately limited to a Phase 9 pending state. `Checks` is terminal and does not feed another sheet.

A `STALE` capture status means a modeled assumption or structure input changed after capture. Run `python scripts/phase8.py all` to rebuild, recalculate, recapture, restore Base, validate and render temporary previews. Do not treat `N/D` as zero, `N/M` as compliance, warning as breach, or a lower debt balance caused by unpaid obligations or draw shutoff as improved performance.

The workbook is not a lender commitment, official compliance certificate, final credit recommendation, final risk grade, or recovery analysis.
""", encoding="utf-8")
    (DOCS / "CALCULATION_VALIDATION.md").write_text(f"""# Calculation validation

The Phase 8 workflow builds the workbook with the bundled artifact runtime, recalculates every approved scenario in LibreOffice 26.8.0.3, captures comparisons, restores Base, saves, and then validates structure and cached results. USD-million and ratio parity use a 0.002 tolerance.

Controls cover the exact 14-sheet order, native formulas and charts, terminal `Checks`, external links, cached formula errors, calculation mode, workbook checks, Base restoration, Python-to-workbook numeric points, same-date alternative comparisons, balanced Phase 7 sizing pairings, and closing coverage remaining `N/D`. The disposable dynamic copy tests scenario changes, fixed historicals, term size, contribution, amortization, rate and spread, EBITDA, DSO, exact covenant boundaries, incomplete LTM periods, complete zero/negative denominators, missing interest, revolver exhaustion, draw shutoff, cash-floor and sweep safeguards, stale capture status, and full Base restoration. The `{DYNAMIC_TEST_DEFINITION_VERSION}` registry contains {len(REQUIRED_DYNAMIC_CASES)} required case identities; exact completeness, uniqueness, PASS status, runtime metadata, test-definition digest, and tested-artifact identity are enforced. An absent or explicitly not-run gate is `NOT_RUN`; malformed, stale, truncated, duplicated, failed, or unsupported evidence is `FAIL`.

The post-commit Excel compatibility control maps `sheet14.xml` to `Checks`, rejects OOXML formula text with a leading equals sign, and rejects inline array constants passed to range-only criteria functions. The bounded audit-remediation workbook contains 3,318 Phase 8 cell formulas before later-phase overlays. Its normalized Phase 8 fingerprint is `a0c7329eca85e5d830e74394a9e7b72eacfc0aee3c93ee920901321397a6ed80`; the change from the earlier compatibility fingerprint reflects the intended live cash/debt integration, deterministic package canonicalization, same-date transaction, sensitivity, LTM completeness, canonical source-byte generation, validation-evidence revisions, and cross-engine typed-state normalization.

Microsoft Excel for Microsoft 365 version 16.0 build 20326 opened the corrected workbook without repair, ran a full calculation rebuild, updated a non-Base scenario, restored Base, saved, closed, and reopened a disposable copy. Formula counts and the Base output remained intact, all nine captures were `CURRENT`, both capture-freshness checks were `PASS` before save and after reopen, and no recovery log was generated. The artifact renderer independently requires the same nine `CURRENT` states and both `PASS` checks after rendering. Run `powershell -ExecutionPolicy Bypass -NoProfile -File scripts/validate-phase8-excel.ps1` for the separate Excel gate.

All sheets are rendered to temporary PNG previews through the artifact runtime and inspected for formulas, styles, hierarchy, widths, status text and chart placement. LibreOffice applies bounded print areas, landscape orientation on wide schedules, fit-to-width settings, and repeated header rows on long tables.

Native engine metadata and chart-axis identifiers can change during recalculation. The authoritative generated package therefore receives an atomic, deterministic packaging pass that fixes neutral core metadata, remaps chart-axis references consistently, and emits fixed ZIP metadata; repeated same-input production builds are tested for byte identity. Cross-engine review still compares source signatures and normalized workbook components because disposable copies saved by different spreadsheet engines need not be byte-identical. Chart placement remains separately validated by structural tests and rendered-sheet review.
""", encoding="utf-8")
    (DOCS / "PHASE9_HANDOFF.md").write_text("""# Phase 9 handoff

Phase 9 remains unstarted. The existing `Recovery` sheet contains no recovery percentage, collateral value, enterprise value, liquidation value, or invented guarantee credit.

Separate authorization and evidence are required for collateral scope, priority, liens, perfection, guarantor coverage, foreign-cash accessibility, asset appraisals, receivable and inventory eligibility, intellectual-property value, going-concern valuation and liquidation costs. Going-concern and liquidation must remain alternative cases rather than additive recoveries.

Phase 9 should consume the approved Phase 8 workbook in its saved Base state, preserve the 14-sheet architecture, retain unresolved legal fields, and avoid changing Phase 7 financing or covenant decisions without explicit owner review. Any recovery output must remain separate from the Phase 10 final recommendation and risk grade.
""", encoding="utf-8")
    ledger = []
    for index, relative in enumerate(SOURCE_INPUTS, start=1):
        ledger.append({
            "ledger_id": f"P8L-{index:03d}", "source_path": relative,
            "source_type": "approved_prior_phase_artifact", "source_date": "2025-12-15_or_earlier",
            "workbook_use": "formula input, parity control, source register, or disclosure",
            "input_signature": hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
            "cutoff_status": "within_cutoff", "review_status": "approved_upstream",
            "limitations": "Use remains subject to the classifications and limitations in the source artifact.",
        })
    write_csv(DOCS / "SOURCE_LEDGER.csv", ledger)


def update_readme() -> None:
    path = ROOT / "README.md"
    text = path.read_text(encoding="utf-8")
    marker = "## Phase 8 Excel underwriting model"
    section = """

## Phase 8 Excel underwriting model

Phase 8 adds `model/Quanex_Credit_Underwriting.xlsx`, a 14-sheet formula-driven underwriting workbook with one live scenario selector, captured scenario comparisons, transaction, forecast, debt, liquidity, covenant, sensitivity, source and terminal-check views. LibreOffice 26.8.0.3 performs the required full recalculation and saves the Base scenario.

Reproduce and validate with:

```powershell
python scripts/phase8.py all
python -m unittest discover -s tests -v
```

The workbook preserves the approved Phase 7 provisional structure. At Phase 8 completion, recovery analysis and the final recommendation were still pending; those historical phase boundaries do not supersede the current **Conditional Approval** recommendation above. The conditional $15 million source, closing cash-interest evidence, legal definitions, and other stated diligence items remain unresolved.
"""
    if marker not in text:
        path.write_text(text.rstrip() + section + "\n", encoding="utf-8")
        return
    prefix, existing = text.split(marker, 1)
    next_section = existing.find("\n## ")
    suffix = "" if next_section < 0 else existing[next_section:]
    path.write_text(prefix.rstrip() + section.rstrip() + suffix.rstrip() + "\n", encoding="utf-8")


def build() -> dict[str, object]:
    head = git_head()
    approved = head in {APPROVED_PHASE7_COMMIT, APPROVED_PHASE8_COMMIT} or run(
        ["git", "merge-base", "--is-ancestor", APPROVED_PHASE8_COMMIT, head], check=False,
    ).returncode == 0
    if not approved:
        raise Phase8Error(f"HEAD is not the approved Phase 7/8 checkpoint or a descendant: {head}")
    if run(["git", "branch", "--show-current"]).stdout.strip() != "main":
        raise Phase8Error("Phase 8 must run on main")
    DYNAMIC_EVIDENCE.unlink(missing_ok=True)
    build_starting_checkpoint()
    period_rows = build_period_inputs()
    support = build_model_support_inputs()
    write_workbook_map()
    write_docs()
    update_readme()
    run_artifact_tool("build")
    capture = run_libreoffice("capture")
    write_capture_results(capture)
    inspect = run_libreoffice("inspect")
    controls = validate_workbook(inspect, require_dynamic=False)
    return {
        "period_input_rows": len(period_rows), "scenarios": len(SCENARIOS),
        "workbook_size": MODEL.stat().st_size, "validation_controls": len(controls),
        "formula_count": workbook_structure()["formula_count"],
        **support,
    }


def visual(preview_dir: Path | None = None) -> dict[str, object]:
    if preview_dir is None:
        preview_dir = Path(tempfile.mkdtemp(prefix="quanex-phase8-previews-"))
    preview_dir.mkdir(parents=True, exist_ok=True)
    run_artifact_tool("inspect", preview_dir)
    previews = sorted(preview_dir.glob("*.png"))
    if len(previews) != 14:
        raise Phase8Error(f"Expected 14 sheet previews, found {len(previews)}")
    return {"preview_dir": str(preview_dir), "preview_count": len(previews)}


def dynamic(
    evidence_path: Path | None = None,
    *,
    tested_artifact: str | None = None,
) -> dict[str, object]:
    evidence_path = DYNAMIC_EVIDENCE if evidence_path is None else evidence_path
    tested_artifact = tested_artifact or DYNAMIC_TESTED_ARTIFACT
    with tempfile.TemporaryDirectory(prefix="quanex-phase8-dynamic-") as temp_name:
        copy = Path(temp_name) / MODEL.name
        shutil.copy2(MODEL, copy)
        tested_artifact_sha256 = sha256(copy)
        tested_artifact_fingerprint = normalized_fingerprint()
        report = run_libreoffice("dynamic", copy)
        report["tested_artifact"] = tested_artifact
        report["tested_artifact_sha256"] = tested_artifact_sha256
        report["tested_artifact_semantic_fingerprint"] = tested_artifact_fingerprint
    if report.get("dynamic_status") != "PASS":
        evidence_path.unlink(missing_ok=True)
        raise Phase8Error("Dynamic workbook tests failed")
    write_dynamic_evidence(
        report, evidence_path=evidence_path, tested_artifact=tested_artifact,
    )
    return report


def normalized_fingerprint() -> str:
    return semantic_workbook_fingerprint(
        MODEL,
        prefix_parts=(
            source_signature().encode("ascii"),
            (ROOT / "scripts" / "build-phase8.mjs").read_bytes(),
        ),
    )


def all_workflow() -> None:
    summary = build()
    dynamic_report = dynamic()
    final_controls = validate_workbook()
    with tempfile.TemporaryDirectory(prefix="quanex-phase8-previews-") as temp_name:
        previews = visual(Path(temp_name))
    summary["dynamic_tests"] = dynamic_report.get("test_count")
    summary["final_validation_controls"] = len(final_controls)
    summary["preview_count"] = previews["preview_count"]
    summary["normalized_fingerprint"] = normalized_fingerprint()
    print("Phase 8 complete: " + json.dumps(summary, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("inputs", "build", "validate", "dynamic", "visual", "all"))
    parser.add_argument("--preview-dir", type=Path)
    args = parser.parse_args()
    if args.command == "inputs":
        build_starting_checkpoint(); print(f"Phase 8 inputs: {len(build_period_inputs())} rows")
    elif args.command == "build":
        print(json.dumps(build(), indent=2))
    elif args.command == "validate":
        print(f"Phase 8 validation: PASS ({len(validate_workbook(write_outputs=False))} controls)")
    elif args.command == "dynamic":
        print(json.dumps(dynamic(), indent=2))
    elif args.command == "visual":
        print(json.dumps(visual(args.preview_dir), indent=2))
    else:
        all_workflow()


if __name__ == "__main__":
    main()
