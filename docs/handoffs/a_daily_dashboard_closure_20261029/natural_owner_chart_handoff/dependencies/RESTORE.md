# 既有 Gate 自然入口精确依赖补件

这是 B 类机械备份：从真实工作树提取既有 dirty 调用，非本轮新实现，也不代表独立全 gate 认证。查过本 handoff 树中的 *.diff/*.patch，没有可复用 gate 文件补丁。没有改 gate、其他源码、服务、pins 或 CURRENT，没有运行 tests/业务 canary。

恢复基线和字节身份见 REPLAY_RECEIPT.json。基线 commit 为 e6df789828ef064a9114e27962f99d2575711e7f，gate blob af1e97ccad03f7d0cfe51301eebe513304947242。gate_materialize_daily_product.patch 只有一个上下文 hunk：在原 run_a 的既有 formula 完成后调用 materialize_daily_product(data_root=authority_paths["--a-data-root"], target=int(target), formula_result=formula)，异常为 CANNOT_CONFIRM，将结果加入原 outcome。CALLSITE.txt 是当前真实调用位点的8行原字节。没有夹带其他 dirty。

在隔离临时目录放规定 base blob，先 git apply --check 再 git apply 本补丁；重放全文件与真实当前 gate 逐字节一致，临时完整文件已删除。实际恢复只能对先核 SHA 的这个规定基线使用；若目标还有他人修改，先核具体 hunk，不能覆盖或整文件 checkout。此说明不授权生产应用。

运行依赖为已独审 C4 commit e6df7898 的 ops/research_panel_daily_product.py / render_original_formula_projection.py / SourceReader / completion matching，以及 RESTORE_FILES.md 指定既有源码和 pinned 来源。此补件仅闭合源码恢复链，不证明现役入口已安装或自然执行。15:40 runtime、自然 D30、历史同事件收益仍 NOT_RUN。四旗保持 true/false/false/false。
