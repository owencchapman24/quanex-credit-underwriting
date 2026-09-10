#!/usr/bin/env python3
"""Build and validate the Quanex Phase 4 debt and closing-mechanics layer.

The workflow is deliberately case-specific, deterministic, and network-free. It
uses only the approved Phase 0-3 evidence set. Owner-reviewed projected-closing
sensitivities and selected test terms remain distinct from actual borrower
facts, commitments, lender quotes, final covenants, and official compliance
calculations; unresolved private terms remain pending.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "phase4" / "raw"
PROCESSED = ROOT / "data" / "phase4" / "processed"
DOCS = ROOT / "docs" / "phase-4"
PHASE1_MANIFEST = ROOT / "data" / "raw" / "SOURCE_MANIFEST.csv"
PHASE1_DEBT_TERMS = ROOT / "data" / "processed" / "debt_terms.csv"
PHASE2_SPREAD = ROOT / "data" / "phase2" / "processed" / "historical_spread.csv"
PHASE2_BRIDGES = ROOT / "data" / "phase2" / "processed" / "earnings_bridges.csv"
PHASE3_SOURCES = ROOT / "data" / "phase3" / "raw" / "SOURCE_ADDITIONS.csv"
PHASE3_TRENDS = ROOT / "data" / "phase3" / "processed" / "QUARTERLY_SEGMENT_TRENDS.csv"
PHASE3_GAPS = ROOT / "data" / "phase3" / "processed" / "INFORMATION_GAPS.csv"
APPROVED_PHASE3_COMMIT = "f382b0007396a6a4e93bd17ac66b5326b35dbe83"
CUTOFF = date(2025, 12, 15)
CLOSING_DATE = date(2026, 1, 31)

MONEY = "USD_millions"
OWNER_PENDING = "pending_owner_approval"
OWNER_PHASE5 = "owner_reviewed_for_phase5_testing"
OWNER_SENSITIVITY = "owner_reviewed_sensitivity"
OWNER_THRESHOLD = "owner_reviewed_initial_analytical_threshold"
OWNER_METHODOLOGY = "owner_reviewed_methodology"
PHASE5_TERM_NAMES = {
    "term_loan_commitment_cap", "revolver_commitment", "permitted_use",
    "participating_bank_hold_cap", "projected_closing", "tenor",
    "term_funding_formula", "base_annual_amortization",
    "annual_amortization_sensitivities", "term_and_drawn_revolver_margin",
    "term_and_revolver_maturity", "collateral", "guarantors",
    "excess_cash_flow_sweep", "operating_cash_floor", "restricted_payments",
    "reporting_package",
}
THRESHOLD_TERM_NAMES = {
    "net_leverage_covenant", "cash_interest_coverage_covenant",
    "usable_liquidity_covenant",
}

CHECKPOINT_FIELDS = (
    "repository", "branch", "local_head", "tracked_origin_main", "live_remote_main",
    "ahead", "behind", "working_tree_clean_before_work", "verified_on", "notes",
)
CLOSING_INPUT_FIELDS = (
    "case_id", "case_name", "amortization_timing", "opening_term_principal",
    "preclosing_term_amortization", "at_closing_scheduled_amortization_component",
    "opening_revolver_borrowings", "revolver_movement", "other_bank_debt_movement",
    "accrual_days", "existing_interest_rate_percent", "prepayment_premium",
    "hedge_break_cost", "financing_fees", "legal_advisory_admin_fees",
    "lc_treatment", "lc_replacement_amount", "lc_cash_collateral_use",
    "borrower_cash_contribution", "identified_accessible_cash",
    "minimum_operating_cash", "new_term_cap", "new_revolver_commitment",
    "historical_fcf_calibration_reference", "revolver_movement_role",
    "accrued_interest_role", "fcf_interest_double_counting_control",
    "sensitivity_basis", "purpose", "status", "source_ids", "owner_review_status",
)
TERM_INPUT_FIELDS = (
    "term_id", "category", "term_name", "proposed_value", "units", "purpose",
    "risk_addressed", "source_or_hypothetical_status", "source_ids",
    "open_negotiation_issue", "final_approval_phase", "owner_review_status", "notes",
)
INSTRUMENT_FIELDS = (
    "instrument_id", "lifecycle", "instrument_name", "obligation_type", "borrower_or_issuer",
    "administrative_agent_or_lender_group", "guarantors", "secured_status",
    "collateral_description", "structural_priority", "principal_balance",
    "carrying_value", "commitment", "drawn_amount", "letters_of_credit",
    "undrawn_availability", "currency", "interest_rate_basis", "applicable_margin",
    "commitment_fee", "lc_fee", "default_rate", "maturity", "scheduled_amortization",
    "mandatory_prepayment", "voluntary_prepayment", "cash_sweep_mechanics",
    "covenant_relevance", "change_of_control_consequences", "hedging_relationship",
    "refinance_treatment", "source_ids", "source_reference", "determinability_status",
    "diligence_status", "owner_review_status", "notes",
)
LEGAL_FIELDS = (
    "legal_item_id", "topic", "exact_contractual_or_reported_language",
    "publicly_disclosed_implementation", "analyst_interpretation",
    "unresolved_private_diligence", "source_ids", "source_reference", "status",
    "owner_review_status", "notes",
)
BRIDGE_FIELDS = (
    "bridge_id", "case_id", "sequence", "item", "opening_value", "movement",
    "closing_value", "units", "calculation", "status", "classification", "source_ids",
    "source_reference", "owner_review_status", "notes",
)
SOURCES_USES_FIELDS = (
    "sources_uses_id", "case_id", "sequence", "category", "item", "amount", "units",
    "calculation", "classification", "status", "source_ids", "owner_review_status", "notes",
)
DEBT_SCHEDULE_FIELDS = (
    "schedule_id", "structure", "case_id", "amortization_case", "annual_amortization_percent",
    "installment_number", "payment_date", "fiscal_year", "days_from_prior_date",
    "period_treatment", "original_principal", "quarterly_amortization_percent",
    "beginning_principal", "scheduled_principal", "balloon_principal",
    "total_principal_due", "ending_principal",
    "units", "classification", "owner_review_status", "notes",
)
MATURITY_FIELDS = (
    "maturity_id", "structure", "case_id", "amortization_case", "fiscal_bucket",
    "obligation_category", "amount", "units", "measurement_basis", "status",
    "source_ids", "owner_review_status", "notes",
)
COMPARISON_FIELDS = (
    "comparison_id", "item", "existing_value", "proposed_reference_value", "units",
    "existing_source_ids", "proposed_status", "borrower_benefit", "lender_protection",
    "principal_risk", "owner_review_status", "notes",
)
ECONOMICS_FIELDS = (
    "economics_id", "analysis_type", "principal_base", "existing_margin_bps",
    "proposed_margin_bps", "annual_spread_savings_or_cost", "upfront_fee_sensitivity",
    "break_even_years", "within_five_year_tenor", "units", "classification", "source_ids",
    "owner_review_status", "notes",
)
CP_FIELDS = (
    "condition_id", "description", "risk_addressed", "responsible_party",
    "evidence_required", "timing", "waivability", "consequence_if_unmet",
    "public_or_hypothetical_status", "source_ids", "owner_review_status", "notes",
)
PHASE5_FIELDS = (
    "input_id", "input_name", "reference_case_value", "units", "input_status",
    "source_ids", "calculation_or_basis", "phase5_required_action", "owner_review_status", "notes",
)
LEDGER_FIELDS = (
    "record_id", "output_file", "layer", "metric_or_item", "value", "units", "source_ids",
    "document_titles", "source_urls", "publication_dates", "source_reference", "classification",
    "owner_review_status", "notes",
)


class Phase4Error(RuntimeError):
    """A failure that makes Phase 4 unsafe to use."""


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise Phase4Error(f"Missing required input: {path.relative_to(ROOT)}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict[str, str]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def dec(value: str | int | Decimal, label: str = "value") -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise Phase4Error(f"Invalid decimal for {label}: {value!r}") from exc


def fmt(value: Decimal | str | int | None) -> str:
    if value is None or value == "":
        return ""
    result = format(dec(value), "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return result or "0"


def ensure_unique(rows: list[dict[str, str]], field: str, label: str) -> None:
    values = [row[field] for row in rows]
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise Phase4Error(f"Duplicate {label}: {', '.join(duplicates)}")


def semis(values: Iterable[str]) -> str:
    return ";".join(dict.fromkeys(value for value in values if value))


def checkpoint_rows() -> list[dict[str, str]]:
    return [{
        "repository": "owencchapman24/quanex-credit-underwriting",
        "branch": "main",
        "local_head": APPROVED_PHASE3_COMMIT,
        "tracked_origin_main": APPROVED_PHASE3_COMMIT,
        "live_remote_main": APPROVED_PHASE3_COMMIT,
        "ahead": "0", "behind": "0", "working_tree_clean_before_work": "yes",
        "verified_on": "2026-09-09",
        "notes": "Verified before Phase 4 file creation; live remote checked independently with git ls-remote.",
    }]


def closing_input_rows() -> list[dict[str, str]]:
    common = {
        "opening_term_principal": "468.75",
        "opening_revolver_borrowings": "172.5",
        "other_bank_debt_movement": "0",
        "existing_interest_rate_percent": "6.57",
        "prepayment_premium": "0",
        "borrower_cash_contribution": "0",
        "identified_accessible_cash": "0",
        "minimum_operating_cash": "25",
        "new_term_cap": "650",
        "new_revolver_commitment": "300",
        "revolver_movement_role": "principal_balance_sensitivity_not_cash_forecast",
        "accrued_interest_role": "separate_unpaid_payoff_interest_sensitivity",
        "fcf_interest_double_counting_control": "Historical FCF calibrates only the principal-balance sensitivity; accrued payoff interest is separate and must be reconciled in the Phase 5 integrated cash and interest schedule, never added as a second historical FCF use.",
        "status": "owner_reviewed_sensitivity_pending_closing_diligence",
        "source_ids": "SRC-001;SRC-003;SRC-021",
        "owner_review_status": OWNER_PHASE5,
    }
    cases = [
        {
            "case_id": "CC-LOW", "case_name": "minimum_payoff",
            "amortization_timing": "before_closing",
            "preclosing_term_amortization": "6.25",
            "at_closing_scheduled_amortization_component": "0",
            "revolver_movement": "0", "accrual_days": "0", "hedge_break_cost": "0",
            "financing_fees": "3", "legal_advisory_admin_fees": "2",
            "lc_treatment": "replace_under_new_revolver_non_cash",
            "lc_replacement_amount": "6.2", "lc_cash_collateral_use": "0",
            "historical_fcf_calibration_reference": "not_applicable_low_case",
            "sensitivity_basis": "Minimum funded-payoff case: scheduled Term A installment precedes close, no seasonal revolver increase, no accrued-interest or hedge use, and $5m total fee sensitivity.",
            "purpose": "Establish the lower supported funding boundary without assuming a cash contribution.",
        },
        {
            "case_id": "CC-REF", "case_name": "reference_case",
            "amortization_timing": "at_closing_embedded_in_payoff",
            "preclosing_term_amortization": "0",
            "at_closing_scheduled_amortization_component": "6.25",
            "revolver_movement": "25", "accrual_days": "30", "hedge_break_cost": "0",
            "financing_fees": "7.5", "legal_advisory_admin_fees": "2.5",
            "lc_treatment": "replace_under_new_revolver_non_cash",
            "lc_replacement_amount": "6.2", "lc_cash_collateral_use": "0",
            "historical_fcf_calibration_reference": "FY2025_Q1_FCF_trough_24.134_USD_millions",
            "sensitivity_basis": "The $25m revolver movement is a principal-balance sensitivity informed by, but not equal to or independently additive with, the observed $24.134m FY2025 Q1 FCF trough. It is not an October-to-January cash forecast. Accrued payoff interest and $10m total fees are separately identified closing-use sensitivities pending closing diligence.",
            "purpose": "Test term-cap exhaustion and the opening revolver implication under one seasonal cash-trough increment.",
        },
        {
            "case_id": "CC-HIGH", "case_name": "funding_pressure",
            "amortization_timing": "after_closing_cancelled_by_payoff",
            "preclosing_term_amortization": "0",
            "at_closing_scheduled_amortization_component": "0",
            "revolver_movement": "50", "accrual_days": "60", "hedge_break_cost": "10",
            "financing_fees": "15", "legal_advisory_admin_fees": "5",
            "lc_treatment": "cash_collateralize_at_closing",
            "lc_replacement_amount": "0", "lc_cash_collateral_use": "6.2",
            "historical_fcf_calibration_reference": "approximately_twice_FY2025_Q1_FCF_trough_24.134_USD_millions",
            "sensitivity_basis": "The $50m revolver movement is a principal-balance sensitivity informed by approximately twice the observed FY2025 Q1 FCF trough, not an October-to-January cash forecast or an independently additive FCF use. Accrued payoff interest, $10m hedge cost, $20m total fees, and $6.2m restricted-cash LC collateralization are separate closing-use sensitivities pending closing diligence.",
            "purpose": "Expose dependence on the new revolver when several unresolved closing costs are adverse.",
        },
    ]
    return [{**common, **row} for row in cases]


def proposed_term_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add(category: str, name: str, value: str, units: str, purpose: str, risk: str,
            status: str = "hypothetical_proposed_term", sources: str = "",
            issue: str = "Subject to negotiation and Phase 5-6 model results",
            phase: str = "Phase 6") -> None:
        rows.append({
            "term_id": f"PT-{len(rows) + 1:03d}", "category": category,
            "term_name": name, "proposed_value": value, "units": units,
            "purpose": purpose, "risk_addressed": risk,
            "source_or_hypothetical_status": status, "source_ids": sources,
            "open_negotiation_issue": issue, "final_approval_phase": phase,
            "owner_review_status": OWNER_PENDING,
            "notes": "No lender commitment or borrower-approved final term sheet supports this proposal.",
        })

    add("parties", "borrower", "Quanex Building Products Corporation", "text", "Identify the direct borrower.", "Obligor clarity", "supported_borrower_identity", "SRC-003", "Eligible co-borrowers and joinders require legal confirmation", "Phase 4 owner review")
    add("facilities", "term_loan_commitment_cap", "650", MONEY, "Fund supported closing uses without automatic overfunding.", "Term out persistent bank borrowings", issue="Final size follows approved closing case and Phase 5 capacity")
    add("facilities", "revolver_commitment", "300", MONEY, "Preserve working-capital and LC capacity.", "Seasonal liquidity", issue="Phase 5-6 must test peak usable liquidity and LC sublimit")
    add("purpose", "permitted_use", "Refinance bank borrowings; term out persistent revolver usage; preserve seasonal access; fund supported fees", "text", "Define bounded transaction purpose.", "Use-of-proceeds drift", issue="Final funds flow and eligible fees")
    add("hold", "participating_bank_hold_cap", "50", MONEY, "Bound the participating bank exposure.", "Concentration", issue="Allocation between facilities and final syndication")
    add("timing", "projected_closing", "2026-01-31", "date", "Set the hypothetical transaction date.", "Timing mismatch", issue="Actual closing remains hypothetical", phase="Phase 4 owner review")
    add("tenor", "tenor", "5", "years", "Extend final maturity to January 31, 2031.", "Refinancing concentration", issue="Only about 18 months beyond existing maturity; economics must justify")
    add("funding", "term_funding_formula", "Supported closing uses less approved cash contribution; capped at $650m", "formula", "Prevent automatic full-cap funding.", "Overfunding and unsupported cash use", issue="Final payoff and accessible cash certificate")
    add("amortization", "base_annual_amortization", "10", "percent_of_original_principal", "Create contractual deleveraging.", "Maturity balloon", issue="Debt-service burden must pass Phase 5-6")
    add("amortization", "annual_amortization_sensitivities", "5;10;15", "percent_of_original_principal", "Show balloon versus near-term debt-service trade-off.", "Structure sensitivity", issue="Owner selects case after cash-flow model")
    add("pricing", "term_and_drawn_revolver_margin", "Term SOFR + 250-350 bps", "basis_points", "Bound pricing sensitivity without implying a quote.", "Floating-rate and return risk", issue="No market quote; benchmark floor and pricing grid remain open")
    add("pricing", "unused_commitment_fee", "pending_information", "percent", "Compensate undrawn commitment.", "Revolver carry cost", status="pending_information", issue="Requires lender proposal")
    add("pricing", "letter_of_credit_fee", "pending_information", "percent", "Compensate LC exposure.", "Contingent credit exposure", status="pending_information", issue="LC pricing and fronting fee require proposal")
    add("maturity", "term_and_revolver_maturity", "2031-01-31", "date", "Provide a common five-year maturity.", "Refinancing risk")
    add("security", "collateral", "Eligible domestic obligor personal property, subject to legal confirmation and permitted liens", "text", "Preserve a first-priority domestic collateral package.", "Loss severity", issue="Exact collateral, exclusions, perfection, real-property treatment and foreign assets")
    add("guarantees", "guarantors", "Eligible material domestic subsidiaries, with exclusions explicit", "text", "Capture material domestic enterprise support.", "Structural subordination", issue="Post-Tyman legal-entity and guarantor schedule")
    add("mandatory_prepayment", "excess_cash_flow_sweep", "50", "percent_of_defined_excess_cash_flow", "Accelerate repayment while safeguarding operations.", "Deleveraging and cash leakage", issue="Definition, thresholds, step-downs, deductions, timing and liquidity safeguards")
    add("covenants", "net_leverage_covenant", "3.25x maximum; initially test step to 3.00x from FY2028", "turns", "Set an early-warning maintenance test.", "Leverage deterioration", issue="Definition, cash netting, cure rights, cushions and step date")
    add("covenants", "cash_interest_coverage_covenant", "3.00x minimum", "turns", "Protect cash debt-service capacity.", "Interest burden", issue="Numerator and denominator definitions")
    add("covenants", "usable_liquidity_covenant", "50", MONEY, "Preserve funded liquidity capacity.", "Seasonal cash shortfall", issue="Accessible cash, revolver availability and test frequency")
    add("liquidity", "operating_cash_floor", "25", MONEY, "Reserve operating cash in the model.", "Cash over-sweep", issue="Entity-level accessible and trapped cash analysis in Phase 5")
    add("distributions", "restricted_payments", "No debt-funded buybacks; bounded distributions subject to pro forma tests", "text", "Protect deleveraging while retaining tested flexibility.", "Cash leakage", issue="Baskets, leverage/liquidity tests and Board policy")
    add("negative_covenants", "additional_debt_and_acquisitions", "Consent requirements or documented baskets", "text", "Limit incremental leverage and integration risk.", "Debt layering and acquisition execution", issue="Baskets, ratios, permitted liens and acquisition conditions")
    add("reporting", "reporting_package", "Quarterly financials/certificates; monthly liquidity and working-capital reporting; annual audited statements", "text", "Make liquidity and operating risks observable.", "Monitoring delay", issue="Delivery deadlines, detail, audit qualification and control remediation")
    add("prepayment", "voluntary_prepayment", "pending_information", "text", "Allow optional deleveraging or refinancing.", "Call protection and flexibility", status="pending_information", issue="Premium, soft-call, notice and breakage")
    add("prepayment", "mandatory_prepayment_other", "pending_information", "text", "Capture asset sale, debt issuance and insurance proceeds.", "Leakage and collateral erosion", status="pending_information", issue="Thresholds, reinvestment and application order")
    add("rates", "default_rate_increment", "pending_information", "basis_points", "Compensate default exposure.", "Default risk", status="pending_information", issue="Requires lender proposal")
    add("letters_of_credit", "lc_sublimit_and_transition", "pending_information", MONEY, "Ensure existing $6.2m LCs are replaced or collateralized once.", "Operational continuity and double counting", status="pending_information", sources="SRC-001;SRC-003", issue="Issuer consent, sublimit, fronting, replacement and collateral mechanics")
    next(row for row in rows if row["term_name"] == "term_and_drawn_revolver_margin")["notes"] = (
        "Hypothetical sensitivity only; no spread is a lender quote, commitment, or borrower-approved term."
    )
    for term in rows:
        if term["term_name"] == "borrower":
            term["owner_review_status"] = "not_applicable_existing_fact"
        elif term["term_name"] in PHASE5_TERM_NAMES:
            term["owner_review_status"] = OWNER_PHASE5
            term["source_or_hypothetical_status"] = "hypothetical_owner_reviewed_for_phase5_testing"
            term["notes"] = "Owner-reviewed only for Phase 5 testing; not a final covenant, lender commitment, borrower-approved term sheet, or closing fact."
        elif term["term_name"] in THRESHOLD_TERM_NAMES:
            term["owner_review_status"] = OWNER_THRESHOLD
            term["source_or_hypothetical_status"] = "hypothetical_initial_analytical_test_threshold"
            term["final_approval_phase"] = "Phase 7"
            term["notes"] = "Initial analytical test threshold for Phase 5 only; not an approved final covenant or official compliance calculation."
    for name in ("collateral", "guarantors"):
        term = next(row for row in rows if row["term_name"] == name)
        term["notes"] = "Owner-reviewed for Phase 5 testing only and subject to post-Tyman joinders, exclusions, perfection, control, foreign-equity limits, permitted liens and legal opinions; no confirmed legal coverage is asserted."
    next(row for row in rows if row["term_name"] == "term_and_drawn_revolver_margin")["notes"] = (
        "Owner-reviewed sensitivity for Phase 5 testing only; no spread is a lender quote, commitment, borrower-approved final term, or closing fact."
    )
    return rows


def seed_raw() -> None:
    write_csv(RAW / "STARTING_CHECKPOINT.csv", checkpoint_rows(), CHECKPOINT_FIELDS)
    write_csv(RAW / "CLOSING_CASE_INPUTS.csv", closing_input_rows(), CLOSING_INPUT_FIELDS)
    write_csv(RAW / "PROPOSED_TERM_INPUTS.csv", proposed_term_rows(), TERM_INPUT_FIELDS)


def debt_instrument_rows() -> list[dict[str, str]]:
    facility_common = {
        "lifecycle": "existing_at_2025_10_31", "borrower_or_issuer": "Quanex Building Products Corporation",
        "administrative_agent_or_lender_group": "Wells Fargo Bank, N.A., as administrative agent; syndicate lenders",
        "guarantors": "Subsidiary guarantors other than Excluded Subsidiaries; complete post-Tyman schedule not publicly determinable",
        "secured_status": "senior_secured",
        "collateral_description": "First-priority liens, subject to permitted liens and excluded assets, on substantially all loan-party assets; 10-K describes substantially all domestic assets other than real property",
        "structural_priority": "Senior at loan parties; structurally subordinated to obligations at non-guarantor subsidiaries",
        "currency": "USD; revolver also permits specified alternative currencies",
        "interest_rate_basis": "Base Rate or Adjusted Term SOFR; specified alternative-currency mechanics",
        "applicable_margin": "SOFR/RFR 2.00%-2.75%; Base Rate 1.00%-1.75%, leverage-based",
        "default_rate": "2.00% above otherwise applicable rate",
        "maturity": "2029-08-01",
        "covenant_relevance": "Existing maximum CNLR 3.25x at projected close absent another qualifying step-up; minimum interest coverage 3.00x",
        "change_of_control_consequences": "Change of Control is an Event of Default under section 8.11",
        "hedging_relationship": "Loan prepayment does not itself affect obligations under Hedge Agreements; exact positions and break costs are not public",
        "source_ids": "SRC-001;SRC-003",
        "determinability_status": "partially_determinable",
        "diligence_status": "requires_payoff_and_legal_confirmation",
        "owner_review_status": "not_applicable_existing_fact",
    }

    def row(**values: str) -> dict[str, str]:
        blank = {field: "" for field in INSTRUMENT_FIELDS}
        blank.update(values)
        return blank

    rows = [
        row(**facility_common, instrument_id="EX-TERM-A", instrument_name="Existing Term Loan A",
            obligation_type="funded_bank_principal", principal_balance="468.75",
            carrying_value="not_determinable_by_instrument", commitment="500", drawn_amount="468.75",
            letters_of_credit="0", undrawn_availability="not_applicable", commitment_fee="not_applicable",
            lc_fee="not_applicable", scheduled_amortization="$6.25m quarterly / $25m annually; 1.25% quarterly of original principal",
            mandatory_prepayment="100% of specified impermissible debt proceeds and qualifying asset/insurance/condemnation proceeds, subject to thresholds, exceptions and reinvestment",
            voluntary_prepayment="Without premium or penalty, subject to notice, minimum amounts and section 2.19(e) breakage",
            cash_sweep_mechanics="No excess-cash-flow sweep identified in the approved public agreement",
            refinance_treatment="Repay at hypothetical close; exact payoff and accrued amounts require payoff letter",
            source_reference="SRC-003 sections 2.3-2.4, 2.14, 7.1-7.2, 8.11; SRC-001 Note 9",
            notes="Principal is gross amount owed. The $11.040m unamortized financing-cost balance is not allocated by instrument."),
        row(**facility_common, instrument_id="EX-REVOLVER", instrument_name="Existing Revolving Credit Facility",
            obligation_type="funded_bank_principal_and_commitment", principal_balance="172.5",
            carrying_value="not_determinable_by_instrument", commitment="475", drawn_amount="172.5",
            letters_of_credit="6.2", undrawn_availability="296.3", commitment_fee="0.150%-0.250% leverage-based",
            lc_fee="Applicable SOFR/RFR margin of 2.00%-2.75%, plus customary issuer charges",
            scheduled_amortization="None; drawings repay at maturity unless prepaid",
            mandatory_prepayment="Immediate repayment/cash collateralization if revolving outstandings exceed commitment",
            voluntary_prepayment="Without premium or penalty, subject to notice and section 2.19(e) breakage",
            cash_sweep_mechanics="No excess-cash-flow sweep identified; revolving loans may be repaid and reborrowed",
            refinance_treatment="Repay funded drawings; replace or cash-collateralize LCs once; exact payoff requires letter",
            source_reference="SRC-003 sections 2.5, 2.8-2.10, 2.15-2.16 and Schedule 1; SRC-001 Note 9",
            notes="$100m alternative-currency, $30m LC, and $15m swingline limits are sublimits, not incremental commitments."),
        row(instrument_id="EX-LC", lifecycle="existing_at_2025_10_31", instrument_name="Outstanding letters of credit",
            obligation_type="contingent_revolver_exposure", borrower_or_issuer="Quanex Building Products Corporation or permitted subsidiary account",
            administrative_agent_or_lender_group="Wells Fargo Bank, N.A., as issuing lender; revolving lenders participate",
            guarantors=facility_common["guarantors"], secured_status="secured_obligation",
            collateral_description=facility_common["collateral_description"], structural_priority=facility_common["structural_priority"],
            principal_balance="0", carrying_value="not_applicable", commitment="30", drawn_amount="0",
            letters_of_credit="6.2", undrawn_availability="not_applicable", currency="USD_or_permitted_alternative_currency",
            interest_rate_basis="Contingent exposure; reimbursement obligations arise if drawn",
            applicable_margin="LC commission equals applicable SOFR/RFR margin", commitment_fee="not_applicable",
            lc_fee="2.00%-2.75% commission plus customary issuer charges", default_rate=facility_common["default_rate"],
            maturity="No later than five business days before 2029-08-01, subject to agreement mechanics",
            scheduled_amortization="not_applicable", mandatory_prepayment="Cash collateralization if exposure exceeds commitment or facility terminates without replacement",
            voluntary_prepayment="Cancellation/replacement subject to instrument and issuer consent", cash_sweep_mechanics="not_applicable",
            covenant_relevance="Reduces revolver availability but is not funded debt unless drawn",
            change_of_control_consequences=facility_common["change_of_control_consequences"], hedging_relationship="not_applicable",
            refinance_treatment="Replace under new revolver or cash-collateralize; never both as a use and funded principal",
            source_ids="SRC-001;SRC-003", source_reference="SRC-003 sections 2.15 and 2.9; SRC-001 Note 9",
            determinability_status="reported_exposure_transition_pending", diligence_status="requires_lc_schedule_and_issuer_confirmation",
            owner_review_status=OWNER_PENDING, notes="The $6.2m is counted once as contingent exposure."),
        row(instrument_id="EX-FIN-LEASE", lifecycle="retained_post_close", instrument_name="Finance lease obligations",
            obligation_type="funded_lease_obligation", borrower_or_issuer="Quanex consolidated subsidiaries",
            administrative_agent_or_lender_group="Multiple lessors; private schedules not public", guarantors="Instrument-specific; not publicly determinable",
            secured_status="Asset-level lease claims; terms not publicly determinable", collateral_description="Leased equipment, vehicles and warehouse/real-estate interests as applicable",
            structural_priority="Potentially senior with respect to leased assets", principal_balance="60.733", carrying_value="60.733",
            commitment="not_applicable", drawn_amount="60.733", letters_of_credit="0", undrawn_availability="not_applicable",
            currency="primarily_USD_not_fully_determinable", interest_rate_basis="Weighted-average finance lease discount rate 4.92%",
            applicable_margin="not_applicable", commitment_fee="not_applicable", lc_fee="not_applicable", default_rate="not_determinable",
            maturity="Multiple; weighted-average remaining term 15.1 years", scheduled_amortization="Contract-specific; Note 6 maturity table",
            mandatory_prepayment="not_determinable", voluntary_prepayment="not_determinable", cash_sweep_mechanics="not_applicable",
            covenant_relevance="Included in Phase 2 gross funded debt; treatment under proposed definitions remains open",
            change_of_control_consequences="not_determinable", hedging_relationship="not_applicable",
            refinance_treatment="Retained; not included in bank-debt payoff", source_ids="SRC-001",
            source_reference="SRC-001 Note 6 and Note 9", determinability_status="reported_aggregate_private_instruments",
            diligence_status="requires_lease_schedule_and_change_of_control_review", owner_review_status=OWNER_PENDING,
            notes="$4.477m current plus $56.256m noncurrent lease liabilities. The combined $62.619m finance leases and other debt includes $1.886m residual other debt."),
        row(instrument_id="EX-OTHER-DEBT", lifecycle="retained_post_close", instrument_name="Other debt residual",
            obligation_type="other_funded_debt", borrower_or_issuer="Quanex consolidated subsidiaries",
            administrative_agent_or_lender_group="not_determinable", guarantors="not_determinable", secured_status="not_determinable",
            collateral_description="not_determinable", structural_priority="Potential structural priority at issuing subsidiary; not determinable",
            principal_balance="1.886", carrying_value="1.886", commitment="not_applicable", drawn_amount="1.886",
            letters_of_credit="0", undrawn_availability="not_applicable", currency="not_determinable", interest_rate_basis="not_determinable",
            applicable_margin="not_determinable", commitment_fee="not_applicable", lc_fee="not_applicable", default_rate="not_determinable",
            maturity="Included with finance leases and other in Note 9 maturity table", scheduled_amortization="not_separately_determinable",
            mandatory_prepayment="not_determinable", voluntary_prepayment="not_determinable", cash_sweep_mechanics="not_applicable",
            covenant_relevance="Included in Phase 2 gross funded debt", change_of_control_consequences="not_determinable",
            hedging_relationship="not_applicable", refinance_treatment="Retained pending instrument-level diligence",
            source_ids="SRC-001;SRC-002", source_reference="Calculated: $62.619m combined less $60.733m finance lease liabilities from SRC-001 Notes 6 and 9",
            determinability_status="calculated_residual_components_not_public", diligence_status="requires_instrument_schedule",
            owner_review_status=OWNER_PENDING, notes="Residual is not assumed refinanced and must not be duplicated with finance leases."),
        row(instrument_id="EX-OPERATING-LEASE", lifecycle="retained_post_close", instrument_name="Operating lease liabilities",
            obligation_type="operating_lease_debt_like_obligation", borrower_or_issuer="Quanex consolidated subsidiaries",
            administrative_agent_or_lender_group="Multiple lessors", guarantors="Instrument-specific; not publicly determinable",
            secured_status="Lease rights; not classified as funded debt", collateral_description="Operating lease rights",
            structural_priority="Potential asset-level priority; not funded bank debt", principal_balance="not_applicable",
            carrying_value="160.905", commitment="not_applicable", drawn_amount="not_applicable", letters_of_credit="0",
            undrawn_availability="not_applicable", currency="primarily_USD_not_fully_determinable", interest_rate_basis="Weighted-average discount rate 5.64%",
            applicable_margin="not_applicable", commitment_fee="not_applicable", lc_fee="not_applicable", default_rate="not_determinable",
            maturity="Multiple; weighted-average remaining term 11.2 years", scheduled_amortization="Contract-specific; Note 6 maturity table",
            mandatory_prepayment="not_determinable", voluntary_prepayment="not_determinable", cash_sweep_mechanics="not_applicable",
            covenant_relevance="Not included in Phase 2 funded debt; definition treatment must be specified",
            change_of_control_consequences="not_determinable", hedging_relationship="not_applicable",
            refinance_treatment="Retained; not a payoff use", source_ids="SRC-001", source_reference="SRC-001 Note 6",
            determinability_status="reported_aggregate_private_instruments", diligence_status="requires_lease_schedule",
            owner_review_status=OWNER_PENDING, notes="$15.446m current plus $145.459m noncurrent; kept separate from finance leases and funded debt."),
        row(instrument_id="EX-DEFERRED-FEES", lifecycle="accounting_adjustment_at_close", instrument_name="Unamortized deferred financing fees",
            obligation_type="contra_debt_not_principal", borrower_or_issuer="Quanex Building Products Corporation",
            administrative_agent_or_lender_group="not_applicable", guarantors="not_applicable", secured_status="not_applicable",
            collateral_description="not_applicable", structural_priority="not_applicable", principal_balance="0", carrying_value="-11.04",
            commitment="not_applicable", drawn_amount="0", letters_of_credit="0", undrawn_availability="not_applicable", currency="USD",
            interest_rate_basis="not_applicable", applicable_margin="not_applicable", commitment_fee="not_applicable", lc_fee="not_applicable",
            default_rate="not_applicable", maturity="Accounting write-off timing depends on transaction treatment",
            scheduled_amortization="Accounting amortization only", mandatory_prepayment="not_applicable", voluntary_prepayment="not_applicable",
            cash_sweep_mechanics="not_applicable", covenant_relevance="Excluded from funded-principal payoff and Phase 2 gross debt",
            change_of_control_consequences="not_applicable", hedging_relationship="not_applicable",
            refinance_treatment="Do not fund as debt principal; accounting write-off and new fee treatment require confirmation",
            source_ids="SRC-001", source_reference="SRC-001 Note 9", determinability_status="reported_aggregate",
            diligence_status="requires_accounting_treatment", owner_review_status=OWNER_PENDING,
            notes="Contra-debt reduces the $703.869m gross funded principal to $692.829m carrying debt."),
        row(instrument_id="EX-ACCRUED-INTEREST", lifecycle="closing_use_if_due", instrument_name="Accrued interest and agent payoff items",
            obligation_type="closing_payable_not_principal", borrower_or_issuer="Quanex Building Products Corporation",
            administrative_agent_or_lender_group="Wells Fargo Bank, N.A.", guarantors=facility_common["guarantors"], secured_status="secured_obligation",
            collateral_description=facility_common["collateral_description"], structural_priority=facility_common["structural_priority"],
            principal_balance="0", carrying_value="not_determinable", commitment="not_applicable", drawn_amount="0", letters_of_credit="0",
            undrawn_availability="not_applicable", currency="USD", interest_rate_basis="Closing sensitivity uses 6.57% reported rate and 0/30/60-day accrual",
            applicable_margin="not_applicable", commitment_fee="not_applicable", lc_fee="not_applicable", default_rate="not_applicable",
            maturity="Due at payoff", scheduled_amortization="not_applicable", mandatory_prepayment="not_applicable", voluntary_prepayment="not_applicable",
            cash_sweep_mechanics="not_applicable", covenant_relevance="Closing use only", change_of_control_consequences="not_applicable",
            hedging_relationship="Break costs remain separate", refinance_treatment="Pay exact amount shown on payoff letter",
            source_ids="SRC-001;SRC-003", source_reference="SRC-001 Note 9; SRC-003 sections 2.3-2.4 and 2.8",
            determinability_status="pending_information", diligence_status="essential_payoff_letter",
            owner_review_status=OWNER_PENDING, notes="Sensitivity is not an actual January accrued-interest balance."),
        row(instrument_id="NEW-TERM", lifecycle="hypothetical_post_close", instrument_name="Proposed five-year term loan",
            obligation_type="proposed_funded_bank_principal", borrower_or_issuer="Quanex Building Products Corporation",
            administrative_agent_or_lender_group="not_selected", guarantors="Eligible material domestic subsidiaries; subject to legal confirmation",
            secured_status="hypothetical_senior_secured", collateral_description="Eligible domestic obligor personal property; exclusions and permitted liens to be negotiated",
            structural_priority="Proposed senior at loan parties; structural subordination remains for non-guarantors",
            principal_balance="varies_by_closing_case", carrying_value="not_applicable_before_close", commitment="up_to_650",
            drawn_amount="varies_by_closing_case", letters_of_credit="0", undrawn_availability="not_applicable", currency="USD",
            interest_rate_basis="Term SOFR", applicable_margin="hypothetical_250-350_bps", commitment_fee="not_applicable",
            lc_fee="not_applicable", default_rate="pending_information", maturity="2031-01-31",
            scheduled_amortization="5%/10%/15% annual sensitivities, paid quarterly on original funded principal",
            mandatory_prepayment="50% ECF sweep proposed for testing; other terms pending", voluntary_prepayment="pending_information",
            cash_sweep_mechanics="Hypothetical 50% of defined ECF with liquidity safeguards", covenant_relevance="Proposed 3.25x net leverage, 3.00x cash-interest coverage and $50m usable-liquidity tests",
            change_of_control_consequences="pending_information", hedging_relationship="Rate and hedge structure pending",
            refinance_treatment="New funding equals supported uses less approved cash, capped at $650m",
            source_ids="", source_reference="Case architecture; no executed term sheet", determinability_status="hypothetical",
            diligence_status="pending_closing_diligence_and_lender_commitment", owner_review_status=OWNER_PHASE5,
            notes="Owner-reviewed only as a Phase 5 test structure; no commitment exists, and size remains subject to final capacity, payoff and funds flow."),
        row(instrument_id="NEW-REV", lifecycle="hypothetical_post_close", instrument_name="Proposed five-year revolving facility",
            obligation_type="proposed_commitment_and_case_draw", borrower_or_issuer="Quanex Building Products Corporation",
            administrative_agent_or_lender_group="not_selected", guarantors="Eligible material domestic subsidiaries; subject to legal confirmation",
            secured_status="hypothetical_senior_secured", collateral_description="Eligible domestic obligor personal property; exclusions and permitted liens to be negotiated",
            structural_priority="Proposed senior at loan parties; structural subordination remains for non-guarantors",
            principal_balance="varies_by_closing_case", carrying_value="not_applicable_before_close", commitment="300",
            drawn_amount="varies_by_closing_case", letters_of_credit="0_or_6.2_by_case", undrawn_availability="varies_by_closing_case",
            currency="USD_and_other_currencies_if_agreed", interest_rate_basis="Term SOFR or other agreed benchmark",
            applicable_margin="hypothetical_250-350_bps", commitment_fee="pending_information", lc_fee="pending_information",
            default_rate="pending_information", maturity="2031-01-31", scheduled_amortization="None; opening draw assumed due at maturity for principal-only illustration",
            mandatory_prepayment="Commitment-overdraw protections required", voluntary_prepayment="Expected revolving repayment/reborrow; final terms pending",
            cash_sweep_mechanics="No projected sweeps in Phase 4", covenant_relevance="Proposed maintenance covenants; Phase 5-6 must test peak liquidity",
            change_of_control_consequences="pending_information", hedging_relationship="pending_information",
            refinance_treatment="Mechanically funds supported residual after term and approved cash, subject to $300m including LCs",
            source_ids="", source_reference="Case architecture; no executed term sheet", determinability_status="hypothetical",
            diligence_status="pending_closing_diligence_and_lender_commitment", owner_review_status=OWNER_PHASE5,
            notes="Owner-reviewed only as a Phase 5 test structure; nominal opening availability is not proof of seasonal sufficiency."),
    ]
    return rows


def legal_structure_rows() -> list[dict[str, str]]:
    items = [
        ("primary_borrower", "Quanex Building Products Corporation is the Borrower.", "The FY2025 10-K identifies the same parent company.", "Parent is the direct bank obligor.", "Confirm no proposed co-borrowers.", "SRC-001;SRC-003", "SRC-003 preamble and definition of Borrower", "supported"),
        ("known_2024_loan_parties", "Amendment No. 1 was executed by the Borrower and named domestic loan parties.", "Named signatures include Quanex Custom Components, Quanex North American Cabinet Components, Quanex Homeshield, Quanex IG Systems, Quanex North American Fenestration, Mikron Industries and Mikron Washington.", "This is evidence of signatories in June 2024, not a complete October 2025 guarantor schedule.", "Obtain current legal-entity/guarantor schedule after Tyman joinders.", "SRC-003", "SRC-003 Amendment No. 1 signature pages", "partial_public_implementation"),
        ("guarantor_requirement", "Guarantors are subsidiaries other than Excluded Subsidiaries and later joinders under section 5.11.", "Public filings do not list the complete post-Tyman guarantor population.", "Material eligible domestic subsidiaries should support the proposed facilities.", "Confirm entity-by-entity joinders and enforceability.", "SRC-003", "SRC-003 definitions of Guarantor/Excluded Subsidiary and section 5.11", "contract_supported_private_implementation_pending"),
        ("foreign_subsidiaries", "Foreign Subsidiaries are Excluded Subsidiaries.", "Tyman materially increased foreign operations.", "Foreign operating assets and cash are structurally outside direct domestic guarantee support absent specific arrangements.", "Map foreign borrowers, local debt, restrictions and upstream capacity.", "SRC-001;SRC-003", "SRC-003 definition of Excluded Subsidiary; SRC-001 Item 1 and liquidity", "supported_limitation"),
        ("immaterial_domestic_subsidiaries", "Individual 2.5% asset/revenue and aggregate 5% tests govern immaterial domestic exclusions.", "Current designations are not publicly determinable.", "The framework limits but does not eliminate non-guarantor domestic exposure.", "Test current entities against thresholds.", "SRC-003", "SRC-003 definition of Immaterial Domestic Subsidiary", "contract_supported_private_implementation_pending"),
        ("security_grant", "Agent may require liens in substantially all loan-party assets other than Excluded Assets.", "10-K states substantially all domestic assets other than real property were collateral.", "Public evidence supports the framework, not present perfection for every asset.", "Lien searches, UCC/IP filings and collateral schedules.", "SRC-001;SRC-003", "SRC-003 sections 5.11-5.12; SRC-001 Note 9/MD&A", "partially_supported"),
        ("real_property", "Excluded Assets are governed by the Guaranty and Security Agreement.", "10-K explicitly excludes real property from its domestic collateral description.", "Do not assume owned real estate or real-estate lease interests are mortgaged.", "Confirm owned/leased property, mortgages and landlord waivers.", "SRC-001;SRC-003", "SRC-001 Note 9; SRC-003 definition of Excluded Assets", "reported_exclusion"),
        ("equity_pledges", "No pledge of a first-tier foreign subsidiary is required beyond up to 65% voting and 100% nonvoting equity interests.", "Exact pledged equity after Tyman is not public.", "Foreign equity support is limited and does not equal a foreign asset lien.", "Inspect pledge schedules and perfection.", "SRC-003", "SRC-003 section 5.11", "contract_supported_private_implementation_pending"),
        ("deposit_accounts_and_cash_control", "The collateral framework covers loan-party assets subject to exclusions.", "No complete public deposit-account/control-agreement schedule is available.", "Book cash cannot be assumed perfected, controlled or accessible.", "Obtain account list, control agreements, restrictions and cash dominion terms.", "SRC-001;SRC-003", "SRC-003 Guaranty and Security Agreement references; SRC-001 liquidity", "pending_information"),
        ("permitted_liens_and_priority", "First-priority liens are subject to Permitted Liens and Excluded Assets.", "Implementation and competing liens are not fully public.", "Priority is qualified; asset-level claims may rank ahead.", "Lien search, lease claims, purchase-money debt and intercreditor review.", "SRC-003", "SRC-003 sections 5.12, 6.2 and 14.1", "contract_supported_private_implementation_pending"),
        ("post_tyman_joinders", "Acquired entities must comply with section 5.11 where applicable.", "Exact Tyman joinders, guaranties and security deliveries are not public.", "Post-acquisition credit support cannot be presumed.", "Current organizational chart, joinders, security documents and legal opinions.", "SRC-001;SRC-003", "SRC-003 Permitted Acquisition and section 5.11; SRC-001 Note 9", "pending_information"),
        ("foreign_cash", "Existing covenant cash netting is subject to eligibility conditions and a $25m non-U.S. sublimit within a $100m cap.", "$46.9m of $76.0m book cash was held in foreign countries at October 31, 2025.", "Consolidated cash is not automatically available for debt repayment or closing contribution.", "Entity, jurisdiction, tax, exchange-control, lien and operational-access analysis.", "SRC-001;SRC-003", "SRC-001 liquidity; SRC-003 Consolidated Funded Indebtedness definition", "reported_cash_access_pending"),
        ("structural_subordination", "Foreign and qualifying immaterial domestic subsidiaries may be Excluded Subsidiaries.", "Material operations and assets exist outside the United States.", "Creditors at non-guarantor subsidiaries may be structurally senior to parent lenders for those assets/cash flows.", "Quantify assets, EBITDA, cash and liabilities by guarantor/non-guarantor group.", "SRC-001;SRC-003", "SRC-003 Excluded Subsidiary definition; SRC-001 geographic disclosures", "analyst_interpretation"),
        ("lien_release_at_refinancing", "Existing liens remain until obligations and LC exposure are discharged under release mechanics.", "No hypothetical payoff or release document is public.", "New liens cannot be assumed first-priority without coordinated releases and new perfection.", "Payoff letter, LC treatment, releases, UCC terminations and bring-down searches.", "SRC-003", "SRC-003 sections 2.9, 14.11 and Amendment No. 1 reaffirmation", "essential_closing_diligence"),
        ("proposed_package", "No proposed credit agreement exists.", "Case architecture proposes eligible domestic guarantees and personal-property security.", "All proposed legal terms remain hypothetical and should not be inferred from the existing facility.", "Negotiate guaranty, collateral, exclusions, perfection, account control and priority.", "", "Case architecture", "hypothetical_pending_owner_review"),
    ]
    return [{
        "legal_item_id": f"LS-{index:03d}", "topic": topic,
        "exact_contractual_or_reported_language": exact,
        "publicly_disclosed_implementation": public, "analyst_interpretation": interpretation,
        "unresolved_private_diligence": diligence, "source_ids": sources,
        "source_reference": reference, "status": status,
        "owner_review_status": (
            "not_applicable_existing_fact" if status in {"supported", "reported_exclusion"}
            else OWNER_PHASE5 if topic == "proposed_package"
            else OWNER_METHODOLOGY
        ),
        "notes": "Public evidence is not a representation that guarantees or liens are complete, valid, enforceable or perfected at closing.",
    } for index, (topic, exact, public, interpretation, diligence, sources, reference, status) in enumerate(items, 1)]


def calculate_closing_cases(inputs: list[dict[str, str]]) -> dict[str, dict[str, Decimal | str]]:
    results: dict[str, dict[str, Decimal | str]] = {}
    for row in inputs:
        cid = row["case_id"]
        opening_term = dec(row["opening_term_principal"])
        preclose_amort = dec(row["preclosing_term_amortization"])
        term_payoff = opening_term - preclose_amort
        opening_rev = dec(row["opening_revolver_borrowings"])
        rev_move = dec(row["revolver_movement"])
        other_move = dec(row["other_bank_debt_movement"])
        rev_payoff = opening_rev + rev_move
        bank_payoff = term_payoff + rev_payoff + other_move
        accrued = bank_payoff * dec(row["existing_interest_rate_percent"]) / Decimal("100") * dec(row["accrual_days"]) / Decimal("360")
        total_uses = sum((
            term_payoff, rev_payoff, other_move, accrued, dec(row["prepayment_premium"]),
            dec(row["hedge_break_cost"]), dec(row["financing_fees"]),
            dec(row["legal_advisory_admin_fees"]), dec(row["lc_cash_collateral_use"]),
        ), Decimal("0"))
        cash = dec(row["borrower_cash_contribution"])
        term_cap = dec(row["new_term_cap"])
        term_funding = min(term_cap, max(Decimal("0"), total_uses - cash))
        term_only_gap = max(Decimal("0"), total_uses - cash - term_funding)
        revolver_capacity = dec(row["new_revolver_commitment"]) - dec(row["lc_replacement_amount"])
        new_revolver = min(revolver_capacity, term_only_gap)
        funding_gap = max(Decimal("0"), term_only_gap - new_revolver)
        availability = dec(row["new_revolver_commitment"]) - new_revolver - dec(row["lc_replacement_amount"])
        results[cid] = {
            "case_name": row["case_name"], "amortization_timing": row["amortization_timing"],
            "opening_term": opening_term, "preclose_amort": preclose_amort,
            "at_close_amort_component": dec(row["at_closing_scheduled_amortization_component"]),
            "term_payoff": term_payoff, "opening_revolver": opening_rev, "revolver_movement": rev_move,
            "revolver_payoff": rev_payoff, "other_bank_movement": other_move, "bank_payoff": bank_payoff,
            "accrued_interest": accrued, "prepayment_premium": dec(row["prepayment_premium"]),
            "hedge_break_cost": dec(row["hedge_break_cost"]), "financing_fees": dec(row["financing_fees"]),
            "legal_fees": dec(row["legal_advisory_admin_fees"]), "lc_treatment": row["lc_treatment"],
            "lc_replacement": dec(row["lc_replacement_amount"]), "lc_cash_collateral": dec(row["lc_cash_collateral_use"]),
            "cash_contribution": cash, "accessible_cash": dec(row["identified_accessible_cash"]),
            "minimum_cash": dec(row["minimum_operating_cash"]), "total_uses": total_uses,
            "term_funding": term_funding, "term_only_gap": term_only_gap, "new_revolver": new_revolver,
            "funding_gap": funding_gap, "remaining_availability": availability,
            "source_ids": row["source_ids"], "basis": row["sensitivity_basis"], "purpose": row["purpose"],
            "historical_fcf_calibration_reference": row["historical_fcf_calibration_reference"],
            "revolver_movement_role": row["revolver_movement_role"],
            "accrued_interest_role": row["accrued_interest_role"],
            "fcf_interest_double_counting_control": row["fcf_interest_double_counting_control"],
            "owner_review_status": row["owner_review_status"],
        }
    return results


def closing_bridge_rows(inputs: list[dict[str, str]], results: dict[str, dict[str, Decimal | str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add(cid: str, item: str, opening: str, movement: str, closing: str, calculation: str,
            status: str, classification: str, sources: str, reference: str, notes: str = "") -> None:
        rows.append({
            "bridge_id": f"CB-{len(rows) + 1:04d}", "case_id": cid,
            "sequence": str(sum(1 for row in rows if row["case_id"] == cid) + 1), "item": item,
            "opening_value": opening, "movement": movement, "closing_value": closing,
            "units": MONEY, "calculation": calculation, "status": status,
            "classification": classification, "source_ids": sources,
            "source_reference": reference, "owner_review_status": OWNER_PHASE5, "notes": notes,
        })

    by_id = {row["case_id"]: row for row in inputs}
    for cid in ("CC-LOW", "CC-REF", "CC-HIGH"):
        result, raw = results[cid], by_id[cid]
        sources = str(result["source_ids"])
        add(cid, "Existing Term A principal at October 31", "468.75", "0", "468.75", "Approved October 31 principal", "supported", "reported_fact", "SRC-001;SRC-002", "SRC-001 Note 9; SRC-002 net-debt table")
        add(cid, "Pre-closing scheduled Term A amortization", "468.75", fmt(-dec(result["preclose_amort"])), fmt(dec(result["term_payoff"])), "Opening Term A less installment paid before close", "sensitivity", "timing_assumption", "SRC-003", "SRC-003 section 2.3", f"Timing: {result['amortization_timing']}")
        add(cid, "Scheduled amortization component embedded in payoff", "", fmt(result["at_close_amort_component"]), fmt(result["at_close_amort_component"]), "Disclosure only; included within total Term A payoff and never added again", "sensitivity", "timing_assumption", "SRC-003", "SRC-003 section 2.3", "Prevents double counting when the scheduled date coincides with closing.")
        add(cid, "Term A payoff", "468.75", fmt(-dec(result["preclose_amort"])), fmt(result["term_payoff"]), "Opening principal less only a pre-closing installment", "owner_reviewed_sensitivity_pending_closing_diligence", "calculated_from_fact_and_assumption", sources, "Closing case input")
        add(cid, "Existing revolver borrowings", "172.5", fmt(result["revolver_movement"]), fmt(result["revolver_payoff"]), "October 31 revolver plus owner-reviewed principal-balance sensitivity; historical FCF is calibration only", "owner_reviewed_sensitivity_pending_closing_diligence", "calculated_from_fact_and_assumption", "SRC-001;SRC-002;SRC-021", "SRC-001 Note 9; SRC-021 FY2025 Q1 cash evidence", str(result["basis"]))
        add(cid, "Other bank-debt movement", "0", fmt(result["other_bank_movement"]), fmt(result["other_bank_movement"]), "Explicit sensitivity; no other public bank debt identified", "pending_information", "assumption", "SRC-001", "SRC-001 Note 9")
        add(cid, "Total bank principal payoff", "641.25", fmt(dec(result["bank_payoff"]) - Decimal("641.25")), fmt(result["bank_payoff"]), "Term A payoff + revolver payoff + other bank-debt movement", "calculated", "calculated", sources, "Calculated from closing inputs")
        add(cid, "Existing letters of credit", "6.2", fmt(dec(result["lc_replacement"]) - Decimal("6.2")), fmt(result["lc_replacement"]), "Replacement exposure under new revolver; zero when cash-collateralized as separate use", "sensitivity", "contingent_exposure", "SRC-001;SRC-003", "SRC-001 Note 9; SRC-003 sections 2.9 and 2.15", f"Treatment: {result['lc_treatment']}")
        add(cid, "Accrued interest", "0", fmt(result["accrued_interest"]), fmt(result["accrued_interest"]), f"Bank payoff x 6.57% x {raw['accrual_days']}/360; separate unpaid payoff-interest use", "owner_reviewed_sensitivity_pending_closing_diligence", "calculated_from_reported_rate", "SRC-001", "SRC-001 Note 9", "Exact rate, reset and payment date require payoff letter. Phase 5 must reconcile this use with integrated cash interest and must not add it again through the historical FCF calibration reference.")
        add(cid, "Prepayment premium", "0", "0", "0", "Existing term/revolver prepayment has no premium; interest-period breakage stays separate", "supported_with_diligence", "reported_contract_term", "SRC-003", "SRC-003 sections 2.4 and 2.8")
        add(cid, "Hedge or interest-period break cost", "0", fmt(result["hedge_break_cost"]), fmt(result["hedge_break_cost"]), "Case sensitivity; not a public payoff amount", "pending_information", "sensitivity", "SRC-003", "SRC-003 sections 2.4, 2.8 and 2.19(e)")
        add(cid, "Financing fees", "0", fmt(result["financing_fees"]), fmt(result["financing_fees"]), "Explicit fee sensitivity; not a lender quote", "pending_information", "sensitivity", "", "Case input")
        add(cid, "Legal, advisory and administrative expenses", "0", fmt(result["legal_fees"]), fmt(result["legal_fees"]), "Explicit transaction-cost sensitivity", "pending_information", "sensitivity", "", "Case input")
        add(cid, "LC cash-collateralization use", "0", fmt(result["lc_cash_collateral"]), fmt(result["lc_cash_collateral"]), "Only a cash use in the collateralization case", "owner_reviewed_sensitivity_pending_closing_diligence", "sensitivity", "SRC-001;SRC-003", "SRC-003 sections 2.9 and 2.15", "LC exposure is counted once and is not also a replacement LC deduction.")
        add(cid, "Restricted cash created by LC collateralization", "0", fmt(result["lc_cash_collateral"]), fmt(result["lc_cash_collateral"]), "Balance-sheet classification of funded LC collateral; disclosure only and not an additional use", "owner_reviewed_sensitivity_pending_closing_diligence", "restricted_asset_excluded_from_usable_liquidity", "SRC-001;SRC-003", "SRC-003 sections 2.9 and 2.15", "The funded amount is restricted cash or another separately classified restricted asset and is excluded from operating cash and usable liquidity.")
        add(cid, "Approved borrower cash contribution", "0", fmt(result["cash_contribution"]), fmt(result["cash_contribution"]), "Capped by identified accessible cash, which is conservatively zero pending diligence", "pending_information", "assumption", "SRC-001;SRC-003", "SRC-001 liquidity; SRC-003 cash-netting definition")
        add(cid, "Minimum operating cash", "76.018", "not_a_funding_source", fmt(result["minimum_cash"]), "Proposed reserve distinct from accessible closing cash", "hypothetical", "proposed_term", "SRC-001", "SRC-001 balance sheet", "Not a use and not an accessible funding source in Phase 4.")
        add(cid, "Closing cash", "76.018", "pending_information", "", "Actual January cash and legal accessibility unavailable at cutoff", "pending_information", "missing_value", "SRC-001", "SRC-001 balance sheet and liquidity")
        add(cid, "Retained finance leases and other debt", "62.619", "0", "62.619", "Retained outside bank payoff", "supported", "reported_fact", "SRC-001;SRC-002", "SRC-001 Note 9; SRC-002 net-debt table")
        add(cid, "Retained operating lease liabilities", "160.905", "0", "160.905", "Retained debt-like obligation; excluded from funded debt", "supported", "reported_fact", "SRC-001", "SRC-001 Note 6")
        add(cid, "Total closing uses", "", "", fmt(result["total_uses"]), "Bank payoff + accrued interest + premium + hedge + fees + legal/admin + LC cash collateral", "calculated", "calculated", sources, "Sources and uses")
        add(cid, "New term funding", "0", fmt(result["term_funding"]), fmt(result["term_funding"]), "Minimum of $650m cap and supported uses after approved cash", "calculated_pending_approval", "calculated_proposed_source", "", "Case architecture", "Not automatically funded at the cap.")
        add(cid, "Term-only funding gap", "0", fmt(result["term_only_gap"]), fmt(result["term_only_gap"]), "Uses less approved cash and capped term funding", "calculated", "calculated", "", "Case architecture")
        add(cid, "Opening new-revolver draw", "0", fmt(result["new_revolver"]), fmt(result["new_revolver"]), "Explicit residual supported use after term and approved cash, capped by $300m less replacement LCs", "calculated_pending_approval", "calculated_proposed_source", "", "Case architecture", "A transparent funding source, not an unexplained balancing plug.")
        add(cid, "Nominal remaining new-revolver availability", "300", fmt(-dec(result["new_revolver"]) - dec(result["lc_replacement"])), fmt(result["remaining_availability"]), "$300m commitment less opening draw less replacement LCs", "calculated", "calculated", "", "Case architecture", "Not proof of Phase 5 seasonal sufficiency.")
        add(cid, "Residual funding gap after capped revolver", "0", fmt(result["funding_gap"]), fmt(result["funding_gap"]), "Term-only gap less permitted opening revolver draw", "calculated", "calculated", "", "Case architecture")
    return rows


def sources_uses_rows(results: dict[str, dict[str, Decimal | str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add(cid: str, category: str, item: str, amount: Decimal, calc: str, classification: str,
            status: str, sources: str = "", notes: str = "") -> None:
        rows.append({
            "sources_uses_id": f"SU-{len(rows) + 1:04d}", "case_id": cid,
            "sequence": str(sum(1 for row in rows if row["case_id"] == cid) + 1),
            "category": category, "item": item, "amount": fmt(amount), "units": MONEY,
            "calculation": calc, "classification": classification, "status": status,
            "source_ids": sources, "owner_review_status": OWNER_PHASE5, "notes": notes,
        })

    for cid in ("CC-LOW", "CC-REF", "CC-HIGH"):
        r = results[cid]
        add(cid, "use", "Existing Term A payoff", dec(r["term_payoff"]), "Opening principal less pre-closing amortization only", "fact_plus_timing_assumption", "owner_reviewed_sensitivity_pending_closing_diligence", "SRC-001;SRC-003")
        add(cid, "use", "Existing revolver payoff", dec(r["revolver_payoff"]), "October 31 draw plus owner-reviewed principal-balance sensitivity; historical FCF is calibration only", "fact_plus_sensitivity", "owner_reviewed_sensitivity_pending_closing_diligence", "SRC-001;SRC-021")
        add(cid, "use", "Other bank-debt movement", dec(r["other_bank_movement"]), "Explicit input", "sensitivity", "pending_information", "SRC-001")
        add(cid, "use", "Accrued interest", dec(r["accrued_interest"]), "Separate unpaid payoff-interest sensitivity; must reconcile to Phase 5 integrated interest", "sensitivity", "owner_reviewed_sensitivity_pending_closing_diligence", "SRC-001", "Do not double count cash interest already embedded in the historical FCF calibration reference.")
        add(cid, "use", "Prepayment premium", dec(r["prepayment_premium"]), "No premium under public agreement; breakage separate", "reported_contract_term", "supported_with_diligence", "SRC-003")
        add(cid, "use", "Hedge and interest-period break cost", dec(r["hedge_break_cost"]), "Explicit sensitivity", "sensitivity", "pending_information", "SRC-003")
        add(cid, "use", "Financing fees", dec(r["financing_fees"]), "Explicit fee sensitivity", "sensitivity", "pending_information", notes="Not a lender quote.")
        add(cid, "use", "Legal, advisory and administrative expenses", dec(r["legal_fees"]), "Explicit cost sensitivity", "sensitivity", "pending_information")
        add(cid, "use", "LC cash collateral", dec(r["lc_cash_collateral"]), "Zero if LCs replace under new revolver; $6.2m only in collateralization case", "restricted_cash_funding_use", "owner_reviewed_sensitivity_pending_closing_diligence", "SRC-001;SRC-003", "Creates restricted cash or another restricted asset; excluded from usable operating liquidity and counted exactly once.")
        add(cid, "total_use", "Total uses", dec(r["total_uses"]), "Sum of use rows", "calculated", "calculated")
        add(cid, "source", "New term funding", dec(r["term_funding"]), "Supported uses less approved cash, capped at $650m", "calculated_proposed_source", OWNER_PHASE5)
        add(cid, "source", "Opening new-revolver draw", dec(r["new_revolver"]), "Residual supported use, capped by $300m less replacement LCs", "calculated_proposed_source", OWNER_PHASE5, notes="Explicit funding waterfall; not an unexplained plug.")
        add(cid, "source", "Borrower cash contribution", dec(r["cash_contribution"]), "Cannot exceed identified accessible cash", "assumption", "pending_information", "SRC-001;SRC-003")
        total_sources = dec(r["term_funding"]) + dec(r["new_revolver"]) + dec(r["cash_contribution"])
        add(cid, "total_source", "Total sources excluding funding gap", total_sources, "Sum of committed-modeled sources", "calculated", "calculated")
        add(cid, "gap", "Explicit residual funding gap", dec(r["funding_gap"]), "Maximum of zero and uses less capped modeled sources", "calculated", "calculated")
        add(cid, "control", "Sources plus explicit gap less uses", total_sources + dec(r["funding_gap"]) - dec(r["total_uses"]), "Total sources + gap - total uses", "calculated_control", "PASS")
    return rows


def payment_dates() -> list[date]:
    dates: list[date] = []
    year, month = 2026, 4
    for _ in range(20):
        day = 30 if month == 4 else 31
        dates.append(date(year, month, day))
        if month == 4:
            month = 7
        elif month == 7:
            month = 10
        elif month == 10:
            month = 1
            year += 1
        else:
            month = 4
    return dates


def last_weekday(year: int, month: int) -> date:
    """Return a calendar proxy for the last Business Day of a fiscal quarter.

    The executed agreement uses "Business Day," but a complete Agent holiday
    calendar is not public. Weekend adjustment is deterministic; final payoff
    diligence must confirm any holiday convention.
    """
    result = date(year, month, calendar.monthrange(year, month)[1])
    while result.weekday() >= 5:
        result = result.fromordinal(result.toordinal() - 1)
    return result


def existing_payment_dates() -> list[date]:
    """Executed Term A installments remaining after October 31, 2025."""
    dates: list[date] = []
    year, month = 2026, 1
    while (year, month) <= (2029, 7):
        dates.append(last_weekday(year, month))
        if month == 1:
            month = 4
        elif month == 4:
            month = 7
        elif month == 7:
            month = 10
        else:
            month = 1
            year += 1
    return dates


def quanex_fiscal_year(payment_date: date) -> str:
    return f"FY{payment_date.year if payment_date.month <= 10 else payment_date.year + 1}"


def debt_schedule_rows(results: dict[str, dict[str, Decimal | str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    dates = payment_dates()
    rates = (("AMORT-5", Decimal("5")), ("AMORT-10", Decimal("10")), ("AMORT-15", Decimal("15")))

    remaining = Decimal("468.75")
    prior = date(2025, 10, 31)
    for number, payment_date in enumerate(existing_payment_dates(), 1):
        scheduled_due = min(Decimal("6.25"), remaining)
        ending = remaining - scheduled_due
        rows.append({
            "schedule_id": f"DS-{len(rows) + 1:04d}", "structure": "existing",
            "case_id": "", "amortization_case": "EXISTING-EXECUTED",
            "annual_amortization_percent": "5", "installment_number": str(number),
            "payment_date": payment_date.isoformat(), "fiscal_year": quanex_fiscal_year(payment_date),
            "days_from_prior_date": str((payment_date - prior).days),
            "period_treatment": "last_weekday_proxy_for_last_Business_Day_of_fiscal_quarter",
            "original_principal": "500", "quarterly_amortization_percent": "1.25",
            "beginning_principal": fmt(remaining), "scheduled_principal": fmt(scheduled_due),
            "balloon_principal": "0", "total_principal_due": fmt(scheduled_due),
            "ending_principal": fmt(ending), "units": MONEY,
            "classification": "executed_contract_term_schedule_from_2025_10_31_balance",
            "owner_review_status": "not_applicable_existing_fact",
            "notes": "Section 2.3 requires installments on the last Business Day of each fiscal quarter. Weekend-adjusted dates are shown; Agent holiday convention and payoff application require closing confirmation.",
        })
        remaining = ending
        prior = payment_date
    rows.append({
        "schedule_id": f"DS-{len(rows) + 1:04d}", "structure": "existing",
        "case_id": "", "amortization_case": "EXISTING-EXECUTED",
        "annual_amortization_percent": "5", "installment_number": str(len(existing_payment_dates()) + 1),
        "payment_date": "2029-08-01", "fiscal_year": "FY2029",
        "days_from_prior_date": str((date(2029, 8, 1) - prior).days),
        "period_treatment": "contractual_maturity_after_last_quarterly_installment",
        "original_principal": "500", "quarterly_amortization_percent": "1.25",
        "beginning_principal": fmt(remaining), "scheduled_principal": "0",
        "balloon_principal": fmt(remaining), "total_principal_due": fmt(remaining),
        "ending_principal": "0", "units": MONEY,
        "classification": "executed_contract_term_maturity",
        "owner_review_status": "not_applicable_existing_fact",
        "notes": "The July 31, 2029 quarterly installment precedes the August 1, 2029 maturity; no separate quarterly installment is modeled on the maturity date.",
    })

    for cid in ("CC-LOW", "CC-REF", "CC-HIGH"):
        original = dec(results[cid]["term_funding"])
        for label, annual_pct in rates:
            quarterly_pct = annual_pct / Decimal("4")
            scheduled = original * quarterly_pct / Decimal("100")
            remaining = original
            prior = CLOSING_DATE
            for number, payment_date in enumerate(dates, 1):
                scheduled_due = min(scheduled, remaining)
                pre_balloon = remaining - scheduled_due
                balloon = pre_balloon if number == len(dates) else Decimal("0")
                total_due = scheduled_due + balloon
                ending = remaining - total_due
                rows.append({
                    "schedule_id": f"DS-{len(rows) + 1:04d}", "structure": "proposed", "case_id": cid,
                    "amortization_case": label, "annual_amortization_percent": fmt(annual_pct),
                    "installment_number": str(number), "payment_date": payment_date.isoformat(),
                    "fiscal_year": quanex_fiscal_year(payment_date),
                    "days_from_prior_date": str((payment_date - prior).days),
                    "period_treatment": "full_quarter_no_proration; calendar anchor subject to business-day convention",
                    "original_principal": fmt(original), "quarterly_amortization_percent": fmt(quarterly_pct),
                    "beginning_principal": fmt(remaining),
                    "scheduled_principal": fmt(scheduled_due), "balloon_principal": fmt(balloon),
                    "total_principal_due": fmt(total_due), "ending_principal": fmt(ending),
                    "units": MONEY, "classification": "hypothetical_principal_only_schedule",
                    "owner_review_status": OWNER_PHASE5,
                    "notes": "No cash sweep, voluntary repayment, revolver movement, or interest projection is included. The first modeled payment is 2026-04-30; actual business-day mechanics require final documents.",
                })
                remaining = ending
                prior = payment_date
    return rows


def maturity_rows(schedule: list[dict[str, str]], results: dict[str, dict[str, Decimal | str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add(structure: str, cid: str, amort: str, bucket: str, category: str, amount: Decimal | str,
            basis: str, status: str, sources: str, owner: str, notes: str = "") -> None:
        rows.append({
            "maturity_id": f"MT-{len(rows) + 1:04d}", "structure": structure,
            "case_id": cid, "amortization_case": amort, "fiscal_bucket": bucket,
            "obligation_category": category, "amount": fmt(amount) if amount != "" else "", "units": MONEY,
            "measurement_basis": basis, "status": status, "source_ids": sources,
            "owner_review_status": owner, "notes": notes,
        })

    facility = {"FY2026": Decimal("25"), "FY2027": Decimal("25"), "FY2028": Decimal("25"), "FY2029": Decimal("566.25")}
    finance_other = {"FY2026": Decimal("8.351"), "FY2027": Decimal("8.031"), "FY2028": Decimal("6.830"), "FY2029": Decimal("6.498"), "FY2030": Decimal("6.146"), "Thereafter": Decimal("51.637")}
    operating = {"FY2026": Decimal("23.884"), "FY2027": Decimal("21.242"), "FY2028": Decimal("19.576"), "FY2029": Decimal("18.314"), "FY2030": Decimal("16.982"), "Thereafter": Decimal("120.209")}
    for bucket, value in facility.items():
        notes = "The $566.25m FY2029 amount is total bank-facility principal paid in Quanex FY2029: $18.75m of quarterly Term A installments, $375.00m Term A balloon and $172.50m revolver, assuming unchanged revolver principal. It is not a maturity-date balloon." if bucket == "FY2029" else "Reported fiscal-year bank-facility principal payments."
        add("existing", "", "EXISTING-EXECUTED", bucket, "reported_bank_facility_principal_payments", value, "reported_fiscal_year_principal_payments", "supported", "SRC-001;SRC-003", "not_applicable_existing_fact", notes)
    for bucket, value in finance_other.items():
        add("existing_and_retained", "", "", bucket, "finance_leases_and_other_contractual_payments", value, "undiscounted_contractual_payments", "supported", "SRC-001", "not_applicable_existing_fact", "$24.874m aggregate present-value discount reconciles $87.493m payments to $62.619m carrying/principal amount; instrument split is not public.")
    for bucket, value in operating.items():
        add("existing_and_retained", "", "", bucket, "operating_lease_contractual_payments", value, "undiscounted_debt_like_payments_separate_from_funded_debt", "supported", "SRC-001", "not_applicable_existing_fact", "$59.302m aggregate present-value discount reconciles $220.207m payments to $160.905m lease liability.")

    def summary(structure: str, cid: str, amort: str, period_label: str, period_start: date,
                maturity: date, revolver: Decimal, owner: str, sources: str) -> None:
        term_rows = [row for row in schedule if row["structure"] == structure
                     and row["case_id"] == cid and row["amortization_case"] == amort]
        term_rows.sort(key=lambda row: (row["payment_date"], int(row["installment_number"])))
        opening = dec(term_rows[0]["beginning_principal"])
        for row in term_rows:
            if date.fromisoformat(row["payment_date"]) <= period_start:
                opening = dec(row["ending_principal"])
        in_period = [row for row in term_rows
                     if period_start < date.fromisoformat(row["payment_date"]) <= maturity]
        scheduled = sum((dec(row["scheduled_principal"]) for row in in_period), Decimal("0"))
        maturity_row = next(row for row in term_rows if row["payment_date"] == maturity.isoformat())
        final_installment = dec(maturity_row["scheduled_principal"])
        balloon = dec(maturity_row["balloon_principal"])
        term_due_at_maturity = final_installment + balloon
        funded_due_at_maturity = term_due_at_maturity + revolver
        funded_during_period = sum((dec(row["total_principal_due"]) for row in in_period), Decimal("0")) + revolver
        basis = f"authoritative_principal_schedule; period_after_{period_start.isoformat()}_through_{maturity.isoformat()}"
        notes = "Revolver equals the opening draw and is assumed unchanged through maturity solely for this principal comparison; Phase 5 must model actual draws and repayments."
        measures = (
            ("term_principal_outstanding_at_beginning_of_period", opening),
            ("revolver_principal_outstanding_at_beginning_of_period", revolver),
            ("total_funded_principal_outstanding_at_beginning_of_period", opening + revolver),
            ("scheduled_term_principal_payments_during_period", scheduled),
            ("final_scheduled_term_installment_due_on_maturity_date", final_installment),
            ("post_installment_term_balloon", balloon),
            ("total_term_principal_due_on_maturity_date", term_due_at_maturity),
            ("revolver_principal_due_on_maturity_date", revolver),
            ("total_funded_principal_due_on_maturity_date", funded_due_at_maturity),
            ("total_funded_principal_payments_during_period", funded_during_period),
            ("revolver_unchanged_through_maturity_assumption", revolver),
        )
        for category, amount in measures:
            add(structure, cid, amort, period_label, category, amount, basis,
                "supported_calculation" if structure == "existing" else "hypothetical_calculation",
                sources, owner, notes if "revolver" in category or "funded" in category else "")
        retained = finance_other.get(period_label.split("_")[0], "") if period_label.startswith("FY") else ""
        retained_status = "supported" if retained != "" else "not_determinable_from_annual_maturity_buckets"
        retained_note = "Shown separately from funded principal and at undiscounted contractual payment amounts." if retained != "" else "The public annual maturity buckets do not support an exact allocation to this period."
        add(structure, cid, amort, period_label, "retained_finance_leases_and_other_debt_maturities",
            retained, "reported_undiscounted_contractual_payments_separate_from_funded_principal",
            retained_status, "SRC-001", owner, retained_note)

    existing_maturity = date(2029, 8, 1)
    summary("existing", "", "EXISTING-EXECUTED", "FY2029_maturity_reporting_year",
            date(2028, 11, 1), existing_maturity, Decimal("172.5"),
            "not_applicable_existing_fact", "SRC-001;SRC-003")
    summary("existing", "", "EXISTING-EXECUTED", "FINAL_12M_TO_2029-08-01",
            date(2028, 8, 1), existing_maturity, Decimal("172.5"),
            "not_applicable_existing_fact", "SRC-001;SRC-003")
    proposed_maturity = date(2031, 1, 31)
    for cid in ("CC-LOW", "CC-REF", "CC-HIGH"):
        for amort in ("AMORT-5", "AMORT-10", "AMORT-15"):
            revolver = dec(results[cid]["new_revolver"])
            summary("proposed", cid, amort, "FY2031_maturity_reporting_year",
                    date(2030, 11, 1), proposed_maturity, revolver, OWNER_PHASE5, "")
            summary("proposed", cid, amort, "FINAL_12M_TO_2031-01-31",
                    date(2030, 1, 31), proposed_maturity, revolver, OWNER_PHASE5, "")
    return rows


def comparison_rows(results: dict[str, dict[str, Decimal | str]], maturities: list[dict[str, str]]) -> list[dict[str, str]]:
    ref = results["CC-REF"]
    def measure(structure: str, bucket: str, category: str) -> str:
        row = next(row for row in maturities if row["structure"] == structure
                   and row["case_id"] == ("" if structure == "existing" else "CC-REF")
                   and row["amortization_case"] == ("EXISTING-EXECUTED" if structure == "existing" else "AMORT-10")
                   and row["fiscal_bucket"] == bucket and row["obligation_category"] == category)
        return row["amount"]
    existing_fy = "FY2029_maturity_reporting_year"
    proposed_fy = "FY2031_maturity_reporting_year"
    existing_12m = "FINAL_12M_TO_2029-08-01"
    proposed_12m = "FINAL_12M_TO_2031-01-31"
    items = [
        ("Funded term debt", "468.750 at 2025-10-31", f"{fmt(ref['term_funding'])} at hypothetical close", MONEY, "SRC-001;SRC-002", "Terms out bank payoff and supported costs", "Creates scheduled deleveraging", "Higher mandatory amortization and fees; dates differ"),
        ("Revolver borrowings", "172.500 at 2025-10-31", f"{fmt(ref['new_revolver'])} opening reference draw", MONEY, "SRC-001;SRC-002", "Restores revolver toward working-capital purpose", "Visibility and control over seasonal drawings", "Actual January balance and peak need are unknown"),
        ("Facility commitments", "$500m original term plus $475m revolver", "Up to $650m term plus $300m revolver", MONEY, "SRC-003", "Potentially terms out persistent revolver use", "New underwriting and protections", "Headline total falls from $975m to $950m and term is not reusable"),
        ("LC capacity and treatment", "$30m sublimit; $6.2m outstanding", "$6.2m replacement assumed; proposed sublimit pending", MONEY, "SRC-001;SRC-003", "Avoids operational disruption if replacement agreed", "LC exposure consumes commitment", "Issuer consent and final sublimit pending"),
        ("Opening undrawn availability", "296.300 reported", fmt(ref["remaining_availability"]), MONEY, "SRC-001;SRC-003", "Reference availability remains substantial", "Explicit cap prevents overdraw", "$300m commitment is $175m smaller and not yet proven sufficient"),
        ("Final maturity", "2029-08-01", "2031-01-31", "date", "SRC-003", "Approximately 18-month extension", "Longer runway for repayment", "Limited extension relative to cost and restrictions"),
        ("Annual scheduled term amortization", "$25m", f"{fmt(dec(ref['term_funding']) * Decimal('0.10'))} base 10% case", MONEY, "SRC-003", "Faster debt reduction", "Reduces balloon", "Raises near-term debt-service burden"),
        ("Beginning funded principal in maturity reporting fiscal year", measure("existing", existing_fy, "total_funded_principal_outstanding_at_beginning_of_period"), measure("proposed", proposed_fy, "total_funded_principal_outstanding_at_beginning_of_period"), MONEY, "SRC-001;SRC-003", "Like-for-like reporting-year opening balance", "Makes the maturity build auditable", "Reporting fiscal years have different lengths before maturity"),
        ("Scheduled term principal in maturity reporting fiscal year", measure("existing", existing_fy, "scheduled_term_principal_payments_during_period"), measure("proposed", proposed_fy, "scheduled_term_principal_payments_during_period"), MONEY, "SRC-001;SRC-003", "Separates installments from balloons", "Shows contractual deleveraging", "Quanex FY2031 contains only the January 2031 proposed installment"),
        ("Final scheduled installment due on maturity date", measure("existing", existing_fy, "final_scheduled_term_installment_due_on_maturity_date"), measure("proposed", proposed_fy, "final_scheduled_term_installment_due_on_maturity_date"), MONEY, "SRC-003", "Separates same-day installment from balloon", "Prevents understated maturity-date term due", "Existing final quarterly installment is July 31, 2029, one day before maturity"),
        ("Post-installment term balloon", measure("existing", existing_fy, "post_installment_term_balloon"), measure("proposed", proposed_fy, "post_installment_term_balloon"), MONEY, "SRC-003", "True post-installment balloon comparison", "Separates residual refinance risk", "Excludes revolver and retained debt"),
        ("Total term principal due on maturity date", measure("existing", existing_fy, "total_term_principal_due_on_maturity_date"), measure("proposed", proposed_fy, "total_term_principal_due_on_maturity_date"), MONEY, "SRC-003", "Includes any same-day scheduled installment", "Prevents balloon-definition ambiguity", "Assumes no sweep or voluntary prepayment"),
        ("Revolver principal due on maturity date", measure("existing", existing_fy, "revolver_principal_due_on_maturity_date"), measure("proposed", proposed_fy, "revolver_principal_due_on_maturity_date"), MONEY, "SRC-001;SRC-003", "Shows revolver separately", "Makes maturity funding need visible", "Opening/reference revolver is assumed unchanged solely for this comparison"),
        ("Total funded principal due on maturity date", measure("existing", existing_fy, "total_funded_principal_due_on_maturity_date"), measure("proposed", proposed_fy, "total_funded_principal_due_on_maturity_date"), MONEY, "SRC-001;SRC-003", "Like-for-like same-date funded principal", "Separates maturity wall from earlier installments", "Excludes retained finance leases and other debt"),
        ("Total funded principal payments in maturity reporting fiscal year", measure("existing", existing_fy, "total_funded_principal_payments_during_period"), measure("proposed", proposed_fy, "total_funded_principal_payments_during_period"), MONEY, "SRC-001;SRC-003", "Explains the reported $566.25m correctly", "Prevents fiscal-year totals being mislabeled balloons", "$566.25m is the existing FY2029 total, not a maturity-date balloon"),
        ("Total funded principal payments in final 12 months to maturity", measure("existing", existing_12m, "total_funded_principal_payments_during_period"), measure("proposed", proposed_12m, "total_funded_principal_payments_during_period"), MONEY, "SRC-001;SRC-003", "Consistent rolling-12-month comparison", "Captures four proposed quarterly installments", "Different from the Quanex reporting fiscal-year measure"),
        ("Pricing basis and margin", "Base Rate or Adjusted Term SOFR; SOFR/RFR +200-275 bps", "Term SOFR +250-350 bps sensitivity", "basis_points", "SRC-003", "No interest-saving benefit assumed", "Sensitivity can target risk-adjusted return", "May increase cost; no lender quote"),
        ("Unused commitment fee", "0.150%-0.250% leverage-based", "pending_information", "percent", "SRC-003", "Smaller commitment could reduce gross carry", "Fee compensates undrawn liquidity", "Proposed fee and actual unused balance unknown"),
        ("Upfront and transaction costs", "$11.040m unamortized prior fees are contra-debt; fee letters private", "$10m reference sensitivity", MONEY, "SRC-001;SRC-003", "None absent refinancing", "Costs must be funded and disclosed", "Write-off, new fees, legal/admin and hedge costs may erode benefit"),
        ("Security", "First-priority liens subject to permitted liens/exclusions; domestic real property excluded in 10-K description", "Eligible domestic obligor personal property subject to confirmation", "text", "SRC-001;SRC-003", "Potential refresh of collateral diligence", "Opportunity to confirm perfection and exclusions", "Cannot assume broader coverage"),
        ("Guarantees", "Subsidiaries other than excluded subsidiaries; complete post-Tyman schedule unavailable", "Eligible material domestic subsidiaries; exclusions explicit", "text", "SRC-003", "Potential clean-up of post-Tyman joinders", "Defined guarantor coverage", "Foreign and non-guarantor structural subordination remains"),
        ("Maintenance covenants", "3.25x max CNLR and 3.00x min interest coverage", "Initially test 3.25x net leverage, 3.00x cash-interest coverage and $50m usable liquidity", "text", "SRC-003;SRC-016", "Could reset definitions and add liquidity protection", "More direct liquidity monitoring", "Proposed definitions and cushion are not final"),
        ("Restricted payments", "Detailed baskets/conditions; certain actions use 2.75x and >$25m liquidity tests", "No debt-funded buybacks; bounded distributions subject to pro forma tests", "text", "SRC-003", "Clearer policy discipline", "Protects deleveraging", "May reduce operating/shareholder flexibility"),
        ("Additional debt and acquisitions", "Permitted baskets and $310m/100% EBITDA uncommitted incremental capacity", "Consent requirements or documented baskets", "text", "SRC-003", "Can tailor post-acquisition flexibility", "Controls leverage and execution risk", "Tighter restrictions may reduce strategic flexibility"),
        ("Reporting burden", "Annual within 120 days; quarterly within 60 days; certificates", "Quarterly plus monthly liquidity/WC and annual audited reporting", "text", "SRC-003", "Earlier visibility may support relationship", "Improves monitoring", "Higher administrative burden"),
        ("Refinancing dependency", "Concentrated August 2029 maturity", "Concentrated January 2031 balloon after scheduled amortization", "text", "SRC-001;SRC-003", "Defers maturity wall", "More amortization lowers residual", "Only about 18 months of extension"),
        ("Borrower benefit", "Retain $475m revolver and avoid new transaction costs", "Term out revolver use and refresh maturity", "text", "SRC-001;SRC-003", "Benefit exists only if term-out, liquidity and maturity value exceed costs", "N/A", "A limited amendment/extension may be superior"),
        ("Principal risks", "Persistent revolver usage; 2029 maturity; existing covenant headroom unavailable", "Fees, smaller revolver, higher amortization, tighter terms and unproven opening balances", "text", "SRC-001;SRC-003", "Balanced alternative analysis", "Conditions protect against uncertainty", "Refinance must not be presumed preferable"),
    ]
    return [{
        "comparison_id": f"FC-{i:03d}", "item": item, "existing_value": existing,
        "proposed_reference_value": proposed, "units": units,
        "existing_source_ids": sources, "proposed_status": "owner_reviewed_for_phase5_testing_not_final",
        "borrower_benefit": benefit, "lender_protection": protection,
        "principal_risk": risk, "owner_review_status": OWNER_PHASE5,
        "notes": "Existing and proposed values are not represented as equivalent-date borrower facts.",
    } for i, (item, existing, proposed, units, sources, benefit, protection, risk) in enumerate(items, 1)]


def refinancing_economics_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    principal = Decimal("650")
    for existing in (Decimal("200"), Decimal("225"), Decimal("250"), Decimal("275")):
        for proposed in (Decimal("250"), Decimal("300"), Decimal("350")):
            annual = principal * (existing - proposed) / Decimal("10000")
            for fee in (Decimal("5"), Decimal("10"), Decimal("20")):
                breakeven = fee / annual if annual > 0 else None
                rows.append({
                    "economics_id": f"RE-{len(rows) + 1:04d}", "analysis_type": "spread_and_upfront_fee_break_even",
                    "principal_base": fmt(principal), "existing_margin_bps": fmt(existing),
                    "proposed_margin_bps": fmt(proposed), "annual_spread_savings_or_cost": fmt(annual),
                    "upfront_fee_sensitivity": fmt(fee), "break_even_years": fmt(breakeven) if breakeven else "N/M",
                    "within_five_year_tenor": "yes" if breakeven is not None and breakeven <= Decimal("5") else "no",
                    "units": MONEY, "classification": "hypothetical_sensitivity", "source_ids": "SRC-003",
                    "owner_review_status": OWNER_METHODOLOGY,
                    "notes": "Positive annual value is spread savings; negative is incremental cost. Same SOFR base assumed solely to isolate margin. Excludes revolver mix, base-rate floors, hedge effects, fee amortization, taxes and principal decline. No spread is a lender quote. Owner review retains the existing facilities and a limited amendment/extension as live alternatives; this sensitivity does not establish refinancing preference.",
                })
    for margin in (Decimal("0.150"), Decimal("0.250")):
        annual_fee = Decimal("296.3") * margin / Decimal("100")
        rows.append({
            "economics_id": f"RE-{len(rows) + 1:04d}", "analysis_type": "existing_unused_commitment_fee_diagnostic",
            "principal_base": "296.3", "existing_margin_bps": fmt(margin * Decimal("100")),
            "proposed_margin_bps": "", "annual_spread_savings_or_cost": fmt(-annual_fee),
            "upfront_fee_sensitivity": "", "break_even_years": "N/M", "within_five_year_tenor": "no",
            "units": MONEY, "classification": "calculated_from_existing_fact", "source_ids": "SRC-001;SRC-003",
            "owner_review_status": "not_applicable_existing_fact",
            "notes": "Existing annual unused-fee run-rate on October 31 reported availability; actual average unused commitment differs. Proposed fee is pending, so no savings claim is made. Existing and limited amendment/extension alternatives remain live.",
        })
    return rows


def condition_precedent_rows() -> list[dict[str, str]]:
    items = [
        ("Payoff letters", "Exact principal, accrued interest, fees and wire instructions", "Borrower/Existing agent", "Executed payoff letter and funds-flow approval", "At least 2 business days before close", "Not waivable without replacement evidence", "No closing; bank debt amount is unverified", "private_essential", "SRC-003"),
        ("Existing lien releases", "Avoid competing liens and confirm discharge", "Existing agent/New counsel", "Release documents and UCC/IP termination authorization", "Closing", "Not waivable for first-priority structure", "No closing or expressly junior/unperfected position", "private_essential", "SRC-003"),
        ("New lien perfection", "Create and perfect proposed collateral package", "Borrower/New agent counsel", "Executed security documents, filings, searches and control agreements", "Closing/post-close period only if tightly bounded", "Limited post-close undertakings only", "No closing or documented collateral exception", "hypothetical_essential", "SRC-003"),
        ("Guarantee execution", "Establish eligible domestic subsidiary support", "Borrower/New agent counsel", "Current entity chart, guaranty and joinders", "Closing", "Only agreed excluded subsidiaries", "No closing or reduced approved credit support", "hypothetical_essential", "SRC-003"),
        ("Corporate authority", "Ensure enforceable execution and borrowing authority", "Borrower counsel", "Resolutions, incumbency, charter documents and good standing", "Closing", "Not waivable", "No closing", "standard_hypothetical", "SRC-003"),
        ("KYC and beneficial ownership", "Meet AML/sanctions and onboarding requirements", "Borrower/Lenders", "KYC, beneficial-ownership and sanctions materials", "Before funding", "Not waivable where legally required", "No funding", "standard_hypothetical", "SRC-003"),
        ("Legal opinions", "Confirm authorization, enforceability and security", "Borrower counsel", "Corporate, enforceability and security opinions by jurisdiction", "Closing", "Scope exceptions subject to lender approval", "No closing or explicit risk acceptance", "hypothetical_essential", "SRC-003"),
        ("Existing compliance certificate", "Verify no default and current headroom", "Borrower", "Latest delivered certificate and detailed calculation", "Before commitment/close", "Not waivable without lender credit approval", "Stop underwriting or require cure/waiver", "private_essential", "SRC-001;SRC-003;SRC-016"),
        ("Projected compliance certificate", "Test proposed structure under agreed definitions", "Borrower/CFO", "Pro forma certificate using final debt and approved EBITDA", "Closing", "Not waivable without credit approval", "No closing or resize/restructure", "hypothetical_essential", "SRC-003"),
        ("January closing-balance certificate", "Replace October facts with actual closing balances", "Borrower/CFO", "Term, revolver, cash, LC, other debt and working-capital certificate", "Closing", "Not waivable", "No closing or delayed funding", "private_essential", "SRC-001;SRC-003"),
        ("Minimum usable liquidity", "Protect operations at close", "Borrower/New agent", "Sources/uses and liquidity certificate under final definition", "Closing", "Only with credit approval", "No closing or add equity/reduce uses", "hypothetical_essential", ""),
        ("Borrower cash contribution", "Avoid unsupported debt funding where required", "Borrower", "Accessible-cash evidence and funds flow", "Closing if required", "May be zero only if approved sources fully cover uses", "Funding gap remains or transaction resizes", "pending_information", "SRC-001;SRC-003"),
        ("LC replacement", "Maintain operating instruments without double funding", "Borrower/Existing and new issuing banks", "LC schedule, beneficiaries, replacement/cash-collateral mechanics", "Closing", "Not waivable while exposure remains", "No closing or cash collateral included once", "private_essential", "SRC-001;SRC-003"),
        ("Hedge treatment", "Quantify survival, novation or break cost", "Borrower/Treasury counterparties", "Hedge schedule, consents and termination quotes", "Before final sources and uses", "Only if no affected hedge exists", "No closing or funded documented cost", "private_essential", "SRC-003"),
        ("Fee letters", "Establish pricing, OID, upfront, agency and unused fees", "Arranger/New agent", "Executed fee and engagement letters", "Before commitment/close", "Commercial terms require approval", "No economic recommendation or closing", "private_essential", "SRC-003"),
        ("Sources-and-uses confirmation", "Prevent hidden uses or balancing plugs", "Borrower/Arranger", "Final funds flow tied to payoff, fees and cash", "Closing", "Not waivable", "No funding", "hypothetical_essential", ""),
        ("Financial projections", "Test repayment and covenant capacity", "Borrower/CFO", "Approved integrated base/downside forecast", "Before final approval", "Not waivable for underwriting", "No final structure approval", "private_essential", "SRC-003"),
        ("Quality-of-earnings and adjustment support", "Validate material EBITDA adjustments and cash timing", "Borrower/CFO/Advisors", "Adjustment schedules, invoices, accruals and realization evidence", "Before final approval", "Only explicit conservative treatment", "Reduce EBITDA or resize structure", "private_essential", "SRC-001;SRC-002"),
        ("Maintenance-capex schedule", "Protect asset base and avoid overstated free cash flow", "Borrower/Operations", "Maintenance, safety, integration and expansion split", "Before Phase 5 approval", "Not waivable without conservative floor", "Use conservative capex or stop capacity conclusion", "private_essential", "SRC-001"),
        ("Working-capital reporting", "Resolve AP and other operating balance methods and seasonality", "Borrower/CFO", "Monthly historical and projected AR, inventory, AP and other operating WC", "Before Phase 5 approval and monthly thereafter", "Not waivable without conservative method", "No reliable liquidity/capacity conclusion", "private_essential", "SRC-001;SRC-021"),
        ("Control-remediation plan", "Address cash-flow reporting material weakness", "Borrower/Audit committee", "Milestones, testing results, owners and reporting controls", "Before close and monitored post-close", "May allow monitored post-close milestones", "Enhanced reporting, reservation or no closing", "private_essential", "SRC-001"),
        ("Full committed financing", "Eliminate syndication and funding gap risk", "Arranger/Lenders", "Executed commitments totaling approved facilities", "Before/at closing", "Not waivable", "No closing", "hypothetical_essential", ""),
        ("No material adverse change", "Protect against deterioration between approval and close", "Borrower", "Bring-down certificate under negotiated definition", "Closing", "Subject to agreed carve-outs and credit approval", "No closing or waiver/escalation", "hypothetical_negotiation", ""),
        ("Required consents", "Avoid contractual or regulatory breach", "Borrower/Counsel", "Third-party, lease, regulatory and corporate consents", "Closing or bounded post-close only", "Only immaterial exceptions approved by counsel/lenders", "No closing or excluded obligation/asset", "private_essential", "SRC-003"),
    ]
    return [{
        "condition_id": f"CP-{i:03d}", "description": desc, "risk_addressed": risk,
        "responsible_party": party, "evidence_required": evidence, "timing": timing,
        "waivability": waiver, "consequence_if_unmet": consequence,
        "public_or_hypothetical_status": status, "source_ids": sources,
        "owner_review_status": OWNER_METHODOLOGY,
        "notes": "Owner review approves the condition category and consequence as methodology only; it does not establish satisfaction. Evidence remains required at the stated time.",
    } for i, (desc, risk, party, evidence, timing, waiver, consequence, status, sources) in enumerate(items, 1)]


def phase5_input_rows(results: dict[str, dict[str, Decimal | str]]) -> list[dict[str, str]]:
    ref = results["CC-REF"]
    items = [
        ("required_opening_cash", "25", MONEY, "provisional", "SRC-001", "Phase 4 operating-cash floor; not accessible funding", "Test by entity and operating need"),
        ("accessible_cash_determination", "", MONEY, "pending_information", "SRC-001;SRC-003", "$76.018m book cash, including $46.9m foreign, is not automatically accessible", "Determine unrestricted domestic/foreign cash, tax, lien and operating constraints"),
        ("opening_term_principal", fmt(ref["term_funding"]), MONEY, "provisional_reference_case", "", "Capped funding waterfall from reference uses", "Replace with final owner-approved closing case and payoff"),
        ("opening_revolver_draw", fmt(ref["new_revolver"]), MONEY, "provisional_reference_case", "", "Residual reference use after capped term and zero cash contribution", "Replace with final funds flow; model later seasonal movement separately"),
        ("letter_of_credit_usage", fmt(ref["lc_replacement"]), MONEY, "sensitivity", "SRC-001;SRC-003", "Reference assumes noncash replacement under new revolver", "Confirm issuer, sublimit and beneficiary acceptance"),
        ("revolver_commitment", "300", MONEY, "provisional", "", "Governing case architecture", "Test daily/monthly usable liquidity and peak need"),
        ("retained_finance_leases_and_other_debt", "62.619", MONEY, "known_at_2025_10_31", "SRC-001;SRC-002", "Retained outside bank payoff", "Roll forward to closing from instrument schedules"),
        ("retained_operating_lease_liabilities", "160.905", MONEY, "known_at_2025_10_31", "SRC-001", "Debt-like retained obligation; not funded debt", "Roll forward and retain separate treatment"),
        ("term_sofr_curve_or_base_rate", "", "percent", "pending_information", "", "No cutoff-compliant closing rate selected", "Select documented cutoff-consistent forward/base-rate assumptions"),
        ("term_and_revolver_margin", "250-350", "basis_points", "sensitivity", "", "Hypothetical range, not a lender quote", "Select final pricing grid/floor after proposal"),
        ("annual_term_amortization", "10", "percent_of_original_principal", "provisional", "", "Base term-sheet case; 5% and 15% sensitivities retained", "Run all cases against forecast cash generation"),
        ("fee_amortization_treatment", "", "text", "pending_information", "SRC-001", "$11.040m existing deferred costs and new costs require accounting analysis", "Define cash/noncash and tax treatment without adding to principal payoff"),
        ("cash_interest_inputs", "", "text", "pending_information", "SRC-001;SRC-003", "Need benchmark, margins, floors, timing, hedge and average balances", "Build integrated interest only in Phase 5 after approval"),
        ("cash_sweep", "50", "percent_of_defined_excess_cash_flow", "provisional", "", "Hypothetical test with liquidity safeguards", "Define ECF, deductions, threshold, step-down and payment date"),
        ("operating_cash_floor", "25", MONEY, "provisional", "", "Distinct from $50m usable-liquidity covenant", "Test against seasonal operating need and accessible cash"),
        ("net_leverage_covenant", "3.25x then test 3.00x from FY2028", "turns", "initial_analytical_test_threshold", "SRC-003;SRC-016", "Owner-reviewed Phase 5 analytical threshold, not a final covenant or existing contractual calculation", "Test capacity; Phase 7 defines funded debt, eligible cash, EBITDA, cure and step timing"),
        ("cash_interest_coverage_covenant", "3.00", "turns", "initial_analytical_test_threshold", "SRC-003", "Owner-reviewed Phase 5 analytical threshold, not a final covenant", "Test capacity; Phase 7 defines numerator, cash interest and exclusions"),
        ("usable_liquidity_covenant", "50", MONEY, "initial_analytical_test_threshold", "", "Owner-reviewed Phase 5 analytical threshold, not a final covenant", "Test capacity; Phase 7 defines accessible cash, available revolver and reporting frequency"),
        ("closing_funding_gap_after_revolver", fmt(ref["funding_gap"]), MONEY, "calculated_reference_case", "", "Capped sources less uses", "Recalculate with actual payoff and committed terms"),
        ("term_only_funding_gap", fmt(ref["term_only_gap"]), MONEY, "calculated_reference_case", "", "Amount requiring reference opening revolver absent accessible cash", "Owner approve funding mix"),
        ("accounts_payable_method", "", "text", "pending_information", "SRC-001", "DPO remains not determinable without purchases", "Approve separate AP driver; do not use zero or a funding plug"),
        ("other_operating_working_capital_method", "", "text", "pending_information", "SRC-001", "Other current operating assets/liabilities require separate methods", "Approve balances and drivers; do not default to zero"),
        ("forecast_period_timing", "Quanex fiscal quarters ending Jan 31, Apr 30, Jul 31, Oct 31", "text", "known_convention", "SRC-001", "Closing coincides with fiscal quarter end", "Define beginning/end-of-period debt, interest and cash-flow timing"),
        ("first_term_payment_timing", "2026-04-30 modeled calendar anchor", "date", "provisional", "", "Full-quarter 2.5% installment in 10% base case", "Conform to final business-day and stub provisions"),
        ("distribution_policy", "$0-$10m repurchases; $14-$15m dividends reference", MONEY, "owner_reviewed_phase3_range", "SRC-001", "Unmitigated cases retain selected base policy", "Select periodization; show reductions only as separate mitigations"),
        ("reference_revolver_movement_calibration", "25", MONEY, "owner_reviewed_principal_balance_sensitivity", "SRC-021", "Informed by the $24.134m FY2025 Q1 FCF trough but not an October-to-January cash forecast or separate historical FCF use", "Replace with an integrated cash, interest and revolver calculation; reconcile accrued payoff interest without double counting"),
        ("pressure_case_restricted_cash_from_lc_collateral", "6.2", MONEY, "owner_reviewed_pressure_sensitivity", "SRC-001;SRC-003", "Explicitly funded LC collateral creates restricted cash or another restricted asset and is excluded from usable liquidity", "Keep separate from operating cash; do not also deduct replacement LCs"),
        ("revolver_maturity_assumption", "Opening draw held unchanged solely for maturity comparison", "text", "owner_reviewed_methodology", "", "No future revolver draws or repayments are projected in Phase 4", "Replace with the integrated Phase 5 revolver schedule"),
        ("financing_alternative_decision", "Test reference refinancing; retain existing facilities and limited amendment/extension as live alternatives", "text", "owner_reviewed_methodology", "SRC-001;SRC-003", "Phase 4 does not establish that refinancing is economically preferable", "Compare debt capacity and downside results before selecting a structure"),
    ]
    return [{
        "input_id": f"P5-{i:03d}", "input_name": name, "reference_case_value": value,
        "units": units, "input_status": status, "source_ids": sources,
        "calculation_or_basis": basis, "phase5_required_action": action,
        "owner_review_status": (
            "not_applicable_existing_fact" if status in {"known_at_2025_10_31", "known_convention"}
            else "owner_reviewed" if status == "owner_reviewed_phase3_range"
            else OWNER_THRESHOLD if name in {"net_leverage_covenant", "cash_interest_coverage_covenant", "usable_liquidity_covenant"}
            else OWNER_PENDING if status == "pending_information"
            else OWNER_PHASE5
        ),
        "notes": "Phase 5 must not convert a pending item to zero or treat the partial contractual EBITDA reconstruction as official.",
    } for i, (name, value, units, status, sources, basis, action) in enumerate(items, 1)]


def source_catalog() -> dict[str, dict[str, str]]:
    catalog: dict[str, dict[str, str]] = {}
    for row in read_csv(PHASE1_MANIFEST):
        catalog[row["source_id"]] = {
            "title": row["document_title"], "publication": row["publication_or_filing_date"],
            "url": row["source_url"],
        }
    for row in read_csv(PHASE3_SOURCES):
        catalog[row["source_id"]] = {
            "title": row["document_title"], "publication": row["publication_date"],
            "url": row["source_url"],
        }
    return catalog


def source_ledger_rows(file_rows: list[tuple[str, str, list[dict[str, str]], str, str, str]]) -> list[dict[str, str]]:
    catalog = source_catalog()
    ledger: list[dict[str, str]] = []
    for output_file, layer, rows, id_field, item_field, value_field in file_rows:
        for row in rows:
            source_ids = [sid for sid in row.get("source_ids", "").split(";") if sid]
            ledger.append({
                "record_id": row[id_field], "output_file": output_file, "layer": layer,
                "metric_or_item": row[item_field], "value": row.get(value_field, ""),
                "units": row.get("units", "text"), "source_ids": ";".join(source_ids),
                "document_titles": semis(catalog[sid]["title"] for sid in source_ids),
                "source_urls": semis(catalog[sid]["url"] for sid in source_ids),
                "publication_dates": semis(catalog[sid]["publication"] for sid in source_ids),
                "source_reference": (row.get("source_reference") or row.get("calculation")
                                     or row.get("calculation_or_basis", "")),
                "classification": (row.get("classification") or row.get("status")
                                   or row.get("source_or_hypothetical_status")
                                   or row.get("public_or_hypothetical_status")
                                   or row.get("input_status") or row.get("determinability_status")
                                   or row.get("proposed_status") or layer),
                "owner_review_status": row.get("owner_review_status", ""),
                "notes": row.get("notes", ""),
            })
    return ledger


def document_texts(results: dict[str, dict[str, Decimal | str]], term_rows: list[dict[str, str]],
                   comparison: list[dict[str, str]], conditions: list[dict[str, str]],
                   phase5: list[dict[str, str]], maturities: list[dict[str, str]]) -> dict[Path, str]:
    def money(value: Decimal | str) -> str:
        return f"{dec(value):,.3f}"

    case_lines = []
    for cid in ("CC-LOW", "CC-REF", "CC-HIGH"):
        r = results[cid]
        case_lines.append(
            f"| {cid} / {r['case_name']} | {money(r['bank_payoff'])} | {money(r['total_uses'])} | "
            f"{money(r['term_funding'])} | {money(r['term_only_gap'])} | {money(r['new_revolver'])} | "
            f"{money(r['remaining_availability'])} | {money(r['funding_gap'])} |"
        )
    def maturity_amount(structure: str, cid: str, amort: str, bucket: str, category: str) -> str:
        return next(row["amount"] for row in maturities
                    if row["structure"] == structure and row["case_id"] == cid
                    and row["amortization_case"] == amort and row["fiscal_bucket"] == bucket
                    and row["obligation_category"] == category)

    maturity_categories = (
        ("Term principal at period beginning", "term_principal_outstanding_at_beginning_of_period"),
        ("Scheduled term principal during period", "scheduled_term_principal_payments_during_period"),
        ("Final installment due on maturity date", "final_scheduled_term_installment_due_on_maturity_date"),
        ("Post-installment term balloon", "post_installment_term_balloon"),
        ("Total term principal due on maturity date", "total_term_principal_due_on_maturity_date"),
        ("Revolver principal due on maturity date", "revolver_principal_due_on_maturity_date"),
        ("Total funded principal due on maturity date", "total_funded_principal_due_on_maturity_date"),
        ("Total funded principal payments during period", "total_funded_principal_payments_during_period"),
    )
    maturity_lines = []
    for label, category in maturity_categories:
        maturity_lines.append(
            f"| {label} | {maturity_amount('existing', '', 'EXISTING-EXECUTED', 'FY2029_maturity_reporting_year', category)} | "
            f"{maturity_amount('proposed', 'CC-REF', 'AMORT-10', 'FY2031_maturity_reporting_year', category)} | "
            f"{maturity_amount('existing', '', 'EXISTING-EXECUTED', 'FINAL_12M_TO_2029-08-01', category)} | "
            f"{maturity_amount('proposed', 'CC-REF', 'AMORT-10', 'FINAL_12M_TO_2031-01-31', category)} |"
        )
    methodology = f"""# Phase 4 methodology

