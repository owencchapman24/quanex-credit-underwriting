# Workbook guide

Use the blue selector on `Assumptions` to change the live case. Blue financing and sensitivity cells on that sheet are the only model controls. The approved saved state is Base with a $635m term, $300m revolver, $15m conditional non-debt source, 7.5% annual amortization, 6.57% modeled all-in rate and 50% ECF sweep. Green cells are imported approved data or cross-sheet links; black cells are same-sheet formulas. Red font is reserved for external workbook links, and none exist.

`Credit Summary` is the lender-facing overview. `Scenario Comparison` shows the current live case and nine versioned captures. `Forecast`, `Debt Schedule`, `Liquidity`, and `Covenants` are the authoritative live chain. `Historicals`, `Credit Adjustments`, `Transaction`, `Sensitivities`, and `Sources` provide traceability and supporting analysis. `Recovery` is deliberately limited to a Phase 9 pending state. `Checks` is terminal and does not feed another sheet.

A `STALE` capture status means a modeled assumption or structure input changed after capture. Run `python scripts/phase8.py all` to rebuild, recalculate, recapture, restore Base, validate and render temporary previews. Do not treat `N/D` as zero, `N/M` as compliance, warning as breach, or a lower debt balance caused by unpaid obligations or draw shutoff as improved performance.

The workbook is not a lender commitment, official compliance certificate, final credit recommendation, final risk grade, or recovery analysis.
