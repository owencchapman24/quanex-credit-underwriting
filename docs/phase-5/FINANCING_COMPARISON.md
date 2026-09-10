# Phase 5 financing comparison

The same operating base case is applied to both alternatives. The opening
measurement is February 1, 2026 at 00:00, after the alternative-specific
January 31 actions. The hypothetical refinancing closes immediately before the
existing Term A installment.

## Same-point opening bridge

| Item | Existing | Proposed | Date or period |
|---|---:|---:|---|
| October 31, 2025 Term A | 468.75 | 468.75 | 2025-10-31 |
| October 31, 2025 revolver | 172.5 | 172.5 | 2025-10-31 |
| November-January revolver movement | 25 | 25 | 2025-11-01_to_2026-01-31 |
| FY2026 Q1 operating CFADS before cash interest | 0.30058782918787770867427544 | 0.30058782918787770867427544 | 2025-11-01_to_2026-01-31 |
| January 31 Term A installment | 6.25 | 0 | 2026-01-31_immediately_after_closing_timestamp |
| Accrued interest through closing timestamp | 3.64771875 | 3.64771875 | through_2026-01-31_closing |
| Refinancing fees | 0 | 10 | 2026-01-31_closing |
| Existing-debt payoff | 0 | 666.25 | 2026-01-31_closing |
| New term funding | 0 | 650 | 2026-01-31_closing |
| New revolver funding | 0 | 29.89771875 | 2026-01-31_closing |
| Cash retained | 25 | 25 | 2026-02-01_00:00 |
| Letters of credit | 6.2 | 6.2 | 2026-02-01_00:00 |
| Ending term debt | 462.5 | 650 | 2026-02-01_00:00 |
| Ending revolver debt | 207.39771875 | 29.89771875 | 2026-02-01_00:00 |
| Ending total bank debt | 669.89771875 | 679.89771875 | 2026-02-01_00:00 |
| Ending cash | 25 | 25 | 2026-02-01_00:00 |
| Available revolver capacity after LCs | 261.40228125 | 263.90228125 | 2026-02-01_00:00 |
| Previously reported opening bank debt | 660 | 679.89771875 | prior_phase5_presentation |
| Correction to prior existing opening debt | 9.89771875 | 0 | same_point_reconciliation |
| Reconciled proposed less existing bank debt | 0 | 10 | 2026-02-01_00:00 |

The prior USD 19.89771875m difference is fully explained. Existing opening debt
increases by USD 9.89771875m for the revolver-funded USD 6.25m installment and
USD 3.64771875m accrued interest. Reconciled proposed debt exceeds reconciled
existing debt by USD 10m, equal to proposed fees. FY2026 Q1 operating CFADS is
shown but not separately credited against the Phase 4 USD 25m revolver
sensitivity. The same-point USD 25m cash is a testing assumption because actual
January cash is not determinable.

## Common horizon: February 1, 2026 through July 31, 2029

The measurement event is the existing facility maturity on August 1, 2029.
Interest periods are identical.

| Metric | Existing | Proposed | Units |
|---|---:|---:|---|
| opening_term_debt | 462.5 | 650 | USD_millions |
| opening_revolver_debt | 207.39771875 | 29.89771875 | USD_millions |
| opening_total_bank_debt | 669.89771875 | 679.89771875 | USD_millions |
| upfront_fees | 0 | 10 | USD_millions |
| accrued_interest_through_closing | 3.64771875 | 3.64771875 | USD_millions |
| cumulative_cash_interest | 127.4711665797101677540328191 | 130.0565446238712572817742345 | USD_millions |
| cumulative_recurring_financing_fees | not_determinable | not_determinable | USD_millions |
| scheduled_principal | 87.5 | 227.5 | USD_millions |
| revolver_repayments | 169.2340601427289049587548786 | 156.9973388133452991118844743 | USD_millions |
| revolver_draws | 19.58562259943892261368229137 | 149.9342793142164062945533027 | USD_millions |
| cash_sweeps | 0 | 0 | USD_millions |
| planned_distributions | 68.24999999999999999999999996 | 68.24999999999999999999999996 | USD_millions |
| retained_obligation_payments | 25.99775000000000000000000004 | 25.99775000000000000000000004 | USD_millions |
| total_cash_debt_service | 410.2029767224390727127876977 | 540.5516334372165563936587088 | USD_millions |
| total_lender_cash_receipts | 384.2052267224390727127876977 | 514.5538834372165563936587088 | USD_millions |
| ending_term_debt | 375 | 422.5 | USD_millions |
| ending_revolver_debt | 57.74928120671001765492741287 | 22.83465925087110718266882846 | USD_millions |
| ending_total_bank_debt | 432.7492812067100176549274129 | 445.3346592508711071826688285 | USD_millions |
| peak_revolver_usage | 207.39771875 | 39.95416505588877547275839092 | USD_millions |
| minimum_revolver_availability | 261.40228125 | 253.8458349441112245272416091 | USD_millions |
| minimum_usable_liquidity | 261.40228125 | 253.8458349441112245272416091 | USD_millions |
| cash_floor_failure_months | 0 | 0 | count |
| distribution_revolver_draw_flag_months | 5 | 18 | count |
| debt_due_at_august_1_2029_existing_maturity | 432.7492812067100176549274129 | 0 | USD_millions |

