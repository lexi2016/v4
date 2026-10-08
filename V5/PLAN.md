# V5 版本隔离与超跌影子运行 Implementation Plan

> 状态更新（2026-10-08）：本计划已进入实施。054782a 的 Mac 全套 78 项测试通过，1167ed3 新增 11 项及全套 89 项在 Mac 通过。当前由 dot 写代码、原 Mac 会话测试，不用云端 Codex 测试。以下任务描述保留初始设计；实际完成范围以 docs/ACCEPTANCE.md 为准。

**Goal:** 建立独立版本组合和发布健康检查，封装一个原超跌 reader 在隔离目录影子运行，保持 V4 持续运行。

**Architecture:** 单仓库下仅新增 V5 文件。冻结原 reader 的最小完整依赖包，在独立 Python 进程中运行；manifest、composition 和观测身份分开。影子结果采用不可变 run、校验读回和幂等提交，不接管 V4 的任何 writer 或自然调度。

**Tech Stack:** Python；标准库负责合同、JSON、hash、文件锁和进程通信；原 reader 所需 pandas/Parquet 依赖按固定来源的实际锁核定，pytest 负责隔离测试。3.14.6仅为此前观察到的Mac解释器版本。除非源码/依赖证明确须精确版本，其他兼容解释器可以开发和执行合成测试，记录实际Python/依赖；Mac实际环境另验，不能将补丁号不同本身当作禁止开发条件。

**Spec:** [V5 架构规格草案](SPEC.md)，尤其第5.1节；[来源与证据基线](BASELINE.md)。本计划仅实现第5.1节，不把14类长期职责全部实施。

**Status:** IMPLEMENTING / SYNTHETIC_BASELINE_MAC_78_PASS / PROVIDER_MAC_89_PASS / DEPLOYMENT_NOT_RUN。真实输入准入、页面视觉与自然运行仍待验。原配置根的 10/7 panel 和 VIPDOC 增量缺失已只读复核，不能推断全机无原件。

## Global Constraints

- V4 与 Vibe 原有服务在替代验收前保留，V5 不能覆盖其源码根、运行配置或状态目录
- A 股与 HK 合同保持分离；HK 证券开市与港股通开市、价格日与资格来源日分别判断
- 已验证的算法优先复用。算法变更应是另一个独立讨论和验收，不夹带在工程重构中
- 研究结果保持 research_only=true、production_allowed=false、buy_gate_updated=false、orders_sent=false；不接账户、不产生订单、不变更 BUY 门
- 真正 PIT、来源取得时间、真实运行时间与研究 cutoff 不得伪造；恢复、历史回看、手动运行不能升级成自然成功
- 首轮排除生产者修复/接管、补抓行情、自然调度启用、完整页面迁移和 V4 切换；只读原 owner，写 V5 私有影子目录
- 所有新增代码、测试、依赖和文档在 V5/；根目录 AGENTS.md、README.md、handoff/ 和其他分支不改；不 merge、force push、添加全仓 CI 或更改仓库可见性
- 源码候选基线与活动字节不自动相等；缺依赖不能用空实现代替；所有合成 fixture 标 SYNTHETIC，不能用它通过真实业务或自然验收
- dot在当前工作中编写代码；原 Mac Codex 会话承担独立测试及反馈，不并行改另一套业务代码，不启动云端 Codex 测试

## Review Focus

- 同文件四门 helper 与真实两门 reader 容易混用：成交额、低点反弹不影响 reader 的 strict/near；由任务4明确回归
- 当前缺日期输入但 legacy coverage 为0：标准影子结果必须 CANNOT_CONFIRM 且 evaluated_count=null；由任务4和6验证
- 目标10/8的池资格可来自9/30，不代表超跌 master 也可回退9/30：超跌沿原 reader 读取其 panel session 的 exact-date master；由任务4验证
- reader 隐式读取活动源码根、网络或写原来源：独立包导入及只读快照边界必须拒绝；由任务1、4和7验证
- 发布竞争、进程中断及相同请求重投：不能覆盖其他模块版本、产生半提交或重复结果；由任务3和6验证

