# 独立 Mac 验收与回退

本文件列出候选命令，**本次全部产品执行 NOT_RUN**。继续使用原独立 Mac 测试任务及已有完整隔离源码；不启动另一套真实采集，不安装依赖，不接生产目录。基线 RED、候选 GREEN、相关回归、自然证据分别记录。

## 0. 固定版本、字节与环境

旧基线使用 `cdd430e4dcd8d3e8c5949baff21a4831b4689444` 的完整隔离 checkout；它的 V5 tree 与要求保留的 `7115f65267a1496d0ca8214cc14130f8c2b65d87` 完全相同，且已经包含原三项 handoff 测试。修复候选使用新独立分支的已读回交付 commit。两个 checkout 分开，保留现有未提交内容。

记录 `pwd`、实际 commit、Python/平台、现有原源码根和测试命令。`V5_ARCHIVE_PRODUCER_SOURCE_ROOT` 指向已有完整隔离原源码；不要指向本包 after/ 或零散 handoff 快照。manifest 的 15 项 dependency SHA 全部检查，尤其实际 `domains/_research_hourly_parts/_namespace.py`；不符时保留原错误，不能算 RED/GREEN。

Mac 临时目录必须使用无 symlink 祖先的规范路径；需要时把 `TMPDIR` 设为**已有且获准**的规范隔离临时根。不要为了让测试通过放宽产品根目录检查。新链与 IO fixture 已 resolve 自己的临时根；旧相关回归仍需满足相同环境前提。

在候选 checkout 根可先核补丁源码清单（仅标准库文件校验，不执行产品）：

```bash
python3 -B - <<'PY'
from pathlib import Path
import hashlib, json
root = Path.cwd()
manifest = json.loads((root/'handoff/v5-article-identity-repair-20261010-r1/SOURCE_SHA256.json').read_bytes())
for row in manifest['files']:
    raw = (root/row['path']).read_bytes()
    assert len(raw) == row['after_bytes'], row['path']
    assert hashlib.sha256(raw).hexdigest() == row['after_sha256'], row['path']
print('SOURCE_BYTES_MATCHED; product tests not executed')
PY
```

## 1. 在旧固定版本确认原三项 RED

仅在旧基线完整 checkout 根运行：

```bash
V5_ARCHIVE_PRODUCER_SOURCE_ROOT=/ABS/EXISTING_ISOLATED_FULL_SOURCE \
PYTHONPATH=V5/src:V5/tests:handoff/v5-article-identity-20261010 \
python3 -B -m unittest \
 test_identity_gap_candidate.IdentityGapCandidate.test_control_valid_capture_is_accepted \
 test_identity_gap_candidate.IdentityGapCandidate.test_article_id_mutation_must_be_rejected \
 test_identity_gap_candidate.IdentityGapCandidate.test_dedupe_key_mutation_must_be_rejected -v
```

只有 control 成功，且两个合法 64hex 单键变异失败在 `unexpectedly accepted` 位置，才称已确认 RED。依赖缺失、日期/路径/clock gate、错误 fixture 或其他拒绝都不证明漏洞，也不证明修复。保留实际 exit code 和失败原因。

## 2. 在修复候选执行 51 项身份/闭环候选

```bash
V5_ARCHIVE_PRODUCER_SOURCE_ROOT=/ABS/EXISTING_ISOLATED_FULL_SOURCE \
PYTHONPATH=V5/src:V5/tests \
python3 -B -m unittest test_archive_article_v2 test_archive_builder_identity -v
```

| 类 | 方法数 | 必须观察的行为 |
|---|---:|---|
| ArticleV2ChainTests | 23 | 原 producer → 原 collector/builder → 原 store/reader → 原材料与 native identity → manager 同 run/plan；旧语义/PIT拒绝保留 |
| BoundArchiveBuilderIdentityTests | 22 | 全 source 正例；article_id/dedupe_key、缺 source、SHA、run/date、owner时钟、完整 archive 变异；自洽 source/archive 伪造；reader 类型/生成时间/未声明文件；v1分派 |
| OriginalOwnerBoundIOTests | 2 | 旧临时 symlink 不被使用；目的 source symlink 拒绝；sentinel/指向不变；原 source 字节与 readonly replay |
| OriginalBuilderCompleteSourceContractTests | 4 | claim_type≠evidence_level、fallback及strip/lower、重复证据合并、非身份聚合字段；只证明原builder合同 |

