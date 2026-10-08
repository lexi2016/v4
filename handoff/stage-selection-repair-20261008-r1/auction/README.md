# Issue #28 · A 股 09:25 昨收保留修复

## 已完成的候选及范围

基线为私有仓库 `lexi2016/v4` 的冻结提交 `00524e9050fe212f87911b56eea1c2db719dd94b`，来源为 `handoff/stage-selection-issues-20261008`。本包交付三个不同字节文件：canonical builder、实际 Stage builder、两侧共用的 selector。前像来自该提交的逐文件冻结清单；后像复用了经本次重新审阅、重新运行测试的先前候选，没有另造实现。

两个 owner 分别运行同一组 31 项回归。每侧修复前 **24 FAIL / 7 PASS，退出码 1**；修复后 **31 PASS / 0 FAIL，退出码 0**。这些是作者在 Linux 的隔离源码测试，包含真实导入的 builder、selector、SelectionStore、consumer，以及从固定 API 源码抽取的完整 GET route 经 FastAPI TestClient 的 HTTP 序列化。当前完整 owner 应用、Mac、8873 实例、页面及自然时段均为 **NOT_RUN**。本结果不构成独立验收或部署批准。

## 根因与最小修改

两个版本的 `stage_center/_live_collectors_parts/selection_builder_registry.py` 均在 `STAGE_0925` 的行映射里漏掉 `prev_close_price`。原始 fixture 的 100 因而没有进入 selector；现每个 builder 只增加一行原值传递。

`stage_center/_selection_parts/a_auction.py` 原来把未知日涨幅的 `qmt_gap_pct` 输出成 `0.0`。此外，通用 card helper 会在 `current_change_pct=None` 时以 last/open 计算窗口涨幅，后展开的 `**card` 又覆盖了 selector 的日涨幅；竞价 open/last 同价时便出现假 0。后像把非正数及无法解析为有限数值的昨收规范为 null，在 card 展开后明确写回竞价价/昨收的日涨幅，并让 `qmt_gap_pct` 同样保持 null。缺失原因进入独立字段和 `lane_evidence`。

| 输入状态 | `prev_close_price` | 两个百分比 | `current_change_pct_missing_reason` |
|---|---:|---:|---|
| 昨收 100、竞价价 105 | 100 | 5 | null |
| 昨收 100、竞价价 100 | 100 | 0 | null |
| 昨收不存在、null、空字符串 | null | null | `PREV_CLOSE_PRICE_MISSING` |
| 昨收 0、负数、文本、NaN、±Infinity、boolean | null | null | `PREV_CLOSE_PRICE_INVALID` |
| 昨收有效、竞价价缺失 | 100 | null | `AUCTION_PRICE_MISSING_OR_INVALID` |

### 为什么保持 schema/codec/API 字节不变

已补齐并分别 pin 的历史 `selection.py`、`store_publication.py` 和 `store_verification.py` 明确约定：`artifact.csv` 保留 12 列 V1 header，完整 V2 行保存在 manifest 的 `selection_envelope`，由 receipt、latest、run identity 绑定。冻结的 `schema_values.py` 本来已有 V2 `current_change_pct`，只是 V1 CSV 不带该列。新测试验证了实际发布、文件读回及 consumer 返回的完整行，而非把 CSV 的投影当成唯一载体。

因此本候选不扩 CSV header，也不改变旧 V1/V2 schema 或 codec。新缺失原因同时进入 legacy CSV 的 `lane_evidence`；完整价格、百分比和独立原因字段经 manifest envelope 持久化。修改 manifest 中的昨收会触发原来的 manifest SHA mismatch。

可用的 A 池固定 app 后像中，`project_shared_selection` 保留整行；真实 `stage_workbench` 普通路径调用这个函数。隔离测试执行了完整这些函数及原绑定常量，没有复刻它们的结果。没有复现出需修改的 API 投影代码，故 API 后像不增加修改。

## owner 与精确文件指纹

完整文件位于 `before/source/<owner>/...`、`after/source/<owner>/...`。`SOURCE_CHANGES.json` 还记录 bytes 和 Git blob SHA-1。

| 应用 owner / 相对路径 | 前像 SHA-256 | 后像 SHA-256 |
|---|---|---|
| canonical · `stage_center/_live_collectors_parts/selection_builder_registry.py` | `8b3552498b125ae90c56964799f3cf0e644a077243f7be4c37ea23261214379a` | `7fa71ee1a4b96f6f53d49467fcb296969104e851949234849fd256a5372d5725` |
| active_stage_reference · 同一路径 | `5b315c482723f4bbfb187e36241ea422f2a59518a2056be037d1fdbe2f00eb22` | `409274a2adace19f22ef6d19cdbc7e5291b58fd9944d39239abbffd90ab1f6e4` |
| canonical + active Stage · `stage_center/_selection_parts/a_auction.py` | `d0a96edcb4d87f223b117917a8f0d68276bd088a88abe8f787d245c8e1c669ad` | `1a85982c4cc70656f74f5d9b3e0b475425a7eb17645ab014c03bef587ab13bfe` |

selector 只存一份完整 canonical 前后像，依据原 `identical_active_stage_mappings` 同样应用于实际 Stage；不能把 canonical 的 45 KB builder 覆盖实际 Stage 的 22 KB builder。`patches/canonical.patch` 和 `patches/active_stage_reference.patch` 分别针对相应 owner 根，均含其 builder 与共用 selector 两个修改。

## 排名、算法与历史产物

原公式、系数、分数 0–100 边界、Python 稳定排序和 Top10 截取都保持。缺失 gap 在**内部评分公式**中仍使用原来的中性项；对外观测百分比与该评分回退分开。此举恢复已有真实输入，会改变新候选的分数和排名。

