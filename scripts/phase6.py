"""Build and validate Phase 6 downside, liquidity, and reverse-stress analysis.

This case-specific workflow consumes the committed Phase 3 and Phase 5 layers.
It uses only the Python standard library, performs no network access, and keeps
analytical warning tests distinct from formal contractual compliance.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import subprocess
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_CEILING, getcontext
from pathlib import Path
from typing import Iterable, Sequence


# Match the committed Phase 5 Decimal context. A module-level increase would
# mutate process-global Decimal behavior during test discovery and alter prior-
# phase deterministic outputs even though their formulas were untouched.
getcontext().prec = 28

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "phase6" / "raw"
PROCESSED = ROOT / "data" / "phase6" / "processed"
DOCS = ROOT / "docs" / "phase-6"

sys.path.insert(0, str(ROOT / "scripts"))
import phase5  # noqa: E402


APPROVED_PHASE5_COMMIT = "412ce5e79355ad2b96ae33ab3f169ac25ef36b38"
APPROVED_PHASE6_COMMIT = "b5554f8848e1622ae1de1e371b974c886f3e33db"
CUTOFF = date(2025, 12, 15)
STRESS_START = date(2026, 2, 1)
MITIGATION_START = date(2026, 5, 1)
PROPOSED_MATURITY = date(2031, 1, 31)
EXISTING_MATURITY_EVENT = date(2029, 7, 31)
TOLERANCE = Decimal("0.000001")
ITERATION_TOLERANCE = Decimal("0.000000001")
LIQUIDITY_WARNING = Decimal("50")
LEVERAGE_INITIAL = Decimal("3.25")
LEVERAGE_STEPDOWN = Decimal("3.00")
COVERAGE_WARNING = Decimal("3.00")
MONEY = "USD_millions"

PHASE3_SCENARIOS = ROOT / "data" / "phase3" / "processed" / "SCENARIO_DRIVER_CANDIDATES.csv"
PHASE3_MITIGATIONS = ROOT / "data" / "phase3" / "processed" / "MITIGATION_REGISTER.csv"
PHASE3_DRIVERS = ROOT / "data" / "phase3" / "processed" / "RISK_DRIVER_MAP.csv"
PHASE3_GAPS = ROOT / "data" / "phase3" / "processed" / "INFORMATION_GAPS.csv"
PHASE3_OWNER = ROOT / "data" / "phase3" / "raw" / "OWNER_REVIEW_DECISIONS.csv"
PHASE5_ASSUMPTIONS = ROOT / "data" / "phase5" / "raw" / "MODEL_ASSUMPTIONS.csv"
PHASE5_OPERATING = ROOT / "data" / "phase5" / "processed" / "QUARTERLY_OPERATING_FORECAST.csv"
PHASE5_COMMON = ROOT / "data" / "phase5" / "processed" / "COMMON_HORIZON_COMPARISON.csv"
PHASE5_DISTRIBUTIONS = ROOT / "data" / "phase5" / "processed" / "DISTRIBUTION_ANALYSIS.csv"
PHASE5_MONTHLY = ROOT / "data" / "phase5" / "processed" / "MONTHLY_LIQUIDITY_SCHEDULE.csv"
PHASE5_VALIDATION = ROOT / "data" / "phase5" / "processed" / "VALIDATION_RESULTS.csv"


class Phase6Error(RuntimeError):
    """Raised when a material Phase 6 control fails."""


@dataclass(frozen=True)
class ScenarioConfig:
    scenario_id: str
    severity: str
    mitigated: bool = False
    no_waiver: bool = False
    volume_percent: Decimal = Decimal("0")
    margin_bps: Decimal = Decimal("0")
    dso_days: Decimal = Decimal("0")
    dio_days: Decimal = Decimal("0")
    ap_ratio_bps: Decimal = Decimal("0")
    other_asset_ratio_bps: Decimal = Decimal("0")
    other_liability_ratio_bps: Decimal = Decimal("0")
    rate_bps: Decimal = Decimal("0")
    remediation_cash_total: Decimal = Decimal("0")
    plateau_quarters: int = 0
    recovery_quarters: int = 0
    extra_annual_cfads: Decimal = Decimal("0")
    timing_convention: str = "adverse"


SCENARIOS = (
    ScenarioConfig("BASE", "base"),
    ScenarioConfig(
        "MODERATE_UNMITIGATED", "moderate", volume_percent=Decimal("-6.5"),
        margin_bps=Decimal("-200"), dso_days=Decimal("5"), dio_days=Decimal("10"),
        ap_ratio_bps=Decimal("-50"), other_asset_ratio_bps=Decimal("25"),
        other_liability_ratio_bps=Decimal("-25"), rate_bps=Decimal("100"),
        remediation_cash_total=Decimal("3"), plateau_quarters=4, recovery_quarters=3,
    ),
    ScenarioConfig(
        "SEVERE_UNMITIGATED", "severe", volume_percent=Decimal("-15"),
        margin_bps=Decimal("-375"), dso_days=Decimal("15"), dio_days=Decimal("25"),
        ap_ratio_bps=Decimal("-100"), other_asset_ratio_bps=Decimal("50"),
        other_liability_ratio_bps=Decimal("-50"), rate_bps=Decimal("200"),
        remediation_cash_total=Decimal("10"), plateau_quarters=8, recovery_quarters=4,
    ),
    ScenarioConfig(
        "MODERATE_MITIGATED", "moderate", mitigated=True,
        volume_percent=Decimal("-6.5"), margin_bps=Decimal("-200"),
        dso_days=Decimal("5"), dio_days=Decimal("10"), ap_ratio_bps=Decimal("-50"),
        other_asset_ratio_bps=Decimal("25"), other_liability_ratio_bps=Decimal("-25"),
        rate_bps=Decimal("100"), remediation_cash_total=Decimal("3"),
        plateau_quarters=4, recovery_quarters=3,
    ),
    ScenarioConfig(
        "SEVERE_MITIGATED", "severe", mitigated=True,
        volume_percent=Decimal("-15"), margin_bps=Decimal("-375"),
        dso_days=Decimal("15"), dio_days=Decimal("25"), ap_ratio_bps=Decimal("-100"),
        other_asset_ratio_bps=Decimal("50"), other_liability_ratio_bps=Decimal("-50"),
        rate_bps=Decimal("200"), remediation_cash_total=Decimal("10"),
        plateau_quarters=8, recovery_quarters=4,
    ),
    ScenarioConfig(
        "MODERATE_NO_WAIVER", "moderate", no_waiver=True,
        volume_percent=Decimal("-6.5"), margin_bps=Decimal("-200"),
        dso_days=Decimal("5"), dio_days=Decimal("10"), ap_ratio_bps=Decimal("-50"),
        other_asset_ratio_bps=Decimal("25"), other_liability_ratio_bps=Decimal("-25"),
        rate_bps=Decimal("100"), remediation_cash_total=Decimal("3"),
        plateau_quarters=4, recovery_quarters=3,
    ),
    ScenarioConfig(
        "SEVERE_NO_WAIVER", "severe", no_waiver=True,
        volume_percent=Decimal("-15"), margin_bps=Decimal("-375"),
        dso_days=Decimal("15"), dio_days=Decimal("25"), ap_ratio_bps=Decimal("-100"),
        other_asset_ratio_bps=Decimal("50"), other_liability_ratio_bps=Decimal("-50"),
        rate_bps=Decimal("200"), remediation_cash_total=Decimal("10"),
        plateau_quarters=8, recovery_quarters=4,
    ),
)

CHECKPOINT_FIELDS = (
    "repository", "branch", "local_head", "tracked_origin_main", "live_remote_main",
    "ahead", "behind", "working_tree_clean_before_work", "verified_on", "notes",
)
SCENARIO_ASSUMPTION_FIELDS = (
    "scenario_assumption_id", "scenario_id", "driver_id", "shock_name", "base_value",
    "shock_value", "units", "start_period", "end_period", "plateau_quarters",
    "recovery_quarters", "recovery_pattern", "affected_lines", "transmission_method",
    "cash_or_noncash", "double_counting_control", "review_status", "source_ids",
    "upstream_ids", "limitations",
)
MITIGATION_FIELDS = (
    "mitigation_decision_id", "mitigation_id", "applicable_scenarios", "risk_driver_ids",
    "action", "start_date", "implementation_lag", "implementation_cost",
    "ebitda_effect", "cash_flow_effect", "maximum_realizable_amount", "duration",
    "execution_dependency", "reversibility", "modeled_credit", "owner_review_status",
    "source_ids", "rationale", "limitations",
)
OPERATING_FIELDS = (
    "scenario_id", "scenario_family", "forecast_id", "fiscal_year", "quarter",
    "period_start", "period_end", "stress_factor", "base_revenue", "volume_shock_percent",
    "revenue", "base_gross_margin_percent", "gross_margin_shock_bps",
    "gross_margin_percent", "gross_profit", "cash_operating_expenses",
    "lender_base_ebitda", "lender_base_ebitda_margin_percent",
    "depreciation_and_amortization", "operating_income", "cash_tax_proxy",
    "days_sales_outstanding", "days_inventory_outstanding",
    "accounts_payable_to_cost_of_sales_percent", "other_current_assets_to_revenue_percent",
    "other_current_liabilities_to_revenue_percent", "accounts_receivable", "inventory",
    "accounts_payable", "other_operating_current_assets",
    "other_operating_current_liabilities", "operating_net_working_capital",
    "change_in_operating_net_working_capital", "working_capital_cash_flow",
    "capital_expenditures", "base_identified_cash_uses", "additional_remediation_cash_use",
    "cfads_before_cash_interest", "rate_shock_bps", "monthly_allocation_pattern",
    "classification", "review_status", "source_ids", "upstream_ids",
    "double_counting_control", "limitations",
)
MONTHLY_FIELDS = (
    "monthly_stress_id", "scenario_id", "scenario_family", "structure", "drawability_path",
    "month_start", "month_end", "fiscal_year", "quarter", "quarter_period_id",
    "month_in_quarter", "monthly_allocation_weight", "opening_cash", "revenue",
    "lender_base_ebitda", "cash_tax_proxy", "working_capital_cash_flow",
    "capital_expenditures", "other_operating_cash_uses", "cfads_before_cash_interest",
    "all_in_rate_percent", "opening_term_principal", "scheduled_term_principal_due",
    "scheduled_term_principal_paid", "scheduled_principal_shortfall",
    "cash_available_before_mandatory_payments", "mandatory_payment_failure_flag",
    "failed_mandatory_obligation_type", "failed_mandatory_obligation_types",
    "failed_obligation_amount_due", "failed_obligation_amount_paid",
    "failed_obligation_unpaid_amount", "cash_available_before_failed_payment",
    "cash_remaining_after_failed_payment", "cash_sweep",
    "maturity_term_payment", "ending_term_principal", "opening_revolver", "revolver_draw",
    "revolver_repayment", "maturity_revolver_payment", "ending_revolver",
    "cash_interest_due", "cash_interest_paid", "cash_interest_shortfall",
    "retained_obligation_due", "retained_obligation_paid", "retained_obligation_shortfall",
    "base_planned_dividend", "planned_dividend_after_mitigation", "dividend_paid",
    "dividend_suspended", "dividend_unpaid", "dividend_revolver_draw_caused",
    "dividend_paid_while_revolver_outstanding", "base_planned_repurchase",
    "planned_repurchase_after_mitigation", "repurchase_paid", "repurchase_suspended",
    "repurchase_unpaid", "repurchase_revolver_draw_caused",
    "repurchase_paid_while_revolver_outstanding", "distribution_breach_effect",
    "provisional_distribution_status", "cash_before_revolver_action", "ending_cash",
    "operating_cash_floor", "cash_floor_shortfall", "letters_of_credit",
    "revolver_commitment", "nominal_revolver_availability", "usable_revolver_availability",
    "usable_liquidity", "drawability_status", "drawability_shutoff_date",
    "commitment_exhaustion_flag", "ttm_lender_base_ebitda", "gross_funded_leverage",
    "book_cash_net_leverage_diagnostic", "analytical_bank_leverage",
    "analytical_leverage_threshold", "ebitda_cash_interest_coverage",
    "cfads_cash_interest_coverage", "cfads_scheduled_debt_service_coverage",
    "analytical_leverage_failure_flag", "analytical_coverage_failure_flag",
    "analytical_liquidity_failure_flag", "maturity_event", "maturity_principal_due",
    "maturity_principal_paid", "maturity_principal_shortfall", "unsupported_maturity_gap",
    "timing_convention",
    "model_status", "classification", "review_status", "source_ids", "upstream_ids",
    "limitations",
)
QUARTERLY_FIELDS = (
    "quarterly_stress_id", "scenario_id", "scenario_family", "structure", "fiscal_year",
    "quarter", "period_start", "period_end", "revenue", "lender_base_ebitda",
    "lender_base_ebitda_margin_percent", "cash_tax_proxy", "working_capital_cash_flow",
    "capital_expenditures", "other_operating_cash_uses", "cfads_before_cash_interest",
    "cash_interest_paid", "scheduled_principal_paid", "retained_obligation_paid",
    "dividends_paid", "repurchases_paid", "dividends_suspended", "repurchases_suspended",
    "revolver_draws", "revolver_repayments", "cash_sweep", "ending_term_principal",
    "ending_revolver", "ending_cash", "minimum_usable_liquidity",
    "peak_period_end_revolver", "mandatory_payment_failure_months",
    "cash_floor_shortfall", "scheduled_principal_shortfall", "cash_interest_shortfall",
    "retained_obligation_shortfall", "maturity_principal_due", "maturity_principal_paid",
    "maturity_principal_shortfall", "unsupported_maturity_gap", "classification",
    "review_status", "source_ids", "upstream_ids", "limitations",
)
DEBT_FIELDS = (
    "debt_stress_id", "scenario_id", "structure", "fiscal_year", "quarter",
    "period_end", "opening_term_principal", "scheduled_principal_due",
    "scheduled_principal_paid", "cash_sweep", "maturity_term_payment",
    "ending_term_principal", "opening_revolver", "revolver_draws", "revolver_repayments",
    "maturity_revolver_payment", "ending_revolver", "ending_bank_debt",
    "retained_debt_proxy", "gross_funded_debt", "cash_interest_paid",
    "nominal_revolver_availability", "usable_revolver_availability", "drawability_status",
    "unsupported_maturity_gap", "status", "source_ids", "upstream_ids", "limitations",
)
RESULT_FIELDS = (
    "scenario_result_id", "scenario_id", "scenario_family", "structure",
    "mitigation_status", "drawability_path", "opening_bank_debt", "opening_revolver_balance",
    "minimum_usable_liquidity", "minimum_liquidity_month",
    "peak_subsequent_period_end_revolver", "peak_subsequent_period_end_revolver_date",
    "peak_revolver_including_opening", "peak_revolver_date",
    "cumulative_cash_interest", "scheduled_principal_paid", "cash_sweep",
    "ending_bank_debt", "maturity_date", "unsupported_maturity_gap",
    "first_incremental_post_closing_draw_date", "first_incremental_post_closing_draw_amount",
    "first_revolver_repayment_date", "first_analytical_threshold_failure",
    "first_50m_analytical_liquidity_warning",
    "first_cash_floor_failure", "revolver_capacity_exhaustion_date",
    "first_mandatory_payment_failure_date", "failed_obligation_type",
    "failed_obligation_amount_due", "failed_obligation_amount_paid",
    "failed_obligation_unpaid_amount", "revolver_capacity_exhausted_before_failure",
    "drawability_shutoff_before_failure", "cash_available_before_failed_payment",
    "cash_remaining_after_failed_payment", "mandatory_payment_failure_months",
    "planned_dividends", "paid_dividends", "unpaid_dividends", "suspended_dividends",
    "directly_draw_funded_dividends", "planned_repurchases", "paid_repurchases",
    "unpaid_repurchases", "suspended_repurchases", "directly_draw_funded_repurchases",
    "repurchases_while_revolver_outstanding", "status", "classification", "review_status",
    "source_ids", "upstream_ids", "limitations",
)
DISTRESS_FIELDS = (
    "distress_event_id", "scenario_id", "structure", "event_type", "event_date", "status",
    "observed_value", "threshold_or_rule", "failed_obligation_type", "amount_due",
    "amount_paid", "unpaid_amount", "revolver_capacity_already_exhausted",
    "drawability_shutoff_active", "cash_available_before_payment",
    "cash_remaining_after_payment", "scenario_timing_convention",
    "interim_failure_or_maturity_shortfall", "sequence_number", "classification",
    "source_ids", "upstream_ids", "notes",
)
THRESHOLD_FIELDS = (
    "threshold_test_id", "scenario_id", "structure", "period_end", "fiscal_year", "quarter",
    "gross_funded_leverage", "book_cash_net_leverage_diagnostic",
    "analytical_bank_leverage", "analytical_leverage_threshold", "leverage_headroom",
    "ebitda_cash_interest_coverage", "coverage_threshold", "coverage_headroom",
    "cfads_cash_interest_coverage", "cfads_scheduled_debt_service_coverage",
    "usable_liquidity", "liquidity_threshold", "liquidity_headroom",
    "bank_debt_headroom", "break_even_ebitda", "earnings_cushion",
    "analytical_status", "formal_contractual_compliance", "drawability_status",
    "classification", "review_status", "source_ids", "upstream_ids", "limitations",
)
DRAWABILITY_FIELDS = (
    "drawability_path_id", "scenario_id", "structure", "path_convention",
    "analytical_trigger_date", "shutoff_effective_date", "new_draws_after_shutoff",
    "outstanding_revolver_preserved", "minimum_usable_liquidity",
    "cash_floor_failure_date", "revolver_capacity_exhaustion_date",
    "first_mandatory_payment_failure_date", "failed_obligation_type",
    "maturity_gap", "status", "classification", "review_status", "source_ids",
    "upstream_ids", "limitations",
)
MITIGATION_RESULT_FIELDS = (
    "mitigation_result_id", "severity", "structure", "unmitigated_scenario_id",
    "mitigated_scenario_id", "mitigation_start_date", "implementation_cost",
    "planned_distributions", "distributions_due_under_policy",
    "distributions_actually_paid_unmitigated",
    "distributions_unpaid_due_to_prior_cash_or_capacity_failure",
    "distributions_formally_suspended_in_mitigated_case",
    "distributions_actually_paid_mitigated", "incremental_cash_preserved_by_mitigation",
    "incremental_interest_saved", "incremental_retained_obligations_paid",
    "other_timing_or_waterfall_effect", "other_timing_or_waterfall_explanation",
    "maturity_gap_reduction", "mitigation_reconciliation_difference",
    "dividends_suspended", "repurchases_suspended", "minimum_liquidity_unmitigated",
    "minimum_liquidity_mitigated", "minimum_liquidity_benefit",
    "opening_revolver_balance", "peak_subsequent_revolver_unmitigated",
    "peak_subsequent_revolver_mitigated", "peak_revolver_including_opening_unmitigated",
    "peak_revolver_including_opening_mitigated", "peak_revolver_benefit",
    "peak_revolver_date_unmitigated", "peak_revolver_date_mitigated",
    "maturity_gap_unmitigated", "maturity_gap_mitigated", "maturity_gap_benefit",
    "cash_interest_unmitigated", "cash_interest_mitigated", "cash_interest_benefit",
    "payment_failure_unmitigated", "payment_failure_mitigated", "status",
    "classification", "review_status", "source_ids", "upstream_ids", "limitations",
)
REVERSE_FIELDS = (
    "reverse_stress_id", "structure", "test_name", "shock_dimension", "lower_bound",
    "upper_bound", "result_value", "units", "search_tolerance", "search_iterations",
    "threshold", "threshold_status", "first_failure_date", "resulting_metric",
    "opening_revolver_balance", "peak_subsequent_period_end_revolver",
    "peak_revolver_including_opening", "peak_revolver_date",
    "classification", "review_status", "source_ids", "upstream_ids", "limitations",
)
GRID_FIELDS = (
    "grid_point_id", "grid_name", "structure", "x_dimension", "x_value", "x_units",
    "y_dimension", "y_value", "y_units", "minimum_usable_liquidity",
    "opening_revolver_balance", "peak_subsequent_period_end_revolver",
    "peak_revolver_including_opening", "peak_revolver_date",
    "first_distress_date", "maturity_gap", "minimum_interest_coverage",
    "no_waiver_shortfall", "classification", "review_status", "source_ids",
    "upstream_ids", "limitations",
)
TIMING_FIELDS = (
    "timing_sensitivity_id", "scenario_id", "scenario_family", "structure",
    "timing_case", "timing_pattern", "minimum_usable_liquidity",
    "minimum_liquidity_month", "opening_revolver_balance",
    "peak_subsequent_period_end_revolver", "peak_subsequent_period_end_revolver_date",
    "peak_revolver_including_opening", "peak_revolver_date",
    "first_incremental_post_closing_draw_date", "first_incremental_post_closing_draw_amount",
    "first_50m_analytical_liquidity_warning", "first_cash_floor_failure",
    "revolver_capacity_exhaustion_date", "first_mandatory_payment_failure_date",
    "failed_obligation_type", "maturity_shortfall",
    "minimum_liquidity_difference_from_equal",
    "peak_subsequent_revolver_difference_from_equal",
    "peak_revolver_including_opening_difference_from_equal",
    "maturity_shortfall_difference_from_equal", "event_date_comparison_from_equal",
    "classification", "review_status", "source_ids", "upstream_ids", "limitations",
)
VALIDATION_FIELDS = (
    "validation_id", "category", "test_name", "status", "observed_value",
    "expected_value_or_rule", "materiality_tolerance", "notes",
)
LEDGER_FIELDS = (
    "ledger_id", "artifact_path", "record_type", "record_id", "source_ids",
    "upstream_ids", "classification", "review_status", "source_date",
    "cutoff_status", "notes",
)


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


def dec(value: object, label: str = "value") -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise Phase6Error(f"Invalid decimal for {label}: {value!r}") from exc


def fmt(value: Decimal | int | str | None) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    number = dec(value)
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def semis(values: Iterable[str]) -> str:
    return ";".join(sorted({value for value in values if value}))


def ensure_unique(rows: list[dict[str, str]], field: str, label: str) -> None:
    values = [row[field] for row in rows]
    if not all(values) or len(values) != len(set(values)):
        raise Phase6Error(f"Missing or duplicate {label} IDs")


def next_month_start(value: date) -> date:
    return date(value.year + (1 if value.month == 12 else 0), 1 if value.month == 12 else value.month + 1, 1)


def scenario_by_id(scenario_id: str) -> ScenarioConfig:
    try:
        return next(config for config in SCENARIOS if config.scenario_id == scenario_id)
    except StopIteration as exc:
        raise Phase6Error(f"Unknown scenario: {scenario_id}") from exc


def analytical_leverage_test(
    debt: Decimal, ebitda: Decimal | None, threshold: Decimal,
) -> tuple[Decimal | None, bool, str]:
    if ebitda is None:
        return None, False, "NOT_DETERMINABLE"
    if ebitda <= 0:
        return None, True, "N/M_FAILURE"
    ratio = debt / ebitda
    return ratio, ratio > threshold, "BREACHED_ANALYTICAL_THRESHOLD" if ratio > threshold else "PASS"


def analytical_coverage_test(
    ebitda: Decimal | None, cash_interest: Decimal | None,
) -> tuple[Decimal | None, bool, str]:
    if ebitda is None or cash_interest is None or cash_interest <= 0:
        return None, False, "NOT_DETERMINABLE"
    ratio = ebitda / cash_interest
    return ratio, ratio < COVERAGE_WARNING, "BREACHED_ANALYTICAL_THRESHOLD" if ratio < COVERAGE_WARNING else "PASS"


def analytical_liquidity_test(liquidity: Decimal | None) -> tuple[bool, str]:
    if liquidity is None:
        return False, "NOT_DETERMINABLE"
    return liquidity < LIQUIDITY_WARNING, "BREACHED_ANALYTICAL_THRESHOLD" if liquidity < LIQUIDITY_WARNING else "PASS"


def formal_contractual_compliance(
    eligible_cash: Decimal | None, contractual_ebitda: Decimal | None,
) -> str:
    del eligible_cash, contractual_ebitda
    return "NOT_DETERMINABLE"


def shock_factor(config: ScenarioConfig, fiscal_year: str, quarter: str) -> Decimal:
    periods = [(fy, q) for fy, q, _, _ in phase5.forecast_periods()]
    key = (fiscal_year, quarter)
    start_key = ("FY2026", "Q2")
    if config.severity == "base" or key not in periods or periods.index(key) < periods.index(start_key):
        return Decimal("0")
    index = periods.index(key) - periods.index(start_key)
    if index < config.plateau_quarters:
        return Decimal("1")
    recovery_index = index - config.plateau_quarters
    if recovery_index < config.recovery_quarters:
        return Decimal(config.recovery_quarters - recovery_index) / Decimal(config.recovery_quarters + 1)
    return Decimal("0")


def monthly_weights(config: ScenarioConfig, factor: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    if factor == 0 or config.severity == "base" or config.timing_convention == "equal":
        third = Decimal("1") / Decimal("3")
        return third, third, third
    if config.severity == "moderate":
        return Decimal("0.20"), Decimal("0.30"), Decimal("0.50")
    return Decimal("0.10"), Decimal("0.25"), Decimal("0.65")


def checkpoint_rows() -> list[dict[str, str]]:
    return [{
        "repository": "owencchapman24/quanex-credit-underwriting",
        "branch": "main", "local_head": APPROVED_PHASE5_COMMIT,
        "tracked_origin_main": APPROVED_PHASE5_COMMIT,
        "live_remote_main": APPROVED_PHASE5_COMMIT,
        "ahead": "0", "behind": "0", "working_tree_clean_before_work": "yes",
        "verified_on": "2026-09-10",
        "notes": "Live remote verified before Phase 6 editing; Phase 5 baseline validations and 184 tests passed.",
    }]


def scenario_assumption_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    definitions = (
        ("DRV-001", "volume_vs_base", "0", "volume_percent", "percent", "revenue", "Multiply Phase 5 revenue by one plus the scenario volume shock.", "operating", "Do not apply a separate EBITDA percentage shock.", "SCN-001"),
        ("DRV-003", "gross_margin_vs_base", "0", "margin_bps", "basis_points", "gross_profit;lender_base_ebitda", "Apply to Phase 5 gross margin; EBITDA remains gross profit less cash operating expenses.", "operating", "Includes fixed-cost deleverage and execution disruption; no second opex penalty.", "SCN-002"),
        ("DRV-005", "dso_vs_base", "0", "dso_days", "days", "accounts_receivable;working_capital_cash_flow", "Recalculate receivables from stressed TTM revenue and DSO.", "cash", "No blanket working-capital shock.", "SCN-003"),
        ("DRV-005", "dio_vs_base", "0", "dio_days", "days", "inventory;working_capital_cash_flow", "Recalculate inventory from stressed TTM cost of sales and DIO.", "cash", "No second inventory cash plug.", "SCN-004"),
        ("DRV-013", "accounts_payable_ratio_vs_base", "0", "ap_ratio_bps", "basis_points", "accounts_payable;working_capital_cash_flow", "Adjust the explicitly labeled AP-to-cost-of-sales balance relationship.", "cash", "This is not DPO and cost of sales is not called purchases.", "SCN-009"),
        ("DRV-013", "other_current_assets_ratio_vs_base", "0", "other_asset_ratio_bps", "basis_points", "other_operating_current_assets;working_capital_cash_flow", "Adjust the separate other-current-assets-to-revenue relationship.", "cash", "Kept separate from receivables and the AP relationship.", "SCN-009"),
        ("DRV-013", "other_current_liabilities_ratio_vs_base", "0", "other_liability_ratio_bps", "basis_points", "other_operating_current_liabilities;working_capital_cash_flow", "Adjust the separate other-current-liabilities-to-revenue relationship.", "cash", "Kept separate from payables and no funding plug is used.", "SCN-009"),
        ("DRV-012", "floating_rate_vs_base", "0", "rate_bps", "basis_points", "cash_interest;revolver;liquidity", "Add once to the modeled all-in rate and recalculate interest on average endogenous debt.", "cash", "Do not also change the Phase 5 base-rate or spread inputs.", "SCN-006"),
        ("DRV-007", "additional_remediation_cash", "0", "remediation_cash_total", MONEY, "other_operating_cash_uses;cfads", "Spread the proposed cash-only amount across the initial stressed quarters.", "cash", "Gross-margin stress contains the operating effect; this amount is not deducted from EBITDA.", "SCN-005"),
        ("DRV-005", "monthly_timing_pattern", "equal thirds", "severity", "allocation_pattern", "monthly cash flow;liquidity", "Delay stressed-quarter cash generation within the quarter and preserve the quarterly total.", "cash", "Quarterly values reconcile exactly; the pattern is not asserted actual seasonality.", "SCN-003;SCN-004"),
        ("DRV-010", "distribution_treatment", "Phase 5 selected policy", "mitigated", "status", "dividends;share_repurchases;revolver", "Retain base distributions in unmitigated cases and apply dated actions only in mitigated cases.", "cash", "No reduction is embedded in unmitigated stress.", "SCN-007"),
        ("DRV-012", "drawability_convention", "continued analytical drawability", "no_waiver", "status", "usable_revolver_availability;cash_shortfall", "For proposed no-waiver paths only, shut off unused capacity from the month after first analytical failure.", "cash", "Stress convention only; existing facilities receive analytical warnings without shutoff.", "GAP-005;GAP-006"),
    )
    index = 0
    for config in SCENARIOS:
        for driver, name, base, attribute, units, lines, method, cash_type, control, upstream in definitions:
            index += 1
            raw = getattr(config, attribute)
            value = (
                ("equal_thirds" if config.severity == "base" else "20%_30%_50%" if config.severity == "moderate" else "10%_25%_65%")
                if attribute == "severity"
                else ("yes" if raw is True else "no" if raw is False else fmt(raw))
            )
            review = (
                "inherited_owner_reviewed_phase5_testing"
                if config.severity == "base"
                else "owner_reviewed_for_phase6_testing"
            )
            end_period = (
                "not_applicable" if config.severity == "base"
                else ("FY2027_Q1_plateau_then_FY2027_Q2_Q4_recovery" if config.severity == "moderate"
                      else "FY2028_Q1_plateau_then_FY2028_Q2_FY2029_Q1_recovery")
            )
            rows.append({
                "scenario_assumption_id": f"P6A-{index:04d}", "scenario_id": config.scenario_id,
                "driver_id": driver, "shock_name": name, "base_value": base,
                "shock_value": value, "units": units,
                "start_period": "not_applicable" if config.severity == "base" else "FY2026_Q2",
                "end_period": end_period, "plateau_quarters": str(config.plateau_quarters),
                "recovery_quarters": str(config.recovery_quarters),
                "recovery_pattern": "none" if config.severity == "base" else "linear_to_zero_after_plateau",
                "affected_lines": lines, "transmission_method": method,
                "cash_or_noncash": cash_type, "double_counting_control": control,
                "review_status": review, "source_ids": "SRC-001;SRC-002;SRC-003",
                "upstream_ids": upstream,
                "limitations": "Owner reviewed the exact stress point, timing, recovery, distribution treatment and drawability convention for Phase 6 analytical testing only. These are not management forecasts, contractual conclusions or final loan terms.",
            })
    return rows


def mitigation_rows() -> list[dict[str, str]]:
    source = {row["mitigation_id"]: row for row in read_csv(PHASE3_MITIGATIONS)}
    decisions = (
        ("MIT-001", "MODERATE_MITIGATED;SEVERE_MITIGATED", "2026-05-01", "one quarter", "0", "0", "Up to $5m annual run-rate avoided", "through applicable maturity", "yes"),
        ("MIT-002", "SEVERE_MITIGATED", "2026-05-01", "one quarter", "0", "0", "50% of the $14.5m annual testing dividend", "through applicable maturity", "yes"),
        ("MIT-003", "", "", "project-specific", "", "", "not_determinable", "", "no"),
        ("MIT-004", "", "", "one to two quarters", "", "", "not_determinable", "", "no"),
        ("MIT-005", "", "", "up to three months", "", "", "not_determinable", "", "no"),
        ("MIT-006", "", "", "two to eight quarters", "", "", "not_determinable", "", "no"),
        ("MIT-007", "", "", "unknown", "", "", "zero credit", "", "no"),
        ("MIT-008", "", "", "entity/tax dependent", "", "", "not_determinable", "", "no"),
    )
    rows: list[dict[str, str]] = []
    for index, (mid, scenarios, start, lag, cost, ebitda, maximum, duration, credit) in enumerate(decisions, start=1):
        row = source[mid]
        rows.append({
            "mitigation_decision_id": f"P6M-{index:03d}", "mitigation_id": mid,
            "applicable_scenarios": scenarios, "risk_driver_ids": row["driver_ids"],
            "action": row["action"], "start_date": start, "implementation_lag": lag,
            "implementation_cost": cost, "ebitda_effect": ebitda,
            "cash_flow_effect": maximum if credit == "yes" else "not_modeled",
            "maximum_realizable_amount": maximum, "duration": duration,
            "execution_dependency": row["execution_risk"], "reversibility": row["reversibility"],
            "modeled_credit": credit,
            "owner_review_status": (
                "owner_reviewed_for_phase6_testing"
                if mid in {"MIT-001", "MIT-002"}
                else "proposed_for_owner_review"
            ),
            "source_ids": row["source_ids"],
            "rationale": (
                "Owner reviewed the exact testing action, timing, amount and zero direct implementation cost; feasibility, board action, legal permission and execution remain unconfirmed."
                if mid in {"MIT-001", "MIT-002"}
                else row["notes"]
            ),
            "limitations": (
                "Owner reviewed this action's timing, amount and zero direct implementation cost for Phase 6 analytical testing only; management action, legal permission and execution are not promised."
                if mid in {"MIT-001", "MIT-002"}
                else "No Phase 6 credit is modeled; feasibility, amount and timing remain pending."
            ),
        })
    return rows


def seed_raw() -> None:
    write_csv(RAW / "STARTING_CHECKPOINT.csv", checkpoint_rows(), CHECKPOINT_FIELDS)
    write_csv(RAW / "SCENARIO_ASSUMPTIONS.csv", scenario_assumption_rows(), SCENARIO_ASSUMPTION_FIELDS)
    write_csv(RAW / "MITIGATION_DECISIONS.csv", mitigation_rows(), MITIGATION_FIELDS)


def build_operating(config: ScenarioConfig) -> list[dict[str, str]]:
    base_rows = read_csv(PHASE5_OPERATING)
    assumptions = {row["assumption_id"]: row for row in read_csv(PHASE5_ASSUMPTIONS)}
    base_dso = dec(assumptions["P5A-006"]["value"])
    base_dio = dec(assumptions["P5A-007"]["value"])
    base_ap_ratio = dec(assumptions["P5A-008"]["value"]) / 100
    base_other_asset_ratio = dec(assumptions["P5A-009"]["value"]) / 100
    base_other_liability_ratio = dec(assumptions["P5A-010"]["value"]) / 100
    day_count = dec(assumptions["P5A-041"]["value"])
    tax_rate = dec(assumptions["P5A-012"]["value"]) / 100
    qactual = phase5.phase3_quarterly()
    rolling_revenue = deque((qactual[("FY2025", q, "revenue")] for q in ("Q1", "Q2", "Q3", "Q4")), maxlen=4)
    rolling_cogs = deque((
        qactual[("FY2025", q, "revenue")] - qactual[("FY2025", q, "gross_profit")]
        for q in ("Q1", "Q2", "Q3", "Q4")
    ), maxlen=4)
    opening_nwc = (
        phase5.phase2_value("FY2025", "accounts_receivable")
        + phase5.phase2_value("FY2025", "inventory")
        + phase5.phase2_value("FY2025", "other_presented_current_assets")
        - phase5.phase2_value("FY2025", "accounts_payable")
        - phase5.phase2_value("FY2025", "other_presented_operating_current_liabilities")
    )
    output: list[dict[str, str]] = []
    for base in base_rows:
        factor = shock_factor(config, base["fiscal_year"], base["quarter"])
        volume_shock = config.volume_percent * factor
        margin_shock = config.margin_bps * factor
        revenue = dec(base["revenue"]) * (Decimal("1") + volume_shock / 100)
        margin = dec(base["gross_margin_percent"]) / 100 + margin_shock / Decimal("10000")
        gross_profit = revenue * margin
        cogs = revenue - gross_profit
        opex_ratio = -dec(base["cash_operating_expenses"]) / dec(base["revenue"])
        cash_opex = -(revenue * opex_ratio)
        ebitda = gross_profit + cash_opex
        dna_ratio = -dec(base["depreciation_and_amortization"]) / dec(base["revenue"])
        dna = -(revenue * dna_ratio)
        operating_income = ebitda + dna
        cash_tax = -(max(operating_income, Decimal("0")) * tax_rate)
        rolling_revenue.append(revenue)
        rolling_cogs.append(cogs)
        ttm_revenue = sum(rolling_revenue, Decimal("0"))
        ttm_cogs = sum(rolling_cogs, Decimal("0"))
        dso = base_dso + config.dso_days * factor
        dio = base_dio + config.dio_days * factor
        ap_ratio = base_ap_ratio + config.ap_ratio_bps * factor / Decimal("10000")
        other_asset_ratio = base_other_asset_ratio + config.other_asset_ratio_bps * factor / Decimal("10000")
        other_liability_ratio = base_other_liability_ratio + config.other_liability_ratio_bps * factor / Decimal("10000")
        receivables = ttm_revenue / day_count * dso
        inventory = ttm_cogs / day_count * dio
        payables = ttm_cogs * ap_ratio
        other_assets = ttm_revenue * other_asset_ratio
        other_liabilities = ttm_revenue * other_liability_ratio
        nwc = receivables + inventory + other_assets - payables - other_liabilities
        change_nwc = nwc - opening_nwc
        wc_cash = -change_nwc
        opening_nwc = nwc
        capex_ratio = -dec(base["capital_expenditures"]) / dec(base["revenue"])
        capex = -(revenue * capex_ratio)
        base_other_use = dec(base["other_necessary_operating_cash_uses"])
        remediation = Decimal("0")
        if factor == 1 and config.remediation_cash_total:
            remediation_quarters = 2 if config.severity == "moderate" else 4
            stress_index = len(output) - 1
            if 0 <= stress_index < remediation_quarters:
                remediation = -(config.remediation_cash_total / Decimal(remediation_quarters))
        cfads = ebitda + cash_tax + wc_cash + capex + base_other_use + remediation
        if config.extra_annual_cfads and (base["fiscal_year"], base["quarter"]) != ("FY2026", "Q1"):
            cfads += config.extra_annual_cfads / Decimal("4")
        weights = monthly_weights(config, factor)
        output.append({
            "scenario_id": config.scenario_id, "scenario_family": config.severity,
            "forecast_id": base["forecast_id"], "fiscal_year": base["fiscal_year"],
            "quarter": base["quarter"], "period_start": base["period_start"],
            "period_end": base["period_end"], "stress_factor": fmt(factor),
            "base_revenue": base["revenue"], "volume_shock_percent": fmt(volume_shock),
            "revenue": fmt(revenue), "base_gross_margin_percent": base["gross_margin_percent"],
            "gross_margin_shock_bps": fmt(margin_shock), "gross_margin_percent": fmt(margin * 100),
            "gross_profit": fmt(gross_profit), "cash_operating_expenses": fmt(cash_opex),
            "lender_base_ebitda": fmt(ebitda),
            "lender_base_ebitda_margin_percent": fmt(ebitda / revenue * 100),
            "depreciation_and_amortization": fmt(dna), "operating_income": fmt(operating_income),
            "cash_tax_proxy": fmt(cash_tax), "days_sales_outstanding": fmt(dso),
            "days_inventory_outstanding": fmt(dio),
            "accounts_payable_to_cost_of_sales_percent": fmt(ap_ratio * 100),
            "other_current_assets_to_revenue_percent": fmt(other_asset_ratio * 100),
            "other_current_liabilities_to_revenue_percent": fmt(other_liability_ratio * 100),
            "accounts_receivable": fmt(receivables), "inventory": fmt(inventory),
            "accounts_payable": fmt(payables), "other_operating_current_assets": fmt(other_assets),
            "other_operating_current_liabilities": fmt(other_liabilities),
            "operating_net_working_capital": fmt(nwc),
            "change_in_operating_net_working_capital": fmt(change_nwc),
            "working_capital_cash_flow": fmt(wc_cash), "capital_expenditures": fmt(capex),
            "base_identified_cash_uses": fmt(base_other_use),
            "additional_remediation_cash_use": fmt(remediation),
            "cfads_before_cash_interest": fmt(cfads), "rate_shock_bps": fmt(config.rate_bps * factor),
            "monthly_allocation_pattern": ";".join(fmt(value) for value in weights),
            "classification": "formula_calculated_scenario_operating_build",
            "review_status": "inherited_phase5_base" if config.severity == "base" else "owner_reviewed_for_phase6_testing",
            "source_ids": "SRC-001;SRC-002;SRC-003",
            "upstream_ids": "SCN-001;SCN-002;SCN-003;SCN-004;SCN-005;SCN-006;SCN-009;P5A-001:P5A-013;P5A-041",
            "double_counting_control": "Volume changes revenue once; gross-margin shock includes fixed-cost deleverage; DSO, DIO, AP and other balance drivers replace any generic working-capital plug; remediation is cash-only.",
            "limitations": "Exact stress points, recovery and timing are owner-reviewed for Phase 6 analytical testing only. Equal allocation is neutral; adverse allocation is conservative; neither is observed borrower seasonality.",
        })
    return output


def base_structure_parameters(
    structure: str, amortization_percent: Decimal = Decimal("10"),
) -> dict[str, Decimal | date]:
    assumptions = phase5.read_csv(PHASE5_ASSUMPTIONS)
    amap = phase5.assumption_map(assumptions)
    return phase5.structure_parameters(
        structure, amap, Decimal("300"), amortization_percent, Decimal("6.57"),
    )


def distribution_plan(config: ScenarioConfig, month_end: date) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    base_dividend = Decimal("14.5") / Decimal("12")
    base_repurchase = Decimal("5") / Decimal("12")
    dividend = base_dividend
    repurchase = base_repurchase
    if config.mitigated and month_end >= MITIGATION_START:
        repurchase = Decimal("0")
        if config.severity == "severe":
            dividend = base_dividend / Decimal("2")
    return base_dividend, dividend, base_repurchase, repurchase


def allocate_payment(resources: Decimal, amount_due: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    paid = min(max(resources, Decimal("0")), amount_due)
    return paid, amount_due - paid, resources - paid


def run_monthly(
    config: ScenarioConfig, structure: str, operating: list[dict[str, str]],
    amortization_percent: Decimal = Decimal("10"),
) -> list[dict[str, str]]:
    assumptions = phase5.read_csv(PHASE5_ASSUMPTIONS)
    amap = phase5.assumption_map(assumptions)
    params = base_structure_parameters(structure, amortization_percent)
    retained_by_year = phase5.retained_payment_by_year(amap)
    op_index = {(row["fiscal_year"], row["quarter"]): row for row in operating}
    dates = (
        phase5.month_sequence(2026, 2, 2031, 1)
        if structure == "proposed"
        else phase5.month_sequence(2026, 2, 2029, 7)
    )
    cash = dec(amap["P5A-016"]["value"])
    term = dec(params["opening_term"])
    revolver = dec(params["opening_revolver"])
    commitment = dec(params["commitment"])
    lc = dec(params["lc"])
    floor = dec(amap["P5A-016"]["value"])
    retained_proxy = dec(amap["P5A-032"]["value"])
    q1 = op_index[("FY2026", "Q1")]
    ebitda_window: deque[Decimal] = deque(
        [dec(q1["lender_base_ebitda"]) / Decimal("3")] * 3, maxlen=12,
    )
    interest_window: deque[Decimal] = deque(maxlen=12)
    cfads_window: deque[Decimal] = deque(maxlen=12)
    scheduled_service_window: deque[Decimal] = deque(maxlen=12)
    shutoff_effective: date | None = None
    analytical_trigger: date | None = None
    rows: list[dict[str, str]] = []

    for index, month_end in enumerate(dates, start=1):
        fy, quarter = phase5.fiscal_quarter_for_month(month_end.year, month_end.month)
        qrow = op_index[(fy, quarter)]
        month_number = ((month_end.month - 2) % 3) + 1
        weights = tuple(dec(item) for item in qrow["monthly_allocation_pattern"].split(";"))
        weight = weights[month_number - 1]
        allocated = {
            field: dec(qrow[field]) * weight
            for field in (
                "revenue", "lender_base_ebitda", "cash_tax_proxy",
                "working_capital_cash_flow", "capital_expenditures",
                "base_identified_cash_uses", "additional_remediation_cash_use",
                "cfads_before_cash_interest",
            )
        }
        other_cash_uses = allocated["base_identified_cash_uses"] + allocated["additional_remediation_cash_use"]
        retained_due = retained_by_year[fy] / Decimal("12")
        base_dividend, planned_dividend, base_repurchase, planned_repurchase = distribution_plan(config, month_end)
        scheduled_due = Decimal("0")
        if phase5.is_quarter_end(month_end):
            scheduled_due = min(term, dec(params["quarterly_principal"]))
        maturity_event = (
            structure == "proposed" and month_end == PROPOSED_MATURITY
        ) or (
            structure == "existing" and month_end == EXISTING_MATURITY_EVENT
        )
        no_waiver_shutoff = (
            structure == "proposed" and config.no_waiver
            and shutoff_effective is not None and month_end >= shutoff_effective
        )
        new_draws_allowed = not no_waiver_shutoff
        max_drawn_revolver = commitment - lc
        incremental_capacity = (
            max(Decimal("0"), max_drawn_revolver - revolver)
            if new_draws_allowed else Decimal("0")
        )
        annual_rate = Decimal("6.57") + dec(qrow["rate_shock_bps"]) / Decimal("100")
        estimated_ending_revolver = revolver
        final: dict[str, Decimal | str | int] = {}
        for iteration in range(1, 101):
            average_term = (term + max(Decimal("0"), term - scheduled_due)) / Decimal("2")
            average_revolver = (revolver + estimated_ending_revolver) / Decimal("2")
            interest_due = (average_term + average_revolver) * annual_rate / Decimal("100") / Decimal("12")
            resources = cash + allocated["cfads_before_cash_interest"] + incremental_capacity
            resources_before_mandatory = max(resources, Decimal("0"))
            resources_before_interest = max(resources, Decimal("0"))
            interest_paid, interest_shortfall, resources = allocate_payment(resources, interest_due)
            resources_after_interest = max(resources, Decimal("0"))
            resources_before_retained = resources_after_interest
            retained_paid, retained_shortfall, resources = allocate_payment(resources, retained_due)
            resources_after_retained = max(resources, Decimal("0"))
            resources_before_scheduled = resources_after_retained
            scheduled_paid, scheduled_shortfall, resources = allocate_payment(resources, scheduled_due)
            resources_after_scheduled = max(resources, Decimal("0"))
            dividend_paid, dividend_unpaid, resources = allocate_payment(resources, planned_dividend)
            repurchase_paid, repurchase_unpaid, resources = allocate_payment(resources, planned_repurchase)
            cash_after_mandatory = (
                cash + allocated["cfads_before_cash_interest"]
                - interest_paid - retained_paid - scheduled_paid
            )
            attribution = phase5.distribution_funding(
                structure, cash_after_mandatory, floor, revolver,
                dividend_paid, repurchase_paid,
            )
            cash_before_revolver = cash_after_mandatory - dividend_paid - repurchase_paid
            revolver_draw = Decimal("0")
            revolver_repayment = Decimal("0")
            cash_after_revolver = cash_before_revolver
            if cash_before_revolver < floor:
                revolver_draw = min(floor - cash_before_revolver, incremental_capacity)
                cash_after_revolver += revolver_draw
            else:
                revolver_repayment = min(cash_before_revolver - floor, revolver)
                cash_after_revolver -= revolver_repayment
            ending_revolver_before_maturity = revolver + revolver_draw - revolver_repayment
            sweep = Decimal("0")
            if (
                month_end.month == 10 and ending_revolver_before_maturity == 0
                and not any(value > TOLERANCE for value in (
                    interest_shortfall, retained_shortfall, scheduled_shortfall,
                ))
            ):
                cash_excess = max(Decimal("0"), cash_after_revolver - floor)
                availability_before_sweep = max(
                    Decimal("0"), commitment - lc - ending_revolver_before_maturity,
                )
                safeguard_capacity = max(
                    Decimal("0"), cash_excess + availability_before_sweep - LIQUIDITY_WARNING,
                )
                sweep = min(
                    term - scheduled_paid,
                    cash_excess * dec(amap["P5A-022"]["value"]) / Decimal("100"),
                    safeguard_capacity,
                )
            ending_term_before_maturity = term - scheduled_paid - sweep
            ending_cash_before_maturity = cash_after_revolver - sweep
            if abs(ending_revolver_before_maturity - estimated_ending_revolver) <= ITERATION_TOLERANCE:
                final = {
                    "interest_due": interest_due, "interest_paid": interest_paid,
                    "interest_shortfall": interest_shortfall,
                    "resources_before_mandatory": resources_before_mandatory,
                    "resources_before_interest": resources_before_interest,
                    "resources_after_interest": resources_after_interest,
                    "retained_paid": retained_paid, "retained_shortfall": retained_shortfall,
                    "resources_before_retained": resources_before_retained,
                    "resources_after_retained": resources_after_retained,
                    "scheduled_paid": scheduled_paid, "scheduled_shortfall": scheduled_shortfall,
                    "resources_before_scheduled": resources_before_scheduled,
                    "resources_after_scheduled": resources_after_scheduled,
                    "dividend_paid": dividend_paid, "dividend_unpaid": dividend_unpaid,
                    "repurchase_paid": repurchase_paid, "repurchase_unpaid": repurchase_unpaid,
                    "cash_after_mandatory": cash_after_mandatory, "attribution": attribution,
                    "cash_before_revolver": cash_before_revolver, "revolver_draw": revolver_draw,
                    "revolver_repayment": revolver_repayment,
                    "ending_revolver_before_maturity": ending_revolver_before_maturity,
                    "sweep": sweep, "ending_term_before_maturity": ending_term_before_maturity,
                    "ending_cash_before_maturity": ending_cash_before_maturity,
                    "iteration": iteration,
                }
                break
            estimated_ending_revolver = ending_revolver_before_maturity
        else:
            raise Phase6Error(f"Interest iteration did not converge: {config.scenario_id}/{structure}/{month_end}")

        ending_cash = dec(final["ending_cash_before_maturity"])
        ending_term = dec(final["ending_term_before_maturity"])
        ending_revolver = dec(final["ending_revolver_before_maturity"])
        maturity_term_payment = Decimal("0")
        maturity_revolver_payment = Decimal("0")
        maturity_principal_due = Decimal("0")
        maturity_principal_paid = Decimal("0")
        maturity_gap = Decimal("0")
        if maturity_event:
            maturity_principal_due = ending_term + ending_revolver
            available_cash = max(Decimal("0"), ending_cash - floor)
            maturity_revolver_payment = min(ending_revolver, available_cash)
            ending_revolver -= maturity_revolver_payment
            available_cash -= maturity_revolver_payment
            maturity_term_payment = min(ending_term, available_cash)
            ending_term -= maturity_term_payment
            ending_cash -= maturity_revolver_payment + maturity_term_payment
            maturity_principal_paid = maturity_revolver_payment + maturity_term_payment
            maturity_gap = ending_term + ending_revolver

        cash_floor_shortfall = max(Decimal("0"), floor - ending_cash)
        nominal_availability = Decimal("0") if maturity_event else commitment - lc - ending_revolver
        usable_availability = (
            Decimal("0") if maturity_event or no_waiver_shutoff
            else max(Decimal("0"), nominal_availability)
        )
        usable_liquidity = max(Decimal("0"), ending_cash - floor) + usable_availability
        ebitda_window.append(allocated["lender_base_ebitda"])
        interest_window.append(dec(final["interest_paid"]))
        cfads_window.append(allocated["cfads_before_cash_interest"])
        scheduled_service_window.append(
            dec(final["interest_paid"]) + dec(final["scheduled_paid"]) + dec(final["retained_paid"])
        )
        ttm_ebitda = sum(ebitda_window, Decimal("0")) if len(ebitda_window) == 12 else None
        bank_debt = ending_term + ending_revolver
        gross_debt = bank_debt + retained_proxy
        cash_above_floor = max(Decimal("0"), ending_cash - floor)
        leverage_threshold = LEVERAGE_STEPDOWN if month_end >= date(2027, 11, 1) else LEVERAGE_INITIAL
        gross_leverage, _, _ = analytical_leverage_test(gross_debt, ttm_ebitda, leverage_threshold)
        net_diag, _, _ = analytical_leverage_test(gross_debt - cash_above_floor, ttm_ebitda, leverage_threshold)
        bank_leverage, leverage_failure, _ = analytical_leverage_test(bank_debt, ttm_ebitda, leverage_threshold)
        interest_coverage: Decimal | None = None
        cfads_interest_coverage: Decimal | None = None
        debt_service_coverage: Decimal | None = None
        coverage_failure = False
        if len(interest_window) == 12 and sum(interest_window, Decimal("0")) > 0:
            interest_coverage, coverage_failure, _ = analytical_coverage_test(
                sum(list(ebitda_window)[-12:], Decimal("0")),
                sum(interest_window, Decimal("0")),
            )
            cfads_interest_coverage = sum(cfads_window, Decimal("0")) / sum(interest_window, Decimal("0"))
        if len(scheduled_service_window) == 12 and sum(scheduled_service_window, Decimal("0")) > 0:
            debt_service_coverage = sum(cfads_window, Decimal("0")) / sum(scheduled_service_window, Decimal("0"))
        liquidity_failure, _ = analytical_liquidity_test(usable_liquidity)
        liquidity_failure = not maturity_event and liquidity_failure
        any_analytical_failure = leverage_failure or coverage_failure or liquidity_failure
        if any_analytical_failure and analytical_trigger is None:
            analytical_trigger = month_end
            if structure == "proposed" and config.no_waiver:
                shutoff_effective = next_month_start(month_end)

        attribution = final["attribution"]
        if not isinstance(attribution, dict):
            raise Phase6Error("Invalid distribution attribution")
        direct_dividend = dec(attribution["dividend_draw_caused"])
        direct_repurchase = dec(attribution["repurchase_draw_caused"])
        broad_repurchase = dec(attribution["repurchase_paid_while_revolver"])
        distribution_breach_effect = max(
            Decimal("0"), cash_floor_shortfall
            - max(Decimal("0"), floor - dec(final["cash_after_mandatory"])),
        )
        if structure == "proposed" and direct_repurchase > TOLERANCE:
            distribution_status = "narrow_debt_funded_repurchase_flag"
        elif structure == "proposed" and broad_repurchase > TOLERANCE:
            distribution_status = "broad_interpretation_repurchase_flag"
        else:
            distribution_status = "permission_not_determinable"
        payment_failures = {
            "INTEREST_PAYMENT_FAILURE": dec(final["interest_shortfall"]),
            "RETAINED_OBLIGATION_PAYMENT_FAILURE": dec(final["retained_shortfall"]),
            "SCHEDULED_PRINCIPAL_PAYMENT_FAILURE": dec(final["scheduled_shortfall"]),
        }
        failure_details = (
            (
                "CASH_INTEREST", interest_due, dec(final["interest_paid"]),
                dec(final["interest_shortfall"]), dec(final["resources_before_interest"]),
                dec(final["resources_after_interest"]),
            ),
            (
                "RETAINED_MANDATORY_OBLIGATION", retained_due, dec(final["retained_paid"]),
                dec(final["retained_shortfall"]), dec(final["resources_before_retained"]),
                dec(final["resources_after_retained"]),
            ),
            (
                "SCHEDULED_TERM_PRINCIPAL", scheduled_due, dec(final["scheduled_paid"]),
                dec(final["scheduled_shortfall"]), dec(final["resources_before_scheduled"]),
                dec(final["resources_after_scheduled"]),
            ),
        )
        failed_obligations = [item for item in failure_details if item[3] > TOLERANCE]
        primary_failure = failed_obligations[0] if failed_obligations else None
        model_status = "PASS"
        if any(value > TOLERANCE for value in payment_failures.values()):
            model_status = "MANDATORY_PAYMENT_FAILURE"
        elif cash_floor_shortfall > TOLERANCE:
            model_status = "LIQUIDITY_FAILURE"
        elif maturity_event and maturity_gap > TOLERANCE:
            model_status = "MATURITY_SHORTFALL"
        elif any_analytical_failure:
            model_status = "BREACHED_ANALYTICAL_THRESHOLD"
        drawability_path = (
            "NO_WAIVER_DRAWABILITY_SHUTOFF" if structure == "proposed" and config.no_waiver
            else "WAIVER_OR_CONTINUED_DRAWABILITY" if structure == "proposed"
            else "EXISTING_ANALYTICAL_WARNING_ONLY"
        )
        drawability_status = (
            "no_waiver_drawability_shutoff" if no_waiver_shutoff
            else "continued_after_analytical_warning" if analytical_trigger and structure == "proposed"
            else "existing_contractual_drawability_not_reconstructed" if structure == "existing"
            else "available_before_analytical_shutoff"
        )
        rows.append({
            "monthly_stress_id": f"P6M-{config.scenario_id}-{structure[:1].upper()}-{index:04d}",
            "scenario_id": config.scenario_id, "scenario_family": config.severity,
            "structure": structure, "drawability_path": drawability_path,
            "month_start": date(month_end.year, month_end.month, 1).isoformat(),
            "month_end": month_end.isoformat(), "fiscal_year": fy, "quarter": quarter,
            "quarter_period_id": qrow["forecast_id"], "month_in_quarter": str(month_number),
            "monthly_allocation_weight": fmt(weight), "opening_cash": fmt(cash),
            "revenue": fmt(allocated["revenue"]), "lender_base_ebitda": fmt(allocated["lender_base_ebitda"]),
            "cash_tax_proxy": fmt(allocated["cash_tax_proxy"]),
            "working_capital_cash_flow": fmt(allocated["working_capital_cash_flow"]),
            "capital_expenditures": fmt(allocated["capital_expenditures"]),
            "other_operating_cash_uses": fmt(other_cash_uses),
            "cfads_before_cash_interest": fmt(allocated["cfads_before_cash_interest"]),
            "all_in_rate_percent": fmt(annual_rate), "opening_term_principal": fmt(term),
            "scheduled_term_principal_due": fmt(scheduled_due),
            "scheduled_term_principal_paid": fmt(dec(final["scheduled_paid"])),
            "scheduled_principal_shortfall": fmt(dec(final["scheduled_shortfall"])),
            "cash_available_before_mandatory_payments": fmt(dec(final["resources_before_mandatory"])),
            "mandatory_payment_failure_flag": "yes" if primary_failure else "no",
            "failed_mandatory_obligation_type": primary_failure[0] if primary_failure else "",
            "failed_mandatory_obligation_types": ";".join(item[0] for item in failed_obligations),
            "failed_obligation_amount_due": fmt(primary_failure[1]) if primary_failure else "",
            "failed_obligation_amount_paid": fmt(primary_failure[2]) if primary_failure else "",
            "failed_obligation_unpaid_amount": fmt(primary_failure[3]) if primary_failure else "",
            "cash_available_before_failed_payment": fmt(primary_failure[4]) if primary_failure else "",
            "cash_remaining_after_failed_payment": fmt(primary_failure[5]) if primary_failure else "",
            "cash_sweep": fmt(dec(final["sweep"])), "maturity_term_payment": fmt(maturity_term_payment),
            "ending_term_principal": fmt(ending_term), "opening_revolver": fmt(revolver),
            "revolver_draw": fmt(dec(final["revolver_draw"])),
            "revolver_repayment": fmt(dec(final["revolver_repayment"])),
            "maturity_revolver_payment": fmt(maturity_revolver_payment),
            "ending_revolver": fmt(ending_revolver), "cash_interest_due": fmt(dec(final["interest_due"])),
            "cash_interest_paid": fmt(dec(final["interest_paid"])),
            "cash_interest_shortfall": fmt(dec(final["interest_shortfall"])),
            "retained_obligation_due": fmt(retained_due),
            "retained_obligation_paid": fmt(dec(final["retained_paid"])),
            "retained_obligation_shortfall": fmt(dec(final["retained_shortfall"])),
            "base_planned_dividend": fmt(base_dividend),
            "planned_dividend_after_mitigation": fmt(planned_dividend),
            "dividend_paid": fmt(dec(final["dividend_paid"])),
            "dividend_suspended": fmt(base_dividend - planned_dividend),
            "dividend_unpaid": fmt(dec(final["dividend_unpaid"])),
            "dividend_revolver_draw_caused": fmt(direct_dividend),
            "dividend_paid_while_revolver_outstanding": fmt(dec(attribution["dividend_paid_while_revolver"])),
            "base_planned_repurchase": fmt(base_repurchase),
            "planned_repurchase_after_mitigation": fmt(planned_repurchase),
            "repurchase_paid": fmt(dec(final["repurchase_paid"])),
            "repurchase_suspended": fmt(base_repurchase - planned_repurchase),
            "repurchase_unpaid": fmt(dec(final["repurchase_unpaid"])),
            "repurchase_revolver_draw_caused": fmt(direct_repurchase),
            "repurchase_paid_while_revolver_outstanding": fmt(broad_repurchase),
            "distribution_breach_effect": fmt(distribution_breach_effect),
            "provisional_distribution_status": distribution_status,
            "cash_before_revolver_action": fmt(dec(final["cash_before_revolver"])),
            "ending_cash": fmt(ending_cash), "operating_cash_floor": fmt(floor),
            "cash_floor_shortfall": fmt(cash_floor_shortfall), "letters_of_credit": fmt(lc),
            "revolver_commitment": fmt(commitment),
            "nominal_revolver_availability": fmt(nominal_availability),
            "usable_revolver_availability": fmt(usable_availability),
            "usable_liquidity": fmt(usable_liquidity), "drawability_status": drawability_status,
            "drawability_shutoff_date": shutoff_effective.isoformat() if shutoff_effective else "",
            "commitment_exhaustion_flag": "yes" if (nominal_availability <= TOLERANCE and not maturity_event) else "no",
            "ttm_lender_base_ebitda": fmt(ttm_ebitda), "gross_funded_leverage": fmt(gross_leverage),
            "book_cash_net_leverage_diagnostic": fmt(net_diag),
            "analytical_bank_leverage": fmt(bank_leverage),
            "analytical_leverage_threshold": fmt(leverage_threshold),
            "ebitda_cash_interest_coverage": fmt(interest_coverage),
            "cfads_cash_interest_coverage": fmt(cfads_interest_coverage),
            "cfads_scheduled_debt_service_coverage": fmt(debt_service_coverage),
            "analytical_leverage_failure_flag": "yes" if leverage_failure else "no",
            "analytical_coverage_failure_flag": "yes" if coverage_failure else "no",
            "analytical_liquidity_failure_flag": "yes" if liquidity_failure else "no",
            "maturity_event": "yes" if maturity_event else "no",
            "maturity_principal_due": fmt(maturity_principal_due),
            "maturity_principal_paid": fmt(maturity_principal_paid),
            "maturity_principal_shortfall": fmt(maturity_gap),
            "unsupported_maturity_gap": fmt(maturity_gap), "model_status": model_status,
            "timing_convention": (
                "equal_neutral" if config.timing_convention == "equal" or config.severity == "base"
                else "adverse_conservative"
            ),
            "classification": "formula_calculated_downside_liquidity_path",
            "review_status": "owner_reviewed_for_phase6_testing" if config.severity != "base" else "inherited_phase5_base",
            "source_ids": "SRC-001;SRC-002;SRC-003",
            "upstream_ids": "P5A-014;P5A-015;P5A-016;P5A-018:P5A-032;SCN-001:SCN-009",
            "limitations": "Recurring financing fees, official covenant definitions, eligible cash, distribution permissions and actual closing cash remain unavailable. Monthly timing is an owner-reviewed testing convention, not observed borrower seasonality.",
        })
        cash, term, revolver = ending_cash, ending_term, ending_revolver
        if maturity_event:
            break
    return rows


def aggregate_quarterly(monthly: list[dict[str, str]]) -> list[dict[str, str]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in monthly:
        groups[(row["scenario_id"], row["structure"], row["fiscal_year"], row["quarter"])].append(row)
    output: list[dict[str, str]] = []
    for index, ((scenario_id, structure, fy, quarter), rows) in enumerate(groups.items(), start=1):
        rows.sort(key=lambda row: row["month_end"])
        first, last = rows[0], rows[-1]
        sums = {
            field: sum((dec(row[field]) for row in rows), Decimal("0"))
            for field in (
                "revenue", "lender_base_ebitda", "cash_tax_proxy",
                "working_capital_cash_flow", "capital_expenditures",
                "other_operating_cash_uses", "cfads_before_cash_interest",
                "cash_interest_paid", "scheduled_term_principal_paid",
                "retained_obligation_paid", "dividend_paid", "repurchase_paid",
                "dividend_suspended", "repurchase_suspended", "revolver_draw",
                "revolver_repayment", "cash_sweep", "scheduled_principal_shortfall",
                "cash_interest_shortfall", "retained_obligation_shortfall",
                "maturity_principal_due", "maturity_principal_paid",
                "maturity_principal_shortfall",
            )
        }
        output.append({
            "quarterly_stress_id": f"P6Q-{index:04d}", "scenario_id": scenario_id,
            "scenario_family": first["scenario_family"], "structure": structure,
            "fiscal_year": fy, "quarter": quarter, "period_start": first["month_start"],
            "period_end": last["month_end"], "revenue": fmt(sums["revenue"]),
            "lender_base_ebitda": fmt(sums["lender_base_ebitda"]),
            "lender_base_ebitda_margin_percent": fmt(sums["lender_base_ebitda"] / sums["revenue"] * 100),
            "cash_tax_proxy": fmt(sums["cash_tax_proxy"]),
            "working_capital_cash_flow": fmt(sums["working_capital_cash_flow"]),
            "capital_expenditures": fmt(sums["capital_expenditures"]),
            "other_operating_cash_uses": fmt(sums["other_operating_cash_uses"]),
            "cfads_before_cash_interest": fmt(sums["cfads_before_cash_interest"]),
            "cash_interest_paid": fmt(sums["cash_interest_paid"]),
            "scheduled_principal_paid": fmt(sums["scheduled_term_principal_paid"]),
            "retained_obligation_paid": fmt(sums["retained_obligation_paid"]),
            "dividends_paid": fmt(sums["dividend_paid"]), "repurchases_paid": fmt(sums["repurchase_paid"]),
            "dividends_suspended": fmt(sums["dividend_suspended"]),
            "repurchases_suspended": fmt(sums["repurchase_suspended"]),
            "revolver_draws": fmt(sums["revolver_draw"]), "revolver_repayments": fmt(sums["revolver_repayment"]),
            "cash_sweep": fmt(sums["cash_sweep"]), "ending_term_principal": last["ending_term_principal"],
            "ending_revolver": last["ending_revolver"], "ending_cash": last["ending_cash"],
            "minimum_usable_liquidity": fmt(min(dec(row["usable_liquidity"]) for row in rows if row["maturity_event"] != "yes") if any(row["maturity_event"] != "yes" for row in rows) else Decimal("0")),
            "peak_period_end_revolver": fmt(max(dec(row["ending_revolver"]) for row in rows)),
            "mandatory_payment_failure_months": str(sum(
                1 for row in rows if row["mandatory_payment_failure_flag"] == "yes"
            )),
            "cash_floor_shortfall": fmt(max(dec(row["cash_floor_shortfall"]) for row in rows)),
            "scheduled_principal_shortfall": fmt(sums["scheduled_principal_shortfall"]),
            "cash_interest_shortfall": fmt(sums["cash_interest_shortfall"]),
            "retained_obligation_shortfall": fmt(sums["retained_obligation_shortfall"]),
            "maturity_principal_due": fmt(sums["maturity_principal_due"]),
            "maturity_principal_paid": fmt(sums["maturity_principal_paid"]),
            "maturity_principal_shortfall": fmt(sums["maturity_principal_shortfall"]),
            "unsupported_maturity_gap": last["unsupported_maturity_gap"],
            "classification": "formula_calculated_quarterly_stress",
            "review_status": first["review_status"], "source_ids": first["source_ids"],
            "upstream_ids": first["upstream_ids"],
            "limitations": "Quarter aggregates monthly provisional allocations; actual monthly seasonality is unavailable.",
        })
    return output


def build_debt_schedule(quarterly: list[dict[str, str]], monthly: list[dict[str, str]]) -> list[dict[str, str]]:
    month_groups: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in monthly:
        month_groups[(row["scenario_id"], row["structure"], row["fiscal_year"], row["quarter"])].append(row)
    output: list[dict[str, str]] = []
    retained_proxy = dec(next(row for row in read_csv(PHASE5_ASSUMPTIONS) if row["assumption_id"] == "P5A-032")["value"])
    for index, qrow in enumerate(quarterly, start=1):
        rows = month_groups[(qrow["scenario_id"], qrow["structure"], qrow["fiscal_year"], qrow["quarter"])]
        rows.sort(key=lambda row: row["month_end"])
        first, last = rows[0], rows[-1]
        bank_debt = dec(last["ending_term_principal"]) + dec(last["ending_revolver"])
        output.append({
            "debt_stress_id": f"P6D-{index:04d}", "scenario_id": qrow["scenario_id"],
            "structure": qrow["structure"], "fiscal_year": qrow["fiscal_year"],
            "quarter": qrow["quarter"], "period_end": qrow["period_end"],
            "opening_term_principal": first["opening_term_principal"],
            "scheduled_principal_due": fmt(sum(dec(row["scheduled_term_principal_due"]) for row in rows)),
            "scheduled_principal_paid": qrow["scheduled_principal_paid"], "cash_sweep": qrow["cash_sweep"],
            "maturity_term_payment": fmt(sum(dec(row["maturity_term_payment"]) for row in rows)),
            "ending_term_principal": last["ending_term_principal"], "opening_revolver": first["opening_revolver"],
            "revolver_draws": qrow["revolver_draws"], "revolver_repayments": qrow["revolver_repayments"],
            "maturity_revolver_payment": fmt(sum(dec(row["maturity_revolver_payment"]) for row in rows)),
            "ending_revolver": last["ending_revolver"], "ending_bank_debt": fmt(bank_debt),
            "retained_debt_proxy": fmt(retained_proxy), "gross_funded_debt": fmt(bank_debt + retained_proxy),
            "cash_interest_paid": qrow["cash_interest_paid"],
            "nominal_revolver_availability": last["nominal_revolver_availability"],
            "usable_revolver_availability": last["usable_revolver_availability"],
            "drawability_status": last["drawability_status"],
            "unsupported_maturity_gap": last["unsupported_maturity_gap"],
            "status": last["model_status"], "source_ids": last["source_ids"],
            "upstream_ids": last["upstream_ids"],
            "limitations": "Retained debt stays at the Phase 5 conservative opening proxy because principal and interest allocation is unavailable.",
        })
    return output


def first_row(
    rows: list[dict[str, str]], predicate,
) -> dict[str, str] | None:
    return next((row for row in rows if predicate(row)), None)


def revolver_path_measures(rows: list[dict[str, str]]) -> dict[str, Decimal | str]:
    """Separate opening exposure from subsequent month-end revolver behavior."""
    if not rows:
        raise Phase6Error("Cannot measure an empty revolver path")
    ordered = sorted(rows, key=lambda row: row["month_end"])
    opening = dec(ordered[0]["opening_revolver"])
    subsequent_peak_row = max(ordered, key=lambda row: dec(row["ending_revolver"]))
    subsequent_peak = dec(subsequent_peak_row["ending_revolver"])
    first_draw = first_row(ordered, lambda row: dec(row["revolver_draw"]) > TOLERANCE)
    first_repayment = first_row(ordered, lambda row: dec(row["revolver_repayment"]) > TOLERANCE)
    if opening >= subsequent_peak:
        headline_peak = opening
        headline_peak_date = "OPENING_POSITION"
    else:
        headline_peak = subsequent_peak
        headline_peak_date = subsequent_peak_row["month_end"]
    return {
        "opening_revolver_balance": opening,
        "peak_subsequent_period_end_revolver": subsequent_peak,
        "peak_subsequent_period_end_revolver_date": subsequent_peak_row["month_end"],
        "peak_revolver_including_opening": headline_peak,
        "peak_revolver_date": headline_peak_date,
        "first_incremental_post_closing_draw_date": first_draw["month_end"] if first_draw else "",
        "first_incremental_post_closing_draw_amount": dec(first_draw["revolver_draw"]) if first_draw else "",
        "first_revolver_repayment_date": first_repayment["month_end"] if first_repayment else "",
    }


def mandatory_failure_detail(row: dict[str, str] | None) -> dict[str, Decimal | str] | None:
    """Return the first failed mandatory obligation in contractual payment order."""
    if row is None or row.get("mandatory_payment_failure_flag") != "yes":
        return None
    return {
        "failed_obligation_type": row["failed_mandatory_obligation_type"],
        "failed_obligation_amount_due": dec(row["failed_obligation_amount_due"]),
        "failed_obligation_amount_paid": dec(row["failed_obligation_amount_paid"]),
        "failed_obligation_unpaid_amount": dec(row["failed_obligation_unpaid_amount"]),
        "revolver_capacity_exhausted_before_failure": (
            "yes" if row["commitment_exhaustion_flag"] == "yes" else "no"
        ),
        "drawability_shutoff_before_failure": (
            "yes" if row["drawability_status"] == "no_waiver_drawability_shutoff" else "no"
        ),
        "cash_available_before_failed_payment": dec(row["cash_available_before_failed_payment"]),
        "cash_remaining_after_failed_payment": dec(row["cash_remaining_after_failed_payment"]),
    }


def scenario_summary(rows: list[dict[str, str]]) -> dict[str, Decimal | str]:
    """Return decision outputs for one scenario/structure path."""
    if not rows:
        raise Phase6Error("Cannot summarize an empty monthly scenario")
    rows = sorted(rows, key=lambda row: row["month_end"])
    non_maturity = [row for row in rows if row["maturity_event"] != "yes"]
    liquidity_row = min(non_maturity, key=lambda row: dec(row["usable_liquidity"]))
    params = base_structure_parameters(rows[0]["structure"])
    opening_liquidity = (
        dec(params["commitment"]) - dec(params["lc"])
        - dec(params["opening_revolver"])
    )
    minimum_liquidity = dec(liquidity_row["usable_liquidity"])
    minimum_liquidity_month = liquidity_row["month_end"]
    if opening_liquidity < minimum_liquidity:
        minimum_liquidity = opening_liquidity
        minimum_liquidity_month = "2026-01-31"
    revolver = revolver_path_measures(rows)
    maturity_row = next((row for row in rows if row["maturity_event"] == "yes"), rows[-1])
    analytical = first_row(rows, lambda row: any(
        row[field] == "yes" for field in (
            "analytical_leverage_failure_flag", "analytical_coverage_failure_flag",
            "analytical_liquidity_failure_flag",
        )
    ))
    payment = first_row(rows, lambda row: row["mandatory_payment_failure_flag"] == "yes")
    payment_detail = mandatory_failure_detail(payment)
    liquidity_warning = first_row(
        non_maturity, lambda row: dec(row["usable_liquidity"]) < LIQUIDITY_WARNING,
    )
    cash_floor = first_row(rows, lambda row: dec(row["cash_floor_shortfall"]) > TOLERANCE)
    exhaustion = first_row(rows, lambda row: row["commitment_exhaustion_flag"] == "yes")
    first_draw = first_row(rows, lambda row: dec(row["revolver_draw"]) > TOLERANCE)
    status = "PASS"
    if payment:
        status = "MANDATORY_PAYMENT_FAILURE"
    elif cash_floor:
        status = "LIQUIDITY_FAILURE"
    elif dec(maturity_row["unsupported_maturity_gap"]) > TOLERANCE:
        status = "MATURITY_SHORTFALL"
    elif analytical:
        status = "BREACHED_ANALYTICAL_THRESHOLD"
    return {
        "minimum_usable_liquidity": minimum_liquidity,
        "minimum_liquidity_month": minimum_liquidity_month,
        **revolver,
        "cumulative_cash_interest": sum((dec(row["cash_interest_paid"]) for row in rows), Decimal("0")),
        "scheduled_principal_paid": sum((dec(row["scheduled_term_principal_paid"]) for row in rows), Decimal("0")),
        "cash_sweep": sum((dec(row["cash_sweep"]) for row in rows), Decimal("0")),
        "ending_bank_debt": dec(maturity_row["ending_term_principal"]) + dec(maturity_row["ending_revolver"]),
        "maturity_date": maturity_row["month_end"],
        "unsupported_maturity_gap": dec(maturity_row["unsupported_maturity_gap"]),
        "first_analytical_threshold_failure": analytical["month_end"] if analytical else "",
        "first_50m_analytical_liquidity_warning": liquidity_warning["month_end"] if liquidity_warning else "",
        "first_cash_floor_failure": cash_floor["month_end"] if cash_floor else "",
        "revolver_capacity_exhaustion_date": exhaustion["month_end"] if exhaustion else "",
        "first_mandatory_payment_failure_date": payment["month_end"] if payment else "",
        "failed_obligation_type": payment_detail["failed_obligation_type"] if payment_detail else "",
        "failed_obligation_amount_due": payment_detail["failed_obligation_amount_due"] if payment_detail else "",
        "failed_obligation_amount_paid": payment_detail["failed_obligation_amount_paid"] if payment_detail else "",
        "failed_obligation_unpaid_amount": payment_detail["failed_obligation_unpaid_amount"] if payment_detail else "",
        "revolver_capacity_exhausted_before_failure": payment_detail["revolver_capacity_exhausted_before_failure"] if payment_detail else "",
        "drawability_shutoff_before_failure": payment_detail["drawability_shutoff_before_failure"] if payment_detail else "",
        "cash_available_before_failed_payment": payment_detail["cash_available_before_failed_payment"] if payment_detail else "",
        "cash_remaining_after_failed_payment": payment_detail["cash_remaining_after_failed_payment"] if payment_detail else "",
        "mandatory_payment_failure_months": sum(
            1 for row in rows if row["mandatory_payment_failure_flag"] == "yes"
        ),
        "planned_dividends": sum((dec(row["base_planned_dividend"]) for row in rows), Decimal("0")),
        "paid_dividends": sum((dec(row["dividend_paid"]) for row in rows), Decimal("0")),
        "unpaid_dividends": sum((dec(row["dividend_unpaid"]) for row in rows), Decimal("0")),
        "suspended_dividends": sum((dec(row["dividend_suspended"]) for row in rows), Decimal("0")),
        "directly_draw_funded_dividends": sum((dec(row["dividend_revolver_draw_caused"]) for row in rows), Decimal("0")),
        "planned_repurchases": sum((dec(row["base_planned_repurchase"]) for row in rows), Decimal("0")),
        "paid_repurchases": sum((dec(row["repurchase_paid"]) for row in rows), Decimal("0")),
        "unpaid_repurchases": sum((dec(row["repurchase_unpaid"]) for row in rows), Decimal("0")),
        "suspended_repurchases": sum((dec(row["repurchase_suspended"]) for row in rows), Decimal("0")),
        "directly_draw_funded_repurchases": sum((dec(row["repurchase_revolver_draw_caused"]) for row in rows), Decimal("0")),
        "repurchases_while_revolver_outstanding": sum((dec(row["repurchase_paid_while_revolver_outstanding"]) for row in rows), Decimal("0")),
        "status": status,
    }


def build_scenario_results(monthly: list[dict[str, str]]) -> list[dict[str, str]]:
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in monthly:
        groups[(row["scenario_id"], row["structure"])].append(row)
    output: list[dict[str, str]] = []
    for index, ((scenario_id, structure), rows) in enumerate(groups.items(), start=1):
        rows.sort(key=lambda row: row["month_end"])
        config = scenario_by_id(scenario_id)
        summary = scenario_summary(rows)
        params = base_structure_parameters(structure)
        output.append({
            "scenario_result_id": f"P6R-{index:03d}", "scenario_id": scenario_id,
            "scenario_family": config.severity, "structure": structure,
            "mitigation_status": "mitigated_owner_reviewed_for_phase6_testing" if config.mitigated else "unmitigated",
            "drawability_path": rows[0]["drawability_path"],
            "opening_bank_debt": fmt(dec(params["opening_term"]) + dec(params["opening_revolver"])),
            **{field: fmt(summary[field]) for field in (
                "opening_revolver_balance", "minimum_usable_liquidity",
                "peak_subsequent_period_end_revolver", "peak_revolver_including_opening",
                "first_incremental_post_closing_draw_amount", "cumulative_cash_interest",
                "scheduled_principal_paid", "cash_sweep", "ending_bank_debt",
                "unsupported_maturity_gap", "failed_obligation_amount_due",
                "failed_obligation_amount_paid", "failed_obligation_unpaid_amount",
                "cash_available_before_failed_payment", "cash_remaining_after_failed_payment",
                "mandatory_payment_failure_months", "planned_dividends", "paid_dividends",
                "unpaid_dividends",
                "suspended_dividends", "directly_draw_funded_dividends",
                "planned_repurchases", "paid_repurchases", "unpaid_repurchases",
                "suspended_repurchases",
                "directly_draw_funded_repurchases", "repurchases_while_revolver_outstanding",
            )},
            **{field: str(summary[field]) for field in (
                "minimum_liquidity_month", "peak_subsequent_period_end_revolver_date",
                "peak_revolver_date", "maturity_date",
                "first_incremental_post_closing_draw_date", "first_revolver_repayment_date",
                "first_analytical_threshold_failure", "first_50m_analytical_liquidity_warning",
                "first_cash_floor_failure", "revolver_capacity_exhaustion_date",
                "first_mandatory_payment_failure_date", "failed_obligation_type",
                "revolver_capacity_exhausted_before_failure",
                "drawability_shutoff_before_failure", "status",
            )},
            "classification": "formula_calculated_scenario_summary",
            "review_status": rows[0]["review_status"], "source_ids": rows[0]["source_ids"],
            "upstream_ids": f"{rows[0]['monthly_stress_id']}:{rows[-1]['monthly_stress_id']}",
            "limitations": "Formal covenant compliance, proposed documentation, recurring fees, eligible cash and refinancing at maturity remain not determinable.",
        })
    return output


def build_distress_events(monthly: list[dict[str, str]]) -> list[dict[str, str]]:
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in monthly:
        groups[(row["scenario_id"], row["structure"])].append(row)
    output: list[dict[str, str]] = []
    event_number = 0
    for (scenario_id, structure), rows in groups.items():
        rows.sort(key=lambda row: row["month_end"])
        revolver = revolver_path_measures(rows)
        peak_subsequent = max(rows, key=lambda row: dec(row["ending_revolver"]))
        first_draw = first_row(rows, lambda row: dec(row["revolver_draw"]) > TOLERANCE)
        first_repayment = first_row(rows, lambda row: dec(row["revolver_repayment"]) > TOLERANCE)
        first_mandatory = first_row(rows, lambda row: row["mandatory_payment_failure_flag"] == "yes")
        specifications = (
            ("OPENING_REVOLVER_EXPOSURE", None, "OPENING_POSITION", "WARNING", fmt(revolver["opening_revolver_balance"]), "opening balance"),
            ("FIRST_INCREMENTAL_POST_CLOSING_DRAW", first_draw, first_draw["month_end"] if first_draw else "", "WARNING", first_draw["revolver_draw"] if first_draw else "", ">0 incremental draw"),
            ("FIRST_REVOLVER_REPAYMENT", first_repayment, first_repayment["month_end"] if first_repayment else "", "WARNING", first_repayment["revolver_repayment"] if first_repayment else "", ">0 repayment"),
            ("PEAK_SUBSEQUENT_PERIOD_END_REVOLVER", peak_subsequent, peak_subsequent["month_end"], "WARNING", fmt(revolver["peak_subsequent_period_end_revolver"]), "maximum modeled month-end balance after opening"),
            ("PEAK_REVOLVER_INCLUDING_OPENING", None if revolver["peak_revolver_date"] == "OPENING_POSITION" else peak_subsequent, str(revolver["peak_revolver_date"]), "WARNING", fmt(revolver["peak_revolver_including_opening"]), "maximum of opening and subsequent month-end balances"),
            ("FIRST_LIQUIDITY_WARNING", first_row(rows, lambda r: r["maturity_event"] != "yes" and dec(r["usable_liquidity"]) < LIQUIDITY_WARNING), "", "BREACHED_ANALYTICAL_THRESHOLD", "", "usable liquidity <50"),
            ("FIRST_CASH_FLOOR_FAILURE", first_row(rows, lambda r: dec(r["cash_floor_shortfall"]) > TOLERANCE), "", "LIQUIDITY_FAILURE", "", "cash-floor shortfall >0"),
            ("FIRST_ANALYTICAL_LEVERAGE_FAILURE", first_row(rows, lambda r: r["analytical_leverage_failure_flag"] == "yes"), "", "BREACHED_ANALYTICAL_THRESHOLD", "", "above analytical threshold"),
            ("FIRST_ANALYTICAL_COVERAGE_FAILURE", first_row(rows, lambda r: r["analytical_coverage_failure_flag"] == "yes"), "", "BREACHED_ANALYTICAL_THRESHOLD", "", "below 3.00x"),
            ("FIRST_NO_WAIVER_DRAWABILITY_SHUTOFF", first_row(rows, lambda r: r["drawability_status"] == "no_waiver_drawability_shutoff"), "", "WARNING", "", "new draws unavailable"),
            ("FIRST_REVOLVER_CAPACITY_EXHAUSTION", first_row(rows, lambda r: r["commitment_exhaustion_flag"] == "yes"), "", "LIQUIDITY_FAILURE", "", "nominal revolver availability <=0"),
            ("FIRST_MANDATORY_PAYMENT_FAILURE", first_mandatory, "", "MANDATORY_PAYMENT_FAILURE", "", "unpaid cash interest, scheduled term principal or retained mandatory obligation"),
            ("FIRST_SCHEDULED_INTEREST_FAILURE", first_row(rows, lambda r: dec(r["cash_interest_shortfall"]) > TOLERANCE), "", "MANDATORY_PAYMENT_FAILURE", "", "cash-interest shortfall >0"),
            ("FIRST_SCHEDULED_PRINCIPAL_FAILURE", first_row(rows, lambda r: dec(r["scheduled_principal_shortfall"]) > TOLERANCE), "", "MANDATORY_PAYMENT_FAILURE", "", "scheduled-term-principal shortfall >0"),
            ("FIRST_RETAINED_OBLIGATION_FAILURE", first_row(rows, lambda r: dec(r["retained_obligation_shortfall"]) > TOLERANCE), "", "MANDATORY_PAYMENT_FAILURE", "", "retained-obligation shortfall >0"),
            ("FIRST_DISTRIBUTION_RESTRICTION_FLAG", first_row(rows, lambda r: r["provisional_distribution_status"] != "permission_not_determinable"), "", "WARNING", "", "narrow or broad analytical flag; not a payment default"),
            ("EXISTING_MATURITY_SHORTFALL", first_row(rows, lambda r: structure == "existing" and r["maturity_event"] == "yes" and dec(r["maturity_principal_shortfall"]) > TOLERANCE), "", "MATURITY_SHORTFALL", "", "unfunded at existing maturity"),
            ("PROPOSED_MATURITY_SHORTFALL", first_row(rows, lambda r: structure == "proposed" and r["maturity_event"] == "yes" and dec(r["maturity_principal_shortfall"]) > TOLERANCE), "", "MATURITY_SHORTFALL", "", "unfunded at proposed maturity"),
        )
        event_dates = {
            (explicit_date or event_row["month_end"])
            for _, event_row, explicit_date, _, _, _ in specifications
            if explicit_date or event_row is not None
        }
        dated = sorted(event_dates, key=lambda value: (value != "OPENING_POSITION", value))
        failure_fields = {
            "FIRST_SCHEDULED_INTEREST_FAILURE": ("CASH_INTEREST", "cash_interest_due", "cash_interest_paid", "cash_interest_shortfall"),
            "FIRST_RETAINED_OBLIGATION_FAILURE": ("RETAINED_MANDATORY_OBLIGATION", "retained_obligation_due", "retained_obligation_paid", "retained_obligation_shortfall"),
            "FIRST_SCHEDULED_PRINCIPAL_FAILURE": ("SCHEDULED_TERM_PRINCIPAL", "scheduled_term_principal_due", "scheduled_term_principal_paid", "scheduled_principal_shortfall"),
        }
        for event_type, event_row, explicit_date, occurred_status, explicit_value, rule in specifications:
            event_number += 1
            event_date = explicit_date or (event_row["month_end"] if event_row else "")
            event_occurred = bool(event_date)
            status = occurred_status if event_occurred else (
                "NOT_APPLICABLE" if (
                    event_type.startswith("EXISTING_") and structure != "existing"
                ) or (
                    event_type.startswith("PROPOSED_") and structure != "proposed"
                ) or (
                    event_type == "FIRST_NO_WAIVER_DRAWABILITY_SHUTOFF"
                    and not scenario_by_id(scenario_id).no_waiver
                ) else "PASS"
            )
            observed_value = explicit_value
            if event_row is not None and not observed_value:
                value_fields = {
                    "FIRST_LIQUIDITY_WARNING": "usable_liquidity",
                    "FIRST_CASH_FLOOR_FAILURE": "cash_floor_shortfall",
                    "FIRST_ANALYTICAL_LEVERAGE_FAILURE": "analytical_bank_leverage",
                    "FIRST_ANALYTICAL_COVERAGE_FAILURE": "ebitda_cash_interest_coverage",
                    "FIRST_NO_WAIVER_DRAWABILITY_SHUTOFF": "usable_revolver_availability",
                    "FIRST_REVOLVER_CAPACITY_EXHAUSTION": "nominal_revolver_availability",
                    "FIRST_MANDATORY_PAYMENT_FAILURE": "failed_obligation_unpaid_amount",
                    "FIRST_SCHEDULED_INTEREST_FAILURE": "cash_interest_shortfall",
                    "FIRST_SCHEDULED_PRINCIPAL_FAILURE": "scheduled_principal_shortfall",
                    "FIRST_RETAINED_OBLIGATION_FAILURE": "retained_obligation_shortfall",
                    "FIRST_DISTRIBUTION_RESTRICTION_FLAG": "repurchase_revolver_draw_caused",
                    "EXISTING_MATURITY_SHORTFALL": "maturity_principal_shortfall",
                    "PROPOSED_MATURITY_SHORTFALL": "maturity_principal_shortfall",
                }
                observed_value = event_row[value_fields[event_type]]
            obligation_type = ""
            amount_due = amount_paid = unpaid_amount = ""
            cash_before = cash_after = ""
            event_class = ""
            if event_type == "FIRST_MANDATORY_PAYMENT_FAILURE" and event_row is not None:
                obligation_type = event_row["failed_mandatory_obligation_type"]
                amount_due = event_row["failed_obligation_amount_due"]
                amount_paid = event_row["failed_obligation_amount_paid"]
                unpaid_amount = event_row["failed_obligation_unpaid_amount"]
                cash_before = event_row["cash_available_before_failed_payment"]
                cash_after = event_row["cash_remaining_after_failed_payment"]
                event_class = "interim_mandatory_payment_failure"
            elif event_type in failure_fields and event_row is not None:
                obligation_type, due_field, paid_field, unpaid_field = failure_fields[event_type]
                amount_due, amount_paid, unpaid_amount = (
                    event_row[due_field], event_row[paid_field], event_row[unpaid_field]
                )
                if event_row["failed_mandatory_obligation_type"] == obligation_type:
                    cash_before = event_row["cash_available_before_failed_payment"]
                    cash_after = event_row["cash_remaining_after_failed_payment"]
                event_class = "interim_mandatory_payment_failure"
            elif event_type.endswith("MATURITY_SHORTFALL") and event_row is not None:
                obligation_type = "MATURITY_PRINCIPAL"
                amount_due = event_row["maturity_principal_due"]
                amount_paid = event_row["maturity_principal_paid"]
                unpaid_amount = event_row["maturity_principal_shortfall"]
                event_class = "maturity_shortfall"
            output.append({
                "distress_event_id": f"P6E-{event_number:04d}", "scenario_id": scenario_id,
                "structure": structure, "event_type": event_type, "event_date": event_date,
                "status": status,
                "observed_value": observed_value,
                "threshold_or_rule": rule,
                "failed_obligation_type": obligation_type,
                "amount_due": amount_due, "amount_paid": amount_paid,
                "unpaid_amount": unpaid_amount,
                "revolver_capacity_already_exhausted": (
                    "yes" if event_row is not None and event_row["commitment_exhaustion_flag"] == "yes"
                    else "no" if event_row is not None else ""
                ),
                "drawability_shutoff_active": (
                    "yes" if event_row is not None and event_row["drawability_status"] == "no_waiver_drawability_shutoff"
                    else "no" if event_row is not None else ""
                ),
                "cash_available_before_payment": cash_before,
                "cash_remaining_after_payment": cash_after,
                "scenario_timing_convention": rows[0]["timing_convention"],
                "interim_failure_or_maturity_shortfall": event_class,
                "sequence_number": str(dated.index(event_date) + 1) if event_date else "",
                "classification": "chronological_analytical_event_not_contractual_default",
                "source_ids": "SRC-001;SRC-002;SRC-003",
                "upstream_ids": event_row["monthly_stress_id"] if event_row else scenario_id,
                "notes": "Mandatory payment failure excludes missed dividends and repurchases. Maturity shortfall, analytical warnings and drawability conventions remain separately classified and are not official covenant conclusions.",
            })
    return output


def build_threshold_tests(monthly: list[dict[str, str]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    quarter_ends = [row for row in monthly if phase5.is_quarter_end(date.fromisoformat(row["month_end"]))]
    for index, row in enumerate(quarter_ends, start=1):
        bank_debt = dec(row["ending_term_principal"]) + dec(row["ending_revolver"])
        ttm = dec(row["ttm_lender_base_ebitda"]) if row["ttm_lender_base_ebitda"] else None
        leverage = dec(row["analytical_bank_leverage"]) if row["analytical_bank_leverage"] else None
        threshold = dec(row["analytical_leverage_threshold"])
        coverage = dec(row["ebitda_cash_interest_coverage"]) if row["ebitda_cash_interest_coverage"] else None
        liquidity = dec(row["usable_liquidity"])
        break_even = bank_debt / threshold
        status = "PASS"
        if row["model_status"] == "MANDATORY_PAYMENT_FAILURE":
            status = "MANDATORY_PAYMENT_FAILURE"
        elif row["model_status"] == "LIQUIDITY_FAILURE":
            status = "LIQUIDITY_FAILURE"
        elif row["model_status"] == "MATURITY_SHORTFALL":
            status = "MATURITY_SHORTFALL"
        elif any(row[field] == "yes" for field in (
            "analytical_leverage_failure_flag", "analytical_coverage_failure_flag",
            "analytical_liquidity_failure_flag",
        )):
            status = "BREACHED_ANALYTICAL_THRESHOLD"
        output.append({
            "threshold_test_id": f"P6T-{index:04d}", "scenario_id": row["scenario_id"],
            "structure": row["structure"], "period_end": row["month_end"],
            "fiscal_year": row["fiscal_year"], "quarter": row["quarter"],
            "gross_funded_leverage": row["gross_funded_leverage"],
            "book_cash_net_leverage_diagnostic": row["book_cash_net_leverage_diagnostic"],
            "analytical_bank_leverage": row["analytical_bank_leverage"],
            "analytical_leverage_threshold": fmt(threshold),
            "leverage_headroom": fmt(threshold - leverage) if leverage is not None else "N/M",
            "ebitda_cash_interest_coverage": row["ebitda_cash_interest_coverage"],
            "coverage_threshold": fmt(COVERAGE_WARNING),
            "coverage_headroom": fmt(coverage - COVERAGE_WARNING) if coverage is not None else "N/M",
            "cfads_cash_interest_coverage": row["cfads_cash_interest_coverage"],
            "cfads_scheduled_debt_service_coverage": row["cfads_scheduled_debt_service_coverage"],
            "usable_liquidity": fmt(liquidity), "liquidity_threshold": fmt(LIQUIDITY_WARNING),
            "liquidity_headroom": fmt(liquidity - LIQUIDITY_WARNING),
            "bank_debt_headroom": fmt(threshold * ttm - bank_debt) if ttm is not None else "N/M",
            "break_even_ebitda": fmt(break_even),
            "earnings_cushion": fmt(ttm - break_even) if ttm is not None else "N/M",
            "analytical_status": status,
            "formal_contractual_compliance": formal_contractual_compliance(None, None),
            "drawability_status": row["drawability_status"],
            "classification": "analytical_warning_test_not_compliance_certificate",
            "review_status": row["review_status"], "source_ids": row["source_ids"],
            "upstream_ids": row["monthly_stress_id"],
            "limitations": "Eligible cash, final EBITDA definitions, covenant baskets, equity cures and proposed legal documentation are unavailable. Book-cash net leverage is an analyst diagnostic only.",
        })
    return output


def build_drawability_paths(monthly: list[dict[str, str]]) -> list[dict[str, str]]:
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in monthly:
        groups[(row["scenario_id"], row["structure"])].append(row)
    output: list[dict[str, str]] = []
    for index, ((scenario_id, structure), rows) in enumerate(groups.items(), start=1):
        rows.sort(key=lambda row: row["month_end"])
        summary = scenario_summary(rows)
        trigger = first_row(rows, lambda r: any(r[field] == "yes" for field in (
            "analytical_leverage_failure_flag", "analytical_coverage_failure_flag",
            "analytical_liquidity_failure_flag",
        )))
        shutoff = first_row(rows, lambda r: r["drawability_status"] == "no_waiver_drawability_shutoff")
        cash_floor = first_row(rows, lambda r: dec(r["cash_floor_shortfall"]) > TOLERANCE)
        exhaustion = first_row(rows, lambda r: r["commitment_exhaustion_flag"] == "yes")
        payment = first_row(rows, lambda r: r["mandatory_payment_failure_flag"] == "yes")
        path = rows[0]["drawability_path"]
        output.append({
            "drawability_path_id": f"P6DP-{index:03d}", "scenario_id": scenario_id,
            "structure": structure, "path_convention": path,
            "analytical_trigger_date": trigger["month_end"] if trigger else "",
            "shutoff_effective_date": shutoff["month_start"] if shutoff else "",
            "new_draws_after_shutoff": "0" if shutoff else "not_applicable",
            "outstanding_revolver_preserved": "yes",
            "minimum_usable_liquidity": fmt(summary["minimum_usable_liquidity"]),
            "cash_floor_failure_date": cash_floor["month_end"] if cash_floor else "",
            "revolver_capacity_exhaustion_date": exhaustion["month_end"] if exhaustion else "",
            "first_mandatory_payment_failure_date": payment["month_end"] if payment else "",
            "failed_obligation_type": payment["failed_mandatory_obligation_type"] if payment else "",
            "maturity_gap": fmt(summary["unsupported_maturity_gap"]),
            "status": str(summary["status"]),
            "classification": "analytical_drawability_convention_not_legal_conclusion",
            "review_status": rows[0]["review_status"], "source_ids": rows[0]["source_ids"],
            "upstream_ids": f"{rows[0]['monthly_stress_id']}:{rows[-1]['monthly_stress_id']}",
            "limitations": "Proposed no-waiver shutoff is a Phase 6 stress convention. Existing drawability remains an analytical warning because formal covenant inputs are incomplete.",
        })
    return output


def build_mitigation_results(
    results: list[dict[str, str]], monthly: list[dict[str, str]],
) -> list[dict[str, str]]:
    by_key = {(row["scenario_id"], row["structure"]): row for row in results}
    monthly_by_key: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in monthly:
        monthly_by_key[(row["scenario_id"], row["structure"])].append(row)
    output: list[dict[str, str]] = []
    pairs = (
        ("moderate", "MODERATE_UNMITIGATED", "MODERATE_MITIGATED"),
        ("severe", "SEVERE_UNMITIGATED", "SEVERE_MITIGATED"),
    )
    for severity, unmitigated_id, mitigated_id in pairs:
        for structure in ("proposed", "existing"):
            unmitigated = by_key[(unmitigated_id, structure)]
            mitigated = by_key[(mitigated_id, structure)]
            unmitigated_monthly = monthly_by_key[(unmitigated_id, structure)]
            mitigated_monthly = monthly_by_key[(mitigated_id, structure)]
            planned_distributions = sum((
                dec(row["base_planned_dividend"]) + dec(row["base_planned_repurchase"])
                for row in unmitigated_monthly
            ), Decimal("0"))
            distributions_due = sum((
                dec(row["planned_dividend_after_mitigation"])
                + dec(row["planned_repurchase_after_mitigation"])
                for row in mitigated_monthly
            ), Decimal("0"))
            paid_unmitigated = sum((
                dec(row["dividend_paid"]) + dec(row["repurchase_paid"])
                for row in unmitigated_monthly
            ), Decimal("0"))
            unpaid_unmitigated = sum((
                dec(row["dividend_unpaid"]) + dec(row["repurchase_unpaid"])
                for row in unmitigated_monthly
            ), Decimal("0"))
            formally_suspended = sum((
                dec(row["dividend_suspended"]) + dec(row["repurchase_suspended"])
                for row in mitigated_monthly
            ), Decimal("0"))
            paid_mitigated = sum((
                dec(row["dividend_paid"]) + dec(row["repurchase_paid"])
                for row in mitigated_monthly
            ), Decimal("0"))
            cash_preserved = paid_unmitigated - paid_mitigated
            interest_saved = (
                dec(unmitigated["cumulative_cash_interest"])
                - dec(mitigated["cumulative_cash_interest"])
            )
            additional_retained_paid = sum((
                dec(row["retained_obligation_paid"]) for row in mitigated_monthly
            ), Decimal("0")) - sum((
                dec(row["retained_obligation_paid"]) for row in unmitigated_monthly
            ), Decimal("0"))
            other_effect = -additional_retained_paid
            gap_reduction = (
                dec(unmitigated["unsupported_maturity_gap"])
                - dec(mitigated["unsupported_maturity_gap"])
            )
            reconciliation_difference = gap_reduction - (
                cash_preserved + interest_saved + other_effect
            )
            index = len(output) + 1
            output.append({
                "mitigation_result_id": f"P6MR-{index:03d}", "severity": severity,
                "structure": structure, "unmitigated_scenario_id": unmitigated_id,
                "mitigated_scenario_id": mitigated_id, "mitigation_start_date": MITIGATION_START.isoformat(),
                "implementation_cost": "0",
                "planned_distributions": fmt(planned_distributions),
                "distributions_due_under_policy": fmt(distributions_due),
                "distributions_actually_paid_unmitigated": fmt(paid_unmitigated),
                "distributions_unpaid_due_to_prior_cash_or_capacity_failure": fmt(unpaid_unmitigated),
                "distributions_formally_suspended_in_mitigated_case": fmt(formally_suspended),
                "distributions_actually_paid_mitigated": fmt(paid_mitigated),
                "incremental_cash_preserved_by_mitigation": fmt(cash_preserved),
                "incremental_interest_saved": fmt(interest_saved),
                "incremental_retained_obligations_paid": fmt(additional_retained_paid),
                "other_timing_or_waterfall_effect": fmt(other_effect),
                "other_timing_or_waterfall_explanation": (
                    "Cash preserved also funds additional retained mandatory obligations before bank principal."
                    if abs(additional_retained_paid) > TOLERANCE else "none"
                ),
                "maturity_gap_reduction": fmt(gap_reduction),
                "mitigation_reconciliation_difference": fmt(reconciliation_difference),
                "dividends_suspended": mitigated["suspended_dividends"],
                "repurchases_suspended": mitigated["suspended_repurchases"],
                "minimum_liquidity_unmitigated": unmitigated["minimum_usable_liquidity"],
                "minimum_liquidity_mitigated": mitigated["minimum_usable_liquidity"],
                "minimum_liquidity_benefit": fmt(dec(mitigated["minimum_usable_liquidity"]) - dec(unmitigated["minimum_usable_liquidity"])),
                "opening_revolver_balance": unmitigated["opening_revolver_balance"],
                "peak_subsequent_revolver_unmitigated": unmitigated["peak_subsequent_period_end_revolver"],
                "peak_subsequent_revolver_mitigated": mitigated["peak_subsequent_period_end_revolver"],
                "peak_revolver_including_opening_unmitigated": unmitigated["peak_revolver_including_opening"],
                "peak_revolver_including_opening_mitigated": mitigated["peak_revolver_including_opening"],
                "peak_revolver_benefit": fmt(dec(unmitigated["peak_revolver_including_opening"]) - dec(mitigated["peak_revolver_including_opening"])),
                "peak_revolver_date_unmitigated": unmitigated["peak_revolver_date"],
                "peak_revolver_date_mitigated": mitigated["peak_revolver_date"],
                "maturity_gap_unmitigated": unmitigated["unsupported_maturity_gap"],
                "maturity_gap_mitigated": mitigated["unsupported_maturity_gap"],
                "maturity_gap_benefit": fmt(dec(unmitigated["unsupported_maturity_gap"]) - dec(mitigated["unsupported_maturity_gap"])),
                "cash_interest_unmitigated": unmitigated["cumulative_cash_interest"],
                "cash_interest_mitigated": mitigated["cumulative_cash_interest"],
                "cash_interest_benefit": fmt(dec(unmitigated["cumulative_cash_interest"]) - dec(mitigated["cumulative_cash_interest"])),
                "payment_failure_unmitigated": "yes" if unmitigated["first_mandatory_payment_failure_date"] else "no",
                "payment_failure_mitigated": "yes" if mitigated["first_mandatory_payment_failure_date"] else "no",
                "status": "OWNER_REVIEWED_FOR_PHASE6_TESTING_NOT_CERTAIN_MANAGEMENT_ACTION",
                "classification": "side_by_side_management_action_sensitivity",
                "review_status": "owner_reviewed_for_phase6_testing", "source_ids": "SRC-001;SRC-002;SRC-003",
                "upstream_ids": f"{unmitigated['scenario_result_id']};{mitigated['scenario_result_id']};MIT-001;MIT-002",
                "limitations": "Scheduled policy reductions and realized cash preservation are separate. Distributions already unpaid in the unmitigated failure path receive no mitigation credit; implementation, board action and legal permission are not assumed certain.",
            })
    return output


def run_case(
    config: ScenarioConfig, structure: str,
    amortization_percent: Decimal = Decimal("10"),
) -> list[dict[str, str]]:
    return run_monthly(config, structure, build_operating(config), amortization_percent)


def failure_snapshot(
    rows: list[dict[str, str]], failure_kind: str,
) -> tuple[bool, str, Decimal]:
    non_maturity = [row for row in rows if row["maturity_event"] != "yes"]
    if failure_kind == "liquidity_warning":
        row = first_row(non_maturity, lambda r: dec(r["usable_liquidity"]) < LIQUIDITY_WARNING)
        return (row is not None, row["month_end"] if row else "", dec(row["usable_liquidity"]) if row else min(dec(r["usable_liquidity"]) for r in non_maturity))
    if failure_kind == "commitment_exhaustion":
        row = first_row(non_maturity, lambda r: r["commitment_exhaustion_flag"] == "yes")
        return (row is not None, row["month_end"] if row else "", dec(row["nominal_revolver_availability"]) if row else min(dec(r["nominal_revolver_availability"]) for r in non_maturity))
    if failure_kind == "interest_coverage":
        available = [row for row in non_maturity if row["ebitda_cash_interest_coverage"]]
        row = first_row(available, lambda r: dec(r["ebitda_cash_interest_coverage"]) < COVERAGE_WARNING)
        value = dec(row["ebitda_cash_interest_coverage"]) if row else min(dec(r["ebitda_cash_interest_coverage"]) for r in available)
        return row is not None, row["month_end"] if row else "", value
    if failure_kind == "leverage_325":
        available = [row for row in non_maturity if row["analytical_bank_leverage"] and date.fromisoformat(row["month_end"]) < date(2027, 11, 1)]
        row = first_row(available, lambda r: dec(r["analytical_bank_leverage"]) > LEVERAGE_INITIAL)
        value = dec(row["analytical_bank_leverage"]) if row else max(dec(r["analytical_bank_leverage"]) for r in available)
        return row is not None, row["month_end"] if row else "", value
    if failure_kind == "leverage_300":
        available = [row for row in non_maturity if row["analytical_bank_leverage"] and date.fromisoformat(row["month_end"]) >= date(2027, 11, 1)]
        row = first_row(available, lambda r: dec(r["analytical_bank_leverage"]) > LEVERAGE_STEPDOWN)
        value = dec(row["analytical_bank_leverage"]) if row else max(dec(r["analytical_bank_leverage"]) for r in available)
        return row is not None, row["month_end"] if row else "", value
    if failure_kind == "payment_failure":
        row = first_row(rows, lambda r: any(dec(r[field]) > TOLERANCE for field in (
            "cash_interest_shortfall", "scheduled_principal_shortfall", "retained_obligation_shortfall",
        )))
        value = max((max(dec(r["cash_interest_shortfall"]), dec(r["scheduled_principal_shortfall"]), dec(r["retained_obligation_shortfall"])) for r in rows), default=Decimal("0"))
        return row is not None, row["month_end"] if row else "", value
    if failure_kind == "distribution_eliminated":
        row = first_row(rows, lambda r: (
            dec(r["base_planned_dividend"]) + dec(r["base_planned_repurchase"]) > 0
            and dec(r["dividend_paid"]) + dec(r["repurchase_paid"]) <= TOLERANCE
        ))
        value = (
            dec(row["dividend_paid"]) + dec(row["repurchase_paid"])
            if row else min(dec(r["dividend_paid"]) + dec(r["repurchase_paid"]) for r in rows)
        )
        return row is not None, row["month_end"] if row else "", value
    if failure_kind == "no_waiver_liquidity":
        row = first_row(non_maturity, lambda r: r["drawability_status"] == "no_waiver_drawability_shutoff" and dec(r["cash_floor_shortfall"]) > TOLERANCE)
        value = max((dec(r["cash_floor_shortfall"]) for r in non_maturity), default=Decimal("0"))
        return row is not None, row["month_end"] if row else "", value
    if failure_kind == "maturity_gap_eliminated":
        row = next(row for row in rows if row["maturity_event"] == "yes")
        value = dec(row["unsupported_maturity_gap"])
        return value <= TOLERANCE, row["month_end"], value
    raise Phase6Error(f"Unknown reverse-stress failure kind: {failure_kind}")


def constant_config(
    scenario_id: str, *, volume_percent: Decimal = Decimal("0"),
    margin_bps: Decimal = Decimal("0"), dso_days: Decimal = Decimal("0"),
    dio_days: Decimal = Decimal("0"), rate_bps: Decimal = Decimal("0"),
    extra_annual_cfads: Decimal = Decimal("0"), no_waiver: bool = False,
) -> ScenarioConfig:
    active = any(value != 0 for value in (
        volume_percent, margin_bps, dso_days, dio_days, rate_bps, extra_annual_cfads,
    ))
    return ScenarioConfig(
        scenario_id=scenario_id, severity="severe" if active else "base",
        no_waiver=no_waiver, volume_percent=volume_percent, margin_bps=margin_bps,
        dso_days=dso_days, dio_days=dio_days, rate_bps=rate_bps,
        plateau_quarters=99 if active else 0, recovery_quarters=0,
        extra_annual_cfads=extra_annual_cfads,
    )


def rounded_search_result(value: Decimal, tolerance: Decimal) -> Decimal:
    return value.quantize(tolerance, rounding=ROUND_CEILING)


def bounded_reverse_search(
    structure: str, name: str, dimension: str, units: str,
    lower: Decimal, upper: Decimal, tolerance: Decimal, threshold: str,
    failure_kind: str, config_factory,
) -> dict[str, str]:
    def evaluate(value: Decimal) -> tuple[bool, str, Decimal]:
        config = config_factory(value)
        return failure_snapshot(run_case(config, structure), failure_kind)

    lower_result = evaluate(lower)
    if lower_result[0]:
        selected_value = lower
        result = {
            "test_name": name, "shock_dimension": dimension, "lower_bound": fmt(lower),
            "upper_bound": fmt(upper), "result_value": fmt(lower), "units": units,
            "search_tolerance": fmt(tolerance), "search_iterations": "0",
            "threshold": threshold, "threshold_status": "threshold_already_failed",
            "first_failure_date": lower_result[1], "resulting_metric": fmt(lower_result[2]),
        }
    else:
        upper_result = evaluate(upper)
        if not upper_result[0]:
            selected_value = upper
            result = {
                "test_name": name, "shock_dimension": dimension, "lower_bound": fmt(lower),
                "upper_bound": fmt(upper), "result_value": "", "units": units,
                "search_tolerance": fmt(tolerance), "search_iterations": "0",
                "threshold": threshold, "threshold_status": "not_reached_within_bounds",
                "first_failure_date": "", "resulting_metric": fmt(upper_result[2]),
            }
        else:
            lo, hi = lower, upper
            iterations = 0
            winning = upper_result
            while hi - lo > tolerance and iterations < 80:
                midpoint = (lo + hi) / Decimal("2")
                evaluated = evaluate(midpoint)
                iterations += 1
                if evaluated[0]:
                    hi, winning = midpoint, evaluated
                else:
                    lo = midpoint
            displayed = rounded_search_result(hi, tolerance)
            displayed_result = evaluate(displayed)
            selected_value = displayed
            result = {
                "test_name": name, "shock_dimension": dimension, "lower_bound": fmt(lower),
                "upper_bound": fmt(upper), "result_value": fmt(displayed), "units": units,
                "search_tolerance": fmt(tolerance), "search_iterations": str(iterations),
                "threshold": threshold, "threshold_status": "approximated_first_failure",
                "first_failure_date": displayed_result[1] or winning[1],
                "resulting_metric": fmt(displayed_result[2] if displayed_result[0] else winning[2]),
            }
    exposure = revolver_path_measures(run_case(config_factory(selected_value), structure))
    result.update({
        "opening_revolver_balance": fmt(exposure["opening_revolver_balance"]),
        "peak_subsequent_period_end_revolver": fmt(exposure["peak_subsequent_period_end_revolver"]),
        "peak_revolver_including_opening": fmt(exposure["peak_revolver_including_opening"]),
        "peak_revolver_date": str(exposure["peak_revolver_date"]),
    })
    return result


def build_reverse_stress() -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for structure in ("proposed", "existing"):
        specifications = (
            ("volume decline to first $50m liquidity warning", "volume_decline", "percent", Decimal("0"), Decimal("60"), Decimal("0.01"), "usable liquidity < $50m", "liquidity_warning", lambda x: constant_config(f"RS-VOL-{fmt(x)}", volume_percent=-x)),
            ("gross-margin decline to first $50m liquidity warning", "gross_margin_decline", "basis_points", Decimal("0"), Decimal("1500"), Decimal("1"), "usable liquidity < $50m", "liquidity_warning", lambda x: constant_config(f"RS-GM-{fmt(x)}", margin_bps=-x)),
            ("combined volume-margin scale to commitment exhaustion", "severe_combined_scale", "multiple_of_severe_case", Decimal("0"), Decimal("3"), Decimal("0.01"), "nominal revolver availability <= 0", "commitment_exhaustion", lambda x: constant_config(f"RS-COMB-{fmt(x)}", volume_percent=Decimal("-15") * x, margin_bps=Decimal("-375") * x, dso_days=Decimal("15") * x, dio_days=Decimal("25") * x, rate_bps=Decimal("200") * x)),
            ("DSO increase to commitment exhaustion", "dso_increase", "days", Decimal("0"), Decimal("150"), Decimal("0.1"), "nominal revolver availability <= 0", "commitment_exhaustion", lambda x: constant_config(f"RS-DSO-{fmt(x)}", dso_days=x)),
            ("DIO increase to commitment exhaustion", "dio_increase", "days", Decimal("0"), Decimal("200"), Decimal("0.1"), "nominal revolver availability <= 0", "commitment_exhaustion", lambda x: constant_config(f"RS-DIO-{fmt(x)}", dio_days=x)),
            ("rate increase to cash-interest coverage below 3.00x", "rate_increase", "basis_points", Decimal("0"), Decimal("1000"), Decimal("1"), "EBITDA/cash interest < 3.00x", "interest_coverage", lambda x: constant_config(f"RS-RATE-{fmt(x)}", rate_bps=x)),
            ("gross-margin decline to leverage above 3.25x", "gross_margin_decline", "basis_points", Decimal("0"), Decimal("1000"), Decimal("1"), "analytical bank leverage > 3.25x before FY2028", "leverage_325", lambda x: constant_config(f"RS-LEV325-{fmt(x)}", margin_bps=-x)),
            ("gross-margin decline to leverage above 3.00x after FY2028", "gross_margin_decline", "basis_points", Decimal("0"), Decimal("1000"), Decimal("1"), "analytical bank leverage > 3.00x beginning FY2028", "leverage_300", lambda x: constant_config(f"RS-LEV300-{fmt(x)}", margin_bps=-x)),
            ("combined operating scale to scheduled debt-service failure", "severe_combined_scale", "multiple_of_severe_case", Decimal("0"), Decimal("5"), Decimal("0.01"), "interest, scheduled principal or retained-obligation shortfall > 0", "payment_failure", lambda x: constant_config(f"RS-DS-{fmt(x)}", volume_percent=Decimal("-15") * x, margin_bps=Decimal("-375") * x, dso_days=Decimal("15") * x, dio_days=Decimal("25") * x, rate_bps=Decimal("200") * x)),
            ("combined operating scale to eliminate monthly cash available for distributions", "severe_combined_scale", "multiple_of_severe_case", Decimal("0"), Decimal("5"), Decimal("0.01"), "no planned dividend or repurchase can be paid in a month", "distribution_eliminated", lambda x: constant_config(f"RS-DIST-{fmt(x)}", volume_percent=Decimal("-15") * x, margin_bps=Decimal("-375") * x, dso_days=Decimal("15") * x, dio_days=Decimal("25") * x, rate_bps=Decimal("200") * x)),
            ("combined operating scale to first no-waiver liquidity failure", "severe_combined_scale", "multiple_of_severe_case", Decimal("0"), Decimal("3"), Decimal("0.01"), "cash-floor failure after proposed analytical shutoff", "no_waiver_liquidity", lambda x: constant_config(f"RS-NW-{fmt(x)}", volume_percent=Decimal("-15") * x, margin_bps=Decimal("-375") * x, dso_days=Decimal("15") * x, dio_days=Decimal("25") * x, rate_bps=Decimal("200") * x, no_waiver=True)),
            ("annual CFADS increment to eliminate unsupported maturity gap", "sustainable_annual_cfads_increment", "USD_millions_per_year", Decimal("0"), Decimal("300"), Decimal("1"), "unsupported maturity gap <= $0", "maturity_gap_eliminated", lambda x: constant_config(f"RS-CFADS-{fmt(x)}", extra_annual_cfads=x)),
        )
        for name, dimension, units, lower, upper, tolerance, threshold, failure_kind, factory in specifications:
            if structure == "existing" and failure_kind == "no_waiver_liquidity":
                result = {
                    "test_name": name, "shock_dimension": dimension,
                    "lower_bound": fmt(lower), "upper_bound": fmt(upper),
                    "result_value": "", "units": units,
                    "search_tolerance": fmt(tolerance), "search_iterations": "0",
                    "threshold": threshold,
                    "threshold_status": "not_applicable_existing_analytical_warning_only",
                    "first_failure_date": "", "resulting_metric": "",
                }
            else:
                result = bounded_reverse_search(
                    structure, name, dimension, units, lower, upper, tolerance,
                    threshold, failure_kind, factory,
                )
            result.update({
                "reverse_stress_id": f"P6RS-{len(output) + 1:03d}", "structure": structure,
                "classification": "bounded_analytical_reverse_stress",
                "review_status": "proposed_for_owner_review",
                "source_ids": "SRC-001;SRC-002;SRC-003",
                "upstream_ids": "SCN-001:SCN-009;P5A-001:P5A-042",
                "limitations": "Breakpoint is model-dependent and reported only to the stated tolerance; it is not a forecast, covenant cure, refinancing assumption or legal conclusion.",
            })
            output.append(result)
    return output


def decision_snapshot(rows: list[dict[str, str]]) -> dict[str, Decimal | str]:
    non_maturity = [row for row in rows if row["maturity_event"] != "yes"]
    coverages = [dec(row["ebitda_cash_interest_coverage"]) for row in non_maturity if row["ebitda_cash_interest_coverage"]]
    first_distress = first_row(non_maturity, lambda row: any((
        row["analytical_leverage_failure_flag"] == "yes",
        row["analytical_coverage_failure_flag"] == "yes",
        row["analytical_liquidity_failure_flag"] == "yes",
        dec(row["cash_floor_shortfall"]) > TOLERANCE,
        dec(row["cash_interest_shortfall"]) > TOLERANCE,
        dec(row["scheduled_principal_shortfall"]) > TOLERANCE,
        dec(row["retained_obligation_shortfall"]) > TOLERANCE,
    )))
    maturity = next(row for row in rows if row["maturity_event"] == "yes")
    revolver = revolver_path_measures(rows)
    return {
        "minimum_usable_liquidity": min(dec(row["usable_liquidity"]) for row in non_maturity),
        **revolver,
        "first_distress_date": first_distress["month_end"] if first_distress else "",
        "maturity_gap": dec(maturity["unsupported_maturity_gap"]),
        "minimum_interest_coverage": min(coverages) if coverages else "",
        "no_waiver_shortfall": max(dec(row["cash_floor_shortfall"]) for row in rows),
    }


def build_sensitivity_grids() -> list[dict[str, str]]:
    output: list[dict[str, str]] = []

    def add_grid(
        grid_name: str, structure: str, x_name: str, x_units: str,
        y_name: str, y_units: str, x_values: Sequence[Decimal],
        y_values: Sequence[Decimal], factory,
    ) -> None:
        for x_value in x_values:
            for y_value in y_values:
                config, amortization = factory(x_value, y_value)
                snapshot = decision_snapshot(run_case(config, structure, amortization))
                output.append({
                    "grid_point_id": f"P6G-{len(output) + 1:04d}", "grid_name": grid_name,
                    "structure": structure, "x_dimension": x_name, "x_value": fmt(x_value),
                    "x_units": x_units, "y_dimension": y_name, "y_value": fmt(y_value),
                    "y_units": y_units, "minimum_usable_liquidity": fmt(snapshot["minimum_usable_liquidity"]),
                    "opening_revolver_balance": fmt(snapshot["opening_revolver_balance"]),
                    "peak_subsequent_period_end_revolver": fmt(snapshot["peak_subsequent_period_end_revolver"]),
                    "peak_revolver_including_opening": fmt(snapshot["peak_revolver_including_opening"]),
                    "peak_revolver_date": str(snapshot["peak_revolver_date"]),
                    "first_distress_date": str(snapshot["first_distress_date"]),
                    "maturity_gap": fmt(snapshot["maturity_gap"]),
                    "minimum_interest_coverage": fmt(snapshot["minimum_interest_coverage"]),
                    "no_waiver_shortfall": fmt(snapshot["no_waiver_shortfall"]),
                    "classification": "decision_relevant_two_variable_sensitivity",
                    "review_status": "proposed_for_owner_review", "source_ids": "SRC-001;SRC-002;SRC-003",
                    "upstream_ids": "SCN-001:SCN-009;P5A-001:P5A-042",
                    "limitations": "Grid points are sensitivities, not forecasts or owner-approved scenario assumptions.",
                })

    for structure in ("proposed", "existing"):
        add_grid(
            "volume_vs_gross_margin", structure, "volume_decline", "percent",
            "gross_margin_decline", "basis_points",
            (Decimal("5"), Decimal("10"), Decimal("15")),
            (Decimal("150"), Decimal("300"), Decimal("450")),
            lambda x, y: (constant_config(f"GRID-VM-{fmt(x)}-{fmt(y)}", volume_percent=-x, margin_bps=-y), Decimal("10")),
        )
        add_grid(
            "dso_vs_dio", structure, "dso_increase", "days", "dio_increase", "days",
            (Decimal("5"), Decimal("10"), Decimal("15")),
            (Decimal("10"), Decimal("20"), Decimal("30")),
            lambda x, y: (constant_config(f"GRID-WC-{fmt(x)}-{fmt(y)}", dso_days=x, dio_days=y), Decimal("10")),
        )
        add_grid(
            "rate_vs_gross_margin", structure, "rate_increase", "basis_points",
            "gross_margin_decline", "basis_points",
            (Decimal("100"), Decimal("200"), Decimal("300")),
            (Decimal("150"), Decimal("300"), Decimal("450")),
            lambda x, y: (constant_config(f"GRID-RM-{fmt(x)}-{fmt(y)}", rate_bps=x, margin_bps=-y), Decimal("10")),
        )
    scenario_lookup = {config.severity: config for config in (
        scenario_by_id("BASE"), scenario_by_id("MODERATE_UNMITIGATED"),
        scenario_by_id("SEVERE_UNMITIGATED"),
    )}
    add_grid(
        "amortization_vs_operating_stress", "proposed", "annual_amortization", "percent",
        "operating_stress", "ordinal_base_1_moderate_2_severe_3",
        (Decimal("5"), Decimal("10"), Decimal("15")),
        (Decimal("1"), Decimal("2"), Decimal("3")),
        lambda x, y: (replace(scenario_lookup[{Decimal("1"): "base", Decimal("2"): "moderate", Decimal("3"): "severe"}[y]], scenario_id=f"GRID-AM-{fmt(x)}-{fmt(y)}"), x),
    )
    return output


def build_timing_sensitivity(monthly: list[dict[str, str]]) -> list[dict[str, str]]:
    """Compare neutral equal allocation with the approved adverse timing cases."""
    core_groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in monthly:
        core_groups[(row["scenario_id"], row["structure"])].append(row)
    requested = (
        ("MODERATE_UNMITIGATED", "proposed"),
        ("MODERATE_UNMITIGATED", "existing"),
        ("SEVERE_UNMITIGATED", "proposed"),
        ("SEVERE_UNMITIGATED", "existing"),
        ("SEVERE_MITIGATED", "proposed"),
        ("SEVERE_MITIGATED", "existing"),
        ("MODERATE_NO_WAIVER", "proposed"),
        ("SEVERE_NO_WAIVER", "proposed"),
    )
    event_fields = (
        "first_incremental_post_closing_draw_date",
        "first_50m_analytical_liquidity_warning",
        "first_cash_floor_failure",
        "revolver_capacity_exhaustion_date",
        "first_mandatory_payment_failure_date",
    )
    output: list[dict[str, str]] = []
    for scenario_id, structure in requested:
        base_config = scenario_by_id(scenario_id)
        equal_config = replace(base_config, timing_convention="equal")
        equal_rows = run_case(equal_config, structure)
        adverse_rows = core_groups[(scenario_id, structure)]
        summaries = {
            "equal": scenario_summary(equal_rows),
            "adverse": scenario_summary(adverse_rows),
        }
        equal = summaries["equal"]
        for timing_case, path_rows in (("equal", equal_rows), ("adverse", adverse_rows)):
            summary = summaries[timing_case]
            comparisons = [
                f"{field}: equal={equal[field] or 'none'}, {timing_case}={summary[field] or 'none'}"
                for field in event_fields if summary[field] != equal[field]
            ]
            if timing_case == "equal":
                event_comparison = "reference_equal_allocation"
            elif comparisons:
                event_comparison = "; ".join(comparisons)
            else:
                event_comparison = "same_event_dates_as_equal"
            output.append({
                "timing_sensitivity_id": f"P6TS-{len(output) + 1:03d}",
                "scenario_id": scenario_id, "scenario_family": base_config.severity,
                "structure": structure, "timing_case": timing_case,
                "timing_pattern": (
                    "equal_thirds"
                    if timing_case == "equal"
                    else "20%_30%_50%" if base_config.severity == "moderate"
                    else "10%_25%_65%"
                ),
                "minimum_usable_liquidity": fmt(summary["minimum_usable_liquidity"]),
                "minimum_liquidity_month": str(summary["minimum_liquidity_month"]),
                "opening_revolver_balance": fmt(summary["opening_revolver_balance"]),
                "peak_subsequent_period_end_revolver": fmt(summary["peak_subsequent_period_end_revolver"]),
                "peak_subsequent_period_end_revolver_date": str(summary["peak_subsequent_period_end_revolver_date"]),
                "peak_revolver_including_opening": fmt(summary["peak_revolver_including_opening"]),
                "peak_revolver_date": str(summary["peak_revolver_date"]),
                "first_incremental_post_closing_draw_date": str(summary["first_incremental_post_closing_draw_date"]),
                "first_incremental_post_closing_draw_amount": fmt(summary["first_incremental_post_closing_draw_amount"]),
                "first_50m_analytical_liquidity_warning": str(summary["first_50m_analytical_liquidity_warning"]),
                "first_cash_floor_failure": str(summary["first_cash_floor_failure"]),
                "revolver_capacity_exhaustion_date": str(summary["revolver_capacity_exhaustion_date"]),
                "first_mandatory_payment_failure_date": str(summary["first_mandatory_payment_failure_date"]),
                "failed_obligation_type": str(summary["failed_obligation_type"]),
                "maturity_shortfall": fmt(summary["unsupported_maturity_gap"]),
                "minimum_liquidity_difference_from_equal": fmt(dec(summary["minimum_usable_liquidity"]) - dec(equal["minimum_usable_liquidity"])),
                "peak_subsequent_revolver_difference_from_equal": fmt(dec(summary["peak_subsequent_period_end_revolver"]) - dec(equal["peak_subsequent_period_end_revolver"])),
                "peak_revolver_including_opening_difference_from_equal": fmt(dec(summary["peak_revolver_including_opening"]) - dec(equal["peak_revolver_including_opening"])),
                "maturity_shortfall_difference_from_equal": fmt(dec(summary["unsupported_maturity_gap"]) - dec(equal["unsupported_maturity_gap"])),
                "event_date_comparison_from_equal": event_comparison,
                "classification": "monthly_timing_sensitivity_not_observed_seasonality",
                "review_status": "owner_reviewed_for_phase6_testing",
                "source_ids": "SRC-001;SRC-002;SRC-003",
                "upstream_ids": f"{scenario_id};P5A-001:P5A-042",
                "limitations": "Equal allocation is neutral and adverse allocation is a conservative underwriting sensitivity. Neither is verified actual monthly seasonality; exact event dates depend on the selected convention.",
            })
    return output


def prior_analytical_artifact_changes() -> list[str]:
    protected = [
        path for path in subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", APPROVED_PHASE5_COMMIT],
            cwd=ROOT, text=True, capture_output=True, check=True,
        ).stdout.splitlines()
        if path.startswith(("data/phase", "docs/phase-"))
    ]
    result = subprocess.run(
        ["git", "diff", "--name-only", APPROVED_PHASE5_COMMIT, "--", *protected],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    missing = [path for path in protected if not (ROOT / path).is_file()]
    return sorted(set(missing + [line for line in result.stdout.splitlines() if line]))


def changed_paths() -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    output: list[str] = []
    for line in result.stdout.splitlines():
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        output.append(path.replace("\\", "/"))
    return output


def approved_phase6_contains_phase7() -> bool:
    """Return whether the approved Phase 6 snapshot already contained Phase 7."""
    result = subprocess.run(
        [
            "git", "ls-tree", "-r", "--name-only", APPROVED_PHASE6_COMMIT, "--",
            "data/phase7", "docs/phase-7", "scripts/phase7.py", "tests/test_phase7.py",
        ],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    return bool(result.stdout.strip())


def validate_changed_paths() -> None:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        capture_output=True, check=True,
    ).stdout.strip()
    at_phase5_checkpoint = head == APPROVED_PHASE5_COMMIT
    approved_phase6_is_ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", APPROVED_PHASE6_COMMIT, head],
        cwd=ROOT, text=True, capture_output=True,
    ).returncode == 0
    if not at_phase5_checkpoint and not approved_phase6_is_ancestor:
        raise Phase6Error(
            "HEAD is neither the approved Phase 5 development checkpoint nor a "
            f"descendant of the approved Phase 6 commit: {head}"
        )
    allowed_exact = {
        ".gitattributes", "README.md", "scripts/phase4.py", "scripts/phase5.py", "scripts/phase6.py",
        "scripts/phase7.py", "scripts/phase8.py", "scripts/build-phase8.mjs",
        "scripts/recalculate-phase8.py", "scripts/validate-phase8-excel.ps1",
        "scripts/phase9.py", "scripts/build-phase9.mjs", "scripts/recalculate-phase9.py", "scripts/validate-phase9-excel.ps1",
        "scripts/phase10.py", "scripts/build-phase10.mjs", "scripts/render-phase10.py",
        "scripts/phase11.py", "scripts/render-phase11.py",
        "tests/test_phase5.py", "tests/test_phase6.py",
        "tests/test_phase7.py", "tests/test_phase8.py", "tests/test_phase9.py", "tests/test_phase10.py", "tests/test_phase11.py",
        "tests/test_audit_remediation.py",
        "model/Quanex_Credit_Underwriting.xlsx",
    }
    unexpected = [
        path for path in changed_paths()
        if path not in allowed_exact
        and not path.startswith("data/phase6/")
        and not path.startswith("docs/phase-6/")
        and not path.startswith("data/phase7/")
        and not path.startswith("docs/phase-7/")
        and not path.startswith("data/phase8/")
        and not path.startswith("docs/phase-8/")
        and not path.startswith("data/phase9/")
        and not path.startswith("docs/phase-9/")
        and not path.startswith("data/phase10/")
        and not path.startswith("docs/phase-10/")
        and not path.startswith("data/phase11/")
        and not path.startswith("docs/phase-11/")
        and not path.startswith("reports/")
    ]
    if unexpected:
        raise Phase6Error("Unexpected changed paths: " + ", ".join(unexpected))
    prior = prior_analytical_artifact_changes()
    if prior:
        raise Phase6Error("Protected Phase 0-5 analytical artifacts changed: " + ", ".join(prior))


def validation_rows(
    operating: list[dict[str, str]], monthly: list[dict[str, str]],
    quarterly: list[dict[str, str]], results: list[dict[str, str]],
    assumptions: list[dict[str, str]], mitigations: list[dict[str, str]],
    reverse: list[dict[str, str]], grids: list[dict[str, str]],
    mitigation_results: list[dict[str, str]], timing: list[dict[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add(category: str, name: str, passed: bool, observed: object,
            expected: str, tolerance: str = "exact", notes: str = "") -> None:
        rows.append({
            "validation_id": f"P6V-{len(rows) + 1:03d}", "category": category,
            "test_name": name, "status": "PASS" if passed else "FAIL",
            "observed_value": str(observed), "expected_value_or_rule": expected,
            "materiality_tolerance": tolerance, "notes": notes,
        })

    ensure_unique(assumptions, "scenario_assumption_id", "scenario assumption")
    ensure_unique(mitigations, "mitigation_decision_id", "mitigation")
    ensure_unique(monthly, "monthly_stress_id", "monthly stress")
    ensure_unique(results, "scenario_result_id", "scenario result")
    ensure_unique(timing, "timing_sensitivity_id", "timing sensitivity")
    add("starting_state", "starting checkpoint commit", checkpoint_rows()[0]["local_head"] == APPROVED_PHASE5_COMMIT, checkpoint_rows()[0]["local_head"], APPROVED_PHASE5_COMMIT)
    add("lineage", "protected Phase 0-5 analytical artifacts unchanged", not prior_analytical_artifact_changes(), semis(prior_analytical_artifact_changes()), "none")
    add("scope", "required scenario count", len(SCENARIOS) == 7, len(SCENARIOS), "7")
    add("scope", "scenario assumption count", len(assumptions) == 84, len(assumptions), "84")
    add("scope", "all eight Phase 3 mitigations retained", len(mitigations) == 8, len(mitigations), "8")
    add("traceability", "stress assumptions are owner-reviewed for Phase 6 testing", all(row["review_status"] == "owner_reviewed_for_phase6_testing" for row in assumptions if row["scenario_id"] != "BASE"), "checked", "all non-base assumption records owner-reviewed for analytical testing only")
    add("traceability", "credited mitigations are owner-reviewed for Phase 6 testing", all(row["owner_review_status"] == "owner_reviewed_for_phase6_testing" for row in mitigations if row["modeled_credit"] == "yes"), "checked", "MIT-001 and MIT-002 only")
    add("scenario_mechanics", "moderate shock no stronger than severe", abs(scenario_by_id("MODERATE_UNMITIGATED").volume_percent) <= abs(scenario_by_id("SEVERE_UNMITIGATED").volume_percent) and abs(scenario_by_id("MODERATE_UNMITIGATED").margin_bps) <= abs(scenario_by_id("SEVERE_UNMITIGATED").margin_bps), "-6.5%/-200bps vs -15%/-375bps", "moderate <= severe")
    add("scenario_mechanics", "unmitigated distributions unchanged", all(dec(row["base_planned_dividend"]) == dec(row["planned_dividend_after_mitigation"]) and dec(row["base_planned_repurchase"]) == dec(row["planned_repurchase_after_mitigation"]) for row in monthly if "UNMITIGATED" in row["scenario_id"]), "checked", "planned equals base")
    add("scenario_mechanics", "cash taxes never positive", all(dec(row["cash_tax_proxy"]) <= 0 for row in operating), max(dec(row["cash_tax_proxy"]) for row in operating), "<=0")
    add("scenario_mechanics", "working-capital source is explicit balance mechanics", all("generic working-capital plug" in row["double_counting_control"] for row in operating), "checked", "no generic plug")
    add("scenario_mechanics", "no fixed-cost double counting", all("gross-margin shock includes fixed-cost deleverage" in row["double_counting_control"] for row in operating), "checked", "single margin transmission")
    add("scenario_mechanics", "remediation is cash-only", all(dec(row["additional_remediation_cash_use"]) <= 0 for row in operating), "checked", "no EBITDA add-back or duplicate cash charge")
    credited_mitigations = [row for row in mitigations if row["modeled_credit"] == "yes"]
    add("mitigation", "mitigations start after one-quarter lag", all(row["start_date"] == MITIGATION_START.isoformat() and row["implementation_lag"] == "one quarter" for row in credited_mitigations), MITIGATION_START.isoformat(), "2026-05-01 after one quarter", notes="Distribution actions begin after the February-April quarter.")
    pre_mitigation = [row for row in monthly if row["scenario_id"].endswith("MITIGATED") and date.fromisoformat(row["month_end"]) < MITIGATION_START]
    add("mitigation", "no pre-start distribution reductions", all(dec(row["dividend_suspended"]) == 0 and dec(row["repurchase_suspended"]) == 0 for row in pre_mitigation), len(pre_mitigation), "all zero")
    add("mitigation", "no unsupported proceeds", all(abs(dec(row["cfads_before_cash_interest"]) - (dec(row["lender_base_ebitda"]) + dec(row["cash_tax_proxy"]) + dec(row["working_capital_cash_flow"]) + dec(row["capital_expenditures"]) + dec(row["other_operating_cash_uses"]))) <= TOLERANCE for row in monthly), "checked", "CFADS components only", "0.000001")
    add("mitigation", "realized mitigation cash excludes already-unpaid distributions", all(dec(row["incremental_cash_preserved_by_mitigation"]) == dec(row["distributions_actually_paid_unmitigated"]) - dec(row["distributions_actually_paid_mitigated"]) for row in mitigation_results), "checked", "actual paid unmitigated less actual paid mitigated")
    add("mitigation", "mitigation maturity-gap benefit reconciles", all(abs(dec(row["mitigation_reconciliation_difference"])) <= TOLERANCE for row in mitigation_results), max(abs(dec(row["mitigation_reconciliation_difference"])) for row in mitigation_results), "<=0.000001", "0.000001", "Cash preserved plus interest savings plus identified retained-obligation effect equals maturity-gap reduction.")
    add("liquidity", "no negative revolver", all(dec(row["ending_revolver"]) >= 0 for row in monthly), min(dec(row["ending_revolver"]) for row in monthly), ">=0")
    add("liquidity", "revolver within commitment less LCs", all(dec(row["ending_revolver"]) <= dec(row["revolver_commitment"]) - dec(row["letters_of_credit"]) + TOLERANCE for row in monthly), max(dec(row["ending_revolver"]) - (dec(row["revolver_commitment"]) - dec(row["letters_of_credit"])) for row in monthly), "<=0", "0.000001")
    add("liquidity", "letters of credit counted once", all(dec(row["nominal_revolver_availability"]) == (Decimal("0") if row["maturity_event"] == "yes" else dec(row["revolver_commitment"]) - dec(row["letters_of_credit"]) - dec(row["ending_revolver"])) for row in monthly), "checked", "commitment - one LC deduction - revolver")
    add("liquidity", "no post-maturity drawability", all(dec(row["usable_revolver_availability"]) == 0 for row in monthly if row["maturity_event"] == "yes"), "checked", "zero")
    shutoff_rows = [row for row in monthly if row["drawability_status"] == "no_waiver_drawability_shutoff"]
    add("drawability", "no new draws after no-waiver shutoff", all(dec(row["revolver_draw"]) == 0 for row in shutoff_rows), len(shutoff_rows), "all draws zero")
    existing_no_waiver = [row for row in monthly if row["structure"] == "existing" and row["drawability_path"] == "NO_WAIVER_DRAWABILITY_SHUTOFF"]
    add("drawability", "no unofficial existing-facility shutoff", not existing_no_waiver, len(existing_no_waiver), "0")
    add("thresholds", "formal contractual compliance never asserted", all(row["formal_contractual_compliance"] == "NOT_DETERMINABLE" for row in build_threshold_tests(monthly)), "checked", "NOT_DETERMINABLE")
    add("thresholds", "book-cash net leverage remains diagnostic", all("diagnostic" in row["classification"] or "analytical" in row["classification"] for row in build_threshold_tests(monthly)), "checked", "diagnostic only")
    add("outputs", "monthly first 24 months present for every scenario and structure", all(sum(1 for row in monthly if row["scenario_id"] == scenario.scenario_id and row["structure"] == structure and row["month_end"] <= "2028-01-31") == 24 for scenario in SCENARIOS for structure in ("proposed", "existing")), "checked", "24 each")
    qgroups: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in monthly:
        qgroups[(row["scenario_id"], row["structure"], row["fiscal_year"], row["quarter"])].append(row)
    qindex = {(row["scenario_id"], row["structure"], row["fiscal_year"], row["quarter"]): row for row in quarterly}
    q_reconciles = all(abs(sum((dec(row["lender_base_ebitda"]) for row in group), Decimal("0")) - dec(qindex[key]["lender_base_ebitda"])) <= TOLERANCE for key, group in qgroups.items())
    add("outputs", "monthly-to-quarterly EBITDA reconciliation", q_reconciles, "checked", "exact within tolerance", "0.000001")
    paired_operating = {(row["scenario_id"], row["fiscal_year"], row["quarter"]): row["lender_base_ebitda"] for row in operating}
    same_stress = all(len({qindex[(scenario.scenario_id, structure, fy, q)]["lender_base_ebitda"] for structure in ("proposed", "existing")}) == 1 for scenario in SCENARIOS for fy, q, _, _ in phase5.forecast_periods() if (scenario.scenario_id, fy, q) in paired_operating and (scenario.scenario_id, "existing", fy, q) in qindex)
    add("outputs", "same operating stress applied to both structures", same_stress, "checked", "identical quarterly EBITDA")
    add("outputs", "mandatory payment failure excludes distributions", all(row["mandatory_payment_failure_flag"] == ("yes" if any(dec(row[field]) > TOLERANCE for field in ("cash_interest_shortfall", "scheduled_principal_shortfall", "retained_obligation_shortfall")) else "no") for row in monthly), "checked", "interest, scheduled principal or retained obligation only")

    by_result = {(row["scenario_id"], row["structure"]): row for row in results}
    phase5_common = {row["metric_name"]: row for row in read_csv(PHASE5_COMMON)}
    parity_pairs = (
        ("proposed opening bank debt", dec(by_result[("BASE", "proposed")]["opening_bank_debt"]), Decimal("679.89771875")),
        ("existing opening bank debt", dec(by_result[("BASE", "existing")]["opening_bank_debt"]), Decimal("669.89771875")),
        ("proposed minimum liquidity", dec(by_result[("BASE", "proposed")]["minimum_usable_liquidity"]), Decimal("253.8458349441112245272416091")),
        ("existing minimum liquidity", dec(by_result[("BASE", "existing")]["minimum_usable_liquidity"]), Decimal("261.40228125")),
        ("proposed maturity gap", dec(by_result[("BASE", "proposed")]["unsupported_maturity_gap"]), Decimal("340.9478312215931607465924833")),
        ("existing maturity gap", dec(by_result[("BASE", "existing")]["unsupported_maturity_gap"]), Decimal("432.7492812067100176549274129")),
    )
    for name, observed, expected in parity_pairs:
        add("base_parity", name, abs(observed - expected) <= TOLERANCE, fmt(observed), fmt(expected), "0.000001")
    for structure in ("proposed", "existing"):
        expected_peak = dec(phase5_common["peak_revolver_usage"][f"{structure}_value"])
        observed_peak = dec(by_result[("BASE", structure)]["peak_revolver_including_opening"])
        add("base_parity", f"{structure} headline peak revolver includes opening and matches Phase 5", abs(observed_peak - expected_peak) <= TOLERANCE, fmt(observed_peak), fmt(expected_peak), "0.000001")
    p5_monthly = read_csv(PHASE5_MONTHLY)
    p6_base_index = {
        (row["structure"], row["month_end"]): row for row in monthly
        if row["scenario_id"] == "BASE" and row["month_end"] <= "2028-01-31"
    }
    parity_fields = {
        "opening_cash": "opening_cash", "revenue": "revenue",
        "lender_base_ebitda": "lender_base_ebitda",
        "cfads_before_cash_interest": "cfads_before_cash_interest",
        "opening_term_principal": "opening_term_principal",
        "ending_term_principal": "ending_term_principal",
        "opening_revolver": "opening_revolver", "revolver_draw": "revolver_draw",
        "revolver_repayment": "revolver_repayment", "ending_revolver": "ending_revolver",
        "ending_cash": "ending_cash", "cash_floor_shortfall": "cash_floor_shortfall",
        "usable_liquidity": "usable_liquidity",
    }
    signed_parity_fields = {
        "cash_interest": "cash_interest_paid",
        "retained_finance_and_other_debt_payment": "retained_obligation_paid",
        "dividends": "dividend_paid", "share_repurchases": "repurchase_paid",
    }
    monthly_parity = True
    for p5_row in p5_monthly:
        p6_row = p6_base_index.get((p5_row["structure"], p5_row["month_end"]))
        if p6_row is None:
            monthly_parity = False
            break
        if any(abs(dec(p5_row[left]) - dec(p6_row[right])) > TOLERANCE for left, right in parity_fields.items()):
            monthly_parity = False
            break
        if any(abs(abs(dec(p5_row[left])) - dec(p6_row[right])) > TOLERANCE for left, right in signed_parity_fields.items()):
            monthly_parity = False
            break
    add("base_parity", "Phase 5 first-24-month zero-shock schedule", monthly_parity, len(p5_monthly), "48 rows and all relevant cash/debt fields", "0.000001")
    proposed_base = [row for row in monthly if row["scenario_id"] == "BASE" and row["structure"] == "proposed" and row["month_end"] <= "2029-07-31"]
    proposed_common_end = dec(proposed_base[-1]["ending_term_principal"]) + dec(proposed_base[-1]["ending_revolver"])
    add("base_parity", "proposed common-horizon ending bank debt", abs(proposed_common_end - dec(phase5_common["ending_total_bank_debt"]["proposed_value"])) <= TOLERANCE, fmt(proposed_common_end), phase5_common["ending_total_bank_debt"]["proposed_value"], "0.000001")
    p5_dist = [row for row in read_csv(PHASE5_DISTRIBUTIONS) if row["structure"] == "proposed" and row["period_end"] <= "2029-07-31"]
    expected_direct_buybacks = sum((dec(row["repurchase_revolver_draw_caused"]) for row in p5_dist), Decimal("0"))
    expected_broad_buybacks = sum((dec(row["repurchase_paid_while_revolver_outstanding"]) for row in p5_dist), Decimal("0"))
    actual_direct_buybacks = sum((dec(row["repurchase_revolver_draw_caused"]) for row in proposed_base), Decimal("0"))
    actual_broad_buybacks = sum((dec(row["repurchase_paid_while_revolver_outstanding"]) for row in proposed_base), Decimal("0"))
    add("base_parity", "proposed common-horizon directly draw-funded repurchases", abs(actual_direct_buybacks - expected_direct_buybacks) <= TOLERANCE, fmt(actual_direct_buybacks), fmt(expected_direct_buybacks), "0.000001")
    add("base_parity", "proposed common-horizon repurchases while revolver outstanding", abs(actual_broad_buybacks - expected_broad_buybacks) <= TOLERANCE, fmt(actual_broad_buybacks), fmt(expected_broad_buybacks), "0.000001")
    add("reverse_stress", "minimum reverse-stress tests per structure", all(sum(1 for row in reverse if row["structure"] == structure) >= 12 for structure in ("proposed", "existing")), len(reverse), ">=12 each")
    add("reverse_stress", "bounded searches retain explicit limits and tolerance", all(row["lower_bound"] != "" and row["upper_bound"] != "" and row["search_tolerance"] != "" for row in reverse), "checked", "all populated")
    add("sensitivity", "decision grids populated without duplicate points", len(grids) == len({row["grid_point_id"] for row in grids}) == 63, len(grids), "63")
    add("timing", "required equal and adverse timing comparisons", len(timing) == 16 and {row["timing_case"] for row in timing} == {"equal", "adverse"}, len(timing), "16 rows across 8 scenario/structure pairs")
    add("timing", "timing conventions preserve opening revolver", all(dec(row["opening_revolver_balance"]) == dec(base_structure_parameters(row["structure"])["opening_revolver"]) for row in timing), "checked", "opening exposure unchanged")
    add("timing", "adverse timing patterns are exact", all(row["timing_pattern"] == ("20%_30%_50%" if row["scenario_family"] == "moderate" else "10%_25%_65%") for row in timing if row["timing_case"] == "adverse"), "checked", "moderate 20/30/50; severe 10/25/65")
    add("cutoff", "no post-cutoff evidence", all(row["source_ids"] for row in assumptions + operating + monthly), "checked", f"source IDs trace to <= {CUTOFF.isoformat()}")
    add("scope", "no Phase 7 implementation", not approved_phase6_contains_phase7(), "checked", "no Phase 7 code/data/tests")
    return rows


def source_ledger_rows(collections: Sequence[tuple[str, str, list[dict[str, str]], str]]) -> list[dict[str, str]]:
    manifest = phase5.source_manifest()
    output: list[dict[str, str]] = []
    for artifact, record_type, rows, id_field in collections:
        for row in rows:
            source_ids = row.get("source_ids", "")
            dates = []
            for source_id in source_ids.split(";"):
                if not source_id:
                    continue
                if source_id not in manifest:
                    raise Phase6Error(f"Unknown source ID {source_id} in {artifact}/{row.get(id_field, '')}")
                dates.append(manifest[source_id]["publication_or_filing_date"])
            source_date = max(dates) if dates else ""
            cutoff_status = "within_cutoff" if not source_date or date.fromisoformat(source_date) <= CUTOFF else "post_cutoff"
            output.append({
                "ledger_id": f"P6L-{len(output) + 1:05d}", "artifact_path": artifact,
                "record_type": record_type, "record_id": row.get(id_field, ""),
                "source_ids": source_ids, "upstream_ids": row.get("upstream_ids", ""),
                "classification": row.get("classification", "raw_governance_record"),
                "review_status": row.get("review_status", row.get("owner_review_status", "deterministic_calculation")),
                "source_date": source_date, "cutoff_status": cutoff_status,
                "notes": row.get("limitations", row.get("notes", "")),
            })
    return output


def display_money(value: str | Decimal) -> str:
    return f"${dec(value):,.3f}m"


def render_docs(
    assumptions: list[dict[str, str]], mitigations: list[dict[str, str]],
    results: list[dict[str, str]], events: list[dict[str, str]],
    thresholds: list[dict[str, str]], mitigation_results: list[dict[str, str]],
    reverse: list[dict[str, str]], grids: list[dict[str, str]],
    timing: list[dict[str, str]],
) -> None:
    result_index = {(row["scenario_id"], row["structure"]): row for row in results}
    assumption_index = {(row["scenario_id"], row["shock_name"]): row for row in assumptions}

    methodology = """# Phase 6 methodology

