# 经理公告／美股映射：最终代码修复与一次业务验收方案

## 结论与唯一入口

本目录是一个合并后的业务候选，不再要求 Work 叠加多个旧修复包。唯一执行说明：`WORK_ONCE.md`。普通 Chat 完成代码；Work 负责同一新隔离候选的风险定向独立审核、原构建器产物身份和获授权后的现场验收。此交付不是合并、安装或启调度授权。

本批新增 7 个既有运行文件的修复；另将原 B1/US 的两改一增原字节并入 `after/app/`。累计补丁共 9 改、1 增。API6726 的 workspace、autorun、资格过滤器等 9 个未受影响 pin 保留；未重跑 API14、B1/US33、R3B10 或 F0–F2。

**状态更新：23350050f185f4cdaea0da6f5f248114810a476d 的 F0–F2 独立回执是 PASS。旧“独立待”不再使用。** 它证明 inactive built candidate 的源码／构建／隔离行为，不证明真实资格发布、部署或经理 API/UI。ab9ba67099fbe5683ebf8fbfa20ce3196ccb89e0 为 `PLAN_ONLY`，不是 R3A 已实施证据。

## 用户可见问题 → 根因 → 本次代码 → 验收

| 用户可见问题 | 已核根因与改动 | 代码／验收 |
|---|---|---|
| 公告始终查前三家、后批正文使前批消失 | 复用 2849459 的原 owner 有界续扫、同日 committed run 合并、issuer/art_code/body 去重及原 MaterialStore observation 见证，不重新研发 | `workspace_announcements.py`、`eastmoney_run_history.py`；旧 B1 20 项复用，新 RPC 两批输入测试调用原采集和存储代码 |
| 盘前同轮新公告没进入计划 | bdc95a3 的 cycle 在 `plan_target` 有值时 RPC 后提前 return，导致下方原公告采集未执行；现在符合原采集政策时先执行一次原采集，再按完成后的真实时钟调用原 RPC；采集不应运行时仍原 RPC-only 路径 | `ops/run_manager_announcement_cycle.py`；同轮 collect→plan、两批新输入、关闭采集、失败批次保留前批 |
| 原计划 RPC 地址无接收者 | bdc95a3 的 `plan_owner_dispatch` 请求 `/workspace/scheduled-cycle`，但同一冻结 router 未注册该 POST；本次注册原地址，沿原注入 service 和原 binding/state/master/full-reader 检查，无新端口、无窄 service 回退 | `manager_research_router.py`；ASGI 请求实际经过 router/RPC/Store；错误 SHA、跨源、请求体和缺 full readers 均拒绝 |
| 排队或重复调用可能消费旧时钟／旧输入 | 服务端在 coordinator 实际执行时重新取钟；写请求不借用同 key 的旧 in-flight 响应，原 Store 事务按真实 input_identity 保持幂等；不改 workspace 的既有生成合同 | `plan_owner_dispatch.py`；重复 input 不改 run/产物字节；过 09:30 不生成计划；执行中跨截止失败也保留已保存计划字节，失败 attempt 正常记录 |
| 手动原公告 POST 后计划没有刷新 | 在同一原公告提交后，若服务器已有有效 plan binding，调用同一原计划 owner；未绑定返回 NOT_BOUND，计划失败以独立 `plan_refresh` 返回，不擦除已提交公告 | 同一 router 与 dispatch helper；无绑定不自动启用，GET 路由不采集、不新增写入 |
| US 关系原件有字段，消费者却报缺取得时钟 | `_zsxq_rows` 固定构造丢失文章级可选时间／引用；原 lane 的 `raw_items.raw_payload` 可保留，archive 又固定投影且严格 schema 不接收额外文章字段。本次在原链传递源内已有字段，并以输入 SHA＋raw_id 的可选 `manager_source_evidence` 封装进入原 archive 合同，再在消费者读取 | `collect_hourly_research_input.py`→原 `research_hourly`→`domains/research.py`→`contracts/research.py`→`existing_materials.py`；原 archive 磁盘发布／读回、篡改拒绝、冲突原件不借字段、名单排名与旧 Stage 投影不变 |

## 原始事实和时间边界

只传递原 topic 中实际存在的 `retrieved_at`、`available_at`、`related_us_symbols/us_symbols/us_symbol`、`source_refs`、`business_relation_validity`。没有从 crawl_time、first_seen、status.fetched_at、程序执行时间、archive 发布时刻生成这些字段。非法值保留给原消费者拒绝；缺值仍缺值。历史存档不回写，不以新处理时间倒造旧采集。

原文回连要求原 raw_id 一致、明确股票代码、source_type/name/path/url/title 完整一致、原正文含原 evidence_sentence；歧义或冲突不拼接字段。可选封装绑定的是原输入 SHA，而不是让 archive 自身 SHA 自引用。原 source_refs 仍是源声明，不能替换已独立验证的 archive 来源绑定，更不能让传入的 claim_type/verification 提权。

当前报导中的明确 ticker＋本股关系动作可以形成 **归因报导的研究关联**，不等同独立事实或 BUY。普通研究 archive 仍为 RESEARCH_OPINION／REPORTED_CLAIM，不能凭透传一个长期合同升级成 SOURCE_STATEMENT。没有 `礼来→LLY` 别名表；没有真实原文 ticker/关系/时钟的 09969→LLY 继续拒绝。行业标签不代替本股业务命题。原 US exact-session、两源 PIT、资格和 cutoff 校验未放宽。

