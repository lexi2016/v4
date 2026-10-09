# 真实 transport 字节盲区与独立 CLI：第二轮 RED 候选

本轮状态 TEST_CANDIDATE_NOT_RUN；生产 candidate/pinned 字节相对 `e4fc9225d31f8aa4d57538e29d5f575e81178cfa` 全部不变。父任务报告该 commit 在 Mac 单次 18 PASS / 0 FAIL / ERROR / SKIP，exit 0，1.678 秒。这只证明第一轮覆盖路径，不证明完整字节预算安全，也未集成部署。

## 审查边界

字节盲区是继承的失败语义，不是本次并发修复新增回归；CLI 初始化顺序则是新回归。第一轮18项离线通过有效，但不证明所有入口或真实采集安全。64MiB只可称应用预算目标，不能称物理网络硬上限。计数锁和许可只协调同一gate，owner只协调同一output，不是跨批全局上限；MaterialStore原30秒锁等待及存储收尾也不受3600秒硬终止保证。已知read返回字节应保留；未知消耗须明确标记并停止后续准入，不能虚构长度。

真实采集门禁仍缺HTTPError结构化状态/Retry-After、429/403/验证码全批停止或冷却；作为明确后续项，本輪不实现、不无限扩范围，绝不因此放行真实采集。

## 静态核实

- candidate announcement_source 在 `_request_eastmoney_hk` 返回后才 `record_transport_response`。
- pinned hkex_provider 的真实 `_request_eastmoney_hk` 在返回前拒绝非法 response/final URL 和 >8MiB body。
- `_default_eastmoney_hk_transport` 在每次 read 后更新局部 total；读到上限+1 就抛错，已读 body 不返回。若后续 read 抛 OSError，前面成功读取的字节也被 public_error 包装掩盖。以上路径进入 finally 释放 reservation，现有总字节却保持 0。
- default transport 的 Content-Length 拒绝发生在 read 前，正确实收应为 0，不能简单把所有错误都算整个预留量或宣称预留量是已读取字节。
- candidate run_capture 首先 `from infrastructure.owned_io import SafeRoot`，其调用的 `_run_capture_owned` 后面才由 imports() 设置 APP_ROOT。直接 ops CLI 没有 app 根路径就先报 ModuleNotFoundError；旧测试预插 pinned 路径遮蔽此问题。

## 新测试（未运行）

`tests/test_provider_byte_accounting_red.py`：仅运行新增六项，不重复旧18项。导入旧 harness 以复用严格源 SHA 验证与网络/子进程禁止钩子，但使用真实 HkexOfficialProvider。

1. 真实 default transport，通过受控 opener/response 返回上限+1 字节；期望账上 8388609，当前预计 0 → FAIL。
2. 真实 default transport 成功读取7字节后下次read抛错；期望7，当前预计0 → FAIL。
3. 真实 provider 接收受控 transport 的 >8MiB SourceResponse 再拒绝；期望8388609，当前预计0 → FAIL。
4. 真实 provider 接收带非法 final_url 的 SourceResponse；必须拒绝且计已返回body，当前预计0 → FAIL。
5. 真实 default transport 因 Content-Length 超限在read前拒绝，计0 → 预期PASS。
6. 真实 default transport 成功读取23字节，计恰好23，无重复计数 → 预期PASS。

默认 transport 测试不替换请求构造、read循环或拒绝逻辑，仅替换 build_opener 返回的对象；read(size) 遵守传入大小，逐次记录实际返回字节，所有内容为内存重复字符，不含公告数据。非法 URL 是未请求的测试标签。provider 级替身显式提供已返回的body；这与真实网络内核流量不是同一指标。

`tests/test_cli_import_red.py`：只运行一个新测试。不得导入旧 harness，避免掩盖路径问题；用隔离临时 app 树复制候选 ops 脚本及真实 owned_io，在无PYTHONPATH/PYTHONHOME的 `python -B -I` 子进程中模拟直接脚本的 ops sys.path，通过runpy执行真正 main。故意传 INVALID 日期，期望在本地校验报 BODY_BATCH_TARGET_DATE_INVALID，当前预计 ModuleNotFoundError → FAIL。子进程有独立网络/进一步子进程禁止钩子，不能采集；父进程唯一允许子进程就是此固定离线CLI冒烟。

预期本轮合计 **2 PASS / 5 FAIL / 0 ERROR**；只是预测，不是已观测。ERROR、fixture错误或network deny触发不算有效RED。本轮不重跑前18项。

## Mac 单次命令

父任务在现有 Mac 任务按 README 从本轮固定 commit 提取本目录后执行，避免 unittest discover 导致旧18项重跑：

```bash
shasum -a 256 -c SHA256SUMS || exit 1
python3 -B -I tests/test_provider_byte_accounting_red.py > provider-red.log 2>&1
PROVIDER_RC=$?
python3 -B -I tests/test_cli_import_red.py > cli-red.log 2>&1
CLI_RC=$?
cat provider-red.log
cat cli-red.log
printf 'provider_exit=%s cli_exit=%s\n' "$PROVIDER_RC" "$CLI_RC"
```

两条测试命令各执行一次，预期各exit1；回传固定commit、完整日志、退出码与环境信息，不自动重试。

## 最小修复设计（尚未实现；等待真实RED及后续审查）

- 需要把计量边界下移到真实 transport 的每次成功read，失败前也传递累计值。调用级 observer/计量上下文必须只绑定当前 request-id，不能使用跨worker全局可变计数。源层及provider层结算应对同一请求按累计值幂等，避免双算。
- 真实 provider 对注入transport已经返回的字节，应先计量再做URL/大小拒绝；非bytes/缺失body只报告已知值，不臆造长度。保留原拒绝、不把超限改成功。
- 默认 read 的上限+1 探测也必须在可用总预算内预留。修复须在read之前给出可消耗额度，包括探测字节；预算不足就停止读取/失败，不能先超读再补账、扩大64MiB或挤占其他在途reservation。必要时边界响应保守失败；需补“剩余仅上限/不足一探测字节”的预算竞争回归再决定具体接口。
- 抛错前的已读字节保留入账，未消费预留可释放，重复finally不得消掉已消费量。部分IO在异常发生的同一次read内未返回的字节仍不能精确观测，需区分应用read返回字节与TCP实际流量；未知消耗需明确标记并停止该gate后续准入。
- CLI 用最小模块搜索路径初始化在首次 infrastructure import 前建立 APP_ROOT；不靠修改用户环境、扩大权限或额外启动collector。复用同一根路径逻辑，保持原日期/owner/NO_RETRY门禁。
- 以上将可能增加第三份 hkex_provider.py 候选；须从已有同源 manifest 对应的固定pinned字节起步。此次不改任何生产文件，也不提前把设计当实现。HTTP状态/冷却/权限合同仍由父任务协调，未部署。
