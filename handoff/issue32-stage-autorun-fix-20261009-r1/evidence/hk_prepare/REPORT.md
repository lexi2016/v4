# Issue32：HK 原 owner 精确日期准备候选

## 结论与范围

基线为 `b00ca5a658a9de83cf5e54ad39aa68ddd5c23526`。本候选修复原有准备入口的受控采集、精确来源恢复和失败诊断；**不代表 2026-10-09 港股输入已经就绪**。本轮没有真实业务源、没有访问 OpenD、没有更新真实数据、没有发布服务、没有 GitHub 写入。所有测试股票和时钟均为合成数据。

目标保持 `target_date=20261009`、价格日 `20261008`、资格日 `20261008`。10/8 的价格 10/7、资格 9/30 分日期历史故障没有套用到本目标。

四个源码文件的精确前后 SHA 与字节数见 `SOURCE_DELTA.json`。原输入未修改。实际共享 owner 的 `hk_0_2.py` 和 `materialize_hk_0_2.py` 没有改写；排名、Top100 数量、原模型、原 Stage 合同保持原样。

## 已核实故障链

1. 交接状态明确 `hk_security_master/latest.json` 仅有截至 20260930 的 36 个日期，缺 `entries["20261008"]`；旧 loader 直接索引该键，错误被压成 `metadata invalid: '20261008'`。
2. 实际旧 executor 运行 `ops.ensure_hk_security_master --reuse-only`。实际 ensure 已有原 owner 采集分支，但该模式不进入采集。实际 executor 还会在准备步骤失败后继续尝试评分；配对 executor/dispatcher 修复由独立任务交付。
3. 可见实际 ensure 通过 `scripts.acquire_hk_security_master` 取得原 resolver、collector、publisher。collector 调用签名只有 Python 路径和代码列表，没有历史日期参数。
4. 额外取得的 **10/5 历史 canonical 参考**明确使用 `get_market_snapshot`，只投影参考字段，发布时传入当前 capture 时间；因此它不能在 10/9 生成一份合法的 10/8 历史快照。参考 SHA 为 `9d65e7016df3529f10c34a9532da3b2ac9236c4446a3bf7adea1531281e6c6ad`，没有证明实际 current collector 与参考同字节，不作为部署源。
5. 原 canonical 共享 master 已有 `restore_verified_hk_security_master`；实际旧共享 owner 没有。本候选移植该原 owner 方法，并补上复制身份与时间边界检查。

## 最小行为变化

### 原 ensure 入口

- 新增显式 CLI `--prepare-exact-date`，与 `--reuse-only` 互斥。配对 executor 使用新参数；旧 ensure 不识别新参数时会退出 2，避免仅删旧参数导致旧版本静默调用不受日期约束的采集。
- 顺序为：验证精确日期 universe → 验证/复用本地 master → 可选恢复显式指定的已验证源 → 原当前快照 collector → 原 publisher → 原 loader 读回完整三件套。
- 新增 `--verified-source-store-root PATH`，只接受操作者已经定位、核实的原 owner 精确日期 source store。不会搜索、猜测、生成或改标来源。
- 原当前快照 collector 只允许请求日期等于采集开始时的 `Asia/Shanghai` 日期，并在 collector 返回后再次核对。历史、未来或跨午夜采集均在 publication 前失败，不写目标 master。
- `--reuse-only` 仍可用于只验证或从显式 verified source 恢复；该模式永不调用 Futu collector。普通已有 master 的 reuse 同样校验 capture 必须带时区、上海日期等于请求日期、所有行 capture 等于 manifest；无效旧源立即拒绝，保持原字节，不回退重采。
- 成功继续返回 JSON `ok=true,status=READY`、退出 0，并提供 master 的 run/artifact/manifest SHA。失败继续返回 JSON `ok=false,status=FAILED,error=...`、退出 1；缺历史源报 `HK_SECURITY_MASTER_NEEDS_VERIFIED_SOURCE` 和请求日期。
- 原直接调用 `capture=` 分支并非本 CLI 的采集路径。本轮不以其无历史采集时间合同的 v1 envelope 做历史回填，也不改造 canonical 现有 v2 membership 流程；只禁止把 capture 和显式 source restore 混用。

### 原共享 master owner

- 缺日期时报 `HK_SECURITY_MASTER_EXACT_DATE_MISSING: trade_date=...; available_max_date=...`，不回退旧日。
- loader 补校验 receipt 的 `trade_date` 与请求日期一致。
- 恢复前要求源 manifest 为指定日期，capture 为带时区时间且上海日期等于该日期，行 capture 与 manifest 相同；源三件套须通过原 loader 的身份、SHA、安全 flag 检查。
- artifact/manifest/receipt 保持原字节、run id、capture，不重建表或重写历史时间。same-root 或重复恢复时，已相同的日期 entry 不重写 pointer，保留原格式与 SHA。既有其他日期保留；目标已有不同 run、冲突不可变文件、源身份变化或已观察到目标 pointer 变化时拒绝。
- 不可变文件采用已 fsync 的同目录临时文件加 `os.link` 排他创建，遇到介入创建的不同文件不会覆盖。
- 复制后、发布 pointer 前重新校验源、源 pointer、源与目标三个文件字节；发布后由原 loader 读回。中断复制可留下未被 pointer 引用的同字节文件，但不提前发布 `entries[date]`，可按原路径恢复重试。
- **恢复操作要求原 source/target owner writer 处于静止状态。** 旧 publisher 没有共同写锁；本候选检测已观察到的 pointer 改变，但不是并发事务，最终检查与 pointer 写入之间仍需运维侧排他。没有新建全局锁或改动其他 producer。

