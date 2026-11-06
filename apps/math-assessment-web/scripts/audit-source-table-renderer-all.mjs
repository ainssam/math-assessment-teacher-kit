import { spawn } from "node:child_process";
import { readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDirectory, "..", "..", "..");
const workerPath = path.join(scriptDirectory, "audit-source-table-renderer.mjs");
const outputDirectory = path.join(projectRoot, "data", "derived");
const outputPath = path.join(outputDirectory, "math_assessment_source_renderer_audit.json");
const shardCount = Math.max(1, Math.min(8, Number(process.env.RENDERER_AUDIT_WORKERS || 4)));

function runShard(shardIndex) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [workerPath], {
      cwd: projectRoot,
      env: {
        ...process.env,
        RENDERER_AUDIT_SHARD_INDEX: String(shardIndex),
        RENDERER_AUDIT_SHARD_COUNT: String(shardCount),
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    child.stdout.on("data", (chunk) => process.stdout.write(`[${shardIndex + 1}/${shardCount}] ${chunk}`));
    child.stderr.on("data", (chunk) => process.stderr.write(`[${shardIndex + 1}/${shardCount}] ${chunk}`));
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`Renderer audit shard ${shardIndex} exited with code ${code}`));
    });
  });
}

await Promise.all(Array.from({ length: shardCount }, (_, index) => runShard(index)));

const shardReports = [];
for (let index = 0; index < shardCount; index += 1) {
  const shardPath = path.join(
    outputDirectory,
    `math_assessment_source_renderer_audit.shard-${index}.json`,
  );
  shardReports.push(JSON.parse(await readFile(shardPath, "utf8")));
}

const first = shardReports[0];
const report = {
  generated_at: new Date().toISOString(),
  database: first.database,
  scope: first.scope,
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
  counters: Object.fromEntries(Object.keys(first.counters).map((key) => [key, 0])),
  samples: Object.fromEntries(Object.keys(first.samples).map((key) => [key, []])),
  shard_elapsed_seconds: shardReports.map((shard) => shard.elapsed_seconds),
};

const summedKeys = [
  "item_count",
  "document_count",
  "source_document_count",
  "rubric_document_count",
  "decode_failure_count",
  "render_failure_count",
  "source_text_loss_document_count",
  "residual_achievement_level_break_count",
  "rendered_table_topology_failure_count",
];
for (const shard of shardReports) {
  for (const key of summedKeys) report[key] += Number(shard[key] || 0);
  for (const key of Object.keys(report.counters)) {
    report.counters[key] += Number(shard.counters[key] || 0);
  }
  for (const key of Object.keys(report.samples)) {
    report.samples[key].push(...(shard.samples[key] || []));
    report.samples[key] = report.samples[key].slice(0, 30);
  }
}
report.passed = (
  report.decode_failure_count === 0
  && report.render_failure_count === 0
  && report.source_text_loss_document_count === 0
  && report.residual_achievement_level_break_count === 0
  && report.rendered_table_topology_failure_count === 0
);

await writeFile(outputPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
for (let index = 0; index < shardCount; index += 1) {
  await rm(
    path.join(outputDirectory, `math_assessment_source_renderer_audit.shard-${index}.json`),
    { force: true },
  );
}

console.log(JSON.stringify({
  output: path.relative(projectRoot, outputPath).replaceAll("\\", "/"),
  item_count: report.item_count,
  document_count: report.document_count,
  source_text_loss_document_count: report.source_text_loss_document_count,
  residual_achievement_level_break_count: report.residual_achievement_level_break_count,
  rendered_table_topology_failure_count: report.rendered_table_topology_failure_count,
  passed: report.passed,
  counters: report.counters,
}, null, 2));

if (!report.passed) process.exitCode = 1;
