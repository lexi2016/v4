# Mac 分项验收与隔离回滚

这是一份**待执行验收清单**，不预填本轮最终测试总数、Mac 成功结果或交付提交。各命令须在实际 Mac、已核实的固定来源和独立候选中执行。源码层回归、原 owner 合成 fixture、真实私有业务资产、API/Chrome 页面和部署状态分别记录。

依据：固定交接 `46081f5bcfb5f0c9e63aaa8b2b7baf65ae191eff` 的 `REPRO_AND_ACCEPTANCE.md`、`ADDITIONAL_INTERFACE_AND_PROGRESS.md`、更新后的 `US_STATUS_APPENDIX.md`；本交付 `INTERFACE_CONTRACT.md`；各固定来源保留的原验收文档。最终补丁、完整 after-files、前后文件 SHA 与本地实测汇总由主交付报告提供。

## 1. 三个固定来源分别应用增量

| 独立候选 | 必须从该固定来源建立 | 本轮增量范围与应用要求 |
|---|---|---|
| 经理 V5 | `3d9541aca3e5d28e94109609940503cca239b9fe` | current_recovery 与 Reader/Reviewer 合同；经理、tick、dispatch、owner adapter、revision adapter 及新 handoff 模块、相应测试/文档；以交付文件 SHA 清单为准 |
| 超跌 V5 | `ebe5944ecfbec2f6a161793d7c11946dea063e57` | `rebound_panel_repair.py` 身份比较最小修复及新增 `test_rebound_owner_identity.py`；保留原业务代码和原 owner capsule |
| 公告 e06d bundle | `e06d143e881c66c22053a5c594b9c0be21d5be34` | 新的只读 reviewer binding 工具、拒绝/结构测试与交接文档；原 create/import、原 manifests 与原 bundle 文件保持冻结 |

操作顺序：先保留固定基线只读副本，再创建各自独立候选；对每个拟替换文件核对交付清单的 before SHA，应用对应补丁或完整 after-file，最后核对 after SHA。新增文件须确认为交付新增项，不能覆盖同名未知本地文件。补丁相对根以交付清单为准，先做 `git apply --check`；不能靠调整 pin、删测试或修改日期使不匹配的基线通过。

交付根的实际目录合同如下。`CHANGE_MANIFEST.json` 是总变更清单；每项 SHA 清单按其中记录的相对路径在对应候选根核对，不能在错误来源树上应用。

| 增量 | 可应用补丁 | 完整文件与校验清单 |
|---|---|---|
| 经理 | `manager/changes.patch` | `manager/after/`、`manager/before/`、`manager/BEFORE_SHA256SUMS`、`manager/AFTER_SHA256SUMS` |
| 超跌 | `rebound/changes.patch` | `rebound/after/`、`rebound/before/`、`rebound/BEFORE_SHA256SUMS`、`rebound/AFTER_SHA256SUMS` |
| 公告修订 | `revision/changes.patch` | `revision/after/`、`revision/before/`、`revision/BEFORE_SHA256SUMS`、`revision/AFTER_SHA256SUMS` |

公告修订没有修改既有文件，故 `revision/BEFORE_SHA256SUMS` 为空；这不替代对原 e06d bundle/manifests 的固定身份核验。原独审请求单独位于 `original-reviewer/reviewer-binding-request.json`，不是可导入 reviewer。

不要把三个来源的整棵树相互覆盖。经理中的冻结 e06d capsule 继续按自己的 manifest 校验；e06d 新工具不装进原 owner app。原 V4、BUY、Stage、正式 admission、既有产物与旧 `latest` 指针均不作为增量目标。

## 2. 实际路径和运行环境

下列变量由 Mac 操作者填写**已经核实的实际绝对路径**，本文不提供猜测路径。每次验收使用新的证据目录，避免覆盖之前的失败或成功记录。

