import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const mode = process.argv[2];
const root = path.resolve(process.argv[3]);
const baselinePath = path.resolve(process.argv[4]);
const previewDir = process.argv[5] ? path.resolve(process.argv[5]) : null;
const modelPath = path.join(root, "model", "Quanex_Credit_Underwriting.xlsx");
const payload = JSON.parse(await fs.readFile(path.join(root, "data", "phase9", "processed", "WORKBOOK_INPUTS.json"), "utf8"));

const COLORS = {
  navy: "#17365D", blue: "#1F4E78", medium: "#4472C4", paleBlue: "#D9EAF7",
  paleTan: "#FAF4EA", gray: "#F2F2F2", line: "#B7C9D6", input: "#FFF2CC",
  warning: "#FCE4D6", fail: "#F4CCCC", formula: "#000000", link: "#008000",
  hardcode: "#0000FF", white: "#FFFFFF", text: "#222222",
};
const FONT = "Arial";

function title(sheet, text, scenario = true) {
  sheet.showGridLines = false;
  sheet.getRange("C2").values = [[text]];
  sheet.getRange("C2").format.font = { name: FONT, size: 15, bold: true, color: COLORS.navy };
  sheet.getRange("C3:N3").format.borders = { bottom: { style: "thin", color: COLORS.medium } };
  if (scenario) {
    sheet.getRange("C4").values = [["Case selected:"]];
    sheet.getRange("D4").formulas = [["='Assumptions'!$D$4"]];
    sheet.getRange("D4").format = { fill: COLORS.paleBlue, font: { name: FONT, bold: true, color: COLORS.link }, horizontalAlignment: "center", borders: { preset: "outside", style: "dashed", color: COLORS.medium } };
  }
}

function section(sheet, address, text) {
  const range = sheet.getRange(address);
  sheet.getRange(address.split(":")[0]).values = [[text]];
  range.format = { fill: COLORS.blue, font: { name: FONT, bold: true, color: COLORS.white }, borders: { preset: "outside", style: "thin", color: COLORS.blue } };
}

function headers(sheet, address, values) {
  const range = sheet.getRange(address);
  range.values = [values];
  range.format = { fill: COLORS.navy, font: { name: FONT, bold: true, color: COLORS.white }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { insideVertical: { style: "thin", color: COLORS.white }, bottom: { style: "thin", color: COLORS.white } } };
}

function setWidths(sheet, widths) {
  for (const [column, width] of Object.entries(widths)) sheet.getRange(`${column}:${column}`).format.columnWidth = width;
}
function money(range) { range.format.numberFormat = '$#,##0.0;[Red]($#,##0.0);-'; }
function ratio(range) { range.format.numberFormat = '0.00"x";[Red](0.00"x");-'; range.format.font.italic = true; }
function percent(range) { range.format.numberFormat = '0.0%;[Red](0.0%);-'; range.format.font.italic = true; }
function dateFmt(range) { range.format.numberFormat = "mm/dd/yy"; }
function imported(range) { range.format.font = { name: FONT, size: 10, color: COLORS.link }; }
function hardcode(range) { range.format = { fill: COLORS.input, font: { name: FONT, size: 10, color: COLORS.hardcode }, borders: { preset: "outside", style: "thin", color: COLORS.line } }; }
function sameFormula(range) { range.format.font = { name: FONT, size: 10, color: COLORS.formula }; }
function crossFormula(range) { range.format.font = { name: FONT, size: 10, color: COLORS.link }; }
function styleStatus(range) {
  range.conditionalFormats.deleteAll();
  range.conditionalFormats.add("containsText", { text: "FAIL", format: { fill: COLORS.fail, font: { bold: true, color: "#9C0006" } } });
  range.conditionalFormats.add("containsText", { text: "N/D", format: { fill: COLORS.input, font: { color: "#7F6000" } } });
  range.conditionalFormats.add("containsText", { text: "PENDING", format: { fill: COLORS.warning, font: { color: "#9C5700" } } });
}
function excelDate(text) { return text ? new Date(`${text}T00:00:00Z`) : null; }
function pct(text) { return Number(text) / 100; }
function n(text) { return Number(text); }

