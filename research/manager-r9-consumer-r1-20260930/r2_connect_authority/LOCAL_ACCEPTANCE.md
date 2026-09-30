# 本机接续：先核资格原件，再采用R2，最后才验原API/UI

本轮Chat没有执行这里的Mac命令。路径来自2026-09-30反馈；执行前由本机主控核当前command/cwd/env/release，漂移即停止并记录，不用旧路径覆盖新版本。
不启动旧ensure/full-market producer，不补资格链，不动Stage/A股/BUY/Vibe8910/暂停daily。

## 0. 本轮冻结与已通过范围

唯一运行差异为 `v4/manager_research/connect_selection.py`。前像是本机已验R1 SHA `1d5a03958b36b3e430133dec4365ad56b9c244200d28eefdb2f96892ee8f3a0f`。
不要把runtime.patch直接打到原r9（该新增文件原先不存在），也不要重新覆盖其他9个R1后像。
本机唯一Writer负责新隔离候选；另一个独立Reviewer负责实际source、真实数据、配置及后续API/UI。包中的R1旧独立receipt不能升级成R2通过。

设置包根和本机原解释器（以下命令在解压包根执行）：

```bash
PKG="$PWD"
PY="/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python"
WORK="$HOME/Desktop/学习/agents调试/MANAGER_AUTHORITY_R2_20260930"
test ! -e "$WORK" || { echo '证据工作目录已存在，请保留旧收据并选新的目录'; exit 2; }
mkdir -p "$WORK"
"$PY" -I "$PKG/tools/verify_delivery.py" > "$WORK/package_check.log" 2>&1
"$PY" -I "$PKG/tools/run_offline_tests.py" --evidence-dir "$WORK/offline_tests"
```

上面仍然只是只读依赖/合成测试。不宣称完整r9或目标数据通过，也不要求重跑未变的R1全流程。

## 1. 直接核尚未展示过的V4目标日原件——此步不用先部署R2

下列两个根是显式比较对象，不是自动fallback。`selected-data-root`只是本机希望核查的候选根，不证明它被授权为唯一生产权威。

```bash
R1_APP="$HOME/Desktop/学习/agents调试/MANAGER_CONSUMER_R1_ACCEPTANCE_20260930/candidate/app"
OWNER_APP="$HOME/Desktop/学习/agents调试/v4_stage_root_hk_fix_20260928/line_fix_r1/today_combined_stage_fix_20260930/candidate/app"
V4_DATA="$HOME/Library/Application Support/com.lexi.v4.local/state/data"
OLD_DATA="$HOME/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data"
TARGET=20260930
# 记录现在这个真实截止时刻；不注入原reader的clock，不倒填历史取得时间。
CUTOFF="$("$PY" -I -c 'from datetime import datetime; from zoneinfo import ZoneInfo; print(datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat())')"
"$PY" -I "$PKG/tools/audit_connect_authority.py" \
  --app-root "$R1_APP" --owner-root "$OWNER_APP" \
  --owner-sha256 f527db45d4ec3720845606dd38e76bf6e93e973063b43f1cadb44a8e12407e5c \
  --data-root "$V4_DATA" --data-root "$OLD_DATA" --selected-data-root "$V4_DATA" \
  --date "$TARGET" --cutoff "$CUTOFF" --output-dir "$WORK/authority_intake" \
  > "$WORK/authority_intake.stdout.log" 2> "$WORK/authority_intake.stderr.log"
rc=$?
printf '%s\n' "$rc" > "$WORK/authority_intake.exit_code"
```

解释器在该工具进程内禁网，原数据目录只读；只新建WORK下证据文件。原reader/owner源SHA或路径不符会失败，不复制reference来凑SHA。完整原件通过时exit0仅表示READBACK_VERIFIED_PROPOSAL_ONLY，`activation_allowed=false`仍为false；缺件或冲突exit2，不忽略错误继续启用。

输出 `authority_intake/authority_readback.json` 包含每个根的目标日四件套身份/缺项、原reader诊断、原source捕获时钟和现在读回见证时钟。读取655或其他真实数量不符651旧合同会准确失败，不能删名单或改门槛。
不能用当前查询为20260929重造原件。检查历史日只允许读取当日真正保存的原件，供给缺失保持CANNOT_CONFIRM。

## 2. 证明当前供给职责，不把上一步当生产半段完成

有完整authority时，由本机唯一Writer提取**该产物所指原job**的最小闭包证据：实际运行command/cwd和必要路径配置、加载源码SHA、父调度/run、原始源响应及真实请求/取得时钟、产物四件套的相同document/run/SHA。只提取必要字段，不导出凭证。

没有原件时，按照OWNER_CLOSURE.md的B/C分支处理。已有原collector的plate响应可在同一job内沿原owner发布资格分支，但必须先确认其活动源和完整原响应，不能用filtered snapshot代替；本包没有这段当前生产实现前像，故没有伪造其精确diff。

此阶段达不到时，停止资格启用，提交本次原reader具体缺项和owner缺口，不再重写正文分类，不再反复重复旧空输入的网络请求。

## 3. 只有本机主控决定继续时，构建R1+R2隔离候选

该步骤不改活动release。必须完整R1 app仍在，并且10个源SHA与本机已验pin一致。下列代码复制完整app后，只应用一文件runtime.patch；不把包内reference_only混入候选。

