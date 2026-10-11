# Mac 集成与 A/H/O/I/R/D/N 现场验收步骤

**状态：NOT_RUN。此文是针对已有应用和原 owner 的执行交接；本次没有连接 Mac、发布应用、启动 owner、调用 8873 或操作现场页面。**

先读 FINAL_REPORT.md。源码候选提交为 cd93198cb0de06c8f32386ed1fc808a5b4e53bec，附件基线为 31f5a39ce1ee7cd76bbf268e68760b6adc319774。交付只包含 8 个业务文件及 4 个测试文件的变更，不是完整应用。测试 support、旧快照和合成数据不能复制进正式发行目录补缺件。

## 1. 固定根与实际运行身份

以下值来自问题包与固定 GitHub 交付，必须在现场重新取证；它们不证明当前进程的加载状态。

| 身份 | 已知值 |
|---|---|
| canonical 源码 | /Users/lexi/Desktop/学习/v4_app |
| API 配置所指根 | /Users/lexi/Desktop/学习/agents调试/V4_US_MAPPING_DAILY_CHAIN_MAC_20261011_R1/integrated_release/manager-us-mapping-daily-chain-20261011-r1/app |
| scheduler 根 | /Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-auto-d1-20261011-r1/app |
| 原 Mac Python | /Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python |
| HK 共享 authority | /Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data |
| 10/09 原预选池根 | /Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/preselection_pools/20261009/ |
| 固定 release manifest SHA | 3b548f81684bd48e19b9cad8ac824f036163699f8cf53dc3234bc184df9014ad |
| 固定 API plist SHA | 8c27d44a9ddc23c0830b35a1bbaaf4e34721b86a2d749ce4c1d7aa60d723a081 |
| 固定 scheduler plist SHA | 5b6e208750e5f6287975857456ae0aabea57d6f5b9d4fecaecf619be17b75413 |

分别记录 API、scheduler、Stage 的实际命令行、解释器、cwd、加载模块路径、源码 SHA、配置 SHA、candidate manifest 与 deployment receipt。保留原未提交 diff 和文件 SHA，尤其是 canonical、现役 HK 与 US 的分叉修改。不能只看 plist，或用新起的 Python 打印模块路径，来证明运行中的 API 已加载该模块。

当前 source manifest 的旧 NOT_ACTIVATED 元数据与固定 activation receipt 已分清作用域：不改写旧 manifest，不把历史激活证明当作本补丁加载证明。

## 2. 在完整源码的隔离候选中核字节、合并补丁

在现场先设置 V4_PATCH_DIR 为此交付目录，V4_SOURCE_ROOT 为从实际完整源码建立的隔离候选根；不要设成正在服务的不可变发行根。以下命令未在 Mac 执行。

```bash
V4_PYTHON='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python'
: "${V4_PATCH_DIR:?请先指定此交付目录}"
: "${V4_SOURCE_ROOT:?请先指定完整源码的隔离候选根}"
git -C "$V4_SOURCE_ROOT" status --short
git -C "$V4_SOURCE_ROOT" diff --name-status
"$V4_PYTHON" "$V4_PATCH_DIR/check_candidate.py" --target "$V4_SOURCE_ROOT" --phase before
```

check_candidate.py 只核字节，没有部署、import owner 或写目标目录的动作。BEFORE_MISMATCH 表示现场文件不等于本次附件基线，须逐文件比较现场、附件前镜像与候选，保留已有修改后合并；不要自动覆盖。清单中的 canonical SHA 是捕获时的观察值，不是要求现场退回该 SHA。

仅当以上核对通过且该候选没有需保留的冲突时，才可在隔离候选应用补丁：

```bash
git -C "$V4_SOURCE_ROOT" apply --check "$V4_PATCH_DIR/changes.patch"
git -C "$V4_SOURCE_ROOT" apply "$V4_PATCH_DIR/changes.patch"
"$V4_PYTHON" "$V4_PATCH_DIR/check_candidate.py" --target "$V4_SOURCE_ROOT" --phase after
git -C "$V4_SOURCE_ROOT" diff --check
git -C "$V4_SOURCE_ROOT" diff --stat
```

逐文件合并会产生不同于 after/ 的字节，这是新的候选，须重新记录 SHA、运行验证并独立复核。不能沿用本报告中精确后镜像的测试结论。禁止对 canonical 或现役根执行整包覆盖、reset/clean、覆盖未提交 diff 或 force push。

## 3. 实际依赖、保存门禁与发布验证

