# 测试范围与正式运行证据

本轮验证的是问题包所提供源码切片上的受限差异。**代码、独立复验和补丁核对已有证据；受保护集成、部署、真实10/8补算、正式API/普通页以及连续自然日期仍未验收。** 不将隔离测试计作自然运行。

## 1. 实现者与独立复验分别记录

| 执行者／测试组 | 本轮结果 | 主要合同与证据 |
| --- | --- | --- |
| Writer：workspace / history / daily / dispatch / US / HK 主组合 | **112 passed** | 原owner、日期和故障接续、新保存计划及原HK入口；[实现者报告](evidence/writer/writer_final_report.json)、[主日志](evidence/writer/writer_final_pytest_main.log)。 |
| Writer：普通页面相关Vitest | **34 passed，4个文件** | 实际Python owner/route DTO、原API校验、计划保存/US daily展示、dailyChannels；[日志](evidence/writer/writer_final_vitest.log)。 |
| Writer：限定strict TypeScript检查 | **退出码0，无诊断** | 仅managerWorkspace API DTO、dailyResearchRun和researchAttention；[日志](evidence/writer/writer_final_tsc.log)。不是完整父页面构建。 |
| Writer：namespace与页面交叉组 | **2 passed；另25 passed** | 两个owner namespace另测；25项与112主组合和独立路由探针重叠，**不相加**。命令及原日志见实现者报告。 |
| 不同身份Reviewer：US原owner / workspace | **18 passed** | 原peripheral payload/receipt/manifest、精确US session与registry时点、超时/忙隔离、不可变run、故障DTO与计划读回；[最终合并报告](independent_tests/final_review.json)。 |
| 不同身份Reviewer：每日调用完整接续 | **14 passed，1个renderer检查另列** | 原reviewed import→daily-cycle→原plan owner保存→API读回；跨日/休市、晚到、重启/同slot重放、计划已提交后的回执恢复、独立预算；[最终合并报告](independent_tests/final_review.json)。 |
| 不同身份Reviewer：HK发布链 | **4 passed** | 原actual child及capture/publish/readback；含第二日正常推进latest后再读第一日、cache重入不重采、原件不改和真实旧artifact篡改拒绝；[最终合并报告](independent_tests/final_review.json)。 |
| 不同身份Reviewer：精确页面接续及公告窗口 | **实际Python路由1项、TS投影2项、来源窗口1项通过** | 真实路由DTO进入前端校验/投影；研究cutoff与实际read_at分离；有效公告产品的原多日范围及真实source SHA改变。[最终合并报告](independent_tests/final_review.json)记录各自范围及原日志。 |
| Root交付工具：stdlib校验器 | **24 tests通过** | 错根、前后像、源/补丁SHA与字节、符号链接及额外目标拒绝；[日志](evidence/package/verifier_tests.log)。工具另经独立包装复核。 |
| Root实际补丁及范围核对 | **6类profile、33文件、3保留pin、2份旧修复增量通过** | 正向应用、所有after字节/文件集合、逆向完整恢复；[补丁报告](evidence/package/patch_verification.json)。[范围报告](evidence/package/source_scope_audit.json)核17个本地保留身份及actual HK非HK AST。 |

各组共享fixture和用例，数量不求和。重新跑过同一组也不累计成更多独立覆盖。报告保留原命令、cwd与捕获时日志位置；本包的实现者日志副本集中在 `evidence/writer/`，独立测试与日志集中在 `independent_tests/`，文件名保持不变。

冻结源码对应的唯一最终独立结论是 `independent_tests/final_review.json`。同目录的 US、daily、HK 分阶段报告及早期红测作为过程证据保留，不替代最终报告；证据优先级和各日志索引见 [EVIDENCE_INDEX.md](independent_tests/EVIDENCE_INDEX.md)。

## 2. 三个曾被局部通过遗漏的接续已明确验证

