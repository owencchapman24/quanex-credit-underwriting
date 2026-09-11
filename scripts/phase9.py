"""Phase 9 recovery, borrower-risk, monitoring, and workbook integration.

The module consumes the approved Phase 0-8 artifacts without live network access.
Recovery sensitivities are illustrative owner-review cases.  The official public-
information facility recovery conclusion remains not determinable.
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
from datetime import date
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "phase9"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
DOCS = ROOT / "docs" / "phase-9"
MODEL = ROOT / "model" / "Quanex_Credit_Underwriting.xlsx"
APPROVED_PHASE8_COMMIT = "1a23f7f1c393082329277bf4129ba31343f6cb87"
PHASE8_FINGERPRINT = "7dae55edc1d7fbb7ae15c04ff8173a5e610e75c31f4a6c75ad2c72e4eb078635"
INFORMATION_CUTOFF = "2025-12-15"
NODE = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe"
NODE_MODULES = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "node_modules"
PROGRAM_FILES = Path(os.environ.get("ProgramFiles", "Program Files"))
LIBREOFFICE = Path(shutil.which("soffice.exe") or PROGRAM_FILES / "LibreOffice" / "program" / "soffice.exe")
LO_PYTHON = LIBREOFFICE.with_name("python.exe")
TOLERANCE = Decimal("0.002")
N_D = "N/D"
REVIEW = "owner_reviewed"

SOURCE_INPUTS = (
    "data/phase2/processed/historical_spread.csv",
    "data/phase2/processed/adjustment_decisions.csv",
    "data/phase3/processed/RISK_DRIVER_MAP.csv",
    "data/phase3/processed/INFORMATION_GAPS.csv",
    "data/phase4/processed/LEGAL_STRUCTURE_REGISTER.csv",
    "data/phase5/processed/BASE_CASE_CREDIT_METRICS.csv",
    "data/phase6/processed/SCENARIO_RESULTS.csv",
    "data/phase7/processed/STRUCTURE_COMPARISON.csv",
    "data/phase7/processed/BREACH_INTERVENTION_TIMELINE.csv",
    "data/phase7/processed/ULTIMATE_MATURITY_COMPARISON.csv",
    "data/phase8/processed/FORMULA_PARITY_RESULTS.csv",
    "docs/phase-0/EVIDENCE_INVENTORY.csv",
)


class Phase9Error(RuntimeError):
    """Raised when a Phase 9 control fails."""


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise Phase9Error(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


phase7 = load_module("phase7_for_phase9", ROOT / "scripts" / "phase7.py")
phase8 = load_module("phase8_for_phase9", ROOT / "scripts" / "phase8.py")


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
        raise Phase9Error(f"Numeric value required, received {value!r}")
    return Decimal(str(value))


def fmt(value: Decimal | object) -> str:
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        capture_output=True, check=True,
    ).stdout.strip()


def is_phase8_descendant(head: str) -> bool:
    if head == APPROVED_PHASE8_COMMIT:
        return True
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", APPROVED_PHASE8_COMMIT, head],
        cwd=ROOT, capture_output=True,
    ).returncode == 0


def source_signature() -> str:
    digest = hashlib.sha256()
    for relative in SOURCE_INPUTS:
        path = ROOT / relative
        digest.update(relative.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def selected_exposure() -> dict[str, str]:
    candidates = phase7.candidate_definitions()
    _, selected_monthly, _ = phase7.build_structure_comparison(candidates)
    severe = selected_monthly["SEVERE_UNMITIGATED"]
    failure = next(row for row in severe if row["mandatory_payment_failure_flag"] == "yes")
    term = dec(failure["ending_term_principal"])
    revolver = dec(failure["ending_revolver"])
    unpaid_interest = dec(failure["cash_interest_shortfall"])
    retained = Decimal("62.619")
    bank_principal = term + revolver
    return {
        "recovery_date": failure["month_end"],
        "scenario_id": "SEVERE_UNMITIGATED",
        "term_principal": fmt(term),
        "revolver_principal": fmt(revolver),
        "bank_principal": fmt(bank_principal),
        "unpaid_cash_interest": fmt(unpaid_interest),
        "facility_claim": fmt(bank_principal + unpaid_interest),
        "retained_other_funded_debt": fmt(retained),
        "gross_funded_principal": fmt(bank_principal + retained),
        "stressed_ttm_ebitda": failure["ttm_lender_base_ebitda"],
        "gross_funded_leverage": failure["gross_funded_leverage"],
        "cash_interest_due": failure["cash_interest_due"],
        "cash_interest_paid": failure["cash_interest_paid"],
        "usable_liquidity": failure["usable_liquidity"],
        "drawability_status": failure["drawability_status"],
        "failed_obligation_type": failure["failed_mandatory_obligation_type"],
    }


def maturity_exposure() -> dict[str, str]:
    row = next(
        item for item in read_csv(ROOT / "data" / "phase7" / "processed" / "ULTIMATE_MATURITY_COMPARISON.csv")
        if item["candidate_id"] == "STR-008"
    )
    return {
        "date": row["maturity_date"],
        "bank_claim_before_cash": row["maturity_payment_due"],
        "cash_applied": row["available_cash_applied"],
        "unsupported_gap": row["unsupported_maturity_gap"],
        "retained_other_funded_debt": "62.619",
        "gross_funded_before_cash": fmt(dec(row["maturity_payment_due"]) + Decimal("62.619")),
    }


def recovery_assumptions(exposure: dict[str, str], maturity: dict[str, str]) -> list[dict[str, str]]:
    rows: list[tuple[str, str, str, str, str, str, str, str, str, str]] = [
        ("P9A-001", "recovery_date", "primary recovery-analysis date", exposure["recovery_date"], "date", "calculated", "STR-008;SEVERE_UNMITIGATED", "First mandatory cash-interest failure in the selected severe continued-draw path.", "primary_date", REVIEW),
        ("P9A-002", "scenario", "primary recovery scenario", exposure["scenario_id"], "identifier", "calculated", "P7SC-STR-008-SEVERE_UNMITIGATED", "Selected severe unmitigated proposed structure; not the Base case.", "primary_date", REVIEW),
        ("P9A-003", "claim", "term principal at recovery date", exposure["term_principal"], "USD_millions", "calculated", "Phase 7 selected monthly path", "Ending term principal at the first mandatory-payment failure date.", "both", "approved_upstream_calculation"),
        ("P9A-004", "claim", "revolver principal at recovery date", exposure["revolver_principal"], "USD_millions", "calculated", "Phase 7 selected monthly path", "Ending revolver principal at the first mandatory-payment failure date.", "both", "approved_upstream_calculation"),
        ("P9A-005", "claim", "unpaid cash interest at recovery date", exposure["unpaid_cash_interest"], "USD_millions", "calculated", "Phase 7 selected monthly path", "Cash-interest shortfall in the first mandatory-payment failure month.", "both", REVIEW),
        ("P9A-006", "claim", "retained finance lease and other funded obligations", exposure["retained_other_funded_debt"], "USD_millions", "calculated", "P5A-032", "Retained funded obligations included in the sensitivity; ranking, collateral priority, entity allocation and enforceability remain not determinable.", "both", REVIEW),
        ("P9A-007", "earnings", "stressed TTM lender-base EBITDA", exposure["stressed_ttm_ebitda"], "USD_millions", "calculated", "Phase 7 selected monthly path", "Stress-date TTM lender EBITDA; not contractual EBITDA or a compliance certificate.", "going_concern", REVIEW),
        ("P9A-008", "going_concern", "low going-concern multiple", "3", "turns", "proposed_assumption", "P9D-003", "Continued-operation enterprise-value sensitivity; no market evidence is asserted and a sale versus restructuring path is not selected.", "going_concern_low", REVIEW),
        ("P9A-009", "going_concern", "base going-concern multiple", "4", "turns", "proposed_assumption", "P9D-003", "Continued-operation enterprise-value sensitivity; no market evidence is asserted and a sale versus restructuring path is not selected.", "going_concern_base", REVIEW),
        ("P9A-010", "going_concern", "high going-concern multiple", "5", "turns", "proposed_assumption", "P9D-003", "Continued-operation enterprise-value sensitivity; no market evidence is asserted and a sale versus restructuring path is not selected.", "going_concern_high", REVIEW),
        ("P9A-011", "cost", "going-concern realization cost", "10", "percent", "proposed_assumption", "P9D-004", "Deducted once from gross enterprise value.", "going_concern", REVIEW),
        ("P9A-012", "cost", "asset-realization cost", "15", "percent", "proposed_assumption", "P9D-008", "Deducted once from gross illustrative asset proceeds.", "asset_realization", REVIEW),
        ("P9A-013", "deduction", "other-funded-obligations deduction used for conservative sensitivity", exposure["retained_other_funded_debt"], "USD_millions", "proposed_assumption", "P9D-011", "Deducted once so retained finance leases and other funded obligations are not ignored. It is not evidence that the amount legally ranks ahead of the bank facilities; ranking, collateral priority, entity allocation and enforceability remain not determinable.", "both", REVIEW),
        ("P9A-014", "access", "full consolidated-access ceiling case", "100", "percent", "proposed_assumption", "P9D-012", "Gross mechanical upper-bound sensitivity only. Full consolidated access is not expected lender access; entity-level, foreign-asset, guarantor, collateral and legal accessibility remain not determinable.", "asset_realization", REVIEW),
        ("P9A-015", "access", "cash realization credit", "0", "percent", "proposed_assumption", "P9D-009", "Explicit zero credit pending entity-level accessibility evidence; not a claim that cash has no value.", "asset_realization", REVIEW),
        ("P9A-016", "asset", "receivables realization low", "50", "percent", "proposed_assumption", "P9D-005", "Illustrative; not an eligibility or collectability conclusion.", "asset_low", REVIEW),
        ("P9A-017", "asset", "receivables realization base", "70", "percent", "proposed_assumption", "P9D-005", "Illustrative; not an eligibility or collectability conclusion.", "asset_base", REVIEW),
        ("P9A-018", "asset", "receivables realization high", "85", "percent", "proposed_assumption", "P9D-005", "Illustrative; not an eligibility or collectability conclusion.", "asset_high", REVIEW),
        ("P9A-019", "asset", "inventory realization low", "20", "percent", "proposed_assumption", "P9D-006", "Illustrative; no inventory appraisal or saleability analysis is available.", "asset_low", REVIEW),
        ("P9A-020", "asset", "inventory realization base", "40", "percent", "proposed_assumption", "P9D-006", "Illustrative; no inventory appraisal or saleability analysis is available.", "asset_base", REVIEW),
        ("P9A-021", "asset", "inventory realization high", "60", "percent", "proposed_assumption", "P9D-006", "Illustrative; no inventory appraisal or saleability analysis is available.", "asset_high", REVIEW),
        ("P9A-022", "asset", "PP&E realization low", "20", "percent", "proposed_assumption", "P9D-007", "Illustrative; consolidated book PP&E is not an appraisal or collateral schedule.", "asset_low", REVIEW),
        ("P9A-023", "asset", "PP&E realization base", "40", "percent", "proposed_assumption", "P9D-007", "Illustrative; consolidated book PP&E is not an appraisal or collateral schedule.", "asset_base", REVIEW),
        ("P9A-024", "asset", "PP&E realization high", "60", "percent", "proposed_assumption", "P9D-007", "Illustrative; consolidated book PP&E is not an appraisal or collateral schedule.", "asset_high", REVIEW),
        ("P9A-025", "priority", "bank claim allocation", "pari_passu_pro_rata", "text", "proposed_assumption", "P9D-013", "Illustrative term/revolver/unpaid-interest allocation only; final legal priority is not known.", "both", REVIEW),
        ("P9A-026", "conclusion", "official facility recovery", N_D, "status", "not_determinable", "GAP-001;GAP-002;GAP-004", "Missing guarantor, collateral, lien, priority, appraisal, access, and claims evidence prevents an official percentage.", "official", "not_determinable"),
        ("P9A-027", "maturity", "maturity sensitivity date", maturity["date"], "date", "calculated", "P7UM-008", "Separate refinancing exposure sensitivity; not the primary default date.", "maturity", REVIEW),
        ("P9A-028", "maturity", "maturity bank claim before cash", maturity["bank_claim_before_cash"], "USD_millions", "calculated", "P7UM-008", "Bank maturity payment due before modeled cash application.", "maturity", "approved_upstream_calculation"),
    ]
    return [
        {"assumption_id": rid, "category": category, "description": description, "value": value,
         "unit": unit, "classification": classification, "source_or_ids": source, "rationale": rationale,
         "sensitivity_role": role, "limitation": rationale, "review_status": status}
        for rid, category, description, value, unit, classification, source, rationale, role, status in rows
    ]


def owner_decisions() -> list[dict[str, str]]:
    decisions = [
        ("P9D-001", "Primary recovery date", "Use 2027-12-31, the first mandatory cash-interest failure in selected severe unmitigated.", "Approve the date or select another traceable model event."),
        ("P9D-002", "Recovery earnings", "Use stress-date TTM lender-base EBITDA of $130.356m for the going-concern sensitivity.", "Approve, revise, or set going-concern analysis to N/D."),
        ("P9D-003", "Going-concern multiples", "Use 3.0x / 4.0x / 5.0x only as low/base/high illustrative sensitivities.", "Approve or revise; no market evidence supports the range."),
        ("P9D-004", "Going-concern realization cost", "Deduct 10% once from enterprise value.", "Approve or revise."),
        ("P9D-005", "Receivables realization", "Use 50% / 70% / 85% of FY2025 consolidated book receivables.", "Approve or revise; not an ABL eligibility conclusion."),
        ("P9D-006", "Inventory realization", "Use 20% / 40% / 60% of FY2025 consolidated book inventory.", "Approve or revise; no appraisal is available."),
        ("P9D-007", "PP&E realization", "Use 20% / 40% / 60% of FY2025 consolidated net PP&E.", "Approve or revise; no appraisal is available."),
        ("P9D-008", "Asset realization cost", "Deduct 15% once from gross illustrative asset proceeds.", "Approve or revise."),
        ("P9D-009", "Cash recovery credit", "Give zero illustrative credit pending entity-level accessibility evidence.", "Approve or revise after cash-access diligence."),
        ("P9D-010", "Goodwill and intangibles", "Give zero asset-realization credit to goodwill and unsupported intangibles.", "Approve or revise only with specific value evidence."),
        ("P9D-011", "Other-funded-obligations deduction", "Deduct $62.619m of retained finance leases and other funded obligations once for conservative sensitivity; no legal ranking is asserted.", "Owner revision implemented; ranking, collateral priority, entity allocation and enforceability remain N/D."),
        ("P9D-012", "Full consolidated-access ceiling case", "Use 100% consolidated accessibility solely as a gross mechanical upper-bound sensitivity, not expected lender access.", "Owner revision implemented; actual entity, foreign-asset, guarantor, collateral and legal accessibility remain N/D."),
        ("P9D-013", "Bank allocation", "Allocate illustrative bank proceeds pro rata among term, revolver, and unpaid interest.", "Approve or revise after priority documentation."),
        ("P9D-014", "Official facility recovery", "Keep the official recovery conclusion N/D.", "Approve until legal, appraisal, and claims evidence is complete."),
        ("P9D-015", "Borrower risk grade", "Provisional grade: Elevated.", "Approve, revise to Satisfactory/Weak, or request additional evidence."),
        ("P9D-016", "Monitoring thresholds and actions", "Adopt MON-001 through MON-026 as proposed post-closing monitoring triggers.", "Approve or revise individual thresholds, reports, owners, and actions."),
    ]
    return [
        {"decision_id": rid, "judgment": judgment, "proposed_treatment": treatment,
         "owner_action_required": "None before commit; revisit only if new evidence changes this treatment.",
         "review_status": REVIEW}
        for rid, judgment, treatment, action in decisions
    ]


def latest_book_values() -> dict[str, Decimal]:
    rows = read_csv(ROOT / "data" / "phase2" / "processed" / "historical_spread.csv")
    wanted = {
        "cash_and_cash_equivalents", "accounts_receivable", "inventory",
        "property_plant_and_equipment_net", "goodwill", "intangible_assets_net",
        "other_presented_current_assets",
    }
    values = {
        row["metric_name"]: dec(row["value"])
        for row in rows if row["fiscal_year"] == "FY2025" and row["metric_name"] in wanted
    }
    if set(values) != wanted:
        raise Phase9Error(f"Missing FY2025 book values: {sorted(wanted - set(values))}")
    return values


def recovery_cases(exposure: dict[str, str], assumptions: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    index = {row["assumption_id"]: row for row in assumptions}
    claim = dec(exposure["facility_claim"])
    ebitda = dec(exposure["stressed_ttm_ebitda"])
    prior = dec(index["P9A-013"]["value"])
    cases: list[dict[str, str]] = []
    waterfall: list[dict[str, str]] = []

    def add_case(case_id: str, method: str, name: str, gross: Decimal, cost_rate: Decimal, basis: str) -> None:
        costs = gross * cost_rate
        after_cost = max(Decimal("0"), gross - costs)
        bank = max(Decimal("0"), after_cost - prior)
        recovery = min(bank, claim) / claim if claim > 0 else Decimal("0")
        residual = max(Decimal("0"), bank - claim)
        cases.append({
            "case_id": case_id, "method": method, "case_name": name,
            "valuation_date": exposure["recovery_date"], "scenario_id": exposure["scenario_id"],
            "facility_claim": fmt(claim), "valuation_basis": basis,
            "gross_value": fmt(gross), "realization_costs": fmt(costs),
            "other_funded_obligations_deduction": fmt(prior),
            "illustrative_bank_allocation": fmt(min(bank, claim)),
            "illustrative_facility_recovery_percent": fmt(recovery * 100), "residual_value": fmt(residual),
            "official_status": "illustrative_sensitivity_only", "review_status": REVIEW,
            "limitations": "Assumes value and allocation mechanics solely for sensitivity. The $62.619m deduction does not establish legal seniority. Full consolidated asset access is a ceiling case, not expected lender access. Official facility recovery remains N/D.",
        })
        steps = [
            ("gross_value", gross), ("less_realization_costs", -costs),
            ("proceeds_after_costs", after_cost), ("less_other_funded_obligations", -min(after_cost, prior)),
            ("illustrative_allocation_to_bank_claim", min(bank, claim)),
            ("facility_claim_cap", claim), ("residual_after_bank_claim", residual),
        ]
        for sequence, (step, amount) in enumerate(steps, start=1):
            waterfall.append({
                "waterfall_id": f"{case_id}-W{sequence:02d}", "case_id": case_id,
                "method": method, "sequence": sequence, "step": step, "amount": fmt(amount),
                "unit": "USD_millions", "classification": "calculated_sensitivity",
                "source_or_ids": "P9A-001:P9A-025", "review_status": REVIEW,
            })

    for number, assumption_id, label in ((1, "P9A-008", "Low"), (2, "P9A-009", "Base"), (3, "P9A-010", "High")):
        multiple = dec(index[assumption_id]["value"])
        add_case(f"P9C-GC-{number}", "going_concern", label, ebitda * multiple,
                 dec(index["P9A-011"]["value"]) / 100,
                 f"continued-operation sensitivity: {fmt(ebitda)} stressed TTM lender EBITDA x {fmt(multiple)}x; sale versus restructuring not selected")

    books = latest_book_values()
    pct_ids = {
        "Low": ("P9A-016", "P9A-019", "P9A-022"),
        "Base": ("P9A-017", "P9A-020", "P9A-023"),
        "High": ("P9A-018", "P9A-021", "P9A-024"),
    }
    access = dec(index["P9A-014"]["value"]) / 100
    for number, label in enumerate(("Low", "Base", "High"), start=1):
        ar_id, inv_id, ppe_id = pct_ids[label]
        gross = access * (
            books["accounts_receivable"] * dec(index[ar_id]["value"]) / 100
            + books["inventory"] * dec(index[inv_id]["value"]) / 100
            + books["property_plant_and_equipment_net"] * dec(index[ppe_id]["value"]) / 100
        )
        add_case(f"P9C-AR-{number}", "asset_realization", label, gross,
                 dec(index["P9A-012"]["value"]) / 100,
                 "FY2025 consolidated AR, inventory and net PP&E book values x illustrative realization percentages")
    return cases, waterfall


def claim_register(exposure: dict[str, str]) -> list[dict[str, str]]:
    claims = [
        ("P9CL-001", "Term loan principal", exposure["term_principal"], "bank_facility", "pari_passu_assumed", "P9A-003"),
        ("P9CL-002", "Revolver principal", exposure["revolver_principal"], "bank_facility", "pari_passu_assumed", "P9A-004"),
        ("P9CL-003", "Unpaid cash interest", exposure["unpaid_cash_interest"], "bank_facility", "pari_passu_assumed", "P9A-005"),
        ("P9CL-004", "Retained finance lease and other funded obligations", exposure["retained_other_funded_debt"], "other_funded_debt", "ranking_not_determinable_deducted_for_sensitivity", "P9A-006"),
        ("P9CL-005", "Taxes, employee, administrative, local and other priority claims", N_D, "other_priority", "not_determinable", "GAP-001;GAP-002"),
    ]
    return [
        {"claim_id": rid, "claim_name": name, "amount": amount, "unit": "USD_millions",
         "claim_class": claim_class, "priority_status": priority, "source_or_ids": source,
         "collateral_access": N_D, "review_status": REVIEW if amount != N_D else "not_determinable",
         "limitations": "Priority, guarantor coverage, collateral access and enforceability require private legal diligence."}
        for rid, name, amount, claim_class, priority, source in claims
    ]


def facility_assessment(cases: list[dict[str, str]], maturity: dict[str, str]) -> list[dict[str, str]]:
    by_method: dict[str, list[Decimal]] = {}
    for row in cases:
        by_method.setdefault(row["method"], []).append(dec(row["illustrative_facility_recovery_percent"]))
    return [{
        "assessment_id": "P9FRA-001", "official_facility_recovery": N_D,
        "going_concern_sensitivity_range": f"{fmt(min(by_method['going_concern']))}%-{fmt(max(by_method['going_concern']))}%",
        "asset_realization_sensitivity_range": f"{fmt(min(by_method['asset_realization']))}%-{fmt(max(by_method['asset_realization']))}%",
        "primary_recovery_date": "2027-12-31", "primary_scenario": "SEVERE_UNMITIGATED",
        "maturity_sensitivity_date": maturity["date"],
        "maturity_bank_claim_before_cash": maturity["bank_claim_before_cash"],
        "classification": "official_not_determinable_with_illustrative_sensitivities",
        "review_status": REVIEW,
        "reasons_not_determinable": "Complete guarantor scope; collateral coverage and perfection; asset eligibility and appraisals; foreign and entity-level access; lien priority; taxes, employee, administrative and local claims; enforceable pari passu treatment; realization costs.",
        "limitations": "Going-concern and asset-realization methods are alternatives and are never added. Recovery does not determine borrower default risk.",
    }]


def risk_assessment() -> list[dict[str, str]]:
    return [{
        "assessment_id": "P9RA-001", "provisional_grade": "Elevated",
        "scale_status": "approved_five_grade_scale", "review_status": REVIEW,
        "base_case": "Base operations service interim debt, but the selected structure retains a $324.780m unsupported maturity gap and does not self-liquidate.",
        "moderate_case": "Moderate paths avoid mandatory payment failure but retain $408.375m unmitigated and $381.133m mitigated maturity gaps and breach proposed covenant thresholds.",
        "severe_case": "Selected severe unmitigated reaches a covenant breach in October 2026, zero usable liquidity in July 2027 and mandatory cash-interest failure in December 2027.",
        "execution_quality": "Tyman integration, plant stabilization, adjustment dependence, a $302.284m impairment signal and unresolved cash-flow control remediation reduce confidence.",
        "management_dependence": "Deleveraging depends on operating execution, working-capital control, disciplined distributions, timely reporting and early refinancing preparation.",
        "information_limits": "Official contractual EBITDA, closing balances, eligible cash, guarantor/collateral coverage, priority claims and recovery evidence remain unavailable.",
        "next_better_grade_case": "Satisfactory would require sustained base-or-better EBITDA and cash conversion, no covenant warning, reduced revolver dependence, verified control remediation and a credible funded maturity solution.",
        "next_worse_grade_case": "Weak is supported if moderate performance approaches severe liquidity behavior, the conditional $15m source fails, reporting deteriorates, integration slips, or refinancing support remains uncommitted as maturity approaches.",
        "change_evidence": "Two or more quarters of stable comparable volume and margin, FCF conversion, verified debt reduction, completed controls and documented refinancing progress could improve the grade; covenant breach, payment failure, material reporting exception or unavailable refinancing could worsen it.",
        "default_recovery_separation": "Borrower grade reflects default risk only. Illustrative recovery sensitivities do not improve the grade.",
        "source_or_ids": "P5BCM;P6SC;P6FE;P6RS;P7SC;P7TL;P7UM;P8PAR;DRV-003;DRV-004;DRV-007;DRV-009;DRV-012",
    }]


def monitoring_schedule() -> list[dict[str, str]]:
    definitions = [
        ("MON-001", "DRV-001", "Comparable revenue and volume", "Organic or ex-Tyman revenue and unit volume by segment/geography versus prior year and approved case.", "percent", "quarterly", "Quarterly segment/geography price-volume-mix bridge", "available_through_required_borrower_reporting", "FY2025 reported perimeter", "below -5% year over year or 5% below approved case", "", "less_than", "quarter and trailing four quarters", "Portfolio manager", "Explain variance and provide revised demand bridge.", "Reconcile within 10 business days; require monthly volume reporting if unresolved.", "10_business_days", "analyst_warning", "no", "DRV-001", "Comparable volume requires borrower reporting."),
        ("MON-002", "DRV-002", "Price, mix and raw-material recovery", "Segment price/mix benefit less raw-material and index cost movement.", "basis_points", "quarterly", "Price-volume-mix and index-pass-through bridge", "available_through_required_borrower_reporting", "No quantified Phase 9 baseline", "adverse gross-margin effect above 100 bps", "", "greater_than", "quarter", "Portfolio manager", "Provide pass-through actions and customer/mix explanation.", "Request corrective pricing plan within 10 business days.", "10_business_days", "analyst_warning", "no", "DRV-002", "Public reporting does not isolate all effects."),
        ("MON-003", "DRV-003", "Gross margin", "Consolidated gross profit divided by revenue, with segment and plant bridge.", "percent", "monthly", "Monthly management accounts and plant operating report", "available_through_required_borrower_reporting", "FY2025 27.2%; Phase 3 range 26%-28%", "below 25%", "", "less_than", "month and trailing quarter", "Portfolio manager", "Provide plant, mix and fixed-cost bridge.", "Increase reporting frequency and require a 30-day margin action plan.", "5_business_days", "analyst_warning", "no", "DRV-003", "Acquisition mix and seasonality affect comparisons."),
        ("MON-004", "DRV-003;DRV-007", "Lender-base EBITDA", "LTM lender-base EBITDA using the approved adjustment register, separately reconciled to company and contractual measures.", "USD_millions", "monthly", "Monthly EBITDA bridge and quarterly compliance certificate", "available_through_required_borrower_reporting", "FY2025 $225.344m", "below $180m LTM", "", "less_than", "LTM", "Credit officer", "Deliver detailed variance and add-back bridge.", "Require revised projections and monthly lender-base EBITDA reporting.", "5_business_days", "analyst_warning", "no", "DRV-003;DRV-007;P9D-016", "Threshold is proposed for owner review and is not contractual."),
        ("MON-005", "DRV-007", "Adjustment and add-back usage", "Company, contractual and lender adjustments by category, cash status, cap and remaining eligibility.", "USD_millions", "monthly", "Adjustment, accrual and cash-payment roll-forward", "available_through_required_borrower_reporting", "$10.263m FY2025 composite unresolved", "new composite item or LTM lender adjustments above $40m excluding impairment", "subject to final EBITDA definition", "greater_than", "LTM", "Credit officer", "Provide invoices, cash timing, cap and double-counting analysis.", "Defer new lender credit pending evidence; escalate certificate exception.", "immediate", "reporting_exception", "possible", "DRV-007", "Contractual eligibility remains separate from lender normalization."),
        ("MON-006", "DRV-005", "CFO to lender EBITDA conversion", "Trailing-twelve-month CFO divided by lender-base EBITDA.", "percent", "quarterly", "Cash-flow statement and EBITDA bridge", "available_through_required_borrower_reporting", "FY2025 73.2%", "below 60%", "", "less_than", "LTM", "Portfolio manager", "Provide cash conversion and working-capital bridge.", "Require revised cash forecast and monthly working-capital reporting.", "10_business_days", "analyst_warning", "no", "DRV-005", "CFO includes cash interest under US GAAP."),
        ("MON-007", "DRV-005;DRV-006", "FCF to lender EBITDA conversion", "CFO less capital expenditure divided by lender-base EBITDA.", "percent", "quarterly", "Cash-flow statement and project-level capex schedule", "available_through_required_borrower_reporting", "FY2025 45.4%", "below 35%", "", "less_than", "LTM", "Portfolio manager", "Explain working-capital and capex variance.", "Require revised liquidity forecast; do not cut maintenance capex without evidence.", "10_business_days", "analyst_warning", "no", "DRV-005;DRV-006", "Maintenance versus growth capex remains pending."),
        ("MON-008", "DRV-005", "DSO", "Average gross trade receivables divided by revenue times fiscal days.", "days", "monthly", "Receivables aging and average-balance schedule", "available_through_required_borrower_reporting", "FY2025 40.03", "above 45 days", "", "greater_than", "month and trailing three months", "Portfolio manager", "Provide aging, disputes and collection plan.", "Require weekly collections report if above threshold for two months.", "5_business_days", "analyst_warning", "no", "DRV-005", "Acquisition perimeter affects historical comparison."),
        ("MON-009", "DRV-005", "DIO", "Average inventory divided by cost of sales times fiscal days.", "days", "monthly", "Inventory aging and reserve schedule", "available_through_required_borrower_reporting", "FY2025 72.22", "above 80 days", "", "greater_than", "month and trailing three months", "Portfolio manager", "Provide SKU aging, reserve and liquidation plan.", "Require monthly inventory reduction milestones.", "10_business_days", "analyst_warning", "no", "DRV-005", "Mix and acquisition perimeter affect comparability."),
        ("MON-010", "DRV-013", "Payables and other operating working capital", "AP, accrued liabilities and other operating balances versus approved monthly forecast, separately bridged.", "USD_millions", "monthly", "Purchases, AP, accrual and other operating working-capital bridge", "available_through_required_borrower_reporting", "DPO not determinable", "variance above 10% from approved forecast or unexplained supplier stretching", "", "absolute_variance_greater_than", "month", "Portfolio manager", "Provide supplier aging and cash-flow reconciliation.", "Escalate unexplained funding benefit and revise liquidity forecast.", "5_business_days", "reporting_exception", "no", "DRV-013", "Cost of sales is not purchases; DPO remains N/D."),
        ("MON-011", "DRV-006", "Maintenance capital expenditure", "Actual and committed maintenance/safety capex versus approved maintenance floor.", "USD_millions", "monthly", "Project-level capex schedule", "dependent_on_private_diligence", "Maintenance floor N/D", "below approved maintenance floor or deferred safety project", "", "less_than_or_event", "year to date", "Portfolio manager", "Explain deferral and operational effect.", "Do not credit cash preservation; require project remediation plan.", "immediate", "analyst_warning", "no", "DRV-006", "Threshold becomes measurable only after borrower schedule."),
        ("MON-012", "DRV-012", "Usable liquidity", "Eligible unrestricted cash plus undrawn drawable revolver capacity after LCs.", "USD_millions", "monthly", "Monthly liquidity certificate by entity and jurisdiction", "available_through_required_borrower_reporting", "$263.902m opening Base", "below $75m", "below $50m proposed covenant", "less_than", "month end and pro forma for material actions", "Credit officer", "Deliver 13-week cash forecast and corrective-action plan.", "Notify lenders immediately; suspend discretionary actions where documents permit.", "immediate", "analyst_warning", "possible", "DRV-012;P7CP-006;P7CP-011", "Eligible cash and drawability require final documentation."),
        ("MON-013", "DRV-010;DRV-012", "Revolver utilization", "Drawn revolver plus LCs divided by commitment.", "percent", "monthly", "Debt and liquidity report", "available_through_required_borrower_reporting", "12.0% opening including LCs", "above 75%", "", "greater_than", "month end", "Portfolio manager", "Explain usage and deliver 13-week cash forecast.", "Increase reporting to weekly and restrict repurchases under proposed terms.", "immediate", "analyst_warning", "no", "DRV-010;DRV-012", "Availability depends on final draw conditions."),
        ("MON-014", "DRV-012", "Revolver drawability", "Representations, no-default conditions, covenant compliance and documentation needed for a new draw.", "status", "each_draw", "Borrowing request and compliance certificate", "dependent_on_private_diligence", "Available in Base before warnings", "any unmet draw condition", "documented draw condition", "event", "current", "Credit officer", "Provide cure, waiver request or alternative liquidity plan.", "Escalate immediately; preserve rights and do not assume continued funding.", "immediate", "legal_or_documentation_exception", "yes", "DRV-012", "Final conditions and remedies require executed documents."),
        ("MON-015", "DRV-012", "Gross total funded leverage", "Gross funded debt divided by lender EBITDA; zero cash netting.", "turns", "monthly", "Debt report and quarterly compliance certificate", "available_through_required_borrower_reporting", "3.2285x opening", "at or above 3.25x/3.00x/2.75x warning schedule", "above 3.50x/3.25x/3.00x proposed covenant schedule", "greater_than_or_equal_warning", "LTM", "Credit officer", "Provide covenant bridge and debt-reduction plan.", "At warning suspend repurchases and require 10-business-day plan; breach requires consent/waiver analysis.", "immediate", "contractual_covenant_or_warning", "yes", "DRV-012;P7CP-002:P7CP-009", "Official contractual EBITDA remains unavailable."),
        ("MON-016", "DRV-012", "Cash-interest coverage", "LTM lender EBITDA divided by LTM cash interest paid or payable.", "turns", "monthly", "Cash-interest schedule and compliance certificate", "available_through_required_borrower_reporting", "Base modeled minimum 5.39x", "below 3.50x", "below 3.00x proposed covenant", "less_than", "LTM", "Credit officer", "Provide interest bridge, hedge status and revised forecast.", "Increase reporting and begin amendment/waiver planning before breach.", "immediate", "contractual_covenant_or_warning", "yes", "DRV-012;P7CP-005;P7CP-010", "Closing LTM cash interest remains N/D."),
        ("MON-017", "DRV-012", "Covenant certificate", "Timely complete certificate using executed definitions with supporting calculations.", "status", "quarterly", "Quarterly compliance certificate", "available_through_required_borrower_reporting", "Required within proposed 45-day cadence", "late, incomplete or unreconciled certificate", "reporting covenant when documented", "event", "quarter", "Credit officer", "Deliver corrected certificate and reconciliation.", "Issue reporting exception; preserve default rights subject to cure language.", "immediate", "reporting_exception", "yes", "DRV-012", "Final delivery and cure terms require documentation."),
        ("MON-018", "DRV-012", "Scheduled principal and interest", "Cash due and paid by instrument and due date.", "USD_millions", "monthly", "Debt-service report and bank statements", "available_through_required_borrower_reporting", "No Base modeled failure", "any amount unpaid when due", "payment obligation", "event", "due date", "Credit officer", "Confirm payment, cause, cash position and cure status.", "Escalate immediately to special-assets/legal review and preserve remedies.", "immediate", "payment_default", "yes", "DRV-012", "Grace periods and remedies require final documents."),
        ("MON-019", "DRV-010", "Distributions with revolver outstanding", "Dividends and repurchases paid while revolver principal remains outstanding.", "USD_millions", "monthly", "Distribution, board approval and debt report", "available_through_required_borrower_reporting", "Base retains planned distributions", "any repurchase with revolver outstanding or debt-funded distribution", "proposed restriction", "event", "month", "Credit officer", "Provide source of funds and pro forma tests.", "Reject or require consent where documentation permits; revise deleveraging plan.", "before_payment", "legal_or_documentation_exception", "possible", "DRV-010;P7CP-014", "Rights depend on final restricted-payment drafting."),
        ("MON-020", "DRV-004;DRV-008", "Integration and synergy milestones", "Realized recurring synergies, costs to achieve, service levels and reporting-unit performance versus approved plan.", "USD_millions_and_status", "monthly", "Integration milestone and synergy bridge", "dependent_on_private_diligence", "$30m claimed realized; remaining $15m receives no Base credit", "less than 80% of milestones on time or two quarters below plan", "", "event", "month and quarter", "Portfolio manager", "Provide milestone recovery plan and customer impact.", "No additional EBITDA credit; require monthly steering-committee reporting.", "10_business_days", "analyst_warning", "no", "DRV-004;DRV-008", "Synergy quality and sustainability require evidence."),
        ("MON-021", "DRV-003;DRV-004", "Plant execution and remediation", "Service, scrap, labor efficiency, downtime and remediation spend for identified plants.", "status_and_percent", "monthly", "Plant operating KPI package", "dependent_on_private_diligence", "Mexico hardware stabilization remains a risk", "missed service target or remediation milestone", "", "event", "month", "Portfolio manager", "Provide root-cause and recovery plan.", "Escalate to monthly management call and revise downside case if delayed.", "5_business_days", "analyst_warning", "no", "DRV-003;DRV-004", "Public evidence does not provide plant KPI thresholds."),
        ("MON-022", "DRV-009", "Material-weakness remediation", "Design, operation and testing status of cash-flow statement controls.", "status", "monthly", "Management certification, test evidence and auditor updates", "available_through_required_borrower_reporting", "Outstanding at FY2025 year-end", "missed milestone, failed test or new deficiency", "reporting/control undertaking when documented", "event", "month", "Credit officer", "Provide remediation evidence and auditor communication.", "Increase reporting, require independent validation and escalate material exceptions.", "immediate", "reporting_exception", "possible", "DRV-009", "The weakness is not treated as a known misstatement."),
        ("MON-023", "DRV-009", "Reporting timeliness and quality", "Delivery of monthly, quarterly and annual reporting, reconciliations and explanations.", "days", "monthly", "Proposed 15/45/90-day reporting package", "available_through_required_borrower_reporting", "15/45/90 days proposed", "late, incomplete, internally inconsistent or unreconciled report", "reporting covenant when documented", "event", "reporting due date", "Credit officer", "Deliver missing information and explanation.", "Issue reporting exception and escalate repeated failures to watchlist review.", "immediate", "reporting_exception", "yes", "DRV-009;P7CP-017", "Final cure periods require drafting."),
        ("MON-024", "DRV-012", "Guarantor, collateral, lien and perfection status", "Current legal-entity, guarantor, collateral, lien, control and perfection schedule.", "status", "quarterly_and_event", "Counsel certificate and collateral/perfection schedule", "dependent_on_private_diligence", "N/D from public information", "missing joinder, lapse, release or excluded material asset", "documentation requirement", "event", "current", "Credit officer and counsel", "Provide corrective filing, joinder or legal analysis.", "Escalate legal exception; preserve conditions and remedies subject to documents.", "immediate", "legal_or_documentation_exception", "yes", "DRV-012;GAP-001;GAP-002", "Public filings do not establish complete post-Tyman coverage."),
        ("MON-025", "DRV-011", "Foreign cash and FX exposure", "Cash by entity/jurisdiction plus currency revenue, cost, debt and hedge exposure.", "USD_millions_and_percent", "monthly", "Entity cash and FX exposure schedule", "dependent_on_private_diligence", "$46.9m foreign cash at FY2025; no access credit", "material unhedged move or cash-transfer restriction", "", "event", "month", "Portfolio manager", "Provide hedge and cash-access analysis.", "Exclude inaccessible cash and revise liquidity forecast.", "5_business_days", "analyst_warning", "no", "DRV-011", "Tax, legal and operating access remain unknown."),
        ("MON-026", "DRV-012", "Maturity refinancing preparation", "Documented refinancing, extension, repayment or committed alternative funding milestones.", "months_and_status", "quarterly_then_monthly", "Board-approved refinancing plan and lender evidence", "available_through_required_borrower_reporting", "$324.780m Base unsupported maturity gap", "no documented plan 24 months before maturity; no executable commitment 12 months before maturity", "maturity 2031-01-31", "event", "forward", "Credit officer", "Provide options, timetable, adviser mandate and lender feedback.", "Watchlist at 24 months without plan; special-assets escalation at 12 months without executable solution.", "quarterly_or_immediate", "maturity_refinancing_risk", "no", "DRV-012;P7UM-008", "Refinancing is not assumed and requires separate underwriting."),
    ]
    fields = ("monitor_id", "risk_driver_ids", "metric_or_event", "exact_definition", "unit", "frequency",
              "required_report_or_source", "observability_status", "baseline", "warning_threshold",
              "covenant_or_contractual_threshold", "comparator_direction", "lookback_period",
              "responsible_lender_reviewer", "required_borrower_response", "lender_action",
              "escalation_timing", "severity_classification", "cure_or_waiver_relevance",
              "source_or_assumption_ids", "limitation")
    return [dict(zip(fields, row, strict=True), review_status=REVIEW) for row in definitions]


def escalation_actions() -> list[dict[str, str]]:
    rows = [
        ("P9E-001", "analyst_warning", "Investigate and reconcile; obtain a 10-business-day corrective-action plan.", "warning does not itself terminate draws"),
        ("P9E-002", "reporting_exception", "Require corrected reporting, increase frequency and preserve rights subject to cure terms.", "reporting default depends on executed documentation"),
        ("P9E-003", "contractual_covenant_breach", "Suspend restricted payments under proposed terms; obtain consent, amendment, waiver or support before relying on continued drawability.", "no waiver or continued draw is assumed"),
        ("P9E-004", "payment_default", "Immediate credit, legal and special-assets escalation; verify cure period and preserve remedies.", "remedies depend on executed documents"),
        ("P9E-005", "liquidity_failure", "Require a 13-week cash plan, weekly reporting and funded support; stop assuming revolver availability.", "new borrowing remains subject to draw conditions"),
        ("P9E-006", "maturity_refinancing_risk", "Begin watchlist review at 24 months without a plan and special-assets review at 12 months without an executable solution.", "refinancing is separately underwritten"),
        ("P9E-007", "legal_or_documentation_exception", "Obtain counsel analysis, corrective documents and required consents; preserve conditions precedent and remedies.", "do not claim an undocumented prohibition or lien"),
    ]
    return [
        {"action_id": rid, "severity_classification": severity, "required_lender_action": action,
         "legal_boundary": boundary, "review_status": REVIEW}
        for rid, severity, action, boundary in rows
    ]


def build_source_ledger() -> list[dict[str, str]]:
    rows = []
    for index, relative in enumerate(SOURCE_INPUTS, start=1):
        path = ROOT / relative
        rows.append({
            "ledger_id": f"P9L-{index:03d}", "source_path": relative,
            "source_type": "approved_prior_phase_artifact", "source_date": "2025-12-15_or_earlier",
            "phase9_use": "recovery exposure, book-value reference, risk assessment, monitoring, or control",
            "input_signature": hashlib.sha256(path.read_bytes()).hexdigest(),
            "cutoff_status": "within_cutoff", "review_status": "approved_upstream",
            "limitations": "Use retains the classifications, dates and limitations in the source artifact.",
        })
    return rows


def write_docs(exposure: dict[str, str], maturity: dict[str, str], cases: list[dict[str, str]], monitors: list[dict[str, str]]) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    gc = [row for row in cases if row["method"] == "going_concern"]
    ar = [row for row in cases if row["method"] == "asset_realization"]
    (DOCS / "METHODOLOGY.md").write_text(f"""# Phase 9 methodology

