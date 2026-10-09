# 派生恢复目录 → prepare → 注册/验证 → 私有导入 → 读回

基线 4cac13494d850bbabe64a226f130ab2799beb2b3。Mac 真实 prepare 报 ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_FAILURE_ROW_INVALID：analysis 的第二层合同仍强制 failed.pages=[]，未兼容已由 terminal 验证的 60/108、27/86。父任务报告 340 条真实阅读/独审完成，52 条采集失败仍未评估；本候选不生成或替换这些审查结果。

## 全链合同变化

1. workspace terminal 验证仍逐页检查原 artifact、request receipt、SHA、来源、序列和原 error；非零失败页再输出 retained_pages_sha256，绑定整个页序列。
2. analysis build 对失败页要求 count/total/页序列摘要与 terminal 一致，再按真实文章/公告日调用原逐页来源验证器。聚合正文/hash/PDF 仍必须 null；原失败状态保持。
3. 产品的 body_capture_failure 保存原 error、artifact SHA、保留页数/总页数、保留页摘要和完整保留页引用。它们是失败采集证据，不是已读语义引用。研究投影仍 TEXT_INSUFFICIENT_UNASSESSED、NOT_ASSESSED；body_page_citations=[]、body_page_count=null、exact_quote=null。
4. validate_product 重建失败证据视图并再次验证 terminal 绑定和逐页 SHA/来源；import_product 和 read 均复用该验证。不能只在 prepare 放行而在 import/read 丢页，或把失败页改成已评估。
5. registered handoff、真实 reviewer 来源 SHA、独立 reader/reviewer 身份、原 agent receipt 和 owner import receipt 校验不放宽。针对失败/阅读缺口的显式 article_decisions 仍必须 NOT_ASSESSED。

新候选 analysis.py 的前像为固定 0382f753 owner_dependencies 副本；workspace 候选只追加 terminal 页序列摘要。所有原文件副本和原证据不改。

## 新的离线分析 owner

新增 ops/run_v5_offline_analysis.py。它接受已验证的 recovery root 和操作者核实的 recovery_receipt.json 文件 SHA。adopt 核查 derived_root、marker、BLOCKED policy、original identity/archive、所有 recovered_file SHA，并重新调用 terminal validator；之后只在该派生根写 offline_analysis_owner_identity.json、jobs/products/receipts。原 OFFLINE_RECOVERY.json、recovery_receipt、BLOCKED 和 original 均保留。

这不是 PrivateOwner 的采集身份：不生成 v5_owner_identity.json，不初始化 provider/budget。begin_capture 和 capture 命令永久拒绝。CLI 安装拒绝 socket/DNS/subprocess 的 audit hook；原 CLI 的请求绑定进程内私有方法，没有 API server、8873 POST 或 V4 写入口。目录读固定为该 run 已验证的 catalog snapshot。

日期/run/catalog/body/evidence root 由恢复回执固定，用户不能通过参数改日期或换目录；输入和输出必须在该派生根内且无链接。注册和导入写入继续使用已有 SafeRoot/原 Store。每次命令前后复核旧恢复证据与 BLOCKED SHA；只有 import 和原 owner readback 成功后生成 manager_binding.v1.json。

## Mac 离线验收

原 81 项测试文件不变；新 test_offline_analysis_chain.py 有 7 项候选：完整 prepare→register-handoff→verify→import→readback；缺注册审核拒绝；同一 reader/reviewer 拒绝；capture/8873/跨日期拒绝；保留页篡改（重算产品 SHA 仍拒绝）；失败提升为已评估拒绝；错误恢复回执 SHA 拒绝。测试中全部阅读/审查是明确的临时合成 fixture，不写入真实证据。合计 88 项，云端 NOT_RUN。

```bash
shasum -a 256 -c SHA256SUMS || exit 1
python3 -B -I tests/test_offline_analysis_chain.py > offline-analysis-chain.log 2>&1
CHAIN_RC=$?
python3 -B -I tests/test_failed_partial_pages.py > failed-pages-regression.log 2>&1
PAGES_RC=$?
python3 -B -I tests/test_offline_evidence_recovery.py > recovery-regression.log 2>&1
RECOVERY_RC=$?
cat offline-analysis-chain.log failed-pages-regression.log recovery-regression.log
printf 'chain=%s pages=%s recovery=%s\n' "$CHAIN_RC" "$PAGES_RC" "$RECOVERY_RC"
test "$CHAIN_RC/$PAGES_RC/$RECOVERY_RC" = '0/0/0'
```

