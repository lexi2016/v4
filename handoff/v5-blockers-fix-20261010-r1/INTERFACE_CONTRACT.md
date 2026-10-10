# Reader / 独立 Reviewer 可调用接口合同

本文说明本轮 V5 候选提供的 Python 调用合同、交接文件约束和阻塞状态。最终交付提交、文件 SHA 与测试汇总以主交付报告为准。交付根的 `CHANGE_MANIFEST.json` 对应各项增量，原独审请求位于 `original-reviewer/reviewer-binding-request.json`。本文本身不表示真实后台、Mac 调度或原独审已接通。

依据：固定交接 `46081f5bcfb5f0c9e63aaa8b2b7baf65ae191eff` 的 `REPRO_AND_ACCEPTANCE.md`、`ADDITIONAL_INTERFACE_AND_PROGRESS.md`；经理来源 `3d9541aca3e5d28e94109609940503cca239b9fe`；公告修订 owner 来源 `e06d143e881c66c22053a5c594b9c0be21d5be34`。当前合同实现位于经理候选的 `src/v5_shadow/daily_review_handoff.py`，原导入命令仍由冻结 e06d owner 执行。

## 1. 当前交付边界

候选新增可显式调用的提交、轮询和回执校验入口，并把只读修订预检接到 daily 业务 claim 之前。调用方须注入其**已经存在、由 host 管理的通道对象**。这里没有创建模型服务、队列、认证客户端、后台 worker 或自动轮询任务。

真实通道尚未绑定时，对有效任务调用 `submit_review_task(..., channel=None)` 或 `poll_review_task(..., channel=None)`，结果为 `BLOCKED_REVIEW_CHANNEL_NOT_BOUND`。当前固定批次的原独审新文件、实际新文件 SHA 和真实通道返回证据仍待原审核者提供，业务保持 BLOCKED。

JSON 中两个人名不同，仅满足声明的格式约束。实际 Reader 与 Reviewer 的身份、独立性、原审核者身份和通道来源，须由已有 host 的身份与任务记录核实。结构工具不证明作者身份，也不会产生原独审 PASS。

## 2. 可调用入口

```python
from v5_shadow.daily_review_handoff import (
    submit_review_task,
    poll_review_task,
    validate_review_return,
    preflight_revision,
)
```

```text
submit_review_task(task, *, channel=None, now=None)
poll_review_task(task, *, channel=None, now=None)
validate_review_return(task, receipt, *, now=None)
preflight_revision(owner_request, *, now=None)
```

| 入口 | 实际行为 | 结果边界 |
|---|---|---|
| `submit_review_task` | 校验任务与输入文件字节；显式调用一次 `channel.submit(task)`；校验返回回执 | 不自动重提，不分配 daily 业务 attempt |
| `poll_review_task` | 重核任务输入字节；调用 `channel.poll(task_id, request_sha256)` | 永远不调用 submit，不分配 daily 业务 attempt |
| `validate_review_return` | 校验回执字段、任务摘要、身份声明、时钟、状态与输出引用结构 | 单独调用时不读取输出文件，不代表语义审核或原 owner 导入通过 |
| `preflight_revision` | 只读核对恢复回执、三个输入文件 SHA、修订绑定、reviewer 来源字段、决定摘要，以及可选完整 handoff | 就绪仅为 `READY_FOR_ORIGINAL_OWNER`；原 owner 仍逐步重新验收 |

`now` 是可选的有时区 `datetime` 对象；任务和回执内的时间字段则是有时区 ISO 8601 字符串。正常 host 调用使用默认真实时钟。实现分别在调用前执行任务准入、回调返回后采集实际时钟校验返回，允许 host 在回调内记录实际 acknowledgement/heartbeat。显式传入的 `now` 保持固定，供可控测试或已明确管理时钟的调用方使用；不得用它回填真实业务时间。

### host 对象合同

