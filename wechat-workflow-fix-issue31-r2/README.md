# Issue #31 — 公众号失败恢复与附录披露候选

本目录是 [Issue #31](https://github.com/lexi2016/v4/issues/31) 的限定修复交接。它以固定审查快照和已验收 R1 为输入；原来的两个目录保持冻结。本目录不代表实际 Mac 运行树，也不是部署或 issue 关闭回执。

**10.8 单篇恢复成功不等于缺陷修复。实际 Mac 验收完成前，issue 保持 open。**

## 固定输入

| 输入 | 用途 |
| --- | --- |
| [`bdb736bddd3c04e061eff0a43c47104523d144a0/wechat-workflow-review`](https://github.com/lexi2016/v4/tree/bdb736bddd3c04e061eff0a43c47104523d144a0/wechat-workflow-review) | 原审查快照；采集 adapter 和相关依赖的来源。 |
| [`e7dcf69d342a43d605521d551aafb4dc5c3911af/wechat-workflow-fix-r1`](https://github.com/lexi2016/v4/tree/e7dcf69d342a43d605521d551aafb4dc5c3911af/wechat-workflow-fix-r1) | 已验收 R1；先覆盖其六个精确文件，再进行本批修改。 |

下载输入通过 base64 还原原字节，逐项核对 Git blob SHA 和大小。R1 六文件另与原 `MAC_ACCEPTANCE.json` 的 SHA-256 对照。输入逐文件清单见 `INPUT_FILES.json`，基线摘要见 `INPUT_BASELINE.json`；本批每个变更文件的 before/after SHA 与换行统计见 `SOURCE_MANIFEST.json`。

## 已定位的故障

已确认的 adapter 顺序是：把同一个 `--out` 传给外部 collector，等待子程序执行结束，仅在返回码为零后验证身份和 artifact。离线 fixture 模拟先保存 BODY/图片、随后发生 OCR 错误，复现了非零退出跳过来源提交，以及后续 collector 可写入原输出根的问题。结合 issue 中的覆盖证据，可以定位 adapter 缺少失败隔离与来源提交保护；外部 collector 内部各文件的真实写入顺序仍需读取活动 Mac 源码确认。本批没有反复请求真实微信文章。

附录的原 A/BJ probe 在读取 receipt 后执行绑定校验。row_count 不匹配会在返回 probe 前抛出，调用方因此丢失已经读取的 receipt 汇总事实；失败 probe 没有进入缓存，又按代码重复读取。原 Markdown 同时包含固定的成功措辞。候选分别处理来源事实披露、行情可用性和失败缓存。

## 候选范围

- `wechat_article_fetch.py`：既有 adapter 内隔离每次 collector 输出；验证来源后再进行仅创建、可幂等恢复的提交；保留原始 attempt 证据；已有可信来源时复用缓存并报告缺失阶段。显式 saved HTML 权限需要与实际输入 SHA 绑定。
- `wechat_yesterday_performance.py`：保存已读取 receipt 的来源、状态、计数、coverage 和 authority；绑定失败仍拒绝价格；缓存成功及失败 probe；按实际状态生成 JSON/Markdown，保留全部上市线和逐行校验语义。
- 两个针对性测试文件，以及默认工作流中一段失败分层/恢复说明。未修改 runner、Vision、共享市场数据、R1 的归档/索引实现或 skill。

实际文件范围由 `SOURCE_MANIFEST.json` 和 `actual_diff.patch` 约束。`runtime.patch` 只包含两个运行脚本，测试与文档分别交付，避免整棵导出目录被误当成运行树更新。

## 如何审阅

1. 先读 `STATUS.json` 和独立 `evidence/reviewer/` 回执，确认结论绑定的文件 SHA。
2. 对照 `actual_diff.patch` 审查全部实际变更；`source/` 保存完整 after 文件，`before/` 保存本批对应的原字节。
3. 查看 `evidence/writer/` 中原始失败和修复后结果，以及根协调者的补丁正向/反向字节校验。失败日志保留，不用后来的绿色结果覆盖。
4. 按 `MAC_ACCEPTANCE_REQUIRED.md` 完成当前 Mac 实际入口、collector、prepare/Vision、一次有界恢复和冻结包/Drive 交付验收。

测试输入只使用临时合成 HTML、有效 PNG、Parquet 和 receipt。Issue 中 5137/5800、5261 与此前观察到的 5125 属于不同证据层；合成测试不构成对真实市场大表的独立复测。HK 缺前序 receipt 的输入缺口仍需如实披露。

## 状态边界

`IMPLEMENTED`、`TESTED`、`REVIEWED` 和 `BEHAVIOR_VERIFIED` 的精确范围以 `STATUS.json` 为准。当前固定快照缺少活动 Mac runner、外部 collector 和继承的顶层 AGENTS；历史 runner 只作上下文，没有混入候选。

本批候选只有一位 Luna Max Writer 和一位独立 Luna Max Reviewer。根协调者负责输入核对、交接材料、补丁字节验证和交付；材料契约检查不构成第二份产品代码验收。身份和最终 SHA 绑定见状态及复核回执。

不得把 Linux 离线通过、历史 R1 的 PASS、10.8 的恢复包，或本目录中的说明文件合并解释为本批 Mac 已通过。完整实际行为未执行的部分填写 `CANNOT_CONFIRM`。

本批维持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。不自动合并、不部署、不重启服务、不修改市场面板、scheduler/pointer、latest/正式池或 BUY gate，也不关闭 issue。
