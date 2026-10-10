# Mac 隔离应用、真实读回验收与回退

状态：**MAC NOT_RUN**。代码唯一 authority 为 **C = `6daed6271313b5ae5324c8948f163258ab8d1fa3`**；前像为 **F = `f7cb731c384ee6890a87d16c19a5b5a621779477`**。本文件依据这组代码身份和实际函数、CLI 编写；本会话没有启动 Mac 候选、切换端口、采集公告、重分类、刷新经理计划或执行回退。

交付分支为 `v5/module01-announcement-readback-20261010-chat`。后续材料提交 H 仅用于分发本目录的文件、索引和证据，不能替代 C 成为另一个代码运行基线；分支推进到 H 后，仍按下文 checkout **固定 C**，或在固定 F 应用本包差异。H 的身份由最终交付回执提供，本文件不把包含自身的材料提交伪称为其源码前像。现场真实路径、进程身份和入口切换设施由 Mac 操作人填写，这是输入边界，不是代码候选未完成。

## 1. 固定身份和本次成功条件

| 项目 | 固定值或要求 |
|---|---|
| V5 前像 F | `lexi2016/v4@f7cb731c384ee6890a87d16c19a5b5a621779477` 的 `V5/` |
| 唯一代码候选 C | `6daed6271313b5ae5324c8948f163258ab8d1fa3`；与 `SOURCE_MANIFEST.json.code_commit` 必须一致 |
| 交付分支 / 材料提交 H | `v5/module01-announcement-readback-20261010-chat`；H 仅材料，以最终交付回执核准，不以浮动分支 HEAD 代替 C |
| 源码与包校验入口 | `SOURCE_MANIFEST.json`、`verify_preimage.py`、`PACKAGE_INDEX.json`；索引记录交付文件 SHA，排除索引自身 |
| Mac 既存经理 run | `5b4feaf7ef7d4d13bec639e90b6d3db0` |
| 同 run 的计划产品 SHA | `56556a67ddc1a562e82b38e750be92fcfda070945397cc4eacffd1c79f42bcf0` |
| 原计划生成时间 | `2026-10-10T02:23:24.502381+00:00`，只读回看时间另报 |
| Mac 既有公告决定 | 392 = 2 event + 0 earnings + 26 observe + 270 not selected + 94 unknown；不是 392 只入选股票 |
| 原前端差异回执 SHA | `757fff2254cdb714946f6efdeb4675c86bbc97ea41f5df0556bd290348bd9804`，这是历史回执，不能替代本轮逐文件前像检查 |
| 本次业务行为 | 已存在的原 owner 结果 → 同 run 终态核验 → 新隔离 API generation → 普通页面 GET 消费 |
| 现役服务 | 保留 V4、BUY、Vibe 8910；候选端口和目录均由现场确认，61796 不能根据旧回执推定当前状态 |

Mac 回执来源为输入包 `START_HERE.md`，并非本轮复测。原 `managerWorkspace.currentRecovery.spec.ts` 固定校验该 run、SHA 和计划日 `20261009`。实际请求中的来源日、公告日和 owner binding 仍必须来自 Mac 原件，不能由该计划日反推出日期或文件路径。

本批通过要求：真实经理 GET 与已验证的同 run 计划/terminal 一致；公告股票、理由、来源、日期及未评估/资格限制可见；其他 lane 缺源不吞掉健康公告；所有非交易字段维持原值；生成按钮在只读服务、历史入口、首次失败和上下文不完整时不可用。原业务终态允许保留 `PARTIAL`；不能为了页面成功改成 `SUCCEEDED`，也不据此宣称三策略、自然接续或 18 模块完成。

## 2. 操作人必须填写的变量和现场证据

以下变量都是**真实绝对路径或现场确认值**。不能把示例路径、云端 `/workspace/...`、旧 PARTIAL/0 portable 数据代入 Mac 正式结果。使用独立 bash 会话，先启用 `set -euo pipefail`，每条命令记录 stdout、stderr、退出码、UTC 时间；失败证据不覆盖。

| 变量 | 含义与边界 |
|---|---|
| `V5_ORIGIN_REPO` | Mac 已核身份的 `lexi2016/v4` Git 仓库；只作对象来源，不在该工作树覆盖文件 |
| `V5_CANDIDATE_ROOT` | 尚不存在的隔离 checkout 目录；不得位于现役部署目录或 owner 数据根内 |
| `V5_DELIVERY_ROOT` | 已核材料提交/交付回执的本包目录，含 `before/`、`after/`、两个 patch、`SOURCE_MANIFEST.json`、`verify_preimage.py` 和 `PACKAGE_INDEX.json` |
| `V5_EVIDENCE_ROOT` | 本次全新的私有证据目录，保留失败和所有候选/旧 generation 回执 |
| `V5_VERIFY_PYTHON` | Mac 实际已安装 Python 3.14.6 的绝对可执行路径，用于隔离应用前的只读文件校验；候选业务环境随后仍由原 uv.lock 建立 |
| `V5_WEB_ROOT` | 完整、隔离的 web 工程目录；不能只是 V5 overlay，也不是现役 web 根 |
| `V5_WEB_SOURCE_COPY` | 仅采用“复制已核 Mac web”模式时填写：实际完整前端来源根 |
| `V5_MAC_OWNER_REQUEST` | Mac 实际 owner 请求 JSON 原件。含原 `inputs` 文件 SHA、原 `manager_output_root`、原公告 binding；不是历史响应 DTO |
| `V5_REAL_CURRENT_RECOVERY_RESPONSE` | 原 Mac `manager-read-publication.json` 类 envelope，含 `.result.payload`；真实回执测试专用 |
| `V5_PUBLICATION_ROOT` | 尚不存在的新私有 module publication 根，与原 owner 数据根、现役 API 根、旧 generation 隔离 |
| `V5_RELEASE_ID` | 现场为本次新 publication 记录的候选 release，关联代码 C；格式遵循 `[A-Za-z0-9][A-Za-z0-9_.-]{0,127}` |
| `V5_MANAGER_PORT`、`V5_ANNOUNCEMENT_PORT`、`V5_GATEWAY_PORT` | 三个不同的、现场核实空闲的 loopback 端口；不得默认抢占 61796、8910 或正常服务端口 |
| 现役预览身份和切换机制 | 原 URL、PID/启动时间、启动命令、配置/静态根与各 SHA、release、active generation、实际入口控制方式及精确回退操作；以现场观察填表 |

