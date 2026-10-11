# V4 三路选股闭环修复 R2：实际源码候选与未完成验收

**整体：PARTIAL / 未完成。** 本轮已实施并独立复验可在当前环境证明的代码修复，交付 10 个业务文件差异、12 个测试/fixture、前后 SHA、原依赖恢复字节和具体 Mac 集成步骤。没有连接原 Mac、部署到 8873、执行真实市场补采或观察到下一交易日的自然回执；A/H/O 的真实日常执行、保存、实机 API 与页面闭环仍未通过。工程测试、提交和本包均不改变这一结论。

## 1. 已按原 README 填写的验收表

| 编号 | 本轮实现与已取得证据 | 尚缺的最终通过证据 | 最终状态 |
|---|---|---|---|
| A | 原证据构造、原 Reviewer/handoff/import、原 owner 保存、真实 FastAPI GET 全链复验；精确日期、计数与源引用对账；H5354 等未映射身份不再落成有效零，保留原理由/风险 | 实际 55 条所属 product、evidence run、owner import receipt；相同真实 run/SHA 在 Mac 8873 重载读回；原日常 Reader/Reviewer/导入执行 | PARTIAL |
| H | 消费原 STAGE_0935_0940 的 HK_CONNECT 完整结果及 execution 绑定；找回配对 execution_evidence 原源；隔离原选择器 + SelectionStore + 完整 consumer 的 9 项行为通过 | 精确目标日 membership V2、D-1 canonical Top100、合法普通 Stage 三件及真实执行回执；实际 API/UI；backfill 不计入 | PARTIAL |
| O | 原两门计算、原 ledger、同响应成交量补充源校验及保存读回；未知/未归档不显示有效 0；已保存产品绑定其确切 attempt，后续失败不会改绑 | 实际逐 symbol/session 的足量输入、量来源、最终研究 ledger、真实 run/product/attempt，以及 8873 重载 | PARTIAL |
| I | 历史冻结比较沿原 semantic_value 的狭义登记合同；无关登记变化与相关 payload/receipt/date/PIT 等变化的正负例通过；未改 workspace_identity.py | 10/12 原保存 run 与当前完整 prehash/components 的成对重算。现有 46+15 引用摘要不足以查明完整污染路径 | PARTIAL |
| R | 7 个合计 147,031,510 B 的等规模合成事后计划，在无 journal 且 UTF-8 截断场景只探测 114,688 B，不读正文、不溢出、不改文件、不准入迟到计划；显式过去日 dynamic 使用当前时间 | 原 Mac 10/09 那 7 个真实档案与实际 8873 页面重载；本轮未持有原大正文 | PARTIAL |
| D | 独立通道缺口、计数未知、有效零、保留其余合法行、原风险和 run/SHA 的 Python/API/DOM 测试通过 | 原 Mac 实际三路输入/结果下的隔离行为与页面重载证据 | PARTIAL |
| N | 查明原固定激活记录只验证配置与 dry-run，daily archive=NOT_RUN、natural=false；现有绑定为 plan-only，公告采集关闭 | 下一实际交易日，原调度自动执行各路 owner → 保存 → API → 页面同 run/SHA 的自然回执 | NOT_RUN |

本轮没有把“未到自然时段”当作现时事实。没有读取当前 Mac 时钟、调度 heartbeat 或自然 receipt，所以 N 准确表述为“本会话未观察/未执行，NOT_RUN”。

## 2. 基线、身份与变更边界

原附件 ZIP：`V4_三路选股闭环_问题包_20261011(1).zip`，949,918 B，SHA256：

`3e389c00b4c82b4e987b3e06f51af70728d10b48e6d8de1f5554640e8b66eee7`

已核原 PACKAGE_MANIFEST 的 136 个条目及 SOURCE_MANIFEST 的 126 个源码条目。10 个附件业务文件发生变化，其余 116 个字节不变，原附件测试源未修改。详见 `BEFORE_AFTER_SHA256.json` 与 `checks/attachment_and_protected_sources.json`。每个修改都从附件对应前镜像产生；清单里的 canonical SHA 只是原捕获观察，不能作为退回或覆盖目标。

