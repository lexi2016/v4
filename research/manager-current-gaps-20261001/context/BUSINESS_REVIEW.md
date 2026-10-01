# V4 业务数据完整性与普通 API/UI 消费审查（2026-09-30）

## 结论

本轮在已修候选之上确认了三组仍需修正的静态源码缺陷：

1. **P1：Eastmoney 多版本正文的后端身份与前端唯一性合同冲突**，合法历史合并后可能使整个普通工作台响应无法渲染
2. **P1：US 映射的新后端证据形状与普通前端合同不一致**，真正出现有效映射时仍会被前端整页拒绝；至少有两个独立必然拒绝条件，另有长期关系／镜像时间分支不兼容
3. **P2：Stage 不可变文件先写、latest 后写，但缺少中断恢复协议**，一次最终指针写失败即可使同一输入的正常重试持续失败

另发现 **P2 待目标字节核对**：新 SCHEDULED_MORNING 计划与旧历史 reader 的 execution_kind 白名单不兼容。

以上是固定源码的逻辑审查，**没有执行测试、故障注入、真实 provider、HTTP 或浏览器复现**。没有修改应用源码、状态、release、配置或数据，也没有做部署。本稿中的“确认”只指静态调用链与条件分支已明确；不意味着已证明 Mac 活动服务正在运行这些字节。

## 审查基线和边界

