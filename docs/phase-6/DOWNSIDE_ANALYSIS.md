# Downside analysis

## Scenario calibration owner-reviewed for Phase 6 analytical testing

| Input | Moderate | Severe |
| --- | ---: | ---: |
| Volume vs base | -6.5% | -15% |
| Gross-margin pressure | -200 bps | -375 bps |
| DSO increase | 5 days | 15 days |
| DIO increase | 10 days | 25 days |
| AP/cost-of-sales change | -50 bps | -100 bps |
| Other current assets/revenue change | +25 bps | +50 bps |
| Other operating current liabilities/revenue change | -25 bps | -50 bps |
| Rate shock | +100 bps | +200 bps |
| Cash-only remediation | $3.000m over two quarters | $10.000m over four quarters |
| Plateau / recovery | 4 quarters / 3-quarter linear recovery | 8 quarters / 4-quarter linear recovery |
| Monthly stress weighting | 20% / 30% / 50% | 10% / 25% / 65% |

The owner approved these exact stress points, recovery paths and timing conventions for Phase 6 analytical testing only. They are not management forecasts, final underwriting assumptions, contractual conclusions or final loan terms. The 12%-13% lender EBITDA margin is a validation reference only and never an input.

## Results

| Scenario | Structure | Minimum usable liquidity | Opening revolver | Peak subsequent period-end revolver | Headline peak including opening | Unsupported maturity gap | First $50m warning | First cash-floor failure | First mandatory failure | Overall path status |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| BASE | proposed | $253.846m (2028-01-31) | $29.898m | $39.954m (2028-01-31) | $39.954m (2028-01-31) | $340.948m | none | none | none | MATURITY_SHORTFALL |
| BASE | existing | $261.402m (2026-01-31) | $207.398m | $200.986m (2026-02-28) | $207.398m (OPENING_POSITION) | $432.749m | none | none | none | MATURITY_SHORTFALL |
| MODERATE_UNMITIGATED | proposed | $146.524m (2027-01-31) | $29.898m | $147.276m (2027-01-31) | $147.276m (2027-01-31) | $429.487m | none | none | none | MATURITY_SHORTFALL |
| MODERATE_UNMITIGATED | existing | $184.810m (2027-01-31) | $207.398m | $283.990m (2027-01-31) | $283.990m (2027-01-31) | $512.828m | none | none | none | MATURITY_SHORTFALL |
| SEVERE_UNMITIGATED | proposed | $0.000m (2027-04-30) | $29.898m | $293.800m (2027-04-30) | $293.800m (2027-04-30) | $599.638m | 2026-07-31 | 2027-04-30 | 2027-07-31 SCHEDULED_TERM_PRINCIPAL | MANDATORY_PAYMENT_FAILURE |
| SEVERE_UNMITIGATED | existing | $0.000m (2028-01-31) | $207.398m | $468.800m (2028-01-31) | $468.800m (2028-01-31) | $705.685m | 2027-02-28 | 2028-01-31 | none | LIQUIDITY_FAILURE |
| MODERATE_MITIGATED | proposed | $150.382m (2027-01-31) | $29.898m | $143.418m (2027-01-31) | $143.418m (2027-01-31) | $401.569m | none | none | none | MATURITY_SHORTFALL |
| MODERATE_MITIGATED | existing | $188.109m (2026-05-31) | $207.398m | $280.691m (2026-05-31) | $280.691m (2026-05-31) | $494.672m | none | none | none | MATURITY_SHORTFALL |
| SEVERE_MITIGATED | proposed | $0.000m (2027-06-30) | $29.898m | $293.800m (2027-06-30) | $293.800m (2027-06-30) | $552.113m | 2026-08-31 | 2027-06-30 | 2027-10-31 SCHEDULED_TERM_PRINCIPAL | MANDATORY_PAYMENT_FAILURE |
| SEVERE_MITIGATED | existing | $10.947m (2028-02-29) | $207.398m | $457.853m (2028-02-29) | $457.853m (2028-02-29) | $660.781m | 2027-05-31 | none | none | MATURITY_SHORTFALL |
| MODERATE_NO_WAIVER | proposed | $0.000m (2026-11-30) | $29.898m | $123.460m (2026-10-31) | $123.460m (2026-10-31) | $404.115m | 2026-11-30 | 2026-11-30 | none | LIQUIDITY_FAILURE |
| MODERATE_NO_WAIVER | existing | $184.810m (2027-01-31) | $207.398m | $283.990m (2027-01-31) | $283.990m (2027-01-31) | $512.828m | none | none | none | MATURITY_SHORTFALL |
| SEVERE_NO_WAIVER | proposed | $0.000m (2026-08-31) | $29.898m | $243.991m (2026-07-31) | $243.991m (2026-07-31) | $541.901m | 2026-07-31 | 2026-08-31 | 2027-01-31 SCHEDULED_TERM_PRINCIPAL | MANDATORY_PAYMENT_FAILURE |
| SEVERE_NO_WAIVER | existing | $0.000m (2028-01-31) | $207.398m | $468.800m (2028-01-31) | $468.800m (2028-01-31) | $705.685m | 2027-02-28 | 2028-01-31 | none | LIQUIDITY_FAILURE |

## Underwriting observations

- Moderate stress materially increases revolver use and the maturity balloon but remains above the $50m liquidity warning under continued drawability. Analytical leverage is the first warning, not a contractual breach.
- Severe stress exhausts the modeled revolver under both structures. The proposed path subsequently develops mandatory-payment failure; the exact first failed obligation, due, paid and unpaid amounts are recorded. The existing path develops a cash-floor failure before maturity without an interim mandatory-payment failure.
- The proposed no-waiver convention converts an analytical warning into a following-month drawability shutoff and earlier cash-floor pressure. That convention is intentionally separate from legal conclusions.
- All paths retain an unsupported maturity balloon because refinancing is excluded. The result is refinancing risk, not an assumption that the debt will actually default at maturity.
