# 独立工程审查及修复证据

两名独立代码审查者只读检查了本轮增量，发现 5 项 Important、0 项 Critical。原始报告按修复前状态保留在 `evidence/review/`。随后每项均先写回归并确认失败，再修复；最终整合者复核源码并重新执行相关测试。下表是工程修复闭环，不代表原 392 条公告获得了新的独立语义审核。

| 发现 | 修复 | RED / GREEN 证据 |
|---|---|---|
| 通道回调内产生的 heartbeat 晚于调用前 now，被误判为未来 | 默认时钟改在回调后重新采样；显式 now 仍固定 | manager/interface-review-red.log 与 interface-review-green.log；submit、poll 两个子场景 |
| recovery 缺 exact run journal 仍被旧手动计划兼容逻辑放行 | 仅 recovery read 收紧原 verifier 的 None 返回，在原 daily_channels 生成前拒绝 | manager/current-recovery-review-red.log 与 current-recovery-review-green.log；删 exact、删 exact+latest、同日兼容对照 |
| reviewer 声明的 semantic SHA 与实际输入 SHA 不符仍可领取任务 | 只读 preflight 在 claim 前比较 SHA | manager/interface-review-red.log 与 interface-review-green.log |
| 前序 lane 执行期间 reviewer 文件移走，announcement 仍先 claim | 每个公告任务实际 claim 前调用可选只读 preclaim hook；owner 内仍二次校验 | manager/interface-review-red.log 与 interface-review-green.log；实际账本无公告尝试 |
| 原 reviewer 字段比较混同 bool/int/float、丢失小数精度 | helper 以 Decimal 无损解析，递归检查 JSON 类型和值，拒绝 NaN/Infinity | revision/strict-json-red.log、strict-json-green.log；root-tool-final.log 与 root-gate-final.log |

以上日志路径均相对于 `evidence/`。最终经理/接口 82 项回归与 e06d 全 126 项套件通过；超跌独立审查未发现需修改项，18 项新增身份回归通过。完整 discovery 的基线失败另见 `VALIDATION.md`，没有隐去失败或移除 opt-in。
