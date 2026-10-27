import { cleanup, render, screen, waitFor, within } from "@testing-library/vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import TaskStatusView from "./TaskStatusView.vue";


const fixture = {
  logical_workload_count: 3,
  active_owner_count: 1,
  alias_count: 1,
  retired_owner_count: 1,
  task_registration_count: 2,
  groups: {
    logical: [
      { workload_id: "failed_job", status: "FAILED", result_code: "EXIT_1", last_run: "2026-07-30T12:01:02Z", next_due: "18:00", duration_ms: 3100, freshness: "STALE", receipt_path: "receipts/live/failure.json" },
      { workload_id: "calendar_job", status: "NON_TRADING_DAY", result_code: "CALENDAR_SKIPPED", last_run: "2026-07-30T07:00:01Z", next_due: "12:00", duration_ms: 5, freshness: "CURRENT", receipt_path: "receipts/live/calendar.json" },
      { workload_id: "ok_job", status: "SUCCEEDED", result_code: "OK", last_run: "2026-07-30T06:59:59Z", next_due: "12:00", duration_ms: 800, freshness: "CURRENT", receipt_path: "receipts/live/success.json" },
    ],
    active_owners: [{ owner_id: "v35_dispatcher.failed_job", workload_id: "failed_job", status: "ACTIVE" }],
    aliases: [{ alias: "legacy_failed_job", workload_id: "failed_job", status: "ALIAS_ONLY" }],
    retired: [{ owner_id: "LegacyFailedJob", replacement_workload_id: "failed_job", status: "RETIRED_DISABLED" }],
    registrations: [
      { graph_task_spec_id: "task_spec:LegacyGraphOne", legacy_task_id: "LegacyGraphOne", timeline_node_ids: ["node_one"], legacy_launcher_paths: ["launcher_one.ps1"], actual_windows_task_ids: ["LegacyGraphOne"], enabled: false, execution_allowed: false, status: "CANNOT_CONFIRM", disposition: "USER_APPROVED_DISABLED_CANNOT_CONFIRM" },
      { graph_task_spec_id: "task_spec:LegacyGraphTwo", legacy_task_id: "LegacyGraphTwo", timeline_node_ids: ["node_two"], legacy_launcher_paths: [], actual_windows_task_ids: ["LegacyGraphTwo"], enabled: false, execution_allowed: false, status: "CANNOT_CONFIRM", disposition: "USER_APPROVED_DISABLED_CANNOT_CONFIRM" },
    ],
  },
  cannot_confirm: ["EXECUTION_RECEIPT_MISSING", "GRAPH_TASK_REGISTRATIONS_CANNOT_CONFIRM:2"],
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
};