```python
class ExistingHostChannel:
    channel_id: str

    def submit(self, task: dict) -> dict:
        # 接到 host 已有的运行通道；返回完整 return schema。
        ...

    def poll(self, task_id: str, request_sha256: str) -> dict:
        # 只查询既有任务；不能在这里偷偷重新提交。
        ...
```

`channel.channel_id` 必须与任务中的 `channel_id` 完全相同。提交时传入脱离调用方可变对象的规范化任务副本；轮询传递同一个任务 ID 与逻辑请求 SHA。模块不从配置动态导入通道，不执行配置中的命令，也不自行查找凭据。

host 负责现有通道的认证、实际 worker 与审核者映射、任务持久化、heartbeat 产生、超时和失败记录，以及按任务 ID / 请求 SHA 核对重复提交。模块自身没有跨调用的持久去重器；再次显式调用 submit 会再次调用 host。因此，不应把“没有自动重试”误解为“任意重复 submit 都只执行一次”。

## 3. Task schema：字段必须完整且不得额外增减

schema 为 `v5.announcement_review_task.v1`。

| 字段 | 类型与约束 |
|---|---|
| `schema_version` | 固定字符串 `v5.announcement_review_task.v1` |
| `task_id` | 非空字符串，最多 256 字符；由真实 host 分配或接受的任务身份 |
| `channel_id` | 非空字符串，最多 256 字符；绑定已有 host 通道 |
| `target_date` | 有效 `YYYYMMDD` 日期 |
| `source_run_id` | 32 位小写十六进制，必须等于 `decision_revision.source_run_id` |
| `reader_identity` | 非空字符串，最多 256 字符；真实身份由 host 核实 |
| `reviewer_identity` | 同上，且与 `reader_identity` 不同 |
| `review_scope` | `REVISION_BINDING_ONLY` 或 `READ_AND_REVIEW`；本次既有 392 条批次只能使用前者 |
| `decision_revision` | 下表五字段的精确对象 |
| `input_files` | 非空对象：`输入名 -> {"path": 绝对路径, "sha256": 实际文件SHA}`；输入名非空且最多 256 字符 |
| `created_at` | 有时区 ISO 8601 字符串，不晚于校验时钟，严格早于 deadline |
| `deadline` | 有时区 ISO 8601 字符串；submit 在到期后阻塞 |
| `heartbeat_timeout_seconds` | 真正的整数，范围 1–3600；布尔值不接受 |

`decision_revision` 的五字段：

| 字段 | 约束与含义 |
|---|---|
| `revision_id` | 匹配 `[a-z0-9][a-z0-9_-]{0,63}` 的新唯一 ID；后续原 owner 禁止复用既有目录 |
| `parent_product_sha256` | 64 位小写十六进制；父产品逻辑 SHA |
| `parent_owner_receipt_file_sha256` | 64 位小写十六进制；父 owner 回执原文件 SHA |
| `source_recovery_receipt_sha256` | 64 位小写十六进制；恢复回执原文件 SHA |
| `source_run_id` | 32 位小写十六进制；原 source run |

文件引用只有 `path` 和 `sha256` 两个字段。路径须绝对、不能含 `..`；实际读取拒绝符号链接和非普通文件。每文件按原 SafeRoot 的 64 MiB 上限读取并解析 JSON，核对原始字节 SHA。在本次 `REVISION_BINDING_ONLY` 任务中，`input_files` 至少包含 `semantic_catalog` 和 `decisions`，并持续保存其冻结字节供提交、轮询和最终预检核对。

请求逻辑摘要必须使用候选的 `v5_shadow.digests.sha256_json(task)`：UTF-8、键排序、无多余空白、保留非 ASCII 字符、禁止 NaN；规范化请求 JSON 上限为 16 MiB。**请求逻辑 SHA、文件原始字节 SHA、owner 产品逻辑 SHA 是不同字段，不能互相替用。**

## 4. Return schema：每次 acknowledgement、heartbeat 和终态均返回完整对象

