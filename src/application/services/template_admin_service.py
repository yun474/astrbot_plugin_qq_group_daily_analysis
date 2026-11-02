"""
模板管理用例（WebUI 模板管理页使用）

列表、设为默认、安装、卸载、预览。安装和卸载后清理模板缓存，无需重启即可生效。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ...infrastructure.config.config_manager import ConfigManager
from ...infrastructure.reporting.generators import ReportGenerator
from ...infrastructure.reporting.sample_data import build_sample_analysis_result
from ...infrastructure.reporting.template_installer import (
    TemplateInstaller,
    TemplateInstallError,
)
from ...utils.logger import logger

# 卸载当前模板后回退到的内置模板
FALLBACK_TEMPLATE = "HatsuneMiku"


class TemplateAdminService:
    def __init__(
        self, config_manager: ConfigManager, report_generator: ReportGenerator
    ):
        self.config_manager = config_manager
        self.report_generator = report_generator
        self.html_templates = report_generator.html_templates
        self.catalog = self.html_templates.catalog
        self.installer = TemplateInstaller(self.catalog)
        # 安装/卸载串行执行，避免同名并发安装
        self._lock = asyncio.Lock()

    async def list_templates(self) -> dict:
        templates = await asyncio.to_thread(self.catalog.list_templates)
        return {
            "current": self.config_manager.get_report_template(),
            "templates": [t.to_dict() for t in templates],
        }

    def set_default(self, name: str) -> None:
        if not self.catalog.exists(name):
            raise TemplateInstallError(f"模板 '{name}' 不存在")
        self.config_manager.set_report_template(name)
        logger.info(f"报告模板已通过插件页面设置为: {name}")

    async def install_from_github(self, repo_url: str, name: str = "") -> dict:
        async with self._lock:
            result = await self.installer.install_from_github(repo_url, name or None)
            self.html_templates.clear_cache()
            return result

    async def install_from_zip(
        self, zip_data: bytes, name: str = "", filename: str = ""
    ) -> dict:
        async with self._lock:
            result = await asyncio.to_thread(
                self.installer.install_from_zip,
                zip_data,
                name or None,
                fallback_name=Path(filename).stem if filename else "",
            )
            self.html_templates.clear_cache()
            return result

    async def uninstall(self, name: str) -> dict:
        """卸载自定义模板；如果正在使用，自动改回内置模板"""
        async with self._lock:
            await asyncio.to_thread(self.installer.uninstall, name)
            self.html_templates.clear_cache()
            reverted = False
            if self.config_manager.get_report_template() == name:
                self.config_manager.set_report_template(FALLBACK_TEMPLATE)
                reverted = True
                logger.warning(
                    f"当前使用的模板 {name} 已被卸载，报告模板已自动改回 {FALLBACK_TEMPLATE}"
                )
            return {
                "name": name,
                "reverted_to": FALLBACK_TEMPLATE if reverted else "",
            }

    async def render_preview(self, name: str) -> str:
        """用内置示例数据渲染模板预览 HTML"""
        if not self.catalog.exists(name):
            raise TemplateInstallError(f"模板 '{name}' 不存在")
        html = await self.report_generator.render_preview_html(
            build_sample_analysis_result(), name
        )
        if not html:
            raise TemplateInstallError("模板渲染失败，请查看插件日志")
        return html
