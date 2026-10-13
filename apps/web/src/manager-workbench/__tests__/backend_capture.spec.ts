/// <reference types="vite/client" />
import capturedWire from "./fixtures/backend-http.json?raw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/vue";
import Workbench from "../Workbench.vue";
import { createWorkbenchApi } from "../api";

type Wire = { status: number; body: unknown };
// Captured by the real frozen native A engines -> B store/service -> FastAPI
// TestClient. Material is wholly synthetic, never a production response.
const wires: Record<string, Wire> = JSON.parse(capturedWire);
function reply(wire: Wire): Response {
  return new Response(JSON.stringify(wire.body), { status: wire.status,
    headers: { "Content-Type": "application/json" } });
}
function install(scenario = "full") {
  const spy = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname;
    let key = scenario + "_page_" + (url.searchParams.get("offset") || "0");
    if (url.searchParams.get("decision")) key = scenario + "_filtered";
    if (path.includes('/recommendations/')) key=scenario+'_recommendations_'+path.split('/').pop()+'_'+(url.searchParams.get('decision')?'filtered':url.searchParams.get('offset')||'0');
    if (path.endsWith("20261014")) key = scenario + "_not_run";
    if (path.includes("/stocks/")) key = scenario + "_lane_detail";
    if (path.endsWith("/history")) key = scenario + "_history";
    if (path.includes("/reviews/")) key = scenario + "_review";
    if (path.endsWith("/runs") && init.method === "POST") key = scenario + "_created";
    else if (path.includes("/runs/")) key = scenario + "_job";
    if (!wires[key]) throw new Error("Missing actual capture: " + key);
    return Promise.resolve(reply(wires[key]));
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}
describe("actual frozen Mac backend wire compatibility", () => {
  beforeEach(() => window.history.replaceState(null, "", "?date=20261013"));
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("reads every one of 251 saved lane rows through real B paging, keeping full watch counts", async () => {
    const spy = install();
    render(Workbench);await fireEvent.click(screen.getByRole("button",{name:/超跌推荐/}));
    await screen.findByText("HK.00001");
    const symbols = new Set<string>();
    for (let page = 0; page < 6; page++) {
      document.querySelectorAll(".mwb-symbol").forEach(node => symbols.add(node.textContent || ""));
      expect(document.querySelectorAll('.mwb-counts strong')[1]?.textContent).toBe("251");
      expect(screen.getByText(/服务端筛选后共 251 行/)).toBeTruthy();
      if (page < 5) {
        await fireEvent.click(screen.getByRole("button", { name: "下一页" }));
        await screen.findByText("HK." + String(page * 50 + 51).padStart(5, "0"));
      }
    }
    expect(symbols.size).toBe(251);
    expect(screen.getByText("HK.00251")).toBeTruthy();
    expect(screen.getByRole("button", { name: "下一页" }).hasAttribute("disabled")).toBe(true);
    expect(spy.mock.calls.every(([, init]) => init?.method !== "POST")).toBe(true);
  });

  it("renders five views using native facts, actual evidence, history, Top20 and job wire", async () => {
    const spy = install();render(Workbench);await fireEvent.click(screen.getByRole("button",{name:/超跌推荐/}));
    await screen.findByText("HK.00001");
    expect(screen.getAllByRole("tab")).toHaveLength(5);
    await fireEvent.click(screen.getByRole("button", { name: /查看 HK.00001/ }));
    await screen.findByText("失效条件");
    expect(screen.getAllByText(/volume_ratio/).length).toBeGreaterThan(0);
    expect(screen.getByText(/审计原件：/).closest("details")?.textContent).toContain("evidence_ids");
    expect(screen.getAllByText(/VERIFIED/).length).toBeGreaterThan(0);
    await fireEvent.click(screen.getByRole("tab", { name: "计划历史" }));
    await screen.findByText("LEGACY · 原样历史");
    expect(screen.getByText(/legacy-fixture-run/)).toBeTruthy();
    expect(screen.getByText("NEW · 新计划")).toBeTruthy();
    await fireEvent.click(screen.getByRole("tab", { name: "收盘复盘" }));
    await screen.findByText("HK.00020");
    expect(screen.getAllByRole("row")).toHaveLength(21);
    expect(screen.getAllByText("100%")).toHaveLength(1);
    expect(screen.getByText("0%")).toBeTruthy();
    expect(screen.getByText(/synthetic-full-connect/)).toBeTruthy();
    await fireEvent.click(screen.getByRole("tab", { name: "研究进度" }));
    await fireEvent.click(screen.getByRole("button", { name: "生成研究计划" }));
    await screen.findByText(/执行状态：已完成/);
    expect(screen.getByRole("button", { name: "查看此任务保存版本" })).toBeTruthy();
    const post = spy.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(post![1]!.body as string)).toEqual({target_date:"20261013",phase:"MANUAL"});
  });

  it("partial missing announcement keeps 251 independent oversold watch rows", async () => {
    install("partial");render(Workbench);await fireEvent.click(screen.getByRole("button",{name:/超跌推荐/}));
    await screen.findByText("HK.00001");
    expect(document.querySelectorAll('.mwb-counts strong')[1]?.textContent).toBe("251");
    expect(screen.getByText("READY")).toBeTruthy();
    await fireEvent.click(screen.getByRole("tab", { name: "研究进度" }));
    expect(screen.getByText("输入缺失")).toBeTruthy();
    expect(screen.getByText("完成")).toBeTruthy();
  });

  it("missing inputs are distinct from actual evaluated empty; saved row counts do not invent coverage", async () => {
    install("unknown");const mounted = render(Workbench);await fireEvent.click(screen.getByRole("button",{name:/超跌推荐/}));
    await waitFor(() => expect(document.querySelector('.mwb-counts strong')?.textContent).toBe("0"));
    expect(screen.queryByText("研究已完成且有效空集")).toBeNull();
    expect(screen.getByText("INPUT_MISSING")).toBeTruthy();
    mounted.unmount();cleanup();
    vi.stubGlobal("fetch", vi.fn(async () => reply(wires.empty)));
    render(Workbench);await fireEvent.click(screen.getByRole("button",{name:/超跌推荐/}));
    await screen.findByText("研究已完成且有效空集");
    expect(document.querySelector('.mwb-counts strong')?.textContent).toBe("0");
    expect(screen.getByText("0–0")).toBeTruthy();
  });

  it("filtered zero rows keep full counts and do not claim a global valid empty", async () => {
    install("partial");render(Workbench);await fireEvent.click(screen.getByRole("button",{name:/超跌推荐/}));await screen.findByText("HK.00001");
    await fireEvent.update(screen.getByLabelText("分类"), "NOT_SELECTED");
    await screen.findByText("此筛选或版本暂无名单行");
    expect(document.querySelectorAll('.mwb-counts strong')[1]?.textContent).toBe("251");
    expect(screen.queryByText("研究已完成且有效空集")).toBeNull();
  });

  it.each([
    ["full_404",404,"ENTITY_NOT_FOUND"], ["full_409",409,"NOT_RETRYABLE"],
    ["full_422",422,"DATE_INVALID"], ["full_422_limit",422,"REQUEST_VALIDATION_FAILED"],
    ["full_503",503,"STATE_CHANNEL_UNAVAILABLE"]
  ])("maps actual error capture %s to status and precise server gap", async (key,status,code) => {
    const api = createWorkbenchApi(vi.fn(async () => reply(wires[key])) as unknown as typeof fetch);
    await expect(api.getHistory("20261013")).rejects.toMatchObject({status,message:expect.stringContaining(code)});
  });

  it("rejects unsafe success flags before exposing any rows", async () => {
    const unsafe = {...wires.full_page_0.body as object, production_allowed:true};
    const api=createWorkbenchApi(vi.fn(async()=>reply({status:200,body:unsafe})) as unknown as typeof fetch);
    await expect(api.getDay({date:"20261013"})).rejects.toMatchObject({status:502});
  });
});
