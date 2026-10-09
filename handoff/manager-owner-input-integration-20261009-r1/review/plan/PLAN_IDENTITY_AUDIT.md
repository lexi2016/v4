# Plan identity 独立审查

## 结论与范围

根协调的候选已应用两处最小修复；本分工独立重跑最终七项，**7 passed / 1 warning，3.14 秒，exit 0**。对应原基线是 **4 passed / 3 failed**。候选与基线分开保留，证据仅覆盖离线合成应用行为。

固定 R2 附件所示 `5df99128…` saved identity 与 `7c5d9f18…` GET identity 不同，不能直接认定 stale guard 有 bug。原 isolated owner 与 `create_app` 注入的 archive/close/native readers 不同，附件 gaps 也明确变化。本审查已通过真实 `create_app` 创建的 service、原 plan owner 保存、真实 FastAPI GET，证明相同 reader/date 绑定刷新后可 `CURRENT`，不同 reader 绑定仍 `STALE_INPUTS_CHANGED`。

另发现两个可在离线应用接线中确定性复现的代码缺口。它们不构成“Mac 的 20261009 数据已恢复”的证据，也不解释附件中未绑定 HK authority 时的全部 identity 差异。

1. `connect_selection.filter_cards` 把 V2 authority 的本次读取时刻 `read_at` 带进材料卡，进而带进 plan identity。相同 source 文件、相同 authority identity，仅 witness clock 从 08:00 变成 08:01，GET 从 `CURRENT` 变为 `STALE_INPUTS_CHANGED`。反向独立测试还证实，该投影错误排除真正持久化的 `available_at`：相同 read_at 下，合法 publication available_at 07:02→07:03、publication SHA 改变，GET 仍错误 `CURRENT`。
2. `workspace.refresh_workspace_plan` 的 scheduled duplicate reuse 分支不比较完整 `date_bindings`。旧 `selection_date=20261008` 的 `SCHEDULED_MORNING` 产品，可被目标 `20261009` 的正常 morning dispatch 报作 `ALREADY_MATERIALIZED`；默认 selection=target 的 GET 随后正确拒绝该旧绑定。

本分工没有修改生产文件、Stage、BUY、Vibe 或实际服务，没有进行网络数据采集、GitHub 写入或部署。

## 原调用链与源码锚点

| 边界 | 固定 R2 源码位置 | 已确认行为 |
|---|---|---|
| 应用 owner 创建 | `apps/api/v35_api/app.py:5245–5269` | 一个 `manager_research_service` 注入 archive source、close reader、master/screen roots、US reader，再同时交给 GET/POST router。 |
| 手动 POST | `apps/api/v35_api/manager_research_router.py:253–324` | 接收 selection/announcement 查询，透传 `workspace_date_bindings`，由同一 service 执行原 plan owner。 |
| 原 plan owner | `v4/manager_research/service.py:469–478` | 委托同包 `workspace.refresh_workspace_plan`。 |
| 日期与保存上下文 | `v4/manager_research/workspace.py:480–561` | 全日期对匹配时复用 saved cutoff，但重新执行原 readers；日期对不匹配不复用上下文。 |
| identity 汇总 | `v4/manager_research/workspace.py:706–765, 881–896` | Connect 过滤后的 discovery cards 进入原 workspace projection；再汇总 announcement、research attention 与已消费 mapping identity。 |
| GET stale 门禁 | `v4/manager_research/workspace.py:1031–1068` | 比较 input identity、semantic version、完整日期绑定、cutoff，并验证同 run owner attempt；保护本身应保留。 |
| 定时 duplicate reuse | `v4/manager_research/workspace.py:1168–1194` | 比较 input identity / semantic version / execution kind / cutoff；漏掉 `date_bindings`。 |
| 定时入口 | `v4/manager_research/plan_owner_dispatch.py:402–435` → `ops/run_manager_announcement_cycle.py:401–438` → `workspace_plan_autorun.py:242–299` | 正常 morning 分支把 target 交给既有 owner；owner 默认日期为 target selection + previous HK publication。 |
| V2 读取 witness | `domains/manager_research_evidence.py:251–276` | `available_at` 来自持久化 publication；`read_at` 是本次 native reader clock。 |
| 错误 witness 投影 | `v4/manager_research/connect_selection.py:187–191` | 注释说 witness clock 不进入 identity，代码却排除 `available_at` 而保留 `read_at`。 |
| 进入语义哈希 | `v4/manager_research/workspace_projection.py:492–496` | 整个 `discovered_cards` 被哈希，含上一步的 membership_source。 |

