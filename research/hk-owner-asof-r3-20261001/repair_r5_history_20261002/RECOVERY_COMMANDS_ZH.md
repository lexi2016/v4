# Mac历史恢复命令（只在R5隔离组合验收通过后执行）

以下命令由Mac负责；Chat没有执行。先设置实际活动根，所有路径沿当前配置，不重新安装环境。

```bash
export R9_APP="/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r9-hk-child-binding-standard-b1f316ac73f0/app"
export SHARED_PACKAGE="/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260923-hk02-owner-rebase-r2/app/upstreams/v3_shared_data"
export SHARED_DATA_ROOT="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data"
export HK_UNIVERSE_ROOT="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data"
export HK_ASSET_ROOT="$SHARED_DATA_ROOT/assets/hk_0_2"
export HK_TDX_ROOT="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/hk_tdx"
export SERVICE_PYTHON="/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python"
export HK_PYTHON="/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260904T081111Z-v35-strict-stage-acquisition-v15/app/ops/launch_hk_0_2_python_nosite.sh"
```

## 1. 先只读检查9/29原authority

```bash
cd "$R9_APP"
"$SERVICE_PYTHON" -B - <<'PY'
from pathlib import Path
from stage_center.hk_universe_preflight import _load_shared_universe_reader
root=Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data")
reader=_load_shared_universe_reader()
for day in ("20260928","20260929"):
    try:
        u=reader(root,day,"HK_CONNECT")
        import hashlib
        print(day,"READY",len(u.codes),u.codes_sha256,
              hashlib.sha256(u.path.read_bytes()).hexdigest(),u.path)
    except Exception as e:
        print(day,"CANNOT_CONFIRM",type(e).__name__,str(e))
PY
```

若20260929已经存在并通过严格reader，禁止创建manual recovery，直接使用原authority。

## 2. 原9/29 authority仍缺失时，恢复资格

官方SSE调整信息页在2026-09-28列明03228和09607调入、生效日2026-09-29。下载原始官方字节并计算SHA；若下载结果本身不含20260928、20260929、03228、09607，则停止，不自行制作替代JSON。

```bash
OFFICIAL="$PWD/sse_hkconnect_adjust_20260929.html"
curl -fL 'https://www.sse.com.cn/services/hkexsc/disclo/eligiblead/' -o "$OFFICIAL"
OFFICIAL_SHA="$(shasum -a 256 "$OFFICIAL" | awk '{print $1}')"

read PARENT_ARTIFACT_SHA PARENT_CODES_SHA <<EOF
$("$SERVICE_PYTHON" -B - <<'PY'
from pathlib import Path
import hashlib
from stage_center.hk_universe_preflight import _load_shared_universe_reader
root=Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data")
u=_load_shared_universe_reader()(root,"20260928","HK_CONNECT")
print(hashlib.sha256(u.path.read_bytes()).hexdigest(),u.codes_sha256)
PY
)
EOF

"$SERVICE_PYTHON" -B -m stage_center.hk_universe_preflight   --store-root "$HK_UNIVERSE_ROOT"   --trade-date 20260929   --parent-trade-date 20260928   --parent-artifact-sha256 "$PARENT_ARTIFACT_SHA"   --parent-codes-sha256 "$PARENT_CODES_SHA"   --official-evidence "$OFFICIAL"   --official-evidence-sha256 "$OFFICIAL_SHA"   --official-url 'https://www.sse.com.cn/services/hkexsc/disclo/eligiblead/'   --notice-date 20260928   --effective-date 20260929   --delta-code HK.03228   --delta-code HK.09607
```

该入口仍使用当前Futu两板块完整集合做corroboration；产物必须标记MANUAL_RECOVERY、natural_verified=false，并记录实际10/2恢复/corroboration时间。当前集合若不等于“9/28父authority＋两只官方delta”，必须失败，不能删差异凑数。

## 3. 通过既有HK daily owner读取9/29历史价格并填panel缺口

历史模式加在原`ops.macos_research_panel_daily_gate`；它仍要求原owner的全部显式authority参数。直接复用当前`research_panel_daily_hk`命令里的原A/HK路径值，只新增：

```
--date 20260929
--lane HK
--hk-history-recovery
--hk-universe-root "$HK_UNIVERSE_ROOT"
```

完整形态：

```bash
cd "$R9_APP"
"$SERVICE_PYTHON" -B -m ops.macos_research_panel_daily_gate   --date 20260929 --lane HK   --receipt-root "$RESEARCH_PANEL_RECEIPT_ROOT"   --a-tdx-root "$A_TDX_ROOT"   --hk-tdx-root "$HK_TDX_ROOT"   --a-minimum-rows 5000   --a-sync-script "$A_SYNC_SCRIPT"   --a-formula-script "$A_FORMULA_SCRIPT"   --a-seed-panel "$A_SEED_PANEL"   --a-data-root "$A_DATA_ROOT"   --a-selector-pointer "$A_SELECTOR_POINTER"   --a-backtest-pointer "$A_BACKTEST_POINTER"   --a-selector-seed "$A_SELECTOR_SEED"   --a-backtest-seed "$A_BACKTEST_SEED"   --a-contract-csv "$A_CONTRACT_CSV"   --a-canonical-formula "$A_CANONICAL_FORMULA"   --a-return-root "$A_RETURN_ROOT"   --hk-updater-script "$SHARED_PACKAGE/scripts/update_hk_0_2_panel.py"   --hk-python-executable "$HK_PYTHON"   --hk-asset-root "$HK_ASSET_ROOT"   --hk-universe-root "$HK_UNIVERSE_ROOT"   --hk-history-recovery
```

成功标准只到`HISTORY_SOURCE_READY`：Futu历史行情source_date=20260929，但requested_at/received_at必须是真实执行时间；不得出现伪造的9/29 captured_at。它会沿原pack与HK0.2 panel owner写入新的不可变gap-fill panel，并保留parent panel SHA。

## 4. 来源齐备后才由Mac执行原D-1物化

Chat不执行：

```bash
"$HK_PYTHON" -B "$SHARED_PACKAGE/scripts/materialize_hk_0_2.py"   --store-root "$SHARED_DATA_ROOT"   --asset-root "$HK_ASSET_ROOT"   --signal-date 20260929   --eligibility-source-date 20260929   --eligibility-universe-root "$HK_UNIVERSE_ROOT"   --target-date 20260930
```

随后由Mac按原链完成HK-only projector、Stage、普通API/UI读回。任何一步发现旧immutable target key冲突都停止，不覆盖旧key。

## 5. HK开市/Connect休市的自然日期

不走history/manual命令。原preselection owner自动分开：
- price = target日前一HK证券交易日；
- eligibility as-of = target日前一HK Connect交易日。

当price日Connect关闭时，owner只读上一Connect authority，并对旧as-of master使用reuse-only；不会用今天Futu名单或今天metadata改写旧日期。
