# 给Chat的独立编码任务：M18经理保存和普通读回
你负责原总计划模块18的交接或续修。请先确认唯一写入者：用户已把旧9cac0ff跨13→18任务交给原Chat，正在修manager same-run/latest及共享UI的只读、日期、取消。若你就是该Chat，请把本包作为边界补充继续同一候选；若是新Chat，先接收和审查该固定候选，未明确移交前禁止重做这几项或修改同一文件。收到候选后逐项标已解决、需适配、剩余阻断，只对获移交的缺口编码。请读同包START_HERE、SOURCE_MAP、ACCEPTANCE，交完整候选而非另起重复方案。Chat编写方案/代码，嘻嘻负责现有Mac应用、实测、页面验收和精确回传。

## 先交清楚映射，再编码
逐文件给SOURCE_TARGET_MAP：原owner/donor固定commit/path/blob、实际V5目标函数、现有等效实现、差异理由、前像SHA、依赖与唯一写入者。V4的A严格identity、FOUR US prepare/exact读回、D局部重放只能作为语义参考；F中并不存在manager vendor的workspace_identity.py，不能直接复制该文件并把整个workspace换掉。严格源SHA/契约pin不可绕过，若确需更新vendor，只更新最小已审差异及全部相关descriptor/fixture/hash，并说明影响。

## 这批要闭合的业务
1. 接M13/M14/M15已提交且经各自owner独立回读的引用，核target/source/publication/session/eligibility日期、cutoff、实际获取时点、run、artifact/receipt/manifest。源不足返回原拒绝与缺口；健康lane仍可见。M18不采集、不重跑模型/三策略、不把观察结果升级为正式候选。
2. 原经理显式refresh保存，独立读取本次run的产品及同run终态，验证owner、输入identity、SHA、安全字段和日期。latest是另一个观察指针；另一请求推进latest不能让本次确定已保存产品误报失败，也不能用另一run的终态借成功。优先复用原run/存储，不无理由新建operation_id、新store或宽松validator。
3. 已有current_recovery须保留：过去目标日的现在研究进入独立current_recovery，用真实now/generated_at，historical_eligible=false。auto可读该目标已提交恢复产品；显式historical仍执行原PIT门禁。不存在该目标恢复时不能绕过历史拒绝，不重写旧历史文件。
4. 普通GET读已发布generation，无采集/生成副作用。经理readback、module API、gateway、浏览器显示同一已消费run/SHA和终态，另列最新失败尝试。观察字段不可装成保存计划的筛选来源。日期切换、刷新、返回、迟到响应、取消均保留身份。
5. 第一步就核实际发布路由：F的module_api只读405，gateway可配置转发GET/POST，前端却有refresh。不要凭假想V4 router写一个无法接到V5的修补。共享执行路由、UI、gateway、调度及配置只提交INTEGRATION_REQUEST，列精确文件/函数/合同/依赖与验收；统一集成接受后才由唯一集成者修改。不得自启另一预览发布者。
6. 保留已有源检查，且只在真实差异用例复现后改语义。strictidentity只能对原reader已验证引用，且确属无关的registry-wide指纹做局部处理；不能递归删SHA、忽略真实payload/receipt变化。FOUR上游准备由相应owner/统一调度负责，M18只消费最终exact引用。
7. 前端已有e0a6bc36候选优先复核，不重写同一修复。F的requestManagerWorkspace有CURRENT_RECOVERY兼容检查差异，POST签名不含可选bindings，不能机械套V4另外版本补丁。先读真实DTO/validator/调用者，测试证明需要的最小合同改动后交统一集成。

## 测试与反馈
先用原测试证明必要失败，保留原负测及历史兼容；测试同run/latest交错、孤立product/RUNNING、terminal缺失/篡改、源SHA变化、错误日期、未来时钟、超时后副作用未知、健康lane+其他lane缺源、current_recovery与显式历史互斥、只读GET无文件变化。不要通过重采、扩大coverage、改阈值、补0制造成功。

Mac真实392原件留在Mac。没有原件的真实API/浏览器/自然运行标NOT_RUN，不把fixture包装成现场证据。旧测试各套分列，不相加。必要import/typecheck/build/完整依赖失败保留原日志。

## 必交候选
- START_HERE：唯一候选commit、明确基线、范围、真实测试结果及缺口。
- SOURCE_TARGET_MAP、DEPENDENCIES及COMPOSITION_MANIFEST：每个修改/新增文件的原commit/path/blob、before/after SHA256、descriptor/依赖变化；新增文件明确BEFORE_ABSENT。
- before/、after/完整修改文件；runtime.patch、reverse.patch；必要完整测试源码和原始执行日志。只有diff或代码片段不足交接。
- MAC_APPLY_AND_ACCEPTANCE：前像逐文件核对、隔离候选、原193/其他受保护资产如相关的非delta校验、固定候选实测、实际API/generation/静态bundle/页面、统一窗口切换及单模块回滚。Mac绝对路径、解释器和端口未核时用待绑定变量并列取值方式，不能猜覆盖命令。
- INTEGRATION_REQUEST：所有共享代码、HTTP refresh、UI、gateway、调度需求单列，禁止跨模块直接覆盖。
- 如有代码级阻断只列首个失败函数/合同/缺件及最小补件，不再索要整库或重做原三策略。可独立实现与测试继续。

若有对应已授权开发分支写权限，提交独立候选并远端读回；不改main/现役分支、不合并、不部署Mac。否则交完整离线文件包。嘻嘻会把固定候选在Mac的实际问题交回本Chat修同一实现。

