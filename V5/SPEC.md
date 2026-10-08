# V5 模块独立发布架构规格草案

日期：2026年10月8日，香港时间

状态：书面规格草案，首轮范围见第5.1节。2026年10月8日用户要求建立独立 V5 分支并逐个迁移，现进入首轮实施计划审阅；产品实现尚未开始。未创建产品骨架，未运行产品代码、构建、测试或部署。本次建立的 V5 目录只保存文档，不能称为可运行的 V5 工程。

## 1 建议与需要审阅的决定

建议采用一个 V5 源码仓库、按业务模块构建不可变发布包、按模块独立 worker 执行、统一只读 API 与界面入口的结构。每个模块拥有自己的版本、依赖锁、运行状态、输出目录及发布指针。跨模块以版本化数据合同交换不可变产物，不相互加载对方的活动源码目录。

这比直接拆成许多网络微服务更适合目前的来源依赖和运行规模，也能真正解决“升级一个模块覆盖另一个模块”“源码已有功能但活动 producer 没有”“主进程 Ready 而子业务停用”的问题。纯粹把大文件拆小、继续共用一个发布目录，不能达到这个目标。

建议保留已经验过的算法、阈值、排序及安全门，只重做边界、版本管理、编排与证据连接。V4 继续运行，V5 先读取已核准的同一权威来源、写入隔离的研究结果；不能另建同源采集器或修改 V4 的现役状态。某一来源何时由 V5 接管，需要独立的验收与 owner 切换。

本轮请先审阅三个决定：

1. 是否接受“单仓库、独立发布包和 worker、统一入口”的总体方向
2. 是否接受下文的业务边界，以及 V5 初期只读复用 V4 权威来源的迁移方式
3. 是否批准首轮仅做“独立版本组合与发布健康，加一个超跌 reader 的隔离影子运行”；其余业务模块只保留边界，不在首轮实施

本文件本身就是本轮待审规格，不要求批准后再重写一份相同规格。用户批准这份草案及首轮范围后，才编写并提交实施计划，由用户审阅计划并选择执行方式。当前文件不授权创建工程、改现役、启停服务或发布；其余模块后续扩展仍需相应规格审阅。

## 2 对目标的理解

已知目标是独立重构 V5，让 A/H 预选、阶段选股、收盘复盘，以及经理公告、超跌、US 映射每天形成有日期、有依据、有逐股理由的研究结果。打开页面能看见当前目标日真实完成了什么、还缺什么，并能追溯到相同 run 和 SHA。

成功不以“服务在跑”“HTTP 200”“某日页面有股票”判断，而以来源、算法、触发、输出、API 和 UI 的完整连接判断。模块可独立升级、发布和回滚，失败范围不能无故扩散。按用户最新分工，dot在当前工作中编写代码，云端 Codex 只做定向测试，本地 Codex 只承担后续获批部署、原生兼容验证与反馈，不在本地并行开发第二套代码。

必须保留的约束：

- V4 与 Vibe 原有服务在替代验收前保留，V5 不能覆盖其源码根、运行配置或状态目录
- A 股与 HK 合同保持分离；HK 证券开市与港股通开市、价格日与资格来源日分别判断
- A 股只要有有效、可追溯的预选来源，就可以进入阶段选股；缺失或 partial 的可选子池不全局阻断，坏来源隔离；显示分页不能把完整选股输入截成前 200 行
- HK 严格池的资格、来源、模型、Top100 完整性与日期门不放宽；有坏的目标日输入时不能悄悄回退到旧日
- 真正 PIT、来源取得时间、真实运行时间与研究 cutoff 不得伪造；恢复、历史回看、手动运行不能升级成自然成功
- 研究结果保持 research_only=true、production_allowed=false、buy_gate_updated=false、orders_sent=false；不接账户、不产生订单、不变更 BUY 门
- 已验证的算法优先复用。算法变更应是另一个独立讨论和验收，不夹带在工程重构中

运行部署仍受现役机器可达来源、原生依赖和本地数据约束。本文不预先决定把实时运行搬到云端，也不假定云端可直接取得本机行情或凭证。

## 3 证据基线与可靠范围

本稿区分三类事实：本轮只读查看的固定 GitHub 文件；既有现役审计记录；设计建议。固定 commit 只是源码快照身份，不自动等于正在运行的字节。

| 范围 | 固定源码基线 | 本稿可确认的范围 |
| --- | --- | --- |
| Stage 和 HK 10月8日准备 | c563adc067fcd6a6b95fe756c7618f46d2f4389e | 含不同日期、不同根的快照和候选；10月8日候选明确未部署、输入阻塞 |
| 经理工作台 | 9dfa50346357b6dc4b2463a30dcbf3718fce2f03 | 带 canonical/API 快照；不能把 canonical 的所有能力视为现役已接通 |
| US 每日映射 | 840b9538c45c9ba8fd56f8e89048aff230df0f0f | release delta 表示该次部署增量；自然验收仍需独立证据 |
| 公告日期目录与分析 | a7732310a5262b59c95a30fdf5d7bedc9910939f | 已有手动 exact-date 产物与导入验证；不等于自然语义分析链已完成 |

