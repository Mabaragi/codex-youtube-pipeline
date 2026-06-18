import { spawn } from "node:child_process";
import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const standaloneRoot = join(root, ".next", "standalone", "ops-ui");
const serverPath = join(standaloneRoot, "server.js");

if (!existsSync(serverPath)) {
  throw new Error("Standalone build is missing. Run `pnpm build` first.");
}

copyIfExists(join(root, "public"), join(standaloneRoot, "public"));
copyIfExists(join(root, ".next", "static"), join(standaloneRoot, ".next", "static"));

const child = spawn(process.execPath, [serverPath], {
  cwd: standaloneRoot,
  env: process.env,
  stdio: "inherit",
});

child.on("exit", (code) => {
  process.exit(code ?? 0);
});

function copyIfExists(source, target) {
  if (!existsSync(source)) {
    return;
  }
  mkdirSync(dirname(target), { recursive: true });
  cpSync(source, target, { force: true, recursive: true });
}
