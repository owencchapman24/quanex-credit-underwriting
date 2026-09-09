# Phase 1 methodology and completion record

**Information cutoff:** December 15, 2025
**Historical period:** FY2021-FY2025
**Committee date:** December 15, 2025
**Hypothetical refinancing close:** January 31, 2026

## Purpose and boundaries

This phase creates a case-specific evidence and normalization layer for later
credit work. It does not decide lender-normalized EBITDA, forecast performance,
size a refinancing, set covenant levels, build the final Excel model, or make a
credit recommendation. The proposed refinancing remains hypothetical, and the
existing facilities remain a live alternative.

The four data layers are kept separate:

1. source-faithful reported historical facts;
2. company-disclosed unaudited Tyman pro forma facts;
3. mechanical calculations from reported facts; and
4. company-disclosed, unreviewed adjustment candidates.

There are no analyst assumptions or accepted lender EBITDA adjustments in the
Phase 1 datasets.

## Required Phase 1 source set

| ID | Source | Phase 1 use |
|---|---|---|
| SRC-001 | FY2025 Form 10-K | FY2023-FY2025 statements, FY2024-FY2025 balance sheets, debt balances, accounting and comparability review |
| SRC-002 | Q4/FY2025 results release | Debt reconciliation and company non-GAAP adjustment candidates |
| SRC-003 | Amendment No. 1 and conformed credit agreement | Operative facility terms and covenant language |
| SRC-004 | Original 2022 credit agreement | Contract lineage and unchanged provisions |
| SRC-008 | Tyman unaudited pro forma exhibit | Separate company-disclosed combined pro forma layer |
| SRC-012 | FY2024 Form 10-K | FY2023 balance sheet, acquisition-period review, and FY2022-FY2024 pro forma summary |
| SRC-013 | FY2023 Form 10-K | Pre-Tyman presentation and accounting-policy review |
| SRC-014 | FY2022 Form 10-K | FY2021-FY2022 statements and balance sheets |
| SRC-016 | June 5, 2025 results release | Acquisition covenant step-up timing |

All nine references were already approved in the Phase 0 evidence inventory and
were published no later than the cutoff. `data/raw/SOURCE_MANIFEST.csv` is an
exact allowlist; validation fails if it is expanded or reordered.

The SEC archive returned HTTP 403 to automated downloads from this environment,
including with an identifiable user agent. Phase 1 therefore uses the permitted
"reproducibly referenced" route: exact SEC archive URLs remain in the manifest,
and source-faithful statement extracts with page/section references are retained
in raw CSVs. No live download is required to rebuild the processed data.

## Workflow

From the repository root:

```powershell
python scripts/phase1.py all
python -m unittest discover -s tests -v
```

`all` recreates the bounded source extracts (without overwriting an existing
manual-override register), builds processed data, creates the source ledger, and
runs credit-risk validation. It uses only the Python standard library. Inputs are
USD thousands unless explicitly stated; normalized monetary
values are USD millions. Expenses and cash outflows are negative in normalized
data. Balance-sheet facts are instants; income and cash-flow facts retain exact
annual start and end dates.

## Manual-entry and override record

The raw CSVs are deterministic transcriptions and structured legal summaries
from the approved primary sources. They are manual ingestion, not analyst
overrides. Every one of the 174 reported facts, 37 company pro forma facts, 11
adjustment candidates, and 51 debt-term records is enumerated in
`SOURCE_LEDGER.csv` with source ID, document, URL, period, location, original
value, units, normalized value or term, classification, and limitations. The
ledger has 302 records: nine source-document entries plus 293 fact, candidate,
calculation, and term entries.

**Active manual overrides: none.** `data/raw/MANUAL_OVERRIDES.csv` contains only
the control header. Any future override must identify the reason, source,
affected fact and period, original and replacement values, reviewer note, and
status; incomplete overrides fail validation.

## Conflicts and missing information

