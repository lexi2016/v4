# Issue #30：实际 R2 API 切换入口的边界、补丁与隔离验证

## 1. 结论与交付范围

本批已对实际发布参考脚本制作精确候选补丁，把 **当前 active + 声明 delta 的完整库存验证** 和 **所有 API 发布者共用的指针锁** 接进 `execute` / `rollback` 内部入口，以及自动恢复和 active plist 写入点。保留 V4/8873 单一入口、整包原子切换和原 R2 业务证据约束；没有引入新 publisher、进程、端口或 producer。

候选通过 **21 个离线合成场景测试**。这证明的是发布边界与恢复状态机的源码行为。真实 R2 发布包、经理产品数据、Mac launchd、8873/API/UI 和自然时段均未运行。实际业务恢复仍为 `NOT_RUN` / `CANNOT_CONFIRM`；未安装候选、未调用服务命令、未改业务数据。

原脚本的包自洽校验不能证明保留当前 active 的业务修复。隔离探针复现了这一点：候选缺失 active 中的 `preselection.py`，并带有旧经理字节，原 `_load_candidate_release` 和 `_preflight` 仍给出 `READY_API_ONLY_R2_CUTOVER`。这是源码边界证明，不是对真实 R2 运行全流程的模拟验收。

## 2. 来源身份与安装目标

完整阅读的原文件为 1674 行：

- 输入：`input/baseline/source/actual_cutover_reference/api_only_cutover_r2_ready.py`
- 原 SHA256：`ddb7c5b5b95aed1e2e9fb8a592503b88ec3966f6e34c9350c47648bb0f97ce4a`
- 原实际源码路径：`/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_R1_MAC_20261008/completion_20261008/workspace_failure/staged/api_only_cutover_r2_ready.py`
- 候选：`candidate/api_only_cutover_r2_ready.py`
- 精确前后 SHA、差异和测试身份另见 `CHANGESET.json` 与 `api_only_cutover_r2_ready.patch`。

**不把此脚本直接搬到 `ops/api_only_cutover.py`。** 原第 38 行按 `__file__.parents[3]` 计算 `TASK_ROOT`，随后大量路径和 SHA 绑定原经理任务布局；搬迁会改变运行身份。候选保留该计算方式以及所有原有顶层业务常量。它仍是对原 staged 入口的精确补丁，并未在 Mac 安装或接管任何文件。

唯一执行的项目 helper 固定为：

- 路径：`/Users/lexi/Desktop/学习/v4_app/ops/api_release_integration.py`
- SHA256：`0b9d3b678dc7e875b9514bd8b66b7e8fc69229759c366ef0df776126746180bf`
- 接口版本：`v4.api_release_integration.v2`

路径和 SHA 不是 plan、环境变量或 import path 的输入。测试显式把这两个常量改为临时 fixture 路径及实际文件 SHA；生产候选不提供相应 CLI/环境覆盖。

## 3. 原脚本真正的发布边界

以下行号均指原 SHA 的脚本。该脚本没有名为 `apply` 的 CLI；正向切换的 CLI 是 `execute`，内部是 `_run_switch`。

| 入口/函数 | 原行号 | 实际作用与缺口 |
|---|---:|---|
| `_load_candidate_release` | 447–520 | 检查 candidate manifest、目标 inventory、任务源候选副本、frontend 和 staging receipt。没有读取当前 active app 的 manifest/inventory，也没有 base/delta 保留证明。 |
| `_preflight` | 654–723 | 比较 active plist SHA、元数据和 loaded identity；候选包自洽检查不等于当前集成基线检查。 |
| `_stage_api_plist` | 748–823 | 只写任务 staged plist/diff 和 plan；不写 live plist。它会读 launchd 和业务回读依赖，不能在真实机上被当作完全无运行读取的操作。 |
| `_run_switch` | 1452–1539 | 两次 preflight：1456、1491；1496 bootout；1503 再读候选；1505–1506 替换唯一 active plist；1509 bootstrap。 |
| `_run_rollback` | 1542–1590 | 原先也调用 `_load_candidate_release`（1558）。不能在该通用函数里无条件加入 `active_pointer="base"`，否则正常回滚时 current 已是 candidate，会被错误阻断。 |
| `_restore_after_failure` | 1354–1449 | 自动失败恢复和手动 rollback 共用。允许旧指针、候选指针、缺失指针；拒绝未知运行身份。 |
| `_switch_lock` | 1608–1620 | 锁位于任务的 `EVIDENCE_ROOT/api_only_switch_runs/.api_only_cutover.lock`；不是所有 API 发布者共用的锁。 |
| `main` | 1629–1674 | 原来仅 CLI 外层加锁；直接调用 `_run_switch` / `_run_rollback` / 恢复或写入 helper 不要求 lease。 |

