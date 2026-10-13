import { describe, expect, it, vi } from "vitest";
import { ApiError, createWorkbenchApi } from "../api";
import { SCHEMA_VERSION } from "../types";
import { sampleDay, wrapped } from "./fixtures/sample";

function reply(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
}
describe("only the B manager-workbench API is used", () => {
  it("reads saved day with bounded server pagination and no compute POST", async () => {
    const transport = vi.fn(async () => reply(wrapped(sampleDay()))) as unknown as typeof fetch;
    const api = createWorkbenchApi(transport);
    const result = await api.getDay({ date: "20261013", phase: "PREOPEN", offset: 200, limit: 50,
      decision: "UNASSESSED", q: "HK.01234" });
    expect(result.data?.counts.unassessed).toBeNull();
    const args = (transport as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(args[0]).toContain("/api/v4/manager-workbench/days/20261013?");
    expect(args[0]).toContain("offset=200");
    expect(args[0]).toContain("decision=UNASSESSED");
    expect(args[1].method).toBeUndefined();
    expect(args[1].cache).toBe("no-store");
  });
  it("rejects unsafe page arguments before network access", async () => {
    const transport = vi.fn() as unknown as typeof fetch;
    const api = createWorkbenchApi(transport);
    await expect(api.getDay({ date: "20261013", limit: 201 })).rejects.toMatchObject({ status: 422 });
    await expect(api.getDay({ date: "20260231" })).rejects.toMatchObject({ status: 422 });
    expect(transport).not.toHaveBeenCalled();
  });
  it("returns NOT_RUN 200 with null data instead of synthesizing empty results", async () => {
    const api = createWorkbenchApi(vi.fn(async () => reply(wrapped(null, "NOT_RUN"))) as unknown as typeof fetch);
    const result = await api.getDay({ date: "20261013" });
    expect(result.state).toBe("NOT_RUN");
    expect(result.data).toBeNull();
  });
  it("distinguishes 409 retry conflict, 503 unavailability and bad JSON", async () => {
    const api = createWorkbenchApi(vi.fn(async () => reply({ schema_version: SCHEMA_VERSION,
      state: "CONFLICT", data: null, gaps: ["healthy job"] }, 409)) as unknown as typeof fetch);
    await expect(api.retryJob("job-1")).rejects.toMatchObject({ status: 409 });
    const unavailable = createWorkbenchApi(vi.fn(async () => reply(null, 503)) as unknown as typeof fetch);
    await expect(unavailable.getHistory("20261013")).rejects.toMatchObject({ status: 503 });
    const invalid = createWorkbenchApi(vi.fn(async () => reply({ state: "READY", data: {} })) as unknown as typeof fetch);
    await expect(invalid.getDay({ date: "20261013" })).rejects.toBeInstanceOf(ApiError);
  });
  it("POSTs only target date/phase/lanes; subsequent GET is read-only", async () => {
    const transport = vi.fn(async () => reply(wrapped({ job_id: "j1", run_id: "r1", status_url: "/jobs/j1" }))) as unknown as typeof fetch;
    const api = createWorkbenchApi(transport);
    await api.createRun("20261013", "RETROSPECTIVE", ["ANNOUNCEMENT"]);
    const body = JSON.parse((transport as ReturnType<typeof vi.fn>).mock.calls[0][1].body as string);
    expect(body).toEqual({ target_date: "20261013", phase: "RETROSPECTIVE", lanes: ["ANNOUNCEMENT"] });
    expect(body).not.toHaveProperty("cutoff");
    await api.getJob("j1");
    expect((transport as ReturnType<typeof vi.fn>).mock.calls[1][1].method).toBeUndefined();
  });
  it("never silently reads a different stock version", async () => {
    const transport = vi.fn(async () => reply(wrapped({ stock: null }))) as unknown as typeof fetch;
    await createWorkbenchApi(transport).getStock("HK.01234", "20261013", "run-01");
    expect((transport as ReturnType<typeof vi.fn>).mock.calls[0][0]).toContain("run_id=run-01");
  });
});
