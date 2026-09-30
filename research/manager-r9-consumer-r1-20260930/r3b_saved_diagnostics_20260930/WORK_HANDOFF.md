# 交给原经理 Work：R3-B 隔离应用、复验、回退

Chat 已完成研发；Work 不承担宽泛研发。运行只变一个文件，不需要 R3-A/F0 放行。
复用 cf306997… 的既有 R1/R2 验收。不要重跑未变化的 47/27 项或其他项目测试；本次先跑附带 10 项 changed-surface 测试。原工作规程另有必要的相关测试须单列范围，不能隐藏失败。

## 1. 验交付并复制已验 R2 到新隔离候选

从解压目录执行，PKG 为绝对路径。下面只创建隔离副本和测试输出；不使用活动 release，不重载服务。

```bash
set -euo pipefail
PKG="$PWD"
PY="/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python"
BASE="/Users/lexi/Desktop/学习/agents调试/MANAGER_AUTHORITY_R2_ACCEPTANCE_20260930/candidate/app"
RUN="/Users/lexi/Desktop/学习/agents调试/MANAGER_R3B_ACCEPTANCE_20260930"
CAND="$RUN/candidate/app"
"$PY" "$PKG/tools/verify_delivery.py"
test -d "$BASE"
test ! -e "$RUN"
mkdir -p "$RUN/candidate"
/usr/bin/ditto "$BASE" "$CAND"
"$PY" - "$CAND" <<'PY'
from pathlib import Path
import hashlib, sys
p=Path(sys.argv[1])
for rel, expected in {
 'v4/manager_research/workspace.py':'ec9c7ba68c93061fa035747ba08c6e71fc7c167c322db2e225963542c72cd2d7',
 'v4/manager_research/connect_selection.py':'b6c5300172f59b6979dbab15927036ff1ab3599a2adae2b4f0e5a1e4868a6248',
}.items():
 assert hashlib.sha256((p/rel).read_bytes()).hexdigest()==expected, 'PREIMAGE_DRIFT:'+rel
PY
(cd "$CAND" && git apply --check "$PKG/runtime.patch" && git apply "$PKG/runtime.patch")
"$PY" -I "$PKG/tools/run_tests.py" --app-root "$CAND" --output-dir "$RUN/writer-test"
```

仅以上两文件核适用性，不重复全项目同 SHA 审计。若原冻结路径有迁移，用原已验 R2 的真实定位替换 BASE，不拿 active/canonical 未冻结树顶替。已有 RUN 时另取新隔离名字，不删除旧回执。

## 2. 独立复验

由独立 Reviewer 在同一冻结 CAND、不同新进程运行：

```bash
"$PY" -I "$PKG/tools/run_tests.py" --app-root "$CAND" --output-dir "$RUN/reviewer-test"
```

runner 只测试包内10项，不安装依赖、不请求任何市场数据。它绑定传入 app 的实际导入路径/源码，原 writer/store/_read_plan/_readback_plan/get_workspace/_compute_workspace 不被替换；替换仅在合成上游输入边界。输出 `pytest.log`、JUnit、导入身份、环境及测试退出码。

核对 changed-pin witness：同一 run_id/input_identity/product SHA，响应诊断 NEW_PIN，保存文件仍保留 OLD_PIN 且全字节不变。名单只有合成 allowed 股；非港股/非资格股不得进入，BUY false。另核未变 binding、失效资格、破坏保存文件、较早 cutoff 等反例。

若新测试受实际 Mac 依赖影响失败，保留完整退出码/异常和精确差异，不能删用例或换旧依赖凑绿。平台适配仍限本批，不开展其他代码研发。

独立 receipt 必须记录：Writer/Reviewer 身份、前后 SHA、实际测试命令/日志/JUnit SHA、运行 Python/OS、使用的 app 根与导入根、P0/P1/P2；`DEPLOYED/API_VERIFIED/UI_VERIFIED/NATURAL_VERIFIED=CANNOT_CONFIRM`。不把作者日志更名成独立结果。

## 3. 回退（仅新隔离副本）

```bash
"$PY" - "$CAND" <<'PY'
from pathlib import Path
import hashlib, sys
p=Path(sys.argv[1])/'v4/manager_research/workspace.py'
assert hashlib.sha256(p.read_bytes()).hexdigest()=='8a1ce5122be59f2d56e258522909ca0ff76345a32aed3b4a2517e9cfb2e7c190'
PY
(cd "$CAND" && git apply -R --check "$PKG/runtime.patch" && git apply -R "$PKG/runtime.patch")
```

回退后 workspace.py 应为前像 ec9c7b…；原 R2、活动服务、资格数据不曾被改，无需改配置/回退线上。保留全部测试回执。禁止在活动 release 执行这些命令。

## 4. 本轮不执行

不部署/合并、不变 PR9 Draft / Issue8 Open、不启用绑定、不运行 producer/Futu，不强造09969→LLY。真实资格 reader 接受、满足消费时点后，才进入另批原经理 API/UI 业务验收。
