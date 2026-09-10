# quanex-credit-underwriting

Public-information underwriting of a hypothetical Quanex Building Products
Corporation refinancing: repayment capacity, downside liquidity, debt structure,
covenants, and an auditable Excel credit model.

## Current phase

Phase 0 (case mandate and evidence-feasibility gate) is complete. The committee
date and substantive-information cutoff are both **December 15, 2025**. No
borrower, financial, operating, financing, management, or industry information
first published after that date may enter the original underwriting record.

Phase 0 concluded **GO to Phase 1, subject to documented diligence conditions**.
Phase 1 now provides a source-traceable FY2021-FY2025 data foundation and a
structured existing-debt register. Its handoff is **CONDITIONAL GO to Phase 2**;
this is not a credit approval, a lender-normalized EBITDA conclusion, or a
judgment that refinancing is preferable to retaining the existing facilities.
Phase 2 adds a reconciled five-year spread, historical cash-flow and debt
controls, and low/base/high lender-normalization cases. The project owner has
reviewed the Phase 2 lender-base judgments; contractual eligibility, cash-flow
treatment, and remaining diligence limitations stay separately identified.
Phase 3 adds a cutoff-controlled borrower and industry evidence layer, an
eight-quarter operating/cash trend, and owner-reviewed base/moderate/severe
calibration ranges. The reviewed ranges are not period forecasts; FX and
payables/other-operating-working-capital methods remain pending, and no scenario
has been run. Phase 4 adds the debt-instrument and legal-structure registers,
low/reference/high projected-closing sensitivities, sources and uses,
principal-only amortization schedules, a provisional term sheet, financing-
alternative economics, closing conditions, and a Phase 5 opening-input
specification. The owner-reviewed low/reference/pressure cases and selected
provisional structure are approved only for Phase 5 testing; actual payoff,
cash, fee, interest, hedge, LC, legal and commitment evidence remains pending.
Corrected maturity outputs separate installments, post-installment balloons,
maturity-date funded principal, Quanex fiscal-year payments and rolling-12-month
payments. Phase 4 retains the existing facilities and a limited amendment or
extension as live alternatives and does not conclude that refinancing is
economically preferable. No actual January 2026 information or integrated
forecast is used.

- [Case charter](docs/phase-0/CASE_CHARTER.md)
- [Existing financing and refinancing logic](docs/phase-0/EXISTING_FINANCING.md)
- [Evidence inventory](docs/phase-0/EVIDENCE_INVENTORY.csv)
- [Decision log and open items](docs/phase-0/DECISION_LOG.md)
- [Phase 1 methodology and completion record](docs/phase-1/METHODOLOGY.md)
- [Phase 1 data dictionary](docs/phase-1/DATA_DICTIONARY.md)
- [Tyman acquisition comparability map](docs/phase-1/ACQUISITION_COMPARABILITY.md)
- [Phase 1 source ledger](docs/phase-1/SOURCE_LEDGER.csv)
- [Phase 2 methodology](docs/phase-2/METHODOLOGY.md)
- [Phase 2 reconciled credit analysis](docs/phase-2/CREDIT_ANALYSIS.md)
- [Phase 3 evidence-driven handoff questions](docs/phase-2/PHASE3_HANDOFF.md)
- [Phase 2 source ledger](docs/phase-2/SOURCE_LEDGER.csv)
- [Phase 3 methodology](docs/phase-3/METHODOLOGY.md)
- [Phase 3 borrower and industry driver brief](docs/phase-3/BORROWER_INDUSTRY_BRIEF.md)
- [Phase 4 bounded handoff](docs/phase-3/PHASE4_HANDOFF.md)
- [Phase 3 source ledger](docs/phase-3/SOURCE_LEDGER.csv)
- [Phase 4 methodology and closing cases](docs/phase-4/METHODOLOGY.md)
- [Phase 4 provisional term sheet](docs/phase-4/PROVISIONAL_TERM_SHEET.md)
- [Phase 4 public legal-structure summary](docs/phase-4/LEGAL_STRUCTURE_SUMMARY.md)
- [Phase 5 opening-input handoff](docs/phase-4/PHASE5_HANDOFF.md)
- [Phase 4 source ledger](docs/phase-4/SOURCE_LEDGER.csv)

Run the Phase 0 controls with:

```powershell
powershell -NoProfile -File scripts/validate-phase0.ps1
```

Run the Phase 1 pipeline and material-risk tests with:

```powershell
python scripts/phase1.py all
python -m unittest discover -s tests -v
```

Phase 1 uses only the Python standard library and performs no network access.

Run the Phase 2 workflow and tests with:

```powershell
python scripts/phase2.py all
python -m unittest discover -s tests -v
```

Phase 2 also uses only the Python standard library and performs no network
access. It does not contain forecasts, transaction sizing, or final human
approval of credit adjustments.

Run the Phase 3 workflow and all decision-relevant tests with:

```powershell
python scripts/phase3.py all
python -m unittest discover -s tests -v
```

Phase 3 uses only the Python standard library and performs no live network
access. It preserves owner-reviewed calibration decisions but does not construct
projected statements, run scenarios, size a facility, or begin Phase 4.

Run the Phase 4 workflow and all decision-relevant tests with:

```powershell
python scripts/phase4.py all
python -m unittest discover -s tests -v
```

Phase 4 also uses only the Python standard library and performs no live network
access. It does not finalize the refinancing, build projected operating
statements, integrate cash interest, establish final debt capacity or covenants,
or begin Phase 5. Owner-reviewed leverage, coverage and liquidity levels are
initial analytical test thresholds only; Phase 7 retains final covenant design.
