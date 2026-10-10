import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import ManagerSelectionView from "./ManagerSelectionView.vue";
import { validateSelectionProduct } from "../contracts/selection";
import {
  buildManagerResearchQueue,
  normalizeManagerHkCode,
  validateManagerPreselection,
} from "../contracts/managerPreselection";
import { validateManagerDecisionResponse } from "../contracts/managerDecision";
import { validateManagerStageSelection } from "../contracts/managerStageSelection";

declare const process: { cwd(): string };

const response = (payload: unknown) => ({ ok: true, json: async () => payload });

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve;
  });
  return { promise, resolve };
};

const sourceRef = {
  type: "RESEARCH_SUPPLY_FROZEN_ENVELOPE",
  path: "/research/20260828/2200_initial_supply_freeze.json",
  raw_sha256: "a".repeat(64),
  frozen_payload_sha256: "b".repeat(64),
  json_pointer: "/frozen_payload/event_cards/0",
  source_date: "20260828",
  source_time: "2026-08-28T21:50:00+08:00",
  supply_receipt_path: "/receipts/research/20260828/supply.json",
  supply_receipt_sha256: "c".repeat(64),
};

const candidate = {
  candidate_id: "HK.09926|09926.HK",
  event_stock_link_id: "EVENT_AKESO|HK.09926|09926.HK",
  market: "HK",
  normalized_code: "09926",
  entity_id: "09926.HK",
  event_id: "EVENT_AKESO",
  bucket: "CONDITIONAL_RESEARCH_MAP",
  catalyst: JSON.stringify({ summary: "创新药事件待核验", trigger: "官方披露" }),
  counterevidence: JSON.stringify(["财务桥接未完成"]),
  invalidation: "官方数据不支持事件假设",
  evidence_level: "VERIFIED_SOURCE_IDENTITY",
  financial_bridge: JSON.stringify({ status: "UNVERIFIED" }),
  consensus: "NOT_COMPARABLE_NO_CONSENSUS",
  overnight_pending: "等待正式资格核验",
  source_metadata: { supply_card: { entity: "AKESO", price_reaction: { name: "康方生物" } } },
  source_status: "RESEARCH_SUPPLY_IMPORTED",
  published_at: "2026-08-28 18:10 HKT",
  published_at_aware: "2026-08-28T18:10:00+08:00",
  source_time: "2026-08-28T21:50:00+08:00",
  acceptance: "RESEARCH_SUPPLY_ONLY",
  eligibility: "ELIGIBILITY_CANNOT_CONFIRM",
  pit_status: "READY",
  research_status: "RESEARCH_ONLY",
  recommendation_status: "RESEARCH_ONLY",
  route_status: { R1: "VERIFIED_SOURCE_IDENTITY", R6: "CONTINUOUS_CATALYST_UNVERIFIED" },
  gemini_status: "UNVERIFIED",
  source_refs: [sourceRef],
};

const missingSnapshot = (phase: string) => ({
  phase,
  status: "NOT_MATERIALIZED",
  run_id: null,
  event_at: null,
  artifact_sha256: null,
  candidate_ids: [],
  changes: [],
  freeze_run_id: null,
  freeze_snapshot_sha256: null,
  snapshot_sha256: null,
});

const researchCodes = ["00001","00005","00013","00107","00142","00151","00165","00173","00175","00177","00270","00300","00316","00345","00347","00363","00386","00392","00460","00525","00548","00586","00604","00639","00656","00669","00699","00700","00751","00772","00855","00895","00914","00916","00941","00981","00995","01024","01066","01071","01088","01093","01113","01128","01157","01164","01304","01318","01385","01513","01519","01800","01810","01833","01860","01908","01951","01952","01999","02005","02057","02097","02145","02155","02196","02202","02252","02273","02291","02315","02338","02359","02378","02400","02410","02423","02476","02498","02600","02601","02602","02607","02628","02643","02676","02687","02691","02714","02858","02869","02877","02888","03268","03288","03323","03393","03633","03696","03738","03866","03908","03933","03986","06030","06067","06078","06185","06600","06680","06687","06690","06745","06806","06826","06951","06955","09606","09611","09626","09690","09696","09926","09987","09999"] as const;

const researchCandidates = researchCodes.map((code, index) => {
  if (code === candidate.normalized_code) return candidate;
  return {
    ...candidate,
    candidate_id: `HK.${code}|${code}.HK`,
    event_stock_link_id: `EVENT_RESEARCH_${code}|HK.${code}|${code}.HK`,
    normalized_code: code,
    entity_id: `${code}.HK`,
    event_id: `EVENT_RESEARCH_${code}`,
    bucket: "EVENT_RESEARCH_MAP",
    source_metadata: { supply_card: { entity: `ISSUER_${code}`, price_reaction: { name: `研究候选${index + 1}` } } },
  };
});

const managerDecisionRef = {
  path: "/Users/lexi/Desktop/学习/助手/白毛研究员/research/20260828/2200_initial_supply_20260831_v4_manager_bridge/manager_decision.json",
  raw_sha256: "40cfef21bbcf409dbebd07b7a664e29abe35bbb5bb37f0bd798540d4a9bd8a0c",
};
const managerRunId = "baimao-20260830-manager-research-overlay-v4";
const managerGeneratedAt = "2026-08-30T13:38:58.510320+08:00";
const managerCoreCodes = ["02315", "03738", "06951"] as const;
const managerConditionalCodes = ["06078", "01304", "01952", "02676", "02410"] as const;
const managerReasons: Record<string, string> = {
  "02315": "D-1第53；官方中报收入+51.6%、毛利+61.6%、期内利润+402.3%，经营加速支持核心研究；但低基数/一次性、现金转换、估值及目标日盘面仍待核，非BUY。",
  "03738": "D-1第45；收入、毛利、法定利润及调整后盈利均同比改善；但需核对调整项、现金转换、估值及目标日承接，非BUY。",
  "06951": "D-1第34；收入+54.82%、归母净利+56.18%，增长质量支持核心研究；但利润率/现金流/估值桥及目标日盘面未完成，非BUY。",
  "06078": "D-1第12；收入-1.4%，但利润+4.7%、毛利率+0.8pp、经营现金流+0.7%、自由现金流+38.5%，属修复线索；收入/债务/持续性与目标日盘面待核。",
  "01304": "D-1第16；收入、毛利、利润及现金余额同比改善；现金余额不等于经营现金流，持续性/估值/目标日承接待核。",
  "01952": "D-1第55；收入+157.3%、净亏收窄至5.9百万元、调整后利润转正；但20日涨幅约37%、会计调整和现金消耗带来追高风险，等待盘面稳定。",
  "02676": "D-1第28；收入+66.7%、毛利+48.4%、由亏转盈；但毛利质量、现金流、一次性因素和目标日盘面待核。",
  "02410": "D-1第6；NMPA有条件批准带来产品催化；但批准不等于商业化/盈利兑现，适应症、监管条件、经营桥和目标日承接待核。",
};
const managerResearchDetails: Record<string, Record<string, unknown>> = {
  "02315": {
    status: "READY", direction: "POSITIVE", priority_bucket: "PRIORITY",
    investment_thesis_cn: "收入、毛利与期内利润同步改善，经营加速值得进入核心研究；估值与现金转换仍待核。",
    official_facts: [
      { statement_cn: "官方中报收入同比增长51.6%。", markdown_path: "/research/02315.md", markdown_sha256: "a".repeat(64), line_start: 314, line_end: 321, excerpt_sha256: "b".repeat(64) },
      { statement_cn: "官方中报毛利同比增长61.6%。", markdown_path: "/research/02315.md", markdown_sha256: "a".repeat(64), line_start: 314, line_end: 321, excerpt_sha256: "c".repeat(64) },
      { statement_cn: "官方中报期内利润同比增长402.3%。", markdown_path: "/research/02315.md", markdown_sha256: "a".repeat(64), line_start: 314, line_end: 321, excerpt_sha256: "d".repeat(64) },
    ],
    confirmation_conditions: ["核对现金转换与一次性项目", "完成估值桥并观察目标日承接"],
    counterevidence_cn: ["低基数或一次性收益可能夸大同比增速"],
    invalidation_conditions: ["利润改善不能转化为现金，或目标日承接失效"],
  },
  "03738": {
    status: "READY", direction: "POSITIVE", priority_bucket: "PRIORITY",
    investment_thesis_cn: "收入、毛利及法定与调整后盈利均改善，先作为核心研究线索；调整项、现金转换和估值未完成。",
    official_facts: [
      { statement_cn: "官方披露收入同比显著增长。", markdown_path: "/research/03738.md", markdown_sha256: "e".repeat(64), line_start: 34, line_end: 39, excerpt_sha256: "f".repeat(64) },
      { statement_cn: "官方披露毛利及法定利润同比改善。", markdown_path: "/research/03738.md", markdown_sha256: "e".repeat(64), line_start: 34, line_end: 39, excerpt_sha256: "1".repeat(64) },
      { statement_cn: "官方披露调整后盈利同比改善。", markdown_path: "/research/03738.md", markdown_sha256: "e".repeat(64), line_start: 34, line_end: 39, excerpt_sha256: "2".repeat(64) },
    ],
    confirmation_conditions: ["拆分调整项并核对现金转换", "完成估值桥并观察目标日承接"],
    counterevidence_cn: ["调整项可能使法定与调整后利润不可比"],
    invalidation_conditions: ["现金流未跟随利润改善或目标日承接失效"],
  },
  "06951": {
    status: "READY", direction: "POSITIVE", priority_bucket: "PRIORITY",
    investment_thesis_cn: "收入与归母净利同步增长，增长质量支持核心研究；利润率、现金流和估值仍待核。",
    official_facts: [
      { statement_cn: "官方披露收入同比增长54.82%。", markdown_path: "/research/06951.md", markdown_sha256: "3".repeat(64), line_start: 30, line_end: 34, excerpt_sha256: "4".repeat(64) },
      { statement_cn: "官方披露归母净利同比增长56.18%。", markdown_path: "/research/06951.md", markdown_sha256: "3".repeat(64), line_start: 30, line_end: 34, excerpt_sha256: "5".repeat(64) },
    ],
    confirmation_conditions: ["核对利润率与经营现金流", "完成估值桥并观察目标日盘面"],
    counterevidence_cn: ["收入增长可能伴随利润率或现金流压力"],
    invalidation_conditions: ["利润率/现金流恶化或目标日承接失效"],
  },
  "06078": {
    status: "READY", direction: "MIXED", priority_bucket: "CONDITIONAL",
    investment_thesis_cn: "收入略降而利润、毛利率与现金流改善，构成修复线索；持续性、债务与盘面仍待确认。",
    official_facts: [
      { statement_cn: "官方披露收入同比下降1.4%，利润同比增长4.7%。", markdown_path: "/research/06078.md", markdown_sha256: "6".repeat(64), line_start: 185, line_end: 190, excerpt_sha256: "7".repeat(64) },
      { statement_cn: "官方披露毛利率、经营现金流及自由现金流均改善。", markdown_path: "/research/06078.md", markdown_sha256: "6".repeat(64), line_start: 185, line_end: 190, excerpt_sha256: "8".repeat(64) },
    ],
    confirmation_conditions: ["核对收入/债务与改善持续性", "观察目标日盘面承接"],
    counterevidence_cn: ["收入仍负增长，修复可能尚未形成趋势"],
    invalidation_conditions: ["现金流或利润修复反转"],
  },
  "01304": {
    status: "READY", direction: "POSITIVE", priority_bucket: "CONDITIONAL",
    investment_thesis_cn: "收入、毛利、利润及现金余额改善，进入条件研究；现金余额不等于经营现金流。",
    official_facts: [
      { statement_cn: "官方披露收入、毛利与利润同比改善。", markdown_path: "/research/01304.md", markdown_sha256: "9".repeat(64), line_start: 35, line_end: 41, excerpt_sha256: "a".repeat(64) },
      { statement_cn: "官方披露期末现金余额同比增加。", markdown_path: "/research/01304.md", markdown_sha256: "9".repeat(64), line_start: 35, line_end: 41, excerpt_sha256: "b".repeat(64) },
    ],
    confirmation_conditions: ["补齐经营现金流与持续性核对", "完成估值桥并观察目标日承接"],
    counterevidence_cn: ["现金余额不等于经营现金流或自由现金流"],
    invalidation_conditions: ["经营现金流不能支持利润改善"],
  },
  "01952": {
    status: "READY", direction: "POSITIVE", priority_bucket: "CONDITIONAL",
    investment_thesis_cn: "收入高增、净亏收窄并出现调整后盈利，作为条件研究；涨幅、调整项和现金消耗构成追高风险。",
    official_facts: [
      { statement_cn: "官方披露收入同比增长157.3%。", markdown_path: "/research/01952.md", markdown_sha256: "c".repeat(64), line_start: 460, line_end: 500, excerpt_sha256: "d".repeat(64) },
      { statement_cn: "官方披露净亏损由249.8百万元收窄至5.9百万元，调整后亏损转为盈利97.2百万元。", markdown_path: "/research/01952.md", markdown_sha256: "c".repeat(64), line_start: 460, line_end: 500, excerpt_sha256: "e".repeat(64) },
      { statement_cn: "官方披露现金及现金等价物约1.8588十亿元。", markdown_path: "/research/01952.md", markdown_sha256: "c".repeat(64), line_start: 460, line_end: 500, excerpt_sha256: "f".repeat(64) },
    ],
    confirmation_conditions: ["拆解会计调整与现金消耗", "等待涨幅消化后观察目标日盘面"],
    counterevidence_cn: ["D1前20日涨幅约37%，存在追高风险"],
    invalidation_conditions: ["调整后盈利不能持续或现金消耗恶化"],
  },
  "02676": {
    status: "READY", direction: "POSITIVE", priority_bucket: "CONDITIONAL",
    investment_thesis_cn: "收入与毛利增长并由亏转盈，作为条件研究；毛利质量、现金流及一次性因素待核。",
    official_facts: [
      { statement_cn: "官方披露收入同比增长66.7%。", markdown_path: "/research/02676.md", markdown_sha256: "0".repeat(64), line_start: 35, line_end: 41, excerpt_sha256: "1".repeat(64) },
      { statement_cn: "官方披露毛利同比增长48.4%，经营及期内利润由亏转盈。", markdown_path: "/research/02676.md", markdown_sha256: "0".repeat(64), line_start: 35, line_end: 41, excerpt_sha256: "2".repeat(64) },
    ],
    confirmation_conditions: ["核对毛利质量、现金流及一次性因素", "观察目标日承接"],
    counterevidence_cn: ["利润转正可能包含一次性因素"],
    invalidation_conditions: ["毛利或现金流无法延续改善"],
  },
  "02410": {
    status: "READY", direction: "MIXED", priority_bucket: "CONDITIONAL",
    investment_thesis_cn: "NMPA有条件批准带来产品催化，作为条件研究；批准不等于商业化或盈利兑现。",
    official_facts: [
      { statement_cn: "官方公告披露NMPA有条件营销批准。", markdown_path: "/research/02410.md", markdown_sha256: "3".repeat(64), line_start: 1, line_end: 12, excerpt_sha256: "4".repeat(64) },
    ],
    confirmation_conditions: ["核对适应症、监管条件与经营桥", "观察商业化兑现及目标日承接"],
    counterevidence_cn: ["有条件批准不等于商业化收入或盈利兑现"],
    invalidation_conditions: ["监管条件未满足或商业化兑现弱于预期"],
  },
};

const managerProjection = (code: string): Record<string, unknown> | undefined => {
  const coreIndex = managerCoreCodes.indexOf(code as (typeof managerCoreCodes)[number]);
  const conditionalIndex = managerConditionalCodes.indexOf(code as (typeof managerConditionalCodes)[number]);
  if (coreIndex >= 0) {
    return {
      schema_version: "v3_5.manager_research_decision.v1",
      phase: "2200",
      decision_state: "INITIAL_RESEARCH_DELTA",
      source_date: "20260828",
      target_trade_date: "20260831",
      run_id: managerRunId,
      generated_at: managerGeneratedAt,
      cutoff_at: "2026-08-28T22:27:18+08:00",
      role: "CORE",
      order: coreIndex + 1,
      reason: managerReasons[code],
    };
  }
  if (conditionalIndex >= 0) {
    return {
      schema_version: "v3_5.manager_research_decision.v1",
      phase: "2200",
      decision_state: "INITIAL_RESEARCH_DELTA",
      source_date: "20260828",
      target_trade_date: "20260831",
      run_id: managerRunId,
      generated_at: managerGeneratedAt,
      cutoff_at: "2026-08-28T22:27:18+08:00",
      role: "CONDITIONAL",
      order: conditionalIndex + 1,
      reason: managerReasons[code],
    };
  }
  return undefined;
};

const managerCandidates = researchCandidates.map((item) => {
  const projection = managerProjection(item.normalized_code || "");
  if (!projection) return item;
  const currentSupply = item.source_metadata?.supply_card as Record<string, unknown>;
  return {
    ...item,
    manager_decision: projection,
    source_metadata: {
      ...item.source_metadata,
      supply_card: {
        ...currentSupply,
        manager_research: managerResearchDetails[item.normalized_code || ""],
      },
    },
  };
});
const managerSnapshotCandidateIds = [...managerCoreCodes, ...managerConditionalCodes]
  .map((code) => `HK.${code}|${code}.HK`)
  .sort();
const managerFocusCandidateId = "HK.02315|02315.HK";
const managerFocusCandidate = managerCandidates.find((item) => item.candidate_id === managerFocusCandidateId) as typeof managerCandidates[number];

const product = {
  schema_version: "v3_5.selection_research_product.v1",
  contract_id: "v3_5.selection_research_product.v1",
  workflow_name: "V35_SELECTION_RESEARCH_PRODUCT",
  pass_signal: "V35_SELECTION_RESEARCH_VERTICAL_SLICE_VERIFIED",
  source_date: "20260828",
  target_trade_date: "20260831",
  requested_date: "20260831",
  endpoint_mode: "EXACT",
  timezone: "Asia/Shanghai",
  cutoff_at: "2026-08-28T22:27:18+08:00",
  generated_at: managerGeneratedAt,
  run_id: managerRunId,
  origin: "MANUAL_RECOVERY",
  status: "READY_WITH_DECLARED_GAPS",
  acceptance: "RESEARCH_SUPPLY_ONLY",
    research_candidates: managerCandidates,
  formal_shortlist: [],
  snapshots: {
    "2200": {
      phase: "2200",
      status: "READY",
      run_id: managerRunId,
      event_at: managerGeneratedAt,
      artifact_sha256: managerDecisionRef.raw_sha256,
      candidate_ids: [
        "HK.01304|01304.HK",
        "HK.01952|01952.HK",
        "HK.02315|02315.HK",
        "HK.02410|02410.HK",
        "HK.02676|02676.HK",
        "HK.03738|03738.HK",
        "HK.06078|06078.HK",
        "HK.06951|06951.HK",
      ],
      changes: [],
      freeze_run_id: null,
      freeze_snapshot_sha256: null,
      snapshot_sha256: "8ff2df03858da99e9ed4263de665230e3c43c008ecafb29344a82f0dc33e1613",
    },
    "0830": missingSnapshot("0830"),
    "0935": missingSnapshot("0935"),
    "1620": missingSnapshot("1620"),
  },
  intraday_observations: [],
  outcomes: [],
  counts: {
    research_candidates: 124,
    formal_shortlist: 0,
    snapshots: 4,
    intraday_observations: 0,
    outcomes: 0,
  },
  route_status: { R1: "VERIFIED_SOURCE_IDENTITY", R2: "NOT_MATERIALIZED", R6: "NOT_MATERIALIZED", GEMINI: "UNVERIFIED" },
  gemini_status: "UNVERIFIED",
  formal_authority: {
    status: "NOT_MATERIALIZED",
    target_trade_date: "20260831",
    pit_status: "CANNOT_CONFIRM",
    selector_status: "CANNOT_CONFIRM",
    research_evidence: false,
    manager_decision: false,
    source_sha256: null,
    evidence_refs: [],
    manager_decision_ref: null,
  },
  source_refs: researchCandidates.flatMap((item) => item.source_refs || []),
  first_failed_layer: "FORMAL_AUTHORITY_NOT_MATERIALIZED",
  cannot_confirm: [
    "FORMAL_AUTHORITY_NOT_MATERIALIZED",
    "SNAPSHOT_0830_NOT_MATERIALIZED",
    "SNAPSHOT_0935_NOT_MATERIALIZED",
    "SNAPSHOT_1620_NOT_MATERIALIZED",
  ],
  manager_decision_ref: managerDecisionRef,
  lineage: {
    artifact_path: "research/selection/20260831/baimao-20260830-manager-research-overlay-v4.json",
    artifact_sha256: "648010bfb763313ce27708e3b00aaf74f4e401b0f1aa16c6e53517c0347c9acb",
    manifest_path: "research/selection/20260831/baimao-20260830-manager-research-overlay-v4.manifest.json",
    manifest_sha256: "5ddfe0c09dae57f282f9e762105a765ca1538d0010ea740ba928aa6c812b9ff8",
    receipt_path: "receipts/research/selection/20260831/baimao-20260830-manager-research-overlay-v4.json",
    receipt_sha256: "80c8a20d5cc936b84811a2611eecaf6ea986befa9da3a34ea5ea3a3eb90bc283",
    current_path: "research/selection/20260831/current.json",
    current_sha256: "0396319551622fbdd22d5fb7da8d30e013caa077a78698d530e8e1afe0839517",
    run_id: managerRunId,
    target_trade_date: "20260831",
  },
  artifact_sha256: "648010bfb763313ce27708e3b00aaf74f4e401b0f1aa16c6e53517c0347c9acb",
  manifest_sha256: "5ddfe0c09dae57f282f9e762105a765ca1538d0010ea740ba928aa6c812b9ff8",
  receipt_sha256: "80c8a20d5cc936b84811a2611eecaf6ea986befa9da3a34ea5ea3a3eb90bc283",
  current_sha256: "0396319551622fbdd22d5fb7da8d30e013caa077a78698d530e8e1afe0839517",
  RESEARCH_ONLY: true,
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
};

const hkD1Codes = ["HK.02718","HK.02506","HK.02687","HK.02273","HK.06166","HK.02410","HK.01384","HK.02706","HK.09630","HK.03317","HK.02556","HK.06078","HK.02583","HK.09903","HK.02889","HK.01304","HK.02768","HK.02099","HK.06651","HK.01918","HK.03858","HK.02419","HK.03200","HK.02155","HK.01196","HK.06809","HK.00917","HK.02676","HK.03696","HK.00165","HK.03661","HK.01989","HK.01675","HK.06951","HK.06067","HK.03339","HK.02637","HK.02652","HK.02595","HK.06693","HK.02650","HK.06185","HK.02291","HK.06869","HK.03738","HK.03296","HK.02507","HK.01357","HK.02218","HK.06082","HK.01333","HK.01797","HK.02315","HK.01888","HK.01952","HK.01364","HK.06821","HK.01768","HK.01112","HK.06090","HK.09887","HK.09606","HK.02238","HK.09678","HK.02259","HK.02431","HK.02685","HK.02591","HK.02617","HK.09911","HK.06687","HK.03330","HK.02665","HK.06745","HK.02635","HK.00268","HK.00325","HK.02513","HK.02788","HK.06600","HK.01081","HK.02661","HK.00631","HK.02589","HK.02476","HK.02701","HK.00189","HK.06055","HK.00100","HK.02575","HK.06855","HK.00148","HK.02631","HK.02586","HK.02097","HK.02565","HK.00668","HK.02715","HK.06682","HK.02356"] as const;
const preselectionIntersectionCodes = new Set(["02687","02273","02410","06078","01304","02155","02676","03696","00165","06951","06067","06185","02291","03738","02315","01952","09606","06687","06745","06600","02476","02097"]);
const preselection = {
  schema_version: "v3_preselection_pools.v1",
  module_id: "unified_preselection_pools",
  write_policy: "read_only",
  ok: true,
  data_status: "PARTIAL_WITH_ROWS",
  requested_date: "20260831",
  selected_date: "20260831",
  trade_date: "20260831",
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
  cannot_confirm: [],
  pools: [{
    schema_version: "v3_5.preselection_pool.v1",
    pool_id: "hkconnect_d1_top100",
    display_name: "HK Connect D-1 Top100",
    market: "HK",
    status: "STRICT_0_2_READY",
    pool_size: 100,
    returned_rows: 100,
    source_row_count: 100,
    trade_date: "20260831",
    source_role: "SHARED_VERIFIED_HK_0_2",
    source_run_id: "shared-hk-d1-20260828",
    source_sha256: "d".repeat(64),
    producer_id: "shared-hk-preselection",
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
    cannot_confirm: ["RESEARCH_ONLY_NOT_BUY_GATE"],
    rows: hkD1Codes.map((code, index) => {
      const normalizedCode = code.replace(/^HK\./, "");
      return {
      market: "HK",
      symbol: `HK.${normalizedCode}`,
      code: `HK.${normalizedCode}`,
      code_norm: `HK.${normalizedCode}`,
      ts_code: `${normalizedCode}.HK_CONNECT`,
      stock_name: `D-1研究标的${normalizedCode}`,
      name: `D-1研究标的${normalizedCode}`,
      pool_id: "hkconnect_d1_top100",
      pool_rank: index + 1,
      rank: String(index + 1),
      pool_score: Number((1 - index / 1000).toFixed(6)),
      signal_date: "20260828",
      target_date: "20260831",
      trade_date: "20260831",
      recommendation_status: "WATCH_ONLY",
      trade_status_contract: "WATCH_ONLY",
      research_only: "True",
      production_allowed: false,
      buy_gate_updated: false,
      orders_sent: false,
      event_present_in_selection_fixture: preselectionIntersectionCodes.has(normalizedCode),
      };
    }),
  }],
};