## 实际 owner 与 canonical 映射

| 候选相对路径 | 本机实际集成位置/身份 |
|---|---|
| `source/actual_pool_scheduler/ops/ensure_hk_security_master.py` | `/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260929-manager-1555-pytdx-r1/app/ops/ensure_hk_security_master.py`；只应用该实际前像的差异 |
| `source/actual_shared_owner/shared_data/hk_security_master.py` | `/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260923-hk02-owner-rebase-r2/app/upstreams/v3_shared_data/shared_data/hk_security_master.py` |
| `source/canonical_reference/ops/ensure_hk_security_master.py` | `/Users/lexi/Desktop/学习/v4_app/ops/ensure_hk_security_master.py` 的对应最小差异；保留其现有 v2 membership 代码 |
| `source/canonical_reference/upstreams/v3_shared_data/shared_data/hk_security_master.py` | `/Users/lexi/Desktop/学习/v4_app/upstreams/v3_shared_data/shared_data/hk_security_master.py` 的对应差异；不是拿实际旧文件覆盖 canonical |

实际 executor 的 `--prepare-exact-date` 与上述实际 ensure 必须配对；canonical split executor 也只应用自己的差异。恢复所加载的 `shared_package_root` 必须确实加载已更新共享 owner，不能仅修改 canonical 而运行旧实际 owner。

## 明确缺失的依赖与真实数据

以下不是本包完整当前闭包，不能据历史参考拼装部署：

- 实际当前 `scripts/acquire_hk_security_master.py`，及其 `scripts/acquire_stage_raw.py`、`scripts/live_acquisition/universe.py` 与传递依赖；历史参考只能说明一个已存在采集实现的行为。
- 实际 `infrastructure/isolated_package_loader.py`，shared `hashing.py`、`paths.py`、`store.py`、HK producer 所需 `allowlist.py`、`consumer.py` 等；测试使用明确标注的合成导入边界，未证明运行模块身份。
- 实际 `scripts/update_hk_0_2_panel.py`、当前 resolver 的 universe authority、Futu Python/OpenD 依赖、HK 冻结模型/运行时、TDX `vipdoc/ds/lday/71#*.day`、panel/model pointer 与 manifest/artifact。
- 原共享源中 **真正捕获于 10/8** 的 master artifact/manifest/receipt 和相应精确索引；本次没有该来源，不推断任何备份 root 存在。
- 独立的 10/8 价格面板刷新结果、panel SHA、合格覆盖与评分 run。可见原 updater 要求至少 500 代码、当前新增日非零交易与金额覆盖率至少 80%；这些真实值均未执行核验。
- 当前本地池 converter 与 `ops.materialize_scheduled_preselection`/pool store 闭包。原共享 producer 当前只输出/绑定 `signal_date` 与同日 master；局部 API 同日分支需要 envelope 明确携带 `price_signal_date=eligibility_source_date=20261008`。缺 converter 源码，不能证明新 pool 中这两个字段存在及上游三件套身份被正确复制。

## 本机合法准备步骤（本轮 NOT_RUN）

下列变量必须取自本机已核实的实际 owner 配置，而非候选或历史快照推测。`ISSUE32_VERIFIED_SOURCE_STORE` 只能指向已核实的真实 10/8 来源；如果不存在，目标维持 BLOCKED。恢复期间由本机在已授权范围内保证原 owner writer 静止。本轮没有启停服务。

先沿原价格 owner 准备精确 10/8 面板；以下命令来自实际 executor 的既有调用，入口文件本包缺失，须由本机闭包核验：

```bash
cd "$ISSUE32_SHARED_PACKAGE"
"$ISSUE32_HK_PYTHON" -m scripts.update_hk_0_2_panel \
  --asset-root "$ISSUE32_SHARED_STORE/assets/hk_0_2" \
  --tdx-root "$ISSUE32_HK_TDX_ROOT" --through-date 20261008
```

有真实精确来源后，通过原 ensure 恢复并读回；`--reuse-only` 保证不会把现在的市场快照当作 10/8：

```bash
cd "$ISSUE32_POOL_APP"
"$ISSUE32_SCHEDULER_PYTHON" -m ops.ensure_hk_security_master \
  --store-root "$ISSUE32_SHARED_STORE" \
  --universe-root "$ISSUE32_UNIVERSE_ROOT" \
  --shared-package-root "$ISSUE32_SHARED_PACKAGE" \
  --trade-date 20261008 --futu-python "$ISSUE32_FUTU_PYTHON" \
  --reuse-only --verified-source-store-root "$ISSUE32_VERIFIED_SOURCE_STORE"
```

