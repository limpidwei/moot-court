"""
Insight / 可视化模块回归测试

目标：确保 insights 提取和 JSON 解析的稳定性，
防止后续改动导致 Insight 卡片空白或解析失败。

覆盖场景：
1. _try_parse_json 能处理多种 LLM 输出格式
2. extract_phase_insights 各 phase 返回正确的字段结构
3. Phase 8 的 known_win_rate 正确注入 prompt
4. LLM 返回异常内容时的容错处理
"""
from __future__ import annotations

import pytest
import json

from backend.services.insights import (
    _try_parse_json,
    extract_phase_insights,
    _PHASE_PROMPTS,
)


# ═══════════════════════════════════════════════════════════
# 测试 1：_try_parse_json 多策略解析
# ═══════════════════════════════════════════════════════════

class TestTryParseJSON:
    """验证 JSON 解析器能处理 LLM 的各种输出格式"""

    def test_direct_json(self):
        text = '{"legal_relation": "借款合同", "win_rate_assessment": {"level": "high", "reason": "证据充分"}}'
        result = _try_parse_json(text)
        assert result is not None
        assert result["legal_relation"] == "借款合同"

    def test_markdown_code_block(self):
        text = '```json\n{"legal_relation": "买卖合同"}\n```'
        result = _try_parse_json(text)
        assert result is not None
        assert result["legal_relation"] == "买卖合同"

    def test_markdown_code_block_without_lang(self):
        text = '```\n{"legal_relation": "劳动争议"}\n```'
        result = _try_parse_json(text)
        assert result is not None
        assert result["legal_relation"] == "劳动争议"

    def test_extract_from_surrounding_text(self):
        text = '根据分析，关键信息如下：\n{\n  "legal_relation": "侵权责任",\n  "best_claim_basis": "民法典第1165条"\n}\n希望对你有帮助。'
        result = _try_parse_json(text)
        assert result is not None
        assert result["best_claim_basis"] == "民法典第1165条"

    def test_invalid_json_returns_none(self):
        text = '这不是 JSON，只是一段普通文字。'
        result = _try_parse_json(text)
        assert result is None

    def test_empty_string_returns_none(self):
        result = _try_parse_json("")
        assert result is None

    def test_nested_json(self):
        text = '{"key_issues": [{"text": "合同是否有效", "favor": "neutral"}]}'
        result = _try_parse_json(text)
        assert result is not None
        assert len(result["key_issues"]) == 1


# ═══════════════════════════════════════════════════════════
# 测试 2：extract_phase_insights 各 Phase 字段结构
# ═══════════════════════════════════════════════════════════

