#!/usr/bin/env python3
"""Build and validate the Quanex Phase 2 reconciled historical spread.

The workflow is case-specific, deterministic, and network-independent. It
consumes the committed Phase 1 foundation, adds source-faithful extracts from
the same approved filings where statement reconciliation requires them, and
keeps owner-reviewed lender-normalization judgments distinct from contractual
eligibility and historical cash-flow treatment.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
PHASE1_FACTS = ROOT / "data" / "processed" / "historical_facts.csv"
PHASE1_PRO_FORMA = ROOT / "data" / "processed" / "pro_forma_facts.csv"
PHASE1_ADJUSTMENTS = ROOT / "data" / "processed" / "adjustment_candidates.csv"
PHASE1_DEBT = ROOT / "data" / "processed" / "debt_terms.csv"
PHASE1_MANIFEST = ROOT / "data" / "raw" / "SOURCE_MANIFEST.csv"
PHASE2_RAW = ROOT / "data" / "phase2" / "raw"
PHASE2_PROCESSED = ROOT / "data" / "phase2" / "processed"
PHASE2_DOCS = ROOT / "docs" / "phase-2"
CUTOFF = date(2025, 12, 15)
YEARS = tuple(f"FY{year}" for year in range(2021, 2026))
MONEY_UNIT = "USD_millions"
RECON_TOLERANCE = Decimal("0.001")
COMPANY_ROUNDED_TOLERANCE = Decimal("0.05")
VALID_SOURCES = {
    "SRC-001", "SRC-002", "SRC-003", "SRC-004", "SRC-008",
    "SRC-012", "SRC-013", "SRC-014", "SRC-016",
}

SUPPLEMENTAL_FIELDS = (
    "record_id", "category", "metric_name", "fiscal_year", "period_start",
    "period_end", "period_type", "original_value", "original_units",
    "normalized_value", "normalized_units", "source_id", "source_reference",
    "classification", "notes",
)
ADJUSTMENT_DECISION_FIELDS = (
    "adjustment_id", "fiscal_year", "description", "reported_amount",
    "units", "source_id", "company_treatment", "contractual_eligibility",
    "cash_noncash_status", "recurrence_assessment",
    "expected_cash_realization_or_reversal", "lender_recommendation",
    "accepted_amount_low", "accepted_amount_base", "accepted_amount_high",
    "rejected_or_haircut_amount_base", "rationale",
    "double_counting_relationships", "expiry_or_sunset_consideration",
    "missing_information", "human_review_status",
)
SPREAD_FIELDS = (
    "spread_id", "fiscal_year", "period_start", "period_end", "period_type", "section",
    "metric_name", "value", "units", "status", "classification",
    "source_ids", "input_ids", "calculation", "comparability_status", "notes",
)
BRIDGE_FIELDS = (
    "bridge_id", "fiscal_year", "bridge_type", "sequence", "line_item",
    "adjustment_id", "amount", "resulting_subtotal", "units", "status",
    "classification", "source_ids", "input_ids", "cash_noncash_status",
    "recurrence_assessment", "company_included", "contractual_eligibility",
    "lender_treatment", "cap_or_expiry", "double_counting_risk",
    "human_review_status", "rationale",
)
METRIC_FIELDS = (
    "metric_id", "fiscal_year", "metric_name", "numerator", "denominator",
    "value", "display_value", "units", "status", "failure_flag",
    "source_ids", "input_ids", "calculation", "comparability_note", "notes",
)
RECON_FIELDS = (
    "check_id", "fiscal_year", "category", "description", "left_value",
    "right_value", "difference", "tolerance", "status", "severity",
    "source_ids", "input_ids", "resolution", "notes",
)
LEDGER_FIELDS = (
    "record_id", "output_file", "layer", "fiscal_year", "metric_or_term",
    "source_ids", "input_ids", "document_titles", "source_urls",
    "publication_or_filing_dates", "classification", "human_review_status",
    "notes",
)


class Phase2Error(RuntimeError):
    """A failure that makes the Phase 2 output unsafe to use."""


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise Phase2Error(f"Missing required input: {path.relative_to(ROOT)}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict[str, str]],
              fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, extrasaction="raise", lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def dec(value: str | int | Decimal, label: str = "value") -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise Phase2Error(f"Invalid decimal for {label}: {value!r}") from exc


def fmt(value: Decimal | str | int | None) -> str:
    if value is None or value == "":
        return ""
    number = dec(value)
    result = format(number, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return result or "0"


def presentation(value: Decimal | str | None, places: int = 3) -> str:
    if value is None or value == "":
        return "N/D"
    quantum = Decimal(1).scaleb(-places)
    return f"{dec(value).quantize(quantum):,.{places}f}"


def period(year: str) -> tuple[str, str]:
    number = int(year[-4:])
    return f"{number - 1}-11-01", f"{number}-10-31"


def comparability(year: str) -> str:
    return {
        "FY2021": "pre_tyman",
        "FY2022": "pre_tyman",
        "FY2023": "pre_tyman_includes_lmi_from_2022_11_01",
        "FY2024": "mixed_perimeter_includes_three_months_tyman",
        "FY2025": "first_full_post_tyman_year_with_integration_effects",
    }[year]


def source_for_cash_flow(year: str) -> tuple[str, str]:
    if year in {"FY2023", "FY2024", "FY2025"}:
        return "SRC-001", "FY2025 Form 10-K, Consolidated Statements of Cash Flow, p. 46"
    if year == "FY2022":
        return "SRC-012", "FY2024 Form 10-K, Consolidated Statements of Cash Flow, p. 44"
    return "SRC-014", "FY2022 Form 10-K, Consolidated Statements of Cash Flow, p. 39"


def supplemental_seed_rows() -> list[dict[str, str]]:
    """Return source-faithful statement extracts omitted from Phase 1."""
    rows: list[dict[str, str]] = []

    def add(category: str, metric: str, year: str, value_thousands: int,
            source_id: str, reference: str, period_type: str = "duration",
            notes: str = "") -> None:
        start, end = period(year)
        if period_type == "instant":
            start = ""
        rows.append({
            "record_id": f"S2R-{len(rows) + 1:04d}",
            "category": category,
            "metric_name": metric,
            "fiscal_year": year,
            "period_start": start,
            "period_end": end,
            "period_type": period_type,
            "original_value": str(value_thousands),
            "original_units": "USD_thousands",
            "normalized_value": fmt(Decimal(value_thousands) / 1000),
            "normalized_units": MONEY_UNIT,
            "source_id": source_id,
            "source_reference": reference,
            "classification": "reported_supplemental_extract",
            "notes": notes,
        })

    balance_totals = {
        "FY2021": (717323, 297541, 419782, "SRC-014", "FY2022 Form 10-K, Consolidated Balance Sheets, p. 35"),
        "FY2022": (724617, 259782, 464835, "SRC-014", "FY2022 Form 10-K, Consolidated Balance Sheets, p. 35"),
        "FY2023": (831143, 285589, 545554, "SRC-012", "FY2024 Form 10-K, Consolidated Balance Sheets, p. 40"),
        "FY2024": (2319788, 1309042, 1010746, "SRC-001", "FY2025 Form 10-K, Consolidated Balance Sheets, p. 42"),
        "FY2025": (1968233, 1242054, 726179, "SRC-001", "FY2025 Form 10-K, Consolidated Balance Sheets, p. 42"),
    }
    for year, (assets, liabilities, equity, source, reference) in balance_totals.items():
        add("balance_sheet", "total_assets", year, assets, source, reference, "instant")
        add("balance_sheet", "total_liabilities", year, liabilities, source, reference, "instant")
        add("balance_sheet", "shareholders_equity", year, equity, source, reference, "instant")

    cfo_components: dict[str, dict[str, int | None]] = {
        "FY2021": {
            "cash_flow_depreciation_and_amortization": 42732,
            "gain_loss_on_disposition_noncash": 3039,
            "stock_based_compensation": 1970,
            "deferred_income_taxes": 1785,
            "deferred_loan_costs_charge": 0,
            "goodwill_impairment_noncash": 0,
            "fx_forward_gain_noncash": 0,
            "noncash_restructuring": None,
            "other_noncash_operating": 2126,
            "change_accounts_receivable": -19017,
            "change_inventory": -31382,
            "change_other_current_assets": -1817,
            "change_accounts_payable": 7097,
            "change_accrued_liabilities": 16212,
            "change_income_taxes_payable": -378,
            "change_deferred_pension": -708,
            "change_other_long_term_liabilities": 477,
            "other_operating_changes": -528,
        },
        "FY2022": {
            "cash_flow_depreciation_and_amortization": 40109,
            "gain_loss_on_disposition_noncash": 109,
            "stock_based_compensation": 2291,
            "deferred_income_taxes": 2097,
            "deferred_loan_costs_charge": 0,
            "goodwill_impairment_noncash": 0,
            "fx_forward_gain_noncash": 0,
            "noncash_restructuring": None,
            "other_noncash_operating": 1905,
            "change_accounts_receivable": 6945,
            "change_inventory": -32035,
            "change_other_current_assets": -970,
            "change_accounts_payable": -3047,
            "change_accrued_liabilities": -3159,
            "change_income_taxes_payable": -5192,
            "change_deferred_pension": 77,
            "change_other_long_term_liabilities": 305,
            "other_operating_changes": 194,
        },
        "FY2023": {
            "cash_flow_depreciation_and_amortization": 42866,
            "gain_loss_on_disposition_noncash": 278,
            "stock_based_compensation": 2521,
            "deferred_income_taxes": 5147,
            "deferred_loan_costs_charge": 0,
            "goodwill_impairment_noncash": 0,
            "fx_forward_gain_noncash": 0,
            "noncash_restructuring": 0,
            "other_noncash_operating": 1529,
            "change_accounts_receivable": 6969,
            "change_inventory": 30024,
            "change_other_current_assets": -1880,
            "change_accounts_payable": -11611,
            "change_accrued_liabilities": -4249,
            "change_income_taxes_payable": -9009,
            "change_deferred_pension": None,
            "change_other_long_term_liabilities": 683,
            "other_operating_changes": 1283,
        },
        "FY2024": {
            "cash_flow_depreciation_and_amortization": 60328,
            "gain_loss_on_disposition_noncash": -5218,
            "stock_based_compensation": 2952,
            "deferred_income_taxes": -15336,
            "deferred_loan_costs_charge": 3469,
            "goodwill_impairment_noncash": 0,
            "fx_forward_gain_noncash": -6512,
            "noncash_restructuring": 0,
            "other_noncash_operating": 4495,
            "change_accounts_receivable": 973,
            "change_inventory": 33484,
            "change_other_current_assets": 4297,
            "change_accounts_payable": -35824,
            "change_accrued_liabilities": 6250,
            "change_income_taxes_payable": 9139,
            "change_deferred_pension": None,
            "change_other_long_term_liabilities": -7155,
            "other_operating_changes": 411,
        },
        "FY2025": {
            "cash_flow_depreciation_and_amortization": 103444,
            "gain_loss_on_disposition_noncash": 613,
            "stock_based_compensation": 3685,
            "deferred_income_taxes": -18535,
            "deferred_loan_costs_charge": 0,
            "goodwill_impairment_noncash": 302284,
            "fx_forward_gain_noncash": 0,
            "noncash_restructuring": 4561,
            "other_noncash_operating": 7114,
            "change_accounts_receivable": -6878,
            "change_inventory": 23553,
            "change_other_current_assets": -3653,
            "change_accounts_payable": 3313,
            "change_accrued_liabilities": -9657,
            "change_income_taxes_payable": 11108,
            "change_deferred_pension": None,
            "change_other_long_term_liabilities": -4693,
            "other_operating_changes": -556,
        },
    }
    for year, values in cfo_components.items():
        source, reference = source_for_cash_flow(year)
        for metric, value in values.items():
            if value is not None:
                add("cash_flow_bridge", metric, year, value, source, reference)

    cash_summary = {
        "FY2021": (-18708, 0, -65000, 0, -680, 16272, 0, -492, -71861, 421, -11560, 51621, 40061),
        "FY2022": (-32962, 70500, -95500, -1210, -1747, 689, 0, -1413, -45879, -4092, 15032, 40061, 55093),
        "FY2023": (-128439, 102000, -100000, 0, -2567, 1215, 0, -567, -16151, 919, 3381, 55093, 58474),
        "FY2024": (-420594, 785000, -83750, -13808, -296206, 573, 6512, -1193, 385156, -8853, 44521, 58474, 102995),
        "FY2025": (-62008, 190000, -265000, 0, -4045, 214, 0, -1400, -127480, -286, -24877, 102995, 78118),
    }
    cash_names = (
        "investing_cash_flow_total", "credit_facility_borrowings",
        "credit_facility_repayments", "debt_issuance_costs",
        "other_long_term_debt_repayments", "common_stock_issuance",
        "hedge_contract_proceeds", "payroll_tax_stock_vesting",
        "financing_cash_flow_total", "fx_effect_on_cash",
        "net_change_cash_reported", "cash_begin_total", "cash_end_total",
    )
    for year, values in cash_summary.items():
        source, reference = source_for_cash_flow(year)
        for metric, value in zip(cash_names, values):
            add("cash_flow_summary", metric, year, value, source, reference)

    debt_history = {
        "FY2021": (0, 38000, 15537, 597, 53537, 52940),
        "FY2022": (0, 13000, 19202, 1528, 32202, 30674),
        "FY2023": (0, 15000, 55000, 1200, 70000, 68800),
    }
    for year, (term, revolver, leases, fees, principal, carrying) in debt_history.items():
        if year == "FY2023":
            source = "SRC-012"
            reference = "FY2024 Form 10-K Note 9, Long-term debt, p. 61"
        else:
            source = "SRC-014"
            reference = "FY2022 Form 10-K Note 8, Long-term debt, p. 54"
        for metric, value in (
            ("term_loan_principal", term), ("revolver_borrowings", revolver),
            ("finance_lease_obligations_principal", leases),
            ("unamortized_financing_fees", fees),
            ("total_debt_principal", principal),
            ("total_debt_carrying_amount", carrying),
        ):
            add("debt", metric, year, value, source, reference, "instant")
    add("debt", "unamortized_financing_fees", "FY2024", 13983, "SRC-012",
        "FY2024 Form 10-K Note 9, Long-term debt, p. 61", "instant",
        "Contra-debt amount; retained separately from principal.")
    add("debt", "unamortized_financing_fees", "FY2025", 11040, "SRC-001",
        "FY2025 Form 10-K Note 9, Long-term debt, p. 62", "instant",
        "Contra-debt amount; retained separately from principal.")

    # Append newly sourced diagnostics so existing supplemental record IDs remain
    # stable. SRC-001 Note 1 separately discloses historical cash paid for
    # interest. This is not the contractual paid-or-payable denominator and does
    # not establish closing-LTM coverage.
    for year, value in {"FY2023": 5737, "FY2024": 10910, "FY2025": 52630}.items():
        add(
            "supplemental_cash_flow",
            "cash_interest_paid_disclosed",
            year,
            value,
            "SRC-001",
            "FY2025 Form 10-K Note 1, Supplemental Cash Flow Information, p. 55",
            notes=(
                "Reported cash paid for interest; separate historical diagnostic. "
                "Not contractual interest paid or payable and not closing-LTM evidence."
            ),
        )
    return rows


def adjustment_decision_rows(candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    proposals = {
        "AC-001": (
            "Goodwill impairment", "likely_permitted_nonrecurring_noncash_or_intangible_write_down",
            "noncash", "nonrecurring_charge_but_material_business_risk_signal", "no cash reversal",
            "accepted", "302.284", "302.284", "302.284",
            "Full mathematical reversal is appropriate because the charge is noncash; retain the impairment as a major asset-quality and forecasting warning.",
            "Matches the FY2025 GAAP impairment and CFO noncash addback; do not add either again.",
            "No contractual expiry identified for the recorded charge; no forward addback implied.",
            "Official compliance certificate and lender calculation are unavailable.",
        ),
        "AC-002": (
            "Plant relocation cost recorded in cost of sales", "not_clearly_permitted_from_public_record",
            "cash_status_not_disclosed", "temporary_but_execution_cost_may_recur_during_stabilization", "cash timing not disclosed",
            "pending_information", "0", "0", "1.432",
            "Owner-reviewed base acceptance is zero because the disclosure does not establish cash character, completion, or nonrecurrence; the full amount remains only in the company/high sensitivity.",
            "Paired with AC-003; neither may also be included through a broader restructuring line.",
            "Sunset when the relocation/stabilization program ends; no carry-forward assumed.",
            "Invoice detail, cash timing, completion evidence, and contractual classification.",
        ),
        "AC-003": (
            "Plant relocation cost recorded in SG&A", "not_clearly_permitted_from_public_record",
            "cash_status_not_disclosed", "temporary_but_execution_cost_may_recur_during_stabilization", "cash timing not disclosed",
            "pending_information", "0", "0", "0.221",
            "Owner-reviewed base acceptance is zero because the disclosure does not establish cash character, completion, or nonrecurrence; the full amount remains only in the company/high sensitivity.",
            "Paired with AC-002; neither may also be included through a broader restructuring line.",
            "Sunset when the relocation/stabilization program ends; no carry-forward assumed.",
            "Invoice detail, cash timing, completion evidence, and contractual classification.",
        ),
        "AC-004": (
            "Inventory purchase-accounting step-up", "likely_permitted_nonrecurring_noncash_acquisition_accounting_subject_to_certificate",
            "noncash_purchase_accounting_expense", "nonrecurring_for_acquired_inventory", "no future cash realization; expense has run through earnings",
            "accepted", "9.007", "9.007", "9.007",
            "The fair-value step-up is a finite acquisition-accounting charge rather than recurring operating cost; full acceptance does not erase acquisition risk.",
            "Do not also add this amount through a pro forma purchase-accounting adjustment.",
            "Expires after the acquired inventory is sold; no forward carry after exhaustion.",
            "Official contractual classification and compliance certificate.",
        ),
        "AC-005": (
            "Transaction, advisory, reorganization, and product-recall composite", "mixed_and_not_determinable_from_public_record",
            "mixed_or_not_disclosed", "mixed_category_includes_potentially_recurring_operational_cost", "cash realization cannot be assessed without disaggregation",
            "pending_information", "0", "0", "10.263",
            "Base acceptance is zero because transaction, reorganization, and recall costs are inseparable; the full company amount is retained only as an upper case pending evidence.",
            "Potential overlap with acquisition costs, restructuring, and operating remediation; no other bridge may absorb it.",
            "Any eligible acquisition-service cost would be subject to the agreement's 90-day incurrence limit.",
            "Component amounts, invoices, cash/noncash split, dates, recall scope, and recurrence evidence.",
        ),
        "AC-006": (
            "Restructuring, severance, and software", "only_identified_one_time_noncash_restructuring_component_clearly_permitted",
            "mixed_4.561_noncash_remainder_not_established_noncash", "partly_nonrecurring_with_cash_execution_risk", "noncash portion has no cash reversal; remaining 5.630 may consume cash",
            "partial_accept", "4.561", "4.561", "10.191",
            "Accept only the $4.561 million noncash restructuring amount reconciled in the cash-flow statement; defer the remaining $5.630 million.",
            "The $4.561 million CFO addback is evidence of noncash character, not a second EBITDA adjustment.",
            "No forward carry; cash reversals of prior noncash charges must be deducted under the agreement.",
            "Cash payments, project completion, software write-off detail, and official covenant treatment.",
        ),
        "AC-007": (
            "Tyman post-measurement-period deferred-tax correction", "tax_is_already_excluded_in_ebitda",
            "noncash_deferred_tax_accounting", "nonrecurring_tax_measurement_correction", "no EBITDA cash realization",
            "not_applicable", "0", "0", "0",
            "The $9 million charge matters to adjusted net income and tax quality but cannot be added again to EBITDA because income taxes are already excluded.",
            "Adding it to EBITDA would double count the standard tax addback.",
            "Not applicable to EBITDA; retain for tax-quality review only.",
            "Cash-tax implications, if any, remain unavailable.",
        ),
        "AC-008": (
            "Plant closure cost recorded in cost of sales", "not_clearly_permitted_from_public_record",
            "cash_status_not_disclosed", "closure_related_but_recurrence_and_cash_timing_not_proven", "cash timing not disclosed",
            "pending_information", "0", "0", "3.025",
            "Owner-reviewed base acceptance is zero because closure specificity alone does not prove cash character, completion, or nonrecurrence; the full amount remains only in the company/high sensitivity.",
            "Must not overlap with other restructuring or disposition adjustments.",
            "No carry beyond the closure period without new support.",
            "Cash/noncash split, closure completion, and contractual classification.",
        ),
        "AC-009": (
            "Plant closure gain recorded in SG&A", "likely_required_deduction_for_unusual_or_disposition_gain",
            "noncash_gain_component_with_separate_sale_proceeds", "nonrecurring_gain", "no future earnings benefit assumed",
            "accepted", "-4.196", "-4.196", "-4.196",
            "Deduct the gain in full, consistent with both the company bridge and lender conservatism; excluding losses while retaining gains would be asymmetric.",
            "Do not also deduct the related disposition gain through another contractual line.",
            "Applies only to FY2024.",
            "Official compliance presentation is unavailable.",
        ),
        "AC-010": (
            "Inventory and receivables purchase-accounting step-up", "likely_permitted_acquisition_accounting_or_pro_forma_item_subject_to_certificate",
            "noncash_purchase_accounting_expense", "nonrecurring_for_acquired_balances", "no future cash realization; accounting discount/step-up has run through earnings",
            "accepted", "29.076", "29.076", "29.076",
            "Owner-reviewed full acceptance reflects a finite acquisition-accounting effect; collectability, cash-realization, integration, and pro forma limitations remain separate from the earnings normalization.",
            "Do not also include it in a separate acquisition pro forma or working-capital adjustment.",
            "Expires as acquired inventory and receivables are realized.",
            "Official contractual bridge, precise inventory/receivable split, and evidence on collectability and cash realization.",
        ),
        "AC-011": (
            "Tyman transaction and advisory fees", "not_determinable_without_out_of_pocket_support_incurrence_dates_and_compliance_certificate",
            "cash", "nonrecurring_completed_acquisition_cost", "cash was consumed historically; no reversal",
            "accepted", "39.324", "39.324", "39.324",
            "Owner-reviewed lender earnings normalization accepts the completed-transaction cost, but contractual eligibility remains unresolved and historical cash conversion continues to reflect the cash use.",
            "Do not also add the same fees through a pro forma acquisition-cost line.",
            "Any contractual eligibility would depend on the agreement's acquisition-cost timing and evidence requirements; no forward carry is assumed.",
            "Invoices, payees, exact incurrence dates, and official compliance certificate.",
        ),
    }
    rows = []
    for candidate in candidates:
        cid = candidate["candidate_id"]
        if cid not in proposals:
            raise Phase2Error(f"No Phase 2 decision for {cid}")
        (description, eligibility, cash_status, recurrence, realization,
         recommendation, low, base, high, rationale, overlap, sunset,
         missing) = proposals[cid]
        amount = dec(candidate["normalized_value"], cid)
        accepted = dec(base, cid)
        rejected = Decimal(0) if amount < 0 and accepted == amount else amount - accepted
        rows.append({
            "adjustment_id": cid,
            "fiscal_year": candidate["fiscal_year"],
            "description": description,
            "reported_amount": fmt(amount),
            "units": MONEY_UNIT,
            "source_id": candidate["source_id"],
            "company_treatment": candidate["company_treatment"],
            "contractual_eligibility": eligibility,
            "cash_noncash_status": cash_status,
            "recurrence_assessment": recurrence,
            "expected_cash_realization_or_reversal": realization,
            "lender_recommendation": recommendation,
            "accepted_amount_low": low,
            "accepted_amount_base": base,
            "accepted_amount_high": high,
            "rejected_or_haircut_amount_base": fmt(rejected),
            "rationale": rationale,
            "double_counting_relationships": overlap,
            "expiry_or_sunset_consideration": sunset,
            "missing_information": missing,
            "human_review_status": "owner_reviewed",
        })
    return rows


def index_unique(rows: list[dict[str, str]], key_fields: tuple[str, ...],
                 label: str) -> dict[tuple[str, ...], dict[str, str]]:
    result: dict[tuple[str, ...], dict[str, str]] = {}
    for row in rows:
        key = tuple(row[field] for field in key_fields)
        if key in result:
            raise Phase2Error(f"Duplicate {label}: {key}")
        result[key] = row
    return result


def build_spread(phase1: list[dict[str, str]],
                 supplemental: list[dict[str, str]]) -> list[dict[str, str]]:
    facts = index_unique(phase1, ("fiscal_year", "metric_name"), "Phase 1 fact")
    supp = index_unique(supplemental, ("fiscal_year", "metric_name"), "supplemental fact")
    rows: list[dict[str, str]] = []

    def add(year: str, section: str, metric: str, value: Decimal | None,
            status: str, classification: str, source_ids: str, input_ids: str,
            calculation: str = "", notes: str = "") -> None:
        start, end = period(year)
        period_type = "instant" if section in {"balance_sheet", "debt"} else "duration"
        if period_type == "instant":
            start = ""
        rows.append({
            "spread_id": f"S2S-{len(rows) + 1:04d}", "fiscal_year": year,
            "period_start": start, "period_end": end, "period_type": period_type,
            "section": section,
            "metric_name": metric, "value": fmt(value), "units": MONEY_UNIT,
            "status": status, "classification": classification,
            "source_ids": source_ids, "input_ids": input_ids,
            "calculation": calculation, "comparability_status": comparability(year),
            "notes": notes,
        })

    def from_phase1(year: str, section: str, metric: str,
                    output_metric: str | None = None) -> Decimal:
        row = facts[(year, metric)]
        value = dec(row["normalized_value"], row["fact_id"])
        add(year, section, output_metric or metric, value, "supported",
            row["classification"], row["source_ids"], row["fact_id"],
            row["calculation"], row["notes"])
        return value

    def from_supp(year: str, section: str, metric: str,
                  output_metric: str | None = None) -> Decimal:
        row = supp[(year, metric)]
        value = dec(row["normalized_value"], row["record_id"])
        add(year, section, output_metric or metric, value, "supported",
            row["classification"], row["source_id"], row["record_id"], "",
            row["notes"])
        return value

    income_metrics = (
        "revenue", "cost_of_sales_excluding_depreciation_and_amortization",
        "gross_profit", "selling_general_and_administrative",
        "depreciation_and_amortization", "goodwill_impairment_charges",
        "restructuring_charges", "operating_income", "interest_expense",
        "income_tax_expense", "net_income",
    )
    for year in YEARS:
        values: dict[str, Decimal] = {}
        for metric in income_metrics:
            if (year, metric) in facts:
                values[metric] = from_phase1(year, "income_statement", metric)
            elif metric in {"goodwill_impairment_charges", "restructuring_charges"}:
                add(year, "income_statement", metric, Decimal(0), "not_separately_presented_assumed_zero",
                    "presentation_control", "", "", "",
                    "No separate line in the selected statement; zero is used only for statement presentation, not for missing cash-flow items.")
                values[metric] = Decimal(0)
            else:
                raise Phase2Error(f"Missing required income fact: {year} {metric}")
        pretax = values["net_income"] - values["income_tax_expense"]
        other = pretax - values["operating_income"] - values["interest_expense"]
        sources = ";".join(sorted(set(
            facts[(year, metric)]["source_ids"] for metric in
            ("net_income", "income_tax_expense", "operating_income", "interest_expense")
        )))
        ids = ";".join(facts[(year, metric)]["fact_id"] for metric in
                       ("net_income", "income_tax_expense", "operating_income", "interest_expense"))
        add(year, "income_statement", "other_income_expense", other, "supported",
            "calculated", sources, ids,
            "pretax_income - operating_income - interest_expense")
        add(year, "income_statement", "pretax_income", pretax, "supported",
            "calculated", sources, ids, "net_income - income_tax_expense")
        unadjusted = values["operating_income"] - values["depreciation_and_amortization"]
        add(year, "earnings", "unadjusted_ebitda", unadjusted, "supported",
            "calculated", sources,
            f"{facts[(year, 'operating_income')]['fact_id']};{facts[(year, 'depreciation_and_amortization')]['fact_id']}",
            "operating_income - normalized_negative_D&A",
            "Company-style EBITDA excludes other, net; no credit adjustments included.")

    balance_phase1 = (
        "cash_and_cash_equivalents", "accounts_receivable", "inventory",
        "accounts_payable", "current_assets", "current_liabilities",
        "property_plant_and_equipment_net", "goodwill", "intangible_assets_net",
        "current_maturities_of_long_term_debt", "long_term_debt",
        "current_operating_lease_liabilities", "noncurrent_operating_lease_liabilities",
        "total_operating_lease_liabilities",
    )
    for year in YEARS:
        for metric in balance_phase1:
            from_phase1(year, "balance_sheet", metric)
        for metric in ("total_assets", "total_liabilities", "shareholders_equity"):
            from_supp(year, "balance_sheet", metric)
        asset_parts = []
        if (year, "prepaid_and_other_current_assets") in facts:
            asset_parts.append(facts[(year, "prepaid_and_other_current_assets")])
        else:
            for metric in ("prepaid_assets", "other_current_assets"):
                asset_parts.append(facts[(year, metric)])
        if (year, "income_taxes_receivable") in facts:
            asset_parts.append(facts[(year, "income_taxes_receivable")])
        other_assets = sum((dec(row["normalized_value"]) for row in asset_parts), Decimal(0))
        add(year, "balance_sheet", "other_presented_current_assets", other_assets,
            "supported", "calculated", ";".join(sorted({r["source_ids"] for r in asset_parts})),
            ";".join(r["fact_id"] for r in asset_parts), "sum of separately presented other current asset lines",
            "Presentation changed in FY2024-FY2025; components remain preserved in Phase 1.")
        liability_parts = [facts[(year, "accrued_liabilities")], facts[(year, "income_taxes_payable")]]
        other_liabilities = sum((dec(row["normalized_value"]) for row in liability_parts), Decimal(0))
        add(year, "balance_sheet", "other_presented_operating_current_liabilities",
            other_liabilities, "supported", "calculated",
            ";".join(sorted({r["source_ids"] for r in liability_parts})),
            ";".join(r["fact_id"] for r in liability_parts),
            "accrued_liabilities + income_taxes_payable")

    cfo_detail = (
        "cash_flow_depreciation_and_amortization", "goodwill_impairment_noncash",
        "stock_based_compensation", "deferred_income_taxes",
        "gain_loss_on_disposition_noncash", "deferred_loan_costs_charge",
        "fx_forward_gain_noncash", "noncash_restructuring",
        "other_noncash_operating", "change_accounts_receivable", "change_inventory",
        "change_other_current_assets", "change_accounts_payable",
        "change_accrued_liabilities", "change_income_taxes_payable",
        "change_deferred_pension", "change_other_long_term_liabilities",
        "other_operating_changes",
    )
    cash_summary_metrics = (
        "investing_cash_flow_total", "credit_facility_borrowings",
        "credit_facility_repayments", "debt_issuance_costs",
        "other_long_term_debt_repayments", "common_stock_issuance",
        "hedge_contract_proceeds", "payroll_tax_stock_vesting",
        "financing_cash_flow_total", "fx_effect_on_cash", "net_change_cash_reported",
        "cash_begin_total", "cash_end_total",
    )
    for year in YEARS:
        from_phase1(year, "cash_flow", "net_income", "cash_flow_net_income")
        for metric in cfo_detail:
            if (year, metric) in supp:
                from_supp(year, "cash_flow", metric)
            else:
                add(year, "cash_flow", metric, None, "not_separately_presented_not_zero",
                    "missing_control", "", "", "", "Omitted from the selected presentation; not converted to zero.")
        working_cap_components = (
            "change_other_current_assets", "change_accrued_liabilities",
            "change_income_taxes_payable", "change_deferred_pension",
            "change_other_long_term_liabilities", "other_operating_changes",
        )
        available = [supp[(year, metric)] for metric in working_cap_components if (year, metric) in supp]
        total_other_wc = sum((dec(row["normalized_value"]) for row in available), Decimal(0))
        add(year, "cash_flow", "other_operating_working_capital_movements", total_other_wc,
            "supported", "calculated", ";".join(sorted({r["source_id"] for r in available})),
            ";".join(r["record_id"] for r in available), "sum of other reported operating balance movements")
        from_phase1(year, "cash_flow", "cash_flow_from_operations")
        from_phase1(year, "cash_flow", "capital_expenditures")
        from_phase1(year, "cash_flow", "free_cash_flow_before_finance_lease_payments", "free_cash_flow")
        if (year, "acquisition_cash_flows") in facts:
            from_phase1(year, "cash_flow", "acquisition_cash_flows")
        else:
            add(year, "cash_flow", "acquisition_cash_flows", None,
                "not_determinable_not_zero", "missing_control", "", "", "",
                "No dedicated material acquisition-cash-flow line in the selected Phase 1 statement; absence is not zero.")
        from_phase1(year, "cash_flow", "dividends_paid")
        from_phase1(year, "cash_flow", "share_repurchases")
        for metric in cash_summary_metrics:
            from_supp(year, "cash_flow", metric)
        other_financing_names = (
            "debt_issuance_costs", "common_stock_issuance",
            "hedge_contract_proceeds", "payroll_tax_stock_vesting",
        )
        components = [supp[(year, metric)] for metric in other_financing_names]
        other_financing = sum((dec(row["normalized_value"]) for row in components), Decimal(0))
        add(year, "cash_flow", "other_material_financing_flows", other_financing,
            "supported", "calculated", ";".join(sorted({r["source_id"] for r in components})),
            ";".join(r["record_id"] for r in components), "sum of debt issuance costs, stock issuance, hedge proceeds, and vesting payroll tax")

    for year in YEARS:
        if year in {"FY2024", "FY2025"}:
            for metric in ("term_loan_principal", "revolver_borrowings",
                           "finance_lease_obligations_principal", "total_debt_principal"):
                from_phase1(year, "debt", metric)
            fee_row = supp[(year, "unamortized_financing_fees")]
            fees = dec(fee_row["normalized_value"])
            add(year, "debt", "unamortized_financing_fees", fees, "supported",
                "reported_supplemental_extract", fee_row["source_id"], fee_row["record_id"], "",
                "Contra-debt amount; presented as a positive reconciling value.")
            from_phase1(year, "debt", "total_debt_carrying_amount")
        else:
            for metric in ("term_loan_principal", "revolver_borrowings",
                           "finance_lease_obligations_principal", "total_debt_principal",
                           "unamortized_financing_fees", "total_debt_carrying_amount"):
                from_supp(year, "debt", metric)

    # Append the new historical-interest diagnostic so all previously published
    # spread IDs retain their meaning. Missing FY2021-FY2022 values remain
    # explicit missing controls and are never converted to zero.
    for year in YEARS:
        if (year, "cash_interest_paid_disclosed") in supp:
            from_supp(year, "cash_flow", "cash_interest_paid_disclosed")
        else:
            add(
                year,
                "cash_flow",
                "cash_interest_paid_disclosed",
                None,
                "not_determinable_not_zero",
                "missing_control",
                "",
                "",
                "",
                "The approved evidence does not contain a separate cash-paid-interest disclosure for this year; absence is not zero.",
            )
    return rows


def spread_index(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return index_unique(rows, ("fiscal_year", "metric_name"), "spread row")


def build_bridges(spread: list[dict[str, str]], decisions: list[dict[str, str]],
                  supplemental: list[dict[str, str]]) -> list[dict[str, str]]:
    values = spread_index(spread)
    decisions_by_year: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in decisions:
        decisions_by_year[row["fiscal_year"]].append(row)
    supp = index_unique(supplemental, ("fiscal_year", "metric_name"), "supplemental fact")
    rows: list[dict[str, str]] = []

    def add(year: str, bridge_type: str, sequence: int, line_item: str,
            amount: Decimal | None, subtotal: Decimal | None, status: str,
            classification: str, source_ids: str, input_ids: str,
            decision: dict[str, str] | None = None, rationale: str = "") -> None:
        rows.append({
            "bridge_id": f"S2B-{len(rows) + 1:04d}", "fiscal_year": year,
            "bridge_type": bridge_type, "sequence": str(sequence),
            "line_item": line_item,
            "adjustment_id": decision["adjustment_id"] if decision else "",
            "amount": fmt(amount), "resulting_subtotal": fmt(subtotal),
            "units": MONEY_UNIT, "status": status, "classification": classification,
            "source_ids": source_ids, "input_ids": input_ids,
            "cash_noncash_status": decision["cash_noncash_status"] if decision else "",
            "recurrence_assessment": decision["recurrence_assessment"] if decision else "",
            "company_included": decision["company_treatment"] if decision else "",
            "contractual_eligibility": decision["contractual_eligibility"] if decision else "",
            "lender_treatment": decision["lender_recommendation"] if decision else "",
            "cap_or_expiry": decision["expiry_or_sunset_consideration"] if decision else "",
            "double_counting_risk": decision["double_counting_relationships"] if decision else "",
            "human_review_status": decision["human_review_status"] if decision else "not_applicable",
            "rationale": rationale or (decision["rationale"] if decision else ""),
        })

    for year in YEARS:
        operating = dec(values[(year, "operating_income")]["value"])
        dna = -dec(values[(year, "depreciation_and_amortization")]["value"])
        unadjusted = operating + dna
        add(year, "unadjusted_ebitda", 1, "GAAP operating income", operating, operating,
            "supported", "reported", values[(year, "operating_income")]["source_ids"],
            values[(year, "operating_income")]["input_ids"])
        add(year, "unadjusted_ebitda", 2, "Add: depreciation and amortization", dna,
            unadjusted, "supported", "calculated",
            values[(year, "depreciation_and_amortization")]["source_ids"],
            values[(year, "depreciation_and_amortization")]["input_ids"],
            rationale="No credit adjustment; standard EBITDA construction.")

        add(year, "company_adjusted_ebitda", 1, "Unadjusted EBITDA", unadjusted,
            unadjusted, "supported", "calculated", "", values[(year, "unadjusted_ebitda")]["spread_id"])
        company_subtotal = unadjusted
        company_sequence = 2
        if decisions_by_year[year]:
            for decision in decisions_by_year[year]:
                if decision["adjustment_id"] == "AC-007":
                    continue
                amount = dec(decision["reported_amount"])
                company_subtotal += amount
                add(year, "company_adjusted_ebitda", company_sequence,
                    decision["description"], amount, company_subtotal, "supported",
                    "company_adjustment", decision["source_id"], decision["adjustment_id"], decision)
                company_sequence += 1
            add(year, "company_adjusted_ebitda", company_sequence,
                "Company-adjusted EBITDA reconstructed from disclosed bridge", Decimal(0),
                company_subtotal, "supported", "calculated", "SRC-002",
                ";".join(d["adjustment_id"] for d in decisions_by_year[year] if d["adjustment_id"] != "AC-007"),
                rationale="Exact reconstruction; company publication presents the result rounded to one decimal million.")
        else:
            add(year, "company_adjusted_ebitda", company_sequence,
                "Company-adjusted EBITDA", None, None, "not_determinable",
                "missing_control", "", "",
                rationale="The approved Phase 1 evidence does not contain a company adjustment bridge for this year; unadjusted EBITDA is not relabeled.")

        add(year, "contractual_ebitda_public_reconstruction", 1, "Unadjusted EBITDA", unadjusted,
            unadjusted, "supported_starting_point", "calculated", "SRC-001;SRC-003",
            values[(year, "unadjusted_ebitda")]["spread_id"])
        if year == "FY2025":
            contract_subtotal = unadjusted
            contract_lines = (
                ("AC-001", dec(next(d for d in decisions if d["adjustment_id"] == "AC-001")["reported_amount"])),
                ("stock_based_compensation", dec(supp[(year, "stock_based_compensation")]["normalized_value"])),
                ("gain_loss_on_disposition_noncash", dec(supp[(year, "gain_loss_on_disposition_noncash")]["normalized_value"])),
                ("AC-006", dec(supp[(year, "noncash_restructuring")]["normalized_value"])),
                ("AC-004", dec(next(d for d in decisions if d["adjustment_id"] == "AC-004")["reported_amount"])),
            )
            seq = 2
            for identifier, amount in contract_lines:
                contract_subtotal += amount
                if identifier.startswith("AC-"):
                    decision = next(d for d in decisions if d["adjustment_id"] == identifier)
                    add(year, "contractual_ebitda_public_reconstruction", seq,
                        decision["description"], amount, contract_subtotal,
                        "identifiable_public_component", "contractual_reconstruction",
                        decision["source_id"] + ";SRC-003", identifier, decision)
                else:
                    record = supp[(year, identifier)]
                    add(year, "contractual_ebitda_public_reconstruction", seq,
                        ("Noncash stock-based compensation" if identifier == "stock_based_compensation"
                         else "Noncash loss on disposition of capital assets"), amount, contract_subtotal,
                        "identifiable_public_component", "contractual_reconstruction",
                        record["source_id"] + ";SRC-003", record["record_id"],
                        rationale=("Agreement permits qualifying noncash equity compensation, subject to cash-reversal deductions."
                                   if identifier == "stock_based_compensation" else
                                   "Agreement permits qualifying noncash losses on sales of fixed assets; related proceeds remain in cash flow."))
                seq += 1
            add(year, "contractual_ebitda_public_reconstruction", seq,
                "Partial public-information contractual reconstruction", Decimal(0),
                contract_subtotal, "partial_not_official", "contractual_reconstruction",
                "SRC-001;SRC-002;SRC-003", "",
                rationale="Not an official covenant calculation: restricted subsidiary income, other-net components, cash reversals, and the compliance certificate are unavailable.")
        else:
            add(year, "contractual_ebitda_public_reconstruction", 2,
                "Contractual EBITDA", None, None, "not_determinable",
                "missing_control", "SRC-003", "",
                rationale="Public evidence does not provide the period-specific compliance bridge; FY2023-FY2024 acquisition pro forma mechanics add further uncertainty.")

        for case, decision_field, case_status, case_classification, final_label, case_rationale in (
            ("low", "accepted_amount_low", "owner_reviewed_low_sensitivity", "sensitivity",
             "Lender-normalized EBITDA (low sensitivity)",
             "Owner-reviewed lower sensitivity; it is not the selected lender base."),
            ("base", "accepted_amount_base", "owner_reviewed_lender_base", "owner_reviewed_lender_judgment",
             "Lender-normalized EBITDA (owner-reviewed base)",
             "Owner-reviewed lender-normalization base; contractual EBITDA and cash-flow treatment remain separate."),
            ("high", "accepted_amount_high", "company_case_sensitivity_not_lender_accepted", "sensitivity",
             "Company/high adjusted EBITDA case",
             "Company/high sensitivity preserves company treatment and is not accepted lender-base EBITDA."),
        ):
            bridge_type = f"provisional_lender_normalized_ebitda_{case}"
            subtotal = unadjusted
            add(year, bridge_type, 1, "Unadjusted EBITDA", unadjusted, subtotal,
                "supported", "calculated", "", values[(year, "unadjusted_ebitda")]["spread_id"],
                rationale="Starting measure for the labeled lender-normalization case.")
            seq = 2
            for decision in decisions_by_year[year]:
                amount = dec(decision[decision_field])
                subtotal += amount
                add(year, bridge_type, seq, decision["description"], amount, subtotal,
                    case_status, case_classification,
                    decision["source_id"], decision["adjustment_id"], decision)
                seq += 1
            add(year, bridge_type, seq, final_label,
                Decimal(0), subtotal, case_status,
                case_classification, "", ";".join(d["adjustment_id"] for d in decisions_by_year[year]),
                rationale=case_rationale)
    return rows


def final_bridge_values(bridges: list[dict[str, str]], bridge_type: str) -> dict[str, Decimal | None]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in bridges:
        if row["bridge_type"] == bridge_type:
            grouped[row["fiscal_year"]].append(row)
    result: dict[str, Decimal | None] = {}
    for year in YEARS:
        final = max(grouped[year], key=lambda row: int(row["sequence"]))
        result[year] = dec(final["resulting_subtotal"]) if final["resulting_subtotal"] else None
    return result


def build_metrics(spread: list[dict[str, str]], bridges: list[dict[str, str]]) -> list[dict[str, str]]:
    values = spread_index(spread)
    company = final_bridge_values(bridges, "company_adjusted_ebitda")
    lender = final_bridge_values(bridges, "provisional_lender_normalized_ebitda_base")
    lender_bridge_ids = {
        year: max(
            (row for row in bridges if row["fiscal_year"] == year and row["bridge_type"] == "provisional_lender_normalized_ebitda_base"),
            key=lambda row: int(row["sequence"]),
        )["bridge_id"]
        for year in YEARS
    }
    rows: list[dict[str, str]] = []

    def add(year: str, name: str, numerator: Decimal | None,
            denominator: Decimal | None, value: Decimal | None, units: str,
            status: str, failure: str, calculation: str, note: str = "",
            source_ids: str = "", input_ids: str = "") -> None:
        rows.append({
            "metric_id": f"S2M-{len(rows) + 1:04d}", "fiscal_year": year,
            "metric_name": name, "numerator": fmt(numerator),
            "denominator": fmt(denominator), "value": fmt(value),
            "display_value": "N/M" if status == "not_meaningful" else
                             ("N/D" if value is None else fmt(value)),
            "units": units, "status": status, "failure_flag": failure,
            "source_ids": source_ids, "input_ids": input_ids,
            "calculation": calculation, "comparability_note": comparability(year),
            "notes": note,
        })

    def ratio(year: str, name: str, numerator: Decimal | None,
              denominator: Decimal | None, units: str, calculation: str,
              require_positive_denominator: bool = False, note: str = "",
              source_ids: str = "", input_ids: str = "") -> None:
        if numerator is None or denominator is None:
            add(year, name, numerator, denominator, None, units, "not_determinable",
                "MISSING_INPUT", calculation, note, source_ids, input_ids)
        elif require_positive_denominator and denominator <= 0:
            add(year, name, numerator, denominator, None, units, "not_meaningful",
                "NONPOSITIVE_EBITDA", calculation,
                note or "Negative or zero EBITDA makes leverage or coverage not meaningful.",
                source_ids, input_ids)
        elif denominator == 0:
            add(year, name, numerator, denominator, None, units, "not_meaningful",
                "ZERO_DENOMINATOR", calculation, note, source_ids, input_ids)
        else:
            calculated = numerator / denominator
            if units == "percent":
                calculated *= 100
            add(year, name, numerator, denominator, calculated,
                units, "calculated", "", calculation, note, source_ids, input_ids)

    for position, year in enumerate(YEARS):
        revenue = dec(values[(year, "revenue")]["value"])
        gross_profit = dec(values[(year, "gross_profit")]["value"])
        operating = dec(values[(year, "operating_income")]["value"])
        unadjusted = dec(values[(year, "unadjusted_ebitda")]["value"])
        cfo = dec(values[(year, "cash_flow_from_operations")]["value"])
        fcf = dec(values[(year, "free_cash_flow")]["value"])
        debt = dec(values[(year, "total_debt_principal")]["value"])
        cash = dec(values[(year, "cash_and_cash_equivalents")]["value"])
        net_debt = debt - cash
        interest = -dec(values[(year, "interest_expense")]["value"])
        current_assets = dec(values[(year, "current_assets")]["value"])
        current_liabilities = dec(values[(year, "current_liabilities")]["value"])
        ar = dec(values[(year, "accounts_receivable")]["value"])
        inventory = dec(values[(year, "inventory")]["value"])
        ap = dec(values[(year, "accounts_payable")]["value"])
        cost = -dec(values[(year, "cost_of_sales_excluding_depreciation_and_amortization")]["value"])
        if position == 0:
            add(year, "revenue_growth", None, None, None, "percent",
                "not_determinable", "MISSING_PRIOR_YEAR", "current revenue / prior revenue - 1",
                "FY2020 is outside the approved five-year spread.")
        else:
            prior_revenue = dec(values[(YEARS[position - 1], "revenue")]["value"])
            ratio(year, "revenue_growth", revenue - prior_revenue, prior_revenue,
                  "percent", "(current revenue - prior revenue) / prior revenue",
                  note="FY2023 includes LMI; FY2024-FY2025 growth is acquisition-distorted and is not organic growth.")
        ratio(year, "gross_margin", gross_profit, revenue, "percent", "gross profit / revenue")
        ratio(year, "operating_margin", operating, revenue, "percent", "operating income / revenue")
        ratio(year, "unadjusted_ebitda_margin", unadjusted, revenue, "percent", "unadjusted EBITDA / revenue")
        ratio(year, "company_adjusted_ebitda_margin", company[year], revenue,
              "percent", "company-adjusted EBITDA / revenue")
        ratio(year, "provisional_lender_normalized_ebitda_margin", lender[year], revenue,
              "percent", "provisional lender-normalized EBITDA / revenue",
              note="Uses owner-reviewed lender-base judgments; not contractual EBITDA or a covenant calculation.")
        add(year, "cash_flow_from_operations", cfo, None, cfo, MONEY_UNIT,
            "reported", "", "reported CFO; includes cash interest", source_ids=values[(year, "cash_flow_from_operations")]["source_ids"])
        add(year, "free_cash_flow", fcf, None, fcf, MONEY_UNIT,
            "calculated", "", "CFO + normalized negative capital expenditures",
            "Cash interest is already included in CFO and is not subtracted again.")
        for label, ebitda in (("unadjusted", unadjusted), ("company_adjusted", company[year]),
                              ("provisional_lender_normalized", lender[year])):
            ratio(year, f"cfo_to_{label}_ebitda", cfo, ebitda, "percent",
                  f"CFO / {label} EBITDA", True)
            ratio(year, f"fcf_to_{label}_ebitda", fcf, ebitda, "percent",
                  f"FCF / {label} EBITDA", True)
        ratio(year, "cfo_to_gross_funded_debt", cfo, debt, "percent", "CFO / gross funded principal")
        ratio(year, "fcf_to_gross_funded_debt", fcf, debt, "percent", "FCF / gross funded principal")
        for label, ebitda in (("unadjusted", unadjusted), ("company_adjusted", company[year]),
                              ("provisional_lender_normalized", lender[year])):
            ratio(year, f"gross_funded_debt_to_{label}_ebitda", debt, ebitda,
                  "turns", f"gross funded principal / {label} EBITDA", True)
        add(year, "net_debt_book_cash_comparable", net_debt, None, net_debt,
            MONEY_UNIT, "calculated", "", "gross funded principal - book cash",
            "Not contractual net debt; book cash may be inaccessible or ineligible.")
        ratio(year, "net_debt_book_cash_to_provisional_lender_ebitda", net_debt,
              lender[year], "turns", "(gross funded principal - book cash) / provisional lender EBITDA",
              True, "Not the credit-agreement numerator; eligible cash is not public.")
        ratio(year, "provisional_lender_ebitda_to_interest_expense_proxy", lender[year],
              interest, "turns", "provisional lender EBITDA / GAAP interest expense", True,
              "Proxy only; contractual paid-or-payable and closing-LTM cash interest are unavailable. The separately disclosed historical cash-paid amount is presented in its own diagnostic.")
        add(
            year,
            "ebitda_to_cash_interest",
            lender[year],
            None,
            None,
            "turns",
            "not_determinable",
            "MISSING_CASH_INTEREST",
            "EBITDA / contractual cash interest paid or payable",
            "Contractual paid-or-payable and closing-LTM cash interest remain unavailable; the separately disclosed historical cash-paid amount is not substituted for this measure.",
        )
        ratio(year, "current_ratio", current_assets, current_liabilities, "turns",
              "current assets / current liabilities")
        ratio(year, "quick_ratio", cash + ar, current_liabilities, "turns",
              "(cash and cash equivalents + accounts receivable) / current liabilities",
              note="Restricted cash, inventory, tax receivables, and prepaids are excluded.")
        if position == 0:
            add(year, "days_sales_outstanding", None, None, None, "days",
                "not_determinable", "MISSING_OPENING_BALANCE",
                "average accounts receivable / revenue * actual fiscal days",
                "FY2020 opening balance is outside the approved foundation.")
            add(year, "days_inventory_outstanding", None, None, None, "days",
                "not_determinable", "MISSING_OPENING_BALANCE",
                "average inventory / cost of sales excluding D&A * actual fiscal days",
                "FY2020 opening balance is outside the approved foundation.")
        else:
            prior = YEARS[position - 1]
            fiscal_days = Decimal((datetime.strptime(period(year)[1], "%Y-%m-%d").date() -
                                   datetime.strptime(period(year)[0], "%Y-%m-%d").date()).days + 1)
            avg_ar = (ar + dec(values[(prior, "accounts_receivable")]["value"])) / 2
            avg_inventory = (inventory + dec(values[(prior, "inventory")]["value"])) / 2
            ratio(year, "days_sales_outstanding", avg_ar * fiscal_days, revenue, "days",
                  "average accounts receivable / revenue * actual fiscal days",
                  note="FY2024-FY2025 averages are acquisition-distorted.")
            ratio(year, "days_inventory_outstanding", avg_inventory * fiscal_days, cost, "days",
                  "average inventory / cost of sales excluding D&A * actual fiscal days",
                  note="Cost of sales, not revenue, is used; FY2024-FY2025 averages are acquisition-distorted.")
        add(year, "days_payables_outstanding", ap, None, None, "days",
            "not_determinable", "MISSING_PURCHASES_DENOMINATOR",
            "average accounts payable / purchases * actual fiscal days",
            "Purchases are not in the approved evidence; revenue or cost of sales is not substituted.")

    # Append the new metric family to preserve all pre-existing Phase 2 metric
    # IDs. These ratios are historical cash-paid diagnostics only.
    for year in YEARS:
        cash_paid_row = values[(year, "cash_interest_paid_disclosed")]
        cash_paid = dec(cash_paid_row["value"]) if cash_paid_row["value"] else None
        ratio(
            year,
            "historical_lender_ebitda_to_disclosed_cash_interest_paid",
            lender[year],
            cash_paid,
            "turns",
            "lender-normalized EBITDA / disclosed historical cash interest paid",
            True,
            "Historical cash-paid diagnostic only; not contractual interest paid or payable, closing-LTM coverage, or certified covenant compliance.",
            source_ids=cash_paid_row["source_ids"],
            input_ids=f"{lender_bridge_ids[year]};{cash_paid_row['spread_id']}",
        )
    return rows


def build_reconciliations(spread: list[dict[str, str]], bridges: list[dict[str, str]],
                          pro_forma: list[dict[str, str]],
                          supplemental: list[dict[str, str]]) -> list[dict[str, str]]:
    values = spread_index(spread)
    supp = index_unique(supplemental, ("fiscal_year", "metric_name"), "supplemental fact")
    rows: list[dict[str, str]] = []

    def add(year: str, category: str, description: str, left: Decimal | None,
            right: Decimal | None, status: str | None = None, severity: str = "material",
            resolution: str = "", notes: str = "", source_ids: str = "",
            input_ids: str = "", tolerance: Decimal = RECON_TOLERANCE) -> None:
        difference = None if left is None or right is None else left - right
        resolved_status = status or ("PASS" if abs(difference or Decimal(0)) <= tolerance else "FAIL")
        rows.append({
            "check_id": f"S2C-{len(rows) + 1:04d}", "fiscal_year": year,
            "category": category, "description": description,
            "left_value": fmt(left), "right_value": fmt(right),
            "difference": fmt(difference), "tolerance": fmt(tolerance),
            "status": resolved_status, "severity": severity,
            "source_ids": source_ids, "input_ids": input_ids,
            "resolution": resolution, "notes": notes,
        })

    cfo_components = (
        "cash_flow_net_income", "cash_flow_depreciation_and_amortization",
        "gain_loss_on_disposition_noncash", "stock_based_compensation",
        "deferred_income_taxes", "deferred_loan_costs_charge",
        "goodwill_impairment_noncash", "fx_forward_gain_noncash",
        "noncash_restructuring", "other_noncash_operating",
        "change_accounts_receivable", "change_inventory", "change_other_current_assets",
        "change_accounts_payable", "change_accrued_liabilities",
        "change_income_taxes_payable", "change_deferred_pension",
        "change_other_long_term_liabilities", "other_operating_changes",
    )
    financing_components = (
        "credit_facility_borrowings", "credit_facility_repayments",
        "debt_issuance_costs", "other_long_term_debt_repayments", "dividends_paid",
        "common_stock_issuance", "hedge_contract_proceeds", "payroll_tax_stock_vesting",
        "share_repurchases",
    )
    for year in YEARS:
        assets = dec(values[(year, "total_assets")]["value"])
        liabilities = dec(values[(year, "total_liabilities")]["value"])
        equity = dec(values[(year, "shareholders_equity")]["value"])
        add(year, "balance_sheet", "Assets = liabilities + equity", assets,
            liabilities + equity, source_ids=values[(year, "total_assets")]["source_ids"])
        cfo_sum = sum((dec(values[(year, metric)]["value"]) for metric in cfo_components
                       if values[(year, metric)]["value"]), Decimal(0))
        cfo = dec(values[(year, "cash_flow_from_operations")]["value"])
        add(year, "cash_flow", "Detailed CFO bridge = reported CFO", cfo_sum, cfo,
            source_ids=values[(year, "cash_flow_from_operations")]["source_ids"])
        fcf_constructed = cfo + dec(values[(year, "capital_expenditures")]["value"])
        fcf = dec(values[(year, "free_cash_flow")]["value"])
        add(year, "cash_flow", "CFO plus capex = free cash flow", fcf_constructed, fcf,
            source_ids=values[(year, "free_cash_flow")]["source_ids"],
            resolution="Cash interest remains inside CFO; it is not subtracted twice.")
        financing_sum = sum((dec(values[(year, metric)]["value"]) for metric in financing_components), Decimal(0))
        financing = dec(values[(year, "financing_cash_flow_total")]["value"])
        add(year, "cash_flow", "Financing activity detail = financing cash flow", financing_sum, financing,
            source_ids=values[(year, "financing_cash_flow_total")]["source_ids"])
        cash_movement = cfo + dec(values[(year, "investing_cash_flow_total")]["value"]) + financing + dec(values[(year, "fx_effect_on_cash")]["value"])
        reported_change = dec(values[(year, "net_change_cash_reported")]["value"])
        add(year, "cash_flow", "CFO + CFI + CFF + FX = reported cash change", cash_movement,
            reported_change, source_ids=values[(year, "net_change_cash_reported")]["source_ids"])
        begin = dec(values[(year, "cash_begin_total")]["value"])
        end = dec(values[(year, "cash_end_total")]["value"])
        add(year, "cash_flow", "Beginning cash plus reported change = ending cash", begin + reported_change,
            end, source_ids=values[(year, "cash_end_total")]["source_ids"])
        principal = dec(values[(year, "total_debt_principal")]["value"])
        fees = dec(values[(year, "unamortized_financing_fees")]["value"])
        carrying = dec(values[(year, "total_debt_carrying_amount")]["value"])
        add(year, "debt", "Gross funded principal less financing fees = carrying amount",
            principal - fees, carrying, source_ids=values[(year, "total_debt_principal")]["source_ids"])
        current_long = (dec(values[(year, "current_maturities_of_long_term_debt")]["value"]) +
                        dec(values[(year, "long_term_debt")]["value"]))
        add(year, "debt", "Current plus long-term debt = carrying amount", current_long,
            carrying, source_ids=values[(year, "long_term_debt")]["source_ids"])
        instruments = (dec(values[(year, "term_loan_principal")]["value"]) +
                       dec(values[(year, "revolver_borrowings")]["value"]) +
                       dec(values[(year, "finance_lease_obligations_principal")]["value"]))
        add(year, "debt", "Instrument principal = consolidated funded principal",
            instruments, principal, source_ids=values[(year, "total_debt_principal")]["source_ids"])
        income_dna = -dec(values[(year, "depreciation_and_amortization")]["value"])
        cash_dna = dec(values[(year, "cash_flow_depreciation_and_amortization")]["value"])
        add(year, "earnings", "Income-statement D&A = cash-flow D&A addback", income_dna,
            cash_dna, source_ids=values[(year, "depreciation_and_amortization")]["source_ids"])
        if year == "FY2025":
            impairment = -dec(values[(year, "goodwill_impairment_charges")]["value"])
            cf_impairment = dec(values[(year, "goodwill_impairment_noncash")]["value"])
            add(year, "earnings", "GAAP impairment = CFO noncash impairment addback",
                impairment, cf_impairment, source_ids="SRC-001;SRC-002",
                resolution="Reversed in EBITDA arithmetic but retained as a material business-risk signal.")
        acquisition = values[(year, "acquisition_cash_flows")]
        if acquisition["value"]:
            add(year, "cash_flow", "Acquisition cash flow retained from Phase 1", dec(acquisition["value"]),
                dec(acquisition["value"]), source_ids=acquisition["source_ids"], input_ids=acquisition["input_ids"])
        else:
            add(year, "cash_flow", "Acquisition cash flow explicitly missing, not zero", None, None,
                "EXPLICIT_MISSING", "informational", "No plug or zero assigned.", acquisition["notes"])

    debt_terms = read_csv(PHASE1_DEBT)
    maturity_total = sum((dec(row["numeric_value"]) for row in debt_terms
                          if row["term_name"].startswith("facility_principal_due_fy")), Decimal(0))
    facility_principal = (dec(values[("FY2025", "term_loan_principal")]["value"]) +
                          dec(values[("FY2025", "revolver_borrowings")]["value"]))
    add("FY2025", "debt", "Facility maturity disclosure = Term A plus revolver principal",
        maturity_total, facility_principal, source_ids="SRC-001;SRC-003",
        resolution="Maturity schedule excludes finance leases and other debt.")

    published_company = {"FY2024": Decimal("182.4"), "FY2025": Decimal("242.9")}
    company = final_bridge_values(bridges, "company_adjusted_ebitda")
    for year, published in published_company.items():
        add(year, "earnings", "Reconstructed company-adjusted EBITDA = published rounded amount",
            company[year], published, source_ids="SRC-002", tolerance=COMPANY_ROUNDED_TOLERANCE,
            resolution="Exact bridge is compared with the company's one-decimal presentation.")

    pf_index: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in pro_forma:
        key = (row["fiscal_year"], row["metric_name"], row["variant"])
        pf_index[key] = row
    for year in ("FY2022", "FY2023", "FY2024"):
        for metric in ("revenue", "net_income"):
            key = (year, metric, "2024-12-16_fy2024_10K_summary")
            pf = dec(pf_index[key]["normalized_value"])
            reported = dec(values[(year, metric)]["value"])
            add(year, "acquisition_comparability", f"Pro forma {metric} minus reported {metric}",
                pf, reported, "DISTINCT_LAYER", "informational",
                "Difference quantified, not reconciled away.",
                "Pro forma information is unaudited and never substituted for reported history.",
                source_ids=pf_index[key]["source_ids"] + ";" + values[(year, metric)]["source_ids"])
    add("ALL", "lineage", "All Phase 2 spread rows retain source and input IDs",
        Decimal(len(spread)), Decimal(sum(bool(r["source_ids"] or r["status"].startswith("not_")) for r in spread)),
        resolution="Calculated and missing-control rows retain upstream input IDs or an explicit missing status.")
    return rows


def manifest_map() -> dict[str, dict[str, str]]:
    rows = read_csv(PHASE1_MANIFEST)
    return {row["source_id"]: row for row in rows}


def build_ledger(outputs: list[tuple[str, str, list[dict[str, str]]]]) -> list[dict[str, str]]:
    manifest = manifest_map()
    rows: list[dict[str, str]] = []
    for output_file, layer, records in outputs:
        for record in records:
            record_id = (record.get("spread_id") or record.get("bridge_id") or
                         record.get("metric_id") or record.get("check_id") or
                         record.get("adjustment_id") or record.get("record_id"))
            source_value = record.get("source_ids") or record.get("source_id", "")
            ids = [item for item in source_value.split(";") if item]
            source_rows = [manifest[item] for item in ids if item in manifest]
            rows.append({
                "record_id": record_id, "output_file": output_file, "layer": layer,
                "fiscal_year": record.get("fiscal_year", ""),
                "metric_or_term": (record.get("metric_name") or record.get("line_item") or
                                   record.get("description", "")),
                "source_ids": ";".join(ids),
                "input_ids": record.get("input_ids", ""),
                "document_titles": "; ".join(r["document_title"] for r in source_rows),
                "source_urls": "; ".join(r["source_url"] for r in source_rows),
                "publication_or_filing_dates": "; ".join(r["publication_or_filing_date"] for r in source_rows),
                "classification": record.get("classification", layer),
                "human_review_status": record.get("human_review_status", "not_applicable"),
                "notes": record.get("notes", "") or record.get("rationale", "") or record.get("resolution", ""),
            })
    return rows


def render_docs(spread: list[dict[str, str]], bridges: list[dict[str, str]],
                decisions: list[dict[str, str]], metrics: list[dict[str, str]],
                reconciliations: list[dict[str, str]]) -> None:
    values = spread_index(spread)
    company = final_bridge_values(bridges, "company_adjusted_ebitda")
    contract = final_bridge_values(bridges, "contractual_ebitda_public_reconstruction")
    low = final_bridge_values(bridges, "provisional_lender_normalized_ebitda_low")
    base = final_bridge_values(bridges, "provisional_lender_normalized_ebitda_base")
    high = final_bridge_values(bridges, "provisional_lender_normalized_ebitda_high")

    methodology = """# Phase 2 methodology and control framework