## 1 文件与职责

以下是初始计划文件清单，其中核心产品文件已创建。参见 docs/ACCEPTANCE.md 核对实际验证范围。

| 路径 | 职责 |
| --- | --- |
| V5/pyproject.toml 与 V5/uv.lock | 仅 V5 的构建/测试和依赖锁，不改 V4 依赖 |
| V5/src/v5_shadow/contracts.py | 所有跨任务类型、固定 schema 与安全字段 |
| V5/src/v5_shadow/digests.py | 有界 canonical JSON 与 SHA256，无 NaN/Infinity |
| V5/src/v5_shadow/source_capsule.py | 按固定 snapshot manifest 核最小依赖包的来源和字节 |
| V5/src/v5_shadow/composition.py | 版本兼容与配置派生，V5 内部单模块 CAS 切换 |
| V5/src/v5_shadow/health.py | 获准身份、载入身份、输入就绪分层比较 |
| V5/src/v5_shadow/legacy_adapter.py | 唯一原 reader 入口，不重写指标或交易规则 |
| V5/src/v5_shadow/worker.py | 独立进程请求处理与真实开始/完成时间记录 |
| V5/src/v5_shadow/shadow_store.py | 幂等键、不可变提交、SHA读回及中断恢复 |
| V5/src/v5_shadow/cli.py | check、health、run-shadow、read-result 四个命令 |
| V5/src/v5_shadow/__init__.py 和 __main__.py | 仅包入口，不执行采集或业务副作用 |
| V5/vendor/rebound_baseline/ | 按任务1准入清单复制的原文件，保持原路径与字节；未准入文件不混入 |
| V5/contracts/rebound_source_manifest.json | 原文件 commit、variant、路径、blob与SHA256的逐文件闭包 |
| V5/contracts/module.schema.json 与 composition.schema.json | 版本/配置的可审阅 JSON 合同，无真实机器路径 |
| V5/config/composition.synthetic.json | 只用于合成隔离验证的示例配置 |
| V5/tests/fixtures/rebound_factory.py | 生成最小 SYNTHETIC panel/master fixture，不上传真实行情 |
| V5/tests/test_source_capsule.py | 来源闭包和导入隔离 |
| V5/tests/test_contracts.py | 合同、日期、时间、安全字段和状态白名单 |
| V5/tests/test_composition.py | 兼容准入、CAS与独立回滚 |
| V5/tests/test_legacy_adapter.py | 原 reader 语义保持和缺输入反例 |
| V5/tests/test_health.py | 健康与业务就绪分开 |
| V5/tests/test_shadow_store.py | 幂等、并发、半写入与不可变读回 |
| V5/tests/test_cli_isolation.py | 端到端隔离和命令行回执 |
| V5/docs/ACCEPTANCE.md | 按层填写实际命令、环境、结果和未验项 |

真实来源绝对路径、运行数据和完整请求只留获准机器；不得写入 GitHub。根 README 和现有源码目录仍保持原 SHA。代码任务新增文件时只 git add 指定路径，不使用 git add -A。

## 2 固定接口与状态

实现使用 frozen dataclass，集合字段使用 tuple；JSON解析先按 schema 严格校验再构造对象。所有 SHA 是小写64位十六进制；来源 Git blob另存40位字段，不能混同。

