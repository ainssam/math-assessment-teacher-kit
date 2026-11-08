import { DatabaseSync } from "node:sqlite";
import { inflateSync } from "node:zlib";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";
import { createServer } from "vite";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const root = path.resolve(webRoot, "../..");
const databasePath = path.resolve(root, process.env.MATH_ASSESSMENT_DETAIL_DB);
const output = path.resolve(root, process.env.TABLE_GRID_OUTPUT || "data/derived/table-grid.json");
if (!output.startsWith(path.join(root, "data", "derived") + path.sep)) throw Error("Unsafe output");
const ids = (process.env.RENDERER_AUDIT_ITEM_IDS || "").split(",").filter(Boolean);
if (ids.some((id) => !/^[0-9a-f]{28}$/.test(id))) throw Error("Invalid item ID");
const dom = new JSDOM("<!doctype html><html><body></body></html>");
for (const key of ["DOMParser", "Document", "Element", "HTMLTableElement", "HTMLTableRowElement", "HTMLTableCellElement", "Node", "NodeFilter"]) globalThis[key] = dom.window[key];
const vite = await createServer({ root: webRoot, configFile: false, appType: "custom", logLevel: "error", server: { middlewareMode: true, hmr: false } });
const db = new DatabaseSync(databasePath, { readOnly: true });
const findings = [];
let documents = 0;
try {
  const { segmentSourceTables } = await vite.ssrLoadModule("/app/lib/source-table-segmentation.ts");
  const rows = db.prepare(`SELECT i.item_id,i.case_id,c.school_name,c.subject,i.title,i.source_html_zlib,i.rubric_html_zlib
    FROM assessment_items i JOIN cases c USING(case_id) WHERE i.extraction_status='bounded'
    ${ids.length ? `AND i.item_id IN (${ids.map((id) => `'${id}'`).join(",")})` : ""}`).iterate();
  for (const item of rows) {
    for (const part of ["source", "rubric"]) {
      const source = inflateSync(Buffer.from(item[part + "_html_zlib"])).toString("utf8");
      if (!source.trim()) continue;
      documents++;
      const rendered = segmentSourceTables(source).html;
      const document = new DOMParser().parseFromString(rendered, "text/html");
      for (const [tableIndex, table] of Array.from(document.querySelectorAll("table")).entries()) {
        const tableRows = Array.from(table.rows);
        const grid = Array.from({ length: tableRows.length }, () => []);
        const overlaps = [];
        for (const [r, row] of tableRows.entries()) {
          let c = 0;
          for (const cell of Array.from(row.cells)) {
            while (grid[r][c]) c++;
            for (let rr = r; rr < Math.min(r + cell.rowSpan, grid.length); rr++) {
              for (let cc = c; cc < c + cell.colSpan; cc++) {
                if (grid[rr][cc]) overlaps.push([rr, cc]);
                grid[rr][cc] = true;
              }
            }
            c += cell.colSpan;
          }
        }
        const width = Math.max(0, ...grid.map((row) => row.length));
        const incomplete = grid.map((row, r) => ({ row: r, holes: Array.from({ length: width }, (_, c) => !row[c]).filter(Boolean).length })).filter((row) => row.holes);
        if (!overlaps.length && (!incomplete.length || tableRows.length < 3)) continue;
        findings.push({ item_id: item.item_id, case_id: item.case_id, school_name: item.school_name, subject: item.subject,
          title: item.title, part, table_index: tableIndex, row_count: grid.length, column_count: width,
          overlapping_slots: overlaps, incomplete_rows: incomplete,
          row_examples: tableRows.slice(0, 6).map((row) => Array.from(row.cells).map((cell) => ({ text: cell.textContent.replace(/\s+/g," ").trim().slice(0,100), colspan: cell.colSpan, rowspan: cell.rowSpan }))),
        });
      }
      if (documents % 2000 === 0) console.log(`grid audit ${documents} documents`);
    }
  }
  await mkdir(path.dirname(output), { recursive: true });
  const report = { documents, finding_tables: findings.length, overlap_tables: findings.filter((f) => f.overlapping_slots.length).length, item_count: new Set(findings.map((f) => f.item_id)).size, findings,
    interpretation: "Ragged rows require original-table comparison; overlap is a geometry defect. No cell text was changed." };
  await writeFile(output, JSON.stringify(report, null, 2) + "\n");
  console.log(JSON.stringify({ documents, finding_tables: report.finding_tables, overlap_tables: report.overlap_tables, item_count: report.item_count }));
} finally { db.close(); await vite.close(); dom.window.close(); }