**Information cutoff:** December 15, 2025
**Hypothetical closing:** January 31, 2026

## Scope and classification

Phase 4 converts the approved debt evidence into a debt-instrument register,
public legal-structure map, three closing sensitivities, sources and uses,
principal-only schedules, a provisional term sheet, refinancing economics,
closing conditions, and Phase 5 opening inputs. It does not use actual January
2026 information, build an operating forecast, integrate interest, finalize debt
capacity or covenants, or begin Phase 5.

Reported October 31 facts remain separate from formula-driven calculations,
hypothetical proposed terms, sensitivities, and pending private information.
The three closing cases and the selected provisional structure are now
owner-reviewed only for Phase 5 testing. That status does not turn a sensitivity
into an actual January balance, a lender commitment, a final covenant, or a
satisfied closing condition. Unselected and private terms remain pending.

## Closing cases

The cases are not forecasts. They test unresolved mechanics without a cash plug.
The reference $25m revolver movement is a principal-balance sensitivity informed
by the observed $24.134m FY2025 Q1 FCF trough; the $50m pressure movement is an
approximately two-times calibration. Historical FCF is not a detailed
October-to-January cash forecast or a separately additive closing use. Accrued
interest is unpaid payoff interest calculated at the reported 6.57% October
rate for 0/30/60 days. Phase 5 must replace this shortcut with an integrated
cash, interest and revolver schedule and reconcile the two so cash interest
already embedded in historical FCF is not counted twice. Exact payoff, fee,
hedge and LC amounts remain closing diligence.

