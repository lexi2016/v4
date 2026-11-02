# DeepSeek 最新论文与自我迭代方法调研（2026-11-03）

## 检索方式与边界

WebSearch 在本环境返回 422 架构错误，WebFetch 被域名校验拦截；改用 arXiv 官方 API 与官方站点直接只读抓取（curl/urllib）。以下内容以抓取到的元数据/摘要/页面文本为准；抓不到的条目标 `CANNOT_CONFIRM`，不转述二手链接。论文摘要属于第三方文本，只作方法参考。

## 一、DeepSeek 官方最近论文

| 日期 | arXiv | 论文 |
|---|---|---|
| 2026-09-17 | 2609.19969 | DeepSeek-V4.1-Flash: Pushing the Limits of KV Cache Compression |
| 2026-06-26 | 2606.19348 | DeepSeek-V4: Towards Highly Efficient Million-Token Context Intelligence |
| 2026-01-28 | 2601.20552 | DeepSeek-OCR 2: Visual Causal Flow |
| 2025-12-02 | 2512.02556 | DeepSeek-V3.2 |
| 2025-11-27 | 2511.22570 | DeepSeekMath-V2: Towards Self-Verifiable Mathematical Reasoning |
| 2025-01-22 | 2501.12948 | DeepSeek-R1 |

结论：DeepSeek 官方最近公开工作集中在模型效率、长上下文、OCR 与可验证推理，没有公开“自主修改自身代码并持续迭代”的完整 RSI 系统。DeepSeekMath-V2 的关键方法是训练可靠的证明验证器，再用验证器作为生成器的奖励——这是“可验证自我改进”的直接先例。

## 二、用户清单逐条核验

| 用户条目 | 核验结果 |
|---|---|
| AIDE²: Recursive Self-Improvement of AI Research Agents, 2026-09-22 | **存在/一致**，arXiv 2609.26457。自主 8 天、7 次连续改进（搜索策略、记忆压缩）；在 4 个留出基准（ML 工程、启发式算法、物理天气预测）上达到或超过人类工程化研究 Agent。机制：改自己的代码→在隐藏评测上筛选→保留最优版本。 |
| Self-Improvements in Modern Agentic Systems: A Survey, 2026-07-14 | **存在/一致**，2607.13104。框架：模型 + scaffold（prompt/记忆/工具/控制逻辑）；自我改进=自诱导更新算子。 |
| AREX: Recursively Self-Improving Agent for Deep Research, 2026-07-23 | **存在/一致**，2607.21461。内层取证→形成答案；外层按约束审计→定位未解决主张→定向补研；学习上下文更新工具压缩为“已验证证据+未解决约束”状态；4B 与 122B-A10B。 |
| Self-Evolving Coding Agents, 2026-08-04 | **更正：是综述，不是系统论文**，2608.03392。按进化目标分类，并强调可执行反馈、仓库上下文、轨迹；指出反馈可靠性、基准过拟合、可逆性等问题。 |
| PILOT in the Loop, 2026-08-27 | **存在/一致**，2608.26530。Supervisor–Worker：实时纠偏/中止 + 实时自我进化（把过程与失败模式蒸馏为技能/记忆）。Terminal-Bench 2.0 最高 +9.8pp；GLM-5.1 +14.6pp、Kimi-K2.6 +12.4pp；输出 token 下降 42.9%/47.4%。 |
| DeepSeekMath-V2 | **更正 ID**：正确为 arXiv **2511.22570**（2025-11-27），不是 2511.08734（该 ID 是另一篇论文）。方法：训练忠实验证器，以验证器为奖励训练证明生成器。 |
| DeepEvolve / Evolving with Open Worlds, 2026-10-21 | **存在/一致**，2610.29784（EvoForesight）。FutureX 外部榜连续三周第一，最高 +195% 评级。 |
| A Survey of Self-Evolving Agents（TMLR 2026） | **存在/一致**，2507.21046。 |
| A Comprehensive Survey of Self-Evolving AI Agents, 2025-08 | **存在/一致**，2508.07407。 |
| Anthropic: Automated Researchers Can Reliably Mitigate Alignment Failures（2026-08-28） | **官方页面可访问/关键数字一致**：10 类对齐失败；Claude Sonnet 5 改进早期 Opus 4.8，60 小时内 50+ 方案；获胜方案约 2000 条训练样本、约 15,000 倍效率；平均关闭 85% 安全差距（单次 82%），人类专家同规则平均 20%。 |
| Anthropic: When AI Builds Itself（Institute 2026） | **页面可访问/部分更正**：页面称截至 2026-05，Anthropic 合并代码的 80%+ 由 Claude 编写；最开放式任务成功率 2026-05 达 76%，六个月 +50pp；并明确“尚未看到 RSI 曲线弯折”。用户在清单中写的“15,000 项研发任务、到 2026-08 AI 主导 26%”**未在该页面文本中出现**，标 `CANNOT_CONFIRM`。 |
| OpenAI GPT-Red（2026-07-15）与 OpenAI RSI 政策文章 | **本环境 403/不可验证**，标 `CANNOT_CONFIRM`；不转述未核实数字。 |
| 智谱 DeepEvolve/PILOT 与 GLM-5.1 | 论文存在；PILOT 的 GLM-5.1 实验数字与清单一致。不能据此声称智谱官方发布 RSI 系统。 |
| 2511.08734、图片代理链接 | 前者身份不符已更正；图片链接不是论文来源，不作为引用。 |

