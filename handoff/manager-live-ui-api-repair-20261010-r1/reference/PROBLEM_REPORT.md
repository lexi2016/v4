# 现役三通道工作台问题报告

## 目标和边界

目标日期是 2026-10-09；公告 publication 日期是 2026-10-08。页面回看、独立 API 读取和修正后隔离运行发生在 2026-10-10，均为事后回看或人工 retrospective。包内没有自然时段成功证据，也没有修复后的运行。

该包的问题来自部署候选 stage_r4_manager_r2_owner_input_r1_fused_r1（PID 10321，manifest fd7f21af0205b9d25a8ab5d33592aff42bf76c0419799b7c1724b94a286aeb86）的真实 HTTP/API 与浏览器读回，以及独立 review。不要把另一个 run、隔离 candidate 或旧 2026-09-30 运行混作同一事实。

## 已复现的用户可见问题

### P1 — 同一计划在刷新读回后变成 stale

部署后 owner 刷新 receipt 记录 POST + GET + GET。三个响应均为 HTTP 200；两次 GET 与 POST 返回同一计划 run 3bc75d1beea24036850b1af0f4d5f395、产品 SHA 38eaad4b3d8adfd4738fa0bb4e6ef5ab969414447450e485614f384f48aab991、目标/选股日期 20261009、公告日期 20261008，状态 CURRENT / consumed=true。

后续独立浏览器读取的请求为：

    GET /api/v4/manager/research/workspace?date=20261009&view=dynamic

它仍读取同一 run 和产品 SHA，却返回 STALE_INPUTS_CHANGED、consumed=false。保存与当前 input_identity 不同（saved 4b7da917cb344f71fcf336e397a9f31122a45b78bd30f5a3a2b1a4494dd0727e，current e0f5ed6853fd464903104bf226af96ea595aacca35f1f3f7b45c8bd843165c5f）；日期绑定、semantic version 和 research cutoff 相同。独立 GET 前后的 saved plan 文件 SHA 相同，说明读取没有改写 saved plan。15,037,791 字节的响应体没有保存。

已证：运行身份/产品相同、input identity 改变、后一次读取拒绝消费该计划。独立后端复核还确认一个 P2 identity-coupling contributor：plan 的 1,970 个 source refs 都把整个 registry manifest SHA 写入语义 identity；在固定 1,970 个 material 的其他字段后，只替换这个全局 SHA，candidate build_workspace 的 projection identity 即变化。复核同时比对 40 对 payload/receipt：当前 bytes 与原保存 SHA 相同，且当前 manifest entries 仍匹配。这说明全局 registry 指纹可使未变的已消费材料一起失效，给出了真实可复现的宽泛失效机制；但不证明它就是这次 live GET 的唯一原因。旧 manifest 原始 bytes 未留存，live GET body SHA 未保存，且存在其他 identity extensions，因此 live mismatch 的具体 changed field 仍 CANNOT_CONFIRM。保留 fail-closed identity guard；不要绕过、缓存旧状态或伪造 CURRENT。代码检查点包括 code/current_fused_app/infrastructure/research_lane_source.py:93-112、v4/manager_research/existing_materials.py:23-65、workspace_projection.py:492-495 和 workspace.py:881-896、1036；对应 source hashes 和 counterfactual receipt 在 evidence/root_cause_*。

### P2 — 页面没有可见的每日三路结果摘要

真实页面检查记录 three_channel_summary_visible=false。独立前端审查已确认原因：固定候选中 dailyChannels.ts:190-229 定义 renderer，managerWorkspace.ts 接收并校验 daily_channels；但 catalystObservationPanel.ts 的 render(value) 没有传入 value.daily_channels，也没有 import/call renderDailyChannels，候选 JS bundle 亦无该标题。它是 renderer wiring omission，不是 v-if 或 stale-plan gate。独立审查用合成三路输入调用 helper 后看到标题和三张卡；这只证明 helper 自身能渲染，不能证明页面已接线或真实 API 内容正确。

- ANNOUNCEMENT：CANNOT_CONFIRM，gap ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED，目标 20261009 / publication 20261008；
- HK_CONNECT：CANNOT_CONFIRM，目标日 membership 未核实，目标 authority 缺少可验证 V2 artifact；
- OVERSOLD：PARTIAL，693 行待核，screen gap 695。

页面确实显示公告、研究注意力、HK 资格及超跌详情，但没有一眼可见的三路状态、日期、run/source identity 和 pending/gap 总览。现有 workspace response contract 已包含经日期绑定校验的 daily_channels；缺陷在该字段没有从 panel render(value) 传给现有 renderer。本包只将缺失摘要列为视觉缺陷，不推断 API 完全没有三路状态。该候选源码虽有构建 bundle SHA，E1 没有记录 browser-loaded bundle SHA，二者完全一致仍为 CANNOT_CONFIRM。

### P2 — 美股关系状态容易被读成矛盾

同一真实视图的上方 business-status 行显示“美股：尚未评估”；它读取 research_attention.us_mapping_diagnostics（或 legacy us_market_attention.mapping_diagnostics）的 assessment_state / accepted relation count。下方每日映射卡读取 us_mapping_research.daily_run，显示 VALID_EMPTY、4 个已审阅关系、0 条匹配。独立审查确认这两处是不同评估范围，并非同一输入的状态矛盾。由于上方标签较宽泛，页面应相邻写清“美股评估/完整度”与“每日 US-HK 已审映射（4 项）”的 scope，避免将局部结果理解为全市场无匹配或完整 US 输入。

另一条修正根绑定的 2026-10-10 isolated owner run 记录：其 2026-10-09 external_finance owner payload 为 READY，但没有 market_snapshot，该隔离计划的 US market 输入仍 CANNOT_CONFIRM。这是隔离 run 的来源缺口，不覆盖部署 API 的 daily mapping VALID_EMPTY 结果。

