# Issue #33：saved-evaluation owner / guard / event 生命周期只读审查

## 审查边界

已完整读取附件中的 `xendcg_saved_eval/src/run_saved_evaluation_r2.py`（805 行）、`saved_evaluation_entry.py`（550 行）、`saved_evaluation_registration.py`（205 行）、`official_helpers/registry_adapter.py`（462 行）和 `execution_guard_core.py`（418 行），并读取问题正文、ISSUE_PACKAGE 元数据及相关 worker、builder、validator 的源码片段。未读取真实 scores、Top3、truth、模型、registry；未执行 candidate CLI、研究任务或测试；未修改产品代码或写 GitHub 消息。

下文文件名均指 `issue33/inputs/attachments/` 下的相应附件，行号是附件原始行号。

## 结论

可复用 existing owner → `ExecutionGuard.claim_no_fit` → route-profiled official adapter → monitored saved-evaluation worker → official terminal 的生命周期。**不能直接把 RFF candidate binding 传给原 R2 launcher，也不能只改 schema。** 新入口需要独立 RFF route/profile、evaluation execution、RUN_SPEC / INPUT_BINDING / parent release 和新输出根；旧 candidate execution、绑定、seal 与 PR5 accepted worker 均保持原字节。

核心复用点如下。

| 源码位置 | 可复用行为 / 适配意义 |
|---|---|
| `execution_guard_core.py:281–317` `claim_no_fit` | 官方零 debit 入口；构造 `NO_FIT_ENGINEERING_CANARY`、planned=0、debit=0，再委托同一个 backend 原子 claim。不要调用 `claim` 或 `execute_once`。 |
| `registry_adapter.py:136–169` | zero-debit claim 在真实 fit 预算耗尽后仍被允许；旧 RUN_STARTED debit 从不被回收。 |
| `saved_evaluation_registration.py:52–108` | 现有 route 子类在原 lock 内校验 registry 全字节 SHA、route event 前缀、全球唯一 execution ID、spec/binding/source SHA，然后调用原 `_append_unlocked`。 |
| `registry_adapter.py:310–333` | 原官方 lock、compatibility validator、canonical builder、append、flush、fsync；不能替换为自己的 JSONL writer。 |
| `saved_evaluation_entry.py:291–359` | 消费 owner 的既有 claim；确认新 execution 不等于旧 candidate、恰好一条 durable open start、identity/zero-debit/start receipt/source SHA 一致。 |
| `saved_evaluation_entry.py:396–447` | 单 worker + 原资源监视；读回 status/result/metrics/source snapshots/trace fsync 证据后才承认指标有效。 |
| `saved_evaluation_entry.py:512–550` | 先写 run receipt，再同一 adapter terminalize，再独立 readback 唯一 terminal，最后写 terminal receipt。只有 METRICS 文件不代表完成。 |
| `run_saved_evaluation_r2.py:629–700` | claim append 抛错后只读回一次，精确确认刚落盘 start 后直接 CANNOT_CONFIRM terminal；永远不重跑 claim 或 worker。 |

## 最小接口与隔离方式

建议 RFF 专属 CLI 只有显式的 `run_spec_path`、`input_binding_path`、`parent_release_path` 输入；不得暴露任意 route / candidate ID / evaluator / thresholds 的命令行覆盖。contract 内对 RFF 固定 route、已知旧 candidate execution、PR5 helper SHA、冻结研究合同及评价 scope 严格校验。上层 local freeze 可生成合同模板和命令，但真实执行前必须填充并独立核验 native、registry 与所有工件身份，不能伪造 release。

复用 entry 的理想窄接口为：

```python
run_after_durable_claim(
    claim=claim, adapter=official_adapter, payload=bound_payload,
    run_spec_path=..., input_binding_path=...,
    native_spec=..., native_runtime_helper_path=...,
    resource_tree=..., resource_trace_path=...,
    # 新 RFF 局部适配所需的显式依赖：
    worker_module=rff_saved_evaluation_worker,
    recovery_root=rff_saved_evaluation_root,
    candidate_output_root=immutable_candidate_output_root,
)
```