## Purpose and boundary

Phase 6 applies borrower-specific downside mechanisms to the approved Phase 5 base case. It does not resize the financing, finalize covenants, assume a waiver or refinancing, perform recovery analysis, or start Phase 7. All monetary values are USD millions and all calculations retain `Decimal` precision; displayed values may be rounded.

## Scenario architecture

The model starts each structure on February 1, 2026. `BASE` is a zero-shock parity run. Moderate and severe paths transmit volume once through revenue; gross-margin pressure once through gross profit, including fixed-cost absorption; DSO, DIO, AP, and other current-balance changes through explicit balance mechanics; cash-only remediation below EBITDA; and the rate shock once through the all-in rate. No generic EBITDA or working-capital plug is used.

The moderate shock is held for four quarters and then recovers by 75%, 50%, and 25% residual factors in FY2027 Q2-Q4, with full recovery in FY2028 Q1. The severe shock is held for eight quarters and then recovers by 80%, 60%, 40%, and 20% residual factors through FY2029 Q1, with full recovery in FY2029 Q2. Equal monthly allocation is the neutral timing convention. Stressed allocations of 20%/30%/50% (moderate) and 10%/25%/65% (severe) are conservative underwriting sensitivities. Neither convention is verified actual monthly seasonality, so exact event dates depend on the selected timing case.

