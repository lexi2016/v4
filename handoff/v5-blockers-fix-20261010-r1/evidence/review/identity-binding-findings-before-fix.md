# 独立只读审查：超跌身份比较与原独审修订绑定

## 审查结论

- **A 超跌身份比较：在本次限定差异范围内，未发现需要修改的 Critical / Important / Minor 问题。** 新比较器保留完整代码结构比较，新增源码回归在指定 Linux CPython 3.14.6 下独立重跑 18/18 PASS。
- **B 修订绑定预检：发现 1 条 Important。** 原 reviewer 字段比较会接受类型变化，也会因 JSON 小数解析精度损失而漏掉实际数值变化，却输出 `original_reviewer_fields_unchanged=true` 和 `STRUCTURAL_BINDING_VERIFIED`。应在交付该结构保证前修复。
- 未发现此次增量直接授权 import、冒充原 reviewer 身份或绕过原 create 的情况。上述 B 问题的实际影响是错误的结构通过报告；`authorship_verified=false`、`authorizes_import=false` 仍然成立。

本报告记录的是**修复前原始 finding**。B 被审工具 SHA256 为 `aa2e16e9677688824efe985b75f4b3fc8be67b3ba561c1ee07c356c35231d1f1`。主任务已获通知；本报告不声称后续修复已完成或已独审通过。

## 范围与环境

交接约束来自 `/workspace/scratch/17ec887ca39d/input/REPRO_AND_ACCEPTANCE.md`，固定交接为 `46081f5bcfb5f0c9e63aaa8b2b7baf65ae191eff`。

| 增量 | before | after |
|---|---|---|
| A | `input/sources/ebe5944e/V5` | `work/rebound/V5` |
| B | `input/sources/e06d/bundle` | `work/revision/bundle` |

路径均相对于 `/workspace/scratch/17ec887ca39d`。测试解释器为 `/workspace/scratch/17ec887ca39d/runtime/v5-env/bin/python`，实际版本为 CPython 3.14.6，Linux x86_64；不属于 Mac 私有原 owner 验收。

独审没有修改任何候选文件，没有 GitHub 写入或部署。复现文件只写入本证据目录；运行期间的 reviewer 都有明确 synthetic 标识，并位于执行后自动删除的临时目录，未留下业务 reviewer 或真实 revision。

## Important B-1：原字段的类型或精确数值变化被误判为未变

### 位置

`work/revision/bundle/tools/review_revision_binding.py`：

- 第 107 行：`json.loads(raw, object_pairs_hook=unique)` 采用默认二进制浮点解析。
- 第 156–157 行：`returned[key] != value` 采用 Python 普通值比较。
- 第 162–163 行：比较漏检后输出结构通过并声称原字段未变。

### 可复现触发

合成原 reviewer 满足工具所检查的原合同，五项 `decision_revision` 字段保持正确，所有输入与返回文件 SHA 都正确固定。只修改原有字段后，实际 CLI 结果如下：

| 原有字段变化 | 返回状态 | 退出码 | 原字段未变声明 |
|---|---|---:|---|
| 嵌套对象 `false` → `0` | `STRUCTURAL_BINDING_VERIFIED` | 0 | `true` |
| 嵌套对象 `true` → `1` | `STRUCTURAL_BINDING_VERIFIED` | 0 | `true` |
| 顶层数值 `392` → `392.0` | `STRUCTURAL_BINDING_VERIFIED` | 0 | `true` |
| 列表中的嵌套对象 `false` → `0` | `STRUCTURAL_BINDING_VERIFIED` | 0 | `true` |
| JSON 小数 `9007199254740993.0` → `9007199254740992.0` | `STRUCTURAL_BINDING_VERIFIED` | 0 | `true` |
| 对照：`392` → `391` | `BLOCKED` | 2 | 无 |

每个案例执行前后全部输入文件 SHA 一致。所有案例的 `authorship_verified`、`authorizes_import` 均保持 `false`。

前四项来自 Python 对布尔值、整数、浮点数的宽松数值相等语义，该语义还会递归传播到列表和字典。第五项更早发生在 JSON 解析阶段：两个不同的十进制 JSON 数字被解析为同一个二进制 float；仅给已解析值增加 `type(a) is type(b)` 仍无法检测这种变化。

### 后果与范围

这违反本工具和交接说明对“保留所有既有 reviewer 字段原值”的承诺。调用方会得到退出 0 和明确的“原字段未变”声明，虽然输入结构或数值已经变化。

这是新增预检工具的结构保证缺陷，并不证明本批真实原 reviewer 包含某个合成字段，也不证明任何真实返回文件已经被修改。本次未获得真实原 reviewer 字节。五项绑定本身均是经过格式验证的字符串，因此本复现没有绕过精确五字段绑定；原 create 仍未改动，且预检没有调用 create/import。

### 最小修复建议

