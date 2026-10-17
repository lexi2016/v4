# 公告选股：最新采集在读回阶段失败，模型未启动

## 可直接提交给 Chat 的请求
请按本包证据最小修复 V4 公告选股按钮：点击后能采集当前窗口最新公告，再把合法、可追溯的新增公告交给现有本地 Qwen3.8 Flash 研究，并自动更新现有页面。复用已有成功结果与采集缓存，禁止成功任务重跑。先修下面已经复现的产物读回大小合同不一致，不扩为数据层迁移或全局权限/限制调整。修复须独立 Reviewer 验收后再更新同一 V4 页面。

## 本次真实操作与结果
- 北京/香港时间 2026-10-17 23:00:50，在现有页面打开“公告选股”，只点击一次“采集新增公告并增量选股”。页面目标港股日仍为 20261016，未擅自改成周末目标日。
- 新任务 e20cf0d93ea843a885b090173b6eab55，研究截止时间 2026-10-17 23:00:00+08:00，并非旧的 10月16日14:57冻结续跑。
- 23:03:53 终止：FAILED / CAPTURE_ANNOUNCEMENTS / OWNED_FILE_TOO_LARGE。
- model input.json/result.json 均未生成；程序在模型进程启动分支之前失败。本次不能称为“模型研究已启动”。
- 页面仍显示旧的 05:44:49 结果和11只新增候选，那是上一任务，不能冒充本次结果。

## 已确认的直接原因
- 本次采集产物已实际写到本机，大小 87,576,192 字节（83.519 MiB），SHA及本地路径见 capture-product-summary.json。
- 有1184条目录记录，1150条正文完整、31条在窗口外、3条正文失败。日期窗口覆盖10月14日至17日；返回的公告日期为14/15/16日。不要将目录观察结果宣称为官方全市场完整覆盖。
- infrastructure/owned_io.py:103 的 SafeRoot.read_bytes 默认 max_bytes=64*1024*1024；第111行拒绝大于该限值的文件。
- v4/manager_workbench/inputs/capture_store.py:230-237 的 save_product 在存在性比较和保存后读回时均未显式提供 max_bytes，故使用64MiB默认值。
- capture.py:278 保存整个聚合产物，rows 与 source_variants 含相同1184条记录；此为体积证据，不意味着授权重构产物合同。
- announcement_update.py:1499 调用 capture_window，异常被记录为采集失败；其后第1509行消费者已采用256MiB读上限，但本次根本没有到达这里。
- 对已落盘的同一产物仅执行一次 SafeRoot默认只读读取，直接复现 OWNED_FILE_TOO_LARGE。未重新采集、未执行模型、未改限值。

## 最小复现（已有机器，纯只读）
运行环境使用现役API环境或与其兼容的Python，把 active_runtime_root 加入sys.path，构造 SafeRoot(capture_root)，调用 read_bytes(artifact_ref)。三个路径均在 capture-product-summary.json / runtime-and-source-binding.json。预期当前代码抛出 OWNED_FILE_TOO_LARGE。无需再点按钮、无需再下载原始公告。

## 修复边界与验收建议
1. 对齐现有 capture producer 与下游消费者的有界产物大小合同，覆盖首次保存读回和同SHA重复保存比较两个分支；保留路径、owner、SHA、不可变及安全校验。不要默认放宽全局SafeRoot限制或吞异常。
2. 先用合成非敏感超64MiB且在合法合同内的产物验证，以及明确超过合同边界的拒绝用例；不为验证重复跑旧成功模型。
3. 复用本次已保存的合法缓存，经既有入口完成发布，并证明新的模型输入、模型实际开始处理、任务身份和API/UI结果绑定。按钮提交、HTTP 200、旧结果或模型端口在线都不算启动证据。
4. 本次聚合产物另带 BODY_ARTICLE_TITLE_OR_DATE_MISMATCH、BODY_PAGE_TOTAL_INVALID、CAPTURE_AVAILABLE_AFTER_RESEARCH_CUTOFF 等缺口。它们是现存证据，不要清零或越过PIT/资格门禁；当前直接阻断是大小限制，后续是否阻断仍需精确判定。
5. 保持目标日期、A/HK分离、唯一producer和现有页面；RESEARCH_ONLY=true，production_allowed=false，buy_gate_updated=false，orders_sent=false。不得改Vibe或其他服务。
6. active-source是实际运行版本快照，runtime-and-source-binding.json逐项列出它与canonical源码SHA是否相同。不要把canonical HEAD自动当成实际运行版本。

## 包内与未做事项
包含真实失败attempt、精简API前后对照、UI截图、产物大小与SHA摘要、4个实际运行源码文件及哈希。未包含原始公告正文、大型数据文件、凭证、租约token或完整配置。未修改业务代码、未重启服务、未再次点击、本材料按用户本轮授权上传GitHub；未向其他Chat发送消息。独立修复验收尚未执行，本包仅为已复现故障的交接。