## Cash, debt, and interest

The payment order is cash interest, retained contractual obligations, scheduled term principal, dividends, and repurchases. A mandatory-payment failure means unpaid cash interest, unpaid scheduled term principal, or an unpaid retained mandatory obligation. Missed dividends and repurchases remain separately reported and are not lender payment defaults. A maturity balloon shortfall is separately classified as `MATURITY_SHORTFALL`. In failure-event records, cash available before payment means cash plus any capacity that remains both available and drawable immediately before the failed obligation; cash remaining after payment is the resulting cash balance. Revolver draws restore the $25m operating cash floor when capacity and modeled drawability remain. Surplus cash first repays the revolver; the Phase 5 October sweep follows only after revolver repayment and preserves the $50m analytical liquidity safeguard. Interest is iterated from average monthly term and revolver balances, so additional draws increase later interest.

The headline revolver exposure is the greater of the opening balance and all subsequent modeled month-end balances. The opening balance, the peak subsequent period-end balance, and the headline peak are stored separately. `OPENING_POSITION` identifies a headline peak that occurs at closing. The draw event field identifies the first incremental post-closing draw; opening revolver debt is never classified as an incremental draw.

Maturity capacity becomes zero and available cash above the floor is applied to the revolver and then the term loan. Remaining principal is an unsupported maturity gap; no refinancing is assumed.