describe("TaskStatusView", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("separates identities, prioritizes failures, and exposes cannot_confirm", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => fixture })));

    const { container } = render(TaskStatusView, { props: { date: "20260730" } });

    expect((await screen.findByRole("alert")).textContent).toContain("EXECUTION_RECEIPT_MISSING");
    const rows = container.querySelectorAll("[data-workload-row]");
    const counts = container.querySelector(".task-counts") as HTMLElement;
    expect(rows).toHaveLength(3);
    expect(within(rows[0] as HTMLElement).getByText("failed_job")).toBeTruthy();
    expect(within(counts).getByText("逻辑任务").nextElementSibling?.textContent).toBe("3");
    expect(within(counts).getByText("已配置 owner").nextElementSibling?.textContent).toBe("1");
    expect(within(counts).getByText("别名").nextElementSibling?.textContent).toBe("1");
    expect(within(counts).getByText("退役 owner").nextElementSibling?.textContent).toBe("1");
    expect(within(counts).getByText("图谱待确认").nextElementSibling?.textContent).toBe("2");
    expect(screen.getAllByText(/legacy_failed_job/)).toHaveLength(1);
    expect(screen.getByText("仅映射，不产生第二次执行")).toBeTruthy();
    expect(screen.getByText("图谱待确认任务 · 不会执行")).toBeTruthy();
    expect(container.querySelectorAll("[data-registration-row]")).toHaveLength(2);
    expect(screen.getByText("LegacyGraphOne")).toBeTruthy();
    expect(screen.getAllByText(/execution_allowed=false/)).toHaveLength(2);
    expect(screen.queryByText("正在读取任务状态")).toBeNull();
  });

  it("ends loading and shows a visible error on request failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false })));

    render(TaskStatusView, { props: { date: "20260730" } });

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("任务状态读取失败"));
    expect(screen.queryByText("正在读取任务状态")).toBeNull();
  });

  it("keeps the seven stage summary cards inside task status", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => fixture })));

    const { container } = render(TaskStatusView, {
      props: {
        date: "20260730",
        phaseStatus: "观察材料已生成",
        currentStageLabel: "09:30-09:35",
        selectedARows: 4,
        aSourceRows: 12,
        aCandidateCount: 6,
        selectedHkRows: 3,
        hkCandidateCount: 5,
        referenceMode: true,
        selectedTotalRows: 7,
        dataLevel: "WATCH_ONLY",
      },
    });

    await screen.findByText("failed_job");
    const summary = container.querySelector("[data-stage-summary]") as HTMLElement;
    expect(summary).toBeTruthy();
    expect(summary.querySelectorAll("article")).toHaveLength(7);
    expect(within(summary).getByText("观察材料已生成")).toBeTruthy();
    expect(within(summary).getByText("本地参考快照")).toBeTruthy();
    expect(within(summary).getByText("7")).toBeTruthy();
  });

  it("does not turn a missing stage summary identity into zero counts", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => fixture })));

    const { container } = render(TaskStatusView, { props: { date: "20260730" } });

    await screen.findByText("failed_job");
    const summary = container.querySelector("[data-stage-summary]") as HTMLElement;
    expect(within(summary).getAllByText("—").length).toBeGreaterThan(0);
    expect(within(summary).getAllByText("CANNOT_CONFIRM").length).toBeGreaterThan(0);
    expect(within(summary).queryByText(/^0$/)).toBeNull();
  });

  it("shows an explicit zero only when date and stage identity match", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => fixture })));

    const { container } = render(TaskStatusView, {
      props: {
        date: "20260730",
        currentStageId: "STAGE_0925",
        stageSummary: {
          trade_date: "20260730",
          stage_id: "STAGE_0925",
          stage_label: "港股通09:20 / A股09:25竞价选股",
          phase_status: "数据待补齐",
          selected_a_rows: 0,
          a_source_rows: 0,
          a_candidate_count: 0,
          selected_hk_rows: 0,
          hk_candidate_count: 0,
          selected_total_rows: 0,
          data_level: "WATCH_ONLY",
        },
      },
    });

    await screen.findByText("failed_job");
    const summary = container.querySelector("[data-stage-summary]") as HTMLElement;
    expect(within(summary).getAllByText("0").length).toBeGreaterThan(0);
    expect(within(summary).queryByText("—")).toBeNull();
  });

  it("marks a date or stage mismatch as cannot confirm instead of showing stale metrics", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => fixture })));

    const { container } = render(TaskStatusView, {
      props: {
        date: "20260730",
        currentStageId: "STAGE_0925",
        stageSummary: {
          trade_date: "20260729",
          stage_id: "STAGE_0930_0935",
          stage_label: "09:30-09:35",
          phase_status: "READY",
          selected_a_rows: 12,
          selected_hk_rows: 4,
          selected_total_rows: 16,
          data_level: "READY",
        },
      },
    });

    await screen.findByText("failed_job");
    const summary = container.querySelector("[data-stage-summary]") as HTMLElement;
    expect(within(summary).getAllByText("—").length).toBeGreaterThan(0);
    expect(within(summary).getAllByText("CANNOT_CONFIRM").length).toBeGreaterThan(0);
    expect(within(summary).queryByText(/^12$/)).toBeNull();
  });
});
