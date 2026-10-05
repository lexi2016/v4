# V4 现役源码只读核查 · 2026-10-05

结论：现役源码已收到并分层核验。最明确的剩余工程缺口是研究归档 producer 与经理 US consumer 的取得时钟合同不衔接；不能将旧字段改名补齐。经理 GET、计划保存、历史读取各自有明确职责，旧计划 STALE_INPUTS_CHANGED 不等于更新失效。Stage R3 修复仍在现役，但自然选股是否完成缺新运行原件。此次没有证明新的现场故障，也没有修代码。

## 收件和审查边界

- Library：libfile_f070e9e1382881919549a6af1285aae7；文件 v4-running-source-20261005-sanitized.zip。
- 本地原包：`/workspace/attachments/b524da86-ba54-4ff8-906c-5b8bff2880fc/v4-running-source-20261005-sanitized.zip`。
- 6,676,343 bytes；SHA256 `c7f89eec30a9b44eb974078d2db0a0f42fc79480734cd7ca5fdf863b7de9f1b0`；1464 ZIP条目；CRC全部通过。
- 解包根：`/workspace/current-source-input/extracted`。下文包内证据均相对其 `handoff/v4-running-source-20261005/`。
- 1417 去重源码路径，3075 分层引用；所有分片SHA、源码SHA256、大小、Git blob SHA1与还原字节均核对，0差异。清单及差异索引见同目录 PACKAGE_VERIFICATION.json。
- 还原目录：`/workspace/review-20261005/{canonical,api,stage}`；分别1354、881、840文件。只执行文件校验/复制，没有导入业务模块、安装依赖、运行测试、采集器、API或调度。
- AGENTS追加规则SHA为 `fd790799d7ae8913088eb716ebe29da51c21e57681966240691542978e2d84c0`，与包内收据一致。本轮明确指令仅提出GitHub同步方案，故未执行上传。

## 身份、分层和并行工作

包内 RUNTIME_IDENTITY.json 的观察时刻为2026-10-05 00:00:02 UTC；本轮没有访问Mac复测。

| 层 | 身份与核查结果 |
|---|---|
| canonical | Mac `v4_app`，HEAD `55a5ba0`，含未提交研发改动；不能仅凭HEAD重建 |
| API/经理 | `manager-selection-r10-20261004-business-r1`，记录PID72627 running；入口 `apps.api.v35_api.run` |
| Stage | `issue23_runner_helper_r3/stage_r1_binding_candidate_r3`；已注册，记录not running、runs=9；这是进程快照，不是9次选股成功 |
| GitHub | main仍`615d1ce`；本次远端查询未见`*20261005*`分支。旧`8851f7f`只能复用相同blob，不能当现役 |

API与canonical共同路径有137处字节不同，API另有10条独有路径；Stage对应120处不同、11条独有路径。不同不等于缺陷，禁止整树覆盖。

已交叉核对：API/canonical workspace.py均为`c6c97c9…`；store.py均为#24后像`79e077d2…`；Stage runner.py与canonical均为R3后像`2dbfa90c…`，API副本runner为`317159a9…`，不能用API副本诊断Stage实际执行。announcement_source.py在API/canonical均为`4e5a0304…`，workspace_announcements.py却分别为`6bcd3409…`和`7d27e1e5…`。

evidence/PUBLIC_LEDGER_SUMMARY.json：经理R10 writer/reviewer已completed；9/30 Top20/公告单日writer与限定review也已completed，但有较早interrupted记录、一个材料任务receipt_verified=false。evidence/REMAINING.json明确HK day25仍有writer且缺当前生命周期终态。因此不能声称全项目无并行任务，也不另派重复实现。

## 当前问题与最小下一步

下列源码路径相对各还原层；行号以该层为准。现有Mac回执与本轮静态确认分开列示。

