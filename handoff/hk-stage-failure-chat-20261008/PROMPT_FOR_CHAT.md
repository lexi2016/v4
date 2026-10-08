# 交给Chat的任务

请以本问题包为输入，完成 `20261008 / STAGE_0930_0935 / HK_CONNECT` 的可复核候选修复和针对性测试。目标是修复真实来源的拆分日期provenance闭环，同时保留固定D1 Top100、日期/市场边界、來源身份、封闭失败行为和交易安全状态。先阅读本目录 `README.zh-CN.md` 与 `evidence/*.json`，再核对源码副本SHA。

## 冻结事实

- API owner：LaunchAgent `com.lexi.v35.api-only`，当前API目录 `manager-daily-chain-20261008-r3-api/app`，8873的GET回读HTTP 200、整体 `PARTIAL_WITH_ROWS`。HK摘要只展示 `SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID`，这是API层投影。
- Stage owner：LaunchAgent `com.lexi.stage-center.scheduler`，当前not running、launchd最近退出码3；入口和工作目录指向 `V4_HK_STAGE_RECOVERY_20261003/issue23_runner_helper_r3/stage_r1_binding_candidate_r3/app`，配置release `20261003-hk-binding-wrapper-r3`。Stage与API源码/生命周期不同，不得默认API owner就是Stage owner。
- 输入owner：实际配置的primary `com.lexi.v4.local/state/data` 没有 `preselection_pools/20261008` 日期目录；配置的secondary `com.lexi.v35.local/state/data` 有该日期目录。当前whole-date resolver因此选中v3.5来源根里的 `hkconnect_d1_top100` 文件。包里提供了 artifact/manifest/receipt 的摘要SHA，没有原始池行。
- 实际Stage日历解析：价格信号日 `20261007`；Connect资格来源日 `20260930`。现有源池100行的 `signal_date` 都是 `20260930`，但artifact没有 `historical_provenance`。Stage直接回执报 `HK D1 split-date eligibility provenance missing`，HK `write_performed=false`。
- 仅新增provenance对象不会闭环：当前验证随后要求每行 `signal_date` 等于 `20261007`，现有行仍为 `20260930`；此外校验器将provenance里的D1 manifest/receipt SHA与payload的 `source_manifest_sha256` / `source_receipt_sha256` 比较，而观测到的payload没有这两个字段，尽管物理manifest/receipt SHA可由已读trio核验。候选需基于resolver实际验证的trio身份适配这一比较，并分别核实已有权威价格日期输入、资格日期输入及真实capture-time；如缺少任何一项，保持 `CANNOT_CONFIRM`，不改标日期、不造字段、不声称恢复。
- 用户提供的上次交付参考是commit `4c9218789fe320dd42c1946e5dfb5161d8f8ed2a` / branch `codex/issue28-historical-p2-mac-20261008`。两项历史P2据报仅有本机集成测试38/38且未部署，不能作为本次根因已修或当前owner已更新的证据。

## 交付要求

1. 用精确日期、Stage owner、输入artifact身份固定复现；解释Stage精确错误如何映射成API的粗粒度状态。
2. 输出候选diff和最小必要文件清单，覆盖当前canonical源码与上述实际Stage owner的版本差异。不得只改canonical副本后声称实际Stage已修复。
3. 给缺失provenance和行级价格信号日期不匹配分别加针对性回归，复用已存在测试并补充当前缺口。运行测试并附实际命令、解释器、结果；系统Python 3.9不兼容 `StrEnum`，Stage配置中的V4虚拟环境是本机执行证据之一。
4. 在候选中只消费已存在且可核验的日期、artifact、manifest、receipt、run_id与capture-time证据。绝不推导/伪造资格artifact哈希、run_id、捕获时间，绝不把 `source_sha256` 当作其他来源的hash。
5. 不改变D1 Top100固定池、不使用latest/全市场回退、不混A/HK、不建第二producer、不放松日期/来源/行级约束、不改BUY安全；保持所有交易安全flags为false。
6. 说明候选代码已实现、测试、与实际Stage owner适配、API/UI集成、部署、自然运行各自证据。当前服务/计划任务/外部数据不得被修改或部署，除非用户另行明确授权。缺证据写 `CANNOT_CONFIRM`。

`publish_minimal_git_sync/`只是未修改的最小基线，不是补丁或发布包。此任务的目标是完成可审查候选和Mac验收方案，部署/切换服务不是当前授权范围。
