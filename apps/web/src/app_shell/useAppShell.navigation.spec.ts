import { createApp, h, nextTick, type App } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAppShell } from "./useAppShell";

vi.mock("../api/review", () => ({
  loadReview: vi.fn(async (date: string) => ({ trade_date: date })),
}));

vi.mock("../api/pool_stage", () => ({
  loadPoolSnapshot: vi.fn(async () => null),
  loadStageSnapshot: vi.fn(async (date: string, stage: string) => ({
    trade_date: date,
    stage: { stage_id: stage },
    unified_rows: [],
  })),
  projectSummaryPoolPage: vi.fn(() => null),
  POOL_PAGE_SIZE: 200,
}));

vi.mock("../api/runtime", () => ({
  loadTaskStatus: vi.fn(async (date: string) => ({ business_date: date, timeline_nodes: [] })),
}));

type Shell = ReturnType<typeof useAppShell>;
type MountedShell = { app: App; host: HTMLDivElement; shell: Shell };

const mounted: MountedShell[] = [];
const TARGET_DATE = "20261029";
const SECOND_DATE = "20261028";

function jsonResponse(body: unknown) {
  return { ok: true, json: async () => body } as Response;
}

function mountShell(): MountedShell {
  const host = document.createElement("div");
  document.body.append(host);
  let shell: Shell | undefined;
  const app = createApp({
    setup() {
      shell = useAppShell();
      return () => h("main", [
        shell!.researchActive.value ? h("section", { "data-view": "research" }) : null,
        shell!.closeReviewActive.value
          ? h("section", { "data-view": `review-${shell!.reviewFocus.value}` })
          : null,
        !shell!.researchActive.value && !shell!.closeReviewActive.value && !shell!.sopActive.value
          ? h("section", { "data-view": "stage" })
          : null,
      ]);
    },
  });
  app.mount(host);
  const instance = { app, host, get shell() { return shell!; } } as MountedShell;
  mounted.push(instance);
  return instance;
}

function dispose(instance: MountedShell) {
  instance.app.unmount();
  instance.host.remove();
  const index = mounted.indexOf(instance);
  if (index >= 0) mounted.splice(index, 1);
}

async function waitForMount(shell: Shell, date: string) {
  await vi.waitFor(() => expect(shell.selectedDate.value).toBe(date));
  await nextTick();
}

function viewOf(host: HTMLElement) {
  return host.querySelector("[data-view]")?.getAttribute("data-view") ?? "";
}

function queryValue(key: string) {
  return new URLSearchParams(window.location.search).get(key);
}

async function moveHistory(direction: "back" | "forward") {
  const popped = new Promise<void>((resolve) => {
    window.addEventListener("popstate", () => resolve(), { once: true });
  });
  window.history[direction]();
  await popped;
  await nextTick();
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.includes("/api/v1/runs/date-list")) {
      return jsonResponse({
        default_date: TARGET_DATE,
        navigation_date: TARGET_DATE,
        dates: [SECOND_DATE, TARGET_DATE],
        stage_dates: [SECOND_DATE, TARGET_DATE],
        review_dates: [SECOND_DATE, TARGET_DATE],
        future_target_dates: [],
        research_dates: [TARGET_DATE],
        hk_observation_only_dates: [],
      });
    }
    if (path.includes("/api/v4/research/dates")) return jsonResponse({ research_dates: [TARGET_DATE] });
    return jsonResponse({});
  }));
  window.history.replaceState({}, "", `/?date=${TARGET_DATE}`);
});

