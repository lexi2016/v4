# Issue 33：RFF saved-evaluation 数学与数据合同核对

范围：只读冻结源码、已有 PR5 receipt 与合成 frames。没有读取真实 scores、Top3、truth、模型或 registry，没有运行候选 worker，也没有重新运行或撤销 PR5 的 29 个已接受测试。

本子任务随后按主控明确指示新增 `candidate/src/rff_saved_eval_frames.py` 与 `candidate/tests/test_rff_saved_eval_frames.py`，仅负责数据帧评价。文件、源身份、truth 读取计数和 RUN_STARTED→terminal 生命周期由主控的外层 worker/owner 负责。

## 1. 源码身份与结论

| 来源 | 实际核对的 SHA256 |
|---|---|
| `inputs/attachments/rff/pr5_accepted/src/rff_worker.py` | `3ea10757a81207147e5cfb9e68e69750a0579786153e7ce58ccf342a3184058c` |
| `inputs/attachments/shared/src/score_aware_metrics.py` | `fc93d6225c75b633981508a18c428e7649122571c7d897264d0b7da1e591eb8c` |
| `inputs/attachments/xendcg_saved_eval/src/evaluation_worker.py` | `1ee350797f5ee64908b7fe3eaaff379446266e9c33642037e00eed4ef5b05180` |
| `inputs/remote/research/f5-rff-r3/external_frozen_evaluator/metrics.py` | `c8ffabf345069d64a82ac686e6747afda8c22433f1309eecdc999a7ad1eac763` |
| `inputs/remote/research/f5-rff-r3/research/hk_burst_f5/batches/full64_rff_logistic_r1_20260927/contracts/EXPERIMENT_CONTRACT.json` | `e6c1509955730a032d183563d6ffcf2501a587dd5734426f35fc59b222491135` |

RFF 同时保存 raw logistic decision margin 与拟合分类器给出的 sigmoid 概率。XENDCG saved worker 的 `SCORE_COLUMNS` 只有 `ranking_score`，并明确把概率诊断置空。因此不能直接把 XENDCG 的 `evaluate_frames` 用在 RFF 上，也不能只替换 route/schema 字符串。

## 2. 保存 scores / Top3 的源码合同

保存链见 accepted RFF worker 349–399 行，CSV 实现见 remote 的 XENDCG `candidate_worker.py` 89–95、151–159 行。

| 工件 | 列集合 | 源码可确认的 dtype / 语义 |
|---|---|---|
| `CANDIDATE_SCORES.csv.gz` | `code, session_id, market_date, scoreable, ranking_score, probability` | `code` 由 `pd.read_csv(dtype={"code": "string"})` 保留前导零；`ranking_score` 与 `probability` 的生成数组明确为 `np.float64`；其余三列沿用 pretruth CSV 推断结果，源码没有固定全部 dtype |
| `CANDIDATE_TOP3.csv.gz` | scores 的全部列，另加 `rank, weight` | raw margin 降序、同分 code 字符串升序；按 session 分组最多取 3；`rank` 来自 `cumcount()+1`；`weight` 是字符串 `"1/3"` |
| truth CSV 读取视图 | `code, session_id, market_date, scoreable, y, label_status, first_exact, episode_state` | `code` 同样为 pandas string；其余列由原 CSV parser 推断；合法未知 `y` 保留 NaN，不能当作 key 未匹配 |
| control scores 读取视图 | `code, session_id, market_date, scoreable, probability, y, label_status, first_exact, episode_state` | 原 binary probability path；已保存 outcomes 必须与同一 truth 的完整域按 key 精确对等 |
| control Top3 身份视图 | `code, session_id, rank, probability` | 身份比较按 `session_id, rank, code` 排序，精确比较数值，不以 dtype 差异代替身份差异 |

严格区分“源码列集合”和“真实工件列顺序”。pretruth 使用 `read_csv(usecols=...)`，其输出列顺序仍取决于源 header；随后在末尾追加 margin、probability。因此未打开真实 header 不能宣称所有列的真实顺序已确认，也不能宣称 session/market_date/scoreable 的实际 dtype 已验证。CSV 没有存储 dtype 元数据。

