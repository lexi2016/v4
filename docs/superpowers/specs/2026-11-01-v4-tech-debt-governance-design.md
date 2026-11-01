# V4 技术债治理设计

- 日期：2026-11-01
- 状态：待批准
- 适用范围：`v4_app` 源码仓库（线上 8873 的后端与前端源码）
- 关联审计：`/Users/lexi/Desktop/学习/agents调试/v4_code_audit_20261101/AUDIT_REPORT.md`

## 1. 意图与目标

把当前"改一次数据要发版、改一个阶段怕碰坏别的、看不懂跳不动、前端大文件改不动"
这四类问题逐项消除。目标不是"代码变好看"，而是三件可验证的事：

1. 补历史数据不需要改代码、不需要发版；
2. 改一个阶段的行为，只碰几十行代码，且有测试兜底；
3. 编辑器能跳转、类型检查能报真问题；前端改一个 tab 不再动 4,000 行文件。

## 2. 非目标与反目标

- 不改任何业务含义、数据边界、PIT/证据链语义、BUY gate。
- 不迁移架构（不换框架、不换数据库、不改模块角色）。
- 不做"大爆炸"重写；不允许攒成一个持续多周、一次性上线的大重构。
- 反目标：治理过程中出现任何响应内容变化（哪怕字段顺序），都视为失败。

## 3. 现状（2026-11-01 实测，线上 release）

后端非 vendor 代码 **208,187 行**。集中在这个文件：

| 指标 | 数值 |
| --- | --- |
| `apps/api/v4_api/app.py` | **6,478 行 / 400 KB** |
| 其中 `create_app` 之前（模块级） | **4,398 行** |
| 其中 `create_app` 函数 | **2,081 行** |
| 模块级赋值语句 | 31 个，合计 3,735 行 |
| 64 位 SHA 字面量 | **1,572 个** |
| 8 位日期字面量 | 176 个 |

### 3.1 模块级常量的真实构成（前 10）

| 行数 | 名称 | 类型 |
| --- | --- | --- |
| 2,276 | `_MONTH_HK_AFTERFACT_R9_STAGE_ROWS` | Tuple |
| 597 | `_MONTH_HK_AFTERFACT_R5_BINDINGS` | Tuple |
| 165 | `_MONTH_HK_AFTERFACT_R8_BINDING_ROWS` | Tuple |
| 140 | `_HK_R9_POOL_EVIDENCE` | Dict |
| 101 | `_HK_R9_LEGACY_STALE_LANE_IDENTITIES` | Dict |
| 76 | `_HK_MORNING_HISTORY_20261023` | Dict |
| 58 | `_HK_MORNING_SELECTION_RECOVERY_ROWS` | Tuple |
| 51 | `_APPROVED_EXACT_STAGE_BACKFILLS[(date, stage, market, run_id)]` | Dict |
| 44 | `_HK_MORNING_HISTORY_SAFE_PACKETS` | Dict |
| 31 | `_HK_R8_COMMON_REQUIRED_EVIDENCE` | Tuple |

其中 `_MONTH_HK_AFTERFACT_R8_BINDINGS`、`_MONTH_HK_AFTERFACT_R9_BINDINGS`、
`_HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE` 是**计算得到的**（Call / DictComp），
不是纯数据；它们由叶子常量派生，迁移叶子后保持不动。

### 3.2 其它结构债

| 位置 | 问题 |
| --- | --- |
| `apps/api/v4_api/app.py` | `create_app` 2,081 行；`stage_workbench` 单路由 540 行；`project_shared_selection` 264 行 |
| `domains/*`、`infrastructure/*` | **72 处** `globals(),` 注入 + **8 个** `_*_parts` 目录；为拆文件而放弃正常导入 |
| `apps/web/src/views/ManagerSelectionView.vue` | **4,002 行** |
| `apps/web/src/api/managerWorkspace.ts` | **1,858 行**，只有 4 个 fetch，其余全是内联校验 |
| `apps/web/src/manager-workbench/Workbench.vue` | 1,333 行 |
| `apps/web/src/components/research/GlobalIndustryMap.vue` | 1,232 行 |
| `apps/web/src/app_shell/useAppShell.ts` | 990 行，返回 106 个键 |

## 4. 总体策略

四个独立项目，按 **数据 → `create_app` → `globals()` → 前端** 顺序推进。
每个阶段满足：独立分支、独立 canary、独立验收、独立发布、独立回滚。