| 变量 | 指向的真实对象 |
|---|---|
| `DELIVERY_ROOT` | 解包后含 `CHANGE_MANIFEST.json`、`manager/`、`rebound/`、`revision/`、`original-reviewer/` 的交付根 |
| `V5_PYTHON` | 独立 CPython 3.14.6、原 uv.lock 依赖环境中的解释器 |
| `MANAGER_V5_ROOT` | 应用经理增量后的 V5 目录，含 `src/`、`tests/`、`uv.lock` |
| `REBOUND_V5_ROOT` | 应用超跌增量后的 V5 目录 |
| `E06D_BUNDLE_ROOT` | 应用公告增量后的完整 e06d bundle，含 `candidate/`、`tests/`、`tools/` |
| `MAC_EVIDENCE_ROOT` | 本次新的私有验收证据目录 |
| `REVIEW_REQUEST` / `REVIEW_REQUEST_SHA256` | 交付根 `original-reviewer/reviewer-binding-request.json` 的实际绝对路径及已核实的实际文件 SHA |
| `ORIGINAL_REVIEWER` / `SEMANTIC_CATALOG` / `ARTICLE_DECISIONS` | Mac 原真实冻结文件，不能使用脱敏诊断替身 |
| `ACTUAL_RETURNED_REVIEWER` / `ACTUAL_RETURNED_REVIEWER_SHA256` | 原审核者真实返回后才填写的新文件与新文件 SHA |
| `MANAGER_REAL_REQUEST` | 原 owner 真实导入和反读后形成的合法经理请求；未具备时该项验收保持 NOT_RUN |
| `V5_REBOUND_REPAIR_REAL_INPUT` | 原流程已批准的真实私有模型/raw/capture/repair 绑定 JSON |

先检查必需环境变量和实际解释器：

```sh
: "${V5_PYTHON:?请设置实际CPython3.14.6解释器绝对路径}"
: "${MANAGER_V5_ROOT:?请设置实际经理候选V5绝对路径}"
: "${REBOUND_V5_ROOT:?请设置实际超跌候选V5绝对路径}"
: "${E06D_BUNDLE_ROOT:?请设置实际完整e06d候选bundle绝对路径}"
: "${MAC_EVIDENCE_ROOT:?请设置本次新证据目录绝对路径}"

"$V5_PYTHON" -B -c 'import platform,sys; assert platform.python_implementation()=="CPython" and sys.version_info[:3]==(3,14,6); print(platform.platform()); print(sys.version); print(sys.executable)'
"$V5_PYTHON" -B -c 'import numpy,pandas,pyarrow; print({"numpy":numpy.__version__,"pandas":pandas.__version__,"pyarrow":pyarrow.__version__})'
shasum -a 256 "$MANAGER_V5_ROOT/uv.lock" "$REBOUND_V5_ROOT/uv.lock"
```

保留原 `uv.lock`，用原项目的 locked/frozen 安装方式建立独立环境，记录 lock SHA、解释器和实际依赖版本。不得改锁文件、改 Python 版本、使用未验证替代依赖或仅关闭 skip 来补足验收。若既有两个候选需要各自独立环境，分别填写 `V5_PYTHON` 并分别记录；每个实际运行环境都须满足同一要求。

每项记录 `SOURCE_BASE_REF`、`DELIVERY_COMMIT=待主报告填写`、before/after 文件 SHA、命令、开始/结束 UTC、退出码、测试名称及实际 PASS/FAIL/ERROR/SKIP。下文测试数量均由真实日志填写，不依据旧文档的预期数量推算。

## 3. 经理与接口的源码 / fixture 验收

在经理候选运行原 daily 组及新增修复组：

```sh
cd "$MANAGER_V5_ROOT"
PYTHONPATH=src:tests "$V5_PYTHON" -B -m unittest \
  test_us_mapping_scope test_run_ledger test_daily_dispatch test_daily_us_owner \
  test_daily_owner_adapters test_daily_manager_assembly -v

PYTHONPATH=src:tests "$V5_PYTHON" -B -m unittest \
  test_manager_plan test_manager_plan_date_gate \
  test_manager_current_recovery test_daily_review_handoff -v

V5_ANNOUNCEMENT_REVISION_TEST_BUNDLE="$E06D_BUNDLE_ROOT" \
  PYTHONPATH=src:tests "$V5_PYTHON" -B -m unittest test_daily_revision_chain -v
```

