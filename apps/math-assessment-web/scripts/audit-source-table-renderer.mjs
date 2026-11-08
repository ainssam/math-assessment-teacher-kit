import { DatabaseSync } from "node:sqlite";
import { inflateSync } from "node:zlib";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { JSDOM } from "jsdom";
import { createServer } from "vite";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(scriptDirectory, "..");
const projectRoot = path.resolve(webRoot, "..", "..");
const databasePath = process.env.MATH_ASSESSMENT_DETAIL_DB
  ? path.resolve(projectRoot, process.env.MATH_ASSESSMENT_DETAIL_DB)
  : path.join(
      projectRoot,
      "data",
      "publish",
      "math_assessment_catalog_detail.sqlite",
    );
const shardIndex = Number(process.env.RENDERER_AUDIT_SHARD_INDEX || 0);
const shardCount = Number(process.env.RENDERER_AUDIT_SHARD_COUNT || 1);
if (
  !Number.isInteger(shardIndex)
  || !Number.isInteger(shardCount)
  || shardCount < 1
  || shardIndex < 0
  || shardIndex >= shardCount
) {
  throw new Error("Invalid renderer audit shard configuration");
}
const outputFilename = shardCount > 1
  ? `math_assessment_source_renderer_audit.shard-${shardIndex}.json`
  : "math_assessment_source_renderer_audit.json";
const derivedDirectory = path.join(projectRoot, "data", "derived");
const configuredOutput = process.env.RENDERER_AUDIT_OUTPUT
  ? path.resolve(projectRoot, process.env.RENDERER_AUDIT_OUTPUT)
  : null;
if (configuredOutput && !configuredOutput.startsWith(`${derivedDirectory}${path.sep}`)) {
  throw new Error("RENDERER_AUDIT_OUTPUT must stay inside data/derived");
}
const outputPath = configuredOutput || path.join(derivedDirectory, outputFilename);
const selectedItemIds = (process.env.RENDERER_AUDIT_ITEM_IDS || "")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);
if (selectedItemIds.some((value) => !/^[a-f0-9]{28}$/.test(value))) {
  throw new Error("RENDERER_AUDIT_ITEM_IDS must contain 28-character lowercase hex IDs");
}

const dom = new JSDOM("<!doctype html><html><body></body></html>");
Object.assign(globalThis, {
  DOMParser: dom.window.DOMParser,
  Document: dom.window.Document,
  Element: dom.window.Element,
  HTMLTableElement: dom.window.HTMLTableElement,
  HTMLTableRowElement: dom.window.HTMLTableRowElement,
  HTMLTableCellElement: dom.window.HTMLTableCellElement,
  Node: dom.window.Node,
  NodeFilter: dom.window.NodeFilter,
});

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

const entityDecoder = dom.window.document.createElement("textarea");
function decodeEntities(value) {
  entityDecoder.innerHTML = value;
  return entityDecoder.value;
}

function sourceTextSegments(value) {
  const segments = String(value || "")
    .replace(/<script\b[\s\S]*?<\/script\s*>/gi, "")
    .replace(/<style\b[\s\S]*?<\/style\s*>/gi, "")
    .replace(/<br\s*\/?>/gi, "\n")
    .split(/<[^>]*>/g)
    .map((part) => normalizeText(decodeEntities(part)))
    .filter(Boolean);
  return [...new Set(segments)];
}

function outputText(value) {
  return normalizeText(decodeEntities(
    String(value || "")
      .replace(/<script\b[\s\S]*?<\/script\s*>/gi, "")
      .replace(/<style\b[\s\S]*?<\/style\s*>/gi, "")
      .replace(/<br\s*\/?>/gi, " ")
      .replace(/<[^>]*>/g, " "),
  ));
}

function rowGrade(row) {
  for (const cell of Array.from(row.cells)) {
    const text = normalizeText(cell.textContent);
    if (/^[A-E]$/.test(text)) return text;
  }
  return null;
}

