# V4 组装与验收报告（v4_app）

- **日期**：2026-09-11
- **交付物**：`/Users/lexi/Desktop/学习/v4_app/`（独立目录 + 独立 git 仓库，4 个提交）
- **性质**：组装 + 集成修复 + 本地运行验收的**候选工作副本**。不是部署，不是放行；未触碰 v3.5、未触碰任何 release、未碰 launchd、未碰交易相关语义。
- **来源底座**：当前正在运行的 release `20260910-manager-page-restore-api-v8` 的 `app/` 源码（2026-09-10T05:15Z，只读复制；即"之前已有 v4"的最新连贯形态，含 `v4/manager_research` 后端、manager 路由、`stage_center`、预构建前端 dist）。

## 一、git 历史（v4_app 仓库）

| commit | 内容 |
|---|---|
| `0b11d5f` | snapshot: assemble v4_app from release 20260910-manager-page-restore-api-v8（630 文件全量落库，含此前不在 git 的关键合同/组件） |
| `20956fc` | refactor(infra): unify trading-safety guards into one shared superset（4 份分叉安全过滤 → 1 份共享实现 + 跨存储一致性测试） |
| `36c27a0` | test(config): tolerate starlette 1.6 TestClient(httpx) deprecation only（单类告警放宽，其余保持 -W error） |
| `1a681e2` | chore: ignore artifacts/ evidence dir |

## 二、如何运行（沙箱，端口 8899）

沙箱启动脚本（幂等，已被本次验收实际使用）：`v4_app/.runtime/serve-v4-sandbox.sh`

- 解释器：**既有** `runtime/venvs/v3.5-mac/bin/python`（Python 3.14.6；与生产 api-only 服务一致的环境来源；已确认含 fastapi/uvicorn/pytest/httpx2/starlette/pyarrow/pandas/pytdx 等全部依赖。**本次验收没有安装任何新依赖**）
- 数据根：
  - `V35_DATA_ROOT` = 既有 `state/data`（页面只读 GET）
  - `V35_STAGE_CENTER_SELECTION_ROOT` = 既有 `com.lexi.stage-center.local/state/selection`
  - `V4_MANAGER_RESEARCH_STATE_ROOT` = **v4_app/.runtime/manager_auto_research（只读拷贝，7.8MB）**——manager 页面若触发 ensure 写入，只会写进沙箱副本
- 安全旗：`RESEARCH_ONLY=1`，`production_allowed/buy_gate_updated/orders_sent` 全部 `false`（与生产 plist 契约一致）
- 静态页面：API 在 `/` 挂载构建后的 dist（主应用 / `/manager-selection/` / `/daily-research-command/`）

```bash
bash "/Users/lexi/Desktop/学习/v4_app/.runtime/serve-v4-sandbox.sh"
# 浏览器打开 http://127.0.0.1:8899/
```

## 三、三来源对照（我的审计 × 外部修复包 × v4 现状 → 本次动作）

| 项 | 审计/修复包结论 | v4（release v8）现状 | 本次动作 |
|---|---|---|---|
| P0-1 调度入口签名错配（main 线） | `run_scheduled_slot` 传 4 个不被接受的参数 | **v4 线已修复**（`FixedExecutorRegistry` 接受 external-root 参数，双调用点一致） | 不改，记录 |
| P0-2 manager 三链路无后端 | main 线必 404 | **v4 线已修复**（`manager_research_router.py` + `/api/v4/manager/research*` 等全路由在线，实测返回真实产品） | 不改，验证 |
| P0-3 关键合同不在 git | `v3_runtime_graph_contract.json` 等 8 文件只在磁盘 | 同上（复制自 release，无从查证其 git 史） | **首提交全量落库**（含合同 JSON） |
| P0-4 测试机器绑定/缺数据 | `C:\Users\huang`、`/Users/lexi`、`.runtime` 证据依赖 | v4 tests 中仍存在（18 文件 118 处引用） | 部分恢复（补 `.runtime/evidence` 真实证据树）；其余分类记录 |
| 安全过滤三套分叉 | pool 过滤器漏 action 词（`{"buy":"YES"}` 可过） | **v4 同样存在**（4 份拷贝：pool/stage/universal/data_store） | **已修复**：统一为 `infrastructure/trading_safety.py` 严格超集 + 一致性测试 |
| 锁实现 | main 线 mtime 强删锁有竞态（修复包 A01） | v4 线已是 `interprocess_lock`（PID 存活检测，无按龄强删） | 不改（对比结论记录，不混跑两套） |
| dry-run 占用正式 claim（A06） | main 线需修 | v4 线已有 `dry_run_namespace()` | 不改 |
| pyarrow/pandas 依赖缺口 | main 线缺声明 | v4 环境（既有 venv）已含；`pyproject.toml` 仍未声明 | 记录（建议补声明，本次不改声明以保持冻结环境一致） |
| starlette 1.6 TestClient 弃用告警 | — | `-W error` 下 6 个测试文件无法收集 | **已修复**：单类告警放宽（其余仍 error） |

