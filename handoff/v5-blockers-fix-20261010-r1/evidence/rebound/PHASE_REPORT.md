# 超跌 owner 身份误拒修复候选

日期：2026-10-10。基线：`lexi2016/v4@ebe5944ecfbec2f6a161793d7c11946dea063e57`。

## 结果

已在隔离候选中修复 `_verify_owner` 对正确冻结源码的 marshal 误拒。使用真实 `_HKLoader` 和原有 SHA 校验源码胶囊，在 **Linux CPython 3.14.6、原 uv.lock 依赖**下完成 RED → GREEN：原实现的干净 loader 测试以 `REPAIR_OWNER_FUNCTION_MODIFIED` 失败；修复后新增 18 项身份测试全部通过。

交接指定四模块实际运行 **81 项＝77 PASS＋4 SKIP**。四个 SKIP 均为原有显式 opt-in 未设置，实际解释器不是低于 Python 3.14。交接中的历史“新增 68＝66 PASS＋2 SKIP；加既有 13 后 81＝77 PASS＋4 SKIP”保留为历史记录；本轮执行日志独立保存。

全项目 unittest discovery 也已执行，结果为 **Ran 480 tests；failures=6、errors=19、skipped=5**，不能称全项目通过。随后在未修改的原基线、同一解释器及依赖环境下复跑所有失败模块，33 tests 得到完全相同的 6 个 FAIL 和 19 个 ERROR。逐项名称集合比较一致，见 `evidence/baseline-failure-comparison.json`。

Mac 原生环境、真实模型与私有 repair 发布／反读仍为 **NOT_RUN**。Linux 源码身份和合成行为结果不替代这些验收。

## 根因及最小改动

原 `src/v5_shadow/rebound_panel_repair.py` 的 `_verify_owner` 有两处直接比较 `marshal.dumps(code)`：原 owner 顶层函数、从冻结依赖导入的 Python helper。两处共同把序列化的引用编码差异当成函数修改。

