# R2 现有权威来源七项核查

只读核查终态 CANNOT_CONFIRM；没有计算新Top20、修改源或抓取行情。以下是本机现有事实，不是全港股通成员数量的外部认定。20260911对象仅用于核查既有合同，不计前瞻样本。

|事项|现有证据|缺口|
|---|---|---|
|成员authority|stage_center/hk_universe_preflight.py 与 upstreams/v3_shared_data/scripts/live_acquisition/universe.py 声明 FUTU_HKCONNECT_PLATE_MEMBERSHIP；HK.GangGuTong/HK.LIST1922；schema v3_shared_data.stage_universe.v1 及 authority manifest/receipt/current v1|指定20260911 formal universe目录缺失；代码内该日canonical651是现有合同约束，不是本轮验证的真实全市场数量|
|成员实际artifact|security_master 20260911有691行、code字段；artifact SHA59d884d3854428803f15865a18e2fd594c2251e2c538dbb8fa92a23ec7044b01；manifest SHA87f3cd14c9720a3a9541cc87ff5d513e4e22d474ed00623fcb4043dc75ce1177|producer在formal universe缺失时fallback到HK0.2 panel；manifest未直接绑定历史panel SHA，不能提升为正式成员authority|
|收盘source|ops/collect_hkconnect_close_snapshot.py；infrastructure/hkconnect_close_store.py；schema v3_5.hkconnect_close_snapshot.v1，source FUTU_FULL_HKCONNECT_CLOSE_SNAPSHOT|20260911有691行READY/coverage1，但只证明这一收盘文件及内部覆盖，不证明member authority|
|涨幅语义|pct_chg_close=round((close/pre_close-1)*100,8)|缺复权/公司行动/reference语义，不能自行替换为raw小数公式|
|最终收盘|producer新采集限制16:10之后|payload无finalization timestamp/final_eod标志或source update aggregate；READY不等于FINAL证明|
|同涨幅排序|close rows无rank或source tie-break|不可把shadow内security_id ASC提升为source authority|
|停牌处理|security_master有sec_status，close source无对应join/policy；错日或非正close/preclose会跳过|不能自行剔除或填0；缺明确政策时truth不准入|

## 既有数据路径

正式authority缺失目录：
`/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/universes/20260911/`

观察到的security-master run：
`/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data/assets/hk_security_master/runs/20260911/99c790b7455f21f6d342a13c/`

收盘payload：
`/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/hkconnect_close_snapshots/20260911.json`
SHA256 `079614febec8ba5b7a94d1a05e758aec73d75f0f2352e87502b6283e26bfcd18`。
receipt路径`state/data/receipts/hkconnect_close_snapshots/20260911.json`，其SHA `e4c2f3d03024ec365b42438ce7d6163e41517239c72baa7cc45c4dc44468abbe`；receipt绑定payload身份，但不证明FINAL。

## raw hash映射缺口

20260911 selector run-857d9ee5d6f22d5f48ce38fd声明raw_artifact_sha256=ba0fafbfcf933231d35a1e58489edf561586437a721752179b69106777319433；定向查找未定位到相同实际源文件SHA。另有active_snapshot_sha256=6af8bed48810c0656d1f070db84eb22b53aed1f57281b8e7bd927f59558e27a4，D1 JSON/source SHA，未找到它们到raw hash的既有manifest映射。不能凭这些声明创建合格前瞻输入。

## 反馈给Chat的裁决事项

请依据既有producer事实给最小下一步合同，尤其明确：成员authority缺失与691/651差异交哪个现有owner修复；FINAL/涨幅语义/tie-break/停牌政策需要什么现有证据或明确冻结决定；raw hash关系未证时是否仅保留capture拒绝。Codex不自创规则，不新增平行源，不继续历史恢复。未启动自然canary。
