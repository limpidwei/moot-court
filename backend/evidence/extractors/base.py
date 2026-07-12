"""
证据解析器抽象基类

所有多模态解析器（文本/图片OCR/语音转文字/合同结构化）
都继承此基类，实现统一接口。
"""
from abc import ABC, abstractmethod
from ..schemas import EvidenceItem


class BaseExtractor(ABC):
    """所有证据解析器的抽象基类"""

    @abstractmethod
    async def extract(self, file_path: str, metadata: dict | None = None) -> EvidenceItem:
        """
        从文件中提取结构化证据。

        Args:
            file_path: 文件路径
            metadata: 可选的额外元数据（如上传时间、上传者等）

        Returns:
            EvidenceItem: 统一格式的证据项
        """
        ...

    @abstractmethod
    def can_handle(self, file_path: str) -> bool:
        """
        判断是否能处理该文件类型。

        Args:
            file_path: 文件路径

        Returns:
            True 如果此解析器可以处理该文件
        """
        ...

    @property
    @abstractmethod
    def extractor_type(self) -> str:
        """解析器类型标识，如 'text', 'image', 'audio', 'contract'"""
        ...
