# 实际原件定位后的只读诊断（2026-10-05）

本轮未增加或修改 runtime/test 源码；PR27 保持 Draft。以下原件事实来自父线程 Mac 只读回报，云端未取得/独立复算这些原始数据，不冒充本机复验。

指定 article `935c5711e5ec57d3645381231afa8ebc577c94c52b5d7bcb72d78559789a03c5` 的原 archive 标签是 **000333 / zsxq**，不是 HK.00300。archive SHA `d73b3faa4c35bef3d0f78b0fa7c06edd818fda17a36da792cc96d9fec4eeba2e`；原 source_input 绑定 `incoming/20260929/2100.recovery-feef15d9f1e75b94.json`，SHA `feef15d9f1e75b9456ad376c47d34a65241921635500b6aa8fc205774bdcaa9e`。这纠正了“寻找另一个 HK archive collector”的先前假设，不改变原缺 acquisition pair 的事实。

父线程确认 source/archive 无 available_at/retrieved_at；旧 fetched_at 为21:03:02、原始2100 incoming不存在，LATE_RECOVERY 的 original_time_capture/natural_execution_verified 均 false。不能将此旧 fetched_at、恢复时间或当前时间补作取得证明。旧 archive/receipt 不作任何修改。

## GitHub 精确源码检索

刷新并逐 blob 计算 SHA256：64 个当前远端分支头，加一个已交付 Git bundle 的旧 head；相关五种 basename 共20种不同源码字节。另一个ZIP交付没有目标文件。三个实际 producer SHA 均 **未命中**：

- collector：`66b941f5a066250c4fd9830170302b8b1f7041760a37c6e4bf02ea222aa307ab`
- domains/research.py：`486c182e202e7ed7f9e689be1c1c61f7ea9fd3e23f5876f861f57210ec64ee10`
- hourly：`24b1437016be4bdb9ee06c6ac7b10136e89f7e276179551ceb7ba90a09e78cd0`

结果/固定 head 清单见 actual-producer-source-search.json。没有遍历每一个历史 commit，结论限于当前可见交付快照；本地已有各 materialized snapshot 也未命中。不能据此构造逐字节三方适配，PR27 before/after 不能覆盖实际 r9 producer。

下一步最小源码：从已定位 producer root 只取上述三份准确文件（hourly 的相对路径需明确；本次同时搜了 run_hourly_research.py 和 research_hourly.py）。同时读取 `contracts/research.py`、`domains/research_hourly.py`、`ops/run_zsxq_hourly_delta.py`、实际加载的 `upstreams/shared_research/v3_zsxq_adapter.py` 的 SHA：若与已交付前像相同只需 hash；若不同再提供对应源码。也需确认 wrapper 的实际模块解析路径，不仅是目录同名。

三方适配顺序为 PR27 API前像 → PR27限定差异，与 actual producer 前像比较；只迁移可证明对应的采集完成/摘要保存/传递/合同校验增量。当前缺准确 actual 字节，尚不能生成可信 patch。本轮没有尝试覆盖、放宽旧合同或切换 producer/reader。

## A股标签如何可能被HK卡引用

以下为已交付 API snapshot 源码逻辑，并非已核当前 Mac Manager 的运行身份：

1. `existing_materials.py::project_archive`（23–66）保留完整 source_row 和 original_article_id，生成 material_id，记录 archive refs；不按 A股 stock_code 转换 HK 代码。
2. `workspace_discovery.py::project_material_discovery`（207–318）明确允许一篇带 A股标签的研究文章成为 HK 研究材料。依据是原 title/body 中唯一 native HK 名称，再用实际正文进行主体/动作解析；主题、原 stock_code、代码相似度都不够。original_source_row 原样保留；identity_source、propositions、source refs 一起进入卡片。
3. `workspace_semantics.py::prose_sources/assess` 使用正文或 evidence_sentence 的原文片段，输出 source_field、起止位置、subject_quote/action_quote、action_subject、polarity、claim_status。只有名字命中而无合格主体动作，不应产生有效 proposition。
4. `issuer_us_relations.py::_anchored/material_us_relations` 再核同一HK主体、原文跨度、肯定状态及业务/US关系；`_card_errors`独立检查来源/身份及 acquisition pair。可产生关系诊断不代表已获准关系。该历史文章缺两钟，原门槛应拒绝为合格 US 关系，不能显示成功零或成功恢复。

因此原标签000333与卡symbol HK.00300不同**可能符合明确合同**，不能单凭不同认定错配。也不能凭代码声明就认定本条合法。区分三种情况需要实际对象：原文确实有目标HK主体的合格动作＝可合法跨市场材料；主体/跨度不匹配＝潜在解析错配；找不到对应HK00300卡或引用的是另一article＝旧报告/关联标注错误。当前尚不足以在三者中定案。

复用了既有3项限定合成测试（A股标签文章可发现明确HK主体、六位A股不重标HK、歧义别名拒绝）：3 passed / 42 deselected，日志见 evidence/existing-mapping-tests.log。没有新增测试或真实数据回放；不能代替本条正文/卡片验收。

## Mac只需一个卡片样本

请从已保存计划/关系审计只读提取同时匹配该 article_id 与 HK.00300 的对象（不要触发 refresh）：

- 所属 plan date/run_id、计划原件路径/SHA；card_id、event_id、material_id、symbol/name、semantic_version/status、mapping_reason、identity_mapping_basis。
- original_source_row 中 article_id、stock_code/name、source_title、实际被引用的 prose 字段完整值及 source_path_sha256；source_refs 的 payload_path/payload_sha256（应核是否本archiveSHA），及 source_input_sha256。
- propositions 全部字段，尤其 source_field/start/end/quote、subject_quote、action_quote/action_subject、subject_resolution、polarity/claim_status；subject_scope、identity_pair_basis、identity_source及master中该HK条目/别名。
- issuer_business_relations 和 relation audit 的 reason/rejection_reasons、accepted/rejected状态；published/available/retrieved/first_seen/collected/archive_recorded_at，以及计划cutoff/window。
- 若无该双条件样本，返回“未找到”并给出旧报告中将其标作HK00300的那一行及所属对象层级，不要强行拼接。

另给 Manager 实际加载的 existing_materials.py、workspace_discovery.py、workspace_semantics.py、issuer_us_relations.py 路径/SHA，以确认上面代码链是否对应活动版本；一致只需hash，不一致再取差异源码。不需要整份333MB计划或全量档案，不新采集、不重写回执。
