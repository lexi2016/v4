# 冻结的四个功能问题与接受条件

证据以固定 R2 candidate release 为准：commit a7f5d09fb19de10564925757207977aadc080cc1，release manifest SHA-256 f6385dd23e9fda4d2169f20d6dc68b6e1e519b2b1a35e1ceb0bfd3111a079ad5。直接 app-wired create_app/get_workspace 的报告为 SHA-256 8c654e5838d669ec641061d275f4d30e7a727ef535b87b5636c12f694e5e1e5d。机器 receipt 文件 SHA-256 776f5646a6537321d69360c7bf66b2fb59147db2a1cc83bff654d058e6f3b1f1；receipt 内部 canonical hash 是 6ab0071ed312b09d11be2025ae3a3d740db08375b3cf5ca264579f979e046055，两者不是同一字段。

| 问题 | app-wired 10/09 观察 | 原 owner / 消费端 | 最小接受条件 |
|---|---|---|---|
| Announcement 未导入 10/09 选股 | ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED；0 rows；review NOT_RUN | 现有 announcement catalog/body capture、独立 Reader、独立 Reviewer、register-handoff/import owner；消费者在 workspace_announcements / announcement_analysis / GET workspace | 绑定 target=20261009、publication=20261008 的 capture、Reader/Reviewer 两份原始输出与 SHA；由现有 owner import 后 GET 显示消费 rows 或证据完整的明确空结果。不得伪造 Reader/Reviewer 身份。 |
| HK Connect 未验证目标成员 | HK_CONNECT_TARGET_AUTHORITY_ROOT_NOT_BOUND、TARGET_HK_CONNECT_MEMBERSHIP_UNVERIFIED | 现有 HK universe V2 authority/config owner；consumer connect_selection.read_scope | 精确目标日 20261009 的 authority manifest/source root/SHA，能证明目标 HK_CONNECT membership 与 acquired/available 时间早于 cutoff；消费端显示 members/count 或可证明确空。不得降级 BUY。 |
| Oversold 缺精确日期 master | SCREEN_SECURITY_MASTER_READ_FAILED:HK_SECURITY_MASTER_EXACT_DATE_ENTRY_MISSING；verified_session=20261008 | 现有 HK security-master/panel owner；consumer hk_security_master 与 workspace_plan | 同一 root/cutoff 下有 20261008 security-master index/manifest entry、snapshot、HK02 panel 与成交量来源 provenance；读取到 screen result 或证据完整的明确空结果。不得回退 latest 日期或重贴 D-1 标签。 |
| Plan saved product 与当前 identity 不同 | STALE_INPUTS_CHANGED，consumed=false，run_readback=CANNOT_CONFIRM；saved input identity 5df99128…，当前 identity 7c5d9f18… | ManagerResearchJobService.refresh_workspace_plan + workspace plan readback | 输入不变时由原 owner 重建并验证 run/product/input SHA 后 CURRENT；输入变化必须保持 STALE_INPUTS_CHANGED。不得绕过 identity 比较或消费旧产品。 |

现有单日 owner 接口的解释见 DAY_RUN_REUSE_AND_INTEGRATION.md。原因并非四个确认的代码 bug：三项当前是 owner 输入/authority 未绑定或缺少，第四项是 stale guard 忠实报告身份变化；Chat 应先沿固定输入查 producer → artifact → reader → plan consumer，再提出最小修复。修复不能新增 producer、collector、面板或绕过真实数据门槛。

完整 GET 实际回传 0 stocks，Announcement、HK_CONNECT、OVERSOLD 均 CANNOT_CONFIRM；外加 plan 原生 close read PLAN_NATIVE_CLOSE_READ_FAILED:20261008:FileNotFoundError 在注入实际 reader 后仍然存在。计划还有 breadth/amount、native HK universe、material discovery security-master、Vibe owner 等缺项；这些属于 additional required owner inputs，不扩为本包额外冻结问题。

安全标志必须保持 RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。