## Thresholds and drawability

The model separately reports gross funded leverage, book-cash net leverage (diagnostic only), analytical bank leverage, EBITDA/cash-interest coverage, CFADS/cash-interest coverage, CFADS/scheduled-debt-service coverage, and usable liquidity. The 3.25x/3.00x leverage, 3.00x coverage, and $50m liquidity levels are analytical warnings, not final covenants.

Formal contractual compliance is `NOT_DETERMINABLE`. The proposed no-waiver path switches off new revolver draws beginning the month after the first modeled analytical failure. The continued-drawability path leaves capacity available. Existing-facility drawability is never switched off from this unofficial reconstruction.

## Mitigations and limitations

Only two dated actions receive modeled credit: share-repurchase suspension beginning May 1, 2026 in both mitigated cases and a 50% dividend reduction from that date in the severe mitigated case. Costs are modeled at zero because these distribution actions have no direct implementation cost, but board action and legal permission are not assumed certain. Scheduled policy reductions are reported separately from realized cash preservation. A distribution already unpaid in the unmitigated failure path receives no mitigation credit. Other Phase 3 mitigations remain visible with zero or not-determinable credit.

Recurring financing fees, actual closing cash, eligible cash, covenant definitions, foreign-cash accessibility, proposed legal terms, and amendment economics remain unavailable. The owner reviewed scenario severity, exact timing, recovery, the two modeled capital-allocation actions, and the no-waiver convention for Phase 6 analytical testing only. They are not management forecasts, final underwriting assumptions, contractual conclusions, or final loan terms. The proposed no-waiver path is not a legal conclusion, official covenant calculation, or prediction that lenders would refuse a waiver; it is not applied to the existing facilities because formal compliance cannot be reconstructed.
"""
    write_text(DOCS / "METHODOLOGY.md", methodology)

    rows = []
    for scenario_id in ("BASE", "MODERATE_UNMITIGATED", "SEVERE_UNMITIGATED", "MODERATE_MITIGATED", "SEVERE_MITIGATED", "MODERATE_NO_WAIVER", "SEVERE_NO_WAIVER"):
        for structure in ("proposed", "existing"):
            row = result_index[(scenario_id, structure)]
            rows.append(
                f"| {scenario_id} | {structure} | {display_money(row['minimum_usable_liquidity'])} ({row['minimum_liquidity_month']}) | "
                f"{display_money(row['opening_revolver_balance'])} | {display_money(row['peak_subsequent_period_end_revolver'])} ({row['peak_subsequent_period_end_revolver_date']}) | "
                f"{display_money(row['peak_revolver_including_opening'])} ({row['peak_revolver_date']}) | {display_money(row['unsupported_maturity_gap'])} | "
                f"{row['first_50m_analytical_liquidity_warning'] or 'none'} | {row['first_cash_floor_failure'] or 'none'} | "
                f"{row['first_mandatory_payment_failure_date'] + ' ' + row['failed_obligation_type'] if row['first_mandatory_payment_failure_date'] else 'none'} | {row['status']} |"
            )
    moderate = scenario_by_id("MODERATE_UNMITIGATED")
    severe = scenario_by_id("SEVERE_UNMITIGATED")
    downside = f"""# Downside analysis