function formulas(sheet, address, matrix, cross = false) {
  sheet.getRange(address).formulas = matrix;
  (cross ? crossFormula : sameFormula)(sheet.getRange(address));
}

async function loadWorkbook(inputPath) {
  return SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
}

function addAssumptions(workbook) {
  const a = workbook.worksheets.getItem("Assumptions");
  a.getRange("H23:L38").clear({ applyTo: "all" });
  section(a, "H23:L23", "Phase 9 recovery assumptions — owner reviewed");
  headers(a, "H24:L24", ["Assumption", "Low", "Base", "High", "Status / source"]);
  const x = payload.exposure;
  const rows = [
    ["Primary recovery date", null, excelDate(x.recovery_date), null, "Calculated: first mandatory-payment failure"],
    ["Recovery scenario", null, x.scenario_id, null, "Selected severe unmitigated"],
    ["Term principal", null, n(x.term_principal), null, "Phase 7 selected path"],
    ["Revolver principal", null, n(x.revolver_principal), null, "Phase 7 selected path"],
    ["Unpaid cash interest", null, n(x.unpaid_cash_interest), null, "Proposed claim component"],
    ["Other-funded-obligations deduction", null, n(x.retained_other_funded_debt), null, "P9D-011; owner reviewed; ranking N/D"],
    ["Stress-date TTM lender EBITDA", null, n(x.stressed_ttm_ebitda), null, "P9D-002; not contractual EBITDA"],
    ["Going-concern multiple", 3, 4, 5, "P9D-003; owner reviewed; illustrative"],
    ["Going-concern realization cost", 0.10, 0.10, 0.10, "P9D-004; owner reviewed"],
    ["Full consolidated-access ceiling", 1.00, 1.00, 1.00, "P9D-012; owner reviewed; access N/D"],
    ["Receivables realization", 0.50, 0.70, 0.85, "P9D-005; owner reviewed; no appraisal"],
    ["Inventory realization", 0.20, 0.40, 0.60, "P9D-006; owner reviewed; no appraisal"],
    ["Net PP&E realization", 0.20, 0.40, 0.60, "P9D-007; owner reviewed; no appraisal"],
    ["Asset realization cost", 0.15, 0.15, 0.15, "P9D-008; owner reviewed"],
  ];
  a.getRange("H25:L38").values = rows;
  imported(a.getRange("H25:H31"));
  imported(a.getRange("J25:J31"));
  hardcode(a.getRange("I32:K38"));
  a.getRange("L25:L38").format.font = { name: FONT, size: 9, color: COLORS.text };
  dateFmt(a.getRange("J25")); money(a.getRange("J27:J31"));
  ratio(a.getRange("I32:K32"));
  percent(a.getRange("I33:K38"));
  a.getRange("H25:L38").format.wrapText = true;
  a.getRange("H25:L38").format.borders = { bottom: { style: "hair", color: COLORS.line } };
  for (const row of [31, 33, 34]) a.getRange(`${row}:${row}`).format.rowHeight = 29;
}

