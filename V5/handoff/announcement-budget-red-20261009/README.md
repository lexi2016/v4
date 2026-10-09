# 公告请求预算 / 并发：首批 RED 候选

状态：TEST_CANDIDATE_NOT_RUN。仅测试与固定源副本；无生产修复、部署或远端采集。已获授权将本测试候选提交到独立分支 `v5/announcement-capture-budget-20261009`，精确发布 commit/tree/blob 由父任务交接记录提供。父任务安排现有 Mac 独立验收。云端只做 Git 原文件读取、manifest SHA 校验和打包，没有导入产品模块或执行本测试。

## 固定来源及转移

- 原源 commit：`0fd5eb374cb155232ed003d5fc4d0d3594252491`。
- V5 主开发基线：`945b89d7c3411a4913f50c4472514a61676c621e`，目标主任务分支 `v5/module-isolation-20261008`；本候选没有移动其 HEAD。
- `SOURCE_MANIFEST.json`：逐文件原路径、Git blob SHA1、SHA256、来源 manifest 路径及 SHA256、原 source_root。
- `pinned/ops/*.py`：daily-chain bundle manifest 精确对应的两个原脚本，未改。
- `pinned/v4/manager_research/*.py` 与 `pinned/infrastructure/*.py`：同一固定提交的 API manifests 选取，按 snapshot_path 读取，再验证 manifest SHA。源文件虽去重存于 canonical 路径，选择依据是 API manifest，不是 main。该旧 API 快照与现役 R3 的依赖一致性尚须 Mac 核验，不能宣称现役等价。
- `tests/test_capture_budget_red.py`：新增测试完整文件，stdlib unittest，无 pytest 安装要求；`pinned/**/__init__.py` 是空测试 namespace shim，不是产品修改。
- 发布目录：`V5/handoff/announcement-budget-red-20261009/`，只新增测试、必要源文本和清单；不上传 tar.gz、日志或公告数据。全部源副本未改，暂无生产 patch，因为必须先取得实际 RED。
- 全部新增交付路径与 manager_plan、workspace、UI 修改不重叠。只读依赖副本包含 workspace_projection.py，字节未改，也不应替换主任务对应文件。

## Mac 精确命令（由父任务安排，不启动另一任务）

在现有 Mac 验收终端使用已有私有仓库 checkout 只读取出固定提交；只写新的临时目录，不切换现役分支、不读取现役材料或配置。`CANDIDATE_COMMIT` 必须填父任务收到的发布固定 SHA，不用移动分支代替：

```bash
REPO=/path/to/existing/v4
CANDIDATE_COMMIT=REPLACE_WITH_PUBLISHED_40_CHAR_COMMIT
 git -C "$REPO" fetch origin v5/announcement-capture-budget-20261009
 git -C "$REPO" cat-file -e "$CANDIDATE_COMMIT^{commit}"
CANDIDATE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/announcement-budget-red.XXXXXX")"
git -C "$REPO" archive "$CANDIDATE_COMMIT" V5/handoff/announcement-budget-red-20261009 | tar -x -C "$CANDIDATE_DIR"
cd "$CANDIDATE_DIR/V5/handoff/announcement-budget-red-20261009"
shasum -a 256 -c SHA256SUMS
PYTHONDONTWRITEBYTECODE=1 python3 -I tests/test_capture_budget_red.py > mac-red.log 2>&1
TEST_RC=$?
cat mac-red.log
printf 'candidate_commit=%s test_exit=%s\n' "$CANDIDATE_COMMIT" "$TEST_RC"
```

Python 3.10+，macOS/POSIX；只使用标准库。固定源内 PDF parser 会被导入，但不调用 PDF 解析，因此不需安装 PDF 依赖。测试使用真实 MaterialStore/SafeRoot 和真实 capture_eastmoney/_capture_url，替换最底层 HTTP transport 为受控 SourceResponse；audit hook 禁止 socket 连接、DNS、bind 和子进程。测试不调用 run_capture/main/daily owner、真实 URL 请求或服务入口。字符串 URL 仅用于原安全校验和 source-key，绝不连网。

预期首轮：5 个测试方法中 2 个 FAIL、3 个 PASS（预测，尚未观测），exit=1：