schema 为 `v5.announcement_review_return.v1`。以下字段必须全部存在，不能额外增加字段。

| 字段 | 类型与约束 |
|---|---|
| `schema_version` | 固定字符串 `v5.announcement_review_return.v1` |
| `task_id` | 与原任务完全相同 |
| `request_sha256` | 必须等于 `sha256_json(task)` |
| `channel_id` | 与原任务完全相同 |
| `source_run_id` | 与原任务完全相同 |
| `reader_identity` | 与原任务完全相同 |
| `reviewer_identity` | 与原任务完全相同 |
| `status` | `SUBMITTED`、`RUNNING`、`FAILED`、`COMPLETED`、`OUTCOME_UNKNOWN` 之一 |
| `submitted_at` | 真实有时区 ISO 8601 时间；不得早于任务创建 |
| `heartbeat_at` | 真实有时区 ISO 8601 时间；不早于 submitted_at，不晚于校验时钟或任务 deadline |
| `reason_codes` | 非空字符串组成的列表；`FAILED` / `OUTCOME_UNKNOWN` 必须至少有一项原因 |
| `output_files` | 非完成状态必须为 `{}`；`COMPLETED` 必须精确包含以下三个文件引用 |

完成态 `output_files`：

| 精确键名 | 对应原 owner 请求字段 |
|---|---|
| `semantic_catalog` | `{"path": revision_create.semantic_catalog, "sha256": revision_create.semantic_sha256}` |
| `reviewer_output` | `{"path": revision_create.reviewer_output, "sha256": revision_create.reviewer_sha256}` |
| `decisions` | `{"path": revision_create.decisions, "sha256": revision_create.decisions_sha256}` |

`SUBMITTED` 和 `RUNNING` 的 heartbeat 超过允许间隔会被拒绝。已完成回执可以作为固定历史返回反复验证，不因之后时间流逝而要求重新审核；它的身份、请求 SHA、文件引用和实际文件字节仍须保持一致。host 应持久保留真实终态，不能把完成任务改写成另一个请求的结果。

### 返回状态与调用方处理

| 返回情况 | 调用方应保留的判断 |
|---|---|
| `SUBMITTED` / `RUNNING` | 已声明接收或运行；等待实际完成，不进入 revision 业务 claim |
| `COMPLETED` | 通道返回结构通过；随后还需实际输出文件 preflight 和原 owner 验收 |
| `FAILED` / `OUTCOME_UNKNOWN` | 保留原原因和任务身份；不能当作成功或自动重提授权 |
| `BLOCKED_REVIEW_CHANNEL_NOT_BOUND` | 真实通道未注入；保持 BLOCKED |
| `BLOCKED_REVIEW_WINDOW_CLOSED` | 到期后不能新 submit；不能回填 created_at/deadline 来放行 |
| `OUTCOME_UNKNOWN_NO_AUTOMATIC_RETRY` | submit 回调抛错，外部可能已经接收；先通过原通道核对结果 |
| `BLOCKED_REVIEW_POLL_FAILED` | 查询失败；poll 不转为 submit |
| `BLOCKED_INVALID_REVIEW_RETURN` | 返回不符合合同；保留阻塞并核对真实回执 |

成功解析的 wrapper 结果包含 `status`、`request_sha256`、规范化 `receipt`、`retry_submission_automatically=false`、`natural_verified=false`。未取得有效 receipt 的阻塞/异常结果不伪造 receipt，部分错误带 `reason_codes`。任务本身或输入文件在回调前无效时可抛出合同或 I/O 异常；host 应记录阻塞原因，不能把异常视为可重提证明。

## 5. 仅合成的合同示例

以下代码仅演示调用方式。输入位于自动清理的临时目录，内容明确为 SYNTHETIC；对象是进程内假通道，不连接真实后台，不生成 reviewer PASS，也不向业务根写文件。

