# BR003 + 两个既有 owner 接续面（2026-10-02）

固定反馈基线：`34e1dc6912100830f42cf0fc90eec72f624afc9a`。
BI01/BI02 上游候选提交：`d18be217a84c10c17c7b36bb7816b2ee58f14ff9`。

本批只做三件事：BR003 最小增量、公告原 owner 续跑说明、目标日 HK Connect 原 owner 输入说明。没有日线、BI04、日历、调度、服务切换或新架构。

## A. BR003

**结果：PATCH_READY / LOCAL_NOT_RUN_BY_CHAT。**

唯一改动文件：`apps/web/src/api/managerWorkspace.ts`。相对已在 Mac 39 项通过的 d18 after-image：

- before SHA256 `981e77c0024c56a2f089927db76a6dda59d399a61858beea59e639d75e9d1c42`，67498 bytes。
- after SHA256 `6eef36501d05334c60e052ec0e344240ce310c6a0a1444a7ce6b8c61be33f9fa`，67513 bytes。
- 增量 patch SHA256 `5279b153f186e7c51ffe04a4763c3e351194991cbebb1c29a69ed06834f0d48c`，3006 bytes。

修法不是比较 capture date。`validateResearchAttention(raw, date, ...)` 已经拿到工作台请求日；本补丁只把这个 `date` 继续传入 `validCompanyEvidence` → `validMirrorCompanyEvidence`，再由现有 `validateEastmoneyDocuments([doc], date, cutoff)` 校验 projected owner-document 的 `target_trade_date`。

因此合法历史样本继续保持：consumer target=`20261002`，`owner_document.target_trade_date=20261002`，`owner_document.capture_trade_date=20260929`，`owner_capture.target_trade_date=20260929`。仅把 projected owner-document target 偷换成 `20260929` 时拒绝。

未改变 PIT 窗、正文/source refs、issuer、relation_origin、双来源或资格门禁。

## 针对性测试

`tests/test_br003_target_date.py` 包含两项：

1. `test_history_capture_date_is_separate_from_consumer_target`：合法历史抓取必须继续通过。
2. `test_wrong_owner_document_target_date_is_rejected`：仅篡改 projected `owner_document.target_trade_date` 必须被 TS parser 拒绝。

`tools/work_once.py` 只接受已经是 d18 五文件 after-image 的隔离 `application_candidate`；它核 SHA、应用本增量 patch，然后一次运行原 39 项 + 新 2 项。预期是 41 项全部通过；Chat 未在 Mac 代跑，不提前标 TESTED。

本地一次执行：

```bash
python research/manager-br003-owner-continuation-20261002/tools/work_once.py \
  --app /absolute/path/to/existing/application_candidate \
  --output /absolute/path/to/new/br003-evidence
```

通过门：exit 0；`WORK_RECEIPT.json.status == ISOLATED_41_CASES_PASS`；五文件 SHA 与 `SOURCE_PINS.json` after 状态一致。之后才由 Codex按原流程做小范围接入/部署/API/UI 验收。

## B / C

公告覆盖与目标日港股通资格输入的原 owner 接续见 `OWNER_CONTINUATION.md`。两面均不要求本批再写业务抓取器/reader。

安全标志保持：`RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
