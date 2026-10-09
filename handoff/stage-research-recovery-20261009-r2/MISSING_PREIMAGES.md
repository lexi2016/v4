# 一次性前像与缺失证据清单

下面的 SHA 都是已取得源码字节的参考值，**不是声称已读取当前 Mac**。21 个文件都有完整 before/after；其中 7 个 before 来自用户已提供的 actual 切片，14 个仅有固定仓库中的历史参考。当前逐文件状态由 `prepare_canary.py` 一次输出。命中 before 或 R1 after 就可以在新副本应用，已是最终 after 则保持；其余返回完整当前文件及其 SHA，由 Chat 做必要代码移植。

完整绝对路径和可接受 SHA 列表见 [REQUESTED_PREIMAGES.json](REQUESTED_PREIMAGES.json)。

## 源码根

| 组 | 实际读取根 |
|---|---|
| stage | `/Users/lexi/Desktop/学习/agents调试/V4_HK_STAGE_RECOVERY_20261003/issue23_runner_helper_r3/stage_r1_binding_candidate_r3/app` |
| api | `/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app` |
| ui | `/Users/lexi/Desktop/学习/v4_app` |

## 仅有历史参考的 14 个文件

路径相对于上表对应根。`SOURCE_MAP.json.accepted_before_sha256` 另外列出可接受的 R1 后像；表中只显示已知原始 before。

| 组 | 文件 | 已知 before SHA256 |
|---|---|---|
| stage | `ops/_run_stage_center_nodes_parts/deadline_supervision.py` | `95ce916246f3376fc3618c0890ee1f76f2b0231c50d77fe5440a9b956884a674` |
| stage | `ops/_run_stage_center_nodes_parts/node_entry.py` | `f9530f010055476e17d87e93198e28d3f4943ed34255a2419130eb9f39deb6ed` |
| stage | `ops/_run_stage_center_nodes_parts/runtime_arguments.py` | `2e40c84a30d9cabf047fefb5caec14f8b569d24e54a7f50c16211f0c0fda53ec` |
| stage | `ops/run_stage_center_tick.py` | `4eb8e1a3be0e3780ff9cb62417c695c5aab67948f224db462d3f6e3a67299f42` |
| stage | `stage_center/_live_collectors_parts/hk_minute.py` | `b6c78a4ffd7193d0e1afeee530a1c4c123e72a20ba3bc9f8183727dcca58a179` |
| stage | `stage_center/_live_collectors_parts/selection_builder_registry.py` | `5b315c482723f4bbfb187e36241ea422f2a59518a2056be037d1fdbe2f00eb22` |
| stage | `stage_center/_runner_parts/configuration.py` | `713ac5b8ac81fe186904eca38c8e7a28a2edb83a0cf98766546a09f7169c7486` |
| stage | `stage_center/_runner_parts/hk_candidate_authority.py` | `1fd933e8436e4316832c29f89da16c1ccf3ed78b14ee853262ed758e476d2f95` |
| stage | `stage_center/_runner_parts/selection_input_validation.py` | `23e8afa65fa9fe0b24baefb8e778af3c475e1affaa34a2734ea80ea0aca9d44c` |
| stage | `upstreams/v3_shared_data/scripts/live_acquisition/pytdx_hq.py` | `7b5f062e6c1231fa5edc7db0de5406066220e69cfe3605bf5b13fd3e0b8ad18f` |
| api | `stage_center/consumer.py` | `61f8a3541aa7a2e698cc4374385e3d20d41b40ffd5a3cd7d87c9494cb8726cf4` |
| ui | `apps/web/src/App.vue` | `995a680995cc42feadeaa8d2bdd44294c8ec782a908d664c698faf69d4cf02a1` |
| ui | `apps/web/src/components/review/StageExecutionEvidencePanel.vue` | `07188178bbcd5ae2b01b9d6c1ef9dffd7b94f1b27f0211501cc2464566c5bc8b` |
| ui | `apps/web/src/contracts/runtime.ts` | `9a882a174b433488684b05781ade00beb665706e962f753700960a4250d13419` |

