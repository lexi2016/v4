# V4 经理研究页：当前进度、页面缺口与源码交接

核对日期：2026-10-01，北京时间。现场检查约 21:39–21:42。这是问题与源码交接，不是修复完成报告。

## 当前结论

8873 页面可以加载，API 可以返回数据，但上游材料、港股权威成员表、日线完整性与冻结计划仍有缺口。页面“READY”表示评估程序执行过，不代表已经生成有效关注卡。公告、美股行情和映射关系是三个不同验收面，不能把其中一个成功当成全部完成。

用户本轮决定：先彻底梳理并提交 GitHub，由指定 Chat 负责方案和代码；本地主控负责之后落地、独立测试和反馈。本轮已停止 BI01/BI02 Writer，Writer 确认没有写入、没有运行修复测试。本包新增内容仅在 research 下，未修改仓库业务源码、运行服务或门禁。

## 本轮检查的页面和数据

- 页面：`http://127.0.0.1:8873/manager-selection/?date=20260925&plan_date=20261002`，自动视图。两个日期分别是阶段参考日期和计划目标日期，不能混同。
- API：`GET /api/v4/manager/research/workspace?date=20261002&view=auto`。
- 页面截图：[manager-current.jpg](evidence/manager-current.jpg)，页面文字：[manager-current.txt](evidence/manager-current.txt)。
- API 关键字段：[api-summary.json](evidence/api-summary.json)。完整响应约 17.7 MB，仅留本地，投影内记录完整响应 SHA；未上传历史研报正文和原始档案。
- 配置的发布身份、接口健康回执：[runtime_identity.json](evidence/runtime_identity.json)。配置身份不能独自证明每个进程已导入的文件。
- 独立只读代码审计：[current_audit.md](evidence/current_audit.md)，含精确文件行号、身份差异与调用链。本轮未做修复测试，因此不是独立修复验收。

## 为什么页面仍然没有达到预期

| 现场问题 | 当前证据 | 还缺什么 / 下一交付面 |
| --- | --- | --- |
| HKEX 公告覆盖不完整 | `PARTIAL`；查询 15/696，681 未查询；10 个文档，7 BODY_PARSED、3 FAILED | 权威查询范围、失败文档、完整覆盖/明确覆盖缺口回执。不能把 PARTIAL 当成全市场已扫描无事件 |
| 东方财富当前材料窗口为空 | 当前 `NOT_RUN`、0 文档；历史材料日期为 20260929，2 条被判在窗口外 | 当前窗口采集状态和历史材料状态应分别说明。历史存在不等于当前可消费；也不能说此前从未成功 |
| 美股有行情但没有 HK 有效映射 | `PARTIAL`；33/33 标的可用、24 代理；6 个正向行业、9 个正向个股；`mapping_eligible=true`；`source_material_card_count=0`、`FULL_VERIFIED_MATERIAL_CARDS_REQUIRED`；accepted=0 | 先恢复可追溯、截止时间内的合格材料卡，再验收结构化关系与 Python→TS 合同。不能把零结果只归因于行情 PARTIAL |
| 旧材料被读到，但没有合格关注卡 | 2016 条材料先投影出 16 个发行人的 67 张候选卡；67 张全部因 `TARGET_HK_CONNECT_MEMBERSHIP_UNVERIFIED` 被过滤；关系层收到 0；另有 1995 个材料缺获取时间 | 当前直接断点是目标日成员表缺失。恢复权威输入后仍要核真实性、主体、获取时间和关系证据；不补造历史时钟、不降低门槛 |
| 目标日 HK Connect 权威成员表缺失 | `HK_CONNECT_TARGET_AUTHORITY_UNVERIFIED:HK_UNIVERSE_V2_ARTIFACT_MISSING`；期望 `universes/20261002/HK_CONNECT_FULL_MARKET.json`；membership=CANNOT_CONFIRM | 由权威源 owner 交正式成员表与来源 SHA；不能将价格有效的 689 行冒充 696 行证券主表 |
| 反弹观察的日线/成交量不完整 | 689 个待核；典型要求 60 个完整日线但只有 59，前 5 个交易日只有 4 | 补采失败地址、时间范围、证券/价格分离及回读完整性。UI 已准确暴露前置条件缺口，不应靠改标签产生候选 |
| 冻结计划已经陈旧 | `STALE_INPUTS_CHANGED`、`MANUAL_REFRESH`；旧计划未消费，最新输入已变化 | 确认输入权威性后重建计划，再核 manifest→consumer→页面绑定；本轮未触发刷新 |
| 其他计划前置条件未物化 | close recapture `NOT_RUN/CLOSE_RECAPTURE_NOT_MATERIALIZED`；目标阶段 `NOT_DUE/SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID` | 分别处理实际缺输入和目标时段未到。不能由这个未来目标页推断 A 股所有历史阶段都未修好 |

页面巡检期间没有观察到浏览器 console error/warn；本轮零材料场景不能证明 BI01/BI02 正例合同已通过。

## 已做 / 未闭环