这些是推荐接口，不是原函数现有参数。若采用 route-local wrapper / 私有模块装配来避免改变已有 owner 源文件，必须避免污染全局共享的 R2 模块状态，并把 wrapper、被载入原模块以及实际 spawn target 全部列入 manifest。若决定抽取公共参数化 core，则需新版本源身份与新 execution；不能把修改后的源码当作旧冻结 R2 身份重放。

实际绑定注意：原 entry 在 `:354–359` 要求 `code_files['evaluation_worker']` 精确匹配 `worker.__file__`，`code_files['saved_evaluation_entry']` 精确匹配当前 entry 的 `__file__`；`:110–135` 另要求实际 `worker.run_saved_evaluation` 所在模块列入 `code_files`，其 path/SHA 被传给 monitor `target_descriptor`。仅把 PR5 SHA 写成一个无人验证的元数据字段不够。

### 原 R2 中必须解除的路线耦合

- launcher `:20–40`：R2 路径常量、导入目录和 `recovery_spawn_support`。
- launcher `:149–161`：R2 schema 与硬编码 `F5_FULL64_XENDCG_R1_20260924_SAVED_EVAL_R2_01` / route。
- launcher `:176–233`：固定 parent release 路径/schema、handoff root、固定 writer agent 比较。
- launcher `:597–600`：claim 恢复证据必须落在自己的 recovery `evidence` 根。
- entry `:178–211`：输出必须为 `RECOVERY_ROOT/execution/<execution_id>`，trace 必须直接落在 `RECOVERY_ROOT/evidence`，二者父目录必须已存在且非 symlink。
- entry `:360–363`：当前通过 `identity_only_files['candidate_model']['path']` 推导旧输出根。不应为新的 scores-only 路由引入不必要模型文件依赖；RFF 局部接口可显式冻结旧 candidate output root。
- registration `:31–45`：stage、baseline、signal scope 文案仍为 R2/CANDIDATE_01，需要 RFF route profile。保留 `registration_mode=LIVE_EXECUTION`、research safety 与不超过 DIRECTION_ONLY 的证据上限。

## RUN_SPEC / INPUT_BINDING / parent release 的准确字段

### 当前 entry 原样消费的 BOUND_FIELDS（13 项）

`execution_id`, `candidate_execution_id`, `output_root`, `resource_trace_path`, `code_files`, `code_sha256`, `executable_helpers`, `input_files`, `identity_only_files`, `evaluation_contract`, `score_aware_metrics_path`, `score_aware_metrics_sha256`, `synthetic_only`。

出处：entry `:34–38`；entry `:305–309` 按字段逐项比较 payload 与 binding，不允许 payload 覆盖。

### launcher / registration 额外必需 binding 字段

| 字段 | 用途 |
|---|---|
| `schema`, `route_id` | RFF 独立 schema / 固定路线；不能继续借用 candidate schema。 |
| `run_spec_path`, `run_spec_sha256`, `input_binding_path`, `parent_release_path` | 绝对解析路径与原始字节 SHA。binding 自身 SHA 在载入后计算，避免自引用。 |
| `official_registry_path`, `official_registry_sha256_before_start` | claim 时锁内验证完整 registry 前缀。 |
| `expected_route_event_sha256_before_start` | 有序 route SHA 列表，必须包含旧 candidate 执行现有 start/terminal，不能只填两条已知事件就假设完整。 |
| `expected_previous_event_sha256` | 全局 registry tail；claim-after-append-error 精确恢复在 launcher `:548–569` 使用。建议正常 claim/readback 同样显式检查它。 |
| `start_receipt_path` | registration `:67,135–151` 使用；应固定为新 output 的 `EVALUATION_START_RECEIPT.json` 并与 owner 实际路径相等。 |
| `resources` | entry `:364–374` 使用；当前限制 workers=1、wall≤600 秒、RSS≤3221225472 字节、cpu_threads 最终恰好 4、sample≤0.05 秒。应冻结实际 Mac 可用上限，避免静默 clamp 与宣称的合同不一致。 |
| `official_helpers` | 必需 `execution_guard`, `registry_adapter`, `builder`, `validator` 的 path/SHA；额外冻结 validator policy 元数据依赖。 |
| `executable_helpers` | 必需 `native_runtime`, `native_reference_contract`, `resource_tree`；应包括 launcher/monitor 的其余执行依赖，特别是 source SHA 漂移所涉资源树。 |