| Case | Bank payoff | Total uses | New term | Term-only gap | Opening revolver | Nominal availability | Residual gap |
|---|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(case_lines)}

The funding waterfall uses approved borrower cash first (zero in every case
because accessible cash is not publicly established), then new term funding up
to $650m, then an explicit opening revolver draw up to the unused $300m capacity
after replacement LCs. Any residual remains a visible funding gap. The revolver
draw is therefore a documented source, not an unexplained balancing plug.

The January $6.25m old-facility amortization is paid before closing only in the
low case. In the reference case it is identified as a component of the full
payoff and is not added twice. In the pressure case the old installment would
fall after/collapse into refinancing and therefore does not occur separately.

In the pressure case, $6.2m is funded once as LC cash collateral. It creates
restricted cash or another separately classified restricted asset, is excluded
from usable operating liquidity, and is not also deducted as a replacement LC.
Replacement under a new revolver would be a separate alternative, never a
simultaneous second treatment.

## Debt and lease measurement

Bank leverage and payoff use gross principal. The $11.040m deferred-financing-
cost balance is contra-debt, not principal. The $62.619m finance leases and other
debt are retained: $60.733m is identifiable finance-lease liability and the
$1.886m balance is a calculated other-debt residual. Operating leases of
$160.905m are retained separately and are not called funded debt.

