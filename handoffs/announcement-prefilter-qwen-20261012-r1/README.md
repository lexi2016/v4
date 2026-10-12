# V4 公告脚本初筛与 Qwen3.8 本地研判交接包

状态：`HANDOFF_PREPARED_ONLY`。本包是后续 Chat 实施时使用的需求、源码参考和 Vibe 片段；不是可运行应用、修复提交、部署或验收结果。

用户目标是让 V4 先用确定性脚本筛掉有充分证据的低价值例行公告，把重大事件和拿不准的公告交给本机 Qwen3.8 阅读正文，避免同一内容反复消耗模型 token，并纳入现有每日自动流程。原有完整正文采集可复用。最终必须把结果交回原公告 owner，完成同日期 readback 与完整语义合同验证。

从 `CHAT_PROMPT.md` 开始，把 `REQUIREMENTS.md` 当唯一功能边界；`SOURCE_MAP.md` 说明两份 V4 源码根、精确 Vibe 片段、API/调度入口和未闭合依赖。`source/canonical/` 和 `source/r6-8873/` 是分别保存的逐字源码快照，不能交叉覆盖。快照只有选定模块和入口，不是完整依赖闭包，也不应作为 fresh app 启动。

当前可用于验证设计的冻结本地语料为 target date `20261012` / publication date `2026-10-11`，23 条目录记录中 21 条有完整正文、2 条正文抓取失败；该语料的语义状态是 `NOT_REVIEWED`，没有模型调用或筛选效果结论。`manifest.json` 只记录本地证据路径和 SHA，不包含正文、目录响应、行情、凭证或账户资料。

所有结果继续保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。本交接阶段未实现业务、未调用模型、未采集公告、未运行服务/计划任务，也未做 GitHub 操作。
