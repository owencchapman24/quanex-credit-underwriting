#!/usr/bin/env python3
"""Build and validate the Quanex Phase 3 driver-evidence layer.

This workflow is deliberately case-specific and network-independent. It uses
source-faithful, cutoff-controlled extracts to produce reviewable borrower,
industry, scenario-driver, mitigation, and diligence registers. It does not
build forecasts or run scenarios.
"""

from __future__ import annotations

import argparse
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
RAW = ROOT / "data" / "phase3" / "raw"
PROCESSED = ROOT / "data" / "phase3" / "processed"
DOCS = ROOT / "docs" / "phase-3"
PHASE0_INVENTORY = ROOT / "docs" / "phase-0" / "EVIDENCE_INVENTORY.csv"
PHASE2_SPREAD = ROOT / "data" / "phase2" / "processed" / "historical_spread.csv"
PHASE2_BRIDGES = ROOT / "data" / "phase2" / "processed" / "earnings_bridges.csv"
PHASE2_DECISIONS = ROOT / "data" / "phase2" / "processed" / "adjustment_decisions.csv"
PHASE2_METRICS = ROOT / "data" / "phase2" / "processed" / "historical_credit_metrics.csv"
CUTOFF = date(2025, 12, 15)
ACCESS_DATE = "2026-09-09"
APPROVED_PHASE2_COMMIT = "4432dcbdbfaa0aa828420af3287262e355c451d0"
QUARTERS = tuple((fy, q) for fy in ("FY2024", "FY2025") for q in ("Q1", "Q2", "Q3", "Q4"))

SOURCE_FIELDS = (
    "source_id", "publisher", "document_title", "document_type", "source_url",
    "publication_date", "information_period", "access_date", "cutoff_status",
    "relevant_section", "redistribution_status", "local_path", "extract_sha256",
    "extract_bytes", "preservation_mode", "added_reason", "supported_driver_ids", "notes",
)
EVIDENCE_FIELDS = (
    "evidence_id", "topic", "evidence_type", "metric_name", "fiscal_year", "quarter",
    "period_start", "period_end", "observation_date", "publication_date", "frequency",
    "geography", "segment", "perimeter", "value", "units", "vintage", "source_ids",
    "historical_range_used", "relationship_to_quanex", "source_reference",
    "acceptance_status", "revision_risk", "claim", "limitations",
)
TREND_FIELDS = (
    "trend_id", "fiscal_year", "quarter", "period_start", "period_end", "frequency",
    "perimeter", "segment", "geography", "metric_name", "value", "units", "status",
    "classification", "source_ids", "input_ids", "calculation", "comparability_note", "notes",
)
DRIVER_FIELDS = (
    "driver_id", "driver_name", "category", "borrower_segment_or_geography",
    "supporting_evidence_ids", "source_ids", "historical_observation",
    "management_explanation", "analyst_interpretation", "confidence_level",
    "base_case_direction", "moderate_downside_mechanism", "severe_downside_mechanism",
    "primary_forecast_line", "secondary_forecast_lines", "cash_flow_transmission",
    "expected_timing", "duration", "potential_mitigation", "mitigation_cost",
    "mitigation_delay", "implementation_constraint", "potential_monitoring_metric",
    "warning_threshold_candidate", "potential_diligence_condition",
    "double_counting_relationships", "status", "owner_review_status",
    "monitoring_observability", "required_reporting_source",
)
ASSUMPTION_FIELDS = (
    "assumption_id", "driver_id", "forecast_line", "units", "proposed_low",
    "proposed_high", "proposed_direction_or_range", "starting_historical_reference",
    "evidence_ids", "source_ids", "assumption_role", "forecast_override_permitted",
    "calculation_method", "rationale", "confidence",
    "alternative_interpretation", "information_gap", "status", "owner_review_status",
)
SCENARIO_FIELDS = (
    "scenario_candidate_id", "driver_id", "forecast_line", "units",
    "moderate_low", "moderate_high", "moderate_timing", "moderate_duration",
    "severe_low", "severe_high", "severe_timing", "severe_duration",
    "evidence_ids", "source_ids", "range_conclusion", "transmission_mechanism",
    "overlap_control", "unmitigated_distribution_treatment",
    "mitigated_distribution_treatment", "limitations", "status", "owner_review_status",
)
MITIGATION_FIELDS = (
    "mitigation_id", "driver_ids", "action", "management_used_or_discussed",
    "historical_cash_reference", "potential_cash_benefit", "timing", "upfront_cost",
    "operational_consequence", "reversibility", "execution_risk", "lender_consent",
    "availability_status", "embedded_in_unmitigated_stress", "evidence_ids", "source_ids",
    "status", "owner_review_status", "notes",
)
GAP_FIELDS = (
    "gap_id", "description", "carried_from_phase", "affected_driver_ids", "source_ids",
    "forecast_limitation", "diligence_condition", "closing_condition",
    "covenant_limitation", "monitoring_requirement", "confidence_reduction",
    "potential_decision_blocker", "conservative_treatment", "status",
    "owner_review_status", "notes",
)
LEDGER_FIELDS = (
    "record_id", "output_file", "layer", "metric_or_item", "source_ids",
    "evidence_ids", "document_titles", "source_urls", "publication_dates",
    "classification", "owner_review_status", "notes",
)
OWNER_DECISION_FIELDS = (
    "decision_id", "record_type", "record_id", "decision_status",
    "owner_review_status", "approved_treatment", "remaining_limitation", "review_context",
)
VALID_UNITS = {
    "USD_millions", "percent", "basis_points", "days", "quarters", "months",
    "years", "thousand_units_SAAR", "USD_billions", "count", "text", "status",
}


class Phase3Error(RuntimeError):
    """A failure that makes the Phase 3 output unsafe to use."""


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise Phase3Error(f"Missing required input: {path.relative_to(ROOT)}")
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
        raise Phase3Error(f"Invalid decimal for {label}: {value!r}") from exc


