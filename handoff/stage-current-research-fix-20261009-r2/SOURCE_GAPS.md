# 当前前像、输入与落地参数边界

本清单列全本包已知的应用前像边界。**27 个 conditional 条目已经有可核对的源码、最小补丁和完整 after；只有本机整文件 SHA 不属于该角色明列的 before、R1 或 after 时，才需要补交对应的当前文件内容与实际 SHA。** 另有两份 RawStore 当前实际源码尚未取得，必须与归档参考明确区分。

本清单依据本包 `SOURCE_GAPS.json`、`SOURCE_MAP.json` 及 `evidence/REFERENCE_SOURCE_INDEX.json` 生成；后者与修复工作目录的 `SOURCE_INDEX.json` 字节一致。这里的来源状态描述 Chat 取得的固定快照，**不表示 Chat 已读取任何 Mac 当前文件**。`SOURCE_MAP.json` 仍是工具检查和应用时的机器可读依据。

## 1. 三个源码根分别核对

| 角色 | 用户给出的源码根 | 边界 |
|---|---|---|
| `actual_stage` | `/Users/lexi/Desktop/学习/agents调试/V4_HK_STAGE_RECOVERY_20261003/issue23_runner_helper_r3/stage_r1_binding_candidate_r3/app` | 实际 Stage owner；独立 canary 应用此角色补丁。 |
| `canonical_stage` | `/Users/lexi/Desktop/学习/v4_app` | canonical 已有 dirty 且与 actual 不同；仅在原发布链需要时，用自己的前像及独立变体。 |
| `actual_api` | `/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app` | 实际 API 与现有 Vue；不使用 r5c 拆分候选，不覆盖 canonical API。 |

本包共列 42 个角色/文件条目：actual Stage 18、canonical Stage 18、actual API 6。其中 conditional 为 12＋12＋3，已有明确 supplied 来源为 4＋4＋3，Stage 两个新模块在两个变体中共计 4 个 `NEW_FILE` 条目。以下分别列出，避免把“历史条件快照”“已提供快照”“新文件”或“当前字节未知”混为一类。

### SHA 的含义与应用规则

- **B** 是 `before/角色/相对路径` 的恢复前像；**R1** 是 `r1/角色/相对路径` 的参考前像；**after** 是本轮完整交付。全部数字均为文件原始字节的 SHA256，不是 Git blob SHA1、JSON canonical digest 或远端分支名称。
- B 与 R1 相同的条目只列一个 SHA。表中所有 after 同样是工具可接受的已应用状态；after 与 R1 相等表示该文件沿用 R1 修复。允许同一源码根中各文件分别处于已列出的 B、R1 或 after 状态。
- `tools/stage_patch.py prepare` 会对所选角色的全部目标逐个检查，一次列出不匹配；通过后仅建立新的物理独立 canary。当前源不匹配时，提供该文件完整内容及实际 SHA，由 Chat 适配补丁；不要求 Mac 编写业务逻辑。不能用另一个角色中“同名”的文件消除不匹配。
- 新增文件只接受“原路径不存在”或“已等于本包 after”。`None` 在机器清单中表示预期原文件不存在，不是未知 SHA。若当地已有不同内容，同样必须保留并核对。
- 固定来源列中的 B/R1 是分别追溯的参考字节。表内 after 的完整内容均在 `after/角色/相对路径`；不得由历史来源路径推断当前 Mac 已与之相同。

## 2. 历史条件前像：实际 Stage，12 个文件

这些条目均为 `HISTORICAL_CONDITIONAL`，与 `SOURCE_GAPS.json` 的 `actual_stage` 条件项完全对应。

