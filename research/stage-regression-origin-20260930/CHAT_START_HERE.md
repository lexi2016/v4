# V4 三项回归与 205 输入证据包

状态：证据包已整理，等待独立只读复核。仅供引用，不可安装；本包没有修改业务源码、服务、计划任务或交易权限。

## 三项结论

| 范围 | 已证实内容 | 不能据此声称 |
| --- | --- | --- |
| A 股 STAGE_0925 | 最后一条有 A 行的正式回执是 2026-09-24，10 行，输入 188/193，RECOVERY / LATE_CATCHUP_REPLAY；不是自然完整成功。首个后续故障是 9/28 strict current missing/unavailable；9/29、9/30 为 naive/aware datetime TypeError，9/30 正式节点三次耗尽。 | 磁盘 a_auction/provider 修复及单代码 RECOVERY canary 未证明正式 205 输入恢复，也未证明进程加载这些字节。详见 [a0925.json](evidence/a0925.json)。 |
| A 股 STAGE_1445_1500 | 9/30 留下 202/205 行 partial raw artifact（SHA256 cddd12a4…），未写 A selection；API 回读为 CANNOT_CONFIRM / 0 行。A 的具体错误为 RESEARCH_SOURCE_WITNESS_INVALID:SOURCE_ARCHIVE_PROJECTION_SHA_MISMATCH。15:00 archive 晚于 cutoff 2 秒，选择器读取 14:00 archive；重建 projection 校验失败。 | 跨市场汇总的 first_failed_layer 不能单独归因 A；具体不同字段、source owner 和 helper 引入版本仍 CANNOT_CONFIRM。没有安全依据做整包或泛化回退。详见 [a_close.json](evidence/a_close.json)。 |
| 港股 HK_CONNECT | 11 个日期共 88 条正式回执、83 个含 HK 节点；有行的 31 条均匹配 selection_latest。最新有行匹配为 9/29 STAGE_0925 10 行、PARTIAL_WITH_ROWS、RECOVERY、覆盖率 0.10 / 缺 80；最新 READY 为 9/28 STAGE_1545_1555 9 行 RECOVERY；最近 NATURAL + READY 为 9/21 STAGE_1545_1555 10 行。 | STAGE_0930_0935 中，9/28–29 的严格 D-1 Top100 被 active snapshot cutoff 拒绝；9/30 的 0 行 sentinel 指向 9/29 security-master metadata invalid，但没有绑定到那三次 capture 尝试。不能由此证明阶段代码回归。详见 [hk.json](evidence/hk.json) 与完整脱敏 [88 条回执索引](evidence/hk_stage_receipt_index.json)。 |

HK READY/有行结果仍是阶段选择层状态。所有交易安全标志保持 false：production_allowed=false、buy_gate_updated=false、orders_sent=false。UI、实际加载源码 SHA 和历史 source/config/run 绑定均为 CANNOT_CONFIRM。

## 205 代码输入身份

原序唯一 205 代码数组见 [a0925_candidate_codes_original_order.json](input/a0925_candidate_codes_original_order.json)，文件 SHA256 为 cf16619116f85832c9bf1ba80c60a6166f37afee52f3ed4b379e76b6e708b71c。相同原序数组以换行 UTF-8 算法得到既有 expected 摘要 80f5a1c0bbed293b637d1a2bb25585de932ce5b235dd3ff0236fcb9a99d8eb69，以紧凑 JSON UTF-8 得到 reader 摘要 ed7370dd8a81ddc621d606c61b8df95095cdc2c9def7909ab8be5e02b214b073。不可排序，也不要把这三种摘要混为同一文件字节身份。

A0925 审计恢复了 preimage：canary 源码断言 fresh snapshot.codes 与 candidate.codes 相等，且 run 20260930-a_share_stage_acquisition_universe_v3-92023837d870 的 current/artifact 字节与 canary 记录绑定。原 canary receipt 没有持久化 fresh snapshot 原数组；这是证据限制，不是 codes digest 仍缺失。此前评论中未解释的摘要差异已核清为算法不同；保留 expected 80f5 摘要不变。

