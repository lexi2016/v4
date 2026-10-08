# Issue #30：实际 R2 API 切换入口的边界、补丁与隔离验证

## 1. 结论与交付范围

本批已对实际发布参考脚本制作精确候选补丁，把 **当前 active + 声明 delta 的完整库存验证** 和 **所有 API 发布者共用的指针锁** 接进 `execute` / `rollback` 内部入口，以及自动恢复和 active plist 写入点。保留 V4/8873 单一入口、整包原子切换和原 R2 业务证据约束；没有引入新 publisher、进程、端口或 producer。

修复独立审查 R5、R6、R7 后，最终候选通过 **76 个离线合成场景测试**：原 21 项不删不改，新增 41 项恢复合同/状态案例、9 项 JSON 入口案例与 2 项元数据案例，并将原审查 R5/R6/R7 探针按相同字节复跑各 1 项。初始候选 SHA `931a9e2749adee74ad4b7021b9f7451aaf9c905c586003250adec9cc14a9a364` 与其报告保留在 `initial/`。这证明的是发布边界与恢复状态机的源码行为。真实 R2 发布包、经理产品数据、Mac launchd、8873/API/UI 和自然时段均未运行。实际业务恢复仍为 `NOT_RUN` / `CANNOT_CONFIRM`；未安装候选、未调用服务命令、未改业务数据。

原脚本的包自洽校验不能证明保留当前 active 的业务修复。隔离探针复现了这一点：候选缺失 active 中的 `preselection.py`，并带有旧经理字节，原 `_load_candidate_release` 和 `_preflight` 仍给出 `READY_API_ONLY_R2_CUTOVER`。这是源码边界证明，不是对真实 R2 运行全流程的模拟验收。

## 2. 来源身份与安装目标

完整阅读的原文件为 1674 行：

- 输入：`input/baseline/source/actual_cutover_reference/api_only_cutover_r2_ready.py`
- 原 SHA256：`ddb7c5b5b95aed1e2e9fb8a592503b88ec3966f6e34c9350c47648bb0f97ce4a`
- 原实际源码路径：`/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_R1_MAC_20261008/completion_20261008/workspace_failure/staged/api_only_cutover_r2_ready.py`
- 候选：`candidate/api_only_cutover_r2_ready.py`，2092 行，SHA256 `389be853923a72066472ad229129a9a41ef9e9785f1b729aa468ed3e58df19f5`
- 精确前后 SHA、差异和测试身份另见 `CHANGESET.json` 与 `api_only_cutover_r2_ready.patch`。

**不把此脚本直接搬到 `ops/api_only_cutover.py`。** 原第 38 行按 `__file__.parents[3]` 计算 `TASK_ROOT`，随后大量路径和 SHA 绑定原经理任务布局；搬迁会改变运行身份。候选保留该计算方式以及所有原有顶层业务常量。AST 对比确认 47 个顶层 Name 赋值与 `sys.dont_write_bytecode` 赋值全部未变。它仍是对原 staged 入口的精确补丁，并未在 Mac 安装或接管任何文件。

唯一执行的项目 helper 固定为：

- 路径：`/Users/lexi/Desktop/学习/v4_app/ops/api_release_integration.py`
- SHA256：`1f4afc70d7e5920b67c2b148def6b9167819664c33c92b475d919a097b9dd050`
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

