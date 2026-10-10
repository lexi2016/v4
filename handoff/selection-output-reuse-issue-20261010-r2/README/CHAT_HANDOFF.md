# Chat handoff：恢复真实、可追溯的选股输出

## 当前结论

上一轮 `manager-live-ui-api-20261010-r1` 的 UI/API 修复通过独立验收：2026-10-09 workspace plan 为 `CURRENT`，三路状态能显示并绑定请求日期。业务选股仍是 `FAIL`：0 条已验证候选、0 条正式建议、正式 Stage artifact `CANNOT_CONFIRM`。这两个结论必须分开。

最新请求是 plan/selection target `20261009`、公告 publication `2026-10-08`。当前 `ANNOUNCEMENT` consumer 没找到对应的 exact-pair consumed product，报 `ANNOUNCEMENT_EXACT_DATE_PRODUCT_NOT_CONSUMED`。历史 VERIFIED 产品是 target `20261008`、publication `2026-10-07`；target 和 publication 都不同，严禁把历史产品重绑到当前日期。历史 2026-10-08 公告阳性结果只证明公告文章决策，不证明当前三路或 Stage 成功。用户曾提到的 2026-09-30“三路独立成功”在本包和现有 E evidence 中未核，标 `CANNOT_CONFIRM`。

## 请 Chat 完成的工作

1. 先对当前运行 release 的真实 owner/input/consumer 链定位。包内 `source/current-live-release/` 保留了当前三路聚合与消费模块；`source/historical-r2-release/` 保留已验证旧公告导入链及其直接日期/来源校验依赖。以 `SOURCE_MANIFEST.json` 的源路径和 SHA 为准，不要把当前版和历史版同名文件混用。
2. ANNOUNCEMENT 沿 `read_manager_workspace` → `service.get_workspace` → `workspace._compute_workspace` → `workspace_daily_channels.build_daily_channels` → `workspace_announcements.read_analysis_consumption` 核验日期对、产品、handoff、review、owner receipt 和读回。必须比较当前 `(target_trade_date=20261009, publication_date=2026-10-08)` 与旧产品 `(20261008, 2026-10-07)`；禁止跨日重绑。
3. HK_CONNECT 沿 `workspace._compute_workspace` 的 `connect_selection.read_scope` → `domains.manager_research_evidence.read_universe_evidence` 核验精确目标日 V2 artifact、source owner binding、source date/market/SHA、acquired_at/available_at 截止和完整 membership。必要环境绑定为 `V4_MANAGER_UNIVERSE_ROOT`、`V4_MANAGER_UNIVERSE_OWNER_ROOT`、`V4_MANAGER_UNIVERSE_OWNER_SHA256`；不得把 prior-session capture 当目标日 authority。
4. OVERSOLD 沿 `workspace._compute_workspace` → `workspace_plan.read_rebound_screen` → `_read_hk02_panel_witness` / `_screen_panel_volume_evidence` / `rebound_native_evidence` 核验原 HK panel owner、精确 market_session、manifest/panel SHA、prior-60 与 previous-5 session coverage、native field/volume unit 和尺度证明。当前有 693 pending、695 gaps；receipt 未证明具体生产 owner，继续 `CANNOT_CONFIRM`。
5. 正式 Stage 从 `workspace._compute_workspace` 的 `service.observation_reader.read(date)` / `_reader_value(..., 'STAGE')` 和 `_stage_attempt` 追到原 Stage artifact consumer。验收固定池合同、目标日、输入来源/run/SHA、执行 receipt 与结果读回：A 股完整同日 `a_all_pool_rows`；HK 精确前一交易日 canonical D-1 Top100。当前没有已验证正式 Stage artifact。不要用全市场、generic list、别日名单替代。
6. 只修已证明断点，先复用包内已有 owner 和消费者；不放宽阈值、资格、来源、HK D-1 pool 或数据完整性门槛。真实输入合法地产生零结果时，给出完整覆盖与 owner 验证的逐项零原因，不伪造非空候选。

## 真实结果验收

包内 `tests/test_synthetic_package_contract.py` 只验证合成合同样例字段；它不是业务代码回归或真实结果。两份 `tests/upstream_reference/` 是可在 V4 checkout 执行的原定向测试。命令必须在本目录执行。第二条先把 `PROJECT_ROOT` 和 `V4_PYTHON` 替换为本机 V4 checkout 与已装项目依赖的 Python 解释器；它需要完整 V4 checkout 和项目依赖：

```sh
python3 -m unittest discover -s tests -p test_synthetic_package_contract.py -v

PROJECT_ROOT=/path/to/v4_app \
V4_PYTHON=/path/to/python-with-v4-project-dependencies \
PYTHONPATH="$PROJECT_ROOT" "$V4_PYTHON" -m pytest -q \
  "$PWD/tests/upstream_reference/test_manager_announcement_analysis.py" \
  "$PWD/tests/upstream_reference/test_manager_announcement_daily_flow.py"
```

当前真实历史复跑标为 `NOT_REPRODUCIBLE_FROM_PACKAGE`：完整真实 announcement catalog、reviewer 输出、article decisions 和原 owner 数据没有放进 ZIP。原 VERIFIED owner receipt 仅作历史证据；不能声称已重跑或重现 33 个证券结果。package-local synthetic tests 只检查 fixture 字段合同；本轮 Writer 已从包根运行该命令，4 个测试方法通过，但这不是业务代码或真实输出的行为验收，也不能提升该状态。

业务验收要贯穿精确日期请求、原 owner 输入及来源、run/product/artifact SHA、过滤/判定记录、API 与重载 UI。若声称自然执行，还需自然周期 scheduler/owner receipt。`HTTP 200`、测试、旧 receipt、manual refresh 或截图各自不能代替这条链。保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

## 证据边界

`CURRENT_CHAIN.json` 列出当前 E run、lane 状态和具体读回字段。独立 GET 的 body 为 16,410,445 bytes、SHA `5f56cc06...f53952`，没有持久化。另有一个 E 本机保存的 owner readback：16,410,447 bytes、SHA `6c0fe13667f5872a10cb83608bd29c1f4a7acdfa3c12e10af75cae2d7e40bdbc`，路径 `/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_LIVE_UI_API_REPAIR_MAC_20261010_R1/ui/owner-readback.json`；它与独立 GET body 是不同证据，本包不包含任一大 body。完整源/证据清单见 `SOURCE_MANIFEST.json`。真实 2026-09-30 三路成功声称仍 `CANNOT_CONFIRM`，与 2026-10-08 公告通道历史阳性及 2026-10-09 当前失败分列。

本包状态 `READY_FOR_REVIEW` 仅表示 Chat 问题包内容可审，不代表业务已修复、选股已产出、Stage 已恢复或自然运行通过。
