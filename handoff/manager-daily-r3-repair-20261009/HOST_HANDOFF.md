# R3：交给 Mac Luna Max / 原共享发布 owner

## 交接结论与权限边界

本包提供候选代码、定向合成测试、按源码角色生成的精确补丁和来源清单。Chat 未访问你的 Mac，未发真实 owner POST，未补采、读取或改写真实 plan/state，未启停、重载或部署服务。`IMPLEMENTED/TESTED` 与 `INTEGRATED/DEPLOYED/API/UI/NATURAL` 分开验收。

唯一目标仍是原链路每个适用交易日接续输入、形成可追溯计划并由普通经理页面读回。不要再把原采集成功、HTTP 200、候选 PASS 或单日手动成功当作每日业务已经恢复。

固定问题包：`b98d85c95d19780e2900dce7de9372328e67acf6`；共享父基线：`66bb05a2e12976775ccb997191ce943bae8cc9a5`。R1 `008649895054cb24f1d1c3df37e215d307615db3`、R2 `6a2fa48faf1da0a7d0d1715b3a4a40f55249b64c` 的必要累计增量已按各角色收进 after；选择正确 profile，一次应用。不要把 cumulative 和 R3-only increment 叠加两次。

## 1. 先锁定当前根，保留并行成果

复用原唯一共享 owner 和 Issue30 的 release lock/active-base/explicit-delta 流程。在锁内重读当时的 API、manager worker、HK child 和静态 web 来源、release manifest、plist、入口与模块 SHA。问题包的身份是 10/9 11:06 的观测，不代替接手时刻的读取。scheduler/API `launchd running` 也不证明某个 Python 模块已经加载。

| 角色 | 包内基线 | 处理方式 |
| --- | --- | --- |
| API | Issue32 `issue32_preselection_api_actual_r4/app`，其经理路径仍 R1 before | 在最新全量 API 根的隔离副本按 `api_current` 合入经理累计增量 |
| 已验 R2 API 候选 | R1→R2 累计经理候选 | 仅用 `api_r2_increment`；不是现役 API 的直接补丁 |
| manager worker | `manager-us-mapping-daily-20261006-r2/app` | 用 `worker_current`，保留与 API 不同的执行根 |
| shared scheduler | `issue32-preselection-scheduler-mac-20261009-r1/app` | 本包不修改 daemon/launcher，后续只由原 owner 更新经理绑定相关 pin |
| HK child | `r3a-r9-import-closure-20260930T193024Z/app` | 用 `hk_child` 的三件原 R1 重放；现存 namespace 保留 |
| HK02 updater | `20260923-hk02-owner-rebase-r2/app/upstreams/v3_shared_data` | 保留原 owner、脚本及库；不得放入 API consumer 假装补齐 producer |
| web | R1 web before（随后在 Mac 已构建 R1/R2 候选） | `web_cumulative` 只用于完全匹配的源码；已匹配 after 则直接复用 |

Issue32 必须保留：

| 文件 | SHA-256 |
| --- | --- |
| `apps/api/v35_api/app.py` | `5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5` |
| `apps/api/v35_api/preselection_router.py` | `718d54a6c6aa8cde2871ce4dc41cbc1d825f199a57b605e4f5ec70d8c4fe19ae` |
| `apps/api/v35_api/preselection_service.py` | `cbed3aa4797889051eb7bebe4b8e3240b568d72b4dfb5c20f65e914d39e48044` |

`workspace_daily_channels.py` 的新增 R3 修复以父提交中 Mac completion 的 API 源码 SHA `de4e91150d3198dda40e170660de8a83c717811d478411941015b7cf1364c15f` 为前像；它不在 R3 的 32 件实时快照里。因此必须额外核接手根实际 before，不可说该文件本轮已在 Mac 重读。如果任何 before 或保护文件不同，保留新旧双方和失败收据，按并行改动重新形成最小 delta，不覆盖、不刷新无关 pin。

## 2. 原共享 owner 先审查五条精确路径归属

`release_policy_review/` 是独立的政策源码候选，依据 R3 所附原 Issue30 `api_release_integration.py`，仅将以下五条精确路径登记为 manager 的共享依赖，不加目录前缀权限：

