## 当前请求：只补 RFF 已保存预测评价入口

关联 #2 与 PR #5。PR #5 的 join 修复已在 Mac 独立通过 29/29 合成测试；不应重新处理已接受的 join 缺陷。本问题是后续恢复阻断，**不是已验证的模型效果失败**。

独立问题包验收：`PASS_SUBMISSION_READY`，P0/P1/P2=0。没有启动新的 fit/predict/model load/truth decode 或改写 registry。

- [中文问题包](https://github.com/lexi2016/v4/blob/4c5fb40122cec7a40036bfda5e4d9516d82dcd18/research/f5-rff-r3/recovery-20261009/ISSUE_PACKAGE_ZH.md)
- [机器证据与身份](https://github.com/lexi2016/v4/blob/4c5fb40122cec7a40036bfda5e4d9516d82dcd18/research/f5-rff-r3/recovery-20261009/ISSUE_PACKAGE.json)
- [代码附件 ZIP](https://github.com/lexi2016/v4/blob/4c5fb40122cec7a40036bfda5e4d9516d82dcd18/research/f5-rff-r3/recovery-20261009/CODE_ATTACHMENTS.zip)
- [独立复核回执](https://github.com/lexi2016/v4/blob/4c5fb40122cec7a40036bfda5e4d9516d82dcd18/research/f5-rff-r3/recovery-20261009/review/INDEPENDENT_PACKAGE_REVIEW_REV2_RECEIPT.json)

附件 ZIP SHA256：`878e4432cd536ea96835b1b073916f71afaebee10f21239d801a0bb5d071bd64`。附件含历史源码、已接受 PR #5 worker/test、Mac receipt；不含真实分数、标签、模型或行情数据。

## 修复范围与交付要求

RFF 当前 candidate 入口会重新 fit/predict；completion 模块只读回既有结果。现有 XENDCG R2 runner 绑定其自身 schema/route/execution，不能直接消费 RFF candidate binding。请沿用既有 evaluator、owner 与登记生命周期，提供最小的 RFF route-scoped saved-evaluation 适配，禁止重训、重预测、重建分数或另造数据 producer。

1. 复用 PR #5 accepted route-local join，绑定 worker SHA `3ea10757a81207147e5cfb9e68e69750a0579786153e7ce58ccf342a3184058c`；原 candidate execution、binding、prediction seal 原字节保留。
2. 独立 evaluation execution 与输出目录；绑定原 scores/Top3/controls/合同/evaluator SHA；fit/predict/model-load 固定为0，truth读取次数如实登记，不重置旧执行额度。
3. 保持原评价、样本、成本和阈值；2024已暴露，最高DIRECTION_ONLY。保留research-only及其余三安全旗false。
4. 交付完整修改文件、最小正反补丁、源码身份变化、合成测试、准确本机命令和RUN_STARTED→terminal方案。先做代码与合成验收，真实数据评价由本机主控在新绑定独立验收后执行；本Issue不授权远程训练/真实数据执行。
5. 有新阻断立即交付具体错误/代码位置/缺失工件，不无限重试或改门槛。

以下为完整问题包正文：

# F5 RFF 已保存分数评价恢复问题包

日期：2026-10-09  
状态：BLOCKED_DIRECT_SAVED_EVAL_REUSE  
适用路线：F5_FULL64_RFF_LOGISTIC_R1_20260927  
候选执行：F5_FULL64_RFF_LOGISTIC_R1_20260927_RESUME_20260928_01

## 结论

现有 XENDCG R2 展示了可复用的 saved-evaluation 生命周期与评价依赖，但冻结 runner 不能直接接受 RFF 的 route、execution 和 candidate binding。RFF 尚无独立、零 fit/predict 的已保存分数评价入口；RFF candidate CLI 会调用完整 candidate worker。RFF 的 evaluation-completion 模块只为已终止运行做 readback/完成收据。当前没有可执行的 RFF saved-eval 命令。

此前真实 candidate execution 在 CANDIDATE_TRUTH_JOIN_DOMAIN_MISMATCH 处失败。之后 PR5 已接受 RFF 路线本地的 truth-join helper；当前交接包错误地遗漏了该接受证据，现已补入。旧失败涉及的真实 row/key 仍未知，不能据此撤销已接受的 helper，也不应要求重造 join 规则。PR5 的独立 Mac receipt 只覆盖 29 个 synthetic cases；完整 worker/L04 与历史真实失败行仍未验证。PR5 已接受的 worker 与历史 candidate worker 在附件中分开放置，且不改动历史执行或其 binding。

## 冻结研究与既有执行

RFF 冻结合同 SHA256：e6c1509955730a032d183563d6ffcf2501a587dd5734426f35fc59b222491135。既有 controls 和阈值保持不变：development primary 为 candidate-minus-PLUS lower bound > 0；practical BASE34 lower bound >= 0.03；promotion_now=false，2024 暴露期最高只能标为 DIRECTION_ONLY。

既有真实运行报告 SHA256：1fdba915fabdf41e34f68606abbadf002ff32a8f465af1a80b4c18e98365da53。该 execution 已记录 fit=1、candidate predict=1、truth decode=1，随后 join 失败；没有 candidate result、metrics 或 evaluation completion receipt。既有 RUN_STARTED 与 terminal SHA 分别为 69a41b317075cfcb21c26133401e19b8af7a435185c87d5f4cf76f7b2e24d9af 和 5fe5704e4fb63a00e1802a14ba7e09f41985342a89e4f0c301793991b80ff0cf。这里只保留之前已核对的 receipt 元数据。

原 RFF candidate binding SHA256 为 efe96e1d1046d074f545d7d53501d7281d2fad2e24b0a8f9f1ad9199f06f44d7。Prediction seal SHA256 为 4fc18f9ae2cd47d3a1a23adaadd2ddcc5db9aa97b60a1758d78f2b497cdc8bfa；其中保存的 CANDIDATE_SCORES.csv.gz SHA256 为 3b87a52e5b2d2df88e3091a2c8e3b5262f809bf6323363a31047223f91bdc006，CANDIDATE_TOP3.csv.gz SHA256 为 273504cc6152dedf2f6f88ae6fb6af5598af84340b2e954241d7b6ff6f63a78e。没有打开这些文件的任何行。

RFF binding 与 XENDCG R2 metadata 声明相同评价范围：grid_rows=169986、scoreable_rows=120084、sessions=246、selection_slots=738、known_positive_denominator=126；均引用 score_aware_metrics.py SHA256 fc93d6225c75b633981508a18c428e7649122571c7d897264d0b7da1e591eb8c。这只是静态元数据匹配，没有确认真实 scores/Top3 列、dtype 或 key 顺序一致。

## 机制阻断及代码证据

1. RFF CLI 只有 candidate 入口；它调用 worker 生成 scores/Top3，随后在同一候选执行中读 truth 并 join。代码见 CODE_ATTACHMENTS.zip:rff/src/rff_candidate_entry.py:1022,1052 与 CODE_ATTACHMENTS.zip:rff/pre_pr5_historical/src/rff_worker.py:349,370,390。这个历史 worker SHA 为 cecff1218a60c3c67405168b742f40ba76286efbd2435d8f31703375c640619d。

2. PR5 接受的 route-local RFF worker SHA 为 3ea10757a81207147e5cfb9e68e69750a0579786153e7ce58ccf342a3184058c；对应测试 SHA 为 c19f32aee9aae82919e49583ec041da97852ce5520918810ab1e14e3446980ad。独立 Mac receipt SHA 为 28f5cac31469a488987bffba4a799ba73910392bff36e74403dcfd42edd20630，报告 29/29 synthetic cases 通过。接受 helper 位于 CODE_ATTACHMENTS.zip:rff/pr5_accepted/src/rff_worker.py:80-108；其 left-domain 测试位于 CODE_ATTACHMENTS.zip:rff/pr5_accepted/tests/test_rff_truth_join.py:77-101；独立 receipt 位于 CODE_ATTACHMENTS.zip:rff/pr5_accepted/review/INDEPENDENT_MAC_REVIEW_RECEIPT.json。PR5 fixed commit links: [accepted worker](https://github.com/lexi2016/v4/blob/66a57bead52a20845e1d2af6035c7f19f0b04ed7/research/f5-rff-r3/research/hk_burst_f5/batches/full64_rff_logistic_r1_20260927/src/rff_worker.py) and [accepted test](https://github.com/lexi2016/v4/blob/66a57bead52a20845e1d2af6035c7f19f0b04ed7/research/f5-rff-r3/research/hk_burst_f5/batches/full64_rff_logistic_r1_20260927/tests/test_rff_truth_join.py). 这只证明冻结 Mac 环境上的 29 个 synthetic cases；完整 worker/L04 与旧 execution 的实际失败 keys 仍为 CANNOT_CONFIRM。

3. RFF evaluation-completion 模块只在 official terminal 后读取已完成运行信息并写 completion receipt；它不是独立 saved-score evaluator。代码见 CODE_ATTACHMENTS.zip:rff/src/rff_evaluation_completion.py:489。

4. XENDCG R2 runner 要求 R2 schema，并硬编码 XENDCG route/execution。直接传入现有 RFF binding 会遇到 schema mismatch；改成 R2 schema 后仍不匹配硬编码 route/execution。代码见 CODE_ATTACHMENTS.zip:xendcg_saved_eval/src/run_saved_evaluation_r2.py:149,156。saved_evaluation_entry 还要求新 evaluation execution、耐久的零 fit/predict RUN_STARTED、candidate execution identity-only artifacts 与 owner registry adapter，见 CODE_ATTACHMENTS.zip:xendcg_saved_eval/src/saved_evaluation_entry.py:291,310。

5. 附件中的 XENDCG R2 runner、entry 和 resource_tree 当前文件 SHA 与已绑定的冻结 SHA 不同；具体 expected/current 值保留在 ISSUE_PACKAGE.json。未追查差异原因，ZIP 仅供静态审阅，不代表可重放冻结 R2 identity。

## 最小下一步

为既有 RFF route 准备 route-scoped saved-evaluation RUN_SPEC/INPUT_BINDING 和新的 evaluation execution identity。复用现有 saved-evaluation lifecycle、score-aware metrics 与 PR5 接受的 RFF join helper；binding 必须固定 PR5 accepted worker/helper SHA 3ea10757a81207147e5cfb9e68e69750a0579786153e7ce58ccf342a3184058c，候选 execution 指向原 RFF candidate execution。原 candidate execution、旧 worker binding 与候选 artifact 均保持不变，不改 registry 旧事件。不要创建第二个 join 规则，也不要因缺少旧失败 row/key 就撤回 PR5 accepted helper。

新执行身份未冻结，故本包不给可执行命令。未来 execution 应先有唯一新 evaluation RUN_STARTED，再评价并写 terminal；fit、candidate/control predict、calibrator fit、model load 都必须为 0，且不得自动重试。truth decode 次数与 metrics/terminal receipt 链由新 contract 冻结。

## 验收顺序

1. 独立 Reviewer 检查实际新增的 route-scoped evaluator、binding 与准确源 SHA，确认绑定 PR5 accepted helper SHA、原 RFF candidate execution、冻结合同、controls、helper SHA、fresh output/trace roots 与 official lifecycle。
2. 静态确认 saved-eval 命令不会调用 candidate CLI、fit/predict 或模型加载；输出目录与候选输出隔离，失败时不自动重试。
3. 不重开 PR5 accepted synthetic join tests，也不创建第二套 join 规则。对原真实失败 execution，准确 row/key 与是否能由 accepted helper 解决仍保持 CANNOT_CONFIRM；旧 execution/binding 不变。
4. parent 接受完整 spec/binding 和命令后才启动唯一的新 evaluation execution；核验 RUN_STARTED→terminal、零 fit/predict/model-load、评价真值读取计数、controls 不变、指标与 receipt SHA 链。2024 结果上限仍为 DIRECTION_ONLY。

## CANNOT_CONFIRM

- 原失败 execution 中触发 CANDIDATE_TRUTH_JOIN_DOMAIN_MISMATCH 的真实 row/key，以及 PR5 accepted helper 对这些原始行的实际表现；本批没有读分数或 truth 行。
- RFF saved scores/Top3 与 XENDCG evaluation worker 的逐列、dtype、key-order parity；本批只读代码与 metadata。
- 可直接执行的 RFF zero-debit saved-eval 命令、新 evaluation execution ID、identity binding、parent release 与 registry append。
- PR5 accepted helper 的完整 worker/L04 行为及其在历史真实失败 execution 上的结果。
- 本地 registry 之外的 Git/外部持久化状态。

## 本批边界

没有读取 CANDIDATE_SCORES.csv.gz、CANDIDATE_TOP3.csv.gz、CANDIDATE_RAW_SCORES.npy、候选模型、evaluation truth/labels 或 registry JSONL；没有 fit、predict、model load、研究预检、测试运行或 registry 写入。此前 PR5 独立 Mac receipt 的 29/29 是已有证据；本次更正没有重跑。
