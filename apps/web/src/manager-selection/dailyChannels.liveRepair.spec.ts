import { describe, expect, it, vi } from "vitest";
import { requestManagerWorkspace } from "../api/managerWorkspace.js";
import {
  readDailyDateBindings,
  renderDailyChannels,
  validateDailyChannels,
  validateWorkspaceDateBindings,
  type DailyChannels,
  type WorkspaceDateBindings,
} from "./dailyChannels";

const date = "20260930";
const bindings: WorkspaceDateBindings = {
  plan_date: date,
  selection_date: date,
  announcement_date: date,
};
const safe = { RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false };
const digest = "a".repeat(64);
const generatedAt = "2026-09-30T09:29:00+08:00";

function channel(channel: "ANNOUNCEMENT" | "HK_CONNECT" | "OVERSOLD"): Record<string, unknown> {
  const runId = `${channel.toLowerCase()}-run`;
  const product = channel === "ANNOUNCEMENT" ? "b".repeat(64) : "c".repeat(64);
  const row: Record<string, unknown> = {
    ...safe,
    symbol: "HK.00001",
    name: `${channel} 示例公司`,
    reason: `${channel} 原 owner 研究理由`,
    selection_status: "SELECTED",
    target_trade_date: date,
    data_date: date,
    run_id: runId,
    generated_at: generatedAt,
    product_sha256: product,
    source_refs: [{ title: `${channel} 原始来源`, sha256: digest }],
  };
  const value: Record<string, unknown> = {
    ...safe,
    channel,
    owner: `EXISTING_${channel}_OWNER`,
    status: "READY",
    target_trade_date: date,
    selection_date: date,
    announcement_date: date,
    data_date: date,
    rows: [row],
    candidate_count: 1,
    pending_count: 0,
    watch_count: 0,
    gaps: [],
    dependencies: [],
    run_id: runId,
    generated_at: generatedAt,
    product_sha256: product,
    input_identity: digest,
    execution_kind: channel === "ANNOUNCEMENT" ? "OWNER_IMPORT_TIMING_NOT_CLASSIFIED" : "SCHEDULED_PREOPEN",
    natural_run_verified: false,
  };
  if (channel === "ANNOUNCEMENT") {
    row.source_manifest_sha256 = digest;
    value.product_checks = [{
      status: "CONSUMED",
      product_sha256: product,
      target_trade_date: date,
      publication_date: date,
      evidence_run_id: runId,
      owner_available_at: generatedAt,
      source_manifest_sha256: digest,
    }];
    value.other_product_checks = [];
  }
  return value;
}

function fixture(): DailyChannels {
  return {
    ...safe,
    schema_version: "v4.manager_research.daily_channels.v1",
    date_bindings: { ...bindings },
    channels: [channel("ANNOUNCEMENT"), channel("HK_CONNECT"), channel("OVERSOLD")] as DailyChannels["channels"],
    selection_rules_unchanged: true,
  };
}

describe("manager live repair daily-channel contract", () => {
  it("keeps presentation fallbacks separate from explicit request bindings", () => {
    const legacy = readDailyDateBindings(new URLSearchParams("?date=20260930&plan_date=20261002"), "20260930");
    expect(legacy.bindings).toEqual({ plan_date: "20261002", selection_date: "20260930", announcement_date: "20260930" });
    expect(legacy.explicit).toBe(false);
    expect(legacy.requested).toEqual({});

    const explicit = readDailyDateBindings(new URLSearchParams(
      "?date=20260930&plan_date=20261002&selection_date=20261001&announcement_date=20260929"), "20260930");
    expect(explicit.explicit).toBe(true);
    expect(explicit.requested).toEqual({ selection_date: "20261001", announcement_date: "20260929" });
    expect(() => validateWorkspaceDateBindings(bindings, date, explicit.requested))
      .toThrow("WORKSPACE_DAILY_DATE_BINDING_MISMATCH");
    expect(() => readDailyDateBindings(new URLSearchParams("?announcement_date=20260931"), date))
      .toThrow("WORKSPACE_DAILY_DATE_BINDING_INVALID");
  });

  it("sends only explicitly requested child dates to the workspace API", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL) => ({ ok: true, status: 200, json: async () => ({}) } as Response));
    vi.stubGlobal("fetch", fetchMock);
    try {
      await expect(requestManagerWorkspace(date, new AbortController().signal, "auto", {
        selection_date: "20261001",
      })).rejects.toThrow();
      const url = String(fetchMock.mock.calls[0][0]);
      expect(url).toContain("selection_date=20261001");
      expect(url).not.toContain("announcement_date=");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("binds all three channels to the requested plan, selection, and announcement dates", () => {
    expect(validateWorkspaceDateBindings(bindings, date, {
      selection_date: date,
      announcement_date: date,
    })).toEqual(bindings);
    expect(() => validateWorkspaceDateBindings({ ...bindings, plan_date: "20261001" }, date))
      .toThrow("WORKSPACE_DAILY_DATE_BINDING_MISMATCH");

    const wrongDate = fixture();
    wrongDate.channels[2].target_trade_date = "20261001";
    expect(() => validateDailyChannels(wrongDate, bindings)).toThrow("WORKSPACE_DAILY_CHANNEL_INVALID");
  });

  it("renders same-day rows, reasons, and run identities while retaining the complete owner payload", () => {
    const raw = fixture();
    const before = structuredClone(raw);
    const host = document.createElement("section");

    renderDailyChannels(host, raw, bindings);

    expect(host.querySelectorAll("[data-daily-channel]")).toHaveLength(3);
    expect(host.querySelector("[data-daily-bindings]")?.textContent).toContain("来源/选股日 20260930 · 公告日 20260930 · 计划日 20260930");
    expect(host.textContent).toContain("ANNOUNCEMENT 原 owner 研究理由");
    expect(host.textContent).toContain("HK_CONNECT 原 owner 研究理由");
    expect(host.textContent).toContain("OVERSOLD 原 owner 研究理由");
    expect(host.textContent).toContain("announcement-run");
    expect(host.textContent).toContain("hk_connect-run");
    expect(host.textContent).toContain("oversold-run");
    expect(host.querySelectorAll("[data-daily-symbol='HK.00001']")).toHaveLength(3);
    expect(host.textContent).toMatch(/自然时段运行验收：(CANNOT_CONFIRM（未核实）|未核实)[.。]/);
    expect(raw).toEqual(before);
  });
});
