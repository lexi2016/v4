# Issue #28 continuation · 收盘复盘来源/PIT 不确定标记

## 结论与边界

本续批修复 Section 7 记录的第三项历史 P2：旧模型池缺少上游来源 manifest/receipt/provenance 时，复盘输出没有明确的来源/PIT 不确定原因。只改 `ops/build_close_review.py` 的一个条件；R1 交付目录、基础池 validator、模型输入、KPI、状态计算及发布方法都不改。

作者在固定源码及合成 fixture 上取得 **before 8 FAIL / 6 PASS（exit 1）→ after 14 PASS（exit 0）**。真实 `20260825` 原始池、复盘输出、历史 capture/manifest/receipt 没有提供；这项结果证明了通用代码分支的修复，**没有证明 8/25 历史数据已经恢复或已被重写**。

产品、测试、运行器与支持源码均位于本独立目录，路径从文件自身位置解析，可整体迁移。原始日志保留实际执行环境及命令，作为审计记录；运行器不使用日志中的绝对路径定位源码。

## 已确认的源码合同

产品前像来自提交 `00524e9050fe212f87911b56eea1c2db719dd94b` 的 `handoff/stage-selection-issues-20261008/source/canonical/ops/build_close_review.py`。

原 builder 先用 `CloseSnapshotStore`、`PreselectionPoolStore` 读取已经验证的本地产物，再由 `domains.close_review.build_native_close_review` 计算复盘，通过 `ReviewStore.publish_native` 发布。原来的唯一 PIT 标记分支是 `historical_provenance` 键存在；旧池没有该键时，来源引用缺口没有进入输出。

已从同一冻结提交的 `handoff/v4-running-source-20261005/canonical` 定点取得并核对 domain、ReviewStore 和 CloseSnapshotStore 的完整原始 blob。其合同是：

- native 输出 schema 为 `v3_5.close_review.v1`，诊断通道为既有的 `cannot_confirm` 列表。
- `ReviewStore` 对该字段要求 list，没有原因码白名单；已有 `HK_MODEL_SOURCE_PIT_AVAILABILITY_CANNOT_CONFIRM` 可以沿原 schema 发布和读回。
- local pool 的 artifact/manifest/receipt 校验，不能替代上游来源 manifest/receipt 或其历史可得性证明。
- 单独的来源 SHA 两字段存在也不构成本次新增的 PIT 验收。这个修复只保持既有普通池行为，没有据其存在赋予新的 `PIT_SAFE` 或自然执行声明。

`SOURCE_IDENTITIES.json` 列出 20 份精确身份：三份未修改的 Issue28 原文件、16 份固定历史支持源码和一份候选后像。每份都有 SHA-256、bytes、Git blob SHA；原始来源另有仓库路径及冻结 commit。支持源码是历史测试依赖，不能当作当前 Mac owner 的身份证明。

## 最小修改

原分支继续成立，并覆盖缺少任一上游引用的情况：

```python
if isinstance(preselection, dict) and (
    "historical_provenance" in preselection
    or not all(
        preselection.get(field)
        for field in ("source_manifest_sha256", "source_receipt_sha256")
    )
):
    reason = "HK_MODEL_SOURCE_PIT_AVAILABILITY_CANNOT_CONFIRM"
    if reason not in review["cannot_confirm"]:
        review["cannot_confirm"].append(reason)
```

没有新增 schema 字段或原因码，没有按 `20260825`、当前日期或机器时钟判断。没有补写 provenance、capture、run、source SHA 或自然执行标记。

| 输入类别 | 输出行为 |
|---|---|
| 缺 source manifest SHA | 增加已有来源/PIT 原因一次 |
| 缺 source receipt SHA | 同上 |
| 两字段都缺且没有 historical provenance | 同上；包括文档记载的 8/25 缺证据类别 |
| 原 `historical_provenance` 存在 | 保留原原因且去重 |
| 两 SHA 字段都有、没有 historical provenance | 与原输出逐字段相同 |
| exact absent-pool sentinel | 保留 `MODEL_0_2_SOURCE_MISSING`、0 模型行及原缺池原因，另附来源/PIT 原因 |
| 本地池 manifest/receipt 缺失、损坏或合同出错 | 原异常继续抛出，不转换成空池或可发布的警告结果 |

