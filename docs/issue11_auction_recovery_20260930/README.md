# Issue #11：A 股 09:25 一次修复恢复额度（源码候选）

## 状态与基线

Refs #11。代码提交 `f8aaea6ab0fe7f94cd4ca5f6ec07821c0d24d8f6`，基线 `3d03ca4ade08ac4c5f3f049756997d3934c782e3`，PR base 为 `codex/stage-selection-mac-resume-20260929`，不向 main 混入源码导入。

本次只修改两个产品文件：`ops/_run_stage_center_nodes_parts/node_entry.py` 和 `stage_dispatch.py`；另有两份新测试及一份原测试替身修正。没有改采集器、行情数据、其他阶段预算、HK D-1 规则、评分、模型、API 或 UI。

**源码候选及作者 Linux 合同测试已完成；独立 Reviewer、Mac 前像适配、目标解释器测试、集成、部署、真实恢复、API/UI 和自然运行均未完成。不要关闭 #11。** 旧事故撤回通过只代表活动文件恢复，不代表本候选或业务通过。本候选不是那份误写活动包的旧候选。

关键阻断仍须保留：GitHub 的 stage_dispatch 前像 SHA 为 `df6221a177d82f0fd683896b3ef21cd66cd7a8a4b6c6c8b95571f277108d52fe`，issue 报告的 Mac 活动前像为 `dcb4784d1374fbe8f9076646b6befba4b48331826a7f07a82c25e497820689d4`，**不同**。node_entry 的 GitHub 前像与 issue 报告同为 `54defb0f45adbafcf4b661611f41d0b43d89abf492d89d587c28962eff9b36fe`，但这里没有现场读回。不能直接覆盖安装。

## 根因和最小复现

原调用链：`run_nodes(explicit_node)` → `stage_dispatch` → 旧回执/三次预算 → 原 HK dependency rearm → 原 SlotLock → 原 StageCenterRunner._run_one → 原 raw/selection 与 receipt writer。

旧 A 股失败不符合 HK 专用 rearm，因此直接 `SKIPPED_RETRY_EXHAUSTED`。不应复用 HK 授权或清零计数。本候选增加明确的一次修复额度：原 3 次 + 单独 1 次，总调用上限4，不是“额度未变”。

最小合成例：精确日期/阶段、三次 TypeError 旧回执、六个 START/RETURN、205代码身份、不同 writer/reviewer 的批准合同全部匹配时，旧代码仍跳过；候选在原锁内先持久化授权审计，再调用一次原 runner。缺失回执、损坏回执、无关错误、身份漂移、隐式扫描、重复授权等必须不调用 runner。

## 授权与持久化合同

运行配置只有显式提供 `a_0925_recovery_authorization` 及其 canonical JSON SHA256，且 `run_nodes` 收到精确 `20260930 / STAGE_0925` 的 explicit_node 时才进入候选路径；定时全节点扫描不能使用它。wall clock 和 evaluated_at 都必须是本日，禁止未来 evaluated_at；必须为 RECOVERY，其他日期不生效。到下一日失效，不伪造 wall time 重放授权。

授权对象必需字段：

- `schema_version=stage_center.a_auction_recovery_authorization.v1`、`issue=11`、`trade_date=20260930`、`stage_id=STAGE_0925`、`market=A_SHARE`、`mode=RECOVERY`。
- `additional_attempts=1`、`candidate_count=205`，必须是真整数；三个 safety flags 均为 false。
- `approval_id`、`writer_id`、`reviewer_id`、`review_status=APPROVED`；writer/reviewer 必须不同。身份字符串与 SHA 并不构成数字签名，实际批准仍由 Mac owner 与独立 Reviewer 完成，本交付没有生成可用批准记录。
- `original_receipt_sha256=b920987cdecc63d0f7857c50404b3807c8f5212f418be304f75a11a06500a87f`。
- `candidate_artifact_sha256=92023837d8709abfb46fb03dec82ee9758ff56e57615cdfebeb98926e3789d72`、`codes_sha256=80f5a1c0bbed293b637d1a2bb25585de932ce5b235dd3ff0236fcb9a99d8eb69`。codes SHA 当前按原序列 JSON list canonical 序列化计算，必须与 Mac 实际口径核对，不能重排以凑 SHA。
- `original_attempts`：精确六个 `attempt_evidence/...` 相对文件名及字节 SHA；必须覆盖1/2/3各 START/RETURN，不搜索“最新文件”。
- `fixed_modules`：实际加载的 `stage_center._live_collectors_parts.a_auction` 与 `infrastructure.tdx_minute_replay_provider` 的文件 SHA；须位于当前 app 根内并经 SafeRoot 读取。

canonical JSON 使用 `ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False` 的 UTF-8。外层配置 `a_0925_recovery_authorization_sha256` 绑定整个授权对象。

**GitHub 基线仍含已知未修复 collector SHA `b74756748e98035d8058447f5f2644aa5709e4739bfe0ee9f365d4f0c7094e2c`，代码明确拒绝它，即使配置填了其自身 SHA。** Mac 已修复的时区代码不在本次产品 diff 中，不能把本候选当作已经包含该修复。

进入原 slot lock 后再次核旧回执、输入、修复代码身份，随后以原 SafeRoot 原子 require_absent 写 `a_0925_issue11_recovery.json`。记录旧 receipt 原字节的 base64、旧字节 SHA、六次证据 SHA、完整205候选身份、批准 SHA、真实预留时间、原3次/新增1次。先预留后调用；崩溃也消耗额度，不能自动再领。

