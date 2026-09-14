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


def dynamic_evidence_state() -> tuple[str, str]:
    if not DYNAMIC_EVIDENCE.is_file():
        return "NOT_RUN", "dynamic evidence file absent"
    rows = read_csv(DYNAMIC_EVIDENCE)
    if not rows:
        return "NOT_RUN", "dynamic evidence file empty"
    current_script = sha256(ROOT / "scripts" / "recalculate-phase8.py")
    current_builder = sha256(ROOT / "scripts" / "build-phase8.mjs")
    if any(row.get("dynamic_script_sha256") != current_script or row.get("workbook_builder_sha256") != current_builder for row in rows):
        return "N/D", "dynamic evidence does not match current workbook logic"
    if any(row.get("source_input_signature") != source_signature() for row in rows):
        return "N/D", "dynamic evidence does not match current source inputs"
    if any(row.get("status") == "FAIL" for row in rows):
        return "FAIL", "one or more dynamic tests failed"
    if not all(row.get("status") == "PASS" for row in rows):
        return "N/D", "dynamic evidence is incomplete"
    return "PASS", f"{len(rows)} separately recorded dynamic tests"


def write_dynamic_evidence(report: dict[str, object]) -> list[dict[str, object]]:
    tests = report.get("tests", [])
    if report.get("dynamic_status") != "PASS" or not isinstance(tests, list) or not tests:
        DYNAMIC_EVIDENCE.unlink(missing_ok=True)
        return []
    rows = [{
        "evidence_id": f"P8DE-{index:03d}",
        "test_name": str(item.get("test", "")),
        "status": str(item.get("status", "N/D")),
        "observed": json.dumps(item.get("observed"), sort_keys=True, separators=(",", ":")),
        "engine": str(report.get("engine", "")),
        "final_scenario": str(report.get("final_scenario", "")),
        "dynamic_script_sha256": sha256(ROOT / "scripts" / "recalculate-phase8.py"),
        "workbook_builder_sha256": sha256(ROOT / "scripts" / "build-phase8.mjs"),
        "source_input_signature": source_signature(),
        "tested_artifact": "disposable copy of model/Quanex_Credit_Underwriting.xlsx",
    } for index, item in enumerate(tests, 1)]
    write_csv(DYNAMIC_EVIDENCE, rows)
    return rows


