# Stage 与经理共享运行面：经理侧证据摘要

观察基准：2026-10-09 14:04 +08 的共享 owner identity 快照；2026-10-09 14:33 +08 对 LaunchAgent、PID、工作目录、binding 与源码字节作只读复核。该摘要记录当前共享边界，不代表模块隔离、R3 候选验收或发布完成。

## 已证实事实

- `com.lexi.v35.api-only` 的 API 进程 PID 78617 在 8873 运行，`WorkingDirectory`/`V35_APP_ROOT` 指向 `/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app`。manifest SHA-256 为 `16675f6016d40e8a5eaf7b1e3e37694228364fae544e8a7b73e4bf17e1f5a9e6`，与 pin 相符。
- 这个 API app 同时定义 `/api/v3/manager/stage-selection`，注册 `create_manager_research_router`（`/api/v4/manager/research`）及 `create_manager_workbench_router`（`/api/v4/manager/workbench-research`），并从同一 app 根挂载 `web/dist`。源码锚点是 `apps/api/v35_api/app.py`（SHA `5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5`），经理 router SHA 分别为 `manager_research_router.py` `84f65a351e1e44171820cb8698e4198b3084e39b8d0cfe82c6b4bc05595f8073`、`manager_workbench_router.py` `95ccda85ff50d44cffbb18fc655e417f926c14b27a60cfa4c5fad17a3cbd1b5e`；Stage API 的受保护 `preselection_router.py` SHA 为 `718d54a6c6aa8cde2871ce4dc41cbc1d825f199a57b605e4f5ec70d8c4fe19ae`。因此整 app 根切换会同时改变 Stage、经理 API 与统一 8873 静态页面所用字节。
- API LaunchAgent 当前 `V4_MANAGER_PLAN_OWNER_BINDING_PATH` 指向 `V4_MANAGER_DAILY_CHAIN_20261008/deployment/c1_plan_only/staged_config/manager-plan-binding-c1.disabled.final-d1-r2.json`，SHA `f3b7cbfa1709b2b27816d294e599cb1ae82ff918ba41ec148644f1a1751f5fd6`；identity readback 为 `enabled=false`、`plan_owner_present=false`，其绑定 `app_root` 是经理 API 的旧 R2 路径。
- `com.lexi.v35.scheduler` 是另一个 LaunchAgent/PID 83677，工作目录和 `V35_APP_ROOT` 指向 `/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/issue32-preselection-scheduler-mac-20261009-r1/app`，而 `PYTHONPATH` 也指向该 scheduler app 与 `upstreams`。该树与上面的 API candidate/app 是两个不同源码副本，不能混作一棵树。scheduler manifest SHA `6ccaa8fcf7e7046b53b2451829a1c4ed805ad274287ae2580eee36391f5f0794` 与 pin 相符；daemon 与 launcher 文件 SHA 分别为 `19e071da0c6b6748465853c4ad86a80d6060524333e9dab21647b67adc8b49ec`、`0c577ae83b1f182dabf3b62e642a5bd5f0f8708b48e1806d8c653b691d2ec952`。该进程的 Python 解释器/runtime 来自 `20260904T081111Z-v35-strict-stage-acquisition-v15/runtime`；解释器位置与其 app 源码根不同。
- 当前 scheduler 环境中的经理公告绑定是另一份文件：`MANAGER_DAILY_CHAIN_FIX_20260928/staged_config/manager-daily-plan-hook-r1/manager-plan-binding-r2.json`，SHA `c0fbff52449eb5dbf5c1655f17cf08915bea1214f9499cc8a4df1176d9625951`，`enabled=true`，指向 worker 根 `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-us-mapping-daily-20261006-r2/app`；plan owner 仍缺。其 canary pin 为 `f891e74f2bbfed928f36479b0cbea57ab5fdcf2ab4882f9977f82654bfcbba81`。scheduler 与 API 的经理 binding 不同，不可推断二者一致或已经使用同一个计划 owner。
- API 与 scheduler 都指向共享 Stage selection 状态根 `/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection`；API、scheduler 另各自读取共享研究数据根。运行/发布树分开不代表数据、路由、绑定或统一页面边界已隔离。
- `V4_ISSUE32_MAC_20261009/tools/api_only_cutover_issue32_r4.py` SHA `864a07b9bdf915a14b877eac89ddc931bb0f4976b70599c242671ff177e9cf25` 描述的是 API LaunchAgent 根切换：限定写 API plist、发布锁及本任务 receipt/备份，并将 scheduler、binding、经理状态设为只读。其目标虽然是经理 R1 API 候选，指针仍切换整份 API app 根；这属于 API-only 切换，不是 manager-only 模块发布，也不建立 Stage 与经理源码隔离。本轮没有运行该工具。
- R3 的共享政策审查 SHA `aa9bc900b2c4959dcc6945fe389c40bdf4829b752deb21f029a5936c48872416` 为 `PASS_POLICY_ONLY`：只审过五条精确 shared paths（见 `manager_evidence/manifest.json`），无 broad prefix 且 `automatic_application=false`。其 P2 明确缺政策定向测试 receipt 和最终候选身份核验；它不是 R3 候选行为验收或已采用政策。
- 稳定 R3 writer receipt `evidence/mac_candidate_receipt.json`（SHA `30113d01f3c9ffec5ad16f9b617ad9bfb15da13ff09b9a5c287a715e42e168fd`）记录候选树 192 个原始文件核验、191 条清单 hash 无 mismatch，状态 `CANDIDATE_SAVED_WRITER_TESTED_REVIEW_PENDING`。离线结果为 R3 范围 `66/0`、daily regression `36/0`、policy/verifier `18/0`；旧 HK supplement `12/3` 保留为 `FAIL_RECORDED`，其中两项是已知 screen failures，一项是固定旧 helper 期待 updater 不提供的 CLI 参数。它们不是本隔离包的测试，也没有因本任务重跑。
- R3 只有候选根：API current 13 paths、worker 5、HK child 3、web 0 新路径（复用既有 R2 after）；candidate root 与各自 source root 对照见 receipt。API 候选中的 daemon/launcher 副本 SHA `c5a922e5f5dc71bd5df61a1ee72eb7fceb0d8347142c5297981242f207b226d9` / `2634b60f718e4c94fec0d731d12102e27d85847d8e0b9e8bb6f5ab499ae6d9d5` 不等于当前 scheduler root 的 `19e071da…` / `0c577a83…`；receipt 证明它们是 API 树中被保留的重复文件，LaunchAgent 指向独立 scheduler 根，因此不构成 scheduler drift。
- R3 `REVIEWER_ENTRY.md` SHA `c0ad3b4abafd50c94d57404e6faa532680cf00d879c1a4acc9f2f05ab4853fa8` 要求独立只读 review；`FINAL_HANDOFF.md` SHA `97eaf87137319f4f143ca4722228213e39246f6ef6a3020cb61df5ebc14049e9` 明确 `independent_review=PENDING`、`shared_root_published=false`、`stage_delta_applied=false`，当前 integration boundary 等唯一 shared owner 完成单独 Stage release boundary。R3 Writer PASS 不提升为独立验收、集成或部署。
- 14:04 identity 快照中 `com.lexi.stage-center.scheduler` 为 `not running`、last exit code `3`。本摘要没有把 Stage scheduler 的服务状态推断为由经理发布造成；也没有证据说明这项状态与候选未部署之间存在因果关系。
- Stage 侧固定回执另确认 `apps/web/src/App.vue` 与 `apps/web/src/contracts/runtime.ts` 都是带现存修改的 UI 共用路径，且 package 历史前像不匹配，`StageExecutionEvidencePanel.vue` 缺失；Stage 源改动、测试、构建、部署均未运行。细节和 source SHA 见 E 内精简证据 [STAGE_SHARED_BOUNDARY_20261009.md](../evidence/STAGE_SHARED_BOUNDARY_20261009.md) 与 `evidence/stage_boundary.json`。这表明页面发布也需要独立所有权，但不证明 8873 当下静态内容或某次覆盖事件。

