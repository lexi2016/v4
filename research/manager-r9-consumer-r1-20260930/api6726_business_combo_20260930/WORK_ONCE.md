# Work：一次隔离应用与定向复验

## 一条命令（在本包根目录）

```bash
"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" tools/prepare_combo.py --base-app "/Users/lexi/Desktop/学习/agents调试/MANAGER_API_INTEGRATION_20260930/candidate/app" --output "/Users/lexi/Desktop/学习/agents调试/MANAGER_B1_US_API6726_ACCEPTANCE_20260930/run1"
```

输出目录必须不存在；可换成另一个新目录，不限嵌套层级。输入必须是已验 API 6726 候选，不能改成旧 R3B app。工具读取该输入，复制到 `run1/app`，只应用原 `original_business/runtime.patch`。不应用 integration diff，不复制 reference_only，不安装旧 cycle，不覆盖新 workspace/autorun。

随后运行原 B1/US 33 项；输出 `patch_check.log`、`patch_apply.log`、`test_result/pytest.log`、`junit.xml`、`receipt.json` 和 `application_receipt.json`。receipt 记录完整新组合前后 pin，不从执行者或模型名称推断独立性。

## 通过信号和边界

33 tests / failures=0 / errors=0 / skipped=0，12项组合源码身份不变；application 状态为 `B1_US_APPLIED_AND_TESTED_B2_NOT_ADMITTED`。仅该选定范围 exit=0，不代表 B2、真实资格、API/UI 全部通过。独立审核只针对本次新增两工具、新 profile 与组合结果，不重跑已验旧14项、不重写旧业务或41项。

仅两改一增：
`v4/manager_research/workspace_announcements.py`、`issuer_us_relations.py`、新增 `eastmoney_run_history.py`。完整 after 见原包 `original_business/after/api/`；原 SOURCE_PINS 和新 COMBINATION_PINS 对照即可。任何其它源码差异都不是本包实施内容。

若输入不是新 API 前像，工具在输出目录创建前停止并给精确路径；不得通过改 pin、降级 workspace、覆盖 autorun 凑绿。若依赖导致测试失败，回传该日志／原异常和涉及路径即可，不能换旧 reference 依赖补环境。没有宽泛研发任务转交 Work。

## 回退

本包不修改输入 app。停止采用／删除新隔离目录即可放弃候选，保留日志；不重启任何服务。确需在隔离 app 内反向验证时，从 `run1/app` 对包内绝对路径执行 `git apply --check -R .../original_business/runtime.patch` 后执行 `git apply -R ...`，再按 COMBINATION_PINS.base_sha256 核对两改前像并确认新增文件已移除。不要在原 API 或 release 上执行。

## 一次 B2 回传（不阻挡上述33项）

只按 B2_ENTRY_STATUS.md 确认3条当前目标路径是否与已经上传的 blob 一致。相同只交身份映射，无需重传源码；不同或缺文件则只回传相应最终字节／缺失事实，再给列出的非敏感开关字段。无需整项目、原始plist、空间任务或17:20材料。
