import { opendir, readFile, rm, unlink, writeFile } from "node:fs/promises";
import { resolve, sep } from "node:path";

const buildDirectory = resolve(process.cwd(), ".next");
const expectedSegment = `${sep}apps${sep}math-assessment-web${sep}.next`;

if (!buildDirectory.endsWith(expectedSegment)) {
  throw new Error(`Refusing to edit an unexpected build directory: ${buildDirectory}`);
}

let removedMaps = 0;
let cleanedReferences = 0;

async function walk(directory) {
  const entries = await opendir(directory);
  for await (const entry of entries) {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) {
      await walk(path);
      continue;
    }
    if (!entry.isFile()) continue;
    if (entry.name.endsWith(".map")) {
      await unlink(path);
      removedMaps += 1;
      continue;
    }
    if (!/\.(?:js|mjs|css)$/.test(entry.name)) continue;
    const original = await readFile(path, "utf8");
    const cleaned = original.replace(/\r?\n?\/\/[#@]\s*sourceMappingURL=.*?(?=\r?\n|$)/g, "");
    if (cleaned !== original) {
      await writeFile(path, cleaned, "utf8");
      cleanedReferences += 1;
    }
  }
}

await walk(buildDirectory);
const typeDirectory = resolve(buildDirectory, "types");
await rm(typeDirectory, { recursive: true, force: true });
const devDirectory = resolve(buildDirectory, "dev");
await rm(devDirectory, { recursive: true, force: true });
console.log(`Protection artifacts removed: maps=${removedMaps}, references=${cleanedReferences}, build_types=1, dev_artifacts=1`);