| 位置 | 最终候选行号 | 门禁 |
|---|---:|---|
| `_json_loads` | 166–180 | 所有 JSON 输入复用同一策略，保留键顺序，拒绝顶层/嵌套重复键与非标准 NaN/Infinity 常量。 |
| `_load_integration_guard` | 193–222 | 固定文件 → SHA → `compile(raw)` → `exec` 同一份已验 bytes；不从路径再次导入，不采用 `sys.modules` 的同名模块。 |
| `_require_release_lock` | 225–236 | lease 必须属于本次实际入口的注册事务，再由 core 验证锁持有状态。 |
| `_verify_api_integration` | 239–258 | 验证 candidate、base、delta、模块 ownership、非 delta 全库存及目录保留，并将 plist SHA 绑定本次 plan。 |
| `_verify_rollback_base` | 261–282 | 纯读校验记录中的 base、backup 字节、before identity 和指针 SHA；不要求旧 base 自带 v2 集成元数据。 |
| `_require_publication_paths` | 285–290 | `execute` / `rollback` 创建锁前，计划必须明确包含 active plist 和共享锁路径。 |
| `_preflight` | 777–850 | `active_pointer="base"` 验证；实际事务中 `require_shared_lock=True`。 |
| `_run_switch` / `_run_switch_locked` | 1824–1832 / 1835–1942 | 内部持有共享锁直到最终回读或自动恢复完成；第二次 preflight、bootout 前和 active 写入前重新验证 base/合同，沿写点传同一 lease。 |
| `_run_rollback` / `_run_rollback_locked` | 1945–1952 / 1955–2009 | 内部同锁；成功 receipt 的普通回滚仍使用 `active_pointer="candidate"` 全验证。中断续恢复使用不可变 prepared 合同与精确原 base 验证。 |
| `_create_prepared_transaction` / `_load_prepared_transaction` | 1523–1538 / 1570–1639 | 原操作内一次写入完整准备合同；续恢复核 exact bytes SHA、receipt 自身 hash、原操作路径与 plan hash，逐项对比可变状态记录。 |
| `_assert_prepared_transaction` | 1555–1567 | 动作边界重查准备合同 bytes 与本次来源 receipt 的精确 bytes 快照；不从修改后的状态记录采纳新 CAS 或 base。 |
| `_recovery_state` / `_verify_recovery_backup` | 1650–1681 / 1684–1696 | 已知 base/candidate/ABSENT 指针、严格显式 CAS、known/unloaded runtime，精确备份 bytes/metadata 与 base inventory。 |
| `_restore_after_failure` | 1699–1821 | 同一 lease 完成恢复；不要求 candidate 健康；停 job 前及写入/启动前重查；所有完成/失败状态保留原合同。 |
| active 写 helper | 1029–1065 / 1077–1103 | 无 lease 拒绝；只允许固定 `ACTIVE_API_PLIST`；最终 replace/link 前再次检查 lease。 |
| `_switch_lock` | 2031–2039 | 使用 active plist 旁的共享锁；注册的已验 guard 仅绑定本次 lease，退出时清除 lease 绑定。 |
| `_launchctl_action` / `main` | 748–759 / 2048–2088 | bootout 固定到现有 GUI uid + API label；bootstrap 仍用 active plist。续恢复返回 `ROLLBACK_INCOMPLETE` 时 CLI exit 2。 |

共享锁路径：

```text
/Users/lexi/Library/LaunchAgents/.com.lexi.v35.api-only.release.lock
```

原 inventory backend 的路径和 SHA 仍作为来源证据校验，但不再执行任务私有 `build_release_candidate.py`。库存计算由同一个已 pin 的 stdlib core 执行，保留原 regular-file inventory 的 hash schema，避免隐式引入未 pin 的 builder helper 闭包。

### helper 在事务中变化的恢复边界

补充 RED 用例证明：若已 bootout 后 helper 被改写，再在恢复时重新读取 helper 会使恢复被 SHA mismatch 阻断。候选改为使用**本次有效 lease 绑定的已验 module 对象**完成恢复；不执行被替换的 helper。下一次事务仍从固定路径重新检查 SHA，因此不会跨事务接受已变化的文件。`helper_change_red.log` / `helper_change_green.log` 保留了这一轮 RED→GREEN。

## 6. 正向、普通回滚与中断续恢复

| 场景 | 可接受 active 状态 | 必须验证 | 限制 |
|---|---|---|---|
| build/prepare/只读 preflight | 当前 base | 当前 plist + manifest + 完整 inventory；声明 delta 与文件/目录保留 | 不产生 live 写入授权。 |
| execute | 精确 base | 同一共享 lease、plan before SHA、当前 base、candidate/delta，bootout 前与写点前再验 | 不用候选自洽替代当前 base 保留。 |
| 成功 receipt 的普通 operator rollback | 精确 candidate，candidate runtime 已确认 | 已绑定的 prepared 合同、candidate 包和当前集成证明、recorded base、backup bytes/metadata | 保留初始候选的正常回滚门禁。 |
| 同一 execute 的失败恢复 | 精确 base / 精确 candidate / 缺失 | 本次 lease、已记录 base、精确 backup、受限 runtime；恢复前再验 base | 不重新要求 candidate 健康或 active 路径已存在。 |
| `PREPARED` / `ABORTED_BEFORE_BOOTOUT` / `ROLLBACK_INCOMPLETE` / `ROLLED_BACK_TO_PREIMAGE` 的续恢复 | 精确 base / 精确 candidate / `ABSENT` | 操作者显式当前 SHA，带自校验 SHA 的状态记录，原 prepared bytes SHA 与 plan 绑定，原 backup 与 base，动作前反复核对当前来源 receipt | 状态记录不能选择另一个 base；未知 pointer/runtime 一律拒绝。 |

