# 数据面独立只读核查

核查目标是 20261009、09:30+08 截止；不把 10/12 问题套到 10/09。未执行 owner、补采、生成或数据改写。

## 港股通

权威根：`/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data`。

10/09 池及回执位于 `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/preselection_pools/20261009/`，回执 `receipts/hkconnect_d1_top100.json` 为 EXPECTED_MISSING，empty SHA、空行；池报告 `HK_0_2_EXACT_INPUT_CONTRACT_INVALID ... metadata invalid: '20261008'`。

security-master 的 assets/hk_security_master/latest.json 有10/09条目、无10/08条目。已见10/09 snapshot run `2624664162720b55c473d083`，采集时刻17:31:16+08，693行，晚于计划cutoff，不能代替10/08。

HK0.2存在10/08和10/09面板。10/09补充面板记录发布时间为10/10 15:38:34 UTC，属事后。10/08 manifest 的 provider session finality 为 NOT_ATTESTED，amount/trade units 为 NOT_PROVEN。精确10/08 authority、10/09 canonical D1 Top100正式发表仍未核实。

既有入口 ops/ensure_hk_security_master.py 支持 --trade-date 20261008 --reuse-only，以及 --verified-source-store-root 的已验证精确来源恢复；不能将当前capture打回历史日期。ops/materialize_scheduled_preselection.py 是现有 consumer。当前未证实完整合法输入，因此本包不给出宣称必能产池的执行命令。先恢复可验证的原输入；找不到就明确保留历史缺口。

## 超跌反弹

本次已见10/08和10/09 HK面板，但精确date/symbol的60个完整交易日、成交量来源及对应screen artifact/receipt没有闭环。结论为未核实，不等于历史数据确定不存在。要求列出逐symbol缺少哪些session/字段及既有缓存/TDX路径可否恢复，不能拿214初筛数当最终选股验收。

## 公告

55只已显示事后研究结果。未获得证明原产品在10/09 09:30之前可用的原owner回执，不能导入当时PIT名单。应把现存产品接入显式回看口径，同时修复下一实际交易日的正常生成/保存/读回。

## 数据验收不允许偷换

历史当时输入不可恢复，不妨碍修复读取错误、展示真实回看成果和完成未来日常链路；但任何一项不能替代另一项。若正常日常三路输入仍不完整，整体修复未通过，不能仅交付“缺数据”的漂亮空页面。有效零结果仅限输入合法完整、算法真实运行、原owner保存且页面读回一致的场景。
