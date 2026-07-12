import os
import sys

os.environ["USE_AGENT_V2"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from backend.models.case import CaseInput
from backend.agents.v2.defendant import DefendantAgentV2

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

    defendant = DefendantAgentV2()
    catalog = await defendant.draft_evidence_catalog(case.evidence, case_input=case)

    print("=" * 60)
    print("被告证据目录（带约束）")
    print("=" * 60)
    print(catalog)
    print("=" * 60)

    # 保存到文件
    with open("scripts/test_evidence_constraint_output.md", "w", encoding="utf-8") as f:
        f.write("# 被告证据目录约束测试\n\n")
        f.write(f"案件：{case.case_title}\n\n")
        f.write("## 事实锁\n\n")
        from backend.agents.v2.evidence_constraint import FactExtractor
        lock = FactExtractor().extract(case)
        f.write(lock.to_prompt())
        f.write("\n\n## 被告证据目录\n\n```\n")
        f.write(catalog)
        f.write("\n```\n")
    print("已保存到 scripts/test_evidence_constraint_output.md")

if __name__ == "__main__":
    asyncio.run(main())