| 类型 | 首轮字段 |
| --- | --- |
| SafetyFlags | research_only:bool=true；production_allowed、buy_gate_updated、orders_sent:bool=false |
| SourceEntry | repository:str、commit:str、variant:str、snapshot_path:str、relative_path:str、git_blob_sha:str、sha256:str |
| SourceCapsule | entries:tuple[SourceEntry,...]、manifest_sha256:str、python_version:str、dependency_lock_sha256:str |
| DependencyRequirement | module_id:str、input_contract:str、required_capabilities:tuple[str,...] |
| ModuleManifest | schema_version='v5.module.v1'、module_id:str、release_id:str、code_manifest_sha256:str、python_version:str、dependency_lock_sha256:str、capabilities:tuple[str,...]、requires:tuple[DependencyRequirement,...]、input_contracts:tuple[str,...]、output_contract:str、entrypoint:str、safety:SafetyFlags；首轮可执行module_id仅rebound_shadow，其output_contract固定v5.rebound_shadow.v1 |
| Binding | authority_root:Path或null、shadow_root:Path、calendar_sha256:str、source_capsule_sha256:str、input_snapshot_sha256:str或null；仅机器本地保存真实根 |
| Composition | schema_version='v5.composition.v1'、revision:int、modules:dict[str,ModuleManifest]、bindings:dict[str,Binding]；未知module可保留但不执行 |
| ShadowRequest | request_id:str、target_trade_date:str、research_cutoff:带时区datetime、requested_at:带时区datetime、execution_kind='SHADOW_MANUAL'或'SHADOW_REPLAY'、data_kind='SYNTHETIC'或'OWNER_VERIFIED'、composition_sha256:str、input_snapshot_sha256:str或null |
| RuntimeIdentity | module_id、release_id、code_manifest_sha256、python_version、dependency_lock_sha256、effective_config_sha256、source_capsule_sha256:均str；observed_at:带时区datetime |
| LegacyScreen | 原 read_rebound_screen 的完整dict；不覆盖原 status、rule_version、coverage、source_refs或逐股字段 |
| HealthReport | schema_version='v5.health.v1'、identity_status='MATCH'/'MISMATCH'/'UNVERIFIED'、compatibility_status='COMPATIBLE'/'INCOMPATIBLE'/'UNVERIFIED'、input_status='READY'/'MISSING'/'INVALID'/'UNVERIFIED'、reason_codes:tuple[str,...]、expected和observed身份摘要 |
| ShadowResult | schema_version='v5.rebound_shadow.v1'、run_id:str、request:ShadowRequest、runtime:RuntimeIdentity、legacy_screen:LegacyScreen、business_status='COMPLETED'/'VALID_EMPTY'/'PARTIAL'/'CANNOT_CONFIRM'/'FAILED'、evaluated_count:int或null、formal_eligibility_status='UNVERIFIED'、natural_verified=false、started_at/finished_at:真实带时区datetime、safety:SafetyFlags |
| RunReference | run_id:str、artifact_sha256:str、manifest_sha256:str、receipt_sha256:str、idempotency_key:str |

接口中的 Path 必须是获准根内的已解析真实路径，不允许越界、symlink组件或 ../。所有日期为 YYYYMMDD；时区感知的截止时刻单独保存，不能用机器当天替换目标日。historical cutoff 仅 SHADOW_REPLAY 可用且结果永不标自然。

原 reader 字段里出现 VERIFIED_TARGET_UNIVERSE 也不自动成为 V5 已核准的目标日正式资格。保留 legacy_screen 原值，V5 formal_eligibility_status 首轮固定 UNVERIFIED，避免把研究面板成员身份升级成正式资格。

## 3 任务顺序与停止条件

任务1→2→3→4→5→6→7。每个任务提交后独立审阅，未过审不继续依赖它的任务。合同/环境可以在真实行情缺失时开发；真实研究验收须等原 owner 数据齐。源码闭包缺失时任务4的原 reader 迁移阻塞，不用 mock 替代后宣称已迁移。

下面的 Run 命令为初始任务说明；现统一交给原 Mac 独立测试会话，在V5/目录执行；测试任务只读取提交的候选代码，不自行迁移或修复产品源码，失败反馈由dot处理。测试前确认实际解释器与固定依赖兼容，令V5_PYTHON指向该解释器并使用私有环境；下面的python均指该环境。兼容版本可运行工程/合成测试，记录版本差异；只有某项已证明不兼容才阻塞该项。Mac原生测试另有独立回执，命令未执行明确NOT_RUN。

