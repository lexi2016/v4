# V4 经理工作台 R1 · Mac 接续交接

交接日期：2026-10-08。现役身份最后只读核对：18:56:12 北京时间（10:56:12 UTC）。

## 先读结论

**修复候选已集成并通过限定范围独立验收，但未成功上线。两次 API 切换均因发布检查失败而自动回退，当前运行原 R3。不要把候选、测试通过或 release 目录存在当成已部署。**

用户现要求交接文档。本次交接不继续切换、启用调度或补采。后继优先解决发布检查的哈希来源/序列化一致性，不能未经定位再次在线试错。不得重新开始业务修复全流程。

源码唯一入口：`/Users/lexi/Desktop/学习/v4_app`；本批未改 canonical。
全部隔离工作：`/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_R1_MAC_20261008`（下称 TASK）。该目录不是 Git 仓库。

## 目标、角色和边界

原目标：接续 Chat R1 交付，在 Mac 核对现役身份、集成修复、完整构建、受控发布、公告同产品 API/三路页面核验、自动运行分层验收，并反馈 GitHub。

输入固定提交：
- R1 修复：`66339d576431285cfaa7e62ca58de31e7548a931`。
- 原 US 映射源码补充：`281f2f39d0f096fa370e9765604dc634f1e9af6e`。
- 原问题包：`0fd5eb374cb155232ed003d5fc4d0d3594252491`。

唯一 Writer：`manager_r1_mac_writer`；独立 Reviewer：`manager_r1_mac_review`，均 Luna Max。后继依照现行 AGENTS 继续唯一 Writer / 独立 Reviewer，不由主控改业务代码。

保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。Stage Center 和 Vibe8910 不在切换范围；原 06:30 公告 heartbeat 仍为原采集/真实 reader/reviewer 的 owner，不建第二 producer。正式计划绑定仍禁用。

## 当前真正运行的版本

| 项目 | 最后核对结果 |
| --- | --- |
| API label | `com.lexi.v35.api-only` |
| API PID | `23876`，running；PID 只是观察值 |
| API release | `manager-daily-chain-20261008-r3-api` |
| API app | `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-daily-chain-20261008-r3-api/app` |
| API manifest SHA | `946c49b9c34bd09fbca04644556de3acba1635eb240fa9293f6391e9d46b40e9` |
| API plist SHA | `72050bf4c7f00c8271cf9226ea866683a8e9e459d2875547b08f69fad30bfdf5` |
| scheduler plist SHA | `c478c87e7866fa50154df674ea7cb570197251aaa5da3014b3666e7f22914da2` |
| Stage plist SHA | `9c7199ca1fcfedc09397255c932d25c6edc15779952bbd5b5bec2671e883d3f5` |
| 原禁用 binding SHA | `f3b7cbfa1709b2b27816d294e599cb1ae82ff918ba41ec148644f1a1751f5fd6`，前次回执核对，交接时未重读 |

原 scheduler 根：`/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/hk-research-calendar-all-r1-20261007-scheduler/app`。原 scheduler PID 1310 为此前观察，不冒充交接时重新核实。

实际启动身份、磁盘 manifest 与 HTTP 可分别核对；没有进程内 Python 源码指纹，仍 `CANNOT_CONFIRM`，不要注入进程或新增追踪接口。

## 已完成，后继直接复用证据

1. 输入包 68 个文件完整性核对；以实际 API/scheduler 树隔离集成，保留原依赖、symlink、mode 和数据根。
2. 必要后端测试原独立验收 123 项、前端 29 项、限定和完整 TypeScript 检查、完整构建通过。Mac Writer 最终后端 124 项、前端 29 项通过。
3. 独立验收发现并修复两个 P2：港股通状态受无关 US gaps 污染；公告日期切换未重新加载官方 review。增量独立复跑后端 13 项、UI 1 项通过。
4. 新 API release 已创建，1016 条 inventory 与候选一致；静态构建 11 文件匹配。未成功保留为现役。
5. 发布辅助工具原 18 项独立测试通过；第一次修正发布检查后 20 项独立测试通过。**这些测试未阻止下面两次真实发布失败，不能作为线上通过证据。**

