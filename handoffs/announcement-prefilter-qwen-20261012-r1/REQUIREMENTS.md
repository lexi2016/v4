# 实施需求：V4 公告脚本初筛 + 本地 Qwen3.8

## 目标和边界

为 V4 现有公告链加入确定性脚本初筛，降低模型 token 消耗，同时完整召回重大或不确定公告。确定性脚本只做路由和有证据的例行项判定；重大事件及不确定项由已验证身份的本地 Qwen3.8 阅读原公告正文，再由现有完整语义校验、显式决策、owner 导入/readback 和工作台消费链闭环。

复用现有完整正文采集链，不另建公告 producer、不用标题 TopN 截断完整目录、不新增轮询定时器、不由人工每天读完全文。A/HK 市场、来源、日期、既有 owner 与交易安全门禁保持独立；公告中的投资风险研究不得自动转成买入。不得改变 HK D-1 池定义。

## 冻结验证输入与日期身份

首个实际验收样本固定为 target trade date `20261012`，publication date `2026-10-11`，evidence run `6557712adca825b670f28c5169655db1`。本地语料有 23 条公告目录记录：21 条 `COMPLETE_CONTENT_API_BODY`，2 条 `BODY_CAPTURE_FAILED`；当前 `semantic_status=NOT_REVIEWED`，`live_import=NOT_RUN`，`live_api_ui=NOT_VERIFIED`，`natural_run=NOT_VERIFIED`。这些是验收输入事实，不是分析效果。

每个 capture、脚本路由、正文分析、product、owner import、API readback 和 workspace 消费都必须绑定相同的 `target_trade_date=20261012` 与 `publication_date=2026-10-11`，并保留 catalog run/SHA、source identity、body SHA、owner 与 `available_at`。不得静默回退到先前 HK publication `pub09` 或其他日期。日期/市场/issuer/art_code/SHA 不一致、缺失或冲突时，整条记录为 `CANNOT_CONFIRM`/`NOT_ASSESSED` 并保留原因，不得补写成成功。

对完整权威目录逐条核验来源、市场、公告日期、发行人、`art_code` 和内容 SHA。以市场+publication date+`art_code` 做去重候选；重复记录仅在 issuer/source identity 与内容 SHA 一致时折叠。相同 `art_code` 映射到不同发行人或不同正文 SHA 时隔离并报告冲突。输出必须覆盖完整目录，给出逐条去向和未覆盖项；禁止静默分页遗漏、TopN 截断、把缺正文算成零条或低价值。

## 确定性脚本路由

先对目录与原始正文做规则化检查，再决定是否调用模型。只允许在规则充分明确、正文完整且所有重大例外检查均通过时，把某条公告标为 `SKIPPED_ROUTINE`。每个此类结果必须携带规则 ID/版本、命中证据、异常检查结果、输入 SHA 和日期/发行人身份。它表示“脚本依据规则跳过模型”，不表示“AI 已阅读”或“语义已验证”。要作为完整集的一部分导入现有 owner，必须扩展/兼容语义合同，让完整目录的每条记录都有可审计处置，同时不绕过现有完整 semantic gate。

业绩预告、盈利警告、并购重组、重大合同、融资/担保、诉讼仲裁、监管风险等优先送模型，但类别命中只决定路由，不代表利好、有效选股或买入。标题含糊、混合事件、未知类别、新模板、来源冲突、金额/日期异常、正文与标题不符、正文无法充分解析、例行公告出现重要数字/异常条款，一律送模型或保留未评估。规则必须覆盖全文可检查的数字、主体、金额单位、变更/生效状态、限制性条款等例外；若脚本无法排除重大例外就不得 `SKIPPED_ROUTINE`。

正文抓取失败、截断或校验失败必须是 `NOT_ASSESSED` 并说明原因，不得交给脚本静默归为例行，也不得标成模型已读。对于无法送达模型的高价值候选，仍为未评估，不能被删除或下游当作零。

## 本地 Qwen 与语义正确性

仅允许调用已确认运行在本机的 Qwen3.8；禁止云端/付费 fallback。配置 alias、API model 字段和权重身份分开记录。首次运行与每次模型版本变化时验证实际服务进程、权重名称、revision/commit、配置 SHA、服务实现和本机 endpoint；统一以 `modelname + revision + configSHA` 作为已验证模型身份。若只看到 alias 或配置标签、无法确认实际权重，则 `CANNOT_CONFIRM`，不可把输出归为 Qwen3.8。

已有 canary 显示 alias `claude-sonnet-4-6`，而本地标签为 `mlx-community/Qwen3.8-27B-8bit`、config `model_type=qwen3_5`。这只作为身份冲突线索，不能作为实际 Qwen3.8 运行证明；新实现要在第一次调用前核验并记录真实模型身份。

模型必须基于正文逐条提取可追溯事实和原文短引，核对发行人/主体关系、数字与单位、公告对象、日期、条件、未偿/已偿、计划/已完成等状态；每个事实关联正文位置或来源片段 SHA。JSON 可解析、HTTP 200、模型自报正确均不等于语义正确。保留已有反例回归：邦泰跃尚的公告源主体是独立第三方，旧分析曾误写为联营公司；另将“未偿本金”误判为“已完成”。主体、数字、单位、时间状态或引文校验失败时不得标成成功，须返回可审计失败/未评估状态。

## Cache、并发和 token 账本

