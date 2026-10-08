# Issue #28 · HK 原 producer 分日期绑定候选

## 结论与适用范围

**两个实际 producer 前像已完成最小修复，离线定向验收通过；这两个文件单独部署不能解除当前 HK 阻断。** 当前实际 caller、共享来源 owner、calendar/store 完整运行依赖以及真实 10/7 价格原件均不在交接包中。Luna 必须在原 owner 上补齐身份核对与调用参数后，才能进行后续集成验收。

本批以冻结 commit `00524e9050fe212f87911b56eea1c2db719dd94b` 为基准，仅修改 `source/active_producer_reference` 对应的两个文件。它们属于交接所标识的 `hk-research-calendar-all-r1-20261007-scheduler/app`：原 materializer 保持单文件结构。没有把较新的 canonical split-module 整文件覆盖到运行 monolith。

| 分层 | 结果 |
|---|---|
| 候选实现 | PASS：两文件补丁、精确前后像、源码清单均已提供 |
| 本批离线定向测试 | PASS：55 项；所有行情行、分数与 capture 值均为明确合成 fixture |
| 冻结前像反证 | 3 FAIL / 2 PASS；失败在候选上均转为 PASS |
| 补丁正向/反向重放 | PASS：逐文件重建精确 after/before 字节 |
| 原 Stage 严格 validator | PASS：原函数体校验合成持久化三件套；正文和校验分支均未修改 |
| 完整实际 owner 导入、自然 scheduler、模型评分、业务补采、完整 Stage selection | NOT_RUN |
| Mac、部署、实际业务产物、8873 API/UI、自然时段/PIT 验收 | NOT_RUN；当前 HK 业务闭环仍 CANNOT_CONFIRM |

