# R3：原共享 owner 的 Mac 离线候选接续合同

本轮 API 交付采用**完整 R1/R2 API 后像、原 API HK consumer 修复，加 R3 增量**，保留 daily 行为及其必要共享依赖；不删依赖来绕过发布门禁，不修改现行 policy，不新增发布 owner。代码和合成测试以最终源码 manifest、测试回执为准；当前 **INTEGRATED / DEPLOYED / API / UI / NATURAL 均为 `NOT_RUN`**。这里的 API 指现场 API，合成路由测试另记。

## 1. 实际基底与保护文件

固定输入 commit：`b98d85c95d19780e2900dce7de9372328e67acf6`；R1：`008649895054cb24f1d1c3df37e215d307615db3`；R2：`6a2fa48faf1da0a7d0d1715b3a4a40f55249b64c`；共享基线：`66bb05a2e12976775ccb997191ce943bae8cc9a5`。

R3 `package/current_vs_candidate.json` 第 4–123 行记录的 API 根是：

`/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app`

记录的 release manifest SHA：`16675f6016d40e8a5eaf7b1e3e37694228364fae544e8a7b73e4bf17e1f5a9e6`。这是交接观察值；Mac 接续前必须重读当前 active identity，不得把旧 R1 API 根或 cloud 合成树当作现役累计根。

| 必须保留的 API 路径 | SHA256 |
|---|---|
| `apps/api/v35_api/app.py` | `5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5` |
| `apps/api/v35_api/preselection_router.py` | `718d54a6c6aa8cde2871ce4dc41cbc1d825f199a57b605e4f5ec70d8c4fe19ae` |
| `apps/api/v35_api/preselection_service.py` | `cbed3aa4797889051eb7bebe4b8e3240b568d72b4dfb5c20f65e914d39e48044` |

## 2. 已实测的 ownership 阻断

原 policy：`handoff/manager-daily-failure-20261009-r3/package/source_snapshot/issue30_release_policy/ops/api_release_integration.py`。

- 文件 SHA：`1f4afc70d7e5920b67c2b148def6b9167819664c33c92b475d919a097b9dd050`。
- policy SHA：`c55f4f09269661e0db05fa566aa1be9a96b2aa681912223c38fb802c4127e1b6`。
- 原文件第 36–38、573–603 行仅给予 manager 三个前缀：`domains/manager_research/`、`v4/manager_research/`、`apps/api/v35_api/manager_`。

已用原文件的 `module_scope`、`_validate_module_scope` 运行只读探针，退出码 0。实际命令 argv/stdin、Linux/Python 环境、stdout 及逐项结果见 [shared_owner_scope_audit.json](../evidence/shared_owner_scope_audit.json) 的 `probe`。下列路径均实测为 `API_RELEASE_MODULE_PATH_NOT_OWNED:<path>`：

| 待原 owner 独立登记的路径 | 记录的当前 API before SHA256 |
|---|---|
| `infrastructure/_research_peripheral_store_parts/_namespace.py` | `null`，必须确认原路径仍不存在 |
| `infrastructure/scheduling/manager_announcement_supervisor.py` | `73eb6a2f7cbf2e2307a87edc3013e355c331f2ce87e6e0ae693b9f78de2dd34a` |
| `ops/render_manager_announcement_binding.py` | `6d9f7a221df8ea8cdb0eb5e79a699f4a8f38459dbf1c4c1742b7550b8da0cc4a` |
| `ops/run_manager_announcement_cycle.py` | `c6f9cfa57515682b4f076e10f2030196dc9377bdbb9ec4abe737e36d15485c1c` |
| `v3_shared_data/shared_data/hk_daily_supplement.py` | `5528a6b44bfb5b79265732b85beb1fb89860355b48a852da07264fb34231c79c` |

这些 before 属于 API 根；HK 行是 API consumer，不是 HK 0.2 updater。最终 after、全部经理文件 before 及 R1 复用后像见最终交付 manifest/审计 JSON；模式必须现场核实。将 cycle 填入 `shared_paths` 实测为 `API_RELEASE_MODULE_SHARED_PATH_NOT_ALLOWED`。source allowlist 和 explicit-untracked 不能替代 ownership；**登记 JSON 本身也不能使现行 policy 放行**。原唯一 owner 必须通过既有审查流程关闭实际执行的权限门，本轮不得自行放宽。