关键回执（均 TASK 相对路径）：

| 回执 | SHA-256 |
| --- | --- |
| `writer_receipt.json` | `e5cdc5f5c6a248fcf2905ebd3ce832b15ffc93c0e06ca6f82bc13daea0fa1710` |
| `review/p2_delta_independent_review.json` | `0cf607eecc19a73d21eafef653b69ff9f9716c286198de05c272f47aa5d58084` |
| `phase2/writer_receipt.json` | `1c7d4ae6cc13d11bac842e831f95ccdb84aac525f331a101beb3b2a376f6d5f3`，对应旧 helper，已被增量取代 |
| `review/phase2_independent_review.json` | `51c7afe26aea6ef99ab0f9ef23461dd6df85ceca8233a3ac1e8ba8d9daf3833f` |
| `phase2/receipts/oracle_delta/r1_post_switch_oracle_delta_writer_receipt.json` | `3dc6fd522b3ed406876688d792e78b609735a9bb1d5b3b953387b2832f1a10fe` |
| `review/oracle_delta_independent_review.json` | `41dc6daf63895d44ad1424319db96deac8e12ab833ae3ad04dc33f7bf2f50185` |

旧补充测试失败仍保留：前端全套 176 通过/3 失败；supervisor 19 通过/4 失败；修改面板 runtime 全文件 18 通过/1 个既有缺 fixture 失败。详见原回执，不扩大为本次发布阻断点，也不宣称全套全绿。

## 冻结候选和当前发布文件

- API：`TASK/candidate/api/app`。
- web：`TASK/candidate/web`；scheduler：`TASK/candidate/scheduler/app`。
- 已暂存 API：`/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-workbench-r1-mac-20261008-api/app`。
- API inventory：`0f2e6752b55430dd556d212739a9de4b2176acc92f95fc15b45ec342cb2b3771`。
- 新 release manifest：`d125d33b8c8a5cae6edead79cb756b671baf07a79ddc0653c2884800a7eafb49`。
- 新 staged plist：`TASK/phase2/drafts/com.lexi.v35.api-only.plist`，SHA `d3552150122b8f9c89d538e5ce4553ac49a73dd4a4342e2d4786d88ee373a357`。
- 当前 helper：`TASK/phase2/tools/api_only_cutover.py`，SHA `39bb4a929dcb0fa151df250635bdff02af15d765b381c3fd1f291e30e2765942`。
- 当前 helper 测试：`TASK/phase2/tests/test_api_only_cutover.py`，SHA `8835e4874f650992b79266e8648a8096e1254e17d5e0090fea80d45af0be6a8f`。
- 当前 runbook：`TASK/phase2/drafts/api_only_cutover_runbook.md`，SHA `7f0a79f278959b8976c622ad7eeed4cbcc664247a5e9590f7466f51bbbbdf529`。

运行解释器：`/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python`。
**当前 helper 仍有未解决的实际阻断，禁止照旧直接执行切换。**

## 两次发布失败与回退

第一次：2026-10-08 10:01 UTC 开始。

- 错误：`API_ONLY_RUNTIME_VERIFICATION_TIMEOUT:HISTORICAL_ANALYSIS_RESPONSE_SHA_MISMATCH:current_analysis`。
- 回执：`TASK/phase2/receipts/api_only_switch_runs/20261008T100114Z-941bbf76/operation_receipt.json`。
- SHA：`1b2e12a890aa130cacfa49b22ac9f5470fb9af080c094ebefde4b60d96edbc80`。
- 结果：`ROLLED_BACK_TO_PREIMAGE`，恢复 R3 PID 21204，原公告产品读回匹配。
- 独立诊断：R1 仅增加顶层 `consumption_validation`，原产品内容未变。旧工具要求整个响应 SHA 与 R3 一致，误拦合法 schema 增量。
- 修正：仅在切换后校验中剔除这个已知新增顶层字段，原响应仍按基线校验；新增字段另验 schema、日期、状态、安全值、产品身份及固定 SHA。切换前/回退校验仍保留旧严格规则。