### Task 1 冻结原 reader 的最小来源包

**Files:** Create source_capsule.py、contracts/rebound_source_manifest.json、vendor/rebound_baseline/ 准入文件、tests/test_source_capsule.py；Create contracts.py中的SourceEntry/SourceCapsule两种基础类型；本任务同时引入仅够测试的 pyproject.toml 和 uv.lock。

**Interfaces:**
- Consumes: BASELINE.md 的固定commit和运行快照 manifest；不能自行选latest分支
- Produces: SourceEntry、SourceCapsule；inspect_capsule(capsule_root:Path, entries:tuple[SourceEntry,...]) -> SourceCapsule；verify_capsule(capsule:SourceCapsule, root:Path) -> tuple[str,...]，返回空tuple才完整通过

- [ ] Step 1 写 test_rejects_missing_changed_or_unlisted_source：删除一项、改一字节、混入未登记.py分别得到 SOURCE_MISSING、SOURCE_SHA_MISMATCH、SOURCE_UNDECLARED；同名canonical/API不同SHA不得互换
- [ ] Step 2 运行 python -m pytest tests/test_source_capsule.py -q，预期新接口未实现而FAIL，保存真实首个失败原因
- [ ] Step 3 从9dfa503…fce2f03的 api variant manifest还原所选原文件；只沿 plan_context/read_rebound_screen 的可达依赖收闭包，逐文件记录原blob及SHA256。已识别入口见下段，manifest若指向共用snapshot须按原映射取字节；不把canonical整个树复制成API版
- [ ] Step 4 实现两个接口，核完整闭包与依赖锁。缺少原共享 master/store 依赖时返回 SOURCE_CLOSURE_INCOMPLETE并阻止后续reader任务，不拼接一个未经验证来源版本
- [ ] Step 5 写并运行 test_imports_only_frozen_capsule：隔离子进程的非标准库模块只来自该包/其私有依赖环境；fixture插入活动源码根、未知module或导入时网络/写源尝试均拒绝
- [ ] Step 6 运行 python -m pytest tests/test_source_capsule.py -q，预期全部PASS；云端确实缺某兼容依赖时标该项BLOCKED，其他可执行的来源/合同测试照常进行；Mac原生未验单列，不能把跳过项统计为PASS，也不因3.14.6补丁号不同停止全部开发
- [ ] Step 7 仅提交本任务准入文件与测试：commit message为 test(v5): pin rebound source capsule and isolation boundary

最小入口清单：v4/manager_research/workspace_plan.py、workspace_projection.py、workspace_read_control.py；infrastructure/owned_io.py；contracts/trading_calendar.py与market_calendar_2026.json；v3_shared_data/shared_data/hk_security_master.py及其实际store依赖；相关包初始化文件。准确闭包由固定api variant的manifest和可达导入交叉确认，不把其他lazy业务入口如stock_plan、announcement分析迁入执行路径。此清单是原路径，不代表所有文件都在GitHub api子目录单独存有副本。

原 workspace_plan blob=10abaf491648f20b3618fbf3404c440a7ca77dc7；规则=20260923_REBOUND_TWO_GATE_V1，schema=v4.manager_research.rebound_v3_screen.v1。这些是候选来源锚点，不是最新现役等价证明。包内原源码不改；V5包装逻辑另放legacy_adapter.py。

### Task 2 建立请求 产物与安全合同

**Files:** Extend contracts.py，保留任务1的SourceEntry/SourceCapsule；Create digests.py、contracts/module.schema.json、composition.schema.json、tests/test_contracts.py。

**Interfaces:**
- Consumes: SourceEntry/SourceCapsule字段规范；任务1形成的来源身份
- Produces: parse_manifest(value:dict) -> ModuleManifest；parse_request(value:dict) -> ShadowRequest；canonical_bytes(value:dict) -> bytes；sha256_json(value:dict) -> str；本计划第2节全部dataclass定义

