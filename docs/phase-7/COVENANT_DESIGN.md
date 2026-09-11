# Covenant design

**Status:** Owner-reviewed Phase 7 public-information underwriting structure, subject to all stated conditions and diligence gaps. It is not a lender commitment, final legal drafting, or an official compliance calculation.

## Framework separation

| Framework | Test | Threshold | Period | Key limitation |
|---|---|---:|---|---|
| existing_contractual | maximum Consolidated Net Leverage Ratio | 3.25 turns | 2026-01-31 to open | Not an official compliance certificate. |
| proposed_contractual | maximum gross total funded leverage | 3.50 turns | 2026-01-31 to 2027-10-31 | A 3.50x gross covenant is not directly comparable with the existing 3.25x net covenant. Final debt and EBITDA definitions require counsel and lender approval. |
| proposed_contractual | maximum gross total funded leverage | 3.25 turns | 2027-11-01 to 2028-10-31 | Step date aligns to the FY2028 testing year; exact certificate date and stub-period treatment require drafting. |
| proposed_contractual | maximum gross total funded leverage | 3.00 turns | 2028-11-01 to 2031-01-31 | The final test before maturity must not imply refinancing availability. |
| proposed_contractual | minimum EBITDA to cash-interest coverage | 3.00 turns | 2026-01-31 to 2031-01-31 | The Phase 6 model lacks a complete closing-date LTM cash-interest denominator; opening compliance is therefore not determinable from public information. |
| proposed_contractual | minimum usable liquidity | 50 USD_millions | 2026-01-31 to 2031-01-31 | The Phase 7 model gives no credit to book cash; final eligible cash remains pending information. |
| analyst_warning | gross total funded leverage warning | 3.25 turns | 2026-01-31 to 2027-10-31 | A warning is not a covenant breach, waiver decision, or compliance certificate. |
| analyst_warning | gross total funded leverage warning | 3.00 turns | 2027-11-01 to 2028-10-31 | A warning is 0.25x inside the proposed covenant. |
| analyst_warning | gross total funded leverage warning | 2.75 turns | 2028-11-01 to 2031-01-31 | A warning is 0.25x inside the proposed covenant. |
| analyst_warning | minimum EBITDA to cash-interest coverage warning | 3.50 turns | 2026-01-31 to 2031-01-31 | A warning is not a legal breach. |
| analyst_warning | minimum usable liquidity warning | 75 USD_millions | 2026-01-31 to 2031-01-31 | The committed Phase 6 $50m warning remains preserved in prior outputs; Phase 7 adds a more conservative $75m intervention threshold. |
| model_control | operating cash floor | 25 USD_millions | 2026-01-31 to 2031-01-31 | Do not combine this cash floor with the $50m liquidity covenant or count it as an accessible closing contribution. |

## Proposed definitions and limitations

The proposed leverage covenant is gross total funded leverage with zero cash netting. The existing public covenant is a net leverage test with agreement-defined terms. The 3.50x proposed gross threshold therefore does not silently replace or reinterpret the existing 3.25x net threshold.

Drawn revolver principal is included in debt. The $62.619m retained finance-lease and other-debt proxy is included economically pending final legal classification. Operating lease liabilities and trade payables are excluded unless final drafting states otherwise. Lender EBITDA starts with the Phase 2 owner-reviewed base and requires a documented definition, adjustment schedule, caps, sunsets and anti-duplication controls.

No cash is netted in the proposed covenant. Book cash and a capped $25m cash sensitivity remain diagnostics because entity location, restrictions, tax, liens and operating requirements are unresolved.

## Cures, step-ups and drawability

No equity cure, acquisition step-up, waiver or refinancing is assumed. A warning alone never blocks drawings. In the covenant-linked no-waiver path, a tested breach blocks new drawings from the following month. The continued-draw path requires lender consent or continuing legal availability. The inherited Phase 6 analytical shutoff remains separately labeled and is not a Phase 7 legal default.

## Monitoring and intervention

The analyst warning levels are 0.25x inside the leverage covenants, 3.50x coverage versus a 3.00x covenant, and $75m liquidity versus a $50m covenant. Warning boundaries are inclusive. A warning suspends share repurchases, starts monthly reporting and requires a 10-business-day action plan. A proposed breach suspends all restricted payments and invokes the no-new-draw convention unless lenders approve another outcome.