主表和价格都独立 READY 后由原 producer 生成，不能在前两步失败后把空占位当池：

```bash
cd "$ISSUE32_SHARED_PACKAGE"
"$ISSUE32_HK_PYTHON" -m scripts.materialize_hk_0_2 \
  --store-root "$ISSUE32_SHARED_STORE" \
  --asset-root "$ISSUE32_SHARED_STORE/assets/hk_0_2" \
  --signal-date 20261008 --target-date 20261009
```

然后由现有 scheduler/local converter 生成本地池，分别核验上游 artifact/manifest/receipt 与本地池 snapshot 三件套；不得用本地 SHA 替换上游身份。真实单阶段 canary、完整 API/UI 与自然 slot receipt 由本机独立验收，不能用这份源码测试代替。不要删除或重置历史 settled slot。

对未来正常工作日，配对 executor 的 `--prepare-exact-date` 会沿既有 resolver/collector/publisher 自动准备当日 signal-date 输入；若延迟到次日才采集，则明确拒绝，并要求真实原始源恢复。

## RED → GREEN 与实际验证

测试环境：Linux x86_64，Python 3.14.7，运行路径 `/workspace/scratch/25c09a595aec/issue28/references/work/test-venv/bin/python`。这不是 HK 模型固定 Python 3.13.12 运行环境；本轮没有执行评分模型。

生产修改前先运行 `tests/test_hk_prepare_restore.py`：20 failed / 4 passed；已存在 canonical restore 的正常行为通过，缺实际 restore/CLI、缺日期错误、receipt 日期漏校验和 capture 边界按预期失败。新增原当前采集日期 guard 先得到 10 failed；live publish 读回故障注入先得到 2 failed；排他文件创建与 pointer 竞态故障注入先得到 8 failed。完整失败证据保留在上级 `hk_prepare_*red.txt`。独立复查又发现 ordinary reuse 绕过 capture 检查；复查先得到 6 个失败，本任务追加行 capture 与同根 pointer 原字节探针先得到 10 个失败，再完成修订。新增 RED 见 `../hk_prepare_reuse_review_red.txt`，独立原 RED 记录没有覆盖。

最终定向测试：

```bash
/workspace/scratch/25c09a595aec/issue28/references/work/test-venv/bin/python -m pytest -q tests/test_hk_prepare_restore.py tests/test_preselection_executor_prerequisites.py tests/test_dispatcher_receipts.py --tb=short
```

最终复查修订结果 **80 passed**，其中 HK 准备测试 58、配对 scheduler/dispatcher 测试 22。覆盖正常 exact restore、源/目标冲突、源篡改、非同日/无时区 capture、same-root/重复恢复、复制中断、读取回执缺失、before/after collection 日界、CLI JSON 与安全 flag，以及配对调度门禁。最终证据 `combined_green_r2.txt`（原 70 passed 保留在 `combined_green.txt`）。另将独立复查原文件与本任务合跑，64 passed = 本任务 58 + 独立 6。

按技能要求初次执行无路径限制的 `python -m pytest -q --tb=short` 时，测试边界尚未配置，scratch 中另一独立 API harness 被错误地一并收集，退出 2。该原始失败保留；五个错误是：

- `work/api_combined_r1/isolated/preselection/tests/test_api_same_date.py`：与顶层同名模块 import file mismatch。
- `.../test_issue28_preselection_hk_fallback.py`：缺 `contracts`。
- `.../test_issue30_preselection_module.py`：缺 `infrastructure`。
- `.../test_preselection_review_probes.py`：缺 `infrastructure`。
- `.../test_preselection_source_root_20261008.py`：缺 `contracts`。

另有 FastAPI/Starlette 的 httpx 弃用警告。完整原输出见 `whole_scratch_pytest_collection.txt`。这些独立 harness 的正确启动方式由对应任务交付，本任务没有改它们的导入设置。主控随后为正式候选包配置 `testpaths=tests`；本任务复查后重新运行同一裸 pytest 命令，**111 passed**，证据 `whole_package_green_r2.txt`。此结果仅代表正式候选源码包，不能扩大为完整实际 app 的测试通过。

## 状态边界

| 验证层 | 状态 |
|---|---|
| 本任务最小源码候选与合成回归 | PASS（58 HK / 80 联合定向；另独立 probe 6） |
| 正式候选包默认测试命令 | PASS（111）；此前未配置边界的 scratch 收集 FAIL 原证据保留 |
| 实际当前 owner 完整导入闭包与采集 | NOT_RUN / 缺依赖 |
| 真正 10/8 master/价格与 10/9 上游 Top100 | BLOCKED / 未提供真实输入 |
| 本地 converter、Stage 输入来源复制 | CANNOT_CONFIRM |
| 本机独立验收、部署、完整 API/UI、自然 slot | NOT_RUN |

`production_allowed=false; buy_gate_updated=false; orders_sent=false` 全部保留。
