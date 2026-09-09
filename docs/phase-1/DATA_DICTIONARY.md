# Phase 1 data dictionary

## Dataset fields

| Field | Meaning |
|---|---|
| `fact_id` / `raw_fact_id` | Stable row identifier within its dataset. |
| `layer` | `reported_historical`, `company_disclosed_pro_forma`, or `calculated`; layers must not be merged silently. |
| `variant` | Identifies reported, mechanical, or source-version variants; used to preserve overlapping pro forma disclosures without treating them as duplicates. |
| `metric_name` | Canonical snake-case financial metric. |
| `fiscal_year` | Quanex fiscal label; fiscal years end October 31. Pro forma labels remain distinct. |
| `period_start`, `period_end` | Exact source period. Instant facts have a blank start date. |
| `period_type` | `duration` for income/cash flow or `instant` for balance-sheet/debt facts. |
| `period_grain` | `annual`, `nine_months`, `year_end`, or `instant`. |
| `statement` | Income statement, balance sheet, cash flow, debt reconciliation, pro forma statement, or calculated layer. |
| `original_reported_value` | Source value before unit conversion and sign normalization. Blank for calculated rows. |
| `original_units` | Source units; financial-statement extracts are USD thousands. |
| `normalized_value` | USD millions after unit conversion and the stated sign convention. |
| `normalized_units` | `USD_millions` for normalized monetary facts. |
| `classification` | `reported`, `reported_pro_forma`, or `calculated`. |
| `source_ids` | Semicolon-separated IDs from the Phase 0 evidence inventory. |
| `source_reference` | Page, note, section, exhibit, or calculation input reference. |
| `source_type` | SEC filing/exhibit, company release, contract, or calculated-from-reported. |
| `override_status`, `override_rationale` | Manual-override control. All current facts are `none`. |
| `comparability_status` | Acquisition perimeter warning carried with every fact. |
| `calculation` | Formula description for mechanical calculated values. |
| `notes` | Source fidelity, scope, or limitation note. |

## Sign convention

Revenue, income, assets, liabilities, and debt balances are positive unless the
source amount itself is negative. Costs and expenses are negative in normalized
income data. Capital expenditures, acquisitions, dividends, and repurchases are
negative cash outflows. This convention makes `revenue + cost_of_sales` equal
gross profit and `cash_flow_from_operations + capital_expenditures` equal free
cash flow before finance-lease payments.

## Core normalized metrics

