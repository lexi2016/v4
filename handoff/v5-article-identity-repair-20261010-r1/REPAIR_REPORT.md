# 完整原 builder source 绑定说明

## 1. 为什么 archive 本身的 SHA 不够

固定原 `domains/research.py` 的 `_dedupe_tuple` 从 timeline 输入取 `stock_code/code`、`source_title/title`、`url/source_url`、`source_path`、`source_name/source_type`、`claim_type or evidence_level`，逐项 strip/lower，再用 U+001F 拼接。原 builder 使用该元组生成 dedupe_key，并以 archive_date、U+001E 和元组生成 article_id。去重还涉及原始重复行、证据长度合并及事件时间。

原 archive v1 不保留所有这些输入；其 validator 只检查两个键的格式/唯一性。给 archive 再加一份 SHA 或从 article 猜回 claim_type 都不能建立原输入证明。本修复保留并校验完整 source，包括原 builder 消费的 optional 部分。每日聚合、bridge、raw/research items、manifest 等不被裁剪为方便的单篇输入。

固定证据：`handoff/v4-running-source-20261005/canonical/domains/research.py`，SHA-256 `b77cc0d3c9ec36eeee3e6cab207945a783b0352a703efdb5c8e2f7f17966506f`。原问题与验收约束见相邻旧 handoff；该目录未改。

## 2. 复用的原 owner 与原 source 文件

| 职责 | 复用接口 / 路径 |
|---|---|
| 原研究 source owner | `ops.collect_hourly_research_input.build_hourly_research_input(*, data_root, business_date, slot)` |
| 原完整 source normalizer | `domains.research_hourly.build_research_lane_snapshot` 及四个 parts |
| 原 source 输出名 | `research/incoming/{trade_date}/{slot}.json` |
| 原 runner 的 source witness 命名合同 | `research/hourly/source/{sha256}.json` |
| 原 archive builder | `domains.research.build_research_archive(source, *, source_input_sha256)` |
| 原 archive 保存/读取 | 既有固定 `ResearchArchiveStore`，仍用 REPLAY 和现有独立 reader |
| 安全 IO | 既有固定 `infrastructure.owned_io.SafeRoot` 的 dirfd/no-follow/require_absent |

原 collector 源码 SHA-256 为 `767eaae79e2436284c0cf73626fd114a92448d3aff37b69c378862aae141a7fa`；原 runner 源码 SHA 为 `eaf56ebec0d821fe5b8548ceeafe8070bd67245d3159f94d1431a7d87795f98a`。这两个原文件均未修改，且本次不调用完整 hourly runner。

V5 新 capsule 用逐字相同的七份 collector/normalizer/builder 文件及一份明确说明的 namespace support，来源、Git blob SHA、SHA-256、字节数都列在 `V5/contracts/archive_builder_source_manifest.json`。该 descriptor 规范 SHA/PIN 为 `6624676cc21ec1ec729e6b7ad6a52688d467aeda907db5870d26a62ceb920dea`。

固定 handoff 缺少研究 parts 实际 `_namespace.py`。本次采用同一固定 commit 已提供的 generic namespace 实现作为**V5 结构支持**，它与已有完整参考源码中的研究 namespace 字节相同，SHA 为 `45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1`。这不是声称缺失文件曾在原固定目录存在。Mac 的完整原源码实际路径仍必须通过该 SHA gate；不符则拒绝，不能临时找近似模块放行。

原 archive reader capsule 与其 PIN `33a4b671c4b2b6b89db2c3e8bed7efdc8d1ee8fc983ff005d2ade2692d47b2a4` 均保持不变。新闭包由 V5 loader 显式合并，重名不同字节直接拒绝；原模块只在隔离 child 中加载。

## 3. 新 request 与 owner receipt

### Source owner 输入

`run_build`/`archive_builder_v1.py` CLI 接收精确四字段：

```text
capture_root: 绝对、规范、无 symlink 祖先，标记 .v5-archive-acquisition
capture_files: {本次明确相对路径: SHA256}
receipt: {path, sha256, bytes}，本次 acquisition_receipt.v3.json
status: {path, sha256, bytes}，本次固定日期/slot 的状态文件
```

只允许本次 acquisition 回执、它声明的三个产物/全部页以及该 status。没有 latest、glob 或前一 READY 回退。status 的 run/date/slot、相对状态路径、三个实际 capture 路径及 acquisition evidence 必须一致。原 READY_EMPTY 行为保留为空来源，不替用旧 READY。

实际原 collector 仍负责 source 内容。V5 在调用边界限制 `_latest_zsxq_status`/`_read_json` 可见输入，限制唯一写入目的地，并记录原时钟；没有重写 stock evidence、行业、主体、dedupe 或聚合算法。

### 源文件及返回值

原 owner 在内存生成完整对象后，经 V5 安全 IO 以原 serializer 输出：

```python
json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode('utf-8')
```

实际保存字节无 BOM/额外换行。先读回 source，再计算 SHA；hash witness 复制这份 bytes。绝不把读取后的任意重新序列化当成收到的 source SHA。V5 IO 使用原 `SafeRoot.write_bytes(..., require_absent=True)`，替代原 collector 可预测临时 Path writer；原算法/源码文件不修改。

返回值保留 `capture_root,capture_files,receipt`，另有 `builder_source,builder_receipt,archive_v1`、request/source identity、`readback=MATCHED` 和 false 安全字段。MATCHED 是产品接口设计的返回字段；本次未运行该接口，因此不是本次的产品执行结果。

### Owner receipt 内容

`external_sources/zsxq_hourly/{run_id}/builder_source_receipt.v1.json`，schema 为 `v5.archive_builder_source_receipt.v1`，精确包含：

