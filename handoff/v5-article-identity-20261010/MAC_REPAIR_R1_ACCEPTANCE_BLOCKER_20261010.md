# Identity repair r1 Mac 验收阻塞回执

固定交付：`9fb6fa7ab1be54de9d03463e11926ad76e1cae27`，分支 `chat/v5-article-identity-repair-20261010-r1`。已读该交付的 START_HERE、MAC_ACCEPTANCE、SOURCE_SHA256、STATIC_REVIEW；未改冻结问题包。本回执不集成任何未验产品代码。

## 已完成来源校验

- 候选 tree：`5f028eae2dfe0fa0c05e1e67e93b0f77ff2b6594`；父版本 `cdd430e4dcd8d3e8c5949baff21a4831b4689444`。远端递归树2671条，非截断。
- 新隔离根：`/Users/lexi/Documents/Codex/2026-10-10/task-2/identity-r1`。
- `baseline/` 的608个必要源文件匹配旧固定blob，另有冻结三项测试，blob `fdb695357ecc2884e2c34f049947002ced03005c`。
- `candidate/` 的627个目标文件匹配新固定blob，另含计划文件；SOURCE_SHA256内18项全部匹配长度与SHA256。校验退出0。两目录是必要文件快照，不冒称完整git checkout。
- 原task-2/candidate及59/59结果保持。5b64314的fixture/负例修正尚未合入新候选；不能整树覆盖。

## 本机真实依赖门

候选要求15项均匹配。期望 `domains/research.py` SHA256：
`b77cc0d3c9ec36eeee3e6cab207945a783b0352a703efdb5c8e2f7f17966506f`。

| 只读原根 | 结果 | research.py实际SHA256 | 实际research-hourly namespace |
|---|---|---|---|
| `/Users/lexi/Documents/Codex/2026-10-02/task/V4_SOURCE_SYNC_20261005/payload/handoff/v4-running-source-20261005/canonical` | 13/15，拒绝 | `2ad669ea58f08338605885547ec065921ec63cc0047460bb2acd153151fb214b` | 原路径缺失 |
| `/Users/lexi/Desktop/学习/v4_app` | 14/15，拒绝 | `b784915ade13720032732921ebc7f219efa420452cf8cd57d42b6e3bad6c9860` | 存在且为 `45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1` |

通用namespace路径或候选vendor字节没有被拿来冒充原路径。两个原根未改，依赖门未放宽。完整清单在本机 `identity-r1/source_dependency_check.json`。

## RED/GREEN 实际状态

旧基线自己的7项依赖在canonical中7/7匹配；与候选15项门分开。

第一条基线命令误用系统Python 3.9.6，在导入 `type | None` 注解处退出1，未执行测试。日志 `identity-r1/baseline-red.log`。该结果不是RED。

随后使用本任务此前已成功的Python3.13重试。实际请求命令如下，cwd为 `identity-r1/baseline`：

```sh
set -o pipefail
env TMPDIR=/private/var/folders/mw/045dzcpj70x3m5nnfwj6lmnm0000gn/T V5_ARCHIVE_PRODUCER_SOURCE_ROOT=/Users/lexi/Documents/Codex/2026-10-02/task/V4_SOURCE_SYNC_20261005/payload/handoff/v4-running-source-20261005/canonical PYTHONPATH=V5/src:V5/tests:handoff/v5-article-identity-20261010 /Users/lexi/.local/bin/python3.13 -B -m unittest test_identity_gap_candidate.IdentityGapCandidate.test_control_valid_capture_is_accepted test_identity_gap_candidate.IdentityGapCandidate.test_article_id_mutation_must_be_rejected test_identity_gap_candidate.IdentityGapCandidate.test_dedupe_key_mutation_must_be_rejected -v 2>&1 | tee /Users/lexi/Documents/Codex/2026-10-10/task-2/identity-r1/baseline-red-python313.log
```

执行工具最终返回进程创建失败：

```text
Failed to create unified exec process:
exec-server connection attempt failed:
environment registry request failed
(409 Conflict, environment_offline): Environment is not connected.
```

因此此重试**没有产品进程退出码、没有测试输出**，不能计失败测试或RED。未反复启动未知状态的测试。新候选“51”仍只是静态方法数，51批次、相关回归及新source安全/类型/时间/owner重放动态验证全部NOT_RUN。此前59/59针对5b64314，不能迁移为9fb6的PASS。

## 恢复后的明确续点

1. 恢复同一Mac执行连接；不需先恢复真实采集认证。先在baseline按上述Python3.13命令跑三项，control成功且两个单键变异在unexpectedly accepted处失败才确认RED。
2. 原两root维持拒绝。独立审查认为可另建**固定cdd完整canonical Git树重建＋真实原路径namespace单独结构补件**的工程快照：原canonical逐blob匹配，缺文件从固定cdd原路径取得；namespace只能来自已核的本机真实路径，记录源路径、SHA/长度、复制前后字节相等，不取vendor/stub。必须标明其工程快照属性，不声称是原始未改cdd树或现役源。该恢复路径目前仅经条件审查，**尚未创建或运行**。
3. 完整源证明与15/15门成立后，运行原交付身份候选及相关回归；观察真实结果后精确合入5b64314同句正例/跨句负例，并更新相应SHA，必要最小修复交独审。
4. 同步产品前核开发分支冲突；本次只新增本说明。source/archive同时伪造、1/true、可用时间、安全IO/no-overwrite与完整owner重放均须动态证据，不能靠静态判断签GREEN。

真实同批builder source仍CANNOT_CONFIRM，natural_verified=false；未读取秘密、未改认证/安全配置、未用Chrome、未触碰V4/61796、未部署。
