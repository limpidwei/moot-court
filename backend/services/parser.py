"""
智能案卷解析服务

支持：
- 粘贴长文本 AI 自动解析
- 上传 .txt / .docx / .pdf 文件
"""

import io
import json
from ..llm import llm_call
from ..orchestration.prompts import PARSER_SYSTEM


def parse_text(text: str) -> dict:
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
    result = llm_call(PARSER_SYSTEM, prompt, temperature=0.2)

    # 清理可能的 Markdown 包裹
    result = result.strip()
    if result.startswith("```"):
        lines = result.split("\n")
        result = "\n".join(lines[1:-1])

    try:
        return json.loads(result)
    except json.JSONDecodeError:
        # 尝试提取 JSON 片段
        import re
        m = re.search(r"\{[\s\S]*\}", result)
        if m:
            return json.loads(m.group())
        return {"error": "解析失败", "raw": result}


def extract_text_from_txt(content: bytes) -> str:
    """从 .txt 文件提取文本"""
    return content.decode("utf-8", errors="replace")


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


def parse_file(filename: str, content: bytes) -> dict:
    """上传文件 → 提取文本 → AI 解析 → 结构化数据"""
    text = extract_text_from_file(filename, content)
    if text.startswith("[错误]"):
        return {"error": text}
    return parse_text(text)
