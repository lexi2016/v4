# PR20 HK R9最小返修 R4

固定输入：`3bcb43884cfa54fecf6eea88b0450279ffd07ab5`，PR20分支 `codex/hk-owner-asof-r3-mac-review-20261002`。新增此增量目录，不改原R3/独立Mac反馈。A股21/21普通适用API格及新增Stage UI既有已验状态保留，不重开A。

## 实现与尚未实现

已改两个活动运行文件：真实R9 `preselection_pool_store.py` 接受并校验HK专属来源扩展；R3 active `executor_registry_preselection.py` 显式导入模块私有helper，修复真实R9函数重绑定丢失全局helper的问题。canonical/shared/Stage/provider/selector及A业务未改。

原19项4个owner用例不再monkeypatch不存在的registry.load_isolated_package_module，改用各真实facade已存在的方法；删除原测试合并owner+registry全局变量的伪装配。旧测试断言完整保留，没有删用例或删断言。新20项使用实际e5ead3 R9存储和真实R9 FunctionType重绑定规则，源码provider/child边界明确合成。

历史9/29未恢复、9/30真实D-1池未生成。本次GitHub原件只有缺失回执、9/28信号Top100及9/29盘前局部快照，不能证明9/29真实成员和全日价格已齐。`prepare_original_hk_history.py`仅在Mac显式指定的原owner配置根读取原资格reader、资产reader和可选VIPDOC原件；不采集、不造authority、不搬移或重写来源。真正源齐时只给出既有 `scripts/materialize_hk_0_2.py` 命令，不执行。必须由Mac后续获准执行原恢复/物化与读回。

## 存储合同

扩展仅限 `hkconnect_d1_top100 / HK / SHARED_VERIFIED_HK_0_2 / v3_shared_hk_0_2_consumer_v1`。`historical_provenance`、`source_manifest_sha256`、`source_receipt_sha256`必须成套，校验原v2/v1 schema、完整SHA、run对应、source/price/target和timezone-aware实际capture。不是把字段直接放进通用allowlist。其余未知顶层字段、A携带HK扩展、错误身份、未来capture仍拒绝。旧无扩展产物保留原合同。

完整扩展参与原artifact canonical SHA，原receipt/manifest校验、原锁和不可变发布保持不变；不另建receipt字段合同，不覆盖旧产物。资格有效性仍采用R3已有EXACT_CAPTURE_DATE_ONLY，分别保留价格日和实际source日；不会据上一Connect日推断资格有效。港股通休市不改变HK证券日历生产路径，旧9/28和今日名单都不能重标为9/29。

## 实际测试

同一新20项：RED 10 pass/10 fail/0 error/0 skip/exit1；GREEN 20 pass/0 fail/0 error/0 skip/exit0。原始日志和JUnit在validation。红例包含存储拒绝以及R9 `_hk_owner_universe_root` NameError。A已落盘合成池的artifact/receipt和manifest内A条目不变。

作者Linux Python3.13.5，只使用`-o addopts='-W error'`处理本容器已有warning配置差异，不改环境/业务版本。实际R9 store与两个测试涉及的owner/projector源字节已核；完整R9 facade及其其余业务handler、实际publisher/shared-reader没有在作者载体完整执行。重绑定回归使用已读R9源码的FunctionType规则，不冒充完整Mac组合。原19项修订版已交付，但本轮没有宣布它重新通过；Mac需用原环境复测。

canonical旧exit1的stderr指向别组旧测试`test_require_absent_rejects_so0/runtime_graph/snapshots`在共享pytest临时根中清理失败，不是这组HK断言失败。新测试入口为本轮新建独立--basetemp，不chmod/chflags旧证据、不忽略异常；新目录自身清理失败仍报错，不假装exit0。

只读历史工具运行了缺源合成负例：exit2，CANNOT_CONFIRM，无创建源目录、无命令执行；另两脚本--help/语法检查通过。未执行实际Mac原件定位、历史数据恢复、模型物化、selection、API/UI或自然调度。

## 前像

实际R9 store：e5ead3a523c44f95f7730d1faf4b314c93954db26eab3ec34b777d956223184d。
R3已应用active owner：cf5d2d1f2cb67fe4881ff615b89b61315c8226a319bc27927a95556a31ace3e5。
详细after完整SHA和bytes在SOURCE_SHA256.json。不是原PR19活动旧前像，更不能用R9整文件覆盖canonical。旧19夹具前像也附。

不部署、不创建APPROVED、不真实采集/selection、不扩额、不延长9/30授权。PR保持Draft。