```python
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from v5_shadow.daily_review_handoff import (
    submit_review_task, poll_review_task, validate_review_return,
)
from v5_shadow.digests import canonical_bytes, sha256_json

with TemporaryDirectory(prefix="synthetic-review-contract-") as directory:
    root = Path(directory).resolve()
    inputs = {}
    for name in ("semantic_catalog", "decisions"):
        path = root / (name + ".json")
        raw = canonical_bytes({"fixture": "SYNTHETIC_CONTRACT_ONLY", "role": name})
        path.write_bytes(raw)
        inputs[name] = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}

    created = datetime.now(timezone.utc)
    task = {
        "schema_version": "v5.announcement_review_task.v1",
        "task_id": "synthetic-task", "channel_id": "synthetic-host-channel",
        "target_date": "20261009", "source_run_id": "1" * 32,
        "reader_identity": "synthetic-reader",
        "reviewer_identity": "synthetic-independent-reviewer",
        "review_scope": "REVISION_BINDING_ONLY",
        "decision_revision": {
            "revision_id": "synthetic-binding-only",
            "parent_product_sha256": "a" * 64,
            "parent_owner_receipt_file_sha256": "b" * 64,
            "source_recovery_receipt_sha256": "c" * 64,
            "source_run_id": "1" * 32,
        },
        "input_files": inputs, "created_at": created.isoformat(),
        "deadline": (created + timedelta(minutes=30)).isoformat(),
        "heartbeat_timeout_seconds": 300,
    }

    class SyntheticChannel:
        channel_id = "synthetic-host-channel"

        def submit(self, received_task):
            self.task = received_task
            self.submitted_at = datetime.now(timezone.utc).isoformat()
            return self.receipt("SUBMITTED")

        def poll(self, task_id, request_sha256):
            assert task_id == self.task["task_id"]
            assert request_sha256 == sha256_json(self.task)
            return self.receipt("RUNNING")

        def receipt(self, status):
            return {
                "schema_version": "v5.announcement_review_return.v1",
                **{key: self.task[key] for key in (
                    "task_id", "channel_id", "source_run_id",
                    "reader_identity", "reviewer_identity")},
                "request_sha256": sha256_json(self.task), "status": status,
                "submitted_at": self.submitted_at,
                "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "reason_codes": [], "output_files": {},
            }

    assert submit_review_task(task)["status"] == "BLOCKED_REVIEW_CHANNEL_NOT_BOUND"
    channel = SyntheticChannel()
    acknowledgement = submit_review_task(task, channel=channel)
    running = poll_review_task(task, channel=channel)
    checked = validate_review_return(task, running["receipt"])
    assert acknowledgement["status"] == "SUBMITTED"
    assert checked["status"] == "RUNNING"
    assert checked["natural_verified"] is False
```

示例中的 `1`、`a`、`b`、`c` 摘要及 synthetic 身份没有业务含义，不能复制到真实请求、返回文件、source receipt 或产物。真实完成态只能引用真实通道返回且已核 SHA 的三个文件。

## 6. 与 daily revision / 业务 attempt 的接线

公告 `owner_request` 保留原合同：`target_date`、`revision_create`、`review_identities`，可增加 `review_handoff`。

`revision_create` 精确字段为：

```text
parent_root, recovery_sha256, revision_id,
parent_product_sha256, parent_receipt_sha256,
semantic_catalog, semantic_sha256,
reviewer_output, reviewer_sha256,
decisions, decisions_sha256
```

`review_identities` 精确字段为 `parent_task_id`、`reader_identity`、`reviewer_identity`。可选 `review_handoff` 精确为 `{"task": 完整task, "receipt": 完整return}`。`revision_create` 中三个文件均须在真实 `parent_root` 内；恢复回执的 `derived_root` 必须与该根一致。

当前接线顺序：

