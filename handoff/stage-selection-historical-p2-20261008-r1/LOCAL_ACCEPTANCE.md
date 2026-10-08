# 本机适配、验收与回滚边界

本增量仅包含 Issue #28 第 7 节中两项历史 P2 的源码候选：历史来源日期上界，以及收盘复盘缺来源时的现有 PIT 不确定原因。它基于已经交付的 R1 commit `d8485e92bed685a1dc38a1f40a05858b9be4765c`，不能单独当作完整应用或可执行发布计划。

## 1. Writer 先核实际 owner 和前像

按原工单安排，Luna Max 是本机唯一 Writer，之后由不同身份 Reviewer 复验。以下是待执行的本机适配步骤，本轮没有操作 Mac。

原工单的 canonical 来源根说明是 `v4_app working tree at HEAD 55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054 with pre-existing changes`。冻结切片位于 `00524e9050fe212f87911b56eea1c2db719dd94b/handoff/stage-selection-issues-20261008/source/canonical`。commit 名称不能替代文件前像 SHA，也不能证明当前 API、scheduler 或 Stage 正在加载这些字节。

| canonical 相对路径 | 要求匹配的冻结前像 SHA-256 | 本增量后像 SHA-256 |
|---|---|---|
| `infrastructure/preselection_pool_store.py` | `028298a05ea44e310487c1159acc8147cf652e23ba716989135b178198795a92` | `9f1606a977d36c063d9c650e54b9861947eb7b692e779837852e3831b7814bef` |
| `ops/build_close_review.py` | `a361ae023285392ddf3b0e9674a9c506fae79252cc02c15df221ae09ba28e5aa` | `59ac7798bcb1d54bbd11bbc61803997f36881a29cd1b82ecb663166791d5e0f2` |

先记录当前 owner 的完整路径、入口、解释器、依赖根、实际文件 SHA 与工作区未提交改动。只有前像完全匹配的隔离副本才可直接应用相应 patch；如已漂移，按最小 diff 在该 owner 的原版本上适配并重新记录前后 SHA，不能整文件覆盖其他人的修改。也不能用本包 `support` 中的历史依赖替换当前运行依赖。

## 2. 先做隔离的真实依赖验收

用本机候选自己的解释器和依赖，复跑本包的聚焦测试，再在该 owner 的隔离数据根作一个完整调用验证。Linux 的合成测试结果不替代这一步。

- 历史池：分别令 eligibility 日期和 price 日期晚于目标日，保持其他 SHA、run、嵌套日期绑定正确，确认物化和读取都拒绝。可接受日期等于目标日；合法分日期和没有可选 `target_date` 的旧合同继续有效。
- 迟采样历史恢复：原先明确允许读取的历史恢复继续保持原 capture time 和不确定状态。读取成功不能充当 Stage 或 PIT 验收；Stage 原来的晚采样拒绝不放宽。
- 收盘复盘：分别缺来源 manifest SHA、receipt SHA、两者都缺以及真正无模型池时，输出包含一次 `HK_MODEL_SOURCE_PIT_AVAILABILITY_CANNOT_CONFIRM`。原模型行、KPI、status 和安全标记保持原计算合同。
- 来源 SHA 两字段完整且无历史 provenance 的普通池，和前像输出逐字段比较。该兼容性对照不代表仅凭两个 SHA 就证明完整 PIT 安全。
- 本地池 artifact/receipt/manifest 损坏应保留异常，不得变成可以发布的空池。确认原来源三件套和旧复盘在只读验收前后字节一致。
- 如测试显式构建新的合成复盘，仍按原 `ReviewStore.publish_native` 的 expected-SHA/CAS 规则运行。读取旧复盘与显式重建是不同操作；不要把重建命令当作只读检查。

本轮只发布了新的源码交接，不授权对真实历史日期执行重建、回填、强制物化或改写已封存输出。原8/25缺来源、9/30晚采样、10/7缺原始来源继续保留 `CANNOT_CONFIRM`。

## 3. 嵌套未知字段 P2 的具体缺件

该项仍未修复；原探针在 before 和 after 都实际失败。缺件是以下两个嵌套版本对象的完整生产合同及原始输出字段清单：

- `v4.hk_eligibility_asof.v1`
- `v4.hk_history_price_recovery.v1`

定点读取的冻结 recovery test 仍引用 `/Users/lexi/Desktop/学习/agents调试/v4_hk_history_r5_acceptance_20261002` 下的 `api_integration/ACTIVE_BINDINGS.json`、原始 source day archive 以及 `local_fix/roots/shared_package`。应由本机 Writer 从这些原位置确认对应 producer/schema 的精确路径、SHA、必填与可选字段，以及脱敏的合法字段结构；必要字节按原仓库授权范围交接。不要上传原始行情、完整配置、账号或凭证。

现有 consumer 能证明一些可选字段存在，却不足以给出完整白名单。`source_input_sha256` 的任意字符串来源标签是数据键，不能与版本对象的 schema 键混为一谈。完整原合同到位后，再补未知 scalar/map/list 键分别拒绝、合法可选字段保留及开放 digest map 标签的定向测试。

## 4. 与 R1 和部署验收衔接

本增量不取代 R1 的港股 producer、A 竞价、A 池读取和发布恢复补丁。R1 的源码独立复审结果继续作为先前证据，旧 R2 发布失败回执也继续保留；没有新的活动发布计划或 Mac canary 回执。

本机需要分别核对候选来源身份、实际 owner 集成、发布计划及恢复边界，之后再验 API、重载页面和自然时段。每项独立记录 `PASS / FAIL / NOT_RUN / CANNOT_CONFIRM`；不把选择结果、人工补跑或标称 NATURAL 当成自然执行证据。实际活动 release 只有在原工单要求的独立验收完成后才能进入相应授权的发布流程。

继续保持 V4/8873 唯一研究入口、A/HK 分离、A 全量有效汇总池的现有准入规则，以及 `RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。经理台 R3、Vibe8910 和模型/BUY 逻辑属于原有边界。

## 5. 回滚

本轮未部署，因此不存在需要本轮回滚的活动服务。若本机在隔离候选中适配失败，只在仍匹配本次后像 SHA 的该副本上反向应用 patch，验证恢复到记录的前像 SHA；若已经发生其他修改，先比较差异并保留他人字节，不强制覆盖。

回滚仅针对候选源码。不得删除、改写或“修正”历史 artifact、receipt、manifest、旧失败回执或原始 capture time。活动服务的回滚应使用该次已独立验收、精确绑定的发布/恢复计划，本包不提供执行活动服务切换的命令。