每一份 file ref 至少包含 `path`, `sha256`；既有 worker 对 identity-only refs 可额外检验 `bytes`。`code_sha256` 是按 `canonical_bytes(code_files)` 算出的 manifest SHA，**不是**任意 git commit SHA、单 worker SHA 或 helper 合并 hash（launcher `:129–137`）。helper refs 被整个 binding SHA 间接覆盖，同时在启动和 terminal 前直接验证。

新 binding 还应显式冻结 `candidate_output_root`、原 candidate binding/spec/seal、RFF `EXPERIMENT_CONTRACT`、原 controls、PR5 accepted worker 与 evaluator 及转递依赖。无需把任何旧文件改写为新 schema。附件本身没有完整 RFF candidate binding/spec、native 合同和 registry 当前前缀，不能据此填出可立即执行的真实 binding。

### RUN_SPEC 已有校验与 RFF 需补齐的声明

launcher `:149–168` 校验 `schema`, `route_id`, `execution_id`，以及严格 int 0 的：

- `fit_calls_authorized`
- `predict_calls_authorized`
- `control_fit_calls_authorized`
- `control_predict_calls_authorized`
- `calibrator_fit_calls_authorized`

另外 `candidate_model_load_authorized is False`。entry `:310–312` 本身只重复校验前两个，不能跳过 owner 的完整校验。

RFF 新 spec 应同时冻结 `candidate_execution_id`、`automatic_retry=false`、truth 最大 decode attempts=1、evaluation scope / 原阈值 / controls、`evidence_ceiling=DIRECTION_ONLY`、2024 已暴露状态，以及四个 safety flags。这些应在 owner 验证并与 binding 一致，不能只记录在一个不被检查的附加字段里。

### parent release 原实现逐项验证的 24 类字段

出处：launcher `:182–233`。必须有真实独立 reviewer transcript，且在本次 RFF handoff 根内；transcript 中 reviewer_agent 非 writer、`reviewer_verdict=PASS`, `REVIEWED=PASS`, `BEHAVIOR_VERIFIED=PASS`。当前 hardcoded `/root/saved_eval_writer` 对新 writer 身份不足，宜在新合同冻结 writer identity。

release 必须逐项等于：

1. RFF 自己的 `schema`、`active=true`、`execution_id`、`route_id`。
2. `run_spec_sha256`、`input_binding_sha256`、`source_code_sha256=code_sha256`。
3. `official_registry_path`、`official_registry_sha256_before_start`、`expected_route_event_sha256_before_start`。
4. `reviewer_agent`、`reviewer_verdict=PASS`、`reviewer_transcript_path`、`reviewer_transcript_sha256`。
5. 上述五项 `*_calls_authorized=0`、`candidate_model_load_authorized=false`、`saved_prediction_evaluation_authorized=true`。
6. `resource_caps=binding.resources`。
7. `artifact_sha256={input_files:{name:sha},identity_only_files:{name:sha}}`。
8. 非空 `parent_authorization_id`。

建议 RFF release 也显式重复旧 candidate execution、PR5 helper SHA、truth attempt cap 与 evidence ceiling，虽然它们已被整个 binding SHA 间接保护，人工审阅将更清楚。release 是本机主控真实授权产物，不能由代码测试伪造 PASS 后用于真实运行。

## RUN_STARTED → terminal 与失败路径

正常路径：

