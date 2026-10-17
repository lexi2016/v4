# 可直接复制给 Chat 的修复 Prompt

请在开始修改前阅读本仓库内的问题材料：

1. `docs/handoffs/us_hk_friday_close_20261017/packet/CHAT_ISSUE.md`：故障证据、日期/来源边界和验收范围。
2. `docs/handoffs/us_hk_friday_close_20261017/packet/source_context/README.md`：三个已加载运行版本的源码入口、摘录用途和目标源码匹配要求。
3. `docs/handoffs/us_hk_friday_close_20261017/packet/SOURCE_MANIFEST.json`：每个运行源码文件的完整文件 SHA-256、摘录行号/摘要 SHA-256，以及当前工作树对应文件是否逐字节相同。它没有验证目标 GitHub base；请先核对你正在修改的目标 checkout，再按证据适配，不要把摘录当补丁目标。
4. `docs/handoffs/us_hk_friday_close_20261017/packet/evidence/`：脱敏运行身份摘录、API 实际消费计数说明、合成契约用例、精简研究结果，以及 `real_relation_projection.json`。该投影是从冻结 mapping input 派生的 667 股票 / 1,003 关系身份与状态测试 fixture，保留来源、状态、use-scope、证据、缺口和 provenance；不含 quote 数据。它明确标记为非 owner、非完整 overlay，不能证明运行时实际加载了 canonical overlay。

## 目标与四个已确认断点

仅修复现有 V4 US 收盘后选择链路中的以下四个断点：

1. **US digest 没有把 release identity 传给 pinned dispatcher。** 当前 LaunchAgent 缺少 `V35_APP_ROOT`、`V35_RELEASE_ID`、`V35_RELEASE_MANIFEST_PATH`、`V35_RELEASE_MANIFEST_SHA256`；dispatcher 记录 `RELEASE_IDENTITY` 并在 workload 前失败。保留原 release-manifest 校验；让缺少 identity 的错误仍可诊断且 fail closed。
2. **调度日期、US session 日期和 HK 目标日期被混用。** 上海时间 2026-10-17 04:15 对应 US session `20261016`；HKEX 在 `20261019` 休市，目标应是下一 HK session `20261020`。将 `scheduled_date`、`trade_date`、`us_session_date`、`target_date`、source cutoff、run ID、manifest 和 SHA 保持为独立、可校验字段；禁止悄悄回退到 `20261015`。
3. **US close 完成后没有事件刷新已创建的目标选择草稿。** 现有 selector 在 US close 前已建立 `20261020` 草稿。owner artifact 成功提交后，接入现有 consumer 并以精确 artifact identity 幂等刷新该目标；单独记录 capture、selector-consumption、API/page 和 notification 结果。
4. **catalog 显示 667 只股票 / 1,003 条映射，不代表现有 API selector 实际消费了 1,003 条。** loaded API `announcement-continuation-api-20261017-r11c` 的 `NativeAdapters.us_mapping` 当前经过 dynamic bindings，审查证据显示其 relation projection 为 37 条：10 条 evidence-backed relation identities（对应 10 个 reviewed pairs）、5 条 reviewed seeds、22 条 `PROPOSED` / `PIT_UNCONFIRMED` registry relations；计数没有重复身份。请修复**现有 selector consumer 的输入接入**，并用 consumer 运行结果证明它读取完整冻结的 667/1,003 overlay；不能只修 catalog/API 展示。`evidence/real_relation_projection.json` 可用于验证 relation identities、字段保真、总数守恒和状态边界，但它是非 owner、非完整 overlay fixture，不可作为真实 runtime/API/UI/natural acceptance。完整 owner overlay 的运行时消费须在目标环境另行验证并取得 readback receipt；在这之前报告 `CANNOT_CONFIRM`。保留每条关系原有的 source、status、use-scope 与证据字段；不得把 757 条 `CLOSED_RESEARCH_SCOPE` 升格成 `REVIEWED`、PIT 安全或优先关系。`OPEN` 与 `CLOSED_EXCLUDED_SCOPE` 绝不可成为候选。

## 冻结范围

- 复用现有 producer、US digest、manager scheduler、selector、日期日历和映射 catalog；只修改能闭合上述四个断点的权威仓库源码及必要测试。
- 不增加 producer、数据底板、独立面板或平行 selector；不改变映射/研究状态含义、排序/rank、BUY gate、provider 权限或交易行为。
- 不回放或重新采集行情，不改 frozen capture、研究结果、原始输入或报告；after-close snapshot 仅是描述性报价观察，不是官方日线收盘价或 owner receipt。
- 两条已确认、非阻断的研究工具/展示限制需原样保留：Top 20 US 的关联 HK 列汇总所有关系状态，可能包含 `OPEN` 关联码；候选结论以正向且 `CLOSED_RESEARCH_SCOPE` 的行表为准。冻结 builder 的 `--verify` 参数仍会重建/覆盖输出；若确有必要复算，只能在临时副本上运行且不得调用 capture 脚本。原油相关价格上涨可形成航空等用户的成本压力，不等于利好方向。
- 不修改本机 release copy、LaunchAgent、计划任务或服务；不部署、不重启、不发送通知、不做真实交易。
- 保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

## 必须验证的行为

- release identity 已绑定时 dispatcher 通过既有 manifest 校验；缺失/错误时给出可定位 typed failure 且启动零 workload。
- 用 DST-aware fixture 证明 `20261017 04:15 HKT -> US session 20261016 -> HK target 20261020`，并跳过 HK 假日 `20261019`；各日期语义独立，不被一个 `business_date` 覆盖。
- selector 只接受精确 session/target 的 owner artifact 和 receipt，并校验 session、manifest、SHA、cutoff、run ID；输入缺失或 partial 时保留状态、覆盖率和错误，不 impute、不用 `20261015` fallback。
- 同一 exact artifact 重复到达时，刷新现有 `20261020` 草稿只产生一个 canonical consumer result。
- selector 的**实际消费输入**是 667 stock / 1,003 relation 冻结 overlay，relation identity/count 守恒；保留原始 source/status/use fields，`OPEN` / excluded 不进入候选，`CLOSED_RESEARCH_SCOPE` 不被改写为 review/PIT eligibility。测试不能只读 catalog 展示/API response。
- 使用 `evidence/real_relation_projection.json` 做 source-level consumer identity/count/field/status boundary test；将其结果标记为 fixture test。未经 canonical owner overlay 的实际消费者 readback，不得声称完整 overlay 已被 runtime/API/UI/natural run 消费，状态保留 `CANNOT_CONFIRM`。
- provider 失败保留原始错误和尝试 session；capture、consumer、API、重载页面、notification 各自报告，不得用任一层结果冒充另一层通过。
- 除 focused 自动化测试外，不声称 API/UI/notification/natural-slot 已验收，除非提供各自独立 receipt。

## 交付

提交前给出：

- 实际修改文件与逐项 diff，目标分支/base 和匹配的运行源码身份；说明哪些文件逐字节匹配、哪些经过目标版本适配。
- 复现命令、每个 focused test 的命令和结果；覆盖四个断点、部分数据、状态边界、幂等和 safety flags。
- 未解决的 `CANNOT_CONFIRM`，特别是没有真实 owner artifact 时仍无法证明的自然输入/运行结果。
- 精确 rollback 边界：仅回退本次允许源码/测试改动的方式及涉及文件；不要恢复、覆盖或删除他人的改动。
- 不要把 Writer 的测试称为独立审核；等待不同身份的只读 Reviewer 对实际 diff、冻结 PASS 范围及目标行为出具 `REVIEWED` / `BEHAVIOR_VERIFIED`。
