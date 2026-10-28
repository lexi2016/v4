import { afterEach, expect, it, vi } from "vitest";
import { readCollection, startCollection } from "./manualCollection";

afterEach(() => vi.unstubAllGlobals());

it("posts only the selected fixed identity", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ job_id: "a".repeat(32), trade_date: "20261020" }) });
  vi.stubGlobal("fetch", fetchMock);
  await startCollection({ date: "20261020", target: "HK_STAGE", stage_id: "STAGE_1545_1555" });
  expect(fetchMock).toHaveBeenCalledWith("/api/v3/manual-collection", expect.objectContaining({
    method: "POST", body: JSON.stringify({ date: "20261020", target: "HK_STAGE", stage_id: "STAGE_1545_1555" }),
  }));
});

it("shows the server's concrete refusal", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => ({ detail: { message: "窗口已结束" } }) }));
  await expect(startCollection({ date: "20261020", target: "HK_CLOSE" })).rejects.toThrow("窗口已结束");
});

it("refuses path-shaped job ids without a request", async () => {
  const mock = vi.fn(); vi.stubGlobal("fetch", mock);
  await expect(readCollection("../../other")).rejects.toThrow("标识无效");
  expect(mock).not.toHaveBeenCalled();
});
