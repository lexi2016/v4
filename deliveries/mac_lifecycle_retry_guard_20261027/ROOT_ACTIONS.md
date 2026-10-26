# Root 接入动作 · 待一次独审与协调

本文件是候选动作，不是已执行回执。Writer 未更改现役、plist、服务、权限、数据、admission。固定 Python：`/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python -B`；两旗 `PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1`。

## 先决与保留

1. 一次只读独审覆盖 `IDENTITY.json` 引用的源码差异、15 checks、单股/21证据、000523原envelope、严格shim、三个完整候选和本控制边界。不得重复76全量/公式/采集。
2. Root 安装前重新读取现役 owner/manifest/plist。任何 pin 漂移停止，保留本候选并作受影响增量，不用本文件旧SHA覆盖后续 owner。
3. 旧R1 API包/失败日志、旧a_daily、旧Main、旧Graph配置、76 admission及原失败均保留。不要执行本目录 `api_cutover.py`：它是已发生CAS首错的旧基线控制，fresh R2不能使用它。

## 不活动物化

只在独审PASS后可做；目标均必须不存在。复用 Graph 原 `writer/operator.py::stage` 的临时目录→逐文件核对→原子rename方式，不改旧release。组件物化时必须复制整个 `component_package/mac-lifecycle-retry-component-20261027-r1`，不是只复制shim；核对外层manifest的每个files相对路径/SHA、严格component15 pins、seed/preimage、所有路径不得symlink逃逸。Main复制整个 `main_package/mac-lifecycle-main-binding-20261027-r1`，其881物理文件（880原应用文件及原bookkeeping）逐字节原样。物化Main时manifest不再替换路径：已声明future target、原prepared source另保留。

精确源/目的见 `control/COMPONENT_PACKAGE.json`、`control/MAIN_METADATA_PACKAGE.json`。Main manifest `702208bc93b97380a1180a740674f2d1e9bae987852737e234ea8223c6094d03`；组件外层 `abd3ecf3da0b4d7532e99de18072e8a72872e2981a51958d618cfcdb07805fe6`。只物化不使运行中的scheduler获得新env。

API fresh R2由1319现役完整文件+2差异组成，1317非delta及6 Graph改动保全。源 `api_package/mac-lifecycle-notes-21-api-20261027-r2`；目标同名release位于原releases根。目标manifest必须使用 `control/release-manifest.fresh-r2.materialized.json`，SHA `ddbac24cc87b88ac0ef6b7ba2f62105f6d42ecb0de87bb74646467bcc7ff8173`，本地candidate manifest SHA `1193461b755b02af8f1012a94754b3f1247fb796fb13a96dba42e59716d06236`。仅candidate.root/app_root从本地投影到目标；application_inventory的精确entry_count=1319。实际目标原dispatcher需在物化后用目标四身份环境再读回一次；不得改dispatcher或放宽identity。

## API安装接口缺口 · 当前不能直接执行旧控制

当前API基线manifest `c4f1c68c8f0b2dcf9ed98949146ced5b3aafaa67beadbb3c0b1e847e4e811a59`；plist `ec095bb5615452c116e79d78f35a0c75e34cf4b67788d8a1dfe32b509354e550`。当前schema是 `v4.runtime_graph_repair_release.v1`；原 `api_release_integration.read_active_release/verify_api_release_candidate` 严格拒绝它。fresh标准候选没有虚构api_integration收据；不能以旧Futu标准包充当当前active或扩大allowlist绕gate。

原owner机制已冻结于 `IDENTITY.json.owner_original_mechanism`：`V4_RUNTIME_GRAPH_REPAIR_20261026/API_REBASE_R1/compose_api_rebase.py` 与 `writer/operator.py`。后者 `verify_release`/`install_plist`/`validate_api_observation` 是真实原入口。Root需与该owner明确沿其现有控制使用本fresh完整树、标准identity输出和其Graph验收；不扩为另一发布系统修复。其config有 `MANAGER_WORKBENCH_API.module_file` 精确旧API path；新API root若变化，这一对应也须由owner协调。仅保全模块SHA不足以冒充新path已生效。

