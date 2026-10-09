# Stage 最短链路：HK 输入与原入口只读核查

固定仓库输入：`lexi2016/v4@28ab2d35020adf031f10f38c1040514fc81b6d66`。本报告只读源码及已上传证据，没有连接 Mac、采集真实数据、启动 Stage、发布或改写业务输入。源码基线与远端文件均核对 Git blob / 字节数 / SHA256。所引用 10/5 源码由该批 `MANIFEST.json` 的 **stage variant** 映射到同一个实际 Stage app；这是过去采集的运行源码，不能替代 10/9 本机重读。20 文件本轮包的 actual/canonical 身份以本轮 `SOURCE_MANIFEST.json` 为准。

## 一、结论及本轮边界

1. **A 阶段已经执行并产生结果。** 当前包 `PROMPT_FOR_CHAT.md:14–24`、`DIAGNOSIS.md:5–13` 记载前五阶段 216 输入、205/206 行情、各 10 只结果；9:45 阶段声明 NATURAL/DUE 不等于独立自然验收。不要再诊断为算法尚未执行。
2. **HK 20261009 阻断是缺少合格的 20261008 主表及随后正式 Top100 产物。** Mac 有界核查没有找到可恢复的原始三件套，最新确认 20260930；已见 10/8 价格观察的 provider_finality 仍为 CANNOT_CONFIRM。不能通过修改状态、重标今日/旧日快照或新增旧池 fallback 补出输入。
3. **Issue32 的 scheduler/shared 配套修复已部署。** 本轮复用，不重新发布这部分。可选 verified-source restore 仍要求原 writer 静止；Mac 回传将其记录为非阻断 P2，不能宣称具备并发事务安全。默认已部署调度没有配置该可选恢复参数。
4. **已有真实单阶段入口可用作本机核对后的执行入口。** `stage_center.runner` 本身没有 CLI；同 owner 10/5 快照有 `ops.run_stage_center_nodes` 和 `ops.run_stage_center_tick`。本轮可给精确入口合同与本机步骤；必须先核 10/9 plist 实际 argv、config、模块文件 SHA、解释器及实际 import root。当前缺这些内容的现场读回，不能假设仅改 workspace 就生效。
5. **触发时钟、实际行情 cutoff、回执写入是三种不同证据。** 新回执可记录当时真实写入时间并绑定产物；不能给旧回执补造历史时钟，也不能仅凭 mode/NATURAL、DUE 或新的文件 SHA 宣告自然执行通过。

## 二、HK 已部署代码与真实恢复条件

已发布身份来自固定树 `handoff/issue32-mac-recovery-20261009/SCHEDULER_DEPLOYMENT_RESULT.json:8–28` 及独立 `scheduler/reviewer/scheduler-publish-r3/POST_DEPLOY_REVIEW.json:3–37`：

- scheduler app：`/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/issue32-preselection-scheduler-mac-20261009-r1/app`。
- shared package：`/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/issue32-hk-security-master-owner-mac-20261009-r1/app/upstreams/v3_shared_data`。
- 原始修复提交：`9c4b868683a8a4547386cef22354c4f2299c2c26`。Mac candidate 回执对四个 after 文件逐项给出同一 SHA；激活回执证明这组候选所在发布 root 已加载。不是本轮新连 Mac 观察。

| 原模块 | SHA256 | 已核语义与行号 |
|---|---|---|
| `ops/ensure_hk_security_master.py` | `ff03d294128e9fdbe5c319688bea2b8ae1ff1d63afadd51c5a66041e0300321e` | 620–642 先核 exact universe；缺原 authority pointer 的唯一特定错误才可查精确日 panel codes。648–701 先尝试已核原来源恢复/复用；679–680 还验行覆盖和 captured_at。703–716 reuse-only 或过去日期没有原件时明确拒绝。721–749 当前快照采集前后验上海日期，再用原发布器与原读回器校验。767–813 是真实 CLI。 |
| `shared_data/hk_security_master.py` | `2703a97e6ac18c03b06184a482857d303d77d49adaf1561a2c82423dea084847` | 212–244 恢复原件且验证 capture 日期/各行一致；246–318 核来源索引与三件套原字节、不得覆盖目标不同 run、观察到指针变化即拒绝；319–332 同一读取器重验；335–388 exact 日期、run、schema、安全位、artifact/manifest SHA 和行数。 |

