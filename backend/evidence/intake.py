"""
证据摄入接口（预留骨架）

未来实现：
- 文件上传（单个文件 / zip 压缩包）
- 文件夹遍历
- 自动分发到对应解析器
- 批量处理 + 进度回调
"""
from __future__ import annotations

import logging
from typing import Callable

from .schemas import EvidenceItem, EvidenceRegistry
from .extractors.base import BaseExtractor
from .extractors import ALL_EXTRACTORS

logger = logging.getLogger(__name__)

# 解析器注册表
_registered_extractors: list[BaseExtractor] = []


def register_extractor(extractor: BaseExtractor) -> None:
    """注册一个新的证据解析器"""
    _registered_extractors.append(extractor)
    logger.info(f"注册解析器: {extractor.extractor_type}")


# 自动注册所有内置提取器
for _ext in ALL_EXTRACTORS:
    register_extractor(_ext)


def get_extractor_for_file(file_path: str) -> BaseExtractor | None:
    """根据文件类型查找合适的解析器"""
    for extractor in _registered_extractors:
        if extractor.can_handle(file_path):
            return extractor
    return None


async def process_file(
    file_path: str,
    metadata: dict | None = None,
    on_progress: Callable[[str, float], None] | None = None,
) -> EvidenceItem | None:
    """
    处理单个文件，返回结构化证据。

    Args:
        file_path: 文件路径
        metadata: 额外元数据
        on_progress: 进度回调 (stage, percent)

    Returns:
        EvidenceItem 或 None（无匹配解析器时）
    """
    extractor = get_extractor_for_file(file_path)
    if not extractor:
        logger.warning(f"无解析器可处理: {file_path}")
        return None

    if on_progress:
        on_progress(f"正在解析: {file_path}", 0.0)

    try:
        item = await extractor.extract(file_path, metadata or {})
        if on_progress:
            on_progress(f"解析完成: {file_path}", 1.0)
        return item
    except Exception as e:
        logger.error(f"解析失败 {file_path}: {e}")
        if on_progress:
            on_progress(f"解析失败: {file_path}", -1.0)
        return None


async def process_folder(
    folder_path: str,
    case_id: str,
    on_progress: Callable[[str, float], None] | None = None,
) -> EvidenceRegistry:
    """
    批量处理文件夹中的所有文件。

    Args:
        folder_path: 文件夹路径
        case_id: 案件 ID
        on_progress: 进度回调

    Returns:
        EvidenceRegistry 包含所有成功解析的证据
    """
    from .extractors.batch_extractor import process_folder as _batch_process_folder
    items = await _batch_process_folder(folder_path, on_progress)

    registry = EvidenceRegistry(case_id=case_id)
    for item in items:
        registry.items.append(item)
    return registry
