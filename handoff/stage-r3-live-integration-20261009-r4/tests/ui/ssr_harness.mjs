import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { createRequire, stripTypeScriptTypes } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const phase = process.env.STAGE_UI_PHASE ?? "after";
if (!["before", "after"].includes(phase)) throw new Error("unknown phase");
const runtime = process.env.STAGE_UI_RUNTIME ?? resolve(root, "../ui_runtime");
const requireRuntime = createRequire(resolve(runtime, "package.json"));
export const vue = requireRuntime("vue");
const { parse, compileScript } = requireRuntime("@vue/compiler-sfc");
const ssr = requireRuntime("@vue/server-renderer");
export const sourceRoot = process.env.STAGE_UI_SOURCE_ROOT
  ? resolve(process.env.STAGE_UI_SOURCE_ROOT) : resolve(root, phase, "apps/web/src");
const filename = resolve(sourceRoot, "components/review/StageExecutionEvidencePanel.vue");
const source = readFileSync(filename, "utf8");
const { descriptor, errors } = parse(source, { filename });
if (errors.length) throw new Error(JSON.stringify(errors));
const script = compileScript(descriptor, {
  id: "stage-evidence-fixture", genDefaultAs: "__sfc__", inlineTemplate: true,
  templateOptions: { ssr: true },
});
let executable = stripTypeScriptTypes(script.content, { mode: "strip" });
// Run the real compiler output against the installed Vue runtime. Only the
// static import plumbing is adapted; component logic/template are unchanged.
for (const [specifier, argument] of [["vue", "vue"], ["vue/server-renderer", "ssr"]]) {
  const escaped = specifier.replaceAll("/", "\\/");
  executable = executable.replace(
    new RegExp(`import\\s*\\{([^}]+)\\}\\s*from\\s*[\"']${escaped}[\"'];?`, "g"),
    (_, names) => `const {${names.replace(/\bas\b/g, ":")}} = ${argument};`,
  );
}
if (/^\s*(import|export)\s/m.test(executable)) throw new Error("unhandled compiler import/export");
const component = new Function("vue", "ssr", executable + "\nreturn __sfc__;")(vue, ssr);
if (process.env.STAGE_UI_GENERATED_DIR) {
  mkdirSync(process.env.STAGE_UI_GENERATED_DIR, { recursive: true });
  writeFileSync(resolve(process.env.STAGE_UI_GENERATED_DIR, "compiled-component.js"), script.content);
  writeFileSync(resolve(process.env.STAGE_UI_GENERATED_DIR, "runtime-component.js"), executable);
}

export async function render(evidence) {
  return await ssr.renderToString(vue.createSSRApp(component, { evidence }));
}

export function primary(html) {
  return html.replace(/<details\b[^>]*>[\s\S]*?<\/details>/g, "");
}

export function text(html) {
  return html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}

export function market(html, key) {
  const match = html.match(new RegExp(`<article\\b[^>]*data-market="${key}"[^>]*>([\\s\\S]*?)<\\/article>`));
  if (match) return text(match[1]);
  // Baseline has no data-market attribute. Locate its existing market title
  // so RED failures test user-visible behavior, not a new test hook.
  for (const article of html.matchAll(/<article\b[^>]*>([\s\S]*?)<\/article>/g)) {
    const heading = article[1].match(/<h4\b[^>]*>([\s\S]*?)<\/h4>/);
    if (heading && text(heading[1]).startsWith(key)) return text(article[1]);
  }
  return "";
}

export function base() {
  return {
    status: "SELECTION_REFERENCES_PARTIALLY_BOUND_EXECUTION_UNVERIFIED",
    trade_date: "20261009", stage_id: "STAGE_0925", execution_verified: false, natural_verified: false,
    attempt_mode: "RECOVERY", due_status: "LATE_CATCHUP_REPLAY", declared_status: "PARTIAL_WITH_ROWS",
    recorded_at: null, node_attempt_count: 1, node_outcome: "SETTLED_PARTIAL",
    receipt_history_binding: "OWNER_HISTORY_NOT_RECORDED",
    cannot_confirm: ["NO_INDEPENDENT_RUN_RECEIPT_SHA_BINDING"],
    markets: {
      A_SHARE: { selection_binding: "BOUND_TO_VERIFIED_SELECTION", requested_rows: 216, source_rows: 205,
        observed_rows: null, accepted_rows: null, selected_rows: 10, reasons: [] },
      HK_CONNECT: { status: "CANNOT_CONFIRM", selection_binding: "NO_VERIFIED_SELECTION_BINDING",
        failure_layer: "PRESELECTION_INPUT", requested_rows: null, source_rows: null,
        observed_rows: null, accepted_rows: null, selected_rows: 0,
        reasons: ["HK D1 status must be STRICT_0_2_READY"] },
    },
    selection_results: {
      A_SHARE: { status: "RESULT_AVAILABLE", selected_rows: 10, requested_rows: 216, source_rows: 205,
        missing_quote_rows: 11, quote_coverage_ratio: 0.949074 },
      HK_CONNECT: { status: "NO_VERIFIED_RESULT", selected_rows: null, requested_rows: null,
        source_rows: null, missing_quote_rows: null, quote_coverage_ratio: null },
    },
    selection_artifact_bindings: {},
  };
}

export const versions = Object.fromEntries(["vue", "@vue/compiler-sfc", "@vue/server-renderer"]
  .map(name => [name, requireRuntime(name + "/package.json").version]));
