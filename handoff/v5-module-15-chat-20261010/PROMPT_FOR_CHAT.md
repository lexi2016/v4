# 请实现原15号模块美股到港股映射

## 必须使用用户指定的 Superpowers 插件

用户明确指定已安装的 Superpowers（plugin://superpowers@openai-curated-remote）。本会话须实际选择并使用该插件的相关技能，不能只在正文写插件名称当作已调用。先按 using-superpowers 判断应使用的流程；修复按 systematic-debugging，必要设计/计划在本模块范围内完成，再按 test-driven-development、requesting-code-review 与 verification-before-completion交代码和可核验证据。复用既有总体计划，不再发起全仓设计或仅交第二份计划。

如果本会话无法访问该插件，说明实际入口/可见限制，不声称已启用；把这一问题回传嘻嘻。仍如实区分候选、静态检查、实际测试和Mac验收，禁止伪造执行。


你只负责原M15，不接管M03采集、M02港股来源、M04归档生产或M18经理/API/前端。用户按原18模块分别开Chat；原编号和P0—P5不变。请复用既有源码审查，直接交M15最小候选，不重做整库审查，也不只返回另一份泛化方案。嘻嘻负责Mac落地独验，跨模块问题由集成者转交对应owner。

先读START_HERE.md、SOURCE_INDEX.md。代码观察基线固定f7cb731c384ee6890a87d16c19a5b5a621779477；其他固定commit只作具体语义donor。未知Mac前像不妨碍基于该固定目标交候选，但安装前必须逐文件核对。

## 一 先交源到目标映射与改动边界

SOURCE_TARGET_MAP.csv须列donor commit/path/function、目标文件、原模块owner、已等效能力、必要delta、依赖/manifest/PIN变化及跨模块请求。

可修改范围：M15自有适配器us_mapping_daily.py、us_mapping_io.py、us_mapping_scope.py、daily_us_owner.py，必要的M15专属新增文件/测试，M15自有vendor/us_mapping_baseline内映射owner/消费桥接，以及对应us_mapping_source_manifest.json。每项仍须有实际需要，不能为凑文件数重构。

M15材料映射函数目前物理位于manager_plan_baseline闭包的issuer_us_relations.py、research_evidence.py、research_attention.py。先复用这些固定原函数，说明如何通过M15接口调用；确需独立闭包时只做最小、来源固定的M15私有封装，保留原算法，列完整依赖和byte identity。不得直接修改M18的共享vendor，也不重写一套关系算法或复制整套经理系统。

只读参考/禁止跨写：cloud_us_collector/cloud_transport、原采集ops与source store、M02/M04生产模块、manager_plan及其vendor、current_us_research跨模块编排、module_api/api_gateway、manager-workbench前端及共享调度/发布文件。必要变化列CROSS_MODULE_REQUESTS.md交对应owner或集成者，不在本候选夹带。

## 二 固定输入合同

M03输入是同一原owner的精确三文件：research/peripherals/manifest.json、research/peripherals/<US session>/external_finance.json、receipts/research/peripherals/<US session>/external_finance.json，逐文件SHA及原取得回执可核。最近完成session由原US日历、America/New_York/DST和cutoff决定，不能用HK目标日代US session。保留phase、capture/publication/available时点、raw response SHA、原安全字段及缺报价状态。

原配置24行业代理/33证券仅是固定样本范围；M15消费实际配置和产物，不将其说成全市场或4键采集。缺源时明确SOURCE_MISSING/CANNOT_CONFIRM等原状态，不调用采集、不补零、不伪造三文件。M03真实采集和自然slot未证不由M15合成测试代签。

M02输入分别提供native identity、主表参考日、HK目标/资格日及资格状态。M04输入是原主体、正文/span、source refs/hash、publication/retrieved/available时间和允许的原standing contract。实际历史取得时点不存在就保持缺口；不能把reviewed_at或新取得时点回填为历史可用。

## 三 两条路径分别完成

种子daily复用原reviewed artifact、registry/daily_match_symbols、_relation_available_at与原build/persist/read。LITE/COHR/AVGO/CIEN四键只在原关系可用且行情准入时join raw_individual_up；三张可匹配卡和另两张无daily键主题卡保持。DIRECT_NAMED_COMPONENT_SUPPLY、PRODUCT_PEER、OPTICAL_TRANSPORT_PEER不可互换，范围外上涨股保持未评估。合法完整输入下零匹配才是该范围的有效空。

