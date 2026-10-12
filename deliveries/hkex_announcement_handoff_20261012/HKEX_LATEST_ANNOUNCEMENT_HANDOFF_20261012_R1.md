# 港股最新公告采集修复交接 · 2026-10-12 R1

## 1. 接手人先看这段

目标是：从披露易取得近一天的全市场最新公告目录，完成分页、保存目录，再在本地筛港股通及有效公告。用图达通 2026-10-12 06:05 的公告验证，必须在目录、正文、默认 API 和页面中建立可追溯对应关系。

当前尚未完成。16:06 的实际 8873 服务仍运行 R3，默认公告 API 为 PARTIAL；其中七个采集 run 的全市场目录行数都为 0。默认 API 已有图达通同一事件的英文公告及已解析正文，但这不能证明全市场目录采集恢复，也没有完成用户指定中文公告和页面验收。

先前实现把旧的逐公司查询留在主链前端，并沿用跨多个交易日的回补窗口，偏离了本轮最新公告目标。用户已明确纠正。不要继续把这两项当作需要保留的当前主流程。

本文件是问题与继续工作交接，不是修复完成、发布许可扩大或正式选股结论。

## 2. 用户已锁定的方向

- 官方入口：https://www1.hkexnews.hk/listedco/listconews/index/lci.html?lang=zh 。
- 顺序：全市场最新公告目录 → 分页与本地保存 → 本地筛港股通 → 筛有效公告及需要的正文 → V4 原 API/页面读取。
- 采集目录时不先按公司、港股通名单、标题关键词或事件类别缩小来源集合。
- 包含当天盘前公告，实际发布时间与抓取时间分别记录。补采不冒充盘前自然运行或当时已知数据。
- 用户允许采用第三方公告来源；可核对、复用 V4 既有东方财富链路，来源身份必须如实标记。没有锁定必须只用一个来源。
- 近一天的时间起止应按香港时间明确写入 receipt。用户未逐字裁决“滚动 24 小时”还是“最新自然日”；已明确的是近一天、最新、包含当天盘前，不能默默改成周五至周一的多个交易日回补。
- 用户目前要求先交接和对比来源。尚未部署的新候选留在原处，不继续发布。

## 3. 已定位的卡点与证据

| 项目 | 证据与影响 | 当前状态 |
|---|---|---|
| 旧逐公司查询抢占全市场采集 | 14:50:21 开始的真实 owner 采集，5 个逐公司环节到 14:51:09 才完成，约 48 秒；共享上限 45 秒已耗尽，全市场目录 0 行、正文 0 份、完整性 UNVERIFIED | R3 实际失败，修正顺序的候选尚未部署 |
| 调换顺序后的预算异常丢失产品 | R4 先做全市场采集，但后续真实逐公司 collector 在 active-list 缓存缺失时抛出 CaptureBudgetExpired，保存产品前退出。原新增测试绕过了该真实分支 | 独立 Reviewer R4 FAIL，已由 R4-R2 针对性修复 |
| R4-R2 保存边界 | 真采集器 + 空缓存 + 虚拟时钟回归：全市场目录和正文已保存，后续到预算边界的逐公司查询明确未执行，attempt 为 PARTIAL | 独立 Reviewer 10/10 PASS，仅覆盖该保存边界；未激活 |
| 默认采集窗口仍不符最新目标 | R3 真实全市场请求日期为 20261009—20261012，起点 2026-10-09 16:10，沿用前一交易日收盘回补 | 用户已要求改为近一天最新公告 |
| 本地港股通过滤资格 | 当前 693 条 native security master 的 receipt 明确是 REFERENCE_IDENTITY_NOT_TARGET_CONNECT_ELIGIBILITY | 不能把这份名录直接当成目标日期港股通资格；需复用现有有日期与来源证据的港股通 owner |
| coverage 合同 | 当前 workspace_announcements 的校验/投影依赖非空 native scope；不再逐公司查询时，会把 scope 中公司全部标为未查询 | Writer 已报告需要区分全市场目录覆盖与逐公司覆盖；新增该文件写入尚未授权，未实施 |
| 最新主流程候选 | integration/latest-disclosure-r1/app 工作目录已存在 | 无冻结 manifest、无 closure、无独立验收，不能称已实现 |