现役审计已经确认：API/scheduler 为 hk-research-calendar-all-r1-20261007，Stage 注册仍为 20261003-hk-binding-wrapper-r3。10月7日多次启动中，经理 hook 因 app-root 与 pin 不一致停用，主 scheduler 随后仍进入 DAEMON_READY。API plist 缺 owner binding 变量是已证声明缺项，但不能据此声称已在运行进程复现 API 拒绝。

最新只读现场反馈还确认：活动 shared producer 是 Sep23-hk02-owner-rebase-r2；其 CLI 没有 eligibility-source-date，hk_0_2 生产入口用 signal date 同时选择 master 和 score，活动 registry 也没有分日期传参。其 panel_latest 为10月2日，正确10月7日 panel 在所查活动根中缺失。本文未直接读取该机器，沿用现场反馈，完整路径与 SHA 必须在实施前以现役清单核对，不能补写或猜测。

GitHub 的分日期消费/投影实现已经检查独立资格来源的 run、捕获时间和 SHA，但“新 reader 已存在”不能证明旧 producer 可产生其要求的数据。10月8日要求 target=10月8日、price_signal=10月7日、eligibility_source=9月30日；已有旧信号池被拒绝是正确保护，不能通过换标签解决。[S2][S3]

## 4 三种可选结构

| 方案 | 发布与故障边界 | 优点 | 主要代价 | 结论 |
| --- | --- | --- | --- | --- |
| A 模块化单体 | 文件和包可分开，仍共用解释器、依赖环境与整套发布目录 | 最少运行组件，最接近现状 | 独立回滚受共享依赖限制，子模块异常与运行身份容易耦合；若整包替换仍会覆盖其他模块 | 不满足本次独立发布的核心目标 |
| B 单仓库独立模块包与 worker | 每模块不可变包、独立执行环境、单 owner 输出、独立发布指针；通过产物合同交互 | 保留现有算法，兼顾隔离、回滚和小规模运维；按需要逐步拆分 | 需认真建立合同、版本组合准入及持久调度回执，不能只拆目录 | 推荐 |
| C 全量网络微服务 | 每模块服务、数据库、网络 API、独立部署 | 跨机器扩容及团队分工空间大 | 额外引入网络故障、认证、服务发现、消息基础设施和分布式一致性；并不自动解决旧源码/来源错配 | 有明确跨机负载、团队或可用性需要时再演进 |

方案 B 的 worker 可以是按任务启动的独立进程，也可以是常驻进程；这个选择由模块负载决定。不能以“同一 Python 进程加载多个活动源码根”代替隔离。公共合同库按版本随模块构建，不使用可变的共享 PYTHONPATH 或环境自动拾取其他版本。

前端也需明确发布边界。长期建议一个轻量界面外壳，业务页以固定版本的静态包注册，每页只读该模块公开合同。模块页回滚只切其静态包与兼容合同，其他页面不重新打包。若后续选择单个前端整包交付，应明确它是一个共同发布单元，不能宣称所有业务页面已可独立发布。首轮不实施这一页面拆包方案，仅提供影子结果和健康记录的可审阅读回；无需先引入微前端基础设施。

## 5 建议的模块边界

“独立模块”同时具备明确输入合同、唯一输出 owner、单独版本和测试、可独立部署的执行入口。算法内部小函数不必都变成服务。

| 模块 | 拥有的职责和产物 | 直接依赖 | 明确不做 |
| --- | --- | --- | --- |
| 日期与资格合同 | 发布固定日历/主表/资格版本的只读索引与校验结果 | 既有 A、HK 证券、Connect、US 权威日历及主表 owner | 不把四种日历合并为通用“今天开市”布尔值 |
| 来源适配 | 按明确 owner、日期、run、SHA 读既有 panel、新闻、US session、原文等 | 经准入的现役来源 | 初期不另采同源，不重建底板，不以 latest 冒充 exact-date |
| A 预选 | 汇总合法子池、去重、保持完整输入、输出 A 预选结果 | 原 A v1.9.2、复盘、stage7、资讯、白毛/微信等已核准来源 | 不让坏可选池拖死全池，不把展示条数当算法输入 |
| HK 预选 | 验证原 HK 0.2 模型和三日期来源，物化合格 HK 研究池 | HK02 panel、原固定模型、主表/资格来源 | 不重训，不补标签，不改变 Top100、排序或正式资格 |
| A 阶段 | 按 A 阶段时间和完整合法候选输入复用原 selector | A 预选、A 实时原始快照、适用研究材料 | 不因 HK 失败停止 A |
| HK 阶段 | 按 HK 合同采集/消费原 owner 快照、执行原 selector | HK 预选、竞价/分钟快照、适用研究材料 | 不扩大到全市场，不把恢复回看当自然；Stage8 保持 HK-only |
| A 收盘 | 原 A 收盘研究产物与证据组装 | A 收盘 panel、相应阶段/复盘来源 | 不把未完成盘中资料升格为最终收盘 |
| HK 收盘 | 原 close Top20、模型池和各阶段证据的日期绑定组装 | HK 收盘源、HK 预选、HK 阶段输出 | 任一缺项保留缺口，不能替其他模块补造结果 |
| 公告研究 | 日期目录、缺页续跑、正文证据、语义分析、审核导入、逐股理由 | 原公告来源和正文/语义生成 owner、主表 | 不将旧 HKEX 定时任务与新日期目录混为一条已完成链 |
| 超跌研究 | 对 exact-date panel 和历史窗口运行既有指标、分列严格/近似/未知 | HK02、主表及历史会话 | 不将缺输入当 0，不改变价格与量比等合取门槛 |
| US 映射 | 读已结束 US session 和已审关系表，保存当日映射与理由 | US digest 原 owner、关系版本、目标资格 | 不扩称全美股扫描，不因完整计划超时无回执 |
| 经理汇总 | 对明确的公告、超跌、US、阶段/收盘引用生成目标日汇总 | 上述模块已提交的不可变 run | 不再承担同源采集或所有 lane 的串行计算 |
| 只读 API 与界面外壳 | 按指定视图 manifest 投影结果、来源、缺口和运行状态 | 已发布视图、模块公开 schema、运行回执 | GET 不采集、不重算、不写业务结果 |
| 任务与发布控制 | 安排到期任务、核兼容版本、记录自然父链和发布过程 | 模块 manifest、日历合同、持久调度日志 | 不拥有任何选股算法、不通过重复 tick 暗改业务输入 |