## Selected-structure covenant summary

| Path | Closing warning | Closing covenant | Max leverage | Min coverage | Opening liquidity | Subsequent minimum (date) | All-in minimum (date) | First warning | First breach | First draw shutoff | Payment failure | Maturity gap |
|---|---|---|---:|---:|---:|---:|---:|---|---|---|---|---:|
| BASE | not_determinable | not_determinable | 3.228471664433044589605225788x | 5.385958143510740202126050031x | $263.902m | $270.341m (2026-02-28) | $263.902m (OPENING_POSITION) | none | none | none | none | $324.780m |
| MODERATE_UNMITIGATED | not_determinable | not_determinable | 4.489250193362220496112949436x | 3.21037383225652856657170589x | $263.902m | $165.078m (2027-01-31) | $165.078m (2027-01-31) | 2026-10-31 | 2026-10-31 | none | none | $408.375m |
| SEVERE_UNMITIGATED | not_determinable | not_determinable | 7.057401459649876678831184631x | 1.781935137831290008599621829x | $263.902m | $0.000m (2027-07-31) | $0.000m (2027-07-31) | 2026-04-30 | 2026-10-31 | none | 2027-12-31 | $604.258m |
| MODERATE_MITIGATED | not_determinable | not_determinable | 4.46700610804697192532459313x | 3.21683406720595994209164216x | $263.902m | $168.937m (2027-01-31) | $168.937m (2027-01-31) | 2026-10-31 | 2026-10-31 | none | none | $381.133m |
| SEVERE_MITIGATED | not_determinable | not_determinable | 6.952855624180312930251039561x | 1.800808047646651465852370982x | $263.902m | $0.000m (2027-11-30) | $0.000m (2027-11-30) | 2026-04-30 | 2026-10-31 | none | 2028-01-31 | $554.718m |
| MODERATE_NO_WAIVER | not_determinable | not_determinable | 4.378743433190989811687069384x | 3.218171493292327243011830521x | $263.902m | $0.000m (2026-11-30) | $0.000m (2026-11-30) | 2026-10-31 | 2026-10-31 | 2026-11-30 | none | $396.875m |
| SEVERE_NO_WAIVER | not_determinable | not_determinable | 6.81315885843563940769012503x | 1.861980995883890218713637955x | $263.902m | $0.000m (2026-11-30) | $0.000m (2026-11-30) | 2026-04-30 | 2026-10-31 | 2026-11-30 | 2027-02-28 | $538.041m |
| MODERATE_PHASE7_COVENANT_NO_WAIVER | not_determinable | not_determinable | 4.378743433190989811687069384x | 3.218171493292327243011830521x | $263.902m | $0.000m (2026-11-30) | $0.000m (2026-11-30) | 2026-10-31 | 2026-10-31 | 2026-11-30 | none | $396.875m |
| SEVERE_PHASE7_COVENANT_NO_WAIVER | not_determinable | not_determinable | 6.81315885843563940769012503x | 1.861980995883890218713637955x | $263.902m | $0.000m (2026-11-30) | $0.000m (2026-11-30) | 2026-04-30 | 2026-10-31 | 2026-11-30 | 2027-02-28 | $538.041m |

## Initial leverage covenant comparison

The transaction is sized below 3.25x while the proposed maintenance covenant begins at 3.50x. The 0.25x difference equals $56.336m of debt capacity or $15.989m of EBITDA cushion at selected opening debt. It is maintenance cushion, not additional closing funding capacity.

| Scenario | Covenant case | Closing | First warning | First breach | Liquidity at breach | Draw shutoff | Payment failure | Days breach-to-failure |
|---|---|---|---|---|---:|---|---|---:|
| moderate | proposed_3.50x_initial | compliant | 2026-10-31 | 2026-10-31 | $184.247m | 2026-11-30 | none | N/D |
| moderate | alternative_3.25x_initial | compliant | 2026-10-31 | 2026-10-31 | $184.247m | 2026-11-30 | none | N/D |
| severe | proposed_3.50x_initial | compliant | 2026-04-30 | 2026-10-31 | $55.638m | 2026-11-30 | 2027-02-28 | 120 |
| severe | alternative_3.25x_initial | compliant | 2026-04-30 | 2026-10-31 | $55.638m | 2026-11-30 | 2027-02-28 | 120 |
