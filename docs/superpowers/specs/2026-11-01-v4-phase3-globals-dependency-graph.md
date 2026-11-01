# V4 阶段 3:`globals()` 依赖图(先证实)

- 日期:2026-11-01
- 状态:调查完成,**发现阻断项,未开始改造**
- 对应设计:§8「阶段 3:去 globals()」的 8.1「先证实,再动手」
- 范围:`apps/ domains/ infrastructure/ stage_center/ contracts/ ops/`(排除 `.venv`、`node_modules`、`tests`)

## 1. 结论摘要

| 项 | 数值 |
| --- | --- |
| `globals(),` 注入点 | **72**(与设计 §3.2 一致) |
| 传 `globals()` 的门面函数 | 56,分布在 4 个模块 |
| 能解析到实现模块的 | 38 个函数体 / 304 次名字读取 |
| **解析不到实现模块的** | **18 个函数体,指向 12 个不存在的文件** |

**阻断项**:`stage_center/runner.py` 和 `stage_center/raw_store.py` 里有 18 个门面函数,
惰性导入的 parts 模块在本分支和线上 API release 中**都不存在**。线上 API 进程一旦
调用这些函数就抛 `ModuleNotFoundError`。这不只是丑代码,是实际断链。

在补齐之前,对这两个模块做「去 globals」没有意义——没有实现体可改。

## 2. 机制

不是「函数读全局变量」那么简单,是一套门面/实现分离:

```
domains/preselection.py（门面）
    def date_catalog(store, *, current_date=None, ...):
        from domains._preselection_parts.date_catalog import _date_catalog_body as _v4_impl
        return _v4_impl(globals(), store, current_date=current_date, ...)
```

```
domains/_preselection_parts/date_catalog.py（实现）
    from ._namespace import read_global as _v4_global
    ...
    _v4_global(_v4_scope, 'OPTIONAL_DAILY_POOL_IDS')
```

`_v4_scope` 就是门面传进来的 `globals()`。`read_global`(`*_parts/_namespace.py`)
先查该 dict,再退回 `__builtins__`,查不到抛 `NameError`。

后果:实现在**运行期**才能确定门面里有哪些名字,静态分析、跳转、类型检查全部失效。
这正是设计 §1 里「编辑器能跳转、类型检查能覆盖真实缺陷」目标要解决的。

## 3. 名字分类(304 次读取)

| 类别 | 次数 | 占比 | 处理方向 |
| --- | --- | --- | --- |
| `import`(门面里 import 的名字,如 `Path`、`Mapping`) | 65 | 21% | parts 直接 import |
| `function`(门面里定义/转发的函数) | 54 | 18% | 真实依赖,需显式化 |
| `builtin`(`str`、`dict`、`len`、`isinstance`…) | **159** | **52%** | **完全不需要 globals** |
| `constant`(门面模块级常量) | 16 | 5% | 下沉到 `_common.py` |
| `class` | 10 | 3% | 同函数,显式化 |

最省力的一刀:**159 次 builtin 读取(52%)** 在 parts 模块里直接就能解析,
`read_global` 的回落分支现在在做本可以省掉的事。这批改动没有语义风险。

## 4. 按门面分布

| 门面 | 函数体 | 注入点 | 名字读取 | 类别构成 |
| --- | --- | --- | --- | --- |
| `domains/preselection.py` | 19 | 19 | 135 | builtin 77 / function 31 / import 21 / constant 6 |
| `stage_center/runner.py` | 7 | 7 | 82 | builtin 42 / import 24 / function 10 / class 6 |
| `apps/api/v4_api/research_lane_router.py` | 5 | 5 | 50 | builtin 28 / import 9 / function 7 / constant 6 |
| `stage_center/raw_store.py` | 7 | 7 | 37 | builtin 12 / import 11 / function 6 / class 4 |
| **合计** | **38** | **38** | **304** | |

