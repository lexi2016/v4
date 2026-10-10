# M04/M15 新采集 → article v2 → 原经理消费候选

基线 `4475cafd374ccbbb35f9b218ade7e38a1d6fa9d7`。云端候选；产品测试、真实采集、Mac独立验收和部署均 **NOT_RUN**。原 V4 活动源、冻结 archive/manager owner、公告 current_recovery/reviewer、策略及 BUY 门未改。

2026-10-10 身份修复候选基于 `cdd430e4dcd8d3e8c5949baff21a4831b4689444`，保留 `7115f65267a1496d0ca8214cc14130f8c2b65d87`。新 v2 导入必须带完整原 builder source 及其 owner 回执；旧的仅 archive/capture 请求拒绝。详细补丁、来源说明及 Mac 验收见 [身份修复交付](../../../handoff/v5-article-identity-repair-20261010-r1/START_HERE.md)。本次不改采集 producer 源码。

## 完整调用链

1. **原 producer 隔离补丁**：`source/ops/run_zsxq_hourly_delta.py` 在现有 `process_runner` 返回后逐页测量完成时间，保存实际 CLI stdout 文本的 UTF-8 表示（去 BOM；不是声称原始网络字节）。原分页、分析和三个产物算法不变。页响应、原 recent、原 summary 均 fsync 后读回，再记录 `source_payloads_available_at`；版本 `v5.zsxq_acquisition_receipt.v3` 固定每页和三个原文件的 SHA/长度及 producer SHA。批次开始时刻、旧 `fetched_at` 从不成为篇级 retrieved_at。
2. **原 source 与 article v2 导入**：`archive_builder_v1.run_build` 只向固定原 collector 提供显式声明的同批 status/summary，由原 normalizer 生成完整 source，经 V5 安全 IO 边界按原序列化落盘；源 SHA 来自实际读回字节。`archive_article_v2.run_import` 在独立子进程校验原 v1、逐文章页响应/原摘要及完整 owner source。导入前重放原 owner 的完整输出并逐字比较，再调用原 `build_research_archive` 比较完整 v1 对象和规范 SHA；不从 article 猜回 claim_type。输出 `v5.research_archive.v2`，保留原算法字段，补正文、取得/可用时间和 source/owner 引用。
3. **原 archive store**：在全新标记目录调用原 `ResearchArchiveStore.publish(mode='REPLAY')`，保留原 manifest、receipt、冲突拒绝和安全门，不更新 LIVE latest。先原 store 读回，再通过独立 `archive_reader` 子进程读回。返回 `archive_binding={root,files}`，包含全部精确证据文件 SHA。
4. **原材料 consumer**：现有 archive reader 增加明确 v2 分派；每次读 v2 都复核原 v1、页文件、summary、文章绑定，并在只读内存路径重放完整 source/原 builder，再由原 archive store 返回。最终 payload 比较规范字节，拒绝 Python 等值但 JSON 类型不同的篡改。v1 仍原样校验并保留缺取得时间拒绝。原 `project_archive → native issuer/proposition → issuer_us_relations` 自动消费新增字段；不改主体识别、行业 taxonomy、个股关系、资格或两源 PIT 门。
5. **当前 US 实际入口**：`current_us_research.run_current_research` 可选 `archive_import`；导入成功的精确 binding 自动进入原经理 refresh、同 run 保存及独立 read。也保留直接 `archives` 输入；两者互斥。导入失败抛出错误，不回退旧档案。不改变普通经理 API 的已有发布流程。

## 接口与拒绝边界

`archive_import` 的精确字段（没有网络或服务调用）：

```text
capture_root: 本次原producer的隔离数据根绝对路径
capture_files: {相对路径: 原文件SHA256}，显式包含本批回执、原产物、页、status、完整source、owner结果及owner回执
receipt: {path, sha256, bytes}，指向 acquisition_receipt.v3.json
builder_source: {path, sha256, bytes}，指向 research/hourly/source/{原source字节SHA256}.json
builder_receipt: {path, sha256, bytes}，指向本次 run 的 builder_source_receipt.v1.json
archive_v1: 同一次原归档builder产出的完整 v3_5.research_archive.v1 JSON对象
output_root: 全新私有根；仅含 .v5-archive-article-v2
```

输出根标记内容精确为 `v5.archive-article.v2\n`；producer 根仍用 `v5.archive-acquisition.v2\n`。两个根与其他写入根不能重叠。先向 `archive_builder_v1.run_build` 传精确四字段 `capture_root,capture_files,receipt,status`；其中 status 是本批固定状态文件的 path/SHA/bytes，不能选择 latest。保留它返回的五项绑定与完整 `archive_v1`，再补 `output_root` 组成上述七字段请求。可用 `python3 -I -B V5/src/v5_shadow/archive_article_v2.py < request.json` 单独导入；完整当前研究请求把同一对象放入 `archive_import`，沿用现有入口。此处是候选接口说明，实际执行仍归独立 Mac 任务。

