# Mac：源身份、隔离单阶段、发布与同一结果读回

## 1. 先确定真实运行对象

固定问题包记录的 owner 如下；它们是输入时的事实，现场仍须重读。

| 角色 | 原根 |
|---|---|
| canonical 源码 | `/Users/lexi/Desktop/学习/v4_app` |
| actual Stage | `/Users/lexi/Desktop/学习/agents调试/V4_HK_STAGE_RECOVERY_20261003/issue23_runner_helper_r3/stage_r1_binding_candidate_r3/app` |
| actual API | `/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app` |
| Stage plist | `/Users/lexi/Library/LaunchAgents/com.lexi.stage-center.scheduler.plist` |
| 用户入口 | `http://127.0.0.1:8873` |

读取 plist 的 `ProgramArguments`、`WorkingDirectory` 和其中实际 `--config` 路径，核启动器使用的解释器和 flags/bootstrap。保留 venv Python 的 lexical 路径，不能把 symlink resolve 成裸解释器。本轮包未附当前 plist/config 正文，不能凭历史示例猜它们的值。问题包记录 plist SHA `9c7199ca1fcfedc09397255c932d25c6edc15779952bbd5b5bec2671e883d3f5`、config SHA `ef5f49cb4efc35ec76e718415662cece51abb327b6ea7d5ccaa45df2b91869f7`；若已变，先记录新的事实与差异。

对 `SOURCE_MAP.json` 每个目标只做所需文件核验。actual Stage 与 canonical 的 receipt/slot 前像不同，分别集成。API reader 是本轮 actual 源码；API consumer、三个 UI 文件、四份节点 helper 只有固定树中的历史前像。历史前像匹配才可直接应用；否则在当前文件上移植最小语义差异，并对保留的并行修复做独立验收。不得把本包切片拼成完整运行 app，也不得把测试 support/references 部署到应用。

用现役完整 app 建一个新的隔离候选，保留全部非改动文件的 SHA 清单。逐组执行 `git apply --check <绝对补丁路径>`，然后应用并核后像 SHA；补丁路径和目标 owner 见 `SOURCE_MAP.json`。UI 同样只集成现有页面，不另建面板。现役预选 API、scheduler/shared、经理和公告修复要保持；不要刷新不相关的旧 Issue23 pin 或用旧 API 整包覆盖。

## 2. 候选测试与实际 import

先在解压交付根验证文件：

```bash
python3 tools/verify_package.py
```

选择本机已有 pytest 的受控 Python。UI 测试使用 Node 24 与 Vue/compiler/server-renderer 3.5.13。可在本包的隔离测试依赖目录按锁文件安装：

```bash
npm ci --ignore-scripts --prefix work/ui_runtime
"$STAGE_TEST_PY" tools/run_targeted_checks.py --node "$STAGE_TEST_NODE" --output "$STAGE_TEST_OUTPUT"
```

三个变量均填写已确认的绝对路径，输出目录必须是新的、在交付包外。这里的 suite 是切片和组件 SSR；随后还要在完整候选 app、原真实依赖和原启动方式下复跑对应断言，核 `runner`、选择器、receipt helper、API reader/consumer 的 `__file__` 和 SHA。候选导入失败、依赖 pin 失败或非改动文件丢失都不能进入发布。完整 App 构建/类型检查与现有项目要求保持，不用 SSR 代替。

## 3. A 原行情字段链的定点核验

用同一个 20261009、stage、股票代码，核 provider 原 payload → 原 SourceResult → 原 builder 行或 qmt → 选股 envelope。

