import { describe, expect, it } from "vitest";
import { validateManagerWorkbenchResearch } from "./managerWorkbenchResearch";

const DATE = "20260918";

const universeSource = {
  owner: "SIMULATED_FIXTURE",
  role: "HK_CONNECT_ELIGIBLE_UNIVERSE_FIXTURE",
  artifact_ref: "simulated/universe/20260918.json",
  manifest_ref: null,
  receipt_ref: null,
  run_id: "SIMULATED-UNIVERSE-20260918",
  sha256: "a".repeat(64),
  source_date: DATE,
  market: "HK_CONNECT",
  lane: null,
  reason: "SIMULATED fixture only",
  observed_at: "2026-09-18T15:29:00+08:00",
  available_at: "2026-09-18T15:29:30+08:00",
};

const valid = (): any => ({
  schema_version: "v4.manager_workbench.research.v1",
  market: "HK_CONNECT",
  trade_date: DATE,
  slot: "1530",
  as_of: "2026-09-18T15:30:00+08:00",
  generated_at: "2026-09-18T15:31:00+08:00",
  run_id: "SIMULATED-B1-CONTRACT-20260918",
  status: "PARTIAL",
  rule_version: "manager-workbench-b1-simulated-v1",
  cache_key: `${DATE}|HK_CONNECT|1530|manager-workbench-b1-simulated-v1`,
  universe: universeSource,
  coverage: { eligible_count: 3, covered_count: 2, missing_count: 1, missing_reasons: ["SIMULATED_ONE_QUOTE_MISSING"] },
  cannot_confirm: ["SIMULATED_B2_SCANNER_NOT_IMPLEMENTED"],
  priority_summary: {
    focus: [{ item_id: "focus-1", candidate_id: "sim-hk-00100", name: "模拟重点（SIMULATED）", occurred_at: "2026-09-18T15:30:00+08:00", reason: "SIMULATED：仅供合同测试", evidence_status: "SIMULATED_PARTIAL", kind: "FOCUS" }],
    theme_changes: [],
    risk_upgrades: [],
  },
  candidates: [{
    candidate_id: "sim-hk-00100",
    symbol: "HK.00100",
    name: "模拟候选（SIMULATED）",
    source_lanes: ["CLOSE_DISCOVERY", "CONTINUOUS_TRACKING"],
    first_seen_at: "2026-09-17T15:30:00+08:00",
    last_seen_at: "2026-09-18T15:30:00+08:00",
    observed_at: "2026-09-18T15:29:59+08:00",
    available_at: "2026-09-18T15:30:00+08:00",
    turnover_amount: { value: 100000001, currency: "HKD", unit: "HKD", as_of: "2026-09-18T15:30:00+08:00", status: "SIMULATED" },
    volume_comparison: { state: "unknown", ratio: null, baseline_as_of: null, reason: "SIMULATED：B2 baseline missing" },
    position: { state: "unknown", label: "待确认", reason: "SIMULATED：B2 rule unbound" },
    catalyst: { summary: "SIMULATED：不代表真实催化", status: "SIMULATED_PARTIAL" },
    research_priority: { level: "WATCH", previous_level: "WATCH", change_reason: "SIMULATED" },
    data_status: "SIMULATED_PARTIAL",
    attention_reason: "SIMULATED：验证工作台合同",
    predicates: [{ predicate_id: "B1_FIXTURE_PRESENT", value: true, reason: "SIMULATED fixture字段存在", input_refs: ["simulated/fixture"], rule_version: "v1" }],
    sources: [{
      ...universeSource,
      role: "CLOSE_DISCOVERY_FIXTURE",
      artifact_ref: "simulated/close/20260918.json",
      run_id: "SIM-CLOSE-20260918",
      lane: "CLOSE_DISCOVERY",
      reason: "SIMULATED 15:30来源理由",
    }, {
      ...universeSource,
      role: "CONTINUOUS_TRACKING_FIXTURE",
      artifact_ref: "simulated/continuous/20260918.json",
      run_id: "SIM-CONTINUOUS-20260918",
      lane: "CONTINUOUS_TRACKING",
      reason: "SIMULATED 连续跟踪来源理由",
    }],
    risks: [],
    observation_plan: { triggers: ["等待真实受控证据"], invalidation_conditions: [], missing_evidence: ["B2/B3"] },
    qualified: null,
    trade_date: DATE,
  }],
  RESEARCH_ONLY: true,
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
});

