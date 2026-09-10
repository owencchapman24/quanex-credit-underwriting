# Phase 5 integrated base case analysis

**Recommendation:** CONDITIONAL GO for owner review, not final credit approval.

## Operating forecast

Amounts are USD millions. This table contains operating measures only; FY2031
contains Q1 only.

| Fiscal year | Coverage | Revenue | Lender EBITDA | Margin | CFADS before interest | Cash taxes | Capex | Working-capital cash flow |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| FY2026 | full_year | 1,837.595 | 222.274 | 12.10% | 111.967 | -29.708 | -64.316 | -15.582 |
| FY2027 | full_year | 1,837.549 | 222.268 | 12.10% | 128.254 | -29.707 | -64.314 | 0.007 |
| FY2028 | full_year | 1,837.503 | 222.263 | 12.10% | 128.250 | -29.706 | -64.313 | 0.007 |
| FY2029 | full_year | 1,837.457 | 222.257 | 12.10% | 128.247 | -29.706 | -64.311 | 0.007 |
| FY2030 | full_year | 1,837.411 | 222.251 | 12.10% | 128.244 | -29.705 | -64.309 | 0.007 |
| FY2031 | Q1_only | 399.984 | 32.021 | 8.01% | 15.647 | -2.376 | -13.999 | 0.002 |

The model uses the Phase 3 driver chain rather than an EBITDA-growth shortcut.
FY2025 remains the first full post-Tyman anchor. The flat-to-slightly-lower
compound revenue path follows the selected volume and price/mix midpoints.
Gross margin is the primary operating-margin driver. The owner-reviewed
12%-13% lender EBITDA margin is validation only.

FY2031 Q1 has a lower EBITDA margin than each full-year period because the
FY2025 post-Tyman Q1 gross-margin shape is retained while cash operating costs
remain a revenue-based ratio. It is a seasonal-quarter output, not a full-year
margin forecast.

## FY2026 period presentation

| Period | Structure | Revenue | EBITDA | CFADS before interest | Cash interest | CFO proxy | FCF proxy | Status |
|---|---|---:|---:|---:|---:|---:|---:|---|
| FY2026_Q1_pre_closing_operations | common_operating | 400.0339989 | 32.02502371136811080570144005 | 0.30058782918787770867427544 | N/D | N/D | N/D | calculated_operating_only |
| FY2026_Q2_Q4_post_closing | existing | 1437.561060075 | 190.2486370271889141942985599 | 111.6669019281209967468051766 | -31.56751134489467701431921005 | 130.4140276858513197324859666 | 80.0993905832263197324859666 | calculated_post_closing |
| FY2026_Q2_Q4_post_closing | proposed | 1437.561060075 | 190.2486370271889141942985599 | 111.6669019281209967468051766 | -32.07260464845616279376728803 | 129.9089343822898339530378886 | 79.59429727966483395303788862 | calculated_post_closing |
| FY2026_full_year_operating | common_operating | 1837.595058975 | 222.273660738557025 | 111.967489757308874455479452 | N/D | N/D | N/D | calculated_operating_only |
| FY2026_full_year_financing | existing | N/D | N/D | N/D | N/D | N/D | N/D | not_determinable_incomplete_q1_financing |
| FY2026_full_year_financing | proposed | N/D | N/D | N/D | N/D | N/D | N/D | not_determinable_incomplete_q1_financing |

## Proposed reference structure

The February 1 reference debt is USD 650.000m term and USD 29.898m revolver.
Modeled cumulative bank cash interest is USD 168.554m,
scheduled term principal is USD 325.000m, and provisional
cash sweeps are USD 0.000m. Peak revolver usage is
USD 39.954m and minimum usable liquidity is
USD 253.846m. These figures exclude not-determinable
recurring financing fees; the exclusion is not a zero-value assumption.

At January 31, 2031, modeled cash above the operating floor covers
USD 0.000m. The remaining unsupported maturity
funding gap is USD 340.948m. No refinancing source, waiver or
post-maturity availability fills that amount.

## Existing facilities: rate-neutral central comparison

