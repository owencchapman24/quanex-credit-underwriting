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