- `infrastructure/_research_peripheral_store_parts/_namespace.py`
- `infrastructure/scheduling/manager_announcement_supervisor.py`
- `ops/render_manager_announcement_binding.py`
- `ops/run_manager_announcement_cycle.py`
- `v3_shared_data/shared_data/hk_daily_supplement.py`

该政策候选不在 `api_current` 的业务补丁里，也没有自动应用器。原 api_platform/shared owner 先独立审查采用后，再由相同 owner 生成 `module=manager`、五条 exact `shared_paths` 的 delta receipt，使用采用后的 `POLICY_SHA256`。旧 receipt 仍绑定旧政策，不能重签成新身份。不能仅由调用方在 change-set 填入共享路径就绕过原政策拒绝。

保留原 active release 的复制、目录权限、before/after diff、共享锁与切换前读回机制。不要把 Chat 的测试树作为可部署的全量 app；它是选定原源码的合成测试装配，未提供完整可运行环境。

## 3. 独立源码验包和补丁核验

下列命令只读核验源码。变量必须由本机 owner 从实际观测填写，不复制旧根当当前根：

```bash
export manager_r3_package="/absolute/path/to/manager-daily-r3-repair-20261009"
export manager_r3_python="/absolute/path/to/verified/python"
export manager_r3_api_candidate="/absolute/path/to/new/isolated/api/app"

"$manager_r3_python" "$manager_r3_package/tools/verify_delivery.py" \
  --package "$manager_r3_package"
"$manager_r3_python" "$manager_r3_package/tools/verify_delivery.py" \
  --package "$manager_r3_package" --profile api_current \
  --source-root "$manager_r3_api_candidate" --against before
git -C "$manager_r3_api_candidate" apply --check \
  "$manager_r3_package/runtime/api_current.patch"
```

通过后仍由原 owner 的 delta/candidate builder 集成；以上 `git apply --check` 不替代共享发布合同。集成后的相同根用 `--against after` 核验，并独立运行本包 TESTING 中的原测试和 R3 定向测试。全量 web 继续用已恢复的完整本机源码执行 typecheck/build；Chat 没有把已缺的原 HTML 或旧 test fixture 造出来。

API、worker、HK child、web 分别核各自 profile。不能用 API 补丁覆盖整个 worker，也不能用 HK child 的现存 namespace 前像假装 R1 的“新增文件不存在”条件成立。

## 4. 一份 binding，两个真实执行身份

顶层 `app_root/files` 始终对应 manager worker。新的 `plan_owner` 对象对应真正提供 8873 原 owner 的 API 根：

```json
{
  "plan_owner": {
    "schema_version": "v4.manager_research.plan_owner_binding.v1",
    "owner": "ManagerResearchJobService.refresh_workspace_plan",
    "app_root": "<exact API app root>",
    "files": {"<actual closed source inventory path>": "<actual SHA-256>"}
  }
}
```

这只是字段示意，不能激活。源 inventory 必须由原 renderer 对两个最终源码根计算。保留旧 same-root binding 的严格兼容；双 root 缺少显式 owner 身份必须拒绝。不要取消 SHA 校验，也不要改成排除 root/enabled 的“语义哈希”。

新显式双 root canary 必须证明实际 `owner_execution_app_root` 等于最终 API root，且 `owner_source_inventory_sha256` 等于该根 `binding_inventory(API)` 字典的 canonical JSON SHA（UTF-8，ensure_ascii=False、sort_keys=True、separators=(',', ':')）。原 canary 的 `app_root/candidate_binding_app_root` 仍对应 worker。不得拿旧 root 的 `hook_executed=false` canary 或 migration 文档代替这项真实执行证明。

原 renderer 保留 plan-only 必须 enabled + 真实 canary 的门禁。因此先由原 owner 在已核验候选完成其原有手动 owner/canary流程，再渲染新文件；本包不会提供假 canary 或能够直接启用的填空配置。

```bash
"$manager_r3_python" "$manager_r3_worker_candidate/ops/render_manager_announcement_binding.py" \
  --app-root "$manager_r3_worker_candidate" \
  --plan-owner-app-root "$manager_r3_api_candidate" \
  --manager-state-root "$manager_r3_state_root" \
  --security-master-root "$manager_r3_master_root" \
  --python "$manager_r3_python" \
  --output "$manager_r3_staged_binding" \
  --enabled --plan-material-refresh-only --daily-automation \
  --plan-activation-receipt "$manager_r3_real_canary"
```

