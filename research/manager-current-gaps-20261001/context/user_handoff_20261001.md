# V4 公告、美股映射与日线补采交接

更新日期：2026-10-01（北京时间）。这是用户要求“先写交接文档”时的状态快照；不代表未完成项已经验收。

## 1. 接手先看这几项

**页面部分修复已上线；最新美股映射候选尚未上线。不要把候选的测试结果当作当前页面结果。**

| 工作面 | 已完成 | 当前缺口 |
|---|---|---|
| 公告 | 已部署；实际 API 与页面检查已完成。最近一次验收查询 15/696 家，取得 10 份文档，7 份正文解析成功，3 份受预算限制 | 不是全市场公告采集完成；仍有历史失败发行人，未取得自然时段验收 |
| 美股映射 | 4 个生产文件的修复、现有依赖补齐、隔离候选与启动配置准备完成；Writer 在实际服务 Python 下报告 9 项聚焦测试通过 | 独立候选验收进行中；2 个旧测试用例需要适配新行为；尚未部署、未验证新版本 API/UI |
| 港股通范围 | 候选按正式配置可读取 20260930 的 696 码，供 20261002 的 D-1 研究使用；保留来源日期、SHA 和实际可用时间 | 属于候选的只读投影，尚未证明当前 8873 已采用 |
| 日线补采 | 补采代码及隔离 capsule 的 27 项离线测试已独立通过；真实连接和外部公开接法已排查 | 没有拿到真实日 K 线；没有发布补采结果，也没有进行全 696 码补采 |
| 9 月 30 日经理尾盘选股 | 已检查相关结果与回执 | 有效结果仍为 CANNOT_CONFIRM；不要由此推断全 V4 所有阶段均无结果 |

当前没有下单或改动 BUY 门禁：`RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

## 2. 工作边界与当前运行版本

- 唯一源码项目：`/Users/lexi/Desktop/学习/v4_app`；用户入口仍为 8873。
- 本次继续目标：公告与美股映射收尾；补线另查通达信/pytdx 的真实连接方式。补线不可达不再阻塞映射修复上线。
- 不改 Vibe 8910、无关计划任务、Stage/A 股逻辑或其他工作区；不建第二数据源底板或平行 producer。
- 主控负责协调、集成和交接；业务代码由同一 Luna Max Writer 修改，独立 Luna Max Reviewer 验收。实际服务使用的 Python 和真实读回结果优先，不再追加版本字符串门槛。
- 当前用户已授权同范围的可回退本地修复、研究服务发布与必要重载。接续不应为同一动作重复索取批准；发生新的范围、权限或生产/交易变化才另行裁决。

本次写文档时已重新读取活动 plist：

```text
plist: /Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist
plist SHA256: 2ba6b17639d769fe8adf977707b099ec1de1587c65b81eb0675d3ad81323996b
active release: r4-stage-merged-c3e5357d07f068e79296790e0b968934c34541d579c586282c5e83f56f6a3875
active app: /Users/lexi/Library/Application Support/com.lexi.v4.local/releases/r4-stage-merged-c3e5357d07f068e79296790e0b968934c34541d579c586282c5e83f56f6a3875/app
active manifest SHA256: ec5c62cd8a9935c6c2838afd3c02a98ea9fe9d2aaefdae27fb5d462a8c65e3b5
```

浏览器当时地址为 `http://127.0.0.1:8873/manager-selection/?date=20260925&plan_date=20261002`。页面参数中的历史日期和计划日期必须分别解释，不能当成新数据的来源日期。

## 3. 美股映射的实际修改与最终候选

修改范围：