### 所有 active/plist 写路径

| 写路径 | 原调用/实现行 | 写入目标 |
|---|---:|---|
| 正向替换 | 调用 1505–1506；实现 899–931，`os.replace` 在 921 | `/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist` |
| 自动或手动回滚替换 | 1402–1403 → `_atomic_replace_bytes` | 同一 active plist |
| active 缺失时恢复 | 1405 → `_create_preimage_exclusive`（943–964）；`os.link` 在 953 | 同一 active plist |
| staged plist/diff | 779–787 | 原任务 evidence 下两个 staged 文件 |
| staged plan CAS | 810 → `_atomic_write_json`（726–745） | 原任务 `PLAN_PATH` |
| preimage backup、preflight、operation receipt | 1471、1476、1478 及 `_record` | 原任务 `api_only_switch_runs` |

运行写入只通过 `_launchctl_action`：切换 bootout/bootstrap 在 1496、1509；恢复在 1393、1410。scheduler、Stage scheduler、disabled binding 和 manager state 的路径均未出现写入调用。API app 指针由 plist 中 `V35_APP_ROOT`、release identity、`PYTHONPATH` 和 `WorkingDirectory` 整体切换；没有独立的模块活跃指针。

## 4. 五个原缺陷/语义探针

命令：

```text
python3 /workspace/scratch/25c09a595aec/issue30/work/cutover_analysis/probe_cutover_boundaries.py
```

结果保存在 `probe_results.json`。全部输入、写入和故障注入位于本任务临时目录；不启动服务、不调用 `launchctl`、不访问 HTTP、不读实盘或业务数据。

| 探针 | 观察 | 结论 |
|---|---|---|
| 两个任务根、同一 active plist | 同任务第二把锁被拒；不同任务第二把锁在第一把持有时仍成功 | 私有 evidence 锁不能串行化 API 发布者。 |
| 旧候选缺少当前 active 的文件/修复 | 原候选加载与 preflight 返回 READY，无 `api_integration` | 当前基线和非 delta 保留不在原发布门禁内。 |
| 库存 backend 的 SHA 检查后换文件 | 校验旧 bytes 后，`spec.loader.exec_module` 执行新 bytes | 路径+SHA 检查后再从路径导入存在 TOCTOU。 |
| 最后 plist CAS 检查之后注入另一 publisher 的替换 | 本次 `os.replace` 覆盖另一 publisher，函数仍成功 | “先检查 SHA，再 rename”本身不是对不合作发布者的系统级 CAS。 |
| active 缺失的恢复 | 原 `_restore_after_failure` 恢复精确 preimage | 该语义必须保留；不能把 #28 另一套旧 recovery 的缺失路径缺陷混称为 R2 已发生。 |

旧候选探针真实执行了原 `_load_candidate_release`、`_candidate_plist_bytes`、`_staged_plist_diff`、`_preflight` 和库存算法；synthetic pins 替代了真实冻结字节。review、scheduler guard、launchd 身份和历史 HTTP 回读是明确的 test doubles。它不证明经理业务、真实 frontend 或 R2 独立验收通过。

## 5. 候选的实际接线

以下行号指本批候选，后续 reviewer 若改源码需重新生成行号/身份。

| 位置 | 候选行号 | 门禁 |
|---|---:|---|
| `_load_integration_guard` | 176 | 固定文件 → SHA → `compile(raw)` → `exec` 同一份已验 bytes；不从路径再次导入，不采用 `sys.modules` 的同名模块。 |
| `_require_release_lock` | 208 | lease 必须属于本次实际入口的注册事务，再由 core 验证锁持有状态。 |
| `_verify_api_integration` | 222 | 验证 candidate、base、delta、模块 ownership、非 delta 全库存，并将 plist SHA 绑定本次 plan。 |
| `_verify_rollback_base` | 244 | 纯读校验记录中的 base、backup 字节、before identity 和指针 SHA；不要求旧 base 自带 v2 集成元数据。 |
| `_require_publication_paths` | 268 | `execute` / `rollback` 创建锁前，计划必须明确包含 active plist 和共享锁路径。 |
| `_preflight` | 756 | 增加 `active_pointer="base"` 验证；实际事务中 `require_shared_lock=True`。 |
| `_run_switch` / `_run_switch_locked` | 1581 / 1592 | 内部获取共享锁并保持到最终回读或自动恢复结束，导入调用同样受保护。 |
| 第二次 preflight | 1635 | bootout 前重新验证同一 active 集成 base。 |
| active 写入前验证 | 1651–1656 | bootout 后，在 active plist 替换之前再次验证 base/delta 全库存，传递同一 lease。 |
| `_run_rollback` / `_run_rollback_locked` | 1695 / 1705 | 内部同锁，1726 以 `active_pointer="candidate"` 校验；只可恢复成功 receipt 中记录的精确 base。 |
| `_restore_after_failure` | 1472 | 同一个 lease；允许精确 base/candidate/absent 指针状态；未知指针在服务动作前拒绝。 |
| active 写 helper | 1008 / 1056 | 无 lease 拒绝；只允许固定 `ACTIVE_API_PLIST`；最终 replace/link 前再次检查 lease。 |
| `_switch_lock` | 1790 | 使用 active plist 旁的共享锁；注册的已验 guard 仅绑定本次 lease，退出时清除 lease 绑定。 |