function achievementLevelBreakCount(value) {
  const document = new DOMParser().parseFromString(`<main>${value}</main>`, "text/html");
  const tables = Array.from(document.querySelectorAll("table"));
  let count = 0;
  for (let index = 0; index < tables.length - 1; index += 1) {
    const previousRows = Array.from(tables[index].rows);
    const nextRows = Array.from(tables[index + 1].rows);
    const previousGrades = previousRows.map(rowGrade).filter(Boolean);
    const nextGrades = nextRows.map(rowGrade).filter(Boolean);
    if (
      previousGrades.slice(-3).join("") === "ABC"
      && nextGrades.slice(0, 2).join("") === "DE"
    ) {
      count += 1;
    }
  }
  return count;
}

function renderedTableTopologyIssues(value) {
  const document = new DOMParser().parseFromString(`<main>${value}</main>`, "text/html");
  const issues = [];
  for (const [tableIndex, table] of Array.from(document.querySelectorAll("table")).entries()) {
    const rows = Array.from(table.rows);
    for (const [rowIndex, row] of rows.entries()) {
      for (const [cellIndex, cell] of Array.from(row.cells).entries()) {
        for (const attribute of ["rowspan", "colspan"]) {
          const raw = cell.getAttribute(attribute);
          if (raw === null) continue;
          if (!/^\d+$/.test(raw) || Number(raw) < 1) {
            issues.push({ table_index: tableIndex, row_index: rowIndex, cell_index: cellIndex, attribute, value: raw });
          }
        }
        if (cell.rowSpan > rows.length - rowIndex) {
          issues.push({
            table_index: tableIndex,
            row_index: rowIndex,
            cell_index: cellIndex,
            attribute: "rowspan",
            value: String(cell.rowSpan),
            remaining_rows: rows.length - rowIndex,
          });
        }
      }
    }
  }
  return issues;
}

const reviewItemIds = new Set();

function sample(list, value, limit = 30) {
  reviewItemIds.add(value.item_id);
  if (list.length < limit) list.push(value);
}

const vite = await createServer({
  root: webRoot,
  configFile: false,
  appType: "custom",
  logLevel: "error",
  server: { middlewareMode: true, hmr: false },
});

