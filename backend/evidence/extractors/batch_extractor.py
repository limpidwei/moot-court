"""
批量证据提取器 — ZIP / 文件夹

职责：
- 解压 ZIP 文件到临时目录
- 遍历文件夹中的所有文件
- 自动分发到对应解析器
- 生成 EvidenceRegistry
"""
from __future__ import annotations

import os
import zipfile
import tempfile
import shutil
import logging
from pathlib import Path
from typing import Callable

from .base import BaseExtractor
from ..schemas import EvidenceItem, EvidenceRegistry

logger = logging.getLogger(__name__)

# ZIP 文件后缀
_ZIP_EXTENSIONS = (".zip",)


class ZipExtractor(BaseExtractor):
    """ZIP 批量提取器 — 解压后逐文件处理"""

    @property
    def extractor_type(self) -> str:
        return "zip"

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(_ZIP_EXTENSIONS)

    async def extract(self, file_path: str, metadata: dict | None = None) -> EvidenceItem:
        """
        ZIP 文件不直接产出单个 EvidenceItem，而是产出聚合文本。
        实际使用中，建议在 intake 层直接调用 process_zip()。
        """
        from ..intake import process_file  # 局部导入避免循环依赖
        items = await process_zip(file_path, on_progress=None)
        combined = []
        for item in items:
            combined.append(f"--- {item.source_file} ---\n{item.content[:1000]}")
        return EvidenceItem(
            id="",
            source_file=os.path.basename(file_path),
            source_type="zip",
            content="\n\n".join(combined),
            summary=f"ZIP 压缩包，包含 {len(items)} 个文件",
            raw_metadata={
                **(metadata or {}),
                "file_count": len(items),
                "inner_files": [item.source_file for item in items],
            },
        )


async def process_zip(
    file_path: str,
    on_progress: Callable[[str, float], None] | None = None,
) -> list[EvidenceItem]:
    """
    处理 ZIP 文件，解压后遍历内部文件。

    Args:
        file_path: ZIP 文件路径
        on_progress: 进度回调

    Returns:
        成功解析的 EvidenceItem 列表
    """
    if not zipfile.is_zipfile(file_path):
        logger.error(f"不是有效的 ZIP 文件: {file_path}")
        return []

    temp_dir = tempfile.mkdtemp(prefix="evidence_zip_")
    items: list[EvidenceItem] = []

    try:
        # 解压
        if on_progress:
            on_progress("解压 ZIP", 0.1)
        with zipfile.ZipFile(file_path, "r") as zf:
            # Zip Slip 防护：逐个 entry 校验解压目标仍在 temp_dir 内
            temp_dir_real = os.path.realpath(temp_dir)
            for member in zf.namelist():
                target = os.path.realpath(os.path.join(temp_dir, member))
                if target != temp_dir_real and not target.startswith(temp_dir_real + os.sep):
                    logger.warning(f"[security] 拒绝越界 ZIP 条目: {member}")
                    continue
                zf.extract(member, temp_dir)

        # 遍历解压后的文件
        all_files = []
        for root, _dirs, files in os.walk(temp_dir):
            for fname in files:
                all_files.append(os.path.join(root, fname))

        total = len(all_files)
        if on_progress:
            on_progress(f"发现 {total} 个文件", 0.2)

        for idx, fpath in enumerate(all_files):
            from ..intake import process_file  # 局部导入避免循环依赖
            item = await process_file(fpath)
            if item:
                items.append(item)
            if on_progress and total > 0:
                progress = 0.2 + 0.8 * (idx + 1) / total
                on_progress(f"处理 {os.path.basename(fpath)}", progress)

    except Exception as e:
        logger.error(f"ZIP 处理失败: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return items


async def process_folder(
    folder_path: str,
    on_progress: Callable[[str, float], None] | None = None,
) -> list[EvidenceItem]:
    """
    处理文件夹中的所有文件。

    Args:
        folder_path: 文件夹路径
        on_progress: 进度回调

    Returns:
        成功解析的 EvidenceItem 列表
    """
    folder = Path(folder_path)
    if not folder.is_dir():
        logger.error(f"不是有效的文件夹: {folder_path}")
        return []

    all_files = [f for f in folder.rglob("*") if f.is_file()]
    total = len(all_files)
    items: list[EvidenceItem] = []

    if on_progress:
        on_progress(f"发现 {total} 个文件", 0.0)

    for idx, fpath in enumerate(all_files):
        from ..intake import process_file  # 局部导入避免循环依赖
        item = await process_file(str(fpath))
        if item:
            items.append(item)
        if on_progress and total > 0:
            on_progress(f"处理 {fpath.name}", (idx + 1) / total)

    return items
