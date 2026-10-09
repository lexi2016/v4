# 唯一实现 owner 参考输入

本文件保留 architect 的冻结实现要求，作为唯一实现 owner 的参考材料；它不是 Chat 并行派工。当前 `module_proxy.py` 与 `api_module_contracts.json` 仍处于 `PARALLEL_IMPLEMENTATION_IN_PROGRESS/NOT_BASELINE`，不得将其工作树字节误当设计前 preimage 或固定基线。

请按本包实现 Stage API 与 Manager API 的受限独立运行/发布候选，不执行生产发布。先阅读本目录 `README.md`、`ARCHITECTURE_HANDOFF.md`、`ROUTE_CONTRACT.md`、`IMPLEMENTATION_SCOPE.md`、`ACCEPTANCE_ROLLBACK_MATRIX.md`、`OPEN_DECISIONS.md` 和 `evidence/`。它们是冻结合同；facts/inference/gaps 要分开，不把设计或文档自评当作实际运行验收。

**唯一目标：** 保留现有 8873 浏览器入口和静态页面平台 owner，在 8873 加固定 route dispatcher；Stage 与 Manager API 各自 loopback 运行、manifest、plist、binding、release root、锁和 role rollback。实现只在受控 release chain 内做受限 role 参数化/版本化，不新建平行发布器，不改业务算法、数据 owner、Stage selection state、A/HK 边界、Manager binding 或 BUY 安全。

**允许目标改动路径**（先在当前 canonical repo 验证实际 owner 与文件状态，再按 architect 文件表实现）：

- `apps/api/v35_api/module_proxy.py`（新增）
- `deployment/api_module_contracts.json`（新增）
- `apps/api/v35_api/app.py`、`apps/api/v35_api/run.py`（最小路由/role 启动合同）
- `ops/api_release_integration.py`、`ops/build_release_candidate.py`、`ops/release_candidate_sources.py`、`ops/prepare_api_only_cutover.py`（现有受控链的 role-aware 候选版本）
- `deployment/com.lexi.v4.stage-api.plist`、`deployment/com.lexi.v4.manager-api.plist`（新增角色配置）

项目 canonical 根为 `/Users/lexi/Desktop/学习/v4_app`。不要改任何现役 app release、LaunchAgent、共享 state/研究数据、`web/dist`、已存在 Stage/Manager candidate、Vibe 8910、凭证或全局 hooks。不要把整个 app 根当一个 role release，也不要复制完整 app 初始化来重复 scheduler、producer 或后台写任务。对冻结 ISSUE30 guard 与 ISSUE32 cutover 先读源码；不得原地覆盖冻结版本或绕过其 CAS、前后像、非 delta、lock 和 rollback 保护。

**固定合同：** 8873 保持唯一入口和统一静态页面，Stage API loopback 8874、Manager API loopback 8875（安装时重新确认占用）。仅按 `ROUTE_CONTRACT.md` 固定的 method/path 分流，不接收 request-provided upstream。保留原请求/响应合同，过滤 hop-by-hop header，设置有界 timeout；POST 不自动重试；错误方法 405、已知后端离线 503/504、不回退旧 handler，未知 API route 404 只适用于本分流合同，平台其他既有 routes 保持原行为。Manager `/api/v3/manager/stage-selection` 只读共享 Stage selection owner。UI 改动由平台单独发布，不建微前端。

**实现要求：**

1. 对每个目标路径记录 before/after SHA、变更原因、release root、role manifest 和允许的 delta。新合同需明确 route-method、role、端口、label、manifest、binding、锁和 rollback identity；错误或不完整角色信息 fail closed。
2. 角色进程只加载本模块需要的路由与副作用；静态资源只由 gateway/platform 提供。验证启动依赖和实际调用图，证明不会重复初始化 producer/scheduler/后台 writer。
3. 沿现有受控发布链实现 role profile；Stage/Manager 使用独立固定锁，拒绝错 plist、manifest、source delta、角色 path 或静态/gateway bytes。gateway 默认行为和当前安全链保持兼容。
4. 写针对真实合同的测试：method/path mapping、body/query/status/content-type/required headers、405/404/503/504、POST no retry、错 role/manifest/delta 拒绝、两把锁独立、跨角色/平台 SHA 保持、角色 rollback 及 gateway rollback 保留 dispatcher。不要仅改 route 名称或用单元 PASS 声称完成运行隔离。
5. 只产候选文件和测试；不要切 LaunchAgent、启动/停止服务、改 state、调用真实行情/producer、发布、commit/push 或发送外部消息。

**停止条件：** 如果 canonical owner、路由合同、release guard 实际字节、rollback 边界或原数据 owner 与冻结材料不一致，保留当前文件，报告具体冲突和 `CANNOT_CONFIRM` 给主控。端口在候选实现阶段只记录待安装复核，不强占。

**交接输出：** 提供最小 diff、所有 touched path 的 before/after SHA、测试命令与结果、manifest、角色 source closure、完整 release/rollback matrix、未执行项和 `CANNOT_CONFIRM`。Writer `PASS` 只是交接。另由不同 agent identity 的 Luna Max Reviewer read-only 检查 actual diff、P0/P1/P2、scope、运行角色行为证据，出具 `REVIEWED` / `BEHAVIOR_VERIFIED`；部署/API/UI/natural status 分开记录。
