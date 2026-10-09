# R3 输入与日期合同

## 1. 范围与结论

本文记录固定仓库提交 `b98d85c95d19780e2900dce7de9372328e67acf6` 的 R1/R2 累计代码及本次 R3 候选中，已经通过源码核对和合成测试验证的输入、日期与回读合同。本文编写期间只读取已有代码和日志，没有新增测试执行或任何 live 操作。

核心合同是：真实 owner 新保存前必须至少有一个经原研究通道验证的合法输入；完整评估后的合法零结果可以保存，全通道均未齐备不能造出空计划、run 或 attempt。保存后的回读同时核对日期、原 run、产品 SHA、输入身份和 owner 证据。10/8 的事后计划用 `dynamic` 核对，普通 `auto` 保留历史资格规则；10/9 当日的普通 `auto` 可以核对当日已保存的同一计划。

本次生产改动限于 [workspace.py](../after/api/v4/manager_research/workspace.py) 的 `_plan_input_failure_reasons` 和 `refresh_workspace_plan` 保存前输入门。真实入口的上下文与诊断透传由 R3 对应 router、autorun 和 cycle 改动承接。低级历史保存与历史读回规则保留。

所有日期判断以代码中的 `Asia/Hong_Kong` 为业务日期基准。下文“当日”“过去”均相对于实际请求的香港日期，不能通过把时钟回填为目标日改变事后执行身份。

## 2. 三个日期与页面/API 名称转换

页面 URL 与 workspace API 对 `date` 的含义不同。R2 页面继续用 URL 的 `date` 表示原 Stage 来源日；计划日保存在页面 URL 的 `plan_date`。向 workspace API 发请求时，计划日映射为 API 的 `date`。

| 业务含义 | 页面 URL / 前端绑定 | Workspace API 参数 | 后端字段与默认值 |
| --- | --- | --- | --- |
| 计划目标日 | `plan_date` | 必填 `date=YYYYMMDD` | owner 的 `target_trade_date`；`date_bindings.plan_date`；`plan_context.plan_trade_date` |
| 来源/选股日 | `selection_date` | 可选 `selection_date=YYYYMMDD` | `date_bindings.selection_date`；省略时默认等于计划目标日 |
| 公告发布日期 | `announcement_date` | 可选 `announcement_date`，接受 `YYYYMMDD` 或 `YYYY-MM-DD` | `date_bindings.announcement_date` 统一为八位日期；省略时由 `previous_hk_session(plan_date)` 决定 |

这些是同一业务日期在页面、API 和产品中的名称对应关系。不能把页面 `plan_date` 原样当成 workspace API 的计划参数，也不能把页面原 Stage `date` 误传为计划日。router 实际声明的日期参数是 `date`、`selection_date` 和 `announcement_date`。

公告显式日期在新计算上下文中可表示为 `plan_context.announcement_publication_date=YYYY-MM-DD`。完整日期绑定命中保存上下文时会沿用原上下文；如果原保存来自默认公告日，该上下文可以没有这个显式字段。R2 exact-page 测试专门保留了这一断言。判断完整页面身份应比较 `date_bindings`，不能仅凭该可选字段是否存在判断不一致。

例如，R2 页面集成用例给定：

```text
页面 URL：date=20261007&plan_date=20261008&selection_date=20261006&announcement_date=20261007
生成 API：POST /api/v4/manager/research/workspace/refresh?date=20261008&selection_date=20261006&announcement_date=20261007
回读 API：GET /api/v4/manager/research/workspace?date=20261008&view=auto&selection_date=20261006&announcement_date=20261007
```

三个 workspace 日期必须保留，原 Stage 来源日仍是 `20261007`。以上为已核对的请求形状说明，本次没有执行这些 live 请求。

源码依据：候选 `apps/api/v35_api/manager_research_router.py` 的 `_date`、`_announcement_date`、`read_manager_workspace`、`refresh_manager_workspace`，以及 `workspace.get_workspace`。前端依据为固定提交下 R2 `after/web/apps/web/src/manager-selection/catalystObservationPanel.ts` 的 `mountCatalystObservations`/`load`，以及 R2 `after/tests/apps/web/src/views/ManagerSelectionView.dailyIntegration.spec.ts` 的原 POST→GET 三日期断言；本文只引用这些前端源码，未声称重新执行前端或 Mac UI 测试。

## 3. 10/8 事后计划：dynamic 与 auto 分别证明什么

实际执行日为香港 2026-10-09、计划目标为 `20261008` 时，原手动 refresh route 使用实际时间，并由服务端设置 `execution_context.timing=RETROSPECTIVE`。测试中的 `research_cutoff` 是 `2026-10-09T10:00:00+08:00`，没有伪装为 10/8 盘前时间。

