# 新采集时间回执候选（M04 / M15）

基线：`d1bf034640ca2e5957423de2745a98e159b69af2`。身份：云端代码候选，NOT_DEPLOYED；产品测试、独立验收、真实采集、自然时段验证均 NOT_RUN。本批不改 V4、经理跨日逻辑、公告或超跌代码。

## 实际接线

- `source/ops/run_zsxq_hourly_delta.py` 是原 producer 的限定补丁副本，`producer.patch` 和 `manifest.json` 固定原始/候选字节。原分页、筛选、分析及输出算法保持原样。
- 仅允许含 `.v5-archive-acquisition` 文件（精确内容 `v5.archive-acquisition.v2\n`）的隔离数据根。没有自动创建标记或选择正式数据根的逻辑。
- 新调用在原采集回调完成后记录 `retrieval_completed_at`；原三个文件经 SafeRoot fsync 并独立读回匹配后记录 `source_payloads_available_at`。回执绑定精确文件 SHA/长度，原成功状态引用其 SHA/路径。时钟逆序、读回不一致不发布新成功状态。已有成功槽位复用，不补写时间。
- 当前 US 入口从独立经理读回结果返回 `archive_readback` 和 `coverage_paths`，分别展示原行业材料、个股关系、固定 seed 三种范围。保留原拒绝、nullable、真实零值及总评估状态，不新增映射算法或扩大 seed 范围。

## 明确限制

回执时间只覆盖本次有界 CLI 响应和派生摘要，不是逐篇文章取得证明，也不是历史 PIT。原 `fetched_at`、`collected_at` 不重命名为新时间。旧 archive v1 白名单和 manager 原缺取得时间拒绝保持不变；本批尚未实现 article v2 导入/消费合同，因此不会凭此回执把旧归档放行。

行业路径需要上涨行业及经验证的 HK 主体业务主题，不要求显式 ETF ticker；个股路径仍需显式 US symbol。四键 registry 仅固定 seed。HK02513 的正文混绑及 NLR/REMX/ARKX 主题缺口不在本批猜测修复。所有自然验证、正式资格和全市场覆盖声明保持 false。

这是原 producer 的候选补丁，不是第二套定时采集服务。未来真实执行须在现有完整隔离源码副本的 `ops/run_zsxq_hourly_delta.py` 位置应用，以保留 `__file__` 相对的原 analyzer/upstreams 依赖；不可把本目录当独立可运行安装。真实 CLI、凭据、selector、完整 analyzer 依赖尚未运行验证。本批不提供部署或真实采集命令。

## 交现有 Mac 独立任务

在本候选固定提交的仓库根执行；环境变量指向现有完整隔离原源码，测试先核 manifest 中七个基础依赖 SHA。测试只用临时标记根，采集和 analyzer 是合成替身，不调用真实 CLI。两个命令分别运行，避免同一 Python 进程的原包导入缓存互相污染。

```bash
V5_ARCHIVE_PRODUCER_SOURCE_ROOT=/ABS/EXISTING_ISOLATED_FULL_SOURCE PYTHONPATH=V5/src:V5/tests python3 -B -m unittest test_archive_acquisition_producer -v
PYTHONPATH=V5/src:V5/tests python3 -B -m unittest test_current_us_research test_us_mapping_scope test_manager_archive_reader -v
```

新增 producer 六项覆盖：完成时间不取历史 now、旧成功不回填、未标记根拒绝、采集失败、时钟倒退、落盘字节不符。当前入口增加三范围保真及 archive 双调用透传断言；已有真实原 workspace 测试继续验证旧归档缺取得时间拒绝、同 run 保存/独立读回。以上是测试候选，尚无本提交 RED/GREEN 结果。

记录：按用户要求云端只做 AST、diff、哈希及补丁静态一致性核对；Mac 独立测试仍是验收门。此次只交 M04/M15 最小候选，未宣称主计划或完整经理链交付完成。