上述状态目录与 canary 来自本机 owner 的既有实际身份；不使用 Chat 临时测试目录或合成收据。渲染输出必须是新路径，保留旧绑定用于回退。

原共享 owner 准备切换时应使：

- `V4_MANAGER_ANNOUNCEMENT_BINDING` 与 `V4_MANAGER_PLAN_OWNER_BINDING_PATH` 指向同一原始 JSON，或逐字节相同的固定副本；记录完整 SHA。
- `V4_MANAGER_ANNOUNCEMENT_APP_ROOT` 是 worker 根；`V35_APP_ROOT` 在 API 进程中是 API 根，两者不要求相等。
- cycle、Python 与 canary pin 都对应最终候选的实际字节；只更新本次必要身份。
- 两端实际加载的 supervisor/dispatch/cycle 身份分别读回，不能只检查磁盘文件。

本包未执行这些生产配置变更。按原流程分开报告候选集成、实际部署、API、UI 与自然时段验收。

## 5. 先按原输入 owner 恢复，再做真实两日研究

详见 `HK_INPUT_CONTINUATION.md`。公告沿原 capture → Reader/Reviewer → owner import；US 沿原 04:15 source owner → 当日 mapping owner；HK 沿同次 capture → V2 membership/资格 → 原 HK02/main panel → security master/原超跌 owner。没有合法输入的通道独立保留原因。不要新建采集器、平行数据层或新的每日调度。

原 R1/R2 daily 分支保持原时间和预算：5 秒 US 准备预算、独立原 plan owner 预算、固定 same-day catch-up slots、跨日幂等和终态读回。当前自然 run 是否发起要查该分支的 dispatch receipt；scheduler 进程存在或 source receipt 成功都不够。

R3 两份现场 GET 的 `date` 均为 `20261009`，只有 selection/announcement 绑定不同；不能将它们写成已经实际读过 `date=20261008`。

### 10/8 事后产物

仅沿原 owner 在合法输入具备时执行。保留真实执行时刻、真实 available_at/retrieved_at、source date、cutoff，不回写成 10/8 盘前已知。只有实际保存后才要求 run/product SHA。随后显式使用：

```text
GET /api/v4/manager/research/workspace?date=20261008&selection_date=20261008&announcement_date=20261007&view=dynamic
```

核同日期、来源日期、source/input SHA、owner、run_id、product SHA、逐股理由和原通道状态。普通 `auto` 继续保留历史资格：存在合格历史 run 则读原 run；不存在则保留 `HISTORY_QUALIFIED_SAVED_PLAN_MISSING`。不要求 auto 消费本次事后 run。

### 10/9 当日产物

合法输入可用并由原 owner 保存后，普通页面默认 `view=auto` 应读回同一日期、run、产品 SHA、输入身份与逐股理由。刷新和重开原链接后再次核；GET 不应偷偷重算新的 run。明确 selection/announcement 日期并核页面的实际选择。

缺输入时保留 CANNOT_CONFIRM/NOT_RUN/NOT_IMPORTED 及原原因；输入完整且经原筛选为零时接受有来源、run、SHA、cutoff和淘汰理由的合法空结果。PARTIAL 诊断快照仍可保存，单一坏通道不阻断独立合法通道，未知候选数不能改成 0。

## 6. 连续自然日与回滚

真实业务完成需观察至少两个连续适用交易日的原自然链：dispatch → exact inputs → mapping/import/screen → original owner → sealed product → API → 普通页面。以原交易日历判定适用日，分别保留 HK 开市与 Connect 资格边界。10/8 手动事后计划不能计为自然日；10/9 手动检查不能证明下一交易日会自动运行。

每个日期记录前次产物的路径/SHA和本次幂等结果；再次读取旧日时其 immutable run 不变。任何 gate 拒绝应有具体稳定原因；网络超时只能说 owner outcome 未确认，不要自动重试生成重复计划。

候选未部署时，回退就是保留或弃用该隔离候选，现役无变化。部署后由原共享 owner 按保存的旧 API/worker/HK release身份、旧 binding 和对应 pins 成套回退，使用原锁和切换前核验；不以回滚代码为由删除或覆盖真实历史计划。Stage、BUY、Vibe8910、原 US source scheduler 和公告任务不得随本次回滚改动。

所有阶段保留：`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
