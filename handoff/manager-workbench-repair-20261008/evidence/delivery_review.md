# 最终交付包窄范围独立复核

日期：2026-10-08。审查对象：`delivery/manager-workbench-repair-20261008`。本次仅核对交付说明、源码清单、补丁边界、preflight 记录、结果说明与只读校验工具；未重跑业务测试，未修改业务源码、交付正文、manifest 或 preflight。

## 结论

**就本次已审内容，没有未关闭的 Important 问题。** README 的校验命令和调查阶段的失效证据引用均已修正；另发现并关闭了交付工具的源内报告写入漏洞。该工具问题与前一轮业务审查的 **7 项 Important 闭环**分开计数。

包内说明与前一轮独立代码审查一致：这是已审查的代码候选，**不是已部署完整 release，也不证明实际 Mac 进程、真实页面或三路自然运行完成**。完整依赖闭包、真实成交量单位/倍率、目标 V2 与 D-1 原始身份、06:30 heartbeat 的真实 reader/reviewer、独立 US 准备入口、生产构建与现场运行证据仍明确未闭合。

## 源码、覆盖范围与 preflight

- 独立逐文件计算全部 **24 个 payload** 的 SHA256 和字节数，均与 `source_manifest.json` 一致。其中 23 个修复 payload 与最终 `candidate` 对应文件逐字节相同；另 1 个为明确分开的既有 scheduler daemon 前置增量。
- 清单分为 `api=12`、`web=3`、`tests=8`、`scheduler_prerequisite=1`。主正反补丁限定 23 个修复路径，scheduler 正反补丁只包含 daemon。
- 主补丁、前置补丁和 payload 均未覆盖现役 `ops/launch_v35_macos_scheduler.sh`、`ops/run_v35_macos_scheduler.py` 或 `businessStatus.ts`。这三项的 preserve pin 保持严格；API 的 R3 `announcement_analysis.py` 兼容字节也单独保留。
- 文档明确要求从现场已核完整 API/scheduler 副本构建候选，保留实际 launcher、runner、due.py、native 依赖、symlink/mode 和数据根；不能把组装树整体部署为当前 release。
- 四份 preflight 的 `manifest_sha256` 均匹配当前清单 `ecc428fb1473b90867a5b58abb82d89a094eaec311fa478c69c09dd5abf4f7fb`。

| 记录 | 结果 | 审查判断 |
| --- | --- | --- |
| API before / baseline | PASS | 与前像字节核验一致，不代表实际 Mac 前像 |
| API after / candidate | PASS | 与候选字节核验一致，不代表服务已切换 |
| Scheduler before / frozen snapshot | PASS | 明确标为冻结快照，实际进程身份仍 NOT_VERIFIED |
| Web after / assembled snapshot | FAIL | 正确保留 `businessStatus.ts` 的 `PRESERVE_SHA_MISMATCH`，没有改 pin 或复制旧版本冒充通过 |

## 命令与文档修正

初始 README 的三条示例使用 `--package-root .`，而工具强制绝对路径。独立执行实际示例得到 `FAIL / ABSOLUTE_PATH_REQUIRED`，文件检查数为零。最小修正已实施：示例省略此参数，使用工具默认的绝对脚本包根，未放松路径检查。

修正后本人通过真实 CLI 对实际 baseline 执行 README 用法，得到 **PASS：24 个包 payload、12 个 API 源文件、1 个 preserve pin**。

`SCHEDULER_CLOSURE.md`、`FRONTEND.md` 的证据引用已改为包内实际路径；`INPUT_OWNER_MAP.md` 已明确 F1–F4 是修复前定位记录，并链接最终修改和测试证据。最终检查 README 和全部 docs 的 Markdown 相对链接，**无失效目标**。

`results.json` 对代码测试、合成 API/DOM、完整构建、部署、真实 API/页面和自然运行分别给出状态；明确记录实际故障产品对尚未在 Mac 识别。后端 123、前端 29 的结果有对应包内最终日志，不与独立审查重叠批次相加。

## Important：只读工具的源内报告写入漏洞——已关闭

初始 `tools/verify_delivery.py::_write_report` 仅用字符串父路径判断源内目标；`main` 即使已因 source-root 符号链接拒绝核验，仍继续生成报告。因此 `source-alias -> real-source` 时，核验返回 `SYMLINK_NOT_ALLOWED`，随后向 `real-source/new-report.json` 写报告却可以成功。本人在独立临时目录复现了该原始行为；真实候选和包内业务文件未被写入。

最终修正位于 `tools/verify_delivery.py:265`、`:287`：写报告前按相同 nofollow 规则打开并验证 source 根；用打开目录的 `(st_dev, st_ino)` 沿报告父目录的 `..` 祖先链检查是否位于源码树内，避免只依赖路径拼写；通过后才使用 `O_EXCL` 新建报告。合法根的源文件 SHA 不匹配仍允许生成源外失败报告。

本人对最终文件执行了以下**真实 subprocess CLI**回归，全部符合预期：

| 情形 | 最终结果 |
| --- | --- |
| source 根为符号链接，报告指向真实源码树 | FAIL，含 `SYMLINK_NOT_ALLOWED` 和 `REPORT_WRITE_FAILED`；源码树内未创建报告 |
| 合法源码根，报告在其嵌套子目录 | FAIL / `REPORT_INSIDE_SOURCE_ROOT`；未创建报告 |
| 合法源码根但待核文件缺失，报告位于源外 | 核验保持 FAIL；成功生成源外失败报告 |
| 同一源外报告路径再次调用 | FAIL / `REPORT_WRITE_FAILED`；原报告字节不变 |

工具作者另新增实际 CLI red 回归并完成最终 **17 项自测通过**。本审查已读取包内 `evidence/tests/delivery_verifier_report_guard.log` 的 17 项成功结果，并核对 `results.json` 已直接指向该最终日志；旧 13 项日志明确保留为初始证据。本审查独立执行的是上表四类 CLI 情形及 README 实际 preflight，没有将作者的 17 项自测称为本人重跑。

审阅的最终工具 SHA256：

- `tools/verify_delivery.py`：`cfc2c28327bc260047ef011bc0b09f8cbba862039c5429d3e9f5a9677e251cfa`
- `tools/test_verify_delivery.py`：`6e3d38797f4d6c0520c9b7395f563d8c41242bfba88321021d1fb04058359f1f`

## 审查边界

`package_manifest` 将由主控在工具、日志和本报告字节稳定后生成；按本次明确分工，该尚未生成的文件没有被本审查预先认证。源码 payload 的精确比对已完成。实际 Mac 大小写文件系统、现场 release 与进程、服务切换、canary 和自然时段均未在此环境运行，不能由这些离线检查升级为通过。
