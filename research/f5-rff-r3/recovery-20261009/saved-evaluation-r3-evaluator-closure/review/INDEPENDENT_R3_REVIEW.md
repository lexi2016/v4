**R3 独立复核结论：PASS_R3_SOURCE_AND_SYNTHETIC_LOG_REVIEW。** 在下列精确源码与测试快照范围内，未发现新增、确定的 P0/P1。该结论限于历史 evaluator 依赖闭包、导入身份及 RUN_STARTED 前预检；不代表真实 Mac 评价通过，也不证明真实命中率提升。

基准为已获用户本机验收的 R2 `4be3c657c04cb3431d19a83cf584bdb2a0481dac`；本轮反馈固定于 `cd1a080c13f1b1849d4b882b587b374dd948e5c8`。复核者未编写本轮生产或测试代码；此前参与历史身份恢复，本轮仅只读检查实际 diff、测试与作者日志，并独立计算文件 SHA/大小和 AST 常量。未重新执行测试，未修改生产或测试文件。

**历史身份与精确依赖。** `MAC_FIXED_SOURCE_MANIFEST.json` 的历史创建时间为 `2026-09-23T03:45:54.298791Z`，完整文件为 19131 bytes，SHA256 `64fd0f7a5e3d646f7b5b184d44ca10576aab9db73772b3abb2cfceab36862a9b`。独立保存的 `MAC_FIXED_PACKAGE_IDENTITY_RECEIPT.json` 创建于 `2026-09-23T03:46:17.479973Z`，其内容指定上述完整清单身份。返回文本补一个末尾 LF 后，完整 SHA 与大小同时命中该历史记录；当前快照没有被自行提升为历史 pin。

身份回执保留的是完整返回文本 5826 bytes，不声称取得其服务元数据标记的 5827-byte 原文件。原归档 `HK_SPIKE_F5_TRAIN_V1_MAC_FIXED_20260914.zip` 的历史声明为 1073959 bytes、SHA256 `aaf9d39eaed231f957c1818e19396edc258bf1df3a7add3d480630122b003412`；本次未取得或重新散列归档。六份反馈源码/配置与历史清单逐字身份一致；init 是候选版本声明 `__version__ = "1.0.0"` 加 LF 的 22 字节恢复，完整 SHA 独立核算命中历史清单，未声称读取原 Mac init。

| 历史相对路径 | bytes | SHA256 |
| --- | ---: | --- |
| `spike5/__init__.py` | 22 | `27e8febb48ada44153ea2add9969a2c50a9831a74d9755fdd53c549a888b1cc2` |
| `spike5/common.py` | 2067 | `affff27d758d73fdbde3da21af59b94b265d4072cf83036475cd06b0941a4097` |
| `spike5/features.py` | 5941 | `947e8d9a2f2b36e44ecfc8d713e0c492670039838dcf3e5abb9396f17a637c38` |
| `spike5/settings.py` | 288 | `702c374612806e45647b8cdb8cb345736b6cac689f23df352c00d08735bfb4fc` |
| `spike5/metrics.py` | 8758 | `c8ffabf345069d64a82ac686e6747afda8c22433f1309eecdc999a7ad1eac763` |
| `config/base_features.json` | 408 | `6284bfe3609ec9f220b4f4baef6e0cb4d3190529830fbcb0d8ff435c0859c7af` |
| `config/contract.json` | 10193 | `17ecffd1304e152da4f611b3ffc4b5e92633fac20d528b93ce9b6f8714b1c4bb` |

独立重算交付 fixture 的全部七份字节及 bundled manifest，均与表中身份一致。`config/contract.json` 保留历史 Mac metadata amendment 后的 `17ecffd1…` 身份，没有回退原提交归档的配置；未新增阈值或指标。

**实际实现检查。** `rff_saved_eval_contracts.py:192` 固定完整历史清单 SHA，校验 schema、identity_kind 及路径唯一性；`:208`、`:229` 从已绑定 metrics 包根派生五份模块、两份配置，逐项验证精确路径、历史 SHA、整数 bytes 与实际读入字节。清单记录自身及全部七项进入 binding，`load_documents` 的精确键集合包含新增成员。整个 closure 摘要覆盖模块、配置和历史清单记录。

`rff_saved_eval_worker.py:57` 在执行任何 spike5 包体前检查已有全部 `spike5` / `spike5.*` 缓存；未知名称、错误 `__file__` / `__spec__.origin`、源码身份、整体 closure 标记或不完整已加载闭包均拒绝。`:75` 按 init/common/features/settings/metrics 的实际历史依赖顺序使用已校验字节加载。独立检查五份原源码导入，内部依赖仅为 settings→common/features、metrics→settings，未见遗漏的额外 spike5 依赖。首次模块/config 加载未完整通过时不会获得整体闭包标记，后续调用拒绝留下的不完整或无标记缓存；没有新增重试或清空旧合法缓存的路径。

两项 JSON 读取限定为 closure 中的精确配置路径，并由 `checked_read` 返回的 UTF-8 字节交给原等价 JSON 解码。`common.read_json` 在 `finally` 恢复；settings、metrics、features、配置原文件字节均保持历史身份。成功缓存再次使用仍先校验实际文件与完整 closure 身份，配置漂移不能借旧 settings 缓存跳过。