最后一组需要完整固定 e06d fixture bundle；缺 fixture 应记 ERROR / NOT_RUN，不能改成 skip。它在临时合成材料上执行原 create、prepare、register、verify、import、readback，再由原经理保存和普通 auto 读取。它不生成本批真实 392 条审核结果，也不证明真实后台已接入。

重点验收如下，逐项填写实际结果：

| 场景 | 必须得到的行为 |
|---|---|
| 固定旧目标 `20261009`、实际当前 now | 跨日保存到 `current_recovery`，不得把目标改成今天来掩盖原错位 |
| 当天正常目标 / 原正常路径 | 保留原 store 与原 CURRENT 行为 |
| 普通 `view=auto` 读取恢复计划 | 与保存结果的精确 run ID、产品 SHA 和目标日一致；成功为 `CURRENT_RECOVERY` |
| 显式 `view=historical` | 继续进入原历史资格门；不能消费 current_recovery 作为历史可用计划 |
| 本目标没有恢复计划、只有其他目标恢复 | 不借用其他目标，不隐藏原历史资格缺失 |
| 已绑定输入变化或去掉已消费 owner 版本 | 拒绝或 `consumed=false`；不能沿用旧输入身份声称已消费 |
| 缺精确 journal、缺全部 journal、篡改 journal | 恢复读回 fail closed；不得为 `CURRENT_RECOVERY / consumed=true` |
| 恢复目录/文件符号链接、无效输入 SHA | 拒绝，外部目录和原计划文件不被写入 |
| 缺原独审、同一 reader/reviewer、缺修订字段、错误决定摘要或 semantic SHA | preflight 阻塞，公告业务账本不新增 attempt |
| 前序 lane 运行期间 reviewer 文件丢失/改变 | 实际 claim 前再次阻塞，公告账本不新增 attempt |
| 通道在 submit/poll 回调内记录实际时间 | 正常 acknowledgement/heartbeat 可被验证；真正未来或过期 heartbeat 拒绝 |
| submit/poll 回调抛错、错误 request/source/output | 保留失败或未知结果，不自动重提，不生成业务成功 |

所有删除 journal、篡改 SHA、移动 reviewer 等故障注入只运行在测试临时副本。不要在真实历史 root、实际恢复产物或真实 reviewer 文件上操作。

### 实际经理原 owner 保存 / 读回

只有原 owner 的真实输入版本和导入反读已经具备，才使用 `MANAGER_REAL_REQUEST` 进入本步骤。缺原独审返回或其他真实输入时，保持该项 NOT_RUN，保留明确缺项。固定旧目标的手工恢复不通过 daily tick 冒充当天调度；daily tick 仍坚持当前目标与原时间窗口。

1. 核对请求 `target_date=20261009`，绑定真实已验证 owner 版本及文件 SHA，输出使用独立候选的标记根。新根按原合同建立 `.v5-manager-plan-root`；仅复用已有原计划时，先保存其完整清单和每文件 raw SHA。
2. 在原 owner 导入完成之后采集实际 `datetime.now(timezone.utc).isoformat()` 作为此次经理 `now`；不倒填 10/9，也不改写真实 source 的 available_at。
3. 调用 `run_manager_plan`，`action=refresh`、`view=auto`，保留原目标绑定。记录返回的 `readback.store_relative`、run ID、计划 SHA、input identity、精确 journal 和实际 generated_at。
4. 用同一已核绑定执行 `action=read`、`view=auto`，读时使用实际当前时钟；再次独立读回。成功必须同时满足 `consumed=true`、`CURRENT_RECOVERY`、同目标/run/SHA，而非只比较旧引用。
5. 核对 `read_context.mode=CURRENT_RECOVERY`、`requested_view=auto`、`owner_view=dynamic`、`historical_eligible=false` 和实际 `read_as_of`。响应附加的恢复身份不能改变保存计划的原 SHA。
6. 精确读取 `manager_output_root/current_recovery/workspace_plans/20261009/<run_id>.json` 与同根 `workspace_plan_runs/20261009/<run_id>.json`，核对原 owner 封存 journal 和产品身份；正常根的旧 `workspace_plans`、`workspace_plan_runs` 和旧指针逐字节不变。
7. 显式 historical 读取保持原 PIT 资格判断；真实恢复结果不得登记成虚假的历史可用 CURRENT。