`UNDEFINED` 名字:**0**。所有能解析的函数体,其读取的名字都在门面里确实存在——
说明当前能跑的部分没有名字拼写错误。

`dynamic` 读取(非字面量名字,如 `_v4_global(scope, some_expr)`):**0**。
所有门面-实现契约都是静态字面量,可以机械提取。

## 5. 阻断项证据

### 5.1 缺失的 parts 文件(12 个)

`stage_center/_runner_parts/`:分支 3 个文件,对照 release `a-stage-owner-compatibility-20261030-r2-stage` 有 14 个。缺:

```
a_candidate_authority.py   a_name_authority.py      configuration.py
hk_candidate_authority.py  row_evidence.py          runner_receipts.py
selection_input_validation.py  slot_execution.py    slot_idempotency.py
slot_lock.py               tick_planning.py
```

`stage_center/_raw_store_parts/`:缺 `transaction_publish.py`(分支 6,对照 7)。

### 5.2 依赖断裂的函数(18 个)

```
raw_store.py: publish_raw_artifact                    → _raw_store_parts.transaction_publish
runner.py:    lane_status_bundle, _atomic_json, _existing_binding_matches,
              _latest_entry, _read_verified_raw_source, _with_candidate_evidence,
              _project_raw_rows                        → _runner_parts.row_evidence
              build_production_config                  → _runner_parts.configuration
              _validate_formal_input, _formal_selection_codes, _find_exact_file,
              _validate_exact_selection_inputs, _selection_source
                                                       → _runner_parts.selection_input_validation
              _a_selector_name_map, _attach_a_name_authority
                                                       → _runner_parts.a_name_authority
              _attach_a_authority                      → _runner_parts.a_candidate_authority
              _attach_hk_authority                     → _runner_parts.hk_candidate_authority
```

### 5.3 实测

在分支工作树内:

```
importlib.import_module('stage_center._runner_parts.row_evidence')          → ModuleNotFoundError
importlib.import_module('stage_center._runner_parts.configuration')         → ModuleNotFoundError
importlib.import_module('stage_center._raw_store_parts.transaction_publish') → ModuleNotFoundError
```

在线上 API release(`candidates/perf-runtime-repair-20261101-r1/app`)内,同样三个全部失败。

### 5.4 影响面

- `build_production_config` 有真实调用方:`infrastructure/manual_collection.py`、
  `ops/run_stage_center_tick.py`、`ops/run_stage_center_nodes.py`。
- 但线上 stage 调度器(`com.lexi.stage-center.scheduler`)跑的是**另一个 release**
  `a-stage-owner-compatibility-20261030-r2-stage`,那个 release 的 `_runner_parts`
  是完整的 14 个文件,导入正常。
- 所以现状是:**调度链能用,API release 里这条路径是断的**——只要 API 进程走到
  `build_production_config` 或 `publish_raw_artifact`,就是 500。

### 5.5 可恢复来源

三个文件在 commit `2d1936518`(不在本分支祖先链上)中存在:

| 文件 | 行数 | 与 stage release 比对 |
| --- | --- | --- |
| `_runner_parts/configuration.py` | 37 | **完全相同**(sha 前缀 `bbf325df58b1`) |
| `_runner_parts/row_evidence.py` | 239 | 不同(git `8529d4961bcf` / stage `13ab48fa5429`),但读取的名字集合完全一致 |
| `_raw_store_parts/transaction_publish.py` | 278 | 未比对 |

**兼容性已逐个门面核实**(按函数体 AST 比对):

- `stage_center/runner.py`:两侧共 23 个 `_v4_impl` 门面函数,**22 个完全相同**。
  唯一差异是 `build_production_config` 少了可选参数 `hk_snapshot_shared_store_root`;
  而 `configuration.py` 里该参数默认 `None`,缺失不影响调用。
- `stage_center/raw_store.py`:7 个门面函数**全部完全相同**。

