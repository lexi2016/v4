import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import DailyResearchCommandView from "./DailyResearchCommandView.vue";

const slots = ["1000", "1100", "1200", "1300", "1400", "1500", "1600", "1700"];

const slotCounts: Record<string, [number, number, number]> = {
  "1000": [604, 182, 422],
  "1100": [69, 69, 0],
  "1200": [1, 1, 0],
  "1300": [24, 24, 0],
  "1400": [19, 19, 0],
  "1500": [21, 21, 0],
  "1600": [7, 7, 0],
  "1700": [7, 7, 0],
};

const slotMatrix = slots.map((slot) => {
  const [raw_rows, exact_rows, excluded_rows] = slotCounts[slot];
  return {
    slot,
    status: "READY" as const,
    raw_rows,
    exact_rows,
    excluded_rows,
    artifact_path: `research/hourly/live/20260824/${slot}.json`,
    artifact_sha256: "a".repeat(64),
    receipt_path: `receipts/research/hourly/live/20260824/${slot}.json`,
    receipt_sha256: "b".repeat(64),
    source_input_sha256: "c".repeat(64),
  };
});

const readyWithGap = {
  schema_version: "v3_5.research_day_product.v1",
  contract_id: "v3_5.research_day_product.v1",
  workflow_name: "V35_DAILY_RESEARCH_AUTHORITY_V1",
  pass_signal: "V35_DAILY_RESEARCH_AUTHORITY_PASS_V1",
  archive_date: "20260824",
  requested_date: "20260824",
  resolved_date: "20260824",
  timezone: "Asia/Shanghai",
  date_mode: "EXACT",
  endpoint_mode: "EXACT",
  status: "READY_WITH_DECLARED_GAPS",
  authoritative: false,
  is_full_day: true,
  loading_complete: true,
  write_policy: "read_only",
  recommendation_status: "RESEARCH_ONLY",
  expected_slots: slots,
  coverage: {
    expected_slots: 8,
    ready_slots: 8,
    missing_slots: [],
    complete: true,
    slot_matrix: slotMatrix,
  },
  counts: {
    raw_rows: 752,
    evidence_rows: 330,
    excluded_rows: 422,
    mention_pairs: 323,
    urls: 195,
    stock_rollups: 242,
    high_priority: 0,
    duplicate_pairs: 7,
  },
  exclusions: { date_mismatch: 422, pit_violation: 0, invalid_row: 0 },
  excluded_by_date: { "20260820": 13, "20260822": 117, "20260823": 292 },
  slot_matrix: slotMatrix,
  evidence_rows: [
    {
      archive_date: "20260824",
      slot: "1700",
      source_row_ref: "1700:0",
      stock_code: "000001",
      stock_name: "平安银行",
      url: "https://example.test/article",
      evidence_level: "L3_STRONG",
      evidence_sentence: "exact-date evidence",
    },
  ],
  mention_pairs: [
    {
      pair_key: "https://example.test/article|000001",
      normalized_url: "https://example.test/article",
      stock_code: "000001",
      stock_name: "平安银行",
      winner: { archive_date: "20260824", slot: "1700", source_row_ref: "1700:0" },
      source_slots: ["1600", "1700"],
      occurrence_count: 2,
      variant_count: 2,
      article_ids: ["a-1", "a-2"],
      dedupe_keys: ["d-1", "d-2"],
      source_refs: [{ source_row_ref: "1600:0" }, { source_row_ref: "1700:0" }],
      duplicate_reason: "CROSS_SLOT_REPEAT",
      tiebreaker: { slot: "1700", evidence_level: "L3_STRONG" },
      recommendation_status: "RESEARCH_ONLY",
    },
  ],
  stock_rollups: [
    {
      stock_code: "000001",
      stock_name: "平安银行",
      mention_pair_count: 1,
      evidence_row_count: 2,
      source_slots: ["1600", "1700"],
      urls: ["https://example.test/article"],
      pair_keys: ["https://example.test/article|000001"],
      duplicate_pair_count: 1,
      recommendation_status: "RESEARCH_ONLY",
    },
  ],
  high_priority: [],
  high_priority_status: {
    status: "CANNOT_CONFIRM",
    rule_id: null,
    registry: "MISSING",
    cannot_confirm: "JYG_STOCK_MENTIONS_REGISTRY_MISSING",
  },
  lineage: {
    source_refs: { "1700": { artifact_sha256: "a".repeat(64) } },
    artifact_sha256: "d".repeat(64),
    manifest_sha256: "e".repeat(64),
    receipt_sha256: "f".repeat(64),
    current_sha256: null,
    transformer_identity_sha256: "1".repeat(64),
  },
  execution_origin: "NATURAL",
  alerts: [
    {
      severity: "SEV2",
      code: "REGISTRY_MISSING",
      status: "OPEN",
      message: "JYG registry missing; high_priority remains empty",
    },
  ],
  cannot_confirm: ["JYG_STOCK_MENTIONS_REGISTRY_MISSING"],
  hourly_latest: {
    endpoint_mode: "LATEST_SLOT",
    slot: "1700",
    row_count: 7,
    is_full_day: false,
  },
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
  RESEARCH_ONLY: true,
};

