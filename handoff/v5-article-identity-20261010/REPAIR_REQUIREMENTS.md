# 缺失输入与修复要求

## 缺的不是另一个哈希函数

原 builder 源码已附；缺的是本批原始 builder 输入的完整字节及其与capture/run的绑定合同。不得猜claim_type或把其无条件替换为evidence_level。status相对路径已可由原run重建，但无法恢复所有去重/合并原输入。

至少需要：

1. 同批 `trade_date`、完整 `stock_research_timeline`、`stock_research_daily`、`source_manifest`，不是抽出单条方便的article。
2. timeline保留原 `claim_type`、`evidence_level`、`source_path`，以及原去重元组各字段及其fallback字段；保留重复证据行和原聚合字段。
3. 原builder source字节对应SHA256、来源owner、run/date及capture文件的明确绑定；来源由现有采集/研究owner输出，不能由消费者随意补写已丢字段。
4. 原 `source_input_sha256` 的生产/序列化语义及准确输入字节。若已有源文件合同能复用，应给出文件名、owner和固定源码证据；不能用另造JSON的SHA冒充原source SHA。

完整source是权威输入；上述是最少必查项目，不授权删掉原builder消费的其他字段。不要提供或上传用户真实材料来证明接口；可先用完整合成source验证合同。

## 最小实现要求

- 在V5既有导入请求和receipt文件清单中显式绑定原builder输入；不得隐式扫目录、读最新文件或绕过独立读回。
- 调原 `domains.research.build_research_archive(source, *, source_input_sha256)`，对原v1 archive做确定性逐字段/规范SHA核对，再执行现有v2扩展。必须验证source来自本次绑定owner/run，不仅把任意两个自洽JSON并排放置。
- 缺失、SHA不符、日期/run不符或内容不符，保留可识别拒绝理由且不发布成功manifest；既有v1读取保持明确版本行为，不能悄悄伪补证据。
- 当前发布时间精度、显式组冲突、status路径、正文/URL/主体绑定和PIT排序全部保留。未知字段nullable，不填0，不倒填取得/可用/生成时间。
- 仅V5接线；保留原算法、V4、冻结交付。不得生产采集、部署或交易，不改凭据/系统权限。公告导入、UI清理、超跌兼容不在本包范围。

## 验收候选

- 先用本包控制项与两项变异确认真实RED；修复后两个身份键篡改必须被拒。
- 完整合成原builder source正例成功；claim_type与evidence_level不同、重复证据合并、fallback字段使用，身份均与原builder一致。
- 缺source、源SHA篡改、run/date不符、source与archive不符分别拒绝；拒绝前不得发布成功manifest。
- 原store保存 → 独立archive reader → 原材料投影/主体关系 → 原经理保存 → 同run attempt和plan独立读回；正例核同run/plan SHA，不能只验孤立helper。
- 原行业路径不要求ETF/US ticker；直接个股路径仍需明确US关系；当前US session不一致必须保留INPUT_MISSING，不能把旧恢复结果塞入当前来源。
- 所有执行交现有独立Mac任务；此交付全部产品测试NOT_RUN，Mac离线。合成通过不能算自然时段验证。
