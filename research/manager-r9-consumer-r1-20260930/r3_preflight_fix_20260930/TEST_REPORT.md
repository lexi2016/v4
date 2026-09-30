# 作者测试结果

环境：Linux，Python 3.13.5，pytest 9.0.2。没有 Mac、Luna Writer/Reviewer、Futu、真实资格或服务运行。

## 红绿验证

固定旧工具原字节 SHA：91a74a28600fc5066dbfe4489f1a0a43113b760a52e4142afdd1fa77d817e619。
五个同名场景：实际 WorkingDirectory+脚本形状、七文件相同但 split 实现不同、缺 namespace、相互冲突 roots、plist/manifest secret-safe 输出。
旧工具：5 failed，退出 1，见 logs/final_before_red.txt。新版：上述五例及扩展用例通过。

## 最终验证在补丁实际应用后的目录进行

将 before/ 复制到新的临时目录，git apply tools.patch + tests.patch；逐字节对 after 与完整测试文件；在该目录运行 python -m pytest -q。结果：30 passed，0 skipped，exit 0，见 logs/final_after.txt 和 logs/junit.xml。
随后逆序 git apply -R tests.patch / tools.patch，确认旧工具字节完整恢复、新测试删除。见 logs/verification.json。

## 30 项覆盖

真实 plist 形状及四种明确路径形式；根歧义/相对路径/父目录跳转/不支持的 shell 字符串；拆分实现与 namespace；传递 import/包 __init__；缺件与动态依赖；模块级副作用不执行；文件过大/symlink/FIFO/语法失败/目录预算；manifest 重复键/敏感字段/异常状态值；只创建不覆盖证据/禁止写 canonical；真实临时 Git 的 HEAD/dirty/untracked SHA；文件全相同时仍不授予 lineage/behavior/activation PASS。

扩展测试编写时曾有一个夹具将 None 写入 plist，触发序列化 TypeError。已改为删除缺失键后复验，没有跳过测试或捕获异常伪造通过。最终测试文件与补丁应用后的 30 项日志一致。

不重复 R1 47/R2 27 的未变验收；不把 30 加到它们上面宣称业务链通过。未声称全 V4 测试通过。
