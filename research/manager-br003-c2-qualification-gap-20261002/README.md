# BR003-C2 与 qualification 有界收口

固定反馈提交：`660e1e8e97027f70865d2df84ccf132c90c8c278`。

## A：BR003-C2

本地反馈证明上一版业务方向正确、但漏传两层 `date`。本次只补四处：

`validateResearchAttention(date)`
→ `validateAttentionDecision(..., date)`
→ `validateAttentionLaneEvidence(..., date)`
→ 已有 `validCompanyEvidence(..., date)`.

相对失败候选：
- before SHA256: `6eef36501d05334c60e052ec0e344240ce310c6a0a1444a7ce6b8c61be33f9fa` (67513 bytes)
- after SHA256: `415f55cb4fcc14cc33ac451b3c3d7a154cffe56d4986b81e82fb40a9a71e91c3` (67552 bytes)
- patch SHA256: `883f5fb4c09436cb1feeb49fd0f2fa97751bcb42b76b23cfd288ddfa218b6926`

没有再改 mirror date 语义；合法 20260929 historical capture 仍应通过，projected owner-document target 与 workspace request 不一致仍应拒绝。

### 本地一次执行

```bash
python research/manager-br003-c2-qualification-gap-20261002/tools/work_once.py \
  --app /absolute/path/to/existing/failed/application_candidate \
  --output /absolute/path/to/new/br003-c2-evidence
```

runner 先 strict TypeScript 编译，只有编译 exit0 才运行原 39 + BR003 2 项。Chat 未在 Mac 复跑，因此状态是 `PATCH_READY / TESTED_NOT_RUN_BY_CHAT`，不写 41 passed。

## B：公告

本轮不再续跑。接受本地封存终态：270/696，204 文档，156 BODY_PARSED，14 issuer query failures，426 未查询；连续两批 source time-budget failure 后停止。保留 run/savepoint，不改预算、不重开窗口。

## C：qualification

详见 `C_QUALIFICATION_GAP.md`。已定位现有 V2 builder，但现有 8 文件不足以诚实实现 publisher：缺 exact V2 producer 源字节、7 个 provenance 原值，以及可能缺唯一现有 publisher 源文件。没有这些输入前停止，不改 reader/日线/门槛。

安全位保持 `production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
