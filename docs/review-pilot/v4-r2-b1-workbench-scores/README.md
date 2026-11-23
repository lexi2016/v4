# V4 工作台评分补件修复候选

基线提交为 `22c56ff0e4a5ea06c70b04471565986e73ebdfd0`。API 读侧以现役 `v4-d20-autoupdate-20261122-api-r1` 的实际文件为前像，叠加在对应 API 应用根。Main 写侧复用路径 A 的原有叠加目录，以现役 `v4-main-plan2-p0-20261123-r4` 的三个实际文件为前像，并增加 `app/ops/workbench_score_calculation.py`。两角色各自的目录用于候选组装。以下名单与日期结果来自只读工件复验。

| 角色和文件 | 前像 SHA-256 | 候选 SHA-256 |
| --- | --- | --- |
| API `research_workbench_host.py` | `1c102c541e5937ed501d7bb7b55884687277241175571d4f6b5599d840ff6ef1` | `167cf79aac24ffb297487e8a062f4f4ab426f7e5efb5f3e2d4443498f5878742` |
| API `research_workbench_formula_group_supplement.py` | `cc4e4c9a83f2303e86194cfb070e9767dfb3bb1d278147822d8c1ef685c6555a` | `f758a622fcb3233829d79a25bcbf54977d37fe22b0cdda540f5a3892396dceda` |
| API `research_workbench_score_action.py` | `605ef003f41279bc6ad1f83618ba4829e741366b402ce7c6c12e2b0bf7592cc1` | `34c8852c94f04b54f7491b81ce16bbb616b02f206ad3ab28eea85a1ea462d13e` |
| Main `materialize_workbench_score_action.py` | `005c8b3ef4723ffc56385d2ad91d5487e3cd3aeb30d56886671f063e39c96b1b` | `5c3df10a228ef220d2167dfd087a4fbbac3e9dec545821aa29301a5970b5ed5f` |
| Main `_formula_groups_daily_parts/workbench_supplements.py` | `c9dae00ec93ed2a6d9332eeb55d7be47130198d57301fc4f336952f8690d041e` | `069883165144a2f0d1b92a4fb05ebfa7031802d6dc13b432a5dd99f3d91c7fd3` |
| Main `workbench_score_calculation.py` | 新文件 | `4e039f65ef92e597bed7af212a7d98ccf8ca523100b1fc854e3a0b177f74b152` |
| Main `research_daily_capacity.py` | `b11f5d9b3c03094798f8bf53a22f0217151b16b3a82eeb5089c933dc0e1d2b8c` | `60a280759de37756d4f2c2936f18b1ed46353da09b61d9f5f2b81f3edeeb9b42` |

计算模块持有输入规范化、资格和目标日判断、KB/N/评分续跑及动作计算。新档案固定其 SHA 和另外八份规则及计算模块的 SHA。写入文件 SHA 单独记录，索引保存各记录的产生者指纹集合。已验证的旧 writer SHA 只在等价计算指纹下复用。只改写入器时，可继续沿已验证的计算、价格、资格和前缀身份复用缓存，且保留原不可变记录的写入器身份。评分、主图和 F10 独立校验。整个补件指针不可信时，行情和列表仍可从原有来源读取。

Main 在有效补件指针提交后，通过原产品所有者的锁和 CAS 更新同日评分索引及事件。只复用已读回的不可变评分记录，重叠记录要求原引用完全一致。日期、代际、原始输入、复权口径、计算规则或编码冲突时保留现有索引。新格式允许同一计算身份下的逐股写入器来源不同。旧格式和新格式同时出现时拒绝将两种记录拼成一个索引，API 仍按现有两份书签分别校验读取。D23 实际两份索引的并集为 306 只，218 + 104 − 16。工作台仍展示其原有的 104 只名单。

针对性测试使用 Mac Python 3.14.6。基础运行命令为 `python -B -m pytest -p no:cacheprovider -q docs/review-pilot/v4-r2-b1-workbench-scores/tests/test_score_publication.py`，15 项通过。另以现役 Main 的只读源码和本批 Main 候选文件组装临时测试目录，复用路径 A 的实际评分多进程、F10 与补件写前守卫、补件受管 Claim 三项测试，3 项通过。相同计算身份下，`tests/verify_score_prefix.py --legacy-writer <只读旧版写入器>` 验证新版和已审旧版前缀均复用 138 行且只计算 1 行，前缀变化时重新校验并计算 139 行。评分、动作、KB 字段和 N 结构业务字段与冷跑一致。测试写入仅发生在隔离目录。

部署和正式接口验收尚未执行。API 可以先做单角色切换验证；Main 的新格式须配合已兼容的 API。回滚使用角色切换前的精确前像。Main 合并阶段遇到 CAS 竞争会拒绝发布，事件替换失败由原发布器恢复索引字节。阶段失败时现有不可变评分记录可继续用于验证和恢复。