保留此次真实调用的请求摘要、原 owner 引用、两次读回摘要、旧文件前后清单、原计划 run/SHA 和实际时钟证据。源文中保存时间、读取时间和香港目标日是不同概念，证据必须能区分。

### API / Chrome 另验

合成 loopback HTTP 测试通过后，仍须在**已实际接线的候选 API / Chrome 页面**独立验收；本文不安装服务、启动服务或发布 module generation。

由现有 host 核对候选 API 的实际 base URL、release ID、module generation、源请求 SHA 与预期路由。原路由为 `/api/v4/manager/research/workspace`，普通查询为 `?date=20261009&view=auto`；不能用手工改成 dynamic 的 URL 替代普通 auto 验收。

若需要 `publish_workspace_read`，由已有候选发布流程显式提交经过原 owner 计算的只读结果，再进行 GET。GET 本身只读取已提交 generation，不能临时写计划。Chrome 实际页面显示的 run/SHA、恢复身份、目标日和历史资格必须与保存及 API 返回对应；检查网络响应、刷新后的稳定性和无计划文件写入。记录实际 URL、release/generation、响应 SHA、截图时间和文件清单差异。未接线或没有 Chrome 实测时分别记 `API_NOT_RUN` / `CHROME_NOT_RUN`。

## 4. e06d 原独审补绑定与原命令链

### 4.1 独立回归

在完整 e06d bundle 中逐文件启动独立 Python 进程，避免原 owner fixture 的模块状态相互污染：

```sh
cd "$E06D_BUNDLE_ROOT"
for case_file in \
  test_decision_revision.py test_offline_analysis_chain.py test_offline_evidence_recovery.py \
  test_v5_private_owner.py test_capture_budget_red.py test_cli_import_red.py \
  test_failed_partial_pages.py test_http_policy_red.py test_oversized_http_review.py \
  test_owner_path_review.py test_provider_byte_accounting_red.py \
  test_revision_review_gate.py test_revision_review_tool.py
do
  "$V5_PYTHON" -B -m unittest discover -s tests -p "$case_file" -v
  case_status=$?
  if [ "$case_status" -ne 0 ]; then exit "$case_status"; fi
done
```

新增 gate 测试须证明缺失、错配或错误类型的五项 binding、错误文件 SHA 和决定摘要都在原 create 的目录/锁/写入前拒绝，原父输入字节不变。结构工具须保持原 reviewer 既有字段的类型和精确值，包括嵌套值、布尔/整数/小数差别及大整数附近的小数；`9007199254740993.0` 被替换为 `9007199254740992.0` 必须拒绝，不能被二进制浮点舍入掩盖。原 owner 文件与原 manifests 仍按交付不变性清单核 SHA。

### 4.2 缺原独审返回时，只做等待预检

确认 `REVIEW_REQUEST_SHA256` 是请求文件本身的实际 SHA，原 reviewer、semantic 与 decisions 都是原真实字节；本批固定值见 `INTERFACE_CONTRACT.md`。然后运行：

```sh
"$V5_PYTHON" -I -B "$E06D_BUNDLE_ROOT/tools/review_revision_binding.py" inspect \
  --request "$REVIEW_REQUEST" --request-sha256 "$REVIEW_REQUEST_SHA256" \
  --original-reviewer "$ORIGINAL_REVIEWER" \
  --semantic-catalog "$SEMANTIC_CATALOG" --decisions "$ARTICLE_DECISIONS"
```

正确冻结输入但尚无返回时，预期为 `BLOCKED_AWAITING_ORIGINAL_REVIEWER`、退出码 2；这是等待状态，不能为取得退出码 0 而拼出 reviewer。错误摘要等合同问题为 BLOCKED，记录具体原因。该工具只读、不创建 revision，也不消耗 daily 业务 attempt。

原独审任务必须经原有审核通道核实实际作者和独立性，范围仅为新 revision 的精确五字段绑定。原 392 条不重读、不重决；semantic 和 decisions 文件逐字节保持固定。原 reviewer 既有字段不改，仅由原人补 binding；新时间、任务/worker、channel、request SHA、返回文件 SHA 以真实回执留存。

