# 剩余 collector / builder 修复

本组件以固定提交 `0fc3e8304e11700230517616ded0c86f83a4b257` 能取得的源码及其 R1 输出后像为基础，新增三个最小改动文件。不是现役 Mac 读回；当前 Mac 三个目标文件必须满足 `COMPONENT_MANIFEST.json` 的前像 SHA，才可向隔离 canary 应用补丁。`runtime_collectors.patch` 已正向、反向应用并逐字节比对。

## A 股字段贯通

09:25 builder 现在原值传递 `SourceResult.rows[*].prev_close_price`，修复已确认的源有昨收、builder 丢昨收断点。原竞价 collector 会把精确竞价 CSV / 原历史提供器给出的昨收放进 SourceResult，原 R1 selector 负责输出日涨幅、保留实际零值及缺项理由。

分钟链不需要另写采集器：原 PyTDX HQ 固定 probe 的 `normalize_rows` 接受源端明示 `last_close / prev_close / pre_close`，原 minute aggregation 输出 `prev_close_price`，原 `_to_source` 保留行字典，原 builder 已映射为 `qmt.lastClose`。新测试实际经过这些原函数、原选择器和磁盘 SelectionStore，证明上述现有字段通路；没有把本次合成响应称为 Mac 真行情。

缺少源端昨收继续输出 `null` 和 `PREV_CLOSE_PRICE_MISSING`，实际昨收有效且当前价相同继续输出 `0`。不把当日开盘价当昨收，不新增日线查询或另一行情来源。

A 股可选研究/资讯上下文根缺失，或原 `load_research_context` 抛出 `ResearchContextError`，现在只停用该补充上下文并保留原错误。原算法输入中的研究标量为缺失，原公式不给该项 bonus；展示字段保持 null。原候选、行情、原始 SHA、结果及 SelectionStore 完整性错误继续抛出，不被该限定异常捕获。

## HK 当前日研究模式

仅在 plan 的 HK binding 明确为 `CURRENT_DAY_RESEARCH_ONLY` 时启用。调用 HK 组件 `research_metadata(binding)` 校验研究摘要及日期/阶段，并要求 collector 的完整有序 codes 与 binding.codes 一致。

研究分钟使用现有 `scripts.live_acquisition.pytdx_exhq.collect_pytdx_exhq_minute`，复用原固定阶段窗、代码分批、分钟聚合及 SourceResult 转换。15:45–15:55:05 研究窗口不再走正式 Stage8 RT_DATA 历史回放入口，不构造无关的回放 provider，不请求 Futu 实时强势/港股通成员 predicate。正式模式的上述分支保持原行为。

builder 将研究行送进原 `select_hk_four_lane` 已有的空 lane 观察路径，原四路评分、权重、排序和 Top10 字节未改。不给研究行增加 `LIVE_HKCONNECT_GAINER`、D1 模型或 09:20 二筛身份。研究来源元数据只在原排序和 Top10 完成后附上，并用原 immutable identity helper 重新绑定最终行。

每个研究选中行标明 `source_mode/input_mode=CURRENT_DAY_RESEARCH_ONLY`、`input_binding_sha256`、`universe_as_of`、`security_metadata_captured_at`、`stale_universe`、`current_connect_eligibility=CANNOT_CONFIRM`、`formal_eligible=false`。envelope 保留完整 `hk_current_day_research`，另列 `algorithm_input_contract`，避免把相同公式 SHA 误解成已满足正式 D1 输入合同或可比较的正式研究结论。

实际行情时钟仍是原分钟行 `update_time` 经原卡片生成的 `source_last_bar_time`。security metadata 的 captured_at 不会填入报价时间。原证券资料中的 `last_price` 等额外报价字段不能穿过 HK 输入模块允许的九个资料字段；`circular_market_val` 暂不转成原算法平台流通市值输入，因为本包没有独立核到它的单位语义。

用户报告的采集是 2026-10-09 15:38:41+08:00，本组件没有读取该 Mac 文件。该时点晚于前面所有分钟阶段的 cutoff，因此现有八阶段中只能为 10/9 的 15:45–15:55:05 窗口供研究输入，不能用于早盘或 15:00 阶段。此限制由 HK binding 模块校验，不通过伪造 evaluated_at 绕过。

## 实际测试

完整套件在 actual 与 canonical 各自源码上执行：两套原前像均 **32 failed / 4 passed**；两套后像均 **36 passed / 0 failed / 0 error / 0 skipped**。actual 原始红绿记录在 `evidence/final_before`、`evidence/final_after`；增加变体测试入口后 actual 复跑记录在 `evidence/actual_variant_after`，canonical 红绿记录在 `evidence/canonical_before`、`evidence/canonical_after`。记录均含 stdout、stderr、JUnit、命令、Python/系统信息和测试源码 SHA。

覆盖 A 竞价 4 种昨收情形、6 个分钟阶段逐股字段通路、216 完整请求与 205/206 行行情、原 Top10 选中第 200 行以后样本；HK 695 完整请求与 684 行行情、原四路排序和 Top10、无 LIVE 假 lane、来源时间分离、不可用分钟不得由证券资料补价；STRICT 默认有/无 lane 的完整 envelope 与 frozen before 相等，正式 Stage8 仍调用原回放。

源码 witness 专项用原 `HourlyResearchStore` 在临时目录发布合成 archive/receipt/manifest 和 SHA 一致的源文件，故意让 archive 内容不同于源的原投影。原 validator 实际抛出 `RESEARCH_SOURCE_WITNESS_INVALID:SOURCE_ARCHIVE_PROJECTION_SHA_MISMATCH`，builder 保留该错误并继续用有效行情调用原算法；原研究文件逐字节不变，选股产物另行写入原 SelectionStore 并读回。没有 mock 这个 validator 或错误字符串。

Linux / Python 3.14.7 测试使用合成 source responses，provider 网络调用为 0。Mac、真实行情采集、8873 HTTP/浏览器、部署与自然时段验收均未执行。

## 精简复跑

将本组件与主包其他补丁一同应用到核过 SHA 的隔离 canary 后，可在已有含 pytest 的本机 Python 环境运行：

```bash
python3 run_tests.py --variant actual_stage --phase after --runtime-root /绝对路径/隔离canary/app --output /绝对路径/新的验收目录
```

脚本先逐个核对 canary 的三个改动文件是否正好等于组件 after，且存在 HK 研究 binding 模块；不匹配时停止，不覆盖 canary。随后运行离线合成链路测试。真实证券资料与原 ExHQ 行情、发布、API/UI 同一 run 的验收沿主交付命令继续。

`collector_registry.py` 的已附 canonical 前像与 actual 相同；`hk_minute.py` 与 `selection_builder_registry.py` 的 canonical 前像不同。因此另附 `canonical/{before,after}`、`canonical/runtime_collectors.patch` 和独立 SHA 清单，保留 canonical 原有的历史研究合同及旧分支；禁止用 actual 完整文件覆盖 canonical。canonical 复跑将上面参数改为 `--variant canonical`。`evidence/canonical_preservation.json` 验证额外合同 helper AST、历史 builder 分支、旧分钟尾部均保留，补丁正反向逐字节一致。canonical 中已有的外层 `_selection_identity_ids` 继续复用，未引入可能遮蔽原历史分支的局部 import。

仅将对应前像的补丁应用到负责 Stage 的 owner/canary；API 继续按原产物协议读取，不要求先拆分模块。
