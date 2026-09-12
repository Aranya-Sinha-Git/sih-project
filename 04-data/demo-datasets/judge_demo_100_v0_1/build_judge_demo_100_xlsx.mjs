import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const rootDir = path.dirname(fileURLToPath(import.meta.url));
const outputDir = path.join(rootDir, "outputs", "judge_demo_100_20260912");
const csvPath = path.join(rootDir, "judge_demo_100.csv");
const xlsxPath = path.join(outputDir, "judge_demo_100.xlsx");
const csvText = await fs.readFile(csvPath, "utf8");
const workbook = await Workbook.fromCSV(csvText, { sheetName: "Judge Demo 100" });
const sheet = workbook.worksheets.getItem("Judge Demo 100");

const dateValues = csvText.trimEnd().split(/\r?\n/).slice(1).map((line) => {
  const fields = line.split(",");
  return [new Date(`${fields[1].replaceAll('"', "")}T00:00:00Z`)];
});
sheet.getRange("B2:B101").values = dateValues;
sheet.showGridLines = false;
sheet.getRange("A1:G101").format.font = { name: "Aptos", size: 10, color: "#1F2937" };
sheet.getRange("A1:G1").format = {
  fill: "#17365D",
  font: { name: "Aptos", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  borders: { preset: "outside", style: "thin", color: "#17365D" },
};
sheet.getRange("A2:G101").format.verticalAlignment = "top";
sheet.getRange("B2:B101").format.numberFormat = "yyyy-mm-dd";
sheet.getRange("F2:F101").format.wrapText = true;
sheet.getRange("A2:G101").format.borders = {
  insideHorizontal: { style: "thin", color: "#E5E7EB" },
  bottom: { style: "thin", color: "#CBD5E1" },
};
sheet.getRange("A1:A101").format.columnWidth = 17;
sheet.getRange("B1:B101").format.columnWidth = 13;
sheet.getRange("C1:C101").format.columnWidth = 24;
sheet.getRange("D1:D101").format.columnWidth = 21;
sheet.getRange("E1:E101").format.columnWidth = 18;
sheet.getRange("F1:F101").format.columnWidth = 78;
sheet.getRange("G1:G101").format.columnWidth = 31;
sheet.getRange("A1:G1").format.rowHeight = 25;
sheet.getRange("A2:G101").format.rowHeight = 96;
sheet.freezePanes.freezeRows(1);
sheet.freezePanes.freezeColumns(2);
const table = sheet.tables.add("A1:G101", true, "JudgeDemo100Reports");
table.style = "TableStyleMedium2";
table.showBandedRows = true;
table.showFilterButton = true;

workbook.recalculate();
const inspect = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 5000,
  tableMaxRows: 4,
  tableMaxCols: 7,
  tableMaxCellChars: 90,
});
console.log(inspect.ndjson ?? inspect);
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});
console.log(errors.ndjson ?? errors);
const preview = await workbook.render({ sheetName: "Judge Demo 100", range: "A1:G18", scale: 1, format: "png" });
const previewPath = path.join(os.tmpdir(), "judge_demo_100_preview.png");
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(xlsxPath);
console.log(JSON.stringify({ xlsxPath, previewPath, rows: 100, columns: 7 }));
