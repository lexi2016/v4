# article v2 独立静态审查

审查基线：`4a8063eb3ac4bdbbb30bd7659c5a38c4b32e6d28`。两位独立只读审查者分别检查采集合同和消费/计划接线，主写入者核对并最小修复。云端实际文件可用；未运行产品模块或产品测试、未采集、未部署。Mac离线及Chrome SIGABRT不作为代码结论。

## 明确发现和本次处理

1. **发布时间微秒误拒（已改代码，未运行验收）**：原collector与builder使用 `isoformat(timespec='seconds')`，4a8063却要求archive与原页时间精确相等。新判断仅允许原owner的截秒转换，并核summary与原页全精度时间相等；v2输出保留原页全精度发布时间，PIT排序也用全精度，不能提前截秒。
2. **显式group冲突（已改代码，未运行验收）**：原producer把请求group覆盖到recent，候选因此忽略响应自己携带的冲突group。现在原页若含嵌套/顶层group_id，必须与本页请求一致；省略时才使用请求group。
3. **source_path_sha256未绑定（已改代码，未运行验收）**：原校验只核64hex。现按原collector由本次run日期/slot确定的status相对路径计算SHA并核对。不会改原source_path算法。
4. **article_id/dedupe_key未重算（OPEN，问题包）**：原builder的去重元组末项来自 `claim_type or evidence_level`，archive v1不保留claim_type，也不携原source_path明文或完整builder source。当前接口仅接收archive_v1及capture。虽然正文/URL/主体/时间/page SHA已有独立绑定，两个旧身份字段仍只通过原v1格式/唯一性验证。不能把此边界称为完整原builder来源身份验证；也不能据此声称正文或US业务关系可随意伪造。

## 代码已确认的链路与测试覆盖

- producer确为V5隔离副本；页时钟在runner完成后测量，来源可用时钟在原页/正文/摘要fsync和读回后测量。无批次开始时间替代篇级取得时间。
- 通过原 `ResearchArchiveStore.publish/read_exact`、独立reader、`existing_materials.project_archive`、原native主体parser和关系consumer。旧v1不获补时间。
- 原行业路径不要求ETF ticker，原个股路径要求明确US symbol；四键seed未替代两条材料路径。两条原算法不改。
- 原manager核计划与同run attempt、input identity；当前入口再独立read核run/SHA。
- 原闭环测试故意缺US来源，只能证明材料接入，不能证明最终US映射。本次补两项候选：通过冻结原US snapshot builder和原store生成全部33个symbol的合成READY三文件；无显式US ticker的光模块正文应形成行业映射，含NASDAQ:AVGO正文应形成直接关系，均核保存和独立同run读回。合成capture按原纽约16:15–16:20窗口构造，16:17必须不晚于测试cutoff；若窗口尚未过去明确失败，不能借未来数据通过。外层无RSS记录使用READY_EMPTY，snapshot仍须READY。未运行，不报告PASS。

## 精确剩余接口问题

解决OPEN项需要在导入合同中绑定原builder输入字节，而非猜回已丢字段：原函数
`domains.research.build_research_archive(source, *, source_input_sha256)`，至少需要同批次完整 `stock_research_timeline`、`stock_research_daily`、`trade_date` 和 `source_manifest`；timeline必须保留 `claim_type`、`evidence_level`、`source_path`、原dedup字段。应由原builder重建并与接收archive_v1逐字段/规范SHA比较，然后再做v2扩展。当前receipt绑定原recent/summary，但尚不包含这份builder source。没有请求或创建新外部服务。

本地问题包只含必要源码、固定基线/候选SHA清单、明确变异复现步骤和上述事实/缺证据；不含原始市场数据、账号、凭证或运行日志，未发送给Chat或其他外部接收方。另需明确 `source_generated_at` 是导入生成时点，不是archive自身落盘完成时点；来源原文的durable availability另有回执，单凭字段命名不判定PIT突破。

## 交现有Mac的一次验收命令（NOT_RUN）

```bash
V5_ARCHIVE_PRODUCER_SOURCE_ROOT=/ABS/EXISTING_ISOLATED_FULL_SOURCE PYTHONPATH=V5/src:V5/tests python3 -B -m unittest test_archive_acquisition_producer test_archive_article_v2 test_current_us_research test_manager_archive_reader test_us_mapping_scope test_manager_plan -v
```

云端只进行AST、原owner源码差异和SHA、补丁一致性与远端读回核对。源码清单及前后SHA见同目录 `2026-10-10-article-v2-static-review-sha.json`。公告导入、UI清理和超跌兼容不在本轮改动范围。
