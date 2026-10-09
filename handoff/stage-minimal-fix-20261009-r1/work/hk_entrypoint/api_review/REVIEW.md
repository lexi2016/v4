# API 读取与原 receipt writer 的独立审查

结论：**PASS_SOURCE_SLICE_WITH_HISTORICAL_SUPPORT**。本轮实际源码切片上的 reader 及条件式 consumer 接线可交付继续本机核验；此结论不代表 Mac 现役版本、API/UI、自然阶段或部署验收通过。

审查者：`/root/stage_hk_and_entrypoint`；reader 作者：`/root`；writer 作者：`/root/stage_receipt_binding`。审查者只写独立测试、证据和报告，没有修改产品候选。固定输入 commit：`28ab2d35020adf031f10f38c1040514fc81b6d66`。

## 最终源码身份

| 文件 | SHA256 | 身份 |
|---|---|---|
| `api_ui/after/source/actual_api/stage_center/execution_evidence.py` | `bd79b1844568a79750ccce6c547cfe08f651291f1863e213fb25629d34a67b79` | 本轮 actual API 前像上的候选 |
| `api_ui/after/conditional_api/stage_center/consumer.py` | `bc428dc5b3747b0eb1e3c4d68ae4e6f2441882393cfa4a31e4c4c962b924c234` | 10/5 历史参考上的一行条件件 |

consumer 前像 SHA256 为 `61f8a3541aa7a2e698cc4374385e3d20d41b40ffd5a3cd7d87c9494cb8726cf4`。其唯一增量是原调用传入 `selection_store=self.store`。不能把这个历史文件当作已核 Mac 当前 consumer，更不能整文件覆盖身份不同的当前 API。

## 独立复现与处理

第一轮独立真实 Store 往返共 32 项，26 通过、6 失败；失败覆盖三类问题、每类各执行 actual/canonical writer。原始失败保存在 `evidence/independent_initial`，没有改写成通过记录。

1. **P2 调用时钟来源字段丢失。** 原 slot writer 产生 `runner_clock_source=OWNER_RUNNER_INVOCATION_UTC`，reader 读取另一个不存在的字段，导致调用时刻存在但来源为空。作者修正投影后，真实原 slot 的 NOOP 写入与读取往返通过。
2. **P2 结果与引用的状态口径不一致。** 未知状态已被结果摘要拒绝，receipt 引用和 trio 却仍可被标为绑定。作者将具有字符串类型检查的状态白名单统一用于三个入口。
3. **P3 异常状态形状。** `status=[]` 会使集合检查抛异常。固定的历史 consumer 通常先转字符串，此探针对当前未知调用身份提供防御性覆盖。相同 typed helper 已解决。

修复后原 32 项全部通过；再加入历史 consumer 原调用 AST →真实 SelectionStore 的两项集成测试，最终独立测试 **34/34** 通过。API 作者的最终含 consumer 套件由审查者另行执行，**28/28** 通过。所有最终测试记录均包含命令、平台、时间、源码 SHA、标准输出、JUnit，以及测试前后源码未变化的核对。

## 已验证的具体边界

- 原 SelectionStore 真正 `publish`、`read_verified` 和 `_verify_run`，实际写出并核验 artifact/manifest/receipt；没有用 fake `_verify_run` 为这组独立往返冒充真实验证。
- reader 缺 root、缺 receipt、非法 JSON、日期身份错误或安全标志错误时，独立已验证选股的 10 行仍可展示；HK 仍保留预选输入缺失原因。
- receipt archive 在原 receipt root 下核对 exact slot 路径、文件字节 SHA、内容及显式 UTC owner 写时钟，只返回 `OWNER_HISTORY_SHA_BOUND`。完整绑定时仍保留 `NO_INDEPENDENT_RUN_RECEIPT_SHA_BINDING`，`execution_verified`、`natural_verified` 始终为 false。
- 只有调用方传入的既有 SelectionStore 可以核对选股三件套。没有 store 返回 `SELECTION_STORE_NOT_BOUND`；另一个空 store、绝对路径、其他日期路径都不能成为有效绑定。
- 文件字节 SHA 与 JSON canonical SHA 独立。重新排版 manifest 后，原 Store 的 canonical 核验仍可通过，新 receipt 的字节绑定会明确冲突。
- 原 Store 核验期间 current receipt 被原 writer 更新，reader 会报告 `RECEIPT_CHANGED_DURING_READ` 并撤销 current archive/trio 的完成绑定，不把旧观察当成当前证明。
- 真正缺少当前输入或选股三件套时，writer 保留已有结果和失败原因，不捏造 HK/A 输入，不把 owner 新写入时间变成旧数据的计算时间。

定位：最终 reader 的严格计数与状态检查位于 24–30 行，结果独立摘要位于 63–85 行，owner history 核验位于 88–118 行，原 Store 与双 SHA 核验位于 121–176 行，时钟来源映射位于 238 行，并发 current 重读位于 283–294 行。源码为本报告上方所列固定 SHA 的文件。

## 测试支持与边界

`quote_fields/SUPPORT_MANIFEST.json` 对 13 个支持文件逐一记录固定 commit、repo 路径、SHA 和身份。`selection.py` 与 `contracts.py` 来自本轮 actual Stage 原件；publication/verification、IO、calendar 是另行固定的历史参考；namespace 是声明的测试替代。所有支持文件在 fixture 初始化时再次按 SHA 核对。当前完整 Mac app 未提供，因此本测试既不是完整现役 import，也不是网络采集或自然运行。

consumer 条件件仅执行该原调用 AST 以核实既有 store 的传递，并核对整文件唯一差异。Mac 当前 consumer 前像未核；当前选择 Store、receipt root 和构建引用仍需本机实查。5 秒真实负载预算、服务发布、HTTP/UI、自然时段回执与历史缺失输入重建均不在本独立结论内。

## 复跑

```bash
python /workspace/scratch/25c09a595aec/stage_minimal/work/hk_entrypoint/run_independent_review.py --suite api --label another_independent_api_run
python /workspace/scratch/25c09a595aec/stage_minimal/work/hk_entrypoint/run_independent_review.py --suite api-author --label another_api_author_run
```

证据：`evidence/independent_with_conditional_consumer`、`evidence/independent_author_with_consumer`。初始失败与中间修复通过记录均保留。当前未发现未解决的 P0/P1/P2 代码问题。