## 四、测试证据

环境：既有 `runtime/venvs/v3.5-mac`（Python 3.14.6，macOS）。原始日志在 `v4_app/artifacts/`。

| 运行 | 结果 | 说明 |
|---|---|---|
| baseline_v2.log（快照 = 未集成修改的原始 v4_app） | **918 passed / 102 failed / 10 errors / 69s** | 10 个收集错误：6×starlette 弃用告警升级、2×pyarrow 缺失、1×缺 `ops.build_manager_source_successor_proof`、1×其他 |
| after_final3.log（集成后，`--ignore` 两个真实物化吊死测试） | **1008 passed / 77 failed / 2 errors / 73s** | 对比基线：**+90 passed、-25 failed、-8 errors**。剩余 2 个收集错误 = `test_manager_overlay_supersession` / `test_review_calendar_input`（基线同样存在） |

**失败主因分类（102 → 最终）**：
1. **依赖缺失（已恢复）**：pyarrow×23、pandas×2 用例此前 ModuleNotFoundError；既有环境装好后可运行。
2. **收集错误（已恢复）**：6 个 starlette 弃用文件在告警放宽后可收集运行。
3. **证据/机器绑定（部分恢复，其余 CANNOT_CONFIRM）**：`.runtime/evidence` 证据树补齐后 phase0/phase4/phase5 等文件读取类失败减少；publisher 的 `_formal_data_root()` 硬编码正式根（`~/Library/.../state/data`）+ 个人 Documents 路径 → 单测 fixtures 走 tmp 路径必 `PATH_UNSAFE`；这类"产品守卫与单测从未同场验证"的分叉**不修改产品语义**，保留为待裁决。
4. **冻结哈希类**：phase5/6/7 回执、preselection receipt 等断言历史 SHA 的测试与当前 checkout 不匹配（`test_phase6_current_checkout_*` 需要 git 仓库上下文），属"历史证据 vs 当前树"的固有张力。
5. **吊死测试（新发现，重要）**：`tests/test_stage_eight_runs.py` 的**两个测试**（`test_eight_stages_independently_materialize_from_real_sources` 与 `test_eight_stages_api_returns_native_snapshot_with_safe_boundaries`）——依赖 pandas 可用 + 本机真实 TDX/HK 数据，会进入**无超时的真实物化**流程并无限挂起（基线中因依赖缺失为快速失败）。最终全量运行以 `--ignore=tests/test_stage_eight_runs.py` 排除（2 个测试）；建议：给该类测试加显式 root 注入 + 超时守卫（属测试改造，本次不做）。

剩余 77 个失败的分簇（与基线同源，均非本次集成引入）：`test_runtime_graph_hardening`(15) 与 `test_review_core_natural_pool_pipeline`(14) 为产品守卫硬编码正式根/个人路径 vs 单测 tmp fixtures 的 PATH_UNSAFE/PathBoundary 家族；`test_phase5_runtime_governance_audit`(9) 为 "unsafe task registration boundary"（测试与收紧后的注册守卫漂移）；`test_preselection_slice`(3) 为日期目录行为断言；其余为冻结哈希/git 上下文/证据绑定类。完整清单见 `artifacts/after_final3.log`。

## 五、页面点击验收（真实浏览器，无头 Chrome + CDP，零安装）

用机器上既有 Chrome（152）+ 纯标准库 CDP 驱动执行**真实点击/输入**；每步采集：正文长度、关键控件、控制台错误、失败请求、HTTP≥400、截图。截图存于 `v4_app/artifacts/screenshots/`。