可审查fresh plist：`control/api-only.fresh-r2.candidate.plist` SHA `128dbb3c992f87fe3917c9aeebbdaf44d1d30a0cf5c1922121db70f3ffdb19d9`。除4身份、PYTHONPATH对应前缀及WorkingDirectory外，全部原值相同，包括Graph配置和76数据环境。现阶段Graph旧path有明确协调缺口，故这份plist不是单独充分的安装计划。

原API共享锁 `ops.api_release_integration.shared_api_release_lock(api_plist,timeout_seconds=2)`，锁文件 `.com.lexi.v35.api-only.release.lock`；原 `announcement_flash_cutover_guard(manager_workbench_root,timeout_seconds=10)` 必须保持。锁内fresh plist/manifest/inventory CAS、目标完整inventory校验后才可沿既有API-only操作；任何busy/owner不能确认即不切。先退出旧API且确认8873无监听，再bootstrap候选；本批Writer未执行。新API原date-list必须回报原dispatcher强identity，并用新ownerGraph原proof验证PID、模块path/SHA、Main/config对应，不能只assert HTTP200。两券商HTTP说明应有事实、无伪bar且原错误保留；000523只需既有六日最小读回，不重算。

## Main共享scheduler · 必须最终问题

现役Main manifest `2ed2da9abc77280da40f0f6f2cf9f0401759d517b7272b30c6ea3f5053cef031`；scheduler plist `7474ae90d8e29fe3677ca90301d902168984c0ee5690a0a0dbe187450b72793b`。完整新Main候选plist `control/main-scheduler.candidate.plist` SHA `7c2b762a7c22dc851d385f15519b0fd8e02bcae6eb72c76aa3cb51a1157a71b6`。业务唯一标量是 `V35_RESEARCH_PANEL_A_SYNC_SCRIPT` → 新固定入口；为保持清单identity一致，另必须对应4身份/PYTHONPATH/WorkingDirectory，其他env/参数/健康lane全保留。早先 `scheduler.candidate.plist` 只有单标量，已被完整Main方案取代，不执行。

原安装入口是 Graph `writer/operator.py::install_plist(row)`：要求 `label_state(com.lexi.v35.scheduler) is None`，loaded即拒绝；按beforeSHA备份，原子CAS前再读expected，afterSHA受pin。没有“只改文件即可热生效”合同。原 `ExecutionLedger.try_acquire_scheduler_lane` 使用 `scheduler_lane_owners/A_LONG.lock` 与 `DEFAULT.lock` 的稳定inode/inherited FD，busy不能unlink/reclaim/kill制造idle；slot claim/receipt还受 `_slot_blocks_retry`。Root先沿原controller读取实际daemon/子进程、两lane与claim owner，待自然idle；不取消健康工作，不把历史空闲当fresh空闲。

新Main root还影响当前Graph config.main/authority path，该对应由原owner协调，不擅自改collector/config。最小问题应同时明确：是否授权在自然idle、原owner/锁/CAS一致时，对共享scheduler执行一次受控unload/bootstrap，并由原Graph owner更新必要的Main/API path绑定？在答案前只允许不活动物化，不能reload或新造动态旁路。

实际生效必须读回新PID/start、cwd、launchctl已装env的新固定entry及新Main四身份，原dispatcher与原调用模块path/SHA；自然1530 A槽或原已授权等价执行必须证明21 lifecycle_skips、provider前guard、原target/accepted/quarantine/5000不变。候选零调用不冒称自然日更已完成。其他lane原状态照旧，不宣称Graph整体PASS。

## 回退

物化但未绑定：无需删新目录，现役不变。切换后需回退时，在原owner/锁和自然idle允许边界内，用精确afterSHA逆CAS恢复 `main-scheduler.before.plist`/`api-only.fresh-r2.before.plist`，沿原API-only或已获授权的scheduler单次bootstrap；保留候选、新release和失败。Graph协调对应一并按其原收据逆CAS。验证精确旧plist/manifest、同PID cwd/loaded bytes及旧Graph实际能力，不能把旧custom schema的CANNOT_CONFIRM伪报为标准dispatcher PASS；新旧admission不写不删。新数据/原失败未改，无数据回滚动作。