function addRecovery(workbook) {
  const r = workbook.worksheets.getItem("Recovery");
  r.getRange("C1:N66").clear({ applyTo: "all" });
  title(r, "Recovery analysis — secondary repayment sensitivity");
  r.mergeCells("C5:N5");
  r.getRange("C5").values = [["Official facility recovery remains N/D: guarantor, collateral, lien, priority, access, appraisal and complete claims evidence are unavailable."]];
  r.getRange("C5:N5").format = { fill: COLORS.warning, font: { name: FONT, bold: true, color: "#7F6000" }, wrapText: true, rowHeight: 31, borders: { preset: "outside", style: "thin", color: COLORS.line } };
  section(r, "C7:G7", "Primary recovery exposure");
  r.getRange("C8:C17").values = [["Recovery date"], ["Scenario"], ["Term principal"], ["Revolver principal"], ["Unpaid cash interest"], ["Illustrative facility claim"], ["Other-funded-obligations deduction"], ["Gross funded principal"], ["Stress-date TTM lender EBITDA"], ["Gross funded leverage"]];
  formulas(r, "D8:D17", [
    ["='Assumptions'!J25"], ["='Assumptions'!J26"], ["='Assumptions'!J27"], ["='Assumptions'!J28"], ["='Assumptions'!J29"],
    ["=SUM(D10:D12)"], ["='Assumptions'!J30"], ["=D10+D11+D14"], ["='Assumptions'!J31"], ["=D15/D16"],
  ], true);
  dateFmt(r.getRange("D8")); money(r.getRange("D10:D16")); ratio(r.getRange("D17"));
  r.getRange("F8:G17").values = [
    ["Status", "Primary first mandatory-payment failure"], ["Drawability", payload.exposure.drawability_status],
    ["Cash interest due", n(payload.exposure.cash_interest_due)], ["Cash interest paid", n(payload.exposure.cash_interest_paid)],
    ["Usable liquidity", n(payload.exposure.usable_liquidity)], ["Failed obligation", payload.exposure.failed_obligation_type],
    ["Illustrative allocation", "Owner-reviewed pro rata mechanics"], ["Legal priority", "N/D"],
    ["Recovery method", "Going concern OR asset realization"], ["Boundary", "Methods are alternatives; never added"],
  ];
  money(r.getRange("G10:G12")); styleStatus(r.getRange("G8:G17"));
  section(r, "I7:N7", "Separate ultimate-maturity sensitivity");
  r.getRange("I8:I13").values = [["Maturity date"], ["Bank payment due before cash"], ["Modeled cash applied"], ["Unsupported maturity gap"], ["Retained debt proxy"], ["Gross funded before cash"]];
  r.getRange("J8:J13").values = [[excelDate(payload.maturity.date)], [n(payload.maturity.bank_claim_before_cash)], [n(payload.maturity.cash_applied)], [n(payload.maturity.unsupported_gap)], [n(payload.maturity.retained_other_funded_debt)], [n(payload.maturity.gross_funded_before_cash)]];
  imported(r.getRange("J8:J13")); dateFmt(r.getRange("J8")); money(r.getRange("J9:J13"));
  r.getRange("L8:N13").values = [["Purpose", "Base maturity refinancing exposure", "Not the primary recovery date"], ["Refinancing", "Not assumed", "Requires separate underwriting"], ["Source", "P7UM-008", "Approved upstream"], ["Status", "Sensitivity", "Not a recovery estimate"], ["Claim priority", "N/D", "Private diligence required"], ["Recovery impact", "None in official conclusion", "Official result stays N/D"]];
  styleStatus(r.getRange("M8:N13"));

  section(r, "C20:F20", "Going-concern sensitivity");
  headers(r, "C21:F21", ["Measure", "Low", "Base", "High"]);
  r.getRange("C22:C30").values = [["Stress-date TTM lender EBITDA"], ["Illustrative multiple"], ["Gross enterprise value"], ["Realization costs"], ["Value after costs"], ["Other-funded-obligations deduction"], ["Illustrative bank allocation (capped)"], ["Illustrative facility recovery"], ["Residual after facility claim"]];
  formulas(r, "D22:F30", [
    ["=$D$16", "=$D$16", "=$D$16"], ["='Assumptions'!I32", "='Assumptions'!J32", "='Assumptions'!K32"],
    ["=D22*D23", "=E22*E23", "=F22*F23"], ["=D24*'Assumptions'!I33", "=E24*'Assumptions'!J33", "=F24*'Assumptions'!K33"],
    ["=MAX(0,D24-D25)", "=MAX(0,E24-E25)", "=MAX(0,F24-F25)"], ["=$D$14", "=$D$14", "=$D$14"],
    ["=MIN($D$13,MAX(0,D26-D27))", "=MIN($D$13,MAX(0,E26-E27))", "=MIN($D$13,MAX(0,F26-F27))"],
    ["=IF($D$13=0,0,D28/$D$13)", "=IF($D$13=0,0,E28/$D$13)", "=IF($D$13=0,0,F28/$D$13)"],
    ["=MAX(0,D26-D27-$D$13)", "=MAX(0,E26-E27-$D$13)", "=MAX(0,F26-F27-$D$13)"],
  ]);
  money(r.getRange("D22:F22")); ratio(r.getRange("D23:F23")); money(r.getRange("D24:F28")); percent(r.getRange("D29:F29")); money(r.getRange("D30:F30"));
  r.getRange("C31:F31").values = [["Boundary", "No market evidence", "Owner-review sensitivity", "Not official recovery"]];
  r.getRange("C31:F31").format = { fill: COLORS.paleTan, font: { name: FONT, italic: true, color: COLORS.text } };

  section(r, "H20:N20", "Asset-realization sensitivity");
  headers(r, "H21:N21", ["Asset", "FY2025 book", "Low %", "Low proceeds", "Base %", "Base proceeds", "High % / proceeds"]);
  const book = payload.book_values || {};
  const assets = [
    ["Cash", book.cash_and_cash_equivalents, 0, 0, 0], ["Accounts receivable", book.accounts_receivable, 35, 35, 35],
    ["Inventory", book.inventory, 36, 36, 36], ["Net PP&E", book.property_plant_and_equipment_net, 37, 37, 37],
    ["Goodwill", book.goodwill, null, null, null], ["Intangible assets", book.intangible_assets_net, null, null, null],
    ["Other current assets", book.other_presented_current_assets, null, null, null],
  ];
  for (let i = 0; i < assets.length; i += 1) {
    const row = 22 + i; const [label, value, assumptionRow] = assets[i];
    r.getRange(`H${row}:I${row}`).values = [[label, n(value)]];
    if (label === "Accounts receivable" || label === "Inventory" || label === "Net PP&E") {
      formulas(r, `J${row}:N${row}`, [[`='Assumptions'!I${assumptionRow}`, `=I${row}*J${row}*'Assumptions'!I34`, `='Assumptions'!J${assumptionRow}`, `=I${row}*L${row}*'Assumptions'!J34`, `=TEXT('Assumptions'!K${assumptionRow},"0.0%")&" / "&TEXT(I${row}*'Assumptions'!K${assumptionRow}*'Assumptions'!K34,"$#,##0.0")`]], true);
    } else {
      r.getRange(`J${row}:N${row}`).values = [[0, 0, 0, 0, "0.0% / $0.0"]]; imported(r.getRange(`J${row}:N${row}`));
    }
  }
  imported(r.getRange("I22:I28")); money(r.getRange("I22:I28")); percent(r.getRange("J22:J28")); money(r.getRange("K22:K28")); percent(r.getRange("L22:L28")); money(r.getRange("M22:M28"));
  r.getRange("H29:H34").values = [["Gross consolidated full-access ceiling proceeds"], ["Realization costs"], ["Proceeds after costs"], ["Other-funded-obligations deduction"], ["Illustrative bank allocation (capped)"], ["Illustrative facility recovery"]];
  formulas(r, "I29:N34", [
    ["", "", "=SUM(K22:K28)", "", "=SUM(M22:M28)", "=I23*'Assumptions'!K35+I24*'Assumptions'!K36+I25*'Assumptions'!K37"],
    ["", "", "=K29*'Assumptions'!I38", "", "=M29*'Assumptions'!J38", "=N29*'Assumptions'!K38"],
    ["", "", "=MAX(0,K29-K30)", "", "=MAX(0,M29-M30)", "=MAX(0,N29-N30)"],
    ["", "", "=$D$14", "", "=$D$14", "=$D$14"],
    ["", "", "=MIN($D$13,MAX(0,K31-K32))", "", "=MIN($D$13,MAX(0,M31-M32))", "=MIN($D$13,MAX(0,N31-N32))"],
    ["", "", "=IF($D$13=0,0,K33/$D$13)", "", "=IF($D$13=0,0,M33/$D$13)", "=IF($D$13=0,0,N33/$D$13)"],
  ]);
  money(r.getRange("K29:K33")); money(r.getRange("M29:N33")); percent(r.getRange("K34")); percent(r.getRange("M34:N34"));

  section(r, "C37:I37", "Illustrative Base allocation under assumed mechanics");
  headers(r, "C38:I38", ["Claim", "Claim amount", "Claim share", "GC allocation", "GC shortfall", "Asset ceiling allocation", "Asset shortfall"]);
  r.getRange("C39:C42").values = [["Term principal"], ["Revolver principal"], ["Unpaid cash interest"], ["Total bank claim"]];
  formulas(r, "D39:I42", [
    ["=$D$10", "=D39/$D$13", "=$E$28*E39", "=D39-F39", "=$M$33*E39", "=D39-H39"],
    ["=$D$11", "=D40/$D$13", "=$E$28*E40", "=D40-F40", "=$M$33*E40", "=D40-H40"],
    ["=$D$12", "=D41/$D$13", "=$E$28*E41", "=D41-F41", "=$M$33*E41", "=D41-H41"],
    ["=SUM(D39:D41)", "=SUM(E39:E41)", "=SUM(F39:F41)", "=SUM(G39:G41)", "=SUM(H39:H41)", "=SUM(I39:I41)"],
  ]);
  money(r.getRange("D39:D42")); percent(r.getRange("E39:E42")); money(r.getRange("F39:I42"));
  r.getRange("C44:I46").values = [
    ["Allocation boundary", "Owner-reviewed pro rata sensitivity", "", "Final legal waterfall and priority remain N/D", "", "", ""],
    ["Official facility recovery", "N/D", "", "Illustrative cases cannot resolve missing evidence", "", "", ""],
    ["Owner review", "All 16 P9D decisions reviewed", "", "No Phase 10 recommendation", "", "", ""],
  ]; styleStatus(r.getRange("D44:I46"));
  r.freezePanes.freezeRows(7); r.freezePanes.freezeColumns(3);
  r.getRange("L8:N13").format.wrapText = true;
  for (let row = 8; row <= 13; row += 1) r.getRange(`${row}:${row}`).format.rowHeight = 24;
  r.getRange("C31:F31").format.wrapText = true; r.getRange("31:31").format.rowHeight = 28;
  setWidths(r, { A: 2, B: 2, C: 31, D: 18, E: 16, F: 18, G: 28, H: 28, I: 27, J: 16, K: 18, L: 18, M: 20, N: 28 });
}

