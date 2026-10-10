# 原US采集闭包独立审查修复

父线程对30861db静态审查发现清单外Python文件和sys.path包可在逐字校验后执行。本轮以隔离临时目录实际复现：额外ops/__init__.py、parts/__init__.py、legacy pyc、外部同名ops包和合法头部但被替换执行体的pycache。原入口红测7项/5失败，保留日志；并非已发生业务源篡改。

最小修复限cloud_us_collector：逐项验证源树，拒绝清单外文件/目录及symlink；固定finder只给ops/infrastructure/contracts的已列模块或确切namespace生成spec，禁止fallback到sys.path同名包。loader读取并重新核SHA后直接compile源码字节，不加载或写入pyc。可保留对应已列源码的普通__pycache__，避免误拒合法运行缓存；无对应源码的缓存拒绝。导入后/入口finally审计module.__file__/__spec__.origin/name/loader和package/namespace搜索路径。原48文件和manifest PIN不变。

最终18/18通过，exit0，2.294秒；包括8个既有transport测试及10个collector测试。新增负测覆盖额外__init__、legacy及namespace pyc、带有效原头的被替换缓存、外部同名包、spec.origin篡改与namespace.__path__篡改；正常缓存可以原样保留。

新增正向合成链：同一个guarded transport的1份Tencent格式报价及5份RSS响应→原CLI→原三件套→原ResearchPeripheralStore.read_exact逐字相等；33报价、24行业行全部READY、RSS非空，原read前后目录全部文件SHA不变，订单/production仍false。测试socket/DNS实际调用被审计钩子拒绝，实际拒绝域名没有再请求。此前12/12仅含拒绝链，不应称为完整成功采集验证；本次正向也只是合成，不是现实网络/业务/自然接续验收。

补证：父线程10:07:37在另一云端桌面19096、tab5实际看到version1页面并markDeliverable，旧18896保持；title“经理选股工作台·V4”是原UI字样，不是切换现役V4。本容器未自行操作Chrome，也未把该云端桌面验收称作Mac IAB。Library version1及其源码bd3d4fb、数据PARTIAL不变，本轮collector修复没有页面字节变化，无需重复打包。

全量UI17个失败节点原栈已脱敏保存round3-ui-17-failure-stacks.txt，缺件错误不代表补原件后所有业务断言必通过。689行用例依赖两件：OCT2_RESEARCH_SELECTION_PROJECTION原gzip和V5_ISSUE8R2_OBSERVATIONS原ownerObservations JSON；不能只登记projection。其他真实缺件与01—18/P0—P5/Mac清单沿用ROUND3.md。

源码检查命令：PYTHONPATH=V5/src V5/.venv/bin/python -B -m v5_shadow.cloud_us_collector --owner-root /workspace/v5-us-collector-final --check-only，48文件、exit0、network_checked=false。

测试命令：PYTHONPATH=V5/src V5/.venv/bin/python -B -m unittest discover -s V5/tests -p 'test_cloud*.py'。原日志在/workspace/v5-evidence/round3，SHA索引collector-review-evidence.json；红测、语法修正前错误、绿测均保留。断连只读诊断另见DISCONNECT.md，未因此重启或改变任何服务。