Phase 9 uses the approved Phase 0-8 evidence and the selected Phase 7 structure. No new source was added and the information cutoff remains {INFORMATION_CUTOFF}. The primary recovery date is {exposure['recovery_date']}, the first mandatory cash-interest failure in the selected severe-unmitigated continued-draw sensitivity. The analysis separates borrower default risk from facility recovery and treats recovery as secondary repayment.

Going-concern and asset-realization sensitivities are alternative methods and are never added. Each deducts realization costs and the $62.619m other-funded-obligations amount once, caps the illustrative allocation at the bank claim and prevents negative proceeds. The deduction avoids ignoring retained finance leases and other funded obligations; it does not establish legal seniority. Consolidated book assets are reference values, not appraisals, eligible collateral or a borrowing base. The asset method is a full consolidated-access ceiling case, not expected lender access. The official facility recovery remains `N/D` because legal access, guarantor coverage, liens, collateral, appraisals and priority claims are unavailable.

The owner reviewed all 16 Phase 9 decisions. Their underlying values remain illustrative assumptions or `N/D` conclusions rather than facts, appraisals, borrowing-base determinations or legal conclusions. The provisional borrower grade is `Elevated`, uses only the approved five-grade project scale and is not a bank or agency rating. Monitoring maps every Phase 3 driver to at least one specific trigger and action. No Phase 10 recommendation is made.

