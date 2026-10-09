# 三项静态审查修复，待 Mac 验收

基线 db871765422a03e7b74fb467052eaaa25c8ec8ea。只处理父任务指出的三项问题；无业务算法变化。云端仅静态读取、AST、SHA 和 git 核验，没有产品测试或真实请求。原 47 项测试文件逐字保留，新写 8 项负例后实现修复；尚无这些新用例的 Mac RED/GREEN。

## 派生输出隔离

已核实原 CLI `_capture` 在 `announcement_agent_runs/<run>/evidence` 普通 mkdir，随后普通 Path.open；只有根和 CLI 参数检查无法覆盖内部链接。

owner 在独占锁内、begin_capture 和来源请求之前检查完整私有状态树，遇到任意内部目录/文件符号链接立即 V5_OWNER_SYMLINK_FORBIDDEN，不删除或替换链接。原 CLI 新增两个默认行为不变的 IO 接口 `_mkdir`、`_write_new`，所有派生输出写入都使用它们；owner 执行期间将其绑定现有 SafeRoot。body 的完整目录输出 mkdir/atomic_json 同样绑定 SafeRoot。SafeRoot 使用逐层目录描述符和 O_NOFOLLOW，输出文件 require_absent/安全原子发布，故不只依靠容易过时的预检查。绑定在 finally 恢复；私有 owner 不允许 canary/resume 入口。

原 pinned 文件、Store、MaterialStore、workspace 依赖均不变。新增 candidate/ops/run_manager_daily_announcement.py 是原 CLI 的最小 IO 接缝完整文件，需与 owner 一起组装；不能仅覆盖 owner。现有文件冲突仍拒绝，无删除原文件或更改 V4 的处理。

新负例覆盖：既有内部派生目录链接；嵌套产物文件链接；预检查之后创建目录链接再调用 CLI mkdir；预检查之后创建产物链接再调用 CLI writer。均要求拒绝、链接保留、V4 sentinel 不变；前两项还要求拒绝发生在 capture 和 policy 写入之前。已有 21 条完整目录用例用于正向回归。

## 返回式超大 429

问题限返回 SourceResponse 的 transport：旧顺序在 8 MiB+1 正文上先抛大小错误，漏记 429 策略；标准 urllib HTTPError 分支此前已登记策略。

保留精确累计 read/returned bytes，验证 response 类型及来源 URL 后先登记 HTTP/Retry-After，再做正文大小拒绝。8 MiB+1、低于 64 MiB 的返回式 429 新用例要求准确字节数、120 秒冷却、后续 URL 不再请求、无缓存和租约释放。标准 HTTPError 行为不变，无真实请求。

## 历史预算合同

transport_policy.json 现在带 history，完整保存前次状态、日期、计数、停止原因和当前运行快照。任何既有记录非 FINISHED 或有 stop 都阻断新运行；任何已用 target 或 publication 都拒绝复用，不只最近的精确组合。不同且从未使用过的两个日期、全部历史 FINISHED 且无 stop 才能开始独立日期批次。失败/STARTED/冷却停止不得通过改日期解除。没有清空历史、删除材料或自动恢复功能。

新负例覆盖同 target 换 publication、完成另一天后返回旧 target、同 publication 换 target，并核对两次 FINISHED 历史保留。历史和预算限同一明确私有根；不宣称多个独立根间全局协调。升级后的 app SHA 身份不同，不应直接覆盖已有状态根身份来绕过检查；实际状态迁移需父任务另行审核。

## Mac 命令

在固定本次 commit 提取的完整 handoff 目录，沿用 HTTP_OWNER_FIX.md 的五个独立进程命令验证原 47 项，再运行：

```bash
python3 -B -I tests/test_owner_path_review.py > owner-path-review.log 2>&1
OWNER_PATH_RC=$?
python3 -B -I tests/test_oversized_http_review.py > oversized-http-review.log 2>&1
OVERSIZED_HTTP_RC=$?
cat owner-path-review.log oversized-http-review.log
printf 'owner_path=%s oversized_http=%s\n' "$OWNER_PATH_RC" "$OVERSIZED_HTTP_RC"
test "$OWNER_PATH_RC/$OVERSIZED_HTTP_RC" = '0/0'
```

新增预期 7+1 项，总计 55。请返回每文件 PASS/FAIL/ERROR、exit 和日志，不在同一进程 discover 所有文件。全部实际通过且独立审核完成前不启动真实 capture。成功审查导入/readback 的原缺项仍未关闭。
