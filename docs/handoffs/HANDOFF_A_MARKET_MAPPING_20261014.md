# 20261014 自然监控：A股交易所映射修复

范围仅`stage_center/_live_collectors_parts/temporal_validation.py`的`_tdx_code`映射，主助手按用户要求直接处理；不修改HK策略、交易门禁或历史自然回执。

09:35自然阶段读取完整381只A股，实际分钟返回372只。其余9只被请求为SZ.510300、SZ.512100及7个SZ.920xxx：旧映射仅列出上海股票代码前缀，遗漏5开头上海ETF；北交所前缀遗漏920。修复增加`5 → SH`、`920 → BJ`，其余既有映射保持。

- 修复前实际函数复现三例均错误为SZ；修复后SH.510300、SH.512100、BJ.920826。
- `tests/test_stage_a_market_mapping_20261014.py`：10 passed，覆盖ETF、北交所920、旧北交所代码和普通沪深股票。
- 真实既有TDX采集canary：两只ETF及一只北交所股票均READ_OK，20261014 09:30–09:35各5根K线，3/3无缺失。此为事后只读探测，不写正式阶段，不冒充自然补齐。
- 运行候选实际模块6项映射检查通过。09:40旧进程保留到自然结束，空闲后切换下一次调度；部署结果见本机deployment.json。
- 候选`/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-market-map-20261014-r1/app`；manifest SHA256 `61196841e5fccd3f08877437b4c4c37b750d4f00072fc0deb888c68eb4acf559`。仅投影本文件与既有配置中的发布路径，不新增服务。
- 用户明确要求直接处理：独立Reviewer NOT_RUN；修复后的自然阶段仍待后续节点验收。

09:35港股已自然留存100/100十档盘口，请求/接收时间均在09:34窗口；100只各5根分钟原始K线，原文件SHA与文件名一致。实际raw100行，活跃过滤后4行，并非只采了4只。8873显示A10/HK4及价格指标；API执行与正式资格仍CANNOT_CONFIRM，不能将完整采集等同完整研究验收。09:25同样保留L0竞价恢复、无盘口证据缺口。

本机证据根`/Users/lexi/Desktop/学习/agents调试/V4_NATURAL_MONITOR_20261014`：0902、0932、0937各自receipt/API/UI；`a-market-map-fix`保存范围、前文件、canary、候选和部署。原始数据不上传。代码同步基于私有分支`codex/morning-preflight-20261014`提交`9fbf753c17b9bf8a2dfd106ce1224d4cc38e0147`，新分支`codex/a-market-map-20261014`；远端同步读回证据保存在本机。
