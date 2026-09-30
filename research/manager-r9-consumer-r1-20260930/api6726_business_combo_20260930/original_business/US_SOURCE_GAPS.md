# 美股映射：源码支持范围、实际供给缺口、当前可完成修复

## 固定消费代码实际要求

业务前像 `4c1e2de...` 的 issuer_us_relations.py：
- `_anchored` 要求本股 symbol/action_subject、一致原文 source_field/start/end/quote、AFFIRMED。只含公司名或同一行业标签不够。
- `extract_issuer_business_relations` 在已接受 action_quote 内提取原有 20 类 business taxonomy；或关系动词 + 明确 US.X / NASDAQ:X / NYSE:X / $X。原行的 related_us_symbols/us_symbols/us_symbol 只在同一动作原文也出现该 literal ticker 时辅助，不从“礼来”推导 LLY。
- `_card_errors` 要求原生发行人身份和 verified refs；真实 retrieved_at、available_at 及 publication/mirror 时间顺序均可核且不越 cutoff。first_seen_at/collected_at/archive_recorded_at 只是额外检查，不能替代取得时间。
- `material_us_relations` 重新从原文提取，不信任可变缓存的关系标签；当前关系和 standing 分开，始终 `is_new_catalyst=false`。是否“当期催化”仍由别的原规则决定。
- research_evidence.py 的两源 join 另要求当期 US capture、独立 US payload/receipt/manifest 身份，不能把 issuer 文和 US 输入做成同一来源；raw mover 不映射也保留。

## 有明确代码依据的供给问题

1. **原文简繁体断层（本批已修）。** R1 原生分类器支持簽署、授權、許可等动作，但 `_BUSINESS` / `_RELATION` 第二层仍主要是简体；原来的 BIO/OIL 主题正则虽已有部分繁体，生物製藥產能仍可能因业务动词层漏掉。只加正交字形，不增加公司/beneficiary 列表，不改原文，不扩来源或时间准入。

2. **小时输入不是关系合同生产器。** 指定 8851... 的 `ops/collect_hourly_research_input.py::_zsxq_rows`（约263–392）读取 status.fetched_at / topic.create_time，输出 published_at、crawl_time、source_published_at、first_seen_at、last_checked_at、themes、raw_text、stock_code/name。该字面构造未输出 related_us_symbols/us_symbol、retrieved_at、available_at 或 business_relation_validity。`domains/research_hourly.py` 的 ResearchItem/StockResearchEvidence 使用 source_published_at/first_seen_at 等，并不是自动补齐本消费者需要的字段。这里只能断言这条指定源码路径，不能推断所有活动渠道都没有这些字段。

3. **消费侧保留不等于采集侧已产出。** `workspace_discovery.project_material_discovery` 保留 original_source_row 和原始时间；`existing_materials.project_archive` 从文章级字段读 retrieved_at/available_at，不把 archive 生成时间当取得时间。所查 8851... existing_materials.py 约23–69 同样如此。本地作者参考版本还保留无效字段原值和时钟诊断，但本批没有修改该模块，也不将此参考差异套到活动源。仅有 crawl_time/first_seen_at 的文章会继续拒绝，不能在缺少原字段定义/响应绑定时任意重命名。

4. **standing 路径在普通 archive 上还有结构限制，不只是缺几个字段。** `_standing_contract` 要求合同已经存在于 original_source_row.business_relation_validity，绑定 source payload SHA、全文/quote SHA、span、valid_from/valid_until/confirmed_at（最长366日），且 claim_status=SOURCE_STATEMENT。普通 project_archive 明确赋予 RESEARCH_OPINION，原分类器相应标 REPORTED_CLAIM，不能简单加一份合同就升级成源事实。该 archive projector 的 source_refs 只含整个 archive 的 binding，若把含合同自身的整个 archive SHA 又写入合同，会出现自引用绑定问题；需要独立原文来源及原 owner 的明确合同供给，不接受手填自证。以上是源码路径限制，不宣称全部其他渠道均不可实现 standing。

5. **镜像正文通路不生产长期合同。** R1 announcement_materials.mirror_material 的 source_row 仅含 body_text；正确保留镜像时间和实际 refs 的取得时间，published_at=None、HKEX 首发未知。正文明确写 ticker 的当期关系可进入原 extractor；公司名称联想、外部缓存 ticker 或镜像发布时间都不能替代明确关系/官方首发。

## 本批代码和验证

只改 issuer_us_relations.py 的两条正则与两行说明；实际旧源码在7个相关断言失败，修改后US 13项通过，含原 native parser → 原 relation join 正例、名称/metadata/否定句负例、取得时间缺失/越窗、旧关系无合同、原文span与时钟不变、raw mover保留。测试使用 QTEST 等合成 ticker，不是任何真实公司业务事实。

B1 同时使已存真实正文能够进入既有 material/card/selection 及此映射链；不会因只读 latest 而人为丢掉另一批关系材料。是否出现真实有效映射，仍取决于原输入。

## 一次现场补充，范围见 WORK_HANDOFF.md

只要当前 producer → 原 archive 转换入口的相关方法和一条文章原件/receipt、原字段时钟定义、可验证 ticker/业务 span。没有 standing 原合同或 09969/LLY 真正关系/取得时钟，明确 CANNOT_CONFIRM；不造样本、不把旧关系当新催化。B1/B2/字形修复不等待 F0。

参考不可变源码：
- 4c1e2de72ef8a026aa5229caca6e4a5e98b17e36 / research/manager-r9-consumer-r1-20260930/candidate/v4/manager_research/{issuer_us_relations.py,workspace_discovery.py,research_evidence.py,announcement_materials.py}
- 8851f7f84e3d506d3f1317eec03ba92c8f49e324 / {ops/collect_hourly_research_input.py,domains/research_hourly.py,v4/manager_research/existing_materials.py}
这些快照不是活动采集进程的等同性证明。
