# Phase 8 methodology

Phase 8 translates the approved Phase 0-7 Python and CSV analysis into one lender-facing `.xlsx` model. It does not revise the 21 owner-reviewed Phase 7 decisions. The calculation direction is `Historicals + Sources + Assumptions -> Transaction + Forecast -> Debt Schedule + Liquidity -> Covenants -> Credit Summary + Scenario Comparison -> Checks`; `Checks` has no outbound dependencies.

## Calculation design

One editable selector on `Assumptions` drives one Forecast, Debt Schedule, Liquidity and Covenants chain. The forecast covers twenty fiscal quarters through January 31, 2031. The debt and liquidity schedules use twenty-four monthly periods followed by twelve non-overlapping quarterly periods. Native formulas select approved scenario-period inputs, calculate forecast subtotals, scale cash interest to debt and rate controls, roll term and revolver balances, retain unpaid mandatory obligations, and distinguish opening, subsequent-minimum and all-in liquidity.

Reported history and approved prior-phase calculated values are imported with source IDs. Transaction mechanics, earnings subtotals, forecast outputs, debt, liquidity, covenant tests, summaries and sensitivities are formulas. Dynamic overlays permit controlled review of term size, non-debt contribution, amortization, rate, EBITDA and DSO without changing the approved saved state.

## Scenario captures and engine

The workbook is authored with the bundled `@oai/artifact-tool` runtime and recalculated by LibreOffice 26.8.0.3 because Microsoft Excel is not installed. The capture workflow selects each of nine approved cases, fully recalculates, stores headline values and signatures, restores Base, recalculates and saves. Captures are snapshots, not parallel live forecasts. A formula-driven stale flag compares each captured signature with the current input signature.

Missing closing cash interest and unresolved legal or diligence items remain `N/D`, `Pending information`, or `Condition precedent`. Zero and nonpositive denominators display `N/M`. The separate book-cash diagnostic is not covenant or lender net leverage. The Recovery sheet remains pending Phase 9. No post-cutoff evidence is added.