**Information cutoff:** December 15, 2025

## Scope

Phase 2 consumes the committed Phase 1 foundation and produces a reconciled
FY2021-FY2025 consolidated spread, earnings bridges, reviewed adjustments,
credit metrics, and evidence-derived Phase 3 questions. It does not forecast,
size a refinancing, calculate closing liquidity, produce an official covenant
calculation, or begin Phase 3.

No new source ID was added. `SUPPLEMENTAL_FACTS.csv` transcribes balance-sheet
totals, detailed cash-flow lines, cash roll-forwards, financing flows,
FY2021-FY2023 debt principal, and the FY2023-FY2025 cash-paid-interest table
from SRC-001, SRC-012, and SRC-014 because those controls were not fields in
the Phase 1 extract. The approved archival URLs and publication dates remain in
the Phase 1 manifest and ledgers.

## Layers

1. Reported Phase 1 facts remain unchanged.
2. Phase 2 supplemental reported facts are source-faithful and separately identified.
3. Company-disclosed pro forma facts remain separate from reported history.
4. Mechanical calculations identify their input IDs and formulas.
5. Company-adjusted EBITDA is reconstructed only for FY2024-FY2025, where the approved bridge exists.
6. Contractual EBITDA is not treated as an official compliance figure. FY2025 has only a partial public-information reconstruction; other years remain not determinable.
7. The lender-normalized base reflects the project owner's reviewed judgments. Low is a lower sensitivity, and high preserves the company case; contractual eligibility and historical cash-flow treatment remain separate.

