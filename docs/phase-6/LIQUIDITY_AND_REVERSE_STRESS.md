# Liquidity and reverse stress

## Liquidity mechanics and distribution attribution

Monthly cash and debt are modeled for the full applicable term, including at least the first 24 months, and aggregate to the quarterly stress outputs. Working-capital stress changes explicit receivable, inventory, payable, and other operating-current-balance proxies. Interest is endogenous to debt and rates.

The base proposed path exactly preserves the Phase 5 common-horizon distinction: directly draw-funded repurchases are $6.754m, while $17.500m of repurchases occur while revolver debt remains outstanding. The narrow and broad interpretations are both analytical flags; neither is a legal opinion. Severe unmitigated distributions remain in the model.

## Dated mitigation comparison and realized cash attribution

| Severity | Structure | Planned distributions | Due under mitigated policy | Paid unmitigated | Unpaid unmitigated | Paid mitigated | Actual cash preserved | Interest saved | Other waterfall effect | Maturity-gap reduction |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| moderate | proposed | $97.500m | $73.750m | $97.500m | $0.000m | $73.750m | $23.750m | $4.168m | $0.000m | $27.918m |
| moderate | existing | $68.250m | $52.000m | $68.250m | $0.000m | $52.000m | $16.250m | $1.906m | $0.000m | $18.156m |
| severe | proposed | $97.500m | $39.313m | $84.500m | $13.000m | $36.292m | $48.208m | $0.656m | $-1.338m | $47.525m |
| severe | existing | $68.250m | $28.438m | $68.250m | $0.000m | $28.438m | $39.812m | $5.091m | $0.000m | $44.904m |

Modeled actions begin May 1, 2026 after a one-quarter implementation lag. Repurchases are suspended in both mitigated cases; severe mitigation also reduces dividends 50%. The modeled actions have no direct implementation cost and no EBITDA benefit. Actual cash preserved equals distributions actually paid in the unmitigated path less distributions actually paid in the mitigated path. It excludes distributions that the unmitigated path already could not pay. The other waterfall effect is the negative of additional retained mandatory obligations paid in the mitigated path; it is separately quantified rather than left as an unexplained residual. Actual cash preserved plus interest saved plus that identified effect reconciles to the maturity-gap reduction within $0.000001m. Board approval, legal permission, execution, and persistence are not assumed certain.

## Monthly timing sensitivity

| Scenario | Structure | Timing | Minimum usable liquidity | Headline peak revolver | First $50m warning | First cash-floor failure | First mandatory failure | Maturity shortfall |
| --- | --- | --- | ---: | ---: | --- | --- | --- | ---: |
| MODERATE_UNMITIGATED | proposed | equal | $146.581m (2027-01-31) | $147.219m (2027-01-31) | none | none | none  | $429.081m |
| MODERATE_UNMITIGATED | proposed | adverse | $146.524m (2027-01-31) | $147.276m (2027-01-31) | none | none | none  | $429.487m |
| MODERATE_UNMITIGATED | existing | equal | $184.867m (2027-01-31) | $283.933m (2027-01-31) | none | none | none  | $512.460m |
| MODERATE_UNMITIGATED | existing | adverse | $184.810m (2027-01-31) | $283.990m (2027-01-31) | none | none | none  | $512.828m |
| SEVERE_UNMITIGATED | proposed | equal | $0.000m (2027-04-30) | $293.800m (2027-04-30) | 2026-07-31 | 2027-04-30 | 2027-07-31 SCHEDULED_TERM_PRINCIPAL | $610.072m |
| SEVERE_UNMITIGATED | proposed | adverse | $0.000m (2027-04-30) | $293.800m (2027-04-30) | 2026-07-31 | 2027-04-30 | 2027-07-31 SCHEDULED_TERM_PRINCIPAL | $599.638m |
| SEVERE_UNMITIGATED | existing | equal | $0.000m (2028-01-31) | $468.800m (2028-01-31) | 2027-03-31 | 2028-01-31 | none  | $705.201m |
| SEVERE_UNMITIGATED | existing | adverse | $0.000m (2028-01-31) | $468.800m (2028-01-31) | 2027-02-28 | 2028-01-31 | none  | $705.685m |
| SEVERE_MITIGATED | proposed | equal | $0.000m (2027-07-31) | $293.800m (2027-07-31) | 2026-10-31 | 2027-07-31 | 2027-10-31 SCHEDULED_TERM_PRINCIPAL | $553.282m |
| SEVERE_MITIGATED | proposed | adverse | $0.000m (2027-06-30) | $293.800m (2027-06-30) | 2026-08-31 | 2027-06-30 | 2027-10-31 SCHEDULED_TERM_PRINCIPAL | $552.113m |
| SEVERE_MITIGATED | existing | equal | $12.251m (2028-01-31) | $456.549m (2028-01-31) | 2027-07-31 | none | none  | $660.145m |
| SEVERE_MITIGATED | existing | adverse | $10.947m (2028-02-29) | $457.853m (2028-02-29) | 2027-05-31 | none | none  | $660.781m |
| MODERATE_NO_WAIVER | proposed | equal | $0.000m (2026-11-30) | $123.429m (2026-10-31) | 2026-11-30 | 2026-11-30 | none  | $403.832m |
| MODERATE_NO_WAIVER | proposed | adverse | $0.000m (2026-11-30) | $123.460m (2026-10-31) | 2026-11-30 | 2026-11-30 | none  | $404.115m |
| SEVERE_NO_WAIVER | proposed | equal | $0.000m (2026-08-31) | $244.534m (2026-07-31) | 2026-07-31 | 2026-10-31 | 2027-01-31 SCHEDULED_TERM_PRINCIPAL | $567.101m |
| SEVERE_NO_WAIVER | proposed | adverse | $0.000m (2026-08-31) | $243.991m (2026-07-31) | 2026-07-31 | 2026-08-31 | 2027-01-31 SCHEDULED_TERM_PRINCIPAL | $541.901m |

