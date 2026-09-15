# Phase 8 methodology

Phase 8 translates the approved Phase 0-7 Python and CSV analysis into one lender-facing `.xlsx` model. It does not revise the 21 owner-reviewed Phase 7 decisions. The calculation direction is `Historicals + Sources + Assumptions -> Transaction + Forecast -> Debt Schedule + Liquidity -> Covenants -> Credit Summary + Scenario Comparison -> Checks`; `Checks` has no outbound dependencies.

## Calculation design

One editable selector on `Assumptions` drives one Forecast, Debt Schedule, Liquidity and Covenants chain. The forecast covers twenty fiscal quarters through January 31, 2031. The debt and liquidity schedules use twenty-four monthly periods followed by twelve non-overlapping quarterly periods. Native formulas select approved scenario-period inputs, calculate forecast subtotals, scale cash interest to debt and rate controls, roll term and revolver balances, retain unpaid mandatory obligations, and distinguish opening, subsequent-minimum and all-in liquidity.

Reported history and approved prior-phase calculated values are imported with source IDs. Transaction mechanics, earnings subtotals, forecast outputs, debt, liquidity, covenant tests, summaries and sensitivities are formulas. Dynamic overlays permit controlled review of term size, non-debt contribution, amortization, rate, EBITDA and DSO without changing the approved saved state.

## Scenario captures and engine

The workbook is authored with the bundled `@oai/artifact-tool` runtime and reproducibly recalculated by LibreOffice 26.8.0.3. Microsoft Excel for Microsoft 365 provides a separate compatibility gate. The capture workflow selects each of nine approved cases, fully recalculates, stores headline values and typed input states, restores Base, recalculates and saves. Captures are snapshots, not parallel live forecasts. A formula-driven stale flag compares each captured typed state with the complete current input state; numeric serialization is normalized at 12 decimal places to avoid sub-ULP cross-engine noise while retaining sensitivity far below any economically meaningful input increment. Dynamic interaction evidence is stored separately under `P8-DYNAMIC-2.0`: all 60 explicitly identified cases must be unique and PASS, with matching stage, scenario, input scope, engine, scripts, builder, source signature, test-definition digest, and tested-artifact identity. Missing, truncated, duplicated, failed, not-run, or stale evidence cannot pass.

The Transaction sheet separates the October 31, 2025 historical debt reference from January 31, 2026 projected alternatives. Term sizing uses approved Phase 7 source pairings and reports sources less uses explicitly. Amortization sensitivity reruns the selected structure through the Phase 7 cash, revolver, interest, sweep, liquidity, covenant, and maturity engine; it is not a shortcut maturity-gap adjustment. Incomplete LTM periods display `N/D`; `N/M` is reserved for complete periods with nonpositive EBITDA or another nonpositive required denominator.

## Post-commit Excel compatibility correction

The first desktop-Excel opening of commit `b52141dadeb91362cac7cece9b31ec0f3e573534` reported a removed formula record in `sheet14.xml`. Package mapping identifies that part as `Checks`; the exact incompatible record was `Checks!G20`, whose `COUNTIF` used an inline array constant as the range argument. LibreOffice evaluated that permissive extension, but Excel requires `COUNTIF`'s first argument to be a range. The builder now expresses the same nine-value membership test with ordinary `OR` comparisons. No business calculation depends on `Checks`.

Microsoft Excel for Microsoft 365 version 16.0 build 20326 opened the corrected workbook normally, performed a full calculation rebuild, changed the selector to Moderate unmitigated, restored Base, saved a disposable copy, and reopened that copy without repair. Formula and Checks counts are re-established after each bounded generator revision, and no recovery log may be generated.

Missing closing cash interest and unresolved legal or diligence items remain `N/D`, `Pending information`, or `Condition precedent`. Zero and nonpositive denominators display `N/M`. The separate book-cash diagnostic is not covenant or lender net leverage. The Recovery sheet remains pending Phase 9. No post-cutoff evidence is added.
