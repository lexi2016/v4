请接手 V4 经理研究页的问题定位、最小修复方案与实际代码交付。本地主控负责之后应用补丁、Luna Max 独立复跑、API/UI 验收和反馈。请先读本包 README、evidence/current_audit.md、evidence/api-summary.json、SOURCE_INDEX.json，再读 source/ 中真实源码和 configured_release_reference/ 中现役差异。不要只返回方案后等待。

仓库：lexi2016/v4；交接分支：codex/manager-current-gaps-20261001；目录：research/manager-current-gaps-20261001/。关联 Issue8/17、draft PR18；已有 PR18 不能当本机已修复。交接是聚焦源码快照，source/ 不是旧 main 的运行代码，也不是完整安装包；缺具体依赖时点名文件，不假设存在。

当前页面：http://127.0.0.1:8873/manager-selection/?date=20260925&plan_date=20261002。当前配置 release 仍为 r4-stage-merged-c3e535…，而 US mapping 候选未激活。

当前实证：
1. BI01：Eastmoney event_id 只按 source+art_code，跨 issuer/正文实例会冲突；TS 全页 validator 要求唯一。PR18 尚未在本机合入验收。
2. BI02：后端向 why_now_readable 追加方向文字，前端只接受固定 lane 标签；native hk_relation 缺 semantic_status 但前端要求 ACCEPTED；standing/mirror 被短材料时间窗处理。必须以真实 schema 修复，不凭空添加 STANDING_RELATION/version。
3. 0 映射的直接输入断点：2016 条材料→16 个 issuer/67 张候选卡→目标日 HK Connect V2 artifact 缺失→67 张全部被 membership gate 过滤→source_material_card_count=0。US 行情33/33、24 proxies、mapping_eligible=true，PARTIAL 不是唯一原因。
4. HKEX 15/696、681 未查、10 文档/7解析/3失败；Eastmoney 当前 NOT_RUN，历史窗口外文档另计。反弹689待核，典型60日只有59；9个日线地址诊断无样本。
5. US 候选 manifest 的 base_release_id 自指、独立最终 reviewer PENDING；旧 fixtures 未闭环；计划 STALE_INPUTS_CHANGED。BI04 reader 白名单不含 SCHEDULED_MORNING，真实 writer-reader 组合仍需确认。

请先按“代码 bug / 数据前置条件 / 候选集成 / 当前时段状态”给简洁问题清单和 owner，然后第一批只处理 BI01/BI02，核实 BI04。冻结允许路径、唯一 Writer、失败复现与 PASS_SIGNAL。复用现有生产路径，不造第二 producer。BI01 必须真实 Python 多 issuer/多正文输出→实际 TS parser→DOM 多实例验证；同实例稳定去重、异实例不合并。BI02 必须真实 native 与 standing/mirror 正例 Python→TS 验证，同时保留不足双来源、PIT、过期关系负例。对不完整成员表/材料/日线单列后续批次，不降门槛制造非零。

交付真实 patch 或分支/commit、变更清单、before/after SHA、测试命令和 stdout、独立 review 状态；不能执行就明确 NOT_RUN/CANNOT_CONFIRM，仍给可落地最小补丁，不伪造测试或部署。已有冻结候选不得原地改写。

日历暂不改；不改 A 股阶段、BUY、Vibe8910、服务/调度/冻结release；保持 RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。本地后续按收到代码的实际行为验收，Issue8/17 暂不关闭。
