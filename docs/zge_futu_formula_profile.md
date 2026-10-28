# Z哥图形的 Futu QFQ profile

`FUTU_QFQ_ASOF` 是原 selector 面板的有限 chart-only 派生视图。它用于在用户明确要求时，让 Z哥图形中的 OHLC、BBI、白线、黄线和 MA60 与 Futu 前复权显示口径保持一致。原 RAW selector、信号标签、回测与模型读法不变。

当前 profile 仅覆盖 `002612.SZ`、`001283.SZ`，且只支持 `asof=20261023`。因子来自 2026-10-24 的 Futu OpenD `get_rehab` 观察。有效日过滤和当日数值匹配不认证历史 PIT，也不支持选股、回测、收益评价、全市场 QFQ 或成交量/标签复权。

## 消费方式

先用现有只读 reader 解析 selector pointer 并完成对应日期 receipt、manifest 和源文件身份绑定。调用时应使用 profile 绑定的 selector 文件；其实际路径与 SHA 必须仍与 profile 一致。若 pointer 已指向其他版本、profile 缺失、代码或日期未覆盖、source/factor/cache/formula hash 不符，读取必须失败并报告 `CANNOT_CONFIRM`，不能回退到 RAW。

原 reader 的默认行为仍为 RAW。仅用户明确要求 Futu QFQ 图形时显式传入 profile：

```python
qfq_columns = [
    "open", "high", "low", "close", "BBI",
    "zge_white_line", "zge_yellow_line", "ma60",
]
meta = reader.get_panel_meta(
    panel_path=panel_path,
    include_dates=False,
    profile="FUTU_QFQ_ASOF",
    asof="20261023",
)
frame = reader.load_selector_ready(
    columns=qfq_columns,
    filters=[("ts_code", "=", code)],
    ts_codes=[code],
    panel_path=panel_path,
    profile="FUTU_QFQ_ASOF",
    asof="20261023",
)
profile_meta = frame.attrs["profile_metadata"]
```

绘图前保留 `meta["read_profile"]` 或 `profile_meta` 中的 profile ID、asof、factor basis/vintage/SHA、selector path/SHA、derived-cache SHA、formula SHA、支持字段、volume basis 和 PIT 状态。图中不要混入 RAW 的 `J`、`B1/B2/B3`、成交量或其他未声明支持的字段。历史窗口从完整历史 warmup 缓存切片，不能只用当前可见窗口重新计算 EMA。

## 验证与边界

准备 canary 的确定性入口为 `implementation/prepare_futu_profile_canary.py`。它仅读取已绑定 selector 与现成 `get_rehab` CSV，不取历史行情、不更新 pointer，也不安装 profile；输出留在 `implementation/futu_qfq_profile_v1/`。

安装器 `ops/install_futu_formula_profile.py` 默认只做 dry run。安装需固定位置 `review/FUTU_PROFILE_REVIEW_PASS.json` 存在并声明独立 Reviewer PASS，且其 source/profile/cache/skill 文档哈希与当前候选完全一致。它只允许更新冻结 allowlist 中的 reader/helper/profile/cache/技能配方文件，安装前保留字节级备份到 `implementation/activation_backups/`。controller 负责 review 后的激活；本交付不执行安装、回滚或 live consumer readback。

安装前预演：

```bash
"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" -B \
  ops/install_futu_formula_profile.py
```

安装器校验 receipt 的结构为：

```json
{
  "status": "PASS",
  "reviewer_agent": "/root/yellow_line_review",
  "scope_id": "FUTU_PROFILE_CHART_DERIVATIVE",
  "reviewed_hashes": {
    "reader_sha256": "<reviewed candidate SHA-256>",
    "helper_sha256": "<reviewed candidate SHA-256>",
    "profile_sha256": "<reviewed artifact SHA-256>",
    "cache_sha256": "<reviewed artifact SHA-256>",
    "skill_doc_sha256": "<reviewed staged document SHA-256>",
    "contract_doc_sha256": "<reviewed staged document SHA-256>"
  }
}
```

`--apply` 只有在 Reviewer 保存匹配 receipt 后才解除保护。每个目标在写入时重新核对原始 SHA，按文件原子替换并读回 SHA；失败时仅对已写入且仍匹配候选 SHA 的目标尝试按字节备份回滚。要回滚成功安装，可传入 activation record 的绝对路径；脚本只会恢复 receipt 中预先列出的固定目标，且要求当前 SHA 与安装后 SHA 完全一致。

软件 parity PASS 只表示这两个代码、该日期和列集合的工程回归。它不改变 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