Equal allocation is the neutral timing convention. The adverse 20%/30%/50% moderate and 10%/25%/65% severe allocations are conservative underwriting sensitivities. Neither is verified actual monthly seasonality. Exact distress dates are conditional on the selected allocation. A lower debt or maturity balance caused by curtailed borrowing, unpaid obligations, or liquidity failure is not improved credit performance. Phase 7 may use the conservative date for intervention design but must not call it an observed forecast.

## Reverse stress

| Structure | Test | Approximate breakpoint | Status | First failure date |
| --- | --- | ---: | --- | --- |
| proposed | volume decline to first $50m liquidity warning | 56.53 percent | approximated_first_failure | 2030-12-31 |
| proposed | gross-margin decline to first $50m liquidity warning | 287 basis_points | approximated_first_failure | 2030-12-31 |
| proposed | combined volume-margin scale to commitment exhaustion | 0.46 multiple_of_severe_case | approximated_first_failure | 2030-11-30 |
| proposed | DSO increase to commitment exhaustion | 40.4 days | approximated_first_failure | 2030-02-28 |
| proposed | DIO increase to commitment exhaustion | 55.3 days | approximated_first_failure | 2030-02-28 |
| proposed | rate increase to cash-interest coverage below 3.00x | 458 basis_points | approximated_first_failure | 2027-01-31 |
| proposed | gross-margin decline to leverage above 3.25x | 96 basis_points | approximated_first_failure | 2026-12-31 |
| proposed | gross-margin decline to leverage above 3.00x after FY2028 | 121 basis_points | approximated_first_failure | 2027-12-31 |
| proposed | combined operating scale to scheduled debt-service failure | 0.47 multiple_of_severe_case | approximated_first_failure | 2031-01-31 |
| proposed | combined operating scale to eliminate monthly cash available for distributions | 0.47 multiple_of_severe_case | approximated_first_failure | 2031-01-31 |
| proposed | combined operating scale to first no-waiver liquidity failure | 0.13 multiple_of_severe_case | approximated_first_failure | 2027-01-31 |
| proposed | annual CFADS increment to eliminate unsupported maturity gap | 63 USD_millions_per_year | approximated_first_failure | 2031-01-31 |
| existing | volume decline to first $50m liquidity warning | not reached percent | not_reached_within_bounds | none |
| existing | gross-margin decline to first $50m liquidity warning | 620 basis_points | approximated_first_failure | 2029-06-30 |
| existing | combined volume-margin scale to commitment exhaustion | 0.89 multiple_of_severe_case | approximated_first_failure | 2029-05-31 |
| existing | DSO increase to commitment exhaustion | 53.6 days | approximated_first_failure | 2026-05-31 |
| existing | DIO increase to commitment exhaustion | 73.5 days | approximated_first_failure | 2026-05-31 |
| existing | rate increase to cash-interest coverage below 3.00x | 474 basis_points | approximated_first_failure | 2027-01-31 |
| existing | gross-margin decline to leverage above 3.25x | 113 basis_points | approximated_first_failure | 2026-12-31 |
| existing | gross-margin decline to leverage above 3.00x after FY2028 | 134 basis_points | approximated_first_failure | 2027-12-31 |
| existing | combined operating scale to scheduled debt-service failure | 0.96 multiple_of_severe_case | approximated_first_failure | 2029-05-31 |
| existing | combined operating scale to eliminate monthly cash available for distributions | 0.96 multiple_of_severe_case | approximated_first_failure | 2029-05-31 |
| existing | combined operating scale to first no-waiver liquidity failure | not reached multiple_of_severe_case | not_applicable_existing_analytical_warning_only | none |
| existing | annual CFADS increment to eliminate unsupported maturity gap | 115 USD_millions_per_year | approximated_first_failure | 2029-07-31 |

Searches are bounded and reported only to their stated tolerance. `threshold_already_failed` and `not_reached_within_bounds` replace invented breakpoints. Sustainable annual CFADS is a mathematical requirement to retire the balloon without refinancing, not an operating forecast or cure assumption.

## Sensitivity grids

The 63 grid points cover volume/margin, DSO/DIO, rate/margin for both structures, and proposed amortization/operating stress. They report minimum liquidity, opening revolver, subsequent period-end peak, headline peak including opening, first analytical distress, interest coverage, and maturity gap. Grid points remain sensitivities rather than owner-approved forecasts.
