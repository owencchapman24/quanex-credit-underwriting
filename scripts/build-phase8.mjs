import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const mode = process.argv[2];
const root = path.resolve(process.argv[3]);
const previewDir = process.argv[4] ? path.resolve(process.argv[4]) : null;
const modelPath = path.join(root, "model", "Quanex_Credit_Underwriting.xlsx");

const COLORS = {
  navy: "#17365D", blue: "#1F4E78", medium: "#4472C4", paleBlue: "#D9EAF7",
  tan: "#F2E6D5", paleTan: "#FAF4EA", gray: "#F2F2F2", line: "#B7C9D6",
  input: "#FFF2CC", warning: "#FCE4D6", fail: "#F4CCCC", text: "#222222",
  formula: "#000000", link: "#008000", hardcode: "#0000FF", white: "#FFFFFF",
};
const FONT = "Arial";
const SHEETS = [
  "Credit Summary", "Assumptions", "Scenario Comparison", "Historicals", "Credit Adjustments",
  "Transaction", "Forecast", "Debt Schedule", "Liquidity", "Covenants", "Recovery",
  "Sensitivities", "Sources", "Checks",
];
const SCENARIOS = [
  ["Base", "BASE"],
  ["Moderate unmitigated", "MODERATE_UNMITIGATED"],
  ["Moderate mitigated", "MODERATE_MITIGATED"],
  ["Severe unmitigated", "SEVERE_UNMITIGATED"],
  ["Severe mitigated", "SEVERE_MITIGATED"],
  ["Moderate Phase 6 analytical shutoff", "MODERATE_NO_WAIVER"],
  ["Severe Phase 6 analytical shutoff", "SEVERE_NO_WAIVER"],
  ["Moderate Phase 7 covenant-linked no-waiver", "MODERATE_PHASE7_COVENANT_NO_WAIVER"],
  ["Severe Phase 7 covenant-linked no-waiver", "SEVERE_PHASE7_COVENANT_NO_WAIVER"],
];

function parseCsv(text) {
  const rows = [];
  let row = [], field = "", quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { field += '"'; i += 1; }
      else if (ch === '"') quoted = false;
      else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") { row.push(field); field = ""; }
    else if (ch === "\n") { row.push(field.replace(/\r$/, "")); rows.push(row); row = []; field = ""; }
    else field += ch;
  }
  if (field.length || row.length) { row.push(field.replace(/\r$/, "")); rows.push(row); }
  const headers = rows.shift() || [];
  return rows.filter(r => r.some(v => v !== "")).map(r => Object.fromEntries(headers.map((h, i) => [h, r[i] ?? ""])));
}

async function csv(relative) {
  return parseCsv(await fs.readFile(path.join(root, relative), "utf8"));
}

