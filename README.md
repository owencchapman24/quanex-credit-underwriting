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
This is a decision to continue the analysis, not a credit approval or a judgment
that the proposed refinancing is preferable to retaining the existing facilities.

- [Case charter](docs/phase-0/CASE_CHARTER.md)
- [Existing financing and refinancing logic](docs/phase-0/EXISTING_FINANCING.md)
- [Evidence inventory](docs/phase-0/EVIDENCE_INVENTORY.csv)
- [Decision log and open items](docs/phase-0/DECISION_LOG.md)

Run the Phase 0 controls with:

```powershell
powershell -NoProfile -File scripts/validate-phase0.ps1
```
