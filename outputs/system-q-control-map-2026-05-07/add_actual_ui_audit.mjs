import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workspaceRoot = path.resolve("../..");
const inputPath = path.join(workspaceRoot, "outputs/system-q-control-map-2026-05-07/System_Q_Button_Control_Map_2026-05-07.xlsx");
const reportPath = path.join(workspaceRoot, "Development/software/SYSTEM_Q_VERIFY_RUNS/actual_ui_20260507_152803/actual_ui_report.json");
const outputPath = path.join(workspaceRoot, "outputs/system-q-control-map-2026-05-07/System_Q_Button_Control_Map_2026-05-07_actual_ui_audited.xlsx");

const report = JSON.parse(await fs.readFile(reportPath, "utf8"));
const input = await FileBlob.load(inputPath);
const wb = await SpreadsheetFile.importXlsx(input);

const stateConfirmed = report.results.filter((r) => r.state_changed).length;
const visualConfirmed = report.results.filter((r) => r.state_changed && r.visual_changed).length;
const noStateChange = report.results.filter((r) => !r.state_changed).length;
const stateOnly = report.results.filter((r) => r.state_changed && !r.visual_changed).length;

const summary = wb.worksheets.add("Actual UI Summary");
summary.showGridLines = false;
const summaryRows = [
  ["Metric", "Count", "Meaning"],
  ["Actual interactions driven", report.total, "Real Windows mouse/key events against the visible System Q Tk window."],
  ["State-confirmed", stateConfirmed, "The expected app state field changed after the real UI interaction."],
  ["State + visual confirmed", visualConfirmed, "The expected state field changed and the before/after screenshot hash changed."],
  ["State-only confirmed", stateOnly, "The state changed, but the captured window did not show a screenshot delta for that control."],
  ["No state change", noStateChange, "The expected state field did not change."],
  ["Evidence folder", report.run_dir, "Each result row has before/after screenshot paths under this folder."],
  ["Important limitation", "Editor visual feedback", "The actual captured interface shows the editor/control area clipped or not repainting for many editor checks; do not treat state-only rows as full visual proof."],
];
summary.getRangeByIndexes(0, 0, summaryRows.length, 3).values = summaryRows;
summary.tables.add(`A1:C${summaryRows.length}`, true, "ActualUiSummary");
summary.getRange("A1:C1").format.fill = "#1F4E78";
summary.getRange("A1:C1").format.font = { color: "#FFFFFF", bold: true };
summary.getRange("A:C").format.wrapText = true;
[230, 190, 720].forEach((w, i) => summary.getRangeByIndexes(0, i, summaryRows.length, 1).format.columnWidthPx = w);
summary.getRangeByIndexes(1, 0, summaryRows.length - 1, 3).format.rowHeightPx = 48;

const audit = wb.worksheets.add("Actual UI Audit");
audit.showGridLines = false;
const headers = [
  "ID",
  "Area",
  "Stage",
  "Label",
  "Action",
  "Classification",
  "State Changed",
  "Visual Changed",
  "State Field",
  "Before Value",
  "After Value",
  "Diff BBox",
  "Before Screenshot",
  "After Screenshot",
  "Notes",
];
const rows = report.results.map((r) => {
  const classification = !r.state_changed
    ? "FAIL - no state change"
    : r.visual_changed
      ? "PASS - state and visual changed"
      : "STATE ONLY - visual not confirmed";
  const note = !r.state_changed
    ? "Actual OS interaction did not change the expected state field."
    : r.visual_changed
      ? "Actual OS interaction changed expected state and screenshot."
      : "Actual OS interaction changed expected state, but screenshot hash/diff did not change for this control.";
  return [
    r.id,
    r.area,
    r.stage,
    r.label,
    r.action,
    classification,
    Boolean(r.state_changed),
    Boolean(r.visual_changed),
    r.state_attr,
    String(r.before_value),
    String(r.after_value),
    r.diff_bbox ? JSON.stringify(r.diff_bbox) : "",
    r.screenshots?.before ?? "",
    r.screenshots?.after ?? "",
    note,
  ];
});
audit.getRangeByIndexes(0, 0, rows.length + 1, headers.length).values = [headers, ...rows];
audit.freezePanes.freezeRows(1);
audit.freezePanes.freezeColumns(5);
audit.tables.add(`A1:O${rows.length + 1}`, true, "ActualUiAudit");
audit.getRange("A1:O1").format.fill = "#7F1D1D";
audit.getRange("A1:O1").format.font = { color: "#FFFFFF", bold: true };
audit.getRange("A:O").format.wrapText = true;
[250, 130, 100, 85, 250, 230, 110, 110, 190, 140, 140, 150, 520, 520, 420].forEach((w, i) => {
  audit.getRangeByIndexes(0, i, rows.length + 1, 1).format.columnWidthPx = w;
});
audit.getRangeByIndexes(1, 0, rows.length, headers.length).format.rowHeightPx = 50;

for (const sheetName of ["Actual UI Summary", "Actual UI Audit"]) {
  const sheet = wb.worksheets.getItem(sheetName);
  sheet.getUsedRange().format.font = { name: "Aptos", size: 10 };
  sheet.getUsedRange().format.verticalAlignment = "top";
}

const check = await wb.inspect({
  kind: "table",
  range: "Actual UI Summary!A1:C8",
  include: "values",
  tableMaxRows: 8,
  tableMaxCols: 3,
});
console.log(check.ndjson);

const auditCheck = await wb.inspect({
  kind: "table",
  range: "Actual UI Audit!A1:O12",
  include: "values",
  tableMaxRows: 12,
  tableMaxCols: 15,
});
console.log(auditCheck.ndjson);

await wb.render({ sheetName: "Actual UI Summary", range: "A1:C8", scale: 1, format: "png" });
await wb.render({ sheetName: "Actual UI Audit", range: "A1:O18", scale: 1, format: "png" });

const output = await SpreadsheetFile.exportXlsx(wb);
await output.save(outputPath);
console.log(outputPath);
