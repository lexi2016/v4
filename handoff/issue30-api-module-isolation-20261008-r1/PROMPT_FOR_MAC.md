# 给本机接手者：完成 Issue #30 集成与恢复验收

请从本包 `README.zh-CN.md`、`SOURCE_MANIFEST.json`、`TEST_RESULTS.json` 和独立最终审查开始。任务是基于**接手时实际 active 的完整版本**集成本批源码，在保留经理修复的前提下验证预选池恢复，并把批准后的部署/API/UI/自然时段分别闭环。

当前交接不授予自动部署权限。这个限制来自 Issue #30 原 README 第 6 节末尾和项目 `AGENTS.md` 的同步边界。先把源码集成、候选、差异、测试与实际切换计划做成可审查结果；仅在需要执行真实切换时，依据已有会话授权判断是否还需最终批准。不要因只读核验、隔离测试或候选构建反复询问是否继续。

## 1. 核真实身份与允许修改范围

读取本机项目和上位 AGENTS。记录 canonical、当前 API、Stage、scheduler 各自源码根、服务入口与版本，保留其他会话工作树。不要把 Git HEAD 代替工作区字节，不要盲目 `git add -A`、reset/clean 或整树同步不同 owner。

已知 API 指针是 `/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist`。重新只读取得当前 release id/root、manifest SHA、完整 app 库存、入口 app SHA、source roots 和运行身份；不要照抄历史 PID 34989。Issue #30 报告的晚间 app SHA 是 `90a2bf6390c6c0e219aa3d9bb22bc3b3630ecb2d447df494ae69425933424ed7`，manifest 是 `2cc1447a740195c4f50299330d845635ddf762c45eb59586436a527e4f8b75a8`，1016 项 inventory 是 `c371c633437e366d28549a94be35741e8d137d2a0836155695c9d125bb427f05`。这些是待复核的历史参考。

必须取得当前 `domains/preselection.py`、pool store/readers/sources、锁、API config 和运行依赖的身份。本包只能证明 app 单文件前像和历史测试闭包；经理交付中引用的完整 inventory 正文未取得。若现役已变化，不强行套旧 before SHA，保留并重新制作最小差异和独立审查。新 router/service 在 active 中必须确认不存在；若已存在，同样停止旧 addition 合同并重新集成。

只修改 `SOURCE_MANIFEST.json` 的八个产品路径所对应 owner；`test_support/` 不写入正式源码。实际 R2 脚本保留任务目录层级，其 guard 位于 canonical `ops/api_release_integration.py`，不要搬动专用脚本造成 `TASK_ROOT` 错误。源码库与 API 发布目录不同，不能把本包 app 后像无条件覆盖当前 canonical app。

## 2. 先复跑便携测试，再复验当前完整闭包

使用已存在、依赖可核对的 Python 环境，在全新、无路径别名的目录执行：

```bash
python -B /absolute/package/run_tests.py \
  --python /absolute/venv/bin/python \
  --output-root /absolute/new-issue30-replay
```

以 `TEST_INPUTS.json` 的最终预期数量和 `SUMMARY.json` 为准；不得删除失败测试、换成 stub 或借其他目录的旧模块使其变绿。记录 Mac 用户、Python/依赖身份，保留失败及警告。Linux root 运行过的权限测试不能替代 Mac 服务用户权限验收。

随后在**当前完整依赖闭包**的隔离 API 环境复验 app 启动、预选池与经理联合行为。不得把便携的 AST 注册测试称为完整 `create_app` 验收。经理公告、日期隔离、workspace、已有 routes 与静态资源都要保留。

## 3. 生成当前 active 的真实 delta 与候选

本包 `change_sets/preselection.json` 固定三个业务文件的前后 SHA/mode；before mode 来自 Git 文件合同，不冒充现役 mode 观察。实际不相符时重做记录与审查，不改 receipt 迁就结果。

下面入口只读取 active 与后像并创建一个新 delta 文件，不启动服务。先创建独立 evidence 目录，将绝对路径替换为本机实际路径：

```bash
python -B /absolute/package/after/ops/create_api_module_delta.py \
  --active-api-plist /Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist \
  --after-root /absolute/package/after \
  --change-set /absolute/package/change_sets/preselection.json \
  --output /absolute/new-evidence/preselection-delta.json
```

不得在 Chat 环境生成一个假的 1016 项 base/receipt 冒充本机观察。该入口的输出也是完整性合同，不是部署批准。