const notMaterialized = {
  ...readyWithGap,
  execution_origin: undefined,
  archive_date: "20260823",
  requested_date: "20260823",
  resolved_date: null,
  status: "NOT_MATERIALIZED",
  authoritative: false,
  coverage: {
    expected_slots: 8,
    ready_slots: 0,
    missing_slots: slots,
    complete: false,
    slot_matrix: [],
  },
  counts: {
    raw_rows: 0,
    evidence_rows: 0,
    excluded_rows: 0,
    mention_pairs: 0,
    urls: 0,
    stock_rollups: 0,
    high_priority: 0,
    duplicate_pairs: 0,
  },
  excluded_by_date: {},
  slot_matrix: [],
  evidence_rows: [],
  mention_pairs: [],
  stock_rollups: [],
  cannot_confirm: ["RESEARCH_DAY_PRODUCT_NOT_MATERIALIZED:20260823"],
  alerts: [],
};

const response = (payload: unknown) => ({ ok: true, json: async () => payload });

describe("DailyResearchCommandView", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState({}, "", "/daily-research-command/");
  });

  it("selects the canonical default date and reads only its strict day API", async () => {
    window.history.replaceState({}, "", "/daily-research-command/");
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return response({ ok: true, default_date: "20260824", dates: ["20260824"], stage_dates: [], future_target_dates: [] });
      }
      return response(readyWithGap);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(DailyResearchCommandView);

    expect(await screen.findByText("READY_WITH_DECLARED_GAPS")).toBeTruthy();
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/runs/date-list",
      "/api/v3/research/day?archive_date=20260824",
    ]);
    expect(window.location.search).toBe("?date=20260824");
  });

  it("stays on NO_DATE_SELECTED when the date catalog is unavailable", async () => {
    window.history.replaceState({}, "", "/daily-research-command/");
    const fetchMock = vi.fn(async (_url: string) => ({ ok: false, status: 503, json: async () => ({}) }));
    vi.stubGlobal("fetch", fetchMock);

    render(DailyResearchCommandView);

    expect(await screen.findByText("NO_DATE_SELECTED")).toBeTruthy();
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual(["/api/v1/runs/date-list"]);
  });

  it("uses only strict day API and renders the six-layer research evidence", async () => {
    window.history.replaceState({}, "", "/daily-research-command/?date=20260824");
    const fetchMock = vi.fn(async (url: string) => response(readyWithGap));
    vi.stubGlobal("fetch", fetchMock);

    const { container } = render(DailyResearchCommandView);

    expect(await screen.findByText("READY_WITH_DECLARED_GAPS")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith("/api/v3/research/day?archive_date=20260824");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls.flat().join(" ")).not.toContain("/articles");
    expect(fetchMock.mock.calls.flat().join(" ")).not.toContain("hourly");
    expect(screen.getByText("requested 20260824")).toBeTruthy();
    expect(screen.getByText("resolved 20260824")).toBeTruthy();
    expect(screen.getByText("Asia/Shanghai")).toBeTruthy();
    expect(screen.getByText("752")).toBeTruthy();
    expect(screen.getByText("330")).toBeTruthy();
    expect(screen.getByText("323")).toBeTruthy();
    expect(screen.getByText("242")).toBeTruthy();
    expect(screen.getByText("195 URLs")).toBeTruthy();
    expect(screen.getByText("7 duplicate pairs")).toBeTruthy();
    expect(screen.getByText("JYG_STOCK_MENTIONS_REGISTRY_MISSING")).toBeTruthy();
    expect(screen.getByText("SEV2 · REGISTRY_MISSING")).toBeTruthy();
    expect(screen.getByText("execution_origin=NATURAL")).toBeTruthy();
    expect(screen.queryByText("AUTO_RETRY")).toBeNull();
    expect(screen.queryByText("MANUAL_RECOVERY")).toBeNull();
    expect(screen.getByText("1700 · 7 rows · SLOT_ONLY · is_full_day=false")).toBeTruthy();
    expect(screen.getAllByRole("row")).toHaveLength(9);
    expect(container.querySelectorAll("[data-slot]")).toHaveLength(8);
    for (const [slot, counts] of Object.entries(slotCounts)) {
      const cells = container.querySelectorAll(`[data-slot="${slot}"] th, [data-slot="${slot}"] td`);
      expect(cells[2]?.textContent).toBe(String(counts[0]));
      expect(cells[3]?.textContent).toBe(String(counts[1]));
      expect(cells[4]?.textContent).toBe(String(counts[2]));
    }
    expect(screen.getByText("excluded 422 · date/PIT/invalid 422/0/0")).toBeTruthy();
    expect(screen.getByText("artifact")).toBeTruthy();
    expect(screen.getByText("current")).toBeTruthy();
    expect(screen.getAllByText("CANNOT_CONFIRM").length).toBeGreaterThan(0);
    expect(screen.getByText("production_allowed=false")).toBeTruthy();
    expect(screen.getByText("buy_gate_updated=false")).toBeTruthy();
    expect(screen.getByText("orders_sent=false")).toBeTruthy();
    expect(within(container.querySelector("[data-pool=mention_pairs]") as HTMLElement).getByText("323")).toBeTruthy();
  });

  it("rejects a response from another date as STALE and never shows its rows", async () => {
    window.history.replaceState({}, "", "/daily-research-command/?date=20260824");
    vi.stubGlobal("fetch", vi.fn(async () => response({ ...readyWithGap, archive_date: "20260823", resolved_date: "20260823" })));

    render(DailyResearchCommandView);

    expect(await screen.findByText("STALE")).toBeTruthy();
    expect(screen.queryByText("平安银行")).toBeNull();
  });

  it("clears old payload and ignores a slow response after the date changes", async () => {
    window.history.replaceState({}, "", "/daily-research-command/?date=20260824");
    let resolveOld: ((value: unknown) => void) | undefined;
    const oldResponse = new Promise((resolve) => { resolveOld = resolve; });
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("20260824")) return oldResponse;
      return Promise.resolve(response({ ...readyWithGap, archive_date: "20260825", requested_date: "20260825", resolved_date: "20260825" }));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(DailyResearchCommandView);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const dateInput = screen.getByLabelText("研究日期") as HTMLInputElement;
    await fireEvent.update(dateInput, "2026-08-25");
    expect(await screen.findByText("resolved 20260825")).toBeTruthy();
    resolveOld?.(response({ ...readyWithGap, archive_date: "20260824", resolved_date: "20260824" }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByText("resolved 20260825")).toBeTruthy();
    expect(screen.queryByText("resolved 20260824")).toBeNull();
  });

  it("shows NOT_MATERIALIZED without carrying rows from another date", async () => {
    window.history.replaceState({}, "", "/daily-research-command/?date=20260823");
    vi.stubGlobal("fetch", vi.fn(async () => response(notMaterialized)));

    render(DailyResearchCommandView);

    expect((await screen.findAllByText("CANNOT_CONFIRM")).length).toBeGreaterThan(0);
    expect(screen.getByText("RESEARCH_DAY_PRODUCT_NOT_MATERIALIZED:20260823")).toBeTruthy();
    expect(screen.queryByText("平安银行")).toBeNull();
    expect(screen.getByText("0 evidence rows")).toBeTruthy();
  });

  it.each(["NATURAL", "AUTO_RETRY", "MANUAL_RECOVERY"] as const)(
    "renders only the single validated execution origin %s",
    async (origin) => {
      window.history.replaceState({}, "", "/daily-research-command/?date=20260824");
      vi.stubGlobal("fetch", vi.fn(async () => response({ ...readyWithGap, execution_origin: origin })));

      render(DailyResearchCommandView);

      expect(await screen.findByText("READY_WITH_DECLARED_GAPS")).toBeTruthy();
      expect(screen.getByText(`execution_origin=${origin}`)).toBeTruthy();
      for (const other of ["NATURAL", "AUTO_RETRY", "MANUAL_RECOVERY"] as const) {
        if (other !== origin) expect(screen.queryByText(other)).toBeNull();
      }
    },
  );

  it.each([
    ["missing", undefined],
    ["invalid", "UNREGISTERED_ORIGIN"],
    ["mixed", ["NATURAL", "AUTO_RETRY"]],
  ] as const)("renders origin CANNOT_CONFIRM for %s origin", async (_label, origin) => {
    window.history.replaceState({}, "", "/daily-research-command/?date=20260824");
    const candidate = { ...readyWithGap } as Record<string, unknown>;
    if (origin === undefined) delete candidate.execution_origin;
    else candidate.execution_origin = origin;
    vi.stubGlobal("fetch", vi.fn(async () => response(candidate)));

    const { container } = render(DailyResearchCommandView);

    const expectedState = origin === undefined ? "CANNOT_CONFIRM" : "REJECTED";
    await waitFor(() => expect(container.querySelector("main")?.getAttribute("data-state")).toBe(expectedState));
    expect(container.querySelector(".daily-research-command__origin-tag")?.textContent).toBe("execution_origin=CANNOT_CONFIRM");
    expect(screen.queryByText("execution_origin=NATURAL")).toBeNull();
    expect(screen.queryByText("execution_origin=AUTO_RETRY")).toBeNull();
    expect(screen.queryByText("execution_origin=MANUAL_RECOVERY")).toBeNull();
  });

  it.each([
    ["RESEARCH_ONLY", undefined],
    ["RESEARCH_ONLY", false],
    ["production_allowed", "false"],
    ["buy_gate_updated", true],
    ["orders_sent", 0],
  ] as const)("fails closed when safety flag %s is invalid", async (flag, value) => {
    window.history.replaceState({}, "", "/daily-research-command/?date=20260824");
    const candidate = { ...readyWithGap } as Record<string, unknown>;
    if (value === undefined) delete candidate[flag];
    else candidate[flag] = value;
    vi.stubGlobal("fetch", vi.fn(async () => response(candidate)));

    render(DailyResearchCommandView);

    expect((await screen.findAllByText("CANNOT_CONFIRM")).length).toBeGreaterThan(0);
    const actual = value === undefined ? "CANNOT_CONFIRM" : String(value);
    const flagNode = screen.getByText(`${flag}=${actual}`);
    expect(flagNode).toBeTruthy();
    expect(flagNode.className).toContain("daily-research-command__safety-flag--gap");
  });

  it.each([
    ["endpoint_mode", "LATEST"],
    ["schema_version", "v3_5.wrong.v1"],
    ["contract_id", "v3_5.wrong.v1"],
    ["pass_signal", "WRONG_PASS"],
    ["timezone", "UTC"],
    ["recommendation_status", "BUY"],
    ["write_policy", "force"],
  ] as const)("rejects strict wire mismatch in %s", async (field, value) => {
    window.history.replaceState({}, "", "/daily-research-command/?date=20260824");
    vi.stubGlobal("fetch", vi.fn(async () => response({ ...readyWithGap, [field]: value })));

    render(DailyResearchCommandView);

    expect(await screen.findByText("REJECTED")).toBeTruthy();
    expect(screen.queryByText("平安银行")).toBeNull();
  });
});
