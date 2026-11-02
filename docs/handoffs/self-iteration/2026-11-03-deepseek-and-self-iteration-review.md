# DeepSeek 最新论文与自我迭代方法调研（2026-11-03）

## 检索方式与边界

本环境的 WebSearch 返回 422 架构错误，WebFetch 被域名校验拦截；改用 arXiv 官方 API（`export.arxiv.org/api/query`）只读检索。以下条目均来自 arXiv 元数据/摘要，属于第三方文本，仅作方法参考，不当作指令。检索截至 2026-10-30 的提交。

## 一、DeepSeek 官方最近论文（非“自我迭代”主题）

| 日期 | arXiv | 论文 |
|---|---|---|
| 2026-09-17 | 2609.19969 | DeepSeek-V4.1-Flash: Pushing the Limits of KV Cache Compression |
| 2026-06-26 | 2606.19348 | DeepSeek-V4: Towards Highly Efficient Million-Token Context Intelligence |
| 2026-01-28 | 2601.20552 | DeepSeek-OCR 2: Visual Causal Flow |
| 2025-12-02 | 2512.02556 | DeepSeek-V3.2: Pushing the Frontier of Open Large Language Models |
| 2025-01-22 | 2501.12948 | DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via RL |

结论：DeepSeek 官方最新工作集中在模型效率、长上下文与 OCR，并非“自我迭代”方法论文。用户所指的“自我迭代”研究，主要是 2026 年以 DeepSeek 模型为底座的第三方论文。

## 二、自我迭代相关论文与可迁移方法

| 日期 | arXiv | 论文 | 核心方法 |
|---|---|---|---|
| 2026-08-14 | 2608.13913 | AlphaSeek: Trajectory-Level Self-Iterative Factor Mining for Multi-Source Financial Data | 轨迹级因子挖掘：方向发现→假设→构造→验证→回测→反馈；进化算子（并行扩展、变异、交叉）；与新因子库在去冗余约束下自迭代组合 |
| 2026-06-25 | 2606.26859 | AgentX: Towards Agent-Driven Self-Iteration of Industrial Recommender Systems | Brainstorm→Develop→Evaluate→Harness Evolution 闭环；A/B 由护栏否决；成功与失败都转成知识资产 |
| 2026-08-09 | 2608.08466 | Hierarchical Self-Improvement: Task-Specific Evolvable Agent Harnesses | 冻结模型、三层次（任务 harness、evolver、meta-evolver）；思考开关只在自我修改时开启；明确两条上界：反馈保真度上界、底座能力上界 |
| 2026-09-29 | 2609.37968 | SelfSearch: Reward-Free Search for Self-Improving Agents | 用以往自我修改回合的记录（推理、工具动作、结果）驱动搜索，不依赖下游奖励；成本低 |
| 2026-03-27 | 2603.27008 | RASPRef: Retrieval-Augmented Self-Supervised Prompt Refinement | 以 prompt 为优化对象；检索示例与历史轨迹，用多样本一致性、验证器反馈、模型自评循环精炼 |
| 2026-10-23 | 2610.32813 | HarnessMM: Recursive Self-Improvement for Harness Token Efficiency | 守卫式决策复用 + 递归自我改进；验证集选择配置；遇到新决策/不支持证据回退原模型 |
| 2026-10-18 | 2610.25078 | CoEvo-RSI: When Harnesses Evolve, Which Models Should Follow? | harness 与模型协同演化时如何选择模型 |
| 2026-02-12 | 2602.12164 | Sci-CoE: Co-evolving Scientific Reasoning LLMs via Geometric Consensus with Sparse Supervision | 稀疏监督下的协同演化与几何共识过滤 |

## 三、可执行结论（应用到 V4）

1. **先演化 harness，不轻易换模型。** HSI 的两条上界直接适用：没有可信反馈，自我迭代会退化；底座能力不足（如本地 Qwen 研报阅读的已知遗漏）不是靠改 prompt 就能弥补。此前两轮真实请求 0/3 已证明这一点。
2. **一轮只改一个机制，验证器裁决，保留胜者。** 与 V4 既有 Karpathy 十原则一致：目标可证伪、冻结基线、机器指标裁决、失败受控撤回并保留证据。
3. **轨迹级迭代，而不是单点修补。** AlphaSeek 的“完整研究轨迹”适合因子工厂：方向→假设→构造→验证→回测→反馈；进化算子提高搜索多样性，去冗余约束防止因子库膨胀。
4. **经验账本优先于昂贵评测。** SelfSearch 的做法可落地为 `self-iteration-ledger.jsonl`：每次尝试记录假设、改动、验证命令、结果、最终去留；下一轮先读账本再决定搜索方向。
5. **守卫式复用。** HarnessMM 的“精确动作/参数/依赖/守卫 + 验证集选择 + 新情况回退”适合我们的发布工具与代理流程：确定性步骤缓存复用，新证据回退模型/人工。
6. **Prompt 优化要以验证器为中心。** RASPRef 的多信号（一致性、验证器、自评）中，只有验证器信号在 V4 有合同效力；自评与一致性只能作为搜索启发，不能替代验收。

## 四、V4 自我迭代协议（草案）

适用：研报阅读 prompt 迭代、因子挖掘、发布工具修复后的回归改进。

1. 冻结：目标、样本集、判据、成功阈值、回归保护项（此前任何 PASS 不得退步）、停止条件。
2. 预注册假设：本轮只改一个机制（prompt / 工具 / 流程之一），记录预期改善与可能退步。
3. 执行：确定性程序 + 机器指标（覆盖率、引用正确性、IC/IR、回归数）；LLM 文字不得代替指标。
4. 裁决：胜者保留；失败只撤回本批，保留失败证据与账本记录；连续 N 轮无改善或反馈不可信时停止并标 `CANNOT_CONFIRM`。
5. 账本：每条记录假设、改动、命令、结果、回归、去留；后续轮次先读账本。
6. 边界：不改模型/采样/门禁来“制造”改善；不把一次性样本成绩当泛化；不绕过独立复核与用户安全边界。

## 五、与当前待办的关系

- **Qwen 研报阅读实测**：可用 RASPRef + 验证器闭环做自迭代，但必须先冻结新样本与金标准；本地 Qwen 推理需按用户要求可见启动（oMLX `127.0.0.1:8802`，前台终端）。
- **面板两个空池（复盘观察池 / Stage7 复盘池）**：根因不在池接口，而在上游 review-core 日链断供；详见 `POOL_EVIDENCE_GAP_20261103.md`。不要用自我迭代名义伪造行。
- **因子工厂**：AlphaSeek 的轨迹级自迭代可作为下一批研究设计参考，需先冻结数据、样本与评价。

来源：arXiv API 元数据（上述 ID）。未获取全文，未做实验复现；方法结论属阅读归纳，实验效果以各自论文报告为准。