const preselectionForDate = (targetDate: string) => ({
  ...preselection,
  requested_date: targetDate,
  selected_date: targetDate,
  trade_date: targetDate,
  pools: preselection.pools.map((pool) => ({
    ...pool,
    trade_date: targetDate,
    rows: pool.rows.map((row) => ({ ...row, target_date: targetDate, trade_date: targetDate })),
  })),
});

const managerStageSelection = {
  schema_version: "stage_center.selection_consumer.v1",
  response_source: "SHARED_STAGE_CENTER",
  trade_date: "20260831",
  stage_id: "STAGE_0935_0940",
  status: "PARTIAL_WITH_ROWS",
  markets: {
    A: {
      market: "A_SHARE",
      status: "READY",
      rows: Array.from({ length: 10 }, (_, index) => ({
        market: "A_SHARE",
        code: `A.${String(index + 1).padStart(6, "0")}`,
        name: `A股fixture-${index + 1}`,
        rank: index + 1,
        score: 100 - index,
      })),
    },
    HK: {
      market: "HK_CONNECT",
      status: "PARTIAL_WITH_ROWS",
      selection_status: "PARTIAL_WITH_ROWS",
      selected_rows: 8,
      rows: [
        ["09678", "云知声"],
        ["06082", "壁仞科技"],
        ["01918", "融创中国"],
        ["01888", "建滔积层板"],
        ["00189", "东岳集团"],
        ["00100", "MINIMAX-W"],
        ["00148", "建滔集团"],
        ["02513", "智谱"],
      ].map(([code, name], index) => ({
        market: "HK_CONNECT",
        code: `HK.${code}`,
        name,
        rank: index + 1,
        score: 90 - index,
        stage_score: 80 - index,
        d1_rank: index + 2,
        d1_score: Number((0.92 - index / 100).toFixed(2)),
        candidate_lanes: ["LIVE_HKCONNECT_GAINER"],
        current_change_pct: Number((2.5 + index / 10).toFixed(2)),
        pct_chg: Number((4.5 + index / 10).toFixed(2)),
        volume_ratio: Number((1.2 + index / 10).toFixed(2)),
        turnover: 20000000 + index * 1000000,
      })),
    },
  },
  unified_rows: [],
  write_performed: false,
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
};

const managerPriorityStageRow = (code: string, name: string, rank: number, overrides: Record<string, unknown> = {}) => ({
  market: "HK_CONNECT",
  code: `HK.${code}`,
  name,
  rank,
  stage_score: 80 - rank,
  current_change_pct: 1.2,
  pct_chg: 2.4,
  volume_ratio: 1.1,
  turnover: 1000000,
  source_last_bar_time: "2026-09-08 09:40:00",
  ...overrides,
});

const managerPriorityStageFor = (
  targetDate: string,
  rows: readonly Record<string, unknown>[],
  status: "READY" | "CANNOT_CONFIRM" = "READY",
) => ({
  ...managerStageSelection,
  trade_date: targetDate,
  status,
  cannot_confirm: status === "READY" ? [] : ["SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"],
  markets: {
    ...managerStageSelection.markets,
    HK: {
      ...managerStageSelection.markets.HK,
      status,
      selection_status: status,
      selected_rows: rows.length,
      rows: [...rows],
    },
  },
});

const managerPriorityFacts = (targetDate: string, code: string) => ({
  code: `HK.${code}`,
  target_trade_date: targetDate,
  source: {
    published_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T08:30:00+08:00`,
    retrieved_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T10:00:00+08:00`,
    sha256: "f".repeat(64),
  },
  facts: [
    {
      fact_type: "OFFICIAL_FACT",
      fields: {
        label_cn: "净利润",
        period_label_cn: "截至六个月 2026年6月30日",
        values: [{ column: "2026", raw: "20" }, { column: "2025", raw: "10" }],
      },
      source_sha256: "f".repeat(64),
    },
    {
      fact_type: "OFFICIAL_FACT",
      fields: {
        label_cn: "经营活动现金流量净额",
        period_label_cn: "截至六个月 2026年6月30日",
        values: [{ column: "2026", raw: "30" }, { column: "2025", raw: "5" }],
      },
      source_sha256: "f".repeat(64),
    },
  ],
  confirmation_conditions: ["下一阶段确认价格承接"],
  invalidation_conditions: ["现金流转弱"],
  research_recommendation: {
    investment_advice: {
      action: "WATCH",
      label_cn: "研究观察",
      status: "GENERATED",
      summary: "后端同报告期研究意见：经营事实待观察。",
      coverage_scope: "仅依据已解析官方财报结构化事实；近期重大事件（含合作/公告）覆盖未确认。",
      priority_rank: code === "00001" ? 1 : 2,
      priority_reason: code === "00001" ? "后端优先级理由一" : "后端优先级理由二",
      basis: [
        {
          dimension: "profit_loss",
          state: "POSITIVE",
          current: "20",
          previous: "10",
          current_column: "2026",
          previous_column: "2025",
          period: "截至六个月 2026年6月30日",
          currency: "RMB",
          unit: "thousands",
          fact_refs: [{ source_sha256: "f".repeat(64), locator: "PDF page 1", page: 1 }],
        },
      ],
    },
    execution_gate: { status: "BLOCKED", action_level: "NO_BUY" },
    as_of: { target_trade_date: targetDate },
  },
});

const pendingManagerStageFor = (targetDate: string) => managerPriorityStageFor(targetDate, [], "CANNOT_CONFIRM");

const managerDecisionResponseFor = (selectionPayload: unknown): Record<string, unknown> => {
  const selection = selectionPayload as Record<string, unknown>;
  const targetDate = typeof selection.target_trade_date === "string" ? selection.target_trade_date : "20260831";
  const candidates = Array.isArray(selection.research_candidates) ? selection.research_candidates : [];
  const snapshot = (selection.snapshots as Record<string, unknown> | undefined)?.["2200"] as Record<string, unknown> | undefined;
  const sourceDate = typeof selection.source_date === "string" ? selection.source_date : null;
  const runId = typeof snapshot?.run_id === "string" ? snapshot.run_id : null;
  const generatedAt = typeof snapshot?.event_at === "string" ? snapshot.event_at : null;
  const candidateIds = new Set(
    candidates
      .map((item) => (item as Record<string, unknown>).candidate_id)
      .filter((id): id is string => typeof id === "string"),
  );
  const snapshotIds = Array.isArray(snapshot?.candidate_ids)
    ? snapshot.candidate_ids.filter((id): id is string => typeof id === "string")
    : [];
  const rowFor = (code: string) => ({
    candidate_id: `HK.${code}|${code}.HK`,
    reason: managerReasons[code],
  });
  const core = managerCoreCodes.map(rowFor);
  const conditional = managerConditionalCodes.map(rowFor);
  if (
    snapshot?.status !== "READY"
    || !sourceDate
    || !runId
    || !generatedAt
    || snapshotIds.length !== managerCoreCodes.length + managerConditionalCodes.length
    || !snapshotIds.every((id) => candidateIds.has(id))
    || [...core, ...conditional].some((row) => !candidateIds.has(row.candidate_id))
  ) {
    return {
      schema_version: "v3_5.manager_research_decision_read.v1",
      document_schema_version: "v3_5.manager_research_decision.v1",
      endpoint_mode: "EXACT",
      requested_date: targetDate,
      target_trade_date: targetDate,
      status: "CANNOT_CONFIRM",
      source_date: null,
      phase: null,
      decision_state: null,
      run_id: null,
      generated_at: null,
      cutoff_at: null,
      core: [], conditional: [], KEEP: [], ADD: [], REMOVE: [], qualification_refs: [],
      safety: { RESEARCH_ONLY: true, WATCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false },
      lineage: null,
      reason: null,
      cannot_confirm: ["MANAGER_DECISION_FIXTURE_UNAVAILABLE"],
    };
  }
  const decisionIds = [...core, ...conditional].map((row) => row.candidate_id);
  return {
    schema_version: "v3_5.manager_research_decision_read.v1",
    document_schema_version: "v3_5.manager_research_decision.v1",
    endpoint_mode: "EXACT",
    requested_date: targetDate,
    target_trade_date: targetDate,
    status: "READY",
    source_date: sourceDate,
    phase: "2200",
    decision_state: "INITIAL_RESEARCH_DELTA",
    run_id: runId,
    generated_at: generatedAt,
    cutoff_at: typeof selection.cutoff_at === "string" ? selection.cutoff_at : generatedAt,
    core,
    conditional,
    KEEP: [],
    ADD: [...core, ...conditional],
    REMOVE: candidates.some((item) => (item as Record<string, unknown>).candidate_id === "HK.09926|09926.HK")
      ? [{ candidate_id: "HK.09926|09926.HK", reason: "旧条件研究不纳入当前经理集合" }]
      : [],
    qualification_refs: decisionIds.map((candidateId) => ({ candidate_id: candidateId, status: "ELIGIBILITY_CANNOT_CONFIRM", raw_sha256: null })),
    safety: { RESEARCH_ONLY: true, WATCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false },
    lineage: {
      selection_artifact_sha256: (selection.lineage as Record<string, unknown> | undefined)?.artifact_sha256 || "a".repeat(64),
      selection_run_id: typeof selection.run_id === "string" ? selection.run_id : null,
      manager_decision_raw_sha256: managerDecisionRef.raw_sha256,
      source_date: sourceDate,
      target_trade_date: targetDate,
    },
    reason: null,
    cannot_confirm: [],
  };
};

const managerDecisionNotMaterializedResponse = (targetDate = "20260831"): Record<string, unknown> => ({
  schema_version: "v3_5.manager_research_decision_read.v1",
  document_schema_version: "v3_5.manager_research_decision.v1",
  endpoint_mode: "EXACT",
  requested_date: targetDate,
  target_trade_date: targetDate,
  status: "NOT_MATERIALIZED",
  source_date: null,
  phase: null,
  decision_state: null,
  run_id: null,
  generated_at: null,
  cutoff_at: null,
  core: [],
  conditional: [],
  KEEP: [],
  ADD: [],
  REMOVE: [],
  qualification_refs: [],
  safety: {
    RESEARCH_ONLY: true,
    WATCH_ONLY: true,
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
  },
  lineage: null,
  reason: "SELECTION_PRODUCT_NOT_MATERIALIZED",
  cannot_confirm: [],
});

const managerResearchPayloadFor = (
  targetDate: string,
  rows: readonly Record<string, unknown>[] = [],
): Record<string, unknown> => ({
  schema_version: "v4.manager_research.product.v1",
  target_trade_date: targetDate,
  stage_id: "STAGE_0935_0940",
  market: "HK_CONNECT",
  status: "READY",
  product: {
    schema_version: "v4.manager_research.product.v1",
    target_trade_date: targetDate,
    stage_id: "STAGE_0935_0940",
    market: "HK_CONNECT",
  rows,
  recommendation_summary: {
    investment_advice_counts: { BUY: 0, CONDITIONAL_BUY: 0, WATCH: rows.length, AVOID: 0, DATA_INSUFFICIENT: 0 },
  },
    RESEARCH_ONLY: true,
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
  },
  RESEARCH_ONLY: true,
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
});

const managerResearchNullProductFor = (
  targetDate: string,
  status: "NOT_MATERIALIZED" | "CANNOT_CONFIRM" | "RUNNING" = "NOT_MATERIALIZED",
): Record<string, unknown> => ({
  schema_version: "v4.manager_research.product.v1",
  target_trade_date: targetDate,
  stage_id: "STAGE_0935_0940",
  market: "HK_CONNECT",
  status,
  product: null,
  job: status === "RUNNING" ? { status: "RUNNING", job_id: "mr-fixture" } : null,
  can_ensure: status !== "RUNNING",
  can_retry: status === "CANNOT_CONFIRM",
  cannot_confirm: status === "NOT_MATERIALIZED" ? ["STAGE_NOT_MATERIALIZED"] : [],
  RESEARCH_ONLY: true,
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
});

const workbenchMissingFor = (targetDate: string, status = "INPUT_MISSING") => ({
  schema_version: "v4.manager_workbench.research.v1",
  market: "HK_CONNECT",
  trade_date: targetDate,
  slot: "1530",
  as_of: null,
  generated_at: null,
  run_id: null,
  status,
  rule_version: "manager-workbench-b1-contract-v1",
  cache_key: `${targetDate}|HK_CONNECT|1530|manager-workbench-b1-contract-v1`,
  universe: null,
  coverage: { eligible_count: null, covered_count: null, missing_count: null, missing_reasons: ["SIMULATED_TEST_GAP"] },
  cannot_confirm: ["SIMULATED_TEST_GAP"],
  priority_summary: { focus: [], theme_changes: [], risk_upgrades: [] },
  candidates: [],
  RESEARCH_ONLY: true,
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
});

const workbenchSimulatedFor = (targetDate: string) => ({
  schema_version: "v4.manager_workbench.research.v1",
  market: "HK_CONNECT",
  trade_date: targetDate,
  slot: "1530",
  as_of: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:30:00+08:00`,
  generated_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:31:00+08:00`,
  run_id: `SIM-WORKBENCH-${targetDate}`,
  status: "PARTIAL",
  rule_version: "manager-workbench-b1-simulated-v1",
  cache_key: `${targetDate}|HK_CONNECT|1530|manager-workbench-b1-simulated-v1`,
  universe: { owner: "SIMULATED_FIXTURE", role: "HK_CONNECT_UNIVERSE_FIXTURE", artifact_ref: "simulated/universe.json", manifest_ref: null, receipt_ref: null, run_id: `SIM-UNIVERSE-${targetDate}`, sha256: "a".repeat(64), source_date: targetDate, market: "HK_CONNECT", lane: null, reason: "SIMULATED universe lineage", observed_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:29:00+08:00`, available_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:29:30+08:00` },
  coverage: { eligible_count: 3, covered_count: 2, missing_count: 1, missing_reasons: ["SIMULATED_ONE_MISSING"] },
  cannot_confirm: ["SIMULATED_B2_NOT_IMPLEMENTED"],
  priority_summary: {
    focus: [{ item_id: "sim-focus", candidate_id: "sim-minimax", name: "MINIMAX-W（SIMULATED）", occurred_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:30:00+08:00`, reason: "SIMULATED：同股多来源展示", evidence_status: "SIMULATED_PARTIAL", kind: "FOCUS" }],
    theme_changes: [],
    risk_upgrades: [{ item_id: "sim-risk", candidate_id: "sim-extra", name: "模拟尾盘候选（SIMULATED）", occurred_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:30:00+08:00`, reason: "SIMULATED：风险样式测试", evidence_status: "SIMULATED_PARTIAL", kind: "RISK_UPGRADED" }],
  },
  candidates: [
    {
      candidate_id: "sim-minimax", symbol: "HK.00100", name: "MINIMAX-W（SIMULATED）", source_lanes: ["CLOSE_DISCOVERY", "CONTINUOUS_TRACKING"],
      first_seen_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:20:00+08:00`, last_seen_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:30:00+08:00`, observed_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:30:00+08:00`, available_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:30:00+08:00`,
      turnover_amount: { value: 123000000, currency: "HKD", unit: "HKD", as_of: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:30:00+08:00` }, volume_comparison: { state: "unknown", ratio: null, baseline_as_of: null, reason: "SIMULATED" }, position: { state: "unknown", label: "待确认", reason: "SIMULATED" }, catalyst: { summary: "SIMULATED：不代表真实催化", status: "SIMULATED_PARTIAL" }, research_priority: { level: "WATCH", previous_level: "WATCH", change_reason: "SIMULATED" }, data_status: "SIMULATED_PARTIAL", attention_reason: "SIMULATED：验证阶段候选与研究来源合并", predicates: [{ predicate_id: "B1_FIXTURE", value: true, reason: "SIMULATED fixture存在", input_refs: ["simulated/fixture"], rule_version: "v1" }],
      sources: [{ owner: "SIMULATED_FIXTURE", role: "CLOSE_DISCOVERY_FIXTURE", artifact_ref: "simulated/close.json", manifest_ref: null, receipt_ref: null, run_id: "SIM-CLOSE", sha256: "b".repeat(64), source_date: targetDate, market: "HK_CONNECT", lane: "CLOSE_DISCOVERY", reason: "SIMULATED close reason", observed_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:30:00+08:00`, available_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:30:00+08:00` }, { owner: "SIMULATED_FIXTURE", role: "CONTINUOUS_TRACKING_FIXTURE", artifact_ref: "simulated/watch.json", manifest_ref: null, receipt_ref: null, run_id: "SIM-WATCH", sha256: "d".repeat(64), source_date: targetDate, market: "HK_CONNECT", lane: "CONTINUOUS_TRACKING", reason: "SIMULATED watch reason", observed_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:29:00+08:00`, available_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:29:30+08:00` }], risks: [], observation_plan: { triggers: ["等待真实证据"], invalidation_conditions: ["合同失败"], missing_evidence: ["B2/B3"] }, qualified: null, trade_date: targetDate,
    },
    {
      candidate_id: "sim-extra", symbol: "HK.01234", name: "模拟尾盘候选（SIMULATED）", source_lanes: ["CLOSE_DISCOVERY"],
      first_seen_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:30:00+08:00`, last_seen_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:30:00+08:00`, observed_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:30:00+08:00`, available_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:30:00+08:00`,
      turnover_amount: { value: 125000000, currency: "HKD", unit: "HKD", as_of: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:30:00+08:00` }, volume_comparison: null, position: null, catalyst: null, research_priority: { level: "WATCH", previous_level: null, change_reason: "SIMULATED" }, data_status: "SIMULATED_PARTIAL", attention_reason: "SIMULATED：验证原Top100外的B1展示合同，不代表真实扫描", predicates: [{ predicate_id: "B1_FIXTURE", value: true, reason: "SIMULATED fixture存在", input_refs: ["simulated/fixture"], rule_version: "v1" }],
      sources: [{ owner: "SIMULATED_FIXTURE", role: "CLOSE_DISCOVERY_FIXTURE", artifact_ref: "simulated/extra.json", manifest_ref: null, receipt_ref: null, run_id: "SIM-EXTRA", sha256: "c".repeat(64), source_date: targetDate, market: "HK_CONNECT", lane: "CLOSE_DISCOVERY", reason: "SIMULATED extra reason", observed_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:30:00+08:00`, available_at: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:30:00+08:00` }], risks: [], observation_plan: { triggers: ["等待真实证据"], invalidation_conditions: ["合同失败"], missing_evidence: ["B2/B3"] }, qualified: null, trade_date: targetDate,
    },
  ],
  RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false,
});

const managerWorkspaceFor = (targetDate: string) => {
  const strict = {
    classification: "STRICT_REBOUND",
    qualification_status: "RESEARCH_ONLY_CANDIDATE",
    code: "HK.09998",
    name: "测试严格",
    target_monday: targetDate,
    history_status: "KNOWN",
    prior60_session_count: 60,
    amount_hkd: 120000000,
    oversold_flag: true,
    volume_ratio_5d: 1.8,
    rebound_close_vs_low_pct: 3.4,
  };
  const pending = {
    classification: null,
    qualification_status: "RESEARCH_ONLY_CANDIDATE",
    code: "HK.09999",
    name: "测试待核",
    target_monday: targetDate,
    history_status: "PARTIAL_UNKNOWN",
    history_unknown_reasons: "PRIOR_60_SESSIONS_INCOMPLETE:51",
    prior60_session_count: 51,
    amount_hkd: 130000000,
    oversold_flag: null,
    volume_ratio_5d: null,
    rebound_close_vs_low_pct: null,
  };
  const lane = (name: "STAGE" | "CATALYST" | "CLOSE") => ({
    lane: name, owner: `SIMULATED_${name}`, state: "NOT_RUN", target_date: targetDate,
    stock_count: null, last_attempt_at: null, last_success_at: null, run_id: null,
    execution_kind: "READ_ONLY", failure_reasons: [], next_plan: null,
    schedule_status: "UNBOUND", input_coverage: {},
  });
  return {
    RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false,
    semantic_version: "20260921.manager-semantic.r3.v1", focus_symbols: [], briefing: {}, company_events: [], rejected_relations: [],
    schema_version: "v4.manager_research.workspace.v1", target_trade_date: targetDate,
    input_identity: `${targetDate}${"a".repeat(56)}`, stocks: [], lanes: [lane("STAGE"), lane("CATALYST"), lane("CLOSE")],
    themes: [], materials: [], gaps: [],
    summary: { stock_count: 0, relation_count: 0, theme_count: 0, reused_material_count: 0, formal_recommendation_count: 0 },
    plan_context: {
      plan_trade_date: targetDate, market_session: targetDate, market_data_verified: true,
      research_cutoff: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:30:00+08:00`,
    },
    plan_product: { status: "NOT_MATERIALIZED", consumed: false },
    read_context: {
      mode: "CURRENT_DYNAMIC_PREVIEW", status: "NOT_MATERIALIZED",
      contract: "20260923.workspace-history-read.r1", candidate_count_known: false,
      as_of: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6)}T15:30:00+08:00`,
    },
    market_screen: {
      schema_version: "v4.manager_research.rebound_v3_screen.v1", rule_version: "TEST_REBOUND_V3",
      target_trade_date: targetDate, verified_session: targetDate, status: "READY_WITH_GAPS",
      cards: [strict], strict: [strict], near: [], pending: [pending], gaps: ["SCREEN_PRIOR_60_INCOMPLETE:HK.09999"],
      coverage: { amount_gate_candidate_count: 2, history_complete_count: 1, history_pending_count: 1,
        strict_count: 1, near_candidate_count: 0, near_selected_count: 0, selected_count: 1 },
      input_identity: `${"b".repeat(64)}`, authority: null,
      RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false,
      main_screen_ready: true, longlist_target: 10,
    },
  };
};

const stubFetch = (selectionPayload: unknown, preselectionPayload: unknown = preselection) => {
  const fetchMock = vi.fn(async (url: string) => {
    if (url.includes("/api/v3/preselection-pools")) return response(preselectionPayload);
    if (url.includes("/api/v3/manager/stage-selection")) return response(managerStageSelection);
    if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(selectionPayload));
    if (url.includes("/api/v4/manager/research/workspace")) {
      const targetDate = new URL(url, "http://test").searchParams.get("date") || "20260831";
      return response(managerWorkspaceFor(targetDate));
    }
    if (url.includes("/api/v4/manager/research/catalyst-observations")) return response({
      schema_version: "v4.manager_research.catalyst_observations.v1",
      target_trade_date: new URL(url, "http://test").searchParams.get("date") || "20260831",
      status: "EMPTY", cards: [], gaps: ["SIMULATED_CATALYST_NOT_MATERIALIZED"], can_refresh: true,
      stage_dependency: false, quote_dependency: false, input_bindings: [], generated_at: null,
      RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false,
    });
    if (url.includes("/api/v4/manager/workbench-research")) {
      const targetDate = new URL(url, "http://test").searchParams.get("date") || "20260831";
      return response(workbenchMissingFor(targetDate));
    }
    return response(selectionPayload);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
};

const withoutField = <T extends object>(value: T, field: string): Partial<T> => {
  const copy = { ...value } as Partial<T>;
  delete (copy as Record<string, unknown>)[field];
  return copy;
};

const canonicalValue = (value: unknown): unknown => {
  if (Array.isArray(value)) return value.map((item) => canonicalValue(item));
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.keys(value as Record<string, unknown>)
      .sort()
      .map((key) => [key, canonicalValue((value as Record<string, unknown>)[key])]),
  );
};

const canonicalSha = async (value: unknown): Promise<string> => {
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(JSON.stringify(canonicalValue(value))),
  );
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
};