只追加诊断信息，不修改 domain 已计算出的状态。该变更不自动降级或升级模型资格，也不授权数据重建；任何以前已生成的 `MODEL_REVIEW_READY` 字面值仍按原 domain 行为处理，新增原因不等同于本批授予 READY。

### 产品指纹

| 文件 | Bytes | SHA-256 | Git blob SHA-1 |
|---|---:|---|---|
| `before/canonical/ops/build_close_review.py` | 6601 | `a361ae023285392ddf3b0e9674a9c506fae79252cc02c15df221ae09ba28e5aa` | `88977853aa8941ac69b25bb026516663e3789faf` |
| `after/canonical/ops/build_close_review.py` | 6843 | `59ac7798bcb1d54bbd11bbc61803997f36881a29cd1b82ecb663166791d5e0f2` | `d1662276cd5020533831cb866e7f05eb7183e7e6` |

`close_pit.patch` 针对相应 canonical owner 根的 `ops/build_close_review.py`。没有为实际 API、scheduler 或其他 owner 制作整文件覆盖版本；本机合入仍须先查当时实际 owner 的前像。

## RED / GREEN 与兼容性证明

14 项测试覆盖两个 fixture 日期（20260825 和 20260826），分别缺 manifest、缺 receipt、两者都缺，排除日期硬编码。所有 fixture 都是人为构造的 600 个收盘证券行和最多 100 个模型池行，不含用户业务行情。

测试运行真实 producer、domain、三个 store 的 schema 校验、磁盘发布和已验证读回，确认：

- 缺来源类别读回的 `cannot_confirm` 中新增原原因一次，model rows、KPI、row counts、schema、status 以及三个安全标记与 baseline 保持。
- 完整普通 SHA-pair 对照的整个 review 与 baseline 相同。
- 原历史 provenance 分支保持；固定原测试文件的 split-date fixture 函数通过 AST 原样抽取复用，没有改写 provenance 来让测试通过。
- input pool artifact、receipt、manifest 以及 close snapshot/receipt 字节在构建前后不变。
- native pool receipt 缺失、损坏以及 manifest 缺失分别继续抛错，且没有复盘输出被发布。
- 旧版本已保存的复盘及 receipt 在读取时原样保留，缺失的新原因不会被读取流程补写。原 `publish_native` 的显式重建/CAS supersession 行为未改变；测试没有声称对同一已保存日期执行 rebuild 会成为只读操作。

`logs/before.log` 是 8 项缺原因的断言失败，另 6 项兼容性对照通过，没有 collection/import error。`logs/after.log` 是 14 项全部通过，无 warning。对应 JSON 保存命令、退出码、环境及范围；JUnit XML 保存逐项结果。

Stage 实际 consumer 不在本限定来源集合中。fixture 明确传 `stage_selection_root=None`，真实 builder 走原有“七个阶段缺失”分支；harness 使用一份只要被构造就抛错的 **unused import sentinel** 满足导入。没有执行或冒充 Stage consumer、Stage 采集、API 或完整应用。

## 复跑

用 Python 3.14.7 / pytest 9.1.1 环境，在本目录运行：

```bash
python run_tests.py --phase before --output recheck
python run_tests.py --phase after --output recheck
```

`before` 应退出 1、14 项中 8 项失败；`after` 应退出 0、14 项通过。工作区现有解释器可通过外部绝对路径调用，但源码及 output 参数不绑定本次工作区位置。`recheck` 是调用者指定的新结果目录，避免覆盖已封存 `logs`。

原始完整应用测试模块未在此 fragment 上重新全量执行；本批仅使用新 14 项实际 store 测试验证具体变化和相邻错误路径。历史的 51 项通过、70/3 扩展结果不转算成本批结果。

## 后续与未执行项

独立 Reviewer 的前像合同判断已认可该窄条件；后像独立复跑结果由根线程在独立 review 目录记录，本作者结果不冒充独立验收。

实际8/25原产物未提供；其字段及状态只能保留原交接说明的证据边界。当前 Mac owner 源码闭包、Mac Python 3.14.6、live API/UI、自然时段、历史业务数据恢复和部署均为 **NOT_RUN / CANNOT_CONFIRM**。本批没有访问或操作 Mac、业务数据、服务、行情采集链、BUY/模型、经理台、Vibe 或 GitHub 写入；R1 交付保持不变。