真实失败源文件：`receipts/controller/r3-live/full-native-hkex-capture/owner-response.json`，SHA-256 `ccbd0a9601703bbbeb0eed8aa3b779ced9bd6c87fbe89d3b0b7323aaa9767951`。原始响应只留本机，不随本交接包上传。精简默认 API 读回见 `evidence/default-api-summary.json`。

R4 FAIL：`receipts/reviewer/minimal-api-owner-r4/review-20261012-r4.md`，SHA-256 `cde8fc142dd8a41baea8b4edec8482612deaa3884af51b27449ff6f141d75723`。

R4-R2 PASS：`receipts/reviewer/minimal-api-owner-r4-r2/review-20261012-r4-r2.md`，SHA-256 `3f72218a84773ee82813f5e795be69a285e64d795ca200a19e2b0bd7d97b84e0`。该 receipt 可以作为相同源码 SHA 的局部行为证据，不可升级成最新全市场主流程或 live 验收。

## 4. “预算”是什么、实际耗时知道多少

它是现有脚本中的内部限时/限次数机制，不是模型 token、费用、港交所额度或 Futu 历史配额。CaptureBudget 默认：45 秒、57 次原 provider 边界调用、调用间隔至少 0.5 秒。它计算的是 provider 调用，不完全等于底层物理 HTTP 次数；缓存与跳转会改变实际请求数量。

代码说明是每轮协作式限时，外层另有进程截止。正常 plan RPC 85 秒、daily RPC 90 秒、child alarm 101 秒、supervisor 111 秒是另一层限制。不能混成一个“抓取预算”。为何恰好取 45 秒，现有代码没有给出业务充分性论证。

已知真实的一轮旧路径耗时约 48 秒，仍未取得全市场目录。每个逐公司环节的完成时刻相隔约 8—9 秒，这不是单个港交所 HTTP 延迟的独立测量。新回归里的 44.5 秒目录、0.5 秒正文只是虚拟时钟，不能作为真实性能数字。

单条公告实际网络耗时、修正后完整全市场目录耗时、待处理正文批次耗时：目前均无完成的一轮实测。不得承诺“几秒抓完”或“一轮 45 秒保证全量”。几个小时的工程耗时来自实现、集成、复验及连续暴露的本地问题，不能归因于港交所本身慢。

## 5. 正确的 Vibe-Research 对比

指定仓库：https://github.com/simonlin1212/Vibe-Research 。本次查证固定 main commit：`d643728e79b955dfdcdcd8b0dd362bd7c90c35c8`，提交时间 2026-10-11 11:17:03 UTC。先前查看的是本机 `/Users/lexi/Desktop/学习/vibe-astock` 的旧实现，不能代替此远端版本，也不能据此断言当前 Vibe-Research 没有港股公告源。

| 来源/端点 | 当前仓库的实际抓取办法 | 与本轮目标的关系 |
|---|---|---|
| 深交所 + 东方财富：fetch_announcements | 深市按公司 POST 深交所 annList，失败再试东方财富；沪市/北交所走东方财富 np-anotice。默认最近 30 条，取标题、日期、主键、PDF 链接，不下载正文 | 可借鉴轻量目录、失败备源、主键和原始响应记录；不是港股全市场最新目录 |
| 巨潮：cninfo_announcements | 查官方股票→orgId 映射，再 POST hisAnnouncement/query；默认第一页 30 条，返回标题、类型、日期、详情链接 | 是独立 A 股公告接口，不是 fetch_announcements 中始终自动运行的第三条回退 |
| exchange_announcements | 深市仍为深交所，沪市/北交所仍为东方财富，返回公告与 PDF 直链 | 备源端点；不要把三个端点误数成三个不同的新数据网站 |
| 披露易：hkex_results_dates | 先按港股代码查内部 stockId，再分别查询末期、中期、季度业绩三种分类；每类最多 500 条，按 NEWS_ID 去重；hasNextRow 为真时标 truncated | 确实接了港交所，但用途是个股历史业绩事件回看，不能代替“近一天全市场全部公告” |
| SEC EDGAR | sec_filings、sec_daily_filings、sec_fulltext_search、sec_earnings_8k_dates；部分需 SEC 联系方式 | 美股申报与业绩来源，不是港股入口 |
| 东方财富转载 SEC | us_earnings_8k_dates 从新到旧分页，筛 8-K 2.02；翻到上限标 partial。事件回看中用作 SEC 联系方式未配或取不到时的来源 | 可借鉴清楚标记第三方转载与未取全边界 |
| RSS 等资讯 | 数据目录另有 RSS 新闻雷达等来源 | 新闻资讯和正式公司公告分开，不把资讯源数量算成公告覆盖证明 |

