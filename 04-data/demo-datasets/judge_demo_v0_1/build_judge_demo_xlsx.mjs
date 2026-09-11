import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = path.dirname(fileURLToPath(import.meta.url));
const csvPath = path.join(outputDir, "judge_demo_500.csv");
const xlsxPath = path.join(outputDir, "judge_demo_500.xlsx");
const csvText = await fs.readFile(csvPath, "utf8");
const workbook = await Workbook.fromCSV(csvText, { sheetName: "Judge Demo Reports" });
const sheet = workbook.worksheets.getItem("Judge Demo Reports");

const dateValues = csvText.trimEnd().split(/\r?\n/).slice(1).map((line) => {
  const fields = line.split(",");
  return [new Date(`${fields[1].replaceAll('"', "")}T00:00:00Z`)];
});
sheet.getRange("B2:B501").values = dateValues;
sheet.getRange("A1:G501").format.font = { name: "Aptos", size: 10 };
sheet.getRange("A1:G1").format = {
  fill: "#17365D",
  font: { name: "Aptos", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
sheet.getRange("A2:G501").format.verticalAlignment = "top";
sheet.getRange("B2:B501").format.numberFormat = "yyyy-mm-dd";
sheet.getRange("F2:F501").format.wrapText = true;
sheet.getRange("A1:G501").format.borders = {
  style: "continuous",
  color: "#D9E2F3",
};
sheet.getRange("A1:A501").format.columnWidth = 17;
sheet.getRange("B1:B501").format.columnWidth = 13;
sheet.getRange("C1:C501").format.columnWidth = 22;
sheet.getRange("D1:D501").format.columnWidth = 21;
sheet.getRange("E1:E501").format.columnWidth = 18;
sheet.getRange("F1:F501").format.columnWidth = 78;
sheet.getRange("G1:G501").format.columnWidth = 29;
sheet.getRange("A1:G1").format.rowHeight = 24;
sheet.getRange("A2:G501").format.rowHeight = 48;
sheet.freezePanes.freezeRows(1);
sheet.tables.add("A1:G501", true, "JudgeDemoReports");

workbook.recalculate();
const inspect = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 5000,
  tableMaxRows: 3,
  tableMaxCols: 7,
  tableMaxCellChars: 80,
});
console.log(inspect.ndjson ?? inspect);
const preview = await workbook.render({ sheetName: "Judge Demo Reports", autoCrop: "all", scale: 0.25, format: "png" });
const previewPath = path.join(os.tmpdir(), "judge_demo_500_preview.png");
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(xlsxPath);
console.log(JSON.stringify({ xlsxPath, previewPath, rows: 500, columns: 7 }));
