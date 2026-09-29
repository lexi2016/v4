# 研究原字节归档与云盘镜像合同 v3

本地是正式留存，Drive承担默认交接和回收镜像。源材料、Chat报告和复核意见分别保存，不覆盖原件。

## 默认交接和回收

每篇文章使用已核实的Drive文章目录及`01_资料包`、`02_Chat回传`、`03_本地复核`。给用户
一个`START_HERE`链接和短prompt；用户不需要为默认流程再次上传冻结资料。Chat没有Drive写
工具时，Chat/用户将原文件回传给Codex，Codex先本地归档，再把原字节镜像到`02_Chat回传`；
真实provider metadata、字节和版本回执缺失时，不声称镜像成功。直接文件仅是Drive受阻时的
受控回退。

## 冻结输入
保留原URL/稳定文章标识、标题、公众号、biz、带时区发布时间、采集时间（没有则未知）、内容摘要和有序来源。
manifest.json.input_descriptor逐项记录BODY.md、OCR_FULL.md、manifest.csv及全部原图的路径/编号/字节数/SHA256。
input_digest对该descriptor规范JSON计算，不包含自身；ZIP摘要放包外PACKAGE_RECEIPT.json。
package_id每个版本取新值，机器始终核验ID+input_digest+可信ZIP SHA，不只依赖ID。若原ZIP
上传超过60秒，先查是否已有本次结果，再用相互独立的小ZIP；本例约2–3.5MB分包曾成功。
不使用分卷ZIP、不重做OCR；每个分包记录`members_sha256`，同时保留原包input_digest和SHA，
不能把分包hash当作新输入。
新冻结包声明`review_contract_version=wechat-event-dispositions-v1`，并同时纳入manifest.json与
input_descriptor/input_digest。summary.json必须回显该冻结版本；每个coverage `EVENT`
`source_index`在`event_dispositions`中恰好映射一个`PROMOTE/HOLD/REJECT/CANNOT_CONFIRM`，不能漏、重复、写未知来源或
映射`NO_EVENT/UNREADABLE`。旧v2包无此字段仍按旧合同归档，并在receipt记
`NOT_RUN_LEGACY_PACKAGE`。该检查只验结构闭合，不验研究语义。
导入对照旧冻结ZIP，不回读当前run OCR；旧v1输入只能LEGACY_INPUT_UNVERIFIED，不伪造迁移。

## 返回原件
唯一导入器wechat_chat_handoff.py保留report和每个CSV/JSON原字节，内容相同不重复创建版本；不同内容另存版本。
返回头部和summary绑定相同package_id/input_digest/return_id；summary的artifact_sha256绑定报告和三份CSV。
字段schema按workspace/templates/chat_research_prompt.md；统计由程序复算，金融语义与公司映射另核。
没有四份结构附件仍REPORT_ONLY_ARCHIVED并列缺失；非空但无效的文件照样原字节留存并标INVALID。
缺可信ZIP SHA，即使结构齐全也不标完整绑定。禁止临时算待验ZIP的SHA冒充既有可信回执。
回收先读report.md绑定头与summary.json身份，按package_id/input_digest/return_id/URL/文章日定位
冻结包；不能用最近Chat会话代替。90/58等来源计数冲突先查身份。五个原始返回文件按return_id
和字节SHA留存；缺失不补造，新return或内容变更创建新版本，不覆盖旧件。

可信ZIP通过后，IMPORT_RECEIPT.binding保留冻结manifest的account、biz、published_at及manifest
member SHA，供V4身份字段使用。不要只抽manifest来消除身份缺口，因为descriptor还引用BODY、OCR
和原图；只有完整源路径随包存在时才传可选manifest，否则保留`FROZEN_INPUT_NOT_REGISTERED`。

## 互不替代的状态
transport: file_id、parent_id、版本、provider校验字段、raw_bytes_obtained、observed_sha256、expected_sha256、hash_match、members_sha256。
local: bytes_archived、input_binding_valid、structure_valid、chat_claimed_complete、independent_review_scope。
Chat cannot set RESEARCH_VERIFIED/API_VERIFIED/UI_VERIFIED/NATURAL_VERIFIED. Import never sets semantic_research_accepted=true.
REPORT_AND_STRUCTURED_ARCHIVED只证明原字节+有界结构/身份；REPORT_WITH_STRUCTURED_UNBOUND表示结构可读但缺可信输入绑定。
仅计算出摘要记HASH_COMPUTED，不叫HASH_VERIFIED；provider MD5与SHA256分别保留。
metadata、bytes、hash、Chat读取、结构和语义分别验收；文件引用、网页文本、HTTP200、元数据存在不证明原字节取得。回传附件不能当作Drive原字节往返验证。下载失败不得从文本重建“原件”。

## 权限与边界
不代发Chat、不轮询、不改权限、不自动发布、不部署、不下单。归档与云盘镜像完成后，用户已授权的V4 Stage A研究归档展示可按独立合同登记并验证exact文章日API/UI；它不是legacy、候选、评分、正式池或BUY gate。服务配置、交易门禁及旧股票池均不在默认链。
RESEARCH_ONLY / WATCH_ONLY / NO_BUY_GATE；production_allowed=false、buy_gate_updated=false、orders_sent=false。
