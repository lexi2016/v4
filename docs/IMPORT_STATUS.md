# GitHub 导入状态

状态：**PARTIAL_SOURCE_IMPORT / DRAFT_ONLY / NOT_DEPLOYED**。

2026-09-16，已实际接通私有仓库 `lexi2016/v4`，repository ID 为 `1373086047`。main 的初始化提交为 `8e27c2fd301a5663dda41946f327c0afbcad167a`；源码审查分支为 `codex/bootstrap-v4-20260916`。

## 来源与完整性

完整来源包：`V4_GITHUB_PROJECT_20260916.zip`，3,247,749 字节。

SHA256：`2ce0b590240e80f6fc5009f91ac64435e0cc6f5d08c7a2f97d5d108630568a5f`。

包内共745个文件；EXPORT_MANIFEST.json列出其余744个文件，该清单本身的SHA256为 `1f032eed783dfa1dc0c5b15ff265627b61e96183eca7df9b9634de98726617e0`。本轮已在隔离容器重新核验全部清单字节，没有据此声称已经全量上传。

本分支只导入其中24个原路径文件，另把原CI文件的相同内容放在 `.github/templates/ci.yml`，并增加本次状态说明。包括README在内共29个远程文件；这不是745文件全量源码，也不是可安装的依赖闭包。原包其余721个路径尚未按原位置上传。

已导入的原路径文件保持原字节。不要把换行规范化导致的SHA变化当成可忽略差异。remote tree和本地按同一文件字节计算的Git tree须一致。

## 尚未完成

- `apps/web/src/App.vue`、完整API应用、阶段runner/selection、其余业务模块、依赖锁、测试和完整来源清单尚未上传；AGENTS指向的SOURCE_LINEAGE仍需从原包补齐。
- 当前写入接口接收文本，不接受本地ZIP路径；容器直接Git连接因DNS失败。不是再次授权即可完成的情况。
- main的最新读取结果为 `protected=false`。`.github/settings/*.json`仅是目标配置，当前接口没有仓库管理设置写入动作，不能称保护已经启用。
- `.github/templates/ci.yml`是未启用模板，不在workflows目录；不让缺源码的半成品运行一套注定缺文件的CI。完整导入后应使用原包 `.github/workflows/ci.yml` 并删除此重复模板。
- Dependabot、Issue和PR模板当前仅在草稿分支；不声称已在默认分支生效。
- 没有GitHub CI结果、Mac构建或浏览器验收，没有合并、release发布、部署、训练和下单。

## 接续

见 `FULL_IMPORT_NEXT_ACTION.md`。仓库已经存在且已有真实提交，不要再运行旧脚本的新建仓库路径，更不要改成公开以解决连接问题。完整导入必须是一次有文件清单和远程哈希核验的批量传输，不能把本次部分提交当作完成。