Lease maturity rows preserve undiscounted contractual payments. They must not be
summed to present-value liabilities without the disclosed discount. Proposed
term schedules have 20 full quarterly installments beginning April 30, 2026;
actual business-day and stub provisions require final documents.

## Corrected maturity definitions

Section 2.3 of the executed agreement requires the existing Term A to amortize
on the last Business Day of each fiscal quarter. The $468.75m October 31, 2025
balance implies 15 remaining $6.25m installments from January 2026 through July
2029, followed by a $375.00m term balloon on August 1, 2029. The schedule uses a
weekend-adjusted last-weekday proxy; the Agent holiday calendar remains payoff
diligence.

The reported $566.25m is **not** a maturity-date balloon. It is total bank-
facility principal paid in Quanex FY2029: $18.75m of quarterly installments,
$375.00m of Term A balloon, and $172.50m of assumed unchanged revolver principal.
The actual funded principal due on August 1, 2029 is $547.50m because the final
$6.25m quarterly installment occurs July 31, 2029.

The table separates the Quanex reporting fiscal year containing maturity from
the final rolling 12 months ending at maturity. This is necessary because
Quanex FY2031 contains only the January 31, 2031 proposed payment, while the
rolling 12-month period contains four quarterly payments.

| Measure ($m) | Existing FY2029 | Proposed reference FY2031 | Existing final 12m | Proposed reference final 12m |
|---|---:|---:|---:|---:|
{chr(10).join(maturity_lines)}

