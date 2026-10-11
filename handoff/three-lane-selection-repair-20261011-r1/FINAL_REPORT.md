# V4 三路选股修复候选与验收记录

**整体结论：PARTIAL / 未完成。已实际修改并提交候选代码，完成限定工程复现和独立复核；A/H/O 三路实际 owner → 保存 → 8873 API → 重载页面，以及下一自然交易日 N，尚未完成。**

本记录对应 2026-10-11 的问题包。不能用本地测试、HTTP 200、初筛数量、US 映射或回放结果替代三路业务验收。

## 1. 交付版本与文件

| 项目 | 固定身份 |
|---|---|
| 原问题包 ZIP SHA-256 | 3e389c00b4c82b4e987b3e06f51af70728d10b48e6d8de1f5554640e8b66eee7 |
| 问题包 GitHub 基线 | lexi2016/v4 @ 1ea98799d1763c88be2be1f0ee1b0ccec654532f |
| 先前 US 交付固定提交 | a1b722e4c82defcb9537d5c05915c6a8072c02d3 |
| 本地附件源码基线 | 31f5a39ce1ee7cd76bbf268e68760b6adc319774 |
| 本地候选源码提交 | cd93198cb0de06c8f32386ed1fc808a5b4e53bec |
| 新独立交付分支 | codex/three-lane-selection-repair-20261011-r1 |
| 远端载荷提交及读回 | 见同目录 SYNC_RECEIPT.json；分支同步不代表部署 |
| 范围 | 修改 8 个业务文件，新增 4 个测试文件；其余 118 个附件源码文件未改 |

此目录的 after/ 是 12 个变更文件的精确后镜像，changes.patch 是相对于附件基线的可审查补丁。BEFORE_AFTER_SHA256.json 保存每个文件的完整前后 SHA、字节数、Git blob 和附件所记 canonical SHA。check_candidate.py 只读核对包内字节及指定根的前／后镜像，不部署、不运行业务 owner。

附件的 126 个源码文件已全部重新核 SHA，并与本地基线逐字节比较。原 README、数据缺口、归档清单及清单核验都已读取。此附件本来就不是完整应用。

## 2. 已修改的行为

### R：有界历史查询

workspace_history.py 复用原 workspace_plan_runs/<date>/<run>.json 小型 owner journal。只有通过原 attempt 校验、同 owner、同日期、同 run，且 started_at 晚于历史 cutoff，才排除该不可能属于当时的 run。journal 只用于排除，不能准入计划；有机会合格的计划仍完整验证产品 SHA、日期、原 owner attempt、PIT 和冻结业务投影。

保留原 32 MiB 单件、64 MiB 正文累计、64 run 限制，新增每份 journal 64 KiB 边界。剩余正文预算在 SafeRoot 读取前传入，避免先超额读取再报错。损坏或错身份 journal 保持失败，缺 journal 的旧记录回落原正文校验。

独立实测使用**合成计划、原归档相同尺寸**：147,031,510 B 的目录只返回 23,388,302 B latest 正文和 4,146 B journal，即可确认这些 late runs 均不属于盘前。没有将这些合成数据标作真实 Mac 计划。

**残余仍开着：**若 latest 对应的旧 journal 缺失，latest 正文可能重复计入预算。独立反例中，latest 24 MiB + 同 run 24 MiB + 合法早期 run 20 MiB，虽只有 44 MiB 唯一正文，仍会因剩余 16 MiB 拒绝下一件。不能仅凭文件名、run_id、大小、mtime 或正文自报 SHA 跳过未验证字节。实际 Mac 的逐 run journals 尚未提供，因此 R 未验收通过。

### I：历史冻结字段与原语义身份保持一致

原 workspace_identity.py 已有严格的全局登记 SHA 例外；本轮没有扩大它。可复现的问题出现在后续历史冻结检查：外层语义 identity 已一致，仍用原始字典比较材料字段，导致登记溯源变化再次拒绝旧计划。

现改为复用原 semantic_value 比较冻结字段。相关 payload、receipt、路径、日期、PIT、原始正文，以及不属于该精确登记合同的 manifest 变化，仍被拒绝。

