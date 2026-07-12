"""
文本证据提取器

支持格式：.txt, .docx, .pdf
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .base import BaseExtractor
from ..schemas import EvidenceItem


class TextExtractor(BaseExtractor):
    """纯文本提取器 (.txt)"""

    @property
    def extractor_type(self) -> str:
        return "text"

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(".txt")

    async def extract(self, file_path: str, metadata: dict | None = None) -> EvidenceItem:
        # 自动检测编码
        content = _read_text_with_encoding(file_path)
        return EvidenceItem(
            id="",
            source_file=os.path.basename(file_path),
            source_type="text",
            content=content,
            summary="",
            raw_metadata=metadata or {},
        )


class DocxExtractor(BaseExtractor):
    """Word 文档提取器 (.docx)"""

    @property
    def extractor_type(self) -> str:
        return "docx"

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(".docx")

    async def extract(self, file_path: str, metadata: dict | None = None) -> EvidenceItem:
        try:
            import docx
        except ImportError:
            raise RuntimeError("python-docx 未安装，请执行: pip install python-docx")

        doc = docx.Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        content = "\n".join(paragraphs)

        return EvidenceItem(
            id="",
            source_file=os.path.basename(file_path),
            source_type="docx",
            content=content,
            summary="",
            raw_metadata=metadata or {},
        )


class PdfExtractor(BaseExtractor):
    """PDF 文本提取器 (.pdf)

    使用 pymupdf (fitz) 提取文本和元数据。
    如果是扫描件（无文本层），会返回空内容，由调用方决定是否转图片 OCR。
    """

    @property
    def extractor_type(self) -> str:
        return "pdf"

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(".pdf")

    async def extract(self, file_path: str, metadata: dict | None = None) -> EvidenceItem:
        try:
            import fitz  # pymupdf
        except ImportError:
            raise RuntimeError("pymupdf 未安装，请执行: pip install pymupdf")

        doc = fitz.open(file_path)
        try:
            page_count = len(doc)
            pages_text = []
            for page in doc:
                text = page.get_text()
                if text.strip():
                    pages_text.append(text)
        finally:
            doc.close()

        content = "\n".join(pages_text)

        # 检测是否可能是扫描件（无文本层）
        is_scanned = len(content.strip()) < 50 and page_count > 0

        return EvidenceItem(
            id="",
            source_file=os.path.basename(file_path),
            source_type="pdf",
            content=content,
            summary="",
            raw_metadata={
                **(metadata or {}),
                "page_count": page_count,
                "is_scanned": is_scanned,
            },
        )


# ============================================================
# 工具函数
# ============================================================

def _read_text_with_encoding(file_path: str) -> str:
    """读取文本文件，自动尝试常见编码。

    P3 修复：latin-1 不抛 UnicodeDecodeError 但对中文返乱码且不报错（调用方无从得知数据已损坏）。
    改为仅在全部常用中文编码失败后才用 latin-1 兜底，并记 warning。同时加入 charset-normalizer
    作为首选检测器。
    """
    # 1. charset-normalizer 检测
    try:
        from charset_normalizer import from_bytes
        with open(file_path, "rb") as fh:
            raw = fh.read()
        result = from_bytes(raw).best()
        if result is not None:
            text = str(result)
            if text and "�" not in text:
                return text
    except Exception:
        pass

    # 2. 显式编码回退链
    encodings = ["utf-8", "gb18030", "gbk", "gb2312", "utf-16"]
    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue

    # 3. latin-1 兜底（永不抛错，但中文会变成乱码——记 warning 供调用方排查）
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"文件 {file_path} 所有编码尝试失败，回退 latin-1（中文可能乱码）")
    with open(file_path, "r", encoding="latin-1") as f:
        return f.read()