阶段之间**不共享分支**，不允许前一阶段未发布就开下一阶段。

## 5. 阶段 0：安全网（所有阶段的前置）

在动任何代码前先固化"行为基线"，否则无法证明重构没有改变行为。

- 工具：新增 `ops/capture_response_baseline.py`（只读，GET 全部路由）。
- 输入：固定日期集合（近 10 个交易日 + 3 个历史回补日 + 1 个空日期）。
- 输出：每个 `(date, path)` 的响应体 SHA-256 与字节数，写入
  `agents调试/tech_debt_20261101/baseline/<phase>.json`。
- 验收：每个阶段完成后重跑同一工具，**所有 SHA 必须完全一致**；出现差异即为 FAIL，
  必须解释并证明差异是预期的（例如显式记录了新增字段）。

采集范围：`/api/v1/runs/date-list`、`/api/v4/meta/stages`、`/api/v4/preselection-pools`、
`/api/v4/workbench/stage`（7 个阶段）、`/api/v4/workbench/stage-batch`、
`/api/v4/review`、`/api/v4/tasks/status`、`/api/v4/manager-workbench/*`（只读子集）。

### 5.1 规范化规则（否则 SHA 相等不可能成立）

实测这些响应含易变内容，直接比对 SHA 会永远 FAIL。基线工具必须按路由做确定性规范化：

| 路由 | 易变字段 | 处理 |
| --- | --- | --- |
| 全部 | `runtime_identity`（每次发布后 `release_id`/`manifest_sha256` 变化） | 整块移除 |
| `date-list` | `system_date`、`navigation_date`、`requested_date`、`selected_date`、`research_dates` 等随自然日/请求变化 | 固定 `?date=` 并移除 `system_date` |
| `tasks/status` | 时间戳、进程状态、耗时 | 移除 `*_at`、`*_seconds`、`process_status` 类字段 |
| `review` | 生成时间类字段 | 移除 `*_at`、`*_time` |
| 全部 | 列表顺序敏感性 | 仅对明确无序的字段排序；有顺序含义的（如选中排名）保持原序 |

规范化规则写在基线工具里，并与其输出一起存档。规则本身的任何变更都必须显式记录，
因为它会改变"一致"的含义。

### 5.2 采集安全性

被采集的全部是 GET 路由。当前实现中 GET 路径只读 store / 只读文件，
响应携带 `write_performed=false`，人工收集类是 POST 且不在采集范围。
尽管如此，基线工具仍要在采集前断言目标实例的只读标志，并在采集后比对 store 目录
mtime 未变化。

### 5.3 环境

- **线上 8873** 当前运行的是候选 release（不是某个 git 分支的 HEAD）。
- 每个阶段从**对应源码分支**切出，构建候选后在**临时端口**（如 8991）用真实数据验证，
  再决定是否切换线上。
- 切换线上属于需要单独授权的动作；每个阶段结尾都停在"候选已验证、等授权"。

## 6. 阶段 1：数据出代码

### 6.1 做法

1. 新增 `apps/api/v4_api/evidence/` 目录，按数据集拆 JSON：
   `hk_r9_stage_rows.json`、`hk_r5_bindings.json`、`hk_r8_binding_rows.json`、
   `hk_r9_pool_evidence.json`、`hk_r9_stale_lane_identities.json`、
   `hk_morning_history_20261023.json`、`hk_morning_history_safe_packets.json`、
   `hk_r8_common_required_evidence.json` 等。
2. 新增 `apps/api/v4_api/evidence/loader.py`：
   - 启动时加载，校验 `evidence/manifest.json`（每个文件 path + SHA-256 + 条目数）；
   - **元组键还原**：JSON 只能表达数组，加载后把需要元组键的映射还原为 `tuple` 键
     （`_APPROVED_EXACT_STAGE_BACKFILLS` 实测需要）；
   - **元组/列表保真**：原字面量是 `tuple` 的，加载后仍为 `tuple`，避免比较语义变化；
   - 失败即抛 `EVIDENCE_DATASET_INVALID:<name>:<reason>`，不允许静默降级。
3. `app.py` 顶部改为从 loader 取名字，消费代码一行不改：
   `from apps.api.v4_api.evidence.loader import _MONTH_HK_AFTERFACT_R9_STAGE_ROWS`
   或 `_HK_R9_POOL_EVIDENCE = evidence.named("hk_r9_pool_evidence")`。
4. 计算型常量（Call / DictComp）保持在代码里，只把它们的叶子依赖换成加载值。