`run_rff_saved_evaluation.py:733–734` 是 runner 唯一新增的两行，调用真实 bound worker 的同一 evaluator loader，位于 native 校验之后、任何 official helper 加载/adapter/guard 构造之前。静态路径保证预检拒绝早于 RUN_STARTED；`_execute_bound:308` 的临近 claim source snapshot 校验与 child 原校验均保留。AST 对比确认所有既有 PINS 和 CANDIDATE_EVENT_SHA256 不变，原 receipt 链校验、官方路径约束、候选 fit=1 计数、登记/监控/异常生命周期未改；frames 与 registration 全文件逐字未变。

**测试与日志边界。** 作者执行的新增依赖测试 14/14、新增预启动测试 9/9、受影响 contracts 回归 38/38、worker 回归 22/22 均为 OK，共 23 项新增加 60 项受影响合成检查。独立复核者阅读下表完整 GREEN 日志及 RED 核心反例，未自行重跑，也未将这一组称作全部历史验收重跑。

| 作者日志 | cases | 结果 | SHA256 |
| --- | ---: | --- | --- |
| `analysis/evaluator_dependencies_green_attempt1.log` | 14 | OK | `930817eeec4fa4fd0198e542e532683d073333e964ab509a0eba80dcd11d19d2` |
| `review/R3_EVALUATOR_PRESTART_TEST_OUTPUT.txt` | 9 | OK | `b4681b0a518aa6bfe468f984af6fad8dcc0f03eb19c43848bc2a062d878f8e29` |
| `analysis/r3_contracts_regression_green.log` | 38 | OK | `975ec30d6b14173880ac7f5260cc6ab48bb3965e25d489f936b745647cb90a59` |
| `analysis/r3_worker_regression_green.log` | 22 | OK | `dafee85773e103d092355b0945808c82ef4bf2789b803c9629384bd824b83ab2` |

依赖完整 RED 为 `analysis/evaluator_dependencies_red_complete.log`（31442 bytes；SHA256 `cf6ebab0da031719d95aead61ac08f4844d4858863c710d66383c800db1c45ee`），14 个 unittest cases 下报告 26 个失败与 2 个错误，包括原 common/features 导入缺失源码身份、静态闭包接口缺失，以及原路径/缓存接受反例。预启动 RED 是原 runner 上最初的一项顺序测试；随后扩展为最终 9 项 GREEN，不能表述为最终 9 项全部执行过 RED。该过程及冻结摘要见 `review/R3_EVALUATOR_PRESTART_VERIFICATION.json`。

预启动用例实际执行 `_run_real`、真实 worker preflight 和历史七份 source/config；外围明确替换 load_documents、review/release、native 校验与已验证 wrapper 的两个绝对路径属性，并在第一项 official helper 加载前设置观察屏障。正向完整事件顺序断言要求 evaluator_ready 先于屏障，负向要求 SavedEvaluationError 且未到屏障、未进入 owner/monitor、未创建 output/trace、数据/model/registry 读取计数为空；屏障不能让错误顺序假通过。它不执行官方登记或真实评价。

新增测试没有替换历史 source SHA、manifest pin、settings/metrics 实现或配置；正向仅将原 wrapper 的两项路径指向临时历史源码。受影响既有用例改为七份完整历史 fixture；错误包根用例仍到原 absolute-path guard，其余期望错误变为更早、更强的历史身份拒绝，未弱化已有拒绝断言。fixture provenance/README 的最后改动仅移除内部定位元数据，不改清单、七份字节、产品或测试。

**冻结源码。** 下表为复核时独立重算的文件身份；完整测试、日志与历史依赖快照另见同名 JSON。

| 文件 | bytes | SHA256 |
| --- | ---: | --- |
| `candidate/src/rff_saved_eval_contracts.py` | 46016 | `856c4adc1948a51a829f83d8a6d5201d1a1c5dc008bc12bbc951c6dc49b22c81` |
| `candidate/src/rff_saved_eval_worker.py` | 18997 | `df5c873c20f2af57ebd68d72d29cdc56c16b0e91e581406395fd029f8b99d99a` |
| `candidate/src/run_rff_saved_evaluation.py` | 49678 | `91af4af8dc815ba9748265d60880b8526a3dd3744c14c136ee7e518d28b20e8e` |
| `candidate/src/rff_saved_eval_frames.py` | 20611 | `0931cf63d5f779d02025ce5e41ca984aa9541686709b58e2d2367782200e203b` |
| `candidate/src/rff_saved_eval_registration.py` | 22974 | `e25f3312332547f71f9edab2b76a49e20921ca1fb3c29d0c0face7211fd03ce0` |

本次复核未访问真实 Mac scores/truth/model/registry，未执行真实 prepare/eval、fit/predict、PR5 旧验收或重做 R2 本机验收。历史归档取得限制和 init 字节恢复方式如上保留。真实 R3 的本机 prepare、独立 review/release 与一次真实评价仍待本机流程完成；本报告不创建执行授权，也不声称真实命中率结果。
