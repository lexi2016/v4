# 验证记录说明

这些记录只证明列明的候选工程行为，不能替代 Mac、8873、实际 owner 或自然验收。

TEST_RESULTS.json 汇总实际最终结果；original_suite_comparison.json 保留全部 106 个 case ID、各自终态、29 项共同失败、命令、时间、退出码以及完整日志/JUnit 的 SHA，只删了重复长 traceback。ORIGINAL_REGRESSION_REVIEW.md 保留逐类归因，尤其是原 6 个 bad_readback 断言分歧。

独立报告按 EVIDENCE_INDEX.json 从 Reviewer 产物逐字节复制；报告中的绝对执行路径是当时环境记录，未全部作为交付文件重建。reproduction/ 中的脚本保留原执行路径和依赖假设，不是 Mac 一键部署入口。HK 30 项摘要只移除了重复的合成 source envelope，保留每项预期、实际计数/顺序/状态及 PASS/FAIL。

SUPPORT_PROVENANCE.json 的 28 个固定原文件及 FRONTEND_SUPPORT_PROVENANCE.json 只为隔离测试补齐依赖，本包不分发这些代码为生产依赖。完整 consumer import、完整 app build、全量原测试失败及现场未知项均保留。

RED_GREEN_HISTORY.json 记录开发期间的复现/修正摘要和原日志 SHA；这些阶段的用例数量与源码不同，不能累加为最终通过数。跨语言 fixture 与 Parquet 股票/日期均为合成样本，不是实际 owner 选股结果。
