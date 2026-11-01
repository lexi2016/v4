# R2.2执行后反馈：只剩一个独立P1，请给最小修正合同

已按你R2.2只改三文件，selection.py/ops锁定不变。独立复跑62tests通过，实际selector返回identity、directfreeze状态、三方Top10、sealed bytes、local/external状态分离全部通过。但独立Reviewer发现一个不满足你原合同Do not symlink的反例，故工程scope仍FAIL。

请读取REVIEW_RESULT.md、当前源码与r2_2.diff。唯一问题：预先把run_root/provenance设置为指向outside的目录软链接后，capture把五类provenance bytes写到outside，本地verify仍PASS；修改outside文件后本地verify失败。当前写入/读取仅检查最终文件，未检查父目录。

用户明确工作流：Chat出方案，Codex落地测试反馈。发现本问题后没有自行修复。请只给覆盖该既有边界的下一批最小合同：
- 允许的文件和函数；
- 写入和verify应如何拒绝父目录/中间目录软链接、确认封存实际位于run root内；
- 无效情况如何拒绝且不在outside写出文件；
- 最少的反例（写前symlink、封存后目录被替换为symlink、正常本地封存、外部原source漂移不影响已封存bytes）；
- 明确无需重开margin/selector/owner/服务/自然canary，也不要扩大为无限供应链或恶意Python威胁模型。

正式目标仍全部港股通收盘涨幅Top20，未开始任何自然样本。REAL_AUTHORITY/BLOCKED_OWNER_PENDING不作为本批工程FAIL理由。
请给一个可完成的闭环验收终点，不重复恢复20260911或调整策略。