1. 原字段比较改为递归的类型严格 JSON 值比较；字典检查相同 key 集合，列表检查长度和逐项值，布尔值、整数与小数类型区分处理。
2. JSON 小数采用无损解析，例如 `Decimal`，避免在比较前丢失十进制原值；不要仅在默认 float 结果上增加类型判断。
3. 新回归至少覆盖顶层及嵌套布尔值与整数互换、整数与小数互换、不同小数舍入为同一 float 的情形；上述变化应返回 `ORIGINAL_REVIEW_FIELDS_CHANGED`、`BLOCKED` 和退出 2，同时保留全部 false 权限标志及零写入验证。

附带的实际观察：返回文件新增 `NaN` 来源字段也会结构通过。可在同一 JSON 严格处理修改中拒绝非标准常量，并检测非有限解析数值；不把此观察另列为第二条阻断问题。

### 证据与执行方法

- 复现脚本：`evidence/review_identity_binding/reproduce_field_type_drift.py`
- 逐案例结果：`evidence/review_identity_binding/field-type-drift-results.json`

```sh
/workspace/scratch/17ec887ca39d/runtime/v5-env/bin/python -I -B \
  /workspace/scratch/17ec887ca39d/evidence/review_identity_binding/reproduce_field_type_drift.py
```

脚本可重跑；它调用真实候选 CLI，写合成临时输入并比较执行前后文件摘要，最后删除这些临时输入。证据 JSON 固定被执行候选的 SHA，便于区分修复前后的结果。

## A：比较器与回归审查

`_same_code` 比较指定 18 个公开不可变 code 字段，包含递归 `co_consts`、嵌套 code、名称/变量/闭包字段、文件与行号、行表与异常表；不是只比较 `co_code`。不同标量类型带不同类型标记，float/complex 按位比较，元组、frozenset 和 slice 递归比较。未知或可变常量失败关闭。

冻结 owner 自身函数及导入 helper 的两处 marshal 字节比较都已替换；原函数 globals 对象身份、源码 SHA、模块常量与 native struct 布局门禁仍在原位置。

新测试在子进程先调用实际冻结 loader 和 `_verify_owner`，然后才展开 code 属性，因此能检测本次原始干净加载失败。持有/释放 docstring 引用、替换函数、嵌套 code、函数常量、导入 callable/helper、复制 globals、模块常量与 native 布局等场景有实际调用验证。完整 18 字段逐项变化及嵌套常量测试与本次风险相关。

独审实际执行：

```sh
cd /workspace/scratch/17ec887ca39d/work/rebound/V5
PYTHONPATH=src:tests /workspace/scratch/17ec887ca39d/runtime/v5-env/bin/python \
  -B -m unittest test_rebound_owner_identity -v
```

结果：18 tests，OK，无 SKIP。

独审还核对已有日志：原四模块为 **81 tests = 77 PASS + 4 SKIP**；全发现为 480 tests、6 FAIL、19 ERROR、5 SKIP。原基线同失败模块的 33 tests 重现相同 6 FAIL 和 19 ERROR，名称集合比对相同。因此不能声称 81 项全 PASS，也不能声称全项目通过。Mac 原模型/私有 repair 发布 child、反读、原 panel/pointer 不变的真实验收仍为未执行。

## B：其他核准点与测试覆盖

独审实际按文件独立重跑了 `tests/test_revision_review_tool.py` 的 12 项与 `tests/test_revision_review_gate.py` 的 8 项，均通过。后者调用真实原 create 与父证据验证，在写文件、建目录、kernel lock 等变更边界设置断言，并比较输入目录和文件字节；它真实覆盖缺绑定等情况在写入前拒绝。前者对原字段改变的测试只覆盖字符串差异，未覆盖 B-1 的数值/类型风险，所以 20 项通过不能排除本 finding。

工具只读文件并核对固定 SHA；拒绝普通 symlink 和非普通文件，限制单文件读取量，检查重复 JSON key。对 semantic/decisions 只证明所期待文件字节，逻辑摘要与逐篇业务门禁仍交给原 owner。所有报告明确不验证作者身份、不进行语义审查、不授权导入。文档也明确区分请求文件、原独审实际返回文件及真实通道来源，未把自报 reviewer 名称当成作者证明。

## 差异隔离复核

独审重新读取 before/after 文件字节进行 SHA256 比较，结果保存于 `evidence/review_identity_binding/source-diff-summary.json`：

- A：515 个原文件，只有 `src/v5_shadow/rebound_panel_repair.py` 变化；仅新增 `tests/test_rebound_owner_identity.py`，没有删除原文件。
- B：64 个原文件全部字节相同；仅新增指定工具、两个测试和交接说明，共 4 个文件，没有删除原文件。

上述差异和 B finding 均以原始独审时点为准。后续修复与验证由主任务另行记录。