GitHub 父提交是原问题包 `1ea98799d1763c88be2be1f0ee1b0ccec654532f`，其父为既有 US 交付 `a1b722e4c82defcb9537d5c05915c6a8072c02d3`。本轮独立分支为 `codex/three-lane-closure-20261011-r2`，必要字节保存在 `handoff/three-lane-closure-20261011-r2/`。实际同步后的固定 commit、tree 和远端读回核验见随下载包 `GIT_DELIVERY.json`；该记录与 DELIVERY_MANIFEST 是源码提交完成后生成的封装记录，Git 提交保留其余候选和证据。该记录不构成 merge 或部署回执。

本地候选以同一附件的逐文件字节为基线，复用 R1 的 8 文件修复前重新做了 RED/GREEN：原附件 54 failed / 19 passed / 1 skipped，复用后 73 passed / 1 skipped。R2 随后补上无 journal 历史排除、公告计数、当前回看、成交量来源修复、精确保存绑定及风险显示。R1 的旧交付结论没有直接沿用。

测试组装使用已记录的旧完整源码作为依赖支持，再覆盖 126 个精确附件文件及核过 Git blob 的必要支持源码。支持目录不代表完整现役发行，也不随本包整套部署。`checks/root/support_provenance.json`、独立 source snapshots 与 `recovered_dependencies/` 记录来源。当前候选本身仍不是可直接运行的完整 Mac release；完整 Stage 验证使用了明确标示的 review-only 原 execution_evidence overlay。

本轮唯一业务 Writer 是 `/root`；只读 Reviewer 为 `/root/history_identity_review`、`/root/announcement_review` 和 `/root/hk_rebound_review`。Reviewer 没有修改业务候选。实际使用本会话模型环境，不冒称已在用户 Mac 中运行指定 Luna Max Writer/Reviewer；现场仍须遵守原身份规则。

### 运行身份冲突的处理

重新从固定 US 提交取回原 activation execution 与独立 review。原回执记录当时 API PID 28664、scheduler PID 28680、API release 根与 plist/manifest SHA 匹配；独立 review 时间为 2026-10-11 14:12:20+08，并明确只验证 loaded configuration 与一次 dry-run。这解释了不可变候选 manifest 的旧 NOT_ACTIVATED 字段为何不能单独推断部署状态。

原 manifest SHA 仍为 `3b548f81684bd48e19b9cad8ac824f036163699f8cf53dc3234bc184df9014ad`，API plist 为 `8c27d44a9ddc23c0830b35a1bbaaf4e34721b86a2d749ce4c1d7aa60d723a081`。这些原回执证明其记录时刻，不能证明当前 Mac 进程已加载 R2。没有修改旧 manifest 或 receipt。原文与固定来源见 `checks/provenance/`。

## 3. 实际代码修复与结果