语义 cache key 至少包含 issuer、`art_code`、body SHA、parser 版本、规则版本、prompt 版本、schema 版本以及已验证模型身份。不要按 target date 重复阅读未变正文；cache 命中后仍须为当前目标日期重新绑定 cutoff、owner、`available_at`、输入身份及 readback 证据，不能把未来看到的材料倒填为历史 PIT 证据。

并发相同 key 使用 singleflight/互斥；结果原子写入，等待者复用同一成功结果。正文 SHA、规则、prompt、schema 或模型身份变化时只失效对应条目。失败、超时、截断、JSON 无效、语义验证失败、模型身份不明都不能缓存为成功。重试次数有界；refresh、页面读、审查或人工触发不得每次都重跑模型或伪造 reviewer PASS。

逐次记录 provider 实际返回的 `prompt_tokens`、`completion_tokens`、`total_tokens`、`cached_tokens`、`reasoning_tokens`、模型身份、request/cache 状态、成功/失败和耗时；失败尝试消耗的 token 也计入总量。保留 provider 对字段是否互相包含的说明，聚合时不重复相加。usage 缺字段就记 `NOT_REPORTED`，本地 tokenizer 推算只能放在单独 `estimated` 字段；禁止将缺失填成 0。零新模型调用应报告零新增模型 token。相同输入首次运行后并发/二次运行应无新调用并复用同一结果；只改变一个正文 SHA 时只让这一条重新判读。

全量 AI 基线仅复用既有实际 usage receipt，或用精确本地 tokenizer/同 prompt 的离线估算并显式标 `ESTIMATED`；不得额外调用模型制造 baseline 消耗。分别报告质量、目录覆盖、AI 调用次数、实际/估算 token、延迟、cache 命中、失败数和 owner readback 状态。

## 每日链和现有 owner

目标流程为：完整目录/正文 capture → 确定性脚本路由 → 本地 Qwen 或语义 cache → 原完整语义校验及显式逐条处置 → 原公告 owner import → 同日期 API/workspace readback → 既有 daily plan 消费。把调用接到经源码和运行 receipt 确认的现有 heartbeat/scheduler 入口，复用原触发、binding、锁和失败隔离，不新增第二个 producer、后台 timer 或独立面板。

快照表明 V4 存在 announcement supervisor、cycle、`/workspace/scheduled-cycle` 与 owner dispatch 候选 hook；这不证明它们已由当前运行 scheduler 调用。旧的 manual-reader/人工读取流程只代表当前能力或历史状态，不等于每日自动读正文已完成。实施者必须以 scheduler/owner 的日期绑定执行 receipt、代码 SHA、真实 API import/readback 与自然时段结果验证连通。若 hook 当前不可达，保留 `CANNOT_CONFIRM` 并报告具体链路缺口，不另造 poll timer。

导入与页面消费继续经过原 owner 的完整集语义合同。`SKIPPED_ROUTINE` 必须以显式、带版本的脚本 judgment 扩展输入集；现有模型 review、决策、消费和来源校验不得被绕过。日期不一致时，不得把 target12/pub11 写到 pub09 或反向覆盖。A/HK 分离，HK D-1 pool、BUY gate 与模型门禁不变。

## 验收与报告

先由独立标注者在实际模型运行前，基于冻结完整目录和正文逐条标注重大事件、可安全跳过的例行事件、含重大例外的例行事件、未知/混合项及未评估项；在解封模型结果前冻结标注 SHA、召回分母和数值 PASS 阈值。小样本不能在阈值冻结前声称效果提升。对 23 条目录逐条 reconciliation；2 条正文失败仍保留在覆盖表中并计为未评估。

至少验证：

1. 正常重大公告被路由到 Qwen，确定性例行项只有在例外检查通过后才 `SKIPPED_ROUTINE`。
2. 含重大数字/异常条款的例行标题不会漏过脚本，模糊/混合/未知标题不会被跳过。
3. 正文失败、截断、日期错配、issuer/art_code/SHA 冲突分别保持失败/未评估且带原因。
4. 已知主体关系和未偿本金反例在语义回归中判对；对引用、主体、数字/单位和状态做逐项验证。
5. 相同输入并发与二次调用只产生一个首次模型调用，后续无新增调用/token；改变一个 body SHA 只失效该条。
6. 日常触发 receipt 证明走原 scheduler/heartbeat 与原 owner；API import、同日期 GET/readback、workspace result 和消费合同分别闭环。
7. 质量达到事前冻结的召回阈值，完整目录无静默遗漏；报告 precision/recall 或适合样本量的逐项结果，并分开列未评估数。
8. 报告实际 provider token usage 与 full-AI baseline 来源；缺失 usage/身份/自然运行证据继续标 `NOT_REPORTED`/`CANNOT_CONFIRM`，不能宣称节省比例或 NATURAL_VERIFIED。

`pub09` 的另一批 392 条仅可作为后续扩大验证集或趋势对照；本次无须为 baseline 对这批全文做全量模型调用。

## 输出和安全

保留逐条 route/disposition、rule/model 版本、输入 SHA、date pair、attempt usage、cache hit、失败原因、显式决策、owner import/readback receipt 和 daily trigger identity。模型输出只作研究证据，不直接改变 Stage/BUY 或证券池。

一直保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。实施代码、测试、部署、API/UI、自然执行是不同验收状态；手动 canary、历史回放、Writer 测试或 HTTP 200 不代表自然自动闭环。