Retained finance-lease and other-debt maturities stay separate. The public
annual buckets provide $6.498m for FY2029 but place FY2031 and later payments in
an unallocated `Thereafter` bucket, so an exact proposed-maturity-period amount
is not determinable. Revolver principal is held unchanged from the applicable
starting/reference balance solely for this maturity comparison.

## Economics and limitations

Spread break-even uses a constant $650m principal only to isolate existing
SOFR-margin bands of 200-275 bps from hypothetical proposed spreads of 250-350
bps. It excludes principal decline, revolver mix, benchmark/floor differences,
hedges, taxes and fee accounting. Positive values are annual spread savings;
negative values are costs. No proposed spread or fee is a market quote.

The reference case leaves no residual funding gap after a calculated
${money(results['CC-REF']['new_revolver'])}m opening revolver draw, but this is
not evidence that a $300m revolver is sufficient through seasonal or downside
conditions. That question belongs to Phase 5-6.

Owner review directs Phase 5 to test the reference refinancing while retaining
the existing facilities and a limited amendment/extension as live alternatives.
Phase 4 does not establish that refinancing is economically preferable: the
maturity extension is only about 18 months, the revolver is $175m smaller,
reference opening availability is below reported existing availability,
scheduled amortization is higher, and pricing may be more expensive. Only the
most favorable spread pairing produces savings, and fee recovery can consume
much of the five-year tenor.

