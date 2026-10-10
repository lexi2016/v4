# V5 云端实际执行记录（2026-10-10 UTC）

结论：**隔离预览已启动，原经理普通 auto API 同 run 读回及实际响应 DOM 验证通过；三策略真实业务首批退出未通过。** 新真实采集已尝试，但来源网络/原准入阻断。没有 Mac 部署、自然验收、交易或 V4 修改。

## 固定身份与运行边界

- 保存环境 `/workspace/v4` 是默认旧提交 `615d1ce5417ed65ca2c8b736435c5d4596b79b19`。先 `git fetch` 和 `git ls-remote` 读回指定分支，确认 `v5/module-isolation-20261008` 为 `164c010c7eaa1659db9bfed0ff5f123c7a39eefc`。
- 独立工作树 `/workspace/v5-cloud`，新分支 `v5/cloud-preview-20261010`；本文和可复现工具的最终提交见远端分支，运行 Python 业务源码仍逐字为基线164c010。`02dbca5353a22c2e9ca55c1250b2cf9279800949` 已验证是基线祖先。
- Linux；Python 3.14.7、pandas 2.3.3、pyarrow 24.0.0；Node 24.19.0、npm 11.9.0。`uv sync --frozen --project V5` exit 0，npm ci exit 0。不是 Mac 的 Python 3.14.6 环境。
- 根 AGENTS.md 已读；工作树无 `.agents/skills`；Mac 上位规则文件不在云端，未声称读取。旧 README 的“不做云端测试”已被本次用户明确授权取代。
- Gateway `127.0.0.1:18896`，manager module `18897`，announcement module `18898`，启动 PID 分别 2925/2923/2924（当次记录，重启需重核）。实际 `ps`、配置及 SHA 留在证据目录。`/proc/<pid>/cwd` 读取被环境拒绝，未扩大权限；launch cwd 与命令行已记录。
- 页面 `http://127.0.0.1:18896/manager-selection/?date=20261012`；原首页 `/` 也提供，但其他模块未接线，不称完整应用可用。仅同一容器 loopback 可访问，无公网/受控转发 URL；父线程不能假定可访问 localhost。未触碰用户 Mac 61796 或 V4/8910。
- Gateway 静态 SHA 清单固定 11 文件，最终重建与运行清单完全相同。只读 GET 路由；未启动 scheduler/后台采集。无热加载承诺。

## 新真实采集、原计算与读回

**US / M03、M15：** 使用基线 canonical 原 `ops.us_market_digest`，在私有副本补入现有 vendor 的三个缺失 `_namespace.py`，无算法修改。首次三次启动为缺依赖失败，未联网；第四次才实际调用原采集。命令：

```bash
PYTHONPATH=/workspace/v5-runtime/us-owner timeout 180 V5/.venv/bin/python -B -m ops.us_market_digest \
 --data-root /workspace/v5-runtime/us-cloud --trade-date 20261009 --capture-phase POST_CLOSE --allow-late-post-close --timeout 10
```

原迟到窗口校验通过；真实 capture 时间 `2026-10-10T09:00:16Z`，capture id `f54d25d3d6f71030d818f181`。腾讯和五个 RSS 来源均失败；回执错误 `Tunnel connection failed: 403 Forbidden`。这是代理CONNECT隧道建立失败，尚未取得上游HTTP响应，不能归因上游站点拒绝；具体网络规则待正常环境网络配置核实。没有更换代理、扩大网络权限、伪造价格或再次采集。原程序 **exit 2**，`operation_status=NO_LANE_READY`、`market_snapshot_status=CANNOT_CONFIRM`。2026-10-10增量审查纠正：初版报告误把shell尾部tail命令的exit 0写成采集程序退出码；原`us-capture-4.exit`始终为`2\n`，SHA256 `53c234e5e8472b6ac51c1ae1cab3fe06fad053beb8ebfd8977b010655bfdd3c3`，原证据未改。原 owner 返回 `ORIGINAL_TIME_CAPTURE=true` 同时 `CONTROLLED_LATE_POST_CLOSE/late=true`；本报告按实际触发记手动迟到恢复，natural_verified=false，不改写 owner 字段。新产物保存三文件，未覆盖历史392批。

随后真实失败产物进入 V5 `current_us_research`，target `20261012`；原 US run `92999408fd0a4560ac96858f142f99b4`。US无可用输入，不能解释为四键或全市场有效空。materials为空且明确缺源，native master未绑定，未伪造材料。