在变更前保存当前监听进程、旧 API GET/headers、旧普通页面和静态资源 SHA、旧 `active.json`/generation 回执及配置。端口权限错误不能证明进程停止。无需读凭据或导出全部公告正文；必要真实原件留在 Mac 私有证据目录。

## 3. 前像校验与隔离应用

### 3.1 两种源码应用模式：二选一

本包 `SOURCE_MANIFEST.json` 固定 `source_base_commit=F`、`code_commit=C`，共 **20 条路径**：7 个运行/配置文件、3 个既有测试更新、10 个新增测试/支持文件。每条有 `path`、`change`、`before`（新增时为 null）、`after`，身份字段含 SHA-256、Git blob SHA、字节数和 mode；`patches` 记录 `runtime.patch` 和 `reverse.patch` 的摘要。`verify_preimage.py` 默认读取与脚本同目录的该 manifest，检查包内 before/after、patch 摘要和目标 20 路径的指定 phase，失败即非零退出。

先按最终材料提交/交付回执核准本包身份，再核 `PACKAGE_INDEX.json` 所列交付文件 SHA。索引排除自身，不能作为自己真实性的独立证明；它用于检验已取得可信身份的交付材料。不要修改 manifest、包内 after 或校验器使未知前像通过。若包中同时提供 `RUNTIME_FILE_HASHES.csv`，它是便于人工查看的同一清单，机器 guard 以 `SOURCE_MANIFEST.json` 为准。

两种模式都先运行以下准备命令。`V5_CANDIDATE_ROOT` 与证据目录必须尚不存在；固定 F/C 对象缺失时只从已核 origin 取得准确对象，不切浮动分支：

```bash
set -euo pipefail
: "${V5_ORIGIN_REPO:?必填真实 Git 仓库}"
: "${V5_CANDIDATE_ROOT:?必填新的隔离 checkout}"
: "${V5_DELIVERY_ROOT:?必填已校验交付包}"
: "${V5_EVIDENCE_ROOT:?必填新的私有证据目录}"
: "${V5_VERIFY_PYTHON:?必填已安装 Python 3.14.6 绝对路径}"
V5_BASE_COMMIT=f7cb731c384ee6890a87d16c19a5b5a621779477
V5_CODE_COMMIT=6daed6271313b5ae5324c8948f163258ab8d1fa3
export V5_BASE_COMMIT V5_CODE_COMMIT V5_CANDIDATE_ROOT V5_DELIVERY_ROOT V5_EVIDENCE_ROOT

"$V5_VERIFY_PYTHON" -c 'import sys; assert sys.version_info[:3] == (3,14,6); print(sys.version)'
git -C "$V5_ORIGIN_REPO" remote -v
git -C "$V5_ORIGIN_REPO" cat-file -e "$V5_BASE_COMMIT^{commit}"
git -C "$V5_ORIGIN_REPO" cat-file -e "$V5_CODE_COMMIT^{commit}"
test ! -e "$V5_CANDIDATE_ROOT"
test ! -e "$V5_EVIDENCE_ROOT"
mkdir -m 700 "$V5_EVIDENCE_ROOT"
```

**模式 A：固定 F + 精确 patch。** 先在 F 新 checkout 上通过 before guard，才应用 patch；应用后通过 after guard。不覆盖 Mac 已有工作树。

```bash
git -C "$V5_ORIGIN_REPO" worktree add --detach "$V5_CANDIDATE_ROOT" "$V5_BASE_COMMIT"
test "$(git -C "$V5_CANDIDATE_ROOT" rev-parse HEAD)" = "$V5_BASE_COMMIT"
test -z "$(git -C "$V5_CANDIDATE_ROOT" status --porcelain)"
"$V5_VERIFY_PYTHON" -B "$V5_DELIVERY_ROOT/verify_preimage.py" \
  --repo-root "$V5_CANDIDATE_ROOT" --phase before \
  > "$V5_EVIDENCE_ROOT/preimage-before.stdout.json" \
  2> "$V5_EVIDENCE_ROOT/preimage-before.stderr.log"
git -C "$V5_CANDIDATE_ROOT" apply --check "$V5_DELIVERY_ROOT/runtime.patch"
git -C "$V5_CANDIDATE_ROOT" apply "$V5_DELIVERY_ROOT/runtime.patch"
git -C "$V5_CANDIDATE_ROOT" diff --check
"$V5_VERIFY_PYTHON" -B "$V5_DELIVERY_ROOT/verify_preimage.py" \
  --repo-root "$V5_CANDIDATE_ROOT" --phase after \
  > "$V5_EVIDENCE_ROOT/preimage-after.stdout.json" \
  2> "$V5_EVIDENCE_ROOT/preimage-after.stderr.log"
git -C "$V5_CANDIDATE_ROOT" apply --check "$V5_DELIVERY_ROOT/reverse.patch"
```

`before` 检查修改路径的 SHA-256、字节数、Git blob SHA 与 F 交付前像一致，且新增路径不存在；`after` 要求全部 20 条候选路径匹配 C 交付字节。manifest 另记录 Git mode，按固定 checkout 的 Git 树核对；此校验器不单独检查文件执行位，不能把其 PASS 解释为执行位检查结果。`reverse.patch --check` 仅证明此刻可逆，不执行回退。任何前像不符，保留实际 SHA、路径和日志并停止；不得跳过 guard、强行三方合并、替换整份 V4 workspace 或修改 vendor manifest 迁就前像。

**模式 B：直接固定 C checkout。** 本模式无需再 apply runtime.patch，否则会重复叠加。材料根 `V5_DELIVERY_ROOT` 仍来自已核交付材料，源码根则严格取 C：

