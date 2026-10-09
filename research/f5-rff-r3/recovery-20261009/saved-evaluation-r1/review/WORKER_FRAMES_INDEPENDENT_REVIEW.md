# Issue #33 — worker / frames / 本机文档独立复核

日期：2026-10-09  
Reviewer：`/root/lifecycle_review`  
复核方式：最终源码只读检查、原实现对照、4 个临时合成 probe。  
源码结论：`PASS_SCOPED_STATIC_AND_SYNTHETIC_REVIEW`；本范围未发现 P0/P1。  
文档结论：正文及示例的作用域正确；实际 `after/examples/` 已核对，先前的条件性 P2 已关闭。  
本次最终范围：P0=0、P1=0、未关闭 P2=0。

## 1. 独立性与范围

本次独立结论只覆盖 `candidate/src/rff_saved_eval_worker.py`、`candidate/src/rff_saved_eval_frames.py`、`candidate/README_ZH.md` 和三个 `candidate/*.example.json`。Reviewer 没有编写或修改这两个被复核的运行文件；它们由另一参与者实现并由主控冻结。

Reviewer 曾实现 `rff_saved_eval_contracts.py` 与 `rff_saved_eval_registration.py`。**这两个文件不属于本次独立通过范围。** 它们只在接口对照或合成运行中作为既有依赖使用。runner 的全量正确性亦不属于本报告的独立通过范围；仅对其 marker/readback 接口与文档表述作了有限对照。

文档子复核由 `/root/lifecycle_review/review_mac_docs` 并行完成；本报告作者也完整读取了 README、三个示例和相应接口源码，并独立核验了下面的文件 SHA。

本报告不等同于真实 Mac 的 `INDEPENDENT_LOCAL_REVIEW.json` 或 `PARENT_RELEASE.json`。没有为任何真实 evaluation execution 签发 PASS 或 release。

## 2. 实际复核文件身份

路径均相对于 `issue33/`。

| 文件 | 字节数 | SHA256 |
| --- | ---: | --- |
| `candidate/src/rff_saved_eval_worker.py` | 16893 | `c015246b4b3a21bcb69a1745e41516a9c19f694bf923dfb39553a920a96dfdd8` |
| `candidate/src/rff_saved_eval_frames.py` | 20611 | `0931cf63d5f779d02025ce5e41ca984aa9541686709b58e2d2367782200e203b` |
| `candidate/README_ZH.md` | 12735 | `04d676d4a8612e4afa88cd7644236ab467f4a15d010e11b7a87aedebe7a418ae` |
| `candidate/PREPARE_CONFIG.example.json` | 963 | `6b4ddeb4104dd77eb14562901d01384cac71ec1e6cee403f67382dd3792d11b1` |
| `candidate/LOCAL_REVIEW.example.json` | 757 | `d1253cdf0f70dd172f8593a746e1be03ec3d3ccfd726e7a83c0ab7ce27255e9d` |
| `candidate/PARENT_RELEASE.example.json` | 1622 | `5b4f6b0c1d14b7cd19daefed7e6371cdd098f9465c2b470b143cc440b3a49819` |

用于对照的依赖身份：

| 依赖 | SHA256 | 本报告的用途 |
| --- | --- | --- |
| `candidate/src/run_rff_saved_evaluation.py` | `f27d34886671186e69010908ddc640edfb4ba0780fdbe77618715feb433fa1ed` | CLI、marker 消费及完成约束对照；不是 runner 全量独立 PASS |
| `candidate/src/rff_saved_eval_contracts.py` | `35b9f88b8183f8980333bfe4e06f37b3ef3e2acbea7a0fc6904b1d130ef058b7` | 接口和示例拒绝条件对照；Reviewer 自己编写，排除在独立 PASS 外 |
| `candidate/src/rff_saved_eval_registration.py` | `e25f3312332547f71f9edab2b76a49e20921ca1fb3c29d0c0face7211fd03ce0` | 仅记录冻结身份；Reviewer 自己编写，排除在独立 PASS 外 |
| `inputs/attachments/rff/pr5_accepted/src/rff_worker.py` | `3ea10757a81207147e5cfb9e68e69750a0579786153e7ce58ccf342a3184058c` | 原 accepted join 与 RFF 指标组合的源码依据 |
| `inputs/attachments/shared/src/score_aware_metrics.py` | `fc93d6225c75b633981508a18c428e7649122571c7d897264d0b7da1e591eb8c` | 原 score-kind 分派、raw AP 与 binary 默认行为 |
| `inputs/remote/research/f5-rff-r3/external_frozen_evaluator/metrics.py` | `c8ffabf345069d64a82ac686e6747afda8c22433f1309eecdc999a7ad1eac763` | 原 probability、episode、paired 数学 |