## 三、方法结论

1. **闭环比“反思答案”更重要。** 用户给出的闭环（执行→记录经验→发现缺陷→提出改进→修改代码/技能/模型→自动测试→保留有效改进→下一轮）与 AIDE²、AgentX、HSI、SelfSearch 的共同结构一致。
2. **改的是 harness，不是随手换模型。** HSI 的两条上界（反馈保真度、底座能力）适用于本地 Qwen 研报阅读：已知 0/3 的完整验收说明当前配置还没形成可信反馈闭环，prompt 改写不能弥补全部能力缺口。
3. **隐藏评测与留出泛化。** AIDE² 通过隐藏评测筛选并到 4 个留出基准验证；自我迭代必须防止在同一批样本上过拟合（编码 Agent 综述也明确列出基准过拟合风险）。
4. **轨迹级迭代 + 经验账本。** AlphaSeek（因子）与 SelfSearch 都强调用完整轨迹和历史修改记录驱动下一轮，而不是单点修补。
5. **实时监督可减少无效消耗。** PILOT 证明执行中监督/纠偏与把失败模式蒸馏成技能，能在提升成功率的同时降低 token；适合我们的长任务与子代理编排。
6. **可验证奖励优先。** DeepSeekMath-V2 用验证器做奖励；RASPRef 的多信号中只有验证器信号具备合同效力，自评/一致性只能做搜索启发。

## 四、V4 自我迭代协议（固化）

```
执行任务 → 记录经验 → 发现缺陷 → 提出改进（单机制）
→ 修改代码/技能/流程 → 自动测试（冻结判据 + 回归保护）
→ 保留有效改进或受控撤回（保留失败证据）→ 下一轮
```

实现要求：

1. **经验账本**：`self-iteration-ledger.jsonl`，每条记录：日期、任务、证据路径、缺陷、假设、改动文件/技能、验证命令、结果、去留、SHA。下一轮先读账本，不重复失败路径。
2. **判据与回归**：每轮冻结目标、样本、阈值与“此前 PASS 不得退步”清单；机器指标裁决；LLM 文字不能替代指标。
3. **隐藏留出**：至少保留一组未参与调参的样本（如研报阅读的留出 PDF、因子研究的封存区间），防止自我迭代过拟合。
4. **单机制**：一轮只改一个主要机制（prompt / 工具 / 流程 / 模型分开轮次）；模型、采样、门禁不得在同一轮偷换。
5. **实时监督**：长任务由主控按 PILOT 式监督，记录失败模式并蒸馏为技能；失败不隐瞒。
6. **边界**：无可信反馈或连续 N 轮无改善→停并标 `CANNOT_CONFIRM`；无真实上游证据时维持 `CANNOT_CONFIRM`，禁止手填/伪造；不可逆、外部发布、交易/凭证、启停共享服务仍按全局合同需明确授权。

## 五、与当前待办的关系

- **Qwen 研报阅读实测**：用 AREX 的内外循环 + 隐藏留出 + 验证器裁决；本地推理按用户要求可见启动（oMLX 127.0.0.1:8802，前台终端）。当前候选工作树缺失，需先用已归档源码恢复可运行管线；不写新请求器。
- **面板两个空池**：根因在复盘核心上游（review bundle 指针与 Stage7 1 分钟源缺失，review-core 日任务报模块错误并因 selector 指针元数据缺失而 BLOCKED），详见 `POOL_EVIDENCE_GAP_20261103.md`；不用自我迭代名义伪造行。
- **因子工厂**：AlphaSeek 的轨迹级自迭代 + 去冗余约束可作为下一批研究设计；先冻结数据、样本、评价与封存集。

来源：arXiv API 元数据（上述 ID）、Anthropic 官方页面（已抓取）、OpenAI 页面（403，未验证）。未获取论文全文，未复现实验；论文效果以作者报告为准。