### 6.2 迁移顺序（canary 优先）

| 批次 | 数据集 | 理由 |
| --- | --- | --- |
| C1 | `_HK_R8_OBSERVATION_MODE_SHA256_BY_DATE_STAGE`（17 行） | 最小、纯字典、可立即验证 |
| C2 | `_MONTH_HK_AFTERFACT_R9_STAGE_ROWS`（2,276 行） | 最大收益，单独一批便于定位问题 |
| C3 | `_MONTH_HK_AFTERFACT_R5_BINDINGS` + `_MONTH_HK_AFTERFACT_R8_BINDING_ROWS` | 两个大元组 |
| C4 | 其余小字典/元组（约 8 个） | 收尾 |
| C5 | 删除 `app.py` 中的原字面量，行数目标 < 3,000 | 收益兑现 |

每批完成后立即：跑全量测试 + 阶段 0 基线对比 + 独立提交。

### 6.3 等价性证明（每批必做）

- 迁移前：用 `pickle` 或 JSON 规范化导出原常量到 `agents调试/.../oracle/<name>.json`。
- 迁移后：断言 `loaded == oracle`，并额外断言类型一致（`Tuple`/`Dict`/键类型）。
- 迁移完成后把 oracle 保留为回归测试，防止后续误改。

### 6.4 已知风险

| 风险 | 应对 |
| --- | --- |
| 元组键无法直接 JSON 化 | loader 显式还原；测试覆盖 `.get((d,s,m,r))` 的命中与未命中 |
| 元组/列表语义不同 | 按原类型还原；oracle 断言类型 |
| 字典顺序影响输出 | JSON 保留插入顺序；基线 SHA 对比兜底 |
| 大文件加载影响启动 | 实测启动耗时；必要时按需惰性加载（先用全量加载，简单优先） |
| 数据文件未随 release 打包 | 已核实：发布构建**只复制 git 跟踪的文件**（`build_candidate` 用 `_git_tracked_paths`），所以 `evidence/*.json` 必须先提交到 git，且在构建后用 inventory 条目数校验 |

### 6.5 验收

- `app.py` < 3,000 行；
- 31 个模块级赋值中，纯数据项全部来自 `evidence/`；
- 全量测试通过（基线为当前线上分支的 78 项后端测试）；
- 阶段 0 基线 SHA 全部一致；
- 启动时间不高于当前 +0.5 s。

## 7. 阶段 2：拆 `create_app`

### 7.1 做法

按职责切成模块，`create_app` 只做装配：

| 新模块 | 承接内容 | 预计行数 |
| --- | --- | --- |
| `v4_api/read_models.py` | 数据读取与 store 装配 | ~300 |
| `v4_api/verify.py` | HK 回补/晨间/择时证据校验（`_hk_r8_*`、`_hk_r9_*`、`_hk_morning_*`） | ~600 |
| `v4_api/projection.py` | `project_shared_selection`、市场状态归约 | ~500 |
| `v4_api/routes/stage.py` | `stage_workbench`（540 行）拆成 3 段私有函数 | ~540 |

### 7.2 顺序（canary 优先）

1. `project_shared_selection`（264 行闭包）→ 独立函数，参数显式传入依赖；
2. `stage_workbench` 540 行按"取数 / 校验 / 投影"拆三段；
3. `_hk_r8_*` / `_hk_r9_*` 校验函数成组迁移到 `verify.py`；
4. `create_app` 收敛到 < 300 行装配代码。

### 7.3 验收

- `create_app` < 300 行；
- 路由目录测试通过（`tests/test_v4_legacy_retirement.py` 的完整路由清单）；
- 阶段 0 基线 SHA 全部一致；
- 全量测试通过。

## 8. 阶段 3：去 `globals()`

### 8.1 根因

`_parts` 分片是为了在不改内部引用的前提下物理拆文件，`_namespace.read_global` 是它的垫片。
根因是**循环导入**：门面 `domains/preselection.py` 导入 parts，parts 又需要门面的名字。

### 8.2 做法

按模块分批，每批：

1. 抽出共享常量/工具到 `_common.py`（不依赖门面）；
2. parts 正常 `from ._common import ...`，删除 `_v4_global(_v4_scope, ...)`；
3. 门面改为直接 `from ._parts.x import y` 并 re-export；
4. 删除 `_namespace.py` 与该模块的 `globals(),` 调用。

### 8.3 顺序