在完整候选内运行新针对性测试与相应原套件，使用原 Mac 解释器和原前端锁文件。保留真实命令、退出码、版本、skip 与 failure ID。至少验证：

- 原 stage_center.consumer 完整 import，原 SelectionStore、当前 execution_evidence 合同及普通 HK provenance 路径。本次只有真实 store + 未改 helper 的隔离验证，完整 consumer 因缺当前依赖而阻塞。
- 新 history / daily channels / diagnostics / 日期请求测试；原 plan identity、issue24、workspace targeted、公告和 US daily 套件。
- 原完整 frontend typecheck 和 build，再检查实际页面路由。本次全量 typecheck 仍失败；10 文件闭包零诊断不是替代门禁。
- 原保存链在真实产物与 owner attempt 下，产品读回的 run、SHA、日期、identity 与终态一致。6 个原 issue24 bad_readback 断言分歧尚未修复，需单独裁定并关闭，不能只删断言或把 consumed=true 当完整通过。

本地隔离 Python 针对性命令对应以下四个文件；在 Mac 上不设置指向本次 Linux support_source 的 PYTHONPATH：

```bash
cd "$V4_SOURCE_ROOT"
"$V4_PYTHON" -B -m pytest -p no:cacheprovider -q \
  tests/test_manager_three_lane_history_r1.py \
  tests/test_manager_three_lane_channels_r1.py \
  tests/test_manager_three_lane_rebound_diagnostics_r1.py \
  tests/test_manager_research_selection_ledger.py
```

完成完整候选与独立 Reviewer 检查后，集成/部署继续使用原发布入口及其既有门禁。cycle / consumer 字节变化需要原流程重建 source fingerprint、manifest、binding、canary 和独立 receipt；不能把本次 SHA 写入旧 receipt 冒充发布。此次独立 Git 分支同步不包含 merge、部署或服务启停。

如果发布后发现问题，使用原发布流程回到现场保存的上一已验证 release；只撤回本次限定变更并保留并行修改。回滚也记录 API/scheduler 的加载身份和 receipt，不能用旧整包覆盖整个 canonical，不能回滚原研究数据来伪造验收。

## 4. R：历史当时与现在回看分开取证

原 GET 合同是 /api/v4/manager/research/workspace，参数 date 是计划目标日；selection_date、announcement_date、view 分别绑定选择日、公告日和口径。以下是只读请求模板，输出需在现场保存并核 SHA：

```bash
curl --fail-with-body --silent --show-error --max-time 60 --get \
  'http://127.0.0.1:8873/api/v4/manager/research/workspace' \
  --data-urlencode 'date=20261009' \
  --data-urlencode 'selection_date=20261009' \
  --data-urlencode 'announcement_date=20261008' \
  --data-urlencode 'view=historical'

curl --fail-with-body --silent --show-error --max-time 60 --get \
  'http://127.0.0.1:8873/api/v4/manager/research/workspace' \
  --data-urlencode 'date=20261009' \
  --data-urlencode 'selection_date=20261009' \
  --data-urlencode 'announcement_date=20261008' \
  --data-urlencode 'view=dynamic'
```

历史验收固定 cutoff=2026-10-09T09:30:00+08:00。问题包列出的归档均为事后计划：应确认查询不再因那些 late runs 溢出，同时仍拒绝它们进入盘前。现在回看使用实际可用时间和 dynamic 口径，即使可显示事后合法研究，也不能反向增加历史 PIT。

先只读清点 workspace_plans/20261009/ 与 workspace_plan_runs/20261009/ 的文件路径、大小、SHA、run、started_at、cutoff；分别记录缺失或损坏的 journal。**缺 journal 时 latest 重复正文仍可能耗尽预算的已知残余未关闭。**不要在 GET 内补造 journal，也不要根据 run_id/mtime/自报 SHA 跳过未验证文件。若现场命中该残余，R 继续 PARTIAL，保留具体反例。

原 POST /api/v4/manager/research/workspace/refresh 是带查询参数的无 body、同源写操作，应由原页面/owner 入口在其门禁内触发。今天手动刷新旧目标日会记为 RETROSPECTIVE，不计历史或自然运行；不能手工设置伪造 cutoff/availability 绕过它。

## 5. I：10/12 原保存产品与当前输入的成对比较

先只读保全以下旧证据，再考虑刷新；不要用新 run 覆盖问题样本后宣称误失效已消失。

