# 工程与研究进展：2026-10-18及2026-10-19

版本：2026-10-19 13:25 北京时间。昨天指10月18日00:00–24:00；今天截至本报告读取时点。按项目与实际证据归类，不能将任务列表的completed等同产品验收，也不能将108个未归档ID全部称为Codex工程。

## 一、昨天有实际推进的工作

| 项目 | 实际推进与验证 | 仍未解决 | 下一责任 |
|---|---|---|---|
| V4公告选股 Issue44 | 10/18 02:35:19运行结束为PARTIAL；新增7只候选已显示。Reviewer PASS_WITH_P2限缓存、新结果及API/UI读回；已不再停留于83.519MiB产物被64MiB读回限制拒绝的旧状态 | 主任务192成功/3失败；分块27成功/18失败。38失败由17历史+3主+18分块组成，另1正文缺口、21资格未知。不能称全量成功 | 原研发/运行负责人定位剩余失败，验收侧逐项读原回执，避免重跑成功任务 |
| V4美港映射链路 Issue45 | 源码基线缺失已解除；之后已合并475f9d6并部署digest r2、manager r2、API r3，最终32d940ea；日期补丁独审30通过、1旧fixture失败。不能继续报未部署 | 缺匹配US16的owner回执；fallback实际US15，被US_OWNER_RECEIPT_ARTIFACT_SESSION_INVALID拒绝。API/UI仍INPUT_MISSING | 原owner提供正确日期回执，验收自然流程。计划窗口10/20北京04:15，US19→HK20；计划不等验收 |
| V5 PR4 | 产品91f1dbe补过响应竞争与测试问题；P0 Node164、定向UI84、typecheck及build通过。新增独立证据文档5f2558d | 官方完整前端仍471通过/14失败/6跳过；本地加仓库自带合成样本后474/11/6，两个结果不可混算。真实来源、浏览器、自然采集及18模块闭环未验收 | Chat补实际代码/接线和真实输入；验收侧固定版本验证。不能把fixture通过当真实业务通过 |
| PDF单条恢复取证 | 10/18约00:44已核单条GET能取得符合现有字段的链接，旧错误未复现，固定d56d0ea | 这只是取证，321条并未恢复；单document_key一次性可审计恢复入口尚待交付/验证 | 原修复方先补单条入口，保留缓存/来源，不全量重放或手改共享索引 |
| 192/193研究材料 | 恢复82356事件预测缓存、完成文件身份/日期/字段/行业连接与折结构检查；原193输入门29文件21:36交付并核远端大小/SHA | 原生193安装身份、历史INDEXC/ST/PIT、2022 selector域仍缺；内部结构自洽不是独立价格与防泄漏认证 | 材料持有人提供原件与来源，研究验收侧复用缓存逐项核验 |