let database;
try {
  const { segmentSourceTables } = await vite.ssrLoadModule(
    "/app/lib/source-table-segmentation.ts",
  );
  database = new DatabaseSync(databasePath, { readOnly: true });
  const itemFilter = selectedItemIds.length
    ? `AND item_id IN (${selectedItemIds.map((value) => `'${value}'`).join(",")})`
    : "";
  const rows = database.prepare(`
    SELECT item_id, case_id, source_html_zlib, rubric_html_zlib
    FROM assessment_items
    WHERE extraction_status = 'bounded'
      ${itemFilter}
    ORDER BY case_id, item_order
  `).iterate();

  const report = {
    generated_at: new Date().toISOString(),
    database: path.relative(projectRoot, databasePath).replaceAll("\\", "/"),
    scope: selectedItemIds.length
      ? "Selected bounded assessment items rendered through segmentSourceTables"
      : "All bounded assessment items rendered through segmentSourceTables",
    shard_index: shardIndex,
    shard_count: shardCount,
    item_count: 0,
    document_count: 0,
    source_document_count: 0,
    rubric_document_count: 0,
    decode_failure_count: 0,
    render_failure_count: 0,
    source_text_loss_document_count: 0,
    residual_achievement_level_break_count: 0,
    rendered_table_topology_failure_count: 0,
    counters: {
      split_table_count: 0,
      section_count: 0,
      merged_fragment_count: 0,
      reconstructed_cell_count: 0,
      orphan_standard_group_count: 0,
      recovered_note_group_count: 0,
      clamped_rowspan_count: 0,
      clipped_colspan_count: 0,
      grade_continuation_row_count: 0,
      pruned_trailing_column_count: 0,
      normalized_long_header_cell_count: 0,
      wide_table_count: 0,
    },
    samples: {
      decode_failures: [],
      render_failures: [],
      source_text_loss: [],
      residual_achievement_level_breaks: [],
      rendered_table_topology_failures: [],
    },
  };

  const startedAt = performance.now();
  let sourceRowIndex = -1;
  for (const row of rows) {
    sourceRowIndex += 1;
    if (sourceRowIndex % shardCount !== shardIndex) continue;
    report.item_count += 1;
    for (const [kind, blob] of [
      ["source", row.source_html_zlib],
      ["rubric", row.rubric_html_zlib],
    ]) {
      let html;
      try {
        html = inflateSync(Buffer.from(blob)).toString("utf8");
      } catch (error) {
        report.decode_failure_count += 1;
        sample(report.samples.decode_failures, {
          case_id: row.case_id,
          item_id: row.item_id,
          kind,
          error: String(error),
        });
        continue;
      }
      if (!html.trim()) continue;

      report.document_count += 1;
      report[`${kind}_document_count`] += 1;
      try {
        const originalSegments = sourceTextSegments(html);
        const result = segmentSourceTables(html);
        const renderedText = outputText(result.html).replace(/\s+/g, "");
        const missingSegments = originalSegments.filter(
          (segment) => !renderedText.includes(segment.replace(/\s+/g, "")),
        );

        for (const key of Object.keys(report.counters)) {
          const resultKey = key.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
          report.counters[key] += Number(result[resultKey] || 0);
        }

        if (missingSegments.length) {
          report.source_text_loss_document_count += 1;
          sample(report.samples.source_text_loss, {
            case_id: row.case_id,
            item_id: row.item_id,
            kind,
            missing_segments: missingSegments.slice(0, 5),
          });
        }

        const residualBreaks = achievementLevelBreakCount(result.html);
        report.residual_achievement_level_break_count += residualBreaks;
        if (residualBreaks) {
          sample(report.samples.residual_achievement_level_breaks, {
            case_id: row.case_id,
            item_id: row.item_id,
            kind,
            count: residualBreaks,
          });
        }

        const topologyIssues = renderedTableTopologyIssues(result.html);
        if (topologyIssues.length) {
          report.rendered_table_topology_failure_count += 1;
          sample(report.samples.rendered_table_topology_failures, {
            case_id: row.case_id,
            item_id: row.item_id,
            kind,
            issues: topologyIssues.slice(0, 5),
          });
        }
      } catch (error) {
        report.render_failure_count += 1;
        sample(report.samples.render_failures, {
          case_id: row.case_id,
          item_id: row.item_id,
          kind,
          error: String(error),
        });
      }
    }

    if (report.item_count % 1000 === 0) {
      const seconds = ((performance.now() - startedAt) / 1000).toFixed(1);
      console.log(`renderer audit ${report.item_count} items (${seconds}s)`);
    }
  }

  report.elapsed_seconds = Number(((performance.now() - startedAt) / 1000).toFixed(2));
  report.review_item_ids = [...reviewItemIds].sort();
  report.passed = (
    report.decode_failure_count === 0
    && report.render_failure_count === 0
    && report.source_text_loss_document_count === 0
    && report.residual_achievement_level_break_count === 0
    && report.rendered_table_topology_failure_count === 0
  );

  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  console.log(JSON.stringify({
    output: path.relative(projectRoot, outputPath).replaceAll("\\", "/"),
    item_count: report.item_count,
    document_count: report.document_count,
    source_text_loss_document_count: report.source_text_loss_document_count,
    residual_achievement_level_break_count: report.residual_achievement_level_break_count,
    rendered_table_topology_failure_count: report.rendered_table_topology_failure_count,
    passed: report.passed,
    elapsed_seconds: report.elapsed_seconds,
    counters: report.counters,
  }, null, 2));

  if (shardCount === 1 && !report.passed) process.exitCode = 1;
} finally {
  database?.close();
  await vite.close();
  dom.window.close();
}