`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。

## 实际前像与候选 SHA-256

| 实际相对路径 | Before SHA-256 | After SHA-256 |
|---|---|---|
| `domains/preselection_materializer.py` | `f090146f39eaaf1ea5baaa5da60cddc2aefe738be16eb1609f166b643953d84e` | `1187afe30c1f0614ddcd33f52eb3d82511d98ffe62b3fa5d4bf02f661b1ef290` |
| `ops/materialize_scheduled_preselection.py` | `2aac77c9a995c8e97488be5324e8dd105e19e68a08bfb71cceb2df670aaa5478` | `e8f412ae44ceb708fb4480a3d20906cfbf057051e14ec49bb70efbca0b82b638` |

完整字节数、SHA-256、Git blob SHA-1 和冻结仓库相对路径在 `SOURCE_IDENTITIES.json`。其中 `before/` 是包内实际 producer 前像；`after/` 是本批候选；`support/` 是只为离线验收提供的 canonical/原 validator 依赖，**不能据此断言这些文件就是当前实际 scheduler 的共享 owner 或运行依赖**。全部原引用字节已按冻结 Git tree 核对。

## 断点和修复

交接已观察到目标 10/8 HK 文件有 100 个代码，但行级价格日期都是 9/30，且缺少分日期来源链。冻结前像可用合成 fixture 重现：旧 CLI 只传 `trade_date=20261008, signal_date=20260930`，旧 adapter 将有 100 行的共享池映射成 `STRICT_0_2_READY`；原 Stage 随后拒绝 `HK D1 split-date eligibility provenance missing`。

本批将原路径接成以下合同：

| 层 | 必须绑定的值 |
|---|---|
| HK 目标日 | `20261008` |
| HK securities 价格信号日 | `20261007` |
| HK Connect 资格来源日 | `20260930` |
| A 原调用日期 | 保持独立的 A `trade_date` / `signal_date`；不从 A 日期推断 HK 价格日 |

1. **原 ops 接收三项独立 HK 参数。** 缺任一项时，HK 生成有明确原因的零行 `CANNOT_CONFIRM`，有效 A 仍物化。原 caller 必须显式传全三项；不能继续使用旧调用后期待自动解除 HK 阻断。
2. **使用原 `contracts.trading_calendar` 校验显式日期。** 目标必须为确认的 HK securities session，价格日与资格日分别等于该目标的 securities / Connect 前一 session。格式错误、错资格日、自洽但旧的价格日、未知年份或缺失日历均拒绝 HK readiness；不硬编码 10/8，也不新建日历来源。
3. **原 monolith 将资格日传入原共享 reader。** `expected_signal_date=20261007` 与 `expected_eligibility_source_date=20260930` 同时校验。较老 reader 不支持该签名时返回可识别的输入合同错误，不回落到旧 reader 参数。
4. **只从已核验来源投影 provenance。** 新产物绑定来源 run、artifact-relative、artifact SHA、manifest SHA、receipt SHA，连同原资格 run / artifact SHA / capture 值。保留 source 内的时间精度和时区；不生成原始 capture 或 PIT 证明。拒绝非 READY、foreign root、foreign owner/role/date、不完整来源以及资格 capture 日不符。
5. **封闭 HK reuse 旁路并保持 A 独立。** 即使使用 `--reuse-formal-pools`，仍先调用原共享 reader；只有已存对象与这次已验证的完整投影一致才可复用。旧日、缺 provenance、foreign run/SHA 或不同 rows 仅将本次 HK lane 标为零行 `CANNOT_CONFIRM`，带 `HK_0_2_REUSE_CONTRACT_INVALID` 原因，不抛出全批异常。A 缓存尚不存在时仍由原 A builder 正常生成；HK 复用文件缺失或无效也只影响 HK。
6. **拒绝的 HK 槽不写回，A 正常物化。** `main` 对本次拒绝的 HK 输出明确 `reused=false`、`NOT_PUBLISHED_EXISTING_SLOT_PRESERVED`，继续物化有效 A 和其余 lane。既不将新来源冒充复用成功，也不把缺失 placeholder 覆盖到旧 HK 槽。原 HK artifact/receipt 字节与共享日期 manifest 的 HK 条目保留；日期 manifest 可正常增加新 A/其他 lane 条目。这个状态是本次 producer 的隔离结果，不代表已经修复或移除了原存储中的旧 HK 输入。

等日直接 adapter reader 调用保持兼容；合法分日期输出与包内 canonical 的既有投影逐对象相等。原严格 Stage validator SHA 仍为 `92e8fb2be06e6530c33f3cf2f5b44f29b0bcf7875e6a5902260f8be4c814f735`。

## caller → shared owner 的证据边界

实际包只冻结了上述 ops 与 monolith，**没有当前实际 `FixedExecutorRegistry` 执行主体、共享 producer 脚本或绑定配置**。冻结仓库中的 `handoff/hk-close-hk-calendar-20261007/scheduler/ops/run_scheduled_slot.py` 只构造 `DispatchRequest` 并实例化 registry；它不是完整的当前 executor 前像。

补充参考 `handoff/v4-running-source-20261005/canonical/infrastructure/scheduling/_executor_registry_parts/preselection.py` 展示已有的正确来源链：`scripts.update_hk_0_2_panel` 使用 HK 价格截止日；`ops.ensure_hk_security_master` 使用资格来源日；`scripts.materialize_hk_0_2` 使用价格/资格/目标三日期；最终 `ops.materialize_scheduled_preselection` 再携带同一三日期。该参考不是本批实际 caller，也不能直接覆盖它：例如参考还传递 `--market-scope`，而此次修复的旧 ops 没有接收该额外参数。

canonical `shared_data.hk_0_2` 已有 `materialize_frozen_hk_0_2(... eligibility_source_date=...)`、`publish_hk_0_2_rows(...)` 和严格 `read_verified_hk_0_2_pool(...)`。离线 fixture 使用这些原函数，不新建 producer；不运行冻结模型打分，不运行 TDX/Futu 采集。

## 可重复验证

在可用的 Python 3.11+ 环境中安装 pytest 后，运行：

```bash
python run_tests.py --mode all --log-dir /tmp/issue28-hk-review
```

脚本先校验清单内 36 个文件，再正向/反向重放补丁，然后在独立 Python 进程运行 before 与 after。before 的预期结果是 **3 FAIL / 2 PASS**，不是要求把红色基线变成绿色；after 的预期结果是 **55 PASS**。所有合成来源与输出均在 pytest 临时目录，不需要业务根、Mac 或网络。

本轮实测命令和环境：

```bash
/workspace/scratch/25c09a595aec/issue28/references/work/test-venv/bin/python \
  delivery/hk/run_tests.py --mode all --log-dir delivery/hk/logs