原 writer 使用 `to_csv(index=False, lineterminator="\n")`，没有自定义 float_format，随后 `gzip.compress(..., mtime=0)`。后续读取必须消费绑定的原字节；不得重新写 CSV、从 raw `.npy` 或模型重建分数，或者为了适配而重排/改写保存工件。

新 frame 层接受列集合而不强制文件 header 顺序；代码值必须是字符串，session 必须具有整数数值，候选 raw/probability 必须为数值类型且在恰好的 scoreable 域有限，unscoreable 位置必须为 NaN，probability 必须在闭区间 `[0,1]`。这些检查不修复或强制转换原 frame。

真实固定范围：G=169986，S=120084，calendar=246，slots=738。`known_positive_denominator=126` 实际对应 frozen helper 的 confirmed NEW episodes，不能与 `(y == 1).sum()` 比较。新 evaluator 用真实 helper 的 `confirmed_new_events` 核验这个分母，并另外记录 positive-label rows。

## 3. 最小 accepted join 复用

accepted `_join_truth` 位于 worker 80–108 行。它以 `code/session_id` 建立 left-domain key coverage，只附加 `y,label_status,first_exact,episode_state`，保留 left frame 所有原列、分数值、行序、index（包括非唯一 index）。未知 `y` 不构成 join 失败。

新 frame 层只执行：

```python
candidate_frame = accepted_worker._join_truth(candidate_scores, truth)
candidate_selected = accepted_worker._join_truth(candidate_top3, truth)
```

`accepted_worker` 由外层对整个文件 SHA 校验后直接 import。不得 AST 抽取后重编译 helper，不得复制 helper，不得调用完整 `run_candidate_worker`，也不走历史 `candidate_worker._join_truth` 或 XENDCG `_attach_truth`。

controls 沿用原 RFF 行为：保留其已存 outcomes，经完整域、scoreable/date 和 outcomes 按 key 精确对比后交给原 binary helper，不额外写回标签。新 frame 层的日期、grid 对照及排序统计量检查是工件一致性校验，不创建第二套 truth-join 规则。

## 4. 指标差异与必须保留的细节

### 4.1 RFF 的 binary 概率块不能丢弃

accepted worker 426–435 行先调用 raw-ranking `score_aware.arm_metrics`，随后将候选 arm 的 `probability` **整个替换**为 binary `score_aware.probability_metrics(candidate_frame)`。

原 binary helper 的概率指标域是 scoreable 且概率有限的行，known 指其中 label 有限的行。它报告 known-label noninterpolated AP、Brier、logloss、包含未知标签的 Brier/logloss identification bounds、原配置 calibration bins，并保持 `probabilities_calibrated_claim=False`。界限来自未知标签在 0/1 两种结局下的逐行最小/最大损失；它们不是置信区间。概率 0 和 1 合法，logloss 使用 frozen helper 自己的 epsilon clipping。

新实现保留上述整个候选 arm 对象，与原 RFF composition 逐项对等，不把它改成 XENDCG 的“没有概率模型”空值结果。

### 4.2 margin AP 注释与旧序列化输出存在差别

原 RFF 注释及冻结合同说 AP/Top3 走 margin。实际 Top3 确实走 margin；但原 worker 的第 435 行覆盖整个 `probability` 后，旧字段 `arms.CANDIDATE_RFF_LOGISTIC.probability.average_precision_known` 实际来自 sigmoid 概率。

在精确数学中 sigmoid 单调，排序相同；有限精度饱和可能制造概率 ties，因而两种 AP 不能无条件宣称相等。新实现不改原字段含义，另加 `ranking_score_diagnostics.average_precision_known` 明确保留 raw AP，并用 synthetic saturated probabilities 覆盖两种 AP 不相等的情况。

### 4.3 paired precision 保持原 helper 的共享未知抵消

