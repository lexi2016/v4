# V5 实际验收与最短接续

状态截至 2026-10-08：工程合成链路已有独立 Mac 证据；真实业务与生产运行未完成。

## 已执行结果

固定产品提交：`054782a08e8eb701b98714eeb0fadbd60153725c`。

- 环境：Mac，Python 3.14.6，pandas 2.3.3，pyarrow 24.0.0；7 项依赖与固定 uv.lock 对应。
- 审查回归：10/10 PASS。
- 完整 unittest 套件：78/78 PASS，exit 0，未跳过。
- 52 份来源文件核验，18 份冻结 vendor 文件未改。
- 原始输出保留 4 条 HTTPError 清理 ResourceWarnings；未将它们删除或记为无警告。
- 测试提交 bcff 的历史 RED 未执行。当时 Mac 传输中断，用户明确允许先修静态已证实问题再本地测试；不能补写成 RED 已通过复现。
- 证据文件名：REVIEW-FIX-FINAL.md、review-fix-full.stderr.log、review-fix-source-manifest.json，留在原 Mac 独立测试输出中。

此前 41→49→54→60→63→68 项结果为历史阶段，不能相加成总测试数。

## 本批规范化测试结果

固定候选 `1167ed3ea2aa7e8c8e1b2d79f4e490beec1395fb` 仅新增 provider_evidence.py 和 test_provider_evidence.py，远端两个文件完整内容及 SHA 已核对。

13:30 北京时间预检发现原临时隔离根及 locked-venv 不存在，exit 127；11 项及全套均未运行，原 78 PASS 日志也无法从旧路径重新读取。随后在原会话恢复持久目录 V5-test-1167ed3 及同锁私有 Python 3.14.6。新增 11/11 PASS，全套 89/89 PASS，均 exit 0；全套于 05:32:58—05:33:30 UTC 实际执行，耗时 31.612 秒。源码及 vendor 18 项运行后 SHA 未变，4 条 HTTPError ResourceWarnings 保留。持久 evidence/RESULT.md 与 full.stderr.log 为本批新回执，不冒称恢复了旧日志。未另外重跑原 78 项，不新建测试会话。

这批只规范化 SDK 原值与语义字段：缺失不填零、普通股票 stock_owner 不适用、衍生品所需 underlying 不得省略。它尚未接入真实 collector/publisher，也不证明目标日成员资格。

## 页面验证边界

source-only 入口已生成合成结果严格 1、接近 2、排除 1，临时服务与 fixture 已清理。普通浏览器读取/截图工具不可用，未取得截图，视觉验收 BLOCKED。HTTP/HTML 测试不取代实际浏览器验收。

## 真实数据及剩余工作

- OWNER_VERIFIED 输入准入尚未开放；不是给数据改一个标记即可运行。
- Mac 明确配置的 HK02 资产根缺 10/7 panel/master；指定 VIPDOC 根内 713 个文件尾部检查未见 10/7，689 个最新为 10/2。结论仅限该检查范围。
- 原更新器只能消费已有真实历史记录，不能在 10/8 用当前快照假造 10/7。
- 仍需原生产入口一致版本闭包、私有写根、来源/单位/日期证明、真实结果同 run/SHA 的 API/UI 验收，以及真正自然时段的自动运行证据。
- 没有生产部署、V4 修改、真实行情补采、下单或 BUY 门变化。

## 接续入口

使用原隔离环境及 source-only 脚本，不换活动 V4 根、不安装全局依赖。产品入口：

    python -B run_shadow.py check --composition COMPOSITION_JSON
    python -B run_shadow.py run-shadow --composition COMPOSITION_JSON --request REQUEST_JSON --output-root PRIVATE_SHADOW_ROOT
    python -B run_shadow.py read-result --output-root PRIVATE_SHADOW_ROOT --target-date YYYYMMDD --run-id RUN_ID

所有新的失败保留原日志和 exit code，由代码作者修复；本机测试不修改断言或产品实现来凑通过。
