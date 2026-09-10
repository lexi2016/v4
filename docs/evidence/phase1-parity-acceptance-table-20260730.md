# Phase 1 Parity Acceptance Table — 20260730

本会话没有可调用的内置浏览器 DevTools 控制器，因此无法读取“第一次打开 V3”时的真实视口。自动证据使用固定的 1440×900 Chrome/Playwright fallback，页面 lane 保持 `CANNOT_CONFIRM`，不冒充内置浏览器验收。

| 图谱节点 | V3 入口 | V3.5 入口 | 业务日期 | 冻结输入 | V3 结果 | V3.5 结果 | 差异 | Artifact | API | Page | 截图 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `timeline_node:v3_opening_intraday_stage_select_0925_1500`; `api:GET /workbench/stage`; `api_ref:/api/v3/workbench/stage` | `http://127.0.0.1:8771/?date=20260730` | `http://127.0.0.1:8872/?date=20260730` | `20260730` | V3 `605148ad…`; V3.5 `d447078f…`，不一致 | API A/HK/total `0/10/10`；可见阶段股票行 `10` | API A/HK/total `50/20/70`；可见候选行 `20` | 输入 SHA 不同，行数差异只记录，不升级为业务等价性失败 | `CANNOT_CONFIRM`：V3 snapshot 无独立 manifest；两侧都显式带 `SOURCE_SHA_MISMATCH_V3_V35` | `CANNOT_CONFIRM`：`SOURCE_SHA_MISMATCH_V3_V35` | `CANNOT_CONFIRM`：fallback loading 结束、无横向溢出、console 0/0；内置控制器不可用 | `.runtime/evidence/phase1/screenshots/v3-20260730-1440x900-final.png`; `v35-20260730-1440x900-final.png` | `CANNOT_CONFIRM`；Phase 2 使用同一冻结输入 replay 才能裁决业务等价性 |

当前机器权威 receipt：
`.runtime/evidence/phase1/parity/20260730/stage.workbench/stage_0925_live_source_mismatch_v2/receipt.json`
（`5ec8689ce76a8963d2792afff21c64a4161c702a9005d467ec98500cb93d88de`）。

机器权威索引：
`.runtime/evidence/phase1/parity/20260730/stage.workbench/authority.json`
（`dfbf7a36d7fe3f0d02020dbc84a42ec31488aad76a4f74b56fabdf7dd4a97c7c`）。
索引将早期 `stage_0925` 的探索性 `FAIL` 和第一版 source-mismatch receipt 标记为 superseded；自动消费者只读取索引指定的 active receipt。