结论:从 `2d1936518` 恢复这 12 个 parts 文件与当前门面**部分**兼容。

> **本节结论已被 §9 修正。** 逐函数比对只能证明"委托函数一致",
> 不能证明 parts 依赖的模块级私有实现也在。实测恢复后仍有两处
> `NameError`,且分支的两个门面相对 `2d1936518` 是严格子集
> (`runner.py` 缺 9 个、`raw_store.py` 缺 42 个模块级定义)。


### 5.6 缺失之外的第二个断点

`row_evidence.py`(两个版本都是)读取 `HISTORICAL_OBSERVATION_CONTRACT_PREFIX`,
而这个名字**在任何门面里都不存在**——分支、stage release 都只有读取处,没有定义处。
即使按原样恢复文件,该代码路径仍然会 `NameError`。

这正说明 `globals()` 间接层的问题:静态分析看不见,只能靠运行期抛错发现;
而这一个至今没被发现,说明那条路径还没被跑到。

## 6. 建议批次(阻断项解决后)

| 批次 | 内容 | 判据 |
| --- | --- | --- |
| 0 | 补齐 12 个 parts 文件 + 让 18 个函数可用 | 三个 `import_module` 通过;`build_production_config` 实测可调用 |
| 1 | 去掉 159 次 builtin 读取 | 每批次 `grep -c '_v4_global(_v4_scope'` 下降;全量测试不变 |
| 2 | 65 个 `import` 类名字改为 parts 内直接 import | 同上;`globals()` 参数逐步改为按需 |
| 3 | 16 个常量下沉 `_common.py` | 常量类读取归零 |
| 4 | 54 函数 + 10 类显式化 | 按模块分批:preselection → raw_store → research_lane_router → runner |
| 5 | 移除 `globals()` 参数与 `read_global` | `grep -c 'globals(),'` == 0;新增导入环检测测试 |

每批仍按设计 §8.3:依赖图更新 → 改动 → 全量测试 → 基线一致 →
`grep 'globals(),'` 计数下降。

## 7. 测试 monkeypatch 依赖

设计 §8.1 要求先记录测试对这些名字的 monkeypatch 依赖。全量 `tests/` 扫描结果:

- 对四个门面命名空间(`domains.preselection`、`stage_center.runner`、
  `stage_center.raw_store`、`apps.api.v4_api.research_lane_router`)的直接
  `setattr` / `patch`:**0 处**。
- 唯一相关的一处是 `tests/test_v4_legacy_retirement.py` 打
  `domains._preselection_parts.source_validation._display_name_date_role`。
  该名字在同一个 parts 模块内被直接调用(`source_validation.py:124`),不经
  `_v4_global`,所以这个 patch 是有效的,不是静默失效。
- 另有若干 patch 打在无关对象上(`StageSelectionConsumer`、`repair`、`runtime`
  等),不构成约束。

**含义**:阶段 3 的搬迁不会被测试的 monkeypatch 绑死,这是好消息;
但也意味着搬迁如果改变行为,测试不一定抓得到——所以为什么基线比对不能省。

## 8. 复现

依赖图由一次性只读脚本生成,脚本不入库(AST 扫描门面函数的 `_v4_impl(globals(), ...)`
调用与 parts 模块的 `_v4_global(_v4_scope, '...')` 字面量)。
表 3、表 4 的数字可直接从该输出核对;`UNDEFINED` 与 `dynamic` 为 0 是硬断言。

## 9. 补齐尝试的实测结果(2026-11-01)

按 §5.5 的结论从 `2d1936518` 恢复了 12 个 parts 文件,**结论要修正**:
12 个文件本身不是完整的缺口。

### 9.1 恢复后能到什么程度

- 12 个模块全部可导入(`import_module` 无失败)。
- `build_production_config` 需要一处适配:`configuration.py` 把
  `hk_snapshot_shared_store_root` 传给 `RunnerConfig`,而本分支的 `RunnerConfig`
  没有该字段。去掉该参数后,调用成功并返回 `RunnerConfig`。