以上文件是既有 `handoff/issue32-stage-autorun-fix-20261009-r1/after/source/actual_pool_scheduler/...` 与 `actual_shared_owner/...`，本轮没有修改。

### 真实输入事实的边界

固定 Mac `INPUT_AUDIT.json:2–32`：目标 20261009；价格/资格日期均 20261008；原 master index 共 36 entries、最新确认 20260930、缺 20261008 entry；本地 HK pool 为 0 / EXPECTED_MISSING。检查过配置 shared store、20260923 owner、canonical upstream runtime、20260904 review-core、邻近 backup/archive 以及指定 canary 文件名。**这些有界目录未找到恢复来源；不能推断整个磁盘或外部系统永远不存在原件。**

资格主表索引原路径：`/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data/assets/hk_security_master/latest.json`；当时 SHA `7547d5c65a773ebeb51a81ec0a1ab173dc311ee3009b61088bede48260bcd763`。10/8 价格观察 manifest SHA `a9c75b248d264e2ed78532cbfc1004f8de97b8e8f91c587a66b50f5afa020bee`、panel SHA `785212e96f9f088075800f55dfaf09ef83fccdde7c220e24f9f14d8808db5f90`，这不提供缺失的资格/证券主表。

### 原链恢复步骤（仅当找到真实 10/8 原件）

1. 在原 owner/store/archive 中确认 `latest.entries[20261008]` 指向原 run，原 artifact/manifest/receipt 全在；验证 manifest trade_date、run、同一 universe codes SHA、安全位及三件套 SHA。`captured_at` 必须是带时区的真实采集时间，上海日期为 20261008，各行 capture 与 manifest 相同。不能新生成假索引来包装不完整来源。
2. 用原已部署 ensure 入口的 `--reuse-only --verified-source-store-root <真实原来源根>` 做合法恢复。取值 `--store-root`、`--universe-root`、`--shared-package-root`、`--futu-python` 都来自现役配置/实际脚本，不从旧示例猜测。源/目标 writer 必须在操作窗口内静止。这个参数是原件迁移，不会调用当前行情来伪造历史。
3. 主表通过后，仍须核精确 10/8 价格面板质量/PIT，再由原 HK 0.2 producer 生成 target 20261009 的正式 Top100，沿已发布 materializer/consumer 写入原本地池三件套。缺环节就保留具体失败，不直接改 local pool.status。
4. 由原 Stage `_build_hk_stage_binding` 读回验证 10/9 exact pool，并重新核同一输入身份。只有合法输入才进入该阶段采集与原算法；恢复后首先做隔离单阶段 canary，随后走现有自然调度与既有重试规则，不重置 settled slot。

`--prepare-exact-date --trade-date 20261008` 在 10/9 没有真实历史来源时会明确失败，这是保护而非当前 bug。原 Futu 采集参考 `scripts/acquire_hk_security_master.py:33–55` 使用 `get_market_snapshot`，不是历史主表接口；不得绕过已部署日期 guard 直接调用旧 helper。此参考只说明旧采集实现，非本轮新采集证据。

## 三、10/9 不可启用旧 HK 观察 lane

本轮 actual `stage_center/runner.py` SHA `2dbfa90c42cb4bd3b9b78d20bfbd1ac15eba0f3a18dd1105b32decd04a2b5232`：

- 585–602：目标 HK securities/Connect 日历先验证；**Connect 开市只读目标日 exact pool**，置于 `source_read_lease(target)` 内。
- 604–698：仅 Connect 明确 NON_TRADING_DAY 而 HK securities 开市，才能找 prior Connect session；仍须原 source lease、三件套身份、exact Top100、代码成员一致，并输出观察身份。
- 170–207、215–305：观察 binding 额外校验日期关系、source run、SHA、source date、100 个唯一成员；不是一般旧研究池接入口。