### 4.3 原人真实返回之后

`ACTUAL_RETURNED_REVIEWER_SHA256` 目前为待返回值。收到真实文件并核对通道证据后才设置；不可用旧 reviewer SHA、请求 SHA 或结构报告 SHA 替代。

```sh
"$V5_PYTHON" -I -B "$E06D_BUNDLE_ROOT/tools/review_revision_binding.py" inspect \
  --request "$REVIEW_REQUEST" --request-sha256 "$REVIEW_REQUEST_SHA256" \
  --original-reviewer "$ORIGINAL_REVIEWER" \
  --semantic-catalog "$SEMANTIC_CATALOG" --decisions "$ARTICLE_DECISIONS" \
  --reviewer-output "$ACTUAL_RETURNED_REVIEWER" \
  --reviewer-sha256 "$ACTUAL_RETURNED_REVIEWER_SHA256"
```

即使得到 `STRUCTURAL_BINDING_VERIFIED` / 退出码 0，报告仍为 `authorship_verified=false`、`semantic_review_performed=false`、`authorizes_import=false`。只有原通道来源已另外核实后，才交给原 `DECISION_REVISION.md` 所列命令链。

1. 真实输入放入原恢复根的独立 inputs，保持原文件；核对新 revision ID、父产品逻辑 SHA、父回执文件 SHA、恢复回执 SHA、source run 和原 semantic/decisions SHA。
2. 按原 owner 执行 `create → prepare → register-handoff → verify → import → readback`，保存每条实际 argv、开始/结束时间、退出码及输出摘要。create 必须使用真实新 reviewer 文件 SHA。
3. 缺输入时不执行真实 create 来制造失败目录。若 ID 已存在或留有 pending 失败目录，保留证据；新的 ID 必须重新取得原人针对该绑定的返回，不能删目录复用或自行修改 reviewer 中 ID。
4. 新 available_at 必须是实际新导入时间。经理随后通过原读取接口消费新版本；不能覆盖原父产品、旧计划或历史 PIT。
5. 原 91 项门禁及缺证据 NOT_ASSESSED 继续生效。保持原统计：文章 392＝事件 2 / 业绩 0 / 观察 26 / 不选 270 / 未评估 94；发行人 281＝2 / 26 / 182 / 71。结构绑定通过不构成重新审批这些决定，也不将整批变为正式选股准入。

## 5. 超跌身份、原模型与私有 repair 验收

先运行新身份回归和原指定模块：

```sh
cd "$REBOUND_V5_ROOT"
PYTHONPATH=src:tests "$V5_PYTHON" -B -m unittest test_rebound_owner_identity -v
PYTHONPATH=src:tests "$V5_PYTHON" -B -m unittest \
  test_rebound_panel_repair test_rebound_raw_repair \
  test_rebound_admission test_rebound_observation -v
```

确认正确冻结 loader 在尚未展开 code 属性前就通过；持有/释放 docstring 引用不改变身份结果。替换函数、嵌套 code、导入 helper、globals、常量和 native layout 仍须拒绝。身份修复只改变结构比较方法，不能跳过原模型、源码与 native 布局验证。

随后仅在真实原模型/locked 依赖、已批准 raw/capture 绑定及独立私有资产副本具备后，显式启用原 opt-in：

```sh
: "${V5_REBOUND_REPAIR_REAL_INPUT:?须先具备原流程批准的真实私有输入绑定JSON}"
V5_REBOUND_REPAIR_ORIGINAL_TESTS=1 \
  V5_REBOUND_OBSERVATION_ORIGINAL_TESTS=1 \
  V5_REBOUND_REPAIR_REAL_INPUT="$V5_REBOUND_REPAIR_REAL_INPUT" \
  PYTHONPATH=src:tests "$V5_PYTHON" -B -m unittest \
  test_rebound_panel_repair test_rebound_observation -v
```

保留既有 skip 装饰器。未设置 opt-in 或未提供真实输入导致的 SKIP 必须按原文记录为未验；不能报告私有 repair 已通过。不得用 synthetic capture/approval、常量数值、伪造包装或回填时间满足真实输入合同。

