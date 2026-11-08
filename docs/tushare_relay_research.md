# Tushare 第三方 relay：隔离研究能力目录

该工具快照 Tushare 官方接口菜单，并对用户选定的少量接口做小请求。它不是官方直连，也不替换 V4 行情来源、selector 或任何 owner。金融研究标志固定为 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

服务商公开教程要求不要批量探测接口，并建议历史分钟数据走网盘。工具默认只采集官方公开文档；relay 请求必须显式指定，当前限定 `daily_basic`、`income` 和 `index_member_all` 三种代表，最多三次主站接口尝试。官方目录的其他接口保留 `DOCUMENTED_NOT_PROBED`、参数未解析、本地 SDK、账户操作或其他明确状态。目录描述不等于服务商已开通。实测空表也不能证明无权限或无数据。历史分钟不在本批请求范围。

## 运行

使用已验证的 Python 环境（需 `requests`、`beautifulsoup4`）并在本源码根运行。下面路径只是示意：配置文件由使用者提前提供，权限必须为 `0600` 或更严格，包含 `TUSHARE_TOKEN`、`TUSHARE_HTTP_URL` 和可选的 `TUSHARE_FALLBACK_HTTP_URL`；不可提交或打印文件内容。输出目录应为独立、专用的新目录，不能是 V4 数据根或活动 release。

```sh
python ops/audit_tushare_capabilities.py catalog --out /path/to/new-isolated-audit

python ops/audit_tushare_capabilities.py probe \
  --out /path/to/new-isolated-audit \
  --env-file /path/to/private/relay.env \
  --prior-receipt /path/to/verified-prior-receipt.json \
  --api daily_basic
```

`--api` 可以在后续命令中选择尚未尝试的代表。每项在发送前持久化 `REQUEST_DISPATCHED`，进程中断后标 `INTERRUPTED_OUTCOME_UNKNOWN_NO_RETRY`，不会自动重发；一次审计共不超过三个不同的代表。默认仅访问主站，串行发送、间隔至少 3 秒，连接/读取超时和响应体积有上限，不跟随重定向、不保存 provider 错误原文。只有显式使用 `--allow-fallback` 且主站发生连接或超时传输异常时，才允许尝试备用站；拒绝权限、重定向、HTTP 错误或业务错误均不换站。启用备用会增加一次 HTTP 尝试。凭据、端点及冻结目录变化会拒绝在原审计目录续跑。

目录分母由当次官方菜单的去重 doc_id 冻结，页面原始字节、来源、抓取时间、SHA、参数表和可安全静态读取的示例随之保存。页数与唯一 API 名称数分别统计；不能自动识别的页面不消失。`capability_report.json` 的 `api_records` 提供逐接口状态，`records` 保留页面状态。官方文档可能变更，多接口页面的参数未必能够可靠对应，未确定部分保持未测状态。

## 给既有 V4 owner 的只读入口

隔离目录的 `manifest.json` 绑定 `official_catalog.json`、`capability_report.json` 和每个小样本的 SHA。样本保留第三方 relay 地址、接口、参数、请求日期/报告期、实际观察时间、市场和 `run_id`。日期仅描述请求；字段/数值是否满足请求、正确性和披露可用时间仍需独立核验，`available_at` 与 PIT 均为 `CANNOT_CONFIRM`。读取示例：

```python
from pathlib import Path
from infrastructure.tushare_relay import read_isolated_sample

sample = read_isolated_sample(Path('/path/to/new-isolated-audit'), 'daily_basic')
```

reader 校验 manifest、目录、报告、样本字节及声明身份，只返回隔离样本，不进行正式导入。后续若要用于公司材料或研究面板，仍须由原有 owner 验证实际市场、候选池、日期、`numeric_manifest`、generation、input SHA 及其 index/shard 合同；池外证券不能强写候选产品。未经数据 owner 的语义和 PIT 验收，不能将该目录当作新权威源、完整历史或生产输入。本代码不改变正在运行的 API、数据或调度。
