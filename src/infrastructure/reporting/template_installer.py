"""
自定义报告模板的安装与卸载（参考上游 template_installer.py）

来源：
- GitHub 仓库链接：下载源码 zip 后安装
- WebUI 上传的 zip 文件

安全约束：
- zip 成员路径不能跳出目标目录，不能是绝对路径或符号链接
- 限制成员数量、单文件大小、解压总大小
- 模板名不能带路径分隔符，不能和内置模板或已安装模板重名
- 必须包含 image_template.html；template.json 可选
- 安装时写入 .tpl_installed.json 标记，只有带标记的模板才能卸载
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import aiohttp

from ...utils.logger import logger
from .template_catalog import (
    INSTALL_MARKER_FILE,
    REQUIRED_TEMPLATE_FILE,
    TemplateCatalog,
)

MAX_ZIP_SIZE = 20 * 1024 * 1024  # 上传或下载的 zip 上限
MAX_EXTRACTED_SIZE = 40 * 1024 * 1024  # 解压后总大小上限
MAX_SINGLE_FILE_SIZE = 15 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 300
MAX_TEMPLATE_NAME_LEN = 50

# 报告各板块用到的子模板，缺少时对应板块会空白（安装时提示用户）
OPTIONAL_PARTIALS = (
    "topic_item.html",
    "user_title_item.html",
    "quote_item.html",
    "activity_chart.html",
    "chat_quality_item.html",
)

_INVALID_NAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_GITHUB_HOSTS = {"github.com", "www.github.com"}
_GITHUB_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")


class TemplateInstallError(Exception):
    """模板安装或卸载失败，消息可以直接展示给用户"""


class TemplateInstaller:
    """自定义模板安装器，模板装到 catalog.custom_dir 下"""

    def __init__(self, catalog: TemplateCatalog):
        if catalog.custom_dir is None:
            raise ValueError("未配置自定义模板目录")
        self.catalog = catalog
        self.store_dir: Path = catalog.custom_dir

    # ------------------------------------------------------------------
    # 安装
    # ------------------------------------------------------------------

    def install_from_zip(
        self,
        zip_data: bytes,
        name: str | None = None,
        source: str = "upload",
        source_url: str = "",
        fallback_name: str = "",
    ) -> dict:
        """从 zip 内容安装模板（同步，调用方用 asyncio.to_thread 执行）

        Args:
            name: 用户指定的模板名，优先使用
            fallback_name: 压缩包文件平铺在顶层时使用的名字（例如上传的文件名）
        """
        if not zip_data:
            raise TemplateInstallError("压缩包内容为空")
        if len(zip_data) > MAX_ZIP_SIZE:
            raise TemplateInstallError(
                f"压缩包超过 {MAX_ZIP_SIZE // 1024 // 1024} MB 上限"
            )
        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_data))
        except zipfile.BadZipFile as e:
            raise TemplateInstallError("压缩包格式无效，请上传 zip 文件") from e

        with zf:
            members = _validate_members(zf)
            root = _locate_template_root(members)
            template_name = self._resolve_name(name, root, fallback_name)
            self.store_dir.mkdir(parents=True, exist_ok=True)

            with tempfile.TemporaryDirectory(
                prefix=".tpl_install_", dir=self.store_dir
            ) as tmp:
                staging = Path(tmp) / template_name
                staging.mkdir()
                written = _extract_root(zf, members, root, staging)
                if not (staging / REQUIRED_TEMPLATE_FILE).is_file():
                    raise TemplateInstallError(
                        f"模板根目录缺少 {REQUIRED_TEMPLATE_FILE}"
                    )
                missing = [f for f in OPTIONAL_PARTIALS if not (staging / f).is_file()]
                (staging / INSTALL_MARKER_FILE).write_text(
                    json.dumps(
                        {
                            "source": source,
                            "source_url": source_url,
                            "installed_at": datetime.now().strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                # 临时目录建在模板目录内，同一磁盘上直接改名，安装要么完整成功要么不留痕迹
                staging.rename(self.store_dir / template_name)

        logger.info(f"自定义模板安装成功: {template_name}（{len(written)} 个文件）")
        if missing:
            logger.warning(
                f"自定义模板 {template_name} 缺少子模板 {', '.join(missing)}，对应板块会空白"
            )
        return {"name": template_name, "files": len(written), "missing": missing}

    async def install_from_github(self, repo_url: str, name: str | None = None) -> dict:
        """从 GitHub 仓库链接安装模板"""
        owner, repo, branch = parse_github_repo_url(repo_url)
        zip_data = await download_github_archive(owner, repo, branch)
        return await asyncio.to_thread(
            self.install_from_zip,
            zip_data,
            name or None,
            "github",
            repo_url.strip(),
        )

    def _resolve_name(self, name: str | None, root: str, fallback: str = "") -> str:
        """模板名：优先用户指定，否则用压缩包根目录名（去掉 GitHub 的 -main/-master 后缀）"""
        candidate = (name or "").strip()
        if not candidate and root:
            candidate = root.rsplit("/", 1)[-1]
            for suffix in ("-main", "-master"):
                if candidate.endswith(suffix) and len(candidate) > len(suffix):
                    candidate = candidate[: -len(suffix)]
                    break
        if not candidate:
            candidate = fallback.strip()
        if not candidate:
            raise TemplateInstallError("无法从压缩包推断模板名，请手动填写模板名")
        template_name = validate_template_name(candidate)
        if self.catalog.is_builtin(template_name):
            raise TemplateInstallError(
                f"模板名 '{template_name}' 与内置模板重名，请换个名字"
            )
        if (self.store_dir / template_name).exists():
            raise TemplateInstallError(
                f"模板 '{template_name}' 已安装，如需更新请先卸载"
            )
        return template_name

    # ------------------------------------------------------------------
    # 卸载
    # ------------------------------------------------------------------

    def uninstall(self, name: str) -> None:
        """卸载带安装标记的自定义模板"""
        template_name = validate_template_name(name)
        if self.catalog.is_builtin(template_name):
            raise TemplateInstallError(f"'{template_name}' 是内置模板，不能卸载")
        target = self.store_dir / template_name
        # 拒绝符号链接：rmtree 跟随链接可能删到别处
        if target.is_symlink() or not target.is_dir():
            raise TemplateInstallError(f"模板 '{template_name}' 不存在")
        if not (target / INSTALL_MARKER_FILE).is_file():
            raise TemplateInstallError(
                f"模板 '{template_name}' 不是通过插件页面安装的，请手动删除"
            )
        shutil.rmtree(target)
        logger.info(f"自定义模板已卸载: {template_name}")


# ----------------------------------------------------------------------
# 校验与解压
# ----------------------------------------------------------------------


def validate_template_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise TemplateInstallError("模板名不能为空")
    if cleaned in {".", ".."} or cleaned.startswith(".") or cleaned.endswith("."):
        raise TemplateInstallError("模板名不能以点开头或结尾")
    if len(cleaned) > MAX_TEMPLATE_NAME_LEN:
        raise TemplateInstallError(f"模板名不能超过 {MAX_TEMPLATE_NAME_LEN} 个字符")
    if _INVALID_NAME_CHARS.search(cleaned):
        raise TemplateInstallError('模板名不能包含 \\ / : * ? " < > | 等字符')
    return cleaned


def _validate_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """防路径穿越、符号链接和压缩炸弹"""
    members = zf.infolist()
    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise TemplateInstallError(f"压缩包文件数超过 {MAX_ARCHIVE_MEMBERS} 个")
    total = 0
    for m in members:
        norm = m.filename.replace("\\", "/")
        if any(ord(ch) < 32 for ch in m.filename):
            raise TemplateInstallError("压缩包包含非法文件名")
        if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm):
            raise TemplateInstallError(f"压缩包包含绝对路径: {m.filename}")
        if any(part in {".", ".."} for part in norm.split("/")):
            raise TemplateInstallError(f"压缩包包含非法路径: {m.filename}")
        if stat.S_ISLNK(m.external_attr >> 16):
            raise TemplateInstallError(f"压缩包包含符号链接: {m.filename}")
        if m.file_size > MAX_SINGLE_FILE_SIZE:
            raise TemplateInstallError(f"压缩包内文件过大: {m.filename}")
        total += m.file_size
        if total > MAX_EXTRACTED_SIZE:
            raise TemplateInstallError("压缩包解压后总大小超出限制")
    return members


def _locate_template_root(members: list[zipfile.ZipInfo]) -> str:
    """定位最浅的、包含 image_template.html 的目录（'' 表示压缩包顶层）"""
    dirs: dict[str, int] = {}
    for m in members:
        if m.is_dir():
            continue
        norm = m.filename.replace("\\", "/")
        directory, _, filename = norm.rpartition("/")
        if filename == REQUIRED_TEMPLATE_FILE:
            dirs[directory] = directory.count("/") + 1 if directory else 0
    if not dirs:
        raise TemplateInstallError(f"压缩包中没有找到 {REQUIRED_TEMPLATE_FILE}")
    min_depth = min(dirs.values())
    shallowest = [d for d, depth in dirs.items() if depth == min_depth]
    if len(shallowest) > 1:
        raise TemplateInstallError("压缩包里有多个模板，请每个模板单独打包安装")
    return shallowest[0]


def _extract_root(
    zf: zipfile.ZipFile, members: list[zipfile.ZipInfo], root: str, dest_dir: Path
) -> list[str]:
    """只解压模板根目录下的文件，返回写入的相对路径"""
    prefix = f"{root}/" if root else ""
    base = dest_dir.resolve()
    written = []
    for m in members:
        if m.is_dir():
            continue
        norm = m.filename.replace("\\", "/")
        if prefix and not norm.startswith(prefix):
            continue  # 模板根目录以外的文件（README 等）不需要
        rel = norm[len(prefix) :]
        if not rel or rel == INSTALL_MARKER_FILE:
            continue
        dest = (dest_dir / rel).resolve()
        if not dest.is_relative_to(base):
            raise TemplateInstallError(f"非法解压路径: {m.filename}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zf.open(m) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out, length=1024 * 1024)
        except (RuntimeError, NotImplementedError) as e:
            raise TemplateInstallError("压缩包无法解压（可能已加密）") from e
        written.append(rel)
    return written


# ----------------------------------------------------------------------
# GitHub 下载
# ----------------------------------------------------------------------


def parse_github_repo_url(repo_url: str) -> tuple[str, str, str]:
    """解析 https://github.com/<owner>/<repo>[/tree/<branch>]，返回 (owner, repo, branch)"""
    parsed = urlparse((repo_url or "").strip())
    if parsed.scheme != "https" or parsed.hostname not in _GITHUB_HOSTS:
        raise TemplateInstallError("只支持 https://github.com/ 开头的仓库链接")
    parts = [unquote(p) for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        raise TemplateInstallError("GitHub 链接格式不正确")
    owner, repo = parts[0], parts[1].removesuffix(".git")
    branch = ""
    if len(parts) >= 4 and parts[2] == "tree":
        branch = "/".join(parts[3:])
    elif len(parts) != 2:
        raise TemplateInstallError("只支持仓库主页或 /tree/<分支> 形式的链接")
    segments = [owner, repo] + (branch.split("/") if branch else [])
    for seg in segments:
        if seg in {".", ".."} or not _GITHUB_SEGMENT.match(seg):
            raise TemplateInstallError("GitHub 链接包含非法字符")
    return owner, repo, branch


async def download_github_archive(owner: str, repo: str, branch: str = "") -> bytes:
    """下载仓库源码 zip；未指定分支时先查默认分支，查不到再依次尝试 main、master"""
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(trust_env=True, timeout=timeout) as session:
        if not branch:
            branch = await _get_default_branch(session, owner, repo)
        candidates = [branch] if branch else ["main", "master"]
        last_error = ""
        for candidate in candidates:
            url = (
                f"https://github.com/{owner}/{repo}/archive/refs/heads/{candidate}.zip"
            )
            logger.info(f"下载模板压缩包: {url}")
            try:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        last_error = f"下载失败（HTTP {resp.status}）"
                        continue
                    body = bytearray()
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        body.extend(chunk)
                        if len(body) > MAX_ZIP_SIZE:
                            raise TemplateInstallError(
                                f"仓库压缩包超过 {MAX_ZIP_SIZE // 1024 // 1024} MB 上限"
                            )
                    return bytes(body)
            except TemplateInstallError:
                raise
            except Exception as e:
                last_error = f"下载出错: {e}"
    raise TemplateInstallError(last_error or "无法下载仓库压缩包")


async def _get_default_branch(
    session: aiohttp.ClientSession, owner: str, repo: str
) -> str:
    try:
        async with session.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return str(data.get("default_branch") or "").strip()
    except Exception as e:
        logger.debug(f"获取 {owner}/{repo} 默认分支失败: {e}")
    return ""
