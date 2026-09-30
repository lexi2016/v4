# Stage A/HK execution R4

固定输入：bdc95a3f9d6d0313baeff2bf727ea82d122dc820。原冻结 handoff 不修改；本目录保存源码候选的完整 Stage 前像、完整后像、实际新测试和原始红绿日志。

本轮起点核对没有发现已保存 R4 改动/日志，R4 远端仍在输入提交。现在已完成以下隔离研发，不声称延续了不存在的上轮代码。

## 实际功能

公开 run_nodes → 原 slot lock/共享阶段预算 → 单次市场 scope → 原 StageCenterRunner._run_one → 原 A/HK selector/RawStore/SelectionStore/consumer。

HK 合法 settled-partial 剩余预算内可只运行 HK，即使配置仍含未使用的 A 授权；不删授权、不调用 A authority、不重新采集或发布 A。瞬态失败重试保留原 backoff 和共享计数，封存 raw 可复用。原 raw bundle 用原 verify_run 读取保留市场的精确 raw SHA 后补齐，不能拿新采集替换已有市场。

A 一次额外恢复只运行 A。原三次+一次=4不变，第二次拒绝。真正 A consumed 后共享阶段原预算已耗尽，不能伪造独立 HK 剩余额度或把计数4清为1。本候选没有新授权、第二producer/selector或新数据根。

原回执写入统一保留非执行市场完整对象。正常、预期异常、未预期异常、磁盘写失败、KeyboardInterrupt 的测试均保留 A原结果/不可变文件/原latest中的A条目。共享current receipt会更新本次市场和计数；更新前完整旧receipt字节在原attempt_evidence下留存，不能称整个共享current字节不变。

## 源差异

三个新修改：stage_dispatch.py、slot_execution.py、runner_receipts.py。node_entry.py完整复用PR12后像；未导入e790c1a的拒绝guard。SOURCE_SHA256.json列明canonical/Stage before及after，不能两份叠加。

Stage before为node_entry 54defb…、dispatch dcb478…、slot_execution d55cfe…、runner_receipts 3d0d3f…。Mac已修collector728fa6…、provider02d750…、HK minuteb6c78a…、acquisition2806c6…原样保留。preserve_reference/acquisition.py只是Mac模式字段原件，不是新增权限。

research_context不在本批：Mac9/29四码特例与旧远端9/28二十七码不同，均不是9/30资格，不整文件覆盖。A1445不改。不停旧producer，不动经理/F5，不重跑五个有效A阶段。

## 实际验证

同一18项测试最终RED：7pass/11fail/0error/0skip，exit1；GREEN：18pass/0fail/0error/0skip，exit0。原日志与result在validation。旧10、58+1不重跑、不相加。

测试经真实公开入口、原runner/原kernel lock、原选择器及存储/consumer；行情、205输入和外部授权/加载身份、日历/exact-input是明确合成替身，不是Mac真实行情/PIT验收。没有实际HTTP8873或浏览器测试。

作者Linux Python3.13.5，不重装依赖，不为版本改业务；-o addopts='-W error'仅处理本容器不存在的Starlette warning类别。Mac当前服务解释器和依赖仍是最终目标验收。

测试导入载体用了既有缓存，修改文件和原runner/kernel lock/acquisition按固定源身份核对；不是整个680文件及全部依赖等价认证。早期fixture窗口错误、封存raw复用的错误测试预期已修正，完整下载包保留其原日志；最终红绿均使用已对齐原kernel锁，不把载体纠正包装成产品锁改造。

## Work一次接续

1. 新非活动隔离目录以canonical为编辑底本，逐路径保留Stage修复和所需拆分依赖。只有完整SHA等于before时直接应用差异；等于after则跳过，第三值三方适配。旧PR14/R3不能直接套本前像。已是e870…的node_entry不回装。
2. 下载包的runtime.patch只改四个目标文件，complete.patch另含新测试，二选一；不能叠加。GitHub本目录before/after与该包同字节，可生成同一差异。先git apply --check，再在隔离目录应用。不要写活动release，即使目录名叫candidate。
3. 以实际SERVICE_PYTHON只执行 tests/test_stage_ah_execution_r4.py，保存stdout/stderr/exit/JUnit；按风险独立审核scope、共享预算、异常保全、bundle重读与入口旁路。复用未变化旧测试结果，不以固定模型身份作门禁。原builder发布pin更新是另行批准的非活动候选步骤，不自动全量repin或部署。
4. 代码回退只恢复准确before，不能删除receipt、attempt、raw/selection、consumed marker，不能清零额度。真实补跑与部署另行授权，本轮没有APPROVED对象。

## 真实验收缺口（一次列清）

A205：原reader报告ed7370…、guard80f5a1…；本批常量/输入顺序不改。原序数组、生成预期SHA的原数组来源及current/artifact各自绑定仍需原件，六attempt正文仍未取得；由Work对原指定文件独立核验，不要求不同对象hash相等，不用排序凑值。

HK：64摘要3sample不是完整SourceResult。准确D-1/二筛资格、完整输出/明确missing、真实来源和时间仍缺，不能凭本合成通过采集补跑。没有重做已撤回HK ZIP或实现新盘中池。

后续合法产物齐备后，Stage/API实际加载路径/SHA、同一读取根、普通API/UI的date/stage/market/run/hash/行序/NO_BUY/NO_TRADE/formal值须逐项一致；成功和异常时A原结果不能被清空。当前Mac独立组合验收、集成、部署、真实API/UI和自然时段均NOT_EXECUTED。

A1445仅留原receipt/首拒因、最后正常→首次失败差异、raw/selection、归档source witness/cutoff、API读取根。不得归因旧PR6/7或借0925额度。

RESEARCH_ONLY；production_allowed=false，buy_gate_updated=false，orders_sent=false。9月30日授权不跨日延长。
