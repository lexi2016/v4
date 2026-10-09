# R4 完整文件身份

以固定 Git commit 和 SOURCE_MAP 为准；表中 SHA 为完整 SHA-256。

| 文件 | 操作 | 前像 SHA-256 | 后像 SHA-256 |
| --- | --- | --- | --- |
| `api/apps/api/v35_api/app.py` | `modify` | `5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5` | `a51b927e98e23ccdd33a849644abfa544232809aab29c2e7223969cc2308d0b8` |
| `api/stage_center/consumer.py` | `modify` | `61f8a3541aa7a2e698cc4374385e3d20d41b40ffd5a3cd7d87c9494cb8726cf4` | `16f004edb60ab256993f02ec4df36caa5d2cb3aa55bff643834c3119ec86d207` |
| `api/stage_center/execution_evidence.py` | `modify` | `e4c4ea94d892158383620beab1825014f21e926b57907354475f8c9ff382704b` | `1be96e736fda2863f6f8ff2315e8879a98499bbd30f5a911b46423c4dc6f094b` |
| `api/stage_center/research_read_binding.py` | `add` | `ABSENT` | `c33a1452df34c7dcc7fc96e61b1177079c54c467164b7cb957d773f2d2e0ba05` |
| `ui/apps/web/src/App.vue` | `modify` | `f43bdb2c7214bce09221757eecb75eea9d5e1c746a3213bb53e6d0c84b751d9c` | `8f1c00c4b278fd46736d9176d94752539f46e7c04d38fc13129084e6b9164c0f` |
| `ui/apps/web/src/components/review/StageExecutionEvidencePanel.vue` | `modify` | `07188178bbcd5ae2b01b9d6c1ef9dffd7b94f1b27f0211501cc2464566c5bc8b` | `eca21b9d5674e3a18b09672c43401164ca356fd84fd6c719c14453c006f0ee5d` |
| `ui/apps/web/src/contracts/runtime.ts` | `modify` | `9a882a174b433488684b05781ade00beb665706e962f753700960a4250d13419` | `b3d437e906f81d08af045f5b0f3990662c64676572376d42edddaf109f3dd980` |
| `release/ops/api_release_integration.py` | `modify` | `1f4afc70d7e5920b67c2b148def6b9167819664c33c92b475d919a097b9dd050` | `5325f7a81acadb4016385416c88319e4baab0a26974ac19ed17dd7debb7e0f29` |
| `release/ops/build_release_candidate.py` | `modify` | `81f4290a6f51e5958048d782c2d4b1eecfc42f892e387e6c1a22bb71912abef6` | `33bd9f8b4dd1803e0ff583a7763576374b83f89d38bac6ca0249316f17a10404` |
| `release/ops/build_release_candidate_stage.py` | `unchanged` | `79cbb7ab98ca894594c2f80f802d9ed410bf64489decad469fdf3fc9d6b402df` | `79cbb7ab98ca894594c2f80f802d9ed410bf64489decad469fdf3fc9d6b402df` |
| `release/ops/create_api_module_delta.py` | `modify` | `04e67a3ce948eecf9dac04083277bd919c7ec8880ec5814bbe57e7a5ba8d0072` | `594a537982c8e060d29158445468a5cfd6af585f3b78c7872fe7625bf6f8012d` |
| `release/ops/prepare_api_only_cutover.py` | `unchanged` | `0fee40c13bdb76d8d4d7b5b0068eb8b6e7cade9187a5f3c3154b7d6238a1af4c` | `0fee40c13bdb76d8d4d7b5b0068eb8b6e7cade9187a5f3c3154b7d6238a1af4c` |
| `release/ops/release_candidate_audit.py` | `unchanged` | `84d30676cf88d244f930eb0abc1f8184db20e53ec2e0ad7a4f32590086673cdf` | `84d30676cf88d244f930eb0abc1f8184db20e53ec2e0ad7a4f32590086673cdf` |
| `release/ops/release_candidate_ports.py` | `unchanged` | `1b70ef9725335c1570b96b937753917ac9d5114cfa66359ee08178eb282fd7d4` | `1b70ef9725335c1570b96b937753917ac9d5114cfa66359ee08178eb282fd7d4` |
| `release/ops/release_candidate_sources.py` | `unchanged` | `76d963c71cb388e1f7efc51478078f0f21dd280093646fc9d47e955dfe04a738` | `76d963c71cb388e1f7efc51478078f0f21dd280093646fc9d47e955dfe04a738` |
| `release/ops/stage_service_overlay_contract.py` | `unchanged` | `36eb27395bfd10cc78c6f0ba237eb67afe22716f653e56b5dec2ab3827e22838` | `36eb27395bfd10cc78c6f0ba237eb67afe22716f653e56b5dec2ab3827e22838` |

新增交接入口的全部 SHA、字节数和原样引用来源见 [HANDOFF_TOOL_IDENTITIES.json](HANDOFF_TOOL_IDENTITIES.json)。

Mac 实时生成的研究绑定对、delta、release manifest、static inventory、发布计划与操作回执以各工具输出为准。本包没有预先编造这些 Mac 运行后的 SHA。
