# V4 经理调度、保存、API、普通页面与发布链审查

## 结论与证据边界

1. 已有不少重要防护，不应重写成另一套经理引擎：原 owner、精确日期、绑定 SHA、同 run 产品/attempt 回读、研究安全字段、盘前截止线、原子单文件写入、只读 GET 和非 delta 文件保留都应保留。
2. “有子进程”不等于“经理与阶段选股完全隔离”。R3 候选的调度器确实异步启动限时 worker，但计划工作经 loopback RPC 回到现有 API owner；共享 API 应用仍挂载阶段、预选和经理路由。共享进程的资源竞争是静态风险，尚无本轮现场测量证明它造成过某次超时。
3. GitHub 有多个不同时间、不同职责的后像，不能拼成一个未经证明的现役版本。尤其四功能问题包的 R2 router 已含 US owner 准备步骤，而树中 R3 router 没有；覆盖错版本会丢修复。
4. 本次仅静态读取 GitHub 固定源码并保存审查附件；未编码产品、未运行测试、未启动 Mac/浏览器、未部署或执行交易。没有当前全量 Mac 快照，不能证明现役进程、API、浏览器 bundle 与本文候选一致。下述验收是待执行规范，不是已通过结果。

主源码锚点 A = `8c8e35d9d53431c9082dec49f4976e363c275765`。原四功能包锚点 B = `74478a0e62be215c8527ccc9a14b89b51042d014`。

本文缩写只为阅读方便，完整路径、blob SHA、文件 SHA256、字节数、可打开的固定 GitHub 链接和本包快照位置见末尾及 `DELIVERY_SOURCE_MANIFEST.json`：

- R3 = A 下 `handoff/manager-daily-r3-repair-20261009/after/api_current/`
- UI10 = A 下 `handoff/manager-live-ui-api-repair-20261010-r1/after/`
- V9 = A 下 `handoff/manager-validator-restoration-20261009-r1/after/`
- OBS = A 下 `handoff/manager-daily-failure-20261009-r3/package/source_snapshot/`
- FOUR = B 下 `handoff/manager-four-functional-gaps-20261009/package/`

## KNOWN_CANDIDATES：不能把 A 视为唯一最新候选

下表对 A 已做本报告所列源码静态阅读；另两项只核对固定 commit 变更摘要和完整交付 README，未深读其全部后像或复跑测试。README 测试数字均为交付者报告，不是本轮验证。

| 固定候选 | 文件范围与声明 | 与 A 的关系、审查动作 |
|---|---|---|
| A `8c8e35d9d53431c9082dec49f4976e363c275765`，`handoff/manager-live-ui-api-repair-20261010-r1` | 7文件，语义身份helper、workspace/projection与4前端模块；声明离线后端35、前端22通过；LIVE_API_UI_NOT_RUN | 本文主静态锚点，不是现役，不是其他候选的当然基线。身份版本`CONSUMED_RESEARCH_ARTIFACTS_V1`；成功POST直接复用 |
| C `fa97ac802a19b05d4e18c121f8bac77f2f5fa311`，`handoff/manager-live-ui-api-repair-20261010-163151` | 8文件并行R1，比A范围多`research_attention.py`两行，覆盖attention-card digest；声明backend21、frontend23；完整工程测试/构建NOT_RUN | 基于同批fused前像/固定c0fc35c7恢复材料，并非证明继承A；新身份`v4.manager_research.input_identity.v2`；需比较重叠文件、legacy快捷复用保护，不能把不同helper/schema交叉替换。额外attention前像live字节未证明 |
| D `c8935da1217e6a3b43eeba2c3ce53d87ed4e27ee`，`handoff/manager-live-ui-api-repair-20261010-r2` | 9文件R2；额外修`archive_catalyst_inputs.py`已物化催化的第二处全局manifest耦合，冻结来源重放与PIT不放宽；新增56后端/44前端，旧76安全回归声明通过 | README明确保留A并行分支、没有合并/改写A，也不拿A取代自身固定基线。新身份`CONSUMED_ARTIFACTS_V1`；手动POST后canonical GET，与A直用POST有合同冲突。archive前像只有固定Git来源，Mac为CANNOT_CONFIRM |

D 的全后端报告为288 FAIL/1255 PASS/20 SKIP/33 ERROR；前端20 FAIL/372 PASS/1 SKIP并有4 load failures；全量类型检查和完整构建仍FAIL。Python测试3.12.14低于项目声明>=3.14。D还明确：非空催化卡测试是在reader输出边界的合成行，真实来源PIT与历史/auto provenance不变性未证明。不能用新增定向测试通过覆盖这些限制。