## Reproduction

```powershell
python scripts/phase1.py validate
python scripts/phase2.py all
python scripts/phase3.py all
python scripts/phase4.py all
python -m unittest discover -s tests -v
powershell -ExecutionPolicy Bypass -NoProfile -File scripts/validate-phase0.ps1
```

Python standard library only; the workflow performs no live network access.
"""
    def term_display(row: dict[str, str]) -> str:
        value, units = row["proposed_value"], row["units"]
        if value == "pending_information" or units in {"text", "date", "formula", "basis_points", "turns"}:
            return value
        if units == MONEY:
            return f"${value}m"
        if units == "years":
            return f"{value} years"
        if units == "percent_of_original_principal":
            return f"{value.replace(';', '% / ')}% of original principal"
        if units == "percent_of_defined_excess_cash_flow":
            return f"{value}% of defined excess cash flow"
        return f"{value} {units}"

    term_lines = "\n".join(
        f"| {row['term_id']} | {row['term_name']} | {term_display(row)} | {row['purpose']} | {row['open_negotiation_issue']} | {row['owner_review_status']} |"
        for row in term_rows
    )
    term_sheet = f"""# Provisional proposed term sheet

Every proposed term below is hypothetical. Selected terms are owner-reviewed
only for Phase 5 testing; remaining private or unselected terms stay pending.
No owner-review status is a lender quote, commitment, borrower-approved final
term, satisfied closing condition, or official compliance calculation.