Mac 实际成功结果尚缺，不能把此候选写成全链 GREEN。

## 真实资料的接续命令（Mac 验收后）

组装当前候选到新 APP；不覆盖旧 app。DERIVED_ROOT 是已有 OFFLINE_TERMINAL_EVIDENCE_VERIFIED 的离线派生根，RECOVERY_RECEIPT_SHA 是该根现有回执的只读 SHA。旧 7536 文件和 17 份审查证据不改。语义/审查/decision 输入若在根外，父任务先按已核实 SHA 原样复制进派生根的 inputs 目录；原路径及原字节保留。不要生成新分类或伪造 reviewer。

```bash
python3 -B -I tools/assemble_owner_app.py --out "$ANALYSIS_APP"
python3 -B -I "$ANALYSIS_APP/ops/run_v5_offline_analysis.py" \
  --recovery-root "$DERIVED_ROOT" --recovery-receipt-sha256 "$RECOVERY_RECEIPT_SHA" adopt
python3 -B -I "$ANALYSIS_APP/ops/run_v5_offline_analysis.py" \
  --recovery-root "$DERIVED_ROOT" --recovery-receipt-sha256 "$RECOVERY_RECEIPT_SHA" \
  prepare --semantic-catalog "$SEMANTIC_CATALOG"
python3 -B -I "$ANALYSIS_APP/ops/run_v5_offline_analysis.py" \
  --recovery-root "$DERIVED_ROOT" --recovery-receipt-sha256 "$RECOVERY_RECEIPT_SHA" \
  register-handoff --semantic-catalog "$SEMANTIC_CATALOG" --reviewer-output "$REVIEWER_OUTPUT" \
  --decisions "$ARTICLE_DECISIONS" --parent-task-id "$ACTUAL_PARENT_TASK_ID" \
  --reader-identity "$ACTUAL_READER_IDENTITY" --reviewer-identity "$ACTUAL_REVIEWER_IDENTITY"
python3 -B -I "$ANALYSIS_APP/ops/run_v5_offline_analysis.py" \
  --recovery-root "$DERIVED_ROOT" --recovery-receipt-sha256 "$RECOVERY_RECEIPT_SHA" verify
python3 -B -I "$ANALYSIS_APP/ops/run_v5_offline_analysis.py" \
  --recovery-root "$DERIVED_ROOT" --recovery-receipt-sha256 "$RECOVERY_RECEIPT_SHA" import
python3 -B -I "$ANALYSIS_APP/ops/run_v5_offline_analysis.py" \
  --recovery-root "$DERIVED_ROOT" --recovery-receipt-sha256 "$RECOVERY_RECEIPT_SHA" readback
```

必须保留已有真实 decisions，不因某字段缺失而省略它以获取 NOT_ASSESSED 默认结果。register-handoff 复用原函数构建 agent receipt/analysis_product/handoff_manifest；verify 验证它们；import 再验证一次后才写产品。

实际输出位于派生根：
- workspace_announcements/20261009/eastmoney_date_catalog/20261008/analysis.v1.json
- 同目录 owner_import_receipt.v1.json
- 根 offline_import_readback.json 和 manager_binding.v1.json

manager_binding 是本候选的私有产物描述：绑定 owner root、日期/run、产品文件及逻辑 SHA、导入回执文件 SHA、读回 SHA、恢复回执 SHA、BLOCKED SHA。明确 manager_ui_integrated=false；它不声称经理页面已读取这些产物。本任务不修改并行 manager/UI；父任务可用这些准确路径和 SHA 接入现有消费层。

若已有派生根曾按另一 app 版本 adopt，身份不一致会拒绝，不能手改身份绕过；应保留该目录并由父任务安排新的离线副本承接。任何失败都停止该阶段，禁止重新 capture、刷新目录、清零预算或写 V4。
