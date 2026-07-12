"""
真实 LLM 完整庭审测试 —— 验证新 Skill Prompt 效果
运行：cd /c/Users/86186/moot-court && py scripts/test_skill_v2_real.py
"""
import os
import sys
import asyncio

os.environ["USE_AGENT_V2"] = "true"

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.models.case import CaseInput
from backend.orchestration.workflow import create_initial_state
from backend.orchestration.workflow_v2 import run_trial_v2
from backend.llm import LLMConfig, _default_config


def _print_section(title: str, content: str, max_len: int = 2000):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")
    print(content[:max_len] if len(content) > max_len else content)
    if len(content) > max_len:
        print(f"\n... (截断，共 {len(content)} 字符)")


async def main():
    case = CaseInput(
        case_title="借款合同纠纷",
        facts=(
            "2023年3月1日，原告张三通过银行转账借给被告李四人民币10万元，"
            "双方口头约定借款期限为6个月，月利率1.5%。"
            "2023年9月1日借款到期后，被告未归还本金及利息。"
            "原告多次催讨无果，遂起诉至法院。"
            "被告辩称：10万元不是借款，而是原告委托其投资理财的款项；"
            "且双方从未约定利息。"
        ),
        evidence="1. 银行转账记录（2023年3月1日，张三转李四10万元）\n2. 微信聊天记录（张三催款记录，李四回复'再等等'）\n3. 证人王五证言（在场听到双方谈论借款）",
        claims="1. 判令被告归还借款本金10万元；2. 判令被告支付利息（按月利率1.5%计算，自2023年3月1日至实际清偿之日）；3. 被告承担本案诉讼费用。",
    )

    state = create_initial_state(case, user_role="neutral")
    state["llm_config"] = _default_config()

    print("开始真实 LLM 完整庭审测试...")
    print(f"案件：{case.case_title}")
    print(f"LLM：{state['llm_config'].model}")

    # 逐阶段运行
    for phase in range(1, 9):
        print(f"\n{'#' * 70}")
        print(f"# Phase {phase}")
        print(f"{'#' * 70}")

        # 运行当前阶段
        state = await run_trial_v2(state)

        # 输出当前阶段结果
        if phase == 1 and state.get("phase1_analysis"):
            _print_section("Phase 1: 请求权基础分析", state["phase1_analysis"])
        elif phase == 2 and state.get("phase2_complaint"):
            _print_section("Phase 2: 起诉状", state["phase2_complaint"])
        elif phase == 3 and state.get("phase3_analysis"):
            _print_section("Phase 3: 答辩策略分析", state["phase3_analysis"])
        elif phase == 4 and state.get("phase4_answer"):
            _print_section("Phase 4: 答辩状", state["phase4_answer"])
        elif phase == 5 and state.get("phase5_issues"):
            _print_section("Phase 5: 争议焦点", state["phase5_issues"])
        elif phase == 6:
            if state.get("phase6_cross_exam"):
                _print_section("Phase 6: 交叉询问", state["phase6_cross_exam"])
            if state.get("phase6_evidence_exam"):
                _print_section("Phase 6: 举证质证", state["phase6_evidence_exam"])
        elif phase == 7:
            if state.get("phase7_plaintiff_final"):
                _print_section("Phase 7: 原告最后陈述", state["phase7_plaintiff_final"])
            if state.get("phase7_defendant_final"):
                _print_section("Phase 7: 被告最后陈述", state["phase7_defendant_final"])
        elif phase == 8 and state.get("phase8_judgment"):
            _print_section("Phase 8: 判决书", state["phase8_judgment"])

        # 标记当前阶段完成，继续下一阶段
        if phase < 8:
            state[f"phase{phase}_confirmed"] = True

        if state.get("error"):
            print(f"[错误] Phase {phase}: {state['error']}")

    print("\n" + "=" * 70)
    print("庭审测试完成！")
    print("=" * 70)

    # 保存完整输出到文件
    output_path = "scripts/test_skill_v2_output.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# 真实 LLM 完整庭审测试输出\n\n")
        f.write(f"案件：{case.case_title}\n")
        f.write(f"LLM：{state['llm_config'].model}\n\n")
        for phase in range(1, 9):
            f.write(f"## Phase {phase}\n\n")
            for key in sorted(state.keys()):
                if key.startswith(f"phase{phase}_") and state.get(key):
                    f.write(f"### {key}\n\n```\n{state[key]}\n```\n\n")
    print(f"完整输出已保存到：{output_path}")


if __name__ == "__main__":
    asyncio.run(main())