describe("manager workbench research contract", () => {
  it("accepts an exact-date explicitly simulated research-only envelope", () => {
    expect(validateManagerWorkbenchResearch(valid(), DATE)).toBeNull();
  });

  it.each([
    ["RESEARCH_ONLY", null],
    ["RESEARCH_ONLY", "true"],
    ["production_allowed", null],
    ["production_allowed", "false"],
    ["buy_gate_updated", true],
    ["orders_sent", true],
  ])("rejects invalid safety field %s=%s", (field, value) => {
    const payload = valid();
    payload[field] = value;
    expect(validateManagerWorkbenchResearch(payload, DATE)).toContain(field);
  });

  it("rejects a missing safety field rather than defaulting it", () => {
    const payload = valid();
    delete payload.orders_sent;
    expect(validateManagerWorkbenchResearch(payload, DATE)).toContain("orders_sent");
  });

  it("accepts Z and +08:00 but rejects naive timestamps and an incomplete cache key", () => {
    const z = valid();
    z.as_of = "2026-09-18T07:30:00Z";
    expect(validateManagerWorkbenchResearch(z, DATE)).toBeNull();

    const naive = valid();
    naive.as_of = "2026-09-18T15:30:00";
    expect(validateManagerWorkbenchResearch(naive, DATE)).toContain("as_of");

    const badKey = valid();
    badKey.cache_key = `${DATE}|HK_CONNECT|1530`;
    expect(validateManagerWorkbenchResearch(badKey, DATE)).toContain("cache_key");
  });

  it("does not permit duplicate symbols to masquerade as separate source candidates", () => {
    const payload = valid();
    payload.candidates.push({ ...payload.candidates[0], candidate_id: "second" });
    expect(validateManagerWorkbenchResearch(payload, DATE)).toContain("未合并");
  });

  it("rejects duplicate stable candidate IDs across different symbols", () => {
    const payload = valid();
    payload.candidates.push({ ...payload.candidates[0], symbol: "HK.00999" });
    expect(validateManagerWorkbenchResearch(payload, DATE)).toContain("candidate_id");
  });

  it("keeps INPUT_MISSING distinct from READY_EMPTY", () => {
    const payload = valid();
    payload.status = "INPUT_MISSING";
    payload.as_of = null;
    payload.generated_at = null;
    payload.candidates = [];
    payload.priority_summary.focus = [];
    expect(validateManagerWorkbenchResearch(payload, DATE)).toBeNull();
  });

  it("rejects future PIT timestamps and incomplete visible lineage", () => {
    const late = valid();
    late.candidates[0].available_at = "2026-09-18T15:30:01+08:00";
    expect(validateManagerWorkbenchResearch(late, DATE)).toContain("candidates");

    const missingRun = valid();
    missingRun.run_id = null;
    expect(validateManagerWorkbenchResearch(missingRun, DATE)).toContain("run_id");

    const missingLane = valid();
    missingLane.candidates[0].sources = [missingLane.candidates[0].sources[0]];
    expect(validateManagerWorkbenchResearch(missingLane, DATE)).toContain("candidates");
  });

  it("rejects future or undefined nested turnover and volume baselines", () => {
    const lateTurnover = valid();
    lateTurnover.candidates[0].turnover_amount.as_of = "2026-09-18T16:00:00+08:00";
    expect(validateManagerWorkbenchResearch(lateTurnover, DATE)).toContain("candidates");

    const lateBaseline = valid();
    lateBaseline.candidates[0].volume_comparison.baseline_as_of = "2026-09-18T16:00:00+08:00";
    expect(validateManagerWorkbenchResearch(lateBaseline, DATE)).toContain("candidates");

    const undefinedTurnover = valid();
    delete undefinedTurnover.candidates[0].turnover_amount.as_of;
    expect(validateManagerWorkbenchResearch(undefinedTurnover, DATE)).toContain("candidates");

    const undefinedBaseline = valid();
    delete undefinedBaseline.candidates[0].volume_comparison.baseline_as_of;
    expect(validateManagerWorkbenchResearch(undefinedBaseline, DATE)).toContain("candidates");
  });

  it("requires every declared predicate to be true before qualified can be true", () => {
    const qualified = valid();
    qualified.candidates[0].qualified = true;
    expect(validateManagerWorkbenchResearch(qualified, DATE)).toBeNull();

    const unknown = valid();
    unknown.candidates[0].qualified = true;
    unknown.candidates[0].predicates[0] = { ...unknown.candidates[0].predicates[0], value: "unknown" };
    expect(validateManagerWorkbenchResearch(unknown, DATE)).toContain("candidates");

    const absent = valid();
    absent.candidates[0].qualified = true;
    absent.candidates[0].predicates = [];
    expect(validateManagerWorkbenchResearch(absent, DATE)).toContain("candidates");
  });

  it.each(["PENDING_SLOT", "INPUT_MISSING", "FAILED", "NOT_APPLICABLE"]) (
    "rejects candidate or summary data on non-data status %s",
    (status) => {
      const payload = valid();
      payload.status = status;
      payload.as_of = null;
      payload.generated_at = null;
      expect(validateManagerWorkbenchResearch(payload, DATE)).toContain(status);
    },
  );

  it("rejects unsafe diagnostics, fake credentials, local paths, and undeclared source lanes", () => {
    const secret = valid();
    secret.cannot_confirm = ["Traceback (most recent call last): sk-FAKESECRET123456"];
    expect(validateManagerWorkbenchResearch(secret, DATE)).toContain("不允许");

    const path = valid();
    path.candidates[0].sources[0].artifact_ref = "/Users/example/private.json";
    expect(validateManagerWorkbenchResearch(path, DATE)).toContain("不允许");

    const badLane = valid();
    badLane.candidates[0].sources[0].lane = "STAGE";
    expect(validateManagerWorkbenchResearch(badLane, DATE)).toContain("candidates");
  });
});