1. timeout 长预算子项预期 `[20.0]`，原源实际应为 `[3600.0]`；短剩余 0.25 秒及无 budget 子项应通过。
2. 三请求在释放任何 transport read 前同时进入，应为 3；原源预计只能观察到 1。控制线程等待有上限，finally 释放阻塞，结果还检查全部回执、请求数和实际字节总量。独立提交六个线程，同时检查第四个请求不得入场，防止修复后无限并发。
3. 失败请求终态回执及 reservation 释放、请求/截止预算阻止 transport、字节预留阻止下一次满额响应应通过。

导入、SHA、权限、超时 watchdog 等 ERROR 不算有效 RED。请返回 Mac Python/系统版本、发布 commit 与 SHA256SUMS 校验结果、完整 mac-red.log 和退出码。只有确认前两项以预期断言失败，才进入实现；不要把预测写成已失败。

## 已核实源码与下一轮实现约束

- daily `_capture` 215–274 仍是日期目录验证→全目录 body→证据回执；body batch 587–661 提交全部 rows，未换成前三入口抓取。
- gate 的 RLock 从 before_request 延伸到 _capture_url finally end_request，跨 HTTP/read、MaterialStore 写入和 hash 回读。`_owner`/单 `_reserved_bytes` 只适用于单在途；不能简单提前 release。
- timeout 源 521–523 有 budget 时只用 batch remainder；应约束 provider timeout 与剩余截止的最小值，并保留截止检查（该值是 transport/socket 超时，不等于已证明完整流读取硬截止）。
- 保留原 3 workers、2000 请求、64MiB、3600 秒、0.35 秒；3 不是官方额度，不承诺性能倍数。独立 semaphore 限制在途，节流只控制开始时间；短计数锁维护 request-id reservation/结算，finally 恰好释放；失败、缓存、终态日志不得错计或释放他人的预留。
- MaterialStore 145–195 按 source-key kernel_lock；SafeRoot 120–155 用 UUID 临时名/原子替换，182–215 用独立 fd flock。不同 key 可并行；相同 key 的 fetch 被序列化，但后续 readback 不在 fetch 锁内，仍须保证 URL/art_code 唯一派发，防止 force/rebind 竞争。仅静态核实，Mac 并发压力证明 NOT_RUN。
- body-batch atomic_json 48–54 固定 `.tmp`，batch marker 存在检查与写入不是原子 owner 锁；并发实现须保留单 writer/唯一临时名和批 owner 排他，不能只靠 MaterialStore 锁。当前 progress 在 as_completed 主线程写，勿改为 worker 共写。
- 原 run_capture 共享 provider；其 urllib opener 并发安全未证明。后续使用每 worker transport/provider，材料仓库共享；本测试使用每次调用独立受控 provider，不证明真实 opener 安全。
- 原实现没有专用 429/403/Retry-After 能力。HTTPError 的 public_error 丢失状态及 Retry-After，envelope 不保存 headers。后续若加冷却，仅白名单保存 Retry-After（秒数/HTTP-date），不保存 cookie/token；403/验证码停止；429/503 冷却且 one-attempt 可保持，不用新 run 重置预算，不将 plan 600 秒退避冒充 HTTP 退避。API 合同/许可由父任务核实，此包不增加远端访问方式。
- 原 resume 非中断续传；batch_attempt 无终态拒绝重跑，URL/article marker 无终态为 INDETERMINATE_NO_RETRY。保留完整成功页复用；已发无终态协调处理，不删 marker。

## 最小缺项

1. 现有 Mac 上实际 RED 结果；这是开始生产实现的前置条件。
2. Mac 对 API manifest 依赖与目标实际 app 来源的核对（此包是固定候选快照）。
3. GREEN 前还需追加并发 reservation 结算/重复释放、缓存零请求、节流与截止等待、MaterialStore 同 key/不同 key、重复 URL/art_code、批 owner 和唯一 tmp 回归。这首批不是完整并发安全证明。
4. 真实 transport headers/停止冷却合同及准确集成路径由父任务确认后另做失败测试；本轮不实现重试。

仓库与 Mac 上位规则已分清：读取固定 checkout 的 AGENTS.md 与 canonical/AGENTS.md；云端 `/workspace/.agents` 为空，checkout 无本地 skills；规则引用的 `/Users/lexi/.../AGENTS.md` 云端不可用，Mac 验收需读取。首轮遵守“先不推任何分支”；本轮根据父任务后续明确授权，仅发布指定独立分支及指定新增目录。已读取 test-driven-development/SKILL.md；其补充 writing-good-tests.md 资源读取失败。用户要求的“等待实际 RED 才实现”本身已经足够决定本轮停止于测试交付，无需另行授权。