| 修改文件 | 修复内容与约束 |
|---|---|
| `v4/manager_research/workspace_history.py` | 先检查原 sealed journal 的截止时间；对规范存储布局使用最多 16 KiB 的排除性头探测。安全路径、非符号链接、常规文件、日期/owner/schema/run/flags 形状与时间边界都必须匹配。头探测只能排除确定迟到文件，不能准入、不能宣称全 SHA 已验证。未知布局回到原有界全文门禁；单件 32 MiB、扫描正文 64 MiB、64 runs、256 entries 上限保留。另将冻结结构的二次比较接回原 semantic_value 狭义合同。 |
| `v4/manager_research/workspace.py` | 保留 Stage 完整同次返回；显式过去日 dynamic 使用当前真实时钟，保存产品仍不可改写。单列 read_basis；返回确切保存产品对应的 workspace_plan_product_attempt，同时保留最新失败 attempt。 |
| `v4/manager_research/service.py` | 缓存身份区分省略 view 的内部旧调用与显式 dynamic；内部旧调用继续使用保存 cutoff，原 HTTP auto/history 合同保留。避免当前回看修复影响既有计划稳定读取。 |
| `v4/manager_research/workspace_daily_channels.py` | A 对账原产品 selected/watch/excluded/unassessed 总数和源身份，保留未映射/拒绝引用、原风险；H 消费经原门禁核实的 Stage 结果及同 run 执行引用；O 消费原最终 ledger，并要求匹配保存证据才能标有效零。 |
| `v4/manager_research/workspace_plan.py` | 数字齐全但量来源未证明时，仍尝试原日线 supplement reader；只使用同一原响应经过验证的六个量值，不给绝对单位盖章；保留有效面板价格与前 60 日高点。诊断列出缺失/重复/非法日期字段及原 owner 拒绝原因，诊断与策略输入身份分开。 |
| `stage_center/consumer.py` | 在原 consumer 出口保留原 verified selection provenance，供 H 精确绑定；没有创建第二选择器。 |
| `ops/run_manager_announcement_cycle.py` | 保存/读回原执行上下文，避免正式产品的运行类别或身份在循环结果里丢失；未增加 producer，未假造 Reader/Reviewer。 |
| `apps/web/src/api/managerWorkspace.ts` | GET/POST 保留 plan、selection、announcement 三日期及 view，仍走原 API 和原校验器。 |
| `apps/web/src/manager-selection/catalystObservationPanel.ts` | 日期与视图经 URL/请求/重载一致传递，迟到旧请求不能覆盖切日后的状态。 |
| `apps/web/src/manager-selection/dailyChannels.ts` | 校验确切产品 attempt；无归档 O 不能成为 READY_EMPTY；展示未映射源代码和 mapped/unmapped 原风险，全部按文本渲染。 |

`research_attention.py` 的原两门策略和 ledger、`workspace_identity.py` 的核心归一化、US 具体实现、BUY 门禁、Vibe8910 均未改。RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。未启停服务、未改真实研究数据。

### 原有效零与未知的可执行区别

A 完整原产品的明确 NOT_SELECTED 可得到 READY_EMPTY / 0；原 owner 选中 H5354 但尚无可核映射时，返回 PARTIAL / null，源代码及原判断保留。混合输入中可映射的合格行继续显示，未映射记录不会拖空它们，也不会被偷偷变成 HK.05354。

O 只有完整原 ledger、无待核、原 owner 已保存且 run/SHA/attempt 一致，才显示 READY_EMPTY / 0。未归档和输入不完整为 null；已有部分合法行保留 PARTIAL。其他通道缺件可使整体 owner attempt 为 PARTIAL，而已完整的 O 仍可合法为零。后续 attempt B 失败时，已保存产品 A 仍引用 A 的原准入终态，最新失败 B 仍单列显示。

H 的“输入不足、selected_rows=0、write_performed=false”不是有效零。必须是原算法执行后保存的合法零行三件、精确日期/池和同 run 执行证据。

## 4. 独立复验、实际测试结果与剩余门禁

主要环境：Linux x86_64；CPython 3.14.6，pytest 9.1.1；pandas 3.0.6 / pyarrow 26.0.0；Node 24.19，Vitest 4.1.10，TypeScript 5.9.3。前端 DOM 验证是测试环境中的原 renderer，不是 Mac 浏览器。命令、版本、退出码和源 SHA 在 checks 下保留。

