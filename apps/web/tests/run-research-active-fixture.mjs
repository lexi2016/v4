// Source-only runtime parity: no services, dist copy, package installation, or shared writes.
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const sourceRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const activeRoot = process.env.V4_ACTIVE_SOURCE_ROOT;
const dependencies = process.env.V4_WEB_NODE_MODULES;
if (!activeRoot || !dependencies) throw new Error("Set V4_ACTIVE_SOURCE_ROOT and V4_WEB_NODE_MODULES to existing read-only inputs.");
const activeIdentities = {
  "apps/web/src/views/ResearchView.vue": "589660673c5330f240fb76e5c43c3a7a88bb25b99d9cbe824ba4de889045609e",
  "apps/web/src/api/research_lane.ts": "e65f03bdf789bfb4ba26ecf30c3ae1cbd56a84d3b0aec80f9bd4ecb473eaa750",
  "apps/web/src/api/position25.ts": "d4b6e346f363a4fa38f7bd915bd9150be2fe8aeee5869ce513267ac4a2933403",
  "apps/web/src/api/singleStockRepairSop.ts": "dcdbc74a19cbe93fd5a563abd64a8796e809f0670728872ef043cd875bac14ab",
  "apps/web/src/composables/useResearchLane.ts": "c185614a38c401a9afdf9d392c1e866b3942b7740f870894b120a83c690401ff",
  "apps/web/src/composables/researchFeedPresentation.ts": "6ab145253d6ad1957902c5262ed0c82cc2adb4d58dff09ebc484fed4f76d0e52",
  "apps/web/src/components/research/ResearchStatusStrip.vue": "5066ba418f6502e4ae6eefb2d7ac94221232aab16f187cbe875e33172ad4ac8a",
  "apps/web/src/components/research/ResearchImpactList.vue": "c2248151611747cf2c14f7e07983470cc85a94b3d566e7616ab133f533e7e087",
  "apps/web/src/components/research/ResearchFeedPane.vue": "8980cd832a42b8d9bd353933ae98cb458d3fb13bc28c36e2f0df5892ddf72e4a",
  "apps/web/src/components/research/ResearchFeedCard.vue": "bc4e78f5f7f3557225f2f82d9be0f2fe031016b0aca8606c9f513b07bf221e0d",
  "apps/web/src/components/research/ResearchSourceColumns.vue": "4b6d6ee1344dfcca5ed45df8e60853be099942a1930047f6091b9ded0359fe1c",
  "apps/web/src/components/research/WechatResearchPanel.vue": "4cb44d8e06164d967339c201dca48cabef7aa1b7678c30a107c7ecab1b143592",
  "apps/web/src/api/wechat_research.ts": "d91903d4f39b9d2b95f294c50326caef70071ed3430fe2c7c771d241b6f8570d",
  "apps/web/src/components/research/ResearchContextPane.vue": "1cbcfcc7109e7b1a15d49e64435ba32b67c204f0bf0ea2a797a2a93687afac59",
  "apps/web/src/components/research/ResearchAppendix.vue": "2969a9c32e5a253c7f4165f30f1faa3cf3283ebcb33aae0fb83f1c9b209f4a21",
  "apps/web/src/styles/v3-research-lane.css": "d7b56919209d8551d5fb44789db20246d745b63273a42a60d0b34927be7232e8"
};
const overlays = [
  "apps/web/src/views/ResearchView.vue",
  "apps/web/src/api/research_lane.ts",
  "apps/web/src/composables/useResearchLane.ts",
  "apps/web/src/components/research/ResearchFeedPane.vue",
  "apps/web/src/components/research/ResearchImpactList.vue",
  "apps/web/src/components/research/ResearchStatusStrip.vue",
];
const tests = [
  "apps/web/src/views/ResearchMachineCards.spec.ts",
  "apps/web/src/composables/useResearchLane.spec.ts",
  "apps/web/src/api/research_lane.spec.ts",
];
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const activeSources = Object.entries(activeIdentities).map(([path, expected]) => {
  const bytes = readFileSync(join(activeRoot, path));
  if (sha256(bytes) !== expected) throw new Error(`Active source identity changed: ${path}`);
  return [path, bytes];
});
const fixture = mkdtempSync(join(sourceRoot, ".research-ui-runtime-"));
const put = (path, bytes) => {
  const target = join(fixture, path);
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, bytes);
};
for (const [path, bytes] of activeSources) put(path, bytes);
for (const path of [...overlays, ...tests]) put(path, readFileSync(join(sourceRoot, path)));
const web = join(fixture, "apps/web");
// Real local node_modules directory keeps Vite temporary files inside the fixture.
const localModules = join(web, "node_modules");
mkdirSync(localModules);
for (const entry of readdirSync(dependencies)) {
  if (entry.startsWith(".vite")) continue;
  symlinkSync(join(dependencies, entry), join(localModules, entry));
}
put("apps/web/package.json", '{"type":"module"}');
put("apps/web/vite.config.mjs", `import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";
export default defineConfig({ plugins: [vue()], cacheDir: ".vite", test: { environment: "jsdom" } });`);
const result = spawnSync(process.execPath, [join(dependencies, "vitest/vitest.mjs"), "run", ...(process.argv.length > 2 ? process.argv.slice(2) : tests.map((path) => path.replace("apps/web/", "")))], {
  cwd: web, encoding: "utf8", env: { ...process.env, NO_COLOR: "1" },
});
process.stdout.write(result.stdout || "");
process.stderr.write(result.stderr || "");
const receipt = {
  active_source_files: activeSources.length,
  exact_active_sha256: activeIdentities,
  feature_overlay_sha256: Object.fromEntries(overlays.map((path) => [path, sha256(readFileSync(join(sourceRoot, path)))])),
  source_only_fixture: fixture,
  exit_code: result.status,
  fixture_removed: result.status === 0,
  services_started: false,
  shared_dependencies_written: false,
};
if (result.status === 0) rmSync(fixture, { recursive: true });
console.log(JSON.stringify(receipt, null, 2));
if (result.error) console.error(result.error.message);
process.exit(result.status ?? 1);
