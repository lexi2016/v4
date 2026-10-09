# 原 Stage receipt writer 四文件独立审查

结论：**PASS_SOURCE_SLICE_WITH_HISTORICAL_SUPPORT**。未发现未解决的 P0/P1/P2 产品代码问题。候选可以进入严格版本匹配的本机复跑阶段；尚未完成发布、服务、页面或自然运行验收。

审查者：`/root/stage_hk_and_entrypoint`；作者：`/root/stage_receipt_binding`。审查者没有修改产品文件。固定输入 commit：`28ab2d35020adf031f10f38c1040514fc81b6d66`。

## 冻结源码

| 文件 | SHA256 |
|---|---|
| `receipt_binding/after/source/actual_stage/stage_center/_runner_parts/runner_receipts.py` | `d634647ef5f50620a4b98a696a61b7d2d1491e9f7c2c351e0e621168a2e03f9f` |
| `receipt_binding/after/source/actual_stage/stage_center/_runner_parts/slot_execution.py` | `447a07af0470b86436f7aba128f782429a7b8e7fcf8dad8b92e6d01b7cfb6d96` |
| `receipt_binding/after/source/canonical/stage_center/_runner_parts/runner_receipts.py` | `e7877b8c94b118a224b7b8b762be51b02f8aa24b2341e92d2677289961d66e20` |
| `receipt_binding/after/source/canonical/stage_center/_runner_parts/slot_execution.py` | `6e50b9406bc09d9a6c4c73ae1b96a2bd73a7d82a0ae00df30371026edadf7fd8` |

四个 SHA 与作者冻结消息一致，独立测试前后再次核对未改变。

## 独立证据

| 验证层 | 结果 | 证据目录 |
|---|---:|---|
| 作者两份精确候选测试，独立复跑 | 39/39 | `evidence/independent_author_exact_candidate_files` |
| 独立原 Store／最终写入／deadline／局部恢复 | 7/7 | `evidence/independent_finalization` |
| 真正 SelectionStore writer→reader＋条件 consumer | 34/34 | `../api_review/evidence/independent_with_conditional_consumer` |
| 原 slot 调度、采集、评分调用 AST 保持 | actual 与 canonical 均相等 | `SLOT_ALGORITHM_INVARIANTS.json` |

AST 检查移除的内容严格限于：新增 helper import、调用时钟变量、input binding 初始化与捕获、局部 receipt 包装函数；再将六处包装调用映射回原 `self._write_receipt`。归一后两个变体各自的**完整 slot 文件 AST**与对应前像完全相等。这证明该四文件改动没有挪动原采集、选择、评分、分支及输出控制流。

## 写入链与失败处理

actual `runner_receipts.py` 62–86 行仍由原 owner 方法负责最终 receipt；先经过原 deadline 的 `before_receipt`、原作用域合并，再核原选股 Store，写归档，最后写 current receipt 并通知原 deadline。`_archive_owner_receipt` 从 294 行开始，移除传入旧 history、记录真实 UTC owner 写时刻、在原 root 的该 slot 下按 bytes SHA 创建独立副本，并核读回内容。原归档被保留。

独立 7 项包含：

- 真实固定历史 `end_to_end_deadline.complete_receipt` 超过预算触发最终 owner rewrite，最终落盘状态为 `PARTIAL_COMMIT_RETRY_REQUIRED`；两个原归档都保留，reader 绑定最终 current，同时 A 10 行仍可见。
- 新归档写成功但 current pointer 写失败，旧 current 的全部字节不变；额外归档不被 reader 误认为新的 current 完成证明。
- actual 的 HK 局部恢复保留原 A market 完整对象、原 A 输入引用和原 A 三件套引用，拒绝恢复载荷夹带的另一套 A 值；失败 HK 不从旧值继承输入或选股绑定。
- 原 Store 三件套在写时再次核验失败，保留旧已计算结果及明确 binding error，不为缺失的 trio 生成假绑定。

实际 slot 的调用时刻记录在 `slot_execution.py` 30–42 行，输入引用捕获在 128–130 行。调用时刻仅描述本次 owner 进入原 slot 的时间；NOOP 复用不会因此变成新计算或自然完成。A 输入的 canonical 与文件 byte SHA 按原 CandidateInput 字段分别命名；HK StageUniverseBinding 未暴露完整 trio 时继续保留 `NOT_EXPOSED_BY_STAGE_UNIVERSE_BINDING`，没有新增或伪造资格输入。

原 dispatcher 的锁与最后写入回调已在冻结的 `HK_AND_ENTRYPOINT_REVIEW.md` 核对：其最终改写走同一 owner `_write_receipt`，deadline final rewrite 回调也回到该方法。这个引用仅证明所给固定历史源码的路径；不宣称当前 Mac 运行 helper 已与之匹配。

## 测试入口发现

最初按作者 README 的整目录命令执行时，实际为 **39 PASS + 2 RED**。`tests/test_receipt_baseline_gap.py` 仍在收集，并明确加载基线源码，因此两项失败证明原缺口，并非四文件候选回归。该输出保存在 `evidence/independent_author_suite`。

作者随后冻结精确两份候选测试，并增加 `pytest.ini` 的 `python_files` 限定。审查者独立按两文件命令复跑为 **39/39 PASS**。最终交付应只将 `test_owner_receipt_binding.py` 和 `test_slot_receipt_wiring.py` 作为候选成功套件；基线 RED 脚本与日志留在 evidence。不得把之前 41 项的两项失败删改为通过，也不得把偶然收集范围当成产品测试成功。

## 证据强度与待验收

owner archive 与选股 trio 匹配只得到 `OWNER_HISTORY_SHA_BOUND` 与选股原件绑定。它没有签名、独立运行监督者或自然时段的不可变外部证明；API 的 `execution_verified` 和 `natural_verified` 仍始终 false。

测试使用本轮 actual selection facade/contract 和逐 SHA 固定的历史 publication、verification、IO、calendar、deadline 支持；candidate acquisition 与既有 slot 查询是显式合成边界。没有完整现役 Mac import、真实行情、HK 10/8资格主表、自然运行或线上 API/UI 验收。新增 fsync/读回的真实 5 秒负载表现也必须在匹配源码的本机原入口测量。

## 复跑

```bash
python /workspace/scratch/25c09a595aec/stage_minimal/work/hk_entrypoint/run_independent_review.py --suite writer --label another_writer_author_run
python /workspace/scratch/25c09a595aec/stage_minimal/work/hk_entrypoint/run_independent_review.py --suite writer-finalization --label another_writer_finalization_run
```

共用的独立 fixture、命令、JUnit、源码身份和初始失败均随报告保存。
