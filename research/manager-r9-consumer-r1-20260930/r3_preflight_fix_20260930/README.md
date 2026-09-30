# Issue #8：R3 取证工具返修候选

输入证据：852708f6f210f3e7e9abcc065d7826815c8f39f2。
修复前像：145f35355cf3e47e335a580452c97175eb36c5f8 的 audit_r3_source_release_binding.py，SHA256 91a74a28600fc5066dbfe4489f1a0a43113b760a52e4142afdd1fa77d817e619。

这是取证工具修订，不是 R3-A producer 修改，不是 R3-B 修改。原 R1/R2、旧 preflight、原验收目录及 manifest 不覆盖。

## 修正

1. 识别 WorkingDirectory、Program、脚本路径与旧的裸 app 参数；交叉核对，拒绝相互冲突的 roots 和未经审阅的 shell -c 字符串。不再取第一个候选。
2. 比较两个实现树中已知 dispatcher/capture 拆分族全部 Python 文件，再静态递归本地 import 和包 __init__；包括 panel_execution.py、hk_market_capture.py、两组 _namespace.py 及可解析的传递依赖。动态加载、缺件、语法错误、预算超限明确报告。
3. 静态集合只是保守超集，不证明实际运行依赖闭包。文件相同只输出 EQUAL_FOR_COLLECTED_FILES；historical_lineage、behavior_equivalence、formal_activation 各自保持 CANNOT_CONFIRM，producer_edit_allowed 永远为 false。不能拿本工具当作 R3-A 自动授权门。
4. plist/manifest 只读本机原字节用于 SHA；只输出 manifest 白名单状态字段，不复制原件、环境变量、参数全集、异常文本或源文件正文。Git 仅读取 HEAD 与所查路径的 dirty/untracked 状态，不输出 diff。
5. 不导入项目模块，不执行采集器/服务/网络；单文件 2 MiB、单树 256 文件/32 MiB、拆分目录 96 项上限。拒绝 symlink/FIFO；输出只创建新文件，禁止覆盖证据或写进 canonical/release/config 目录。

## 当前结果不是“再跑一遍 hash 就能 PASS”

已回传的原始结论直接复用：canonical 与 configured release 不同；1555 收据不证明 1720 来源。不要对相同源码重复运行以期待状态变化。参见 FORWARD_ALIGNMENT.md，先裁定前向来源对齐；修订工具只在新来源/新构建或独立工具复验时使用。

## 作者环境测试

```bash
python -m pytest -q
```

原工具在五个聚焦场景全部失败；返修工具声明测试范围 30 项通过。测试使用临时合成目录/合成 plist，不代表 Mac/Luna、真实 owner、资格产物或 API/UI 已验。详情见 TEST_REPORT.md。

## 本机独立复验（不接触 producer）

由项目既有唯一 Luna Max Writer 接续候选，另一 Luna Max Reviewer 复跑本工具测试；本轮 Chat 只是作者候选，不冒称二者。

以下命令从本目录执行。仅在新的取证理由成立时运行后半段，不重复已完成的 852708... 比较：

```bash
PY="/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python"
"$PY" -m pytest -q tests/test_preflight.py
OUT=$(/usr/bin/mktemp -d /private/tmp/issue8-r3-audit.XXXXXX)
"$PY" after/tools/audit_r3_source_release_binding.py \
  --canonical "/Users/lexi/Desktop/学习/v4_app" \
  --plist "/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist" \
  --output "$OUT/receipt.json"
```

退出 1：已输出观察，但来源门仍 CANNOT_CONFIRM；退出 2：输入、路径或输出拒绝。成功比较应有 comparison_completed=true、files 非空；不得只看退出码。动态依赖未决/预算不足也不能宣称完整闭包。

没有需要回传的原始 plist 或环境值。仅回传白名单回执及独立 Reviewer 结果。新 audit_started_at/finished_at 只代表本次静态取证时间，不回填此前取证或 plate acquired_at。

## 采用与回退

直接使用 after/tools 新工具即可。tools.patch 相对旧工具目录，以 -p1 在隔离副本应用；tests.patch 添加同目录下 tests。补丁正反向已按字节核验。回退仅还原隔离工具副本，不触碰业务源码、release、LaunchAgent、manifest 或服务。旧工具保留为缺陷证据，不能再作为绑定门。

PR #9 仍须 Draft，Issue #8 仍须 Open。未合并、部署、启用绑定、调用 Futu、运行真实 canary。