- source 有昨收而当前 builder 丢失：取得当前 `selection_builder_registry.py` 的精确源码与 SHA，只修原值透传，不部署 10/8 旧整文件。这个旧断点已在参考源码确认，当前是否仍有要由现场确认。
- source 自身缺昨收：结果应为 `prev_close_price=null`、`current_change_pct=null` 和明确原因；不能显示真实 0。真实价格相等且昨收有效时应显示 0。
- 09:25 缺 11 只的回执是 EMPTY_PAGE；记录实际代码、来源和重试结果，不直接认定供应商永远不覆盖。后续阶段少 10 只的具体原因从原 source/receipt 提取。
- A 输入仍为完整 216，不读取 UI 的 200 行切片作为算法输入。HK 缺输入不阻断 A；坏/空/partial 子池只隔离。缺新闻/研报等补充材料不新增全局评分门禁。
- 原算法 SHA、评分入参、分数、排名、Top10、支撑/压力/失效位规则保持；新的观测字段使新结果 run/artifact identity 变化是正常现象。旧已结算 run 不回填、不强行覆盖。

## 4. HK 的恢复前提

当前 **BLOCKED_DATA**：未找到真实 20261008 资格主表三件套，正式 20261009 池为 0。已部署 ensure/shared 模块提供的合法恢复步骤见 `work/hk_entrypoint/HK_AND_ENTRYPOINT_REVIEW.md`。

若找到真实来源，核原 index entry、run、artifact/manifest/receipt、trade_date、同一 universe codes SHA、安全位，以及带时区的真实 `captured_at`，其上海日期和各行应为 20261008。按原已部署 ensure 的 `--reuse-only --verified-source-store-root <已验证来源根>` 恢复；其他 store/universe/shared/python 参数从现役配置取。该可选原件恢复仍要求源与目标 writer 静止，历史并发 P2 不因本轮补丁自动解决。

随后仍须通过精确 10/8 价格面板与 PIT，再由原 HK producer 生成 target=20261009 的正式 Top100，沿原 materializer/consumer 落到本地权威池，再由原 Stage exact-date binding 读回。任何一环缺失都保持具体失败。禁止把今日 snapshot 或 9/30 池改标 10/8；10/9 Connect 开市，不能使用仅适用于 Connect 关闭日的旧观察 lane。找不到原件就记录确切缺口，不能把状态改成 READY。

## 5. 真实同日、隔离、单阶段入口

`stage_center.runner` 本身没有 CLI。已核同 owner 历史入口是 `ops.run_stage_center_nodes`；现场要核当前 facade/helper 与 plist 一致。使用实际时钟，不传伪造的 `--evaluated-at`。

从实际 config 复制新 canary config，仅将 `raw_root`、`selection_root`、`receipt_root` 改为新的独立输出目录，例如同一新 canary 下的 `stage/raw`、`stage/selection`、`stage/receipts`。这个 sibling 布局保留原 consumer 的绑定合同。所有 candidate、HK pool、研究/新闻、原共享来源根继续明确指向原已核输入，保存 config 的精确前后差分。任何额外输出或权限变更须另核；不要把未核 `V4_STAGE_CANARY_ROOT` guard 或旧配置例子直接加进现役命令。

以下变量来自上述身份核验与隔离候选，不能留空。若现役入口有必要 flags/bootstrap，沿用其原启动方式。

```bash
: "${STAGE_APP:?填写完整隔离候选 app 根}"
: "${STAGE_PY:?填写现役受控解释器的 lexical 路径}"
: "${STAGE_CANARY_CONFIG:?填写新隔离配置绝对路径}"
cd "$STAGE_APP"
"$STAGE_PY" -m ops.run_stage_center_nodes --config "$STAGE_CANARY_CONFIG" --check
"$STAGE_PY" -m ops.run_stage_center_nodes --config "$STAGE_CANARY_CONFIG" --trade-date 20261009 --node STAGE_0945_1030
```

这是指定一个 10:30 截止的节点，不是 all-node 扫描。当前上海日若已不是 20261009，不得忽略日期拒绝；另按真实历史数据和既有 backfill 合同做回看。历史 nodes parser 的 `--historical-backfill` 没有传给 runner，不能当隔离保证。已核真正隔离 backfill 的入口是原 `ops.run_stage_center_tick --historical-backfill --stage-id ...` 到原 `tick_planning._backfill_runner`；本轮没有执行历史重建。

