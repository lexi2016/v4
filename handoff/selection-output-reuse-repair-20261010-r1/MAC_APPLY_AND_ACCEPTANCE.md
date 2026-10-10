# Mac 候选应用、回滚与真实验收

## 当前状态和应用目标

本会话未连接 Mac、部署 release、修改 launch 配置、启停服务或执行真实选股。下面是可复核的本机操作步骤，执行前必须从现有配置确认实际源码根、解释器、owner 数据根和服务入口。固定 GitHub 基线与文件 SHA 是本包的代码身份；`CURRENT` 链接或目录名本身不能证明进程实际加载这些字节。

**先在独立完整候选中应用与测试。** 将变量设置为实际绝对路径：

```bash
V4_REPAIR_PACKAGE='/absolute/path/V4_SELECTION_REUSE_REPAIR_20261010_R1'
V4_PATCH_APP_ROOT='/absolute/path/to/isolated/full/v4_candidate/app'
V4_PYTHON='/absolute/path/to/existing/project/python'
```

不要把 `V4_PATCH_APP_ROOT` 指向正在运行的不可变 release。它应来自本机原有 release/checkout 流程的隔离候选，且未混入其他人的修改。若需要部署或启停服务，沿项目原流程另行执行并保留实际身份回执；本包没有自动部署脚本。

## 1. 核对完整包与两个 before 文件

```bash
(cd "$V4_REPAIR_PACKAGE" && shasum -a 256 -c PACKAGE_SHA256SUMS.txt)

"$V4_PYTHON" - "$V4_REPAIR_PACKAGE" "$V4_PATCH_APP_ROOT" before <<'PY'
from pathlib import Path
import hashlib, json, sys
pkg = Path(sys.argv[1]).resolve(strict=True)
app = Path(sys.argv[2]).resolve(strict=True)
phase = sys.argv[3]
manifest = json.loads((pkg / 'SOURCE_MANIFEST.json').read_text())
bad = []
for item in manifest['runtime_changes']:
    path = app / item['path']
    safe = path.is_file() and not path.is_symlink() and path.resolve() == path
    actual = hashlib.sha256(path.read_bytes()).hexdigest() if safe else None
    expected = item[phase + '_sha256']
    print(json.dumps({'path': item['path'], 'actual': actual, 'expected': expected,
                      'match': actual == expected}, ensure_ascii=False))
    if actual != expected:
        bad.append(item['path'])
if bad:
    raise SystemExit('SOURCE_IDENTITY_MISMATCH: ' + ', '.join(bad))
PY
```

runner 的 before 来源是历史 `manager-daily-chain-20261008-r2-api`；`workspace_plan.py` 的 before 来源是当前 `manager-live-ui-api-20261010-r1`。候选中任何一个文件缺失或 SHA 不符，都先定位实际版本差异，再移植本包的已证明小差异；不要整目录复制历史 API，也不要覆盖一个不同版本以凑 SHA。

## 2. 只应用两个文件的精确补丁

确认上一步两个 match 都为 true 后，在隔离候选运行：

```bash
(
  set -e
  cd "$V4_PATCH_APP_ROOT"
  git apply --check "$V4_REPAIR_PACKAGE/runtime.patch"
  git apply "$V4_REPAIR_PACKAGE/runtime.patch"
)
```

完整 after 文件同时保留在 `after/`。补丁应用后，将上面的 SHA 核对命令最后一个参数由 `before` 改为 `after` 再运行，两项都必须完全匹配。

若该 isolated app 已经在 Git 工作树内，检查 `git diff --` 后跟两个明确路径，确认仅出现本包差异。不要把测试支持源码、旧同名目录或环境变量一起替换。

## 3. 执行原业务函数回归

使用项目已有依赖的 Python，运行：

```bash
cd "$V4_PATCH_APP_ROOT"
PYTHONPATH="$V4_PATCH_APP_ROOT" "$V4_PYTHON" -m pytest -q \
  "$V4_REPAIR_PACKAGE/tests/targeted" \
  "$V4_REPAIR_PACKAGE/tests/upstream_reference" --tb=short
```

本会话对应结果为 42 passed。Mac 的依赖与运行入口需要独立验证；本包没有携带或替换 venv。扩展历史参考组请单独运行，并保留已记录的 1 项原 fixture 日历失配，不通过删测试或降生产状态要求消除它。

独立复核确认 `_readback` 与固定仓库已有修法逐字一致。若本机 `workspace_announcements` 不含本包所核验的完整 `validate_owner_analysis_readback`，这是版本身份不一致，应先定位；不能用残缺回执绕过该验证器。

## 4. 真实公告的续接顺序

从现有服务配置取得 `V4_LIVE_APP_ROOT`、`V4_API_BASE` 和 `V4_RESEARCH_STATE_ROOT`；当前包记录的 API 为 `http://127.0.0.1:8873`，实际以本机运行身份为准。先只读当前精确日期：

```bash
PYTHONPATH="$V4_LIVE_APP_ROOT" "$V4_PYTHON" \
  "$V4_LIVE_APP_ROOT/ops/run_manager_daily_announcement.py" readback \
  --target-date 20261009 --publication-date 2026-10-08 \
  --api-base "$V4_API_BASE"
```