def fmt(value: Decimal | str | int | None) -> str:
    if value is None or value == "":
        return ""
    result = format(dec(value), "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return result or "0"


def semis(values: Iterable[str]) -> str:
    return ";".join(dict.fromkeys(value for value in values if value))


def sha256_text(text: str) -> tuple[str, str]:
    payload = text.encode("utf-8")
    return hashlib.sha256(payload).hexdigest(), str(len(payload))


def ensure_unique(rows: list[dict[str, str]], field: str, label: str) -> None:
    values = [row[field] for row in rows]
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise Phase3Error(f"Duplicate {label}: {', '.join(duplicates)}")


def source_seed_rows() -> list[dict[str, str]]:
    base = [
        ("SRC-017", "Quanex Building Products Corporation", "Quanex FY2024 Q1 results release", "SEC 8-K exhibit / issuer release", "https://investors.quanex.com/news-releases/news-release-details/quanex-building-products-announces-first-quarter-2024-results", "2024-03-07", "Three months ended 2024-01-31", "Selected results; cash flow; net debt; sales analysis; selected segment data", "Quarterly seasonality and legacy perimeter", "DRV-001;DRV-003;DRV-005"),
        ("SRC-018", "Quanex Building Products Corporation", "Quanex FY2024 Q2 results release", "SEC 8-K exhibit", "https://www.sec.gov/Archives/edgar/data/1423221/000117184324003332/exh_991.htm", "2024-06-06", "Three and six months ended 2024-04-30", "Selected results; free cash flow; net debt; selected segment data", "Quarterly seasonality, volume, price and cash conversion", "DRV-001;DRV-002;DRV-003;DRV-005"),
        ("SRC-019", "Quanex Building Products Corporation", "Quanex FY2024 Q3 results release", "SEC 8-K exhibit", "https://www.sec.gov/Archives/edgar/data/1423221/000117184324005085/exh_991.htm", "2024-09-05", "Three and nine months ended 2024-07-31", "Selected results; free cash flow; net debt; selected segment data", "Last fully pre-Tyman quarter and seasonal cash generation", "DRV-001;DRV-003;DRV-005"),
        ("SRC-020", "Quanex Building Products Corporation", "Quanex FY2024 Q4 and full-year results release", "SEC 8-K exhibit", "https://www.sec.gov/Archives/edgar/data/1423221/000117184324006907/exh_991.htm", "2024-12-12", "Three and twelve months ended 2024-10-31", "Selected results; Tyman contribution; debt; liquidity; segment data", "First mixed-perimeter quarter and acquisition-driven debt step-up", "DRV-001;DRV-003;DRV-004;DRV-012"),
        ("SRC-021", "Quanex Building Products Corporation", "Quanex FY2025 Q1 results release", "SEC 8-K exhibit / issuer release", "https://investors.quanex.com/news-releases/news-release-details/quanex-building-products-announces-first-quarter-2025-results", "2025-03-10", "Three months ended 2025-01-31", "Selected results; cash flow; net debt; non-GAAP reconciliation", "Full post-Tyman seasonality and cash trough", "DRV-003;DRV-004;DRV-005;DRV-010"),
        ("SRC-022", "Quanex Building Products Corporation", "Quanex FY2025 Q3 results release", "SEC 8-K exhibit", "https://www.sec.gov/Archives/edgar/data/1423221/000117184325005746/exh_991.htm", "2025-09-04", "Three and nine months ended 2025-07-31", "Selected results; segment data; Mexico plant and synergy commentary", "Run-rate, integration execution and current-segment evidence", "DRV-001;DRV-002;DRV-003;DRV-004;DRV-005"),
        ("SRC-023", "U.S. Census Bureau and U.S. Department of Housing and Urban Development", "Monthly New Residential Construction, August 2025", "Original government statistical release", "https://www.census.gov/construction/nrc/pdf/newresconst_202508.pdf", "2025-09-17", "August 2025", "Release CB25-143; permits, starts and completions", "Latest housing-start release available by cutoff due subsequent release delay", "DRV-001"),
        ("SRC-024", "Joint Center for Housing Studies of Harvard University", "Remodeling Expected to Continue Slow but Steady Growth Into Next Year", "Research center dated release", "https://www.jchs.harvard.edu/blog/remodeling-expected-continue-slow-steady-growth-next-year", "2025-10-16", "Projection through 2026 Q3", "Leading Indicator of Remodeling Activity release", "Bounded repair-and-remodeling demand context", "DRV-001"),
        ("SRC-025", "Office for National Statistics", "Construction output in Great Britain: October 2025", "Original government statistical release", "https://www.ons.gov.uk/businessindustryandtrade/constructionindustry/bulletins/constructionoutputingreatbritain/october2025", "2025-12-12", "October 2025 and three months to October 2025", "Main points and data-quality notice", "U.K. new-work and private-housing repair/maintenance context", "DRV-001;DRV-011"),
    ]
    rows = [{
        "source_id": sid, "publisher": publisher, "document_title": title,
        "document_type": dtype, "source_url": url, "publication_date": pub,
        "information_period": info, "access_date": ACCESS_DATE, "cutoff_status": "ALLOWED",
        "relevant_section": section, "redistribution_status": "facts_only_with_attribution",
        "local_path": "data/phase3/raw/DRIVER_EVIDENCE.csv", "extract_sha256": "",
        "extract_bytes": "", "preservation_mode": "source_faithful_extract_and_reproducible_reference",
        "added_reason": reason, "supported_driver_ids": drivers,
        "notes": "Only material facts are retained; no full copyrighted document is copied.",
    } for sid, publisher, title, dtype, url, pub, info, section, reason, drivers in base]
    census = next(row for row in rows if row["source_id"] == "SRC-023")
    census["notes"] = (
        "August 2025 was the latest actual New Residential Construction release available "
        "at the 2025-12-15 cutoff. September and October 2025 estimates were not released "
        "until 2026-01-09 and are excluded from analytical evidence."
    )
    return rows


def evidence_seed_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add(topic: str, etype: str, metric: str, source_ids: str, reference: str,
            claim: str, *, fy: str = "", quarter: str = "", start: str = "",
            end: str = "", observation: str = "", publication: str = "",
            frequency: str = "event", geography: str = "Global", segment: str = "Consolidated",
            perimeter: str = "current_disclosure", value: str = "", units: str = "text",
            vintage: str = "", acceptance: str = "accepted", revision: str = "not_revisable",
            historical_range: str = "not_applicable",
            relationship: str = "direct_borrower_evidence", limitations: str = "") -> None:
        rows.append({
            "evidence_id": f"EVD-{len(rows) + 1:04d}", "topic": topic,
            "evidence_type": etype, "metric_name": metric, "fiscal_year": fy,
            "quarter": quarter, "period_start": start, "period_end": end,
            "observation_date": observation or end, "publication_date": publication,
            "frequency": frequency, "geography": geography, "segment": segment,
            "perimeter": perimeter, "value": value, "units": units,
            "vintage": vintage or (f"as_published_{publication}" if publication else "source_vintage"),
            "source_ids": source_ids, "historical_range_used": historical_range,
            "relationship_to_quanex": relationship, "source_reference": reference,
            "acceptance_status": acceptance, "revision_risk": revision,
            "claim": claim, "limitations": limitations,
        })

    # Current operating model and credit-relevant disclosures from the approved FY2025 10-K.
    operating = [
        ("business_model", "products", "Item 1, pp. 5-6", "Components include insulating-glass spacers, vinyl profiles, screens, metal and wood products, seals, hardware, solar sealants, cabinetry components and commercial access products."),
        ("business_model", "customer_channel", "Item 1, pp. 5-6", "Quanex supplies building-products OEMs, including window, door and cabinet manufacturers and distributors, plus commercial construction contractors."),
        ("business_model", "geographic_footprint", "Item 1, p. 5", "The primary customer base is in North America and the U.K.; operations also include Germany, Mexico, Canada and Italy."),
        ("business_model", "manufacturing_footprint", "Item 1, p. 5", "At October 31, 2025 Quanex operated 34 U.S. plants, seven U.K. plants, three in Mexico, two in Italy and one each in Germany and Canada."),
        ("business_model", "order_model", "Item 1, p. 5", "Products are generally made to customer specifications after order, allowing minimal finished-goods inventory at most sites while raw material buffers remain necessary."),
        ("business_model", "demand_drivers", "Item 1 and Risk Factors", "Residential remodeling/replacement and housing starts are the primary demand drivers; construction demand is cyclical, seasonal and interest-rate sensitive."),
        ("business_model", "seasonality", "MD&A, p. 22", "Winter weather tends to slow construction and installation of exterior building products."),
        ("business_model", "raw_materials", "Item 1, pp. 7-8", "Material inputs include PVC, epoxy, butyl, titanium dioxide, silicone, EPDM, polypropylene, aluminum, steel, stainless steel, zinc and hardwood/softwood."),
        ("business_model", "price_pass_through", "Market risk, p. 35", "Index and surcharge mechanisms mitigate many PVC, petroleum, hardwood and metal inputs, but coverage is incomplete and pricing updates have timing lags, including up to three months for hardwood."),
        ("business_model", "customer_concentration", "Note 3, p. 49", "One customer represented more than 10% of consolidated net sales and receivables in FY2023-FY2025."),
        ("business_model", "single_site_risk", "Risk Factors, p. 13", "One U.S. insulating-glass-spacer plant is a sole source, subject to disaster-recovery risk."),
        ("business_model", "current_segments", "MD&A, p. 21", "Current segments are Hardware Solutions, Extruded Solutions and Custom Solutions; they were adopted during FY2025 integration and prior-period disclosures were recast only where the company supplied them."),
        ("business_model", "capital_intensity", "Cash flows and commitments, pp. 30-34", "FY2025 capital expenditures were $62.642m and firm capital-project commitments were $8.3m; maintenance versus expansion spend was not disclosed."),
        ("business_model", "foreign_exchange", "Risk factors and market risk", "International operations create translation and transaction exposure; derivatives have been used, but the forecast sensitivity of operating cash flow is not quantified."),
    ]
    for topic, metric, ref, claim in operating:
        add(topic, "reported_fact", metric, "SRC-001", ref, claim, fy="FY2025",
            end="2025-10-31", observation="2025-10-31", publication="2025-12-12",
            frequency="annual", perimeter="full_post_tyman")

    qdata = {
        ("FY2024", "Q1"): ("2023-11-01", "2024-01-31", "legacy_pre_tyman", "SRC-017", "2024-03-07", {
            "revenue": "239.155", "gross_profit": "51.432", "company_adjusted_ebitda": "19.274",
            "cash_flow_from_operations": "3.854", "capital_expenditures": "-9.580",
            "free_cash_flow": "-5.726", "cash_and_cash_equivalents": "44.422", "total_debt_principal": "65.211"}),
        ("FY2024", "Q2"): ("2024-02-01", "2024-04-30", "legacy_pre_tyman", "SRC-018", "2024-06-06", {
            "revenue": "266.201", "gross_profit": "66.238", "company_adjusted_ebitda": "40.024",
            "cash_flow_from_operations": "33.091", "capital_expenditures": "-7.603",
            "free_cash_flow": "25.488", "cash_and_cash_equivalents": "56.149", "total_debt_principal": "55.217"}),
        ("FY2024", "Q3"): ("2024-05-01", "2024-07-31", "legacy_pre_tyman", "SRC-019", "2024-09-05", {
            "revenue": "280.345", "gross_profit": "70.904", "company_adjusted_ebitda": "42.035",
            "cash_flow_from_operations": "46.388", "capital_expenditures": "-6.252",
            "free_cash_flow": "40.136", "cash_and_cash_equivalents": "93.966", "total_debt_principal": "55.007"}),
        ("FY2024", "Q4"): ("2024-08-01", "2024-10-31", "mixed_three_months_tyman", "SRC-020", "2024-12-12", {
            "revenue": "492.161", "gross_profit": "117.050", "company_adjusted_ebitda": "81.050",
            "cash_flow_from_operations": "5.479", "capital_expenditures": "-13.651",
            "free_cash_flow": "-8.172", "cash_and_cash_equivalents": "97.744", "total_debt_principal": "776.926"}),
        ("FY2025", "Q1"): ("2024-11-01", "2025-01-31", "full_post_tyman", "SRC-021", "2025-03-10", {
            "revenue": "400.044", "gross_profit": "92.316", "company_adjusted_ebitda": "38.542",
            "cash_flow_from_operations": "-12.510", "capital_expenditures": "-11.624",
            "free_cash_flow": "-24.134", "cash_and_cash_equivalents": "49.982", "total_debt_principal": "764.306"}),
        ("FY2025", "Q2"): ("2025-02-01", "2025-04-30", "full_post_tyman", "SRC-016", "2025-06-05", {
            "revenue": "452.478", "gross_profit": "131.382", "company_adjusted_ebitda": "63.135",
            "cash_flow_from_operations": "28.497", "capital_expenditures": "-14.920",
            "free_cash_flow": "13.577", "cash_and_cash_equivalents": "62.626", "total_debt_principal": "784.977"}),
        ("FY2025", "Q3"): ("2025-05-01", "2025-07-31", "full_post_tyman", "SRC-022", "2025-09-04", {
            "revenue": "495.273", "gross_profit": "137.968", "company_adjusted_ebitda": "70.295",
            "cash_flow_from_operations": "60.656", "capital_expenditures": "-14.452",
            "free_cash_flow": "46.204", "cash_and_cash_equivalents": "66.272", "total_debt_principal": "733.694"}),
        ("FY2025", "Q4"): ("2025-08-01", "2025-10-31", "full_post_tyman", "SRC-002", "2025-12-11", {
            "revenue": "489.846", "gross_profit": "137.562", "company_adjusted_ebitda": "70.918",
            "cash_flow_from_operations": "88.254", "capital_expenditures": "-21.646",
            "free_cash_flow": "66.608", "cash_and_cash_equivalents": "76.018", "total_debt_principal": "703.869"}),
    }
    instant_metrics = {"cash_and_cash_equivalents", "total_debt_principal"}
    for (fy, quarter), (start, end, perimeter, sid, pub, values) in qdata.items():
        for metric, value in values.items():
            source_ids = sid
            reference = "Selected quarterly results, free-cash-flow or net-debt table"
            limitations = ""
            if fy == "FY2025" and quarter == "Q2" and metric == "company_adjusted_ebitda":
                source_ids = "SRC-002;SRC-016"
                reference = "FY2025 annual-release LTM bridge compared with original Q2 release"
                limitations = "Selected $63.135m from the latest within-cutoff annual bridge so quarters reconcile; original Q2 release showed $61.913m and the $1.222m difference is not explained."
            add("quarterly_trend", "reported_fact", metric, source_ids, reference,
                f"{fy} {quarter} {metric.replace('_', ' ')} was {value} {('USD millions')}.",
                fy=fy, quarter=quarter, start="" if metric in instant_metrics else start,
                end=end, observation=end, publication=pub, frequency="quarterly",
                perimeter=perimeter, value=value, units="USD_millions",
                revision="annual_recast_or_revision_possible" if "adjusted_ebitda" in metric else "interim_subject_to_year_end_reconciliation",
                limitations=limitations)
    add("quarterly_trend", "reported_fact", "company_adjusted_ebitda", "SRC-016",
        "Original FY2025 Q2 non-GAAP reconciliation", "The original FY2025 Q2 release reported adjusted EBITDA of $61.913m.",
        fy="FY2025", quarter="Q2", start="2025-02-01", end="2025-04-30",
        publication="2025-06-05", frequency="quarterly", perimeter="full_post_tyman",
        value="61.913", units="USD_millions", acceptance="superseded_for_annual_reconciliation",
        revision="visible_within_cutoff_presentation_difference",
        limitations="The later FY2025 annual release shows $63.135m for this quarter; cause of the $1.222m difference is not disclosed.")

    # Annual current-segment table: company-recast FY2024 and FY2025 only.
    segment_data = {
        "FY2024": {"Hardware Solutions": ("427.839", "51.404"), "Extruded Solutions": ("559.995", "112.189"), "Custom Solutions": ("309.441", "29.961"), "Unallocated Corporate & Other": ("-19.413", "-11.171")},
        "FY2025": {"Hardware Solutions": ("841.674", "88.800"), "Extruded Solutions": ("646.627", "123.398"), "Custom Solutions": ("388.210", "42.891"), "Unallocated Corporate & Other": ("-38.870", "-12.199")},
    }
    for fy, segments in segment_data.items():
        for segment, (revenue, ebitda) in segments.items():
            for metric, value in (("segment_revenue", revenue), ("segment_company_adjusted_ebitda", ebitda)):
                add("segment_trend", "reported_fact", metric, "SRC-002;SRC-001",
                    "FY2025 results release selected segment data; FY2025 10-K Note 17",
                    f"Company-recast {fy} {segment} {metric.replace('_', ' ')} was ${value}m.",
                    fy=fy, start=f"{int(fy[-4:])-1}-11-01", end=f"{fy[-4:]}-10-31",
                    publication="2025-12-12", frequency="annual", segment=segment,
                    perimeter="company_recast_current_segments", value=value, units="USD_millions",
                    revision="company_recast_within_cutoff",
                    limitations="Do not extend the current segment structure before FY2023 or treat the recast as a constant combined-company perimeter.")

    qualitative = [
        ("historical_driver", "organic_growth", "SRC-020", "FY2024 Q4 results summary", "FY2024 Q4 revenue rose 66.6% reported, but excluding Tyman declined 2.3%; full-year legacy revenue declined 5.0%, largely on volume.", "management_explanation"),
        ("historical_driver", "organic_growth", "SRC-016", "FY2025 Q2 results summary", "FY2025 Q2 revenue rose 70.0% reported, while excluding Tyman declined 1.4%, mainly on lower North American volume.", "management_explanation"),
        ("historical_driver", "organic_growth", "SRC-022", "FY2025 Q3 results summary", "FY2025 Q3 revenue rose 76.7% reported; excluding Tyman it increased 1.4% as pricing and tariff pass-throughs exceeded lower volume.", "management_explanation"),
        ("historical_driver", "organic_growth", "SRC-002", "FY2025 Q4 results summary", "FY2025 Q4 revenue declined 0.5%, mainly from lower volume; Extruded Solutions revenue declined 6.4% on lower volume.", "management_explanation"),
        ("historical_driver", "integration_synergy", "SRC-002", "FY2025 results commentary", "Management said integration was substantially complete, the original $30m synergy target was fully realized, and a path remained to about $45m over time.", "management_explanation"),
        ("historical_driver", "plant_execution", "SRC-002;SRC-022", "FY2025 Q3 and Q4 commentary", "Management identified an operational issue at a Mexico hardware plant and expected stabilization in the first half of FY2026.", "management_explanation"),
        ("historical_driver", "restructuring_cash", "SRC-001", "Note 1, p. 52", "FY2025 restructuring included $6.3m workforce alignment costs; $5.6m had been paid and $0.7m remained accrued, plus $3.9m of software disposal. Additional charges could occur.", "reported_fact"),
        ("historical_driver", "working_capital", "SRC-001", "FY2025 cash-flow statement", "FY2025 inventory released $23.553m of cash while receivables used $6.878m; FY2024 inventory released $33.484m while payables used $35.824m.", "reported_fact"),
        ("historical_driver", "capital_allocation", "SRC-001;SRC-002", "FY2025 cash-flow and net-debt tables", "FY2025 FCF was $102.255m, bank debt declined $75m, dividends used $14.889m and repurchases used $32.360m.", "reported_fact"),
        ("historical_driver", "impairment", "SRC-001", "Notes 7 and 17", "The $302.284m goodwill impairment affected all three segments, including two reporting units that were fully impaired.", "reported_fact"),
        ("historical_driver", "cash_flow_control", "SRC-001", "Item 9A", "The cash-flow preparation and review material weakness remained unremediated at October 31, 2025; no identified financial-statement misstatement or revision resulted.", "reported_fact"),
        ("historical_driver", "composite_adjustment", "SRC-002", "FY2025 adjusted EBITDA reconciliation", "The $10.263m transaction, advisory, reorganization and product-recall category was not publicly disaggregated.", "reported_fact"),
    ]
    for topic, metric, sources, reference, claim, etype in qualitative:
        add(topic, etype, metric, sources, reference, claim, fy="FY2025",
            end="2025-10-31", publication="2025-12-12" if "SRC-001" in sources else "2025-12-11",
            frequency="annual_or_event", perimeter="full_post_tyman",
            revision="management_explanation_not_independently_verified" if etype == "management_explanation" else "not_revisable",
            limitations="Management causation and completion statements are not independently verified." if etype == "management_explanation" else "")

    working_capital = [
        ("accounts_payable_history", "reported_fact", "Accounts payable was $124.404m at FY2024 year-end and $131.307m at FY2025 year-end.", "Balance growth spans a changing acquisition perimeter and does not establish payment timing."),
        ("accounts_payable_cost_proxy", "analyst_calculation", "Year-end accounts payable was 12.80% and 9.81% of annual cost of sales excluding D&A in FY2024 and FY2025.", "This is a balance-to-cost proxy, not DPO. Purchases are unavailable, and year-end balances plus the Tyman perimeter change limit comparability."),
        ("other_operating_current_asset_history", "analyst_calculation", "Other presented current assets were $35.034m in FY2024 and $36.151m in FY2025, or 2.74% and 1.97% of revenue.", "Residual balance grouping and acquisition perimeter changes limit use as a forecast range."),
        ("other_operating_current_liability_history", "analyst_calculation", "Other presented operating current liabilities were $110.243m in FY2024 and $107.231m in FY2025, or 8.63% and 5.84% of revenue.", "Residual balance grouping includes unlike accrued items and cannot be forecast as a funding plug."),
        ("payables_and_accrual_cash_movements", "reported_fact", "Accounts-payable cash movement was negative $35.824m in FY2024 and positive $3.313m in FY2025; accrued-liability movement was positive $6.250m and negative $9.657m.", "Cash-flow movements are not ending balances and should not be mixed with balance-to-driver ratios."),
        ("other_working_capital_cash_movements", "analyst_calculation", "Other operating working-capital movements were positive $12.942m in FY2024 and negative $7.451m in FY2025.", "The residual combines different accounts; missing components must not default to zero."),
    ]
    for metric, etype, claim, limitations in working_capital:
        add("historical_driver", etype, metric, "SRC-001",
            "Phase 2 historical spread; FY2025 10-K balance sheet and cash-flow statement",
            claim, fy="FY2024-FY2025", end="2025-10-31", observation="2025-10-31",
            publication="2025-12-12", frequency="annual", perimeter="acquisition_affected",
            limitations=limitations)

    industry = [
        ("housing_starts", "housing_starts_total", "1307", "thousand_units_SAAR", "United States", "2025-08-31", "2025-09-17", "SRC-023", "1.307m SAAR; -6.0% year over year", "indirect", "Housing starts were 1.307m SAAR in August 2025, down 6.0% year over year.", "Estimates carry sampling error and may be revised; August was the latest release available by the cutoff because later releases were delayed."),
        ("housing_starts", "single_family_starts", "890", "thousand_units_SAAR", "United States", "2025-08-31", "2025-09-17", "SRC-023", "890,000 SAAR; -7.0% from revised July", "indirect", "Single-family housing starts were 890,000 SAAR in August 2025, down 7.0% from revised July.", "Month-to-month change had a reported confidence interval and the series is revisable."),
        ("housing_starts", "building_permits_total", "1312", "thousand_units_SAAR", "United States", "2025-08-31", "2025-09-17", "SRC-023", "1.312m SAAR; -11.1% year over year", "contextual", "Building permits were 1.312m SAAR in August 2025, down 11.1% year over year.", "Permits include multifamily units and are contextual rather than a direct Quanex volume predictor."),
        ("remodeling", "lira_growth_early_2026", "2.4", "percent", "United States", "2026-03-31", "2025-10-16", "SRC-024", "2.4% early 2026 to 1.9% by 2026 Q3", "contextual", "The October 2025 LIRA projected 2.4% year-over-year remodeling-spending growth in early 2026.", "A model-based nominal-spending forecast, not Quanex volume; publication vintage is preserved."),
        ("remodeling", "lira_growth_2026_q3", "1.9", "percent", "United States", "2026-09-30", "2025-10-16", "SRC-024", "2.4% early 2026 to 1.9% by 2026 Q3", "contextual", "The October 2025 LIRA projected remodeling-spending growth easing to 1.9% by 2026 Q3.", "A model-based nominal-spending forecast, not Quanex volume; inflation and mix may differ."),
        ("uk_construction", "construction_output_three_month_change", "-0.3", "percent", "Great Britain", "2025-10-31", "2025-12-12", "SRC-025", "-0.3% three months to October 2025", "contextual", "Total construction output fell 0.3% in the three months to October 2025.", "ONS disclosed a public-housing data error and future revisions; this exact release vintage is retained."),
        ("uk_construction", "private_housing_repair_maintenance_three_month_change", "-2.3", "percent", "Great Britain", "2025-10-31", "2025-12-12", "SRC-025", "-2.3% three months to October 2025", "indirect", "Private-housing repair and maintenance fell 2.3% in the three months to October 2025.", "Context for U.K. exposure; no direct statistical elasticity to Quanex was tested."),
        ("uk_construction", "new_work_three_month_change", "0.1", "percent", "Great Britain", "2025-10-31", "2025-12-12", "SRC-025", "+0.1% three months to October 2025", "contextual", "New construction work grew 0.1% in the three months to October 2025.", "Aggregate sector series; product and customer mix differ from Quanex."),
    ]
    for topic, metric, value, units, geo, obs, pub, sid, historical_range, relationship, claim, limitations in industry:
        add("industry_indicator", "official_statistic" if sid != "SRC-024" else "external_forecast",
            metric, sid, "Dated release main points", claim, observation=obs, publication=pub,
            frequency="monthly" if sid != "SRC-024" else "quarterly_projection",
            geography=geo, segment="Relevant end market", perimeter="external_indicator",
            value=value, units=units, vintage=f"release_vintage_{pub}",
            historical_range=historical_range, relationship=relationship,
            revision="revisable_flagged" if sid in {"SRC-023", "SRC-025"} else "forecast_vintage_locked",
            limitations=limitations)
    return rows


def attach_extract_hashes(sources: list[dict[str, str]], evidence: list[dict[str, str]]) -> None:
    for source in sources:
        sid = source["source_id"]
        selected = [row for row in evidence if sid in row["source_ids"].split(";")]
        payload = "\n".join("|".join(row[field] for field in EVIDENCE_FIELDS) for row in selected)
        digest, size = sha256_text(payload)
        source["extract_sha256"] = digest
        source["extract_bytes"] = size


def build_trends(evidence: list[dict[str, str]]) -> list[dict[str, str]]:
    accepted = [row for row in evidence if row["topic"] in {"quarterly_trend", "segment_trend"}
                and row["acceptance_status"] == "accepted"]
    rows: list[dict[str, str]] = []
    for item in accepted:
        rows.append({
            "trend_id": f"TRD-{len(rows) + 1:04d}", "fiscal_year": item["fiscal_year"],
            "quarter": item["quarter"], "period_start": item["period_start"],
            "period_end": item["period_end"], "frequency": item["frequency"],
            "perimeter": item["perimeter"], "segment": item["segment"],
            "geography": item["geography"], "metric_name": item["metric_name"],
            "value": item["value"], "units": item["units"], "status": "supported",
            "classification": "reported", "source_ids": item["source_ids"],
            "input_ids": item["evidence_id"], "calculation": "",
            "comparability_note": "No cross-perimeter growth inference." if "tyman" in item["perimeter"] else "Company-recast segment disclosure only.",
            "notes": item["limitations"],
        })

    by_q: dict[tuple[str, str], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        if row["quarter"]:
            by_q[(row["fiscal_year"], row["quarter"])][row["metric_name"]] = row
    for key in QUARTERS:
        values = by_q[key]
        required = {"revenue", "gross_profit", "company_adjusted_ebitda", "cash_flow_from_operations", "capital_expenditures", "free_cash_flow"}
        missing = required - values.keys()
        if missing:
            raise Phase3Error(f"Quarter {key} missing {sorted(missing)}")
        for metric, numerator_name, denominator_name in (
            ("gross_margin", "gross_profit", "revenue"),
            ("company_adjusted_ebitda_margin", "company_adjusted_ebitda", "revenue"),
            ("fcf_to_company_adjusted_ebitda", "free_cash_flow", "company_adjusted_ebitda"),
        ):
            numerator = dec(values[numerator_name]["value"])
            denominator = dec(values[denominator_name]["value"])
            value = numerator / denominator * 100
            template = values[numerator_name]
            rows.append({
                "trend_id": f"TRD-{len(rows) + 1:04d}", "fiscal_year": key[0],
                "quarter": key[1], "period_start": template["period_start"],
                "period_end": template["period_end"], "frequency": "quarterly",
                "perimeter": template["perimeter"], "segment": "Consolidated",
                "geography": "Global", "metric_name": metric, "value": fmt(value),
                "units": "percent", "status": "calculated", "classification": "analyst_calculation",
                "source_ids": semis(values[numerator_name]["source_ids"].split(";") + values[denominator_name]["source_ids"].split(";")),
                "input_ids": f"{values[numerator_name]['trend_id']};{values[denominator_name]['trend_id']}",
                "calculation": f"{numerator_name} / {denominator_name} * 100",
                "comparability_note": template["comparability_note"],
                "notes": "Diagnostic only; company-adjusted EBITDA is not lender-normalized or contractual EBITDA.",
            })
    return rows


def owner_decision_rows() -> list[dict[str, str]]:
    seed = [
        ("assumption", "ASM-001", "owner_reviewed_range", "Underlying volume -2% to +1% calibration range", "Not a period-by-period forecast"),
        ("assumption", "ASM-002", "owner_reviewed_range", "Price/mix 0% to +1% calibration range", "Not a period-by-period forecast"),
        ("assumption", "ASM-003", "owner_reviewed_range", "Gross margin 26% to 28% as the primary gross-profit driver", "Operating costs must generate EBITDA"),
        ("assumption", "ASM-004", "owner_reviewed_methodology", "Lender-normalized EBITDA margin 12% to 13% as a validation band", "Must not override the operating build"),
        ("assumption", "ASM-005", "owner_reviewed_range", "DSO 40 to 43 days", "Periodization remains for forecast construction"),
        ("assumption", "ASM-006", "owner_reviewed_range", "DIO 70 to 75 days", "Periodization remains for forecast construction"),
        ("assumption", "ASM-007", "owner_reviewed_range", "Total capex 3% to 4% of revenue", "Maintenance, integration and expansion split remains unresolved"),
        ("assumption", "ASM-008", "owner_reviewed_range", "Zero base credit for incremental unrealized synergies", "Verified future realization may be reconsidered"),
        ("assumption", "ASM-009", "owner_reviewed_range", "At least $0.7m of restructuring cash", "Upper bound remains pending information"),
        ("assumption", "ASM-010", "owner_reviewed_range", "Repurchases $0m to $10m as a financial-policy range", "Not fixed; financing restrictions must be established in Phase 4"),
        ("assumption", "ASM-011", "owner_reviewed_range", "Dividends $14m to $15m", "Future Board action remains uncommitted"),
        ("assumption", "ASM-012", "owner_reviewed_methodology", "Zero-basis-point reference relative to the Phase 4 closing rate", "Not a zero interest-rate assumption"),
        ("assumption", "ASM-013", "pending_information", "No numerical FX base credit", "Exposure and hedge schedules remain unavailable"),
        ("assumption", "ASM-014", "owner_reviewed_methodology", "Qualitative cash-flow reporting limitation and monitoring item", "Not a numeric forecast plug"),
        ("assumption", "ASM-015", "pending_information", "Accounts-payable forecast method to be resolved in Phase 5", "DPO is unavailable because purchases are not disclosed"),
        ("assumption", "ASM-016", "pending_information", "Other operating working-capital method to be resolved in Phase 5", "Must not become a funding plug or zero"),
        ("scenario", "SCN-001", "owner_reviewed_range", "Moderate/severe volume calibration", "No scenario has been run"),
        ("scenario", "SCN-002", "owner_reviewed_range", "Moderate/severe gross-margin calibration", "Includes volume-related fixed-cost deleverage"),
        ("scenario", "SCN-003", "owner_reviewed_range", "Moderate/severe DSO calibration", "No scenario has been run"),
        ("scenario", "SCN-004", "owner_reviewed_range", "Moderate/severe DIO calibration", "No scenario has been run"),
        ("scenario", "SCN-005", "owner_reviewed_range", "Moderate/severe execution-delay calibration", "Margin effect remains in SCN-002"),
        ("scenario", "SCN-006", "owner_reviewed_range", "Moderate/severe funding sensitivity", "Phase 4 closing rate and hedge exposure still control"),
        ("scenario", "SCN-007", "owner_reviewed_methodology", "Both unmitigated cases retain selected base distributions", "Distribution reductions occur only in mitigated cases"),
        ("scenario", "SCN-008", "pending_information", "Capex stress method preserves maintenance and safety floor", "Project-level split is unavailable"),
        ("scenario", "SCN-009", "pending_information", "Payables and other operating working-capital stress method", "Numeric ranges await a defensible Phase 5 forecast method"),
    ]
    seed.extend(("mitigation", f"MIT-{number:03d}", "owner_reviewed_methodology",
                 "Owner-reviewed mitigation classification", "Feasibility limits and separate-case treatment remain")
                for number in range(1, 9))
    return [{
        "decision_id": f"ORD-{index:03d}", "record_type": record_type,
        "record_id": record_id, "decision_status": status,
        "owner_review_status": "owner_reviewed", "approved_treatment": treatment,
        "remaining_limitation": limitation,
        "review_context": "Governing Work Phase 3 owner-review revision",
    } for index, (record_type, record_id, status, treatment, limitation) in enumerate(seed, 1)]


def driver_rows(evidence: list[dict[str, str]]) -> list[dict[str, str]]:
    eids = {row["metric_name"]: row["evidence_id"] for row in evidence}
    def ids(*metrics: str) -> str:
        return semis(eids[metric] for metric in metrics if metric in eids)
    seed = [
        ("DRV-001", "End-market volume and demand", "revenue", "All segments; U.S., U.K. and Europe", ids("housing_starts_total", "building_permits_total", "lira_growth_2026_q3", "private_housing_repair_maintenance_three_month_change", "organic_growth"), "SRC-001;SRC-020;SRC-016;SRC-022;SRC-002;SRC-023;SRC-024;SRC-025", "Legacy revenue fell 5.0% in FY2024; ex-Tyman quarterly movement was -1.4% in FY2025 Q2, +1.4% in Q3, and Q4 consolidated revenue fell 0.5%. U.S. August starts and permits were down 6.0% and 11.1% year over year.", "Management attributed weakness mainly to lower volume, consumer confidence, affordability and high rates.", "Demand was soft rather than in clear recovery; acquisition-created reported growth is not organic.", "high", "Flat to slightly down underlying volume until evidence improves.", "Volume 5%-8% below base for four quarters.", "Volume 12%-18% below base for six to eight quarters.", "revenue", "receivables;inventory;gross_margin;EBITDA", "Lower shipments reduce EBITDA; receivables may release initially, while poor scheduling can trap inventory.", "immediate", "cyclical; multi-quarter", "Pricing, cost control, inventory reduction", "Potential margin/customer trade-off", "one to two quarters", "Customer demand, weather and affordability are outside management control.", "organic_or_ex_tyman_revenue_change", "below -5% year over year", "Demand evidence by segment and geography", "Volume shock includes normal fixed-cost deleverage; do not add the same deleverage again in DRV-003.", "proposed", "pending_owner_approval"),
        ("DRV-002", "Price, mix and raw-material pass-through", "revenue_and_margin", "Hardware, Extruded and Custom", ids("price_pass_through", "raw_materials", "organic_growth"), "SRC-001;SRC-018;SRC-022;SRC-002", "Pass-throughs helped FY2025 Q3 ex-Tyman sales despite lower volume; annual segment bridges show both favorable and unfavorable price/index effects.", "Management describes index, surcharge and base-price mechanisms with incomplete coverage and lags.", "Pricing can offset input inflation but is not a durable substitute for volume and can lag by up to three months.", "medium", "Broadly neutral to modestly positive price/mix, not volume growth.", "Lagged recovery of inflation and tariff costs compresses margin.", "Incomplete recovery plus adverse mix compounds sustained volume pressure.", "revenue", "cost_of_sales;gross_margin;working_capital", "Input costs precede customer recovery, using cash and reducing gross profit.", "one to three months", "while input shock persists", "Indexing, surcharges and general price increases", "Commercial concessions or share loss", "up to three months", "Not all customers and commodities are covered.", "price_cost_lag_and_segment_mix", "gross-margin decline over 150 bps with stable volume", "Customer/index schedules and commodity coverage", "Do not count tariff pass-through as both price growth and margin expansion.", "proposed", "pending_owner_approval"),
        ("DRV-003", "Gross margin, utilization and fixed-cost absorption", "margin", "Manufacturing network", ids("seasonality", "plant_execution", "capital_intensity"), "SRC-001;SRC-017;SRC-018;SRC-019;SRC-020;SRC-002", "Quarterly gross margin ranged from 21.5% to 25.3% in pre-Tyman FY2024 and 23.1% to 29.0% in full post-Tyman FY2025; Q1 was the seasonal low in both years.", "Management cited cost control, raw-material deflation, synergies, lower volume and Mexico operational issues.", "FY2025 margin improvement has acquisition, mix and synergy effects; it is not a proven through-cycle level.", "medium", "Use a bounded margin range below peak quarters.", "150-250 bps compression inclusive of volume deleverage.", "300-450 bps compression with persistent disruption.", "gross_margin", "EBITDA;inventory;cash_flow_from_operations", "Lower absorption raises unit cost and may create inventory inefficiency.", "same quarter as volume", "four to eight quarters", "Cost controls and site actions", "Restructuring cash and service risk", "one to four quarters", "Plant changes require execution before savings recur.", "gross_margin_and_plant_service", "gross margin below 25% or missed service levels", "Plant-level utilization and bridge of FY2025 improvement", "Margin scenario must state that fixed-cost deleverage is included, not stacked with DRV-001.", "proposed", "pending_owner_approval"),
        ("DRV-004", "Tyman integration, synergy and plant stabilization", "integration", "All segments; Mexico Hardware plant", ids("integration_synergy", "plant_execution", "impairment"), "SRC-001;SRC-002;SRC-022", "Management said $30m of original synergies were realized and held a path to $45m; a Mexico hardware plant still required stabilization; $302.284m of goodwill was impaired.", "Integration was described as substantially complete and plant stabilization expected in FY2026 H1.", "Do not credit the remaining $15m until realized; the impairment materially weakens confidence in acquisition forecasts.", "low_to_medium", "No incremental synergy credit beyond evidenced run rate.", "Recovery delayed two to four quarters; incremental costs remain unquantified.", "Disruption persists six to eight quarters, with remediation cash and customer loss risk.", "EBITDA", "revenue;gross_margin;restructuring_cash;capex", "Missed output and extra labor/freight reduce EBITDA and consume cash.", "immediate", "through stabilization", "Dedicated integration resources and plant remediation", "Not disclosed", "several quarters", "Benefits depend on site execution and customer retention.", "realized_synergies_and_service_levels", "less than 80% of stated remaining milestones on time", "Monthly plant KPI pack and synergy bridge", "Do not count synergies both in base margin and a separate addback; no credit for unverified future savings.", "proposed", "pending_owner_approval"),
        ("DRV-005", "Working-capital and inventory volatility", "cash_conversion", "Consolidated", ids("working_capital", "order_model"), "SRC-001;SRC-017;SRC-018;SRC-019;SRC-020;SRC-021;SRC-016;SRC-022;SRC-002", "Phase 2 DSO was 42.25 days in FY2024 and 40.03 in FY2025; DIO was 70.30 and 72.22 days. FY2025 Q1 FCF was negative $24.134m before recovery later in the year.", "Management emphasizes working-capital management; Q1 is historically a net-borrowing period.", "Average-balance ratios remain acquisition-distorted, and quarterly cash generation is highly seasonal.", "medium", "Hold DSO near 40-43 and DIO near 70-75 pending post-Tyman history.", "DSO +5 days and DIO +10 days over four quarters.", "DSO +15 and DIO +25 days over six to eight quarters.", "accounts_receivable", "inventory;accounts_payable;cash_flow_from_operations;revolver", "Longer collections and inventory holding consume cash and increase revolver needs.", "same quarter as stress", "until balances normalize", "Collections focus and inventory reduction", "Potential service disruption or discounting", "one to two quarters", "PPA, seasonality and changed perimeter limit history.", "DSO_DIO_and_quarterly_CFO", "DSO above 45 or DIO above 80", "Monthly working-capital bridge by segment", "Do not separately shock total working capital if DSO and DIO shocks already capture it.", "proposed", "pending_owner_approval"),
        ("DRV-006", "Maintenance versus integration and expansion capex", "capital_expenditure", "Consolidated", ids("capital_intensity"), "SRC-001", "FY2025 capex was $62.642m, 3.41% of revenue, versus $37.086m in FY2024; maintenance versus discretionary spend is not disclosed.", "Management expects to fund capital projects from operations or the revolver.", "A maintenance floor cannot be set from public information and capex cannot be assumed fully removable.", "low", "Use total capex as reference; separate categories only after diligence.", "Defer only verified discretionary projects.", "Preserve an owner-approved maintenance and safety floor; no unsupported zero capex.", "capital_expenditures", "free_cash_flow;revolver;plant_execution", "Capex is a direct cash use; over-deferral can impair service and savings.", "annual and project-specific", "multi-year", "Defer expansion/integration projects where supportable", "Lost growth or delayed savings", "project-specific", "Maintenance, safety and committed projects are not removable.", "capex_by_category_and_commitments", "capex below approved maintenance floor", "Maintenance/expansion/integration schedule", "Capex reductions cannot also be counted as integration savings.", "pending_information", "pending_owner_approval"),
        ("DRV-007", "Adjustment quality and restructuring cash", "earnings_quality", "Consolidated", ids("composite_adjustment", "restructuring_cash"), "SRC-001;SRC-002", "$10.263m of FY2025 adjustments remains an inseparable composite; $0.7m workforce accrual remained and future restructuring charges were possible.", "Management labels the categories as transaction, advisory, reorganization, recall and restructuring.", "Lender EBITDA acceptance does not remove cash; unidentified recall/reorganization costs can recur.", "low", "No base addback for the composite; include identified cash requirements when known.", "Recovery delayed with additional unquantified cash cost.", "Persistent cost and customer-remediation cash drain.", "restructuring_and_integration_costs", "EBITDA;cash_flow_from_operations;free_cash_flow", "Cash payments reduce liquidity even if excluded from lender-normalized earnings.", "near term", "until programs close", "Complete programs and document savings", "Cash severance, systems and recall costs", "one to four quarters", "Public disclosure lacks invoices and category detail.", "cash_adjustments_and_completion", "new composite charges or accrual growth", "Disaggregated schedule and cash roll-forward", "Never reverse historical cash outflows when normalizing EBITDA.", "pending_information", "pending_owner_approval"),
        ("DRV-008", "Acquisition valuation and impairment signal", "business_risk", "All three current segments", ids("impairment"), "SRC-001", "$302.284m of goodwill was impaired in FY2025; two reporting units were fully impaired.", "Company attributed operating headwinds to softer markets and execution while maintaining the acquisition thesis.", "The noncash addback is mathematically accepted in Phase 2, but the magnitude is an adverse forecasting and asset-quality signal.", "high", "No direct cash addback change; reduce confidence in growth and terminal assumptions.", "Weaker margin/revenue realization than management case.", "Persistent underperformance and further asset-quality pressure.", "EBITDA", "revenue;capex;structure;monitoring", "No immediate cash use, but weak performance reduces debt repayment capacity.", "ongoing", "multi-year", "Operational remediation and portfolio review", "Potential restructuring or sale costs", "long", "Impairment itself does not quantify future cash impact.", "segment_performance_vs_underwriting_case", "two consecutive quarters below approved margin plan", "Reporting-unit performance and valuation bridge", "Do not add impairment to cash or treat its reversal as removal of risk.", "proposed", "pending_owner_approval"),
        ("DRV-009", "Cash-flow reporting-control remediation", "reporting_quality", "Consolidated", ids("cash_flow_control"), "SRC-001", "The cash-flow control material weakness persisted at FY2025 year-end; no identified misstatement or revision was reported.", "Management expects remediation before FY2026 year-end.", "Confidence in forecast cash-flow classification and close controls is reduced until testing proves remediation.", "high", "Retain reported cash facts but require enhanced validation.", "More frequent reconciliation and reporting-condition controls.", "Potential delayed/qualified reporting and covenant-information risk.", "cash_flow_from_operations", "all_cash_flow_lines;covenant_reporting", "Control failure can delay detection or reporting of cash errors.", "immediate", "until remediation is tested", "Remediation plan and audit-committee oversight", "Internal resource and systems cost", "at least sufficient operating period", "Completion date is a management expectation, not proof.", "control_testing_status_and_audit_findings", "missed remediation milestone or new deficiency", "Detailed plan, test results and auditor update", "Do not model a known misstatement; use a confidence and monitoring consequence.", "pending_information", "pending_owner_approval"),
        ("DRV-010", "Debt reduction versus distributions", "financial_policy", "Consolidated", ids("capital_allocation"), "SRC-001;SRC-002", "FY2025 bank debt fell $75m, but dividends and repurchases used $47.249m combined; Q1 and Q2 included $30.892m of repurchases while leverage remained elevated.", "Management listed debt repayment, growth and opportunistic repurchases as priorities.", "Distributions are a controllable cash use but were not subordinated entirely to deleveraging.", "high", "Use the owner-reviewed base financial-policy ranges without treating them as fixed period forecasts.", "Retain the selected base distributions in the unmitigated moderate case; suspension is a separate mitigation.", "Retain the selected base distributions in the unmitigated severe case; no discretionary distributions is a separate severe mitigation.", "share_repurchases", "dividends;free_cash_flow;debt_repayment;revolver", "Distributions directly reduce cash available for debt paydown.", "immediate", "while leverage elevated", "Board can suspend distributions", "Shareholder and signaling impact", "one quarter", "Board discretion; not committed at cutoff; Phase 4 financing terms may impose different restrictions.", "distributions_and_bank_debt_reduction", "repurchases while lender leverage headroom narrows", "Distribution blocker or leverage-based policy", "Do not embed suspended distributions in unmitigated stress cash flow; structure-specific restrictions must come from Phase 4.", "owner_reviewed_methodology", "owner_reviewed"),
        ("DRV-011", "Geography and foreign exchange", "geography_fx", "U.K., Europe, Mexico and Canada", ids("geographic_footprint", "foreign_exchange", "private_housing_repair_maintenance_three_month_change"), "SRC-001;SRC-025", "Quanex has material non-U.S. operations; U.K. private-housing repair/maintenance fell 2.3% in the latest pre-cutoff three-month release.", "Management cites currency volatility and uses derivatives for some exposures.", "Translation, transaction and local-demand effects should remain separate; public data do not support a precise EBITDA elasticity.", "low_to_medium", "Use constant-currency operating drivers and a separately disclosed translation diagnostic later.", "Adverse local demand; FX sensitivity pending exposure data.", "Sustained U.K./European contraction plus adverse translation; magnitude pending.", "revenue", "gross_margin;cash;debt", "Local-currency earnings translate differently and foreign cash may not be fully accessible.", "quarterly", "multi-quarter", "Natural hedges and derivatives", "Hedge premiums and basis risk", "instrument-specific", "Currency and entity exposure is not fully public.", "constant_currency_growth_and_foreign_cash", "unhedged move or local decline beyond approved case", "Currency exposure and hedge schedule", "Do not count local-demand decline and FX translation as the same revenue shock.", "pending_information", "pending_owner_approval"),
        ("DRV-012", "Floating-rate and refinancing sensitivity", "funding", "Consolidated", ids("capital_allocation"), "SRC-001;SRC-003;SRC-016", "Facilities are floating-rate; FY2025 weighted-average borrowing cost was 6.83%, maturity is August 1, 2029, and the assumed January 2026 covenant maximum is 3.25x absent another qualifying step-up.", "Management reported compliance and liquidity at FY2025 year-end.", "Rate shocks affect cash interest, while restricted refinancing affects structure and maturity risk; neither proves default.", "high", "Use contractual benchmark/spread mechanics and closing debt when available.", "+100 bps funding cost; refinancing remains available but costlier.", "+200 bps plus restricted refinancing; no assumed waiver or refinance proceeds.", "cash_interest", "free_cash_flow;debt_repayment;covenant_headroom;maturity", "Higher cash interest directly reduces FCF and debt repayment.", "next reset", "while rates remain high", "Debt repayment or hedging", "Cash use, hedge premium or break cost", "one quarter or hedge-specific", "Closing balance, exact rate, hedges and fees remain unknown.", "cash_interest_and_covenant_headroom", "headroom below owner-approved threshold", "Closing debt, SOFR election, hedge and covenant certificate", "Do not double count rate-driven housing demand in DRV-001 and debt cash interest in DRV-012 without separate lines.", "pending_information", "pending_owner_approval"),
        ("DRV-013", "Payables and other operating working capital", "cash_conversion", "Consolidated", ids("accounts_payable_history", "accounts_payable_cost_proxy", "other_operating_current_asset_history", "other_operating_current_liability_history", "payables_and_accrual_cash_movements", "other_working_capital_cash_movements"), "SRC-001", "FY2024/FY2025 accounts payable was $124.404m/$131.307m; the end-balance-to-cost-of-sales proxy was 12.80%/9.81%. Other operating current-asset and liability balances and their cash movements were volatile and acquisition-affected.", "No sufficiently granular public purchases, accrual or other working-capital forecast method was provided.", "DPO is not determinable because purchases are unavailable. Phase 5 must select separate, traceable balance-to-driver relationships; no component may default to zero or become a funding plug.", "low", "Keep accounts payable, accrued operating liabilities, and other operating current assets/liabilities pending until a defensible Phase 5 method is approved.", "Apply a separate adverse cash-flow treatment only after balance-driver ranges are approved; do not substitute a DSO/DIO or blanket working-capital shock.", "Apply a larger but separately supported adverse cash-flow treatment; no unsupported numeric shock or zero balance.", "accounts_payable", "accrued_operating_liabilities;other_operating_current_assets;other_operating_current_liabilities;cash_flow_from_operations;revolver", "Lower payables/accruals or higher other operating assets consume cash and increase revolver use; the reverse can release cash but cannot be assumed as a plug.", "same period as operating activity", "until balances normalize", "Supplier-term and accrual management", "Potential supplier, service or control consequences", "one to several quarters", "Purchases and account-level drivers are unavailable; cost of sales is only a labeled proxy, not DPO.", "payables_accruals_and_other_operating_working_capital", "pending until required borrower schedule establishes thresholds", "Monthly balance and cash-flow bridge with purchases, payables, accruals and other operating items", "Keep separate from DSO/DIO and avoid a duplicate total-working-capital shock.", "pending_information", "owner_reviewed"),
    ]
    rows = [dict(zip(DRIVER_FIELDS, row)) for row in seed]
    monitoring = {
        "DRV-001": ("available_through_required_borrower_reporting", "Quarterly segment/geography comparable-volume bridge; public releases may be incomplete"),
        "DRV-002": ("available_through_required_borrower_reporting", "Quarterly price/volume/mix and index-pass-through bridge by segment"),
        "DRV-003": ("available_through_required_borrower_reporting", "Monthly plant utilization, service-level and consolidated gross-margin reporting"),
        "DRV-004": ("dependent_on_private_diligence", "Monthly integration milestone, realized-synergy and plant-service KPI package"),
        "DRV-005": ("available_through_required_borrower_reporting", "Monthly receivables/inventory aging and average-balance DSO/DIO schedule"),
        "DRV-006": ("dependent_on_private_diligence", "Project-level maintenance, safety, integration and expansion capex schedule"),
        "DRV-007": ("available_through_required_borrower_reporting", "Monthly adjustment, accrual and cash-payment roll-forward"),
        "DRV-008": ("available_through_required_borrower_reporting", "Quarterly reporting-unit performance versus approved underwriting case"),
        "DRV-009": ("available_through_required_borrower_reporting", "Management certification, remediation milestones, testing evidence and auditor updates"),
        "DRV-010": ("available_through_required_borrower_reporting", "Monthly distributions, cash and funded-debt report; public statements are lagged"),
        "DRV-011": ("dependent_on_private_diligence", "Currency-level revenue, cost, debt, cash and hedge exposure schedule"),
        "DRV-012": ("available_through_required_borrower_reporting", "Compliance certificate, covenant calculation, accessible-liquidity and borrowing-base report"),
        "DRV-013": ("available_through_required_borrower_reporting", "Monthly purchases, payables, accruals and other operating working-capital balance/cash bridge"),
    }
    for row in rows:
        row["monitoring_observability"], row["required_reporting_source"] = monitoring[row["driver_id"]]
        if row["driver_id"] not in {"DRV-010", "DRV-013"}:
            row["status"] = "pending_information" if row["driver_id"] in {"DRV-006", "DRV-007", "DRV-009", "DRV-011", "DRV-012"} else "owner_reviewed_methodology"
            row["owner_review_status"] = "owner_reviewed"
    return rows


def assumption_rows(drivers: list[dict[str, str]], evidence: list[dict[str, str]],
                    decisions: list[dict[str, str]]) -> list[dict[str, str]]:
    by_driver = {row["driver_id"]: row for row in drivers}
    seed = [
        ("ASM-001", "DRV-001", "underlying_volume", "percent", "-2", "1", "-2% to +1% year over year", "FY2024 legacy -5.0%; FY2025 ex-Tyman Q2 -1.4%, Q3 +1.4%, Q4 total -0.5%", "Apply segment-level volume only after perimeter is fixed.", "Soft indicators and borrower commentary do not support a rebound assumption.", "medium", "Remodeling nominal spend remains positive, but may not translate to units.", "No full-year organic bridge by current segment."),
        ("ASM-002", "DRV-002", "price_and_mix", "percent", "0", "1", "0% to +1%", "FY2025 Q3 tariff/pricing pass-through offset lower volume", "Separate unit volume from price/mix.", "Allows modest recovery without treating pass-through as organic units.", "low_to_medium", "Price could be negative where indexed input costs fall.", "Customer-level index coverage and tariff bridge missing."),
        ("ASM-003", "DRV-003", "gross_margin", "percent", "26", "28", "26% to 28%", "FY2025 annual 27.2%; quarterly 23.1%-29.0%", "Apply to revenue after volume/price; range contains the annual result below the peak.", "Recognizes Q1 seasonality and uncertain integration benefit.", "medium", "A segment build may produce a different consolidated range.", "Plant-level and segment cost bridges missing."),
        ("ASM-004", "DRV-003", "calculated_lender_normalized_ebitda_margin_validation", "percent", "12", "13", "12% to 13% validation band", "FY2025 Phase 2 lender-base margin 12.26%; company-adjusted margin 13.22%", "Calculate EBITDA from revenue, gross margin, operating expenses and accepted adjustments; compare the result with this band and flag any result outside it.", "The band is a reasonableness check and cannot override the authoritative operating build.", "medium", "A supported operating build may fall outside the band and must be escalated rather than forced back inside it.", "No post-integration through-cycle history."),
        ("ASM-005", "DRV-005", "days_sales_outstanding", "days", "40", "43", "40 to 43 days", "FY2024 42.25; FY2025 40.03", "Use average-balance convention consistent with Phase 2.", "Keeps the base inside observed mixed/post-Tyman values.", "medium", "Customer/mix changes may alter the stable level.", "Only two acquisition-affected annual observations."),
        ("ASM-006", "DRV-005", "days_inventory_outstanding", "days", "70", "75", "70 to 75 days", "FY2024 70.30; FY2025 72.22", "Use cost-of-sales denominator and average inventory.", "Does not assume the FY2025 inventory cash release repeats.", "medium", "Stabilization could normalize inventory below 70.", "Purchase and safety-stock detail missing."),
        ("ASM-007", "DRV-006", "capital_expenditures_as_percent_of_revenue", "percent", "3", "4", "3% to 4% of revenue, subject to maintenance floor", "FY2025 3.41%; FY2024 2.90%", "Apply to revenue only until category schedule is obtained.", "Anchors to reported total capex without calling all spend maintenance.", "low", "Integration spend could fall after stabilization.", "Maintenance/expansion/integration split missing."),
        ("ASM-008", "DRV-004", "incremental_unrealized_synergies", "USD_millions", "0", "0", "$0 base credit; $15m company/high claim tracked separately", "Management: $30m realized; path to $45m", "Exclude unrealized synergy from base EBITDA; monitor realization outside forecast until approved.", "Impairment and plant issues require realized evidence.", "high", "Verified run-rate savings could later enter base.", "Timing, cost-to-achieve and duplicate savings bridge missing."),
        ("ASM-009", "DRV-007", "restructuring_cash_payments", "USD_millions", "0.7", "", "At least $0.7m known accrual; upper amount pending", "$0.7m workforce accrual at FY2025 year-end; additional charges possible", "Enter known cash need; do not invent an upper bound.", "Only disclosed residual is certain.", "low", "Some accrual may pay later or be offset.", "Cash timing and future program scope missing."),
        ("ASM-010", "DRV-010", "share_repurchases", "USD_millions", "0", "10", "$0-$10m owner-reviewed financial-policy range; not a fixed forecast", "FY2025 repurchases $32.360m", "Separate discretionary distributions from operations and retain the selected amount in both unmitigated downside cases.", "Phase 4 must determine proposed-facility restrictions; the existing-financing alternative cannot assume restraint without support.", "low", "A later owner decision may set zero until a leverage threshold is met.", "No binding prospective policy or Phase 4 restriction is established."),
        ("ASM-011", "DRV-010", "dividends", "USD_millions", "14", "15", "$14m-$15m annual reference; not committed", "FY2025 $14.889m; FY2024 $11.972m", "Use only after owner decision and Board-policy review.", "Reflects run rate without growth.", "medium", "Dividend could be reduced under stress.", "Future Board actions are not committed."),
        ("ASM-012", "DRV-012", "funding_rate_sensitivity_reference", "basis_points", "0", "0", "0 bps relative to the eventual Phase 4 closing-rate assumption; not a zero interest rate", "FY2025 weighted average 6.83%", "Apply later sensitivities to floating funded principal after Phase 4 establishes the contractual closing rate and hedge exposure.", "This is a reference point, not a hardcoded interest-rate assumption.", "high", "Hedging may alter exposure.", "Closing debt, benchmark, spread and hedge schedule missing."),
        ("ASM-013", "DRV-011", "foreign_exchange", "percent", "", "", "Direction and range pending exposure schedule", "International footprint; no public cash-flow elasticity", "Model local operations before translation where practical.", "Unsupported precision would be misleading.", "low", "Natural hedges may reduce sensitivity.", "Currency revenue, cost, debt and hedge exposures missing."),
        ("ASM-014", "DRV-009", "cash_flow_reporting_confidence", "status", "", "", "Enhanced review required until remediation tested", "FY2025 cash-flow control material weakness remained outstanding", "Apply as a reporting/monitoring control, not a numeric financial plug.", "No identified misstatement was reported.", "high", "Successful testing could remove the condition.", "Remediation test results unavailable."),
        ("ASM-015", "DRV-013", "accounts_payable", "status", "", "", "Pending Phase 5 method; no zero default", "FY2024/FY2025 accounts payable $124.404m/$131.307m; AP/cost-of-sales proxy 12.80%/9.81%", "Prefer purchases-based DPO only if purchases become available; otherwise use an explicitly labeled accounts-payable-to-cost-of-sales or other separate balance relationship.", "Cost of sales is not purchases, so the current proxy cannot be labeled DPO or selected without owner review.", "low", "Supplier-specific or average-balance relationships may be superior.", "Purchases, payment terms and post-Tyman comparable history are unavailable."),
        ("ASM-016", "DRV-013", "other_operating_current_assets_and_liabilities", "status", "", "", "Pending Phase 5 separate balance-driver method; no zero or funding plug", "FY2024/FY2025 other operating current assets $35.034m/$36.151m and liabilities $110.243m/$107.231m", "Forecast separate operating asset, accrued-liability and other operating-liability relationships using an approved operational driver; a disclosed percentage-of-revenue proxy may be considered but must remain labeled.", "Residual balances combine unlike items and the two-year history is acquisition-affected.", "low", "Account-level schedules may support distinct drivers.", "Account composition, seasonality and forecast drivers remain unavailable."),
    ]
    roles = {
        "ASM-001": "primary_forecast_input", "ASM-002": "primary_forecast_input",
        "ASM-003": "primary_forecast_input", "ASM-004": "validation_band",
        "ASM-005": "primary_forecast_input", "ASM-006": "primary_forecast_input",
        "ASM-007": "provisional_total_capex_input", "ASM-008": "normalization_constraint",
        "ASM-009": "minimum_cash_requirement", "ASM-010": "financial_policy_range",
        "ASM-011": "financial_policy_range", "ASM-012": "sensitivity_reference",
        "ASM-013": "pending_methodology", "ASM-014": "qualitative_monitoring_control",
        "ASM-015": "pending_methodology", "ASM-016": "pending_methodology",
    }
    decision_by = {row["record_id"]: row for row in decisions if row["record_type"] == "assumption"}
    rows = []
    for aid, did, line, units, low, high, direction, start, method, rationale, confidence, alt, gap in seed:
        driver = by_driver[did]
        rows.append({
            "assumption_id": aid, "driver_id": did, "forecast_line": line, "units": units,
            "proposed_low": low, "proposed_high": high,
            "proposed_direction_or_range": direction, "starting_historical_reference": start,
            "evidence_ids": driver["supporting_evidence_ids"], "source_ids": driver["source_ids"],
            "assumption_role": roles[aid],
            "forecast_override_permitted": "no" if roles[aid] in {"validation_band", "sensitivity_reference", "pending_methodology", "qualitative_monitoring_control"} else "only_after_periodization",
            "calculation_method": method, "rationale": rationale, "confidence": confidence,
            "alternative_interpretation": alt, "information_gap": gap,
            "status": decision_by[aid]["decision_status"],
            "owner_review_status": decision_by[aid]["owner_review_status"],
        })
    return rows


def scenario_rows(drivers: list[dict[str, str]],
                  decisions: list[dict[str, str]]) -> list[dict[str, str]]:
    by_driver = {row["driver_id"]: row for row in drivers}
    seed = [
        ("SCN-001", "DRV-001", "volume_vs_base", "percent", "-8", "-5", "onset in first stressed quarter", "4 quarters", "-18", "-12", "onset in first stressed quarter", "6-8 quarters", "retain", "Apply volume to revenue; working-capital release/need is modeled separately.", "Gross-margin shock includes fixed-cost deleverage; do not duplicate it.", "Borrower experienced an 8.7% quarterly decline and 5.0% legacy annual decline; severe range is plausible but not directly observed in post-Tyman history."),
        ("SCN-002", "DRV-003", "gross_margin_vs_base", "basis_points", "-250", "-150", "with volume shock", "4 quarters", "-450", "-300", "with persistent disruption", "6-8 quarters", "retain", "Reduce gross margin; EBITDA follows without a separate utilization charge.", "Includes fixed-cost deleverage from SCN-001 and operational pressure from SCN-005.", "Ranges are hypotheses anchored to a 550-590 bp quarterly gross-margin span, not a statistical elasticity."),
        ("SCN-003", "DRV-005", "days_sales_outstanding_vs_base", "days", "5", "5", "same quarter as collection slowdown", "4 quarters", "15", "15", "same quarter", "6-8 quarters", "retain", "Increase receivables and reduce CFO/revolver availability.", "Do not also apply a blanket working-capital percentage shock.", "Five days is material against a 40-43-day base; 15 days is severe and requires explicit customer/collection mechanism."),
        ("SCN-004", "DRV-005", "days_inventory_outstanding_vs_base", "days", "10", "10", "build begins with demand miss", "4 quarters", "25", "25", "build begins before corrective action", "6-8 quarters", "retain", "Increase inventory and reduce CFO/revolver availability.", "Coordinate with volume and plant disruption; do not count the same stock build twice.", "Ten and 25 days are material relative to 70-75-day base and test reversal of FY2024-FY2025 inventory cash releases."),
        ("SCN-005", "DRV-004", "execution_recovery_delay", "quarters", "2", "4", "after forecast starting point", "2-4 quarters", "6", "8", "after forecast starting point", "6-8 quarters", "revise_to_timed_delay", "Delay unverified savings and apply cash remediation only when supported.", "Operational margin effect is included in SCN-002; no separate duplicate decrement.", "Management expected stabilization in FY2026 H1; these ranges test slippage beyond that claim."),
        ("SCN-006", "DRV-012", "floating_rate_vs_base", "basis_points", "100", "100", "next reset", "4 quarters", "200", "200", "next reset", "through refinancing window", "retain", "Apply only to floating funded principal after hedges; reduce FCF.", "Separate from housing-demand effect in SCN-001.", "Contract is floating-rate; magnitude is an architecture hypothesis, not a rate forecast."),
        ("SCN-007", "DRV-010", "distribution_policy_treatment", "status", "", "", "not applicable; selected base distributions retained", "entire unmitigated moderate case", "", "", "not applicable; selected base distributions retained", "entire unmitigated severe case", "owner_reviewed_methodology", "Retain the owner-selected base repurchase and dividend policy in both unmitigated cases; quantify suspension or reduction only in separately disclosed mitigated cases.", "Never include distribution suspension in unmitigated cash flow; proposed- versus existing-financing restrictions must come from Phase 4 structure.", "No discretionary distributions remains a potential severe-case mitigation, not part of unmitigated stress."),
        ("SCN-008", "DRV-006", "capital_expenditures", "status", "", "", "after project review", "stress period", "", "", "after project review", "stress period", "pending_information", "Defer only identified discretionary projects and preserve a maintenance/safety floor.", "Do not count deferred integration capex and the related savings simultaneously.", "Maintenance split is unavailable, so numeric reduction is intentionally unresolved."),
        ("SCN-009", "DRV-013", "payables_and_other_operating_working_capital", "status", "", "", "after Phase 5 approves separate balance drivers", "stress period", "", "", "after Phase 5 approves separate balance drivers", "stress period", "pending_information", "Stress accounts payable, accrued operating liabilities, and other operating current assets/liabilities through separate approved balance relationships; transmit the change through CFO and revolver use.", "Do not use DPO without purchases, substitute revenue for purchases, silently call cost of sales purchases, or add a blanket shock already captured by DSO/DIO.", "Numeric ranges remain unresolved; no missing component may default to zero or serve as a funding plug."),
    ]
    decision_by = {row["record_id"]: row for row in decisions if row["record_type"] == "scenario"}
    rows = []
    for values in seed:
        sid, did, line, units, ml, mh, mt, md, sl, sh, st, sd, conclusion, mechanism, overlap, limits = values
        driver = by_driver[did]
        rows.append({
            "scenario_candidate_id": sid, "driver_id": did, "forecast_line": line,
            "units": units, "moderate_low": ml, "moderate_high": mh,
            "moderate_timing": mt, "moderate_duration": md, "severe_low": sl,
            "severe_high": sh, "severe_timing": st, "severe_duration": sd,
            "evidence_ids": driver["supporting_evidence_ids"], "source_ids": driver["source_ids"],
            "range_conclusion": conclusion, "transmission_mechanism": mechanism,
            "overlap_control": overlap,
            "unmitigated_distribution_treatment": "retain_selected_base_distribution_policy",
            "mitigated_distribution_treatment": "separate_mitigation_register_only",
            "limitations": limits, "status": decision_by[sid]["decision_status"],
            "owner_review_status": decision_by[sid]["owner_review_status"],
        })
    return rows


def mitigation_rows(drivers: list[dict[str, str]],
                    decisions: list[dict[str, str]]) -> list[dict[str, str]]:
    by_driver = {row["driver_id"]: row for row in drivers}
    decision_by = {row["record_id"]: row for row in decisions if row["record_type"] == "mitigation"}
    seed = [
        ("MIT-001", "DRV-010", "Suspend share repurchases", "FY2025 repurchases occurred; suspension not committed", "$32.360m FY2025 use", "Up to run-rate use avoided; future amount not committed", "one quarter", "$0 direct", "May reduce shareholder support", "reversible", "low", "not_determinable", "controllable_uncommitted"),
        ("MIT-002", "DRV-010", "Reduce or suspend dividends", "No prospective reduction commitment", "$14.889m FY2025 use", "Up to dividend cash use avoided, subject to Board action", "one quarter", "$0 direct", "Stronger adverse signal than buyback suspension", "reversible", "medium", "not_determinable", "board_dependent"),
        ("MIT-003", "DRV-006", "Defer discretionary capex", "General liquidity flexibility discussed; project list absent", "$62.642m FY2025 total capex", "not_determinable", "project-specific", "Possible cancellation cost", "May delay growth, integration or reliability", "partly_reversible", "medium", "project_and_document_specific", "pending_project_level_evidence"),
        ("MIT-004", "DRV-005", "Reduce inventory", "Working-capital management discussed", "$23.553m FY2025 inventory cash release", "not_determinable; historical release is not repeatable guidance", "one to two quarters", "Potential expedite or discount cost", "Service and production disruption if cut too far", "partly_reversible", "high", "not_expected_for_ordinary_course", "uncertain_operationally_disruptive"),
        ("MIT-005", "DRV-002", "Use pricing/index/surcharge mechanisms", "Used across multiple commodities", "No standalone cash amount", "not_determinable", "up to three months", "Customer concessions or share loss", "May protect margin but pressure demand", "reversible", "medium", "ordinary_course", "controllable_with_constraints"),
        ("MIT-006", "DRV-003;DRV-004;DRV-007", "Cost reduction or facility consolidation", "Plant and restructuring actions used historically", "$10.191m FY2025 restructuring charge", "not_determinable", "two to eight quarters", "Severance, relocation, systems and capex", "Execution/service disruption", "difficult_to_reverse", "high", "document_specific", "execution_dependent"),
        ("MIT-007", "DRV-012", "Asset sale, equity support, refinancing or waiver", "No committed source at cutoff", "None", "No credit in base or stress", "unknown", "Fees, dilution or value leakage", "Potential structural subordination or reduced asset base", "not_applicable", "high", "yes_or_not_determinable", "speculative"),
        ("MIT-008", "DRV-011;DRV-012", "Repatriate excess foreign cash for debt repayment", "Management discussed repatriating excess cash", "$46.9m foreign cash noted in Phase 0", "not_determinable", "entity/tax/operational dependent", "Taxes, trapped-cash or local-liquidity cost", "May reduce local liquidity", "partly_reversible", "medium", "not_determinable", "pending_accessibility_tax_legal"),
    ]
    rows = []
    for mid, dids, action, used, hist, benefit, timing, cost, consequence, reversible, risk, consent, availability in seed:
        related = [by_driver[did] for did in dids.split(";")]
        rows.append({
            "mitigation_id": mid, "driver_ids": dids, "action": action,
            "management_used_or_discussed": used, "historical_cash_reference": hist,
            "potential_cash_benefit": benefit, "timing": timing, "upfront_cost": cost,
            "operational_consequence": consequence, "reversibility": reversible,
            "execution_risk": risk, "lender_consent": consent,
            "availability_status": availability, "embedded_in_unmitigated_stress": "no",
            "evidence_ids": semis(evidence_id for row in related
                                   for evidence_id in row["supporting_evidence_ids"].split(";")),
            "source_ids": semis(source for row in related for source in row["source_ids"].split(";")),
            "status": decision_by[mid]["decision_status"],
            "owner_review_status": decision_by[mid]["owner_review_status"],
            "notes": "Owner reviewed the classification, not feasibility or amount. The benefit must be quantified incrementally only in a separately disclosed mitigated case; both unmitigated cases retain selected base distributions and other policies.",
        })
    return rows


def gap_rows() -> list[dict[str, str]]:
    seed = [
        ("GAP-001", "Complete guarantor scope", "Phase 0/1", "DRV-012", "SRC-003", "no", "yes", "yes", "no", "yes", "yes", "yes", "Do not assume all material entities guarantee."),
        ("GAP-002", "Post-Tyman collateral coverage and perfection", "Phase 0/1", "DRV-012", "SRC-003", "no", "yes", "yes", "no", "yes", "yes", "yes", "Do not assign collateral value or structural protection."),
        ("GAP-003", "Fee-letter economics and final spread", "Phase 0/1", "DRV-012", "SRC-003", "yes", "yes", "yes", "no", "yes", "yes", "yes", "No fee or spread assumption beyond public grid."),
        ("GAP-004", "Eligible covenant cash and accessibility", "Phase 0/1", "DRV-011;DRV-012", "SRC-003;SRC-001", "yes", "yes", "yes", "yes", "yes", "yes", "yes", "No covenant cash netting; book-cash net debt remains diagnostic."),
        ("GAP-005", "Official contractual EBITDA certificate", "Phase 1/2", "DRV-004;DRV-007;DRV-012", "SRC-003;SRC-016", "yes", "yes", "yes", "yes", "yes", "yes", "yes", "Use Phase 2 lender-base only; no official compliance claim."),
        ("GAP-006", "Covenant headroom on lender and contractual definitions", "Phase 0/2", "DRV-012", "SRC-003;SRC-016", "yes", "yes", "yes", "yes", "yes", "yes", "yes", "No projected covenant capacity until certificate and closing data arrive."),
        ("GAP-007", "Refinancing hedge and break costs", "Phase 0/1", "DRV-012", "SRC-003", "yes", "yes", "yes", "no", "yes", "yes", "no", "No benefit or cost assumed."),
        ("GAP-008", "January 2026 closing balances", "Phase 0/1", "DRV-005;DRV-012", "SRC-001;SRC-002", "yes", "yes", "yes", "yes", "yes", "yes", "yes", "Use October 2025 only as historical anchor, not closing balance."),
        ("GAP-009", "Exact cash interest and hedge exposure", "Phase 1/2", "DRV-012", "SRC-001;SRC-003", "yes", "yes", "yes", "yes", "yes", "yes", "yes", "Do not derive projected cash interest from annual expense."),
        ("GAP-010", "Maintenance versus expansion/integration capex", "Phase 2", "DRV-006", "SRC-001", "yes", "yes", "yes", "no", "yes", "yes", "yes", "Preserve total capex reference and do not remove maintenance."),
        ("GAP-011", "Restructuring cash timing and completion", "Phase 2", "DRV-004;DRV-007", "SRC-001", "yes", "yes", "yes", "no", "yes", "yes", "no", "Include known $0.7m accrual; leave unknown future amount pending."),
        ("GAP-012", "FY2025 composite-adjustment disaggregation", "Phase 2", "DRV-007", "SRC-002", "yes", "yes", "no", "yes", "yes", "yes", "yes", "Continue $0 lender-base acceptance; require category/cash schedule."),
        ("GAP-013", "Cash-flow control remediation evidence", "Phase 2", "DRV-009", "SRC-001", "yes", "yes", "yes", "yes", "yes", "yes", "yes", "Enhanced reporting checks until controls operate and are tested."),
        ("GAP-014", "FY2025 Q2 adjusted EBITDA $1.222m presentation difference", "Phase 3", "DRV-003;DRV-007", "SRC-002;SRC-016", "yes", "yes", "no", "yes", "yes", "yes", "no", "Use $63.135m only for annual tie-out; do not infer economic improvement."),
        ("GAP-015", "Accounts payable and other operating working-capital forecast method", "Phase 3 owner review", "DRV-005;DRV-013", "SRC-001", "yes", "yes", "no", "no", "yes", "yes", "yes", "Phase 5 must select separate balance-to-driver relationships without a DPO proxy, zero default or funding plug."),
    ]
    rows = []
    for values in seed:
        gid, desc, phase, drivers, sources, forecast, diligence, closing, covenant, monitoring, confidence, blocker, treatment = values
        rows.append({
            "gap_id": gid, "description": desc, "carried_from_phase": phase,
            "affected_driver_ids": drivers, "source_ids": sources,
            "forecast_limitation": forecast, "diligence_condition": diligence,
            "closing_condition": closing, "covenant_limitation": covenant,
            "monitoring_requirement": monitoring, "confidence_reduction": confidence,
            "potential_decision_blocker": blocker, "conservative_treatment": treatment,
            "status": "pending_information", "owner_review_status": "pending_owner_approval",
            "notes": "Private or closing-date information must not be replaced by an unsupported assumption.",
        })
    return rows


def source_maps(sources: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    existing = read_csv(PHASE0_INVENTORY)
    result: dict[str, dict[str, str]] = {}
    for row in existing:
        result[row["source_id"]] = {
            "title": row["document_title"], "url": row["source_location"],
            "date": row["publication_or_filing_date"],
        }
    for row in sources:
        result[row["source_id"]] = {
            "title": row["document_title"], "url": row["source_url"], "date": row["publication_date"],
        }
    return result


def build_ledger(collections: list[tuple[str, str, list[dict[str, str]], str, str]],
                 sources: list[dict[str, str]]) -> list[dict[str, str]]:
    smap = source_maps(sources)
    rows: list[dict[str, str]] = []
    for filename, layer, items, id_field, source_field in collections:
        for item in items:
            source_ids = item.get(source_field, "")
            parsed = source_ids.split(";") if source_ids else []
            evidence_ids = item.get("supporting_evidence_ids", item.get("evidence_ids", item.get("input_ids", "")))
            rows.append({
                "record_id": f"LED-{len(rows) + 1:04d}", "output_file": filename,
                "layer": layer, "metric_or_item": item[id_field], "source_ids": source_ids,
                "evidence_ids": evidence_ids,
                "document_titles": semis(smap[sid]["title"] for sid in parsed),
                "source_urls": semis(smap[sid]["url"] for sid in parsed),
                "publication_dates": semis(smap[sid]["date"] for sid in parsed),
                "classification": item.get("classification", item.get("status", item.get("decision_status", layer))),
                "owner_review_status": item.get("owner_review_status", "not_applicable"),
                "notes": item.get("notes", item.get("limitations", item.get("remaining_limitation", ""))),
            })
    return rows


def phase2_values() -> tuple[dict[tuple[str, str], Decimal], dict[str, Decimal]]:
    metrics = {(row["fiscal_year"], row["metric_name"]): dec(row["value"])
               for row in read_csv(PHASE2_METRICS) if row["value"]}
    bridges = read_csv(PHASE2_BRIDGES)
    finals: dict[str, Decimal] = {}
    for fy in ("FY2024", "FY2025"):
        rows = [row for row in bridges if row["fiscal_year"] == fy and row["bridge_type"] == "provisional_lender_normalized_ebitda_base" and row["resulting_subtotal"]]
        finals[fy] = dec(sorted(rows, key=lambda row: int(row["sequence"]))[-1]["resulting_subtotal"])
    return metrics, finals


def render_docs(evidence: list[dict[str, str]], trends: list[dict[str, str]],
                drivers: list[dict[str, str]], assumptions: list[dict[str, str]],
                scenarios: list[dict[str, str]], mitigations: list[dict[str, str]],
                gaps: list[dict[str, str]], sources: list[dict[str, str]]) -> None:
    qidx = {(r["fiscal_year"], r["quarter"], r["metric_name"]): r for r in trends if r["quarter"]}
    qlines = []
    for fy, q in QUARTERS:
        vals = [qidx[(fy, q, metric)]["value"] for metric in ("revenue", "gross_margin", "company_adjusted_ebitda", "cash_flow_from_operations", "free_cash_flow", "total_debt_principal")]
        qlines.append(f"| {fy} {q} | {qidx[(fy,q,'revenue')]['perimeter']} | {Decimal(vals[0]):,.3f} | {Decimal(vals[1]):.1f}% | {Decimal(vals[2]):,.3f} | {Decimal(vals[3]):,.3f} | {Decimal(vals[4]):,.3f} | {Decimal(vals[5]):,.3f} |")
    methodology = f"""# Phase 3 methodology

## Purpose and boundary

Phase 3 converts approved historical evidence into borrower-specific forecast mechanisms and owner-reviewed calibration ranges. It does **not** build projected statements, run scenarios, size a facility, calculate projected interest or covenant headroom, or begin Phase 4. Owner review approves the stated ranges or methods, not period-by-period forecasts.

## Evidence architecture

- `SOURCE_ADDITIONS.csv` adds {len(sources)} bounded sources, SRC-017 through SRC-025. Existing sources retain their prior IDs.
- `DRIVER_EVIDENCE.csv` preserves reported facts, management explanations and external indicators separately. Observation and publication dates are distinct; each external indicator carries its historical range used and relationship to Quanex.
- `OWNER_REVIEW_DECISIONS.csv` preserves the governing review disposition separately from source facts and calculated outputs.
- The processed registers are deterministic transformations or explicit analyst proposals. Blank information remains blank or `pending_information`, never zero.
- Every new source was published by {CUTOFF.isoformat()}. Revisable Census and ONS releases are locked to their dated release vintage and carry revision flags.
- Locally retained extracts are hashed by source from canonical evidence-row payloads. The manifest stores the SHA-256 and byte count; no full source document is copied.

The August 2025 New Residential Construction release was the latest actual release available at the December 15, 2025 cutoff. Although the Census schedule had contemplated later data, September and October 2025 estimates were not released until January 9, 2026. Those later releases are excluded and are referenced only to explain vintage availability, never as analytical evidence.

## Quarterly construction

The eight-quarter table uses reported standalone-quarter figures. Cash-flow figures use valid standalone disclosures or annual/YTD differences disclosed in the cited releases. FY2024 Q1-Q3 are legacy pre-Tyman, FY2024 Q4 is mixed perimeter, and FY2025 is full post-Tyman. Quarterly revenue, gross profit, CFO, capex and FCF tie exactly to annual Phase 2 amounts.

The latest within-cutoff FY2025 annual release shows Q2 adjusted EBITDA of $63.135m, versus $61.913m in the original Q2 release. The reconciled series uses $63.135m only so the four quarters tie to $242.890m; the unexplained $1.222m difference remains a diligence item. This is not an analyst earnings adjustment.

## Authoritative forecast mechanics

Volume and price/mix generate revenue. Gross margin is the primary gross-profit assumption. Operating expenses and accepted adjustments then generate lender-normalized EBITDA. The owner-reviewed 12%-13% lender-normalized EBITDA margin is a validation band only: it cannot be hardcoded to override the operating build. A later forecast must flag any calculated EBITDA margin outside the band and require review rather than forcing the result back into range. Scenario margin shocks flow through this same chain.

DSO and DIO retain their owner-reviewed ranges. Accounts payable, accrued operating liabilities, and other operating current assets and liabilities remain pending Phase 5 methods. Purchases are unavailable, so DPO is not determinable. Accounts payable as a percentage of cost of sales may be considered only as an explicitly labeled proxy; cost of sales must never be called purchases. Other operating balances require separate approved relationships and cannot default to zero or serve as a funding plug.

## Scenario and mitigation discipline

The stated operating ranges are owner-reviewed calibrations, not forecasts. Revenue volume, price/mix, margin, working capital, capex and cash costs remain separate. The margin shock explicitly includes volume-related fixed-cost deleverage. Both moderate and severe unmitigated cases retain the selected base distribution policy. Buyback suspension, dividend reduction, and no discretionary distributions appear only in separately disclosed mitigated cases with incremental cash benefit shown. Maintenance capex is not assumed removable, and speculative refinancing, waivers, asset sales or equity receive no credit.

## Monitoring observability

Every driver classifies its warning trigger as publicly observable, available through required borrower reporting, dependent on private diligence, or not currently measurable. Reporting-dependent triggers identify the required reporting source. Numerical thresholds remain warning candidates rather than final covenants.

## Reproduction

```powershell
python scripts/phase3.py all
python -m unittest discover -s tests -v
```

Python standard library only; no live network access is used.
"""
    write_text(DOCS / "METHODOLOGY.md", methodology)

    brief = f"""# Borrower and industry driver brief

## Credit-focused operating model

Quanex supplies engineered components to building-products OEMs and distributors. Current products span window and door hardware, screens, insulating-glass spacers, vinyl profiles, seals, weatherstripping, wood and metal components, custom mixing, cabinetry and building-access solutions. The primary demand channels are residential repair/replacement and new housing, with secondary commercial and adjacent applications. The post-Tyman footprint is concentrated in North America and the U.K. but also includes Germany, Mexico, Canada and Italy. [SRC-001]

The manufacturing model is predominantly build-to-order with low finished-goods inventory, but it requires raw-material availability and plant execution. PVC, petroleum derivatives, metals and wood are material inputs. Indexes and surcharges reduce long-run exposure for many customers, yet coverage is incomplete and timing lags can reach three months. This creates a price/cost working-capital bridge rather than a perfect pass-through. [SRC-001]

Current reportable segments—Hardware Solutions, Extruded Solutions and Custom Solutions—were adopted during FY2025 integration. Company-supplied FY2023-FY2024 recasts are useful for presentation, but they do not fabricate a constant combined-company perimeter. FY2024 still contains only three months of Tyman; FY2025 is the first full post-Tyman year. [SRC-001; SRC-002]

## Eight-quarter evidence

USD millions except margins.

| Period | Perimeter | Revenue | Gross margin | Company adj. EBITDA | CFO | FCF | Gross debt |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(qlines)}

The table shows a repeatable first-quarter cash trough: FCF was negative $5.726m in FY2024 Q1 and negative $24.134m in FY2025 Q1. FY2024 Q4 is not a clean run-rate quarter: Tyman entered the perimeter and gross debt rose from $55.007m at Q3 to $776.926m. FY2025 Q4 revenue was 0.5% lower year over year and company-adjusted EBITDA was $70.918m versus $81.050m; full-year reported growth was acquisition-led. [SRC-017 through SRC-022; SRC-002]

## Industry evidence available at the cutoff

- U.S. August 2025 housing starts were 1.307m SAAR, down 6.0% year over year; single-family starts were 890,000 SAAR and permits were 1.312m, down 11.1% year over year. This September 17 release was the latest actual release available by the cutoff. September and October estimates were not released until January 9, 2026 and are excluded; revision risk remains explicit. [SRC-023]
- The October 2025 LIRA expected nominal owner-occupied remodeling spending growth of 2.4% in early 2026, easing to 1.9% by 2026 Q3. This is contextual nominal spending, not Quanex unit demand or an elasticity. [SRC-024]
- Great Britain construction output fell 0.3% in the three months to October 2025; private-housing repair and maintenance fell 2.3%, while new work grew 0.1%. The ONS release identified a data error and future revisions, so only this dated vintage is used. [SRC-025]

Together these indicators support a flat-to-soft base direction, not a precise demand forecast. They support the owner-reviewed 5%-8% moderate volume calibration and 12%-18% severe calibration without asserting a tested elasticity.

## Historical driver conclusions

- Reported FY2025 revenue growth is not organic: Tyman contributed the majority of the increase. Legacy/ex-Tyman quarterly trends ranged from decline to modest growth.
- FY2025 gross margin of 27.2% improved from 23.9%, but quarterly margins ranged from 23.1% to 29.0%; acquisition mix, synergies, raw-material movements and seasonality prevent a clean structural conclusion.
- Management said the initial $30m synergy target was realized and retained a path to $45m. Phase 3 gives no base credit to the remaining $15m without realized evidence.
- The Mexico hardware plant issue and FY2025 impairment make plant stabilization and acquisition execution primary margin risks.
- FY2025 DSO of 40.03 and DIO of 72.22 days remain acquisition-affected; Q1 cash seasonality and large annual inventory releases caution against assuming smooth conversion.
- FY2024/FY2025 accounts payable was $124.404m/$131.307m. The 12.80%/9.81% end-balance-to-cost-of-sales relationship is only a labeled proxy, not DPO; purchases are unavailable. Other operating current assets and liabilities also require separate Phase 5 methods and cannot default to zero.
- FY2025 capex was $62.642m, but maintenance versus integration/expansion remains not determinable.
- The $10.263m composite adjustment remains disaggregated neither for EBITDA quality nor cash timing. The known restructuring accrual was $0.7m, with possible further charges.
- The $302.284m impairment remains a major adverse signal even though Phase 2 accepts the noncash reversal mathematically.
- The cash-flow material weakness remained outstanding, with no identified misstatement. This reduces confidence and raises monitoring needs; it is not a plug to reported cash.
- FY2025 bank debt fell $75m, while dividends and buybacks used $47.249m. Distribution policy therefore materially affects deleveraging.

## Proposed assumption and scenario ranges

Owner-reviewed base calibrations: underlying volume -2% to +1%; price/mix 0% to +1%; gross margin 26%-28%; DSO 40-43 days; DIO 70-75 days; total capex 3%-4% of revenue subject to an unresolved maintenance floor; zero base credit for the remaining $15m management synergy claim. The 12%-13% lender-normalized EBITDA margin is a validation band, not an independent forecast driver.

Moderate: volume 5%-8% below base for four quarters; gross margin 150-250 bps below base inclusive of fixed-cost deleverage; DSO +5 days; DIO +10 days; recovery delayed 2-4 quarters; floating rate +100 bps.

Severe but plausible: volume 12%-18% below base for six to eight quarters; gross margin 300-450 bps below base inclusive of deleverage and operational disruption; DSO +15 days; DIO +25 days; disruption/recovery delayed 6-8 quarters; floating rate +200 bps plus restricted refinancing. Capex reductions remain unquantified until the maintenance floor is known. Both unmitigated cases retain the selected base distributions; suspension or reduction is modeled only as a separate mitigation.

These are owner-reviewed calibration ranges, not final period-by-period forecasts. No scenario was run. FX and the payables/other-operating-working-capital methods remain pending information.
"""
    write_text(DOCS / "BORROWER_INDUSTRY_BRIEF.md", brief)

    handoff = """# Phase 4 handoff

Phase 4 should use these findings only after owner review; no closing, debt-service, liquidity or covenant calculation has been performed here.

1. Size and amortization must reflect a soft underlying demand base, first-quarter cash seasonality, a 12%-13% lender-normalized EBITDA validation band, and no credit for the remaining $15m synergy claim until verified. The band cannot override EBITDA generated by the operating build.
2. Revolver sizing must capture the Q1 cash trough, DSO/DIO stresses, separately modeled payables and other operating working capital, restructuring cash, capex commitments and restricted access to foreign cash.
3. Obtain January 2026 debt, cash, revolver, letters-of-credit and working-capital balances before building sources and uses.
4. Obtain the official contractual EBITDA and covenant certificate; do not use the partial public reconstruction as compliance EBITDA.
5. Resolve eligible cash, guarantor scope, collateral/perfection after Tyman, and legal-entity cash accessibility.
6. Obtain the fee letter, spread election, unused fees, hedge schedule, break costs, payoff letters and any make-whole/termination amounts.
7. Require a maintenance/expansion/integration capex schedule and do not assume the maintenance floor is discretionary.
8. Obtain a plant stabilization plan, realized-synergy bridge, cost-to-achieve schedule, service KPIs and customer-loss evidence.
9. Obtain the FY2025 composite-adjustment disaggregation and restructuring cash roll-forward.
10. Require cash-flow control remediation milestones, testing evidence and delivery/covenant-reporting protections.
11. Compare retaining the August 2029 facilities against refinancing without presuming that higher fees, tighter terms or early refinancing are value accretive.
12. Compare proposed- and existing-financing distribution restrictions only after both unmitigated cases retain the selected base policy; show buyback suspension and dividend reduction solely as incremental mitigations.
13. Phase 5 must resolve accounts payable, accrued operating liabilities and other operating current assets/liabilities through separate approved relationships without using DPO absent purchases, a zero default or a funding plug.
"""
    write_text(DOCS / "PHASE4_HANDOFF.md", handoff)


def seed_raw() -> dict[str, int]:
    evidence = evidence_seed_rows()
    sources = source_seed_rows()
    owner_decisions = owner_decision_rows()
    attach_extract_hashes(sources, evidence)
    write_csv(RAW / "SOURCE_ADDITIONS.csv", sources, SOURCE_FIELDS)
    write_csv(RAW / "DRIVER_EVIDENCE.csv", evidence, EVIDENCE_FIELDS)
    write_csv(RAW / "OWNER_REVIEW_DECISIONS.csv", owner_decisions, OWNER_DECISION_FIELDS)
    checkpoint = [{
        "repository": "owencchapman24/quanex-credit-underwriting", "branch": "main",
        "local_head": APPROVED_PHASE2_COMMIT, "tracked_origin_main": APPROVED_PHASE2_COMMIT,
        "live_remote_main": APPROVED_PHASE2_COMMIT, "ahead": "0", "behind": "0",
        "working_tree_clean_before_work": "yes", "verified_on": ACCESS_DATE,
        "notes": "Verified before Phase 3 file creation; live remote checked independently with git ls-remote.",
    }]
    write_csv(RAW / "STARTING_CHECKPOINT.csv", checkpoint, tuple(checkpoint[0]))
    return {"new_sources": len(sources), "evidence": len(evidence),
            "owner_decisions": len(owner_decisions)}


def build() -> dict[str, int]:
    sources = read_csv(RAW / "SOURCE_ADDITIONS.csv")
    evidence = read_csv(RAW / "DRIVER_EVIDENCE.csv")
    owner_decisions = read_csv(RAW / "OWNER_REVIEW_DECISIONS.csv")
    trends = build_trends(evidence)
    drivers = driver_rows(evidence)
    assumptions = assumption_rows(drivers, evidence, owner_decisions)
    scenarios = scenario_rows(drivers, owner_decisions)
    mitigations = mitigation_rows(drivers, owner_decisions)
    gaps = gap_rows()
    write_csv(PROCESSED / "QUARTERLY_SEGMENT_TRENDS.csv", trends, TREND_FIELDS)
    write_csv(PROCESSED / "RISK_DRIVER_MAP.csv", drivers, DRIVER_FIELDS)
    write_csv(PROCESSED / "ASSUMPTION_CANDIDATES.csv", assumptions, ASSUMPTION_FIELDS)
    write_csv(PROCESSED / "SCENARIO_DRIVER_CANDIDATES.csv", scenarios, SCENARIO_FIELDS)
    write_csv(PROCESSED / "MITIGATION_REGISTER.csv", mitigations, MITIGATION_FIELDS)
    write_csv(PROCESSED / "INFORMATION_GAPS.csv", gaps, GAP_FIELDS)
    ledger = build_ledger([
        ("data/phase3/raw/DRIVER_EVIDENCE.csv", "raw_evidence", evidence, "evidence_id", "source_ids"),
        ("data/phase3/raw/OWNER_REVIEW_DECISIONS.csv", "owner_decision", owner_decisions, "decision_id", "source_ids"),
        ("data/phase3/processed/QUARTERLY_SEGMENT_TRENDS.csv", "processed_trend", trends, "trend_id", "source_ids"),
        ("data/phase3/processed/RISK_DRIVER_MAP.csv", "analyst_driver", drivers, "driver_id", "source_ids"),
        ("data/phase3/processed/ASSUMPTION_CANDIDATES.csv", "proposed_assumption", assumptions, "assumption_id", "source_ids"),
        ("data/phase3/processed/SCENARIO_DRIVER_CANDIDATES.csv", "proposed_scenario", scenarios, "scenario_candidate_id", "source_ids"),
        ("data/phase3/processed/MITIGATION_REGISTER.csv", "proposed_mitigation", mitigations, "mitigation_id", "source_ids"),
        ("data/phase3/processed/INFORMATION_GAPS.csv", "information_gap", gaps, "gap_id", "source_ids"),
    ], sources)
    write_csv(DOCS / "SOURCE_LEDGER.csv", ledger, LEDGER_FIELDS)
    render_docs(evidence, trends, drivers, assumptions, scenarios, mitigations, gaps, sources)
    return {
        "trends": len(trends), "drivers": len(drivers), "assumptions": len(assumptions),
        "scenarios": len(scenarios), "mitigations": len(mitigations), "gaps": len(gaps),
        "ledger": len(ledger),
    }


def output_paths() -> list[Path]:
    return [
        RAW / "SOURCE_ADDITIONS.csv", RAW / "DRIVER_EVIDENCE.csv", RAW / "OWNER_REVIEW_DECISIONS.csv",
        RAW / "STARTING_CHECKPOINT.csv",
        PROCESSED / "QUARTERLY_SEGMENT_TRENDS.csv", PROCESSED / "RISK_DRIVER_MAP.csv",
        PROCESSED / "ASSUMPTION_CANDIDATES.csv", PROCESSED / "SCENARIO_DRIVER_CANDIDATES.csv",
        PROCESSED / "MITIGATION_REGISTER.csv", PROCESSED / "INFORMATION_GAPS.csv",
        DOCS / "SOURCE_LEDGER.csv", DOCS / "METHODOLOGY.md", DOCS / "BORROWER_INDUSTRY_BRIEF.md",
        DOCS / "PHASE4_HANDOFF.md",
    ]


def fingerprints() -> dict[str, str]:
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in output_paths()}


def validate() -> dict[str, int]:
    sources = read_csv(RAW / "SOURCE_ADDITIONS.csv")
    evidence = read_csv(RAW / "DRIVER_EVIDENCE.csv")
    owner_decisions = read_csv(RAW / "OWNER_REVIEW_DECISIONS.csv")
    trends = read_csv(PROCESSED / "QUARTERLY_SEGMENT_TRENDS.csv")
    drivers = read_csv(PROCESSED / "RISK_DRIVER_MAP.csv")
    assumptions = read_csv(PROCESSED / "ASSUMPTION_CANDIDATES.csv")
    scenarios = read_csv(PROCESSED / "SCENARIO_DRIVER_CANDIDATES.csv")
    mitigations = read_csv(PROCESSED / "MITIGATION_REGISTER.csv")
    gaps = read_csv(PROCESSED / "INFORMATION_GAPS.csv")
    ledger = read_csv(DOCS / "SOURCE_LEDGER.csv")
    checkpoint = read_csv(RAW / "STARTING_CHECKPOINT.csv")

    for rows, field, label in (
        (sources, "source_id", "source IDs"), (evidence, "evidence_id", "evidence IDs"),
        (trends, "trend_id", "trend IDs"), (drivers, "driver_id", "driver IDs"),
        (assumptions, "assumption_id", "assumption IDs"),
        (scenarios, "scenario_candidate_id", "scenario IDs"),
        (mitigations, "mitigation_id", "mitigation IDs"), (gaps, "gap_id", "gap IDs"),
        (owner_decisions, "decision_id", "owner decision IDs"),
    ):
        ensure_unique(rows, field, label)
    decision_keys = [(row["record_type"], row["record_id"]) for row in owner_decisions]
    if len(decision_keys) != len(set(decision_keys)):
        raise Phase3Error("Duplicate owner decision target")
    if any(row["decision_status"] not in {"owner_reviewed_range", "owner_reviewed_methodology", "pending_information", "not_applicable"}
           or row["owner_review_status"] != "owner_reviewed" for row in owner_decisions):
        raise Phase3Error("Invalid owner-review disposition")

    if [row["source_id"] for row in sources] != [f"SRC-{number:03d}" for number in range(17, 26)]:
        raise Phase3Error("New sources are not the next contiguous IDs SRC-017 through SRC-025")
    required_source_fields = {"publisher", "document_title", "document_type", "source_url", "publication_date", "information_period", "access_date", "relevant_section", "redistribution_status", "extract_sha256", "extract_bytes", "added_reason"}
    for row in sources:
        if any(not row[field] for field in required_source_fields):
            raise Phase3Error(f"Incomplete provenance for {row['source_id']}")
        if datetime.strptime(row["publication_date"], "%Y-%m-%d").date() > CUTOFF or row["cutoff_status"] != "ALLOWED":
            raise Phase3Error(f"Post-cutoff source: {row['source_id']}")
        if len(row["extract_sha256"]) != 64 or int(row["extract_bytes"]) <= 0:
            raise Phase3Error(f"Invalid local extract hash for {row['source_id']}")
    census = next(row for row in sources if row["source_id"] == "SRC-023")
    if "latest actual" not in census["notes"] or "2026-01-09" not in census["notes"] or "excluded" not in census["notes"]:
        raise Phase3Error("Census cutoff-vintage rationale is incomplete")
    if any("2026-01-09" in "|".join(row.values()) for row in evidence):
        raise Phase3Error("Post-cutoff January 2026 housing release entered analytical evidence")

    valid_sources = {row["source_id"] for row in read_csv(PHASE0_INVENTORY)} | {row["source_id"] for row in sources}
    for collection in (evidence, trends, drivers, assumptions, scenarios, mitigations, gaps, ledger):
        for row in collection:
            for field in ("source_ids",):
                for source_id in row.get(field, "").split(";"):
                    if source_id and source_id not in valid_sources:
                        raise Phase3Error(f"Invalid source ID {source_id}")
    for row in evidence:
        if row["units"] not in VALID_UNITS:
            raise Phase3Error(f"Invalid evidence units for {row['evidence_id']}: {row['units']}")
        if not row["source_ids"] or not row["publication_date"]:
            raise Phase3Error(f"Missing lineage for {row['evidence_id']}")
        if datetime.strptime(row["publication_date"], "%Y-%m-%d").date() > CUTOFF:
            raise Phase3Error(f"Post-cutoff evidence: {row['evidence_id']}")
        if row["observation_date"] and row["publication_date"] == row["observation_date"] and row["topic"] == "industry_indicator":
            raise Phase3Error(f"Observation/publication date not distinguished for {row['evidence_id']}")
        if row["topic"] == "industry_indicator" and not row["vintage"]:
            raise Phase3Error(f"Missing vintage for {row['evidence_id']}")
        if row["topic"] == "industry_indicator" and (not row["historical_range_used"] or row["relationship_to_quanex"] not in {"direct", "indirect", "contextual"}):
            raise Phase3Error(f"Incomplete external-indicator relationship for {row['evidence_id']}")
        if row["revision_risk"] == "revisable_flagged" and not row["vintage"].startswith("release_vintage_"):
            raise Phase3Error(f"Uncontrolled revision risk for {row['evidence_id']}")

    accepted_q = [row for row in evidence if row["topic"] == "quarterly_trend" and row["acceptance_status"] == "accepted"]
    keys = [(row["fiscal_year"], row["quarter"], row["metric_name"]) for row in accepted_q]
    if len(keys) != len(set(keys)):
        raise Phase3Error("Duplicate accepted quarterly fact")
    if {key[:2] for key in keys} != set(QUARTERS):
        raise Phase3Error("Eight-quarter coverage failed")
    perimeter = {(row["fiscal_year"], row["quarter"]): row["perimeter"] for row in accepted_q}
    if any(perimeter[("FY2024", q)] != "legacy_pre_tyman" for q in ("Q1", "Q2", "Q3")):
        raise Phase3Error("Pre-Tyman perimeter mislabeled")
    if perimeter[("FY2024", "Q4")] != "mixed_three_months_tyman" or any(perimeter[("FY2025", q)] != "full_post_tyman" for q in ("Q1", "Q2", "Q3", "Q4")):
        raise Phase3Error("Post-Tyman perimeter mislabeled")
    if any(row["fiscal_year"] < "FY2023" for row in trends if row["segment"] not in {"Consolidated", ""}):
        raise Phase3Error("Current segment history fabricated before company recast")

    qindex = {(r["fiscal_year"], r["quarter"], r["metric_name"]): dec(r["value"])
              for r in trends if r["quarter"] and r["classification"] == "reported"}
    annual = {(r["fiscal_year"], r["metric_name"]): dec(r["value"])
              for r in read_csv(PHASE2_SPREAD) if r["value"]}
    bridge_annual = {fy: sum(qindex[(fy, q, "company_adjusted_ebitda")] for q in ("Q1", "Q2", "Q3", "Q4")) for fy in ("FY2024", "FY2025")}
    for fy in ("FY2024", "FY2025"):
        for metric in ("revenue", "gross_profit", "cash_flow_from_operations", "capital_expenditures", "free_cash_flow"):
            total = sum(qindex[(fy, q, metric)] for q in ("Q1", "Q2", "Q3", "Q4"))
            if total != annual[(fy, metric)]:
                raise Phase3Error(f"Quarterly {metric} does not reconcile for {fy}: {total}")
    phase2_company = {}
    for row in read_csv(PHASE2_BRIDGES):
        if row["bridge_type"] == "company_adjusted_ebitda" and row["resulting_subtotal"]:
            phase2_company[row["fiscal_year"]] = dec(row["resulting_subtotal"])
    if bridge_annual["FY2024"] != Decimal("182.383") or bridge_annual["FY2025"] != Decimal("242.890"):
        raise Phase3Error("Quarterly company-adjusted EBITDA does not reconcile")
    for fy, value in bridge_annual.items():
        if value != phase2_company[fy]:
            raise Phase3Error(f"Phase 2 EBITDA changed for {fy}")

    valid_evidence = {row["evidence_id"] for row in evidence}
    valid_drivers = {row["driver_id"] for row in drivers}
    expected_decision_targets = ({("assumption", row["assumption_id"]) for row in assumptions}
                                 | {("scenario", row["scenario_candidate_id"]) for row in scenarios}
                                 | {("mitigation", row["mitigation_id"]) for row in mitigations})
    if set(decision_keys) != expected_decision_targets:
        raise Phase3Error("Owner-review decisions do not match governed records")
    governed = ({("assumption", row["assumption_id"]): row for row in assumptions}
                | {("scenario", row["scenario_candidate_id"]): row for row in scenarios}
                | {("mitigation", row["mitigation_id"]): row for row in mitigations})
    for decision in owner_decisions:
        record = governed[(decision["record_type"], decision["record_id"])]
        if record["status"] != decision["decision_status"] or record["owner_review_status"] != decision["owner_review_status"]:
            raise Phase3Error(f"Owner-review decision not propagated to {decision['record_id']}")
    for collection in (drivers, assumptions, scenarios, mitigations):
        for row in collection:
            field = "supporting_evidence_ids" if "supporting_evidence_ids" in row else "evidence_ids"
            references = [value for value in row[field].split(";") if value]
            if len(references) != len(set(references)):
                raise Phase3Error(f"Duplicate evidence reference in {row.get('driver_id', row.get('assumption_id', row.get('scenario_candidate_id', row.get('mitigation_id', 'record'))))}")
            invalid = sorted(set(references) - valid_evidence)
            if invalid:
                raise Phase3Error(f"Invalid evidence reference(s): {', '.join(invalid)}")
    for row in drivers:
        if not row["supporting_evidence_ids"] or not row["source_ids"]:
            raise Phase3Error(f"Unmapped material driver {row['driver_id']}")
        if not (row["primary_forecast_line"] or row["potential_diligence_condition"] or row["potential_monitoring_metric"]):
            raise Phase3Error(f"Narrative-only driver {row['driver_id']}")
        if row["owner_review_status"] != "owner_reviewed":
            raise Phase3Error(f"Missing owner-reviewed disposition for {row['driver_id']}")
        if row["monitoring_observability"] not in {"publicly_observable", "available_through_required_borrower_reporting", "dependent_on_private_diligence", "not_currently_measurable"}:
            raise Phase3Error(f"Invalid monitoring observability for {row['driver_id']}")
        if row["monitoring_observability"] in {"available_through_required_borrower_reporting", "dependent_on_private_diligence"} and not row["required_reporting_source"]:
            raise Phase3Error(f"Missing required reporting source for {row['driver_id']}")
        for eid in row["supporting_evidence_ids"].split(";"):
            if eid and eid not in valid_evidence:
                raise Phase3Error(f"Invalid evidence ID {eid} in {row['driver_id']}")
    for row in assumptions:
        if row["driver_id"] not in valid_drivers or row["owner_review_status"] != "owner_reviewed":
            raise Phase3Error(f"Invalid assumption mapping/review: {row['assumption_id']}")
        if row["units"] not in VALID_UNITS:
            raise Phase3Error(f"Invalid assumption unit: {row['assumption_id']}")
    expected_base_ranges = {
        "ASM-001": ("-2", "1"), "ASM-002": ("0", "1"), "ASM-003": ("26", "28"),
        "ASM-004": ("12", "13"), "ASM-005": ("40", "43"), "ASM-006": ("70", "75"),
        "ASM-007": ("3", "4"), "ASM-008": ("0", "0"), "ASM-009": ("0.7", ""),
        "ASM-010": ("0", "10"), "ASM-011": ("14", "15"), "ASM-012": ("0", "0"),
        "ASM-013": ("", ""), "ASM-014": ("", ""), "ASM-015": ("", ""),
        "ASM-016": ("", ""),
    }
    if {row["assumption_id"]: (row["proposed_low"], row["proposed_high"]) for row in assumptions} != expected_base_ranges:
        raise Phase3Error("Owner-reviewed base calibration changed")
    for row in scenarios:
        if row["driver_id"] not in valid_drivers or row["owner_review_status"] != "owner_reviewed":
            raise Phase3Error(f"Invalid scenario mapping/review: {row['scenario_candidate_id']}")
        if row["units"] not in VALID_UNITS:
            raise Phase3Error(f"Invalid scenario unit: {row['scenario_candidate_id']}")
        numeric = all(row[field] for field in ("moderate_low", "moderate_high", "severe_low", "severe_high"))
        if numeric:
            ml, mh, sl, sh = (dec(row[field]) for field in ("moderate_low", "moderate_high", "severe_low", "severe_high"))
            if ml > mh or sl > sh:
                raise Phase3Error(f"Inverted scenario range: {row['scenario_candidate_id']}")
            if row["scenario_candidate_id"] in {"SCN-001", "SCN-002"} and abs(sl) < abs(ml):
                raise Phase3Error(f"Severe scenario not more adverse: {row['scenario_candidate_id']}")
        if not row["overlap_control"]:
            raise Phase3Error(f"Missing double-counting control: {row['scenario_candidate_id']}")
        if row["unmitigated_distribution_treatment"] != "retain_selected_base_distribution_policy" or row["mitigated_distribution_treatment"] != "separate_mitigation_register_only":
            raise Phase3Error(f"Distribution treatment is not separated in {row['scenario_candidate_id']}")
    expected_scenario_ranges = {
        "SCN-001": ("-8", "-5", "-18", "-12"),
        "SCN-002": ("-250", "-150", "-450", "-300"),
        "SCN-003": ("5", "5", "15", "15"),
        "SCN-004": ("10", "10", "25", "25"),
        "SCN-005": ("2", "4", "6", "8"),
        "SCN-006": ("100", "100", "200", "200"),
        "SCN-007": ("", "", "", ""), "SCN-008": ("", "", "", ""),
        "SCN-009": ("", "", "", ""),
    }
    if {row["scenario_candidate_id"]: tuple(row[field] for field in ("moderate_low", "moderate_high", "severe_low", "severe_high")) for row in scenarios} != expected_scenario_ranges:
        raise Phase3Error("Owner-reviewed scenario calibration changed")
    ebitda_band = next(row for row in assumptions if row["assumption_id"] == "ASM-004")
    if ebitda_band["assumption_role"] != "validation_band" or ebitda_band["forecast_override_permitted"] != "no" or "flag" not in ebitda_band["calculation_method"]:
        raise Phase3Error("EBITDA-margin validation band can override the operating build")
    payables = next(row for row in assumptions if row["assumption_id"] == "ASM-015")
    other_wc = next(row for row in assumptions if row["assumption_id"] == "ASM-016")
    if any(row["proposed_low"] or row["proposed_high"] for row in (payables, other_wc)):
        raise Phase3Error("Missing payables or other working capital defaulted to a number")
    if payables["status"] != "pending_information" or other_wc["status"] != "pending_information":
        raise Phase3Error("Working-capital method is not pending information")
    if "purchases" not in payables["calculation_method"].lower() or "cost of sales" not in payables["rationale"].lower() or "cannot be labeled dpo" not in payables["rationale"].lower():
        raise Phase3Error("DPO proxy limitation is not explicit")
    if any(row["embedded_in_unmitigated_stress"] != "no" for row in mitigations):
        raise Phase3Error("Mitigation embedded in unmitigated stress")
    if any(row["owner_review_status"] != "owner_reviewed" or row["status"] != "owner_reviewed_methodology" for row in mitigations):
        raise Phase3Error("Mitigation classification is not owner-reviewed methodology")
    expected_mitigation_classes = {
        "MIT-001": "controllable_uncommitted", "MIT-002": "board_dependent",
        "MIT-003": "pending_project_level_evidence",
        "MIT-004": "uncertain_operationally_disruptive",
        "MIT-005": "controllable_with_constraints", "MIT-006": "execution_dependent",
        "MIT-007": "speculative", "MIT-008": "pending_accessibility_tax_legal",
    }
    if {row["mitigation_id"]: row["availability_status"] for row in mitigations} != expected_mitigation_classes:
        raise Phase3Error("Owner-reviewed mitigation classification changed")
    if any(row["availability_status"] == "speculative" and "No credit" not in row["potential_cash_benefit"] for row in mitigations):
        raise Phase3Error("Speculative mitigation receives credit")
    capex_scenario = next(row for row in scenarios if row["scenario_candidate_id"] == "SCN-008")
    if capex_scenario["moderate_low"] or capex_scenario["severe_low"] or "maintenance" not in capex_scenario["transmission_mechanism"]:
        raise Phase3Error("Maintenance capex improperly removable")
    if any(row["status"] != "pending_information" for row in gaps):
        raise Phase3Error("Information gap converted into an assumption")

    decisions = read_csv(PHASE2_DECISIONS)
    expected = {"AC-001": "302.284", "AC-002": "0", "AC-003": "0", "AC-004": "9.007", "AC-005": "0", "AC-006": "4.561", "AC-007": "0", "AC-008": "0", "AC-009": "-4.196", "AC-010": "29.076", "AC-011": "39.324"}
    if {r["adjustment_id"]: r["accepted_amount_base"] for r in decisions} != expected:
        raise Phase3Error("Phase 2 adjustment decisions changed")
    _, lender = phase2_values()
    if lender != {"FY2024": Decimal("179.358"), "FY2025": Decimal("225.344")}:
        raise Phase3Error("Phase 2 lender-base EBITDA changed")

    if len(ledger) != len(evidence) + len(owner_decisions) + len(trends) + len(drivers) + len(assumptions) + len(scenarios) + len(mitigations) + len(gaps):
        raise Phase3Error("Source ledger incomplete")
    if len(checkpoint) != 1 or checkpoint[0]["local_head"] != APPROVED_PHASE2_COMMIT or checkpoint[0]["working_tree_clean_before_work"] != "yes":
        raise Phase3Error("Starting checkpoint audit record invalid")
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Phase3Error(f"Cannot verify HEAD: {exc}") from exc
    if head != APPROVED_PHASE2_COMMIT:
        raise Phase3Error(f"HEAD changed during Phase 3: {head}")

    expected_evidence = evidence_seed_rows()
    expected_sources = source_seed_rows()
    expected_owner_decisions = owner_decision_rows()
    attach_extract_hashes(expected_sources, expected_evidence)
    if evidence != expected_evidence or sources != expected_sources or owner_decisions != expected_owner_decisions:
        raise Phase3Error("Raw controlled inputs diverge from deterministic seed")
    before = fingerprints()
    build()
    if before != fingerprints():
        raise Phase3Error("Deterministic regeneration failed")

    stats = {
        "new_sources": len(sources), "evidence_rows": len(evidence), "trend_rows": len(trends),
        "drivers": len(drivers), "assumptions": len(assumptions), "scenario_candidates": len(scenarios),
        "mitigations": len(mitigations), "information_gaps": len(gaps), "ledger_rows": len(ledger),
        "post_cutoff_sources": 0,
        "owner_reviewed_assumptions": sum(row["status"].startswith("owner_reviewed") for row in assumptions),
    }
    print("Phase 3 validation: PASS")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("seed", "build", "validate", "all"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command in {"seed", "all"}:
            seed_raw()
        if args.command in {"build", "all"}:
            build()
        if args.command in {"validate", "all"}:
            validate()
    except (Phase3Error, KeyError, OSError, ValueError) as exc:
        print(f"Phase 3 error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