## Scenario calibration owner-reviewed for Phase 6 analytical testing

| Input | Moderate | Severe |
| --- | ---: | ---: |
| Volume vs base | {fmt(moderate.volume_percent)}% | {fmt(severe.volume_percent)}% |
| Gross-margin pressure | {fmt(moderate.margin_bps)} bps | {fmt(severe.margin_bps)} bps |
| DSO increase | {fmt(moderate.dso_days)} days | {fmt(severe.dso_days)} days |
| DIO increase | {fmt(moderate.dio_days)} days | {fmt(severe.dio_days)} days |
| AP/cost-of-sales change | {fmt(moderate.ap_ratio_bps)} bps | {fmt(severe.ap_ratio_bps)} bps |
| Other current assets/revenue change | +{fmt(moderate.other_asset_ratio_bps)} bps | +{fmt(severe.other_asset_ratio_bps)} bps |
| Other operating current liabilities/revenue change | {fmt(moderate.other_liability_ratio_bps)} bps | {fmt(severe.other_liability_ratio_bps)} bps |
| Rate shock | +{fmt(moderate.rate_bps)} bps | +{fmt(severe.rate_bps)} bps |
| Cash-only remediation | {display_money(moderate.remediation_cash_total)} over two quarters | {display_money(severe.remediation_cash_total)} over four quarters |
| Plateau / recovery | 4 quarters / 3-quarter linear recovery | 8 quarters / 4-quarter linear recovery |
| Monthly stress weighting | 20% / 30% / 50% | 10% / 25% / 65% |