共享锁路径：

```text
/Users/lexi/Library/LaunchAgents/.com.lexi.v35.api-only.release.lock
```

原 inventory backend 的路径和 SHA 仍作为来源证据校验，但不再执行任务私有 `build_release_candidate.py`。库存计算由同一个已 pin 的 stdlib core 执行，保留原 regular-file inventory 的 hash schema，避免隐式引入未 pin 的 builder helper 闭包。

### helper 在事务中变化的恢复边界

补充 RED 用例证明：若已 bootout 后 helper 被改写，再在恢复时重新读取 helper 会使恢复被 SHA mismatch 阻断。候选改为使用**本次有效 lease 绑定的已验 module 对象**完成恢复；不执行被替换的 helper。下一次事务仍从固定路径重新检查 SHA，因此不会跨事务接受已变化的文件。`helper_change_red.log` / `helper_change_green.log` 保留了这一轮 RED→GREEN。

## 6. 正向与回滚的语义必须分开

| 场景 | 可接受 active 状态 | 必须验证 | 不应要求 |
|---|---|---|---|
| build/prepare/只读 preflight | 当前 base | 当前 plist + manifest + 完整 inventory；声明 delta 与非 delta 保留 | 不产生 live 写入授权 |
| execute | 精确 base | 相同共享 lease、plan before SHA、当前 base、candidate/delta，bootout 前与写点前再验 | 不能用候选自洽替代 base 保留 |
| 成功后的 operator rollback | 精确 candidate | 成功 receipt、自身 hash、candidate 绑定、recorded base、backup 字节和元数据 | 不能要求 current 已等于 base |
| 同一 execute 的失败恢复 | 精确 base / 精确 candidate / 缺失 | 本次 lease、预先记录的 base、精确 backup、受限 runtime 状态；恢复前再验 base | 不能重新要求候选健康或 active 路径已存在 |
| 任意第三个/未知 pointer 或 loaded identity | 拒绝 | 保留失败证据 | 不能选择另一个“看起来旧”的包强行恢复 |

原 R2 包没有 v2 的 base/delta 合同，候选应拒绝该包；本批没有为历史发布补造虚假 delta。旧 base manifest 只需满足已记录身份和完整库存要求，允许恢复。若作为 operator rollback 的当前 candidate 自身已损坏，原入口的严格包检查仍会阻断这一独立操作；同次失败自动恢复则不依赖候选健康。这一范围区分是有意保留的。

## 7. 验证记录

环境：Python 3.12.14，`/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3`，Linux x86_64 / glibc 2.39。使用 stdlib `unittest`，没有安装依赖。

```text
python3 -m unittest discover -s /workspace/scratch/25c09a595aec/issue30/work/cutover_analysis/tests -v
21 tests; 0 failures; 0 errors; 0 skipped
OK
```

- `actual_red.log`：原脚本的 11 个新增边界测试失败，包含无 lease 的两种 active 写入和自动恢复未被拒绝。
- `actual_green_initial.log`：最初 8 PASS / 3 ERROR；3 个 ERROR 当时来自尚在改造中的 core 仍导入未提供的 `infrastructure`，不是被隐去的通过结果。
- `actual_green_scenarios.log`：stdlib core 接入后 19 场景通过。
- `helper_change_red.log` / `helper_change_green.log`：事务中 helper 变化导致恢复阻断的补充 RED→GREEN。
- `allowlist_red.log`：新增共享锁未列入旧 plan 允许路径时仍被创建的缺口；最终在创建前拒绝。
- `actual_green.log`：最终 21 场景全部通过，无跳过。

