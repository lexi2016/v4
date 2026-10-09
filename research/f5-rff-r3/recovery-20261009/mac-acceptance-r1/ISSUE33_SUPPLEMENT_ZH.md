# Issue 33 补充：本机 prepare 被 receipt pin 身份类型阻断

**状态：P1 已由独立 Reviewer 确认；当前仍 BLOCKED。** 本补充用于附加到同一 Issue 33。它记录了固定 commit 的源码问题、本机只读回执证据和合成测试盲区；没有修改源码、旧 candidate 文件或 registry，也没有再次运行 prepare。

根目录的 `PREPARE_BLOCKER.md` 与 `PREPARE_ATTEMPT_RECEIPT.json` 是初次 prepare 阻断时的时间点记录，创建时独立 Reviewer receipt 尚未生成。其 pending-review 状态和“尚未查看 terminal”只描述初次尝试；本补充附有后来确认的双回执 metadata 与最终独立审阅结论。

独立 Reviewer 的结论为 P0=0、P1=1、P2=0，`REVIEWED=BLOCKED`、`BEHAVIOR_VERIFIED=false`。Reviewer 记录 142 个 synthetic tests 通过；但这些测试没有用正式发布的 PINS 检查旧 receipt 文件，因此不能解除本机 prepare 阻断。完整独立 receipt 位于 `/Users/lexi/Desktop/学习/因子工厂/handoffs/F5_RFF_SAVED_EVAL_R1_LOCAL_20261009/review/LOCAL_ACCEPTANCE_BLOCKER_RECEIPT.json`，SHA256 `61d4e579ff139e01eb3ec65d481b51ecd7dead72041bc61db10e9d3d4d05eef1`。

## 复现

本机冻结解释器以 metadata-only 命令读取源码与回执元数据，返回：

```text
{"status": "CANNOT_CONFIRM", "error_type": "SavedEvaluationError", "error": "BOUND_FILE_SHA_MISMATCH:/Users/lexi/Desktop/学习/因子工厂/handoffs/F5_RFF_RESUME_EXECUTION_20260928/execution/F5_FULL64_RFF_LOGISTIC_R1_20260927_RESUME_20260928_01/candidate_output/CANDIDATE_START_RECEIPT.json:0292f37c00181b3447d0cda65f0b24096e9100ace35fb024ff5f579248e64a03:69a41b317075cfcb21c26133401e19b8af7a435185c87d5f4cf76f7b2e24d9af", "automatic_retry": false, "safety": {"research_only": true, "production_allowed": false, "buy_gate_updated": false, "orders_sent": false}}
```

实际候选启动回执文件 SHA256 为 `0292f37c00181b3447d0cda65f0b24096e9100ace35fb024ff5f579248e64a03`；其 `start_event_sha256` 字段为 `69a41b317075cfcb21c26133401e19b8af7a435185c87d5f4cf76f7b2e24d9af`。Issue33 第 43 行将该值称为 RUN_STARTED event SHA。实际候选终止回执文件 SHA256 为 `c8dc367a7acf7196c4951074759e8c8015c071d6c2d7e6cf8b3afd3bf01f6ca1`；其 `terminal_event_sha256` 字段为 `5fe5704e4fb63a00e1802a14ba7e09f41985342a89e4f0c301793991b80ff0cf`，而其 `start_receipt_sha256` 正确指向启动回执文件 SHA `0292f37c00181b3447d0cda65f0b24096e9100ace35fb024ff5f579248e64a03`。两个原始 JSON 回执作为 metadata-only 附件原样收录，没有包含真实评分/真值数据。

## 代码位置与独立发现

- `candidate/src/rff_saved_eval_contracts.py:40-41` 将 `69a41b317075cfcb21c26133401e19b8af7a435185c87d5f4cf76f7b2e24d9af` 和 `5fe5704e4fb63a00e1802a14ba7e09f41985342a89e4f0c301793991b80ff0cf` 放入 `candidate_start` / `candidate_terminal` pin。
- 同文件 `:98-102` 的 `file_record()` 对完整文件字节求 SHA256；`:493-494` 将上述 pin 作为文件 SHA 预期值传入。启动 receipt 的比较先失败，故本机没有生成新的 `RUN_SPEC.json` 或 `INPUT_BINDING.json`。
- `candidate/tests/test_rff_saved_eval_contracts.py:299-317` 的 `refresh_old_binding()` 为 synthetic receipts 重新计算文件 SHA 并覆盖 fixture pins，随后 `active()` 用这些动态 fixture 值 patch `contracts.PINS`。因此 142 项 synthetic PASS 未检出发布 PINS 的 event/file SHA 类别错误。

Reviewer 的本机 readback 认定这是 **event SHA 与 receipt-file SHA pin 类别混用**；两份原 receipt 的内部链仍一致，现有证据不支持“旧材料损坏”。本机 prepare 在源码第 497 行读取 registry 之前停止，没有执行 append。未读取真实 score/truth 行，未启动 worker、fit、predict 或 model load。

## 最小修复与复验要求

1. 分别固定完整 receipt 文件 SHA 与 RUN_STARTED / terminal event SHA。
2. 对文件校验使用完整文件 SHA；单独检查 start receipt 的 `start_event_sha256`、terminal receipt 的 `terminal_event_sha256`，并验证 terminal receipt 的 `start_receipt_sha256` 等于完整 start receipt 文件 SHA。
3. 保留现有身份和源码 SHA guard，不删除、不绕过。
4. 增加使用发布 PINS 和冻结原始 receipt metadata 的回归测试；修复后重新生成本机 `RUN_SPEC`/`INPUT_BINDING`，再交独立 Reviewer 复核。

本机配置、两份旧回执、独立 Reviewer receipt 与最小源码/测试随 `CODE_ATTACHMENTS.zip` 附上。机器证据在 `ISSUE33_SUPPLEMENT.json`，附件清单在 `CODE_ATTACHMENTS_MANIFEST.json`。固定源码 commit 为 `3764032a16f3cd9db88ec0d0ca122fd5d01c167b`，commit tree 为 `a4568e573da77422f963ce4cf2c6d46faaaa0cc0`，after subtree 为 `f6368e2deafc48100e1baffb9c93985456cec54d`。