afterEach(() => {
  while (mounted.length) dispose(mounted[0]);
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

describe("desktop navigation URL state", () => {
  it("restores review, date, stage, and browser history from the generated URLs", async () => {
    let current = mountShell();
    await waitForMount(current.shell, TARGET_DATE);
    expect(viewOf(current.host)).toBe("stage");

    current.shell.openResearch();
    await nextTick();
    expect(queryValue("view")).toBe("research");
    expect(viewOf(current.host)).toBe("research");

    await current.shell.loadCloseReview("A");
    await nextTick();
    expect(window.location.search).toContain(`date=${TARGET_DATE}`);
    expect(queryValue("view")).toBe("a-review");
    expect(viewOf(current.host)).toBe("review-A");

    dispose(current);
    current = mountShell();
    await waitForMount(current.shell, TARGET_DATE);
    expect(queryValue("view")).toBe("a-review");
    expect(viewOf(current.host)).toBe("review-A");

    const dateInput = document.createElement("input");
    dateInput.value = "2026-10-28";
    await current.shell.onDateInputChange({ currentTarget: dateInput } as unknown as Event);
    expect(current.shell.selectedDate.value).toBe(SECOND_DATE);
    expect(queryValue("date")).toBe(SECOND_DATE);
    expect(queryValue("view")).toBe("a-review");

    await moveHistory("back");
    expect(queryValue("date")).toBe(TARGET_DATE);
    expect(queryValue("view")).toBe("a-review");
    expect(viewOf(current.host)).toBe("review-A");
    await moveHistory("forward");
    expect(queryValue("date")).toBe(SECOND_DATE);
    expect(viewOf(current.host)).toBe("review-A");

    current.shell.loadStageFromUser("STAGE_0930_0935");
    await vi.waitFor(() => expect(queryValue("stage")).toBe("STAGE_0930_0935"));
    expect(queryValue("view")).toBeNull();
    expect(viewOf(current.host)).toBe("stage");
    expect(queryValue("date")).toBe(SECOND_DATE);

    dispose(current);
    current = mountShell();
    await waitForMount(current.shell, SECOND_DATE);
    expect(current.shell.selectedStage.value).toBe("STAGE_0930_0935");
    expect(queryValue("view")).toBeNull();
    expect(viewOf(current.host)).toBe("stage");

    await moveHistory("back");
    expect(queryValue("view")).toBe("a-review");
    expect(queryValue("date")).toBe(SECOND_DATE);
    expect(viewOf(current.host)).toBe("review-A");
    await moveHistory("forward");
    expect(queryValue("view")).toBeNull();
    expect(queryValue("stage")).toBe("STAGE_0930_0935");
    expect(viewOf(current.host)).toBe("stage");
  });

  it("preserves the existing HK and research review focus routes", async () => {
    let current = mountShell();
    await waitForMount(current.shell, TARGET_DATE);
    await current.shell.loadCloseReview("HK");
    expect(queryValue("view")).toBe("review");
    expect(current.shell.reviewFocus.value).toBe("HK");

    dispose(current);
    current = mountShell();
    await waitForMount(current.shell, TARGET_DATE);
    expect(current.shell.reviewFocus.value).toBe("HK");
    expect(viewOf(current.host)).toBe("review-HK");

    await current.shell.loadCloseReview("research");
    expect(queryValue("view")).toBe("research-review");
    expect(current.shell.reviewFocus.value).toBe("research");
    dispose(current);

    current = mountShell();
    await waitForMount(current.shell, TARGET_DATE);
    expect(current.shell.reviewFocus.value).toBe("research");
    expect(viewOf(current.host)).toBe("review-research");
  });

  it("keeps direct research URLs working and safely falls back for unknown views", async () => {
    window.history.replaceState({}, "", `/?date=${TARGET_DATE}&view=research`);
    let current = mountShell();
    await waitForMount(current.shell, TARGET_DATE);
    expect(queryValue("view")).toBe("research");
    expect(viewOf(current.host)).toBe("research");

    dispose(current);
    current = mountShell();
    await waitForMount(current.shell, TARGET_DATE);
    expect(viewOf(current.host)).toBe("research");
    dispose(current);

    window.history.replaceState({}, "", `/?date=${TARGET_DATE}&stage=STAGE_0930_0935&view=unknown`);
    current = mountShell();
    await waitForMount(current.shell, TARGET_DATE);
    expect(current.shell.selectedStage.value).toBe("STAGE_0930_0935");
    expect(viewOf(current.host)).toBe("stage");
  });
});
