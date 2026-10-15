# 超跌次日恢复：阶段 B 候选交接

目标 20261016，价格日 20261015。现有 owner 与现行引擎已产出可评估候选；业务源码零修改，未切换配置/服务，未创建正式新 API run，独立 Reviewer PENDING。

- 单股 HK.00001：TDX owner READY，same-source proof 通过，实际 NOT_SELECTED（两个条件都未满足）。
- 全量 689 只：owner 567 READY、122 UNASSESSED（105 OHLC_INVALID、17 精确 61-session 不完整）。原隔离证券中有 2 只即使 owner READY 也没有被放行。
- canonical 与现役 release 的 inprocess 结果一致：565 已评估 = 21 SELECTED + 171 CONDITIONAL_WATCH + 373 NOT_SELECTED；124 未评估 = 111 单位/同源证据缺口 + 13 原字段隔离。
- 全部 565 同源比较证明通过。币种和绝对成交量单位仍为 null，未冒充已证明；仅依赖现有 engine 认可的固定 SDK、请求、证券、日历、原始响应和逐 bar 身份比较。未改门槛、校验或字段隔离。
- 原 16:30 run 保留；本次 TDX 数据真实 available_at=2026-10-15T15:59:22.803325+00:00，不能用于声称旧 16:30 自然运行已完成。

原 capsule/阶段 A 将 parquet SHA 误标为 manifest SHA。第一次 preflight 在任何 TDX 连接和 owner 产物写入前正确拒绝；错误收据保留为 phase_b_canary_capture.json。真实 manifest SHA 是 bf80f6869862c9363f132d8ca0b134e613d919bc0441b52550efcc417726fba0；parquet SHA 是 a562369dbc49f06761304c10ba7128d2289c7f0befd0d9264f7dbbc50404241c。已用真实身份新 attempt 完成 capture。

候选配置：/Users/lexi/Library/Application Support/com.lexi.v4.local/config/oversold-nextday-recovery-20261015-r1.json；SHA f4bc5c37fb08d57766bf3cd596f9fe4abdc6c32a327e09bc99c5f555822c7158。相对 v9 只新增 source_bindings.hk_panel.20261015.tdxpy_history，完整 pin 见 phase_b_candidate_config_receipt.json。源 manifest 为 runs/20261015/7484c9312ffe565ca8778264/manifest.json；SHA f60edafd683bc5a11df399f491116eb750a535865f54532771ed139ac30fdbc1。

21 只候选：00100、01347、01377、01384、01609、01672、01779、02249、02477、02513、02583、02590、02631、02697、02715、02858、03200、03277、03625、06651、06809（均 HK）。这仍是待独立验收/正式 API 落盘的研究名单。

## 独立只读复跑

无需再次请求 TDX，禁止重跑 capture。用实际服务 Python，执行：

```sh
MWB_CANDIDATE_SOURCE_ROOT='/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-mapping-finish-20261015-r2/app' \
'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B \
docs/handoffs/oversold_nextday_recovery_20261015/phase_b_validate.py --full --stdout-only \
--config '/Users/lexi/Library/Application Support/com.lexi.v4.local/config/oversold-nextday-recovery-20261015-r1.json'
```

去掉 MWB_CANDIDATE_SOURCE_ROOT 即验 canonical。验证脚本只读源数据；--stdout-only 不写 receipt。源/运行身份各 SHA、窗口父身份、错误分类和安全标志见 phase_b_receipt.json。unit tests NOT_RUN（无业务代码变化）；实际 owner canary/full 与实际消费者/engine 已运行，脚本 AST 通过，独立复跑待 Reviewer。

Reviewer PASS 后由主控沿已授权同目标，激活新候选配置并通过既有 POST /api/v4/manager-workbench/runs 创建 target_date=20261016、phase=MANUAL、lanes=[OVERSOLD] 新 run，核 API/页面，并同步必要证据到独立分支。不要部署 canonical 旧 US consumer 文件：本次只需配置绑定；两份消费者的超跌结果已经一致。

RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。

后续激活约束（本阶段未执行）：保留 v9；只激活本次单一 JSON binding 变化，不 wholecopy canonical 源码。切换前 fresh CAS 核验当前运行身份、v9 与候选 SHA，并获取现有控制锁；若使用 launchd 重载，确认旧 PID 已退出、label 已消失并 settle 2 秒后才 bootstrap，避免先前 bootstrap 5。须独立 Reviewer PASS 后在同一授权链继续。
