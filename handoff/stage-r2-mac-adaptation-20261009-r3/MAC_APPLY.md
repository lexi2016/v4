# R3 Mac 落地：执行适配代码

从本 README 所属固定 commit 取完整 `handoff/stage-r2-mac-adaptation-20261009-r3` 目录。以下只操作新建隔离目录；现役 Stage、API 和 dirty canonical 均为读取来源。Mac 执行命令、测试与验收；新增业务/工具代码由 Chat 交付。R2 的旧 partial copy 保留，新尝试必须换新 WORK，不能先 chmod 原根或复用旧目标。

## 1. 核固定包与前像，准备新 Stage canary

填入本机既有 Python/配置路径。`WORK` 须是新目录；不要复用此前输出。`TICK_CONFIG` 是当前实际 tick JSON 配置，保留其中的有效输入 roots、原共享行情依赖和词法 venv 路径。

```bash
PKG='/absolute/stage-r2-mac-adaptation-20261009-r3'
WORK='/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009'
V4PY='/absolute/current/venv/bin/python'
TICK_CONFIG='/absolute/current/stage_center_tick_config.json'
STAGE_ACTUAL='/Users/lexi/Desktop/学习/agents调试/V4_HK_STAGE_RECOVERY_20261003/issue23_runner_helper_r3/stage_r1_binding_candidate_r3/app'
API_ACTUAL='/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app'
UI_SOURCE='/Users/lexi/Desktop/学习/v4_app'
HK_INPUT='/Users/lexi/Desktop/学习/agents调试/V4_HK_INPUT_RESTORE_20261009/candidate/futu_snapshot_current_20261009T153841+0800'
mkdir "$WORK"
"$V4PY" -B "$PKG/tools/verify_package.py" --package "$PKG"
"$V4PY" -B "$PKG/tools/prepare_canary.py" \
  --package "$PKG" --group stage --source-root "$STAGE_ACTUAL" \
  --destination "$WORK/stage_app" > "$WORK/stage_prepare.json"
```

退出非零时读取 `stage_prepare.json`：它一次列出每个缺文件/不匹配的实际 SHA 和期望 SHA，门禁失败时不建立候选目录。本次所需前像已齐，状态见 [MISSING_PREIMAGES.md](MISSING_PREIMAGES.md)。只在反馈之后字节确实又变化时回传工具列出的具体不匹配文件与 SHA，由 Chat 给对应增量。`after/stage` 不是完整 app，不能代替上一步的克隆。

准备政策已固定在 `CANARY_SOURCE_POLICY.json`，SHA 绑定到 SOURCE_MAP：内部 `v3_shared_data -> upstreams/v3_shared_data` 原样保留；精确外部 `upstreams/v3.5` 只记录链接文本并隔离，不读取目标目录内容。其他意外链接继续报告。候选 `CANARY_SOURCE_MANIFEST.json` 记录所选源集合、SHA、模式和链接身份，供后续 canary 核对。

## 2. 独立复跑最终候选测试

`UI_RUNTIME` 使用已有、装好 Vue/compiler/server-renderer 的 web 项目目录（含 package.json 和 node_modules）。本轮记录用 Python 3.12、Node 24、Vue 3.5.13；使用本机既有环境实际执行并保留返回值。工具没有可用 UI 运行环境会报 NOT_RUN，不会算通过。

```bash
UI_RUNTIME='/absolute/existing/web/project'
"$V4PY" -B "$PKG/tools/run_checks.py" \
  --stage-app "$WORK/stage_app" --ui-runtime "$UI_RUNTIME" \
  --output "$WORK/independent_checks"
```

期望数量固定在 `TEST_EXPECTATIONS.json`：Stage 148 / API 82 / adaptation 50 / Vue 45 / 当前 App Vue 27，合计 352。所有套件必须精确命中数量、零 skip/failure/error，少跑、多跑、缺报告也会失败；该文件 SHA 同样绑定到 SOURCE_MAP。另有 fresh 695 合成输入的原 runner→原算法→三件套→owner→API→Vue 全链。工具输出实际命令、模块版本、源码 SHA、日志、JUnit 和 `RESULTS.json`。这是独立源码复跑，不能替代下一步真实数据执行。

## 3. 用用户给定真实四文件执行一个分钟阶段

工具在写出前核对四份真实文件的固定 SHA；复制到新的研究输入目录并附上 pin。它不修改原 HK 输入、正式 D1、原配置或原共享源。若共享 HQ root 在候选 app 外，会在新目录克隆已有依赖，仅应用已匹配 SHA 的那个 HQ 修复；新副本只读目录的必要权限调整由工具完成并恢复。内部 alias 不再被当作任意外部链接拒绝。

