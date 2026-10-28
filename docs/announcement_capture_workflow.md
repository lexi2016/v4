# Eastmoney 港股指定日期公告目录

日期目录通过现有 `ManagerResearchJobService`、`HkexOfficialProvider` 和共享 `MaterialStore` 采集 Eastmoney 港股公告列表。它只读取列表响应，不抓正文或 PDF，也不做公告语义判断。

## 一次调用

把 `date` 设为 manager 目标交易日，把 `publication_date` 设为明确的公告列表日期：

```text
POST /api/v4/manager/research/announcements/refresh?date=20260930&source_scope=EASTMONEY_HK_DATE_CATALOG&publication_date=2026-09-29
```

成功后可用相同参数读取并重新校验目录：

```text
GET /api/v4/manager/research/announcements?date=20260930&source_scope=EASTMONEY_HK_DATE_CATALOG&publication_date=2026-09-29
```

请求使用 `ann_type=H`、`client_source=web`、`f_node=0`、同日 `begin_time`/`end_time`、`page_size=20` 和逐页 `page_index`。总页数由第 1 页 `total_hits` 推导，并额外读取空终页；每次请求先落 owner attempt，再落逐页响应 receipt。

## 结果与恢复

- `COMPLETE` 表示 Eastmoney 指定日期列表的页数、总行数、唯一 `art_code`、通知日期和港股 `116/H` 代码均通过校验，且观察到空终页。
- `COMPLETE_EMPTY` 仅在第 1 页 `total_hits=0` 且列表为空时表示已验证空目录。
- 缺页、终页非空、总数漂移、重复 `art_code`、通知日期或市场代码不符均为 `PARTIAL`；原始列表行仍保留，失败原因和逐页引用可读回。
- 同一日期已有目录时，普通刷新只重验并复用已有 source refs，不重新抓取完整列表。部分目录需要显式 `resume=true`；通过校验的页复用原引用，仅缺失或未通过的页再尝试一次。失败页没有自动重试。
- 已由受信调用方读取并确认存放在同一共享 `MaterialStore` 的 page refs，可通过 owner 的内部 Python 方法 `service.accept_saved_date_catalog_refs(target_date, publication_date, page_refs)` 纳入原交易、attempt/page receipts、seal 和 GET readback。此方法只接收引用对象，不接收文件路径；它固定禁用 provider，缺页、错日期 URL、错 SHA 或其他引用错误会形成可重验的 `PARTIAL`，不会触发 fresh capture。已存在 owner 产品时拒绝覆盖。
- 该路径把产品 `capture_mode` 记录为 `SAVED_REFERENCE_IMPORT`，每页保留源 ref 自带的 `retrieved_at`。产品 `generated_at` 是 owner 处理时间，不能被解释为重新采集时间。无网络集成脚本 `TASK/fixed_announcement_workflow/integrate_saved_date_catalog_refs.py` 默认 dry-run；只有显式 `--apply --state-root ... --master-root ...` 才写入指定 owner state。
- 目录结果另含与当前已验证港股 master 的代码交集视图。该视图只是发行人关联输入，不代表 manager 选股结果。

Eastmoney 的 `display_time` 与 `notice_date` 不一致时，行不会因时间差被过滤；差异单独计数。该目录只证明 Eastmoney 镜像按指定日期返回的列表分页，不证明 HKEX 首次发布时间，也不证明相关事项在该日发生。既有 `EASTMONEY_HK` issuer mirror 仍是另一种有限范围；其 page-size/latest 结果不能作为完整日期目录。