51 是静态方法计数，不是已执行/已通过计数。特殊 claim_type/fallback/duplicates 的手写完整 source 仅用于原 builder 合同测试，不能冒充原 collector 的真实来源正例。

自洽伪造测试必须先确认原 source 的准确 bytes 和原 indent=2 serializer 控制，再只改 claim_type，并同步 source/witness/owner result/archive 及全部哈希。其拒绝应为原 owner 语义重放不符，不能仅因 compact/pretty 格式不同“碰巧拒绝”。

当前 US 相关合成 fixture 使用已过去的合法 POST_CLOSE 窗口；日期按现有原 calendar/context 推导。当前 session 不一致仍须 `INPUT_MISSING`，不能把旧恢复文件用作当前来源。行业路径不要求 ETF/US ticker；直接个股路径仍需明确 US 关系。不得用强改日期或 patch 原 selector/mapper 让用例通过。

## 3. 已有受影响入口回归

在上述身份批次结果得到解释后，再运行相关既有入口：

```bash
V5_ARCHIVE_PRODUCER_SOURCE_ROOT=/ABS/EXISTING_ISOLATED_FULL_SOURCE \
PYTHONPATH=V5/src:V5/tests \
python3 -B -m unittest \
 test_archive_acquisition_producer test_current_us_research \
 test_manager_archive_reader test_us_mapping_scope test_manager_plan -v
```

原 v1 validator、已有 V5 archive dispatch、current_us archive_import 运输、经理同 run 读回和旧错误理由都应保留。发现失败只修对应具体原因；不因本次身份补丁另建行情、主体或经理算法。

## 4. 候选接口如何接入本批 source

以下只说明接口，实际执行仍在独立 Mac 的获准合成任务内。现有 acquisition fixture 生成本次 receipt、三个产物、逐页文件和固定 status 后，形成四字段 owner request：

```text
capture_root, capture_files, receipt, status
```

输入 `archive_builder_v1.run_build`，或其 source-only CLI：

```bash
python3 -I -B V5/src/v5_shadow/archive_builder_v1.py < bound-owner-request.json
```

保存返回完整 source bindings，不从控制台手工重建 source。保留返回的 `capture_root,capture_files,receipt,builder_source,builder_receipt,archive_v1`，补全新 `output_root`，组成 importer 精确七字段。该 root 只能有 `.v5-archive-article-v2`，内容为 `v5.archive-article.v2\n`。

这个对象可传已有 `archive_article_v2.run_import`，或置于既有 current_us_research 请求的 `archive_import`。后者仍把精确 binding 交原 manager refresh/read。不能把整个 owner 返回字典原样当 importer request，因为返回还含 schema/readback/identity 等不属于七字段合同的元数据。

## 5. 落地、回退与结果报告

优先使用完整新交付 commit 的独立 checkout。若使用 zip，则 `after/` 是完整修改后文件；`runtime.patch` 是对固定 cdd 基线的 18 路径补丁。仅在无冲突的获准隔离 checkout 使用：

```bash
git apply --check /ABS/UNPACKED/runtime.patch
git apply /ABS/UNPACKED/runtime.patch
```

不应用到实际 V4 owner 目录，不覆盖并行修改。需要撤回且文件未被后续修改时，先 `git apply -R --check`，再按已有授权逆向应用；否则保留工作树并让原 Mac 任务按精确 before SHA 人工处理。更安全的环境回退是保留新分支不动，回到独立的旧固定 checkout；没有 merge/deploy 或业务数据需要回滚。

失败的隔离 root 可能留下 source/lock，但没有成功 receipt/manifest；保留作诊断，不删除生产或旧归档。新 attempt 使用另一个获准合成根。

结果分别记录：基线 RED、候选 51 项、相关回归、原 store/reader/manager 闭环、真实同批源、自然时段、集成、部署、API/UI。任何依赖/环境失败保留原文；只同步最小脱敏错误和 SHA，不上传真实材料、source、账号、行情或完整运行目录。合成通过仍保持 natural_verified=false。
