# 云端第三轮：原采集链、跨日页面与原超跌修复

2026-10-10。基线仍为164c010c7eaa1659db9bfed0ff5f123c7a39eefc，工作分支v5/cloud-preview-20261010。不是完整业务上线；原01—18/P0—P5范围不变。真实392原件尚未获准转移到云端，未上传Mac原始数据。V4、Mac61796、既有桌面预览不变。

## 已实现

- Mac发布交接e0a6bc36f9563df6a4e0f37d4e16a59e14347227，patch SHA757fff2254cdb714946f6efdeb4675c86bbc97ea41f5df0556bd290348bd9804的三处TS修改已经核SHA合并：CURRENT_RECOVERY严格身份校验、同run日通道接受、明确现在回看且非历史可用的标签。managerWorkspace保留先前云端DTO声明，未整文件覆盖。原三项真实run测试仅增加显式fixture路径，不把合成样本冒充5b4feaf7ef7d4d13bec639e90b6d3db0。
- 美股完整原producer闭包48文件，包括原交易日历，固定于164c010。原24行业代理/33证券范围与原CLI/存储未缩为四键演示。新增source-only组装、逐字SHA核验、隔离标记输出入口。受限transport通过原transport参数注入；代理CONNECT拒绝不再触发direct fallback。此前被拒绝的实际来源未重试。
- 超跌原修复模块从既有审核源码移植：40084ee的日期兼容+2bfb身份修复，依赖ebe5944原解码器及固定source manifest。没有改公式或解除门禁。原测试缺真实请求现在显式ERROR，不skip。
- 原前端测试适配实际折叠交互、10个已存在请求及保留标题；缺失真实JSON通过显式路径绑定，缺失继续FAIL。689行原测试原有skipIf已移除；缺真实原件也明确FAIL。并行DOM加载等待放宽到有界5秒，完整组件case上限15秒，业务断言未删除。

## 实际验证

原始日志及每条程序独立exit在 `/workspace/v5-evidence/round3`；同目录索引只记录SHA不上传原业务数据。套件存在重叠，不累计为总通过率。

- 完整原美股闭包+transport：12/12，exit0；含原CLI→原store三件失败产物，模拟6次代理CONNECT403、0次直连，原退出码2/NO_LANE_READY/CANNOT_CONFIRM。测试socket/DNS被审计钩子拒绝，未访问实际来源。
- pinned collector assemble/check-only：48文件核验，exit0；network_checked=false，capture_executed=false。
- native身份与跨日保存/普通auto：8/8，exit0；原根不可变，错误binding/SHA/日期拒绝。
- 原超跌repair/identity/date：49项，48通过、1ERROR、0skip，exit1；唯一错误V5_REBOUND_REPAIR_REAL_REQUEST_REQUIRED_NO_SKIP，缺真实请求，不是准入通过。
- 原超跌raw decoder：22/22，exit0；合成原始字段，非真实行情/单位证明。
- 独立前端CURRENT_RECOVERY+实际缺源响应+日通道绑定：7/7，exit0；合成恢复响应没有发布。
- 全量UI、完整typecheck及build最终结果见本文件末尾；真实fixture缺失保留，不称全绿。
- 首轮/第二轮全量Python613项0failure/19error/0skip仍是此前本云端执行记录，不重记为本轮新通过。19项是18个公告真实输入及1个US真实输入缺口。
- 父线程09:43回报：旧便携包在另一个云端桌面CDP Chromium完成实际DOM/截图并展示给用户。属于该旧包云端桌面首屏；不是本容器内置浏览器、不是Mac IAB，也不是本轮新静态包的视觉验收。

## 原链条核查与真实阻塞

美股：原materialize_us_market_phase→phase_publication→phase_payload→Tencent/RSS→ResearchPeripheralStore闭包已具备。当前research映射仍要求原行情三件套、native身份、材料归档和两路径完整性；四键seed不代替真实完整范围。环境HTTP(S)代理已正常配置到平台proxy:8080且无内嵌凭据，不是简单“缺代理”。实际403发生于CONNECT、未取得上游HTTP响应。平台需确认qt.gtimg.cn及news.google.com正常出口许可；本轮没有修改代理/换出口/隧道/增权。新增shim没有重试旧拒绝来证明。

公告：原Eastmoney目录np-anotice-stock.eastmoney.com/api/security/ann及正文np-cnotice-stock.eastmoney.com/api/content/ann链已经定位。新批目录精确读回失败，持久policy仍BLOCKED/BODY_BATCH_TRANSPORT_CONSUMPTION_UNKNOWN；不清门禁、不换根重复采集。原receipt只有脱敏URLError，不能断定与US同一403。真实独立Reviewer签名未生成。原392合法产物原件传输仍待用户授权；计数不能重构。

公告迁移还有路径身份障碍：announcement_offline_reader校验binding.owner_root==本地root，DecisionRevisionOwner与verify_recovery绑定revision_root和parent_root。修订根本身不等于完整父级恢复依赖。必须先取得原binding/revision/recovery/source manifest、逐文件SHA和父依赖闭包，设计显式只读迁移映射并单独负向验证；不能改写原JSON、SHA、Reviewer、伪建/Users或扩大权限。当前没有声称云端能直接接受Mac路径。