fixture 的金额均为 10,000,000，其他奖励为零；其量能奖励为 0.25。输入顺序为下跌、上涨、平盘：

| 竞价价 / 昨收 | 修复前分数 / 排名 | 修复后分数 / 排名 |
|---|---|---|
| 95 / 100 | 50.25 / 1 | 0.25 / 3 |
| 105 / 100 | 50.25 / 2 | 100 / 1 |
| 100 / 100 | 50.25 / 3 | 50.25 / 2 |

两侧的算法清单 SHA 都仍是 `eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2`；最终行变化会形成不同 run identity。100/105 单行 fixture 从 `run-6e97de84d03150186a654435` 变为 `run-a928ac5bd0bfa871b78301ef`。这是合成证据，不是 10/8 业务运行身份。完整对应 artifact/manifest/receipt SHA 见 `logs/*_pipeline.json`。

旧版本发布的 fixture 用修复后的 store 仍能原样读回；对同一 slot 发布修复后的不同 envelope 仍触发 `selection slot conflict`，原 trio 和 latest 字节保持不变。旧运行的假 0 也没有被读取过程偷偷改成新语义。没有重跑、覆盖或宣称修复已保存的 10/8 业务结果。

## 测试、输出与复跑

测试覆盖真实 adapter 的 100/105、缺失及非法昨收、观察到的真 0、竞价与 last 不同、缺竞价价原因、原排序/Top10 边界、分数及排名变化、原有 schema codec、manifest 篡改拒绝、旧 run 读回与 slot 冲突、日期/竞价窗口拒绝，以及实际 GET route 的 A/HK 分离、null JSON、价格、run/artifact identity 和只读性。

实际环境：Python **3.14.7**、pytest **9.1.1**、FastAPI **0.142.4**、Starlette **1.7.0**、httpx **0.28.1**、anyio **4.15.1**，Linux x86_64。每次测试有一项已保留的 StarletteDeprecationWarning（已装 httpx 的 TestClient 接口弃用提示）；没有安装或升级依赖。

在本次工作根执行以下命令。before 预期失败，故应保留退出码 1；after 预期退出码 0。

```bash
ISSUE28_PY=/workspace/scratch/25c09a595aec/issue28/references/work/test-venv/bin/python
"$ISSUE28_PY" delivery/auction/run_focused.py --owner canonical --phase before --output work/auction/reviewer_logs
"$ISSUE28_PY" delivery/auction/run_focused.py --owner canonical --phase after --output work/auction/reviewer_logs
"$ISSUE28_PY" delivery/auction/run_focused.py --owner active_stage_reference --phase before --output work/auction/reviewer_logs
"$ISSUE28_PY" delivery/auction/run_focused.py --owner active_stage_reference --phase after --output work/auction/reviewer_logs
```

在完整 owner 源码根验收时，应将相同 fixture 接入 owner 自身测试入口；本包的已记录结果使用 `assemble_support.py` 明确组装源码依赖。`run_focused.py` 为每次运行保留原始 stdout、JUnit、命令、退出码、环境和每个载入文件的指纹。`observe_pipeline.py --owner <owner> --phase <before|after> --output <scratch-dir>` 可复现机器管线取值。

`RESULTS.json` 汇总已记录结果，`SUPPLEMENT_MANIFEST.json` pin 30 个未修改支持文件，`PACKAGE_MANIFEST.json` 列出本包全部交付字节。所有 fixture 都是合成行；输出不含当前原始行情或完整业务响应。

## 依赖缺口与 Luna Max 后续检查

这 27 份 Issue28 冻结源码不含完整 facade、publisher、consumer 和 Stage namespace。30 个 support 文件逐项核对了 bytes/SHA/Git blob 或记录中的固定 blob；其中公式、store、consumer 主要来自 20261005 的历史源码，**不能冒充 10/8 实际 owner**。测试中的 `_namespace.py` 使用固定的历史 API `read_global` helper 代入缺失 Stage helper；这是明确的 harness seam。

API 参考后像为提交 `4ad7cc52257b49470b3004ebfee9649af43189dd` 的 `handoff/a-preselection-source-20261008/canonical/apps/api/v35_api/app.py`，SHA `435dcedd3beb43bf4a0ccb35ff6fc033ba536a940990c36f5f23358f5492b590`。本次执行的是其中完整普通 GET route、projection、HK 显示 helper 和原常量；没有调用 `create_app`、无关 router、middleware、真实配置或 8873 网络服务。

Luna Max 在真实 owner 上应先取得并单独 pin `stage_center/selection.py`、`stage_center/consumer.py`、`_selection_parts/primitives_io.py`、`store_publication.py`、`store_verification.py`、两个 Stage `_namespace.py` 和当前 API `app.py`，核实它们仍按完整 envelope 返回行。若实际 owner 的代码不同，应只在该 owner 的实际前像上补齐对应字段保留，再独立运行同样 100/105 与缺值 fixture；本包没有用历史支持源码整体覆盖运行依赖。现有固定 API 源码未显示额外丢字段点，因此没有凭空新增 API 修改。

完整应用导入、当前 API owner、Mac Python 3.14.6、当前服务/配置、独立 Reviewer、部署、线上 API/UI 及自然时段验收分开处理。作者仅完成候选和上述隔离验证。应用前按两种 builder 与共享 selector 的前像 SHA 精确检查，在隔离 owner checkout 中应用补丁，再由不同身份 Reviewer 验证；活动 release、已保存结果、BUY/模型、经理台、Vibe8910 和服务任务均未修改。
