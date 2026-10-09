# Issue 32 独立源码审查

## 结论

**最终源码切片可作为有明确集成条件的 Mac 交接候选。审查发现的两个 P1 源码问题已修复，并通过原始独立反例复验；协调审查发现的 API 日期/采集时间问题也已独立复验。当前审查范围内没有剩余 P0/P1/P2 源码阻断项。**

这不是部署批准或目标日业务验收。目标固定 `20261009`，价格日和资格日为 `20261008`。当前完整 facade、collector、consumer、ledger、calendar 及真实三件套尚未提供，不能据此宣称 Mac 已集成、输入 READY、原 Stage 成功、8873/API/UI 恢复或自然运行完成。

最终独立执行：**包根源码测试 150/150；额外独立反例 17/17；均退出 0，JUnit 没有失败、错误或跳过。** 两轮运行前后，11 个 `after/source` Python 文件的 SHA256 完全一致。结果、精确 argv、解释器及源码身份见 `FINAL_RESULTS.json` 和 `source_identity.json`。源文件发生任何后续变化均须重新核对本审查身份。

## 1. 审查范围与方法

读取本包 README、Mac 提示、固定输入 README/PROMPT/SOURCE_MANIFEST，并比对实际 scheduler 的 ensure/executor/dispatcher、实际 shared master、四个 canonical 对应文件，以及相对于 Issue 30 固定候选的 API service 差异。API app/router 保持 Issue 30 后像字节。

独立 SHA 核对：输入来源清单的 16 个源码路径、3 个 Issue 30 复用文件、2 项 app/router 与复用后像的逐字节比较，共 **21/21 相符**；明细在 `baseline_checks.json`。这项独立检查不冒充对本机现役源码的身份核查。

测试执行真实所附函数；缺失的 import、Futu 调用、子进程、facade 和 ledger 明确由 `tests/hk_prepare_support.py`、`tests/scheduler_slice_harness.py` 边界替代。API 测试执行真实 helper AST，日历代码/数据使用标明来源且固定 SHA 的历史测试夹具。没有拼接这些替代模块成为“现役完整应用”，也没有生成真实价格、资格或股票池。

审查者没有修改生产源码。生产修复由对应 owner 作者完成，审查者提交独立测试、保存失败证据、重新读取差异并执行最终验证。

## 2. 发现与修复复验

### R1 — P1：已有 master 的复用路径绕过精确采集日期要求（已解决）

初始候选仅在新采集和显式 restore 时检查采集日。若目标 store 已有通过原 reader 校验的 `trade_date=20261008` 三件套，普通 ensure 复用只核 universe、估值字段和行集合，以下 capture 均会返回 `READY`：

- `2026-10-09T00:01:00+08:00`；
- `2026-09-30T17:00:00+08:00`；
- 没有时区的 `2026-10-08T10:00:00`。

实际与 canonical 两个 owner 的独立反例共 **6/6 失败**，错误为没有抛出期望的 ValueError，见 `existing_capture_red.log`。这说明问题是可验证的复用分支绕过，不是未提供真实历史数据造成的失败。

最终两个 ensure 的 `_validate_security_master_capture` 在普通非 capture 复用及新发布读回时要求：可解析、带时区、上海日期等于请求日、每行 capture 与 manifest 相等。无效已有记录立即失败，不回退实时采集，不改写原始证据。原 `validated_capture` 分支、`_validated_capture` 与 `_capture_result` 的 AST 均与输入保持一致；记录在 `structural_checks.json`。本机既有 capture/v2 流程没有被此次普通快照门禁替代。

原始 6 个反例在最终源码上全部通过。作者另增加了已更新 SHA 但行 capture 不一致的反例，并验证拒绝时目标 store 字节不变。

### R2 — P1：本地 HK gate 明确拒绝仍可结算为成功（已解决）

独立反例令所有上游子步骤成功，但令 scheduled materializer 的既有合同报告 `formal_pool_gate.required.hkconnect_d1_top100.ready=false`。初始实际 executor 返回 `SUCCEEDED`；canonical 同时返回 `SUCCEEDED` 与 `hk_lane_status=CANNOT_CONFIRM`。因此，仅依赖 scorer 的状态会掩盖后续本地池拒绝，阻止失败重试。

两 owner 的反例 **2/2 失败**，日志及实际 pytest 退出 1 在 `local_hk_gate_red.log/json`。