独立验证了同语义全局登记变化可读，以及 7 类真实语义变化继续失败。**这不是对真实 10/12 那次失效的结案：**原保存产品和当前完整输入/prehash 未附，尚不能复算其两项组件变化。原 46 个 material refs / 15 个 projection refs 的派生比较只能作为调查线索。

### H：摘要消费原 Stage 选择

workspace.py 保留同一次已读取、已进入 projection.stage 身份的完整 Stage envelope；不再次抓源。workspace_daily_channels.py 的 HK 路径消费原 canonical selection_markets.HK_CONNECT，保留原行顺序、rank、order、原算法和 source refs，停止从 workspace focus 列表推导 HK 选择。

沿原合同检查目标日 membership V2、精确 D-1 Top100、原 STAGE_0935_0940、原 selection run/三件 SHA 与 execution selection reference。原 Manager 就读取该阶段，本轮没有改成 0925。计划 cutoff 必须允许读取该阶段。

stage_center/consumer.py 仅让普通 HK 复用已有 _verified_selection_provenance。该 helper 没有改写；独立用真实 SelectionStore 证明它能拒绝 latest artifact SHA 不一致、CSV 内容篡改、receipt count 变化和 run 不一致。

新增明确拒绝 code/symbol 冲突、重复代码/rank、错误 projected order、显式安全标志冲突，以及原合同中的 D1_PRESELECT_REFERENCE、WAITING_0920_SECOND_FILTER、BACKFILL、prior-date 和 late replay 声明。会员过滤后不重排原 rank/order。

非空选择缺执行绑定时保留原研究行并标 PARTIAL；完整合法输入和匹配零行回执才可显示有效 0。尚未验证的输入保持数量未知。所有输出仍为 RESEARCH_ONLY、NO_BUY，natural_run_verified=false。

### O：使用原研究选择台账，单独输出输入诊断

O 摘要改为消费原 build_research_selection_ledger，核目标日、来源日、source identity、原规则及 decision digest，只展示原 SELECTED / NEAR_WATCH 判定。raw strict 或 near 不能代替原优先级、未决、排除与完整 accounting。

research_attention.py 已恢复附件原字节，SHA 为 4073ad6f0c36de045017dc8fa18433438cf63371c13588777117108945aad1bb。原两门规则、研究优先级、source-ref validator 没有改写。

read_rebound_screen 新增可选 diagnostics 输出。它在同一次原 Parquet/日历计算中，单独输出每股缺失/重复的 prior60、previous5 日期、历史数值状态、量来源及原 refs；不往原 screen 或 ledger 添加字段。成功结束才提交诊断，整次失败清空旧结果与部分行，refs 深拷贝；诊断绑定本次 cutoff、screen identity、来源日及自身 SHA。

独立用同一份**合成 Parquet 输入**调用附件原函数与候选，完整 screen、plan、attention、ledger 字典和身份均相同，10/10 断言通过。未证明单位的量保持未知；测试中的 pending 和缺失日期只属于该合成样本，不能当真实市场诊断。

### A 与前端日期/回读

ops/run_manager_announcement_cycle.py 的保存 owner 回读补回原 execution_context，防止合法 product/attempt 的同 run 语义在回读时丢失。未更改公告生产、分析、注册或导入 owner。

A 摘要继续要求 publication_date + target_trade_date + CONSUMED。没有将页面显示的 55 只写入代码，也没有用 catalog run 冒充 evidence run 或 owner import receipt。

前端保留 plan / selection / announcement 三个日期以及 view，canonical 参数优先于 alias；没有显式公告日时仍交原 HK 日历决定。日期或口径变化会清理旧结果；POST 与后续读回使用同一组绑定。工作台读取/刷新链路中，不同日期、旧请求和取消后的迟到响应不能覆盖当前页面；只有完整绑定相同时可保留 stale 结果。新增指定日期但响应漏掉 date_bindings 时拒绝读回。此次取消验证没有覆盖下方原公告采集控件的所有请求。

## 3. 工程验证及明确未通过项

