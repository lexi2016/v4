# 原独审修订绑定：可调用请求与只读预检

## 当前结论

**业务状态仍为 `BLOCKED_AWAITING_ORIGINAL_REVIEWER`。** 本增量完成结构门禁调查、拒绝与零写入测试，以及独立可调用的请求/返回预检。没有重做392条正文、决定或语义审查，没有生成该批次的 reviewer PASS 文件，也没有执行真实 create/import。

固定基线为 `e06d143e881c66c22053a5c594b9c0be21d5be34`，仓库路径是 `V5/handoff/announcement-budget-red-20261009`。`candidate/ops/run_v5_decision_revision.py` 的五字段字典全等校验已在新 revision 的锁、目录和 pending 清单写入前执行。缺字段属于原独审输入尚未覆盖新修订；不需要放宽这个门禁。本轮所有64个原文件字节保持不变，核心 SHA256 仍为 `d78898559a8b46e7ec7edd344bc3352871d1f360db75fe62d6545c0532b9ab64`。

`tools/review_revision_binding.py` 是独立的标准库工具，不装入原 owner app，不更改 app manifest、原导入器、91项门禁或业务聚合。它输出请求或结构报告，不提交模型任务，也不证明审核者身份；真正的任务、通道、worker 身份和返回文件 SHA 必须经已有审核运行通道核实。

## 已准备的具体请求

交付件 `deliverables/reviewer-binding-request.json` 是可发给原独审的请求，不是可导入的 reviewer。

- 修订 ID：`decision-r20261010-rebind-638bfee44529438d`。
- 请求文件 SHA256：`98464a39323fd332e29dbed82344b9e9c5eefed75fede37ec7dca8c93991845c`。
- 未发送给审核者；未创建 revision。Mac 私有根尚未检查该 ID 是否存在；真正 create 仍执行原不可复用检查。
- 原独审的新 reviewer 文件与新文件 SHA：**尚未返回**。请求 SHA 不能用作 reviewer SHA。

原独审须核对并补充以下精确对象。所有值都区分逻辑产品 SHA 与文件 SHA：

```json
{
  "revision_id": "decision-r20261010-rebind-638bfee44529438d",
  "parent_product_sha256": "e724d07b39e5b4fb3ccbb0b4536f4519b4badbfd3783cad7ee6506a7af242ad6",
  "parent_owner_receipt_file_sha256": "6b5907c556b35b4e4a2c8a9928889b33d314369de31a7c6a12058f352c0525d0",
  "source_recovery_receipt_sha256": "b7b37e5385cdb7f14edc711af3b9d4bfd708441ac1de290a24a2b086b0f37b0f",
  "source_run_id": "16cc60afcb089f11690430b05853114c"
}
```

独审交付须保留既有 reviewer 字段原值，补充顶层 `decision_revision`。可以新增来源说明字段；本预检禁止修改既有 `review_conclusion`、reader/reviewer 身份、决定摘要、旧 `reviewed_at` 等字段。新绑定审查的时间、任务与通道来源放在真实返回回执或新增来源字段，不把旧语义审查时间改写成新语义审查。

原字段保持检查按 JSON 类型和值递归执行，覆盖对象和数组：`false` 不等于 `0`，`true` 不等于 `1`，整数 `392` 不等于小数 `392.0`。小数采用 Decimal 精确解析，`9007199254740993.0` 与 `9007199254740992.0` 不会因二进制浮点舍入被视为相同。类型和值一致、仅对象键序或等值小数写法不同的返回仍可通过结构检查。请求、原 reviewer 和返回 reviewer 三个 JSON 入口均拒绝 `NaN`、`Infinity`、`-Infinity` 和重复键。这些解析及比较只作用于新增预检工具，没有修改 semantic、decisions 或原 owner 的权威摘要算法。