frozen `paired_precision` 21–35 行对每个 session 枚举两侧所选 code 的并集。每个 code 的系数为 `I(candidate selected)-I(control selected)`；共同选中的 code 系数恰为零，即使其 label 未知也应抵消。只有独占未知 code 扩大 identification interval。每个 session 固定除以 3，再平均整个 calendar，因此总分母始终为 `3 * sessions`，不能改成 known-selected 数、实际 filled slots 或两个独立 arm 的上下界相减。

RFF 原实现检查两个 control 的 paired 分母；XENDCG evaluator 只显式检查 PLUS。新实现保留两侧检查，并核验 daily session 域/顺序。候选 Top3 直接使用保存内容，检查每个已保存 pick 在 raw margin 降序/code 升序规则下的 order statistic；不会重新选择候选 Top3。控制 selector 按原 RFF 调用 binary wrapper 与 frozen 原 helper，对比保存 Top3 后使用。

### 4.4 门槛、成本与 evidence 上限

| 项目 | 原值/语义 |
|---|---|
| Development primary | candidate-minus-PLUS paired lower `> 0.0` |
| Practical BASE34 | candidate-minus-BASE34 paired lower `>= 0.03`，即精度差 3 个百分点 |
| Promotion paired precision gain | `0.03` |
| Relative precision lower ratio | `1.25` |
| Random lift lower | `2.0` |
| Positive years minimum | `2` |
| Selected unknown fraction maximum | `0.05` |
| Empty slots maximum | `0` |
| Episode coverage gain minimum | `0.0` |
| Known AP gain minimum | `0.0` |
| Known Brier gain maximum | `0.0` |
| Promotion now | `false`，单个 exposed year 阻止 promotion |

原 `development_decision=DEVELOPMENT_PASS` 只是两个 development gates 的结果，新实现保留该标签；最终 `evidence_status/evidence_ceiling` 仍固定为 `DIRECTION_ONLY`，promotion 仍 `BLOCKED_SINGLE_EXPOSED_YEAR`。research_only=true，其余 production_allowed/buy_gate_updated/orders_sent 全 false。

frozen metrics.py 自述是 predictive metrics 而非 P&L/backtest，函数中没有 fee、slippage 或另设交易成本模型；不应发明成本参数。它固定 Top3 的每 seat 权重为 1/3，且空席位仍计入分母。所有这类原样本与权重语义保留。

资源限制另由最新协作约束决定：`remote/research/f5-rff-r3/COLLABORATION.md` 第 9 行明确未来 Mac 的资源约束已被用户重置，**不能默认**旧合同的 4 线程/3 GiB/1800 秒。原冻结合同字节不改；新 run resource spec 必须由主控显式冻结。frame 层不设置任何资源默认值。

## 5. 原 evaluator 设置缺口

`external_frozen_evaluator/metrics.py` 第 10 行 imports `.settings.CONTRACT`，第 46 行使用 `CONTRACT['calibration_bins']`；当前附件/source slice 没有这个 settings 文件。不能从 metrics.py SHA 推导原 bins，也不能猜其配置。

真实外层应使用本机既有 frozen evaluator 及原 settings，核对其绑定来源与 SHA，并在进入 frame 层前完成 `score_aware.frozen_metrics()` 的加载/身份检查。合成测试只给 exact metrics.py 注入明确标记的 synthetic settings（bins `[0.0,0.5,1.0]`），不声称其等同真实 bins。

## 6. 新增合成验收与诊断

先写测试，再确认新模块缺失的 RED：21 个 assertion failures，exit 1。随后完成新 frame 层，第一轮 21/21 通过。补入 0.03 真实算术边界及 dtype 诊断后，先确认字符串 y/first_exact 产生错误类型的两个 RED subcases，再新增最小 dtype guards，23/23 tests 通过。主控另发现借用 XENDCG 的 first_exact 全局非空检查比原 RFF 更严；新增“y=0/unknown 的 first_exact 为 NaN，原 helper 成功且新组合应相等”回归，确认 RED 后移除这一多余限制，最新结果为 24/24 tests 通过（2.601 秒，exit 0）。没有填值或改变 accepted join。

