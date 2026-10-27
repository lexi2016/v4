# 已审研究源码小型增量 · 2026-10-27

目标为既有 `research/panel-code-20261027` 分支的增量；原成功提交 `1bef4c55140f7062d2b24f8aee915cc99844bd35` 不重传、不覆改。此目录**仅本地准备，未push**。

## 覆盖与限制
- `state_incremental_v1`：冻结六股算法、journal、holdout driver和三份tests，独审仅授权受限算法/候选日志研究。六股历史等值不代表全池。
- `state_consumer_v1`：冻结三股consumer、state adapter/journal、canary/resume driver和test；不包括新5073全池版本或任何未审扩大版本。
- `SOURCE_MANIFEST.json`逐项保留原文件路径、原SHA、导出SHA。12份源码**逐字一致**，没有脱敏改写代码。
- `AUDIT_SUMMARY.json`是白名单字段派生摘要，提供原独审SHA/status和代码SHA；不是原回执，也不授予新用途。

## 没有包含
真实行情、持仓/用户资料、历史/日指标、state文件、授权scope原件、输入config、私有绝对路径配置、日志/原始独审详细输入、credentials、生产配置或新全池实现。

代码内 `ROOT_SCOPE_SHA` 等是校验hash引用，不是凭据或实际授权负载。真实 `ROOT_CANARY_SCOPE.json` **没有包含**，不得从hash常量推断获得运行授权。默认缺授权文件即失败，不能为了跑通自行补造/取消校验。

## 合同与依赖
原冻结公式SHA：`d35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac`。
原式解释器SHA：`ae4243ec9582055fb6f2ee796978ad20e17f9dee7a56388063cbdbcb56ef0d1c`。

依赖原仓库原式及研究代码、已审mother_overlay core/writer、授权输入和回执；未把它们重复打包。测试中的相对路径/缓存数据依赖原样保留，真实fixture未导出，因此静态语法通过不代表在克隆目录已运行或已重做独审。

状态与单日日志配对、不可变写入、相同pair复用、source/event/policy/calendar绑定以及失败关闭保持原代码语义。当前不授予public reader、网页显示、训练、生产、自然日更或全池准入；不替代已有每日历史指标。

本包无网络调用、下载、重算或实际业务测试；只进行了导出副本哈希、语法、敏感模式/绝对路径扫描。公开仅限用户授权研究源码；没有新增许可声明。