def validate_workbook(
    engine_report: dict[str, object] | None = None,
    *,
    require_dynamic: bool = True,
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
    (DOCS / "METHODOLOGY.md").write_text("""# Phase 8 methodology

Phase 8 translates the approved Phase 0-7 Python and CSV analysis into one lender-facing `.xlsx` model. It does not revise the 21 owner-reviewed Phase 7 decisions. The calculation direction is `Historicals + Sources + Assumptions -> Transaction + Forecast -> Debt Schedule + Liquidity -> Covenants -> Credit Summary + Scenario Comparison -> Checks`; `Checks` has no outbound dependencies.

## Calculation design

One editable selector on `Assumptions` drives one Forecast, Debt Schedule, Liquidity and Covenants chain. The forecast covers twenty fiscal quarters through January 31, 2031. The debt and liquidity schedules use twenty-four monthly periods followed by twelve non-overlapping quarterly periods. Native formulas select approved scenario-period inputs, calculate forecast subtotals, scale cash interest to debt and rate controls, roll term and revolver balances, retain unpaid mandatory obligations, and distinguish opening, subsequent-minimum and all-in liquidity.

Reported history and approved prior-phase calculated values are imported with source IDs. Transaction mechanics, earnings subtotals, forecast outputs, debt, liquidity, covenant tests, summaries and sensitivities are formulas. Dynamic overlays permit controlled review of term size, non-debt contribution, amortization, rate, EBITDA and DSO without changing the approved saved state.

## Scenario captures and engine

The workbook is authored with the bundled `@oai/artifact-tool` runtime and reproducibly recalculated by LibreOffice 26.8.0.3. Microsoft Excel for Microsoft 365 provides a separate compatibility gate. The capture workflow selects each of nine approved cases, fully recalculates, stores headline values and signatures, restores Base, recalculates and saves. Captures are snapshots, not parallel live forecasts. A formula-driven stale flag compares each captured signature with the current input signature. Dynamic interaction evidence is stored separately and can pass only when the disposable-copy test actually ran, matched the current scripts and source signature, and every recorded test passed.

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
    (DOCS / "CALCULATION_VALIDATION.md").write_text("""# Calculation validation

The Phase 8 workflow builds the workbook with the bundled artifact runtime, recalculates every approved scenario in LibreOffice 26.8.0.3, captures comparisons, restores Base, saves, and then validates structure and cached results. USD-million and ratio parity use a 0.002 tolerance.

Controls cover the exact 14-sheet order, native formulas and charts, terminal `Checks`, external links, cached formula errors, calculation mode, workbook checks, Base restoration, Python-to-workbook numeric points, same-date alternative comparisons, balanced Phase 7 sizing pairings, and closing coverage remaining `N/D`. The disposable dynamic copy tests scenario changes, fixed historicals, term size, contribution, amortization, rate and spread, EBITDA, DSO, exact covenant boundaries, incomplete LTM periods, complete zero/negative denominators, missing interest, revolver exhaustion, draw shutoff, cash-floor and sweep safeguards, stale capture status, and full Base restoration. An unrun or unsupported dynamic gate remains `NOT_RUN` or `N/D`; it cannot pass.

The post-commit Excel compatibility control maps `sheet14.xml` to `Checks`, rejects OOXML formula text with a leading equals sign, and rejects inline array constants passed to range-only criteria functions. The bounded audit-remediation workbook contains 2,742 Phase 8 cell formulas before later-phase overlays. Its normalized Phase 8 fingerprint is `3f66a86542015ee20dc9812b99f00cfbcc84b8a56e78173247e5a5a77a7922dd`; the change from the earlier compatibility fingerprint reflects the intended same-date transaction, integrated sensitivity, LTM completeness, and validation-evidence revisions.

Microsoft Excel for Microsoft 365 version 16.0 build 20326 opened the corrected workbook without repair, ran a full calculation rebuild, updated a non-Base scenario, restored Base, saved, closed, and reopened a disposable copy. Formula counts and the Base output remained intact, and no recovery log was generated. Run `powershell -ExecutionPolicy Bypass -NoProfile -File scripts/validate-phase8-excel.ps1` for this separate Excel gate.

All sheets are rendered to temporary PNG previews through the artifact runtime and inspected for formulas, styles, hierarchy, widths, status text and chart placement. LibreOffice applies bounded print areas, landscape orientation on wide schedules, fit-to-width settings, and repeated header rows on long tables.

Native engine metadata, capture timestamps, chart-axis identifiers, and sub-point drawing coordinates can change between runs. Deterministic testing therefore compares source signatures and normalized workbook components, excluding volatile core properties, capture timestamp strings, calculation-chain metadata, and engine-rounded drawing-coordinate serialization while canonically mapping chart-axis identifiers. Chart placement is separately validated by structural tests and rendered-sheet review. This is not a claim of byte-identical `.xlsx` archives.
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
    if marker in text:
        return
    addition = """

## Phase 8 Excel underwriting model

Phase 8 adds `model/Quanex_Credit_Underwriting.xlsx`, a 14-sheet formula-driven underwriting workbook with one live scenario selector, captured scenario comparisons, transaction, forecast, debt, liquidity, covenant, sensitivity, source and terminal-check views. LibreOffice 26.8.0.3 performs the required full recalculation and saves the Base scenario.

Reproduce and validate with:

```powershell
python scripts/phase8.py all
python -m unittest discover -s tests -v
```

The workbook preserves the approved Phase 7 provisional structure. The conditional $15 million source, closing cash interest, legal definitions and other diligence items remain unresolved. Recovery analysis remains pending Phase 9, and no final credit recommendation is made.
"""
    path.write_text(text.rstrip() + addition + "\n", encoding="utf-8")


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


def dynamic() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="quanex-phase8-dynamic-") as temp_name:
        copy = Path(temp_name) / MODEL.name
        shutil.copy2(MODEL, copy)
        report = run_libreoffice("dynamic", copy)
    if report.get("dynamic_status") != "PASS":
        DYNAMIC_EVIDENCE.unlink(missing_ok=True)
        raise Phase8Error("Dynamic workbook tests failed")
    write_dynamic_evidence(report)
    return report


def normalized_fingerprint() -> str:
    excluded = {"docProps/core.xml", "xl/calcChain.xml", "xl/sharedStrings.xml"}
    digest = hashlib.sha256()
    digest.update(source_signature().encode("ascii"))
    digest.update((ROOT / "scripts" / "build-phase8.mjs").read_bytes())
    with zipfile.ZipFile(MODEL) as archive:
        for name in sorted(archive.namelist()):
            if name in excluded:
                continue
            if name.startswith("xl/drawings/drawing") and name.endswith(".xml"):
                continue
            data = archive.read(name)
            if name.startswith("xl/charts/chart") and name.endswith(".xml"):
                axis_ids: dict[bytes, bytes] = {}

                def normalize_axis_id(match: re.Match[bytes]) -> bytes:
                    original = match.group(2)
                    if original not in axis_ids:
                        axis_ids[original] = str(len(axis_ids) + 1).encode("ascii")
                    return match.group(1) + axis_ids[original] + match.group(3)

                data = re.sub(
                    rb'(<c:(?:axId|crossAx) val=")(\d+)("/>)',
                    normalize_axis_id,
                    data,
                )
            digest.update(name.encode("utf-8"))
            digest.update(data)
    return digest.hexdigest()


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
        print(f"Phase 8 validation: PASS ({len(validate_workbook())} controls)")
    elif args.command == "dynamic":
        print(json.dumps(dynamic(), indent=2))
    elif args.command == "visual":
        print(json.dumps(visual(args.preview_dir), indent=2))
    else:
        all_workflow()


if __name__ == "__main__":
    main()
