# R1 → R2 本机接续进度

目标：原经理工作台每日三路研究输入 → 当日计划 → 原普通页面。金融安全标志保持研究用途；本记录不是部署或自然验收证明。

## 已核对的事实

- 固定 R1 `008649895054cb24f1d1c3df37e215d307615db3` 与 R2 `6a2fa48faf1da0a7d0d1715b3a4a40f55249b64c` 的 230 件交付文件下载后逐字节和 Git blob 核验通过。
- 09:15 核对时现役 API 为 `manager-workbench-r1-mac-20261008-api-r2/app`，PID 34989；R1 API 11 条生产路径均匹配 before。原候选 web 四条生产路径均匹配 before，canonical web 存在并行变化，未覆盖。
- API 内 `v3_shared_data/shared_data/hk_daily_supplement.py` 是 R1 `hk_upstream` 的真正 reader consumer；前像 `5528a6b44bfb5b79265732b85beb1fb89860355b48a852da07264fb34231c79c` 匹配，可映射固定 R1 增量。独立 HK02 updater 使用另一模块，不能据此给 updater 复制文件。
- 原 US 四槽任务 `com.lexi.v4.us-market-digest` 已加载；10/8、10/9 04:15 LIVE dispatch 均 SUCCEEDED，来源回执 SHA 匹配。原 runner 为 `16f7895072a66b8a7e6ed0c792f74069101426cfa1194df3bd89e63d95f4d948`，data root 与 API reader 同根。来源已采集不等于目标日 mapping 已生成。
- 10/8 公告 Reader/Reviewer、handoff 和 owner import 已有绑定产物，但 capture 为 PARTIAL，外部身份为 DECLARED。原 06:30 自动化历史编号为 `automation-3`；当前 exact TOML 不存在，view 仅渲染卡片，没有配置/状态证据。指定 state root 未找到 10/9 公告 run。

## 当前阻断与发布边界

- HK child 中 R1 期望新增的 `_namespace.py` 已存在，须由该 owner 累计适配，不能覆盖。
- 公告 worker 绑定另一个 app root，supervisor/cycle 与 R1 前像不同；API 副本通过不能证明这个 worker 已适配。
- 唯一共享发布 owner 正在处理 Issue32；四条 R1 共享路径尚不属于现有发布策略。经理候选不得覆盖其 app.py、预选池或 Stage 修改。
- 超跌成交量单位、六日尺度和历史/PIT 资格没有因文件匹配而获得证明。

## 现场读取基线（2026-10-09 09:22:39 CST）

|请求|观察|
|---|---|
|10/8 selection=10/8、announcement=10/7、auto|HTTP 500，日志记录 WorkspaceReadError|
|相同绑定 dynamic|HTTP 200；计划 NOT_MATERIALIZED，US daily run NOT_RUN|
|10/9 selection=10/9、announcement=10/8、auto|HTTP 200；计划 NOT_MATERIALIZED，US daily run NOT_RUN|

这三个 GET 并行发起，500 日志止于 `workspace_read_control.py:201` 容量分支；因此它是并发基线中的失败，不能归因为过去日期读取本身有缺陷，也不能当普通页面单请求的复现。候选 R1 路由有对应异常到 503 的映射；现役实际加载及异常处理仍未核实。只保存状态元数据，没有把原始行情或研究名单写入此交接。未发 POST，未补采，未改业务 state。

## 状态

隔离累计候选已获独立 Reviewer 冻结范围 PASS：4 项独立 API 合同、2 项正确候选根的保存读回、R1 daily/catch-up 10 项、US owner 12 项、5 项完整父组件、完整 web typecheck/build 均通过。首次错误 cwd 的两项 FAIL 已保留，正确根复跑记录了实际 import 路径/SHA。REVIEWED、TESTED、合成范围 BEHAVIOR_VERIFIED 通过；HK reader 行为覆盖保持非阻断 P2/CANNOT_CONFIRM。现场 INTEGRATED、DEPLOYED、API_VERIFIED、UI_VERIFIED、真实 10/8 补算均未验收；NATURAL_VERIFIED 为 NATURAL_SLOT_UNVERIFIED。

证据入口：`intake/download_verification.json`、`integration_audit/source_root_map.json`、`integration_audit/r1_r2_production_preimage_audit.json`、`integration_audit/supplement_consumer_map.json`、`input_audit/r2-input-identity-audit.json`、`coordination/live_get_baseline.json`、`coordination/live_auto_500_log_excerpt.json`。