| Metric | Financial meaning | Period | Source/classification | Known limitation |
|---|---|---|---|---|
| `revenue` | Consolidated net sales | Duration | Reported | Acquisition perimeter changes in FY2024/FY2025 |
| `cost_of_sales_excluding_depreciation_and_amortization` | Product cost before separately presented D&A | Duration | Reported, negative | Not total operating cost |
| `gross_profit` | Revenue plus normalized cost of sales | Duration | Calculated | Excludes separately presented D&A |
| `selling_general_and_administrative` | SG&A expense | Duration | Reported, negative | Contains acquisition/integration items in later periods |
| `restructuring_charges` | Separately reported restructuring expense | Duration | Reported, negative | Company cash-flow addback may differ from income-statement charge |
| `depreciation_and_amortization` | Consolidated D&A expense | Duration | Reported, negative | Purchase accounting materially changes comparability |
| `goodwill_impairment_charges` | Non-cash goodwill impairment | Duration | Reported, negative | FY2025 segment-restructuring event |
| `operating_income` | Consolidated GAAP operating income/loss | Duration | Reported | Mixed acquisition perimeter in FY2024 |
| `interest_expense` | Reported financing expense | Duration | Reported, negative | Post-acquisition debt changes the run rate |
| `income_tax_expense` | Reported tax expense/benefit | Duration | Reported, normally negative | FY2025 includes acquisition-related discrete tax effects |
| `net_income` | Consolidated GAAP net income/loss | Duration | Reported | No EBITDA normalization embedded |
| `cash_flow_from_operations` | GAAP operating cash flow | Duration | Reported | FY2024/FY2025 cash-flow control weakness warrants heightened review |
| `capital_expenditures` | Purchases of property, plant and equipment | Duration | Reported, negative | Free cash flow remains before finance-lease payments |
| `free_cash_flow_before_finance_lease_payments` | CFO plus capex | Duration | Calculated | Not residual cash available for discretionary use |
| `acquisition_cash_flows` | Cash paid for business acquisitions, net where reported | Duration | Reported, negative | Not populated for FY2021/FY2022 absent a dedicated selected-source line |
| `dividends_paid`, `share_repurchases` | Shareholder cash distributions | Duration | Reported, negative | A reported dash is zero; an absent row is missing |
| `cash_and_cash_equivalents`, `restricted_cash` | Reported cash balances | Instant | Reported | Book cash is not automatically covenant-eligible cash |
| `accounts_receivable`, `inventory`, `accounts_payable` | Core operating working-capital accounts | Instant | Reported | Acquisition and FX affect comparability |
| `prepaid_assets`, `other_current_assets` | Separately presented FY2024/FY2025 items | Instant | Reported | Earlier periods use a combined line |
| `prepaid_and_other_current_assets` | Combined earlier-period current operating assets | Instant | Reported | Must not be silently split |
| `current_assets`, `current_liabilities` | GAAP current totals | Instant | Reported | Include non-operating items |
| `property_plant_and_equipment_net` | Net tangible fixed assets | Instant | Reported | Fair-value step-up affects post-acquisition values |
| `goodwill`, `intangible_assets_net` | Acquisition-related and other intangible assets | Instant | Reported | PPA and FY2025 impairment break comparability |
| `current_maturities_of_long_term_debt`, `long_term_debt` | GAAP carrying amounts | Instant | Reported | Net of financing fees; not principal owed |
| `total_debt_carrying_amount` | Current plus long-term GAAP debt | Instant | Calculated | Differs from gross principal by deferred financing fees |
| `finance_lease_obligations_principal` | Company net-debt reconciliation amount | Instant | Reported | Includes real-estate finance leases and other debt |
| `current_operating_lease_liabilities`, `noncurrent_operating_lease_liabilities` | ASC 842 operating-lease obligations | Instant | Reported | Separate from finance-lease debt |
| `total_operating_lease_liabilities` | Current plus noncurrent operating leases | Instant | Calculated | Not included in company net debt |
| `term_loan_principal`, `revolver_borrowings`, `total_debt_principal` | Gross instrument balances | Instant | Reported | Total excludes letters of credit |
| `net_debt_company_definition` | Total debt principal less cash | Instant | Reported non-GAAP | Not the credit-agreement covenant numerator |

`adjustment_candidates.csv` uses `phase2_status=unreviewed`; values document the
company's disclosure and do not represent lender acceptance. `debt_terms.csv`
uses `reported`, `calculated`, `not_determinable`, and `conflicting_source` states.

## Debt and control datasets

| Field | Meaning |
|---|---|
| `term_id` | Stable debt-register record ID. |
| `instrument_name` | Term A, revolver, or terms shared by both facilities. |
| `as_of_date` | Balance or evidence date; not a forecast closing date. |
| `term_name` | Canonical model-facing debt term. |
| `value_text` | Source-faithful legal or financial description. |
| `numeric_value`, `units` | Optional model-ready scalar; blank when not determinable or inherently textual. |
| `status` | `reported`, `calculated`, `not_determinable`, or `conflicting_source`. |
| `conflict_group` | Links contradictory source statements that must remain visible. |
| `authority_resolution` | Governing-source decision; blank when no conflict exists. |
| `candidate_id` | Stable company-disclosed adjustment-candidate ID. |
| `company_treatment` | How the company used or characterized the item; not a lender decision. |
| `phase2_status` | Always `unreviewed` in Phase 1. |
| `override_id` | Stable override record; no active records currently exist. |
| `affected_raw_fact_id` | Exact fact changed by a manual override. |
| `reason`, `reviewer_note` | Required justification and review evidence for any override. |
| `original_value`, `replacement_value` | Required before-and-after override values. |
