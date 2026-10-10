# 第一模块公告范围核对

目标基线：`lexi2016/v4@f7cb731c384ee6890a87d16c19a5b5a621779477` 的 `V5/`。

## 本批决定

公告生产实现已有非空消费闭环，本职责范围不修改生产文件、vendor 或 manifest。新增 `V5/tests/module01_owner_fixture.py` 与 `V5/tests/test_module01_announcement_contract.py`，通过真正的固定原 owner、目录/正文存储、注册、导入、reader 和 `run_manager_plan` 验证现有行为。经理 exact-run 与普通 API/frontend 变更由其他职责完成。

## 目标调用链与已有保护

- `src/v5_shadow/announcement_offline_reader.py::read_owner/_worker` 调用原 `OfflineAnalysisOwner/DecisionRevisionOwner`，验证 app pin、binding SHA、产品文件、owner receipt 文件、保存的完整 `offline_import_readback.json`、注册 handoff、恢复/修订证据。`install_consumer_contract` 使用固定经理 capsule 的 `validate_registered_handoff`、`validate_owner_analysis_import_receipt`、`_analysis_time_refs`、`read_analysis_consumption`，保留 offline owner 原 failed-page validator。worker 禁止网络和写入。
- `OfflineAnalysisOwner.get_announcement_date_catalog/_verify_registered` 读原恢复和注册证据；本批 reader 直接调用 owner 的 catalog/read request 与消费函数，不执行 `execute(['build-reviewed'])` 或 `execute(['readback'])`。因此旧辅助 CLI 的已知缺陷不等于本次已保存结果的读回失败。
- `announcement_analysis_api.py::publish_analysis/response_record` 分别验证 explicit ISO、explicit compact 与 default 查询。default 调用原 `analysis.read(owner, target, None)`，不把 explicit payload 改 label；输出保留 nullable 未评估状态。
- `announcement_bridge.py::_assemble` 从声明的不可变输入快照调用原 `announcement_analysis.read`、owner receipt validator 和消费函数；校验文件前后字节及 catalog run mirror。输出仍明确 `source_origin_verified=False/workspace_consumption_verified=False/natural_verified=False`；桥接读回不提升为真实源或自然验收。
- `manager_plan.py::_assemble` 将 offline transport 接入原 service；普通原 manager 的 `workspace_announcements.read_reviewed_analysis_references` 按精确日期独立消费。`workspace_daily_channels.build_daily_channels` 仅将已消费产品的 SELECTED/CONDITIONAL_WATCH 投影为公告 rows，保留未评估数量、产品检查和缺口。US、港股通、超跌缺源不清空健康公告。

## A strict identity 与 D frozen replay

固定 V5 manager capsule 没有 `workspace_identity.py`。其 `workspace_projection.build_workspace` 仍使用保守的全输入 digest，只剔除展示用 `research_cutoff`；这不是 A `semantic_inputs/_complete_research_binding/identity_diagnostics` 的字节或语义等效移植。

固定 V5 的 `archive_catalyst_inputs.project_archive_catalysts` 仍完整比较 selected 与 frozen selected，包含 registry manifest SHA；尚未等效 D `_replay_selection`。但本次 `manager_plan._assemble` 的 `get_catalyst_observations` 是显式 `V5_CATALYST_OWNER_NOT_BOUND`，`_catalyst_data_root/_catalyst_news_owner_root=None`，并声明 `owner_bindings.catalyst=NOT_BOUND`。固定 capsule 当前读取入口没有调用 `project_archive_catalysts` 的路径。新增真实 owner 合成测试表明这不阻断本批非空公告。依据主控确认，本批保留原字节，待实际绑定 frozen catalyst 的任务再将 D 局部比较适配 A 严格 binding 谓词；不能把本批测试称为 frozen catalyst 功能已修复。

## d659 两文件三修复：逐项结论

精确 donor 已读并保存在 `inputs/D659_SOURCE_MANIFEST.json`、`D659_RUNTIME.patch`、`D659_READBACK_REUSE_SOURCE.json`，commit 为 `d659ff0dbcc00aa1944908cfc8b44443642ea171`。

| donor 修复 | 固定 V5 实际实现 | 本批处理 |
|---|---|---|
| historical runner `_build(..., reviewed=True)` 在 receipt 进入最终 base SHA 后重建 extension | offline/revision 两个 runner 的 build-reviewed 分支仍先 extension 后 receipt，未等效。两者 `_register_handoff` 已按最终 receipt/base SHA 后建立 extension | 保留非空已保存结果的 register/import/read 路径；原 owner 合成注册＋导入＋消费测试证明该路径正确。本批不运行 build-reviewed，不移植旧 runner |
| historical runner `_readback` 调完整 `validate_owner_analysis_readback` | offline/revision 的 CLI `_readback` 仍使用仅日期/SHA 的临时 product，未等效；本批 `announcement_offline_reader._worker` 使用完整原 owner analysis request 和独立完整消费函数 | 旧 CLI 问题准确保留为后续；不声称已等效，不为只读结果改 vendor |
| current-live `workspace_plan.read_rebound_screen` 80% 比较使用 Decimal | V5 manager capsule 的辅助 gate 比较有 Decimal，但实际 `read_rebound_screen` 中 `close <= _REBOUND_OVERSOLD_RATIO * prior60_high` 仍是浮点，未等效 | 本批适配器 `committed_screen` 只接受独立提交且准入的 rebound 原结果；缺源走 `original_screen(None, context)`，不触及真实 panel 浮点分支。正式超跌准入另验，不能把辅助 Decimal 当修复已覆盖 |