材料路径复用material_us_relations→collect_attention_evidence/us_mappings/us_mapping_diagnostics→research_attention的原函数。行业/主题按原业务证据join raw_industry_up，不强求显式ticker；个股按明确ticker关系join raw_individual_up，不能仅凭行业词汇。两路各自留输入身份、匹配/未匹配/拒绝原因，缺native master、无正文关系、缺取得时间、过cutoff、源SHA变化准确拒绝。

输出诊断至少区分：合法报价、上涨、关系匹配、时间/身份准入、有效结果、范围外、无材料、材料被拒、资格未知。数量来源可追溯且不硬编码33/4。四键daily已经评估，不应被材料或HK_CONNECT另一lane缺口覆盖；材料未评估也不能被四键成功覆盖。

## 四 修M15自己的最小合同缺口

1. owner版本：旧persist_daily_run仅有now；R3版本有timeout_seconds/execution_context、budget、dispatch journal/publication intent及_read_exact_run。先核M15实际调用需要，再复用匹配版本和完整依赖。不得删kwargs、吞TypeError或只加签名shim。新增写路径仅限M15自有输出合同，逐条列明；不扩大系统权限，不放开任意I/O。跨模块service/router接线仅提请求。
2. 旧receipt：M15的us_market_bridge应复用同一原store._receipt_matches。只接受完整合法新形状或恰缺market_snapshot_captured_at与market_snapshot_source_response_sha256的精确旧形状。只缺一项、多缺、改值、额外字段继续拒绝。payload/manifest绑定、原receipt字节SHA、session/phase/cutoff与安全验证保留。原source store和receipt不改写；共享M18 bridge副本需要相同改动时交M18请求，不跨写。
3. 精确读回：本次M15保存按指定daily run及artifact SHA独立读回，latest观察另报；若实际owner还有dispatch/terminal则按其同run合同校验，不借另一run。未知副作用先查原run/attempt，不能盲目重试。失败保留既有成功。
4. 闭包：M15 manifest目前39项，namespace、入口常量、_LEGACY_MARKET_SNAPSHOT_RECEIPT_FIELDS、schema_values.py、JSON和日历及传递依赖完整。若候选增加材料闭包/R3 owner，给差异和真实新计数，不硬凑原39。来源字节或manifest变更同步更新相应M15 PIN，禁止去掉PIN或回退到外部同名包。

## 五 给M18的输出和集成请求

交M15独立产品或稳定读接口：schema、HK目标/参考/资格日、US session/phase/cutoff、实际generated_at、execution_kind、来源三SHA、关系artifact/registry身份、材料及native引用、daily run/artifact与精确读回、分路径结果/拒绝/范围/资格及原安全字段。

材料路径没有独立原store时说明如何由M15提供固定结果并交M18按原workspace合同保存，不新建平行经理store。经理run不是M15 daily run。M18后续需验证消费身份、经理产品及同run terminal、普通GET/API/页面，并保留历史只读、CURRENT_RECOVERY和迟到响应边界。current_us_research已有dynamic覆盖路径只是参考，不证明普通auto已通过。

上述M18/UI/API能力未集成时，如实列联调缺口；不阻塞独立M15候选，不宣称普通页面完成。M13公告Chat另行工作，共享文件由集成者统一合并。

## 六 返回完整可应用候选

- START_HERE.md、固定候选commit/基线、SOURCE_TARGET_MAP.csv、依赖/manifest/PIN变化及范围内逐文件说明。
- before/after完整修改文件、runtime.patch、reverse.patch，逐文件before/after SHA；新增文件完整交付。
- M15必要测试源码、实际命令/cwd/解释器/依赖、原始日志/exit；定向、聚合、真实重放分别记录，失败与NOT_RUN保留，不skip补绿。
- MAC_APPLY_AND_ACCEPTANCE.md：前像核验、独立根、原输入只读、候选应用/回退、精确run与两路径真实验收。安装路径未知不得猜覆盖命令。
- CROSS_MODULE_REQUESTS.md：每项写请求编号、M02/M03/M04/M18 owner、固定位置/最小复现、所需输入输出、兼容与验收；无跨模块问题也明确写无。

具已授权写权限时只提交lexi2016/v4独立M15开发分支并远端读回；不改main/现役分支，不部署Mac。否则返回完整文件包。没有真实输入就标NOT_RUN并交准确缺件合同，不让用户重发已有固定源码。候选、合成通过、历史四键成功都不等于完整M15验收。