## 实际行为结果

最终自包含七项真实应用行为基线运行：**4 passed / 3 failed / 1 warning，3.09 秒**，见 `baseline_seven_cases.log`。此前首次完成的四项运行是 2 passed / 2 failed，随后补充独立 availability 负向与两项 scheduled 正向；原日志均保留。

| 测试 | 原基线结果 | 证据意义 |
|---|---|---|
| `test_app_injected_owner_same_binding_is_current_and_changed_reader_is_stale` | PASS | 同 app owner 保存后 GET 为 CURRENT / consumed=true / run_readback=VERIFIED；run、product SHA、attempt 同源校验；拆掉 archive reader 后 input identity 改变并 stale。GET 前后 manager 文件 SHA 不变。 |
| `test_app_get_keeps_different_selection_binding_stale` | PASS | 改 selection 查询继续 fail closed；GET 无写入。 |
| `test_scheduled_dispatch_cannot_reuse_saved_other_selection_binding` | RED | 真实 dispatch branch → ops → autorun → app-owned service 把旧日期绑定报为 ALREADY_MATERIALIZED，随后真实 HTTP GET 为 STALE_INPUTS_CHANGED。 |
| `test_app_immutable_authority_read_clock_does_not_stale_plan` | RED | 完整 V2 六件合成工件、原 security-master writer、原 ResearchArchiveStore、原 issuer classifier 产出一张合成材料卡；source bytes 和 scope identity 不变，只改变 reader clock 即错误 stale。 |
| `test_app_persisted_availability_change_stales_plan_with_same_read_clock` | RED | 持久化 publication 的 available_at 07:02→07:03，重新由原纯 owner 哈希函数封装；仍为 OWNER_VERIFIED、仍在 cutoff 前、read_at 不变，但原基线 input identity 未变且 GET 错误 CURRENT。 |
| `test_scheduled_same_date_binding_keeps_run_without_rewriting`（MORNING/PREOPEN 各一项） | 2 PASS | 同日期同 kind 的原 scheduled owner 重复调用保持同 run 和 product SHA，无 manager 产品重写；GET 为 CURRENT。 |

三个 RED 独立到达业务断言；availability 不再被 read_at 的早期失败截断。它用于防止修复时同时丢掉真正的来源时间证据。

`CURRENT` 只表示保存产品与当前输入及 owner receipt 一致。本测试的无输入情况仍为业务 `PARTIAL`，合成材料例也保留原数据/PIT gaps，均不是全市场有效空或正式推荐。

## 根协调候选修复与独立验收

1. 在 `connect_selection.filter_cards` 的 membership_source 投影中只排除 `read_at`，保留持久化 `available_at` 与 `acquired_at`。外层 `selection_diagnostics.membership.source` 继续展示实际 witness clock。原 V2 source 验证、cutoff 和 membership 门槛不变。
2. 在 `workspace.refresh_workspace_plan` 的 scheduled reuse 条件中要求 `existing_workspace.get('date_bindings') == prepared.get('date_bindings')`。不匹配时继续原 owner 保存分支，创建新的 run/product/attempt；GET 的 stale guard 原样保留。

根已在独占候选 `four_function_gaps/work/repaired/app` 应用上述两处修改；本分工逐字节 review diff，只包含 membership 时间字段及其注释、scheduled reuse 的一个日期比较。随后使用独立新 basetemp 执行相同最终七项测试，全部通过。日志为 `candidate_seven_cases.log`，机器摘要为 `candidate_metadata.json`。

| 文件 | 固定 R2 SHA-256 | 候选 SHA-256 |
|---|---|---|
| `v4/manager_research/connect_selection.py` | `eaa01a13d8065b11cc8397a12edaad8b892f183158aa1f9475d29645dee09d83` | `238f608d8b130aaed6ecfeaea6a66550bf918045c82adeb9aa3ce4f7000ea291` |
| `v4/manager_research/workspace.py` | `a6225ef5583a73c066a5c31400f84e237aaceb63abefcf199cfb8c9b8af7dcdc` | `7a4875f1ab5ba46ac6c18bdaffe2c103a136734fda276fbee918163332844bb0` |

候选确认：相同 source 工件而 read_at 改变仍 CURRENT、同 input identity；合法的 persisted available_at 改变仍触发 STALE_INPUTS_CHANGED；错误日期绑定的 scheduled refresh 创建新 run，并使同日期 GET 回到 CURRENT；MORNING/PREOPEN 同日期重复仍保持同 run 且无重写；已有不同 reader/selection 的 stale 保护保留。所有检查保持四个 research safety flags，合成缺口及 natural_run_verified=false。

