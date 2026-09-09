# Phase 3 methodology

## Purpose and boundary

Phase 3 converts approved historical evidence into borrower-specific forecast mechanisms and owner-reviewed calibration ranges. It does **not** build projected statements, run scenarios, size a facility, calculate projected interest or covenant headroom, or begin Phase 4. Owner review approves the stated ranges or methods, not period-by-period forecasts.

## Evidence architecture

- `SOURCE_ADDITIONS.csv` adds 9 bounded sources, SRC-017 through SRC-025. Existing sources retain their prior IDs.
- `DRIVER_EVIDENCE.csv` preserves reported facts, management explanations and external indicators separately. Observation and publication dates are distinct; each external indicator carries its historical range used and relationship to Quanex.
- `OWNER_REVIEW_DECISIONS.csv` preserves the governing review disposition separately from source facts and calculated outputs.
- The processed registers are deterministic transformations or explicit analyst proposals. Blank information remains blank or `pending_information`, never zero.
- Every new source was published by 2025-12-15. Revisable Census and ONS releases are locked to their dated release vintage and carry revision flags.
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