donor 两个前像分别是 historical runner `bfb853fb982e0b2da1024fa942ae9dc5d67fa88a8d112f46054608641129c1ee`、current-live workspace `881599ba5a68badd7e18271c57666937f3e954088dfcfcb4c827dcf99419be7f`；不得混为同一运行基线或覆盖固定 V5 capsule。

`COMPLETE_EMPTY` 端到端缺口、旧 US receipt 兼容与正式超跌准入均未扩展；新增测试仅验证它们缺源不抹去健康公告。

## 新增测试与夹具身份

夹具模式来自远端已读原测试：commit `1a699a040c0b2cd467726bca5ccc7847182cb975`，路径 `V5/handoff/announcement-budget-red-20261009/tests/test_v5_private_owner.py`，Git blob `d77163606682a83313487453aa599ed97bea1703`。固定副本在 `inputs/UPSTREAM_PRIVATE_OWNER_TEST.py`。

新 helper 不采用旧 bundle assembler、不修改生产 pin、不借 Mac 392 原件。它直接载入目标 offline capsule 的原 `PrivateOwner/HkexOfficialProvider/SourceResponse`，只将网络 transport 换成明确合成响应；audit hook 拒绝实际 socket/subprocess。原 capture、catalog/body persistence、`register-handoff`、`import` 与原 handoff/receipt validators 均运行。4 条合成决定为 1 event / 0 performance / 1 watch / 1 not selected / 1 not assessed，只产生 1 条 selected 股票。

运行环境：固定目标项目 `.venv/bin/python`，Python 3.14.6，原 uv.lock 依赖。测试命令：

```bash
.venv/bin/python -m unittest discover -s tests -p test_module01_announcement_contract.py -v
```

最终 `logs/announcement-contract-final.log`：**9 tests，OK**，覆盖真实原 reader 的不可变读回、决定/股票数量区分、健康公告＋US/HK_CONNECT/OVERSOLD 缺源、保存与同 run 普通读回、错误日期/default basis、改外层 pin 后的原目录材料篡改、原正文 artifact 篡改、重封 owner parent 篡改、缺注册 handoff 不能晋升消费、原 owner 源码 pin 拒绝篡改。

完整过程保留：`announcement-contract-initial.log` 是 pytest 不存在的真实失败；改用项目标准库 unittest，无新增依赖。`announcement-contract-unittest-initial.log` 是夹具误纳入 material parsed cache 的 path 拒绝；`announcement-contract-unittest-second.log` 是篡改夹具错误挑中未被原目录 reader 消费的 body cache。随后只修夹具选择，改为精确 `listing_source.source_ref.blob_sha256`，并补充真正注册正文 artifact 篡改测试。它们不是生产回归 RED，不把这些失败描述为发现/修复了目标代码漏洞。

## 真正 DTO 与复用接口

- `create_manager_fixture(root)` 返回 `request/announcement_request/owner_readback/consumption/catalog/provenance`。
- `create_manager_dto(root)` 返回 `{fixture, result}`，其中 result 是真正的 `run_manager_plan` 返回值。
- 已生成 `logs/announcement-synthetic-dto.json`、`logs/announcement-synthetic-result.json` 与 `logs/announcement-fixture-provenance.json`，供普通 API→完整 frontend validator 验证复用。可再读输入 `tmp/announcement-fixture/fixture.json`，无需重生成。
- 本次合成 run `5685e9708c734ddda582338cfd45f849`，plan SHA `687b7f94142c888c10e6de86e29c2372d3037e691461b4420558c0c0b33ca05a`。这只标识合成测试，不能替换现场 Mac run。

## 保留的真实限制

Mac 历史回执：run `5b4feaf7ef7d4d13bec639e90b6d3db0`，产品 SHA `56556a67ddc1a562e82b38e750be92fcfda070945397cc4eacffd1c79f42bcf0`；392 是决定数：2 event / 0 earnings / 26 observe / 270 not selected / 94 unknown。真实 392 原件、本机原绑定的 `read_owner` happy path、Mac API/浏览器、自然周期与完整三策略，本职责本会话均 `NOT_RUN`。不能用上述 9 项合成通过升级它们。

本职责生产文件、owner capsule 与所有 manifest 保持原字节。