对这个事后保存的计划，用相同三日期的显式 `view=dynamic` 回读。测试要求保存与回读的 run、product SHA、input identity、日期绑定、逐股理由及证据引用一致，并验证 GET 没有改变产品或 attempt 文件。

过去日期的普通 `auto` 进入原 `workspace_history.read_history`。因此有两种明确结果：

1. 只有事后保存、没有原合格历史计划：`auto` 保持 `consumed=false`、`run_id=null`，原因是 `HISTORY_QUALIFIED_SAVED_PLAN_MISSING`。事后 dynamic 成功不能使它变成盘前历史。
2. 原来存在合格盘前计划，后来又保存事后计划：`dynamic` 回读后来的事后 run，`auto` 继续回读原合格历史 run。原历史 product SHA、input identity、attempt、cutoff 与产品字节不变。

第二个测试通过原低级 scheduled owner 真正写入临时目录中的合格历史产品，没有重新封装成功 DTO、覆盖历史产品或删状态来达成断言。29 项原历史合同回归同时保留了跨日期拒绝、cutoff/PIT、源身份改变、原 scheduled attempt 和历史资格要求。

验证来源：[test_manager_r3_dates_inputs.py](../tests/test_manager_r3_dates_inputs.py) 的 `test_retrospective_1008_dynamic_reads_saved_identity_without_changing_auto_history`、`test_retrospective_latest_preserves_1008_qualified_auto_history`，及 [test_manager_history_contract_20261008.py](../tests/test_manager_history_contract_20261008.py)。

## 4. 10/9 当日 auto 与 R2 exact-page query 合同

API 的 GET 默认 `view=auto`。目标日为实际香港当日时，该路径可回读当前保存计划，不进入过去日期历史分支。R3 使用 `date=20261009`、`selection_date=20261009`、`announcement_date=20261008`，省略 `view`，验证普通页面请求与原保存一致。

R2 的 `_saved_plan_context_for_bindings` 只在完整三日期与已验证保存产品一致时复用原 `plan_context`。它返回原 cutoff，上层仍调用原 owner readers 重新计算并由 `_readback_plan` 比较输入和语义身份。请求几秒后的实际墙钟变化不会独自使同一页面失去原 cutoff；真实源变化仍会被识别。

通过标准包括：

- `plan_product.status=CURRENT`、`consumed=true`，保存与 GET 的 `run_id`、`sha256`、顶层 `input_identity` 相同。
- `run_readback.status=VERIFIED`，绑定原 run、产品 SHA、输入身份、正确 owner 和同 run 的封存 terminal attempt；回读时间不早于生成时间。
- `date_bindings` 完整相同，原 `plan_context` 与 cutoff 相同；逐股理由对应同目标日、公告日、证据 run、source manifest SHA、原公告 product SHA 与 `source_refs`。
- `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`；`natural_run_verified=false` 不能被合成运行升级。

只改选股日或公告日，不能继续消费另一查询的保存结果。原 R2 测试要求 `STALE_INPUTS_CHANGED`；真正 source catalog run 变化时也保持 stale，并保留被拒绝的旧 plan run/SHA 供核对。

输入门使旧测试必须先建立合法输入。两个 R2 exact-page fixture 现在经原 import 导入真实合成 `NOT_SELECTED` 公告，保留原日期、cutoff、run 和 SHA 断言。随后模拟新的 source catalog run 时，额外要求试图覆盖 immutable 公告产品的 import 返回 409，旧产品字节不变，再验证原计划 stale。没有弱化源变化检查。

原 `include_saved=False` owner 预览仍从本次真实请求的 cutoff 计算，不消费保存 cutoff，也不生成产品。证据为 [test_manager_workspace_exact_page_binding_20261008.py](../tests/test_manager_workspace_exact_page_binding_20261008.py) 的两个测试，以及 R3 `test_current_1009_default_auto_reads_same_saved_run_sha_inputs_and_stock_reason`。

## 5. 合法输入、独立通道与合法空结果

输入门消费原通道已验证的投影，不重新拥有采集、mapping、股票筛选或公告评估规则。

| 原通道结果 | R3 新保存行为 | 候选数/诊断含义 |
| --- | --- | --- |
| 全通道缺源、尚未运行、只采集未导入/评估，且无合法 US daily | `CANNOT_CONFIRM`；不创建计划产品、run 或 attempt | 未知保持未知，不能填 0 |
| 公告已导入但 reader gap、未评估或缺少 decisions，且无其他合法通道 | 不允许据此保存成功空计划 | 保留 `PARTIAL`、`ANNOUNCEMENT_SELECTION_NOT_ASSESSED` 与 pending 诊断 |
| 至少一个原通道合法，其他通道缺失 | 保存已验证通道的结果，保留其他通道缺口 | 不清空已验证股票及逐股理由；整体可保持 PARTIAL |
| 原通道完整评估且明确零入选 | 允许保存可追溯空结果 | 对该已评估通道允许合法 0；不把其他未知通道也改为 0 |