以上14类职责是长期边界，不是首轮实施清单。A/H 两组 workers 将来可共享已验算法实现，但依赖和运行身份分别冻结。公告内部采集、正文、分析、导入可先作为一个 owner 下的有界阶段；以后有独立运维需求才拆独立发布单元。

### 5.1 首轮仅验证版本隔离和一个超跌 reader

首轮目标：验证 V5 的独立版本组合、真实发布健康读回和原超跌 reader 的只读隔离运行，证明这条架构边界可用。暂不迁移完整经理工作台、其他业务线、生产调度或权威 producer。

范围只包含：

- 一份版本化 module manifest 与 composition 合同，能够固定超跌 reader、合同基础包、环境和来源绑定的身份；生成并核验其派生配置，不改 V4 的 plist 或 binding
- 一个发布健康检查入口，分开报告“获准版本”“实际载入版本”“合同兼容”“数据就绪”；版本漂移、缺来源、目标日不符必须分别可见
- 一个独立超跌 reader worker，封装并复用已核对版本的 plan_context、read_rebound_screen 及必要原依赖，保留原指标、阈值、严格/近似/未知语义和源门禁；不得暗中导入可变 V4 活动源码根
- 一份隔离影子结果与读回回执，绑定目标日期、cutoff、原输入 run/SHA、reader 版本和结果 SHA；只写 V5 私有影子目录，不更新 V4、经理正式 latest 或任何权威来源

首轮通过条件分为两层，不互相替代：

1. 工程与合同层：在隔离 fixture 上证明缺输入不会变成有效零、错误 SHA/日期/PIT 会拒绝、相同输入重复运行不重复提交；仅切换/回退该 reader 的两个候选版本时，其他版本引用和 V4 身份不变。合成 fixture 必须标明 SYNTHETIC，只能证明合同、状态和隔离机制
2. 真实研究层：只有原 owner 的 exact-date HK02、主表/资格、前5个完整会话与原60会话窗口、量纲及 PIT 证据齐全，才能对同一冻结输入比较原 reader 与 V5 影子结果，核对逐股分类、数值、理由事实和全部来源身份。真实输入缺失时这一层保持 BLOCKED/CANNOT_CONFIRM

目前正确10月7日 HK02 panel 在所查活动根缺失，故目标10月8日的真实业务验收仍被阻塞。工程合同通过、历史日期通过、合成数据通过或影子进程可运行，都不能被报告成10月8日超跌研究成功。首轮也不宣称经理三线每日自然运行已经完成。

首轮排除：修复或接管 HK02 producer、补抓行情、改变日期标签或资格、重写算法、上线自然调度、14模块并行重构、完整业务页面迁移以及任何 V4 切换。HK 分日期 producer/consumer 错配先用作兼容准入的反例，不在本轮顺带修复实际 producer。

## 6 真实来源依赖与尚未关闭的缺项

### 6.1 预选与阶段

canonical 的 preselection_materializer 经 isolated_package_loader 读取 shared 包中的 v192_selector 与 hk_0_2，随后写 PreselectionPoolStore。当前结构仍有跨源码根的 Python 模块加载，适合作为 V4 兼容适配范围，不能直接当作 V5 的长期模块边界。[S3][S4]

Stage runner 的实际依赖包含候选输入、日期/资格、RawStore、SelectionStore、collector、既有 hourly research 与 morning news。原候选配置还包含 A panel receipt、HK second filter、竞价、分钟快照、旧回看根等不同来源。它们不应被一个“data_root”掩盖。SourceResolver 的日期 owner 规则是：某个目标日目录已存在却坏/不完整时，不退到另一个来源根；读期间 owner 和文件锁身份变化必须拒绝。[S5][S6]

活动 shared producer 与 registry 缺分日期接线已由现场反馈确认，不再当作未知根因。实施前仍需收齐完整源码/运行身份清单，并验证修复后的参数链与真实产物；正确10月7日 panel 的原 owner 产出、原生依赖可复现锁仍未齐。10月8日候选准备记录只证明候选 pin 检查和部分隔离验证，不能视为已部署或自然 Stage 通过。[S2]

### 6.2 收盘

build_close_review 直接消费 CloseSnapshotStore、PreselectionPoolStore、StageSelectionConsumer，再交 ReviewStore 保存。HK 模型池必须是 exact-date、STRICT_0_2_READY、合法 source_role 和100个唯一 HK 标的。阶段证据与模型池是不同输入，即使 close Top20 已有，也不能自动推断另外两者已齐。[S7]