## 已有 actual 切片的 7 个文件

路径相对于上表对应根。`SOURCE_MAP.json.accepted_before_sha256` 另外列出可接受的 R1 后像；表中只显示已知原始 before。

| 组 | 文件 | 已知 before SHA256 |
|---|---|---|
| stage | `stage_center/_runner_parts/hk_input_validation.py` | `92e8fb2be06e6530c33f3cf2f5b44f29b0bcf7875e6a5902260f8be4c814f735` |
| stage | `stage_center/_runner_parts/runner_receipts.py` | `d3d9e69230b00a2864eae106f1c5c89ea0d383e20c2e87d655d4cabd273bbc83` |
| stage | `stage_center/_runner_parts/slot_execution.py` | `278085fb1effdc9dcf5c5dc9626d68faea0bc53c44f66be4eb89f9a0415fc07a` |
| stage | `stage_center/_selection_parts/a_auction.py` | `d0a96edcb4d87f223b117917a8f0d68276bd088a88abe8f787d245c8e1c669ad` |
| stage | `stage_center/_selection_parts/a_live.py` | `b7faa3286df4f0312075c7a4563d3f4deed463d3f10ab2c4902967e8d5d7781d` |
| stage | `stage_center/runner.py` | `2dbfa90c42cb4bd3b9b78d20bfbd1ac15eba0f3a18dd1105b32decd04a2b5232` |
| api | `stage_center/execution_evidence.py` | `e4c4ea94d892158383620beab1825014f21e926b57907354475f8c9ff382704b` |

## 另外两项只影响实际接线证明

1. 若当前 API factory/启动参数与已存档版本不同：需要实际 API 根的 `apps/api/v35_api/app.py` 完整字节及当前 SHA256，以及当前 launcher/config 的具体路径、SHA 和非敏感参数。已取得参考是 Git blob SHA1 `f2cdb61eb5689f70bf9f9508e96a0262c0af7389`；当前 SHA 未知，不填写猜测值。现有参考支持 `stage_center_selection_root`，本包不改这个大文件。
2. `shared_data_root` 若指向 Stage app 外，需要该 root 下 `scripts/live_acquisition/pytdx_hq.py` 命中 before `7b5f062e6c1231fa5edc7db0de5406066220e69cfe3605bf5b13fd3e0b8ad18f` 或 after `fdd849fc032b5745d6611df31b5f9a147b14207d77dca953dff7b0ea4140cea2`。canary 驱动自动核验、复制并记录实际路径；只有不匹配才回传。

## dirty canonical 的边界

Stage 组按用户给定的 actual Stage 变体生成，API 组按实际 API 变体/条件 consumer 生成。canonical `/Users/lexi/Desktop/学习/v4_app` 与它们不同。现有发布链若要求 canonical 归并，JSON 同时列了各对应路径；未知字节不能整文件覆盖，只能由 Chat 对回传当前前像做最小合并。独立 canary 的复制不修改任何 canonical 源文件。

## 10/9 projection SHA mismatch 的实际输入

没有收到该次 archive/witness，不能从错误名称推断坏字段。只读诊断工具会一次给出该次准确 `archive_path`、`receipt_path`、`manifest_path`、`witness_path`、四者实际 SHA、原校验错误和字段差异；回传报告及它明确指出的这四份文件即可。witness 路径为实际 research root 下 `research/hourly/source/<receipt.source_input_sha256>.json`，不能人为补一个 hash 或重写 receipt 让校验通过。

695 行原始 HK 文件仍在用户给出的本机路径；Chat 未读过它们。本包按用户提供的四个 SHA 准备准入代码，文件本身不作为上传附件要求。0925 竞价与 Stage8 RTDATA 所需专用行情也不能由这些证券资料替代。