## Sign, precision, and materiality

Monetary values are USD millions. Expenses and cash outflows are negative.
Exact `Decimal` arithmetic is retained in CSVs; documentation generally shows
three decimal places. Statement reconciliations use a $0.001 million tolerance,
matching source precision. Comparison to company EBITDA rounded to one decimal
uses a $0.05 million tolerance. No unexplained plug is permitted.

Free cash flow is CFO plus normalized negative capital expenditures. Cash
interest is already inside US-GAAP CFO and is not subtracted again. SRC-001
separately reports cash paid for interest for FY2023-FY2025; the resulting
historical coverage diagnostic is not the contractual paid-or-payable measure
and does not establish closing-LTM coverage. Gross funded debt uses principal,
including finance leases/other debt; carrying debt is kept separate. Net debt
using book cash is an analyst comparable, not the contractual numerator because
eligible cash is not public.

Working-capital days use actual inclusive fiscal days (366 for FY2024; 365 for
the other displayed years), average balances when an opening year is available,
revenue for DSO, and cost of sales excluding D&A for DIO. DPO remains not
determinable because purchases are unavailable; neither revenue nor cost of
sales is substituted.

Negative or zero EBITDA produces `N/M` and a failure flag for leverage,
conversion, and coverage. Historical ratios are observations, not approval
tests.