原 HK02/收盘日历修复已经存在，后续 V5 应保留证券开市与 Connect 可用性分层，不重复推倒重做。其自然时段行为仍需真实证据，部署证据不可补称自然成功。[S8]

### 6.3 经理三线

经理 workspace 同时读取 catalyst、Stage、close、close recapture、existing materials、discovery、公告 body、Connect scope、exact quote 和 rebound screen，说明目前汇总与计算耦合很深。V5 拆分的目标是让这些输入成为固定引用，汇总不再暗中运行全部逻辑。[S9]

公告目前的新日期目录需要 publication_date，且拒绝 schedule 参数；普通 schedule 仍进入旧 announcement_autorun。分析 build_product 消费给定 semantic_catalog/body_corpus，再经 import_product 导入。尚需明确能够自动产出正文与语义材料的原 owner 及其触发合同，不能假定“有 build_product 函数”便完成自动分析。[S10][S11]

超跌应保留 reader 对 authority、会话、量纲、来源和 PIT 的门禁；此前5日均取完整 HK 会话，60日高点窗口按原算法保留完整及半日会话。实际 read_rebound_screen 的 strict 是历史完整且“收盘不高于此前60会话高点的80%”与“当前成交量不低于此前5个完整会话均量的1.5倍”同时为真；near 是历史完整、这两门已知且恰好一门通过。成交额与低点反弹仅作观察，不能把同文件 rebound_v3_metrics helper 的四门替换为这个 reader 的准入规则，也不能把未知填入 near。[S12]

US 映射已有 exact US session reader，要求 POST_CLOSE、唯一 provider session、可信血缘、cutoff 前取得及可用关系登记。现役所读10月7日 COMPLETED 有来源日期和 run，但自然父链还未证明；10月8日盘前尚未发生不能称失败。旧部署增量在完整 plan 调用后才尝试 mapping，构成异常串扰的静态风险。V5 应让独立 lane 各留回执，再由汇总引用。[S13][S14]

这些依赖的“源码存在”“候选验过”“现役已载入”“正确日期材料齐全”“自然产出通过”应列为五个不同字段，不能压成一个勾。

## 7 版本与配置必须只有一个发布来源

### 7.1 三份不同目的的记录

1. Module manifest 是模块发布包的不可变身份：module_id、release_id、源码 commit/文件清单 SHA、入口、平台/Python ABI、依赖锁摘要、模型/算法身份、配置 schema、输入/输出合同、能力列表及安全旗标
2. Deployment composition 是当前获准的模块版本组合：每模块固定 release、有效配置摘要、来源绑定、能力要求、读写边界、调度/截止配置和兼容性验收引用。它是部署意图的唯一来源
3. Runtime observation 是进程实际载入的身份、路径/文件摘要、依赖版本、启动时间和能力读回。它记录事实，不能反过来自动改“获准版本”以掩盖漂移

plist、环境变量、binding、API 的 owner 配置由同一 composition 派生，不再手工在多个位置各抄一次 pin。派生文件仍逐项核验，不能因为出自生成器就跳过现役读回。路径只是身份的一部分，还须比源码、解释器/依赖、配置及数据 owner。

### 7.2 独立发布怎样避免互相覆盖

每模块发布到新的不可变目录；改变 A 模块不能写 HK、公告或经理模块目录。每次发布只改该模块的 active 引用，并以 compare-and-swap 校验 composition 旧版本，防止两位发布者把对方的模块版本覆盖回去。组合文件采用完整版本快照和原子激活，不让 consumer 读到一半旧、一半新的配置。

公共合同或基础包的新版本不全局就地替换；各模块显式升级自己的版本。新老 worker 的在途任务固定使用启动时的版本和输入快照，不能跟着 active 指针跳变。模块发布先排空/终止有风险的旧任务并记录结果，或者允许旧任务完成后再切未来任务，不同时让两代 owner 写同一逻辑产物。

可运行包必须带与目标平台相符的依赖闭包。Linux 云端测试通过不代表 Mac 原生运行通过。当前 Stage 记录的 Python3.14.6 和若干 observed distributions 不能代替可复现 lock/wheelhouse；除非源码或依赖证明确须精确版本，其他兼容Python可用于开发及合成测试，记录实际版本、依赖和与Mac未验差异。依赖闭包不完整阻止的是相应可复现发布或业务验收声明，不把补丁版本号不同当作停止全部开发的理由。

### 7.3 用10月8日问题验收生产者与消费者准入

消费者要求能力 hk_pool.split_price_eligibility.v1，并明确三日期合同。发布准入不仅看版本号或 CLI 帮助，还要验证：

- producer 真正收到 target_date、price_signal_date、eligibility_source_date 三个独立值
- 活动 executor/registry 把三个值传至实际生产入口，而非只在上层配置里出现
- producer 使用对应原 panel、主表/资格 run，并在产物里保留独立血缘
- consumer 用同一三日期及 SHA 读回，正式资格语义没有被观察性降级替换
- 对“只有旧9月30日价格、却目标为10月8日”的反例明确拒绝