| 交付面 | 可确认进度 | 未闭环边界 |
| --- | --- | --- |
| 公告抓取 | 现役能返回部分 HKEX 文档和正文状态 | 覆盖不足、3 文档失败、当前 Eastmoney 未运行；不算全链验收 |
| US 行情与 D-1 投影候选 | 旧 Writer handoff 报 33/33、24 代理、696 D-1；有候选 release | 尚未部署验收；manifest 的 overlay base_release_id 错误自引用；不得原地改冻结候选 |
| 候选测试 | 旧 handoff 有 Writer 9 passed；另有 43 passed/3 failed 报告 | 两个旧 PARTIAL fixtures 和一个 relation_origin 基线问题未闭环；本轮未复跑，不升级为 TESTED/REVIEWED |
| BI01 公告实例 ID | 当前配置发布源码仍只按 source+art_code 生成 ID；TS 对重复 ID 报错；PR18 是 draft 证据包 | 源码缺陷仍在；当前 Eastmoney 0 条没有触发正例，不能把 PR18 当本机已修复 |
| BI02 跨端映射合同 | 当前配置源码仍有 why_now 固定标签冲突、native relation 缺 semantic_status、standing/mirror 短时间窗不匹配 | 源码合同不一致仍在；当前空关系没有触发正例，尚无真实本轮补丁或 Python→TS 实跑；不得假设新枚举 |
| BI04 历史 morning reader | 当前 reader 仅接受 MANUAL_REFRESH/SCHEDULED_PREOPEN，不接受 SCHEDULED_MORNING | 静态 reader 缺口确认；实际 writer-reader 组合和自然触发仍 CANNOT_CONFIRM |
| A 股阶段 | 另一负责会话已有 closeout receipt：三天 21 个适用阶段恢复 API/UI | 此处引用 owner 回执，未重复测试；仍不代表完整源/自然时段验收 |
| HK 阶段 | 另一负责会话已区分 D-1 日期错位、1445 报价失败、缺 D-1、成员表与价格表混用 | HK 修复候选未激活；本次不重开其源码修改 |

旧交接：[user_handoff_20261001.md](context/user_handoff_20261001.md)。旧 US Writer 回执：[us_mapping_writer_handoff.json](context/us_mapping_writer_handoff.json)。阶段 owner 回执：[stage_closeout_and_hk_diagnosis.md](context/stage_closeout_and_hk_diagnosis.md)。它们是各自层级证据，不互相替代。

## 源码身份和目录

- 当前本地 HEAD：`55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`；分支 `codex/system-consolidation-20260912`。工作区大量已有 tracked/untracked 改动，不能视为干净 HEAD 或任意覆盖。
- 配置的 release：`r4-stage-merged-c3e5357d07f068e79296790e0b968934c34541d579c586282c5e83f56f6a3875`。
- `source/` 是当前 canonical 源码快照，保留原路径；不是从旧 GitHub main 推断出来的代码。
- `configured_release_reference/` 保存 4 个与 canonical 不同的已配置发布文件，仅供差异核对。
- [SOURCE_INDEX.json](SOURCE_INDEX.json) 逐文件记录 SHA256、大小、与配置版本是否相同；[MANIFEST.json](MANIFEST.json) 绑定本包文件内容。
- `context/BUSINESS_REVIEW.md` 是 GitHub 固定审计版本；`context/PR18.json` 保留 PR 状态/身份摘要。

本包是聚焦的源码/证据交接，不是完整可安装工程或测试依赖包。测试结果必须在真实本地环境运行后给 stdout 和命令回执；缺文件时点名所需文件，不能伪造补齐。

## 给代码负责 Chat 的任务边界

1. 先读真实 schema、源文件 SHA、现役差异与 current_audit；将数据前置条件、代码 bug、部署/候选状态分别列出。
2. 第一批只处理 BI01/BI02，并核实 BI04 是否确实存在。提出一个明确的唯一 Writer、allowed paths、failing reproduction、PASS_SIGNAL 的最小批次；不要把采集失败和日历改动夹进合同修复。
3. BI01 验收必须是多 issuer/多 source/同文档真实 Python 输出进入实际 TS parser，再验证 DOM 多实例 ID；重复同实例要稳定去重，不能误合并不同 issuer/正文。
4. BI02 验收必须使用真实 native 与 standing/mirror 正例，Python→TS 输出能够被现有 validator 接受，按真实字段表达材料时间和关系时间；同时保留过期/不足双来源/PIT 的负例门禁。
5. 数据与候选集成另列后续批次：合格材料 feed、HK 成员表、日线补采、候选 manifest 与 fixtures、计划消费；明确各项 owner 和下一证据，不以增加零值或放宽门槛“修好”页面。
6. 交回真实 patch 或分支/commit、变更文件和 before/after SHA、测试命令与 stdout；未执行标 NOT_RUN。本地负责应用补丁、Luna Max 独立复跑、API/UI 验收及反馈。

日历议题暂不修改；若需要讨论，先核 refresh_announcements→return path→GET announcements→product/project builder→plan_context→announcement_autorun 实际复用边界，区分材料日期、计划交易日和 consumer cutoff。

严格保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。不改 BUY、A 股阶段、Vibe 8910、调度、服务、冻结 release 或第二 producer；不降低日期/来源/成员/PIT/双来源门槛。本包提交不会关闭 Issue8/17，不表示 IMPLEMENTED/TESTED/REVIEWED/DEPLOYED/NATURAL_VERIFIED。
