# Root 单次部署链

当前只准备控制，现役零写入。原 lifecycle R1 独审、15 checks、21事实和000523缓存/公式证据复用；本轮只增量审 controller、config/path投影、回退与首次物化路径验收。

1. 将本目录 CASE_MANIFEST、PLAN、controller、probe及原owner协调原件交同一Reviewer。要求真实回执 `verdict=PASS`、`deployment_plan_sha256`、`controller_sha256`、`case_manifest_sha256`。没有回执不执行。原业务源码不修改、不重审或重跑76/5538。
2. Root临执行读取三个实际plist、旧manifest、原Main owner及PID/start/CWD；任一PLAN pin漂移即停。程序自身还会锁内重读。不要执行上一阶段 obsolete api_cutover.py。
3. 以普通当前用户、交互PTY运行以下命令，填入Reviewer实际SHA与fresh Main PID。所有subprocess Python使用sys.executable -B。Writer从未调用execute。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 RESEARCH_ONLY=true PRODUCTION_ALLOWED=false BUY_GATE_UPDATED=false ORDERS_SENT=false '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B '/Users/lexi/Desktop/学习/因子工厂/research/mac_lifecycle_retry_guard_20261027_r1/deployment_20261027_r1/controller.py' --execute-reviewed --review '<实际回执绝对路径>' --review-sha '<实际回执SHA256>' --expected-main-pid <fresh_PID>
```

顺序：核Case/Review后才动态导入原控制；两券商只读保存切换前错误；原Graph验证旧custom树，整包物化新组件/Main/API/collector；目标API原standard dispatcher与目标固定entry原loader首次读回，15pins/seed/路径全验证且禁止网络/文件写入。然后持原Main service.owner.lock，等自然idle，双持A_LONG/DEFAULT稳定锁，拿原announcement及shared API locks、原collector.lock并再次核旧API/Main真实Graph证据和所有CAS。

自然idle条件包含当前双lane cycle active0/queued0、原PID/start/CWD/loaded wrapper、无daemon descendants/进程组业务、claim/receipt、原PDF pending=0及无PDF producer；manager capture仍原false。busy只等，不kill/取消或unlink锁。健康长等待期间不一直占API提交锁。09:24–09:27不部署，原09:25/09:26安排不变。

按原operator在label unloaded后分别CAS三plist；Main共享服务只做本次一次bootout/bootstrap，API必要重载。Graph原collector自然空闲才卸载；collector.lock阻止新reader抢工作，inbox/history均保留。新Main因控制器持双lane暂不可dispatch，`PERSISTED_LANE_OWNER_ACTIVE`为预期抑制，不是新业务失败。

读回：Main native Python/PID/start/CWD/四身份及新A_SYNC entry；目标API原强identity；原Graph当前API/Main proof。两券商保留原错误、空rows并只追加20261019事实；000523六日与原完整envelope严格相同。最后释放collector.lock，用原activate_graph完整API/Main context做两次30秒内fresh gate；原cold reconcile和/status新config/snapshot实际读回。保留真实Graph整体状态，不把EVIDENCE_GAP或CANNOT_CONFIRM升为业务/PIT PASS。最后释放所有guards，健康自然任务才开始。

## 失败与恢复

ROOT_EXECUTION.jsonl逐条fsync意图/结果；原进程持guards。未知launchctl结果不自动重发，同配置bootstrap明确拒绝重复；不要启动另一个controller，已有journal直接拒绝新执行。

若进入 `FAILURE_GUARDS_RETAINED`，Root先读最后意图、label/PID、plist SHA确定实际状态，再在同一PTY输入 `ROLLBACK`。它在原guard下按精确afterSHA逆CAS恢复三份原文并启动旧绑定；第三方漂移拒绝覆盖。不会改原数据、失败或76admission，也不删除新release。若原activate_graph已由本操作disable Graph，才恢复其原enabled状态；外来disabled变更拒绝覆盖。

若回退启动已完成但读回尚未就绪，输入 `VERIFY_ROLLBACK`，只重新读回，禁止用重复ROLLBACK制造第二次重载。原Graph actual proof验证旧PID/CWD与原typed清单/配置，旧custom API不冒充standard dispatcher PASS。仅完整恢复后释放guards。未确认状态保留checkpoint，由Root精确对账，不弱化身份门。

## 实际完成的界线

控制器成功日志/实际HTTP与Graph读回后，Root再作必要的UI只读显示确认、同步CURRENT_STATUS/源交付状态。17:00原A自然日更消费及未来数据有效性仍按真实时点证据记录；启动成功不冒称自然业务完成。没有重采、公式重算、BUY/交易或权限扩大。

## R2 独审返修后的有效约束

旧R1独审FAIL仅为内存控制预演，不是实际停服。原件及49份精确字节封存在FAILED_R1。执行必须使用新CASE/PLAN/controller哈希及同Reviewer的R2 PASS，旧回执不能放行。

恢复前先读取所有label的真实loaded arguments、WorkingDirectory、身份env、PID/CWD及磁盘SHA，形成最小恢复计划。已验证健康旧Main/API保持运行；仅处理本操作造成的缺失/新绑定。未知或不匹配状态在任何恢复动作前停止并持guards，不重发未知结果、不给全局token豁免。

VERIFY_ROLLBACK现在同时要求旧collector真实loaded/enabled、原CLI/config与原monitor/config/snapshot读回。QueueDirectories的PID0合法；unloaded、disabled、错误配置或未确认monitor都不能记录完成或释放guards。旧custom API仍只给分层恢复证明。

保护窗保留09:24–09:27，并预留300秒启动余量：09:19起直到09:28不开始切换。最后fresh Graph GET返回后和首个服务syscall前各复核；跨窗则释放本轮API/collector/lane guards。等待从业务lane锁之外进行，不反复拿锁影响自然09:25/26任务；Main控制owner锁仅排斥另一控制器。余量是保守启动预算，不是对异常耗时的完成保证。

## R3：本次真实前置失败的唯一接续

原ROOT_EXECUTION.jsonl有且仅有START及两次before HTTP，SHA cdf0f99f3376e2381dc8cdfff9db12f31c8a55455979035a284f077414772fd0。ROOT_STAGE_FAILURE_R1证明在旧collector声明链接检查处退出；四新release不存在、三plist原before不变，未进部署锁/物化/CAS/重载。不需要ROLLBACK。已接受R2源码/Case/Plan/审PASS与本次实际journal、HTTP、错误等114文件精确保存在FAILED_STAGE_R1，不删除旧journal或覆盖HTTP。

用同Reviewer本次symlink+resume增量PASS及新Case/Plan/controller绑定；在原执行命令增加 `--resume-prestage-r1`。示例：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 RESEARCH_ONLY=true PRODUCTION_ALLOWED=false BUY_GATE_UPDATED=false ORDERS_SENT=false '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B '/Users/lexi/Desktop/学习/因子工厂/research/mac_lifecycle_retry_guard_20261027_r1/deployment_20261027_r1/controller.py' --execute-reviewed --resume-prestage-r1 --review '<本次真实R3回执>' --review-sha '<实际SHA>' --expected-main-pid <fresh_PID>
```