// SIMULATED R2 wire tests. No legitimate all-four-positive input is available.
describe('R2 closed evidence admission',()=>{
  function observation() {
    const p=valid();p.rule_version='manager-close-rework-r2-v1';p.cache_key=`${DATE}|HK_CONNECT|1530|${p.rule_version}`;
    const c=p.candidates[0];c.qualified=null;
    c.predicates=['turnover_gt_100m_hkd','verified_volume_expansion','verified_oversold_or_breakout','new_direct_pit_catalyst'].map(predicate_id=>({predicate_id,value:'unknown',rule_version:p.rule_version,reason:'SIMULATED',input_refs:[]}));
    return p;
  }
  it('retains an honest observation',()=>expect(validateManagerWorkbenchResearch(observation(),DATE)).toBeNull());
  it.each([1,2])('does not accept a positive unsupported authority at leg %i',(i)=>{
    const p=observation();p.candidates[0].predicates[i].value=true;
    expect(validateManagerWorkbenchResearch(p,DATE)).not.toBeNull();
  });
  it('rejects arbitrary version, missing condition, and inconsistent qualified',()=>{
    for(const mutate of [(p:any)=>p.candidates[0].predicates.pop(),(p:any)=>p.candidates[0].predicates[0].rule_version='ARBITRARY',(p:any)=>p.candidates[0].qualified=true]){
      const p=observation();mutate(p);expect(validateManagerWorkbenchResearch(p,DATE)).not.toBeNull();
    }
  });
  it('does not accept USD as a verified HKD threshold',()=>{
    const p=observation();p.candidates[0].predicates[0].value=true;p.candidates[0].turnover_amount.currency='USD';
    expect(validateManagerWorkbenchResearch(p,DATE)).not.toBeNull();
  });
});