### P2 — 页面把 100 条原始观察放在核心结果之前

真实视觉检查记录 100 条 raw observation rows 出现在核心研究结果 section 前面。独立源码审查确认 catalystObservationPanel.ts:151-165 将 researchAttentionSection 放在 stocks/background sections 后；实际截图也记录 100 行 raw observations 先出现。把可读性问题解决为顺序和默认折叠状态：先显示计划消费状态、ANNOUNCEMENT/HK_CONNECT/OVERSOLD 结果和待核原因，再保留完整 raw observations 于可展开审计区。不能删除或截断 producer/选股输入来改善布局；页面展示截断不改变实际消费集合。

## 后端实际数据边界

修正了 source-root mapping 的 isolated review 明确推翻了“目标 2026-10-08 HK02 panel 缺失”的先前诊断：正确 V3.5 shared runtime 下 exact-date panel 存在，manifest SHA a9c75b248d264e2ed78532cbfc1004f8de97b8e8f91c587a66b50f5afa020bee，panel SHA 785212e96f9f088075800f55dfaf09ef83fccdde7c220e24f9f14d8808db5f90。目标 2026-10-08 security-master index 没有 exact-date entry，daily supplement pointer 和该日 universe directory 也缺失。不要把 panel 缺失作为当前已证根因，也不能用现在的 Futu capture 回填 PIT 日期。

十月九日超跌 screen 会看六个 session（20261002、05、06、07、08、09）。修正 owner review 记录 693 行历史未完成；成交量单位/scale NOT_PROVEN，provider finality NOT_ATTESTED_BY_PROVIDER。这是现有读取/来源合同无法证实完整六日量纲及 finality 的缺口；不能只写“没有抓到行情”，也不能附加未经权威源证明的单位字段。

公告链亦须分日期对待：有证据的 target 20261008 / publication 20261007 owner 产品有 613 个 Reader 行、613 个 Reviewer disposition（身份不同）、33 selected，且 owner import receipt VERIFIED。target 20261009 / publication 20261008 的解析导入仍 NOT_RUN。请复用包内 capture、prepare、Reader/Reviewer handoff、register-handoff、import、readback 的原 owner 入口；Chat 没有 Mac owner 环境，不可伪造或宣称补跑。

用户此前报告 2026-09-30 曾有独立公告/美股映射/超跌单日成功。本次限定材料未找到该独立入口/receipt，仍为 CANNOT_CONFIRM，不能以当前材料断言用户报告不存在；旧 09:53 workspace plan 不是该独立 receipt。

## 要求 Chat 交付

1. 沿固定部署源码和本包真实 receipt 检查 stale identity 变化，解释为何紧邻 POST + GET + GET 是 CURRENT、后续同 run GET 却 stale。独立 counterfactual 已证明全局 manifest SHA 是 P2 过宽耦合 contributor，但不是唯一 live root cause；请将 identity 改为实际 consumed artifact binding（source/date/path、manifest entry/payload SHA、receipt SHA）及 semantic available_at/content，保留全局 manifest SHA 作为 provenance。增加定向回归：仅未消费的 manifest entry 改变时 identity 不变；被消费 payload/receipt 或 semantic available_at 改变时 identity 改变或校验失败；保持 guard fail-closed 并保留可定位差异。真实 live changed field 继续标 CANNOT_CONFIRM，除非新证据闭环。
2. 在现有 manager 页面显眼位置接入每日三路结果摘要，绑定同一 workspace 响应与计划日期；显示每路状态、数据日、run/product identity、候选/待核、gap 与 CANNOT_CONFIRM，不创建第二 producer。
3. 并列解释 US relation assessment 与 daily mapping 的范围，显式保留“4 个已审关系”的 scope；不要将 VALID_EMPTY 升为全市场空结果或完整 US 输入。
4. 调整 raw observation 与核心结果的视觉顺序，完整原始 rows 可展开保留。
5. 给出最小源码 diff、围绕确切状态转移/页面渲染的回归测试、执行命令与实际结果，并列出每处 source SHA。若未在有真实 owner 环境的 Mac 上执行，写 PROPOSAL_ONLY / LIVE_API_UI_NOT_RUN；不要声称修复完成。

## 验收条件

- 同 run/product/date + 不变的 plan-relevant inputs 的重复 readback 语义一致；若输入身份确实变化，页面/receipt 应指出变化的、有来源依据的 component，而不是隐藏 stale；
- 计划日期和公告 publication 日期明确；页面可见三路真实状态、run/provenance 和 pending/gap，并与 API response/date bindings 一致；
- 4-relation VALID_EMPTY 清楚标注局部已审范围；不等于 US market full coverage；
- 原始观察仍完整可查看，首屏优先显示研究结果与 incomplete/gap 状态；
- research only: RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。

本包不授权回填市场数据、联网采集、访问运行中的 8873、改 Mac state、重启服务、改日程、改 BUY/production gate 或发布修复。

## CANNOT_CONFIRM

- identity 变化是否由全局 manifest SHA 这一 contributor 唯一造成（旧 manifest bytes、live GET body SHA 与其他 identity extension 不足）；
- browser 实际加载的 ManagerSelection bundle SHA 是否等于候选构建 bundle SHA；
- 用户报告的 2026-09-30 独立成功 run receipt；
- 2026-10-09/2026-10-08 announcement 最新完整 Reader/Reviewer/import 产物；
- HK Connect target-date V2 membership authority；
- 精确 2026-10-08 security-master capture，以及六日 volume unit/scale 和 provider finality；
- full-market US mapping coverage；
- 当前部署后的修复行为、UI/API readback 和自然时段结果。