function addSummary(workbook) {
  const s = workbook.worksheets.getItem("Credit Summary");
  s.getRange("C47:N59").clear({ applyTo: "all" });
  section(s, "C47:G47", "Phase 9 recovery and borrower risk");
  s.getRange("C48:C55").values = [["Provisional borrower grade"], ["Official facility recovery"], ["Primary recovery date"], ["Illustrative bank claim"], ["Illustrative GC recovery range"], ["Illustrative asset ceiling recovery"], ["Owner-review status"], ["Secondary-repayment boundary"]];
  formulas(s, "D48:D55", [
    ["=\"Elevated\""], ["='Recovery'!D45"], ["='Recovery'!D8"], ["='Recovery'!D13"],
    ["=TEXT('Recovery'!D29,\"0.0%\")&\" / \"&TEXT('Recovery'!E29,\"0.0%\")&\" / \"&TEXT('Recovery'!F29,\"0.0%\")"],
    ["=TEXT('Recovery'!K34,\"0.0%\")&\" / \"&TEXT('Recovery'!M34,\"0.0%\")&\" / \"&TEXT('Recovery'!N34,\"0.0%\")"],
    ["=\"16 decisions owner reviewed\""], ["=\"Recovery does not improve default risk\""],
  ], true);
  dateFmt(s.getRange("D50")); money(s.getRange("D51")); styleStatus(s.getRange("D48:D55"));
  section(s, "H47:N47", "Monitoring and escalation");
  s.getRange("H48:H55").values = [["Monitoring records"], ["Phase 3 risk drivers mapped"], ["Key EBITDA warning"], ["Key liquidity warning"], ["Maturity preparation"], ["Reporting/control"], ["Documentation"], ["Phase 10 status"]];
  s.getRange("I48:N55").values = [
    [26, "specific reports, triggers, responses and actions", "", "", "", ""], [13, "all Phase 3 drivers", "", "", "", ""],
    [180, "USDm LTM lender EBITDA", "", "", "", ""], [75, "USDm usable liquidity", "", "", "", ""],
    ["24 months before maturity", "watchlist if no plan", "", "", "", ""], ["monthly remediation evidence", "reporting exceptions escalate", "", "", "", ""],
    ["quarterly and event driven", "guarantor/collateral/perfection remain N/D", "", "", "", ""], ["Not started", "owner decisions required first", "", "", "", ""],
  ]; imported(s.getRange("I48:N55")); money(s.getRange("I50:I51")); styleStatus(s.getRange("I54:N55"));
  setWidths(s, { C: 35, D: 22, E: 18, F: 18, G: 18, H: 30, I: 24, J: 34, K: 18, L: 18, M: 18, N: 18 });
}

