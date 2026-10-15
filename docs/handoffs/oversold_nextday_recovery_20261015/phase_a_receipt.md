# 超跌次日恢复：阶段 A 回执

日期：2026-10-15（Asia/Shanghai）  
阶段状态：STAGE_A_COMPLETE_WITH_REMEDIATION_ESCALATION  
总体选股结果：CANNOT_CONFIRM

## 真实 MANUAL run

- 通过既有 POST /api/v4/manager-workbench/runs 创建新 run：04fd6d63b3bc4a9e8fabe7a481c12d4c。
- 目标日 20261016，阶段 MANUAL，实际 cutoff 为 2026-10-15 23:42；没有伪造 16:30 自然时段。
- 进程仍为 PID 99039，运行 release 为 .../releases/us-hk-mapping-finish-20261015-r2/app。
- 实际绑定面板 assets/hk_0_2/panels/20261015-a562369dbc49/manifest.json（SHA-256 a562369dbc49f06761304c10ba7128d2289c7f0befd0d9264f7dbbc50404241c，17:20:02 发布）以及 20261015 的 689 行 security master（17:30:18 可用）。
- API 投影和冻结 snapshot 均显示 689 行 OVERSOLD 全部为 UNASSESSED，引擎原因是 676 行 UNIT_ADJUSTMENT_OR_CURRENCY_UNKNOWN、13 行 HK_HISTORY_FIELD_QUARANTINED。没有合格候选。运行安全标志保持 RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。

## 缺失交易日与实际 gap

冻结输入要求 20260722–20261015 共 61 个 HK securities session；当前 panel 只有 58 个，三个对所有 689 只证券均缺失的日期为 20261005、20261006、20261007。活动 release 的 HK 证券日历将这三天标为完整交易日，因此这是面板覆盖缺口，不是交易日历剔除。

冻结输入的窗口证据显示：647 只证券恰有 57/60 根 prior-high 历史 bar；另有 29 只在三个全局缺口之外还有逐证券缺口；13 只被历史字段隔离。三个日期是观察到的 panel 缺失，不是引擎输出的拒绝原因。676 行当前首先被单位、复权或币种未知阻断；补齐日期本身不足以把它们升级为候选。

## 可复用入口与边界

- 最短既有 owner 入口是 upstreams/v3_shared_data/shared_data/hk_daily_supplement.py 中的 capture_tdxpy_window_supplement。该入口可按窗口捕获 TDX 数据，但当前没有公开 API/CLI 调用入口。
- 20261015 没有可复用的 tdxpy61 manifest，也没有指向当前窗口的日补充 pointer；不能把旧 parent identity 的缓存当作当前补齐。
- 20261013 旧 TDX 全量产物曾有 568/690 READY，但绑定的是旧 panel/master identity。
- 20261014 三证券 canary 为 0/3 READY；两端点都遇到 HK_DAILY_SUPPLEMENT_OHLC_INVALID。不要放宽 OHLC 校验，也不要重用该失败产物。当前已有证据不足以确认同一请求的原始缓存可用。

建议的下一阶段仅在主控扩展 freeze 后执行：在当前权威共享链下，对 20261015 的精确 61-session 窗口做一个证券 canary；校验当前 panel/master identity、bar 日期与 OHLC，再决定是否允许全量捕获 689 只。若通过，再将本次 manifest 绑定到运行配置的 source_bindings.hk_panel.20261015.tdxpy_history 并创建新的 MANUAL run。需要的新增写入范围为该次 tdxpy61/runs/20261015/<run_id> 产物目录，以及配置文件 /Users/lexi/Library/Application Support/com.lexi.v4.local/config/manager-workbench-v9.json。任何 canary 失败都停止本阶段并保留原始缺口；不要回写旧 run。

即使 TDX 日期补齐通过，仍须单独验证其价格单位、复权、币种与历史字段隔离语义。现有证据不能确认该补采会解除 676 行主阻断或 13 行 quarantine，因此不能承诺候选恢复。

## 执行和验证

- 创建 run：curl -X POST http://127.0.0.1:8873/api/v4/manager-workbench/runs，JSON 为 {"target_date":"20261016","phase":"MANUAL","lanes":["OVERSOLD"]}。
- 读取 run 与结果：GET /api/v4/manager-workbench/runs/04fd6d63b3bc4a9e8fabe7a481c12d4c 和 GET /api/v4/manager-workbench/days/20261016/recommendations/OVERSOLD?phase=MANUAL&run_id=04fd6d63b3bc4a9e8fabe7a481c12d4c&offset=0&limit=200。
- 用服务 Python 只读检查 LOAD_INPUTS.json、冻结 snapshot、HK 日历以及现存 tdxpy61/runs manifest/raw capture；用 rg 定位既有 owner 函数和调用点。
- 未改业务源码、配置、服务、scheduler、panel、raw 数据或旧 run。未运行单元测试；本阶段验证是实际 owner run、API readback 和冻结输入检查。
- 后续全量 TDX 补采、配置绑定和超跌候选恢复均未执行，等待主控冻结阶段 B 的允许路径。独立 Reviewer 尚未验收。
