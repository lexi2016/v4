# Google Drive 优先交接合同与最小诊断方案

本文件定义Drive优先的默认交接和回收镜像步骤，不是已完成连接器集成。此代码包没有新建
Drive客户端、凭据、后台服务或自动传输代码。直接文件仅是Drive当前工具不可用或有界诊断
失败时的受控回退；不默认要求用户再次上传冻结资料。

## 固定身份与目录
每篇文章目录先核实真实root、article folder及`01_资料包`、`02_Chat回传`、`03_本地复核`的
metadata和parents；`01_资料包`内每个package_id/input_digest独立不可变版本，`02_Chat回传`
按return_id区分，`03_本地复核`只保存复核意见。当前已知root候选
`<REDACTED_PRIVATE_DRIVE_ID>`仅作metadata查询提示，不是本篇目录或全局身份。
文件名/日期/同一文章文件夹不能证明同一资料包。先读取精确ID及parents，分页只跟真实next token，不猜目录。
外部交接记录保留本地input_digest与可信ZIP SHA，以及实际provider文件/目录ID；没有ID写null不猜。
默认给用户一个已核实的Drive `START_HERE`链接和短prompt。Chat有真实Drive写工具时按该目录写入；没有Drive写工具时，Chat/用户把原文件字节交回Codex，由Codex本地归档后上传到`02_Chat回传`并记录provider ID/revision。没有真实metadata/bytes receipt不得声称写入。
回收前先读report.md绑定头和summary.json，按package_id/input_digest/return_id/URL/文章日定位冻结包；不能默认配到最近Chat会话。90/58等来源数不一致时先核身份。一次返回取得五个原始文件；return_id变化或原字节变化须落成新版本，不能覆盖旧文件。

## 最小传输诊断（分层，不盲目重试）
1. 先读当前工具真实schema。若支持fields，按需请求id,name,mimeType,size,parents,version,headRevisionId,modifiedTime,md5Checksum,sha256Checksum,capabilities(canDownload)。文档有字段不代表当前连接器会返回。
2. 先用一个小型非原生文件实测原字节往返。取得文件引用不算落盘成功；必须由受支持的文件参数/下载接口消费该引用，不能把私有引用当公共URL。
3. 记录raw_bytes_obtained、observed_sha256、expected_sha256、hash_match。只有与可信预期值相等才叫匹配；文本readback不是字节比对。
4. 原ZIP上传达到60秒超时后先查目标有无本次上传结果，避免重复创建；无结果时改用相互独立的小ZIP（当前例证每个约2–3.5MB成功），不使用分卷ZIP，不重做OCR。每个分包记录`members_sha256`，同时绑定原`input_digest`与原包SHA；相同失败边界且无新信息才转受控直接交接，不连续盲重试。
5. HTTP403保留脱敏响应主机/发生层/HTTP状态/error reason/request ID/文件MIME和canDownload。区分Drive拒绝、连接器文件引用解析、运行时落盘权限；无证据不归因为大小或OAuth。
6. 只有真实工具暴露恢复会话/分块能力才用可恢复上传；Google API支持不等于连接器支持，不硬塞未定义参数，不搭第二客户端绕过权限。

## 可安全减少的重复
同一file ID、同一已经实际取得字节的版本、同一输入绑定，且本地留存未改变，才可跳过内容下载。
缺可靠版本不得只凭名称/大小/mtime跳过；版本变化后下载原件，SHA相同只跳过重复导入。
版本不是内容哈希，可能变化但内容不变；MD5不能直接与本地SHA256比较。所有MD/CSV/JSON/ZIP保留非原生格式。
下载失败不得重建文本冒充原件；原生Docs/Sheets的export是另一种表示，不说与原上传字节相同。

## 回退和状态
Drive上传失败：保持本地包+可信回执，优先由Codex接收并上传原文件或独立小ZIP；仍不可用时才让用户进行受控直接文件交接。直接交接不是默认路由，也不改变原`input_digest`/package SHA。
Chat不能完整访问原图：按编号补图，保留缺口，不能把三张可读推广到89张全读。
回传无结构附件：仅报告归档；结构齐全但缺可信包：未绑定归档；字段无效：保留原字节并标无效。
回传附件、文件引用或文本readback不能作为Drive原字节往返验证。本地结构通过不能自动RESEARCH_VERIFIED，也不能直接发布池、改BUY gate或交易；归档和镜像通过后，用户已授权的V4 Stage A研究归档展示必须另行登记并按exact文章日验证API/UI，不触发legacy、候选或评分。不后台轮询、不自动发送Chat、不改共享权限。

新冻结包的`review_contract_version=wechat-event-dispositions-v1`由manifest和input_digest绑定。导入要求summary的`event_dispositions`对coverage中每个EVENT source_index各填一个PROMOTE/HOLD/REJECT/CANNOT_CONFIRM；NO_EVENT、UNREADABLE、遗漏、重复和未知编号均结构无效。旧v2包缺版本时明确记录`NOT_RUN_LEGACY_PACKAGE`。结构检查不是研究语义验收。
可信冻结ZIP的导入receipt会保留manifest中的account、biz、published_at和member SHA供V4身份字段使用。不要只把manifest单独抽进归档：descriptor引用的BODY、OCR、图片源也必须处于可解析路径中才可登记完整输入；缺源路径就保留`FROZEN_INPUT_NOT_REGISTERED`。

## 官方资料（2026-09-20核查；仅产品文档，不是本链路实测）
- 文件字段、版本、checksum：https://developers.google.com/workspace/drive/api/reference/rest/v3/files
- 上传方式和可恢复上传：https://developers.google.com/workspace/drive/api/guides/manage-uploads
- 下载/导出与canDownload：https://developers.google.com/workspace/drive/api/guides/manage-downloads
- 错误reason：https://developers.google.com/workspace/drive/api/guides/handle-errors

未完成的原ZIP上传超时、403原字节下载、版本字段返回、Chat完整读包和真实往返均保留未验；本修复不声称远端故障已解决。
