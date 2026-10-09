# V4 Stage 当前研究恢复实施计划

> Agentic workers: use superpowers systematic-debugging, TDD and verification-before-completion. 用户已明确授权直接编码；本轮不以设计审批或API拆分阻断。

**Goal:** 显式当前HK研究输入经原分钟行情和原四路算法产出可读结果，并修复A昨收透传、同run证据与页面。

**Architecture:** 沿既有runner、collector、builder、SelectionStore、consumer与Vue做最小增量。默认STRICT不变，研究角色单独标记；研究来源资料不提供行情/PIT或港股通资格。

**Tech Stack:** Python / 原19字段RawStore与SelectionStore / Vue 3.

**Spec:** 本轮用户2026-10-09完整请求，0fc3e8304e11700230517616ded0c86f83a4b257与其中SOURCE_MAP为代码基线。

## Global Constraints

- RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.
- 原排序、权重、Top10、公式SHA不变；216完整A输入不按200行UI截断。
- 不建producer、不另建权威数据底板、不改Stage8算法/BUY/Vibe8910。
- 四个Mac输入仅用户给定SHA和路径；未读到原数据，测试用明确合成夹具。
- actual Stage、actual API与dirty canonical分别处理。历史依赖不是现役证明。

## Tasks

1. HK研究接线（lane_hk）: runner/configuration/hk_input_validation/selection_input_validation/hk_candidate_authority/hk_minute/registry/node_entry/run_stage_center_tick。构造HK_CURRENT_DAY_RESEARCH binding，source_evidence中research_source=<canonical JSON>，严格SHA和日期、代码全集准入。
2. A字段（lane_a）: 在实际21870字节registry的竞价映射补prev_close_price；验证既有minute bridge到qmt.lastClose。同股真实生产转换链RED→GREEN，缺值null/真实0保持。
3. 市场隔离与证据（lane_core）: slot_execution消除研究D1强绑定、旧LIVE刷新；A builder失败不阻断HK，已发布结果不在异常receipt中丢失；runner_receipts以真实kind/SHA绑输入与selection trio。记录本轮候选文件身份与研究投影诊断，保留来源不一致拒绝。
4. API/Vue（lane_api）: 已由SelectionStore验证的CANNOT_CONFIRM+rows仍显示研究结果；显式日期/阶段/市场/run/SHA校验；行情覆盖、研究限制、执行证据独立展示；手动不能NATURAL。
5. 集成：合并非重叠差异，运行四lane测试与实际store往返、独立审查。提供after、实际before→after patch、R1→R2 delta、全部SHA、隔离canary落地脚本与固定远端commit。

## Review Focus

- HK缺历史资格时显式研究能走完整流程，默认STRICT仍拒绝。
- 15:38证券资料不覆盖分钟价格，不把午后报价伪装09:35。
- 四文件/候选漂移、日期/市场/run串接被拒绝，来源缺口保留。
- A研究witness损坏只阻断A的受影响计算，HK仍可落盘，已计算结果仍可读。
- 手动回看/有rows不会自动升级为自然、正式资格或交易授权。

## 完成状态

五项任务均已完成候选实现和本机定向验证。最终 SOURCE_MAP 包含 21 项，Stage 148、API 82、Vue 45 全部通过；最终独立 695 合成全链使用原 owner 历史 tick 和仅传 selection_root 的现有 API consumer 构造方式。完整结果与独立审查见 EVIDENCE.md。Mac 当前字节、真实数据、既有发布链、现场 API/UI 与自然时段验收保持 NOT_RUN；不能用本地测试代替。
