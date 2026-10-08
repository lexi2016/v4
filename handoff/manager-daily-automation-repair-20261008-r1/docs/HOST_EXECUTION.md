# 受保护集成与本机验收执行入口

本文件是代码交付的执行交接。当前轮没有在 Mac 执行采集、POST、启停、启用或部署。以下正式运行步骤由 Issue #30 的唯一集成 owner 在受保护的新累计基线及相应授权下执行；它们不是已完成回执。

## 1. 确定本轮真正应用的文件与根

先读取 `source_manifest.json` 的每条 `profile/path/before_sha256/after_sha256/after_path/patch_path`。`before_source_basis` 区分 actual 来源和仅供隔离测试的仓库前像。两项 `0602f34` 修复仍未部署，因此 workspace/history 提供 **旧 R2 → 本轮合并结果** 的补丁，并另留相对已验候选的增量；不得假定现场已安装上一包。

路径变量由集成 owner 根据当前进程、配置及 release manifest 绑定为真实绝对路径：

- `manager_handoff_root`：本交付目录。
- `manager_api_root`：当前 8873 对应的受保护累计 API 候选根。
- `manager_web_root`：实际完整普通经理页源码根。
- `manager_hk_child_root`：原调度选中的实际 HK child 候选根。
- `manager_hk_package_root`：`resolve(actual V35_RESEARCH_PANEL_HK_UPDATER_SCRIPT).parents[1]`；核实际 supplement `__file__`。
- `manager_scheduler_root`：当前原 scheduler 的实际候选根，供原层的保留校验及 hook 身份核验。
- `manager_evidence_root`：已有的本机验收输出目录，在以上源码根之外；完整业务数据不上传。
- `manager_python`：该原入口要求并由现有 canary/source gate 核过的实际 Python。原公告 worker 要求 Python 3.14，不用任意系统 Python 代替。

`tools/verify_delivery.py` 是 stdlib 只读验证器：每次核全部 after 文件以及全部 patch / incremental patch 的 SHA 和字节数，再核所选 profile 的源文件，拒绝不符前像、非正规文件和符号链接，不改源码、配置或服务。前像为 null 表示要求现场缺失；若现场已有不同 namespace，交集成 owner 对齐，不能覆盖。仅执行最终 manifest 中有 file 或 preserve records 的 profile；空 profile 会明确拒绝，不应为了通过而补造现场 pin。

```bash
python3 "$manager_handoff_root/tools/verify_delivery.py" \
  --source-root "$manager_api_root" --profile api --against before \
  --report "$manager_evidence_root/api-before.json"

python3 "$manager_handoff_root/tools/verify_delivery.py" \
  --source-root "$manager_web_root" --profile web --against before \
  --report "$manager_evidence_root/web-before.json"

python3 "$manager_handoff_root/tools/verify_delivery.py" \
  --source-root "$manager_hk_child_root" --profile hk_child --against before \
  --report "$manager_evidence_root/hk-child-before.json"

python3 "$manager_handoff_root/tools/verify_delivery.py" \
  --source-root "$manager_hk_package_root" --profile hk_upstream --against before \
  --report "$manager_evidence_root/hk-upstream-before.json"

python3 "$manager_handoff_root/tools/verify_delivery.py" \
  --source-root "$manager_scheduler_root" --profile scheduler_prerequisite --against before \
  --report "$manager_evidence_root/scheduler-preservation-before.json"
```

不要在一个混合根上使用 `--profile all`。验证器不代替 Issue #30 的并发发布锁、基线 CAS、模块 ownership 与 #28 保留验收。对当前应用有合法漂移的文件，应在新累计候选中合并差异并重新审查，不能为匹配本包 SHA 回退受保护的新功能。

仅按 manifest 的有限文件清单应用已经核 SHA 的补丁，合并后以 `--against after` 和新的 report 文件名再次核验。验证工具另检查每份 patch 的确切目标路径与完整临时文件集合，实际包的通过结果以 evidence/package/patch_verification.json 为准；现场仍应审实际 git diff，确保没有额外路径。完整新基线执行本包测试清单、真实依赖导入/构建、经理功能及 #28 预选池联合验收，保存实际加载身份。问题包不是完整依赖闭包；Stage 或原页面缺失依赖须从实际应用核明，不得创建测试替身后称完整入口通过。