目前活动 producer 没有此分日期入口，所以应标记 PRODUCER_CAPABILITY_MISMATCH；即使新 consumer 可启动、100行池可读，也不能进入 INPUT_READY。正确10月7日 panel 尚缺又是独立的 INPUT_MISSING，不能只解决版本兼容就宣布数据已齐。

V5 先以只读适配器保留原 owner；若要迁移 producer，须先审批其模块规格与来源接管，验证真实原数据，再以唯一 owner 移交。不能绕过现役缺能力而在 V5 新建一个无审批同源抓取者。

## 8 数据合同与一致读回

每份研究产物至少保留以下字段语义。首轮只实现超跌影子所需的子集，其余字段按不适用或未实现明确标注；最终字段映射及类型在实施计划中逐项列出，不得改变这些含义：

- 身份：schema_id、schema_version、module_id、release_id、algorithm_id/sha、run_id、artifact_sha、manifest_sha、receipt_sha
- 业务分区：market、target_trade_date、stage_or_slot、source_session_date、price_signal_date、eligibility_source_date；不适用字段显式标为不适用，不能随意复用一个 date
- 时间：原文发布时间或市场事件时间、源取得时间、系统可用时间、cutoff、任务实际开始/完成时间、时区、日历版本；保留 provider 原时区并有标准化时间
- 血缘：所有父产物的 owner、run、三件套 SHA、角色与版本；不只存路径，不依赖随时可变的 latest
- 结果：状态、覆盖分母、已评估数量、严格入选/观察/排除/未知计数、逐股理由与对应证据、明确 gap 列表
- 运行：自然/手动/恢复/历史回看类型、root_trigger_id、parent_run_ids、attempt_id、输入摘要与重试原因
- 安全：只研究、正式资格状态、PIT 状态及三个禁止交易旗标

逐股理由至少说明来自哪一条研究线、为何入选或观察、对应日期/数值/公告证据，以及缺的材料。确定性规则产生的结论使用原规则事实；模型生成的解释需引用正文/页码或来源记录，保存模型/提示词版本和输入摘要。没有正文证据不能生成肯定性事实理由；不把解释文字当成新的交易决策。

写入采用“不可变 run 目录完成写入并验证 → 提交 manifest/receipt → 原子更新该分区指针”。每模块是其产物的唯一 writer；其他模块只能读已提交产物。取消任务或崩溃后的半写入不能变成 latest。

API 读取一个固定视图 manifest，其中引用每个 lane 的 run 和 SHA。页面所有卡片使用这个视图身份加载；刷新获取新视图时整体切换，不能分别读取多个 latest 后拼出不存在的组合。历史页面固定日期、run 与版本；当日缺结果可并列展示“上次成功日期”，但不将旧成功伪装成今天的结果。

“同 run/SHA”是同一个视图对应同一组子产物引用，不要求不同业务模块强行共用一个 run_id。各 lane 有自己的自然执行 run，汇总有自己的 view/run，并保存父引用。

## 9 编排与自然运行证明

任务控制按日历和时段创建真实触发记录，依赖满足后再调相应 worker。它只安排任务，不内嵌选股业务。调度日志持久化，进程重启后按同一逻辑任务键恢复，不凭内存重复开始。

主业务连接建议为：

- A/H 原 owner 输入分别到位 → 对应预选 → 对应阶段 → 对应收盘
- 公告日期目录 → 缺页续跑 → 正文和语义证据 → 校验及导入 → 公告研究结果
- HK02 exact-date 与必要历史到位 → 超跌结果
- 已完成 US session 与已审关系表到位 → US 映射结果
- 经理汇总按当时应完成的 lane 集合引用已提交结果，明确未到时、待输入或失败，不反过来控制各 lane 是否能运行

日历和依赖语义由每条任务声明：HK02/证券研究可以用 HK 证券日历；Connect 资格另做验证；US 来源按其独立市场会话和夏令时处理。不能把 CROSS_MARKET 解释成所有市场同时开才可运行。

自然证明需要形成 scheduler 真实到期事件、worker 启动记录、来源采集/可用时间、子 run、汇总 view、API/UI 读回的完整父链，并满足原时段边界。单独写 NATURAL=true、MANUAL_REFRESH 标签或父 PID 都不足以成立。旧标签不改写，可增加解释性的 trigger evidence；恢复使用真实恢复时间，错过严格 cutoff 就保留错过边界或观察性结果。

调度尚未到时应是 NOT_DUE。到了应开始的时段却没有 dispatch 是 MISSED_DISPATCH；已 dispatch 但依赖缺失是 WAITING_INPUT/BLOCKED；超出完成窗口是 MISSED_DEADLINE。三者不能用一条 NOT_RUN 或一个成功返回混淆。

## 10 健康与业务状态分层

至少分四层展示和报警：

1. 进程健康：是否已安装、载入身份是否匹配、进程是否响应
2. 模块就绪：来源绑定、合同版本、日期/资格、必需输入是否满足
3. 本次业务结果：NOT_DUE、WAITING_INPUT、RUNNING、COMPLETED、VALID_EMPTY、PARTIAL、FAILED、MISSED_DEADLINE、CANCELLED
4. 验收证据：候选/隔离测试、部署、API/UI、真实自然、下一有效日期切换分别是否已验证

READY 只能描述它所在的层。scheduler 健康时经理 hook 停用，应显示“调度主进程正常，经理自动任务不可用：绑定不一致”，总业务状态不能全绿。一个模块故障不必停止其他不依赖它的模块。

