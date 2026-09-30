# R3-A：一次 F0 最小交接清单（不阻断 R3-B）

F0 当前 **CANNOT_CONFIRM / 未确认已上传**。a6ade9… 工具修复、852708f6… 的 canonical/release 不同和 15:55 来源范围不足直接复用，不再要求重复比较相同 SHA，不索取完整项目ZIP或原始plist。`producer_edit_allowed=false` 不是反复审计可刷到 PASS 的目标。

仅交接下面实际运行相关源码字节及清单；可用统一源码交接的同一个不可变目录引用，不另造第二批重复证据。

| 必要源码/资料 | 用途 |
|---|---|
| canonical `contracts/runtime_workloads.json`、`infrastructure/scheduling/executor_registry.py`、`_executor_registry_parts/panel_execution.py`、该包 `__init__.py` / `_namespace.py`；其在原17:20调用中确有使用的本地helper | 冻结唯一 workload/handler、参数/环境白名单和拆分调用边界；不是迁移其他任务 |
| canonical `ops/macos_research_panel_daily.py`、`_macos_research_panel_daily_parts/hk_market_capture.py`、该包 `__init__.py` / `_namespace.py`，以及当前 HK lane 实际调用的 capture/gate/manifest 写入helper | Chat 实现 F1 与现有17:20行为最小适配；保留两个已存在 plate 调用，不再抓取 |
| canonical `ops/ensure_hk_security_master.py` 与它实际调用的现有 publisher/存储/哈希/不可变提交 helper | 原同次capture进入现有发布流的接点与失败传播；不让行情有效性过滤缩小membership |
| configured release 对应17:20原件：`executor_registry.py` / `executor_registry_review.py`、`macos_research_panel_daily.py` / `_collectors.py` / `_gate.py`、`ensure_hk_security_master.py`，及上述相关必要本地依赖 | 仅只读行为参考和差分oracle；不直接修改release，文件如已在统一交接里则引用原路径/SHA |
| 同一消费目标中的 `domains/manager_research_evidence.py`、它加载的 `stage_center/hk_universe_preflight.py` 与现有 schema/常量/序列化依赖（与R2已给版本相同就引用既有blob） | 核真实authority合同、日期、source/receipt完整性和取得/读回时钟语义，避免凭文件名猜兼容 |
| 原构建器及相关本地helper/命令入口；canonical每个相关dirty/untracked文件SHA、模式、HEAD/status、运行入口脱敏定位、构建来源记录（有则引用） | Chat确定最小前向source布局，Work用原构建器生成隔离候选及本次真实source-output回执 |

上述 helper 仅指实际17:20调用的依赖，不要求整目录/整项目递归打包。若入口未直指某一 helper，请列实际 import/call 路径即可，不要求 Work 先研发适配器。源码字节缺失才补交；已有 SHA/摘要不是源码字节的替代。

历史来源证明目前只可说“已检查材料未覆盖17:20”，不能说已证明所有历史记录不存在。无历史映射时采用新的前向构建证据，不回改旧manifest、不补造旧时钟。

分工：F0 一次真实源码冻结交接 → **Chat 完成 F1 代码和精确patch** → **Work 用原构建器做隔离候选、无网络原路由canary、真实source-output回执和独立验收** → 获授权后才由现有owner做真实provenance/authority与API/UI验收。Work不承担宽泛代码研发。

17:20后取得的数据不得倒用于同日更早时点；已有 target_date 不证明可用，主表发布时刻不等于plate取得时刻。缺供给时序继续失败，不改变Stage/BUY/F5/Vibe。
