"""
Case Ontology 单元测试
"""

import pytest
from backend.models.case import CaseInput
from backend.ontology.extractor import extract_from_case_input, enrich_from_trial_session
from backend.ontology.models import CaseOntology
from backend.ontology import service as ontology_service
from backend.orchestration.workflow import TrialSession


@pytest.fixture
def sample_case_input():
    return CaseInput(
        case_title="原告张三诉被告李四民间借贷纠纷",
        facts="2023年1月1日，被告李四因生意周转需要，向原告张三借款人民币10万元，约定2023年6月30日前归还。"
              "原告通过银行转账支付了该笔借款。借款到期后，被告未按约定还款。",
        evidence="1. 借条（书证）—— 证明借款合意\n2. 银行转账记录（书证）—— 证明借款已交付",
        claims="1. 判令被告偿还借款本金10万元（依据《中华人民共和国民法典》第675条）\n"
           "2. 判令被告支付逾期利息（依据《中华人民共和国民法典》第676条）",
        mode="asymmetric",
        user_side="plaintiff",
        source_materials="原告张三诉被告李四民间借贷纠纷，借款10万元。",
    )


@pytest.fixture
def sample_trial_session(sample_case_input):
    session = TrialSession(case_input=sample_case_input, user_id=1)
    session.current_phase = 5
    session.phase5_issues = (
        "1. 原被告之间是否存在真实有效的借贷关系？\n"
        "2. 原告是否实际交付了借款本金？\n"
        "3. 被告是否应当支付逾期利息？"
    )
    session.phase1_analysis = (
        "本案可依据《中华人民共和国民法典》第679条主张自然人借款合同自借款交付时生效。"
    )
    session.phase8_judgment = (
        "综合全案证据，原告主张的借贷关系成立，被告应偿还本金10万元及逾期利息。"
    )
    return session


def test_extract_from_case_input(sample_case_input):
    ont = extract_from_case_input(sample_case_input)
    assert isinstance(ont, CaseOntology)
    assert ont.case.title == sample_case_input.case_title
    assert ont.case.case_type == "民间借贷纠纷"
    assert len(ont.parties) >= 2
    assert any(p.role == "plaintiff" for p in ont.parties)
    assert any(p.role == "defendant" for p in ont.parties)
    assert len(ont.facts) >= 1
    assert len(ont.claims) == 2
    assert len(ont.evidence) == 2
    # 法条提取：source 应包含「民法典」
    sources = [n.source for n in ont.legal_norms]
    assert any("民法典" in s for s in sources), f"未提取到民法典，实际 sources={sources}"


def test_enrich_from_trial_session(sample_trial_session):
    ont = extract_from_case_input(sample_trial_session.case_input)
    ont = enrich_from_trial_session(ont, sample_trial_session)
    assert ont.case.status == "running"
    assert len(ont.issues) == 3
    assert any("借贷关系" in i.title for i in ont.issues)
    assert len(ont.decisions) >= 1
    assert len(ont.action_items) >= 1


def test_ontology_service_build_and_save(sample_trial_session):
    sample_trial_session.case_input.case_title = "test-service-case"
    ontology = ontology_service.build_and_save_ontology(sample_trial_session)
    case_id = ontology.case.id

    loaded = ontology_service.get_ontology(case_id)
    assert loaded is not None
    assert loaded.case.title == "test-service-case"

    summary = ontology_service.get_dashboard_summary(case_id)
    assert summary is not None
    assert summary["stats"]["facts_count"] >= 1

    ontology_service.delete_ontology(case_id)
    assert ontology_service.get_ontology(case_id) is None


def test_ontology_to_dict_roundtrip(sample_case_input):
    ont = extract_from_case_input(sample_case_input)
    data = ont.to_dict()
    restored = CaseOntology.from_dict(data)
    assert restored.case.title == ont.case.title
    assert len(restored.facts) == len(ont.facts)
