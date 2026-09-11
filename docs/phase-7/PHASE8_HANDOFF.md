# Phase 8 handoff

All 21 Phase 7 structuring decisions are owner reviewed for the public-information underwriting structure. Phase 8 may use the formula-ready input CSV only after Phase 8 is separately authorized. This review is not a lender commitment, final legal drafting, official compliance calculation, or evidence that unresolved information exists.

## Required model implementation

1. Build the selected $635m term commitment and funding, conditional $15m non-debt source, opening revolver and retained debt as separate inputs. Retain the exact $639.851m term allocation only as an analytical boundary.
2. Preserve gross funded leverage, zero-cash net leverage and capped-cash diagnostic as separate measures. Do not use book cash in covenant calculations.
3. Implement 7.5% annual amortization quarterly and the 50% ECF sweep after revolver repayment without deducting distributions or double-counting operating uses.
4. Implement proposed covenant, warning and operational cash-floor tests separately. Show ratio, debt, EBITDA, coverage and liquidity headroom.
5. Preserve the continued-draw/waiver, Phase 7 covenant-linked no-waiver, and inherited Phase 6 analytical-shutoff paths separately. A warning does not terminate drawings.
6. Implement the owner-reviewed repurchase and dividend rules while preserving that Phase 7 took no cash-flow credit for them.
7. Retain all unsupported maturity gaps and do not assume refinancing.

## Information still required

- Final payoff, fees, hedge termination, LC transition and sources-and-uses evidence.
- Evidence that at least $15.000m of non-debt funding is accessible without reducing the $25m operating cash floor.
- Proposed legal definitions for funded debt, lender EBITDA, eligible cash, ECF, pro forma transactions, restricted payments, draw conditions, cures and events of default.
- Amendment or extension pricing, tenor, fees and covenant proposal.
- Final collateral, guarantor, perfection and foreign-cash analysis.

- Complete LTM cash-interest data for closing coverage; preserve `N/D` until it exists and use `N/M` only for a nonpositive denominator.
- Final lender and legal definition of the owner-reviewed 3.50x initial maintenance covenant; the 3.25x alternative remains a sensitivity, not the selected proposal.

## Selected outputs to preserve

- Closing warning: not_determinable; closing covenant: not_determinable; closing coverage: N/D.
- Common-horizon selected ending funded debt: $514.754m; opening liquidity: $263.902m; subsequent minimum: $270.341m on 2026-02-28; all-in minimum: $263.902m at OPENING_POSITION.
- Selected ultimate-maturity gap: $324.780m; reference facility gap: $340.948m on its earlier maturity.
- Sources-and-uses control: $0.000m.

## Scenario findings to preserve

- BASE: first warning none; first breach none; first draw shutoff none; opening liquidity $263.902m; subsequent minimum $270.341m on 2026-02-28; all-in minimum $263.902m at OPENING_POSITION; first mandatory failure none; maturity gap $324.780m.
- MODERATE_UNMITIGATED: first warning 2026-10-31; first breach 2026-10-31; first draw shutoff none; opening liquidity $263.902m; subsequent minimum $165.078m on 2027-01-31; all-in minimum $165.078m at 2027-01-31; first mandatory failure none; maturity gap $408.375m.
- SEVERE_UNMITIGATED: first warning 2026-04-30; first breach 2026-10-31; first draw shutoff none; opening liquidity $263.902m; subsequent minimum $0.000m on 2027-07-31; all-in minimum $0.000m at 2027-07-31; first mandatory failure 2027-12-31; maturity gap $604.258m.
- MODERATE_MITIGATED: first warning 2026-10-31; first breach 2026-10-31; first draw shutoff none; opening liquidity $263.902m; subsequent minimum $168.937m on 2027-01-31; all-in minimum $168.937m at 2027-01-31; first mandatory failure none; maturity gap $381.133m.
- SEVERE_MITIGATED: first warning 2026-04-30; first breach 2026-10-31; first draw shutoff none; opening liquidity $263.902m; subsequent minimum $0.000m on 2027-11-30; all-in minimum $0.000m at 2027-11-30; first mandatory failure 2028-01-31; maturity gap $554.718m.
- MODERATE_NO_WAIVER: first warning 2026-10-31; first breach 2026-10-31; first draw shutoff 2026-11-30; opening liquidity $263.902m; subsequent minimum $0.000m on 2026-11-30; all-in minimum $0.000m at 2026-11-30; first mandatory failure none; maturity gap $396.875m.
- SEVERE_NO_WAIVER: first warning 2026-04-30; first breach 2026-10-31; first draw shutoff 2026-11-30; opening liquidity $263.902m; subsequent minimum $0.000m on 2026-11-30; all-in minimum $0.000m at 2026-11-30; first mandatory failure 2027-02-28; maturity gap $538.041m.
- MODERATE_PHASE7_COVENANT_NO_WAIVER: first warning 2026-10-31; first breach 2026-10-31; first draw shutoff 2026-11-30; opening liquidity $263.902m; subsequent minimum $0.000m on 2026-11-30; all-in minimum $0.000m at 2026-11-30; first mandatory failure none; maturity gap $396.875m.
- SEVERE_PHASE7_COVENANT_NO_WAIVER: first warning 2026-04-30; first breach 2026-10-31; first draw shutoff 2026-11-30; opening liquidity $263.902m; subsequent minimum $0.000m on 2026-11-30; all-in minimum $0.000m at 2026-11-30; first mandatory failure 2027-02-28; maturity gap $538.041m.
