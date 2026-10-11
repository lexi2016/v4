# Mac 集成、部署门禁与原 owner 现场验收

**本文件全部现场步骤：NOT_RUN。** 本轮没有访问原 Mac、8873 或真实研究数据。此交付是 10 个业务文件的差异候选，不是完整应用发行；完整原测试仍有 38 项失败，原前端仍有 3 项 runtime 失败和 6 条类型错误。应先在现场完整候选中裁定这些门禁，不能将本文件当成部署已获通过的证明。

先读 README.md、BEFORE_AFTER_SHA256.json 和 recovered_dependencies/DEPENDENCY_RECOVERY_REVIEW.md。按原项目 Luna Max Writer / 独立只读 Reviewer 身份实施；本轮 Chat 的隔离测试和 Reviewer 身份不能代替现场要求。

## 1. 重新固定运行与源码身份

以下为原附件和固定旧回执中的已知值，现场逐项重读。保留 canonical 未提交 diff、现役 HK/US 补丁和现有发行根，按角色处理，不整包覆盖。

| 角色 | 原记录值 |
|---|---|
| canonical | `/Users/lexi/Desktop/学习/v4_app` |
| API 配置根 | `/Users/lexi/Desktop/学习/agents调试/V4_US_MAPPING_DAILY_CHAIN_MAC_20261011_R1/integrated_release/manager-us-mapping-daily-chain-20261011-r1/app` |
| scheduler 根 | `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-auto-d1-20261011-r1/app` |
| 原解释器 | `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python` |
| HK authority | `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data` |
| 10/09 preselection | `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/preselection_pools/20261009/` |
| release manifest SHA | `3b548f81684bd48e19b9cad8ac824f036163699f8cf53dc3234bc184df9014ad` |
| API plist SHA | `8c27d44a9ddc23c0830b35a1bbaaf4e34721b86a2d749ce4c1d7aa60d723a081` |
| scheduler plist SHA | `5b6e208750e5f6287975857456ae0aabea57d6f5b9d4fecaecf619be17b75413` |

分别记录运行中 API、scheduler、Stage 的 PID、实际命令行、cwd、解释器、loaded module 路径/源码身份、绑定、manifest/canary/部署回执。新起一个 Python 打印 __file__ 只证明那个新进程的解析，不能证明原服务已加载这些字节。`.v4.local` 与 `.v35.local` 的源/数据角色不要混用。

旧 activation 回执当时记录 API PID 28664、scheduler PID 28680 已加载匹配配置；它不是本次 R2 的加载证据。旧不可变 manifest 内 NOT_ACTIVATED 元数据保持原文，不手改来“消除冲突”。

## 2. 完整隔离候选与逐文件合并

先从实际完整源码与用户修改建立新的隔离候选，记录允许的 22 个路径及前镜像。将 `V4_PATCH_DIR` 指向本交付目录，将 `V4_SOURCE_ROOT` 指向该完整隔离候选，不能指向正在服务的不可变 release。

```bash
V4_PYTHON='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python'
: "${V4_PATCH_DIR:?请指定交付目录}"
: "${V4_SOURCE_ROOT:?请指定完整源码隔离候选根}"
git -C "$V4_SOURCE_ROOT" status --short
git -C "$V4_SOURCE_ROOT" diff --name-status
"$V4_PYTHON" "$V4_PATCH_DIR/check_candidate.py" --target "$V4_SOURCE_ROOT" --phase before
```

check_candidate.py 只读核 before/after 包内字节和目标，不运行 owner 或改目标。任何 BEFORE_MISMATCH 都意味着需要以现场、附件 before、候选 after 做逐文件比较并合并；保留已有更晚修复。新增测试已存在也不能覆盖。不能用 reset、clean、全目录复制或 force push 解决不一致。

精确前镜像通过且无需合并时，在隔离候选执行：

```bash
git -C "$V4_SOURCE_ROOT" apply --check "$V4_PATCH_DIR/changes.patch"
git -C "$V4_SOURCE_ROOT" apply "$V4_PATCH_DIR/changes.patch"
"$V4_PYTHON" "$V4_PATCH_DIR/check_candidate.py" --target "$V4_SOURCE_ROOT" --phase after
git -C "$V4_SOURCE_ROOT" diff --check
git -C "$V4_SOURCE_ROOT" diff --stat
```

