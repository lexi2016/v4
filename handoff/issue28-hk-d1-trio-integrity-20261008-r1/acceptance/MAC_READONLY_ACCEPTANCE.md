# Issue #28：实际 owner、API 投影与 Mac 接续验收

固定输入为 [问题包提交 `30ad7bb6`](https://github.com/lexi2016/v4/tree/30ad7bb633f715f30c4e10eb67e9041de92cf036/handoff/hk-stage-failure-chat-20261008)，目标为 `20261008 / STAGE_0930_0935 / HK_CONNECT`。本说明给出源码身份盘点、只读检查和离线验收步骤；这些操作不构成部署或失败槽恢复。实际 owner 的源码候选通过测试后，仍须分别取得真实业务源、Mac 集成、发布、API/UI 和自然时段证据。

## 1. Stage 精确错误怎样成为 API 的粗粒度状态

以下位置均指问题包 `source/actual_stage_owner/` 中的固定字节，不是当前 canonical 的推测替代。

| 层次 | 源码位置 | 已核实行为 |
| --- | --- | --- |
| 固定输入校验 | `stage_center/_runner_parts/hk_input_validation.py`，缺少 provenance 分支及其后的行级日期分支 | 价格日与资格日分离时，没有对象就抛出 `HK D1 split-date eligibility provenance missing`；补对象后仍须满足价格日、资格日、身份、capture-time 和每行 `signal_date`。 |
| HK 绑定 | `stage_center/_runner_parts/slot_execution.py`，72–80、162–165 | HK 绑定错误保留为 `hk_binding_error`，进入 `exact_input_errors["HK_CONNECT"]`；有效 A 股输入仍可继续。 |
| HK 来源结果 | 同文件，309–317 | 原错误进入零行 `SourceResult(..., "CANNOT_CONFIRM", cannot_confirm=(error,))`，不调用该 HK 采集分支。 |
| HK 发布 | 同文件，584–588、649–657 | 零行 `CANNOT_CONFIRM` 跳过 HK raw、selection 和 latest 发布；市场回执保存精确错误、`selected_rows=0`、`write_performed=false`。这里的 0 不是一次成功选出零只。 |
| 跨市场状态 | 同文件，697–702；`ops/run_stage_center_nodes.py`，212–218 | A 有有效写入而 HK 被阻断时，总体可以是 `PARTIAL_WITH_ROWS`；有写入的 partial 被判为 `SETTLED_PARTIAL`。总体 `write_performed=true` 不能用于声称 HK 写入。 |
| 调度回执 | `ops/_run_stage_center_nodes_parts/stage_dispatch.py`，367、384–427 | 调度层保留 runner 市场结果，增加 attempt、dispatch、outcome 等元数据，并经原回执入口持久化。 |
| API 当前入口 | `source/api_runtime/GET_stage_read_path_excerpt.txt`，原 `app.py` 5047、5227–5234 | 当前 GET 调用 `shared_selection_consumer.get(selected, stage, allow_backfill=True)`，随后还有两个 HK 投影/override 函数。它是读取入口，不能证明 Stage 再执行。 |

当前 API 的完整 `app.py`、`stage_center/consumer.py` 和 override 实现未包含在此包中。该包的 API 回读摘要确认实际显示了 `SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID`；源码摘录只足以确认调用 shared consumer，不能单凭摘录证明当前 consumer 的完整异常映射字节。

上一轮已存档的 consumer 参考文件 SHA 为 `865c2ea8183e5e6aeb9145ce2bfbb3e5b442825904b14c47fe024593a9205489`。其中 `read_verified` 失败会转为 `_invalid_market`，该分支把公开错误统一为上述 sentinel，并把行数、run 和 artifact 身份设为未确认。这与本次观测一致，但该旧副本不能冒充当前 API owner 的独立 SHA 验收。Mac 接续时应记录当前 consumer 与 override 文件身份并核实只读调用链，不因摘录不全而修改 API。

## 2. 已 settled 的旧槽不会因替换校验器自动恢复

实际 `ops/run_stage_center_nodes.py` 的 `_stage_settled` 把 `SETTLED_PARTIAL` 视为 settled。实际 `stage_dispatch.py` 的 153–196 行通常会返回 `SKIPPED_ALREADY_SETTLED`。已有特殊恢复形状要求 HK 唯一错误为 `HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE`，并核对日期、模式、attempt 预算等条件；当前 `provenance missing` 错误不满足该形状。

另一条 `_exact_hk_d1_dependency_rearm` 路径要求已有回执为顶层 `CANNOT_CONFIRM`、重试耗尽以及精确失败层和安全状态，也不是对所有 `SETTLED_PARTIAL` 槽的通用重开授权。

因此，当前候选源码通过校验测试仍不能推出 10 月 8 日旧槽已重跑。不得删除或改写原回执、latest、attempt/rearm 标记来获得成功；不得改动 A 股已成功结果。任何旧槽恢复需要独立、可复核的恢复设计和明确授权。现在补跑得到的结果也不能被记为 09:30–09:35 的自然运行。

## 3. 当前冻结身份及仍需补足的业务证据

| 对象 | 冻结记录 | Mac 接续要核对的内容 |
| --- | --- | --- |
| Stage owner | `com.lexi.stage-center.scheduler`；`20261003-hk-binding-wrapper-r3` | 当前加载入口、工作目录、配置、解释器和精确源文件 SHA；不以 API PID 代替 Stage owner。 |
| API owner | `com.lexi.v35.api-only`；`manager-daily-chain-20261008-r3-api/app`；8873 | 当前监听 PID 和 launchd 状态、API 源文件 SHA、实际 consumer 和 override 身份。旧 PID 21204 只是一次观测值。 |
| Stage 校验器 | canonical 与 actual 均为 `92e8fb2be06e6530c33f3cf2f5b44f29b0bcf7875e6a5902260f8be4c814f735` | 前像应一致；只允许各 owner 明确列出的候选后像，避免把整棵 canonical 覆盖实际 Stage。 |
| 实际日期 owner | primary 无 10/08 日期目录；secondary 有该目录 | 用原 resolver 的 whole-date 规则确认；不得按单个池改为跨根混读。 |
| 物理本地池 trio | artifact `62d7716c…`；manifest `cc476019…`；receipt `1871468d…` | 原 reader 返回稳定且一致的物理 trio 身份；三者只证明该本地池的完整性与来源归属。 |
| 上游 D1 来源 | payload `source_sha256=ce4e9422…`，不同于本地 artifact SHA | 用真实原来源 reader/manifest/receipt/run 验证价格来源；不得把上游 artifact SHA 与本地 manifest/receipt SHA 拼为一组。 |
| 价格信号 | 目标价格日应为 `20261007`，现有 100 行为 `20260930` | 真实 10/07 价格输入及其完整身份链尚缺。保留旧池原字节，不改标行日期。 |
| Connect 资格 | 资格来源日应为 `20260930` | 需要独立资格 artifact、run、可追溯的 manifest/receipt 和真实 capture-time。当地 capture 日期须满足 Stage 原约束；不能从价格池 hash 或当前时间推造。 |
| 历史失败回执 | `cb8be29778c1d1bb8c2dc44266ce0495b8efc1da094911e84864a9a2bad6193b` | 保留原始文件及 SHA，读取精确 HK 市场结果；包内摘要不是原始回执替代品。 |

任何来源证据缺项仍为 `CANNOT_CONFIRM`。当前候选只增强校验完成前对稳定物理 trio 身份的复核；分层证据在交付中报告，不向 runtime 新增证据字段。它不能修复旧 9/30 行、创造 10/7 价格，或补出 provenance 和真实资格 capture。两项历史 P2 的 Mac 38/38 和 canonical 集成不替代本次业务输入、Stage 发布与运行证据。

## 4. Mac 只读检查

以下命令不导入 V4 应用、不调用 Stage 主入口、不发起数据恢复。先把 `ISSUE28_PROBLEM_DIR`、`ISSUE28_CANDIDATE_DIR` 和 `ISSUE28_ACCEPTANCE_DIR` 设为实际解包目录；不要把候选根设为实际服务根。

```bash
: "${ISSUE28_PROBLEM_DIR:?请设置完整问题包目录}"
: "${ISSUE28_CANDIDATE_DIR:?请设置已核验的候选交付目录}"
: "${ISSUE28_ACCEPTANCE_DIR:?请设置本说明与审计脚本所在目录}"
ISSUE28_STAGE_ROOT="$HOME/Desktop/学习/agents调试/V4_HK_STAGE_RECOVERY_20261003/issue23_runner_helper_r3/stage_r1_binding_candidate_r3/app"
ISSUE28_CANONICAL_ROOT="$HOME/Desktop/学习/v4_app"
ISSUE28_API_ROOT="$HOME/Library/Application Support/com.lexi.v4.local/releases/manager-daily-chain-20261008-r3-api/app"
ISSUE28_RECEIPT_ROOT="$HOME/Library/Application Support/com.lexi.v4.local/state/stage/receipts"
ISSUE28_PY="$HOME/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python"

"$ISSUE28_PY" -B -c 'import sys, platform; from enum import StrEnum; print(sys.executable); print(sys.version); print(platform.platform()); print("StrEnum import OK")'

"$ISSUE28_PY" -B "$ISSUE28_ACCEPTANCE_DIR/audit_runtime_identity.py" \
  --problem-root "$ISSUE28_PROBLEM_DIR" \
  --stage-root "$ISSUE28_STAGE_ROOT" \
  --canonical-root "$ISSUE28_CANONICAL_ROOT" \
  --api-root "$ISSUE28_API_ROOT" \
  --receipt-root "$ISSUE28_RECEIPT_ROOT" \
  --candidate-manifest "$ISSUE28_CANDIDATE_DIR/candidate_identity.json"
```

解释器路径来自实际配置的冻结记录，执行前应与下面的 launchd/config 观测一致。系统 Python 3.9 的 `StrEnum` 导入不兼容；不能用它失败后的结果替代 V4 owner 的测试。脚本读取固定 source identity 允许清单内的 30 个文件（15 canonical、13 actual Stage、2 API）、实际 Stage 配置和唯一指定日期/阶段的回执；不枚举数据目录。

脚本要求 `candidate_identity.json` 具有严格结构：`schema_version=issue28.hk_stage_candidate_identity.v1`，`files` 每项仅有 `owner`、`path`、`before_sha256`、`after_sha256`。候选只允许 frozen 清单内 canonical / actual Stage 路径，前像必须与冻结证据一致。运行源文件分别显示 `MATCHES_BEFORE`、`MATCHES_AFTER`、`DIFFERS`、`MISSING` 或 `UNREADABLE_OR_UNSTABLE`。`SOURCE_MATCH` 仅表示文件身份匹配，脚本始终保留 `runtime_recovery_status=CANNOT_CONFIRM`。

退出 0 只表示清单读取/身份和最小配置回执检查满足；退出 2 表示输入/manifest 被拒绝；退出 3 表示缺文件、身份差异或配置回执缺口。不能把退出 0 当作 provenance、部署或阶段恢复通过。对一份故意不含完整 API app 的离线问题包运行时，缺失项应保留未确认，不能补空文件获得通过。

加载状态只读观测可用下列命令；输出只保留状态字段，不导出 LaunchAgent 的环境变量。`not running` 本身不能证明计划任务损坏，最近 exit 3 也需要对应那次进程证据才能归因。

```bash
"$ISSUE28_PY" -B - <<'PY'
import json, os, re, subprocess
labels = ("com.lexi.stage-center.scheduler", "com.lexi.v35.api-only")
for label in labels:
    completed = subprocess.run(
        ["/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"],
        text=True, capture_output=True, check=False, timeout=10,
    )
    allowed = []
    for line in completed.stdout.splitlines():
        if re.match(r"^\s*(state|pid|last exit code|program|working directory)\s*=", line):
            allowed.append(line.strip())
    print(json.dumps({"label": label, "command_exit": completed.returncode,
                      "loaded_fields": allowed,
                      "status": "OBSERVED_ONLY" if completed.returncode == 0 else "CANNOT_CONFIRM"},
                     ensure_ascii=False))
PY
```

API 回读应限定为已有 `GET /api/v3/workbench/stage?date=20261008&stage=STAGE_0930_0935`，记录 HTTP 状态、日期/阶段、各市场状态、run/artifact 身份和三个安全 flag，不上传原始行或完整响应。只有 HTTP 200 不通过 HK 验收。由于当前 GET 显式允许 backfill 且后续存在 override，还必须区分自然结果、历史回补及只读展示覆盖；API 显示有行不能自动升级为自然运行成功。

若需补齐当前 API 的源码映射证据，应在已读回身份的 API 工作根中读取 `stage_center/consumer.py` 的 `_market_from_store_or_backfill`、`_invalid_market` 和实际 `app.py` 的两个 HK override 函数，并记录完整文件 SHA。无需运行服务主入口。若当前 consumer 来源根另有配置或 `sys.path` 覆盖，必须先确认实际导入位置；路径里出现同名文件不足以证明进程使用它。

## 5. 离线测试、集成及后续发布的分界

离线候选测试必须使用交付中实际提供的双 owner harness 命令和已记录依赖。分别保留未改前像、候选后像、原测试结果、新回归结果、解释器和源文件 SHA。若 harness 使用补充的固定历史依赖，报告其 commit/SHA 和 scope，不能称为实际 Stage 完整 runtime 复跑。不要为获得绿色结果静默改原测试 fixture，或使用测试替身掩盖产品 Store 的真实校验。

原问题包的 19 项测试已用未改测试文件逐 owner 执行：actual Stage 为 12 PASS / 7 FAIL，canonical 为 17 PASS / 2 FAIL；均无 error / skip，原始退出码为 1。这些 FAIL 应保留。对应入口是 `harness_agent/run_original_baseline.py --owner both`，实际 Linux 解释器为 Python 3.14.7，pytest 9.1.1。该 harness 实际加载 7 个精确 owner 模块和 17 个固定补充依赖，验证范围为 HK 绑定与物理 Store，不包含 ops 调度、slot 完整发布或 API。原始命令、导入来源和逐项结果见 harness 的 `logs/original_baseline/RESULTS.json` 与各 owner 的 imports / log / XML。

若主交付保留该原基线 harness，Mac 可用以下入口复跑原失败；它不是候选后像通过入口。把日志目录设为新的隔离位置，保留 Linux 原始证据，不指向任何业务根：

```bash
: "${ISSUE28_ORIGINAL_HARNESS_DIR:?请设置交付中的原基线 harness 目录}"
: "${ISSUE28_MAC_ORIGINAL_LOG_DIR:?请设置新的隔离日志目录}"
"$ISSUE28_PY" -B "$ISSUE28_ORIGINAL_HARNESS_DIR/run_original_baseline.py" \
  --owner both --log-dir "$ISSUE28_MAC_ORIGINAL_LOG_DIR"
```

后像 harness 的具体入口和最终结果以主交付实际执行记录为准，不以原基线命令替代。

至少分开覆盖：没有 provenance；有 provenance 但行级价格日仍为 9/30；合法分日期来源；上游 hash 与本地 trio 混用；trio/owner 在读取中变化；日期、市场、Top100、capture-time 和安全 flag 不满足。只有合法现存来源的正例可用于确认候选接受路径；合成 fixture 的绿色测试只证明合同处理能力。

本目录审计脚本本身有 5 项标准库烟测。在解包后的 Mac 可复跑：

```bash
ISSUE28_HK_PROBLEM_ROOT="$ISSUE28_PROBLEM_DIR" \
  "$ISSUE28_PY" -B "$ISSUE28_ACCEPTANCE_DIR/test_audit_runtime_identity.py"
```

这 5 项只验证审计工具的临时 fixture 行为，包括前/后像分类、输出不包含行和配置秘密、缺少运行源码仍未确认、冻结证据与允许路径拒绝、符号链接拒绝，以及每次审计前后 fixture 文件字节不变。它们不是 5 项 HK 产品回归。Linux 已执行结果见 `SMOKE_TEST_RECEIPT.json` 与 `SMOKE_TEST.log`；Mac 执行仍为 `NOT_RUN`。

| 阶段 | 通过所需证据 | 本文能否宣称通过 |
| --- | --- | --- |
| 候选实现与双 owner 适配 | 两个明确 owner 的候选 diff、前后 SHA、所需依赖及合同回归 | 以主交付的实际测试记录为准；本文只完成调用链盘点。 |
| Mac 独立测试 | Mac owner 解释器、精确前后像和独立回归回执 | `NOT_RUN`。 |
| 源码集成 | 分别确认 canonical 与 actual Stage 工作副本的后像身份，保留并行改动 | `NOT_RUN`；文件检查不能代表已加载进程。 |
| 部署 | 审查通过的具体发布清单、回滚前像、owner 切换和运行版本读回 | 未授权、`NOT_RUN`。 |
| 旧槽恢复 | 真实输入完整，针对冻结失败回执的恢复设计，保留 A 结果和旧证据 | 未授权、`NOT_RUN`；不能清除 settled/attempt 状态获得重跑。 |
| API / UI | 对应已验证 selection 身份的只读 API 和实际 UI 读回，区分 backfill/override | 当前只有失败状态的 HTTP 200 摘要；本轮验收 `NOT_RUN`。 |
| 自然时段 | 实际计划任务自然触发、真实采集时间、正常日期与窗口、完整来源/发布回执 | `NOT_RUN`；人工补跑、离线回放和历史 backfill 均不能替代。 |

## 6. 回滚范围

当前只读审计和隔离测试不需要业务回滚。若未来另行获准集成或发布，应只针对候选清单列出的文件和精确 owner 建立前像备份，记录文件权限与 SHA；应用后立即复核目标后像。如现场前像已变化，停止应用该文件并核对并行工作，不直接覆盖。

回退源码时只恢复这批文件的匹配前像。不能回退整棵 canonical 覆盖 Stage，也不能恢复、删除或覆盖行情、预选池、raw/selection/latest、失败回执、attempt/rearm 标记来配合源码回退。API release、Vibe 8910、计划任务和其他已集成改动不属于此候选文件回滚范围。真正的服务切换和旧槽恢复命令须在后续独立审查与授权后形成，本文不提供自动执行它们的命令。
