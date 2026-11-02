"""
统一注册 WebUI 插件页面用到的后端接口

接口路径：/astrbot_plugin_qq_group_daily_analysis/<path>
页面端通过 bridge 调用时只写 <path>。只有能登录 AstrBot WebUI 的管理员才能访问。
"""

from __future__ import annotations

from ..shared.constants import PLUGIN_NAME
from .log_routes import LogRoutes
from .report_routes import ReportRoutes
from .task_routes import TaskRoutes
from .template_routes import TemplateRoutes


def register_webui_routes(plugin) -> None:
    """main.py 初始化时调用一次；插件重载时同一路由会被替换为新实例的处理函数"""
    groups = [
        ReportRoutes(plugin.report_generator.report_archive),
        TemplateRoutes(plugin.template_admin_service),
        TaskRoutes(plugin.task_registry, plugin.incremental_trigger),
        LogRoutes(),
    ]
    for group in groups:
        for path, handler, methods, desc in group.routes():
            plugin.context.register_web_api(
                f"/{PLUGIN_NAME}/{path}", handler, methods, f"群分析插件: {desc}"
            )