1. `ops/us_market_digest.py`：同一交易日、不同秒的报价时间只作诊断，不再因此整批降为 PARTIAL；混合交易日等真实错误仍受约束。
2. `v4/manager_research/us_market_bridge.py`：对已核验的旧归档报价做内存重放，修正限定的旧误判；保留旧采集时间、原响应 SHA、旧存储状态，不重写归档。
3. `v4/manager_research/connect_selection.py`：保留原 V2 路径，并接入显式 D-1 来源分支，区分目标日期与来源日期。
4. `v4/manager_research/connect_capture_adapter.py`：校验原始双名单采集、manifest、panel receipt、原生 master 与成功 dispatch 链；支持正式配置的 `receipts/live` 根目录，避免重复拼接 `live/live`。
5. 两个新增测试文件：`tests/test_manager_us_quote_replay_r4.py`、`tests/test_manager_connect_capture_adapter_r4.py`。
6. 打包时补入现存 `ops/_us_market_digest_parts/` 的 13 个 Python 文件，逐文件 SHA 已记录；不是另写一套解析器。没有重建前端，也没有混入日线补采改动。

**最终候选以 handoff 的明确字段为准，不按文件名排序或目录时间猜测：**

```text
release: r4-us-mapping-6e1538c6804ba0bc0a15a9c60564601c1677de3915849afc22ba589081a72850
root: /Users/lexi/Library/Application Support/com.lexi.v4.local/releases/r4-us-mapping-6e1538c6804ba0bc0a15a9c60564601c1677de3915849afc22ba589081a72850
manifest SHA256: 55618356e7014fe458e50c75b2af380b5b214e0a8df68f021cb9cb647e7916dc
inventory: 1006 entries
inventory aggregate SHA256: 836d43caf68fdc40b95cedfa3a40a9b928fd38ac4da48dc0c431af33388ed83a
activation: NOT_ACTIVATED
```

源码逐文件 SHA、精确测试命令、旧数据散列、候选 diff 和配置路径都在机器交接文件中，不必重建一份清单：

[writer_handoff.json](./us_mapping_repair/writer_handoff.json)

该文件本次读回 SHA256：`fda0f1873db0bc32c4591cc5d7b9ce21ca4b313d624c504c2c6c1049e37e7953`。候选 manifest 已由主控读回核对相同 SHA；这只是身份核验，不替代独立测试。

两个旧候选保留但已废弃，禁止部署：

- `r4-us-mapping-0da6743e…4900c`：漏了 13 文件依赖包。
- `r4-us-mapping-ea56b90e…aa376`：未兼容正式 dispatch live-root。

Writer 报告的真实只读投影：

- 20260930 美股原始 33/33 报价、24 个行业代理，重投影为 READY；有 6 个上涨行业、9 个上涨代理标的。此结果不等于已有合格港股映射候选。
- 原归档的 PARTIAL/CANNOT_CONFIRM 标签与字节未修改；保留 `captured_at=2026-09-30T20:15:00Z` 和原响应 SHA。
- 港股通 D-1 范围为 OWNER_VERIFIED，696 码，`source_date=20260930`、`target_trade_date=20261002`、`scope_error=null`。
- 数据可用时间上界来自成功 dispatch：`2026-09-30T17:20:08.269649+08:00`。
- 以上尚待独立候选验收；新版本 API_VERIFIED/UI_VERIFIED/NATURAL_VERIFIED 仍为 CANNOT_CONFIRM。

## 4. 测试与独立验收尚缺什么

**新增候选清单问题（独立 Reviewer 已发现，最终评级待定）：** `release-manifest.json` 的 `source.us_mapping_overlay.base_release_id` 错指向候选自身 `r4-us-mapping-6e1538…`，而 `candidate.base_release_id` 与 `base_manifest_sha256` 指向实际的 `r4-stage-merged-c3e535…` 基线。身份校验器 PASS 没有覆盖此字段一致性。该不一致应在发布前修正并重新绑定 manifest/plist SHA；当前候选暂不得上线。不要原地改已冻结候选后仍沿用旧身份。