## 完整源码与固定来源

37 个计划源码中，32 个已在固定 PR15 handoff 清单中找到完全相同的相对路径后缀与 SHA256，均记录固定 commit/path/bytes/Git blob SHA1；不重复打包远端字节。另将清单未覆盖的 5 个直接依赖按原字节 SHA 导出到 source_export/files，并附一个 A0925 canary 源文件。canary 内唯一私有绝对路径已替换为标记；原始与导出 SHA、字节跨度和替换文本见机器可查的 [PLAN.json](source_export/PLAN.json)。这些来源只能识别候选磁盘版本，不能证明历史或进程实际加载版本。

完整 handoff 锚定 lexi2016/v4 commit bdc95a3f9d6d0313baeff2bf727ea82d122dc820，目录 research/mac-source-handoff-20260930；HANDOFF_FILE_MANIFEST 覆盖 2,063 项 payload，总仓库交接计数为 2,065，另含清单等元数据，两个计数范围不同；payload 共 39,643,992 字节。查看 [REMOTE_SOURCE_INVENTORY.json](source_export/REMOTE_SOURCE_INVENTORY.json)。a_auction、TDX replay provider 与 stage dispatch 三份既有差分已存在该固定 handoff commit，包内只引用，不复制。

上游固定引用：PR12 候选 cb33d2fe2241079f46ae5e09e605f11a2fd5462f；PR13 完整输入记账诊断 8af24212ecdbdd4105a44ac536f8b469b5ad9660；PR14 旧 Mac 适配前像 e865206c492dcb7505e72892ebf430d7746488c8（独立 10 项回执 SHA a649908305eb37d50aada8e8e814f4ba30018904add0e32c579936a12f0a59b7）；新安全拒绝 e790c1a577800e3fbde1d6b15cee0b7a0efd91ac 不应用、不复测。更早 PR12/13 Mac 证据锚 a60fbd8c55aa1fad637d8706ceada0db251ffb97，仅作既有来源引用。

## 给 Chat 的修复边界与最小验收

1. 对 A STAGE_0925，把 9/28 的 missing current 与 9/29–30 的 timezone TypeError 分开处理；确认真正 owner 和加载版本后再修最小兼容点。保留 205 原序、双算法输入摘要及既有 DECISION_LOCK；单代码采集 canary 不等于正式阶段恢复。
2. 对 A STAGE_1445_1500，先找出 projection SHA 不同的准确字段、生成 owner 和 helper 引入版本，再决定最小局部修复。保留 a_auction/provider 修复和共享 context/selector 所服务的其他有效阶段；现有证据不支持泛化回退。
3. 对 HK，恢复 cutoff 前及时 snapshot/source-capture lineage；继续执行既有 exact-date D-1 Top100 与 active-snapshot cutoff 校验，不放宽 PIT gate。区分 9/28–29 timing rejection 与 9/30 上游 security-master sentinel。
4. 每个候选改动绑定 source/input/config/run/artifact 固定身份与 SHA；确认 205 输入未变、A/HK 日期和市场边界未混合、partial 子池按既有规则保留有效可追溯输入并隔离坏源，显示截断不影响完整选股输入。
5. 分层报告 source、测试、runtime、API、UI 与自然运行证据。raw collector 行、canary、Stage 非空、配置指向、manifest 状态或 HTTP 200 都不能单独替代阶段语义成功；未确认项保持 CANNOT_CONFIRM。
6. 维持 production_allowed=false、buy_gate_updated=false、orders_sent=false。本包不授权采集重跑、部署、重启、回退、合并或真实交易。候选提交后由独立 reviewer 复核实际 diff、测试和目标行为；本证据包本身未做产品测试。
