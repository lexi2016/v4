# M16验收与回滚

本清单待执行，未声称产品通过。状态统一为：代码接入、真实数据通过、页面可用、自动接续、完整验收。五项分别登记；工程测试单列证据，不替代真实数据、页面或按原触发合同的自动接续。

## 原测试与新增断点

在完整隔离原owner环境、已有Mac解释器保留：
- tests/optimization/test_manager_transactions.py：GET迁移零字节变化、缓存metadata重验、并发写冲突、receipt失败不publish、cancelled generation拒绝晚到进度/commit、事件合并最新财务、product/job/receipt原子绑定、双实例不能认同attempt、错误不泄密
- tests/test_manager_lifecycle_hardening.py：symlink拒绝、tampered cache不READY、跨实例冲突、receipt失败、发布前取消
- tests/test_manager_contract_hardening.py：真实精确日期/cutoff、row身份、市场拼写、嵌套交易语义拒绝
- tests/test_manager_research_router_contract.py：date必须、真实日、bodyless events、来源故障状态
- tests/test_manager_research_catalyst_service.py：初始资料及事件更新保留facts，event outage不READY，不重收财务
- tests/test_manager_research_service.py：原财务研究语义与单位；涉及真实EVIDENCE_ROOT的测试需核原件，不能造fixture冒当原回归
- 相关decision recovery合同仅在确有影响时回归，不能改其cutoff/time规则。

新增V5 test_manager_jobs.py：纯GET全目录/锁/任务数零改变、相同输入幂等、变更输入新identity、重复点击、队列满、timeout、重启遗留owner、取消竞态、轮询中断不误取消后台、事件并发merge、同run读回。先失败用例后最小修复；固定最终候选重跑原及新增，历史测试数量不相加。

## Mac真实业务

1. 核原固定候选/观察source、当前唯一provider、worker与store版本，记录非秘密config及私有根，V4/M13/M18摘要不变。
2. 一次真实已授权候选任务提交→排队/运行→product/job/receipt提交→普通GET与job轮询同identity/SHA。无输入时明确拒绝，不生成空财务成功。
3. 真实重试、取消、事件更新分别验证。保留前成功，新attempt不覆盖；事件更新财务收集计数不增且facts/receipt SHA保持。
4. 取消后即使慢调用完成也不能提交旧generation。重启后无owner任务不得绿装RUNNING成功；按原恢复合同留痕。取消页面请求不应误取消后台job。
5. 真实V5浏览器进入经理资料页、切日、刷新、后退/前进、重复生成、失败/重试、取消/结果、事件更新。普通进入与刷新不得发ensure POST；记录Network、页面截图、URL、run与代码SHA。
6. 非每日业务按原实际用户/事件触发验收，不强设日调度。下一适用调用与跨日隔离成立；任何未验项标NOT_RUN/BLOCKED。完整当前回归由集成者统一执行。

## 单模块回滚

发布者保存M16旧/新worker代码、路由binding与generation；排空/停止新接收并按原owner处理在途job，避免同时两个worker认领同store。失败仅恢复M16旧绑定，保留所有attempt/receipt/成功产物；不删历史，不回写V4，不回退M13或M18。回滚后验原product/job引用一致，普通经理读持续可用。

反馈同一Chat：commit/patch SHA、job/date/input/generation/attempt、各产物SHA、命令/退出码/完整非秘密错误、provider请求计数、GET写入差异、页面与回滚证据。不要凭页面关闭宣称后台已取消。