在 CPython [v3.14.6 的 Python/marshal.c](https://github.com/python/cpython/blob/v3.14.6/Python/marshal.c) 中，`w_ref` 对 marshal 版本至少 3 使用 `_PyObject_IsUniquelyReferenced` 决定是否写入引用标志。额外保留一个非 interned docstring 引用即可改变输出字节，代码内容无需变化。官方 [marshal 文档](https://docs.python.org/3.14/library/marshal.html) 也把它定义为 CPython 内部序列化格式，而不是规范化代码身份。

本轮 stdlib 最小实验先记录序列化、再检查代码属性，避免先展开属性改变实验条件。在 Linux 3.14.6 上，原 predicate 的结果为：

| 状态 | `marshal` 字节相等 | 完整结构身份 |
|---|---:|---:|
| 尚未额外持有 reference code 的 docstring | False | True |
| 额外持有 docstring | True | True |
| 释放额外引用 | False | True |

完整实验记录在 `evidence/reference-state-probe-3.14.6.json`。该实验是本轮合成诊断，不冒充 ZIP 内的原 Mac 诊断文件。代码属性记录为 **18 个命名字段**。

生产代码只增加 `_same_code`，并用它替换上述两处 marshal 比较。结构包含以下全部字段：

| 类别 | 比较字段 |
|---|---|
| 参数及局部布局 | `co_argcount`、`co_posonlyargcount`、`co_kwonlyargcount`、`co_nlocals`、`co_stacksize`、`co_flags` |
| 可执行内容及嵌套内容 | `co_code`、`co_consts`、`co_names`、`co_varnames` |
| 源码及位置身份 | `co_filename`、`co_name`、`co_qualname`、`co_firstlineno`、`co_linetable`、`co_exceptiontable` |
| 闭包布局 | `co_freevars`、`co_cellvars` |

常量递归处理 code、tuple、frozenset、slice 及编译器标量；保留严格类型标签。因此 `1`、`True`、`1.0` 不会互相冒用。float/complex 用明确的二进制位表示，区分正负零和 NaN payload；frozenset 以排序后的结构序列消除迭代次序影响。未知类型、可变常量和递归异常 fail closed，不调用自定义常量的相等方法。

原 source SHA、函数命名空间／globals 归属、owner 文件路径、literal module constants、native `Struct` 类型／格式／尺寸检查仍在原路径执行。业务 repair、scale=1、价格／量单位、正式 admission、原始行保持、694 批量限制相关代码均未改动。

## 实测覆盖

新增 `tests/test_rebound_owner_identity.py`，共 18 个测试方法。源码 owner 测试在独立进程运行，先用未展开代码属性的真实冻结 loader 通过身份门，再做修改并断言拒绝；不 mock `_verify_owner`。

| 情况 | 实际结果 |
|---|---|
| 正确冻结 loader，检查代码属性之前 | PASS |
| owner docstring 引用持有／释放 | PASS |
| reference code docstring 引用持有／释放 | PASS |
| 替换 owner 函数 | `REPAIR_OWNER_FUNCTION_IDENTITY` |
| owner 函数换成复制的 globals 字典 | `REPAIR_OWNER_FUNCTION_IDENTITY` |
| 外层 `co_code` 不变、替换嵌套 code | `REPAIR_OWNER_FUNCTION_MODIFIED` |
| `co_code` 不变、改变常量 | `REPAIR_OWNER_FUNCTION_MODIFIED` |
| 导入 helper 替换为 callable 对象 | `REPAIR_OWNER_IMPORTED_HELPER_IDENTITY` |
| 导入 helper 的 code 被替换 | `REPAIR_OWNER_IMPORTED_HELPER_MODIFIED` |
| 导入 helper 使用复制的 globals 字典 | `REPAIR_OWNER_IMPORTED_GLOBALS` |
| 修改 literal module constant | `REPAIR_OWNER_CONSTANT_MODIFIED` |
| 修改 native Struct 的字节序而尺寸不变 | `REPAIR_OWNER_NATIVE_LAYOUT_MODIFIED` |
| 18 个代码字段逐项变动、嵌套常量、严格数值类型、正负零、NaN 位、未知常量 | 全部按预期接受或拒绝 |

这些测试检查可冻结代码结构及既有上下文门禁，不把 Python 进程内任意代码执行描述为安全沙箱。

## 执行环境与命令

完整环境记录：`evidence/environment.json`。

- 解释器：`/workspace/scratch/17ec887ca39d/runtime/v5-env/bin/python`，CPython 3.14.6，Linux x86_64，GIL build。
- 依赖：numpy 2.5.3、pandas 2.3.3、pyarrow 24.0.0；来自原锁文件。
- `uv.lock` SHA256：`7cb690f890cc28b6a79311f07e724f61c3dc4411494d480c0041f075f0825bfd`。
- `pyproject.toml` SHA256：`0a1824d3b255ee7f8391919254b2c21bf0deaf6da11a1b8cfc3e3a58c6fd4584`。
- 候选源码根：`/workspace/scratch/17ec887ca39d/work/rebound/V5`。
- 原始输入根：`/workspace/scratch/17ec887ca39d/input/sources/ebe5944e/V5`。

以下均在候选源码根运行，命令前缀为 `PYTHONPATH=src:tests /workspace/scratch/17ec887ca39d/runtime/v5-env/bin/python -B -m unittest`：

| 参数 | 实际结果 | 原始日志 |
|---|---|---|
| `test_rebound_owner_identity.FrozenOwnerIdentityTests.test_frozen_loader_passes_before_code_inspection -v`，修改生产前 | 1 FAIL，原错误码，退出 1 | `evidence/red-frozen-loader-locked.log` |
| `test_rebound_owner_identity -v` | 18 PASS，退出 0 | `evidence/green-owner-identity-locked.log` |
| `test_rebound_panel_repair test_rebound_raw_repair test_rebound_admission test_rebound_observation -v` | 81＝77 PASS＋4 SKIP，退出 0 | `evidence/rebound-four-modules-locked.log` |
| `discover -s tests -v` | Ran 480；6 FAIL、19 ERROR、5 SKIP，退出 1 | `evidence/full-discovery-locked.log` |

随后在原始输入根运行相同前缀，加参数：

```text
test_announcement_bridge test_manager_announcement_binding test_us_mapping_daily test_review_guards test_worker_pipeline -v
```

结果：Ran 33；6 FAIL、19 ERROR，退出 1。日志：`evidence/baseline-unrelated-failures-locked.log`。未更改测试要求、输入日期、环境门禁或相关 pins 来隐藏这些结果。

### 全项目未通过项

19 个 ERROR：

- `test_announcement_bridge.AnnouncementBridgeTests` 下 17 个测试均在 setup 因 `V5_ANNOUNCEMENT_REQUEST_PATH_REQUIRED_NO_SKIP` 失败。
- `test_manager_announcement_binding.ManagerAnnouncementRealOwnerTests.setUpClass` 同样缺公告 request 路径。
- `test_us_mapping_daily.UsMappingDailyTests.setUpClass` 因 `V5_US_MAPPING_REQUEST_PATH_REQUIRED_NO_SKIP` 失败。

6 个 FAIL 的完整名称：

```text
test_review_guards.ReviewGuardsTests.test_changed_input_not_reused
test_review_guards.ReviewGuardsTests.test_forged_input_digest_rejected
test_review_guards.ReviewGuardsTests.test_future_master_rejected
test_review_guards.ReviewGuardsTests.test_worker_ignores_timestamp_cached_old_source
test_worker_pipeline.WorkerPipelineTests.test_missing_input_saved_as_unknown
test_worker_pipeline.WorkerPipelineTests.test_worker_commit_readback_and_repeat_same_run
```

这六项的实际返回在预期业务验证前被 runtime 身份拒绝：`RUNTIME_MODULE_ID_UNVERIFIED`、`RUNTIME_RELEASE_ID_UNVERIFIED`，同时带 `INPUT_UNVERIFIED`。原基线重跑复现相同失败。

完整 25 个错误／失败名称、5 个 skip 原文和 warning 原文均列于 `evidence/full-discovery-summary.json`。全项目比指定四模块多一个 `V5_REBOUND_OWNER_ORIGINAL_TESTS` 未设导致的 skip；它也不是 Python 版本不足。

日志保留了 pandas 原 concat 行的两条 FutureWarning，以及 readonly HTTP 测试的 ResourceWarning。它们未被静音，也未被计为通过依据。

## 字节身份及交付增量

基线 515 个文件，候选 516 个文件：**1 个生产文件修改、1 个测试文件新增、514 个既有文件字节完全相同**。精确数据在 `evidence/changed-files.json`；可应用增量在 `rebound-owner-identity.patch`。

| 路径 | 修改前 SHA256 | 修改后 SHA256 |
|---|---|---|
| `V5/src/v5_shadow/rebound_panel_repair.py` | `1fa7d530b7b1fe7190a0e33990c82e0d26292a6c98f02d72dc942b455bd6ac94` | `8c912de834dfaebaa0a0973fbe015cf65d2326e06de2a0677918e00df5a696a8` |
| `V5/tests/test_rebound_owner_identity.py` | 新增 | `182ca1a555443f39b546838f724895b968b4b5ecebc13bc11e15cdf6f4cf00d6` |

由生产源码派生的身份也已计算，适用于这个隔离 ebe5944e 候选树：

| 派生身份 | 修改前 | 修改后 |
|---|---|---|
| `health.module_code_digest(src/v5_shadow)` | `4e2a6fb561aa63c9aa91b1d9f4cbb5adcb61ec794f9672fa705374a215f0f452` | `fc40b2fce9d98dead732224b31f2d3d8cf77a0906a26191f1f41a4a18b834596` |
| `sha256_json(rebound_observation._identity())` | `4773caa21851c7715ce8924d5a417cb61b40b25e097d9cc84cd49ffda78d2955` | `b2a0afd5cb206b10993af67e699bb060384e16ca8acc706f2cf432fb143ad82b` |

`rebound_observation._identity()` 动态读取 repair 源文件 SHA；其 map 只改变 `rebound_panel_repair.py` 这一项。全树搜索没有静态 manifest/capsule 固定该文件旧 SHA，所以没有刷新任何无关 pin。原 owner 文件仍为 `27da90f0e623e45fa1a27af7dcc3b6e5e1ff2320bae1c61bd903ed82050beb89`。

本轮输入是按原固定 ref 逐文件取得并校验的源码。未取得完整 ZIP，因此不声称整 ZIP 校验通过，也不声称读取了其中独立的 Mac trace、code-object diagnostic 或 docstring diagnostic。

## Mac 待验

1. 在 Mac 原 CPython 3.14.6、相同锁依赖中先运行新的 `test_rebound_owner_identity`。
2. 用原有显式 `V5_REBOUND_REPAIR_ORIGINAL_TESTS=1` 和 `V5_REBOUND_OBSERVATION_ORIGINAL_TESTS=1` 按原流程执行 owner 验收；既有装饰器和输入要求保持原样。
3. 使用 Mac 已有、真实批准的 `V5_REBOUND_REPAIR_REAL_INPUT`，在原测试建立的私有副本中发布 child 并反读，核对原 panel/pointer、模型、native capture、approval 文件字节不变。
4. 保留 scale=1、价格／量单位证明、正式 admission 限制及原业务边界；数值满足两门不代表正式准入，未放开 694 批量。

未推送 GitHub、未部署、未访问真实私有资产，未修改任何原 panel/pointer。