| # | 步骤 | 结果 | 截图 |
|---|---|---|---|
| 01 | 打开首页 `/` | 4.7 万字符正文；20 条时间线；US CLOSE 板块数据；0 错误 | 01-home.png |
| 02 | **点击「经理选股工作台」** | 跳转 `/manager-selection/?date=20260901`；10 只固定候选（HK.06090 不同集团…HK.03986 兆易创新）；资料阅读台诚实 CANNOT_CONFIRM；唯一 404 = favicon（无功能影响） | 02-manager-workbench-click.png |
| 03 | **在经理页把目标交易日 2026-09-01 → 2026-09-10** | URL 随动 `?date=20260910`；正文 3.1 万 → **9.2 万字符**；`reader=READY`（资料 200 条 / 原事件 11 条）；0 错误 | 03-manager-date-20260910.png |
| 04 | **点击「研报决策台」** | 真实研报正文（*ST西旅/盈新发展/西安饮食/紫光股份 等 L3 证据）；过滤器齐全；0 错误 | 04-research-desk.png |
| 05 | **点击「A股复盘」** | **17 张表 / 974 行**；US CLOSE PROXY MAP 24 组板块涨跌；0 错误 | 05-a-share-review.png |
| 06 | **点击「D-1 预选池」** | **8 张表 / 835 行**；0 错误 | 06-d1-pool.png |
| 07 | **点击「任务状态」** | 任务状态面板切换；0 错误 | 07-task-status.png |
| 08 | 打开 `/daily-research-command/` | 独立入口加载；空态如实提示"请选择 exact research date" | 08-daily-research-command.png |
| 09 | 全天指挥台选日期 20260910 | 正文 696 → **4.1 万字符**；requested/resolved=20260910；STATUS=CANNOT_CONFIRM（SEV2 registry missing 如实暴露）；安全旗正确；0 错误 | 09-daily-command-20260910.png |

**结论：全部页面均渲染真实内容（非空白）；点击、日期输入、视图切换均驱动真实数据请求；全程零 console error（除 favicon 404）、零失败请求、零 HTTP≥400。**

## 六、API 冒烟（沙箱 8899）

- `/healthz` → `{"status":"ok"}`；`/readyz` → 三安全旗 false
- `/api/v4/manager/research?date=20260910` → 真实产品（HK_CONNECT / STAGE_0935_0940 / input_row_count=10）
- `/api/v3/preselection-pools?date=20260910` → 真实池（A股 D-1 v1.9.2 候选池等）
- `/api/v3/research/dates` → 真实日期目录；`/api/v3/manager/stage-selection` 等 37 条路由全部注册

## 七、遗留问题与建议（CANNOT_CONFIRM）

1. **v9–v14「inactive candidate」链未纳入**（A 股恢复类 overlay，独立评审链中）——是否并入需裁决。
2. **publisher `_formal_data_root` 硬编码**：产品代码内嵌个人路径（`/Users/lexi/Documents/Codex/2026-08-13`、`~/Library/...`）+ 单测 fixtures 在 tmp → 该族单测永远 PATH_UNSAFE。建议：给守卫加显式配置/env seam 后再改测试（动产品语义前需裁决）。
3. **测试机器绑定 18 文件 118 处**：建议按"显式 env 注入 + 缺数据 skip（保留断言）"逐文件改造，本次未批量改（避免大范围 churn）。
4. **`test_stage_eight_runs` 真实物化无超时**：建议加超时/根注入守卫（详见第四节）。
5. **依赖声明缺口**：`pyproject.toml` 未声明 pyarrow/pandas/httpx2（环境靠既有 venv 承载）；建议补 `[dependency-groups]` 声明。
6. **favicon 404**：manager-selection 入口未声明 favicon（仅噪音）。
7. **本机残留**：另有一个 9 月 9 日起驻留的旧 pytest 进程（PID 64780，非本次产生）与 `/private/var/.../pytest-of-lexi/garbage-*` 历史残片（属旧运行的 chmod 保护目录，pytest 清理失败仅告警）。建议手工核销。
8. **Claude 桌面版 Browser 预览在本安装不可用**（预览子进程沙箱拒绝读取项目文件；已用"Chrome + CDP"替代并留证）。若后续要恢复 in-app 预览，需检查该安装的预览沙箱配置。

## 八、边界声明

- 未修改：v3.5 仓库、`~/Library/.../releases/*`、launchd、`state/*` 生产数据（manager 写入被隔离到沙箱拷贝）、`v3_shared_data`。
- 未新增任何依赖安装（验证环境 = 既有 `runtime/venvs/v3.5-mac`）。
- 未启用任何 workload、未接交易、未改变 BUY gate。
- 本交付为**候选工作副本**：页面与 API 的本地验收通过不等于部署或放行。
