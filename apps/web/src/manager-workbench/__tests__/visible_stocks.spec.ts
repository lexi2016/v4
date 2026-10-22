import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/vue";
import Workbench from "../Workbench.vue";
import { humanTime } from "../display";
import type { DayData, Phase, SingleDayMappingSummary } from "../types";
import { sampleDay, wrapped } from "./fixtures/sample";

const DATE = "20261022";
const names = ["联想样本", "中芯样本", "华虹样本", "上海复旦样本", "ASM样本"];
function summary(decisions = Array(5).fill("BENEFIT")): SingleDayMappingSummary {
  return { state: "PARTIAL", source_session: "20261021", target_date: DATE, price_session: "20261021",
    counts: { BENEFIT: decisions.filter(x => x === "BENEFIT").length,
      RISK: decisions.filter(x => x === "RISK").length },
    rows: decisions.map((decision, i) => ({ symbol: `HK.${String(i + 1).padStart(5, "0")}`,
      name: names[i], decision, mapping_grade: "A", primary_proxy: "AMD", primary_signed_return_pct: "3.3",
      reasons: ["冻结映射研究"], mapping_paths: [] })),
    catalog_candidates: Array.from({ length: 410 }, (_, i) => ({ symbol: `HK.${10000 + i}`, name: `诊断${i}` }))
  } as unknown as SingleDayMappingSummary;
}
function day(run: string, phase: Phase, mapping?: SingleDayMappingSummary): DayData {
  return sampleDay({ snapshot: { run_id: run, context: { target_date: DATE, market: "HK_CONNECT", phase,
    cutoff: "2026-10-22T04:17:10+08:00" } }, stocks: [],
    recommendation_counts: { US_MAPPING: { selected: 0, watch: 44 } },
    versions: [{ run_id: "intraday", phase: "INTRADAY" }, { run_id: "saved-next", phase: "NEXT_DAY" }],
    us_mapping_summary: mapping ? { source_decision_counts: {}, groups: [], factor_summary: { factor_decision_counts: {}, single_day_mapping: mapping } } : undefined
  } as unknown as Partial<DayData>);
}
function response(data: DayData): Response {
  return new Response(JSON.stringify(wrapped(data)), { status: 200, headers: { "Content-Type": "application/json" } });
}
function install(handler: (url: URL) => Response | Promise<Response>) {
  const spy = vi.fn((input: RequestInfo | URL, _init: RequestInit = {}) => handler(new URL(String(input), window.location.origin)));
  vi.stubGlobal("fetch", spy); return spy;
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
beforeEach(() => { window.history.replaceState(null, "", `?date=${DATE}`); });

describe("visible saved single-day stocks", () => {
  it("shows saved five benefit rows before a closed complete 410-row diagnostic source", async () => {
    install(() => response(day("saved-next", "NEXT_DAY", summary())));
    render(Workbench);
    const benefits = await screen.findByRole("region", { name: "当前版本潜在受益观察名单" });
    expect(within(benefits).getAllByRole("listitem")).toHaveLength(5);
    for (const name of names) expect(benefits.textContent).toContain(name);
    expect(benefits.closest("details")).toBeNull();
    expect(benefits.textContent).toContain("saved-next");
    expect(benefits.textContent).toContain("正式入选 0 只");
    const diagnostic = screen.getByLabelText("完整港股诊断候选来源") as HTMLDetailsElement;
    expect(diagnostic.open).toBe(false);
    expect(benefits.compareDocumentPosition(diagnostic) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(benefits).queryByText(/诊断/)).toBeNull();
    diagnostic.open = true;
    expect(within(diagnostic).getAllByRole("row")).toHaveLength(411);
    expect(screen.getByRole("region", { name: "当前版本下跌风险观察名单" }).textContent).toContain("没有下跌风险观察股票");
  });

  it("keeps zero benefit and risk / unknown categories separate", async () => {
    install(() => response(day("saved-next", "NEXT_DAY", summary(["RISK", "UNASSESSED", "OBSERVATION"]))));
    render(Workbench);
    const benefits = await screen.findByRole("region", { name: "当前版本潜在受益观察名单" });
    expect(within(benefits).queryAllByRole("listitem")).toHaveLength(0);
    expect(benefits.textContent).toContain("潜在受益观察 · 0 只");
    const risk = screen.getByRole("region", { name: "当前版本下跌风险观察名单" });
    expect(within(risk).getAllByRole("listitem")).toHaveLength(1);
    expect(risk.textContent).toContain(names[0]);
    expect(benefits.textContent).not.toContain(names[1]);
  });

  it.each(["", "&phase=INTRADAY&run_id=intraday"])("offers same-date version without auto-switching %s", async suffix => {
    window.history.replaceState(null, "", `?date=${DATE}${suffix}`);
    const spy = install(url => response(url.searchParams.get("run_id") === "saved-next"
      ? day("saved-next", "NEXT_DAY", summary()) : day("intraday", "INTRADAY")));
    render(Workbench);
    const button = await screen.findByRole("button", { name: "查看该保存版的潜在受益 / 风险观察名单" });
    expect(spy).toHaveBeenCalledTimes(2);
    expect(window.location.search).toBe(`?date=${DATE}${suffix}`);
    expect(screen.queryByRole("region", { name: "当前版本潜在受益观察名单" })).toBeNull();
    expect(screen.getByRole("region", { name: "单日映射保存版入口" }).textContent).toContain(humanTime("2026-10-22T04:17:10+08:00"));
    await fireEvent.click(button);
    const benefits = await screen.findByRole("region", { name: "当前版本潜在受益观察名单" });
    expect(benefits.textContent).toContain("saved-next");
    expect(new URLSearchParams(window.location.search).get("run_id")).toBe("saved-next");
    expect(new URLSearchParams(window.location.search).get("phase")).toBe("NEXT_DAY");
    await fireEvent.update(screen.getByLabelText("阶段"), "INTRADAY");
    await screen.findByRole("button", { name: "查看该保存版的潜在受益 / 风险观察名单" });
    expect(screen.queryByRole("region", { name: "当前版本潜在受益观察名单" })).toBeNull();
    expect(spy.mock.calls.every(([, init]) => !init?.method)).toBe(true);
  });

  it("rejects mismatched target date / run during discovery", async () => {
    const invalid = day("wrong-run", "NEXT_DAY", summary());
    invalid.snapshot!.context.target_date = "20261021";
    install(url => response(url.searchParams.get("run_id") ? invalid : day("intraday", "INTRADAY")));
    render(Workbench);
    await screen.findByText(/部分同日保存版读取失败/);
    expect(screen.queryByRole("button", { name: "查看该保存版的潜在受益 / 风险观察名单" })).toBeNull();
    expect(screen.queryByRole("region", { name: "当前版本潜在受益观察名单" })).toBeNull();
  });

  it("ignores late discovery after calendar navigation", async () => {
    let finish: (response: Response) => void = () => {};
    install(url => {
      if (url.searchParams.get("run_id") === "saved-next") return new Promise<Response>(resolve => { finish = resolve; });
      return response(url.pathname.includes("20261023")
        ? { ...day("empty", "INTRADAY"), snapshot: null, versions: [] } : day("intraday", "INTRADAY"));
    });
    render(Workbench);
    await screen.findByText(/正在查找同目标日/);
    const date = screen.getByLabelText("目标港股日") as HTMLInputElement;
    expect(date.type).toBe("date");
    await fireEvent.change(date, { target: { value: "2026-10-23" } });
    finish(response(day("saved-next", "NEXT_DAY", summary())));
    await waitFor(() => expect(new URLSearchParams(window.location.search).get("date")).toBe("20261023"));
    expect(screen.queryByRole("button", { name: "查看该保存版的潜在受益 / 风险观察名单" })).toBeNull();
    expect(screen.queryByText(/同目标日 20261022 已有/)).toBeNull();
  });
});
