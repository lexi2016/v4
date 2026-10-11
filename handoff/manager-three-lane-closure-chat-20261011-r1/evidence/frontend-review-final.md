# 三路前端独立只读审查 — 最终结果

## 结论与范围

**前端限定范围审查通过；最终未发现尚未解决的 Critical / Important 阻塞项。该结论不构成 A/H/O/N 业务闭环通过，也不构成真实 Mac 8873 API/UI 或自然执行验收。**

Reviewer 独立审查了相对基线 `2152496bf288b696c5c7eb6e9e2abc08962ca33d` 的以下生产文件差异，以及两份新增测试和其合成 fixture：

- `apps/web/src/api/managerWorkspace.ts`
- `apps/web/src/manager-selection/dailyChannels.ts`
- `apps/web/src/manager-selection/catalystObservationPanel.ts`
- `apps/web/src/manager-selection/__tests__/threeLaneDaily20261011.spec.ts`
- `apps/web/src/manager-selection/__tests__/threeLanePanel20261011.spec.ts`

另独立复跑现有 `catalystObservationPanel.runtime.spec.ts` 中可执行的 9 项。相关后端投影和现有页面挂载代码仅作为合同及调用关系参照读取，没有扩大为后端全量审查。

Reviewer 没有修改 candidate、隔离测试源或工具链；发现的问题全部交由 root Writer 修复。Reviewer 仅在 `work/reviewer_frontend_tmp` 中创建探针、日志和本记录。

## Severity 分类与修复核验

| 编号 | 首次发现严重度 | 首次可复现问题 | 最终处理与独立核验 |
|---|---|---|---|
| F1 | Important / P2 | HK 校验只证明展示行属于 native 子集；原产物 61 行可被截到 50 行并把 candidate_count 改为 50 而获准。清空展示行并写 0、改名/改理由、改逐行 run/SHA 引用也未被完整绑定。 | 已修复。根据原 membership 核对完整有序允许子集，保留原 rank/order 和逐股理由、lane_evidence、SelectionStore 引用；空允许子集只能显示 null。完整 61 行继续通过；截断、改理由/引用、伪零均在真实 workspace validator 入口拒绝。合法会员排除子集与空子集的正例仍通过。 |
| F2 | Important / P2 | 原 Stage 缺 native execution/availability 时间，前端仍能接收含 61 行的 HISTORICAL_AS_OF workspace；原 source_evidence 的 backfill 标记也未全部执行后端同等否决。 | 已修复。历史 mode 下非空 Stage run 拒绝；backfill_run_id、selection_mode 与 4 个原 source_evidence markers 同后端拒绝。完整 synthetic workspace 的历史和 backfill 变异探针均报 WORKSPACE_DAILY_STAGE_REFERENCE_INVALID。 |
| F3 | Important / P2 | 明确请求 selection/announcement 日期后，服务响应若同时省略 date_bindings 与 daily_channels，真实 GET/POST 客户端函数仍可接收，无法确认被选择的来源日。 | 已修复。只要 expectedBindings 存在明确来源日，响应就必须确认 date_bindings；缺字段报 WORKSPACE_DAILY_DATE_BINDING_MISSING，存在但错日仍报 WORKSPACE_DAILY_DATE_BINDING_MISMATCH。无明确来源日且具有原 GET read_context 的兼容样本仍通过。 |

三类问题都在初始新增 15 项测试通过时由代码审查及独立变异探针发现，不能把初始 GREEN 等同于完整审查。

最终没有留下需要本前端补丁继续修复的 Critical / Important 项。没有另外提出无关风格改动。

## 最终实际执行结果

最终独立命令：

```bash
node /workspace/scratch/81f12368319d/work/web_toolchain/node_modules/vitest/vitest.mjs run \
  --config /workspace/scratch/81f12368319d/work/web_toolchain/vitest.config.mjs \
  src/manager-selection/__tests__/threeLaneDaily20261011.spec.ts \
  src/manager-selection/__tests__/threeLanePanel20261011.spec.ts \
  src/manager-selection/catalystObservationPanel.runtime.spec.ts \
  --testNamePattern='^(?!.*renders the actual Eastmoney owner workspace readback instead of reporting a network failure)'
```

工作目录：`/workspace/scratch/81f12368319d/work/web_test_app/apps/web`。

结果：**Vitest 4.1.10，3 个文件通过，43 passed / 1 skipped（44 总计），退出状态 0，耗时 4.90 秒。** 日志原始 Start at 为 `20:02:54`。新增两份文件 34 项通过，原 runtime 文件 9 项通过。

跳过项是明确缺失 Mac fixture 的 `renders the actual Eastmoney owner workspace readback instead of reporting a network failure`，其输入路径为 `/Users/lexi/Desktop/学习/agents调试/EASTMONEY_HK_ANN_20260929/integration/workspace_after.json`。此项没有执行，不算 PASS。

独立复跑过程中曾出现 41 passed / 2 failed / 1 skipped：新增测试的 legacy GET 正例没有原 GET 合同要求的 read_context，导致 WORKSPACE_OBJECT_INVALID。Writer 随后只补齐测试 helper 的 plan_context/read_context，生产 GET 门禁没有放宽；最后一次 43 passed 是对修正后的真实样本合同复跑。

