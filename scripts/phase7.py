#!/usr/bin/env python3
"""Build and validate Phase 7 covenant mechanics and final sizing outputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import phase6  # noqa: E402


APPROVED_PHASE6_COMMIT = "b5554f8848e1622ae1de1e371b974c886f3e33db"
APPROVED_PHASE7_COMMIT = "58e1b83a644021b785162d851e1539dd65dff9f5"
CUTOFF = date(2025, 12, 15)
RAW = ROOT / "data" / "phase7" / "raw"
PROCESSED = ROOT / "data" / "phase7" / "processed"
DOCS = ROOT / "docs" / "phase-7"
PHASE2_BRIDGES = ROOT / "data" / "phase2" / "processed" / "earnings_bridges.csv"
PHASE5_ASSUMPTIONS = ROOT / "data" / "phase5" / "raw" / "MODEL_ASSUMPTIONS.csv"
PHASE5_COMMON_HORIZON = ROOT / "data" / "phase5" / "processed" / "COMMON_HORIZON_COMPARISON.csv"
PHASE6_RESULTS = ROOT / "data" / "phase6" / "processed" / "SCENARIO_RESULTS.csv"
TOLERANCE = Decimal("0.000001")
MONEY = "USD_millions"
N_D = "not_determinable"
N_D_VALUE = "N/D"
N_M = "N/M"
REVIEW = "owner_reviewed"
OWNER_REVIEW_NOTE = (
    "Approved for the Phase 7 public-information underwriting structure; not an actual "
    "lender commitment, final legal drafting, official covenant compliance calculation, "
    "or evidence that unresolved funding sources or private information exist; subject to "
    "the stated conditions and diligence gaps."
)
COMMON_HORIZON_END = date(2029, 7, 31)
REFERENCE_CLOSING_USES = Decimal("679.89771875")


class Phase7Error(RuntimeError):
    """Raised when a material Phase 7 control fails."""


@dataclass(frozen=True)
class StructureCandidate:
    candidate_id: str
    name: str
    alternative_type: str
    structure: str
    opening_term: Decimal | None
    opening_revolver: Decimal | None
    revolver_commitment: Decimal | None
    letters_of_credit: Decimal | None
    amortization_percent: Decimal | None
    maturity: date | None
    all_in_rate_percent: Decimal | None
    cash_contribution: Decimal | None
    ecb_sweep_percent: Decimal | None
    quantitative_status: str
    selection_status: str
    rationale: str
    limitations: str


CHECKPOINT_FIELDS = (
    "repository", "branch", "local_head", "tracked_origin_main",
    "live_remote_main", "ahead", "behind", "working_tree_clean_before_work",
    "verified_on", "notes",
)
STRUCTURE_FIELDS = (
    "candidate_id", "candidate_name", "alternative_type", "quantitative_status",
    "selection_status", "opening_term_principal", "opening_revolver",
    "opening_bank_debt", "retained_other_funded_debt", "opening_gross_funded_debt",
    "term_commitment", "revolver_commitment", "total_term_plus_revolver_commitments",
    "letters_of_credit", "opening_revolver_availability", "opening_usable_liquidity",
    "undrawn_term_commitment",
    "unused_term_commitment_treatment", "required_non_debt_contribution",
    "reference_closing_uses", "sources_uses_control", "annual_amortization_percent",
    "annual_scheduled_term_principal", "maturity_date", "all_in_rate_percent",
    "excess_cash_flow_sweep_percent", "source_ids", "upstream_ids",
    "review_status", "rationale", "limitations",
)
COVENANT_PROPOSAL_FIELDS = (
    "proposal_id", "framework", "metric_or_term", "definition", "numerator",
    "denominator", "threshold", "units", "effective_start", "effective_end",
    "testing_frequency", "cash_netting", "drawn_revolver_treatment", "inclusions",
    "exclusions", "pro_forma_rules", "exceptions", "cures", "stepups",
    "draw_condition_effect", "reporting_requirement", "source_ids", "upstream_ids",
    "evidence_status", "owner_review_status", "limitations",
)
OWNER_DECISION_FIELDS = (
    "decision_id", "topic", "proposed_choice", "alternatives_considered",
    "quantified_effect", "required_evidence", "source_ids", "upstream_ids",
    "owner_review_status", "human_review_status", "review_note", "limitations",
)
COMPARISON_FIELDS = (
    "comparison_id", "candidate_id", "candidate_name", "scenario_id",
    "scenario_treatment", "opening_term_principal", "opening_revolver",
    "opening_bank_debt", "retained_other_funded_debt", "opening_gross_funded_debt",
    "opening_gross_funded_leverage", "zero_cash_net_leverage",
    "capped_25m_cash_net_leverage_diagnostic", "cash_eligibility_status",
    "annual_amortization_percent", "annual_scheduled_term_principal",
    "cumulative_scheduled_principal_paid", "cumulative_cash_sweep",
    "cumulative_cash_interest", "revolver_commitment", "letters_of_credit",
    "opening_revolver_availability", "opening_usable_liquidity",
    "subsequent_minimum_usable_liquidity", "subsequent_minimum_liquidity_date",
    "all_in_minimum_usable_liquidity", "all_in_minimum_liquidity_date",
    "peak_revolver_including_opening",
    "peak_revolver_date", "first_analytical_threshold_failure",
    "first_50m_liquidity_warning", "first_cash_floor_failure",
    "revolver_capacity_exhaustion_date", "first_mandatory_payment_failure_date",
    "failed_obligation_type", "maturity_date", "unsupported_maturity_gap",
    "overall_path_status", "required_non_debt_contribution", "source_ids",
    "upstream_ids", "classification", "review_status", "limitations",
)
FINAL_ASSUMPTION_FIELDS = (
    "assumption_id", "category", "assumption_name", "value", "units",
    "definition_or_formula", "input_status", "source_ids", "upstream_ids",
    "owner_review_status", "phase8_required_action", "limitations",
)
COVENANT_MATRIX_FIELDS = (
    "matrix_id", "framework", "test_name", "metric_definition", "debt_definition",
    "earnings_definition", "cash_treatment", "drawn_revolver_treatment",
    "threshold", "units", "effective_period", "test_frequency", "warning_or_covenant",
    "cure_and_stepup_treatment", "draw_condition_consequence", "source_ids",
    "upstream_ids", "evidence_status", "owner_review_status", "limitations",
)
COVENANT_TEST_FIELDS = (
    "test_id", "scenario_id", "path_convention", "period_end", "fiscal_year",
    "quarter", "gross_funded_debt", "bank_debt", "eligible_cash_assumed",
    "capped_cash_sensitivity", "ttm_lender_base_ebitda", "gross_funded_leverage",
    "zero_cash_net_leverage", "capped_cash_net_leverage_diagnostic",
    "contractual_leverage_limit", "leverage_ratio_headroom",
    "leverage_debt_headroom", "leverage_break_even_ebitda",
    "ltm_cash_interest", "interest_coverage", "contractual_interest_coverage_minimum",
    "interest_coverage_ratio_headroom", "interest_coverage_earnings_cushion",
    "usable_liquidity", "contractual_minimum_liquidity",
    "liquidity_headroom", "analyst_leverage_warning", "analyst_coverage_warning",
    "analyst_liquidity_warning", "operating_cash", "operating_cash_floor",
    "leverage_status", "coverage_status", "liquidity_status", "operating_cash_status",
    "overall_warning_status", "overall_covenant_status", "input_completeness_status",
    "cash_floor_failure_flag", "commitment_exhaustion_flag",
    "mandatory_payment_failure_flag", "maturity_shortfall_flag",
    "drawability_status", "source_ids", "upstream_ids", "classification",
    "review_status", "limitations",
)
HEADROOM_FIELDS = (
    "headroom_id", "test_id", "scenario_id", "period_end", "framework",
    "metric", "actual", "threshold", "ratio_or_amount_headroom",
    "debt_headroom", "break_even_ebitda", "earnings_cushion", "units",
    "status", "formula", "source_ids", "upstream_ids", "review_status",
    "limitations",
)
TIMELINE_FIELDS = (
    "timeline_id", "scenario_id", "path_convention", "first_analyst_warning_date",
    "first_proposed_covenant_breach_date", "warning_lead_days_to_breach",
    "first_drawability_shutoff_date", "first_50m_liquidity_failure_date",
    "first_cash_floor_failure_date", "revolver_capacity_exhaustion_date",
    "first_mandatory_payment_failure_date", "failed_obligation_type",
    "maturity_date", "maturity_shortfall", "initial_intervention",
    "breach_intervention", "continued_drawability_treatment",
    "no_waiver_treatment", "source_ids", "upstream_ids", "review_status",
    "limitations",
)
SIZING_FIELDS = (
    "sizing_id", "analysis", "ebitda", "leverage_threshold", "cash_netting",
    "maximum_total_funded_debt", "retained_other_funded_debt",
    "maximum_bank_debt", "opening_revolver", "analytical_term_capacity",
    "term_commitment", "initial_term_funding", "reference_term_funding",
    "required_non_debt_contribution", "undrawn_term_commitment",
    "unused_term_commitment_treatment",
    "resulting_total_funded_debt", "resulting_leverage", "headroom_or_shortfall",
    "opening_usable_liquidity", "subsequent_minimum_usable_liquidity",
    "subsequent_minimum_liquidity_date", "all_in_minimum_usable_liquidity",
    "all_in_minimum_liquidity_date",
    "status", "source_ids", "upstream_ids", "owner_review_status", "limitations",
)
COMMON_HORIZON_FIELDS = (
    "common_horizon_id", "candidate_id", "candidate_name", "scenario_id",
    "period_start", "period_end", "cumulative_cash_interest",
    "cumulative_scheduled_principal", "cumulative_ecf_sweep",
    "cumulative_revolver_repayments", "ending_term_debt", "ending_revolver_debt",
    "ending_total_bank_debt", "ending_total_funded_debt", "peak_revolver_usage",
    "opening_usable_liquidity", "subsequent_minimum_usable_liquidity",
    "subsequent_minimum_liquidity_date", "all_in_minimum_usable_liquidity",
    "all_in_minimum_liquidity_date", "unpaid_mandatory_obligations",
    "first_warning_date", "first_breach_date", "warning_status", "covenant_status",
    "comparison_status", "source_ids", "upstream_ids", "review_status", "limitations",
)
ULTIMATE_MATURITY_FIELDS = (
    "maturity_comparison_id", "candidate_id", "candidate_name", "scenario_id",
    "period_start", "maturity_date", "horizon_months", "cumulative_cash_interest",
    "cumulative_scheduled_principal", "cumulative_ecf_sweep",
    "final_term_debt", "final_revolver_debt", "final_total_bank_debt",
    "final_total_funded_debt", "maturity_payment_due", "available_cash_applied",
    "unsupported_maturity_gap", "first_interim_payment_failure_date",
    "failed_obligation_type", "comparison_status", "source_ids", "upstream_ids",
    "review_status", "limitations",
)
SOURCES_USES_FIELDS = (
    "reconciliation_id", "candidate_id", "candidate_name", "term_commitment",
    "initial_term_funding", "opening_revolver", "required_non_debt_contribution",
    "total_sources", "reference_closing_uses", "sources_less_uses",
    "opening_bank_debt", "retained_other_funded_debt", "opening_total_funded_debt",
    "closing_gross_leverage", "warning_status", "covenant_status",
    "undrawn_term_commitment", "unused_term_commitment_treatment", "status",
    "source_ids", "upstream_ids", "review_status", "limitations",
)
COVENANT_SUMMARY_FIELDS = (
    "summary_id", "scenario_id", "path_convention", "closing_warning_status",
    "closing_covenant_status", "maximum_gross_funded_leverage",
    "tightest_leverage_ratio_headroom", "tightest_leverage_debt_headroom",
    "minimum_cash_interest_coverage", "tightest_coverage_ratio_headroom",
    "opening_usable_liquidity", "subsequent_minimum_usable_liquidity",
    "subsequent_minimum_liquidity_date", "all_in_minimum_usable_liquidity",
    "all_in_minimum_liquidity_date", "tightest_liquidity_headroom",
    "minimum_operating_cash", "tightest_operating_cash_headroom",
    "first_warning_date", "first_breach_date", "first_draw_shutoff_date",
    "first_liquidity_shortfall_date", "first_cash_floor_failure_date",
    "first_mandatory_payment_failure_date", "failed_obligation_type",
    "ultimate_maturity_gap", "input_completeness_status", "source_ids",
    "upstream_ids", "review_status", "limitations",
)
LEVERAGE_COVENANT_COMPARISON_FIELDS = (
    "comparison_id", "scenario_family", "covenant_case", "initial_leverage_limit",
    "warning_threshold", "closing_leverage", "closing_status", "first_warning_date",
    "first_breach_date", "liquidity_at_first_breach", "first_draw_shutoff_date",
    "first_mandatory_payment_failure_date", "days_breach_to_payment_failure",
    "ultimate_maturity_gap", "source_ids", "upstream_ids", "review_status", "limitations",
)
DISTRIBUTION_FIELDS = (
    "restriction_test_id", "scenario_id", "test_name", "proposed_rule",
    "planned_amount", "amount_paid_in_phase6_path", "amount_flagged_or_blocked",
    "first_flag_date", "test_result", "cash_flow_credit_taken_in_phase7",
    "source_ids", "upstream_ids", "owner_review_status", "limitations",
)
PHASE8_FIELDS = (
    "input_id", "section", "input_name", "value", "units", "formula_or_definition",
    "input_status", "source_ids", "upstream_ids", "owner_review_status",
    "phase8_model_location", "limitations",
)
VALIDATION_FIELDS = (
    "validation_id", "category", "test_name", "status", "observed_value",
    "expected_value_or_rule", "tolerance", "notes",
)
LEDGER_FIELDS = (
    "ledger_id", "artifact_path", "record_id", "metric_or_term", "source_ids",
    "upstream_ids", "classification", "review_status", "cutoff_status", "notes",
)


def dec(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value in (None, "", N_D, N_D_VALUE, N_M):
        raise Phase7Error(f"Cannot convert unavailable value to Decimal: {value!r}")
    return Decimal(str(value))


def fmt(value: object) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    number = dec(value)
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def ratio(numerator: Decimal, denominator: Decimal | None) -> Decimal | str:
    if denominator is None:
        return N_D_VALUE
    if denominator <= 0:
        return N_M
    return numerator / denominator


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            missing = [field for field in fields if field not in row]
            extra = [field for field in row if field not in fields]
            if missing or extra:
                raise Phase7Error(f"Schema mismatch for {path.name}: missing={missing}, extra={extra}")
            writer.writerow(row)


def ensure_unique(rows: list[dict[str, str]], key: str, label: str) -> None:
    values = [row[key] for row in rows]
    if len(values) != len(set(values)):
        raise Phase7Error(f"Duplicate {label} key")


def source_manifest() -> dict[str, dict[str, str]]:
    return phase6.phase5.source_manifest()


def phase5_value(assumption_id: str) -> Decimal:
    row = next(
        (item for item in read_csv(PHASE5_ASSUMPTIONS) if item["assumption_id"] == assumption_id),
        None,
    )
    if row is None or not row["value"]:
        raise Phase7Error(f"Missing Phase 5 assumption: {assumption_id}")
    return dec(row["value"])


def fy2025_lender_ebitda() -> Decimal:
    rows = read_csv(PHASE2_BRIDGES)
    matches = [
        row for row in rows
        if row["fiscal_year"] == "FY2025"
        and row["bridge_type"] == "provisional_lender_normalized_ebitda_base"
        and row["line_item"] == "Lender-normalized EBITDA (owner-reviewed base)"
    ]
    if len(matches) != 1:
        raise Phase7Error("FY2025 lender-base EBITDA is not uniquely supported")
    return dec(matches[0]["resulting_subtotal"])


def checkpoint_rows() -> list[dict[str, str]]:
    return [{
        "repository": "owencchapman24/quanex-credit-underwriting",
        "branch": "main",
        "local_head": APPROVED_PHASE6_COMMIT,
        "tracked_origin_main": APPROVED_PHASE6_COMMIT,
        "live_remote_main": APPROVED_PHASE6_COMMIT,
        "ahead": "0", "behind": "0", "working_tree_clean_before_work": "yes",
        "verified_on": "2026-09-10",
        "notes": "Verified before Phase 7 edits. Live remote was checked independently. The Phase 6 descendant-validation defect was repaired without changing approved Phase 6 data or documentation.",
    }]


def candidate_definitions() -> tuple[StructureCandidate, ...]:
    ebitda = fy2025_lender_ebitda()
    retained = phase5_value("P5A-032")
    opening_revolver = phase5_value("P5A-026")
    maximum_bank_debt_at_325 = ebitda * Decimal("3.25") - retained
    analytical_term_capacity = maximum_bank_debt_at_325 - opening_revolver
    exact_required_contribution = REFERENCE_CLOSING_USES - analytical_term_capacity - opening_revolver
    rounded_640_revolver_at_capacity = maximum_bank_debt_at_325 - Decimal("640")
    common_limit = (
        "Uses unchanged Phase 6 operating cases and payment ordering. Actual payoff, fees, "
        "accessible cash, pricing, legal terms, and refinancing at maturity remain unresolved."
    )
    return (
        StructureCandidate(
            "STR-001", "Retain existing facilities", "existing_retention", "existing",
            phase5_value("P5A-027"), phase5_value("P5A-028"), phase5_value("P5A-030"),
            phase5_value("P5A-031"), None, date(2029, 8, 1), phase5_value("P5A-020"),
            Decimal("0"), Decimal("0"), "quantified_existing_rate_neutral_case",
            "live_alternative", "Preserves the committed existing-facility comparison and avoids unsupported transaction assumptions.",
            "Applicable existing pricing tier and amendment economics remain not determinable; August 2029 maturity dependence remains.",
        ),
        StructureCandidate(
            "STR-002", "Limited amendment or extension", "amend_extend", "amend_extend",
            None, None, None, None, None, None, None, None, None,
            "qualitative_only", "live_alternative",
            "Retains an amendment or extension as a live option without inventing tenor, fees, pricing, covenants, or capacity.",
            "No lender proposal or sufficiently complete public terms support quantitative modeling.",
        ),
        StructureCandidate(
            "STR-003", "$650m reference term / 10% amortization", "reference_refinancing", "proposed",
            Decimal("650"), opening_revolver, Decimal("300"), Decimal("6.2"), Decimal("10"),
            date(2031, 1, 31), Decimal("6.57"), Decimal("0"), Decimal("50"),
            "quantified_phase6_reference", "not_selected",
            "Preserves the Phase 4-6 reference transaction for direct reconciliation.", common_limit,
        ),
        StructureCandidate(
            "STR-004", "$650m term / 5% amortization", "lower_amortization_refinancing", "proposed",
            Decimal("650"), opening_revolver, Decimal("300"), Decimal("6.2"), Decimal("5"),
            date(2031, 1, 31), Decimal("6.57"), Decimal("0"), Decimal("50"),
            "quantified_sensitivity", "not_selected",
            "Tests lower scheduled principal and a larger reliance on the annual cash sweep and maturity refinancing.", common_limit,
        ),
        StructureCandidate(
            "STR-005", "$650m term / 7.5% amortization", "lower_amortization_refinancing", "proposed",
            Decimal("650"), opening_revolver, Decimal("300"), Decimal("6.2"), Decimal("7.5"),
            date(2031, 1, 31), Decimal("6.57"), Decimal("0"), Decimal("50"),
            "quantified_sensitivity", "not_selected",
            "Tests an intermediate scheduled-amortization burden with a separately identified 50% annual cash sweep.", common_limit,
        ),
        StructureCandidate(
            "STR-006", "$650m term / 15% amortization", "higher_amortization_refinancing", "proposed",
            Decimal("650"), opening_revolver, Decimal("300"), Decimal("6.2"), Decimal("15"),
            date(2031, 1, 31), Decimal("6.57"), Decimal("0"), Decimal("50"),
            "quantified_sensitivity", "not_selected",
            "Tests faster contractual deleveraging and the corresponding near-term liquidity burden.", common_limit,
        ),
        StructureCandidate(
            "STR-007", "$625m term / conditional $25m contribution / 7.5% amortization",
            "conditional_cash_supported_refinancing", "proposed", Decimal("625"),
            opening_revolver, Decimal("300"), Decimal("6.2"), Decimal("7.5"),
            date(2031, 1, 31), Decimal("6.57"), Decimal("25"), Decimal("50"),
            "quantified_conditional_sensitivity", "not_selected",
            "Shows a real reduction in funded debt when a separate $25m non-debt closing source is available.",
            "No accessible cash or equity source is established. The contribution may not consume the separate $25m operating cash floor. " + common_limit,
        ),
        StructureCandidate(
            "STR-008", "$635m practical term / $15m conditional contribution / 7.5% amortization",
            "recommended_conditional_refinancing", "proposed", Decimal("635"),
            opening_revolver, Decimal("300"), Decimal("6.2"), Decimal("7.5"),
            date(2031, 1, 31), Decimal("6.57"), Decimal("15"), Decimal("50"),
            "quantified_practical_sizing_with_cushion", "owner_reviewed_phase7_provisional_structure",
            "Uses a practical rounded term amount below the exact 3.25x total-funded-debt capacity and closes below the inclusive 3.25x analyst warning.",
            "The $15m non-debt source is a closing condition, not an assumption that book or foreign cash is accessible, and it may not consume the separate $25m operating cash floor. Unused term commitment is not treated as delayed-draw availability. " + common_limit,
        ),
        StructureCandidate(
            "STR-009", "Exact 3.25x analytical total-funded-debt boundary / 7.5% amortization",
            "analytical_capacity_boundary", "proposed", analytical_term_capacity,
            opening_revolver, Decimal("300"), Decimal("6.2"), Decimal("7.5"),
            date(2031, 1, 31), Decimal("6.57"), exact_required_contribution, Decimal("50"),
            "quantified_analytical_boundary", "not_selected",
            "Preserves the exact calculated allocation at the 3.25x total-funded-debt boundary without presenting the result as a negotiated facility amount.",
            "Closing exactly at 3.25x activates the inclusive analyst warning but does not breach the proposed 3.50x covenant. " + common_limit,
        ),
        StructureCandidate(
            "STR-010", "$640m rounded term / $10m contribution / reference revolver",
            "rounded_marginal_exception", "proposed", Decimal("640"),
            opening_revolver, Decimal("300"), Decimal("6.2"), Decimal("7.5"),
            date(2031, 1, 31), Decimal("6.57"), Decimal("10"), Decimal("50"),
            "quantified_marginal_exception", "not_selected",
            "Tests a conventional rounded term amount while keeping the reference revolver allocation and a round $10m non-debt source.",
            "The structure exceeds the 3.25x analytical sizing boundary by $0.149m and therefore remains an unselected sizing exception. " + common_limit,
        ),
        StructureCandidate(
            "STR-011", "$640m rounded term / exact non-debt source / reallocated revolver",
            "rounded_at_analytical_capacity", "proposed", Decimal("640"),
            rounded_640_revolver_at_capacity, Decimal("300"), Decimal("6.2"), Decimal("7.5"),
            date(2031, 1, 31), Decimal("6.57"), exact_required_contribution, Decimal("50"),
            "quantified_rounded_allocation_at_boundary", "not_selected",
            "Demonstrates that term and revolver allocation can change while total funded debt remains at the same 3.25x analytical capacity.",
            "The exact $10.149m non-debt source remains unsupported and closing exactly at 3.25x activates the inclusive analyst warning. " + common_limit,
        ),
    )


def structure_candidate_rows(candidates: tuple[StructureCandidate, ...]) -> list[dict[str, str]]:
    retained = phase5_value("P5A-032")
    rows: list[dict[str, str]] = []
    for candidate in candidates:
        bank_debt = (
            candidate.opening_term + candidate.opening_revolver
            if candidate.opening_term is not None and candidate.opening_revolver is not None
            else None
        )
        gross_debt = bank_debt + retained if bank_debt is not None else None
        availability = (
            candidate.revolver_commitment - candidate.letters_of_credit - candidate.opening_revolver
            if candidate.revolver_commitment is not None
            and candidate.letters_of_credit is not None
            and candidate.opening_revolver is not None else None
        )
        annual_principal = (
            candidate.opening_term * candidate.amortization_percent / Decimal("100")
            if candidate.opening_term is not None and candidate.amortization_percent is not None
            else None
        )
        contribution = candidate.cash_contribution
        sources_control = (
            candidate.opening_term + candidate.opening_revolver + contribution - REFERENCE_CLOSING_USES
            if candidate.structure == "proposed" and candidate.opening_term is not None
            and candidate.opening_revolver is not None and contribution is not None else None
        )
        term_commitment = candidate.opening_term
        undrawn_term = Decimal("0") if term_commitment is not None else None
        rows.append({
            "candidate_id": candidate.candidate_id, "candidate_name": candidate.name,
            "alternative_type": candidate.alternative_type,
            "quantitative_status": candidate.quantitative_status,
            "selection_status": candidate.selection_status,
            "opening_term_principal": fmt(candidate.opening_term),
            "opening_revolver": fmt(candidate.opening_revolver),
            "opening_bank_debt": fmt(bank_debt),
            "retained_other_funded_debt": fmt(retained) if bank_debt is not None else "",
            "opening_gross_funded_debt": fmt(gross_debt),
            "term_commitment": fmt(term_commitment),
            "revolver_commitment": fmt(candidate.revolver_commitment),
            "total_term_plus_revolver_commitments": fmt(
                term_commitment + candidate.revolver_commitment
                if term_commitment is not None and candidate.revolver_commitment is not None else None
            ),
            "letters_of_credit": fmt(candidate.letters_of_credit),
            "opening_revolver_availability": fmt(availability),
            "opening_usable_liquidity": fmt(availability),
            "undrawn_term_commitment": fmt(undrawn_term),
            "unused_term_commitment_treatment": (
                "none; funded term equals commitment and no delayed-draw availability is assumed"
                if term_commitment is not None else N_D
            ),
            "required_non_debt_contribution": fmt(contribution),
            "reference_closing_uses": fmt(REFERENCE_CLOSING_USES) if candidate.structure == "proposed" else "",
            "sources_uses_control": fmt(sources_control),
            "annual_amortization_percent": fmt(candidate.amortization_percent),
            "annual_scheduled_term_principal": fmt(annual_principal),
            "maturity_date": candidate.maturity.isoformat() if candidate.maturity else "",
            "all_in_rate_percent": fmt(candidate.all_in_rate_percent),
            "excess_cash_flow_sweep_percent": fmt(candidate.ecb_sweep_percent),
            "source_ids": "SRC-001;SRC-002;SRC-003",
            "upstream_ids": "PT-002;PT-003;PT-007;PT-008;PT-009;PT-010;PT-017;P5A-016;P5A-018;P5A-020;P5A-022;P5A-025:P5A-032;P6R-001:P6R-014",
            "review_status": REVIEW, "rationale": candidate.rationale,
            "limitations": candidate.limitations,
        })
    return rows


def covenant_proposal_rows() -> list[dict[str, str]]:
    common = {
        "source_ids": "SRC-001;SRC-003", "upstream_ids": "PT-017:PT-024;P6T-0001:P6T-0238",
        "owner_review_status": REVIEW,
    }
    specifications = [
        ("P7CP-001", "existing_contractual", "maximum Consolidated Net Leverage Ratio", "Public reconstruction of the existing maintenance covenant applicable at the projected closing absent another qualifying acquisition step-up.", "Consolidated Funded Indebtedness less permitted netted cash under the agreement", "Consolidated EBITDA under the agreement", "3.25", "turns", "2026-01-31", "", "quarterly", "Existing agreement permits defined cash netting, but the eligible amount is not determinable from approved public evidence.", "Included in funded indebtedness.", "Agreement-defined funded debt, subject to exclusions and definitions.", "Items excluded by the agreement; exact public compliance calculation unavailable.", "Agreement-defined pro forma rules; not reconstructed as an official calculation.", "No additional exception assumed from public evidence.", "Not assumed.", "Qualifying-acquisition step-up may apply only if elected and supported.", "Existing draw conditions apply; formal drawability is not reconstructed.", "Existing reporting terms; current private compliance certificate required.", "partial_public_reconstruction", "Not an official compliance certificate."),
        ("P7CP-002", "proposed_contractual", "maximum gross total funded leverage", "Gross total funded debt divided by lender EBITDA; no cash netting.", "Term principal + drawn revolver + other funded debt including the retained $62.619m proxy, subject to final legal drafting", "Lender EBITDA using the Phase 2 owner-reviewed base as the opening reference and a documented proposed definition thereafter", "3.50", "turns", "2026-01-31", "2027-10-31", "quarterly and at closing", "none", "Included at face principal.", "Borrowed money, drawn revolver and finance-lease/other funded debt.", "Operating lease liabilities and trade payables unless final legal drafting expressly includes them.", "Pro forma acquisitions and dispositions only with delivered calculations and no unsupported synergies.", "None assumed.", "No automatic step-up.", "An uncured breach is proposed to block new drawings, subject to final legal drafting.", "Quarterly certificate within 45 days; annual certificate within 90 days.", "hypothetical_proposal", "A 3.50x gross covenant is not directly comparable with the existing 3.25x net covenant. Final debt and EBITDA definitions require counsel and lender approval."),
        ("P7CP-003", "proposed_contractual", "maximum gross total funded leverage", "First leverage step-down.", "Same as P7CP-002", "Same as P7CP-002", "3.25", "turns", "2027-11-01", "2028-10-31", "quarterly", "none", "Included at face principal.", "Same as P7CP-002.", "Same as P7CP-002.", "Same as P7CP-002.", "None assumed.", "No automatic step-up.", "Same as P7CP-002.", "Same as P7CP-002.", "hypothetical_proposal", "Step date aligns to the FY2028 testing year; exact certificate date and stub-period treatment require drafting."),
        ("P7CP-004", "proposed_contractual", "maximum gross total funded leverage", "Second leverage step-down.", "Same as P7CP-002", "Same as P7CP-002", "3.00", "turns", "2028-11-01", "2031-01-31", "quarterly", "none", "Included at face principal.", "Same as P7CP-002.", "Same as P7CP-002.", "Same as P7CP-002.", "None assumed.", "No automatic step-up.", "Same as P7CP-002.", "Same as P7CP-002.", "hypothetical_proposal", "The final test before maturity must not imply refinancing availability."),
        ("P7CP-005", "proposed_contractual", "minimum EBITDA to cash-interest coverage", "LTM lender EBITDA divided by LTM cash interest paid or payable on funded debt.", "LTM lender EBITDA", "LTM cash interest paid or payable, including default interest and recurring cash financing fees when known", "3.00", "turns", "2026-01-31", "2031-01-31", "quarterly and at closing when a complete LTM denominator is delivered", "not_applicable", "Interest on drawn revolver included.", "Cash interest on all funded debt and recurring cash financing fees.", "Noncash amortization of financing fees unless paid in cash.", "Acquisition pro forma EBITDA only under the same documented leverage rules.", "None assumed.", "No step-up.", "An uncured breach is proposed to block new drawings, subject to final legal drafting.", "Quarterly certificate and monthly cash-interest reporting.", "hypothetical_proposal", "The Phase 6 model lacks a complete closing-date LTM cash-interest denominator; opening compliance is therefore not determinable from public information."),
        ("P7CP-006", "proposed_contractual", "minimum usable liquidity", "Unrestricted eligible cash plus undrawn revolver capacity that is legally and operationally drawable.", "Eligible cash + revolver commitment - drawn revolver - outstanding LCs", "not_applicable", "50", MONEY, "2026-01-31", "2031-01-31", "monthly and upon any distribution, acquisition, or additional debt", "Eligible cash only after entity, jurisdiction, tax, lien and operating-need validation.", "Deducted from revolver capacity.", "Unrestricted cash and available, drawable revolver capacity.", "Trapped, restricted, pledged, required operating, or otherwise unavailable cash.", "Tested after the proposed transaction or distribution.", "No cure amount assumed.", "No step-up.", "Failure is proposed to block new drawings and restricted payments, subject to final legal drafting.", "Monthly liquidity certificate within 15 days; immediate notice below $75m warning.", "hypothetical_proposal", "The Phase 7 model gives no credit to book cash; final eligible cash remains pending information."),
        ("P7CP-007", "analyst_warning", "gross total funded leverage warning", "Earlier lender intervention threshold using the proposed gross debt and lender EBITDA definitions.", "Same as P7CP-002", "Same as P7CP-002", "3.25", "turns", "2026-01-31", "2027-10-31", "monthly monitoring and quarterly formal calculation", "none", "Included.", "Same as proposed covenant.", "Same as proposed covenant.", "No unsupported pro forma credit.", "not_applicable", "not_applicable", "Does not itself determine legal drawability.", "Monthly leverage estimate; quarterly certificate.", "analyst_threshold", "A warning is not a covenant breach, waiver decision, or compliance certificate."),
        ("P7CP-008", "analyst_warning", "gross total funded leverage warning", "First warning step-down.", "Same as P7CP-002", "Same as P7CP-002", "3.00", "turns", "2027-11-01", "2028-10-31", "monthly monitoring and quarterly formal calculation", "none", "Included.", "Same as proposed covenant.", "Same as proposed covenant.", "No unsupported pro forma credit.", "not_applicable", "not_applicable", "Does not itself determine legal drawability.", "Monthly leverage estimate; quarterly certificate.", "analyst_threshold", "A warning is 0.25x inside the proposed covenant."),
        ("P7CP-009", "analyst_warning", "gross total funded leverage warning", "Second warning step-down.", "Same as P7CP-002", "Same as P7CP-002", "2.75", "turns", "2028-11-01", "2031-01-31", "monthly monitoring and quarterly formal calculation", "none", "Included.", "Same as proposed covenant.", "Same as proposed covenant.", "No unsupported pro forma credit.", "not_applicable", "not_applicable", "Does not itself determine legal drawability.", "Monthly leverage estimate; quarterly certificate.", "analyst_threshold", "A warning is 0.25x inside the proposed covenant."),
        ("P7CP-010", "analyst_warning", "minimum EBITDA to cash-interest coverage warning", "Early intervention threshold inside the proposed coverage covenant.", "Same as P7CP-005", "Same as P7CP-005", "3.50", "turns", "2026-01-31", "2031-01-31", "monthly monitoring and quarterly formal calculation", "not_applicable", "Included.", "Same as proposed covenant.", "Same as proposed covenant.", "No unsupported pro forma credit.", "not_applicable", "not_applicable", "Does not itself determine legal drawability.", "Monthly estimate; quarterly certificate.", "analyst_threshold", "A warning is not a legal breach."),
        ("P7CP-011", "analyst_warning", "minimum usable liquidity warning", "Early intervention threshold above the proposed minimum-liquidity covenant.", "Same as P7CP-006", "not_applicable", "75", MONEY, "2026-01-31", "2031-01-31", "monthly", "same as P7CP-006", "Deducted.", "Same as proposed covenant.", "Same as proposed covenant.", "Tested after proposed actions.", "not_applicable", "not_applicable", "Does not itself determine legal drawability.", "Immediate notice and 10-business-day action plan.", "analyst_threshold", "The committed Phase 6 $50m warning remains preserved in prior outputs; Phase 7 adds a more conservative $75m intervention threshold."),
        ("P7CP-012", "model_control", "operating cash floor", "Minimum operating cash retained before optional debt repayment in the model.", "Ending modeled cash", "not_applicable", "25", MONEY, "2026-01-31", "2031-01-31", "monthly", "not_applicable", "not_applicable", "Operating cash retained in the modeled entity perimeter.", "No assumption that the amount is eligible for covenant netting.", "not_applicable", "not_applicable", "not_applicable", "Separate from covenant drawability until documented.", "Monthly cash report by entity and jurisdiction.", "modeling_control_not_contractual", "Do not combine this cash floor with the $50m liquidity covenant or count it as an accessible closing contribution."),
        ("P7CP-013", "proposed_contractual", "excess cash flow sweep", "50% of positive annual excess cash flow after specified operating and mandatory financing uses, applied after revolver repayment.", "CFO-equivalent cash generation less cash taxes, ordinary-course capex, working-capital uses, cash interest, scheduled term amortization and retained mandatory obligations", "not_applicable", "50", "percent", "2026-10-31", "2030-10-31", "annual", "not_applicable", "Revolver must be repaid before term sweep.", "Documented cash generation only.", "No deduction for dividends, repurchases, voluntary acquisitions, unverified synergies, or unavailable cash; no duplicated deduction for amounts already included in CFO-equivalent cash generation.", "Acquisition/disposition pro forma effects require delivered evidence.", "Subject to the $50m usable-liquidity safeguard and $25m operating cash floor.", "No step-down proposed.", "not_applicable", "Annual ECF certificate and calculation within 90 days after fiscal year-end.", "hypothetical_proposal", "Phase 4-6 modeled sweeps remain sensitivities. Final legal ECF definitions and recurring fee treatment are pending."),
        ("P7CP-014", "proposed_contractual", "restricted payments", "No debt-funded share repurchases; no share repurchases while any revolver borrowing is outstanding; dividends require pro forma tests.", "not_applicable", "not_applicable", "See DISTRIBUTION_RESTRICTION_TESTS.csv", "text", "2026-01-31", "2031-01-31", "at each payment and monthly monitoring", "same as P7CP-006", "Any drawn revolver blocks repurchases.", "Ordinary dividends only if no default, gross leverage <=3.00x and usable liquidity >=$75m after payment.", "Share repurchases outside the stated tests; debt-funded distributions.", "Pro forma after giving effect to payment.", "No exception assumed beyond a tightly bounded lender-approved basket.", "No step-up.", "Warning suspends repurchases; breach suspends all restricted payments.", "Monthly distribution report and board approvals on request.", "hypothetical_proposal", "Phase 7 does not take cash-flow credit for these restrictions; Phase 6 unmitigated cash paths remain unchanged."),
        ("P7CP-015", "proposed_contractual", "additional debt and acquisitions", "Incremental debt and acquisitions require pro forma covenant compliance and a warning-level cushion.", "not_applicable", "not_applicable", "gross leverage <=3.00x and usable liquidity >=$100m", "text", "2026-01-31", "2031-01-31", "at each transaction", "same as P7CP-006", "All proposed incremental borrowings included.", "Documented ordinary-course debt baskets only.", "Unapproved acquisition debt, unrestricted-subsidiary leakage and unsupported synergy credit.", "Full pro forma sources, uses, integration costs and LTM EBITDA bridge required.", "No general acquisition step-up assumed.", "No step-up.", "Failure blocks the transaction; it does not create modeled proceeds.", "Pre-transaction certificate and lender notice.", "hypothetical_proposal", "Basket sizes, permitted liens and legal mechanics remain subject to owner, lender and counsel review."),
        ("P7CP-016", "proposed_contractual", "cures, waivers and drawability", "No equity cure, waiver, acquisition step-up or continued drawability is assumed.", "not_applicable", "not_applicable", "pending legal drafting", "text", "2026-01-31", "2031-01-31", "continuous", "not_applicable", "New draws blocked after an uncured breach under the proposed convention.", "None assumed.", "Any negotiated cure or waiver not evidenced at the cutoff.", "not_applicable", "No cure assumed.", "No step-up assumed.", "Continued drawability and no-waiver paths remain separate model cases.", "Immediate breach notice; lender reservation of rights.", "hypothetical_proposal", "This is an underwriting proposal, not a legal conclusion about the existing or future agreement."),
        ("P7CP-017", "proposed_contractual", "reporting and control remediation", "Quarterly financials and compliance certificate, monthly liquidity/working-capital reporting, annual audited statements and control-remediation updates.", "not_applicable", "not_applicable", "15/45/90 day cadence", "days", "2026-01-31", "2031-01-31", "monthly/quarterly/annual", "not_applicable", "not_applicable", "Liquidity, debt, covenant EBITDA bridge, cash by entity, working capital, capex, distributions, integration and remediation status.", "None assumed.", "not_applicable", "Limited administrative cure only if legally negotiated; no financial cure assumed.", "No step-up.", "Late reporting is an escalation event; final default mechanics require drafting.", "Monthly within 15 days; quarterly within 45 days; annual within 90 days.", "hypothetical_proposal", "The cash-flow control material weakness remains a confidence issue, not a known financial-statement misstatement."),
    ]
    rows: list[dict[str, str]] = []
    for values in specifications:
        if len(values) == 22:
            values = (
                *values[:17],
                "No financial cure assumed; any administrative cure requires final drafting.",
                *values[17:],
            )
        (
            proposal_id, framework, metric, definition, numerator, denominator,
            threshold, units, start, end, frequency, cash_netting, revolver,
            inclusions, exclusions, pro_forma, exceptions, cures, stepups,
            draw_effect, reporting, evidence, limitations,
        ) = values
        item = {
            "proposal_id": proposal_id, "framework": framework,
            "metric_or_term": metric, "definition": definition, "numerator": numerator,
            "denominator": denominator, "threshold": threshold, "units": units,
            "effective_start": start, "effective_end": end,
            "testing_frequency": frequency, "cash_netting": cash_netting,
            "drawn_revolver_treatment": revolver, "inclusions": inclusions,
            "exclusions": exclusions, "pro_forma_rules": pro_forma,
            "exceptions": exceptions, "cures": cures, "stepups": stepups,
            "draw_condition_effect": draw_effect, "reporting_requirement": reporting,
            **common, "evidence_status": evidence, "limitations": limitations,
        }
        if framework in {"analyst_warning", "model_control"}:
            item.update({"exceptions": "not_applicable", "cures": "not_applicable", "stepups": "not_applicable"})
        field_overrides = {
            "P7CP-006": {"exceptions": "No exception assumed beyond the defined eligible-cash rules.", "cures": "No cure amount assumed.", "stepups": "No step-up."},
            "P7CP-013": {"cures": "not_applicable", "stepups": "No step-down proposed."},
            "P7CP-014": {"cures": "not_applicable", "stepups": "No step-up."},
            "P7CP-015": {"exceptions": "Documented ordinary-course baskets only; no broad exception assumed.", "cures": "No financial cure assumed.", "stepups": "No general acquisition step-up assumed."},
            "P7CP-016": {"exceptions": "None assumed.", "cures": "No cure or waiver assumed.", "stepups": "No acquisition step-up assumed."},
            "P7CP-017": {"exceptions": "None assumed.", "cures": "Limited administrative cure only if legally negotiated; no financial cure assumed.", "stepups": "No step-up."},
        }
        item.update(field_overrides.get(proposal_id, {}))
        rows.append(item)
    return rows


def owner_review_rows(candidates: tuple[StructureCandidate, ...]) -> list[dict[str, str]]:
    selected = next(item for item in candidates if item.candidate_id == "STR-008")
    decisions = [
        ("P7OD-001", "recommended structure", selected.name, "Retain existing; amend/extend; exact analytical boundary; $639m; $640m; full $650m reference; alternative amortization", f"$635m term commitment and funding; $15m conditional non-debt contribution; opening gross leverage {fmt((dec(selected.opening_term) + dec(selected.opening_revolver) + phase5_value('P5A-032')) / fy2025_lender_ebitda())}", "Executable closing source and final lender diligence"),
        ("P7OD-002", "term commitment and funding", "$635m term commitment funded at closing; no continuing unused term availability", "$650m cap; exact $639.851m boundary; $639m and $640m rounded alternatives", "Avoids false precision and closes below the inclusive 3.25x warning", "Payoff, fees, hedge, LC and funds-flow evidence"),
        ("P7OD-003", "amortization", "7.5% annually, paid 1.875% quarterly", "5%, 10%, 15%", "Balances scheduled service with a separately modeled ECF sweep", "Lender approval and final legal documentation"),
        ("P7OD-004", "gross or net leverage", "Gross total funded leverage; zero cash netting", "Bank-only gross; capped-cash net; existing-style net leverage", "Reference $650m term is 3.295x on zero-cash total funded debt", "Final funded-debt, EBITDA and cash definitions"),
        ("P7OD-005", "leverage covenant", "3.50x through FY2027, 3.25x FY2028, 3.00x thereafter", "3.25x initial gross covenant; existing 3.25x net test; flat 3.50x", "At closing the 0.25x interval equals $56.336m of debt capacity or $16.096m of EBITDA cushion at the exact analytical boundary; it is maintenance cushion, not sizing capacity", "Legal drafting and quarterly certification"),
        ("P7OD-006", "analyst leverage warning", "3.25x / 3.00x / 2.75x with inclusive activation", "Strictly-greater warning boundary; Phase 6 bank-leverage warnings", "Exactly 3.25x is warning, not breach; selected $635m structure closes below warning", "Implementation control and ongoing monitoring data"),
        ("P7OD-007", "cash-interest coverage", "3.00x covenant; 3.50x warning", "No coverage covenant; higher covenant", "Preserves Phase 6 3.00x test as covenant proposal with earlier warning", "Complete LTM cash-interest denominator"),
        ("P7OD-008", "minimum liquidity", "$50m covenant; $75m warning", "$50m only", "Adds earlier intervention while preserving the committed Phase 6 $50m failure level", "Eligible cash and drawability definitions"),
        ("P7OD-009", "operating cash floor", "$25m separate model control", "Treat as covenant cash or closing contribution", "No cash-netting or contribution credit", "Cash by entity, jurisdiction and restriction"),
        ("P7OD-010", "ECF sweep", "50%, after revolver repayment, no step-down", "25% or leverage-based step-down", "Preserves a clear deleveraging mechanism without double-counting operating uses", "Final legal ECF definition and annual certificate"),
        ("P7OD-011", "share repurchases", "Prohibit debt-funded repurchases and all repurchases while revolver debt is outstanding", "Only prohibit directly draw-funded repurchases", "Addresses both Phase 6 narrow and broad flags", "Owner, lender and legal approval"),
        ("P7OD-012", "dividends", "Permit only if no default, gross leverage <=3.00x and liquidity >=$75m after payment", "Full suspension; looser basket", "Preserves limited flexibility with measurable protection", "Board policy and legal drafting"),
        ("P7OD-013", "warning response", "Suspend repurchases; deliver a 10-business-day action plan and monthly reporting", "Observation only", "Creates an intervention timeline before breach", "Lender agreement and final legal documentation"),
        ("P7OD-014", "breach response", "Suspend all restricted payments; covenant-linked no-waiver shutoff begins in the following month", "Immediate same-day shutoff; continued drawability or waiver", "Warnings alone do not terminate draws; Phase 6 analytical shutoff remains a separately labeled sensitivity", "Final events-of-default, notice, cure and waiver terms"),
        ("P7OD-015", "equity cures and acquisition step-ups", "None assumed", "Negotiated cure or step-up", "Avoids unsupported covenant relief", "Private lender proposal and legal drafting"),
        ("P7OD-016", "maturity refinancing", "No refinancing assumed", "Refinancing at or before maturity", "Keeps unsupported maturity gaps visible", "Future market access cannot be established at cutoff"),
        ("P7OD-017", "book-cash leverage", "Diagnostic only", "Use book cash as eligible cash", "Prevents $76.018m book cash and $46.9m foreign cash from being treated as available", "Cash-access diligence"),
        ("P7OD-018", "amend/extend option", "Retain as qualitative live alternative", "Discard option; invent economics", "Avoids an unsupported refinancing superiority conclusion", "Lender amendment proposal"),
        ("P7OD-019", "financing comparison horizon", "Use July 31, 2029 common horizon and separate ultimate-maturity view", "Compare cumulative totals through different maturities", "Removes the approximately 18-month horizon mismatch from direct comparisons", "Deterministic presentation control"),
        ("P7OD-020", "coverage status terminology", "N/D for missing inputs; N/M only for zero or negative denominator", "Use N/M for all unavailable coverage", "Keeps missing information distinct from mathematically non-meaningful ratios", "Deterministic status control"),
        ("P7OD-021", "drawability path taxonomy", "Separate continued-draw, Phase 7 covenant-linked no-waiver, and inherited Phase 6 analytical shutoff", "One combined no-waiver path", "Prevents an analytical warning from being presented as a legal draw termination", "Final legal draw conditions remain pending"),
    ]
    return [{
        "decision_id": item[0], "topic": item[1], "proposed_choice": item[2],
        "alternatives_considered": item[3], "quantified_effect": item[4],
        "required_evidence": item[5], "source_ids": "SRC-001;SRC-002;SRC-003",
        "upstream_ids": "PT-002:PT-024;P6R-001:P6R-014;P6RS-001:P6RS-024",
        "owner_review_status": REVIEW, "human_review_status": REVIEW,
        "review_note": OWNER_REVIEW_NOTE,
        "limitations": (
            "Owner review records underwriting judgment, not an observed borrower fact or "
            "external evidence. Required evidence and all stated conditions remain open."
        ),
    } for item in decisions]


@contextmanager
def candidate_parameter_override(candidate: StructureCandidate) -> Iterator[None]:
    original = phase6.base_structure_parameters
    if candidate.structure != "proposed":
        yield
        return
    if any(value is None for value in (
        candidate.opening_term, candidate.opening_revolver,
        candidate.revolver_commitment, candidate.letters_of_credit,
        candidate.amortization_percent, candidate.maturity,
        candidate.all_in_rate_percent,
    )):
        raise Phase7Error(f"Incomplete quantitative candidate: {candidate.candidate_id}")

    def replacement(structure: str, amortization_percent: Decimal = Decimal("10")) -> dict[str, Decimal | date]:
        if structure != "proposed":
            return original(structure, amortization_percent)
        return {
            "opening_term": dec(candidate.opening_term),
            "opening_revolver": dec(candidate.opening_revolver),
            "commitment": dec(candidate.revolver_commitment),
            "lc": dec(candidate.letters_of_credit),
            "all_in_rate": dec(candidate.all_in_rate_percent),
            "quarterly_principal": dec(candidate.opening_term) * dec(candidate.amortization_percent) / Decimal("400"),
            "maturity": candidate.maturity,
        }

    phase6.base_structure_parameters = replacement
    try:
        yield
    finally:
        phase6.base_structure_parameters = original


MODELED_SCENARIOS = (
    "BASE", "MODERATE_UNMITIGATED", "SEVERE_UNMITIGATED",
    "MODERATE_MITIGATED", "SEVERE_MITIGATED",
    "MODERATE_NO_WAIVER", "SEVERE_NO_WAIVER",
)
PHASE7_NO_WAIVER_SCENARIOS = {
    "MODERATE_PHASE7_COVENANT_NO_WAIVER": "MODERATE_UNMITIGATED",
    "SEVERE_PHASE7_COVENANT_NO_WAIVER": "SEVERE_UNMITIGATED",
}


@contextmanager
def phase7_covenant_trigger_override(limit_function=None) -> Iterator[None]:
    """Make Phase 6's next-month shutoff respond only to Phase 7 covenant breaches."""
    if limit_function is None:
        limit_function = leverage_limit
    original_leverage = phase6.analytical_leverage_test
    original_coverage = phase6.analytical_coverage_test
    retained = phase5_value("P5A-032")
    dates = phase6.phase5.month_sequence(2026, 2, 2031, 1)
    state = {"leverage_calls": 0, "month_index": 0}

    def leverage_test(
        debt: Decimal, ebitda: Decimal | None, threshold: Decimal,
    ) -> tuple[Decimal | None, bool, str]:
        result, _, status = original_leverage(debt, ebitda, threshold)
        call_number = state["leverage_calls"]
        state["leverage_calls"] += 1
        month_index, call_in_month = divmod(call_number, 3)
        state["month_index"] = month_index
        if call_in_month != 2:
            return result, False, status
        on_date = dates[month_index]
        if not phase6.phase5.is_quarter_end(on_date):
            return result, False, "not_applicable_between_tests"
        if ebitda is None:
            return result, False, N_D
        if ebitda <= 0:
            return result, True, "breached_nonpositive_ebitda"
        gross_leverage = (debt + retained) / ebitda
        limit = limit_function(on_date)
        breached = gross_leverage > limit
        return result, breached, "breached" if breached else "compliant"

    def coverage_test(
        ebitda: Decimal | None, cash_interest: Decimal | None,
    ) -> tuple[Decimal | None, bool, str]:
        result, _, _ = original_coverage(ebitda, cash_interest)
        on_date = dates[state["month_index"]]
        if not phase6.phase5.is_quarter_end(on_date):
            return result, False, "not_applicable_between_tests"
        if ebitda is None or cash_interest is None:
            return result, False, N_D
        if cash_interest <= 0:
            return result, False, N_M
        breached = ebitda / cash_interest < Decimal("3.00")
        return result, breached, "breached" if breached else "compliant"

    phase6.analytical_leverage_test = leverage_test
    phase6.analytical_coverage_test = coverage_test
    try:
        yield
    finally:
        phase6.analytical_leverage_test = original_leverage
        phase6.analytical_coverage_test = original_coverage