```bash
git -C "$V5_ORIGIN_REPO" worktree add --detach "$V5_CANDIDATE_ROOT" "$V5_CODE_COMMIT"
test "$(git -C "$V5_CANDIDATE_ROOT" rev-parse HEAD)" = "$V5_CODE_COMMIT"
test -z "$(git -C "$V5_CANDIDATE_ROOT" status --porcelain)"
"$V5_VERIFY_PYTHON" -B "$V5_DELIVERY_ROOT/verify_preimage.py" \
  --repo-root "$V5_CANDIDATE_ROOT" --phase after \
  > "$V5_EVIDENCE_ROOT/preimage-after.stdout.json" \
  2> "$V5_EVIDENCE_ROOT/preimage-after.stderr.log"
git -C "$V5_CANDIDATE_ROOT" apply --check "$V5_DELIVERY_ROOT/reverse.patch"
```

两种模式所得 20 条路径的 after 身份应一致；完整其余源码继续来自固定 F/C 的 Git 对象，不从旧 V4 donor 整包覆盖。材料提交 H 不作为第二种业务源码 authority。

### 3.2 原解释器和锁文件

`V5/pyproject.toml` 要求 Python `>=3.14`，本次固定验证环境为 **Python 3.14.6 + 原 `V5/uv.lock`**。候选中执行：

```bash
cd "$V5_CANDIDATE_ROOT/V5"
uv sync --frozen --python 3.14.6
.venv/bin/python -c 'import sys; assert sys.version_info[:3] == (3,14,6); print(sys.version)'
git diff --exit-code -- pyproject.toml uv.lock
export V5_PYTHON="$V5_CANDIDATE_ROOT/V5/.venv/bin/python"
export PYTHONPATH="$V5_CANDIDATE_ROOT/V5/src"
export PYTHONDONTWRITEBYTECODE=1
```

保留 uv 日志、解释器路径、版本及锁文件 SHA。缺依赖/解释器按真实失败处理；不能换较低 Python、删 import、mock owner 或安装一个替代协议实现来补绿。安装只在候选环境内进行，不改 Mac 正常服务的环境。

## 4. 完整前端与 overlay guard

实际入口是 `V5/ui/manager-workbench/apply_candidate.py --web-root`；它要求候选根标记 `.v5-ui-candidate` **准确为** `v5.ui-candidate.v1\n`。它先校验 manifest 的全部 `unchanged` 依赖，逐项校验 overlay `after_sha256`，目标只接受 `before_sha256`、`after_sha256` 或显式 `previous_candidate_sha256`；拒绝目标软链接/越界路径。全部前置核验通过才替换，替换后再次验 SHA。标记不是绕过前像的许可证。

两种模式二选一：

1. **Mac 原完整 web 的隔离副本**：先由操作人确认 `V5_WEB_SOURCE_COPY`、完整依赖和原前像；`V5_WEB_ROOT` 必须尚不存在。将它复制到新目录后，确认该目录不是现役源/静态根，才写上述标记并运行 overlay。不在现役目录新增标记。
2. **固定 Git 对象重建**：使用现有 `V5/tools/cloud_preview/assemble_web.py --out "$V5_WEB_ROOT"`，输出必须不存在。该脚本会创建标记、执行 overlay、补两个 HTML 挂载入口和 provenance，不执行依赖安装、测试或 build。需要以下**精确** Git 对象在候选仓库可读取：

| 对象 | 用途 |
|---|---|
| `164c010c7eaa1659db9bfed0ff5f123c7a39eefc` | 原 canonical web |
| `8342862f05ca9f6516f51b3164b6110651e5af77` | 原工作台 UI 和 Mac completion 源 |
| `7d2b71a91ad4d54f85fe03f5973248af686d7a87` | 四项原 TS 依赖 |

若对象缺失，只从已确认 origin 获取这些固定对象；不得改 `assemble_web.py` 的 ref 或拿浮动最新版拼接。脚本内部调用 `python3 apply_candidate.py`，执行前记录 `python3` 身份；此 overlay 工具只处理文件和 SHA，业务运行/测试仍用上节的 3.14.6。

复制模式的实际 overlay 命令：

```bash
"$V5_PYTHON" -B "$V5_CANDIDATE_ROOT/V5/ui/manager-workbench/apply_candidate.py" \
  --web-root "$V5_WEB_ROOT"
```

Git 对象重建模式的实际命令：

```bash
"$V5_PYTHON" -B "$V5_CANDIDATE_ROOT/V5/tools/cloud_preview/assemble_web.py" \
  --out "$V5_WEB_ROOT"
```

记录 `overlay-manifest.json`、overlay 输出、完整 `package.json`/`package-lock.json` SHA。**本轮实际验证的前端环境是 Node v24.19.0 / npm 11.9.0**；Mac 使用相同版本，并记录可执行路径和版本，不把云端版本验证当作 Mac 已验。只在新 web 根执行 `npm ci`；锁文件不得更新。实际 scripts 为 `test=vitest run`、`typecheck=vue-tsc --noEmit`、`build=vite build`。

源树完整组装、overlay guard 通过后，导出 Python UI 安装测试需要的准确原依赖目录：

```bash
export V5_MODULE01_WEB_ROOT="$V5_WEB_ROOT"
node --version
npm --version
test "$(node --version)" = v24.19.0
test "$(npm --version)" = 11.9.0
```

`test_module01_ui_overlay.py` 从该根取得三项 pinned unchanged 依赖，在临时目录运行原安装器；没有此变量会 skip，汇总必须标 `NOT_RUN`，不能计为已通过。

## 5. 必要回归：真实与合成输入保持独立

### 5.1 Python 定向合同

从候选 `V5/` 运行标准 unittest，完整保留每组日志。以下均不要求 Mac 原 392 正文：

