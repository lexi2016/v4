# Stage 与经理 API 独立发布：架构交接

状态：只读设计完成，IMPLEMENTED / TESTED / DEPLOYED / BEHAVIOR_VERIFIED 均 NOT_RUN。用户要求先拆发布耦合并交问题包；不将本文件视为实现或运行验收。

## 目标和已证事实

当前 8873 API PID78617 使用 issue32_preselection_api_actual_r4，同一 app 注册 Stage 与经理路由，并挂载 apps/web/dist。两个业务候选都源于完整 app 快照，整根切换存在相互覆盖风险；具体历史事故因果链 CANNOT_CONFIRM。Stage 业务修复本机尚未集成，经理候选已保留但未部署，详见各侧证据。

## 冻结方案

- 8873：唯一浏览器入口、同域固定方法/路径分流、共享静态资源。归平台 owner，普通模块发布不得改其路由、配置、bundle、manifest 或进程。
- Stage API：独立 loopback 8874、com.lexi.v4.stage-api、release root、manifest、active plist、发布锁及回滚点。
- Manager API：独立 loopback 8875、com.lexi.v4.manager-api，同样独立。端口仅为安装前待复核的选择，不能根据一次空闲观察强占。
- Stage/Manager 的代码升级、重启、回滚不改另一模块或平台。页面 URL 不变，保持原数据 owner、原 state/read roots、原算法/门禁，不产生第二 producer。
- 本方案隔离 API 发布。页面仍由平台单独构建发布；Stage 与经理的页面改动提交平台合并，不随任一 API release 覆盖共享 dist。暂不引入微前端框架。若后续要求 UI 也完全独立发布，另作静态入口/资产合同设计。

## 固定路由 ownership

| 方法 | 路径 | 后端 |
|---|---|---|
| GET | /api/v3/meta/stages | Stage |
| GET | /api/v3/preselection-pools | Stage |
| GET | /api/v3/workbench/stage | Stage |
| POST | /api/v3/workbench/stage/ensure | Stage |
| GET | /api/v3/stage-center/selection | Stage |
| POST | /api/v3/stage-center/selection/ensure | Stage |
| GET | /api/v3/manager/stage-selection | Manager |
| GET | /api/v4/manager/workbench-research | Manager |
| 逐项提取现有已注册方法 | /api/v4/manager/research 下现有明确路由 | Manager |

research 路由必须从当前 manager_research_router.py 提取并在合同中逐项列明，不能用任意方法/任意子路径透传替代。manager/stage-selection 固定归 Manager，经原 StageSelectionConsumer 只读同一 Stage selection 根，不成为写入者。Stage产物合同与Manager consumer兼容性必须纳入各自升级验收。

## 按文件实施任务

1. 新增 apps/api/v35_api/module_proxy.py、deployment/api_module_contracts.json；最小修改 apps/api/v35_api/app.py、run.py，明确 gateway/stage/manager 角色和启动合同。role 只启用本模块必要路由/依赖；核查并禁止因复制完整 app 初始化而重复启动 scheduler、producer 或后台写任务。后端拒绝非本角色路由和静态请求。
2. ops/api_release_integration.py：在现有保护链加入不可伪造的固定角色表，绑定 Label、plist、端口、release root、manifest、delta allowlist 和锁。原默认gateway行为保持。当前实现拒绝非 api-only plist 且固定同一锁，尚不支持仅传另一plist实现独立发布。模块分别使用 .com.lexi.v4.stage-api.release.lock / .com.lexi.v4.manager-api.release.lock；原gateway锁保持。
3. ops/build_release_candidate.py、ops/release_candidate_sources.py、ops/prepare_api_only_cutover.py：受限角色profile、角色manifest与路由合同SHA，拒绝跨角色delta和静态/gateway改写。可以保留不可变完整依赖闭包，但不能以模块发布切换整个8873 app或激活包中其他角色内容。
4. 复用既有受控激活流程。当前实际guard为V4_ISSUE30_MAC_20261008/package/after/ops/api_release_integration.py；cutover为V4_ISSUE32_MAC_20261009/tools/api_only_cutover_issue32_r4.py，均属已冻结版本，禁止原地改写。后者硬绑8873、Label和Issue32根，不能只换plist/端口复用。Chat应交其可审查最小role化差异/新版本候选，并明确未来canonical落点，沿原锁、CAS、前后像、非delta保护、回滚流程实施；不得新增绕过门禁的平行发布器或任意路径覆盖开关。
5. 一次性运行配置：保留现有 com.lexi.v35.api-only.plist 作为gateway入口；新增 com.lexi.v4.stage-api.plist 与 com.lexi.v4.manager-api.plist。精确数据根从当前实际配置继承，各角色独立配置/manifest/binding；业务binding保持原writer/API身份约束，不被网关路由合同取代。
6. 必要测试由改动文件真实合同驱动：角色绑定、方法/路径路由、代理错误、非模块路径拒绝、错plist/manifest/delta拒绝、跨角色保护、独立锁和回滚；不靠改名称或单元PASS宣称隔离。

## 网络和失败语义

固定目标仅loopback，不允许从请求输入指定上游URL。保留路径/query/body/status/content-type及必要响应头，去除hop-by-hop头；设置有界连接/读取时间，不自动重试可能写入的POST。已分流的已知路由错方法405、后端不可用503/504，禁止fallback旧handler。仅本拆分合同的未知API路由404；平台其他既有合法路由继续原行为，不全局拦截正常接口。

## 一次迁移与后续独立发布

先冻结身份和当前指针，建立并启动两个隔离后端，核readiness及原数据身份；随后一次切换8873分流并验证。不得先切网关再让未就绪后端承接请求。迁移失败按预先定义的整体回退流程恢复；正式拆分启用后，模块冷回滚仅回本角色前版，gateway日常回滚必须回仍带dispatcher的兼容版，不静默重新暴露旧handler。回到未拆架构必须作为显式整体迁移回退，不是模块发布选项。

## 唯一验收信号

Stage独立升级/重启/回滚：Manager PID、manifest/source SHA、API行为及8873静态SHA不变，8873 Stage同date/stage/run读回；Manager做对称验收，Stage同样不变。分别验证锁可独立取得，错角色拒绝，后端离线不fallback，共享平台/其他模块字节不变。首次平台迁移单独记录，不能用迁移时允许变更掩盖后续跨模块覆盖。

本次不修改选股算法、权威数据层、自然触发规则或交易位。HK缺真实日期输入继续BLOCKED_DATA。架构工程通过仍不等于选股或自然时段验收。

## 本机来源

- manager_evidence/SHARED_SURFACE_20261009.md 与 manifest.json。
- /Users/lexi/Desktop/学习/agents调试/V4_STAGE_MINIMAL_FIX_MAC_20261009/evidence/CURRENT_STATE_RECEIPT.md / .json。
- /Users/lexi/Desktop/学习/agents调试/V4_MANAGER_R3_REPAIR_MAC_20261009/coordination/SHARED_OWNER_CURRENT_IDENTITY.json、SHARED_OWNER_HANDOFF.md、SHARED_OWNER_POLICY_REVIEW.json、SHARED_OWNER_INCREMENT_1415.json。

独立架构输入：Luna Max architect stage_independent_api_design；主控只做文档整合和迁移顺序/ownership约束，不签发源码或部署PASS。最终问题包由经理会话唯一Writer和独立Reviewer交付。