| 相对路径 | 可接受的 before / R1 SHA256 | 最终 after SHA256 | 前像来源 |
|---|---|---|---|
| `ops/_run_stage_center_nodes_parts/deadline_supervision.py` | B：`95ce916246f3376fc3618c0890ee1f76f2b0231c50d77fe5440a9b956884a674`；R1：`1f65476c5a274195b789a3529a3e95821bfcf81278c6ac72e01c52655932cf08` | `1f65476c5a274195b789a3529a3e95821bfcf81278c6ac72e01c52655932cf08` | B：S01；R1：S02 |
| `ops/_run_stage_center_nodes_parts/node_entry.py` | B：`f9530f010055476e17d87e93198e28d3f4943ed34255a2419130eb9f39deb6ed`；R1：`3a40b79ecea876997aad9272205ebf61289af2a17162057fa680174c50e74fd2` | `2a02a0a3796a8153998fea7d1270aeb580c17928cc61c9e48bbf77bf84b7aebf` | B：S03；R1：S04 |
| `ops/_run_stage_center_nodes_parts/runtime_arguments.py` | B=R1：`2e40c84a30d9cabf047fefb5caec14f8b569d24e54a7f50c16211f0c0fda53ec` | `9a28fd1ff484e88864fc2aed2bddf50804d56a5bb91b2bb10a84be0fbc344e5e` | S05 |
| `stage_center/_live_collectors_parts/collector_registry.py` | B=R1：`b8c366267f611ff76d0228093a9d826ee7c367b938aa4ab098f022a687245999` | `ffbb149879c549d389ae4cc16e18a0e813808e0269c980e4f5fc9ee8db5d8eeb` | S06 |
| `stage_center/_live_collectors_parts/hk_minute.py` | B=R1：`b6c78a4ffd7193d0e1afeee530a1c4c123e72a20ba3bc9f8183727dcca58a179` | `4225089d076fe3db535b671879ce49f51bb2c453833edcca3f72eda7db86ee4a` | S07 |
| `stage_center/_live_collectors_parts/selection_builder_registry.py` | B=R1：`5b315c482723f4bbfb187e36241ea422f2a59518a2056be037d1fdbe2f00eb22` | `62738552347913633aca16a805a163bf3346cdf8ab0cf79eed3c8be75c9fe522` | S08 |
| `stage_center/_runner_parts/configuration.py` | B=R1：`713ac5b8ac81fe186904eca38c8e7a28a2edb83a0cf98766546a09f7169c7486` | `410fffc5198803922b97f4f013fccf6ef8510fed04a2435445cee0a02875dbc9` | S09 |
| `stage_center/_runner_parts/hk_candidate_authority.py` | B=R1：`1fd933e8436e4316832c29f89da16c1ccf3ed78b14ee853262ed758e476d2f95` | `822ab3c2f03f7296030dd642c4816a484fcf1fa3bcff61db800bb9e0789eda69` | S10 |
| `stage_center/_runner_parts/hk_input_validation.py` | B=R1：`92e8fb2be06e6530c33f3cf2f5b44f29b0bcf7875e6a5902260f8be4c814f735` | `d9ac01e284bbb9aaf52a7cdca10dde7142be1b3eb9a23bf0c72c319f581f0b3a` | S11 |
| `stage_center/_runner_parts/selection_input_validation.py` | B=R1：`23e8afa65fa9fe0b24baefb8e778af3c475e1affaa34a2734ea80ea0aca9d44c` | `0ca0969d7ddc055495fec453d8a1fe38ac81ffcdb3b47a206e9f8f1beff1ee21` | S12 |
| `stage_center/_runner_parts/tick_planning.py` | B=R1：`c27cb9717ec2940364d1e1186529e6df1b37b07aae0c56f65334f6f9bf06dd15` | `9e8eba3d860c10b7bbfe3e8af242dbf331612b42e070097dab539bfd3e9577be` | S13 |
| `stage_center/runner.py` | B=R1：`2dbfa90c42cb4bd3b9b78d20bfbd1ac15eba0f3a18dd1105b32decd04a2b5232` | `14941d742e9c552bad96b7b0c979fdf9c387894b120263c359a49c09a9537865` | S14 |

## 3. 历史条件前像：canonical Stage，12 个文件

以下是 canonical 自己的前像和 after。特别是 `node_entry.py`、`hk_minute.py`、`selection_builder_registry.py`、`tick_planning.py` 与 `runner.py` 的前像，与 actual Stage 不同；本包已分别实现相同修复并保留各自旧分支。

| 相对路径 | 可接受的 before / R1 SHA256 | 最终 after SHA256 | 前像来源 |
|---|---|---|---|
| `ops/_run_stage_center_nodes_parts/deadline_supervision.py` | B：`95ce916246f3376fc3618c0890ee1f76f2b0231c50d77fe5440a9b956884a674`；R1：`1f65476c5a274195b789a3529a3e95821bfcf81278c6ac72e01c52655932cf08` | `1f65476c5a274195b789a3529a3e95821bfcf81278c6ac72e01c52655932cf08` | B：S01；R1：S15 |
| `ops/_run_stage_center_nodes_parts/node_entry.py` | B：`2343cd5e250aaa05acc698ba2daf34220f13ffb5543c655df799fdb3bd7fe464`；R1：`0efb31e207a7282eea9308c81c69c7bfd0f4c989d03d03acc9407e430f832fe6` | `3cdf8d10d86119c60bd1416f34935751452712a9e6805d8fbd9948fd26ea33b8` | B：S16；R1：S17 |
| `ops/_run_stage_center_nodes_parts/runtime_arguments.py` | B=R1：`2e40c84a30d9cabf047fefb5caec14f8b569d24e54a7f50c16211f0c0fda53ec` | `9a28fd1ff484e88864fc2aed2bddf50804d56a5bb91b2bb10a84be0fbc344e5e` | S05 |
| `stage_center/_live_collectors_parts/collector_registry.py` | B=R1：`b8c366267f611ff76d0228093a9d826ee7c367b938aa4ab098f022a687245999` | `ffbb149879c549d389ae4cc16e18a0e813808e0269c980e4f5fc9ee8db5d8eeb` | S06 |
| `stage_center/_live_collectors_parts/hk_minute.py` | B=R1：`397818be00edff0d203e3c6763f4e5c0447a61a85142cde232c6724114298ca0` | `3fc328ada99143c801a5a4312dbe87187b2970cc016a4330568315d6afe8afa1` | S18 |
| `stage_center/_live_collectors_parts/selection_builder_registry.py` | B=R1：`8b3552498b125ae90c56964799f3cf0e644a077243f7be4c37ea23261214379a` | `d6a9383c35782e006f6ba71e133e1e231f22c93fdfb3234ab075f8316731e022` | S19 |
| `stage_center/_runner_parts/configuration.py` | B=R1：`713ac5b8ac81fe186904eca38c8e7a28a2edb83a0cf98766546a09f7169c7486` | `410fffc5198803922b97f4f013fccf6ef8510fed04a2435445cee0a02875dbc9` | S09 |
| `stage_center/_runner_parts/hk_candidate_authority.py` | B=R1：`1fd933e8436e4316832c29f89da16c1ccf3ed78b14ee853262ed758e476d2f95` | `822ab3c2f03f7296030dd642c4816a484fcf1fa3bcff61db800bb9e0789eda69` | S10 |
| `stage_center/_runner_parts/hk_input_validation.py` | B=R1：`92e8fb2be06e6530c33f3cf2f5b44f29b0bcf7875e6a5902260f8be4c814f735` | `d9ac01e284bbb9aaf52a7cdca10dde7142be1b3eb9a23bf0c72c319f581f0b3a` | S20 |
| `stage_center/_runner_parts/selection_input_validation.py` | B=R1：`23e8afa65fa9fe0b24baefb8e778af3c475e1affaa34a2734ea80ea0aca9d44c` | `0ca0969d7ddc055495fec453d8a1fe38ac81ffcdb3b47a206e9f8f1beff1ee21` | S12 |
| `stage_center/_runner_parts/tick_planning.py` | B=R1：`b4faf61c9b750538d714a23fae1b565c3d387a236f42cee379dcf8c966194711` | `163151b19c8f06558bb889092c73209a569c569df5aa97c1a86cdfd28dc6d6ac` | S21 |
| `stage_center/runner.py` | B=R1：`d36cc60c538f23ab0f48c7387523d83ed5cebbdc67c0dd630e671f98ecdffa48` | `081961b37939fa431bd6613b892b2358a56a13c78cb54f72fc5cd747fc320073` | S22 |

