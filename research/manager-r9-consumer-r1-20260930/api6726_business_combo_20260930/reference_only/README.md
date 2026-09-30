# 仅用于精确重建验证；禁止安装

r3b_input 是旧R3B workspace 8a1ce512… 与旧 autorun ec257948… 的原字节。它们只用于在临时目录应用已上传 API integration actual_diff.patch，验证最终完整SHA为35c9292d…/e785ae1d…。测试和源码读回记录验证重建一致，不证明部署。

prepare_combo.py 不读取或复制本目录到任何API候选。它只保留 --base-app 中已经存在的新API源码。不要使用本目录回退新的WorkspaceReadError/SCHEDULED_MORNING。
