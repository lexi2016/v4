# 给蔡凯：先解决 10/9 有效预选池与自动阶段运行

请先读本包 README.zh-CN.md、HK_READINESS_STATE.json、A_POOL_SOURCE_STATE.json、CURRENT_READBACK.json 和 SOURCE_MANIFEST.json。目标固定 2026-10-09，不是泛化重构 API，也不是把单元测试刷绿。

已确认：10/9 A 股主池 37 行、研究池 186 行在后台，但现役 API 仍返回空；10/9 港股只有空占位，原因是 security-master 缺 `entries["20261008"]`；现役 executor 又调用 `ensure_hk_security_master --reuse-only`。17:30/18:00 调度选中预选任务却 UPSTREAM_NOT_READY，尚未启动 producer。10/8 HK Stage 另有旧 9/30 池缺分日期来源绑定的问题。

请沿既有 owner 修复主表/价格准备依赖、精确日期 HK Top100 生成和自动调度链，让 10/9 能由原 Stage 消费。查清 UPSTREAM_NOT_READY 的具体依赖原因；不能直接删除 gate、伪造主表或旧池改日期。10/9 应使用10/8价格与10/8资格；10/8历史问题需要10/7价格与9/30资格，分开验证。

API读取修复直接复用固定 commit `2ead7eb9e9f067b69610d24990bc47f792bc75b4` 的 Issue30交付。它已在Mac独立218/218通过，但完整app真实源/经理联合canary、部署和UI尚未做。不要再重复写发布框架；以实际 active 为集成基线保留经理代码。Mac状态及候选身份见 ISSUE30_MAC_STATUS.json。

交付：最小源码diff与前后SHA、实际owner/canonical映射、必要依赖/生成步骤、定向回归、真实输入缺口、给Mac的测试与可回退发布说明。不要把本包源码切片当完整应用。当前canonical与各实际owner不同，不能整文件跨版本替换。

成功条件：10/9有效预选池准备 → 原调度器实际启动并完成 → Stage绑定正确输入并产生可验证run/artifact → 8873同日期API与重载页面一致；自然时段另有receipt。正常空选可成立，输入缺失不算成功。第一轮09:15触发前完成必要输入和本机发布验收。

用户会把你的代码交回本机会话做测试、独立验收和发布；本机已有该目标的必要可回退研究服务发布授权。不得自行扩到交易/BUY、其他服务或历史数据重写。保持三项安全flag false；不建立第二producer/面板，不因可选A子池为空而全局阻断。