第二次：2026-10-08 10:32 UTC 开始。

- 错误：`API_ONLY_RUNTIME_VERIFICATION_TIMEOUT:HISTORICAL_ANALYSIS_CONSUMPTION_VALIDATION_SHA_MISMATCH:current_analysis`。
- 回执：`TASK/phase2/receipts/api_only_switch_runs/20261008T103231Z-48dac360/operation_receipt.json`。
- SHA：`0cb892aa56f9b991c0402e087cd1a43960e2ba00efdcfb21d2bd0ae94516492f`。
- 结果：`ROLLED_BACK_TO_PREIMAGE`，恢复 R3 PID 23876；原公告响应、scheduler/Stage 配置仍匹配。

两次失败 live R1 响应原文未被保留；不能声称已取得失败当次完整字段差异。失败回执不可删除。后继应补保留必要的 metadata-only 投影，避免只留下无法解释的 digest。

## 当前唯一优先阻断：投影哈希的计算来源

证据：

- `TASK/review/phase2_failure/failure_diagnosis.json`，SHA `7c0312a33ed9f9476e8edf8110b178d4361b460e1fbc9d656e5e7713e4e49166`。
- `TASK/review/oracle_runtime_failure/runtime_failure_diagnosis.json`，SHA `4cfe9b9a1ecd9722c07bcc86b25e43d48048a1fd4bb8c219eb02673016d6dfbf`。
- `TASK/review/oracle_runtime_failure/consumption_validation_comparison.json`，SHA `affd28396dc25fb2d2aceaf071bde6782f8977bb176c4f1ad9e5dd28d7276fa4`，已保留完整 metadata-only 投影。

相同候选在先前 TestClient 环境与实际 staged plist 环境下，8 次只读 GET 的投影稳定一致；未复现环境根或墙钟时间依赖。

| 对象 | helper 固定投影 SHA | 新诊断投影 SHA |
| --- | --- | --- |
| current | `796e437a76c1a40acf7ade7c1bac64be53c7aaa4cd21e387d3ca7e3e2c72aee9` | `f5c96caab104572949931351501fcb103743df16e1a97ed6650253905ac0f2a6` |
| legacy | `25ed3622660ce7602bb782257cf3b85d7346c1c7838e8fc1488b9dbf245ab726` | `be89ecb3f0029d3142ad8b70e24d30ec2e5ac71d7eb08183f0953d4b9d9525f3` |

**关键线索：两次诊断的完整 R1 响应 SHA 实际相同。** current 均为 `e6388eaea085347dd041b8372ee86fabd608be7c8676043327d3ed080ce8d748`；legacy 均为 `2ad27621c57772ef293833a46030e4ad064e1ddcc569837313e1e3dd10e87640`。因此优先对比哈希时 `json.dumps` 的 `sort_keys`、`ensure_ascii`、`separators`、末尾换行及 helper serializer；不能直接断言数据变化，也不能盲换常量。

交接最终补充：Reviewer 已停止并交回结果，没有生成 `hash_provenance.json`。已读到的旧探针使用 `json.dumps(value, ensure_ascii=False, separators=(",", ":"))`，不设置 `sort_keys`、无末尾换行；当前 helper 第127行的 serializer 会排序键。完整响应 SHA 相同支持响应未变。保留的投影文件已经按字母排序，无法恢复原始键顺序，因此“旧 pins 恰好等于原对象不排序序列化的 SHA”仍 `CANNOT_CONFIRM`。序列化方式不同是首要解释，而非已完全证明的修复结论。后继先核这一点，不重复环境/时间排查。所有子任务在交接时均已停止或完成。

当前产品：529 股票、613 article decisions，原产品 SHA `8b1e906db2cdcb8784d9658085aa4f1aa0711a8711b83a38c9ee8d7567151157`；新增 validation 为 `VERIFIED`。
旧产品：524 股票、580 article decisions，SHA `7b27fe7d40e9c12db3d56751cc789c6eb84515bb2392fc1b00a3bc4a5fd38278`；新增 validation 为 `NOT_CONSUMED_INVALID`，缺口 `ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_INVALID`。保留可读性，不升级为可消费。

