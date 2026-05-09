"""
模拟法庭 — Streamlit 前端

用法：
  1. 先启动后端:  cd moot-court && uvicorn backend.main:app --port 8000
  2. 再启动前端:  cd moot-court && streamlit run frontend/app.py
"""

import requests
import streamlit as st

# ---- 配置 ----
st.set_page_config(
    page_title="模拟法庭",
    page_icon="⚖️",
    layout="wide",
)

API_BASE = "http://127.0.0.1:8000"


# ---- 页面 ----
st.title("⚖️ 模拟法庭")
st.caption(
    "输入案情和证据，AI 法官与双方律师即刻按照《民事诉讼法》"
    "程序进行模拟庭审，并给出量化的胜率评估。"
)

# -- 侧边栏：案卷输入 --
with st.sidebar:
    st.header("📋 案卷信息")

    case_title = st.text_input(
        "案由",
        placeholder="例如：买卖合同纠纷",
    )
    facts = st.text_area(
        "案情事实",
        placeholder=(
            "描述案件发生的时间、地点、当事人、"
            "主要经过等核心事实要素..."
        ),
        height=180,
    )
    evidence = st.text_area(
        "证据清单",
        placeholder=(
            "每行一项，标注证据类型，例如：\n"
            "1. 《购销合同》原件——书证\n"
            "2. 银行转账凭证——电子数据\n"
            "3. 微信聊天记录截图——电子数据\n"
            "4. 收货单——书证"
        ),
        height=150,
    )
    claims = st.text_area(
        "诉讼请求",
        placeholder=(
            "例如：\n"
            "1. 判令被告支付货款人民币50万元\n"
            "2. 判令被告支付逾期付款利息\n"
            "   （自2025年3月1日起至实际付清之日止，\n"
            "    按LPR的1.5倍计算）\n"
            "3. 本案诉讼费由被告承担"
        ),
        height=140,
    )

    start_btn = st.button(
        "🔨 开始模拟庭审",
        type="primary",
        use_container_width=True,
    )


# -- 主区域 --
if "trial_phases" not in st.session_state:
    st.session_state.trial_phases = None
if "trial_loading" not in st.session_state:
    st.session_state.trial_loading = False
if "case_id" not in st.session_state:
    st.session_state.case_id = None


def reset_trial():
    st.session_state.trial_phases = None
    st.session_state.trial_loading = False
    st.session_state.case_id = None


if start_btn:
    if not case_title or not facts or not evidence or not claims:
        st.error("请填写完整的案卷信息（案由、事实、证据、诉讼请求）")
    else:
        reset_trial()
        st.session_state.trial_loading = True
        st.session_state.case_id = None

        # 1. 创建案卷
        with st.spinner("正在提交案卷..."):
            resp = requests.post(
                f"{API_BASE}/case/create",
                json={
                    "case_title": case_title,
                    "facts": facts,
                    "evidence": evidence,
                    "claims": claims,
                },
                timeout=30,
            )
            if resp.status_code != 200:
                st.error(f"提交案卷失败: {resp.text}")
                st.session_state.trial_loading = False
            else:
                st.session_state.case_id = resp.json()["case_id"]

        # 2. 执行庭审
        if st.session_state.case_id:
            with st.spinner(
                "庭审进行中，7 个阶段依次推进，请耐心等待（约 2-4 分钟）..."
            ):
                resp = requests.get(
                    f"{API_BASE}/trial/run/{st.session_state.case_id}",
                    timeout=600,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    st.session_state.trial_phases = data.get("phases", [])
                    st.session_state.trial_loading = False
                else:
                    st.error(f"庭审执行失败: {resp.text}")
                    st.session_state.trial_loading = False

        st.rerun()


# 展示庭审结果
if st.session_state.trial_phases:
    phases = st.session_state.trial_phases
    st.success(f"✅ 庭审结束，共完成 {len(phases)} 个阶段")

    for i, phase in enumerate(phases):
        with st.expander(
            f"**阶段 {i + 1}：{phase['label']}**",
            expanded=(i == len(phases) - 1),
        ):
            st.markdown(phase["content"])

    if st.button("🔄 重新开庭", use_container_width=True):
        reset_trial()
        st.rerun()
