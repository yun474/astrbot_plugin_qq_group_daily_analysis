# 初音未来模板图片

这 6 张 PNG 原样取自上游 [SXP-Simon/astrbot_plugin_qq_group_daily_analysis 的修复提交](https://github.com/SXP-Simon/astrbot_plugin_qq_group_daily_analysis/commit/ca7b49275587272f4e3917cbba4ffd224dac9112)（#217，shiitin / Shiitin，2026-08-29）。保留上游文件名和原始图片内容。

上游模板通过 jsDelivr 引用此目录；本 fork 通过 Jinja2 的 `local_image()` 将文件转成 Data URI，直接嵌入图片报告与 HTML 报告，生成时无需访问图片图床。请随插件完整分发此目录。

`retouch_2026032802083201.png` 用于活跃时段背景，其余 5 张用于话题装饰，`retouch_2026032810150449.png` 同时用于群聊锐评装饰。模板原有的字体、图标脚本及其他来源的头像/人格配图不属于这批资源。
