# Sizing rationale

**Recommendation:** CONDITIONAL GO for committing the owner-reviewed Phase 7 provisional structure and, after separate authorization, proceeding to Phase 8. All closing and diligence conditions remain open.

The original $650m term funding is not automatically acceptable. Including the $29.898m opening revolver and $62.619m retained funded-debt proxy, opening total funded debt is $742.517m. The 3.25x zero-cash analytical capacity is $732.368m.

The owner-reviewed Phase 7 provisional structure is a $635m term commitment funded at closing, a $300m revolver with $29.898m drawn at closing, and a conditional $15m non-debt contribution. Opening total funded debt is $727.517m and gross leverage is 3.23x, below the inclusive 3.25x warning. The term amount must refresh from final payoff, fees, hedge and LC evidence.

## Practical sizing alternatives

| Analysis | Term funding | Contribution | Total funded debt | Leverage | Headroom / (shortfall) | Opening liquidity | Subsequent minimum (date) | All-in minimum (date) | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Exact total-funded-debt capacity at 3.25x with reference revolver allocation | $639.851m | $10.149m | $732.368m | 3.25x | $0.000m | $263.902m | $270.315m (2026-02-28) | $263.902m (OPENING_POSITION) | EXACT_BOUNDARY_WARNING_ACTIVE |
| $640m term with $10m contribution and reference revolver allocation | $640.000m | $10.000m | $732.517m | 3.25x | -$0.149m | $263.902m | $270.314m (2026-02-28) | $263.902m (OPENING_POSITION) | MARGINAL_SIZING_EXCEPTION |
| $640m term with revolver reallocated inside exact 3.25x bank-debt capacity | $640.000m | $10.149m | $732.368m | 3.25x | $0.000m | $264.051m | $270.463m (2026-02-28) | $264.051m (OPENING_POSITION) | EXACT_BOUNDARY_WARNING_ACTIVE |
| $635m practical term with $15m contribution and reference revolver allocation | $635.000m | $15.000m | $727.517m | 3.23x | $4.851m | $263.902m | $270.341m (2026-02-28) | $263.902m (OPENING_POSITION) | PASS_BELOW_WARNING_WITH_MODEST_CUSHION |
| $639m rounded term at or below analytical capacity | $639.000m | $11.000m | $731.517m | 3.25x | $0.851m | $263.902m | $270.319m (2026-02-28) | $263.902m (OPENING_POSITION) | PASS_BELOW_WARNING_WITH_MINIMAL_CUSHION |
| $625m term with conditional $25m non-debt contribution at 3.25x | $625.000m | $25.000m | $717.517m | 3.18x | $14.851m | $263.902m | $270.396m (2026-02-28) | $263.902m (OPENING_POSITION) | PASS_IF_SEPARATE_SOURCE_EXISTS |

The $640m/$10m option exceeds the 3.25x capacity by about $0.149m and remains an unselected sizing exception. The $640m reallocation alternative reduces the revolver by the same $0.149m and requires the exact non-debt source; this changes term-versus-revolver allocation without changing total funded debt. The selected $635m option adds a modest practical cushion and does not imply unused term availability.

## Sources and uses

| Candidate | Term | Revolver | Non-debt source | Total sources | Uses | Control | Warning | Covenant |
|---|---:|---:|---:|---:|---:|---:|---|---|
| $650m reference term / 10% amortization | $650.000m | $29.898m | $0.000m | $679.898m | $679.898m | $0.000m | warning | compliant |
| $650m term / 5% amortization | $650.000m | $29.898m | $0.000m | $679.898m | $679.898m | $0.000m | warning | compliant |
| $650m term / 7.5% amortization | $650.000m | $29.898m | $0.000m | $679.898m | $679.898m | $0.000m | warning | compliant |
| $650m term / 15% amortization | $650.000m | $29.898m | $0.000m | $679.898m | $679.898m | $0.000m | warning | compliant |
| $625m term / conditional $25m contribution / 7.5% amortization | $625.000m | $29.898m | $25.000m | $679.898m | $679.898m | $0.000m | compliant | compliant |
| $635m practical term / $15m conditional contribution / 7.5% amortization | $635.000m | $29.898m | $15.000m | $679.898m | $679.898m | $0.000m | compliant | compliant |
| Exact 3.25x analytical total-funded-debt boundary / 7.5% amortization | $639.851m | $29.898m | $10.149m | $679.898m | $679.898m | $0.000m | warning | compliant |
| $640m rounded term / $10m contribution / reference revolver | $640.000m | $29.898m | $10.000m | $679.898m | $679.898m | $0.000m | warning | compliant |
| $640m rounded term / exact non-debt source / reallocated revolver | $640.000m | $29.749m | $10.149m | $679.898m | $679.898m | $0.000m | warning | compliant |

## Common horizon through July 31, 2029

