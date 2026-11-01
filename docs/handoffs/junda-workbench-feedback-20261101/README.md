# 钧达单股工作台反馈修复

范围：钧达股份 `002865.SZ`，2026-10-30 收盘来源、2026-11-02 观察看板。日期控件、单股历史图上的 KB 事件、当日信号合并和研究资料缺口展示均沿用原工作台；原 172 只候选、原式买卖点及既有 57 个 KB 字段保持身份。

两份单股候选各增加 17 个知识库持有评分字段和 4 个 S/14:55 滴滴三态字段。未知分项不计为否，未完全确定时总分为 null，并提供得分上下界。`contracts/a_share_kb_hold_score_v1.json` 和 `contracts/a_share_kb_supplemental_signals_v1.json` 固定规则、字段和来源；旧 `ref_hold_score` 保留原身份。相同日期的原式历史覆盖、公司、财务和研报缺口如实显示，不借用其他股票或旧日期资料。

QFQ 日更单股 checkpoint 仅在两个角色 schema 都包含完整 21 列时启用新字段；不完整 schema 及会丢失已算字段的建表直接失败。旧 legacy schema 不启用本扩展。原 vendor 建表器的单股真实前缀写入和回读已通过；完整 `run_daily_rebuild` 与自然日更尚未验收。

验证：针对性测试 34 项 Python 和 2 项 JavaScript 通过；P1 返修的受影响检查 15 项通过，独立 Reviewer 对修复及最终身份链均为 `REVIEWED/PASS`。隔离页面验证日期、hover、点击、窗口和历史 KB 标签；重新绑定后双角色全部列和页面行逐项相同。源门禁、COW inventory 和临时 API smoke 通过。

单股展示本地候选 `junda-single-20261101-8e342a6d64746507` 已由主控激活，generation `8e342a6d6474650793dac707508689d28925f5ecac0bcd620b34b0395d22b317`，activation receipt SHA-256 `2c3ca2afa3f2664894120848275ba2c5b0a439ed3feefaa8edc1e096a618726f`。这次激活没有切换两个全局面板指针、Main 或 seed；真实 8873 UI 回读由主控另行记录。

部署基线为当时实际 API owner `date-history-fix-20261101-r1`，保留其其他源码、inventory 和 integration 元数据；候选在该基线之上应用七个审阅后的展示 delta。此源码分支不声称包含该 owner 的完整构建输入或可独立复现整个现役服务。精确来源、字段清单、可回退操作和证据哈希见本机 `junda_feedback_20261101_r1/REVIEW_HANDOFF_R2.md`。

研究专用：`RESEARCH_ONLY=true`，`production_allowed=false`，`buy_gate_updated=false`，`orders_sent=false`。