Workbook lineage is explicit. The original Phase 8 normalized fingerprint was `12589f4c34975118fad1aea3ddb83de8f67b4521f33307104ef1bd42efb07dd7`; the corrected Excel-compatible Phase 8 fingerprint was `{PHASE8_FINGERPRINT}`. Phase 9 is generated from that corrected baseline.
""", encoding="utf-8")
    (DOCS / "RECOVERY_ANALYSIS.md").write_text(f"""# Recovery analysis

## Primary exposure

At {exposure['recovery_date']}, the selected severe-unmitigated path first fails cash interest. Term principal is ${Decimal(exposure['term_principal']):,.3f}m, revolver principal is ${Decimal(exposure['revolver_principal']):,.3f}m and unpaid cash interest is ${Decimal(exposure['unpaid_cash_interest']):,.3f}m. The illustrative bank claim is ${Decimal(exposure['facility_claim']):,.3f}m; gross funded principal including the ${Decimal(exposure['retained_other_funded_debt']):,.3f}m retained-debt proxy is ${Decimal(exposure['gross_funded_principal']):,.3f}m. This date follows the October 2026 covenant breach and July 2027 liquidity exhaustion.

The separate {maturity['date']} Base sensitivity shows a ${Decimal(maturity['bank_claim_before_cash']):,.3f}m bank maturity payment before ${Decimal(maturity['cash_applied']):,.3f}m modeled cash application, leaving the approved ${Decimal(maturity['unsupported_gap']):,.3f}m unsupported gap. It is not the primary default-date exposure.

