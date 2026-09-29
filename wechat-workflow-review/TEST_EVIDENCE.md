# 测试与导出检查证据

快照目录：`handoffs/github_workflow_review_20260929`。测试均使用此快照中的代码；不含真实文章/业务收据的 V4 测试夹具。

## 已通过

- 公众号边界与 macOS OCR 缓存：`35 passed`。命令从 `source/wechat/` 执行：`PYTHONPATH=scripts python -m pytest -q -p no:cacheprovider tests/test_review_wechat_boundaries.py tests/test_wechat_macos_ocr_cache.py`。使用可用的 Python 3.14 + pytest 环境；pytest 配置报一个未知 `cache_dir` 选项警告。
- 包冻结/回传导入：`9 passed`。`PYTHONPATH=scripts:tests python -m unittest discover -s tests -p 'test_wechat_chat_handoff.py' -v`，使用 Python 3.12 + Pillow。
- OCR 清单准备：从 `test_wechat_prepare_ocr_manifest.py` 独立调用其两个纯 Python 测试函数，均 `PASS`；子进程实际执行导出副本 `scripts/wechat_prepare_ocr.py`。
- 前篇表现附录：`1 passed, 3 skipped`。未安装 pandas 与 PyArrow 的运行环境将三项 Parquet 集成测试按测试定义跳过；这些验证为 `CANNOT_CONFIRM`。
- V4 Stage A 登记、归档读取和 API 子路由：`65 passed`。命令从 `source/v4_app/` 执行：`PYTHONPATH=. python -m pytest -q -p no:cacheprovider --basetemp=.test-tmp tests/test_wechat_stage_a.py`。仅以合成 report/receipt 夹具运行。最终运行有 `cache_dir` 配置选项警告及 Starlette TestClient 弃用警告。
- V4 TypeScript API 客户端：`6 passed`，命令为 `node --test tests/wechat_ui/client.test.cjs`；测试通过本机可用的 TypeScript 编译器编译导出客户端代码。
- Python 源码解析与 CLI 装载：7 个导出 `.py` 文件均通过 `ast.parse`；采集适配器、包导入、OCR prepare、macOS OCR、表现脚本的 `--help` 均 exit 0。
- 导出隐私扫描：最终扫描确认无本机用户名绝对路径、已知 Windows 用户路径、私有 Drive root ID、私钥标记或 GitHub token 前缀。

## 修复测试副本后的复验

Stage A 测试第一次运行时，合成夹具初版仍有日期、文章 ID 和包 ID 映射不匹配，结果 `59 passed, 6 failed`；失败集中在导出夹具和对应测试副本的合成身份，不涉及被复制的归档/路由实现。已改用合成文章日、合成文章标识和明确的合成 package ID，之后整组 `65 passed`。第一次默认 pytest 临时目录清理出现权限/目录非空警告；最终复验将 basetemp 放在快照内，测试通过后删除该临时目录。

## 尚不能确认

- `tests/test_wechat_handoff_v2.py` 未运行：现有环境没有同一 Python 解释器同时可用的 pytest 与 Pillow。新 `event_dispositions` 冻结/导入测试结果为 `CANNOT_CONFIRM`。
- 前篇表现附录的三项 Parquet 集成验证因 pandas/PyArrow 缺失跳过；完整行情文件读取仍为 `CANNOT_CONFIRM`。
- 外部 intake collector 未随快照导出，真实网页/图片抓取和可选 Crawl4AI 浏览器路线没有执行；网络采集不是本次离线验收目标。
- 没有执行真实 macOS Vision/Swift OCR。
- 未组装完整 V4 应用，也未验证真实 archive root、运行服务、exact-date API/UI、Drive 传输、业务文章、自然时段或任何部署状态。Stage A 离线测试只验证合成夹具下的登记器、archive reader 与独立 API 子路由行为。

测试结果只表示上述离线代码范围，不构成业务语义验收、运行部署或发布证据。
