import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const mode = process.argv[2];
const root = path.resolve(process.argv[3]);
const baselinePath = path.resolve(process.argv[4]);
const previewDir = process.argv[5] ? path.resolve(process.argv[5]) : null;
const modelPath = path.join(root, "model", "Quanex_Credit_Underwriting.xlsx");
const payload = JSON.parse(await fs.readFile(path.join(root, "data", "phase10", "processed", "WORKBOOK_INPUTS.json"), "utf8"));

const COLORS = {
  blue: "#1F4E78", paleBlue: "#D9EAF7", warning: "#FCE4D6",
  white: "#FFFFFF", text: "#222222", line: "#B7C9D6", link: "#008000",
};
const FONT = "Arial";

function parseCsv(text) {
  const rows = []; let row = [], field = "", quoted = false;
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

async function csv(relative) { return parseCsv(await fs.readFile(path.join(root, relative), "utf8")); }
function n(value) { const parsed = Number(value); return Number.isFinite(parsed) ? parsed : null; }
function excelDate(text) { return new Date(`${text}T00:00:00Z`); }
function section(sheet, range, text) {
  sheet.getRange(range.split(":")[0]).values = [[text]];
  sheet.getRange(range).format = { fill: COLORS.blue, font: { name: FONT, bold: true, color: COLORS.white }, borders: { preset: "outside", style: "thin", color: COLORS.blue } };
}
function headers(sheet, range, values) {
  const target = sheet.getRange(range); target.values = [values];
  target.format = { fill: "#17365D", font: { name: FONT, bold: true, color: COLORS.white }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { insideVertical: { style: "thin", color: COLORS.white }, bottom: { style: "thin", color: COLORS.white } } };
}
function imported(range) { range.format.font = { name: FONT, size: 10, color: COLORS.link }; }
function money(range) { range.format.numberFormat = '$#,##0.0;[Red]($#,##0.0);-'; }
function ratio(range) { range.format.numberFormat = '0.00x;[Red](0.00x);-'; range.format.font.italic = true; }
function percent(range) { range.format.numberFormat = '0.0%;[Red](0.0%);-'; range.format.font.italic = true; }
function dateFmt(range) { range.format.numberFormat = "mm/dd/yy"; }
function styleStatus(range) {
  range.conditionalFormats.deleteAll();
  range.conditionalFormats.add("containsText", { text: "FAIL", format: { fill: "#F4CCCC", font: { bold: true, color: "#9C0006" } } });
  range.conditionalFormats.add("containsText", { text: "WARNING", format: { fill: COLORS.warning, font: { bold: true, color: "#9C5700" } } });
  range.conditionalFormats.add("containsText", { text: "N/D", format: { fill: "#FFF2CC", font: { color: "#7F6000" } } });
}
function setWidths(sheet, widths) { for (const [column, width] of Object.entries(widths)) sheet.getRange(`${column}:${column}`).format.columnWidth = width; }

async function loadWorkbook(inputPath) {
  return SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
}

function updateCreditSummary(workbook) {
  const sheet = workbook.worksheets.getItem("Credit Summary");
  sheet.mergeCells("C5:N5");
  sheet.getRange("C5").values = [["Conditional Approval — proceed with diligence and definitive documentation. | owner_reviewed | public-information hypothetical transaction"]];
  sheet.getRange("C5:N5").format = {
    fill: COLORS.paleBlue,
    font: { name: FONT, bold: true, color: "#17365D" },
    wrapText: true,
    rowHeight: 34,
    borders: { preset: "outside", style: "thin", color: COLORS.line },
  };
  sheet.mergeCells("C6:N6");
  sheet.getRange("C6").values = [["No final commitment or funding authorization exists until all material conditions are satisfied."]];
  sheet.getRange("C6:N6").format = { fill: COLORS.warning, font: { name: FONT, size: 10, bold: true, color: "#9C5700" }, wrapText: true, rowHeight: 26, borders: { preset: "outside", style: "thin", color: COLORS.line } };
  sheet.getRange("C47").values = [["Phase 9 recovery and borrower risk — retained"]];
  sheet.getRange("H47").values = [["Phase 10 committee recommendation"]];
  sheet.getRange("H47:N47").format = {
    fill: COLORS.blue,
    font: { name: FONT, bold: true, color: COLORS.white },
    borders: { preset: "outside", style: "thin", color: COLORS.blue },
  };
  sheet.getRange("H48:H55").values = [
    ["Recommendation / risk"], ["Facilities / hold"], ["Repayment hierarchy"], ["Liquidity / maturity"],
    ["Common horizon 07/31/29"], ["Moderate breach 10/31/26"], ["Conditions / fallback"], ["Recovery / boundary"],
  ];
  sheet.getRange("I48:N55").values = [
    ["Conditional Approval — proceed with diligence and definitive documentation. | owner_reviewed", "Elevated - project-specific qualitative only", "", "", "", ""],
    ["$635m term / $300m revolver / $29.898m opening draw", "Up to $50m combined hold; conditional $15m non-debt source", "", "", "", ""],
    ["Primary: recurring operating cash after all required uses", "Amortization/sweep are payment mechanisms, not sources", "", "", "", ""],
    ["Cash + legally drawable revolver = liquidity support only", "Refinancing = unresolved dependency; 01/31/31 bank-debt gap $324.780m", "", "", "", ""],
    ["Total funded debt: existing $495.368m / reference $507.954m / selected $514.754m", "Selected is $19.385m above existing; no faster same-horizon deleveraging", "", "", "", ""],
    ["U/M leverage 4.4893x/4.4670x; coverage 3.2104x/3.2168x", "Liquidity $165.078m/$168.937m; no exhaustion/payment failure; mitigation does not cure; no waiver", "", "", "", ""],
    ["All material CPs remain open", "If unmet: no added debt/covenant loosening; retain or amend existing via limited amendment/extension", "", "", "", ""],
    ["Official recovery N/D; collateral/business-sale recovery is secondary backstop", "Not bank approval, commitment, funding authorization, legal opinion, or official grade", "", "", "", ""],
  ];
  sheet.getRange("I48:N55").format.font = { name: FONT, size: 10, color: COLORS.link };
  sheet.getRange("H48:N55").format.wrapText = true;
  sheet.getRange("H48:N55").format.borders = { bottom: { style: "hair", color: COLORS.line } };
  for (const row of [49, 50, 51, 52, 53, 54, 55]) sheet.getRange(`${row}:${row}`).format.rowHeight = 39;
  sheet.getRange("I53:N53").format = { fill: COLORS.warning, font: { name: FONT, size: 10, bold: true, color: "#9C5700" }, wrapText: true };
  sheet.getRange("I53:N55").conditionalFormats.deleteAll();
  sheet.getRange("I53:N55").conditionalFormats.add("containsText", { text: "N/D", format: { fill: "#FFF2CC", font: { color: "#7F6000" } } });
  sheet.getRange("H56").values = [["Same-date closing debt"]];
  sheet.getRange("I56:N56").values = [["01/31/26 existing $732.517m / selected $727.517m", "Selected is $5.000m lower only with the conditional $15m source; otherwise resize, replace with acceptable non-debt funding, or do not close", "", "", "", ""]];
  sheet.getRange("H56:N56").format = { fill: "#F2F2F2", font: { name: FONT, size: 10, color: COLORS.text }, wrapText: true, rowHeight: 38, borders: { bottom: { style: "hair", color: COLORS.line } } };
  sheet.getRange("H57").values = [["Authorization boundary"]];
  sheet.getRange("I57:N57").values = [["No final commitment or funding authorization until every material condition is satisfied", "Mandatory fallback: retain or amend existing facilities if a material condition fails", "", "", "", ""]];
  sheet.getRange("H57:N57").format = { fill: COLORS.warning, font: { name: FONT, size: 10, bold: true, color: "#9C5700" }, wrapText: true, rowHeight: 38, borders: { bottom: { style: "hair", color: COLORS.line } } };
}

async function applyAuditRemediation(workbook) {
  const [openingDebt, termSizing, amortization, dynamicEvidence, scenarioCaptures] = await Promise.all([
    csv("data/phase8/processed/OPENING_DEBT_COMPARISON.csv"),
    csv("data/phase8/processed/TERM_SIZING_SENSITIVITY.csv"),
    csv("data/phase8/processed/AMORTIZATION_SENSITIVITY_RESULTS.csv"),
    csv("data/phase8/processed/DYNAMIC_TEST_EVIDENCE.csv"),
    csv("data/phase8/processed/SCENARIO_CAPTURE_RESULTS.csv"),
  ]);

  const tx = workbook.worksheets.getItem("Transaction");
  tx.getRange("C20:I44").clear({ applyTo: "all" });
  tx.charts.deleteAll();
  section(tx, "C20:G20", "Historical reference - October 31, 2025 actual");
  headers(tx, "C21:G21", ["Reference point", "Date", "Bank debt", "Lease / other debt", "Total funded debt"]);
  const actual = openingDebt.find(row => row.comparison_group === "historical_reference");
  tx.getRange("C22:G22").values = [[actual.alternative, excelDate(actual.comparison_date), n(actual.bank_debt), n(actual.other_funded_debt), n(actual.total_funded_debt)]];
  imported(tx.getRange("C22:G22")); dateFmt(tx.getRange("D22")); money(tx.getRange("E22:G22"));
  section(tx, "C24:I24", "Projected closing alternatives - January 31, 2026");
  headers(tx, "C25:I25", ["Alternative", "Date", "Bank debt", "Lease / other debt", "Total funded debt", "vs projected existing", "Status"]);
  const projected = openingDebt.filter(row => row.comparison_group === "projected_closing_alternatives");
  tx.getRange("C26:I28").values = projected.map((row, index) => [row.alternative, excelDate(row.comparison_date), n(row.bank_debt), n(row.other_funded_debt), n(row.total_funded_debt), index === 0 ? 0 : n(row.total_funded_debt) - n(projected[0].total_funded_debt), row.status]);
  imported(tx.getRange("C26:I28")); dateFmt(tx.getRange("D26:D28")); money(tx.getRange("E26:H28")); styleStatus(tx.getRange("I26:I28"));
  tx.getRange("C30:I30").values = [["Selected is $5.000m below same-date existing only because the conditional $15m source exceeds assumed $10m refinancing fees. If unavailable: resize, obtain acceptable non-debt funding, or do not close."]];
  tx.mergeCells("C30:I30");
  tx.getRange("C30:I30").format = { fill: COLORS.warning, font: { name: FONT, italic: true, color: "#7F6000" }, wrapText: true, rowHeight: 34 };
  section(tx, "C32:G32", "Common horizon and separate ultimate maturities");
  headers(tx, "C33:G33", ["Alternative", "07/31/29 total funded debt", "vs existing", "Maturity", "Unsupported bank-debt gap"]);
  const common = parseCsv(await fs.readFile(path.join(root, "data/phase7/processed/COMMON_HORIZON_COMPARISON.csv"), "utf8"));
  const maturity = parseCsv(await fs.readFile(path.join(root, "data/phase7/processed/ULTIMATE_MATURITY_COMPARISON.csv"), "utf8"));
  const comparisonRows = [["STR-001", "Retain existing facilities"], ["STR-008", "Selected $635m refinancing"], ["STR-003", "$650m reference refinancing"]];
  const existingCommon = n(common.find(row => row.candidate_id === "STR-001" && row.scenario_id === "BASE").ending_total_funded_debt);
  tx.getRange("C34:G36").values = comparisonRows.map(([candidateId, label]) => {
    const commonRow = common.find(row => row.candidate_id === candidateId && row.scenario_id === "BASE");
    const maturityRow = maturity.find(row => row.candidate_id === candidateId && row.scenario_id === "BASE");
    return [label, n(commonRow.ending_total_funded_debt), n(commonRow.ending_total_funded_debt) - existingCommon, excelDate(maturityRow.maturity_date), n(maturityRow.unsupported_maturity_gap)];
  });
  imported(tx.getRange("C34:G36")); money(tx.getRange("D34:E36")); dateFmt(tx.getRange("F34:F36")); money(tx.getRange("G34:G36"));
  tx.getRange("C38:G38").values = [["Ultimate gaps use different maturity dates and are not directly comparable. Limited amendment / extension remains N/D without terms."]];
  tx.mergeCells("C38:G38");
  tx.getRange("C38:G38").format = { fill: "#FAF4EA", font: { name: FONT, italic: true, color: "#666666" }, wrapText: true, rowHeight: 28 };
  section(tx, "C40:G40", "Commitment and unresolved closing items");
  tx.getRange("C41:C44").values = [["Revolver commitment"], ["Letters of credit"], ["Gross availability"], ["Usable availability after LCs"]];
  tx.getRange("D41:D44").formulas = [["='Assumptions'!D14"], ["='Assumptions'!D16"], ["='Assumptions'!D14-'Assumptions'!D15"], ["='Assumptions'!D14-'Assumptions'!D16-'Assumptions'!D15"]];
  money(tx.getRange("D41:D44")); imported(tx.getRange("D41:D44"));
  tx.getRange("F41:G44").values = [["Financing fees not already approved", "N/D"], ["LC transition mechanics", "Pending information"], ["Final lender pricing", "Pending information"], ["Final payoff and funds flow", "Pending information"]];
  styleStatus(tx.getRange("G41:G44"));
  const debtChart = tx.charts.add("bar", [tx.getRange("C25:C28"), tx.getRange("G25:G28")]);
  debtChart.title = "Projected closing funded debt - 01/31/26 (USD millions)"; debtChart.titleTextStyle.typeface = FONT; debtChart.hasLegend = false; debtChart.setPosition("K6", "R20");
  setWidths(tx, { C: 32, D: 14, E: 15, F: 18, G: 20, H: 18, I: 24, J: 3 });

  const cv = workbook.worksheets.getItem("Covenants");
  for (let row = 9; row <= 27; row += 1) {
    cv.getRange(`G${row}`).formulas = [[`=IF(COUNTIFS('Assumptions'!$C$41:$C$364,$D$4,'Assumptions'!$H$41:$H$364,$C${row},'Assumptions'!$AT$41:$AT$364,"<>")=0,"N/D",SUMIFS('Assumptions'!$AT$41:$AT$364,'Assumptions'!$C$41:$C$364,$D$4,'Assumptions'!$H$41:$H$364,$C${row})*(1+'Assumptions'!$D$21))`]];
    cv.getRange(`H${row}`).formulas = [[`=IF(G${row}="N/D","",IF(G${row}<=0,"",F${row}/G${row}))`]];
    cv.getRange(`I${row}`).formulas = [[`=IF(G${row}="N/D","N/D",IF(G${row}<=0,"N/M",TEXT(H${row},"0.00x")))`]];
    cv.getRange(`L${row}`).formulas = [[`=IF(G${row}="N/D","N/D",IF(G${row}<=0,"N/M",IF(H${row}>J${row},"BREACH",IF(H${row}>=K${row},"WARNING","COMPLIANT"))))`]];
    cv.getRange(`N${row}`).formulas = [[`=IF(OR(G${row}="N/D",M${row}=""),"",IF(OR(G${row}<=0,M${row}<=0),"",G${row}/M${row}))`]];
    cv.getRange(`O${row}`).formulas = [[`=IF(OR(G${row}="N/D",M${row}=""),"N/D",IF(OR(G${row}<=0,M${row}<=0),"N/M",TEXT(N${row},"0.00x")))`]];
    cv.getRange(`R${row}`).formulas = [[`=IF(OR(G${row}="N/D",M${row}=""),"N/D",IF(OR(G${row}<=0,M${row}<=0),"N/M",IF(N${row}<P${row},"BREACH",IF(N${row}<=Q${row},"WARNING","COMPLIANT"))))`]];
    cv.getRange(`V${row}`).formulas = [[`=IF(X${row}="INCOMPLETE","N/D",IF(L${row}="N/M","N/M",IF(R${row}="N/M","N/M",IF(L${row}="N/D","N/D",IF(R${row}="N/D","N/D",IF(OR(L${row}="BREACH",R${row}="BREACH",T${row}="BREACH"),"BREACH","COMPLIANT"))))))`]];
    cv.getRange(`X${row}`).formulas = [[`=IF(OR(G${row}="N/D",M${row}=""),"INCOMPLETE","COMPLETE")`]];
    cv.getRange(`AF${row}`).formulas = [[`=IF(OR(G${row}="N/D",G${row}<=0,M${row}="",M${row}<=0),"",G${row}-M${row}*P${row})`]];
  }
  const sc = workbook.worksheets.getItem("Scenario Comparison");
  sc.getRange("M5").formulas = [["=MAX('Transaction'!$D$9,MAX('Debt Schedule'!R12:R47))"]];
  sc.getRange("M12:M20").values = scenarioCaptures.map(row => [n(row.peak_revolver)]);
  sc.getRange("Q12:Q20").values = scenarioCaptures.map(row => [n(row.maximum_leverage)]);
  imported(sc.getRange("M12:M20")); imported(sc.getRange("Q12:Q20"));
  sc.getRange("Q4").values = [["Maximum quarterly-test leverage"]];
  sc.getRange("Q11").values = [["Maximum quarterly-test leverage"]];
  const creditSummary = workbook.worksheets.getItem("Credit Summary");
  creditSummary.getRange("C24").values = [["Maximum quarterly-test leverage"]];

  const s = workbook.worksheets.getItem("Sensitivities");
  s.getRange("C6:Q31").clear({ applyTo: "all" });
  section(s, "C6:K6", "Term sizing - authoritative Phase 7 closing pairings");
  headers(s, "C7:K7", ["Term", "Opening revolver", "Non-debt source", "Total sources", "Total uses", "Sources less uses", "Closing funded debt", "Opening leverage", "Status"]);
  s.getRange("C8:K11").values = termSizing.map(row => [n(row.term_amount), n(row.opening_revolver), n(row.non_debt_source), n(row.total_sources), n(row.total_uses), n(row.sources_less_uses), n(row.projected_closing_funded_debt), n(row.opening_leverage), row.case_status]);
  imported(s.getRange("C8:K11")); money(s.getRange("C8:I11")); ratio(s.getRange("J8:J11")); styleStatus(s.getRange("K8:K11"));
  section(s, "C14:H14", "EBITDA and leverage headroom");
  headers(s, "C15:H15", ["EBITDA change", "Lender EBITDA", "Opening leverage", "3.50x debt headroom", "3.25x warning headroom", "Maturity-gap diagnostic"]);
  [-0.20, -0.10, 0, 0.10, 0.20].forEach((change, index) => {
    const row = 16 + index; s.getRange(`C${row}`).values = [[change]];
    s.getRange(`D${row}:H${row}`).formulas = [[`='Credit Adjustments'!$E$14*(1+C${row})`, `='Transaction'!$D$17/D${row}`, `=D${row}*3.5-'Transaction'!$D$17`, `=D${row}*3.25-'Transaction'!$D$17`, `='Scenario Comparison'!$X$5-('Credit Adjustments'!$E$14-D${row})*0.5`]];
  });
  imported(s.getRange("C16:H20")); percent(s.getRange("C16:C20")); money(s.getRange("D16:D20")); ratio(s.getRange("E16:E20")); money(s.getRange("F16:H20"));
  section(s, "J14:N14", "Rate, working capital and liquidity");
  headers(s, "J15:N15", ["Spread change", "Cash interest diagnostic", "DSO change", "Liquidity effect", "Maturity-gap effect"]);
  [-0.01, 0, 0.01, 0.02].forEach((change, index) => {
    const row = 16 + index; s.getRange(`J${row}`).values = [[change]]; s.getRange(`L${row}`).values = [[[-5, 0, 5, 10][index]]];
    s.getRange(`K${row}`).formulas = [[`='Scenario Comparison'!$J$5+J${row}*AVERAGE('Debt Schedule'!S12:S47)*5`]];
    s.getRange(`M${row}:N${row}`).formulas = [[`=-L${row}*SUM('Forecast'!D10:W10)/365`, `=MAX(0,'Scenario Comparison'!$X$5-M${row})`]];
  });
  imported(s.getRange("J16:N19")); percent(s.getRange("J16:J19")); money(s.getRange("K16:K19")); money(s.getRange("M16:N19"));
  section(s, "C23:Q23", "Integrated selected-structure amortization sensitivity - Base operating case");
  headers(s, "C24:Q24", ["Annual amort.", "Scheduled principal", "Avg. bank debt", "Cash interest", "Peak revolver", "Min. operating cash", "Min. usable liquidity", "ECF sweep", "Ending bank debt", "07/31/29 funded debt", "Maturity gap", "Max quarterly-test leverage", "Min complete LTM coverage", "First warning", "First breach"]);
  s.getRange("C25:Q28").values = amortization.map(row => [n(row.annual_amortization_percent) / 100, n(row.cumulative_scheduled_principal), n(row.average_modeled_bank_debt), n(row.cumulative_cash_interest), n(row.peak_revolver), n(row.minimum_operating_cash), n(row.minimum_usable_liquidity), n(row.cumulative_ecf_sweep), n(row.ending_bank_debt), n(row.common_horizon_total_funded_debt), n(row.unsupported_maturity_gap), n(row.maximum_quarterly_test_leverage), n(row.minimum_complete_ltm_coverage), row.first_warning_date, row.first_breach_date]);
  imported(s.getRange("C25:Q28")); percent(s.getRange("C25:C28")); money(s.getRange("D25:M28")); ratio(s.getRange("N25:O28")); styleStatus(s.getRange("P25:Q28"));
  s.getRange("C30:Q30").values = [["Each row reruns the Phase 7 integrated cash, debt, revolver, interest, liquidity, ECF sweep, covenant, and maturity mechanics. The 7.5% row is the approved selected Base case."]];
  s.mergeCells("C30:Q30");
  s.getRange("C30:Q30").format = { fill: "#FAF4EA", font: { name: FONT, italic: true, color: "#666666" }, wrapText: true, rowHeight: 30 };
  setWidths(s, { C: 15, D: 17, E: 17, F: 17, G: 17, H: 18, I: 17, J: 17, K: 18, L: 18, M: 18, N: 18, O: 18, P: 16, Q: 16 });

  const checks = workbook.worksheets.getItem("Checks");
  section(checks, "C58:H58", "Post-Phase 11 economic-semantic controls");
  headers(checks, "C59:H59", ["Check", "Observed", "Expected", "Tolerance", "Status", "Notes"]);
  const dynamicPasses = dynamicEvidence.filter(row => row.status === "PASS").length;
  const integratedParity = `=ABS('Sensitivities'!D26-'Scenario Comparison'!K5)+ABS('Sensitivities'!F26-'Scenario Comparison'!J5)+ABS('Sensitivities'!G26-'Scenario Comparison'!M5)+ABS('Sensitivities'!I26-'Scenario Comparison'!P5)+ABS('Sensitivities'!J26-'Scenario Comparison'!L5)+ABS('Sensitivities'!L26-'Scenario Comparison'!W5)+ABS('Sensitivities'!M26-'Scenario Comparison'!X5)+ABS('Sensitivities'!N26-'Scenario Comparison'!Q5)+ABS('Sensitivities'!O26-'Scenario Comparison'!R5)`;
  const items = [
    ["Projected alternatives share 01/31/26", '=COUNTIF(\'Transaction\'!D26:D28,DATE(2026,1,31))', 3, 0, '=IF(D60=E60,"PASS","FAIL")', "Rejects mixed comparison dates"],
    ["10/31/25 actual shown separately", '=\'Transaction\'!D22', excelDate("2025-10-31"), 0, '=IF(D61=E61,"PASS","FAIL")', "Historical reference is not an alternative row"],
    ["Selected same-date debt advantage", '=\'Transaction\'!G27-\'Transaction\'!G26', -5, 0.002, '=IF(ABS(D62-E62)<=F62,"PASS","FAIL")', "Conditional $15m source exceeds $10m fees"],
    ["Feasible sizing rows balance", '=MAX(ABS(\'Sensitivities\'!H8),ABS(\'Sensitivities\'!H9),ABS(\'Sensitivities\'!H10),ABS(\'Sensitivities\'!H11))', 0, 0.002, '=IF(D63<=F63,"PASS","FAIL")', "No feasible row uses unexplained funding"],
    ["Selected conditional source visible", '=\'Sensitivities\'!E9', 15, 0.002, '=IF(ABS(D64-E64)<=F64,"PASS","FAIL")', "Not replaced with incremental debt"],
    ["Integrated 7.5% parity", integratedParity, 0, 0.02, '=IF(D65<=F65,"PASS","FAIL")', "Debt, interest, revolver, liquidity, sweep, covenant, and maturity chain"],
    ["April 2026 incomplete LTM", '=\'Covenants\'!I9', "N/D", 0, '=IF(D66=E66,"PASS","FAIL")', "Missing is not N/M"],
    ["July 2026 incomplete LTM", '=\'Covenants\'!I10', "N/D", 0, '=IF(D67=E67,"PASS","FAIL")', "Missing is not N/M"],
    ["First complete leverage date", '=ISNUMBER(\'Covenants\'!H11)', true, 0, '=IF(D68=E68,"PASS","FAIL")', "October 2026 has a complete EBITDA denominator"],
    ["Common-horizon disadvantage", '=\'Transaction\'!D35-\'Transaction\'!D34', 19.38542657947032, 0.002, '=IF(ABS(D69-E69)<=F69,"PASS","FAIL")', "Selected remains above existing at 07/31/29"],
    ["Phase 8 dynamic evidence", dynamicPasses, dynamicEvidence.length, 0, '=IF(AND(D70=E70,E70>0),"PASS","FAIL")', "Separately identifiable disposable-copy evidence"],
    ["Final scenario Base", '=\'Assumptions\'!D4', "Base", 0, '=IF(D71=E71,"PASS","FAIL")', "Approved saved state"],
  ];
  items.forEach((item, index) => {
    const row = 60 + index; checks.getRange(`C${row}`).values = [[item[0]]];
    if (typeof item[1] === "string" && item[1].startsWith("=")) checks.getRange(`D${row}`).formulas = [[item[1]]]; else checks.getRange(`D${row}`).values = [[item[1]]];
    checks.getRange(`E${row}`).values = [[item[2]]]; checks.getRange(`F${row}`).values = [[item[3]]]; checks.getRange(`G${row}`).formulas = [[item[4]]]; checks.getRange(`H${row}`).values = [[item[5]]];
  });
  imported(checks.getRange("D60:E71")); styleStatus(checks.getRange("G60:G71"));
  setWidths(checks, { C: 38, D: 24, E: 24, F: 13, G: 15, H: 62 });
}

function updateChecks(workbook) {
  const sheet = workbook.worksheets.getItem("Checks");
  sheet.getRange("C55").values = [["Phase 10 recommendation status"]];
  sheet.getRange("D55:E55").values = [[payload.recommendation_status, payload.recommendation_status]];
  sheet.getRange("D55:E55").format = {
    font: { name: FONT, size: 10, color: COLORS.link },
    wrapText: true,
  };
  sheet.getRange("H55").values = [["Owner-reviewed project recommendation; not a bank approval or lender commitment"]];
  sheet.getRange("55:55").format.rowHeight = 30;
}

async function build() {
  const workbook = await loadWorkbook(baselinePath);
  await applyAuditRemediation(workbook);
  updateCreditSummary(workbook);
  updateChecks(workbook);
  workbook.recalculate();
  await fs.mkdir(path.dirname(modelPath), { recursive: true });
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(modelPath);
  console.log(JSON.stringify({ status: "PASS", sheets: 14, output: "model/Quanex_Credit_Underwriting.xlsx" }));
}

async function inspect() {
  const workbook = await loadWorkbook(baselinePath);
  await fs.mkdir(previewDir, { recursive: true });
  const ranges = { "Credit Summary": "C1:N59", "Transaction": "C1:R45", "Sensitivities": "C1:Q31", "Covenants": "C1:AR28", "Recovery": "C1:N47", "Checks": "C1:H72" };
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
    options: { useRegex: true, maxResults: 300 },
    summary: "Phase 10 formula error scan",
  });
  if (errors.ndjson && !errors.ndjson.includes('"matchCount":0')) console.log(errors.ndjson);
  for (const [sheetName, range] of Object.entries(ranges)) {
    const image = await workbook.render({ sheetName, range, scale: 1, format: "png" });
    await fs.writeFile(path.join(previewDir, `${sheetName.toLowerCase().replaceAll(" ", "-")}.png`), new Uint8Array(await image.arrayBuffer()));
  }
  const sample = await workbook.inspect({ kind: "region", sheetId: "Credit Summary", range: "C1:N59", maxChars: 9000 });
  await fs.writeFile(path.join(previewDir, "inspection.ndjson"), sample.ndjson, "utf8");
  console.log(JSON.stringify({ status: "PASS", previews: Object.keys(ranges).length, errorScan: "completed" }));
}

if (mode === "build") await build();
else if (mode === "inspect") await inspect();
else throw new Error("usage: build-phase10.mjs build|inspect ROOT WORKBOOK [PREVIEW_DIR]");