日常研究通道的准入先要求目标日相同、`input_identity` 为 64 位小写十六进制；`READY`/`READY_EMPTY` 可消费。原通道为 `PARTIAL` 时，如果仍有原 owner 已验证的同目标日行，且行带 `reason` 和 `source_refs`，这些独立合法行也可消费。此判断依赖原 `workspace_daily_channels` 和 reader 的验证结果，不接受来自请求 body 的股票或原因列表。

真实合成公告 `NOT_SELECTED` 正向测试核对了原公告产品、owner import receipt、证据 run、`not_selected_stock_count=1`、原 article decision 和原因。通道明确 `READY_EMPTY`、candidate/pending 均为 0，计划可以保存并由普通 auto 同身份读回。若其他通道仍有缺口，整体 attempt 允许保留既有 PARTIAL 语义；“合法空结果”不等于强制把整体状态改为 SUCCEEDED_EMPTY。

全无合法输入时的返回形状为：

```json
{
  "status": "CANNOT_CONFIRM",
  "reason": "WORKSPACE_PLAN_INPUTS_NOT_READY",
  "failure_reasons": ["WORKSPACE_PLAN_INPUTS_NOT_READY", "原通道的具体原因"],
  "workspace_plan_attempt": null,
  "plan_product": {
    "status": "CANNOT_CONFIRM",
    "consumed": false,
    "run_id": null,
    "sha256": null,
    "generated_at": null,
    "original_owner": "ManagerResearchJobService.refresh_workspace_plan"
  }
}
```

这个 `plan_product` 对象是未保存的诊断描述。输入检查发生在首次 run/attempt 写入前。测试比较临时状态中的研究文件与产品内容，允许事务层创建 mutex 文件，但不把 mutex 当作业务产物。已有合法保存后输入变为不可用，新请求返回诊断，原产品和同 run attempt 保留不变。

## 6. US capture 与每日 mapping 必须分开核对

`us_market_attention.status=READY` 只能证明 source reader 接受了采集产物。daily mapping 尚为 `NOT_RUN` 时，这个 source 状态不能单独授权计划保存。

US 合法准入还要求 `us_mapping_research.daily_run` 的目标日一致、状态为 `COMPLETED` 或 `VALID_EMPTY`，且 `owner_chain.us_mapping_daily_plan_reference.status=CONSUMED`。daily run 与消费引用的 run 和 artifact SHA 必须一致；run 是合法 32 位十六进制，input identity 与 artifact SHA 是合法 64 位十六进制。

新增 US 双分支测试使用真实 `ResearchPeripheralStore`、`ResearchPeripheralUsMarketReader`、原 reviewed seed/registry 摘要校验和原 `ManagerResearchJobService.refresh_us_mapping_research`。仅源 payload、registry/seed 和时钟来自临时合成 fixture：

- 合法采集但未调用 daily owner：source READY、daily NOT_RUN、计划 CANNOT_CONFIRM，无新计划。
- 原 daily owner 真实生成 VALID_EMPTY：source、daily run、artifact SHA、input identity 与计划引用一致，计划可保存，普通 auto 回读同 run/SHA/input。

测试还要求 workspace POST/GET 不启动公告采集、催化采集或第二次 US mapping 生产，并核对源文件未变化。US reader 抛 RuntimeError/ImportError 的独立测试证明：US 缺口不会抹掉已验证公告股票、原因和证据。

## 7. 实际入口上下文与低级历史兼容边界

`workspace.refresh_workspace_plan` 对显式 `execution_context` 执行保存前输入门。实际新写入入口必须由服务端传入真实 context：

| 入口 | 新写入时的 context |
| --- | --- |
| `POST /workspace/refresh` | MANUAL；过去目标为 RETROSPECTIVE，其他为 UNCLASSIFIED；实际服务器时间、服务器 trigger_id；natural=false |
| scheduled preopen | SCHEDULED / ON_TIME，受原 opening deadline 限制 |
| scheduled morning | 传递已准入 context；legacy 调用没有 context 时由原 wrapper 补 SCHEDULED / ON_TIME |
| same-day catchup | SCHEDULED / LATE_CATCHUP，绑定原 scheduled slot 与 trigger_id |
| 原材料变化/晚间计划生成路径 | 原 MANUAL_REFRESH owner 配合服务端 SCHEDULED / ON_TIME context |

源码依据为候选 `apps/api/v35_api/manager_research_router.py`、`v4/manager_research/workspace_plan_autorun.py` 和 `ops/run_manager_announcement_cycle.py`。已保存计划的无新增写入复用仍受原产品与 owner readback 校验约束。

