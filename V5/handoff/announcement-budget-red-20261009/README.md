# 公告预算与有界并发：第二轮修复候选

状态 **HTTP_POLICY_RED_CANDIDATE_NOT_RUN**。历史记录：本轮依据现有 Mac 实际 RED 修复真实 provider/transport 字节计量和独立 CLI 初始化，完整说明见 [REVIEW_FIX.md](REVIEW_FIX.md)。云端没有运行产品测试，未采集、集成或部署。

第一轮 e4fc9225 已由父任务报告 Mac 18 项通过。第二轮 cdab6fa8 实际为 provider 2 PASS / 4 FAIL、CLI 1 FAIL，均 exit1，无环境ERROR；本次以此为依据实现。原18+7断言不变，增加6项竞争/未知消耗回归，待Mac单次复验31项。历史失败测试及设计记录见 [REVIEW_RED.md](REVIEW_RED.md)，其中“未实现/未运行”描述只对应历史cdab候选，不代表本轮状态。

## 当前阶段：HTTP门禁RED及私有owner接线

父任务已报告79fcdf81的31项Mac通过、两缺陷独立复审关闭。现进入今天完整链适配：本轮仅新增9项HTTP门禁失败回归及12项固定依赖来源清单，生产三文件不变。请先执行 [HTTP_POLICY_RED.md](HTTP_POLICY_RED.md) 的单次新测试命令；不要重复下面历史31项复验命令。该文也给出复用原完整链的V5私有owner分派边界，下一阶段不通过8873写入。

## 固定来源、交付和边界

- 分支 `v5/announcement-capture-budget-20261009`；路径仅 `V5/handoff/announcement-budget-red-20261009/`。
- 初始V5基线 `945b89d7c3411a4913f50c4472514a61676c621e`；本次parent `cdab6fa8843d5007c216e83d0bff9e61aa01f7a8`。
- 原源 `0fd5eb374cb155232ed003d5fc4d0d3594252491`。`SOURCE_MANIFEST.json`/`pinned/` 保留逐文件原路径、来源manifest SHA、blob SHA及SHA256；依赖按该提交API manifest选择，不取main。父任务已报告13个原文件与目标R3 app/canonical对应文件同SHA，不等于整个现役进程等价。
- `candidate/` 提供三个生产完整文件：`ops/manager_announcement_body_batch.py`、`v4/manager_research/announcement_source.py`、`v4/manager_research/hkex_provider.py`。`CANDIDATE_MANIFEST.json` 记录前后SHA，`SHA256SUMS` 覆盖本交付。须一起核验/集成，不能混用旧provider。
- 无manager_plan、UI、workspace源码变更；pinned的workspace_projection.py仅为不变测试依赖。不提交公告数据、凭据、日志、pycache或tar.gz。
- 不新建采集器：日期目录→全目录body→审查导入流水线、来源/日期/SHA、one-attempt/NO_RETRY等门禁保持。原3 workers/2000调用/64MiB/3600s/0.35s数值不变。

## 已实现

timeout取provider配置与剩余时间的最小值；短计数锁与最多3在途许可分离；逐请求字节预留和累计结算；每worker独立provider/opener；URL与批owner排他、唯一临时名、聚合主线程写入。真实read返回字节即时计量，拒绝响应仍保留计数；探测第+1字节也先取得预算；未知消耗标记并停止同gate后续准入。CLI提前初始化APP_ROOT。

批owner持久锁位置为 `output_root.parent/.locks/body-batch-<output basename SHA256>.mutex`，是output之外的唯一新增写入，仍在同一证据父目录内，避免预先创建canary输出目录。锁inode不能删除。

## Mac 精确提取与单次复验

由父任务接续现有Mac任务，不另起任务。使用已有私有仓库只提取本轮固定发布commit，不切换现役分支。填已有checkout和父任务收到的本轮40位SHA：

```bash
REPO=/path/to/existing/v4
CANDIDATE_COMMIT=REPLACE_WITH_PUBLISHED_40_CHAR_COMMIT
git -C "$REPO" fetch origin v5/announcement-capture-budget-20261009
git -C "$REPO" cat-file -e "$CANDIDATE_COMMIT^{commit}" || exit 1
CANDIDATE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/announcement-budget-fix.XXXXXX")"
git -C "$REPO" archive "$CANDIDATE_COMMIT" V5/handoff/announcement-budget-red-20261009 | tar -x -C "$CANDIDATE_DIR"
cd "$CANDIDATE_DIR/V5/handoff/announcement-budget-red-20261009" || exit 1
shasum -a 256 -c SHA256SUMS || exit 1
python3 -B -I tests/test_capture_budget_red.py > budget-validation.log 2>&1
BUDGET_RC=$?
python3 -B -I tests/test_provider_byte_accounting_red.py > provider-validation.log 2>&1
PROVIDER_RC=$?
python3 -B -I tests/test_cli_import_red.py > cli-validation.log 2>&1
CLI_RC=$?
cat budget-validation.log
cat provider-validation.log
cat cli-validation.log
printf 'commit=%s budget_exit=%s provider_exit=%s cli_exit=%s\n' "$CANDIDATE_COMMIT" "$BUDGET_RC" "$PROVIDER_RC" "$CLI_RC"
```

Python3.10+、POSIX/macOS、标准库；无PDF解析/安装要求。三个文件分别执行一次，不使用同进程discover。全部使用受控响应和临时目录，网络禁止；CLI测试仅允许自身定义的离线子进程。预计18+12+1通过，但没有云端运行或GREEN声明。返回固定commit、完整日志、退出码和环境，失败不自动重跑。

## 仍未放行

应用可证明响应体字节不等于TCP物理流量；opaque transport不能在内部read前限额；未知消耗须停止而非猜数。计数/许可仅同gate，owner仅同output，不是跨批全局上限；3600秒不包括可证明的强制终止，MaterialStore锁等待/存储收尾仍可能越过合作式截止。所有具体限制见REVIEW_FIX。

HTTP状态/Retry-After以及429/403/验证码全批停止/冷却仍是后续门禁，当前未知消耗stop不能替代它们；未部署、未真实采集，不提高凭据或访问权限，不绕过限制，不承诺性能倍数。原resume非中断续传，已发无终态仍协调处理，不删marker/换run绕过预算。