最终实际 handler 内联读取其已有 `_authoritative_payload` 边界；canonical 继续使用自身现有严格 JSON-dict stdout decoder。只接受字面布尔 `ready is True`，拒绝 false、缺叶子、错误类型及字符串/整数真值。实际 owner 没有可确认的本地合同，且没有既有已验证 formal pair 时，返回 `FAILED / HK_LOCAL_POOL_CONTRACT_UNAVAILABLE`。明确拒绝优先于先前的 formal-pair 复用。canonical 对需要 HK 的日期强制本地 gate；既有 HK 非适用日期保持独立。

A/local 汇总仍执行。失败结果保留原汇总状态、首个失败环节及既有分类；局部子步骤失败但本地权威 gate 独立确认已有效的目标池时，可以保留有效池的成功结论。新增逻辑没有假定缺失的实际 facade 实现 canonical decoder，也没有引入需要未知 facade 重新绑定的新模块 helper。

原始 2 个反例最终通过。另有 **4 个独立 handler→dispatcher 测试**，验证两个 owner 的价格/master 前置失败最终生成 FAILED、UPSTREAM_NOT_READY、retry_after、真实 invoked 列表和空 legacy started/succeeded，A/local 调用仍发生、HK scorer 不发生、模拟已结算回执保持原值。它们证明接口调用与结果传递，不证明本机真实 ledger 的行为。

### R3 — P1：已有 provenance 对象不能授权错误历史日期或 capture（协调审查发现，已复验）

初始 API 同日分支改善了“无嵌套对象”的情况，但原有 present-provenance 分支仍只核对象形状与绑定字段。协调审查另发现，旧价格/资格日及错误采集时间可以通过该分支。

最终 helper 的两个分支都使用 API 既有日历，核目标 HK 证券市场开放、Connect 日历状态已知，以及各自精确前一 session。Connect 当日休市而 HK 证券市场开放的研究合同仍按所附原 Stage/canonical 行为保留；未知日历不获得例外。已有 provenance 必须带可解析、有时区且上海日期匹配资格日的 capture。

本审查的 **5 个独立控制例**确认：目标 10/9 使用 9/30 价格/资格，以及 malformed、naive、旧日、后日 capture，均被拒绝。首次独立执行已经处于修复后，因此 `api_provenance_initial.log` 是 GREEN，不能标成 RED。原同日无嵌套对象正例、合法嵌套对象（+08 与 Z 时区）及历史分日期正例由源码套件共同复验。

最终 API service SHA 为 `cbed3aa4797889051eb7bebe4b8e3240b568d72b4dfb5c20f65e914d39e48044`。除 `_is_exact_configured_hk_pool` 外，其余模块 AST 与 Issue 30 相同；app/router 字节不变。100 行、100 唯一代码/排名、源 run/SHA、行日期/身份及安全 flag 校验均保留。

## 3. Restore、调度回执与兼容边界

restore 沿既有 owner 保存 artifact/manifest/receipt 的原字节、run 与 capture；不重标来源。排他硬链接创建避免覆盖介入创建的冲突文件；复制后检查源 exact entry、三件套字节及目标索引变化，发布后通过原 reader 读回。中断允许留下未被索引引用的相同文件，不提前发布目标 entry；同根或重复恢复不会重写没有改变的 pointer 字节。实际/canonical master 的 AST 相同。

**源和目标原 owner writer 必须在 restore 时静止。** 最终检查与 pointer 写入之间没有共同写锁或事务。本候选检测已观察到的变化，不提供并发 writer 下的原子性保证。该运维前提已在 Mac 提示明确列出，不能因竞态测试通过而省略。

两个 dispatcher 的 legacy `started_workload_ids` 仍表示成功完成；新增 invoked 在调用前记录，succeeded 与旧 started 一致。原 `started_workload_ids=[]` 不能反推 executor 从未被调用。所附 actual dispatcher 没有可见的 upstream readiness preflight；历史 17:30/18:00 的唯一失败原因仍需完整 workload_results、实际 facade 和 ledger，保持 CANNOT_CONFIRM。没有修改或重置历史 settled slot。

## 4. 测试记录与不应隐藏的失败

