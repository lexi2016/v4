# R3 证据摘要

## 现场 API 结果

2026-10-09 11:00 CST，本 Writer 对本机 `127.0.0.1:8873` 依次发出两次 GET，无并发；完整响应只在内存中用于提取状态与 SHA，未保存名单、行情或响应正文。两次均 HTTP 200：

- `date=20261009&selection_date=20261008&announcement_date=20261007&view=auto`：7,617,251 bytes，SHA-256 `8a1580c5fc68bd00ab2a0fea00e5b2a528af502fdef2ba95f34f6d072b3292c8`。`plan_product=NOT_MATERIALIZED`, `run_id=null`; US `daily_run=NOT_RUN`; announcements `NOT_RUN`，reviewed products `NOT_IMPORTED`; HK authority diagnostic `HK_UNIVERSE_V2_ARTIFACT_MISSING`。
- `date=20261009&selection_date=20261009&announcement_date=20261008&view=auto`：7,617,254 bytes，SHA-256 `acf24ed6bf70333dc7ac456f1d104f73e1d2a2768fb3693c7a3976d1398ac9dc`。同样无 plan/run，US daily mapping 未运行；公告未运行/未导入，HK V2 universe 缺失。

用户另报告 10:53 CST 的两次顺序 GET：超跌状态 `SCREEN_SECURITY_MASTER_READ_FAILED:StoreError`。本 Writer 的 11:00 精简投影只确认 `market_screen=CANNOT_CONFIRM`，因此 exact error 保留为用户现场报告，不能说由 11:00 projection 重新确认。机器投影见 `../evidence/live_get_projection_20261009.json`。

## 当前 API 与共享调度身份

2026-10-09 11:06 CST 的白名单身份读取见 `../evidence/runtime_identity.json`：

- `com.lexi.v35.api-only` PID `78617`，配置 root `/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app`，manifest SHA `16675f60…`，plist SHA `c88e4069…`。Issue32 三个保护文件 SHA 在 `current_vs_candidate.json`。
- 运行 API 的 `V4_MANAGER_PLAN_OWNER_BINDING_PATH` 是 C1 文件，SHA `f3b7cbfa…`，字段 `enabled=false`，app root 仍为 `manager-daily-chain-20261008-r2-api/app`。
- 共享 `com.lexi.v35.scheduler` PID `83677`，11:03 后当前 plist SHA `b9e9e836…`，scheduler root 已切到 `issue32-preselection-scheduler-mac-20261009-r1/app`；此前 R2 记载的 `20260928-manager-daily-plan-r2` root 仅为历史。
- 当前 scheduler binding SHA `c0fbff52…`，`enabled=true`、`plan_material_refresh_only=true`、`plan_material_refresh.enabled=true`、公告采集关闭。它绑定 `manager-us-mapping-daily-20261006-r2/app`，cycle SHA 与 plist pin 一致。其 plan canary 是 `hook_executed=false` 的历史手工回读凭据，不是 10/9 自动 dispatch 收据。
- 当前 scheduler 与 API owner binding SHA 不同，API binding app root 也不等于现役 API root。`run_manager_announcement_cycle.py` 到期后通过 `request_bound_plan_cycle(args.binding, plan_target)` 调用 8873；API 先对比 SHA，再校验 app root 与 enabled。静态配置/代码组合预测首个拒绝码 `PLAN_OWNER_BINDING_SHA_MISMATCH`。这是静态推断；本 Writer 未触发请求，也未读取 owner dispatch 状态文件，因此实际未触发还是触发后失败仍 `CANNOT_CONFIRM`。

## 输入与候选的区分

- R2 输入审计已确认 `com.lexi.v4.us-market-digest` 10/8、10/9 04:15 自然源采集成功；这与当前 workspace 的 US `daily_run=NOT_RUN` 是两层证据。
- 10/8 公告分析产品存在，但采集 `PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS`，外部身份 `DECLARED`，10/9 API 仍显示 `NOT_IMPORTED`/`NOT_RUN`。历史 `automation-3` TOML 当前缺失；是否启用和时区 `CANNOT_CONFIRM`。
- HK V2 universe missing 是 API 当前 membership 诊断，不代表可用 full-market/旧日期 fallback。HK child namespace 已存在 SHA `45da7914…`；原 updater 实际导入 `shared_data.hk_0_2` 与 `shared_data.store`，不导入 `hk_daily_supplement`。对应代码快照按来源分组。
- R1 `008649895054cb24f1d1c3df37e215d307615db3`、R2 `6a2fa48faf1da0a7d0d1715b3a4a40f55249b64c`，累计 Mac 候选 `e4b4dfa3a85608f074c0dae34138033dae7c1c3f`；独立 Reviewer 对冻结隔离候选 PASS，P0/P1 无，HK supplement reader behavior 有一个 P2 `CANNOT_CONFIRM`。更新后的共享 baseline `66bb05a2e12976775ccb997191ce943bae8cc9a5`。R1/R2 manager 源在当前 API 仍是 before，不能用候选 PASS 推导实际 manager 结果。

## 未确认项

- 当日具体 scheduler dispatch / owner receipt：`CANNOT_CONFIRM`。
- 两日期真实 plan 产品及逐股理由：`NOT_RUN`。
- 普通 auto 是否能回读同 run/SHA：`NOT_RUN`。
- 10:53 精确 oversold 错误在 11:00 响应里的再次确认：`CANNOT_CONFIRM`。
- Python 实际加载模块 identity、UI readback、自然时段结果、manager candidate deployment：`CANNOT_CONFIRM`。

`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。没有 POST、采集、计划生成、服务状态更改或 Git 操作。

## 包装校验

在 R3 根目录，Writer 执行 `python3 -m py_compile tools/validate_package.py` 与 `python3 tools/validate_package.py`。校验器对 33 条 manifest 逐条核对源与快照的字节数/SHA，确认 Issue32 三个保护文件 SHA，解析包装 JSON，并对 `package/` 和 `evidence/` 文本执行高置信凭证模式扫描。结果见 `../evidence/validation_receipt.json`；源码记录为 32 个可比对快照、1 个显式缺失路径、3 个 expected SHA 未设路径，当前校验 PASS、凭证命中 0。
