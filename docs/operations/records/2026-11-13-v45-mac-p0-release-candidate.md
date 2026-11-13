# V4 三入口 P0 · Mac 发布候选

- 唯一上游业务候选 `0a460190d6957d351b97d736e1ab057e0971581d`。17 个移植文件的原始 Git blob 已逐项复核。V4 源码基线 `937d0650902f4278c803ce7a241d74f50a36469b`，最终业务源码 `1c93645b34671c8569cc1eb367560b8051523751`，同步分支 `codex/v45-mac-p0-integration-20261113`。逐项前后 SHA-256 在本地 `SOURCE_SHA256.json`。
- 原 API 首页在 Vibe 8910 链接后追加今日选股 `/v45/selection/`、个股研究 `/v45/research/`、复盘验证 `/v45/review/`，原 API 负责 A/HK 数据读取。候选沿用 8873 现役首页主 bundle 和独立研究工作台绑定，首页加独立入口模块，三个新页面使用 Vite 构建资源。
- 独立 Reviewer 对最终业务源码 **PASS**。I1 要求公司材料匹配数值日包原生身份与 SHA，畸形数值项与独立图件分别显示。I2 隔离坏页和坏来源，保留已核兄弟候选，跨页整批身份冲突由原适配器拒绝。I3 切换港股观察日释放旧 run_id，已确认的新批次随同日跨页链接传递。
- 生产基线 API `v4-stage-card-context-20261113-r1-api`，PID 62616，manifest `800127cf5179e0088eb188b3ab2d3f13d987c59834cc32d854af704aeff8f292`。Main 与 Stage 均为 11 月 13 日 daily-history-delta r1，Stage 配置 owner 与 Main manifest SHA 相符。8873 runtime graph 对整体运行身份仍报 `CANNOT_CONFIRM`。

## 验收结果

| 核验 | 结果 |
| --- | --- |
| Node 24.19.0 / npm 11.17.0 / Vite 7.3.6 | Vite 118 模块构建成功。独立运行 39 项 Node 定向测试全通过，含真实冻结回放 2 项。冻结 ZIP 23 个 manifest 成员 SHA 匹配。冻结回放 HTTP 6 个 HTML、13 个资源通过。 |
| 现役池两日完整分页 | 11/12 A421、HK100、554 条来源关系，Stage7 缺件。11/13 A341、HK100、460 条关系，Stage7 PARTIAL。四个响应同日分页 fingerprint 和 source_digests 一致。冻结 11/13 样例 A272、HK100、386 条关系单独保留。 |
| A 股实样 | `000159.SZ` D11 数值和原图描述 READY，材料 NOT_MATERIALIZED。实际原图 HTML 和投影均 HTTP 200、SHA 匹配，候选浏览器 iframe 渲染。导航回踩 D+2 总 2／有效 1／未成熟 1，D+5 总 2／有效 0／未成熟 2。 |
| 港股实样 | `HK.02659` 原 0.2 池排名 1、分数 1.004231309893722。PREOPEN 绑定计划个股 READY、原判定 UNASSESSED，5 个 lane 明细。同批复盘返回 NOT_RUN，`SAME_DATE_CLOSE_INPUT_UNAVAILABLE`。候选浏览器从选股进入工作台，跨页携带该路径选定的同日计划。 |
| 真实浏览器 | Chrome 157，1440px 和 638px，三页直达、刷新、同日证券及来源日传递，页面无整体横向溢出。两种宽度都核 A 股研究和复盘，港股工作台及同日复盘在桌面核验。首页 10 个旧入口逐项相同，新增 3 项。旧研报决策台、经理选股、研究工作台和 Top200 HTTP 200 且前后响应 SHA 相同。 |
| 完整 Web 基线差异 | 640 条 Vitest。集成 607 过、31 失败、2 跳过。基线初次缺一份固定夹具，补同基线原夹具后该受影响套件 18/18 通过，剩余 31 个失败及 2 个跳过的断言集合一致。两端 `npm run typecheck` 通过。 |
| 生产 | 候选构建、独审、隔离 API/UI 已验。8873 切换和切换后 API/UI 为 NOT_RUN，线上三个新路径仍 HTTP 404。自然时段及 PIT 为 CANNOT_CONFIRM。 |

## 候选与回滚

候选 `v4-v45-parallel-p0-20261113-r2-api` 位于本机发布候选目录。正式候选 manifest SHA-256 `d4e4ac488640966b41fefdd439d40e407f781b08ec0ca2b9cd2287307f99c739`，1,380 个 inventory 条目，aggregate `ecacde2e9505a4ab4093ae5d42ab355fd34a282582da6adbb44bfbd3ac7b5c4c`。1,368 个旧条目字节保持，首页一项替换及 11 项静态新增。候选与 Chrome 验收目录的 app inventory 和 v45 delta 完全一致。正式路径在隔离环境实际启动，12 个 HTTP 入口与 frontend-build 身份通过，隔离监听随后关闭。

候选同级 `api-proposed.plist` 已通过 plutil。回滚对象为同级 `api-before.plist`，字节等于 8873 当时的现役 plist，SHA-256 `f126f92caae145a91fced70f36f0ad05727632bba500e0b57bd09cbdb3a2c4a5`。生产发布前重新核现役 plist 和 API manifest，取得切换授权后只操作 `com.lexi.v4.api`。回滚使用原 plist 及原发布根，回读 8873 健康和 frontend-build 身份。Main/Stage 绑定无需随此静态发布改变。此轮无生产切换。

本机证据目录为 `/Users/lexi/Desktop/学习/agents调试/v45_mac_p0_20261113`。保留 `CANDIDATE_RESULT.json`、`FORMAL_HTTP_RECEIPT.json`、`BROWSER_RESULT.json`、`LIVE_MEMBERSHIPS.json`、`REPRESENTATIVE_API_RECEIPTS.json` 和浏览器截图。旧工作台 `/days` 对同一证券仍返回较大的原快照，PREOPEN 实样约 87 MiB。公式对照两侧缺独立输入版本对账，当前在线可比性保留 CANNOT_CONFIRM。

`RESEARCH_ONLY=true` · `production_allowed=false` · `buy_gate_updated=false` · `orders_sent=false`