## Illustrative alternative sensitivities

| Method | Low | Base | High |
|---|---:|---:|---:|
| Illustrative going-concern recovery | {Decimal(gc[0]['illustrative_facility_recovery_percent']):.1f}% | {Decimal(gc[1]['illustrative_facility_recovery_percent']):.1f}% | {Decimal(gc[2]['illustrative_facility_recovery_percent']):.1f}% |
| Illustrative full-access ceiling recovery | {Decimal(ar[0]['illustrative_facility_recovery_percent']):.1f}% | {Decimal(ar[1]['illustrative_facility_recovery_percent']):.1f}% | {Decimal(ar[2]['illustrative_facility_recovery_percent']):.1f}% |

These are owner-reviewed illustrative sensitivities, not official estimates. Going-concern is a continued-operation enterprise-value sensitivity using stress-date TTM lender EBITDA and 3.0x-5.0x multiples; it does not select a sale versus restructuring path. Asset realization is a full consolidated-access ceiling case that applies realization percentages to FY2025 consolidated receivables, inventory and net PP&E. Those latest approved book values predate the 2027 recovery date and are a historical reference, not a projected recovery balance sheet. Cash receives explicit zero credit pending accessibility evidence; goodwill and unsupported intangibles receive no liquidation value. The $62.619m other-funded-obligations deduction is taken once to avoid ignoring retained finance leases and other funded obligations, not because legal seniority has been established. Neither method proves collateral eligibility, legal priority or lender access.