def relabel_phase7_path(
    rows: list[dict[str, str]], path_convention: str, shutoff_status: str,
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for source in rows:
        row = dict(source)
        row["drawability_path"] = path_convention
        if row["drawability_status"] == "no_waiver_drawability_shutoff":
            row["drawability_status"] = shutoff_status
        elif row["drawability_status"] == "continued_after_analytical_warning":
            row["drawability_status"] = "continued_draw_or_waiver_after_warning"
        output.append(row)
    return output


def model_candidate(
    candidate: StructureCandidate, scenario_id: str,
) -> tuple[list[dict[str, str]], dict[str, Decimal | str]]:
    phase7_linked = scenario_id in PHASE7_NO_WAIVER_SCENARIOS
    base_scenario_id = PHASE7_NO_WAIVER_SCENARIOS.get(scenario_id, scenario_id)
    config = phase6.scenario_by_id(base_scenario_id)
    if phase7_linked:
        config = replace(config, scenario_id=scenario_id, no_waiver=True)
    if candidate.structure == "amend_extend":
        raise Phase7Error("Qualitative amendment candidate cannot be modeled")
    with candidate_parameter_override(candidate):
        if phase7_linked:
            with phase7_covenant_trigger_override():
                rows = phase6.run_case(
                    config, candidate.structure,
                    dec(candidate.amortization_percent) if candidate.amortization_percent is not None else Decimal("10"),
                )
        else:
            rows = phase6.run_case(
                config, candidate.structure,
                dec(candidate.amortization_percent) if candidate.amortization_percent is not None else Decimal("10"),
            )
        summary = phase6.scenario_summary(rows)
    if phase7_linked:
        rows = relabel_phase7_path(
            rows, "PHASE7_COVENANT_LINKED_NO_WAIVER",
            "phase7_covenant_linked_shutoff_active",
        )
    elif scenario_id in {"MODERATE_NO_WAIVER", "SEVERE_NO_WAIVER"}:
        rows = relabel_phase7_path(
            rows, "PHASE6_ANALYTICAL_SHUTOFF_SENSITIVITY",
            "phase6_analytical_shutoff_active",
        )
    elif candidate.structure == "proposed":
        rows = relabel_phase7_path(
            rows, "CONTINUED_DRAW_OR_WAIVER_SENSITIVITY",
            "not_applicable",
        )
    return rows, summary


def liquidity_presentation(
    candidate: StructureCandidate,
    monthly: list[dict[str, str]],
    through: date | None = None,
) -> dict[str, str]:
    """Return opening, subsequent, and all-in usable-liquidity extrema."""
    if any(value is None for value in (
        candidate.revolver_commitment, candidate.letters_of_credit,
        candidate.opening_revolver,
    )):
        return {
            "opening_usable_liquidity": "",
            "subsequent_minimum_usable_liquidity": "",
            "subsequent_minimum_liquidity_date": "",
            "all_in_minimum_usable_liquidity": "",
            "all_in_minimum_liquidity_date": "",
        }
    opening = (
        dec(candidate.revolver_commitment)
        - dec(candidate.letters_of_credit)
        - dec(candidate.opening_revolver)
    )
    eligible = [
        row for row in monthly
        if row["maturity_event"] != "yes"
        and (through is None or date.fromisoformat(row["month_end"]) <= through)
    ]
    if not eligible:
        raise Phase7Error(f"Missing subsequent liquidity records: {candidate.candidate_id}")
    minimum_row = min(
        eligible,
        key=lambda row: (dec(row["usable_liquidity"]), row["month_end"]),
    )
    subsequent = dec(minimum_row["usable_liquidity"])
    if opening <= subsequent:
        all_in = opening
        all_in_date = "OPENING_POSITION"
    else:
        all_in = subsequent
        all_in_date = minimum_row["month_end"]
    return {
        "opening_usable_liquidity": fmt(opening),
        "subsequent_minimum_usable_liquidity": fmt(subsequent),
        "subsequent_minimum_liquidity_date": minimum_row["month_end"],
        "all_in_minimum_usable_liquidity": fmt(all_in),
        "all_in_minimum_liquidity_date": all_in_date,
    }


def model_covenant_linked_no_waiver(
    candidate: StructureCandidate, scenario_id: str, base_scenario_id: str,
    limit_function,
) -> tuple[list[dict[str, str]], dict[str, Decimal | str]]:
    config = replace(
        phase6.scenario_by_id(base_scenario_id),
        scenario_id=scenario_id,
        no_waiver=True,
    )
    with candidate_parameter_override(candidate):
        with phase7_covenant_trigger_override(limit_function):
            rows = phase6.run_case(config, candidate.structure, dec(candidate.amortization_percent))
        summary = phase6.scenario_summary(rows)
    return relabel_phase7_path(
        rows, "PHASE7_COVENANT_LINKED_NO_WAIVER",
        "phase7_covenant_linked_shutoff_active",
    ), summary


def build_structure_comparison(
    candidates: tuple[StructureCandidate, ...],
) -> tuple[
    list[dict[str, str]],
    dict[str, list[dict[str, str]]],
    dict[tuple[str, str], list[dict[str, str]]],
]:
    ebitda = fy2025_lender_ebitda()
    retained = phase5_value("P5A-032")
    output: list[dict[str, str]] = []
    selected_monthly: dict[str, list[dict[str, str]]] = {}
    all_monthly: dict[tuple[str, str], list[dict[str, str]]] = {}
    counter = 0
    for candidate in candidates:
        if candidate.structure == "amend_extend":
            counter += 1
            output.append({
                "comparison_id": f"P7SC-{counter:03d}", "candidate_id": candidate.candidate_id,
                "candidate_name": candidate.name, "scenario_id": "NOT_MODELED",
                "scenario_treatment": "qualitative_live_alternative", "opening_term_principal": "",
                "opening_revolver": "", "opening_bank_debt": "", "retained_other_funded_debt": "",
                "opening_gross_funded_debt": "", "opening_gross_funded_leverage": "",
                "zero_cash_net_leverage": "", "capped_25m_cash_net_leverage_diagnostic": "",
                "cash_eligibility_status": N_D, "annual_amortization_percent": "",
                "annual_scheduled_term_principal": "", "cumulative_scheduled_principal_paid": "",
                "cumulative_cash_sweep": "", "cumulative_cash_interest": "",
                "revolver_commitment": "", "letters_of_credit": "",
                "opening_revolver_availability": "", "opening_usable_liquidity": "",
                "subsequent_minimum_usable_liquidity": "",
                "subsequent_minimum_liquidity_date": "",
                "all_in_minimum_usable_liquidity": "",
                "all_in_minimum_liquidity_date": "",
                "peak_revolver_including_opening": "",
                "peak_revolver_date": "", "first_analytical_threshold_failure": "",
                "first_50m_liquidity_warning": "", "first_cash_floor_failure": "",
                "revolver_capacity_exhaustion_date": "", "first_mandatory_payment_failure_date": "",
                "failed_obligation_type": "", "maturity_date": "",
                "unsupported_maturity_gap": "", "overall_path_status": N_D,
                "required_non_debt_contribution": "", "source_ids": "SRC-001;SRC-003",
                "upstream_ids": "PT-002:PT-024", "classification": "qualitative_not_determinable",
                "review_status": REVIEW, "limitations": candidate.limitations,
            })
            continue
        bank = dec(candidate.opening_term) + dec(candidate.opening_revolver)
        gross = bank + retained
        opening_availability = dec(candidate.revolver_commitment) - dec(candidate.letters_of_credit) - dec(candidate.opening_revolver)
        amort = dec(candidate.amortization_percent) if candidate.amortization_percent is not None else None
        annual_principal = dec(candidate.opening_term) * amort / Decimal("100") if amort is not None else Decimal("25")
        scenario_ids = MODELED_SCENARIOS
        if candidate.candidate_id == "STR-008":
            scenario_ids = (*scenario_ids, *PHASE7_NO_WAIVER_SCENARIOS)
        for scenario_id in scenario_ids:
            monthly, summary = model_candidate(candidate, scenario_id)
            liquidity = liquidity_presentation(candidate, monthly)
            all_monthly[(candidate.candidate_id, scenario_id)] = monthly
            if candidate.candidate_id == "STR-008":
                selected_monthly[scenario_id] = monthly
            counter += 1
            gross_leverage = ratio(gross, ebitda)
            cash_cap = Decimal("25")
            capped_net = ratio(gross - cash_cap, ebitda)
            output.append({
                "comparison_id": f"P7SC-{counter:03d}", "candidate_id": candidate.candidate_id,
                "candidate_name": candidate.name, "scenario_id": scenario_id,
                "scenario_treatment": (
                    "phase7_covenant_linked_no_waiver_recalculation"
                    if scenario_id in PHASE7_NO_WAIVER_SCENARIOS
                    else "inherited_phase6_analytical_shutoff_sensitivity"
                    if scenario_id in {"MODERATE_NO_WAIVER", "SEVERE_NO_WAIVER"}
                    else "phase6_operating_case_with_continued_draw_or_waiver_sensitivity"
                ),
                "opening_term_principal": fmt(candidate.opening_term),
                "opening_revolver": fmt(candidate.opening_revolver), "opening_bank_debt": fmt(bank),
                "retained_other_funded_debt": fmt(retained), "opening_gross_funded_debt": fmt(gross),
                "opening_gross_funded_leverage": fmt(gross_leverage),
                "zero_cash_net_leverage": fmt(gross_leverage),
                "capped_25m_cash_net_leverage_diagnostic": fmt(capped_net),
                "cash_eligibility_status": "pending_information_diagnostic_only",
                "annual_amortization_percent": fmt(amort),
                "annual_scheduled_term_principal": fmt(annual_principal),
                "cumulative_scheduled_principal_paid": fmt(summary["scheduled_principal_paid"]),
                "cumulative_cash_sweep": fmt(summary["cash_sweep"]),
                "cumulative_cash_interest": fmt(summary["cumulative_cash_interest"]),
                "revolver_commitment": fmt(candidate.revolver_commitment),
                "letters_of_credit": fmt(candidate.letters_of_credit),
                "opening_revolver_availability": fmt(opening_availability),
                **liquidity,
                "peak_revolver_including_opening": fmt(summary["peak_revolver_including_opening"]),
                "peak_revolver_date": str(summary["peak_revolver_date"]),
                "first_analytical_threshold_failure": str(summary["first_analytical_threshold_failure"]),
                "first_50m_liquidity_warning": str(summary["first_50m_analytical_liquidity_warning"]),
                "first_cash_floor_failure": str(summary["first_cash_floor_failure"]),
                "revolver_capacity_exhaustion_date": str(summary["revolver_capacity_exhaustion_date"]),
                "first_mandatory_payment_failure_date": str(summary["first_mandatory_payment_failure_date"]),
                "failed_obligation_type": str(summary["failed_obligation_type"]),
                "maturity_date": str(summary["maturity_date"]),
                "unsupported_maturity_gap": fmt(summary["unsupported_maturity_gap"]),
                "overall_path_status": str(summary["status"]),
                "required_non_debt_contribution": fmt(candidate.cash_contribution),
                "source_ids": "SRC-001;SRC-002;SRC-003",
                "upstream_ids": f"{candidate.candidate_id};{scenario_id};P6R-001:P6R-014",
                "classification": "formula_calculated_structure_scenario_comparison",
                "review_status": REVIEW,
                "limitations": candidate.limitations + " A lower debt balance caused by curtailed drawings or unpaid obligations is not improved performance.",
            })
    return output, selected_monthly, all_monthly


def leverage_limit(on_date: date) -> Decimal:
    if on_date <= date(2027, 10, 31):
        return Decimal("3.50")
    if on_date <= date(2028, 10, 31):
        return Decimal("3.25")
    return Decimal("3.00")


def leverage_warning(on_date: date) -> Decimal:
    return leverage_limit(on_date) - Decimal("0.25")


def leverage_limit_325_alternative(on_date: date) -> Decimal:
    return Decimal("3.25") if on_date <= date(2028, 10, 31) else Decimal("3.00")


def leverage_warning_325_alternative(on_date: date) -> Decimal:
    return Decimal("3.25") if on_date <= date(2027, 10, 31) else Decimal("3.00") if on_date <= date(2028, 10, 31) else Decimal("2.75")


def maximum_measure_status(
    value: Decimal | str, warning_threshold: Decimal, covenant_limit: Decimal,
) -> str:
    if value in {N_D_VALUE, N_M}:
        return N_D
    actual = dec(value)
    if actual > covenant_limit:
        return "breached"
    if actual >= warning_threshold:
        return "warning"
    return "compliant"


def minimum_measure_status(
    value: Decimal | str, warning_threshold: Decimal, covenant_minimum: Decimal,
) -> str:
    if value in {N_D_VALUE, N_M}:
        return N_D
    actual = dec(value)
    if actual < covenant_minimum:
        return "breached"
    if actual <= warning_threshold:
        return "warning"
    return "compliant"


def coverage_ratio(
    ebitda: Decimal | None, cash_interest: Decimal | None,
) -> Decimal | str:
    if ebitda is None or cash_interest is None:
        return N_D_VALUE
    if cash_interest <= 0:
        return N_M
    return ebitda / cash_interest


def overall_covenant_status(*statuses: str) -> str:
    if "breached" in statuses:
        return "breached"
    if N_D in statuses:
        return N_D
    return "compliant"


def overall_warning_status(*statuses: str) -> str:
    if "breached" in statuses:
        return "breached"
    if "warning" in statuses:
        return "warning"
    if N_D in statuses:
        return N_D
    return "compliant"


def build_covenant_tests(
    selected_monthly: dict[str, list[dict[str, str]]],
    limit_function=None, warning_function=None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if limit_function is None:
        limit_function = leverage_limit
    if warning_function is None:
        warning_function = leverage_warning
    retained = phase5_value("P5A-032")
    tests: list[dict[str, str]] = []
    headroom: list[dict[str, str]] = []
    test_counter = 0
    selected = next(item for item in candidate_definitions() if item.candidate_id == "STR-008")
    opening_bank = dec(selected.opening_term) + dec(selected.opening_revolver)
    opening_gross = opening_bank + retained
    opening_ebitda = fy2025_lender_ebitda()
    opening_liquidity = dec(selected.revolver_commitment) - dec(selected.letters_of_credit) - dec(selected.opening_revolver)
    for scenario_id, monthly in selected_monthly.items():
        rows: list[tuple[str, str, str, Decimal, Decimal, Decimal | None, Decimal | None, Decimal, Decimal, str, str, str, str, str, str]] = []
        rows.append((
            "2026-01-31", "FY2025", "closing_test", opening_gross, opening_bank,
            opening_ebitda, None, opening_liquidity, Decimal("25"),
            "available_before_covenant_test", "no", "no", "no", "no", "",
        ))
        for row in monthly:
            if row["maturity_event"] == "yes" or row["month_end"][5:7] not in {"01", "04", "07", "10"}:
                continue
            bank_debt = dec(row["ending_term_principal"]) + dec(row["ending_revolver"])
            ebitda = dec(row["ttm_lender_base_ebitda"]) if row["ttm_lender_base_ebitda"] else None
            coverage = dec(row["ebitda_cash_interest_coverage"]) if row["ebitda_cash_interest_coverage"] else None
            ltm_interest = ebitda / coverage if ebitda is not None and coverage is not None and coverage > 0 else None
            rows.append((
                row["month_end"], row["fiscal_year"], row["quarter"], bank_debt + retained,
                bank_debt, ebitda, ltm_interest, dec(row["usable_liquidity"]), dec(row["ending_cash"]), row["drawability_status"],
                "yes" if dec(row["cash_floor_shortfall"]) > TOLERANCE else "no",
                row["commitment_exhaustion_flag"], row["mandatory_payment_failure_flag"],
                "yes" if dec(row["unsupported_maturity_gap"]) > TOLERANCE else "no",
                row["monthly_stress_id"],
            ))
        for item in rows:
            (
                period_end, fiscal_year, quarter, gross_debt, bank_debt, ebitda,
                ltm_interest, liquidity, ending_cash, drawability, cash_floor_flag,
                exhaustion_flag, payment_flag, maturity_flag, source_row,
            ) = item
            test_counter += 1
            on_date = date.fromisoformat(period_end)
            limit = limit_function(on_date)
            warning = warning_function(on_date)
            leverage_value = ratio(gross_debt, ebitda)
            zero_cash = leverage_value
            cash_cap = min(Decimal("25"), max(Decimal("0"), ending_cash))
            capped_cash = ratio(gross_debt - cash_cap, ebitda)
            ratio_headroom = limit - dec(leverage_value) if leverage_value not in {N_D_VALUE, N_M} else leverage_value
            debt_headroom = limit * ebitda - gross_debt if ebitda is not None and ebitda > 0 else ratio(Decimal("0"), ebitda)
            break_even = gross_debt / limit
            coverage = coverage_ratio(ebitda, ltm_interest)
            coverage_ratio_headroom = dec(coverage) - Decimal("3.00") if coverage not in {N_D_VALUE, N_M} else coverage
            earnings_cushion = ebitda - Decimal("3.00") * ltm_interest if ebitda is not None and ltm_interest is not None and ltm_interest > 0 else coverage
            leverage_status = maximum_measure_status(leverage_value, warning, limit)
            coverage_status = minimum_measure_status(coverage, Decimal("3.50"), Decimal("3.00"))
            liquidity_status = minimum_measure_status(liquidity, Decimal("75"), Decimal("50"))
            operating_cash_status = "breached" if ending_cash < Decimal("25") else "compliant"
            covenant_status = overall_covenant_status(leverage_status, coverage_status, liquidity_status)
            warning_status = overall_warning_status(
                leverage_status, coverage_status, liquidity_status,
                "warning" if operating_cash_status == "breached" else "compliant",
            )
            input_status = (
                "complete" if leverage_value not in {N_D_VALUE, N_M}
                and coverage not in {N_D_VALUE, N_M} else N_D
            )
            test_id = f"P7CT-{test_counter:04d}"
            tests.append({
                "test_id": test_id, "scenario_id": scenario_id,
                "path_convention": monthly[0]["drawability_path"] if monthly else "",
                "period_end": period_end, "fiscal_year": fiscal_year, "quarter": quarter,
                "gross_funded_debt": fmt(gross_debt), "bank_debt": fmt(bank_debt),
                "eligible_cash_assumed": "0", "capped_cash_sensitivity": fmt(cash_cap),
                "ttm_lender_base_ebitda": fmt(ebitda),
                "gross_funded_leverage": fmt(leverage_value),
                "zero_cash_net_leverage": fmt(zero_cash),
                "capped_cash_net_leverage_diagnostic": fmt(capped_cash),
                "contractual_leverage_limit": fmt(limit),
                "leverage_ratio_headroom": fmt(ratio_headroom),
                "leverage_debt_headroom": fmt(debt_headroom),
                "leverage_break_even_ebitda": fmt(break_even),
                "ltm_cash_interest": fmt(ltm_interest) if ltm_interest is not None else N_D_VALUE,
                "interest_coverage": fmt(coverage),
                "contractual_interest_coverage_minimum": "3",
                "interest_coverage_ratio_headroom": fmt(coverage_ratio_headroom),
                "interest_coverage_earnings_cushion": fmt(earnings_cushion),
                "usable_liquidity": fmt(liquidity), "contractual_minimum_liquidity": "50",
                "liquidity_headroom": fmt(liquidity - Decimal("50")),
                "analyst_leverage_warning": fmt(warning), "analyst_coverage_warning": "3.5",
                "analyst_liquidity_warning": "75", "operating_cash": fmt(ending_cash),
                "operating_cash_floor": "25", "leverage_status": leverage_status,
                "coverage_status": coverage_status, "liquidity_status": liquidity_status,
                "operating_cash_status": operating_cash_status,
                "overall_warning_status": warning_status,
                "overall_covenant_status": covenant_status,
                "input_completeness_status": input_status,
                "cash_floor_failure_flag": cash_floor_flag,
                "commitment_exhaustion_flag": exhaustion_flag,
                "mandatory_payment_failure_flag": payment_flag,
                "maturity_shortfall_flag": maturity_flag, "drawability_status": drawability,
                "source_ids": "SRC-001;SRC-002;SRC-003",
                "upstream_ids": f"STR-008;{source_row};{scenario_id}",
                "classification": "proposed_covenant_test_not_official_compliance",
                "review_status": REVIEW,
                "limitations": "Gross covenant and zero-cash treatment are Phase 7 proposals. Capped-cash leverage is diagnostic only. N/D means a required input is missing; N/M is reserved for a nonpositive denominator.",
            })
            for metric, actual, threshold, gap, debt_gap, break_even_value, cushion, units, formula in (
                ("gross_funded_leverage", fmt(leverage_value), fmt(limit), fmt(ratio_headroom), fmt(debt_headroom), fmt(break_even), "", "turns", "ratio headroom = L - D/E; debt headroom = L*E - D; break-even EBITDA = D/L"),
                ("cash_interest_coverage", fmt(coverage), "3", fmt(coverage_ratio_headroom), "", "", fmt(earnings_cushion), "turns", "coverage cushion = E - C*I"),
                ("usable_liquidity", fmt(liquidity), "50", fmt(liquidity - Decimal("50")), "", "", "", MONEY, "liquidity headroom = usable liquidity - minimum liquidity"),
                ("analyst_leverage_warning", fmt(leverage_value), fmt(warning), fmt(warning - dec(leverage_value)) if leverage_value not in {N_D_VALUE, N_M} else leverage_value, "", "", "", "turns", "warning gap = warning threshold - D/E"),
            ):
                metric_status = {
                    "gross_funded_leverage": leverage_status,
                    "cash_interest_coverage": coverage_status,
                    "usable_liquidity": liquidity_status,
                    "analyst_leverage_warning": leverage_status,
                }[metric]
                headroom.append({
                    "headroom_id": f"P7H-{len(headroom)+1:05d}", "test_id": test_id,
                    "scenario_id": scenario_id, "period_end": period_end,
                    "framework": "proposed_contractual" if metric != "analyst_leverage_warning" else "analyst_warning",
                    "metric": metric, "actual": actual, "threshold": threshold,
                    "ratio_or_amount_headroom": gap, "debt_headroom": debt_gap,
                    "break_even_ebitda": break_even_value, "earnings_cushion": cushion,
                    "units": units,
                    "status": metric_status,
                    "formula": formula, "source_ids": "SRC-001;SRC-002;SRC-003",
                    "upstream_ids": test_id, "review_status": REVIEW,
                    "limitations": "N/D is reported when information is missing. N/M is reserved for a mathematically non-meaningful nonpositive denominator. Missing information is never converted to zero.",
                })
    return tests, headroom


def build_timeline(
    tests: list[dict[str, str]], selected_monthly: dict[str, list[dict[str, str]]],
    comparisons: list[dict[str, str]],
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    selected_results = {
        row["scenario_id"]: row for row in comparisons if row["candidate_id"] == "STR-008"
    }
    for scenario_id in selected_monthly:
        scenario_tests = sorted(
            [row for row in tests if row["scenario_id"] == scenario_id],
            key=lambda row: row["period_end"],
        )
        warning = next((row for row in scenario_tests if row["overall_warning_status"] in {"warning", "breached"}), None)
        breach = next((row for row in scenario_tests if row["overall_covenant_status"] == "breached"), None)
        monthly = selected_monthly[scenario_id]
        shutoff = next((row for row in monthly if row["drawability_status"] in {
            "phase7_covenant_linked_shutoff_active", "phase6_analytical_shutoff_active",
        }), None)
        result = selected_results[scenario_id]
        lead_days = ""
        if warning and breach:
            lead_days = str((date.fromisoformat(breach["period_end"]) - date.fromisoformat(warning["period_end"])).days)
        output.append({
            "timeline_id": f"P7TL-{len(output)+1:03d}", "scenario_id": scenario_id,
            "path_convention": monthly[0]["drawability_path"],
            "first_analyst_warning_date": warning["period_end"] if warning else "",
            "first_proposed_covenant_breach_date": breach["period_end"] if breach else "",
            "warning_lead_days_to_breach": lead_days,
            "first_drawability_shutoff_date": shutoff["month_end"] if shutoff else "",
            "first_50m_liquidity_failure_date": result["first_50m_liquidity_warning"],
            "first_cash_floor_failure_date": result["first_cash_floor_failure"],
            "revolver_capacity_exhaustion_date": result["revolver_capacity_exhaustion_date"],
            "first_mandatory_payment_failure_date": result["first_mandatory_payment_failure_date"],
            "failed_obligation_type": result["failed_obligation_type"],
            "maturity_date": result["maturity_date"], "maturity_shortfall": result["unsupported_maturity_gap"],
            "initial_intervention": "At warning: suspend share repurchases, notify lenders, begin monthly covenant/liquidity reporting, and deliver a 10-business-day action plan.",
            "breach_intervention": "At proposed breach: suspend all restricted payments. The Phase 7 covenant-linked no-waiver path terminates new drawings from the following month; the continued-draw path requires lender consent or continuing legal availability.",
            "continued_drawability_treatment": "Continued drawability after breach is a separate waiver-or-consent sensitivity and is not automatic.",
            "no_waiver_treatment": (
                "Draw shutoff follows the first proposed Phase 7 covenant breach and is recalculated from the following month."
                if monthly[0]["drawability_path"] == "PHASE7_COVENANT_LINKED_NO_WAIVER"
                else "Inherited Phase 6 analytical shutoff sensitivity; not a Phase 7 legal default or covenant-linked result."
                if monthly[0]["drawability_path"] == "PHASE6_ANALYTICAL_SHUTOFF_SENSITIVITY"
                else "No automatic shutoff; continued drawability requires lender consent or continuing availability after breach."
            ),
            "source_ids": "SRC-001;SRC-002;SRC-003", "upstream_ids": f"STR-008;{scenario_id}",
            "review_status": REVIEW,
            "limitations": "Warnings use an inclusive boundary and do not terminate drawings. Covenant-linked shutoff begins only after a tested breach; separate mechanical liquidity or capacity failures remain independently identified.",
        })
    return output


def build_covenant_summary(
    tests: list[dict[str, str]], selected_monthly: dict[str, list[dict[str, str]]],
    comparisons: list[dict[str, str]],
) -> list[dict[str, str]]:
    comparison_index = {
        row["scenario_id"]: row for row in comparisons if row["candidate_id"] == "STR-008"
    }
    output: list[dict[str, str]] = []
    for scenario_id, monthly in selected_monthly.items():
        scenario_tests = sorted(
            [row for row in tests if row["scenario_id"] == scenario_id],
            key=lambda row: row["period_end"],
        )
        closing = next(row for row in scenario_tests if row["period_end"] == "2026-01-31")

        def numeric(field: str) -> list[Decimal]:
            return [
                dec(row[field]) for row in scenario_tests
                if row[field] not in {"", N_D_VALUE, N_M, N_D}
            ]

        first_warning = next((row for row in scenario_tests if row["overall_warning_status"] in {"warning", "breached"}), None)
        first_breach = next((row for row in scenario_tests if row["overall_covenant_status"] == "breached"), None)
        first_liquidity = next((row for row in scenario_tests if row["liquidity_status"] == "breached"), None)
        first_cash_floor = next((row for row in scenario_tests if row["operating_cash_status"] == "breached"), None)
        first_shutoff = next((row for row in monthly if row["drawability_status"] in {
            "phase7_covenant_linked_shutoff_active", "phase6_analytical_shutoff_active",
        }), None)
        first_payment = next((row for row in monthly if row["mandatory_payment_failure_flag"] == "yes"), None)
        leverage_values = numeric("gross_funded_leverage")
        leverage_headroom = numeric("leverage_ratio_headroom")
        leverage_debt_headroom = numeric("leverage_debt_headroom")
        coverage_values = numeric("interest_coverage")
        coverage_headroom = numeric("interest_coverage_ratio_headroom")
        cash_values = numeric("operating_cash")
        result = comparison_index[scenario_id]
        output.append({
            "summary_id": f"P7CS-{len(output)+1:03d}", "scenario_id": scenario_id,
            "path_convention": monthly[0]["drawability_path"],
            "closing_warning_status": closing["overall_warning_status"],
            "closing_covenant_status": closing["overall_covenant_status"],
            "maximum_gross_funded_leverage": fmt(max(leverage_values)) if leverage_values else N_D_VALUE,
            "tightest_leverage_ratio_headroom": fmt(min(leverage_headroom)) if leverage_headroom else N_D_VALUE,
            "tightest_leverage_debt_headroom": fmt(min(leverage_debt_headroom)) if leverage_debt_headroom else N_D_VALUE,
            "minimum_cash_interest_coverage": fmt(min(coverage_values)) if coverage_values else N_D_VALUE,
            "tightest_coverage_ratio_headroom": fmt(min(coverage_headroom)) if coverage_headroom else N_D_VALUE,
            "opening_usable_liquidity": result["opening_usable_liquidity"],
            "subsequent_minimum_usable_liquidity": result["subsequent_minimum_usable_liquidity"],
            "subsequent_minimum_liquidity_date": result["subsequent_minimum_liquidity_date"],
            "all_in_minimum_usable_liquidity": result["all_in_minimum_usable_liquidity"],
            "all_in_minimum_liquidity_date": result["all_in_minimum_liquidity_date"],
            "tightest_liquidity_headroom": fmt(dec(result["all_in_minimum_usable_liquidity"]) - Decimal("50")),
            "minimum_operating_cash": fmt(min(cash_values)),
            "tightest_operating_cash_headroom": fmt(min(cash_values) - Decimal("25")),
            "first_warning_date": first_warning["period_end"] if first_warning else "",
            "first_breach_date": first_breach["period_end"] if first_breach else "",
            "first_draw_shutoff_date": first_shutoff["month_end"] if first_shutoff else "",
            "first_liquidity_shortfall_date": first_liquidity["period_end"] if first_liquidity else "",
            "first_cash_floor_failure_date": first_cash_floor["period_end"] if first_cash_floor else "",
            "first_mandatory_payment_failure_date": first_payment["month_end"] if first_payment else "",
            "failed_obligation_type": first_payment["failed_mandatory_obligation_type"] if first_payment else "",
            "ultimate_maturity_gap": result["unsupported_maturity_gap"],
            "input_completeness_status": (
                "complete" if all(row["input_completeness_status"] == "complete" for row in scenario_tests)
                else N_D
            ),
            "source_ids": "SRC-001;SRC-002;SRC-003",
            "upstream_ids": f"STR-008;{scenario_id};{';'.join(row['test_id'] for row in scenario_tests)}",
            "review_status": REVIEW,
            "limitations": "Liquidity extrema use the opening position plus every subsequent non-maturity month. Covenant tests remain quarterly; monthly drawability and payment events remain separately traced. N/D remains visible when a complete LTM input is unavailable.",
        })
    return output


def build_leverage_covenant_comparison(
    candidates: tuple[StructureCandidate, ...],
    selected_monthly: dict[str, list[dict[str, str]]],
) -> list[dict[str, str]]:
    selected = next(item for item in candidates if item.candidate_id == "STR-008")
    output: list[dict[str, str]] = []
    for family, base_id, proposed_id in (
        ("moderate", "MODERATE_UNMITIGATED", "MODERATE_PHASE7_COVENANT_NO_WAIVER"),
        ("severe", "SEVERE_UNMITIGATED", "SEVERE_PHASE7_COVENANT_NO_WAIVER"),
    ):
        cases: list[tuple[str, Decimal, object, object, list[dict[str, str]], dict[str, Decimal | str]]] = []
        proposed_rows = selected_monthly[proposed_id]
        cases.append(("proposed_3.50x_initial", Decimal("3.50"), leverage_limit, leverage_warning, proposed_rows, phase6.scenario_summary(proposed_rows)))
        alt_id = f"{family.upper()}_PHASE7_325_COVENANT_NO_WAIVER"
        alt_rows, alt_summary = model_covenant_linked_no_waiver(
            selected, alt_id, base_id, leverage_limit_325_alternative,
        )
        cases.append(("alternative_3.25x_initial", Decimal("3.25"), leverage_limit_325_alternative, leverage_warning_325_alternative, alt_rows, alt_summary))
        for case_name, initial_limit, limit_fn, warning_fn, monthly, summary in cases:
            test_rows, _ = build_covenant_tests(
                {monthly[0]["scenario_id"]: monthly}, limit_fn, warning_fn,
            )
            first_warning = next((row for row in test_rows if row["overall_warning_status"] in {"warning", "breached"}), None)
            first_breach = next((row for row in test_rows if row["overall_covenant_status"] == "breached"), None)
            first_shutoff = next((row for row in monthly if row["drawability_status"] == "phase7_covenant_linked_shutoff_active"), None)
            first_payment = next((row for row in monthly if row["mandatory_payment_failure_flag"] == "yes"), None)
            liquidity_at_breach = ""
            if first_breach:
                breach_month = next(row for row in monthly if row["month_end"] == first_breach["period_end"])
                liquidity_at_breach = breach_month["usable_liquidity"]
            days_to_payment = ""
            if first_breach and first_payment:
                days_to_payment = str((
                    date.fromisoformat(first_payment["month_end"])
                    - date.fromisoformat(first_breach["period_end"])
                ).days)
            closing = next(row for row in test_rows if row["period_end"] == "2026-01-31")
            output.append({
                "comparison_id": f"P7LC-{len(output)+1:03d}", "scenario_family": family,
                "covenant_case": case_name, "initial_leverage_limit": fmt(initial_limit),
                "warning_threshold": "3.25", "closing_leverage": closing["gross_funded_leverage"],
                "closing_status": closing["leverage_status"],
                "first_warning_date": first_warning["period_end"] if first_warning else "",
                "first_breach_date": first_breach["period_end"] if first_breach else "",
                "liquidity_at_first_breach": liquidity_at_breach,
                "first_draw_shutoff_date": first_shutoff["month_end"] if first_shutoff else "",
                "first_mandatory_payment_failure_date": first_payment["month_end"] if first_payment else "",
                "days_breach_to_payment_failure": days_to_payment,
                "ultimate_maturity_gap": fmt(summary["unsupported_maturity_gap"]),
                "source_ids": "SRC-001;SRC-002;SRC-003",
                "upstream_ids": f"STR-008;{monthly[0]['scenario_id']}",
                "review_status": REVIEW,
                "limitations": "The 3.25x and 3.50x cases change only the initial leverage covenant trigger. A warning is inclusive and does not terminate drawings; shutoff begins in the month after a tested breach.",
            })
    return output


def build_sizing_rows(
    candidates: tuple[StructureCandidate, ...],
    all_monthly: dict[tuple[str, str], list[dict[str, str]]],
) -> list[dict[str, str]]:
    ebitda = fy2025_lender_ebitda()
    retained = phase5_value("P5A-032")
    reference_revolver = phase5_value("P5A-026")
    reference_term = phase5_value("P5A-025")
    reference_total = reference_term + reference_revolver + retained
    candidate_index = {item.candidate_id: item for item in candidates}

    def sizing_liquidity(candidate: StructureCandidate) -> dict[str, str]:
        monthly = all_monthly.get((candidate.candidate_id, "BASE"))
        if monthly is None:
            monthly, _ = model_candidate(candidate, "BASE")
        return liquidity_presentation(candidate, monthly)

    def make(
        analysis: str, threshold: Decimal, cash: Decimal, term: Decimal,
        revolver: Decimal, required_source: Decimal, status: str,
        liquidity_candidate: StructureCandidate, limitations: str,
    ) -> dict[str, str]:
        max_total = ebitda * threshold + cash
        max_bank = max_total - retained
        analytical_term_capacity = max_bank - revolver
        resulting_total = term + revolver + retained
        resulting_leverage = (resulting_total - cash) / ebitda
        return {
            "sizing_id": f"P7SZ-{len(rows)+1:03d}", "analysis": analysis,
            "ebitda": fmt(ebitda), "leverage_threshold": fmt(threshold),
            "cash_netting": fmt(cash), "maximum_total_funded_debt": fmt(max_total),
            "retained_other_funded_debt": fmt(retained), "maximum_bank_debt": fmt(max_bank),
            "opening_revolver": fmt(revolver),
            "analytical_term_capacity": fmt(analytical_term_capacity),
            "term_commitment": fmt(term), "initial_term_funding": fmt(term),
            "reference_term_funding": fmt(reference_term),
            "required_non_debt_contribution": fmt(required_source),
            "undrawn_term_commitment": "0",
            "unused_term_commitment_treatment": "none; funded term equals commitment and no delayed-draw availability is assumed",
            "resulting_total_funded_debt": fmt(resulting_total),
            "resulting_leverage": fmt(resulting_leverage),
            "headroom_or_shortfall": fmt(max_total - resulting_total), "status": status,
            **sizing_liquidity(liquidity_candidate),
            "source_ids": "SRC-001;SRC-002;SRC-003",
            "upstream_ids": "S2B-0099;P5A-025;P5A-026;P5A-032;STR-003;STR-007;STR-008",
            "owner_review_status": REVIEW, "limitations": limitations,
        }

    rows: list[dict[str, str]] = []
    rows.append(make(
        "$650m reference against 3.25x zero-cash total funded leverage",
        Decimal("3.25"), Decimal("0"), reference_term, reference_revolver, Decimal("0"),
        "FAIL_SHORTFALL", candidate_index["STR-003"],
        "Reference debt exceeds the test by the negative headroom. This is not cured with book cash.",
    ))
    rows.append(make(
        "$650m reference against proposed 3.50x zero-cash total funded covenant",
        Decimal("3.50"), Decimal("0"), reference_term, reference_revolver, Decimal("0"),
        "PASS_WITH_LIMITED_HEADROOM", candidate_index["STR-003"],
        "This does not establish lender acceptance of the proposed threshold or final definitions.",
    ))
    rows.append(make(
        "$650m reference with capped $25m cash diagnostic at 3.25x",
        Decimal("3.25"), Decimal("25"), reference_term, reference_revolver, Decimal("0"),
        "DIAGNOSTIC_ONLY", candidate_index["STR-003"],
        "Eligible cash remains pending information; this row cannot support closing sizing.",
    ))
    exact = candidate_index["STR-009"]
    rows.append(make(
        "Exact total-funded-debt capacity at 3.25x with reference revolver allocation",
        Decimal("3.25"), Decimal("0"), dec(exact.opening_term), dec(exact.opening_revolver),
        dec(exact.cash_contribution), "EXACT_BOUNDARY_WARNING_ACTIVE", exact,
        "This is an analytical total-funded-debt boundary, not a negotiated term-loan amount. Equality activates the inclusive analyst warning.",
    ))
    rounded_exception = candidate_index["STR-010"]
    rows.append(make(
        "$640m term with $10m contribution and reference revolver allocation",
        Decimal("3.25"), Decimal("0"), dec(rounded_exception.opening_term),
        dec(rounded_exception.opening_revolver), dec(rounded_exception.cash_contribution),
        "MARGINAL_SIZING_EXCEPTION", rounded_exception,
        "The rounded structure exceeds the 3.25x total-funded-debt capacity by $0.149m; rounding does not conceal the exception.",
    ))
    rounded_capacity = candidate_index["STR-011"]
    rows.append(make(
        "$640m term with revolver reallocated inside exact 3.25x bank-debt capacity",
        Decimal("3.25"), Decimal("0"), dec(rounded_capacity.opening_term),
        dec(rounded_capacity.opening_revolver), dec(rounded_capacity.cash_contribution),
        "EXACT_BOUNDARY_WARNING_ACTIVE", rounded_capacity,
        "Term and revolver allocations change, but total funded debt remains at the same analytical capacity. Equality activates the warning.",
    ))
    selected = candidate_index["STR-008"]
    rows.append(make(
        "$635m practical term with $15m contribution and reference revolver allocation",
        Decimal("3.25"), Decimal("0"), dec(selected.opening_term),
        dec(selected.opening_revolver), dec(selected.cash_contribution),
        "PASS_BELOW_WARNING_WITH_MODEST_CUSHION", selected,
        "The practical selected amount leaves measurable headroom to the 3.25x analyst warning and requires a separately evidenced non-debt source.",
    ))
    rounded_639 = replace(
        selected, candidate_id="SIZING-639", name="$639m rounded sizing alternative",
        opening_term=Decimal("639"), cash_contribution=Decimal("11"),
        selection_status="not_selected",
    )
    rows.append(make(
        "$639m rounded term at or below analytical capacity",
        Decimal("3.25"), Decimal("0"), Decimal("639"), reference_revolver,
        Decimal("11"), "PASS_BELOW_WARNING_WITH_MINIMAL_CUSHION", rounded_639,
        "This rounded alternative is below the exact boundary but leaves only $0.851m of debt headroom to the warning threshold.",
    ))
    cash_625 = candidate_index["STR-007"]
    rows.append(make(
        "$625m term with conditional $25m non-debt contribution at 3.25x",
        Decimal("3.25"), Decimal("0"), dec(cash_625.opening_term),
        dec(cash_625.opening_revolver), dec(cash_625.cash_contribution),
        "PASS_IF_SEPARATE_SOURCE_EXISTS", cash_625,
        "The contribution must be incremental to the $25m operating cash floor and supported by evidence.",
    ))
    rows.append({
        "sizing_id": f"P7SZ-{len(rows)+1:03d}", "analysis": "Reference opening total funded debt control",
        "ebitda": fmt(ebitda), "leverage_threshold": "", "cash_netting": "0",
        "maximum_total_funded_debt": "", "retained_other_funded_debt": fmt(retained),
        "maximum_bank_debt": "", "opening_revolver": fmt(reference_revolver),
        "analytical_term_capacity": "", "term_commitment": fmt(reference_term),
        "initial_term_funding": fmt(reference_term), "reference_term_funding": fmt(reference_term),
        "required_non_debt_contribution": "0", "undrawn_term_commitment": "0",
        "unused_term_commitment_treatment": "none; fully funded reference term",
        "resulting_total_funded_debt": fmt(reference_total),
        "resulting_leverage": fmt(reference_total / ebitda), "headroom_or_shortfall": "",
        **sizing_liquidity(candidate_index["STR-003"]),
        "status": "CONTROL", "source_ids": "SRC-001;SRC-002;SRC-003",
        "upstream_ids": "S2B-0099;P5A-025;P5A-026;P5A-032",
        "owner_review_status": REVIEW,
        "limitations": "Opening total funded debt includes the retained $62.619m finance-lease/other-debt proxy. Final contractual treatment is subject to legal definitions.",
    })
    return rows


def path_status_events(
    candidate: StructureCandidate, monthly: list[dict[str, str]],
    through: date = COMMON_HORIZON_END,
    limit_function=None,
) -> dict[str, str]:
    if limit_function is None:
        limit_function = leverage_limit
    retained = phase5_value("P5A-032")
    observations: list[tuple[date, str, str]] = []
    opening_debt = dec(candidate.opening_term) + dec(candidate.opening_revolver) + retained
    opening_leverage = ratio(opening_debt, fy2025_lender_ebitda())
    opening_limit = limit_function(date(2026, 1, 31))
    opening_warning = min(Decimal("3.25"), opening_limit)
    opening_leverage_status = maximum_measure_status(opening_leverage, opening_warning, opening_limit)
    observations.append((date(2026, 1, 31), opening_leverage_status, N_D))
    for row in monthly:
        on_date = date.fromisoformat(row["month_end"])
        if on_date > through or row["maturity_event"] == "yes" or not phase6.phase5.is_quarter_end(on_date):
            continue
        ebitda = dec(row["ttm_lender_base_ebitda"]) if row["ttm_lender_base_ebitda"] else None
        gross_debt = dec(row["ending_term_principal"]) + dec(row["ending_revolver"]) + retained
        leverage_value = ratio(gross_debt, ebitda)
        limit = limit_function(on_date)
        warning = min(leverage_warning(on_date), limit)
        leverage_status = maximum_measure_status(leverage_value, warning, limit)
        coverage_value: Decimal | str = (
            dec(row["ebitda_cash_interest_coverage"])
            if row["ebitda_cash_interest_coverage"] else N_D_VALUE
        )
        coverage_status = minimum_measure_status(coverage_value, Decimal("3.50"), Decimal("3.00"))
        liquidity_status = minimum_measure_status(dec(row["usable_liquidity"]), Decimal("75"), Decimal("50"))
        covenant = overall_covenant_status(leverage_status, coverage_status, liquidity_status)
        warning_status = overall_warning_status(leverage_status, coverage_status, liquidity_status)
        observations.append((on_date, warning_status, covenant))
    first_warning = next((item[0].isoformat() for item in observations if item[1] in {"warning", "breached"}), "")
    first_breach = next((item[0].isoformat() for item in observations if item[2] == "breached"), "")
    path_warning = "warning" if first_warning else N_D if any(item[1] == N_D for item in observations) else "compliant"
    path_covenant = "breached" if first_breach else N_D if any(item[2] == N_D for item in observations) else "compliant"
    return {
        "first_warning_date": first_warning,
        "first_breach_date": first_breach,
        "warning_status": path_warning,
        "covenant_status": path_covenant,
    }


def build_common_horizon_comparison(
    candidates: tuple[StructureCandidate, ...],
    all_monthly: dict[tuple[str, str], list[dict[str, str]]],
) -> list[dict[str, str]]:
    retained = phase5_value("P5A-032")
    output: list[dict[str, str]] = []
    for candidate in candidates:
        if candidate.structure == "amend_extend":
            output.append({
                field: ({
                    "common_horizon_id": f"P7CH-{len(output)+1:03d}",
                    "candidate_id": candidate.candidate_id, "candidate_name": candidate.name,
                    "scenario_id": "BASE", "period_start": "2026-02-01",
                    "period_end": COMMON_HORIZON_END.isoformat(), "comparison_status": N_D,
                    "source_ids": "SRC-001;SRC-003", "upstream_ids": "PT-002:PT-024",
                    "review_status": REVIEW, "limitations": candidate.limitations,
                }.get(field, "")) for field in COMMON_HORIZON_FIELDS
            })
            continue
        monthly = [
            row for row in all_monthly[(candidate.candidate_id, "BASE")]
            if date.fromisoformat(row["month_end"]) <= COMMON_HORIZON_END
        ]
        if not monthly:
            raise Phase7Error(f"Missing common-horizon rows: {candidate.candidate_id}")
        last = monthly[-1]
        liquidity = liquidity_presentation(candidate, monthly, COMMON_HORIZON_END)
        events = path_status_events(candidate, monthly)
        unpaid = sum((
            dec(row["cash_interest_shortfall"])
            + dec(row["scheduled_principal_shortfall"])
            + dec(row["retained_obligation_shortfall"])
            for row in monthly
        ), Decimal("0"))
        ending_bank = dec(last["ending_term_principal"]) + dec(last["ending_revolver"])
        output.append({
            "common_horizon_id": f"P7CH-{len(output)+1:03d}",
            "candidate_id": candidate.candidate_id, "candidate_name": candidate.name,
            "scenario_id": "BASE", "period_start": "2026-02-01",
            "period_end": COMMON_HORIZON_END.isoformat(),
            "cumulative_cash_interest": fmt(sum((dec(row["cash_interest_paid"]) for row in monthly), Decimal("0"))),
            "cumulative_scheduled_principal": fmt(sum((dec(row["scheduled_term_principal_paid"]) for row in monthly), Decimal("0"))),
            "cumulative_ecf_sweep": fmt(sum((dec(row["cash_sweep"]) for row in monthly), Decimal("0"))),
            "cumulative_revolver_repayments": fmt(sum((dec(row["revolver_repayment"]) for row in monthly), Decimal("0"))),
            "ending_term_debt": last["ending_term_principal"],
            "ending_revolver_debt": last["ending_revolver"],
            "ending_total_bank_debt": fmt(ending_bank),
            "ending_total_funded_debt": fmt(ending_bank + retained),
            "peak_revolver_usage": fmt(max([dec(candidate.opening_revolver), *(dec(row["ending_revolver"]) for row in monthly)])),
            **liquidity,
            "unpaid_mandatory_obligations": fmt(unpaid),
            **events, "comparison_status": "common_horizon_comparable",
            "source_ids": "SRC-001;SRC-002;SRC-003",
            "upstream_ids": f"{candidate.candidate_id};BASE;P6M-BASE",
            "review_status": REVIEW,
            "limitations": "All quantitative candidates use the same 2026-02-01 through 2029-07-31 horizon. The existing-facility maturity event is shown separately in the ultimate-maturity view.",
        })
    return output


def build_ultimate_maturity_comparison(
    candidates: tuple[StructureCandidate, ...],
    all_monthly: dict[tuple[str, str], list[dict[str, str]]],
) -> list[dict[str, str]]:
    retained = phase5_value("P5A-032")
    output: list[dict[str, str]] = []
    for candidate in candidates:
        if candidate.structure == "amend_extend":
            output.append({field: ({
                "maturity_comparison_id": f"P7UM-{len(output)+1:03d}",
                "candidate_id": candidate.candidate_id, "candidate_name": candidate.name,
                "scenario_id": "BASE", "period_start": "2026-02-01",
                "comparison_status": N_D, "source_ids": "SRC-001;SRC-003",
                "upstream_ids": "PT-002:PT-024", "review_status": REVIEW,
                "limitations": candidate.limitations,
            }.get(field, "")) for field in ULTIMATE_MATURITY_FIELDS})
            continue
        monthly = all_monthly[(candidate.candidate_id, "BASE")]
        maturity_row = next((row for row in monthly if row["maturity_event"] == "yes"), None)
        if maturity_row is None:
            raise Phase7Error(f"Missing maturity row: {candidate.candidate_id}")
        interim_failure = next((
            row for row in monthly if row["maturity_event"] != "yes"
            and row["mandatory_payment_failure_flag"] == "yes"
        ), None)
        final_bank = dec(maturity_row["ending_term_principal"]) + dec(maturity_row["ending_revolver"])
        maturity_date = candidate.maturity or date.fromisoformat(maturity_row["month_end"])
        horizon_months = (maturity_date.year - 2026) * 12 + maturity_date.month - 1
        output.append({
            "maturity_comparison_id": f"P7UM-{len(output)+1:03d}",
            "candidate_id": candidate.candidate_id, "candidate_name": candidate.name,
            "scenario_id": "BASE", "period_start": "2026-02-01",
            "maturity_date": maturity_date.isoformat(), "horizon_months": str(horizon_months),
            "cumulative_cash_interest": fmt(sum((dec(row["cash_interest_paid"]) for row in monthly), Decimal("0"))),
            "cumulative_scheduled_principal": fmt(sum((dec(row["scheduled_term_principal_paid"]) for row in monthly), Decimal("0"))),
            "cumulative_ecf_sweep": fmt(sum((dec(row["cash_sweep"]) for row in monthly), Decimal("0"))),
            "final_term_debt": maturity_row["ending_term_principal"],
            "final_revolver_debt": maturity_row["ending_revolver"],
            "final_total_bank_debt": fmt(final_bank),
            "final_total_funded_debt": fmt(final_bank + retained),
            "maturity_payment_due": maturity_row["maturity_principal_due"],
            "available_cash_applied": maturity_row["maturity_principal_paid"],
            "unsupported_maturity_gap": maturity_row["unsupported_maturity_gap"],
            "first_interim_payment_failure_date": interim_failure["month_end"] if interim_failure else "",
            "failed_obligation_type": interim_failure["failed_mandatory_obligation_type"] if interim_failure else "",
            "comparison_status": "different_contractual_horizon_not_directly_comparable",
            "source_ids": "SRC-001;SRC-002;SRC-003",
            "upstream_ids": f"{candidate.candidate_id};BASE;{maturity_row['monthly_stress_id']}",
            "review_status": REVIEW,
            "limitations": "Existing and proposed structures have different maturities. Interest, amortization, cash generation and maturity balances are not directly comparable without the common-horizon view.",
        })
    return output


def build_sources_uses_reconciliation(
    candidates: tuple[StructureCandidate, ...],
) -> list[dict[str, str]]:
    retained = phase5_value("P5A-032")
    ebitda = fy2025_lender_ebitda()
    output: list[dict[str, str]] = []
    for candidate in candidates:
        base = {
            "reconciliation_id": f"P7SU-{len(output)+1:03d}",
            "candidate_id": candidate.candidate_id, "candidate_name": candidate.name,
            "source_ids": "SRC-001;SRC-002;SRC-003", "upstream_ids": candidate.candidate_id,
            "review_status": REVIEW,
        }
        if candidate.structure != "proposed":
            output.append({field: base.get(field, N_D if field in {"status", "warning_status", "covenant_status"} else "") for field in SOURCES_USES_FIELDS} | {
                "limitations": "Existing retention and amend/extend are not the Phase 4 reference refinancing sources-and-uses case.",
            })
            continue
        term = dec(candidate.opening_term)
        revolver = dec(candidate.opening_revolver)
        contribution = dec(candidate.cash_contribution)
        total_sources = term + revolver + contribution
        bank = term + revolver
        total_debt = bank + retained
        leverage_value = total_debt / ebitda
        warning = maximum_measure_status(leverage_value, Decimal("3.25"), Decimal("3.50"))
        output.append({
            **base, "term_commitment": fmt(term), "initial_term_funding": fmt(term),
            "opening_revolver": fmt(revolver), "required_non_debt_contribution": fmt(contribution),
            "total_sources": fmt(total_sources), "reference_closing_uses": fmt(REFERENCE_CLOSING_USES),
            "sources_less_uses": fmt(total_sources - REFERENCE_CLOSING_USES),
            "opening_bank_debt": fmt(bank), "retained_other_funded_debt": fmt(retained),
            "opening_total_funded_debt": fmt(total_debt), "closing_gross_leverage": fmt(leverage_value),
            "warning_status": warning,
            "covenant_status": "breached" if leverage_value > Decimal("3.50") else "compliant",
            "undrawn_term_commitment": "0",
            "unused_term_commitment_treatment": "none; funded term equals commitment and no delayed-draw availability is assumed",
            "status": "compliant" if abs(total_sources - REFERENCE_CLOSING_USES) <= TOLERANCE else "breached",
            "limitations": "The reference closing-use total remains subject to final payoff, fee, hedge and LC evidence. Non-debt contributions remain pending evidence and cannot use the $25m operating cash floor.",
        })
    return output


def build_final_assumptions(
    candidates: tuple[StructureCandidate, ...],
    all_monthly: dict[tuple[str, str], list[dict[str, str]]],
) -> list[dict[str, str]]:
    selected = next(item for item in candidates if item.candidate_id == "STR-008")
    ebitda = fy2025_lender_ebitda()
    retained = phase5_value("P5A-032")
    total_capacity = ebitda * Decimal("3.25")
    bank_capacity = total_capacity - retained
    exact_term_capacity = bank_capacity - phase5_value("P5A-026")
    opening_total_debt = dec(selected.opening_term) + dec(selected.opening_revolver) + retained
    liquidity = liquidity_presentation(selected, all_monthly[("STR-008", "BASE")])
    values = [
        ("P7FA-001", "selection", "selected_candidate", "STR-008", "identifier", "Owner-reviewed Phase 7 provisional structure for further underwriting; not a lender commitment or final credit recommendation.", "owner_reviewed_provisional"),
        ("P7FA-002", "facilities", "term_commitment", fmt(selected.opening_term), MONEY, "Practical rounded term commitment, fully funded at closing subject to supported uses.", "proposed"),
        ("P7FA-003", "facilities", "initial_term_funding", fmt(selected.opening_term), MONEY, "Equals the proposed term commitment; no delayed-draw term capacity is assumed.", "proposed"),
        ("P7FA-004", "sizing", "analytical_total_funded_debt_capacity", fmt(total_capacity), MONEY, "3.25 * FY2025 lender-base EBITDA; analytical boundary, not term-loan capacity.", "formula_calculated"),
        ("P7FA-005", "sizing", "analytical_bank_debt_capacity", fmt(bank_capacity), MONEY, "Total funded-debt capacity less retained other funded debt.", "formula_calculated"),
        ("P7FA-006", "sizing", "analytical_term_capacity_at_reference_revolver", fmt(exact_term_capacity), MONEY, "Bank-debt capacity less the reference opening revolver allocation; not a negotiated facility amount.", "formula_calculated"),
        ("P7FA-007", "funding", "required_non_debt_contribution", fmt(selected.cash_contribution), MONEY, "Reference closing uses less selected term funding and opening revolver.", "conditional_pending_evidence"),
        ("P7FA-008", "facilities", "opening_revolver_draw", fmt(selected.opening_revolver), MONEY, "Phase 4-6 reference residual after fees and payoff.", "inherited_reference"),
        ("P7FA-009", "facilities", "revolver_commitment", "300", MONEY, "Committed revolving capacity.", "proposed"),
        ("P7FA-010", "facilities", "letters_of_credit", "6.2", MONEY, "Replacement LC usage deducted once from availability.", "inherited_reference"),
        ("P7FA-011", "facilities", "total_term_plus_revolver_commitments", fmt(dec(selected.opening_term) + Decimal("300")), MONEY, "Term commitment plus revolver commitment; not equal to funded debt.", "formula_calculated"),
        ("P7FA-012", "facilities", "undrawn_term_commitment", "0", MONEY, "Funded term equals commitment at closing.", "proposed"),
        ("P7FA-013", "facilities", "unused_term_commitment_treatment", "cancelled_or_unavailable_at_closing", "text", "No continuing delayed-draw or ordinary undrawn term availability is assumed.", "proposed"),
        ("P7FA-014", "sizing", "opening_total_funded_debt", fmt(opening_total_debt), MONEY, "Initial term + opening revolver + retained other funded debt.", "formula_calculated"),
        ("P7FA-015", "sizing", "closing_gross_funded_leverage", fmt(opening_total_debt / ebitda), "turns", "Opening total funded debt / FY2025 lender-base EBITDA.", "formula_calculated"),
        ("P7FA-016", "amortization", "annual_amortization", "7.5", "percent_of_original_funded_term", "Paid 1.875% of original funded principal quarterly.", "proposed"),
        ("P7FA-017", "maturity", "term_and_revolver_maturity", "2031-01-31", "date", "Five years from hypothetical close.", "proposed"),
        ("P7FA-018", "pricing", "term_and_drawn_revolver_margin", "250-350", "basis_points_over_SOFR", "Phase 4 sensitivity range; no lender quote.", "pending_lender_proposal"),
        ("P7FA-019", "pricing", "modeled_all_in_rate", "6.57", "percent", "3.57% base-rate proxy + 300 bps midpoint for comparison only.", "testing_assumption"),
        ("P7FA-020", "cash", "operating_cash_floor", "25", MONEY, "Separate model reserve; not covenant eligible cash or a closing source.", "model_control"),
        ("P7FA-021", "cash", "contractual_cash_netting", "0", MONEY, "Gross leverage proposal gives no cash-netting credit.", "proposed"),
        ("P7FA-022", "covenants", "maximum_gross_total_funded_leverage_initial", "3.5", "turns", "Through 2027-10-31; maintenance cushion above 3.25x sizing, not additional funding capacity.", "proposed"),
        ("P7FA-023", "covenants", "maximum_gross_total_funded_leverage_step1", "3.25", "turns", "2027-11-01 through 2028-10-31.", "proposed"),
        ("P7FA-024", "covenants", "maximum_gross_total_funded_leverage_step2", "3", "turns", "From 2028-11-01 through maturity.", "proposed"),
        ("P7FA-025", "covenants", "minimum_cash_interest_coverage", "3", "turns", "LTM lender EBITDA / LTM cash interest paid or payable.", "proposed"),
        ("P7FA-026", "covenants", "minimum_usable_liquidity", "50", MONEY, "Eligible accessible cash plus legally drawable revolver availability.", "proposed"),
        ("P7FA-027", "warnings", "leverage_warning_schedule", "3.25/3.00/2.75", "turns", "Inclusive activation: leverage greater than or equal to the warning threshold triggers warning.", "proposed"),
        ("P7FA-028", "warnings", "cash_interest_coverage_warning", "3.5", "turns", "Early intervention before the 3.00x proposed covenant.", "proposed"),
        ("P7FA-029", "warnings", "usable_liquidity_warning", "75", MONEY, "Early intervention before the $50m proposed covenant.", "proposed"),
        ("P7FA-030", "prepayment", "annual_excess_cash_flow_sweep", "50", "percent", "After revolver repayment; no step-down; subject to stated cash safeguards.", "proposed"),
        ("P7FA-031", "distributions", "share_repurchase_rule", "prohibited_if_debt_funded_or_revolver_outstanding", "text", "Both narrow and broad Phase 6 funding flags are addressed.", "proposed"),
        ("P7FA-032", "distributions", "dividend_rule", "no_default_and_leverage_lte_3.00x_and_liquidity_gte_75", "text", "Pro forma after payment; all restricted payments suspended after breach.", "proposed"),
        ("P7FA-033", "hold", "participating_bank_hold_cap", "50", MONEY, "Maximum participating bank exposure; facility allocation pending.", "inherited_proposal"),
        ("P7FA-034", "security", "collateral", "eligible_domestic_obligor_personal_property", "text", "Subject to lien, exclusion, perfection and permitted-lien diligence.", "proposed"),
        ("P7FA-035", "security", "guarantors", "eligible_material_domestic_subsidiaries", "text", "Entity-by-entity post-Tyman schedule required.", "proposed"),
        ("P7FA-036", "drawability", "covenant_linked_no_waiver", "shutoff_month_after_tested_breach", "text", "Warning alone does not terminate draws; inherited Phase 6 sensitivity remains separate.", "proposed"),
        ("P7FA-037", "comparison", "common_horizon_end", COMMON_HORIZON_END.isoformat(), "date", "Like-for-like financing comparison through July 31, 2029.", "proposed"),
        ("P7FA-038", "reporting", "reporting_cadence", "monthly_15_quarterly_45_annual_90", "days", "Liquidity/control, quarterly certificate and annual audited reporting.", "proposed"),
        ("P7FA-039", "closing", "required_conditions", "CP-001:CP-024", "identifiers", "No condition is assumed satisfied by public evidence alone.", "inherited_required_conditions"),
        ("P7FA-040", "liquidity_presentation", "opening_usable_liquidity", liquidity["opening_usable_liquidity"], MONEY, "Revolver commitment less letters of credit and opening revolver borrowing; no cash add-on.", "formula_calculated"),
        ("P7FA-041", "liquidity_presentation", "subsequent_minimum_usable_liquidity", liquidity["subsequent_minimum_usable_liquidity"], MONEY, "Lowest post-closing non-maturity monthly usable-liquidity observation in the selected base case.", "formula_calculated"),
        ("P7FA-042", "liquidity_presentation", "subsequent_minimum_liquidity_date", liquidity["subsequent_minimum_liquidity_date"], "date", "Date of the selected base case post-closing minimum.", "formula_calculated"),
        ("P7FA-043", "liquidity_presentation", "all_in_minimum_usable_liquidity", liquidity["all_in_minimum_usable_liquidity"], MONEY, "Lower of opening usable liquidity and the subsequent post-closing minimum.", "formula_calculated"),
        ("P7FA-044", "liquidity_presentation", "all_in_minimum_liquidity_date", liquidity["all_in_minimum_liquidity_date"], "date_or_label", "OPENING_POSITION when opening usable liquidity is the all-in minimum; otherwise the post-closing date.", "formula_calculated"),
    ]
    return [{
        "assumption_id": row[0], "category": row[1], "assumption_name": row[2],
        "value": row[3], "units": row[4], "definition_or_formula": row[5],
        "input_status": row[6], "source_ids": "SRC-001;SRC-002;SRC-003",
        "upstream_ids": "STR-008;P7CP-001:P7CP-017;CP-001:CP-024",
        "owner_review_status": REVIEW,
        "phase8_required_action": "Implement as a formula-linked input only when Phase 8 is separately authorized; retain pending-information and condition-precedent status where stated.",
        "limitations": OWNER_REVIEW_NOTE,
    } for row in values]


def covenant_matrix_rows(proposals: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{
        "matrix_id": f"P7CM-{index:03d}", "framework": row["framework"],
        "test_name": row["metric_or_term"], "metric_definition": row["definition"],
        "debt_definition": row["numerator"] if "leverage" in row["metric_or_term"] else "not_applicable",
        "earnings_definition": row["denominator"] if row["denominator"] != "not_applicable" else "not_applicable",
        "cash_treatment": row["cash_netting"],
        "drawn_revolver_treatment": row["drawn_revolver_treatment"],
        "threshold": row["threshold"], "units": row["units"],
        "effective_period": f"{row['effective_start']} to {row['effective_end'] or 'open'}",
        "test_frequency": row["testing_frequency"],
        "warning_or_covenant": row["framework"],
        "cure_and_stepup_treatment": f"cures: {row['cures']}; stepups: {row['stepups']}",
        "draw_condition_consequence": row["draw_condition_effect"],
        "source_ids": row["source_ids"], "upstream_ids": row["proposal_id"],
        "evidence_status": row["evidence_status"],
        "owner_review_status": row["owner_review_status"],
        "limitations": row["limitations"],
    } for index, row in enumerate(proposals, start=1)]


def build_distribution_tests(
    selected_monthly: dict[str, list[dict[str, str]]],
    covenant_tests: list[dict[str, str]],
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for scenario_id in selected_monthly:
        monthly = selected_monthly[scenario_id]
        scenario_tests = sorted(
            [row for row in covenant_tests if row["scenario_id"] == scenario_id],
            key=lambda row: row["period_end"],
        )
        first_warning = next((row["period_end"] for row in scenario_tests if row["overall_warning_status"] in {"warning", "breached"}), "")
        direct_rows = [row for row in monthly if dec(row["repurchase_revolver_draw_caused"]) > TOLERANCE]
        broad_rows = [row for row in monthly if dec(row["repurchase_paid_while_revolver_outstanding"]) > TOLERANCE]
        dividends = [row for row in monthly if dec(row["dividend_paid"]) > TOLERANCE]
        repurchases = [row for row in monthly if dec(row["repurchase_paid"]) > TOLERANCE]
        post_warning = [
            row for row in monthly
            if first_warning and row["month_end"] > first_warning
            and dec(row["dividend_paid"]) + dec(row["repurchase_paid"]) > TOLERANCE
        ]
        rules = [
            (
                "debt_funded_share_repurchase",
                "Prohibit any share repurchase that directly causes a revolver draw.",
                sum((dec(row["base_planned_repurchase"]) for row in monthly), Decimal("0")),
                sum((dec(row["repurchase_paid"]) for row in monthly), Decimal("0")),
                sum((dec(row["repurchase_revolver_draw_caused"]) for row in direct_rows), Decimal("0")),
                direct_rows, "FAIL_IN_PHASE6_CASH_PATH" if direct_rows else "PASS_IN_PHASE6_CASH_PATH",
            ),
            (
                "share_repurchase_while_revolver_outstanding",
                "Prohibit share repurchases while any revolver borrowing is outstanding.",
                sum((dec(row["base_planned_repurchase"]) for row in monthly), Decimal("0")),
                sum((dec(row["repurchase_paid"]) for row in monthly), Decimal("0")),
                sum((dec(row["repurchase_paid_while_revolver_outstanding"]) for row in broad_rows), Decimal("0")),
                broad_rows, "FAIL_IN_PHASE6_CASH_PATH" if broad_rows else "PASS_IN_PHASE6_CASH_PATH",
            ),
            (
                "warning_suspension",
                "Suspend share repurchases after any analyst warning; dividends require the separate pro forma basket.",
                sum((dec(row["base_planned_dividend"]) + dec(row["base_planned_repurchase"]) for row in monthly), Decimal("0")),
                sum((dec(row["dividend_paid"]) + dec(row["repurchase_paid"]) for row in monthly), Decimal("0")),
                sum((dec(row["dividend_paid"]) + dec(row["repurchase_paid"]) for row in post_warning), Decimal("0")),
                post_warning, "RESTRICTION_WOULD_APPLY" if post_warning else "NO_POST_WARNING_PAYMENT_IDENTIFIED",
            ),
        ]
        for name, rule, planned_amount, paid_amount, flagged_amount, flagged_rows, result in rules:
            output.append({
                "restriction_test_id": f"P7RP-{len(output)+1:03d}", "scenario_id": scenario_id,
                "test_name": name, "proposed_rule": rule,
                "planned_amount": fmt(planned_amount),
                "amount_paid_in_phase6_path": fmt(paid_amount),
                "amount_flagged_or_blocked": fmt(flagged_amount),
                "first_flag_date": flagged_rows[0]["month_end"] if flagged_rows else "",
                "test_result": result, "cash_flow_credit_taken_in_phase7": "0",
                "source_ids": "SRC-001;SRC-002;SRC-003", "upstream_ids": f"STR-008;{scenario_id}",
                "owner_review_status": REVIEW,
                "limitations": "Phase 7 preserves the Phase 6 cash paths and takes no liquidity, debt, interest, or maturity-gap benefit from proposed restrictions. Phase 8 must implement approved terms prospectively.",
            })
    return output


def phase8_rows(final: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{
        "input_id": f"P8I-{index:03d}", "section": row["category"],
        "input_name": row["assumption_name"], "value": row["value"],
        "units": row["units"], "formula_or_definition": row["definition_or_formula"],
        "input_status": row["input_status"], "source_ids": row["source_ids"],
        "upstream_ids": row["assumption_id"], "owner_review_status": row["owner_review_status"],
        "phase8_model_location": {
            "facilities": "Debt Schedule", "amortization": "Debt Schedule",
            "maturity": "Debt Schedule", "pricing": "Debt Schedule",
            "cash": "Liquidity", "covenants": "Covenants", "warnings": "Covenants",
            "prepayment": "Debt Schedule", "distributions": "Cash Flow/Covenants",
            "hold": "Sources & Uses", "security": "Terms", "drawability": "Liquidity/Covenants",
            "reporting": "Checks", "closing": "Sources & Uses/Checks", "selection": "Summary",
            "funding": "Sources & Uses", "sizing": "Sources & Uses/Covenants",
            "comparison": "Financing Comparison",
        }.get(row["category"], "Terms"),
        "limitations": row["limitations"],
    } for index, row in enumerate(final, start=1)]


def prior_analytical_artifact_changes() -> list[str]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        capture_output=True, check=True,
    ).stdout.strip()
    checkpoint = APPROVED_PHASE6_COMMIT
    if head == APPROVED_PHASE7_COMMIT or subprocess.run(
        ["git", "merge-base", "--is-ancestor", APPROVED_PHASE7_COMMIT, head],
        cwd=ROOT, text=True, capture_output=True,
    ).returncode == 0:
        checkpoint = APPROVED_PHASE7_COMMIT
    protected = [
        path for path in subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", checkpoint],
            cwd=ROOT, text=True, capture_output=True, check=True,
        ).stdout.splitlines()
        if path.startswith(("data/phase", "docs/phase-"))
    ]
    result = subprocess.run(
        ["git", "diff", "--name-only", checkpoint, "--", *protected],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    missing = [path for path in protected if not (ROOT / path).is_file()]
    return sorted(set(missing + [line for line in result.stdout.splitlines() if line]))


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
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        capture_output=True, check=True,
    ).stdout.strip()
    approved_head = head in {APPROVED_PHASE6_COMMIT, APPROVED_PHASE7_COMMIT} or subprocess.run(
        ["git", "merge-base", "--is-ancestor", APPROVED_PHASE7_COMMIT, head],
        cwd=ROOT, text=True, capture_output=True,
    ).returncode == 0
    if not approved_head:
        raise Phase7Error(f"HEAD is not the approved Phase 6/7 checkpoint or a descendant: {head}")
    allowed_exact = {
        ".gitattributes", "README.md", "scripts/phase4.py", "scripts/phase5.py", "scripts/phase6.py", "scripts/phase7.py",
        "scripts/phase8.py", "scripts/build-phase8.mjs", "scripts/recalculate-phase8.py",
        "scripts/validate-phase8-excel.ps1",
        "scripts/phase9.py", "scripts/build-phase9.mjs", "scripts/recalculate-phase9.py", "scripts/validate-phase9-excel.ps1",
        "scripts/phase10.py", "scripts/build-phase10.mjs", "scripts/render-phase10.py",
        "tests/test_phase6.py", "tests/test_phase7.py", "tests/test_phase8.py", "tests/test_phase9.py", "tests/test_phase10.py",
        "model/Quanex_Credit_Underwriting.xlsx",
    }
    unexpected = [
        path for path in changed_paths()
        if path not in allowed_exact
        and not path.startswith("data/phase7/")
        and not path.startswith("docs/phase-7/")
        and not path.startswith("data/phase8/")
        and not path.startswith("docs/phase-8/")
        and not path.startswith("data/phase9/")
        and not path.startswith("docs/phase-9/")
        and not path.startswith("data/phase10/")
        and not path.startswith("docs/phase-10/")
        and not path.startswith("reports/")
    ]
    if unexpected:
        raise Phase7Error("Unexpected changed paths: " + ", ".join(unexpected))
    prior = prior_analytical_artifact_changes()
    if prior:
        raise Phase7Error("Protected Phase 0-6 analytical artifacts changed: " + ", ".join(prior))


def validation_rows(
    candidates: list[dict[str, str]], proposals: list[dict[str, str]],
    owner: list[dict[str, str]], comparison: list[dict[str, str]],
    final: list[dict[str, str]], tests: list[dict[str, str]],
    headroom: list[dict[str, str]], timeline: list[dict[str, str]],
    sizing: list[dict[str, str]], distributions: list[dict[str, str]],
    phase8: list[dict[str, str]], common_horizon: list[dict[str, str]],
    ultimate_maturity: list[dict[str, str]], sources_uses: list[dict[str, str]],
    covenant_summary: list[dict[str, str]], leverage_comparison: list[dict[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add(category: str, name: str, passed: bool, observed: object, expected: str, tolerance: str = "exact", notes: str = "") -> None:
        rows.append({
            "validation_id": f"P7V-{len(rows)+1:03d}", "category": category,
            "test_name": name, "status": "PASS" if passed else "FAIL",
            "observed_value": str(observed), "expected_value_or_rule": expected,
            "tolerance": tolerance, "notes": notes,
        })

    ensure_unique(candidates, "candidate_id", "candidate")
    ensure_unique(proposals, "proposal_id", "covenant proposal")
    ensure_unique(owner, "decision_id", "owner decision")
    ensure_unique(comparison, "comparison_id", "structure comparison")
    ensure_unique(final, "assumption_id", "final assumption")
    ensure_unique(tests, "test_id", "covenant test")
    ensure_unique(headroom, "headroom_id", "headroom")
    ensure_unique(timeline, "timeline_id", "timeline")
    ensure_unique(sizing, "sizing_id", "sizing")
    ensure_unique(distributions, "restriction_test_id", "distribution test")
    ensure_unique(phase8, "input_id", "Phase 8 input")
    ensure_unique(common_horizon, "common_horizon_id", "common-horizon comparison")
    ensure_unique(ultimate_maturity, "maturity_comparison_id", "ultimate-maturity comparison")
    ensure_unique(sources_uses, "reconciliation_id", "sources-and-uses reconciliation")
    ensure_unique(covenant_summary, "summary_id", "covenant summary")
    ensure_unique(leverage_comparison, "comparison_id", "leverage covenant comparison")
    selected = next(row for row in candidates if row["candidate_id"] == "STR-008")
    reference = next(row for row in candidates if row["candidate_id"] == "STR-003")
    reference_base = next(row for row in comparison if row["candidate_id"] == "STR-003" and row["scenario_id"] == "BASE")
    committed_base = next(row for row in read_csv(PHASE6_RESULTS) if row["structure"] == "proposed" and row["scenario_id"] == "BASE")
    phase5_common_liquidity = next(
        row for row in read_csv(PHASE5_COMMON_HORIZON)
        if row["metric_name"] == "minimum_usable_liquidity"
    )
    formula_total_debt = fy2025_lender_ebitda() * Decimal("3.25")
    formula_term = formula_total_debt - phase5_value("P5A-032") - phase5_value("P5A-026")
    add("starting_state", "approved Phase 6 checkpoint recorded", checkpoint_rows()[0]["local_head"] == APPROVED_PHASE6_COMMIT, checkpoint_rows()[0]["local_head"], APPROVED_PHASE6_COMMIT)
    add("lineage", "protected Phase 0-6 analytical artifacts unchanged", not prior_analytical_artifact_changes(), ";".join(prior_analytical_artifact_changes()), "none")
    add("scope", "structure alternatives include existing and amendment", {"existing_retention", "amend_extend"}.issubset({row["alternative_type"] for row in candidates}), len(candidates), "both live alternatives")
    add("scope", "required amortization sensitivities", {"5", "7.5", "10", "15"}.issubset({row["annual_amortization_percent"] for row in candidates}), sorted({row["annual_amortization_percent"] for row in candidates if row["annual_amortization_percent"]}), "5/7.5/10/15")
    add("sizing", "reference opening term", dec(reference["opening_term_principal"]) == Decimal("650"), reference["opening_term_principal"], "650")
    add("sizing", "reference opening revolver", dec(reference["opening_revolver"]) == Decimal("29.89771875"), reference["opening_revolver"], "29.89771875")
    add("sizing", "reference opening bank debt", dec(reference["opening_bank_debt"]) == Decimal("679.89771875"), reference["opening_bank_debt"], "679.89771875")
    add("sizing", "total-funded-debt capacity labeled separately", any(row["assumption_name"] == "analytical_total_funded_debt_capacity" and abs(dec(row["value"]) - formula_total_debt) <= TOLERANCE for row in final), fmt(formula_total_debt), "3.25x EBITDA", fmt(TOLERANCE))
    add("sizing", "exact analytical term allocation retained separately", any(row["candidate_id"] == "STR-009" and abs(dec(row["opening_term_principal"]) - formula_term) <= TOLERANCE for row in candidates), fmt(formula_term), "analytical boundary", fmt(TOLERANCE))
    add("sizing", "selected practical term amount", dec(selected["opening_term_principal"]) == Decimal("635"), selected["opening_term_principal"], "635")
    add("sizing", "smaller term has real non-debt source", abs((Decimal("650") - dec(selected["opening_term_principal"])) - dec(selected["required_non_debt_contribution"])) <= TOLERANCE, selected["required_non_debt_contribution"], "650 - selected term", fmt(TOLERANCE))
    add("sizing", "operating cash floor not used as contribution", "may not consume" in selected["limitations"], "documented", "separate source")
    add("reconciliation", "Phase 6 reference maturity gap retained", abs(dec(reference_base["unsupported_maturity_gap"]) - dec(committed_base["unsupported_maturity_gap"])) <= TOLERANCE, reference_base["unsupported_maturity_gap"], committed_base["unsupported_maturity_gap"], fmt(TOLERANCE))
    add("reconciliation", "Phase 6 reference all-in minimum liquidity retained", abs(dec(reference_base["all_in_minimum_usable_liquidity"]) - dec(committed_base["minimum_usable_liquidity"])) <= TOLERANCE, reference_base["all_in_minimum_usable_liquidity"], committed_base["minimum_usable_liquidity"], fmt(TOLERANCE))
    add("reconciliation", "Phase 5 reference all-in minimum liquidity retained", abs(dec(reference_base["all_in_minimum_usable_liquidity"]) - dec(phase5_common_liquidity["proposed_value"])) <= TOLERANCE, reference_base["all_in_minimum_usable_liquidity"], phase5_common_liquidity["proposed_value"], fmt(TOLERANCE))
    add("definitions", "three covenant frameworks remain distinct", {"existing_contractual", "proposed_contractual", "analyst_warning"}.issubset({row["framework"] for row in proposals}), sorted({row["framework"] for row in proposals}), "existing/proposed/warning")
    add("definitions", "proposed leverage uses zero cash", all(row["cash_netting"] == "none" for row in proposals if row["proposal_id"] in {"P7CP-002", "P7CP-003", "P7CP-004"}), "checked", "none")
    add("definitions", "drawn revolver included", all("Included" in row["drawn_revolver_treatment"] or "included" in row["drawn_revolver_treatment"] for row in proposals if row["proposal_id"] in {"P7CP-002", "P7CP-003", "P7CP-004"}), "checked", "included")
    add("definitions", "book cash remains diagnostic", all(row["cash_eligibility_status"] == "pending_information_diagnostic_only" for row in comparison if row["scenario_id"] != "NOT_MODELED"), "checked", "diagnostic only")
    add("warnings", "leverage warnings at or inside covenants", all(dec(row["analyst_leverage_warning"]) <= dec(row["contractual_leverage_limit"]) for row in tests), "checked", "warning <= covenant")
    add("warnings", "one increment below warning", maximum_measure_status(Decimal("3.249999"), Decimal("3.25"), Decimal("3.50")) == "compliant", "compliant", "below warning")
    add("warnings", "exact warning boundary", maximum_measure_status(Decimal("3.25"), Decimal("3.25"), Decimal("3.50")) == "warning", "warning", "ratio >= warning")
    add("warnings", "one increment above warning", maximum_measure_status(Decimal("3.250001"), Decimal("3.25"), Decimal("3.50")) == "warning", "warning", "above warning and below covenant")
    add("covenants", "exact maximum covenant boundary", maximum_measure_status(Decimal("3.50"), Decimal("3.25"), Decimal("3.50")) == "warning", "warning", "equality is compliant but warning remains active")
    add("covenants", "one increment above maximum covenant", maximum_measure_status(Decimal("3.500001"), Decimal("3.25"), Decimal("3.50")) == "breached", "breached", "ratio > covenant")
    add("warnings", "coverage warning inside covenant", all(dec(row["analyst_coverage_warning"]) > dec(row["contractual_interest_coverage_minimum"]) for row in tests), "checked", "warning > covenant")
    add("warnings", "liquidity warning inside covenant", all(dec(row["analyst_liquidity_warning"]) > dec(row["contractual_minimum_liquidity"]) for row in tests), "checked", "warning > covenant")
    add("headroom", "leverage headroom formula", all(row["ratio_or_amount_headroom"] in {N_D_VALUE, N_M} or abs(dec(row["ratio_or_amount_headroom"]) - (dec(row["threshold"]) - dec(row["actual"]))) <= TOLERANCE for row in headroom if row["metric"] in {"gross_funded_leverage", "analyst_leverage_warning"}), "checked", "L-D/E", fmt(TOLERANCE))
    add("headroom", "no negative or zero EBITDA ratios", all(row["gross_funded_leverage"] in {N_D_VALUE, N_M} or (row["ttm_lender_base_ebitda"] and dec(row["ttm_lender_base_ebitda"]) > 0) for row in tests), "checked", "N/D missing; N/M nonpositive denominator")
    add("coverage", "missing coverage is N/D", all(row["interest_coverage"] == N_D_VALUE and row["coverage_status"] == N_D for row in tests if row["quarter"] == "closing_test"), "checked", "N/D")
    add("coverage", "zero coverage denominator is N/M", coverage_ratio(Decimal("1"), Decimal("0")) == N_M, coverage_ratio(Decimal("1"), Decimal("0")), N_M)
    add("coverage", "negative coverage denominator is N/M", coverage_ratio(Decimal("1"), Decimal("-1")) == N_M, coverage_ratio(Decimal("1"), Decimal("-1")), N_M)
    add("cash", "cash floor distinct from liquidity covenant", any(row["proposal_id"] == "P7CP-012" and row["threshold"] == "25" for row in proposals) and any(row["proposal_id"] == "P7CP-006" and row["threshold"] == "50" for row in proposals), "25 and 50", "distinct")
    add("sweep", "ECF sweep rate", next(row for row in proposals if row["proposal_id"] == "P7CP-013")["threshold"] == "50", next(row for row in proposals if row["proposal_id"] == "P7CP-013")["threshold"], "50")
    add("sweep", "ECF excludes distributions as deductions", "No deduction for dividends" in next(row for row in proposals if row["proposal_id"] == "P7CP-013")["exclusions"], "documented", "no distribution deduction")
    add("distributions", "no Phase 7 cash-flow credit for restrictions", all(row["cash_flow_credit_taken_in_phase7"] == "0" for row in distributions), "checked", "0")
    add("distributions", "both repurchase interpretations tested", {"debt_funded_share_repurchase", "share_repurchase_while_revolver_outstanding"}.issubset({row["test_name"] for row in distributions}), "checked", "narrow and broad")
    add("drawability", "three drawability paths remain separate", {"CONTINUED_DRAW_OR_WAIVER_SENSITIVITY", "PHASE7_COVENANT_LINKED_NO_WAIVER", "PHASE6_ANALYTICAL_SHUTOFF_SENSITIVITY"}.issubset({row["path_convention"] for row in timeline}), sorted({row["path_convention"] for row in timeline}), "continued/Phase7/Phase6")
    add("drawability", "warning alone never shuts off Phase 7 draws", all(not row["first_drawability_shutoff_date"] or row["first_proposed_covenant_breach_date"] < row["first_drawability_shutoff_date"] for row in timeline if row["path_convention"] == "PHASE7_COVENANT_LINKED_NO_WAIVER"), "checked", "breach before shutoff")
    phase7_timelines = [row for row in timeline if row["path_convention"] == "PHASE7_COVENANT_LINKED_NO_WAIVER"]
    phase7_breach_tests = {
        row["scenario_id"]: next(
            test for test in tests
            if test["scenario_id"] == row["scenario_id"]
            and test["period_end"] == row["first_proposed_covenant_breach_date"]
        ) for row in phase7_timelines
    }
    add("drawability", "no circular liquidity trigger", all(
        phase7_breach_tests[row["scenario_id"]]["leverage_status"] == "breached"
        and phase7_breach_tests[row["scenario_id"]]["liquidity_status"] != "breached"
        for row in phase7_timelines
    ), "checked", "triggering breach independently exists before shutoff")
    add("comparison", "common horizon fixed", all(row["period_end"] == COMMON_HORIZON_END.isoformat() for row in common_horizon), "checked", COMMON_HORIZON_END.isoformat())
    liquidity_rows = [
        row for collection in (comparison, common_horizon, sizing, covenant_summary)
        for row in collection if row.get("opening_usable_liquidity")
    ]
    add("liquidity", "all-in liquidity is lower of opening and subsequent", all(
        dec(row["all_in_minimum_usable_liquidity"]) == min(
            dec(row["opening_usable_liquidity"]),
            dec(row["subsequent_minimum_usable_liquidity"]),
        ) for row in liquidity_rows
    ), len(liquidity_rows), "all quantitative presentation rows")
    add("liquidity", "opening-position label used when opening is minimum", all(
        row["all_in_minimum_liquidity_date"] == "OPENING_POSITION"
        for row in liquidity_rows
        if dec(row["opening_usable_liquidity"]) <= dec(row["subsequent_minimum_usable_liquidity"])
    ), "checked", "OPENING_POSITION")
    add("liquidity", "subsequent date retained when later liquidity is lower", all(
        row["all_in_minimum_liquidity_date"] == row["subsequent_minimum_liquidity_date"]
        for row in liquidity_rows
        if dec(row["opening_usable_liquidity"]) > dec(row["subsequent_minimum_usable_liquidity"])
    ), "checked", "subsequent minimum date")
    add("liquidity", "no ambiguous minimum-liquidity output field", all(
        "minimum_usable_liquidity" not in row
        for collection in (comparison, common_horizon, sizing, covenant_summary)
        for row in collection
    ), "checked", "opening/subsequent/all-in fields only")
    add("comparison", "ultimate maturities separately labeled", all(row["comparison_status"] in {"different_contractual_horizon_not_directly_comparable", N_D} for row in ultimate_maturity), "checked", "different horizon")
    add("reconciliation", "sources equal uses for proposed candidates", all(abs(dec(row["sources_less_uses"])) <= TOLERANCE and row["status"] == "compliant" for row in sources_uses if row["initial_term_funding"]), "checked", "zero")
    add("sizing", "practical rounded alternatives present", {"STR-008", "STR-009", "STR-010", "STR-011"}.issubset({row["candidate_id"] for row in candidates}), "checked", "selected/exact/$640 cases")
    exact_candidate = next(row for row in candidates if row["candidate_id"] == "STR-009")
    reallocated_candidate = next(row for row in candidates if row["candidate_id"] == "STR-011")
    add("sizing", "term and revolver allocation preserves total bank debt", abs(
        dec(exact_candidate["opening_bank_debt"]) - dec(reallocated_candidate["opening_bank_debt"])
    ) <= TOLERANCE, reallocated_candidate["opening_bank_debt"], exact_candidate["opening_bank_debt"], fmt(TOLERANCE))
    add("covenants", "complete covenant summary paths", len(covenant_summary) == len({row["scenario_id"] for row in tests}), len(covenant_summary), "one per selected path")
    add("covenants", "3.25x versus 3.50x comparison", {row["covenant_case"] for row in leverage_comparison} == {"proposed_3.50x_initial", "alternative_3.25x_initial"}, sorted({row["covenant_case"] for row in leverage_comparison}), "both")
    add("maturity", "no refinancing proceeds", all(dec(row["unsupported_maturity_gap"]) >= 0 for row in comparison if row["unsupported_maturity_gap"]), "checked", "no negative gap")
    add("review", "all Phase 7 judgments owner reviewed", all(row["owner_review_status"] == REVIEW for row in proposals + owner + final + sizing + distributions), "checked", REVIEW)
    add("review", "all 21 human decisions owner reviewed", len(owner) == 21 and all(row["human_review_status"] == REVIEW for row in owner), len(owner), "21 owner_reviewed decisions")
    add("review", "owner review note preserves approval limitations", all(row["review_note"] == OWNER_REVIEW_NOTE for row in owner), "checked", "uniform limited-scope approval note")
    add("source", "source IDs valid", all(source in source_manifest() for collection in (candidates, proposals, comparison, final, sizing) for row in collection for source in row["source_ids"].split(";") if source), "checked", "all IDs in approved manifest")
    add("cutoff", "no new source IDs", {source for collection in (candidates, proposals, comparison, final, sizing) for row in collection for source in row["source_ids"].split(";") if source}.issubset({"SRC-001", "SRC-002", "SRC-003"}), "SRC-001;SRC-002;SRC-003", "approved pre-cutoff sources only")
    add("handoff", "Phase 8 inputs formula-ready", len(phase8) == len(final), len(phase8), str(len(final)))
    approved_phase7_paths = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", APPROVED_PHASE7_COMMIT],
        cwd=ROOT, text=True, capture_output=True, check=True,
    ).stdout.splitlines()
    add("scope", "Phase 8 not implemented", not any(
        path == "scripts/phase8.py" or path.startswith("data/phase8/")
        for path in approved_phase7_paths
    ), "absent", "no Phase 8 implementation")
    add("scope", "no workbook created", not any(
        path.lower().endswith(".xlsx") for path in approved_phase7_paths
    ), "absent", "no xlsx")
    return rows


def source_ledger_rows(artifacts: list[tuple[str, list[dict[str, str]], str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for artifact, records, id_field in artifacts:
        for record in records:
            rows.append({
                "ledger_id": f"P7L-{len(rows)+1:05d}", "artifact_path": artifact,
                "record_id": record[id_field],
                "metric_or_term": record.get(
                    "metric_or_term",
                    record.get(
                        "test_name",
                        record.get(
                            "analysis",
                            record.get(
                                "assumption_name",
                                record.get("candidate_name", record.get("topic", "record")),
                            ),
                        ),
                    ),
                ),
                "source_ids": record.get("source_ids", "SRC-001;SRC-002;SRC-003"),
                "upstream_ids": record.get("upstream_ids", record[id_field]),
                "classification": record.get("classification", record.get("framework", "phase7_record")),
                "review_status": record.get("owner_review_status", record.get("review_status", REVIEW)),
                "cutoff_status": "within_cutoff",
                "notes": "No new evidence source. Trace source IDs through the approved Phase 1-6 ledgers. Owner review is workflow and underwriting-judgment metadata, not an observed borrower fact or post-cutoff analytical evidence; stated conditions remain open.",
            })
    return rows


def money(value: str) -> str:
    if not value or value in {N_D, N_D_VALUE}:
        return "N/D"
    amount = dec(value)
    return f"-${abs(amount):,.3f}m" if amount < 0 else f"${amount:,.3f}m"


def turns(value: str) -> str:
    if value in ("", N_D, N_D_VALUE):
        return "N/D"
    if value == N_M:
        return N_M
    return f"{dec(value):.2f}x"


def write_docs(
    candidates: list[dict[str, str]], proposals: list[dict[str, str]],
    comparison: list[dict[str, str]], final: list[dict[str, str]],
    tests: list[dict[str, str]], timeline: list[dict[str, str]],
    sizing: list[dict[str, str]], distributions: list[dict[str, str]],
    common_horizon: list[dict[str, str]],
    ultimate_maturity: list[dict[str, str]],
    sources_uses: list[dict[str, str]],
    covenant_summary: list[dict[str, str]],
    leverage_comparison: list[dict[str, str]],
) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    selected = next(row for row in candidates if row["candidate_id"] == "STR-008")
    reference = next(row for row in candidates if row["candidate_id"] == "STR-003")
    exact = next(row for row in candidates if row["candidate_id"] == "STR-009")
    selected_tests = [row for row in tests if row["scenario_id"] == "BASE"]
    closing_test = next(row for row in selected_tests if row["period_end"] == "2026-01-31")
    selected_sources = next(row for row in sources_uses if row["candidate_id"] == "STR-008")
    selected_common = next(row for row in common_horizon if row["candidate_id"] == "STR-008")
    selected_maturity = next(row for row in ultimate_maturity if row["candidate_id"] == "STR-008")
    reference_maturity = next(row for row in ultimate_maturity if row["candidate_id"] == "STR-003")
    methodology = f"""# Phase 7 methodology

## Purpose and boundary

Phase 7 converts the approved Phase 4-6 financing, base-case and downside results into covenant and sizing proposals. It does not change operating assumptions, treat a warning as a contractual breach, assume a waiver or maturity refinancing, build the final workbook, perform recovery analysis, assign a final risk grade, draft the committee memo, or start Phase 8. Amounts are USD millions and calculations retain `Decimal` precision.

No new evidence source was added. Phase 7 uses SRC-001, SRC-002 and SRC-003 through the approved prior-phase ledgers. The information cutoff remains {CUTOFF.isoformat()}.

The project owner reviewed all 21 Phase 7 structuring decisions. That workflow status approves the Phase 7 public-information underwriting structure only. It is not a lender commitment, final legal drafting, official covenant compliance, or evidence that unresolved funding sources or private information exist. Every stated condition and diligence gap remains open.

## Candidate method

Quantitative candidates reuse the Phase 6 monthly operating, cash, interest and payment-ordering mechanics. The $650m/10% reference row reconciles to the committed Phase 6 outputs. The amendment or extension alternative remains qualitative because price, tenor, fees and covenant terms are unavailable.

The 3.25x sizing test limits total funded debt, not the term loan. The exact total-funded-debt capacity is {money(next(row['maximum_total_funded_debt'] for row in sizing if row['sizing_id'] == 'P7SZ-004'))}; after retained other funded debt and the reference revolver allocation, the corresponding analytical term allocation is {money(exact['opening_term_principal'])}. That exact amount is a calculation boundary, not a realistic negotiated commitment.

The selected practical candidate uses a {money(selected['term_commitment'])} term commitment funded at closing, {money(selected['opening_revolver'])} of opening revolver debt, {money(selected['retained_other_funded_debt'])} of retained other funded debt, and a conditional {money(selected['required_non_debt_contribution'])} non-debt source. The non-debt source may not consume the separate $25m operating cash floor. The funded term equals the commitment; no delayed-draw or continuing undrawn term availability is assumed.

## Covenant calculations

Proposed gross funded leverage uses term principal, drawn revolver and the $62.619m retained funded-debt proxy, with zero cash netting. Capped-cash leverage is reported only as a diagnostic. Ratio headroom is `L - D/E`; debt headroom is `L*E - D`; break-even EBITDA is `D/L`; coverage earnings cushion is `E - C*I`. A missing EBITDA input produces `N/D`; a nonpositive EBITDA denominator produces `N/M`.

For a maximum measure, equality with the covenant remains compliant and only a value above the maximum is breached. Equality with the analyst-warning threshold activates a warning. Missing required information is `N/D`; `N/M` is reserved for a nonpositive denominator. Proposed contractual tests, analyst warnings and the existing contractual reconstruction are separate. Proposed covenant results are not official compliance calculations. Closing cash-interest coverage is `N/D` because a complete LTM denominator is unavailable.

## Drawability paths

The Phase 6 analytical shutoff sensitivity, the Phase 7 covenant-linked no-waiver path and the continued-draw or waiver sensitivity are separately labeled. A warning never terminates drawings. Under the selected Phase 7 convention, covenant-linked shutoff begins in the month after the first tested breach. A separate liquidity or capacity failure can independently prevent a draw and is not caused by the covenant shutoff assumption.

## Comparison horizons

The common-horizon output ends on {COMMON_HORIZON_END.isoformat()} for every quantitative structure. The ultimate-maturity output separately follows each structure to its own maturity and explicitly warns that different horizons are not directly comparable. No refinancing proceeds are assumed.

Liquidity presentation distinguishes opening usable liquidity, the lowest subsequent post-closing non-maturity monthly observation, and the all-in minimum. The all-in minimum is calculated as the lower of the first two values and is labeled `OPENING_POSITION` when opening is the lower value. This prevents a post-closing minimum from being presented as though it included the opening position.

## Distribution and ECF treatment

Phase 7 tests proposed distribution restrictions against Phase 6 cash paths but takes zero cash-flow credit for them. The 50% annual ECF sweep follows revolver repayment and excludes dividends and repurchases from permitted deductions. Prior modeled sweeps remain sensitivities until legal definitions are approved.
"""
    (DOCS / "METHODOLOGY.md").write_text(methodology, encoding="utf-8")

    covenant_lines = [
        "# Covenant design", "", "**Status:** Owner-reviewed Phase 7 public-information underwriting structure, subject to all stated conditions and diligence gaps. It is not a lender commitment, final legal drafting, or an official compliance calculation.", "",
        "## Framework separation", "",
        "| Framework | Test | Threshold | Period | Key limitation |", "|---|---|---:|---|---|",
    ]
    for row in proposals:
        if row["proposal_id"] in {"P7CP-001", "P7CP-002", "P7CP-003", "P7CP-004", "P7CP-005", "P7CP-006", "P7CP-007", "P7CP-008", "P7CP-009", "P7CP-010", "P7CP-011", "P7CP-012"}:
            covenant_lines.append(f"| {row['framework']} | {row['metric_or_term']} | {row['threshold']} {row['units']} | {row['effective_start']} to {row['effective_end'] or 'open'} | {row['limitations']} |")
    covenant_lines.extend([
        "", "## Proposed definitions and limitations", "",
        "The proposed leverage covenant is gross total funded leverage with zero cash netting. The existing public covenant is a net leverage test with agreement-defined terms. The 3.50x proposed gross threshold therefore does not silently replace or reinterpret the existing 3.25x net threshold.", "",
        "Drawn revolver principal is included in debt. The $62.619m retained finance-lease and other-debt proxy is included economically pending final legal classification. Operating lease liabilities and trade payables are excluded unless final drafting states otherwise. Lender EBITDA starts with the Phase 2 owner-reviewed base and requires a documented definition, adjustment schedule, caps, sunsets and anti-duplication controls.", "",
        "No cash is netted in the proposed covenant. Book cash and a capped $25m cash sensitivity remain diagnostics because entity location, restrictions, tax, liens and operating requirements are unresolved.", "",
        "## Cures, step-ups and drawability", "",
        "No equity cure, acquisition step-up, waiver or refinancing is assumed. A warning alone never blocks drawings. In the covenant-linked no-waiver path, a tested breach blocks new drawings from the following month. The continued-draw path requires lender consent or continuing legal availability. The inherited Phase 6 analytical shutoff remains separately labeled and is not a Phase 7 legal default.", "",
        "## Monitoring and intervention", "",
        "The analyst warning levels are 0.25x inside the leverage covenants, 3.50x coverage versus a 3.00x covenant, and $75m liquidity versus a $50m covenant. Warning boundaries are inclusive. A warning suspends share repurchases, starts monthly reporting and requires a 10-business-day action plan. A proposed breach suspends all restricted payments and invokes the no-new-draw convention unless lenders approve another outcome.", "",
        "## Selected-structure covenant summary", "",
        "| Path | Closing warning | Closing covenant | Max leverage | Min coverage | Opening liquidity | Subsequent minimum (date) | All-in minimum (date) | First warning | First breach | First draw shutoff | Payment failure | Maturity gap |",
        "|---|---|---|---:|---:|---:|---:|---:|---|---|---|---|---:|",
    ])
    for row in covenant_summary:
        covenant_lines.append(
            f"| {row['scenario_id']} | {row['closing_warning_status']} | {row['closing_covenant_status']} | "
            f"{row['maximum_gross_funded_leverage']}x | {row['minimum_cash_interest_coverage']}x | "
            f"{money(row['opening_usable_liquidity'])} | {money(row['subsequent_minimum_usable_liquidity'])} ({row['subsequent_minimum_liquidity_date']}) | "
            f"{money(row['all_in_minimum_usable_liquidity'])} ({row['all_in_minimum_liquidity_date']}) | {row['first_warning_date'] or 'none'} | "
            f"{row['first_breach_date'] or 'none'} | {row['first_draw_shutoff_date'] or 'none'} | "
            f"{row['first_mandatory_payment_failure_date'] or 'none'} | {money(row['ultimate_maturity_gap'])} |"
        )
    covenant_lines.extend([
        "", "## Initial leverage covenant comparison", "",
        "The transaction is sized below 3.25x while the proposed maintenance covenant begins at 3.50x. The 0.25x difference equals "
        + money(fmt(fy2025_lender_ebitda() * Decimal('0.25')))
        + " of debt capacity or " + money(fmt((dec(selected['opening_gross_funded_debt']) / Decimal('3.25')) - (dec(selected['opening_gross_funded_debt']) / Decimal('3.50'))))
        + " of EBITDA cushion at selected opening debt. It is maintenance cushion, not additional closing funding capacity.", "",
        "| Scenario | Covenant case | Closing | First warning | First breach | Liquidity at breach | Draw shutoff | Payment failure | Days breach-to-failure |",
        "|---|---|---|---|---|---:|---|---|---:|",
    ])
    for row in leverage_comparison:
        covenant_lines.append(
            f"| {row['scenario_family']} | {row['covenant_case']} | {row['closing_status']} | "
            f"{row['first_warning_date'] or 'none'} | {row['first_breach_date'] or 'none'} | "
            f"{money(row['liquidity_at_first_breach']) if row['liquidity_at_first_breach'] else 'N/D'} | "
            f"{row['first_draw_shutoff_date'] or 'none'} | {row['first_mandatory_payment_failure_date'] or 'none'} | "
            f"{row['days_breach_to_payment_failure'] or 'N/D'} |"
        )
    (DOCS / "COVENANT_DESIGN.md").write_text("\n".join(covenant_lines) + "\n", encoding="utf-8")

    sizing_lines = [
        "# Sizing rationale", "", "**Recommendation:** CONDITIONAL GO for committing the owner-reviewed Phase 7 provisional structure and, after separate authorization, proceeding to Phase 8. All closing and diligence conditions remain open.", "",
        "The original $650m term funding is not automatically acceptable. Including the $29.898m opening revolver and $62.619m retained funded-debt proxy, opening total funded debt is $742.517m. The 3.25x zero-cash analytical capacity is " + money(next(row["maximum_total_funded_debt"] for row in sizing if row["sizing_id"] == "P7SZ-004")) + ".", "",
        "The owner-reviewed Phase 7 provisional structure is a $635m term commitment funded at closing, a $300m revolver with $29.898m drawn at closing, and a conditional $15m non-debt contribution. Opening total funded debt is " + money(selected["opening_gross_funded_debt"]) + " and gross leverage is " + turns(fmt(dec(selected["opening_gross_funded_debt"]) / fy2025_lender_ebitda())) + ", below the inclusive 3.25x warning. The term amount must refresh from final payoff, fees, hedge and LC evidence.", "",
        "## Practical sizing alternatives", "",
        "| Analysis | Term funding | Contribution | Total funded debt | Leverage | Headroom / (shortfall) | Opening liquidity | Subsequent minimum (date) | All-in minimum (date) | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in sizing[3:9]:
        sizing_lines.append(
            f"| {row['analysis']} | {money(row['initial_term_funding'])} | {money(row['required_non_debt_contribution'])} | "
            f"{money(row['resulting_total_funded_debt'])} | {turns(row['resulting_leverage'])} | "
            f"{money(row['headroom_or_shortfall'])} | {money(row['opening_usable_liquidity'])} | "
            f"{money(row['subsequent_minimum_usable_liquidity'])} ({row['subsequent_minimum_liquidity_date']}) | "
            f"{money(row['all_in_minimum_usable_liquidity'])} ({row['all_in_minimum_liquidity_date']}) | {row['status']} |"
        )
    sizing_lines.extend([
        "", "The $640m/$10m option exceeds the 3.25x capacity by about $0.149m and remains an unselected sizing exception. The $640m reallocation alternative reduces the revolver by the same $0.149m and requires the exact non-debt source; this changes term-versus-revolver allocation without changing total funded debt. The selected $635m option adds a modest practical cushion and does not imply unused term availability.", "",
        "## Sources and uses", "",
        "| Candidate | Term | Revolver | Non-debt source | Total sources | Uses | Control | Warning | Covenant |",
        "|---|---:|---:|---:|---:|---:|---:|---|---|",
    ])
    for row in sources_uses:
        if row["initial_term_funding"]:
            sizing_lines.append(
                f"| {row['candidate_name']} | {money(row['initial_term_funding'])} | {money(row['opening_revolver'])} | "
                f"{money(row['required_non_debt_contribution'])} | {money(row['total_sources'])} | "
                f"{money(row['reference_closing_uses'])} | {money(row['sources_less_uses'])} | {row['warning_status']} | {row['covenant_status']} |"
            )
    sizing_lines.extend([
        "", "## Common horizon through July 31, 2029", "",
        "| Candidate | Interest | Scheduled principal | Sweep | Ending bank debt | Ending funded debt | Peak revolver | Opening liquidity | Subsequent minimum (date) | All-in minimum (date) | Unpaid obligations | Warning | Covenant |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ])
    for row in common_horizon:
        if row["comparison_status"] == "common_horizon_comparable":
            sizing_lines.append(
                f"| {row['candidate_name']} | {money(row['cumulative_cash_interest'])} | {money(row['cumulative_scheduled_principal'])} | "
                f"{money(row['cumulative_ecf_sweep'])} | {money(row['ending_total_bank_debt'])} | {money(row['ending_total_funded_debt'])} | "
                f"{money(row['peak_revolver_usage'])} | {money(row['opening_usable_liquidity'])} | "
                f"{money(row['subsequent_minimum_usable_liquidity'])} ({row['subsequent_minimum_liquidity_date']}) | "
                f"{money(row['all_in_minimum_usable_liquidity'])} ({row['all_in_minimum_liquidity_date']}) | {money(row['unpaid_mandatory_obligations'])} | "
                f"{row['warning_status']} | {row['covenant_status']} |"
            )
    sizing_lines.extend([
        "", "## Ultimate maturity (different horizons)", "",
        "| Candidate | Maturity | Months | Interest | Scheduled principal | Sweep | Final funded debt | Maturity due | Cash applied | Unsupported gap |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in ultimate_maturity:
        if row["comparison_status"] != N_D:
            sizing_lines.append(
                f"| {row['candidate_name']} | {row['maturity_date']} | {row['horizon_months']} | {money(row['cumulative_cash_interest'])} | "
                f"{money(row['cumulative_scheduled_principal'])} | {money(row['cumulative_ecf_sweep'])} | "
                f"{money(row['final_total_funded_debt'])} | {money(row['maturity_payment_due'])} | "
                f"{money(row['available_cash_applied'])} | {money(row['unsupported_maturity_gap'])} |"
            )
    sizing_lines.extend([
        "", "Ultimate-maturity totals use different cash-generation periods and cannot be compared directly. Pricing, amortization, contributions, maturity length, payment failures and draw availability must each be identified before drawing a conclusion. Retaining the existing facilities remains a live quantitative alternative; a limited amendment or extension remains live but `N/D` without terms. No refinancing proceeds are assumed.",
    ])
    (DOCS / "SIZING_RATIONALE.md").write_text("\n".join(sizing_lines) + "\n", encoding="utf-8")

    term_lines = [
        "# Final proposed term sheet", "", "**Owner-reviewed Phase 7 provisional structure for further underwriting.**", "",
        "This is a hypothetical underwriting proposal, not a lender quote, commitment, borrower approval, executed amendment, official compliance calculation, or final credit approval.", "",
        "| Category | Term | Proposed value | Status / limitation |", "|---|---|---|---|",
    ]
    for row in final:
        term_lines.append(f"| {row['category']} | {row['assumption_name']} | {row['value']} {row['units']} | {row['input_status']} |")
    term_lines.extend([
        "", "## Closing conditions retained", "",
        "All 24 Phase 4 conditions remain required as applicable. Payoff letters, lien releases and perfection, guarantor/entity schedules, accessible-cash evidence, hedging, final funds flow, fees, LC replacement, projections, compliance certificates and control-remediation evidence are not treated as satisfied.", "",
        "## Maturity and downside limitation", "",
        "The selected $635m term is fully funded at closing and has no continuing unused term capacity. The conditional $15m non-debt source remains pending evidence and may not reduce the $25m operating cash floor.", "",
        "Every quantified structure retains an unsupported maturity gap when no future refinancing is assumed. Severe scenarios can exhaust revolver capacity and produce mandatory-payment failures. Lower ending debt caused by curtailed borrowing or unpaid obligations is not favorable performance.",
    ])
    (DOCS / "FINAL_PROPOSED_TERM_SHEET.md").write_text("\n".join(term_lines) + "\n", encoding="utf-8")

    handoff_lines = [
        "# Phase 8 handoff", "", "All 21 Phase 7 structuring decisions are owner reviewed for the public-information underwriting structure. Phase 8 may use the formula-ready input CSV only after Phase 8 is separately authorized. This review is not a lender commitment, final legal drafting, official compliance calculation, or evidence that unresolved information exists.", "",
        "## Required model implementation", "",
        "1. Build the selected $635m term commitment and funding, conditional $15m non-debt source, opening revolver and retained debt as separate inputs. Retain the exact $639.851m term allocation only as an analytical boundary.",
        "2. Preserve gross funded leverage, zero-cash net leverage and capped-cash diagnostic as separate measures. Do not use book cash in covenant calculations.",
        "3. Implement 7.5% annual amortization quarterly and the 50% ECF sweep after revolver repayment without deducting distributions or double-counting operating uses.",
        "4. Implement proposed covenant, warning and operational cash-floor tests separately. Show ratio, debt, EBITDA, coverage and liquidity headroom.",
        "5. Preserve the continued-draw/waiver, Phase 7 covenant-linked no-waiver, and inherited Phase 6 analytical-shutoff paths separately. A warning does not terminate drawings.",
        "6. Implement the owner-reviewed repurchase and dividend rules while preserving that Phase 7 took no cash-flow credit for them.",
        "7. Retain all unsupported maturity gaps and do not assume refinancing.", "",
        "## Information still required", "",
        "- Final payoff, fees, hedge termination, LC transition and sources-and-uses evidence.",
        "- Evidence that at least " + money(selected["required_non_debt_contribution"]) + " of non-debt funding is accessible without reducing the $25m operating cash floor.",
        "- Proposed legal definitions for funded debt, lender EBITDA, eligible cash, ECF, pro forma transactions, restricted payments, draw conditions, cures and events of default.",
        "- Amendment or extension pricing, tenor, fees and covenant proposal.",
        "- Final collateral, guarantor, perfection and foreign-cash analysis.", "",
        "- Complete LTM cash-interest data for closing coverage; preserve `N/D` until it exists and use `N/M` only for a nonpositive denominator.",
        "- Final lender and legal definition of the owner-reviewed 3.50x initial maintenance covenant; the 3.25x alternative remains a sensitivity, not the selected proposal.", "",
        "## Selected outputs to preserve", "",
        f"- Closing warning: {closing_test['overall_warning_status']}; closing covenant: {closing_test['overall_covenant_status']}; closing coverage: {closing_test['interest_coverage']}.",
        f"- Common-horizon selected ending funded debt: {money(selected_common['ending_total_funded_debt'])}; opening liquidity: {money(selected_common['opening_usable_liquidity'])}; subsequent minimum: {money(selected_common['subsequent_minimum_usable_liquidity'])} on {selected_common['subsequent_minimum_liquidity_date']}; all-in minimum: {money(selected_common['all_in_minimum_usable_liquidity'])} at {selected_common['all_in_minimum_liquidity_date']}.",
        f"- Selected ultimate-maturity gap: {money(selected_maturity['unsupported_maturity_gap'])}; reference facility gap: {money(reference_maturity['unsupported_maturity_gap'])} on its earlier maturity.",
        f"- Sources-and-uses control: {money(selected_sources['sources_less_uses'])}.", "",
        "## Scenario findings to preserve", "",
    ]
    for row in covenant_summary:
        handoff_lines.append(
            f"- {row['scenario_id']}: first warning {row['first_warning_date'] or 'none'}; first breach {row['first_breach_date'] or 'none'}; "
            f"first draw shutoff {row['first_draw_shutoff_date'] or 'none'}; opening liquidity {money(row['opening_usable_liquidity'])}; "
            f"subsequent minimum {money(row['subsequent_minimum_usable_liquidity'])} on {row['subsequent_minimum_liquidity_date']}; "
            f"all-in minimum {money(row['all_in_minimum_usable_liquidity'])} at {row['all_in_minimum_liquidity_date']}; "
            f"first mandatory failure {row['first_mandatory_payment_failure_date'] or 'none'}; maturity gap {money(row['ultimate_maturity_gap'])}."
        )
    (DOCS / "PHASE8_HANDOFF.md").write_text("\n".join(handoff_lines) + "\n", encoding="utf-8")


def build() -> dict[str, object]:
    validate_changed_paths()
    RAW.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    candidates_def = candidate_definitions()
    candidates = structure_candidate_rows(candidates_def)
    proposals = covenant_proposal_rows()
    owner = owner_review_rows(candidates_def)
    comparison, selected_monthly, all_monthly = build_structure_comparison(candidates_def)
    final = build_final_assumptions(candidates_def, all_monthly)
    matrix = covenant_matrix_rows(proposals)
    tests, headroom = build_covenant_tests(selected_monthly)
    timeline = build_timeline(tests, selected_monthly, comparison)
    sizing = build_sizing_rows(candidates_def, all_monthly)
    distributions = build_distribution_tests(selected_monthly, tests)
    common_horizon = build_common_horizon_comparison(candidates_def, all_monthly)
    ultimate_maturity = build_ultimate_maturity_comparison(candidates_def, all_monthly)
    sources_uses = build_sources_uses_reconciliation(candidates_def)
    covenant_summary = build_covenant_summary(tests, selected_monthly, comparison)
    leverage_comparison = build_leverage_covenant_comparison(candidates_def, selected_monthly)
    phase8 = phase8_rows(final)
    validations = validation_rows(
        candidates, proposals, owner, comparison, final, tests, headroom,
        timeline, sizing, distributions, phase8, common_horizon,
        ultimate_maturity, sources_uses, covenant_summary, leverage_comparison,
    )
    failures = [row for row in validations if row["status"] != "PASS"]
    if failures:
        raise Phase7Error("Pre-write validation failed: " + ", ".join(row["test_name"] for row in failures))
    write_csv(RAW / "STARTING_CHECKPOINT.csv", CHECKPOINT_FIELDS, checkpoint_rows())
    write_csv(RAW / "STRUCTURE_CANDIDATES.csv", STRUCTURE_FIELDS, candidates)
    write_csv(RAW / "COVENANT_PROPOSALS.csv", COVENANT_PROPOSAL_FIELDS, proposals)
    write_csv(RAW / "OWNER_REVIEW_DECISIONS.csv", OWNER_DECISION_FIELDS, owner)
    write_csv(PROCESSED / "STRUCTURE_COMPARISON.csv", COMPARISON_FIELDS, comparison)
    write_csv(PROCESSED / "FINAL_FINANCING_ASSUMPTIONS.csv", FINAL_ASSUMPTION_FIELDS, final)
    write_csv(PROCESSED / "COVENANT_MATRIX.csv", COVENANT_MATRIX_FIELDS, matrix)
    write_csv(PROCESSED / "COVENANT_TEST_RESULTS.csv", COVENANT_TEST_FIELDS, tests)
    write_csv(PROCESSED / "COVENANT_HEADROOM.csv", HEADROOM_FIELDS, headroom)
    write_csv(PROCESSED / "BREACH_INTERVENTION_TIMELINE.csv", TIMELINE_FIELDS, timeline)
    write_csv(PROCESSED / "SIZING_RESULTS.csv", SIZING_FIELDS, sizing)
    write_csv(PROCESSED / "DISTRIBUTION_RESTRICTION_TESTS.csv", DISTRIBUTION_FIELDS, distributions)
    write_csv(PROCESSED / "COMMON_HORIZON_COMPARISON.csv", COMMON_HORIZON_FIELDS, common_horizon)
    write_csv(PROCESSED / "ULTIMATE_MATURITY_COMPARISON.csv", ULTIMATE_MATURITY_FIELDS, ultimate_maturity)
    write_csv(PROCESSED / "SOURCES_AND_USES_RECONCILIATION.csv", SOURCES_USES_FIELDS, sources_uses)
    write_csv(PROCESSED / "COVENANT_SUMMARY.csv", COVENANT_SUMMARY_FIELDS, covenant_summary)
    write_csv(PROCESSED / "LEVERAGE_COVENANT_COMPARISON.csv", LEVERAGE_COVENANT_COMPARISON_FIELDS, leverage_comparison)
    write_csv(PROCESSED / "PHASE8_MODEL_INPUTS.csv", PHASE8_FIELDS, phase8)
    write_csv(PROCESSED / "VALIDATION_RESULTS.csv", VALIDATION_FIELDS, validations)
    write_docs(
        candidates, proposals, comparison, final, tests, timeline, sizing,
        distributions, common_horizon, ultimate_maturity, sources_uses,
        covenant_summary, leverage_comparison,
    )
    ledger = source_ledger_rows([
        ("data/phase7/raw/STRUCTURE_CANDIDATES.csv", candidates, "candidate_id"),
        ("data/phase7/raw/COVENANT_PROPOSALS.csv", proposals, "proposal_id"),
        ("data/phase7/raw/OWNER_REVIEW_DECISIONS.csv", owner, "decision_id"),
        ("data/phase7/processed/STRUCTURE_COMPARISON.csv", comparison, "comparison_id"),
        ("data/phase7/processed/FINAL_FINANCING_ASSUMPTIONS.csv", final, "assumption_id"),
        ("data/phase7/processed/COVENANT_MATRIX.csv", matrix, "matrix_id"),
        ("data/phase7/processed/COVENANT_TEST_RESULTS.csv", tests, "test_id"),
        ("data/phase7/processed/COVENANT_HEADROOM.csv", headroom, "headroom_id"),
        ("data/phase7/processed/BREACH_INTERVENTION_TIMELINE.csv", timeline, "timeline_id"),
        ("data/phase7/processed/SIZING_RESULTS.csv", sizing, "sizing_id"),
        ("data/phase7/processed/DISTRIBUTION_RESTRICTION_TESTS.csv", distributions, "restriction_test_id"),
        ("data/phase7/processed/COMMON_HORIZON_COMPARISON.csv", common_horizon, "common_horizon_id"),
        ("data/phase7/processed/ULTIMATE_MATURITY_COMPARISON.csv", ultimate_maturity, "maturity_comparison_id"),
        ("data/phase7/processed/SOURCES_AND_USES_RECONCILIATION.csv", sources_uses, "reconciliation_id"),
        ("data/phase7/processed/COVENANT_SUMMARY.csv", covenant_summary, "summary_id"),
        ("data/phase7/processed/LEVERAGE_COVENANT_COMPARISON.csv", leverage_comparison, "comparison_id"),
        ("data/phase7/processed/PHASE8_MODEL_INPUTS.csv", phase8, "input_id"),
        ("data/phase7/processed/VALIDATION_RESULTS.csv", validations, "validation_id"),
    ])
    write_csv(DOCS / "SOURCE_LEDGER.csv", LEDGER_FIELDS, ledger)
    return {
        "structure_candidates": len(candidates), "comparison_rows": len(comparison),
        "covenant_proposals": len(proposals), "owner_review_decisions": len(owner),
        "covenant_tests": len(tests), "headroom_rows": len(headroom),
        "timeline_rows": len(timeline), "sizing_rows": len(sizing),
        "distribution_tests": len(distributions), "common_horizon_rows": len(common_horizon),
        "ultimate_maturity_rows": len(ultimate_maturity), "sources_uses_rows": len(sources_uses),
        "covenant_summary_rows": len(covenant_summary),
        "leverage_covenant_comparison_rows": len(leverage_comparison), "phase8_inputs": len(phase8),
        "validation_rows": len(validations), "ledger_rows": len(ledger),
        "selected_term_funding": next(row["opening_term_principal"] for row in candidates if row["candidate_id"] == "STR-008"),
        "selected_non_debt_source": next(row["required_non_debt_contribution"] for row in candidates if row["candidate_id"] == "STR-008"),
    }


def generated_files() -> list[Path]:
    paths = list(RAW.glob("*.csv")) + list(PROCESSED.glob("*.csv")) + list(DOCS.glob("*"))
    return sorted(path for path in paths if path.is_file())


def fingerprints() -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in generated_files()
    }


def validate() -> dict[str, object]:
    expected = {
        RAW / "STARTING_CHECKPOINT.csv", RAW / "STRUCTURE_CANDIDATES.csv",
        RAW / "COVENANT_PROPOSALS.csv", RAW / "OWNER_REVIEW_DECISIONS.csv",
        PROCESSED / "STRUCTURE_COMPARISON.csv", PROCESSED / "FINAL_FINANCING_ASSUMPTIONS.csv",
        PROCESSED / "COVENANT_MATRIX.csv", PROCESSED / "COVENANT_TEST_RESULTS.csv",
        PROCESSED / "COVENANT_HEADROOM.csv", PROCESSED / "BREACH_INTERVENTION_TIMELINE.csv",
        PROCESSED / "SIZING_RESULTS.csv", PROCESSED / "DISTRIBUTION_RESTRICTION_TESTS.csv",
        PROCESSED / "COMMON_HORIZON_COMPARISON.csv",
        PROCESSED / "ULTIMATE_MATURITY_COMPARISON.csv",
        PROCESSED / "SOURCES_AND_USES_RECONCILIATION.csv",
        PROCESSED / "COVENANT_SUMMARY.csv",
        PROCESSED / "LEVERAGE_COVENANT_COMPARISON.csv",
        PROCESSED / "PHASE8_MODEL_INPUTS.csv", PROCESSED / "VALIDATION_RESULTS.csv",
        DOCS / "METHODOLOGY.md", DOCS / "COVENANT_DESIGN.md", DOCS / "SIZING_RATIONALE.md",
        DOCS / "FINAL_PROPOSED_TERM_SHEET.md", DOCS / "PHASE8_HANDOFF.md",
        DOCS / "SOURCE_LEDGER.csv",
    }
    missing = [str(path.relative_to(ROOT)) for path in sorted(expected) if not path.is_file()]
    if missing:
        raise Phase7Error("Missing Phase 7 artifacts: " + ", ".join(missing))
    checkpoint = read_csv(RAW / "STARTING_CHECKPOINT.csv")
    if len(checkpoint) != 1 or any(checkpoint[0][field] != APPROVED_PHASE6_COMMIT for field in (
        "local_head", "tracked_origin_main", "live_remote_main",
    )):
        raise Phase7Error("Starting checkpoint does not match the approved Phase 6 commit")
    validations = read_csv(PROCESSED / "VALIDATION_RESULTS.csv")
    failures = [row for row in validations if row["status"] != "PASS"]
    if failures:
        raise Phase7Error("Phase 7 validation failures: " + ", ".join(row["test_name"] for row in failures))
    ledger = read_csv(DOCS / "SOURCE_LEDGER.csv")
    if any(row["cutoff_status"] != "within_cutoff" for row in ledger):
        raise Phase7Error("Phase 7 source ledger includes post-cutoff evidence")
    if any(row["review_status"] not in {REVIEW, "phase7_record"} for row in ledger):
        raise Phase7Error("Phase 7 ledger contains an invalid review status")
    validate_changed_paths()
    return {
        "status": "PASS", "validations": len(validations), "ledger_rows": len(ledger),
        "generated_files": len(generated_files()),
        "proposed_covenant_breaches": sum(
            row["overall_covenant_status"] == "breached"
            for row in read_csv(PROCESSED / "COVENANT_TEST_RESULTS.csv")
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "validate", "all"), nargs="?", default="all")
    args = parser.parse_args()
    try:
        if args.command in ("build", "all"):
            print("Phase 7 build:", build())
        if args.command in ("validate", "all"):
            print("Phase 7 validation:", validate())
    except (Phase7Error, phase6.Phase6Error, OSError, subprocess.CalledProcessError) as exc:
        print(f"Phase 7 failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
