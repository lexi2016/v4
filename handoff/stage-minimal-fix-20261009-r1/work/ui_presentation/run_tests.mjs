#!/usr/bin/env node
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const root = dirname(fileURLToPath(import.meta.url));
const { values } = parseArgs({ options: {
  phase: { type: "string", default: "after" },
  out: { type: "string" },
  runtime: { type: "string" },
} });
if (!["before", "after"].includes(values.phase) || !values.out) {
  throw new Error("Usage: node run_tests.mjs --phase before|after --out NEW_DIRECTORY [--runtime VUE_PACKAGE_ROOT]");
}
const phase = values.phase;
const runtime = resolve(values.runtime ?? process.env.STAGE_UI_RUNTIME ?? resolve(root, "../ui_runtime"));
const output = resolve(values.out);
const manifest = JSON.parse(readFileSync(resolve(root, "SOURCE_CHANGES.json"), "utf8"));
const sources = manifest.files.map(entry => {
  const path = resolve(root, phase, entry.relative_path);
  const bytes = readFileSync(path);
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  if (sha256 !== entry[phase].sha256 || bytes.length !== entry[phase].bytes) {
    throw new Error(`Source identity mismatch: ${path}`);
  }
  return { relative_path: entry.relative_path, bytes: bytes.length, sha256 };
});
const requireRuntime = createRequire(resolve(runtime, "package.json"));
const packages = Object.fromEntries(["vue", "@vue/compiler-sfc", "@vue/server-renderer"]
  .map(name => [name, requireRuntime(name + "/package.json").version]));
mkdirSync(dirname(output), { recursive: true });
// Evidence directories are append-only: an existing --out is an error.
mkdirSync(output);
const started_at_utc = new Date().toISOString();
const args = ["--test", "--test-reporter=tap", "tests/presentation.test.mjs"];
const run = spawnSync(process.execPath, args, {
  cwd: root,
  env: { ...process.env, STAGE_UI_PHASE: phase, STAGE_UI_RUNTIME: runtime,
    STAGE_UI_GENERATED_DIR: resolve(output, "generated") },
  encoding: "utf8", maxBuffer: 8 * 1024 * 1024,
});
writeFileSync(resolve(output, "stdout.tap"), run.stdout ?? "");
writeFileSync(resolve(output, "stderr.log"), run.stderr ?? "");
const count = label => {
  const match = (run.stdout ?? "").match(new RegExp(`^# ${label} (\\d+)\\s*$`, "m"));
  return match ? Number(match[1]) : null;
};
const report = {
  scope: "SOURCE_ONLY_VUE_SFC_COMPILE_AND_SSR_NOT_FULL_APP_BUILD_OR_BROWSER_ACCEPTANCE",
  phase, command: [process.execPath, ...args], cwd: root,
  started_at_utc, finished_at_utc: new Date().toISOString(),
  test_clock_scope: "TEST_PROCESS_ONLY_NOT_A_BUSINESS_OR_RECEIPT_TIMESTAMP",
  node: process.version, runtime, packages, sources,
  exit_code: run.status, signal: run.signal, error: run.error?.message ?? null,
  tests: count("tests"), pass: count("pass"), fail: count("fail"),
  skipped: count("skipped"), cancelled: count("cancelled"), todo: count("todo"),
  artifacts: ["stdout.tap", "stderr.log", "generated/compiled-component.js", "generated/runtime-component.js"],
};
writeFileSync(resolve(output, "RESULTS.json"), JSON.stringify(report, null, 2) + "\n");
console.log(JSON.stringify({ phase, exit_code: report.exit_code, tests: report.tests,
  pass: report.pass, fail: report.fail, output }, null, 2));
process.exitCode = run.status ?? 1;