聚合状态使用明确白名单：未知状态绝不默认为成功。必需 lane 有未完成项时，汇总可以 PARTIAL_USABLE 并呈现有效股票；不能用 US 成功掩盖 plan PARTIAL。可选 A 子池缺失按已定规则隔离，不必升级成整条 A 失败。只有完整有效评估且确无命中才可显示 VALID_EMPTY；缺输入时“已评估数量”是未知或部分，而非默认为0。

模块页同时保留本次尝试和上次成功，失败不能覆盖掉成功历史；上次成功也不能遮蔽当前失败。页面可点击证据到相应日期、模块和 run，不需要翻全机日志猜测问题。

## 11 幂等 有限重试与故障隔离

同一逻辑任务的业务键包含 module、market、target date、stage/slot、cutoff 和运行类型；每个输入摘要的尝试有唯一 attempt_id。相同逻辑键、相同输入和相同算法/配置重复触发，只读回同一已提交结果，不重复采集或写入。输入真的变化时产生新的 revision，并显式引用旧 run，不能覆盖旧证据。

模块私有运行账本对业务键、输入摘要和 active owner epoch 做唯一约束或等价锁。允许至少一次投递，但提交有幂等性；不声称网络或进程能实现无条件 exactly once。旧 worker 的租约过期后，带旧 fencing token 的提交必须被拒绝，避免暂停后恢复的旧进程覆盖新 owner。

重试分类：

- 临时网络/短锁竞争：按该模块配置的有限次数、退避和截止时间重试，留每次回执
- 尚未到位的上游：等待具体 input identity 变化或预定检查点，不把每次心跳算成新业务尝试，不无限产生 UPSTREAM_NOT_READY
- 日期、PIT、SHA、来源身份、合同或安全门失败：不自动重试同一输入；须新的有效输入/获审版本或明确修复
- 公告 partial：复用成功页和正文，只补未完成项；不同分析内容遵守审核替换流程
- 超过自然窗口：留下错过边界；按获准恢复策略另建 recovery 任务，不能倒填自然时间

每模块单独的并发数、运行超时和资源上限，公告下载或语义分析不可拖住短窗口 Stage。经理汇总也不与 US 映射共用一个长时间串行调用门。控制器重启时，尚未结案的 in-flight 任务先核已提交结果和租约，再决定恢复，不能盲目重跑成功 lane。

## 12 测试与发布准入

独立升级必须同时满足“模块自己没坏”和“声明的版本组合能一起工作”。建议门分为：

1. 源码与环境门：固定源码、算法、依赖、入口及配置身份，禁止浮动文件根和未声明依赖
2. 算法保持门：已验输入 fixture 上核逐行名单、顺序、分类、数值、理由事实与 SHA，差异逐项解释；历史验收仅在字节、输入和范围均不变时复用
3. 合同门：producer/consumer 双向测试，包含旧 producer 新 consumer、旧 UI 新产物等不兼容反例；版本号相符仍需语义能力测试
4. 隔离门：在私有状态目录、录制来源或明确合成 fixture 中运行，不能写 V4，也不能把 mock/PIT 不足的数据称真实通过
5. 故障门：并发触发、半写入、worker crash、超时、绑定漂移、过期租约、依赖迟到和控制器重启
6. 部署门：检查实际载入身份、唯一 writer、只读/写入范围以及每模块失败域；包正确不代表服务已切换
7. 同一视图门：数据结果、API 与刷新页面对应同一 view/run 和全部子 SHA
8. 自然和跨日门：真实自然时段完成，并在下一有效目标日正确滚动；人工回放不能替代

本轮未运行以上测试，不能给它们 PASS。

重点反例清单：

- HK target=10/8、price=10/7、eligibility=9/30；旧9/30价格池必须拒绝，新分日期 consumer 配旧 producer 必须在准入阻止
- HK 证券开、Connect 闭时，研究与正式资格分开；10/8两者均开，不能套用闭 Connect 观察 fallback
- 目标日目录存在但损坏时不改读别根旧日；SHA或锁/owner在读取期间变化即拒绝
- A 可选子池缺失，其他有效候选继续；完整选股输入超过200行时不能被 UI 截断
- Stage8 HK-only，原冻结算法/窗口不改变；晚恢复不伪造自然实时
- previous5 必须五个完整会话，prior60 保留原半日语义；未知量纲不算 strict 或 near
- 公告目录完整但正文缺失、正文已有但语义结果缺失、语义已有但未导入分别可见
- US session错误、盘中替收盘、关系登记晚于cutoff、缺必要输入均不得成为 VALID_EMPTY
- plan 超时而 US 已可算：US 留自己回执；plan PARTIAL 不包装成全局 SUCCEEDED
- 重复自然 tick、重复投递、发布竞争、崩溃半写入、旧 owner 复活不能双写或覆写最新有效结果
- 单个公告/Stage/UI页升级失败，只回滚其获准模块；其他模块版本和 V4 服务保持身份不变

## 13 迁移兼容与回滚原则

以下是长期迁移设计门，不是已批准实施计划。首轮只覆盖第5.1节的版本/健康与单 reader 影子范围，不能因本节描述后续阶段便一并实施。

