# 资格 owner 闭环：已确认链、尚未确认的供给与最小合法接入

## 1. 先保存已经通过的 R1

附件 `receipts/independent_review_receipt.json` 的正式结论是 `FAIL_FOR_TARGET_RUNTIME_ACCEPTANCE`，同时代码 scope PASS，47项合成用例PASS、原回归132/6且基线同样132/6。不能改写成R1代码失败，也不能说全链通过。
本轮把 prior R1 的10个源码后像与附件 SOURCE_PINS逐个比较，10个SHA一致；新diff只涉及connect_selection.py，其他9个不动。原独立receipt和原R1 diff原字节保留。
收到的反馈包只有收据、源码和公开路径摘要，没有这些本机测试的完整stdout/JUnit原件；本轮验证的是附件身份及内部引用，不是Mac现场重验。

## 2. 源码能确认的 owner 图

| 角色 | 精确位置（包内 reference / received evidence） | 当前证据结论 |
|---|---|---|
| 经理读取端 | R1 `v4/manager_research/connect_selection.py:17-43` | 原来只传数据root/date，没有把既有reader支持的owner root/SHA接口接出 |
| 原读取验证端 | `domains/manager_research_evidence.py:49-102,127-219` | 已支持显式owner root/SHA；读原件和current/manifest/receipt四件套，不调用ensure |
| 原资格合同实现 | `stage_center/hk_universe_preflight.py:23-30,93-102,162-225` | 固定651、两个Futu plate、原canonical bytes及源SHA；这是现有合同，不是当今资格数量的结论 |
| 残留采集函数 | 同文件 `ensure_hk_connect_universe:457+` | 当前日Futu板块读取/写入，不能重建历史；函数存在不证明现行生产调度 |
| 原Stage调用路径 | `run_stage_center_tick.py:519+,623+` | helper存在，但main明确不跑legacy full-market producer |
| Stage数据根选择 | `ops/_run_stage_center_nodes_parts/node_entry.py:171-190` | hk_full_universe_root保留lineage，不是自动fallback；不能拿配置键当资格已生产 |

原闭环的**读取半段**是：
`原资格文件 + current + run/manifest + run/receipt → 已固定SHA的原owner规则 → domains.read_universe_evidence → R1/R2 read_scope → 原workspace候选过滤 → selection_diagnostics`。

**生产半段尚未证明**：当前哪个被授权的单一job真正采集/发布目标日membership，使用哪份未改写响应、实际取得时钟，以及该job的父调度/run凭据。原authority自身保留的 `origin_claim=NOT_ASSERTED_REQUIRES_PARENT_SCHEDULER_RECEIPT` 不能自证自然调度。

## 3. 两个数据根，不作越界推断

附件 current_runtime_context.json观测时点：2026-09-30T04:36:05.901291Z。

旧API绑定根：`/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data`。
反馈说明该根全量资格最新20260814、没有20260929/30。普通master最新20260928、694行无Connect资格字段。

V4 Stage配置中出现：`/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data`。
**附件没有该根目标日目录清单、四件套或原reader结果。**因此当前结论是“V4根供给未核”，不是“已证明全系统不存在目标日资格”，也不是“将环境变量改指这里就能通过”。工具仅对显式给出的根逐一核验，不自动在磁盘搜索或回退。

## 4. 一次有界只读检查后的分支

### A. V4根已有完整、同合同、目标日原件

不补采、不迁出第二份authority。用原reader全链通过后，检查产生这些字节的原run/父调度与唯一发布职责；将该已核数据root和原owner代码SHA绑定给经理。相同date/sha可复用，不改变原件时间。
工具可以给出三字段environment**建议**，但始终 `activation_allowed=false`；只读成功不是活动producer/授权/部署证明。两个显式根若存在不同有效SHA，停止自动选择，由原owner解释冲突。

### B. 有真实当前名单，但不是这个原owner的合同

不能改名、补壳、补source_role或虚构Futu plate去喂旧reader；显式owner参数也不是任意来源的通用插件接口。
须由当前**唯一权威数据层原owner**补齐该来源自己的原件、有效日期、取得时钟、manifest/receipt与读取合同；在该原权威边界完成源内兼容，再让经理消费。不能在经理里另写“宽松名单解析器”，不能把旧日期改成目标日。
实际全量数不是651时，也不能在经理端裁成651或放宽门槛；需要原owner按真实来源变更其合同，并重新冻结源SHA。此包未作该合同变更。

### C. 没有完整目标日原件

维持 `CANNOT_CONFIRM`，不调用残留ensure，不补current/manifest/receipt来制造成功。
下一允许的源级改动是**现有已证明活动的资格/全市场源owner**在同一job内持久化已获取的完整membership输入，向V4唯一authority根发布一次，而不是增加经理采集器/第二计时器。

补充读过GitHub源码快照 `8851f7f84e3d506d3f1317eec03ba92c8f49e324` 中 `ops/_macos_research_panel_daily_parts/hk_market_capture.py`：其函数读取两块plate后会按日期、OHLC、volume/turnover过滤snapshot，返回结果没有完整保留两块原始plate及取得时钟。**过滤后的行情rows不能作为资格名单**，`source_sha`本身也不补回丢失的原始响应。该快照README明确不是活动部署等价证明，故不把它指定为当前活动producer，也不提供对它的冒名“活动前像”补丁。

如本机证明该类现有job确实是活动源，最小合法接续为：在现有网络调用旁保留两块未筛选的原始响应及请求/完成时间 → 同一job沿原权威存储事务发布membership → 原reader读回 → 经理绑定。不得为新增membership输出再发一轮同源请求，不得用行情过滤后的subset，不得将现在获取的名单倒写为过去日期。

若现有项目根本没有被授权的活动资格job，需在V4唯一数据层明确**一个**责任owner和启用决定；当前Stage禁止旧full-market这条边保持原样。没有该真实入口/调用与当前源前像，不能声称已经交付有效producer补丁。

## 5. 本次最小diff究竟关闭什么

关闭“原reader跨release代码绑定参数没有被消费端暴露”和“原reader结构化拒因被扁平字符串吞掉”两个有限接线缺口。
不关闭真实资格原件缺失、当前producer职责未证、官方/镜像时间证据缺失、HK.09969→LLY正例缺失、UI展示缺口。
`available_at`在此资格reader中是本次只读见证时间；不是网络实际取得时间。保留原 `observed_at=captured_at`，不注入cutoff作假时钟，不能把现在验证资格当作过去完整选股PIT已验。
