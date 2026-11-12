# D2026-11-12 关闭时点研究适配与精简证据

此目录仅归档本批实际执行的一次性研究适配源码与精简结果；没有复制原引擎、权重或行情，没有新producer、服务、UI或模型门禁。原kernel与模型按`SOURCE_REFERENCES.json`的路径/SHA复用。

实际运行根：`/Users/lexi/Desktop/学习/agents调试/v4_close_selection_20261112`。`operators/`为该根`writer/`原样字节归档，`adapters/`为独立ZGE工作树`05_EXPERIMENTS/SELECTION_D20261112/`原样归档。不要在此文档目录直接启动历史全市场任务；恢复时先按SHA核已有运行根和checkpoint，只续缺项。原同日期成功结果无需重跑。

绝对环境：panel Python `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python`；model Python `/Users/lexi/Desktop/学习/runtime/venvs/v02-parity/bin/python`，sklearn1.8.0。所有子进程用当前`sys.executable`或冻结的panel/model解释器；新增fit=0。原权重及每头imputer/scaler不写。

实际顺序：`run_fresh_engine.py`先3市场canary再按资源实测14workers/28pending调用原kernel，全5809；`project_and_ledger.py canary/remaining`按截止投影；`features_and_scores.py canary/remaining`调用原32列定义和旧D3折×4角色；`structure_and_queues.py`与`opportunity_projections.py`复用事实/明确UNKNOWN；`render_review_queue.py`只复用同代同全prefix/公式/引擎/日历的原R19数据；`verify_final_numeric.py`机械核全部实际输出。输入、命令与逐项回执在运行根保存，不包含于Git。

实绩：5809处理、5536fresh公式调用、273资格UNKNOWN；930至少一子组UNKNOWN。341候选均可评分，1364角色行/4092候选头输出，另24个非候选canary诊断头输出已披露，无隐藏fit。全量wall566秒/任务CPU6232.7秒/累计RSS峰约21.48GiB。原模型NO_BREAKTHROUGH/无final保留，均值不是校准胜率或BUY。

有效研究A=0。原机器唯一A002501源名过期，当前官方为*ST利源；原数值保留，风险人工层阻断优先。主控实际看5图，其余不冒称人工认证。五机会类型的线索与正式归属UNKNOWN分开，均允许重叠；无新统一阈值或信号。

`publish_workbench_materials.py`仅准备原execution模块的材料链接，沿原owner序列化+A_LONG稳定inode+latest CAS。执行须匹配经过独立审查的plan SHA，且在本批Drive交付后由主控调用；只补材料/evidence，保留未来自然节点状态、原左侧分组和原评分。此归档不声明已执行、已部署或API/UI通过。

Git仅同步本目录必要源码和精简证据，不含原行情、完整结果CSV/Parquet、权重、cache、日志、认证、运行时发布目录或依赖。独立审查和实际本地写回/Drive交付由对应回执单独说明。