## 4. 历史条件前像：实际 API / Vue，3 个文件

这三份前端文件来自已固定的历史源码；是否等于 Mac 当前 Vue 源码，由本机字节预检确定。它们不构成采用 API 拆分候选的授权或依赖。

| 相对路径 | 可接受的 before / R1 SHA256 | 最终 after SHA256 | 前像来源 |
|---|---|---|---|
| `apps/web/src/App.vue` | B：`995a680995cc42feadeaa8d2bdd44294c8ec782a908d664c698faf69d4cf02a1`；R1：`e13a92e7f990ef18de0909edf0d2644410ba55194b21b583d43b76d648801dc5` | `8351d35f6c5205e5341f393e76f89ebeadba1adc94177ac5df3cec091913f31c` | B：S23；R1：S24 |
| `apps/web/src/components/review/StageExecutionEvidencePanel.vue` | B：`07188178bbcd5ae2b01b9d6c1ef9dffd7b94f1b27f0211501cc2464566c5bc8b`；R1：`6cb4aecf34fe69a0b95af9075bfabbcd0c504dc29026cb31edd17ef83f764a6a` | `a6df35e056f033ac3c978f37b099472b6eb24b73bb2ca4e213c76c2ad4ffaa9c` | B：S25；R1：S26 |
| `apps/web/src/contracts/runtime.ts` | B：`9a882a174b433488684b05781ade00beb665706e962f753700960a4250d13419`；R1：`c440de3ff964daa01994cbcd04d9b3ce1f417737a39034520c478ef83448bebe` | `884f46b3e54c5bd66e83ac5f8e5aba18712f5703ccf8dfb6959be860bc4b0095` | B：S27；R1：S28 |

## 5. 已有 supplied 来源的其余目标，11 个条目

以下不在 27 个 conditional 项之中，但应用时仍做相同的整文件 SHA 核对。`SUPPLIED_SOURCE_SNAPSHOT` 或 `SUPPLIED_CURRENT_API_SNAPSHOT` 表示已取得对应包内固定快照；不能解读为本轮读过当前 Mac 文件。

### actual Stage：4 个

| 相对路径 | 可接受的 before / R1 SHA256 | 最终 after SHA256 | 前像来源 |
|---|---|---|---|
| `stage_center/_runner_parts/runner_receipts.py` | B：`d3d9e69230b00a2864eae106f1c5c89ea0d383e20c2e87d655d4cabd273bbc83`；R1：`d634647ef5f50620a4b98a696a61b7d2d1491e9f7c2c351e0e621168a2e03f9f` | `264c3de7e9463508e68b01e24cc12f86e330f14ab92b51120b1ad196e63683e4` | B：S29；R1：S30 |
| `stage_center/_runner_parts/slot_execution.py` | B：`278085fb1effdc9dcf5c5dc9626d68faea0bc53c44f66be4eb89f9a0415fc07a`；R1：`447a07af0470b86436f7aba128f782429a7b8e7fcf8dad8b92e6d01b7cfb6d96` | `16d34ea2bf095769775fb829b3036c65058689b31c7a4262908e10c52f258666` | B：S31；R1：S32 |
| `stage_center/_selection_parts/a_auction.py` | B：`d0a96edcb4d87f223b117917a8f0d68276bd088a88abe8f787d245c8e1c669ad`；R1：`01b00f748daa0ef7b0502805d977d883b20616c2070aa35685744af8f9131af1` | `01b00f748daa0ef7b0502805d977d883b20616c2070aa35685744af8f9131af1` | B：S33；R1：S34 |
| `stage_center/_selection_parts/a_live.py` | B：`b7faa3286df4f0312075c7a4563d3f4deed463d3f10ab2c4902967e8d5d7781d`；R1：`4225b27df7067663da42b635773bf90e94b4601fc2478b8decb5c635f77d86a0` | `4225b27df7067663da42b635773bf90e94b4601fc2478b8decb5c635f77d86a0` | B：S35；R1：S36 |