Writer 在候选内、实际 API 服务 Python 3.14.6 下运行两份聚焦测试：**9 passed in 0.11s**。release identity、plist 解析、只读发布前置检查也报告通过。按项目合同，这些是 Writer 交接证据，不能直接登记为最终 TESTED。

此前扩大运行得到 `43 passed, 3 failed`。独立 Reviewer 最新已完成以下定性，但完整候选最终 verdict 尚未交付：

| 失败项 | 独立定性 | 下一动作 |
|---|---|---|
| `test_us_map_freshness.py::test_latest_partial_keeps_both_times_and_quality` | 旧 fixture 把同日秒差行情强制标为 PARTIAL，与本次正确 READY 行为冲突 | 有界修正 fixture/期望并复验 |
| `test_us_map_freshness.py::test_reads_do_not_mutate_artifact_receipt_or_manifest` | 同一旧 fixture 产生无真实缺口的 PARTIAL，触发存储一致性校验 | 同批修正，仍须验证读操作不改旧数据 |
| `test_manager_us_market_bridge.py::test_partial_snapshot_keeps_raw_discovery_but_never_becomes_ready` | 精确旧版 preimage 已复现；fixture 缺 `relation_origin=NATIVE_MATERIAL_PROPOSITION`，原有门禁即拒绝；属既有测试缺口 | 单列既有问题，不为通过此例削弱来源门禁 |

已授权 Writer 仅为前两项调整 `tests/test_us_map_freshness.py`，尚未确认实际完成。若修改导致候选身份变化，需要记录新身份；未变化的生产源码与已独立通过的测试证据可复用，不重复全套审计。

角色交接状态：

- `/root/r4_actual_capture_writer`：业务修改与冻结候选准备；发生两次回传连接中断，已按同一任务恢复，产物未清理、未从头重做。最终 v2 handoff 文件已经读回，Writer FINAL 已收到；其明确确认尚未修改两个过时测试 fixture。
- `/root/r4_independent_reviewer`：只读检查；已完成上述失败定性，正在核验 v2 pins 并做候选验收。等待明确最终 PASS/FAIL 和证据。
- `/root/r4_us_selection_trace`：补线连接调查已完成，没有成功 K 线样本。

## 5. 日线补采与“别人怎么连接”的排查结果

现有实现采用 `TdxExHq_API`、日线 `category=4`、港股通 `market=71`；官方接口文档中的参数形状与之相符。没有证据说明这两个参数本身用错。

共验证 9 个不同地址；除一台能连接/setup 但功能读取超时外，其余连接拒绝或超时，**没有获得任何日线样本**：

| 路径 | 地址 | 实际结果 |
|---|---|---|
| 本机既有首选 | `119.97.142.130:7721` | 连接拒绝 |
| 本机既有备用 | `101.227.73.20:7709`、`119.147.212.81:7727` | 连接超时 |
| 公开旧扩展配置 | `112.74.214.43:7727` | setup 成功；第一次日线调用报错。后续有界诊断中 `get_markets()` 等待响应头 5 秒超时，未再请求日线 |
| 同一旧配置 | `119.97.185.5:7727`、`106.14.95.149:7727` | 连接超时 |
| Mootdx 当前启用配置 | `47.112.95.207:7720`、`218.75.75.18:7720` | 连接拒绝 |
| Mootdx 当前启用配置 | `58.49.110.76:7720` | 5 秒连接超时 |

参考来源：