The February 1 retain-existing opening uses USD 462.500m term principal and USD
207.398m of revolver debt after explicitly funding the January installment and
accrued interest. Modeled cumulative bank cash interest in the 6.57% rate-neutral
case is
USD 127.471m and scheduled term principal after
closing is USD 87.500m. Peak revolver usage is
USD 207.398m and minimum usable liquidity is
USD 261.402m. These figures likewise exclude
not-determinable recurring financing fees.

At the August 1, 2029 maturity, only cash above the floor is applied. The
remaining unsupported funding gap is USD 432.749m. Nominal
revolver capacity is not treated as available after maturity.

## Distribution attribution through the common horizon

| Structure | Planned dividends | Planned repurchases | Dividend draw-causing | Repurchase draw-causing | Dividends while revolver outstanding | Repurchases while revolver outstanding | Repurchase amount to suspend/fund differently |
|---|---:|---:|---:|---:|---:|---:|---:|
| existing | 50.750 | 17.500 | 3.640 | 2.083 | 50.750 | 17.500 | 0.000 |
| proposed | 50.750 | 17.500 | 17.047 | 6.754 | 50.750 | 17.500 | 6.754 |

Cash-funded amounts and monthly flags are in `DISTRIBUTION_ANALYSIS.csv`.
Planned distributions are not automatically permitted. A debt-funded proposed
buyback is flagged as not compliant; otherwise public permission remains
pending. No distribution reduction has been treated as completed.

## Financing sensitivities

| Structure | Case | Amortization | Spread | All-in rate | Cumulative interest | Scheduled principal | Sweep | Minimum liquidity | Maturity gap |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| proposed | 5_percent_amortization | 5% | 300 bps | 6.57% | 177.892 | 162.500 | 106.897 | 263.902 | 350.286 |
| proposed | 10_percent_reference | 10% | 300 bps | 6.57% | 168.554 | 325.000 | 0.000 | 253.846 | 340.948 |
| proposed | 15_percent_amortization | 15% | 300 bps | 6.57% | 168.529 | 487.500 | 0.000 | 134.731 | 340.923 |
| proposed | 250_bps_spread | 10% | 250 bps | 6.07% | 153.652 | 325.000 | 5.519 | 259.479 | 326.046 |
| proposed | 300_bps_reference | 10% | 300 bps | 6.57% | 168.554 | 325.000 | 0.000 | 253.846 | 340.948 |
| proposed | 350_bps_spread | 10% | 350 bps | 7.07% | 184.214 | 325.000 | 0.000 | 247.031 | 356.608 |
| existing | pricing_band_1 | 5% | 200 bps | 5.57% | 105.907 | 87.500 | 0.000 | 261.402 | 411.185 |
| existing | pricing_band_2 | 5% | 225 bps | 5.82% | 111.220 | 87.500 | 0.000 | 261.402 | 416.498 |
| existing | pricing_band_3 | 5% | 250 bps | 6.07% | 116.584 | 87.500 | 0.000 | 261.402 | 421.863 |
| existing | pricing_band_4 | 5% | 275 bps | 6.32% | 122.001 | 87.500 | 0.000 | 261.402 | 427.280 |
| existing | 6.57_percent_rate_neutral | 5% | N/A bps | 6.57% | 127.471 | 87.500 | 0.000 | 261.402 | 432.749 |

These rows vary financing terms only. They are not Phase 6 operating downside
cases. A lower technical gap is not an automatic facility-size recommendation.

## Credit interpretation

The build tests whether ordinary modeled cash supports interim interest and
principal while separately exposing maturity dependence. Any unsupported
maturity balance remains a refinancing dependency. Formal covenant compliance
is not determinable because official contractual EBITDA, covenant debt,
eligible cash and testing definitions are unavailable.
Modeled cash flow and liquidity remain before recurring financing fees, which
cannot be quantified from approved evidence. Neither financing alternative
self-liquidates. The proposed reference can meet interim interest and scheduled
principal under these testing assumptions, but both structures retain material
maturity funding gaps.
