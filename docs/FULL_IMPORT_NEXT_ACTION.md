# 对现有私有仓库完成全量导入

本工单面向能够直接读取完整ZIP并使用已登录GitHub CLI/Git的本机Codex。不要求用户重新上传数据、不新建第二仓库、不触碰正式服务。

## 已确定对象

- 仓库：lexi2016/v4；repository ID：1373086047；必须为private且owner为lexi2016。
- 分支：codex/bootstrap-v4-20260916；保留本次草稿PR，不合并。
- 来源包：V4_GITHUB_PROJECT_20260916.zip。
- ZIP SHA256：2ce0b590240e80f6fc5009f91ac64435e0cc6f5d08c7a2f97d5d108630568a5f。
- EXPORT_MANIFEST SHA256：1f032eed783dfa1dc0c5b15ff265627b61e96183eca7df9b9634de98726617e0。

## 顺序

1. 用既有gh登录态读回仓库ID、private、owner、main和目标分支的真实HEAD。只在新隔离clone执行；不输出凭证或环境全集，不把本机正式源码目录当导入目标。
2. 使用上述精确ZIP安全解压。先核对ZIP SHA，再逐项核对EXPORT_MANIFEST中744条路径、字节数和SHA，另核对清单本身；拒绝路径穿越、重复成员、软链接、额外文件、缺文件和凭证。
3. 按远程实际树核对本次24个原路径文件。已经与ZIP一致的保留；不同字节须停止并审查，禁止用git reset --hard或强推压掉后续修改。README和本次docs是仓库初始化文档，不是原包字节；需要在导入提交中显式处理并保留历史。
4. 用原包 .github/settings/repository.json 和 main-protection.json 配置并读回服务端规则；没有管理权限或套餐不支持时记录精确失败，不改公开、不降保护、不将模板当已启用。不允许自动合并。
5. 将744条已验证文件及EXPORT_MANIFEST一次性按字节复制到同一审查分支；没有入清单的大数据、旧dist和正式证据不得上传。恢复原位置 .github/workflows/ci.yml，删除本次 .github/templates/ci.yml 副本。来源清单保留其历史语义，不伪称Mac现役。
6. 静态与凭证检查后仅普通push，禁止force。远程递归tree的路径集和Git blob SHA必须与导入后的精确清单一致；README状态更新作为单独可审查差异记录。
7. 更新同一个草稿PR和IMPORT_STATUS：分别报告原包文件导入数、额外仓库元数据、文件哈希差异、服务端保护状态、CI运行结果。任何缺件或未运行检查不得标为PASS。

旧 tools/github_bootstrap.py 的默认执行路径设计为创建新仓库，会拒绝未经它创建的既有仓库；本次仓库已经由用户创建并已有提交，不应盲目重复执行该新建路径。

## 不在本工单范围

不使用现时行情填历史；不训练、不动模型/评分/BUY、不访问账户或订单；不修改正式数据，不重启8872、不变更Vibe8910；不把旧dist放回修复后的源码。正式激活另须Python3.14、前端原生typecheck/test/build、实际浏览器与原唯一Writer/独立Reviewer验收。
