import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const packageJson = readFileSync(path.join(root, "package.json"), "utf8");
const runtime = readFileSync(path.join(root, "scripts", "runtime.mjs"), "utf8");
const deployment = readFileSync(path.join(root, "vercel.json"), "utf8");

const failures = [];

if (packageJson.includes("@curriculum-topic-analyzer/web")) {
  failures.push("기본 패키지 명령이 기존 탐구주제 분석기 웹앱을 가리킵니다.");
}
if (!runtime.includes('"math-assessment-web"')) {
  failures.push("개발 실행 경로가 새 수학 수행평가 웹앱을 가리키지 않습니다.");
}
if (deployment.includes('"apps/web/"') || deployment.includes('"services/api/"')) {
  failures.push("배포 설정에 기존 탐구주제 분석기 경로가 남아 있습니다.");
}

const publicDirectory = path.join(root, "apps", "math-assessment-web", "public");
const forbiddenExtensions = new Set([".csv", ".hwp", ".hwpx", ".jsonl", ".pdf", ".sqlite"]);

function inspectPublicFiles(directory) {
  if (!existsSync(directory)) return;
  for (const name of readdirSync(directory)) {
    const target = path.join(directory, name);
    if (statSync(target).isDirectory()) {
      inspectPublicFiles(target);
      continue;
    }
    if (forbiddenExtensions.has(path.extname(name).toLowerCase())) {
      failures.push(`공개 폴더에 원문·대용량 데이터 후보가 있습니다: ${path.relative(root, target)}`);
    }
  }
}

inspectPublicFiles(publicDirectory);

if (failures.length > 0) {
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log("제품 경계 확인 완료: 기본 실행·배포 경로와 공개 데이터 범위가 분리되었습니다.");