```bash
cd "$V5_CANDIDATE_ROOT/V5"
"$V5_PYTHON" -B -m unittest discover -s tests -p 'test_module01_*.py' -v
"$V5_PYTHON" -B -m unittest discover -s tests -p 'test_manager_response_budget.py' -v
"$V5_PYTHON" -B -m unittest discover -s tests -p 'test_manager_current_recovery.py' -v
"$V5_PYTHON" -B -m unittest discover -s tests -p 'test_announcement_analysis_api.py' -v
"$V5_PYTHON" -B -m unittest discover -s tests -p 'test_module_artifacts.py' -v
"$V5_PYTHON" -B -m unittest discover -s tests -p 'test_module_api.py' -v
"$V5_PYTHON" -B -m unittest discover -s tests -p 'test_api_gateway.py' -v
```

覆盖的本批风险是 exact run/latest 交错、缺失或借用另一 run terminal、公告原来源篡改、健康公告与缺源 lane 并存、expected-run 预发布 guard、只读 HTTP 头、响应容量边界及 generation CAS。测试所建合成 owner 数据位于独立临时根，不能作为 Mac 原件的替代。

### 5.2 Web 合同、真实原件及 build

```bash
cd "$V5_WEB_ROOT"
npm ci
npm run test -- \
  src/api/managerWorkspace.module01.spec.ts \
  src/manager-selection/catalystObservationPanel.module01.spec.ts \
  src/manager-selection/dailyChannels.v5Bindings.spec.ts \
  src/manager-selection/catalystViewNavigation.spec.ts
V5_REAL_CURRENT_RECOVERY_RESPONSE="$V5_REAL_CURRENT_RECOVERY_RESPONSE" \
  npm run test -- src/api/managerWorkspace.currentRecovery.spec.ts
npm run typecheck
npm run build
```

原 `managerWorkspace.currentRecovery.spec.ts` 必须绑定 Mac 原 envelope（`.result.payload`），完整跑原三项测试，不修改原件、不把合成响应写进该文件。`V5_ANNOUNCEMENT_REVIEW_FIXTURES` 等其他原 fixture 若执行相关 suite 就绑定实际原件；缺少的项如实标 `NOT_RUN` 或原始失败，不能用空 JSON/跳过断言补绿。

`managerWorkspace.module01.http.spec.ts` 专门要求 `V5_MODULE01_HTTP_RECEIPT`，其生成器 `V5/tests/module01_export_http.py` 只接受明确标识的 **4 决定合成 owner fixture**；可引用交付包该项已运行的证据，若在 Mac 重跑则仍使用独立合成根。未绑定时该 suite 自身 skip，汇总必须写 `NOT_RUN`，不能计为通过；不得把真实 392 响应塞入该 synthetic 合同。

**不要把真实 Mac response 绑定给 `cloudActualReadback.spec.ts`。** 它固定 `20261012` 并断言没有 `[data-daily-symbol]`，服务于旧空云端样本；不是健康公告的 Mac 验收。真实完整 DTO 经 gateway 与前端请求/validator 的验收由下节实际 GET 和内置浏览器完成。

若完整 `npm run typecheck`/工程测试失败，保留原日志和来源归因。本次存在的 `tsconfig.cloud-product.json` 仅为重建模式额外产物；`vue-tsc --noEmit -p tsconfig.cloud-product.json` 可作为补充产品源码检查，不能替代完整 typecheck 或抹去其失败。build 成功也不替代真实 owner/API/浏览器验收。

## 6. 复用真实 run：先只读核验，再发布到新根

### 6.1 从原请求生成本次只读请求

读取实际 `V5_MAC_OWNER_REQUEST` 原件，在新证据目录创建 `auto-read-request.json`。仅将 `action` 改为 `read`、`view` 改为 `auto`、`now` 改为**实际本次 UTC 时间**。其余字段（target/selection/announcement 日期、inputs 全部 SHA、原 owner binding、原 manager 输出根、可选 owner）原样保留。

```bash
export V5_MAC_OWNER_REQUEST
"$V5_PYTHON" -B - <<'PY'
import json, os
from datetime import datetime, timezone
from pathlib import Path
src = Path(os.environ['V5_MAC_OWNER_REQUEST'])
request = json.loads(src.read_bytes())
request.update(action='read', view='auto', now=datetime.now(timezone.utc).isoformat())
out = Path(os.environ['V5_EVIDENCE_ROOT']) / 'auto-read-request.json'
with out.open('x', encoding='utf-8') as stream:
    json.dump(request, stream, ensure_ascii=False, indent=2)
PY
```

**不可新增 operation_id、新建 manager store、修改原 latest，或改成 refresh。** `manager_plan._request` 不接受任意额外字段。已有 marker/owner 路径失败应作为合同差异回传，不能现场造 marker 修补原 owner。

现有 `auto` 在已存在的 `current_recovery` 保存范围内按原规则选择；`--expected-run` 是**拒错 guard，不是选择任意旧 run 的参数**。若 `auto` 选到另一 run，应停止，记录实际 run、SHA、store 和 latest 观察，回传精确差异。不得移动 latest、把旧 run 复制到新 store 或刷新来凑正确值。

### 6.2 独立保留原 owner 完整读回 envelope

以下调用只读原业务数据，将结果写入新的本次证据文件；独立记录 exact product/terminal 与 latest 观察。成功后仍需下一节实际 HTTP 验证。

