# 运行链补数据与复用 SOP

本规程通过现有 `/api/v4/operations/sop?doc=runtime-data-recovery` 读取。所有结果均为研究证据：`RESEARCH_ONLY=true`，生产、BUY 和订单标志为 false。候选验证不代表线上或自然时段验收。

先固定原日期、市场、Stage、来源、口径、原始 SHA、输入 generation 和 owner。原始分钟窗口成交额不能用当日累计成交额替代。HK fixedpool/Futu、经理 ExHQ 和日线各保留来源与消费者合同。ReviewDaily 的网络生产者与 Main/FUPAN 的消费者没有重复采集证据，不合并。

使用现役清单中的绝对 `PANEL_PYTHON`，以下命令中的 `$CONFIG` 是固定 Stage 配置，`$RECOVERY` 是本批隔离证据目录；不得指向原始 raw/selection/receipts。CLI 不推进任何正式 latest，也不改原收据。

1. 原始 raw 已有：先验证同 date/stage/market 的 artifact/manifest/receipt 三联 SHA，重放原始行并输出 `ORIGINAL_RAW_REPLAYED` 收据。保留原始缺口，不把重放行标为新自然运行。

   ```sh
   "$PANEL_PYTHON" -B -m ops.recover_stage_data --config "$CONFIG" --date 20261030 --stage-id STAGE_1445_1500 --market A_SHARE --action replay-original --output "$RECOVERY"
   ```

2. 确认有历史接口：仅现有 TDX A 分钟接口可用时按原 date 查询；每次最多三代表，不静默切 Futu 或其他来源。输出 `AFTERFACT_MINUTE_OBSERVATION`，保存原始响应 SHA、查询时间、原窗口及单位缺口；`pit_safe=false`，盘口字段与原时点采集时间继续 CANNOT_CONFIRM。

   ```sh
   "$PANEL_PYTHON" -B -m ops.recover_stage_data --config "$CONFIG" --date 20261030 --stage-id STAGE_1445_1500 --market A_SHARE --action historical-minute --symbols A.600000,A.000001,A.920001 --output "$RECOVERY"
   ```

3. 原时点字段无法恢复或接口没有证据：写 `CANNOT_CONFIRM` 恢复收据，保留原失败。不得用新报价填旧日期、填零或把 afterfact 升为 PIT。

   ```sh
   "$PANEL_PYTHON" -B -m ops.recover_stage_data --config "$CONFIG" --date 20261030 --stage-id STAGE_1545_1555 --market HK_CONNECT --action record-gap --output "$RECOVERY"
   ```

失败收据保留异常与原收据 SHA；每次独立 attempt，成功也保留历史失败。原始数据、错误、恢复收据和必要 checkpoint 不清理。真实交易窗口三代表的源时间、单位与字段验证未完成时保持 CANNOT_CONFIRM，非交易时段不等待下一交易窗口阻断其他工作。

A/HK 复盘和 21:40 现有调用统一经过原 builder；同 date + input generation + builder SHA 返回 NOOP，输入或代码改变创建新代次，原产品沿既有 CAS/supersession 合同保留。15:00/15:55 的 Stage 完成通知与 cron 使用同一个 workload claim，cron 只作有界恢复；15:55 经理的独立 attempt/status 不由 Stage 成功覆盖。
