# PR20 R5：HK 9/29真实历史恢复与来源合同收口

固定输入：`7ec9bceedceb56af97f4d365451d8560860cbc09`。

## 业务目标

本批只处理HK。A股保持冻结，沿用最新owner报告的A 21/21适用API格和新增Stage UI已验状态。

1. 在既有`macos_research_panel_daily` collector/gate与既有shared HK 0.2 updater中加入明确的历史缺口恢复模式。历史行情通过Futu `request_history_kline` 精确读取目标日，记录真实request/receive时间；不生成9/29伪`captured_at`。
2. 复用既有`recover_hk_connect_universe`人工恢复机制，扩展为同一官方生效日的多只delta。9/29官方调整是03228、09607两只；父authority仍须是已验证9/28完整成员，当前Futu仅作为恢复时刻的完整集合corroboration，不冒充9/29自然capture。
3. `natural_verified`在当前权威reader合同中恒为false。本批R9 store和Stage都显式拒绝true。
4. HK证券开市、港股通休市时，价格日取上一HK证券交易日，资格as-of取上一HK Connect交易日。自然owner不会把今天名单回填为旧as-of，也不会在旧as-of主档缺失时用今天元数据静默补旧日期。
5. 历史9/29价格缺口插入现有panel时重新计算跨日连续性，使9/30的pre_close/pct_chg链基于真实补入的9/29，而不是保持跨缺口旧值。

## 修改范围

10个既有文件，分三个实际根：
- R9 preselection app：publisher、history collector/gate、projector、owner、pool store；
- shared package：严格universe reader、security master as-of reader、HK0.2 updater；
- Stage app：严格HK D1 validator。

不新增producer、panel或BUY机制。未改A代码、经理、F5、Vibe、服务配置。

## 当前证据与边界

Mac此前对46ff1ef R4限定组合已独立27/27、exit0；本批不重跑这些旧用例。
作者新增纯合同TDD：RED 2 pass/8 fail/exit1；GREEN 10 pass/0 fail/exit0。该作者测试只验证合同，不等于10个实际模块的Mac组合验收。
本批另交付实际模块目标测试`tests/test_hk_history_r5_target.py`，状态NOT_RUN，交给Mac用当前Python3.14.6和实际依赖执行。

9/29真实价格尚未批量读取；现有证据只有单股HK.00005历史接口成功样本。9/29资格authority尚未写入；恢复必须先尝试原authority，缺失时才允许用已验证9/28父authority＋官方9/29生效变更＋当前完整集合corroboration生成MANUAL_RECOVERY，并保留10/2真实恢复时间。

因此本提交是代码候选，不是9/30 D-1池、Stage/API/UI或自然运行恢复结论。

RESEARCH_ONLY；production_allowed=false；buy_gate_updated=false；orders_sent=false。