- `StageCenterRunner(config)` 可构造。
- `publish_raw_artifact` 仍然失败:`NameError: _allows_temporal_false_observation`。

### 9.2 根因:分支的两个门面是严格子集

按模块级名字比对(`2d1936518` 相对本分支):

| 文件 | 分支独有定义 | 2d1936518 独有定义 |
| --- | --- | --- |
| `stage_center/runner.py` | **0** | **9** |
| `stage_center/raw_store.py` | **0** | **42** |

`raw_store.py` 缺的 42 个里含 5 个大函数(180 / 126 / 67 / 48 / 36 行),
以及 `HK_FUTU_RTDATA_*` 等常量与 `TradingDayState`、`resolve_market_states` 的导入。

即:parts 是给**较新的门面**生成的,本分支的门面是较旧版本——
门面里的委托函数一致,但它们依赖的模块级私有实现没跟过来。

### 9.3 共有定义也不全同

| 文件 | 共有定义 | 完全相同 | 不同 |
| --- | --- | --- | --- |
| `runner.py` | 46 | 41 | `RunnerConfig`、`StageCenterRunner`、`build_production_config`、`_authorize_hk_0930_tdx_temporal_false_observation`、`_build_hk_stage_binding` |
| `raw_store.py` | 22 | 21 | `validate_rows` |

`RunnerConfig` 只差一个可选字段;`StageCenterRunner` 接口相同(10 个方法),
但实现体不同;`validate_rows` 的实现体不同。

### 9.4 因此有三条路

1. **选择性补齐**:只把 51 个缺失定义搬过来,保留本分支的 `RunnerConfig`、
   `StageCenterRunner`、`validate_rows` 实现。风险:parts 与这些旧实现从未一起跑过,
   每处不兼容都要逐个实测发现(已经发现 2 处)。
2. **整对采纳**:直接采用 `2d1936518` 的 `runner.py` + `raw_store.py` 全文再加 12 个
   parts。三者本是同一批生成的,自洽性最好;代价是 `RunnerConfig` 加回一个字段、
   `StageCenterRunner` 与 `validate_rows` 的实现升级——属于行为变更,需要单独验收。
3. **暂不补齐**:承认这两个模块在分支上是断的,阶段 3 先在
   `domains/preselection.py` 与 `apps/api/v4_api/research_lane_router.py`
   两个完整门面上做。

工作区现状:12 个 parts 文件已放入工作树,`configuration.py` 有上述一处改动;
全量测试仍 134 通过、1 个既有失败。**后续执行见 §10。**

## 10. 选择性补齐的执行结果(2026-11-01,已提交)

选定方案 1(选择性补齐),commit `3d4abc991`。

### 10.1 做了什么

- **12 个 parts 文件**从 `2d1936518` 恢复:11 个 `_runner_parts` + `transaction_publish.py`。
- **两个门面**以该提交的文件为底,但**保留本分支的 6 个定义**:
  `RunnerConfig`、`StageCenterRunner`、`build_production_config`、
  `validate_rows`、`_authorize_hk_0930_tdx_temporal_false_observation`、
  `_build_hk_stage_binding`。净增 51 个模块级定义。
- **`receipt_identity.py` 一并更新**:本分支这一版比门面旧,
  `validate_rows` 在本次改动**之前就已经是坏的**(门面传的关键字它的实现体不认)。
- **一处适配**:`configuration.py` 去掉 `hk_snapshot_shared_store_root`
  (本分支已退役的 `RunnerConfig` 字段)。

### 10.2 验证

| 项 | 结果 |
| --- | --- |
| `build_production_config(...)` | 返回 `RunnerConfig`,路径正确 |
| `StageCenterRunner(config)` | 构造成功 |
| `validate_rows([], ...)` | 返回 `(rows, cannot_confirm)` |
| `publish_raw_artifact(临时根, ...)` | 返回 dict |
| 57 处门面→实现委托签名 | **0 问题**(模块存在性 + 关键字 + 位置参数) |
| 全量测试 | **251 通过**,1 个既有失败(线上 plist 回执) |

