"""
合同结构化提取器

支持格式：.txt, .docx, .pdf（任意包含合同文本的文件）

职责：
- 识别文件是否为合同
- 用 LLM 提取合同关键条款
- 输出结构化数据（当事人、标的、金额、期限、违约责任等）

注意：can_handle 在注册顺序中应放在 TextExtractor/DocxExtractor/PdfExtractor 之后，
      作为 "二次增强" 提取器。但当前架构中，我们先在 intake 层识别合同并路由。
"""
from __future__ import annotations

import os
import logging
import json
import re

from backend.llm import llm_call
from .base import BaseExtractor
from ..schemas import EvidenceItem

logger = logging.getLogger(__name__)

_CONTRACT_EXTENSIONS = (".txt", ".docx", ".pdf")

_CONTRACT_EXTRACTION_PROMPT = """你是一位合同审查专家。请分析以下合同文本，提取关键结构化信息。

要求提取以下字段（纯 JSON 输出）：
{
  "is_contract": true/false,           // 判断是否为合同文本
  "contract_type": "",                 // 合同类型：借款合同、买卖合同、租赁合同、劳动合同、服务合同等
  "parties": {
    "party_a": {"name": "", "role": ""},
    "party_b": {"name": "", "role": ""}
  },
  "subject": "",                       // 合同标的/交易内容
  "amount": {"value": "", "currency": "CNY"},  // 金额
  "term": {"start_date": "", "end_date": "", "duration": ""},  // 合同期限
  "payment_terms": "",                 // 付款条款
  "key_obligations": [""],             // 各方主要义务
  "breach_clause": "",                 // 违约责任条款摘要
  "termination_clause": "",            // 解除/终止条款摘要
  "dispute_resolution": "",            // 争议解决方式
  "other_key_terms": [""]              // 其他关键条款
}

如果文本明显不是合同（如普通聊天记录、收据），is_contract 设为 false，其他字段留空字符串。

合同文本：
"""


class ContractExtractor(BaseExtractor):
    """合同结构化提取器（基于 LLM）"""

    @property
    def extractor_type(self) -> str:
        return "contract"

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(_CONTRACT_EXTENSIONS)

    async def extract(self, file_path: str, metadata: dict | None = None) -> EvidenceItem:
        # 先读取原始文本内容
        raw_text = await self._read_raw_text(file_path)
        if not raw_text:
            return EvidenceItem(
                id="",
                source_file=os.path.basename(file_path),
                source_type="contract",
                content="",
                summary="无法读取合同文本",
                raw_metadata={"error": "empty_content"},
            )

        # LLM 结构化提取
        structured = await self._extract_with_llm(raw_text)

        # 生成摘要
        summary = self._build_summary(structured)

        # 提取当事人列表
        parties = []
        pa = structured.get("parties", {})
        if pa.get("party_a", {}).get("name"):
            parties.append(pa["party_a"]["name"])
        if pa.get("party_b", {}).get("name"):
            parties.append(pa["party_b"]["name"])

        # 提取日期
        term = structured.get("term", {})
        date = term.get("start_date", "")

        return EvidenceItem(
            id="",
            source_file=os.path.basename(file_path),
            source_type="contract",
            content=raw_text,
            summary=summary,
            date=date,
            parties=parties,
            relevance=["合同成立", "违约事实"] if structured.get("is_contract") else [],
            raw_metadata={
                **(metadata or {}),
                "structured": structured,
                "is_contract": structured.get("is_contract", False),
            },
        )

    async def _read_raw_text(self, file_path: str) -> str:
        """读取文件原始文本"""
        if file_path.lower().endswith(".txt"):
            encodings = ["utf-8", "gbk", "gb2312", "latin-1"]
            for enc in encodings:
                try:
                    with open(file_path, "r", encoding=enc) as f:
                        return f.read()
                except UnicodeDecodeError:
                    continue
            return ""

        if file_path.lower().endswith(".docx"):
            try:
                import docx
                doc = docx.Document(file_path)
                return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            except Exception as e:
                logger.warning(f"docx 读取失败: {e}")
                return ""

        if file_path.lower().endswith(".pdf"):
            try:
                import fitz
                doc = fitz.open(file_path)
                try:
                    text = "\n".join(page.get_text() for page in doc)
                finally:
                    doc.close()
                return text
            except Exception as e:
                logger.warning(f"pdf 读取失败: {e}")
                return ""

        return ""

    async def _extract_with_llm(self, text: str) -> dict:
        """调用 LLM 提取结构化合同信息"""
        prompt = _CONTRACT_EXTRACTION_PROMPT + text[:4000]  # 限制长度
        try:
            response = await llm_call(
                system_prompt="你是一位合同审查专家，只输出 JSON。",
                user_message=prompt,
                temperature=0.1,
                max_tokens=2048,
            )
            return self._extract_json(response) or {"is_contract": False}
        except Exception as e:
            logger.error(f"合同 LLM 提取失败: {e}")
            return {"is_contract": False}

    def _build_summary(self, structured: dict) -> str:
        """从结构化数据生成一句话摘要"""
        if not structured.get("is_contract"):
            return "非合同文本"
        ct = structured.get("contract_type", "合同")
        pa = structured.get("parties", {})
        a_name = pa.get("party_a", {}).get("name", "甲方")
        b_name = pa.get("party_b", {}).get("name", "乙方")
        amount = structured.get("amount", {}).get("value", "")
        subject = structured.get("subject", "")
        parts = [f"{ct}", f"当事人：{a_name} 与 {b_name}"]
        if amount:
            parts.append(f"金额：{amount}")
        if subject:
            parts.append(f"标的：{subject}")
        return "；".join(parts)

    def _extract_json(self, text: str) -> dict | None:
        """从 LLM 响应中提取 JSON"""
        if not text:
            return None
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        patterns = [r"```json\s*(.*?)\s*```", r"```\s*(.*?)\s*```"]
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    continue
        try:
            start = min(text.index("{"), text.index("["))
            end = max(text.rindex("}"), text.rindex("]")) + 1
            return json.loads(text[start:end])
        except (ValueError, json.JSONDecodeError):
            pass
        return None