本分工未修改生产或候选源文件，也未建议重建 collector、producer、第二数据根或改变金融安全标志。候选源变更由根执行。

## 可复现命令与环境限制

```bash
PLAN_AUDIT_APP_ROOT=/workspace/scratch/0e089a11ee60/four_function_gaps/work/baseline/app \
PYTHONDONTWRITEBYTECODE=1 \
/workspace/scratch/0e089a11ee60/four_function_gaps/runtime_locked/bin/python -B -m pytest \
  -q -s --tb=short -p no:cacheprovider -c /dev/null \
  --basetemp=/workspace/scratch/0e089a11ee60/four_function_gaps/review/plan/tmp_baseline_identity_v3 \
  /workspace/scratch/0e089a11ee60/four_function_gaps/review/plan/test_app_plan_identity_audit.py
```

测试支持 `PLAN_AUDIT_APP_ROOT` 指向独立候选源码根；放在应用 `tests/` 后默认取父目录为应用根。最终单文件自带原 HK auditor 合成工件逻辑，直接调用应用原 V2 纯 builder、master/archive writers，不依赖 `review/hk`、原请求包或其他测试 fixture。需要 pytest、FastAPI TestClient 和完整项目原依赖。

候选命令与上述相同，只把 `PLAN_AUDIT_APP_ROOT` 改为 `four_function_gaps/work/repaired/app`，并使用新 basetemp `review/plan/tmp_candidate_identity_v1`。最终测试文件 SHA-256 为 `596a372bd9ff426e3b7468beb4d9fbdc94bb1b2e268e9ac975458ac4f0259ca9`。

- 实际源码根：`four_function_gaps/work/baseline/app`。20 份固定 R2 附件文件未修改；其余支撑从同 commit `a7f5d09fb19de10564925757207977aadc080cc1` 的固定 Git blobs 补足。关键源码 SHA 在 `baseline_metadata.json`。
- 实際 runtime：Python **3.12.14**；项目声明 **>=3.14**，因此保留环境偏差。根报告 31 项依赖与 `uv.lock` 一致，含 FastAPI 0.141.1、Starlette 1.6.0、httpx 0.28.1、pandas 3.0.6、pyarrow 24。
- App service 实际模块身份：`_v4_manager_research_runtime.service`；未拿普通 `v4` fixture service 冒充应用 owner。
- ASGI TestClient，无监听服务端口。测试禁止 socket 外连，source/state 均在 review 临时目录。
- 保留一次 Starlette 关于 TestClient(httpx) 的 deprecation warning。
- 导入支撑的 30 个通用 `_namespace.py` 是同 commit 原 527 字节 helper 的逐字节复制，仅 `ISOLATED_TEST_IMPORT_SUPPORT_ONLY`，详见 `work/import_support_adaptation.json`；不得声称为 Mac release 的完整运行身份。
- Matching review_router、manager package exports 与 API research_attention 的来源见 `work/api_support_alignment.json`。未改 Manager reducer/owner/router 方法来跳过实测。

前置错误原文另行保留为环境缺口，不算功能 RED：`ModuleNotFoundError: fastapi`（旧试跑 runtime）、`ModuleNotFoundError: stage_center._selection_parts._namespace`、`create_review_router() got an unexpected keyword argument 'hk_close_root'`、`_v4_manager_research_runtime has no attribute ManagerResearchJobService`。经根补齐以上支撑后才得到最终三个行为 RED。

扩充七项后的两次中间运行还观察到执行环境传输暂存文件短暂出现在目录快照，以及重用旧 basetemp 后已删除目录被同步恢复产生 FileExistsError。原日志 `baseline_final_behavior.log`、`baseline_verified_cases.log` 保留；最终测试排除非应用的传输暂存目录并使用新的独立 basetemp 后，四项正向全部通过，三个功能 RED 保持不变。应用 owned 文件、manifest、receipt、run 产品均仍参与前后 SHA 对比，没有忽略业务写入。

## 仍未执行的验收

Mac 真行情/owner state、实际 API 服务、UI、集成部署、自然时段以及完整仓库回归均 **NOT_RUN / CANNOT_CONFIRM**。日 capture、Reader、Reviewer、HK 精确日 authority/panel 缺口仍须各原 owner 补证。不能由合成计划或 code pass 宣称四功能恢复。