## 3. worker 复核结果

### 3.1 保存输入入口与零生产活动

`_start_and_binding()`（worker 第 105–142 行）检查 immutable binding 字节、逐项 payload 对应关系、spec 中严格整数零预算、一次 truth 解码授权，以及与 output 相符的 durable start receipt。output 必须只包含该 start receipt；不允许把既有 output 当成重试入口。

`run_saved_evaluation()`（第 145–259 行）没有 candidate CLI、fit、predict、calibrator 或模型读取调用。accepted worker 在 `_load_evaluators()` 中按完整文件 SHA 加载，实际被使用的接口仅为 frames 中的 `_join_truth`。新增程序没有复制或重写它，也没有生成新的 candidate scores/Top3。

`_common()`（第 20–44 行）核对同目录源路径、完整 SHA 和 cached-module 身份，随后编译对应源码字节。`_load_evaluators()`（第 57–87 行）在执行 accepted worker/score-aware 模块前检查 pin，核对 frozen metrics 的路径与 SHA、同包 settings/init、实际返回的 metrics 模块身份，并拒绝未绑定的 `spike5` 子模块。

`_validate_child_runtime()`（第 90–102 行）复用绑定的 native helper/reference，要求 supplied spec 与 helper 从 reference 得到的 spec 完全相同，再执行原 `verify_child_launch_environment()`。源码没有 synthetic/skip 环境分支；原观察结果的 distribution-lock 限制保持原值。

### 3.2 truth 与两个 control 标签文件的计数

worker 第 179–189 行先校验非 truth 文件快照、解析并核验保存的 candidate scores/Top3。主 truth 的文件打开只出现在第 191 行；最后第 237 行重验的是 source/metadata，不会重读输入 truth。

第 190–208 行分别记录：

| 字段 | 含义与更新位置 |
| --- | --- |
| `evaluation_truth_artifact_read_attempts` | 调用受绑定的 truth snapshot 读取前置 1 |
| `evaluation_truth_artifact_reads_completed` | 读取和 SHA 校验成功返回后置 1 |
| `evaluation_truth_decode_attempts` | durable marker 写入后、CSV 解码调用前置 1 |
| `evaluation_truth_decodes_completed` | CSV 解码成功返回后置 1 |
| `evaluation_label_values_decoded` | 与成功解码状态同步为 true |

`EVALUATION_TRUTH_READ_START.json` 在解码前独占写入，固定 execution、candidate、route、spec/binding/source/start/seal/truth 身份；marker 本身只记录 attempt=1、completion=null，没有提前宣称解码完成。

第 210–215 行另外解析两个 control score 文件中的既有标签，每次成功后累加 `control_label_artifacts_decoded`；完整成功为 2。control Top3 只解析 code/session/rank/probability，不增加标签解码完成数。主 truth 的一次解码与 controls 的两次标签文件解码没有混为一个指标。

失败状态保留当时已发生的计数（第 251–258 行）。若 status 本身没有保存成功，worker 不凭空构造已观测零活动；父进程的 fallback 只承认经过完整身份检查的 marker，相关集成 probe 见第 6 节。

## 4. frames 复核结果

### 4.1 原 join 与保存的候选 Top3

唯一两处 outcome attachment 是第 232–233 行调用 `accepted_worker._join_truth(candidate_scores, truth)` 与相应 candidate Top3。full-grid metadata、date、mask 和保存 Top3 的检查不另造 outcome join。

`_check_saved_candidate_top3()`（第 101–138 行）检查保存文件的三席、rank、字符串 `1/3` 权重、grid 子集和数值对应关系，并以原 raw-margin/code 次序验证每个已保存 rank。它不调用 candidate selector，不返回新 picks，不保存替代 Top3。第 270–277 行调用的 selector 只用于核对两个原 frozen controls，符合原 RFF worker 第 438–453 行的组合方式。

frames 保留 unknown `y`，没有把 unknown 标签作为 key 缺失证据；也没有引入旧 XENDCG 的全局 first_exact 非空规则（第 219–228 行）。本复核没有重开 PR5 原 29 个 tests；旧真实失败 keys 仍未知。

### 4.2 评价定义、阈值与来源

