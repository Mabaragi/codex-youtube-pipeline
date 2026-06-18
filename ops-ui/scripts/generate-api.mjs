import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const appRoot = resolve(scriptDir, "..");

const result = spawnSync(
  "pnpm",
  [
    "exec",
    "openapi-typescript",
    "openapi/codex-api.openapi.json",
    "-o",
    "src/generated/codex-api.ts",
  ],
  {
    cwd: appRoot,
    stdio: "inherit",
    shell: process.platform === "win32",
  },
);

process.exit(result.status ?? 1);
