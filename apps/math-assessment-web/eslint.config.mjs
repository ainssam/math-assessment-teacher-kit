import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";

export default defineConfig([
  ...nextVitals,
  globalIgnores([
    ".next/**",
    ".next-*-audit-backup/**",
    ".dorms-check/**",
    "coverage/**",
    "next-env.d.ts",
  ]),
]);