| ID | Term | Proposed value | Purpose | Open issue | Owner review |
|---|---|---|---|---|---|
{term_lines}

## Structural caveats

The five-year maturity reaches January 31, 2031, only about 18 months beyond the
existing August 1, 2029 maturity. The proposed revolver is $175m smaller than the
existing commitment. Faster amortization lowers the balloon but increases
near-term debt service. The 3.25x net-leverage, 3.00x cash-interest-coverage,
$50m usable-liquidity and FY2028 3.00x leverage thresholds are initial analytical
tests only; Phase 7 owns final covenant design. Security and guarantees remain
subject to post-Tyman joinders, excluded subsidiaries, lien perfection,
deposit-account control, foreign-equity limitations, permitted liens and legal
opinions. Phase 5-6 must compare the reference test structure with retaining or
amending the existing facilities.
"""
    legal = """# Public legal-structure summary

Quanex Building Products Corporation is the existing borrower. The agreement
requires subsidiary guarantees other than for foreign and qualifying immaterial
domestic subsidiaries. Public amendment signatures identify several domestic
loan parties as of June 2024, but they do not establish a complete post-Tyman
guarantor schedule at October 2025 or the hypothetical close.

The public framework supports first-priority liens, subject to permitted liens
and excluded assets, on substantially all loan-party assets. The FY2025 10-K
describes substantially all domestic assets other than real property as
collateral. It does not establish current lien perfection, deposit-account
control, every Tyman joinder, pledged equity, or every excluded asset.

Foreign subsidiaries are excluded guarantors under the existing agreement. A
first-tier foreign equity pledge is limited to up to 65% of voting and 100% of
nonvoting interests where applicable; this is not a lien on foreign operating
assets. Of $76.018m book cash, $46.9m was held abroad. Neither amount is assumed
accessible for closing or repayment. Non-guarantor creditors may be structurally
senior with respect to their entities' assets and cash flows.

The owner-reviewed Phase 5 test concept uses eligible domestic guarantees and
personal-property collateral, but it remains hypothetical. Closing requires current entity,
guarantor, collateral, lien, control-agreement, perfection, cash-access and
release evidence. Public filings are not substitutes for those private legal
confirmations.
"""
    cp_essential = sum(1 for row in conditions if "essential" in row["public_or_hypothetical_status"])
    pending_inputs = sum(1 for row in phase5 if row["input_status"] == "pending_information")
    handoff = f"""# Phase 5 opening-input handoff

Phase 5 should test the owner-reviewed reference closing case, not treat it as an
actual January balance. The current reference is ${money(results['CC-REF']['term_funding'])}m
term funding, ${money(results['CC-REF']['new_revolver'])}m opening revolver draw,
$6.200m replacement LCs and ${money(results['CC-REF']['remaining_availability'])}m
nominal opening revolver availability. Actual payoff, cash and committed terms
must replace these sensitivities before approval.

The $25m revolver movement is a principal-balance calibration informed by the
$24.134m FY2025 Q1 FCF trough, not a detailed cash forecast. The separately
modeled ${money(results['CC-REF']['accrued_interest'])}m accrued-interest use is
unpaid payoff interest. Phase 5 must integrate cash, interest and revolver
movement and prevent double counting of historical cash interest. The pressure
case funds $6.2m of LC collateral once as restricted cash, excludes it from
usable liquidity, and assumes no simultaneous replacement LC.

There are {pending_inputs} inputs explicitly marked pending information. Core
items include accessible cash, the cutoff-consistent benchmark/rate curve, cash
interest mechanics, fee accounting, AP and other operating working-capital
methods. DPO remains not determinable. Neither AP nor other working capital may
default to zero or become a funding plug.

Phase 5 must retain $62.619m finance leases/other debt and separately retain
$160.905m operating lease liabilities, roll both to closing, and avoid adding the
$11.040m deferred-financing-cost balance to payoff principal. It must use the
owner-reviewed FY2025 lender-base EBITDA of $225.344m without relabeling the
partial contractual reconstruction as official compliance EBITDA.

The proposed 10% amortization case pays 2.5% of original principal quarterly;
5% and 15% alternatives remain required. No Phase 4 schedule includes cash
sweeps, voluntary repayment, future revolver movement or integrated interest.
For the $650m reference/10% case, the authoritative schedule produces a
$325.000m post-installment term balloon, $341.250m total term due on the January
31, 2031 maturity date, $371.148m total funded principal due on that date with
the unchanged $29.898m opening revolver, and $419.898m of funded principal
payments in the final rolling 12 months.

The 3.25x net-leverage, 3.00x cash-interest-coverage, $50m usable-liquidity and
FY2028 3.00x leverage thresholds are owner-reviewed initial analytical tests,
not final covenants. Phase 5 must show whether the reference structure can meet
them; Phase 7 owns final covenant design.

The owner-reviewed financing decision is to proceed to Phase 5 with the
reference refinancing as a test case while retaining the existing facilities
and a limited amendment/extension as live alternatives. Refinancing is not
approved or established as economically preferable.