这个命令应使用本轮已核验的 runner 及匹配的现有 consumer。有效回执验证仍要与下方 workspace 的 cutoff 消费结果核对。

### 如果同日期的原 handoff 已存在

从该 handoff 本身读取 `evidence_run_id`，确认 `catalog_read.json`、正文 terminal receipts、真实 reader/reviewer、decisions、`handoff_manifest.v1.json`、`analysis_product.json` 全部属于当前精确日期和同一 run。先通过原 `validate_registered_handoff`。若确实只是未导入，沿原入口执行：

```bash
PYTHONPATH="$V4_LIVE_APP_ROOT" "$V4_PYTHON" \
  "$V4_LIVE_APP_ROOT/ops/run_manager_daily_announcement.py" import \
  --evidence-run-id "$V4_EXISTING_EXACT_RUN_ID" \
  --research-state-root "$V4_RESEARCH_STATE_ROOT" \
  --api-base "$V4_API_BASE"
```

这是实际 owner 数据写入步骤，应由本机已授权原流程执行；本会话没有执行它。现有不可变不同内容冲突必须保留并定位，不删除冲突文件强行覆盖。

### 如果只有同日期已保存 capture，阅读审核尚未完成

复用该 catalog/body run；原 `capture --resume-evidence-run-id` 可用于同一保存 run 的恢复并验证 owner GET 对应关系。必须使用真实正文生成 reader/reviewer 输出及明确决策，再走原 `register-handoff`：

```bash
PYTHONPATH="$V4_LIVE_APP_ROOT" "$V4_PYTHON" \
  "$V4_LIVE_APP_ROOT/ops/run_manager_daily_announcement.py" register-handoff \
  --evidence-run-id "$V4_EXISTING_EXACT_RUN_ID" \
  --research-state-root "$V4_RESEARCH_STATE_ROOT" \
  --target-date 20261009 --publication-date 2026-10-08 \
  --semantic-catalog "$V4_REAL_SEMANTIC_CATALOG" \
  --reviewer-output "$V4_REAL_REVIEWER_OUTPUT" \
  --decisions "$V4_REAL_ARTICLE_DECISIONS" \
  --parent-task-id "$V4_REAL_PARENT_TASK_ID" \
  --reader-identity "$V4_REAL_READER_IDENTITY" \
  --reviewer-identity "$V4_REAL_REVIEWER_IDENTITY"
```

以上变量都来自真实任务及已完成的原输出，不填写 synthetic fixture 中的身份、run 或决策。没有明确决策时按原合同保留 `NOT_ASSESSED`。若原 capture 也没有，需由原 owner 正常执行真实采集和审核；不能仅凭本包源代码产生合法名单。

新采集、审核、导入的实际时间必须保留。晚于原研究 cutoff 的结果可以是新的历史研究重跑结果，不能改为原时点已可用。当前修补不会改变这一点。

## 5. 真实产物—接口—重载页面验收

使用同一个原 API，读取并在本机保存完整响应与文件 SHA：

```text
/api/v4/manager/research/announcements/analysis?date=20261009&publication_date=20261008
/api/v4/manager/research/workspace?date=20261009&view=dynamic&selection_date=20261009&announcement_date=20261008
```

逐项核对：

1. 原 source catalog、正文、语义记录、真实 review/decisions 与目标日期一致；缺失和未评估行有明确原因。
2. `product_sha256`、`source_manifest_sha256`、catalog run、evidence run、handoff、judgment、owner receipt 身份互相一致，且原验证器通过。
3. Workspace `product_checks` 中同一日期产品被实际消费；源时间、review、owner `available_at` 不晚于该 workspace 的真实 `research_cutoff`。
4. API 候选、观察、未评估的数量与原逐条决策和证券去重结果吻合；不能仅看一个 `candidate_count`。
5. 港股通、超跌和 Stage 各自原产物完成其必要 owner/输入验证；合法零结果须给完整覆盖和逐条拒绝原因，pending 不等于已证明零。
6. 原页面重新加载后，日期绑定、候选代码、原因、来源 SHA 和 API 一致。记录实际 URL、重载时间、屏幕结果和对应 API SHA。本会话只做了合成 FastAPI 重复 GET，没有执行这一步。
7. 若要声称自然运行，必须另取原 scheduler/owner 的实际周期 receipt；manual refresh 或历史重跑不能代替它。

## 6. 回滚

隔离候选回滚前，先用第 1 节命令核对两个文件均匹配 `after` SHA，再执行：

```bash
(
  set -e
  cd "$V4_PATCH_APP_ROOT"
  git apply --reverse --check "$V4_REPAIR_PACKAGE/runtime.patch"
  git apply --reverse "$V4_REPAIR_PACKAGE/runtime.patch"
)
```

最后核对两个 `before` SHA。若文件已被其他修改改变，先保留差异，不能强行反向覆盖。包内 `before/` 提供原始字节作为核验基准。

若后续已通过原流程部署，则用部署前保存的完整 release 身份执行项目既有 release 回切，并重新读回原 API/页面；本包未执行或自动化任何服务回切。回滚代码不应改写已产生的 owner 业务证据、日期、SHA 或时间戳。
