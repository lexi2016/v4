# 本轮测试与证据边界

## 最终版本实际执行

最终整包运行于 **2026-10-09 10:53:13–10:53:32 UTC**，Python 3.12.14、Linux x86_64、Node 24.19.0；Vue、compiler-sfc、server-renderer 均为 3.5.13。完整实际命令、工作目录和返回值保存在 [evidence/final/RESULTS.json](evidence/final/RESULTS.json)，其 SHA256 为 `f2851fc64edfbe992f3708ba5fd330378690014473699208c3e818240497baa4`。

| 执行项 | 最终结果 | 证明范围 |
|---|---:|---|
| Stage、A 字段链、HK 准入/collector/原算法、owner/市场隔离、canary 与 witness 工具 | 148 passed | 包内 16 个 Stage 后像加 166 个固定测试依赖；真实转换和存储代码，外部 I/O 使用合成夹具。含 52 个 A 链路测试及 12 个新 canary 驱动测试。 |
| API reader、完整 consumer、backfill/身份/回执边界 | 82 passed | 两个最终 API 后像；正常/错误身份、研究来源、不可变回执及精确 backfill 根映射。 |
| 现有 Vue App 函数与执行证据面板 | 45 passed，0 failed，0 skipped | 真实 SFC 编译和 SSR、原 App 计数函数；包含 API 投影后的同 run 数据。 |
| 独立 fresh 695 全链 | PASS | 原 owner 历史 tick → 原 HK collector 路由 → 原四路算法 → Raw/SelectionStore → owner history → 无显式 receipt 参数的 API consumer → 已取得原 API 投影函数 → Vue。 |
| 字节与补丁 | PASS | 21 个 before/after、16 个集成 Stage 文件、5 个 API/UI 测试副本、分组补丁与 166 个支持文件 SHA 对应。 |

这三组是本轮 **275 项定向测试**。不能把它们说成完整现役应用总测试全通过，也没有把旧 Linux 287 或本地 Writer 14 加入本轮结果。

## 同一 run 全链的具体观察

[API 断言](evidence/full_chain/api_readback_assertions.json) 和 [Vue 断言](evidence/full_chain/vue_readback_assertions.json) 来自最终全链运行，记录：

- `trade_date=20261009`，`stage_id=STAGE_0930_0935`，`market=HK_CONNECT`。
- `run_id=run-2c40a8d057e1beffde847ab1`，请求 695，取得行情 695，选中 10。
- 原 HK 算法 SHA `fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506`。
- 原始行情 SHA `3c942a34e3dcb713ed250f0d42e5f031f4aa09e0cb09b3691678a0a288576741`。
- selection CSV SHA `aa69e1d04c009ac033434ec5be156465bff2db964b2a14815c00c7b894054100`。
- `OWNER_HISTORY_SHA_BOUND`、`BOUND_TO_VERIFIED_SELECTION_TRIO`，研究模式 `CURRENT_DAY_RESEARCH_REPLAY` / `RECOVERY`。
- `natural_verified=false`、`execution_verified=false`；A 没有借用 HK 的行或身份。

这 695 行证券资料和行情是**明确合成测试输入**。没有读取用户 Mac 的 695 行、没有采集真实市场，也没有生成用户可以据以交易的真实推荐名单。测试生成的 raw/完整响应无需上传，`tools/run_checks.py` 可在新目录重建；这里只保存精简断言和 [SSR HTML](evidence/full_chain/vue_panel_ssr.html)。

最后的 API 测试使用 `StageSelectionConsumer(actual_backfill_selection_root)`，没有显式传 receipt 根；由新增精确同 id 路径映射读取 owner。原 API 投影函数未修改，其引用 commit、原始 Git blob 和摘录 SHA 位于 [test_support/API_PROJECTION_REFERENCE.json](test_support/API_PROJECTION_REFERENCE.json)。没有运行完整 HTTP 服务。

## 原算法身份

| 家族 | 原 SHA256 |
|---|---|
| A live/auction | `eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2` |
| HK four-lane / 原公共 manifest | `fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506` |

两者本来就不同，不能合并成一个算法 SHA。排序、权重、Top10 及原公式文件保持；相关字节断言见 [a_algorithm_invariants.json](evidence/history/a_algorithm_invariants.json)。HK 原算法 manifest 的文字包含正式 D1 背景，并不认证本次输入资格；本次实际资格以独立的研究 binding 和 `formal_d1_eligible=false` 为准。

## 失败记录与修复轨迹

1. A 修复前同股完整链测试为 42 pass / 10 fail；补 registry 昨收透传和源 bool 处理后 52 pass。详见 [a_lane_results.json](evidence/history/a_lane_results.json) 及原始 before 日志。最终整包的 148 项又包含这 52 项，不能重复相加。
2. 首次打包复跑发现两个支持文件遗漏：Stage 135 pass / 1 fail（遗漏 `BASELINE_A_SHA.json`），API 48 pass / 28 errors（遗漏 `legacy_support`）。源码全链及 Vue 当时通过；遗漏已补，最终全部复跑为上表结果。保留 [package_first_attempt.json](evidence/history/package_first_attempt.json)，不隐藏第一次失败。
3. 最后发现原 API 仅传 selection root 时无法绑定 backfill receipt，针对性测试为 1 fail / 5 pass。新增精确同 namespace 映射后最终 API 82 pass，fresh owner 全链也改经同入口。修复前证据见 [api_namespace_red.log](evidence/history/api_namespace_red.log)。
4. 独立代码审查发现并修复：A 最后指针复核仍全局中断、两种旧 replay origin 仍可能被 NATURAL 覆盖、真实 NOT_DUE 回执缺 markets、坏 manifest 使诊断脚本抛未归一异常。最终候选已覆盖这些场景。审查记录见 `evidence/review/FINAL_REVIEW.md`。

## 已有应用测试的五个基线失败

固定历史支持应用的 19 个既有测试在 before 与 after 均为 14 pass / 5 fail；没有改写这些测试或放松来源校验：

| 既有测试 | 已观察到的缺口 |
|---|---|
| `test_exact_cutoff_selects_verified_slot_and_preserves_provenance` | 已存档夹具缺 source witness。 |
| `test_live_stage_uses_only_verified_formal_overlay_membership` | 已存档夹具缺 source witness。 |
| `test_persistent_v4_node_entrypoint_checks_ten_nodes` | 未提供 Mac 的 tick config。 |
| `test_v4_analyzer_is_pure_and_does_not_invent_stage_quality` | 缺 `upstreams/shared_research/v3_zsxq_adapter.py`。 |
| `test_node_cli_check_is_reproducible_without_network` | 硬编码 Mac venv 在 Linux 不存在。 |

此结果不是现役 Mac 独立验收。对应记录保留在 `evidence/history/a_app_before`、`a_app_regression_with_path` 和 A lane 结果中。

## 未执行或未取得

- 当前 Mac 21 文件字节、dirty canonical 三方归并、现役完整应用集成/构建：NOT_RUN。
- 用户那四个真实 HK 文件、真实 10/9 PyTDX 报价、实际 A 216 输入独立运行：NOT_RUN。
- 15:50/15:55 的实际 source archive/witness 差异根因：CANNOT_CONFIRM；不能从临时窗口的旧 receipt 归因于六文件。
- 真实 8873 HTTP/UI、既有发布链、现场自然触发验收：NOT_RUN。
- 0925 HK 竞价、1545–1555 HK RTDATA 的当前研究专用输入：未提供，未伪造。

四项金融标志始终保持：`RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