## 2. 原调度绑定与启用条件

沿用现有 AnnouncementCycleHook、原公告 worker 和同一个注入式 8873 service。新的 daily 配置通过原绑定校验；不另设 daemon 或 cron。06:30 原公告任务继续由原 owner 负责。MORNING、PREOPEN、EVENING_NEXT_SESSION 保留，有限 SAME_DAY_CATCHUP 由原日历和 slot 规则决定。

先核当前原 hook 如何加载 `V4_MANAGER_ANNOUNCEMENT_APP_ROOT` 和执行同根 `ops/run_manager_announcement_cycle.py`，并确认 scheduler 的 binding 路径与 API 的 `V4_MANAGER_PLAN_OWNER_BINDING_PATH` 指向同一个经过 SHA 校验的文件。实际 scheduler hook/daemon 的加载身份另留证据，不能用配置文字替代。

本轮 supervisor、worker 和 renderer 归 `api` profile。若现场 API 与 bound worker 实际采用不同应用根，由唯一 owner 在两根分别核相同 helper 闭包及当前前像；`infrastructure/scheduling` 这一目录名本身不要求另向 scheduler 根复制 supervisor。`scheduler_prerequisite` 在本包仅核原 scheduler workloads 保留 pin，不提供替换配置，也不证明其中原 US 任务已启用。

合法原 owner canary 及来源迁移证据通过原校验后，新的 renderer 可生成 **enabled 的 daily 配置**。下列命令只生成配置文件；本轮没有执行它，也没有替代真实 canary 生成任何通过回执。

```bash
cd "$manager_api_root"
PYTHONPATH="$manager_api_root:$manager_api_root/upstreams" \
  "$manager_python" -m ops.render_manager_announcement_binding \
  --app-root "$manager_api_root" \
  --manager-state-root "$manager_state_root" \
  --security-master-root "$manager_master_root" \
  --python "$manager_python" \
  --enabled --plan-material-refresh-only --daily-automation \
  --plan-activation-receipt "$manager_plan_canary_receipt" \
  --output "$manager_candidate_binding"
```

`policy_status=PROPOSAL_ONLY` 保留原研究策略语义，不等于 enabled=false。真正启用仍须依照原 canary、source inventory、Python/root/binding 和共享发布 gate。确认 actual US 采集任务及原审核产品生产链能持续供源；见 `INPUT_AND_RUNTIME_GAPS.md`。现役 US workload disabled 和 missing actual executable 不能被 canonical 配置掩盖。

上面的 cwd 和限定 `PYTHONPATH` 是命令的一部分：renderer 在解析 `--app-root` 前就导入 supervisor，不能继承旧 release 的导入根。原源码缺失的 marker 或 Stage 依赖需要实际来源核验，不能通过造空文件或 shim 让命令通过。

## 3. 真实 10/8 事后补算

完成受保护集成并取得正式运行授权后，以下两个入口依次调用 **原 US owner** 与 **原 plan owner**。不传入股票、源码、客户端时间或研究决定。服务端记录真实执行时间，目标 10/8 与研究 cutoff/source session 分开核验。这两个 POST 不执行 HK capture/gate，也不生产公告审核产品；先沿原 owner 核对真实 10/8 同次 HK 发布链和原 reviewed 输入，缺失部分保留缺口，不能把两次 HTTP200 当作三路输入都已补齐。

```bash
curl --fail-with-body --silent --show-error --max-time 15 \
  -X POST -H 'Origin: http://127.0.0.1:8873' \
  'http://127.0.0.1:8873/api/v4/manager/research/workspace/us-mapping/refresh?date=20261008' \
  -o "$manager_evidence_root/20261008-us-retrospective-response.json"

curl --fail-with-body --silent --show-error --max-time 45 \
  -X POST -H 'Origin: http://127.0.0.1:8873' \
  'http://127.0.0.1:8873/api/v4/manager/research/workspace/refresh?date=20261008' \
  -o "$manager_evidence_root/20261008-plan-retrospective-response.json"

curl --fail-with-body --silent --show-error --max-time 40 \
  'http://127.0.0.1:8873/api/v4/manager/research/workspace?date=20261008&selection_date=20261008&announcement_date=20261007&view=dynamic' \
  -o "$manager_evidence_root/20261008-workspace-readback.json"
```

