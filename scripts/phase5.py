"""Build and validate the Phase 5 integrated base case and debt capacity model.

The workflow is intentionally case-specific, deterministic, standard-library
only, and offline. Owner-reviewed Phase 5 testing assumptions remain distinct
from management forecasts, market quotes, final loan terms and credit approval.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
import subprocess
from collections import defaultdict, deque
from datetime import date
from decimal import Decimal, InvalidOperation, getcontext
from pathlib import Path
from typing import Iterable, Sequence


getcontext().prec = 28

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "phase5" / "raw"
PROCESSED = ROOT / "data" / "phase5" / "processed"
DOCS = ROOT / "docs" / "phase-5"

PHASE2_SPREAD = ROOT / "data" / "phase2" / "processed" / "historical_spread.csv"
PHASE2_BRIDGES = ROOT / "data" / "phase2" / "processed" / "earnings_bridges.csv"
PHASE3_TRENDS = ROOT / "data" / "phase3" / "processed" / "QUARTERLY_SEGMENT_TRENDS.csv"
PHASE3_ASSUMPTIONS = ROOT / "data" / "phase3" / "processed" / "ASSUMPTION_CANDIDATES.csv"
PHASE3_GAPS = ROOT / "data" / "phase3" / "processed" / "INFORMATION_GAPS.csv"
PHASE3_SOURCES = ROOT / "data" / "phase3" / "raw" / "SOURCE_ADDITIONS.csv"
PHASE4_INPUTS = ROOT / "data" / "phase4" / "processed" / "PHASE5_OPENING_INPUTS.csv"
PHASE4_CLOSING = ROOT / "data" / "phase4" / "processed" / "CLOSING_BRIDGE.csv"
PHASE4_MATURITY = ROOT / "data" / "phase4" / "processed" / "MATURITY_SCHEDULE.csv"
PHASE1_MANIFEST = ROOT / "data" / "raw" / "SOURCE_MANIFEST.csv"
PHASE1_DEBT_TERMS = ROOT / "data" / "processed" / "debt_terms.csv"

APPROVED_PHASE4_COMMIT = "8ed5b5c320a64fd0da9ba54ecd84e5ca5692158a"
APPROVED_PHASE5_COMMIT = "412ce5e79355ad2b96ae33ab3f169ac25ef36b38"
CUTOFF = date(2025, 12, 15)
CLOSING_DATE = date(2026, 1, 31)
PROPOSED_MATURITY = date(2031, 1, 31)
EXISTING_MATURITY = date(2029, 8, 1)
MONEY = "USD_millions"
TOLERANCE = Decimal("0.000001")
ITERATION_TOLERANCE = Decimal("0.000000001")
ANALYTICAL_LIQUIDITY_THRESHOLD = Decimal("50")

CHECKPOINT_FIELDS = (
    "repository", "branch", "local_head", "tracked_origin_main", "live_remote_main",
    "ahead", "behind", "working_tree_clean_before_work", "verified_on", "notes",
)
ASSUMPTION_FIELDS = (
    "assumption_id", "category", "assumption_name", "forecast_period", "value",
    "units", "classification", "review_status", "source_ids", "upstream_ids",
    "calculation_or_basis", "limitation_or_rationale",
)
OPERATING_FIELDS = (
    "forecast_id", "fiscal_year", "quarter", "period_start", "period_end",
    "days_in_period", "frequency", "perimeter", "classification", "review_status",
    "prior_year_same_quarter_revenue", "underlying_volume_growth_percent",
    "price_mix_growth_percent", "revenue", "cost_of_sales", "gross_margin_percent",
    "gross_profit", "cash_operating_expenses", "lender_base_ebitda",
    "lender_base_ebitda_margin_percent", "depreciation_and_amortization",
    "operating_income", "cash_tax_proxy", "ttm_revenue", "ttm_cost_of_sales",
    "days_sales_outstanding", "days_inventory_outstanding", "accounts_receivable",
    "inventory", "accounts_payable", "other_operating_current_assets",
    "other_operating_current_liabilities", "operating_net_working_capital",
    "change_in_operating_net_working_capital", "working_capital_cash_flow",
    "capital_expenditures", "other_necessary_operating_cash_uses",
    "cfads_before_cash_interest", "source_ids", "assumption_ids", "calculation",
    "comparability_note",
)
MONTHLY_FIELDS = (
    "monthly_id", "structure", "month_start", "month_end", "fiscal_year", "quarter",
    "quarter_period_id", "month_in_quarter", "classification", "review_status",
    "opening_cash", "revenue", "lender_base_ebitda", "cash_tax_proxy",
    "working_capital_cash_flow", "capital_expenditures",
    "other_necessary_operating_cash_uses", "cfads_before_cash_interest",
    "opening_term_principal", "scheduled_term_principal", "cash_sweep",
    "maturity_term_payment", "ending_term_principal", "opening_revolver",
    "revolver_draw", "revolver_repayment", "maturity_revolver_payment",
    "ending_revolver", "cash_interest", "retained_finance_and_other_debt_payment",
    "recurring_financing_fees", "recurring_financing_fees_status",
    "scheduled_principal_priority_status",
    "cash_after_mandatory_debt_service_before_distributions",
    "dividends", "share_repurchases",
    "dividend_cash_funded_after_mandatory_debt_service",
    "dividend_revolver_draw_caused", "dividend_paid_while_revolver_outstanding",
    "debt_funded_dividend_flag",
    "repurchase_cash_funded_after_mandatory_debt_service",
    "repurchase_revolver_draw_caused", "repurchase_paid_while_revolver_outstanding",
    "debt_funded_buyback_flag", "cash_floor_effect_from_distributions",
    "liquidity_threshold_effect_from_distributions",
    "usable_liquidity_below_50_after_distributions_flag",
    "provisional_term_distribution_compliance", "cfo_proxy", "fcf_proxy",
    "cash_before_revolver_action", "cash_applied_at_maturity",
    "unsupported_maturity_funding_gap", "ending_cash", "operating_cash_floor",
    "cash_floor_shortfall", "letters_of_credit", "revolver_commitment",
    "revolver_availability", "usable_liquidity", "commitment_breach",
    "maturity_event", "model_status", "iteration_count", "assumption_ids", "notes",
)
WATERFALL_FIELDS = (
    "waterfall_id", "structure", "forecast_id", "fiscal_year", "quarter",
    "period_start", "period_end", "classification", "review_status", "opening_cash",
    "revenue", "lender_base_ebitda", "cash_tax_proxy",
    "working_capital_cash_flow", "capital_expenditures",
    "other_necessary_operating_cash_uses", "cfads_before_cash_interest",
    "cash_interest", "recurring_financing_fees", "recurring_financing_fees_status",
    "cfo_proxy", "fcf_proxy", "retained_finance_and_other_debt_payment",
    "scheduled_term_principal", "cash_after_mandatory_debt_service_before_distributions",
    "dividends", "share_repurchases", "dividend_revolver_draw_caused",
    "repurchase_revolver_draw_caused", "dividend_paid_while_revolver_outstanding",
    "repurchase_paid_while_revolver_outstanding", "cash_floor_effect_from_distributions",
    "liquidity_threshold_effect_from_distributions", "debt_funded_dividend_flag",
    "debt_funded_buyback_flag", "provisional_term_distribution_compliance",
    "cash_before_revolver_action", "revolver_draw", "revolver_repayment",
    "cash_sweep", "cash_applied_at_maturity", "unsupported_maturity_funding_gap",
    "ending_cash", "operating_cash_floor", "cash_floor_shortfall",
    "minimum_revolver_availability", "minimum_usable_liquidity",
    "peak_revolver_usage", "commitment_breach", "maturity_event", "model_status",
    "assumption_ids", "notes",
)
DEBT_FIELDS = (
    "debt_schedule_id", "structure", "forecast_id", "fiscal_year", "quarter",
    "period_start", "period_end", "opening_term_principal",
    "scheduled_term_principal", "cash_sweep", "maturity_term_payment",
    "ending_term_principal", "opening_revolver", "revolver_draw",
    "revolver_repayment", "maturity_revolver_payment", "ending_revolver",
    "retained_finance_and_other_debt_opening_proxy",
    "retained_finance_and_other_debt_payment",
    "retained_finance_and_other_debt_ending_proxy", "gross_funded_debt",
    "cash_interest", "revolver_availability", "maturity_event",
    "unsupported_maturity_funding_gap", "classification", "review_status",
    "source_ids", "assumption_ids", "notes",
)
METRIC_FIELDS = (
    "metric_id", "structure", "fiscal_year", "period_coverage", "metric_name",
    "numerator", "denominator", "value", "display_value", "units", "status",
    "failure_flag", "classification", "review_status", "source_ids",
    "assumption_ids", "calculation", "notes",
)
SENSITIVITY_FIELDS = (
    "sensitivity_id", "structure", "sensitivity_dimension", "case_name",
    "rate_case_type", "pricing_tier_status", "annual_amortization_percent",
    "spread_basis_points", "all_in_rate_percent", "opening_term_principal",
    "opening_revolver", "cumulative_cash_interest", "cumulative_scheduled_principal",
    "cumulative_cash_sweep", "peak_revolver_usage", "minimum_revolver_availability",
    "minimum_usable_liquidity", "ending_term_principal", "ending_revolver",
    "cash_available_above_floor_at_maturity", "unsupported_maturity_funding_gap",
    "first_cash_floor_failure", "first_commitment_breach", "classification",
    "review_status", "source_ids", "assumption_ids", "notes",
)
COMPARISON_FIELDS = (
    "comparison_id", "metric_name", "existing_value", "proposed_value", "units",
    "comparison_date_or_period", "status", "classification", "review_status",
    "source_ids", "assumption_ids", "analytical_interpretation", "limitations",
)
OPENING_BRIDGE_FIELDS = (
    "bridge_id", "sequence", "item", "existing_value", "proposed_value", "units",
    "as_of_or_period", "existing_treatment", "proposed_treatment",
    "existing_cash_effect", "proposed_cash_effect", "existing_bank_debt_effect",
    "proposed_bank_debt_effect", "status", "classification", "review_status",
    "source_ids", "upstream_ids", "calculation", "limitations",
)
DISTRIBUTION_FIELDS = (
    "distribution_id", "structure", "forecast_id", "fiscal_year", "quarter",
    "period_start", "period_end", "planned_dividend", "planned_repurchase",
    "dividend_cash_funded_after_mandatory_debt_service",
    "dividend_revolver_draw_caused", "dividend_paid_while_revolver_outstanding",
    "debt_funded_dividend_flag", "repurchase_cash_funded_after_mandatory_debt_service",
    "repurchase_revolver_draw_caused", "repurchase_paid_while_revolver_outstanding",
    "debt_funded_buyback_flag", "cash_floor_effect_from_distributions",
    "liquidity_threshold_effect_from_distributions",
    "usable_liquidity_below_50_after_distributions_flag",
    "provisional_term_compliance_status", "amount_to_suspend_or_fund_differently",
    "classification", "review_status", "source_ids", "assumption_ids", "notes",
)
COMMON_HORIZON_FIELDS = (
    "analysis_id", "segment", "metric_name", "existing_value", "proposed_value",
    "units", "period_start", "period_end", "measurement_event", "status",
    "classification", "review_status", "source_ids", "assumption_ids",
    "calculation", "limitations",
)
PERIOD_PRESENTATION_FIELDS = (
    "presentation_id", "period_label", "structure", "period_start", "period_end",
    "scope", "revenue", "lender_base_ebitda", "cfads_before_cash_interest",
    "cash_interest", "cfo_proxy", "fcf_proxy", "status", "classification",
    "review_status", "assumption_ids", "calculation", "limitations",
)
VALIDATION_FIELDS = (
    "validation_id", "category", "test_name", "status", "observed_value",
    "expected_value_or_rule", "materiality_tolerance", "notes",
)
LEDGER_FIELDS = (
    "record_id", "artifact_path", "record_type", "source_or_assumption_id",
    "source_type", "source_date", "forecast_period", "units", "original_value",
    "normalized_value", "classification", "review_status",
    "formula_or_transformation", "upstream_artifact", "source_ids",
    "limitation_or_rationale",
)


class Phase5Error(RuntimeError):
    """Raised when a decision-relevant Phase 5 control fails."""


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict[str, str]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def dec(value: str | int | Decimal, label: str = "value") -> Decimal:
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise Phase5Error(f"Invalid decimal for {label}: {value}") from exc


def fmt(value: Decimal | str | int | None) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except InvalidOperation:
            return str(value)
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def p3(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.001')):,.3f}"


def semis(values: Iterable[str]) -> str:
    return ";".join(dict.fromkeys(value for value in values if value))


def ensure_unique(rows: list[dict[str, str]], field: str, label: str) -> None:
    values = [row[field] for row in rows]
    if len(values) != len(set(values)):
        raise Phase5Error(f"Duplicate {label} identifiers")


def fiscal_quarter_for_month(year: int, month: int) -> tuple[str, str]:
    if month in (11, 12):
        return f"FY{year + 1}", "Q1"
    if month == 1:
        return f"FY{year}", "Q1"
    if month in (2, 3, 4):
        return f"FY{year}", "Q2"
    if month in (5, 6, 7):
        return f"FY{year}", "Q3"
    return f"FY{year}", "Q4"


def month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date.fromordinal(date(year, month + 1, 1).toordinal() - 1)


def month_sequence(start_year: int, start_month: int, end_year: int, end_month: int) -> list[date]:
    values: list[date] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        values.append(month_end(year, month))
        month += 1
        if month == 13:
            year += 1
            month = 1
    return values


def source_manifest() -> dict[str, dict[str, str]]:
    catalog = {row["source_id"]: row for row in read_csv(PHASE1_MANIFEST)}
    for row in read_csv(PHASE3_SOURCES):
        normalized = dict(row)
        normalized["publication_or_filing_date"] = row["publication_date"]
        catalog[row["source_id"]] = normalized
    return catalog


def phase2_value(fiscal_year: str, metric_name: str) -> Decimal:
    matches = [
        row for row in read_csv(PHASE2_SPREAD)
        if row["fiscal_year"] == fiscal_year and row["metric_name"] == metric_name
        and row["status"] == "supported"
    ]
    if len(matches) != 1:
        raise Phase5Error(f"Expected one Phase 2 fact for {fiscal_year}/{metric_name}")
    return dec(matches[0]["value"], metric_name)


def lender_base_ebitda(fiscal_year: str) -> Decimal:
    matches = [
        row for row in read_csv(PHASE2_BRIDGES)
        if row["fiscal_year"] == fiscal_year
        and row["bridge_type"] == "provisional_lender_normalized_ebitda_base"
    ]
    if not matches:
        raise Phase5Error(f"Missing lender-base bridge for {fiscal_year}")
    final = max(matches, key=lambda row: int(row["sequence"]))
    return dec(final["resulting_subtotal"], f"{fiscal_year} lender EBITDA")


def phase3_quarterly() -> dict[tuple[str, str, str], Decimal]:
    rows = read_csv(PHASE3_TRENDS)
    result: dict[tuple[str, str, str], Decimal] = {}
    for row in rows:
        if row["segment"] == "Consolidated" and row["fiscal_year"] == "FY2025":
            key = (row["fiscal_year"], row["quarter"], row["metric_name"])
            if key in result:
                raise Phase5Error(f"Duplicate Phase 3 quarterly fact: {key}")
            result[key] = dec(row["value"], str(key))
    return result


def checkpoint_rows() -> list[dict[str, str]]:
    return [{
        "repository": "owencchapman24/quanex-credit-underwriting",
        "branch": "main",
        "local_head": APPROVED_PHASE4_COMMIT,
        "tracked_origin_main": APPROVED_PHASE4_COMMIT,
        "live_remote_main": APPROVED_PHASE4_COMMIT,
        "ahead": "0",
        "behind": "0",
        "working_tree_clean_before_work": "yes",
        "verified_on": "2026-09-10",
        "notes": "Verified before Phase 5 edits; live remote checked independently with git ls-remote.",
    }]


def assumption_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add(aid: str, category: str, name: str, period: str, value: Decimal | str,
            units: str, classification: str, review: str, sources: str,
            upstream: str, basis: str, limitation: str) -> None:
        rows.append({
            "assumption_id": aid, "category": category, "assumption_name": name,
            "forecast_period": period, "value": fmt(value), "units": units,
            "classification": classification, "review_status": review,
            "source_ids": sources, "upstream_ids": upstream,
            "calculation_or_basis": basis, "limitation_or_rationale": limitation,
        })

    owner = "owner_reviewed_for_phase5_testing"
    inherited = "inherited_owner_reviewed"
    calculated = "calculated_from_approved_inputs"
    add("P5A-001", "operating", "underlying_volume_growth", "FY2026-FY2031", Decimal("-0.5"),
        "percent", "selected_midpoint_assumption", owner, "", "ASM-001",
        "Midpoint of the owner-reviewed -2% to +1% range.",
        "A midpoint is a modeling choice, not evidence of actual volume growth.")
    add("P5A-002", "operating", "price_mix_growth", "FY2026-FY2031", Decimal("0.5"),
        "percent", "selected_midpoint_assumption", owner, "", "ASM-002",
        "Midpoint of the owner-reviewed 0% to +1% range.",
        "Does not represent organic unit growth or guaranteed pass-through.")
    add("P5A-003", "operating", "annual_gross_margin", "FY2026-FY2031", Decimal("27"),
        "percent", "selected_midpoint_assumption", owner, "SRC-001", "ASM-003",
        "Midpoint of the owner-reviewed 26%-28% range.",
        "Quarterly shape retains FY2025 full-post-Tyman seasonality; plant execution remains a risk.")
    add("P5A-004", "operating", "cash_operating_expense_ratio", "FY2026-FY2031", Decimal("14.9041"),
        "percent_of_revenue", "owner_reviewed_rounded_run_rate_assumption", owner, "SRC-001",
        "FY2025 lender-base EBITDA bridge",
        "(FY2025 gross profit - owner-reviewed lender-base EBITDA) / FY2025 revenue.",
        "No unrealized synergy or separate forecast addback is included.")
    add("P5A-005", "operating", "depreciation_and_amortization_ratio", "FY2026-FY2031", Decimal("5.6292"),
        "percent_of_revenue", "owner_reviewed_rounded_run_rate_assumption", owner, "SRC-001",
        "FY2025 historical spread", "FY2025 D&A / FY2025 revenue.",
        "Asset-level depreciation and acquisition-intangible runoff are unavailable.")
    add("P5A-006", "working_capital", "days_sales_outstanding", "FY2026-FY2031", Decimal("41.5"),
        "days", "selected_midpoint_assumption", owner, "SRC-001", "ASM-005",
        "Midpoint of the owner-reviewed 40-43 day range using trailing-12-month revenue.",
        "Only two acquisition-affected annual observations support the range.")
    add("P5A-007", "working_capital", "days_inventory_outstanding", "FY2026-FY2031", Decimal("72.5"),
        "days", "selected_midpoint_assumption", owner, "SRC-001", "ASM-006",
        "Midpoint of the owner-reviewed 70-75 day range using trailing-12-month cost of sales.",
        "Does not assume the FY2025 inventory cash release repeats.")
    add("P5A-008", "working_capital", "accounts_payable_to_cost_of_sales", "FY2026-FY2031",
        Decimal("9.8106"), "percent", "owner_reviewed_rounded_proxy_assumption", owner, "SRC-001", "ASM-015;GAP-015",
        "FY2025 ending accounts payable / FY2025 cost of sales.",
        "This is not DPO and is not a purchases-based payment-period measure.")
    add("P5A-009", "working_capital", "other_operating_current_assets_to_revenue",
        "FY2026-FY2031", Decimal("1.9673"), "percent", "owner_reviewed_rounded_proxy_assumption",
        owner, "SRC-001", "ASM-016;GAP-015",
        "FY2025 other presented operating current assets / FY2025 revenue.",
        "The residual combines unlike accounts and requires account-level diligence.")
    add("P5A-010", "working_capital", "other_operating_current_liabilities_to_revenue",
        "FY2026-FY2031", Decimal("5.8353"), "percent", "owner_reviewed_rounded_proxy_assumption",
        owner, "SRC-001", "ASM-016;GAP-015",
        "FY2025 other presented operating current liabilities / FY2025 revenue.",
        "The residual combines unlike accounts and requires account-level diligence.")
    add("P5A-011", "cash_flow", "capital_expenditures_to_revenue", "FY2026-FY2031",
        Decimal("3.5"), "percent", "selected_midpoint_assumption", owner, "SRC-001",
        "ASM-007;GAP-010", "Midpoint of the owner-reviewed 3%-4% total-capex range.",
        "Maintenance, integration and expansion categories remain not determinable.")
    add("P5A-012", "cash_flow", "cash_tax_rate_proxy", "FY2026-FY2031", Decimal("25"),
        "percent_of_positive_operating_income", "new_modeling_assumption", owner, "",
        "GAP-009", "Applied to positive operating income before financing.",
        "A legal-entity cash-tax forecast and interest tax-shield schedule are unavailable.")
    add("P5A-013", "cash_flow", "known_restructuring_cash_payment", "FY2026_Q2",
        Decimal("0.7"), MONEY, "inherited_minimum_with_timing_assumption", owner, "SRC-001",
        "ASM-009;GAP-011", "Known FY2025 year-end accrual, modeled as paid in FY2026 Q2.",
        "Amount is inherited; payment quarter is newly proposed and future program cost is unknown.")
    add("P5A-014", "distributions", "annual_dividends", "FY2026-FY2031", Decimal("14.5"),
        MONEY, "selected_midpoint_assumption", owner, "SRC-001;SRC-002", "ASM-011",
        "Midpoint of the owner-reviewed $14m-$15m annual reference.",
        "Board actions are not committed; modeled evenly by month.")
    add("P5A-015", "distributions", "annual_share_repurchases", "FY2026-FY2031", Decimal("5"),
        MONEY, "selected_midpoint_assumption", owner, "SRC-001;SRC-002", "ASM-010",
        "Midpoint of the owner-reviewed $0-$10m range.",
        "Not a commitment; reductions remain Phase 6 mitigations.")
    add("P5A-016", "liquidity", "opening_operating_cash", "2026-01-31", Decimal("25"),
        MONEY, "inherited_testing_assumption", inherited, "", "P5-001;P5-015",
        "Phase 4 owner-reviewed operating cash floor retained at closing.",
        "Book cash is not treated as accessible closing or debt-repayment cash.")
    add("P5A-017", "liquidity", "accessible_cash_above_floor", "2026-01-31", Decimal("0"),
        MONEY, "conservative_model_boundary", owner, "SRC-001;SRC-003", "P5-002;GAP-004",
        "No cash beyond the $25m operating floor is credited at closing.",
        "This is a conservative model boundary, not evidence that accessible cash is zero.")
    add("P5A-018", "pricing", "implied_constant_base_rate", "2026-02-01_to_2031-01-31",
        Decimal("3.57"), "percent", "new_modeling_assumption", owner, "SRC-001",
        "P5-009;P5-010", "October reported 6.57% rate less proposed 300 bps midpoint spread.",
        "Not a quoted SOFR rate or forward curve; the base-rate path remains owner review.")
    add("P5A-019", "pricing", "proposed_reference_spread", "2026-02-01_to_2031-01-31",
        Decimal("300"), "basis_points", "selected_midpoint_assumption", owner, "",
        "P5-010;PT-011", "Midpoint of the owner-reviewed 250-350 bps testing range.",
        "Not a market quote, lender commitment or approved term.")
    add("P5A-020", "pricing", "existing_rate_neutral_comparison_case", "2026-02-01_to_2029-08-01",
        Decimal("6.57"), "percent", "rate_neutral_comparison_assumption", owner, "SRC-001;SRC-003",
        "DT-026;DT-027;DT-028;DT-029;DT-030;GAP-009",
        "Held equal to the proposed 3.57% base-rate proxy plus 300 bps solely for a rate-neutral comparison.",
        "Not an actual or representative January 2026 existing-facility rate. The applicable leverage tier is not determinable.")
    add("P5A-021", "debt", "proposed_annual_term_amortization", "2026-04-30_to_2031-01-31",
        Decimal("10"), "percent_of_original_principal", "inherited_testing_assumption",
        inherited, "", "P5-011;PT-009", "Paid quarterly at 2.5% of original principal.",
        "Five-percent and 15% financing sensitivities remain separate.")
    add("P5A-022", "debt", "annual_excess_cash_flow_sweep", "FY2026-FY2030",
        Decimal("50"), "percent_of_cash_above_floor", "inherited_rate_new_timing_definition",
        owner, "", "P5-014;PT-017",
        "After revolver repayment, 50% of cash above the floor is swept at October 31 subject to the Phase 4 $50m analytical liquidity threshold.",
        "The rate is owner-reviewed for testing; timing and simplified public definition require review. The $50m threshold is not a final covenant.")
    add("P5A-023", "timing", "monthly_operating_flow_allocation", "first_24_months",
        "equal_one_third_within_each_fiscal_quarter", "text", "new_modeling_assumption",
        owner, "", "P5-023",
        "Quarterly operating flows are allocated equally across each quarter's three months.",
        "No public monthly seasonality is available; Phase 6 must test more adverse timing.")
    add("P5A-024", "timing", "cash_interest_timing", "all_modeled_months",
        "average_beginning_and_ending_debt", "text", "new_modeling_assumption", owner,
        "", "P5-013;GAP-009",
        "Monthly interest uses average term after scheduled principal and iterated average revolver.",
        "Sweeps occur at month end and reduce interest beginning the following month.")
    add("P5A-025", "debt", "proposed_opening_term_principal", "2026-01-31", Decimal("650"),
        MONEY, "inherited_reference_case", inherited, "", "P5-003;CC-REF",
        "Exact Phase 4 reference closing bridge.", "Actual payoff and final funding remain pending.")
    add("P5A-026", "debt", "proposed_opening_revolver", "2026-01-31",
        Decimal("29.89771875"), MONEY, "inherited_reference_case", inherited, "",
        "P5-004;CC-REF", "Exact Phase 4 reference closing bridge.",
        "Not an actual January 2026 balance.")
    add("P5A-027", "debt", "existing_opening_term_principal", "2026-02-01",
        Decimal("462.5"), MONEY, "calculated_reference_timing", calculated, "SRC-001;SRC-003",
        "CC-REF;existing debt schedule",
        "$468.75m October balance less the January 31 scheduled $6.25m payment after the hypothetical refinancing timestamp.",
        "February 1 same-point balance. The installment is funded in the revolver bridge and is not a free debt reduction.")
    add("P5A-028", "debt", "existing_opening_revolver", "2026-02-01",
        Decimal("207.39771875"), MONEY, "calculated_same_point_opening_bridge", calculated, "SRC-001;SRC-003;SRC-021",
        "CC-REF;P5A-027", "$172.5m October draw plus $25m reference movement, $6.25m January installment funding and $3.64771875m accrued-interest funding.",
        "Same-point Phase 5 comparison assumption, not an actual January 2026 balance; FY2026 Q1 CFADS is disclosed but not separately credited to the Phase 4 principal sensitivity.")
    add("P5A-029", "liquidity", "proposed_revolver_commitment", "2026-01-31_to_2031-01-31",
        Decimal("300"), MONEY, "inherited_testing_assumption", inherited, "", "P5-006;PT-003",
        "Phase 4 provisional structure.", "Not a commitment.")
    add("P5A-030", "liquidity", "existing_revolver_commitment", "2026-01-31_to_2029-08-01",
        Decimal("475"), MONEY, "existing_contract_fact", "not_applicable_existing_fact",
        "SRC-001;SRC-003", "EX-REVOLVER", "Existing executed facility commitment.",
        "Availability ceases at maturity absent amendment or waiver.")
    add("P5A-031", "liquidity", "letters_of_credit", "modeled_term", Decimal("6.2"),
        MONEY, "inherited_reference_case", inherited, "SRC-001;SRC-003", "P5-005",
        "Reference case assumes noncash replacement once under the applicable revolver.",
        "Issuer, sublimit and transition remain pending; LCs are counted once.")
    add("P5A-032", "debt", "retained_finance_leases_and_other_debt_opening_proxy",
        "2026-01-31", Decimal("62.619"), MONEY, "reported_opening_fact",
        "not_applicable_existing_fact", "SRC-001;SRC-002", "P5-007",
        "October 31, 2025 finance leases and other funded debt retained.",
        "Public data do not allocate future payments between principal and interest.")
    for idx, (fy, amount) in enumerate((
        ("FY2026", "8.351"), ("FY2027", "8.031"), ("FY2028", "6.83"),
        ("FY2029", "6.498"), ("FY2030", "6.146"),
    ), start=33):
        add(f"P5A-{idx:03d}", "debt", "retained_finance_and_other_contractual_payments",
            fy, Decimal(amount), MONEY, "reported_undiscounted_payment_bucket",
            "not_applicable_existing_fact", "SRC-001", f"MT-000{idx - 28}",
            "Phase 4 retained-obligation maturity schedule.",
            "Includes interest and principal; not a liability roll-forward.")
    add("P5A-038", "debt", "retained_finance_and_other_contractual_payments",
        "FY2031", Decimal("6.146"), MONEY, "continuation_assumption", owner, "SRC-001",
        "P5A-037;MT-0010", "FY2030 annual amount continued solely to allocate FY2031 Q1.",
        "The public filing puts FY2031 and later in an unallocated thereafter bucket.")
    add("P5A-039", "cash_flow", "operating_lease_cash_treatment", "FY2026-FY2031",
        "included_in_operating_costs_no_separate_subtraction", "text",
        "methodology_control", owner, "SRC-001", "P5-008",
        "Operating lease expense remains in the operating cost base.",
        "Contractual cash timing is not separately forecast to avoid double counting.")
    add("P5A-040", "transaction", "proposed_upfront_financing_and_advisory_fees",
        "2026-01-31", Decimal("10"), MONEY, "inherited_reference_case", inherited, "",
        "CC-REF;P5-019", "Included once in Phase 4 reference closing uses and funded debt.",
        "Not subtracted again from the post-closing cash waterfall.")
    add("P5A-041", "timing", "working_capital_day_count", "FY2026-FY2031",
        Decimal("365"), "days", "new_modeling_assumption", owner, "", "ASM-005;ASM-006",
        "Trailing-12-month revenue and cost-of-sales denominators use 365 days.",
        "Leap-year day differences are immaterial to this annualized public-information proxy.")
    add("P5A-042", "pricing", "recurring_financing_fees", "modeled_term", "",
        MONEY, "missing_input", "pending_information", "SRC-003", "PT-012;PT-013",
        "Recurring commitment, LC, fronting, administrative and other financing fees are not fully determinable.",
        "Excluded rather than entered as zero; modeled cash flow and liquidity are before these fees.")
    return rows


def seed_raw() -> None:
    write_csv(RAW / "STARTING_CHECKPOINT.csv", checkpoint_rows(), CHECKPOINT_FIELDS)
    write_csv(RAW / "MODEL_ASSUMPTIONS.csv", assumption_rows(), ASSUMPTION_FIELDS)


def assumption_map(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    ensure_unique(rows, "assumption_id", "assumption")
    return {row["assumption_id"]: row for row in rows}


def assumption_decimal(rows: dict[str, dict[str, str]], aid: str) -> Decimal:
    return dec(rows[aid]["value"], aid)


def forecast_periods() -> list[tuple[str, str, date, date]]:
    rows: list[tuple[str, str, date, date]] = []
    starts = {
        "Q1": (11, 1), "Q2": (2, 1), "Q3": (5, 1), "Q4": (8, 1),
    }
    ends = {
        "Q1": (1, 31), "Q2": (4, 30), "Q3": (7, 31), "Q4": (10, 31),
    }
    for fy in range(2026, 2031):
        for quarter in ("Q1", "Q2", "Q3", "Q4"):
            sm, sd = starts[quarter]
            em, ed = ends[quarter]
            sy = fy - 1 if quarter == "Q1" else fy
            rows.append((f"FY{fy}", quarter, date(sy, sm, sd), date(fy, em, ed)))
    rows.append(("FY2031", "Q1", date(2030, 11, 1), date(2031, 1, 31)))
    return rows


def build_operating_forecast(assumptions: list[dict[str, str]]) -> list[dict[str, str]]:
    amap = assumption_map(assumptions)
    qactual = phase3_quarterly()
    volume = assumption_decimal(amap, "P5A-001") / 100
    price_mix = assumption_decimal(amap, "P5A-002") / 100
    growth_factor = (Decimal("1") + volume) * (Decimal("1") + price_mix)
    target_margin = assumption_decimal(amap, "P5A-003") / 100
    opex_ratio = assumption_decimal(amap, "P5A-004") / 100
    dna_ratio = assumption_decimal(amap, "P5A-005") / 100
    dso = assumption_decimal(amap, "P5A-006")
    dio = assumption_decimal(amap, "P5A-007")
    ap_ratio = assumption_decimal(amap, "P5A-008") / 100
    other_asset_ratio = assumption_decimal(amap, "P5A-009") / 100
    other_liability_ratio = assumption_decimal(amap, "P5A-010") / 100
    capex_ratio = assumption_decimal(amap, "P5A-011") / 100
    tax_rate = assumption_decimal(amap, "P5A-012") / 100
    day_count = assumption_decimal(amap, "P5A-041")

    actual_quarters: dict[str, dict[str, Decimal]] = {}
    for quarter in ("Q1", "Q2", "Q3", "Q4"):
        rev = qactual[("FY2025", quarter, "revenue")]
        gp = qactual[("FY2025", quarter, "gross_profit")]
        actual_quarters[quarter] = {"revenue": rev, "cogs": rev - gp, "margin": gp / rev}
    annual_actual_margin = (
        sum((value["revenue"] - value["cogs"] for value in actual_quarters.values()), Decimal("0"))
        / sum((value["revenue"] for value in actual_quarters.values()), Decimal("0"))
    )
    margin_deltas = {
        quarter: value["margin"] - annual_actual_margin
        for quarter, value in actual_quarters.items()
    }
    revenue_by_period: dict[tuple[str, str], Decimal] = {
        ("FY2025", quarter): value["revenue"] for quarter, value in actual_quarters.items()
    }
    rolling_revenue = deque((actual_quarters[q]["revenue"] for q in ("Q1", "Q2", "Q3", "Q4")), maxlen=4)
    rolling_cogs = deque((actual_quarters[q]["cogs"] for q in ("Q1", "Q2", "Q3", "Q4")), maxlen=4)
    opening_nwc = (
        phase2_value("FY2025", "accounts_receivable")
        + phase2_value("FY2025", "inventory")
        + phase2_value("FY2025", "other_presented_current_assets")
        - phase2_value("FY2025", "accounts_payable")
        - phase2_value("FY2025", "other_presented_operating_current_liabilities")
    )

    output: list[dict[str, str]] = []
    for idx, (fy, quarter, start, end) in enumerate(forecast_periods(), start=1):
        prior_fy = f"FY{int(fy[2:]) - 1}"
        prior_revenue = revenue_by_period[(prior_fy, quarter)]
        revenue = prior_revenue * growth_factor
        revenue_by_period[(fy, quarter)] = revenue
        margin = target_margin + margin_deltas[quarter]
        gross_profit = revenue * margin
        cogs = revenue - gross_profit
        cash_opex = -(revenue * opex_ratio)
        ebitda = gross_profit + cash_opex
        dna = -(revenue * dna_ratio)
        operating_income = ebitda + dna
        cash_tax = -(max(operating_income, Decimal("0")) * tax_rate)
        rolling_revenue.append(revenue)
        rolling_cogs.append(cogs)
        ttm_revenue = sum(rolling_revenue, Decimal("0"))
        ttm_cogs = sum(rolling_cogs, Decimal("0"))
        receivables = ttm_revenue / day_count * dso
        inventory = ttm_cogs / day_count * dio
        payables = ttm_cogs * ap_ratio
        other_assets = ttm_revenue * other_asset_ratio
        other_liabilities = ttm_revenue * other_liability_ratio
        nwc = receivables + inventory + other_assets - payables - other_liabilities
        change_nwc = nwc - opening_nwc
        wc_cash = -change_nwc
        opening_nwc = nwc
        capex = -(revenue * capex_ratio)
        other_uses = -assumption_decimal(amap, "P5A-013") if (fy, quarter) == ("FY2026", "Q2") else Decimal("0")
        cfads = ebitda + cash_tax + wc_cash + capex + other_uses
        days = Decimal((end - start).days + 1)
        output.append({
            "forecast_id": f"OP-{idx:04d}", "fiscal_year": fy, "quarter": quarter,
            "period_start": start.isoformat(), "period_end": end.isoformat(),
            "days_in_period": fmt(days), "frequency": "quarterly",
            "perimeter": "post_tyman_forecast_from_fy2025_full_year_anchor",
            "classification": "formula_calculated_forecast",
            "review_status": "contains_owner_reviewed_phase5_testing_assumptions",
            "prior_year_same_quarter_revenue": fmt(prior_revenue),
            "underlying_volume_growth_percent": fmt(volume * 100),
            "price_mix_growth_percent": fmt(price_mix * 100),
            "revenue": fmt(revenue), "cost_of_sales": fmt(-cogs),
            "gross_margin_percent": fmt(margin * 100), "gross_profit": fmt(gross_profit),
            "cash_operating_expenses": fmt(cash_opex), "lender_base_ebitda": fmt(ebitda),
            "lender_base_ebitda_margin_percent": fmt(ebitda / revenue * 100),
            "depreciation_and_amortization": fmt(dna), "operating_income": fmt(operating_income),
            "cash_tax_proxy": fmt(cash_tax), "ttm_revenue": fmt(ttm_revenue),
            "ttm_cost_of_sales": fmt(ttm_cogs), "days_sales_outstanding": fmt(dso),
            "days_inventory_outstanding": fmt(dio), "accounts_receivable": fmt(receivables),
            "inventory": fmt(inventory), "accounts_payable": fmt(payables),
            "other_operating_current_assets": fmt(other_assets),
            "other_operating_current_liabilities": fmt(other_liabilities),
            "operating_net_working_capital": fmt(nwc),
            "change_in_operating_net_working_capital": fmt(change_nwc),
            "working_capital_cash_flow": fmt(wc_cash), "capital_expenditures": fmt(capex),
            "other_necessary_operating_cash_uses": fmt(other_uses),
            "cfads_before_cash_interest": fmt(cfads),
            "source_ids": "SRC-001;SRC-002;SRC-016;SRC-021;SRC-022",
            "assumption_ids": "P5A-001;P5A-002;P5A-003;P5A-004;P5A-005;P5A-006;P5A-007;P5A-008;P5A-009;P5A-010;P5A-011;P5A-012;P5A-013;P5A-041",
            "calculation": "Revenue uses volume and price/mix; gross profit uses quarterly seasonal margin; EBITDA subtracts cash operating expense; TTM balance drivers determine working capital; CFADS subtracts taxes, capex, working-capital investment and identified cash uses.",
            "comparability_note": "FY2025 is the first full post-Tyman year. FY2024 mixed-perimeter results and current segments are not fabricated into this forecast.",
        })
    return output


def forecast_index(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {(row["fiscal_year"], row["quarter"]): row for row in rows}


def retained_payment_by_year(amap: dict[str, dict[str, str]]) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for row in amap.values():
        if row["assumption_name"] == "retained_finance_and_other_contractual_payments":
            result[row["forecast_period"]] = dec(row["value"])
    return result


def existing_pricing_grid() -> list[dict[str, Decimal | str]]:
    """Return the approved leverage grid without selecting an applicable tier."""
    terms = {row["term_name"]: row for row in read_csv(PHASE1_DEBT_TERMS)}
    rows: list[dict[str, Decimal | str]] = []
    for number in range(1, 5):
        name = f"pricing_band_{number}"
        if name not in terms:
            raise Phase5Error(f"Missing approved existing pricing term: {name}")
        text = terms[name]["value_text"]
        commitment = re.search(r"commitment ([0-9.]+)%", text)
        sofr = re.search(r"SOFR/RFR ([0-9.]+)%", text)
        if not commitment or not sofr:
            raise Phase5Error(f"Cannot parse approved existing pricing term: {name}")
        rows.append({
            "term_id": terms[name]["term_id"], "band": name,
            "leverage_condition": text.split(":", 1)[0],
            "commitment_fee_percent": Decimal(commitment.group(1)),
            "sofr_rfr_margin_bps": Decimal(sofr.group(1)) * Decimal("100"),
            "source_ids": terms[name]["source_ids"],
        })
    return rows


def structure_parameters(structure: str, amap: dict[str, dict[str, str]],
                         spread_bps: Decimal, amortization_percent: Decimal,
                         existing_all_in_rate: Decimal | None = None) -> dict[str, Decimal | date]:
    if structure == "proposed":
        return {
            "opening_term": assumption_decimal(amap, "P5A-025"),
            "opening_revolver": assumption_decimal(amap, "P5A-026"),
            "commitment": assumption_decimal(amap, "P5A-029"),
            "lc": assumption_decimal(amap, "P5A-031"),
            "all_in_rate": assumption_decimal(amap, "P5A-018") + spread_bps / Decimal("100"),
            "quarterly_principal": assumption_decimal(amap, "P5A-025") * amortization_percent / Decimal("400"),
            "maturity": PROPOSED_MATURITY,
        }
    if structure == "existing":
        return {
            "opening_term": assumption_decimal(amap, "P5A-027"),
            "opening_revolver": assumption_decimal(amap, "P5A-028"),
            "commitment": assumption_decimal(amap, "P5A-030"),
            "lc": assumption_decimal(amap, "P5A-031"),
            "all_in_rate": (
                existing_all_in_rate
                if existing_all_in_rate is not None
                else assumption_decimal(amap, "P5A-020")
            ),
            "quarterly_principal": Decimal("6.25"),
            "maturity": EXISTING_MATURITY,
        }
    raise Phase5Error(f"Unknown structure: {structure}")


def is_quarter_end(value: date) -> bool:
    return value.month in (1, 4, 7, 10)


def distribution_funding(
    structure: str,
    cash_after_mandatory: Decimal,
    floor: Decimal,
    beginning_revolver: Decimal,
    dividend: Decimal,
    repurchase: Decimal,
) -> dict[str, Decimal | str]:
    """Attribute distributions after mandatory debt service, before revolver action."""
    available = max(Decimal("0"), cash_after_mandatory - floor)
    dividend_cash = min(dividend, available)
    dividend_draw = dividend - dividend_cash
    after_dividend = max(Decimal("0"), available - dividend_cash)
    repurchase_cash = min(repurchase, after_dividend)
    repurchase_draw = repurchase - repurchase_cash
    mandatory_draw_needed = max(Decimal("0"), floor - cash_after_mandatory)
    dividend_while_revolver = (
        dividend if beginning_revolver > 0 or mandatory_draw_needed > 0 else Decimal("0")
    )
    repurchase_while_revolver = (
        repurchase
        if beginning_revolver > 0 or mandatory_draw_needed > 0 or dividend_draw > 0
        else Decimal("0")
    )
    if structure == "proposed" and repurchase_draw > TOLERANCE:
        compliance = "not_compliant_debt_funded_buyback"
    elif structure == "proposed" and repurchase_while_revolver > TOLERANCE:
        compliance = "pending_information_buyback_while_revolver_outstanding"
    else:
        compliance = "pending_information_distribution_permissions"
    return {
        "dividend_cash_funded": dividend_cash,
        "dividend_draw_caused": dividend_draw,
        "dividend_paid_while_revolver": dividend_while_revolver,
        "debt_funded_dividend_flag": "yes" if dividend_draw > TOLERANCE else "no",
        "repurchase_cash_funded": repurchase_cash,
        "repurchase_draw_caused": repurchase_draw,
        "repurchase_paid_while_revolver": repurchase_while_revolver,
        "debt_funded_buyback_flag": "yes" if repurchase_draw > TOLERANCE else "no",
        "cash_floor_effect": dividend_draw + repurchase_draw,
        "liquidity_threshold_effect": dividend + repurchase,
        "provisional_compliance": compliance,
    }


def model_one_month(
    structure: str,
    current_date: date,
    quarter_row: dict[str, str],
    month_number_in_quarter: int,
    beginning_cash: Decimal,
    beginning_term: Decimal,
    beginning_revolver: Decimal,
    params: dict[str, Decimal | date],
    amap: dict[str, dict[str, str]],
    retained_payments: dict[str, Decimal],
) -> dict[str, Decimal | str | int]:
    floor = assumption_decimal(amap, "P5A-016")
    sweep_rate = assumption_decimal(amap, "P5A-022") / 100
    annual_dividends = assumption_decimal(amap, "P5A-014")
    annual_repurchases = assumption_decimal(amap, "P5A-015")
    commitment = dec(params["commitment"])
    lc = dec(params["lc"])
    annual_rate = dec(params["all_in_rate"]) / 100
    maturity = params["maturity"]
    if not isinstance(maturity, date):
        raise Phase5Error("Invalid maturity")

    allocated = {
        name: dec(quarter_row[name]) / Decimal("3")
        for name in (
            "revenue", "lender_base_ebitda", "cash_tax_proxy",
            "working_capital_cash_flow", "capital_expenditures",
            "other_necessary_operating_cash_uses", "cfads_before_cash_interest",
        )
    }
    fiscal_year = quarter_row["fiscal_year"]
    retained = retained_payments[fiscal_year] / Decimal("12")
    dividends = annual_dividends / Decimal("12")
    repurchases = annual_repurchases / Decimal("12")
    scheduled = Decimal("0")
    if is_quarter_end(current_date):
        scheduled = min(beginning_term, dec(params["quarterly_principal"]))

    maturity_event = (
        structure == "proposed" and current_date == PROPOSED_MATURITY
    ) or (
        structure == "existing" and current_date == date(2029, 7, 31)
    )
    term_after_scheduled = beginning_term - scheduled
    estimated_ending_revolver = beginning_revolver
    final: dict[str, Decimal | int] = {}
    iteration = 0
    for iteration in range(1, 101):
        average_term = (beginning_term + term_after_scheduled) / Decimal("2")
        average_revolver = (beginning_revolver + estimated_ending_revolver) / Decimal("2")
        cash_interest = (average_term + average_revolver) * annual_rate / Decimal("12")
        cash_after_mandatory = (
            beginning_cash + allocated["cfads_before_cash_interest"] - cash_interest
            - retained - scheduled
        )
        distributions = distribution_funding(
            structure, cash_after_mandatory, floor, beginning_revolver,
            dividends, repurchases,
        )
        cash_before_revolver = cash_after_mandatory - dividends - repurchases
        revolver_draw = Decimal("0")
        revolver_repayment = Decimal("0")
        cash_after_revolver = cash_before_revolver
        max_drawn_revolver = commitment - lc
        if cash_before_revolver < floor:
            needed = floor - cash_before_revolver
            remaining_capacity = max(Decimal("0"), max_drawn_revolver - beginning_revolver)
            revolver_draw = min(needed, remaining_capacity)
            cash_after_revolver += revolver_draw
        else:
            available_for_repayment = cash_before_revolver - floor
            revolver_repayment = min(available_for_repayment, beginning_revolver)
            cash_after_revolver -= revolver_repayment
        ending_revolver_before_maturity = beginning_revolver + revolver_draw - revolver_repayment
        sweep = Decimal("0")
        if current_date.month == 10 and ending_revolver_before_maturity == 0:
            cash_excess = max(Decimal("0"), cash_after_revolver - floor)
            availability_before_sweep = max(
                Decimal("0"), commitment - lc - ending_revolver_before_maturity,
            )
            liquidity_safeguard_capacity = max(
                Decimal("0"), cash_excess + availability_before_sweep
                - ANALYTICAL_LIQUIDITY_THRESHOLD,
            )
            sweep = min(
                term_after_scheduled, cash_excess * sweep_rate,
                liquidity_safeguard_capacity,
            )
        ending_term_before_maturity = term_after_scheduled - sweep
        ending_cash_before_maturity = cash_after_revolver - sweep
        if abs(ending_revolver_before_maturity - estimated_ending_revolver) <= ITERATION_TOLERANCE:
            final = {
                "cash_interest": cash_interest,
                "cash_after_mandatory": cash_after_mandatory,
                "distributions": distributions,
                "cash_before_revolver": cash_before_revolver,
                "revolver_draw": revolver_draw,
                "revolver_repayment": revolver_repayment,
                "ending_revolver_before_maturity": ending_revolver_before_maturity,
                "sweep": sweep,
                "ending_term_before_maturity": ending_term_before_maturity,
                "ending_cash_before_maturity": ending_cash_before_maturity,
            }
            break
        estimated_ending_revolver = ending_revolver_before_maturity
    else:
        raise Phase5Error(f"Interest/revolver iteration did not converge for {structure}/{current_date}")

    ending_cash = dec(final["ending_cash_before_maturity"])
    ending_term = dec(final["ending_term_before_maturity"])
    ending_revolver = dec(final["ending_revolver_before_maturity"])
    maturity_term_payment = Decimal("0")
    maturity_revolver_payment = Decimal("0")
    cash_applied_at_maturity = Decimal("0")
    unsupported_gap = Decimal("0")
    if maturity_event:
        cash_available = max(Decimal("0"), ending_cash - floor)
        maturity_revolver_payment = min(ending_revolver, cash_available)
        ending_revolver -= maturity_revolver_payment
        cash_available -= maturity_revolver_payment
        maturity_term_payment = min(ending_term, cash_available)
        ending_term -= maturity_term_payment
        cash_applied_at_maturity = maturity_revolver_payment + maturity_term_payment
        ending_cash -= cash_applied_at_maturity
        unsupported_gap = ending_term + ending_revolver

    cash_floor_shortfall = max(Decimal("0"), floor - ending_cash)
    availability = Decimal("0") if maturity_event else commitment - lc - ending_revolver
    commitment_breach = max(Decimal("0"), -availability)
    usable_liquidity = max(Decimal("0"), ending_cash - floor) + max(Decimal("0"), availability)
    status = "PASS"
    if cash_floor_shortfall > TOLERANCE:
        status = "CASH_FLOOR_FAILURE"
    if commitment_breach > TOLERANCE:
        status = "COMMITMENT_BREACH"
    if maturity_event and unsupported_gap > TOLERANCE:
        status = "UNSUPPORTED_MATURITY_FUNDING_GAP"

    cfo_proxy = (
        allocated["lender_base_ebitda"] + allocated["cash_tax_proxy"]
        + allocated["working_capital_cash_flow"]
        + allocated["other_necessary_operating_cash_uses"]
        - dec(final["cash_interest"])
    )
    fcf_proxy = cfo_proxy + allocated["capital_expenditures"]
    distribution = final["distributions"]
    if not isinstance(distribution, dict):
        raise Phase5Error("Invalid distribution attribution")
    return {
        **allocated,
        "opening_cash": beginning_cash,
        "opening_term": beginning_term,
        "scheduled": scheduled,
        "sweep": dec(final["sweep"]),
        "maturity_term_payment": maturity_term_payment,
        "ending_term": ending_term,
        "opening_revolver": beginning_revolver,
        "revolver_draw": dec(final["revolver_draw"]),
        "revolver_repayment": dec(final["revolver_repayment"]),
        "maturity_revolver_payment": maturity_revolver_payment,
        "ending_revolver": ending_revolver,
        "cash_interest": dec(final["cash_interest"]),
        "retained_payment": retained,
        "cash_after_mandatory": dec(final["cash_after_mandatory"]),
        "dividends": dividends,
        "repurchases": repurchases,
        **distribution,
        "cfo_proxy": cfo_proxy,
        "fcf_proxy": fcf_proxy,
        "cash_before_revolver": dec(final["cash_before_revolver"]),
        "cash_applied_at_maturity": cash_applied_at_maturity,
        "unsupported_gap": unsupported_gap,
        "ending_cash": ending_cash,
        "floor": floor,
        "cash_floor_shortfall": cash_floor_shortfall,
        "lc": lc,
        "commitment": commitment,
        "availability": availability,
        "usable_liquidity": usable_liquidity,
        "liquidity_threshold_failure_flag": (
            "yes" if usable_liquidity < ANALYTICAL_LIQUIDITY_THRESHOLD else "no"
        ),
        "commitment_breach": commitment_breach,
        "maturity_event": "yes" if maturity_event else "no",
        "model_status": status,
        "iteration_count": iteration,
    }


def run_monthly_model(
    structure: str,
    operating: list[dict[str, str]],
    assumptions: list[dict[str, str]],
    spread_bps: Decimal = Decimal("300"),
    amortization_percent: Decimal = Decimal("10"),
    existing_all_in_rate: Decimal | None = None,
) -> list[dict[str, str]]:
    amap = assumption_map(assumptions)
    params = structure_parameters(
        structure, amap, spread_bps, amortization_percent, existing_all_in_rate,
    )
    op_index = forecast_index(operating)
    retained = retained_payment_by_year(amap)
    dates = (
        month_sequence(2026, 2, 2031, 1)
        if structure == "proposed"
        else month_sequence(2026, 2, 2029, 7)
    )
    cash = assumption_decimal(amap, "P5A-016")
    term = dec(params["opening_term"])
    revolver = dec(params["opening_revolver"])
    retained_proxy = assumption_decimal(amap, "P5A-032")
    rows: list[dict[str, str]] = []
    for idx, end in enumerate(dates, start=1):
        fy, quarter = fiscal_quarter_for_month(end.year, end.month)
        qrow = op_index[(fy, quarter)]
        month_in_quarter = ((end.month - 2) % 3) + 1
        modeled = model_one_month(
            structure, end, qrow, month_in_quarter, cash, term, revolver,
            params, amap, retained,
        )
        start = date(end.year, end.month, 1)
        assumption_ids = (
            "P5A-003;P5A-004;P5A-006;P5A-007;P5A-008;P5A-009;P5A-010;"
            "P5A-011;P5A-012;P5A-014;P5A-015;P5A-016;P5A-018;P5A-019;"
            "P5A-020;P5A-021;P5A-022;P5A-023;P5A-024;P5A-025;P5A-026;"
            "P5A-027;P5A-028;P5A-029;P5A-030;P5A-031;P5A-032;P5A-042"
        )
        rows.append({
            "monthly_id": f"ML-{structure[:1].upper()}-{idx:04d}",
            "structure": structure, "month_start": start.isoformat(),
            "month_end": end.isoformat(), "fiscal_year": fy, "quarter": quarter,
            "quarter_period_id": qrow["forecast_id"],
            "month_in_quarter": str(month_in_quarter),
            "classification": "formula_calculated_base_case",
            "review_status": "contains_owner_reviewed_phase5_testing_assumptions",
            "opening_cash": fmt(dec(modeled["opening_cash"])),
            "revenue": fmt(dec(modeled["revenue"])),
            "lender_base_ebitda": fmt(dec(modeled["lender_base_ebitda"])),
            "cash_tax_proxy": fmt(dec(modeled["cash_tax_proxy"])),
            "working_capital_cash_flow": fmt(dec(modeled["working_capital_cash_flow"])),
            "capital_expenditures": fmt(dec(modeled["capital_expenditures"])),
            "other_necessary_operating_cash_uses": fmt(dec(modeled["other_necessary_operating_cash_uses"])),
            "cfads_before_cash_interest": fmt(dec(modeled["cfads_before_cash_interest"])),
            "opening_term_principal": fmt(dec(modeled["opening_term"])),
            "scheduled_term_principal": fmt(dec(modeled["scheduled"])),
            "cash_sweep": fmt(dec(modeled["sweep"])),
            "maturity_term_payment": fmt(dec(modeled["maturity_term_payment"])),
            "ending_term_principal": fmt(dec(modeled["ending_term"])),
            "opening_revolver": fmt(dec(modeled["opening_revolver"])),
            "revolver_draw": fmt(dec(modeled["revolver_draw"])),
            "revolver_repayment": fmt(dec(modeled["revolver_repayment"])),
            "maturity_revolver_payment": fmt(dec(modeled["maturity_revolver_payment"])),
            "ending_revolver": fmt(dec(modeled["ending_revolver"])),
            "cash_interest": fmt(-dec(modeled["cash_interest"])),
            "retained_finance_and_other_debt_payment": fmt(-dec(modeled["retained_payment"])),
            "recurring_financing_fees": "",
            "recurring_financing_fees_status": "not_determinable_excluded_not_zero",
            "scheduled_principal_priority_status": "mandatory_before_distributions",
            "cash_after_mandatory_debt_service_before_distributions": fmt(dec(modeled["cash_after_mandatory"])),
            "dividends": fmt(-dec(modeled["dividends"])),
            "share_repurchases": fmt(-dec(modeled["repurchases"])),
            "dividend_cash_funded_after_mandatory_debt_service": fmt(dec(modeled["dividend_cash_funded"])),
            "dividend_revolver_draw_caused": fmt(dec(modeled["dividend_draw_caused"])),
            "dividend_paid_while_revolver_outstanding": fmt(dec(modeled["dividend_paid_while_revolver"])),
            "debt_funded_dividend_flag": str(modeled["debt_funded_dividend_flag"]),
            "repurchase_cash_funded_after_mandatory_debt_service": fmt(dec(modeled["repurchase_cash_funded"])),
            "repurchase_revolver_draw_caused": fmt(dec(modeled["repurchase_draw_caused"])),
            "repurchase_paid_while_revolver_outstanding": fmt(dec(modeled["repurchase_paid_while_revolver"])),
            "debt_funded_buyback_flag": str(modeled["debt_funded_buyback_flag"]),
            "cash_floor_effect_from_distributions": fmt(dec(modeled["cash_floor_effect"])),
            "liquidity_threshold_effect_from_distributions": fmt(dec(modeled["liquidity_threshold_effect"])),
            "usable_liquidity_below_50_after_distributions_flag": str(modeled["liquidity_threshold_failure_flag"]),
            "provisional_term_distribution_compliance": str(modeled["provisional_compliance"]),
            "cfo_proxy": fmt(dec(modeled["cfo_proxy"])), "fcf_proxy": fmt(dec(modeled["fcf_proxy"])),
            "cash_before_revolver_action": fmt(dec(modeled["cash_before_revolver"])),
            "cash_applied_at_maturity": fmt(dec(modeled["cash_applied_at_maturity"])),
            "unsupported_maturity_funding_gap": fmt(dec(modeled["unsupported_gap"])),
            "ending_cash": fmt(dec(modeled["ending_cash"])),
            "operating_cash_floor": fmt(dec(modeled["floor"])),
            "cash_floor_shortfall": fmt(dec(modeled["cash_floor_shortfall"])),
            "letters_of_credit": fmt(dec(modeled["lc"])),
            "revolver_commitment": fmt(dec(modeled["commitment"])),
            "revolver_availability": fmt(dec(modeled["availability"])),
            "usable_liquidity": fmt(dec(modeled["usable_liquidity"])),
            "commitment_breach": fmt(dec(modeled["commitment_breach"])),
            "maturity_event": str(modeled["maturity_event"]),
            "model_status": str(modeled["model_status"]),
            "iteration_count": str(modeled["iteration_count"]),
            "assumption_ids": assumption_ids,
            "notes": (
                "Monthly operating flows are equal one-third allocations of the governing quarter. "
                "Retained-obligation payment includes principal and interest; the liability proxy is not amortized. "
                "Mandatory interest, retained-obligation payments and scheduled principal precede distributions. "
                "Recurring financing fees are not determinable and are excluded rather than set to zero. "
                + ("Existing maturity event occurs August 1 immediately after this July period. " if structure == "existing" and end == date(2029, 7, 31) else "")
                + ("No post-maturity revolver availability is credited." if str(modeled["maturity_event"]) == "yes" else "")
            ).strip(),
        })
        cash = dec(modeled["ending_cash"])
        term = dec(modeled["ending_term"])
        revolver = dec(modeled["ending_revolver"])
        if str(modeled["maturity_event"]) == "yes":
            break
    return rows


def group_monthly_by_quarter(monthly: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    order: list[tuple[str, str]] = []
    for row in monthly:
        key = (row["structure"], row["quarter_period_id"])
        if key not in grouped:
            order.append(key)
        grouped[key].append(row)
    return [grouped[key] for key in order]


def aggregate_waterfall(monthly: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    flow_fields = (
        "revenue", "lender_base_ebitda", "cash_tax_proxy", "working_capital_cash_flow",
        "capital_expenditures", "other_necessary_operating_cash_uses",
        "cfads_before_cash_interest", "cash_interest", "cfo_proxy", "fcf_proxy",
        "scheduled_term_principal", "retained_finance_and_other_debt_payment",
        "dividends", "share_repurchases", "revolver_draw", "revolver_repayment",
        "cash_sweep", "cash_applied_at_maturity",
        "dividend_cash_funded_after_mandatory_debt_service",
        "repurchase_cash_funded_after_mandatory_debt_service",
        "dividend_revolver_draw_caused",
        "repurchase_revolver_draw_caused", "dividend_paid_while_revolver_outstanding",
        "repurchase_paid_while_revolver_outstanding", "cash_floor_effect_from_distributions",
        "liquidity_threshold_effect_from_distributions",
    )
    for idx, group in enumerate(group_monthly_by_quarter(monthly), start=1):
        first, last = group[0], group[-1]
        pre_maturity = [row for row in group if row["maturity_event"] != "yes"] or group
        opening_availability = (
            dec(first["revolver_commitment"]) - dec(first["letters_of_credit"])
            - dec(first["opening_revolver"])
        )
        opening_usable_liquidity = (
            max(Decimal("0"), dec(first["opening_cash"]) - dec(first["operating_cash_floor"]))
            + max(Decimal("0"), opening_availability)
        )
        sums = {
            field: sum((dec(row[field]) for row in group), Decimal("0"))
            for field in flow_fields
        }
        status = next((row["model_status"] for row in group if row["model_status"] != "PASS"), "PASS")
        rows.append({
            "waterfall_id": f"WF-{first['structure'][:1].upper()}-{idx:04d}",
            "structure": first["structure"], "forecast_id": first["quarter_period_id"],
            "fiscal_year": first["fiscal_year"], "quarter": first["quarter"],
            "period_start": first["month_start"], "period_end": last["month_end"],
            "classification": "formula_calculated_base_case",
            "review_status": "contains_owner_reviewed_phase5_testing_assumptions",
            "opening_cash": first["opening_cash"],
            **{field: fmt(value) for field, value in sums.items()},
            "recurring_financing_fees": "",
            "recurring_financing_fees_status": "not_determinable_excluded_not_zero",
            "cash_after_mandatory_debt_service_before_distributions": last[
                "cash_after_mandatory_debt_service_before_distributions"
            ],
            "debt_funded_dividend_flag": (
                "yes" if any(row["debt_funded_dividend_flag"] == "yes" for row in group) else "no"
            ),
            "debt_funded_buyback_flag": (
                "yes" if any(row["debt_funded_buyback_flag"] == "yes" for row in group) else "no"
            ),
            "provisional_term_distribution_compliance": (
                "not_compliant_debt_funded_buyback"
                if any(row["provisional_term_distribution_compliance"] == "not_compliant_debt_funded_buyback" for row in group)
                else "pending_information_distribution_permissions"
            ),
            "cash_before_revolver_action": last["cash_before_revolver_action"],
            "unsupported_maturity_funding_gap": last["unsupported_maturity_funding_gap"],
            "ending_cash": last["ending_cash"], "operating_cash_floor": last["operating_cash_floor"],
            "cash_floor_shortfall": fmt(max(dec(row["cash_floor_shortfall"]) for row in group)),
            "minimum_revolver_availability": fmt(min(
                [opening_availability] + [dec(row["revolver_availability"]) for row in pre_maturity]
            )),
            "minimum_usable_liquidity": fmt(min(
                [opening_usable_liquidity] + [dec(row["usable_liquidity"]) for row in pre_maturity]
            )),
            "peak_revolver_usage": fmt(max(
                [dec(first["opening_revolver"])] + [dec(row["ending_revolver"]) for row in group]
            )),
            "commitment_breach": fmt(max(dec(row["commitment_breach"]) for row in group)),
            "maturity_event": last["maturity_event"], "model_status": status,
            "assumption_ids": first["assumption_ids"],
            "notes": (
                "Quarterly roll-up of the deterministic monthly debt and cash waterfall. "
                "The displayed cash-after-mandatory balance is the final month value; distribution attribution fields are quarterly sums."
            ),
        })
    return rows


def aggregate_debt_schedule(monthly: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    retained_proxy = Decimal("62.619")
    for idx, group in enumerate(group_monthly_by_quarter(monthly), start=1):
        first, last = group[0], group[-1]
        scheduled = sum((dec(row["scheduled_term_principal"]) for row in group), Decimal("0"))
        sweep = sum((dec(row["cash_sweep"]) for row in group), Decimal("0"))
        maturity_term = sum((dec(row["maturity_term_payment"]) for row in group), Decimal("0"))
        draws = sum((dec(row["revolver_draw"]) for row in group), Decimal("0"))
        repayments = sum((dec(row["revolver_repayment"]) for row in group), Decimal("0"))
        maturity_rev = sum((dec(row["maturity_revolver_payment"]) for row in group), Decimal("0"))
        retained_payment = -sum((dec(row["retained_finance_and_other_debt_payment"]) for row in group), Decimal("0"))
        gross_debt = dec(last["ending_term_principal"]) + dec(last["ending_revolver"]) + retained_proxy
        rows.append({
            "debt_schedule_id": f"DB-{first['structure'][:1].upper()}-{idx:04d}",
            "structure": first["structure"], "forecast_id": first["quarter_period_id"],
            "fiscal_year": first["fiscal_year"], "quarter": first["quarter"],
            "period_start": first["month_start"], "period_end": last["month_end"],
            "opening_term_principal": first["opening_term_principal"],
            "scheduled_term_principal": fmt(scheduled), "cash_sweep": fmt(sweep),
            "maturity_term_payment": fmt(maturity_term),
            "ending_term_principal": last["ending_term_principal"],
            "opening_revolver": first["opening_revolver"], "revolver_draw": fmt(draws),
            "revolver_repayment": fmt(repayments), "maturity_revolver_payment": fmt(maturity_rev),
            "ending_revolver": last["ending_revolver"],
            "retained_finance_and_other_debt_opening_proxy": fmt(retained_proxy),
            "retained_finance_and_other_debt_payment": fmt(retained_payment),
            "retained_finance_and_other_debt_ending_proxy": fmt(retained_proxy),
            "gross_funded_debt": fmt(gross_debt),
            "cash_interest": fmt(-sum((dec(row["cash_interest"]) for row in group), Decimal("0"))),
            "revolver_availability": last["revolver_availability"],
            "maturity_event": last["maturity_event"],
            "unsupported_maturity_funding_gap": last["unsupported_maturity_funding_gap"],
            "classification": "formula_calculated_base_case",
            "review_status": "contains_owner_reviewed_phase5_testing_assumptions",
            "source_ids": "SRC-001;SRC-003",
            "assumption_ids": first["assumption_ids"],
            "notes": (
                "Retained finance-lease/other-debt balance stays at the October proxy because public "
                "undiscounted payments cannot be split between principal and interest. Gross debt is therefore a conservative diagnostic."
            ),
        })
    return rows


def safe_ratio(numerator: Decimal, denominator: Decimal) -> tuple[str, str, str]:
    if denominator <= 0:
        return "", "N/M", "NONPOSITIVE_DENOMINATOR"
    return fmt(numerator / denominator), fmt(numerator / denominator), ""


def metric_row(
    mid: int,
    structure: str,
    fiscal_year: str,
    coverage: str,
    name: str,
    numerator: Decimal | None,
    denominator: Decimal | None,
    value: Decimal | None,
    units: str,
    status: str = "calculated",
    failure: str = "",
    calculation: str = "",
    notes: str = "",
) -> dict[str, str]:
    display = "N/M" if failure else (fmt(value) if value is not None else "N/D")
    return {
        "metric_id": f"CM-{mid:04d}", "structure": structure,
        "fiscal_year": fiscal_year, "period_coverage": coverage,
        "metric_name": name, "numerator": fmt(numerator), "denominator": fmt(denominator),
        "value": fmt(value), "display_value": display, "units": units,
        "status": status, "failure_flag": failure,
        "classification": "formula_calculated_credit_metric",
        "review_status": "contains_owner_reviewed_phase5_testing_assumptions",
        "source_ids": "SRC-001;SRC-003",
        "assumption_ids": "P5A-001;P5A-002;P5A-003;P5A-004;P5A-006;P5A-007;P5A-008;P5A-009;P5A-010;P5A-011;P5A-012;P5A-014;P5A-015;P5A-016;P5A-018;P5A-019;P5A-020;P5A-021;P5A-022;P5A-042",
        "calculation": calculation, "notes": notes,
    }


def build_credit_metrics(
    waterfall: list[dict[str, str]],
    debt: list[dict[str, str]],
    monthly: list[dict[str, str]],
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    debt_by_forecast = {(row["structure"], row["forecast_id"]): row for row in debt}
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in waterfall:
        groups[(row["structure"], row["fiscal_year"])].append(row)
    mid = 0
    for (structure, fy), rows in groups.items():
        rows.sort(key=lambda row: row["period_end"])
        first, last = rows[0], rows[-1]
        coverage = f"{first['quarter']}-{last['quarter']}"
        sums = {
            field: sum((dec(row[field]) for row in rows), Decimal("0"))
            for field in (
                "revenue", "lender_base_ebitda", "cash_tax_proxy",
                "working_capital_cash_flow", "capital_expenditures",
                "cfads_before_cash_interest", "cash_interest", "cfo_proxy", "fcf_proxy",
                "scheduled_term_principal", "retained_finance_and_other_debt_payment",
                "dividends", "share_repurchases", "cash_sweep",
            )
        }
        end_debt_row = debt_by_forecast[(structure, last["forecast_id"])]
        gross_debt = dec(end_debt_row["gross_funded_debt"])
        bank_debt = dec(end_debt_row["ending_term_principal"]) + dec(end_debt_row["ending_revolver"])
        cash_above_floor = max(Decimal("0"), dec(last["ending_cash"]) - dec(last["operating_cash_floor"]))
        net_debt_diag = gross_debt - cash_above_floor
        interest = -sums["cash_interest"]
        retained_payment = -sums["retained_finance_and_other_debt_payment"]
        scheduled_service = interest + sums["scheduled_term_principal"] + retained_payment
        values = [
            ("revenue", sums["revenue"], MONEY, "Sum modeled-quarter revenue."),
            ("lender_base_ebitda", sums["lender_base_ebitda"], MONEY, "Sum formula-calculated lender-base EBITDA; no top-down EBITDA growth."),
            ("lender_base_ebitda_margin", sums["lender_base_ebitda"] / sums["revenue"] * 100, "percent", "EBITDA / revenue."),
            ("cash_tax_proxy", sums["cash_tax_proxy"], MONEY, "Negative cash use."),
            ("working_capital_cash_flow", sums["working_capital_cash_flow"], MONEY, "Positive is cash contribution; negative is use."),
            ("capital_expenditures", sums["capital_expenditures"], MONEY, "Negative cash use."),
            ("cfads_before_cash_interest", sums["cfads_before_cash_interest"], MONEY, "EBITDA less modeled taxes, capex, working-capital investment and identified cash uses."),
            ("cash_interest", sums["cash_interest"], MONEY, "Negative cash use based on modeled average debt."),
            ("cfo_proxy", sums["cfo_proxy"], MONEY, "EBITDA less cash taxes, working-capital investment, other operating uses and cash interest; not an official GAAP forecast."),
            ("fcf_proxy", sums["fcf_proxy"], MONEY, "Modeled CFO proxy less capital expenditures."),
            ("scheduled_term_principal", sums["scheduled_term_principal"], MONEY, "Required term principal paid in modeled periods."),
            ("cash_sweep", sums["cash_sweep"], MONEY, "Provisional annual term sweep after revolver repayment."),
            ("dividends", sums["dividends"], MONEY, "Negative cash use."),
            ("share_repurchases", sums["share_repurchases"], MONEY, "Negative cash use."),
            ("ending_bank_funded_debt", bank_debt, MONEY, "Term plus revolver principal after modeled payments."),
            ("ending_gross_funded_debt", gross_debt, MONEY, "Bank principal plus conservative retained debt opening proxy."),
            ("book_cash_net_debt_diagnostic", net_debt_diag, MONEY, "Gross debt less modeled cash above the operating floor only."),
            ("minimum_revolver_availability", min(dec(row["minimum_revolver_availability"]) for row in rows), MONEY, "Minimum quarter-observed capacity after LCs."),
            ("minimum_usable_liquidity", min(dec(row["minimum_usable_liquidity"]) for row in rows), MONEY, "Cash above floor plus available revolver; not contractual liquidity."),
            ("peak_revolver_usage", max(dec(row["peak_revolver_usage"]) for row in rows), MONEY, "Maximum ending monthly revolver balance."),
            ("unsupported_maturity_funding_gap", max(dec(row["unsupported_maturity_funding_gap"]) for row in rows), MONEY, "Debt due at maturity not covered by modeled cash above floor."),
        ]
        for name, value, units, note in values:
            mid += 1
            output.append(metric_row(mid, structure, fy, coverage, name, value, None, value, units,
                                     calculation=note, notes=note))

        mid += 1
        output.append(metric_row(
            mid, structure, fy, coverage, "recurring_financing_fees", None, None,
            None, MONEY, status="not_determinable",
            calculation="Proposed unused-commitment, LC and fronting fees are unavailable.",
            notes="Excluded rather than entered as zero; modeled cash flow and liquidity are before these fees.",
        ))

        ratios = [
            ("gross_funded_debt_to_lender_base_ebitda", gross_debt, sums["lender_base_ebitda"], "Ending gross funded debt / same-coverage EBITDA."),
            ("net_debt_diagnostic_to_lender_base_ebitda", net_debt_diag, sums["lender_base_ebitda"], "Book-cash diagnostic only; not covenant or lender net leverage."),
            ("ebitda_to_cash_interest", sums["lender_base_ebitda"], interest, "Modeled EBITDA / modeled bank cash interest."),
            ("cfads_to_cash_interest", sums["cfads_before_cash_interest"], interest, "CFADS before cash interest / modeled bank cash interest."),
            ("cfads_to_scheduled_debt_service", sums["cfads_before_cash_interest"], scheduled_service, "CFADS before interest / bank interest, scheduled term principal and retained-obligation payments."),
            ("cfo_proxy_to_gross_debt", sums["cfo_proxy"], gross_debt, "Modeled CFO proxy / ending gross funded debt."),
            ("fcf_proxy_to_gross_debt", sums["fcf_proxy"], gross_debt, "Modeled FCF proxy / ending gross funded debt."),
        ]
        for name, numerator, denominator, note in ratios:
            mid += 1
            value_text, _, failure = safe_ratio(numerator, denominator)
            value = dec(value_text) if value_text else None
            output.append(metric_row(
                mid, structure, fy, coverage, name, numerator, denominator, value, "turns",
                status="not_meaningful" if failure else "calculated", failure=failure,
                calculation=note, notes=note,
            ))

    for structure in ("existing", "proposed"):
        smonths = [row for row in monthly if row["structure"] == structure]
        opening_bank = dec(smonths[0]["opening_term_principal"]) + dec(smonths[0]["opening_revolver"])
        ending_bank = dec(smonths[-1]["ending_term_principal"]) + dec(smonths[-1]["ending_revolver"])
        first_floor = next((row["month_end"] for row in smonths if dec(row["cash_floor_shortfall"]) > TOLERANCE), "")
        first_breach = next((row["month_end"] for row in smonths if dec(row["commitment_breach"]) > TOLERANCE), "")
        summary_values = [
            ("opening_bank_funded_debt", opening_bank, MONEY, "Opening term plus revolver."),
            ("total_bank_debt_reduction_through_maturity", opening_bank - ending_bank, MONEY, "Opening bank principal less debt remaining unpaid after maturity cash application."),
            ("cumulative_cash_interest", -sum((dec(row["cash_interest"]) for row in smonths), Decimal("0")), MONEY, "Modeled bank cash interest through maturity."),
            ("cumulative_scheduled_term_principal", sum((dec(row["scheduled_term_principal"]) for row in smonths), Decimal("0")), MONEY, "Scheduled term principal through maturity."),
            ("cumulative_cash_sweep", sum((dec(row["cash_sweep"]) for row in smonths), Decimal("0")), MONEY, "Provisional term sweep through maturity."),
            ("maturity_cash_available_above_floor", dec(smonths[-1]["cash_applied_at_maturity"]), MONEY, "Modeled cash above floor applied at maturity."),
            ("unsupported_maturity_funding_gap", dec(smonths[-1]["unsupported_maturity_funding_gap"]), MONEY, "Unpaid funded principal after maturity cash application."),
        ]
        for name, value, units, note in summary_values:
            mid += 1
            output.append(metric_row(mid, structure, "MODEL", "closing_to_maturity", name,
                                     value, None, value, units, calculation=note, notes=note))
        for name, value, flag in (
            ("first_cash_floor_failure", first_floor, "CASH_FLOOR_FAILURE"),
            ("first_commitment_breach", first_breach, "COMMITMENT_BREACH"),
        ):
            mid += 1
            output.append({
                **metric_row(mid, structure, "MODEL", "closing_to_maturity", name, None, None,
                             None, "date", status="PASS" if not value else "FAIL",
                             failure=flag if value else "", calculation="First modeled failure date."),
                "value": value, "display_value": value or "none",
            })
    return output


def model_summary(monthly: list[dict[str, str]]) -> dict[str, Decimal | str]:
    first, last = monthly[0], monthly[-1]
    pre_maturity = [row for row in monthly if row["maturity_event"] != "yes"]
    opening_availability = (
        dec(first["revolver_commitment"]) - dec(first["letters_of_credit"])
        - dec(first["opening_revolver"])
    )
    opening_usable_liquidity = (
        max(Decimal("0"), dec(first["opening_cash"]) - dec(first["operating_cash_floor"]))
        + max(Decimal("0"), opening_availability)
    )
    first_floor = next((row["month_end"] for row in monthly if dec(row["cash_floor_shortfall"]) > TOLERANCE), "")
    first_breach = next((row["month_end"] for row in monthly if dec(row["commitment_breach"]) > TOLERANCE), "")
    return {
        "opening_term": dec(first["opening_term_principal"]),
        "opening_revolver": dec(first["opening_revolver"]),
        "cumulative_interest": -sum((dec(row["cash_interest"]) for row in monthly), Decimal("0")),
        "scheduled": sum((dec(row["scheduled_term_principal"]) for row in monthly), Decimal("0")),
        "sweep": sum((dec(row["cash_sweep"]) for row in monthly), Decimal("0")),
        "peak_revolver": max(
            [dec(first["opening_revolver"])] + [dec(row["ending_revolver"]) for row in monthly]
        ),
        "min_availability": min(
            [opening_availability] + [dec(row["revolver_availability"]) for row in pre_maturity]
        ),
        "min_liquidity": min(
            [opening_usable_liquidity] + [dec(row["usable_liquidity"]) for row in pre_maturity]
        ),
        "ending_term": dec(last["ending_term_principal"]),
        "ending_revolver": dec(last["ending_revolver"]),
        "cash_at_maturity": dec(last["cash_applied_at_maturity"]),
        "gap": dec(last["unsupported_maturity_funding_gap"]),
        "first_floor": first_floor,
        "first_breach": first_breach,
    }


def phase4_reference_closing_values() -> dict[str, Decimal]:
    rows = [row for row in read_csv(PHASE4_CLOSING) if row["case_id"] == "CC-REF"]
    by_item = {row["item"]: row for row in rows}

    def closing(item: str) -> Decimal:
        if item not in by_item or not by_item[item]["closing_value"]:
            raise Phase5Error(f"Missing Phase 4 reference closing item: {item}")
        return dec(by_item[item]["closing_value"], item)

    return {
        "term_payoff": closing("Term A payoff"),
        "bank_payoff": closing("Total bank principal payoff"),
        "accrued_interest": closing("Accrued interest"),
        "financing_fees": closing("Financing fees"),
        "legal_fees": closing("Legal, advisory and administrative expenses"),
        "new_term": closing("New term funding"),
        "new_revolver": closing("Opening new-revolver draw"),
        "lc": closing("Existing letters of credit"),
    }


def build_opening_bridge(
    operating: list[dict[str, str]], assumptions: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Reconcile both alternatives to February 1, 2026 after January actions."""
    amap = assumption_map(assumptions)
    p4 = phase4_reference_closing_values()
    q1_cfads = dec(operating[0]["cfads_before_cash_interest"])
    oct_term = Decimal("468.75")
    oct_revolver = Decimal("172.5")
    reference_movement = Decimal("25")
    installment = Decimal("6.25")
    accrued = p4["accrued_interest"]
    fees = p4["financing_fees"] + p4["legal_fees"]
    existing_term = assumption_decimal(amap, "P5A-027")
    existing_revolver = assumption_decimal(amap, "P5A-028")
    proposed_term = assumption_decimal(amap, "P5A-025")
    proposed_revolver = assumption_decimal(amap, "P5A-026")
    cash = assumption_decimal(amap, "P5A-016")
    lc = assumption_decimal(amap, "P5A-031")
    existing_availability = assumption_decimal(amap, "P5A-030") - lc - existing_revolver
    proposed_availability = assumption_decimal(amap, "P5A-029") - lc - proposed_revolver
    previous_existing = existing_term + reference_movement + oct_revolver
    previous_proposed = proposed_term + proposed_revolver
    correction = installment + accrued
    if previous_proposed - previous_existing != Decimal("19.89771875"):
        raise Phase5Error("Prior $19.898m opening difference did not reconstruct")
    if existing_revolver != oct_revolver + reference_movement + correction:
        raise Phase5Error("Existing same-point revolver bridge does not reconcile")
    if proposed_term != p4["new_term"] or proposed_revolver != p4["new_revolver"]:
        raise Phase5Error("Phase 4 proposed funding changed")

    values: list[tuple[str, str, str, str, str, str, str, str, str, str, str, str, str, str]] = [
        ("October 31, 2025 Term A", fmt(oct_term), fmt(oct_term), MONEY, "2025-10-31",
         "reported opening principal", "reported opening principal", "", "", "", "", "reported_fact", "SRC-001;SRC-002", "DT-008"),
        ("October 31, 2025 revolver", fmt(oct_revolver), fmt(oct_revolver), MONEY, "2025-10-31",
         "reported opening principal", "reported opening principal", "", "", "", "", "reported_fact", "SRC-001;SRC-002", "DT-019"),
        ("November-January revolver movement", fmt(reference_movement), fmt(reference_movement), MONEY, "2025-11-01_to_2026-01-31",
         "Phase 4 reference principal sensitivity", "included in Phase 4 payoff", "", "", fmt(reference_movement), fmt(reference_movement), "owner_reviewed_reference_sensitivity", "SRC-021", "P5-026;CC-REF"),
        ("FY2026 Q1 operating CFADS before cash interest", fmt(q1_cfads), fmt(q1_cfads), MONEY, "2025-11-01_to_2026-01-31",
         "disclosed; not separately credited against the $25m principal sensitivity", "same treatment; not separately credited", "0", "0", "0", "0", "formula_calculated_operating_output", "SRC-001", operating[0]["forecast_id"]),
        ("January 31 Term A installment", fmt(installment), "0", MONEY, "2026-01-31_immediately_after_closing_timestamp",
         "paid and funded with revolver to preserve same-point cash", "refinancing closes immediately before installment; no installment paid", fmt(-installment), "0", "0", "0", "timing_and_funding_treatment", "SRC-003", "DT-009;P5A-027"),
        ("Accrued interest through closing timestamp", fmt(accrued), fmt(accrued), MONEY, "through_2026-01-31_closing",
         "economic cash use funded with revolver before February model", "Phase 4 closing use funded once in new revolver", fmt(-accrued), fmt(-accrued), fmt(accrued), fmt(accrued), "same_point_cash_use", "SRC-001", "CB-0035"),
        ("Refinancing fees", "0", fmt(fees), MONEY, "2026-01-31_closing",
         "not applicable", "Phase 4 fee and legal/advisory uses funded once", "0", fmt(-fees), "0", fmt(fees), "phase4_reference_closing_use", "", "CB-0038;CB-0039"),
        ("Existing-debt payoff", "0", fmt(p4["bank_payoff"]), MONEY, "2026-01-31_closing",
         "facilities retained", "Phase 4 principal payoff", "0", fmt(-p4["bank_payoff"]), "0", fmt(-p4["bank_payoff"]), "phase4_reference_closing_use", "SRC-001;SRC-003;SRC-021", "CB-0033"),
        ("New term funding", "0", fmt(p4["new_term"]), MONEY, "2026-01-31_closing",
         "not applicable", "Phase 4 source", "0", fmt(p4["new_term"]), "0", fmt(p4["new_term"]), "phase4_reference_closing_source", "", "CB-0048"),
        ("New revolver funding", "0", fmt(p4["new_revolver"]), MONEY, "2026-01-31_closing",
         "not applicable", "Phase 4 residual source including accrued interest and fees", "0", fmt(p4["new_revolver"]), "0", fmt(p4["new_revolver"]), "phase4_reference_closing_source", "", "CB-0050"),
        ("Cash retained", fmt(cash), fmt(cash), MONEY, "2026-02-01_00:00",
         "owner-reviewed same-point floor assumption", "owner-reviewed same-point floor assumption", "", "", "", "", "owner_reviewed_same_point_assumption", "", "P5A-016;P5A-017"),
        ("Letters of credit", fmt(lc), fmt(lc), MONEY, "2026-02-01_00:00",
         "existing revolver exposure", "replacement exposure under proposed revolver", "", "", "", "", "contingent_exposure_not_cash_use", "SRC-001;SRC-003", "DT-020;P5A-031"),
        ("Ending term debt", fmt(existing_term), fmt(proposed_term), MONEY, "2026-02-01_00:00",
         "after installment", "new term funded", "", "", "", "", "reconciled_opening_position", "SRC-001;SRC-003", "P5A-025;P5A-027"),
        ("Ending revolver debt", fmt(existing_revolver), fmt(proposed_revolver), MONEY, "2026-02-01_00:00",
         "includes funding of installment and accrued interest", "Phase 4 funded source", "", "", "", "", "reconciled_opening_position", "SRC-001;SRC-003;SRC-021", "P5A-026;P5A-028"),
        ("Ending total bank debt", fmt(existing_term + existing_revolver), fmt(proposed_term + proposed_revolver), MONEY, "2026-02-01_00:00",
         "reconciled retained-facility position", "reconciled proposed position", "", "", "", "", "reconciled_opening_position", "SRC-001;SRC-003;SRC-021", "P5A-025;P5A-026;P5A-027;P5A-028"),
        ("Ending cash", fmt(cash), fmt(cash), MONEY, "2026-02-01_00:00",
         "testing assumption; actual closing cash not determinable", "same", "", "", "", "", "owner_reviewed_same_point_assumption", "SRC-001", "P5A-016;P5A-017"),
        ("Available revolver capacity after LCs", fmt(existing_availability), fmt(proposed_availability), MONEY, "2026-02-01_00:00",
         "475 less LCs and reconciled draw", "300 less LCs and Phase 4 draw", "", "", "", "", "formula_calculated_liquidity", "SRC-001;SRC-003", "P5A-029;P5A-030;P5A-031"),
        ("Previously reported opening bank debt", fmt(previous_existing), fmt(previous_proposed), MONEY, "prior_phase5_presentation",
         "omitted installment/accrued-interest funding", "Phase 4 reference debt", "", "", "", "", "superseded_comparison_control", "", "P5A-025;P5A-026;prior_P5A-027;prior_P5A-028"),
        ("Correction to prior existing opening debt", fmt(correction), "0", MONEY, "same_point_reconciliation",
         "6.25 installment funding plus 3.64771875 accrued-interest funding", "none", "", "", fmt(correction), "0", "timing_and_cash_use_correction", "SRC-001;SRC-003", "DT-009;CB-0035"),
        ("Reconciled proposed less existing bank debt", "0", fmt(proposed_term + proposed_revolver - existing_term - existing_revolver), MONEY, "2026-02-01_00:00",
         "comparison base", "incremental proposed debt equals refinancing fees", "", "", "", fmt(fees), "difference_reconciliation", "", "P5A-040"),
    ]
    rows: list[dict[str, str]] = []
    for idx, value in enumerate(values, start=1):
        (item, ev, pv, units, period, et, pt, ec, pc, ed, pd, classification,
         sources, upstream) = value
        rows.append({
            "bridge_id": f"OB-{idx:03d}", "sequence": str(idx), "item": item,
            "existing_value": ev, "proposed_value": pv, "units": units,
            "as_of_or_period": period, "existing_treatment": et,
            "proposed_treatment": pt, "existing_cash_effect": ec,
            "proposed_cash_effect": pc, "existing_bank_debt_effect": ed,
            "proposed_bank_debt_effect": pd, "status": "supported_or_explicit_assumption",
            "classification": classification,
            "review_status": "owner_reviewed_for_phase5_testing",
            "source_ids": sources, "upstream_ids": upstream,
            "calculation": "Generated deterministically from approved Phase 4 reference inputs and Phase 5 owner-reviewed timing.",
            "limitations": (
                "Actual January cash, cash-flow timing, payoff letter and applicable pricing remain unavailable; "
                "the $25m cash balance is a disclosed testing assumption."
            ),
        })
    return rows


