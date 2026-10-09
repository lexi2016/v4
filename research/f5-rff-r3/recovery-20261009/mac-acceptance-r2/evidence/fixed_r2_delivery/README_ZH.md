# Issue #33 R2：收据文件 SHA 与事件 SHA 分开校验

本增量基于代码提交 `3764032a16f3cd9db88ec0d0ca122fd5d01c167b`，只处理 [Mac 补充反馈](https://github.com/lexi2016/v4/issues/33#issuecomment-6073492447) 确认的 P1。反馈证据固定提交为 `72f5526d4f1358b48d478f5c89a4641b879599de`。

R1 的 142 项合成测试在 Mac 全部通过，但真实 metadata-only prepare 被错误的 receipt pin 阻断。已有 Mac 合成验收保留为原范围内的证据；本次补齐正式固定值与原收据绑定的遗漏覆盖。R1 测试的 synthetic fixture 动态替换文件 PINS，未覆盖正式值与完整原收据字节之间的关系。

## 修复内容

`rff_saved_eval_contracts.py` 的 `PINS` 只保存完整文件的 SHA256。`candidate_start` 改为 `0292f37c00181b3447d0cda65f0b24096e9100ace35fb024ff5f579248e64a03`；`candidate_terminal` 改为 `c8dc367a7acf7196c4951074759e8c8015c071d6c2d7e6cf8b3afd3bf01f6ca1`。

独立的 `CANDIDATE_EVENT_SHA256` 保留原事件身份：start 为 `69a41b317075cfcb21c26133401e19b8af7a435185c87d5f4cf76f7b2e24d9af`，terminal 为 `5fe5704e4fb63a00e1802a14ba7e09f41985342a89e4f0c301793991b80ff0cf`。读取两份收据后，分别检查 `start_event_sha256` 与 `terminal_event_sha256`；原 `terminal.start_receipt_sha256 == metadata.candidate_start.sha256` 校验继续执行。

原 spec、binding、source、execution、route 和收据链校验仍保留。两个原始回执的 schema 实际为 XENDCG 命名，terminal 没有 route_id；本修复不为历史收据新增字段或强加另一种 schema。

所有其他运行文件、PR #5 accepted join、指标、门槛、worker/监控、登记生命周期和安全旗保持 R1 字节。真实 candidate/分数/Top3/旧binding/seal/registry 不属于此补丁。

## 交付目录

- `after/`：完整修改后文件和新增的冻结 metadata 测试输入，是应用在已验收 R1 代码目录副本上的增量；不是第二份完整 R1 运行目录。
- `patches/runtime.patch` / `patches/runtime.reverse.patch`：相对于代码根目录的最小正反补丁。
- `SOURCE_MAP_DELTA.json`：基准提交、修改文件的 before/after SHA、未改变的四个运行文件身份及 metadata 来源。
- `review/`：R1 两处错误的直接复现、针对性测试日志、独立复核和准确验收范围。
- `evidence/`：补充反馈及原始 JSON 元数据；没有真实 scores、truth、labels、模型或 registry 数据。

## 本次验证

R2 在 Linux Python 3.12.14 的最终全套合成测试为 **150/150 PASS（35.797 秒）**，CLI `--help` 为 PASS。150 项包含原 142 项及新增 8 项，不能与子集结果重复累计。测试作者的 contracts 模块记录为 **38/38 PASS**；新增 8 项的独立运行也通过。RED 日志对应修复前生产源码，之后只为测试补充两个常量映射不变断言；最终 38 项和 150 项均使用封版测试字节。

独立复核结论为 `PASS_PIN_FIX_STATIC_WITH_AUTHOR_LOG_REVIEW`：复核者未编写本次生产修复及回归测试，并核对了原始 metadata、完整源码 delta、固定常量回归和作者日志。该复核没有执行本机真实 prepare；主控整套测试结果单独记载。

本次唯一变化的生产文件为 `candidate/src/rff_saved_eval_contracts.py`（`+11/-2`）：

```text
before SHA256 = 35b9f88b8183f8980333bfe4e06f37b3ef3e2acbea7a0fc6904b1d130ef058b7
after  SHA256 = e41ab4b41c8386875b14515e34c7609e108db17b538ed43eebe7f76fc3394ba6
```

最终测试文件 SHA256 为 `95b1baa54699bd6a791f03f67a9f1f54acc98866783c16db0077ef8b429db4b6`。完整文件身份、补丁正反应用验证及日志记录见 `SOURCE_MAP_DELTA.json` 和 `review/VERIFICATION.json`。

## Mac 接续步骤

将下载包解压后，把下面 `RFF_FIX` 改成实际解压目录。原代码与阻断记录保留在 R1 目录；新代码使用 R2 目录。

```bash
RFF_FIX='/Users/lexi/Downloads/RFF_SAVED_EVALUATION_R2_RECEIPT_PIN_FIX'
RFF_OLD='/Users/lexi/Desktop/学习/因子工厂/handoffs/F5_RFF_SAVED_EVAL_R1_CODE_20261009'
RFF_CODE='/Users/lexi/Desktop/学习/因子工厂/handoffs/F5_RFF_SAVED_EVAL_R2_CODE_20261009'
RFF_PY='/Users/lexi/Documents/Codex/2026-08-13/factor-mining-mac/.venv-training-v1/bin/python'

if [ -e "$RFF_CODE" ]; then
  echo 'R2 code directory already exists; stop and inspect its identity.'
  exit 1
fi
cp -R "$RFF_OLD" "$RFF_CODE" || exit 1
cd "$RFF_CODE" || exit 1
shasum -a 256 -c "$RFF_FIX/patches/R1_SHA256SUMS.txt" || exit 1
RFF_PATCH_PREFIX="$(git rev-parse --show-prefix 2>/dev/null || true)"
git apply --directory="$RFF_PATCH_PREFIX" --check "$RFF_FIX/patches/runtime.patch" || exit 1
git apply --directory="$RFF_PATCH_PREFIX" "$RFF_FIX/patches/runtime.patch" || exit 1
shasum -a 256 -c "$RFF_FIX/patches/R2_SHA256SUMS.txt" || exit 1
"$RFF_PY" -B -m unittest discover -s candidate/tests -p 'test_rff_saved_eval_contracts.py' -v || exit 1
"$RFF_PY" -B candidate/src/run_rff_saved_evaluation.py --help || exit 1
```

新回归直接使用正式 PINS 与随包的原始收据字节，不能用 SyntheticPreparation.active() 替换掉它们。部分外围依赖为明确列出的合成元数据；它们不代表本机真实 prepare 已经通过。准确测试边界以 `review/VERIFICATION.json` 为准。

补丁命令显式带上当前 Git 子目录前缀，并在前后核对源码、测试与 accepted-worker 字节。这样即使代码目录位于父 Git 仓库内，也不会把“命令成功但补丁被跳过”误判为安装成功。独立目录及父仓库子目录两种场景的正反补丁均已实际验证，见 `review/PATCH_VERIFICATION.json`。

### 新 prepare 配置

以已接收的 `PREPARE_CONFIG_LOCAL.json`（SHA256 `d862b98076dff198572330628e5a559580f94f232b64dae7c0bb6333c72420e9`）为基础，创建一个新的配置，不覆盖原配置。只调整新的 recovery 根目录、evaluation execution ID 和新代码副本中的 accepted-worker 路径：

```text
recovery_root = /Users/lexi/Desktop/学习/因子工厂/handoffs/F5_RFF_SAVED_EVAL_R2_LOCAL_20261009
execution_id = F5_FULL64_RFF_LOGISTIC_R1_20260927_SAVED_EVAL_R2_20261009_01
accepted_worker_path = /Users/lexi/Desktop/学习/因子工厂/handoffs/F5_RFF_SAVED_EVAL_R2_CODE_20261009/inputs/attachments/rff/pr5_accepted/src/rff_worker.py
```

本机反馈中的明确资源配置为 `cpu_threads=4`、RSS 上限 `34359738368` 字节（32 GiB）、wall 上限 `3600` 秒、采样 `1` 秒；保留这份配置，不退回旧的 3 GiB/1800 秒默认值。新 execution ID 只是接续建议，prepare 仍会检查它未在当前真实 registry 使用。

包内 `examples/PREPARE_CONFIG_R2_LOCAL.example.json` 已按上述三项调整，并逐项保留原资源值；主控核对实际安装路径和新身份后，将其复制为 `$RFF_CODE/PREPARE_CONFIG_R2_LOCAL.json`。随后由本机主控调用一次修复后的 metadata-only prepare：

```bash
"$RFF_PY" -B "$RFF_CODE/candidate/src/run_rff_saved_evaluation.py" prepare \
  --config "$RFF_CODE/PREPARE_CONFIG_R2_LOCAL.json"
```

成功后应得到全新的 `contracts/RUN_SPEC.json` 与 `contracts/INPUT_BINDING.json`，状态 `PREPARED_UNSIGNED_REQUIRES_LOCAL_REVIEW_AND_PARENT_RELEASE`。核对 metadata 中 start/terminal 的 SHA 均为完整文件摘要；原事件字段及 terminal 到 start 文件的链分别通过验证。

代码 SHA 已变化，必须对实际新 spec/binding、代码和来源完成本机独立复核，再由主控形成新的 parent release。R1 的 142 PASS、此前的代码复核、这次远端回归均不替代新绑定验收。

遇到新错误，保留首次失败、路径与缺失工件，停止；不要修改旧收据、放宽SHA guard或反复执行同一prepare。这里没有调用真实run，也没有生成任何可用的review/release授权。

## 回滚

在 R2 代码目录执行：

```bash
cd "$RFF_CODE" || exit 1
RFF_PATCH_PREFIX="$(git rev-parse --show-prefix 2>/dev/null || true)"
git apply --directory="$RFF_PATCH_PREFIX" --check "$RFF_FIX/patches/runtime.reverse.patch" || exit 1
git apply --directory="$RFF_PATCH_PREFIX" "$RFF_FIX/patches/runtime.reverse.patch" || exit 1
shasum -a 256 -c "$RFF_FIX/patches/R1_SHA256SUMS.txt" || exit 1
```

反向补丁仅恢复 R2 副本里的 R1 源码/测试并移除这次新增的fixture；它不会使旧的pin错误变得可运行。因此回滚后停用该入口。若已生成新的spec/binding或发生真实执行，保留其授权、输出、trace和registry记录，不通过回滚代码删除证据或重置预算。

## 结论边界

本次只读了冻结源码和两份原始收据JSON元数据，并运行合成测试。没有连接Mac、读取真实评分/真值行、访问真实registry、训练、预测、模型加载或运行真实评价。原始receipt链一致；问题在于R1代码的哈希类别错误，不是旧材料损坏。真实命中率仍未计算，提升仍未验证。