| 优先级与分类 | 源码/证据、影响 | 复现输入与下一步 |
|---|---|---|
| 1：已确认合同缺口，US取得时钟 | API `domains/research.py:261,286–323` 的build_research_archive只构造published_at/collected_at/first_seen_at，不输出available_at/retrieved_at；collected_at及first_seen_at允许fallback到event_time。`ops/run_hourly_research.py:384`调用该builder；`existing_materials.py:44–60`要求原件显式取得双时钟，`workspace_discovery.py:301–304`原样透传，`issuer_us_relations.py:125–138`明确拒绝缺失及错序；因此不是这段投影漏传。旧真实84条缺时钟及owner代表样本见Issue8评论5968799736，最新R10回执仍保留缺口。 | producer/consumer机制已静态确定；未执行重现。需原owner输入的一条article/source timeline及获取回执、实际producer绑定，分清真实采集时刻与event_time回退；再设计前向合同。包没有实际archive，不足以逐条归因84条，不能重封历史或别名填时钟。 |
| 1：US市场时段/主体关系数据缺口 | API `us_market_bridge.py:165–192,250–278`要求精确US session和输入资格；`issuer_us_relations.py:197–214`还要求主体绑定正文关系。包内LATEST_DIAGNOSTIC_FINAL_FIELDS只报告9/30固定Top20的0 accepted、issuer relations absent，不是全市场零关系。 | 需要同日期US原快照、session、capture/manifest/receipt及发行人原文；无这些输入不能判断是供应缺失、采集晚于cutoff还是合法零结果。与上行取得时钟问题分别处理。 |
| 2：单日公告已修待部署，勿重写 | canonical `workspace_announcements.py:533`已有targeted HKEX采集、`:1029–1173`已有单日投影及targeted scope reader；API版本没有这些新增路径。包内phase2记录57项独立测试与限定事后产物PASS，但DEPLOYED=false、API_VERIFIED=not8873。 | 复用原writer补丁与独立回执；后续仅在用户决定后核采用范围及运行验收。本轮不部署、不再实现。 |
| 2：公告自动分类与人工判断差距，原因未证实 | 包内LATEST_DIAGNOSTIC_FINAL_FIELDS：固定20只中8正文/6发行人，人工3个possible-positive；自动0 positive、800 pending（797 claims+3文档解析缺口）。API/canonical `announcement_source.py:768–822`同一保守主体/动作分类器；`:784`逗号分段、`:793–809`主体/否定/不确定性规则。 | 需要8正文的具体拒绝命题、原页偏移与人工判据逐条对照。不能据人工“可能正向”断言分类器错，更不能从固定样本外推全市场。包内未含这些原正文，不足以重现具体漏判。 |
| 2：Stage主链运行证据不足，非新证实代码bug | Stage `ops/run_stage_center_nodes.py:342`→`ops/_run_stage_center_nodes_parts/node_entry.py:270`→stage_dispatch→runner/tick→slot_execution。`runner.py:570–628`精确交易日/D1或前Connect观察绑定；`:956–986`R3 wrapper兼容仍在；`slot_execution.py:565–636`先raw，再`:647–695`selection发布。10/3旧独立回执仅周末安全跳过/只读绑定；新包runs=9没有每次date/slot/终态。 | 先由原day25 owner给最新终态及指定日期PREP→attempt→raw→selection原SHA/回执，再对API/UI读回；本包未带这些运行存储，不能把注册成功、空闲或旧20-cell失败当当前选股成败。 |
| 3：计划更新职责需核运行配置，暂无新故障证明 | API router`:169–210`区分GET与POST刷新；workspace.py`:383–400`dynamic重投影/历史reader分流，`:679–712`只读比较保存身份并返回STALE_INPUTS_CHANGED，`:716–849`单独保存且验证读回成功后才写成功回执。前端catalystObservationPanel.ts`:467–472,527`明确回看/草案/冻结边界。自动计划workspace_plan_autorun.py`:16–19`preopen默认enabled=true、`:127`morning默认false，实际生效值可被配置覆盖。 | 需要用户具体期望的date/view、原owner attempt及实际调度配置；脱敏API例子未包含当前自动计划开关，不能断言自动更新已开或已坏。不要POST重写旧run来消除stale提示。 |
| 3：已证实性能负担，未新增测量 | API workspace.py`:620–622`仍deepcopy US diagnostics，`:702–703`覆盖动态证据；旧真实profile表明announcement_review占333MB计划92.41%，R10历史GET约338.5MB/32.38秒。store.py`:24,116–153`仍用320MiB限定计划路径读写；它修读回而不缩小对象。 | 读既有字段profile/序列化路径后另定优化范围；本轮无333MB回放。不能仅凭338.5MB GET断言新计划必然超过预算（两者结构不同）。 |
| 3：已知类型检查失败 | API `apps/web/src/views/ManagerSelectionView.spec.ts:4,6`仍有@ts-expect-error；R10验收记录两处TS2578。 | 当前字节存在，但未重跑typecheck；复用旧失败身份，获准后定向核工具链与注释必要性，非业务恢复阻断证明。 |