1. **保存后再打开同日期页面。** 原问题是仅隔几秒，嵌套screen cutoff和显式publication参数就改变输入身份，导致计划被误判过期。本轮同完整绑定用封存研究上下文重跑原reader；actual read_at另记真实读取时间，前端仍核同run/SHA/immutable attempt及时间顺序。原默认多日公告范围不被缩小，真正不同日期或来源变化仍不认作旧计划。
2. **晚到公告进入后续计划。** 09:27封存后09:45到达的合法产品不倒入旧计划；原新评估入口能读取该source SHA，原10:00 catch-up实际消费它、产新run，普通GET读回新计划，原盘前历史仍保留。旧独立断言要求09:45 GET立即改变09:27计划身份，与封存cutoff合同冲突；其红测留在 `daily_owner_chain_cutoff_contract_red.log`，更正后完整后半链通过，不将这次断言修正冒充生产缺陷修复。
3. **第二天发布后仍能读第一天。** 新gate原先把共享latest整文件绑定为昨日不可变artifact；次日合法更新会误报旧链损坏。现将发布时pointer字节作为chain内不可变快照保存，仍验证原日期manifest/panel/master entry和真实artifact。独立两日测试在相同根执行原HK updater/publisher后，重验第一日chain、master reader、lane-ready与cache，原件字节不变；篡改真实旧V2 artifact继续拒绝。

完整裁定见 [REVIEW_CONTRACT_DECISIONS.md](docs/REVIEW_CONTRACT_DECISIONS.md)。这三个隔离结果均不代表实际10/8来源、Mac进程或自然执行已通过。

## 3. 合成边界与实际执行范围

Python使用 **3.14.6**；已验前端工具为 **Node 24.19.0、Vitest 4.1.10、TypeScript 5.9.3、jsdom 28.1.0**。版本和源码装配身份见 [runtime_environment.json](evidence/runtime_environment.json) 与 [test_baseline_identity.json](evidence/test_baseline_identity.json)。交付校验器另使用系统Python的stdlib运行。

所有测试中的报价、reviewed关系、SDK返回、公告研究、capture、时间和canary均为明示的离线合成fixture，未调用真实Mac或外部行情。实际原store、reader、FastAPI路由和publisher可在隔离根执行；TestClient只是进程内API，不是部署后的8873服务。

US测试使用原peripheral store/reader及其payload/receipt/manifest结构。每日调用测试保留原dispatch/service/store，但因所给共享包闭包缺失，以精确文件路径加载supervisor叶模块，并明确注入synthetic binding校验边界。原renderer/完整包检查另行尝试并报告阻断，不以这一注入称真实binding已启用。

HK不同用例的边界分别记录：初始三个独立用例以可读parquet/manifest/pointer fixture替换panel updater边界；新增的两日用例执行**原HK0.2 updater**和原V2/master publisher，仅对Futu、冻结模型seed/reader及daily supplement边界合成注入。Writer正向组也覆盖原updater。真实Futu/TDX/冻结模型运行、合法现场资格/单位与最终性尚未证明；不把合成行数当真实候选数。

完整普通页父级依赖未提供，因此验证范围为API DTO、限定renderer/DOM与投影以及路由到投影的接续。没有用替身补全父页面后宣称完整UI通过。

## 4. 已知失败与阻断如实保留

### HK supplement：13 passed / 2 failed

这两个精确nodeid在本轮源码与原本地基线 `3f2aa6c92d87da098d33b5349698e55d337fd165` 上均由独立Reviewer复现，断言位置虽随新增测试移动，失败值相同：

| 原用例 | 基线与本轮实际结果 |
| --- | --- |
| `test_screen_uses_master_universe_sidecar_volume_and_missing_only_price_overlay` | input_candidate_count实际0，fixture期待3。 |
| `test_complete_panel_history_skips_sidecar_and_preserves_canonical_baseline` | input_candidate_count实际0，fixture期待1。 |

日志见 `independent_tests/hk_supplement_two_failures_base.log`、`independent_tests/hk_supplement_two_failures_current.log` 与 [本轮完整supplement日志](evidence/writer/writer_final_pytest_hk_supplement.log)。原screen/PIT/资格规则保持，不能为消除fixture红色而放宽规则。这两项不被忽略为“全部测试通过”。

