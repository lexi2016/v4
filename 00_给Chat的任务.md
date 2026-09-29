# 给 Chat 的任务：为 V4 经理工作台准备三项精确基线修复

请仅依据本 ZIP 内的活动发布源码与证据，为三项经理缺陷交付完整代码补丁、实施计划，以及可供本机接续的启用候选。**Chat 阶段离线工作**：不联网、不运行 HKEX 工具、不触碰本机活动发布/配置/服务。本机后续真实验收是单独阶段，必须在方案中写清。此 ZIP 本身不是部署授权。

## 固定基线与范围

- 活动 V4 API 源码根：`/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/20260928-manager-daily-plan-r2/app`（release `20260928-manager-daily-plan-r2`）。准确文件字节已复制到 `sources/active_api/`，SHA 在 `SOURCE_PINS.json`。
- 活动 V3.5 调度器源码根：`/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260928-manager-daily-plan-hook-r1/app`（release `20260928-manager-daily-plan-hook-r1`）。调度器源码在 `sources/active_scheduler/`。
- 活动绑定是 `config/manager-plan-binding-r2.json`。Python 入口是 `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python`。
- `sources/isolated_hkex_candidate/` 是隔离候选，不能作为活动源码前像。当前活动 `announcement_source.py` SHA 为 `029ad49dd506ab6ff78b204a0380c03f044085e32ac43ddfb88f8dd582b9f330`；候选 SHA 为 `e3b90c2c09b6f8c4a39bcfd8c8912e3476011a8faf59b94f4069ccaa81ae0d24`。最终审查材料中的 `4dd7abd79726aa6ab24b16bb05d1027feeec047ad7233631c7b4bd47af1827bc` 是 HKEX live-probe guard protocol SHA（`guard_protocol_sha256`），不是 `announcement_source.py` SHA。
- `tests/canonical_repo_different_baseline/` 是 canonical repo 当前工作树中的精选测试，可能有未提交更改；只能作为测试意图参考。`tests/active_release/` 才是活动发布树内的精选测试。请在每个补丁中固定所有实际前像 SHA，不要混淆两套基线。
- `workspace_20260929.raw.json` 是 2026-09-29 07:54:58（Asia/Shanghai）通过本地 API 得到的原始完整响应；`date_list_20260928.raw.json` 是 runtime identity 响应。`evidence/current_workspace_diagnostics.json` 是机器提取摘要，判断以原始 JSON 与对应 SHA 为准。

## 三个缺陷及目标

1. **经理计划早间输入变化后仍然陈旧。** 原计划 run `d4d9ef5eea98409aa5a64e442c812db2` 于 2026-09-29 01:17 左右生成，workspace API 在 07:54:58 返回 `plan_product.status=STALE_INPUTS_CHANGED`。当前绑定的计划资料刷新窗口是 16:00–23:00，状态 `PROPOSAL_ONLY`；正式 pre-open 计划仍在首个 09:30 Stage 窗口前 180 秒触发。请沿现有唯一 owner `ManagerResearchJobService.refresh_workspace_plan` 设计/实现早间对已验证输入变化的幂等刷新和可读回证据；同一 `input_identity` 不重复生产；保持正式 pre-open freeze 与每日既有触发所有权，不新增 producer、不改变 Stage/BUY。
2. **公告 owner 未启用，且缺少原 owner 从真实目录到非空正文再到消费者读回的完整验收。** 当前 binding 明确 `announcement_collection_enabled=false`、`plan_material_refresh_only=true`；API 返回 `NOT_RUN`、`latest_attempt=null`。已有 R3 与 09969 保存请求/owner responses/独立审查显示当时观测范围是有效空目录；最终审查为 `VALID_EMPTY_FOR_OBSERVED_SCOPE`，正向公告正文是 `CANNOT_CONFIRM`，正式部署没有执行。请按活动源码修复原 owner dispatch、原 store 持久化及现有 manager API/消费者投影接线；同时交付可采用的**公告调度启用 binding/config 候选**，但不要在 Chat 阶段应用或启用。
   - Chat 只离线分析、生成代码/测试/配置候选，不联网、不执行 probe。不要把历史同一输入、同一窗口的空查询重复一遍；若没有新证据，不重复请求。
   - `LOCAL_ACCEPTANCE.md` 必须单独写本机未来真实验收：选取一个新的、可核对且确有非空官方公告的 singleton issuer 与窗口，先冻结选择来源/目标日期/截止时间/请求范围；由**原 owner**只查该正式目录一次并保留未改写的请求、目录响应、原始公告正文和各自 SHA/时间/官方文档标识；证明同一正文进入原有 store，再由现有 API/消费者读回同一 document/body identity；独立 reviewer 核对全链路收据。若当时无法找到真实非空输入，应明确缺少哪一项样本/来源证据并标 `CANNOT_CONFIRM`，不得将空结果包装成正向通过，也不得无新信息反复尝试同一输入。这个样本缺口不等于永久禁用公告路径。
   - 只有完整链路及独立 reviewer 通过后，才按 `LOCAL_ACCEPTANCE.md` 将候选 binding 接到活动原 owner 日常 dispatch、启用每日公告调度，再验证调度读取的 binding、下一次原 owner 单例/日常 run、store/API 消费者 readback；回退步骤必须恢复当前 plan-only binding 与关闭公告调度，并保留失败收据。Chat 仅生成可采用候选和步骤，不在本轮部署/重载。
