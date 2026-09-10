# Phase 6 methodology

## Purpose and boundary

Phase 6 applies borrower-specific downside mechanisms to the approved Phase 5 base case. It does not resize the financing, finalize covenants, assume a waiver or refinancing, perform recovery analysis, or start Phase 7. All monetary values are USD millions and all calculations retain `Decimal` precision; displayed values may be rounded.

## Scenario architecture

The model starts each structure on February 1, 2026. `BASE` is a zero-shock parity run. Moderate and severe paths transmit volume once through revenue; gross-margin pressure once through gross profit, including fixed-cost absorption; DSO, DIO, AP, and other current-balance changes through explicit balance mechanics; cash-only remediation below EBITDA; and the rate shock once through the all-in rate. No generic EBITDA or working-capital plug is used.

The moderate shock is held for four quarters and then recovers by 75%, 50%, and 25% residual factors in FY2027 Q2-Q4, with full recovery in FY2028 Q1. The severe shock is held for eight quarters and then recovers by 80%, 60%, 40%, and 20% residual factors through FY2029 Q1, with full recovery in FY2029 Q2. Equal monthly allocation is the neutral timing convention. Stressed allocations of 20%/30%/50% (moderate) and 10%/25%/65% (severe) are conservative underwriting sensitivities. Neither convention is verified actual monthly seasonality, so exact event dates depend on the selected timing case.

## Cash, debt, and interest

The payment order is cash interest, retained contractual obligations, scheduled term principal, dividends, and repurchases. A mandatory-payment failure means unpaid cash interest, unpaid scheduled term principal, or an unpaid retained mandatory obligation. Missed dividends and repurchases remain separately reported and are not lender payment defaults. A maturity balloon shortfall is separately classified as `MATURITY_SHORTFALL`. In failure-event records, cash available before payment means cash plus any capacity that remains both available and drawable immediately before the failed obligation; cash remaining after payment is the resulting cash balance. Revolver draws restore the $25m operating cash floor when capacity and modeled drawability remain. Surplus cash first repays the revolver; the Phase 5 October sweep follows only after revolver repayment and preserves the $50m analytical liquidity safeguard. Interest is iterated from average monthly term and revolver balances, so additional draws increase later interest.

The headline revolver exposure is the greater of the opening balance and all subsequent modeled month-end balances. The opening balance, the peak subsequent period-end balance, and the headline peak are stored separately. `OPENING_POSITION` identifies a headline peak that occurs at closing. The draw event field identifies the first incremental post-closing draw; opening revolver debt is never classified as an incremental draw.

Maturity capacity becomes zero and available cash above the floor is applied to the revolver and then the term loan. Remaining principal is an unsupported maturity gap; no refinancing is assumed.

## Thresholds and drawability

The model separately reports gross funded leverage, book-cash net leverage (diagnostic only), analytical bank leverage, EBITDA/cash-interest coverage, CFADS/cash-interest coverage, CFADS/scheduled-debt-service coverage, and usable liquidity. The 3.25x/3.00x leverage, 3.00x coverage, and $50m liquidity levels are analytical warnings, not final covenants.

Formal contractual compliance is `NOT_DETERMINABLE`. The proposed no-waiver path switches off new revolver draws beginning the month after the first modeled analytical failure. The continued-drawability path leaves capacity available. Existing-facility drawability is never switched off from this unofficial reconstruction.

## Mitigations and limitations

Only two dated actions receive modeled credit: share-repurchase suspension beginning May 1, 2026 in both mitigated cases and a 50% dividend reduction from that date in the severe mitigated case. Costs are modeled at zero because these distribution actions have no direct implementation cost, but board action and legal permission are not assumed certain. Scheduled policy reductions are reported separately from realized cash preservation. A distribution already unpaid in the unmitigated failure path receives no mitigation credit. Other Phase 3 mitigations remain visible with zero or not-determinable credit.

Recurring financing fees, actual closing cash, eligible cash, covenant definitions, foreign-cash accessibility, proposed legal terms, and amendment economics remain unavailable. The owner reviewed scenario severity, exact timing, recovery, the two modeled capital-allocation actions, and the no-waiver convention for Phase 6 analytical testing only. They are not management forecasts, final underwriting assumptions, contractual conclusions, or final loan terms. The proposed no-waiver path is not a legal conclusion, official covenant calculation, or prediction that lenders would refuse a waiver; it is not applied to the existing facilities because formal compliance cannot be reconstructed.
