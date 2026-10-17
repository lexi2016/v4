# 给 Chat 的新增本机证据与后续边界

基线：lexi2016/v4 的 be8a44ea0aeafc546c388cc283a724543dcefb91。新增证据在 codex/zsxq-pdf-url-probe-20261018-r1 的 docs/handoffs/zsxq_pdf_url_probe_20261018/。请先读取 probe.json 与 R/reviewer.json、R/reviewer.md。

本机于2026-10-18 00:44（上海时间）通过既有授权zsxq-cli，对一条10月17日FAILED、ZSXQ_DOWNLOAD_URL_MISSING、attempts=2的附件，只执行了一次下载链接GET查询：CLI返回0，HTTP200，外层success=true，body.succeeded=true，body.resp_data.download_url为非空字符串。已记录文档键/来源run和附件ID哈希，没有保存原始响应、URL、签名、凭证或账号信息。

该响应路径与现有解析路径相符，历史失败未复现，不能证明过去上游返回了什么。未保存URL安全属性，故不声称真实URL已通过HTTPS等完整校验。共享索引前后SHA均为3f279b93b48c13ed32651292b7a72339f8a19712bae731de3277f924e1141239，没有下载PDF、OCR、队列或索引写入。

独立Luna Max Reviewer：诊断范围PASS，未证实本地解析缺陷，不支持改解析器。canonical/API/scheduler三份模块SHA均为727a3f6cfcef626d6cf482eebf9e8d66418fcbe9817ae2e1dd1943c88e8384e0。业务代码未改，测试NOT_RUN。此前321条失败记录尚未恢复。

后续请根据新增证据重新界定目标，不再把“无法访问Mac”当作尚无任何真实响应，也不要把本次成功当成历史根因已查明。不要猜测响应路径或提高全局重试上限。当前既有处理器仍会在attempts=2处停止，单纯file_id筛选不能绕过此条件；不存在已确认可直接调用的安全恢复入口。

如继续处理积压，先交付限定一个document_key、保留来源/日期/哈希和已完成页输出、可审计且只允许一次人工恢复的具体候选方案；禁止直接重放321条、清空或手改共享索引。任何源码实施仍须唯一Luna Max Writer、不同身份的独立Luna Max Reviewer及针对性测试。运行单条下载/OCR/状态写入canary前须明确该执行范围；本份取证材料本身不授权数据写入。上游历史错误响应仍不可得时保留CANNOT_CONFIRM，禁止用猜测mock声称历史复现。沿用既有两页续跑、缓存与退避合同，不扩展日期控件或其他业务。

RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。诊断PASS不等于修复、部署或积压恢复。