最终场景真实执行 core v2 库存/差异验证、R2 staged plist 生成、两次 preflight、写点前重验、plist 原子替换/缺失恢复、receipt 和手动 rollback。launchd 与 HTTP 仅使用合成适配器；review receipt 也是合成数据，历史业务回读明确标记为 `SYNTHETIC_NOT_PRODUCT_ACCEPTANCE`。

整个真实 V4 应用测试、完整 R2 业务验收、Mac xattr/launchd 运行、API/UI 和自然时段：`NOT_RUN`。本测试结果不能外推为这些阶段通过。

## 8. 当前交接未提供的实际依赖

下列路径属于原 R2 运行依赖；不以 canonical draft 的文件 SHA 冒充任务副本，也不猜测缺失 SHA。表中 `T` 指原实际任务根 `/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_R1_MAC_20261008`，`E` 指 `T/completion_20261008/workspace_failure`。

| 原路径 | 已知 SHA / 状态 |
|---|---|
| `E/staged/api_only_cutover_plan_r2.ready.json` | 未随本输入提供；完整原 plan SHA 未知。 |
| `E/staged/com.lexi.v35.api-only.r2.ready.plist` | 未提供；由原 plan 冻结的 SHA 未知。 |
| `E/staged/staged_api_plist_r2.ready.diff.json` | 未提供；SHA 未知。 |
| `E/api_release_r2_stage_receipt.json` | 未提供；原 plan 中 SHA 未知。 |
| `T/candidate/api/app/ops/build_release_candidate.py` | 任务库存 backend 未提供；实际 SHA 由原 plan 指定，不能采用 canonical draft SHA 代替。 |
| `T/control/pre_switch_product_baseline.json` | `c511e4c0241e7f98820aeba0e763a967223da1af454d14c6bac89c6fe8d49c31`；原脚本 pin，内容未提供。 |
| `T/review/p2_delta_independent_review.json` | `0cf607eecc19a73d21eafef653b69ff9f9716c286198de05c272f47aa5d58084`；内容未提供。 |
| `T/receipts/p2_delta_receipt.json` | `04535f6bc8c7b97cf585661c96b9327d3928876ffed314725dd2c8ea5f76b547`；内容未提供。 |
| `E/api_candidate_r2_inventory.json` | `ef048662f8da2efd48ed627d7b6f36b6752cf10de073be30f12c6fb52ddc4516`；内容未提供。 |
| `E/review/independent_review.json` | `f7dacbbc63be34388d37570ec885af8d1625d136ea367b29f16db7144d4f86d4`；内容未提供。 |
| `E/workspace_failure_business_fix_receipt.json` | `7054dde1e405e2e2bf87d162fab8ad8760e2fc2bb1f874fba0e42b20e0618a61`；内容未提供。 |
| `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-workbench-r1-mac-20261008-api-r2/release-manifest.json` 及其完整 `app/` | README 仅提供晚间 manifest SHA `2cc1447a740195c4f50299330d845635ddf762c45eb59586436a527e4f8b75a8` 和 1016 项库存摘要 `c371c633437e366d28549a94be35741e8d137d2a0836155695c9d125bb427f05`，未提供完整实际树。 |
| `/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist` | README 晚间样本 SHA `495a9be82e715979d59c03f5c4dd883a7570c55f15b72fa5ed309cacb3914356`；完整 plist 不在输入，不能当作接手时当前身份。 |

草稿 helper 原先依赖 `/Users/lexi/Desktop/学习/v4_app/infrastructure/interprocess_lock.py`，其 SHA 不在本批 `SOURCE_MANIFEST.json` 中。候选 stdlib core 已去除此运行依赖；这不是假定该历史 helper 的内容或验收状态。

## 9. 发布与 TOCTOU 的实际限制

共享 `flock` 约束参与同一协议的发布者。它不阻止不持锁的脚本直接 `cp`/`os.replace`，也不会使可被任意进程原位改写的 release app 自动不可变。候选在阶段边界和写点前拒绝观测到的漂移；仍要求所有正式 API pointer 发布入口统一接管，release app 按不可变产物管理。

本交接只包含一个实际 staged 切换脚本与若干 canonical 草稿，不能据此宣称所有未提供的历史 install/recovery/publisher 已被阻断。特别是 #28 的另一套旧工具不能被当作本补丁已经修复的入口。对应 owner 必须按路径和 SHA 完成全入口盘点与替换验收。

本批不应直接运行原冻结 R2 plan。真正的预选池恢复 release 必须从届时重新读取的 active 构建，保留经理当前内容，生成新模块 delta、候选、允许共享锁的新 plan、审定 pins 和独立证据；然后才由另行获授权的 Mac 发布者执行。保留 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`，不动 Vibe8910。