真实资产验收必须在原测试建立的完整隔离副本中发布 child 并独立反读。逐字节核对**原始资产根**的 panel、pointer、manifest、model、native/raw、capture 和 approval 不变；候选副本的新 child、回执和指针变更单独留证。原 publisher 本身可以修改其被配置的 asset root，所以复制隔离是执行此测试的前提，不能把真实生产根直接传给它。

保留 scale=1、价格/量单位、来源与最终性证据要求、逐码正式 admission 和原 694 批量 HOLD。数值满足原两门，仅说明数值条件；不能直接声称正式可选、全批可放行或自动部署。缺真实数据、单位或来源证据时继续明确 BLOCKED。

## 6. US 独立已验状态：引用附录，不重复修复

`US_STATUS_APPENDIX.md` 已更新旧 ZIP 的 US NOT_RUN 状态：独立修复 `7a3d3bc1e7a51899a60b455fcc6502c9e66eab60` 在 Mac、CPython 3.14.6 单次验收，`test_native_identity_reader` 与 `test_us_mapping_scope` **11/11 通过、无 skip**；时间为 `2026-10-10T01:09:09.210977–01:09:10.723008Z`。该修复**未部署、未修改旧 f21f72**，本轮不混入三项冻结失败基线，不重做该 US 修复。

继续保留附录的剩余缺项：native master 索引有 `20261009`，无所需 `20261008` entry；仍缺该日 manifest/receipt/artifact 及取得时间完整绑定。不能拿 10/9 主档或 Connect 替代。原 scope 为 PARTIAL，已评估上涨 0、未评估上涨 8，`formal_eligible=false`，不能称全市场零机会。

## 7. 回滚与最终交接记录

本轮候选默认独立、未启用。验收失败时停止推进候选的后续步骤，保留原失败日志、pending revision、未知任务回执和 candidate ledger；不清空 daily attempt 来模拟首次执行，不复用失败 revision ID。

代码回滚在独立候选中使用对应 `manager/before/` 或 `rebound/before/` 恢复修改前文件并核对 `BEFORE_SHA256SUMS`，或直接停用候选入口并保留固定基线供原流程使用。revision 仅有新增文件，无旧文件可恢复；停用其新增工具入口即可，保留输入与证据。不要把三个源树整体互相覆盖。候选未发布时无需触动现有服务或历史指针；若现有 host 之后执行了明确的候选接线/发布，则由该 host 按其已有回滚合同恢复原绑定或 generation，并记录实际变化。本文不提供猜测的 launchd label、进程命令或生产路径。

**不得删除历史计划、原 panel/pointer、原 reviewer、source receipt、原父产品或失败证据。** current_recovery 与新 revision 留在各自隔离目录，不能为了回滚而反写旧计划；真实任务结果未知时，先由原通道 readback 对账，再决定后续动作。

最终记录表由执行者据实填写：

| 项目 | 待填记录 |
|---|---|
| 交付身份 | `DELIVERY_COMMIT`、交付文件清单 SHA、三项固定 baseline |
| Mac runtime | 平台、CPython 3.14.6、lock SHA、实际依赖与执行路径 |
| 源码 / fixture 回归 | 每组命令、实际测试数量、PASS/FAIL/ERROR/SKIP、原始日志与退出码 |
| 经理真实恢复 | 原 owner 引用、目标 `20261009`、实际 now、run/SHA、journal、两次 auto read、旧字节不变 |
| 原独审 | 实际 channel/task/worker、请求 SHA、真实新 reviewer SHA，或明确 BLOCKED 缺项 |
| 超跌真实资产 | opt-in 与真实输入是否具备、child/receipt 反读、原 panel/pointer 字节不变，或 NOT_RUN |
| API / Chrome | 实际 URL、release/generation、普通 auto 查询、响应 SHA、截图时间，或分别 NOT_RUN |
| US | 引用既有 Mac 11/11 附录与未部署 / 10/8 缺项，不改记本轮新验收 |
| 部署 / 回滚 | 当前实际状态、是否有候选接线、已有回滚引用；未执行就记未部署 |
