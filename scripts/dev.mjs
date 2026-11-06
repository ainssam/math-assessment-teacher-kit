import { spawn } from "node:child_process";

import {
  requirePythonEnvironment,
  rootDirectory,
  webDirectory,
  workspaceNodeModule,
} from "./runtime.mjs";

requirePythonEnvironment();

const api = spawn(process.execPath, ["scripts/api.mjs"], {
  cwd: rootDirectory,
  stdio: "inherit",
  windowsHide: true,
});
const web = spawn(
  process.execPath,
  [
    workspaceNodeModule("next", "dist", "bin", "next"),
    "dev",
    "-p",
    process.env.MATH_ASSESSMENT_WEB_PORT ?? "3100",
  ],
  {
    cwd: webDirectory,
    stdio: "inherit",
    windowsHide: true,
  },
);

const children = [api, web];
let stopping = false;

function stop(exitCode = 0) {
  if (stopping) {
    return;
  }
  stopping = true;
  for (const child of children) {
    if (!child.killed) {
      child.kill();
    }
  }
  setTimeout(() => process.exit(exitCode), 250);
}

process.on("SIGINT", () => stop(0));
process.on("SIGTERM", () => stop(0));

for (const child of children) {
  child.on("error", (error) => {
    console.error(error.message);
    stop(1);
  });
  child.on("exit", (code) => {
    if (!stopping && code !== 0) {
      stop(code ?? 1);
    }
  });
}
