# Issue #29：经理模块最小修复交付

本轮完成 **历史 reader 同合同重验** 与 **US reader 异常不阻断工作台** 两项代码修复，已做红灯复现、限定回归和独立审查。生产增量只有两个文件；另有五个测试文件。**三条业务每天自动运行仍未恢复验收**，目标日输入接续和原 US daily owner 的自动调用仍待实际 owner 回执定位。

固定输入为 [`b22836ef3f8fcc6b9218f3422a9bcd7aa61152e9`](https://github.com/lexi2016/v4/commit/b22836ef3f8fcc6b9218f3422a9bcd7aa61152e9)，需求以 [Issue #29](https://github.com/lexi2016/v4/issues/29) 为准。本包是模块补丁及必要后像，**不是完整应用、发布包或可整树覆盖的源码基线**。Issue #29 明确本轮由 Chat 提供代码/方案，发布冻结；本轮没有启动 Mac 服务、采集、执行正式计划、改 binding 或切换发布。

## 1. 两项实际修复

### B：历史指纹变化不再直接拒绝合法重验

原 `workspace_history.py` 在旧计划的 reader SHA 与当前源码指纹不同时，先返回 `HISTORY_READER_VERSION_CHANGED`，尚未读取原 owner 或检查原截止时点的输入。指纹覆盖整个经理源码及多项依赖，因此无关源码变化也可能触发这项早退。

新逻辑仍保留源码 SHA 作为身份记录，并要求：

1. 原产品先通过既有 schema、封存 digest、安全旗、日期/window、exact attempt 和 semantic version 校验。
2. 跨源码指纹时，**原件自身封存的** `workspace.read_context.contract` 必须是受支持的 `20260923.workspace-history-read.r1`。当前 API 返回的合同名不能替代原件字段；未证明或未知合同明确拒绝。
3. 由原 owner 在原 cutoff 下完整重验，要求 `input_identity` 和全部 14 个冻结业务字段一致，并重验 PIT。
4. 重验前后当前源码指纹一致，才返回 `consumed=true` 和 `read_context.reader_compatibility`。

没有旧 SHA 白名单，没有修改旧计划或 attempt，没有放宽选股、交易日、PIT 或量纲门禁。无 SHA 的 legacy 分支继续执行其原完整重验。若实际旧输入或业务投影已经不同，仍明确拒绝；本修复不保证任意旧计划都能读通。

真实 9/30 原计划 `ba13fba330464300b760fe940ba579a1` 未在本轮重验。下一步只需从原件读出封存合同、原 run/cutoff/attempt 身份，并在实际同一候选下重验，不要求先上传完整大计划或重建全部旧 release。

详见 [历史合同诊断](docs/HISTORY_CONTRACT.md) 和 [独立审查](evidence/review/independent_review.md)。

### US reader 失败的完整合同隔离

已在真实 Python manager GET → 冻结 Mac TypeScript validator 之间复现：旧异常返回缺少 `daily_run` 安全旗、schema、coverage 和 `reviewed_research`，前端抛 `WORKSPACE_SAFETY_INVALID`，已存在的公告行也无法通过工作台请求进入首屏。

`workspace.py` 仅修改该异常 handler：返回原合同所需的字段，状态为 `CANNOT_CONFIRM`，数量和日期/运行/来源身份为 `null`，plan reference 保持 `NOT_CONSUMED`。读取失败不能证明 owner 从未运行，也不能宣布已筛选零条。9/30 专属的事后研究引用按现有 Mac 合同返回未知空卡片，其余日期为 `null`；这是既有历史引用的日期边界，不是对每日选股日期硬编码。

成功 reader 路径、原 US 关系算法、registry、cutoff 比较和产品身份绑定未变。冻结前端 validator 未改。新测试证明原公告股票、理由和其他通道可继续进入原首屏 renderer，并保留错日与伪造 `VALID_EMPTY` 的拒绝。

**此修复不执行 `refresh_us_mapping_research`，不能据此宣布每日映射自动化完成。**

## 2. 原版本与历史成果核对

按 Issue #29 的记录，20:27 上线的观察基线为 `manager-workbench-r1-mac-20261008-api-r2`，manifest SHA 为 `2cc1447a740195c4f50299330d845635ddf762c45eb59586436a527e4f8b75a8`。这是固定历史身份，接手时仍须核实际 listener。

本轮隔离测试保留了 b228 的 Mac merged `service.py`、StoreError 版 `workspace_plan.py`、`workspace_daily_channels.py`、两个 Connect reader、`managerWorkspace.ts` 和 `catalystObservationPanel.ts`，没有拿较早 canonical/R1 文件覆盖它们。源码前像与九项保留 pin 见 [source_manifest.json](source_manifest.json)，组装来源见 [assembled_overlays.json](evidence/assembled_overlays.json)。该清单证明限定文件身份，不证明完整现役运行闭包。

已定位并保留的历史成果：

| 原证据 | 已证明的范围 |
| --- | --- |
| 9/29 公告原 run `c5d263c65c7540eba022d81e1f644002` | 原公告抓取、正文和分页身份；不改写成 9/30 新采集 |
| [9/30 17:20 自然回执](https://github.com/lexi2016/v4/blob/d26d34610e7021d9ad1712bc418a32d667b50bd2/research/manager-r9-consumer-r1-20260930/r3_business_fix_20260930/natural_1720_readback.json) | 原 HK 日面板和主表生产成功：membership 696、有效行情 689、主表 696；旧 capture 未保存原 per-plate 时钟，不足以证明 V2 资格 |
| [R10 原验收](https://github.com/lexi2016/v4/blob/815aac0e4f6751a8917e912eec339f1d56cab3ef/research/manager-selection-gaps-20261003/mac-business-r10/FINAL_ACCEPTANCE.json) | source=9/30、target=10/2 的历史回看：689 条决策，58 入选、349 观察、250 排除、32 未决，与原 API/UI 对应；不是本轮自然执行 |
| [旧 US PAGE/DAILY 交付](https://github.com/lexi2016/v4/tree/840b9538c45c9ba8fd56f8e89048aff230df0f0f/handoff/us-mapping-daily-workbench-20261005) | 五条 9/30 回顾卡、手动 owner/HTTP 读回和已安装的 09:27 配置；原记录仍为自然运行未验 |
| Issue #29 的 R2 公告观察 | 同产品 33 候选/54 观察/75 待评估，10/7→10/6→返回无串日；本包保留该修复，不把固定计数写入生产代码 |

用户所指完整 9/30 三路成功记录仍未全部定位。当前 plan reader 的拒读或 NOT_RUN 不能否定以上成果；这些不同日期、不同层次的记录也不能合并成三路日常运行已经完成。

[原 owner、版本、日期、输入路径、consumer、产物与 API/UI 对照表](docs/OWNERS_AND_DATE_RECONCILIATION.md) 已列出完整接续位置及逐项来源。

## 3. 精确交付与合并边界

| 载荷 | 内容 |
| --- | --- |
| [source_delta.patch](source_delta.patch) | 仅 `v4/manager_research/workspace_history.py`、`v4/manager_research/workspace.py` 两份生产增量 |
| [tests_delta.patch](tests_delta.patch) | 新历史 Python、新 US Python、新跨语言 TS 三份测试，加两份原测试的精确断言更新 |
| `after/` | 上述七份文件的完整后像；不包含完整应用、producer 或发布脚本 |
| `*.reverse.patch` | 对这七份文件的反向差异，仅供同一已核候选的逆向比较；不修改业务数据 |
| [source_manifest.json](source_manifest.json) | 每份文件前后 SHA256、Git blob、固定来源、测试关联及九项保留 pin |
| [MODULE_BOUNDARY.md](docs/MODULE_BOUNDARY.md)、[path_scope.json](docs/path_scope.json) | 精确允许路径、保护路径、单一共享集成 owner 边界 |
| [JOINT_REGRESSION.md](docs/JOINT_REGRESSION.md) | 与 #28 合并后的 A178/HK100、空/partial、Stage 完整输入和经理原成果共同验收要求 |

两个生产前后像：

| 文件 | Before SHA256 | After SHA256 |
| --- | --- | --- |
| `workspace_history.py` | `da5e1223326631cc9070c3059ca606bac3840ef468ad5c06f2f3a51534f82ec1` | `d46b84f084af5eb695812a7052520147722a80a6885fb3dfdb4c1a18de3c72b5` |
| `workspace.py` | `183e3ebd0322883a8f8cef37c0244f424f16c63d3120245e263bb9585133dea3` | `ab25d4856019b10bda1cb73928e5e2e75fad870a8321025019dceeb2cf0b6b52` |

经理代码归本 Issue；预选池/Stage 归 #28；共享 `app.py`、启动配置和发布入口由一个集成 owner 管理。两处 #28 的 app.py 回退修复不在本包中。前像漂移时由该 owner 比较并重新合入必要 hunk，不能整包覆盖或更新 manifest 以跳过差异。

复用既有、未修改的 [R1 只读校验器](../manager-workbench-repair-20261008/tools/verify_delivery.py)，通过 `--package-root` 指向本包。下面只校验准备合并的隔离源码，不启动服务：

```bash
python3 /absolute/handoff/manager-workbench-repair-20261008/tools/verify_delivery.py \
  --package-root /absolute/handoff/issue29-manager-daily-repair-20261008 \
  --source-root /absolute/staged/api-source --profile api --against before
```

准备后的同一候选再用 `--against after`，并按实际源码根分别检查 web/tests profile。该校验器检查本包全部七份后像及选定 profile 的目标文件/保留 pin；不安装、不改源码、不验证当前 PID 或完整运行闭包。已有 before/after 隔离核对和正反补丁字节回环均通过，见 [验前像](evidence/preflight_frozen_before.json)、[验后像](evidence/preflight_isolated_after.json)、[补丁回环](evidence/patch_roundtrip.json)。

## 4. 实际测试与独立审查

环境为 Linux、Python 3.14.6、Vitest 4.1.10；使用既有冻结依赖，没有重新安装或升级依赖。详细命令与环境见 [TESTING.md](docs/TESTING.md) 和 [results.json](evidence/results.json)。所有输入为临时存储/合成 fixture，未调用真实 Mac 服务或市场采集。

| 批次 | 结果与范围 |
| --- | --- |
| 新增历史合同测试 | **27 passed**；此前红灯 21 failed/1 passed，后续补充边界覆盖 |
| 新增 US Python 隔离测试 | **7 passed**；此前 6 failed/1 passed |
| 新增跨语言 TS 测试 | **6 passed**；此前 5 failed/1 passed，明确复现 `WORKSPACE_SAFETY_INVALID` |
| 前端限定组合 | **13 passed**；新 6 项加既有 dailyChannels 7 项 |
| 限定 TypeScript 编译 | **exit 0**；仅明列 API/首屏/测试依赖文件，不是全应用编译 |
| 扩展 Python 候选 | **160 passed / 1 failed**；同范围原基线为 **126 passed / 同一项 failed**，新 34 项全部通过 |
| 历史组合候选 | **81 passed / 1 failed**；原基线为 **54 passed / 同一项 failed** |
| 独立复核 | 两生产文件及五测试未发现新的 Critical/Important；独立 Python **114 passed / 1 既有失败**，新 TS **6 passed** |

各批次重叠，不能相加。两项保留失败：

- `test_exact_panel_selected_without_latest_substitution`：前后均为 `PLAN_HK_02_PANEL_LATEST_MANIFEST_UNREADABLE`。
- `test_missing_original_archive_is_not_empty_connect_selection`：旧 fixture 预期 `READY`，冻结 Mac 合同返回 `PARTIAL`；两版本一致。

没有删除上述用例、补 xfail 或修改其冻结规则。完整父页还缺原 `managerAnnouncementAnalysis` / `announcementAnalysis` 文件及匹配的 research renderer 版本；原 runtime suite 在收集阶段失败。没有补 stub 或拼旧组件通过构建，不能声称完整普通页面通过。

[独立报告](evidence/review/independent_review.md) 与 [机器回执](evidence/review/independent_result.json) 保留命令、退出码、日志身份和上述限制。

## 5. C/D 每日接续的具体剩余工作

**C 尚未修复。** 10/8 HK02 已存在，不能再写成最新只有 10/2；仍缺精确 10/7、目标日主表/V2 publication 和成交量单位证明。原 HK gate 本来可以从同一次 capture 接续 membership/V2、HK02、master。需要 10/7、10/8 的 claim/dispatch、`request.business_date`/argv、HK child 五项 pin、同次 capture/panel/ensure 回执与实际写读根，才能区分未触发、日期错传、root 差异或后段失败。缺文件不是充分根因，不能据此另建 producer。

**D 尚未完成。** b228 service 已有 `refresh_us_mapping_research(target_trade_date, *, now)` → 原 `persist_daily_run`，不是“缺 service 方法”。已核四个 US slot 只生成 peripheral capture，没有证明每日 mapping 已执行。现有已核 operator 只准备 plan-only binding；旧无界 PREOPEN 同步尾调用不应恢复。须补当前 US 模块/seed/registry/dispatch/renderer 身份及实际 daily 生命周期，再由唯一集成 owner 在原有生命周期接入有界调用，记录独立 run/target/session/cutoff/产物/读回，同时保留正式 plan 原预算。

本机下一步按此顺序推进：

1. 核现役 listener、两生产前像、完整 build closure 和 #28 的单一集成窗口，合入两项候选；保留 Mac merged 文件与累计修复。
2. 对真实 9/30 原件读取封存合同、原 cutoff/attempt/SHA，在同一候选下执行只读重验，保留成功或具体拒绝原因。
3. 对 10/7、10/8 沿原 producer 取得最小回执，定位第一次未接续的步骤；只有此时才确定 C/D 后续代码位置。缺日或补采方案继续由原 HK02/TDX/tdxpy owner 处理，未知量纲仍未知。
4. 在本机发布冻结解除并协调后，以原 owner 分别完成公告、US→HK、超跌的真实双日期输入→执行→持久化→API→普通页面验收；`HK_CONNECT` 资格通道不得改名成 US 映射。
5. 观察实际自然时段；每条链的日期、run、来源 SHA、运行种类和页面结果必须对应。手动、补跑、回看、canary 或 HTTP 200 均不能替代自然运行。

上述最小回执字段、已找到的原 owner 路径与证据 URL 均列在 [owner/date 对照](docs/OWNERS_AND_DATE_RECONCILIATION.md)。不需要上传原始行情、凭证或完整大计划。

## 6. 九层验收状态

| 状态 | 本轮实际适用范围 |
| --- | --- |
| `IMPLEMENTED` | PASS：仅上述两项经理模块代码修复 |
| `TESTED` | PASS_SCOPED：新增及限定工程测试；扩大回归保留两项基线失败，非全应用通过 |
| `REVIEWED` | PASS_SCOPED：独立代码审查，保留运行与源码闭包限制 |
| `INTEGRATED` | ISOLATED_SOURCE_SLICE_ONLY；完整现役/#28 合成候选 NOT_RUN |
| `DEPLOYED` | NOT_RUN，Issue #29 发布冻结 |
| `API_VERIFIED` | 合成原 owner/route/DTO 有证据；live Mac API NOT_RUN |
| `UI_VERIFIED` | 合成 request/首屏 renderer 有证据；完整普通页面 NOT_RUN |
| `BEHAVIOR_VERIFIED` | 两项故障的限定工程行为通过；真实 9/30、双日期日常链 NOT_RUN |
| `NATURAL_VERIFIED` | `NATURAL_SLOT_UNVERIFIED` |

安全边界始终为 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。没有修改选股阈值、BUY/模型门禁、Vibe8910、旧业务产物或共享发布配置。
