# 76股实际接入SOP（R2）

2026-10-27实际完成本地既有个股历史API的typed消费接入，数据截止2026-10-26。逐股原件、根因范围、修法、SHA、明日复用及失效条件见STOCK_SOP_76_INTEGRATED_R2.csv，76行原候选SOP另保留不改。

- 全76：100266行/152页的机械对账与原公式候选审查已通过；接纳文件原publish锁/CAS提交，现役API运行身份实际通过。
- 抽检000523.SZ、600030.SH、601868.SH：各六日实际HTTP全部行字段/23信号匹配，现有页面各96单元匹配，主图六K及四线已目视；其余73股未逐股HTTP/UI，不把机械全检升级为逐股页面认证。
- 原Mac接纳口径与SDK直接QFQ是不同来源/量坐标；不据此断言原TDX价格坏。原价原量保留，不二次复权，不拼接旧坐标历史。
- 明日可复用同capture的26日及之前历史查询；27日及以后不能用旧快照冒充新日。未来capture自动续期尚未接通，超界请求按已审协议CANNOT_CONFIRM；回滚本事务admission可恢复原默认消费。
- 完整上市历史、PIT、UNKNOWN_NONPIT复权锚、业务收益、自然日更均未认证。
- 原双CURRENT与大底板未写，5538成功/270隔离、25股23日冻结、其他Chat15/338/7与301314边界保留。249条按既有SOP分流另见a_share_local_panel_completion_20261024/mac_panel_update_20261026_r2/sop_reuse_249_20261026_r1；自动生命周期过滤仍未安装。
- R1发布entry_count漏项及恢复原件保留，R2只修metadata/身份控制并增量审查，76数据不重算。非阻断P3诊断信息问题留review/REVIEW_CONTEXT_R1.md后续，不扩本批。

实际接入/样本/截图入口：ROOT_COMPLETION_RECEIPT_R2.json。回退严格执行r2_entry_count_repair/ROOT_ACTIONS_R2.md：先admission_control.py rollback，仅本事务postimage匹配才撤销；需要时root_cutover.py recover，复用原锁/guard/CAS、API-only reload和分层旧基线证明。第三方修改拒绝覆盖，不擅自改权限。

RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。