| 检查 | 本轮实际结果 | 能证明的范围 |
|---|---|---|
| 根针对性 Python 8 文件 | 106 passed，1 skipped | 107 cases，包含原 ledger；skip 为未提供的原实机 fixture，不能写成 107 passed |
| 历史独立门禁 | 40 passed | 28 个根回归 + 12 个独立用例；真实 SafeRoot I/O、边界、路径、UTF-8、SHA 与不改档案 |
| 历史等规模独立探针 | PASS | 7 个合成档案 / 147,031,510 B；无 journal、114,688 B 探测、0 正文读取，未使用 Mac 原大计划 |
| 公告完整原导入链与原门禁 | 完整链 PASS；14 passed / 25 deselected | 原组件、合成完整输入；数值代码、H5354、混合代码、明确未入选、晚导入与 view 隔离 |
| HK 完整 Stage | 9 passed | 原 select_hk_four_lane、原 SelectionStore、完整 consumer，显式原依赖 overlay；合成 membership/D1/执行 receipt |
| 原 supplement reader | 14 case 通过断言 | 1 个有效 READY，12 个畸形/越界拒绝，1 个合法 PARTIAL_WITH_PENDING；不是 14 个市场输入已 READY |
| 最终前端独立运行 | 50 passed，3 failed | 新 Readback 5、日期 8、原 daily 7、独立边界 11 全通过；原 runtime 19 passed / 3 failed |
| 原 runtime 对照 | 附件 16 passed / 6 failed；R1 与 R2 都 19 passed / 同 3 failed | 余下三项没有在 R2 新增，仍未关闭 |
| 原 Python 五套件 | 附件与候选都是 95 passed / 38 failed | 相同 133 IDs，无新增、无解决原失败；完整门禁仍 FAIL |
| 原完整前端 typecheck | 两个统一测试镜像均同 6 条错误 | 类型检查 FAIL；缺 ResearchView.vue 与 issue8R2.ownerObservations.json，衍生 2 implicit-any 和 2 unused ts-expect-error |
| Mac build / deployment / 8873 UI / natural | NOT_RUN | 不能从本地通过推断现场通过 |

原 38 项失败清单完整保留在 `checks/root/original_comparison_final.json`，没有全归咎于环境。其中原 issue24 的 6 个 bad_readback 断言显示保存回执终态合同分歧：某些失败读回场景已写成功 attempt。此原问题未由本轮关闭，必须在完整现场源码中裁定和修复，不能删断言或只验证 consumed 标志后发布。

三项剩余原前端 runtime 失败分别涉及 publication_date alias、旧默认 GET 的重新绑定、以及原首屏整段文本断言。日志与 R1 同源对照保留。最后独立检查新发现的 unmapped 风险未显示已经实际修复并完成 RED→GREEN；未清除这些原失败记录。

独立测试的精确输入/产物/run/SHA 见 `checks/announcement/`、`checks/hk_rebound/` 与两份完整 Python API → TypeScript fixture。全部标识为合成输入，不能覆盖下面的真实数据缺口。

## 5. 真实输入缺口及恢复责任

| 路径/目标 | 已有真实证据 | 原 owner 与下一步 |
|---|---|---|
| 10/09 历史 | cutoff=09:30+08；7 个已有计划全部生成于 10/10–11；旧读正文累计 84,227,585 B 后报扫描超限 | 原 ManagerResearchStore/history 只读复跑，准确得到无当时合格计划；事后产品不得补写盘前时间 |
| A，公告 10/08 / 目标 10/09 | UI 观察 392 目录条目、281 源代码、55/32/121/73；catalog run=4b69fa03fbfc4c48b1c410239332505e；没有随包附原 import receipt | 原 ManagerResearchJobService.import_announcement_analysis 和 run_manager_daily_announcement：核 evidence run、正文、独立 Reader/Reviewer、handoff、import/readback。catalog run 不能当 evidence run |
| H，10/09 | D1 receipt EXPECTED_MISSING，metadata invalid 20261008；无 10/08 master 条目；10/09 的 693 行 snapshot 在 17:31:16 才采集；10/08 面板 finality=NOT_ATTESTED、units=NOT_PROVEN | 原 ensure_hk_security_master 的 reuse-only / 精确 verified-source 恢复，再经 v35_dispatcher.research_panel_daily_hk、materialize_scheduled_preselection 与原 Stage。新补采时间必须真实，无法恢复当时证据就保持历史缺口 |
| O，10/09 / 10/12 分别核 | 现有 214 strict、286 near、34 pending 只属研究初筛观察；未提供逐 symbol 的 60 会话、5 个前序完整量值及当日量、最终已保存 ledger | 原 HK_0_2 panel / hk_daily_supplement + workspace_plan adapter + research_attention ledger。读取新 diagnostics 后逐股列实际缺失/非法 session 和字段，再查原缓存/TDX。测试里的日期不能冒充市场实测缺口 |
| I，10/12 | 原 run=1e9d511515de47599f05539e43e79b81；46 material + 15 projection 去 global manifest 后相同，2 identity components 变化 | 在刷新前保全该保存产品与当前完整 prehash；精确对比相关输入，不广泛忽略 SHA，也不靠新计划掩盖旧样本 |
| N | 固定 binding plan_material_refresh_only=true、announcement_collection_enabled=false；原 cycle 没有完整 Reader→Reviewer→register→import 自动派发闭包 | 原主控与原调度 owner 核真实 Reader/Reviewer heartbeat/身份及 dispatch，走原 canary/发布。单改 enabled 或用手动补跑不计自然通过 |

