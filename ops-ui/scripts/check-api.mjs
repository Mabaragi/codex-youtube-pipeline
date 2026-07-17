import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const appRoot = resolve(scriptDir, "..");
const trackedOutputs = [
  resolve(appRoot, "openapi/codex-api.openapi.json"),
  resolve(appRoot, "src/generated/codex-api.ts"),
];

function fingerprints() {
  return trackedOutputs.map((path) => createHash("sha256").update(readFileSync(path)).digest("hex"));
}

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

const before = fingerprints();
run("pnpm", ["api:export"], appRoot);
run("pnpm", ["api:generate"], appRoot);
const after = fingerprints();
if (before.some((hash, index) => hash !== after[index])) {
  console.error("OpenAPI outputs were stale. Regenerated files are now present; review and rerun api:check.");
  process.exit(1);
}