3. **US-to-HK 映射候选没有可接受关系。** API 显示 session `20260928`、捕获 `2026-09-28T20:15:05Z`、配置 33 个 US symbols 且 33/33 可用；两个上涨行业为“生物医药”“石油”，六个上涨 ticker 保留原始观察。78 条 relation audit 中 49 条为 `ISSUER_PUBLICATION_OUTSIDE_WINDOW`、29 条为 `ISSUER_ACQUISITION_TIME_MISSING_OR_INVALID`；接受 HK mapping 为 0，两个行业为 `NO_MANAGER_THEME_TAXONOMY`，六个 ticker 为 `NO_STRUCTURED_HK_US_RELATION`。请结合 `evidence/us_relation_representative_audit_rows.json`、对应原始存档 payload/receipt 和 `research_evidence.py` / `issuer_us_relations.py` 判断哪些是解析/字段投影故障、哪些是真缺少来源事实。仅在 issuer 与 theme 两侧关系都具备可追溯、两源 PIT 时间与引用时接受映射；保留 unmapped raw movers 和准确拒因。禁止猜行业、补造 US/HK 关系、伪造 `available_at`，也不要把 `mapping_eligible=true` 或输入 33/33 改写为映射覆盖成功。零接受映射可以是正确结果。

## 请交付的完整文件

- `runtime.patch`：相对活动 release 文件路径的完整 unified diff，覆盖经理早间刷新、公告原 owner dispatch/store/消费者接线、日常公告启用候选，以及 US relation 修复。标明精确前像 SHA 与每个文件目标 SHA。
- `tests.patch`：离线聚焦回归测试及必要 fixture，覆盖三项缺陷、同 identity 刷新幂等、正式 pre-open freeze、公告空目录与非空正文、原 store 持久化和消费者 readback、时间缺失/过窗、零映射及 raw mover 保留。fixture 只能表达其记录的事实，不能代替未来真实非空目录验收。
- `after/`：**完整且自包含的改后文件树**，给出每一个新增或修改文件的全部最终字节，不可只给 patch、片段或省略配置/测试/fixture。至少分清 `after/api/<活动 API 相对路径>/...`、`after/scheduler/<活动 scheduler 相对路径>/...`、`after/config/...`、`after/tests/...`、`after/fixtures/...`。其中必须有已接好原 owner/store/consumer 的源码和一份可采用的每日公告调度 enabled binding/config 候选；候选仅供通过本机验收后采用，本轮不应用。
- `SOURCE_PINS.json`：所有 `after/` 文件、测试/fixture 和 patch 的路径、before/after SHA；明确目标树、Python 命令、候选配置激活前置条件及不同基线。应用两个 patch 后，隔离副本必须逐字节等于对应 `after/` 文件。
- `REPAIR_PLAN.md`：每项根因/已确认事实/待证假设/最小改动/owner/依赖/回退方法/本机验收与调度启用门槛。
- `LOCAL_ACCEPTANCE.md`：分成 Chat 离线源码验收、本机未来原 owner 真实单例验收、独立 reviewer、通过后每日调度启用与自然时段确认、失败回退几个阶段。列出可直接执行的 Mac 命令，命令从活动源码和本机路径推导；真实单例步骤覆盖“新鲜非空官方目录 → 原始正文及 SHA → 原 owner → 原 store → 现有 API/消费者读回 → 独立验收”。明确同输入无新信息不重复空查询；如果缺少可核对的非空公告输入，写清需补的输入和 `CANNOT_CONFIRM`，不把它固化为永久禁用规则。
- `CANNOT_CONFIRM.md`：分开陈述源码/离线测试、真实目录与正文、store/API readback、UI、每日调度/自然时段各自能否确认；不能用本地 fixture 或配置候选冒充 live/natural acceptance。

## 边界与通过信号

- Chat 阶段只产源码级补丁、完整 `after/` 与方案；不改活动 release 或本仓库文件，不部署、不重载 API/调度器、不运行网络请求。启用配置只能作为候选写进 `after/`。本机未来验收是单独阶段；它按上述新鲜 singleton 样本进行有界、只读官方请求，并在授权的验收流程中验证原 owner/store/readback。不要重复历史同输入空查询，也不要把无样本解释成永久禁用网络验收。
- 不访问 Futu、不访问 Stage/BUY 输入、不下单、不改门禁；始终 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
- 不重跑旧的 pytdx 100/100 已完成工作；`evidence/manager/FINAL_RUNTIME_STATUS.json` 与独立 reviewer 收据已保留。Formal Stage 0/推荐结果仍未解决，不能写成已完成。
- 将 `HKEX_R3_original.zip` 与外层历史 tool 当作只读上下文；不得在 Chat 阶段运行其 probe 工具。未来本机 acceptance 使用新鲜、预先选定、具非空官方公告证据的单例，不对历史空输入盲目重试。
- 通过信号：三个缺陷均有活动基线精确补丁、聚焦测试、完整 `after/` 改后文件、before/after SHA、可执行本机验收、调度启用前置条件与回退步骤；HKEX 接线贯通原 owner→原 store→消费者；真实证据不足的阶段明确为 `CANNOT_CONFIRM`，没有把候选代码、空结果、fixture、Stage 通过或部署状态混为一谈。