| Candidate | Interest | Scheduled principal | Sweep | Ending bank debt | Ending funded debt | Peak revolver | Opening liquidity | Subsequent minimum (date) | All-in minimum (date) | Unpaid obligations | Warning | Covenant |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| Retain existing facilities | $127.471m | $87.500m | $0.000m | $432.749m | $495.368m | $207.398m | $261.402m | $267.814m (2026-02-28) | $261.402m (OPENING_POSITION) | $0.000m | warning | not_determinable |
| $650m reference term / 10% amortization | $130.057m | $227.500m | $0.000m | $445.335m | $507.954m | $39.954m | $263.902m | $253.846m (2028-01-31) | $253.846m (2028-01-31) | $0.000m | warning | not_determinable |
| $650m term / 5% amortization | $134.297m | $113.750m | $41.164m | $495.086m | $557.705m | $29.898m | $263.902m | $270.259m (2026-02-28) | $263.902m (OPENING_POSITION) | $0.000m | warning | not_determinable |
| $650m term / 7.5% amortization | $131.315m | $170.625m | $12.328m | $467.047m | $529.666m | $29.898m | $263.902m | $270.259m (2026-02-28) | $263.902m (OPENING_POSITION) | $0.000m | warning | not_determinable |
| $650m term / 15% amortization | $130.057m | $341.250m | $0.000m | $445.335m | $507.954m | $136.585m | $263.902m | $157.215m (2029-07-31) | $157.215m (2029-07-31) | $0.000m | warning | not_determinable |
| $625m term / conditional $25m contribution / 7.5% amortization | $125.491m | $164.062m | $18.735m | $442.202m | $504.821m | $29.898m | $263.902m | $270.396m (2026-02-28) | $263.902m (OPENING_POSITION) | $0.000m | not_determinable | not_determinable |
| $635m practical term / $15m conditional contribution / 7.5% amortization | $127.808m | $166.688m | $16.178m | $452.135m | $514.754m | $29.898m | $263.902m | $270.341m (2026-02-28) | $263.902m (OPENING_POSITION) | $0.000m | not_determinable | not_determinable |
| Exact 3.25x analytical total-funded-debt boundary / 7.5% amortization | $128.940m | $167.961m | $14.933m | $456.958m | $519.577m | $29.898m | $263.902m | $270.315m (2026-02-28) | $263.902m (OPENING_POSITION) | $0.000m | warning | not_determinable |
| $640m rounded term / $10m contribution / reference revolver | $128.975m | $168.000m | $14.895m | $457.105m | $519.724m | $29.898m | $263.902m | $270.314m (2026-02-28) | $263.902m (OPENING_POSITION) | $0.000m | warning | not_determinable |
| $640m rounded term / exact non-debt source / reallocated revolver | $128.947m | $168.000m | $15.020m | $456.980m | $519.599m | $29.749m | $264.051m | $270.463m (2026-02-28) | $264.051m (OPENING_POSITION) | $0.000m | warning | not_determinable |

## Ultimate maturity (different horizons)

| Candidate | Maturity | Months | Interest | Scheduled principal | Sweep | Final funded debt | Maturity due | Cash applied | Unsupported gap |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Retain existing facilities | 2029-08-01 | 43 | $127.471m | $87.500m | $0.000m | $495.368m | $432.749m | $0.000m | $432.749m |
| $650m reference term / 10% amortization | 2031-01-31 | 60 | $168.554m | $325.000m | $0.000m | $403.567m | $340.948m | $0.000m | $340.948m |
| $650m term / 5% amortization | 2031-01-31 | 60 | $177.892m | $162.500m | $106.897m | $412.905m | $380.603m | $30.317m | $350.286m |
| $650m term / 7.5% amortization | 2031-01-31 | 60 | $172.492m | $243.750m | $49.257m | $407.505m | $356.993m | $12.107m | $344.886m |
| $650m term / 15% amortization | 2031-01-31 | 60 | $168.529m | $487.500m | $0.000m | $403.542m | $340.923m | $0.000m | $340.923m |
| $625m term / conditional $25m contribution / 7.5% amortization | 2031-01-31 | 60 | $164.003m | $234.375m | $62.631m | $374.016m | $327.994m | $16.597m | $311.397m |
| $635m practical term / $15m conditional contribution / 7.5% amortization | 2031-01-31 | 60 | $167.386m | $238.125m | $57.292m | $387.399m | $339.583m | $14.803m | $324.780m |
| Exact 3.25x analytical total-funded-debt boundary / 7.5% amortization | 2031-01-31 | 60 | $169.035m | $239.944m | $54.695m | $393.899m | $345.212m | $13.932m | $331.280m |
| $640m rounded term / $10m contribution / reference revolver | 2031-01-31 | 60 | $169.085m | $240.000m | $54.616m | $394.098m | $345.384m | $13.905m | $331.479m |
| $640m rounded term / exact non-debt source / reallocated revolver | 2031-01-31 | 60 | $169.043m | $240.000m | $54.786m | $393.907m | $345.214m | $13.926m | $331.288m |

Ultimate-maturity totals use different cash-generation periods and cannot be compared directly. Pricing, amortization, contributions, maturity length, payment failures and draw availability must each be identified before drawing a conclusion. Retaining the existing facilities remains a live quantitative alternative; a limited amendment or extension remains live but `N/D` without terms. No refinancing proceeds are assumed.