```bash
"$V4PY" -B "$PKG/tools/run_current_research_canary.py" \
  --package "$PKG" --stage-app "$WORK/stage_app" --config "$TICK_CONFIG" \
  --hk-input "$HK_INPUT" --output-root "$WORK/research_0935" \
  --stage-id STAGE_0930_0935 --execute
```

该入口调用原 `StageCenterRunner.tick(..., historical_backfill=True, _skip_precapture=True)`；阶段评估时间来自原合同，owner 写入时间来自真实时钟，明确标记 `CURRENT_DAY_RESEARCH_REPLAY`。行情仍由原 PyTDX 链取对应阶段的真实 bar。没有合格行情时返回 `EXECUTED_NO_HK_SELECTION`，不借用证券资料里的字段构造价格。

需要验证 13:00–13:15 时，用新输出 `research_1315` 和 `--stage-id STAGE_1300_1315` 重复同一命令。其他允许阶段列在 README。独立复跑也使用另一个新输出目录，不删除锁、latest 或旧回执。

成功状态为 `RESEARCH_ROWS_WRITTEN`。结果中的选中数必须由真实行情决定，不预先承诺 695 只都有行情。核对 `run_manifest.json`、`result.json` 以及 manifest 给出的实际 `output_paths`；backfill 会增加一层 run namespace，不能读取空的基础 root 后就说没有运行。

## 4. API/UI canary 与同一 run 读回

Stage 研究执行不等待 API 拆分。以下两个命令按各自实际前像准备 API 副本及 UI 源集合。API 源 0555/文件 0444 可直接作为读取来源；工具只临时调整新候选的必要目录模式，并验证恢复。UI 只复制 `apps/web`，保存其中当前 shell、views、manager、配置与锁文件；canonical 根的临时 pytest 链接不属于此源集合。新组件按明确 add 合同创建，已有未知同名文件会拒绝。

```bash
"$V4PY" -B "$PKG/tools/prepare_canary.py" \
  --package "$PKG" --group api --source-root "$API_ACTUAL" \
  --destination "$WORK/api_app" > "$WORK/api_prepare.json"
"$V4PY" -B "$PKG/tools/prepare_canary.py" \
  --package "$PKG" --group ui --source-root "$UI_SOURCE" \
  --destination "$WORK/ui_app" > "$WORK/ui_prepare.json"
```

先用已修完整 consumer 直接读同一真实 run。下面是调用已有对象的读回命令，不是另一个 producer。它同时检查所加载 API 文件 SHA。

```bash
"$V4PY" -B - "$PKG" "$WORK/api_app" "$WORK/research_0935/run_manifest.json" \
  > "$WORK/research_0935/consumer_readback.json" <<'PY'
from pathlib import Path
import hashlib, json, sys
package, api, manifest = map(Path, sys.argv[1:])
for row in json.loads((package / 'SOURCE_MAP.json').read_text())['files']:
    if row['group'] == 'api':
        assert hashlib.sha256((api / row['relative_path']).read_bytes()).hexdigest() == row['after_sha256']
run = json.loads(manifest.read_text())
assert run['status'] == 'RESEARCH_ROWS_WRITTEN'
sys.path.insert(0, str(api))
from stage_center import consumer, execution_evidence
for module, relative in ((consumer, 'stage_center/consumer.py'), (execution_evidence, 'stage_center/execution_evidence.py')):
    assert Path(module.__file__).resolve() == (api / relative).resolve()
reader = consumer.StageSelectionConsumer(run['output_paths']['selection_root'])
assert reader.execution_receipt_root == Path(run['output_paths']['receipt_root'])
data = reader.get(run['trade_date'], run['stage_id'])
assert data['trade_date'] == run['trade_date'] and data['stage_id'] == run['stage_id']
assert data['RESEARCH_ONLY'] is True
assert all(data[key] is False for key in ('production_allowed', 'buy_gate_updated', 'orders_sent'))
hk = data['markets']['HK_CONNECT']
assert hk['run_id'] == run['selection_run_id']
ev = data['execution_evidence']
assert ev['receipt_history_binding'] == 'OWNER_HISTORY_SHA_BOUND'
assert ev['selection_artifact_bindings']['HK_CONNECT']['status'] == 'BOUND_TO_VERIFIED_SELECTION_TRIO'
assert ev['execution_origin'] == 'CURRENT_DAY_RESEARCH_REPLAY'
assert ev['natural_verified'] is False
print(json.dumps(data, ensure_ascii=False, indent=2))
PY
```

既有 API factory 的 `stage_center_selection_root` 绑定到 manifest 的**实际** `output_paths.selection_root`，即带 backfill id 的根。新的 consumer 会精确映射同 id 的 receipt 根。使用现有启动/配置方式作隔离检查；不要把 API 指到基础空 root，不要给普通 GET 添加未获原 allowlist 接受的 `backfill_run_id` 参数。

