# RFF 已保存分数评价入口实施计划

> 执行方式：当前会话主控实施 metadata/worker/runner，独立并行实施 frames 和 registry adapter，最后整体独立复核。

**Goal:** 在 Issue #33 固定提交 `4c5fb40122cec7a40036bfda5e4d9516d82dcd18` 上新增 RFF saved-evaluation 入口，不改变历史 candidate 或已接受 PR #5。

**Architecture:** 新目录内提供合同准备、独立 worker、原 evaluator 组合与 official adapter 的路线适配。prepare 只读代码和元数据，不读分数、truth、模型；run 必须通过精确新 spec/binding/reviewer/parent release，之后一次零 debit RUN_STARTED、一次 worker、一次 terminal。

**Spec:** `inputs/ISSUE33.md`，冻结实验合同和 PR #5 accepted worker。

## 全局约束

- accepted worker SHA `3ea10757a81207147e5cfb9e68e69750a0579786153e7ce58ccf342a3184058c`，只调用 `_join_truth`。
- 原 candidate、绑定、scores、Top3、controls、seal、旧 registry 事件原字节保留。
- 本次实现和验收不读真实数据、不训练、不预测；合成输入与生产批准严格分开。
- 新 execution 的 fit/predict/control fit/control predict/calibrator fit/model-load 都是 0；truth parse 尝试最多 1，尝试/完成分记，未知状态不填 0。
- PLUS lower>0、BASE34 lower>=0.03；原概率与排名评价逻辑、样本和推广门槛不变；最高 DIRECTION_ONLY。
- 未来资源上限由本机主控显式填写并冻结，不自动继承旧 4线程/3GiB/1800秒。
- 新 spec/binding 与 local reviewer/parent release 是本机执行的必要输入；本会话不制造批准。

## 实施与验证

1. `src/rff_saved_eval_contracts.py`：准备和校验精确来源、预算、路径、spec、binding、review/release。`tests/test_rff_saved_eval_contracts.py` 先 RED，覆盖所有显式值与source/path/approval错配。
2. `src/rff_saved_eval_frames.py`：复用 accepted `_join_truth` 和 frozen metrics；新合成测试覆盖保存概率、Top3一致性、合法未知标签、两个控制比较与门槛，不重开 PR #5 已验测试。
3. `src/rff_saved_eval_worker.py`：保存读取快照、truth marker、真实解析计数、metrics/result/status；合成测试覆盖成功及parse/sha/输出冲突失败。
4. `src/rff_saved_eval_registration.py`：复用原 official adapter/builder/validator/guard，保护旧prefix和fit额度，新execution独立；合成registry验证唯一start/terminal、source漂移/状态未知/重复执行。
5. `src/run_rff_saved_evaluation.py`：prepare与run命令，原native/resource monitor接续、显式不自动重试、失败readback和terminal receipt。新spec/binding身份必须由本机独立确认。
6. 独立全增量review；生成完整after、正反patch、SHA映射、本机步骤和回滚说明；发布至专用修复分支，保持Issue真实评价状态未完成。

## 独立审查重点

- 旧PASS回执不能批准新source/spec/binding。
- 输出/trace/metadata路径不能覆盖任何历史输入或registry。
- 分数parse失败不能触发truth读取；truth途中失败必须保留attempt=1。
- 本地原evaluator依赖settings与官方validator依赖policy必须加入来源闭包，不能猜参数。
- RUN_STARTED落盘后异常不重试start；terminal不明时只读回并保留具体错误。
