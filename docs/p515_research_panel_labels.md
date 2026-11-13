# P5.15 V4 研究面板标签查询

以 `stable_security_id` 和八位 `observation_date` 连接现用 V4 逻辑面板与本代样本框。研究消费方可按键查询，返回原面板身份行和 `p515_research` 字段。原面板为面板身份权威来源，样本框提供候选形态、抽样层和待判卷状态。

```sh
"$PANEL_PYTHON" ops/p515_research_panel_labels.py build \
  --pointer "$V4_SELECTOR_POINTER" --reader "$V4_LOGICAL_READER" \
  --frame "$P515_SAMPLE_FRAME" --frame-manifest "$P515_SAMPLE_MANIFEST" \
  --frame-manifest-sha256 "$P515_SAMPLE_MANIFEST_SHA256" --output "$P515_OVERLAY"

"$PANEL_PYTHON" ops/p515_research_panel_labels.py lookup \
  --pointer "$V4_SELECTOR_POINTER" --reader "$V4_LOGICAL_READER" \
  --overlay "$P515_OVERLAY" --overlay-sha256 "$P515_OVERLAY_SHA256" \
  --key 920001.BJ 20261113
```

一次调用支持最多 24 个互异键。面板路径、面板描述符、发布日志、代次回执及读取器沿用样本框绑定。输出文件需为新路径。读取调用校验 overlay 字节 SHA，面板指针变更后，此代的 lookup 返回错误。未来代次需重新冻结样本框和 overlay。

| 检索状态 | 说明 |
|---|---|
| `SAMPLED_PENDING_ADJUDICATION` | 面板行存在，附样本框候选形态、抽样层、阶段和回调待判卷状态。 |
| `NOT_SAMPLED` | 面板行存在，未入该次样本框。 |
| `PANEL_ROW_MISSING` | 本代面板缺指定证券日，返回空面板行。 |

突破、回调和原买点标记转换为 `0`、`1` 或 `UNKNOWN`。候选形态保留代理标记，阶段与回调标签保留 `UNKNOWN_NOT_CREATED`，历史可得性保留 `CANNOT_CONFIRM_HISTORICAL_PIT`。上海、深圳的原面板市场类型为 `A_SHARE`，北交所为 `BJ`。本入口适用于 V4 本地独立研究读取。