HK 恢复源码已从固定 HK 提交找回，详见 `recovered_dependencies/DEPENDENCY_RECOVERY_REVIEW.md`。execution_evidence 原 Git blob `3af4fb13f7da60e0822827fb834c671cef16a372` 与上传 consumer 的依赖调用匹配。两个 ensure 原源分别属于 actual_pool_scheduler 与 canonical_reference；canonical 前镜像与当前测试支持根不同，不能整文件覆盖。候选的 ensure 没有直接增加该 flag，现场须按角色和前镜像合并。

原 `docs/hk_history_backfill.md` 也已找回并完整读取，固定 commit `3ac5233e5928cefef8c1db6896950a1e7cede0cb`。它规定既有分钟数据恢复路径；不能当作 60 日日线数据已齐的证明。先缓存、再原 TDX owner，未使用 Futu 额度来源。

## 6. 三种时间口径的结论

| 口径 | 读取与本轮证据 | 最终边界 |
|---|---|---|
| 历史 PIT | 过去日 auto/historical，守住保存 cutoff 和原当时可用时间 | 没有 10/09 合格原计划就保持无当时计划；55/214/backfill10 不补入 |
| 现在回看 | 显式过去日 dynamic，read_basis=RETROSPECTIVE_CURRENT_TIME；合成原链证实晚导入产品可合法消费，保存旧计划字节不改 | 可以展示现在核实的研究结果；保存计划可能仍因真实输入变化而 STALE，其他合法通道不因此清空 |
| 自然日常 | 必须原调度在实际交易日按原日历触发并留下完整 run/SHA/receipt | 本轮 NOT_RUN；手动、dry-run、canary、回看、US 映射不代替 N |

H 的原 Manager 消费阶段是 STAGE_0935_0940，本来晚于 09:30 盘前界线。已有 SAME_DAY_CATCHUP 时槽可在 Stage 之后归档研究结果，但其实际 execution_kind/timing 必须保留，不能称 09:30 盘前自然产物。本轮未改阶段和时槽。

## 7. 如何继续

按 `MAC_ACCEPTANCE.md` 在完整现场源码的隔离候选中逐文件核前镜像、应用补丁、核后镜像和原门禁，再经原发布流程记录新的加载身份。`check_candidate.py` 只读核字节，不部署、不运行 owner。`NEXT_MAC_TASK.md` 是可直接交给原 Mac Writer/独立 Reviewer 的精确续办任务。

目录内容：`before/` 与 `after/` 为真实源码；`changes.patch` 可审阅和反向撤回；`BEFORE_AFTER_SHA256.json` 是 22 项字节清单；`checks/` 保留正负测试及独立证据；`original_evidence/` 保留用户问题包的小型原证据；`recovered_dependencies/` 是有固定来源和角色边界的原文件。整个交付的文件清单与 SHA 见 `DELIVERY_MANIFEST.json`。未附 venv、node_modules、dist、原市场大数据、原 147 MB 计划或认证资料。