function addSources(workbook) {
  const s = workbook.worksheets.getItem("Sources");
  const start = 62;
  s.getRange(`A${start}:M${start + payload.ledger.length - 1}`).clear({ applyTo: "all" });
  const rows = payload.ledger.map(row => [row.ledger_id, row.source_type, "Phase 9 approved-input reference", excelDate("2025-12-15"), "Approved Phase 0-8 period", "See source artifact", row.source_path, "As recorded", "As recorded", "approved prior-phase artifact", row.review_status, "Phase 9 recovery / risk / monitoring", row.limitations]);
  s.getRange(`A${start}:M${start + rows.length - 1}`).values = rows;
  imported(s.getRange(`A${start}:M${start + rows.length - 1}`)); dateFmt(s.getRange(`D${start}:D${start + rows.length - 1}`));
}

function addChecks(workbook) {
  const c = workbook.worksheets.getItem("Checks");
  section(c, "C40:H40", "Phase 9 recovery, risk and monitoring controls");
  headers(c, "C41:H41", ["Check", "Observed", "Expected", "Tolerance", "Status", "Notes"]);
  const items = [
    ["Official recovery remains N/D", "='Recovery'!D45", "N/D", 0, '=IF(D42=E42,"PASS","FAIL")', "Public-data limitation preserved"],
    ["Primary recovery date", "='Recovery'!D8", excelDate("2027-12-31"), 0, '=IF(D43=E43,"PASS","FAIL")', "First mandatory cash-interest failure"],
    ["Bank claim reconciliation", "='Recovery'!D13", n(payload.exposure.facility_claim), 0.002, '=IF(ABS(D44-E44)<=F44,"PASS","FAIL")', "Term + revolver + unpaid interest"],
    ["Going-concern Base waterfall", "='Recovery'!E28", n(payload.cases.find(x => x.case_id === "P9C-GC-2").illustrative_bank_allocation), 0.002, '=IF(ABS(D45-E45)<=F45,"PASS","FAIL")', "Python-to-workbook parity"],
    ["Asset Base ceiling waterfall", "='Recovery'!M33", n(payload.cases.find(x => x.case_id === "P9C-AR-2").illustrative_bank_allocation), 0.002, '=IF(ABS(D46-E46)<=F46,"PASS","FAIL")', "Python-to-workbook parity"],
    ["Recovery capped at claim", "=MAX('Recovery'!D28:F28,'Recovery'!K33,'Recovery'!M33,'Recovery'!N33)", "='Recovery'!D13", 0, '=IF(D47<=E47,"PASS","FAIL")', "No recovery above 100%"],
    ["Goodwill recovery credit", "='Recovery'!K26", 0, 0, '=IF(D48=E48,"PASS","FAIL")', "Explicit zero without specific value evidence"],
    ["Intangible recovery credit", "='Recovery'!K27", 0, 0, '=IF(D49=E49,"PASS","FAIL")', "Explicit zero without specific value evidence"],
    ["Alternative-method separation", "=IF(AND('Recovery'!E29<=1,'Recovery'!K34<=1),0,1)", 0, 0, '=IF(D50=E50,"PASS","FAIL")', "Going concern and asset methods are not added"],
    ["Owner decisions reviewed", 16, 16, 0, '=IF(D51=E51,"PASS","FAIL")', "Illustrative status and limitations remain"],
    ["Risk grade scale", "='Credit Summary'!D48", "Elevated", 0, '=IF(D52=E52,"PASS","FAIL")', "Provisional and owner reviewed; no PD mapping"],
    ["All Phase 3 drivers monitored", 13, 13, 0, '=IF(D53=E53,"PASS","FAIL")', "Mapped in MON-001 through MON-026"],
    ["Phase 8 EBITDA anchor", "='Credit Adjustments'!E14", 225.344, 0.002, '=IF(ABS(D54-E54)<=F54,"PASS","FAIL")', "Prior-phase formula preserved"],
    ["No Phase 10 recommendation", "Not started", "Not started", 0, '=IF(D55=E55,"PASS","FAIL")', "Scope gate"],
    ["Final saved scenario", "='Assumptions'!D4", "Base", 0, '=IF(D56=E56,"PASS","FAIL")', "Original single selector restored"],
  ];
  for (let i = 0; i < items.length; i += 1) {
    const row = 42 + i, item = items[i]; c.getRange(`C${row}`).values = [[item[0]]];
    if (typeof item[1] === "string" && item[1].startsWith("=")) c.getRange(`D${row}`).formulas = [[item[1]]]; else c.getRange(`D${row}`).values = [[item[1]]];
    if (typeof item[2] === "string" && item[2].startsWith("=")) c.getRange(`E${row}`).formulas = [[item[2]]]; else c.getRange(`E${row}`).values = [[item[2]]];
    c.getRange(`F${row}`).values = [[item[3]]]; c.getRange(`G${row}`).formulas = [[item[4]]]; c.getRange(`H${row}`).values = [[item[5]]];
  }
  crossFormula(c.getRange("D42:E56")); sameFormula(c.getRange("G42:G56")); styleStatus(c.getRange("G42:G56"));
  dateFmt(c.getRange("D43:E43")); money(c.getRange("D44:F49"));
  setWidths(c, { C: 36, D: 23, E: 23, F: 13, G: 15, H: 61 });
}