`--max-time` 只是客户端等待上限；它不撤销已经开始的原 owner 写入。若客户端超时或 HTTP409，不立即重复 POST。先只读核 dispatch、run、pointer 和原 immutable attempt，区分未开始、仍在执行、已保存未读回或失败，沿原恢复机制处理。

API HTTP200 不是通过条件。逐项核 target、source session、真实 cutoff、原输入 SHA/availability、run/SHA、同 run 的 immutable attempt、consumed，以及各路股票和原理由、缺口、已知数量或 null。target10/8 若在10/9执行，US daily 仍应精确读10/7；页面上原 raw US attention 与 target-bound daily mapping 的 as-of 范围分别显示。10/8晚间研究不倒签成10/8盘前。

在普通页面重新加载：

`http://127.0.0.1:8873/manager-selection/?date=20261008&announcement_date=20261007&plan_date=20261008`

普通页默认的“读取口径”为 `auto`。如果执行已在 10/9，打开 10/8 会先读取合格的当时历史；事后补算不具备盘前历史资格。核验本次补算时，在现有“读取口径”选择 **“现在回看（可能含后续消息）”**，使页面发出与上方 API 相同的 `view=dynamic` 请求。另行保存默认“当时历史 / 当日预览”的真实读回；`HISTORY_QUALIFIED_SAVED_PLAN_MISSING` 与事后计划是否保存是两项判断，不能改写历史资格来消除前者。

逐路核股票、原入选理由、source/target/publication 日期、运行状态、缺口、run 引用与计划保存。更换 plan、selection、announcement 日期，包含同 plan 日只改 publication 的请求以及失败响应，确认旧股即时清除且不串日。保留“已有保存计划”与“后来失败尝试”的区别。实际截图/操作时间和 API/run/SHA 关联保存在本机。

## 4. 跨日与连续自然验收

隔离固定日期测试仅证明对应代码行为。正式自然验收需先由原 HK 证券日历确认至少两个连续适用交易日；US 和 Connect 资格日期分别核对。不得以人工调用 `/workspace/daily-cycle` 制造自然运行证据。

每个自然日读取：原自然 scheduler dispatch/slot → 当天原输入 receipts → daily US/plan owner receipts → 同 target 的不可变 run 与 pointer → 原 plan product/同 run attempt → API GET → 普通页重载。记录真实 scheduled/start/finish、release/module SHA、输入来源与 availability。相同 slot 重触发应读同结果；新合法输入或新日期应产生相应新研究结果，旧 run 字节保持不变。

第二日原 HK publisher 正常推进共享 latest 后，再只读验证第一日的 exact HK chain、日期对应 master entry、不可变 panel/manifest/receipt 与旧计划引用。既要证明第一日原件字节不变，也要证明它们仍能被原 reader 读回；仅比较旧文件 SHA 不能发现“原件保留但历史链无法验证”的问题。旧原件真实损坏时仍应明确拒绝，不能为通过跨日验收而跳过校验。

某路缺输入时，确认另两路有效成果能保存和显示；真实评估后的零入选与“未评估、数量未知”分别显示。永久阻塞的原 US read lane 保留有界占位，避免不断堆积线程；仅在它实际返回或经授权重启后恢复，不能称其能自动解除永久挂起。

两日所有关联证据齐备之前，状态为 `NATURAL_SLOT_UNVERIFIED`。10/8补算、一次页面成功、健康端口和 daemon cycle 不代替自然验收。

## 5. 回滚边界

回滚仅由同一集成 owner 在持有发布保护时，从当前累计基线撤销本轮声明的有限 delta，并重新核经理功能与 #28 保留；不要把旧 API/HK/web 整包切回。绑定或任务状态由原发布流程恢复并记录实际身份。

已经写入的研究 run、dispatch 和 owner attempt 保持不可变，不能通过删除历史或改写原件制造干净状态。若新元数据与旧 reader 不兼容，保留文件并明确读取拒绝，由 owner 制定版本兼容处理。TDX sidecar、V2/master 资格来源和缺失 PIT 证据不得在回滚中被倒签或伪造。
