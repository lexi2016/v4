# 学习工作区项目地图

跨项目硬合同见 `/Users/lexi/.codex/AGENTS.md`；本文件只定义 `/Users/lexi/Desktop/学习` 的地图、Mac/Git/量化边界和跨项目读写规则，不重新定义模型角色。不要假定本文件会在所有入口自动加载：跨项目任务按需读取本文件作为权威地图。

## 地图与归属

- `因子工厂/`：A/HK 因子、模型、回测和严格 OOF；先读其 `START_HERE.md`、`CURRENT_STATE.md`。
- `v4_app/`：8873 唯一源码仓库和统一用户研究面板；用户入口从 `00_研究入口/` 打开。实际 release、API、scheduler 和数据根需分别按运行证据核对。
- `v3_system/`：旧 V3 Git 仓库和历史运行参考，不是 8873 的源码或用户入口；`v3.5/`：独立旧应用仓库；`v3_shared_data/`：共享 artifact/manifest/receipt/latest 生产仓库，不负责页面或交易决策。
- `review_core/`：复盘与阶段结果消费层，追溯 producer 和 runtime binding；`数据/`：行情、pointer、面板、回测底板、预选池，存在不等于下游消费。
- `个股/`、`牛股学习/`、`Z哥方法论/`、`郑茹琼/`：资料/专项研究；`助手/`：Codex/Claude、推送和助手自动化，不是所有任务默认目录；`agents调试/`：过程证据/临时验证，不放正式业务源码。
- `runtime/`：共享虚拟环境/依赖/可重建缓存；`00_INBOX_待分拣/`：未确认归属输入。`.runtime/`、`.venv/`、`node_modules/`、`vendor/`、第三方镜像、pytest 临时目录和历史 worktree 不是配置权威，除非任务明确指向不得启动业务修改。
- 不得操作 `数据`、`Z哥方法论`、`牛股学习`、`个股` 的业务文件；助手目录规则见其本地 `AGENTS.md`。

## 统一 V4 研究面板

- `v4_app/` 是统一金融研究用户入口与权威研究数据层的源码项目（当前 8873），承接因子、模型、回测、选股、资讯雷达、研报和复盘。
- 用户从 `00_研究入口/` 的说明或 `.webloc` 进入 `http://127.0.0.1:8873/`；该目录只是导航，不新增服务、面板或 producer。入口可访问性仍需按 API/runtime 证据单独验证。
- 跨项目结果只按已确认的来源、日期/市场边界和 `manifest`/`run_id`/`SHA` 经 V4 API/产物合同接入；不另抓同源、不建第二面板或平行数据 producer，A/HK 合同不混用。
- 既有面板先完成 owner/依赖盘点和 V4 验收，再决定旧系统停用；未验收保持 `CANNOT_CONFIRM`。训练可使用独立后端，但输出仍需回到统一合同。

## 启动、跨项目与 Mac

先确认所属项目，按需读取最近的 `AGENTS.md`、`START_HERE.md`、`CURRENT_STATE.md`、`RUN_STATE`、`NEXT_ACTIONS` 或 acceptance 工件；以当前代码、pointer、manifest、producer/consumer、runtime binding 及当前日期/样本/指标/服务/页面状态为准，旧报告/聊天/历史工件仅作补充。8873 的实际 release 位于 Library Application Support 的独立发布目录；当前 A 数据指针由运行时 `state/workspace/数据`、API/scheduler 绑定和来源合同解析，不以学习根 `数据/` 旧 pointer 代替。默认只在所属项目内工作；跨项目读取或写入须说明原因、允许路径、影响和 PASS，禁止从学习根无范围扫描。

活动配置、脚本、命令和新文档使用 POSIX 路径或项目根推导；工作区根是 `/Users/lexi/Desktop/学习`，过程产物根是 `/Users/lexi/Desktop/学习/agents调试`。历史 Windows 路径可作为来源证据但不能作 Mac 活动入口/fallback；不以 junction、symlink 或伪造目录隐藏未迁移路径，发现盘符依赖按单一变量迁移并验证消费者；跨机器脚本用配置/环境变量，本机入口文档可写绝对路径。

## Git / worktree

`/Users/lexi/Desktop/学习` 本身不是 Git 仓库；不得在此 `git init`、`git add -A` 或执行无范围 Git。独立仓库包括 `v4_app`（8873 唯一源码）、`v3_system`、`v3.5` 和 `v3_shared_data`；后面三个按各自规则作为旧系统或共享数据仓库使用。因子工厂实现 worktree 为 `因子工厂/workspace`，公共 Git 目录属于 V3 主仓库。命令使用明确的 `git -C <repo-or-worktree>`，修改前后核对 branch、HEAD、路径范围；保留用户 tracked/untracked 修改，不无授权 reset/clean/覆盖 checkout/stash/删除 worktree/prune。Windows 迁移后的失效 worktree 先对现存路径尝试 `git worktree repair`，不存在的旧记录只报告。

## 量化与模型实验

算法路线开放：透明公式、线性/树模型、神经网络、学习排序、蒸馏、集成和搜索均可研究；某冻结批次的限制不得变成永久禁令。运行前冻结数据日期、样本、代码、配置、基线、评价函数、成功/拒绝条件和封存集；每批只改一个主要机制，`canary` 通过才跑全量/昂贵训练。日期边界、样本、覆盖率、IC/IR、Recall、收益、回撤等由可重跑确定性程序裁决；训练成功、loss、MPS/GPU 或工程 canary 不等于 lift，完整可比 OOF 与封存验证分开报告。项目 `AGENTS.md` 只补充地图、命令、数据/交易边界和 PASS，不覆盖全局角色或永久封禁算法族。

## 跨项目证据与并发

artifact、manifest、receipt、producer、consumer、API、页面和 runtime 是不同证据层；页面/API 成功不证明目标阶段已消费数据。`FAIL`、`CANNOT_CONFIRM`、缺失 label、截断样本和过期来源须保留，只否决对应结论，不阻止授权内修复；并发、ledger、wait、线程和 reviewer 规则服从全局合同。本目录不新增 Hook、服务、面板、自动化或不受支持的配置键。