超跌：原post-close read_rebound_screen是close<=0.8×prior60最大值、volume>=1.5×prior5均值两门；15:30 manager_close_rebound另有成交额与反弹四门且非final，不能混算。原update_hk_0_2_panel从VIPDOC ds/lday/71#*.day读取32字节记录，不是HTTP下载器；最低500证券/80%正值覆盖，already_current不能补历史缺口。PyTDX六日不能证明67窗口。已有rebound_observation逐证券缺prior60/previous5日期与重复日诊断；不造near1。Mac清单所示历史面板只到20260807，VIPDOC未找到；694 HOLD、单位/币种/finality/资格和信任来源缺口不变。

## 原01—18与P0—P5剩余项

详细逐项清单和七项Mac迁移/回滚见RESULT.md，后续工程修正见INCREMENTAL.md。以下更新覆盖旧文中已过时项，其他原范围全部保留：

| 模块 | 本轮后仍缺 |
|---|---|
| 01 A来源 | 真实producer/当前面板、source receipt、新日05/09一致 |
| 02 HK来源 | 原行情/主表/Connect资格、单位及获取时点 |
| 03 US来源 | 原网络许可、真实完整行情材料、自然session接续 |
| 04 归档 | 真同批builder/source/获取时间，natural_verified=false |
| 05 A预选 | Linux UTC工程已修；七池真实生产/完整消费/新日 |
| 06 HK预选 | 工程通过不代替Mac原100行及新池资格/权重 |
| 07 A阶段 | 真实窗口五价、完整池、竞价/Stage/API/UI |
| 08 HK阶段 | 原资格/06池、真实窗口半日、Stage7/8/API/UI |
| 09 A复盘 | 真收盘/原算法/次日池、slot自然验证 |
| 10 HK复盘 | 原权重/收盘/次日池及自然slot |
| 11 研究/复盘 | 原真实触发/材料归档/节点恢复/API/UI |
| 12 视频 | 原获取/转录/节点产物及合法登录 |
| 13 公告 | 原392数据许可、父闭包/路径兼容、独立审核、同run |
| 14 超跌 | 原VIPDOC历史窗口/单位/资格/真实请求；694 HOLD |
| 15 US映射 | 原两路径完整行情材料/native，非四键演示 |
| 16 公开资料任务 | 原队列/合法来源/持久worker与普通API |
| 17 尾盘跟踪 | 首次窗口真实记录、价格/资格与后续跟踪 |
| 18 经理计划 | PARTIAL同run已证；三策略真实结果、新包视觉、自然恢复 |

P0部分隔离/版本/运行已证，owner锁与调度未齐；P1三策略真实退出未过；P2池/来源真实闭环未过；P3窗口/收盘未过；P4辅助真实链未过；P5连续两适用交易日与完整回滚未过。

Mac后续：保留61796/V4/8910→固定commit另根组装→逐字核原件和迁移身份→按三条真实链分项重放→Mac独立回归及内置浏览器同run/历史拒绝→另端口候选核配置静态进程→失败仅停候选并恢复原路由/配置；原数据不回写、不删档、不开交易。云端通过不抵Mac完整验收。新版只读便携包继续使用同一已保存PARTIAL响应；用户正在看的旧桌面服务保持不动。

## 最终前端结果与命令

全量37文件436项：419 PASS / 17 FAIL / 0 SKIP，exit1，111.74秒。17项全部缺原始fixture：公告4、Mac真实CURRENT_RECOVERY3、100行观察1、Eastmoney2、issue8R2六项、真实689行projection1；没有剩余组件工程失败。完整typecheck exit0、build exit0。20条overlay源码SHA和实际build工作区逐字相等。

```bash
V5_SYNTHETIC_CURRENT_RECOVERY_RESPONSE=/PRIVATE/synthetic-current-recovery.json V5_CLOUD_WORKSPACE_RESPONSE=/PRIVATE/http-workspace.json npm --prefix /workspace/v5-build/apps/web run test -- --maxWorkers=2
npm --prefix /workspace/v5-build/apps/web run typecheck
npm --prefix /workspace/v5-build/apps/web run build
PYTHONPATH=V5/src V5/.venv/bin/python -B -m unittest discover -s V5/tests -p 'test_cloud*.py'
PYTHONPATH=V5/src V5/.venv/bin/python -B -m unittest discover -s V5/tests -p test_rebound_raw_repair.py
V5_REBOUND_REPAIR_ORIGINAL_TESTS=1 PYTHONPATH=V5/src:V5/tests V5/.venv/bin/python -B -m unittest test_rebound_panel_repair test_rebound_owner_identity test_rebound_date_compat
```

原始日志包含此前红测/失败版本，并未用最终结果覆盖。新静态包视觉仍待父线程云端桌面另目录另端口验收。
