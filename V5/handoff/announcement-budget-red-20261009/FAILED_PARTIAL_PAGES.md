# 失败正文已保留页面：V5 候选合同兼容修复

基线 6e30a74b268c8f9ebbb2fa50eda5110ee4c3f71a。父任务报告新增 15 项 Mac 单次 15 PASS、exit0；原 55 未重跑。随后唯一真实离线恢复 exit1：ANNOUNCEMENT_BODY_CAPTURE_FAILURE_RECEIPT_INVALID。旧 7536 文件及 BLOCKED SHA 不变，派生目录 UNVERIFIED，无成功恢复回执。

真实失败形状：AN202610081830210432 保留 60/108 页，error=BODY_BATCH_TRANSPORT_CONSUMPTION_UNKNOWN；AN202610081830209405 保留 27/86 页，error=BODY_CAPTURE_FAILED:ValueError。具体 failure-diagnosis 字段摘要已请求父任务只读提供；这里不声称云端读取了 Mac 原文件。

## 变化边界

原采集器逐页成功后立即保存页面，之后失败时保留 pages 和 content_api_pages_captured；聚合 body_text/body_text_sha256 仍为 null，状态仍为 BODY_CAPTURE_FAILED。原终态 validator 却强制失败 count=0、pages=[]、content_page_count=null，拒绝其生产者合法保留的证据。

只在 V5 handoff 新增 candidate/v4/manager_research/workspace_announcements.py 覆盖候选，原文件从固定 0382f753 的 owner_dependencies 原样副本取前像。除新增失败页验证 helper 和原 failed 分支接线外，其他原函数/成功分支不改。原 owner_dependencies、pinned、V4 运行文件、主任务 workspace/UI 均未改。

失败页验证保留原失败通用约束：状态失败、非空 error、完整正文及 hash 为 null、PDF 为 null、NOT_REVIEWED、PIT/time CANNOT_CONFIRM。零页失败保持原合同。非零页失败要求：

- manifest captured count 为整数，与 body.pages 和原 bodies.content_api_pages 长度一致；两份页结构类型严格相同。
- 页索引是 1..N 连续前缀，禁止中间缺页、重排、重复；总页数为统一整数且不少于 N。失败可能发生在最后一页处理阶段，因此 N=total 也仍只能是失败，不据此提升完整性。
- 复用原 _verify_body_source_rows 校验每页文章/URL/page_index/日期、text SHA、raw SHA 与 source_ref 对应关系。
- 每页 title 与目录一致，证券匹配非空且属于原目录证券集合；原 article_receipts 的状态、原 error、页数、body artifact SHA 一致。
- 每页与已保存 request receipt 的 URL、art_code、page_index、source_ref、raw SHA、retrieved_at 和 content_metadata（总页数、文本 SHA/长度、日期、证券匹配）一致。

终态回执仍为 PARTIAL，failed_articles 保留原 error 和 artifact SHA，并附 captured_page_count/expected_page_count。不删除页面、不拼接完整正文、不重写原 receipt/SHA。恢复工具的原 identity/874 manifest/BLOCKED/字节复制/源 SHA 复核均不放宽；失败发生过的派生目录不覆盖，应在验收后使用另一个全新离线目录。

## Mac 单次候选验收

原 70 个测试方法/文件保持不变。新文件有 11 项：真实 60/108 与 27/86 形状；缺页、乱序、文本 SHA 错、源 SHA 错、总页数漂移、原页不一致、原 error 被替换、失败被提升为完整、request receipt 源绑定不一致；以及通过原完整终态校验器的集成用例（同时覆盖两个页数形状，保持 PARTIAL 和原证据字节不变）。合计 81 项待本轮 Mac 验收。

```bash
shasum -a 256 -c SHA256SUMS || exit 1
python3 -B -I tests/test_failed_partial_pages.py > failed-partial-pages.log 2>&1
PARTIAL_RC=$?
python3 -B -I tests/test_offline_evidence_recovery.py > offline-recovery-regression.log 2>&1
RECOVERY_RC=$?
cat failed-partial-pages.log offline-recovery-regression.log
printf 'partial_pages=%s recovery=%s\n' "$PARTIAL_RC" "$RECOVERY_RC"
test "$PARTIAL_RC/$RECOVERY_RC" = '0/0'
```

云端仅静态检查，以上均 NOT_RUN。验收通过后才由现有 Mac 任务按 RECOVERY_IDENTITY_FIX.md 再安排离线恢复；禁止新网络/重采/预算清零。真实 392 条阅读和独立审查仍须继续，保留正文缺口。

780 当次额外失败的临时记录已清理，无法追溯。6e30 的顺序同步用例已通过，但不能据此宣称 780 当次竞态根因得到运行证据证明。
