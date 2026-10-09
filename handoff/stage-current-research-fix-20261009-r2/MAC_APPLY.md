# Mac 落地：只执行代码、测试与验收

以下使用包内完整 after / 精确前像工具。`PKG` 指向解压后的本包；`WORK` 是一个新的绝对路径目录。先把 `STAGE_PY`、`API_PY` 设置为两套现役原启动命令中的 Python 绝对路径，`STAGE_CFG` 设置为现役 Stage 原 `--config` 指向的 JSON 绝对路径；这些具体路径未提供，因此不猜测。原项目要求 Python ≥3.14，原配置 loader 要求所有 `_root`、`_path` 为绝对路径。保留原 SDK `python_path` 和其他采集配置，无需设计新增业务逻辑。

## 1. 一次预检，建立两个隔离 app

```bash
PKG="/绝对路径/stage-current-research-fix-20261009-r2"
WORK="/Users/lexi/Desktop/学习/agents调试/V4_STAGE_CURRENT_RESEARCH_R2"
STAGE_ACTUAL="/Users/lexi/Desktop/学习/agents调试/V4_HK_STAGE_RECOVERY_20261003/issue23_runner_helper_r3/stage_r1_binding_candidate_r3/app"
API_ACTUAL="/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app"
STAGE_CANARY="$WORK/stage_app"
API_CANARY="$WORK/api_app"

: "${STAGE_PY:?请设置原 Stage Python 的绝对路径}"
: "${API_PY:?请设置原 API Python 的绝对路径}"
: "${STAGE_CFG:?请设置原 Stage config JSON 的绝对路径}"
python3 "$PKG/tools/verify_package.py" --report "$WORK/package_check.json"
python3 "$PKG/tools/stage_patch.py" prepare --role actual_stage \
  --root "$STAGE_ACTUAL" --candidate "$STAGE_CANARY" --report "$WORK/stage_apply.json"
python3 "$PKG/tools/stage_patch.py" prepare --role actual_api \
  --root "$API_ACTUAL" --candidate "$API_CANARY" --report "$WORK/api_apply.json"
```

工具先检查全部待改文件，接受包中明列的 restored before、R1 或最终 after SHA；任何不匹配均一次列全并停止，源 app 不变。候选必须为物理独立且尚不存在的目录；不会通过 symlink 写回现役。它不会启动 timer、生产者或发布服务。

如果某个前像不匹配，按 `SOURCE_GAPS.md` 一次提供那几个**具体源文件内容＋实际 SHA**，由 Chat 处理相同业务改动的代码适配；Mac 无需改逻辑。canonical 如需纳入原发布链，以 `--role canonical_stage` 对 canonical 自己建立第三个隔离副本，不能套 actual Stage/API 文件整棵覆盖。

## 2. Mac 独立复跑

用原 Python 建立独立测试环境，依赖直接读取两套 canary 原 `pyproject.toml` 中的项目依赖和 dev 组；不会修改现役 venv，也不假定多顶层包可以 editable install。然后在隔离 API 前端沿其原锁文件安装、构建：

```bash
"$STAGE_PY" -c 'import sys; assert sys.version_info >= (3, 14), sys.version'
"$STAGE_PY" -m venv "$WORK/test_venv"
CHECK_PY="$WORK/test_venv/bin/python"
"$CHECK_PY" - "$STAGE_CANARY/pyproject.toml" "$API_CANARY/pyproject.toml" <<'PY'
from pathlib import Path
import subprocess, sys, tomllib
dependencies = set()
for name in sys.argv[1:]:
    project = tomllib.loads(Path(name).read_text())
    dependencies.update(project["project"].get("dependencies", []))
    dependencies.update(project.get("dependency-groups", {}).get("dev", []))
subprocess.run([sys.executable, "-m", "pip", "install", *sorted(dependencies)], check=True)
PY
"$CHECK_PY" -c 'import pytest, fastapi, httpx; print("test dependencies ready")'
npm --prefix "$API_CANARY/apps/web" ci
npm --prefix "$API_CANARY/apps/web" run build

"$CHECK_PY" "$PKG/tools/run_checks.py" \
  --stage-root "$STAGE_CANARY" --api-root "$API_CANARY" \
  --ui-runtime "$API_CANARY/apps/web" --output "$WORK/independent_tests_1"
```

原 dev 依赖包含 pytest 和 HTTP TestClient 所需 httpx；本轮 Linux 使用 Python 3.14.8、Node 24。SSR harness 需要 Node 的 `stripTypeScriptTypes` 和项目原 Vue/compiler/server-renderer，可通过 `--node /绝对路径/node` 指定现有兼容 Node。真实采集仍使用原 `STAGE_PY` 与配置中的 SDK Python。

**该 Mac 命令默认关闭归档 RawStore 签名测试兼容层。** 若当前真实 facade/helper 不匹配，保留其错误和两文件 SHA，不要安装测试 shim 到业务代码。Linux 参考记录使用的 `--allow-archived-signature-test-support` 不属于 Mac 验收命令。测试只用临时合成输入，不读取 695 条真实 Mac 文件，也不发真实 provider 网络请求。