**Unresolved conflicting facts: none.** Two source differences are deliberately
preserved and resolved. First, FY2025 Form 10-K Note 9 says the Consolidated Net
Leverage Ratio "must be greater than" 3.25x, while MD&A and section 7.1 of the
executed agreement say it must **not** be greater than 3.25x. The executed
agreement controls, so 3.25x is a maximum. Both records remain visible in the
debt register. Second, the October 16, 2024 pro forma exhibit reports FY2023 pro
forma net income of $48.457 million, while the later FY2024 10-K summary reports
$48.458 million. Both variants remain in the pro forma dataset; the later 10-K
controls for its summary presentation. The $1 thousand difference is immaterial
but is not silently erased.

Material missing or inseparable items are:

- FY2021 and FY2022 do not present a dedicated material acquisition-cash-flow
  line in the selected statements; those values are absent, not filled with zero.
- The FY2025 $10.263 million company reconciling category combines transaction,
  advisory, reorganization, and product-recall items; the components are not
  separately determinable from the selected disclosure.
- The company pro forma exhibit does not provide an audited, recurring combined
  historical series or a substitute for reported results.
- Public evidence does not provide the complete contractual covenant calculation,
  numerical covenant headroom, or eligible-cash amount at October 31, 2025.

The debt register has seven `not_determinable` items: the complete current named
guarantor schedule; exact post-Tyman joinders, pledged equity, exclusions and
perfection; undisclosed fee-letter economics; eligible covenant cash; published
covenant headroom; hypothetical refinancing hedge/break costs; and January 2026
closing balances.

## Reporting and comparability findings

- FY2021-FY2023 are pre-Tyman reported periods. FY2023 also includes the LMI
  acquisition from November 1, 2022; the company disclosed $91.3 million of
  acquisition cash flow.
- Tyman closed August 1, 2024. FY2024 reported results contain only three months
  of Tyman, while the October 31, 2024 balance sheet is post-acquisition.
- FY2025 is the first full reported post-Tyman year, but it contains integration,
  purchase-accounting, restructuring, product-recall, and impairment effects.
- During FY2025 the company moved from four reportable segments to Hardware,
  Extruded, and Custom Solutions and recast FY2024 and FY2023 segment disclosures.
  This does not create comparable pre-acquisition combined-company history.
- The Tyman pro forma exhibit is unaudited, uses preliminary purchase-price and
  financing adjustments, converts Tyman IFRS/GBP information to U.S. GAAP/USD,
  warns that further policy differences may remain, and excludes integration
  costs and synergies. It is never merged into reported history.
- The FY2024 10-K later provides summary Tyman/LMI pro forma revenue and net
  income for FY2022-FY2024. These records remain distinct from the more detailed
  October 2024 exhibit and from reported results.
- FY2025 includes a $302.284 million goodwill impairment triggered in connection
  with segment restructuring. Goodwill therefore is not directly comparable.
- FY2025 also includes a disclosed $9.0 million discrete income-tax charge for
  post-measurement-period corrections to Tyman acquisition deferred taxes. It is
  captured as an unreviewed earnings-quality candidate, not an EBITDA addback.
- The cash-flow statement preparation/review material weakness identified at
  October 31, 2024 remained unremediated at October 31, 2025. The company said it
  caused no identified financial-statement misstatement or revision, but Phase 2
  should apply heightened reconciliation discipline to cash-flow analysis.
- Current-asset presentation becomes more granular in FY2024-FY2025 (`prepaid`
  and `other current assets` separately) than in FY2021-FY2023 (combined).
  The dataset preserves those different labels instead of silently combining them.

No restatement or discontinued-operation adjustment was identified in the
selected consolidated history. This conclusion is bounded to the approved Phase
1 sources and is not a representation that no immaterial classification changes
exist.

## Phase 2 handoff

Phase 2 must decide whether any company adjustment candidate is acceptable,
avoid treating pro forma data as reported history, assess the FY2025 impairment
and composite integration categories, reconcile cash flow with extra care, and
request diligence for covenant headroom, eligible cash, guarantors/collateral,
and fee-letter economics. It must not treat October 31, 2025 debt as a January
31, 2026 closing balance.

**Recommendation: CONDITIONAL GO to Phase 2.** The foundation is sufficient for
earnings-quality and credit-adjustment work, provided Phase 2 maintains the
separate acquisition layers and treats the enumerated diligence gaps as open.
