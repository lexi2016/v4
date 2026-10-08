# Issue #29：模块边界与累计修复保留

本文件是代码交接及本机集成约束，不是发布授权。依据为 Issue #29、固定提交 `b22836ef3f8fcc6b9218f3422a9bcd7aa61152e9` 的 Mac 交接，以及只读核对的 Issue #28 元数据。当前发布冻结：Chat 不启动服务、不采集、不执行正式计划；Luna Max 后续按既有 Writer/独立 Reviewer 分工处理。

## 1. 最小边界

保留同一个 V4 用户入口、API 和权威研究数据层。两个业务任务分别提交最小文件差异；一个集成 owner 负责共享文件合并和后续统一构建。无需第二个网站、长期端口、producer 或发布系统。

| 范围 | 路径或入口 | 本轮边界 |
|---|---|---|
| 经理业务，归 #29 | `v4/manager_research/` 中本次已证实断点涉及的具体文件；`apps/api/v35_api/manager_research_router.py`；`apps/web/src/api/managerWorkspace.ts`；`apps/web/src/manager-selection/` 的经理展示文件 | 只在最终变更清单逐项列出的文件内修改。目录归属不等于允许整目录复制。Stage 读适配、共享 owner 和已有累计修复仍受下列保护约束。 |
| 当前历史兼容断点 | `v4/manager_research/workspace_history.py`、其必要的独立测试 | 以 b228 所指实际 R2 文件作为前像。`workspace_read_control.py` 未改，以固定来源和 SHA 保留；本包不替换当前合同或移除 PIT/owner 校验。 |
| 预选池与 Stage，归 #28 | `domains/preselection.py`、`domains/_preselection_parts/`、`domains/preselection_materializer.py`、`domains/stages.py`、`domains/stage_input_producer.py`、`domains/stage_scoring.py`、`stage_center/`、`infrastructure/preselection_pool_*`、`infrastructure/stage_*` 及相关 Stage API/UI/tests | #29 不修改、不随包重发。canonical 拆分实现与运行版单文件实现由 #28 映射，不能互覆。 |
| 共享 API 合成入口 | `apps/api/v35_api/app.py`、`apps/api/v35_api/run.py` | 只由单一集成 owner 处理。#29 交接不携带这两份完整后像。`app.py` 已确认的两处预选池遗漏修复归集成 owner / #28；不在 #29 重做。 |
| 原调度与发布入口 | `ops/run_v35_macos_scheduler.py`、`ops/run_v35_macos_scheduler_daemon.py`、原 launcher、发布/CAS/recovery helper、live plist、启用 binding | 本轮保护。业务任务可指出所需绑定参数和依赖，不能分别改共享 launcher 或发起切换。原 b228 交接中的 phase2/phase3 工具存在不等于可执行，本包不携带这些工具。 |
| 原输入与权威数据层 | 原 `v3_shared_data` / `upstreams/v3_shared_data`、security master、TDX/tdxpy、行情/资格 producer、原计划及结果目录 | 只读定位原 owner 的触发、日期、输入/输出路径和回执。缺文件不可用新 producer、复制别根 latest 或改旧产物代替。经理侧调用修复必须消费同一权威合同。 |
| 既有研究与安全边界 | BUY/model gate、Vibe8910；经理目录内的 `stage_*` 读适配及 Stage 原件 | 保持原样。`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。 |

最终 `after/`、patch、依赖清单只列此次实际变化的字节；未改文件以固定来源和 SHA 引用。历史完整后像仅供核对，不能作为整应用拷贝源。

本次最终独立审查范围收敛为2个生产文件：`workspace_history.py` 的历史合同重验，以及 `workspace.py` 中原US reader异常分支的DTO修复；精确5个测试路径见 `path_scope.json`。`workspace_read_control.py` 未改，保持保护引用。US异常分支补齐原Mac API合同、安全旗与unknown数量，不运行US owner、不替换原映射算法或改前端validator。

## 2. 必須带入同一候选的既有修复

下面的 SHA 来自冻结 Mac 交接，是文件来源证明，**不是接手时实际 listener 的证明，也不能代替行为回归**。

| 文件 / 已有行为 | 已知冻结身份或来源 | 合并要求 |
|---|---|---|
| `service.py` 的 Mac 已合并增量 | SHA256 `16edcea443ed19fa5a2808f9160b4255bcfe65c309eb48207815afdd834fdd37`；旧 R1 incoming 为 `fe6cb338015eed9299d29bfc842b7e936b750a6246a14dd61049e6fe5da16a19` | 沿 Mac 合并后的前像改最小差异；不能复制旧 R1 后像覆盖它。 |
| `managerWorkspace.ts` 的 Mac 已合并增量 | SHA256 `5854af5d1e2b33cc469ba6abd49096bb2f727280161c663edf4b757742f9ce92`；旧 incoming 为 `703506a0880138122b53de4eeb5f47ed8a790bb6b97b0b56d4bf467de61c68da` | 保留现有 API 类型、日期和状态适配，核对最终组合后的实际 API→TS 消费。 |
| `workspace_plan.py` 的 StoreError 隔离 | 后像 SHA256 `c734f3e986af81b39bf11c09d93caf7a205526c8b4df940a4beeb011f74e0ebb`；原最小 patch SHA256 `ca26534fddda111b81494ab177ecd5702c278f1d2baa6b1609877cc19655ede8` | 缺当日证券主表时保留具体失败原因且 workspace 可读；不得恢复成 500，也不能宣称数据准备完成。 |
| `workspace_daily_channels.py`、`connect_selection.py` 的 Mac P2 适配 | SHA256 分别为 `de4e91150d3198dda40e170660de8a83c717811d478411941015b7cf1364c15f`、`eaa01a13d8065b11cc8397a12edaad8b892f183158aa1f9475d29645dee09d83` | 未改则保留；若接口联动需改，以这两份来源及实际前像核定最小增量。HK_CONNECT 资格输入与美股→港股映射仍分开。 |
| 公告同一产品消费、切日期不串日 | #29 记载的局部 API/UI 验收：33 候选 / 54 观察 / 75 待评估，公告日 10/7→10/6→10/7 | 同固定产品核代码、理由、来源和计数；换产品按新 run/SHA 验收，不能硬编码 33/54/75。 |
| #22 合格关系显示、#24 计划保存/读回 | #29 要求沿原 owner 保留这些已修复路径；仍需本机当前来源清单 | 联合测试保留 VERIFIED_RELATIONS_PASSED_TWO_SOURCE_PIT 的原语义及无损、有界读回，不以旧 issue 当今天运行结果。 |
| 预选池两处既有修复 | #28 / A 预选池固定交接 `4ad7cc52257b49470b3004ebfee9649af43189dd`；#29 已确定 R2 漏带 | 合成候选必须传入 `preselection_source_root=resolved_pool_source`，并保留空列表不会覆盖已有有效汇总的行为。由指定集成 owner 合入，不重造池。 |
| 发布序列化比较、CAS/recovery | #29 记录序列化比较局部已验；#28 保留 guard pin、missing-active recovery 两个独立阻断 | 保留已接受行为；#28 未关闭的发布缺陷仍是未完成项。旧 recovery-module PASS 不能覆盖后续集成 FAIL。 |

`ManagerSelectionView.vue` 的冻结 SHA256 `3db9731126b88555fecf60ac1a12e952b06ed70f838e078207fad9da32c2bed5` 已在父提交内。没有针对该文件的新缺陷就不重复携带。原 `workspace_history.py` 前像为 `da5e1223326631cc9070c3059ca606bac3840ef468ad5c06f2f3a51534f82ec1`；`workspace_read_control.py` 为 `491e3569e8f00586ca6f4e9982e182584d2f2a0437f83da66767b7ffdbf1fb25`。

## 3. 单一集成 owner 的具体工作次序

1. 接手时只读记录 listener 的 release root、解释器、入口、运行 inventory/manifest、共享 app.py 与本次目标文件 SHA，同时记录 #28 候选状态。20:27 的 R2 身份只作历史锚点，不能假定仍活动。
2. 用该现役源码建立隔离集成候选。核对已接受的累计差异清单，将 #28 与 #29 的最小 diff 逐项合入；所有不在变更清单的文件继续来自同一实际前像。遇前像漂移、同路径冲突或未附依赖先停止这次合并并回报具体差异，不能改期望 SHA 让检查通过。
3. `app.py` 的两个预选池差异由集成 owner 在当前实现上合入。候选的 `app.py` SHA 当然会变化；证明它保留经理行为和预选池行为的方式是联合回归，不是要求它等于任一旧 SHA。
4. 完成模块测试和 [联合行为回归](JOINT_REGRESSION.md)。测试日志必须记录同一个组合候选身份、固定输入身份、实际命令/解释器和具体断言。仅单模块 PASS、HTTP 200、CAS 前像相等均不足以接受共享候选。
5. 独立 Reviewer 检查精确 diff、输入/输出合同和联合证据。仍在发布冻结时只交候选与报告，`INTEGRATED` 最多限于隔离合成范围；`DEPLOYED/API_VERIFIED/UI_VERIFIED/NATURAL_VERIFIED` 分别按实际动作记录，不预填通过。
6. 未来解除冻结后，唯一集成 owner 才按现有发布流程处理单一窗口。模块交接不附可自动整树覆盖、修改启用 binding 或切换 listener 的新脚本。本文件不解除冻结。

## 4. 根因表述与运行证据边界

- `app.py` 漏带修复解释预选池零行回归，不能当三条经理日常链所有故障的唯一根因。
- 9/30 四份 PARTIAL plan 不覆盖用户报告的全部原业务成功。历史 reader 拒读也不能反推旧结果不存在。
- 10/8 行情面板已存在；精确 10/7 面板、目标日证券主表及 universe V2 链仍有缺口。不得照抄旧“最新只到10/2”的结论。
- phase3 9/25 canary 未执行、binding 未启用；测试、dry-run 或 disabled draft 不证明日常接续。自然时段未观察仍为 `NATURAL_SLOT_UNVERIFIED`。

## 来源

- [Issue #29](https://github.com/lexi2016/v4/issues/29)；[Issue #28](https://github.com/lexi2016/v4/issues/28)。
- [b228 Mac README](https://github.com/lexi2016/v4/blob/b22836ef3f8fcc6b9218f3422a9bcd7aa61152e9/handoff/manager-workbench-mac-completion-20261008/README.md)、[file_map](https://github.com/lexi2016/v4/blob/b22836ef3f8fcc6b9218f3422a9bcd7aa61152e9/handoff/manager-workbench-mac-completion-20261008/file_map.json)、[分层状态](https://github.com/lexi2016/v4/blob/b22836ef3f8fcc6b9218f3422a9bcd7aa61152e9/handoff/manager-workbench-mac-completion-20261008/evidence/status.json)。
- [A 预选池固定交接](https://github.com/lexi2016/v4/blob/4ad7cc52257b49470b3004ebfee9649af43189dd/handoff/a-preselection-source-20261008/HANDOFF_SUMMARY.md)。只读读取时间和范围见 `metadata_check.json`；其中历史测试报告不是本轮复跑。
