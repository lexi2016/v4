# V4 技术债治理设计（修订版）

- 日期：2026-11-01（修订 r2）
- 状态：待批准
- 适用范围：`v4_app` 源码仓库（线上 8873 的后端与前端源码）
- 关联审计：`/Users/lexi/Desktop/学习/agents调试/v4_code_audit_20261101/AUDIT_REPORT.md`
- 修订依据：独立审查 6 点意见（2026-11-01），逐条已并入本文

## 0. 本修订解决了什么

| 原问题 | 本版处理 |
| --- | --- |
| "补数据不发版"与实现方式矛盾 | 目标改为**证据与逻辑分离**；运行中更新证据单独立项 |
| 响应 SHA 不能单独证明等价 | 改为精确字段路径白名单 + 身份必过断言 + 冻结数据 generation/配置/时钟 |
| 基线覆盖不闭合 | 8 个阶段、真实路由清单、负向分支样本、写接口隔离测试 |
| 数据迁移缺初始化语义 | 明确迁移"导入初始化后的最终值"，oracle 递归校验类型/顺序/键唯一/命中与撤销 |
| "globals 根因是循环导入"未证实 | 先画依赖图并分类，再决定普通导入还是显式参数 |
| 验收指标与发布基线不收紧 | 固定命令与诊断集合、受影响范围零新增错误、发布绑定现役 manifest 与继承 SHA |

## 1. 意图与目标

把四类问题逐项消除。**可验证**的目标如下（按阶段对应）：

1. **阶段 1**：历史证据与业务逻辑在源码上分离——证据是可被独立校验的数据资源，
   逻辑不再被 4,398 行字面量淹没。**本阶段不承诺"运行中更新证据"**。
2. **阶段 2**：改一个阶段的行为只碰几十行函数，且有测试兜底。
3. **阶段 3**：编辑器能跳转、类型检查能覆盖真实缺陷。
4. **阶段 4**：前端改一个 tab 不再动 4,000 行文件。

### 1.1 明确不在本设计内

"补一次数据不用发版"仍需要一个独立设计：接入既有数据 owner、版本指针、
校验与回退合同。本设计只把证据从代码中移出，**仍随 release 冻结**。

## 2. 非目标与反目标

- 不改业务含义、数据边界、PIT/证据链语义、BUY gate。
- 不迁移架构（不换框架、不换数据库、不改模块角色）。
- 不做一次性大重构。
- 反目标：任何**非预期**的响应差异（状态码、关键响应头、规范化后的业务字段）即 FAIL。

## 3. 现状（2026-11-01 实测，线上 release）

后端非 vendor 代码 208,187 行。集中在这个文件：

| 指标 | 数值 |
| --- | --- |
| `apps/api/v4_api/app.py` | 6,478 行 / 400 KB |
| `create_app` 之前（模块级） | 4,398 行 |
| `create_app` 函数 | 2,081 行 |
| 模块级赋值语句 | 31 个，合计 3,735 行 |
| 64 位 SHA 字面量 | 1,572 个 |
| 8 位日期字面量 | 176 个 |

### 3.1 模块级常量（前 10）

| 行数 | 名称 | 类型 |
| --- | --- | --- |
| 2,276 | `_MONTH_HK_AFTERFACT_R9_STAGE_ROWS` | Tuple |
| 597 | `_MONTH_HK_AFTERFACT_R5_BINDINGS` | Tuple |
| 165 | `_MONTH_HK_AFTERFACT_R8_BINDING_ROWS` | Tuple |
| 140 | `_HK_R9_POOL_EVIDENCE` | Dict |
| 101 | `_HK_R9_LEGACY_STALE_LANE_IDENTITIES` | Dict |
| 76 | `_HK_MORNING_HISTORY_20261023` | Dict |
| 58 | `_HK_MORNING_SELECTION_RECOVERY_ROWS` | Tuple |
| 51 | `_APPROVED_EXACT_STAGE_BACKFILLS`（元组键） | Dict |
| 44 | `_HK_MORNING_HISTORY_SAFE_PACKETS` | Dict |
| 31 | `_HK_R8_COMMON_REQUIRED_EVIDENCE` | Tuple |

计算型常量（`Call` / `DictComp`）保留在代码中，只把叶子依赖换成加载值。

### 3.2 其它结构债

