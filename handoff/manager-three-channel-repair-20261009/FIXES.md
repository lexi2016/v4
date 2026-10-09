# 修复说明与证据边界

本次候选运行源码净变化为 **+316 / -77 行，7 个文件**。完整差异以 [source_manifest.json](source_manifest.json) 和 [patches](patches) 为准。原始任务见 [CHAT_TASK.md](reference/problem/package/CHAT_TASK.md)；本机验收边界见 [LOCAL_ACCEPTANCE.md](reference/problem/package/LOCAL_ACCEPTANCE.md)。

## 1. 公告：保留原产物身份，验回真实 owner 链

原正文生产者以紧凑 JSON 保存并对原始字节计算 SHA；`_capture` 却把 corpus、corpus manifest、batch receipt 重新格式化后复制，导致后续按 SHA 校验时失配。修复复用现有 `_copy_json_bytes`，只保留这三份原生产者文件的字节，不改变采集或正文算法。

CLI 原 readback 把返回投影拼成只有日期、哈希等少数字段的“产品”，再调用要求完整判断和来源的导入校验器，合法导入结果也会被拒绝。新 `validate_owner_analysis_readback` 直接校验原 API 消费投影，绑定完整 chain、源 run、catalog/handoff/judgment SHA、owner receipt、当前 handoff 和安全字段。原完整产品导入校验器继续生效。

Reader 必须为非空字符串；Reader 和 Reviewer 去除首尾空格后必须不同。独立审查还复现了两种同一来源身份缺口：缺失值相等可通过、64 位数字被 `str()` 转换后可通过。最终要求原生字符串及既有 run32/SHA64 形状，再校验关系和内容，两个探针均已通过。声明身份与文件绑定不能替代外部平台身份认证，也不证明实际正式审查已经发生。

合成测试从原 capture 代码进入正文验证、Reader/Reviewer fixture、registered handoff、owner import、readback 和 workspace consumer；同时验证任一前置正式产物缺失均不得导入。跨通道用例证明已导入公告可以被保留消费，美股缺输入仍独立显示缺口。[公告报告](announcement/REPORT.md)、[独立发现](independent_review/FINAL_REVIEW.md)。

问题包没有今日完整实际 capture、正式 Reader、不同主体的正式 Reviewer、导入产物。历史第一个断点究竟在触发、采集、外部交接或导入，仍为 **`CANNOT_CONFIRM`**；本次没有真实采集或导入。

## 2. 美股：连接现有显式动作，保留原 owner 与时隙规则

原页面“用既有材料生成计划”调用既有 `POST /api/v4/manager/research/workspace/refresh`，API 只调用计划 owner；即使已有 exact-session 原材料，也不会生成 daily mapping。新的真实路由回归在修改前得到 `NOT_RUN`，修改后通过原 `refresh_us_mapping_research` 形成合法 `VALID_EMPTY`，再让原计划 owner 消费其不可变 run/SHA。

API 在同源和 body 校验后，用原 5 秒预算准备美股映射；之后重新读取服务器时钟作为计划 cutoff，使刚保存的日映射可以进入本次计划。缺输入、失败、超时、busy 都保持可见；意外 RuntimeError/ImportError 返回有界错误诊断，同时原独立计划通道继续。超时复用现有 reader bypass，避免计划重入被阻塞的来源读取；已有 owner 控制防止废弃工作迟到发布。未来日期不提前触发 daily owner，保持原计划行为。

`us_mapping_preparation` 仅是显式 POST 的附加响应诊断，不保存为 owner 凭证或计划 authority。GET 继续只读已保存正式 owner 结果。独立审查发现无 run 的失败 DTO 可夹带任意 artifact 字符串；修复为无 run 时 artifact 必须为空，有 run 时先校验原生字符串 run32/SHA64，再用原不可变读取器校验保存身份。

