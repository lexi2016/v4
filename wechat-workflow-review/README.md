# 微信公众号工作流代码审查快照

生成日期：2026-09-29。此目录是待审查的源码与测试副本，不是 Git 仓库；未初始化 Git、未上传或发布。目标仓库及分支/PR 操作由主控另行处理。

## 分工与数据边界

- Drive 按文章保存冻结资料包、Chat 回传和本地复核镜像：`01_资料包`、`02_Chat回传`、`03_本地复核`。Drive 的 metadata、原字节、SHA、Chat 阅读、结构和语义各自留证。此快照不提供 Drive 客户端或自动传输能力，也不含私有 Drive ID。
- GitHub 用于审查源码、文档、测试和可复现修复。文章 BODY/OCR、原图、冻结 ZIP、真实 `report.md`、`coverage.csv`、`mentions.csv`、`unmapped.csv`、`summary.json`、导入/上传 receipt 和真实行情/面板数据留在经授权的 Drive/本地文章目录，不进入仓库或 issue。
- Chat 负责研究；用户提交 Chat 结果；Codex 按 `package_id/input_digest/return_id` 回收原字节、校验并完成本地归档/Drive 镜像。代码快照不能证明某文章已经抓取、OCR、研究、归档或镜像。
- 默认路线读 WORKFLOW 第 0 节：本地复用 → 缺项采集/OCR → 冻结包 → Drive 交接 → Chat 研究 → 原字节回收与本地校验 → Drive 镜像 → 用户已授权时登记 V4 Stage A 引用并按 exact 文章日检查 API/UI。工作流后续章节里的 V3 流程仅在显式选择 `LEGACY_FULL_RESEARCH` 时启用。

## 研究产物合同

完整报告保持九章：结论先行、事件链地图、高价值事件卡、公司横向比较、A/BJ 优先级、HK 优先级、反证降级与遗漏、决定性验证、来源/边界摘要。五个 Chat 回传原文件为 `report.md`、`coverage.csv`、`mentions.csv`、`unmapped.csv`、`summary.json`。新冻结包把 `review_contract_version=wechat-event-dispositions-v1` 绑定到 manifest/input_digest，要求每个 coverage `EVENT` 来源在 summary 中对应一个 `PROMOTE/HOLD/REJECT/CANNOT_CONFIRM`；结构闭合不等于语义正确。

前篇表现附录是包外的单日描述性价格变动。它覆盖可信前篇 `mentions.csv` 的全部唯一 `(market, listing_code)`，绑定前篇和本篇身份、观察日、运行时指针、行情 receipt 和市场日历；不进入本篇冻结 ZIP 或 `input_digest`，不称为策略收益。

所有研究状态保持 `RESEARCH_ONLY / WATCH_ONLY / NO_BUY_GATE`，并要求 `production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。V4 Stage A 只登记既有归档引用并只读展示；不构建候选、不评分、不发布正式池、不更新 BUY gate。

## 目录映射

`source/wechat/` 映射当前公众号工作目录；`source/skill/` 收录 Feed、Method、Chokepoint 三项技能及默认流程必要参考；`source/v4_app/` 只收录 Stage A 登记器、归档读取器、只读 API 子路由、展示面板/API 客户端及其测试。复制列表和逐文件源/导出 SHA 在 `FILE_MAP_AND_SHA256.json`。

源文件内容仅做导出副本脱敏：macOS 用户目录、Windows 用户目录与私有 Drive root 均替换为占位符；V4 原 Stage A 测试依赖一篇真实报告和 IMPORT_RECEIPT，本快照未复制它们，改用合成 report/receipt，并把测试日期、标题、摘要 SHA 改成合成值。原来源 SHA 与导出 SHA 均保留在文件映射中；导出副本不再与被脱敏源文件逐字节相同。

有意不包括：真实文章/图片/OCR/回传/收据/行情；V4 全仓库和 legacy V3 系统；活动调度器、运行配置、服务/任务计划；外部 `wechat-research-intake` collector；V4 完整 API 主路由的全部依赖、应用路由组装和完整 Vue 页面依赖。`wechat_article_fetch.py` 需要外部 collector，不能在本快照内完成真实采集。macOS Vision/Swift OCR 依赖宿主能力，未执行真实 OCR。

## 离线测试

从本目录的 `source/wechat/` 运行：

```bash
PYTHONPATH=scripts python3 -m pytest -q \
  tests/test_review_wechat_boundaries.py \
  tests/test_wechat_prepare_ocr_manifest.py \
  tests/test_wechat_macos_ocr_cache.py \
  tests/test_wechat_chat_handoff.py \
  tests/test_wechat_handoff_v2.py \
  tests/test_prior_mentions_performance_appendix.py
```

从 `source/v4_app/` 运行 Stage A Python 测试：

```bash
PYTHONPATH=. python3 -m pytest -q tests/test_wechat_stage_a.py
```

V4 TypeScript API 客户端测试：

```bash
node --test tests/wechat_ui/client.test.cjs
```

测试需要 pytest、Pillow、pandas/PyArrow、FastAPI 及 TypeScript 编译器；在此运行环境中只确认了 Pillow 与 pandas 可导入，pytest、PyArrow、FastAPI 和 `tsc` 缺失。若命令无法启动，按 `TEST_EVIDENCE.md` 中记录的结果报告 `CANNOT_CONFIRM`，不要将缺依赖说成测试通过。V4 测试使用本目录的合成报告夹具，不含真实原文或回执。API 子路由有离线测试，但真实 V4 启动配置、Stage A API/UI 运行读取和自然时段均未验证。

完整文件 SHA 清单为 `FILE_SHA256SUMS.txt`（清单不包含自身）。`WRITER_RECEIPT.json` 记录本次导出和验证证据；该文件不是独立 Reviewer 的接受结论。