`owner_plan_readback` 对约定的 CANNOT_CONFIRM 输入诊断先验证目标日、非消费状态、空 run/SHA、无 attempt 和非空原因列表，再保留诊断；它不会强行索取或制造成功 run。router 同样在持久化成功检查之前透传合法输入诊断。cycle 的输入未就绪结果不应被当作自然成功；对应分类是 `INPUT_NOT_READY`，上层保留缺口。

context-free 的直接低级 `service.refresh_workspace_plan` 为既有历史 fixture 和低级兼容接口保留原行为，包括 PARTIAL 保存。这是明确的兼容边界，**不是生产调用绕过建议，也不是授权边界**。新增实际调用路径应传递真实服务端 context 并经原 owner；不能以省略 context 规避合法输入要求，不能伪造 scheduled 时间或 natural 验证标志。对只需要看输入的诊断使用原只读/`include_saved=False` 路径。

两个原 R1 explicit-context 测试现在通过真实合法 `NOT_SELECTED` import 建立前提，冻结实际 import/owner 时钟后继续验证 late catchup 与 retrospective 的原时间/上下文断言。其余低级历史 fixture 没有被改成假成功。

## 8. 已有测试证据与保留失败

本节仅汇总已经保存的执行证据，没有为本文扩展执行。

| 证据 | 已记录结果 | 证明范围 |
| --- | --- | --- |
| [date_inputs_red_03.log](../evidence/date_inputs_red_03.log) | 4 failed / 6 passed | 生产门修改前，缺输入和未评估场景没有返回 CANNOT_CONFIRM，正确出现 RED |
| [date_inputs_final_focused_py314.log](../evidence/date_inputs_final_focused_py314.log) | native CPython 3.14.8；69 passed，1 warning，4.36s | 新 R3 日期/输入 15 + R2 exact-page 2 + R1 owner 23 + 原 history 29 |
| [date_inputs_us_sources_py314_02.log](../evidence/date_inputs_us_sources_py314_02.log) | 2 passed，13 deselected，1 warning，0.47s | 真实 US capture-only 反向与 daily VALID_EMPTY 正向；已包含在上面的 69 项内，不能重复相加 |
| [date_inputs_final_py314.log](../evidence/date_inputs_final_py314.log) | 78 passed / 1 failed，1 warning | 另一次加入完整公告 parity 文件的相邻检查 |
| [date_inputs_parity_baseline_py314.log](../evidence/date_inputs_parity_baseline_py314.log) | untouched baseline 同一例失败 | 确认下述相邻差异不是由 R3 输入门引入 |

保留的相邻失败是 `test_manager_announcement_parity_20261008.py::test_missing_original_archive_is_not_empty_connect_selection`：断言 `selection_diagnostics.status == READY`，实际为 PARTIAL。baseline 与 candidate 在同一 native 3.14 环境同样失败。该测试直接调用 `get_workspace(..., include_saved=False)`，未进入新增保存门。本次没有修改原 parity fixture 或生产 selection 来掩盖它，也未把它标记为通过或 xfail；它应作为基线已存在的相邻兼容问题单列。

唯一 warning 为 Starlette TestClient 对 httpx 的弃用提示。最初 US 测试因缺少精确 `interprocess_lock` 原依赖而失败的日志，以及一条组合命令误指不存在测试文件而没有运行测试的日志均保留；依赖随后由固定提交的原文件补齐。这些环境/命令结果没有计入通过数。

新测试只注入合成源、时钟和临时存储目录，使用原 import、mapping owner、workspace owner、store 和 route；不以 mock 成功 DTO 代替真实保存/读取。新增和修改源码来源分别为固定提交下 R2 `after/api/v4/manager_research/workspace.py`、R2 `after/tests/tests/test_manager_workspace_exact_page_binding_20261008.py`、R1 `after/tests/tests/test_manager_workspace_owner_20261008.py`，以及本次新增 `test_manager_r3_dates_inputs.py`。

## 9. Live 验收状态

| 层级 | 本次状态 |
| --- | --- |
| 真实 Mac 路径、进程和 runtime identity | NOT_RUN |
| live source capture、原公告/US 输入真实性与可用性 | NOT_RUN |
| 真实 Mac owner 生成 10/8 事后或 10/9 当日计划 | NOT_RUN |
| live store、HTTP、普通页面同 run/SHA/input 核验 | NOT_RUN |
| Mac 浏览器/UI exact-page 请求与读回 | NOT_RUN |
| 原自然调度下一次运行及自然恢复证据 | NOT_RUN |
| 部署、真实业务状态写入、采集和交易相关动作 | NOT_RUN |

合成测试只能支持候选实现的合同结论，不能证明上述 live 层已经恢复。本文没有执行或建议扩大 Stage、BUY、Issue32 的改动范围。