```

Python **3.14.7**、pytest **9.1.1**、Linux x86_64/glibc 2.39。该复制测试环境的只读 base interpreter 来源路径在 `logs/RESULTS.json` 中如实记录；不是 Mac 生产评分环境。`logs/before.log`、`logs/after.log` 和 `logs/RESULTS.json` 保留实际命令、限定环境变量、结果和日志 SHA。

验收覆盖：合法三日期 / 原 source 三件套不变 / 原 Stage 接受；旧价格、错资格日、foreign root/owner/role/目标日期/资格 run、trio 篡改、缺 provenance/来源 SHA、非 READY、错误 capture、缺参/partial 参数、旧 reader、reuse 旁路、日历缺失/unknown。A 旁路验证使用实际未改 A adapter，仅 upstream reader 为合成 fixture；通过真实 store 读回的 A artifact 仍 `stage_selection_eligible=true`、`source_merge_role=MAIN_STAGE_INPUT`。完整 A Stage selection 未在本 harness 执行。

### 独立审查发现的 reuse 隔离缺陷已修正

本批第一版 ops 候选 SHA `25623e0ddd684a9e400aeaea5b9911ff35da7c615bdf3e288dd1fbd76874d331` 在 HK reuse 不匹配时全局抛错，违反 A 有效来源独立处理的合同。原测试要求全局异常的断言也不正确，已改成必须返回有效 A 和 HK-only CANNOT_CONFIRM；另外新增 4 个实际 `main` 测试，覆盖旧价格、缺 provenance、foreign 来源和 HK artifact 缺失时，A 尚无缓存仍可新物化，以及旧 HK 字节/条目不被覆盖。

同一组 8 项定向检查在被拒第一版候选上 **8 FAIL**，修复后完整 **55 PASS**。旧候选反证见 `logs/reuse_isolation_red.log`；`hk_reuse_isolation_review_fix.patch` 是该已拒第一版到最终版的精确增量，仅用于审查重放，不替代主补丁。`logs/REUSE_REVIEW.json` 记录旧/新 ops SHA、最终测试 SHA 与反证日志 SHA。

需要重放审查红色结果时，在本目录运行以下离线命令；临时目录中的 ops 应重建为上述 `25623…` SHA：

```bash
hk_review_dir=$(mktemp -d)
cp -R after/active_producer_reference/. "$hk_review_dir/"
git -C "$hk_review_dir" apply --reverse "$PWD/hk_reuse_isolation_review_fix.patch"
HK_OWNER_ROOT="$hk_review_dir" \
HK_BEFORE_OWNER_ROOT="$PWD/before/active_producer_reference" \
HK_SUPPORT_ROOT="$PWD/support/canonical" HK_FROZEN_ROOT="$PWD/support/frozen" \
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  tests/test_hk_split_date_binding.py \
  -k 'reuse_quarantines_bad_hk or actual_cli_rejected_hk_reuse'
```

旧 scheduler 的整体 formal-pair 返回码仍会在 HK 未就绪时为 1；它不再阻止本次有效 A 物化。测试证明 A 产物已经独立持久化并保有阶段输入资格。原 Stage 的逐市场选股、自然调度是否实际消费该 A 输入仍需单独验收；对被保留的旧 HK 槽也不能据 producer 本次完成 A 而宣称该槽已经可用于选股。

## Luna 后续必须补齐的具体依赖

- 在实际 scheduler owner 中定点读取并记录 caller 的路径、SHA、模块加载根和绑定配置，核对 `shared_package_root` / `shared_data_root` / HK 原资产根。只在实际 caller 对应分支做最小参数合并，显式向两个原 materializer 传递目标 `20261008`、价格 `20261007`、资格 `20260930`。
- 定点核实际共享 `scripts/materialize_hk_0_2.py`、`shared_data/hk_0_2.py`、consumer/store/security-master 依赖及原 reader 签名。当前包仅有 canonical 参考，不能将其当作运行前像整体覆盖。实际 pool store 还须支持本候选输出的已有 provenance 合同和精确三件套读写。
- 定点核实际 `contracts/trading_calendar.py` 和 `contracts/market_calendar_2026.json`。测试 JSON 来自冻结仓库，SHA `9e2638b69e25495478cecb6ed551713178fcb989a63ebb4ecfd59689615f0acb`；实际 owner 文件身份仍待核。日历依赖无法确认时保留 HK CANNOT_CONFIRM。
- 在原共享 owner 上只读核真实 10/7 原 panel/raw 的确切日期、原来源 SHA / manifest / receipt、模型约束，以及真实 9/30 资格 master 的 run / artifact / manifest / receipt / capture。**这些原始来源未随包提供，不能据本包断言它们在本机不存在。** 若原始捕获证据缺失，继续报告缺口；今天重新获取的数据不能冒充 9/30 capture 或 10/7 当时 PIT。
- 后续授权的隔离集成应由原完整 Stage 先用合法新三件套执行单阶段 canary，再对实际 selection run / artifact / SHA 与 8873 API/UI 逐项读回。输入缺失时仍没有合法 selection run，不能将执行层声明的 0 升格成真实空选；合法输入后的 0 只有经实际 selection 产生才可认定。

本轮未执行上述业务动作。旧 10/8 artifact / manifest / receipt 全部保留；没有在旧产物上补日期、补 provenance 或改状态。

## 应用与回滚边界

`hk_split_date.patch` 仅以两个准确 before 文件为基线。Luna 在独立候选目录逐项核 before SHA 后，才能应用补丁；先补齐上述 actual owner 依赖并独立复验，再进入现有发布流程。本包不授权切换活动 release、业务补采或自然任务重跑。

源码回滚仅在确认仍为本候选 after SHA 的独立目录反向应用同一补丁，并逐项读回 before SHA。不能对漂移工作树盲目反向 patch，也不能用源码 rollback 改写已有业务产物。活动服务回滚属于既有 owner 的发布流程，不由这份代码补丁执行。