## Reproduction

```powershell
python scripts/phase1.py validate
python scripts/phase2.py all
python -m unittest discover -s tests -v
powershell -ExecutionPolicy Bypass -NoProfile -File scripts/validate-phase0.ps1
```

The Phase 2 workflow uses only the Python standard library and performs no live
network access.
"""
    write_text(PHASE2_DOCS / "METHODOLOGY.md", methodology)

    lines = [
        "# Reconciled historical spread and credit analysis", "",
        "All amounts are USD millions except ratios. Reported growth after the Tyman acquisition is not organic growth.", "",
        "## Core historical spread", "",
        "| Metric | FY2021 | FY2022 | FY2023 | FY2024 | FY2025 |", "|---|---:|---:|---:|---:|---:|",
    ]
    table_metrics = (
        ("Revenue", "revenue"), ("Gross profit", "gross_profit"),
        ("Operating income", "operating_income"), ("Net income", "net_income"),
        ("Unadjusted EBITDA", "unadjusted_ebitda"),
        ("CFO", "cash_flow_from_operations"), ("Free cash flow", "free_cash_flow"),
        ("Cash paid for interest", "cash_interest_paid_disclosed"),
        ("Gross funded debt", "total_debt_principal"),
    )
    for label, metric in table_metrics:
        lines.append("| " + label + " | " + " | ".join(presentation(values[(year, metric)]["value"]) for year in YEARS) + " |")
    lines.extend(["", "## Earnings-definition separation", "",
                  "| Measure | FY2021 | FY2022 | FY2023 | FY2024 | FY2025 |",
                  "|---|---:|---:|---:|---:|---:|",
                  "| Unadjusted EBITDA | " + " | ".join(presentation(values[(y, "unadjusted_ebitda")]["value"]) for y in YEARS) + " |",
                  "| Company-adjusted EBITDA | " + " | ".join(presentation(company[y]) for y in YEARS) + " |",
                  "| Contractual public reconstruction | " + " | ".join(presentation(contract[y]) for y in YEARS) + " |",
                  "| Lender-normalized low sensitivity | " + " | ".join(presentation(low[y]) for y in YEARS) + " |",
                  "| Owner-reviewed lender-normalized base | " + " | ".join(presentation(base[y]) for y in YEARS) + " |",
                  "| Company/high adjusted EBITDA case | " + " | ".join(presentation(high[y]) for y in YEARS) + " |", "",
                  "Company-adjusted EBITDA is not relabeled for FY2021-FY2023 because the approved evidence lacks company bridges. The FY2025 contractual figure is only a partial public-information reconstruction, not a compliance calculation. The project owner reviewed the lender-normalization decisions; low remains a sensitivity and high preserves company treatment rather than lender acceptance.", "",
                  "## Owner-reviewed lender-normalization decisions", "",
                  "| ID | FY | Amount | Recommendation | Low | Base | High | Human review |",
                  "|---|---|---:|---|---:|---:|---:|---|"])
    for row in decisions:
        lines.append(f"| {row['adjustment_id']} | {row['fiscal_year']} | {presentation(row['reported_amount'])} | {row['lender_recommendation']} | {presentation(row['accepted_amount_low'])} | {presentation(row['accepted_amount_base'])} | {presentation(row['accepted_amount_high'])} | {row['human_review_status']} |")
    lines.extend([
        "", "The impairment reversal (AC-001), FY2024 transaction fees (AC-011), purchase-accounting items (AC-004/AC-010), the composite FY2025 category (AC-005), and the cash portion of restructuring (AC-006) are the decisions most capable of changing leverage or a later recommendation.", "",
        "## Revised lender-base credit metrics", "",
        "| Metric | FY2024 | FY2025 |", "|---|---:|---:|",
    ])
    metric_lookup = {(row["fiscal_year"], row["metric_name"]): row for row in metrics}
    for label, metric_name, suffix in (
        ("Lender-normalized EBITDA margin", "provisional_lender_normalized_ebitda_margin", "%"),
        ("CFO / lender-normalized EBITDA", "cfo_to_provisional_lender_normalized_ebitda", "%"),
        ("FCF / lender-normalized EBITDA", "fcf_to_provisional_lender_normalized_ebitda", "%"),
        ("Gross funded debt / lender-normalized EBITDA", "gross_funded_debt_to_provisional_lender_normalized_ebitda", "x"),
        ("Net debt after book cash / lender-normalized EBITDA", "net_debt_book_cash_to_provisional_lender_ebitda", "x"),
        ("Lender-normalized EBITDA / GAAP interest expense", "provisional_lender_ebitda_to_interest_expense_proxy", "x"),
        ("Lender-normalized EBITDA / disclosed historical cash interest paid", "historical_lender_ebitda_to_disclosed_cash_interest_paid", "x"),
    ):
        displayed = []
        for year in ("FY2024", "FY2025"):
            value = metric_lookup[(year, metric_name)]["value"]
            displayed.append(f"{dec(value):.3f}{suffix}" if value else "N/D")
        lines.append(f"| {label} | {displayed[0]} | {displayed[1]} |")
    lines.extend([
        "", "Net debt after book cash is an analyst diagnostic, not covenant or lender net leverage. GAAP interest expense remains a separate proxy. Disclosed FY2023-FY2025 cash paid for interest supports a historical diagnostic only; it is not contractual paid-or-payable interest, closing-LTM coverage, or certified compliance.", "",
        "## Reconciliation conclusion", "",
        f"All {sum(r['status'] == 'PASS' for r in reconciliations)} exact or rounded-tolerance controls pass. Pro forma/reporting comparisons remain intentionally distinct and FY2021-FY2022 acquisition cash flow remains explicitly missing rather than zero. No material statement difference is plugged.", "",
        "## Historical cash-generation observations", "",
        "- CFO was $78.588m, $97.965m, $147.052m, $88.812m, and $164.897m from FY2021 through FY2025; FCF was $54.580m, $64.844m, $109.662m, $51.726m, and $102.255m.",
        "- FY2024 cash conversion weakened while the company paid $398.554m for acquisitions and raised net facility debt. FY2025 CFO recovered and bank debt declined by $75.0m gross, but the post-Tyman perimeter prevents a clean organic trend inference.",
        "- Working capital was volatile: inventory was a $32.035m use in FY2022, then a $30.024m, $33.484m, and $23.553m source in FY2023-FY2025; accounts payable was a use in FY2022-FY2024 before a $3.313m source in FY2025.",
        "- Capex rose from $24.008m in FY2021 to $62.642m in FY2025. Phase 2 does not classify maintenance versus expansion capex.",
        "- Dividends were paid every year and repurchases continued in four of five years, including $32.360m in FY2025 despite elevated acquisition debt.",
        "- The FY2025 $302.284m noncash impairment explains the gap between GAAP loss and positive CFO, but it is an acquisition/asset-quality warning rather than evidence of cash earnings.",
        "- Company-adjusted EBITDA converted to CFO at about 48.7% in FY2024 and 67.9% in FY2025; the large adjustment bridges therefore did not translate dollar-for-dollar into cash.",
        "", "## Underwriting judgment", "",
        "The evidence foundation is suitable for Phase 3 only conditionally. The project owner reviewed the lender-normalization judgments, but contractual eligibility, adjustment cash timing, AC-005 disaggregation, and other identified diligence limitations remain unresolved. The cash-flow control material weakness remained unremediated at October 31, 2025; no known misstatement is inferred, but later forecasting should retain heightened cash-flow reconciliation controls.",
    ])
    write_text(PHASE2_DOCS / "CREDIT_ANALYSIS.md", "\n".join(lines))

    handoff = """# Phase 3 evidence-driven handoff questions