| 原观察字段 | 值 |
|---|---|
| saved run | 1e9d511515de47599f05539e43e79b81 |
| product SHA | 1ce6a9e12c4bf692707b38bbf7c73a75acbea499a9cc3d0bc624538da9234aec |
| 原文件 SHA | 668d52e7e313a4e551d495b24ed4248b22fadb892be24a159a7423acba709f32 |
| input identity | 4d253adb9e279c3764b7a556ba44624cc3f26420a2d2c34459fe760bbba7f81b |

由原 ManagerResearchStore 导出该 run 产品、对应 owner attempt、当前完整 identity components/prehash 和所引 payload/receipt 的路径与 SHA。使用原 workspace_identity 的精确登记合同与本次历史冻结比较，证明只有无关全局登记变动时可继续消费同一保存 run，且读取前后旧产品字节不变。

对相关 payload、receipt、日期、PIT、路径、非该登记合同的 manifest 变化分别确认仍拒绝旧计划。本地 7 类负向测试通过不等于真实 10/12 这两项组件变化已查明。取得成对原始输入前 I 继续 PARTIAL。

## 6. A：原公告 owner 的合法导入和读回

先调用原 CLI 的只读 readback，确认是否已有精确 publication=20261008、target=20261009 的合法 product 和 import receipt：

```bash
cd "$V4_SOURCE_ROOT"
"$V4_PYTHON" ops/run_manager_daily_announcement.py readback \
  --target-date 20261009 --publication-date 20261008 \
  --api-base 'http://127.0.0.1:8873'
```

如需恢复，先核现场原 research-state-root、evidence run 与 body corpus。原入口的顺序为 capture/resume → 实际独立 Reader/Reviewer → register-handoff → import → readback。下面只列原 CLI 接受的参数；变量必须来自真实现场产物，不可填测试标识：

```bash
: "${V4_RESEARCH_STATE_ROOT:?必须取自现场原 owner 配置}"
"$V4_PYTHON" ops/run_manager_daily_announcement.py capture \
  --target-date 20261009 --publication-date 20261008 \
  --api-base 'http://127.0.0.1:8873' \
  --research-state-root "$V4_RESEARCH_STATE_ROOT"
```

若已有经过核验的 evidence run，使用同一 capture 命令的 --resume-evidence-run-id；不要把 catalog run 4b69fa03fbfc4c48b1c410239332505e 当 evidence run。