已取得的 API 源码中，普通只读路由是：

```text
GET /api/v3/workbench/stage?date=20261009&stage=STAGE_0930_0935&limit=10
```

当前实际 API adapter/启动配置并未提供给 Chat，保持原样复制。只有同一 run 读回明确暴露其参数合同不兼容时，回传实际 `apps/api/v35_api/app.py`、报错与当前 SHA/加载配置身份，由 Chat 给必要接线补丁。不能以历史 adapter 片段声称当前 8873 已验证。无需启用 r5c 或编写 API 模块拆分。

### UI 构建与原页面准备

使用已复制 `apps/web/package.json` 和现有 lock，通过项目既有依赖安装/构建命令准备 `$WORK/ui_app/apps/web`。不要把 R2 旧 App 整文件回盖进去，也不要手工修改 shell 补字段。本次只在已上传 App/runtime 前像上接线，并新增证据组件；经理入口、导航、日期/阶段事件保持。

`run_checks` 的当前 App 套件使用真实当前 App 源码进行 Vue 编译、SSR 和事件绑定验证；替代的 shell/其他视图仅为测试输入，不能将它冒充完整现役浏览器验收。实际页面必须使用下面同一 run 的 HTTP 响应复核。

## 5. 通过既有发布链落地，再验同一 run 页面

将已通过上述检查的明确文件增量交给既有发布链；actual Stage、actual API、canonical/UI 的源 SHA 分开记录。发布链若要求 dirty canonical 归并，只对已知前像做逐项审查；未知前像由 Chat 产生对应最小 patch，不能整文件覆盖。此包没有执行启停、部署、merge 或现役数据改写。

在既有入口读回同一日期/阶段，逐项核对：

| 项目 | 必须一致/保留 |
|---|---|
| 运行身份 | date、stage、market、run_id、artifact_id、algorithm_sha256、raw_artifact_sha256，与真实 owner 和三件套一致。 |
| 输入 | 真实四文件 SHA、research binding SHA；A 为实际完整输入数，不能变成 UI 200。 |
| 页面 | 已计算选中数、行情已取得/请求/缺口分别显示；来源限制和执行模式独立显示。 |
| HK 研究 | 名单日期 10/8、15:38:41 资料采集时间、stale、Connect 待确认、非正式 D1。 |
| 回执 | 同一 namespace 的 immutable owner history 和三件套 SHA；模块文件观察与发布候选身份一致。 |
| 模式 | CURRENT_DAY_RESEARCH_REPLAY / RECOVERY；natural_verified=false，不得显示自然触发已验收。 |
| 金融标志 | RESEARCH_ONLY=true，其余 production_allowed/buy_gate_updated/orders_sent 均 false。 |

页面显示 10 只但来源待确认可以是正确研究结果；缺自然证明不能抹去它。只有源码测试通过不能称现役恢复。自然定时流程是后续独立验收项。

## source witness 错误的只读定位

若 A 仍报告 projection SHA mismatch，使用当前配置中实际研究 root 和该阶段所绑定的源 slot：

```bash
PYTHONPATH="$WORK/stage_app" "$V4PY" -B "$PKG/tools/diagnose_source_witness.py" \
  --research-root '/absolute/actual/hourly/research/root' \
  --trade-date 20261009 --slot 'ACTUAL_BOUND_SLOT' --stage-cutoff 13:15:00 \
  > "$WORK/source_witness_diagnostic.json"
```

`ACTUAL_BOUND_SLOT` 必须来自该次绑定，不能猜成阶段名。输出给出 archive/receipt/manifest/witness 的具体路径、SHA、原校验错误和 JSON 字段差异；这些证据回传 Chat 即可。工具不修饰 witness，坏的 A 来源继续单独隔离，HK 已算结果仍可保留。

## 失败保留与回滚

- 任一步非零，保留对应 prepare/result/manifest/日志及 partial 目录；新尝试使用新目标。不得删除锁、回执或旧失败，也不得给原 source 或外部链接目标改权限。
- 尚未发布时：原服务未变，无需“恢复”原源文件；将失败候选留在原处，停止该次隔离验收即可。
- 若已通过既有发布链发布：按同一发布链回到发布前记录的 release/manifest，不对 dirty canonical 整文件回盖、不手动重写业务数据。保留本轮运行 namespace 和 immutable receipt 供对照。
- 以 `SOURCE_MAP.json` 的实际组与 SHA 为应用边界。`patches/ui-before-to-after.patch` 用于本次当前 UI 前像；`patches/r2-package-to-r3.patch` 仅供冻结 R2 **交付包目录**变为 R3，不能贴到任何现役 app 根。推荐直接取完整 R3 包，使用上述 prepare 命令。