- `create_app` 2,081 行；`stage_workbench` 540 行；`project_shared_selection` 264 行
- **72 处** `globals(),` 注入 + **8 个** `_*_parts` 目录
- 前端：`ManagerSelectionView.vue` 4,002 行、`managerWorkspace.ts` 1,858 行、
  `Workbench.vue` 1,333 行、`GlobalIndustryMap.vue` 1,232 行、`useAppShell.ts` 990 行

## 4. 总体策略

四个独立项目，顺序：**数据 → `create_app` → `globals()` → 前端**。
每阶段独立分支、独立 canary、独立验收、独立发布、独立回滚。

## 5. 阶段 0：安全网

### 5.1 工具

新增 `ops/capture_response_baseline.py`（只读 GET），输出：

```
{
  "captured_at": "...", "target": "<url>", "frozen": {...},
  "samples": [{"id": "...", "method":"GET", "path":"...", "params":{},
               "status": 200,
               "headers": {"content-type": "..."},
               "body_sha256": "<规范化的业务字段摘要>",
               "normalized": {"<field.path>": "<value>"}}]
}
```

### 5.2 规范化：精确字段路径白名单（不是模糊删除）

**禁止**按 `*_at` / `*_time` 通配删除——那会掩盖发布时间、采集时间、截止时点等业务变化。
改为**逐路由列出允许忽略的精确路径**，每条都要写明忽略理由：

| 路由 | 精确忽略路径 | 理由 |
| --- | --- | --- |
| 全部 | `runtime_identity.release_id`、`runtime_identity.manifest_sha256` | 每阶段候选的发布标识必然变化 |
| — | 其余 `runtime_identity.*` **不忽略** | 身份回归必须被捕获 |
| `tasks/status` | 逐条列出实测确认的时钟/进程字段（采集时由工具生成，不在文档里猜） | 进程与时钟属运行时事实 |

规则：

- 忽略清单在**采集时**由工具与基线一起冻结（含每条的实测样本值），不允许事后追加。
- 任何**未列出**的字段差异一律 FAIL。
- 身份另设**必过断言**：候选实例必须满足
  `runtime_identity.status == MANIFEST_EXECUTION_FILES_VERIFIED`
  与 `/api/v4/runtime-graph/frontend-build` 的 `status == VERIFIED`；
  这两条是断言，不是"忽略项"。

### 5.3 比较口径

- 比较 **HTTP 状态码**、**关键响应头**（`content-type`）、**规范化后的 JSON 结构**；
- 不比较序列化差异（空白、字段顺序、数字字面量形式）；
- JSON 结构比较保持**数组顺序**（排名、时间轴有顺序含义），对象按键集合比较。

### 5.4 冻结条件

每次采集必须同时记录并固定：

- 数据 generation：`date_catalog.json` 的 SHA、`selection_latest.json` 的 SHA；
- 配置：相关 `V4_*` 环境变量的值；
- 时钟：采集时的 `system_date` 与采集窗口。

三者任一在前后两次采集中不同，结论标记为 `NOT_COMPARABLE`，不判 PASS/FAIL。

### 5.5 样本清单（闭合）

阶段（现役 **8 个**）：`STAGE_0925`、`STAGE_0930_0935`、`STAGE_0935_0940`、
`STAGE_0940_0945`、`STAGE_0945_1030`、`STAGE_1300_1315`、`STAGE_1445_1500`、`STAGE_1545_1555`。

只读路由（采集时以 OpenAPI 实际路由为准，逐一登记参数）：

- `/healthz`、`/readyz`
- `/api/v1/runs/date-list`
- `/api/v4/meta/stages`
- `/api/v4/preselection-pools?date=&limit=&offset=`（含分页第 1 页与第 2 页）
- `/api/v4/workbench/stage?date=&stage=&limit=`（8 个阶段）
- `/api/v4/workbench/stage-batch?date=&stages=`
- `/api/v4/stage-center/selection?date=&stage=`
- `/api/v4/review?date=`
- `/api/v4/tasks/status?date=`
- `/api/v4/manager/stage-selection?date=`
- `/api/v4/manager-workbench/*`（只读子集，参数与分页在采集清单中逐条登记）
- `/api/v4/runtime-graph/*`（只读状态类）

**负向分支样本**（必须覆盖，不能只挑正常日期）：