第 241–250 行沿用原 RFF 组合：candidate arm 先用 raw-margin 分支获得 arm/episode 指标，再用原 binary probability helper 替换 probability 块。raw AP 作为独立 ranking diagnostic 保留。这与原 accepted RFF worker 第 423–435 行一致；没有把 raw margin 填入 Brier/logloss/calibration，也没有把 sigmoid ties 下可能不同的 AP 偷换成同一值。

两个 control 的 selector 和 arm_metrics 均与 frozen evaluator 做逐项一致性核验（第 259–286 行）。paired_precision 直接调用原 score-aware/frozen helper，检查 sessions/slots，而不创建新的 paired 公式（第 288–295 行）。

confirmed NEW episode 分母取原 arm helper 的 `confirmed_new_events` 并验证为冻结值，不把 positive `y` 行数当作分母（第 251–253、282–283、306–308 行）。PLUS `> 0`、BASE34 `>= 0.03`、原 promotion gates 和 `DIRECTION_ONLY` 上限保持原义（第 191–198、297–319 行）。

本模块没有自建成本或收益公式。原 frozen `metrics.py` 第 1 行已经声明并非 P&L/backtest engine；本报告不把这些 predictive metrics 说成成本调整后的策略收益。

## 5. Mac 文档和三个示例

| 检查项 | 位置 | 结论 |
| --- | --- | --- |
| Mac Python | README 第 43–47 行 | 与原 `rff_native_runtime.py` 的冻结 `PYTHON_PATH` 一致 |
| CLI flags | README 第 61–63、82–85 行 | 与 runner `main()` 第 697–714 行的 prepare/run 参数一致 |
| 显式资源 | README 第 56 行、PREPARE_CONFIG | 四项 null 是占位；不会借用旧预算。原 monitor 的 cpu_threads=4 限制有准确的 pre-start 错误说明 |
| 新 execution 与目录 | README 第 34–40、58、88 行 | 说明旧目录/worker/binding 不覆盖，已用 ID 不自动加号或重试 |
| prepare 行为 | README 第 65–67 行 | 明确读取源码/JSON/registry 前缀、创建 unsigned spec/binding，不启动 worker 或 append registry |
| 新独立 review/release | README 第 69–79 行 | 要求实际本机精确 SHA、独立 Reviewer 和 parent release；不沿用 PR5/问题包/远程报告的 PASS |
| noop 示例 | LOCAL_REVIEW、PARENT_RELEASE | review 三项 PENDING；release active=false、evaluation authorized=false；身份/资源占位。原样示例不能通过入口校验，CLI 不提供签发 PASS 的功能 |
| 主 truth 1 与 control 2 | README 第 94 行 | 与 worker 的实际动作和计数字段一致 |
| 孤立 marker | README 第 94、110 行 | 没有把 attempt 当成 completion，也没有把 structural zero debit 当成未知 worker 的实测零活动 |
| settings 与旧 source 边界 | README 第 133–135 行 | settings 历史摘要缺失、新 resource_tree SHA 与旧 R2 不同的事实均明确保留，没有继承旧 R2 PASS |

### 已关闭 P2：最终 `examples/` 打包目录

README 第 54、73 行引用 `examples/PREPARE_CONFIG.example.json`、`examples/LOCAL_REVIEW.example.json` 和 `examples/PARENT_RELEASE.example.json`；本次 staging 文件在 `candidate/`。

该项最初作为交付可用性问题通知主控，不涉及 release 绕过。主控随后实际生成交付目录，本 Reviewer 已只读核对：

```text
issue33/delivery/RFF_SAVED_EVALUATION_R1/after/README_ZH.md
issue33/delivery/RFF_SAVED_EVALUATION_R1/after/examples/PREPARE_CONFIG.example.json
issue33/delivery/RFF_SAVED_EVALUATION_R1/after/examples/LOCAL_REVIEW.example.json
issue33/delivery/RFF_SAVED_EVALUATION_R1/after/examples/PARENT_RELEASE.example.json
```

以上四个文件均存在，逐字节等于第 2 节对应 staging 文件，SHA 也完全相同；`after/examples/` 恰好包含三个指定模板。因此 README 的三个 `examples/` 引用已有实际交付文件，**此 P2 关闭**。本次核对的是这四个已落盘文件，不是尚未完成的最终 ZIP 或 runner/monitor 更新验收。

### settings/成本的准确边界