```bash
"$V5_PYTHON" -B - <<'PY'
import json, os
from pathlib import Path
from v5_shadow.manager_plan import run_manager_plan
root = Path(os.environ['V5_EVIDENCE_ROOT'])
request = json.loads((root/'auto-read-request.json').read_bytes())
result = run_manager_plan(request)
with (root/'mac-owner-read-result.json').open('x', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
p = result['payload']; product = p['plan_product']; terminal = p['workspace_plan_attempt']
expected_run = '5b4feaf7ef7d4d13bec639e90b6d3db0'
expected_sha = '56556a67ddc1a562e82b38e750be92fcfda070945397cc4eacffd1c79f42bcf0'
assert product['run_id'] == expected_run and product['sha256'] == expected_sha
assert product['consumed'] is True
assert terminal['run_id'] == expected_run
assert terminal['state'] in {'SUCCEEDED', 'SUCCEEDED_EMPTY', 'PARTIAL'}
assert terminal['target_trade_date'] == p['target_trade_date'] == request['target_date']
assert terminal['input_identity'] == p['input_identity']
assert result['readback']['run_id'] == expected_run
assert result['readback']['plan_sha256'] == expected_sha
assert result['readback']['attempt'] == terminal
assert product['generated_at'] == '2026-10-10T02:23:24.502381+00:00'
assert product['historical_eligible'] is False
for key in ('production_allowed', 'buy_gate_updated', 'orders_sent'):
    assert result[key] is False and p[key] is False and terminal[key] is False
assert result['natural_verified'] is False
print(json.dumps({'run_id': expected_run, 'plan_sha256': expected_sha,
    'terminal_state': terminal['state'], 'store_relative': result['readback']['store_relative'],
    'latest_observation': result['readback'].get('latest_observation')}, ensure_ascii=False))
PY
```

脚本先保留实际读回再断言，因此不一致也有原响应。`latest_observation` 不等于本 run、MISSING 或 CANNOT_CONFIRM 不能被当作本 run 失败；本 run 本身必须具备准确产品、input identity 和原 `verified_plan_attempt` 验证的 terminal。不要比较两个“全响应 JSON SHA”来代替计划产品 SHA：新读取的观察时间可变，计划产品 SHA 必须不变。

### 6.3 新根发布

完成 owner 验证、前端 build 后，使用真实存在的发布入口：

```bash
: "${V5_PUBLICATION_ROOT:?必填尚不存在的隔离 publication 根}"
: "${V5_RELEASE_ID:?必填最终候选 release}"
"$V5_PYTHON" -B "$V5_CANDIDATE_ROOT/V5/tools/cloud_preview/publish_read.py" \
  --request "$V5_EVIDENCE_ROOT/auto-read-request.json" \
  --expected-run 5b4feaf7ef7d4d13bec639e90b6d3db0 \
  --out "$V5_PUBLICATION_ROOT" \
  --frontend-root "$V5_WEB_ROOT/dist" \
  --release-id "$V5_RELEASE_ID" \
  > "$V5_EVIDENCE_ROOT/manager-publish.stdout.json" \
  2> "$V5_EVIDENCE_ROOT/manager-publish.stderr.log"
```

脚本要求新根且 `action=read,view=auto`，只读原 owner；它通过 `publish_workspace_read(..., expected_generation=None, expected_run_id=...)` 在生成 records 前验证 run、consumed 和同 run 成功类 terminal，再发布 immutable generation。该操作会写**新的 API 输出存储**，不会刷新/采集业务源。

输出真实文件为 `manager.json`、`announcement.json`、`gateway.json`、`frontend.json`、`publication.json` 及各 module 数据目录；stdout 仅含 publication 和 plan_product，**不是 `.result.payload` 原 envelope**。以本次 `mac-owner-read-result.json` 或原 Mac envelope 验证完整 DTO，不能把 publisher stdout 冒充原回执。

发布后检查 stdout 和 `publication.json` 的 generation、release、`previous_generation=null`，再次检查固定 run/SHA 和原生成时间。`publish_read.py` 若中途失败会保留它已经创建的新根；不要删除根后假装第一次成功，也不能对同一目录重跑。保留失败目录和日志，修正明确原因后选择另一个新隔离根。

## 7. 独立公告分析路由：按真实 binding 发布，不能假造空结果

**已核实的实际行为：** `publish_read.py` 只给 manager 生成 record。announcement 只有 marker 和配置，三个配置路由初始均无产品，因此 GET 应为 `503 MODULE_RESULT_NOT_AVAILABLE`。经理 `daily_channels.ANNOUNCEMENT` 已随完整 workspace 发布，独立分析面板则需要自己的原公告响应。

如验收要求独立分析面板显示该原产品，且 `auto-read-request.json` 包含非空、已通过原 reader 的 `announcement_offline_owner`，可用现有 `announcement_analysis_api.publish_analysis` / CLI。先原样抽出 binding；保留所有实际字段，包括存在时的 revision 身份，不能按 CLI help 的“四字段”文字删掉扩展身份：

```bash
"$V5_PYTHON" -B - <<'PY'
import json, os
from pathlib import Path
root = Path(os.environ['V5_EVIDENCE_ROOT'])
request = json.loads((root/'auto-read-request.json').read_bytes())
binding = request.get('announcement_offline_owner')
assert isinstance(binding, dict) and binding
with (root/'announcement-binding.json').open('x', encoding='utf-8') as f:
    json.dump(binding, f, ensure_ascii=False, indent=2)
PY
"$V5_PYTHON" -B -m v5_shadow.announcement_analysis_api \
  --binding "$V5_EVIDENCE_ROOT/announcement-binding.json" \
  --config "$V5_PUBLICATION_ROOT/announcement.json" \
  --expected-generation null \
  > "$V5_EVIDENCE_ROOT/announcement-publish.stdout.json" \
  2> "$V5_EVIDENCE_ROOT/announcement-publish.stderr.log"
```

`null` 仅适用于本次全新、尚未发布的 announcement 根。若该 module 已有 generation，必须从其原 `active.json` 核对实际 SHA，并作为 `--expected-generation <准确 SHA>`；发生 `GENERATION_CONFLICT` 停止并保留，不把 latest 覆盖过去。

实际合同如下：

| 查询 | 发布条件和含义 |
|---|---|
| `/api/v4/manager/research/announcements/analysis?date=<binding.target_date>&publication_date=<原 ISO 日>` | 原 explicit reader 的响应，`date_selection_basis=EXPLICIT` |
| 同 route、compact `publication_date=YYYYMMDD` | 同 explicit 响应，独立 exact query key |
| 同 route、仅 `date=<binding.target_date>` | 单独调用原 `read_owner(..., default_analysis=True)`，`date_selection_basis=PREVIOUS_HK_TRADING_SESSION` |
| `/api/v4/manager/research/announcements`、`/selection` | 此 publisher **不生成**这些记录；若无其他已验原发布产品，继续诚实返回 503 |