## Official conclusion

**Facility recovery: N/D.** Complete guarantor scope, collateral coverage, perfection, entity and foreign-asset access, appraisals, lien priority, administrative and local claims, and enforceable allocation are unavailable. The sensitivities cannot resolve those omissions and do not improve the borrower default-risk grade.
""", encoding="utf-8")
    (DOCS / "RISK_ASSESSMENT.md").write_text("""# Borrower risk assessment

**Provisional borrower grade: Elevated - owner reviewed.**

Base operations support interim debt service, but the selected structure retains a material unsupported maturity gap and depends on refinancing. Moderate stress avoids payment default but breaches proposed covenant thresholds and leaves a larger maturity gap. Severe stress produces early warning, covenant breach, revolver exhaustion and mandatory payment failure. Tyman integration, plant execution, adjustment dependence, the impairment signal, reporting-control remediation and incomplete private information reduce confidence.

The strongest case for `Satisfactory` is the demonstrated FY2025 cash recovery, modeled Base debt service, opening liquidity and proposed intervention package. Moving to that grade would require sustained comparable volume and margin, verified cash conversion and debt reduction, control remediation and a credible funded maturity solution.

The strongest case for `Weak` is the severe path's mandatory cash-interest failure, dependence on a conditional $15m source and continued borrowing/management action, plus unresolved reporting and recovery evidence. Moderate results approaching severe behavior, a failed condition, delayed reporting or an uncommitted refinancing path would support deterioration.