| 层次 | 实际结果 | 范围 |
|---|---|---|
| 最新针对性 Python | 73 passed / 1 skipped | 20 history、45 三路通道、3 Parquet diagnostics、5 原 ledger；1 原实际 Mac fixture 缺件 |
| 原前端 runtime + 新日期用例 | 17 passed / 1 skipped | 真实 jsdom/原 API validator；唯一 skip 为缺失的实际 Mac Eastmoney fixture |
| Python → 原 TypeScript → DOM | 4 passed | 三路齐全及分别缺一路；其它合法通道保留，未知不显示 0 |
| 独立 HK 边界 | 30/30 | 合成 verified-reader boundary；保持原顺序与回放边界 |
| 原 SelectionStore + 未改 helper | 5/5 | 真存储校验、原函数 AST、只读与三件身份 |
| 原/新同 Parquet 比较 | 10/10 断言 | 原顶层函数隔离加载；共享相对依赖，非完整旧应用隔离 |
| 交付字节 helper / 补丁 | 18/18；补丁应用及反向撤回通过 | Python 3.12.14 标准库；隔离基线实际验证仅改 12 路径并精确还原，拒绝畸形清单、缺件、篡改与 symlink |
| 本次前端改动的传递闭包 | 0 类型诊断 | 原 compilerOptions、10 个源文件 |
| 原全项目 typecheck | FAILED：97 诊断 | 候选与换回附件原业务文件的对照逐条相同，新增诊断 0 |
| 5 个原 Python 套件 | FAILED：77 passed / 29 failed | 固定附件基线完全相同，candidate-only failure 0 |
| 完整 Stage consumer import | BLOCKED | 当前 execution_evidence 合同未附；没有提供兼容 stub |
| 完整应用 build / Mac / 8873 / 自然时段 | NOT_RUN | 当前工具环境没有该 Mac 运行会话 |

实际测试环境：Linux、Python 3.14.6、pandas 3.0.6、pyarrow 26.0.0；前端 Node 24.19.0、Vitest 4.1.10、TypeScript 5.9.3。28 个补齐的原 Python/JSON test-support 文件均从固定提交获取并核 Git blob；这些只供隔离测试，不能补成生产发行包。

**29 项原失败没有被统一归成缺依赖。**其中包括缺失 4 个 US 关系 JSON、旧 fixture 缺 v2 身份或 recovery 字段、日历/语义合同断言分歧，也包括 6 个原 issue24 bad_readback 注入：原外层末尾只检查 consumed，以及先写成功 attempt 再终态失败的断言分歧。这段已有流程本轮未改，不能据“基线也失败”宣称完整保存门禁通过。完整失败 ID 与逐类实证在 checks/ORIGINAL_REGRESSION_REVIEW.md 和 checks/original_suite_comparison.json。

本轮只有根 Writer 修改候选，专项 Reviewer 只读。原 Mac Luna Max Writer/Reviewer 的现场身份、加载字节及执行回执尚未建立。

## 4. A / H / O / I / R / D / N 验收

| 编号 | 本次结论 | 未闭合的实际证据 |
|---|---|---|
| A | PARTIAL | 原 catalog/body/semantic Reader + Reviewer、evidence_run、合法导入 receipt、实际 API 与重载页面的同日同 run/SHA |
| H | PARTIAL | 10/08 精确 authority、10/09 canonical D1 Top100、实际原阶段三件与执行回执；10 只 backfill 不计 |
| O | PARTIAL | 实际逐股 60-session / previous5 / 量来源诊断、原最终 ledger、保存产品和 API/UI；214 strict 不计最终完成 |
| I | PARTIAL | 已修复独立复现的历史二次比较；真实 10/12 saved/current 原始输入与 prehash 尚缺 |
| R | PARTIAL | 当前 Mac journals 与两种模式未执行；缺 journal 的 latest 重复预算残余未解决；所有已列事后计划不能进入 10/09 09:30 |
| D | 工程层通过，现场未验收 | 原投影输出合法 CANNOT_CONFIRM DTO 的单路缺件场景中，后端及 DOM 验证其它路保留、缺件计数为 null；任意畸形 DTO 的原整体拒绝合同未改；实际 8873 样本尚缺 |
| N | NOT_RUN | 下一实际交易日各原 owner 自动执行、归档、同 run/SHA 读回及页面重载回执 |

三种口径分别保留：

