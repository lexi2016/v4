# 公告请求预算与有界并发修复候选

状态：IMPLEMENTED_MAC_VALIDATION_PENDING。生产改动仅两份候选完整文件；未集成、部署、真实抓取或云端运行产品测试。保留原日期目录→全目录 body→审查导入路径，不改经理 reader/UI，也不增加采集器。

## 已收到的真实 RED

父任务报告现有 Mac 对 `2db7defbf6cde8663b0239f70a2993f65e1d4f61` 单次执行：3 PASS / 2 FAIL / 0 ERROR，exit 1，3.248 秒。长批预算下 HTTP timeout 实际 3600 秒、预期 20 秒；阻塞响应释放前同时进入 transport 实际 1、预期 3。源清单通过，13 个 pinned 文件与目标 R3 app/canonical 对应文件同 SHA；不是整个现役进程等价证明。

父任务提供的回执路径：`/Users/lexi/Documents/Codex/2026-10-08/task/announcement-budget-2db7def/evidence/RESULT.md`。本云端未读取该 Mac 文件，依据父任务回报开始实现。首轮 `-I` 忽略环境变量产生隔离目录 pycache，本轮命令改用 `-B -I`。

## 交付与文件边界

- 发布分支：`v5/announcement-capture-budget-20261009`，新增/修改仅在 `V5/handoff/announcement-budget-red-20261009/`。
- 初始 V5 基线：`945b89d7c3411a4913f50c4472514a61676c621e`；本次 parent 为上述 RED commit。
- 原源固定 `0fd5eb374cb155232ed003d5fc4d0d3594252491`。`SOURCE_MANIFEST.json` 保留逐文件原来源、manifest SHA、Git blob SHA1、SHA256；`pinned/` 原字节全部保留。
- `candidate/ops/manager_announcement_body_batch.py` 与 `candidate/v4/manager_research/announcement_source.py` 是唯一生产实现候选完整文件。完整文件**不可直接覆盖 manager/UI 分支**；集成前须核前像和 Mac 验收，差异可对照 pinned 原文件查看。
- `CANDIDATE_MANIFEST.json` 记录两文件前后 SHA、来源及 RED 依据。`SHA256SUMS` 校验整个交付包。
- `tests/test_capture_budget_red.py` 保留原五项断言，增加竞争/缓存/释放/节流/owner/transport 回归；先验证原源 SHA，再验证候选 SHA，加载两份候选，其余依赖仍使用 pinned 原源。未安装/覆盖现役模块。
- pinned 内 workspace_projection.py 仅为不变依赖副本；无主任务 workspace、manager_plan、UI 文件修改。无 tar.gz、公告数据、凭据、缓存或运行日志提交。

## 实现

1. 单请求 `timeout=min(provider._timeout, batch_remaining)`；剩余时间非正时拒绝发起，不把小于 1ms 的剩余时间向上取整。无 budget 时仍用 provider 原配置。
2. 保持 3 workers / 2000 请求 / 64MiB / 3600 秒 / 0.35 秒准入间隔。独立 BoundedSemaphore 限制最多 3 个在途；Condition 短锁只修改计数、request-id 租约和准入时刻；等待节流时释放短锁。HTTP/read、MaterialStore 写入和 hash 回读均在计数锁外，许可在 finally 释放。
3. 按 request-id 预留每响应上限，已结算字节加所有未结算预留不得超过总预算再准入。thread-local 绑定当前请求；重复结算同大小幂等，不同大小拒绝；重复 end 不释放他人的许可。失败释放尚未结算预留，已取得响应在时间/存储/hash 校验前计入物理字节，避免失败后漏计。缓存没有请求租约，不计物理请求或响应字节。
4. 每 worker 首次工作时创建独立 HkexOfficialProvider，并在该线程复用；共享 MaterialStore，避免共享 urllib opener。
5. 原 MaterialStore 按 source-key kernel_lock、SafeRoot 唯一临时文件保持不变。增加 URL 级 kernel lock 保护 attempt→receipt 状态转换，不串行不同 URL；原目录 art_code 唯一性校验不变。atomic_json 改 UUID 临时名并清理；progress/corpus 等聚合写入仍在主线程。
6. 批次持有排他 kernel lock，第二 owner 立即拒绝。锁位置在 `output_root.parent/.locks/body-batch-<output basename SHA256>.mutex`，是唯一新增的 output_root 外侧写入；放在同一证据父目录是为了不预先创建 canary output、破坏原“目录必须不存在”门禁。inode 持久保留，不删除锁文件。原 incomplete marker 与 NO_RETRY 规则不变。