手工晚于上午窗口的 canary 只算恢复/回看。已结算槽位返回 SKIPPED/NOOP 属原幂等行为，不代表新字段已生成；另建新的 canary 输出，不能删 live receipt、latest 或锁来强跑。

### 预期产物与核对方式

| 产物 | 原路径合同 / 必须核什么 |
|---|---|
| 阶段原行情 | 新 `raw_root` 内由原 RawStore 写出的实际 bundle/source 及 receipt；从原返回引用验证，不猜文件名。核请求代码216、日期/stage、provider/capture、cutoff、安全位和缺口。 |
| 选股三件套 | 原 SelectionStore 的 `selection_runs/<date>/<role>/<run_id>/artifact.csv`、`manifest.json`、`receipt.json` 及 `selection_latest.json`；路径由原 `_verify_run` 确认。envelope 与列投影合同保持，JSON 允许缺值为 null。 |
| 当前执行回执 | 新 `receipt_root/20261009/STAGE_0945_1030/receipt.json`。A/HK 状态独立，保留原错误；核真正 `runner_invoked_at`、`recorded_at` 及来源字段。 |
| owner 历史正文 | 同槽位 `attempt_evidence/recorded-<SHA>/RECEIPT.json`；SHA 是真实正文原字节，内容与当前回执去掉历史指针后匹配。检查外层 mode/attempt/deadline 最终重写后仍绑定。 |
| 绑定 | 原 reader 调用使用 consumer 原 `self.store`；selection 三件套原字节/规范 SHA 分开核。owner archive 是原执行方历史，`natural_verified` 仍 false；缺完整输入绑定处保留缺口。 |

## 6. 发布、8873 与回滚

通过完整候选和独立验收后，沿本机现有已授权发布流程仅发布所验模块 delta。发布前保留旧 release、启动/模块指针、bundle、config 的精确 SHA 和非改动文件清单，先完成已有审查 gates。不要构造新的切换发布器，也不要替换整个 API 来发布一个 Stage 模块。

发布后核真实 Python import root、API process root、当前 frontend 资源清单与 SHA。既有页面问题不能仅靠源码变动推定恢复：固定历史 App 在有 execution_evidence 时本应显示面板，而观察页面仍是旧提示，这需要现场查构建/加载身份。

只读检查实际入口：

```bash
curl --fail --silent --show-error \
  'http://127.0.0.1:8873/api/v3/workbench/stage?date=20261009&stage=STAGE_0945_1030&limit=10'
```

该 Stage 接口 limit 最大 50，不用预选接口的 limit=200。逐个核 date、stage、market、run_id、algorithm/raw/artifact identity、selected/requested/source 数；浏览器选择同日期/阶段，确认行表与新面板读的是同一结果。五个已有 A 结果仍可显示，其旧字段与旧回执不能被新代码自动伪装成新生成。隔离 canary 结果若尚未按原 owner 的合法流程接入配置中的 selection root，8873 不会自动显示它；必须显式记录该状态，不能把另一个根的成功当页面验收。

若出现模块丢失、字段回归、非改动文件变化、API/UI identity 不一致或错误交易安全位，通过原流程切回保留的旧 release/config/bundle，再读回其 SHA 与 8873。不删除新证据、不改旧业务产物。未发布的候选可按对应补丁 `git apply --reverse --check` 后反向还原。Vibe 8910 不变。

## 7. 自然运行独立验收

下一次真实自然窗口记录真实 launchd/parent 触发来源与时钟、实际 runner 调用时间、行情 capture/cutoff/PIT、原 raw/selection 和最终 receipt/history，再核 8873 同一 run。手工同分钟调用也可能被原规则分类 NATURAL；故 NATURAL/DUE 字样不等于自然证明。

研究模式要求与三个 false 安全位必须现场读回；若当前合同未暴露 RESEARCH_ONLY 环境字段，记录该字段尚未确认，不能声称已读到。测试、单次回看、owner 自存档案或 hourly 成功都不能替代自然闭环。历史缺数据、缺原时间和缺独立触发证据按原事实保留。