## 后继最短接续顺序

1. 先读本交接及上述三份诊断，复用已有测试/构建回执；不重新审计全项目。
2. 只使用已经保存的投影对象和旧探针核对哈希算法。若证实序列化不一致，唯一 Writer 只修 helper/针对性测试和必要回执；不得改变业务判断或删除新增字段来过关。
3. 修复后独立 Reviewer 应在真实 staged 环境的只读响应上直接调用同一校验函数并通过，再允许第三次发布。光靠 mock 测试通过不够。未知字段/原内容变化/安全标志异常仍须拒绝。
4. 仅在有新证据和独立 PASS 后，按 runbook 即时预检、备份、精确前像比较、API-only 切换和失败回退。保留成功/失败新回执，不覆盖旧回执。
5. 实际核验公告 analysis/workspace 同产品、日期、身份、股票和理由；真实 Chrome 重载 `/manager-selection/?date=20261007&announcement_date=20261007&plan_date=20261008`，检查三路及日期切换/迟到响应。页面未验证之前不报 UI_VERIFIED。
6. API/UI 闭环后才接续暂停的 scheduler/binding exact-root historical canary；该 canary 与自然运行分别记录。不要把本交接当启用配置。
7. 最后同步必要源码/测试/精简证据到新私有分支并读回。自然时段必须等待真实合法时段，不回填。

## 暂停的 Phase 3

已创建非现役 scheduler release：`/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-workbench-r1-mac-20261008-scheduler`。Writer 报告635条 inventory=`f68d50e7f130057d81bd3a89d419d6a5dcc01673db13d5f4b672435561785458`，含原树已有生成 `.pyc`；独立发布验收未做。

`TASK/phase3/` 有 scheduler stage receipt、两份 disabled binding 草稿、API canary plist、scheduler plan-only plist/diff、`tools/run_plan_only_historical_canary.py`。这些是中间材料：未执行 canary、未跑测试、未启用；完整 runbook/Writer 最终 receipt 未完成。带 canary 占位依赖的草稿明确 NOT_LOADABLE，不得直接复制到现役。

## 其余真实缺口

- 成交量 owner：此前核对的 HK02 panel 最大日为 20261002；目标 10/7、10/8 manifest/pointer 缺失，单位 `NOT_PROVEN`。这是当时观察，不冒充持续更新检查。超跌数量门保持 `CANNOT_CONFIRM`，不自动采集/另建 producer。
- 原工作台未生成计划、未执行 review 和无效旧 judgment 必须如实保留；不重新导入只为页面变绿。
- 原公告 06:30 heartbeat 定义此前已核对，未修改；自然 capture→reader→reviewer→import→API/UI 未闭环。
- 发布工具独立复核另留 P2：嵌套重复 JSON key 按最后值解析；生产是否出现 `CANNOT_CONFIRM`。不将非阻断项扩大为当前全局审计。

## 分层状态与交付范围

| 层次 | 状态 |
| --- | --- |
| IMPLEMENTED / INTEGRATED | 隔离候选及非现役 release；canonical 未改 |
| TESTED / REVIEWED | 限定业务候选通过；发布检查测试通过但两次实际验收失败 |
| DEPLOYED | R1 未成功上线；原 R3 已恢复 |
| API_VERIFIED | R1 live 未通过；R3 恢复及既有产品已核对 |
| UI_VERIFIED / BEHAVIOR_VERIFIED | 候选限定行为通过；R1 实际重载页面未验收 |
| NATURAL_VERIFIED | CANNOT_CONFIRM / NATURAL_SLOT_UNVERIFIED |
| GitHub | 原输入 commit 已存在；本批 Mac 源码增量尚未同步，不能从 GitHub 完整复原本机候选。此次仅发布交接文档时必须明确该范围 |

过程教训：发布准备过重、串行等待过多；整份旧响应哈希拦住合法新字段，修正后投影哈希来源又未与真实校验函数闭环。后继聚焦同一对象、同一算法和一次真实只读校验；不要继续用重复状态汇报或扩大审计代替修复。