若发生逐文件合并，产生的是新的候选 SHA，必须重新运行和独立复验，不继承本包后镜像的精确结论。现役 HK/US / canonical 差异与本轮补丁分别留痕。

### 已找回的原依赖如何使用

本包 recovered_dependencies 是原提交文件与角色证据，不在自动 changes.patch 内。

1. `stage_api/execution_evidence.py`：原 Git blob `3af4fb13f7da60e0822827fb834c671cef16a372`，SHA256 `1be96e736fda2863f6f8ff2315e8879a98499bbd30f5a911b46423c4dc6f094b`。满足上传 consumer 的 research_source_projection 和 selection_store(s) 接口；配对调用和直接依赖已核。先比现场文件和后续修复，再决定在完整候选中恢复/合并。Linux 完整 Stage 复验通过明确的 review-only import overlay 载入此原文件，候选本身不能因此称完整发行。
2. 两版 `ensure_hk_security_master.py` 各自属于 actual_pool_scheduler 与 canonical_reference，前者无 membership_only，后者有；均有原 verified_source_store_root。canonical_reference 原 before 与本轮旧支持源不匹配。不能把 scheduler 全文件复制覆盖 canonical；读取 original_role_evidence 的配对 manifest，按实际角色和前镜像落入原 owner。
3. `docs/hk_history_backfill.md` 为原分钟数据恢复说明，本轮已完整读过。缓存优先，按原 TDX/共享权威链执行；它不证明 60 日日线历史已经完整，也不授权伪造历史 available_at。未选定 Futu 额度来源时不得暗换。

## 3. 原环境集成测试与发布门禁

在完整候选中使用原 Python、原前端锁文件、真实完整依赖；不用本轮 Linux 的 scoped namespace loader 或旧完整支持目录冒充发行依赖。

```bash
cd "$V4_SOURCE_ROOT"
"$V4_PYTHON" -B -m pytest -p no:cacheprovider -q \
  tests/test_manager_three_lane_history_r1.py \
  tests/test_manager_three_lane_history_r2.py \
  tests/test_manager_three_lane_channels_r1.py \
  tests/test_manager_three_lane_channels_r2.py \
  tests/test_manager_three_lane_rebound_diagnostics_r1.py \
  tests/test_manager_three_lane_rebound_recovery_r2.py \
  tests/test_manager_three_lane_owner_readback_r2.py \
  tests/test_manager_research_selection_ledger.py

"$V4_PYTHON" -B -m pytest -p no:cacheprovider -q \
  tests/test_manager_plan_identity_r2.py \
  tests/test_manager_plan_readback_issue24.py \
  tests/test_manager_workspace_targeted_r2.py \
  tests/test_manager_business_completion_a.py \
  tests/test_manager_business_completion_b.py
```

完整 import stage_center.consumer、原 SelectionStore 与原 execution_evidence；运行原公告导入门禁、相关 HK/US 日常 suite 和前端 typecheck/build。原 issue24 六个失败读回写成功 journal 的断言分歧必须得到具体结论；不删测试、不降低 consumed/run/SHA/状态要求。原前端三个 runtime 失败与六条类型错误亦保留原 failure ID，完整应用验证仍失败时不转交发布为 PASS。

所有检查通过后，继续使用项目原发布 owner 的流程：新 source fingerprint、candidate manifest、binding、canary、独立 receipt 和部署加载证据。cycle/consumer 源字节变化会影响 pin，不能将新 SHA 写进旧 receipt 代替重跑。此批 GitHub 独立分支不执行 merge、部署或启停服务。Vibe8910 保持原样。

## 4. R / 时间口径：固定目标分别取证

先保全真实 10/09 archive inventory 与每个文件 SHA、run、generated_at、cutoff、owner journal。GET 不生成补造 journal、不删档案。实际历史探测应不再因为规范 late 大正文而扫描溢出，同时仍不准入这些产品。非规范头/缺件/损坏仍回原全文和失败门禁；若现场出现具体未知布局反例，保留反例继续修复，不提高限额绕过。

在单独证据目录保存 HTTP 原字节与头。以下均为只读 GET，未在 Mac 执行：