| 冻结输入 | 必须保持的摘要 |
|---|---|
| 原 reviewer 文件 SHA256 | `981f89ebbcee269701ad69e4c346944f9da37cfcb1693032ca11de65c3e4eb29` |
| semantic 文件 SHA256 | `ec315a9470b92869dc5db928a29e52a7d83a67fd7b53925d65e36e83bcaaf8ba` |
| 完整 decisions 文件 SHA256 | `37607c65e2d822298fe321f8c3278acaf0e33d56f3261fa48b098b6ef2e5a10f` |
| 既有 decisions 逻辑 SHA256 | `e0094a54b123050c11870b8f1ed4a71bf768afd87ccb221605b135f846d468c8` |

预检对 semantic 和 decisions 仅核对固定文件字节摘要，并核对原 reviewer 中已存在的逻辑决定摘要；不重算研究结论。原 `create` 与 `register-handoff` 继续负责规范化逻辑摘要和逐条业务门禁。

## 可执行合同

### 1. 生成另一份请求（仅在确需使用另一个新 ID 时）

```sh
python3.14 -B -I "$BUNDLE/tools/review_revision_binding.py" request \
  --revision-id "$REVISION_ID"
```

输出仅写到 stdout。默认值是上表和五项冻结绑定；全部 expected pins 也可显式作为同名连字符参数传入，供别的固定批次使用。本批须核对请求中的值与上述冻结值完全一致。调用方保存 stdout 后固定请求文件 SHA；工具不写输入、不创建目录、不生成审核文件。

`request` 退出码0只表示请求生成成功，JSON状态仍为 BLOCKED。该输出没有 `review_conclusion` 和顶层 `decision_revision`，不能冒用为审核返回。

### 2. Mac 核对既有冻结输入，并显示等待状态

`BUNDLE` 为本源码包根；`REVIEW_REQUEST` 为上面的请求文件。其余路径指向 Mac 已有的真实冻结文件，不使用脱敏诊断 JSON 代替原文件。

```sh
python3.14 -B -I "$BUNDLE/tools/review_revision_binding.py" inspect \
  --request "$REVIEW_REQUEST" \
  --request-sha256 98464a39323fd332e29dbed82344b9e9c5eefed75fede37ec7dca8c93991845c \
  --original-reviewer "$ORIGINAL_REVIEWER" \
  --semantic-catalog "$SEMANTIC_CATALOG" \
  --decisions "$ARTICLE_DECISIONS"
```

未传返回 reviewer 时，核对冻结输入后输出 `BLOCKED_AWAITING_ORIGINAL_REVIEWER`，退出码2。不会消耗执行 attempt，也不会生成 revision；attempt 管理由上层任务通道负责。

### 3. 原独审真实返回后预检新文件

先通过已有审核通道核实实际原 reviewer、请求身份、任务/worker 与返回文件 SHA；没有这些来源证据时保持 BLOCKED。不得由集成器运行“补字段并写 PASS”的脚本。

```sh
python3.14 -B -I "$BUNDLE/tools/review_revision_binding.py" inspect \
  --request "$REVIEW_REQUEST" \
  --request-sha256 98464a39323fd332e29dbed82344b9e9c5eefed75fede37ec7dca8c93991845c \
  --original-reviewer "$ORIGINAL_REVIEWER" \
  --semantic-catalog "$SEMANTIC_CATALOG" \
  --decisions "$ARTICLE_DECISIONS" \
  --reviewer-output "$ACTUAL_RETURNED_REVIEWER" \
  --reviewer-sha256 "$ACTUAL_RETURNED_REVIEWER_SHA"
```

| 预检状态 | 退出码 | 含义 |
|---|---:|---|
| `BLOCKED_AWAITING_ORIGINAL_REVIEWER` | 2 | 原输入满足固定摘要，尚无新 reviewer 返回 |
| `BLOCKED` | 2 | 请求/输入 SHA、JSON、原记录或精确五项绑定不符合合同；`error_codes` 给出原因 |
| `STRUCTURAL_BINDING_VERIFIED` | 0 | 文件字节、五项绑定和既有审核字段一致；仅代表结构验证 |

即使结构验证退出0，报告仍明确 `authorship_verified=false`、`semantic_review_performed=false`、`authorizes_import=false`，并保留业务来源待验证状态。调用方只有在真实审核通道验明返回后，才可把新 reviewer 交给原流程；不能只凭该工具的退出码放行。新的 reviewer JSON 本身也不能证明作者是谁。