### canonical Stage：4 个

| 相对路径 | 可接受的 before / R1 SHA256 | 最终 after SHA256 | 前像来源 |
|---|---|---|---|
| `stage_center/_runner_parts/runner_receipts.py` | B：`af4322e65f21a4e14cc2680a63a2d93ad9bab855b235c7ef0751704549d986d5`；R1：`e7877b8c94b118a224b7b8b762be51b02f8aa24b2341e92d2677289961d66e20` | `d4a547e5f599783ecfb26c6dba5933f48b0eb1759870494ded7a8895e3a028df` | B：S37；R1：S38 |
| `stage_center/_runner_parts/slot_execution.py` | B：`86ea1de7e32e6f29deb6622b4af37b4723e0b086d4c700cd513671ceed719d8a`；R1：`6e50b9406bc09d9a6c4c73ae1b96a2bd73a7d82a0ae00df30371026edadf7fd8` | `88fa56f999fd0a08efeadd95c584930d8c4ac2ac79bca5d15bae2c37cfb6005e` | B：S39；R1：S40 |
| `stage_center/_selection_parts/a_auction.py` | B：`d0a96edcb4d87f223b117917a8f0d68276bd088a88abe8f787d245c8e1c669ad`；R1：`01b00f748daa0ef7b0502805d977d883b20616c2070aa35685744af8f9131af1` | `01b00f748daa0ef7b0502805d977d883b20616c2070aa35685744af8f9131af1` | B：S33；R1：S34 |
| `stage_center/_selection_parts/a_live.py` | B：`b7faa3286df4f0312075c7a4563d3f4deed463d3f10ab2c4902967e8d5d7781d`；R1：`4225b27df7067663da42b635773bf90e94b4601fc2478b8decb5c635f77d86a0` | `4225b27df7067663da42b635773bf90e94b4601fc2478b8decb5c635f77d86a0` | B：S35；R1：S36 |

### actual API：3 个

`apps/api/v35_api/app.py` 与 `stage_center/consumer.py` 的 B 来自 `41a9242d400acec08af3934d1da314b1626a1bcd` 中明确标为 `active_api_issue32` 的 source snapshot。这里只取实际 API 源码作为修复前像，未激活或采用 r5c 拆分实现。`consumer.py` 的另一可接受 R1 SHA 由本包 `r1/actual_api/stage_center/consumer.py` 明列；当前 SOURCE_INDEX 条目指向上述 B，因此本清单对该 R1 仅引用包内文件，不伪补远端来源。

| 相对路径 | 可接受的 before / R1 SHA256 | 最终 after SHA256 | 前像来源 |
|---|---|---|---|
| `apps/api/v35_api/app.py` | B=R1：`5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5` | `bc517ea25961fa82fa5981a944445c3a7c5a361b44a815b90c46f1f91da39adc` | S41 |
| `stage_center/consumer.py` | B：`61f8a3541aa7a2e698cc4374385e3d20d41b40ffd5a3cd7d87c9494cb8726cf4`；R1：`bc428dc5b3747b0eb1e3c4d68ae4e6f2441882393cfa4a31e4c4c962b924c234` | `9c0c566d265a9049119f7e79c967fa1a46877bfc02d05c20c36013f84ad54934` | B：S42；R1：S43 |
| `stage_center/execution_evidence.py` | B：`e4c4ea94d892158383620beab1825014f21e926b57907354475f8c9ff382704b`；R1：`bd79b1844568a79750ccce6c547cfe08f651291f1863e213fb25629d34a67b79` | `23f10554b179dea1be8df4dae7a63d1897faf238913995475f3ffd465583f5fe` | B：S44；R1：S45 |

## 6. 两个新增模块，在两个 Stage 变体中内容相同

| 相对路径 | 适用角色 | 预期前像 | 最终 after SHA256 |
|---|---|---|---|
| `stage_center/hk_current_day_research.py` | `actual_stage`、`canonical_stage` | 路径不存在；或已等于右侧 after | `e5c7385d24c21f116fabf8007d063f6d8395c7b0fda8d30c84167db4aa8c0046` |
| `stage_center/runtime_source_identity.py` | `actual_stage`、`canonical_stage` | 路径不存在；或已等于右侧 after | `56547d9edd7be06f80f9125dc0de1b55c3b97dbd9a57408df5abcc492e059d53` |

## 7. 必须一次取得的两份当前 RawStore 实际前像

