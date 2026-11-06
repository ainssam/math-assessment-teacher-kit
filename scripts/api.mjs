import { spawn } from "node:child_process";

import {
  apiDirectory,
  pythonExecutable,
  requirePythonEnvironment,
  rootDirectory,
} from "./runtime.mjs";

requirePythonEnvironment();

const api = spawn(
  pythonExecutable,
  [
    "-m",
    "uvicorn",
    "app.main:app",
    "--app-dir",
    apiDirectory,
    "--host",
    "127.0.0.1",
    "--port",
    process.env.MATH_ASSESSMENT_API_PORT ?? "8010",
    "--reload",
  ],
  {
    cwd: rootDirectory,
    stdio: "inherit",
    windowsHide: true,
  },
);

function stop() {
  if (!api.killed) {
    api.kill();
  }
}

process.on("SIGINT", stop);
process.on("SIGTERM", stop);
api.on("exit", (code) => process.exit(code ?? 0));