该固定入口必须先证明旧journal精确3事件、原R2 review及前置错误匹配、四目标仍无任何对象（包括dangling link）、三before SHA/旧loaded PID-start配置仍一致。任何不符或ROOT_EXECUTION_PRESTAGE_RESUME_R1.jsonl已存在即拒绝，留Root对账。只有通过才开独立新journal并关联旧SHA；两before HTTP从已保存原件加载，不再次请求/覆盖。default无resume路径仍原样拒绝旧journal。当前native身份是在失败后重新只读核对，不伪称旧journal记录了historical birth。

原Graph verifier继续核声明链接；新exact_inventory只接受原manifest.symlinks中路径/类型/readlink原值匹配的链接。通过fd-relative O_NOFOLLOW读普通文件，不打开/遍历link目标，原copytree(symlinks=True)不复制权威数据。额外文件/链接/非普通对象、目标漂移或link变普通文件仍拒绝。旧/新三树统一传原声明。

原R2三个P2修复与锁内切换/回退尾部均逐字节不变。Root完成首次实际stage、原dispatcher/物化entry probe后才继续原自然idle/300秒窗口/CAS链。一次固定接续不构成通用重试，若又有真实新失败则保留新journal并停止。

## R4：已全物化、尚未切换的唯一接续

R3接续已物化4个inactive release，manifest均为已审精确SHA，目标API原dispatcher退出0；其后probe因误认为lazy helper已在sys.modules而KeyError。它已经过真实_load_authority_module与facade路径断言；尚未获取部署锁、CAS或服务重载。两个历史journal与HTTP均保留，既不ROLLBACK也不删除目标或重复旧flag。R3批准源码/Case/Plan/审PASS/实际原件189文件已精确封存FAILED_MATERIALIZED_R3。

修正只用facade原lazy import同名importlib.import_module装载helper；不调用run_sync。已用固定Python-B、原network/write audit对实际物化entry执行一次exit0，caller/facade/helper、15pins、seed、fact SHA全部保留，原件CORRECTED_PROBE_ACTUAL_READONLY_R4.json。

拿本次真实R4审PASS，执行原命令时只使用 `--resume-materialized-r3`（不得再用或并用 --resume-prestage-r1）。例如：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 RESEARCH_ONLY=true PRODUCTION_ALLOWED=false BUY_GATE_UPDATED=false ORDERS_SENT=false '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B '/Users/lexi/Desktop/学习/因子工厂/research/mac_lifecycle_retry_guard_20261027_r1/deployment_20261027_r1/controller.py' --execute-reviewed --resume-materialized-r3 --review '<实际R4回执>' --review-sha '<实际SHA>' --expected-main-pid <fresh_PID>
```

固定入口先核cdf0…原3事件与9d34…本次5事件、原R3 PASS、已知probe KeyError/旧probe源码SHA、dispatcher退出0的精确目标身份、四个已物化目标完整manifest/普通文件/declared links、corrected probe原件、三旧before与PID/start。任何漂移即拒绝。前置HTTP、已验证dispatcher与未变化目标复用；不执行stage/copy/dispatcher/probe重跑或任何计算。通过后只创建ROOT_EXECUTION_MATERIALIZED_RESUME_R3.jsonl并关联两历史SHA，随后续行原未变的自然idle/保护窗/锁/CAS/读回尾部。新journal已存在即拒绝，旧默认及R1接续防重复门不变。

四份目标物化不等于已安装生效。真实切换、HTTP/UI及自然日更仍由Root实际验收；保护09:25/26安排，近窗按原300秒门在无业务锁下等待。