早盘窗口依然由原 autorun／日历决定：默认 preopen 09:27–09:30，早晨 SCHEDULED_MORNING 分支、既有冻结规则和 evening next-session 规则不变。重试不扩大时窗、不替换历史日期、不生成收盘后伪盘前计划。

## 源码基线与唯一候选组合

1. 以已验 API6726（6726a3dc…）作为完整 app 依赖底座。workspace=35c9292d…、autorun=e785ae1d…、connect_selection=b6c53001…保持原字节。
2. 本目录 `runtime.patch`／`after/app/` 已包含 B1/US＋新 RPC／US 字段修复。**不应用旧 cycle_snapshot.patch，不再叠 53d5558 的旧 runner。** `SOURCE_PINS.json` 给出每条完整 before/after SHA、Git blob、来源及新旧改动分类。
3. 原 API6726 与其已叠 B1/US 的组合均有明确整体 profile；工具必须匹配整个 profile，不按文件任选新旧 SHA。已有不同字节不覆盖，集中输出一次 gap report；原 API 缺少已上传的 RPC/源处理入口时，可将本包固定字节放入新 inactive 副本，并明确记录安装绑定未证实。不会因此改活动服务。
4. bdc95a3 的 cycle/dispatch/router 是上传的真实冻结源码；router 同时与 ab9ba670 计划的 d66b0a41…一致。原 `_zsxq_rows` 使用已上传 8851f7f…快照（bdc 目录没有该路径），其 source applicability 只在目标字节核对后用于安装。`domains/research.py` 的 bdc 与8851 Git blob一致。其余前像原SHA均记录，不能把作者参考依赖当 Mac 完整运行闭包。
5. **R3A 不在本补丁写集合中。** Work 按已批准原 owner 的5文件职责继续；当前业务候选不得再覆盖 Work 的最终 R3A reader/capture。R3A新源码正式冻结后，在同一个候选组登记它的独立差异／来源身份，按受影响交互验收，不重做未变全量测试。无法取得的最终实物不伪造、不用旧 canonical 代替。

## 一次最小现场输入清单（已有 GitHub 原件不再索取）

- **B2 最终绑定**：`ops/run_manager_announcement_cycle.py`、`v4/manager_research/plan_owner_dispatch.py`、`apps/api/v35_api/manager_research_router.py` 的最终 SHA256、worker/API 根目录用途。与本包/已上传前像相同只给映射；不同只给对应最终字节。六项配置：enabled、plan_material_refresh_only、announcement_collection_enabled、preopen_plan、morning_plan、plan_material_refresh。仅脱敏值，原始 plist/凭证不上传。binding文件身份及服务器/worker根的合法一致性用原验证器现场确认，不放宽。
- **真实两批公告**：原 committed product/run_id/SHA、相应成功/失败 journal、issuer/art_code/body身份、原 MaterialStore listing/content/pdf 引用与真实 retrieved/available 时钟。原有已上传文件直接引用，不重传历史整库；若 observation 索引已丢且无见证，不补造。
- **真实关系文章**：一份原 topic/raw_items/raw_payload→archive 的固定引用（路径/ID及SHA）、正文、本股明确身份、原 published/retrieved/available 字段及其来源证据；有则附原 ticker 和长期合同，没有则明确缺失。仅有 crawl/status时间不算文章级取得证明；无事实不用伪正例验收。
- **R3A/F1 实物**：复用 23350050 独立PASS及 dcd72a0 的64条 source-output 映射，55条已有交接继续复用；只交与 bdc95a3 不同／缺失的9条最终F1字节及对应path/SHA。文件名以原映射实际条目为准，不猜定路径；已新上传则引用固定commit。Work正在写的R3A5文件按自己的最终回执引用，本轮Chat不双写。

旧 release 历史来源缺证据仅保留其历史边界，不阻断本次隔离研发。上述缺项只限制对应安装／真实业务验收，不以等待17:20阻挡公告/映射代码完成。

## Work 一次执行与放行顺序

执行 `WORK_ONCE.md` 唯一命令，得到一个新的 app、副本差异清单、27项新增测试日志/JUnit、导入路径SHA和WORK_RECEIPT。Work只做定向独立审核及原构建器的 source→output 身份，不承担宽泛研发。允许源缺件只在固定快照范围种入inactive副本；任何不同字节先给一次集中差异，不盲覆盖。

取得同一候选的必要实际绑定后，真实业务验证依次：原资格 reader 接受目标日期且 acquired/available 都不晚于服务端 cutoff → 两批公告正文在原输入/原工作台共存、去重和拒因一致 → 原 US exact-session payload/manifest/receipt 有效 → 逐股原文关系及真实时钟校验 → 原 API GET/POST 和原页面核对。0候选应有逐项拒因，raw US movers 保留；0不自动等于故障或恢复。

真实 POST／provider／安装／启调度须沿已授权本机流程单独放行。本包只执行离线测试。17:20面板／600行canary成功不能替代资格产物、公告选股或US映射成功；诊断/API200也不能替代上述业务证据。

## 分层状态与终态口径

本轮 IMPLEMENTED=冻结源码上的业务候选；TESTED=27项新增风险场景作者通过；BEHAVIOR_VERIFIED=合成上游下的原Store/原计划/RPC路由/归档消费行为。当前新候选 REVIEWED/DEPLOYED/API_VERIFIED/UI_VERIFIED/NATURAL_VERIFIED 均 CANNOT_CONFIRM，未执行，不能借旧回执扩范围。

F0–F2 独立PASS、API14、原B1/US33、R3B10分别按原范围复用。PR9继续Draft、Issue8继续Open。本轮“最终”表示收敛的一次代码/方案交付，不表示未经真实验收的经理业务已恢复。
