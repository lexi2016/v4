# Chat 修复请求：R4 Mac 479 项套件的只读 fixture 副本权限

R4 固定 suite 在 macOS 26.6.2 arm64、Python 3.14.6、uid 501 下得到 413/479，66 个 PermissionError cases（8 failures + 58 setup errors）。R4 的只读源文件为 `0444`；测试用 `copytree` 保留了 `0444`，之后又尝试修改 **测试自己的临时副本**。Linux EUID 0 的作者环境会绕过该文件模式，因此此前没有显露问题。

请只修测试临时副本的权限准备，保留生产/候选包只读属性和原有权限断言；不要 chmod 原始 package、candidate、after、source tree 或修改业务/发布脚本。

具体位置：

- `tests/api/conftest.py:110` 复制只读 API source fixture。
- `tests/api/test_preparation_and_legacy.py:29-31` 及同文件中对 `tmp_path/api_source` 的准备/失败路径覆盖会修改该副本。
- `tests/api/test_research_read_binding.py` 的 `test_loaded_reader_source_drift_is_rejected[...]` 会在临时 API source 副本中改 `consumer.py`、`execution_evidence.py`、`research_read_binding.py`。
- `tests/integration/test_live_release_preparation.py:72,78-80` 复制并修改只读 `package/after/api/apps/api/v35_api/app.py`。

最小做法是在每个明确要写入的 `tmp_path` 副本上、执行对应测试 mutation 前，仅给目标文件增加 owner-write（必要时仅目标父目录），或为这些 mutation 提供一个 test-only writable-copy helper。不得递归放宽整个 package/source tree 的权限。继续验证原包和 candidate 的字节 SHA、`0444` 模式未变，且工具仍拒绝对原始只读输入写入。

验收顺序：

1. 在 macOS 普通 uid 501 环境定向运行上述 API preparation、loaded-source-drift 和 integration preparation 测试。
2. 确认它们修改的是 `tmp_path` 副本，并断言原 package/candidate SHA 与 mode 完全不变。
3. 在同一 Mac 权限条件下重跑完整 479 项套件；要求 `479/479 PASS`、零 skip/failure/error/cancel/todo。
4. 交独立 Luna Max Reviewer 复跑与检查实际 diff。修复验收前不得把当前 R4 候选提升为可部署状态。

复现与审计证据：

- Writer 结果：`/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R4_MAC_20261009/candidate/mac_apply_20261009_r4_01/independent_checks/RESULTS.json`。
- Mac 摘要：`/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R4_MAC_20261009/evidence/INDEPENDENT_CHECKS_MAC_SUMMARY.json`。
- 独立 Reviewer 结果：`/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R4_MAC_20261009/evidence/review/r2-local-20261009-r4-479-v35env/RESULTS.json`，SHA-256 `93892d84751999d65f88dff2aafc1eebceb60c28cc8959e2a3540f35b3216223`。