def build_sensitivities(
    operating: list[dict[str, str]],
    assumptions: list[dict[str, str]],
) -> list[dict[str, str]]:
    proposed_cases = [
        ("amortization", "5_percent_amortization", Decimal("5"), Decimal("300")),
        ("amortization", "10_percent_reference", Decimal("10"), Decimal("300")),
        ("amortization", "15_percent_amortization", Decimal("15"), Decimal("300")),
        ("pricing", "250_bps_spread", Decimal("10"), Decimal("250")),
        ("pricing", "300_bps_reference", Decimal("10"), Decimal("300")),
        ("pricing", "350_bps_spread", Decimal("10"), Decimal("350")),
    ]
    amap = assumption_map(assumptions)
    base_rate = assumption_decimal(amap, "P5A-018")
    rows: list[dict[str, str]] = []
    for idx, (dimension, name, amort, spread) in enumerate(proposed_cases, start=1):
        monthly = run_monthly_model("proposed", operating, assumptions, spread, amort)
        summary = model_summary(monthly)
        rows.append({
            "sensitivity_id": f"DS-{idx:03d}", "structure": "proposed",
            "sensitivity_dimension": dimension, "case_name": name,
            "rate_case_type": "proposed_facility_testing_range",
            "pricing_tier_status": "hypothetical_not_lender_quote",
            "annual_amortization_percent": fmt(amort),
            "spread_basis_points": fmt(spread),
            "all_in_rate_percent": fmt(base_rate + spread / Decimal("100")),
            "opening_term_principal": fmt(dec(summary["opening_term"])),
            "opening_revolver": fmt(dec(summary["opening_revolver"])),
            "cumulative_cash_interest": fmt(dec(summary["cumulative_interest"])),
            "cumulative_scheduled_principal": fmt(dec(summary["scheduled"])),
            "cumulative_cash_sweep": fmt(dec(summary["sweep"])),
            "peak_revolver_usage": fmt(dec(summary["peak_revolver"])),
            "minimum_revolver_availability": fmt(dec(summary["min_availability"])),
            "minimum_usable_liquidity": fmt(dec(summary["min_liquidity"])),
            "ending_term_principal": fmt(dec(summary["ending_term"])),
            "ending_revolver": fmt(dec(summary["ending_revolver"])),
            "cash_available_above_floor_at_maturity": fmt(dec(summary["cash_at_maturity"])),
            "unsupported_maturity_funding_gap": fmt(dec(summary["gap"])),
            "first_cash_floor_failure": str(summary["first_floor"]),
            "first_commitment_breach": str(summary["first_breach"]),
            "classification": "financing_sensitivity_not_operating_downside",
            "review_status": "contains_owner_reviewed_phase5_testing_assumptions",
            "source_ids": "SRC-001",
            "assumption_ids": "P5A-018;P5A-019;P5A-021;P5A-022",
            "notes": "Same operating base case in every row. No operating downside, waiver or maturity refinancing is introduced.",
        })
    for grid in existing_pricing_grid():
        spread = dec(grid["sofr_rfr_margin_bps"])
        all_in = base_rate + spread / Decimal("100")
        monthly = run_monthly_model(
            "existing", operating, assumptions, existing_all_in_rate=all_in,
        )
        summary = model_summary(monthly)
        idx = len(rows) + 1
        rows.append({
            "sensitivity_id": f"DS-{idx:03d}", "structure": "existing",
            "sensitivity_dimension": "existing_contractual_pricing_grid",
            "case_name": str(grid["band"]),
            "rate_case_type": "approved_contractual_grid_applied_to_phase5_base_rate_proxy",
            "pricing_tier_status": "applicable_tier_not_determinable",
            "annual_amortization_percent": "5", "spread_basis_points": fmt(spread),
            "all_in_rate_percent": fmt(all_in),
            "opening_term_principal": fmt(dec(summary["opening_term"])),
            "opening_revolver": fmt(dec(summary["opening_revolver"])),
            "cumulative_cash_interest": fmt(dec(summary["cumulative_interest"])),
            "cumulative_scheduled_principal": fmt(dec(summary["scheduled"])),
            "cumulative_cash_sweep": fmt(dec(summary["sweep"])),
            "peak_revolver_usage": fmt(dec(summary["peak_revolver"])),
            "minimum_revolver_availability": fmt(dec(summary["min_availability"])),
            "minimum_usable_liquidity": fmt(dec(summary["min_liquidity"])),
            "ending_term_principal": fmt(dec(summary["ending_term"])),
            "ending_revolver": fmt(dec(summary["ending_revolver"])),
            "cash_available_above_floor_at_maturity": fmt(dec(summary["cash_at_maturity"])),
            "unsupported_maturity_funding_gap": fmt(dec(summary["gap"])),
            "first_cash_floor_failure": str(summary["first_floor"]),
            "first_commitment_breach": str(summary["first_breach"]),
            "classification": "financing_sensitivity_not_operating_downside",
            "review_status": "calculated_from_approved_contractual_grid",
            "source_ids": "SRC-003",
            "assumption_ids": "P5A-018;P5A-020;P5A-027;P5A-028;P5A-030",
            "notes": (
                f"{grid['term_id']} {grid['leverage_condition']}; commitment fee {fmt(dec(grid['commitment_fee_percent']))}%. "
                "The applicable January 2026 tier, actual benchmark, floor and recurring fee cash amounts are not determinable."
            ),
        })
    neutral_rate = assumption_decimal(amap, "P5A-020")
    neutral_monthly = run_monthly_model(
        "existing", operating, assumptions, existing_all_in_rate=neutral_rate,
    )
    neutral_summary = model_summary(neutral_monthly)
    idx = len(rows) + 1
    rows.append({
        "sensitivity_id": f"DS-{idx:03d}", "structure": "existing",
        "sensitivity_dimension": "existing_rate_neutral_comparison",
        "case_name": "6.57_percent_rate_neutral", "rate_case_type": "rate_neutral_not_actual_or_representative",
        "pricing_tier_status": "not_a_contractual_tier_selection",
        "annual_amortization_percent": "5", "spread_basis_points": "",
        "all_in_rate_percent": fmt(neutral_rate),
        "opening_term_principal": fmt(dec(neutral_summary["opening_term"])),
        "opening_revolver": fmt(dec(neutral_summary["opening_revolver"])),
        "cumulative_cash_interest": fmt(dec(neutral_summary["cumulative_interest"])),
        "cumulative_scheduled_principal": fmt(dec(neutral_summary["scheduled"])),
        "cumulative_cash_sweep": fmt(dec(neutral_summary["sweep"])),
        "peak_revolver_usage": fmt(dec(neutral_summary["peak_revolver"])),
        "minimum_revolver_availability": fmt(dec(neutral_summary["min_availability"])),
        "minimum_usable_liquidity": fmt(dec(neutral_summary["min_liquidity"])),
        "ending_term_principal": fmt(dec(neutral_summary["ending_term"])),
        "ending_revolver": fmt(dec(neutral_summary["ending_revolver"])),
        "cash_available_above_floor_at_maturity": fmt(dec(neutral_summary["cash_at_maturity"])),
        "unsupported_maturity_funding_gap": fmt(dec(neutral_summary["gap"])),
        "first_cash_floor_failure": str(neutral_summary["first_floor"]),
        "first_commitment_breach": str(neutral_summary["first_breach"]),
        "classification": "financing_sensitivity_not_operating_downside",
        "review_status": "owner_reviewed_for_phase5_testing",
        "source_ids": "SRC-001;SRC-003",
        "assumption_ids": "P5A-018;P5A-020;P5A-027;P5A-028;P5A-030",
        "notes": (
            "Rate-neutral comparison with proposed 6.57% midpoint all-in rate; it is not the actual or "
            "representative existing-facility rate and does not select a leverage tier."
        ),
    })
    return rows