本轮 actual `hk_input_validation.py` SHA `92e8fb2be06e6530c33f3cf2f5b44f29b0bcf7875e6a5902260f8be4c814f735`：31–66 核 source resolver 与三件套前后稳定；75–87 要求 STRICT_0_2_READY 和 100 行；127–171 读取原 store 验权威物理三件套并计算前一 HK price/Connect eligibility session；222–235 验行日期、市场、代码、唯一 Top100。状态字符串满足不代表其余条件满足。

按固定 Stage calendar 的既有合同，20261009 的三市场均开市，前一 HK securities/Connect session 都是 20261008（calendar SHA 在附表）。本轮问题包也明确此日期合同。保持原PIT，不把 9/30 池或今天快照放进观察 lane。

## 四、实际 runner 与可执行入口

### 身份层级

本轮 actual runner 与 10/5 stage variant runner 字节相等；`slot_execution.py` actual SHA `278085fb1effdc9dcf5c5dc9626d68faea0bc53c44f66be4eb89f9a0415fc07a`。但本轮未包含当前 ops facade、tick_planning、deadline、calendar、collectors 或实际 plist/config 正文，所以其 10/5 记录要在 Mac 重核。

| 原模块 | 10/5 同 owner 记录 SHA256 | 入口/接口 |
|---|---|---|
| `ops/run_stage_center_nodes.py` | `8e9ca56aca8a21950590abe83ef305e46a022490eb61f48e0c5d19c2493e1772` | `main()` → `_main_body`；`--config`、`--node`、`--trade-date`、`--evaluated-at`、`--check`、`--deadline-only`。 |
| `ops/_run_stage_center_nodes_parts/node_entry.py` | `f9530f010055476e17d87e93198e28d3f4943ed34255a2419130eb9f39deb6ed` | 503–512 真 parser；586–591 `run_nodes(...explicit_node=args.node)`；350–382 单阶段 dispatch。 |
| `ops/_run_stage_center_nodes_parts/stage_dispatch.py` | `d7ea89f5467fb4d62af6b43c59d9dcd7cfcd020a1ee1ce07a9fae8525f735f86` | 279–435 单 slot lock、回执重读、原 `_run_one`、mode/attempt 后处理，再通过同一 `_write_receipt` 保存。10/8 active Stage source manifest 同 SHA。 |
| `ops/run_stage_center_tick.py` | `4eb8e1a3be0e3780ff9cb62417c695c5aab67948f224db462d3f6e3a67299f42` | 574–632 真 parser；`--stage-id`，最终调用 `StageCenterRunner(config).tick(..., historical_backfill=...)`。 |
| `stage_center/_runner_parts/tick_planning.py` | `c27cb9717ec2940364d1e1186529e6df1b37b07aae0c56f65334f6f9bf06dd15` | 6–17 backfill 输出分别重定向到 `<原输出根>/backfill/<新run_id>`；20–80 单阶段 tick 与锁。该实际参考与 canonical tick helper 不同。 |

本轮 actual runner 在 893–986 暴露 `StageCenterRunner`、`tick(trade_date, evaluated_at, stage_id=..., historical_backfill=False, ...)`；文件结束为 `__all__`，没有 argparse/main。因此 `python -m stage_center.runner --trade-date ...` **不是已存在的 CLI**。

### Mac 最小执行顺序

1. 从 `/Users/lexi/Library/LaunchAgents/com.lexi.stage-center.scheduler.plist` 读取真实 ProgramArguments、WorkingDirectory、配置文件路径，以及实际 app import root。问题包记载 plist SHA `9c7199ca1fcfedc09397255c932d25c6edc15779952bbd5b5bec2671e883d3f5`、config SHA `ef5f49cb4efc35ec76e718415662cece51abb327b6ea7d5ccaa45df2b91869f7`。现场若变，先记录新前像并核差异；不覆盖 pins。
2. 核上述真实入口和依赖 SHA；保留 lexical venv Python 路径（actual RunnerConfig:371–378 明确禁止把 venv symlink resolve 成裸解释器），保留现役启动 flags/import bootstrap。用完整已验 app 建隔离候选并只应用匹配前像的必要 delta；不要用本包 source slice 拼完整应用。
3. 将实际 config 复制到新 canary 区，只将 raw_root、selection_root、receipt_root 指向新独立输出区；所有候选池/行情/原共享来源根保留明确只读绑定。保存 config 前后差分，确认 `candidate_acquisition_root` 读完整 216，HK 仍读精确日权威池。不能拿 `<CONFIGURE_LOCAL_PATH>` 旧示例当真实配置。
4. 在候选 app 对应的完整现役 Python/依赖环境中，按已核模块执行：