晨间原 `MORNING_US` 幂等标识把全天准入时隙合并，早一时隙保存 `INPUT_MISSING` 后，稍后输入到达也只能重放旧缺口。现在标识为 `MORNING_US:<既有准入 slot>`：同 slot 仍逐字节幂等，下一已准入 slot 能消费后来到达的输入。没有扩大准入时窗、缩短间隔或增加调度。PREOPEN 原 no-US 规则保留。[美股报告](us_mapping/findings.md)。

原隔离运行证据为 run `a95450cd4b264fb6840308d7d2681cf6`、SHA `2ac764fa1d5b691c6db518ff35b278f89cceeedd3614549a6741d4e8987bfa67`，`VALID_EMPTY`，配置/可用 33/33，reviewed 4，US/HK 命中 0，full_market=false。17:23 现役 daily `NOT_RUN`、plan `NOT_MATERIALIZED` 是另一组观察。绑定不一致不能独立证明历史因果；首个现役断点仍为 **`CANNOT_CONFIRM`**。实际 reviewed/registry JSON 未提供，回归使用临时合成配置，没有补造运行资料。

## 3. HK 超跌：exact-date 诊断与一致 witness

原 `entries[trade_date]` 缺键被包装成泛化 StoreError，screen 又丢失内部原因。修复引入有界 `HKSecurityMasterReadError`，将缺 exact-date 索引项与坏 schema、不可读 metadata、身份、receipt 或 SHA 不符区分。`data_context.security_master_read` 包含 status、reason_code、requested_trade_date、validation_stage、latest_json_sha256、entry_count、latest_entry_date、requested_entry_present。普通未分类错误仍保持 `CANNOT_CONFIRM`，不误报为缺键。

screen 显式引用问题包提供的 upstream master owner；原同名嵌套 reader 及 daily supplement 没有修改。新 snapshot reader 在一次 index 观察中验证 manifest、receipt、artifact 并解析同一份 artifact 字节，witness 也来自该 snapshot；避免第二次读 index 把同日另一 run 的身份拼到旧行上。原二返回值 reader API 保留兼容包装，receipt 的日期也必须与请求日期一致。该并发指针问题由合成测试证明，不能据此归因某次真实故障。

缺输入或输入未核实时，9 个不可得计数改为 null，`counts_known=false`，结果数组为空；成功读取时 `counts_known=true`、数量为真实数值。现有前端 API validator 接纳严格的 unknown 契约，继续拒绝伪 READY、伪已知计数；旧数值形式 DTO 仍兼容。没有修改页面布局。

有效 exact-date 合成分支即使 index 中存在较新日期也只取目标日，进入真实 screen 计算并得到 `READY_WITH_GAPS`：输入 1、pending 1、selected 0，成交量单位仍 `NOT_PROVEN`。它验证正向读取路径，不把未知量伪装成可选股票。[HK 报告](hk_screen/diagnosis.md)、[前端测试](after/test_delta/apps/web/src/api/managerWorkspace.threeChannel.spec.ts)。

16:01 历史投影显示 36 个日期至 `20260930`、缺 `20261008`；17:34 当前只读复现看到 37 个日期至 `20261009`，仍缺 `20261008`。16:01 原 index 未提供，历史字节重放为 **`CANNOT_CONFIRM`**。17:23 的 `20261009` 收盘后 StoreError、16:50 exact-date panel 缺失分别保留，不能混为同一故障。695 行 Futu 快照未被证明是 D1 主表，未使用或转换成主表。修复不会创建登记项、恢复真实数据或替代日期。

## 4. 独立审查与未运行范围

独立 reviewer 复现并关闭两处 P2 校验问题，没有未关闭的候选 P0/P1/P2。定向兼容检查中唯一剩余失败在原基线同样出现，详见 [TESTING.md](TESTING.md)。没有削弱旧测试、skip 或 xfail 处理。

现役集成/重启、调度和绑定修改、真实状态写入、真实公告/外部模型审查/行情采集、完整原生应用导入、全量类型检查/构建、全仓测试、Mac 本地验收、API/UI 实际读回及自然时段运行均未完成，不纳入候选通过声明。所有运行仍受四项 research-only 标志约束。