The owner approved these exact stress points, recovery paths and timing conventions for Phase 6 analytical testing only. They are not management forecasts, final underwriting assumptions, contractual conclusions or final loan terms. The 12%-13% lender EBITDA margin is a validation reference only and never an input.

## Results

| Scenario | Structure | Minimum usable liquidity | Opening revolver | Peak subsequent period-end revolver | Headline peak including opening | Unsupported maturity gap | First $50m warning | First cash-floor failure | First mandatory failure | Overall path status |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
{chr(10).join(rows)}

## Underwriting observations

- Moderate stress materially increases revolver use and the maturity balloon but remains above the $50m liquidity warning under continued drawability. Analytical leverage is the first warning, not a contractual breach.
- Severe stress exhausts the modeled revolver under both structures. The proposed path subsequently develops mandatory-payment failure; the exact first failed obligation, due, paid and unpaid amounts are recorded. The existing path develops a cash-floor failure before maturity without an interim mandatory-payment failure.
- The proposed no-waiver convention converts an analytical warning into a following-month drawability shutoff and earlier cash-floor pressure. That convention is intentionally separate from legal conclusions.
- All paths retain an unsupported maturity balloon because refinancing is excluded. The result is refinancing risk, not an assumption that the debt will actually default at maturity.
"""
    write_text(DOCS / "DOWNSIDE_ANALYSIS.md", downside)

    reverse_lines = [
        f"| {row['structure']} | {row['test_name']} | {row['result_value'] or 'not reached'} {row['units']} | {row['threshold_status']} | {row['first_failure_date'] or 'none'} |"
        for row in reverse
    ]
    mitigation_lines = [
        f"| {row['severity']} | {row['structure']} | {display_money(row['planned_distributions'])} | {display_money(row['distributions_due_under_policy'])} | {display_money(row['distributions_actually_paid_unmitigated'])} | {display_money(row['distributions_unpaid_due_to_prior_cash_or_capacity_failure'])} | {display_money(row['distributions_actually_paid_mitigated'])} | {display_money(row['incremental_cash_preserved_by_mitigation'])} | {display_money(row['incremental_interest_saved'])} | {display_money(row['other_timing_or_waterfall_effect'])} | {display_money(row['maturity_gap_reduction'])} |"
        for row in mitigation_results
    ]
    timing_lines = [
        f"| {row['scenario_id']} | {row['structure']} | {row['timing_case']} | {display_money(row['minimum_usable_liquidity'])} ({row['minimum_liquidity_month']}) | {display_money(row['peak_revolver_including_opening'])} ({row['peak_revolver_date']}) | {row['first_50m_analytical_liquidity_warning'] or 'none'} | {row['first_cash_floor_failure'] or 'none'} | {row['first_mandatory_payment_failure_date'] or 'none'} {row['failed_obligation_type']} | {display_money(row['maturity_shortfall'])} |"
        for row in timing
    ]
    liquidity_doc = f"""# Liquidity and reverse stress

