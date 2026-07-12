"""
数据库模型定义 - 使用 SQLAlchemy ORM

包含：
- User: 用户表
- Case: 案件表
- CasePhase: 案件阶段表
- CaseAnalysis: 案件分析表（统一分析结果）
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey,
    JSON, Float, Boolean, Index
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """SQLAlchemy 基类"""
    pass


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(100), nullable=True)

    # 配额限制（0 表示无限制）
    daily_token_limit = Column(Integer, default=1_000_000, nullable=False)
    monthly_token_limit = Column(Integer, default=10_000_000, nullable=False)

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    # 关系：一个用户可以有多个案件
    cases = relationship("Case", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}', name='{self.name}')>"


class Case(Base):
    """案件表"""
    __tablename__ = "cases"

    id = Column(String(50), primary_key=True)  # 使用UUID或短ID
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    case_title = Column(String(255), nullable=True)
    case_input = Column(JSON, nullable=False)  # 存储 CaseInput 对象
    current_phase = Column(Integer, default=1, nullable=False)
    user_role = Column(String(50), default="neutral", nullable=False)

    # 元数据
    created_at = Column(DateTime, default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    # 关系
    user = relationship("User", back_populates="cases")
    phases = relationship("CasePhase", back_populates="case", cascade="all, delete-orphan")
    analysis = relationship("CaseAnalysis", back_populates="case", uselist=False, cascade="all, delete-orphan")

    # 索引：加速查询
    __table_args__ = (
        Index("idx_case_user_created", "user_id", "created_at"),
    )

    def __repr__(self):
        return f"<Case(id='{self.id}', title='{self.case_title}', phase={self.current_phase})>"


class CasePhase(Base):
    """案件阶段表 - 存储每个阶段的输出"""
    __tablename__ = "case_phases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(50), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    phase_number = Column(Integer, nullable=False)  # 1-8

    # 阶段内容
    phase_content = Column(Text, nullable=True)  # 主要文本输出
    phase_insights = Column(JSON, nullable=True)  # 洞察数据
    phase_viz_data = Column(JSON, nullable=True)  # 可视化数据

    # 元数据
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    # 关系
    case = relationship("Case", back_populates="phases")

    # 唯一约束：每个案件的每个阶段只能有一条记录
    __table_args__ = (
        Index("idx_case_phase", "case_id", "phase_number", unique=True),
    )

    def __repr__(self):
        return f"<CasePhase(case_id='{self.case_id}', phase={self.phase_number})>"


class CaseAnalysis(Base):
    """案件统一分析表 - 存储 CaseAnalysis 对象"""
    __tablename__ = "case_analysis"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(50), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, unique=True)

    # 分析数据（JSON格式）
    analysis_data = Column(JSON, nullable=False)

    # 元数据
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    # 关系
    case = relationship("Case", back_populates="analysis")

    def __repr__(self):
        return f"<CaseAnalysis(case_id='{self.case_id}')>"


class EvidenceItemModel(Base):
    """证据项表 - 存储多模态证据"""
    __tablename__ = "evidence_items"

    id = Column(String(50), primary_key=True)
    case_id = Column(String(50), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # 文件信息
    filename = Column(String(255), nullable=False)
    storage_path = Column(String(500), nullable=False)
    source_type = Column(String(50), nullable=False)   # txt / docx / pdf / image / audio / contract
    mime_type = Column(String(100), nullable=True)
    file_size = Column(Integer, default=0)

    # 证据分类（由 AI 或用户指定）
    evidence_type = Column(String(50), default="")     # 书证 / 物证 / 电子数据 / 证人证言 / 鉴定意见
    party = Column(String(50), default="unknown")      # plaintiff / defendant / third_party / unknown

    # 提取的内容
    content = Column(Text, nullable=True)              # 提取的完整文本（OCR/转写结果）
    summary = Column(Text, nullable=True)              # AI 摘要
    extracted_date = Column(String(50), nullable=True) # 提取的关联日期
    parties = Column(JSON, default=list)               # 涉及的当事人
    relevance = Column(JSON, default=list)             # 关联争议焦点
    confidence = Column(Float, default=1.0)            # 提取置信度

    # 处理状态
    status = Column(String(20), default="pending")     # pending / extracting / analyzing / completed / failed
    error_message = Column(Text, nullable=True)

    # 元数据
    raw_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    # 关系
    case = relationship("Case", backref="evidence_items", passive_deletes=True)

    # 索引
    __table_args__ = (
        Index("idx_evidence_case_status", "case_id", "status"),
        Index("idx_evidence_case_party", "case_id", "party"),
    )

    def __repr__(self):
        return f"<EvidenceItem(id='{self.id}', case='{self.case_id}', type='{self.source_type}')>"


class ConflictReportModel(Base):
    """证据冲突报告表 - 存储检测到的矛盾"""
    __tablename__ = "conflict_reports"

    id = Column(String(50), primary_key=True)
    case_id = Column(String(50), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # 冲突信息
    conflict_type = Column(String(50), nullable=False)  # temporal / factual / quantitative / party / stance
    severity = Column(String(20), default="medium")     # high / medium / low
    description = Column(Text, nullable=False)          # 冲突描述

    # 涉及的证据和当事人
    involved_evidence_ids = Column(JSON, default=list)
    involved_parties = Column(JSON, default=list)

    # 各方主张（结构化存储）
    claims = Column(JSON, default=list)                 # list[dict] 各方具体说法
    ai_note = Column(Text, nullable=True)               # LLM 分析备注

    # 律师处理状态
    resolved = Column(Boolean, default=False)
    lawyer_note = Column(Text, nullable=True)

    # 元数据
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    # 索引
    __table_args__ = (
        Index("idx_conflict_case_resolved", "case_id", "resolved"),
    )

    def __repr__(self):
        return f"<ConflictReport(id='{self.id}', case='{self.case_id}', type='{self.conflict_type}')>"


class LLMUsageRecord(Base):
    """LLM 用量记录表 - 追踪每次 API 调用的 token 消耗"""
    __tablename__ = "llm_usage_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    case_id = Column(String(50), nullable=True, index=True)

    model = Column(String(100), nullable=False)
    endpoint = Column(String(50), nullable=False)       # llm_call / llm_call_stream
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    latency_ms = Column(Integer, default=0)
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=func.now(), nullable=False, index=True)

    # 索引：加速按用户和日期的统计查询
    __table_args__ = (
        Index("idx_usage_user_created", "user_id", "created_at"),
    )

    def __repr__(self):
        return f"<LLMUsageRecord(id={self.id}, user={self.user_id}, tokens={self.total_tokens})>"


class CaseShare(Base):
    """案件分享表 — 生成只读分享链接"""
    __tablename__ = "case_shares"

    id = Column(String(50), primary_key=True)
    case_id = Column(String(50), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(String(100), unique=True, nullable=False, index=True)
    permission = Column(String(20), default="read", nullable=False)  # read only for now
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)

    def __repr__(self):
        return f"<CaseShare(id='{self.id}', case='{self.case_id}', token='{self.token[:8]}...')>"


class Notification(Base):
    """通知表 — 站内消息"""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(50), nullable=False)          # trial_complete / evidence_ready / system
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    data = Column(JSON, default=dict)                  # 额外数据（case_id 等）
    read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False, index=True)

    # 索引
    __table_args__ = (
        Index("idx_notif_user_read", "user_id", "read"),
    )

    def __repr__(self):
        return f"<Notification(id={self.id}, user={self.user_id}, type='{self.type}', read={self.read})>"
