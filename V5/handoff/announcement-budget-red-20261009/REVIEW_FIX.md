# 第二轮修复：真实字节计量及 CLI 初始化

状态：IMPLEMENTED_MAC_REVALIDATION_PENDING。本轮未在云端运行产品测试，未真实采集、集成或部署。

父任务报告 `cdab6fa8843d5007c216e83d0bff9e61aa01f7a8` 的实际 Mac RED：provider 2 PASS / 4 FAIL，exit 1，0.014 秒；已返回的 8388609 / 7 / 8388609 / 28 字节都记为 0。CLI 1 FAIL，exit 1，0.037 秒，干净入口在设置 app 搜索路径前导入 infrastructure 报 ModuleNotFoundError。清单通过、源码未变、旧18项未重跑。回执由父任务提供：`/Users/lexi/Documents/Codex/2026-10-08/task/announcement-review-cdab6fa/evidence/RESULT.md`，云端未读取该 Mac 文件。

## 实现边界

本轮完整候选必须按一个版本核对三文件：

- `candidate/ops/manager_announcement_body_batch.py`
- `candidate/v4/manager_research/announcement_source.py`
- `candidate/v4/manager_research/hkex_provider.py`（新加入，直接基于原 SOURCE_MANIFEST 对应的 pinned 同源文件）

`pinned/` 和原源清单均未改；生产文件前后 SHA 在 CANDIDATE_MANIFEST.json 中。原源仍固定 `0fd5eb374cb155232ed003d5fc4d0d3594252491`，本次父提交为 cdab6fa8。仅指定 handoff 子目录变化，未改主任务 manager/UI/workspace 文件。

真实默认 transport 在每次 read 返回后立即报告累计字节，不等 provider 返回。gate 用 request-id 保存 observed/reserved/settled，transport→provider→source 的相同累计值幂等，失败释放未用预留而不减已观察字节。真实 provider 对注入 transport 返回的 bytes 先入账，再执行原类型、URL、大小拒绝；这些原拒绝理由不改。无 budget 的既有 provider 调用保持兼容。

在默认 transport 的每次 read 前申请本请求可用额度：保留既有每响应预留，探测的第 +1 字节仅从尚未预留且未消费的总余额取得。无额度就拒绝读取，不能借其他在途请求的预留。64MiB 和其他原预算值不变。若总预算恰好只够响应上限，无法再安全读取一个字节区分 EOF/超限时，保守失败，不先超读再补账。

read/open 异常、opaque transport 异常或缺少可证明 bytes 的返回，标记 `BODY_BATCH_TRANSPORT_CONSUMPTION_UNKNOWN` 并停止该 gate 新准入；已有可证明字节保留，不把预留量伪装成已接收字节。其他已在途请求可报告已返回字节，但不能取得下一次 read 额度。URI、请求计数、截止、one-attempt 和来源门禁仍有效。`byte_accounting` 快照进入 URL receipt、progress、corpus/batch limits，明确 THIS_GATE、observed_response_bytes、unknown_consumption_requests、admission_stop_reason 和 physical_network_bytes_verified=false。

CLI 在模块载入时先设置 APP_ROOT，再允许公开入口导入 infrastructure；不依赖调用者 PYTHONPATH。canary 目录门禁及父目录批 owner 锁保持原候选设计。

## Mac 单次复验

原18项 + 原6项 provider + 原1项 CLI 的断言保留；新增6项：partial read 未知消耗阻止下一请求、opaque 异常/非法body不虚构字节、探测字节不能越过总预算、探测不能使用他人预留、已知 header 拒绝保持身份且不误停下一请求、opener 拒绝保持身份并标记未知。总计31个方法，新增subTest另有异常/非法body两个场景。

从本轮固定 commit 提取目录并验 SHA 后，各文件在独立 Python 进程执行一次。**不要 unittest discover 混在一个进程**：第一、二组安装网络/子进程禁止钩子，第三组有自己限定的离线子进程冒烟。

```bash
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
printf 'budget_exit=%s provider_exit=%s cli_exit=%s\n' "$BUDGET_RC" "$PROVIDER_RC" "$CLI_RC"
```

预计18+12+1通过，尚未运行，不宣称 GREEN。全部受控响应/假 opener、临时输出，无真实网络；第三组执行真实 main 到非法日期的本地参数校验即停止。失败或错误完整回传，不自动重跑。

## 限制和后续门禁

- 这里计的是应用 read/transport 返回且可证明的响应体字节，不含请求头、TLS、TCP缓存、重定向内部流量或失败read未返回的部分；不是64MiB物理网络硬上限。异常未知消耗以停止而非猜测处理。未知标记只在同一gate有效，不得以新run规避。
- 对 opaque 注入 transport，已返回body只能事后计量；若其违反额度，记录真实数量并关闭后续准入，不能追溯撤销已经收到的字节。默认 transport 才支持逐read预先限额。部署必须使用本轮三个候选组成的已核版本，不能把旧provider与新gate混用。为兼容旧测试/调用保留的 duck-typed provider fallback 没有真实transport读边界保证，不作为真实采集放行依据。
- 已在途的阻塞IO不能同步撤销；未知消耗标记阻止新准入和下一次read，不能收回已在执行的read。MaterialStore30秒锁等待及存储收尾也不证明3600秒完整流水线硬终止。
- 原3 workers/2000调用/64MiB/3600s/0.35s不变，许可/计数只协调同gate，批owner只协调同output，不是跨批全局上限；不承诺吞吐倍数。
- HTTPError结构化状态/Retry-After、429/403/验证码全批停止/冷却仍是明确后续工作；未知消耗stop不冒充HTTP协议门禁。未满足这些门禁前仍不放行真实采集。保持无部署、无凭据扩权、无代理轮转。