`publish_analysis` 在相同当前 cutoff 先读 explicit，再读真实 calendar default；只有两者都是 VERIFIED、目标/公告日/日期选择依据正确且产品 SHA 一致时才整体发布。若 default 对应另一日期/产品，报 `ANNOUNCEMENT_API_READ_PAIR_CHANGED` 或日期/验证错误，不能通过改标签、伪造 default、调用旧 build-reviewed CLI 或重导公告来绕过。这种缺口影响独立分析路由，须精确回传；不能把经理已有健康公告也描述为全部失效。

独立公告 `analysis.product_sha256` 是**公告产品 SHA**，不是上节经理计划 SHA。以原 binding/reader 和经理 `announcement_reviewed_analysis.products` 的被消费产品核对两者关系，并按真实原分类校验 392 决定。不要求 announcement evidence run 等于 manager run，它们属于不同 owner。

本批没有 HTTP writer。不要发明 `/publish`、把 GET 改 POST，或用 refresh endpoint 代替 CLI 发布。独立公告列表/selection 未发布时，真实页面必须保留明确缺口，不能称全部公告页面已通过。

## 8. 候选启动：普通静态服务与真实 GET

### 8.1 配置和端口

`publish_read.py` 固定写出的 upstream 端口是 manager `18897`、announcement `18898`。这不是现场端口授权。若这些端口不可用，**只改本次新生成的 `gateway.json` 中两个 port 数字**为操作人已确认的变量；module 的实际 `--port` 必须相同。修改后调用 `api_gateway.validate_config`、保存配置 SHA。gateway 监听端口由 `--port` 指定，无需写进 gateway config。不得把路由 methods 改成包含 POST。

```bash
export V5_PUBLICATION_ROOT V5_MANAGER_PORT V5_ANNOUNCEMENT_PORT V5_GATEWAY_PORT
"$V5_PYTHON" -B - <<'PY'
import json, os
from pathlib import Path
from v5_shadow.api_gateway import validate_config
p = Path(os.environ['V5_PUBLICATION_ROOT'])/'gateway.json'
v = json.loads(p.read_bytes())
ports = [int(os.environ[k]) for k in ('V5_MANAGER_PORT','V5_ANNOUNCEMENT_PORT','V5_GATEWAY_PORT')]
assert len(set(ports)) == 3 and all(1 <= n <= 65535 for n in ports)
v['modules']['manager']['port'] = ports[0]
v['modules']['announcement']['port'] = ports[1]
assert all(row['methods'] == ['GET'] for row in v['routes'])
validate_config(v)
p.write_text(json.dumps(v, indent=2)+'\n', encoding='utf-8')
PY
```

这个配置检查不证明端口空闲，需现场另查。保留修改前后 `gateway.json` 与 SHA；修改仅发生在新候选发布根。

三个命令分别在可记录 PID、启动时间和 stdout/stderr 的独立进程窗口执行。下面是后续 Mac 操作合同，本会话未执行：

```bash
"$V5_PYTHON" -B -m v5_shadow.module_api \
  --config "$V5_PUBLICATION_ROOT/manager.json" --port "$V5_MANAGER_PORT"
```

```bash
"$V5_PYTHON" -B -m v5_shadow.module_api \
  --config "$V5_PUBLICATION_ROOT/announcement.json" --port "$V5_ANNOUNCEMENT_PORT"
```

```bash
"$V5_PYTHON" -B -m v5_shadow.api_gateway \
  --config "$V5_PUBLICATION_ROOT/gateway.json" --port "$V5_GATEWAY_PORT" \
  --frontend-root "$V5_WEB_ROOT/dist" \
  --frontend-manifest "$V5_PUBLICATION_ROOT/frontend.json"
```

实际代码没有 `serve_preview.py`；`run_shadow.py` 也不是此 gateway 启动器。三个服务仅绑定 `127.0.0.1`。gateway 启动时校验所有静态字节并载入内存，不是开发服务器、不自动跟随 rebuild；重建后须生成匹配的新 manifest、重新记录配置身份并仅重启本次候选 gateway。

### 8.2 GET 与只读证据

不要用 `curl -I` 验 module：module 的 HEAD 是只读拒绝路径。使用 GET 并保存 headers/body/状态：

```bash
curl --silent --show-error --max-time 20 \
  -D "$V5_EVIDENCE_ROOT/manager-health.headers" \
  -o "$V5_EVIDENCE_ROOT/manager-health.json" \
  "http://127.0.0.1:${V5_MANAGER_PORT}/__v5/module-health"
curl --silent --show-error --max-time 20 \
  -D "$V5_EVIDENCE_ROOT/gateway-health.headers" \
  -o "$V5_EVIDENCE_ROOT/gateway-health.json" \
  "http://127.0.0.1:${V5_GATEWAY_PORT}/__v5/health"
```

module health 记录 PID、implementation/config SHA、release；`source_provenance_verified=false` 是既有协议，不能因进程正常改成 true。gateway health 为 `GATEWAY_ONLY`、上游 `NOT_PROBED`，所以 health 200 不是业务通过。

经理查询必须**逐字段来自 `auto-read-request.json`**：`date=target_date&view=auto`，只在该请求非 null 时附上 `selection_date`/`announcement_date`。发布 records 按完整 query 精确寻址。额外加 run、无依据的日期、`view=dynamic` 或历史参数不会自动选相同记录；未发布 query 应返回 503。

分别请求直连 module 和 gateway 的同一 workspace query，保存完整字节、SHA、HTTP status、headers。业务必须为 HTTP 200，payload 的 run、固定计划 SHA、生成时间、consumed、同 run terminal、input_identity、date bindings 与第 6 节一致；以完整 frontend validator 成功为准。直连 module 和 gateway 返回的 body 字节应相同。业务 GET 前后对原业务产品/terminal/inputs 和新 module root 做文件清单+SHA 比对，证明 GET 未写入或创建新 run；证据目录不纳入只读源比对。