1. 元数据合同 / source manifests / release / fresh paths 校验。未 claim 前失败：零数据解码、零研究调用、零 registry 新事件。
2. 原 official adapter + guard `claim_no_fit`，锁内检查 immutable registry prefix、route prefix、unused new execution、零计划/debit。
3. 独立 readback 唯一 RUN_STARTED，exclusive 写 start receipt。该 receipt 固定原 candidate execution、当前 spec/binding/source hashes、parent ID、start SHA、before/after registry SHA、全部授权零和 safety。
4. 在 start 后验证 native runtime、原 Python、Mac 文件及 resource_tree，再进入 entry；entry 再确认只有 start receipt、无重入、输出隔离。
5. 一个受监控 worker 哈希绑定 inputs，再唯一一次 truth decode/evaluate；不调用候选 CLI/fit/predict/model loader。
6. status→result→metrics SHA 链 + trace durability + input/source unchanged 均通过后，写 run receipt；向同一 official adapter 提交 COMPLETED，否则 CANNOT_CONFIRM。
7. 独立读回唯一 terminal，再写 terminal receipt。COMPLETED 仅指评价生命周期，不是模型效果获胜。

| 失败时刻 | 正确处理 |
|---|---|
| start append 未落盘或无法确认 | 一次只读 readback，写 claim recovery evidence；不再 append、不启动 worker。 |
| start append 落盘后 owner 收到错误，精确识别唯一 open start | 重建同一个 ExecutionClaim，只做 CANNOT_CONFIRM terminal；不重跑 worker、不重置旧额度。 |
| start 落盘、worker 尚未启动 | 写失败证据 + run receipt，全部实测调用=0、truth attempt=0，append CANNOT_CONFIRM + terminal readback。 |
| worker 正常异常且 durable status 可用 | 从 status 取真实 zero-call 和 truth attempt/completed 计数，指标未完整验证则不登记数值结论。 |
| worker 被 kill / status 丢失 | 区分“授权为0 / debit为0”和“实测 readback 缺失”；从 durable truth-start marker 留下 attempt / 暴露信息，不能把缺状态当作无 truth read。 |
| terminal append 抛错 | 不自动再次 terminalize；先保留当前链状态，报告 `OFFICIAL_TERMINAL_APPEND_FAILED_NO_RETRY`，本机主控只读核验是否实际已落盘。 |
| terminal 已落盘，terminal receipt 写失败 | 不重跑评价，不补第二个 terminal；报告缺 receipt 及已知 event SHA，交本机 readback 修复流程。 |
| source/spec/registry prefix 在 start 后漂移 | fail closed，禁止以变更源码冒充旧身份；若原 official terminal 路径也拒绝，必须报告 dangling start / CANNOT_CONFIRM 及具体 drift，不得声称已有 terminal。 |

## 必须纳入新路线合成验收的既有缺口

1. **缺精确 truth 次数。** 原 worker 只有 `evaluation_label_values_decoded` bool（`:559–560,714,793,817`），不是 read/decode 调用数。新 worker 应在实际 truth parse 紧前写 durable `decode_attempt_count=1`，成功后 `decode_completed_count=1`；未开始为0；解析中失败保留 attempt=1，部分暴露无法确认与完成计数分开表达，不重试。

2. **truth marker 两端不一致。** entry `_truth_read_start_evidence :143–145` 要求 marker 的 `fit_calls==0`、`predict_calls==0`；原 worker `:691–700` 写 marker 却没有这两个字段，因此 worker 无 status 时 marker 判定总是 invalid。并且 marker 早于 candidate CSV parse（`:702–709`），不等于实际 truth decode 调用开始。RFF marker 要包含 owner 所验字段并移到紧贴 truth parse 的位置。

3. **prelaunch 被误记 worker_invoked。** launcher `:775` 在调用 entry 前就置 True，但 entry `:303–388` 仍有大量 prelaunch 校验；此处失败会进 owner fallback 的 UNKNOWN accounting。需真实 launch callback/状态或分离 validate 与 spawn，不能用“进入 entry”等同“worker 已启动”。

4. **preworker truth 字段未知。** launcher `:360–367` 明知 worker 未启动但 `:389–395` 调用 truth terminal helper 不传已知未读状态，得到 CANNOT_CONFIRM。新路由应将已知 no-launch 的 truth attempt0、not decoded 明确传入。

5. **None accounting 与原 guard summary 兼容性。** registration `:177–180` 会把缺失 status 的 fit entered / returned 置 None；但 `execution_guard_core.summarize :193–198` 拒绝 None。当前执行可经 route adapter terminalize，但后来调用 `guard.accounting()` 会报 RegistryIntegrityError。应先设计授权零、debit零、实测未知的字段层次及 readback 语义；不能因方便而伪造实测零，也不应改历史 guard 账本。

