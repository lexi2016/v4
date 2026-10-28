import { cleanup, fireEvent, render, screen } from "@testing-library/vue";
import { flushPromises } from "@vue/test-utils";
import { afterEach, expect, it, vi } from "vitest";
import ManualCollectionControls from "./ManualCollectionControls.vue";

const id = "a".repeat(32);
const job = (status = "READY", changes = {}) => ({ job_id: id, trade_date: "20261020", target: "HK_CLOSE", stage_id: null,
  status, step: "读取 / 生成收盘复盘", message: "当前结果", cannot_confirm: [], result: {}, ...changes });
const response = (value: unknown) => ({ ok: true, json: async () => value });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it("a click posts, shows result, and emits only the completed identity", async () => {
  const fetchMock = vi.fn().mockResolvedValue(response(job("PARTIAL", {
    message: "收盘数据已取得，复盘仍有缺口。", cannot_confirm: ["MISSING_STAGE"],
    result: { same_date_row_count: 698, universe_count: 698, review_status: "MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE" },
  })));
  vi.stubGlobal("fetch", fetchMock);
  const view = render(ManualCollectionControls, { props: { date: "20261020", target: "HK_CLOSE" } });
  await fireEvent.click(screen.getByRole("button", { name: "补采集" })); await flushPromises();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("status").textContent).toContain("仍有缺口");
  expect(screen.getByText(/收盘覆盖/).textContent).toContain("698 / 698");
  expect(view.emitted().completed).toHaveLength(1);
});

it("double click cannot start another job while pending", async () => {
  let release!: (value: unknown) => void;
  const fetchMock = vi.fn().mockReturnValue(new Promise((resolve) => { release = resolve; }));
  vi.stubGlobal("fetch", fetchMock);
  render(ManualCollectionControls, { props: { date: "20261020", target: "HK_CLOSE" } });
  const button = screen.getByRole("button", { name: "补采集" });
  await fireEvent.click(button); await fireEvent.click(button);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  release(response(job())); await flushPromises();
});

it("changing date discards a late result and never refreshes another date", async () => {
  let release!: (value: unknown) => void;
  vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise((resolve) => { release = resolve; })));
  const view = render(ManualCollectionControls, { props: { date: "20261020", target: "HK_CLOSE" } });
  await fireEvent.click(screen.getByRole("button", { name: "补采集" }));
  await view.rerender({ date: "20261016" });
  release(response(job())); await flushPromises();
  expect(view.emitted().completed).toBeUndefined();
  expect(screen.queryByRole("status")).toBeNull();
});

it("stops after twenty reads and offers a manual progress check", async () => {
  vi.useFakeTimers();
  const fetchMock = vi.fn().mockResolvedValue(response(job("RUNNING")));
  vi.stubGlobal("fetch", fetchMock);
  render(ManualCollectionControls, { props: { date: "20261020", target: "HK_CLOSE" } });
  await fireEvent.click(screen.getByRole("button", { name: "补采集" })); await flushPromises();
  for (let n = 0; n < 20; n += 1) { await vi.advanceTimersByTimeAsync(1500); await flushPromises(); }
  expect(fetchMock).toHaveBeenCalledTimes(21);
  expect(screen.getByText(/已停止自动查询/)).toBeTruthy();
  await vi.advanceTimersByTimeAsync(60000);
  expect(fetchMock).toHaveBeenCalledTimes(21);
});

it("unsupported stages have no executable button", () => {
  const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
  render(ManualCollectionControls, { props: { date: "20261020", target: "HK_STAGE", stageId: "STAGE_0940_0945" } });
  expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/该阶段尚未接入/)).toBeTruthy();
  expect(fetchMock).not.toHaveBeenCalled();
});

it("a failed stage displays the exact reason and does not emit success", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(job("CANNOT_CONFIRM", {
    target: "HK_STAGE", stage_id: "STAGE_1545_1555", message: "原窗口已结束。",
    cannot_confirm: ["HK_STAGE8_EXACT_RTDATA_REPLAY_UNAVAILABLE"],
  }))));
  const view = render(ManualCollectionControls, { props: { date: "20261020", target: "HK_STAGE", stageId: "STAGE_1545_1555" } });
  await fireEvent.click(screen.getByRole("button", { name: "补采集" })); await flushPromises();
  expect(screen.getByRole("status").textContent).toContain("未确认补齐");
  expect(screen.getByText(/HK_STAGE8_EXACT_RTDATA/)).toBeTruthy();
  expect(view.emitted().completed).toBeUndefined();
});

it("rejects a mismatching result identity", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(job("READY", { trade_date: "20261016" }))));
  const view = render(ManualCollectionControls, { props: { date: "20261020", target: "HK_CLOSE" } });
  await fireEvent.click(screen.getByRole("button", { name: "补采集" })); await flushPromises();
  expect(screen.getByRole("alert").textContent).toContain("与请求不一致");
  expect(view.emitted().completed).toBeUndefined();
});