class TestExtractPhaseInsights:
    """验证各 phase 的 insights 提取返回预期结构"""

    @pytest.mark.asyncio
    async def test_phase1_structure(self, mock_insights_llm):
        mock_insights_llm.return_value = json.dumps({
            "legal_relation": "借款合同纠纷",
            "best_claim_basis": "民法典第679条",
            "win_rate_assessment": {"level": "high", "reason": "证据链完整"},
            "key_risks": [{"severity": "warning", "text": "利息约定不明确"}],
            "next_action": "准备起诉状",
        })
        result = await extract_phase_insights(1, "mock phase1 content")
        assert "error" not in result
        assert result["legal_relation"] == "借款合同纠纷"
        assert result["_phase"] == 1

    @pytest.mark.asyncio
    async def test_phase2_structure(self, mock_insights_llm):
        mock_insights_llm.return_value = json.dumps({
            "core_claims": ["归还借款10万元", "支付利息"],
            "evidence_strength": [
                {"name": "借条", "strength": "strong", "reason": "有双方签字"},
            ],
            "likely_attacks": ["主张已还款"],
        })
        result = await extract_phase_insights(2, "mock phase2 content")
        assert "error" not in result
        assert result["_phase"] == 2
        assert len(result["core_claims"]) == 2

    @pytest.mark.asyncio
    async def test_phase5_structure(self, mock_insights_llm):
        mock_insights_llm.return_value = json.dumps({
            "key_issues": [
                {"text": "借款本金数额", "favor": "neutral", "reason": "双方无争议"},
            ],
            "likely_direction": "支持原告诉请",
        })
        result = await extract_phase_insights(5, "mock phase5 content")
        assert "error" not in result
        assert result["_phase"] == 5

    @pytest.mark.asyncio
    async def test_phase6_structure(self, mock_insights_llm):
        mock_insights_llm.return_value = json.dumps({
            "favorable_points": ["对方无法提供还款凭证"],
            "unfavorable_points": [{"severity": "danger", "text": "利息约定无书面证据"}],
            "evidence_forecast": [
                {"evidence": "借条", "forecast": "adopt", "reason": "原件核对无误"},
            ],
        })
        result = await extract_phase_insights(6, "mock phase6 content")
        assert "error" not in result
        assert result["_phase"] == 6

    @pytest.mark.asyncio
    async def test_phase8_structure(self, mock_insights_llm):
        mock_insights_llm.return_value = json.dumps({
            "verdict": {"result": "support", "summary": "支持原告诉请"},
            "win_rate": 72.5,
            "key_reasons": ["证据链完整"],
            "appeal_suggestion": "无显著上诉价值",
        })
        result = await extract_phase_insights(8, "mock phase8 content", known_win_rate=72.5)
        assert "error" not in result
        assert result["_phase"] == 8
        assert result["win_rate"] == 72.5

    @pytest.mark.asyncio
    async def test_phase8_injects_known_win_rate(self, mock_insights_llm):
        """验证 Phase 8 的 prompt 中包含 known_win_rate 的精确数值"""
        mock_insights_llm.return_value = '{"win_rate": 65.0}'
        await extract_phase_insights(8, "mock content", known_win_rate=65.0)
        # 检查调用 prompt 中是否包含精确数值
        call_args = mock_insights_llm.call_args
        prompt = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("prompt", "")
        assert "65.0" in prompt, "Phase 8 prompt 应包含 known_win_rate 精确数值"

    @pytest.mark.asyncio
    async def test_unsupported_phase(self):
        """不支持的 phase 应返回错误信息"""
        result = await extract_phase_insights(99, "mock content")
        assert "error" in result
        assert "暂不支持" in result["error"]

    @pytest.mark.asyncio
    async def test_llm_failure_handling(self, mock_insights_llm):
        """LLM 调用失败时应返回错误信息，不抛异常"""
        mock_insights_llm.side_effect = Exception("API 超时")
        result = await extract_phase_insights(1, "mock content")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_non_json_response_handling(self, mock_insights_llm):
        """LLM 返回非 JSON 时应返回 raw 文本和 error 标记"""
        mock_insights_llm.return_value = "这只是一个普通文本回复，不是 JSON。"
        result = await extract_phase_insights(1, "mock content")
        assert "error" in result
        assert "raw" in result
        assert "JSON 解析失败" in result["error"]

    @pytest.mark.asyncio
    async def test_truncation_for_long_content(self, mock_insights_llm):
        """超长内容应被截断到 4000 字符"""
        mock_insights_llm.return_value = '{"legal_relation": "test"}'
        long_content = "A" * 10000
        await extract_phase_insights(1, long_content)
        call_args = mock_insights_llm.call_args
        prompt = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("prompt", "")
        assert len(prompt) < 5000, "prompt 应包含截断后的内容"
        assert "内容已截断" in prompt, "截断标记应在 prompt 中"


# ═══════════════════════════════════════════════════════════
# 测试 3：Phase Prompt 模板完整性
# ═══════════════════════════════════════════════════════════

class TestPhasePrompts:
    """验证各 phase 的 prompt 模板完整且包含必要字段"""

    def test_all_supported_phases_have_prompts(self):
        supported_phases = [1, 2, 5, 6, 8]
        for phase in supported_phases:
            assert phase in _PHASE_PROMPTS, f"Phase {phase} 应有 prompt 模板"

    def test_prompt_templates_contain_json_instruction(self):
        for phase, prompt in _PHASE_PROMPTS.items():
            assert "JSON" in prompt, f"Phase {phase} prompt 应要求 JSON 输出"

    def test_prompt_templates_contain_content_placeholder(self):
        for phase, prompt in _PHASE_PROMPTS.items():
            assert "{content}" in prompt, f"Phase {phase} prompt 应包含 {content} 占位符"
