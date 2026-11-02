"""模板管理接口"""

from __future__ import annotations

from astrbot.api.web import PluginUploadFile, error_response, json_response, request

from ..application.services.template_admin_service import TemplateAdminService
from ..infrastructure.reporting.template_installer import (
    MAX_ZIP_SIZE,
    TemplateInstallError,
)
from ..utils.logger import logger


class TemplateRoutes:
    def __init__(self, service: TemplateAdminService):
        self.service = service

    def routes(self):
        return [
            ("templates", self.list_templates, ["GET"], "模板列表"),
            ("templates/<name>/preview", self.preview, ["GET"], "模板预览"),
            ("templates/default", self.set_default, ["POST"], "设为默认模板"),
            ("templates/install", self.install, ["POST"], "从 GitHub 安装模板"),
            ("templates/upload", self.upload, ["POST"], "上传 zip 安装模板"),
            ("templates/<name>/uninstall", self.uninstall, ["POST"], "卸载模板"),
        ]

    async def list_templates(self):
        return json_response(await self.service.list_templates())

    async def preview(self, name: str):
        try:
            html = await self.service.render_preview(name)
        except TemplateInstallError as e:
            return error_response(str(e))
        return json_response({"name": name, "html": html})

    async def set_default(self):
        payload = await request.json(default={})
        try:
            self.service.set_default(str(payload.get("name") or ""))
        except TemplateInstallError as e:
            return error_response(str(e))
        return json_response({"current": payload.get("name")})

    async def install(self):
        payload = await request.json(default={})
        try:
            result = await self.service.install_from_github(
                str(payload.get("url") or ""), str(payload.get("name") or "")
            )
        except TemplateInstallError as e:
            return error_response(str(e))
        except Exception as e:
            logger.error(f"从 GitHub 安装模板失败: {e}", exc_info=True)
            return error_response("安装失败，请查看插件日志")
        return json_response(result)

    async def upload(self):
        files = await request.files()
        upload = files.get("file")
        if not isinstance(upload, PluginUploadFile):
            return error_response("没有收到文件")
        data = await upload.read(MAX_ZIP_SIZE + 1)
        if len(data) > MAX_ZIP_SIZE:
            return error_response(f"压缩包超过 {MAX_ZIP_SIZE // 1024 // 1024} MB 上限")
        try:
            result = await self.service.install_from_zip(
                data,
                str(request.query.get("name", "") or ""),
                filename=upload.filename or "",
            )
        except TemplateInstallError as e:
            return error_response(str(e))
        except Exception as e:
            logger.error(f"上传安装模板失败: {e}", exc_info=True)
            return error_response("安装失败，请查看插件日志")
        return json_response(result)

    async def uninstall(self, name: str):
        try:
            result = await self.service.uninstall(name)
        except TemplateInstallError as e:
            return error_response(str(e))
        return json_response(result)
