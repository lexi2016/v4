# 给 Chat 的修复任务：知识星球 PDF 下载链接失败

请读取同目录 audit.json、findings.md、ui-evidence.json。证据分支是 lexi2016/v4 的 codex/zsxq-pdf-audit-20261018-r1，基线 be6d08053cb033a30f17d764a27a72c916bc9233。此分支是故障证据交接，不代表当前全部线上应用版本，禁止直接覆盖部署整棵旧树。以下任务是下一轮实施边界；本轮审计没有修改业务或重跑 OCR。

GOAL：查明并最小修复 ZSXQ_DOWNLOAD_URL_MISSING，使真正可恢复的失败项有明确恢复路径，同时保留已验证的长 PDF 自动分批续跑及缓存复用。
WRITER：唯一 gpt-6-luna / max Writer。
REVIEWER：不同 agent identity 的独立 gpt-6-luna / max Reviewer，read-only，独立复跑针对性测试。
ALLOWED_PATHS：infrastructure/zsxq_pdf_ingestion.py、tests/test_zsxq_pdf_ingestion.py；仅当下载响应链路直接需要时允许 ops/run_zsxq_hourly_delta.py 的相关局部；必要脱敏交接证据。
FORBIDDEN_PATHS：其他业务模块、A/HK 池和 BUY 门禁、日期控件、全局配置/权限/hooks、凭证；禁止清空/手改共享索引或全量重跑 OCR。

已确认事实（2026-10-18 00:23 上海时间快照）：
- 10月17日：558 条 PDF 引用，427 READY、131 FAILED，0 pending；558 条在当日均对应唯一附件 ID/来源哈希并完整入索引。
- 10月16日：680 条记录，490 READY、190 FAILED。两日合计321条失败记录，不据此宣称跨日有321份不同PDF。
- 全部失败均为 ZSXQ_DOWNLOAD_URL_MISSING、failure_class=TRANSIENT、attempts=2；队列 NO_RETRYABLE_TASKS 表示重试额度耗尽，不能当成全部处理成功。
- 106页文件已在自然队列经53次、每次2页续跑完成；89页文件复用10月16日结果，89/89 OCR_OK。当前89页文件与旧验收target非同一哈希，不混用文件身份。
- 活动源码及 scheduler/API 中 ingestion 模块 SHA256 均为 727a3f6cfcef626d6cf482eebf9e8d66418fcbe9817ae2e1dd1943c88e8384e0。
- 10月18日尚无来源枚举，记 CANNOT_CONFIRM，不纳入这次修复成败。

执行要求：
1. 先核当前运行身份、目标模块SHA和用户并行改动。沿用现有下载入口，查看 _cli_download_url/_cli_json 及实际支持的响应契约。现有证据只证明未提取到 resp_data.download_url，尚不能断言是解析bug、上游权限还是接口失败。
2. 优先使用现有脱敏响应或官方契约；若现有证据不足，仅通过既有授权客户端对一个失败样本做只读下载链接查询，输出HTTP/业务错误码和脱敏字段结构。不要下载PDF，不打印或上传URL、token/cookie、账号数据，不新增数据producer；遇到登录/权限需求停止并准确报告，不绕过。
3. 只在真实响应证明本地缺陷后最小修复。覆盖真实结构、缺失链接、上游明确错误、安全URL校验；禁止凭空造mock结构后声称复现，禁止猜下载URL、增加重试上限或取消退避来掩盖根因。
4. 复用既有页输出与缓存。给出失败项恢复的明确筛选条件、既有安全重试入口和小样本canary步骤；本任务不直接批量重放321条或修改共享索引。若必须新增数据写入/批量恢复动作，先交付可审查的具体清单与步骤。
5. 独立Reviewer复跑本次回归及受影响的两页续跑/缓存/退避检查；不无理由重跑旧整套验收。修复完成后按项目规则同步独立GitHub分支，并读回commit和关键文件SHA。

PASS_SIGNAL：真实输入绑定的根因证据、最小diff、独立Reviewer PASS和测试receipt、失败项恢复步骤；分别报告IMPLEMENTED/TESTED/REVIEWED，未实际上线或恢复不得称DEPLOYED或全部处理完成。
STOP_RULE：若上游确实无链接或权限不足，保留失败及CANNOT_CONFIRM，准确给出所缺证据/权限和下一动作；本地修复验收通过后停止扩范围。

research_only=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。

说明：同目录 repair-prompt.md 是审计者的离线诊断建议；本文件是面向下一轮 Chat 的完整交接边界，新增仅单例只读响应取证条件，以免在缺真实响应时凭空修复。