构建工具的四个发布文件需要与本机核验的相邻 helper 配合使用；本包 `after/ops` 不附带用于生产的历史 helper 副本。先在独立、可追溯的源码工作区集成四个工具和三个业务后像，核对必要依赖与包内测试身份的差异。正式 builder 使用该工作区作为 `--source-root`，但只从它读取 delta 指定文件；非 delta 全部取当前 active。

通过 `build_release_candidate.py --help` 核对参数后，传入真实 active API plist、真实 scheduler plist、刚生成的 delta、独立新 candidate 目录和明确 release id。**显式传入 V4 的 formal release root**：`/Users/lexi/Library/Application Support/com.lexi.v4.local/releases`，不要误用工具历史 V3.5 默认目录。候选必须在正式 releases 和源码目录之外；不覆盖现有候选。已经被 Git 跟踪的新增模块不用 untracked 参数；未跟踪的 after 文件必须逐项明确纳入。未声明文件不能混入。

核候选完整文件库存、目录保留证明、非 delta digest、三个文件的 before/after、manager 保留证明、环境/安全 flags、外部 venv/symlink 目标身份以及 isolated manager state。候选的 scheduler plist 只是未激活的审查副本，不构成 scheduler rebind。

## 4. 实际只读来源 canary 与联合验收

固定 target date、来源根及实际 source trio SHA 后，隔离读取 `/api/v3/preselection-pools?date=20261008&limit=200`。验业务字段，不只验 HTTP 200。若源 SHA 与 Issue #30 相同，完整去重汇总应 A=178/HK=100；若已变化，重新计算并解释差异，不强制填这些数字。

核对源 premarket 30 与 research 149 的去重关系、完整 A 汇总、缺失/空/partial 子池的隔离原因。翻页不得改变全量计数和输入 fingerprint；完整 Stage 输入不得按 200 行展示页截断。核空本地池保留已配置来源中的 A；非空本地 A 补严格 HK 时不丢 A；错误日期、pending、未知 SHA 错误和 A/HK 身份矛盾均不能伪装成功。任何读取前后业务文件 SHA 不应改变。

同一候选同时验证经理公告、日期隔离和 workspace 更新，以及 Issue #30 保留的现有业务验收。只证明 app 字节未动不能替代这些行为检查。

## 5. 发布入口接管与最终批准

盘点所有可修改同一 active API plist 的入口，逐个确认使用共享锁和 v2 集成 guard，或明确退役而不会再被调用。不能只安装 canonical guard，就宣称旧临时 publisher 也受到保护。Stage、scheduler 不随 API 模块变更自动获得同版本身份。

实际脚本是 R2 专用前像补丁，47 个原顶层赋值保持。新的恢复 release 必须有对应的已冻结 plan、staged plist、完整库存、业务证据和准确 pins；不要盲改一个 SHA 让旧脚本接受新包。计划的允许路径必须覆盖 active API plist 和共享锁；evidence 路径必须按原 owner 合同授权。需要审查 execute 与 rollback 两个公共入口，以及 rollback 的失败续恢复分支；未知 active/runtime 仍应拒绝。

完成上述源码、候选、全闭包测试、来源 canary、联合回归与独立审查后，形成明确的切换/回滚计划，列候选与备份精确 SHA、影响的唯一 API 服务、观察点和恢复路径。依当前有效授权决定是否执行；若尚无真实切换授权，在此具体结果上请求最终批准，说明限制来自 Issue #30，而不是一开始就停在询问是否读取文件。

## 6. 上线后分层报告

获授权的发布者执行受保护切换后，重新读取进程与 manifest/inventory 身份；真实 API 检查同 target date 与 source SHA；重载 UI 验证预选池与经理页面。自然时段另留调度器、run manifest、代码身份、来源与结果链路，手工重跑不能标成 NATURAL。历史 settled slot 不因本包自动删除、重置或改日期。

逐项报告 IMPLEMENTED、TESTED、REVIEWED、MAC_INTEGRATED、DEPLOYED、API_VERIFIED、UI_VERIFIED、NATURAL_VERIFIED，失败与未做分别保留。同步新独立 GitHub 工作分支并读回核验，不 merge/force push，不上传原始行情、凭证、账户、完整 plist、venv 或 dist。

## 7. 不并入这次发布修复的事项

HK 合格 10/7 价格源、9/30 Connect 资格分日期绑定、上游三件套与本地三件套、A 09:25 昨收持久化、研究字段、嵌套历史 P2 和自然证据按 `OPEN_ITEMS.md` 各自验收。没有源就保持缺口，不重标日期、不改 validator、不用缺值 0 掩盖。Vibe8910 保持原样。

始终保持 `RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