直连 manager 200/错误响应含 `X-V5-Workspace-Access: READ_ONLY`；gateway 在成功转发 GET-only workspace 路由时也给此 header。gateway 自己生成的网络/上游错误未必有此 header，因此首次 GET 失败时必须靠 UI 的完整成功读取门槛保持生成禁用，不能推定“没 header 就可写”。gateway 不透传 `X-V5-Record-SHA256`/module health 头，record SHA 取直连 module；不可误判为 gateway 缺字段。

`CURRENT_RECOVERY` 必须保留 `requested_view=auto`、`owner_view=dynamic`、实际 `read_as_of`、`historical_eligible=false`；不把后续读取时间写成原盘前生成。保留最新指针观察的真实结果，不靠 latest 是否相等决定同 run 验收。

独立分析发布成功时另 GET 第 7 节 explicit/default exact query，验证公告产品 SHA 和 basis；未发布列表/selection 保存实际 503及错误体。坏 origin、越界路径和拒写行为由本轮定向测试覆盖，不在现役 owner 进行破坏性试验。

## 9. 普通静态资源与内置浏览器验收

先 GET `http://127.0.0.1:<候选 gateway port>/manager-selection/`，必须返回实际 HTML，`X-V5-Frontend: V4-REUSED`、正确 MIME；按 HTML 引用逐一读取 JS/CSS 等，保存每个资源 URL、HTTP 状态和 SHA，与 `frontend.json` 对上。此 gateway 无 SPA 万能 fallback：使用 manifest 内存在的 `/manager-selection/` 或准确 `.html` 路径，不能用不存在路径的 404 误判业务。

在用户指定的 Mac 内置浏览器打开该**真实候选**普通页面，进入原 `20261009` 计划日，默认 auto；URL 中 selection/publication 绑定只按第 6 节实际请求提供。保存截图、页面 URL、console 和 network，以及同一时点 GET 文件。

| 场景 | 验收要求 |
|---|---|
| 第一次正确普通 GET | `READY`、固定 manager run/计划 SHA 和同 run terminal；股票、原理由、来源引用、日期、缺口及资格限制与实际 DTO 对应 |
| 392 分类 | 以原 owner 决定数组/分类计数核 2/0/26/270/94 和总数 392；daily channel 的 candidate/watch/pending 根据原股票投影核，不能将决定总数当候选股数、把 NOT_SELECTED 当入选或 UNKNOWN 当零 |
| 公告健康、US/HK_CONNECT/OVERSOLD 缺源 | 公告已有股票继续显示；其他 lane 保留 UNKNOWN/CANNOT_CONFIRM、真实原因和 nullable 数量，不清空全部公告 |
| 独立分析 | 若已发布，应完整 validator 通过且显示相同公告产品；若仍 503，明确记录局部缺口，不用经理列表冒充独立分析通过 |
| 只读生成 | “用既有材料生成计划”按钮禁用；普通读、重读、切日、切 view、取消及失败均不得引发 POST。不能点击“公告增量更新”尝试补源 |
| 历史入口和缺 read_context | 不开放生成；未发布历史响应可诚实 503，不借 auto 当前回看冒充历史 |
| 首次 GET 失败 | 显示真实待就绪/错误；生成仍禁用，旧结果不伪装当前成功 |
| 切日/切 view/取消/迟到响应 | 旧请求响应不能覆盖当前选择。实际取消不表示后台 owner 已失败；此只读服务不产生新 run |
| 返回正确 auto | 重新取得已发布同 run，无自动 refresh、自动重试 POST 或无条件二次 GET 混入另一个 run |
| 非交易与时点 | `production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`；不声称自然运行、盘前时点或完整三策略已验收 |

浏览器记录必须来自真实普通 HTML/JS 和真实 API，不是 jsdom、JSON 直出页或诊断页。测试失败、缺原件、未发布 query、未测功能逐项写实际状态。前端现有公告增量更新属于独立既有入口，此候选 gateway 未配置该 writer；验收不触发它，不据“计划生成按钮禁用”宣称所有原 UI 更新按钮都已改造。

## 10. 单窗口切换与精确回退

### 10.1 切换合同

所有业务/API/资源/内置浏览器门槛通过后才安排一个明确的 V5 预览切换窗口。**具体切换设施/路径在输入中未给出，因此本说明不提供猜测性的 `cp dist`、kill、端口接管或 symlink 覆盖命令。** 操作人应把第 2 节现场已确认的以下元组写进最终操作单：

- 旧入口 → 旧进程/启动时间 → 旧配置/静态 SHA → 旧 module release + active generations；
- 候选入口 → 本次三个候选进程 → 候选配置/静态 SHA → 本次 module release + active generations；
- 实际切换原语、准确的前像 guard、准确的逆向原语、执行者与时间。

切换前重新观察旧入口身份；若与记录不同，停止切换并保留差异。单窗口只切 V5 预览入口到**已经验过的整套配置、generation 和静态资源**，不同时改原 owner 输出、V4、BUY 或 8910。不关闭正常旧服务来试探是否候选可用。切后立即重做固定 run GET、静态 SHA和内置浏览器核心验收；保留旧进程/根以供回退，若现场设施不支持共存则先提供该设施的精确逆操作，不能猜 PID。

### 10.2 两类回退不能混用

**A. 本文默认的新 publication 根/新 release：** 回退是按现场记录切回旧预览入口、旧配置和旧静态资源。保留失败候选根、objects、generations、active、进程日志及浏览器证据，不覆盖或删除旧 generation。新根的 `previous_generation` 是 null，不存在可 `activate_generation(None)` 的“空 generation 回退”。不要把旧 release 的 generation 塞进新 release 根。

**B. 同一个 module 根、同一个 release 内已有旧 generation：** 仅在实际使用同根 generation 激活机制时，调用现有 `module_artifacts.activate_generation(config, old_generation, expected_generation=current_generation)`。旧 generation 及其 objects 必须真实存在且校验通过；它会在 publication lock 内做 CAS、完整校验引用后原子替换 active。示例合同如下，变量均须来自切换前后保存的真实回执：