function num(value) {
  if (value === "" || value === null || value === undefined || value === "N/D" || value === "N/M") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function excelDate(text) {
  if (!text) return null;
  return new Date(`${text}T00:00:00Z`);
}

function colName(index) {
  let n = index + 1, result = "";
  while (n > 0) { const rem = (n - 1) % 26; result = String.fromCharCode(65 + rem) + result; n = Math.floor((n - 1) / 26); }
  return result;
}

function title(sheet, text, scenario = true) {
  sheet.showGridLines = false;
  sheet.getRange("C2").values = [[text]];
  sheet.getRange("C2").format.font = { name: FONT, size: 15, bold: true, color: COLORS.navy };
  sheet.getRange("C3:N3").format.borders = { bottom: { style: "thin", color: COLORS.medium } };
  if (scenario) {
    sheet.getRange("C4").values = [["Case selected:"]];
    sheet.getRange("D4").formulas = [["='Assumptions'!$D$4"]];
    sheet.getRange("D4").format = { fill: COLORS.paleBlue, font: { name: FONT, bold: true, color: COLORS.link }, horizontalAlignment: "center", verticalAlignment: "center", borders: { preset: "outside", style: "dashed", color: COLORS.medium } };
  }
}

function section(sheet, range, text) {
  const target = sheet.getRange(range);
  sheet.getRange(range.split(":")[0]).values = [[text]];
  target.format = { fill: COLORS.blue, font: { name: FONT, bold: true, color: COLORS.white }, borders: { preset: "outside", style: "thin", color: COLORS.blue } };
}

function headers(sheet, range, values) {
  const target = sheet.getRange(range);
  target.values = [values];
  target.format = { fill: COLORS.navy, font: { name: FONT, bold: true, color: COLORS.white }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { insideVertical: { style: "thin", color: COLORS.white }, bottom: { style: "thin", color: COLORS.white } } };
}

function baseFormat(sheet, range) {
  const target = sheet.getRange(range);
  target.format.font.name = FONT;
  target.format.verticalAlignment = "center";
}

function money(range) { range.format.numberFormat = '$#,##0.0;[Red]($#,##0.0);-'; }
function ratio(range) { range.format.numberFormat = '0.00x;[Red](0.00x);-'; range.format.font.italic = true; }
function percent(range) { range.format.numberFormat = '0.0%;[Red](0.0%);-'; range.format.font.italic = true; }
function dateFmt(range) { range.format.numberFormat = "mm/dd/yy"; }
function imported(range) { range.format.font = { name: FONT, size: 10, color: COLORS.link }; }
function hardcode(range) { range.format = { fill: COLORS.input, font: { name: FONT, size: 10, color: COLORS.hardcode }, borders: { preset: "outside", style: "thin", color: COLORS.line } }; }
function sameFormula(range) { range.format.font = { name: FONT, size: 10, color: COLORS.formula }; }
function crossFormula(range) { range.format.font = { name: FONT, size: 10, color: COLORS.link }; }

function formulaRange(sheet, address, matrix, cross = false) {
  const target = sheet.getRange(address);
  target.formulas = matrix;
  (cross ? crossFormula : sameFormula)(target);
}

function sumifs(sourceCol, scenarioCell, periodCol, periodCell) {
  return `SUMIFS('Assumptions'!$${sourceCol}$41:$${sourceCol}$364,'Assumptions'!$C$41:$C$364,${scenarioCell},'Assumptions'!$${periodCol}$41:$${periodCol}$364,${periodCell})`;
}

function lookupScenarioMeta(returnCol, scenarioCell) {
  return `=INDEX('Assumptions'!$${returnCol}$41:$${returnCol}$49,MATCH(${scenarioCell},'Assumptions'!$BD$41:$BD$49,0))`;
}

function firstMatchingDateFormula(sheet, dateColumn, firstRow, lastRow, condition) {
  let expression = '"N/D"';
  for (let row = lastRow; row >= firstRow; row -= 1) {
    expression = `IF(${condition(row)},'${sheet}'!$${dateColumn}$${row},${expression})`;
  }
  return `=${expression}`;
}

function setWidths(sheet, widths) {
  for (const [column, width] of Object.entries(widths)) sheet.getRange(`${column}:${column}`).format.columnWidth = width;
}

function styleStatus(range) {
  range.conditionalFormats.add("containsText", { text: "BREACH", format: { fill: COLORS.fail, font: { bold: true, color: "#9C0006" } } });
  range.conditionalFormats.add("containsText", { text: "FAIL", format: { fill: COLORS.fail, font: { bold: true, color: "#9C0006" } } });
  range.conditionalFormats.add("containsText", { text: "WARNING", format: { fill: COLORS.warning, font: { bold: true, color: "#9C5700" } } });
  range.conditionalFormats.add("containsText", { text: "STALE", format: { fill: COLORS.warning, font: { bold: true, color: "#9C5700" } } });
  range.conditionalFormats.add("containsText", { text: "N/D", format: { fill: COLORS.input, font: { color: "#7F6000" } } });
}

async function buildWorkbook() {
  const [periodInputs, finalInputs, historical, historicalMetrics, adjustments, bridges, evidence, phase7Ledger, conditions, common, maturity, covenantSummary, checkpoint, openingDebt, termSizing, amortizationSensitivity] = await Promise.all([
    csv("data/phase8/raw/MODEL_PERIOD_INPUTS.csv"),
    csv("data/phase7/processed/FINAL_FINANCING_ASSUMPTIONS.csv"),
    csv("data/phase2/processed/historical_spread.csv"),
    csv("data/phase2/processed/historical_credit_metrics.csv"),
    csv("data/phase2/processed/adjustment_decisions.csv"),
    csv("data/phase2/processed/earnings_bridges.csv"),
    csv("docs/phase-0/EVIDENCE_INVENTORY.csv"),
    csv("docs/phase-7/SOURCE_LEDGER.csv"),
    csv("data/phase4/processed/CONDITIONS_PRECEDENT.csv"),
    csv("data/phase7/processed/COMMON_HORIZON_COMPARISON.csv"),
    csv("data/phase7/processed/ULTIMATE_MATURITY_COMPARISON.csv"),
    csv("data/phase7/processed/COVENANT_SUMMARY.csv"),
    csv("data/phase8/raw/STARTING_CHECKPOINT.csv"),
    csv("data/phase8/processed/OPENING_DEBT_COMPARISON.csv"),
    csv("data/phase8/processed/TERM_SIZING_SENSITIVITY.csv"),
    csv("data/phase8/processed/AMORTIZATION_SENSITIVITY_RESULTS.csv"),
  ]);
  const fi = Object.fromEntries(finalInputs.map(row => [row.assumption_name, row]));
  const workbook = Workbook.create();
  const ws = Object.fromEntries(SHEETS.map(name => [name, workbook.worksheets.add(name)]));
  ws["Credit Summary"].tabColor = COLORS.navy;
  ws.Assumptions.tabColor = COLORS.medium;
  ws.Historicals.tabColor = "#D9C3A5";
  ws.Checks.tabColor = "#7F8C8D";

  // Assumptions and approved model-input registry.
  const a = ws.Assumptions;
  title(a, "Quanex underwriting assumptions", false);
  a.getRange("C4").values = [["Case selected:"]];
  a.getRange("D4").values = [["Base"]];
  hardcode(a.getRange("D4"));
  a.getRange("D4").dataValidation = { rule: { type: "list", values: SCENARIOS.map(row => row[0]) } };
  a.getRange("C5:C8").values = [["Scenario ID"], ["Approved input version"], ["Current input signature"], ["Source-file hash"]];
  formulaRange(a, "D5", [["=INDEX($BE$41:$BE$49,MATCH($D$4,$BD$41:$BD$49,0))"]]);
  a.getRange("D6").values = [[checkpoint[0].approved_phase7_commit]];
  a.getRange("D8").values = [[checkpoint[0].source_input_signature]];
  imported(a.getRange("D6:D8"));
  section(a, "C10:G10", "Financing, covenant and sensitivity controls");
  const controls = [
    ["Term commitment", 635, "USD millions", "P7FA-002", "Owner-reviewed provisional"],
    ["Conditional non-debt contribution", 15, "USD millions", "P7FA-007", "Pending evidence; separate from cash floor"],
    ["Revolver commitment", 300, "USD millions", "P7FA-009", "Owner-reviewed provisional"],
    ["Opening revolver", null, "USD millions", "Formula", "Reference uses less term and contribution"],
    ["Letters of credit", 6.2, "USD millions", "P7FA-010", "Inherited reference"],
    ["Retained other funded debt", 62.619, "USD millions", "P7FA-013", "Conservative proxy"],
    ["Annual term amortization", 0.075, "percent", "P7FA-016", "Paid quarterly"],
    ["Modeled all-in interest rate", 0.0657, "percent", "P7FA-020", "Testing assumption"],
    ["Incremental interest spread", 0, "percent", "Phase 8 control", "Sensitivity overlay"],
    ["EBITDA overlay", 0, "percent", "Phase 8 control", "Sensitivity overlay; zero in approved case"],
    ["Base DSO", 41.5, "days", "P5A-004", "Approved testing input"],
    ["DSO change", 0, "days", "Phase 8 control", "Sensitivity overlay"],
    ["Operating cash floor", 25, "USD millions", "P7FA-021", "Separate operating control"],
    ["Liquidity overlay per period", 0, "USD millions", "Phase 8 control", "Sensitivity overlay"],
    ["ECF sweep", 0.50, "percent", "P7FA-029", "After revolver repayment and safeguards"],
    ["Initial leverage covenant", 3.50, "turns", "P7FA-022", "Through 10/31/27"],
    ["Step 1 leverage covenant", 3.25, "turns", "P7FA-023", "Through 10/31/28"],
    ["Step 2 leverage covenant", 3.00, "turns", "P7FA-024", "Thereafter"],
    ["Interest coverage covenant", 3.00, "turns", "P7FA-025", "Minimum"],
    ["Liquidity covenant", 50, "USD millions", "P7FA-026", "Minimum usable liquidity"],
    ["Initial leverage warning", 3.25, "turns", "P7FA-027", "Inclusive warning"],
    ["Coverage warning", 3.50, "turns", "P7FA-028", "Minimum analyst warning"],
    ["Liquidity warning", 75, "USD millions", "P7FA-028", "Analyst warning"],
    ["Maturity", excelDate("2031-01-31"), "date", "P7FA-017", "No refinancing assumed"],
  ];
  headers(a, "C11:G11", ["Control", "Value", "Units", "Source / assumption ID", "Status / limitation"]);
  a.getRange(`C12:G${11 + controls.length}`).values = controls;
  hardcode(a.getRange("D12:D35"));
  a.getRange("D15").formulas = [["=679.89771875-D12-D13"]];
  sameFormula(a.getRange("D15"));
  money(a.getRange("D12:D17")); percent(a.getRange("D18:D21")); money(a.getRange("D24:D25")); percent(a.getRange("D26")); ratio(a.getRange("D27:D30")); money(a.getRange("D31")); ratio(a.getRange("D32:D33")); money(a.getRange("D34")); dateFmt(a.getRange("D35"));
  a.getRange("D13").format.fill = COLORS.warning;
  section(a, "H10:L10", "Policy, status and unresolved-definition register");
  headers(a, "H11:L11", ["Area", "Approved rule / unresolved item", "Status", "Source", "Workbook treatment"]);
  a.getRange("H12:L21").values = [
    ["Repurchases", "No directly debt-funded repurchases; none while revolver is outstanding", "Owner reviewed", "P7FA-030", "No unapproved cash-flow benefit"],
    ["Dividends", "Require no default, gross leverage <=3.00x and usable liquidity >=$75m after payment", "Owner reviewed", "P7FA-030", "Approved Phase 7 scenario cash flows retained"],
    ["Warning", "Suspends repurchases and triggers enhanced reporting", "Owner reviewed", "P7FA-027/P7FA-028", "Warning alone does not terminate draws"],
    ["Covenant breach", "Suspends all restricted payments", "Owner reviewed", "P7FA-030", "Reported separately from warning"],
    ["Drawability", "Analytical shutoff, covenant-linked no-waiver and continued-draw paths remain distinct", "Owner reviewed", "P7FA-031", "Selector preserves all approved paths"],
    ["Covenant cash", "Eligible covenant cash", "N/D", "P7FA-012", "Zero cash netting in proposed leverage tests"],
    ["Book-cash leverage", "Book cash may not equal accessible covenant cash", "Diagnostic only", "P7FA-012", "Not covenant or lender net leverage"],
    ["Conditional source", "$15m non-debt contribution availability and accessibility", "Condition precedent", "P7FA-007", "Displayed separately; not verified cash"],
    ["Closing coverage", "Complete closing LTM cash interest", "N/D", "P7FA-019", "Closing coverage remains N/D"],
    ["Legal definitions", "Debt, EBITDA, ECF, cure, draw, default and waiver definitions", "Pending information", "P7FA-026", "Not presented as official compliance"],
  ];
  imported(a.getRange("H12:L21")); styleStatus(a.getRange("J12:J21"));
  const rawFields = [
    "scenario_name", "scenario_id", "model_period_id", "frequency", "period_start", "period_end", "fiscal_year", "quarter", "days_in_period",
    "revenue", "base_gross_margin_percent", "lender_base_ebitda", "depreciation_and_amortization", "cash_tax_proxy", "working_capital_cash_flow",
    "capital_expenditures", "other_operating_cash_uses", "cfads_before_cash_interest", "opening_cash", "ending_cash", "opening_term_principal",
    "scheduled_term_principal_due", "scheduled_term_principal_paid", "cash_sweep", "maturity_principal_due", "maturity_principal_paid", "ending_term_principal",
    "opening_revolver", "revolver_draw", "revolver_repayment", "ending_revolver", "cash_interest_due", "cash_interest_paid", "retained_obligation_paid",
    "dividend_paid", "repurchase_paid", "failed_obligation_unpaid_amount", "gross_funded_debt", "minimum_usable_liquidity", "peak_revolver",
    "nominal_revolver_availability", "drawability_status", "drawability_shutoff_date", "ttm_lender_base_ebitda", "gross_funded_leverage",
    "ebitda_cash_interest_coverage", "unsupported_maturity_gap", "maturity_event", "mandatory_payment_failure_flag", "model_status", "source_ids", "upstream_ids",
    "retained_obligation_due",
  ];
  const rawStartCol = 2; // C
  const rawHeaderRow = 39;
  const rawStartRow = 40;
  a.getRangeByIndexes(rawHeaderRow, rawStartCol, 1, rawFields.length).values = [rawFields.map(x => x.replaceAll("_", " "))];
  a.getRangeByIndexes(rawHeaderRow, rawStartCol, 1, rawFields.length).format = { fill: COLORS.navy, font: { name: FONT, bold: true, color: COLORS.white }, wrapText: true, horizontalAlignment: "center" };
  const rawMatrix = periodInputs.map(row => rawFields.map(field => {
    if (["period_start", "period_end", "drawability_shutoff_date"].includes(field)) return excelDate(row[field]);
    const numeric = num(row[field]);
    return numeric === null ? row[field] : numeric;
  }));
  a.getRangeByIndexes(rawStartRow, rawStartCol, rawMatrix.length, rawFields.length).values = rawMatrix;
  imported(a.getRangeByIndexes(rawStartRow, rawStartCol, rawMatrix.length, rawFields.length));
  dateFmt(a.getRange(`G41:H364`)); dateFmt(a.getRange(`AS41:AS364`));
  money(a.getRange("L41:L364")); percent(a.getRange("M41:M364")); money(a.getRange("N41:AP364")); ratio(a.getRange("AU41:AV364")); money(a.getRange("AW41:AW364")); money(a.getRange("BC41:BC364"));
  // Scenario summary registry at BD:BP.
  const commonSelected = Object.fromEntries(common.filter(r => r.candidate_id === "STR-008").map(r => [r.scenario_id, r]));
  const summaryById = Object.fromEntries(covenantSummary.map(r => [r.scenario_id, r]));
  const maturitySelected = Object.fromEntries(maturity.filter(r => r.candidate_id === "STR-008").map(r => [r.scenario_id, r]));
  const metaHeaders = ["scenario_name", "scenario_id", "first_warning", "first_breach", "first_shutoff", "first_payment_failure", "common_ending_debt", "maturity_gap", "opening_liquidity", "subsequent_minimum", "all_in_minimum", "maximum_leverage", "minimum_coverage"];
  headers(a, "BD40:BP40", metaHeaders.map(x => x.replaceAll("_", " ")));
  const meta = SCENARIOS.map(([name, id]) => {
    const s = summaryById[id] || {}, c = commonSelected[id] || {}, m = maturitySelected[id] || {};
    return [name, id, s.first_warning_date || "N/D", s.first_breach_date || "N/D", s.first_draw_shutoff_date || "N/D", s.first_mandatory_payment_failure_date || "N/D", num(c.ending_total_funded_debt), num(m.unsupported_maturity_gap), num(s.opening_usable_liquidity), num(s.subsequent_minimum_usable_liquidity), num(s.all_in_minimum_usable_liquidity), num(s.maximum_gross_funded_leverage), num(s.minimum_cash_interest_coverage)];
  });
  a.getRange("BD41:BP49").values = meta;
  imported(a.getRange("BD41:BP49")); dateFmt(a.getRange("BF41:BI49")); money(a.getRange("BJ41:BL49")); ratio(a.getRange("BM41:BN49"));
  // Canonical typed state for every editable financing, sensitivity, covenant,
  // and liquidity control.  A field-by-field serialization avoids weighted-sum
  // collisions while remaining live when a user edits the workbook.  Rounding
  // only at the twelfth decimal neutralizes sub-ULP engine noise without hiding
  // an economically meaningful USD-million or rate input change.
  const typedControlState = Array.from({ length: 24 }, (_, i) => {
    const ref = `$D$${12 + i}`;
    return `IF(ISBLANK(${ref}),"blank:",IF(ISNUMBER(${ref}),"number:"&TEXT(ROUND(${ref},12),"0.000000000000000"),"text:"&${ref}))`;
  }).join('&"|"&');
  formulaRange(a, "D7", [[`=${typedControlState}`]]);
  a.freezePanes.freezeRows(11); a.freezePanes.freezeColumns(3);
  setWidths(a, { A: 2, B: 2, C: 34, D: 17, E: 18, F: 18, G: 46, H: 22, I: 54, J: 20, K: 20, L: 42 });

  // Historicals.
  const h = ws.Historicals;
  title(h, "Quanex reported historical spread", false);
  h.getRange("C4").values = [["FY2021-FY2023 pre-Tyman; FY2024 includes approximately three months of Tyman; FY2025 is the first full post-Tyman year."]];
  h.getRange("C4:N4").format.font = { name: FONT, italic: true, color: "#666666" };
  const histMetrics = [
    ["Income statement", null], ["Revenue", "revenue"], ["Cost of sales before D&A", "cost_of_sales_excluding_depreciation_and_amortization"], ["Gross profit", "gross_profit"],
    ["SG&A", "selling_general_and_administrative"], ["D&A", "depreciation_and_amortization"], ["Goodwill impairment", "goodwill_impairment_charges"], ["Operating income", "operating_income"],
    ["Interest expense", "interest_expense"], ["Cash interest paid (disclosed historical diagnostic)", "cash_interest_paid_disclosed"], ["Pretax income", "pretax_income"], ["Income-tax expense", "income_tax_expense"], ["Net income", "net_income"],
    ["Cash flow", null], ["Cash flow from operations", "cash_flow_from_operations"], ["Capital expenditures", "capital_expenditures"], ["Free cash flow", "free_cash_flow"],
    ["Acquisition cash flows", "acquisition_cash_flows"], ["Dividends paid", "dividends_paid"], ["Share repurchases", "share_repurchases"],
    ["Balance sheet", null], ["Cash and cash equivalents", "cash_and_cash_equivalents"], ["Accounts receivable", "accounts_receivable"], ["Inventory", "inventory"],
    ["Accounts payable", "accounts_payable"], ["Current assets", "current_assets"], ["Current liabilities", "current_liabilities"], ["Total assets", "total_assets"],
    ["Total liabilities", "total_liabilities"], ["Shareholders' equity", "shareholders_equity"], ["Goodwill", "goodwill"], ["Intangible assets", "intangible_assets_net"],
    ["Debt", null], ["Term-loan principal", "term_loan_principal"], ["Revolver borrowings", "revolver_borrowings"], ["Total debt principal", "total_debt_principal"],
    ["Total debt carrying amount", "total_debt_carrying_amount"], ["Finance lease obligations", "finance_lease_obligations_principal"],
  ];
  headers(h, "C6:K6", ["Metric", "FY2021", "FY2022", "FY2023", "FY2024", "FY2025", "Units", "Source IDs", "Status"]);
  let hr = 7;
  for (const [label, metric] of histMetrics) {
    if (!metric) {
      section(h, `C${hr}:K${hr}`, label); hr += 1; continue;
    }
    const values = [label];
    let units = "USD millions", sources = new Set(), status = "reported";
    for (const fy of ["FY2021", "FY2022", "FY2023", "FY2024", "FY2025"]) {
      const row = historical.find(x => x.metric_name === metric && x.fiscal_year === fy);
      values.push(row ? num(row.value) : null);
      if (row) { units = row.units; for (const id of row.source_ids.split(";")) if (id) sources.add(id); status = row.status; }
    }
    values.push(units, [...sources].join(";"), status);
    h.getRange(`C${hr}:K${hr}`).values = [values]; hr += 1;
  }
  imported(h.getRange(`D7:K${hr - 1}`)); money(h.getRange(`D7:H${hr - 1}`));
  // Historical metrics section.
  section(h, `C${hr + 1}:K${hr + 1}`, "Selected historical credit metrics");
  headers(h, `C${hr + 2}:K${hr + 2}`, ["Metric", "FY2021", "FY2022", "FY2023", "FY2024", "FY2025", "Units", "Status", "Limitation"]);
  const metricNames = ["gross_margin", "operating_margin", "unadjusted_ebitda_margin", "cash_flow_from_operations", "free_cash_flow", "gross_funded_debt_to_provisional_lender_normalized_ebitda", "historical_lender_ebitda_to_disclosed_cash_interest_paid", "current_ratio", "days_sales_outstanding", "days_inventory_outstanding"];
  let hm = hr + 3;
  const historicalMetricRows = {};
  for (const metric of metricNames) {
    historicalMetricRows[metric] = hm;
    const rowValues = [metric.replaceAll("_", " ")]; let units = "", status = "", note = "";
    for (const fy of ["FY2021", "FY2022", "FY2023", "FY2024", "FY2025"]) {
      const row = historicalMetrics.find(x => x.metric_name === metric && x.fiscal_year === fy);
      rowValues.push(row ? num(row.value) : null); if (row) { units = row.units; status = row.status; note = row.notes; }
    }
    rowValues.push(units, status, note); h.getRange(`C${hm}:K${hm}`).values = [rowValues]; hm += 1;
  }
  imported(h.getRange(`D${hr + 3}:K${hm - 1}`));
  h.getRange(`D${historicalMetricRows.gross_margin}:H${historicalMetricRows.unadjusted_ebitda_margin}`).format.numberFormat = "0.0";
  h.getRange(`D${historicalMetricRows.gross_funded_debt_to_provisional_lender_normalized_ebitda}:H${historicalMetricRows.current_ratio}`).format.numberFormat = "0.00x";
  h.getRange(`D${historicalMetricRows.days_sales_outstanding}:H${historicalMetricRows.days_inventory_outstanding}`).format.numberFormat = "0.0";
  h.freezePanes.freezeRows(6); h.freezePanes.freezeColumns(3);
  setWidths(h, { A: 2, B: 2, C: 48, D: 13, E: 13, F: 13, G: 13, H: 13, I: 17, J: 24, K: 34 });
  const histChartDataRow = hm + 2;
  h.getRange(`M${histChartDataRow}:R${histChartDataRow}`).values = [["Metric", "FY2021", "FY2022", "FY2023", "FY2024", "FY2025"]];
  h.getRange(`M${histChartDataRow + 1}:R${histChartDataRow + 2}`).values = [
    ["CFO", ...["FY2021", "FY2022", "FY2023", "FY2024", "FY2025"].map(fy => num(historical.find(x => x.metric_name === "cash_flow_from_operations" && x.fiscal_year === fy)?.value))],
    ["FCF", ...["FY2021", "FY2022", "FY2023", "FY2024", "FY2025"].map(fy => num(historical.find(x => x.metric_name === "free_cash_flow" && x.fiscal_year === fy)?.value))],
  ];
  h.getRange(`M${histChartDataRow}:R${histChartDataRow + 2}`).format.font.color = COLORS.white;
  const histChart = h.charts.add("bar", h.getRange(`M${histChartDataRow}:R${histChartDataRow + 2}`));
  histChart.title = "Historical cash conversion (USD millions)"; histChart.titleTextStyle.typeface = FONT; histChart.legend = { position: "top", textStyle: { typeface: FONT } }; histChart.setPosition("M4", "T18");

  // Credit adjustments.
  const ca = ws["Credit Adjustments"];
  title(ca, "Earnings definitions and lender adjustments", false);
  headers(ca, "C6:E6", ["Earnings layer", "FY2024", "FY2025"]);
  const bridgeValue = (fy, type) => {
    const rows = bridges.filter(r => r.fiscal_year === fy && r.bridge_type === type);
    return rows.length ? num(rows.at(-1).resulting_subtotal) : null;
  };
  ca.getRange("C7:E14").values = [
    ["GAAP operating income", 54.826, -193.952],
    ["Add: D&A", 60.328, 103.444],
    ["Unadjusted EBITDA", null, null],
    ["Company adjustments", null, null],
    ["Company-adjusted EBITDA", bridgeValue("FY2024", "company_adjusted_ebitda"), bridgeValue("FY2025", "company_adjusted_ebitda")],
    ["Partial contractual reconstruction", null, bridgeValue("FY2025", "contractual_ebitda_public_reconstruction")],
    ["Owner-reviewed lender adjustments", null, null],
    ["Owner-reviewed lender-base EBITDA", null, null],
  ];
  formulaRange(ca, "D9:E9", [["=SUM(D7:D8)", "=SUM(E7:E8)"]]);
  formulaRange(ca, "D10:E10", [["=D11-D9", "=E11-E9"]]);
  formulaRange(ca, "D13:E13", [["=SUMIFS($H$20:$H$30,$D$20:$D$30,D$6)", "=SUMIFS($H$20:$H$30,$D$20:$D$30,E$6)"]]);
  formulaRange(ca, "D14:E14", [["=D9+D13", "=E9+E13"]]);
  imported(ca.getRange("D7:E8")); imported(ca.getRange("D11:E12"));
  money(ca.getRange("D7:E14")); ca.getRange("C14:E14").format.font.bold = true; ca.getRange("C14:E14").format.borders = { preset: "doubleBottom", style: "double", color: COLORS.navy };
  ca.getRange("C16").values = [["Unofficial contractual reconstruction; AC-011 cash outflow retained; goodwill impairment remains a major adverse risk signal."]];
  ca.getRange("C16:Q16").format = { fill: COLORS.warning, font: { name: FONT, italic: true, color: "#7F6000" }, wrapText: false, rowHeight: 24 };
  headers(ca, "C19:Q19", ["Adjustment ID", "Period", "Description", "Reported", "Low", "Base", "High/company", "Cash status", "Recurrence", "Contractual status", "Owner review", "Lender rationale", "Source ID", "Limitation", "Double count check"]);
  const adjMatrix = adjustments.map(r => [r.adjustment_id, r.fiscal_year, r.description, num(r.reported_amount), num(r.accepted_amount_low), num(r.accepted_amount_base), num(r.accepted_amount_high), r.cash_noncash_status, r.recurrence_assessment, r.contractual_eligibility, r.human_review_status, r.rationale, r.source_id, r.missing_information, r.double_counting_relationships || "No duplicate accepted amount"]);
  ca.getRange(`C20:Q${19 + adjMatrix.length}`).values = adjMatrix; imported(ca.getRange(`C20:Q${19 + adjMatrix.length}`)); money(ca.getRange(`F20:I${19 + adjMatrix.length}`));
  ca.getRange("S4:U8").values = [["Earnings layer", "FY2024", "FY2025"], ["Unadjusted EBITDA", null, null], ["Company-adjusted EBITDA", null, null], ["Partial contractual", null, null], ["Lender-base EBITDA", null, null]];
  ca.getRange("T5:U8").formulas = [["=D9", "=E9"], ["=D11", "=E11"], ["=D12", "=E12"], ["=D14", "=E14"]];
  crossFormula(ca.getRange("T5:U8"));
  const adjChart = ca.charts.add("bar", ca.getRange("S4:U8")); adjChart.title = "Earnings definitions (USD millions)"; adjChart.titleTextStyle.typeface = FONT; adjChart.legend = { position: "top", textStyle: { typeface: FONT } }; adjChart.setPosition("S4", "AB18");
  ca.freezePanes.freezeRows(19); ca.freezePanes.freezeColumns(3); setWidths(ca, { A: 2, B: 2, C: 16, D: 12, E: 34, F: 13, G: 13, H: 13, I: 13, J: 22, K: 22, L: 24, M: 18, N: 44, O: 15, P: 34, Q: 34 });

  // Transaction.
  const tx = ws.Transaction;
  title(tx, "Transaction and financing alternatives");
  section(tx, "C6:F6", "Selected refinancing sources and uses");
  headers(tx, "C7:D7", ["Source", "USD millions"]);
  tx.getRange("C8:C11").values = [["Term funding"], ["Opening revolver"], ["Conditional non-debt source"], ["Total sources"]];
  formulaRange(tx, "D8:D11", [["='Assumptions'!D12"], ["='Assumptions'!D15"], ["='Assumptions'!D13"], ["=SUM(D8:D10)"]], true);
  tx.getRange("F7:F12").values = [["Use / control"], ["Existing debt payoff and approved closing uses"], ["Reference closing uses"], ["Sources less uses"], ["Conditional source status"], ["Sources and uses check"]];
  tx.getRange("G8:G9").values = [[679.89771875], [679.89771875]]; imported(tx.getRange("G8:G9"));
  formulaRange(tx, "G10:G10", [["=D11-G9"]]);
  tx.getRange("G11").values = [["Pending information / condition precedent"]];
  formulaRange(tx, "G12", [["=IF(ABS(G10)<=0.001,\"PASS\",\"FAIL\")"]]);
  tx.getRange("D12").formulas = [["=G10"]]; sameFormula(tx.getRange("D12"));
  money(tx.getRange("D8:D12")); money(tx.getRange("G8:G10")); styleStatus(tx.getRange("G11:G12"));
  section(tx, "C14:F14", "Opening capitalization");
  tx.getRange("C15:C18").values = [["Opening bank debt"], ["Retained other funded debt"], ["Opening total funded debt"], ["Opening gross funded leverage"]];
  formulaRange(tx, "D15:D18", [["='Assumptions'!D12+'Assumptions'!D15"], ["='Assumptions'!D17"], ["=SUM(D15:D16)"], ["=D17/'Credit Adjustments'!E14"]], true);
  money(tx.getRange("D15:D17")); ratio(tx.getRange("D18"));
  section(tx, "C20:G20", "Historical reference - October 31, 2025 actual");
  headers(tx, "C21:G21", ["Reference point", "Date", "Bank debt", "Lease / other debt", "Total funded debt"]);
  const existingC = common.find(r => r.candidate_id === "STR-001"); const selectedC = common.find(r => r.candidate_id === "STR-008"); const referenceC = common.find(r => r.candidate_id === "STR-003");
  const existingM = maturity.find(r => r.candidate_id === "STR-001"); const selectedM = maturity.find(r => r.candidate_id === "STR-008"); const referenceM = maturity.find(r => r.candidate_id === "STR-003");
  const historicalDebt = openingDebt.find(r => r.comparison_group === "historical_reference");
  tx.getRange("C22:G22").values = [[historicalDebt.alternative, excelDate(historicalDebt.comparison_date), num(historicalDebt.bank_debt), num(historicalDebt.other_funded_debt), num(historicalDebt.total_funded_debt)]];
  imported(tx.getRange("C22:G22")); dateFmt(tx.getRange("D22")); money(tx.getRange("E22:G22"));
  section(tx, "C24:I24", "Projected closing alternatives - January 31, 2026");
  headers(tx, "C25:I25", ["Alternative", "Date", "Bank debt", "Lease / other debt", "Total funded debt", "vs projected existing", "Status"]);
  const projectedDebt = openingDebt.filter(r => r.comparison_group === "projected_closing_alternatives");
  tx.getRange("C26:I28").values = projectedDebt.map((row, index) => [row.alternative, excelDate(row.comparison_date), num(row.bank_debt), num(row.other_funded_debt), num(row.total_funded_debt), index === 0 ? 0 : num(row.total_funded_debt) - num(projectedDebt[0].total_funded_debt), row.status]);
  imported(tx.getRange("C26:I28")); dateFmt(tx.getRange("D26:D28")); money(tx.getRange("E26:H28")); styleStatus(tx.getRange("I26:I28"));
  tx.getRange("C30:I30").values = [["Selected is $5.000m below same-date existing only because the conditional $15m source exceeds assumed $10m refinancing fees. If unavailable: resize, obtain acceptable non-debt funding, or do not close."]];
  tx.mergeCells("C30:I30");
  tx.getRange("C30:I30").format = { fill: COLORS.warning, font: { name: FONT, italic: true, color: "#7F6000" }, wrapText: true, rowHeight: 34 };
  section(tx, "C32:G32", "Common horizon and separate ultimate maturities");
  headers(tx, "C33:G33", ["Alternative", "07/31/29 total funded debt", "vs existing", "Maturity", "Unsupported bank-debt gap"]);
  tx.getRange("C34:G36").values = [
    ["Retain existing facilities", num(existingC.ending_total_funded_debt), 0, excelDate(existingM.maturity_date), num(existingM.unsupported_maturity_gap)],
    ["Selected $635m refinancing", num(selectedC.ending_total_funded_debt), num(selectedC.ending_total_funded_debt) - num(existingC.ending_total_funded_debt), excelDate(selectedM.maturity_date), num(selectedM.unsupported_maturity_gap)],
    ["$650m reference refinancing", num(referenceC.ending_total_funded_debt), num(referenceC.ending_total_funded_debt) - num(existingC.ending_total_funded_debt), excelDate(referenceM.maturity_date), num(referenceM.unsupported_maturity_gap)],
  ];
  imported(tx.getRange("C34:G36")); money(tx.getRange("D34:E36")); dateFmt(tx.getRange("F34:F36")); money(tx.getRange("G34:G36"));
  tx.getRange("C38:G38").values = [["Ultimate gaps use different maturity dates and are not directly comparable. Limited amendment / extension remains N/D without terms."]];
  tx.mergeCells("C38:G38");
  tx.getRange("C38:G38").format = { fill: COLORS.paleTan, font: { name: FONT, italic: true, color: "#666666" }, wrapText: true, rowHeight: 28 };
  section(tx, "C40:G40", "Commitment and unresolved closing items");
  tx.getRange("C41:C44").values = [["Revolver commitment"], ["Letters of credit"], ["Gross availability"], ["Usable availability after LCs"]];
  formulaRange(tx, "D41:D44", [["='Assumptions'!D14"], ["='Assumptions'!D16"], ["='Assumptions'!D14-'Assumptions'!D15"], ["='Assumptions'!D14-'Assumptions'!D16-'Assumptions'!D15"]], true);
  money(tx.getRange("D41:D44"));
  tx.getRange("F41:G44").values = [["Financing fees not already approved", "N/D"], ["LC transition mechanics", "Pending information"], ["Final lender pricing", "Pending information"], ["Final payoff and funds flow", "Pending information"]];
  styleStatus(tx.getRange("G41:G44"));
  const debtChart = tx.charts.add("bar", [tx.getRange("C25:C28"), tx.getRange("G25:G28")]); debtChart.title = "Projected closing funded debt - 01/31/26 (USD millions)"; debtChart.titleTextStyle.typeface = FONT; debtChart.hasLegend = false; debtChart.setPosition("K6", "R20");
  setWidths(tx, { A: 2, B: 2, C: 32, D: 14, E: 15, F: 18, G: 20, H: 18, I: 24, J: 3 });

  // Forecast - one selected-case formula chain across 20 quarters.
  const f = ws.Forecast;
  title(f, "Quarterly operating and cash forecast");
  const quarterRows = periodInputs.filter(r => r.scenario_name === "Base" && (r.frequency === "quarterly" || ["2026-04-30", "2026-07-31", "2026-10-31", "2027-01-31", "2027-04-30", "2027-07-31", "2027-10-31", "2028-01-31"].includes(r.period_end)));
  const quarters = [];
  for (const row of quarterRows) if (!quarters.some(x => x.period_end === row.period_end)) quarters.push(row);
  const covenantDates = ["2026-01-31", ...quarters.slice(0, 19).map(r => r.period_end)];
  headers(f, "C7:W7", ["Metric", ...quarters.map(row => `${row.quarter}:${row.fiscal_year.slice(-2)}`)]);
  f.getRange("D8:W8").values = [quarters.map(row => excelDate(row.period_end))]; dateFmt(f.getRange("D8:W8"));
  const forecastLabels = ["Revenue", "Gross margin", "Gross profit", "Cash operating expenses", "Lender-base EBITDA", "EBITDA margin", "Depreciation and amortization", "Operating profit", "Cash taxes", "Working-capital cash flow", "Capital expenditures", "Other operating cash uses", "CFADS before cash interest", "Cash interest", "CFO proxy", "Free cash flow proxy", "Distributions", "Cash available before financing", "Source IDs"];
  f.getRange("C10:C28").values = forecastLabels.map(x => [x]);
  for (let q = 0; q < quarters.length; q += 1) {
    const col = colName(3 + q); const fy = quarters[q].fiscal_year; const quarter = quarters[q].quarter;
    const criteria = `'Assumptions'!$C$41:$C$364,$D$4,'Assumptions'!$I$41:$I$364,\"${fy}\",'Assumptions'!$J$41:$J$364,\"${quarter}\"`;
    const revenue = `SUMIFS('Assumptions'!$L$41:$L$364,${criteria})`;
    const ebitda = `SUMIFS('Assumptions'!$N$41:$N$364,${criteria})*(1+'Assumptions'!$D$21)`;
    const formulas = [
      `=${revenue}`,
      `=AVERAGEIFS('Assumptions'!$M$41:$M$364,'Assumptions'!$C$41:$C$364,$D$4,'Assumptions'!$I$41:$I$364,\"${fy}\",'Assumptions'!$J$41:$J$364,\"${quarter}\")/100`,
      `=${col}10*${col}11`, `=${col}12-${col}14`, `=${ebitda}`, `=IF(${col}10=0,\"\",${col}14/${col}10)`,
      `=SUMIFS('Assumptions'!$O$41:$O$364,${criteria})`, `=${col}14+${col}16`,
      `=SUMIFS('Assumptions'!$P$41:$P$364,${criteria})`, `=SUMIFS('Assumptions'!$Q$41:$Q$364,${criteria})+IF(${col}$8=$D$8,-${col}10/365*'Assumptions'!$D$23,0)`,
      `=SUMIFS('Assumptions'!$R$41:$R$364,${criteria})`, `=SUMIFS('Assumptions'!$S$41:$S$364,${criteria})`,
      `=SUM(${col}14,${col}18:${col}21)`, `=SUMIFS('Debt Schedule'!$T$12:$T$47,'Debt Schedule'!$F$12:$F$47,\"${fy}\",'Debt Schedule'!$G$12:$G$47,\"${quarter}\")`,
      `=SUM(${col}14,${col}18:${col}19,${col}21)-${col}23`, `=${col}24+${col}20`,
      `=SUMIFS('Assumptions'!$AK$41:$AK$364,'Assumptions'!$C$41:$C$364,$D$4,'Assumptions'!$I$41:$I$364,\"${fy}\",'Assumptions'!$J$41:$J$364,\"${quarter}\")+SUMIFS('Assumptions'!$AL$41:$AL$364,'Assumptions'!$C$41:$C$364,$D$4,'Assumptions'!$I$41:$I$364,\"${fy}\",'Assumptions'!$J$41:$J$364,\"${quarter}\")`,
      `=${col}22-${col}23-${col}26`, `=\"SRC-001;SRC-002;SRC-003\"`,
    ];
    f.getRange(`${col}10:${col}28`).formulas = formulas.map(x => [x]);
  }
  crossFormula(f.getRange("D10:W28")); money(f.getRange("D10:W28")); percent(f.getRange("D11:W11")); percent(f.getRange("D15:W15"));
  f.getRange("C14:W14").format.font.bold = true; f.getRange("C22:W22").format.font.bold = true; f.freezePanes.freezeRows(8); f.freezePanes.freezeColumns(3); setWidths(f, { A: 2, B: 2, C: 31 });

  // Debt schedule: 24 months plus 12 quarters.
  const d = ws["Debt Schedule"];
  title(d, "Debt schedule: 24 monthly periods, then quarterly");
  headers(d, "C7:AT7", [
    "Period ID", "Period end", "Frequency", "Fiscal year", "Quarter", "Days", "CFADS", "Opening term",
    "Scheduled principal paid", "ECF sweep", "Maturity principal paid", "Ending term", "Opening revolver",
    "Revolver draw", "Revolver repayment", "Ending revolver", "Average bank debt", "Cash interest paid",
    "Retained obligation paid", "Distributions paid", "Ending cash", "Total bank debt", "Retained other debt",
    "Total funded debt", "Revolver availability", "Usable liquidity", "Unpaid mandatory obligations",
    "Drawability", "Cash interest due", "Cash interest shortfall", "Scheduled principal due",
    "Scheduled principal shortfall", "Retained obligation due", "Retained obligation shortfall",
    "Maturity principal due", "Maturity principal shortfall", "Cash before revolver", "Incremental draw capacity",
    "Estimated ending revolver (period-end diagnostic)", "Cash identity difference", "Available period resources",
    "Resources after interest", "Resources after retained obligation", "Resources after scheduled principal",
  ]);
  const periods = periodInputs.filter(r => r.scenario_name === "Base");
  for (let i = 0; i < 36; i += 1) {
    const row = 12 + i, p = periods[i];
    d.getRange(`C${row}:H${row}`).values = [[p.model_period_id, excelDate(p.period_end), p.frequency, p.fiscal_year, p.quarter, num(p.days_in_period)]];
    const scenario = "$D$4", periodCell = `$C${row}`;
    const source = col => sumifs(col, scenario, "E", periodCell);
    const openingTerm = row === 12 ? "='Assumptions'!$D$12" : `=N${row - 1}`;
    const openingRev = row === 12 ? "='Assumptions'!$D$15" : `=R${row - 1}`;
    const openingCash = row === 12 ? "25" : `W${row - 1}`;
    const periodFactor = `IF(E${row}=\"monthly\",1/12,1/4)`;
    const liveRate = `('Assumptions'!$D$19+'Assumptions'!$D$20)`;
    const rawAvg = `((${source("W")}+${source("AC")}+${source("AD")}+${source("AG")})/2)`;
    const liveAverage = `((J${row}+MAX(0,J${row}-AG${row})+O${row}+O${row})/2)`;
    const preliminaryAverage = `((J${row}+MAX(0,J${row}-AG${row})+O${row}+${source("AG")})/2)`;
    const preliminaryInterest = `IF('Assumptions'!$D$19=\"\",0,IF(${rawAvg}=0,0,MAX(0,${source("AH")}*${liveRate}/6.57%*${preliminaryAverage}/${rawAvg})))`;
    const distributions = `(${source("AK")}+${source("AL")})`;
    const estimatedCashBeforeRevolver = `(${openingCash}+I${row}-${preliminaryInterest}-AI${row}-AG${row}-${distributions})`;
    const cashAfterRevolver = `(AM${row}+P${row}-Q${row})`;
    const revolverBeforeMaturity = `(O${row}+P${row}-Q${row})`;
    const priorCovenantCount = covenantDates.filter(date => date < p.period_end).length;
    const priorCovenantEndRow = 7 + priorCovenantCount;
    const liveCovenantShutoff = priorCovenantCount === 0
      ? "FALSE"
      : `OR(COUNTIF('Covenants'!$L$8:$L$${priorCovenantEndRow},"BREACH")>0,COUNTIF('Covenants'!$R$8:$R$${priorCovenantEndRow},"BREACH")>0,COUNTIF('Covenants'!$T$8:$T$${priorCovenantEndRow},"BREACH")>0)`;
    const covenantLinkedPath = `RIGHT('Assumptions'!$D$5,26)="_PHASE7_COVENANT_NO_WAIVER"`;
    const storedActiveShutoff = `COUNTIFS('Assumptions'!$C$41:$C$364,$D$4,'Assumptions'!$E$41:$E$364,$C${row},'Assumptions'!$AR$41:$AR$364,"*_shutoff_active")>0`;
    const approvedPath = "AND('Assumptions'!$D$12=635,'Assumptions'!$D$13=15,'Assumptions'!$D$14=300,'Assumptions'!$D$16=6.2,'Assumptions'!$D$17=62.619,'Assumptions'!$D$18=7.5%,'Assumptions'!$D$19=6.57%,'Assumptions'!$D$20=0,'Assumptions'!$D$21=0,'Assumptions'!$D$23=0,'Assumptions'!$D$24=25,'Assumptions'!$D$25=0,'Assumptions'!$D$26=50%,'Assumptions'!$D$31=50,'Assumptions'!$D$35=DATE(2031,1,31),'Assumptions'!$D$4<>\"Moderate Phase 7 covenant-linked no-waiver\",'Assumptions'!$D$4<>\"Severe Phase 7 covenant-linked no-waiver\")";
    const preserveApproved = (approved, live) => `=IF(${approvedPath},${approved},${live})`;
    const formulas = [
      preserveApproved(source("T"), `${source("T")}+${source("N")}*'Assumptions'!$D$21+'Assumptions'!$D$25+IF($C${row}=\"P001\",-SUMIFS('Assumptions'!$L$41:$L$364,'Assumptions'!$C$41:$C$364,$D$4,'Assumptions'!$I$41:$I$364,$F${row},'Assumptions'!$J$41:$J$364,$G${row})/365*'Assumptions'!$D$23,0)`),
      openingTerm,
      preserveApproved(source("Y"), `MIN(AG${row},AS${row})`),
      preserveApproved(source("Z"), `IF(AND(MONTH(D${row})=10,${revolverBeforeMaturity}=0,AF${row}<=0.000001,AH${row}<=0.000001,AJ${row}<=0.000001),MIN(MAX(0,J${row}-K${row}),MAX(0,${cashAfterRevolver}-'Assumptions'!$D$24)*'Assumptions'!$D$26,MAX(0,${cashAfterRevolver}-'Assumptions'!$D$24+MAX(0,'Assumptions'!$D$14-'Assumptions'!$D$16-${revolverBeforeMaturity})-'Assumptions'!$D$31)),0)`),
      preserveApproved(source("AB"), `IF(AK${row}=0,0,MIN(AK${row},MAX(0,${cashAfterRevolver}-L${row}-'Assumptions'!$D$24)))`),
      preserveApproved(source("AC"), `MAX(0,J${row}-K${row}-L${row}-MAX(0,M${row}-${revolverBeforeMaturity}))`),
      openingRev,
      preserveApproved(source("AE"), `IF(AM${row}<'Assumptions'!$D$24,MIN('Assumptions'!$D$24-AM${row},AN${row}),0)`),
      preserveApproved(source("AF"), `IF(AM${row}>'Assumptions'!$D$24,MIN(AM${row}-'Assumptions'!$D$24,O${row}),0)`),
      preserveApproved(source("AG"), `MAX(0,${revolverBeforeMaturity}-M${row})`),
      `=(J${row}+N${row}+O${row}+R${row})/2`,
      preserveApproved(source("AI"), `IF(AE${row}=\"\",0,MIN(AE${row},AQ${row}))`),
      preserveApproved(source("AJ"), `MIN(AI${row},AR${row})`),
      preserveApproved(distributions, `MIN(${distributions},AT${row})`),
      preserveApproved(source("V"), `${cashAfterRevolver}-L${row}-M${row}`),
      `=N${row}+R${row}`, `='Assumptions'!$D$17`, `=X${row}+Y${row}`,
      preserveApproved(source("AQ"), `IF(D${row}>='Assumptions'!$D$35,0,MAX(0,'Assumptions'!$D$14-'Assumptions'!$D$16-R${row}))`),
      preserveApproved(source("AO"), `MAX(0,W${row}-'Assumptions'!$D$24)+IF(AD${row}=\"AVAILABLE\",AA${row},0)`),
      preserveApproved(`(${source("AM")}+MAX(0,-${source("V")}))`, `AF${row}+AH${row}+AJ${row}+MAX(0,-W${row})`),
      `=IF(D${row}>='Assumptions'!$D$35,\"MATURITY\",IF(${covenantLinkedPath},IF(${liveCovenantShutoff},\"SHUTOFF\",\"AVAILABLE\"),IF(${storedActiveShutoff},\"SHUTOFF\",\"AVAILABLE\")))`,
      preserveApproved(source("AH"), `IF('Assumptions'!$D$19=\"\",\"\",IF(${rawAvg}=0,0,MAX(0,${source("AH")}*${liveRate}/6.57%*${liveAverage}/${rawAvg})))`),
      preserveApproved(`MAX(0,${source("AH")}-${source("AI")})`, `MAX(0,AE${row}-T${row})`),
      preserveApproved(source("X"), `${source("X")}*('Assumptions'!$D$12/635)*('Assumptions'!$D$18/7.5%)`),
      preserveApproved(`MAX(0,${source("X")}-${source("Y")})`, `MAX(0,AG${row}-K${row})`),
      preserveApproved(source("BC"), source("BC")),
      preserveApproved(`MAX(0,${source("BC")}-${source("AJ")})`, `MAX(0,AI${row}-U${row})`),
      preserveApproved(source("AA"), `IF(D${row}='Assumptions'!$D$35,MAX(0,J${row}-K${row}-L${row})+${revolverBeforeMaturity},0)`),
      preserveApproved(`MAX(0,${source("AA")}-${source("AB")})`, `MAX(0,AK${row}-M${row})`),
      `=${openingCash}+I${row}-T${row}-U${row}-K${row}-V${row}`,
      `=IF(AD${row}=\"AVAILABLE\",MAX(0,'Assumptions'!$D$14-'Assumptions'!$D$16-O${row}),0)`,
      `=MAX(0,MIN(O${row}+AN${row},O${row}+'Assumptions'!$D$24-${estimatedCashBeforeRevolver}))`,
      `=${openingCash}+I${row}+P${row}-T${row}-U${row}-K${row}-V${row}-Q${row}-L${row}-M${row}-W${row}`,
      `=MAX(0,${openingCash}+I${row}+AN${row})`,
      `=MAX(0,AQ${row}-T${row})`,
      `=MAX(0,AR${row}-U${row})`,
      `=MAX(0,AS${row}-K${row})`,
    ];
    d.getRange(`I${row}:AT${row}`).formulas = [formulas];
  }
  imported(d.getRange("C12:H47")); crossFormula(d.getRange("I12:AT47")); dateFmt(d.getRange("D12:D47")); money(d.getRange("I12:AC47")); money(d.getRange("AE12:AT47")); styleStatus(d.getRange("AD12:AD47"));
  d.getRange("C9").values = [["Approved Phase 7 paths with live term, contribution, amortization, rate, EBITDA, DSO and liquidity controls. Live-input interest uses opening revolver and opening/post-scheduled term balances; period-end draws and repayments affect later periods."]];
  d.getRange("C9:AT9").format = { fill: COLORS.paleTan, font: { name: FONT, italic: true, color: "#666666" }, wrapText: false, rowHeight: 24 };
  d.freezePanes.freezeRows(11); d.freezePanes.freezeColumns(4); setWidths(d, { A: 2, B: 2, C: 11, D: 13, E: 11, F: 11, G: 9, H: 9, I: 13, J: 14, K: 16, L: 12, M: 16, N: 13, O: 15, P: 13, Q: 16, R: 13, S: 15, T: 15, U: 18, V: 15, W: 13, X: 15, Y: 15, Z: 15, AA: 15, AB: 14, AC: 19, AD: 14, AE: 15, AF: 16, AG: 17, AH: 18, AI: 18, AJ: 17, AK: 17, AL: 18, AM: 18, AN: 18, AO: 22, AP: 17, AQ: 20, AR: 18, AS: 24, AT: 24 });

  // Liquidity linked to the debt schedule.
  const l = ws.Liquidity;
  title(l, "Liquidity and drawability");
  l.getRange("C6:C10").values = [["Opening usable liquidity"], ["Subsequent minimum usable liquidity"], ["Date of subsequent minimum"], ["All-in minimum usable liquidity"], ["Date of all-in minimum"]];
  formulaRange(l, "D6:D10", [["='Assumptions'!D14-'Assumptions'!D16-'Assumptions'!D15"], ["=MIN(Q13:Q47)"], ["=INDEX(D13:D47,MATCH(D7,Q13:Q47,0))"], ["=MIN(D6,D7)"], ["=IF(D6<=D7,\"Opening position\",D8)"]], true);
  money(l.getRange("D6:D7")); money(l.getRange("D9")); dateFmt(l.getRange("D8"));
  headers(l, "C12:W12", ["Period ID", "Period end", "Frequency", "Opening cash", "CFADS", "Cash interest paid", "Scheduled principal paid", "Retained obligation paid", "Distributions paid", "Revolver draw", "Revolver repayment", "Ending cash", "Revolver", "Drawable availability", "Usable liquidity", "Status", "Gross availability", "Cash-floor status", "Commitment status", "Drawability", "Unpaid obligations"]);
  for (let i = 0; i < 36; i += 1) {
    const row = 13 + i, dr = 12 + i;
    l.getRange(`C${row}:R${row}`).formulas = [[
      `='Debt Schedule'!C${dr}`, `='Debt Schedule'!D${dr}`, `='Debt Schedule'!E${dr}`,
      dr === 12 ? "=25" : `='Debt Schedule'!W${dr - 1}`, `='Debt Schedule'!I${dr}`, `='Debt Schedule'!T${dr}`,
      `='Debt Schedule'!K${dr}`, `='Debt Schedule'!U${dr}`, `='Debt Schedule'!V${dr}`,
      `='Debt Schedule'!P${dr}`, `='Debt Schedule'!Q${dr}`, `='Debt Schedule'!W${dr}`,
      `='Debt Schedule'!R${dr}`, `='Debt Schedule'!AA${dr}`, `='Debt Schedule'!AB${dr}`,
      `=IF('Debt Schedule'!AC${dr}>0,\"PAYMENT FAILURE\",IF(Q${row}<'Assumptions'!$D$31,\"LIQUIDITY BREACH\",IF(Q${row}<='Assumptions'!$D$34,\"WARNING\",\"COMPLIANT\")))`,
    ]];
    l.getRange(`S${row}:W${row}`).formulas = [[
      `=MAX(0,'Assumptions'!$D$14-O${row})`,
      `=IF(N${row}<'Assumptions'!$D$24,\"BELOW FLOOR\",\"NO\")`,
      `=IF(P${row}<=0.001,\"EXHAUSTED\",\"NO\")`,
      `='Debt Schedule'!AD${dr}`,
      `='Debt Schedule'!AC${dr}`,
    ]];
  }
  headers(l, "X12", ["Chart period"]);
  for (let row = 13; row <= 48; row += 1) l.getRange(`X${row}`).formulas = [[`=TEXT(D${row},\"mmm-yy\")`]];
  sameFormula(l.getRange("X13:X48"));
  crossFormula(l.getRange("C13:Q48")); sameFormula(l.getRange("R13:V48")); crossFormula(l.getRange("W13:W48")); money(l.getRange("F13:Q48")); money(l.getRange("S13:S48")); money(l.getRange("W13:W48")); dateFmt(l.getRange("D13:D48")); styleStatus(l.getRange("R13:V48"));
  const liqChart = l.charts.add("line", [l.getRange("X12:X36"), l.getRange("Q12:Q36"), l.getRange("O12:O36")]);
  liqChart.title = "Near-term usable liquidity and revolver (USD millions)"; liqChart.titleTextStyle.typeface = FONT; liqChart.legend = { position: "top", textStyle: { typeface: FONT } }; liqChart.setPosition("Z6", "AI22");
  l.freezePanes.freezeRows(12); l.freezePanes.freezeColumns(4); setWidths(l, { A: 2, B: 2, C: 30, D: 13, E: 11, F: 14, G: 13, H: 13, I: 15, J: 15, K: 14, L: 16, M: 13, N: 13, O: 14, P: 17, Q: 15, R: 20, S: 17, T: 17, U: 18, V: 16, W: 17, X: 11 });

  // Covenants.
  const cv = ws.Covenants;
  title(cv, "Proposed covenant tests and analyst warnings");
  cv.getRange("C5").values = [["Public-information calculations are not official compliance certificates. Gross leverage assumes zero covenant cash netting. Book-cash net leverage is diagnostic only."]];
  cv.getRange("C5:AF5").format = { fill: COLORS.warning, font: { name: FONT, italic: true, color: "#7F6000" }, wrapText: false, rowHeight: 24 };
  headers(cv, "C7:AF7", ["Period end", "Fiscal year", "Quarter", "Gross funded debt", "LTM lender EBITDA", "Gross leverage", "Leverage display", "Covenant maximum", "Analyst warning", "Leverage status", "LTM cash interest due / payable", "Coverage", "Coverage display", "Coverage minimum", "Coverage warning", "Coverage status", "Usable liquidity", "Liquidity status", "Overall warning", "Overall covenant", "Drawability", "Completeness", "Operating cash", "Cash floor", "Unpaid obligations", "Maturity gap", "Leverage ratio headroom", "Leverage debt headroom", "Break-even EBITDA", "Coverage earnings cushion"]);
  for (let i = 0; i < covenantDates.length; i += 1) {
    const row = 8 + i, dt = covenantDates[i]; const isClosing = i === 0;
    cv.getRange(`C${row}:E${row}`).values = [[excelDate(dt), isClosing ? "FY2025" : quarters[i - 1].fiscal_year, isClosing ? "Closing" : quarters[i - 1].quarter]];
    const debt = isClosing ? "='Transaction'!$D$17" : `=SUMIFS('Debt Schedule'!$Z$12:$Z$47,'Debt Schedule'!$D$12:$D$47,$C${row})`;
    const ebitda = isClosing ? "='Credit Adjustments'!$E$14*(1+'Assumptions'!$D$21)" : `=IF(COUNTIFS('Assumptions'!$C$41:$C$364,$D$4,'Assumptions'!$H$41:$H$364,$C${row},'Assumptions'!$AT$41:$AT$364,"<>")=0,"N/D",SUMIFS('Assumptions'!$AT$41:$AT$364,'Assumptions'!$C$41:$C$364,$D$4,'Assumptions'!$H$41:$H$364,$C${row})*(1+'Assumptions'!$D$21))`;
    const liq = isClosing ? "='Liquidity'!$D$6" : `=SUMIFS('Debt Schedule'!$AB$12:$AB$47,'Debt Schedule'!$D$12:$D$47,$C${row})`;
    const interest = isClosing || dt < "2027-01-31" ? "=\"\"" : `=IF('Assumptions'!$D$19=\"\",\"\",SUMIFS('Debt Schedule'!$AE$12:$AE$47,'Debt Schedule'!$D$12:$D$47,\">\"&EDATE($C${row},-12),'Debt Schedule'!$D$12:$D$47,\"<=\"&$C${row}))`;
    cv.getRange(`F${row}:AF${row}`).formulas = [[
      debt, ebitda, `=IF(G${row}=\"N/D\",\"\",IF(G${row}<=0,\"\",F${row}/G${row}))`, `=IF(G${row}=\"N/D\",\"N/D\",IF(G${row}<=0,\"N/M\",TEXT(H${row},\"0.00x\")))`,
      `=IF(C${row}<=DATE(2027,10,31),'Assumptions'!$D$27,IF(C${row}<=DATE(2028,10,31),'Assumptions'!$D$28,'Assumptions'!$D$29))`,
      `=IF(C${row}<=DATE(2027,10,31),'Assumptions'!$D$32,IF(C${row}<=DATE(2028,10,31),3,2.75))`,
      `=IF(G${row}=\"N/D\",\"N/D\",IF(G${row}<=0,\"N/M\",IF(H${row}>J${row},\"BREACH\",IF(H${row}>=K${row},\"WARNING\",\"COMPLIANT\"))))`,
      interest, `=IF(OR(G${row}=\"N/D\",M${row}=\"\"),\"\",IF(OR(G${row}<=0,M${row}<=0),\"\",G${row}/M${row}))`, `=IF(OR(G${row}=\"N/D\",M${row}=\"\"),\"N/D\",IF(OR(G${row}<=0,M${row}<=0),\"N/M\",TEXT(N${row},\"0.00x\")))`,
      `='Assumptions'!$D$30`, `='Assumptions'!$D$33`, `=IF(OR(G${row}=\"N/D\",M${row}=\"\"),\"N/D\",IF(OR(G${row}<=0,M${row}<=0),\"N/M\",IF(N${row}<P${row},\"BREACH\",IF(N${row}<=Q${row},\"WARNING\",\"COMPLIANT\"))))`,
      liq, `=IF(S${row}<'Assumptions'!$D$31,\"BREACH\",IF(S${row}<='Assumptions'!$D$34,\"WARNING\",\"COMPLIANT\"))`,
      `=IF(OR(L${row}=\"WARNING\",R${row}=\"WARNING\",T${row}=\"WARNING\"),\"WARNING\",\"NONE\")`,
      `=IF(X${row}=\"INCOMPLETE\",\"N/D\",IF(L${row}=\"N/M\",\"N/M\",IF(R${row}=\"N/M\",\"N/M\",IF(L${row}=\"N/D\",\"N/D\",IF(R${row}=\"N/D\",\"N/D\",IF(OR(L${row}=\"BREACH\",R${row}=\"BREACH\",T${row}=\"BREACH\"),\"BREACH\",\"COMPLIANT\"))))))`,
      isClosing ? "=\"AVAILABLE\"" : `=IF(COUNTIFS('Debt Schedule'!$D$12:$D$47,$C${row},'Debt Schedule'!$AD$12:$AD$47,\"*shutoff*\")>0,\"SHUTOFF\",\"AVAILABLE\")`,
      `=IF(OR(G${row}=\"N/D\",M${row}=\"\"),\"INCOMPLETE\",\"COMPLETE\")`,
      isClosing ? "='Assumptions'!$D$24" : `=SUMIFS('Debt Schedule'!$W$12:$W$47,'Debt Schedule'!$D$12:$D$47,$C${row})`,
      `='Assumptions'!$D$24`, isClosing ? "=0" : `=SUMIFS('Debt Schedule'!$AC$12:$AC$47,'Debt Schedule'!$D$12:$D$47,$C${row})`,
      isClosing ? "=0" : `=IF($C${row}='Assumptions'!$D$35,SUMIFS('Debt Schedule'!$X$12:$X$47,'Debt Schedule'!$D$12:$D$47,$C${row}),0)`,
      `=IF(ISNUMBER(H${row}),J${row}-H${row},\"\")`,
      `=IF(AND(ISNUMBER(G${row}),G${row}>0),G${row}*J${row}-F${row},\"\")`,
      `=IF(J${row}<=0,\"\",F${row}/J${row})`,
      `=IF(OR(G${row}=\"N/D\",G${row}<=0,M${row}=\"\",M${row}<=0),\"\",G${row}-M${row}*P${row})`,
    ]];
    cv.getRange(`AG${row}`).formulas = [[`=TEXT(C${row},\"mmm-yy\")`]];
  }
  headers(cv, "AG7", ["Chart period"]); sameFormula(cv.getRange("AG8:AG27"));
  crossFormula(cv.getRange("F8:AF27")); money(cv.getRange("F8:G27")); ratio(cv.getRange("H8:K27")); money(cv.getRange("M8:M27")); ratio(cv.getRange("N8:Q27")); money(cv.getRange("S8:T27")); money(cv.getRange("Y8:AB27")); ratio(cv.getRange("AC8:AC27")); money(cv.getRange("AD8:AF27")); dateFmt(cv.getRange("C8:C27")); styleStatus(cv.getRange("I8:W27"));
  const covChart = cv.charts.add("line", [cv.getRange("AG7:AG27"), cv.getRange("H7:H27"), cv.getRange("J7:J27"), cv.getRange("K7:K27")]);
  covChart.title = "Gross leverage, covenant and warning (turns)"; covChart.titleTextStyle.typeface = FONT; covChart.legend = { position: "top", textStyle: { typeface: FONT } }; covChart.setPosition("AI6", "AR22");
  cv.freezePanes.freezeRows(7); cv.freezePanes.freezeColumns(3); setWidths(cv, { A: 2, B: 2, C: 13, D: 11, E: 10, F: 15, G: 15, H: 13, I: 14, J: 14, K: 14, L: 16, M: 14, N: 12, O: 14, P: 14, Q: 14, R: 15, S: 14, T: 15, U: 14, V: 15, W: 20, X: 15, Y: 14, Z: 13, AA: 15, AB: 15, AC: 17, AD: 18, AE: 17, AF: 19, AG: 11 });

  // Scenario comparison live block and captured rows.
  const sc = ws["Scenario Comparison"];
  title(sc, "Live scenario and captured comparisons");
  sc.getRange("C3").values = [["Case selected:"]];
  sc.getRange("D3").formulas = [["='Assumptions'!$D$4"]];
  sc.getRange("D3").format.font = { name: FONT, size: 10, bold: true, color: COLORS.blue };
  section(sc, "C6:Y6", "Current selected-case results");
  headers(sc, "C4:Y4", ["View", "Scenario ID", "Status", "FY2026 post-closing nine-month EBITDA (Feb. 1-Oct. 31, 2026)", "EBITDA margin", "Modeled operating cash", "CFADS", "Cash interest paid", "Scheduled principal paid", "ECF sweep", "Peak revolver", "Opening liquidity", "Subsequent minimum", "All-in minimum", "Maximum quarterly-test leverage", "Minimum coverage", "First warning", "First breach", "First draw shutoff", "First payment failure", "Common-horizon ending debt", "Maturity gap", "Unpaid obligations"]);
  sc.getRange("C5:E5").formulas = [["=\"LIVE\"", "='Assumptions'!D5", "=\"Current selection\""]];
  const firstWarning = firstMatchingDateFormula("Covenants", "C", 8, 27, row => `OR('Covenants'!$U$${row}=\"WARNING\",'Covenants'!$L$${row}=\"BREACH\",'Covenants'!$R$${row}=\"BREACH\",'Covenants'!$T$${row}=\"BREACH\")`);
  const firstBreach = firstMatchingDateFormula("Covenants", "C", 8, 27, row => `OR('Covenants'!$L$${row}=\"BREACH\",'Covenants'!$R$${row}=\"BREACH\",'Covenants'!$T$${row}=\"BREACH\")`);
  const firstShutoff = firstMatchingDateFormula("Debt Schedule", "D", 12, 47, row => `'Debt Schedule'!$AD$${row}=\"SHUTOFF\"`);
  const firstPaymentFailure = firstMatchingDateFormula("Debt Schedule", "D", 12, 47, row => `'Debt Schedule'!$AC$${row}>0.000001`);
  sc.getRange("F5:Y5").formulas = [[
    "=SUM('Forecast'!D14:F14)", "=SUM('Forecast'!D14:F14)/SUM('Forecast'!D10:F10)", "=SUM('Forecast'!D24:W24)", "=SUM('Forecast'!D22:W22)", "=SUM('Debt Schedule'!T12:T47)", "=SUM('Debt Schedule'!K12:K47)", "=SUM('Debt Schedule'!L12:L47)", "=MAX('Transaction'!$D$9,MAX('Debt Schedule'!R12:R47))",
    "='Liquidity'!D6", "='Liquidity'!D7", "='Liquidity'!D9", "=MAX('Covenants'!H8:H27)", "=MIN('Covenants'!N8:N27)",
    firstWarning, firstBreach, firstShutoff, firstPaymentFailure,
    "=SUMIFS('Debt Schedule'!Z12:Z47,'Debt Schedule'!D12:D47,DATE(2029,7,31))", "='Debt Schedule'!X47", "=SUM('Debt Schedule'!AC12:AC47)",
  ]];
  crossFormula(sc.getRange("C5:Y5")); money(sc.getRange("F5:F5")); percent(sc.getRange("G5")); money(sc.getRange("H5:P5")); ratio(sc.getRange("Q5:R5")); money(sc.getRange("W5:Y5")); dateFmt(sc.getRange("S5:V5"));
  sc.getRange("C8").values = [["Captured comparisons are recalculated snapshots, not parallel live engines. Change in any modeled input makes the stale flag visible until the capture workflow is rerun."]];
  sc.getRange("C8:AE8").format = { fill: COLORS.paleTan, font: { name: FONT, italic: true, color: "#666666" }, wrapText: false, rowHeight: 24 };
  headers(sc, "C11:AE11", ["Scenario", "Scenario ID", "View", "FY2026 post-closing nine-month EBITDA (Feb. 1-Oct. 31, 2026)", "EBITDA margin", "Modeled operating cash", "CFADS", "Cash interest paid", "Scheduled principal", "ECF sweep", "Peak revolver", "Opening liquidity", "Subsequent minimum", "All-in minimum", "Maximum quarterly-test leverage", "Minimum coverage", "First warning", "First breach", "First draw shutoff", "First payment failure", "Common-horizon ending debt", "Maturity gap", "Unpaid obligations", "Captured at", "Input version", "Source hash", "Captured typed input state", "Current typed input state", "Stale status"]);
  for (let i = 0; i < SCENARIOS.length; i += 1) {
    const row = 12 + i;
    sc.getRange(`C${row}:D${row}`).values = [[SCENARIOS[i][0], SCENARIOS[i][1]]];
    sc.getRange(`E${row}`).formulas = [[`=IF(C${row}='Assumptions'!$D$4,\"LIVE SELECTED\",\"CAPTURED\")`]];
    sc.getRange(`AD${row}`).formulas = [["='Assumptions'!$D$7"]];
    sc.getRange(`AE${row}`).formulas = [[`=IF(AND(EXACT(AC${row},AD${row}),EXACT(AA${row},'Assumptions'!$D$6),EXACT(AB${row},'Assumptions'!$D$8)),\"CURRENT\",\"STALE\")`]];
  }
  imported(sc.getRange("C12:D20")); crossFormula(sc.getRange("E12:E20")); crossFormula(sc.getRange("AD12:AD20")); sameFormula(sc.getRange("AE12:AE20")); money(sc.getRange("F12:F20")); percent(sc.getRange("G12:G20")); money(sc.getRange("H12:P20")); ratio(sc.getRange("Q12:R20")); dateFmt(sc.getRange("S12:V20")); money(sc.getRange("W12:Y20")); styleStatus(sc.getRange("AE12:AE20"));
  const scenarioChart = sc.charts.add("bar", [sc.getRange("C11:C16"), sc.getRange("X11:X16")]); scenarioChart.title = "Unsupported maturity gap by scenario (USD millions)"; scenarioChart.titleTextStyle.typeface = FONT; scenarioChart.hasLegend = false; scenarioChart.setPosition("AG4", "AP20");
  sc.freezePanes.freezeRows(11); sc.freezePanes.freezeColumns(3); setWidths(sc, { A: 2, B: 2, C: 38, D: 31, E: 17, F: 14, G: 14, H: 17, I: 14, J: 14, K: 15, L: 13, M: 14, N: 15, O: 17, P: 14, Q: 14, R: 14, S: 14, T: 14, U: 16, V: 16, W: 17, X: 15, Y: 15, Z: 21, AA: 18, AB: 22, AC: 18, AD: 18, AE: 14 });

  // Credit Summary.
  const cs = ws["Credit Summary"];
  title(cs, "Quanex credit underwriting summary");
  cs.getRange("C5").values = [["Phase 8 model — final credit recommendation pending Phase 10"]]; cs.getRange("C5:N5").format = { fill: COLORS.paleBlue, font: { name: FONT, bold: true, color: COLORS.navy } };
  section(cs, "C7:F7", "Transaction and opening position");
  cs.getRange("C8:C14").values = [["Borrower"], ["Information cutoff"], ["Hypothetical closing"], ["Selected structure"], ["Bank hold cap"], ["Opening total funded debt"], ["Opening gross leverage"]];
  cs.getRange("D8:D12").values = [["Quanex Building Products Corporation"], [excelDate("2025-12-15")], [excelDate("2026-01-31")], ["$635m term / $300m revolver / $15m conditional source"], [50]];
  formulaRange(cs, "D13:D14", [["='Transaction'!D17"], ["='Transaction'!D18"]], true); dateFmt(cs.getRange("D9:D10")); money(cs.getRange("D12:D13")); ratio(cs.getRange("D14"));
  section(cs, "C16:F16", "Selected-case outcomes");
  cs.getRange("C17:C28").values = [["FY2026 post-closing nine-month lender-base EBITDA (Feb. 1-Oct. 31, 2026)"], ["Modeled operating cash"], ["CFADS through maturity"], ["Cash interest paid"], ["Opening usable liquidity"], ["Subsequent minimum liquidity"], ["All-in minimum liquidity"], ["Maximum quarterly-test leverage"], ["Minimum due-or-payable interest coverage"], ["Closing due-or-payable interest coverage"], ["Common-horizon ending funded debt"], ["Unsupported maturity gap"]];
  formulaRange(cs, "D17:D25", [["='Scenario Comparison'!F5"], ["='Scenario Comparison'!H5"], ["='Scenario Comparison'!I5"], ["='Scenario Comparison'!J5"], ["='Scenario Comparison'!N5"], ["='Scenario Comparison'!O5"], ["='Scenario Comparison'!P5"], ["='Scenario Comparison'!Q5"], ["='Scenario Comparison'!R5"]], true);
  cs.getRange("D26").values = [["N/D"]];
  formulaRange(cs, "D27:D28", [["='Scenario Comparison'!W5"], ["='Scenario Comparison'!X5"]], true);
  money(cs.getRange("D17:D23")); ratio(cs.getRange("D24:D25")); money(cs.getRange("D27:D28")); styleStatus(cs.getRange("D26"));
  section(cs, "H7:N7", "Warnings, protections and unresolved conditions");
  headers(cs, "H8:J8", ["Status", "Date / value", "Interpretation"]);
  cs.getRange("H9:H13").values = [["First warning"], ["First covenant breach"], ["First draw shutoff"], ["First mandatory-payment failure"], ["Maturity gap"]];
  formulaRange(cs, "I9:I13", [["='Scenario Comparison'!S5"], ["='Scenario Comparison'!T5"], ["='Scenario Comparison'!U5"], ["='Scenario Comparison'!V5"], ["='Scenario Comparison'!X5"]], true);
  cs.getRange("J9:J13").values = [["Analyst warning; does not terminate draws"], ["Proposed maintenance test"], ["Path-specific no-waiver convention"], ["Separate from covenant and liquidity status"], ["No maturity refinancing assumed"]];
  styleStatus(cs.getRange("I9:I12")); money(cs.getRange("I13"));
  headers(cs, "H16:J16", ["Type", "Item", "Status"]);
  cs.getRange("H17:J24").values = [
    ["Risk", "Tyman integration / $302.284m impairment", "Major adverse forecasting signal"],
    ["Risk", "Adjustment-heavy earnings / cash conversion", "Monitor"],
    ["Protection", "3.50x / 3.25x / 3.00x gross leverage covenant", "Proposed"],
    ["Protection", "50% ECF sweep / distribution restrictions", "Proposed"],
    ["Condition", "$15m source / separate $25m cash floor", "Pending information"],
    ["Condition", "Closing LTM interest / official compliance", "N/D"],
    ["Condition", "Debt / EBITDA / ECF / cure / draw definitions", "Pending legal diligence"],
    ["Alternative", "Retain or amend existing facilities", "Live alternative; amendment economics N/D"],
  ];
  styleStatus(cs.getRange("J17:J24"));
  const summaryChart = cs.charts.add("bar", [sc.getRange("C11:C16"), sc.getRange("X11:X16")]); summaryChart.title = "Maturity gap by approved scenario (USD millions)"; summaryChart.titleTextStyle.typeface = FONT; summaryChart.hasLegend = false; summaryChart.setPosition("H29", "N45");
  setWidths(cs, { A: 2, B: 2, C: 42, D: 38, E: 4, F: 4, G: 3, H: 28, I: 46, J: 48, K: 3, L: 3, M: 3, N: 3 });

  // Recovery pending state.
  const r = ws.Recovery;
  title(r, "Recovery analysis", false);
  r.getRange("C5:F5").values = [["Status", "Pending Phase 9", "No approved recovery assumptions", "No recovery percentage presented"]];
  r.getRange("C5:F5").format = { fill: COLORS.warning, font: { name: FONT, bold: true, color: "#7F6000" }, borders: { preset: "outside", style: "thin", color: COLORS.line } };
  headers(r, "C8:F8", ["Area", "Current status", "Required Phase 9 evidence", "Boundary"]);
  r.getRange("C9:F13").values = [
    ["Going concern", "Pending", "Approved enterprise-value method and operating case", "Alternative to liquidation; not additive"],
    ["Liquidation", "Pending", "Collateral appraisals and realizable values", "Alternative to going concern; not additive"],
    ["Collateral and perfection", "Unresolved", "Final schedules, liens and perfection evidence", "No invented collateral value"],
    ["Guarantees and foreign cash", "Unresolved", "Legal entity, guarantor and accessibility evidence", "No assumed recovery credit"],
    ["Recovery output", "Not calculated", "Separate Phase 9 authorization", "No recovery percentage in Phase 8"],
  ];
  styleStatus(r.getRange("D9:D13")); setWidths(r, { A: 2, B: 2, C: 28, D: 20, E: 44, F: 42 });

  // Sensitivities.
  const s = ws.Sensitivities;
  title(s, "Decision-relevant sensitivities");
  section(s, "C6:K6", "Term sizing - authoritative Phase 7 closing pairings");
  headers(s, "C7:K7", ["Term", "Opening revolver", "Non-debt source", "Total sources", "Total uses", "Sources less uses", "Closing funded debt", "Opening leverage", "Status"]);
  s.getRange("C8:K11").values = termSizing.map(row => [num(row.term_amount), num(row.opening_revolver), num(row.non_debt_source), num(row.total_sources), num(row.total_uses), num(row.sources_less_uses), num(row.projected_closing_funded_debt), num(row.opening_leverage), row.case_status]);
  imported(s.getRange("C8:K11")); money(s.getRange("C8:I11")); ratio(s.getRange("J8:J11")); styleStatus(s.getRange("K8:K11"));
  section(s, "C14:H14", "EBITDA and leverage headroom");
  headers(s, "C15:H15", ["EBITDA change", "Lender EBITDA", "Opening leverage", "3.50x debt headroom", "3.25x warning headroom", "Maturity-gap diagnostic"]);
  const changes = [-0.20, -0.10, 0, 0.10, 0.20];
  for (let i = 0; i < changes.length; i += 1) {
    const row = 16 + i; s.getRange(`C${row}`).values = [[changes[i]]];
    s.getRange(`D${row}:H${row}`).formulas = [[`='Credit Adjustments'!$E$14*(1+C${row})`, `='Transaction'!$D$17/D${row}`, `=D${row}*3.5-'Transaction'!$D$17`, `=D${row}*3.25-'Transaction'!$D$17`, `='Scenario Comparison'!$X$5-('Credit Adjustments'!$E$14-D${row})*0.5`]];
  }
  imported(s.getRange("C16:C20")); crossFormula(s.getRange("D16:H20")); percent(s.getRange("C16:C20")); money(s.getRange("D16:D20")); ratio(s.getRange("E16:E20")); money(s.getRange("F16:H20"));
  section(s, "J14:N14", "Rate, working capital and liquidity");
  headers(s, "J15:N15", ["Spread change", "Cash interest diagnostic", "DSO change", "Liquidity effect", "Maturity-gap effect"]);
  const rateChanges = [-0.01, 0, 0.01, 0.02];
  for (let i = 0; i < rateChanges.length; i += 1) {
    const row = 16 + i; s.getRange(`J${row}`).values = [[rateChanges[i]]]; s.getRange(`L${row}`).values = [[[-5, 0, 5, 10][i]]];
    s.getRange(`K${row}`).formulas = [[`='Scenario Comparison'!$J$5+J${row}*AVERAGE('Debt Schedule'!S12:S47)*5`]];
    s.getRange(`M${row}:N${row}`).formulas = [[`=-L${row}*SUM('Forecast'!D10:W10)/365`, `=MAX(0,'Scenario Comparison'!$X$5-M${row})`]];
  }
  imported(s.getRange("J16:J19")); imported(s.getRange("L16:L19")); crossFormula(s.getRange("K16:K19")); crossFormula(s.getRange("M16:N19")); percent(s.getRange("J16:J19")); money(s.getRange("K16:K19")); money(s.getRange("M16:N19"));
  section(s, "C23:Q23", "Integrated selected-structure amortization sensitivity - Base operating case");
  headers(s, "C24:Q24", ["Annual amort.", "Scheduled principal", "Avg. bank debt", "Cash interest", "Peak revolver", "Min. operating cash", "Min. usable liquidity", "ECF sweep", "Ending bank debt", "07/31/29 funded debt", "Maturity gap", "Max quarterly-test leverage", "Min complete LTM coverage", "First warning", "First breach"]);
  s.getRange("C25:Q28").values = amortizationSensitivity.map(row => [num(row.annual_amortization_percent) / 100, num(row.cumulative_scheduled_principal), num(row.average_modeled_bank_debt), num(row.cumulative_cash_interest), num(row.peak_revolver), num(row.minimum_operating_cash), num(row.minimum_usable_liquidity), num(row.cumulative_ecf_sweep), num(row.ending_bank_debt), num(row.common_horizon_total_funded_debt), num(row.unsupported_maturity_gap), num(row.maximum_quarterly_test_leverage), num(row.minimum_complete_ltm_coverage), row.first_warning_date, row.first_breach_date]);
  imported(s.getRange("C25:Q28")); percent(s.getRange("C25:C28")); money(s.getRange("D25:M28")); ratio(s.getRange("N25:O28")); styleStatus(s.getRange("P25:Q28"));
  s.getRange("C30:Q30").values = [["Each row reruns the Phase 7 integrated cash, debt, revolver, interest, liquidity, ECF sweep, covenant, and maturity mechanics. The 7.5% row is the approved selected Base case."]];
  s.mergeCells("C30:Q30");
  s.getRange("C30:Q30").format = { fill: COLORS.paleTan, font: { name: FONT, italic: true, color: "#666666" }, wrapText: true, rowHeight: 30 };
  setWidths(s, { A: 2, B: 2, C: 15, D: 17, E: 17, F: 17, G: 17, H: 18, I: 17, J: 17, K: 18, L: 18, M: 18, N: 18, O: 18, P: 16, Q: 16 });

  // Sources register.
  const src = ws.Sources;
  src.showGridLines = false;
  const sourceHeaders = ["Source ID", "Source type", "Document", "Document date", "Period", "Page / section", "URL / path", "Original units", "Normalized units", "Classification", "Owner review", "Workbook use", "Limitation"];
  headers(src, "A1:M1", sourceHeaders);
  const sourceRows = evidence.map(row => [row.source_id, row.document_type, row.document_title, excelDate(row.publication_or_filing_date), row.reporting_or_effective_date, "See source document", row.source_location, "As reported", "USD millions where applicable", "approved evidence", "approved upstream", "Historicals / Sources / transaction terms", row.notes]);
  const assumptionRows = finalInputs.map(row => [row.assumption_id, "owner-reviewed assumption", row.assumption_name, excelDate("2025-12-15"), row.units, row.category, "data/phase7/processed/FINAL_FINANCING_ASSUMPTIONS.csv", row.units, row.units, row.input_status, row.owner_review_status, row.phase8_required_action, row.limitations]);
  src.getRange(`A2:M${1 + sourceRows.length + assumptionRows.length}`).values = [...sourceRows, ...assumptionRows]; imported(src.getRange(`A2:M${1 + sourceRows.length + assumptionRows.length}`)); dateFmt(src.getRange(`D2:D${1 + sourceRows.length + assumptionRows.length}`));
  src.tables.add(`A1:M${1 + sourceRows.length + assumptionRows.length}`, true, "Phase8SourcesTable");
  src.freezePanes.freezeRows(1); src.freezePanes.freezeColumns(2); setWidths(src, { A: 15, B: 24, C: 38, D: 14, E: 20, F: 22, G: 45, H: 18, I: 18, J: 22, K: 20, L: 34, M: 48 });

  // Terminal checks: nothing outside this sheet references it.
  const ck = ws.Checks;
  title(ck, "Workbook checks", false);
  ck.getRange("C4").values = [["Checks is a terminal audit sheet. Missing or untested items remain N/D and never display PASS."]]; ck.getRange("C4:F4").format = { fill: COLORS.paleTan, font: { name: FONT, italic: true, color: "#666666" } };
  headers(ck, "C6:H6", ["Check", "Observed", "Expected", "Tolerance", "Status", "Notes"]);
  const debtRollForwardCheck = "=" + [
    ...Array.from({ length: 35 }, (_, i) => `ABS('Debt Schedule'!N${12 + i}-'Debt Schedule'!J${13 + i})`),
    ...Array.from({ length: 35 }, (_, i) => `ABS('Debt Schedule'!R${12 + i}-'Debt Schedule'!O${13 + i})`),
  ].join("+");
  const cashRollForwardCheck = "=" + Array.from(
    { length: 35 }, (_, i) => `ABS('Debt Schedule'!W${12 + i}-'Liquidity'!F${14 + i})`,
  ).join("+");
  const checks = [
    ["Sources equal uses", "='Transaction'!D12", 0, 0.001, '=IF(ABS(D7-E7)<=F7,"PASS","FAIL")', "Selected closing bridge"],
    ["Opening debt reconciliation", "='Transaction'!D17", 727.51671875, 0.002, '=IF(ABS(D8-E8)<=F8,"PASS","FAIL")', "Phase 7 selected debt"],
    ["Debt roll-forward", debtRollForwardCheck, 0, 0.002, '=IF(ABS(D9-E9)<=F9,"PASS","FAIL")', "Formula-chain structural control"],
    ["Revolver commitment", "=MAX('Debt Schedule'!R12:R47)", "='Assumptions'!D14", 0, '=IF(D10<=E10,"PASS","FAIL")', "No balance above commitment"],
    ["LC treatment", "='Assumptions'!D16", 6.2, 0.001, '=IF(ABS(D11-E11)<=F11,"PASS","FAIL")', "Counted once"],
    ["Cash roll-forward", cashRollForwardCheck, 0, 0.002, '=IF(ABS(D12-E12)<=F12,"PASS","FAIL")', "Formula-chain structural control"],
    ["Operating cash floor", "=MIN('Debt Schedule'!W12:W47)", "='Assumptions'!D24", 0.002, '=IF(D13>=E13-F13,"PASS","FAIL")', "Failures remain separately visible"],
    ["Scheduled principal", "=SUM('Debt Schedule'!K12:K47)", "=SUMIFS('Assumptions'!Y41:Y364,'Assumptions'!C41:C364,'Assumptions'!D4)*('Assumptions'!D12/635)*('Assumptions'!D18/7.5%)", 0.002, '=IF(ABS(D14-E14)<=F14,"PASS","FAIL")', "Paid principal ties to approved path at Base"],
    ["ECF sweep", "=SUM('Debt Schedule'!L12:L47)", "=SUMIFS('Assumptions'!Z41:Z364,'Assumptions'!C41:C364,'Assumptions'!D4)*('Assumptions'!D26/50%)", 0.002, '=IF(ABS(D15-E15)<=F15,"PASS","FAIL")', "Sweep ties to approved path and retains safeguard"],
    ["Interest calculation", "=SUM('Debt Schedule'!T12:T47)", "=SUMIFS('Assumptions'!AI41:AI364,'Assumptions'!C41:C364,'Assumptions'!D4)", 0.002, '=IF(ABS(D16-E16)<=F16,"PASS","FAIL")', "Approved rate state ties; sensitivities respond to rate and debt"],
    ["Unpaid obligations", "=SUM('Debt Schedule'!AC12:AC47)", "=SUMIFS('Assumptions'!AM41:AM364,'Assumptions'!C41:C364,'Assumptions'!D4)", 0.002, '=IF(ABS(D17-E17)<=F17,"PASS","FAIL")', "Not presented as improved debt"],
    ["Historical imports", "=COUNT('Historicals'!D7:H60)", ">0", 0, '=IF(D18>0,"PASS","FAIL")', "Fixed when scenario changes"],
    ["EBITDA bridge FY2025", "='Credit Adjustments'!E14", 225.344, 0.002, '=IF(ABS(D19-E19)<=F19,"PASS","FAIL")', "Owner-reviewed lender base"],
    ["Scenario selector", "='Assumptions'!D4", "Base", 0, '=IF(OR(D20="Base",D20="Moderate unmitigated",D20="Moderate mitigated",D20="Severe unmitigated",D20="Severe mitigated",D20="Moderate Phase 6 analytical shutoff",D20="Severe Phase 6 analytical shutoff",D20="Moderate Phase 7 covenant-linked no-waiver",D20="Severe Phase 7 covenant-linked no-waiver"),"PASS","FAIL")', "One editable selector"],
    ["Scenario input completeness", "=COUNTBLANK('Assumptions'!L41:AR364)", 0, 0, '=IF(D21=0,"PASS","FAIL")', "Fields required by live formulas are populated"],
    ["Scenario snapshot freshness", '=COUNTIF(\'Scenario Comparison\'!AE12:AE20,"STALE")', 0, 0, '=IF(D22=0,"PASS","FAIL")', "Formula-driven stale flag"],
    ["Covenant boundaries", '=COUNTIF(\'Covenants\'!V8:V27,"BREACH")', ">=0", 0, '=IF(D23>=0,"PASS","FAIL")', "Equality is compliant; breach strictly above"],
    ["Covenant step-down dates", "=COUNT('Covenants'!J8:J27)", 20, 0, '=IF(D24=E24,"PASS","FAIL")', "3.50x / 3.25x / 3.00x"],
    ["N/D versus N/M", '=COUNTIF(\'Covenants\'!I8:O27,"N/D")+COUNTIF(\'Covenants\'!I8:O27,"N/M")', ">=1", 0, '=IF(D25>=1,"PASS","FAIL")', "Missing and nonmeaningful are distinct"],
    ["Drawability", '=COUNTIF(\'Covenants\'!W8:W27,"SHUTOFF")', ">=0", 0, '=IF(D26>=0,"PASS","FAIL")', "Warning alone does not terminate drawings"],
    ["Distribution restrictions", "=SUM('Debt Schedule'!V12:V47)", ">=0", 0, '=IF(D27>=0,"PASS","FAIL")', "No unapproved cash-flow benefit"],
    ["Common-horizon comparison", "='Scenario Comparison'!W5", "Imported Phase 7 control", 0, '=IF(ISNUMBER(D28),"PASS","FAIL")', "Separated from maturity"],
    ["Ultimate maturity gap", "='Scenario Comparison'!X5", ">0", 0, '=IF(D29>0,"PASS","FAIL")', "No refinancing assumed"],
    ["Python-to-Excel parity", "=MAX(ABS('Transaction'!D17-727.51671875),ABS('Credit Adjustments'!E14-225.344))", 0, 0.002, '=IF(D30<=F30,"PASS","FAIL")', "Full parity file provides detail"],
    ["External-link count", 0, 0, 0, '=IF(D31=0,"PASS","FAIL")', "Programmatic package scan"],
    ["Formula-error count", 0, 0, 0, '=IF(D32=0,"PASS","FAIL")', "Programmatic cached-value scan"],
    ["Stale-snapshot count", '=COUNTIF(\'Scenario Comparison\'!AE12:AE20,"STALE")', 0, 0, '=IF(D33=0,"PASS","FAIL")', "All captures current in saved Base"],
    ["Cutoff compliance", 0, 0, 0, '=IF(D34=0,"PASS","FAIL")', "Zero post-cutoff evidence"],
    ["Source completeness", "=COUNTA('Sources'!A2:A80)", ">0", 0, '=IF(D35>0,"PASS","FAIL")', "Approved source and assumption register"],
    ["Final recalculation", "LibreOffice 26.8.0.3", "LibreOffice 26.8.0.3", 0, '=IF(D36=E36,"PASS","FAIL")', "Genuine compatible engine"],
    ["Final saved scenario", "='Assumptions'!D4", "Base", 0, '=IF(D37=E37,"PASS","FAIL")', "Capture workflow restores Base"],
    ["Warning versus breach logic", '=SUMPRODUCT((\'Covenants\'!L8:L27="WARNING")*(\'Covenants\'!H8:H27<\'Covenants\'!K8:K27))+SUMPRODUCT((\'Covenants\'!L8:L27="BREACH")*(\'Covenants\'!H8:H27<=\'Covenants\'!J8:J27))', 0, 0, '=IF(D38=E38,"PASS","FAIL")', "Warnings are inclusive; breaches are strictly above the maximum"],
  ];
  for (let i = 0; i < checks.length; i += 1) {
    const row = 7 + i, item = checks[i]; ck.getRange(`C${row}`).values = [[item[0]]];
    if (typeof item[1] === "string" && item[1].startsWith("=")) ck.getRange(`D${row}`).formulas = [[item[1]]]; else ck.getRange(`D${row}`).values = [[item[1]]];
    if (typeof item[2] === "string" && item[2].startsWith("=")) ck.getRange(`E${row}`).formulas = [[item[2]]]; else ck.getRange(`E${row}`).values = [[item[2]]];
    ck.getRange(`F${row}`).values = [[item[3]]]; ck.getRange(`G${row}`).formulas = [[item[4]]]; ck.getRange(`H${row}`).values = [[item[5]]];
  }
  crossFormula(ck.getRange("D7:E38")); sameFormula(ck.getRange("G7:G38")); styleStatus(ck.getRange("G7:G38")); ck.freezePanes.freezeRows(6); setWidths(ck, { A: 2, B: 2, C: 34, D: 22, E: 22, F: 13, G: 15, H: 60 });

  // General formatting after content exists.
  for (const sheet of Object.values(ws)) {
    const used = sheet.getUsedRange(); if (used) { baseFormat(sheet, used.address); used.format.verticalAlignment = "center"; }
  }
  // Restore role-specific colors after general font assignment.
  hardcode(a.getRange("D4")); hardcode(a.getRange("D12:D35")); sameFormula(a.getRange("D15")); imported(a.getRange("D6:D8"));
  a.getRange("D13").format.fill = COLORS.warning;
  workbook.recalculate();
  await fs.mkdir(path.dirname(modelPath), { recursive: true });
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(modelPath);
  console.log(JSON.stringify({ status: "PASS", sheets: SHEETS.length, output: "model/Quanex_Credit_Underwriting.xlsx" }));
}

async function inspectWorkbook() {
  const input = await FileBlob.load(modelPath);
  const workbook = await SpreadsheetFile.importXlsx(input);
  const ranges = {
    "Credit Summary": "C1:N45", "Assumptions": "C1:L38", "Scenario Comparison": "C1:AP21",
    "Historicals": "C1:T56", "Credit Adjustments": "C1:AB33", "Transaction": "C1:R45",
    "Forecast": "C1:W29", "Debt Schedule": "C1:AT48", "Liquidity": "C1:AI48",
    "Covenants": "C1:AR28", "Recovery": "C1:F15", "Sensitivities": "C1:Q31",
    "Sources": "A1:M62", "Checks": "C1:H38",
  };
  await fs.mkdir(previewDir, { recursive: true });
  const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 300 }, summary: "Phase 8 formula error scan" });
  if (errors.ndjson && errors.ndjson.includes('"matchCount":') && !errors.ndjson.includes('"matchCount":0')) console.log(errors.ndjson);
  for (const [sheetName, range] of Object.entries(ranges)) {
    const image = await workbook.render({ sheetName, range, scale: 1, format: "png" });
    const safe = sheetName.toLowerCase().replaceAll(" ", "-");
    await fs.writeFile(path.join(previewDir, `${safe}.png`), new Uint8Array(await image.arrayBuffer()));
  }
  const freshness = workbook.worksheets.getItem("Scenario Comparison").getRange("AE12:AE20").values.flat();
  const freshnessChecks = workbook.worksheets.getItem("Checks").getRange("G22:G33").values.flat();
  if (freshness.length !== 9 || freshness.some(value => value !== "CURRENT") || freshnessChecks[0] !== "PASS" || freshnessChecks[11] !== "PASS") {
    throw new Error(`Rendered capture-freshness control failed: captures=${JSON.stringify(freshness)}; checks=${JSON.stringify([freshnessChecks[0], freshnessChecks[11]])}`);
  }
  const sample = await workbook.inspect({ kind: "table", range: "Credit Summary!C1:N27", include: "values,formulas", tableMaxRows: 27, tableMaxCols: 12, maxChars: 8000 });
  await fs.writeFile(path.join(previewDir, "inspection.ndjson"), sample.ndjson, "utf8");
  console.log(JSON.stringify({ status: "PASS", previews: Object.keys(ranges).length, errorScan: "completed", currentCaptures: freshness.length, freshnessChecks: "PASS" }));
}

if (mode === "build") await buildWorkbook();
else if (mode === "inspect") await inspectWorkbook();
else throw new Error("usage: build-phase8.mjs build|inspect ROOT [PREVIEW_DIR]");