```bash
: "${V4_EVIDENCE_DIR:?请指定新的现场证据目录}"
curl --fail-with-body --silent --show-error --max-time 60 --get \
  'http://127.0.0.1:8873/api/v4/manager/research/workspace' \
  --data-urlencode 'date=20261009' \
  --data-urlencode 'selection_date=20261009' \
  --data-urlencode 'announcement_date=20261008' \
  --data-urlencode 'view=historical' \
  --dump-header "$V4_EVIDENCE_DIR/1009-historical.headers" \
  --output "$V4_EVIDENCE_DIR/1009-historical.json"

curl --fail-with-body --silent --show-error --max-time 60 --get \
  'http://127.0.0.1:8873/api/v4/manager/research/workspace' \
  --data-urlencode 'date=20261009' \
  --data-urlencode 'selection_date=20261009' \
  --data-urlencode 'announcement_date=20261008' \
  --data-urlencode 'view=dynamic' \
  --dump-header "$V4_EVIDENCE_DIR/1009-retrospective.headers" \
  --output "$V4_EVIDENCE_DIR/1009-retrospective.json"

shasum -a 256 "$V4_EVIDENCE_DIR/1009-historical.json" "$V4_EVIDENCE_DIR/1009-retrospective.json"
```

核业务字段 read_context.mode/read_basis/as_of、date_bindings、plan_product、各通道原 run/SHA/receipt，不能只看 HTTP 200。历史 cutoff 不晚于 2026-10-09 09:30+08；显式现在回看使用真实当前时钟。内部 service 省略 view 仍保持保存 cutoff；HTTP 省略 view 则按原 auto 处理。当前/未来日的保存 cutoff 稳定行为保持。

使用原页面：

`http://127.0.0.1:8873/manager-selection/?date=20261009&plan_date=20261009&selection_date=20261009&announcement_date=20261008&view=historical`

再将 view 改为 dynamic，整页重载、前后切日、后退/前进。记录实际网络参数、原 renderer 列表/风险/未知/零、run/SHA 与页面截图或可访问性树时间及摘要。不得另建第二页面或端口。

## 5. I：刷新前保全 10/12 原失效样本

| 字段 | 真实旧观察 |
|---|---|
| run | `1e9d511515de47599f05539e43e79b81` |
| product SHA | `1ce6a9e12c4bf692707b38bbf7c73a75acbea499a9cc3d0bc624538da9234aec` |
| 原 JSON 文件 SHA | `668d52e7e313a4e551d495b24ed4248b22fadb892be24a159a7423acba709f32` |
| input identity | `4d253adb9e279c3764b7a556ba44624cc3f26420a2d2c34459fe760bbba7f81b` |

由原 ManagerResearchStore 只读导出此 run、对应 attempt、完整保存 identity prehash 和当前完整 components、具体输入路径/date/payload/receipt SHA。原摘要中的 46 material + 15 projection 仅足以提示全局登记可能参与，不能重建全部 prehash。

在隔离的原 owner 验证中只改变无关登记，必须仍消费同一旧 run、旧产品字节不变；分别改变相关 payload、receipt、目标日期、cutoff/PIT、来源路径、实际选择输入及非狭义登记合同字段，必须拒绝旧计划。先证明这一对照，再刷新。禁止宽泛忽略所有 manifest_sha256 或靠生成新计划掩盖旧问题。未取得原成对输入前，I 继续 PARTIAL。

## 6. A：真正的原公告执行与归档

先读回已存在的精确产品，不把页面观察的 catalog run 当 evidence run：

```bash
cd "$V4_SOURCE_ROOT"
"$V4_PYTHON" ops/run_manager_daily_announcement.py readback \
  --target-date 20261009 --publication-date 20261008 \
  --api-base 'http://127.0.0.1:8873'
```

逐一核真实 55 条的原 product/selection SHA、body corpus、independent reviewer、handoff 与 owner import receipt。若需沿原 owner 恢复，使用原 capture/resume → 真实独立 Reader/Reviewer → register-handoff → import → readback。所有变量取自实际 owner 配置和原文件：

```bash
: "${V4_RESEARCH_STATE_ROOT:?现场原 owner 根}"
"$V4_PYTHON" ops/run_manager_daily_announcement.py capture \
  --target-date 20261009 --publication-date 20261008 \
  --api-base 'http://127.0.0.1:8873' \
  --research-state-root "$V4_RESEARCH_STATE_ROOT"
```