const withSnapshotSha = async <T extends Record<string, unknown>>(snapshot: T): Promise<T> => ({
  ...snapshot,
  snapshot_sha256: await canonicalSha(withoutField(snapshot, "snapshot_sha256")),
});

const rebindLineage = (lineage: Record<string, unknown>, previousRunId: string, runId: string) => Object.fromEntries(
  Object.entries(lineage).map(([key, value]) => [
    key,
    typeof value === "string" && key.endsWith("_path")
      ? value.replace(previousRunId, runId)
      : key === "run_id" ? runId : value,
  ]),
);

const compatibleLineage = (runId: string) => rebindLineage(product.lineage, product.run_id, runId);

const compatible0830Product = async (candidateIds: string[], changes: Array<Record<string, string>> = []) => {
  const runId = "manager-compat-20260831-0830";
  const snapshot0830 = await withSnapshotSha({
    phase: "0830",
    status: "READY",
    run_id: runId,
    event_at: "2026-08-31T08:30:00+08:00",
    artifact_sha256: "a".repeat(64),
    candidate_ids: candidateIds,
    changes,
    freeze_run_id: null,
    freeze_snapshot_sha256: null,
    snapshot_sha256: null,
  });
  return {
    ...product,
    run_id: runId,
    generated_at: "2026-08-31T08:30:00+08:00",
    status: "READY_WITH_DECLARED_GAPS",
    snapshots: { ...product.snapshots, "0830": snapshot0830 },
    cannot_confirm: [
      "FORMAL_AUTHORITY_NOT_MATERIALIZED",
      "SNAPSHOT_0935_NOT_MATERIALIZED",
      "SNAPSHOT_1620_NOT_MATERIALIZED",
    ],
    first_failed_layer: "FORMAL_AUTHORITY_NOT_MATERIALIZED",
    lineage: compatibleLineage(runId),
  };
};

const typedFormalProduct = () => {
  const candidateId = managerFocusCandidateId;
  const authorityRun = "formal-authority-run-20260831";
  const sourceSha = "c".repeat(64);
  const binding = {
    candidate_id: candidateId,
    eligibility: "ELIGIBLE",
    pit_status: "READY",
    source_refs: [sourceRef],
  };
  const evidence = {
    schema_version: "v3_5.selection_formal_evidence.v1",
    type: "EXACT_DATE_PIT",
    path: "/research/formal/evidence.json",
    sha256: "d".repeat(64),
    source_sha256: sourceSha,
    source_date: "20260828",
    target_trade_date: "20260831",
    run_id: authorityRun,
    candidate_ids: [candidateId],
    status: "READY",
    pit_status: "READY",
    candidate_bindings: [binding],
  };
  const decision = {
    schema_version: "v3_5.selection_manager_decision.v1",
    type: "MANAGER_DECISION",
    path: "/research/formal/decision.json",
    sha256: "e".repeat(64),
    source_sha256: sourceSha,
    source_date: "20260828",
    target_trade_date: "20260831",
    run_id: authorityRun,
    candidate_ids: [candidateId],
    decision: true,
    candidate_bindings: [binding],
  };
  return {
    ...product,
    research_candidates: product.research_candidates.map((item) => item.candidate_id === candidateId
      ? { ...item, eligibility: "ELIGIBLE" }
      : item),
    formal_shortlist: [candidateId],
    counts: { ...product.counts, formal_shortlist: 1 },
    status: "READY_WITH_DECLARED_GAPS",
    cannot_confirm: ["SNAPSHOT_0830_NOT_MATERIALIZED", "SNAPSHOT_0935_NOT_MATERIALIZED", "SNAPSHOT_1620_NOT_MATERIALIZED"],
    first_failed_layer: "SNAPSHOT_0830_NOT_MATERIALIZED",
    formal_authority: {
      status: "READY",
      target_trade_date: "20260831",
      pit_status: "READY",
      selector_status: "READY",
      research_evidence: true,
      manager_decision: true,
      source_sha256: sourceSha,
      evidence_refs: [evidence],
      manager_decision_ref: decision,
    },
  };
};

const compatibleLaterProduct = async () => {
  const base = await compatible0830Product(managerSnapshotCandidateIds);
  const freeze = base.snapshots["0830"];
  const freezeRunId = freeze.run_id;
  const freezeSnapshotSha = freeze.snapshot_sha256;
  const snapshot0935 = await withSnapshotSha({
    phase: "0935",
    status: "READY",
    run_id: "manager-compat-20260831-0935",
    event_at: "2026-08-31T09:35:00+08:00",
    artifact_sha256: "b".repeat(64),
    candidate_ids: managerSnapshotCandidateIds,
    changes: [],
    freeze_run_id: freezeRunId,
    freeze_snapshot_sha256: freezeSnapshotSha,
    snapshot_sha256: null,
  });
  const snapshot1620 = await withSnapshotSha({
    phase: "1620",
    status: "READY",
    run_id: "manager-compat-20260831-1620",
    event_at: "2026-08-31T16:20:00+08:00",
    artifact_sha256: "d".repeat(64),
    candidate_ids: managerSnapshotCandidateIds,
    changes: [],
    freeze_run_id: freezeRunId,
    freeze_snapshot_sha256: freezeSnapshotSha,
    snapshot_sha256: null,
  });
  return {
    ...base,
    run_id: "manager-compat-20260831-1620",
    generated_at: "2026-08-31T16:20:00+08:00",
    snapshots: { ...base.snapshots, "0935": snapshot0935, "1620": snapshot1620 },
    intraday_observations: [{
      kind: "APPEND_ONLY",
      candidate_id: managerFocusCandidateId,
      freeze_run_id: freezeRunId,
      freeze_snapshot_sha256: freezeSnapshotSha,
      observed_at: "2026-08-31T09:35:00+08:00",
    }],
    outcomes: [{
      kind: "OUTCOME_REFERENCE",
      candidate_id: managerFocusCandidateId,
      freeze_run_id: freezeRunId,
      freeze_snapshot_sha256: freezeSnapshotSha,
      observed_at: "2026-08-31T16:20:00+08:00",
    }],
    counts: { ...base.counts, intraday_observations: 1, outcomes: 1 },
    cannot_confirm: ["FORMAL_AUTHORITY_NOT_MATERIALIZED"],
    first_failed_layer: "FORMAL_AUTHORITY_NOT_MATERIALIZED",
    lineage: rebindLineage(base.lineage, base.run_id, "manager-compat-20260831-1620"),
  };
};

const selectionForDate = (targetDate: string) => ({
  ...product,
  research_candidates: product.research_candidates.map((candidate) => {
    const { manager_decision: _managerDecision, ...wireCandidate } = candidate as Record<string, unknown>;
    return wireCandidate;
  }),
  run_id: product.run_id.replace("20260831", targetDate),
  target_trade_date: targetDate,
  requested_date: targetDate,
  manager_decision_ref: product.manager_decision_ref
    ? { ...product.manager_decision_ref, path: product.manager_decision_ref.path.replace("20260831", targetDate) }
    : product.manager_decision_ref,
  formal_authority: { ...product.formal_authority, target_trade_date: targetDate },
  lineage: Object.fromEntries(
    Object.entries(product.lineage).map(([key, value]) => [
      key,
      key === "target_trade_date"
        ? targetDate
        : key === "run_id"
          ? product.run_id.replace("20260831", targetDate)
          : key.endsWith("_path") && typeof value === "string"
            ? value.replace(product.run_id, product.run_id.replace("20260831", targetDate)).replaceAll("20260831", targetDate)
            : value,
    ]),
  ),
});

const taggedPreselection = (targetDate: string, tag: string) => {
  const base = preselectionForDate(targetDate);
  return {
    ...base,
    pools: base.pools.map((pool) => ({
      ...pool,
      rows: pool.rows?.map((row) => ({
        ...row,
        stock_name: `${tag}-${row.stock_name}`,
      })),
    })),
  };
};

const disjointPreselection = (targetDate: string) => {
  const base = preselectionForDate(targetDate);
  return {
    ...base,
    pools: base.pools.map((pool) => ({
      ...pool,
      rows: pool.rows?.map((row, index) => {
        const code = String(50000 + index);
        return {
          ...row,
          symbol: `HK.${code}`,
          code: `HK.${code}`,
          code_norm: `HK.${code}`,
          ts_code: `${code}.HK_CONNECT`,
          stock_name: `D-1无交集研究标的${code}`,
          name: `D-1无交集研究标的${code}`,
          display_name: `D-1无交集研究标的${code}`,
        };
      }),
    })),
  };
};

const joinConflictCandidate = {
  ...candidate,
  candidate_id: "HK.5|5.HK",
  event_stock_link_id: "EVENT_RESEARCH_5|HK.5|5.HK",
  normalized_code: "5",
  entity_id: "5.HK",
  event_id: "EVENT_RESEARCH_5",
  bucket: "EVENT_RESEARCH_MAP",
  source_metadata: { supply_card: { entity: "ISSUER_5", price_reaction: { name: "研究候选冲突" } } },
};

const joinFailureCandidates = [...researchCandidates, joinConflictCandidate]
  .sort((left, right) => left.candidate_id.localeCompare(right.candidate_id));
const joinFailureProduct = {
  ...product,
  research_candidates: joinFailureCandidates,
  source_refs: joinFailureCandidates.flatMap((item) => item.source_refs || []),
  counts: { ...product.counts, research_candidates: joinFailureCandidates.length },
};

const missingProduct = (
  status: "NOT_MATERIALIZED" | "CANNOT_CONFIRM",
  reason: string,
  targetDate = "20260831",
) => ({
  ...withoutField(
    withoutField(
      withoutField(
        withoutField(product, "artifact_sha256"),
        "manifest_sha256",
      ),
      "receipt_sha256",
    ),
    "current_sha256",
  ),
  source_date: null,
  target_trade_date: targetDate,
  requested_date: targetDate,
  cutoff_at: null,
  generated_at: null,
  run_id: null,
  origin: null,
  status,
  acceptance: "NOT_MATERIALIZED",
  research_candidates: [],
  formal_shortlist: [],
  source_refs: [],
  snapshots: Object.fromEntries(["2200", "0830", "0935", "1620"].map((phase) => [phase, missingSnapshot(phase)])),
  counts: { ...product.counts, research_candidates: 0, formal_shortlist: 0 },
  route_status: { R1: "NOT_MATERIALIZED", R2: "NOT_MATERIALIZED", R6: "NOT_MATERIALIZED", GEMINI: "NOT_MATERIALIZED" },
  gemini_status: "NOT_MATERIALIZED",
  formal_authority: { ...product.formal_authority, status, target_trade_date: targetDate, manager_decision_ref: null },
  first_failed_layer: reason,
  cannot_confirm: [reason],
  manager_decision_ref: null,
  lineage: null,
});

const managerSelectionCss = readFileSync(resolve(process.cwd(), "src/styles/manager-selection.css"), "utf8");
const managerSelectionIndex = readFileSync(resolve(process.cwd(), "manager-selection/index.html"), "utf8");

// Use the current user interaction; never expose collapsed content by DOM mutation.
async function openOriginalSources() {
  // Large 124-row synthetic ledger: wait on its cheap state attribute before
  // querying the whole accessibility tree, rather than racing async decoding.
  await waitFor(() => expect(document.querySelector('main')?.getAttribute('data-state')).not.toBe('LOADING'), {timeout:5000});
  const sources = await waitFor(() => {
    const node=document.querySelector<HTMLDetailsElement>('details.manager-original-sources');
    expect(node).not.toBeNull();return node!;
  });
  if (!sources.open) await fireEvent.click(sources.querySelector(':scope > summary')!);
  await waitFor(() => expect(sources.open).toBe(true));
}

