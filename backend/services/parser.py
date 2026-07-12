"""
智能案卷解析服务（异步版本）

支持：
- 粘贴长文本 AI 自动解析
- 上传 .txt / .docx / .pdf 文件
"""

import io
import json
from ..llm import llm_call
from ..orchestration.prompts import PARSER_SYSTEM


async def parse_text(text: str) -> dict:
    """
    用 AI 从大段文本中提取结构化案卷信息。

    返回：
    {
        "case_title": "...",
        "plaintiff": "...",
        "defendant": "...",
        "facts": "...",
        "evidence_list": [{"name": "...", "type": "...", "description": "..."}],
        "claims": ["...", "..."]
    }
    """
    prompt = f"请解析以下法律文本，提取案卷结构化信息：\n\n{text}"
    result = await llm_call(PARSER_SYSTEM, prompt, temperature=0.2)

    # 清理可能的 Markdown 包裹
    result = result.strip()
    if result.startswith("```"):
        lines = result.split("\n")
        result = "\n".join(lines[1:-1])

    try:
        data = json.loads(result)
        data["raw_text"] = text
        return data
    except json.JSONDecodeError:
        # 尝试提取 JSON 片段
        import re
        m = re.search(r"\{[\s\S]*\}", result)
        if m:
            data = json.loads(m.group())
            data["raw_text"] = text
            return data
        return {"error": "解析失败", "raw": result, "raw_text": text}


def _decode_bytes(content: bytes) -> str:
    """以多编码策略解码文本字节。

    H3 修复：原先硬编码 utf-8，国内常见的 GBK/GB18030 txt 会大面积产生 � 喂给 LLM，
    进而导致整段输出乱码。改为：先 charset-normalizer 检测，失败再依次尝试
    UTF-8 / GB18030 / GBK / Big5，全部失败才以 UTF-8 + replace 兜底。
    """
    if not content:
        return ""
    # 1. charset-normalizer 检测（准确率最高，已装 3.4.x）
    try:
        from charset_normalizer import from_bytes
        result = from_bytes(content).best()
        if result is not None:
            decoded = str(result)
            # 排除误判为纯 ASCII 时丢中文的情况：若含高位字节却解码出零中文，
            # 不在此处过度防御，交给下面的回退链处理。
            if decoded and _has_text_signal(decoded):
                return decoded
    except Exception:
        pass

    # 2. 显式编码回退链
    for encoding in ("utf-8", "gb18030", "gbk", "big5", "utf-16"):
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue

    # 3. 最终兜底
    return content.decode("utf-8", errors="replace")


def _has_text_signal(text: str) -> bool:
    """判断解码结果是否有可读信号：非空且替换符占比不高。"""
    if not text:
        return False
    if "�" not in text:
        return True
    # 替换符占比 > 5% 视为解码失败
    replace_count = text.count("�")
    return replace_count / max(len(text), 1) <= 0.05


def extract_text_from_txt(content: bytes) -> str:
    """从 .txt 文件提取文本"""
    return _decode_bytes(content)


def extract_text_from_docx(content: bytes) -> str:
    """从 .docx 文件提取文本"""
    try:
        from docx import Document
        doc = Document(io.BytesIO(content))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except ImportError:
        return "[错误] 需要安装 python-docx: pip install python-docx"
    except Exception as e:
        return f"[错误] 无法解析 docx: {e}"


def extract_text_from_pdf(content: bytes) -> str:
    """从 .pdf 文件提取文本"""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)
    except ImportError:
        return "[错误] 需要安装 PyPDF2: pip install PyPDF2"
    except Exception as e:
        return f"[错误] 无法解析 PDF: {e}"


def extract_text_from_file(filename: str, content: bytes) -> str:
    """根据文件扩展名选择提取方法"""
    ext = filename.lower().split(".")[-1] if "." in filename else ""
    if ext == "txt":
        return extract_text_from_txt(content)
    elif ext == "docx":
        return extract_text_from_docx(content)
    elif ext == "pdf":
        return extract_text_from_pdf(content)
    else:
        return f"[错误] 不支持的文件格式: .{ext}"


async def parse_file(filename: str, content: bytes) -> dict:
    """上传文件 → 提取文本 → AI 解析 → 结构化数据"""
    text = extract_text_from_file(filename, content)
    if text.startswith("[错误]"):
        return {"error": text}
    return await parse_text(text)