- [ ] Step 1 写 test_manifest_and_request_fail_closed：四个安全位任何不符即 SAFETY_BOUNDARY_INVALID；无时区cutoff、无效真实日期、未知schema/status、NaN/Infinity拒绝
- [ ] Step 2 运行 python -m pytest tests/test_contracts.py -q，预期因新接口缺失FAIL
- [ ] Step 3 实现严格解析和canonical编码：UTF-8、sort_keys=true、separators=(',',':')、ensure_ascii=false、allow_nan=false。通用hash忠实计算传入字节；业务幂等键的字段选择由任务6负责，不能由hash函数悄悄删除字段
- [ ] Step 4 写 test_replay_keeps_real_execution_clock：SHADOW_REPLAY保留历史cutoff，但started_at/finished_at使用实际运行时钟；natural_verified始终false。写 test_three_date_roles_are_not_interchangeable，明确target、panel session与资格来源不可重命名替代
- [ ] Step 5 运行 python -m pytest tests/test_contracts.py tests/test_source_capsule.py -q，预期全部PASS
- [ ] Step 6 仅提交上述合同文件和测试，commit message为 feat(v5): define strict shadow contracts and safety flags

### Task 3 单源版本组合与隔离回滚

**Files:** Create composition.py、config/composition.synthetic.json、tests/test_composition.py。

**Interfaces:**
- Consumes: ModuleManifest、Composition、Binding、sha256_json
- Produces: validate_composition(value:dict, manifests:dict[str,ModuleManifest]) -> Composition；render_effective_config(composition:Composition,module_id:str) -> dict；switch_module(path:Path,module_id:str,new_manifest:ModuleManifest,expected_sha256:str) -> str（仅返回新composition SHA）

- [ ] Step 1 写 test_incompatible_producer_cannot_be_ready：要求hk_pool.split_price_eligibility.v1、提供旧单日期能力的合成条目必须INCOMPATIBLE；它只是准入反例，不执行HK pool。写 test_config_has_one_identity_source：派生release/入口/依赖/根摘要来自同一composition
- [ ] Step 2 运行 python -m pytest tests/test_composition.py -q，预期FAIL
- [ ] Step 3 只实现首轮所需合同能力匹配和V5私有composition文件内的CAS，不建立通用插件平台或服务注册系统；在父目录持独占flock、重读expected SHA、写临时文件并fsync、原子replace后fsync父目录。只允许变更rebound_shadow条目，其他条目字节语义保持
- [ ] Step 4 写 test_concurrent_switch_rejects_stale_revision：两个旧SHA请求只有首个提交，其余STALE_COMPOSITION；写 test_rollback_changes_only_rebound：r1→r2→r1时合成sibling条目不变，V4快照目录hash不变
- [ ] Step 5 写 test_refuses_external_or_symlink_composition：输出根越界、指向V4、目录symlink均拒绝；不得通过改OS安全权限绕过
- [ ] Step 6 运行 python -m pytest tests/test_composition.py tests/test_contracts.py -q，预期全部PASS；此处“回滚”只指隔离配置试验，未启停任何实际服务
- [ ] Step 7 commit message为 feat(v5): add isolated composition admission and rollback

### Task 4 封装原两门超跌 reader

**Files:** Create legacy_adapter.py、worker.py、tests/fixtures/rebound_factory.py、tests/test_legacy_adapter.py。

**Interfaces:**
- Consumes: 已验证SourceCapsule、Binding、ShadowRequest、ModuleManifest；原plan_context(date,now=...)与read_rebound_screen(authority_root,context)
- Produces: run_legacy_screen(request:ShadowRequest,binding:Binding) -> LegacyScreen；build_shadow_result(request:ShadowRequest,runtime:RuntimeIdentity,legacy:LegacyScreen,started_at:datetime,finished_at:datetime) -> ShadowResult；worker_main(request_json:Path,effective_config_json:Path) -> int

