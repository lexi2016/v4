# 请交独立 M13 的完整代码候选

## 必须使用用户指定的 Superpowers 插件

用户明确指定已安装的 Superpowers（plugin://superpowers@openai-curated-remote）。本会话须实际选择并使用该插件的相关技能，不能只在正文写插件名称当作已调用。先按 using-superpowers 判断应使用的流程；修复按 systematic-debugging，必要设计/计划在本模块范围内完成，再按 test-driven-development、requesting-code-review 与 verification-before-completion交代码和可核验证据。复用既有总体计划，不再发起全仓设计或仅交第二份计划。

如果本会话无法访问该插件，说明实际入口/可见限制，不声称已启用；把这一问题回传嘻嘻。仍如实区分候选、静态检查、实际测试和Mac验收，禁止伪造执行。


你是18个模块 Chat 中的第13号，只负责原总计划“公告研究与选股”。请先读本包 START_HERE、SOURCE_MAP、ACCEPTANCE，再基于固定源码交方案与具体代码。不要再做全仓泛化审查，也不要只交另一份计划。

分工：你负责唯一 M13 代码候选和后续必要修复；嘻嘻统一接收所有模块候选、处理共享集成，并在既有 Mac 环境落地、测试、验收和精确回传。你不部署、不切换端口、不操作现役 V4，不替其他 Chat 修改业务。

## 一、先核实际路径，明确文件白名单

代码基线：`lexi2016/v4@f7cb731c384ee6890a87d16c19a5b5a621779477`。材料：`9cac0fffe12fda6ec06e106206e0c647b427913f:handoff/v4-code-optimization-review-20261010`。

请先用固定 Git tree/文件内容确认实际 M13 owner、adapter、reader、入口、测试和 source manifest，输出逐文件白名单及 SOURCE_TARGET_MAP。每条写清：source commit/path/blob/SHA-256、原 owner/函数、V5目标、已有等效能力、具体差异、为何必须修改、是否共享依赖。

本包已核四个 M13 入口，见 SOURCE_MAP。总计划中的 announcement_daily.py 是规划名称，固定目录内不存在；不得把规划文件写成现役路径或杜撰前像。新增文件标 NEW，先说明既有入口无法承载的最小理由，不另造第二套 owner/importer/算法。

只在白名单内写 M13 独占文件及其针对性测试。固定 vendor 胶囊默认只读；若确认原 owner 真有缺陷，先交原版本精确复现、最小 donor 补丁、更新后的完整闭包/manifest 候选，不能偷偷改冻结字节、仅改 PIN 过关或改现役 V4。

共享依赖及其他模块只读：manager_plan*.py、daily_owner_adapters.py、module_api.py、api_gateway.py、web.py、共享 contracts.py、调度/账本/发布、共享前端、V4活跃路径和 M18 经理 vendor。不得以“完成 M13 闭环”为由直接修改。

## 二、业务范围与复用顺序

负责原目录采集、正文读取与来源留存、原 Reader 语义、原独立 Reviewer 结果接入、原 review 修订绑定、原 owner 导入和 M13 独立读取。按 source run → catalog → body corpus → semantic → reviewer → owner product/receipt → exact readback 逐阶段定位；具备 reader/wrapper 不等于真实 producer 已接通。

1. 先复用原 HKEX/东方财富采集与原资料缓存。目录缺页、预算中断、正文失败和真实空分别保留；发行人有界采集不写“全市场”。只为实际缺的阶段提供最小代码，不为了接口暂空重采成功源。
2. 保留原语义算法和分类、审查门禁、body/span/source/hash/时间关系。Reader 与 Reviewer 身份必须真实独立。无实际原 reviewer 返回就维持阻断，不让集成器编造 PASS、不把自评标独审、不造 source origin。
3. 复用原 OfflineAnalysisOwner/DecisionRevisionOwner。完整校验原 parent product/receipt/recovery、semantic/reviewer/decisions SHA 与修订身份后才允许针对新输入的导入；失败不覆写成功产品。现有 392 决定和已消费成果禁止重做或重导。
4. 独立读取按 target/publication/cutoff、owner root、binding、source run、product/receipt SHA 验证。GET 只读，不触发采集、导入、重算或隐式新任务。默认日期必须经原日历真读取，不能改显式结果标签冒充默认查询。
5. 冻结字节、原文引用、取得时点、cutoff/PIT、HKEX首次发布时间、Connect/正式资格未知继续保留 CANNOT_CONFIRM/NOT_ASSESSED。不可回填时钟、null填0、unknown充入选，亦不可放宽来源资格换绿。
6. 为真实新适用日提供原阶段接续入口及状态合同。明确手动恢复/历史回放/自然触发身份。尚未真实执行时仅交代码与验收步骤，状态 NOT_RUN。不要通过复制旧392或修改日期证明新日生产。
7. 如实际目标仍有 COMPLETE_EMPTY 合同缺口，独立、最小修复且覆盖下游消费合同；目录空须有真实完整性证据，不能把缺目录/正文失败当空。这项不阻挡既有合格非空公告材料交付。
8. 先核已有局部“最终SHA绑定顺序、CLI完整readback”修复是否已等效；只在命中实际目标版本时复用。不要合并 unrelated 超跌修复或混淆历史 runner 与 current-live owner。

