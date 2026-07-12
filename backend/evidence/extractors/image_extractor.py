"""
图片证据提取器 — 本地 OCR

支持格式：.jpg, .jpeg, .png, .bmp, .tiff
技术栈：Pillow（图像预处理） + pytesseract（OCR）
"""
from __future__ import annotations

import os
import logging

from PIL import Image, ImageEnhance, ImageFilter

from .base import BaseExtractor
from ..schemas import EvidenceItem

logger = logging.getLogger(__name__)

# 支持的图片后缀
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp")


class ImageExtractor(BaseExtractor):
    """图片 OCR 提取器"""

    @property
    def extractor_type(self) -> str:
        return "image"

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(_IMAGE_EXTENSIONS)

    async def extract(self, file_path: str, metadata: dict | None = None) -> EvidenceItem:
        try:
            import pytesseract
        except ImportError:
            raise RuntimeError(
                "pytesseract 未安装，请执行: pip install pytesseract\n"
                "并确保 Tesseract OCR 已安装: https://github.com/UB-Mannheim/tesseract/wiki"
            )

        # 读取并预处理图片（P2 修复：Image.open → with 避免文件句柄泄漏）
        with Image.open(file_path) as image:
            img_size = image.size
            img_mode = image.mode
            preprocessed = _preprocess_image(image)

        # OCR：优先中文
        try:
            text = pytesseract.image_to_string(preprocessed, lang="chi_sim+eng")
        except pytesseract.TesseractError:
            # 如果中文语言包未安装，退回到英文
            logger.warning("Tesseract 中文语言包未找到，退回到英文识别")
            text = pytesseract.image_to_string(preprocessed, lang="eng")

        # 清理 OCR 结果
        text = _clean_ocr_text(text)

        return EvidenceItem(
            id="",
            source_file=os.path.basename(file_path),
            source_type="image",
            content=text,
            summary="",
            raw_metadata={
                **(metadata or {}),
                "image_size": img_size,
                "image_mode": img_mode,
                "ocr_engine": "tesseract",
            },
        )


def _preprocess_image(image: Image.Image) -> Image.Image:
    """
    图像预处理以提升 OCR 准确率

    步骤：
    1. 转灰度
    2. 适度对比度增强
    3. 锐化
    4. 二值化（自适应阈值）
    """
    # 转灰度
    if image.mode != "L":
        image = image.convert("L")

    # 对比度增强
    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(2.0)

    # 锐化
    image = image.filter(ImageFilter.SHARPEN)

    # 二值化（简单阈值，适合文档）
    threshold = 128
    image = image.point(lambda x: 0 if x < threshold else 255, "1")
    # 转回 L 模式以便 tesseract 处理
    image = image.convert("L")

    return image


def _clean_ocr_text(text: str) -> str:
    """清理 OCR 输出的常见噪音"""
    # 移除多余的空行
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # 合并过短的行（可能是同一行被错误断开了）
    merged = []
    for line in lines:
        if merged and len(line) < 10 and not line.endswith(("。", "！", "？", ":", "；", ",")):
            merged[-1] += line
        else:
            merged.append(line)
    return "\n".join(merged)