- [ ] Step 1 写 test_missing_exact_date_is_unknown_not_zero：缺10/7 panel时原status=CANNOT_CONFIRM、main_screen_ready=false、input_identity=null；V5 business_status=CANNOT_CONFIRM、evaluated_count=null。即便原coverage含0也不得变为VALID_EMPTY
- [ ] Step 2 运行 python -m pytest tests/test_legacy_adapter.py -q，预期新适配器缺失FAIL
- [ ] Step 3 仅包装冻结原入口，显式传cutoff；worker在私有进程和环境中只加载固定包，不导入V4活动路径，不引入网络采集。完整legacy结果嵌入，不改原结果或日期。OWNER_VERIFIED必须由原owner的完整来源回执核得，不能信任request自报的data_kind
- [ ] Step 4 写 test_two_gate_truth_table：历史完整时oversold与volume都真→STRICT；恰一真→NEAR；都假→EXCLUDED；任一未知→PENDING。用生成fixture实际走原read_rebound_screen；不能仅测rebound_v3_metrics。amount或低点反弹变动不改变这两门分类
- [ ] Step 5 写 test_calendar_and_master_are_exact：previous5取5个完整会话；prior60包含原日历中的半日；不以最近可用行凑数；缺reader指定panel session的exact-date master不可用9/30替代。HK pool三日期合同与这个reader需求分开
- [ ] Step 6 写 test_cutoff_revision_and_source_integrity：同日修订仅在原manifest可用时间不晚于cutoff时可用；未来修订、多义修订、文件SHA变化、未知量纲按原门拒绝或保留原缺口，不以mtime选择。真实读取仅准入已冻结、只读且原owner可验证的输入快照或持有原owner一致性读租约；只有前后hash相同而无快照/租约证明，不足以宣称一致读取，保留INPUT_STABILITY_UNVERIFIED
- [ ] Step 7 写 test_legacy_claim_does_not_grant_formal_eligibility：即使legacy字段为VERIFIED_TARGET_UNIVERSE，V5 formal_eligibility_status仍UNVERIFIED，安全三位false。写 test_mapping_whitelist：只有READY且完整评估可COMPLETED/VALID_EMPTY，READY_WITH_GAPS映PARTIAL，CANNOT_CONFIRM保留；未知原status→FAILED
- [ ] Step 8 写 test_unmodified_payload_parity：同一fixture、冻结上下文下直接原调用与适配器legacy_screen逐字段相等；只允许V5外层新增运行元数据。运行 python -m pytest tests/test_legacy_adapter.py -q，预期全部PASS
- [ ] Step 9 commit message为 feat(v5): wrap frozen two-gate rebound reader for shadow runs

fixture生成器必须写明SYNTHETIC，生成parquet与原owner结构所需最小manifest只用于隔离测试。它不具有OWNER_VERIFIED权威，禁止进入真实研究通过统计。若原reader依赖真实签名/不可合成证据导致无法端到端构造，通过隔离reader注入只能验证包装合同；完整原reader parity须等合法录制来源，明确相应测试BLOCKED，不能改reader降门。

### Task 5 分层发布健康

**Files:** Create health.py、tests/test_health.py。

**Interfaces:**
- Consumes: Composition、RuntimeIdentity、LegacyScreen；任务3派生配置摘要
- Produces: observe_runtime(module:ModuleManifest,capsule:SourceCapsule,effective_config:dict) -> RuntimeIdentity；evaluate_health(expected:ModuleManifest,binding:Binding,expected_config_sha256:str,observed:RuntimeIdentity,input_evidence:dict) -> HealthReport

