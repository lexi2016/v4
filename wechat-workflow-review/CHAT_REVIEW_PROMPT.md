# GitHub / Chat 代码审查提示词

请审查此快照中的公众号默认工作流代码。若同时提供了实际 Git diff，以该 diff 为主要审查对象；先核对文件映射/SHA，逐项查看真实改动和目标行为，指出具体文件、行号、触发条件与可复现证据。优先报告阻断默认 Drive/Chat 路线、包身份/回执绑定、原字节完整性、日期/行情来源校验、隐私泄露或 V4 Stage A 只读边界的问题。

如建议修复，请直接给出可应用的 unified diff，路径相对于本快照，并补充针对目标行为的回归测试及实际命令/结果。不要只给意向或伪造测试通过。若缺依赖或测试没运行，明确写 `CANNOT_CONFIRM` 及原因。修改后请把完整 patch 和测试证据反馈给用户，由用户决定后续集成。

审查须遵守这些范围：Drive 承担每篇文章私有资料与回传字节；GitHub 只承载代码、文档、测试和必要脱敏样例。不要要求把原始文章、图片、报告、五个真实回传文件、真实 receipt、私有 Drive ID、市场面板数据或凭证提交到代码仓库。九章报告、五个回传文件及包外表现附录按 README 中的合同检查。

保持 `RESEARCH_ONLY / WATCH_ONLY / NO_BUY_GATE`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。V4 Stage A 只能登记/只读展示既有归档引用。不得据此声称已在本机部署、登记真实文章、API_VERIFIED、UI_VERIFIED、自然时段通过或已上传 GitHub。此快照不含完整 V4 运行环境、采集插件和真实业务数据。