## 3. 调用原 runner 产生真实研究结果

```bash
HK_INPUT="/Users/lexi/Desktop/学习/agents调试/V4_HK_INPUT_RESTORE_20261009/candidate/futu_snapshot_current_20261009T153841+0800"
RUN_OUT="$WORK/run_1"

python3 "$PKG/tools/current_research.py" configure \
  --source-config "$STAGE_CFG" --candidate-root "$STAGE_CANARY" \
  --output-root "$RUN_OUT" --hk-research-root "$HK_INPUT"

"$STAGE_PY" "$PKG/tools/current_research.py" run \
  --candidate-root "$STAGE_CANARY" --config "$RUN_OUT/current_research_config.json" \
  --trade-date 20261009 --stage STAGE_1545_1555 --report "$WORK/run_1_result.json"
```

脚本仅把原配置的 `raw_root/selection_root/receipt_root` 指向新的 `RUN_OUT/stage/*`，增加研究 root 和安全标记；原预选、资料、研究/source、SDK Python 路径保留。它调用原 `_load_config`、`_build_runner` 和 `StageCenterRunner.tick`，由原锁、collector、算法、stores、writer 工作。调用时间使用真实时钟；没有 `--evaluated-at` 倒填参数，没有新 producer 或新算法。

原 15:38 资料仅允许本次 HK 15:55 阶段。价格必须由原分钟链取得合格的 15:45–15:55 窗口；若原 provider 无该真实窗口，回执保留逐股原因，不把收盘后快照或证券资料改装为分钟行情。

同一个 config 再调用会走原幂等合同。需要独立重新采集时，用新的 `RUN_OUT` 再执行 `configure`；保留第一份证据。原 SelectionStore 的已落定 slot 不覆写，已有 A Top10 也不删除。其他 A 阶段可以用原 `--stage` 指定，在同一研究配置下 HK 时间不合法只影响 HK lane。

## 4. 同一个 run 的 API 与页面

使用现有 API 启动模块在另一个本地端口读取上述原 selection 根。以下新 data/ledger 目录用于 canary API；若要显示原 A 预选名称，给原 `--preselection-source-root` 传入源配置中已有的只读根。

```bash
(
  cd "$API_CANARY" || exit 1
  PYTHONPATH="$API_CANARY" "$API_PY" -m apps.api.v35_api.run \
    --host 127.0.0.1 --port 8883 --stage-mode shared \
    --data-root "$WORK/api_data" --ledger-root "$WORK/api_ledger" \
    --stage-selection-root "$RUN_OUT/stage/selection"
)
```

启动块显式进入 API canary，确保 `python -m` 的当前目录优先规则不会加载现役/canonical 同名模块；子 shell 退出后不改变 Stage 的工作目录。

在独立终端执行只读核对：

```bash
"$API_PY" "$PKG/tools/same_run_probe.py" \
  --api-root "$API_CANARY" --selection-root "$RUN_OUT/stage/selection" \
  --receipt-root "$RUN_OUT/stage/receipts" --base-url http://127.0.0.1:8883 \
  --date 20261009 --stage STAGE_1545_1555 --market HK_CONNECT \
  --report "$WORK/same_run_api.json"
```

工具比较本地原 stores/owner receipt、精确 `selection_run_id` 请求、页面普通请求的 date/stage/market/run/algorithm/raw/输入/源码身份，不把旧页面默认结果算作本次 run。报告必须为 `SAME_RUN_VERIFIED` 才通过该项；随后在 `http://127.0.0.1:8883/` 的现有阶段页选择同日同阶段，确认选中数、行情覆盖、研究资料时间/旧 universe/资格限制和手动模式都与报告一致。浏览器验收独立记录，探针不自称看过浏览器。

## 5. 既有发布链

Mac 接受上述真实 run 后，将**已核 SHA 的两个候选及其 `SOURCE_MAP.json`/运行配置**交现有 Stage 与 API 各自的发布链，完成其原备份、测试、切换和回滚钩子；本包没有替换发布器、timer 或 API 模块拆分工作流。实际发布命令/发布器当前源码未提供，不能编造新的发布命令代替现有链。

发布链的代码门禁可直接调用：

```bash
python3 "$PKG/tools/stage_patch.py" verify --role actual_stage --root "$STAGE_ACTUAL" --report "$WORK/stage_released_sha.json"
python3 "$PKG/tools/stage_patch.py" verify --role actual_api --root "$API_ACTUAL" --report "$WORK/api_released_sha.json"
```

代码发布后，用实际 API 根/端口和实际配置中的同一 selection/receipt 根再次执行 `same_run_probe.py`，并保留页面同 run 验收。原输出 slot 已存在时沿其既有不可变/幂等合同复用，不能清空旧证据换取成功。

自然触发放在结果恢复之后。所有手动 canary/补验始终为 `MANUAL_CURRENT_DAY_RESEARCH` 或明确的手动执行，`natural_verified=false`。后续 timer 需要自己的真实时刻、加载版本、输入及同 run 回执证明，不能由这次手动通过反推自然运行已通过。