Recurring fees are not determinable. Total cash debt service includes bank
interest, retained mandatory payments, scheduled principal, gross revolver
repayments, sweeps and maturity cash application. Total lender cash receipts
exclude retained-obligation payments. Neither measure assumes refinancing.

## Proposed extension period: August 1, 2029 through January 31, 2031

| Metric | Proposed | Units |
|---|---:|---|
| additional_cash_interest | 38.49732782728420684620817772 | USD_millions |
| additional_scheduled_principal | 97.5 | USD_millions |
| additional_revolver_draws | 58.02868859729380322290133198 | USD_millions |
| additional_revolver_repayments | 64.91551662657174965897767717 | USD_millions |
| additional_retained_obligation_payments | 9.307000000000000000000000005 | USD_millions |
| additional_planned_distributions | 29.24999999999999999999999998 | USD_millions |
| additional_cash_sweep | 0 | USD_millions |
| final_funded_bank_debt | 340.9478312215931607465924833 | USD_millions |
| cash_available_above_floor_at_maturity | 0 | USD_millions |
| unsupported_maturity_funding_gap | 340.9478312215931607465924833 | USD_millions |

The proposed structure's lower January 2031 gap benefits from approximately 18
additional months of cash generation and amortization and is not directly
comparable with the existing August 2029 gap without this separation.

## Additional labeled comparisons

| Metric | Existing | Proposed | Units |
|---|---:|---:|---|
| Opening bank funded debt | 669.89771875 | 679.89771875 | USD_millions |
| Opening term principal | 462.5 | 650 | USD_millions |
| Opening revolver | 207.39771875 | 29.89771875 | USD_millions |
| Revolver commitment | 475 | 300 | USD_millions |
| Opening revolver availability after LCs | 261.40228125 | 263.90228125 | USD_millions |
| Accrued interest through closing | 3.64771875 | 3.64771875 | USD_millions |
| Upfront financing and advisory fees | 0 | 10 | USD_millions |
| Recurring financing fees | not_determinable | not_determinable | USD_millions |
| Cumulative cash interest on common horizon | 127.4711665797101677540328191 | 130.0565446238712572817742345 | USD_millions |
| Modeled all-in rate | 6.57_rate_neutral | 6.57_owner_reviewed_midpoint | percent |
| Existing contractual-grid all-in range using 3.57% base proxy | 5.57-6.32 | not_applicable | percent |
| Reference annual scheduled term principal | 25 | 65 | USD_millions |
| Cumulative scheduled term principal | 87.5 | 325 | USD_millions |
| Cumulative provisional cash sweep | 0 | 0 | USD_millions |
| Peak revolver usage | 207.39771875 | 39.95416505588877547275839092 | USD_millions |
| Minimum revolver availability | 261.40228125 | 253.8458349441112245272416091 | USD_millions |
| Minimum usable liquidity | 261.40228125 | 253.8458349441112245272416091 | USD_millions |
| Bank funded debt at existing maturity comparison date | 432.7492812067100176549274129 | 445.3346592508711071826688285 | USD_millions |
| Cash available above floor at maturity | 0 | 0 | USD_millions |
| Unsupported maturity funding gap | 432.7492812067100176549274129 | 340.9478312215931607465924833 | USD_millions |
| Maturity date | 2029-08-01 | 2031-01-31 | date |
| Phase 4 contractual funded principal payments in maturity fiscal year | 566.25 | 371.14771875 | USD_millions |
| Phase 4 contractual final rolling-12-month funded payments | 572.5 | 419.89771875 | USD_millions |
| Borrower flexibility | existing_document_terms | more_restrictive_provisional_package | text |
| Limited amendment or extension | live_qualitative_alternative | not_applicable | text |

The proposed structure lowers opening revolver use and extends maturity, but it
has a USD 175m smaller revolver commitment, faster scheduled amortization, USD
10m of fees and additional restrictions. The central interest comparison is
rate-neutral at 6.57%. Existing contractual pricing spans 5.57%-6.32% when the
approved 200-275 bps grid is applied to the 3.57% test base rate, but the
applicable January 2026 tier is not determinable. The 6.57% existing case is not
claimed as actual or representative economics.

Neither alternative is shown as self-funding its maturity obligation through an
assumed refinancing. The unsupported maturity gap is explicit. No conclusion
that the proposed refinancing is economically superior is made. Retention of
the existing facilities and a limited amendment or extension remain live.
