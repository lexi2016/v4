# M04：研究情报与归档

日期：2026-10-10。本包是一个独立 Chat 的编码交接，不是代码发布或测试通过声明。Chat负责方案和具体代码；嘻嘻负责真实Mac独立验收、V5预览接入与精确问题回传。

## 身份、范围与依赖

- 编号按原总计划M04，里程碑P4；早期盘点编号是10，不能套用早期04（A预选）。P1确需的13/15材料入口可先交，不要求等所有P4模块完成。
- 上游：原小时研究、早报、报告/新闻、公众号及归档lane的唯一采集/原归档owner。下游：M05/07、M11、M13、M15、M16及M18只消费已提交引用。
- 本模块拥有材料生产、原文/图片/OCR证据、归档与不可变来源引用。M11的slot研究/研究总结、M12的视频全节点、M13公告语义选股各自独立；不得为材料运输重做这些业务。
- 保留V4源、服务、数据和8910；不交易、不改BUY门、不扩大安全权限或凭据访问。

## 已核事实与当前缺口

固定代码为 `f7cb731c384ee6890a87d16c19a5b5a621779477`。已有 `archive_reader.py`、`archive_article_v2.py`、`archive_builder_v1.py` 和acquisition producer候选，不能写成“全模块未实现”，也不能写成“采集全链已完成”。固定树尚无原计划提议的 `research_ingest_daily.py`。

原归档2058条/34份产物/69文件是迁移计划引用的既有报告，不是本包重测；旧v1缺取得/可用时点不能回写成新证据。9fb身份修复的Mac独立报告记录52/52身份批及36/36相关批分别通过，不能相加称新全套；工程源为固定canonical重建加真实namespace补件。真实同批builder source仍CANNOT_CONFIRM、natural_verified=false，未部署。

早期59/59与身份缺口OPEN已由后续r1身份工程修复接续，但真实来源未因此闭合。原producer README/manifest中的NOT_RUN或历史SHA具有交付时含义，不能覆盖后续回执。原CLI doctor的已报告Keychain error不是已确认根因；认证恢复交用户官方流程，不读秘密或修改系统安全。

## 阅读顺序

1. [PROMPT_FOR_CHAT.md](PROMPT_FOR_CHAT.md)：直接交给负责本模块的Chat
2. [SOURCE_MAP.md](SOURCE_MAP.md)：固定原owner、V5入口和文件身份
3. [ACCEPTANCE.md](ACCEPTANCE.md)：代码交付及真实Mac验收门

## 独占写入边界

本Chat可交付本模块现有三个archive入口、`V5/producers/archive-acquisition-v2/`、`V5/contracts/archive_*`及本模块测试的最小补丁；确需新增编排时候选路径为 `V5/src/v5_shadow/research_ingest_daily.py`、`V5/tests/test_research_ingest_daily.py`。原vendor冻结闭包默认只读，变更须另列原owner修复证据，不整包替换。

运行写根必须由Mac先核为M04私有、不与V4或其他模块重叠。已有capture根标记 `.v5-archive-acquisition`、导入根标记 `.v5-archive-article-v2` 必须保持精确合同；每次有效执行生成不可变新引用，不能覆盖已成功根。上述路径是产品目标，不是本交接文档目录。

`manager_plan.py`、`current_us_research.py`、前端、网关、全局调度/账本和公用manifest不由本Chat跨写。只交接口变更请求与消费者回归建议，统一集成者串行应用；M15/M18不得同时改M04文件。

当前本包仅文档静态核对，产品代码修改、测试、部署均未执行。
