# Issue #33：RFF 已保存分数评价入口

本修复新增一个独立、零训练/预测的 saved-evaluation 入口。入口直接消费旧候选保存的 `CANDIDATE_SCORES.csv.gz` 和 `CANDIDATE_TOP3.csv.gz`，复用 PR #5 accepted worker 中的 `_join_truth`，然后组合原 score-aware 与 binary evaluator。代码交付和合成验收不代表真实命中率已有提升。

基准提交：`4c5fb40122cec7a40036bfda5e4d9516d82dcd18`。范围来自 [Issue #33](https://github.com/lexi2016/v4/issues/33) 与其固定问题包。所有新增内容位于 `research/f5-rff-r3/` 下；历史文件没有覆盖式修改。

## 1. 文件与运行方式

五个运行文件全部位于 `candidate/src/`：

| 文件 | 职责 |
| --- | --- |
| `rff_saved_eval_contracts.py` | 只读源码和 JSON 元数据，准备/校验新 spec、binding、本机 review 与 parent release；不会在 prepare 期间打开分数、Top3、模型或评价 truth 的数据行。 |
| `rff_saved_eval_worker.py` | 在已登记的 start 后核对原生环境，读取已固定的文件快照，记录 truth 解码尝试与完成次数，写指标和逐层收据。 |
| `rff_saved_eval_frames.py` | 调用已验收 join 和原 evaluator；保留保存的候选 Top3 与原概率指标，计算两个控制比较。 |
| `rff_saved_eval_registration.py` | 在原 official adapter/guard/builder/validator 上增加 RFF 路线约束，保留旧 registry 前缀及 fit debit。 |
| `run_rff_saved_evaluation.py` | 提供 `prepare`/`run` CLI，串起单次启动、进程树监控、结果核验及单次 terminal。 |

`inputs/` 只包含问题包中的源码/元数据及固定提交上的参考源码，供合成测试和身份核对使用。`candidate/tests/` 只使用临时生成的分数、标签、合同、registry 和进程目标。没有加入真实 scores、truth、模型、行情或真实 registry。

## 2. 保留的研究定义

- 旧候选执行固定为 `F5_FULL64_RFF_LOGISTIC_R1_20260927_RESUME_20260928_01`；旧 fit=1、predict=1、truth decode=1 不重置。
- join 固定复用 PR #5 accepted worker，SHA256 为 `3ea10757a81207147e5cfb9e68e69750a0579786153e7ce58ccf342a3184058c`。只调用其 `_join_truth`，没有抽取、复制或新建第二条 join 规则，没有调用 candidate CLI。
- 保留 2024 年 169,986 个 grid rows、120,084 个 scoreable rows、246 个 sessions、738 个 selection slots 与 126 个 confirmed NEW episodes。126 是原 helper 的 episode 分母，不是 `y == 1` 的行数。
- PLUS 比较使用 paired lower `> 0`；BASE34 使用 paired lower `>= 0.03`。原 promotion gates 和成本来源仍由原冻结 contract/evaluator 决定。
- 原 RFF `probability` 块保留保存概率上的 Brier、logloss、calibration 与 probability AP；raw-margin AP 单列为 ranking diagnostic。两者在 sigmoid 有限精度 ties 时不保证数值相同。
- `research_only=true`；`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。即使两个 development gates 通过，证据上限和最终 evidence status 仍为 `DIRECTION_ONLY`。

## 3. 准确本机步骤

### A. 安装完整 after 文件并运行合成验收

将修复包的完整 `after/` 内容放到一个尚不存在的新目录：

```text
/Users/lexi/Desktop/学习/因子工厂/handoffs/F5_RFF_SAVED_EVAL_R1_CODE_20261009
```

不要把这组新增文件覆盖到旧 candidate 输出目录，也不要替换旧 worker 或旧绑定。随后使用已冻结的原 RFF Python：

```bash
RFF_CODE='/Users/lexi/Desktop/学习/因子工厂/handoffs/F5_RFF_SAVED_EVAL_R1_CODE_20261009'
RFF_PY='/Users/lexi/Documents/Codex/2026-08-13/factor-mining-mac/.venv-training-v1/bin/python'
cd "$RFF_CODE"
"$RFF_PY" -B -m unittest discover -s candidate/tests -p 'test_*.py' -v
"$RFF_PY" -B candidate/src/run_rff_saved_evaluation.py --help
```

合成测试不重跑 PR #5 原来的 29 个 join tests。它们验证新保存文件入口和组合行为；部分 native/evaluator 路径和 RSS 观测为明确的合成替身，具体见验收报告。无需安装、升级或重建依赖；如现有冻结 Python 缺少依赖，记录确切错误并停止，不在研究运行中修环境。

### B. 本机主控准备新配置

以 `examples/PREPARE_CONFIG.example.json` 为结构，创建新的 `PREPARE_CONFIG_LOCAL.json`。示例中路径对应上面的代码目录；如果实际安装位置不同，只修改新配置中的 `accepted_worker_path` 为相应副本路径，SHA 仍必须匹配 accepted worker。

资源四项必须由本机主控明确填写并冻结。示例故意使用 `null`，不会静默沿用历史 4 线程/3 GiB/1800 秒。附件中 `resource_tree.py` 的现有接口只接受 `cpu_threads=4`；如本机批准的线程配置不是 4，本入口会在 RUN_STARTED 前报 `PACKAGED_MONITOR_THREAD_PROFILE_UNSUPPORTED_REQUIRES_EXPLICIT_4`，不会自行改值。RSS、wall 与采样间隔也必须是明确正数，采样间隔不能超过 wall 上限。

本包给出的 evaluation execution ID 是待本机冻结的建议值，未在真实 registry 登记。如果本机已使用该 ID，停止并由主控重新确定新身份与新 recovery 根目录；没有自动加序号或重试。

```bash
"$RFF_PY" -B candidate/src/run_rff_saved_evaluation.py prepare \
  --config "$RFF_CODE/PREPARE_CONFIG_LOCAL.json"
```

成功时仅生成新 recovery 目录中的 `contracts/RUN_SPEC.json` 与 `contracts/INPUT_BINDING.json`，输出 `PREPARED_UNSIGNED_REQUIRES_LOCAL_REVIEW_AND_PARENT_RELEASE`。prepare 会核对源码和 JSON 元数据，并读取当前 registry 前缀来固定身份；不会 append registry，不会启动 worker，也不会读取真实数据行。

若 old binding、seal、原控制 SHA、native helper/reference、official helpers、policy 或原冻结 evaluator 路径不符，prepare 会给出具体错误并停止。不要改旧 binding、门槛或原工件来消除错误。

### C. 新绑定的本机独立验收与 release

本机 Reviewer 需核对**实际生成**的 spec/binding、五个运行源码、accepted worker、原 evaluator 及同包 `settings.py`/`__init__.py`、official append policy、当前 registry 前缀和已明确的资源限制，再填写新的 `contracts/INDEPENDENT_LOCAL_REVIEW.json`。

本机主控随后按该 review 和实际文件 SHA 形成 `contracts/PARENT_RELEASE.json`。文件结构见 `examples/LOCAL_REVIEW.example.json` 与 `examples/PARENT_RELEASE.example.json`。示例均为 PENDING/inactive，占位摘要不可执行；CLI 不提供签发 PASS 或激活 release 的命令。旧 PR #5 PASS、问题包 PASS 和本包的远程代码复核均不能替代这次本机绑定验收。

`code_sha256` 是包含本机绝对路径的五文件 manifest SHA；它与单文件 SHA 或本交付包摘要不是同一个值。spec、binding、review、release 必须引用同一批本机生成的精确身份。prepare 后源码/元数据/授权或 registry 前缀变化会阻止启动。

### D. 本机主控放行后执行一次

只有新的本机 review/release 已通过，才由本机主控执行：

```bash
RFF_RECOVERY='/Users/lexi/Desktop/学习/因子工厂/handoffs/F5_RFF_SAVED_EVAL_R1_LOCAL_20261009'
"$RFF_PY" -B "$RFF_CODE/candidate/src/run_rff_saved_evaluation.py" run \
  --run-spec "$RFF_RECOVERY/contracts/RUN_SPEC.json" \
  --input-binding "$RFF_RECOVERY/contracts/INPUT_BINDING.json"
```

真实 `run` 校验 macOS、原 interpreter/prefix、原 RFF native reference、子进程环境和本机进程树 RSS backend。新输出目录、resource trace 或 execution ID 已存在时拒绝再次执行。命令没有训练、预测、model-load、补做分数或自动重试分支。

## 4. RUN_STARTED → terminal 与输出解释

启动前完成绑定、授权、原生环境和路径检查；原 guard 以零 debit 向原 official registry 登记唯一新 RUN_STARTED。取得精确 readback 后写 `EVALUATION_START_RECEIPT.json`，然后在原进程树监控器内执行一次 worker。

worker 先核对非 truth 输入快照并解析候选分数/Top3。之后只读取一次主评价 truth 快照；hash 通过后，在解码前独占写入 `EVALUATION_TRUTH_READ_START.json`。尝试和完成分开计数：解析失败是 attempt=1、completed=0；中途退出只剩 marker 时，completion 是 unknown，不补成 0 或 1。两个保存的 control score 文件含已有标签，其成功解码数量单独写入 `control_label_artifacts_decoded`，完整成功应为 2；不能把这两次隐藏在“只读一次主 truth”的表述里。

正常结果包括：

| 文件 | 含义 |
| --- | --- |
| `METRICS.json` | 原 RFF 指标、两个 frozen controls、paired 比较、原 promotion gates 与最高 DIRECTION_ONLY。 |
| `EVALUATION_RESULT_RECEIPT.json` | 输入摘要、metrics SHA、源/绑定/start 链及实际计数。 |
| `EVALUATION_WORKER_STATUS.json` | worker 完成或失败、native 检查、实际计数；不是 registry terminal 的替代品。 |
| `EVALUATION_RUN_RECEIPT.json` | 父进程核验结果、控制比较摘要、资源证据引用、实际计数和错误。 |
| `EVALUATION_TERMINAL_RECEIPT.json` | 唯一 official terminal 的事件摘要、registry after SHA 与 run/start receipt 链。 |

完整成功需要进程退出 0、原监控器的两次 fsync 后检查、正确的 worker/result/metrics 身份和计数，以及 official terminal readback。`COMPLETED` 表示该评价执行和证据链完成；是否通过 development gates 单独见指标，不能据此直接宣称推广或交易许可。

start/terminal append 若“已落盘但调用报错”，只做一次精确只读核对，不再次 append。已落盘的异常 start 会直接关闭为 `CANNOT_CONFIRM`，不启动 worker。汇总收据或补充证据读写失败也会尝试一次失败 terminal。若 terminal 的落盘状态不能确认，写出 `TERMINALIZATION_BLOCKED.json` 并非零退出，不伪造成功终止；保留原 registry 与所有新证据，交本机主控处理。

意外监控异常会通过新入口的包装层调用原进程树清理函数，记录 `EVALUATION_MONITOR_ABORT.json` 和清理/退出证明；清理无法确认时保留 unknown。未知 worker 实测状态与 guard 的结构性零 debit 字段分开登记。旧执行的 fit=1 仍保留，不能从结构性零 debit 推导“已观测到所有实际调用都是 0”。

进程树 RSS 是采样观测，不是绝对瞬时峰值保证；沿用原 helper 的观测定义，未把它改写成硬内存隔离。

## 5. 回滚与失败处理

`patches/runtime.patch` 只增加五个运行文件，`patches/runtime.reverse.patch` 是其精确反向补丁；没有旧研究文件的删改。补丁路径相对于新代码根目录。完整 after 已包含这些文件，不能在完整 after 上重复应用正向补丁。

在尚无真实执行时，可将这份新增代码目录停用；如使用补丁安装，在对应新代码根目录先检查反向补丁，再应用：

```bash
git apply --check /path/to/patches/runtime.reverse.patch
git apply /path/to/patches/runtime.reverse.patch
```

上述 `/path/to/patches` 必须换成下载包实际位置；补丁只针对新增源码。`run` 后的回滚只停用入口，不删除新输出、trace、review/release 或 registry 事件，不恢复旧 registry 快照，不重置预算。若有 `TERMINALIZATION_BLOCKED` 或 `process_tree_termination_confirmed=false`，先由本机主控处置对应 execution；不要把同一命令当成补终止/重试工具。

## 6. 此次验收的边界

最终测试数量、准确命令、环境、日志 SHA、源码 SHA 与独立复核结论见交付包 `review/` 和 `SOURCE_MAP_DELTA.json`。

本次未访问真实 Mac 的 scores/Top3/truth、模型、runtime 合同原件或 registry；未运行真实研究预检/评价、训练或预测。原真实失败 keys 及 accepted join 对那些实际行的表现仍未确认；PR #5 的 Mac 29/29 只保留为已有 scoped evidence，没有重新执行。

远程附件没有 frozen evaluator 的 `settings.py` 历史摘要。本入口会绑定本机同包设置的实际原字节，但其历史一致性仍需本机 review；没有编造 calibration bins、bootstrap 参数或成本。合成 fixture 注入的设置仅供合成数学和流程验证。

问题包里的 `resource_tree.py` 当前 SHA 为 `9d0792a8e582d0345c83ddaf83a15612a5629b5f0460833b4715068324ff2752`，不同于旧 R2 manifest 的 `8b13418…`。本次新绑定固定问题包实际源码并纳入新验收，不继承旧 R2 PASS。本容器原始 `ps` PID namespace 不匹配的失败证据也保留；合成进程测试不替代 Mac 原始 RSS backend、完整 worker/L04 或真实评价验收。
