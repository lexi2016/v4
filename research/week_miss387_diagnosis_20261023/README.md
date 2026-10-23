# 387条共同漏选诊断源码

冻结输入为此前独立PASS的387个(code,selection_date)事件，不包含完整原行情或私有公式。此目录只提供诊断/独立核验实现；生产模型、阈值与输入均未修改。

真实执行顺序：diagnose.py prepare → canary --workers 2 → full --workers 4；后续source_mapping.py验证原文→AST规范结构，report_builder_r2.py从已有DETAILS生成原子阻断和中文报告；verify.py由独立Reviewer调用。源公式/原engine/运行输入依赖保留原本Mac路径，本源码不是脱离冻结输入即可重跑的独立数据包。

最终本地入口：研究目录week_miss387_diagnosis_20261023/presentation_r2/TECHNICAL_REPORT.md；契约与manifest位于该研究目录。原初report_builder.py属于已终结的失败投影历史，不列最终同步allowlist。第一次技术合同仅静态发现诊断砖阈值严格性差异即终结，未做数据计算；实际全387属于DIAGNOSIS_CONTRACT_R2/execution02。

证据边界：A255/B10/inputSHA归档parity387/387，独立numeric无差异；独立shunting-yard原文结构映射A255/B50通过。原平台客户端全公式parity、historical PIT/资格/名称时点、跨商volume/amount单位仍CANNOT_CONFIRM；B参考器NOT/HHVBARS不可达，未验证其通用能力。D当日触发仅后验。

不包含服务发布、UI/API、真实交易或GitHub同步动作；ROOT另行核定源码allowlist并CAS同步。保持research_only=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。