- **历史当时：**20261009 / cutoff 2026-10-09 09:30+08。问题包列出的所有计划都晚生成，不能成为当时计划。
- **现在回看：**使用显式 view=dynamic，在当前真实可用时间下消费合法原产物；不能回填历史 availability。
- **未来自然：**仍需要下一实际交易日的原调度回执。本次没有自然运行 PASS，手动操作不计。

## 5. 实际数据缺口和原 owner 恢复路径

| 对象 | 已有证据与缺口 | 原责任/下一动作 |
|---|---|---|
| 公告 10/08 → 10/09 | UI 观察为 55 selected、32 watch、121 excluded、73 未评估；缺原 import receipt | 沿 run_manager_daily_announcement 的 capture/resume → 实际独立 Reader/Reviewer → register-handoff → import → readback；先验证已有 evidence run，不能把 catalog run 当它 |
| HK membership / D1 | 10/08 master 缺条目；10/09 master 17:31 才采集；10/09 D1 receipt EXPECTED_MISSING，metadata invalid: 20261008 | 先用 ensure_hk_security_master 原 reuse-only / verified-source-store-root 找精确既有证据，再由原 research_panel_daily_hk / materialize_scheduled_preselection 与 Stage 执行 |
| HK0.2 / O 输入 | 10/08 provider finality NOT_ATTESTED，amount/trade units NOT_PROVEN；10/09 补充面板 10/10 才发布 | 读取同次 rebound_input_diagnostics，逐 symbol 列缺 session/字段；先查原缓存。补采前必须取得并读原 docs/hk_history_backfill.md，沿原 TDX 链，记录今天的真实 availability |
| 10/12 计划误失效 | 已知旧 run 和派生 refs 对照，但无完整旧/current 产品 | 原 ManagerResearchStore 只读导出精确 run、input_identity components 和相关 payload/receipt；原 gate 下作成对重算 |
| 自然公告链 | 已查固定 US 交付 binding 为 plan_material_refresh_only=true、announcement_collection_enabled=false | 原主控核当前 binding 和实际语义 agent 派发能力；通过原 canary/发布合同启用后，再等自然时段回执；不能只翻布尔值 |

原数据 owner 的两个 .v35 / .v4 根及 scheduler / API 根必须分别核对；路径相似不代表同一 authority。恢复时找不到当时证据，应保留历史缺口，不能把现在补采的 capture 时间倒填。

## 6. 运行身份与集成限制

问题包 API 配置所指源根为 /Users/lexi/Desktop/学习/agents调试/V4_US_MAPPING_DAILY_CHAIN_MAC_20261011_R1/integrated_release/manager-us-mapping-daily-chain-20261011-r1/app；canonical 为 /Users/lexi/Desktop/学习/v4_app。scheduler 是独立 hk-auto-d1-20261011-r1 根。

固定 GitHub 的原 activation receipt 与配置 SHA 相互印证，足以解释不可变 manifest 内 NOT_ACTIVATED 旧元数据的冲突，并选择该冻结附件作为**候选基线**；不证明本时刻 Mac 进程已加载本补丁。没有改写旧 manifest 的状态文字。

修改 cycle / consumer 后，原源码指纹与发布绑定会变化。必须使用原发布流程重建相应 candidate manifest、binding、canary 和独立 receipt，不能将新 SHA 填进旧回执伪装部署完成。

完整 integration、加载检查、部署/回滚步骤及 A/H/O/I/R/D/N 取证要求在 MAC_ACCEPTANCE.md。本工具环境没有访问 Mac 的能力，仓库 AGENTS.md 的既有授权限于独立分支同步，不包含 merge、部署或服务启停。

## 7. 使用顺序

1. 阅读本报告、BEFORE_AFTER_SHA256.json 和 checks/ 的独立审查摘要。
2. 在实际完整源的隔离候选目录运行 check_candidate.py。出现 BEFORE_MISMATCH 就逐文件合并，并保留 canonical/HK/US 未提交修改；不要整包覆盖。
3. 沿 MAC_ACCEPTANCE.md 做实际环境验证及原发布回执。changes.patch 和 after/ 不构成完整发行包。
4. 保存真实同 run/SHA、API/UI 与自然回执后，再逐行更新 acceptance.json。未通过项继续 PARTIAL / CANNOT_CONFIRM。
