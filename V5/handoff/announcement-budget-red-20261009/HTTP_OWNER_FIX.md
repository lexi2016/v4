# HTTP 修复与私有 owner：待 Mac 验收

## 依据与具体变化

父任务返回 8124c9f6cb35ca4385c2e73bcd55482ee8a7bfa8 的实际 HTTP RED：1 PASS / 8 FAIL / 0 ERROR，exit 1。此前 79fcdf81 的 31 项回归已由父任务报告通过。本轮未在云端执行任何产品测试。

- provider 对返回响应及抛出的 HTTPError 识别 403/429/503；403 和明确 HTML 验证码标记 STOP；429/503 的有效 Retry-After 秒数或 HTTP 日期记录 STOP_AND_COOLDOWN；无效值 STOP。没有自动重试、睡眠后恢复、代理轮转或验证码绕过。HTTPError 关闭资源，不读取其错误页。
- 验证码识别限明确 HTML input/title/recaptcha/h-captcha 标记，不宣称覆盖全部安全挑战；普通 JSON 正文出现 captcha 不应停止。日志不存响应正文/错误头；HTTP 日期规范化后记录，秒数字符串保留。
- gate 在短计数锁内登记停止策略、唤醒等待者并阻止后续准入；已准入的请求可完成，最多 3 个并发槽，不宣称瞬间取消所有网络 I/O。未知消耗继续停止，已知 read 字节继续累计。
- 保持原 3 workers、2000 调用、64 MiB、3600 秒、0.35 秒间隔。timeout=min(provider 配置, gate 剩余秒数)。并发槽与准入间隔独立。3 不是官方许可额度；统计为可观察响应字节，不是物理网络硬上限。
- 新私有 owner 在进程内绑定原 CLI 与原 catalog/import 模块，无 API 服务或 8873 POST。date_catalog 和全部 body 共用同一 gate；复用原 prepare/build-reviewed/register-handoff/import/readback 的原函数及校验，不生成审查结论。
- owner 要求全新专用状态目录、显式 V4 禁写根、固定 app SHA 身份、内核排他锁。请求前记录 STARTED；HTTP/未知消耗立即落盘；崩溃、失败、阻断或同日重复运行均拒绝换 run 清零。冷却到期仍不自动重开，需另行审查；无清除命令。只在上一日期 FINISHED 且无停止策略时允许新日期。

MaterialStore 沿用已核原样源码：抓取 transport 不持有全局存储锁，原索引与 blob 写入保护保留；body 候选另以每 URL 锁防同键竞争，每 worker 独立 provider/opener，汇总由主线程写入。新增 owner 的状态写入使用原 SafeRoot 与原 Store。原调用链、来源 SHA 和 all-rows 语义保留。

## Mac 单次离线验收

接续父任务已有 Mac 独立验收，不另建任务。不把目录覆盖现役 app。先转移本完整 handoff 至新目录，再在该目录执行下列命令。每文件单独进程，避免 audit hook 与 CLI subprocess 用例相互影响。各测试只使用受控假响应/阻塞；新增 owner 测试安装拒绝网络及 subprocess 的 audit hook。

```bash
shasum -a 256 -c SHA256SUMS || exit 1
python3 -B -I tests/test_capture_budget_red.py > budget-validation.log 2>&1
BUDGET_RC=$?
python3 -B -I tests/test_provider_byte_accounting_red.py > provider-validation.log 2>&1
PROVIDER_RC=$?
python3 -B -I tests/test_cli_import_red.py > cli-validation.log 2>&1
CLI_RC=$?
python3 -B -I tests/test_http_policy_red.py > http-validation.log 2>&1
HTTP_RC=$?
python3 -B -I tests/test_v5_private_owner.py > owner-validation.log 2>&1
OWNER_RC=$?
cat budget-validation.log provider-validation.log cli-validation.log http-validation.log owner-validation.log
printf 'budget=%s provider=%s cli=%s http=%s owner=%s\n' "$BUDGET_RC" "$PROVIDER_RC" "$CLI_RC" "$HTTP_RC" "$OWNER_RC"
test "$BUDGET_RC/$PROVIDER_RC/$CLI_RC/$HTTP_RC/$OWNER_RC" = '0/0/0/0/0'
```

预期用例数量分别 18、12、1、9、7，共 47；不是现有验收结果。owner 合成目录为 21 家/21 条，20+1+空终页共 3 页，加全部 21 条正文，共 24 次假响应；沿用 0.35 秒节流，约需 8 秒。断言共享请求/字节预算、全部正文、持久停止、V4 禁写与未登记审查材料拒绝导入。临时路径规范化以适配 Mac /var 符号链接。

只组装候选、不执行产品的命令：

```bash
python3 -B -I tools/assemble_owner_app.py --out /absolute/new/private/app
```

输出目录必须不存在；工具根据三份清单验证再复制，生成 V5_OWNER_APP_MANIFEST.json，不导入产品模块。app SHA 与状态根身份绑定，不能直接换版复用已有根。

## GREEN 后由父任务安排的真实阶段

以下是接口形状，不是本轮可执行的线上验收指令。先由父任务确认 47 项实际结果、独立审查与 API/页面使用政策，再安排合法数据获取。所有路径使用已解析的绝对真实路径；PRIVATE_PARENT 为已有 V5 专用父目录，PRIVATE_STATE 为其下不存在的新目录，V4_ROOT 为实际 V4 状态根（多个根重复 --forbid-root）。

```bash
python3 -B -I "$PRIVATE_APP/ops/run_v5_private_announcement.py" \
  --root "$PRIVATE_STATE" --private-parent "$PRIVATE_PARENT" \
  --forbid-root "$V4_ROOT" --initialize
python3 -B -I "$PRIVATE_APP/ops/run_v5_private_announcement.py" \
  --root "$PRIVATE_STATE" --private-parent "$PRIVATE_PARENT" \
  --forbid-root "$V4_ROOT" --allow-network-capture \
  capture --target-date 20261009 --publication-date 2026-10-08
```

后续原 prepare/build-reviewed/register-handoff/import/readback 子命令使用同一 owner 前缀（去除网络 flag），原输入必须在 PRIVATE_STATE 内；由原 readers/独立 reviewer 提供真实审查产物。禁止改用现役 API、手工伪造审核通过或把 PRIVATE_STATE 指向 V4。

## 剩余缺项和边界

1. 本轮 Mac 47 项实际结果尚缺。cloud_product_tests=NOT_RUN。
2. 新 owner 的成功审查导入/readback 尚无本轮端到端 GREEN；目前新增测试只覆盖未登记输入拒绝。不宣称完整审查导入验收已完成。
3. T20261009/P20261008 真实完整目录、正文与 reader/reviewer 产物未采集，不能交付今日选股结论。
4. HTTP 策略是失败关闭候选，不构成来源服务抓取许可或官方并发额度确认。政策核对由父任务负责。
5. 新 owner 的持久状态范围是一个显式私有根；不同根之间没有全局限额协调。app/状态迁移与解除阻断不在本候选中。

原文件 SHA 详见 SOURCE_MANIFEST.json；原成功链依赖详见 OWNER_SOURCE_MANIFEST.json / OWNER_DEPENDENCIES.json；四个候选完整文件 SHA 与前像详见 CANDIDATE_MANIFEST.json。无 manager/UI 主任务文件重叠。