1. `daily_tick` 构造 job 时先作只读 preflight，缺文件或已知错配直接 BLOCKED。
2. `daily_dispatch` 在每个公告 job 的实际 claim 前调用已绑定的只读 `preclaim`，重新校验前序 lane 运行期间可能改变的输入；失败不创建该公告 run。
3. claim 成功后，`run_revision` 再次 preflight，然后保留原 e06d `create → prepare → register-handoff → verify → import → readback`。
4. owner 产物经过两次独立消费读回；经理仍使用原 owner 的原门禁判断业务完整性，导入并不等于选股成功。

preflight 检查实际文件 SHA、精确五项修订绑定、reviewer 的 semantic 文件 SHA、声明的不同 reader/reviewer、目标日/source run、reviewed_at 和决定逻辑摘要。提供 handoff 时必须已 COMPLETED，task/return/output 引用须和本次 owner request 全等；绑定补充任务还须保持原 semantic 与 decisions 输入引用不变。

`READY_FOR_ORIGINAL_OWNER` 仍携带 `original_owner_verified=false`、`natural_verified=false`。原 e06d 父来源验证、正文证据、91 项既有门禁、规范化决定与原导入反读继续执行。检查与 claim 不是跨文件事务；claim 之后的未知外部变化仍按原 owner 拒绝/未知结果处理，不承诺无条件自动重试。

既有**显式、已经核实原审核来源的冻结文件交接**继续支持不带 `review_handoff` 的入口，并经过同样 preflight 与原 e06d 全链。不能为绕过未完成通道而删除 `review_handoff`、拼装 reviewer 或将结构就绪改称原独审 PASS。

## 7. 本批原独审只补修订绑定

真实交接使用交付的 `original-reviewer/reviewer-binding-request.json` 所指定的新唯一 `revision_id`。Mac 须先确认该 ID 未创建过；若需改 ID，必须取得原审核者对新精确绑定的真实返回。固定其余字段如下：

| 字段 | 固定值 |
|---|---|
| `parent_product_sha256` | `e724d07b39e5b4fb3ccbb0b4536f4519b4badbfd3783cad7ee6506a7af242ad6` |
| `parent_owner_receipt_file_sha256` | `6b5907c556b35b4e4a2c8a9928889b33d314369de31a7c6a12058f352c0525d0` |
| `source_recovery_receipt_sha256` | `b7b37e5385cdb7f14edc711af3b9d4bfd708441ac1de290a24a2b086b0f37b0f` |
| `source_run_id` | `16cc60afcb089f11690430b05853114c` |
| 原 reviewer 文件 SHA | `981f89ebbcee269701ad69e4c346944f9da37cfcb1693032ca11de65c3e4eb29` |
| semantic 文件 SHA | `ec315a9470b92869dc5db928a29e52a7d83a67fd7b53925d65e36e83bcaaf8ba` |
| decisions 文件 SHA | `37607c65e2d822298fe321f8c3278acaf0e33d56f3261fa48b098b6ef2e5a10f` |
| decisions 逻辑 SHA | `e0094a54b123050c11870b8f1ed4a71bf768afd87ccb221605b135f846d468c8` |

原审核者保留原 reviewer 的既有字段及值，只补顶层 `decision_revision`；新增来源说明可以另加，不能改原 reviewed_at、身份、PASS 或决定摘要。新补充审核时间记录在实际返回回执或新增来源字段中。原 392 条决定与 semantic 文件逐字节冻结，不重新阅读、重新判断或改写研究结论。

e06d 增量的 `tools/review_revision_binding.py` 只生成请求或只读比较返回。其 `STRUCTURAL_BINDING_VERIFIED` 明确保留 `authorship_verified=false`、`semantic_review_performed=false`、`authorizes_import=false`。它与本文 task/return 是相互配合的合同，不能把请求文件本身当作 reviewer 文件，不能把请求 SHA 当作新 reviewer SHA。

只有原审核者真实返回后才能填写 `ACTUAL_RETURNED_REVIEWER_SHA256`；目前该值待返回。`available_at` 使用实际新导入时间，原计划字节和历史 PIT 资格保持原状。完整 Mac 执行、证据要求和回滚见 `MAC_ACCEPTANCE.md`。
