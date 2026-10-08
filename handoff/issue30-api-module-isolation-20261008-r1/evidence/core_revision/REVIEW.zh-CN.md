# Issue #30：core 独立审查修订记录

## 冻结范围

本次只修改 `ops/api_release_integration.py`，从主线程已冻结的前像 `0b9d3b678dc7e875b9514bd8b66b7e8fc69229759c366ef0df776126746180bf` 出发；没有修改主线程候选、builder、prepare 或实际 cutover 脚本。新增 `tests/test_core_review_revision.py` 18 个参数化用例。精确大小、Git blob 和 SHA256 见 `FROZEN_IDENTITY.json`。

冻结后像 SHA256：`f79e774cfaf1d02a323b402ec9f2a52d938e8197af9914a7efc331a7b716ca18`。

## 修复一：分开处理 release 新增与 Git 未跟踪状态

原实现要求 `before_sha256 is None` 的所有 delta 路径与 `explicit_untracked_paths` 完全相等。这把“当前 active 没有这个文件”和“源码 Git 没跟踪这个文件”混在了一起。已提交进 Git 的合法模块新增文件因此被拒绝；源码未跟踪但替换 active 已有路径的合法情形也被拒绝。

修订后，receipt 的严格路径、owner、前后 SHA/mode 与 diff 合同继续授权发布差异。`explicit_untracked_paths` 必须规范、唯一，而且是 receipt 路径的子集，不能借它加入 receipt 之外的文件。

新增可选参数 `source_path_allowlist`。builder 应传入其核定的 Git tracked 路径与已明确批准的实际 untracked 路径的并集。core 在创建候选 app 之前检查所有 receipt 路径都在此集合内，防止 ignored 或未批准的源码文件进入候选。允许列表中的非 delta 文件仍然不会复制。

Git 状态由 builder 负责。此 core 不调用 Git，也不把 receipt 相对 active 的新增状态冒充 Git 状态。直接调用 core 时允许省略 `source_path_allowlist`，仍要求完整、合法且来源字节严格匹配的 receipt；正式 builder 必须传入该列表。

## 修复二：目录集合及权限保留

历史 `application_inventory` 只记录文件和符号链接。原实现在复制时保留了空目录和目录权限，但之后的验证没有把目录状态与 baseline 或构建结果比较。候选建完后改目录权限、删空目录或增未声明空目录，文件 inventory 都不会变化。

新增 `directory_preservation`，作为 `api_integration` v2 的必需字段：

```json
{
  "schema_version": "v4.api_release_directory_preservation.v1",
  "base": {"entry_count": 1, "aggregate_sha256": "<64 lowercase hex>"},
  "candidate": {"entry_count": 1, "aggregate_sha256": "<64 lowercase hex>"},
  "added_paths": [],
  "new_directory_mode": "0755"
}
```

目录 digest 对规范排序的 `{path, mode}` 清单计算；`path="."` 表示 app 根。目录数量、集合、目录 mode 和空目录均进入证明。inode 等物理身份继续保留在仅用于本轮读写复核的 descriptor 快照中，不写成跨复制身份。

验证要求如下：

- base 目录（包括 app 根与空目录）必须全部保留，权限完全相同。
- 新目录只能来自 `before_sha256=null` 的 delta 文件必要祖先；不能添加独立空目录。
- 新目录的最终权限固定为 `0755`，不继承源码目录权限。
- 构建期间先用临时可写权限完成复制与 delta，最后从最深层开始恢复 base 权限，支持保留只读 baseline 目录。
- base 与 candidate 的目录 count/digest 都由候选 manifest 中的证明绑定；即使后来同时改动 base 与 candidate，使两边目录重新相同，验证仍会拒绝。
- 已有此 v2 证明的 release 被再次读作 active 时，也要匹配自身 manifest 的 candidate 目录摘要，避免下一轮把已发生的目录漂移当作新 baseline。

所有目录枚举、打开和 chmod 都使用既有 descriptor / `NOFOLLOW` 路径边界。目录快照另外增加枚举前后 fd mode/identity 对比；最终仍复核完整物理快照和 active 指针。

## 合同兼容性

`SCHEMA_VERSION` 仍为 `v4.api_release_integration.v2`；历史文件 inventory、base 九键、delta receipt v2 字段与 module ownership policy 摘要均不变。

`api_integration` 新增必需的 `directory_preservation`；本轮早期未带此字段的 v2 候选须重新构建，不能继续使用。真实历史 R2 base 若没有 v2 集成块，按原有 manifest 文件 inventory 接受；本次从实际观测目录建立候选证明，不宣称历史文件 inventory 曾经覆盖目录。

## 复现与验证

所有测试均使用隔离本地合成文件系统 fixture，没有启动服务、调用真实 API、改写业务数据或部署。

| 记录 | 实际结果 | 说明 |
| --- | --- | --- |
| `review_red.*` | 3 FAIL | 原独立审查脚本字节未变：committed 新增两种调用和目录 mode 漂移均复现 |
| `focused_red.*` | 16 FAIL / 1 PASS | 新增定向测试最初 17 例，对未修 core 执行 |
| `active_directory_red.*` | 1 FAIL | 后补“新 v2 active 目录身份”用例，对未修 core 执行 |
| `focused_green.*` | 18 PASS | 最终定向测试集全部通过 |
| `compatibility_green.*` | 103 PASS | 原发布套件 85 例，加本次 18 例，包含 delta CLI 9 例 |
| `core_review_green.*` | 2 PASS / 2 deselected | 原审查中 committed 新增不带冗余 flag、目录 mode 漂移两例通过；builder 冗余 flag 与 scheduler 由主线程修订 |

不可把复跑累加为新用例：本次新增唯一用例为 18；另复用了原审查的三个失败探针。原审查带冗余 tracked flag 的场景需要主线程完成 builder 分类修订后统一复跑，不能凭本次 core 结果宣称整个构建流程全部修好。

每次运行的完整命令、工作目录、退出码和 JUnit 统计均记录于对应 JSON；完整输出和 JUnit 保留。实际运行时使用既有隔离 Python 3.14.7 / pytest 9.1.1，不安装依赖。环境清除 `PYTEST_ADDOPTS`、`PYTEST_PLUGINS`，禁用插件自动加载及 pytest 缓存、pyc 写入。`RUNTIME.json` 记录 Linux、EUID 0；只读目录用例确认最终 mode、目录结构与文件字节，未替代 Mac 普通服务用户的权限验收。

## 独立审查和未执行事项

冻结源码已送原独立 reviewer 复审，本文不是独立审查通过结论。builder 需传入新 allowlist 参数；实际 cutover 脚本需更新固定 core SHA，再由主线程完成整合及独立验证。

Mac 权限和运行闭包、真实 active 配置/目录、部署、API/UI、自然运行均未在此环境执行。`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。本次没有修改权限规则、服务、金融业务数据或 GitHub。
