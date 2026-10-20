# 公告日常工作流候选

2026-10-20：P1 已独立验收；P23 为离线实现交接，独立验收前不部署、不采集、不调用真实模型。

P1 保留普通整篇 Reader 的合法 `changes`；分块和综合继续由账本拥有固定字段。正面入选仍要求 `facts`、`changes`、`impact`、POSITIVE 与 VERIFIED_EXISTING_FACTS，已给引文必须匹配正文；无原文内容的条件、反面证据可为空。外部固定 prompt/schema 身份与 owned validator SHA 分别记录，漂移失败关闭。历史优先复用兼容且文件 SHA 有效的成功；不兼容或失败历史保留，不自动重跑。分类规则字节沿用已封存版本。

新日常任务先完成既有采集和分类准备，再在任何队列认领前冻结 `announcement_flash/jobs/{job_id}/preprocessing-report.json`。`--preprocess-only` 返回 `PREPROCESSING_COMPLETE`，模型调用和队列认领均为零。报告包含原始条数、完整身份精确去重篇数、日期/港股通资格、历史成功及其他历史保留、A 归档/B 结构提取/D 缺资料、C 普通和长文篇数、分块和综合请求量、未知工作量、本次子集及延期数；主要去向闭合。必须先读回报告真实数字并向用户汇报，再进入已授权的模型阶段；没有增加每批用户批准门槛。

CLI 沿用同一 runner、输入和 job，公共参数为 `--state-root STATE --capture-root CAPTURE --shared-root SHARED --job-id JOB`：

```text
python ops/run_manager_flash_announcements.py [公共参数] --preprocess-only
python ops/run_manager_flash_announcements.py [公共参数] --execute-preprocessed-report-sha256 REPORT_SHA --execution-phase FIRST
python ops/run_manager_flash_announcements.py [公共参数] --execute-preprocessed-report-sha256 REPORT_SHA --execution-phase CONTINUE
```

API 使用 `POST /api/v4/manager-workbench/announcement-flash/{job_id}/execute-preprocessed`，正文为 `{"report_sha256":"…","phase":"FIRST"}`；首篇完整结果验收后使用 `phase=CONTINUE`，同时提供当前不可变交付版本的 `first_delivery_sha256`。两个阶段沿用同一 job 和冻结来源；CONTINUE 只执行其余尚未尝试的新版本。报告或输入漂移即拒绝；历史已处理、成功、已有尝试及用户停止的三篇均排除。FIRST 按 article/source/body 精确绑定，正文修订不会被同 article_id 混入首篇。

`NEW_ONLY_CANARY_20261020` 限最多 8 篇、16 个模型请求、每篇最多 6 个 part；这是当前新增 canary 上限，不是永久日常上限。全部应模型篇数与最多 8 篇子集分开报告；不存在合格新输入时返回 `CANNOT_CONFIRM_NEW_INPUT_UNAVAILABLE`。模型仍使用既有单模型锁。该入口仅派发冻结允许 keys；旧 RUNNING 历史记录保持原字节，不恢复旧 key。若预处理后出现其他处理历史，认领前拒绝。

普通篇每次完成即发布完整分析。长文所有必要 part 成功后马上综合，不等待整批；part 不作为候选。重要新增与就绪综合优先，周期性给较旧工作机会。交付保存为 `deliveries/{sha}.json`，原子更新本 job 的 `deliveries/latest.json`；FIRST/CONTINUE 各自总结也不可变，旧成功文件和 SHA 引用保留。读取 API 将既有候选与新版本合并，未完成、失败、待资料和延期均可见。现有 AnnouncementCandidates 展示报告、逐篇结果、FIRST/CONTINUE 与停止过程，无全站重构。

`POST .../{job_id}/stop` 和 SIGTERM/SIGINT 使用合作取消；重复停止幂等。在途时显示 `STOP_REQUESTED`，当前结果保存后不再派发，未尝试项保持零尝试。执行确已退出、终态读回后才标记 `USER_STOPPED`，保留已完成计数；正常失败仍为失败。历史停止记录不手工改写。

预处理仅不可变身份计算允许配置 1–4 个线程，共享写入由父级串行提交，默认 1。8 个廉价单元的离线对比显示线程开销，无真实批次提速证据；模型并发未改变。单篇既存输入的可逆字典编码原型还原 SHA 相同、字节 45300→39790，但需要新的模型引用解码合同，未应用到请求；token 和推理提速未测，保留原表示。

证据在 `/Users/lexi/Desktop/学习/agents调试/助手/announcement-daily-workflow-20261020/writer/p23/`。测试使用隔离状态、模拟模型输出、真实本地 API 与 R6 前端依赖叠加；不代表现役部署或真实模型语义验收。候选种子有既存 R6 差异，部署只能携带精确候选 overlay，由独立 Reviewer 验收。

未执行：真实采集/模型 POST、live queue/history/cursor 写入、历史重算或已停止三篇续跑、服务/计划任务操作、部署、Git commit/push、真实新增 canary、现役 API/UI/natural 验收。旧定时任务保持停用。

`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`
