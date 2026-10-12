# 给 Chat 的实施任务

请在私有仓库 `lexi2016/v4` 中按本包实施 V4 公告脚本初筛与本地 Qwen3.8 研判。以 `REQUIREMENTS.md` 为需求与验收边界，以 `SOURCE_MAP.md` 的 canonical/R6 SHA 和逐字快照为源码证据，以 `vibe-reference/snippets/` 作为 UI/接口形态参考。这个包是模块 source overlay，不是可运行 fresh app。

先核验实现分支的基线与文件 SHA，再分别检查 canonical `/Users/lexi/Desktop/学习/v4_app` 和声明的 8873 R6 根。两个根有实际字节差异；按 SHA 分开理解，禁止把 R6 文件覆盖到 canonical 或反向混合。Vibe 的 15 条、5 条、60 行只是不同页面/接口的历史限制，不是 V4 公告池边界或完整性规则；Vibe 的公告接口是 A 股关注股数据，HK 未接入。先确定可复用的原 V4 capture、body、semantic、owner import/readback 与 scheduler hook，再只做必要实现，不另建 producer、定时器或面板。

实现脚本先筛目录和完整正文：只有充分确定且无数字/异常条款的低价值例行项可以显式 `SKIPPED_ROUTINE`，其余重大/模糊/混合/未知项交本地已验证的 Qwen3.8 阅读正文。不得云端付费 fallback。先验证真实权重身份，不把 alias 当身份。cache key、singleflight、原子写和 provider usage 按 `REQUIREMENTS.md` 落地；失败/截断/语义不通过不缓存为成功。

保持 target date 与 publication date 全链相同；首个验收固定 target `20261012` / publication `2026-10-11`，不可误消费 HK `pub09`。扩展原完整语义集合同步纳入脚本 judgment，不伪造 AI 已读，不绕过 owner 的 source/PIT/consumption 校验。保存两条已知语义错误作为反例。完整保留 23 条目录覆盖，其中 21 条有正文、2 条失败的冻结测试输入；由独立标注先冻结 recall 分母/阈值后再调用真实模型并报告质量、调用和 token usage。不要额外全量 AI 调用作 baseline。

交付实现 diff、针对性回归、命令与结果、实际 token/usage receipt、model identity、date/run/SHA、scheduler 调度证据、owner API/import/readback 与各自状态。未实际证明的模型、自动化、页面、部署或自然执行标 `CANNOT_CONFIRM`/`NOT_RUN`；不以 HTTP 200、Writer PASS 或本交接包称为完整验收。保持 RESEARCH_ONLY/production/BUY/orders 四个安全 flags 不变，不能由公告研判生成交易动作。
