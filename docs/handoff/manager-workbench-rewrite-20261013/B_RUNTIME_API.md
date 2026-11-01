# B｜计划、任务执行、存储与API重写

## GOAL与唯一交付

提供不依赖旧经理业务的运行中枢：A研究引擎→独立模型执行→不可变计划保存→HTTP读回→明确任务状态，支持09:25/日内/16:30与旧历史只读。

WRITER：本块唯一Luna Max；REVIEWER：不同identity的独立Luna Max。ALLOWED_PATHS：`v4/manager_workbench/__init__.py`、`contracts.py`、`config.py`、`service.py`、`jobs.py`、`store.py`、`api.py`、`scheduler.py`、`legacy.py`、`cli.py`、`executors/**`（以上均在v4/manager_workbench内）；`tests/manager_workbench/runtime/**`、`tests/manager_workbench/contract_samples/**`；`ops/run_manager_workbench.py`及脱敏配置示例`docs/examples/manager_workbench.example.json`。FORBIDDEN_PATHS：A inputs/engines、C前端、旧经理代码、应用中央装配/现役scheduler/binding/plist、全局凭证/hooks/权限、原始业务数据、其他业务与BUY/Vibe8910。

PASS_SIGNAL：公共合同、异步执行、保存后同run/SHA读回、错误隔离、幂等/恢复、历史适配及HTTP定向测试独立通过；本机真实模型canary未执行时不得称自动语义链已验证。STOP_RULE：模型认证/访问不可用报具体缺口，不建API key、不绕过权限；合同变更先交主控协调，继续其他独立事项。

## 第一批先交合同

严格实现COMMON_CONTRACT.md中的公共类型、JSON schema、合成规范样例和协议测试，固定commit供A/C引用。这不是另一次设计批准，不可自行变更用户已锁定行为。样例须含正常、空集、部分完成、未知计数、失败和旧历史状态。

## 具体需求

1. 提供create_service(config, adapters, engines, executor)与create_router(service)装配工厂；服务通过注入调用A，不复制研究规则。运行入口自带参数校验、脱敏配置加载和任务读回，可被现有V4进程/调度器接入，不创建新长期服务或端口。
2. CodexExecutor使用本机既有账户的非交互Codex CLI，Luna Max、结构化输出、read-only执行；Reader和Reviewer不同进程/执行identity。A提供业务prompt/schema，B保存真实调用身份、时间、事件/结果SHA和故障。严格实施共同合同的材料/指令隔离、最小脱敏目录及无关工具/MCP/非模型服务网络工具关闭；无法证明隔离时保留真实canary缺口，不以read-only冒充隔离。模型不直接写业务状态；不新建凭证或修改全局配置，不使用权限/信任绕过参数。
3. 单篇真实Reader→Reviewer→保存→API读回canary由Mac执行；提供可直接运行的canary入口与模拟执行器测试。认证、模型访问或调度身份不可用时明确FAILED/缺口，禁止假输出、仅DECLARED身份冒充实际执行或自动换模型。
4. 后台任务与浏览器请求生命周期分离；POST返回202，GET只读。复用同输入成功结果，健康活动任务不重复启动；失败仅重试可恢复步骤。重启查实际进程/产物状态后恢复或标INTERRUPTED；浏览器等待超时不取消健康模型任务。
5. 新结果使用配置提供的STATE_ROOT下manager_workbench命名空间，旧manager_auto_research根只读。复用通用锁/原子写入；快照与attempt分开保存，快照不可变，成功读回后才更新同日期/phase指针。输入快照注明派生及原owner/SHA，不能成为第二权威源。
6. 09:25冻结已完成且截止前可用结果，缺lane保存PARTIAL；模型仍可继续，晚到结果不改盘前版。每个新完成Stage run且输入变化生成日内版；16:30下一有效HK日草案使用当日真实cutoff。现有调度tick通过新CLI检查due/阶段回执与幂等游标，不要求改Stage producer增加回调。迟到执行单列LATE_CATCHUP，不称自然验收。
7. 接入共同HTTP接口，包括reviews；日期和版本隔离、完整计数与分页、合法未运行200、非法422、未知404、冲突409、通道503。缺单lane保留其他有效结果，接口不泄露本地路径、凭证或堆栈。
8. 旧历史独立适配保存原schema/run/SHA，只读转换用于展示；没有原始来源则CANNOT_CONFIRM。禁止调用旧get_workspace或以现在输入重验后覆盖原结论。历史格式不认识则返回该条缺口，不抹掉其他历史。
9. 提供经理源文件/依赖清单、CLI执行所需最小环境说明、激活/回退建议及旧入口兼容字段映射；不修改中央app.py或现役scheduler。这些落地修改由Mac统一适配，不让三个chat同时碰。

## 必须覆盖的测试

公开schema样例；POST异步/GET无副作用；重复提交/跨进程锁；断点与进程重启；失败不覆盖成功；same-run/SHA不一致拒绝；cutoff前后、09:25未完成、迟到、周末/半日、下一交易日；新Stage重复/变化；Reader/Reviewer同identity或异SHA拒绝；CLI错误输出/未知认证不升级；历史不可改与未知旧schema；所有HTTP状态、分页完整分母、安全四字段。模拟与真实执行结果分列。

## 交接与Mac分工

按README交固定commit/PR或patch、合同样例、A依赖commit、测试与独立Reviewer receipt、脱敏配置和运行命令。Mac主控组织中央应用注入、经理scheduler绑定、CLI账户身份canary、新旧唯一owner切换、发布/API/UI与自然时段验收；B不私自改Mac服务或认证环境。问题反馈只返修本块。
