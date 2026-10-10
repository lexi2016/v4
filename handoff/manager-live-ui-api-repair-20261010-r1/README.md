# V4 Manager 页面与输入身份修复候选 · 2026-10-10 R1

**交付状态：`PROPOSAL_ONLY / LIVE_API_UI_NOT_RUN`。** 已形成针对上传问题包的最小源码候选与离线回归证据。后端最终 35 项通过，前端实际 panel 挂载的 DOM integration 最终 22 项通过。现场 Mac、现役 API、浏览器构建资源身份及自然时段验收尚未执行。

## 从这里开始

1. 阅读 [REPAIR_REPORT.md](REPAIR_REPORT.md)：四项问题的修复、已证事实、实际测试和剩余限制。
2. 阅读 [MAC_ACCEPTANCE.md](MAC_ACCEPTANCE.md)：包内复现、精确前像门禁、在新的完整候选应用、独立验收和回退。
3. 运行下面的离线命令，保留其实际输出。`--report-dir` 必须在包外。

```bash
python3 tools/verify_delivery.py &&
python3 tools/run_offline_tests.py --side after --report-dir /tmp/v4-manager-live-ui-api-repair-r1
```

Python 本轮为 3.12.14，Node 为 24.19.0。测试需要 Node 的 `stripTypeScriptTypes` 与 `registerHooks`，无需安装生产依赖。补丁校验需要 Git。正式项目测试、类型检查与 Vue/Vite 构建须在 Mac 的完整项目环境另行执行。

## 交付内容

| 路径 | 用途 |
|---|---|
| `runtime.patch` | 唯一产品补丁；修改 6 个现有文件，新增 1 个 identity helper |
| `before/`、`after/` | 7 个补丁目标的完整前像/后像；新增文件没有前像 |
| `SOURCE_SHA256.json` | 每个目标的完整 SHA256、未改读取器/接口前提、输入包与来源锚点 |
| `tests/`、`tools/` | 后端 35 项、前端 22 项及离线运行/源码门禁/补丁校验工具 |
| `test_support/` | 可复现所需的冻结测试依赖；其中 upstream 的现役部署 SHA 未获证明，不是发布源码 |
| `reports/` | 原始失败日志、最终成功日志、独立审查、来源清单、合成性能测量 |
| `reference/` | 上传的修复要求与精简历史 counterfactual 证据；未改写 |
| `FILE_MANIFEST.json` | 包内各文件的大小和 SHA256；清单自身不自引用 |

不要将 `after/` 或 `test_support/` 当成完整 app 目录。产品补丁不包含 owner 产物、行情数据、生产依赖或编译 bundle。

## 基线身份

报告中的 release：`stage_r4_manager_r2_owner_input_r1_fused_r1`；manifest SHA256：`fd7f21af0205b9d25a8ab5d33592aff42bf76c0419799b7c1724b94a286aeb86`。这是输入证据记录的身份，不是本轮读取现役服务的结果。

上传 ZIP SHA256：`c8e8f42a108d144ab2a8182c516b7c0173f55cde8566d3d630709151303b5da4`。

缺失前像的检索及独立交付分支父提交为 `c0fc35c7b39502f49e43c2e75139dad7822091cf`。这个 Git 提交是来源锚点，**不是现役部署基线**；`SOURCE_SHA256.json` 才是本补丁的逐文件应用条件。精确匹配恢复了三个模块；`existing_materials.py` 的旧 canonical 变体不匹配，采用匹配报告 SHA 的 API 变体，过程完整保留在 `reports/resolved_preimages.json`。

## 不能被本包结果替代的事实

历史全局 registry 指纹过宽耦合已获 counterfactual 支持；那次 live mismatch 的唯一 changed field 仍为 `CANNOT_CONFIRM`。新合同下无关 registry 变化不应影响已消费材料身份，但实际材料变化必须继续 stale 或被原读取器拒绝。旧计划不得重封或自动提升为 CURRENT。

本包不产生 target `20261009` / publication `20261008` 的公告导入结果，也不证明 HK target membership authority、六日成交量量纲/finality 或全市场 US coverage。研究安全字段保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

## 独立交接位置

仓库 `lexi2016/v4`，新分支 `chat/manager-live-ui-api-repair-20261010-r1`，交接目录 `handoff/manager-live-ui-api-repair-20261010-r1`。本目录的字节和清单会按固定提交读回校验。下载 ZIP 根目录另附 `GITHUB_SYNC_RECEIPT.json` 记录实际提交及读回结果；它是包外同步回执，不属于运行补丁或本目录的自包含文件清单。
