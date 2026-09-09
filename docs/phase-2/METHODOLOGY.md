# Phase 2 methodology and control framework

**Information cutoff:** December 15, 2025

## Scope

Phase 2 consumes the committed Phase 1 foundation and produces a reconciled
FY2021-FY2025 consolidated spread, earnings bridges, reviewed adjustments,
credit metrics, and evidence-derived Phase 3 questions. It does not forecast,
size a refinancing, calculate closing liquidity, produce an official covenant
calculation, or begin Phase 3.

No new source was added. `SUPPLEMENTAL_FACTS.csv` transcribes balance-sheet
totals, detailed cash-flow lines, cash roll-forwards, financing flows, and
FY2021-FY2023 debt principal from SRC-001, SRC-012, and SRC-014 because those
controls were not fields in the Phase 1 extract. The approved archival URLs and
publication dates remain in the Phase 1 manifest and ledgers.

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
interest is already inside US-GAAP CFO and is not subtracted again. Gross funded
debt uses principal, including finance leases/other debt; carrying debt is kept
separate. Net debt using book cash is an analyst comparable, not the contractual
numerator because eligible cash is not public.

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