原 runner 可正常写新的当前 receipt；原旧 receipt 字节留在上述审计记录中，原六个 attempt 文件不修改。新调用使用 attempt_number=4。新结果记录 `CODE_REPAIR_RECOVERY`、`real_time_success=false`、`L0_HISTORICAL_TRANSACTIONS_NOT_COMPLETE_AUCTION_BOOK`，不声称自然竞价完整盘口。

有效 A 结果不得覆盖。SelectionStore 的全局 latest 中存在其他阶段是正常现象，不阻断缺失0925；仅精确0925 entry 存在时核原三件套，损坏 entry 不当作不存在。已用 marker（包括符号链接）禁止再次执行；顶层汇总不能把这种状态写成 NODES_COMPLETE。

## 作者测试和局限

环境 Linux Python 3.13.5 / pytest 9.0.2；目标仓库要求 Python>=3.14、Mac服务报告3.14.6，因此不是目标运行验收。未重装或修改依赖。

最终命令：

```sh
python -m pytest -o addopts='-W error' tests/test_issue11_a_auction_recovery.py tests/test_issue11_recovery_failclosed.py tests/test_manager_stage_rearm_rework.py -q
```

实际输出：`58 passed in 0.31s`，exit0。39个新增 guard 合同用例、19个原 HK rearm 用例。输入、日历、修复模块身份和 runner 业务调用是明确的合成/替身；文件审计、SafeRoot、原锁、attempt journal、SelectionStore 指针与兄弟阶段保全使用实际实现。**没有执行真实205行行情、timezone fix 或完整 StageCenterRunner 业务。** 已知未修复 collector 的拒绝测试不替换实际文件身份。

原 HK 用例在未修改产品基线上为5失败/14通过，原因是旧替身缺少 `preselection_source_root` 关键字及 `scheduled_at/_receipt_path` 诊断字段。本 PR 只补替身参数/字段，原断言全部保留；修正后的替身在未修改产品基线也19通过。不是为让新增产品代码通过而删断言。

新增4个缺失/损坏旧回执负例实际先为4失败，修复显式授权落入正常首次执行旁路后通过。另曾发现并修复其他阶段 latest 错当0925已有结果，以及已用额度顶层误报完成的问题。

额外受影响回归命令：

```sh
python -m pytest -o addopts='-W error' tests/test_stage_source_root_repair.py tests/test_hk_attempt_evidence_repair.py tests/test_stage_morning_root_wiring.py -q
```

候选与未修改产品基线均为 **27 passed / 5 failed**。失败同为 morning-root 文件中的：`test_stage_config_and_runner_bind_hourly_and_morning_roots_separately`、`test_missing_root_and_zero_mentions_remain_cannot_confirm`、`test_20260924_authoritative_readback_uses_configured_root_without_promoting_empty_parser`、`test_legacy_node_config_without_morning_root_only_blocks_a_research_lane`、`test_standalone_tick_wrapper_accepts_legacy_config_for_nonresearch_lane`。分别涉及已有显式来源根合同、缺少本机 morning shared contract、Mac绝对配置路径不存在。未删除、跳过或扩修这些失败，不宣称全仓通过。

Linux限定测试 override 是因为容器缺仓库 warning filter 引用的 Starlette 类别，仍保留 warnings-as-errors；没有修改仓库 pytest 配置。代码/测试使用原缓存作为字节载体，并对本批5个变更文件做远端 Git blob 一致性读回；不是1312文件及全部运行依赖一致性认证。

## Mac 最小接续（不是执行授权）

1. 只在新的 worktree/隔离目录读取 PR。先通过 launchd 的实际 ProgramArguments 确认活动 app，不能由目录名 candidate 判断可写。不要复制本 PR 文件到活动目录。
2. 将活动 stage_dispatch 的最小源码 diff（对应上文 dcb... SHA），以及已修 a_auction/provider 的相关函数和完整文件 SHA，通过当前 GitHub 分支补齐。三方适配保留现场最新保护；其余文件按 identities.json 前后像核对。无需上传整个项目或行情 ZIP。
3. 独立 Reviewer 在目标解释器复跑58项，并核实际 corrected module 身份和已知 TypeError 的修复证据、205输入全量顺序/哈希、六个原 attempt 的相对路径/SHA。真实批准前不得填 APPROVED。
4. 本批两个 ops 文件会改变现有发布清单 pin。仅在独立审核适配后为这两个准确后像更新隔离候选清单；不取消 SHA 检查、不重写活动 manifest、不复制整个 dirty workspace。保持两服务现役职责、原HK规则和其他阶段。
5. 经单独本机授权后，使用原入口的精确 `--node STAGE_0925 --trade-date 20260930` 与隔离的批准配置完成一次恢复；不能用全节点扫描、counter清零、force或重试预算扩大替代。这里没有执行该命令。失败保留一次额度消费和错误，不自动第二次恢复。
6. 由原消费者/API读取实际 selection run、raw/manifest/receipt SHA、行序与逐行限制，再核普通UI。只在真实原产物中已有的 RECOVERY/L0语义得到正确展示时才验收；本次未修改API/UI，不保证其已显示新增receipt字段。A五个已工作的阶段不重跑。

最小证据仅需上述源码差异、解释器/实际模块SHA、六文件路径/SHA、批准记录身份和最终run/hash/count/status；原始行情留Mac。完整旧receipt可继续留本机，本候选现场校验其固定SHA。任何源前像不符、授权过期或业务证据不足均保持阻断。

RESEARCH_ONLY；production_allowed=false；buy_gate_updated=false；orders_sent=false。没有采集、部署或正式补跑。#10 另行处理，不混入此候选。