第一阶段先完成源代码/活动身份与来源合同清单，V5 仅只读桥接 V4 的已验证产物。缺来源时直报缺口；不能为了演示每天有名单而新造数据或松门。

第二阶段对已充分取证的业务链逐一迁移原算法，在 V5 私有研究结果空间中做隔离比对；首轮仅用超跌 reader 验证这一边界。使用既有原始捕获或合法录制 fixture 避免重复同源采集；合成 fixture 只验合同，任何必要的新外部采集另按原 owner 和授权处理。

第三阶段验证自然父链与同一视图读回，正式输出接入统一入口。V4 在这期间继续运行。逐个模块切换消费引用，不做全系统一次切换。

第四阶段才讨论权威 producer 接管。接管必须有排他的 owner epoch、明确读写根、版本兼容矩阵、停止旧写入/开启新写入的受控交接及失败回退；“V5 已能读”不等于允许停 V4。

回滚分开处理：

- 代码回滚：只切受影响模块到已验不可变包；不回退其他模块的版本
- 配置回滚：切到与该包兼容的既有配置及 owner binding，保留完整新旧审计
- 展示回滚：只有合同兼容且日期正确才可引用旧视图；否则显式当前缺口
- 数据回滚：不删除、不覆盖已发布新 run；新旧版本结果并存，以选择哪个已验证 run 决定展示
- 数据库/schema：使用向前扩展、兼容窗口、迁移读回；破坏性收缩在旧版本不再需要且单独审批后进行。若旧版本不能读新状态，禁止声称可一键回滚，先用兼容适配或另行审阅迁移

建议最少证明当前和前一个可回滚发布的读合同兼容；具体保留周期按体量与审阅要求确定，不凭空承诺永远兼容。重大合同语义变更使用新主版本和显式迁移，新版本不能重新解释旧日期的事实。

## 14 本规格需要审阅的选择与依赖

1. 首轮范围：请审阅第5.1节，建议仅版本组合/发布健康加一个超跌 reader 影子运行；其他模块不并行实施
2. 后续独立发布粒度：是否要求所有业务页面也可单独回滚。若是，沿轻量外壳加独立静态模块包；若不是，UI 可作为明确的共同发布单元。该选择不阻塞首轮单 reader 范围
3. 公告正文与语义产物的原生成 owner：进入公告迁移前补齐实际自动入口和来源。它是后续模块的依赖缺项，不扩大首轮范围，也不能承诺自动分析已能每天运行
4. 目标运行环境：保留现役来源可达性，确认 Mac 实际解释器、原生依赖和可复现包的验收路径。dot开发、云端Codex定向测试；兼容环境通过什么就报告什么，未验Mac差异单列，不能以未经执行的计划宣称可运行工程已完成
5. 现役配置清单：需要完整实际 CLI、registry、源码/依赖 SHA、运行环境和源目录映射，形成版本组合基线；不能用10月5日 canonical 整树覆盖当前活动根

这些问题可分阶段审阅，不需要用户一次决定全部实现细节。未获答复的必要选择保持待审，不能把先前对重构方向的支持扩张成对本文件全部内容及实施方式的批准。

## 15 本轮交付与下一道门

已完成的是源码只读研究和此书面规格草案，内容覆盖需求、方案比较、真实来源依赖、模块边界、发布隔离、数据合同、自然运行证据、失败恢复、测试与回滚原则，并明确首轮仅做版本/健康与超跌 reader 影子。没有创建 V5 产品项目、依赖环境、可执行骨架或仓库分支，也没有触碰 V4 运行状态。

下一道门是用户审阅并批准本文件及首轮范围。批准后直接编写实施计划，再请用户审阅计划并选择执行方式，不重复撰写同一规格。未关闭的输入和现役接线问题继续保留；后续业务扩展另行审阅，不由本次批准自动覆盖。

## 来源索引

