# M04验收与回滚

状态统一为：代码接入、真实数据通过、页面可用、自动接续、完整验收。五项分别登记，只有完整验收才可计完成M04。工程测试单列证据，不替代真实数据、页面或自然自动接续。以下是待执行清单，不是本次通过记录。

## 代码与原回归

- 固定候选commit、最小patch SHA256、每文件前后SHA/Git blob、依赖manifest；Mac真实前像不匹配就停相关应用，不整文件强盖。
- 必须保留原 `test_hourly_research_runner.py`：同身份跳过、receipt/transform tamper拒绝、LIVE/non-LIVE/latest分离、历史中断恢复不移动latest、源字节冻结。
- 必须保留原 `test_research_archive.py`：原去重/时区、精确日不fallback、manifest/receipt/reparse拒绝、BACKFILL/REPLAY不改latest。
- V5针对性批在仓库根按现有Mac解释器与真实隔离原source路径执行：`PYTHONPATH=V5/src:V5/tests python3 -B -m unittest test_archive_article_v2 test_archive_builder_identity -v`；另批 `test_archive_acquisition_producer test_current_us_research test_manager_archive_reader test_us_mapping_scope test_manager_plan`。实际环境先按r1报告核，不盲用系统Python或猜source路径，不安装新依赖。
- 新增各lane中断/并发/重试/输入改变测试，以及GET前后全写根字节和job/run数量不变。错误输入不得覆盖前成功。
- 52/52和36/36为既有独立报告，非新候选已过；59/59是更早批次。不得相加为当前全套。

## Mac真实闭环

1. 核活动V4源身份与只读副本、M04唯一writer、私有capture/import/output根、真实入口与既有认证状态；保存原V4相关资产摘要，不复制凭据。
2. 以真实同批page原文、receipt.v3、status、recent、summary、完整builder source及owner receipt形成闭环。正文/图片/OCR缺口如实保留；没有取得时间的旧2058条继续标缺，不重写历史。
3. 相同target/slot/input/code/config身份至多一个运行；失败attempt独立，前成功sha不变。重启只恢复允许的断点，变更输入另建身份。
4. 原store与独立reader读回同SHA，消费者M11/13/15至少按实际接线逐一核引用；提前cutoff排除，不能由阅读成功宣称选股资格成立。
5. V5预览真实浏览器进入材料页、切日、刷新、返回、展开原文与缺图状态。界面、API、receipt一致；记录URL、run、generation、代码SHA、截图。若浏览器或真实来源不可用，分别NOT_RUN/BLOCKED，不用HTML200顶替。
6. 按原各lane实际合同常规触发并在下一适用时段更新，逐lane覆盖。一次恢复或一篇材料不能关闭全部范围；手动、恢复、历史和自然身份各自保留。更高层P5要求的连续适用日证据另行登记。

## 隔离发布和回滚

由嘻嘻指定唯一集成/发布者，以expected-generation/CAS切M04引用；先新进程或确认可热读的合同核真实身份，再切预览。记录旧/新release与generation。失败时仅恢复M04已核旧引用或旧进程，保留失败attempt及新不可变产物，不删除成功历史、不移动V4指针。回滚后核M11/13/15/18既有已提交引用可追溯，其他模块版本/API和V4摘要不变。

## 问题回传

回同一Chat：固定commit、真实输入identity/SHA、命令与退出码、完整错误、期望/实得、写根前后摘要、API/页面证据、最小复现及回滚状态。缺少来源/认证时只给非秘密错误，不发令牌或媒体正文。Chat给唯一修正版，Mac不平行实现第二套。