6. **source 漂移可能阻断 terminal 本身。** registration terminalize `:113` 调 `_verify_contract_snapshots`（`:70–75`），任何 source/spec/binding 漂移都会在 append 前失败。runner fallback 不能绕过这个事实。单纯写 fail receipt 后声称 terminal 已闭合是不成立的。使用独立冻结、禁止原地修改的新源码快照避免常规版本更新造成漂移；非预期漂移按显式阻断交付。

7. **所有源/工件都不保证在 start 后故障仍可闭合。** failure evidence、run receipt 在 terminal 之前写（launcher `:343–453`）；输出权限/磁盘故障可能阻止 terminal。不得对所有系统故障承诺自动闭合；应只声明可验证事件链，报告具体缺工件。

8. **并发其他路线追加也会阻断 terminal。** registration `:140–141` 比较整个 registry SHA 与 start receipt 的 after-start SHA，不仅 route prefix。新本机唯一执行期间必须满足既有全局 prefix 要求；不要擅自放宽或改旧事件。

9. **依赖缺失会早期阻断。** launcher `:40` 导入的 `recovery_spawn_support` 不在附件；native runtime/reference contract 不在附件；validator `:51–75` 在 import 时立即读取 `EXPERIMENT_REGISTRY_APPEND_COMPATIBILITY_POLICY_V1.json` 并从 policy 指定路径导入冻结 builder，该 policy 不在附件。需要合成 fixture / 静态方法替身或补齐被审阅的源码/合同依赖，不能把替身测试称作本机完整 official lifecycle 验收。

10. **禁止伪造 RFF 历史证据来迁就 XENDCG。** 原 XENDCG worker `:585–603,629–641` 要求 model/raw-score 身份以及诊断结果/terminal、prior predict=3；RFF 旧 candidate metadata 是 predict=1，历史真实 keys 仍未知。新 worker 只使用 RFF 已有 seal/binding/receipt 所证明的链，并复用 PR5 已接受 helper；无需或不得生成第二套 join diagnostic 来补足原 XENDCG 合同。

11. **reviewer transcript 自身尚未绑定审查对象。** R2 launcher `:187–199` 只验 transcript 的 reviewer / 三个 PASS 标志，未确认 transcript 内的 reviewed source/spec/binding SHA 等于本次对象。release 虽绑定本次 binding，也绑定 transcript 字节 SHA，但不能证明这个 PASS 是针对本次代码。RFF 新 transcript 应承载并验证 `execution_id`, `run_spec_sha256`, `input_binding_sha256`, `source_code_sha256`、PR5 helper SHA，以及 BEHAVIOR_VERIFIED 的 synthetic-only 范围，禁止复用旧无关 PASS。

## 源 SHA 漂移与旧执行保护

问题包列明旧 R2 frozen binding 与附件当前源码的三处不一致：runner `15210893…` → `25d91cdc…`；entry `c8e604ce…` → `ce631a11…`；resource_tree `8b13418e…` → `9d0792a8…`。它们只能作为当前静态实现参考，不能宣称可重放原冻结 R2。

推荐冻结顺序：完整 route-local 修改与合成验收 → 计算每个当前源码/ref 的 SHA → canonical code_files manifest SHA → 写新 RUN_SPEC 原始字节 SHA → 写新 INPUT_BINDING 原始字节 SHA → reviewer transcript 原始字节 SHA → 本机主控 release。若任何依赖变化，重新生成并审阅**新执行**绑定；旧 candidate binding (`efe96e1d…`)、prediction seal (`4fc18f9a…`) 和 PR5 helper (`3ea10757…`) 一字节也不改。新 evaluation execution 继续使用同一 RFF route，以零 debit 追加 evidence，而不是建立新的 fit 额度路线。

真实 saved scores/Top3 schema、旧失败 keys、当前 registry 全前缀、完整 Mac native依赖在本审查中仍 CANNOT_CONFIRM；不影响完成代码和合成路径，但必须在唯一新 evaluation execution 启动前由本机主控核实。