原 R2 包没有 v2 的 base/delta 合同，候选应拒绝该包；没有为历史发布补造虚假 delta。旧 base manifest 只需满足已记录身份和完整库存要求，允许恢复。中断后的 candidate 可以损坏，因为续恢复只恢复原备份中精确绑定的旧 release；它不会对 candidate 做新发布，也不会把缺失/不健康 candidate 认作新的基线。

### R5 的根因与修复

初始候选在 candidate bootstrap 失败、自动恢复 rename 再遇临时错误时，会把 `operation_receipt.json` 覆盖成 `ROLLBACK_INCOMPLETE`。其中丢失完整 before/after/integration/base，虽然原备份完整，公开 rollback 仅接受成功状态，故故障解除后无法继续。原审查探针在初始候选 SHA `931a…a364` 上复现 `API_ONLY_ROLLBACK_RECEIPT_IDENTITY_INVALID`。

最终 `_run_switch_locked` 在任何 bootout 前，一次写入 `prepared_receipt.json`（独占创建、mode 0400、文件与目录 fsync），其中冻结：plan canonical SHA、原操作目录、before/after、candidate_release、经已 pin core 验证的完整集成证明、原 backup 路径/SHA/元数据，以及 scheduler/binding preimage。程序的后续状态写入从不覆盖该文件。`operation_receipt.json` 始终携带同一组合同字段，并以 `{path, sha256}` 绑定准备文件的原始字节。0400 和一次写入是程序纪律；不是对能够改写全部证据与计划的同 UID 恶意进程提供独立密码学签名。

公开 rollback 从当前 receipt 和 immutable prepared 各读取同一份已哈希 bytes，检查 JSON 自身 hash、原操作目录/备份固定名称、plan SHA、候选目标与 before 身份。之后只使用该准备合同中的 base/backup；还必须让 backup 的 plist bytes 与 plan before SHA 相同，且其中 release identity、实际 manifest 和完整 inventory 经 `verify_recorded_base` 再验。即使同时重算两个 receipt 的 hash，也不能用这些状态文件改成另一个 base 或不同当前 SHA。

续恢复每次建立新的 `-rollback` 操作目录，但引用的是原操作的 prepared 和 backup；成功与再次失败的记录都保留原合同、来源 receipt 的 raw SHA，以及本次操作者提供的 CAS。调用者可以拿返回的最新 `receipt_path` 再次重试，不必覆盖第一次失败证据。

原 `allowed_paths` 的 7 项原路径包含 `api_only_switch_runs` evidence 根；此前补丁只追加共享锁，构成 8 项精确列表。新的 prepared 文件就在原已授权 evidence 根内，不添加 live 写入目标；发布侧新增路径仍只有 active plist 旁的锁。

### 恢复入口与严格当前状态

沿用原 `rollback` CLI / `_run_rollback`，不增加 publisher。以下只是参数形式，尚未在 Mac 执行，也不授权直接运行旧 R2 plan：

```text
<原已审定 staged 脚本> rollback
  --receipt <原操作或最新重试的绝对 operation_receipt.json 路径>
  --confirm ROLLBACK_API_ONLY_TO_RECORDED_PREIMAGE
  --expected-current-plist-sha256 <当前精确 SHA256，或明确缺失时的 ABSENT>
```

`ABSENT` 只匹配不存在的指针；小写 `absent`、空字符串、过期 SHA，以及在已存在指针上使用 `ABSENT` 都拒绝。已知候选/原指针之外的任何 hash，即使操作者显式输入它，也拒绝。来源 receipt 在本次检查后变化会触发 `API_ONLY_RECOVERY_SOURCE_RECEIPT_CHANGED`；准备合同、backup 的 bytes 或元数据变化同样拒绝。

| Runtime 已确认状态 | 指针为 candidate、original 或 absent 时的动作 |
|---|---|
| 原 base job running 且 PID/身份完整 | 必要时恢复指针及已记录元数据，保留已知原 job，再核回读。 |
| 本次 candidate job running 且 PID/身份完整 | 同锁下 bootout 固定 API service target，确认 unloaded，恢复旧指针并 bootstrap 原 job。 |
| 明确 NOT_LOADED | 恢复旧指针并 bootstrap 原 job。 |
| UNKNOWN、LOADED_UNVERIFIED、第三个 identity 或缺 PID | 在服务/指针变更前拒绝。 |