// Large 124-row original UI: retain every assertion with a bounded CI budget.
describe("ManagerSelectionView", {timeout:15000}, () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    window.history.replaceState({}, "", "/manager-selection/");
  });

  it("does not force a positive body minimum that overflows a 320px viewport", () => {
    const bodyRule = managerSelectionCss.match(/body\s*\{[^}]*\}/)?.[0];

    expect(bodyRule).toBeTruthy();
    expect(bodyRule).not.toMatch(/min-width\s*:\s*(?!0(?:\.0+)?(?:px)?\b)[1-9][\d.]*(?:px|rem|em|ch|vw)?/i);
  });

  it("lets narrow ledger controls shrink below an intrinsic select minimum", () => {
    expect(managerSelectionCss).toMatch(/\.ledger-tools\s*\{\s*grid-template-columns:\s*minmax\(0,\s*1fr\)/);
  });

  it("brands the static entry as V4", async () => {
    expect(managerSelectionIndex).toContain("<title>经理选股工作台 · V4</title>");
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    stubFetch(product);

    render(ManagerSelectionView);

    expect(await screen.findByText("V4 · 股票研究")).toBeTruthy();
  });

  it("selects the canonical default date when no date is requested", async () => {
    window.history.replaceState({}, "", "/manager-selection/");
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return response({ ok: true, default_date: "20260831", dates: ["20260831"], stage_dates: [], future_target_dates: [] });
      }
      if (url.includes("/api/v3/preselection-pools")) return response(preselection);
      if (url.includes("/api/v3/manager/stage-selection")) return response(managerStageSelection);
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(product));
      return response(product);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    expect(await screen.findByText("124 条 research ledger（研究账本）")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/runs/date-list", expect.objectContaining({ cache: "no-store" }));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v3/research/selection?target_trade_date=20260831",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
    );
    expect(window.location.search).toBe("?date=20260831");
  });

  it("keeps the explicit-selection prompt when the date catalog is unavailable", async () => {
    window.history.replaceState({}, "", "/manager-selection/");
    const fetchMock = vi.fn(async (_url: string) => ({ ok: false, status: 503, json: async () => ({}) }));
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    expect(await screen.findByText("未选择")).toBeTruthy();
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual(["/api/v1/runs/date-list"]);
  });

  it("reads one exact target date and renders the manager ledger without promotion", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const fetchMock = stubFetch(product);

    expect(product.research_candidates).toHaveLength(124);
    expect(product.research_candidates.filter((item) => item.bucket === "CONDITIONAL_RESEARCH_MAP").map((item) => item.candidate_id))
      .toEqual(["HK.09926|09926.HK"]);
    expect(product.formal_shortlist).toEqual([]);
    expect(product.snapshots["2200"].status).toBe("READY");
    expect(product.snapshots["0830"].status).toBe("NOT_MATERIALIZED");
    expect(product.snapshots["0935"].status).toBe("NOT_MATERIALIZED");
    expect(product.snapshots["1620"].status).toBe("NOT_MATERIALIZED");

    const { container } = render(ManagerSelectionView);

    expect(await screen.findByRole("heading", { level: 1, name: "经理选股工作台" })).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v3/research/selection?target_trade_date=20260831",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v3/preselection-pools?date=20260831&limit=200",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v3/manager/stage-selection?date=20260831&stage=STAGE_0935_0940&limit=50&market=HK_CONNECT",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v3/research/selection/manager-decision?target_trade_date=20260831",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
    );
    expect(fetchMock).toHaveBeenCalledTimes(10);
    for (const endpoint of ['', '/analysis']) {
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/v4/manager/research/announcements${endpoint}?date=20260831`,
        expect.objectContaining({cache:'no-store',signal:expect.any(AbortSignal)}),
      );
    }
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v4/manager/research/workspace?date=20260831&view=auto",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
    );
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/v4/manager/research/catalyst-observations"))).toHaveLength(0);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v4/manager/research?date=20260831",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v3/research/lane?research_date=20260831",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v4/manager/workbench-research?date=20260831&market=HK_CONNECT&slot=1530",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
    );
    expect(await screen.findByText("READY_WITH_DECLARED_GAPS")).toBeTruthy();
    expect(screen.getAllByText("20260831").length).toBeGreaterThan(0);
    expect(screen.getAllByText("20260828").length).toBeGreaterThan(0);
    expect(screen.getByText("MANUAL_RECOVERY")).toBeTruthy();
    expect(screen.getAllByText("124 条研究候选").length).toBeGreaterThan(0);
    expect(screen.getByText(managerReasons["02315"])).toBeTruthy();
    expect(screen.getAllByText("官方中报收入同比增长51.6%。").length).toBeGreaterThan(0);
    expect(screen.queryByText("康方生物")).toBeNull();
    expect(screen.getByText("08:00 第二版（协议槽 08:30）")).toBeTruthy();
    expect(screen.getAllByText("CANNOT_CONFIRM_PHASE_MAPPING").length).toBeGreaterThan(0);
    expect(screen.getAllByText("FORMAL_AUTHORITY_NOT_MATERIALIZED").length).toBeGreaterThan(0);
    expect(screen.getByText("artifact_sha256")).toBeTruthy();
    expect(screen.getByText("648010bfb763313ce27708e3b00aaf74f4e401b0f1aa16c6e53517c0347c9acb")).toBeTruthy();
    expect(screen.getByText("RESEARCH_ONLY=true")).toBeTruthy();
    expect(screen.getByText("production_allowed=false")).toBeTruthy();
    expect(screen.getByText("buy_gate_updated=false")).toBeTruthy();
    expect(screen.getByText("orders_sent=false")).toBeTruthy();
    expect(container.textContent).not.toContain("/api/v3/research/selection\n");
    expect(fetchMock.mock.calls.flat().join(" ")).not.toMatch(/POST|PUT|PATCH|DELETE|manager-decision\.json/);
  }, 15000); // 124-row DOM plus full evidence assertions under parallel CI load.

  it("binds the workspace screen to the selected date and clears cards on a failed read", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    let failWorkspace = false;
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v4/manager/research/workspace")) {
        const targetDate = new URL(url, "http://test").searchParams.get("date") || "20260831";
        if (failWorkspace) throw new Error("simulated workspace read failure");
        return response(managerWorkspaceFor(targetDate));
      }
      if (url.includes("/api/v3/preselection-pools")) return response(preselection);
      if (url.includes("/api/v3/manager/stage-selection")) return response(managerStageSelection);
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(product));
      return response(product);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);
    const screenPanel = await screen.findByRole("region", { name: "REBOUND_V3量价筛选" });
    await waitFor(() => expect(within(screenPanel).getByText(/测试严格/)).toBeTruthy());
    await fireEvent.click(within(screenPanel).getByText(/^待核历史（1）/));
    await waitFor(() => expect(within(screenPanel).getByText(/测试待核/)).toBeTruthy());
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v4/manager/research/workspace?date=20260831&view=auto",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
    );

    failWorkspace = true;
    await fireEvent.change(screen.getByLabelText("计划目标日"), { target: { value: "2026-09-01" } });
    await waitFor(() => expect(screen.getByText("计划 20260901：网络连接或响应读取失败；可检查连接后重新读取。 未显示旧日或未核验股票。")).toBeTruthy());
    expect(within(screenPanel).queryByText(/测试严格/)).toBeNull();
    expect(within(screenPanel).queryByText(/测试待核/)).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v4/manager/research/workspace?date=20260901&view=auto",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
    );
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/v4/manager/research/catalyst-observations"))).toHaveLength(0);
  });

  it("keeps the complete research count searchable and parses JSON fields safely", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    stubFetch(product);

    render(ManagerSelectionView);

    const ledger = await screen.findByRole("region", { name: "完整研究账本" });
    expect(await within(ledger).findByText("124 条研究候选")).toBeTruthy();
    expect(within(ledger).getByLabelText("搜索研究候选")).toBeTruthy();
    expect(within(ledger).getByText("124 条研究候选")).toBeTruthy();
    expect(within(ledger).getAllByText("财务桥接未完成").length).toBeGreaterThan(0);

    await fireEvent.update(within(ledger).getByLabelText("搜索研究候选"), "不存在的候选");
    expect(within(ledger).getByText("当前筛选没有可确认候选；总量仍为 124 条。")).toBeTruthy();
  });

  it("renders parallel model and official evidence with an explicit non-formal reason card", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const joinedCandidate = product.research_candidates.find((item) => item.normalized_code === "02687");
    expect(joinedCandidate).toBeTruthy();
    const reasonCandidate = {
      ...joinedCandidate,
      source_metadata: {
        supply_card: {
          ...(joinedCandidate?.source_metadata?.supply_card as Record<string, unknown>),
          source: {
            classification: "RESULTS_OR_EARNINGS",
            evidence: "2026 INTERIM REPORT",
            source_class: "OFFICIAL_PDF_LEDGER_VERIFIED",
          },
          typed_gaps: [
            { type: "PRIMARY_SOURCE_CONTENT", status: "CANNOT_CONFIRM" },
            { type: "FINANCIAL_BRIDGE", status: "CANNOT_CONFIRM" },
          ],
          promotion_missing_fields: ["EXACT_DATE_ELIGIBILITY_PIT"],
          promotion_allowed: false,
        },
      },
    };
    const reasonProduct = {
      ...product,
      research_candidates: product.research_candidates.map((item) =>
        item.normalized_code === "02687" ? reasonCandidate : item),
    };
    const reasonPreselection = {
      ...preselection,
      pools: preselection.pools.map((pool) => ({
        ...pool,
        rows: pool.rows?.map((row) => String(row.pool_rank) === "3" ? {
          ...row,
          pool_score: 0.7228874873217646,
          selected_strategy: "prob_active",
          score_prob_active: 0.7228874873217646,
          score_prob_memory: 0.7513414485764346,
          score_prob_crash_reflow: 0.7135297341077333,
          ret_5d: 2.6457663868910464,
          ret_20d: -8.595118020994059,
          ret_60d: -85.27758235161846,
          amount_ratio_20d: 1.5687218389941702,
          recent_top20_count_20d: 4,
        } : row),
      })),
    };
    stubFetch(reasonProduct, reasonPreselection);

    render(ManagerSelectionView);
    await openOriginalSources();

    const queue = await screen.findByRole("region", { name: "D-1模型池 × 官方事件研究队列" });
    expect(within(queue).getAllByText("经理研究逻辑（待盘面确认）").length).toBeGreaterThan(0);
    expect(within(queue).getByText(/模型在HK Connect D-1 Top100第3位、池分数0\.7228874873217646/)).toBeTruthy();
    expect(within(queue).getByText("活跃概率（prob_active）")).toBeTruthy();
    expect(within(queue).getAllByText("模型证据").length).toBeGreaterThan(0);
    expect(within(queue).getAllByText("官方事件证据").length).toBeGreaterThan(0);
    expect(within(queue).getAllByText(/业绩\/财报/).length).toBeGreaterThan(0);
    expect(within(queue).getAllByText("为什么仍非formal").length).toBeGreaterThan(0);
    expect(within(queue).getAllByText("research_status=RESEARCH_ONLY").length).toBeGreaterThan(0);
    expect(within(queue).getAllByText("acceptance=RESEARCH_SUPPLY_ONLY").length).toBeGreaterThan(0);
    expect(within(queue).getAllByText("promotion_allowed=false").length).toBeGreaterThan(0);
    expect(within(queue).getAllByText("公告正文关键事实尚未核实").length).toBeGreaterThan(0);
    expect(within(queue).getAllByText("财务影响桥接尚未完成").length).toBeGreaterThan(0);
    expect(within(queue).getAllByText("目标日资格/PIT不可确认").length).toBeGreaterThan(0);
    expect(within(queue).getAllByText("RESULTS_OR_EARNINGS").length).toBeGreaterThan(0);
    expect(within(queue).getAllByText("OFFICIAL_PDF_LEDGER_VERIFIED").length).toBeGreaterThan(0);
    expect(within(queue).getAllByText(/当前仅保留 D-1 × 官方公告交集/).length).toBeGreaterThan(0);
    expect(queue.textContent).not.toMatch(/买入|推荐升级/);
  });

  it("shows the manager research overlay before collapsed AI and audit details", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const base = product.research_candidates.find((item) => item.normalized_code === "02687");
    expect(base).toBeTruthy();
    const reviewed = {
      ...base,
      source_metadata: {
        supply_card: {
          ...(base?.source_metadata?.supply_card as Record<string, unknown>),
          manager_research: {
            status: "READY",
            direction: "MIXED",
            priority_bucket: "CONDITIONAL",
            investment_thesis_cn: "收入和毛利改善，但亏损与流动性仍需盘面确认。",
            official_facts: [
              { statement_cn: "公告披露收入同比增长。", markdown_path: "/research/02687.md", markdown_sha256: "a".repeat(64), line_start: 41, line_end: 41, excerpt_sha256: "b".repeat(64) },
              { statement_cn: "公告披露净亏损扩大。", markdown_path: "/research/02687.md", markdown_sha256: "a".repeat(64), line_start: 44, line_end: 44, excerpt_sha256: "c".repeat(64) },
            ],
            confirmation_conditions: ["核对现金余额与融资安排", "确认收入增长能否转化为经营现金流"],
            counterevidence_cn: ["净亏损仍在扩大"],
            invalidation_conditions: ["现金流或流动性继续恶化"],
          },
          primary_fact_review: {
            status: "READY",
            direction: "MIXED",
            priority_bucket: "CONDITIONAL",
            investment_thesis_cn: "收入和毛利改善，但亏损与流动性仍需盘面确认。",
            official_facts: [
              { statement_cn: "公告披露收入同比增长。", markdown_path: "/research/02687.md", markdown_sha256: "a".repeat(64), line_start: 41, line_end: 41, excerpt_sha256: "b".repeat(64) },
              { statement_cn: "公告披露净亏损扩大。", markdown_path: "/research/02687.md", markdown_sha256: "a".repeat(64), line_start: 44, line_end: 44, excerpt_sha256: "c".repeat(64) },
            ],
            confirmation_conditions: ["核对现金余额与融资安排", "确认收入增长能否转化为经营现金流"],
            counterevidence_cn: ["净亏损仍在扩大"],
            invalidation_conditions: ["现金流或流动性继续恶化"],
          },
        },
      },
    };
    stubFetch({
      ...product,
      research_candidates: product.research_candidates.map((item) => item.normalized_code === "02687" ? reviewed : item),
    });

    const { container } = render(ManagerSelectionView);
    await openOriginalSources();

    const queue = await screen.findByRole("region", { name: "D-1模型池 × 官方事件研究队列" });
    const queueCard = within(queue).getByText("D-1研究标的02687").closest("article");
    expect(queueCard).toBeTruthy();
    expect(within(queueCard as HTMLElement).getByText("经理研究逻辑（待盘面确认）")).toBeTruthy();
    expect(within(queueCard as HTMLElement).getByText("收入和毛利改善，但亏损与流动性仍需盘面确认。")).toBeTruthy();
    expect(within(queueCard as HTMLElement).getByText("公告披露收入同比增长。")).toBeTruthy();
    expect(within(queueCard as HTMLElement).getByText("核对现金余额与融资安排")).toBeTruthy();
    expect(within(queueCard as HTMLElement).getByText("净亏损仍在扩大")).toBeTruthy();
    expect(within(queueCard as HTMLElement).getByText("WATCH_ONLY / RESEARCH_ONLY / 非formal / D1 × official research queue；仅队列身份不决定经理角色")).toBeTruthy();
    const audit = queueCard?.querySelector("details.reason-details--evidence") as HTMLDetailsElement | null;
    expect(audit).toBeTruthy();
    expect(audit?.open).toBe(false);
    const visible = (queueCard as HTMLElement).cloneNode(true) as HTMLElement;
    visible.querySelectorAll("details").forEach((details) => details.remove());
    expect(visible.textContent).not.toMatch(/FINANCIAL_BRIDGE|raw_sha256|excerpt_sha256|\/research\/02687\.md/);
    expect(visible.textContent).not.toContain("仍需核实：");
  });

  it("sorts evidence-backed reviews ahead of the generic queue and excludes legacy 09926 from manager focus", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const reviewFor = (code: string, bucket: "PRIORITY" | "CONDITIONAL") => {
      const candidate = product.research_candidates.find((item) => item.normalized_code === code);
      expect(candidate).toBeTruthy();
      return {
        ...candidate,
        source_metadata: {
          ...candidate?.source_metadata,
          supply_card: {
            ...candidate?.source_metadata?.supply_card,
            manager_research: {
              status: "READY",
              direction: bucket === "PRIORITY" ? "POSITIVE" : "MIXED",
              priority_bucket: bucket,
              investment_thesis_cn: `${code} 研究逻辑待盘面确认。`,
              official_facts: [{ statement_cn: `${code} 官方事实。` }],
              confirmation_conditions: ["观察目标日盘面确认"],
              counterevidence_cn: ["经营数据可能反转"],
              invalidation_conditions: ["事实绑定失效"],
            },
          },
        },
      };
    };
    const priority = reviewFor("02410", "PRIORITY");
    const conditional = reviewFor("02687", "CONDITIONAL");
    stubFetch({
      ...product,
      research_candidates: product.research_candidates.map((item) => {
        if (item.normalized_code === "02410") return priority;
        if (item.normalized_code === "02687") return conditional;
        return item;
      }),
    });

    render(ManagerSelectionView);
    await openOriginalSources();

    const queue = await screen.findByRole("region", { name: "D-1模型池 × 官方事件研究队列" });
    const firstQueueCode = queue.querySelector(".queue-entry code")?.textContent;
    expect(firstQueueCode).toBe("HK.02410");
    const focus = await screen.findByRole("region", { name: "经理关注层" });
    expect(within(focus).getByText("HK.02410")).toBeTruthy();
    expect(within(focus).queryByText("HK.02687")).toBeNull();
    expect(within(focus).queryByText("HK.09926")).toBeNull();
  });

  it("takes manager focus role and order only from the typed projection", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const selectedWithChangedReview = product.research_candidates.map((item) => {
      if (item.normalized_code !== "02315") return item;
      const supplyCard = item.source_metadata?.supply_card as Record<string, unknown>;
      return {
        ...item,
        source_metadata: {
          ...item.source_metadata,
          supply_card: {
            ...supplyCard,
            manager_research: {
              ...(supplyCard.manager_research as Record<string, unknown>),
              priority_bucket: "EXCLUDE",
            },
          },
        },
      };
    });
    stubFetch({ ...product, research_candidates: selectedWithChangedReview });

    render(ManagerSelectionView);
    await openOriginalSources();

    const focus = await screen.findByRole("region", { name: "经理关注层" });
    const core = within(focus).getByRole("region", { name: "核心研究候选" });
    const conditional = within(focus).getByRole("region", { name: "条件研究候选" });
    const codesIn = (scope: HTMLElement) => [...scope.querySelectorAll(".focus-card")]
      .map((card) => card.textContent?.match(/HK\.\d{5}/)?.[0] || "CANNOT_CONFIRM");
    expect(codesIn(core)).toEqual(["HK.02315", "HK.03738", "HK.06951"]);
    expect(codesIn(conditional)).toEqual(["HK.06078", "HK.01304", "HK.01952", "HK.02676", "HK.02410"]);
    expect(within(focus).getByText(managerReasons["02315"])).toBeTruthy();
    expect(within(focus).queryByText("HK.09926")).toBeNull();
  });

  it("fails closed when the manager decision ref does not bind the 2200 snapshot", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    stubFetch({
      ...product,
      manager_decision_ref: {
        ...product.manager_decision_ref,
        raw_sha256: "f".repeat(64),
      },
    });

    render(ManagerSelectionView);
    await openOriginalSources();

    expect(screen.queryByRole("region", { name: "经理关注层" })).toBeNull();
    const gap = await screen.findByText("关键证据不可确认");
    const gapState = gap.closest(".manager-state") as HTMLElement;
    await fireEvent.click(within(gapState).getByText("展开账本状态审计"));
    expect(within(gapState).getByText("CANNOT_CONFIRM · selection contract 未通过：manager_decision projection ref 与 2200 snapshot 不一致。未展示候选。"))
      .toBeTruthy();
  });

  it("accepts the nested PDF/Markdown official material verification enum", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const markdownCandidate = {
      ...product.research_candidates.find((item) => item.normalized_code === "02687"),
      source_metadata: {
        supply_card: {
          ...product.research_candidates.find((item) => item.normalized_code === "02687")?.source_metadata?.supply_card,
          source: {
            classification: "BUSINESS_OR_REGULATORY_CATALYST",
            evidence: "Official PDF/Markdown material",
            source_class: "OFFICIAL_PDF_MARKDOWN_CONTENT_VERIFIED",
          },
        },
      },
    };
    stubFetch({
      ...product,
      research_candidates: product.research_candidates.map((item) =>
        item.normalized_code === "02687" ? markdownCandidate : item),
    });

    render(ManagerSelectionView);
    await openOriginalSources();

    const queue = await screen.findByRole("region", { name: "D-1模型池 × 官方事件研究队列" });
    expect(within(queue).getAllByText(/业务\/监管催化/).length).toBeGreaterThan(0);
    expect(within(queue).getAllByText("Official PDF/Markdown material").length).toBeGreaterThan(0);
    expect(within(queue).getAllByText("OFFICIAL_PDF_MARKDOWN_CONTENT_VERIFIED").length).toBeGreaterThan(0);
    expect(within(queue).getAllByText(/当前仅保留 D-1 × 官方公告交集/).length).toBeGreaterThan(0);
  });

  it("separates the research ledger, manager delta, cross queue, and later authority gaps", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    stubFetch(product);

    render(ManagerSelectionView);

    const summary = await screen.findByRole("region", { name: "经理关注摘要" }, { timeout: 5000 });
    expect(within(summary).getByText("124 条 research ledger（研究账本）")).toBeTruthy();
    expect(within(summary).getByText("8 条 22:00 manager delta（2200）")).toBeTruthy();
    expect(within(summary).getByText("22 条 D1 × official research queue（D1 × 官方研究队列）")).toBeTruthy();
    expect(within(summary).getByText(/formal authority：NOT_MATERIALIZED/)).toBeTruthy();
    expect(within(summary).getByText(/09:35：NOT_MATERIALIZED/)).toBeTruthy();
    expect(within(summary).getByText(/16:20：NOT_MATERIALIZED/)).toBeTruthy();

    const phases = await screen.findByRole("region", { name: "阶段航迹" });
    expect(within(phases).getByText("16:20 结果参考")).toBeTruthy();
    expect(within(phases).getAllByText("候选未物化（非 0）").length).toBeGreaterThanOrEqual(2);
    expect(within(phases).getAllByText("NOT_MATERIALIZED").length).toBeGreaterThanOrEqual(3);
  });

  it("does not call a NOT_MATERIALIZED 16:20 phase an outcome zero", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    stubFetch(product);

    render(ManagerSelectionView);

    expect(await screen.findByText("候选/结果未物化（非 0）")).toBeTruthy();
    const phases = screen.getByRole("region", { name: "阶段航迹" });
    const phase1620 = within(phases).getByText("16:20 结果参考").closest("article");
    expect(phase1620).toBeTruthy();
    expect(phase1620?.textContent).toContain("候选/结果未物化（非 0）");
    expect(phase1620?.textContent).not.toContain("结果观察0");
  });

  it("uses a catalyst statement before summary/title/text and never uses status as catalyst", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const catalystProduct = {
      ...product,
      research_candidates: product.research_candidates.map((item) => item.normalized_code === "02687"
        ? {
            ...item,
            catalyst: JSON.stringify({
              statement: "结构化催化陈述",
              summary: "摘要不应优先",
              title: "标题不应优先",
              text: "正文不应优先",
              status: "STATUS_NOT_A_CATALYST",
            }),
          }
        : item),
    };
    stubFetch(catalystProduct);

    render(ManagerSelectionView);
    await openOriginalSources();

    const queue = await screen.findByRole("region", { name: "D-1模型池 × 官方事件研究队列" });
    expect(within(queue).getAllByText("结构化催化陈述").length).toBeGreaterThan(0);
    expect(within(queue).queryByText("STATUS_NOT_A_CATALYST")).toBeNull();
    expect(within(queue).queryByText("摘要不应优先")).toBeNull();
  });

  it("does not turn status-only catalyst or source objects into official evidence", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const statusOnlyCandidate = {
      ...product.research_candidates.find((item) => item.normalized_code === "02687"),
      catalyst: JSON.stringify({ status: "STATUS_NOT_A_CATALYST" }),
      source_status: "RESEARCH_SUPPLY_IMPORTED",
      source_metadata: {
        supply_card: {
          ...product.research_candidates.find((item) => item.normalized_code === "02687")?.source_metadata?.supply_card,
          catalyst: { status: "SUPPLY_STATUS_NOT_A_CATALYST" },
          source: { status: "OFFICIAL_PDF_LEDGER_VERIFIED" },
        },
      },
    };
    stubFetch({
      ...product,
      research_candidates: product.research_candidates.map((item) =>
        item.normalized_code === "02687" ? statusOnlyCandidate : item),
    });

    render(ManagerSelectionView);
    await openOriginalSources();

    const queue = await screen.findByRole("region", { name: "D-1模型池 × 官方事件研究队列" });
    const officialEvidence = within(queue).getAllByRole("region", { name: "官方事件证据" })
      .find((region) => region.textContent?.includes("CANNOT_CONFIRM"));
    expect(officialEvidence).toBeTruthy();
    expect(within(officialEvidence as HTMLElement).getAllByText("CANNOT_CONFIRM").length).toBeGreaterThan(0);
    expect(within(officialEvidence as HTMLElement).queryByText("STATUS_NOT_A_CATALYST")).toBeNull();
    expect(within(officialEvidence as HTMLElement).queryByText("SUPPLY_STATUS_NOT_A_CATALYST")).toBeNull();
    expect(within(officialEvidence as HTMLElement).queryByText("OFFICIAL_PDF_LEDGER_VERIFIED")).toBeNull();
    expect(within(officialEvidence as HTMLElement).queryByText("RESEARCH_SUPPLY_IMPORTED")).toBeNull();
  });

  it("does not promote source.status when nested source_class is not verified", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const sourceStatusFallbackCandidate = {
      ...product.research_candidates.find((item) => item.normalized_code === "02687"),
      source_metadata: {
        supply_card: {
          ...product.research_candidates.find((item) => item.normalized_code === "02687")?.source_metadata?.supply_card,
          source: {
            classification: "RESULTS_OR_EARNINGS",
            evidence: "2026 INTERIM REPORT",
            source_class: "UNVERIFIED",
            status: "OFFICIAL_PDF_LEDGER_VERIFIED",
          },
        },
      },
    };
    stubFetch({
      ...product,
      research_candidates: product.research_candidates.map((item) =>
        item.normalized_code === "02687" ? sourceStatusFallbackCandidate : item),
    });

    render(ManagerSelectionView);
    await openOriginalSources();

    const queue = await screen.findByRole("region", { name: "D-1模型池 × 官方事件研究队列" });
    expect(within(queue).queryByText(/匹配到官方材料记录/)).toBeNull();
    const officialEvidence = within(queue).getAllByRole("region", { name: "官方事件证据" })
      .find((region) => region.textContent?.includes("CANNOT_CONFIRM"));
    expect(officialEvidence).toBeTruthy();
    expect(within(officialEvidence as HTMLElement).queryByText("RESULTS_OR_EARNINGS")).toBeNull();
    expect(within(officialEvidence as HTMLElement).queryByText("2026 INTERIM REPORT")).toBeNull();
    expect(within(officialEvidence as HTMLElement).queryByText("OFFICIAL_PDF_LEDGER_VERIFIED")).toBeNull();
  });

  it("does not render nested status-only catalyst statements", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const nestedStatusCandidates = product.research_candidates.map((item) => {
      if (item.normalized_code === "02687") {
        return { ...item, catalyst: JSON.stringify({ statement: { status: "NESTED_STATEMENT_STATUS" } }) };
      }
      if (item.normalized_code === "02676") {
        return { ...item, catalyst: JSON.stringify({ summary: { status: "NESTED_SUMMARY_STATUS" } }) };
      }
      return item;
    });
    stubFetch({ ...product, research_candidates: nestedStatusCandidates });

    render(ManagerSelectionView);
    await openOriginalSources();

    const queue = await screen.findByRole("region", { name: "D-1模型池 × 官方事件研究队列" });
    expect(within(queue).queryByText(/NESTED_STATEMENT_STATUS/)).toBeNull();
    expect(within(queue).queryByText(/NESTED_SUMMARY_STATUS/)).toBeNull();
  });

  it("rejects status-only official fields even when the nested source enum is verified", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const statusEvidenceCandidate = {
      ...product.research_candidates.find((item) => item.normalized_code === "02687"),
      source_metadata: {
        supply_card: {
          ...product.research_candidates.find((item) => item.normalized_code === "02687")?.source_metadata?.supply_card,
          source: {
            classification: "RESULTS_OR_EARNINGS",
            evidence: { status: "STATUS_ONLY_EVIDENCE" },
            source_class: "OFFICIAL_PDF_LEDGER_VERIFIED",
          },
        },
      },
    };
    stubFetch({
      ...product,
      research_candidates: product.research_candidates.map((item) =>
        item.normalized_code === "02687" ? statusEvidenceCandidate : item),
    });

    render(ManagerSelectionView);
    await openOriginalSources();

    const queue = await screen.findByRole("region", { name: "D-1模型池 × 官方事件研究队列" });
    expect(within(queue).queryByText(/匹配到官方材料记录/)).toBeNull();
    const officialEvidence = within(queue).getAllByRole("region", { name: "官方事件证据" })
      .find((region) => region.textContent?.includes("STATUS_ONLY_EVIDENCE") || region.textContent?.includes("CANNOT_CONFIRM"));
    expect(officialEvidence).toBeTruthy();
    expect(within(officialEvidence as HTMLElement).queryByText("STATUS_ONLY_EVIDENCE")).toBeNull();
    expect(within(officialEvidence as HTMLElement).queryByText("RESULTS_OR_EARNINGS")).toBeNull();
    expect(within(officialEvidence as HTMLElement).queryByText("OFFICIAL_PDF_LEDGER_VERIFIED")).toBeNull();
  });

  it("keeps legacy 09926 in the full ledger without manager focus or trade authority", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    stubFetch(product);

    render(ManagerSelectionView);
    await openOriginalSources();

    const focus = await screen.findByRole("region", { name: "经理关注层" });
    expect(focus.querySelectorAll(".focus-card")).toHaveLength(8);
    expect(within(focus).queryByText("康方生物")).toBeNull();
    const ledger = await screen.findByRole("region", { name: "完整研究账本" });
    await fireEvent.click(within(ledger).getByText(/展开研究账本/));
    const candidateCard = [...ledger.querySelectorAll(".ledger-entry")]
      .find((entry) => entry.textContent?.includes("HK.09926"));
    expect(candidateCard).toBeTruthy();
    expect((candidateCard as HTMLElement).textContent).toContain("HK.09926");
    expect(within(candidateCard as HTMLElement).getByText("ELIGIBILITY_CANNOT_CONFIRM")).toBeTruthy();
    expect(within(candidateCard as HTMLElement).getAllByText("RESEARCH_ONLY").length).toBeGreaterThan(0);
  });

  it("keeps formal shortlist members out of non-formal focus regardless of bucket", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    stubFetch(typedFormalProduct());

    render(ManagerSelectionView);
    await openOriginalSources();

    const focus = await screen.findByRole("region", { name: "经理关注层" });
    const formalPanel = await screen.findByRole("region", { name: "正式名单" });
    expect(focus.querySelectorAll(".focus-card")).toHaveLength(7);
    expect(within(focus).queryByText(managerFocusCandidateId)).toBeNull();
    expect(within(formalPanel).getByText(/HK\.02315/)).toBeTruthy();
  });

  it("canonicalizes short HK candidate codes consistently with D-1 queue rows", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const shortCodeCandidate = {
      ...joinConflictCandidate,
      bucket: "CONDITIONAL_RESEARCH_MAP",
      source_metadata: {
        supply_card: {
          entity: "ISSUER_5",
          price_reaction: { name: "短码候选" },
        },
      },
    };
    const shortCodeCandidates = product.research_candidates
      .map((item) => item.normalized_code === "00005" ? shortCodeCandidate : item)
      .sort((left, right) => left.candidate_id.localeCompare(right.candidate_id));
    const shortCodePreselection = {
      ...preselection,
      pools: preselection.pools.map((pool) => ({
        ...pool,
        rows: pool.rows.map((row, index) => index === 0 ? {
          ...row,
          symbol: "HK.5",
          code: "HK.5",
          code_norm: "HK.5",
          ts_code: "5.HK_CONNECT",
          stock_name: "短码D-1研究标的",
          name: "短码D-1研究标的",
          display_name: "短码D-1研究标的",
        } : row),
      })),
    };
    stubFetch({
      ...product,
      research_candidates: shortCodeCandidates,
      source_refs: shortCodeCandidates.flatMap((item) => item.source_refs || []),
    }, shortCodePreselection);

    render(ManagerSelectionView);
    await openOriginalSources();

    expect(normalizeManagerHkCode("5")).toBe("00005");
    const queue = await screen.findByRole("region", { name: "D-1模型池 × 官方事件研究队列" });
    const queueCard = within(queue).getByText("短码D-1研究标的").closest("article");
    expect(queueCard).toBeTruthy();
    expect(within(queueCard as HTMLElement).getByText("HK.00005")).toBeTruthy();
    const focus = await screen.findByRole("region", { name: "经理关注层" });
    expect(within(focus).queryByText("短码候选")).toBeNull();
    expect(within(focus).getByText(managerReasons["02315"])).toBeTruthy();
  });

  it("shows eligibility and PIT plus READY 09:35 without a missing marker", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const later = await compatibleLaterProduct();
    const readyProduct = {
      ...later,
      research_candidates: later.research_candidates.map((item) => item.candidate_id === managerFocusCandidateId
        ? { ...item, eligibility: "ELIGIBLE", pit_status: "READY" }
        : item),
    };
    stubFetch(readyProduct);

    render(ManagerSelectionView);
    await openOriginalSources();

    const focus = await screen.findByRole("region", { name: "经理关注层" });
    const candidateCard = within(focus).getByText("HK.02315").closest("article");
    expect(candidateCard).toBeTruthy();
    const fieldSummary = within(candidateCard as HTMLElement).getByLabelText("字段摘要");
    expect(fieldSummary.textContent).toContain("eligibility=ELIGIBLE");
    expect(fieldSummary.textContent).toContain("pit_status=READY");
    expect(fieldSummary.textContent).toContain("09:35：READY");
    expect(fieldSummary.textContent).not.toContain("缺失");
  });

  it("labels a 09:35 CANNOT_CONFIRM snapshot as不可确认 without a missing marker", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const cannotConfirmProduct = {
      ...product,
      snapshots: {
        ...product.snapshots,
        "0935": { ...missingSnapshot("0935"), status: "CANNOT_CONFIRM" },
      },
    };
    stubFetch(cannotConfirmProduct);

    render(ManagerSelectionView);
    await openOriginalSources();

    const focus = await screen.findByRole("region", { name: "经理关注层" });
    const candidateCard = within(focus).getByText("HK.02315").closest("article");
    expect(candidateCard).toBeTruthy();
    const fieldSummary = within(candidateCard as HTMLElement).getByLabelText("字段摘要");
    expect(fieldSummary.textContent).toContain("09:35：CANNOT_CONFIRM（不可确认）");
    expect(fieldSummary.textContent).not.toContain("09:35：CANNOT_CONFIRM（缺失");
  });

  it("collapses queue evidence and the full ledger while leaving summaries and typed gaps visible", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    stubFetch(product);

    render(ManagerSelectionView);
    await openOriginalSources();

    const queue = await screen.findByRole("region", { name: "D-1模型池 × 官方事件研究队列" });
    expect(queue.textContent).toContain("D1 × official research queue；仅队列身份不决定经理角色");
    const evidenceDetails = queue.querySelectorAll("details.reason-details--evidence");
    expect(evidenceDetails).toHaveLength(22);
    expect([...evidenceDetails].every((details) => !details.hasAttribute("open"))).toBe(true);
    expect(within(queue).getAllByText("经理研究逻辑（待盘面确认）").length).toBe(22);
    expect(within(queue).getAllByText("目标日资格/PIT不可确认").length).toBeGreaterThan(0);

    const ledger = await screen.findByRole("region", { name: "完整研究账本" });
    const ledgerDetails = ledger.querySelector("details.ledger-details");
    expect(ledgerDetails).toBeTruthy();
    expect(ledgerDetails?.hasAttribute("open")).toBe(false);
    expect(within(ledger).getByText(/展开研究账本/)).toBeTruthy();

    const focus = await screen.findByRole("region", { name: "经理关注层" });
    const focusEvidenceDetails = focus.querySelectorAll("details.reason-details--evidence");
    expect(focusEvidenceDetails).toHaveLength(8);
    expect([...focusEvidenceDetails].every((details) => !details.hasAttribute("open"))).toBe(true);
    expect(within(focus).getAllByText("经理研究逻辑（待盘面确认）").length).toBe(8);
    expect(within(focus).getAllByText("为什么仍非formal").length).toBe(8);
    expect(within(focus).getAllByLabelText("非 formal typed gaps").length).toBe(8);

    const phases = await screen.findByRole("region", { name: "阶段航迹" });
    const phaseDetails = phases.querySelector("details.phase-details");
    expect(phaseDetails).toBeTruthy();
    expect(phaseDetails?.hasAttribute("open")).toBe(false);

    const lineage = await screen.findByRole("region", { name: "证据血缘" });
    const lineageDetails = lineage.querySelector("details.lineage-details");
    expect(lineageDetails).toBeTruthy();
    expect(lineageDetails?.hasAttribute("open")).toBe(false);
  });

  it("keeps queue and focus cards concise until their AI/audit details are opened", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    stubFetch(product);

    render(ManagerSelectionView);
    await openOriginalSources();

    const visibleReasonInnerText = (card: HTMLElement): string => {
      const reason = card.querySelector(".reason-card");
      if (!reason) return "";
      const visibleReason = reason.cloneNode(true) as HTMLElement;
      visibleReason.querySelectorAll("details").forEach((details) => details.remove());
      return visibleReason.innerText || visibleReason.textContent || "";
    };
    const machineOnlyCardFields = /pool_score|selected_strategy|score_prob_|ret_5d|RESULTS_OR_EARNINGS|source_refs|raw_sha256|source_sha256|frozen_payload_sha256|\/research\/|eligibility=|recommendation_status=|promotion_allowed=/;

    const queue = await screen.findByRole("region", { name: "D-1模型池 × 官方事件研究队列" });
    const queueCard = queue.querySelector(".queue-entry") as HTMLElement | null;
    expect(queueCard).toBeTruthy();
    const queueAudit = queueCard?.querySelector("details.candidate-audit.reason-details--evidence") as HTMLDetailsElement | null;
    expect(queueAudit).toBeTruthy();
    expect(queueAudit?.open).toBe(false);
    expect(queueCard?.querySelector(":scope > .queue-entry__body > dl")).toBeNull();
    expect(queueCard?.querySelector(":scope > .queue-entry__body > .reason-card > .nonformal-reason .nonformal-fields")).toBeNull();
    expect(queueCard?.querySelector(":scope > .queue-entry__body > .reason-card > .candidate-audit .nonformal-fields")).toBeTruthy();
    expect(visibleReasonInnerText(queueCard as HTMLElement)).toMatch(/经理研究逻辑（待盘面确认）/);
    expect(visibleReasonInnerText(queueCard as HTMLElement)).not.toMatch(/目标日资格\/PIT不可确认/);
    expect(visibleReasonInnerText(queueCard as HTMLElement)).not.toMatch(machineOnlyCardFields);
    expect(queueCard?.textContent).toContain("WATCH_ONLY / RESEARCH_ONLY / 非formal / D1 × official research queue；仅队列身份不决定经理角色");
    expect(queueCard?.textContent).toContain("目标日资格/PIT不可确认");

    const focus = await screen.findByRole("region", { name: "经理关注层" });
    const focusCard = within(focus).getByText("HK.02315").closest("article") as HTMLElement | null;
    expect(focusCard).toBeTruthy();
    const focusAudit = focusCard?.querySelector("details.candidate-audit.reason-details--evidence") as HTMLDetailsElement | null;
    expect(focusAudit).toBeTruthy();
    expect(focusAudit?.open).toBe(false);
    expect(focusCard?.querySelector(":scope > div > small")).toBeNull();
    expect(focusCard?.querySelector(":scope > .reason-card > .candidate-boundary-summary")).toBeNull();
    expect(focusCard?.querySelector(":scope > .reason-card > .candidate-audit .candidate-boundary-summary")).toBeTruthy();
    expect(visibleReasonInnerText(focusCard as HTMLElement)).toContain("收入、毛利与期内利润同步改善");
    expect(visibleReasonInnerText(focusCard as HTMLElement)).not.toMatch(/目标日资格\/PIT不可确认/);
    expect(visibleReasonInnerText(focusCard as HTMLElement)).not.toMatch(machineOnlyCardFields);
    expect(focusCard?.textContent).toContain("经理研究集 / CORE #1 / RESEARCH_ONLY / 非formal / 非BUY");
    expect(focusCard?.textContent).toContain("目标日资格/PIT不可确认");

    await fireEvent.click(within(queueAudit as HTMLElement).getByText("展开 AI / 审计详情（模型、typed gaps、状态与原始证据）"));
    expect(queueAudit?.open).toBe(true);
    expect(within(queueAudit as HTMLElement).getAllByText("pool_score").length).toBeGreaterThan(0);
    expect(within(queueAudit as HTMLElement).getByText("selected_strategy")).toBeTruthy();
    expect(within(queueAudit as HTMLElement).getByText("recommendation_status")).toBeTruthy();
    expect(within(queueAudit as HTMLElement).getByText("source_refs")).toBeTruthy();
    expect(within(queueAudit as HTMLElement).getByText(/raw_sha256=/)).toBeTruthy();
    expect(queueAudit?.textContent).toContain("score_prob_active");
    expect(queueAudit?.textContent).toContain("ret_5d");
    expect(queueAudit?.textContent).toContain("event classification");
    expect(queueAudit?.textContent).not.toContain("/research/20260828/2200_initial_supply_freeze.json");
    expect(queueAudit?.textContent).not.toContain("/Users/lexi/");

    await fireEvent.click(focusAudit?.querySelector("summary") as HTMLElement);
    expect(focusAudit?.open).toBe(true);
    expect(within(focusAudit as HTMLElement).getAllByText("eligibility").length).toBeGreaterThan(0);
    expect(within(focusAudit as HTMLElement).getAllByText("pit_status").length).toBeGreaterThan(0);
    expect(focusAudit?.querySelector(".candidate-boundary-summary")).toBeTruthy();
    expect(focusAudit?.textContent).toContain("promotion_allowed=");
    expect(focusAudit?.textContent).not.toContain("/research/20260828/2200_initial_supply_freeze.json");
    expect(focusAudit?.textContent).not.toContain("/Users/lexi/");
    expect(document.body.textContent).not.toContain("markdown_path");
    expect(document.body.textContent).not.toContain("artifact_path");
    expect(document.body.textContent).toContain("raw_sha256=");
    expect(document.body.textContent).toContain("artifact_sha256");
  });

  it("keeps a conditional candidate non-formal when its target-date model row is absent", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const focusSupply = managerFocusCandidate.source_metadata?.supply_card as Record<string, unknown>;
    const conditionalCandidate = {
      ...managerFocusCandidate,
      source_metadata: {
        supply_card: {
          ...focusSupply,
          entity: "AKESO",
          catalyst: { statement: "创新药事件待核验" },
          source: {
            classification: "BUSINESS_OR_REGULATORY_CATALYST",
            evidence: "AKESO official announcement",
            source_class: "OFFICIAL_PDF_LEDGER_VERIFIED",
          },
          manager_research: {
            ...(managerResearchDetails["02315"] || {}),
            investment_thesis_cn: "业务/监管催化线索待盘面确认。",
            official_facts: [{ statement_cn: "AKESO official announcement" }],
            confirmation_conditions: ["等待目标日盘面确认"],
            counterevidence_cn: ["业务兑现仍待核实"],
            invalidation_conditions: ["公告事实绑定失效"],
          },
          typed_gaps: null,
          promotion_missing_fields: [
            "PRIMARY_SOURCE_CONTENT",
            "REAL_09:25_09:35_MARKET_CONFIRMATION",
          ],
          promotion_allowed: false,
        },
      },
    };
    const missingModelPreselection = {
      ...preselection,
      pools: preselection.pools.map((pool) => ({
        ...pool,
        rows: pool.rows.map((row) => row.code_norm === "HK.02315" ? {
          ...row,
          symbol: "HK.99998",
          code: "HK.99998",
          code_norm: "HK.99998",
          ts_code: "99998.HK_CONNECT",
          stock_name: "目标日缺模型行",
          name: "目标日缺模型行",
          display_name: "目标日缺模型行",
        } : row),
      })),
    };
    stubFetch({
      ...product,
      research_candidates: product.research_candidates.map((item) =>
        item.candidate_id === managerFocusCandidateId ? conditionalCandidate : item),
    }, missingModelPreselection);

    render(ManagerSelectionView);
    await openOriginalSources();

    const focus = await screen.findByRole("region", { name: "经理关注层" });
    expect(within(focus).getAllByText("模型证据不可确认（目标日同码行缺失）").length).toBeGreaterThan(0);
    expect(within(focus).getAllByText(/业务\/监管催化/).length).toBeGreaterThan(0);
    expect(within(focus).getAllByText("AKESO official announcement").length).toBeGreaterThan(0);
    expect(within(focus).getAllByText("为什么仍非formal").length).toBeGreaterThan(0);
    expect(within(focus).getAllByText("其他风险待核实").length).toBeGreaterThan(0);
    expect(within(focus).getAllByText("目标日资格/PIT不可确认").length).toBeGreaterThan(0);
    expect(within(focus).getAllByText("09:25/09:35真实盘面确认缺失").length).toBeGreaterThan(0);
    const gapLists = within(focus).getAllByLabelText("非 formal typed gaps");
    expect(gapLists.some((element) => element.textContent?.includes("目标日资格/PIT不可确认"))).toBe(true);
    expect(gapLists.every((element) => !element.textContent?.includes("ELIGIBILITY_CANNOT_CONFIRM："))).toBe(true);
    expect(gapLists.every((element) => !element.textContent?.includes("SOURCE_REFS_CANNOT_CONFIRM"))).toBe(true);
    expect(within(focus).queryByText("活跃概率（prob_active）")).toBeNull();
  });

  it("renders unknown event enums and malformed JSON as explicit cannot-confirm values", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const malformedCandidate = {
      ...product.research_candidates.find((item) => item.normalized_code === "02687"),
      source_metadata: {
        supply_card: {
          source: {
            classification: "UNKNOWN_EVENT_ENUM",
            evidence: "{malformed-json",
            source_class: "OFFICIAL_PDF_LEDGER_VERIFIED",
          },
          typed_gaps: [{ type: "PRIMARY_SOURCE_CONTENT" }],
          promotion_missing_fields: [],
          promotion_allowed: false,
        },
      },
    };
    stubFetch({
      ...product,
      research_candidates: product.research_candidates.map((item) =>
        item.normalized_code === "02687" ? malformedCandidate : item),
    });

    render(ManagerSelectionView);
    await openOriginalSources();

    const queue = await screen.findByRole("region", { name: "D-1模型池 × 官方事件研究队列" });
    expect(within(queue).getAllByText("未识别枚举（原值：UNKNOWN_EVENT_ENUM）").length).toBeGreaterThan(0);
    expect(within(queue).getAllByText("CANNOT_CONFIRM").length).toBeGreaterThan(0);
    expect(within(queue).getAllByText("公告正文关键事实尚未核实").length).toBeGreaterThan(0);
  });

  it("treats a producer-declared empty typed-gap array as empty, not as an unknown zero", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const noGapCandidate = {
      ...product.research_candidates.find((item) => item.normalized_code === "02687"),
      source_metadata: {
        supply_card: {
          ...(product.research_candidates.find((item) => item.normalized_code === "02687")?.source_metadata?.supply_card || {}),
          typed_gaps: [],
        },
      },
      eligibility: "ELIGIBLE",
      pit_status: "READY",
    };
    stubFetch({
      ...product,
      research_candidates: product.research_candidates.map((item) =>
        item.normalized_code === "02687" ? noGapCandidate : item),
    });

    render(ManagerSelectionView);
    await openOriginalSources();

    const queue = await screen.findByRole("region", { name: "D-1模型池 × 官方事件研究队列" });
    const gapLists = within(queue).getAllByLabelText("非 formal typed gaps");
    expect(gapLists.some((element) => element.textContent?.includes("未声明缺口"))).toBe(true);
  });

  it("unions every present typed-gap source before rendering the audit", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const focusCandidate = product.research_candidates.find((item) => item.normalized_code === "02687");
    expect(focusCandidate).toBeTruthy();
    const supply = focusCandidate?.source_metadata?.supply_card as Record<string, unknown>;
    const candidateWithAllGapSources = {
      ...focusCandidate,
      source_metadata: {
        supply_card: {
          ...supply,
          typed_gaps: [{ type: "FINANCIAL_BRIDGE" }],
          promotion_missing_fields: ["EXACT_DATE_ELIGIBILITY_PIT"],
        },
      },
    };
    stubFetch({
      ...product,
      research_candidates: product.research_candidates.map((item) =>
        item.normalized_code === "02687" ? candidateWithAllGapSources : item),
    });

    render(ManagerSelectionView);
    await openOriginalSources();

    const queue = await screen.findByRole("region", { name: "D-1模型池 × 官方事件研究队列" });
    expect(queue.textContent).toContain("财务影响桥接尚未完成");
    expect(queue.textContent).toContain("目标日资格/PIT不可确认");
  });

  it("hides candidate rows for STALE responses and never carries another date", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    stubFetch({ ...product, target_trade_date: "20260830" });

    render(ManagerSelectionView);

    expect((await screen.findAllByText("STALE")).length).toBeGreaterThan(0);
    expect(screen.getByText("目标日期证据不匹配，未展示候选。"))
      .toBeTruthy();
    expect(screen.queryByText("康方生物")).toBeNull();
    expect(screen.queryByText("124 条研究候选")).toBeNull();
  });

  it("does not turn NOT_MATERIALIZED into zero candidates or READY snapshots", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260901");
    stubFetch(
      missingProduct("NOT_MATERIALIZED", "SELECTION_PRODUCT_NOT_MATERIALIZED:20260901", "20260901"),
      preselectionForDate("20260901"),
    );

    render(ManagerSelectionView);

    expect((await screen.findAllByText("NOT_MATERIALIZED")).length).toBeGreaterThan(0);
    const gap = await screen.findByText("研究账本尚未物化");
    const gapState = gap.closest(".manager-state") as HTMLElement;
    expect(within(gapState).getByText("研究账本暂不可用；不代表没有股票。阶段与尾盘结果在下方独立展示。"))
      .toBeTruthy();
    expect(screen.queryByText("0 条研究候选")).toBeNull();
    expect(screen.queryByText("康方生物")).toBeNull();
    expect(screen.queryByText("READY")).toBeNull();
  });

  it("fails closed when the declared research count disagrees with the candidate array", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    stubFetch({
      ...product,
      counts: { ...product.counts, research_candidates: 123 },
    });

    render(ManagerSelectionView);

    expect(await screen.findByText("关键证据不可确认")).toBeTruthy();
    expect(screen.getByText(/counts\.research_candidates 与数组长度不一致/)).toBeTruthy();
    expect(screen.queryByText("康方生物")).toBeNull();
    expect(screen.queryByText("124 条研究候选")).toBeNull();
  });

  it("rejects BUY-like candidate status and never renders an unsafe candidate", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const unsafe = {
      ...product,
      research_candidates: product.research_candidates.map((item, index) =>
        index === 0 ? { ...item, recommendation_status: "BUY" } : item,
      ),
    };
    stubFetch(unsafe);

    render(ManagerSelectionView);

    expect(await screen.findByText("关键证据不可确认")).toBeTruthy();
    expect(screen.getByText(/recommendation_status 必须是 RESEARCH_ONLY/)).toBeTruthy();
    expect(screen.queryByText("康方生物")).toBeNull();
  });

  it("rejects unknown product wire fields instead of treating them as harmless metadata", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    stubFetch({ ...product, unexpected_wire_field: true });

    render(ManagerSelectionView);

    expect(await screen.findByText("关键证据不可确认")).toBeTruthy();
    expect(screen.getByText(/包含未允许 wire 字段/)).toBeTruthy();
    expect(screen.queryByText("康方生物")).toBeNull();
  });

  it("rejects a materialized product with missing run/date/time/origin/acceptance evidence", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    stubFetch({
      ...product,
      run_id: null,
      generated_at: null,
      cutoff_at: null,
      origin: null,
      acceptance: "NOT_MATERIALIZED",
    });

    render(ManagerSelectionView);

    expect(await screen.findByText("关键证据不可确认")).toBeTruthy();
    expect(screen.getByText(/materialized 产品必须提供 run_id/)).toBeTruthy();
    expect(screen.queryByText("康方生物")).toBeNull();
  });

  it("rejects an empty READY ledger and READY formal authority without a formal shortlist", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    stubFetch({
      ...product,
      status: "READY",
      research_candidates: [],
      formal_shortlist: [],
      source_refs: [],
      manager_decision_ref: null,
      counts: { ...product.counts, research_candidates: 0 },
      snapshots: { ...product.snapshots, "2200": { ...product.snapshots["2200"], candidate_ids: [] } },
      formal_authority: { ...product.formal_authority, status: "READY", pit_status: "READY", selector_status: "READY", research_evidence: true, manager_decision: true },
    });

    render(ManagerSelectionView);

    expect(await screen.findByText("关键证据不可确认")).toBeTruthy();
    expect(screen.getByText(/empty selection ledger must be NOT_MATERIALIZED|READY 产品必须包含研究候选/)).toBeTruthy();
    expect(screen.queryByText("康方生物")).toBeNull();
    expect(screen.queryByText("READY_WITH_DECLARED_GAPS")).toBeNull();
  });

  it("rejects a READY later phase when its 0830 dependency is not materialized", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const invalidSnapshot = await withSnapshotSha({
      ...product.snapshots["0935"],
      status: "READY",
      run_id: "phase-0935",
      event_at: "2026-08-29T09:35:00+08:00",
      artifact_sha256: "a".repeat(64),
      candidate_ids: ["HK.09926|09926.HK"],
      changes: [],
      freeze_run_id: "phase-0830",
      freeze_snapshot_sha256: "c".repeat(64),
      snapshot_sha256: "b".repeat(64),
    });
    stubFetch({
      ...product,
      snapshots: {
        ...product.snapshots,
        "0935": invalidSnapshot,
      },
    });

    render(ManagerSelectionView);

    expect(await screen.findByText("关键证据不可确认")).toBeTruthy();
    expect(screen.getByText(/0935 READY 依赖 READY 的 0830/)).toBeTruthy();
    expect(screen.queryByText("康方生物")).toBeNull();
  });

  it("rejects a READY snapshot missing its required snapshot SHA", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    stubFetch({
      ...product,
      snapshots: { ...product.snapshots, "2200": withoutField(product.snapshots["2200"], "snapshot_sha256") },
    });

    render(ManagerSelectionView);

    expect(await screen.findByText("关键证据不可确认")).toBeTruthy();
    expect(screen.getByText(/2200 snapshot 缺少/)).toBeTruthy();
    expect(screen.queryByText("康方生物")).toBeNull();
  });

  it("rejects lineage with missing fields or SHA aliases that do not bind to lineage", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    stubFetch({
      ...product,
      current_sha256: "f".repeat(64),
      lineage: withoutField(product.lineage, "current_sha256"),
    });

    render(ManagerSelectionView);

    expect(await screen.findByText("关键证据不可确认")).toBeTruthy();
    expect(screen.getByText(/lineage 字段不完整/)).toBeTruthy();
    expect(screen.queryByText("康方生物")).toBeNull();
  });

  it("rejects a tampered 2200 candidate set when its snapshot SHA is retained", async () => {
    const tampered = {
      ...product,
      snapshots: {
        ...product.snapshots,
        "2200": {
          ...product.snapshots["2200"],
          candidate_ids: [researchCandidates[1].candidate_id],
        },
      },
    };

    expect(await validateSelectionProduct(tampered, "20260831")).toMatch(/snapshot SHA mismatch/);
  });

  it("accepts an append_selection_phase-compatible 0830 READY snapshot, including a target-date generated_at", async () => {
    const appended = await compatible0830Product(managerSnapshotCandidateIds);

    expect(await validateSelectionProduct(appended, "20260831")).toBeNull();
    expect(appended.source_date).toBe("20260828");
    expect(appended.generated_at).toBe("2026-08-31T08:30:00+08:00");
    expect(appended.snapshots["0830"].status).toBe("READY");
  });

  it("accepts a legal empty 0830 freeze produced by removing the initial candidate", async () => {
    const appended = await compatible0830Product(
      managerSnapshotCandidateIds.filter((candidateId) => candidateId !== managerFocusCandidateId),
      [{ action: "REMOVE", candidate_id: managerFocusCandidateId }],
    );

    expect(await validateSelectionProduct(appended, "20260831")).toBeNull();
    expect(appended.snapshots["0830"].candidate_ids).toEqual(
      managerSnapshotCandidateIds.filter((candidateId) => candidateId !== managerFocusCandidateId),
    );
  });

  it("rejects forged typed formal refs and accepts the complete authority binding", async () => {
    const valid = typedFormalProduct();
    const forged = {
      ...valid,
      formal_authority: {
        ...valid.formal_authority,
        manager_decision_ref: {
          ...valid.formal_authority.manager_decision_ref,
          run_id: "different-authority-run",
        },
      },
    };

    expect(await validateSelectionProduct(forged, "20260831")).toMatch(/authority run|run binding/);
    expect(await validateSelectionProduct(valid, "20260831")).toBeNull();
  });

  it("accepts backend-shaped formatted refs while formal authority is non-READY", async () => {
    const staleAuthority = {
      ...product.formal_authority,
      status: "STALE",
      pit_status: "PIT_STALE",
      selector_status: "SELECTOR_STALE",
      research_evidence: true,
      manager_decision: true,
      source_sha256: "c".repeat(64),
      evidence_refs: [{ path: "/research/formal/stale-evidence.json" }],
      manager_decision_ref: { path: "/research/formal/stale-decision.json" },
    };
    const staleProduct = { ...product, formal_authority: staleAuthority };

    expect(await validateSelectionProduct(staleProduct, "20260831")).toBeNull();
  });

  it("accepts the 0830 freeze through bound 0935 observation and 1620 outcome phases", async () => {
    const appended = await compatibleLaterProduct();

    expect(await validateSelectionProduct(appended, "20260831")).toBeNull();
    expect(appended.snapshots["0935"].freeze_run_id).toBe(appended.snapshots["0830"].run_id);
    expect(appended.snapshots["1620"].freeze_snapshot_sha256).toBe(appended.snapshots["0830"].snapshot_sha256);
  });

  it("joins the exact HK D-1 pool to 22 research rows without promoting 09926", () => {
    expect(validateManagerPreselection(preselection, "20260831")).toBeNull();

    const join = buildManagerResearchQueue(preselection.pools[0].rows, researchCandidates);
    expect(join.issue).toBeNull();
    expect(join.entries).toHaveLength(22);
    expect(join.entries.map((entry) => entry.normalizedCode)).not.toContain("09926");
    expect(join.entries.map((entry) => entry.poolRow.pool_rank)).toEqual(
      [...join.entries.map((entry) => entry.poolRow.pool_rank)].sort((left, right) => Number(left) - Number(right)),
    );
    expect(join.entries.every((entry) => entry.selectionCandidate.recommendation_status === "RESEARCH_ONLY")).toBe(true);
  });

  it("rejects unsafe, duplicate, and malformed D-1 pool wire shapes", () => {
    const duplicateRank = {
      ...preselection,
      pools: [{
        ...preselection.pools[0],
        rows: preselection.pools[0].rows.map((row, index) => index === 98 ? { ...row, pool_rank: 100 } : row),
      }],
    };
    expect(validateManagerPreselection(duplicateRank, "20260831")).toMatch(/重复 pool_rank=100/);

    const malformedRow = {
      ...preselection,
      pools: [{ ...preselection.pools[0], rows: preselection.pools[0].rows.map((row, index) => index === 3 ? null : row) }],
    };
    expect(validateManagerPreselection(malformedRow, "20260831")).toMatch(/row\[3\] 不是对象/);

    const wrongStatus = {
      ...preselection,
      pools: [{ ...preselection.pools[0], status: "READY" }],
    };
    expect(validateManagerPreselection(wrongStatus, "20260831")).toMatch(/STRICT_0_2_READY/);

    const unsafe = { ...preselection, production_allowed: true };
    expect(validateManagerPreselection(unsafe, "20260831")).toMatch(/production_allowed 必须是 false/);
  });

  it("keeps the trusted selection ledger when the D-1 pool cannot be validated", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const invalidPreselection = {
      ...preselection,
      pools: [{ ...preselection.pools[0], status: "READY" }],
    };
    stubFetch(product, invalidPreselection);

    render(ManagerSelectionView);
    await openOriginalSources();

    expect(await screen.findByText("124 条 research ledger（研究账本）")).toBeTruthy();
    expect(screen.getByText(/D-1 预选池 contract 未通过/)).toBeTruthy();
    expect(screen.getAllByText(/不可确认（非0）/).length).toBeGreaterThan(0);
    expect(screen.getByText(/数量未知（不可确认）/)).toBeTruthy();
    expect(screen.getByText(managerReasons["02315"])).toBeTruthy();
    const focus = await screen.findByRole("region", { name: "经理关注层" });
    expect(within(focus).getAllByText(/D1 × official research queue：不可确认/).length).toBeGreaterThan(0);
    expect(within(focus).getAllByText(/模型证据不可确认（D-1 预选池不可确认）/).length).toBeGreaterThan(0);
    expect(screen.queryByText("0 条交叉研究队列")).toBeNull();
  });

  it("keeps the trusted selection ledger when the D-1 HTTP request fails", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.includes("/api/v3/preselection-pools")) return { ok: false, status: 503, json: async () => ({}) };
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(product));
      return response(product);
    }));

    render(ManagerSelectionView);
    await openOriginalSources();

    expect(await screen.findByText("124 条 research ledger（研究账本）")).toBeTruthy();
    expect(await screen.findByText(/D-1 预选池读取失败/)).toBeTruthy();
    expect(screen.getAllByText(/不可确认（非0）/).length).toBeGreaterThan(0);
    expect(screen.getByText("数量未知（不可确认）")).toBeTruthy();
    expect(screen.getByText(managerReasons["02315"])).toBeTruthy();
    const focus = await screen.findByRole("region", { name: "经理关注层" });
    expect(within(focus).getAllByText(/D1 × official research queue：不可确认/).length).toBeGreaterThan(0);
    expect(within(focus).getAllByText(/模型证据不可确认（D-1 预选池不可确认）/).length).toBeGreaterThan(0);
    expect(screen.queryByText("0 条交叉研究队列")).toBeNull();
  });

  it("keeps the trusted selection ledger when the D-1 JSON response is invalid", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.includes("/api/v3/preselection-pools")) {
        return { ok: true, status: 200, json: async () => { throw new Error("invalid D-1 JSON"); } };
      }
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(product));
      return response(product);
    }));

    render(ManagerSelectionView);

    expect(await screen.findByText("124 条 research ledger（研究账本）")).toBeTruthy();
    expect(await screen.findByText(/D-1 预选池读取失败（invalid D-1 JSON）/)).toBeTruthy();
    expect(screen.getByText("数量未知（不可确认）")).toBeTruthy();
    expect(screen.queryByText("0 条交叉研究队列")).toBeNull();
  });

  it("shows the trusted selection ledger while the D-1 response is still pending", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const delayedPreselection = deferred<ReturnType<typeof response>>();
    vi.stubGlobal("fetch", vi.fn((url: string) => url.includes("/api/v3/preselection-pools")
      ? delayedPreselection.promise
      : Promise.resolve(response(product))));

    render(ManagerSelectionView);

    expect(await screen.findByText("124 条 research ledger（研究账本）")).toBeTruthy();
    expect(screen.getByText("不可确认（非0） D1 × official research queue（D1 × 官方研究队列）")).toBeTruthy();
    expect(screen.getByText("数量未知（不可确认）")).toBeTruthy();

    delayedPreselection.resolve(response(preselection));
    expect(await screen.findByText("22 条 D1 × official research queue（D1 × 官方研究队列）")).toBeTruthy();
    expect(screen.getByText("100 条")).toBeTruthy();
  });

  it("keeps the selection ledger when the validated D-1 join fails", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    expect(await validateSelectionProduct(joinFailureProduct, "20260831")).toBeNull();
    stubFetch(joinFailureProduct, preselection);

    render(ManagerSelectionView);

    expect(await screen.findByText("125 条 research ledger（研究账本）")).toBeTruthy();
    expect(await screen.findByText(/研究交叉队列 contract 未通过/)).toBeTruthy();
    expect(screen.getByText("不可确认（非0） D1 × official research queue（D1 × 官方研究队列）")).toBeTruthy();
    expect(screen.getByText("数量未知（不可确认）")).toBeTruthy();
    expect(screen.queryByText("0 条交叉研究队列")).toBeNull();
  });

  it("does not show the D-1 queue when selection validation fails", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    stubFetch({ ...product, counts: { ...product.counts, research_candidates: 123 } }, preselection);

    render(ManagerSelectionView);

    expect(await screen.findByText("关键证据不可确认")).toBeTruthy();
    expect(screen.getByText(/counts\.research_candidates 与数组长度不一致/)).toBeTruthy();
    expect(screen.queryByText("124 条 research ledger（研究账本）")).toBeNull();
    expect(screen.queryByText(/D1 × official research queue/)).toBeNull();
    expect(screen.queryByText("康方生物")).toBeNull();
  });

  it("shows a verified zero-length join as zero instead of unknown", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const noIntersection = disjointPreselection("20260831");
    expect(validateManagerPreselection(noIntersection, "20260831")).toBeNull();
    stubFetch(product, noIntersection);

    render(ManagerSelectionView);
    await openOriginalSources();

    expect(await screen.findByText("124 条 research ledger（研究账本）")).toBeTruthy();
    expect(screen.getByText("0 条 D1 × official research queue（D1 × 官方研究队列）")).toBeTruthy();
    expect(screen.getByText("100 条")).toBeTruthy();
    expect(screen.getByText("交叉研究队列已验证为空（0 条）。")).toBeTruthy();
    expect(screen.queryByText("不可确认（非0） D1 × official research queue（D1 × 官方研究队列）")).toBeNull();
  });

  it("ignores a late D-1 response from the previous target date", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const oldPreselection = deferred<ReturnType<typeof response>>();
    const newDate = "20260901";
    const newSelection = selectionForDate(newDate);
    const newPreselection = taggedPreselection(newDate, "NEW");
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (!url.includes("/api/v3/preselection-pools")) {
        return Promise.resolve(url.includes(newDate) ? response(newSelection) : response(product));
      }
      return url.includes(newDate) ? Promise.resolve(response(newPreselection)) : oldPreselection.promise;
    }));

    render(ManagerSelectionView);
    expect(await screen.findByText("124 条 research ledger（研究账本）")).toBeTruthy();

    const dateInput = screen.getByLabelText("目标交易日") as HTMLInputElement;
    dateInput.value = "2026-09-01";
    await fireEvent.change(dateInput);
    expect(await screen.findByText("NEW-D-1研究标的02687")).toBeTruthy();

    oldPreselection.resolve(response(taggedPreselection("20260831", "OLD")));
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    expect(screen.getByText("NEW-D-1研究标的02687")).toBeTruthy();
    expect(screen.queryByText("OLD-D-1研究标的02687")).toBeNull();
  });

  it("does not let an older response finish after its delayed validator and overwrite a newer date", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const firstFetch = deferred<ReturnType<typeof response>>();
    const secondFetch = deferred<ReturnType<typeof response>>();
    const nativeDigest = globalThis.crypto.subtle.digest.bind(globalThis.crypto.subtle);
    const releaseFirstDigest = deferred<void>();
    const firstDigestComplete = deferred<void>();
    let delayFirstDigest = true;
    const digest = vi.fn((algorithm: AlgorithmIdentifier, data: BufferSource) => {
      if (delayFirstDigest) {
        delayFirstDigest = false;
        return releaseFirstDigest.promise
          .then(() => nativeDigest(algorithm, data))
          .then((result) => {
            firstDigestComplete.resolve();
            return result;
          });
      }
      return nativeDigest(algorithm, data);
    });
    vi.stubGlobal("crypto", { subtle: { digest } });
    const nextPreselection = preselectionForDate("20260901");
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.includes("/api/v3/preselection-pools")) {
        return Promise.resolve(response(url.includes("20260901") ? nextPreselection : preselection));
      }
      return url.includes("20260831") ? firstFetch.promise : secondFetch.promise;
    }));

    render(ManagerSelectionView);
    firstFetch.resolve(response(product));
    await waitFor(() => expect(digest).toHaveBeenCalledTimes(1));

    const dateInput = screen.getByLabelText("目标交易日") as HTMLInputElement;
    dateInput.value = "2026-09-01";
    await fireEvent.change(dateInput);
    secondFetch.resolve(response(missingProduct("NOT_MATERIALIZED", "SELECTION_PRODUCT_NOT_MATERIALIZED:20260901", "20260901")));
    expect(await screen.findByText("研究账本尚未物化")).toBeTruthy();

    releaseFirstDigest.resolve();
    await firstDigestComplete.promise;
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    expect(screen.getAllByText("20260901").length).toBeGreaterThan(0);
    expect(screen.queryByText("康方生物")).toBeNull();
  });

  it("surfaces a timeout when a read ignores its AbortSignal", async () => {
    vi.useFakeTimers();
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));

    render(ManagerSelectionView);
    await vi.advanceTimersByTimeAsync(10_000);
    await nextTick();

    expect(screen.getAllByText(/请求超时/).length).toBeGreaterThan(0);
  });

  it("returns a readable fail-closed issue when cannot_confirm is null", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    stubFetch({
      ...product,
      first_failed_layer: null,
      cannot_confirm: null,
    });

    render(ManagerSelectionView);

    expect(await screen.findByText("关键证据不可确认")).toBeTruthy();
    expect(screen.getByText(/cannot_confirm 必须是字符串数组/)).toBeTruthy();
    expect(screen.queryByText("康方生物")).toBeNull();
  });

  it("keeps a CANNOT_CONFIRM response fail-closed without inventing zero or READY", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const reason = "SELECTION_LINEAGE_NOT_MATERIALIZED:20260831";
    stubFetch(missingProduct("CANNOT_CONFIRM", reason));

    render(ManagerSelectionView);

    expect(await screen.findByText("关键证据不可确认")).toBeTruthy();
    expect((await screen.findAllByText("CANNOT_CONFIRM")).length).toBeGreaterThan(0);
    expect(screen.getAllByText((text) => text.includes(reason)).length).toBeGreaterThan(0);
    expect(screen.queryByText("0 条研究候选")).toBeNull();
    expect(screen.queryByText("康方生物")).toBeNull();
    expect(screen.queryByText("READY")).toBeNull();
  });

  it("renders the exact-stage HK-only candidate panel without using the A-share lane", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v3/manager/stage-selection")) return response(managerStageSelection);
      if (url.includes("/api/v3/preselection-pools")) return response(preselection);
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(product));
      return response(product);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    const panel = await screen.findByRole("region", { name: "今日港股通阶段候选" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v3/manager/stage-selection?date=20260831&stage=STAGE_0935_0940&limit=50&market=HK_CONNECT",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
    );
    await within(panel).findByText("当前显示 8 条");
    expect(within(panel).getByRole("heading", { name: "港股通股票 · 阶段与尾盘观察" })).toBeTruthy();
    expect(within(panel).getByText("09:40补充确认 / 非09:35替代")).toBeTruthy();
    expect(within(panel).getByText(/09:40 controlled recovery.*natural=false.*formal=false.*NO_BUY/)).toBeTruthy();
    expect(within(panel).getByText("stage=STAGE_0935_0940", { exact: true })).toBeTruthy();
    expect(within(panel).getByText("当前显示 8 条")).toBeTruthy();
    for (const name of ["云知声", "壁仞科技", "融创中国", "建滔积层板", "东岳集团", "MINIMAX-W", "建滔集团", "智谱"]) {
      expect(within(panel).getByText(name)).toBeTruthy();
    }
    for (const code of ["09678", "06082", "01918", "01888", "00189", "00100", "00148", "02513"]) {
      expect(panel.textContent).toContain(code);
    }
    expect(panel.textContent).not.toContain("A股fixture-");
    const firstCard = within(panel).getByText("云知声").closest("article");
    expect(firstCard).toBeTruthy();
    expect(within(firstCard as HTMLElement).getByText(/观察入榜原因（非经理入选）/)).toBeTruthy();
    expect(firstCard?.textContent).toContain("NO_TRADE / NO_BUY / 非经理入选");
    expect(firstCard?.querySelectorAll(".manager-stage-contribution")).toHaveLength(5);
    expect(firstCard?.textContent).toMatch(/LIVE_HKCONNECT_GAINER/);
    expect(firstCard?.textContent).toMatch(/阶段窗口（09:35-09:40）涨幅\+2\.5%/);
    const audit = firstCard?.querySelector("details") as HTMLDetailsElement | null;
    expect(audit).toBeTruthy();
    expect(audit?.open).toBe(false);
  });

  it("shows a time-aware pending state for an empty 09:40 stage before the Asia/Shanghai slot", async () => {
    vi.setSystemTime(new Date("2026-09-08T01:02:00.000Z"));
    window.history.replaceState({}, "", "/manager-selection/?date=20260908");
    const targetDate = "20260908";
    const selection = missingProduct("CANNOT_CONFIRM", "SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID", targetDate);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.includes("/api/v3/preselection-pools")) return response(preselectionForDate(targetDate));
      if (url.includes("/api/v3/manager/stage-selection")) return response(pendingManagerStageFor(targetDate));
      if (url.includes("/api/v4/manager/research")) return response(managerResearchPayloadFor(targetDate));
      if (url.includes("/api/v3/research/selection/manager-decision")) {
        return response(managerDecisionNotMaterializedResponse(targetDate));
      }
      return response(selection);
    }));

    render(ManagerSelectionView);

    expect(await screen.findByRole("status", { name: "经理决策优先级待生成" })).toBeTruthy();
    expect(screen.getByText("09:40 阶段候选待生成")).toBeTruthy();
    expect(screen.getByText(/当前空响应只表示待生成，不是投资判断/)).toBeTruthy();
    const researchSummary = await screen.findByRole("region", { name: "经理工作台研究发现摘要" });
    expect(within(researchSummary).getAllByText("研究执行或读取失败").length).toBeGreaterThan(0);
    const stagePanel = await screen.findByRole("region", { name: "今日港股通阶段候选" });
    expect(within(stagePanel).getByText(/09:40 阶段槽尚未到时/)).toBeTruthy();
    expect(within(stagePanel).getByText(/数量未知（CANNOT_CONFIRM）/)).toBeTruthy();
    expect(stagePanel.querySelector(".manager-stage-grid")).toBeNull();
  });

  it("renders five category counts and keeps research preference independent from action classification", async () => {
    vi.setSystemTime(new Date("2026-09-08T03:00:00.000Z"));
    window.history.replaceState({}, "", "/manager-selection/?date=20260908");
    const targetDate = "20260908";
    const stageRows = [
      managerPriorityStageRow("00001", "条件研究公司", 1),
      managerPriorityStageRow("00002", "明确边界公司", 2, {
        action_level: "NO_BUY",
        trade_status: "NO_TRADE",
        formal_eligible: false,
      }),
    ];
    const stage = managerPriorityStageFor(targetDate, stageRows);
    const research = managerResearchPayloadFor(targetDate, [
      managerPriorityFacts(targetDate, "00001"),
      managerPriorityFacts(targetDate, "00002"),
    ]);
    const selection = selectionForDate(targetDate);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.includes("/api/v3/preselection-pools")) return response(preselectionForDate(targetDate));
      if (url.includes("/api/v3/manager/stage-selection")) return response(stage);
      if (url.includes("/api/v4/manager/research")) return response(research);
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(selection));
      return response(selection);
    }));

    render(ManagerSelectionView);

    const dashboard = await screen.findByRole("region", { name: "经理决策优先级摘要" });
    const actionCountRegion = dashboard.querySelector('[aria-label="五类行动计数"]') as HTMLElement;
    expect(actionCountRegion).toBeTruthy();
    expect(Object.fromEntries(
      [...actionCountRegion.querySelectorAll("article")].map((article) => [
        article.querySelector("span")?.textContent?.trim(),
        article.querySelector("strong")?.textContent?.trim(),
      ]),
    )).toEqual({
      "BUY（执行门）": "0",
      "CONDITIONAL（执行门）": "0",
      "WATCH（执行门）": "1",
      "NO_BUY（执行门）": "1",
      "CANNOT_CONFIRM（执行门）": "0",
    });
    const researchCountRegion = dashboard.querySelector('[aria-label="五类研究意见计数"]') as HTMLElement;
    expect(researchCountRegion).toBeTruthy();
    expect(Object.fromEntries(
      [...researchCountRegion.querySelectorAll("article")].map((article) => [
        article.querySelector("span")?.textContent?.trim(),
        article.querySelector("strong")?.textContent?.trim(),
      ]),
    )).toMatchObject({
      "WATCH（研究意见）": "2",
      "CONDITIONAL_BUY（研究意见）": "0",
    });
    const researchPriority = dashboard.querySelector('[aria-label="独立研究优先级"]') as HTMLElement;
    expect(researchPriority).toBeTruthy();
    expect(researchPriority.querySelectorAll(".manager-research-priority__list > article")).toHaveLength(2);
    expect(within(researchPriority).getAllByText(/研究意见=研究观察/)).toHaveLength(2);
    expect(within(dashboard).getByText("研究优先级 #1 · 条件研究公司")).toBeTruthy();
    expect(dashboard.textContent).toContain("后端优先级依据：后端优先级理由一");
    expect(dashboard.textContent).toContain("研究覆盖范围：仅依据已解析官方财报结构化事实；近期重大事件（含合作/公告）覆盖未确认。");
    expect(dashboard.textContent).toContain("数值 basis：profit_loss=POSITIVE");

    const stagePanel = await screen.findByRole("region", { name: "今日港股通阶段候选" });
    const cards = [...stagePanel.querySelectorAll(".manager-stage-card")];
    expect(cards).toHaveLength(2);
    expect(cards[0]?.textContent).toContain("条件研究公司");
    expect(cards[0]?.textContent).toContain("WATCH（执行门）");
    expect(cards[1]?.textContent).toContain("明确边界公司");
    expect(cards[1]?.textContent).toContain("NO_BUY（执行门）");
    expect(stagePanel.textContent).toContain("RESEARCH_ONLY / NO_TRADE / NO_BUY");
  });

  it("puts the source reader first and keeps event evidence out of the reading cards", async () => {
    vi.setSystemTime(new Date("2026-09-08T08:00:00.000Z"));
    window.history.replaceState({}, "", "/manager-selection/?date=20260908");
    const targetDate = "20260908";
    const stage = managerPriorityStageFor(targetDate, [managerPriorityStageRow("01191", "海光芯正", 1)]);
    const catalystEvent = {
      event_id: "event-1",
      event_type: "COOPERATION",
      source_kind: "MEDIA",
      source_id: "iccsz.media.directory.v1",
      official_confirmation_status: "PENDING",
      code: "HK.01191",
      name: "海光芯正",
      counterparty: "格罗方德",
      catalyst: "海光芯正携手格罗方德深化全球战略合作",
      why_might_affect_business: "公司将依托技术，全力推进6.4T NPO产品的工程落地与规模化量产。",
      realization_conditions: ["官方确认合作范围", "观察订单或交付"],
      financial_counterevidence: ["已确认财务反证：PROFIT_LOSS 当前=(118,269)、前期=(34,850)"],
      market_confirmation_gap: ["MEDIA_ONLY_OFFICIAL_CONFIRMATION_PENDING", "ORDER_OR_REVENUE_UNCONFIRMED", "MARKET_PRICE_VOLUME_UNCONFIRMED"],
      publisher_timestamp: "2026-09-08T13:18:14+08:00",
      reported_event_date_text: "9月7日",
      first_seen_at: "2026-09-08T08:00:00+00:00",
      source_url: "http://www.iccsz.com/site/cn/News/2026/09/08/demo.htm",
      source_sha256: "a".repeat(64),
      source_excerpt: "公司将依托技术，全力推进6.4T NPO产品的工程落地与规模化量产。",
      body_parsed: true,
      event_relevant: true,
      event_status: "READY",
      summary_status: "PARSED",
      as_of_bucket: "current",
    };
    const directoryEvent = {
      event_id: "event-directory-only",
      event_type: "OFFICIAL_ANNOUNCEMENT",
      source_kind: "OFFICIAL",
      source_id: "v4.hkex.official_event_directory.v1",
      evidence_level: "OFFICIAL_DIRECTORY_ONLY",
      official_confirmation_status: "BODY_NOT_PARSED",
      code: "HK.01191",
      name: "海光芯正",
      catalyst: "公告目录线索",
      realization_conditions: ["补齐正文"],
      financial_counterevidence: [],
      market_confirmation_gap: ["DIRECTORY_ONLY_BODY_NOT_PARSED", "MARKET_PRICE_VOLUME_UNCONFIRMED"],
      publisher_timestamp: "2026-09-07T09:00:00+08:00",
      first_seen_at: "2026-09-08T08:00:00+00:00",
      source_url: "https://www1.hkexnews.hk/demo.pdf",
      body_parsed: false,
      as_of_bucket: "historical",
    };
    const unknownEvent = {
      event_id: "event-unknown-source",
      event_type: "NEWS",
      source_kind: "UNKNOWN",
      source_id: "unclassified.source.v1",
      official_confirmation_status: "PENDING",
      code: "HK.01191",
      name: "海光芯正",
      source_title: "未分类来源标题",
      publisher_timestamp: "2026-09-06T09:00:00+08:00",
      first_seen_at: "2026-09-08T08:00:00+00:00",
      source_url: "https://example.test/unknown-source",
      source_excerpt: "未分类来源摘要",
      body_parsed: false,
      as_of_bucket: "historical",
    };
    const research = managerResearchPayloadFor(targetDate, [{
      ...managerPriorityFacts(targetDate, "01191"),
      name: "海光芯正",
      catalyst_result: {
        status: "READY",
        events: [catalystEvent, directoryEvent, unknownEvent],
        current_events: [catalystEvent],
        historical_events: [directoryEvent, unknownEvent],
        catalyst_advice: {
          status: "OBSERVE",
          label: "催化观察",
          priority_rank: 1,
          focus_eligible: true,
          focus_window_days: 14,
          priority_reason: "保留媒体合作观察，官方确认待补。",
          summary: "媒体不等于订单或收入。",
        },
        source_coverage: [{ source_id: "iccsz.media.directory.v1", status: "READY" }],
        catalyst_coverage: {
          event_count: 3,
          current_event_count: 1,
          historical_event_count: 2,
          focus_event_count: 1,
          completeness: "BOUNDED_SOURCES_ONLY",
        },
        current_event_as_of: "2026-09-08T08:00:00+00:00",
        market_confirmation_gap: catalystEvent.market_confirmation_gap,
      },
    }]);
    (research.product as Record<string, unknown>).catalyst_coverage = {
      event_count: 3,
      current_event_count: 1,
      historical_event_count: 2,
      focus_event_count: 1,
      completeness: "BOUNDED_SOURCES_ONLY",
    };
    const selection = selectionForDate(targetDate);
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v3/preselection-pools")) return response(preselectionForDate(targetDate));
      if (url.includes("/api/v3/manager/stage-selection")) return response(stage);
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(selection));
      if (url.includes("/api/v4/manager/research")) return response(research);
      return response(selection);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    await screen.findByText("海光芯正携手格罗方德深化全球战略合作");
    const currentResearch = await screen.findByRole("region", { name: "当前研究与近期催化" });
    expect(currentResearch).toBeTruthy();
    const readingDesk = currentResearch.querySelector(".manager-reading-desk");
    expect(readingDesk).toBeTruthy();
    expect(currentResearch.querySelector(".manager-catalyst-list")).toBeNull();
    const catalystAudit = currentResearch.querySelector(".manager-catalyst-audit");
    expect(catalystAudit).toBeTruthy();
    expect(catalystAudit?.textContent).toContain("公告目录线索");
    expect(within(currentResearch).getByText(/coverage=资料 CANNOT_CONFIRM 条（reader=CANNOT_CONFIRM）· 原事件 3 条/)).toBeTruthy();
    const readingCards = [...currentResearch.querySelectorAll(".manager-reading-card")];
    expect(readingCards).toHaveLength(3);
    expect(currentResearch.textContent).toContain("MEDIA");
    expect(currentResearch.textContent).toContain("iccsz.media.directory.v1");
    expect(currentResearch.textContent).toContain("OFFICIAL");
    expect(currentResearch.textContent).toContain("v4.hkex.official_event_directory.v1");
    expect(currentResearch.textContent).toContain("UNKNOWN");
    expect(currentResearch.textContent).toContain("unclassified.source.v1");
    expect(currentResearch.textContent).toContain("来源摘要");
    expect(currentResearch.textContent).not.toContain("港交所/发行人公告目录");
    expect(currentResearch.textContent).not.toContain("官方公告可得摘要");
    expect(within(currentResearch).getByText(/公开资料/)).toBeTruthy();
    expect(within(currentResearch).getByText("按钮只更新研究材料，不提交交易")).toBeTruthy();
    expect(within(currentResearch).queryByText("BUY")).toBeNull();

    await fireEvent.click(within(currentResearch).getByRole("button", { name: "刷新公开资料" }));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v4/manager/research/events?date=20260908",
      expect.objectContaining({ method: "POST", cache: "no-store", signal: expect.any(AbortSignal) }),
    );
  });

  it("shows compact per-stock reader states and retains ALL-view associations after dedupe", async () => {
    vi.setSystemTime(new Date("2026-09-08T08:00:00.000Z"));
    window.history.replaceState({}, "", "/manager-selection/?date=20260908");
    const targetDate = "20260908";
    const stage = managerPriorityStageFor(targetDate, [
      managerPriorityStageRow("01191", "海光芯正", 1),
      managerPriorityStageRow("06166", "星河公司", 2),
      managerPriorityStageRow("06869", "无匹配公司", 3),
    ]);
    const sharedMaterial = {
      id: "shared-public-material",
      title: "两只候选共同的公开报道",
      content_excerpt: "来源提供的原文摘要",
      content_is_excerpt: true,
      published_at: "2026-09-08 08:00:00",
      published_date: "2026-09-08",
      source_name: "测试公开源",
      source_url: "https://example.test/shared",
      source_count: 1,
      source_attributions: [{ source_name: "测试公开源", url: "https://example.test/shared" }],
    };
    const research = managerResearchPayloadFor(targetDate, [
      {
        ...managerPriorityFacts(targetDate, "01191"),
        name: "海光芯正",
        catalyst_result: {
          reader_status: "READY",
          reader_source_gaps: [],
          reader_materials: [sharedMaterial],
        },
      },
      {
        ...managerPriorityFacts(targetDate, "06166"),
        name: "星河公司",
        catalyst_result: {
          reader_status: "PARTIAL",
          reader_source_gaps: ["PUBLIC_NEWS_ERROR: TimeoutError"],
          reader_materials: [sharedMaterial],
        },
      },
      {
        ...managerPriorityFacts(targetDate, "06869"),
        name: "无匹配公司",
        catalyst_result: {
          reader_status: "ERROR",
          reader_source_gaps: ["PUBLIC_NEWS_EMPTY: 公开个股新闻源未返回记录"],
          reader_materials: [],
        },
      },
    ]);
    const selection = selectionForDate(targetDate);
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v3/preselection-pools")) return response(preselectionForDate(targetDate));
      if (url.includes("/api/v3/manager/stage-selection")) return response(stage);
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(selection));
      if (url.includes("/api/v4/manager/research")) return response(research);
      return response(selection);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    const currentResearch = await screen.findByRole("region", { name: "当前研究与近期催化" });
    await within(currentResearch).findByText("两只候选共同的公开报道");
    expect(currentResearch.textContent).toContain("每只固定候选的资料状态");
    expect(currentResearch.textContent).toContain("海光芯正 · HK.01191");
    expect(currentResearch.textContent).toContain("公开新闻抓取状态=READY · 公开新闻=1 条");
    expect(currentResearch.textContent).toContain("星河公司 · HK.06166");
    expect(currentResearch.textContent).toContain("公开新闻抓取状态=PARTIAL · 公开新闻=1 条");
    expect(currentResearch.textContent).not.toContain("可读资料=1 条");
    expect(currentResearch.textContent).toContain("来源缺口：PUBLIC_NEWS_ERROR: TimeoutError");
    expect(currentResearch.textContent).toContain("无匹配公司 · HK.06869");
    expect(currentResearch.textContent).toContain("来源缺口：PUBLIC_NEWS_EMPTY: 公开个股新闻源未返回记录");
    const readingCards = [...currentResearch.querySelectorAll(".manager-reading-card")];
    expect(readingCards).toHaveLength(1);
    expect(readingCards[0]?.textContent).toContain("海光芯正 · HK.01191");
    expect(readingCards[0]?.textContent).toContain("星河公司 · HK.06166");
  });

  it("keeps a material without a usable URL readable without rendering an anchor", async () => {
    vi.setSystemTime(new Date("2026-09-08T08:00:00.000Z"));
    window.history.replaceState({}, "", "/manager-selection/?date=20260908");
    const targetDate = "20260908";
    const stage = managerPriorityStageFor(targetDate, [managerPriorityStageRow("01191", "海光芯正", 1)]);
    const research = managerResearchPayloadFor(targetDate, [{
      ...managerPriorityFacts(targetDate, "01191"),
      name: "海光芯正",
      catalyst_result: {
        reader_status: "READY",
        reader_source_gaps: [],
        reader_materials: [{
          id: "no-url-material",
          title: "无原文链接的可读材料",
          content_excerpt: "标题和摘要仍由来源提供。",
          published_at: "2026-09-08 08:00:00",
          published_date: "2026-09-08",
          source_name: "测试公开源",
          source_url: null,
        }],
      },
    }]);
    const selection = selectionForDate(targetDate);
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v3/preselection-pools")) return response(preselectionForDate(targetDate));
      if (url.includes("/api/v3/manager/stage-selection")) return response(stage);
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(selection));
      if (url.includes("/api/v4/manager/research")) return response(research);
      return response(selection);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    const card = await screen.findByText("无原文链接的可读材料");
    const readingCard = card.closest(".manager-reading-card");
    expect(readingCard).toBeTruthy();
    expect(readingCard?.querySelector("a"), "unusable source URLs must not become clickable anchors").toBeNull();
    expect(readingCard?.textContent).toContain("原文链接不可得（CANNOT_CONFIRM）");
  });

  it("sorts mixed source timestamps chronologically and keeps unknown timestamps last", async () => {
    vi.setSystemTime(new Date("2026-09-08T08:00:00.000Z"));
    window.history.replaceState({}, "", "/manager-selection/?date=20260908");
    const targetDate = "20260908";
    const stage = managerPriorityStageFor(targetDate, [managerPriorityStageRow("01191", "海光芯正", 1)]);
    const event = (id: string, title: string, publishedAt: string, sourceKind: string) => ({
      event_id: id,
      source_kind: sourceKind,
      source_id: `${sourceKind.toLowerCase()}.fixture`,
      source_title: title,
      catalyst: title,
      source_excerpt: `${title} 摘要`,
      publisher_timestamp: publishedAt,
      first_seen_at: "2026-09-08T08:00:00+00:00",
      source_url: `https://example.test/${id}`,
      body_parsed: false,
      event_status: "CANNOT_CONFIRM",
      event_relevant: false,
      as_of_bucket: "historical",
    });
    const research = managerResearchPayloadFor(targetDate, [{
      ...managerPriorityFacts(targetDate, "01191"),
      name: "海光芯正",
      catalyst_result: {
        status: "READY",
        events: [
          event("official-20", "官方20点材料", "2026-09-08T20:00:00+08:00", "OFFICIAL"),
          event("media-1318", "媒体13点材料", "2026-09-08T13:18:14+08:00", "MEDIA"),
          event("unknown-time", "未知时间材料", "CANNOT_CONFIRM", "UNKNOWN"),
        ],
        reader_status: "READY",
        reader_source_gaps: [],
        reader_materials: [
          {
            id: "public-2212",
            title: "公开新闻22点材料",
            content_excerpt: "Eastmoney 原文摘要",
            content_is_excerpt: true,
            published_at: "2026-09-08 22:12:34",
            published_date: "2026-09-08",
            source_name: "Eastmoney fixture",
            source_url: "https://example.test/public-2212",
          },
          {
            id: "future-public",
            title: "目标日之后材料",
            content_excerpt: "必须被日期上限排除",
            published_at: "2026-09-09 00:10:00",
            source_name: "Eastmoney fixture",
            source_url: "https://example.test/future-public",
          },
        ],
      },
    }]);
    const selection = selectionForDate(targetDate);
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v3/preselection-pools")) return response(preselectionForDate(targetDate));
      if (url.includes("/api/v3/manager/stage-selection")) return response(stage);
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(selection));
      if (url.includes("/api/v4/manager/research")) return response(research);
      return response(selection);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    const currentResearch = await screen.findByRole("region", { name: "当前研究与近期催化" });
    await within(currentResearch).findByText("公开新闻22点材料");
    const titles = [...currentResearch.querySelectorAll(".manager-reading-card h3")]
      .map((title) => title.textContent?.trim());
    expect(titles).toEqual([
      "公开新闻22点材料",
      "官方20点材料",
      "媒体13点材料",
      "未知时间材料",
    ]);
    expect(currentResearch.textContent).not.toContain("目标日之后材料");
  });

  it("ensures a missing exact manager-research product once when the server declares it can be ensured", async () => {
    const targetDate = "20260910";
    window.history.replaceState({}, "", `/manager-selection/?date=${targetDate}`);
    const selection = selectionForDate(targetDate);
    const stage = managerPriorityStageFor(targetDate, [managerPriorityStageRow("01191", "海光芯正", 1)]);
    const missing = managerResearchNullProductFor(targetDate);
    const ensured = managerResearchPayloadFor(targetDate);
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v3/preselection-pools")) return response(preselectionForDate(targetDate));
      if (url.includes("/api/v3/manager/stage-selection")) return response(stage);
      if (url.includes("/api/v3/research/selection/manager-decision")) {
        return response(managerDecisionResponseFor(selection));
      }
      if (url.includes("/api/v4/manager/research/ensure")) return response(ensured);
      if (url.includes("/api/v4/manager/research?")) return response(missing);
      return response(selection);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([url]) => url.includes("/api/v4/manager/research/ensure"))).toHaveLength(1);
    });
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v4/manager/research/ensure?date=${targetDate}`,
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
    );
    expect(fetchMock.mock.calls.filter(([url]) => url.includes("/api/v4/manager/research?")).length).toBe(1);
  });

  it("consumes a queued event job through READY and replaces the reader projection", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-08T08:00:00.000Z"));
    window.history.replaceState({}, "", "/manager-selection/?date=20260908");
    const targetDate = "20260908";
    const stage = managerPriorityStageFor(targetDate, [managerPriorityStageRow("01191", "海光芯正", 1)]);
    const baseline = managerResearchPayloadFor(targetDate, [managerPriorityFacts(targetDate, "01191")]);
    const baselineProduct = baseline.product as Record<string, unknown>;
    const finalProduct = {
      ...baselineProduct,
      reader_coverage: {
        status: "READY",
        material_count: 1,
        requested_candidates: 1,
        ready_candidates: 1,
        partial_candidates: 0,
        error_candidates: 0,
      },
      rows: (baselineProduct.rows as Record<string, unknown>[]).map((row) => ({
        ...row,
        catalyst_result: {
          reader_status: "READY",
          reader_source_gaps: [],
          reader_materials: [{
            id: "ready-after-job",
            title: "READY 后更新的公开资料",
            content_excerpt: "终态 job 返回的来源摘要",
            content_is_excerpt: true,
            published_at: "2026-09-08 18:21:52",
            published_date: "2026-09-08",
            source_name: "Eastmoney fixture",
            source_url: "https://example.test/ready-after-job",
          }],
        },
      })),
    };
    const queued = {
      ...baseline,
      status: "QUEUED",
      job: {
        job_id: "mr-events-fixture",
        status: "QUEUED",
        progress: { total: 1, completed: 0, event_rows: 0, reader_materials: 0 },
      },
    };
    const ready = {
      ...baseline,
      status: "READY",
      product: finalProduct,
      job: {
        job_id: "mr-events-fixture",
        status: "READY",
        progress: { total: 1, completed: 1, event_rows: 1, reader_materials: 1 },
      },
    };
    const selection = selectionForDate(targetDate);
    let jobPolls = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v3/preselection-pools")) return response(preselectionForDate(targetDate));
      if (url.includes("/api/v3/manager/stage-selection")) return response(stage);
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(selection));
      if (url.includes("/api/v4/manager/research/events")) return response(queued);
      if (url.includes("/api/v4/manager/research/jobs/mr-events-fixture")) {
        jobPolls += 1;
        return response(jobPolls < 35 ? queued : ready);
      }
      if (url.includes("/api/v4/manager/research")) return response(baseline);
      return response(selection);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    await nextTick();
    const currentResearch = screen.getByRole("region", { name: "当前研究与近期催化" });
    const refreshButton = within(currentResearch).getByRole("button", { name: "刷新公开资料" });
    for (let attempt = 0; attempt < 20 && (refreshButton as HTMLButtonElement).disabled; attempt += 1) {
      await Promise.resolve();
      await nextTick();
    }
    expect((refreshButton as HTMLButtonElement).disabled).toBe(false);
    await fireEvent.click(refreshButton);
    await vi.advanceTimersByTimeAsync(180_000);
    expect(within(currentResearch).getByText("READY 后更新的公开资料")).toBeTruthy();
    expect(within(currentResearch).getByText("公开资料已更新；页面仍保持 RESEARCH_ONLY，不提交交易。")).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([url]) => url.includes("/api/v4/manager/research/events"))).toHaveLength(1);
    expect(jobPolls).toBe(35);
    expect(fetchMock.mock.calls.some(([url]) => url.includes("/api/v4/manager/research/ensure"))).toBe(false);
  });

  it("keeps an all-source catalyst refresh outage out of the success state", async () => {
    vi.setSystemTime(new Date("2026-09-08T08:00:00.000Z"));
    window.history.replaceState({}, "", "/manager-selection/?date=20260908");
    const targetDate = "20260908";
    const stage = managerPriorityStageFor(targetDate, [managerPriorityStageRow("01191", "海光芯正", 1)]);
    const baseline = managerResearchPayloadFor(targetDate, [managerPriorityFacts(targetDate, "01191")]);
    const failedRefresh = {
      ...baseline,
      status: "CANNOT_CONFIRM",
      cannot_confirm: ["ALL_EVENT_SOURCES_FAILED"],
      product: {
        ...(baseline.product as Record<string, unknown>),
        status: "CANNOT_CONFIRM",
        catalyst_status: "CANNOT_CONFIRM",
        catalyst_coverage: {
          event_count: 0,
          current_event_count: 0,
          historical_event_count: 0,
          completeness: "BOUNDED_SOURCES_ONLY",
          all_sources_failed: true,
        },
      },
      job: { status: "CANNOT_CONFIRM", progress: { event_rows: 0 } },
    };
    const selection = selectionForDate(targetDate);
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v3/preselection-pools")) return response(preselectionForDate(targetDate));
      if (url.includes("/api/v3/manager/stage-selection")) return response(stage);
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(selection));
      if (url.includes("/api/v4/manager/research/events")) return response(failedRefresh);
      if (url.includes("/api/v4/manager/research")) return response(baseline);
      return response(selection);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    const currentResearch = await screen.findByRole("region", { name: "当前研究与近期催化" });
    await within(currentResearch).findByText("financial_status=CANNOT_CONFIRM");
    await fireEvent.click(within(currentResearch).getByRole("button", { name: "刷新公开资料" }));
    expect(await within(currentResearch).findByText(/资料刷新=CANNOT_CONFIRM；reader_material_count=0；event_count=0/)).toBeTruthy();
    expect(within(currentResearch).queryByText("公开资料已更新；页面仍保持 RESEARCH_ONLY，不提交交易。")).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v4/manager/research/events?date=20260908",
      expect.objectContaining({ method: "POST", cache: "no-store", signal: expect.any(AbortSignal) }),
    );
  });

  it("keeps all stage cards and shows no research preference when the product is not materialized", async () => {
    vi.setSystemTime(new Date("2026-09-08T03:00:00.000Z"));
    window.history.replaceState({}, "", "/manager-selection/?date=20260908");
    const targetDate = "20260908";
    const stageRows = [
      managerPriorityStageRow("00001", "无研究事实公司", 1),
      managerPriorityStageRow("00002", "第二只公司", 2),
    ];
    const stage = managerPriorityStageFor(targetDate, stageRows);
    const selection = selectionForDate(targetDate);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.includes("/api/v3/preselection-pools")) return response(preselectionForDate(targetDate));
      if (url.includes("/api/v3/manager/stage-selection")) return response(stage);
      if (url.includes("/api/v4/manager/research")) return response(managerResearchNullProductFor(targetDate));
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(selection));
      return response(selection);
    }));

    render(ManagerSelectionView);

    const dashboard = await screen.findByRole("region", { name: "经理决策优先级摘要" });
    expect(within(dashboard).getByText("尚无可比较首选：同报告期官方结构化指标尚未物化或无法确认。")).toBeTruthy();
    const stagePanel = await screen.findByRole("region", { name: "今日港股通阶段候选" });
    expect(stagePanel.querySelectorAll(".manager-stage-card")).toHaveLength(2);
    expect(stagePanel.textContent).toContain("无研究事实公司");
    expect(stagePanel.textContent).toContain("第二只公司");
    expect(stagePanel.textContent).toContain("v4_manager_research=NOT_MATERIALIZED");
    expect(stagePanel.textContent).not.toContain("研究优先级 #1");
  });

  it("keeps a contract-valid top-level READY and HK PARTIAL conflict at CANNOT_CONFIRM", async () => {
    vi.setSystemTime(new Date("2026-09-08T03:00:00.000Z"));
    window.history.replaceState({}, "", "/manager-selection/?date=20260908");
    const targetDate = "20260908";
    const stageRows = [managerPriorityStageRow("00001", "冲突阶段证据公司", 1, {
      action_level: "BUY",
      formal_eligible: true,
    })];
    const baseStage = managerPriorityStageFor(targetDate, stageRows);
    const stage = {
      ...baseStage,
      status: "READY",
      cannot_confirm: [],
      markets: {
        ...baseStage.markets,
        HK: {
          ...baseStage.markets.HK,
          status: "PARTIAL_WITH_ROWS",
          selection_status: "PARTIAL_WITH_ROWS",
          selected_rows: stageRows.length,
          rows: stageRows,
        },
      },
    };
    expect(validateManagerStageSelection(stage, targetDate)).toBeNull();
    const selection = selectionForDate(targetDate);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.includes("/api/v3/preselection-pools")) return response(preselectionForDate(targetDate));
      if (url.includes("/api/v3/manager/stage-selection")) return response(stage);
      if (url.includes("/api/v4/manager/research")) return response(managerResearchPayloadFor(targetDate));
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(selection));
      return response(selection);
    }));

    render(ManagerSelectionView);

    const stagePanel = await screen.findByRole("region", { name: "今日港股通阶段候选" });
    await waitFor(() => expect(stagePanel.querySelector(".manager-stage-card--cannot_confirm")).toBeTruthy());
    const card = stagePanel.querySelector(".manager-stage-card--cannot_confirm");
    expect(card?.textContent).toContain("CANNOT_CONFIRM（执行门）");
    expect(card?.textContent).toContain("独立投资研究意见：CANNOT_CONFIRM");
    expect(card?.textContent).not.toContain("执行门（stage）：BUY（执行门）");
  });

  it("clears a previous date's priority rows before rendering the new exact-date stage", async () => {
    vi.setSystemTime(new Date("2026-09-08T03:00:00.000Z"));
    window.history.replaceState({}, "", "/manager-selection/?date=20260907");
    const firstDate = "20260907";
    const secondDate = "20260908";
    const stageByDate: Record<string, unknown> = {
      [firstDate]: managerPriorityStageFor(firstDate, [managerPriorityStageRow("00011", "旧日期阶段行", 1)]),
      [secondDate]: managerPriorityStageFor(secondDate, [managerPriorityStageRow("00022", "新日期阶段行", 1)]),
    };
    const selectionByDate: Record<string, unknown> = {
      [firstDate]: selectionForDate(firstDate),
      [secondDate]: selectionForDate(secondDate),
    };
    const fetchMock = vi.fn(async (url: string) => {
      const date = url.match(/(?:date|target_trade_date|research_date)=(\d{8})/)?.[1] || firstDate;
      if (url.includes("/api/v3/preselection-pools")) return response(preselectionForDate(date));
      if (url.includes("/api/v3/manager/stage-selection")) return response(stageByDate[date]);
      if (url.includes("/api/v4/manager/research")) return response(managerResearchPayloadFor(date));
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(selectionByDate[date]));
      return response(selectionByDate[date]);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);
    expect(await screen.findByText("旧日期阶段行")).toBeTruthy();

    const dateInput = screen.getByLabelText("目标交易日") as HTMLInputElement;
    dateInput.value = "2026-09-08";
    await fireEvent.change(dateInput);

    expect(await screen.findByText("新日期阶段行")).toBeTruthy();
    expect(screen.queryByText("旧日期阶段行")).toBeNull();
    expect((screen.getByLabelText("目标交易日") as HTMLInputElement).value).toBe("2026-09-08");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v3/manager/stage-selection?date=20260908&stage=STAGE_0935_0940&limit=50&market=HK_CONNECT",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
    );
  });

  it("renders the 20260904 HK.02718 card with fixed contribution semantics", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260904");
    const evidenceRef = (type: string) => ({
      type,
      code: "HK.02718",
      source_date: "20260903",
      target_trade_date: "20260904",
      sha256: "f".repeat(64),
    });
    const stageFixture = {
      ...managerStageSelection,
      trade_date: "20260904",
      markets: {
        HK: {
          ...managerStageSelection.markets.HK,
          rows: [{
            market: "HK_CONNECT",
            code: "HK.02718",
            name: "HK.02718 fixture",
            target_trade_date: "20260904",
            rank: 1,
            d1_rank: 5,
            d1_prob_active: 0.6837,
            pct_chg: 8.43,
            stage_window_change_pct: 0.47,
            stage_score: 57,
            d1_source_refs: [evidenceRef("HK_D1_TOP100")],
            stage_source_refs: [evidenceRef("HK_STAGE_0935_0940")],
          }],
          selected_rows: 1,
        },
      },
    };
    const researchLane = {
      schema_version: "v3_5.research_lane.v1",
      status: "LIVE_PERIPHERAL_ONLY",
      research_date: "20260904",
      endpoint_mode: "EXACT",
      external_finance: {
        status: "READY",
        items: [{ title: "US market background", source_date: "20260904" }],
      },
      morning_news: {
        status: "READY",
        articles: [{ title: "market sentiment background", published_at: "2026-09-04T08:00:00+08:00" }],
      },
      cannot_confirm: [],
      write_policy: "read_only",
      recommendation_status: "RESEARCH_ONLY",
      production_allowed: false,
      buy_gate_updated: false,
      orders_sent: false,
    };
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v3/manager/stage-selection")) return response(stageFixture);
      if (url.includes("/api/v4/manager/research?date=20260904")) return response(managerResearchPayloadFor("20260904", [{
        code: "HK.02718",
        market: "HK_CONNECT",
        target_trade_date: "20260904",
        source_status: "READY",
        source: {
          document_title: "02718 official announcement",
          provider_id: "HKEX",
          published_at: "2026-09-03T16:31+08:00",
          retrieved_at: "2026-09-04T03:07:04+00:00",
          source_url: "https://example.com/hkex/02718.pdf",
        },
        facts: [{ statement_cn: "官方事实：收入增长", locator: "PDF page 12" }],
      }]));
      if (url.includes("/api/v3/research/lane?research_date=20260904")) return response(researchLane);
      if (url.includes("/api/v3/preselection-pools")) return response(preselectionForDate("20260904"));
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(selectionForDate("20260904")));
      return response(selectionForDate("20260904"));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    const panel = await screen.findByRole("region", { name: "今日港股通阶段候选" });
    const card = await within(panel).findByText("HK.02718 fixture");
    const article = card.closest("article") as HTMLElement;
    expect(article.textContent).toContain("观察入榜原因（非经理入选）");
    expect(article.textContent).toContain("D1第5位");
    expect(article.textContent).toContain("prob_active 排序分约0.684");
    expect(article.textContent).toContain("仅用于入池排序");
    expect(article.textContent).toContain("09:40相对前收日涨幅+8.43%");
    expect(article.textContent).toContain("阶段窗口（09:35-09:40）涨幅+0.47%");
    expect(article.textContent).toContain("阶段排序分57");
    expect(article.textContent).toContain("NO_TRADE / NO_BUY / 非经理入选");
    expect(article.textContent).not.toContain("入选理由");
    expect(article.querySelectorAll(".manager-stage-contribution")).toHaveLength(5);
    expect(article.querySelector('[data-contribution-status="JOINED"] strong')?.textContent).toContain("D1");
    expect(article.querySelectorAll('[data-contribution-status="JOINED"]')).toHaveLength(2);
    expect(article.querySelectorAll('[data-contribution-status="AVAILABLE_NOT_JOINED"]')).toHaveLength(3);
    expect(article.querySelectorAll('[data-contribution-status="UPSTREAM_MISSING"]')).toHaveLength(0);
    expect(article.textContent).toContain("V4 HKEX官方材料已采集");
    expect(article.textContent).toContain("官方事实：收入增长");
    expect(article.querySelector('.manager-stage-contribution__background a')?.getAttribute("href"))
      .toBe("https://example.com/hkex/02718.pdf");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v3/research/lane?research_date=20260904",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v4/manager/research?date=20260904",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
    );
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/v3/research/lane")).toBe(false);
  });

  it("keeps the stage card visible when the exact research lane request fails", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260904");
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v3/manager/stage-selection")) {
        return response({ ...managerStageSelection, trade_date: "20260904" });
      }
      if (url.includes("/api/v3/research/lane?research_date=20260904")) throw new Error("lane unavailable");
      if (url.includes("/api/v3/preselection-pools")) return response(preselectionForDate("20260904"));
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(selectionForDate("20260904")));
      return response(selectionForDate("20260904"));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    const panel = await screen.findByRole("region", { name: "今日港股通阶段候选" });
    await within(panel).findByText("云知声");
    const article = within(panel).getByText("云知声").closest("article") as HTMLElement;
    expect(article.querySelectorAll(".manager-stage-contribution")).toHaveLength(5);
    expect(article.querySelectorAll('[data-contribution-status="CANNOT_CONFIRM"]')).toHaveLength(5);
    expect(within(panel).queryByText("lane unavailable")).toBeNull();
  });

  it("aborts and ignores a deferred exact research lane from the previous date", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260904");
    const oldLane = deferred<ReturnType<typeof response>>();
    let oldLaneSignal: AbortSignal | undefined;
    const researchLaneFor = (date: string) => ({
      schema_version: "v3_5.research_lane.v1",
      status: "LIVE_PERIPHERAL_ONLY",
      research_date: date,
      endpoint_mode: "EXACT",
      cannot_confirm: [],
      write_policy: "read_only",
      recommendation_status: "RESEARCH_ONLY",
      production_allowed: false,
      buy_gate_updated: false,
      orders_sent: false,
    });
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.includes("/api/v3/research/lane?research_date=20260904")) {
        oldLaneSignal = init?.signal ?? undefined;
        return oldLane.promise;
      }
      if (url.includes("/api/v3/research/lane?research_date=20260905")) {
        return Promise.resolve(response(researchLaneFor("20260905")));
      }
      if (url.includes("/api/v3/manager/stage-selection")) {
        return Promise.resolve(response({ ...managerStageSelection, trade_date: url.includes("20260905") ? "20260905" : "20260904" }));
      }
      if (url.includes("/api/v3/preselection-pools")) return Promise.resolve(response(preselectionForDate(url.includes("20260905") ? "20260905" : "20260904")));
      if (url.includes("/api/v3/research/selection/manager-decision")) return Promise.resolve(response(managerDecisionResponseFor(selectionForDate(url.includes("20260905") ? "20260905" : "20260904"))));
      return Promise.resolve(response(selectionForDate(url.includes("20260905") ? "20260905" : "20260904")));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);
    await waitFor(() => expect(oldLaneSignal).toBeDefined());

    const dateInput = screen.getByLabelText("目标交易日") as HTMLInputElement;
    dateInput.value = "2026-09-05";
    await fireEvent.change(dateInput);
    expect(oldLaneSignal?.aborted).toBe(true);
    expect((await screen.findAllByText("20260905")).length).toBeGreaterThan(0);
    const panel = screen.getByRole("region", { name: "今日港股通阶段候选" });
    await waitFor(() => expect(panel.querySelectorAll('[data-contribution-status="UPSTREAM_MISSING"]')).toHaveLength(16));

    oldLane.resolve(response({
      ...researchLaneFor("20260904"),
      external_finance: { status: "READY", items: [{ code: "HK.02718", source_date: "20260904", source_refs: [{ code: "HK.02718", target_trade_date: "20260904", path: "/old" }] }] },
    }));
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    expect((screen.getByLabelText("目标交易日") as HTMLInputElement).value).toBe("2026-09-05");
    expect(panel.querySelectorAll('[data-contribution-status="UPSTREAM_MISSING"]')).toHaveLength(16);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v3/research/lane?research_date=20260905",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
    );
  });

  it("times out an exact research lane without hiding the stage card", async () => {
    vi.useFakeTimers();
    window.history.replaceState({}, "", "/manager-selection/?date=20260904");
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("/api/v3/research/lane?research_date=20260904")) return new Promise(() => undefined);
      if (url.includes("/api/v3/manager/stage-selection")) return Promise.resolve(response({ ...managerStageSelection, trade_date: "20260904" }));
      if (url.includes("/api/v3/preselection-pools")) return Promise.resolve(response(preselectionForDate("20260904")));
      if (url.includes("/api/v3/research/selection/manager-decision")) return Promise.resolve(response(managerDecisionResponseFor(selectionForDate("20260904"))));
      return Promise.resolve(response(selectionForDate("20260904")));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);
    await screen.findByRole("region", { name: "今日港股通阶段候选" });
    await vi.advanceTimersByTimeAsync(10_000);
    await nextTick();

    const panel = screen.getByRole("region", { name: "今日港股通阶段候选" });
    expect(within(panel).getByText("云知声")).toBeTruthy();
    expect(panel.querySelectorAll('[data-contribution-status="CANNOT_CONFIRM"]')).toHaveLength(40);
  });

  it("keeps the HK stage count unknown when the stage date does not match", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v3/manager/stage-selection")) {
        return response({ ...managerStageSelection, trade_date: "20260830" });
      }
      if (url.includes("/api/v3/preselection-pools")) return response(preselection);
      return response(product);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    const panel = await screen.findByRole("region", { name: "今日港股通阶段候选" });
    await waitFor(() => expect(panel.querySelector(".manager-stage-audit .manager-stage-note")?.textContent)
      .toContain("数量未知（CANNOT_CONFIRM）"));
    expect(panel.querySelector(".manager-stage-grid")).toBeNull();
    expect(panel.textContent).not.toContain("云知声");
    expect(panel.textContent).not.toContain("A股fixture-");
  });

  it("keeps the HK stage count unknown when markets.HK is missing", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v3/manager/stage-selection")) {
        return response({ ...managerStageSelection, markets: { A: managerStageSelection.markets.A } });
      }
      if (url.includes("/api/v3/preselection-pools")) return response(preselection);
      return response(product);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    const panel = await screen.findByRole("region", { name: "今日港股通阶段候选" });
    await waitFor(() => expect(panel.querySelector(".manager-stage-audit .manager-stage-note")?.textContent)
      .toContain("markets.HK 缺失"));
    expect(panel.querySelector(".manager-stage-grid")).toBeNull();
    expect(panel.textContent).not.toContain("云知声");
    expect(panel.textContent).not.toContain("A股fixture-");
  });

  it("keeps the HK stage count unknown when the research-only safety flag is invalid", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v3/manager/stage-selection")) {
        return response({ ...managerStageSelection, RESEARCH_ONLY: false });
      }
      if (url.includes("/api/v3/preselection-pools")) return response(preselection);
      return response(product);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    const panel = await screen.findByRole("region", { name: "今日港股通阶段候选" });
    await waitFor(() => expect(panel.querySelector(".manager-stage-audit .manager-stage-note")?.textContent)
      .toContain("RESEARCH_ONLY 必须是 true"));
    expect(panel.querySelector(".manager-stage-grid")).toBeNull();
    expect(panel.textContent).not.toContain("云知声");
    expect(panel.textContent).not.toContain("A股fixture-");
  });

  it("keeps the HK stage count unknown for an unrecognized top-level stage status", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v3/manager/stage-selection")) {
        return response({ ...managerStageSelection, status: "BOGUS" });
      }
      if (url.includes("/api/v3/preselection-pools")) return response(preselection);
      return response(product);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    const panel = await screen.findByRole("region", { name: "今日港股通阶段候选" });
    await waitFor(() => expect(panel.querySelector(".manager-stage-audit .manager-stage-note")?.textContent)
      .toContain("stage selection status"));
    expect(panel.querySelector(".manager-stage-audit .manager-stage-note")?.textContent).toContain("数量未知（CANNOT_CONFIRM）");
    expect(panel.querySelector(".manager-stage-grid")).toBeNull();
    expect(panel.textContent).not.toContain("云知声");
    expect(panel.textContent).not.toContain("A股fixture-");
  });

  it("does not render HK rows when the HK lane is CANNOT_CONFIRM", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v3/manager/stage-selection")) {
        return response({
          ...managerStageSelection,
          markets: {
            ...managerStageSelection.markets,
            HK: {
              ...managerStageSelection.markets.HK,
              status: "CANNOT_CONFIRM",
              selection_status: "CANNOT_CONFIRM",
              selected_rows: managerStageSelection.markets.HK.rows.length,
            },
          },
        });
      }
      if (url.includes("/api/v3/preselection-pools")) return response(preselection);
      return response(product);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    const panel = await screen.findByRole("region", { name: "今日港股通阶段候选" });
    await waitFor(() => expect(panel.querySelector(".manager-stage-audit .manager-stage-note")?.textContent)
      .toContain("markets.HK.status"));
    expect(panel.querySelector(".manager-stage-grid")).toBeNull();
    expect(panel.textContent).not.toContain("云知声");
    expect(panel.textContent).not.toContain("A股fixture-");
  });

  it("accepts the real D-1 envelope when optional row evidence is absent", () => {
    const optionalFields = new Set([
      "market",
      "pool_id",
      "pool_score",
      "target_date",
      "signal_date",
      "recommendation_status",
      "trade_status_contract",
      "research_only",
      "production_allowed",
      "buy_gate_updated",
      "orders_sent",
    ]);
    const rows = preselection.pools[0].rows.map((row) => Object.fromEntries(
      Object.entries(row).filter(([key]) => !optionalFields.has(key)),
    ));
    const minimal = {
      ...preselection,
      pools: [{
        ...preselection.pools[0],
        source_row_count: 100,
        source_run_id: "preselection-20260831",
        source_sha256: "a".repeat(64),
        producer_id: "shared-hk-preselection",
        rows,
      }],
    };

    expect(validateManagerPreselection(minimal, "20260831")).toBeNull();
  });

  it("quarantines a stage lane when one row has the wrong market", () => {
    const malformed = structuredClone(managerStageSelection) as any;
    malformed.markets.HK.rows[0].market = "A_SHARE";

    expect(validateManagerStageSelection(malformed, "20260831")).toContain("market");
  });

  it("validates an independent manager decision DTO without accepting a path", () => {
    const dto = {
      schema_version: "v3_5.manager_research_decision_read.v1",
      document_schema_version: "v3_5.manager_research_decision.v1",
      endpoint_mode: "EXACT",
      requested_date: "20260827",
      target_trade_date: "20260827",
      status: "READY",
      source_date: "20260827",
      phase: "2200",
      decision_state: "INITIAL_RESEARCH_DELTA",
      run_id: "manager-20260827",
      generated_at: "2026-08-27T22:00:00+08:00",
      cutoff_at: "2026-08-27T21:59:00+08:00",
      core: [{ candidate_id: "HK.00001|00001.HK", reason: "观察" }],
      conditional: [],
      KEEP: [],
      ADD: [{ candidate_id: "HK.00001|00001.HK", reason: "观察" }],
      REMOVE: [],
      qualification_refs: [{ candidate_id: "HK.00001|00001.HK", status: "ELIGIBILITY_CANNOT_CONFIRM", raw_sha256: null }],
      safety: { RESEARCH_ONLY: true, WATCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false },
      lineage: { manager_decision_raw_sha256: "b".repeat(64), selection_artifact_sha256: "c".repeat(64) },
      reason: null,
      cannot_confirm: [],
    };

    expect(validateManagerDecisionResponse(dto, "20260827")).toBeNull();
    expect(JSON.stringify(dto)).not.toContain("path");

    const actionOnly = {
      ...dto,
      core: [],
      ADD: [{ candidate_id: "HK.00001|00001.HK", reason: "观察" }],
      qualification_refs: [],
    };
    expect(validateManagerDecisionResponse(actionOnly, "20260827")).toBeNull();

    const notMaterialized = {
      ...dto,
      status: "NOT_MATERIALIZED",
      source_date: null,
      phase: null,
      decision_state: null,
      run_id: null,
      generated_at: null,
      cutoff_at: null,
      core: [],
      conditional: [],
      KEEP: [],
      ADD: [],
      REMOVE: [],
      qualification_refs: [],
      lineage: null,
      reason: "SELECTION_PRODUCT_NOT_MATERIALIZED",
      cannot_confirm: [],
    };
    expect(validateManagerDecisionResponse(notMaterialized, "20260827")).toBeNull();
    expect(validateManagerDecisionResponse({ ...notMaterialized, reason: null }, "20260827")).toContain("reason");
  });

  it("renders the real backend NOT_MATERIALIZED manager response as a typed empty state", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v3/research/selection/manager-decision")) {
        return response(managerDecisionNotMaterializedResponse());
      }
      if (url.includes("/api/v3/preselection-pools")) return response(preselection);
      if (url.includes("/api/v3/manager/stage-selection")) return response(managerStageSelection);
      return response(product);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);
    await openOriginalSources();

    const focus = await screen.findByRole("region", { name: "经理关注层" });
    expect(within(focus).getByText(/经理决策证据不可确认；不按 review priority 回退角色/)).toBeTruthy();
    expect(within(focus).queryByText("SELECTION_PRODUCT_NOT_MATERIALIZED")).toBeNull();
    expect(document.body.textContent).not.toContain("/Users/lexi/");
    expect(document.body.textContent).not.toContain("/research/20260828/2200_initial_supply_freeze.json");
    expect(document.body.textContent).not.toContain("/research/formal/");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v3/research/selection/manager-decision?target_trade_date=20260831",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
    );
  });

  it("renders B1 research inside the existing priority workbench and merges same-symbol sources", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v4/manager/workbench-research")) return response(workbenchSimulatedFor("20260831"));
      if (url.includes("/api/v3/preselection-pools")) return response(preselection);
      if (url.includes("/api/v3/manager/stage-selection")) return response(managerStageSelection);
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(product));
      return response(product);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    const researchSummary = await screen.findByRole("region", { name: "经理工作台研究发现摘要" });
    expect(researchSummary.parentElement?.id).toBe("manager-priority-dashboard");
    expect(within(researchSummary).getByText("重点关注 · 主题变化 · 风险上升")).toBeTruthy();
    expect(within(researchSummary).getByText(/覆盖 2\/3 · 缺失 1/)).toBeTruthy();
    expect(within(researchSummary).getByText(/RESEARCH_ONLY=true · production_allowed=false · buy_gate_updated=false · orders_sent=false/)).toBeTruthy();

    const panel = await screen.findByRole("region", { name: "今日港股通阶段候选" });
    await waitFor(() => expect(panel.querySelectorAll(".manager-stage-card")).toHaveLength(8));
    expect(panel.querySelectorAll(".manager-discovery-card")).toHaveLength(1);
    const miniMaxCard = [...panel.querySelectorAll(".manager-stage-card")].find((node) => node.textContent?.includes("MINIMAX-W"));
    expect(miniMaxCard).toBeTruthy();
    expect(miniMaxCard?.textContent).toContain("原有阶段候选");
    expect(miniMaxCard?.textContent).toContain("15:30尾盘发现");
    expect(miniMaxCard?.textContent).toContain("持续跟踪");
    expect(panel.textContent).toContain("模拟尾盘候选（SIMULATED）");
    expect(panel.textContent).toContain("SIMULATED · 仅用于隔离合同/界面测试，不是真实扫描结果。");

    await fireEvent.click(within(panel).getByRole("button", { name: "15:30尾盘发现" }));
    await waitFor(() => expect(panel.querySelectorAll(".manager-stage-card")).toHaveLength(1));
    expect(panel.querySelectorAll(".manager-discovery-card")).toHaveLength(1);
    expect(panel.textContent).not.toContain("云知声");

    await fireEvent.click(within(panel).getByRole("button", { name: "原有阶段候选" }));
    await waitFor(() => expect(panel.querySelectorAll(".manager-stage-card")).toHaveLength(8));
    expect(panel.querySelectorAll(".manager-discovery-card")).toHaveLength(0);
  });

  it("keeps independent B1 research visible when Stage evidence cannot confirm", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v4/manager/workbench-research")) return response(workbenchSimulatedFor("20260831"));
      if (url.includes("/api/v3/preselection-pools")) return response(preselection);
      if (url.includes("/api/v3/manager/stage-selection")) return response({ status: "SIMULATED_INVALID_STAGE" });
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(product));
      return response(product);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    const panel = await screen.findByRole("region", { name: "今日港股通阶段候选" });
    await waitFor(() => expect(panel.textContent).toContain("Stage 数量未知（CANNOT_CONFIRM）"));
    await waitFor(() => expect(panel.textContent).toContain("模拟尾盘候选（SIMULATED）"));
    expect(panel.querySelectorAll(".manager-stage-card")).toHaveLength(0);
    expect(panel.querySelectorAll(".manager-discovery-card")).toHaveLength(2);
    expect(panel.textContent).not.toContain("Stage 数量未知（CANNOT_CONFIRM）；HK stage 证据不可确认。独立研究发现已将 Stage 升级为 READY");
  });

  it("uses a dedicated read-only GET when refreshing the new workbench research lane", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const fetchMock = vi.fn(async (url: string, _options?: RequestInit) => {
      if (url.includes("/api/v4/manager/workbench-research")) return response(workbenchSimulatedFor("20260831"));
      if (url.includes("/api/v3/preselection-pools")) return response(preselection);
      if (url.includes("/api/v3/manager/stage-selection")) return response(managerStageSelection);
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(product));
      return response(product);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);
    const summary = await screen.findByRole("region", { name: "经理工作台研究发现摘要" });
    await waitFor(() => expect(within(summary).getAllByText("覆盖不完整，观察待核").length).toBeGreaterThan(0));
    fetchMock.mockClear();

    await fireEvent.click(within(summary).getByRole("button", { name: "只读刷新研究发现" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v4/manager/workbench-research?date=20260831&market=HK_CONNECT&slot=1530");
    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }));
  });

  it("clears old B1 discovery cards while a same-date refresh is loading", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    let refreshPending: ReturnType<typeof deferred<ReturnType<typeof response>>> | null = null;
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v4/manager/workbench-research")) {
        if (refreshPending) return refreshPending.promise;
        return response(workbenchSimulatedFor("20260831"));
      }
      if (url.includes("/api/v3/preselection-pools")) return response(preselection);
      if (url.includes("/api/v3/manager/stage-selection")) return response(managerStageSelection);
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(product));
      return response(product);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);
    const summary = await screen.findByRole("region", { name: "经理工作台研究发现摘要" });
    const panel = await screen.findByRole("region", { name: "今日港股通阶段候选" });
    await waitFor(() => expect(panel.querySelectorAll(".manager-discovery-card")).toHaveLength(1));

    refreshPending = deferred<ReturnType<typeof response>>();
    await fireEvent.click(within(summary).getByRole("button", { name: "只读刷新研究发现" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v4/manager/workbench-research?date=20260831&market=HK_CONNECT&slot=1530",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }),
    ));
    expect(panel.querySelectorAll(".manager-discovery-card")).toHaveLength(0);

    refreshPending.resolve(response(workbenchSimulatedFor("20260831")));
    await waitFor(() => expect(panel.querySelectorAll(".manager-discovery-card")).toHaveLength(1));
  });

  it("maps a B1 research network failure to FAILED", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v4/manager/workbench-research")) throw new Error("simulated network outage");
      if (url.includes("/api/v3/preselection-pools")) return response(preselection);
      if (url.includes("/api/v3/manager/stage-selection")) return response(managerStageSelection);
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(product));
      return response(product);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);

    const summary = await screen.findByRole("region", { name: "经理工作台研究发现摘要" });
    await waitFor(() => expect(within(summary).getAllByText("研究执行或读取失败").length).toBeGreaterThan(0));
    expect(within(summary).getByText("研究发现读取失败：请求或执行未完成，旧结果已清除。")).toBeTruthy();
  });

  it("keeps B1 FAILED visible when Stage is unavailable", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260831");
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/v4/manager/workbench-research")) throw new Error("simulated network outage");
      if (url.includes("/api/v3/preselection-pools")) return response(preselection);
      if (url.includes("/api/v3/manager/stage-selection")) return response({ status: "SIMULATED_INVALID_STAGE" });
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(product));
      return response(product);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);
    await openOriginalSources();

    const summary = await screen.findByRole("region", { name: "经理工作台研究发现摘要" });
    await waitFor(() => expect(within(summary).getAllByText("研究执行或读取失败").length).toBeGreaterThan(0));
    expect(within(summary).getByText("研究发现读取失败：请求或执行未完成，旧结果已清除。")).toBeTruthy();
    const panel = await screen.findByRole("region", { name: "今日港股通阶段候选" });
    expect(panel.querySelectorAll(".manager-discovery-card")).toHaveLength(0);
  });

  it("ignores a late B1 workbench response from the previous exact date", async () => {
    window.history.replaceState({}, "", "/manager-selection/?date=20260917");
    const oldWorkbench = deferred<ReturnType<typeof response>>();
    const fetchMock = vi.fn(async (url: string) => {
      const parsed = new URL(url, "http://test");
      const date = parsed.searchParams.get("date") || parsed.searchParams.get("target_trade_date") || parsed.searchParams.get("research_date") || "20260917";
      if (url.includes("/api/v4/manager/workbench-research")) {
        if (date === "20260917") return oldWorkbench.promise;
        return response(workbenchSimulatedFor(date));
      }
      if (url.includes("/api/v3/preselection-pools")) return response(preselectionForDate(date));
      if (url.includes("/api/v3/manager/stage-selection")) return response({ ...managerStageSelection, trade_date: date });
      if (url.includes("/api/v3/research/selection/manager-decision")) return response(managerDecisionResponseFor(selectionForDate(date)));
      return response(selectionForDate(date));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ManagerSelectionView);
    await fireEvent.change(screen.getByLabelText("目标交易日"), { target: { value: "2026-09-18" } });
    const summary = await screen.findByRole("region", { name: "经理工作台研究发现摘要" });
    await waitFor(() => expect(summary.textContent).toContain("数据截至 2026-09-18T15:30:00+08:00"));

    oldWorkbench.resolve(response(workbenchSimulatedFor("20260917")));
    await nextTick();
    await Promise.resolve();
    expect(summary.textContent).toContain("数据截至 2026-09-18T15:30:00+08:00");
    expect(summary.textContent).not.toContain("数据截至 2026-09-17T15:30:00+08:00");
  });

});

// SIMULATED integration rendering. Browser/production acceptance is separate.
describe('R2 readable existing workbench',()=>{
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    window.history.replaceState({}, '', '/manager-selection/');
  });

  function mockPage(stagePresent: boolean, research: unknown, fail=false) {
    window.history.replaceState({},'', '/manager-selection/?date=20260831');
    vi.stubGlobal('fetch',vi.fn(async (url:string)=>{
      if(url.includes('/api/v4/manager/workbench-research')) { if(fail)throw new Error('SIMULATED outage');return response(research); }
      if(url.includes('/api/v3/preselection-pools'))return response(preselection);
      if(url.includes('/api/v3/manager/stage-selection'))return response(stagePresent?managerStageSelection:{status:'SIMULATED_INVALID_STAGE'});
      if(url.includes('/api/v3/research/selection/manager-decision'))return response(managerDecisionResponseFor(product));
      return response(product);
    }));
    render(ManagerSelectionView);
  }
  it('shows four indicators after opening original sources while card audit stays collapsed',async()=>{
    mockPage(false,workbenchSimulatedFor('20260831'));
    // Frozen UI contract: the original-source section is collapsed by default.
    // Open it by the user's summary click, not by assigning the DOM open flag.
    const sources = await waitFor(() => {
      const element = document.querySelector<HTMLDetailsElement>('details.manager-original-sources');
      expect(element).not.toBeNull();
      return element!;
    });
    expect(sources.open).toBe(false);
    const summary = sources.querySelector(':scope > summary');
    expect(summary).not.toBeNull();
    await fireEvent.click(summary!);
    await waitFor(() => expect(sources.open).toBe(true));

    const panel=await screen.findByRole('region',{name:'今日港股通阶段候选'});
    await waitFor(()=>expect(panel.querySelectorAll('.manager-discovery-card')).toHaveLength(2));
    expect(within(panel).getByText('阶段候选暂不可用：缺少当日阶段结果。尾盘观察单独展示。')).toBeTruthy();
    const card=panel.querySelector('.manager-discovery-card')!;
    const grid=card.querySelector('.manager-condition-grid')!;
    // Indicators are outside the card's own audit details, but inside the
    // intentionally collapsible original-source section.
    expect(grid.closest('details')).toBe(sources);
    for(const label of ['成交额','放量依据','超跌或突破','新催化'])expect(grid.textContent).toContain(label);
    const audit=card.querySelector<HTMLDetailsElement>('details')!;
    expect(audit).not.toBe(sources);
    expect(audit.open).toBe(false);
    expect(audit.textContent).toContain('SIM-CLOSE');

    await fireEvent.click(summary!);
    await waitFor(() => expect(sources.open).toBe(false));
    expect(audit.open).toBe(false);
  });
  it('does not hide tail-session input gaps when Stage already has stocks',async()=>{
    mockPage(true,workbenchMissingFor('20260831'));
    const panel=await screen.findByRole('region',{name:'今日港股通阶段候选'});
    await waitFor(()=>expect(panel.querySelectorAll('.manager-stage-card')).toHaveLength(8));
    expect(panel.querySelector('.manager-close-independent-state')?.textContent).toContain('尾盘资料缺失');
  });
  it('keeps failure visible even without Stage and does not fabricate cards',async()=>{
    mockPage(false,null,true);
    const summary=await screen.findByRole('region',{name:'经理工作台研究发现摘要'});
    await waitFor(()=>expect(summary.textContent).toContain('旧结果已清除'));
    expect(document.querySelectorAll('.manager-discovery-card')).toHaveLength(0);
  });
});