覆盖原 RFF arm/probability 对等、raw AP 与 sigmoid saturation ties 的区别、shared-unknown paired cancellation、两个 denominator、0.03 inclusive boundary、development PASS 仍 DIRECTION_ONLY、NEW episode 而非 positive-row 分母、保存 Top3 不重选、margin/probability/weight/rank 与 grid 一致、candidate/controls/truth/calendar 原 frame 完全不变，以及 schema/概率域/日期/类型/控制标签/控制 Top3/阈值 drift 的可定位拒绝。

准确的独立 frame 测试命令（从 issue33 根目录）：

```bash
python -m unittest discover -s candidate/tests -p test_rff_saved_eval_frames.py -v
```

测试支持 `ISSUE33_ATTACHMENTS_ROOT` 和 `ISSUE33_REMOTE_ROOT`，便于本机把只含源码的附件放在别处；不会读取 PR5 tests 本身。测试以 SHA 校验真实的 accepted worker、score-aware wrapper 和 frozen metrics 源码，再仅对 synthetic frames 调用函数。

新失败诊断包括字段名和逻辑工件名，例如 `RFF_FRAME_SCHEMA_MISMATCH:candidate_scores`、`RFF_PROBABILITY_COVERAGE_INVALID:candidate_scores`、`RFF_TOP3_GRID_VALUE_MISMATCH:probability`、`RFF_TRUTH_NUMERIC_DTYPE_INVALID:y`、`RFF_PAIRED_SLOT_DENOMINATOR_MISMATCH:FROZEN_BASE34`。外层须把首个错误、具体代码位置、缺失工件及真实 counters 写入 terminal，不能重试、改门槛、补值或自动重排修复。

frame 层没有 truth decode counter，因为接收的是已经解码的 DataFrame；不可伪造为零或新授权次数，外层必须记录实际读次数。旧 candidate 的 fit=1/predict=1/truth_decode=1 仍属于旧 execution，不能由本函数的零训练/预测字段重置。

历史真实失败的 row/key、真实保存 dtype/header/key-order、accepted helper 在旧失败真实行上的表现及完整 worker/L04 行为仍为 `CANNOT_CONFIRM`。上述新增测试证明的是新的 frame composition 对合成工件的行为，不构成真实评价授权或真实模型效果结论。

## 7. 独立子审与保留的边界

独立静态子审未发现 P0/P1，确认 exact accepted join 的两次调用、candidate Top3 不重选、binary 概率输出、两个 paired gates 与 evidence 上限。子审另报两个 P2 输入边界：直接传入 pandas nullable `Float64`/`pd.NA` 的 y 会在 frozen scalar 逻辑失败；selected-positive 的 first_exact 为 inf 或 fractional 时，原 helper 可分别异常或发生原有整数转换。主控明确本 Issue 不为此新增门槛、不改原 evaluator 定义、不作 silent normalize。

理由是实际 saved worker 用原 `pd.read_csv` 默认 numpy float64，并不会产生 nullable Float64；外部帧调用若碰到不支持的 dtype，外层必须把异常原样记录为 terminal，不能伪装成功。first_exact 的真实 schema/取值有效性仍需新 binding 的本机独立验收确认。本修改只去掉误加的全局非空限制，保留原 RFF 可计算的 y=0/unknown 且 first_exact NaN 情形。

独立子审随后只读复核该 delta，确认第 221 行仅要求 label_status/episode_state 非空、没有填值/删行/重选、两次 outcome 附着仍是 accepted helper；新增回归直接比较候选完整臂与两个控制臂。其封版结论是本次 delta 未发现 P0/P1，两个先前边界观察保留为 scope 限制。

曾尝试使用主控的临时 pytest 路径，因 `test_deps/_pytest/compat.py:20` 缺少 `py` 模块而未能启动；没有以此替代或跳过测试。主控最终统一采用上面的标准库 unittest 命令，24 个 frame tests 已按该命令成功执行。