**当前 Mac SHA 均为 `NOT_OBSERVED`。下面的归档 SHA 只标识 Chat 取得的旧组合，不是期望当前值，不是允许安装的替代文件，也不能用于声称现役兼容。** 所需的是 actual Stage 根下这两个当前完整文件及各自当场计算的 SHA256；来源根采用第 1 节的 `actual_stage`。

| 相对路径 | 当前 Mac 实际 SHA256 | 已取得归档 SHA256（仅参考） | 归档来源 | 本包业务补丁 |
|---|---|---|---|---|
| `stage_center/raw_store.py` | **NOT_OBSERVED；不能预填** | `2dea717cb65053c48b75468fd61508b3b61b421a6b528aa8ce93395e99aef547` | S46 | 无；`runtime_patch=false` |
| `stage_center/_raw_store_parts/receipt_identity.py` | **NOT_OBSERVED；不能预填** | `b33c496a6052b450959a9b886c79ad8d5686230e320dbc99bfd98a3e8265a8f0` | S47 | 无；`runtime_patch=false` |

归档组合的 `raw_store.py` facade 会传入 `allow_temporal_false_observation=False`，而归档 `_raw_store_parts/receipt_identity.py` helper 尚不接受该关键字。Linux 整链参考测试中的适配器只去掉**确为 False** 的该参数，再调用未修改的原严格 validator；True 或其他值仍拒绝。此适配器仅属测试支持，**没有进入任何 `after/` 业务文件，不部署，也不能据带适配器的结果声称未适配现役整包通过**。

`tools/run_checks.py` 的 Mac 独立复跑默认关闭这个测试兼容层。当前实际 facade/helper 如果本来匹配，按原代码直接复跑；如果仍不匹配，保留实际错误及上述两文件内容/SHA，由 Chat 处理匹配当前前像的代码。不要把归档文件覆盖到现役，也不要让 Mac 将测试 shim 写入业务源码。

因此一次收集所需代码材料的范围是：这两份未取得的实际 RawStore 文件，以及所选角色 SHA 预检报告中确实不匹配的具体文件。已匹配的 27 个条件条目无需重复收集，另外两个未选中的角色也不因本次 canary 而自动成为前置要求。

## 8. HK 四份输入：用户给定 pin，尚未由 Chat 读取

用户给出的实际运行目录是：

`/Users/lexi/Desktop/学习/agents调试/V4_HK_INPUT_RESTORE_20261009/candidate/futu_snapshot_current_20261009T153841+0800/`

以下 SHA 来自用户明确提供的采集记录。本包生产 reader 将在该目录中核验真实文件字节；Chat 本轮没有把这些本机路径当作可读取附件，也没有读到文件内容。测试采用独立的合成文件和测试 pin，不是对这四份真实输入的验收。

| 原文件 | 用户给定 SHA256 |
|---|---|
| `snapshot_rows_projected.json` | `9c2396530e3de8059d49354a2c330a06829a060bfbac68ff2fb726111d9e0c30` |
| `receipt.json` | `f8735ae71437a85067d7bca06b55f451bdd5dbfa7802cf2f680dfcab5f31a3ea` |
| `reference_codes_20261008.json` | `9b837e801a1fae55893f3aba3548402ac59b4d1027627f6d698a10934027fb95` |
| `FINAL_RECEIPT.json` | `3242a8ffbc4364ff96ef18a2855037521902617fa21a8c024e6f57445dbcf3f3` |

研究声明保留 `universe_as_of=20261008`、`captured_at=2026-10-09T15:38:41+08:00`、`stale_universe=true`、`CURRENT_DAY_RESEARCH_ONLY` 和当前港股通成员资格 `CANNOT_CONFIRM`。两份 receipt 的已给 SHA 只约束文件身份，未知内部字段不被假定为独立资格/PIT 证明。

这份证券资料的时间只能满足本次 `STAGE_1545_1555` 输入时间准入，不能用于早盘、13:15 或 15:00 阶段。资料中的九个返回字段不包含可用报价/OHLCV/provider_data_time；真实阶段价格仍必须由原 ExHQ 分钟链取得，不能用资料 capture 时间代替报价时间。

## 9. 尚未给出的本机运维参数

| 参数 | 当前已知边界 | 本机落地需要提供的现有值 |
|---|---|---|
| Stage 配置文件路径 | 当前真实 `--config` 指向的 JSON 路径未提供；不猜文件名或内容。 | 从现役原启动命令读取 `STAGE_CFG`；本包 `current_research.py configure` 自动生成隔离输出配置。 |
| Stage / API Python 路径 | 真实启动所用解释器路径未提供。 | 复用现役 Stage / API 原启动命令中的解释器及既有依赖。 |
| 既有发布链命令 | 实际发布命令、发布器当前入口未提供。 | 使用原 Stage、API 各自的备份、测试、切换及回滚流程接收已核 SHA 的候选。 |
| 当前 API 端口及读根 | 本包可定义隔离 canary；现役最终发布后的值需采用实际配置。 | 将现役 API 端口、同一 selection/receipt 根传给只读 `same_run_probe.py`，再做同 run 页面验收。 |