| 样本 | 目的 |
| --- | --- |
| 撤销绑定的日期/阶段 | 撤销逻辑 |
| SHA 不匹配的构造样本（临时 store） | 校验失败路径 |
| 缺失证据的日期 | CANNOT_CONFIRM 路径 |
| 空结果（READY_EMPTY） | 零结果路径 |
| 事后观察（AFTERFACT / OBSERVATION_UNVERIFIED） | 观察路径 |

**写接口**：`/api/v4/workbench/stage/ensure`、`/api/v4/stage-center/selection/ensure`
不进基线（会写），但阶段 2 必须为它们补**隔离测试**（临时 store，证明拆分前后行为一致）。

### 5.6 采集安全

只采 GET；采集前断言目标实例只读标志；采集后比对 store 目录 mtime 未变化；
v4-mac 解释器以 `-I` 启动，避免 `PYTHONPATH` 指向 release 导致测错代码。

### 5.7 环境

- 线上 8873 运行的是候选 release，不是 git 分支 HEAD。
- 每阶段从对应源码分支切出 → 构建候选 → **临时端口**用真实数据验证 → 单独授权后再切换线上。

## 6. 阶段 1：证据与逻辑分离

### 6.1 核心约定：迁移的是"初始化后的最终值"

`app.py` 在导入期并不只是定义字面量：`_APPROVED_EXACT_STAGE_BACKFILLS` 有后续追加，
部分常量由 `Call` / `DictComp` 派生。因此必须明确：

- **迁移对象 = 模块导入完成后、`create_app` 第一次执行前**的最终值；
- 加载器返回该最终值，**不再执行任何初始化逻辑**（追加、撤销都在数据侧完成）；
- 数据文件记录生成时的初始化来源与步骤，便于追溯。

### 6.2 类型与结构保真

不只是 tuple/list：

| 结构 | 处理 |
| --- | --- |
| `tuple` | 加载后仍为 `tuple` |
| `set` | JSON 存排序数组，加载时还原 `set` |
| 元组键映射（`_APPROVED_EXACT_STAGE_BACKFILLS`、`_HK_R8_OBSERVATION_MODE_SHA256_BY_DATE_STAGE`） | JSON 存 `[[key...], value]`，加载时还原元组键 |
| 派生映射 | 仍由代码从叶子值计算，不迁移 |

### 6.3 加载器

`apps/api/v4_api/evidence/loader.py`：

- 启动时加载 `evidence/manifest.json`（每文件 path + SHA-256 + 条目数）；
- 校验失败抛 `EVIDENCE_DATASET_INVALID:<name>:<reason>`，不静默降级；
- 不复制业务逻辑，只做解码与类型还原；
- 不做运行时热更新。

### 6.4 迁移顺序（canary 优先）

| 批次 | 数据集 | 说明 |
| --- | --- | --- |
| C1 | `_HK_R8_OBSERVATION_MODE_SHA256_BY_DATE_STAGE`（17 行） | **注意：它本身已是元组键**，直接验证键还原 |
| C2 | `_MONTH_HK_AFTERFACT_R9_STAGE_ROWS`（2,276 行） | 最大收益 |
| C3 | `_MONTH_HK_AFTERFACT_R5_BINDINGS` + `_MONTH_HK_AFTERFACT_R8_BINDING_ROWS` | 两个大元组 |
| C4 | 其余小字典/元组 | 收尾 |

### 6.5 等价性证明

- oracle 来自**迁移前的原始代码**，不是迁移后的 JSON；
- 递归比较：类型、tuple/list/set、键唯一性、顺序、元组键的**命中 / 未命中 / 撤销**；
- 额外断言 `_APPROVED_EXACT_STAGE_BACKFILLS` 的追加与撤销结果；
- oracle 保留为回归测试。

### 6.6 发布打包约束（已核实）

发布构建**只复制 git 跟踪的文件**（`_git_tracked_paths`），因此：

- `evidence/*.json` 必须先提交到 git；
- 构建后用 inventory 条目数核对新增文件已包含。

### 6.7 验收

- 迁移的每个数据集 oracle 全等（含类型与键语义）；
- 阶段 0 基线与负向样本全部一致，身份断言通过；
- 受影响范围的测试零新增失败；
- `app.py` 行数下降（参考指标，不作为硬指标）。

## 7. 阶段 2：拆 `create_app`

