# V4 量化研究与复盘系统

> 私有源码审查仓库。**目前是部分源码导入，不是完整项目，也不是已部署版本。**

## 直接查看

- **[查看已提交的代码分支](https://github.com/lexi2016/v4/tree/codex/bootstrap-v4-20260916)**
- **[草稿 PR #1：工程配置与 API／阶段合同／存储源码](https://github.com/lexi2016/v4/pull/1)**
- [代码结构与阅读入口](https://github.com/lexi2016/v4/blob/codex/bootstrap-v4-20260916/docs/CODE_MAP.md)
- [准确导入状态](https://github.com/lexi2016/v4/blob/codex/bootstrap-v4-20260916/docs/IMPORT_STATUS.md)
- [全量导入接续工单](https://github.com/lexi2016/v4/blob/codex/bootstrap-v4-20260916/docs/FULL_IMPORT_NEXT_ACTION.md)

**当前 main 只保存本说明；请点击代码分支或PR查看实际文件。没有把未经完整验收的源码合并到main。**

## 已完成与未完成

| 项目 | 实际状态 |
|---|---|
| GitHub连接及写入 | 已成功，仓库保持private |
| 审查分支 | `codex/bootstrap-v4-20260916` |
| 源码分支HEAD | `3e147289db9806174d756d2395f5b5f6826ade8b` |
| 分支文件数 | 29个，包括24个与原包字节一致的原路径文件、1个迁移到模板位置的CI文件、4份初始化及状态文档 |
| 完整来源包 | 745个文件；其余721个原路径尚未按原位置导入 |
| PR | #1，草稿，未合并 |
| main分支保护 | 读取为未启用；JSON仅为目标配置 |
| GitHub Actions | CI只放在templates中，未启用、未运行 |
| Mac构建与部署 | 本次未执行 |

## 当前可阅读的代码

API启动入口与白毛只读路由；预选池三件套存储、哈希核验与中断恢复；阶段输出、输入来源、冻结日历合同；前端runtime、selection、review请求模块。已提交的工程文件包括CODEOWNERS、PR/Issue模板、Dependabot、依赖声明及目标保护规则。

**App.vue、完整API应用、阶段runner/selection、其余业务模块、依赖锁、测试和完整来源清单仍未上传。此分支不能作为可安装的完整系统。**

## 完整来源包身份

`V4_GITHUB_PROJECT_20260916.zip`，3,247,749字节。

SHA256：`2ce0b590240e80f6fc5009f91ac64435e0cc6f5d08c7a2f97d5d108630568a5f`。

来源包已在隔离环境按清单核验。本次只对上传字节做核验，不把来源包历史测试报告冒充本PR的CI结果。源码分支树SHA为 `fcd9061fd504d92bbc15e24b873c4aeae0753204`。

## 仍需关闭的发布门

`pyproject.toml`的data extra与uv.lock同步；缺失原经理proof模块；旧Mac绝对路径；原生Python3.14、Vue类型检查/构建与浏览器验收；API、scheduler、Stage现役根和源码绑定。配置模板不等于服务端设置已启用。

## 安全边界

不自动合并、发布Release、部署、训练或访问账户/订单。不上传正式数据、凭证、登录状态、历史大数据和旧dist。保持原Vibe8910，8872不重启，Stage8 HK-only以及较新runner、模型/评分/BUY边界不变。

授权已接通，不需要反复重连；剩余是完整文件传输和服务端配置。旧建库脚本为新仓库设计，不能对本已存在仓库盲目重复执行。
