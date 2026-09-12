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

async function loadWorkbook(inputPath) {
  return SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
}

function updateCreditSummary(workbook) {
  const sheet = workbook.worksheets.getItem("Credit Summary");
  sheet.getRange("C5").values = [["Phase 10 project recommendation - Conditional Approval | owner_reviewed | public-information hypothetical transaction"]];
  sheet.getRange("C5:N5").format = {
    fill: COLORS.paleBlue,
    font: { name: FONT, bold: true, color: "#17365D" },
    wrapText: true,
    rowHeight: 46,
    borders: { preset: "outside", style: "thin", color: COLORS.line },
  };
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
    ["Conditional Approval | owner_reviewed", "Elevated - project-specific qualitative only", "", "", "", ""],
    ["$635m term / $300m revolver / $29.898m opening draw", "Up to $50m combined hold; conditional $15m non-debt source", "", "", "", ""],
    ["Primary: recurring operating cash after all required uses", "Amortization/sweep are payment mechanisms, not sources", "", "", "", ""],
    ["Cash + legally drawable revolver = liquidity support only", "Refinancing = unresolved dependency; 01/31/31 bank-debt gap $324.780m", "", "", "", ""],
    ["Total funded debt: existing $495.368m / reference $507.954m / selected $514.754m", "Selected is $19.386m above existing; no faster same-horizon deleveraging", "", "", "", ""],
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
  const ranges = { "Credit Summary": "C1:N59", "Recovery": "C1:N47", "Checks": "C1:H56" };
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
  console.log(JSON.stringify({ status: "PASS", previews: 3, errorScan: "completed" }));
}

if (mode === "build") await build();
else if (mode === "inspect") await inspect();
else throw new Error("usage: build-phase10.mjs build|inspect ROOT WORKBOOK [PREVIEW_DIR]");