因此目前没有证据认定 C 或 D “整体取代” A。建议 Chat 对同一fused前像做三方逐文件/合同比较：选定一个身份schema及相应helper/workspace/projection/frontend诊断组合；评估C attention层与D frozen-catalyst层是否各有必须保留修复；裁决成功POST回读策略并补跨语言router DTO测试。所有合并仍须精确前像、完整工程和现役验收。不要机械依提交时间串行打补丁。

已核README：[C](https://github.com/lexi2016/v4/blob/fa97ac802a19b05d4e18c121f8bac77f2f5fa311/handoff/manager-live-ui-api-repair-20261010-163151/README.md)、[D](https://github.com/lexi2016/v4/blob/c8935da1217e6a3b43eeba2c3ce53d87ed4e27ee/handoff/manager-live-ui-api-repair-20261010-r2/README.md)。本包保留这两份原文快照与blob清单。

## 1. 实际链路与代码锚点

### 1.1 调度不是直接保存计划

- R3 `infrastructure/scheduling/manager_announcement_supervisor.py:560–587`，`AnnouncementSupervisor.tick`：scheduler 主线程只做轻量窗口/分钟判断，另开 daemon thread，不 join；`run_bound_child:532–557` 使用精确解释器、`-I`、固定 app、清理 PYTHONPATH/PYTHONHOME，并建立独立进程组。
- 同文件 `supervise_child:509–529`：默认 50 秒 wall budget，撤销/取消/超时只终止本次创建的进程组。不能把这当作终止 API 内所有工作的保证。
- R3 `v4/manager_research/plan_owner_dispatch.py:779–824`，`_request_bound_cycle`：固定 `127.0.0.1:8873`，向 scheduled-cycle 或 daily-cycle POST date + binding SHA；无代理、重定向、重试、备用 owner。普通 35 秒、daily 40 秒 transport budget。
- 同文件 `558–616`，admission 先校验 server binding、app、state/master roots、启用状态、真实时钟、分支、目标日。`618–663` 的 daily 分支先调用 US owner（受其预算控制），再通过 `_workspace_reads.run(... seconds=30)` 执行计划。`402–443` 执行前再次校验窗口，不让其他准备工作悄悄耗掉合法窗口。
- 同文件 `665–748`，`_execute_serialized_cycle`：同日 transaction 内读 dispatch 历史，恢复 RUNNING、复用成功/部分完成、限制重试与 backoff，写 started/completed 并读回。这里保存的是调度回执，业务计划仍归原 owner。

### 1.2 保存与读回

- R3 `workspace_plan_autorun.py:129–188`：从既有 Stage `STAGE_0930_0935` 合同推导 HK 开盘边界；交易日检查、盘前窗口和截止后禁止补造盘前。`owner_plan_readback:40–110` 要求同 run product + terminal attempt，校验 owner、input identity、时间、类型和状态。
- UI10 `workspace.py:1116–1248`，`refresh_workspace_plan`：校验 execution_kind、aware clock、deadline、日期绑定；按日 transaction；锁内再次检查幂等；先写 RUNNING attempt。
- UI10 `workspace.py` 精确写入顺序：1238–1247 构建 RUNNING 并将 run/latest attempt 写出；1251–1252 读取原 owner 投影；1262–1272 构建产品、写 product run/latest；1276–1279 回读产品；1283–1287 写 terminal attempt；1288–1293 回读 terminal 与消费状态；1303–1309 例外写 FAILED。四个研究安全字段在产品和 attempt 中继续保留。
- 时间/PIT要分两类：调度 admission/deadline 前置检查在1127–1139，幂等复用时 cutoff/generated_at 边界在1206–1216，产品发布前deadline在1260–1261、终态前1281–1282、最终返回前1300–1301；后续只读消费的生成/终态deadline复核在1004–1021，saved/current cutoff比较在1063–1073。这些时间门禁不是所有源PIT已闭环的证据。源合同由706–734的各原reader检查，812行投影Stage时序，924–931将同cutoff准入的US mapping纳入身份。本轮没有深读所有源reader，不能宣称全链PIT通过。
- UI10 `workspace.py:1004–1113`，`verified_plan_attempt` / `_readback_plan`：CURRENT 需要 owner run、终态、输入语义版本与精确日期绑定一致；不能仅看产品文件存在。输入陈旧、读回失败、owner attempt 未核实分别暴露。已保存计划深拷贝后覆盖实时 owner 状态，不重写历史 sealed bytes。
- 注意：单文件原子写并不等于 product/run/latest 四个文件的整体 ACID 事务。源码已通过同 run 校验避免“孤立产品”冒充成功，进一步优化应保留这种 fail-closed 行为。

### 1.3 API 和普通页面

- R3 `manager_research_router.py:206–244`：GET workspace 使用 `run_in_threadpool`；客户端断开只撤回订阅/设置 cooperative cancel，不保证原生阻塞调用立即停止；错误映射 499/503/504/409。
- R3 `service.py:394–415`：read coordinator 键包含 date、view、clock、selection/publication date 与 US context，避免把不同日期/口径请求合并。`465–482` 委托原 workspace owner。
- FOUR `code/r2_chat_patch_target/apps/api/v35_api/manager_research_router.py:246–380`：比树内 R3 router 更新的路径，手动 refresh 对到期目标先调 US mapping owner、按 exact run/artifact 回读；失败单列 diagnostics，不阻断独立通道；然后重取当前时钟生成计划、从 store 再读同 product。这项已存在修复必须保留。
- UI10 `workspace.py:481–534`：过去日期 auto 使用历史 reader；动态读重读原 owner，用已保存且完整日期绑定一致的 as-of context 减少纯墙钟漂移，仍做输入比较。不是缓存成功捷径。
- V9 `apps/web/src/api/managerWorkspace.ts:1491–1642`，`validateManagerWorkspace`：按工作台、股票、研究关系、schema、安全字段与日期合同进行客户端校验。`1644–1676` GET 用 no-store 与 AbortSignal，检查 view；`1701–1722` POST refresh。
- UI10 `catalystObservationPanel.ts:640–677`，`load`：sequence + AbortController + date/view 守卫；成功 POST 响应只消费一次，不再立即额外 GET；POST 失败只允许一次规范 GET，并清楚标明“生成失败后读取”。非完整源错误时只能保留标为旧的合格结果，合同失败清空旧结果。
- UI10 `dailyChannels.ts:95–138` 校验同 run/日期/owner；`190–235` 普通页面三路结果展示未知、部分、有效空、run、owner、SHA、生成时间和未验自然运行，不能用 0 自动替代未知。
- 冻结普通 `ManagerSelectionView.vue`（UI10 test_support/current，非发布后像）81 行导入 panel；其存在证明有可审查的组件 wiring 快照，不证明生产 bundle 使用该源码。

## 2. 阶段选股与经理的耦合，准确拆分

### 已证源码事实

OBS `issue32_protected/apps/api/v35_api/app.py` 的同一个 `create_app`：

- 4720–4728 挂载 preselection router；4730 起提供 `/api/v3/workbench/stage`。
- 5246–5267 注入 ManagerResearchJobService 与既有 research source、security master、US reader 等。
- 5268–5270 挂载经理研究/workbench 路由。
- 5272–5280 在同 app 挂载 `/preview` 和 `/` 普通 web dist。

因此是共享 API 应用与发布包；源码本身不证明部署了几个 ASGI worker，也不证明所有数据采集都在同一个 OS 进程。OBS `current_shared_scheduler/ops/run_v35_macos_scheduler_daemon.py:719–738` 创建公告 hook；R3 supervisor 又明确把触发器隔离为子进程。必须把“触发 worker 已隔离”与“计划 owner 回到共享 API”区分。

### 静态风险与改进方向（非现场根因结论）

1. 经理 GET/refresh/scheduled-cycle 都占用共享 API 线程与 owner 资源。建议先建立 manager 专用有界执行配额，保留单飞/取消/503 busy，给 stage/preselection GET 留保留容量，再根据负载证据决定是否独立进程。不要未经必要性证明重写/搬迁所有 owner。
2. 管理员刷新超时、取消浏览器或 worker 被杀，并不自动证明 API owner 停止。建议给保存动作加持久 `operation_id` 和只读 status/readback；HTTP 取消只影响等待，写入是否完成应按 owner 回执确认。
3. 同一个 app 发布牵动 stage/preselection 与 web。经理修复应以 active-base + precise delta 发布，禁止把经理 handoff 整目录覆盖完整 app。
4. 读取合同的模块依赖同样耦合。语义输入 identity 与可执行读取器 contract/version 应分开管理；不能删除所有 manifest/contract 校验来“解决”陈旧。

## 3. 必须保留的修复

- UI10 `workspace_identity.py:28–93` 只在原 reader 已验证且结构完整的 research reference 中剔除 registry-wide manifest 指纹；payload、receipt、root、date、slot、mode 仍保留；raw/source_row 不被递归改写。不允许泛化删除所有 SHA。
- UI10 同文件 `110–147` 以组件 digest 给 changed_components；旧计划缺记录时 CANNOT_CONFIRM，不能回溯重封为 CURRENT。
- UI10 `workspace.py:1047–1113` 的实时 owner diagnostics overlay、日期绑定与同 run 校验。
- FOUR router 的 US owner prepare → exact run 回读 → 真实新时钟 → plan → store 回读，不退回 R3 的 plan-only 手动路由。
- V9 frontend validator 的安全、合同、日期检查。为了页面能显示而删 validator 是回归。
- UI10 切日/切view取消与 sequence 守卫、失败显示语义应保留。成功 POST 直接复用与 R2 的 POST 后 canonical GET 存在明确合同差异，须按下方候选矩阵裁决，不能盲目二选一或混接。
- 发布工具的 active baseline、before/after SHA、manifest 与 non-delta 字节保留、共享锁与不覆盖既有候选目录。

## 4. 优化优先级与可执行验收

“优先1/2/3”仅为本文审查建议顺序，不替换或重定义原 V5 的 P0—P5 阶段。

### 优先1：先建立唯一基线与安全发布合同

**建议**：建立 composition manifest，逐文件标注来自哪个固定 commit/path/blob、前像 SHA、依赖模块与候选覆盖顺序。将 API app、router、service、workspace、前端 validator/panel、构建 dist、scheduler/binding 分别列身份；不以目录日期推断新旧。任何未知前像停止应用。

**验收**：

- 对实装前像逐文件比对，故意改一个 protected stage/preselection 文件后构建/校验应拒绝；非 delta 文件内容/权限保持原样。
- 正式项目 import、后端路由测试、TS typecheck、Vue/Vite build 在完整授权环境跑；离线 fixture 通过不能替代。
- API 响应、scheduler binding、静态资源 manifest、浏览器实际加载的 bundle 皆能追溯同一次发布；普通 `/` 与 `/preview` 分别验收。
- 明确记录 Git commit 已上传、候选构建、live activated、GET verified、UI verified、自然时段 verified 六层状态，不互相替代。

### 优先1：跨 API/页面的精确日期与 operation 身份

**已发现需评估的契约空隙**：V9 `refreshManagerWorkspace` 最后一行 `parseWorkspaceResponse(response, date)` 未把本次 `bindings` 传给解析器，而 GET 传了。panel 的 render 另有日期校验，不能直接推断现有页面一定错；仍建议让 API client 在入口统一 `parseWorkspaceResponse(response, date, bindings)`，并测试调用者无需依赖后续 render 才拒绝错日期。

**验收**：POST 响应 plan_date 相同但 selection_date 或 announcement_date 错一天，client 必须拒绝；GET/POST、历史/动态各自验证。切日后旧响应不得覆盖新日，双击 refresh 不重复触发 owner。返回 `operation_id` 后用 exact run 查询，不能靠最新文件猜测本次请求归属。

### 优先2：崩溃一致性与重复请求

**建议**：在保留原 owner 文件合同基础上增加 commit marker/产品索引或统一 publication record，只在 product + terminal attempt 已回读验证后更新可消费指针。新增恢复逻辑须能区别安全可恢复、失败、不可确认；绝不自动将孤立产品提升成功。

**验收**：依次在 RUNNING、product run file、product latest、terminal run file、terminal latest、dispatch completed 后注入退出/超时。重启后的只读 GET 不能显示未经同 run terminal 确认的 CURRENT；重试不会重复发布相同幂等任务；原合法历史产品不改字节。deadline 跨越任一保存/回读步骤，不能补成准时冻结。

### 优先2：资源隔离与预算（先量测）

**建议**：为 admission、owner source read、plan compute、durable write、readback、HTTP 分别打 monotonic 时长，记录 release、date、run、queue/busy、timeout_reason。观测实际 p50/p95/p99、线程/FD/RSS 后选预算，保持 parent > transport > owner 的 headroom，不能仅把 timeout 统一调大。

**验收**：模拟一个阻塞 reader 和并发经理 GET，stage/preselection 健康读仍达到事先约定 SLO；队列/线程数有上限，超限返回明确 busy；断开客户端后任务仍计入配额直到真实退出；超时源不得迟到写成功。测试过程仅用离线 fixture 或已授权只读来源，不交易。

### 优先2：普通页面可信状态而非技术字段堆叠

**建议**：先展示每路“是否已运行、覆盖是否完整、是否有效空、哪一步待处理”；默认折叠 hash 技术明细。并列“当前消费产品 run”与“最近尝试 run”，勿将后一次 FAILED 混作旧合法产品失败，也勿掩盖后一次失败。计划草案、盘前冻结、历史当时回放、现在重算必须分列。

**验收**：CURRENT 旧产品 + 新 FAILED attempt 两者同时正确展示；PARTIAL/NOT_RUN/READBACK_FAILED/有效空四组 DOM fixtures；无 owner artifact 不展示成功；成功 POST 后遵循明确选定的读回合同（A直接复用或R2规范GET）；规范GET不隐式生成/采集；POST 失败后单次 GET 显示的内容明确不是本次生成成功。历史模式禁用生成按钮，切动态必须显式。

### 优先3：版本兼容与可维护性

**建议**：将大 router 和 workspace 的 admission/readback/presentation 拆分为可单测模块，但保留接口与 owner；用版本化 schema 输出 compatibility report，版本变化只读拒绝旧合同或提供明确历史只读 viewer，不迁移重写旧产品。用跨语言共享 fixtures 校验后端输出与前端 validator。

**验收**：前后端 schema matrix（旧/新/缺字段/错时间/错误安全字段），兼容性拒绝可解释；旧历史文件 SHA 完全不变；静态页面加载过期 bundle 不静默渲染成成功。

## 5. 发布源码证据

OBS `issue30_release_policy/ops/api_release_integration.py`：

- `build_integrated_app:813–900`：读取 active release，复制 active app，核对 delta 的 before/after SHA/mode/diff，只应用 allowlisted delta，验证未改字节与目录权限，反复检查输入快照未漂移。
- `verify_api_release_candidate:935–1044`：校验 manifest、active-base/candidate 指针模式、delta receipt、非 delta inventory、共享锁条件。
- `shared_api_release_lock:1075–1129`：持久 POSIX lock inode + lease，不用“旧锁过期”替代互斥；源码特别注明旧 publisher 如不使用同锁必须由 owner 退役。

这些是已读取的发布门禁工具，不是本轮执行过的部署。缺完整 release cutover/restart/rollback 现场证据，不能宣称已有端到端回滚验收。建议发布验收同时检查其他发布器确实使用该锁、切换失败恢复旧 pointer、stage/经理/普通页面均能读旧版本，且不动历史产品。

## 6. 对 Chat 优化审查的要求

- 首先输出逐文件合并矩阵，特别解释为何所选 router 不会丢 FOUR 已有 US owner prepare 修复。
- 为每个 proposed fix 给失败 fixture、精确接口变化、保护不变量、回归测试和回退；没有证据的性能问题标注待测，不写成确定根因。
- 不创造公告 Reader/Reviewer、HK authority 或 US coverage；调度链通了不等于源数据齐全，候选 0 不等于全市场有效空。
- 不把 GitHub 候选、历史取证快照、test_support/current 和 Mac 现役混称同一版本。
- 原 owner/研究模式/不交易/不扩大权限保持不变。本报告不授权部署。

## 7. 实际读取源码与交付说明清单

原字节经过Git blob SHA、SHA256及字节数核验；仅README记录交付声明，不代表其后像均已深读。

1. [handoff/manager-daily-failure-20261009-r3/package/source_snapshot/issue30_release_policy/ops/api_release_integration.py](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-daily-failure-20261009-r3/package/source_snapshot/issue30_release_policy/ops/api_release_integration.py)
   - commit: `8c8e35d9d53431c9082dec49f4976e363c275765`
   - blob SHA: `9525da2da82355bee380b84a6251a69393b42fcc`
   - SHA256: `1f4afc70d7e5920b67c2b148def6b9167819664c33c92b475d919a097b9dd050`; bytes: 57781
   - snapshot: `sources/handoff__manager-daily-failure-20261009-r3__package__source_snapshot__issue30_release_policy__ops__api_release_integration.py`

2. [handoff/manager-daily-r3-repair-20261009/after/api_current/apps/api/v35_api/manager_research_router.py](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-daily-r3-repair-20261009/after/api_current/apps/api/v35_api/manager_research_router.py)
   - commit: `8c8e35d9d53431c9082dec49f4976e363c275765`
   - blob SHA: `31cc593405789b73b21eef1d5d9ee17ede4f3028`
   - SHA256: `9d8d132c58e7cf1c5a5609d93261483d578268ac24c60c2fa7a6a79b87344341`; bytes: 31088
   - snapshot: `sources/handoff__manager-daily-r3-repair-20261009__after__api_current__apps__api__v35_api__manager_research_router.py`

3. [handoff/manager-daily-r3-repair-20261009/after/api_current/infrastructure/scheduling/manager_announcement_supervisor.py](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-daily-r3-repair-20261009/after/api_current/infrastructure/scheduling/manager_announcement_supervisor.py)
   - commit: `8c8e35d9d53431c9082dec49f4976e363c275765`
   - blob SHA: `0acf933f1385625220a2e8255f9c7dc8fc0d0a1b`
   - SHA256: `e9a1e6f79abf268855a88d15dc579744ec4739f3561eccc56972badd89653ffa`; bytes: 34170
   - snapshot: `sources/handoff__manager-daily-r3-repair-20261009__after__api_current__infrastructure__scheduling__manager_announcement_supervisor.py`

4. [handoff/manager-daily-r3-repair-20261009/after/api_current/ops/run_manager_announcement_cycle.py](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-daily-r3-repair-20261009/after/api_current/ops/run_manager_announcement_cycle.py)
   - commit: `8c8e35d9d53431c9082dec49f4976e363c275765`
   - blob SHA: `e492fcb3d3e2487288d5b4e57e6bee40916892cd`
   - SHA256: `01b93a8985bc43f8f08ae5c6d97637abc2273fb20987fb27c6a78c6fc5b59d44`; bytes: 37015
   - snapshot: `sources/handoff__manager-daily-r3-repair-20261009__after__api_current__ops__run_manager_announcement_cycle.py`

5. [handoff/manager-daily-r3-repair-20261009/after/api_current/v4/manager_research/plan_owner_dispatch.py](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-daily-r3-repair-20261009/after/api_current/v4/manager_research/plan_owner_dispatch.py)
   - commit: `8c8e35d9d53431c9082dec49f4976e363c275765`
   - blob SHA: `c87e5535ff902eb3de3a805d502f1d8c7a7a875e`
   - SHA256: `2b532168bfdce41080121df318cb619011b98bb76195eba39df43046a130b987`; bytes: 53112
   - snapshot: `sources/handoff__manager-daily-r3-repair-20261009__after__api_current__v4__manager_research__plan_owner_dispatch.py`

6. [handoff/manager-daily-r3-repair-20261009/after/api_current/v4/manager_research/workspace_plan_autorun.py](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-daily-r3-repair-20261009/after/api_current/v4/manager_research/workspace_plan_autorun.py)
   - commit: `8c8e35d9d53431c9082dec49f4976e363c275765`
   - blob SHA: `dcab179e3cc291991e14e426adf8093fb31b71ef`
   - SHA256: `d7b2940f1203b62d642137a6b8eecffac566d0c1bf625d514c1345c0fc1a2a34`; bytes: 15547
   - snapshot: `sources/handoff__manager-daily-r3-repair-20261009__after__api_current__v4__manager_research__workspace_plan_autorun.py`

7. [handoff/manager-live-ui-api-repair-20261010-r1/after/apps/web/src/manager-selection/businessStatus.ts](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-live-ui-api-repair-20261010-r1/after/apps/web/src/manager-selection/businessStatus.ts)
   - commit: `8c8e35d9d53431c9082dec49f4976e363c275765`
   - blob SHA: `7bce8c049a09f084fcce2e5ad7265d2e06fca0e3`
   - SHA256: `25504185cef4cb8fdae83ec3043b371631fe9448d752e24105a1fe9438f47aba`; bytes: 17938
   - snapshot: `sources/handoff__manager-live-ui-api-repair-20261010-r1__after__apps__web__src__manager-selection__businessStatus.ts`

8. [handoff/manager-live-ui-api-repair-20261010-r1/after/apps/web/src/manager-selection/dailyChannels.ts](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-live-ui-api-repair-20261010-r1/after/apps/web/src/manager-selection/dailyChannels.ts)
   - commit: `8c8e35d9d53431c9082dec49f4976e363c275765`
   - blob SHA: `f17d16b4188c909c61297bc281222cb6e7606d55`
   - SHA256: `44b2fa24a470e4dec6c4318a49c9d028e481a67e93d3f996775cd933bd1a040e`; bytes: 19127
   - snapshot: `sources/handoff__manager-live-ui-api-repair-20261010-r1__after__apps__web__src__manager-selection__dailyChannels.ts`

9. [handoff/manager-live-ui-api-repair-20261010-r1/after/v4/manager_research/workspace.py](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-live-ui-api-repair-20261010-r1/after/v4/manager_research/workspace.py)
   - commit: `8c8e35d9d53431c9082dec49f4976e363c275765`
   - blob SHA: `b8fb7b1cfb37ee3caf135449395beaab34665494`
   - SHA256: `a6d6f067f04a3b543a8436e3080c9f7831e812a2cd10bbe16b783d23692ed33a`; bytes: 78441
   - snapshot: `sources/handoff__manager-live-ui-api-repair-20261010-r1__after__v4__manager_research__workspace.py`

10. [handoff/manager-live-ui-api-repair-20261010-r1/after/v4/manager_research/workspace_identity.py](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-live-ui-api-repair-20261010-r1/after/v4/manager_research/workspace_identity.py)
   - commit: `8c8e35d9d53431c9082dec49f4976e363c275765`
   - blob SHA: `09190c6bd3b240cb880fc9704184479a1c5e0b4d`
   - SHA256: `3c0680ed3996c754ebf0849830e2cd820ebc32d5e01e196ec0e125b5e439062b`; bytes: 7657
   - snapshot: `sources/handoff__manager-live-ui-api-repair-20261010-r1__after__v4__manager_research__workspace_identity.py`

11. [handoff/manager-live-ui-api-repair-20261010-r1/after/v4/manager_research/workspace_projection.py](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-live-ui-api-repair-20261010-r1/after/v4/manager_research/workspace_projection.py)
   - commit: `8c8e35d9d53431c9082dec49f4976e363c275765`
   - blob SHA: `ff3dfe8605e0a780cf68618b75ec235f7853fe32`
   - SHA256: `06b1e5cc770f22db8e111aa61fec9ba1f6ef8b7da5dca3da9a32995203634b17`; bytes: 31286
   - snapshot: `sources/handoff__manager-live-ui-api-repair-20261010-r1__after__v4__manager_research__workspace_projection.py`

12. [handoff/manager-daily-failure-20261009-r3/package/source_snapshot/issue32_protected/apps/api/v35_api/app.py](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-daily-failure-20261009-r3/package/source_snapshot/issue32_protected/apps/api/v35_api/app.py)
   - commit: `8c8e35d9d53431c9082dec49f4976e363c275765`
   - blob SHA: `f2cdb61eb5689f70bf9f9508e96a0262c0af7389`
   - SHA256: `5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5`; bytes: 324648
   - snapshot: `sources/handoff__manager-daily-failure-20261009-r3__package__source_snapshot__issue32_protected__apps__api__v35_api__app.py`

13. [handoff/manager-daily-failure-20261009-r3/package/source_snapshot/current_shared_scheduler/ops/run_v35_macos_scheduler_daemon.py](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-daily-failure-20261009-r3/package/source_snapshot/current_shared_scheduler/ops/run_v35_macos_scheduler_daemon.py)
   - commit: `8c8e35d9d53431c9082dec49f4976e363c275765`
   - blob SHA: `3efa5c11eb7e72ea77d4a05e28f44f6a9a559a83`
   - SHA256: `19e071da0c6b6748465853c4ad86a80d6060524333e9dab21647b67adc8b49ec`; bytes: 34320
   - snapshot: `sources/handoff__manager-daily-failure-20261009-r3__package__source_snapshot__current_shared_scheduler__ops__run_v35_macos_scheduler_daemon.py`

14. [handoff/manager-daily-r3-repair-20261009/after/api_current/v4/manager_research/service.py](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-daily-r3-repair-20261009/after/api_current/v4/manager_research/service.py)
   - commit: `8c8e35d9d53431c9082dec49f4976e363c275765`
   - blob SHA: `141624c44cb7a2b76d6ad1761852396e1fa8f8f2`
   - SHA256: `d7798b66cd8d1691c7b9f081380ce702c7e840b5fb137f4d72aeef56e4bef8a4`; bytes: 94921
   - snapshot: `sources/handoff__manager-daily-r3-repair-20261009__after__api_current__v4__manager_research__service.py`

15. [handoff/manager-validator-restoration-20261009-r1/after/apps/web/src/api/managerWorkspace.ts](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-validator-restoration-20261009-r1/after/apps/web/src/api/managerWorkspace.ts)
   - commit: `8c8e35d9d53431c9082dec49f4976e363c275765`
   - blob SHA: `427177891f85d35b1766cada0b67d045f39e6733`
   - SHA256: `2c02d4cff38d749fcad91b892da83029c8269287fbb867a2216f09ef8aa2c43f`; bytes: 119467
   - snapshot: `sources/handoff__manager-validator-restoration-20261009-r1__after__apps__web__src__api__managerWorkspace.ts`

16. [handoff/manager-four-functional-gaps-20261009/package/DAY_RUN_REUSE_AND_INTEGRATION.md](https://github.com/lexi2016/v4/blob/74478a0e62be215c8527ccc9a14b89b51042d014/handoff/manager-four-functional-gaps-20261009/package/DAY_RUN_REUSE_AND_INTEGRATION.md)
   - commit: `74478a0e62be215c8527ccc9a14b89b51042d014`
   - blob SHA: `8adf53b2e7e70540dd5a48c591d997bcd2394054`
   - SHA256: `8455e583ffbfb11e7e2c9a1c37f26c53c704969eda25515fb11d4d6e17def6f4`; bytes: 10877
   - snapshot: `sources/handoff__manager-four-functional-gaps-20261009__package__DAY_RUN_REUSE_AND_INTEGRATION.md`

17. [handoff/manager-four-functional-gaps-20261009/package/code/r2_chat_patch_target/apps/api/v35_api/manager_research_router.py](https://github.com/lexi2016/v4/blob/74478a0e62be215c8527ccc9a14b89b51042d014/handoff/manager-four-functional-gaps-20261009/package/code/r2_chat_patch_target/apps/api/v35_api/manager_research_router.py)
   - commit: `74478a0e62be215c8527ccc9a14b89b51042d014`
   - blob SHA: `d332ac9d0aa71ec30d7381396a845064687baba0`
   - SHA256: `5c2bb2aa5716726295811eee7919dce1e36420ce027589b0e467351b79b7fd7a`; bytes: 35556
   - snapshot: `sources/handoff__manager-four-functional-gaps-20261009__package__code__r2_chat_patch_target__apps__api__v35_api__manager_research_router.py`

18. [handoff/manager-live-ui-api-repair-20261010-r1/test_support/current/apps/web/src/views/ManagerSelectionView.vue](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-live-ui-api-repair-20261010-r1/test_support/current/apps/web/src/views/ManagerSelectionView.vue)
   - commit: `8c8e35d9d53431c9082dec49f4976e363c275765`
   - blob SHA: `75b848172dd2a3fbc00b44dfb720759867209e42`
   - SHA256: `3db9731126b88555fecf60ac1a12e952b06ed70f838e078207fad9da32c2bed5`; bytes: 202767
   - snapshot: `sources/handoff__manager-live-ui-api-repair-20261010-r1__test_support__current__apps__web__src__views__ManagerSelectionView.vue`

19. [handoff/manager-live-ui-api-repair-20261010-r1/after/apps/web/src/manager-selection/catalystObservationPanel.ts](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-live-ui-api-repair-20261010-r1/after/apps/web/src/manager-selection/catalystObservationPanel.ts)
   - commit: `8c8e35d9d53431c9082dec49f4976e363c275765`
   - blob SHA: `efe2c77e7f4826e9f85898fbe678528688531249`
   - SHA256: `ba13f895bf8b315c9649e73b4a4a6e843cf5d1475b25587745d72a76e7ef7173`; bytes: 63191
   - snapshot: `sources/handoff__manager-live-ui-api-repair-20261010-r1__after__apps__web__src__manager-selection__catalystObservationPanel.ts`

20. [handoff/manager-live-ui-api-repair-20261010-163151/README.md](https://github.com/lexi2016/v4/blob/fa97ac802a19b05d4e18c121f8bac77f2f5fa311/handoff/manager-live-ui-api-repair-20261010-163151/README.md)
   - commit: `fa97ac802a19b05d4e18c121f8bac77f2f5fa311`
   - blob SHA: `027d1e92aaf024d52ac5bece154c473f4aa25120`
   - SHA256: `0f385cfd466c76572e44e3ef25166b0ddb7ab206b5542b7e76790d6f718a4a2f`; bytes: 13572
   - snapshot: `sources/handoff__manager-live-ui-api-repair-20261010-163151__README.md`

21. [handoff/manager-live-ui-api-repair-20261010-r2/README.md](https://github.com/lexi2016/v4/blob/c8935da1217e6a3b43eeba2c3ce53d87ed4e27ee/handoff/manager-live-ui-api-repair-20261010-r2/README.md)
   - commit: `c8935da1217e6a3b43eeba2c3ce53d87ed4e27ee`
   - blob SHA: `85174ca2662618b2cc708f6edf4e642698eae222`
   - SHA256: `85a1946b6cd944a56d4ce0241a2adbc1526c4b2fe6b33b4cc6d712f41dbc2c6e`; bytes: 11291
   - snapshot: `sources/handoff__manager-live-ui-api-repair-20261010-r2__README.md`
