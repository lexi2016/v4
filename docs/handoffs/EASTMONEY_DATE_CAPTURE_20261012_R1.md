# 东方财富港股指定日期采集实测 · 2026-10-12

用户目标：复用既有东方财富按日期分页 owner 获取当天全部港股公告目录，再本地筛港股通，获取图达通当天出货量公告正文并实测耗时。

独立 Reviewer 结论：REVIEWED；目录和图达通正文 BEHAVIOR_VERIFIED。港股通交集 CANNOT_CONFIRM：当日完整资格产物缺失，不代表零条。未改业务源码、部署、服务、计划任务、模型或交易门禁。目录完整性仅针对东方财富在本轮抓取时刻返回的指定日期列表，不代表披露易全集或当天后续新增已捕获。

## 实测

香港时间 16:54:59.802418 至 16:55:01.169203。唯一 canonical 源码根为 /Users/lexi/Desktop/学习/v4_app，实际执行 DIRECT_CANONICAL_OWNER，调用同一 ManagerResearchJobService/日期 collector，沿用已确认共享 Manager state 与 MaterialStore。不是 HTTP refresh；本批 API/UI、部署和自然时段验收 NOT_RUN。

- 日期 2026-10-12；目录 COMPLETE/VERIFIED，102 条，102 个唯一 art_code，重复 0，gaps 0。
- 页行数 [20,20,20,20,20,2,0]；6 数据页、第7页空终页；7次新鲜目录网络请求、0缓存。
- 目标 HK.02665，art_code AN202610121830339681，标题“自愿性公告 未经审核之二零二六年第三季度激光雷达出货量”。
- 正文 COMPLETE_CONTENT_API_BODY，1/1页、1570字符，证券/标题/正文原始响应绑定通过，包含实质出货量内容。1次新鲜正文请求、0缓存。
- monotonic：目录 owner/read 1.016740秒，正文0.264478秒，名单读取/筛选尝试0.002002秒，端到端1.366809秒。端到端包含初始化/验证；工程准备及纯准备时间没有独立计时，CANNOT_CONFIRM。
- 港股通当日权威文件 universes/20261012/HK_CONNECT_FULL_MARKET.json 缺失（HK_UNIVERSE_V2_ARTIFACT_MISSING）；现有旧文件仅覆盖20260810—14。未用旧名单、693 identity master或Top100替代。交集数量、名单SHA及有效日期 CANNOT_CONFIRM。

## 验证与证据身份

使用原Mac v3.5-mac Python研究环境。Writer运行捕获脚本并离线复核；Reviewer以只读方式独立运行 canonical validate_product、verify_product_sources、_validate_catalog_owner_receipts、audit_saved_body_identity，核对原始响应、跨文件SHA及正文全文绑定，不调用provider、不重抓。最初包装校验误用了页identity和字符数字段；原results.json和首轮失败记录保留，过程脚本离线纠正后另存reconciled结果。没有业务源码修复。项目测试套件 NOT_RUN；Reviewer的核心独立重算PASS。

Reviewer无P0/P1；非阻断P2为过程脚本字段兼容分支缺直接回归测试。现有共享源码树有并行tracked/untracked修改，未将其纳入本次交付。

本地证据根：/Users/lexi/Desktop/学习/agents调试/V4_EASTMONEY_DATE_CAPTURE_20261012_R1/
- 目录 owner run_id d539992bd01a433facfd445d2d23d1f1；产品SHA 0424c1108609ea97be0fcd491ca1b3cfd323cdb43fbd930a6b60570527f9bae1。
- capture_and_verify.py SHA 5967f006e5e802294fa7d2ed7d9b2d80dc0e950b4358c006e1939c9815b5b5af。
- results_offline_reconciled.json SHA bdb443aba9e26c4a49b198682fe3d31ab0e78192a47575be30e2e52be88f5160。
- offline_verification.json SHA f072fd6a4512759b8cc0cef30327e5a0a0f2f741f28f4000f02b9a85d03284ca。
- 公告SUMMARY.md SHA a2e328334b6353d9bc545b4cc81ac7e168737fcf8939fcaac4f7b1ea92c56668。
- 正文文本SHA e212d2aae5a419a6b3c15eb38c05993f2ba094fff6cd26aff966b9fecf9a7e01；本地正文文件body_capture/bodies/AN202610121830339681.json。

## 官方上下文默认配置核验

用户另要求以后自动跟随官方默认。独立只读审计：五份Codex TOML解析通过，model_context_window、model_auto_compact_token_limit、model_catalog_json全部缺省；无需写死500k/1M，配置未改。官方CLI codex debug models执行一次、exit0，但stdout272k与当时cache500k不同。官方模型缓存16:53:41香港时间曾为500k、有效95%；17:07:25又读到272k、有效95%。人工未改cache、未再次刷新、未重启客户端。更新触发者/原因及活动会话500k均CANNOT_CONFIRM，不能把历史500k快照当当前生效。CONFIG_AUTO_DEFAULT_VERIFIED；当前CATALOG_500K与ACTIVE_SESSION_500K未确认。

## 交付边界

本次仅同步精简结果，原始公告响应、正文/PDF、业务数据、认证、全模型缓存均仅留本机。源码和配置无本轮业务修改，不上传并行变更。RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。

远端交付基线 b123f8a49f60f3c8d0db4348a997fa59e8a32537；本机工作树HEAD 55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054，二者不能互作已部署身份。分支codex/eastmoney-date-capture-20261012-r1；本文件新增，前SHA不存在，交付后文件SHA由远端读回核验。
