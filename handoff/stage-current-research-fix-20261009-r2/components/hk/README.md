# HK 当前资料研究接线（R1 → R2 增量）

本组件直接补齐 `hk_current_day_research_root`，让 2026-10-09 已授权的当前证券资料进入原 Stage 分钟采集和原四路算法。仅消费既有资料；不发布新的 HK 预选底板、不改写正式 `latest.json`，不改变正式 D1 / `STRICT_0_2_READY` 默认合同。

## 输入与边界

`stage_center/hk_current_day_research.py` 内置的是用户在本轮明确提供的 2026-10-09 采集声明与四个文件 SHA。Chat 没有读取 Mac 上的这四个文件。本机执行时读真实字节并逐项核对，检查证券资料 695 行、参考代码 695 个、代码唯一且集合相等。参考代码保持原列表顺序，不受 UI 200 行限制。

证券资料只有 code、name、outstanding_shares、circular_market_val、listing_date、lot_size、stock_owner、stock_child_type、sec_status 等原字段。适配器不生成 last_price、OHLCV 或报价时间，也不把 circular_market_val 的未核单位猜成算法市值输入。

研究 binding 通过现有 `StageUniverseBinding` 传递，role 为 `CURRENT_DAY_RESEARCH_ONLY`；HK_CONNECT 只是原系统已有的技术 lane，不证明当前港股通成员资格。结果保留：

- `universe_as_of=20261008`；
- `captured_at=2026-10-09T15:38:41+08:00`；
- `stale_universe=true`；
- `current_connect_eligibility=CANNOT_CONFIRM`；
- `RESEARCH_ONLY=true`，三个金融操作标志均为 false。

本次资料取得时间晚于前七阶段，因此只可能用于 `STAGE_1545_1555`。前七阶段拒绝 HK 研究输入时，A 股仍可独立完成选股。执行保留真实时钟，研究 root 下的执行证据始终明确为手动研究，不冒称自然触发。

显式研究 root 无效时，HK lane 返回其具体错误；不会偷偷回退到正式 D1 或旧池。未启用这个 root 时继续使用原来的正式 D1 准入。

## 修改范围

9 个既有文件加 1 个只读适配模块：runner/configuration、selection_input_validation、hk_input_validation、hk_candidate_authority、slot_execution、tick_planning、node_entry、runtime_arguments，以及新模块 hk_current_day_research。

runner / node 配置透传研究 root；所有 HK 重读、现有结果幂等核验、采集前准入、采集后与发布前检查使用同一研究 binding。研究路径关闭旧的 Futu 成员/活跃快照预采集和 Stage8 RT_DATA 回放分支，真实报价由同批 collector 修复复用原 PyTDX ExHQ 链。

A 股研究与新闻 context 根缺失记入不可用证据。候选汇总输入的原严格验证保持；具体 source witness 仍由原 reader 验证，只有补充 context 消费边界可以隔离错误并保留原因。

## 文件身份与应用

`before/` 与 `after/` 属于 actual Stage 候选；`before_canonical/` 与 `after_canonical/` 属于 canonical 条件候选。它们保持不同 runner/helper 的接口和原有差异。

`SOURCE_MAP.json` 逐文件记录来源、before/after SHA、字节数。`runtime.actual_stage.r1_to_r2.patch` 与 `runtime.canonical.r1_to_r2.patch` 均已经正向应用、逐字节比对后像、反向还原并比对前像。

本组件增量以前次 **0fc3 候选后像**为前像。Mac 已恢复到更早 before 的文件需要使用整个 R2 交付的合并补丁，或先按照 R1 匹配补丁恢复候选再应用此增量。不要在 dirty canonical 上整文件覆盖，不要把可用历史切片称为本机当前 SHA。

## 实际测试与限制

`tests/test_hk_current_day_research.py` 有 29 个独立测试用例，包括四输入 SHA、695 完整集合、时间边界、metadata 改写、显式无效 root 不回退、配置入口、原始 HK 四路算法与原 Store、A/HK lane 隔离。

HK 集成用真实生产形状 runner、原四路函数和原 Raw/SelectionStore；输入文件及报价为合成数据。695 个输入、684 个有效报价仍选出 10 只；采集后更改 FINAL_RECEIPT 字节则 HK 不发布 raw / selection。A/HK 集成以原 `CandidateInput` dataclass 为已验证边界的显式局部 mock，216 输入、205 或 206 报价，原 A 算法得到 10 只；HK 15:38 的资料不能用于 13:15，HK provider 不执行、无 HK raw 指针。该 A 测试没有冒称验证 Mac 未提供的候选 current 链。

归档原件存在一处测试组合缺口：`raw_store.py` 无条件向 `receipt_identity._validate_rows_body` 传新参数，而所附 helper 不接收该参数。`evidence/raw_store_archive_signature_without_adapter.stdout` 保留直接失败。为继续检查本次接线，`tests/raw_store_test_support.py` 仅在测试进程中接受精确的 `allow_temporal_false_observation=False` 并代理原严格函数；True 和其他值立即拒绝。该兼容层不进入任何 `after/`、不修改业务 Store、不放松时间验证。

因此测试结论是“源码候选及指定测试组合通过”，不是 Mac 现役完整源组合或 API/UI 实际验收。需要一次取得本机当前 `stage_center/raw_store.py` 和 `stage_center/_raw_store_parts/receipt_identity.py` 的内容与 SHA，才能去除这层明确标记的测试兼容层。其他历史条件前像仍按总包的当前文件核对清单处理。

## 精简落地原则

1. 在独立 canary 应用根核对本次总包的完整源身份，再应用匹配的合并补丁；保留 actual / API / canonical 三根差异。
2. 配置 `hk_current_day_research_root` 指向用户已有 15:38 资料目录，raw/selection/receipt 写入独立 canary 根；保留真实输入四文件字节。运行 20261009 的 `STAGE_1545_1555` 时使用实际当前时钟，不传伪造的 15:55 evaluated-at。
3. 独立复跑同一条链：研究 binding → 原 PyTDX Stage 分钟 → 原四路 → 原三件套 → immutable receipt；验证全部文件 SHA 与同一 date/stage/market/run。A 在前面阶段独立验证完整 216，不受 HK 输入限制。
4. 通过现有发布链应用完整候选，再由现有 API/Vue 对同一个 run 做读回。源文件快照只证明指定时点磁盘文件身份，不当作进程实际加载源码的证明。

自动流程与自然时段验收仍是后续独立项目；研究结果不得因缺自然证明而隐藏。