```bash
R2_OUT="$WORK/r2_candidate"
"$PY" -I - "$PKG" "$R1_APP" "$R2_OUT" <<'PY'
from pathlib import Path
import hashlib,json,shutil,subprocess,sys
pkg,src,out=map(Path,sys.argv[1:])
for p in (pkg,src,out):
    assert p.is_absolute() and p.resolve()==p and '..' not in p.parts, 'PATH_NOT_EXACT'
assert src.is_dir() and not out.exists() and not out.is_relative_to(src), 'DESTINATION_INVALID'
pins=json.loads((pkg/'evidence/input_feedback/SOURCE_PINS.json').read_text())
for row in pins['files']:
    p=src/row['target_path']
    assert p.is_file() and not p.is_symlink(), 'R1_FILE_MISSING_OR_LINK'
    assert hashlib.sha256(p.read_bytes()).hexdigest()==row['after_sha256'], 'R1_SOURCE_DRIFT:'+str(p)
def inventory(root):
    found={}
    for p in root.rglob('*'):
        rel=p.relative_to(root)
        if any(x in {'.git','__pycache__','.pytest_cache'} for x in rel.parts):continue
        assert not p.is_symlink(), 'UNREVIEWED_SOURCE_SYMLINK'
        if p.is_file():found[str(rel)]=hashlib.sha256(p.read_bytes()).hexdigest()
    return found
before=inventory(src)
app=out/'app'
shutil.copytree(src,app,ignore=shutil.ignore_patterns('.git','__pycache__','.pytest_cache'))
assert inventory(app)==before and inventory(src)==before, 'COPY_OR_SOURCE_DRIFT'
subprocess.run(['git','apply','--check',str(pkg/'runtime.patch')],cwd=app,check=True)
subprocess.run(['git','apply',str(pkg/'runtime.patch')],cwd=app,check=True)
final=inventory(app)
changed=[p for p in sorted(before.keys()|final.keys()) if before.get(p)!=final.get(p)]
assert changed==['v4/manager_research/connect_selection.py'], 'UNEXPECTED_CHANGE_SCOPE'
pin=json.loads((pkg/'SOURCE_PINS.json').read_text())['runtime_files'][0]
assert final[changed[0]]==pin['after_sha256'], 'AFTER_SHA_MISMATCH'
assert inventory(src)==before, 'SOURCE_CHANGED'
(out/'clone_receipt.json').write_text(json.dumps(dict(status='ISOLATED_SOURCE_CLONE_ONLY',
 source_app=str(src),candidate_app=str(app),changed=changed,before=before[changed[0]],
 after=final[changed[0]],deployed=False),indent=2)+'\n')
print(app)
PY
```

独立Reviewer在这个完整实际候选内按本机原工具复验受影响的47项R1 targeted合同，以及本次原reader参数/拒因/只读核验；原6个回归失败仍与基线比较，不删除或改为skip。复用未改源码/验收，不重跑pytdx、公告采集或暂停daily。

## 4. Binding、原API及UI验收——均未在Chat完成

仅在第1步实际四件套、第2步唯一producer职责、第3步独立代码/行为均确认后，才把读取报告中的三字段environment交给**现有发布流程**制作候选API binding。不要修改Stage数据配置或关闭安全门。

全量当前plist和发布manifest未随包提供，因此本包不伪造精确plist diff、不提供跳过既有发布检查的launchctl命令。部署前从真实plist制作前/后像，逐字段核只有该绑定及候选release身份发生授权变化，保留当前安全字段、暂停daily和其他源root。新owner源码SHA必须与那次authority验收同一版本；漂移需重验，不直接改expected SHA。

由本机原 `ManagerResearchJobService.refresh_workspace_plan` 刷新原工作台，保存一次真实POST `/api/v4/manager/research/workspace/refresh?date=<target>` 与一次GET `/api/v4/manager/research/workspace?date=<target>` 的完整未改写响应及请求时间/SHA。旧包的capture_original_api.py可沿用，但必须绑定当前候选source/release证据；它是记录器，不是独立review。

逐项核：目标日、加载的三字段和owner代码SHA、membership原件/current/manifest/receipt及run、所有候选的Connect身份/原文/时间、US两侧源及长期关系有效期、0候选逐项拒因。`read_scope`成功只证明其read-side合同；不是“整个页面所有候选可交易”。

UI按UI_ACCEPTANCE_CONTRACT.md冻结实际最小前端路径和SHA后再改，保留原URL/date、API响应SHA、页面截图/原文链接/时间标签/拒因与独立Reviewer回执。没有实际前端前像时不从别的快照替换组件。HTTP200、旧正文面板、合成HTML不能替代这一验收。

## 5. 回退

未部署时：保留R2候选和失败证据，不改活动r9，R1原候选保持不变。
已通过本机正式发布流程才切换过时：用既有发布工具恢复切换前完整API release、manifest和plist前像，删除本次新增三字段只能在恢复的**原前像**范围操作；当前原Stage、公告调度、暂停daily状态不改变。不得恢复9月29日较旧的plan-only配置覆盖9月30日现状。

隔离候选内代码回退可用 `git apply --reverse --check runtime.patch` 后再reverse；SHA必须回到SOURCE_PINS.before。部署环境不原地反打源码替代完整release回退。所有失败收据保留，真实缺源不能靠回退更宽松门槛掩盖。