## Mac 单次验收命令

由父任务接续现有 Mac 验收，不另起任务。用已有私有仓库仅获取并提取固定提交，**不切换运行分支**。把 `REPO` 改为已有 checkout，把 `CANDIDATE_COMMIT` 填本轮固定发布 SHA（不是 RED 旧 SHA）。

```bash
REPO=/path/to/existing/v4
CANDIDATE_COMMIT=REPLACE_WITH_PUBLISHED_40_CHAR_COMMIT
git -C "$REPO" fetch origin v5/announcement-capture-budget-20261009
git -C "$REPO" cat-file -e "$CANDIDATE_COMMIT^{commit}" || exit 1
CANDIDATE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/announcement-budget-fix.XXXXXX")"
git -C "$REPO" archive "$CANDIDATE_COMMIT" V5/handoff/announcement-budget-red-20261009 | tar -x -C "$CANDIDATE_DIR"
cd "$CANDIDATE_DIR/V5/handoff/announcement-budget-red-20261009" || exit 1
shasum -a 256 -c SHA256SUMS || exit 1
python3 -B -I tests/test_capture_budget_red.py > mac-validation.log 2>&1
TEST_RC=$?
cat mac-validation.log
printf 'candidate_commit=%s test_exit=%s\n' "$CANDIDATE_COMMIT" "$TEST_RC"
```

Python 3.10+、POSIX/macOS、标准库，无 PDF 解析调用，无需安装 PDF 依赖。测试用真实 capture/MaterialStore/SafeRoot 与受控 SourceResponse/可观测阻塞，所有材料/输出在测试临时目录；audit hook 禁止 socket、DNS、bind、子进程。部分 owner/provider 单元回归使用本地替身隔离实际 batch 入口；不调用服务或真实采集。预计 18 项通过，但**尚未运行，不宣称 GREEN**。请回传完整日志、退出码、Python/系统版本与固定 commit，错误/失败不要自动重跑。

覆盖：原 timeout/三请求重叠与第四请求阻挡、传输失败释放/回执、请求/截止/字节门禁；缓存零成本、相同 URL 阻塞后复用、竞争预留/重复结算/重复释放、hash 回读失败仍计字节、请求额度竞争、节流/截止等待、unique tmp、批 owner 排他及 canary 目录不预创建、每 worker provider 隔离、许可等待截止、低于 1ms 的 timeout。

## 限制与未执行

- 云端只做源码静态检查、清单和差异检查、发布后原字节读回；候选测试和完整产品 suite 均 NOT_RUN，Mac 候选 GREEN/集成/部署/自然运行均待完成。不能据此承诺提速倍数。
- 原预算以 provider 调用计数，不涵盖 urllib 重定向物理 hops；请求返回前 transport 异常/中断的部分响应字节不可观测，沿用原失败释放语义，不虚构已读取长度。收到完整响应之后才有准确字节。单次 socket timeout 加 cooperative deadline 并不是整个流/存储耗时的硬终止保证；本补丁不增加外部 watchdog。
- 在途许可覆盖收到响应后的 store/hash 收尾，最多 3 的约束比仅 HTTP 更保守。预留空间不足立即拒绝该次 URL，保留 one-attempt，而不是后台排队到预算回收后自动重试。
- 源 API 目录 unique art_code 原校验保留；并发写入测试不等于外部进程 force/rebind 行为证明。批 owner 仅协调采用同一新锁的候选调用，不假称可与旧实现共同运行。不能并行启用旧采集器和候选。
- 原代码没有专用 429/403/Retry-After 能力，本轮不新增或假称具备。HTTPError 仍可能经 public_error 丢失 status/Retry-After，envelope 不存 headers；后续需按父任务确认的 API 合同做白名单 Retry-After 冷却和 403/验证码停止回归，绝不绕过限制、代理轮转或扩大权限。未获官方并发额度，WORKERS=3 只是既有应用上限。
- 原 resume 不是中断续传；已发请求无终态仍需协调，不删 marker/开新 run 重置预算。date-catalog 与审查导入入口未改。