源码固定链接：

- `fetch_announcements.py`：https://github.com/simonlin1212/Vibe-Research/blob/d643728e79b955dfdcdcd8b0dd362bd7c90c35c8/.agents/skills/data-access/scripts/fetch_announcements.py
- `sources/cninfo.py`：https://github.com/simonlin1212/Vibe-Research/blob/d643728e79b955dfdcdcd8b0dd362bd7c90c35c8/.agents/skills/data-access/scripts/sources/cninfo.py
- `sources/exchange.py`：https://github.com/simonlin1212/Vibe-Research/blob/d643728e79b955dfdcdcd8b0dd362bd7c90c35c8/.agents/skills/data-access/scripts/sources/exchange.py
- `sources/hkex.py`：https://github.com/simonlin1212/Vibe-Research/blob/d643728e79b955dfdcdcd8b0dd362bd7c90c35c8/.agents/skills/data-access/scripts/sources/hkex.py
- 数据目录：https://github.com/simonlin1212/Vibe-Research/blob/d643728e79b955dfdcdcd8b0dd362bd7c90c35c8/datasources/CATALOG.md

图达通这条是自愿性出货量公告。只按“末期/中期/季度业绩”三分类抓取可能漏掉此类经营更新，这是对上述代码覆盖范围的推断，不是运行过 Vibe-Research 后的实测结论。本轮没有安装、运行或修改该远端仓库。

用户另给东方财富链接 `https://i.eastmoney.com/1229034599342114`。读取到的是个人中心页面，未取得其动态公告内容；不能把该个人主页直接当成完整港股公告 API。

V4 自身已存在东方财富港股镜像接口：ann_type=H、market_code=116，通过既有 provider/MaterialStore 保存来源。当前也是逐公司小批采集，不能仅改源名称就宣称全市场已覆盖。第三方全市场目录能力和耗时仍须实际验证。

## 6. 运行与候选身份

唯一 canonical 源码根：`/Users/lexi/Desktop/学习/v4_app`。用户入口：`http://127.0.0.1:8873/manager-selection/?date=20261012`。

16:06 运行观测：API PID 7733，cwd 为：

`/Users/lexi/Desktop/学习/agents调试/V4_HKEX_DIRECT_PREOPEN_20261012_R1/integration/minimal-api-owner-r3/app`

API launchd 文件 SHA：`243c918a05dbea7d4863c5b87fbb72ea66b6b69c6913e793cafc4d8866e8bc6f`。R3 release manifest SHA：`c0e16af05d06e4396aae77b21fe427667bd65ec411027d3c7800e4ad15f2de48`。这是本机快照，接手执行前重新核实时须只核必要身份，不重复已通过的完整测试。

R4-R2 的业务源码仍匹配独立 PASS：

- announcement_autorun.py：`9bdb97998408016628149f1dc8bf9a56a072b45abb1fe4aa6b7f93df3d716a5a`。
- test_manager_hkex_preopen_regression.py：`53e2d93b92307a29c7421509acdd27ff04f0f415e38daddfcafc5be60abbe4d3`。
- 原 source-closure.json 仍为 `37b354c9eb1f2dc343bf0d2f5281981937acc26476ae8d5d71d163de1ddc4b80`。

交接时出现候选元数据漂移：Writer 在恢复旧阶段时重新生成了未部署 R4-R2 的 release-manifest；当前 SHA `e7c2dde81faa5769543ed93f661528e600eda4c37e21afde707d1443edc842cc`，不同于 Reviewer 当时的 `042ed01b839516d52f7e243b5ad7a56eece19e6de346d9f5c8cfb539058a5c59`；另写 r4-r2-source-closure.json，SHA `f28a83f122e8441a18aad48a3ffac1de15ee15f55b0b32db567011616da3af3b`。源码和测试字节未变、live 未变。旧 PASS 不足以直接授权使用新 manifest 发布；下一候选必须重新冻结正确身份，不能冒用旧 pin。Writer 已停止进一步写入。

