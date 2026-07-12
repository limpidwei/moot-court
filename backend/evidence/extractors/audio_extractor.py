"""
音频证据提取器 — 语音转文字

支持格式：.mp3, .wav, .m4a, .flac, .ogg, .wma

技术栈（按优先级）：
1. OpenAI Whisper API（需要环境变量 OPENAI_API_KEY）
2. faster-whisper 本地模型（需 pip install faster-whisper）
3. 兜底：返回友好提示，说明缺少依赖
"""
from __future__ import annotations

import os
import logging

from .base import BaseExtractor
from ..schemas import EvidenceItem

logger = logging.getLogger(__name__)

_AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".wma", ".aac")


class AudioExtractor(BaseExtractor):
    """音频语音转文字提取器"""

    @property
    def extractor_type(self) -> str:
        return "audio"

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(_AUDIO_EXTENSIONS)

    async def extract(self, file_path: str, metadata: dict | None = None) -> EvidenceItem:
        transcript = await self._transcribe(file_path)

        return EvidenceItem(
            id="",
            source_file=os.path.basename(file_path),
            source_type="audio",
            content=transcript,
            summary="",
            raw_metadata={
                **(metadata or {}),
                "transcript_method": self._detect_method(),
            },
        )

    def _detect_method(self) -> str:
        """检测当前可用的转写方法"""
        if os.getenv("OPENAI_API_KEY"):
            return "openai_whisper_api"
        try:
            import faster_whisper  # noqa: F401
            return "faster_whisper_local"
        except ImportError:
            return "none"

    async def _transcribe(self, file_path: str) -> str:
        """执行语音转文字，按优先级选择引擎"""
        # 1. 尝试 OpenAI Whisper API
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            try:
                return await self._transcribe_openai(file_path, api_key)
            except Exception as e:
                logger.warning(f"OpenAI Whisper API 失败: {e}，尝试本地模型")

        # 2. 尝试 faster-whisper 本地模型
        try:
            return await self._transcribe_local(file_path)
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"本地 Whisper 失败: {e}")

        # 3. 兜底
        return (
            "【音频转文字失败】\n"
            "系统未能将音频转换为文字。可能的原因：\n"
            "1. 未设置 OPENAI_API_KEY 环境变量（使用云端转写）\n"
            "2. 未安装 faster-whisper（使用本地转写，执行: pip install faster-whisper）\n"
            "\n建议：律师可手动上传该录音的文字稿，或安装上述依赖后重新上传。"
        )

    async def _transcribe_openai(self, file_path: str, api_key: str) -> str:
        """使用 OpenAI Whisper API"""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        with open(file_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="zh",
                response_format="text",
            )
        return str(transcript)

    async def _transcribe_local(self, file_path: str) -> str:
        """使用本地 faster-whisper 模型"""
        from faster_whisper import WhisperModel

        model_size = os.getenv("WHISPER_MODEL_SIZE", "base")
        device = os.getenv("WHISPER_DEVICE", "cpu")
        compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        segments, info = model.transcribe(file_path, language="zh", beam_size=5)

        parts = []
        for segment in segments:
            parts.append(f"[{segment.start:.2f}s - {segment.end:.2f}s] {segment.text}")

        return "\n".join(parts)