- 冻结源码：[`bdc95a3f9d6d0313baeff2bf727ea82d122dc820`](https://github.com/lexi2016/v4/commit/bdc95a3f9d6d0313baeff2bf727ea82d122dc820)，已读完整 source_inventory、两份 CHAT_START_HERE、README 及前像选择约束
- Stage：[`84264c47a99d464d174b8180375c8701883b2bb5`](https://github.com/lexi2016/v4/commit/84264c47a99d464d174b8180375c8701883b2bb5) 的 R4＋digest 候选，审了新 slot_execution、runner_receipts 及所调用的原 RawStore／SelectionStore／consumer 路径
- Manager：[`95426ac3db39f6d86ec2031617c4ac180d40868e`](https://github.com/lexi2016/v4/commit/95426ac3db39f6d86ec2031617c4ac180d40868e) 的 final_business 候选；已读方案、SOURCE_PINS、实际补丁和关键后像
- Manager US 证据映射：R9 candidate `research_evidence.py` 的 SHA256 `6a0075aeba1ec68c14ee5ec09f0290c6bbcd49e296fe76fa3ae17a03510c6ec2`，属于 final SOURCE_PINS 明确保留的 API6726 依赖，原件在 `4c1e2de72ef8a026aa5229caca6e4a5e98b17e36`
- API6726 workspace 通过 R3B 前像和 `53d5558d0ead78b965d2024654c8fa9253fa222d` 所带 integration_actual_diff 静态检查；没有把 bdc 旧 workspace 当作 API6726 最终后像
- 普通前端与未改观察投影使用 bdc 冻结源码；95426 的十文件后像未修这条跨端协议。最终 inactive 组合仍需确认这些原文件的 SHA 与实际装配一致

## BI-01 / P1：合法公告历史在普通 UI 中被判重，整个工作台读取失败

### 触发与实际影响

同日两个 committed Eastmoney run，各自原始 listing/content/PDF/observation 校验通过，且在 consumer cutoff 前：

- 同一发行人、同一 art_code 的正文发生修订，body_sha256 不同；或
- 同一 art_code 合法涉及多个发行人

B1 的新历史逻辑故意保留这些不同实例，但投影的 event_id 仍只有 source＋art_code。前端将第二个实例判为重复，抛 `EASTMONEY_HK_DOCUMENT_IDENTITY_INVALID`。这是“后端保存成功、普通 API 返回可用数据、前端拒绝整份 workspace”的用户效果，不是单个审计区显示少一行。

### 固定源码证据与过滤核对

1. 新历史以 `(symbol, art_code, body_sha256)` 去重，因此不同正文或发行人仍保留：
   [`95426 / eastmoney_run_history.py L247-L253`](https://github.com/lexi2016/v4/blob/95426ac3db39f6d86ec2031617c4ac180d40868e/research/manager-r9-consumer-r1-20260930/final_business_20260930/after/app/v4/manager_research/eastmoney_run_history.py#L247-L253)
2. 新普通 read 直接取全部 history documents，没有随后挑单一最新版本：
   [`95426 / workspace_announcements.py L583-L591`](https://github.com/lexi2016/v4/blob/95426ac3db39f6d86ec2031617c4ac180d40868e/research/manager-r9-consumer-r1-20260930/final_business_20260930/after/app/v4/manager_research/workspace_announcements.py#L583-L591)
3. event_id 的定义仍为 `digest(['EASTMONEY_HK', row['art_code']])`；issuer、正文 SHA 均未参加：
   [`95426 / workspace_announcements.py L620-L650`](https://github.com/lexi2016/v4/blob/95426ac3db39f6d86ec2031617c4ac180d40868e/research/manager-r9-consumer-r1-20260930/final_business_20260930/after/app/v4/manager_research/workspace_announcements.py#L620-L650)
4. `event_lane` 只按原身份、displayed、available、cutoff 过滤，逐条 append，并不去重或挑最新；满足这些条件的两版会一起进入 ordinary workspace：
   [`bdc / announcement_observation.py L47-L76`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/v4/manager_research/announcement_observation.py#L47-L76)
5. 普通前端要求 Eastmoney 文档 event_id 全局唯一：
   [`bdc / managerWorkspace.ts L251-L268`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/apps/web/src/api/managerWorkspace.ts#L251-L268)
6. 整个 workspace 在入口调用此校验，没有公告分区级隔离：
   [`managerWorkspace.ts L731-L734`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/apps/web/src/api/managerWorkspace.ts#L731-L734)、[`L838-L854`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/apps/web/src/api/managerWorkspace.ts#L838-L854)

### 最小修复

- 统一“文档实例”身份为 source＋issuer＋art_code＋body_sha256，并贯通文档、材料、关联引用和 DOM key
- 单独保留 art_code 级 logical_event_id 作为事件聚合标识，不用它承担正文实例唯一性
- 如果业务只展示一个当前正文版本，应明确定义“当前版本＋历史版本列表”投影合同，并保留各自原文、来源、取得时间和拒因；不能为通过前端校验删除旧批材料
- 保留实例唯一性校验，不把任意重复都放行

### 验收场景

1. 原 Store 连续提交相同 issuer/art_code、不同正文 SHA 的两批，普通 GET → 真实 TS validator → 原页面均通过；两版各自原文可查
2. 相同正文重复采集，只保留一个文档实例并聚合 capture occurrences
3. 同 art_code、不同 issuer 保持隔离
4. 历史 cutoff 只接受当时已取得的版本，不借用后版取得时钟
5. 相同实例 ID 的无依据重复、改正文却未改 SHA 等异常仍拒绝

**状态：静态组合确认；未执行复现；未确认已部署。**

## BI-02 / P1：US 映射后端已能产出，普通前端仍拒绝新合同

这是一组 producer／consumer 合同不一致，不按每个条件拆成多个独立缺陷凑数。只修其中一个条件不足以完成。

### A. 所有成功 US 关联的可读解释数组与前端枚举合同冲突

后端研究卡片遇到 US 行业或个股关联时，追加“美股关联原文方向…”到 `decision.why_now_readable`：

- [`bdc / research_attention.py L180-L197`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/v4/manager_research/research_attention.py#L180-L197)

前端却要求该数组严格等于固定 qualified_lanes 的标签数组，不允许这项合法补充说明：

- [`bdc / managerWorkspace.ts L639-L650`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/apps/web/src/api/managerWorkspace.ts#L639-L650)
- 进入证据状态排序分支后必调用此校验：[`L654-L699`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/apps/web/src/api/managerWorkspace.ts#L654-L699)

因此，在当前默认 evidence-state 卡片协议下，只要有一个成功映射就可能抛 `WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID`；没有映射的空例不会暴露问题。

### B. 成功个股关联的派生对象没有前端必需的 semantic_status

新 native material relation 在 `_card_errors` 已核入参 card 的 semantic_status，构造关系对象时却没有带入或重新标注这个字段：

- [`95426 / issuer_us_relations.py L195-L237`](https://github.com/lexi2016/v4/blob/95426ac3db39f6d86ec2031617c4ac180d40868e/research/manager-r9-consumer-r1-20260930/final_business_20260930/after/app/v4/manager_research/issuer_us_relations.py#L195-L237)

目标组合明确保留的原 R9 mapper 原样 deepcopy 到 hk_relation，未补字段：

- [`4c1e2de / candidate/research_evidence.py L376-L401`](https://github.com/lexi2016/v4/blob/4c1e2de72ef8a026aa5229caca6e4a5e98b17e36/research/manager-r9-consumer-r1-20260930/candidate/v4/manager_research/research_evidence.py#L376-L401)
- 所有执行映射均来自这一路 native parser：[`L492-L499`](https://github.com/lexi2016/v4/blob/4c1e2de72ef8a026aa5229caca6e4a5e98b17e36/research/manager-r9-consumer-r1-20260930/candidate/v4/manager_research/research_evidence.py#L492-L499)

前端的个股映射校验要求 `relation.semantic_status === 'ACCEPTED'`：

- [`bdc / managerWorkspace.ts L527-L539`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/apps/web/src/api/managerWorkspace.ts#L527-L539)
- 任一 lane evidence 不合法就抛错：[`L542-L563`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/apps/web/src/api/managerWorkspace.ts#L542-L563)

所以即使移走上述解释追加，成功个股映射仍会被拒绝。

### C. 长期关系与镜像公告的时间语义仍按旧短窗口验证

后端明确支持严格绑定的 `STANDING_RELATION_NOT_NEW_CATALYST`，并为镜像原文提供 issuer_time_basis／issuer_mirror_observed_at，保留“不知道官方首次发布时间”的边界：

- [`95426 / issuer_us_relations.py L143-L184`](https://github.com/lexi2016/v4/blob/95426ac3db39f6d86ec2031617c4ac180d40868e/research/manager-r9-consumer-r1-20260930/final_business_20260930/after/app/v4/manager_research/issuer_us_relations.py#L143-L184)
- 输出时间字段与 standing_validity：[`L220-L237`](https://github.com/lexi2016/v4/blob/95426ac3db39f6d86ec2031617c4ac180d40868e/research/manager-r9-consumer-r1-20260930/final_business_20260930/after/app/v4/manager_research/issuer_us_relations.py#L220-L237)

旧前端则要求关系 publication 和全部 acquisition 都处于当前 start–cutoff 短窗口，未按 standing validity 或 mirror observation 分支：

- [`bdc / managerWorkspace.ts L496-L509`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/apps/web/src/api/managerWorkspace.ts#L496-L509)
- [`L527-L539`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/apps/web/src/api/managerWorkspace.ts#L527-L539)

这意味着合法旧关系也会被拒绝；没有 published_at 的合规镜像时间语义同样不适配。修 A/B 后还必须分别验这些分支。

### 最小修复

1. 明确 US 关系 v2 响应合同：native issuer／source span／two-source lineage／资格／current 或 standing 时间角色，前后端同一结构
2. 派生关系只在原验证完成后携带明确的 semantic admission 状态，不让上游任意 claim 字段提权
3. 将固定 lane labels 与自由说明分字段；例如保持 `why_now_readable` 的既有严格标签合同，把方向／风险解释放入独立字段，并由原 UI 展示
4. 时间校验按 current-publication、mirror-observed、standing-validity 分支，继续严格核 cutoff、取得时钟、原文与来源绑定，不改为“有一个日期就放行”
5. 对一个映射分区的局部问题应保留其它有效工作台内容并显式标出该分区失败；整体安全／身份损坏仍应拒绝

### 验收场景

- 一个真实形状的当前 US 个股正例，一个当前行业正例，都经过原 backend formatter、普通 GET、真实 TS validator、原页面；不得只测 Python relation 函数
- 同样 shape 的零映射负例，保留 raw movers 和逐项拒因
- 简体与繁体原文、明确 ticker、无 ticker、否定主体、错发行人分别验
- 合法长期关系：有效期内可作为旧关联展示，不标新催化；过期／未核 source span／after-cutoff 仍拒绝
- 合规镜像：不伪造 published_at，明确镜像时间 basis
- 补充解释可见，固定 lane 标签和排序强度保持一致

**状态：固定组合中的静态逻辑确认；尚未执行普通 UI 复现，最终装配 SHA 仍需核。**

## BI-03 / P2：Stage 的完整不可变产物可因一次 latest 写失败而被正常重试永久绕过

### 触发与影响

同一输入发布中断在最终目录已建立之后、latest 指针提交之前。典型情况是 artifact／manifest／receipt 已写完，而 latest 的临时文件、fsync、rename 失败；也可能更早中断只留下部分 trio。

重试重新计算得到同一 run_id，发现不可变目录已存在便拒绝。完整且可校验的数据留在磁盘，却不能由正常重试恢复为可消费状态。有限补跑预算可能因此耗尽。这里不宣称数据字节被删除，问题是**已写产物无法通过既有自动恢复路径重新接通**。

### 固定源码证据

- RawStore 先创建最终不可变目录，目录已存在就拒绝：[`bdc / transaction_publish.py L53-L73`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/stage_center/_raw_store_parts/transaction_publish.py#L53-L73)
- RawStore 在三个文件写完和校验之后才更新 latest：[`L129-L156`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/stage_center/_raw_store_parts/transaction_publish.py#L129-L156)
- SelectionStore 同构：[`store_publication.py L83-L100`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/stage_center/_selection_parts/store_publication.py#L83-L100)、[`L140-L159`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/stage_center/_selection_parts/store_publication.py#L140-L159)
- bundle 的 receipt 已存在而无 latest 时同样拒绝：[`transaction_publish.py L201-L218`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/stage_center/_raw_store_parts/transaction_publish.py#L201-L218)
- Runner 只从 latest／selection_latest／bundle_latest 判断存在，缺指针的完整 run 不会被发现：[`slot_idempotency.py L19-L27`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/stage_center/_runner_parts/slot_idempotency.py#L19-L27)
- R4 仍沿原 publish 入口；bundle fallback 只处理 `bundle slot conflict`，不处理“已存在但无 latest”的孤儿：[`84264 / slot_execution.py L591-L645`](https://github.com/lexi2016/v4/blob/84264c47a99d464d174b8180375c8701883b2bb5/research/stage-ah-execution-r4-20260930/after/stage_center/_runner_parts/slot_execution.py#L591-L645)、[`L660-L695`](https://github.com/lexi2016/v4/blob/84264c47a99d464d174b8180375c8701883b2bb5/research/stage-ah-execution-r4-20260930/after/stage_center/_runner_parts/slot_execution.py#L660-L695)

### 最小修复

- under 原 store lock，实现明确的发布恢复协议
- 对完整 orphan trio：按请求的日期、stage、market、输入身份、算法、全部文件 SHA、safety 和完整 envelope 校验完全一致后，只补提交该 key 的 latest；不能重采样、换身份或覆盖兄弟市场
- 对部分 orphan：用 staging 目录＋完整提交标记区分未提交文件；恢复规则显式、可审计。不能“目录存在就信任”，也不能清整个 store 或重置次数
- latest 的更新继续 merge 原 entries，保留未执行市场
- RawStore、SelectionStore、bundle 三处使用一致的恢复原则

### 验收场景

分别在 artifact 写后、manifest 写后、receipt 写后、latest rename 前注入一次 I/O 失败或进程中断，再以相同输入重试：

1. 完整 orphan 可校验重接，run_id／文件 bytes 不变
2. 部分 orphan 不被当作有效输入；按协议恢复，最终可重试
3. 同 run_id 下内容不同、SHA 错误或跨日期／market 的 orphan 必须拒绝
4. 任意失败和重试后，A/HK 未执行一侧的 immutable 文件、latest entry、原结果不变
5. 共享尝试数不清零，不绕过过期截止；存储恢复不等于新采集授权

**状态：静态确认；未执行故障注入。R4已有“异常后A保全”不能替代“失败市场随后恢复成功”。**

## BI-04 / P2 待组合核对：morning 计划能保存，但历史 reader 不接受其 execution_kind

### 证据与边界

API6726 集成补丁让 `validate_attempt`、`_read_plan`、`refresh_workspace_plan` 接受并写入 `SCHEDULED_MORNING`：

- [`53d5558 / integration_actual_diff.patch`](https://github.com/lexi2016/v4/blob/53d5558d0ead78b965d2024654c8fa9253fa222d/research/manager-r9-consumer-r1-20260930/api6726_business_combo_20260930/evidence/integration_actual_diff.patch)

bdc 历史 reader 的 `_read_candidate` 却只允许 MANUAL_REFRESH／SCHEDULED_PREOPEN：

- [`workspace_history.py L55-L65`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/v4/manager_research/workspace_history.py#L55-L65)
- `select_plan` 先读取 latest，没有按不支持种类局部跳过再找合格旧 run：[`L92-L99`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/v4/manager_research/workspace_history.py#L92-L99)
- 错误最终被转成历史 SOURCE_FAILED：[`L232-L234`](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/v4/manager_research/workspace_history.py#L232-L234)

**若最终 API 组合仍带此历史 reader**，某日只有成功 morning 计划而没有成功后续 preopen 替换，次日普通 auto 历史读取会拒绝它。若目录内扫描碰到该种类，也可能使整次候选搜索失败。不能声称 Mac 已触发：workspace_history 并不在 API11 或 95426 明确写集合，最终实物尚需核。

### 修复与验收

- 先核最终 workspace_history SHA，若与此固定源码相同，再统一 writer／current-reader／historical-reader 的 execution-kind 合同
- morning 产品仍需完整 source/PIT/frozen-business 校验，不能仅放宽枚举便算历史成功
- 验 morning-only 次日 auto/history；morning＋preopen；后来的动态手动产品不遮蔽合法 pre-session 产品；不合格未知种类仍拒绝并保留明确拒因

## 已修候选与本次不重复计数的事项

- A205 code digest 修正已有新候选，不再报算法问题
- Stage R4 共享预算、市场 scope 和未执行市场保全已有实装候选；本稿 BI-03 针对更底层 publish 中断后的可恢复性，不否定其已有保全证据
- Eastmoney 首三家续扫、同日 committed 多批合并、原 MaterialStore observation 保留，已有 95426 复用 B1 方案；BI-01 是这次历史保留与普通前端的新交互
- B2 采集前计划提前 return、缺少原 scheduled-cycle 接收路由、排队旧时钟、POST 后计划刷新，95426 已改，不当新缺陷重报
- US 原取得时钟／ticker／source_refs 从 topic 到 archive 的字段投影已有 95426 修复；BI-02 是其成功业务路径的前端合同未同步
- R3A 资格供给未闭环属于已知独立业务缺口，不借此替代上述具体源码审查
- A1445 source/archive 字段差异、HK D1/cutoff、真实完整 SourceResult、同日自然运行与 ordinary API/UI 仍需各自目标输入证据；本次未将其推断成已定位新 bug

## 建议修复次序

1. 先将 BI-01、BI-02 加入同一 Manager inactive 候选，做到“真实后端输出 → 普通 API → 真实 TS validator → 原页面”的正例；不能只新增 helper 测试
2. 独立修 BI-03 的原 store 恢复协议，并与 R4 scope／预算／跨市场保全一起故障注入
3. 核 BI-04 最终 reader 字节，成立则修 writer/reader 合同并补次日历史场景
4. 再合并既有 R3A 最终资格 owner 产物，按真实输入验 qualification → 材料 → US 关系 → 计划 → ordinary UI；不要重跑未变全量测试来掩盖缺失的交互路径
5. 目标组合独立复核及原构建器身份核对后，部署和自然运行按独立授权继续

## 覆盖与未覆盖

本轮实读：RawStore 和 SelectionStore 的发布／校验／幂等／consumer，R4 scope 发布调用；Manager committed history、公告 read/project/event_lane、US 原材料关系提取及保留 mapper、普通 workspace TypeScript 验证、历史计划选择器、最新修复包的字段透传与 RPC 差异。

未覆盖：全部 680 文件逐文件审计、所有实际 UI 页面／错误处理分支、所有评分算法数值回归、真实行情、真实公告来源可用性、R3A 未上传最终字节、完整 API6726 app 装配、Mac 实际加载路径、解释器与调度版本、真实 HTTP／浏览器、当前日期资格、真实自然时段。部署／runtime 映射另审，不在本稿重复。

本稿不能当全 V4 验收通过单。它是一批已有固定证据、可直接进入修复和定向验收的业务审查结果。

