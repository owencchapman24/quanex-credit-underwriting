# Calculation validation

The Phase 8 workflow builds the workbook with the bundled artifact runtime, recalculates every approved scenario in LibreOffice 26.8.0.3, captures comparisons, restores Base, saves, and then validates structure and cached results. USD-million and ratio parity use a 0.002 tolerance.

Controls cover the exact 14-sheet order, native formulas and charts, terminal `Checks`, external links, cached formula errors, calculation mode, 32 workbook checks, Base restoration, 15 Python-to-workbook numeric points, and closing coverage remaining `N/D`. The disposable dynamic copy tests scenario changes, fixed historicals, term size, contribution, amortization, rate and spread, EBITDA, DSO, exact covenant boundaries, missing/zero/negative denominators, revolver exhaustion, draw shutoff, cash-floor and sweep safeguards, stale capture status, and full Base restoration.

All sheets are rendered to temporary PNG previews through the artifact runtime and inspected for formulas, styles, hierarchy, widths, status text and chart placement. LibreOffice applies bounded print areas, landscape orientation on wide schedules, fit-to-width settings, and repeated header rows on long tables.

Native engine metadata, capture timestamps, chart-axis identifiers, and sub-point drawing coordinates can change between runs. Deterministic testing therefore compares source signatures and normalized workbook components, excluding volatile core properties, capture timestamp strings, calculation-chain metadata, and engine-rounded drawing-coordinate serialization while canonically mapping chart-axis identifiers. Chart placement is separately validated by structural tests and rendered-sheet review. This is not a claim of byte-identical `.xlsx` archives.