## 三、已完成证据不重做

392决定（2 event / 0 earnings / 26 observe / 270 not selected / 94 unknown）、经理 run `5b4feaf7ef7d4d13bec639e90b6d3db0`、经理产品 SHA `56556a67ddc1a562e82b38e750be92fcfda070945397cc4eacffd1c79f42bcf0`、生成时间 `2026-10-10T02:23:24.502381+00:00` 见 START_HERE，均为已有回执而非本轮复测。

公告 evidence/source run 与经理 run 是不同身份；不能拿5b4f填公告source_run。缺未公开的精确来源身份就标 SOURCE_NOT_PROVIDED 并交最小只读核对请求，不伪造、不把全部正文搬云端作为交代码前提。当前 Mac前像缺口只阻止具体安装，不阻止基于固定V5源码交可审候选。

原 V4 审查11条逻辑路径大多为经理/共享页面语义 donor。它们不授权 M13 修改 M18，不要求全改，不整套覆盖 V5。

## 四、交给 M18/共享集成的合同

请交 CONSUMER_CONTRACT.md 与 clearly synthetic 或来源可核的 fixture，逐项说明：

- M13 产品/receipt/binding/path/schema版本、target与publication日期、source/evidence run、reader/reviewer身份、实际cutoff/capture、代码与来源摘要、安全字段及未知限制
- 已提交和独立读回条件；未导入、缺源、PARTIAL、真实有效空、STALE、未评估、资格未证的可区分状态
- M18必须引用的原始M13身份，以及经理run/产品/终态由M18自己提供，不能由M13捏造
- 消费者如何验同一声明的M13产品，如何拒绝旧revision/换正文SHA/错日/错cutoff
- 普通analysis与selection路由应暴露什么；analysis成功不等于selection/经理保存成功
- 每个跨模块请求写明接收方、精确路径/函数、前后合同、兼容性、消费fixture和验收责任

shared gateway/普通页面/M18若缺接线，交 CROSS_MODULE_REQUESTS.md，不附可直接覆盖共享文件的runtime.patch。所有共享集成由嘻嘻统一落地。不要为测试mock一个“保存成功”并当真实M18集成通过。

## 五、必须交回的完整候选

1. START_HERE.md：唯一基线、候选commit（无写权限则说明无commit）、M13范围/白名单、实际结果、剩余缺口。
2. SOURCE_TARGET_MAP.csv：逐来源/目标/版本/函数/sha映射，含已等效不改的证据。
3. before/、after/完整修改文件；runtime.patch、reverse.patch；逐文件before/after SHA-256、Git blob（可得时）、新增/删除路径。无差异则明确说明并提供可复用入口证据，不为交补丁制造修改。
4. 依赖、manifest/PIN及源码闭包变化清单；原算法未变与source身份未被弱化的逐项证明。
5. M13针对性测试源码、命令/cwd/解释器/退出码/原始日志；失败、阻断、NOT_RUN都保留。只针对合成输入通过不得写真实工程/业务全绿。
6. CONSUMER_CONTRACT.md、M13消费fixture、CROSS_MODULE_REQUESTS.md；无跨模块请求时明确NONE。
7. MAC_APPLY_AND_ACCEPTANCE.md：真实前像核验、隔离候选、必要定向回归、原M13独立读回、候选回退和回传。Mac未知路径不得猜写覆盖命令。现有392只验原身份，不再生成/导入。
8. 若有阻塞，只列精确文件/函数/缺失合同和最少补件；现有GitHub材料自行读取，不让用户重复整理整库。

如有已授权GitHub写权限，只可交M13独立开发分支并读回固定SHA；不得改main、现役分支、其他Chat分支或部署。没有权限则交完整候选文件包。M13候选、Mac定向测试、已接入页面、自然接续是不同阶段；不得自行计为M13完整完成。