这些是定位既有运行环境的运维参数，不是要求 Mac 设计研究模式、接行情、改算法、补 reader，或继续 API/模块拆分。Chat 已交付业务接线和工具；Mac 负责带真实前像/路径执行隔离 canary、独立测试、既有发布链和同一 run API/UI 验收。具体顺序见 `MAC_APPLY.md`。

所有研究链始终保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。手动补验不标 NATURAL；本清单中的源码与输入 SHA 也不构成自然时段运行证明。

## 10. 固定来源索引

来源编号供上述表格追溯。远端路径均属于 `lexi2016/v4`；固定提交链接对应已提供参考，不能据此推断 Mac 当前工作树。B/R1 路径分列时分别对应其各自 SHA。唯一标为“包内 R1 参考”的条目只承诺本包所附的已核字节。

| 编号 | 固定提交 / 来源类型 | 精确路径 |
|---|---|---|
| S01 | `28ab2d35020adf031f10f38c1040514fc81b6d66` | [handoff/v4-running-source-20261005/canonical/ops/_run_stage_center_nodes_parts/deadline_supervision.py](https://github.com/lexi2016/v4/blob/28ab2d35020adf031f10f38c1040514fc81b6d66/handoff/v4-running-source-20261005/canonical/ops/_run_stage_center_nodes_parts/deadline_supervision.py) |
| S02 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/stage-minimal-fix-20261009-r1/work/entrypoint_clock/after/actual_stage/ops/_run_stage_center_nodes_parts/deadline_supervision.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/stage-minimal-fix-20261009-r1/work/entrypoint_clock/after/actual_stage/ops/_run_stage_center_nodes_parts/deadline_supervision.py) |
| S03 | `28ab2d35020adf031f10f38c1040514fc81b6d66` | [handoff/v4-running-source-20261005/stage/ops/_run_stage_center_nodes_parts/node_entry.py](https://github.com/lexi2016/v4/blob/28ab2d35020adf031f10f38c1040514fc81b6d66/handoff/v4-running-source-20261005/stage/ops/_run_stage_center_nodes_parts/node_entry.py) |
| S04 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/stage-minimal-fix-20261009-r1/work/entrypoint_clock/after/actual_stage/ops/_run_stage_center_nodes_parts/node_entry.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/stage-minimal-fix-20261009-r1/work/entrypoint_clock/after/actual_stage/ops/_run_stage_center_nodes_parts/node_entry.py) |
| S05 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/v4-running-source-20261005/canonical/ops/_run_stage_center_nodes_parts/runtime_arguments.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/v4-running-source-20261005/canonical/ops/_run_stage_center_nodes_parts/runtime_arguments.py) |
| S06 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/v4-running-source-20261005/canonical/stage_center/_live_collectors_parts/collector_registry.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/v4-running-source-20261005/canonical/stage_center/_live_collectors_parts/collector_registry.py) |
| S07 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/v4-running-source-20261005/stage/stage_center/_live_collectors_parts/hk_minute.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/v4-running-source-20261005/stage/stage_center/_live_collectors_parts/hk_minute.py) |
| S08 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/stage-selection-issues-20261008/source/active_stage_reference/stage_center/_live_collectors_parts/selection_builder_registry.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/stage-selection-issues-20261008/source/active_stage_reference/stage_center/_live_collectors_parts/selection_builder_registry.py) |
| S09 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/v4-running-source-20261005/canonical/stage_center/_runner_parts/configuration.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/v4-running-source-20261005/canonical/stage_center/_runner_parts/configuration.py) |
| S10 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/v4-running-source-20261005/canonical/stage_center/_runner_parts/hk_candidate_authority.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/v4-running-source-20261005/canonical/stage_center/_runner_parts/hk_candidate_authority.py) |
| S11 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/stage-minimal-flow-20261009/source/actual_stage/stage_center/_runner_parts/hk_input_validation.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/stage-minimal-flow-20261009/source/actual_stage/stage_center/_runner_parts/hk_input_validation.py) |
| S12 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/v4-running-source-20261005/canonical/stage_center/_runner_parts/selection_input_validation.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/v4-running-source-20261005/canonical/stage_center/_runner_parts/selection_input_validation.py) |
| S13 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/v4-running-source-20261005/stage/stage_center/_runner_parts/tick_planning.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/v4-running-source-20261005/stage/stage_center/_runner_parts/tick_planning.py) |
| S14 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/stage-minimal-flow-20261009/source/actual_stage/stage_center/runner.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/stage-minimal-flow-20261009/source/actual_stage/stage_center/runner.py) |
| S15 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/stage-minimal-fix-20261009-r1/work/entrypoint_clock/after/canonical/ops/_run_stage_center_nodes_parts/deadline_supervision.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/stage-minimal-fix-20261009-r1/work/entrypoint_clock/after/canonical/ops/_run_stage_center_nodes_parts/deadline_supervision.py) |
| S16 | `28ab2d35020adf031f10f38c1040514fc81b6d66` | [handoff/v4-running-source-20261005/canonical/ops/_run_stage_center_nodes_parts/node_entry.py](https://github.com/lexi2016/v4/blob/28ab2d35020adf031f10f38c1040514fc81b6d66/handoff/v4-running-source-20261005/canonical/ops/_run_stage_center_nodes_parts/node_entry.py) |
| S17 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/stage-minimal-fix-20261009-r1/work/entrypoint_clock/after/canonical/ops/_run_stage_center_nodes_parts/node_entry.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/stage-minimal-fix-20261009-r1/work/entrypoint_clock/after/canonical/ops/_run_stage_center_nodes_parts/node_entry.py) |
| S18 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/v4-running-source-20261005/canonical/stage_center/_live_collectors_parts/hk_minute.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/v4-running-source-20261005/canonical/stage_center/_live_collectors_parts/hk_minute.py) |
| S19 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/v4-running-source-20261005/canonical/stage_center/_live_collectors_parts/selection_builder_registry.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/v4-running-source-20261005/canonical/stage_center/_live_collectors_parts/selection_builder_registry.py) |
| S20 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/v4-running-source-20261005/canonical/stage_center/_runner_parts/hk_input_validation.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/v4-running-source-20261005/canonical/stage_center/_runner_parts/hk_input_validation.py) |
| S21 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/v4-running-source-20261005/canonical/stage_center/_runner_parts/tick_planning.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/v4-running-source-20261005/canonical/stage_center/_runner_parts/tick_planning.py) |
| S22 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/stage-minimal-flow-20261009/source/canonical/stage_center/runner.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/stage-minimal-flow-20261009/source/canonical/stage_center/runner.py) |
| S23 | `28ab2d35020adf031f10f38c1040514fc81b6d66` | [handoff/v4-running-source-20261005/api/apps/web/src/App.vue](https://github.com/lexi2016/v4/blob/28ab2d35020adf031f10f38c1040514fc81b6d66/handoff/v4-running-source-20261005/api/apps/web/src/App.vue) |
| S24 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/stage-minimal-fix-20261009-r1/work/ui_presentation/after/apps/web/src/App.vue](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/stage-minimal-fix-20261009-r1/work/ui_presentation/after/apps/web/src/App.vue) |
| S25 | `28ab2d35020adf031f10f38c1040514fc81b6d66` | [handoff/v4-running-source-20261005/api/apps/web/src/components/review/StageExecutionEvidencePanel.vue](https://github.com/lexi2016/v4/blob/28ab2d35020adf031f10f38c1040514fc81b6d66/handoff/v4-running-source-20261005/api/apps/web/src/components/review/StageExecutionEvidencePanel.vue) |
| S26 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/stage-minimal-fix-20261009-r1/work/ui_presentation/after/apps/web/src/components/review/StageExecutionEvidencePanel.vue](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/stage-minimal-fix-20261009-r1/work/ui_presentation/after/apps/web/src/components/review/StageExecutionEvidencePanel.vue) |
| S27 | `28ab2d35020adf031f10f38c1040514fc81b6d66` | [handoff/v4-running-source-20261005/api/apps/web/src/contracts/runtime.ts](https://github.com/lexi2016/v4/blob/28ab2d35020adf031f10f38c1040514fc81b6d66/handoff/v4-running-source-20261005/api/apps/web/src/contracts/runtime.ts) |
| S28 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/stage-minimal-fix-20261009-r1/work/ui_presentation/after/apps/web/src/contracts/runtime.ts](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/stage-minimal-fix-20261009-r1/work/ui_presentation/after/apps/web/src/contracts/runtime.ts) |
| S29 | `28ab2d35020adf031f10f38c1040514fc81b6d66` | [handoff/stage-minimal-flow-20261009/source/actual_stage/stage_center/_runner_parts/runner_receipts.py](https://github.com/lexi2016/v4/blob/28ab2d35020adf031f10f38c1040514fc81b6d66/handoff/stage-minimal-flow-20261009/source/actual_stage/stage_center/_runner_parts/runner_receipts.py) |
| S30 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/stage-minimal-fix-20261009-r1/work/receipt_binding/after/source/actual_stage/stage_center/_runner_parts/runner_receipts.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/stage-minimal-fix-20261009-r1/work/receipt_binding/after/source/actual_stage/stage_center/_runner_parts/runner_receipts.py) |
| S31 | `28ab2d35020adf031f10f38c1040514fc81b6d66` | [handoff/stage-minimal-flow-20261009/source/actual_stage/stage_center/_runner_parts/slot_execution.py](https://github.com/lexi2016/v4/blob/28ab2d35020adf031f10f38c1040514fc81b6d66/handoff/stage-minimal-flow-20261009/source/actual_stage/stage_center/_runner_parts/slot_execution.py) |
| S32 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/stage-minimal-fix-20261009-r1/work/receipt_binding/after/source/actual_stage/stage_center/_runner_parts/slot_execution.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/stage-minimal-fix-20261009-r1/work/receipt_binding/after/source/actual_stage/stage_center/_runner_parts/slot_execution.py) |
| S33 | `28ab2d35020adf031f10f38c1040514fc81b6d66` | [handoff/stage-minimal-flow-20261009/source/actual_stage/stage_center/_selection_parts/a_auction.py](https://github.com/lexi2016/v4/blob/28ab2d35020adf031f10f38c1040514fc81b6d66/handoff/stage-minimal-flow-20261009/source/actual_stage/stage_center/_selection_parts/a_auction.py) |
| S34 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/stage-minimal-fix-20261009-r1/work/quote_fields/after/stage_center/_selection_parts/a_auction.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/stage-minimal-fix-20261009-r1/work/quote_fields/after/stage_center/_selection_parts/a_auction.py) |
| S35 | `28ab2d35020adf031f10f38c1040514fc81b6d66` | [handoff/stage-minimal-flow-20261009/source/actual_stage/stage_center/_selection_parts/a_live.py](https://github.com/lexi2016/v4/blob/28ab2d35020adf031f10f38c1040514fc81b6d66/handoff/stage-minimal-flow-20261009/source/actual_stage/stage_center/_selection_parts/a_live.py) |
| S36 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/stage-minimal-fix-20261009-r1/work/quote_fields/after/stage_center/_selection_parts/a_live.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/stage-minimal-fix-20261009-r1/work/quote_fields/after/stage_center/_selection_parts/a_live.py) |
| S37 | `28ab2d35020adf031f10f38c1040514fc81b6d66` | [handoff/stage-minimal-flow-20261009/source/canonical/stage_center/_runner_parts/runner_receipts.py](https://github.com/lexi2016/v4/blob/28ab2d35020adf031f10f38c1040514fc81b6d66/handoff/stage-minimal-flow-20261009/source/canonical/stage_center/_runner_parts/runner_receipts.py) |
| S38 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/stage-minimal-fix-20261009-r1/work/receipt_binding/after/source/canonical/stage_center/_runner_parts/runner_receipts.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/stage-minimal-fix-20261009-r1/work/receipt_binding/after/source/canonical/stage_center/_runner_parts/runner_receipts.py) |
| S39 | `28ab2d35020adf031f10f38c1040514fc81b6d66` | [handoff/stage-minimal-flow-20261009/source/canonical/stage_center/_runner_parts/slot_execution.py](https://github.com/lexi2016/v4/blob/28ab2d35020adf031f10f38c1040514fc81b6d66/handoff/stage-minimal-flow-20261009/source/canonical/stage_center/_runner_parts/slot_execution.py) |
| S40 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/stage-minimal-fix-20261009-r1/work/receipt_binding/after/source/canonical/stage_center/_runner_parts/slot_execution.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/stage-minimal-fix-20261009-r1/work/receipt_binding/after/source/canonical/stage_center/_runner_parts/slot_execution.py) |
| S41 | `41a9242d400acec08af3934d1da314b1626a1bcd` | [handoff/module-release-isolation-20261009/package/source_snapshot/active_api_issue32/apps/api/v35_api/app.py](https://github.com/lexi2016/v4/blob/41a9242d400acec08af3934d1da314b1626a1bcd/handoff/module-release-isolation-20261009/package/source_snapshot/active_api_issue32/apps/api/v35_api/app.py) |
| S42 | `41a9242d400acec08af3934d1da314b1626a1bcd` | [handoff/module-release-isolation-20261009/package/source_snapshot/active_api_issue32/stage_center/consumer.py](https://github.com/lexi2016/v4/blob/41a9242d400acec08af3934d1da314b1626a1bcd/handoff/module-release-isolation-20261009/package/source_snapshot/active_api_issue32/stage_center/consumer.py) |
| S43 | 包内 R1 参考 | [r1/actual_api/stage_center/consumer.py](r1/actual_api/stage_center/consumer.py) |
| S44 | `28ab2d35020adf031f10f38c1040514fc81b6d66` | [handoff/stage-minimal-flow-20261009/source/actual_api/stage_center/execution_evidence.py](https://github.com/lexi2016/v4/blob/28ab2d35020adf031f10f38c1040514fc81b6d66/handoff/stage-minimal-flow-20261009/source/actual_api/stage_center/execution_evidence.py) |
| S45 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/stage-minimal-fix-20261009-r1/work/api_ui/after/source/actual_api/stage_center/execution_evidence.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/stage-minimal-fix-20261009-r1/work/api_ui/after/source/actual_api/stage_center/execution_evidence.py) |
| S46 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/v4-running-source-20261005/canonical/stage_center/raw_store.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/v4-running-source-20261005/canonical/stage_center/raw_store.py) |
| S47 | `0fc3e8304e11700230517616ded0c86f83a4b257` | [handoff/v4-running-source-20261005/canonical/stage_center/_raw_store_parts/receipt_identity.py](https://github.com/lexi2016/v4/blob/0fc3e8304e11700230517616ded0c86f83a4b257/handoff/v4-running-source-20261005/canonical/stage_center/_raw_store_parts/receipt_identity.py) |

### 本清单依据的冻结文件 SHA256

| 包内文件 | SHA256 |
|---|---|
| `SOURCE_GAPS.json` | `32a3bfdc86e78efd531b016667fbe29747b074f7940dc7606ad4372953b0f105` |
| `SOURCE_MAP.json` | `9ff05ba04a06794a753343780ee7fa890a4d74081a956dfd0b962d8de0ae2b5e` |
| `evidence/REFERENCE_SOURCE_INDEX.json` | `8a08c772a05e9b9b8f5f5a6ff7d02368b0bde3c6e84f9bfd57b0fca10b2e42d3` |