```bash
# STAGE_PY / STAGE_APP / STAGE_CANARY_CONFIG 由上述实际读取与候选构建得到。
# 若启动器有必要的 flags/bootstrap，沿用已经核验的原启动方式。
cd "$STAGE_APP"
"$STAGE_PY" -m ops.run_stage_center_nodes --config "$STAGE_CANARY_CONFIG" --check
"$STAGE_PY" -m ops.run_stage_center_nodes --config "$STAGE_CANARY_CONFIG" --trade-date 20261009 --node STAGE_0945_1030
```

这条命令只运行指定单节点（不是 all-node 扫描）。采用实际当前时钟，不补造 `--evaluated-at`。若该 canary 已结算，允许其原幂等规则返回 SKIPPED_ALREADY_SETTLED；另建新 canary 输出而非改旧 live receipt。11:57 后手工验证上午阶段属于恢复/回看验证，不能称自然时段。若当前 app/入口源码不匹配上述身份，先在本机核等价调用合同再执行。

5. 已有结果只读复現：`GET http://127.0.0.1:8873/api/v3/workbench/stage?date=20261009&stage=STAGE_0945_1030&limit=10`。比较 chosen stage 的 A requested/source/selected 行数、market reasons、algorithm ID/SHA、input/source/run/artifact/receipt 身份和真实 recorded_at。该 API limit 最大 50（问题包已确认），不能复用旧 limit=200 查询本端点。
6. 确认真正已有可追溯结果与独立执行证明分开呈现。保存 canary 回执与 raw/selection 实际验证摘要后再考虑原发布流程；后续由自然调度取得新的时段回执，保留手工操作记录，不回填上午 NATURAL 证明。

**历史 flag 差异不能隐去：**参考 nodes parser 虽有 `--historical-backfill`，但它只出现在 CLI 日期拒绝条件，未传给 `run_nodes` 或 runner；不要将它当作隔离历史写入保证。真正沿已有隔离 backfill 路径的是 `ops.run_stage_center_tick --historical-backfill --stage-id ...` → `tick_planning._backfill_runner`。本任务以同日单节点 canary 为主，历史重建仍需真实输入及明确范围，不能据该 flag 扩大执行。

## 五、时钟、数据 cutoff 与回执后处理