These are bounded research questions arising from Phase 2 observations. They do
not establish forecast assumptions or begin Phase 3 research. Owner review of
the lender-normalization base does not resolve contractual eligibility or cash
timing and realization diligence.

| ID | Phase 2 observation | Phase 3 question |
|---|---|---|
| H-001 | FY2025 reported revenue rose 43.8% because of Tyman, while management cited lower volume and weak end markets. | What volume, price, mix, and market indicators explain underlying demand by the current business perimeter without calling acquisition growth organic? |
| H-002 | Reported gross margin improved to 27.2% in FY2025, but purchase accounting, relocation costs, synergies, and a Mexico plant issue affect comparability. | Which margin gains are recurring, and what evidence exists on plant stabilization, fixed-cost absorption, and realized versus remaining cost savings? |
| H-003 | Inventory supplied cash in FY2023-FY2025 after consuming $32.0m in FY2022; acquisition timing distorts average-balance metrics. | What seasonal and operational drivers explain inventory normalization, and what working-capital use could recur under stable or falling demand? |
| H-004 | FY2025 capex reached $62.6m, materially above FY2021-FY2024. | How much historical and expected capex is maintenance, integration, remediation, or expansion, and what level is necessary to sustain operations? |
| H-005 | The $10.263m FY2025 composite category mixes transaction, advisory, reorganization, and product-recall costs. | What are the components, cash timing, recurrence risk, and operational cause of the recall and reorganization charges? |
| H-006 | Only $4.561m of the $10.191m FY2025 restructuring candidate is identified as noncash. | What cash payments remain, when will programs end, and are further restructuring or software charges expected? |
| H-007 | FY2025 included a $302.284m goodwill impairment and a $9m deferred-tax correction after the Tyman purchase-price allocation. | What operating shortfalls, valuation assumptions, integration issues, and control processes caused these acquisition-accounting outcomes? |
| H-008 | The cash-flow preparation/review material weakness remained outstanding at October 31, 2025. | What remediation has been completed using only cutoff-eligible evidence, what testing remains, and how should confidence in cash-flow forecasts be calibrated? |
| H-009 | Gross funded debt rose from $70.0m in FY2023 to $776.9m in FY2024, then fell to $703.9m in FY2025 while repurchases resumed. | What governs debt reduction versus dividends and repurchases, and how durable is deleveraging priority? |
| H-010 | Company-adjusted EBITDA converted to CFO at roughly 49% in FY2024 and 68% in FY2025. | Which adjustments were cash, what working-capital effects obscured conversion, and what cash realization should later downside cases permit? |
"""
    write_text(PHASE2_DOCS / "PHASE3_HANDOFF.md", handoff)


def build() -> dict[str, int]:
    phase1 = read_csv(PHASE1_FACTS)
    pro_forma = read_csv(PHASE1_PRO_FORMA)
    candidates = read_csv(PHASE1_ADJUSTMENTS)
    supplemental = supplemental_seed_rows()
    decisions = adjustment_decision_rows(candidates)
    spread = build_spread(phase1, supplemental)
    bridges = build_bridges(spread, decisions, supplemental)
    metrics = build_metrics(spread, bridges)
    reconciliations = build_reconciliations(spread, bridges, pro_forma, supplemental)
    write_csv(PHASE2_RAW / "SUPPLEMENTAL_FACTS.csv", supplemental, SUPPLEMENTAL_FIELDS)
    write_csv(PHASE2_RAW / "PROPOSED_ADJUSTMENT_DECISIONS.csv", decisions, ADJUSTMENT_DECISION_FIELDS)
    write_csv(PHASE2_PROCESSED / "historical_spread.csv", spread, SPREAD_FIELDS)
    write_csv(PHASE2_PROCESSED / "earnings_bridges.csv", bridges, BRIDGE_FIELDS)
    write_csv(PHASE2_PROCESSED / "adjustment_decisions.csv", decisions, ADJUSTMENT_DECISION_FIELDS)
    write_csv(PHASE2_PROCESSED / "historical_credit_metrics.csv", metrics, METRIC_FIELDS)
    write_csv(PHASE2_PROCESSED / "reconciliation_results.csv", reconciliations, RECON_FIELDS)
    ledger = build_ledger([
        ("data/phase2/raw/SUPPLEMENTAL_FACTS.csv", "reported_supplemental", supplemental),
        ("data/phase2/processed/historical_spread.csv", "historical_spread", spread),
        ("data/phase2/processed/earnings_bridges.csv", "earnings_bridge", bridges),
        ("data/phase2/processed/adjustment_decisions.csv", "analyst_judgment", decisions),
        ("data/phase2/processed/historical_credit_metrics.csv", "credit_metric", metrics),
        ("data/phase2/processed/reconciliation_results.csv", "reconciliation", reconciliations),
    ])
    write_csv(PHASE2_DOCS / "SOURCE_LEDGER.csv", ledger, LEDGER_FIELDS)
    render_docs(spread, bridges, decisions, metrics, reconciliations)
    stats = {
        "supplemental_facts": len(supplemental), "spread_rows": len(spread),
        "bridge_rows": len(bridges), "adjustment_decisions": len(decisions),
        "metric_rows": len(metrics), "reconciliation_rows": len(reconciliations),
        "ledger_rows": len(ledger),
    }
    print("Phase 2 build: PASS")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    return stats


def validate() -> dict[str, int]:
    manifest = read_csv(PHASE1_MANIFEST)
    source_ids = {row["source_id"] for row in manifest}
    if source_ids != VALID_SOURCES:
        raise Phase2Error("Approved Phase 1 source universe changed")
    for row in manifest:
        filing_date = datetime.strptime(row["publication_or_filing_date"], "%Y-%m-%d").date()
        if filing_date > CUTOFF or row["cutoff_status"] != "ALLOWED":
            raise Phase2Error(f"Post-cutoff or disallowed source: {row['source_id']}")
    supplemental = read_csv(PHASE2_RAW / "SUPPLEMENTAL_FACTS.csv")
    decisions = read_csv(PHASE2_PROCESSED / "adjustment_decisions.csv")
    raw_decisions = read_csv(PHASE2_RAW / "PROPOSED_ADJUSTMENT_DECISIONS.csv")
    spread = read_csv(PHASE2_PROCESSED / "historical_spread.csv")
    bridges = read_csv(PHASE2_PROCESSED / "earnings_bridges.csv")
    metrics = read_csv(PHASE2_PROCESSED / "historical_credit_metrics.csv")
    reconciliations = read_csv(PHASE2_PROCESSED / "reconciliation_results.csv")
    ledger = read_csv(PHASE2_DOCS / "SOURCE_LEDGER.csv")
    if supplemental != supplemental_seed_rows():
        raise Phase2Error("Supplemental source extract is not deterministic")
    expected_decisions = adjustment_decision_rows(read_csv(PHASE1_ADJUSTMENTS))
    if decisions != raw_decisions or decisions != expected_decisions:
        raise Phase2Error("Adjustment decisions diverge from controlled proposal")
    expected_spread = build_spread(read_csv(PHASE1_FACTS), supplemental)
    expected_bridges = build_bridges(expected_spread, decisions, supplemental)
    expected_metrics = build_metrics(expected_spread, expected_bridges)
    expected_recons = build_reconciliations(expected_spread, expected_bridges,
                                             read_csv(PHASE1_PRO_FORMA), supplemental)
    if spread != expected_spread or bridges != expected_bridges or metrics != expected_metrics or reconciliations != expected_recons:
        raise Phase2Error("Processed output diverges from deterministic regeneration")
    if {row["fiscal_year"] for row in spread} != set(YEARS):
        raise Phase2Error("Historical spread does not cover FY2021-FY2025")
    required = {
        "revenue", "gross_profit", "operating_income", "net_income",
        "cash_flow_from_operations", "capital_expenditures", "free_cash_flow",
        "current_assets", "current_liabilities", "total_assets",
        "total_liabilities", "shareholders_equity", "total_debt_principal",
        "total_debt_carrying_amount", "acquisition_cash_flows",
    }
    spread_metrics: dict[str, set[str]] = defaultdict(set)
    for row in spread:
        spread_metrics[row["fiscal_year"]].add(row["metric_name"])
        if row["units"] != MONEY_UNIT:
            raise Phase2Error(f"Unexpected spread unit: {row['spread_id']}")
        expected_start, expected_end = period(row["fiscal_year"])
        if row["period_end"] != expected_end:
            raise Phase2Error(f"Invalid period end: {row['spread_id']}")
        if row["period_type"] == "instant" and row["period_start"]:
            raise Phase2Error(f"Instant row has a start date: {row['spread_id']}")
        if row["period_type"] == "duration" and row["period_start"] != expected_start:
            raise Phase2Error(f"Invalid duration start: {row['spread_id']}")
        if row["period_type"] not in {"instant", "duration"}:
            raise Phase2Error(f"Invalid period type: {row['spread_id']}")
        if not row["value"] and not row["status"].startswith("not_"):
            raise Phase2Error(f"Missing value lacks explicit status: {row['spread_id']}")
        for source_id in row["source_ids"].split(";"):
            if source_id and source_id not in VALID_SOURCES:
                raise Phase2Error(f"Invalid source ID: {row['spread_id']} {source_id}")
    for year in YEARS:
        missing = required - spread_metrics[year]
        if missing:
            raise Phase2Error(f"Missing required spread fields for {year}: {sorted(missing)}")
    ids = [row["adjustment_id"] for row in decisions]
    if len(ids) != 11 or len(ids) != len(set(ids)):
        raise Phase2Error("Adjustment decisions are incomplete or duplicated")
    for row in decisions:
        if row["human_review_status"] != "owner_reviewed":
            raise Phase2Error(f"Missing owner review status: {row['adjustment_id']}")
        supported = dec(row["reported_amount"])
        low, base, high = (dec(row[field]) for field in
                           ("accepted_amount_low", "accepted_amount_base", "accepted_amount_high"))
        if supported >= 0 and (min(low, base, high) < 0 or max(low, base, high) > supported):
            raise Phase2Error(f"Accepted amount exceeds support: {row['adjustment_id']}")
        if supported < 0 and not (low == base == high == supported):
            raise Phase2Error(f"Gain deduction treatment is inconsistent: {row['adjustment_id']}")
    prescribed = {
        "AC-002": ("pending_information", Decimal("0"), Decimal("1.432")),
        "AC-003": ("pending_information", Decimal("0"), Decimal("0.221")),
        "AC-008": ("pending_information", Decimal("0"), Decimal("3.025")),
    }
    for adjustment_id, (recommendation, base_amount, high_amount) in prescribed.items():
        row = next(item for item in decisions if item["adjustment_id"] == adjustment_id)
        if (row["lender_recommendation"] != recommendation or
                dec(row["accepted_amount_base"]) != base_amount or
                dec(row["accepted_amount_high"]) != high_amount):
            raise Phase2Error(f"Owner-reviewed treatment changed: {adjustment_id}")
    failures = [row for row in reconciliations if row["status"] == "FAIL"]
    if failures:
        raise Phase2Error("Material reconciliation failure: " + ", ".join(r["check_id"] for r in failures))
    if any(row["metric_name"] == "days_payables_outstanding" and
           row["failure_flag"] != "MISSING_PURCHASES_DENOMINATOR" for row in metrics):
        raise Phase2Error("DPO used an unsupported denominator")
    fy25_negative = next(row for row in metrics if row["fiscal_year"] == "FY2025" and
                         row["metric_name"] == "gross_funded_debt_to_unadjusted_ebitda")
    if fy25_negative["display_value"] != "N/M" or fy25_negative["failure_flag"] != "NONPOSITIVE_EBITDA":
        raise Phase2Error("Negative EBITDA handling failed")
    if len(ledger) == 0 or any(row["source_ids"] and not row["document_titles"] for row in ledger):
        raise Phase2Error("Phase 2 source ledger is incomplete")
    stats = {
        "years": len(YEARS), "adjustments": len(decisions),
        "reconciliation_passes": sum(r["status"] == "PASS" for r in reconciliations),
        "explicit_missing": sum(r["status"] in {"EXPLICIT_MISSING", "not_determinable"} for r in reconciliations),
        "post_cutoff_sources": 0,
        "owner_reviewed_adjustments": sum(r["human_review_status"] == "owner_reviewed" for r in decisions),
    }
    print("Phase 2 validation: PASS")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    return stats


def fingerprints() -> dict[str, str]:
    paths = sorted(list(PHASE2_RAW.glob("*.csv")) + list(PHASE2_PROCESSED.glob("*.csv")) +
                   list(PHASE2_DOCS.glob("*")))
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths if path.is_file()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "validate", "all"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command in {"build", "all"}:
            build()
        if args.command in {"validate", "all"}:
            validate()
    except (Phase2Error, KeyError, OSError, ValueError) as exc:
        print(f"Phase 2 error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
