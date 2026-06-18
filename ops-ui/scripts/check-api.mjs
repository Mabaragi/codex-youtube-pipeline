import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const appRoot = resolve(scriptDir, "..");
const repoRoot = resolve(appRoot, "..");

function run(command, args, cwd) {
  const result = spawnSync(command, args, {
    cwd,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

run("pnpm", ["api:export"], appRoot);
run("pnpm", ["api:generate"], appRoot);
run(
  "git",
  [
    "diff",
    "--exit-code",
    "--",
    "ops-ui/openapi/codex-api.openapi.json",
    "ops-ui/src/generated/codex-api.ts",
  ],
  repoRoot,
);