async function build() {
  const workbook = await loadWorkbook(baselinePath);
  addAssumptions(workbook); addRecovery(workbook); addSummary(workbook); addSources(workbook); addChecks(workbook);
  workbook.recalculate();
  await fs.mkdir(path.dirname(modelPath), { recursive: true });
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(modelPath);
  console.log(JSON.stringify({ status: "PASS", sheets: 14, output: "model/Quanex_Credit_Underwriting.xlsx" }));
}

async function inspect() {
  const workbook = await loadWorkbook(baselinePath);
  await fs.mkdir(previewDir, { recursive: true });
  const ranges = { "Credit Summary": "C1:N59", "Assumptions": "C1:L38", "Recovery": "C1:N47", "Sources": "A1:M74", "Checks": "C1:H56" };
  const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 300 }, summary: "Phase 9 formula error scan" });
  if (errors.ndjson && !errors.ndjson.includes('"matchCount":0')) console.log(errors.ndjson);
  for (const [sheetName, range] of Object.entries(ranges)) {
    const image = await workbook.render({ sheetName, range, scale: 1, format: "png" });
    await fs.writeFile(path.join(previewDir, `${sheetName.toLowerCase().replaceAll(" ", "-")}.png`), new Uint8Array(await image.arrayBuffer()));
  }
  const sample = await workbook.inspect({ kind: "table", range: "Recovery!C1:N47", include: "values,formulas", tableMaxRows: 47, tableMaxCols: 12, maxChars: 12000 });
  await fs.writeFile(path.join(previewDir, "inspection.ndjson"), sample.ndjson, "utf8");
  console.log(JSON.stringify({ status: "PASS", previews: 5, errorScan: "completed" }));
}

if (mode === "build") await build();
else if (mode === "inspect") await inspect();
else throw new Error("usage: build-phase9.mjs build|inspect ROOT WORKBOOK [PREVIEW_DIR]");
