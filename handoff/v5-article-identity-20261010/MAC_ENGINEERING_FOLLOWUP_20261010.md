# Mac 工程后续说明 — 2026-10-10

本文件是新增后续回执，不修改或替换 `cdd430e4dcd8d3e8c5949baff21a4831b4689444` 冻结问题包的 START_HERE、源码、测试、SHA 清单或 ZIP。未主动联系外部 Chat。

## 工程状态更新

固定候选 `7115f65267a1496d0ca8214cc14130f8c2b65d87` 已在 Mac 隔离快照实际运行。测试修正与上一轮回执位于提交 `5b64314de334908faeee8ba463922e42bbf78518`：
[V5 Mac 回执](../../V5/docs/reviews/2026-10-10-article-v2-mac-verification.md)。

新增合成直接关系正例原先被中文逗号分成两个主体子句；已只修正该 fixture，并保留跨句不冒认 AVGO 的负例。原生产算法未改。独立行业、US个股、跨句负例及同 run 保存/读回三项已通过。

此前六组的唯一 error 是本地测试 socket bind EPERM。独立 Reviewer 核实 `create_module_server` 强制 `127.0.0.1`、使用临时端口和临时 store，GET 前后校验文件不变。依用户新增授权，执行工具经正常 `require_escalated` 通道**仅复跑完整六组一次**，未遭审核拒绝，也未修改系统安全设置或绕过拒绝。

**实际结果：退出码 0，59/59 通过，18.203 秒。** 先前 HTTP EPERM 工程限制解除；先前失败回执保留。该结论只覆盖六组工程测试，不覆盖真实新材料、部署、浏览器或自然接续。

环境：macOS 26.6.2，Python 3.13.12。工作目录：
`/Users/lexi/Documents/Codex/2026-10-10/task-2/candidate/V5`

实际命令（pipefail 保留测试退出码）：

```sh
set -o pipefail
env TMPDIR=/private/var/folders/mw/045dzcpj70x3m5nnfwj6lmnm0000gn/T V5_ARCHIVE_PRODUCER_SOURCE_ROOT=/Users/lexi/Documents/Codex/2026-10-02/task/V4_SOURCE_SYNC_20261005/payload/handoff/v4-running-source-20261005/canonical PYTHONPATH=src:tests /Users/lexi/.local/bin/python3.13 -B -m unittest test_archive_acquisition_producer test_archive_article_v2 test_current_us_research test_manager_archive_reader test_us_mapping_scope test_manager_plan -v 2>&1 | tee /Users/lexi/Documents/Codex/2026-10-10/task-2/review/mac-full-regression-escalated.log
```

本机独立回执：
`task-2/review/mac-full-regression-escalated.md` 和同名 `.log`。

## 身份问题仍 OPEN

59项不包含本冻结问题包的三个 `test_identity_gap_candidate` 用例。本轮没有执行该包的 control/身份变异复现，不能把工程通过解释为身份漏洞修复。

原 article_id/dedupe_key 来源缺口保持 OPEN；7115 的微秒时间、response group、status路径SHA绑定修正未回退。外部后续修复仍应沿原 builder 校验，不猜还原丢失字段。

## 同任务真实输入缺口

限定搜索 `task-2`（当次625文件/45 JSON）、`current-us-8a667188/evidence/remaining19`（87/83）、`current-us-8a667188/real-input`（7/6），并检查该 current-us 项目的捕获文件名，没有找到 `v5.zsxq_acquisition_receipt.v3` 或同批 pages/recent/summary。该结果只针对以上范围，不声称全机不存在。

已有20261009 US三文件与native HK identity可复用，但旧V1归档2058条缺 retrieved_at/available_at，不能补造为取得/可用时点。要继续真实接线，最小输入为：

1. 原 producer 的 v3 receipt：每页 SHA/完成时间、落盘可用时间，以及所声明的同 run page-response、recent、summary 等文件。
2. 同批原 builder 产出的 archive v1；身份修复还需完整 builder source：trade_date、source_manifest、stock_research_timeline、stock_research_daily，保留 claim_type、evidence_level、source_path 和原去重字段。原 builder 重建并核字节/规范SHA；仅给archive v1不闭合身份来源。
3. 与消费 cutoff/session 一致、按原门禁合格的 US三文件和 native identity。已有10/09快照不能自动当未来运行当前输入。

## 现有认证诊断与最小用户操作

现有官方 `zsxq-cli` 0.4.9、原 analyzer、refetch root、selector panel存在。先前只读 `doctor` 实际退出 **5**，输出 `Authentication: keychain error: exit status 152`。

只读公开包文档与安装二进制静态符号表明 doctor 经 LoadToken 进入 Keychain 读取路径。文档将外层5定义为内部错误、11定义为未认证/过期；内层152未给定义，不能据此判断钥匙串锁定、条目缺失、权限拒绝或OAuth过期。本轮未重跑doctor、未运行security/auth status/auth login、未打开凭据或配置秘密值，未发网络请求。

最小下一步：用户在正常登录的 Mac 终端运行以下既有命令，检查现有认证路径；仅保留成功状态或非秘密错误，无需导出/提供令牌：

```sh
/Users/lexi/Documents/Codex/2026-08-13/v35-019ff682/shared-research-runtime/npm/node_modules/.bin/zsxq-cli doctor
```

若仍报错，由用户恢复既有 CLI 对登录钥匙串的正常访问；若确实需要重新授权原账号，应由用户通过既有官方流程完成。本回执不要求修改系统安全设置。doctor通过后，才能沿原已授权采集链取得新不可变捕获，再执行原builder和同run真实读回；不重复采已成功源。

本机诊断：`task-2/MAC_FOLLOWUP_KEYCHAIN_RECEIPT_DIAGNOSTIC.md`、`task-2/acquisition-readiness.log`。M04/M15全模块、真实材料与自然运行尚未完成，V4、61796和已有四键三股成果保持。
