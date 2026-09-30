# 本轮组合适配的实际验证

范围：旧业务2849459的B1/US33项原断言 + 新API6726的workspace/autorun与其余已验源码pin。作者Python 3.13.5/Linux；并非完整Mac候选958文件。原始业务41项日志在original_business/logs内保留，不改、不重算为本轮41通过。

## 结果

| 执行 | 实际结果 | 证据 |
|---|---|---|
| 旧runner对新API+B1/US | exit1，SOURCE_DRIFT:v4/manager_research/workspace.py；0项测试运行 | evidence/old_runner_red.* |
| 本包一次prepare_combo命令 | 33 passed，errors/failures/skipped均0，exit0 | evidence/combo33.log、combo33_junit.xml、combo33_receipt.json |
| 组合工具定向测试 | 7 passed，errors/failures/skipped均0 | evidence/adapter7.log、adapter_junit.xml |
| 原product补丁回退 | 两文件恢复前像，新文件移除 | evidence/PATCH_AND_PRESERVATION.json |
| adapter.patch正反回放 | 精确字节一致 | 同上 |

原33项的测试源码全部与2849459一致；不删断言、不跳用例、不换fixture。新7项只验证新组合pin与工具边界，不属于新增业务功能。旧API14项与B2的旧8项本轮均未执行。

## 源码适用证据

1. 从已上传R3B workspace + ec257948原件，在临时目录实际应用6726 actual_diff.patch。补丁原字节SHA `8f36b8653e771688e4888636206a9f5a6398acf1183ba1507423b3c30172a587` 与receipt一致。
2. 重建后的workspace为 `35c9292d3b422c9d5a744590cc472de5bfa2da8a62d12c6382ca0d1a9b3a6168`，autorun为 `e785ae1d465175bec0517e7c3b4a8d6e16593967cba554aa0428817a85cd079b`，完整SHA匹配，非根据前缀猜测。
3. 作者参考app使用既有原reader/store/classifier依赖；selected原依赖SHA与原AUTHOR_REFERENCE_INVENTORY对齐，新增API双文件除外。复用原包缺少的声明文件py.typed和原pypdf许可证，没有放宽validator。禁止部署作者参考树。
4. 原runtime.patch在新API前像实际应用；前后所有文件差分只有workspace_announcements、issuer_us_relations、eastmoney_run_history。新workspace/autorun/connect_selection不改。
5. 合成上游和原本地存储行为测试不是资格供给、网络、API/UI或自然运行证明。独立Mac组合验收未在本轮执行。

B2本轮只做现有源码入口判断和精确缺口隔离，未完成RPC入口版patch，未声称新native B2兼容。详见B2_ENTRY_STATUS.md。