**公告 / M13：** 固定 owner 包 `1a699a040c0b2cd467726bca5ccc7847182cb975`，组装 app manifest SHA `0ff96e3c5bc48c67fada2b979a9862b7778c9a33c1983cdc0ab180ea85125ab5`。55项安全测试通过后，初始化新私有根并调用原 `run_v5_private_announcement.py --allow-network-capture capture --target-date 20261012 --publication-date 2026-10-09`；forbid-root包含 `/workspace/v4`、`/workspace/v5-cloud`。只发1次东财目录请求，capture id `b79abd76866443b793e10d3310d4a209`，原目录 run `bcae607c36414e2c8bdff0dca1786dce`。exit 2，`ANNOUNCEMENT_DAILY_CATALOG_EXACT_READBACK_REQUIRED`；持久状态 `BLOCKED`，`BODY_BATCH_TRANSPORT_CONSUMPTION_UNKNOWN`、未知消耗1、可观测字节0、automatic_retry=false。没有换根清零、重试、Reader/Reviewer伪签或导入。

已查开发主线和相关已发布 owner/Mac交接包：只取得源码和精简回执，未取得392条完整合法产物；原计数及SHA没有被用来造数据。未声称穷尽所有私有外部存储。

**超跌 / M02、M14：** 已读 `40084ee76acf1c43b2d8768d538d7c91052437dd` 的 START_HERE/SOURCE_ROUTES。历史694 HOLD不变；包明确排除原始panel、membership和SDK输出。云端没有已配置Futu/OpenD、TDX VIPDOC及原资格/单位证明，未创建登录或凭据、未借用Mac历史配额、未运行无准入的替代采集；真实owner运行NOT_RUN。合成原owner比较独立通过，不能变成真实near1/入选。

**经理 / M18：** 原保存→独立read→普通view=auto→module API→gateway一致：run `b28fae24e8c446e199fa5a0743cb8c55`，plan SHA `b4c3beaa2b4de866426f7ed4898d6274c02899171b701759280882e465937a75`，`CURRENT/consumed=true`，attempt `PARTIAL/MANUAL_REFRESH`，`VERIFIED_WITH_GAPS`。发布generation `b9fef35a0726ec7009dd77a822d2092d0bf484b346e369415d866904e5297e4e`。这证明缺源状态的同run读回，不证明三策略真实结果可用。

`GET /api/v4/manager/research/workspace?date=20261012&view=auto` 200；公告 analysis、selection均503 `MODULE_RESULT_NOT_AVAILABLE`（明确接线但无产品）。不把503改0。普通页真实响应jsdom挂载通过：只一次auto请求、同run、缺源措辞，无伪造股票卡。

## 云端测试账（套件重叠，不相加）

- 全套 `PYTHONPATH=V5/src V5/.venv/bin/python -B -m unittest discover -s V5/tests -v`：539 tests，1 failure、38 errors、9 skipped，exit 1，302.758秒。保留原失败，不冒称全套通过。
- Error分组：18公告请求/真实owner夹具缺失；1US真实请求缺失；3归档依赖环境未绑定（后续独立补跑见下）；1revision测试bundle缺失；10个A预选子测试 `A_INPUT_PATH_NOT_DECLARED`；4个经理membership测试以周末当前日调用原交易日门。另1 panel error/1 failure是固定10/9预期在10/10实际时钟下不再显示当前观察。未倒拨业务时钟或改准入来过测试。
- A预选边界错误仍待定位：Linux `/usr/share/zoneinfo/UTC -> Etc/UTC`，原guard只描述Mac特例；不扩大沙箱读取范围。本轮没有把推测写成已修复。
- 原公告安全7套：18+12+1+9+7+7+1＝55/55、各exit 0；合成网络响应，真实原IO/限流/拒绝。
- 显式启用 `V5_REBOUND_OWNER_ORIGINAL_TESTS=1 V5_REBOUND_OBSERVATION_ORIGINAL_TESTS=1 V5_ANNOUNCEMENT_OFFLINE_TEST_BUNDLE=...` 后，`test_rebound_owner test_rebound_observation test_manager_offline_announcement`：54/54，exit0，66.556秒。包括原算法差分和合成原公告导入链，不计为真实业务回放。
- 给原归档源码补齐manifest指定的现有 `_namespace.py`，全依赖SHA匹配后，`test_archive_acquisition_producer test_archive_article_v2 test_archive_builder_identity`：58/58，exit0，98.593秒。真实collector/builder代码，合成获取/analyzer，未新采知识社区；natural_verified仍false。
- 前端最终经理目录：144 PASS / 4 FAIL，19文件中14通过、5失败（其中2 suite因缺JSON不能加载），exit1。3 failed cases缺Mac实际fixture，另1旧文案断言；未删测试。之前失败日志也保留。
- `cloudActualReadback.spec.ts`：1/1 PASS，实际云端API保存响应，jsdom。已包含于最终144，通过数不能再加1。
- 全量 `npm run typecheck` exit2：缺 `issue8R2.ownerObservations.json` 及派生隐式any。恢复原DTO类型后产品专用typecheck exit0；该检查不含测试，不能冒充全量通过。`npm run build` exit0，11文件，与在运行gateway静态SHA清单相同。
- 已存真实成功产物重放：NOT_RUN，未取得完整合法原批输入；本轮US是新失败产物的原计算/保存/读回。
- 真浏览器视觉/截图：NOT_RUN。无内置/托管浏览器工具；环境虽有Chromium二进制，但未使用它冒充用户指定浏览器。HTTP200和jsdom均不替代视觉。
- 自然接续/两个连续适用交易日/正式资格/独立Mac验收：NOT_RUN。