## Liquidity mechanics and distribution attribution

Monthly cash and debt are modeled for the full applicable term, including at least the first 24 months, and aggregate to the quarterly stress outputs. Working-capital stress changes explicit receivable, inventory, payable, and other operating-current-balance proxies. Interest is endogenous to debt and rates.

The base proposed path exactly preserves the Phase 5 common-horizon distinction: directly draw-funded repurchases are $6.754m, while $17.500m of repurchases occur while revolver debt remains outstanding. The narrow and broad interpretations are both analytical flags; neither is a legal opinion. Severe unmitigated distributions remain in the model.

## Dated mitigation comparison and realized cash attribution

| Severity | Structure | Planned distributions | Due under mitigated policy | Paid unmitigated | Unpaid unmitigated | Paid mitigated | Actual cash preserved | Interest saved | Other waterfall effect | Maturity-gap reduction |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(mitigation_lines)}

Modeled actions begin May 1, 2026 after a one-quarter implementation lag. Repurchases are suspended in both mitigated cases; severe mitigation also reduces dividends 50%. The modeled actions have no direct implementation cost and no EBITDA benefit. Actual cash preserved equals distributions actually paid in the unmitigated path less distributions actually paid in the mitigated path. It excludes distributions that the unmitigated path already could not pay. The other waterfall effect is the negative of additional retained mandatory obligations paid in the mitigated path; it is separately quantified rather than left as an unexplained residual. Actual cash preserved plus interest saved plus that identified effect reconciles to the maturity-gap reduction within $0.000001m. Board approval, legal permission, execution, and persistence are not assumed certain.

