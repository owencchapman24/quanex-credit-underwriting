# Phase 4 methodology

**Information cutoff:** December 15, 2025
**Hypothetical closing:** January 31, 2026

## Scope and classification

Phase 4 converts the approved debt evidence into a debt-instrument register,
public legal-structure map, three closing sensitivities, sources and uses,
principal-only schedules, a provisional term sheet, refinancing economics,
closing conditions, and Phase 5 opening inputs. It does not use actual January
2026 information, build an operating forecast, integrate interest, finalize debt
capacity or covenants, or begin Phase 5.

Reported October 31 facts remain separate from formula-driven calculations,
hypothetical proposed terms, sensitivities, and pending private information.
The three closing cases and the selected provisional structure are now
owner-reviewed only for Phase 5 testing. That status does not turn a sensitivity
into an actual January balance, a lender commitment, a final covenant, or a
satisfied closing condition. Unselected and private terms remain pending.

## Closing cases

The cases are not forecasts. They test unresolved mechanics without a cash plug.
The reference $25m revolver movement is a principal-balance sensitivity informed
by the observed $24.134m FY2025 Q1 FCF trough; the $50m pressure movement is an
approximately two-times calibration. Historical FCF is not a detailed
October-to-January cash forecast or a separately additive closing use. Accrued
interest is unpaid payoff interest calculated at the reported 6.57% October
rate for 0/30/60 days. Phase 5 must replace this shortcut with an integrated
cash, interest and revolver schedule and reconcile the two so cash interest
already embedded in historical FCF is not counted twice. Exact payoff, fee,
hedge and LC amounts remain closing diligence.

| Case | Bank payoff | Total uses | New term | Term-only gap | Opening revolver | Nominal availability | Residual gap |
|---|---:|---:|---:|---:|---:|---:|---:|
| CC-LOW / minimum_payoff | 635.000 | 640.000 | 640.000 | 0.000 | 0.000 | 293.800 | 0.000 |
| CC-REF / reference_case | 666.250 | 679.898 | 650.000 | 29.898 | 29.898 | 263.902 | 0.000 |
| CC-HIGH / funding_pressure | 691.250 | 735.019 | 650.000 | 85.019 | 85.019 | 214.981 | 0.000 |

The funding waterfall uses approved borrower cash first (zero in every case
because accessible cash is not publicly established), then new term funding up
to $650m, then an explicit opening revolver draw up to the unused $300m capacity
after replacement LCs. Any residual remains a visible funding gap. The revolver
draw is therefore a documented source, not an unexplained balancing plug.

The January $6.25m old-facility amortization is paid before closing only in the
low case. In the reference case it is identified as a component of the full
payoff and is not added twice. In the pressure case the old installment would
fall after/collapse into refinancing and therefore does not occur separately.

In the pressure case, $6.2m is funded once as LC cash collateral. It creates
restricted cash or another separately classified restricted asset, is excluded
from usable operating liquidity, and is not also deducted as a replacement LC.
Replacement under a new revolver would be a separate alternative, never a
simultaneous second treatment.

## Debt and lease measurement

Bank leverage and payoff use gross principal. The $11.040m deferred-financing-
cost balance is contra-debt, not principal. The $62.619m finance leases and other
debt are retained: $60.733m is identifiable finance-lease liability and the
$1.886m balance is a calculated other-debt residual. Operating leases of
$160.905m are retained separately and are not called funded debt.

Lease maturity rows preserve undiscounted contractual payments. They must not be
summed to present-value liabilities without the disclosed discount. Proposed
term schedules have 20 full quarterly installments beginning April 30, 2026;
actual business-day and stub provisions require final documents.

## Corrected maturity definitions

Section 2.3 of the executed agreement requires the existing Term A to amortize
on the last Business Day of each fiscal quarter. The $468.75m October 31, 2025
balance implies 15 remaining $6.25m installments from January 2026 through July
2029, followed by a $375.00m term balloon on August 1, 2029. The schedule uses a
weekend-adjusted last-weekday proxy; the Agent holiday calendar remains payoff
diligence.

The reported $566.25m is **not** a maturity-date balloon. It is total bank-
facility principal paid in Quanex FY2029: $18.75m of quarterly installments,
$375.00m of Term A balloon, and $172.50m of assumed unchanged revolver principal.
The actual funded principal due on August 1, 2029 is $547.50m because the final
$6.25m quarterly installment occurs July 31, 2029.

The table separates the Quanex reporting fiscal year containing maturity from
the final rolling 12 months ending at maturity. This is necessary because
Quanex FY2031 contains only the January 31, 2031 proposed payment, while the
rolling 12-month period contains four quarterly payments.

| Measure ($m) | Existing FY2029 | Proposed reference FY2031 | Existing final 12m | Proposed reference final 12m |
|---|---:|---:|---:|---:|
| Term principal at period beginning | 393.75 | 341.25 | 400 | 390 |
| Scheduled term principal during period | 18.75 | 16.25 | 25 | 65 |
| Final installment due on maturity date | 0 | 16.25 | 0 | 16.25 |
| Post-installment term balloon | 375 | 325 | 375 | 325 |
| Total term principal due on maturity date | 375 | 341.25 | 375 | 341.25 |
| Revolver principal due on maturity date | 172.5 | 29.89771875 | 172.5 | 29.89771875 |
| Total funded principal due on maturity date | 547.5 | 371.14771875 | 547.5 | 371.14771875 |
| Total funded principal payments during period | 566.25 | 371.14771875 | 572.5 | 419.89771875 |

Retained finance-lease and other-debt maturities stay separate. The public
annual buckets provide $6.498m for FY2029 but place FY2031 and later payments in
an unallocated `Thereafter` bucket, so an exact proposed-maturity-period amount
is not determinable. Revolver principal is held unchanged from the applicable
starting/reference balance solely for this maturity comparison.

## Economics and limitations

Spread break-even uses a constant $650m principal only to isolate existing
SOFR-margin bands of 200-275 bps from hypothetical proposed spreads of 250-350
bps. It excludes principal decline, revolver mix, benchmark/floor differences,
hedges, taxes and fee accounting. Positive values are annual spread savings;
negative values are costs. No proposed spread or fee is a market quote.

The reference case leaves no residual funding gap after a calculated
$29.898m opening revolver draw, but this is
not evidence that a $300m revolver is sufficient through seasonal or downside
conditions. That question belongs to Phase 5-6.

Owner review directs Phase 5 to test the reference refinancing while retaining
the existing facilities and a limited amendment/extension as live alternatives.
Phase 4 does not establish that refinancing is economically preferable: the
maturity extension is only about 18 months, the revolver is $175m smaller,
reference opening availability is below reported existing availability,
scheduled amortization is higher, and pricing may be more expensive. Only the
most favorable spread pairing produces savings, and fee recovery can consume
much of the five-year tenor.

## Reproduction

```powershell
python scripts/phase1.py validate
python scripts/phase2.py all
python scripts/phase3.py all
python scripts/phase4.py all
python -m unittest discover -s tests -v
powershell -ExecutionPolicy Bypass -NoProfile -File scripts/validate-phase0.ps1
```

Python standard library only; the workflow performs no live network access.