- [ ] Step 1 写 test_alive_process_with_wrong_release_is_mismatch：进程存在且响应也不能掩盖release/code/配置/依赖SHA不符；输入缺失与版本不符分别保留reason
- [ ] Step 2 运行 python -m pytest tests/test_health.py -q，预期FAIL
- [ ] Step 3 实现本进程实际__file__、解释器、依赖锁和有效配置的观测，不从expected直接复制成observed；不读取其他服务凭证或改现役环境
- [ ] Step 4 写 test_health_is_not_business_completion：identity=MATCH且compatibility=COMPATIBLE，input仍可MISSING；UNKNOWN状态不能默认Ready；SYNTHETIC成功健康回执不能变成OWNER_VERIFIED
- [ ] Step 5 运行 python -m pytest tests/test_health.py tests/test_composition.py -q，预期全部PASS
- [ ] Step 6 commit message为 feat(v5): separate runtime identity from input readiness

### Task 6 不可变影子存储与幂等

**Files:** Create shadow_store.py、tests/test_shadow_store.py。

**Interfaces:**
- Consumes: ShadowRequest、ShadowResult、RunReference、sha256_json
- Produces: idempotency_key(request:ShadowRequest,runtime:RuntimeIdentity) -> str；publish_shadow(root:Path,result:ShadowResult) -> RunReference；read_shadow(root:Path,ref:RunReference) -> ShadowResult

- [ ] Step 1 写 test_same_input_reuses_committed_run：业务键包含module/target/cutoff/execution_kind/data_kind、固定reader+该模块effective_config+来源输入摘要，排除request_id、requested_at、observed_at、运行起止时间和无关sibling的composition改动；重投request_id不同也读回同一已提交run。真实输入SHA变化须产生新run而不覆盖旧run
- [ ] Step 2 运行 python -m pytest tests/test_shadow_store.py -q，预期FAIL
- [ ] Step 3 实现单机每业务键flock和immutable run trio，结构为shadow_root/runs/<date>/<run_id>/{artifact,manifest,receipt}.json。提交先完整写入/核验，再原子登记幂等索引；没有完整trio不登记成功
- [ ] Step 4 写 test_crash_before_commit_is_not_latest：在三件套各写入点注入中断，read拒绝半产物，恢复先查完整已提交结果；写 test_parallel_duplicate_cannot_double_commit，用两个进程同时发布同键只生成一个有效结果
- [ ] Step 5 写 test_failure_does_not_overwrite_prior_success：本次缺输入留下新失败尝试，可引用上次成功但保留旧日期/身份；失败不能抹除旧历史。输入未知的失败尝试按attempt存档，不用null输入摘要误缓存后续有效结果
- [ ] Step 6 写 test_source_mutation_or_symlink_is_rejected：读取前后来源摘要不同、shadow路径跨出获准根、目录symlink均失败；未获输入稳定性证明的结果不得提交成功
- [ ] Step 7 运行 python -m pytest tests/test_shadow_store.py -q，预期全部PASS；回执固定natural_verified=false，实际finished_at不得由用户请求覆盖
- [ ] Step 8 commit message为 feat(v5): persist immutable idempotent shadow receipts

首轮单worker使用OS文件锁，不实现分布式租约或消息队列。锁由内核随进程退出释放，不让超时任务后台继续提交；未来多机writer/fencing是另一个已明确边界的项目。

### Task 7 最小CLI与完整隔离验收

**Files:** Create cli.py、__main__.py、tests/test_cli_isolation.py、docs/ACCEPTANCE.md；必要时补__init__.py；仅更新V5 README的实际状态。

**Interfaces:**
- Consumes: 任务1–6所有公开接口
- Produces: main(argv:list[str]|None=None) -> int；四个CLI：check --composition，health --composition，run-shadow --composition --request --output-root，read-result --output-root --target-date --run-id。read-result从该日期/run的已提交manifest/receipt构造RunReference再调用read_shadow，不全目录猜测run

