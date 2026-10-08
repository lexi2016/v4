# Issue #28 历史 P2 增量交接 · 2026-10-08

**本批完成两项有明确原合同的源码修复：历史来源日期上界、收盘复盘缺来源时的 PIT 不确定标记。嵌套 provenance 未知字段 P2 仍未解决，原失败探针和所缺原始合同已保留。**

这是上一批 R1 之后的独立增量。两份产品后像、完整前像、最小补丁、定向测试和独立复审证据均在本目录。它是待本机 owner 适配的源码交接；实际 Mac 集成、部署、API/UI、真实历史数据恢复和自然运行均未执行。

## 入口与固定身份

- 总工单：[lexi2016/v4 Issue #28](https://github.com/lexi2016/v4/issues/28)。范围依据为[冻结说明第 7 节](https://github.com/lexi2016/v4/blob/00524e9050fe212f87911b56eea1c2db719dd94b/handoff/stage-selection-issues-20261008/README.md)。
- 产品前像冻结 commit：`00524e9050fe212f87911b56eea1c2db719dd94b`。
- 本次 Git 提交父节点：[上一批 R1，d8485e92bed685a1dc38a1f40a05858b9be4765c](https://github.com/lexi2016/v4/commit/d8485e92bed685a1dc38a1f40a05858b9be4765c)。R1 目录和冻结来源保持原字节。
- 本次独立分支：`chat/issue28-historical-p2-20261008-r1`。
- 本次新增仓库目录：`handoff/stage-selection-historical-p2-20261008-r1`。
- 精确同步 commit、tree、全部文件远端比对和关键文件内容读回记录在下载包的 `GITHUB_SYNC_RECEIPT.json`；该回执在提交后生成，不参与提交内清单的自引用。

本次开始时的 Issue 读回仍为 0 条评论，未提供新增 Mac 验收；[REMOTE_START_CHECK.json](verification/REMOTE_START_CHECK.json) 记录采样时间和父提交身份。已有并行分支不能当成本机验收，也未被合并或覆盖。

## 1. 本次具体修复

| 原历史 P2 | 本批结果 | 行为与边界 |
|---|---|---|
| provenance 日期未限制不晚于目标日 | **源码修复并独立验证** | 两种历史 schema 都拒绝未来 eligibility 或 price 日期；允许日期等于目标日，保留合法分日期来源 |
| 嵌套 provenance 未严格拒绝未知字段 | **DEFERRED，仍有 2 个实际失败探针** | 缺少完整原 producer/schema 及恢复输出的字段合同，不用最小 fixture 或 consumer 字段访问拼出白名单 |
| 8/25 类旧池输出缺明确 source/PIT 标记 | **通用缺证据分支修复并独立验证** | 缺 source manifest SHA 或 receipt SHA 时追加已有原因；实际 8/25 原产物未提供，不宣称恢复了该日数据 |

### 历史来源日期

`infrastructure/preselection_pool_store.py` 只增加三行上界检查。外层原 validator 已验证必填 `trade_date`；可选 `target_date` 存在时必须与它相等。两个 provenance 日期均已转换为合法的 `YYYYMMDD` 日期，因此比较的是来源日与产物目标日。

```python
target_date = _date(str(payload["trade_date"]))
if eligibility_date > target_date or signal_date > target_date:
    raise ValueError("historical pool source date exceeds target date")
```

没有增加严格 D-1、交易日历或 capture-time 截止要求。原 `20260930` 历史目标、`2026-10-02T14:02:56+08:00` 捕获的恢复样本仍可读，原 capture time 和 false 标记保持。这不放宽 Stage 自己的晚采样拒绝，也不授予 PIT 或自然执行资格。

### 收盘来源/PIT 标记

`ops/build_close_review.py` 保留已有 `historical_provenance` 分支，并在 `source_manifest_sha256` 或 `source_receipt_sha256` 任一缺失时，向 `cannot_confirm` 追加一次已有原因：

`HK_MODEL_SOURCE_PIT_AVAILABILITY_CANNOT_CONFIRM`

完整普通来源 SHA-pair 的输出与前像逐字段相同；这只是兼容性证明，两个 SHA 的存在本身不构成完整 PIT 认证。模型行、KPI、schema、status 计算和安全标记仍由原合同决定。本次没有新增日期硬编码或补写 provenance/capture/run/source SHA。

仅原来精确的“没有该模型池” sentinel 会转为模型来源缺失。除这一 sentinel 外，其余文件缺失或损坏异常继续传播；receipt 或 manifest 缺失不会被转为空池。已有复盘的只读入口保持原字节；显式重建仍采用原 `ReviewStore.publish_native` 的 expected-SHA/CAS 规则。

## 2. 产品前后 SHA

本次只有 **2 个产品文件**改变。原路径均是工单冻结的 canonical 切片；它们不能代表当前 Mac 进程实际加载身份。

| 产品路径 | 完整前像 SHA-256 | 完整后像 SHA-256 |
|---|---|---|
| `infrastructure/preselection_pool_store.py` | `028298a05ea44e310487c1159acc8147cf652e23ba716989135b178198795a92` | `9f1606a977d36c063d9c650e54b9861947eb7b692e779837852e3831b7814bef` |
| `ops/build_close_review.py` | `a361ae023285392ddf3b0e9674a9c506fae79252cc02c15df221ae09ba28e5aa` | `59ac7798bcb1d54bbd11bbc61803997f36881a29cd1b82ecb663166791d5e0f2` |

完整路径、bytes、Git blob 和补丁 SHA 见 [BEFORE_AFTER_SHA256.json](BEFORE_AFTER_SHA256.json)。两个补丁均已在临时副本中正向应用、反向恢复，结果分别与完整 after/before 字节完全一致，见 [PATCH_REPLAY.json](verification/PATCH_REPLAY.json)。

## 3. 本批实际测试及独立复审

| 范围 | 原始前像结果 | 候选结果 | 独立 Reviewer |
|---|---:|---:|---:|
| 日期上界与既有合同兼容 | 5 FAIL / 8 PASS | 13 PASS | 13 PASS |
| 收盘缺来源标记与真实 store 读回 | 8 FAIL / 6 PASS | 14 PASS | 14 PASS |
| 两份最终产品同时加载 | 本项不作为单文件 RED | 同一收盘 14 项再执行 | 14 PASS |
| Reviewer 新增：读取旧版封存的未来来源 | 旧版实际物化且能读取 | 新版读取拒绝且来源三件套不变 | 2 PASS |
| 嵌套未知字段独立探针 | 2 FAIL | **2 FAIL** | 复核失败证据及缺合同原因，未宣称修复 |

作者提供的是 **27 个不同的定向回归用例**。Reviewer 对这 27 项独立复跑，再做 14 次组合加载复跑，并新增两个读取反例：合计 **43 次通过的执行，覆盖 29 个不同的用例**。重复执行没有算作新增测试；作者可迁移性复跑也未重复计入独立用例数。原历史 51 PASS、70 PASS / 3 FAIL 以及 R1 的测试总数不是本轮执行结果。

独立结论为 **`PASS_WITH_DEPLOYMENT_GAPS`**，范围限上述两项源码候选。最终精确 SHA、实际命令、组合加载模块路径以及发现数量见 [独立复审报告](review/final/REPORT.md) 和 [机器结果](review/final/REPORT.json)。预实施合同矩阵保留在 [COMPATIBILITY_MATRIX.md](review/COMPATIBILITY_MATRIX.md)；其中记录的“后像尚未执行”属于该文件生成时点，后续结果以 final 报告为准。作者原始 `PENDING_ROOT_REVIEW_RECORD` 也作为原时点记录保留。

### 验证范围如何理解

日期用例使用真实 `PreselectionPoolStore.materialize/read_pool`，原 fixture 和原历史 validator 测试从冻结文件经 SHA 校验后原样抽取；没有替换 validator 或磁盘 I/O。收盘用例运行真实 producer、domain、`CloseSnapshotStore`、`PreselectionPoolStore` 和 `ReviewStore`，使用合成的 600 个收盘行及最多 100 个模型行。

收盘 fixture 明确设置 `stage_selection_root=None`。缺失的实际 Stage consumer 仅用一个“被构造即报错”的导入 sentinel 占位，实际 consumer 未执行。其结果不能扩展为 Stage、完整应用、API/UI 或当前 Mac 依赖闭包验收。组合运行额外核对两个实际加载模块的 `__file__`、SHA，以及 producer 使用的确实是新的 PoolStore 类。

两个独立读取反例先用完整旧版真实物化、读回内部绑定一致的未来来源，再用新版本读取。它们因新增日期上界报错，artifact、receipt 和 manifest 的前后字节保持一致。只保存测试代码和精简哈希摘要，不交付临时合成业务产物。

### 实际环境与复跑

产品测试使用 **Linux x86_64 / glibc 2.39、Python 3.14.7、pytest 9.1.1**。仅打包/哈希/补丁回放使用环境的 Python 3.12.14 标准库和 `patch`。解释器路径、base identity 和执行范围见 [ENVIRONMENT.json](verification/ENVIRONMENT.json)；本次没有安装或升级依赖。

在整个增量包根目录，以已有兼容的 Python/pytest 环境复跑；结果写入新目录，避免覆盖封存日志：

```bash
python -B historical_validation/run_validation.py --mode after --log-dir ../issue28_p2_recheck/dates
python -B close_pit/run_tests.py --phase after --output ../issue28_p2_recheck/close
python -B review/final/run_combined_review.py --close-root close_pit --historical-root historical_validation --output ../issue28_p2_recheck/combined
python verification/replay_patches.py --output ../issue28_p2_recheck/patches.json
python verify_delivery.py
```

原始 RED 可按子目录 README 的 before 命令复跑。日期 runner 的 `--mode all` 还包括仍未解决的嵌套探针；其总退出 0 只表示观察到声明的预期结果，**嵌套探针的 pytest 退出仍为 1，结果仍为 FAIL**，没有 xfail 或跳过。

## 4. 嵌套 P2 为什么仍未闭合

原 consumer 和最小 fixture 没有给出 `v4.hk_eligibility_asof.v1`、`v4.hk_history_price_recovery.v1` 的完整可选字段集合。定点核对两份共享来源文件和两份 recovery test 后，后者仍指向外部的 `ACTIVE_BINDINGS.json`、历史来源 archive 和 `RECOVERY_ROOT/local_fix/roots/shared_package`，没有提供这些完整 schema/producer 字节。

已知可选字段必须保留；`source_input_sha256` 又是开放的来源标签→digest 映射。根据有限字段拼白名单，可能误拒原本合法且已封存的恢复记录。完整调查边界、4 份新取得引用的 commit/blob/SHA、精确本机缺件位置，以及两个仍失败的探针见 [historical_validation/README.md](historical_validation/README.md)。

下一步可执行的本机适配顺序、缺件清单、逐项验收和源码回滚要求已写入 [LOCAL_ACCEPTANCE.md](LOCAL_ACCEPTANCE.md)。需要的是原 producer/schema 的精确身份和合法字段结构，不需要另建数据来源或补造 capture time。

## 5. 仍然开放的 Issue 边界

本增量没有填补8/25缺 manifest/receipt/provenance、9/30捕获晚于目标收盘、10/7原始来源缺失的问题。A 行情少6–7只、研究/新闻评分合同与覆盖、逐 run 执行和自然时段证据也仍按总工单保留。

R1 的港股来源绑定、A 竞价、A 池读取及发布恢复改动继续按其原源码交接和本机验收安排衔接。旧 R2 发布 `FAIL / NOT_DEPLOYABLE` 回执不被新源码测试覆盖。当前 owner 完整身份、Mac canary、活动发布计划、API/UI、自然时段均为 `NOT_RUN / CANNOT_CONFIRM`；本包的 `DEPLOYED=false`。

本批只新增独立源码交接目录，没有合并分支、关闭 Issue、发送 Issue 评论、部署或操作业务数据。经理台 R3、Vibe8910、A/HK 边界、A 全量有效汇总准入以及模型/BUY 安全标记保持原任务边界。代码、必要测试、来源身份和精简证据由 [DELIVERY_MANIFEST.json](DELIVERY_MANIFEST.json) 逐文件封存。
