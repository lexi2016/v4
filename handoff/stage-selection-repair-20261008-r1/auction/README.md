# Issue #28：A 股 09:25 昨收与真实涨幅候选修复

状态：**CANDIDATE_SOURCE_TESTED_IN_BOUNDED_HARNESS**。冻结基线为 `lexi2016/v4@00524e9050fe212f87911b56eea1c2db719dd94b`。这里只交付源码候选、最小补丁和可复验的离线证据；完整现役应用、正式 API/页面及自然运行仍未验收。

候选修复恢复了 `prev_close_price` 的适配传递，并让缺少有效昨收时的 `current_change_pct`、`qmt_gap_pct` 保持 `null`。昨收 100、竞价价 105 的合成输入经过真实导入的 adapter → selector → CSV/manifest/receipt publication → verified read → read-only consumer 后，仍为昨收 100、涨幅 5%。API 投影函数也保留这两个值；该项是明确标注的 AST 隔离投影测试，不等于完整 FastAPI HTTP 验收。

## 修改范围与 owner

canonical 身份为 `v4_app` 工作树（HEAD `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`，含既有修改）；active Stage reference 为 `com.lexi.stage-center.scheduler` 绑定的 Issue23 R3 helper app。本补丁以前像逐文件 SHA 为准，未声称本机运行该 owner。

每个 owner 仅改两处源码文件：

| Owner | 文件 | 修复 |
|---|---|---|
| canonical | `stage_center/_live_collectors_parts/selection_builder_registry.py` | 09:25 适配字典增加一行 `prev_close_price` 传递 |
| active Stage reference | 同名 builder | 在其独立前像上增加同一行；保留该 owner 其余版本内容 |
| canonical / active Stage 显式同字节映射 | `stage_center/_selection_parts/a_auction.py` | 昨收只接受可解析、有限且大于零的数；缺失/无效时不给伪造百分比；在 `**card` 后写入竞价日涨幅，避免通用 card 的 last/open 回退覆盖 `null` |

`after/canonical` 与 `after/active_stage_reference` 是分别绑定前像的完整修改后文件。两个 patch 均在对应精确前像上实际执行 `git apply --check`、应用到临时副本并校验后像 SHA；见 [patch_check.json](logs/patch_check.json)。不要用 canonical builder 覆盖 active builder。

| 文件身份 | 前 SHA256 | 后 SHA256 |
|---|---|---|
| canonical builder | `8b3552498b125ae90c56964799f3cf0e644a077243f7be4c37ea23261214379a` | `7fa71ee1a4b96f6f53d49467fcb296969104e851949234849fd256a5372d5725` |
| active Stage builder | `5b315c482723f4bbfb187e36241ea422f2a59518a2056be037d1fdbe2f00eb22` | `409274a2adace19f22ef6d19cdbc7e5291b58fd9944d39239abbffd90ab1f6e4` |
| 共用 auction selector | `d0a96edcb4d87f223b117917a8f0d68276bd088a88abe8f787d245c8e1c669ad` | `defb01fca7d0a067bf214e794810fac7d19fdbd3fbcd78b8263fe93603952e93` |

完整路径、字节数和复用说明见 [CHANGE_MANIFEST.json](CHANGE_MANIFEST.json)。没有更改 BUY、模型、经理台、Vibe8910、评分公式、排序函数、推荐数量上限、Stage 输入池边界或任何服务配置。

## 根因与持久化合同的澄清