The conditions register contains {len(conditions)} items, including
{cp_essential} explicitly essential public/private or hypothetical conditions.
No missing payoff, LC, lien, guarantee, cash-access, hedge, fee, projection or
working-capital evidence is treated as satisfied. Owner review approves the 20
essential and four additional condition categories and their consequences as
methodology only, not the satisfaction of any condition.
"""
    return {
        DOCS / "METHODOLOGY.md": methodology,
        DOCS / "PROVISIONAL_TERM_SHEET.md": term_sheet,
        DOCS / "LEGAL_STRUCTURE_SUMMARY.md": legal,
        DOCS / "PHASE5_HANDOFF.md": handoff,
    }


def build() -> dict[str, int]:
    inputs = read_csv(RAW / "CLOSING_CASE_INPUTS.csv")
    term_inputs = read_csv(RAW / "PROPOSED_TERM_INPUTS.csv")
    results = calculate_closing_cases(inputs)
    instruments = debt_instrument_rows()
    legal = legal_structure_rows()
    bridges = closing_bridge_rows(inputs, results)
    sources_uses = sources_uses_rows(results)
    schedules = debt_schedule_rows(results)
    maturities = maturity_rows(schedules, results)
    comparisons = comparison_rows(results, maturities)
    economics = refinancing_economics_rows()
    conditions = condition_precedent_rows()
    phase5 = phase5_input_rows(results)

    output_specs = [
        (PROCESSED / "DEBT_INSTRUMENT_REGISTER.csv", instruments, INSTRUMENT_FIELDS),
        (PROCESSED / "LEGAL_STRUCTURE_REGISTER.csv", legal, LEGAL_FIELDS),
        (PROCESSED / "CLOSING_BRIDGE.csv", bridges, BRIDGE_FIELDS),
        (PROCESSED / "SOURCES_AND_USES.csv", sources_uses, SOURCES_USES_FIELDS),
        (PROCESSED / "DEBT_SCHEDULE.csv", schedules, DEBT_SCHEDULE_FIELDS),
        (PROCESSED / "MATURITY_SCHEDULE.csv", maturities, MATURITY_FIELDS),
        (PROCESSED / "FINANCING_COMPARISON.csv", comparisons, COMPARISON_FIELDS),
        (PROCESSED / "REFINANCING_ECONOMICS.csv", economics, ECONOMICS_FIELDS),
        (PROCESSED / "CONDITIONS_PRECEDENT.csv", conditions, CP_FIELDS),
        (PROCESSED / "PHASE5_OPENING_INPUTS.csv", phase5, PHASE5_FIELDS),
    ]
    for path, rows, fields in output_specs:
        write_csv(path, rows, fields)

    texts = document_texts(results, term_inputs, comparisons, conditions, phase5, maturities)
    for path, content in texts.items():
        write_text(path, content)

    ledger_specs = [
        ("data/phase4/raw/CLOSING_CASE_INPUTS.csv", "owner_reviewed_closing_sensitivities", inputs, "case_id", "case_name", "status"),
        ("data/phase4/raw/PROPOSED_TERM_INPUTS.csv", "hypothetical_term_inputs", term_inputs, "term_id", "term_name", "proposed_value"),
        ("data/phase4/processed/DEBT_INSTRUMENT_REGISTER.csv", "debt_instruments", instruments, "instrument_id", "instrument_name", "principal_balance"),
        ("data/phase4/processed/LEGAL_STRUCTURE_REGISTER.csv", "legal_structure", legal, "legal_item_id", "topic", "status"),
        ("data/phase4/processed/CLOSING_BRIDGE.csv", "closing_bridge", bridges, "bridge_id", "item", "closing_value"),
        ("data/phase4/processed/SOURCES_AND_USES.csv", "sources_and_uses", sources_uses, "sources_uses_id", "item", "amount"),
        ("data/phase4/processed/DEBT_SCHEDULE.csv", "principal_schedule", schedules, "schedule_id", "payment_date", "total_principal_due"),
        ("data/phase4/processed/MATURITY_SCHEDULE.csv", "maturity_schedule", maturities, "maturity_id", "obligation_category", "amount"),
        ("data/phase4/processed/FINANCING_COMPARISON.csv", "financing_comparison", comparisons, "comparison_id", "item", "proposed_reference_value"),
        ("data/phase4/processed/REFINANCING_ECONOMICS.csv", "refinancing_economics", economics, "economics_id", "analysis_type", "annual_spread_savings_or_cost"),
        ("data/phase4/processed/CONDITIONS_PRECEDENT.csv", "conditions_precedent", conditions, "condition_id", "description", "public_or_hypothetical_status"),
        ("data/phase4/processed/PHASE5_OPENING_INPUTS.csv", "phase5_handoff", phase5, "input_id", "input_name", "reference_case_value"),
    ]
    ledger = source_ledger_rows(ledger_specs)
    write_csv(DOCS / "SOURCE_LEDGER.csv", ledger, LEDGER_FIELDS)
    return {
        "closing_cases": len(inputs), "proposed_terms": len(term_inputs),
        "debt_instruments": len(instruments), "legal_items": len(legal),
        "bridge_rows": len(bridges), "sources_uses_rows": len(sources_uses),
        "schedule_rows": len(schedules), "maturity_rows": len(maturities),
        "comparison_rows": len(comparisons), "economics_rows": len(economics),
        "conditions": len(conditions), "phase5_inputs": len(phase5), "ledger_rows": len(ledger),
    }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generated_files() -> list[Path]:
    files = list(RAW.glob("*.csv")) + list(PROCESSED.glob("*.csv")) + list(DOCS.glob("*"))
    return sorted(path for path in files if path.is_file())


def fingerprints() -> dict[str, str]:
    return {str(path.relative_to(ROOT)).replace("\\", "/"): sha256_file(path) for path in generated_files()}


def phase2_lender_base_ebitda() -> Decimal:
    rows = read_csv(PHASE2_BRIDGES)
    matches = [row for row in rows if row["fiscal_year"] == "FY2025"
               and row["bridge_type"] == "provisional_lender_normalized_ebitda_base"]
    if not matches:
        raise Phase4Error("Missing FY2025 lender-base EBITDA bridge")
    final = max(matches, key=lambda row: int(row["sequence"]))
    return dec(final["resulting_subtotal"])


def prior_phase_changes() -> list[str]:
    paths = [
        "docs/phase-0", "docs/phase-1", "docs/phase-2", "docs/phase-3",
        "data/raw", "data/processed", "data/phase2", "data/phase3",
        "scripts/phase1.py", "scripts/phase2.py", "scripts/phase3.py",
        "scripts/validate-phase0.ps1", "tests/test_phase1.py", "tests/test_phase2.py", "tests/test_phase3.py",
    ]
    result = subprocess.run(
        ["git", "diff", "--name-only", APPROVED_PHASE3_COMMIT, "--", *paths],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def changed_paths() -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    paths: list[str] = []
    for line in result.stdout.splitlines():
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path.replace("\\", "/"))
    return paths


def validate_changed_paths() -> None:
    allowed_exact = {"README.md", "scripts/phase3.py", "scripts/phase4.py", "tests/test_phase4.py"}
    unexpected = [path for path in changed_paths()
                  if path not in allowed_exact and not path.startswith("data/phase4/")
                  and not path.startswith("docs/phase-4/")]
    if unexpected:
        raise Phase4Error(f"Unexpected changed paths: {', '.join(unexpected)}")


def validate() -> dict[str, int | str]:
    checkpoint = read_csv(RAW / "STARTING_CHECKPOINT.csv")
    inputs = read_csv(RAW / "CLOSING_CASE_INPUTS.csv")
    terms = read_csv(RAW / "PROPOSED_TERM_INPUTS.csv")
    instruments = read_csv(PROCESSED / "DEBT_INSTRUMENT_REGISTER.csv")
    legal = read_csv(PROCESSED / "LEGAL_STRUCTURE_REGISTER.csv")
    bridges = read_csv(PROCESSED / "CLOSING_BRIDGE.csv")
    sources_uses = read_csv(PROCESSED / "SOURCES_AND_USES.csv")
    schedules = read_csv(PROCESSED / "DEBT_SCHEDULE.csv")
    maturities = read_csv(PROCESSED / "MATURITY_SCHEDULE.csv")
    comparisons = read_csv(PROCESSED / "FINANCING_COMPARISON.csv")
    economics = read_csv(PROCESSED / "REFINANCING_ECONOMICS.csv")
    conditions = read_csv(PROCESSED / "CONDITIONS_PRECEDENT.csv")
    phase5 = read_csv(PROCESSED / "PHASE5_OPENING_INPUTS.csv")
    ledger = read_csv(DOCS / "SOURCE_LEDGER.csv")

    if len(checkpoint) != 1:
        raise Phase4Error("Starting checkpoint must have exactly one row")
    cp = checkpoint[0]
    if cp["repository"] != "owencchapman24/quanex-credit-underwriting" or cp["branch"] != "main":
        raise Phase4Error("Starting repository or branch mismatch")
    if any(cp[field] != APPROVED_PHASE3_COMMIT for field in ("local_head", "tracked_origin_main", "live_remote_main")):
        raise Phase4Error("Starting commit mismatch")
    if (cp["ahead"], cp["behind"], cp["working_tree_clean_before_work"]) != ("0", "0", "yes"):
        raise Phase4Error("Starting divergence or cleanliness mismatch")

    for rows, field, label in (
        (inputs, "case_id", "closing case"), (terms, "term_id", "proposed term"),
        (instruments, "instrument_id", "instrument"), (legal, "legal_item_id", "legal item"),
        (bridges, "bridge_id", "bridge row"), (sources_uses, "sources_uses_id", "sources-and-uses row"),
        (schedules, "schedule_id", "schedule row"), (maturities, "maturity_id", "maturity row"),
        (comparisons, "comparison_id", "comparison row"), (economics, "economics_id", "economics row"),
        (conditions, "condition_id", "condition"), (phase5, "input_id", "Phase 5 input"),
        (ledger, "record_id", "source ledger row"),
    ):
        ensure_unique(rows, field, label)

    if {row["case_id"] for row in inputs} != {"CC-LOW", "CC-REF", "CC-HIGH"}:
        raise Phase4Error("Required low/reference/high closing cases are missing")
    for row in inputs:
        if dec(row["opening_term_principal"]) != Decimal("468.75") or dec(row["opening_revolver_borrowings"]) != Decimal("172.5"):
            raise Phase4Error(f"{row['case_id']} does not begin with approved October balances")
        if not row["amortization_timing"] or row["owner_review_status"] != OWNER_PHASE5:
            raise Phase4Error(f"{row['case_id']} lacks timing or owner review")
        if dec(row["borrower_cash_contribution"]) > dec(row["identified_accessible_cash"]):
            raise Phase4Error(f"{row['case_id']} cash contribution exceeds identified accessible cash")
        if row["revolver_movement_role"] != "principal_balance_sensitivity_not_cash_forecast":
            raise Phase4Error(f"{row['case_id']} revolver movement could be mistaken for a cash forecast")
        if row["accrued_interest_role"] != "separate_unpaid_payoff_interest_sensitivity":
            raise Phase4Error(f"{row['case_id']} accrued-interest role is unclear")
        control_text = row["fcf_interest_double_counting_control"].lower()
        if "integrated cash and interest" not in control_text or "never added as a second" not in control_text:
            raise Phase4Error(f"{row['case_id']} lacks the FCF/accrued-interest double-counting control")

    by_inst = {row["instrument_id"]: row for row in instruments}
    if dec(by_inst["EX-TERM-A"]["principal_balance"]) + dec(by_inst["EX-REVOLVER"]["principal_balance"]) != Decimal("641.25"):
        raise Phase4Error("Existing Term A plus revolver does not equal $641.25m")
    availability = dec(by_inst["EX-REVOLVER"]["commitment"]) - dec(by_inst["EX-REVOLVER"]["drawn_amount"]) - dec(by_inst["EX-REVOLVER"]["letters_of_credit"])
    if availability != Decimal("296.3") or availability != dec(by_inst["EX-REVOLVER"]["undrawn_availability"]):
        raise Phase4Error("Existing revolver bridge does not reconcile")
    if by_inst["EX-TERM-A"]["carrying_value"] != "not_determinable_by_instrument":
        raise Phase4Error("Term principal and instrument carrying value were conflated")
    if dec(by_inst["EX-FIN-LEASE"]["principal_balance"]) + dec(by_inst["EX-OTHER-DEBT"]["principal_balance"]) != Decimal("62.619"):
        raise Phase4Error("Retained finance lease and other debt split does not reconcile")
    if dec(by_inst["EX-DEFERRED-FEES"]["carrying_value"]) != Decimal("-11.04"):
        raise Phase4Error("Deferred financing costs must remain contra-debt")

    expected_timings = {"before_closing", "at_closing_embedded_in_payoff", "after_closing_cancelled_by_payoff"}
    if {row["amortization_timing"] for row in inputs} != expected_timings:
        raise Phase4Error("January amortization alternatives are incomplete")

    su_by_case: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in sources_uses:
        su_by_case[row["case_id"]].append(row)
    result_calc = calculate_closing_cases(inputs)
    expected_cases = {
        "CC-LOW": ("462.5", "172.5", "0", "640", "0", "293.8", "6.2", "0"),
        "CC-REF": ("468.75", "197.5", "3.64771875", "650", "29.89771875", "263.90228125", "6.2", "0"),
        "CC-HIGH": ("468.75", "222.5", "7.5691875", "650", "85.0191875", "214.9808125", "0", "6.2"),
    }
    for cid, values in expected_cases.items():
        actual = result_calc[cid]
        fields = ("term_payoff", "revolver_payoff", "accrued_interest", "term_funding",
                  "new_revolver", "remaining_availability", "lc_replacement", "lc_cash_collateral")
        if tuple(dec(actual[field]) for field in fields) != tuple(dec(value) for value in values):
            raise Phase4Error(f"{cid} owner-reviewed closing sensitivity changed")
    for cid, case_rows in su_by_case.items():
        uses = sum((dec(row["amount"]) for row in case_rows if row["category"] == "use"), Decimal("0"))
        sources = sum((dec(row["amount"]) for row in case_rows if row["category"] == "source"), Decimal("0"))
        gap = next(dec(row["amount"]) for row in case_rows if row["category"] == "gap")
        control = next(dec(row["amount"]) for row in case_rows if row["category"] == "control")
        if uses != dec(result_calc[cid]["total_uses"]) or sources + gap != uses or control != 0:
            raise Phase4Error(f"{cid} sources and uses do not reconcile")
        if dec(result_calc[cid]["term_funding"]) > Decimal("650"):
            raise Phase4Error(f"{cid} exceeds term cap")
        if dec(result_calc[cid]["new_revolver"]) + dec(result_calc[cid]["lc_replacement"]) > Decimal("300"):
            raise Phase4Error(f"{cid} exceeds revolver commitment")
        if any(row["item"] in {"Retained finance leases and other debt", "Minimum operating cash"} for row in case_rows):
            raise Phase4Error(f"{cid} improperly uses retained debt or minimum cash as a source/use")
        lc_use = next(dec(row["amount"]) for row in case_rows if row["item"] == "LC cash collateral")
        if lc_use > 0 and dec(result_calc[cid]["lc_replacement"]) > 0:
            raise Phase4Error(f"{cid} double counts LCs")
        distinct = {row["item"] for row in case_rows}
        required = {"Accrued interest", "Hedge and interest-period break cost", "Financing fees", "Legal, advisory and administrative expenses"}
        if not required.issubset(distinct):
            raise Phase4Error(f"{cid} does not keep closing costs separate")
    pressure_restricted = [row for row in bridges if row["case_id"] == "CC-HIGH"
                           and row["item"] == "Restricted cash created by LC collateralization"]
    if len(pressure_restricted) != 1 or dec(pressure_restricted[0]["closing_value"]) != Decimal("6.2"):
        raise Phase4Error("Pressure-case LC collateral is not recorded once as restricted cash")
    if pressure_restricted[0]["classification"] != "restricted_asset_excluded_from_usable_liquidity":
        raise Phase4Error("Pressure-case restricted cash is not excluded from usable liquidity")

    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in schedules:
        grouped[(row["structure"], row["case_id"], row["amortization_case"])].append(row)
        if dec(row["ending_principal"]) < 0 or dec(row["scheduled_principal"]) < 0:
            raise Phase4Error("Negative schedule principal")
        if row["structure"] == "proposed" and (row["payment_date"] > "2031-01-31" or row["payment_date"] <= "2026-01-31"):
            raise Phase4Error("Invalid proposed payment date")
    proposed_groups = {key: rows for key, rows in grouped.items() if key[0] == "proposed"}
    if len(proposed_groups) != 9 or any(len(rows) != 20 for rows in proposed_groups.values()):
        raise Phase4Error("Proposed debt schedule must contain 20 quarters for each case/rate")
    for (structure, cid, amort), rows in proposed_groups.items():
        rows.sort(key=lambda row: int(row["installment_number"]))
        original = dec(rows[0]["original_principal"])
        total = sum((dec(row["total_principal_due"]) for row in rows), Decimal("0"))
        if total != original or dec(rows[-1]["ending_principal"]) != 0:
            raise Phase4Error(f"{cid}/{amort} balloon does not reconcile")
        expected_pct = {"AMORT-5": Decimal("1.25"), "AMORT-10": Decimal("2.5"), "AMORT-15": Decimal("3.75")}[amort]
        if any(dec(row["quarterly_amortization_percent"]) != expected_pct for row in rows):
            raise Phase4Error(f"{cid}/{amort} quarterly amortization is wrong")
        if any(dec(row["beginning_principal"]) - dec(row["total_principal_due"]) != dec(row["ending_principal"]) for row in rows):
            raise Phase4Error(f"{cid}/{amort} schedule roll-forward is broken")

    existing_rows = grouped.get(("existing", "", "EXISTING-EXECUTED"), [])
    if len(existing_rows) != 16 or len(existing_payment_dates()) != 15:
        raise Phase4Error("Existing Term A must show 15 remaining installments plus maturity")
    existing_rows.sort(key=lambda row: int(row["installment_number"]))
    if [row["payment_date"] for row in existing_rows[:-1]] != [value.isoformat() for value in existing_payment_dates()]:
        raise Phase4Error("Existing Term A installment dates do not follow the executed agreement")
    if (existing_rows[-2]["payment_date"], existing_rows[-1]["payment_date"]) != ("2029-07-31", "2029-08-01"):
        raise Phase4Error("Existing final installment and maturity dates are not distinguished")
    if sum((dec(row["scheduled_principal"]) for row in existing_rows), Decimal("0")) != Decimal("93.75"):
        raise Phase4Error("Existing remaining scheduled installments do not reconcile")
    if dec(existing_rows[-1]["balloon_principal"]) != Decimal("375"):
        raise Phase4Error("Existing post-installment term balloon is not $375m")
    if sum((dec(row["total_principal_due"]) for row in existing_rows), Decimal("0")) != Decimal("468.75"):
        raise Phase4Error("Existing Term A schedule does not reconcile to October principal")

    if not any(row["obligation_category"] == "retained_finance_leases_and_other_debt_maturities" for row in maturities):
        raise Phase4Error("Retained debt maturities are missing")
    if not any(row["obligation_category"] == "operating_lease_contractual_payments" for row in maturities):
        raise Phase4Error("Operating lease maturity disclosure is missing")

    term_by_name = {row["term_name"]: row for row in terms}
    if any(term_by_name[name]["owner_review_status"] != OWNER_PHASE5 for name in PHASE5_TERM_NAMES):
        raise Phase4Error("Selected provisional structure is not owner-reviewed for Phase 5 testing")
    if any(term_by_name[name]["owner_review_status"] != OWNER_THRESHOLD for name in THRESHOLD_TERM_NAMES):
        raise Phase4Error("Covenant thresholds are not limited to initial analytical tests")
    pending_term_names = {"unused_commitment_fee", "letter_of_credit_fee", "voluntary_prepayment", "mandatory_prepayment_other", "default_rate_increment", "lc_sublimit_and_transition", "additional_debt_and_acquisitions"}
    if any(term_by_name[name]["owner_review_status"] != OWNER_PENDING for name in pending_term_names):
        raise Phase4Error("Unresolved proposed terms were silently owner-approved")
    if any("hypothetical" not in row["source_or_hypothetical_status"] and row["source_or_hypothetical_status"] != "pending_information" and row["term_name"] != "borrower" for row in terms):
        raise Phase4Error("A proposed term lacks hypothetical/pending classification")
    pricing = next(row for row in terms if row["term_name"] == "term_and_drawn_revolver_margin")
    if "hypothetical" not in pricing["source_or_hypothetical_status"] or "lender quote" not in pricing["notes"]:
        raise Phase4Error("Proposed pricing is not labeled hypothetical")
    if any(row["owner_review_status"] != OWNER_METHODOLOGY or not row["consequence_if_unmet"] for row in conditions):
        raise Phase4Error("Every condition must retain its owner-reviewed methodology status and consequence")
    if len(conditions) != 24 or sum("essential" in row["public_or_hypothetical_status"] for row in conditions) != 20:
        raise Phase4Error("Condition-precedent framework must retain 20 essential and four additional conditions")
    if not any("non-guarantor" in (row["analyst_interpretation"] + row["unresolved_private_diligence"]).lower() for row in legal):
        raise Phase4Error("Non-guarantor structural subordination is missing")
    if not any("not automatically available" in row["analyst_interpretation"].lower() for row in legal):
        raise Phase4Error("Foreign/consolidated cash accessibility limitation is missing")

    required_comparisons = {
        "Opening undrawn availability", "Annual scheduled term amortization", "Final maturity",
        "Upfront and transaction costs", "Post-installment term balloon",
        "Total term principal due on maturity date", "Revolver principal due on maturity date",
        "Total funded principal due on maturity date",
        "Total funded principal payments in maturity reporting fiscal year",
        "Total funded principal payments in final 12 months to maturity",
    }
    if not required_comparisons.issubset({row["item"] for row in comparisons}):
        raise Phase4Error("Financing comparison omits fees, availability, amortization or maturity")
    if not all("No spread is a lender quote" in row["notes"] for row in economics if row["analysis_type"] == "spread_and_upfront_fee_break_even"):
        raise Phase4Error("Economics sensitivities could be mistaken for lender quotes")
    maturity_index = {(row["structure"], row["case_id"], row["amortization_case"], row["fiscal_bucket"], row["obligation_category"]): row for row in maturities}
    def maturity_value(structure: str, cid: str, amort: str, bucket: str, category: str) -> Decimal:
        return dec(maturity_index[(structure, cid, amort, bucket, category)]["amount"])
    existing_expected = {
        "term_principal_outstanding_at_beginning_of_period": Decimal("393.75"),
        "scheduled_term_principal_payments_during_period": Decimal("18.75"),
        "final_scheduled_term_installment_due_on_maturity_date": Decimal("0"),
        "post_installment_term_balloon": Decimal("375"),
        "total_term_principal_due_on_maturity_date": Decimal("375"),
        "revolver_principal_due_on_maturity_date": Decimal("172.5"),
        "total_funded_principal_due_on_maturity_date": Decimal("547.5"),
        "total_funded_principal_payments_during_period": Decimal("566.25"),
    }
    for category, expected in existing_expected.items():
        if maturity_value("existing", "", "EXISTING-EXECUTED", "FY2029_maturity_reporting_year", category) != expected:
            raise Phase4Error(f"Existing maturity definition failed: {category}")
    for cid in ("CC-LOW", "CC-REF", "CC-HIGH"):
        original = dec(result_calc[cid]["term_funding"])
        revolver = dec(result_calc[cid]["new_revolver"])
        for amort, annual_pct in (("AMORT-5", Decimal("5")), ("AMORT-10", Decimal("10")), ("AMORT-15", Decimal("15"))):
            quarterly = original * annual_pct / Decimal("400")
            balloon = original - quarterly * Decimal("20")
            bucket = "FY2031_maturity_reporting_year"
            expected = {
                "final_scheduled_term_installment_due_on_maturity_date": quarterly,
                "post_installment_term_balloon": balloon,
                "total_term_principal_due_on_maturity_date": quarterly + balloon,
                "revolver_principal_due_on_maturity_date": revolver,
                "total_funded_principal_due_on_maturity_date": quarterly + balloon + revolver,
            }
            for category, value in expected.items():
                if maturity_value("proposed", cid, amort, bucket, category) != value:
                    raise Phase4Error(f"{cid}/{amort} proposed maturity definition failed: {category}")
            final_12m = maturity_value("proposed", cid, amort, "FINAL_12M_TO_2031-01-31", "total_funded_principal_payments_during_period")
            if final_12m != quarterly * Decimal("4") + balloon + revolver:
                raise Phase4Error(f"{cid}/{amort} final-12-month maturity payments are wrong")
    if maturity_value("proposed", "CC-REF", "AMORT-10", "FY2031_maturity_reporting_year", "total_funded_principal_due_on_maturity_date") != Decimal("371.14771875"):
        raise Phase4Error("Reference maturity-date funded principal changed")
    if maturity_value("proposed", "CC-REF", "AMORT-10", "FINAL_12M_TO_2031-01-31", "total_funded_principal_payments_during_period") != Decimal("419.89771875"):
        raise Phase4Error("Reference final-12-month funded principal payments changed")
    if phase2_lender_base_ebitda() != Decimal("225.344"):
        raise Phase4Error("Phase 2 FY2025 lender-base EBITDA changed")
    prior_changes = prior_phase_changes()
    unexpected_prior = [path for path in prior_changes if path != "scripts/phase3.py"]
    if unexpected_prior:
        raise Phase4Error(f"Unexpected prior-phase artifacts changed: {', '.join(unexpected_prior)}")
    if prior_changes != ["scripts/phase3.py"]:
        raise Phase4Error("Required Phase 3 committed-lineage validator maintenance is missing or not isolated")

    catalog = source_catalog()
    used_ids = {sid for row in ledger for sid in row["source_ids"].split(";") if sid}
    unknown_ids = used_ids - set(catalog)
    if unknown_ids:
        raise Phase4Error(f"Unknown source IDs: {', '.join(sorted(unknown_ids))}")
    for sid in used_ids:
        if datetime.strptime(catalog[sid]["publication"], "%Y-%m-%d").date() > CUTOFF:
            raise Phase4Error(f"Post-cutoff evidence used: {sid}")
    if any(not row["owner_review_status"] for row in ledger):
        raise Phase4Error("Source ledger has missing owner-review status")
    if any(not row["classification"] for row in ledger):
        raise Phase4Error("Source ledger has missing classification")

    if any(row["input_status"] == "pending_information" and row["reference_case_value"] == "0" for row in phase5):
        raise Phase4Error("Pending Phase 5 information was converted to zero")
    required_phase5 = {"required_opening_cash", "accessible_cash_determination", "opening_term_principal",
                       "opening_revolver_draw", "letter_of_credit_usage", "revolver_commitment",
                       "retained_finance_leases_and_other_debt", "term_sofr_curve_or_base_rate",
                       "annual_term_amortization", "cash_sweep", "forecast_period_timing",
                       "reference_revolver_movement_calibration",
                       "pressure_case_restricted_cash_from_lc_collateral",
                       "revolver_maturity_assumption", "financing_alternative_decision"}
    if not required_phase5.issubset({row["input_name"] for row in phase5}):
        raise Phase4Error("Phase 5 handoff is incomplete")

    for path in generated_files():
        text = path.read_text(encoding="utf-8")
        if "C:\\Users\\" in text or "C:/Users/" in text:
            raise Phase4Error(f"Absolute local path in {path.relative_to(ROOT)}")
        if "2026-01-09" in text:
            raise Phase4Error(f"Post-cutoff January release referenced in Phase 4 output: {path.relative_to(ROOT)}")
    validate_changed_paths()
    return {
        "closing_cases": len(inputs), "proposed_terms": len(terms),
        "debt_instruments": len(instruments), "legal_items": len(legal),
        "schedule_rows": len(schedules), "conditions": len(conditions),
        "phase5_inputs": len(phase5), "source_ledger_rows": len(ledger),
        "post_cutoff_sources": 0, "prior_phase_changes": 1,
        "prior_phase_validation_maintenance": "scripts/phase3.py only",
        "phase2_lender_base_ebitda": fmt(phase2_lender_base_ebitda()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("seed", "build", "validate", "all"), nargs="?", default="all")
    args = parser.parse_args()
    try:
        if args.command in {"seed", "all"}:
            seed_raw()
        stats: dict[str, int | str] = {}
        if args.command in {"build", "all"}:
            stats.update(build())
        if args.command in {"validate", "all"}:
            stats.update(validate())
        if stats:
            print("Phase 4 complete: " + ", ".join(f"{key}={value}" for key, value in stats.items()))
        return 0
    except (Phase4Error, OSError, subprocess.CalledProcessError) as exc:
        print(f"Phase 4 failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
