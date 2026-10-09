# 独立问题包审查

REVIEWED_PACKAGE: FAIL  
BEHAVIOR_VERIFIED: CANNOT_CONFIRM (NOT_RUN)  
P0: 0 · P1: 1 · P2: 0

审查只覆盖 E 问题包及只读源码。未运行服务、POST、行情采集、R3/HK/Stage 业务测试、部署、GitHub 操作。问题包被明确标为 DESIGN_ONLY，没有把设计或 Writer 回执升格为实现或运行行为。

## 结论

隔离边界与目标行为合同整体准确，作为设计说明可复核；17 个 Manager research 路由经当前 router AST 与 SHA 复核，Stage 六路由也与当前 pinned app/router 源码逐项相符。8873 固定入口、Stage/Manager API 独立 role 与锁、平台独立发布 UI、只读 Stage consumer、不增加 producer、旧 handler 不 fallback、角色回退和交叉发布矩阵均有明确描述。现有 guard 固定 api-only label/共享锁、ISSUE32 cutover 固定 8873/Issue32 根等限制被如实写为待 role 化处理，未声称已有支持。

但 PASS_SIGNAL 还要求包可直接交 Chat 实施并可从固定来源复核。当前 ZIP 只有说明、JSON 摘录和验包工具；所需精确源文件字节依赖这台 Mac 的绝对路径，且没有声明一个覆盖这些源文件的可取回 Git remote/ref。因此 Chat 离开 Mac 后无法仅凭 ZIP 和包内 Git SHA 取得完整实施前像，REVIEWED_PACKAGE 不能 PASS。

## 发现

### P1-1 — 实施所需源码前像未随 ZIP 固定，缺少可移植的固定 Git 来源

ZIP 当前 SHA-256 1924122131b7ec11ea1c2e7e57a9337b513256ab762652cb196daca9f728a22c 与冻结值一致；包 manifest SHA-256 5f98c2d7b0c780ac9ac835e714f6ade6ce96d3ea6ece3630161f5f96688e5304 也一致。ZIP 共 25 项，除 manifest 外 24 项均为 Markdown/JSON/验包器；没有应用或发布器源码。manager_evidence/source_extracts_20261009.md:1-3 也明确这些是摘录，不能作为可执行源码。

实施计划要求 Chat 改 apps/api/v35_api/app.py、run.py、ops/api_release_integration.py、build_release_candidate.py、release_candidate_sources.py、prepare_api_only_cutover.py 及 role plist，并在修改前核 owner 与精确源码（package/IMPLEMENTATION_SCOPE.md:17-32；package/CHAT_IMPLEMENTATION_PROMPT.md:7-15）。包内 provenance 只列出若干外部文件的 Mac 绝对路径与 SHA，例如 app/router/cutover（package/manager_evidence/manifest.json:47-80），没有这些完整文件字节；清单没有列 run.py、release builder/source helpers 或现役 gateway plist，也没有列 ISSUE30 guard。README 明说其它机器缺少绝对路径时，外部原件身份是 CANNOT_CONFIRM（package/README.md:16,28）。

我在本机读取并核实了来源限制本身：冻结 ISSUE30 guard SHA 为 1f4afc70d7e5920b67c2b148def6b9167819664c33c92b475d919a097b9dd050，其中只接受 com.lexi.v35.api-only（guard 行 503-504），并固定 .com.lexi.v35.api-only.release.lock（行 1047-1053）；ISSUE32 cutover 固定任务根、127.0.0.1:8873、API-only label 与共享锁（api_only_cutover_issue32_r4.py 行 37-64、83-85、281-286）。包确实正确指出这些限制不能靠替换 plist/端口解决，但 guard 全文和其来源身份没有进入 package manifest/ZIP。cutover 有 SHA provenance，却同样只有外部源路径，不能从 ZIP 还原。

包中 r3_candidate_summary.json 的 source_commit/candidate_commit 是 R3 候选身份（行 7-9），未声明 repository URL，也未绑定到完整的 ISSUE32 活跃 API 源、ISSUE30 guard 与发布 helper 前像。CANNOT_CONFIRM：这些 SHA 是否可从一个 Chat 可访问的固定 Git ref 取回、以及该 ref 是否含齐上述字节。

影响：Chat 若只拿本 ZIP 和这些候选 commit 字符串，必须猜测或自行寻找关键实现源；尤其无法审查角色启动副作用、release builder/source closure 与锁/回退行为的精确前像，可能把模块隔离实现成复制整 app、重复启动 scheduler/producer，或削弱原发布保护。这不是说已有运行行为错误，而是本问题包未达到“可直接交 Chat 实施”的交付条件。

修复条件：将最小必要源码前像（含冻结 ISSUE30 guard、ISSUE32 cutover、当前 app/run/router、release helpers 和现役 gateway 配置）作为带 SHA 的只读 source snapshot 纳入 ZIP；或给出可由 Chat 访问的 repo URL + 固定 commit/ref + 文件路径，并验证每个所需文件都能从该引用取回。补齐后重建 manifest/ZIP 并重新核验。不得以 Mac 绝对路径代替固定远程来源。

## 已确认项与边界

- 6 个 Stage 路由、17 个 Manager research 路由、2 个 Manager 其他路由数量和唯一性通过验包器；--verify-source-provenance 在本机按 manifest 列出的来源 SHA 复核通过。当前 manager_research_router.py 的静态路由定义先于 /{target_trade_date}；实际源码摘录与合同相符。
- 交叉发布矩阵要求升级、重启、冷回滚时另一模块及 8873 gateway/static SHA 不变；离线/错 role、405、503/504、POST 不重试、独立锁、保留 dispatcher 的 gateway 回退都有可证伪读回项。
- 目标保持 8873 唯一 UI/API 入口，Stage API 与 Manager API 分角色；页面源码通过平台单独构建发布。原 Stage selection/data owner、Manager 只读 consumer、binding、算法、A/HK 边界及 BUY 安全旗标不迁移；没有第二 producer 的设计。
- ZIP 仅含文档/JSON/Python 验包器，无数据库、行情文件或业务产物。25 项内容的 credential-pattern 扫描为 0 命中。JSON/Markdown 中仍含 Mac 用户目录、运行目录、Stage selection/shared-data 根等绝对路径与 PID：这是路径元数据，不是 state 内容或凭证；若包要发到当前 Chat 之外，脱敏范围需由 owner 决定（外部受众边界 CANNOT_CONFIRM）。
- 经理 R3 的 66/0, 36/0, 18/0 是 Writer-only 离线结果，旧 HK 补充 12/3 保留 FAIL_RECORDED；Stage Mac 本机为 0 项，历史 Linux 287 项没有升格。没有重跑业务 suites。具体历史覆盖事件因果链仍 CANNOT_CONFIRM。
- 当前 REVIEWED_PACKAGE: FAIL 是交付完整度 verdict。模块隔离尚未实现，服务、集成、部署、API/UI 和自然时段行为均未运行；BEHAVIOR_VERIFIED: CANNOT_CONFIRM。

## 验包命令

见同目录 verification.log。本机 provenance/manifest/ZIP 验证和临时解压后的包内验证均通过；这些只证明包内/已列外部来源的字节一致，不弥补上面的源闭包缺口。