动作边界再次发现 runtime 从 candidate 变成 original 会中止这次 bootout；最终报告恢复成功前还必须再次确认原 base runtime。恢复未完成返回 `ROLLBACK_INCOMPLETE`，并保留可续恢复 receipt，CLI 返回 2；成功返回 `ROLLED_BACK_TO_PREIMAGE` 和 receipt 路径/SHA，CLI 返回 0。没有 prepared 绑定的旧状态 receipt 不会被补造合同后接受。

### R6：重复 JSON 键不能被自校验 SHA 掩盖

R5 的独立复验对 SHA `1f41fe707ee7a24c0e2ba2143431d6c7c628ef9631b7b05e06f09fed415ff4c9` 得到 63 PASS，同时新发现可变 receipt 的 `json.loads` 会采取最后键值。向合法 receipt 前插另一个 `status`，原 canonical checksum 仍能匹配，公开 rollback 未拒绝。该原探针字节保留，针对已留存 `initial/r5_reviewed_api_only_cutover.py` 真实 RED。

最终新增 `_json_loads`，用 `object_pairs_hook` 在每一层拒绝重复键；同时采用与已 pin core 一致的 `parse_constant` 拒绝非标准 NaN/Infinity。`_read_json`、`_signed_receipt`、candidate manifest、binding、staged diff/plan、prepared、OpenAPI 和历史回读全部使用该入口，合法对象保留原键顺序。用于保留历史响应原始字节的 `raw_decode` 只在同一整份 bytes 已通过严格解析后定位切片；原 R3 source-order hash pins 不变。

R6 回归还覆盖：即使重写 prepared 文件的 raw SHA 引用，嵌套重复 base 键也拒绝；即使固定新的 binding raw SHA，重复 enabled 也拒绝；staging 不会把重复 before 的 plan 静默正规化后写回。未改变正常有效 JSON 的结构和序列化顺序。

### R7：已知原字节也必须恢复完整元数据

R5 版本会在 active bytes 已等于 before SHA 时跳过写入；独立探针把该指针 mode 改为 0777、保留 backup 0644，恢复仍误报成功。最终在该分支比较记录的完整 `_file_metadata`：uid、gid、mode、flags、mtime_ns 和 xattr SHA。出现差异时使用同一 lease 与当前精确 SHA 的 `_atomic_replace_bytes`，从已验 backup 恢复；无法安全复制的 owner/metadata 状态失败关闭。

bootstrap 前与最终返回成功前均要求 active metadata 等于已记录 preimage。原 job 已运行时只修复指针/元数据，不多做服务动作；若 bootstrap 后权限再次漂移，则返回 `ROLLBACK_INCOMPLETE`，保留相同 prepared 合同供后续显式重试。

### `launchctl` service-target 的手册依据

