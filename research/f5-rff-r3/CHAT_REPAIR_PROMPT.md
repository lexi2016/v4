请直接处理 GitHub 私有仓库 lexi2016/v4 中的 F5/RFF 评价衔接问题。

分支：f5-rff-r3-collaboration
源码目录：research/f5-rff-r3/
源码基线提交：c24892e57cf4a568bc96095748974abe28b3112f
问题单：https://github.com/lexi2016/v4/issues/2
请先读该目录 README.md、SOURCE_MAP.json 和问题单，基于这份代码修改，不再索要或使用旧 ZIP。

本次真实运行已完成 1 次 fit、1 次 full-S predict，并在预测封存后解码过 1 次 truth，随后报 CandidateError: CANDIDATE_TRUTH_JOIN_DOMAIN_MISMATCH。METRICS 和 L04 完成回执未生成，目前不能评价模型效果。

已定位的代码缺陷：
RFF 的 src/rff_worker.py:390–391 把全量 grid 和 Top3 子集依次交给复用的 _join_truth。
历史 XENDCG candidate_01/src/candidate_worker.py:187–188 比较“当前左表关联后的 y 缺失数”与“全量 truth 的 y 缺失数”。这个等式不适用于 Top3 子集，也不能可靠区分合法空标签与未匹配 key。真实日志没有完整 traceback；第二次 Top3 调用是沿绑定源码及同源 key 构造得出的高可信定位，不要声称取得了不存在的真实栈帧。

请交付最小代码修复，而不是另一份泛化方案：
1. 把修复限制在 RFF 路线自身：实现按当前左表 key 范围验证的 join，或从已验证的全量 join 结果中按 key 取 Top3。明确检查未匹配 key、重复/歧义键，保留合法未知标签的既有语义以及行数、顺序和分数。
2. 不改历史 XENDCG helper/owner、输入池、模型、控制基准、标签、指标、阈值或已签合同；不删除保护条件来制造 PASS，不新建 producer/owner。必要的新源码身份绑定须给出明确 delta，不覆盖历史签发件。
3. 使用纯合成数据写针对性回归：全量 A/B/C/D 的标签为 1/0/1/null，而 Top3 为 A/B/C；此时 0 与 1 的空值数量差异应合法。另覆盖子集含合法空标签、真缺 key、重复 truth key、全量与Top3两条调用，以及评价衔接路径。
4. 不读取真实行情/标签，不 fit、不 predict、不解码 truth、不运行真实评价、不重训。已有模型和封存分数保持原字节；真实恢复不在本次任务授权内。
5. 已修正的 resource_trace_path 在 candidate_output 内，保持这个修正及原 L04 路径保护。用户要求未来 Mac 执行不默认沿用 4线程/3GiB/1800秒限制，但这次错误没有资源终止证据，不要把资源配置改造混入 join 修复。
6. 直接交付相对上述基线的可应用 diff/补丁、修改文件清单和 SHA、纯合成测试结果、剩余未知。若你具备仓库写权限，在此协作分支的修复分支提交 PR；没有写权限就给完整可应用补丁，别只给建议。

后续 F5 训练只使用新会话：https://chatgpt.com/s/cx_6abb07e53d4881918f6b8f8c25b47df8 。不要向旧 F5 会话派发训练。
保持 RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。