已有经过核验的 evidence run 时，使用此原 capture 的 `--resume-evidence-run-id`，不要重新抓同源或复制别的 run。由真实独立 Reader/Reviewer 生成并审阅原输出后：

```bash
: "${V4_EVIDENCE_RUN_ID:?来自原 capture 或核验后的原 evidence run}"
: "${V4_SEMANTIC_CATALOG:?原 Reader 输出}"
: "${V4_REVIEWER_OUTPUT:?独立 Reviewer 实际输出}"
: "${V4_PARENT_TASK_ID:?真实派发父任务}"
: "${V4_READER_IDENTITY:?实际 Reader 身份}"
: "${V4_REVIEWER_IDENTITY:?实际且不同的 Reviewer 身份}"
"$V4_PYTHON" ops/run_manager_daily_announcement.py register-handoff \
  --evidence-run-id "$V4_EVIDENCE_RUN_ID" \
  --research-state-root "$V4_RESEARCH_STATE_ROOT" \
  --target-date 20261009 --publication-date 20261008 \
  --semantic-catalog "$V4_SEMANTIC_CATALOG" \
  --reviewer-output "$V4_REVIEWER_OUTPUT" \
  --parent-task-id "$V4_PARENT_TASK_ID" \
  --reader-identity "$V4_READER_IDENTITY" \
  --reviewer-identity "$V4_REVIEWER_IDENTITY"

"$V4_PYTHON" ops/run_manager_daily_announcement.py import \
  --evidence-run-id "$V4_EVIDENCE_RUN_ID" \
  --research-state-root "$V4_RESEARCH_STATE_ROOT" \
  --api-base 'http://127.0.0.1:8873'
```

有原 decisions 产物时，原 register-handoff 的 `--decisions` 指向该真实文件。不得伪造 semantic review、身份或回执。capture/import availability 按实际发生时间记录，旧 publication date 不表示当时可用。完整 source refs、selection/accounting 与 mapped/unmapped 风险进入原 GET 和页面后核同 run/SHA；研究入选仍不是 BUY。

`ops/run_manager_announcement_cycle.py` 不是这些子命令的入口。它当前不包含完整 Reader→Reviewer→register→import 自动派发，现有 plan-only binding 也不能完成 A 自然链；见第 9 节。

## 7. H：精确 membership、D1 与原正式 Stage

按目标日独立核验，10/12 缺件不能套用为 10/09 缺件。10/09 原 D1 回执 EXPECTED_MISSING、空 SHA、metadata invalid 20261008；原 10/09 master 在 17:31:16 才抓取，不能替代 10/08 精确 authority。

由原 ensure owner 先执行已存在的 reuse-only 读取，参数形状为 `--trade-date 20261008 --reuse-only`；需恢复时，只有确认现场相应角色真正支持 `--verified-source-store-root` 且来源通过原门禁，才能使用该原路径。不要在不支持的候选文件上直接传该参数，更不能将今天 capture 标回旧时点。

恢复合格输入后，经原 `v35_dispatcher.research_panel_daily_hk`、`ops/materialize_scheduled_preselection.py` 与原 Stage 运行。记录 membership V2、精确 D-1 canonical Top100 100 行、源日期/availability/receipt、原算法和 rank/order、artifact/manifest/receipt 三件 SHA、Stage execution 的 selection reference。API 必须消费同次 STAGE_0935_0940 的 HK_CONNECT，不拿 focus_symbols 或 D1 参考池充当正式结果。

原 0925 的 selected_rows=0 / write_performed=false / D1_NOT_STRICT_0_2_READY 保持缺口。backfill `c44b03fa94115911bc4aaa44d2152712` 下 `run-6e62af205e5142401ad186b0` 不计普通正式或自然通过。原普通算法合法保存零行时，仍必须有精确输入、三件和执行绑定。

Manager 原消费阶段在 09:35–09:40，本来晚于 09:30 历史计划界线。已有 SAME_DAY_CATCHUP 时槽 10:00/12:30/15:45/18:30/22:30 可以归档之后的真实结果，但保留真实 LATE_CATCHUP 等类别及 natural 标志，不能修改 receipt 伪装盘前。

## 8. O：足量输入、原计算与真实保存