`git diff --check` 对 3 个生产文件通过。Reviewer 核对的 3 个生产文件、2 个新增测试、1 个 synthetic fixture 在 candidate 与实际隔离测试源之间 SHA256 全部一致。Writer 的严格 TypeScript 校验不计作 Reviewer 独立执行结果。

## 行为核验

| 关注项 | 最终前端结果 |
|---|---|
| 未知与 0 | 合法 OVERSOLD READY_EMPTY 显示 0；ANNOUNCEMENT/HK 未核 lane 显示数量未知；缺 execution/availability 的 HK 空集仅 null。 |
| HK 61 行 | 正例保持 61 行且重绘后仍为 61；不按 50 行 UI alias 截断，也不按 rank 重排；原会员允许子集保持原顺序。 |
| 严格身份及来源 | run、manifest/receipt/artifact SHA、原 source_result、原 membership、逐股名称/理由/lane_evidence/SelectionStore 引用受绑定。 |
| 日期 URL 与重载 | explicit selection_date、announcement_date/publication_date 归一化后传给原 GET/POST；默认不把 legacy date 生造为公告默认日；view=dynamic 从 URL 恢复；公告日期变化重读 analysis 和 workspace，清除过期 alias。 |
| 竞态及旧结果 | 改来源日期使 bindings key 改变并清旧结果；旧请求的晚到响应被 sequence 丢弃；同日期、同口径、同来源绑定的重读才能保留明确标注的旧合格结果。 |
| 历史与现在回看 | 动态请求收到历史 mode 时真实 API 客户端拒绝 WORKSPACE_VIEW_MISMATCH。无 Stage 原可用时间的历史三路 rows 在完整 workspace 校验入口拒绝。 |
| natural / completion | HK 仍为 PARTIAL、generated_at=null、natural_run_verified=false；文案保留执行和可用时间未核实，未升为已自然执行或 READY_EMPTY。 |

独立探针直接导入 candidate 的真实 TypeScript 校验/API函数，使用 Node 与 jsdom；API transport 是明确构造的 synthetic Response。探针构造一个能先通过完整 validateManagerWorkspace 的合成 envelope 后，仅变异目标条件，避免只用局部 validator 错误推断整个入口。

`stage-boundary-final.log` 的历史变异中，直接单独调用无 workspace 参数的 renderer 仍可画出 61 行，这是探针刻意绕过 API admission 的显示结果；**同一变异已被真实完整 workspace validator 拒绝**。生产 panel 从已验证客户端函数取得响应，失败后清空结果。不能把那个单独 renderer 输出当成历史页面获准证据。

## 证据文件

- `work/reviewer_frontend_tmp/independent-final-green.log`：最终 43 passed / 1 skipped。
- `work/reviewer_frontend_tmp/independent-final-vitest.log`：中间 2 个 fixture 合同失败的原日志，保留未覆盖。
- `work/reviewer_frontend_tmp/stage-boundary-probes.mjs` 与 `stage-boundary-final.log`：完整 Stage、截断、改理由/引用、伪零、历史与 backfill 探针。
- `work/reviewer_frontend_tmp/api-binding-probes.mjs` 与 `api-binding-final.log`：真实客户端函数的显式来源日期及 mode 探针。
- `work/reviewer_frontend_tmp/final-source-sha.json`：基线/候选 SHA，及 candidate 与隔离测试源一致性。

## 最终生产文件 SHA256

| 文件 | 基线 SHA256 | 最终 SHA256 |
|---|---|---|
| managerWorkspace.ts | bbb01afba2c87e778310e70ca4d8d2a326655819ff920c7bc6b1ebd2a5f2fc8d | 82b99e20380bfa3b946232ef52fc22fa597fe4fe60d2f0cd5ebdf6ed8c4fbb44 |
| dailyChannels.ts | c4983a1bb3f23ea4ee3cfc598b805f2dc765a525b263156a4d7f6428767d24c4 | a82876249db0f6c77793e26314259dc06b2b94cec8f8227ae2a9711c1aa8c77d |
| catalystObservationPanel.ts | bff5c7765930651e933658b48bf11728f6f609b7a3b8576432a57123cfb83d50 | 7abc94c0e980ea170be5e9153287d132858c242f2467fc952e12ca709006536d |

## 未执行与结论限制

没有访问真实 Mac 的 8873 API、浏览器进程、原 owner 环境、真实保存产物或自然执行回执；没有把 fixture 的股票数量、run、SHA 当作真实业务产物。隔离应用使用已恢复的真实离线工具链；缺失原 API helper 按固定 Git 来源补齐，不能因此断言完整 Mac 构建、现役 loaded-module 身份或部署已通过。

前端已验证 dynamic/auto 的参数和 mode 合同；具体 server now、历史 cutoff、日历选择及事后数据入库时间由后端审查/实证负责，本审查没有独立证明真实时钟口径。

本报告允许给出**限定前端工程审查通过**，整体业务仍必须保持 **PARTIAL / 未完成**，直至 README 所要求的真实三路 owner 执行、保存、统一 API、8873 重载及自然回执分别完成。