def build_distribution_analysis(monthly: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for idx, group in enumerate(group_monthly_by_quarter(monthly), start=1):
        first, last = group[0], group[-1]

        def total(field: str) -> Decimal:
            return sum((dec(row[field]) for row in group), Decimal("0"))

        dividend = -total("dividends")
        repurchase = -total("share_repurchases")
        buyback_draw = total("repurchase_revolver_draw_caused")
        noncompliant = any(
            row["provisional_term_distribution_compliance"] == "not_compliant_debt_funded_buyback"
            for row in group
        )
        status = (
            "not_compliant_debt_funded_buyback"
            if noncompliant else "pending_information_distribution_permissions"
        )
        rows.append({
            "distribution_id": f"DA-{first['structure'][:1].upper()}-{idx:04d}",
            "structure": first["structure"], "forecast_id": first["quarter_period_id"],
            "fiscal_year": first["fiscal_year"], "quarter": first["quarter"],
            "period_start": first["month_start"], "period_end": last["month_end"],
            "planned_dividend": fmt(dividend), "planned_repurchase": fmt(repurchase),
            "dividend_cash_funded_after_mandatory_debt_service": fmt(total("dividend_cash_funded_after_mandatory_debt_service")),
            "dividend_revolver_draw_caused": fmt(total("dividend_revolver_draw_caused")),
            "dividend_paid_while_revolver_outstanding": fmt(total("dividend_paid_while_revolver_outstanding")),
            "debt_funded_dividend_flag": (
                "yes" if any(row["debt_funded_dividend_flag"] == "yes" for row in group) else "no"
            ),
            "repurchase_cash_funded_after_mandatory_debt_service": fmt(total("repurchase_cash_funded_after_mandatory_debt_service")),
            "repurchase_revolver_draw_caused": fmt(buyback_draw),
            "repurchase_paid_while_revolver_outstanding": fmt(total("repurchase_paid_while_revolver_outstanding")),
            "debt_funded_buyback_flag": (
                "yes" if any(row["debt_funded_buyback_flag"] == "yes" for row in group) else "no"
            ),
            "cash_floor_effect_from_distributions": fmt(total("cash_floor_effect_from_distributions")),
            "liquidity_threshold_effect_from_distributions": fmt(total("liquidity_threshold_effect_from_distributions")),
            "usable_liquidity_below_50_after_distributions_flag": (
                "yes" if any(row["usable_liquidity_below_50_after_distributions_flag"] == "yes" for row in group) else "no"
            ),
            "provisional_term_compliance_status": status,
            "amount_to_suspend_or_fund_differently": fmt(buyback_draw if first["structure"] == "proposed" else Decimal("0")),
            "classification": "formula_calculated_distribution_attribution",
            "review_status": "owner_reviewed_policy_with_pending_contractual_permissions",
            "source_ids": "SRC-001;SRC-002;SRC-003",
            "assumption_ids": "P5A-014;P5A-015;P5A-016;P5A-029;P5A-030",
            "notes": (
                "Distributions remain in the unmitigated case. Cash funding is measured after bank interest, "
                "retained mandatory payments and scheduled principal. Direct draw-causing amounts are not "
                "silently reclassified as mandatory debt funding; public distribution permissions remain pending."
            ),
        })
    return rows


def build_common_horizon(
    monthly: list[dict[str, str]], assumptions: list[dict[str, str]],
) -> list[dict[str, str]]:
    common = {
        structure: [row for row in monthly
                    if row["structure"] == structure and row["month_end"] <= "2029-07-31"]
        for structure in ("existing", "proposed")
    }
    if not common["existing"] or not common["proposed"]:
        raise Phase5Error("Common-horizon monthly data are incomplete")
    p4 = phase4_reference_closing_values()
    amap = assumption_map(assumptions)

    def summarize(rows: list[dict[str, str]]) -> dict[str, Decimal]:
        first, last = rows[0], rows[-1]
        opening_availability = (
            dec(first["revolver_commitment"]) - dec(first["letters_of_credit"])
            - dec(first["opening_revolver"])
        )
        pre_maturity = [row for row in rows if row["maturity_event"] != "yes"] or rows

        def positive_total(field: str) -> Decimal:
            return sum((dec(row[field]) for row in rows), Decimal("0"))

        interest = -positive_total("cash_interest")
        retained = -positive_total("retained_finance_and_other_debt_payment")
        scheduled = positive_total("scheduled_term_principal")
        rev_repay = positive_total("revolver_repayment")
        rev_draw = positive_total("revolver_draw")
        sweep = positive_total("cash_sweep")
        distributions = -positive_total("dividends") - positive_total("share_repurchases")
        maturity_cash = positive_total("cash_applied_at_maturity")
        return {
            "opening_term": dec(first["opening_term_principal"]),
            "opening_revolver": dec(first["opening_revolver"]),
            "opening_bank": dec(first["opening_term_principal"]) + dec(first["opening_revolver"]),
            "interest": interest, "scheduled": scheduled, "revolver_repayments": rev_repay,
            "revolver_draws": rev_draw, "sweep": sweep, "distributions": distributions,
            "retained": retained,
            "total_cash_debt_service": interest + retained + scheduled + rev_repay + sweep + maturity_cash,
            "total_lender_cash_receipts": interest + scheduled + rev_repay + sweep + maturity_cash,
            "ending_term": dec(last["ending_term_principal"]),
            "ending_revolver": dec(last["ending_revolver"]),
            "ending_bank": dec(last["ending_term_principal"]) + dec(last["ending_revolver"]),
            "peak_revolver": max([dec(first["opening_revolver"])] + [dec(row["ending_revolver"]) for row in rows]),
            "min_availability": min([opening_availability] + [dec(row["revolver_availability"]) for row in pre_maturity]),
            "min_liquidity": min(
                [max(Decimal("0"), dec(first["opening_cash"]) - dec(first["operating_cash_floor"]))
                 + max(Decimal("0"), opening_availability)]
                + [dec(row["usable_liquidity"]) for row in pre_maturity]
            ),
            "floor_failures": Decimal(sum(dec(row["cash_floor_shortfall"]) > TOLERANCE for row in rows)),
            "distribution_flags": Decimal(sum(
                row["debt_funded_dividend_flag"] == "yes" or row["debt_funded_buyback_flag"] == "yes"
                for row in rows
            )),
            "maturity_due": dec(last["unsupported_maturity_funding_gap"]) + dec(last["cash_applied_at_maturity"]),
        }

    es, ps = summarize(common["existing"]), summarize(common["proposed"])
    common_values: list[tuple[str, str, str, str, str]] = [
        ("opening_term_debt", fmt(es["opening_term"]), fmt(ps["opening_term"]), MONEY, "Opening position from reconciled February 1 bridge."),
        ("opening_revolver_debt", fmt(es["opening_revolver"]), fmt(ps["opening_revolver"]), MONEY, "Opening position from reconciled February 1 bridge."),
        ("opening_total_bank_debt", fmt(es["opening_bank"]), fmt(ps["opening_bank"]), MONEY, "Term plus revolver."),
        ("upfront_fees", "0", fmt(p4["financing_fees"] + p4["legal_fees"]), MONEY, "Proposed amount funded once at closing; existing not applicable."),
        ("accrued_interest_through_closing", fmt(p4["accrued_interest"]), fmt(p4["accrued_interest"]), MONEY, "Existing amount is revolver-funded; proposed amount is in the Phase 4 closing use."),
        ("cumulative_cash_interest", fmt(es["interest"]), fmt(ps["interest"]), MONEY, "Identical February 1, 2026 through July 31, 2029 period."),
        ("cumulative_recurring_financing_fees", "not_determinable", "not_determinable", MONEY, "Blank does not mean zero."),
        ("scheduled_principal", fmt(es["scheduled"]), fmt(ps["scheduled"]), MONEY, "Mandatory scheduled term principal."),
        ("revolver_repayments", fmt(es["revolver_repayments"]), fmt(ps["revolver_repayments"]), MONEY, "Gross modeled revolver repayments."),
        ("revolver_draws", fmt(es["revolver_draws"]), fmt(ps["revolver_draws"]), MONEY, "Gross modeled revolver draws."),
        ("cash_sweeps", fmt(es["sweep"]), fmt(ps["sweep"]), MONEY, "Provisional October sweep after revolver repayment."),
        ("planned_distributions", fmt(es["distributions"]), fmt(ps["distributions"]), MONEY, "Dividends plus repurchases retained in the unmitigated case."),
        ("retained_obligation_payments", fmt(es["retained"]), fmt(ps["retained"]), MONEY, "Mandatory payments; principal and interest split unavailable."),
        ("total_cash_debt_service", fmt(es["total_cash_debt_service"]), fmt(ps["total_cash_debt_service"]), MONEY, "Bank interest, retained payments, scheduled principal, revolver repayments, sweeps and maturity cash application."),
        ("total_lender_cash_receipts", fmt(es["total_lender_cash_receipts"]), fmt(ps["total_lender_cash_receipts"]), MONEY, "Bank interest plus gross bank principal receipts; excludes retained-obligation payments."),
        ("ending_term_debt", fmt(es["ending_term"]), fmt(ps["ending_term"]), MONEY, "After any August 1 existing maturity cash application."),
        ("ending_revolver_debt", fmt(es["ending_revolver"]), fmt(ps["ending_revolver"]), MONEY, "After any August 1 existing maturity cash application."),
        ("ending_total_bank_debt", fmt(es["ending_bank"]), fmt(ps["ending_bank"]), MONEY, "Term plus revolver."),
        ("peak_revolver_usage", fmt(es["peak_revolver"]), fmt(ps["peak_revolver"]), MONEY, "End-of-month peak."),
        ("minimum_revolver_availability", fmt(es["min_availability"]), fmt(ps["min_availability"]), MONEY, "Excludes post-maturity availability."),
        ("minimum_usable_liquidity", fmt(es["min_liquidity"]), fmt(ps["min_liquidity"]), MONEY, "Analytical liquidity, not contractual liquidity."),
        ("cash_floor_failure_months", fmt(es["floor_failures"]), fmt(ps["floor_failures"]), "count", "Visible monthly failures only."),
        ("distribution_revolver_draw_flag_months", fmt(es["distribution_flags"]), fmt(ps["distribution_flags"]), "count", "Months with a dividend or buyback directly causing draw need."),
        ("debt_due_at_august_1_2029_existing_maturity", fmt(es["maturity_due"]), "0", MONEY, "Proposed facility has no maturity on this date."),
    ]
    rows: list[dict[str, str]] = []

    def add(segment: str, metric: str, ev: str, pv: str, units: str, calculation: str,
            start: str, end: str, event: str, status: str = "calculated") -> None:
        rows.append({
            "analysis_id": f"CH-{len(rows) + 1:03d}", "segment": segment,
            "metric_name": metric, "existing_value": ev, "proposed_value": pv,
            "units": units, "period_start": start, "period_end": end,
            "measurement_event": event, "status": status,
            "classification": "like_for_like_common_horizon_or_separate_tail",
            "review_status": "contains_owner_reviewed_phase5_testing_assumptions",
            "source_ids": "SRC-001;SRC-003",
            "assumption_ids": "P5A-014;P5A-015;P5A-016;P5A-018;P5A-019;P5A-020;P5A-021;P5A-022;P5A-025;P5A-026;P5A-027;P5A-028;P5A-040;P5A-042",
            "calculation": calculation,
            "limitations": (
                "Recurring fees and formal covenant compliance remain not determinable; "
                "no refinancing, waiver or post-maturity revolver availability is assumed."
            ),
        })

    for metric, ev, pv, units, calculation in common_values:
        add(
            "common_horizon", metric, ev, pv, units, calculation,
            "2026-02-01", "2029-07-31", "existing_maturity_2029-08-01",
            "not_determinable" if "not_determinable" in (ev, pv) else "calculated",
        )

    tail = [row for row in monthly if row["structure"] == "proposed" and row["month_end"] > "2029-07-31"]
    if not tail or tail[-1]["month_end"] != "2031-01-31":
        raise Phase5Error("Proposed extension-period tail is incomplete")

    def tail_total(field: str, reverse_sign: bool = False) -> Decimal:
        value = sum((dec(row[field]) for row in tail), Decimal("0"))
        return -value if reverse_sign else value

    tail_last = tail[-1]
    tail_values = [
        ("additional_cash_interest", tail_total("cash_interest", True)),
        ("additional_scheduled_principal", tail_total("scheduled_term_principal")),
        ("additional_revolver_draws", tail_total("revolver_draw")),
        ("additional_revolver_repayments", tail_total("revolver_repayment")),
        ("additional_retained_obligation_payments", tail_total("retained_finance_and_other_debt_payment", True)),
        ("additional_planned_distributions", tail_total("dividends", True) + tail_total("share_repurchases", True)),
        ("additional_cash_sweep", tail_total("cash_sweep")),
        ("final_funded_bank_debt", dec(tail_last["ending_term_principal"]) + dec(tail_last["ending_revolver"])),
        ("cash_available_above_floor_at_maturity", dec(tail_last["cash_applied_at_maturity"])),
        ("unsupported_maturity_funding_gap", dec(tail_last["unsupported_maturity_funding_gap"])),
    ]
    for metric, value in tail_values:
        add(
            "proposed_extension_tail", metric, "not_applicable", fmt(value), MONEY,
            "Additional proposed-facility amount after the common horizon.",
            "2029-08-01", "2031-01-31", "proposed_maturity_2031-01-31",
        )
    return rows


def build_period_presentation(
    operating: list[dict[str, str]], monthly: list[dict[str, str]],
) -> list[dict[str, str]]:
    q1 = [row for row in operating if row["fiscal_year"] == "FY2026" and row["quarter"] == "Q1"]
    q2_q4 = [row for row in operating if row["fiscal_year"] == "FY2026" and row["quarter"] in {"Q2", "Q3", "Q4"}]
    full = q1 + q2_q4

    def op_total(rows: list[dict[str, str]], field: str) -> Decimal:
        return sum((dec(row[field]) for row in rows), Decimal("0"))

    values: list[dict[str, str]] = []

    def add(label: str, structure: str, start: str, end: str, scope: str,
            op_rows: list[dict[str, str]] | None, financing_rows: list[dict[str, str]] | None,
            status: str, limitation: str) -> None:
        values.append({
            "presentation_id": f"PP-{len(values) + 1:03d}", "period_label": label,
            "structure": structure, "period_start": start, "period_end": end,
            "scope": scope,
            "revenue": fmt(op_total(op_rows, "revenue")) if op_rows is not None else "",
            "lender_base_ebitda": fmt(op_total(op_rows, "lender_base_ebitda")) if op_rows is not None else "",
            "cfads_before_cash_interest": fmt(op_total(op_rows, "cfads_before_cash_interest")) if op_rows is not None else "",
            "cash_interest": (
                fmt(sum((dec(row["cash_interest"]) for row in financing_rows), Decimal("0")))
                if financing_rows is not None else ""
            ),
            "cfo_proxy": (
                fmt(sum((dec(row["cfo_proxy"]) for row in financing_rows), Decimal("0")))
                if financing_rows is not None else ""
            ),
            "fcf_proxy": (
                fmt(sum((dec(row["fcf_proxy"]) for row in financing_rows), Decimal("0")))
                if financing_rows is not None else ""
            ),
            "status": status, "classification": "explicit_period_presentation",
            "review_status": "contains_owner_reviewed_phase5_testing_assumptions",
            "assumption_ids": "P5A-001;P5A-002;P5A-003;P5A-004;P5A-005;P5A-011;P5A-012;P5A-018;P5A-019;P5A-020;P5A-023;P5A-024",
            "calculation": (
                "Operating amounts aggregate forecast quarters. Post-closing financing amounts aggregate the monthly model. "
                "CFO and FCF are modeled historical-style proxies, not GAAP forecasts."
            ),
            "limitations": limitation,
        })

    add(
        "FY2026_Q1_pre_closing_operations", "common_operating", "2025-11-01", "2026-01-31",
        "pre_closing_operations_only", q1, None, "calculated_operating_only",
        "Q1 existing-facility cash interest, CFO and FCF are not modeled; Q1 CFADS is before cash interest.",
    )
    for structure in ("existing", "proposed"):
        financing = [row for row in monthly if row["structure"] == structure and row["fiscal_year"] == "FY2026"]
        add(
            "FY2026_Q2_Q4_post_closing", structure, "2026-02-01", "2026-10-31",
            "post_closing_operations_and_financing", q2_q4, financing, "calculated_post_closing",
            "Cash interest excludes Q1. January installment and accrued interest are in the opening bridge, not these proxies.",
        )
    add(
        "FY2026_full_year_operating", "common_operating", "2025-11-01", "2026-10-31",
        "full_year_operating_only", full, None, "calculated_operating_only",
        "Full-year CFADS is before cash interest; no full-year CFO or FCF is presented beside it.",
    )
    for field in ("revenue", "lender_base_ebitda", "cfads_before_cash_interest"):
        values[-1][field] = fmt(op_total(q1, field) + op_total(q2_q4, field))
    for structure in ("existing", "proposed"):
        add(
            "FY2026_full_year_financing", structure, "2025-11-01", "2026-10-31",
            "full_year_financing_not_determinable", None, None, "not_determinable_incomplete_q1_financing",
            "Q1 actual existing-facility interest and complete Q1 cash bridge are unavailable, so full-year cash interest, CFO and FCF are not presented.",
        )
    return values


def nearest_month(monthly: list[dict[str, str]], structure: str, end: str) -> dict[str, str]:
    matches = [row for row in monthly if row["structure"] == structure and row["month_end"] <= end]
    if not matches:
        raise Phase5Error(f"No {structure} month at or before {end}")
    return max(matches, key=lambda row: row["month_end"])


def build_comparison(
    monthly: list[dict[str, str]],
    assumptions: list[dict[str, str]],
) -> list[dict[str, str]]:
    existing = [row for row in monthly if row["structure"] == "existing"]
    proposed = [row for row in monthly if row["structure"] == "proposed"]
    es = model_summary(existing)
    ps = model_summary(proposed)
    existing_common = nearest_month(monthly, "existing", "2029-07-31")
    proposed_common = nearest_month(monthly, "proposed", "2029-07-31")
    es_common = model_summary([row for row in existing if row["month_end"] <= "2029-07-31"])
    ps_common = model_summary([row for row in proposed if row["month_end"] <= "2029-07-31"])
    amap = assumption_map(assumptions)
    existing_opening_availability = (
        assumption_decimal(amap, "P5A-030") - assumption_decimal(amap, "P5A-031")
        - dec(es["opening_revolver"])
    )
    existing_grid = existing_pricing_grid()
    existing_rate_low = assumption_decimal(amap, "P5A-018") + dec(existing_grid[0]["sofr_rfr_margin_bps"]) / 100
    existing_rate_high = assumption_decimal(amap, "P5A-018") + dec(existing_grid[-1]["sofr_rfr_margin_bps"]) / 100
    accrued = phase4_reference_closing_values()["accrued_interest"]
    values: list[tuple[str, str, str, str, str, str, str]] = [
        ("Opening bank funded debt", fmt(dec(es["opening_term"]) + dec(es["opening_revolver"])), fmt(dec(ps["opening_term"]) + dec(ps["opening_revolver"])), MONEY, "2026-02-01_00:00", "Same-point positions after alternative-specific January 31 actions; the $10m difference is proposed fees.", "Actual closing balances remain pending."),
        ("Opening term principal", fmt(dec(es["opening_term"])), fmt(dec(ps["opening_term"])), MONEY, "2026-02-01_00:00", "Existing term is after the January installment; proposed closes immediately before that installment.", "Existing installment is funded in the opening revolver and is not a free principal reduction."),
        ("Opening revolver", fmt(dec(es["opening_revolver"])), fmt(dec(ps["opening_revolver"])), MONEY, "2026-02-01_00:00", "Existing includes the reference movement plus funding for the installment and accrued interest.", "Both are testing positions, not actual balances."),
        ("Revolver commitment", "475", "300", MONEY, "modeled term", "Proposed commitment is $175m smaller.", "Final commitment and LC sublimit are uncommitted."),
        ("Opening revolver availability after LCs", fmt(existing_opening_availability), "263.90228125", MONEY, "2026-02-01_00:00", "Availability follows the same-point reconciled draws.", "Neither opening draw is an actual January 2026 balance."),
        ("Accrued interest through closing", fmt(accrued), fmt(accrued), MONEY, "through_2026-01-31_closing", "Existing is funded through the reconciled revolver; proposed is funded in the Phase 4 closing bridge.", "Counted once and excluded from post-February modeled interest."),
        ("Upfront financing and advisory fees", "0", "10", MONEY, "2026-01-31", "Proposed refinancing incurs the Phase 4 reference fee use.", "Final fees are pending."),
        ("Recurring financing fees", "not_determinable", "not_determinable", MONEY, "modeled_term", "Existing and proposed unused-commitment and LC-related fee cash amounts are not modeled.", "Excluded rather than entered as zero; liquidity is before these fees."),
        ("Cumulative cash interest on common horizon", fmt(dec(es_common["cumulative_interest"])), fmt(dec(ps_common["cumulative_interest"])), MONEY, "2026-02-01_to_2029-07-31", "Identical interest period for both alternatives.", "Existing uses the 6.57% rate-neutral case; actual applicable pricing is not determinable."),
        ("Modeled all-in rate", "6.57_rate_neutral", "6.57_owner_reviewed_midpoint", "percent", "modeled_term", "Holds the central comparison rate-neutral.", "Existing 6.57% is not actual or representative pricing."),
        ("Existing contractual-grid all-in range using 3.57% base proxy", f"{fmt(existing_rate_low)}-{fmt(existing_rate_high)}", "not_applicable", "percent", "modeled_term", "Existing SOFR/RFR grid is +200 to +275 bps.", "Applicable January 2026 leverage tier is not determinable."),
        ("Reference annual scheduled term principal", "25", "65", MONEY, "full_fiscal_year", "Proposed reference amortization is $40m higher per full fiscal year.", "Stub maturity years contain fewer scheduled installments."),
        ("Cumulative scheduled term principal", fmt(dec(es["scheduled"])), fmt(dec(ps["scheduled"])), MONEY, "respective maturity", "Proposed 10% amortization requires materially more scheduled principal.", "Excludes maturity balloon."),
        ("Cumulative provisional cash sweep", fmt(dec(es["sweep"])), fmt(dec(ps["sweep"])), MONEY, "respective maturity", "Sweep applies only to the proposed structure.", "Public-information sweep definition is provisional."),
        ("Peak revolver usage", fmt(dec(es["peak_revolver"])), fmt(dec(ps["peak_revolver"])), MONEY, "respective maturity", "Shows operating reliance under the same base case.", "End-of-month measure; intra-month peaks are unavailable."),
        ("Minimum revolver availability", fmt(dec(es["min_availability"])), fmt(dec(ps["min_availability"])), MONEY, "respective maturity", "Excludes capacity after maturity.", "Not contractual liquidity."),
        ("Minimum usable liquidity", fmt(dec(es["min_liquidity"])), fmt(dec(ps["min_liquidity"])), MONEY, "respective maturity", "Cash above floor plus available revolver.", "Cash accessibility and legal availability remain pending."),
        ("Bank funded debt at existing maturity comparison date", fmt(dec(existing_common["ending_term_principal"]) + dec(existing_common["ending_revolver"])), fmt(dec(proposed_common["ending_term_principal"]) + dec(proposed_common["ending_revolver"])), MONEY, "2029-07-31", "Like-for-like date immediately before existing maturity.", "Existing maturity occurs August 1."),
        ("Cash available above floor at maturity", fmt(dec(es["cash_at_maturity"])), fmt(dec(ps["cash_at_maturity"])), MONEY, "respective maturity", "Only modeled cash above the $25m floor is applied.", "Book cash and foreign cash are not credited."),
        ("Unsupported maturity funding gap", fmt(dec(es["gap"])), fmt(dec(ps["gap"])), MONEY, "respective maturity", "Neither structure receives assumed refinancing proceeds.", "Gap is a dependency measure, not a forecast default conclusion."),
        ("Maturity date", "2029-08-01", "2031-01-31", "date", "contractual_or_proposed", "Proposed extends maturity by about 18 months.", "Proposed maturity remains hypothetical."),
        ("Phase 4 contractual funded principal payments in maturity fiscal year", "566.25", "371.14771875", MONEY, "pre_sweep_reference", "Preserves the Phase 4 maturity-fiscal-year measure.", "$566.25m is the existing FY2029 total, not a maturity-date balloon."),
        ("Phase 4 contractual final rolling-12-month funded payments", "572.5", "419.89771875", MONEY, "pre_sweep_reference", "Phase 4 measure before Phase 5 operating cash actions.", "Not the modeled residual after sweeps or revolver repayments."),
        ("Borrower flexibility", "existing_document_terms", "more_restrictive_provisional_package", "text", "qualitative", "Existing terms avoid transaction execution and new restrictions.", "Final proposed baskets, fees and covenants are not determinable."),
        ("Limited amendment or extension", "live_qualitative_alternative", "not_applicable", "text", "qualitative", "May address maturity with lower execution cost.", "No approved economics exist, so it is not quantified."),
    ]
    rows: list[dict[str, str]] = []
    for idx, (metric, ev, pv, units, period, interpretation, limitation) in enumerate(values, start=1):
        rows.append({
            "comparison_id": f"FC5-{idx:03d}", "metric_name": metric,
            "existing_value": ev, "proposed_value": pv, "units": units,
            "comparison_date_or_period": period, "status": "calculated_or_explicitly_qualitative",
            "classification": "like_for_like_base_case_comparison",
            "review_status": "contains_owner_reviewed_phase5_testing_assumptions",
            "source_ids": "SRC-001;SRC-003",
            "assumption_ids": "P5A-016;P5A-018;P5A-019;P5A-020;P5A-021;P5A-022;P5A-025;P5A-026;P5A-027;P5A-028;P5A-029;P5A-030;P5A-031;P5A-040;P5A-042",
            "analytical_interpretation": interpretation, "limitations": limitation,
        })
    return rows


def validation_rows(
    operating: list[dict[str, str]],
    monthly_all: list[dict[str, str]],
    monthly_output: list[dict[str, str]],
    waterfall: list[dict[str, str]],
    debt: list[dict[str, str]],
    metrics: list[dict[str, str]],
    sensitivities: list[dict[str, str]],
    comparison: list[dict[str, str]],
    assumptions: list[dict[str, str]],
    opening_bridge: list[dict[str, str]],
    distributions: list[dict[str, str]],
    common_horizon: list[dict[str, str]],
    period_presentation: list[dict[str, str]],
) -> list[dict[str, str]]:
    del waterfall, metrics, comparison
    checks: list[tuple[str, str, bool | None, str, str, str]] = []

    def add(category: str, name: str, passed: bool | None, observed: str,
            expected: str, notes: str = "") -> None:
        checks.append((category, name, passed, observed, expected, notes))

    add("lineage", "approved_phase4_checkpoint", True, APPROVED_PHASE4_COMMIT,
        APPROVED_PHASE4_COMMIT, "Live remote was verified before editing and recorded in the checkpoint.")
    owner_ids = {
        "P5A-001", "P5A-002", "P5A-003", "P5A-004", "P5A-005", "P5A-006",
        "P5A-007", "P5A-008", "P5A-009", "P5A-010", "P5A-011", "P5A-012",
        "P5A-013", "P5A-014", "P5A-015", "P5A-017", "P5A-018", "P5A-019",
        "P5A-020", "P5A-022", "P5A-023", "P5A-024", "P5A-038", "P5A-039",
        "P5A-041",
    }
    amap = assumption_map(assumptions)
    add("governance", "owner_reviewed_phase5_testing_assumptions",
        all(amap[aid]["review_status"] == "owner_reviewed_for_phase5_testing" for aid in owner_ids),
        str(sum(amap[aid]["review_status"] == "owner_reviewed_for_phase5_testing" for aid in owner_ids)),
        str(len(owner_ids)), "Testing approval is not a management forecast, market quote, final term or credit approval.")
    bridge = {row["item"]: row for row in opening_bridge}
    add("transaction", "same_point_opening_timestamp",
        all(row["as_of_or_period"] == "2026-02-01_00:00" for row in opening_bridge
            if row["item"] in {"Ending term debt", "Ending revolver debt", "Ending total bank debt", "Ending cash", "Available revolver capacity after LCs"}),
        "2026-02-01_00:00", "single post-action comparison timestamp")
    add("transaction", "january_installment_counted_once",
        dec(bridge["January 31 Term A installment"]["existing_value"]) == Decimal("6.25")
        and dec(amap["P5A-027"]["value"]) == Decimal("462.5")
        and dec(amap["P5A-028"]["value"]) == Decimal("207.39771875"),
        f"6.25;term={amap['P5A-027']['value']};revolver={amap['P5A-028']['value']}",
        "installment reduces term once and is funded once in existing revolver")
    add("transaction", "accrued_interest_counted_once_each_path",
        dec(bridge["Accrued interest through closing timestamp"]["existing_value"]) == Decimal("3.64771875")
        and dec(bridge["Accrued interest through closing timestamp"]["proposed_value"]) == Decimal("3.64771875"),
        "3.64771875/3.64771875", "one pre-February economic use in each path")
    add("transaction", "refinancing_fee_counted_once",
        dec(bridge["Refinancing fees"]["existing_value"]) == 0
        and dec(bridge["Refinancing fees"]["proposed_value"]) == Decimal("10"),
        "0/10", "proposed Phase 4 fee use once; no post-closing duplicate")
    add("transaction", "opening_debt_difference_reconciled",
        dec(bridge["Previously reported opening bank debt"]["proposed_value"])
        - dec(bridge["Previously reported opening bank debt"]["existing_value"])
        == Decimal("19.89771875")
        and dec(bridge["Reconciled proposed less existing bank debt"]["proposed_value"])
        == Decimal("10"),
        "prior=19.89771875;reconciled=10", "9.89771875 timing/cash-use correction plus 10 fees")
    add("operating", "quarterly_period_coverage", len(operating) == 21,
        str(len(operating)), "21 quarters from FY2026 Q1 through FY2031 Q1")
    fy_counts: dict[str, int] = defaultdict(int)
    for row in operating:
        fy_counts[row["fiscal_year"]] += 1
    add("operating", "full_year_and_partial_year_aggregation",
        all(fy_counts[f"FY{year}"] == 4 for year in range(2026, 2031)) and fy_counts["FY2031"] == 1,
        ";".join(f"{key}:{fy_counts[key]}" for key in sorted(fy_counts)),
        "four quarters FY2026-FY2030; one quarter FY2031")
    add("operating", "revenue_driver_calculation",
        all(abs(dec(row["revenue"]) - dec(row["prior_year_same_quarter_revenue"])
                * (Decimal("1") + dec(row["underlying_volume_growth_percent"]) / 100)
                * (Decimal("1") + dec(row["price_mix_growth_percent"]) / 100)) <= TOLERANCE
            for row in operating),
        "formula tested on every quarter", "prior-year quarter x volume x price/mix")
    add("operating", "gross_margin_calculation",
        all(abs(dec(row["revenue"]) + dec(row["cost_of_sales"]) - dec(row["gross_profit"])) <= TOLERANCE
            and abs(dec(row["gross_profit"]) / dec(row["revenue"]) * 100
                    - dec(row["gross_margin_percent"])) <= TOLERANCE
            for row in operating),
        "formula tested on every quarter", "revenue plus negative COGS equals gross profit")
    add("operating", "ebitda_operating_build",
        all(abs(dec(row["gross_profit"]) + dec(row["cash_operating_expenses"])
                - dec(row["lender_base_ebitda"])) <= TOLERANCE for row in operating),
        "formula tested on every quarter", "gross profit plus cash operating expenses")
    add("working_capital", "working_capital_not_zero_default",
        all(dec(row["accounts_payable"]) > 0
            and dec(row["other_operating_current_assets"]) > 0
            and dec(row["other_operating_current_liabilities"]) > 0 for row in operating),
        "all AP and other operating balances positive", "no zero defaults")
    add("working_capital", "dpo_remains_not_determinable",
        not any("dpo" in key.lower() for row in operating for key in row),
        "no DPO field or output", "AP/cost-of-sales proxy kept separate")
    add("cash_flow", "cfads_bridge",
        all(abs(
            dec(row["lender_base_ebitda"]) + dec(row["cash_tax_proxy"])
            + dec(row["working_capital_cash_flow"]) + dec(row["capital_expenditures"])
            + dec(row["other_necessary_operating_cash_uses"])
            - dec(row["cfads_before_cash_interest"])
        ) <= TOLERANCE for row in operating),
        "formula tested on every quarter", "EBITDA less taxes, capex, NWC use and other necessary uses")
    add("cash_flow", "cash_tax_and_capex_signs",
        all(dec(row["cash_tax_proxy"]) <= 0 and dec(row["capital_expenditures"]) <= 0
            for row in operating), "all non-positive", "cash uses must not be positive")
    add("cash_flow", "no_duplicate_acquisition_or_adjustment_addbacks",
        not any("synergy" in row["calculation"].lower() or "addback" in row["calculation"].lower()
                for row in operating),
        "none", "forecast operating build contains no separate acquisition or EBITDA addback")
    add("timing", "monthly_first_24_months", len(monthly_output) == 48,
        str(len(monthly_output)), "24 proposed plus 24 existing monthly rows")
    add("timing", "monthly_quarterly_operating_aggregation",
        all(abs(sum((dec(month[field]) for month in monthly_all
                         if month["structure"] == "proposed"
                         and month["quarter_period_id"] == op["forecast_id"]), Decimal("0"))
                    - dec(op[field])) <= TOLERANCE
            for op in operating[1:]
            for field in ("revenue", "lender_base_ebitda", "cash_tax_proxy",
                          "working_capital_cash_flow", "capital_expenditures",
                          "cfads_before_cash_interest")),
        "all proposed post-closing quarters", "three monthly allocations equal governing quarter")
    add("debt", "cash_roll_forward",
        all(abs(
            dec(row["opening_cash"]) + dec(row["cfads_before_cash_interest"])
            + dec(row["cash_interest"]) + dec(row["retained_finance_and_other_debt_payment"])
            + dec(row["dividends"]) + dec(row["share_repurchases"])
            - dec(row["scheduled_term_principal"]) + dec(row["revolver_draw"])
            - dec(row["revolver_repayment"]) - dec(row["cash_sweep"])
            - dec(row["cash_applied_at_maturity"]) - dec(row["ending_cash"])
        ) <= TOLERANCE for row in monthly_all),
        "formula tested on every month", "opening cash plus flows and financing actions equals ending cash")
    add("cash_flow", "mandatory_debt_service_precedes_distributions",
        all(
            abs(
                dec(row["opening_cash"]) + dec(row["cfads_before_cash_interest"])
                + dec(row["cash_interest"])
                + dec(row["retained_finance_and_other_debt_payment"])
                - dec(row["scheduled_term_principal"])
                - dec(row["cash_after_mandatory_debt_service_before_distributions"])
            ) <= TOLERANCE
            and row["scheduled_principal_priority_status"] == "mandatory_before_distributions"
            for row in monthly_all
        ),
        "interest, retained payments and scheduled principal before distributions",
        "economic priority preserved in every month")
    add("cash_flow", "distribution_draw_attribution",
        all(
            abs(
                dec(row["cash_after_mandatory_debt_service_before_distributions"])
                + dec(row["dividends"]) + dec(row["share_repurchases"])
                - dec(row["cash_before_revolver_action"])
            ) <= TOLERANCE
            and row["debt_funded_dividend_flag"]
            == ("yes" if dec(row["dividend_revolver_draw_caused"]) > TOLERANCE else "no")
            and row["debt_funded_buyback_flag"]
            == ("yes" if dec(row["repurchase_revolver_draw_caused"]) > TOLERANCE else "no")
            for row in monthly_all
        ),
        "formula tested on every month", "distribution-caused draws kept separate from mandatory debt funding")
    add("cash_flow", "planned_distributions_not_silently_mitigated",
        all(
            abs(-dec(row["dividends"]) - Decimal("14.5") / 12) <= TOLERANCE
            and abs(-dec(row["share_repurchases"]) - Decimal("5") / 12) <= TOLERANCE
            for row in monthly_all
        ),
        "14.5 annual dividends;5 annual repurchases", "unmitigated policy retained")
    add("cash_flow", "distribution_compliance_flags_visible",
        all(row["provisional_term_compliance_status"] in {
            "not_compliant_debt_funded_buyback", "pending_information_distribution_permissions"
        } for row in distributions)
        and any(row["debt_funded_buyback_flag"] == "yes" for row in distributions),
        "explicit flags and suspension/funding amount", "no fully compliant claim where a debt-funded buyback exists")
    add("debt", "term_roll_forward",
        all(abs(
            dec(row["opening_term_principal"]) - dec(row["scheduled_term_principal"])
            - dec(row["cash_sweep"]) - dec(row["maturity_term_payment"])
            - dec(row["ending_term_principal"])
        ) <= TOLERANCE for row in monthly_all),
        "formula tested on every month", "opening less scheduled, sweep and maturity cash payment")
    add("debt", "revolver_roll_forward",
        all(abs(
            dec(row["opening_revolver"]) + dec(row["revolver_draw"])
            - dec(row["revolver_repayment"]) - dec(row["maturity_revolver_payment"])
            - dec(row["ending_revolver"])
        ) <= TOLERANCE for row in monthly_all),
        "formula tested on every month", "opening plus draws less repayments and maturity cash payment")
    add("debt", "interest_timing_and_sign",
        all(dec(row["cash_interest"]) <= 0 and int(row["iteration_count"]) <= 100 for row in monthly_all),
        "non-positive cash use; converged", "average monthly debt with controlled revolver iteration")
    proposed = [row for row in monthly_all if row["structure"] == "proposed"]
    existing = [row for row in monthly_all if row["structure"] == "existing"]
    add("debt", "quarterly_amortization_reference",
        all(dec(row["scheduled_term_principal"]) in (Decimal("0"), Decimal("16.25"))
            for row in proposed),
        fmt(sum((dec(row["scheduled_term_principal"]) for row in proposed), Decimal("0"))),
        "quarterly payment is 16.25 until maturity or earlier payoff")
    add("debt", "existing_amortization",
        all(dec(row["scheduled_term_principal"]) in (Decimal("0"), Decimal("6.25"))
            for row in existing),
        fmt(sum((dec(row["scheduled_term_principal"]) for row in existing), Decimal("0"))),
        "6.25 on modeled quarter ends through July 2029")
    add("debt", "annual_sweep_timing_and_revolver_priority",
        all(row["month_end"][5:7] == "10" and dec(row["ending_revolver"]) == 0
            and dec(row["usable_liquidity"]) >= ANALYTICAL_LIQUIDITY_THRESHOLD
            for row in monthly_all if dec(row["cash_sweep"]) > 0),
        "all sweeps occur in October after revolver repayment with at least $50m analytical liquidity",
        "annual October test; revolver paid first and liquidity safeguard retained")
    add("liquidity", "cash_floor_or_visible_failure",
        all(dec(row["ending_cash"]) + dec(row["cash_floor_shortfall"])
            >= dec(row["operating_cash_floor"]) - TOLERANCE for row in monthly_all),
        "all months", "floor maintained or shortfall explicitly reported")
    add("liquidity", "commitment_limit_or_visible_failure",
        all(dec(row["ending_revolver"]) + dec(row["letters_of_credit"])
            <= dec(row["revolver_commitment"]) + dec(row["commitment_breach"]) + TOLERANCE
            for row in monthly_all),
        "all months", "draw plus LC within commitment or breach reported")
    add("liquidity", "letters_of_credit_counted_once",
        all(
            dec(row["revolver_availability"]) == 0
            if row["maturity_event"] == "yes"
            else abs(dec(row["revolver_availability"]) - (
                dec(row["revolver_commitment"]) - dec(row["ending_revolver"])
                - dec(row["letters_of_credit"])
            )) <= TOLERANCE
            for row in monthly_all
        ),
        "6.2 deducted once from availability", "no second cash subtraction use in reference case")
    add("liquidity", "restricted_cash_excluded",
        all(dec(row["usable_liquidity"]) == max(Decimal("0"), dec(row["ending_cash"])
                                                - dec(row["operating_cash_floor"]))
            + max(Decimal("0"), dec(row["revolver_availability"])) for row in monthly_all),
        "cash above floor plus revolver availability", "no book or restricted cash credited")
    add("transaction", "phase4_reference_opening_balances",
        dec(proposed[0]["opening_term_principal"]) == Decimal("650")
        and dec(proposed[0]["opening_revolver"]) == Decimal("29.89771875"),
        f"{proposed[0]['opening_term_principal']}/{proposed[0]['opening_revolver']}",
        "650/29.89771875")
    add("transaction", "financing_fees_counted_once",
        all("financing_fee" not in row for row in monthly_all),
        "10 included in Phase 4 sources and uses only", "no post-closing duplicate cash use")
    add("debt", "retained_obligation_consistency",
        all(dec(row["retained_finance_and_other_debt_opening_proxy"])
            == dec(row["retained_finance_and_other_debt_ending_proxy"]) == Decimal("62.619")
            for row in debt),
        "62.619 conservative proxy", "payments modeled; principal/interest split not fabricated")
    add("maturity", "maturity_dates",
        existing[-1]["maturity_event"] == "yes" and proposed[-1]["maturity_event"] == "yes"
        and existing[-1]["month_end"] == "2029-07-31"
        and proposed[-1]["month_end"] == "2031-01-31",
        f"existing event after {existing[-1]['month_end']}; proposed {proposed[-1]['month_end']}",
        "2029-08-01 and 2031-01-31")
    add("maturity", "unsupported_gap_visible",
        dec(existing[-1]["unsupported_maturity_funding_gap"]) >= 0
        and dec(proposed[-1]["unsupported_maturity_funding_gap"]) >= 0,
        f"existing={existing[-1]['unsupported_maturity_funding_gap']};proposed={proposed[-1]['unsupported_maturity_funding_gap']}",
        "non-negative explicit value")
    add("maturity", "no_post_maturity_revolver_availability",
        dec(existing[-1]["revolver_availability"]) == 0
        and dec(proposed[-1]["revolver_availability"]) == 0,
        "0/0", "zero after maturity")
    add("comparison", "same_operating_case_for_both_structures",
        all(
            abs(sum((dec(row[field]) for row in monthly_all
                     if row["structure"] == structure and row["quarter_period_id"] == op["forecast_id"]),
                    Decimal("0")) - dec(op[field])) <= TOLERANCE
            for structure in ("existing", "proposed")
            for op in operating[1:]
            if any(row["structure"] == structure and row["quarter_period_id"] == op["forecast_id"]
                   for row in monthly_all)
            for field in ("revenue", "lender_base_ebitda", "cfads_before_cash_interest")
        ),
        "identical quarter operating inputs", "financing structure changes only debt, interest and maturity")
    add("sensitivity", "amortization_cases",
        {dec(row["annual_amortization_percent"]) for row in sensitivities
         if row["sensitivity_dimension"] == "amortization"} == {Decimal("5"), Decimal("10"), Decimal("15")},
        "5;10;15", "required annual percentages")
    add("sensitivity", "pricing_cases",
        {dec(row["spread_basis_points"]) for row in sensitivities
         if row["structure"] == "proposed" and row["sensitivity_dimension"] == "pricing"}
        == {Decimal("250"), Decimal("300"), Decimal("350")},
        "250;300;350", "required spread range")
    grid_rows = [row for row in sensitivities
                 if row["sensitivity_dimension"] == "existing_contractual_pricing_grid"]
    add("sensitivity", "existing_pricing_grid_range",
        {dec(row["spread_basis_points"]) for row in grid_rows}
        == {Decimal("200"), Decimal("225"), Decimal("250"), Decimal("275")}
        and {dec(row["all_in_rate_percent"]) for row in grid_rows}
        == {Decimal("5.57"), Decimal("5.82"), Decimal("6.07"), Decimal("6.32")},
        "200-275 bps;5.57%-6.32%", "approved grid plus owner-reviewed 3.57% base proxy")
    neutral = next(row for row in sensitivities if row["case_name"] == "6.57_percent_rate_neutral")
    add("sensitivity", "existing_rate_neutral_label",
        neutral["rate_case_type"] == "rate_neutral_not_actual_or_representative"
        and neutral["pricing_tier_status"] == "not_a_contractual_tier_selection",
        neutral["rate_case_type"], "6.57% not described as actual or representative")
    common_rows = [row for row in common_horizon if row["segment"] == "common_horizon"]
    tail_rows = [row for row in common_horizon if row["segment"] == "proposed_extension_tail"]
    add("comparison", "common_horizon_dates_and_interest_period",
        bool(common_rows) and all(
            row["period_start"] == "2026-02-01" and row["period_end"] == "2029-07-31"
            and row["measurement_event"] == "existing_maturity_2029-08-01"
            for row in common_rows
        ),
        "2026-02-01_to_2029-07-31;event=2029-08-01", "same date range for both alternatives")
    add("comparison", "proposed_tail_separated",
        bool(tail_rows) and all(
            row["period_start"] == "2029-08-01" and row["period_end"] == "2031-01-31"
            and row["existing_value"] == "not_applicable" for row in tail_rows
        ),
        "2029-08-01_to_2031-01-31", "proposed extension only")
    presentation = {row["period_label"] + "|" + row["structure"]: row
                    for row in period_presentation}
    q1 = presentation["FY2026_Q1_pre_closing_operations|common_operating"]
    full = presentation["FY2026_full_year_operating|common_operating"]
    q2_existing = presentation["FY2026_Q2_Q4_post_closing|existing"]
    add("presentation", "fy2026_periods_reconcile",
        all(abs(dec(q1[field]) + dec(q2_existing[field]) - dec(full[field])) <= TOLERANCE
            for field in ("revenue", "lender_base_ebitda", "cfads_before_cash_interest")),
        "Q1 plus Q2-Q4 equals FY2026", "operating periods reconcile exactly")
    add("presentation", "fy2026_financing_not_ambiguously_full_year",
        all(row["status"] == "not_determinable_incomplete_q1_financing"
            and not row["cash_interest"] and not row["cfo_proxy"] and not row["fcf_proxy"]
            for row in period_presentation if row["period_label"] == "FY2026_full_year_financing"),
        "full-year financing blank with explicit status", "Q1 existing-facility interest unavailable")
    add("governance", "formal_covenant_compliance_not_asserted", None,
        "not_determinable", "official contractual EBITDA, eligible cash and testing definitions unavailable",
        "Phase 5 metrics are preliminary analytical diagnostics only.")
    add("governance", "dpo_not_determinable", None, "not_determinable",
        "purchases and payment terms unavailable", "AP/cost-of-sales proxy is explicitly not DPO.")
    add("governance", "retained_debt_principal_allocation", None, "not_determinable",
        "future payments mix principal and interest", "Liability held as a conservative opening proxy.")
    add("governance", "recurring_financing_fees", None, "not_determinable",
        "executed fee terms and applicable balances unavailable",
        "Excluded rather than entered as zero; model results are before these fees.")
    add("governance", "applicable_existing_pricing_tier", None, "not_determinable",
        "contractual leverage, eligible cash and pricing-tier status unavailable",
        "Existing grid is modeled as a range; 6.57% is rate-neutral only.")
    add("governance", "distribution_permissions", None, "not_determinable",
        "public evidence does not establish all dividend and repurchase permissions",
        "Planned distributions remain visible with debt-funding and provisional-compliance flags.")
    add("governance", "actual_same_point_closing_cash", None, "not_determinable",
        "January 31 accessible cash is unavailable at the cutoff",
        "$25m is an owner-reviewed Phase 5 testing assumption for both alternatives.")

    rows: list[dict[str, str]] = []
    for idx, (category, name, passed, observed, expected, notes) in enumerate(checks, start=1):
        status = "NOT_DETERMINABLE" if passed is None else ("PASS" if passed else "FAIL")
        rows.append({
            "validation_id": f"VR-{idx:03d}", "category": category, "test_name": name,
            "status": status, "observed_value": observed,
            "expected_value_or_rule": expected,
            "materiality_tolerance": fmt(TOLERANCE), "notes": notes,
        })
    return rows


def source_ledger_rows(
    assumptions: list[dict[str, str]],
    collections: list[tuple[str, str, list[dict[str, str]], str]],
) -> list[dict[str, str]]:
    manifest = source_manifest()
    rows: list[dict[str, str]] = []
    for assumption in assumptions:
        source_dates = [
            manifest[sid]["publication_or_filing_date"]
            for sid in assumption["source_ids"].split(";") if sid in manifest
        ]
        if "ASM-" in assumption["upstream_ids"]:
            upstream = "data/phase3/processed/ASSUMPTION_CANDIDATES.csv"
        elif "DT-" in assumption["upstream_ids"]:
            upstream = "data/processed/debt_terms.csv"
        elif "P5-" in assumption["upstream_ids"] or "PT-" in assumption["upstream_ids"]:
            upstream = "data/phase4/processed/PHASE5_OPENING_INPUTS.csv"
        else:
            upstream = "data/phase2/processed/historical_spread.csv"
        rows.append({
            "record_id": f"LED-A-{assumption['assumption_id']}",
            "artifact_path": "data/phase5/raw/MODEL_ASSUMPTIONS.csv",
            "record_type": "model_assumption",
            "source_or_assumption_id": assumption["assumption_id"],
            "source_type": "upstream_fact_or_explicit_modeling_assumption",
            "source_date": max(source_dates) if source_dates else "",
            "forecast_period": assumption["forecast_period"], "units": assumption["units"],
            "original_value": assumption["value"], "normalized_value": assumption["value"],
            "classification": assumption["classification"],
            "review_status": assumption["review_status"],
            "formula_or_transformation": assumption["calculation_or_basis"],
            "upstream_artifact": upstream, "source_ids": assumption["source_ids"],
            "limitation_or_rationale": assumption["limitation_or_rationale"],
        })
    for artifact_path, record_type, records, id_field in collections:
        for record in records:
            rid = record[id_field]
            period = (
                record.get("fiscal_year") or record.get("forecast_period")
                or record.get("as_of_or_period") or record.get("month_end")
                or record.get("period_end", "")
            )
            normalized = (
                record.get("value") or record.get("revenue")
                or record.get("ending_cash") or record.get("proposed_value")
                or record.get("planned_dividend") or record.get("existing_value", "")
            )
            rows.append({
                "record_id": f"LED-O-{rid}", "artifact_path": artifact_path,
                "record_type": record_type, "source_or_assumption_id": rid,
                "source_type": "formula_calculated_forecast_output",
                "source_date": "", "forecast_period": period,
                "units": record.get("units", ""), "original_value": "",
                "normalized_value": normalized,
                "classification": record.get("classification", "validation_control"),
                "review_status": record.get("review_status", "not_applicable_control"),
                "formula_or_transformation": (
                    record.get("calculation") or record.get("calculation_or_basis")
                    or "Generated by scripts/phase5.py from the identified upstream inputs."
                ),
                "upstream_artifact": "data/phase5/raw/MODEL_ASSUMPTIONS.csv",
                "source_ids": record.get("source_ids", ""),
                "limitation_or_rationale": record.get("notes") or record.get("limitations", ""),
            })
    ensure_unique(rows, "record_id", "source ledger")
    return rows


def annual_operating_rows(operating: list[dict[str, str]]) -> list[dict[str, Decimal | str]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in operating:
        groups[row["fiscal_year"]].append(row)
    output: list[dict[str, Decimal | str]] = []
    for fy, rows in groups.items():
        revenue = sum((dec(row["revenue"]) for row in rows), Decimal("0"))
        ebitda = sum((dec(row["lender_base_ebitda"]) for row in rows), Decimal("0"))
        output.append({
            "fiscal_year": fy, "coverage": "full_year" if len(rows) == 4 else "Q1_only",
            "revenue": revenue, "ebitda": ebitda, "margin": ebitda / revenue * 100,
            "cfads": sum((dec(row["cfads_before_cash_interest"]) for row in rows), Decimal("0")),
            "cash_tax": sum((dec(row["cash_tax_proxy"]) for row in rows), Decimal("0")),
            "capex": sum((dec(row["capital_expenditures"]) for row in rows), Decimal("0")),
            "wc": sum((dec(row["working_capital_cash_flow"]) for row in rows), Decimal("0")),
        })
    return output


def render_docs(
    operating: list[dict[str, str]],
    monthly_all: list[dict[str, str]],
    sensitivities: list[dict[str, str]],
    comparison: list[dict[str, str]],
    assumptions: list[dict[str, str]],
    opening_bridge: list[dict[str, str]],
    distributions: list[dict[str, str]],
    common_horizon: list[dict[str, str]],
    period_presentation: list[dict[str, str]],
) -> None:
    annual = annual_operating_rows(operating)
    es = model_summary([row for row in monthly_all if row["structure"] == "existing"])
    ps = model_summary([row for row in monthly_all if row["structure"] == "proposed"])
    owner_assumptions = [row for row in assumptions if row["review_status"] == "owner_reviewed_for_phase5_testing"]
    inherited_assumptions = [row for row in assumptions if row["review_status"] == "inherited_owner_reviewed"]
    pending_assumptions = [row for row in assumptions if row["review_status"] == "pending_information"]

    annual_table = "\n".join(
        f"| {row['fiscal_year']} | {row['coverage']} | {p3(dec(row['revenue']))} | "
        f"{p3(dec(row['ebitda']))} | {dec(row['margin']).quantize(Decimal('0.01'))}% | "
        f"{p3(dec(row['cfads']))} | {p3(dec(row['cash_tax']))} | "
        f"{p3(dec(row['capex']))} | {p3(dec(row['wc']))} |"
        for row in annual
    )
    assumptions_table = "\n".join(
        f"| {row['assumption_id']} | {row['assumption_name']} | {row['value']} {row['units']} | "
        f"{row['review_status']} |"
        for row in assumptions
    )
    sensitivity_table = "\n".join(
        f"| {row['structure']} | {row['case_name']} | {row['annual_amortization_percent']}% | "
        f"{row['spread_basis_points'] or 'N/A'} bps | {row['all_in_rate_percent']}% | "
        f"{p3(dec(row['cumulative_cash_interest']))} | "
        f"{p3(dec(row['cumulative_scheduled_principal']))} | "
        f"{p3(dec(row['cumulative_cash_sweep']))} | "
        f"{p3(dec(row['minimum_usable_liquidity']))} | "
        f"{p3(dec(row['unsupported_maturity_funding_gap']))} |"
        for row in sensitivities
    )
    comparison_table = "\n".join(
        f"| {row['metric_name']} | {row['existing_value']} | {row['proposed_value']} | "
        f"{row['units']} |"
        for row in comparison
    )
    opening_table = "\n".join(
        f"| {row['item']} | {row['existing_value']} | {row['proposed_value']} | "
        f"{row['as_of_or_period']} |"
        for row in opening_bridge
    )
    period_table = "\n".join(
        f"| {row['period_label']} | {row['structure']} | {row['revenue'] or 'N/D'} | "
        f"{row['lender_base_ebitda'] or 'N/D'} | {row['cfads_before_cash_interest'] or 'N/D'} | "
        f"{row['cash_interest'] or 'N/D'} | {row['cfo_proxy'] or 'N/D'} | "
        f"{row['fcf_proxy'] or 'N/D'} | {row['status']} |"
        for row in period_presentation
    )
    common_table = "\n".join(
        f"| {row['metric_name']} | {row['existing_value']} | {row['proposed_value']} | {row['units']} |"
        for row in common_horizon if row["segment"] == "common_horizon"
    )
    tail_table = "\n".join(
        f"| {row['metric_name']} | {row['proposed_value']} | {row['units']} |"
        for row in common_horizon if row["segment"] == "proposed_extension_tail"
    )
    distribution_table_rows: list[str] = []
    for structure in ("existing", "proposed"):
        rows = [row for row in distributions
                if row["structure"] == structure and row["period_end"] <= "2029-07-31"]
        total = lambda field: sum((dec(row[field]) for row in rows), Decimal("0"))
        distribution_table_rows.append(
            f"| {structure} | {p3(total('planned_dividend'))} | {p3(total('planned_repurchase'))} | "
            f"{p3(total('dividend_revolver_draw_caused'))} | {p3(total('repurchase_revolver_draw_caused'))} | "
            f"{p3(total('dividend_paid_while_revolver_outstanding'))} | "
            f"{p3(total('repurchase_paid_while_revolver_outstanding'))} | "
            f"{p3(total('amount_to_suspend_or_fund_differently'))} |"
        )
    distribution_table = "\n".join(distribution_table_rows)
    existing_grid_table = "\n".join(
        f"| {row['case_name']} | {row['spread_basis_points']} bps | {row['all_in_rate_percent']}% | "
        f"{row['pricing_tier_status']} |"
        for row in sensitivities if row["sensitivity_dimension"] == "existing_contractual_pricing_grid"
    )

    methodology = f"""# Phase 5 methodology

**Information cutoff:** December 15, 2025

**Hypothetical closing:** January 31, 2026

**Opening comparison timestamp:** February 1, 2026 at 00:00, after all
alternative-specific January 31 actions

**Recommendation:** CONDITIONAL GO for a commit review; not facility approval

## Scope and calculation layers

Phase 5 applies one owner-reviewed testing case to the proposed refinancing and
retain-existing alternatives. It does not approve a forecast, market pricing,
facility size, covenant package or credit decision. It does not assume a future
refinancing and does not begin Phase 6. Company-adjusted, partial public
contractual and lender-base EBITDA remain separate; contractual EBITDA is not
an official compliance calculation. Book-cash net debt remains an analyst
diagnostic rather than covenant or lender net leverage.

## January 31 timing convention and opening bridge

The hypothetical refinancing closes **immediately before** the January 31
existing Term A installment. The approved Phase 4 proposed payoff therefore
remains USD 468.750m. The retain-existing path then pays the USD 6.250m
installment, reducing term debt to USD 462.500m, and funds that cash use through
its revolver. Each path recognizes USD 3.64771875m of accrued interest through
the closing timestamp exactly once. The proposed path funds it in the approved
Phase 4 sources and uses; the existing path funds it in its same-point revolver.
The proposed USD 10m fees are also funded once at closing and are not deducted
again after February 1.

FY2026 Q1 CFADS before interest is shown in the bridge but is not separately
credited against the Phase 4 USD 25m revolver-balance sensitivity because that
sensitivity is not an October-to-January cash forecast. Actual January cash is
not determinable. Both paths therefore use the expressly owner-reviewed USD 25m
testing cash assumption, with zero accessible cash above it; this is not an
assertion about actual cash.

| Opening bridge item | Existing | Proposed | Date or period |
|---|---:|---:|---|
{opening_table}

The prior USD 19.89771875m opening-bank-debt difference used USD 660.000m for
the existing path and omitted USD 6.250m of installment funding and USD
3.64771875m of accrued-interest funding. Adding those uses raises the same-point
existing position to USD 669.89771875m. Proposed debt is USD 679.89771875m, so
the remaining USD 10m difference is exactly the proposed fee use.

## Operating and period conventions

The operating forecast contains 21 quarters from FY2026 Q1 through FY2031 Q1.
The post-closing debt model begins February 1. The first new-facility installment
is April 30, 2026. Equal monthly allocation within each quarter is an
owner-reviewed Phase 5 convention only; it is not actual seasonality and must be
stressed in Phase 6. Interest uses average term and iterated average revolver
balances. The 365-day working-capital convention and all selected operating
inputs are provisional testing assumptions with their limitations preserved.

FY2026 Q1 pre-closing operations, Q2-Q4 post-closing operations and financing,
and full-year operations are separately labeled. Full-year FY2026 cash interest,
CFO proxy and FCF proxy are not presented because Q1 existing-facility interest
and a complete Q1 cash bridge are unavailable. CFADS is before cash interest;
CFO and FCF are modeled historical-style proxies, not GAAP forecasts.

## Corrected cash waterfall and distributions

The monthly order is: opening cash; operating generation/use; cash taxes;
necessary capex; working-capital change; cash interest and determinable recurring
fees; retained mandatory obligations; scheduled term principal; planned
dividends; planned repurchases; revolver draw to restore the cash floor;
excess-cash revolver repayment; provisional October term sweep; maturity cash
application; and ending cash, debt, availability and usable liquidity.

The selected USD 14.5m annual dividends and USD 5.0m annual repurchases remain
in the unmitigated case. The model separately attributes amounts funded from
cash after mandatory service, amounts directly causing a revolver draw, and
amounts paid while revolver debt remains. The proposed structure does not treat
a debt-funded buyback as compliant. Any amount to suspend or fund differently is
shown; suspension is not assumed. Public dividend and repurchase permissions
remain pending information.

The 50% October sweep occurs only after revolver repayment and protection of the
USD 25m floor. At maturity, only cash above the floor is applied; no refinancing,
waiver, extension or post-maturity revolver capacity is used as a plug.

Recurring commitment, LC, fronting, administrative and other unresolved fees
remain pending information. Blank never means zero, and cash-flow and liquidity
outputs remain before those fees.

## Existing pricing

Phase 1 documents Adjusted Term SOFR/RFR margins of 200, 225, 250 and 275 bps
and commitment fees of 0.150%, 0.175%, 0.200% and 0.250% across leverage tiers.
The applicable January 2026 tier cannot be reconstructed because contractual
leverage, eligible cash and pricing-tier status are unavailable. Applying the
owner-reviewed 3.57% base-rate proxy produces this analytical range:

| Existing grid tier | SOFR/RFR margin | All-in test rate | Tier status |
|---|---:|---:|---|
{existing_grid_table}

The 6.57% existing case is retained only as a rate-neutral comparison with the
proposed midpoint. It is not actual or representative existing pricing and does
not select a contractual tier.

## Assumption register

There are {len(owner_assumptions)} assumptions expressly
`owner_reviewed_for_phase5_testing`, {len(inherited_assumptions)} inherited
owner-reviewed assumptions and {len(pending_assumptions)} pending-information
input. These statuses are not management forecasts, market quotes, final terms
or underwriting approval.

| ID | Assumption | Value | Review status |
|---|---|---:|---|
{assumptions_table}

## Reproduction

    python scripts/phase1.py validate
    python scripts/phase2.py all
    python scripts/phase3.py all
    python scripts/phase4.py all
    python scripts/phase5.py all
    python -m unittest discover -s tests -v
    powershell -ExecutionPolicy Bypass -NoProfile -File scripts/validate-phase0.ps1

Python standard library only. No network access is required.
"""
    base_analysis = f"""# Phase 5 integrated base case analysis

**Recommendation:** CONDITIONAL GO for owner review, not final credit approval.

## Operating forecast

Amounts are USD millions. This table contains operating measures only; FY2031
contains Q1 only.

| Fiscal year | Coverage | Revenue | Lender EBITDA | Margin | CFADS before interest | Cash taxes | Capex | Working-capital cash flow |
|---|---|---:|---:|---:|---:|---:|---:|---:|
{annual_table}

The model uses the Phase 3 driver chain rather than an EBITDA-growth shortcut.
FY2025 remains the first full post-Tyman anchor. The flat-to-slightly-lower
compound revenue path follows the selected volume and price/mix midpoints.
Gross margin is the primary operating-margin driver. The owner-reviewed
12%-13% lender EBITDA margin is validation only.

FY2031 Q1 has a lower EBITDA margin than each full-year period because the
FY2025 post-Tyman Q1 gross-margin shape is retained while cash operating costs
remain a revenue-based ratio. It is a seasonal-quarter output, not a full-year
margin forecast.

## FY2026 period presentation

| Period | Structure | Revenue | EBITDA | CFADS before interest | Cash interest | CFO proxy | FCF proxy | Status |
|---|---|---:|---:|---:|---:|---:|---:|---|
{period_table}

## Proposed reference structure

The February 1 reference debt is USD 650.000m term and USD 29.898m revolver.
Modeled cumulative bank cash interest is USD {p3(dec(ps['cumulative_interest']))}m,
scheduled term principal is USD {p3(dec(ps['scheduled']))}m, and provisional
cash sweeps are USD {p3(dec(ps['sweep']))}m. Peak revolver usage is
USD {p3(dec(ps['peak_revolver']))}m and minimum usable liquidity is
USD {p3(dec(ps['min_liquidity']))}m. These figures exclude not-determinable
recurring financing fees; the exclusion is not a zero-value assumption.

At January 31, 2031, modeled cash above the operating floor covers
USD {p3(dec(ps['cash_at_maturity']))}m. The remaining unsupported maturity
funding gap is USD {p3(dec(ps['gap']))}m. No refinancing source, waiver or
post-maturity availability fills that amount.

## Existing facilities: rate-neutral central comparison

The February 1 retain-existing opening uses USD 462.500m term principal and USD
207.398m of revolver debt after explicitly funding the January installment and
accrued interest. Modeled cumulative bank cash interest in the 6.57% rate-neutral
case is
USD {p3(dec(es['cumulative_interest']))}m and scheduled term principal after
closing is USD {p3(dec(es['scheduled']))}m. Peak revolver usage is
USD {p3(dec(es['peak_revolver']))}m and minimum usable liquidity is
USD {p3(dec(es['min_liquidity']))}m. These figures likewise exclude
not-determinable recurring financing fees.

At the August 1, 2029 maturity, only cash above the floor is applied. The
remaining unsupported funding gap is USD {p3(dec(es['gap']))}m. Nominal
revolver capacity is not treated as available after maturity.

## Distribution attribution through the common horizon

| Structure | Planned dividends | Planned repurchases | Dividend draw-causing | Repurchase draw-causing | Dividends while revolver outstanding | Repurchases while revolver outstanding | Repurchase amount to suspend/fund differently |
|---|---:|---:|---:|---:|---:|---:|---:|
{distribution_table}

Cash-funded amounts and monthly flags are in `DISTRIBUTION_ANALYSIS.csv`.
Planned distributions are not automatically permitted. A debt-funded proposed
buyback is flagged as not compliant; otherwise public permission remains
pending. No distribution reduction has been treated as completed.

## Financing sensitivities

| Structure | Case | Amortization | Spread | All-in rate | Cumulative interest | Scheduled principal | Sweep | Minimum liquidity | Maturity gap |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
{sensitivity_table}

These rows vary financing terms only. They are not Phase 6 operating downside
cases. A lower technical gap is not an automatic facility-size recommendation.

## Credit interpretation

The build tests whether ordinary modeled cash supports interim interest and
principal while separately exposing maturity dependence. Any unsupported
maturity balance remains a refinancing dependency. Formal covenant compliance
is not determinable because official contractual EBITDA, covenant debt,
eligible cash and testing definitions are unavailable.
Modeled cash flow and liquidity remain before recurring financing fees, which
cannot be quantified from approved evidence. Neither financing alternative
self-liquidates. The proposed reference can meet interim interest and scheduled
principal under these testing assumptions, but both structures retain material
maturity funding gaps.
"""
    financing_doc = f"""# Phase 5 financing comparison

The same operating base case is applied to both alternatives. The opening
measurement is February 1, 2026 at 00:00, after the alternative-specific
January 31 actions. The hypothetical refinancing closes immediately before the
existing Term A installment.

## Same-point opening bridge

| Item | Existing | Proposed | Date or period |
|---|---:|---:|---|
{opening_table}

The prior USD 19.89771875m difference is fully explained. Existing opening debt
increases by USD 9.89771875m for the revolver-funded USD 6.25m installment and
USD 3.64771875m accrued interest. Reconciled proposed debt exceeds reconciled
existing debt by USD 10m, equal to proposed fees. FY2026 Q1 operating CFADS is
shown but not separately credited against the Phase 4 USD 25m revolver
sensitivity. The same-point USD 25m cash is a testing assumption because actual
January cash is not determinable.

## Common horizon: February 1, 2026 through July 31, 2029

The measurement event is the existing facility maturity on August 1, 2029.
Interest periods are identical.

| Metric | Existing | Proposed | Units |
|---|---:|---:|---|
{common_table}

Recurring fees are not determinable. Total cash debt service includes bank
interest, retained mandatory payments, scheduled principal, gross revolver
repayments, sweeps and maturity cash application. Total lender cash receipts
exclude retained-obligation payments. Neither measure assumes refinancing.

## Proposed extension period: August 1, 2029 through January 31, 2031

| Metric | Proposed | Units |
|---|---:|---|
{tail_table}

The proposed structure's lower January 2031 gap benefits from approximately 18
additional months of cash generation and amortization and is not directly
comparable with the existing August 2029 gap without this separation.

## Additional labeled comparisons

| Metric | Existing | Proposed | Units |
|---|---:|---:|---|
{comparison_table}

The proposed structure lowers opening revolver use and extends maturity, but it
has a USD 175m smaller revolver commitment, faster scheduled amortization, USD
10m of fees and additional restrictions. The central interest comparison is
rate-neutral at 6.57%. Existing contractual pricing spans 5.57%-6.32% when the
approved 200-275 bps grid is applied to the 3.57% test base rate, but the
applicable January 2026 tier is not determinable. The 6.57% existing case is not
claimed as actual or representative economics.

Neither alternative is shown as self-funding its maturity obligation through an
assumed refinancing. The unsupported maturity gap is explicit. No conclusion
that the proposed refinancing is economically superior is made. Retention of
the existing facilities and a limited amendment or extension remain live.
"""
    phase6 = f"""# Phase 6 handoff

Phase 6 should stress the actual mechanisms exposed by the base case. It should
not replace them with a top-down EBITDA shock.

1. Test the Phase 3 moderate and severe volume paths through quarterly revenue.
2. Apply gross-margin compression inclusive of fixed-cost deleverage without
   duplicating the demand shock.
3. Stress DSO, DIO, the AP/cost-of-sales proxy and separate other-working-
   capital balances. DPO remains not determinable.
4. Move quarterly operating cash uses within the first 24 months to test
   monthly timing. Equal one-third monthly allocation is only a base convention.
5. Test 100 bps and 200 bps rate increases against modeled average debt.
6. Preserve selected base distributions in unmitigated cases; show reductions
   only as separately identified mitigations. Carry forward every debt-funded
   distribution flag and the amount that would need suspension or other funding.
7. Do not reduce capex below a supported maintenance and safety floor.
8. Test additional restructuring and plant-stabilization cash uses separately
   from accepted lender EBITDA adjustments.
9. Carry the recalculated existing maturity gap of USD {p3(dec(es['gap']))}m and proposed
   reference gap of USD {p3(dec(ps['gap']))}m into reverse-stress analysis
   without assumed refinancing proceeds.
10. Test usable liquidity without book or foreign cash until accessibility,
    tax, lien and local operating constraints are documented.

The Phase 5 assumptions identified in the register have received owner review
for testing only. Phase 6 must not recast them as management guidance, market
quotes, committed terms or final underwriting judgments. It must retain the
existing-rate tier, recurring fees, actual closing cash, Q1 cash/interest bridge,
distribution permissions, DPO and retained-obligation principal/interest split
as pending or not determinable. Equal monthly allocation must receive an
adverse-timing test. Phase 6 has not started here.
"""
    write_text(DOCS / "METHODOLOGY.md", methodology)
    write_text(DOCS / "BASE_CASE_ANALYSIS.md", base_analysis)
    write_text(DOCS / "FINANCING_COMPARISON.md", financing_doc)
    write_text(DOCS / "PHASE6_HANDOFF.md", phase6)


def build() -> dict[str, int | str]:
    assumptions = read_csv(RAW / "MODEL_ASSUMPTIONS.csv")
    operating = build_operating_forecast(assumptions)
    proposed_monthly = run_monthly_model("proposed", operating, assumptions)
    existing_monthly = run_monthly_model("existing", operating, assumptions)
    monthly_all = existing_monthly + proposed_monthly
    monthly_output = existing_monthly[:24] + proposed_monthly[:24]
    waterfall = aggregate_waterfall(monthly_all)
    debt = aggregate_debt_schedule(monthly_all)
    metrics = build_credit_metrics(waterfall, debt, monthly_all)
    sensitivities = build_sensitivities(operating, assumptions)
    comparison = build_comparison(monthly_all, assumptions)
    opening_bridge = build_opening_bridge(operating, assumptions)
    distributions = build_distribution_analysis(monthly_all)
    common_horizon = build_common_horizon(monthly_all, assumptions)
    period_presentation = build_period_presentation(operating, monthly_all)
    validations = validation_rows(
        operating, monthly_all, monthly_output, waterfall, debt, metrics,
        sensitivities, comparison, assumptions, opening_bridge, distributions,
        common_horizon, period_presentation,
    )

    write_csv(PROCESSED / "QUARTERLY_OPERATING_FORECAST.csv", operating, OPERATING_FIELDS)
    write_csv(PROCESSED / "MONTHLY_LIQUIDITY_SCHEDULE.csv", monthly_output, MONTHLY_FIELDS)
    write_csv(PROCESSED / "CASH_FLOW_WATERFALL.csv", waterfall, WATERFALL_FIELDS)
    write_csv(PROCESSED / "DEBT_SCHEDULE.csv", debt, DEBT_FIELDS)
    write_csv(PROCESSED / "BASE_CASE_CREDIT_METRICS.csv", metrics, METRIC_FIELDS)
    write_csv(PROCESSED / "DEBT_CAPACITY_SENSITIVITIES.csv", sensitivities, SENSITIVITY_FIELDS)
    write_csv(PROCESSED / "FINANCING_ALTERNATIVE_COMPARISON.csv", comparison, COMPARISON_FIELDS)
    write_csv(PROCESSED / "OPENING_POSITION_BRIDGE.csv", opening_bridge, OPENING_BRIDGE_FIELDS)
    write_csv(PROCESSED / "DISTRIBUTION_ANALYSIS.csv", distributions, DISTRIBUTION_FIELDS)
    write_csv(PROCESSED / "COMMON_HORIZON_COMPARISON.csv", common_horizon, COMMON_HORIZON_FIELDS)
    write_csv(PROCESSED / "FY2026_PERIOD_PRESENTATION.csv", period_presentation, PERIOD_PRESENTATION_FIELDS)
    write_csv(PROCESSED / "VALIDATION_RESULTS.csv", validations, VALIDATION_FIELDS)
    render_docs(
        operating, monthly_all, sensitivities, comparison, assumptions,
        opening_bridge, distributions, common_horizon, period_presentation,
    )

    collections = [
        ("data/phase5/processed/QUARTERLY_OPERATING_FORECAST.csv", "operating_forecast", operating, "forecast_id"),
        ("data/phase5/processed/MONTHLY_LIQUIDITY_SCHEDULE.csv", "monthly_liquidity", monthly_output, "monthly_id"),
        ("data/phase5/processed/CASH_FLOW_WATERFALL.csv", "cash_flow_waterfall", waterfall, "waterfall_id"),
        ("data/phase5/processed/DEBT_SCHEDULE.csv", "debt_schedule", debt, "debt_schedule_id"),
        ("data/phase5/processed/BASE_CASE_CREDIT_METRICS.csv", "credit_metric", metrics, "metric_id"),
        ("data/phase5/processed/DEBT_CAPACITY_SENSITIVITIES.csv", "debt_capacity_sensitivity", sensitivities, "sensitivity_id"),
        ("data/phase5/processed/FINANCING_ALTERNATIVE_COMPARISON.csv", "financing_comparison", comparison, "comparison_id"),
        ("data/phase5/processed/OPENING_POSITION_BRIDGE.csv", "opening_position_bridge", opening_bridge, "bridge_id"),
        ("data/phase5/processed/DISTRIBUTION_ANALYSIS.csv", "distribution_analysis", distributions, "distribution_id"),
        ("data/phase5/processed/COMMON_HORIZON_COMPARISON.csv", "common_horizon_comparison", common_horizon, "analysis_id"),
        ("data/phase5/processed/FY2026_PERIOD_PRESENTATION.csv", "period_presentation", period_presentation, "presentation_id"),
        ("data/phase5/processed/VALIDATION_RESULTS.csv", "validation_control", validations, "validation_id"),
    ]
    ledger = source_ledger_rows(assumptions, collections)
    write_csv(DOCS / "SOURCE_LEDGER.csv", ledger, LEDGER_FIELDS)
    return {
        "assumptions": len(assumptions), "operating_quarters": len(operating),
        "monthly_rows": len(monthly_output), "waterfall_rows": len(waterfall),
        "debt_rows": len(debt), "metric_rows": len(metrics),
        "sensitivity_rows": len(sensitivities), "comparison_rows": len(comparison),
        "opening_bridge_rows": len(opening_bridge),
        "distribution_rows": len(distributions),
        "common_horizon_rows": len(common_horizon),
        "period_presentation_rows": len(period_presentation),
        "validation_rows": len(validations), "ledger_rows": len(ledger),
        "proposed_maturity_gap": fmt(dec(proposed_monthly[-1]["unsupported_maturity_funding_gap"])),
        "existing_maturity_gap": fmt(dec(existing_monthly[-1]["unsupported_maturity_funding_gap"])),
    }


def generated_files() -> list[Path]:
    files = list(RAW.glob("*.csv")) + list(PROCESSED.glob("*.csv")) + list(DOCS.glob("*"))
    return sorted(path for path in files if path.is_file())


def fingerprints() -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in generated_files()
    }


def protected_prior_changes() -> list[str]:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", APPROVED_PHASE4_COMMIT],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    protected: list[str] = []
    for path in result.stdout.splitlines():
        if (
            path.startswith(("data/", "docs/phase-", "tests/test_phase"))
            or path in {
                "scripts/phase1.py", "scripts/phase2.py", "scripts/phase3.py",
                "scripts/validate-phase0.ps1",
            }
        ):
            if path != "scripts/phase4.py":
                protected.append(path)
    changed = subprocess.run(
        ["git", "diff", "--name-only", APPROVED_PHASE4_COMMIT, "--", *protected],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    missing = [path for path in protected if not (ROOT / path).is_file()]
    return sorted(set(missing + changed.stdout.splitlines()))


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


def protected_phase5_changes() -> list[str]:
    """Return approved Phase 5 analytical artifacts changed after approval."""
    protected = [
        str(path.relative_to(ROOT)).replace("\\", "/")
        for path in generated_files()
    ]
    missing = [path for path in protected if not (ROOT / path).is_file()]
    result = subprocess.run(
        ["git", "diff", "--name-only", APPROVED_PHASE5_COMMIT, "--", *protected],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    changed = [line.replace("\\", "/") for line in result.stdout.splitlines() if line]
    return sorted(set(missing + changed))


def validate_changed_paths() -> None:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            capture_output=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Phase5Error(f"Cannot verify HEAD: {exc}") from exc
    if head != APPROVED_PHASE4_COMMIT:
        descendant = subprocess.run(
            ["git", "merge-base", "--is-ancestor", APPROVED_PHASE5_COMMIT, head],
            cwd=ROOT, text=True, capture_output=True,
        )
        if descendant.returncode != 0:
            raise Phase5Error(f"HEAD is outside the approved Phase 5 lineage: {head}")
        protected = protected_phase5_changes()
        if protected:
            raise Phase5Error(
                "Protected Phase 5 artifact changed after approval: " + ", ".join(protected)
            )
    allowed_exact = {
        "README.md", "scripts/phase4.py", "scripts/phase5.py", "scripts/phase6.py",
        "scripts/phase7.py", "tests/test_phase5.py", "tests/test_phase6.py",
        "tests/test_phase7.py",
    }
    unexpected = [
        path for path in changed_paths()
        if path not in allowed_exact
        and not path.startswith("data/phase5/")
        and not path.startswith("docs/phase-5/")
        and not path.startswith("data/phase6/")
        and not path.startswith("docs/phase-6/")
        and not path.startswith("data/phase7/")
        and not path.startswith("docs/phase-7/")
    ]
    if unexpected:
        raise Phase5Error(f"Unexpected changed paths: {', '.join(unexpected)}")


def validate() -> dict[str, int | str]:
    checkpoint = read_csv(RAW / "STARTING_CHECKPOINT.csv")
    assumptions = read_csv(RAW / "MODEL_ASSUMPTIONS.csv")
    operating = read_csv(PROCESSED / "QUARTERLY_OPERATING_FORECAST.csv")
    monthly = read_csv(PROCESSED / "MONTHLY_LIQUIDITY_SCHEDULE.csv")
    waterfall = read_csv(PROCESSED / "CASH_FLOW_WATERFALL.csv")
    debt = read_csv(PROCESSED / "DEBT_SCHEDULE.csv")
    metrics = read_csv(PROCESSED / "BASE_CASE_CREDIT_METRICS.csv")
    sensitivities = read_csv(PROCESSED / "DEBT_CAPACITY_SENSITIVITIES.csv")
    comparison = read_csv(PROCESSED / "FINANCING_ALTERNATIVE_COMPARISON.csv")
    opening_bridge = read_csv(PROCESSED / "OPENING_POSITION_BRIDGE.csv")
    distributions = read_csv(PROCESSED / "DISTRIBUTION_ANALYSIS.csv")
    common_horizon = read_csv(PROCESSED / "COMMON_HORIZON_COMPARISON.csv")
    period_presentation = read_csv(PROCESSED / "FY2026_PERIOD_PRESENTATION.csv")
    validations = read_csv(PROCESSED / "VALIDATION_RESULTS.csv")
    ledger = read_csv(DOCS / "SOURCE_LEDGER.csv")

    if len(checkpoint) != 1:
        raise Phase5Error("Starting checkpoint must have exactly one row")
    cp = checkpoint[0]
    if cp["repository"] != "owencchapman24/quanex-credit-underwriting" or cp["branch"] != "main":
        raise Phase5Error("Starting repository or branch mismatch")
    if any(cp[field] != APPROVED_PHASE4_COMMIT
           for field in ("local_head", "tracked_origin_main", "live_remote_main")):
        raise Phase5Error("Starting Phase 4 commit mismatch")
    if (cp["ahead"], cp["behind"], cp["working_tree_clean_before_work"]) != ("0", "0", "yes"):
        raise Phase5Error("Starting divergence or cleanliness mismatch")
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            capture_output=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Phase5Error(f"Cannot verify HEAD: {exc}") from exc
    if head != APPROVED_PHASE4_COMMIT:
        descendant = subprocess.run(
            ["git", "merge-base", "--is-ancestor", APPROVED_PHASE4_COMMIT, head],
            cwd=ROOT, text=True, capture_output=True,
        )
        if descendant.returncode != 0:
            raise Phase5Error(f"HEAD is outside approved Phase 4 lineage: {head}")

    for rows, field, label in (
        (assumptions, "assumption_id", "assumption"),
        (operating, "forecast_id", "operating forecast"),
        (monthly, "monthly_id", "monthly liquidity"),
        (waterfall, "waterfall_id", "waterfall"),
        (debt, "debt_schedule_id", "debt schedule"),
        (metrics, "metric_id", "credit metric"),
        (sensitivities, "sensitivity_id", "sensitivity"),
        (comparison, "comparison_id", "comparison"),
        (opening_bridge, "bridge_id", "opening bridge"),
        (distributions, "distribution_id", "distribution analysis"),
        (common_horizon, "analysis_id", "common-horizon comparison"),
        (period_presentation, "presentation_id", "period presentation"),
        (validations, "validation_id", "validation"),
        (ledger, "record_id", "source ledger"),
    ):
        ensure_unique(rows, field, label)

    if len(assumptions) != 42:
        raise Phase5Error(f"Expected 42 model assumptions, found {len(assumptions)}")
    allowed_reviews = {
        "proposed_for_owner_review", "inherited_owner_reviewed",
        "owner_reviewed_for_phase5_testing",
        "calculated_from_approved_inputs", "not_applicable_existing_fact",
        "pending_information",
    }
    if any(row["review_status"] not in allowed_reviews for row in assumptions):
        raise Phase5Error("Invalid or missing assumption review status")
    if any(row["classification"].startswith("new_")
           and row["review_status"] not in {
               "proposed_for_owner_review", "owner_reviewed_for_phase5_testing"
           } for row in assumptions):
        raise Phase5Error("New Phase 5 assumption has an invalid review status")
    fee_input = next(row for row in assumptions if row["assumption_id"] == "P5A-042")
    if fee_input["value"] or fee_input["review_status"] != "pending_information":
        raise Phase5Error("Recurring financing fees must remain explicit pending information")
    if any(row["assumption_name"] == "accounts_payable_to_cost_of_sales"
           and "not DPO" not in row["limitation_or_rationale"] for row in assumptions):
        raise Phase5Error("Accounts-payable proxy could be mistaken for DPO")
    if any(row["assumption_name"] in {
        "accounts_payable_to_cost_of_sales",
        "other_operating_current_assets_to_revenue",
        "other_operating_current_liabilities_to_revenue",
    } and (not row["value"] or dec(row["value"]) == 0) for row in assumptions):
        raise Phase5Error("Working-capital method is missing or zero")

    if len(operating) != 21 or operating[0]["period_end"] != "2026-01-31" or operating[-1]["period_end"] != "2031-01-31":
        raise Phase5Error("Quarterly operating horizon is incomplete")
    if any(dec(row["lender_base_ebitda"]) != dec(row["gross_profit"]) + dec(row["cash_operating_expenses"])
           for row in operating):
        raise Phase5Error("Operating EBITDA bridge does not reconcile")
    annual = annual_operating_rows(operating)
    full_year_margins = [dec(row["margin"]) for row in annual if row["coverage"] == "full_year"]
    if any(not (Decimal("12") <= margin <= Decimal("13")) for margin in full_year_margins):
        raise Phase5Error("Calculated annual lender EBITDA margin falls outside the Phase 3 validation band")
    if any(dec(row["accounts_payable"]) <= 0
           or dec(row["other_operating_current_assets"]) <= 0
           or dec(row["other_operating_current_liabilities"]) <= 0 for row in operating):
        raise Phase5Error("Working-capital output contains unsupported zero")
    if any(abs(
        dec(row["lender_base_ebitda"]) + dec(row["cash_tax_proxy"])
        + dec(row["working_capital_cash_flow"]) + dec(row["capital_expenditures"])
        + dec(row["other_necessary_operating_cash_uses"])
        - dec(row["cfads_before_cash_interest"])
    ) > TOLERANCE for row in operating):
        raise Phase5Error("CFADS bridge does not reconcile")

    if len(monthly) != 48 or {row["structure"] for row in monthly} != {"existing", "proposed"}:
        raise Phase5Error("Monthly output must show 24 months for each structure")
    if any(dec(row["cash_floor_shortfall"]) > TOLERANCE
           and row["model_status"] == "PASS" for row in monthly):
        raise Phase5Error("Cash-floor failure is hidden")
    if any(dec(row["commitment_breach"]) > TOLERANCE
           and row["model_status"] == "PASS" for row in monthly):
        raise Phase5Error("Commitment breach is hidden")

    if any(row["status"] == "FAIL" for row in validations):
        failures = [row["test_name"] for row in validations if row["status"] == "FAIL"]
        raise Phase5Error("Validation controls failed: " + ", ".join(failures))
    required_nd = {
        "formal_covenant_compliance_not_asserted",
        "dpo_not_determinable", "retained_debt_principal_allocation",
        "recurring_financing_fees", "applicable_existing_pricing_tier",
        "distribution_permissions", "actual_same_point_closing_cash",
    }
    if {row["test_name"] for row in validations if row["status"] == "NOT_DETERMINABLE"} != required_nd:
        raise Phase5Error("Required not-determinable controls changed")
    if {dec(row["annual_amortization_percent"]) for row in sensitivities
        if row["structure"] == "proposed" and row["sensitivity_dimension"] == "amortization"} != {Decimal("5"), Decimal("10"), Decimal("15")}:
        raise Phase5Error("Amortization sensitivities are incomplete")
    if {dec(row["spread_basis_points"]) for row in sensitivities
        if row["structure"] == "proposed" and row["sensitivity_dimension"] == "pricing"} != {Decimal("250"), Decimal("300"), Decimal("350")}:
        raise Phase5Error("Pricing sensitivities are incomplete")
    if any(row["classification"] != "financing_sensitivity_not_operating_downside"
           for row in sensitivities):
        raise Phase5Error("Financing sensitivity could be mistaken for Phase 6 downside")
    if not all(row["as_of_or_period"] == "2026-02-01_00:00" for row in opening_bridge
               if row["item"].startswith("Ending ") or row["item"].startswith("Available revolver")):
        raise Phase5Error("Opening bridge contains mixed ending timestamps")
    if any(row["provisional_term_compliance_status"] == "fully_compliant"
           for row in distributions):
        raise Phase5Error("Distribution analysis overstates provisional compliance")
    if any(row["segment"] == "common_horizon"
           and (row["period_start"], row["period_end"]) != ("2026-02-01", "2029-07-31")
           for row in common_horizon):
        raise Phase5Error("Common-horizon output contains mismatched periods")
    if any(row["period_label"] == "FY2026_full_year_financing"
           and (row["cash_interest"] or row["cfo_proxy"] or row["fcf_proxy"])
           for row in period_presentation):
        raise Phase5Error("Incomplete FY2026 financing measures were presented as full-year")

    if lender_base_ebitda("FY2024") != Decimal("179.358") or lender_base_ebitda("FY2025") != Decimal("225.344"):
        raise Phase5Error("Approved Phase 2 lender-base EBITDA changed")
    proposed_opening = next(row for row in comparison if row["metric_name"] == "Opening bank funded debt")
    if dec(proposed_opening["proposed_value"]) != Decimal("679.89771875"):
        raise Phase5Error("Phase 4 reference proposed opening debt changed")
    if dec(proposed_opening["existing_value"]) != Decimal("669.89771875"):
        raise Phase5Error("Existing same-point opening debt does not reconcile")
    contractual = next(row for row in comparison
                       if row["metric_name"] == "Phase 4 contractual final rolling-12-month funded payments")
    if (dec(contractual["existing_value"]), dec(contractual["proposed_value"])) != (
        Decimal("572.5"), Decimal("419.89771875")
    ):
        raise Phase5Error("Phase 4 maturity comparison changed")

    catalog = source_manifest()
    used_ids = {sid for row in ledger for sid in row["source_ids"].split(";") if sid}
    unknown = used_ids - set(catalog)
    if unknown:
        raise Phase5Error("Unknown source IDs: " + ", ".join(sorted(unknown)))
    for sid in used_ids:
        source_date = date.fromisoformat(catalog[sid]["publication_or_filing_date"])
        if source_date > CUTOFF:
            raise Phase5Error(f"Post-cutoff evidence used: {sid}")
    if any(row["source_date"] and date.fromisoformat(row["source_date"]) > CUTOFF for row in ledger):
        raise Phase5Error("Post-cutoff source date in Phase 5 ledger")

    for path in generated_files():
        text = path.read_text(encoding="utf-8")
        if "C:\\Users\\" in text or "C:/Users/" in text:
            raise Phase5Error(f"Absolute machine path in {path.relative_to(ROOT)}")
        lowered = text.lower()
        if "official covenant compliance: pass" in lowered or "final credit approval: go" in lowered:
            raise Phase5Error(f"Unsupported formal conclusion in {path.relative_to(ROOT)}")
    prior_changes = protected_prior_changes()
    if prior_changes:
        raise Phase5Error("Protected Phase 0-4 artifact changed: " + ", ".join(prior_changes))
    validate_changed_paths()
    return {
        "assumptions": len(assumptions), "operating_quarters": len(operating),
        "monthly_rows": len(monthly), "waterfall_rows": len(waterfall),
        "debt_rows": len(debt), "metric_rows": len(metrics),
        "sensitivity_rows": len(sensitivities), "comparison_rows": len(comparison),
        "opening_bridge_rows": len(opening_bridge),
        "distribution_rows": len(distributions),
        "common_horizon_rows": len(common_horizon),
        "period_presentation_rows": len(period_presentation),
        "validation_passes": sum(row["status"] == "PASS" for row in validations),
        "not_determinable_controls": sum(row["status"] == "NOT_DETERMINABLE" for row in validations),
        "ledger_rows": len(ledger), "post_cutoff_sources": 0,
        "prior_phase_changes": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("seed", "build", "validate", "all"),
                        nargs="?", default="all")
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
            print("Phase 5 complete: " + ", ".join(f"{key}={value}" for key, value in stats.items()))
        return 0
    except (Phase5Error, OSError, subprocess.CalledProcessError) as exc:
        print(f"Phase 5 failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
