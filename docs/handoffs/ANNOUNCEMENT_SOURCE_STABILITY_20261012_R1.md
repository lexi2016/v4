# 一天港股公告获取路径实测与选股断点 · 2026-10-12 R1

目标：比较既有路径完整抓取2026-10-12一天全市场公告目录的结果与耗时，检查图达通正文，定位公告选股此前的失败链路。日目录完整性与整天全部正文、港股通过滤、语义分析、选股及自然运行分别验收。上下文修复已按用户要求暂停。

## 全日来源结果

| 路径 | 日目录与时点 | 完整目录耗时 | 可取得内容 |
|---|---|---:|---|
| HKEX既有全市场目录collector（lang=ZH） | 实际响应17:59:02—17:59:14 HKT，316条唯一NEWS_ID；rowRange100/200/300/400累计分页，末页hasNextRow=false；0重复、拒收、gap | 16.373555秒，包含首个新鲜canary；collector12.1945秒复用了canary引用 | 发布时间、证券代码/名称、标题/摘要、原文件链接；246 PDF、65 XLSX、4 HTM、1未标类型 |
| 东方财富既有日期目录owner | 16:55:01 HKT冻结完整快照，102条唯一art_code；页行数20/20/20/20/20/2/0，6数据页+空终页 | 1.016740秒；目录7次新鲜网络请求。此轮只离线读回，没有重抓覆盖 | 中文标题、证券关联、日期/展示时间、公告分类；43个分类标签，77个证券代码；内容API文本正文 |
| HKEX旧逐公司主链 | 有限issuer批次；原R3只查5个发行人约47.8秒后耗尽45秒预算，全市场目录0行 | 没有整天完成耗时，不能外推 | 已查询公司的公告/PDF；不是全市场完整日目录 |
| 东方财富逐公司mirror／Vibe三业绩分类 | 范围是个股有限页，或末期/中期/季度业绩事件 | 全日全市场NOT_RUN，不合本次覆盖目标，不以个股成功冒充完成 | 个股公告或业绩事件；Vibe固定代码快照不是本轮运行证据 |

HKEX共有7个物理网络调用：4目录、2额外rowRange100重复检查、1目标PDF。三次同样的首100条请求均新鲜，HTTP200、响应SHA和NEWS_ID集合相同，仅证明约20秒内短期一致；完整日批次只采一次。含额外检查和正文的脚本合计25.709秒，不可把它标成单纯目录耗时。

图达通HK.02665：HKEX NEWS_ID12369250，06:05中文官方PDF，175912bytes、2页、1265字符，获取与解析2.663560秒；东方财富AN202610121830339681，1内容页、1570字符，0.264478秒。两源分别验证身份绑定；没有逐字一致性或语义审阅结论。没有下载并解析整天所有正文。

两源数量不可直接相减为漏抓。HKEX316条中180条发布不晚于东方财富16:55截止、136条晚于截止；源目录范围及日期语义仍不同，未做全目录精确join。当天后续新增和长期稳定性CANNOT_CONFIRM。

## 选股失败的直接断点

1. 默认owner仍先逐公司、后全市场，CaptureBudget45秒先耗尽。当前8873只读GET返回PARTIAL，33/33官方市场目录产品均0行、UNVERIFIED、ANNOUNCEMENT_TIME_BUDGET_EXHAUSTED，查询窗仍10/09—10/12；直接原生全日collector此次成功，不能把默认流程0行归因网站不可用。
2. 当日完整港股通资格文件缺失：HK_UNIVERSE_V2_ARTIFACT_MISSING。693条native master只证明REFERENCE_IDENTITY_NOT_TARGET_CONNECT_ELIGIBILITY，不能充当20261012资格名单。过滤结果不是已验证零条。
3. 显式EASTMONEY_HK_DATE_CATALOG可由当前API读到COMPLETE102条，但analysis GET返回NOT_IMPORTED、selection NOT_ASSESSED、consumption NOT_IMPORTED；采集成功没有接入完整分析／选股消费链。
4. 旧ANNOUNCEMENT_ANALYSIS_HTTP_503只是前端拼出的非2xx状态名。现有证据不能定位旧服务端异常；本次analysis GET为200。当前日志485条该GET记录为480×200、3×409、2×404、0×503，旧503根因CANNOT_CONFIRM。

当前只读观测PID19621，cwd为futu-api-projection-20261012-r4a/app；部分公告router/workspace_announcements/analysis字节与R3快照一致、与canonical当前树不同。候选测试通过不能证明这些线上模块已替换。旧日期已有选股亦含无效判断receipt或RETROSPECTIVE_RESEARCH_ONLY，没有证明近期自然计划last-known-good。

## 身份、复验与边界

唯一canonical源码根 /Users/lexi/Desktop/学习/v4_app；实际采集为直接原生provider/collector与既有共享MaterialStore，未改业务代码/配置、未部署或启停服务/调度、未导入分析／生成选股。图达通只是正文样本。RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。

证据根 /Users/lexi/Desktop/学习/agents调试/V4_ANNOUNCEMENT_SOURCE_STABILITY_20261012_R1/
- results.json SHA256 0abd36009158963ce9a9c54fb4664dce15be0d6f4f38b272cb7dfb2bb5486208
- offline_coverage.json SHA256 8d4934c933800f71884bfebfcda4a02a63494d4ca517eaf09a9e81202bfdadc8
- SUMMARY.md SHA256 39d10d9b9bb2166e4352495d06418da84bad94bfa847dfd4f5f9ef530fd2761f
- R3 owner-response.json SHA256 ccbd0a9601703bbbeb0eed8aa3b779ced9bd6c87fbe89d3b0b7323aaa9767951
- 东方财富原owner产品SHA256 0424c1108609ea97be0fcd491ca1b3cfd323cdb43fbd930a6b60570527f9bae1；run d539992bd01a433facfd445d2d23d1f1

过程脚本JSON解析与离线覆盖复算exit0；原capture PTY会话失效，进程exit code CANNOT_CONFIRM，数据语义必须以独立核心验证为准。原始响应、正文、共享缓存与认证只留本机，不上传。独立Reviewer READ_ONLY复验：REVIEWED PASS，日目录来源行为与图达通正文身份已验证；当前默认owner预算失败与analysis NOT_IMPORTED已只读复现。P1为既有线上选股链未恢复；P2为本次HKEX只验证lang=ZH参数返回的终页完整性，跨语言全集未确认，且research_cutoff为发请求前17:58:58，不能冒充严格该时点目录；目录口径采用17:59:02—17:59:14实际响应快照。相同旧EM receipt复用，不重抓。

远端独立分支基线 f1f23aebffcc69be03d59e4e271348c30b1929fe；本机工作树HEAD 55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054，与并行修改未纳入。本文件新增，前SHA不存在，远端读回后核验SHA。

建议在原owner内以披露易目录为主、东方财富镜像作为补充；先完成日目录再取所需正文／发行人增强，修复当日资格与既有analysis导入消费断点。只是后续最小修复方向，本批没有实施或发布。
