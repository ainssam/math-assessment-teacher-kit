import { spawnSync } from "node:child_process";
import path from "node:path";

import {
  apiDirectory,
  pythonExecutable,
  requirePythonEnvironment,
  rootDirectory,
} from "./runtime.mjs";

requirePythonEnvironment();

const apiPythonPath = apiDirectory;
const inheritedPythonPath = process.env.PYTHONPATH;
const pythonEnvironment = {
  ...process.env,
  PYTHONPATH: inheritedPythonPath
    ? `${apiPythonPath}${path.delimiter}${inheritedPythonPath}`
    : apiPythonPath,
};

const result = spawnSync(pythonExecutable, process.argv.slice(2), {
  cwd: rootDirectory,
  env: pythonEnvironment,
  stdio: "inherit",
  windowsHide: true,
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}

process.exit(result.status ?? 1);