`tests/test_stage_parts_contract.py` 把上述静态检查固化:任何一次
「实现模块不存在」或「门面传了实现不收的关键字」都会立即失败,
而不是等到运行期。

### 10.3 仍然存在的差异

`RunnerConfig` 少一个可选字段、`StageCenterRunner` 与 `validate_rows`
的实现体仍是本分支版本(与该提交不同但接口一致)。这是选择方案 1 的
既定取舍:保住现役行为,不把一次结构修复变成功能回迁。

## 11. 去 globals 的执行结果(2026-11-01,已提交)

| commit | 内容 |
| --- | --- |
| `e34dcd8c7` | 批次 1:746 处 builtin 读取改为直接引用 |
| `dfc027c0d` | 批次 2:287 处 import 类名字改为直接导入 |
| `1c8d4f148` | 批次 3-4:四个门面移除 `_v4_scope` 与 `globals()` |
| `8f70b8f55` | 另外两处仍有活调用方的注入点 |

### 11.1 现在的状态

| 指标 | 起点 | 现在 |
| --- | --- | --- |
| `_v4_scope` 引用 | 1,221 行 | **0** |
| `_v4_global` 读取 | 827 | **0** |
| `read_global` 引用 | 13 个 `_namespace.py` | **0** |
| `globals(),` | 72 | **1**(非注入,见下) |

76 个实现体去掉了 `_v4_scope` 参数,六个有实际调用关系的门面/调用方
不再传命名空间。所有 parts 模块改为正常 import。

`globals(),` 仅剩 `ops/run_v4_macos_scheduler.py:82`:那是
`FunctionType(code, globals(), ...)` 把 `_due` 模块的函数重新绑定到本模块命名空间,
属于另一套机制,不是门面→实现的注入;改动它等于重写调度器的绑定方式,不在本次范围。

### 11.2 期间发现并修掉的真实问题

1. **`preselection` 的运行期覆盖**。门面构造 `{**scope, "PreselectionPoolStore": _ResolvedPoolStore}`
   覆盖一个名字;机械替换会把它换回基类,静默改变行为。已改为显式参数 `pool_store_class`。
2. **`slot_execution.py` 的动态异常元组**。从元组里动态取 6 个异常类名,已改为字面量元组加导入。
3. **内部辅助函数的参数**。`_signature_supported_kwargs` 等辅助函数的首参数也被去掉,
   但文件内调用点还在传——会在运行期 `TypeError`/`NameError`。已逐处修正
   (`slot_execution.py` 6 处、`manual_quote_scope.py` 9 处、`market_freshness.py` 2 处)。
   这类问题测试覆盖不到,靠逐文件核对。

### 11.3 死代码清理

拆分中途留下了 13 个没有任何引用的 parts 模块(外加一个只含不可达函数的模块)。
按"没用的代码挪到待删除"处理:整目录归档到
`~/Desktop/待删除/v4-dead-parts-20261101/`(保持原路径),再从仓库移除。

删除前做了三重核对:全仓(含 `components/`、`research_panel_delta/`、`upstreams/`、`v4/`、`docs/`)
无名字引用、无 `getattr` 字符串取用、对应模块无导入方。
共移除 14 个死模块 + 12 个已无引用的 `_namespace.py`。

### 11.4 验收

- `tests/test_stage_parts_contract.py`:57 处委托的模块存在性与签名匹配、parts 可导入、
  无 builtin / import 类名字读取、无 `globals()` 传参、门面与 parts 无模块级环。**121 项**。
- 全量测试 **255 通过**,1 个既有失败(线上 plist 回执,与本次无关)。
- 12 个关键模块逐一 import 通过。