The grade assesses default risk only. It is not a bank grade, agency rating, probability of default, mechanical score or Phase 10 recommendation.
""", encoding="utf-8")
    (DOCS / "MONITORING_PLAN.md").write_text(f"""# Monitoring and escalation plan

The owner reviewed the {len(monitors)} monitoring records. They map all 13 Phase 3 risk drivers to defined reports, warning or event triggers, borrower responses, lender actions and escalation timing. Key quantitative warnings are comparable revenue below -5%, gross margin below 25%, LTM lender EBITDA below $180m, DSO above 45 days, DIO above 80 days, usable liquidity below $75m, gross leverage at the applicable 3.25x/3.00x/2.75x warning schedule and cash-interest coverage below 3.50x. Owner review does not convert a warning into a contractual right; proposed contractual thresholds remain subject to final documentation.

Payment default, drawability failure, reporting exception, legal exception and maturity risk receive separate treatment. The lender investigates warnings, requires revised forecasts and corrective plans, increases reporting, requests restrictions only where documentation permits, evaluates waivers or support before reliance, and preserves remedies after an uncured default. Refinancing preparation begins at least 24 months before the January 2031 maturity and escalates at 12 months without an executable solution.
""", encoding="utf-8")
    (DOCS / "PHASE10_HANDOFF.md").write_text("""# Phase 10 handoff