原 frozen `metrics.py` 第 10 行导入 `.settings.CONTRACT`；第 46 行使用 calibration bins，第 122–123 行的 block_interval 使用 bootstrap 设置。远程附件没有 settings 的历史 SHA。本入口能固定本机同包 settings 的实际字节并阻止准备后的漂移，但不能仅凭此次远程材料证明其历史一致性。README 第 71、133 行准确要求本机复核，未补造 bins、bootstrap 或成本参数。

示例 review/release 是人工角色与授权的元数据记录；代码的非空/角色区分/SHA 检查不等同于外部人员身份认证。文档没有声称具备外部认证能力，因此对此不新增阻断。

## 6. 独立的小型合成 probe

没有重复主控的 139-test 全套，也没有调用旧 PR5 test 文件。针对“计数是否等于真实 I/O”和“status 丢失时 marker 是否被误认成完成”两个确定风险，执行了一个独立 Python probe，4 个场景全部通过，进程退出码 0。

方法：使用当前新测试中的 `SavedWorkerTest` 生成 12 行完全合成数据；直接执行最终 worker。额外包装 `Path.open` 与 worker `_read_csv`，独立记录输入文件打开次数和 CSV 解码调用顺序，并在主 truth 解码调用处断言 durable marker 已存在。随后只在临时目录内删除 status、修改 marker 身份，调用 runner `_observations` 观察 fallback。

真实 accepted join、frames 和 frozen metric 数学均执行；`_load_evaluators` 和 child-native verification 按该 fixture 明确替换，绕开的仅是本机路径/环境加载步骤。fallback probe 的 resource-tree ref/descriptor 是观察接口所需的 synthetic 占位，不构成真实 spawn/cleanup 证明。

| 场景 | 独立观察 | 结果 |
| --- | --- | --- |
| 完整合成成功 | 8 个输入各打开 1 次；主 eval_truth parse 1 次；control labels 成功解码 2；marker 在 parse 前存在 | PASS |
| candidate CSV 解析失败 | 主 eval_truth 打开 0、parse 0；truth attempt/completion 均 0；control label decodes=0；worker FAILED | PASS |
| 完整运行后模拟 status 丢失 | 有效 marker 得 attempt=1、completion=null、control count=null；actual activity=UNKNOWN | PASS |
| marker 绑定了错误 start SHA | marker 不被采信；truth 状态 CANNOT_CONFIRM，所有相关计数为 null | PASS |

成功 parse 调用顺序：

```text
candidate_scores
candidate_top3
eval_calendar
eval_truth
FROZEN_UNWEIGHTED_PLUS_PATH_scores
FROZEN_UNWEIGHTED_PLUS_PATH_top3
FROZEN_BASE34_scores
FROZEN_BASE34_top3
```

孤立有效 marker 的实际输出：

```json
{
  "observed_status": "UNKNOWN",
  "truth": {
    "status": "ATTEMPT_DURABLE_COMPLETION_UNKNOWN",
    "evaluation_truth_artifact_read_attempts": 1,
    "evaluation_truth_artifact_reads_completed": 1,
    "evaluation_truth_decode_attempts": 1,
    "evaluation_truth_decodes_completed": null,
    "control_label_artifacts_decoded": null,
    "evaluation_label_values_decoded": null
  }
}
```

probe 使用的 fixture 文件身份：

| 文件 | SHA256 |
| --- | --- |
| `candidate/tests/test_rff_saved_eval_worker.py` | `128c31b79faa794177e075a1563fdfbb77356805d787fab87407097761d7ac76` |
| `candidate/tests/test_rff_saved_eval_frames.py` | `061431fd342c44eab9fb086690cfe14d2fe8bd7d90b76e2073c9005a1d7e895c` |

## 7. 未覆盖与行为边界

- 没有读取真实 scores/Top3/truth、模型、真实 registry；没有真实 fit/predict/model load 或研究运行。
- 没有修改产品源码、原合同、原 helper、旧 candidate 工件或 registry。此次唯一持久化修改是本复核报告。
- 没有跑原 PR5 29 个 tests；引用的 Mac 29/29 是旧 scoped evidence。
- 未验证真实 Mac interpreter/ABI、同包 init/settings 原件、原 RSS backend、完整 worker/L04、真实失败 key 或真实指标。
- 未重复主控的全套 139 tests；主控报告其已通过，该结果不充作本 Reviewer 独立执行证据。主控另行处理的 runner/monitor 变更不在本次独立通过范围。
- 本报告只批准所列源码/文档在明确范围内的静态与合成行为；真实新 binding、review/release、资源和 RUN_STARTED→terminal 仍须本机主控按 Issue 要求独立验收。
