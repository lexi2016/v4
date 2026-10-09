# 经理每日自动化 R1→R2：Mac 累计候选接续

本机已完成固定 R1→R2 的隔离候选装配、真实完整前端构建及原输入任务身份核对。独立 Reviewer 已给出冻结范围 **PASS**：无 P0/P1，保留一项 HK consumer 行为覆盖 P2；`REVIEWED`、`TESTED` 及合成范围 `BEHAVIOR_VERIFIED` 通过，详见同包 `review/independent_receipt.json`。本交接不表示现场部署、10/8 补算或每日自动运行已完成。

## 固定基线与候选

- R1：`008649895054cb24f1d1c3df37e215d307615db3`；R2：`6a2fa48faf1da0a7d0d1715b3a4a40f55249b64c`。原交付共 230 件文件均完整下载并核对 Git blob/字节。
- 本机入口源码：`/Users/lexi/Desktop/学习/v4_app`。09:15 核对的现役 API 为 `manager-workbench-r1-mac-20261008-api-r2/app`，PID 34989；该身份是观察快照，不保证后续仍为现役。
- 候选根：`/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_AUTOMATION_R2_MAC_20261009/candidate/api`；完整前端为同目录 `candidate/web/apps/web`，测试装配为 `candidate/test`。
- API 11 条和 web 4 条 R1 生产前像均匹配，先应用 R1 再应用 R2；canonical web 的并行修改没有被覆盖。最终 `workspace.py` 为 `a6225ef5583a73c066a5c31400f84e237aaceb63abefcf199cfb8c9b8af7dcdc`，`catalystObservationPanel.ts` 为 `ffd5c8cbfdaba9eb7e277695114647ef037b88ae16269be5547d3eff0649d3a3`。
- R1 `hk_upstream` 的实际 consumer 是 API 内 `v3_shared_data/shared_data/hk_daily_supplement.py`，前像 `5528a6b4…` 精确匹配，固定后像为 `f71d6bb8bc0d55a0205d9734562c37d249654e3e39ccc85e18dd6398aa3c3862`。该映射不能用于覆盖另一根的 HK02 updater。

逐文件 SHA、原根、实际测试环境和失败分类见 `evidence/receipts/r2_candidate_minimum_verification.json`、`evidence/receipts/r2_api_web_cumulative_application.json` 与 `integration_audit/`。装配工具只用于本机精确根，不是通用部署器。现役服务、调度、公告自动化和业务数据未被本批更改。

## 本机验证范围

独立复验已回报 R2 auto/readback 4 项、exact date binding 2 项、R1 daily owner/catch-up 10 项、US owner 12 项、原完整父组件 5 项通过；完整候选 web typecheck/build 均退出 0。分组有不同范围，不将其相加宣称全套测试通过。

首次 exact-page 测试从 canonical cwd 运行，返回两项 `PLAN_AFTER_READ_CUTOFF` 失败；其导入根未绑定，不能作候选行为判定。改用候选 cwd 并捕获实际模块路径/SHA 后两项通过，首次失败保留。

HK supplement 的固定测试导入 `upstreams.v3_shared_data.shared_data.hk_daily_supplement`，测试装配缺此路径；实际 API consumer 使用 `v3_shared_data.shared_data.hk_daily_supplement`。文件与镜像 SHA 已核，整套 HK supplement 单测未完成，不将导入核对当行为验收。全量 pytest 未执行。

## 已查清的输入与未解决项

1. **US 原采集任务已确认。** `com.lexi.v4.us-market-digest` 的 10/8、10/9 04:15 自然 dispatch 均成功，source receipt/SHA 匹配；runner `16f7895…` 为指定修复版，data root 与 API reader 同根。目标日 mapping 和计划不能由此推定已生成。
2. **公告每日触发仍未确认。** 10/8 有 Reader/Reviewer、handoff、owner import，capture 保留 PARTIAL、外部身份保留 DECLARED；原 `automation-3` 是历史任务指针，当前 exact TOML 不存在，卡片渲染不能证明配置或启用。指定 state root 尚无 10/9 公告 run。不得新建替代 producer 来填此缺口。
3. **公告 worker 另绑旧根。** supervisor/cycle 与 R1 前像不一致，不能把 API 装配通过报告为 worker 已切换。需唯一发布 owner 按累计基线处理绑定及实际运行身份。
4. **HK child 有真实冲突。** manifest 期望新增的 `_namespace.py` 已存在；保留现状，未覆盖。成交量单位、完整六日尺度、历史资格及 PIT 缺口继续保留。
5. **共享发布仍须串行协调。** 同入口 Issue32 修复由原唯一 owner 管理。四条 R1 路径需归属：`infrastructure/_research_peripheral_store_parts/_namespace.py`、`infrastructure/scheduling/manager_announcement_supervisor.py`、`ops/render_manager_announcement_binding.py`、`ops/run_manager_announcement_cycle.py`；还需包含上述 API nested consumer。不得用本候选整树回退其 app.py、预选池或 Stage。

## 现场结果与下一步

09:22 三路并发只读 GET 中，10/8 auto 返回 500，日志为 `WorkspaceReadError` 容量分支；这不是历史日期单请求错误的复现。10/8 dynamic 与 10/9 auto 返回 200，但均为 `plan_product=NOT_MATERIALIZED`、`us_mapping_research.daily_run=NOT_RUN`。未发 POST、未补采、未改写 plan/run。具体元数据见 `coordination/live_get_baseline.json`；并发条件及错误日志见同目录说明。

由唯一 owner 接收独立 receipt 后，在其最新累计基线上合入必要文件并处理共享归属、实际 worker 绑定及回滚。随后沿原 owner 做真实 10/8 事后补算，保留真实执行时间和来源 cutoff，以 dynamic 验证事后产物、auto 验证当日/未来计划；完成 API 与重载普通页面同日期/run/SHA 读回。最后观察至少两个连续适用交易日的原自然 dispatch→输入→owner→计划→API/UI，以及旧日 exact 产物不变。

现场 INTEGRATED、DEPLOYED、API_VERIFIED、UI_VERIFIED、真实补算尚未验收；自然状态为 `NATURAL_SLOT_UNVERIFIED`。`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
