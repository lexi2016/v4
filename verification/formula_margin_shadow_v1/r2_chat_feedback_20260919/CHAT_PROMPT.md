# 请根据实际R2执行与独立测试，裁决最小下一步

我们按你给的V4_FORMULA_MARGIN_SHADOW_V1_R2_MINIMAL_FIX_SPEC执行，只改三个允许文件，selection.py与ops字节未变。没有改margin规则，没有新增数据源或自动化，没有启动自然canary。用户要求由你出修正方案，Codex只落地、测试、反馈。因此发现下面问题后没有继续自行修复。

唯一主目标仍为当日全部港股通收盘涨幅Top20；无市值限制、不限D1、不删已大涨。D1Top100只做选择输入。

请实际读取REVIEW_RESULT.md、SOURCE_AUTHORITY_FACTS.md、manifest.json、r2.diff与当前源码。

已通过：Fix1实际source/formula/rule哈希及完整有序行绑定；Fix3 hit/markout分离；Fix4共享capture静态校验（日期P1除外）；100成员、真实Top10一致、alias冲突拒绝与回调失败隔离。

仍失败：
1. truth authority在文档中写blocked，实际自制40行且内部自洽的JSON仍可append_labels READY。现有权威源又确实缺失关键合同。
2. captured_at仅检查<=cutoff，20260920采集时间可作为trade_date20260921的FORWARD_NATURAL记录并FROZEN。
3. time_evidence.source缺失仍通过，其应绑定什么现有身份尚待裁决。

现有source已经定位，不再泛泛说缺数据：formal FUTU_HKCONNECT_PLATE_MEMBERSHIP authority chain在20260911缺失；691行security-master使用panel fallback且无直接历史panel hash绑定。691行Futu close snapshot有pct_chg_close=round((close/pre_close-1)*100,8)，但无公司行动/复权语义、FINAL receipt、source tie-break、停牌政策。现有formal loader该日又有651 canonical约束，不能擅自选691或651作为事实。细节与producer源码在包内source_evidence/。

请输出一个不扩大选股研究的下一批冻结合同：
A. authority未就绪时，如何最小且真正fail-closed（区分工程truth fixture和真实admission），允许改哪些函数和必须跑哪些反例？
B. 日期/PIT补齐的准确时区、采集日期、阶段时间范围和实际time evidence绑定要求；不要让操作员自己填时间就算证据。
C. 现有authority链与close producer缺口应交哪个既有owner、最小字段和产物怎么补；哪些需要用户/source owner明确冻结，哪些可由已存在的代码证据确认？不得新抓第二底板，不恢复无关三个月。
D. 在source合同未成立前，明确哪些工程测试可继续、哪些真实capture/label必须禁止。

附件是可审阅源码与证据包，未包含完整V4依赖，因此Chat环境不能完整pytest时请勿视为代码失败或独立通过。独立本机结果见REVIEW_RESULT.md。包内测试组合有重叠，不累计冒充总数。

RESEARCH_ONLY=true; shadow_only=true; production_allowed=false; buy_gate_updated=false; orders_sent=false; automation_created=false; natural_sample_count=0。