篇级约束：archive_date 必须等于本次 durable availability 的上海日期及 run_id 日期；publication 原样保留，可早于采集日。原 topic URL 必须精确17位 topic ID，页中 topic/group 唯一；recent 必须等于该页原 topic 加原 group 标识；原摘要必须同 topic、标题和发布时间，原公司代码/名称（仅复用原collector规范化）必须一致，主体名称及 evidence_sentence 必须在同篇原文，主题必须与原摘要完全一致。所有日期必须有时区，publication ≤ 本页完成 ≤ 原文落盘可用 ≤ 导入记录时间 ≤ 当前时间。消费者仍按自身 cutoff 过滤。

新增 source 时间链：采集产物可用 ≤ owner 开始 ≤ owner 完成 ≤ 完整 source 可用 ≤ v2 导入生成 ≤ 当前时间。原 normalizer 两次无时区 `now()` 保留原值并单独记录当时 UTC offset；collector 的上海时钟与原 slot cutoff 不改。不得用 source_manifest 的旧 cutoff 时间冒充本次取得/可用时间。记录和重放只证明一致性，不能证明真实发生或自然来源。

缺任一文件、哈希/日期/正文/出处/主体不符、重复 topic 歧义、旧 v2 批次回执无逐页证据、附件无正文、生成时间倒填或目标 cutoff 早于可用时间，均拒绝或被原 consumer 排除。不会用另一篇正文、标题近似匹配、清洗后的摘要或批次开始时间补齐。HTML清洗造成 evidence 不是原文精确子串时也拒绝，需原owner提供可验证转换，不自行猜修。旧2058记录没有回写路径；已有输出根拒绝再次导入。

新 acquired article 仍是研究意见，页级内容绑定不是主体关系已确认。HK02513混绑和NLR/REMX/ARKX taxonomy缺口原样拒绝；四键 seed 不扩展。全部 natural_verified/formal资格/全市场覆盖保持原门禁。

## 一次 Mac 验收批次

同一固定提交、现有独立 Mac 任务，在仓库根运行以下候选回归命令。先按身份修复交付的 Mac 文档在旧固定版本确认三项 RED；此处不是已通过记录。变量指向现有完整隔离原源码；manifest 的全部依赖 SHA 必须符合，包括新增 owner/normalizer 与实际 `_namespace.py`，不下载或安装依赖。临时根必须是无 symlink 祖先的规范路径。测试仅使用合成 CLI 返回、合成 analyzer 结果和临时标记目录；实际分页、producer IO、原 collector/builder、archive store、独立 reader、原 native identity/材料 consumer、经理计划由测试候选调用。

```bash
V5_ARCHIVE_PRODUCER_SOURCE_ROOT=/ABS/EXISTING_ISOLATED_FULL_SOURCE PYTHONPATH=V5/src:V5/tests python3 -B -m unittest test_archive_acquisition_producer test_archive_article_v2 test_archive_builder_identity test_current_us_research test_manager_archive_reader test_us_mapping_scope test_manager_plan -v
```

新增闭环测试包含：逐页完成时间区别于批次开始；原文绑定→原 store→独立读回→原 native 主体材料关系审计→经理同 run 计划；旧日期/旧回执/缺页/错SHA/重算外层SHA/重复topic/错正文/错主体/错出处/错发布时间/倒序时间/未声明文件/修改文章后重算archive receipt均拒绝；早 cutoff 排除、旧根字节不变。US源在合成闭环测试中刻意缺失，原US材料关系可接受，但US匹配仍 NOT_EVALUATED/null，不把它报告为真实US选股成功。

当前入口另有运输测试，确认新导入binding同时传入refresh/read且错误时不会用已有档案替代；真实US三文件与真实原analyzer/selector尚未运行验证。

## 静态核对与实际剩余条件

云端只执行 AST、diff、源码/补丁哈希核对；不运行产品测试、CLI采集、构建、部署或交易。`manifest.json`记录原producer、候选、原owner接口和改动前后SHA。原源码的其他函数AST保持一致，目标 materialize 仅增加捕获和回执接线。

原采集候选仍需要已有完整隔离源码的 analyzer/upstreams 路径；不能直接把本目录当独立安装。本次 source owner 适配复用固定原依赖，支持显式新 run，不复用/恢复已有同 slot source。所需输入为：新页级回执及绑定文件、同批原 source 完整字节/owner回执及原 archive v1、当前准确 US session 三文件、原 HK 身份来源。尚无本候选真实同批 source 证据或 Mac PASS，来源证明继续未闭合，不宣称自然链或正式业务已验收。
