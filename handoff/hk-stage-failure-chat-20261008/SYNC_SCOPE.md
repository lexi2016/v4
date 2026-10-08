# 同步范围

此分支只同步本轮问题交接说明、脱敏摘要和完整ZIP文件校验清单；source/、tests/ 与 publish_minimal_git_sync/ 文件位于用户收到的本地ZIP，不在本分支新增目录内。没有业务源码修复或部署。

ZIP: V4_HK_STAGE_FAILURE_CHAT_20261008.zip
SHA256: 5e38cc42aad5614dbb377254c16ed89996f5ba933aea102d579410d0508d4674
字节数: 221220；文件数: 52。

独立Luna Max Reviewer包验收PASS：51项checksum、52个ZIP成员、目录逐字节一致、ZIP完整性与最小基线12项检查通过。REVIEWED=PASS仅针对问题包，项目测试NOT_RUN，BEHAVIOR_VERIFIED=CANNOT_CONFIRM。已有测试缺少单独行级signal_date不匹配回归，PROMPT明确要求Chat新增。没有宣称阶段修复成功。