- [ ] Step 1 写 test_cli_status_and_exit_codes：有效check/read返回0；合法但待输入/未知结果返回2；合同、身份或完整性拒绝返回3；内部异常返回4。返回JSON必须包含status和reason_codes，不能仅以exit0宣称业务完成
- [ ] Step 2 运行 python -m pytest tests/test_cli_isolation.py -q，预期FAIL
- [ ] Step 3 将现有接口连入CLI；只在显式run-shadow写V5输出，check/health/read-result无业务写入。请求不能任意传代码入口；entrypoint只从已核验module manifest取固定worker
- [ ] Step 4 写 test_whole_flow_preserves_v4：准备只读V4 fixture镜像hash、V5 r1/r2 manifest；依次check、health、影子运行、read、重复运行、隔离回滚；核V4镜像与sibling版本不变，结果run/SHA一致
- [ ] Step 5 写 test_no_network_and_no_source_writes：通过可用沙箱/只读挂载实际限制并观察，不能只靠代码自称只读；网络禁用且源只读的情况下合成测试能完成。无法强制限制的目标环境记录ISOLATION_UNVERIFIED，不能宣称安全影子验收完成
- [ ] Step 6 运行 python -m pytest tests -q 和 python -m compileall -q src；保存实际汇总，0个隐式跳过，全部必要测试PASS才工程层通过；代码检查不替代测试
- [ ] Step 7 形成 docs/ACCEPTANCE.md：commit/包/依赖与源码闭包SHA、实际OS/Python、逐命令stdout摘要、工程/合同/真实业务/自然各层状态；不上传raw行情、真实绝对路径或完整大运行数据
- [ ] Step 8 原 owner 数据在获准本地环境已齐时，由本地Codex只读核身份后运行同包影子验收，保留真实来源PIT和先后时间。如果10/7 panel仍缺，真实业务=BLOCKED；不必阻止交付诚实的工程合同结果
- [ ] Step 9 commit message为 test(v5): verify isolated shadow cli and acceptance layers；核远端逐文件SHA与diff仅V5/，不得merge或部署自然服务

## 4 发布包与验收口径

执行到任务7后才有可运行候选，届时以独立包摘要和完整依赖闭包交付。本地部署测试需要完整既有权限范围、目标根和包身份明确，不能因为代码push成功便自动启停V4。

| 层 | 通过要求 | 当前 |
| --- | --- | --- |
| 文档 | spec、baseline、README、plan可审阅且来源固定 | 本次独立分支的V5文档基线 |
| 合同与工程 | 源闭包、TDD测试、隔离/幂等/回滚、实际环境记录 | NOT_RUN |
| 原生目标环境 | 同包在Mac实际解释器及已锁依赖中验证；此前观察为3.14.6，执行时复核 | NOT_RUN |
| 真实业务影子 | 真实exact-date HK02/master/历史/PIT齐全，原reader与影子同输入一致 | BLOCKED，待执行时只读复核数据缺口 |
| 自然每日 | 正式自然调度和跨日父链 | OUT_OF_SCOPE，首轮不承诺 |

计划不会在源缺失时制造候选名单；不会借“影子”名义增设第二采集owner；不会把9dfa snapshot称最新现役。前述原结果的个别文案仍称“60个完整交易日”，与实际窗口保留半日的实现存在语义张力；首轮保持原字节和原文并在验收记录注明，不顺带改算法或历史结果。

## 5 自审结论与实施前审阅

覆盖：规格第5.1的版本组合、发布健康、原reader封装、影子回执分别对应任务3、5、4、6；来源/PIT与目标环境对应任务1、2、4、7；独立回滚对应任务3和7。14类其他职责、自然调度、生产者接管和业务页面拆包明确后置。

接口已按第2节统一，测试分别覆盖Review Focus五项。运行和发布步骤均尚未执行，本文中的Expected结果是目标，不是证据。

建议按任务逐项开发并逐项独立审阅，因为来源版本和PIT错误会给出看似成功的名单。请用户确认本计划是否准确表达首轮范围，并选择这一逐项审阅方式，或选择由同一实现者完成全部任务后做一次整体验收；计划和方式获审前不开始产品实现。