## 01—18原编号剩余项

| 模块 | 本轮之后仍需完成 |
|---|---|
| M01 A来源 | 当前原producer/面板/source receipt绑定、新交易日真实生产与05/09一致；本轮未采 |
| M02 HK来源 | 已配置行情/主表/Connect资格、单位/取得时点；云端缺源，未调用SDK |
| M03 US来源 | 云端网络许可内原来源恢复可用；本次失败不是READY；下个适用session自然续跑 |
| M04 归档 | 58工程通过；真实同批builder/source/获取时间、各lane与自然获取仍缺 |
| M05 A预选 | 修明Linux边界拒绝而不放宽安全；七池真实输入/正式消费、新日接续 |
| M06 HK预选 | 全套包含15项工程通过；真实100行旧池未随仓库取得；新池生产/资格/权重仍缺 |
| M07 A阶段 | 各真实窗口实时五价、完整05池、竞价/Stage等价与API/UI |
| M08 HK阶段 | 原资格及06池、真实窗口/半日、Stage7/8与API/UI |
| M09 A复盘 | 真实收盘来源、原算法产物、次日池及各slot自然验证 |
| M10 HK复盘 | 合法HK来源/原权重、真实收盘与次日池/自然slot |
| M11 盘中研究与研究复盘 | 真实触发、材料归档、原节点恢复和API/UI；非wrapper即完成 |
| M12 视频 | 原获取/转录来源与各节点产物、实际触发；云端无登录绑定 |
| M13 公告 | 新批BLOCKED不重试；完整目录正文、真实独立审核/合法392产物与普通读回 |
| M14 超跌 | 原历史panel/单位/资格与独立owner准入；694 HOLD不变；真实同run未有 |
| M15 US映射 | 两路径真实行情和材料、native身份、完整范围；当前INPUT_MISSING不是有效空 |
| M16 公开资料任务 | 原队列/合法来源/异步恢复与普通API；未启动持久worker |
| M17 尾盘跟踪 | 首次窗口真实记录、价/资格与后续跟踪；未补造错过窗口 |
| M18 经理计划 | 本轮缺源PARTIAL同run链已证；仍需三策略真实结果、视觉及自然恢复/回滚 |

P0：隔离根/版本/依赖/只读服务已证，原所有owner运行锁与调度尚未齐。P1：经理同run已证但公告/US/超跌真实业务阻断，首批未退出。P2：来源/池真实闭环未退出。P3：真实窗口/收盘未退出。P4：归档工程补跑通过，其余真实辅助链未退出。P5：全系统自然连续接续与跨模块回滚未退出。保留原总计划口径，不以本轮部分进展宣布18模块完成。

## Mac迁移、访问与回滚清单

1. Mac恢复后先核活动源码、进程、数据根、配置及锁；保留61796/V4/8910，云端不切换它们。
2. 拉取最终云端分支，按固定commit组装独立候选；核 Python/uv/npm lock、全部源码/配置/静态SHA。云端未持有原Mac patch，未声称拷贝；已按仓库源重组并验证默认auto同run语义。
3. 取得完整合法公告原件、US真实来源三文件、超跌panel/master/资格及原取得回执；逐个核SHA、run、日期/cutoff，原392计数不能替代字节。秘密不从云端或Mac搬运。
4. 只把必要源码/测试/工具/精简证据同步Git；云端原始来源、响应、计划、venv/node_modules/dist均留本地。云端失败policy保留，不作为可清零重试指令。
5. Mac独立跑适用回归，原内置浏览器桌面/手机、默认auto和显式历史/失败/日期切换；三策略实际结果或合法有效空同run。不沿用本轮云端通过作Mac完整验收。
6. 单模块候选发布前登记旧generation及expected_generation，用原CAS机制切换；失败回切已核旧generation，保留attempt与旧日标识。Gateway改配置/static需重启正确的候选进程并重新核SHA，不能只改目录。
7. 云端预览不再需要时只终止经ps核实的2925/2923/2924或其新PID；保留 `/workspace/v5-runtime` 与 `/workspace/v5-evidence` 供审阅。容器结束服务不保证存活；没有durable或父线程可达性承诺。

详细本机命令/退出码/失败日志在 `/workspace/v5-evidence`，来源与产物在 `/workspace/v5-runtime`，前端源码/构建在 `/workspace/v5-build/apps/web`。精简证据索引记录SHA；本记录不公开任何私有业务数据。