[Xcode 随附 `launchctl(1)` 系统手册的 HTML 导出](https://keith.github.io/xcode-man-pages/launchctl.1.html) 在 SUBCOMMANDS 列出 `bootout` 的 `service-target` 形式，并定义 GUI uid 与服务名构成的目标。其[导出仓库说明](https://github.com/keith/xcode-man-pages)标明来源是 Apple 随 Xcode 提供的 man pages。因此 adapter 使用现有固定 `gui/<os.getuid()>/<LABEL>`，缺失 plist 仍可针对已知 job；没有 domain-only 或外部传入 target。bootstrap 仍是原 GUI domain 与原 active plist 路径。

本次读取的是系统手册原文镜像；Apple 旧 archive `launchctl.1.html` URL 返回 404。argv 单测只证明代码生成这些固定参数，不能证明本机 `launchctl` 的版本、权限或行为已通过。目标 Mac 手册/launchd 实测、当前 GUI domain、真实进程终止与启动/readback 仍为 `NOT_RUN`。既有 `launchctl print` 文本解析依赖目标系统格式；不能解析时会进入 UNKNOWN/LOADED_UNVERIFIED 并拒绝，不能当作 NOT_LOADED。

## 7. 验证记录

最终环境：Python 3.14.7，pytest 9.1.1；Linux x86_64 / glibc 2.39。复用已存在的隔离测试解释器，没有安装依赖。明确设置候选/core 路径，最终 test 还独立检查候选源码 hardpin 等于本轮 core 的真实 SHA。

```text
CUTOVER_SOURCE=/workspace/scratch/25c09a595aec/issue30/work/cutover_analysis/candidate/api_only_cutover_r2_ready.py
INTEGRATION_SOURCE=/workspace/scratch/25c09a595aec/issue30/candidate/ops/api_release_integration.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
/workspace/scratch/25c09a595aec/issue28/references/work/test-venv/bin/python -B -m pytest -q -p no:cacheprovider
  issue30/work/cutover_analysis/tests
  issue30/work/cutover_analysis/test_actual_review_probes.py
  issue30/work/cutover_analysis/test_actual_duplicate_receipt_probe.py
  issue30/work/cutover_analysis/test_actual_preimage_metadata_probe.py
  --basetemp=/workspace/scratch/25c09a595aec/issue30/work/cutover_analysis/final_all_green_tmp
  --junitxml=/workspace/scratch/25c09a595aec/issue30/work/cutover_analysis/final_all_green.xml
76 passed in 12.28s; exit 0; no skip
```

前三行是同一个测试进程的环境变量；可复跑的单行命令记录在 `CHANGESET.json`。最终 76 = 原 21 + R5 新增 41 + R6 JSON 9 + R7 metadata 2 + 原审查 R5/R6/R7 各 1。原 `tests/test_actual_api_cutover.py` 以及三份原审查探针均按 SHA 比较确认字节未变。

| 证据 | 结果/意义 |
|---|---|
| `initial/` | 931a 初候选、报告、测试、旧 core 与原证据完整 checkpoint。 |
| `recovery_review_red.log` / `.xml` | 原 R5 探针在 931a 初候选 + 0b9 旧 core 上 1 FAIL：临时 rename 错误解除后，公开 rollback 因 receipt 身份拒绝。 |
| `recovery_cases_red.log` / `.xml` | 新增第一批 36 项在 931a 初候选 + 最终 1f4 core 上 36 FAIL；新接口/保留合同/明确恢复状态缺失，非被 mock 的成功。 |
| `recovery_green_initial.log` / `.xml` | 首个恢复版本 58 PASS：原 21、新 36、原 R5 1。 |
| `recovery_boundary_red.log` / `.xml` | 第一恢复版本 SHA `9ef4d39a1be5beef85b105619c0d0aef8f600d012fa3293699b2cb1f4359f9f3`（已留存 `initial/r5_first_green_api_only_cutover.py`）上 3 FAIL：停 job 前身份切换、最终原 runtime 校验、CLI incomplete exit code；其余 38 项未选。 |
| `recovery_final.log` / `.xml` | R5 阶段 63 PASS，包括上面 3 个修复、adapter 固定 argv 与 ABORTED 续恢复正常路径。其 source 1f41 已留存 checkpoint，不是 R6/R7 后最终结果。 |
| `r6_r7_review_red.log` / `.xml` | 三次审查中的原 R6/R7 两个探针对 1f41 共 2 FAIL，保留每个独立失败名与断言。 |
| `r6_r7_paths_red.log` / `.xml` | 新增 9 项 JSON 和 2 项 metadata 场景对 1f41 共 11 FAIL。 |
| `final_all_green.log` / `.xml` | 最终 source 389b + core 1f4 的全部 76 PASS（12.28 秒），含所有原探针与原 21 项。 |
| `RECOVERY_EVIDENCE.json` | 精简 RED→GREEN 汇总、精确输入/core SHA、失败名与最终测试清单；完整原始日志仍保留本地。 |
| `actual_red.log`、`helper_change_red/green.log`、`allowlist_red.log`、`actual_green.log` | 初始发布边界、当前事务 helper 缓存、共享锁 allowlist 的既有证据；其中 `actual_green.log` 是初始 21 项历史通过，不冒充本次最终结果。 |

最终场景真实执行 core v2 库存/差异/目录验证、R2 staged plist 生成、两次 preflight、写点前重验、共享 flock、plist 原子替换/缺失恢复、receipt、普通 rollback 和多次失败后的公开续恢复。launchd、HTTP、review evidence 使用原 fixture 的明确合成适配器，历史业务回读标记为 `SYNTHETIC_NOT_PRODUCT_ACCEPTANCE`。新增两个 CLI 场景只局部替换 `_load_plan` 为已构造的 synthetic plan，保留 CLI parser、入口、锁和恢复逻辑；另一个 adapter 测试只捕获 argv，不执行 subprocess。

真实 V4 应用全量测试、完整 R2 业务验收、Mac xattr/launchd、API/UI、自然时段与部署全部 `NOT_RUN`。实际运行身份 `CANNOT_CONFIRM_NOT_READ`。这 76 项不能外推为这些阶段通过。

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