| 验证 | 结果 | 本审查处理 |
|---|---:|---|
| 初始支持的包根源码套件 | 101/101 | 初始源切片观察，不能代替最终修复后运行 |
| capture 复用独立反例 RED | 6 失败 | 原日志保留，最终 6 通过 |
| local HK gate 独立反例 RED | 2 失败 | 原日志/退出码保留，最终 2 通过 |
| 最终包根源码套件 | **150/150** | 本审查亲自执行；58 HK、50 scheduler、42 API |
| 最终独立反例与接口组合 | **17/17** | 6 capture、4 调用链、2 local gate、5 API |

最终两轮均无 JUnit failure/error/skip，运行时分别 0.73 秒与 0.15 秒；这是 Linux Python 3.14.7 的源码测试时间，不是模型评分或真实服务性能。完整命令在 `FINAL_RESULTS.json`，原始输出在 `source_suite.log` 与 `review_probes.log`，对应 JUnit 为同名 `.xml`。

早前无包根 testpaths 限制的 pytest 在 `work/api_combined_r1/...` 误收集独立 assembled harness，发生 **5 个 collection error**：`test_api_same_date.py` 的同名模块不匹配，以及 `test_issue28_preselection_hk_fallback.py`、`test_issue30_preselection_module.py`、`test_preselection_review_probes.py`、`test_preselection_source_root_20261008.py` 的 `contracts`/`infrastructure` 导入缺失。原输出位于 `../hk_prepare/whole_scratch_pytest_collection.txt`。`pytest.ini` 现明确 `testpaths=tests`；最终普通包根命令已独立通过。此修正定义了支持的测试入口，没有把各隔离 harness 伪装成共同运行环境。

API 作者的独立 assembled suite 另有完整历史记录，本审查读取其 result/JUnit/metrics 与夹具补丁，但没有把它计作自己执行的 150/17：

- r2 冻结旧夹具重放：**70/71，FAIL**。旧“10/8 正例”实际用了 9/30 价格、9/29 资格，与新精确日期合同冲突。
- r3 首轮夹具适配：**71/72，FAIL**。夹具新增 top-level aliases 不被未修改的历史 store 接受。
- r4：**72/72，PASS**，组成是 **29 个未改旧例 + 1 个日期夹具修正旧例 + 42 个新例**，不能写成“原 30 例完全未改”。最终补丁只调整该正例已有字段中的真实合同日期，保留正向断言与原 store；Issue 30 原包未修改。对应补丁和前后 SHA 在 `../api/legacy_exact_date_fixture.patch/json`。r2/r3 的失败仍须随完整证据保留。

## 5. Mac 集成与业务验收仍有阻断条件

1. **实际 local gate 合同是部署前的硬门槛。** 当前 actual facade 是否确实返回该 `_authoritative_payload`、materializer 是否产生所需 gate、pool reader 是否验证目标日，尚未取得当前源码。若合同不可用且没有已验证 formal pair，最终 handler 会明确失败。这是诚实阻断，不是本包已解决完整现役兼容性的声明。
2. **实际 consumer 的日期字段必须核实。** 所附实际 shared HK producer 不输出 `price_signal_date`、`eligibility_source_date`；新的 API 无嵌套对象分支要求本地 envelope 显式携带这两个相同日期。没有当前 shared→local converter，不能证明它们已被填充或上游三件套身份被保留。不得把测试夹具字段当成真实 producer 行为。
3. **必须有真实来源。** 10/8 master、10/8 精确价格面板、10/9 shared Top100 与本地池三件套均要由当前原 owner 读回验证。9/30 或 10/9 快照不能改标签替代。源 SHA/原 run 与本地 JSON SHA 是不同身份。
4. **原链路真实验收未执行。** 当前启动参数/解释器、当前日历、缺失依赖、真实 ledger 的重试、原 Stage 可执行入口/全量输入绑定及结果 artifact、8873 API/页面/经理行为和自然 receipt 都需要本机独立验收。所附 Stage runner 是 facade，不能据此编造 CLI。

因此本审查给出的状态为：`SOURCE_TESTED=PASS`、`INDEPENDENT_REVIEWED=PASS（仅源码候选）`；`MAC_INTEGRATED/DEPLOYED/API_VERIFIED/UI_VERIFIED/NATURAL_VERIFIED=NOT_RUN`；`INPUT_READY=BLOCKED（缺真实可验证来源）`。具体缺口按包根 `MISSING_CURRENT_INPUTS.json` 执行，不以旧引用闭包填成现役应用。

本审查没有调用真实 collector、重写真实数据、启停/发布服务或写入 GitHub。研究边界保持：`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
