# 云端增量修复与证据（2026-10-10）

本轮不重跑真实采集。首次记录见 RESULT.md；本增量覆盖其中已定位的工程失败，不改变三策略真实业务仍阻断、natural_verified=false、Mac未验收的结论。

## 断连核验与运行边界

收到09:18:42 disconnected通知后，09:20:31 UTC实际shell、Git远端、loopback HTTP均成功。原PID2923/2924/2925仍在，启动时间09:03:36，未重启或新建环境；经理GET200。未提交修复仍在/workspace/v5-cloud。此结论来自实际执行，不来自inProgress状态。容器生命周期之外不保证持久服务；若后续确实失联，应从平台恢复此原保存环境并核工作树/进程/日志，不另建采集根或重复请求。

入口仍为 http://127.0.0.1:18896/manager-selection/?date=20261012 ，只在本容器内可达；没有已验证的父线程可达入口。未找到内置/托管浏览器工具；Chromium二进制没有被当作用户要求的内置浏览器使用。视觉、截图仍NOT_RUN。

原完整计划固定为 `d1bf034640ca2e5957423de2745a98e159b69af2:V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md`，已对照01—18原编号与P0—P5退出条件。

09:25:53完成源码提交后，仅重启这三个已核云端候选进程到固定5f96689；新PID6919/6920/6921，后续访问核验见TEST_RESULTS.md及increment-http.json。

## 新修复及边界

1. A预选Linux UTC固定别名：原pandas→dateutil→open('/usr/share/zoneinfo/UTC')进入guard，Linux别名Etc/UTC被原Mac特例拒绝，错误A_INPUT_PATH_NOT_DECLARED。仅核固定别名和无symlink的固定普通目标，未开放整个zoneinfo目录、用户symlink或环境TZPATH。真实guard子进程同时验证UTC成功、New_York/用户link/etc/passwd仍拒绝。RED日志保留；A/HK相关45项通过（128.158秒）。
2. 周末/跨日合成测试：仅测试夹具通过子进程测试入口替换指定datetime seam，不改业务时钟，不提供运行时配置后门。交易日夹具固定10/9；新加10/10闭市仍拒绝、次日隐藏过期观察断言。29项通过（33.615秒），不能作为自然时段验收。
3. 经理CURRENT_RECOVERY：原revision测试包绑定后出现saved run与auto run不一致。按已发布2bfb4c8c5f770122077e3baf914cf5b05b8a2450 manager/changes.patch，选取manager_plan与相关测试最小修复。迟到当前研究保存到独立current_recovery根，ordinary auto读取同target确切journal；明确historical_eligible=false，显式历史继续原门禁。未改vendor、股票准入或历史产品SHA。测试包括旧根不可变、其他日期不得选用、缺exact journal拒绝、SHA篡改/未来cutoff/symlink拒绝及普通HTTP同run。
4. 前端旧断言：row({})没有owner observation，应为未读取，不能推成NOT_RUN。修正测试夹具为权威同target NOT_RUN三段回执，保留“不是0公告/受限手动”断言，并新增缺字段不可推断用例。产品UI逻辑未为测试降级。前端经理目录146通过/3失败，4文件失败（2suite缺JSON）；全量403通过/20失败，35文件中29通过/6失败，exit1，117.03秒。

## 来源失败与不能由本轮代码修复的缺口

- US实际第四次capture的保存退出码为2，不是shell末尾tail的0；原文件SHA在RESULT.md。6份quote/feed回执均proxy_used=true且fallback_used=true。原ProxyAwareHTTPTransport.fetch把URLError包装为TransportError后，**确实自动尝试了direct fallback**；此前“未更换代理”只描述没有手工改配置，不能表示没有内置fallback。错误是`URLError:<urlopen error Tunnel connection failed: 403 Forbidden>`，http_status=null，未取得上游响应。审查后没有再次访问这些目标或绕过代理；需要平台正常网络配置明确允许原目标/代理路径，并在后续运行前审查CONNECT拒绝不可fallback的原transport行为。不能通过换域、关闭代理、增权或新根重试解决。
- 公告原_capture在目录精确读回门处退出：readback_status必须VERIFIED，内外target/publication匹配、catalog COMPLETE且safety字段可判定。失败发生于正文evidence目录创建之前，不能用旧offline serialization修复当作新目录成功。持久policy BLOCKED/BODY_BATCH_TRANSPORT_CONSUMPTION_UNKNOWN，requests=1，unknown=1，bytes=0；原page receipt只给脱敏URLError/CANNOT_CONFIRM，不能断言它与US同一403。原begin_capture拒绝已有未FINISHED/stop/date记录，因此不能resume、换根清零或跳门。真实Reader/Reviewer宿主和合法输入未绑定，不伪签。
- 392条完整原件仍未取得；计数/run/SHA不是重建数据依据。归档真实同批builder source仍CANNOT_CONFIRM。
- 超跌需要原TDX VIPDOC历史panel、单位/币种/价格finality及Connect资格，或已准入的Futu/OpenD源。已发布PyTDX日线sidecar最多6日不能替代prior60/67cells；历史Futu配额不是本次登录授权。694 HOLD不变，不将合成near1提升真实入选。
- UI缺失原件：issue8R2.ownerObservations.json（2suite静态导入失败）；manager_current_observation_20261002/FIXTURE_BINDING.json；Mac Eastmoney integration/workspace_after.json（2个case）。已查相关已发布cf306997、e9b91cc9、0f3494b4树，未发现完整文件。保留失败，不造JSON、不删用例、不把缺真实fixture算成通过。

## 测试执行与后续

完整原始日志/单独程序exit文件保留在/workspace/v5-evidence/increment；仅精简错误与hash索引进Git。套件重叠不可相加。合成回归、真实失败产物保存/读回、真实成功原批重放、真实新采、UI视觉、自然接续分别记账。最终统计由同目录TEST_RESULTS.md记录。

原01—18模块与P0—P5范围、Mac迁移/回滚七项清单沿用RESULT.md；仅M05 Linux工程边界、M18迟到当前读回及合成测试定位取得增量。M03网络、M13正文/审核/合法392原件、M14原准入/历史行情仍为P1实质阻塞；不能宣布首批、18模块或Mac验收完成。

全量前端新增暴露：src/views/ManagerSelectionView.spec.ts有13个失败（原V4静态标题断言与明确V5云端标题不同、旧fetch计数8对实际10、区域/文案/状态断言不匹配及2个5秒超时）；不归入缺数据，也不直接判定全是无害旧断言，仍需结合原套件/当前UI合同及指定浏览器继续验收。另src/api/managerWorkspace.announcementReview.spec.ts四项缺Mac ANNOUNCEMENTS_20261001/02.json。当前实际缺源响应的单次auto DOM测试通过，不能替代这些未通过的场景。

父线程09:29补充：Mac恢复后已只读核实其前端另一组3TS+1测试patch SHA为757fff2254cdb714946f6efdeb4675c86bbc97ea41f5df0556bd290348bd9804，尚未确认Git发布；云端未取得/未声称同步。本轮2bfb只应用选定最小diff，没有用其manager_plan.py整文件覆盖当前候选；native_master输入校验、身份读取/安装、security_master_root及_identity依赖均保留。e06d和2bfb明确只是合成测试材料，真实392正文与全文决定仍未在云端取得。Mac仅Chrome亦不算IAB验收。