### 4. 保留原 create → prepare → register → verify → import → readback

真实输入须在原恢复根的独立 inputs 中保持各自固定字节。原步骤详见本目录未修改的 `DECISION_REVISION.md`。`create` 必须使用实际返回的 reviewer 文件 SHA、新请求中的同一个 revision ID、原 semantic/decisions SHA，以及原父产品/回执/recovery SHA。create 成功后核对新 manifest 文件 SHA，再运行后续原命令。

如果 ID 已存在，或曾留下初始化失败目录，保留目录并选择新的 ID；新的 ID 必须重新取得原独审对该绑定的真实补充审查。禁止手动清空后复用、把 reviewer 改成另一个 ID 或覆盖旧产品。输入缺失/错配时不要进入真实 create 来制造失败目录。实际导入时间用于新 `available_at`；不回填旧计划或声称旧日历史可用。

## 本轮验证证据

正式环境：Linux x86_64，CPython **3.14.6**，`/workspace/scratch/17ec887ca39d/runtime/v5-env/bin/python`；依赖环境由主任务按原 uv.lock 安装。不是 Mac 环境或 Mac 私有资产验收。

- 原 e06d 98项与新增28项，共 **126/126 PASS、0 SKIP**，13个测试文件各自在独立进程执行。最终完整命令、时间与退出码见 `evidence/locked-suite-strict-json/`。初版118项结果保留在 `evidence/locked-suite/`，不能覆盖后续审查发现的问题。
- 新增 `test_revision_review_gate.py`：8个测试方法、25个拒绝子场景。真实调用原 create 与原父验证；仅在写入方法、建目录与 kernel_lock 边界安装“若调用则失败”的检测，同时比较全部父文件字节和目录。缺绑定、5字段分别缺失/错配、额外字段、错误类型、旧 revision ID、6类错 SHA、错误决定摘要均在任何这些写入边界之前拒绝。
- 新增 `test_revision_review_tool.py`：最终20项。初次 RED 为工具未存在时12项明确失败；初版实现后12项通过。该 RED 不表示原 create 存在漏洞，原门禁一直保持通过。
- 独立结构审查随后发现初版 helper 使用 Python 宽松相等比较，可能接受布尔/整数/小数类型漂移及小数精度丢失；JSON 默认解析也接受非标准非有限数值。本轮先补8项回归，在旧 helper 上实测20个测试方法中的18个失败子场景，再以精确 Decimal 解析及递归类型和值比较修复，20项全部通过。证据为 `evidence/strict-json-red.log`、`evidence/strict-json-green.log`、`evidence/strict-json-gate-regression.log`。最终126项套件覆盖这次修复，不把初版118项通过等同于无审查问题。
- 3.12.14上的原10+7项只是兼容性探测，正式结果以上述3.14.6为准。
- `evidence/SOURCE_INVARIANCE.json` 列出64个原文件的前后 SHA，全部相同。新增工具、测试和本文不改变原 manifests。

测试使用临时、明确标记 synthetic 的两条公告材料。测试目录清理后没有留下业务 reviewer；这些结果不能当作392条的独审、真实导入、API/UI或部署验收。

## 仍需实际返回的内容

原独审经已有通道补充审查上述精确绑定，交付新的 reviewer 文件、其实际 SHA256，以及可核对原审核者身份/任务/请求绑定的真实返回回执。随后由 Mac 运行原导入与反读验收。本轮未获得原 reviewer 原始字节、392正文、完整 decisions 或 Mac私有根，因此这些真实业务步骤均为 `NOT_RUN`；未更改任何业务 PASS、91项限制或392条决定。

## 来源核验限制

固定交接入口是 `46081f5bcfb5f0c9e63aaa8b2b7baf65ae191eff/handoff/v5-blockers-20261010/START_HERE.md` 及同目录两份验收说明。ZIP二进制未能下载；源码通过固定原 ref 的逐文件内容和摘要核对取得，不能称整 ZIP 已核验。`REVIEW_FIX.md`、`SOURCE_MANIFEST.json` 为原 ref 的合法原字节，和ZIP内脱敏摘要不同；不将它们冒称为ZIP字节。