```bash
export V5_ROLLBACK_CONFIG V5_ROLLBACK_OLD_GENERATION V5_ROLLBACK_EXPECTED_CURRENT
"$V5_PYTHON" -B - <<'PY'
import json, os
from pathlib import Path
from v5_shadow.module_artifacts import activate_generation
config = json.loads(Path(os.environ['V5_ROLLBACK_CONFIG']).read_bytes())
result = activate_generation(config, os.environ['V5_ROLLBACK_OLD_GENERATION'],
    expected_generation=os.environ['V5_ROLLBACK_EXPECTED_CURRENT'])
print(json.dumps(result, sort_keys=True))
PY
```

若当前 head 已改变，`GENERATION_CONFLICT` 是停止信号，不能再次读取后无条件覆盖；先查明谁推进了 generation，保留全部证据。不要手工编辑/删除 `active.json`、`.v5-generation-mode` 或 lock。缺 active 的显式恢复是另一个已有合同，只能持有准确完整 generation 时处理，不能在本次回退里猜测。

代码回退只在退出服务的隔离候选 checkout、其字节仍等于本包 after 时进行。先用本包 `verify_preimage.py --repo-root "$V5_CANDIDATE_ROOT" --phase after` 核验，再 `git -C "$V5_CANDIDATE_ROOT" apply --check "$V5_DELIVERY_ROOT/reverse.patch"` 与 `git -C "$V5_CANDIDATE_ROOT" apply "$V5_DELIVERY_ROOT/reverse.patch"`；之后运行同一校验器的 `--phase before`，核回原字节及新增路径已移除。更稳妥的现场回退是恢复已保存的旧整套候选入口；不能把业务数据 SHA 回写成旧值，不能重跑旧 historical runner 构造 run。

## 11. 交回的证据与准确停止条件

操作人回执包含：固定代码/包身份和实际 Mac 前像、逐文件 SHA、解释器/锁文件、overlay stdout 和静态 manifest、每项测试的原日志/退出码、原请求 SHA、本次只读请求与完整 owner readback、exact product/terminal/latest 观察、publication 回执与所有 active/generation SHA、真实 module/gateway headers/body、普通静态资源 SHA、内置浏览器截图/console/network、旧/候选进程和配置身份、实际切换/回退的时间和结果。

下列情况保留失败并回传精确合同，不扩大第一批：前像或 source pin 不符、原 run/SHA/terminal 不符、原公告 readback/receipt/body hash 不符、default/explicit 公告产品不一致、完整 DTO validator 失败、真实 392 计数不符、旧结果覆盖当前选择、只读入口开放生成、generation CAS 冲突或资源 SHA 不符。不要重采/重导392、修改原正文、调整策略阈值或关闭安全字段来通过。

`COMPLETE_EMPTY`、旧 US receipt 兼容、d659ff0 的旧 runner/CLI 修复和正式 rebound Decimal 80% 准入仍各自独立；本批成功不代表这些实现已等效或已落地。历史 runner 与 current-live workspace_plan 不混成一个运行前像。

## 12. 编写依据（实际函数与文件）

| 文件 | 本说明所用合同 |
|---|---|
| `SOURCE_MANIFEST.json` / `verify_preimage.py` / `PACKAGE_INDEX.json` | 固定 F/C、20 路径 before/after 与 patch 摘要、材料清单 SHA |
| 输入 `START_HERE.md` / `PROMPT_FOR_CHAT.md` | 固定 F、Mac 历史 run/SHA/分类数、第一模块范围、NOT_RUN 边界 |
| `V5/tools/cloud_preview/publish_read.py::main` | 新 publication 根、auto/read、expected-run、manager 单路发布、空公告根、真实配置名和默认 upstream 端口 |
| `V5/src/v5_shadow/manager_plan.py::_request/_plan_store_scope/_assemble/publish_workspace_read` | 原输入 binding、same run 产品/terminal、latest 独立观察、current recovery、只读发布 guard |
| `V5/src/v5_shadow/announcement_offline_reader.py::read_owner` | 原 manifest/owner/receipt/产品读回验证、explicit/default reader |
| `V5/src/v5_shadow/announcement_analysis_api.py::response_record/publish_analysis/main` | explicit/default 精确 query、两次原读取同 SHA、CAS CLI、仅 analysis route |
| `V5/src/v5_shadow/module_api.py::create_module_server/main/_generation_head` | GET-only module、只读 header、health、exact query、active 身份 |
| `V5/src/v5_shadow/api_gateway.py::validate_config/load_frontend/create_gateway/main` | loopback、GET 配置、静态 manifest、只读 header 来源、真实启动 CLI |
| `V5/src/v5_shadow/module_artifacts.py::publish_generation/activate_generation/_compare/_activate` | immutable 存储、CAS、同 module/release 验证、保留旧 generation |
| `V5/ui/manager-workbench/apply_candidate.py::main` 与 `overlay-manifest.json` | marker、全部前像/依赖 hash guard、after 读回 |
| `V5/tools/cloud_preview/assemble_web.py::main` | 三个固定 Git 对象、overlay、HTML 入口、source provenance；未执行 build |
| `V5/ui/manager-workbench/source/apps/web/src/api/managerWorkspace.ts` | 完整 DTO validator、read-only header admission、日期/POST 终态合同 |
| `V5/ui/manager-workbench/source/apps/web/src/manager-selection/catalystObservationPanel.ts` | 普通读、生成门槛、迟到响应/取消、只读页面行为 |
| `V5/tools/cloud_preview/cloudActualReadback.spec.ts` | 旧 20261012 空云端样本的固定断言，不能冒充真实 392 验收 |
| `V5/ui/manager-workbench/source/apps/web/src/api/managerWorkspace.currentRecovery.spec.ts` | 原 Mac run/SHA/20261009 的真实 fixture 合同 |

本文件是代码 C 的后续 Mac 操作说明。Mac 原件、真实 GET、浏览器、切换和回退本轮全部为 **NOT_RUN**；代码/交付材料已固化不改变这些现场验收状态。
