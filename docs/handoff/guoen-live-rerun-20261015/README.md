# 国恩科技两条公告：实际链路重跑与独立复核

2026-10-15。本轮将已验收修复加载到原公告模型链路，使用两条原始公告各重新生成一次；没有改写旧答案或为了通过审核调整新结论。

## 结果

| 公告 | 新模型判断 | 独立复核 |
| --- | --- | --- |
| 收购交割（AN202610141830470256） | SELECTED_EVENT / OPERATING_EVENT / POSITIVE | 交割、80%持股及并表事实支持；正向经营或经济收益判断缺少依据，引用也不完整，整体 FAIL |
| 九个月业绩预告（AN202610141830469348） | SELECTED_PERFORMANCE / PERFORMANCE_RESEARCH / POSITIVE | 判断、数字、业务解释和未审计限定正确；利润区间及同比增幅引用不完整，整体 FAIL |

收购公告未给出标的业务、财务和交易总价，不能由“并表”直接推出经济方向为正。新答案虽主动披露这些资料缺口，仍保留 POSITIVE 及经营催化结论。引用方面，U000009 只有“本公司”，未独立覆盖断言中的完整发行人名称；理由中的首期付款和工商登记来自 U000008，未在证据数组单独引用。

业绩公告的归母净利润预计 95,000–110,000 万元、同比增长 54.45%–78.84%；扣非净利润预计 92,000–107,000 万元、同比增长 54.14%–79.27%；EPS 2.20–2.55 元，均有原文支持。但新答案仍只用 U000016 引证第一组完整区间及增幅，缺 U000017/U000019；只用 U000023 引证第二组，缺 U000024/U000026。EPS 的 U000028 引用完整。

因此：两条机械校验通过，完整语义与引用质量为 0/2 通过。未发布为正式选股结果。

## 实际运行

- 原入口：pipeline_canary/evidence/recent-day-20261014/recent_day_freeze.py；复用原始队列、投影和本地 oMLX 请求链，不建第二 producer。
- 为避免误跑旧 172 条，增加显式两条专用候选类型。原 172 条候选和队列保留。
- run_id：guoen-live-rerun-20261015-f6891bd10254b66b3cb2d72a。
- queue_id：recent-day-guoen-20261015-b9418cf8660de7f303d0。
- 主控显式传入 candidate-root，在可见浏览器确认仅两条后点击 Start。第一次 MODEL_NOT_READY 时零 attempt；通过现有管理接口加载同一个 Flash 后再次点击。
- 请求及响应均为 qwen3_8_flash_next，temperature=0、enable_thinking=false；两条各 1 request / 1 attempt，无额外模型测试、重试或答案修订。
- 2026-10-15 11:34:08.431–11:35:07.234 UTC（北京时间 19:34:08–19:35:07）。收购生成 29.981 秒、首内容 14.927 秒；业绩生成 28.817 秒、首内容 5.071 秒。
- 请求使用新固定事实账本及 canonical validator；精确 source、parser、validator、raw、projection 和 queue SHA 见 summary.json。
- 本轮临时入口为 127.0.0.1:60922，PID 82361；完成并保存截图后仅关闭此临时入口。未重启 V4 8873、oMLX 8802 或 US/HK 61318，未改变 27B、idle TTL、采样或模型权重。

## 验收与证据边界

独立 Reviewer：simple_review_resume（Luna Max，与 Writer 身份不同）。入口 actual diff 和 6 项 focused tests 独立 PASS；前轮 parser/guard 的 33 项已验收测试复用，未重复跑。模型两条新 raw、原文及投影已逐项复核，REVIEWED=PASS 表示已审，整体 BEHAVIOR_VERIFIED=FAIL / semantic_acceptance=FAIL 表示未达到答案质量标准。

测试命令（pipeline_canary 根）：

PYTHONDONTWRITEBYTECODE=1 /Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python -m unittest discover -s evidence/recent-day-20261014 -p 'test_guoen_targeted_rerun.py' -v

保留两个 provenance 缺口，不据此改写任何输出：

1. 当前磁盘、新候选和加载回执的 runtime settings SHA 为 e05af04a…b22a99，stream receipts 却记录旧值 836ee204…65f08ea；请求时采用的完整全局设置身份 CANNOT_CONFIRM。
2. stream receipt 的 schema SHA 与候选不同，其含义 CANNOT_CONFIRM；但独立规范化实际请求体的 schema SHA 与候选一致。加载回执的创建时间晚于第一条请求，缺精确 load 动作时间；主控在浏览器流程中观测到先 MODEL_NOT_READY、后 READY 再 Start，Reviewer 无法独立证实精确加载时刻。

代码改动和运行摘要同步私有仓库，原公告正文、旧/新模型回答、队列和凭证留本机。GitHub 源码为交接快照，不是新运行根；V4 8873 的自然定时链路不在本轮验收范围。

RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。