完整 R1 dispatch 第 330–337 行传入 `daily_config/daily_branch/scheduled_slot/trigger_id/us_market_request_context`；当前 API runner 第 272–275 行没有这些参数。R1 dispatch 第 476–493 行还依赖新版 `daily_automation_config` 和 daily 分支。因此保留全部 R1 manager 后像却省略共享依赖不是可运行候选。

## 3. 原 owner 下一步最少动作

1. **读回并钉住输入。**核 active API plist、根、manifest、完整 inventory、逐项 before/mode、三个保护 SHA；核当前共享 builder/check 的绝对路径、SHA 和 source allowlist。固定仓库只附 policy，未附现行 `create_api_module_delta.py`；已找到的 builder 仅 20261005 旧快照，不能冒充现行入口。
2. **关闭共享登记门。**为上表五项登记实际根、必要性、精确 before/after/mode 和原 owner 审查结果，并确认实际 policy/正式入口能够验证授权。未关闭时只允许隔离 prepare/check，保持集成门 `BLOCKED`，不产出“可发布”结论。
3. **建立新隔离候选。**非部署 helper 可检查 payload、前像、路径/symlink、模式与登记证据；候选从实际当前累计 API 基底保留全部非 delta 字节，仅覆盖 manifest 明列的完整 R1/R2 API + R3 运行时增量。禁止用旧整树覆盖；tests、文档、原始数据、state 不进入 runtime delta。旧 `initialize_api_web_candidate.py` 第 17–19 行硬编码旧 API 根，不可原样执行。
4. **验新候选。**按最终 after SHA 重跑针对性测试，核新 manifest/delta SHA、目录模式、非 delta inventory 和保护 SHA。共享原入口使用 `build_integrated_app` / `verify_api_release_candidate` 的相应门禁；基底有漂移就停下重做增量，不能回退并行修复来匹配旧 before。
5. **保持真实身份。**scheduler 当前 worker 为 `manager-us-mapping-daily-20261006-r2/app`，不是 API 根；其 cycle/supervisor/dispatch SHA 单列在审计 JSON。由原 owner 准备同版本 binding 输入，分别核 worker、API、state/master、解释器、enabled、canary 和文件 inventory；不得临时改 binding 的 root/enabled 来通过验证。本轮不写生产 binding 或 LaunchAgent，不重启服务，不发真实 owner POST。

## 4. 其他 R1/R2 profile 的接续

R1 的 web、actual HK child、HK upstream，以及 R2 的 web 增量继续按原固定候选复用；本轮没有这些实际最新根的完整可应用前像，不把它们并入 API/worker 补丁。完整逐项引用见 `../prior_candidates.json`。原 HK child 的 namespace 有并行冲突，R1 HK supplement 仍有一个已记录的 P2 行为验收限制；均须由对应的既有 owner 按最新根逐项合并与验证，不能以本轮 API 合成测试视作关闭。普通页面现役源码、构建和 UI 同 run/SHA 验收仍为 NOT_RUN。

## 5. 正式 delta 格式与回滚

审计 JSON 的 `manager_owned_subset_delta_template` 给出原 `v4.api_release_delta_receipt.v2` 格式，`module_scope` 为：

```json
{
  "module": "manager",
  "shared_paths": [],
  "policy_sha256": "c55f4f09269661e0db05fa566aa1be9a96b2aa681912223c38fb802c4127e1b6"
}
```

这个 subset 的 ownership 已核，但模板含待填值，**不是完整交付的发布许可**。上表未拥有路径单列 `pending_owner_registration`，不得塞入该 scope。正式 receipt 必须有准确 base、排序 entries、before/after SHA 与 mode；修改文件有规范 diff SHA/hunk count，新增文件的 before/mode/diff proof 为 null（原 policy 第 620–665 行）。

未部署候选失败时保留失败回执和候选，不覆盖重跑、不动 active。未来若需部署后回滚，只能由原 owner 用原共享锁核当前指针及不可变记录基底（`verify_recorded_base` 第 544–570 行），撤销获准增量，保留并行修复和历史 run/attempt/state。

## 6. 业务验收边界

10/8 事后产品用显式 `view=dynamic`；普通 `auto` 保持历史资格。10/9 已保存当日计划才要求 `auto` 同日期/run/SHA/输入身份读回。合法输入缺失保留 `CANNOT_CONFIRM` 与具体原因，不造 run 或股票；完整合法输入筛选为空可保存可追溯空结果。fixture、HTTP 200、旧 canary 的 `hook_executed=false` 都不证明真实业务运行。

安全 flags：`RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。现场 **INTEGRATED / DEPLOYED / API / UI / NATURAL：全部 `NOT_RUN`**，待原唯一 owner 分层验收。
