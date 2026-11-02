"""
HTML模板模块
使用Jinja2加载外部HTML模板文件
"""

import asyncio
import base64
import mimetypes
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ...utils.logger import logger
from .template_catalog import TemplateCatalog

# 临时指定本次渲染使用的模板（WebUI 预览用），只影响当前协程，不会影响正在运行的分析任务
_template_override: ContextVar[str | None] = ContextVar(
    "report_template_override", default=None
)


@contextmanager
def use_template(template_name: str) -> Iterator[None]:
    """在 with 块内临时使用指定模板渲染，不修改配置"""
    token = _template_override.set(template_name)
    try:
        yield
    finally:
        _template_override.reset(token)


# 已内联过的插件图片：相对路径 → data URI（报告归档时据此去掉重复的装饰图）
INLINED_LOCAL_IMAGES: dict[str, str] = {}


@lru_cache(maxsize=64)
def local_image(relative_path: str) -> str:
    """将插件自带图片内联到 HTML，供本地截图、远程 T2I 和 HTML 报告共用。"""
    assets_dir = Path(__file__).resolve().parents[3] / "assets"
    image_path = (assets_dir / relative_path).resolve()
    image_path.relative_to(assets_dir)
    mime_type, _ = mimetypes.guess_type(image_path.name)
    if not mime_type or not mime_type.startswith("image/"):
        raise ValueError(f"不是图片资源: {relative_path}")
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    uri = f"data:{mime_type};base64,{encoded}"
    INLINED_LOCAL_IMAGES[relative_path] = uri
    return uri


class HTMLTemplates:
    """HTML模板管理类"""

    def __init__(self, config_manager, custom_dir: str | Path | None = None):
        """初始化Jinja2环境

        Args:
            config_manager: 配置管理器
            custom_dir: 自定义模板目录（WebUI 安装的模板），为空时只使用内置模板
        """
        self.config_manager = config_manager
        self.catalog = TemplateCatalog(custom_dir)
        # 内置模板根目录（保留给调试脚本使用）
        self.base_dir = str(self.catalog.builtin_dir)
        # 缓存不同模板的Jinja2环境（多线程安全）
        self._envs = {}
        self._env_lock = threading.Lock()

    def clear_cache(self) -> None:
        """清空模板环境缓存，安装或卸载自定义模板后调用，无需重启即可生效"""
        with self._env_lock:
            self._envs.clear()

    def _get_env_sync(self) -> Environment:
        """获取当前配置的模板环境（同步版本，供 asyncio.to_thread 调用）"""
        template_name = (
            _template_override.get() or self.config_manager.get_report_template()
        )

        # 如果环境已缓存且配置未变（使用锁保证多线程安全）
        with self._env_lock:
            env = self._envs.get(template_name)
            if env is not None:
                return env

        template_dir = self.catalog.resolve_dir(template_name)
        if template_dir is None:
            logger.warning(f"模板不存在: {template_name}，回退到 scrapbook")
            template_dir = self.catalog.builtin_dir / "scrapbook"

        env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        env.globals["local_image"] = local_image

        # 使用双重检查锁定，避免在高并发下重复创建相同 template_name 的 env
        with self._env_lock:
            existing = self._envs.get(template_name)
            if existing is not None:
                return existing
            self._envs[template_name] = env

        return env

    async def _get_env_async(self) -> Environment:
        """获取当前配置的模板环境（异步版本）"""
        return await asyncio.to_thread(self._get_env_sync)

    def _get_env(self) -> Environment:
        """获取当前配置的模板环境（同步版本，向后兼容）"""
        return self._get_env_sync()

    def _read_template_file_sync(self, filename: str) -> str:
        """同步读取模板文件内容"""
        with open(filename, encoding="utf-8") as f:
            return f.read()

    async def get_image_template_async(self) -> str:
        """获取图片报告的HTML模板（异步版本，返回原始模板字符串）"""
        try:
            env = await self._get_env_async()
            template = env.get_template("image_template.html")
            return await asyncio.to_thread(
                self._read_template_file_sync, template.filename
            )
        except Exception as e:
            logger.error(f"加载图片模板失败: {e}")
            return ""

    def get_image_template(self) -> str:
        """获取图片报告的HTML模板（同步版本，向后兼容）"""
        try:
            env = self._get_env()
            template = env.get_template("image_template.html")
            with open(template.filename, encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"加载图片模板失败: {e}")
            return ""

    def render_template(self, template_name: str, **kwargs) -> str:
        """渲染指定的模板文件

        Args:
            template_name: 模板文件名
            **kwargs: 传递给模板的变量

        Returns:
            渲染后的HTML字符串
        """
        try:
            env = self._get_env()
            template = env.get_template(template_name)
            return template.render(**kwargs)
        except Exception as e:
            logger.error(f"渲染模板 {template_name} 失败: {e}")
            return ""