- 目标：「读取 / 校验 / 投影」三模块 + `routes/`；`create_app` 只做装配（目标 < 300 行，参考值）。
- 顺序：`project_shared_selection` → `stage_workbench`（540 行）三段化 → HK 校验函数成组迁移 → 装配收敛。
- 写接口（`ensure` 两个）必须补隔离测试，证明拆分前后行为一致。
- 验收：路由清单测试、写接口隔离测试、基线一致。

## 8. 阶段 3：去 `globals()`

### 8.1 先证实，再动手

不预设"根因是循环导入"。第一步产出依赖图：

- 每个 `_*_parts` 目录里，被 `_v4_global` 读取的名字分类：
  **常量 / 函数 / 缓存 / 锁 / 实例状态**；
- 标出哪些引用可以在导入期解析，哪些必须运行期绑定；
- 记录测试对这些名字的 monkeypatch 依赖。

### 8.2 按分类选择改法

| 类别 | 改法 |
| --- | --- |
| 常量 | 移到 `_common.py`，正常导入 |
| 纯函数 | 正常导入 |
| 缓存 / 锁 | 显式模块级单例，随模块导入 |
| 实例状态 | 显式参数传入 |

### 8.3 批次与验收

按模块分批（preselection → infrastructure → stage_center → 其余），每批：
依赖图更新 → 改动 → 全量测试 → 基线一致 → `grep 'globals(),'` 计数下降。

最终验收：`globals(),` 为 0；导入图无环（新增 import-graph 测试）；
受影响范围的测试零新增失败。

## 9. 阶段 4：前端拆组件

- `ManagerSelectionView.vue` 按 tab 拆 6 个子组件 + 1 个组合式函数；
- `managerWorkspace.ts` 只保留 fetch 与类型导出，校验器抽到 contracts；
- 验收：单文件行数下降（参考）、vitest 全绿、`vue-tsc` **受影响文件零新增诊断**、build 成功、浏览器实测。

## 10. 交付与验收（收紧版）

### 10.1 固定命令与诊断集合

| 项 | 固定命令 | 判据 |
| --- | --- | --- |
| 后端测试 | `PANEL_PYTHON -B -m pytest -q -p no:cacheprovider --basetemp=<task bench>` | 失败集合 ⊆ 基线失败集合 |
| 前端测试 | `npx vitest run` | 全部通过 |
| 类型检查 | `npx vue-tsc --noEmit` | **受影响文件零新增**；整体错误集合与基线逐条比对（不仅比数量） |
| 构建 | `npx vite build` | 成功 |

### 10.2 发布基线

每个候选必须记录：

- 现役 `release-manifest.json` 的 SHA 与 `release_id`；
- 继承文件的 SHA（非本批修改）；
- 本批差异文件清单与前后 SHA。

不接受"从对应分支切出"作为基线声明。

### 10.3 节奏

- **每个 canary 小批次**：定向测试 + 该数据集 oracle + 受影响路由基线，不强制全量；
- **每个阶段候选**：全量测试 + 全量基线 + 一次独立 reviewer；
- 独立 reviewer 为只读身份，按项目 C 类规则。

### 10.4 独立验收与授权

部署是单独授权的动作；阶段结束停在"候选已在临时端口验证通过、等授权切换"。

## 11. 工作量估算（粗估）

| 阶段 | 工作量 | 可感知收益 |
| --- | --- | --- |
| 0 安全网 | 1–1.5 天 | 无（后续依赖） |
| 1 证据分离 | 2–3 天 | 逻辑与数据分开，`app.py` 大幅缩小 |
| 2 拆 create_app | 3–5 天 | 改阶段只碰小函数 |
| 3 去 globals | 2–4 天（含依赖图） | 能跳转、能静态检查 |
| 4 前端拆分 | 3–5 天 | 改 tab 不动大文件 |

## 12. 已决定的判断（供核对）

1. 先数据后结构；四阶段独立发布。
2. 数据文件放 `apps/api/v4_api/evidence/`，随 release 冻结；既有权威研究数据仍由原 owner 管理。
3. **不合并** `_parts` 目录；只恢复明确依赖与可测试边界。
4. 基线以"精确字段路径白名单 + 身份必过断言"为准，不用通配删除。
5. 数据迁移对象是"导入初始化后的最终值"，加载器不再执行初始化。
6. globals 改造前先产出依赖图，不预设循环导入。