先从实际原 workspace 读取 rebound_input_diagnostics，逐 symbol/date 输出以下字段，不把测试日期或本包 214 数量当实测结果：

- target/source trade date、原日历要求的 prior60 sessions 与 previous5 full sessions。
- missing_prior60_dates、missing_previous5_dates、重复日期、invalid_prior60_high_dates、invalid_previous5_volume_dates、invalid_current_fields。
- 原量来源、finality、units、六个量值同响应证明、daily_supplement_attempted/gaps 与原 reader 的精确拒绝原因。
- screen.input_identity、原 source projection、ledger decision_identity、逐股 SELECTED/NEAR_WATCH/EXCLUDED/UNRESOLVED、原理由和 accounting。

先查原缓存，再按已读原 runbook 和原 TDX/共享 owner 恢复。数字存在不等于量来源已证明。本次 adapter 允许原 reader 已核实的同响应六量作相对比值，绝对 units 仍可 NOT_PROVEN；不能把该资格升级成单位已知，也不能接受归一化字段伪装原 raw 响应。遇到 wrong date/SHA/parent/publish/PENDING 等，保留原拒绝/待核。

使用原 `ManagerResearchJobService.refresh_workspace_plan` 保存原最终研究 ledger；经 readback 核 plan run/product SHA、文件 SHA、input identity、原准入的确切终态 attempt、source/decision digest，再核 API/UI 同源。其他通道有缺件时整体 attempt 可以为 PARTIAL，O 自身已完整的零结果仍按原通道资格核验。未保存的即时 preview 不能成为有效零。验证后续失败 attempt B 不会取代仍有效的产品 A 的原准入记录，但 B 的失败仍在最新状态中可见。

## 9. D、自然调度 N 与最后归档

D 在隔离可恢复的原 owner 输入/测试入口中逐路缺一，不能删现场数据制造测试。其余通道的合法行、原风险、顺序、refs 不应全清；缺件为 null，完整原算法已保存有效空集才为 0。在原页面整页重载，并检查日期请求不会串档。

N 由原主控核真实 Reader/Reviewer 定义、heartbeat、父任务和独立身份；原调度与原导入派发不足时，先补齐原能力并走原 canary/发布合同。现有 fixed binding 为 plan-only/announcement disabled，单改布尔值不能制造完整自动链，不建第二 producer。自然取证必须来自实际交易日、真实原调度触发，不能传伪造 now、改 available_at 或用手动命令替代。

每条 A/H/O 保存：日期与时段、原输入/run/payload/receipt、最终选择逐股理由、产品和 raw 文件 SHA、原 attempt/terminal 状态、实际 API 原字节 SHA、页面重载的同 run/SHA、生成与可用时间、RESEARCH_ONLY/BUY/orders 标志。分别填写历史 PIT / 现在回看 / 自然三种结论。三路没有全部通过时整体继续 PARTIAL。

自然时间未到需要真实 Mac 时钟、原交易日历和原调度 due 判断共同证明；本包不声称当前仍未到。自然未观察到只能报 NOT_RUN/CANNOT_CONFIRM。

## 10. 回滚

隔离候选精确应用后、没有任何后续并行修改时，可核验反向补丁：

```bash
"$V4_PYTHON" "$V4_PATCH_DIR/check_candidate.py" --target "$V4_SOURCE_ROOT" --phase after
git -C "$V4_SOURCE_ROOT" apply --reverse --check "$V4_PATCH_DIR/changes.patch"
git -C "$V4_SOURCE_ROOT" apply --reverse "$V4_PATCH_DIR/changes.patch"
"$V4_PYTHON" "$V4_PATCH_DIR/check_candidate.py" --target "$V4_SOURCE_ROOT" --phase before
```

如已经合并现场差异或发生新修改，反向补丁也需逐文件比较，不能覆盖后续工作。正式部署后的回滚使用原 release/activation owner 指向现场保存的上一已验证发行，并重新取得 API/scheduler loaded identity 与 receipt；不整包覆盖 canonical，不删或倒退研究数据，不伪造通过记录，Vibe8910 原样保留。

现场完整原始行情、正文、计划和大响应留在原受控环境。GitHub 只按既有授权同步必要源码与精简证据；不要扩大为原始市场数据或认证资料上传。