### 完整应用闭包未通过

- 干净导入原scheduling包先在 `stage_center._selection_parts._namespace` 缺失处阻断；[干净导入证据](evidence/closure/clean_scheduler_import.json)。没有新增Stage shim。
- 在已明示的独立模块加载边界内继续检查原renderer inventory，仍缺 `apps/__init__.py` 原字节，不能称实际CLI或enabled binding已生成。`apps/api/__init__.py` 的41B canonical原件存在，不能把它也写成缺失或拿它替代上级marker。
- 原普通页依赖 `apps/web/src/api/managerAnnouncementAnalysis.ts` 和 `apps/web/src/manager-selection/announcementAnalysis.ts` 未提供；完整父页面构建/挂载未通过。
- 这些云端源码切片缺口不证明Mac完整应用也缺相同文件。应由唯一集成owner核真实闭包，不能补造来源文件以通过验证。

## 5. 在已核来源的隔离源码根复现

GitHub仓库根是handoff仓库，不是可直接运行的v4_app。先由唯一owner核明完整累计源码、依赖与本包profile映射，再在隔离候选应用已核补丁。下面变量均须指向实际存在的绝对路径：`manager_source_root` 为测试装配源码根，`manager_python` 为原合格Python，`manager_handoff_root` 为本包根。Mac临时目录使用真实路径，保留原SafeRoot拒绝符号链接的行为。

```bash
cd "$manager_source_root"
PYTHONPATH="$manager_source_root:$manager_source_root/upstreams:$manager_source_root/tests" \
  "$manager_python" -m pytest -q \
  tests/test_manager_workspace_exact_page_binding_20261008.py \
  tests/test_manager_workspace_owner_20261008.py \
  tests/test_manager_history_contract_20261008.py \
  tests/test_manager_daily_automation_20261008.py \
  tests/test_manager_daily_dispatch_20261008.py \
  tests/test_manager_us_daily_automation_20261008.py \
  tests/test_hk_daily_publication_chain.py
```

独立Python测试使用 `MANAGER_TEST_SOURCE_ROOT="$manager_source_root"`，路径指向本包 `independent_tests/`。完整命令和独立UI运行说明见 [独立测试README](independent_tests/README.md)；实际renderer检查必须单独运行和报告阻断，不能混入通过数量。

前端在原 `apps/web` 目录使用现有开发依赖，指定测试用实际Python：

```bash
cd "$manager_source_root/apps/web"
V4_TEST_SOURCE_ROOT="$manager_source_root" V4_TEST_PYTHON="$manager_python" \
  ./node_modules/.bin/vitest run \
  src/manager-selection/dailyResearchRun.spec.ts \
  src/api/managerWorkspace.dailyAutomation.spec.ts \
  src/api/managerWorkspace.usIsolation.spec.ts \
  src/manager-selection/dailyChannels.spec.ts

./node_modules/.bin/tsc --noEmit --strict --target ES2022 --module ESNext \
  --moduleResolution Bundler --lib ES2022,DOM \
  src/api/managerWorkspace.ts \
  src/manager-selection/dailyResearchRun.ts \
  src/manager-selection/researchAttention.ts
```

本次临时依赖链接已移除，未写入源码差异；本包不携带node_modules，也不替代现场现有依赖闭包。

## 6. 正式运行与最终层级

[acceptance_status.json](acceptance_status.json)分别列出IMPLEMENTED、TESTED、REVIEWED、INTEGRATED、DEPLOYED、API_VERIFIED、UI_VERIFIED、BEHAVIOR_VERIFIED、NATURAL_VERIFIED及对应证据。

真实10/8事后补算、受保护共享集成与#28联合保留、部署后的API/普通页、至少两个连续适用交易日的自然运行均未由本轮执行。入口与每项判定见 [HOST_EXECUTION.md](docs/HOST_EXECUTION.md)。`NATURAL_SLOT_UNVERIFIED` 不因以上固定日期测试通过而改变。
