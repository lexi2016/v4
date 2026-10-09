# 经理工作台今日仍未选出：R3 修复问题包

**用户要求：修复后必须能沿原每日链路形成真实研究计划和名单；本包供 Chat 修改代码、测试并交回 Mac 执行。这里交付的是问题包，不是已经修好的程序。**

先读 [Chat 实施任务](package/CHAT_TASK.md)，再读 [完整问题说明](package/README.md)、[根因矩阵](package/root_cause_matrix.json) 与 [现场证据](package/EVIDENCE.md)。源码清单在 [source_manifest.json](package/source_manifest.json)，实际只读观测在 [runtime_identity.json](evidence/runtime_identity.json) 和 [两种日期绑定结果](evidence/live_get_projection_20261009.json)。

## 本次已查清的问题

1. **候选尚未进入现役经理链路。** R1/R2 的隔离候选测试通过，现役 API 的经理文件仍对应 R1 前像。新 Issue32 版本恢复了预选接口，不能据此认定经理计划已恢复。
2. **调度器与 API 使用不同计划绑定。** 11:03 本机核对的调度绑定已启用 plan-only；API 却指向另一份禁用绑定，并且应用根不同。按静态代码，请求到达 API 后首先会被绑定 SHA 校验拒绝。实际 10/9 dispatch 是否发生尚无回执，保留 CANNOT_CONFIRM。
3. **今日输入仍有独立缺口。** US 原采集有自然回执，但今日 daily mapping 尚未物化；公告对应分析未导入；HK 主数据/资格与超跌输入缺口仍需按原 owner 处理。未完成评估不能显示为有效零入选。

目标日期为 **10/8 事后研究** 和 **10/9 当日研究**。保留真实执行时间、来源日期、cutoff、run 与 SHA。10/8 事后结果用显式 dynamic 验证，过去 auto 的历史资格规则保持；10/9 当日计划用普通 auto 验证同 run。合法通道独立消费，不能用旧日 fallback 或虚构名单补齐缺失。

## 使用边界

原 R1/R2 代码和独立测试继续复用；先补齐当前执行/配置身份契约和可审查的接续方案。当前 API 已包含 Issue32 三处预选修复，后续须在实际最新累计基线上做最小增量。发布仍由原唯一共享 owner 负责。

本轮 Chat 范围为代码、测试、非敏感配置示例及 Mac 交接；不包含本机真实 POST、补采、计划写入、服务启停或部署。实际名单、普通页面同 run、连续适用交易日自然运行另行验收，不以合成测试替代。

本目录保留 `package/`、`evidence/`、`tools/` 相对布局，下载包解压后可按说明核验。仅包含必要源码和精简证据，不含凭证、原始行情、账户持仓、实际计划/业务 state、依赖环境或构建目录。

**独立问题包验收已 PASS。** 32 个源码快照的字节与 SHA、当前事实及修正后的日期合同均已独立核对；1 个缺失路径和 3 个无预期 SHA 的来源明确标记。`package/README.md` 与 `package/acceptance.json` 保留 Writer 交接阶段记录，最终包装判定以随后 `review/` 回执为准。这个 PASS 不代表业务修复、现场部署或今日名单已产出。

分支：`codex/manager-daily-failure-20261009-r3`；父提交：`66bb05a2e12976775ccb997191ce943bae8cc9a5`。独立包装审查在 [review/independent_review.md](review/independent_review.md)，发布后逐文件完整读回。

`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