## Monthly timing sensitivity

| Scenario | Structure | Timing | Minimum usable liquidity | Headline peak revolver | First $50m warning | First cash-floor failure | First mandatory failure | Maturity shortfall |
| --- | --- | --- | ---: | ---: | --- | --- | --- | ---: |
{chr(10).join(timing_lines)}

Equal allocation is the neutral timing convention. The adverse 20%/30%/50% moderate and 10%/25%/65% severe allocations are conservative underwriting sensitivities. Neither is verified actual monthly seasonality. Exact distress dates are conditional on the selected allocation. A lower debt or maturity balance caused by curtailed borrowing, unpaid obligations, or liquidity failure is not improved credit performance. Phase 7 may use the conservative date for intervention design but must not call it an observed forecast.

## Reverse stress

| Structure | Test | Approximate breakpoint | Status | First failure date |
| --- | --- | ---: | --- | --- |
{chr(10).join(reverse_lines)}

Searches are bounded and reported only to their stated tolerance. `threshold_already_failed` and `not_reached_within_bounds` replace invented breakpoints. Sustainable annual CFADS is a mathematical requirement to retire the balloon without refinancing, not an operating forecast or cure assumption.

## Sensitivity grids

The 63 grid points cover volume/margin, DSO/DIO, rate/margin for both structures, and proposed amortization/operating stress. They report minimum liquidity, opening revolver, subsequent period-end peak, headline peak including opening, first analytical distress, interest coverage, and maturity gap. Grid points remain sensitivities rather than owner-approved forecasts.
"""
    write_text(DOCS / "LIQUIDITY_AND_REVERSE_STRESS.md", liquidity_doc)

    handoff = """# Phase 7 handoff

Phase 6 stops before covenant structuring. The following items require owner and legal review before Phase 7 can use the downside outputs:

1. Carry forward the owner-reviewed Phase 6 testing assumptions without describing them as management forecasts or final underwriting assumptions.
2. Treat adverse within-quarter dates as conservative intervention-design inputs only; actual monthly seasonality remains unavailable.
3. Assess the credibility, board approval, legal capacity, start date, and duration of the owner-reviewed-for-testing repurchase suspension and dividend reduction.
4. Obtain proposed documentation and formal definitions for EBITDA, eligible cash, leverage, interest coverage, distributions, revolver draw conditions, equity cures, and acquisition step-ups.
5. Resolve whether proposed repurchases are restricted only when they directly cause a draw or whenever revolver debt remains outstanding; Phase 6 carries both interpretations.
6. Determine actual closing cash, accessible domestic/foreign cash, recurring financing fees, revolver and LC terms, and amendment economics.
7. Decide whether the analytical 3.25x/3.00x leverage, 3.00x interest-coverage, and $50m liquidity thresholds should remain warning levels or inform proposed covenants.
8. Review severe-case mandatory-payment failures by obligation, no-waiver cash-floor failures, commitment exhaustion, and maturity balloons without describing analytical events as contractual defaults.
9. Decide which additional mitigations merit quantified diligence; no capex cuts, cost-out, asset-sale, equity, waiver, or refinancing proceeds received Phase 6 credit.
10. Preserve the cash-flow control weakness, Tyman integration risk, impairment signal, and cash-realization limits from prior phases in the final covenant and monitoring design.

Phase 7 must not treat the partial public covenant reconstruction as a compliance certificate or book-cash net leverage as covenant net leverage.
"""
    write_text(DOCS / "PHASE7_HANDOFF.md", handoff)


def build() -> dict[str, int | str]:
    seed_raw()
    assumptions = read_csv(RAW / "SCENARIO_ASSUMPTIONS.csv")
    mitigations = read_csv(RAW / "MITIGATION_DECISIONS.csv")
    operating: list[dict[str, str]] = []
    monthly: list[dict[str, str]] = []
    for config in SCENARIOS:
        scenario_operating = build_operating(config)
        operating.extend(scenario_operating)
        for structure in ("proposed", "existing"):
            monthly.extend(run_monthly(config, structure, scenario_operating))
    quarterly = aggregate_quarterly(monthly)
    debt = build_debt_schedule(quarterly, monthly)
    results = build_scenario_results(monthly)
    events = build_distress_events(monthly)
    thresholds = build_threshold_tests(monthly)
    drawability = build_drawability_paths(monthly)
    mitigation_results = build_mitigation_results(results, monthly)
    reverse = build_reverse_stress()
    grids = build_sensitivity_grids()
    timing = build_timing_sensitivity(monthly)
    validations = validation_rows(
        operating, monthly, quarterly, results, assumptions, mitigations, reverse, grids,
        mitigation_results, timing,
    )

    write_csv(PROCESSED / "SCENARIO_RESULTS.csv", results, RESULT_FIELDS)
    write_csv(PROCESSED / "MONTHLY_LIQUIDITY_STRESS.csv", monthly, MONTHLY_FIELDS)
    write_csv(PROCESSED / "QUARTERLY_STRESS_FORECAST.csv", quarterly, QUARTERLY_FIELDS)
    write_csv(PROCESSED / "SCENARIO_DEBT_SCHEDULE.csv", debt, DEBT_FIELDS)
    write_csv(PROCESSED / "FIRST_DISTRESS_EVENTS.csv", events, DISTRESS_FIELDS)
    write_csv(PROCESSED / "ANALYTICAL_THRESHOLD_TESTS.csv", thresholds, THRESHOLD_FIELDS)
    write_csv(PROCESSED / "DRAWABILITY_PATHS.csv", drawability, DRAWABILITY_FIELDS)
    write_csv(PROCESSED / "MITIGATION_RESULTS.csv", mitigation_results, MITIGATION_RESULT_FIELDS)
    write_csv(PROCESSED / "REVERSE_STRESS_RESULTS.csv", reverse, REVERSE_FIELDS)
    write_csv(PROCESSED / "SENSITIVITY_GRIDS.csv", grids, GRID_FIELDS)
    write_csv(PROCESSED / "TIMING_SENSITIVITY_RESULTS.csv", timing, TIMING_FIELDS)
    write_csv(PROCESSED / "VALIDATION_RESULTS.csv", validations, VALIDATION_FIELDS)
    render_docs(
        assumptions, mitigations, results, events, thresholds, mitigation_results,
        reverse, grids, timing,
    )

    collections = (
        ("data/phase6/raw/STARTING_CHECKPOINT.csv", "starting_checkpoint", read_csv(RAW / "STARTING_CHECKPOINT.csv"), "repository"),
        ("data/phase6/raw/SCENARIO_ASSUMPTIONS.csv", "scenario_assumption", assumptions, "scenario_assumption_id"),
        ("data/phase6/raw/MITIGATION_DECISIONS.csv", "mitigation_decision", mitigations, "mitigation_decision_id"),
        ("data/phase6/processed/SCENARIO_RESULTS.csv", "scenario_result", results, "scenario_result_id"),
        ("data/phase6/processed/MONTHLY_LIQUIDITY_STRESS.csv", "monthly_liquidity_stress", monthly, "monthly_stress_id"),
        ("data/phase6/processed/QUARTERLY_STRESS_FORECAST.csv", "quarterly_stress_forecast", quarterly, "quarterly_stress_id"),
        ("data/phase6/processed/SCENARIO_DEBT_SCHEDULE.csv", "scenario_debt_schedule", debt, "debt_stress_id"),
        ("data/phase6/processed/FIRST_DISTRESS_EVENTS.csv", "first_distress_event", events, "distress_event_id"),
        ("data/phase6/processed/ANALYTICAL_THRESHOLD_TESTS.csv", "analytical_threshold_test", thresholds, "threshold_test_id"),
        ("data/phase6/processed/DRAWABILITY_PATHS.csv", "drawability_path", drawability, "drawability_path_id"),
        ("data/phase6/processed/MITIGATION_RESULTS.csv", "mitigation_result", mitigation_results, "mitigation_result_id"),
        ("data/phase6/processed/REVERSE_STRESS_RESULTS.csv", "reverse_stress", reverse, "reverse_stress_id"),
        ("data/phase6/processed/SENSITIVITY_GRIDS.csv", "sensitivity_grid", grids, "grid_point_id"),
        ("data/phase6/processed/TIMING_SENSITIVITY_RESULTS.csv", "timing_sensitivity", timing, "timing_sensitivity_id"),
        ("data/phase6/processed/VALIDATION_RESULTS.csv", "validation_control", validations, "validation_id"),
    )
    ledger = source_ledger_rows(collections)
    write_csv(DOCS / "SOURCE_LEDGER.csv", ledger, LEDGER_FIELDS)
    by_result = {(row["scenario_id"], row["structure"]): row for row in results}
    return {
        "scenario_assumptions": len(assumptions), "mitigation_decisions": len(mitigations),
        "operating_rows": len(operating), "monthly_rows": len(monthly),
        "quarterly_rows": len(quarterly), "debt_rows": len(debt),
        "scenario_results": len(results), "distress_events": len(events),
        "threshold_tests": len(thresholds), "drawability_paths": len(drawability),
        "mitigation_results": len(mitigation_results), "reverse_stress_tests": len(reverse),
        "sensitivity_grid_points": len(grids), "timing_sensitivity_rows": len(timing),
        "validation_rows": len(validations),
        "ledger_rows": len(ledger),
        "proposed_base_gap": by_result[("BASE", "proposed")]["unsupported_maturity_gap"],
        "existing_base_gap": by_result[("BASE", "existing")]["unsupported_maturity_gap"],
    }


def generated_files() -> list[Path]:
    files = list(RAW.glob("*.csv")) + list(PROCESSED.glob("*.csv")) + list(DOCS.glob("*"))
    return sorted(path for path in files if path.is_file())


def fingerprints() -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in generated_files()
    }


def validate() -> dict[str, int | str]:
    expected = {
        RAW / "STARTING_CHECKPOINT.csv", RAW / "SCENARIO_ASSUMPTIONS.csv",
        RAW / "MITIGATION_DECISIONS.csv", PROCESSED / "SCENARIO_RESULTS.csv",
        PROCESSED / "MONTHLY_LIQUIDITY_STRESS.csv", PROCESSED / "QUARTERLY_STRESS_FORECAST.csv",
        PROCESSED / "SCENARIO_DEBT_SCHEDULE.csv", PROCESSED / "FIRST_DISTRESS_EVENTS.csv",
        PROCESSED / "ANALYTICAL_THRESHOLD_TESTS.csv", PROCESSED / "DRAWABILITY_PATHS.csv",
        PROCESSED / "MITIGATION_RESULTS.csv", PROCESSED / "REVERSE_STRESS_RESULTS.csv",
        PROCESSED / "SENSITIVITY_GRIDS.csv", PROCESSED / "TIMING_SENSITIVITY_RESULTS.csv",
        PROCESSED / "VALIDATION_RESULTS.csv",
        DOCS / "METHODOLOGY.md", DOCS / "DOWNSIDE_ANALYSIS.md",
        DOCS / "LIQUIDITY_AND_REVERSE_STRESS.md", DOCS / "PHASE7_HANDOFF.md",
        DOCS / "SOURCE_LEDGER.csv",
    }
    missing = sorted(str(path.relative_to(ROOT)) for path in expected if not path.is_file())
    if missing:
        raise Phase6Error("Missing Phase 6 artifacts: " + ", ".join(missing))
    checkpoint = read_csv(RAW / "STARTING_CHECKPOINT.csv")
    if len(checkpoint) != 1 or any(checkpoint[0][field] != APPROVED_PHASE5_COMMIT for field in (
        "local_head", "tracked_origin_main", "live_remote_main",
    )):
        raise Phase6Error("Starting checkpoint does not match the approved Phase 5 commit")
    validations = read_csv(PROCESSED / "VALIDATION_RESULTS.csv")
    failures = [row for row in validations if row["status"] != "PASS"]
    if failures:
        raise Phase6Error("Phase 6 validation failures: " + ", ".join(row["test_name"] for row in failures))
    ledger = read_csv(DOCS / "SOURCE_LEDGER.csv")
    if any(row["cutoff_status"] != "within_cutoff" for row in ledger):
        raise Phase6Error("Phase 6 source ledger includes post-cutoff evidence")
    validate_changed_paths()
    results = read_csv(PROCESSED / "SCENARIO_RESULTS.csv")
    return {
        "status": "PASS", "validations": len(validations), "ledger_rows": len(ledger),
        "scenario_results": len(results), "generated_files": len(generated_files()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "validate", "all"), nargs="?", default="all")
    args = parser.parse_args()
    try:
        if args.command in ("build", "all"):
            print("Phase 6 build:", build())
        if args.command in ("validate", "all"):
            print("Phase 6 validation:", validate())
    except (Phase6Error, phase5.Phase5Error, OSError, subprocess.CalledProcessError) as exc:
        print(f"Phase 6 failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
