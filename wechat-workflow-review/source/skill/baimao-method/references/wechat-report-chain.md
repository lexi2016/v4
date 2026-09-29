# 微信研究与回传合同 v2

## 职责和版本
Codex只负责采集、OCR、冻结输入、原字节归档与有界结构校验；Chat负责研究。默认归档后不重做研究。
权威输入为冻结ZIP中manifest.json的input_descriptor/input_digest，不用后来变化的run OCR验证旧报告。
字段的执行模板在workspace/templates/chat_research_prompt.md，程序校验在wechat_chat_handoff.py；二者必须一起测试，不复制第三份schema。
新包在manifest与input_descriptor中冻结`review_contract_version=wechat-event-dispositions-v1`。
summary.json的`event_dispositions`逐个以coverage的EVENT `source_index`映射`PROMOTE/HOLD/REJECT/CANNOT_CONFIRM`；
NO_EVENT、UNREADABLE、缺项、重复和未知来源均不通过结构检查。检查状态要在IMPORT_RECEIPT
与`RESEARCH_VERIFIED`分开。没有该版本字段的旧v2包按旧合同导入并显示新检查`NOT_RUN_LEGACY_PACKAGE`。

首次完整研究返回report.md、coverage.csv、mentions.csv、unmapped.csv、summary.json。
只有报告也可REPORT_ONLY_ARCHIVED；结构无效仍保留原字节并报INVALID；没有可信包外ZIP SHA不能声称绑定完整，使用REPORT_WITH_STRUCTURED_UNBOUND。
原字节留存、输入绑定、结构通过、Chat自报和independent_review_scope分开，任何结构状态都不是RESEARCH_VERIFIED。

## 覆盖与精度
BODY 一行；每图恰好一行，按原顺序；正文内部定位写claim，不额外制造BODY块行。
FULL_ORIGINAL_REVIEW要求每张原图完整阅读。OCR_RISK_REVIEW完整读正文/OCR，关键数字、名称、税币、归属、分部/集团、矛盾必须核图；图表和低OCR密度直接核图，再抽查部分NO_EVENT。
original_checked=true/false/unreadable与original_scope=FULL/PARTIAL/NONE/NOT_APPLICABLE分开。text_read只描述正文/OCR实际阅读。
局部无法读清要说明位置；整源不可读用UNREADABLE。不用SHA、文件数量、OCR状态证明读图。

## 研究顺序与报告
事件变化 → 产业传导 → 最小卡点 → 公司捕获 → 财务兑现 → 反证。稀缺看资格、良率、交期、有效产能和替代难度，而非市场空间口号。
矛盾数值保留原值、单位、期间、主体和算术结果；不能勾稽就标`CANNOT_CONFIRM_RECONCILIATION`，不得猜改数字。
每项重要判断给最强证据、最弱环节、推翻条件；资料不够就保留产品层，不强选股票。
股名、代码、单位、税币、期间和归属有疑点回看对应原图；一手来源就近引用；事后资料明确标记。
框架/LOI、正式PO、交付、验收、收入、毛利和回款分别记；不能把集团现金流归因成某分部现金流。
“名义产能×良率×工艺周期×qualification”等无变量定义/量纲的乘积不作量化论据。

九章：结论先行；事件链地图；高价值事件卡；公司横向比较；A/BJ优先级；HK优先级；反证降级与遗漏；决定性验证；短来源/边界摘要。事件链地图用简短event_chain_id、摘要和来源索引保留合并关系；coverage仍维持BODY+每图一行的既有schema。
逐来源账本主要在coverage.csv，全文证券在mentions.csv。事件图合并同源截图保留所有编号，重复传播不是独立证据。
完整论证只在事件卡写一次；其他章节比较、排序或引用，不重复展开。无固定5事件上限，无强制候选数量。

## 提及与映射
原文主体SOURCE_NAMED与外部主体RESEARCHER_DERIVED分开；同一发行人entity_id相同。
listing_origin区分SOURCE_CODE、NAME_RESOLVED、SUPPLEMENTAL_LISTING、RESEARCH_DERIVED。
A/BJ/HK是市场；港股通资格是另一个待核事实。补另一A/H上市线不能增加原文公司实体数。
映射不安全的名称、匿名主体、未上市公司保留unmapped并带来源，不能因无ticker删掉产品卡点。
遗漏审计按PROMOTE/HOLD/REJECT/CANNOT_CONFIRM解释处置。尚未证实不等于证伪；直接反证不能靠更多同源传闻抵消。
公司优先级表同时列出已有公司级证据与待核公司级证据。PROMOTE只表示优先研究，不构成投资建议；事件处置字段通过也不证明语义正确。

## 报告改写与成本
同input_digest的表达改写只更新report和summary，CSV沿用原字节；若原文件缺失，不按记忆补齐。
旧结构可原字节保存，不添加假字段升为v2。核证新增事实时标明本次增量，不重新下载全部原图或重新OCR。
记录实际获取、OCR调用、读取、人工搬运、耗时和真实token用量；未实测不声称节省百分比。

## Legacy
仅用户明确选LEGACY_FULL_RESEARCH才进入旧本地研究。发布/API/UI另需独立授权，不因“完整报告”触发；缺旧依赖如实停止对应步骤。
RESEARCH_ONLY / WATCH_ONLY / NO_BUY_GATE；production_allowed=false、buy_gate_updated=false、orders_sent=false。