- [TDXPY 扩展行情文档](https://tdxpy.readthedocs.io/zh-cn/latest/api/exhq/)
- [Mootdx 当前服务器配置](https://github.com/mootdx/mootdx/blob/master/mootdx/consts.py)：旧 7727 组已注释，当前启用上述 7720 组。公开配置存在不代表本机可用。
- [旧 pytdx fork 的 connect.cfg](https://github.com/wxyzZ/pytdx/blob/master/connect.cfg)

真实三码 canary 使用原 owner wrapper 和实际配置运行环境。最初的 `contracts` import 路径问题已通过补充临时进程 PYTHONPATH 解决；之后停在真实网络连接失败，不能把外层编排进程退出 0 当作采集成功。

补采 capsule：

`/Users/lexi/Desktop/学习/agents调试/MANAGER_R4_ACTUAL_RESULTS_20261001/data_repair/capture_capsule/d2919357df1ed293550e/app`

[补采 capsule 身份回执](./data_repair/capture_capsule/d2919357df1ed293550e/capture_capsule_receipt.json) · [真实 canary 失败回执](./data_repair/actual_three_code_canary_v2_execution.json) · [失败日志](./data_repair/actual_three_code_canary_v2.log)

尚未安装/切换行情库、修改代理、修改服务或创建新 producer；没有发布官方补采指针。接手只有获得新的可验证连接条件或来源证据才继续，不盲目重复同样地址。后续仍先验证 `00005,00700,00941` 三码的真实日期/完整性，再决定全 696 码补采。

## 6. 接续执行顺序

1. 读 v2 `writer_handoff.json` 和最新独立 Reviewer 结果；以明确 FINAL/产物身份为准，不扫描旧会话或重做已确认来源。
2. 修正候选 manifest 的基线版本字段不一致，关闭两个过时测试 fixture 的问题，保留第三项既有缺口的独立证据；取得最终源码、候选和相关行为的独立 PASS。
3. 发布前重新核对当前 live plist/运行版本及另一 Stage 会话的发布状态。若基线已变化，先保留对方改动并重新集成，不能覆盖。
4. 仅应用新候选的已核验 inactive plist。变动限 5 个 release identity 参数、WorkingDirectory，以及两个只读目录变量：
   - `V4_MANAGER_HK_CAPTURE_RECEIPT_ROOT=/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/receipts`
   - `V4_MANAGER_HK_DISPATCH_RECEIPT_ROOT=/Users/lexi/Library/Application Support/com.lexi.v35.local/state/dispatcher/receipts/live`
5. 使用 handoff 指向的修订版 guard helper，做有回退前像的切换；确认旧 job 已卸载、端口已释放后再启动新版本。不要用旧 build 脚本中的废弃 CAS 模板。
6. 8873 重新读取 `GET /api/v4/manager/research/workspace?date=20261002&view=dynamic`，核实 33 份报价重投影、696 码范围、实际映射卡片和真实缺口；再核对公告展示仍正常。HTTP 200/readyz 只证明接口存活。
7. 浏览器重载普通经理页面，检查日期语义、公告文档和美股映射结果并保留截图。合格映射数量取决于实际材料与双来源门禁，不能为得到非零数而放宽条件。
8. 日线补采保持单独阻塞；尾盘选股与其 owner 的实际结果另行确认。未观察自然运行前继续标记 NATURAL_SLOT_UNVERIFIED。

另一 Stage 会话：**修复 V4 阶段选股故障**，ID `01a0eac3-4e67-7bc1-80fe-bf46dbd03b9c`。最后读取状态为仍在独立复验、尚无新的港股恢复结果；不是当前时刻的保证，不自动授权向该会话发消息。

## 7. 关键证据入口

- [美股映射最终机器交接](./us_mapping_repair/writer_handoff.json)
- [原始修改前像与 receipt](./us_mapping_repair/preimages/batch_20261001/receipt.json)
- [公告第 6 次修订独立验收回执](./rollout/evidence/merged-live-announcements-r6-independent-acceptance.json)
- [前次合并版本上线回执](./rollout/evidence/merged-live-activation.json)
- [前次运行版本独立验收](./rollout/evidence/merged-live-independent-acceptance.json)
- [公告页面截图](./rollout/evidence/merged-live-announcements10.png)

本交接不宣称最新候选已上线，不宣称公告全量采集完成，不宣称日线补采成功，不宣称尾盘有效选股或自然运行已验收。接手应从尚未完成的具体步骤继续。
