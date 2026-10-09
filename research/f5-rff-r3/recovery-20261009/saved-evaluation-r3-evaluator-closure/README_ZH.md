# Issue #33 R3：补齐 evaluator 代码与配置依赖，并在启动前预检

本修复基于已经在 Mac 完成 **38/38 PASS、一次 metadata-only prepare 成功**的 R2 `4be3c657c04cb3431d19a83cf584bdb2a0481dac`。该验收事实保留。本包只处理 [最新 P1 反馈](https://github.com/lexi2016/v4/issues/33#issuecomment-6074178999)，反馈工件固定在提交 `cd1a080c13f1b1849d4b882b587b374dd948e5c8`。

R3 新增 **23/23 针对性测试通过**：依赖闭包 14 项，启动前拦截 9 项。受本次改动影响的 contracts 38 项与 worker 22 项也在 R3 上通过。本次未重新安装或验收同一 R2。远端验证环境为 Linux Python 3.12.14；真实 Mac 上的 R3 prepare、配置加载和新绑定验收仍待本机主控执行。

## 修复了什么

`prepare` 和 `load_documents` 现在绑定、复核完整的冻结 evaluator 依赖：

| 类别 | Binding 名称 | 冻结包内路径 |
| --- | --- | --- |
| 原有模块 | `frozen_package_init` | `spike5/__init__.py` |
| 原有模块 | `frozen_settings` | `spike5/settings.py` |
| 原有模块 | `frozen_metrics` | `spike5/metrics.py` |
| 新补模块 | `frozen_common` | `spike5/common.py` |
| 新补模块 | `frozen_features` | `spike5/features.py` |
| 新补配置 | `frozen_base_features` | `config/base_features.json` |
| 新补配置 | `frozen_contract` | `config/contract.json` |
| 历史身份依据 | `frozen_evaluator_manifest` | R3 代码目录中的 `candidate/contracts/FROZEN_EVALUATOR_SOURCE_MANIFEST.json` |

所有七项源文件与配置均要求历史 SHA256、完整字节数和指定位置同时一致。原 score-aware wrapper 固定的真实 metrics 路径仍由已有校验限制；临时目录重定位只用于合成测试。新增两个模块没有扩大为任意目录白名单：允许运行的包模块名及其逐项文件身份均为固定集合。

worker 先检查完整依赖及现有 `spike5` 缓存，再按原始依赖顺序编译已验证字节。`common`、`features` 在原 `settings.py` 执行前显式载入。`settings.py` 的两次 JSON 读取限定到两条已绑定路径，使用校验过的文件字节和原 JSON 语义；`common.read_json` 随后恢复原函数。每个模块缓存同时检查文件路径、`__spec__.origin`、完整源码摘要，以及包含五模块、两配置和历史清单身份的整体摘要。未绑定模块、半套缓存和不同依赖身份的缓存会被拒绝。

runner 在 native 文件验证之后、任何官方 guard/adapter 的加载与创建之前，调用同一个 worker evaluator loader 作 source/config-only preflight。其后的临近 claim 来源复核与 child 中的加载校验继续执行。因此本问题所涉及的依赖错误在新 `RUN_STARTED` 之前即可失败。真实评价执行期的既有故障处理与资源限制继续适用。

生产修改仅涉及 `rff_saved_eval_contracts.py`、`rff_saved_eval_worker.py` 和 runner；runner 只新增两行接线。`rff_saved_eval_frames.py`、registration、PR #5 accepted join、原 score-aware wrapper、原七份 evaluator 源码/配置及 R2 的文件/事件哈希区别均保留。未新增动态 import-graph 引擎；完整历史 SHA 固定的是已经逐项审查过的依赖图。

## 历史身份如何确认

反馈中的四项缺失身份起初标为 `CANNOT_CONFIRM`。本次找到了独立保存的历史 `MAC_FIXED_SOURCE_MANIFEST.json` 和 `MAC_FIXED_PACKAGE_IDENTITY_RECEIPT.json`。恢复后的清单为 **19131 bytes**，完整 SHA256：

```text
64fd0f7a5e3d646f7b5b184d44ca10576aab9db73772b3abb2cfceab36862a9b
```

这两项同时与历史包身份回执中记录的清单身份匹配。六份反馈源码/配置逐字匹配该历史清单。22-byte `__init__.py` 的版本声明候选经完整 SHA 和字节数核对恢复；这不是一次本机文件读取。R3 在 Mac 上仍会核验实际原包的全部七项文件，补丁不向实际冻结包写入替代文件。

清单对应的是历史 **Mac-fixed** 包 `aaf9d39e…`，与原提交 ZIP `fa107fd9…` 有明确区别。`config/contract.json` 使用清单和历史回执记录的 metadata amendment `HK_SPIKE_F5_INPUT_METADATA_R1_20260914`，SHA 为 `17ecffd1…`，没有回退到原提交的 `d610fc60…`。

来源恢复的边界也记录在包内：清单文本读取少一个末尾 LF，补上唯一 LF 后完整 SHA 和大小与独立旧回执同时命中；身份回执附的是读取到的文本，未声称其 5826 字节等于原始 5827-byte 文件。历史完整 ZIP 字节未在本轮成功取得或重算，所需七项依赖通过历史清单逐项认证。详细记录见 `review/HISTORICAL_IDENTITY_PROVENANCE.md`、`evidence/historical/` 和 fixture 说明。

## 交付与验证

- `after/` 提供三个生产修改文件、两个受影响测试修改文件及所有新增文件的完整内容；这是在已验收 R2 代码副本上应用的增量。
- `before/` 保留五个修改前文件。`patches/runtime.patch` 和 `runtime.reverse.patch` 可正反应用。
- `SOURCE_MAP_DELTA.json` 记录基准提交、所有变更前后 SHA256、Git blob 身份、保留文件及来源关系。
- `review/VERIFICATION.json`、原始日志和独立复核记录说明通过范围；合成测试不会被写作真实 Mac 验收。
- `patches/R2_SHA256SUMS.txt` 与 `R3_SHA256SUMS.txt` 核对代码、测试、冻结 fixture 和 accepted worker。补丁已在独立目录及父 Git 仓库内的中文/空格子目录验证正向应用、反向恢复和全部字节一致。

测试结果分组如下，四组不重叠：

| R3 验证范围 | 测试数 | 结果 |
| --- | ---: | --- |
| 新 evaluator 历史依赖/实际加载/缓存测试 | 14 | PASS |
| 新 runner 启动前集成测试 | 9 | PASS |
| 受影响 contracts 模块回归 | 38 | PASS |
| 受影响 worker 模块回归 | 22 | PASS |

新测试直接使用原历史七份文件，不修改正式 `PINS`；合成重定位仅临时调整已验证 score-aware wrapper 实例的两个绝对路径属性。启动前测试走真实 `_run_real`、bound worker 和实际 preflight，外围只替换 metadata/release/native 接口，并在首次官方 helper 加载前主动停止。它检查失败发生在 owner/monitor 和任何登记动作之前。真实指标函数没有调用，真实分数、标签、真值、模型和 registry 没有打开。

修复前 RED 与修复后 GREEN 日志均保留。初次受影响旧测试中四处预期发生变化，均为更早的身份/路径拒绝；只调整完整历史 fixture 和准确错误预期，没有放宽生产校验。独立复核者未编写生产代码或测试，复核源码、来源证据和执行日志；本包的复核不是本机 parent release。

## Mac 接续：只验收新 R3

由本机主控 Luna Max 使用已验收 R2 目录作为只读基线。将 `RFF_FIX` 指向本包实际解压目录。以下复制的是新的 R3 工作副本，不重新安装 R2，也不改动 R2 已生成的 spec/binding/回执。

```bash
RFF_FIX='/Users/lexi/Downloads/RFF_SAVED_EVALUATION_R3_EVALUATOR_CLOSURE_FIX'
RFF_OLD='/Users/lexi/Desktop/学习/因子工厂/handoffs/F5_RFF_SAVED_EVAL_R2_CODE_20261009'
RFF_CODE='/Users/lexi/Desktop/学习/因子工厂/handoffs/F5_RFF_SAVED_EVAL_R3_CODE_20261009'
RFF_RECOVERY='/Users/lexi/Desktop/学习/因子工厂/handoffs/F5_RFF_SAVED_EVAL_R3_LOCAL_20261009'
RFF_PY='/Users/lexi/Documents/Codex/2026-08-13/factor-mining-mac/.venv-training-v1/bin/python'

if [ -e "$RFF_CODE" ] || [ -e "$RFF_RECOVERY" ]; then
  echo 'R3 destination exists; stop and inspect the first attempt.'
  exit 1
fi
cp -R "$RFF_OLD" "$RFF_CODE" || exit 1
cd "$RFF_CODE" || exit 1
shasum -a 256 -c "$RFF_FIX/patches/R2_SHA256SUMS.txt" || exit 1
RFF_PATCH_PREFIX="$(git rev-parse --show-prefix 2>/dev/null || true)"
git apply --directory="$RFF_PATCH_PREFIX" --check "$RFF_FIX/patches/runtime.patch" || exit 1
git apply --directory="$RFF_PATCH_PREFIX" "$RFF_FIX/patches/runtime.patch" || exit 1
shasum -a 256 -c "$RFF_FIX/patches/R3_SHA256SUMS.txt" || exit 1
"$RFF_PY" -B -m unittest discover -s candidate/tests -p 'test_rff_evaluator_*.py' -v || exit 1
```

这条测试命令应运行新增 23 项。已完成的 R2 38/38 验收不用再跑。新测试只处理新缺口，测试结果不等于实际绑定已经获准评价。

### 一次新 prepare 与一次来源/配置预检

包内 `examples/PREPARE_CONFIG_R3_LOCAL.example.json` 直接继承反馈中已成功的 R2 配置，只更改新的 `recovery_root`、`execution_id` 和新副本中的 `accepted_worker_path`。保留原 `project_root`、candidate binding 和真实 frozen metrics 路径。资源仍为 **4 threads、32 GiB RSS、3600 秒 wall、1 秒采样**。

确认这三个新路径/身份与本机实际一致后，建立新配置并只调用一次 prepare：

```bash
if [ -e "$RFF_CODE/PREPARE_CONFIG_R3_LOCAL.json" ]; then
  echo 'R3 prepare config exists; stop and inspect its identity.'
  exit 1
fi
cp "$RFF_FIX/examples/PREPARE_CONFIG_R3_LOCAL.example.json" \
   "$RFF_CODE/PREPARE_CONFIG_R3_LOCAL.json" || exit 1
"$RFF_PY" -B "$RFF_CODE/candidate/src/run_rff_saved_evaluation.py" prepare \
  --config "$RFF_CODE/PREPARE_CONFIG_R3_LOCAL.json" || exit 1
```

期望产生新 spec/binding，状态为 `PREPARED_UNSIGNED_REQUIRES_LOCAL_REVIEW_AND_PARENT_RELEASE`。检查 `executable_helpers` 共 9 项，`metadata_files` 共 12 项，其中包含上表的完整 evaluator 闭包。start/terminal 仍使用完整收据文件 SHA，原事件身份及收据链单独验证。

随后可在同一冻结 Python 的新进程中调用仅代码/配置预检，验证实际 Mac 路径中的原包导入，不创建 parent release 或 `RUN_STARTED`：

```bash
"$RFF_PY" -B - "$RFF_CODE/candidate/src" "$RFF_RECOVERY" <<'PY' || exit 1
import json
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])
import rff_saved_eval_contracts as common

recovery = Path(sys.argv[2])
_, binding, _, _ = common.load_documents(
    recovery / 'contracts/RUN_SPEC.json', recovery / 'contracts/INPUT_BINDING.json')
worker = common.load_bound_module(binding['code_files']['rff_saved_eval_worker'],
                                  '_rff_saved_evaluator_preflight')
print(json.dumps(worker.preflight_evaluators(common, binding), ensure_ascii=False))
PY
```

期望状态 `PASS_FROZEN_EVALUATOR_CODE_AND_CONFIG` 与完整 `closure_sha256`。保存首次输出及退出码；任一步失败即保留首次证据并停止，不更改历史文件、改写配置摘要、删除缓存后反复重试或放宽 guard。

之后对实际新代码、来源清单、spec/binding、资源和当前登记前缀完成本机独立复核。由本机主控按已有流程形成针对新身份的 release，才进入一次保存分数评价。runner 自身在正式启动前仍会执行同一预检；手动预检不替代这一检查。本包未签发 release，也不提供自动真实 run 命令。

## 回退

回退只操作新 R3 代码副本：

```bash
cd "$RFF_CODE" || exit 1
shasum -a 256 -c "$RFF_FIX/patches/R3_SHA256SUMS.txt" || exit 1
RFF_PATCH_PREFIX="$(git rev-parse --show-prefix 2>/dev/null || true)"
git apply --directory="$RFF_PATCH_PREFIX" --check "$RFF_FIX/patches/runtime.reverse.patch" || exit 1
git apply --directory="$RFF_PATCH_PREFIX" "$RFF_FIX/patches/runtime.reverse.patch" || exit 1
shasum -a 256 -c "$RFF_FIX/patches/R2_SHA256SUMS.txt" || exit 1
```

这会恢复三个生产和两个测试文件，并移除 R3 新增代码清单与 fixture。恢复后的 R2 仍有本次依赖阻断，不能借回退继续真实评价。新 prepare 或后续执行产生的任何 spec/binding/review/release/输出/trace/registry 证据均应保留；源码回退不重置执行身份或预算。

## 结论范围

本次交付的是针对依赖缺口的新源码修复和可复核的软件验证结果。没有新增训练、预测、模型加载、真实分数或真值读取、登记追加或真实评价。**真实命中率尚未产出，提升仍未验证。**