## 旧失败与正确保留的未知

- #22成功原因文案：API businessStatus.ts:37已有正确成功映射；不重复修。
- #24读回：API store.py仍为已验后像；workspace.py:822–838保留保存后读回检查。旧READBACK_FAILED不能替代最新STALE_INPUTS_CHANGED。
- R10已有689条可解释回看决策，58 SELECTED/349 NEAR_WATCH/250 EXCLUDED/32 UNRESOLVED；来自10/4固定API/UI回执，不是本轮新测，不是正式BUY或自然时段。
- #21深链接/页面补丁由R10回执确认保留；旧Issue21“尚未落地”评论不能盖过更新的固定验收。
- Stage R2 wrapper失败由R3覆盖；Stage目录里有旧经理store.py不表示8873退回旧reader，8873用API层。
- 公告旧背景：API workspace_announcements.py:1069–1073显式NOT_PARSED、PUBLICATION_IN_WINDOW_NOT_EVENT_OCCURRENCE、WATCH_ONLY；现役分类器与先前核查字节一致。不预判bug。若要让观察专指“本次新事实”，需先确认新业务合同和当前页面是否有误导性断言。
- 包内事后Top20抓取与R10的20261002回看不是同一验收；14只无文档是unknown，目录分页仍PARTIAL。不能把8正文、3人工可能正向、0自动正向混成“自动利好选股已恢复”。

## GitHub同步可行性与拟议范围（未执行）

只读仓库元数据返回lexi2016/v4为private、当前connector权限push=true/admin=true；git ls-remote可读。此前gh API曾Forbidden，这不等于connector无权限，也不证明shell push可用。本轮未做试写、空分支、blob/tree/commit创建或push。

建议用户确认后：以当前main `615d1ce`为历史父节点创建唯一新交接分支（例如`codex/v4-running-source-20261005`，先复查不存在），仅添加本包清单授权的1464条路径；源码仍放handoff三层位置，不写入根运行源码路径。根AGENTS仅是包内已批准同步段。main只作为Git父节点，不作为运行源码来源。

优先一次普通git提交/push（若已有通道可用）；若只能connector，先用MANIFEST中的git_blob_sha1与既有tree对照复用对象，只上传新增blob，再分小批构造tree及最终commit。不要重传ZIP/base64大包，不重试已知超时的大create_tree请求，不改公开性、不forcepush、不合并。已有未引用小tree不是成功同步；应由最终commit可达性判定。

验收必须读回新branch commit、tree及清单所有文件的blob/mode，并读回关键文件SHA256；若开PR保持Draft。本文报告可在明确纳入范围后另加一个小文件，不把下载辅助脚本/本地还原副本重复上传。当前同步状态：NOT_RUN，方案已给出。

## 证据入口与限制

- 包内：README_ZH.md、RUNTIME_IDENTITY.json、MANIFEST.json、AGENTS_CHANGE_RECEIPT.json、evidence/PUBLIC_LEDGER_SUMMARY.json、evidence/LATEST_DIAGNOSTIC_FINAL_FIELDS.json、evidence/REMAINING.json。
- 最新GitHub Issue8/21/23/24评论已重新只读查询，仍与前轮固定交付一致。
- R10：https://github.com/lexi2016/v4/blob/815aac0e4f6751a8917e912eec339f1d56cab3ef/research/manager-selection-gaps-20261003/mac-business-r10/FINAL_ACCEPTANCE.json
- Stage R3：https://github.com/lexi2016/v4/tree/64802ceabbb13ce3cf77d32735e4ec24bed1108f/research/hk-stage-issue23-r3-deployed-20261003
- US原owner单条：https://github.com/lexi2016/v4/issues/8#issuecomment-5968799736
- #24 profile：https://github.com/lexi2016/v4/issues/24#issuecomment-5967029030

本轮结论为静态源码及既有证据核查。新业务测试、完整调用链执行、Mac实读、API/UI、自然运行、部署均NOT_RUN；没有业务代码改动，没有GitHub写入。下一轮先确定要核实的运行输入/业务合同，不从这份清单自行启动修复。
