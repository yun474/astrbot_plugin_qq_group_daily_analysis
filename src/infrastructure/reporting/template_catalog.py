"""
报告模板目录

统一管理「内置模板 + 自定义模板」的查找与列表：
- 内置模板：插件自带的 templates/ 目录
- 自定义模板：插件数据目录下的 custom_templates/，由 WebUI 安装
同名时内置模板优先，自定义模板不能覆盖内置模板。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ...utils.logger import logger

BUILTIN_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
REQUIRED_TEMPLATE_FILE = "image_template.html"
TEMPLATE_META_FILE = "template.json"
INSTALL_MARKER_FILE = ".tpl_installed.json"


@dataclass
class TemplateInfo:
    """模板展示信息"""

    name: str
    builtin: bool
    display_name: str = ""
    desc: str = ""
    tag: str = ""
    tag_color: str = ""
    # 仅自定义模板：安装标记内容，没有标记的目录不能通过 WebUI 卸载
    install_info: dict = field(default_factory=dict)

    @property
    def removable(self) -> bool:
        return not self.builtin and bool(self.install_info)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["removable"] = self.removable
        return data


class TemplateCatalog:
    """模板目录查询"""

    def __init__(self, custom_dir: str | os.PathLike | None = None):
        self.builtin_dir = BUILTIN_TEMPLATE_DIR
        self.custom_dir = Path(custom_dir) if custom_dir else None

    def is_builtin(self, name: str) -> bool:
        return self._is_template_dir(self.builtin_dir / name)

    def resolve_dir(self, name: str) -> Path | None:
        """返回模板所在目录，内置优先；找不到返回 None"""
        if not name or not is_safe_template_name(name):
            return None
        builtin = self.builtin_dir / name
        if self._is_template_dir(builtin):
            return builtin
        if self.custom_dir:
            custom = self.custom_dir / name
            if self._is_template_dir(custom):
                return custom
        return None

    def exists(self, name: str) -> bool:
        return self.resolve_dir(name) is not None

    def list_names(self) -> list[str]:
        """全部可用模板名：内置在前，自定义在后，各自按名称排序"""
        builtin = self._scan(self.builtin_dir)
        custom = [n for n in self._scan(self.custom_dir) if n not in builtin]
        return builtin + custom

    def list_templates(self) -> list[TemplateInfo]:
        return [self.get_info(name) for name in self.list_names()]

    def get_info(self, name: str) -> TemplateInfo:
        template_dir = self.resolve_dir(name)
        builtin = template_dir is not None and template_dir.parent == self.builtin_dir
        info = TemplateInfo(name=name, builtin=builtin, display_name=name)
        if template_dir is None:
            return info

        meta = _read_json(template_dir / TEMPLATE_META_FILE)
        info.display_name = str(meta.get("name") or name)
        info.desc = str(meta.get("desc") or "")
        info.tag = str(meta.get("tag") or "")
        info.tag_color = str(meta.get("tag_color") or "")
        if not builtin:
            info.install_info = _read_json(template_dir / INSTALL_MARKER_FILE)
        return info

    def _scan(self, base: Path | None) -> list[str]:
        if not base or not base.is_dir():
            return []
        return sorted(
            p.name
            for p in base.iterdir()
            if not p.name.startswith(("__", ".")) and self._is_template_dir(p)
        )

    @staticmethod
    def _is_template_dir(path: Path) -> bool:
        return (path / REQUIRED_TEMPLATE_FILE).is_file()


def is_safe_template_name(name: str) -> bool:
    """模板名只能是单层目录名，不能包含路径分隔符或以点开头"""
    return (
        bool(name)
        and name == os.path.basename(name)
        and "/" not in name
        and "\\" not in name
        and not name.startswith(".")
        and name not in {".", ".."}
    )


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"读取模板信息失败 {path}: {e}")
        return {}