| 证据 | 源码事实 | 能证明什么 / 不能证明什么 |
|---|---|---|
| 节点分钟触发 | nodes facade:64–79 定义 09:15 PREP、09:25、09:35、09:40、09:45、10:30、13:15、15:00、15:50 PRECAPTURE、15:55；244–251 在分钟起点后 0–5 秒标 NATURAL。 | 是调度分类；手工调用处于相同窗口也可能得到同字样，不能独立认证 launchd 自然触发。 |
| Stage due | `stage_center/scheduler.py:65–81` 与该 stage cutoff 精确相等才 DUE，晚于 cutoff 是同日 LATE_CATCHUP_REPLAY。SHA `db110aba2fe504213591330000120b660cff04292728b5325711e2fa6799e7b0`。 | 是 evaluated_at 与计划时钟的关系，不能证明实际行情缺失。 |
| 等待到 cutoff | `deadline_supervision.py:6–20`，SHA `95ce916246f3376fc3618c0890ee1f76f2b0231c50d77fe5440a9b956884a674`：最多等 5 秒；sleep 后返回计划 cutoff，未再次读真实 wall clock。node_entry:355–358 据返回值设 NATURAL。 | 可能记录 DUE/NATURAL 而实际醒来有延迟；必须保留 entry/parent wall 与实际采集时间，不用该字段合成自然证明。 |
| A 数据 cutoff | 同 owner 10/5 `tdx_minute_replay_provider.py:127–144` 核真实当前上海日、精确 target/cutoff 并截断阶段分钟窗口；竞价 205–279 读 exact 09:25，真实 captured_at 晚于 cutoff 就标 RECOVERY。SHA `02d7505614b66768f6c3f6b86e4e606f0df9f4fabb6aaad5ea8f8a0fa3738260`。 | 晚调用仍可能有合法 cutoff 内历史行情；其回看身份必须保留，不能冒充自然 live 快照。 |
| A 竞价 reader | `_live_collectors_parts/a_auction.py:91–126` 核 temporal_cutoff_safe、各安全位、capture_mode、market_cutoff；149–159 只收目标 09:25:00 tick。SHA `2b39ede48161e6be59efc769849a8da2319521faeac3f2985b82de508e7c6aef`。 | reader 不可只相信晚启动/自然字样，仍需其数据时钟/来源合同匹配。当前 collector bytes 尚待本机核对。 |
| 运行耗时 | `end_to_end_deadline.py:18,26–92` 观测 monotonic 五秒；默认 observe/enforce取实际配置。summary 明确 `natural_verified=false`、`business_success_verified=false`；entry anchor不含完整解释器启动，父级需独立核。SHA `f25d91cf1eaf4ea7d1a9a57fc1f8288d14d98536a63dee16467550974b2a812e`。 | 时间预算合格不等于数据PIT或自然触发合格；此模块不硬中断 native/provider 阻塞。 |

本轮 actual `contracts.py:60–68`（SHA `6880f6a82c7f4fb0fde5c0661bd5a8bb12b590661a4b8552bcb3d6be969ae83d`）cutoff 保持：09:25:05、09:35:05、09:40:05、09:45:05、10:30:00、13:15:00、15:00:00、15:55:05。HK 竞价使用独立 09:20:05（actual slot_execution:589–608）。

回执补丁需要覆盖外层最终后处理：参考 Stage dispatch 279 取原 slot lock，293–295 重读 receipt，367 `_run_one`，386–423 添加 mode/attempt/retry；427 再 `_write_receipt`，428–431 `deadline.complete_receipt` 的 rewrite 仍调用同一 writer，435 才释放锁。不可仅给 inner result 算一个 SHA 然后让外层改 body。`tick_planning:64,72` 的 non-due/lock-conflict 也可写 receipt，不能复用旧成功的执行绑定；deadline 可能将结果降级或返回 pending metadata，须保持这些原因。

## 六、本机仍须核的定点依赖

本轮已给 actual 核心源码，足以做局部 writer/API 字段修复和精确函数级测试；以下缺口是现场集成/执行验收，不应成为重写算法或停止全部源码工作的理由：

- 实际 Stage plist argv/config 内容及 env 白名单、当前 ops nodes/tick/node_entry/stage_dispatch/tick_planning/deadline/calendar 文件 SHA；以相同路径的 10/5/10/8 身份作对照。
- 当前 collector / tdx replay provider、selection store / raw store / actual consumer 的所需直接依赖；依据已给完整 app 复核，禁止用历史 canonical 拼合未审完整树。
- 真实 10/8 master 原三件套及原 capture 身份；真实 10/8价格/PIT；10/9 shared Top100 → local verified pool → Stage binding，当前为 **BLOCKED**。
- 8873 当前加载后端和前端 bundle 身份；单阶段 API/UI同一产物读回；未来自然时段实际触发与采集/结果/回执绑定。

本只读分工终态：`READ_ONLY_SOURCE_AUDIT_COMPLETE`；HK真实输入 `BLOCKED`；新采集/执行/部署/API/UI自然验收 `NOT_RUN`。保留 research-only任务边界和三个 false 安全位；Mac回执未暴露 `RESEARCH_ONLY` 环境字段的事实仍为字段级 CANNOT_CONFIRM。
