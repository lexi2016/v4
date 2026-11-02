import { cleanup, render, screen, waitFor, within } from "@testing-library/vue";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App.vue";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("shows the chart group with source date and refreshes only its matching completion", async () => {
  window.history.replaceState({}, "", "/?date=20260730&stage=STAGE_0925");
  class FakeEventSource extends EventTarget {
    static instances: FakeEventSource[] = [];
    close = vi.fn();
    constructor(public url: string) { super(); FakeEventSource.instances.push(this); }
    send(value: unknown) { this.dispatchEvent(new MessageEvent("a_share_daily_completed", { data: JSON.stringify(value) })); }
  }
  vi.stubGlobal("EventSource", FakeEventSource);
  const group = { pool_id:"a_share_chart_selection",display_name:"图形选股",market:"A",status:"CHART_SELECTION_READY",
    pool_size:1,signal_date:"20260729",target_date:"20260730",coverage_evidence:{source_unknown_count:2,source_product_status:"PARTIAL_WITH_ROWS"},
    rows:[{market:"A",symbol:"A.000035",stock_name:"中国天楹",source_date:"20260729",
      source_trace:"图形选股：原公式；待核：导航回踩；来源日 20260729"}] };
  const pool={data_status:"PARTIAL_WITH_ROWS",trade_date:"20260730",market_totals:{A:1,HK:0},
    pools:[group],a_all_pool_rows:group.rows,rows:group.rows,blocking_reasons:[],write_policy:"read_only",
    production_allowed:false,buy_gate_updated:false,orders_sent:false};
  const response=(value:unknown)=>({ok:true,json:async()=>value});
  const fetchMock=vi.fn(async (url:string)=>{
    if(url==="/api/v1/runs/date-list") return response({default_date:"20260730",stage_dates:["20260730"],future_target_dates:[]});
    if(url.startsWith("/api/v4/preselection-pools")) return response(pool);
    if(url==="/api/v4/research/dates") return response({research_dates:[]});
    return response({});
  });
  vi.stubGlobal("fetch",fetchMock);
  const {unmount}=render(App);
  await waitFor(()=>expect(within(screen.getByRole("region",{name:"图形选股"})).getByText("中国天楹")).toBeTruthy());
  const section=screen.getByRole("region",{name:"图形选股"});
  expect(within(section).getByText(/待核：导航回踩/)).toBeTruthy();
  expect(within(section).getByText(/信号日 20260729，目标日 20260730/)).toBeTruthy();
  expect(within(section).getByText(/全范围 2 只股票至少一组待核，可与已命中名单重叠/)).toBeTruthy();
  expect(within(section).getByText(/来源面板为部分完成/)).toBeTruthy();
  const poolCalls=()=>fetchMock.mock.calls.filter(([url])=>url.startsWith("/api/v4/preselection-pools"));
  expect(poolCalls()).toHaveLength(1);
  const source=FakeEventSource.instances[0];
  expect(source.url).toBe("/api/v4/research/events");
  const sha="a".repeat(64);
  const completion={schema_version:"v4.a_share.daily_completion.v1",RESEARCH_ONLY:true,
    production_allowed:false,buy_gate_updated:false,orders_sent:false,data_date:"20260729",
    source_generation:sha,manifest:{sha256:sha},chart_preselection:{status:"READY",pool_id:"a_share_chart_selection",
    target_date:"20260730",source_date:"20260729",source_generation:sha,source_manifest_sha256:sha,artifact_sha256:sha}};
  source.send({...completion,chart_preselection:{...completion.chart_preselection,target_date:"20260731"}});
  expect(poolCalls()).toHaveLength(1);
  source.send({...completion,chart_preselection:{...completion.chart_preselection,status:"CANNOT_CONFIRM",target_date:"20260731",artifact_sha256:undefined}});
  expect(within(section).queryByText(/图形池更新回执未确认/)).toBeNull();
  source.send({...completion,chart_preselection:{...completion.chart_preselection,status:"CANNOT_CONFIRM",artifact_sha256:undefined}});
  await waitFor(()=>expect(poolCalls()).toHaveLength(2));
  await waitFor(()=>expect(screen.getByText(/图形池更新回执未确认：信号日 20260729，目标日 20260730/)).toBeTruthy());
  const otherSha="b".repeat(64);
  const other={...completion,data_date:"20260730",source_generation:otherSha,manifest:{sha256:otherSha},
    chart_preselection:{...completion.chart_preselection,target_date:"20260731",source_date:"20260730",
      source_generation:otherSha,source_manifest_sha256:otherSha,artifact_sha256:otherSha}};
  source.send(other);
  source.send({...other,chart_preselection:{...other.chart_preselection,status:"CANNOT_CONFIRM",artifact_sha256:undefined}});
  source.send(other);
  source.send({...other,chart_preselection:{...other.chart_preselection,status:"CANNOT_CONFIRM",target_date:null,artifact_sha256:undefined}});
  expect(poolCalls()).toHaveLength(2);
  await waitFor(()=>expect(screen.getByText(/图形池更新回执未确认：信号日 20260729，目标日 20260730/)).toBeTruthy());
  const differentGeneration={...completion,source_generation:otherSha,manifest:{sha256:otherSha},
    chart_preselection:{...completion.chart_preselection,source_generation:otherSha,source_manifest_sha256:otherSha,artifact_sha256:otherSha}};
  source.send(differentGeneration);
  await waitFor(()=>expect(poolCalls()).toHaveLength(3));
  await waitFor(()=>expect(screen.getByText(/图形池更新回执未确认：信号日 20260729，目标日 20260730/)).toBeTruthy());
  source.send(completion);
  await waitFor(()=>expect(poolCalls()).toHaveLength(4));
  await waitFor(()=>expect(screen.queryByText(/图形池更新回执未确认/)).toBeNull());
  unmount();
  expect(source.close).toHaveBeenCalledOnce();
});