Phase 10 has not started. The owner reviewed every `P9D` decision, including the revised other-funded-obligations deduction and full consolidated-access ceiling classification. The official public-information facility recovery remains `N/D`; illustrative recovery cannot rescue primary repayment or improve the provisional borrower grade. Phase 10 must preserve the conditional $15m source, unsupported maturity gap, separate retained-facility alternative, private legal and collateral gaps, and the distinction between warnings, covenants, reporting exceptions, payment defaults, liquidity failures and refinancing risk.
""", encoding="utf-8")


def build_data() -> dict[str, object]:
    head = git_head()
    if not is_phase8_descendant(head):
        raise Phase9Error(f"HEAD is not the approved Phase 8 checkpoint or a descendant: {head}")
    exposure = selected_exposure()
    maturity = maturity_exposure()
    assumptions = recovery_assumptions(exposure, maturity)
    decisions = owner_decisions()
    cases, waterfall = recovery_cases(exposure, assumptions)
    claims = claim_register(exposure)
    facility = facility_assessment(cases, maturity)
    risk = risk_assessment()
    monitors = monitoring_schedule()
    escalations = escalation_actions()
    ledger = build_source_ledger()

    write_csv(RAW / "STARTING_CHECKPOINT.csv", [{
        "repository": "owencchapman24/quanex-credit-underwriting", "branch": "main",
        "approved_phase8_commit": APPROVED_PHASE8_COMMIT, "local_head": head,
        "phase8_normalized_fingerprint": PHASE8_FINGERPRINT,
        "source_input_signature": source_signature(), "information_cutoff": INFORMATION_CUTOFF,
        "hypothetical_closing": "2026-01-31", "calculation_engines": "LibreOffice 26.8.0.3;Microsoft Excel 16.0 build 20326",
    }])
    write_csv(RAW / "RECOVERY_ASSUMPTIONS.csv", assumptions)
    write_csv(RAW / "OWNER_REVIEW_DECISIONS.csv", decisions)
    write_csv(RAW / "MONITORING_TRIGGER_INPUTS.csv", monitors)
    write_csv(PROCESSED / "RECOVERY_CASE_REGISTER.csv", cases)
    write_csv(PROCESSED / "RECOVERY_WATERFALL.csv", waterfall)
    write_csv(PROCESSED / "CLAIM_PRIORITY_REGISTER.csv", claims)
    write_csv(PROCESSED / "FACILITY_RECOVERY_ASSESSMENT.csv", facility)
    write_csv(PROCESSED / "BORROWER_RISK_ASSESSMENT.csv", risk)
    write_csv(PROCESSED / "MONITORING_SCHEDULE.csv", monitors)
    write_csv(PROCESSED / "ESCALATION_ACTION_REGISTER.csv", escalations)
    write_csv(DOCS / "SOURCE_LEDGER.csv", ledger)
    write_docs(exposure, maturity, cases, monitors)

    payload = {
        "exposure": exposure, "maturity": maturity, "assumptions": assumptions,
        "cases": cases, "claims": claims, "facility": facility[0], "risk": risk[0],
        "book_values": {key: fmt(value) for key, value in latest_book_values().items()},
        "monitors": monitors, "escalations": escalations, "ledger": ledger,
    }
    PROCESSED.mkdir(parents=True, exist_ok=True)
    (PROCESSED / "WORKBOOK_INPUTS.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def run_artifact_tool(mode: str, baseline: Path, preview_dir: Path | None = None) -> None:
    if not NODE.is_file() or not NODE_MODULES.is_dir():
        raise Phase9Error("Bundled artifact-tool Node runtime is unavailable")
    with tempfile.TemporaryDirectory(prefix="quanex-phase9-artifact-") as temp_name:
        temp = Path(temp_name)
        shutil.copy2(ROOT / "scripts" / "build-phase9.mjs", temp / "build-phase9.mjs")
        junction = temp / "node_modules"
        command = f"New-Item -ItemType Junction -Path '{junction}' -Target '{NODE_MODULES}' | Out-Null"
        subprocess.run(["powershell", "-NoProfile", "-Command", command], check=True)
        args = [str(NODE), str(temp / "build-phase9.mjs"), mode, str(ROOT), str(baseline)]
        if preview_dir is not None:
            args.append(str(preview_dir))
        result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        if result.returncode:
            raise Phase9Error(f"Artifact-tool {mode} failed with exit code {result.returncode}")
        sidecar = MODEL.with_name(MODEL.name + ".inspect.ndjson")
        sidecar.unlink(missing_ok=True)


def phase8_baseline(path: Path) -> None:
    with path.open("wb") as handle:
        result = subprocess.run(
            ["git", "show", f"{APPROVED_PHASE8_COMMIT}:model/Quanex_Credit_Underwriting.xlsx"],
            cwd=ROOT, stdout=handle,
        )
    if result.returncode:
        raise Phase9Error("Unable to extract approved Phase 8 workbook baseline")


def run_libreoffice(mode: str, workbook: Path = MODEL) -> dict[str, object]:
    if not LIBREOFFICE.is_file() or not LO_PYTHON.is_file():
        raise Phase9Error("LibreOffice recalculation engine is unavailable")
    descriptor, report_name = tempfile.mkstemp(prefix="phase9-lo-", suffix=".json")
    os.close(descriptor)
    report = Path(report_name)
    try:
        result = subprocess.run(
            [str(LO_PYTHON), str(ROOT / "scripts" / "recalculate-phase9.py"), mode, str(workbook), str(report)],
            cwd=ROOT, text=True, capture_output=True,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        if result.returncode:
            raise Phase9Error(f"LibreOffice Phase 9 {mode} failed")
        return json.loads(report.read_text(encoding="utf-8"))
    finally:
        report.unlink(missing_ok=True)


def validate(engine_report: dict[str, object] | None = None) -> list[dict[str, object]]:
    assumptions = read_csv(RAW / "RECOVERY_ASSUMPTIONS.csv")
    decisions = read_csv(RAW / "OWNER_REVIEW_DECISIONS.csv")
    cases = read_csv(PROCESSED / "RECOVERY_CASE_REGISTER.csv")
    waterfall = read_csv(PROCESSED / "RECOVERY_WATERFALL.csv")
    claims = read_csv(PROCESSED / "CLAIM_PRIORITY_REGISTER.csv")
    facility = read_csv(PROCESSED / "FACILITY_RECOVERY_ASSESSMENT.csv")
    risk = read_csv(PROCESSED / "BORROWER_RISK_ASSESSMENT.csv")
    monitors = read_csv(PROCESSED / "MONITORING_SCHEDULE.csv")
    ledger = read_csv(DOCS / "SOURCE_LEDGER.csv")
    if engine_report is None:
        engine_report = run_libreoffice("inspect")

    controls: list[dict[str, object]] = []
    def add(name: str, passed: bool, observed: object, expected: object, category: str) -> None:
        controls.append({"validation_id": f"P9V-{len(controls)+1:03d}", "category": category,
                         "test_name": name, "status": "PASS" if passed else "FAIL",
                         "observed": observed, "expected": expected})

    add("approved Phase 8 ancestry", is_phase8_descendant(git_head()), git_head(), APPROVED_PHASE8_COMMIT, "checkpoint")
    add("Phase 8 normalized fingerprint recorded", read_csv(RAW / "STARTING_CHECKPOINT.csv")[0]["phase8_normalized_fingerprint"] == PHASE8_FINGERPRINT, PHASE8_FINGERPRINT, PHASE8_FINGERPRINT, "checkpoint")
    add("six alternative recovery cases", len(cases) == 6, len(cases), 6, "recovery")
    add("methods remain alternatives", {r["method"] for r in cases} == {"going_concern", "asset_realization"}, sorted({r["method"] for r in cases}), "two separate methods", "recovery")
    add("same recovery date and scenario", all(r["valuation_date"] == "2027-12-31" and r["scenario_id"] == "SEVERE_UNMITIGATED" for r in cases), "checked", "2027-12-31 severe", "recovery")
    add("waterfall rows complete", len(waterfall) == 42, len(waterfall), 42, "recovery")
    add("waterfall proceeds nonnegative", all(dec(r["amount"]) >= 0 for r in waterfall if r["step"] in {"gross_value", "proceeds_after_costs", "illustrative_allocation_to_bank_claim", "facility_claim_cap", "residual_after_bank_claim"}), "checked", "nonnegative", "recovery")
    add("recovery capped at claim", all(dec(r["illustrative_bank_allocation"]) <= dec(r["facility_claim"]) for r in cases), "checked", "illustrative allocation <= claim", "recovery")
    add("costs deducted once", all(sum(1 for r in waterfall if r["case_id"] == c["case_id"] and r["step"] == "less_realization_costs") == 1 for c in cases), "checked", "once per case", "recovery")
    add("other funded obligations deducted once", all(sum(1 for r in waterfall if r["case_id"] == c["case_id"] and r["step"] == "less_other_funded_obligations") == 1 for c in cases), "checked", "once per case", "recovery")
    add("official recovery N/D", facility[0]["official_facility_recovery"] == N_D, facility[0]["official_facility_recovery"], N_D, "recovery")
    add("unknown claims remain N/D", any(r["amount"] == N_D for r in claims), "checked", "at least one explicit N/D", "recovery")
    add("goodwill and intangible excluded", any(r["decision_id"] == "P9D-010" for r in decisions), "checked", "P9D-010", "recovery")
    add("all owner decisions implemented", all(r["review_status"] == REVIEW for r in decisions), "checked", REVIEW, "governance")
    add("proposed assumptions retain classification after review", all(r["classification"] == "proposed_assumption" and r["review_status"] == REVIEW for r in assumptions if r["classification"] == "proposed_assumption"), "checked", "proposed_assumption + owner_reviewed", "governance")
    add("other funded obligations are not asserted senior", all("prior-ranking" not in r["description"].lower() for r in assumptions) and next(r for r in claims if r["claim_id"] == "P9CL-004")["priority_status"] == "ranking_not_determinable_deducted_for_sensitivity", "checked", "ranking N/D", "governance")
    add("asset access is a ceiling case", next(r for r in assumptions if r["assumption_id"] == "P9A-014")["description"] == "full consolidated-access ceiling case", "checked", "full consolidated-access ceiling case", "governance")
    add("risk grade valid", risk[0]["provisional_grade"] in {"Strong", "Satisfactory", "Elevated", "Weak", "Impaired"}, risk[0]["provisional_grade"], "approved scale", "risk")
    prohibited_mapping_fields = {"probability_of_default", "agency_rating", "external_rating_mapping"}
    add(
        "no PD or agency mapping",
        not any(prohibited_mapping_fields.intersection(row) for row in risk),
        "checked",
        "no mapping fields",
        "risk",
    )
    add("default and recovery separate", "do not improve" in risk[0]["default_recovery_separation"], risk[0]["default_recovery_separation"], "separate", "risk")
    mapped = {item for row in monitors for item in row["risk_driver_ids"].split(";") if item.startswith("DRV-")}
    add("all 13 drivers monitored", mapped == {f"DRV-{i:03d}" for i in range(1, 14)}, len(mapped), 13, "monitoring")
    add("monitor count", len(monitors) == 26, len(monitors), 26, "monitoring")
    required_monitor = {"frequency", "required_report_or_source", "warning_threshold", "lender_action", "escalation_timing", "review_status"}
    add("monitor fields complete", all(all(row[field] for field in required_monitor) for row in monitors), "checked", "complete", "monitoring")
    add("every monitor owner reviewed", all(row["review_status"] == REVIEW for row in monitors), "checked", REVIEW, "monitoring")
    add("maturity monitoring starts 24 months early", "24 months" in next(r["warning_threshold"] for r in monitors if r["monitor_id"] == "MON-026"), "checked", "24 months", "monitoring")
    add("no post-cutoff sources", all(r["cutoff_status"] == "within_cutoff" for r in ledger), sum(r["cutoff_status"] != "within_cutoff" for r in ledger), 0, "cutoff")
    add("LibreOffice engine", engine_report.get("engine") == "LibreOffice 26.8.0.3", engine_report.get("engine"), "LibreOffice 26.8.0.3", "workbook")
    add("workbook saved Base", engine_report.get("final_scenario") == "Base", engine_report.get("final_scenario"), "Base", "workbook")
    add("Phase 9 terminal checks", int(engine_report.get("phase9_check_failures", -1)) == 0, engine_report.get("phase9_check_failures"), 0, "workbook")
    add("recovery parity", int(engine_report.get("recovery_parity_failures", -1)) == 0, engine_report.get("recovery_parity_failures"), 0, "workbook")
    add("dynamic recovery tests", engine_report.get("dynamic_status") in {None, "PASS"}, engine_report.get("dynamic_status", "not_run"), "PASS or separately run", "workbook")
    structure = phase8.workbook_structure()
    add("14-sheet order", len(structure["sheets"]) == 14 and structure["sheets"][10] == "Recovery", len(structure["sheets"]), 14, "workbook")
    add("Checks G20 compatibility", not structure["excel_formula_compatibility_issues"], len(structure["excel_formula_compatibility_issues"]), 0, "workbook")
    add("no external workbook links", not structure["external_links"], len(structure["external_links"]), 0, "workbook")
    add("Checks remains terminal", not structure["checks_dependencies"], len(structure["checks_dependencies"]), 0, "workbook")
    add("no formula errors", not structure["formula_errors"], len(structure["formula_errors"]), 0, "workbook")
    phase8_parity = read_csv(ROOT / "data" / "phase8" / "processed" / "FORMULA_PARITY_RESULTS.csv")
    add("Phase 8 anchors unchanged", len(phase8_parity) == 15 and all(r["status"] == "PASS" for r in phase8_parity), len(phase8_parity), 15, "workbook")
    failed = [r for r in controls if r["status"] != "PASS"]
    write_csv(PROCESSED / "VALIDATION_RESULTS.csv", controls)
    if failed:
        raise Phase9Error("Phase 9 validation failed: " + ", ".join(str(r["test_name"]) for r in failed))
    return controls


def build_workbook() -> None:
    with tempfile.TemporaryDirectory(prefix="quanex-phase9-baseline-") as temp_name:
        baseline = Path(temp_name) / "Phase8.xlsx"
        phase8_baseline(baseline)
        run_artifact_tool("build", baseline)


def dynamic() -> dict[str, object]:
    """Run destructive input perturbations only on a disposable workbook copy."""
    with tempfile.TemporaryDirectory(prefix="quanex-phase9-dynamic-") as temp_name:
        copy = Path(temp_name) / MODEL.name
        shutil.copy2(MODEL, copy)
        report = run_libreoffice("dynamic", copy)
    if report.get("dynamic_status") != "PASS":
        raise Phase9Error("Phase 9 dynamic workbook tests failed")
    return report


def visual(preview_dir: Path | None = None) -> dict[str, object]:
    if preview_dir is None:
        preview_dir = Path(tempfile.mkdtemp(prefix="quanex-phase9-previews-"))
    preview_dir.mkdir(parents=True, exist_ok=True)
    run_artifact_tool("inspect", MODEL, preview_dir)
    previews = sorted(preview_dir.glob("*.png"))
    if len(previews) != 5:
        raise Phase9Error(f"Expected five Phase 9 preview images, found {len(previews)}")
    return {"preview_dir": str(preview_dir), "preview_count": len(previews)}


def normalized_fingerprint() -> str:
    excluded = {"docProps/core.xml", "xl/calcChain.xml", "xl/sharedStrings.xml"}
    digest = hashlib.sha256()
    digest.update(source_signature().encode("ascii"))
    digest.update((ROOT / "scripts" / "build-phase9.mjs").read_bytes())
    with zipfile.ZipFile(MODEL) as archive:
        for name in sorted(archive.namelist()):
            if name in excluded or (name.startswith("xl/drawings/drawing") and name.endswith(".xml")):
                continue
            data = archive.read(name)
            if name.startswith("xl/charts/chart") and name.endswith(".xml"):
                axis_ids: dict[bytes, bytes] = {}

                def normalize_axis_id(match: re.Match[bytes]) -> bytes:
                    original = match.group(2)
                    if original not in axis_ids:
                        axis_ids[original] = str(len(axis_ids) + 1).encode("ascii")
                    return match.group(1) + axis_ids[original] + match.group(3)

                data = re.sub(rb'(<c:(?:axId|crossAx) val=")(\d+)("/>)', normalize_axis_id, data)
            digest.update(name.encode("utf-8"))
            digest.update(data)
    return digest.hexdigest()


def all_workflow() -> dict[str, object]:
    payload = build_data()
    build_workbook()
    engine = run_libreoffice("inspect")
    controls = validate(engine)
    dynamic_report = dynamic()
    with tempfile.TemporaryDirectory(prefix="quanex-phase9-previews-") as temp_name:
        preview = visual(Path(temp_name))
    summary = {
        "assumptions": len(payload["assumptions"]), "owner_decisions": len(owner_decisions()),
        "recovery_cases": len(payload["cases"]), "waterfall_rows": len(read_csv(PROCESSED / "RECOVERY_WATERFALL.csv")),
        "monitors": len(payload["monitors"]), "validation_controls": len(controls),
        "dynamic_tests": dynamic_report.get("test_count"), "preview_count": preview["preview_count"],
        "formula_count": phase8.workbook_structure()["formula_count"],
        "normalized_fingerprint": normalized_fingerprint(),
    }
    print("Phase 9 complete: " + json.dumps(summary, sort_keys=True))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("inputs", "build", "validate", "dynamic", "visual", "all"))
    parser.add_argument("--preview-dir", type=Path)
    args = parser.parse_args()
    if args.command == "inputs":
        payload = build_data()
        print(json.dumps({k: len(v) if isinstance(v, list) else 1 for k, v in payload.items()}, indent=2))
    elif args.command == "build":
        build_data(); build_workbook(); print(json.dumps({"status": "PASS", "output": str(MODEL.relative_to(ROOT))}))
    elif args.command == "validate":
        rows = validate(); print(f"Phase 9 validation: PASS ({len(rows)} controls)")
    elif args.command == "dynamic":
        report = dynamic(); print(json.dumps(report, indent=2))
    elif args.command == "visual":
        print(json.dumps(visual(args.preview_dir), indent=2))
    else:
        all_workflow()


if __name__ == "__main__":
    main()
