# 原 owner 链定位与仍待验证的内容

## 证据范围

源码以 R2 问题包及 GitHub 固定 commit `e72607634d46146b0b6c0f4a0396f6b2939589f7` 为准。以下是源码与包内回执的核对结果，不是对 Mac 当前进程的直接读回。

当前日期对为 `20261009 / 2026-10-08`。旧公告阳性为 `20261008 / 2026-10-07`。9 月 30 日三路独立成功仍为 `CANNOT_CONFIRM`。源证据见原 [任务书](https://github.com/lexi2016/v4/blob/e72607634d46146b0b6c0f4a0396f6b2939589f7/handoff/selection-output-reuse-issue-20261010-r2/README/CHAT_HANDOFF.md) 和 [当前链记录](https://github.com/lexi2016/v4/blob/e72607634d46146b0b6c0f4a0396f6b2939589f7/handoff/selection-output-reuse-issue-20261010-r2/CURRENT_CHAIN.json)。

## 1. 公告：修复辅助构建身份，继续找当前原产物

现役消费者依次经过 `manager_research_router`、`service.get_workspace`、`workspace._compute_workspace`、`workspace_daily_channels.build_daily_channels` 和 `workspace_announcements.read_analysis_consumption`。

旧成功入口 `ops/run_manager_daily_announcement.py` 已保留。其 `register-handoff` 先将审核回执纳入基础产品，再建立原选股扩展。本次修正 `build-reviewed` 的基础 SHA 顺序，使相同有效输入与原注册路径得到相同完整产品。注册、审核、来源验证以及原 import 入口均保持原样。

还实际复现了旧 CLI `readback` 与当前完整 owner receipt 的不兼容：原 API 的 `consumption_validation.status/validation_status` 已为 `VERIFIED`，旧 CLI 只构造日期和 SHA 的临时 product，却被新增完整绑定校验拒绝。固定仓库 [既有修订](https://github.com/lexi2016/v4/blob/e72607634d46146b0b6c0f4a0396f6b2939589f7/handoff/manager-three-channel-repair-20261009/after/api_r3_candidate/ops/run_manager_daily_announcement.py) 已有正确实现；本轮只逐字复用其中 `_readback` 及所需 import，使用现有完整 `validate_owner_analysis_readback`，没有替换整份旧 runner 或放宽验证。

当前 `ANNOUNCEMENT_EXACT_DATE_PRODUCT_NOT_CONSUMED` 只表明精确日期产品没有通过消费。缺产品、未完成 review、未注册、未导入或晚于 cutoff 的区别，必须读取原 owner 当前日期回执确认。不能由这个聚合 gap 推导出“修补 build-reviewed 后必然恢复”。

真实 reader/reviewer 输出不在包内。一次新的导入会产生真实当前 `available_at`；若研究 cutoff 早于该时间，消费者应继续拒绝其作为原时点已可用产品。重新运行真实历史公告研究可以产生新研究结果，但不能回写为目标日当时已完成的自然运行证明。

## 2. 港股通：原 producer root 与 consumer root 必须对照

原 [hk_capture_gate.py](https://github.com/lexi2016/v4/blob/e72607634d46146b0b6c0f4a0396f6b2939589f7/handoff/v4-running-source-20261005/canonical/ops/_macos_research_panel_daily_parts/hk_capture_gate.py) 从实际 `--hk-asset-root` 推导 `store_root = asset_root.resolve().parent.parent`，把它传给 `ensure_hk_security_master(..., membership_only=True)`。它并不以 Manager 的 universe 环境变量决定发布位置。因此可以有针对性地比对这两个真实配置来源，不需要猜目录。

原 [hk_universe_preflight.py](https://github.com/lexi2016/v4/blob/e72607634d46146b0b6c0f4a0396f6b2939589f7/handoff/v4-running-source-20261005/canonical/stage_center/hk_universe_preflight.py) 已取回并核验，SHA256 为 `9d3d2c2d5ff3bd1c7713a9485e88000ae882f58b0a457b734656094606ba2941`。这只是固定源码参考，不能直接覆盖当前服务的 owner pin。

原 `read_universe_evidence(require_v2=True)` 校验目标 artifact、manifest、receipt、current、capture、publication 六文件；V2 membership 从两个完整 retained SDK frame 派生验证，不按旧 V1 固定计数猜名单。

原 [ensure_hk_security_master.py](https://github.com/lexi2016/v4/blob/e72607634d46146b0b6c0f4a0396f6b2939589f7/handoff/v4-running-source-20261005/canonical/ops/ensure_hk_security_master.py) 保留已存在且验证通过的 publication 字节；缺 publication 时用实际当前时间写 availability。现在补发不能证明历史 cutoff 前已发布。

原 [hk_market_capture.py](https://github.com/lexi2016/v4/blob/e72607634d46146b0b6c0f4a0396f6b2939589f7/handoff/v4-running-source-20261005/canonical/ops/_macos_research_panel_daily_parts/hk_market_capture.py) 会先执行 membership callback，再抛出 quote/snapshot 错误。panel 失败不能单独证明 membership 未发布。

若目标 authority 失败，完整 `read_scope` 还可能读取既存 D-1 capture/dispatch 回执及其关联源，仅将结果保留为 `previous_session_capture`。诊断工具应记录这些条件绑定；D-1 不会替代精确目标日 V2 authority。完整步骤见 `HK_CONNECT_LOCAL_REUSE_RECIPE.md`。

## 3. 超跌：找到原 publisher，单位证明仍无可接入产物

固定 [10 月 9 日 source manifest](https://github.com/lexi2016/v4/blob/e72607634d46146b0b6c0f4a0396f6b2939589f7/handoff/manager-daily-failure-20261009-r3/package/source_manifest.json) 指向原 HK02 publisher：

`/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260923-hk02-owner-rebase-r2/app/upstreams/v3_shared_data`

原入口 `scripts/update_hk_0_2_panel.py` 调用 `shared_data.hk_0_2.update_hk_0_2_panel_from_vipdoc`。该历史入口 SHA 为 `45d31c1e6608d1a9af163ffd56ea111d5caeb40000c58cd140534cf81859634e`；原 [hk_0_2.py](https://github.com/lexi2016/v4/blob/e72607634d46146b0b6c0f4a0396f6b2939589f7/handoff/manager-daily-failure-20261009-r3/package/source_snapshot/hk02_updater_actual/shared_data/hk_0_2.py) SHA 为 `45a5091cb26800b7ccf8d7c3c75b680e951d492ac8ceb5f30b80a1ff9a6eebac`。这些不是 10 月 10 日 live pin 的替代证明。

这套 owner 的 native observation 明确为 `NEW_INCREMENT_ONLY`，volume 字段是 offset 24 的 `uint32_le`，decoder scale 为 1，同时单位为 `None / NOT_PROVEN`，provider finality 也未证明。它不覆盖继承历史的尺度。原 daily supplement 及其后续已检查修订同样保留 `None / NOT_PROVEN`。

当前 `_screen_panel_volume_evidence` 与 supplement 适配器都保留 `NOT_PROVEN`；screen 要求 `OWNER_VERIFIED` 才能完成 volume/history 判断。这与包内 693 pending 相符，但包内计数不足以逐行证明现场实际原因。

本次 80% Decimal 修补只纠正价格比较。若原 owner 从未提供六个比较日的真实 unit/scale 证明，单纯重跑、补 JSON 标签或把 decoder scale=1 当作单位证明都不能解决缺口。后续需要先取得原 provider/owner 可验证证据，再在同一原 owner 合同和 reader 上按证据接入；目前尚无已检查到的兼容产物可直接复用。九份支持源码来源与 SHA 见 `provenance/OVERSOLD_OWNER_REFERENCES.json`。

## 4. Stage：继续复用原不可变产物验证，不改算法

固定源码的原 API adapter 调用：

```python
project_shared_selection(
    shared_selection_consumer.get(
        target_trade_date, 'STAGE_0935_0940', markets=('HK_CONNECT',)
    ),
    limit=50,
)
```

原 [consumer.py](https://github.com/lexi2016/v4/blob/e72607634d46146b0b6c0f4a0396f6b2939589f7/handoff/v4-running-source-20261005/canonical/stage_center/consumer.py) 与 [store_verification.py](https://github.com/lexi2016/v4/blob/e72607634d46146b0b6c0f4a0396f6b2939589f7/handoff/v4-running-source-20261005/canonical/stage_center/_selection_parts/store_verification.py) 已有目标日、stage、market、run、原 artifact/manifest/receipt、算法 SHA 和 raw artifact identity 校验；普通读取保持 `allow_backfill=False`。

正常 adapter 会返回明确 HK payload，读取失败为 `SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID`。这同时涵盖缺失和验证失败，仅靠 Manager 空行无法区分。应定位实际 reader root、`selection_latest.json` 的精确键以及对应不可变三文件。

源码支持 adapter 为 HK 查询，Manager 的 `formal_recommendation_count` 也不能当作原 A+HK Stage 结果计数。A 股必须另外验证完整同日 `a_all_pool_rows`；HK 必须验证精确前一交易日 canonical D-1 Top100。未发现足以解释本次现场事故的 Stage consumer 代码错误，故不改 Stage。五份原参考源码的身份见 `provenance/STAGE_OWNER_REFERENCES.json`。

## 验收状态

两文件三处源代码缺陷已有本地定向验证；真实 exact-pair 产物、live root/pin、数据与 PIT、API/UI、部署、自然运行均继续按缺失证据标为 `NOT_RUN`、`BLOCKED` 或 `CANNOT_CONFIRM`。包内没有可据以宣称真实新名单已产出的证据。