S1 [固定快照使用规则与边界](https://github.com/lexi2016/v4/blob/c563adc067fcd6a6b95fe756c7618f46d2f4389e/AGENTS.md)；[按 variant 还原及禁止整树冒充活动版](https://github.com/lexi2016/v4/blob/c563adc067fcd6a6b95fe756c7618f46d2f4389e/handoff/v4-running-source-20261005/MANIFEST.json)

S2 [10月8日候选 三日期合同 现役身份 输入阻塞与未部署边界](https://github.com/lexi2016/v4/blob/c563adc067fcd6a6b95fe756c7618f46d2f4389e/handoff/hk-oct8-preparation-20261007/HANDOFF_SUMMARY.md)；[准备批次 manifest](https://github.com/lexi2016/v4/blob/c563adc067fcd6a6b95fe756c7618f46d2f4389e/handoff/hk-oct8-preparation-20261007/SYNC_MANIFEST.json)

S3 [canonical 分日期 HK pool 投影与资格来源核验](https://github.com/lexi2016/v4/blob/c563adc067fcd6a6b95fe756c7618f46d2f4389e/handoff/v4-running-source-20261005/canonical/domains/_preselection_materializer_parts/hk_pool.py#L33-L185)；[materializer 原 reader 接口与分日期参数](https://github.com/lexi2016/v4/blob/c563adc067fcd6a6b95fe756c7618f46d2f4389e/handoff/v4-running-source-20261005/canonical/domains/preselection_materializer.py#L105-L237)

S4 [Stage 快照的跨根隔离加载器](https://github.com/lexi2016/v4/blob/c563adc067fcd6a6b95fe756c7618f46d2f4389e/handoff/v4-running-source-20261005/stage/infrastructure/isolated_package_loader.py)

S5 [候选 SourceResolver 日期 owner 和读租约](https://github.com/lexi2016/v4/blob/c563adc067fcd6a6b95fe756c7618f46d2f4389e/handoff/hk-daily-runtime-r2-20261007/candidate/infrastructure/preselection_pool_sources.py#L23-L146)；[候选 runner 输入和运行依赖](https://github.com/lexi2016/v4/blob/c563adc067fcd6a6b95fe756c7618f46d2f4389e/handoff/hk-daily-runtime-r2-20261007/candidate/stage_center/runner.py#L309-L367)

S6 [候选阶段与八阶段市场窗口合同](https://github.com/lexi2016/v4/blob/c563adc067fcd6a6b95fe756c7618f46d2f4389e/handoff/hk-daily-runtime-r2-20261007/candidate/stage_center/contracts.py)；[明确来源根配置示例](https://github.com/lexi2016/v4/blob/c563adc067fcd6a6b95fe756c7618f46d2f4389e/handoff/hk-oct8-preparation-20261007/stage/stage_center_tick_config.example.json)

S7 [收盘候选的原始来源与模型和阶段输入校验](https://github.com/lexi2016/v4/blob/c563adc067fcd6a6b95fe756c7618f46d2f4389e/handoff/hk-oct8-preparation-20261007/close/scheduler_candidate/ops/build_close_review.py)

S8 [HK 日历修复的候选 部署与自然证据边界](https://github.com/lexi2016/v4/blob/c563adc067fcd6a6b95fe756c7618f46d2f4389e/handoff/hk-close-hk-calendar-20261007/HANDOFF_SUMMARY.md)；[scheduler 快照的 workload/owner 注册](https://github.com/lexi2016/v4/blob/c563adc067fcd6a6b95fe756c7618f46d2f4389e/handoff/hk-close-hk-calendar-20261007/scheduler/contracts/runtime_workloads.json)

S9 [经理 workspace 的真实读取依赖](https://github.com/lexi2016/v4/blob/9dfa50346357b6dc4b2463a30dcbf3718fce2f03/handoff/v4-running-source-20261005/canonical/v4/manager_research/workspace.py#L437-L499)

S10 [公告日期目录与原定时链分流](https://github.com/lexi2016/v4/blob/a7732310a5262b59c95a30fdf5d7bedc9910939f/handoff/announcement-daily-repair-20261007/source/v4/manager_research/workspace_announcements.py#L434-L457)；[目录的幂等与 resume](https://github.com/lexi2016/v4/blob/a7732310a5262b59c95a30fdf5d7bedc9910939f/handoff/announcement-daily-repair-20261007/source/v4/manager_research/workspace_announcements.py#L910-L1026)

S11 [分析消费的语义材料与正文合同以及显式导入](https://github.com/lexi2016/v4/blob/a7732310a5262b59c95a30fdf5d7bedc9910939f/handoff/announcement-daily-repair-20261007/source/v4/manager_research/announcement_analysis.py#L736-L914)

S12 [5日与60日会话语义](https://github.com/lexi2016/v4/blob/9dfa50346357b6dc4b2463a30dcbf3718fce2f03/handoff/v4-running-source-20261005/api/v4/manager_research/workspace_plan.py#L622-L644)；[超跌 exact-date 原计算入口及两门规则](https://github.com/lexi2016/v4/blob/9dfa50346357b6dc4b2463a30dcbf3718fce2f03/handoff/v4-running-source-20261005/api/v4/manager_research/workspace_plan.py#L827-L1129)

S13 [US 原 owner reader 的 session 血缘和时点约束](https://github.com/lexi2016/v4/blob/840b9538c45c9ba8fd56f8e89048aff230df0f0f/handoff/v4-running-source-20261005/api/v4/manager_research/us_market_bridge.py#L153-L199)

S14 [US 每日部署增量的 owner binding 校验及 plan 后映射顺序](https://github.com/lexi2016/v4/blob/840b9538c45c9ba8fd56f8e89048aff230df0f0f/handoff/us-mapping-daily-workbench-20261005/release_delta/daily_overlay.patch#L227-L273)；[宽泛状态映射的静态风险](https://github.com/lexi2016/v4/blob/840b9538c45c9ba8fd56f8e89048aff230df0f0f/handoff/us-mapping-daily-workbench-20261005/release_delta/daily_overlay.patch#L343-L363)

S15 [scheduler 快照的多位置 pin 校验](https://github.com/lexi2016/v4/blob/9dfa50346357b6dc4b2463a30dcbf3718fce2f03/handoff/v4-running-source-20261005/canonical/ops/run_v35_macos_scheduler_daemon.py#L223-L320)；[hook 停用后主进程继续](https://github.com/lexi2016/v4/blob/9dfa50346357b6dc4b2463a30dcbf3718fce2f03/handoff/v4-running-source-20261005/canonical/ops/run_v35_macos_scheduler_daemon.py#L720-L753)

现役事实另依据本轮已转交的只读运行审计，本文没有生成可冒充现场原日志的链接。凡未取得当前字节、父触发或原生运行证据的项目，仍保持未证实。
