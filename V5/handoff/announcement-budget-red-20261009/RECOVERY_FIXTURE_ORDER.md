# 780 Mac 13 PASS / 2 FAIL：受控 fixture 请求顺序修复候选

基线远端 7800792d03cee803ab62431154c7880f3e7a985e。父任务报告恢复测试 15 项实际 13 PASS / 2 FAIL，exit1：两处期望 failed_articles=1 得到 2。原 55 项本轮未复跑，真实恢复 NOT_RUN，旧 7536 SHA 未变/BLOCKED。

静态逐项核对第一条假正文：art_code 与目录相同；title 为同一个 rows 值；notice_date 同一天；page_size 为整数 1；security.market_uni=116、stock=00001 与目录来源一致；notice_content 非空。未发现需要放宽正文解析合同的理由。

代码存在可解释额外失败的 fixture 顺序竞争：两个正文 worker 同时提交，gate 的 Condition 和节流不保证 FIFO。第二条 transport 的 OSError 若先发生，会设置全 gate UNKNOWN 停止准入；第一条尚未准入时也会失败。目录顺序/ThreadPoolExecutor 提交顺序不能证明实际请求顺序。Mac 当次 article_receipts/request receipt 的具体 error_code 仍待只读回传，故这只是静态确认的竞争缺陷，不能冒充已读取到的运行根因。

本轮仅改测试 fixture：第二条假 transport 等待第一条有效响应已构造的 threading.Event，最多 10 秒，然后才抛原 SYNTHETIC_UNKNOWN_CONSUMPTION。第一条已准入且为单页，此后无需新的 gate 准入。未知消耗仍真实触发原 gate，后续保持 BLOCKED；未改 workers、预算、正文解析或生产代码，也未将失败预期改为 2。

保留两处 failed_articles=1 断言，并加强逐条状态：AN2026100800000001 必须 COMPLETE_CONTENT_API_BODY，AN2026100800000002 必须 BODY_CAPTURE_FAILED。增加 trace 顺序断言。失败输出保留 art_code/status/error_code 等 article_receipts 和 transport trace，避免临时目录清理后只剩 2 != 1。事件超时同样保留诊断，不静默放过。

云端仅 AST、SHA、字节差分检查，产品测试 NOT_RUN。测试总数不变：原 55 + 恢复 15。Mac 现有任务提取固定新提交后单次执行：

```bash
shasum -a 256 -c SHA256SUMS || exit 1
python3 -B -I tests/test_offline_evidence_recovery.py > recovery-fixture-validation.log 2>&1
RC=$?
cat recovery-fixture-validation.log
printf 'recovery_fixture=%s\n' "$RC"
test "$RC" -eq 0
```

若仍失败，读取新增的逐条错误和 trace 再定位；禁止改期望数或跳过原终态校验。真实离线恢复继续暂停，392 条阅读与独立审查未被本修复完成。
