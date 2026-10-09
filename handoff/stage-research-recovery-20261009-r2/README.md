# V4 Stage 当前研究恢复 R2

**本包在 `0fc3e8304e11700230517616ded0c86f83a4b257` 候选上交付新增代码及可直接运行的隔离落地工具。最终候选通过 148 项 Stage/工具测试、82 项 API 测试、45 项 Vue 测试，以及一次独立生成的 695 只合成输入全链往返。现役 Mac 集成、真实行情执行、发布和现场 API/UI 验收尚未执行。**

本轮职责：Chat 完成代码和回归；Mac 执行既有需求、落地、测试、验收流程。API 拆分、r5c 或两个 Mac 会话协调均不是此包的前置项。

## 交付入口

| 交付 | 内容 |
|---|---|
| [MAC_APPLY.md](MAC_APPLY.md) | 隔离 canary → 独立复跑 → 既有发布链 → 同一 run 的 API/UI 读回命令。 |
| [SOURCE_MAP.json](SOURCE_MAP.json) | 21 个交付文件的前像、R1 候选 SHA、后像 SHA、来源及条件应用边界。 |
| [patches/](patches/) | Stage/API/UI 分组的 before→after 最小补丁及 R1→R2 增量。 |
| [after/](after/) / [before/](before/) | 完整后像与对应完整前像。只有改动文件，不能单独当作完整应用启动。 |
| [MISSING_PREIMAGES.md](MISSING_PREIMAGES.md) | 一次性前像清单；历史参考与用户已提供的 actual 切片明确区分。 |
| [EVIDENCE.md](EVIDENCE.md) / [evidence/final/RESULTS.json](evidence/final/RESULTS.json) | 本轮真实测试环境、命令、结果、失败记录及未执行项。 |
| [CURRENT_DAY_RESEARCH_PIN.json](CURRENT_DAY_RESEARCH_PIN.json) | 固定用户给定的四文件 SHA 与研究标签；不包含、也不替代那 695 行真实数据。 |

21 个交付文件分为 Stage 16、API 2、Vue/类型 3；其中 3 个保留 R1 必要修复，18 个相对 R1 新增或更新。没有重构模块、另建 producer 或改动原选择公式。

## HK：显式研究输入已经接通原分钟行情与原四路算法

新增可选配置 `hk_current_day_research_root`。未配置时沿用正式 D1/STRICT 默认合同；配置后，研究文件使用 `HK_CURRENT_DAY_RESEARCH` binding，不再要求其冒充 `HK_CONNECT_D1_TOP100`。外部传入一个 research marker 不能替代配置授权。

研究 binding 逐字节核对 pin 和四份输入、日期、代码全集及资料字段；采集前、复用原始行情时和写出前重新核对输入。该路径不写正式 HK D1 `latest.json`。

资料标签固定为：`CURRENT_DAY_RESEARCH_ONLY`、`universe_as_of=20261008`、`captured_at=2026-10-09T15:38:41+08:00`、`stale_universe=true`、`hk_connect_membership_status=CANNOT_CONFIRM`、`formal_d1_eligible=false`、`formal_pit=false`。文件 SHA 证明指定字节被使用，不是历史资格、PIT 或供应商真实性认证。

证券资料只接受用户列出的九种字段。价格继续调用既有 `collect_pytdx_exhq_minute`；每只股票验证原 19 字段行情合同、日期、窗口、末根时间和有效 bar 数。15:38 证券资料不是价格，也不会被当成 09:35 行情。缺报价、错日期或越窗只形成对应股票的缺口。

研究路由仍调用原 `select_hk_four_lane`，沿用原评分、权重、排序和 Top10。研究行没有确认的 Connect 成员资格，保持 `formal_eligible=false` / `NO_BUY`；结果可以有行并同时带研究来源限制。

