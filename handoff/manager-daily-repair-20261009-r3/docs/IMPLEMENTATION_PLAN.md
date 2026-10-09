# R3 经理每日计划修复实施计划

> 执行范围：隔离代码、合成 fixture、可审查配置示例与 Mac 交接；不操作真实服务与业务数据。

**Goal:** 复用 R1/R2，修复当前 worker/API owner 身份断点，明确输入不足与合法空结果，保留原日期与来源验收合同。

**Architecture:** 同一原始 binding SHA 继续贯穿调度请求与 API 回执；新增明确 owner API 根身份，worker 根仍按原合同校验。所有实际计划仍由原 ManagerResearchJobService 保存；合成测试使用临时目录和冻结时钟。

**Spec:** 固定 b98d85c95d19780e2900dce7de9372328e67acf6 的 handoff/manager-daily-failure-20261009-r3/package/CHAT_TASK.md。

## 全局约束

- 保留 Issue32 app.py、preselection_router.py、preselection_service.py 三个 SHA。
- 保留 Stage、BUY、Vibe8910 与所有研究安全 flags。
- 不新增 producer、scheduler、automation、面板、发布 owner 或数据底板。
- 10/8 事后产物使用 dynamic；历史 auto 资格不变。10/9 当日 auto 要同 run/product SHA/input 身份。
- 没有合法输入时不造有效零结果，合法通道独立消费。
- 本地 baseline 是远端固定输入装配，仅作测试依赖；不是完整现役 Mac 镜像。

## Task 1：绑定与调用结果合同

- [x] tests/test_manager_r3_binding_identity.py 先复现不同 worker/API 根的拒绝与错误原因丢失。
- [x] infrastructure/scheduling/manager_announcement_supervisor.py 增显式 plan_owner_binding 校验；旧单根 gate 不变。
- [x] ops/render_manager_announcement_binding.py 生成双根绑定候选，不能写 live 配置。
- [x] v4/manager_research/plan_owner_dispatch.py 两 execute 入口统一 owner 身份校验，保留 SHA/enabled/state/master/date gates。
- [x] apps/api/v35_api/manager_research_router.py 仅对安全白名单 admission code 返回具体原因，未知异常仍脱敏。
- [x] ops/run_manager_announcement_cycle.py 保留触发状态和各类失败语义。
- [x] 两入口、legacy、源码漂移、canary、禁用/错根拒绝先 RED 后 GREEN。

## Task 2：日期与输入验收

- [x] tests/test_manager_r3_dates_inputs.py 复用原真实 route/service/store 与合成公告证据。
- [x] 每日受控 owner 路径增加合法输入就绪门；通用历史 PARTIAL 存储合同保持。
- [x] 覆盖全通道未就绪、已采集但未映射/未导入、合法零入选、独立合法通道及逐股理由。
- [x] 10/8 事后 dynamic/auto 分歧与10/9默认auto同身份读回；GET不写新plan。

## Task 3：可执行候选接续与交付

- [x] 以固定 R3 32源码快照核对 R1前像，保留R1/R2后像，分别记录 API/worker 真实前像。
- [x] 交付最新累计 API 根的有限增量与 before 门，实际 Mac 应用待原 owner 执行；不复用硬编码旧root的整树装配器。
- [x] 检查共享 owner ownership 范围；若上游policy或builder缺失，精确记载，不绕过。
- [x] 生成每路径 before/after SHA、最小patch、完整after、回滚及合成测试依赖索引。
- [x] 独立审查与所需回归已完成；固定分支提交与远端读回由最终同步回执记录。

## Review Focus

- 同一 binding SHA 并不证明实际API根或源码一致；双端都必须核实。
- 源采集成功不证明mapping/筛选完成；PARTIAL无正向证据不能计零。
- 新旧日期与cutoff不能互换；事后run不能冒充历史盘前run。
- HTTP200、进程启动、手工canary均不证明同run计划读回或自然执行。
- API与worker共享文件前像不同；不得使用同一beforeSHA覆盖不同root。

## 当前记录

- R3 PACKAGE_MANIFEST 48个payload全部字节/SHA核对通过，另有manifest自身共49件。
- 143件R3/R1/R2/本机反馈已通过Git blob完整性核对下载。
- 最终在原生 CPython3.14.8/Linux 的重新装配测试闭包完成核心235PASS；邻近parity38PASS/1个基线既有FAIL。Mac实际部署/API/UI/NATURAL待原共享owner执行。