### 昨天证据
- 公告终态：[Issue44评论](https://github.com/lexi2016/v4/issues/44#issuecomment-6238993559)，固定提交c482ede563632de8745f502c2f032c8c9fb28c4a。
- 美港链路最新部署与阻塞：[Issue45](https://github.com/lexi2016/v4/issues/45)、[固定部署交付回执](https://github.com/lexi2016/v4/blob/32d940ea014614fcb77e96f974c2b8941cf18812/docs/handoffs/issue45_pr46_deploy_20261018/ROOT_DELIVERY.md)。早期a56dbdaff45f887e7f8dbb38047a66d09fe5b1db仅源码交付，不是最终状态。
- V5：[产品提交](https://github.com/lexi2016/v5/commit/91f1dbe18e9da1d6abbdb974c600c8196a9b796e)、[官方CI](https://github.com/lexi2016/v5/actions/runs/39105893518)、[独立回执](https://github.com/lexi2016/v5/pull/4#issuecomment-6246895499)、[证据文档](https://github.com/lexi2016/v5/commit/5f2558d66c466777a92069f2b28b75daf6f8bf4a)。官方CI于10/18北京时间14:59结束。
- PDF：[固定取证入口](https://github.com/lexi2016/v4/blob/d56d0ea45374764b2f28ab14ead8426752a0f8d1/docs/handoffs/zsxq_pdf_url_probe_20261018/chat-followup.md)。PDF与Issue31公众号工作流分别统计。
- 193：[29文件归档](https://drive.google.com/drive/folders/13dCo_tLB9ozOfF7xKLojST-7quZKDiMv)、[R4证据解释](https://github.com/lexi2016/193/commit/4a7ed49d12bbd675b458821eef51ff5524d6acac)。旧摘要错误模型可复现，不等于实际部署接收器调用链认证。

## 二、今天的推进与问题

| 项目 | 今天新增 | 当前判断 |
|---|---|---|
| 193正式结果 | 13:22读取供方90次正式fit完成汇总，既有6canary；另1次线程试验PARITY_REJECTED，供方称暂停该试验 | M4相对M0 T1/T2/T5配对均值差−1.0266/−1.4857/−0.8582个百分点，三个冻结门禁均失败；M1–M3均负。目前没有可信改善证据。90fit不等于90配置；与总12配置预算映射尚缺冻结合同 |
| 193回放精度 | 11:08静态核实CSV读取改round_trip且保留零容差；供方称六cell回放EXACT、新fit0 | 我方仅静态检查PASS，未执行模型或测试；原始回放JSON/预测/逐cell回执未找到可读原件，独立回放NOT_RUN。新研究为毛close-to-close、历史已暴露，不能直接替代原open口径；原193比较器slot0 |
| 130只美港映射研究交付 | 今天北京时间00:43完成188路径研究文件，01:33完成GitHub28文件发布和读回校验；包含183原关系及补充/别名路径 | 130代码中126有可研究路径，4只仍整体待核/无清晰代理；16只存在整体或部分路径缺口。只属研究资料，不是已部署经理页面或预测有效性认证。此项是助手研究交付，不虚记为Codex产品修复 |
| 10/18公众号周末版 | 今天13:07核实79图资料包及OCR绑定审查回执，资料包身份PASS | 研究回传目录仍空，尚无五文件研究报告/V4归档验收。227代码附录来自10/14旧材料；10/18无交易观测不等于收益0 |
| V5 | 最近12:11增量检查，产品/文档提交和CI未变 | 未见今天新增可核代码、CI或真实页面采集回执。Chat正文可见性不足，不能据此断言停工 |

### 今天证据
- [193正式结果](https://github.com/lexi2016/193/blob/bcbf0a40a7abfb09ec85bc440b21dbf9b5ac21e8/research/a_share_model_selection_v1/FORMAL_RESULT_SUMMARY.json)，提交05:07:58UTC/13:07:58北京时间。90fit、100800选股记录为供方披露，不是我方逐行验收。
- [193精度修复](https://github.com/lexi2016/193/commit/64137f358927757a8e6da5d7b4d53330df311137)。本方新增fit/推断均0，今日进行了定向静态审查；正式结果独验NOT_RUN。
- [130只研究交付](https://github.com/lexi2016/v4/blob/53fee234802916a211891d8d7c0c767c9d9f5a03/docs/handoffs/us_hk_mapping130_supplements_20261018/README.md)。整体未完成代码00317、00586、02357、02922，细节见unresolved.csv；所有prediction_validation=UNTESTED、historical_pit_verified=false。
- [周末版资料入口](https://drive.google.com/file/d/14P1BmlkGEcWPHaAgkJcxbRsc2YTze9oQ/view)、[包审查回执](https://drive.google.com/file/d/13ECovNZkZmJeFLX0kETHpUthKCEKZZEn/view)。回执排除语义、Drive交付、Chat读取及V4归档。

## 三、优先处理顺序
1. 经理工作台：先补Issue45正确US日期owner，消除真实输入阻塞；同时处置Issue44剩余失败并保留7候选读回证据。
2. 193：取已公布SHA对应的selected_returns、metrics、输出manifest、冻结合同与逐cell终态回执，先零fit逐行复核负结果，不追加训练。
3. V5：补11项本地失败所需的真实current recovery回执3项、云workspace响应1项、原689行投影1项、owner observations6项；不得制造样本冒充实际自然链路。
4. PDF：先做单条有审计的一次恢复；公众号：先取得五份研究原文件再验收归档。

## 四、读取范围与限制
本次复用逐时盘点及固定证据，定向刷新Issue44、45、31和PDF入口。最近完整列表基线为108未归档+1归档，缺标题/时间/类型及部分空正文，不能可靠统计昨天/今天每一项Codex工时或完成数量。Issue31早期R2失败及10/11归档PASS属于历史，不列为昨天新增成果。报告没有新跑产品测试、训练、行情抓取或部署；任务列表中空正文不推断停止/完成。后续若原Issue更新，必须读取新回执，不能将本报告静态快照当实时状态。
