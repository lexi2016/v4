# 新增跨端测试结果

测试主体：`tests/producer_cases.py` + `tests/test_cross_boundary.py`。单次完整集合39项：21个实际Python输出→原TS fetch/parser/full validator→DOM场景，12个序列化负例，3个原镜像材料绑定篡改反例，3个实例/引用/说明合同检查。

原前像：14 failed / 25 passed，exit1，无 setup error。修改后：39 passed / 0 failed / 0 errors / 0 skipped，exit0。日志为 `logs/red.txt`、`logs/green.txt`，JUnit 分别为 red.xml/green.xml；不将两轮或旧回执相加。

## 实际命令

```bash
BI_APP=/mnt/data/bi_fix/candidate BI_OUTPUT=/mnt/data/bi_fix/logs/green \
PYTHONPATH=/mnt/data/bi_fix/candidate:/mnt/data/bi_fix/tests \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
/mnt/data/bi_fix/tests/test_cross_boundary.py -q --tb=short \
--junitxml=/mnt/data/bi_fix/logs/green.xml
```

fixture 内实际调用 tsc 的三个入口：`apps/web/src/api/managerWorkspace.ts`、`apps/web/src/manager-selection/researchAttention.ts`、`announcementObservation.ts`，参数 `--target ES2020 --module ES2020 --lib ES2020,DOM --strict --skipLibCheck`。生产 TS 源码不做测试专用删行/替换，renderer 类型 import 由 tsc 正常消除。

环境：Linux / Python3.13.5 / Node22.16.0 / tsc5.8.3 / 系统 Chromium + Python Playwright。试装 jsdom 超时，未以成功记录；Chromium URL 导航被管理员策略拒绝（ERR_BLOCKED_BY_ADMINISTRATOR），故测试不导航任何 URL，而在 about:blank 页面加载原编译模块。只替换 fetch 传输为 Python 生产输出的 JSON Response；原 requestManagerWorkspace 及全页 validator 实际执行，再调用原两套 DOM renderer。外部请求被 abort；没有真实 socket/8873。

## 测试边界

源/master/资格/文章/ref/行情是明确合成上游。indexed Python projection、mirror_material、subject classifier、relation admission、research_attention、workspace builder 实际执行。为避免缺完整原 owner IO，get_workspace 的 `_compute_workspace` 测试边界返回前述生产函数组合结果；原 GET read_context 包装仍执行。没有 mock 掉本次修改函数、关系准入、TS validator 或 renderer。

同文重复、不同正文/issuer、当前native个股/行业、standing+新US事件、mirror与COMPANY_MATERIAL整卡、公司风险说明均有正例。缺HK来源/取得时钟、US晚于cutoff、同源伪双来源、过期或错误span有效期、未确认研究观点、公司名联想、错误序列化语义/issuer/旧排序时钟、镜像冒充首发、原body/page/ref SHA篡改有负例。

`evidence/IMPORTED_SOURCE_IDENTITY.json` 区分 SOURCE_INDEX 精确源码和作者历史参考导入依赖（非完整本机应用，不得部署）。本轮没有跑旧 R1/R2/R3B/API14/F0–F2 测试。三个截图是原DOM renderer在测试容器的无样式承载页，不是完整SPA/CSS和现场8873页面验收。

IMPLEMENTED=五文件补丁；TESTED=新增39项；BEHAVIOR_VERIFIED=上述合成边界范围。独立 REVIEWED、DEPLOYED、真实 API_VERIFIED/UI_VERIFIED/NATURAL_VERIFIED 均 NOT_RUN。源数据是否满足实际业务准入 CANNOT_CONFIRM。