## 推断与限制

同一个 8873 API app 同时承载 Stage route、经理 routes 和静态 UI，所以替换整份 API app 可产生跨模块影响；共同状态根和跨进程 manager binding 又使“只拆源码目录”不足以证明运行隔离。scheduler 自己的服务树不同于 API 树，但仍依赖 manager worker 根及共享 Stage selection 状态。基于这些文件可确认发布/运行耦合面，尚不能确认某次具体覆盖事件的因果链。

`launchctl`/进程参数证明当前配置指向的根及运行 PID；没有读取 Python 进程内部 module object，故精确的内存加载字节仍为 `CANNOT_CONFIRM`。共享 owner identity 是 14:04 的固定快照，14:33 复核确认 LaunchAgent 指向和 PID 仍一致；交接或任何后续发布前必须按原 owner 流程重新读实际 plist、manifest、binding 和源码 SHA。具体 Stage→manager 或 manager→Stage 的覆盖事件与因果链仍为 `CANNOT_CONFIRM`；现有证据能证明边界耦合点，不能替代覆盖事件的 before/after receipt。

## 必须保留的边界

8873 仍是唯一用户入口；沿用原算法、共享研究数据 owner 与产物合同；A/HK 边界保持；不得把 Stage/HK 输入生产迁入经理模块；`RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。API 与 scheduler 都使用同一状态根的观察不授权改写共享 state。