- run_id、trade_date、slot、capture_root；capture receipt 与 status 引用。
- `builder_source`：`research/hourly/source/{sha}.json` 的 path/SHA/bytes。
- `source_original`：同批 `research/incoming/{day}/{slot}.json` 的 path/SHA/bytes。
- `owner_result`：原函数返回完整结果的 path/SHA/bytes，文件在本次 run 内。
- `files`：完整 capture/status/source/witness/result 清单，逐项 SHA 与字节数；不自引用 receipt。
- 固定 owner capsule 身份；owner_started_at、owner_completed_at、source_available_at、三个实际 clock_calls。
- 五项固定 false 安全字段。

receipt 的 SHA/bytes 由外层 `builder_receipt` 和 `capture_files` 绑定。自引用哈希没有用于证明。完整 file set 必须相等；有文件但未声明，同样不得读取。

## 4. 原 builder 身份证明如何进入原链路

既有 importer 七字段为 `capture_root,capture_files,receipt,builder_source,builder_receipt,archive_v1,output_root`。缺新增引用没有旧 v2 降级。旧 v1 仍交原 validator，不伪补证据。

导入先保留原格式与文章语义拒绝，再在任何 archive 成功写入前执行完整证明：

1. 每个引用都核精确 path/SHA/bytes；source、原 source、owner result、archive 的 source_input_sha256 必须一致。run/date/slot/status/owner identity 独立检查。
2. 对原 owner 输入限定本批 status/summary，在只读 BoundPath 中重放原 normalizer 和原 collector。原时钟从 receipt 精确重放。产生的完整 source **字节必须完全相等**。
3. 原 owner result 也比较完整对象与规范字节。
4. 调原 `build_research_archive`，比较完整 v1 对象与规范 SHA；身份键及 stock_pool 等其他字段都在核对范围。
5. 完整 v2 与期望扩展再比较规范字节，避免 Python 的 bool/int 或 int/float 等值掩盖 JSON 类型变化。

原 store 保存后立即读回，并通过独立 archive reader 再读。每次 v2 reader 都重复 source/owner/builder 验证。新增文件扩展原 archive allowlist，原 manager 动态复用该 allowlist；worker identity 同时包含 adapter 与 capsule。现有 `current_us_research.archive_import` 无需新增平行入口，返回 binding 仍进入原 manager refresh/read 与同 run plan。

## 5. 时间语义与非覆盖边界

新增排序为：acquisition.source_payloads_available_at ≤ owner_started_at ≤ owner_completed_at ≤ source_available_at ≤ v2.source_generated_at ≤ 当前时间。

原 normalizer 两次 naive `datetime.now()` 记录原值及当时 UTC offset；原 collector 一次 Shanghai `now()` 记录 aware 值。重放顺序、模块、timezone、字段集合和边界都核对。原 collector `min(now, slot cutoff)` 保持原行为，不能用它替代真实取得或 source 可用时间。历史发布时间继续保留原微秒精度，取得/可用时间不能倒填。

每个 slot 只容许一个新 source 尝试；锁目录通过原 SafeRoot 的 dirfd 创建。已有 source、同名 witness/result/receipt 或部分尝试不覆盖/恢复。发生失败可以留下隔离根内的部分 source/锁用于诊断，但没有成功 owner receipt 或 archive manifest 就不能算准入成功。不得删除既有证据以强行重试；另建获准的新合成根。

原临时文件名 symlink 不再被原 Path writer 打开；目的 source 已有 symlink 由安全 IO/不覆盖约束拒绝。对应两个候选同时检查 sentinel 及 symlink 字节/指向不变，未执行。

## 6. 可识别拒绝与证明限度

| 条件 | 主要预期原因 |
|---|---|
| 缺 builder source / owner receipt | `ARTICLE_V2_BUILDER_SOURCE_REQUIRED` |
| capture 外层 SHA 或引用 bytes/SHA 不符 | `ARTICLE_V2_CAPTURE_SHA` / `ARTICLE_V2_FILE_SHA` |
| 原 source、witness、owner result、archive source SHA 不一致 | `BUILDER_V1_SOURCE_SHA` |
| run/date/slot/status 不一致 | `BUILDER_V1_DATE_RUN_BINDING` / `BUILDER_V1_STATUS_BINDING` |
| 固定源码身份、完整 files 或时钟转录错误 | `BUILDER_V1_OWNER_IDENTITY` / `BUILDER_V1_FILE_SET` / `BUILDER_V1_CLOCK_TRANSCRIPT` |
| 即使全套重新哈希仍不能由原 owner 输出 | `BUILDER_V1_SOURCE_REPLAY_MISMATCH` |
| 身份键或其他原 archive 字段改变 | `BUILDER_V1_ARCHIVE_MISMATCH` |
| v2 类型/内容修改 | `ARTICLE_V2_ARTICLE_OR_PAYLOAD_CHANGED` |
| v2 生成早于完整 source 可用 | `ARTICLE_V2_IMPORT_CLOCK` |
| reader 未声明必要 source/receipt | `ARTICLE_V2_UNDECLARED_FILE` |

物理文件缺失保留底层 FileNotFoundError；既有正文、URL、组、issuer、status 相对路径和 PIT 拒绝理由不改为笼统身份失败。

这些校验把一批声明的 bytes、原 owner 行为和完整 builder 结果连起来，不具备外部可信签名或独立真实来源见证。攻击者若控制全部上游 capture 与时钟，数学上的重放自洽本身仍不能证明自然来源。因此真实同批 source 证明继续 **CANNOT_CONFIRM**，所有产品测试 **NOT_RUN**，自然资格不提升。

完整 hourly runner 原先还有其独立 stage/PIT gate；本次只复用 source 构建和 archive builder，不填补或声称已验证完整 runner、真实 analyzer、当前 US 文件或生产入口。
