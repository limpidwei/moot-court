"""
多模态证据解析器插件包

每个解析器继承 BaseExtractor，注册后可处理特定文件类型。
"""
from .base import BaseExtractor
from .text_extractor import TextExtractor, DocxExtractor, PdfExtractor
from .image_extractor import ImageExtractor
from .audio_extractor import AudioExtractor
from .contract_extractor import ContractExtractor
from .batch_extractor import ZipExtractor

# 全局提取器列表（按优先级排序）
# 注意：contract 放在 text/docx/pdf 之后，作为 "二次增强" 不直接竞争文件
ALL_EXTRACTORS: list[BaseExtractor] = [
    TextExtractor(),
    DocxExtractor(),
    PdfExtractor(),
    ImageExtractor(),
    AudioExtractor(),
    ZipExtractor(),
]