## 7. 最小继续工作范围

接手先按最新主流程裁决范围，不续旧逐公司主链。优先沿用现有全市场 HKEX collector、provider、MaterialStore、目录累积读取、正文缓存与失败续采；禁止另建平行 producer 或长期端口。

Writer 已读页面并报告：现有 official_market_directory_request 的无 stockId、SEHK、DateTime 排序、日期区间、累计 rowRange 与官方最新信息查询兼容。但这只是已报告的代码/页面定位，latest-disclosure 新候选尚无独立验收。

当前已允许的候选位置为 `integration/latest-disclosure-r1/app`，业务文件限 announcement_autorun.py、announcement_source.py、hkex_provider.py 及已有 HKEX 回归测试，后两模块仅在真实接口合同需要时变更。workspace_announcements.py 的 coverage 区分属于已报告而尚未实施的最小范围增量；不得擅自改成另一套 schema、owner 或数据层。

按既有唯一 Luna Max Writer、不同 identity 的独立 Luna Max Reviewer 工作。复用相同源码 SHA 的保存边界、分页、正文缓存等已通过 receipt；仅对新调用顺序、近一天窗口、本地过滤与 coverage 差异做针对性复验。

建议本批验收至少证明：

1. 真实来源请求不带公司/港股通/业绩类别预过滤；近一天全目录分页计数、唯一主键、截止时间与原始引用可核验。
2. 非港股通和无效/未评估公告先存在完整源目录，再本地排除并记录原因；不得把缺数据当成无效。
3. 当天盘前 06:05 图达通条目被捕获，中文原文目录 ID/正文 SHA/API 对应一致。后续刷新不因窗口/缓存游标推进而从累计读取中丢失。
4. 任一补充源/正文失败不丢已保存目录；已完成、失败、待处理、未评估清楚分开。
5. 源码独立 PASS 后，按真实候选身份完成必要 original-owner canary、原服务绑定与重载、默认 API 读回、页面重载核对。
6. 实测分别记录目录采集、正文处理与本地筛选耗时；不把模型分析耗时混入 HTTP 抓取。

本批修复未要求等待未来自然时段才结束；今天事后抓取只能标 manual/observation，不能称盘前自然运行已验证。

## 8. 图达通验收样本与边界

- 公司：图达通 / SEYOND，HK.02665。
- 发布时间：2026-10-12 06:05，香港时间。
- 标题：自願性公告 未經審核之二零二六年第三季度激光雷達出貨量。
- 官方中文 NEWS_ID：12369250。
- 中文 PDF：https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1012/2026101200006_c.pdf 。
- 此前官方直接读取的中文 PDF SHA：`d004e3e4f2c9339f52b4a641452faee3b17edbdfcb13d45686b1234c01a14f57`。只作样本 oracle，不能证明当前自动链已捕获。
- 默认 API 当前可读的是英文 PDF `2026101200005.pdf`，SHA `b998e63dba69b23e92fd1780dda7f1add3f93e0aef151ff2e10093e9fb1dc017`；body_status=BODY_PARSED。中文目标与全量来源及页面仍待核验。

保持 RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。不改 Vibe 8910 源码、配置或服务，不修改模型门禁和交易逻辑，不 merge/公开发布。

## 9. 本交接包内容

本 Markdown、精简默认 API 读回、实际失败摘要、原独立 R4 FAIL/R4-R2 PASS 与原 closure 的逐字副本、必要哈希清单。仅记录源码位置和固定 GitHub 引用，不包含凭证、账号持仓、原始公告全文/PDF、大体积响应、业务状态、完整源码树或依赖环境。

GitHub 同步以新的私有工作分支交付本交接必要字节，基线使用既有固定 commit `b123f8a49f60f3c8d0db4348a997fa59e8a32537`。本交接同步不代表运行修复完成。同步结果见交付时给出的分支与 commit，不把尚未读回核验的上传称为完成。
