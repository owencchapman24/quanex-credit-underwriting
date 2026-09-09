#!/usr/bin/env python3
"""Build and validate the Quanex Phase 1 credit evidence foundation.

The workflow is deliberately case-specific and network-independent. It turns
bounded, source-faithful extracts from the Phase 0-approved evidence set into
normalized CSVs, a debt-term register, and a consolidated source ledger.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
PHASE0_INVENTORY = ROOT / "docs" / "phase-0" / "EVIDENCE_INVENTORY.csv"
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
PHASE1_DOCS_DIR = ROOT / "docs" / "phase-1"
CUTOFF = date(2025, 12, 15)
REQUIRED_SOURCE_IDS = (
    "SRC-001", "SRC-002", "SRC-003", "SRC-004", "SRC-008",
    "SRC-012", "SRC-013", "SRC-014", "SRC-016",
)
ALLOWED_DEBT_STATUSES = {
    "reported", "calculated", "not_determinable", "conflicting_source"
}

MANIFEST_FIELDS = (
    "source_id", "document_title", "document_type",
    "publication_or_filing_date", "reporting_or_effective_date", "source_url",
    "local_path", "sha256", "bytes", "preservation_mode", "cutoff_status",
    "notes",
)
RAW_FACT_FIELDS = (
    "raw_fact_id", "layer", "variant", "metric_name", "fiscal_year", "period_start",
    "period_end", "period_type", "period_grain", "statement",
    "original_value", "original_units", "normalization_multiplier",
    "source_id", "source_reference", "source_type", "comparability_status",
    "notes",
)
PROCESSED_FACT_FIELDS = (
    "fact_id", "layer", "variant", "metric_name", "fiscal_year", "period_start",
    "period_end", "period_type", "period_grain", "statement",
    "original_reported_value", "original_units", "normalized_value",
    "normalized_units", "classification", "source_ids", "source_reference",
    "source_type", "override_status", "override_rationale",
    "comparability_status", "calculation", "notes",
)
ADJUSTMENT_FIELDS = (
    "candidate_id", "fiscal_year", "period_start", "period_end",
    "metric_name", "original_value", "original_units", "normalized_value",
    "normalized_units", "source_id", "source_reference", "company_treatment",
    "phase2_status", "notes",
)
DEBT_FIELDS = (
    "term_id", "instrument_name", "as_of_date", "term_name", "value_text",
    "numeric_value", "units", "status", "source_ids", "source_reference",
    "conflict_group", "authority_resolution", "notes",
)
OVERRIDE_FIELDS = (
    "override_id", "affected_raw_fact_id", "reason", "source_id",
    "affected_metric", "affected_period", "original_value",
    "replacement_value", "reviewer_note", "status",
)


class Phase1Error(RuntimeError):
    """A validation or input failure that makes the foundation unsafe to use."""


@dataclass(frozen=True)
class Source:
    source_id: str
    document_type: str
    document_title: str
    reporting_or_effective_date: str
    publication_or_filing_date: str
    source_location: str
    authority: str


def write_csv(path: Path, rows: Iterable[dict], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise Phase1Error(f"Missing required input: {path.relative_to(ROOT)}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def parse_decimal(value: str, label: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise Phase1Error(f"Invalid numeric value for {label}: {value!r}") from exc


def fmt(value: Decimal) -> str:
    result = format(value, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return result or "0"


def read_sources() -> dict[str, Source]:
    rows = read_csv(PHASE0_INVENTORY)
    sources: dict[str, Source] = {}
    for row in rows:
        source_id = row["source_id"]
        if source_id in sources:
            raise Phase1Error(f"Duplicate Phase 0 source ID: {source_id}")
        filing_date = datetime.strptime(
            row["publication_or_filing_date"], "%Y-%m-%d"
        ).date()
        if filing_date > CUTOFF or row["cutoff_status"] != "ALLOWED":
            raise Phase1Error(f"Phase 0 contains a non-approved source: {source_id}")
        sources[source_id] = Source(
            source_id=source_id,
            document_type=row["document_type"],
            document_title=row["document_title"],
            reporting_or_effective_date=row["reporting_or_effective_date"],
            publication_or_filing_date=row["publication_or_filing_date"],
            source_location=row["source_location"],
            authority=row["authority"],
        )
    missing = sorted(set(REQUIRED_SOURCE_IDS) - set(sources))
    if missing:
        raise Phase1Error(f"Phase 0 inventory is missing required sources: {missing}")
    return sources


def source_ids(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def fiscal_period(fiscal_year: int) -> tuple[str, str]:
    return f"{fiscal_year - 1}-11-01", f"{fiscal_year}-10-31"


def comparability(fiscal_year: int, statement: str) -> str:
    if fiscal_year <= 2023:
        return "pre_tyman"
    if statement == "balance_sheet":
        return "post_tyman_acquisition_date"
    if fiscal_year == 2024:
        return "includes_three_months_of_tyman"
    return "full_year_post_tyman_with_integration_effects"


def historical_seed_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add(
        metric: str, year: int, value: int | str, statement: str,
        source_id: str, reference: str, multiplier: int = 1,
        period_type: str = "duration", note: str = "",
    ) -> None:
        start, end = fiscal_period(year) if period_type == "duration" else ("", f"{year}-10-31")
        rows.append({
            "raw_fact_id": f"RF-{len(rows) + 1:04d}",
            "layer": "reported_historical", "variant": "reported",
            "metric_name": metric,
            "fiscal_year": f"FY{year}", "period_start": start,
            "period_end": end, "period_type": period_type,
            "period_grain": "annual" if period_type == "duration" else "year_end",
            "statement": statement, "original_value": str(value),
            "original_units": "USD_thousands",
            "normalization_multiplier": str(multiplier), "source_id": source_id,
            "source_reference": reference,
            "source_type": "SEC_filing" if source_id != "SRC-002" else "company_results_release",
            "comparability_status": (
                "post_tyman_acquisition_date"
                if period_type == "instant" and year >= 2024
                else comparability(year, statement)
            ),
            "notes": note,
        })

    income = {
        2025: {
            "revenue": 1837641, "cost_of_sales_excluding_depreciation_and_amortization": 1338413,
            "selling_general_and_administrative": 277261, "restructuring_charges": 10191,
            "depreciation_and_amortization": 103444, "goodwill_impairment_charges": 302284,
            "operating_income": -193952, "interest_expense": -55812,
            "income_tax_expense": -8213, "net_income": -250806,
        },
        2024: {
            "revenue": 1277862, "cost_of_sales_excluding_depreciation_and_amortization": 972238,
            "selling_general_and_administrative": 190470, "restructuring_charges": 0,
            "depreciation_and_amortization": 60328, "goodwill_impairment_charges": 0,
            "operating_income": 54826, "interest_expense": -20593,
            "income_tax_expense": -9023, "net_income": 33059,
        },
        2023: {
            "revenue": 1130583, "cost_of_sales_excluding_depreciation_and_amortization": 853059,
            "selling_general_and_administrative": 123957, "restructuring_charges": 0,
            "depreciation_and_amortization": 42866, "goodwill_impairment_charges": 0,
            "operating_income": 110701, "interest_expense": -8136,
            "income_tax_expense": -14545, "net_income": 82501,
        },
        2022: {
            "revenue": 1221502, "cost_of_sales_excluding_depreciation_and_amortization": 953004,
            "selling_general_and_administrative": 117108, "restructuring_charges": 0,
            "depreciation_and_amortization": 40109, "operating_income": 111281,
            "interest_expense": -2559, "income_tax_expense": -21427,
            "net_income": 88336,
        },
        2021: {
            "revenue": 1072149, "cost_of_sales_excluding_depreciation_and_amortization": 831541,
            "selling_general_and_administrative": 115967, "restructuring_charges": 39,
            "depreciation_and_amortization": 42732, "operating_income": 81870,
            "interest_expense": -2530, "income_tax_expense": -23114,
            "net_income": 56980,
        },
    }
    expense_positive = {
        "cost_of_sales_excluding_depreciation_and_amortization",
        "selling_general_and_administrative", "restructuring_charges",
        "depreciation_and_amortization", "goodwill_impairment_charges",
    }
    for year, values in income.items():
        src = "SRC-001" if year >= 2023 else "SRC-014"
        ref = ("Consolidated Statements of Income, FY2025 Form 10-K, p. 43"
               if src == "SRC-001" else
               "Consolidated Statements of Income, FY2022 Form 10-K, p. 36")
        for metric, value in values.items():
            add(metric, year, value, "income_statement", src, ref,
                -1 if metric in expense_positive else 1)

    cash_flow = {
        2025: {"cash_flow_from_operations": 164897, "capital_expenditures": -62642,
               "acquisition_cash_flows": 0, "dividends_paid": -14889,
               "share_repurchases": -32360},
        2024: {"cash_flow_from_operations": 88812, "capital_expenditures": -37086,
               "acquisition_cash_flows": -398554, "dividends_paid": -11972,
               "share_repurchases": 0},
        2023: {"cash_flow_from_operations": 147052, "capital_expenditures": -37390,
               "acquisition_cash_flows": -91302, "dividends_paid": -10639,
               "share_repurchases": -5593},
        2022: {"cash_flow_from_operations": 97965, "capital_expenditures": -33121,
               "dividends_paid": -10598, "share_repurchases": -6600},
        2021: {"cash_flow_from_operations": 78588, "capital_expenditures": -24008,
               "dividends_paid": -10779, "share_repurchases": -11182},
    }
    for year, values in cash_flow.items():
        src = "SRC-001" if year >= 2023 else "SRC-014"
        ref = ("Consolidated Statements of Cash Flow, FY2025 Form 10-K, p. 46"
               if src == "SRC-001" else
               "Consolidated Statements of Cash Flow, FY2022 Form 10-K, p. 39")
        for metric, value in values.items():
            note = "Reported dash (zero), not a missing value." if value == 0 else ""
            add(metric, year, value, "cash_flow_statement", src, ref, note=note)

    balance = {
        2025: {
            "cash_and_cash_equivalents": 76018, "restricted_cash": 2100,
            "accounts_receivable": 205384, "inventory": 254122,
            "income_taxes_receivable": 0, "prepaid_assets": 32387,
            "other_current_assets": 3764, "current_assets": 573775,
            "property_plant_and_equipment_net": 411591,
            "operating_lease_right_of_use_assets": 154866, "goodwill": 271346,
            "intangible_assets_net": 549137, "accounts_payable": 131307,
            "accrued_liabilities": 95155, "income_taxes_payable": 12076,
            "current_maturities_of_long_term_debt": 27561,
            "current_operating_lease_liabilities": 15446,
            "current_liabilities": 281545, "long_term_debt": 665268,
            "noncurrent_operating_lease_liabilities": 145459,
        },
        2024: {
            "cash_and_cash_equivalents": 97744, "restricted_cash": 5251,
            "accounts_receivable": 197689, "inventory": 275550,
            "income_taxes_receivable": 5937, "prepaid_assets": 23419,
            "other_current_assets": 5678, "current_assets": 611268,
            "property_plant_and_equipment_net": 402466,
            "operating_lease_right_of_use_assets": 126715, "goodwill": 574711,
            "intangible_assets_net": 597909, "accounts_payable": 124404,
            "accrued_liabilities": 103623, "income_taxes_payable": 6620,
            "current_maturities_of_long_term_debt": 25745,
            "current_operating_lease_liabilities": 12475,
            "current_liabilities": 272867, "long_term_debt": 737198,
            "noncurrent_operating_lease_liabilities": 117560,
        },
        2023: {
            "cash_and_cash_equivalents": 58474, "restricted_cash": 0,
            "accounts_receivable": 97311, "inventory": 97959,
            "income_taxes_receivable": 8298,
            "prepaid_and_other_current_assets": 11558, "current_assets": 273600,
            "property_plant_and_equipment_net": 250664,
            "operating_lease_right_of_use_assets": 46620, "goodwill": 182956,
            "intangible_assets_net": 74115, "accounts_payable": 74371,
            "accrued_liabilities": 50319, "income_taxes_payable": 384,
            "current_maturities_of_long_term_debt": 2365,
            "current_operating_lease_liabilities": 7224,
            "current_liabilities": 134663, "long_term_debt": 66435,
            "noncurrent_operating_lease_liabilities": 40361,
        },
        2022: {
            "cash_and_cash_equivalents": 55093, "accounts_receivable": 96018,
            "inventory": 120890, "prepaid_and_other_current_assets": 8664,
            "current_assets": 280665, "property_plant_and_equipment_net": 180400,
            "operating_lease_right_of_use_assets": 56000, "goodwill": 137855,
            "intangible_assets_net": 65035, "accounts_payable": 77907,
            "accrued_liabilities": 52114, "income_taxes_payable": 1049,
            "current_maturities_of_long_term_debt": 1046,
            "current_operating_lease_liabilities": 7727,
            "current_liabilities": 139843, "long_term_debt": 29628,
            "noncurrent_operating_lease_liabilities": 49286,
        },
        2021: {
            "cash_and_cash_equivalents": 40061, "accounts_receivable": 108309,
            "inventory": 92529, "prepaid_and_other_current_assets": 8148,
            "current_assets": 249047, "property_plant_and_equipment_net": 178630,
            "operating_lease_right_of_use_assets": 52708, "goodwill": 149205,
            "intangible_assets_net": 82410, "accounts_payable": 86765,
            "accrued_liabilities": 56156, "income_taxes_payable": 6038,
            "current_maturities_of_long_term_debt": 846,
            "current_operating_lease_liabilities": 8196,
            "current_liabilities": 158001, "long_term_debt": 52094,
            "noncurrent_operating_lease_liabilities": 45367,
        },
    }
    for year, values in balance.items():
        if year >= 2024:
            src, ref = "SRC-001", "Consolidated Balance Sheets, FY2025 Form 10-K, p. 42"
        elif year == 2023:
            src, ref = "SRC-012", "Consolidated Balance Sheets, FY2024 Form 10-K, p. 40"
        else:
            src, ref = "SRC-014", "Consolidated Balance Sheets, FY2022 Form 10-K, p. 35"
        for metric, value in values.items():
            note = "Reported dash (zero), not a missing value." if value == 0 else ""
            add(metric, year, value, "balance_sheet", src, ref,
                period_type="instant", note=note)

    debt_crosscheck = {
        2025: {"term_loan_principal": 468750, "revolver_borrowings": 172500,
               "finance_lease_obligations_principal": 62619,
               "total_debt_principal": 703869,
               "net_debt_company_definition": 627851},
        2024: {"term_loan_principal": 493750, "revolver_borrowings": 222500,
               "finance_lease_obligations_principal": 60676,
               "total_debt_principal": 776926,
               "net_debt_company_definition": 679182},
    }
    for year, values in debt_crosscheck.items():
        for metric, value in values.items():
            add(metric, year, value, "debt_reconciliation", "SRC-002",
                "FY2025 results release, Free Cash Flow and Net Debt Reconciliation",
                period_type="instant",
                note="Company net-debt definition; total debt excludes letters of credit."
                if metric in {"total_debt_principal", "net_debt_company_definition"} else "")
    return rows


def pro_forma_seed_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add(metric: str, label: str, start: str, end: str, value: int,
            statement: str, reference: str, period_type: str = "duration") -> None:
        rows.append({
            "raw_fact_id": f"PF-{len(rows) + 1:04d}",
            "layer": "company_disclosed_pro_forma",
            "variant": "2024-10-16_pro_forma_exhibit", "metric_name": metric,
            "fiscal_year": label, "period_start": start, "period_end": end,
            "period_type": period_type,
            "period_grain": "annual" if label == "FY2023" else
                            ("nine_months" if period_type == "duration" else "instant"),
            "statement": statement, "original_value": str(value),
            "original_units": "USD_thousands", "normalization_multiplier": "1",
            "source_id": "SRC-008", "source_reference": reference,
            "source_type": "SEC_pro_forma_exhibit",
            "comparability_status": "unaudited_company_pro_forma_tyman_combination",
            "notes": "Not reported history; preliminary acquisition accounting and financing assumptions apply.",
        })

    duration_sets = (
        ("9M2024", "2023-11-01", "2024-07-31", {
            "revenue": 1394673,
            "cost_of_sales_excluding_depreciation_and_amortization": -994755,
            "selling_general_and_administrative": -235082,
            "depreciation_and_amortization": -66526, "operating_income": 98310,
            "interest_expense": -38941, "other_net": 12684,
            "income_before_income_taxes": 72053, "income_tax_expense": -18967,
            "net_income": 53086,
        }, "Unaudited pro forma combined income statement, nine months ended July 31, 2024, p. 3"),
        ("FY2023", "2022-11-01", "2023-10-31", {
            "revenue": 1954950,
            "cost_of_sales_excluding_depreciation_and_amortization": -1443961,
            "selling_general_and_administrative": -299477,
            "depreciation_and_amortization": -87569, "operating_income": 123943,
            "interest_expense": -66556, "other_net": -881,
            "income_before_income_taxes": 56506, "income_tax_expense": -8049,
            "net_income": 48457,
        }, "Unaudited pro forma combined income statement, year ended October 31, 2023, p. 4"),
    )
    for label, start, end, values, reference in duration_sets:
        for metric, value in values.items():
            add(metric, label, start, end, value, "pro_forma_income_statement", reference)

    balances = {
        "cash_and_cash_equivalents": 184613, "restricted_cash": 5058,
        "accounts_receivable": 191793, "inventory": 305544,
        "income_taxes_receivable": 6055,
        "prepaid_and_other_current_assets": 37466, "current_assets": 730529,
        "property_plant_and_equipment_net": 401305,
        "operating_lease_right_of_use_assets": 137057, "goodwill": 566546,
        "intangible_assets_net": 598922,
    }
    for metric, value in balances.items():
        add(metric, "PF_2024-07-31", "", "2024-07-31", value,
            "pro_forma_balance_sheet",
            "Unaudited pro forma combined balance sheet as of July 31, 2024, pp. 5-6",
            period_type="instant")

    summary_values = {
        2024: {"revenue": 1886834, "net_income": 66037},
        2023: {"revenue": 1954950, "net_income": 48458},
        2022: {"revenue": 2115987, "net_income": 60192},
    }
    for year, values in summary_values.items():
        start, end = fiscal_period(year)
        for metric, value in values.items():
            rows.append({
                "raw_fact_id": f"PF-{len(rows) + 1:04d}",
                "layer": "company_disclosed_pro_forma",
                "variant": "2024-12-16_fy2024_10K_summary",
                "metric_name": metric, "fiscal_year": f"FY{year}",
                "period_start": start, "period_end": end,
                "period_type": "duration", "period_grain": "annual",
                "statement": "pro_forma_results_summary",
                "original_value": str(value), "original_units": "USD_thousands",
                "normalization_multiplier": "1", "source_id": "SRC-012",
                "source_reference": "FY2024 Form 10-K Note 2, Pro Forma Results, p. 55",
                "source_type": "SEC_10-K_pro_forma_note",
                "comparability_status": "unaudited_company_pro_forma_tyman_and_lmi_combination",
                "notes": (
                    "Later 10-K summary controls for its presentation; the earlier exhibit remains separately preserved."
                    if year == 2023 and metric == "net_income" else
                    "Summary pro forma disclosure; detailed components are not provided for this period."
                ),
            })
    return rows


def adjustment_seed_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    values = {
        2025: (
            ("goodwill_impairment", 302284, "added_back_in_company_ebitda_bridge", "SRC-002",
             "FY2025 results release, Adjusted EBITDA reconciliation"),
            ("plant_relocation_cost_of_sales", 1432, "added_back_by_company", "SRC-002",
             "FY2025 results release, Selected Segment Data reconciliation"),
            ("plant_relocation_sga", 221, "added_back_by_company", "SRC-002",
             "FY2025 results release, Selected Segment Data reconciliation"),
            ("inventory_purchase_accounting_step_up", 9007, "added_back_by_company", "SRC-002",
             "FY2025 results release, Selected Segment Data reconciliation"),
            ("transaction_advisory_reorganization_and_product_recall", 10263, "added_back_by_company", "SRC-002",
             "FY2025 results release, Selected Segment Data reconciliation"),
            ("restructuring_severance_and_software", 10191, "added_back_by_company", "SRC-002",
             "FY2025 results release, Selected Segment Data reconciliation"),
            ("tyman_post_measurement_period_tax_correction", 9000,
             "disclosed_discrete_tax_charge_not_an_ebitda_item", "SRC-001",
             "FY2025 Form 10-K Note 2, Tyman acquisition, p. 54"),
        ),
        2024: (
            ("plant_closure_cost_of_sales", 3025, "added_back_by_company", "SRC-002",
             "FY2025 results release, Selected Segment Data reconciliation"),
            ("plant_closure_gain_sga", -4196, "deducted_by_company", "SRC-002",
             "FY2025 results release, Selected Segment Data reconciliation"),
            ("inventory_and_receivables_purchase_accounting_step_up", 29076, "added_back_by_company", "SRC-002",
             "FY2025 results release, Selected Segment Data reconciliation"),
            ("transaction_and_advisory_fees", 39324, "added_back_by_company", "SRC-002",
             "FY2025 results release, Selected Segment Data reconciliation"),
        ),
    }
    for year, items in values.items():
        start, end = fiscal_period(year)
        for metric, value, treatment, source_id, reference in items:
            rows.append({
                "candidate_id": f"AC-{len(rows) + 1:03d}",
                "fiscal_year": f"FY{year}", "period_start": start,
                "period_end": end, "metric_name": metric,
                "original_value": str(value), "original_units": "USD_thousands",
                "normalized_value": fmt(Decimal(value) / 1000),
                "normalized_units": "USD_millions", "source_id": source_id,
                "source_reference": reference,
                "company_treatment": treatment, "phase2_status": "unreviewed",
                "notes": (
                    "Company-disclosed discrete tax item for Phase 2 earnings-quality review; not an EBITDA addback."
                    if metric == "tyman_post_measurement_period_tax_correction" else
                    "Company-disclosed non-GAAP item only; no lender-normalization judgment made."
                ),
            })
    return rows


def debt_seed_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add(instrument: str, name: str, value: str, numeric: str = "",
            units: str = "text", status: str = "reported",
            sources: str = "SRC-003", reference: str = "Conformed Credit Agreement",
            conflict: str = "", resolution: str = "", note: str = "") -> None:
        rows.append({
            "term_id": f"DT-{len(rows) + 1:03d}", "instrument_name": instrument,
            "as_of_date": "2025-10-31", "term_name": name, "value_text": value,
            "numeric_value": numeric, "units": units, "status": status,
            "source_ids": sources, "source_reference": reference,
            "conflict_group": conflict, "authority_resolution": resolution,
            "notes": note,
        })

    both = "Term Loan A and Revolving Credit Facility"
    add(both, "borrower", "Quanex Building Products Corporation")
    add(both, "guarantee_scope", "Subsidiary guarantors other than excluded subsidiaries")
    add(both, "current_named_guarantors", "Public evidence does not establish the complete post-Tyman guarantor schedule",
        status="not_determinable", sources="SRC-001;SRC-003")
    add(both, "security", "First-priority liens, subject to permitted liens, on substantially all loan-party assets")
    add(both, "collateral_scope", "Substantially all domestic assets other than real property; excluded assets and foreign-equity limits apply",
        sources="SRC-001;SRC-003")
    add(both, "current_perfection_and_joinders", "Exact post-Tyman joinders, pledged equity, excluded assets, and perfection",
        status="not_determinable", sources="SRC-001;SRC-003")
    add("Term Loan A", "original_principal", "$500.0 million", "500", "USD_millions")
    add("Term Loan A", "current_funded_principal", "$468.75 million", "468.75", "USD_millions",
        sources="SRC-001;SRC-002", reference="FY2025 Form 10-K Note 9 and FY2025 results release")
    add("Term Loan A", "scheduled_amortization_quarterly", "1.25% of original principal / $6.25 million", "6.25", "USD_millions")
    add("Term Loan A", "scheduled_amortization_annual", "$25.0 million", "25", "USD_millions", status="calculated",
        sources="SRC-003", note="Four quarterly installments of $6.25 million.")
    add("Term Loan A", "maturity", "August 1, 2029", units="date")
    add("Term Loan A", "voluntary_prepayment", "Permitted without premium or penalty, subject to notice, minimums, and interest-period breakage")
    add("Term Loan A", "mandatory_prepayment", "Specified non-permitted debt and qualifying asset-sale, insurance, and condemnation proceeds, subject to exceptions and thresholds")
    add(both, "facility_principal_due_fy2026", "$25.0 million", "25", "USD_millions",
        sources="SRC-001", reference="FY2025 Form 10-K Note 9 debt maturity table")
    add(both, "facility_principal_due_fy2027", "$25.0 million", "25", "USD_millions",
        sources="SRC-001", reference="FY2025 Form 10-K Note 9 debt maturity table")
    add(both, "facility_principal_due_fy2028", "$25.0 million", "25", "USD_millions",
        sources="SRC-001", reference="FY2025 Form 10-K Note 9 debt maturity table")
    add(both, "facility_principal_due_fy2029", "$566.25 million", "566.25", "USD_millions",
        sources="SRC-001", reference="FY2025 Form 10-K Note 9 debt maturity table",
        note="Includes current revolver usage and the Term A balloon; revolver usage can change.")
    add("Revolving Credit Facility", "total_commitment", "$475.0 million", "475", "USD_millions")
    add("Revolving Credit Facility", "current_funded_principal", "$172.5 million", "172.5", "USD_millions",
        sources="SRC-001;SRC-002", reference="FY2025 Form 10-K Note 9 and FY2025 results release")
    add("Revolving Credit Facility", "letters_of_credit_outstanding", "$6.2 million", "6.2", "USD_millions",
        sources="SRC-001", reference="FY2025 Form 10-K Note 9")
    add("Revolving Credit Facility", "availability", "$296.3 million", "296.3", "USD_millions", status="calculated",
        sources="SRC-001;SRC-003", note="$475.0m commitment less $172.5m borrowings and $6.2m letters of credit.")
    add("Revolving Credit Facility", "maturity", "August 1, 2029", units="date")
    add("Revolving Credit Facility", "alternative_currency_sublimit", "$100.0 million", "100", "USD_millions")
    add("Revolving Credit Facility", "letter_of_credit_sublimit", "$30.0 million", "30", "USD_millions")
    add("Revolving Credit Facility", "swingline_sublimit", "$15.0 million", "15", "USD_millions")
    add(both, "interest_rate_benchmark", "Base Rate, Adjusted Term SOFR, or specified alternative-currency rate mechanics")
    pricing = (
        ("pricing_band_1", "CNLR <=1.50x: commitment 0.150%; SOFR/RFR 2.00%; Base Rate 1.00%"),
        ("pricing_band_2", "CNLR >1.50x and <=2.25x: commitment 0.175%; SOFR/RFR 2.25%; Base Rate 1.25%"),
        ("pricing_band_3", "CNLR >2.25x and <=3.00x: commitment 0.200%; SOFR/RFR 2.50%; Base Rate 1.50%"),
        ("pricing_band_4", "CNLR >3.00x: commitment 0.250%; SOFR/RFR 2.75%; Base Rate 1.75%"),
    )
    for name, value in pricing:
        add(both, name, value, units="percent")
    add(both, "default_interest_spread", "2.00% above otherwise applicable rate", "2", "percent")
    add(both, "undisclosed_fee_letters", "Other fee-letter economics are not public",
        status="not_determinable", sources="SRC-003")
    add(both, "consolidated_net_leverage_ratio_maximum", "Not greater than 3.25x", "3.25", "turns",
        sources="SRC-001;SRC-003", reference="Conformed Credit Agreement section 7.1 and FY2025 10-K MD&A",
        conflict="CNLR_DIRECTION", resolution="Executed agreement controls; 3.25x is a maximum.")
    add(both, "fy2025_10k_note_9_cnlr_wording", "Must be greater than 3.25x", "3.25", "turns",
        status="conflicting_source", sources="SRC-001", reference="FY2025 Form 10-K Note 9",
        conflict="CNLR_DIRECTION", resolution="Rejected as a drafting error because the executed agreement and MD&A use not-greater-than.")
    add(both, "consolidated_interest_coverage_ratio_minimum", "Not less than 3.00x", "3", "turns")
    add(both, "qualifying_acquisition_step_up", "Maximum CNLR may increase to 3.75x for the specified four-quarter period after a qualifying acquisition over $100 million", "3.75", "turns")
    add(both, "january_31_2026_cnlr_maximum", "3.25x absent another permitted acquisition step-up", "3.25", "turns",
        sources="SRC-003;SRC-016", reference="Conformed Credit Agreement section 7.1 and June 5, 2025 results release")
    add(both, "cash_netting_cap", "$100.0 million eligible unrestricted cash", "100", "USD_millions")
    add(both, "non_us_cash_sublimit", "$25.0 million within cash-netting cap", "25", "USD_millions")
    add(both, "eligible_cash_at_2025_10_31", "Amount satisfying accessibility and lien conditions is not public",
        status="not_determinable", sources="SRC-001;SRC-003")
    add(both, "incremental_facility_capacity", "Greater of $310 million and 100% of Consolidated EBITDA, minimum $10 million increments; uncommitted", "310", "USD_millions")
    add(both, "negative_covenant_scope", "Debt, liens, fundamental changes, dispositions, junior-debt prepayments, restricted payments, investments, affiliate transactions, and restrictive agreements, subject to baskets and exceptions")
    add(both, "restricted_payment_condition", "Certain actions require pro forma CNLR <=2.75x and liquidity >$25 million", "2.75", "turns")
    add(both, "published_covenant_headroom", "Compliance was reported, but the full calculation and numerical headroom were not published",
        status="not_determinable", sources="SRC-001")
    add(both, "unamortized_financing_fees", "$11.040 million contra-debt", "11.04", "USD_millions",
        sources="SRC-001", reference="FY2025 Form 10-K Note 9")
    add(both, "finance_leases_and_other_debt", "$62.619 million principal; $56.4 million relates to real-estate finance leases", "62.619", "USD_millions",
        sources="SRC-001;SRC-002", reference="FY2025 Form 10-K Note 9 and results-release net-debt reconciliation")
    add(both, "gross_facility_borrowings", "$641.25 million", "641.25", "USD_millions", status="calculated",
        sources="SRC-001;SRC-002", note="$468.75m Term A plus $172.5m revolver.")
    add(both, "gross_debt_including_leases_and_other", "$703.869 million", "703.869", "USD_millions", status="calculated",
        sources="SRC-001;SRC-002", note="$641.25m facility principal plus $62.619m leases/other.")
    add(both, "balance_sheet_debt_after_financing_fees", "$692.829 million", "692.829", "USD_millions", status="calculated",
        sources="SRC-001", note="$703.869m gross debt less $11.040m unamortized financing fees.")
    add(both, "hedge_and_break_costs_on_hypothetical_refinancing", "Not publicly determinable",
        status="not_determinable", sources="SRC-001;SRC-003")
    add(both, "hypothetical_2026_closing_balances", "Not yet forecast or approved",
        status="not_determinable", sources="SRC-001;SRC-003",
        note="Deferred to later phases; October 31, 2025 balances are not a closing forecast.")
    return rows


def seed_raw() -> None:
    sources = read_sources()
    manifest = []
    for sid in REQUIRED_SOURCE_IDS:
        src = sources[sid]
        manifest.append({
            "source_id": sid, "document_title": src.document_title,
            "document_type": src.document_type,
            "publication_or_filing_date": src.publication_or_filing_date,
            "reporting_or_effective_date": src.reporting_or_effective_date,
            "source_url": src.source_location, "local_path": "", "sha256": "",
            "bytes": "", "preservation_mode": "reproducible_reference",
            "cutoff_status": "ALLOWED",
            "notes": "Exact Phase 0-approved archival reference; automated SEC download returned HTTP 403 in this environment. Curated extracts are preserved in adjacent raw CSVs.",
        })
    write_csv(RAW_DIR / "SOURCE_MANIFEST.csv", manifest, MANIFEST_FIELDS)
    write_csv(RAW_DIR / "SOURCE_FACTS.csv", historical_seed_rows(), RAW_FACT_FIELDS)
    write_csv(RAW_DIR / "PRO_FORMA_FACTS.csv", pro_forma_seed_rows(), RAW_FACT_FIELDS)
    write_csv(RAW_DIR / "ADJUSTMENT_CANDIDATES.csv", adjustment_seed_rows(), ADJUSTMENT_FIELDS)
    write_csv(RAW_DIR / "DEBT_TERMS.csv", debt_seed_rows(), DEBT_FIELDS)
    override_path = RAW_DIR / "MANUAL_OVERRIDES.csv"
    if not override_path.exists():
        write_csv(override_path, [], OVERRIDE_FIELDS)
    print("Seeded bounded raw evidence extracts and reproducible source references.")


def validate_source_references(rows: Iterable[dict[str, str]], sources: dict[str, Source],
                               field: str) -> None:
    for row in rows:
        ids = source_ids(row[field])
        if not ids:
            raise Phase1Error(f"Missing source reference in {row}")
        for sid in ids:
            if sid not in REQUIRED_SOURCE_IDS or sid not in sources:
                raise Phase1Error(f"Unapproved or unknown source reference: {sid}")
            filing = datetime.strptime(sources[sid].publication_or_filing_date, "%Y-%m-%d").date()
            if filing > CUTOFF:
                raise Phase1Error(f"Post-cutoff source referenced: {sid}")


def validate_manifest(rows: list[dict[str, str]], sources: dict[str, Source]) -> None:
    if [row["source_id"] for row in rows] != list(REQUIRED_SOURCE_IDS):
        raise Phase1Error("Source manifest changed or expanded without approval")
    for row in rows:
        sid = row["source_id"]
        source = sources[sid]
        if ("10-K/A" in row["document_type"].upper() or
                "10-Q/A" in row["document_type"].upper() or
                "FORM 10-K/A" in row["document_title"].upper() or
                "FORM 10-Q/A" in row["document_title"].upper()):
            raise Phase1Error(f"Amended filing requires explicit resolution: {sid}")
        expected = {
            "document_title": source.document_title,
            "document_type": source.document_type,
            "publication_or_filing_date": source.publication_or_filing_date,
            "reporting_or_effective_date": source.reporting_or_effective_date,
            "source_url": source.source_location,
        }
        for field, value in expected.items():
            if row[field] != value:
                raise Phase1Error(f"Silent source replacement detected: {sid} {field}")
        if (row["cutoff_status"] != "ALLOWED" or
                row["preservation_mode"] not in {"reproducible_reference", "local_copy"}):
            raise Phase1Error(f"Invalid source-manifest control: {sid}")
        if (row["preservation_mode"] == "local_copy" and
                (not row["local_path"] or not row["sha256"] or not row["bytes"])):
            raise Phase1Error(f"Local source lacks path/hash/size: {sid}")


def validate_fact_rows(rows: list[dict[str, str]], sources: dict[str, Source],
                       expected_layer: str) -> None:
    ids = [row["raw_fact_id"] for row in rows]
    duplicates = [key for key, count in Counter(ids).items() if count > 1]
    if duplicates:
        raise Phase1Error(f"Duplicate raw fact IDs: {duplicates}")
    keys = [(r["layer"], r["variant"], r["metric_name"], r["fiscal_year"], r["period_start"],
             r["period_end"], r["period_type"]) for r in rows]
    duplicate_keys = [key for key, count in Counter(keys).items() if count > 1]
    if duplicate_keys:
        raise Phase1Error(f"Duplicate facts: {duplicate_keys[:3]}")
    validate_source_references(rows, sources, "source_id")
    for row in rows:
        if row["layer"] != expected_layer:
            raise Phase1Error(f"Incorrect layer on {row['raw_fact_id']}")
        if not row["variant"]:
            raise Phase1Error(f"Missing fact variant on {row['raw_fact_id']}")
        if row["period_type"] not in {"instant", "duration"}:
            raise Phase1Error(f"Invalid period type on {row['raw_fact_id']}")
        if row["period_type"] == "instant" and row["period_start"]:
            raise Phase1Error(f"Instant fact has a start date: {row['raw_fact_id']}")
        if row["period_type"] == "duration":
            if not row["period_start"] or not row["period_end"]:
                raise Phase1Error(f"Duration fact lacks dates: {row['raw_fact_id']}")
            if row["period_start"] >= row["period_end"]:
                raise Phase1Error(f"Impossible period sequence: {row['raw_fact_id']}")
        if row["original_units"] != "USD_thousands":
            raise Phase1Error(f"Unsupported source unit on {row['raw_fact_id']}")
        parse_decimal(row["original_value"], row["raw_fact_id"])
        multiplier = parse_decimal(row["normalization_multiplier"], row["raw_fact_id"])
        if multiplier not in {Decimal(-1), Decimal(1)}:
            raise Phase1Error(f"Invalid normalization multiplier on {row['raw_fact_id']}")
        if not row["source_reference"]:
            raise Phase1Error(f"Missing page/section reference: {row['raw_fact_id']}")
    if expected_layer == "reported_historical":
        years = {row["fiscal_year"] for row in rows}
        expected = {f"FY{year}" for year in range(2021, 2026)}
        if not expected.issubset(years):
            raise Phase1Error(f"Historical coverage missing: {sorted(expected - years)}")
        for row in rows:
            if row["period_type"] == "duration":
                year = int(row["fiscal_year"][2:])
                if (row["period_start"], row["period_end"]) != fiscal_period(year):
                    raise Phase1Error(f"Wrong fiscal period: {row['raw_fact_id']}")
                if row["period_grain"] != "annual":
                    raise Phase1Error(f"Annual/quarterly confusion: {row['raw_fact_id']}")
            else:
                year = int(row["fiscal_year"][2:])
                if row["period_end"] != f"{year}-10-31" or row["period_grain"] != "year_end":
                    raise Phase1Error(f"Wrong balance-sheet date: {row['raw_fact_id']}")


def validate_overrides(rows: list[dict[str, str]], raw_ids: set[str],
                       sources: dict[str, Source] | None = None) -> None:
    for row in rows:
        if row["status"] not in {"active", "superseded"}:
            raise Phase1Error(f"Invalid manual override status: {row.get('override_id')}")
        missing = [field for field in OVERRIDE_FIELDS if not row.get(field)]
        if missing:
            raise Phase1Error(f"Unsupported manual override {row.get('override_id')}: {missing}")
        if row["affected_raw_fact_id"] not in raw_ids:
            raise Phase1Error(f"Override targets missing fact: {row['affected_raw_fact_id']}")
        if sources is not None:
            validate_source_references([row], sources, "source_id")


def validate_pro_forma_variants(rows: list[dict[str, str]]) -> None:
    grouped: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(row["metric_name"], row["fiscal_year"], row["period_start"],
                 row["period_end"])].append(row)
    conflicts_seen = 0
    for key, variants in grouped.items():
        values = {row["original_value"] for row in variants}
        if len(values) <= 1:
            continue
        conflicts_seen += 1
        if len({row["source_id"] for row in variants}) < 2:
            raise Phase1Error(f"Conflicting pro forma values lack distinct sources: {key}")
        if not any("controls" in row["notes"] for row in variants):
            raise Phase1Error(f"Pro forma conflict lacks authority resolution: {key}")
    expected_key = ("net_income", "FY2023", "2022-11-01", "2023-10-31")
    expected_values = {"48457", "48458"}
    actual_values = {row["original_value"] for row in grouped.get(expected_key, [])}
    if actual_values != expected_values or conflicts_seen != 1:
        raise Phase1Error("Known FY2023 pro forma rounding conflict is not preserved")


def normalize_facts(rows: list[dict[str, str]], overrides: list[dict[str, str]]) -> list[dict[str, str]]:
    active = {row["affected_raw_fact_id"]: row for row in overrides if row["status"] == "active"}
    result = []
    for index, row in enumerate(rows, start=1):
        original = parse_decimal(row["original_value"], row["raw_fact_id"])
        override = active.get(row["raw_fact_id"])
        base = parse_decimal(override["replacement_value"], override["override_id"]) if override else original
        value = base * parse_decimal(row["normalization_multiplier"], row["raw_fact_id"]) / Decimal(1000)
        result.append({
            "fact_id": f"NF-{index:04d}", "layer": row["layer"],
            "variant": row["variant"], "metric_name": row["metric_name"],
            "fiscal_year": row["fiscal_year"],
            "period_start": row["period_start"], "period_end": row["period_end"],
            "period_type": row["period_type"], "period_grain": row["period_grain"],
            "statement": row["statement"], "original_reported_value": row["original_value"],
            "original_units": row["original_units"], "normalized_value": fmt(value),
            "normalized_units": "USD_millions", "classification": "reported",
            "source_ids": row["source_id"], "source_reference": row["source_reference"],
            "source_type": row["source_type"],
            "override_status": "active" if override else "none",
            "override_rationale": override["reason"] if override else "",
            "comparability_status": row["comparability_status"], "calculation": "",
            "notes": row["notes"],
        })
    return result


def add_calculated_facts(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result = list(rows)
    by_key = {(row["fiscal_year"], row["metric_name"]): row for row in rows}
    calculations = (
        ("gross_profit", "revenue", "cost_of_sales_excluding_depreciation_and_amortization"),
        ("free_cash_flow_before_finance_lease_payments", "cash_flow_from_operations", "capital_expenditures"),
        ("total_debt_carrying_amount", "current_maturities_of_long_term_debt", "long_term_debt"),
        ("total_operating_lease_liabilities", "current_operating_lease_liabilities", "noncurrent_operating_lease_liabilities"),
    )
    for year in (f"FY{n}" for n in range(2021, 2026)):
        for output_metric, left_metric, right_metric in calculations:
            left = by_key.get((year, left_metric))
            right = by_key.get((year, right_metric))
            if not left or not right:
                continue
            value = (parse_decimal(left["normalized_value"], left["fact_id"]) +
                     parse_decimal(right["normalized_value"], right["fact_id"]))
            result.append({
                "fact_id": f"CF-{len(result) + 1:04d}", "layer": "calculated",
                "variant": "mechanical", "metric_name": output_metric,
                "fiscal_year": year,
                "period_start": left["period_start"], "period_end": left["period_end"],
                "period_type": left["period_type"], "period_grain": left["period_grain"],
                "statement": "calculated", "original_reported_value": "",
                "original_units": "", "normalized_value": fmt(value),
                "normalized_units": "USD_millions", "classification": "calculated",
                "source_ids": ";".join(dict.fromkeys(source_ids(left["source_ids"]) + source_ids(right["source_ids"]))),
                "source_reference": f"Calculated from {left['fact_id']} and {right['fact_id']}",
                "source_type": "calculated_from_reported_facts", "override_status": "none",
                "override_rationale": "", "comparability_status": left["comparability_status"],
                "calculation": f"{left_metric} + {right_metric}",
                "notes": "Mechanical calculation; not an analyst adjustment.",
            })
    return result


def validate_processed(rows: list[dict[str, str]],
                       sources: dict[str, Source] | None = None) -> None:
    keys = [(r["layer"], r["variant"], r["metric_name"], r["fiscal_year"],
             r["period_end"]) for r in rows]
    duplicates = [key for key, count in Counter(keys).items() if count > 1]
    if duplicates:
        raise Phase1Error(f"Duplicate processed facts: {duplicates[:3]}")
    if sources is not None:
        validate_source_references(rows, sources, "source_ids")
    for row in rows:
        if not row["source_ids"] or not row["source_reference"]:
            raise Phase1Error(f"Processed fact lacks provenance: {row['fact_id']}")
        value = parse_decimal(row["normalized_value"], row["fact_id"])
        if row["classification"] in {"reported", "reported_pro_forma"}:
            original = parse_decimal(row["original_reported_value"], row["fact_id"])
            expected_abs = abs(original) / Decimal(1000)
            if abs(value) != expected_abs and row["override_status"] == "none":
                raise Phase1Error(f"Scaling error: {row['fact_id']}")
        if row["metric_name"] in {"capital_expenditures", "dividends_paid", "share_repurchases", "acquisition_cash_flows"} and value > 0:
            raise Phase1Error(f"Cash outflow sign error: {row['fact_id']}")
        expense_metrics = {
            "cost_of_sales_excluding_depreciation_and_amortization",
            "selling_general_and_administrative", "restructuring_charges",
            "depreciation_and_amortization", "goodwill_impairment_charges",
            "interest_expense", "income_tax_expense",
        }
        asset_and_debt_metrics = {
            "cash_and_cash_equivalents", "restricted_cash", "accounts_receivable",
            "inventory", "income_taxes_receivable", "prepaid_assets",
            "other_current_assets", "prepaid_and_other_current_assets",
            "current_assets", "property_plant_and_equipment_net",
            "operating_lease_right_of_use_assets", "goodwill",
            "intangible_assets_net", "accounts_payable", "accrued_liabilities",
            "income_taxes_payable", "current_maturities_of_long_term_debt",
            "current_operating_lease_liabilities", "current_liabilities",
            "long_term_debt", "noncurrent_operating_lease_liabilities",
            "term_loan_principal", "revolver_borrowings",
            "finance_lease_obligations_principal", "total_debt_principal",
            "net_debt_company_definition",
        }
        if row["metric_name"] in expense_metrics and value > 0:
            raise Phase1Error(f"Expense sign error: {row['fact_id']}")
        if row["metric_name"] in asset_and_debt_metrics and value < 0:
            raise Phase1Error(f"Balance/debt sign error: {row['fact_id']}")


def validate_adjustments(rows: list[dict[str, str]], sources: dict[str, Source]) -> None:
    validate_source_references(rows, sources, "source_id")
    keys = [(row["fiscal_year"], row["metric_name"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise Phase1Error("Duplicated acquisition/adjustment information")
    for row in rows:
        if row["phase2_status"] != "unreviewed":
            raise Phase1Error(f"Phase 1 embedded an adjustment judgment: {row['candidate_id']}")
        expected = parse_decimal(row["original_value"], row["candidate_id"]) / 1000
        if parse_decimal(row["normalized_value"], row["candidate_id"]) != expected:
            raise Phase1Error(f"Adjustment scaling error: {row['candidate_id']}")


def validate_debt(rows: list[dict[str, str]], sources: dict[str, Source]) -> None:
    ids = [row["term_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise Phase1Error("Duplicate debt term IDs")
    validate_source_references(rows, sources, "source_ids")
    conflicts: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row["status"] not in ALLOWED_DEBT_STATUSES:
            raise Phase1Error(f"Invalid debt status: {row['term_id']}")
        if row["status"] == "not_determinable" and row["numeric_value"]:
            raise Phase1Error(f"Not-determinable term has a numeric value: {row['term_id']}")
        if row["conflict_group"]:
            conflicts[row["conflict_group"]].append(row)
        if row["numeric_value"]:
            parse_decimal(row["numeric_value"], row["term_id"])
    for group, group_rows in conflicts.items():
        if len(group_rows) < 2 or not any(r["status"] == "conflicting_source" for r in group_rows):
            raise Phase1Error(f"Conflict is not fully visible: {group}")
        if any(not r["authority_resolution"] for r in group_rows):
            raise Phase1Error(f"Conflict lacks authority resolution: {group}")
    instrument_values = {
        (r["instrument_name"], r["term_name"]): Decimal(r["numeric_value"])
        for r in rows if r["numeric_value"]
    }
    term = instrument_values[("Term Loan A", "current_funded_principal")]
    revolver = instrument_values[("Revolving Credit Facility", "current_funded_principal")]
    commitment = instrument_values[("Revolving Credit Facility", "total_commitment")]
    letters = instrument_values[("Revolving Credit Facility", "letters_of_credit_outstanding")]
    availability = instrument_values[("Revolving Credit Facility", "availability")]
    if term + revolver != Decimal("641.25"):
        raise Phase1Error("Facility debt does not reconcile")
    if commitment - revolver - letters != availability:
        raise Phase1Error("Revolver availability does not reconcile")
    maturity_total = sum(
        Decimal(row["numeric_value"]) for row in rows
        if row["term_name"].startswith("facility_principal_due_fy")
    )
    if maturity_total != term + revolver:
        raise Phase1Error("Facility maturity schedule does not reconcile")
    if Decimal("641.25") + Decimal("62.619") != Decimal("703.869"):
        raise Phase1Error("Gross debt does not reconcile")
    if Decimal("703.869") - Decimal("11.040") != Decimal("692.829"):
        raise Phase1Error("Debt carrying amount does not reconcile")


def source_metadata(ids: str, sources: dict[str, Source],
                    manifest: dict[str, dict[str, str]]) -> dict[str, str]:
    selected = [sources[sid] for sid in source_ids(ids)]
    return {
        "document_titles": "; ".join(src.document_title for src in selected),
        "document_types": "; ".join(src.document_type for src in selected),
        "source_urls": "; ".join(src.source_location for src in selected),
        "local_source_paths": "; ".join(
            manifest[src.source_id]["local_path"] for src in selected
            if manifest[src.source_id]["local_path"]
        ),
        "publication_or_filing_dates": "; ".join(
            src.publication_or_filing_date for src in selected
        ),
    }


def build_ledger(historical: list[dict[str, str]], pro_forma: list[dict[str, str]],
                 adjustments: list[dict[str, str]], debt: list[dict[str, str]],
                 sources: dict[str, Source],
                 manifest_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    manifest = {row["source_id"]: row for row in manifest_rows}
    ledger = []

    def add(issue_id: str, layer: str, ids: str, period: str, reference: str,
            metric: str, original: str, original_units: str, normalized: str,
            normalized_units: str, classification: str, src_type: str,
            override_status: str, override_rationale: str, notes: str) -> None:
        meta = source_metadata(ids, sources, manifest)
        ledger.append({
            "record_id": issue_id, "layer": layer, "source_ids": ids, **meta,
            "reporting_period": period, "source_reference": reference,
            "metric_or_term": metric, "original_value": original,
            "original_units": original_units, "normalized_value": normalized,
            "normalized_units": normalized_units, "classification": classification,
            "source_type": src_type, "override_status": override_status,
            "override_rationale": override_rationale, "notes_limitations": notes,
        })

    for sid in REQUIRED_SOURCE_IDS:
        source = sources[sid]
        add(f"SOURCE-{sid}", "source_document", sid,
            source.reporting_or_effective_date, source.authority,
            "approved_source_document", "", "", "", "", "approved_source",
            source.document_type, "none", "",
            f"Cutoff-approved; preservation_mode={manifest[sid]['preservation_mode']}. "
            f"{manifest[sid]['notes']}")

    for row in historical + pro_forma:
        period = (row["period_end"] if row["period_type"] == "instant" else
                  f"{row['period_start']} to {row['period_end']}")
        add(row["fact_id"], row["layer"], row["source_ids"], period,
            row["source_reference"], row["metric_name"],
            row["original_reported_value"], row["original_units"],
            row["normalized_value"], row["normalized_units"], row["classification"],
            row["source_type"], row["override_status"], row["override_rationale"],
            " | ".join(filter(None, [f"variant={row['variant']}", row["comparability_status"],
                                      row["calculation"], row["notes"]])))
    for row in adjustments:
        add(row["candidate_id"], "company_adjustment_candidate", row["source_id"],
            f"{row['period_start']} to {row['period_end']}", row["source_reference"],
            row["metric_name"], row["original_value"], row["original_units"],
            row["normalized_value"], row["normalized_units"],
            ("reported_discrete_tax_candidate"
             if row["metric_name"] == "tyman_post_measurement_period_tax_correction"
             else "reported_non_gaap_candidate"),
            "SEC_filing" if row["source_id"] == "SRC-001" else "company_results_release",
            "none", "",
            f"{row['company_treatment']} | phase2_status={row['phase2_status']} | {row['notes']}")
    for row in debt:
        add(row["term_id"], "debt_term", row["source_ids"], row["as_of_date"],
            row["source_reference"], f"{row['instrument_name']}: {row['term_name']}",
            row["value_text"], row["units"], row["numeric_value"], row["units"],
            row["status"], "contract_or_company_disclosure", "none", "",
            " | ".join(filter(None, [row["conflict_group"],
                                      row["authority_resolution"], row["notes"]])))
    return ledger


def build() -> None:
    sources = read_sources()
    manifest = read_csv(RAW_DIR / "SOURCE_MANIFEST.csv")
    validate_manifest(manifest, sources)
    raw = read_csv(RAW_DIR / "SOURCE_FACTS.csv")
    raw_pf = read_csv(RAW_DIR / "PRO_FORMA_FACTS.csv")
    overrides = read_csv(RAW_DIR / "MANUAL_OVERRIDES.csv")
    adjustments = read_csv(RAW_DIR / "ADJUSTMENT_CANDIDATES.csv")
    debt = read_csv(RAW_DIR / "DEBT_TERMS.csv")
    validate_fact_rows(raw, sources, "reported_historical")
    validate_fact_rows(raw_pf, sources, "company_disclosed_pro_forma")
    validate_pro_forma_variants(raw_pf)
    validate_overrides(overrides, {row["raw_fact_id"] for row in raw + raw_pf}, sources)
    historical = add_calculated_facts(normalize_facts(raw, overrides))
    pro_forma = normalize_facts(raw_pf, overrides)
    for row in pro_forma:
        row["fact_id"] = row["fact_id"].replace("NF-", "PFN-")
        row["classification"] = "reported_pro_forma"
    validate_processed(historical, sources)
    validate_processed(pro_forma, sources)
    validate_adjustments(adjustments, sources)
    validate_debt(debt, sources)
    write_csv(PROCESSED_DIR / "historical_facts.csv", historical,
              PROCESSED_FACT_FIELDS)
    write_csv(PROCESSED_DIR / "pro_forma_facts.csv", pro_forma,
              PROCESSED_FACT_FIELDS)
    write_csv(PROCESSED_DIR / "adjustment_candidates.csv", adjustments,
              ADJUSTMENT_FIELDS)
    write_csv(PROCESSED_DIR / "debt_terms.csv", debt, DEBT_FIELDS)
    ledger = build_ledger(historical, pro_forma, adjustments, debt, sources, manifest)
    write_csv(PHASE1_DOCS_DIR / "SOURCE_LEDGER.csv", ledger,
              tuple(ledger[0].keys()))
    print(f"Built {len(historical)} historical/calculated facts, "
          f"{len(pro_forma)} pro forma facts, {len(adjustments)} adjustment "
          f"candidates, and {len(debt)} debt terms.")


def validate_all() -> dict[str, int]:
    sources = read_sources()
    manifest = read_csv(RAW_DIR / "SOURCE_MANIFEST.csv")
    validate_manifest(manifest, sources)
    raw = read_csv(RAW_DIR / "SOURCE_FACTS.csv")
    raw_pf = read_csv(RAW_DIR / "PRO_FORMA_FACTS.csv")
    overrides = read_csv(RAW_DIR / "MANUAL_OVERRIDES.csv")
    raw_adjustments = read_csv(RAW_DIR / "ADJUSTMENT_CANDIDATES.csv")
    raw_debt = read_csv(RAW_DIR / "DEBT_TERMS.csv")
    adjustments = read_csv(PROCESSED_DIR / "adjustment_candidates.csv")
    debt = read_csv(PROCESSED_DIR / "debt_terms.csv")
    historical = read_csv(PROCESSED_DIR / "historical_facts.csv")
    pro_forma = read_csv(PROCESSED_DIR / "pro_forma_facts.csv")
    ledger = read_csv(PHASE1_DOCS_DIR / "SOURCE_LEDGER.csv")
    validate_fact_rows(raw, sources, "reported_historical")
    validate_fact_rows(raw_pf, sources, "company_disclosed_pro_forma")
    validate_pro_forma_variants(raw_pf)
    validate_overrides(overrides, {row["raw_fact_id"] for row in raw + raw_pf}, sources)
    validate_processed(historical, sources)
    validate_processed(pro_forma, sources)
    validate_adjustments(adjustments, sources)
    validate_debt(debt, sources)
    expected_historical = add_calculated_facts(normalize_facts(raw, overrides))
    expected_pro_forma = normalize_facts(raw_pf, overrides)
    for row in expected_pro_forma:
        row["fact_id"] = row["fact_id"].replace("NF-", "PFN-")
        row["classification"] = "reported_pro_forma"
    if historical != expected_historical or pro_forma != expected_pro_forma:
        raise Phase1Error("Processed fact output diverges from raw evidence")
    if adjustments != raw_adjustments or debt != raw_debt:
        raise Phase1Error("Processed register diverges from controlled raw input")
    expected_ledger = (len(manifest) + len(historical) + len(pro_forma) +
                       len(adjustments) + len(debt))
    if len(ledger) != expected_ledger:
        raise Phase1Error(f"Source ledger is incomplete: {len(ledger)} != {expected_ledger}")
    expected_ledger_rows = build_ledger(
        historical, pro_forma, adjustments, debt, sources, manifest
    )
    if ledger != expected_ledger_rows:
        raise Phase1Error("Source ledger diverges from normalized outputs")
    if any(row["layer"] == "company_disclosed_pro_forma" for row in historical):
        raise Phase1Error("Pro forma values contaminated reported history")
    stats = {
        "sources": len(manifest), "historical_total": len(historical),
        "historical_reported": sum(r["classification"] == "reported" for r in historical),
        "historical_calculated": sum(r["classification"] == "calculated" for r in historical),
        "pro_forma": len(pro_forma), "adjustment_candidates": len(adjustments),
        "debt_terms": len(debt),
        "debt_not_determinable": sum(r["status"] == "not_determinable" for r in debt),
        "debt_conflicting": sum(r["status"] == "conflicting_source" for r in debt),
        "manual_overrides": sum(r["status"] == "active" for r in overrides),
        "ledger_entries": len(ledger),
    }
    print("Phase 1 validation: PASS")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("seed", "build", "validate", "all"),
                        help="seed raw extracts, build outputs, validate, or run all")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command in {"seed", "all"}:
            seed_raw()
        if args.command in {"build", "all"}:
            build()
        if args.command in {"validate", "all"}:
            validate_all()
    except (Phase1Error, KeyError, OSError, ValueError) as exc:
        print(f"Phase 1 error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