1. **adapter 丢字段。** 冻结 canonical builder 299–318 行和 active builder 22–37 行的 09:25 输入字典没有 `prev_close_price`，但同文件盘中分支已把它传给 `qmt.lastClose`。该缺陷使实际 selector 无法使用原始输入中的昨收。[冻结 canonical builder](https://github.com/lexi2016/v4/blob/00524e9050fe212f87911b56eea1c2db719dd94b/handoff/stage-selection-issues-20261008/source/canonical/stage_center/_live_collectors_parts/selection_builder_registry.py)

2. **两个缺值回退制造“0%”。** 冻结 selector 87 行直接把未知 `qmt_gap_pct` 写成 `0.0`。此外，selector 先产生 `current_change_pct=None`，随后 105 行的 `**card` 又将其覆盖；历史支持源码 `primitives_io.py` 的 card helper 101–103 行会把未知 daily change 回退为 last/open。竞价 open=last 时该回退产生 0%，不是观察到的昨收涨幅。本补丁把最终 daily change 写在 `**card` 之后，修复限制在竞价路径。[冻结 selector](https://github.com/lexi2016/v4/blob/00524e9050fe212f87911b56eea1c2db719dd94b/handoff/stage-selection-issues-20261008/source/canonical/stage_center/_selection_parts/a_auction.py)；[历史 helper 支持](https://github.com/lexi2016/v4/blob/00524e9050fe212f87911b56eea1c2db719dd94b/handoff/v4-running-source-20261005/canonical/stage_center/_selection_parts/primitives_io.py)

3. **常规持久化没有要求把完整字段塞进旧 CSV。** `SELECTION_ARTIFACT_FIELDS_V2` 本来已经含有 `current_change_pct`，因此“所有 schema 都没有涨幅”不准确。真实 `SelectionStore.publish` 有意写固定 V1 的 12 列 `artifact.csv`；完整行放在 manifest 的 selection envelope 中，receipt 绑定 manifest SHA，并由 manifest、receipt 和 selection identity 校验。真实 `read_verified` 返回这个已验证的完整 envelope。该设计允许旧 V3 CSV 消费者继续读取同一 run。[历史 publication 支持](https://github.com/lexi2016/v4/blob/00524e9050fe212f87911b56eea1c2db719dd94b/handoff/v4-running-source-20261005/canonical/stage_center/_selection_parts/store_publication.py)；[历史 verification 支持](https://github.com/lexi2016/v4/blob/00524e9050fe212f87911b56eea1c2db719dd94b/handoff/v4-running-source-20261005/canonical/stage_center/_selection_parts/store_verification.py)

   因此保留 `schema_values.py` 和 `artifact_codec.py` 的原字节，避免修改 V2 字段集合导致历史 V2 CSV 拒读。测试实际调用 codec、写入旧 CSV、验证三件套并读回完整字段；还覆盖 V2 的 `None / 5 / 0` 兼容解码。缺失原因同时写入已有 `lane_evidence` 列，旧 CSV 的解码也能保留原因。仅拿孤立的旧 V1 CSV 无法重建昨收；消费者须使用已经存在的 verified-envelope 合同。

4. **现有 API 投影无需改变。** 冻结 A 池候选 `app.py` 的 `project_shared_selection` 对 A 行使用完整字典透传，`StageSelectionConsumer._project_market` 也 deep-copy 完整行。这里没有额外的价格重算或 schema 截断。使用 app SHA `435dcedd3beb43bf4a0ccb35ff6fc033ba536a940990c36f5f23358f5492b590` 进行的投影测试明确不代表现役 R3 API 的完整依赖或运行身份。[冻结 API 参考](https://github.com/lexi2016/v4/blob/00524e9050fe212f87911b56eea1c2db719dd94b/handoff/a-preselection-source-20261008/canonical/apps/api/v35_api/app.py)

## 缺值语义

| 合成输入 | `prev_close_price` | `current_change_pct` / `qmt_gap_pct` | 行级原因 |
|---|---:|---:|---|
| 昨收 100，竞价 105 | 100 | 5 / 5 | 无缺失原因 |
| 昨收 100，竞价 100 | 100 | 0 / 0 | 有效平盘，保留真实零 |
| 昨收字段缺失、`None`、空串 | `null` | `null` / `null` | `PREV_CLOSE_PRICE_MISSING` |
| 昨收 0、负数、文本、NaN、Infinity、布尔值 | `null` | `null` / `null` | `PREV_CLOSE_PRICE_INVALID` |
| 有有效昨收，竞价价格缺失/无法解析 | 保留有效昨收 | `null` / `null` | `AUCTION_PRICE_MISSING_OR_INVALID` |

原因以 `current_change_pct_missing_reason` 字段出现在完整行中，并以 `current_change_pct_missing_reason=...` 出现在 `lane_evidence`。有效行不新增空原因键，避免无必要地改变已正确直连 selector 输入的 selection identity。通用评分公式原本对未知 gap 使用中性贡献；该内部评分策略保留，不能把其内部数值回退当成观察到的涨幅。

## 评分与排名影响：有变化，来源是恢复输入

三条合成输入均为昨收 100、成交额 1000 万元，输入顺序为 A.000101、A.000102、A.000103。真实 adapter 的前后测量如下；两个 owner 结果一致。[前像测量](logs/canonical_before_semantics.json)、[后像测量](logs/canonical_after_semantics.json)

| 合成代码 | 竞价价 / 实际涨幅 | 前 score / rank | 后 score / rank |
|---|---|---|---|
| A.000101 | 95 / −5% | 50.25 / 1 | 0.25 / 3 |
| A.000102 | 105 / +5% | 50.25 / 2 | 100 / 1 |
| A.000103 | 100 / 0% | 50.25 / 3 | 50.25 / 2 |

修复前 adapter 把三行昨收全部丢掉，使 gap 贡献均为零。修复后原公式用 −5 / +5 / 0 计算，并继续执行既有 0–100 clamp、score 降序、Python 稳定同分顺序与 Top-10 截取。12 个同分输入的测试保留输入前 10 行及完整 source/requested count。

直连 selector、已经带合法昨收的对照输入，**完整 envelope SHA 前后相同**：`f6270f52e2d422a72e47758aeeefd6e35eedca73997270c0754b224276f2afaa`。评分实现 `market_quality.py` SHA 前后相同：`726cd4987a070bf78ac7416756f3cbba86633b1176f6f43535ac747263474b3f`；声明的 algorithm SHA 也保持 `eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2`。

负数昨收的直连 selector 对照从不合法 −205% / score 0 变为 `null` / score 50.25，属于拒绝无效输入后的中性评分效果。真实 10/8 的 171 行排名影响未运行，不能把此三行例子的名次变化当成真实业务结果；没有重跑或覆盖已保存的 10/8 选择。

## 验证结果与边界

运行环境：Linux、CPython 3.14.7、pytest 9.1.1。每个 owner 执行同一组 24 项，不是 48 个不同测试。

| Owner / 阶段 | 结果 | 日志 |
|---|---|---|
| canonical 前像 | 18 FAIL / 6 PASS；均为所预期的断言失败 | [before](logs/canonical_before.log) |
| canonical 后像 | 24 PASS | [after](logs/canonical_after.log) |
| active Stage builder 前像 | 18 FAIL / 6 PASS | [before](logs/active_stage_reference_before.log) |
| active Stage builder 后像 | 24 PASS | [after](logs/active_stage_reference_after.log) |
| 缺失 namespace 的原切片直接导入 | FAIL，`ModuleNotFoundError` | [依赖缺口](logs/canonical_before_missing_namespace.log) |

24 项中 21 项使用真实 Python 模块导入、真实 `SourceResult` / `AcquisitionPlan`、实际 adapter facade、selector、codec、文件持久化、SHA 验证和 read-only consumer；包括修改落盘昨收后必须拒绝、错日期拒绝、非竞价时间窗口拒绝。3 项额外检查 API 投影，是 **AST_ISOLATED_PARTIAL**。

切片缺少 `stage_center/_selection_parts/_namespace.py` 和 `_live_collectors_parts/_namespace.py`；前者定点 GitHub 读取也失败。测试用同一冻结仓库其他 API 子包中的 527 字节 `read_global` helper 进行明确替代。其余支持来自 10/5 历史 canonical 切片，逐项固定仓库路径、blob 与 SHA 见 [SUPPORT_INDEX.json](SUPPORT_INDEX.json)，不冒充 10/8 active Stage 的闭包身份。

**NOT_RUN / CANNOT_CONFIRM：**完整项目测试套件；完整现役 owner 闭包；FastAPI create_app/startup/HTTP/middleware；8873 API/UI 读回；目标 Mac Python 3.14.6；真实行情与原 Stage collector；实际 Stage runner、自然时段、scheduler；真实 171 行分数排名复算；部署与活动 release；其他 A/HK 业务验收。源输入覆盖缺 6–7 只的问题不在本修复内。

## 重现

`reproduce.py` 仅在临时目录组装测试支持源码。提供冻结 commit 的 checkout 或保留相同仓库相对路径的稀疏源码缓存，每个所用文件先检查 SHA。

```bash
python3.14 reproduce.py --repo-root /path/to/frozen-v4 --owner canonical --phase before --log-root /tmp/auction-before
python3.14 reproduce.py --repo-root /path/to/frozen-v4 --owner canonical --phase after --log-root /tmp/auction-after
python3.14 reproduce.py --repo-root /path/to/frozen-v4 --owner active_stage_reference --phase before --log-root /tmp/auction-stage-before
python3.14 reproduce.py --repo-root /path/to/frozen-v4 --owner active_stage_reference --phase after --log-root /tmp/auction-stage-after
```

加 `--without-namespace-support` 可复现原切片无法直接导入的缺口。`logs/*.json` 记录实际命令、解释器、平台、完整源字节身份、测试 SHA 与返回码。工作区实际使用的固定源码缓存为 `work/auction/frozen_test_support`，仅 32 个必要源码文件，属于测试支持而非部署应用；无需为 GitHub 再上传历史支持源码副本。完整 owner 树就绪时，`tests/test_a_auction_prev_close.py` 可直接用正常生产模块 imports 再验；完整 API 测试仍须另行完成。

`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false; DEPLOYED=false`。