```bash
: "${V4_EVIDENCE_RUN_ID:?来自 capture 或核验后的已有 evidence run}"
: "${V4_SEMANTIC_CATALOG:?实际 Reader 输出路径}"
: "${V4_REVIEWER_OUTPUT:?不同身份 Reviewer 的实际输出路径}"
: "${V4_PARENT_TASK_ID:?实际派发父任务标识}"
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

如果原流程产出 decisions，register-handoff 的 --decisions 指向该实际文件；不合成 Reader/Reviewer 或导入回执。ops/run_manager_announcement_cycle.py 不是上述子命令的入口，其现有 main 只接受 binding/dry-run 类参数。

最终核完整 source artifacts、combined product SHA、selection decision SHA、evidence run、import receipt、CONSUMED、目标日/公告日和逐股原理由。UI 观察的 55 只、基础分析 SHA 或 catalog SHA 均不能单独代替这些。新的补采 availability 按实际时间记录，不能改成 10/09 盘前。

## 7. H：精确 HK authority、D-1、原 Stage 三件

10/09 membership 记录在当天 17:31 才采集，不能替代 10/09 盘前的 10/08 精确 authority；问题包也没有 10/08 master 条目。先沿原 ensure_hk_security_master.py 的 reuse-only 路径查当时缓存，或核 verified-source-store-root 的精确既有记录；已知原参数包含 --trade-date 20261008 --reuse-only。入口文件路径、当前参数和 owner root 必须从完整现场源码确认，不能复制别日数据或补写历史时间。

由原 v35_dispatcher.research_panel_daily_hk 和 materialize_scheduled_preselection 恢复相应合法输入，再运行原 Stage。记录 target membership V2、D-1 canonical Top100 清单与 count、artifact/manifest/receipt 三件 SHA、Stage run、algo、rank/order 和 execution 的 selection reference。

Manager 原消费阶段是 STAGE_0935_0940，原 native cutoff 为 09:40:05；本次没有改为 0925。10/09 的 0925 selected=0 / written=false / D1_NOT_STRICT_0_2_READY 不是合法零结果。10 只 backfill 的 c44b03fa94115911bc4aaa44d2152712 / run-6e62af205e5142401ad186b0 不能进入正式自然验收。

若原正式算法完整执行得出零行，仍要有精确 100 个 D-1 输入、合法 membership、零行三件、同 run 的执行引用与 counters，才可显示有效 0。无执行绑定的非空研究投影最多 PARTIAL；missing、replay、WAITING_0920_SECOND_FILTER、D1_PRESELECT_REFERENCE 不能冒正式完成。

## 8. O：原两门计算、完整 ledger 与精确缺口

读取同次原计算输出的 rebound_input_diagnostics，按实际 target/source date、symbol 列出 missing_prior60_dates、missing_previous5_dates、重复日期、历史数值、量来源、cutoff、screen identity 和原 refs。不把测试样本的 20260716/20261005/20261006 当作市场实测缺口。

保留原实现的 prior60 HK sessions（包含原日历定义的半日）与 previous5 full sessions、两门算法、SELECTED/NEAR_WATCH/EXCLUDED/UNRESOLVED、priority 和 accounting。10/08 的 finality NOT_ATTESTED、units NOT_PROVEN 及 10/09 面板直到 10/10 发布的事实都要保留。214 strict、286 near、34 pending 只是原 screen 观察，不能当最终已保存名单。

恢复顺序是先查原缓存及同响应量来源；需要补采时先取得并完整读 docs/hk_history_backfill.md，再沿原 TDX/共享面板 owner。该文档本次未提供，因此没有执行补采，也不臆造它的命令。绝对单位未知就保留未知；原合同允许的同响应相对量比也不能冒充绝对单位证明。

保存原最终研究 ledger 与 plan 后，核 source identity、decision digest、完整计数、run/product/receipt，再到 API 与页面对同一结果。诊断是随原读取生成的观察，不能单独成为第二 screen 或产品身份。

## 9. D、页面重载与 N 自然运行

在隔离、可恢复的原 owner fixture 或正式允许的测试入口分别提供 A/H/O 缺一路的场景。不要删除现场 owner 数据来制造缺件。逐路记录另外两路 rows、原理由、顺序、来源 refs 未被清空，缺件路 count=null；与完整合法零行 ledger/执行回执的 count=0 分开。

在实际 Manager 页面使用 plan_date=20261009、selection_date=20261009、announcement_date=20261008、view=dynamic，保留独立三个日期；随后整页重载。POST 成功时原页面复用经校验的响应，不额外立即 GET；失败时可回退一次 GET，整页重载也会 GET。上述工作台读取/刷新请求都应保持同组日期绑定，旧请求或切日后的迟到响应不覆盖当前结果。页面路由沿用现场已有入口，不新建第二页面或长期端口。

N 必须在下一实际交易日，按原日历和调度自然发生。固定旧 binding 中 plan_material_refresh_only=true、announcement_collection_enabled=false，仅证明当时配置不足以自动完成公告 capture/Reader/Reviewer/import；需由原主控核实际能力，并通过原 canary/发布合同建立完整自然链，不能只改布尔值。

自然执行记录每路真实 scheduled task、reader/reviewer、owner run、输入/产品/receipt SHA、API 同 run/SHA、页面重载和生成/可用时间。手动导入、回看、测试或只跑 US 映射不计 N。当前 acceptance.json 的 natural_run_verified=false、N=NOT_RUN 必须保留，直到这些实际证据齐全。

## 10. 每行验收的必要记录

| 记录 | 要求 |
|---|---|
| 场景 | 历史当时 / 现在回看 / 未来自然，分别记录 |
| 源码/进程 | source root、loaded module SHA、解释器、PID、binding、release/canary/receipt |
| 输入 | authority、准确日期/时段、路径、文件 SHA、receipt、availability；未知字段保留 null |
| 选择 | 原 owner/算法、run、逐股原理由、顺序、完整 ledger/accounting；明确研究与正式 Stage |
| 保存 | product SHA 与文件 SHA 分开，owner attempt 与 import/Stage receipt 同 run/date |
| API | URL/日期绑定、原响应 SHA、业务状态、实际 run/SHA，HTTP 200 只是传输结果 |
| UI | 同入口重载、绑定日期、原列表/理由、读回 run/SHA、截图或可访问性树的生成时间与 SHA |
| 结论 | A/H/O/I/R/D/N 逐项 PASS / PARTIAL / CANNOT_CONFIRM / NOT_RUN，保留失败原因 |

完整现场原始响应、研究数据和计划留在原受控环境。若继续做 Git 交接，只同步必要脱敏摘要、代码和精简证据，遵守已有仓库范围。
