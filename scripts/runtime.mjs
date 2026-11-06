import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const rootDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const webDirectory = path.join(rootDirectory, "apps", "math-assessment-web");
export const apiDirectory = path.join(rootDirectory, "services", "math-assessment-api");

const pythonRelativePath =
  process.platform === "win32"
    ? path.join(".venv", "Scripts", "python.exe")
    : path.join(".venv", "bin", "python");

export const pythonExecutable = path.join(rootDirectory, pythonRelativePath);

export function requirePythonEnvironment() {
  if (existsSync(pythonExecutable)) {
    return;
  }

  console.error("Python 가상환경을 찾지 못했습니다.");
  console.error("README의 '처음 한 번만 실행' 단계를 먼저 진행해 주세요.");
  process.exit(1);
}

export function workspaceNodeModule(...segments) {
  return path.join(webDirectory, "node_modules", ...segments);
}