这一入口支持六个原分钟阶段：`STAGE_0930_0935`、`STAGE_0935_0940`、`STAGE_0940_0945`、`STAGE_0945_1030`、`STAGE_1300_1315`、`STAGE_1445_1500`。0925 竞价及 1545–1555 RTDATA 是其他原采集合同；本批仅有证券资料，不能据此生成这两条专用行情。因此不会伪造这两个阶段的 HK 成功，相关缺口也不阻断 A 或其他阶段。

## A 股：补的是字段断点，已有选中结果继续保留

用户提供的 10/9 记录已经说明前五阶段各选中 10 只。本包不把它们描述为“算法完全没运行”。

可取得的 0925 registry 在 `SourceResult`→builder 的映射中漏了 `prev_close_price`，R2 补一行透传；源 HQ probe 同时拒绝把布尔值 `True/False` 当作 `1/0` 昨收。R1 的 `qmt.lastClose` 和 nullable 涨幅输出修复一并保留。

52 项同股链路回归覆盖原外部桥接、SourceResult、builder、qmt 和最终行：有效昨收贯通，未知涨幅保留 `null` 和原因，真实零涨幅保留 `0`。216 只完整输入不会按 UI 200 行截断；205/206 只行情仍可产生 Top10，10/11 只缺口逐股解释，测试包含第 200 行之后入选的股票。

## 来源证明、结果、回执与页面

`slot_execution` 的最终 A 输入漂移、某市场 source witness 错误、某市场 builder 异常均按市场隔离。已经有效写出的另一市场结果保留在最终 owner receipt 中，不能因后续异常整体消失。

owner 写入以下互相核对的证据：输入 binding、selection CSV/manifest/receipt 三件套字节 SHA、不可变 owner history、日期/阶段/市场/run/算法/原始行情 SHA，以及当次加载模块的路径和文件 SHA。模块文件观察明确 `memory_execution_attested=false`，不声称这是内存执行证明。

API reader/consumer 经原 SelectionStore 独立验证后，把“选中了多少”“行情覆盖多少”“研究来源限制”“执行证据”分别投影。缺自然证明不再把已有研究行隐藏为未运行。Vue 原 App 和执行证据面板显示相同结果；冲突日期、阶段、市场、run、SHA 不得互相借用。

现有 API 仅传 selection 根的构造方式也已补齐：精确的 `<root>/selection/backfill/<id>` 只映射同根、同 id 的 `<root>/receipts/backfill/<id>`，不扫描或回退到别的运行。最后一次全链测试使用原 owner 历史 tick 和这个无显式 receipt 参数的 API 构造入口。

`MANUAL_REPLAY`、`CURRENT_DAY_RESEARCH_REPLAY`、`HISTORICAL_BACKFILL`、`LATE_CATCHUP_REPLAY` 均不能显示为 NATURAL；真正 NOT_DUE 的手动 owner 回执同样保留触发来源。手动补验不升级自然验收。

## 尚不能从已有材料判定的现场问题

10/9 15:50 和 15:55 两次异常处在临时改动窗口，未记录加载模块 SHA，不能归因到原六个文件。实际 `SOURCE_ARCHIVE_PROJECTION_SHA_MISMATCH` 对应的 archive/witness 未提供，原来源校验继续保留。本包提供只读 `diagnose_source_witness.py`，直接调用原 builder/validator，输出原错误、文件 SHA 和字段级差异；不编造修复后的 witness。HK 研究已可独立产出，不再因该 A 侧错误整体中断。

14 个新增依赖/consumer/UI 前像只有固定仓库中的历史参考；其余 7 个有用户给出的 actual 源码切片。所有当前 Mac 文件仍必须逐项命中已接受 SHA。`prepare_canary.py` 一次性列出不匹配，绝不在 dirty canonical 上整文件覆盖或模糊打补丁。具体清单见 [MISSING_PREIMAGES.md](MISSING_PREIMAGES.md)。

默认金融标志始终为 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。本包源码通过不等于现役已恢复；现场完成标准仍是同一真实输入、阶段行情、原算法、同一 run API/UI 读回。