| 批次 | 模块 | 调用点 |
| --- | --- | --- |
| G1 | `domains/_preselection_parts` | 约 20 处 |
| G2 | `infrastructure/_research_store_parts`、`_research_peripheral_store_parts` | 约 15 处 |
| G3 | `stage_center/_selection_parts`、`_runner_parts` | 约 20 处 |
| G4 | 其余 parts | 剩余 |

### 8.4 验收

- `grep -rn 'globals(),' → 0`；
- `_parts` 目录仍可存在（拆文件本身不是问题），但不再有命名空间垫片；
- 每个模块导入图无环（新增一个 import-graph 测试）；
- 全量测试 + 基线 SHA 一致。

## 9. 阶段 4：前端拆组件

### 9.1 做法

1. `ManagerSelectionView.vue`（4,002 行）→ 按 tab 拆 6 个子组件 + 1 个
   `useManagerSelection.ts` 组合式函数；父组件只保留布局与 tab 切换。
2. `managerWorkspace.ts`（1,858 行）→ 校验器抽到 `contracts/managerWorkspaceSchema.ts`，
   `api/` 只保留 4 个 fetch 与类型导出。
3. `Workbench.vue`、`GlobalIndustryMap.vue` 按同一原则拆。

### 9.2 验收

- 单文件 < 800 行；
- `vitest` 17 项通过；新增拆分组件的渲染测试；
- `vue-tsc` 错误数不高于基线（当前 26 个既有错误）；
- `vite build` 成功；
- 浏览器实测:经理工作台各 tab、研究地图、阶段页正常。

## 10. 每阶段的统一交付物

| 项 | 内容 |
| --- | --- |
| 分支 | `refactor/<阶段>-<日期>`，从线上对应分支切出 |
| canary | 每阶段先迁 1 个最小单元并验证 |
| 独立验收 | 阶段 0 基线 SHA + 全量测试 + 单独一个 reviewer |
| 发布 | 走现有 release 候选流程（非直接改线上） |
| 回滚 | 保留上一版 release 目录与 plist 备份 |

### 10.1 基线健康度（2026-11-01 实测）

| 分支 | 后端 | 前端 |
| --- | --- | --- |
| `claude/perf-date-list-live-20261101`（线上基线） | pytest **78 passed** | vitest **12 passed**；vue-tsc **26 个既有错误**；build 成功 |
| `claude/perf-date-list-20261101` | pytest **105 passed**（4 个为既有 `P29_STAGE_APP_ROOT` 环境依赖失败） | vitest **17 passed** |

这些数字就是各阶段的验收阈值。若某台机器跑不出这些数字，先修环境，不要动重构。

### 10.2 独立验收与授权

- 每个阶段安排**一次独立 reviewer**（只读身份、非 Writer），按项目 C 类整改规则。
- 每个阶段的部署都是单独授权的动作；阶段结束时停在"候选已在临时端口验证通过、等授权切换"。

## 11. 工作量估算（粗估，按一个熟练执行者）

| 阶段 | 工作量 | 可感知收益 |
| --- | --- | --- |
| 0 安全网 | 0.5–1 天 | 无（但后续每一步都依赖） |
| 1 数据出代码 | 2–3 天 | 补数据不再发版 |
| 2 拆 create_app | 3–5 天 | 改阶段只碰小函数 |
| 3 去 globals | 2–4 天 | 能跳转、能静态检查 |
| 4 前端拆分 | 3–5 天 | 改 tab 不动大文件 |

## 12. 决定项（本设计的判断，供你核对）

1. **先数据后结构**：因为数据的痛最频繁，且它独立于其他三项。
2. **保留 `_parts` 目录形态**：问题不是"拆文件"，而是"用 `globals()` 拆"，所以只去垫片。
3. **不做一次性大重构**：每阶段单独发布，失败只回滚那一阶段。
4. **以响应 SHA 作为行为等价判据**：比人工看代码可靠。
5. **数据文件用 JSON 而不是 Python 字面量**：可被外部工具校验，且不会再被当成代码编译。

## 13. 未决事项（等你的意见）

- 数据文件是放在 `apps/api/v4_api/evidence/`（代码同级），还是放在共享数据仓
  `v3_shared_data`（跨项目复用）？本设计默认前者，因为它是该 API 的运行时证据。
- 阶段 3 完成后是否要把 `_parts` 目录合并回单文件？本设计建议**不合并**，
  拆文件本身无害，合并会引入新的风险。
