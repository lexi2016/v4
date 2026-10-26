import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, fireEvent } from "@testing-library/vue";
import { defineComponent } from "vue";
import { createTimeline, projectClosingTimeline, nextClosingStatusDelay } from "./timeline";
import { useAppShell } from "./useAppShell";
import type { TaskStatusResponse } from "../contracts/runtime";
const definitions = createTimeline().closingTimeline;
function response(date="20261026", state="FAILED") {
  return { business_date: date, timeline_nodes: [{ ...definitions[3],position:12,business_date:date,status:"FAIL",task_state:state,reason:"SELECTOR_DATE_MISSING",run_id:"dispatch-1",binding_status:state === "READY" ? "BUSINESS_RECEIPT_BOUND_TO_DISPATCH_RUN" : "DISPATCH_RUN_VERIFIED" }] } as TaskStatusResponse;
}
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
describe("closing timeline evidence projection",()=>{
  it("preserves eight stages and correct existing 8873 task purpose",()=>{
    expect(createTimeline().stageDefinitions).toHaveLength(8);
    expect(definitions).toHaveLength(11);
    expect(definitions[10].label).toContain("8873 页面与接口验收");
  });
  it.each(["PLANNED","QUEUED","RUNNING","WAITING_DEPENDENCY","FAILED","PARTIAL","READY"])("shows %s only from exact date and owner",state=>{
    expect(projectClosingTimeline(definitions,response("20261026",state),"20261026")[3].state).toBe(state);
    expect(projectClosingTimeline(definitions,response("20261025",state),"20261026")[3].state).toBe("CANNOT_CONFIRM");
    const wrong=response("20261026",state);wrong.timeline_nodes![0].owner_id="wrong";
    expect(projectClosingTimeline(definitions,wrong,"20261026")[3].state).toBe("CANNOT_CONFIRM");
  });
  it("keeps unprojected dispatch success unknown and rejects duplicate nodes",()=>{
    const payload=response();payload.timeline_nodes![0].task_state=undefined;payload.timeline_nodes![0].status="SUCCEEDED";
    expect(projectClosingTimeline(definitions,payload,"20261026")[3].state).toBe("CANNOT_CONFIRM");
    const dup=response();dup.timeline_nodes!.push(dup.timeline_nodes![0]);
    expect(projectClosingTimeline(definitions,dup,"20261026")[3].state).toBe("CANNOT_CONFIRM");
  });
  it("refreshes once at the next same-date plan boundary",()=>{
    const payload=response("20261026","PLANNED");
    payload.timeline_nodes![0].planned_time="2030";
    const now=Date.parse("2026-10-26T20:29:00+08:00");
    expect(nextClosingStatusDelay(payload,"20261026",now)).toBe(61000);
    expect(nextClosingStatusDelay(payload,"20261026",now+62000)).toBeNull();
    expect(nextClosingStatusDelay(payload,"20261027",now)).toBeNull();
  });
  it("node9 displays the workload 16:10 trigger and refreshes at that boundary",()=>{
    const node={...definitions[0],position:9,business_date:"20261026",status:"PENDING_NOT_DUE",task_state:"PLANNED",planned_time:"1610",label:"16:10 港股通正式收盘：0.2 × 七阶段 Top20"};
    const payload={business_date:"20261026",timeline_nodes:[node]} as TaskStatusResponse;
    expect(definitions[0].label).toContain("9. 16:10 ");
    expect(projectClosingTimeline(definitions,payload,"20261026")[0].label).toContain("9. 16:10 ");
    expect(nextClosingStatusDelay(payload,"20261026",Date.parse("2026-10-26T16:09:00+08:00"))).toBe(61000);
  });
  it("loads the real status API and clears old evidence on a date change",async()=>{
    let resolveNext!: (value: unknown) => void;
    const next = new Promise((resolve) => { resolveNext = resolve; });
    const fetcher=vi.fn(async(input:RequestInfo|URL)=>{
      const url=String(input);
      if (url === "/api/v3/tasks/status?date=20261027") return next;
      const body=url.includes("tasks/status") ? response(new URL(url,"http://local").searchParams.get("date")!)
        :url.includes("date-list") ? { default_date:"20261026",navigation_date:"20261026",system_date:"20261026",dates:["20261026","20261027"],stage_dates:["20261026","20261027"],future_target_dates:[] }
        :url.includes("research/dates") ? {research_dates:[]}:{};
      return {ok:true,json:async()=>body};
    });
    vi.stubGlobal("fetch",fetcher);
    const Harness=defineComponent({setup:useAppShell,template:'<div><button @click="selectedDate=\'20261027\'">next</button><p v-for="node in closingTimeline" :key="node.node_id">{{node.state}} {{node.run_id}} {{node.reason}}</p></div>'});
    render(Harness);
    await waitFor(()=>expect(screen.getByText("FAILED dispatch-1 SELECTOR_DATE_MISSING")).toBeTruthy());
    await fireEvent.click(screen.getByText("next"));
    await waitFor(()=>expect(fetcher).toHaveBeenCalledWith("/api/v3/tasks/status?date=20261027",expect.anything()));
    expect(screen.queryByText("FAILED dispatch-1 SELECTOR_DATE_MISSING")).toBeNull();
    resolveNext({ok:true,json:async()=>response("20261025")});
    await waitFor(()=>expect(screen.getAllByText(/CANNOT_CONFIRM CANNOT_CONFIRM/)).toHaveLength(11));
  });
});
