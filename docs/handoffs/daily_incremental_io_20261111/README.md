# 原日更 IO 首补丁交接（尚未独审、集成或部署）

问题：原公式 owner 在新双表合并前，把已有 CURRENT 另写成 selector/backtest 两套旧数据桶；纯 IO 源码变化又会改变 publication adapter SHA，使原 D11 已完成的部分逐股结果失配。本补丁只去掉重复旧桶，并增加严格、显式的同 D11 部分原结果引用。

分支 `codex/daily-incremental-io-20261111`；Git 基线 `9fdb014ebb24f32359ba31f62f2da1fdba656cbd`。该 Git 版本缺此前已验收的部分现役修改，所以不能把整个 worktree/Git diff 当作可覆盖现役的发布包。`BASELINE.json` 与 `SOURCE_DIFF_BINDING.json` 绑定实际运行源码；两个 `.patch` 才是本批相对现役的精确增量，须在前 SHA 匹配时使用。两个 `.before.py` 是针对性 oracle 的小型源码快照，不是运行包。

## 真实改动

- `ops/research_panel_qfq.py`：保留原 guard 包装的 `spool_current` 名称与参数，改为读原 Parquet 的 symbol 列建立逻辑桶/rowgroup 索引；混合 rowgroup 用 Arrow 精确过滤，保持原顺序、schema、NULL/NaN。返回只读 view，合并前后检查原文件 stat，没有创建旧桶目录或额外全表文件。
- 原 `checkpoint_resume` typed schema 保持 `qfq_original_checkpoint_recovery_v1`，新增显式 `recovery_scope=D11_PARTIAL_IO_ONLY_V1`。只接受 D20261111、已封签旧 adapter `7b1f6b…`、完全相同的 snapshot/driver/formula/kernel/其它非 IO 定义/factor/turnover/双表基线，以及每份原 fingerprint、receipt、artifact SHA。旧普通 complete/37/38 模式不放宽。新 adapter SHA 仍是真实新源码 SHA。
- 原 partial 文件只读引用，不再拷贝并改写成新 checkpoint。合并使用实际返回路径，文件及其回执若在校验后变化则拒绝；最后发布前重验控制引用。缺少的股票继续原函数计算。显式 recovery ref 被原 manifest/typed source closure 引用，现有 retention 能识别和 pin 原 run/chunks；没有新增 storage schema 或改 storage 源码。
- `ops/macos_research_panel_daily_authority.py`：仅新增可选 `checkpoint_resume=None` 参数；非 None 时转发给原 `run_with_retention`。默认调用、CLI、所有环境、来源、guard 和发布路径不变。

不包含跨日 delta-only checkpoint、新数学缓存 key、递推状态、原图/前端、reader/格式迁移、清理或任何 live 操作。原公式 kernel、字段/评分、A/HK、BUY、UNKNOWN、源验证、最终发布门和双表 CAS 都保留。最终完整双表一次原子写仍存在；不宣称 O(当天数据) 算力或端到端日更完成。

## 已执行验收

`tests/test_qfq_daily_io_reuse.py` 共 29 项分别通过，精确命令与此前失败保留在 `TEST_RESULTS.json`。

- 原/补丁实际 owner 合并片段的隔离小表：普通新日、无新 bar、8 只除息变化、新股及保留 HK 数据；两角色的数值、顺序、schema、footer 和 counts 完全一致。
- 原 pinned full-prefix 引擎作为 oracle：11 个各 90 bar 的小 fixture（普通、停牌、8 种 D11 除息、新股），所有输出列逐值一致；数学及 release-gate 定义的 AST 等价也通过。没有重跑真实全市场历史。
- D11 真实首/中/末三份 `000001.SZ`、`002164.SZ`、`002906.SZ` 的改后恢复兼容通过，返回的就是原文件路径，无新数值文件；仅样本 3/1364，不称全部 1364 个逐项认证。
- 缺项正常计算且同身份再试不重算；process worker 原路径返回；14 类身份/日期/路径/内容漂移拒绝；校验后原文件/回执变更拒绝；字典、NULL、NaN；authority 默认和显式参数转发均通过。
- `WRITE_COUNTS.json` 是机器级小 fixture 写入统计：原写 108 行、24 个 writer；补丁写 66 行、4 个 writer，减少的 42 行恰为两角色旧表副本，候选旧桶 writer 为 0。未外推生产字节节省、物理占用或准入结果。
- `git diff --check` 与两份修改源码 AST 解析通过。

首次测试还遇到 pytest 默认共享临时目录对以前测试垃圾目录清理时 EPERM，掩盖了正常报告；之后所有命令改用本任务独立、唯一 `--basetemp` 和 `-p no:cacheprovider`，未修改旧目录权限或手工删除内容。初始代码缺局部 `pyarrow.compute` 导入，以及两个测试 harness 的 scope/package 绑定错误均已定点修正；24+1+3+1 项针对检查分别通过，没有为无关问题重跑全库。

## 后续主控/Reviewer

独立 Reviewer 应审两个相对现役 patch、before/after SHA、真实测试与原目标行为。测试以现役 app 为 cwd 和依赖来源，使用项目绝对 Python；测试文件则取本 worktree 的绝对路径，`--import-mode=importlib`。需设置 `V4_TEST_ORIGINAL_APP` 为绑定的原 app；真实三份只读 canary 另显式设 `V4_TEST_D11_CHECKPOINTS=1`。使用新的本任务 basetemp，不套用共享临时目录清理。

正式继续时必须由主控显式构造封签 recovery ref，包含真正要复用的原 chunks；三份 canary descriptor 只证明样本，不是正式全量恢复清单。不得扫描旧 run 猜来源、伪造新 adapter、把 partial 当成 READY、忽略错源或关闭原 guard。新源码身份仍须原发布门接受；本 Writer 未更新接受清单、未部署或运行 producer。

另一个现有边界：绑定现役 `run_daily_rebuild` 仍要求 workers 1–4；传 14 之前只是先被 storage admission 拒绝，并不证明原函数支持 14。本批未改该参数或上限。

状态：IMPLEMENTED + TARGETED_CHECKS_PASSED；REVIEWED/INTEGRATED/DEPLOYED/API/UI/NATURAL 均 NOT_RUN；Git commit/push NOT_RUN（按主控本阶段指令）。
