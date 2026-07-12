"""
Pytest 共享 fixtures

策略：
- 复用 backend.database 全局 engine（SQLite :memory:）
- main.py 模块导入时 init_db() 已在该引擎上建表
- 每个测试前清空所有表数据，保持隔离
"""
from __future__ import annotations

import os

# 必须在导入任何 backend 模块前设置环境变量
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-pytest-only-32bytes"
os.environ["JWT_EXPIRATION_HOURS"] = "24"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.database import engine, SessionLocal, get_db
from backend.models.database import Base
from backend.main import app
from backend.auth import hash_password

# 确保表已创建（main.py 导入时也会调用 init_db，但这里再保险一次）
Base.metadata.create_all(bind=engine)


def _clear_all_tables():
    """清空所有表数据"""
    db = SessionLocal()
    from backend.models.database import (
        User, Case, CasePhase, CaseAnalysis,
        EvidenceItemModel, ConflictReportModel,
    )
    for model in [ConflictReportModel, EvidenceItemModel, CaseAnalysis, CasePhase, Case, User]:
        db.query(model).delete()
    db.commit()
    db.close()


@pytest.fixture(autouse=True)
def clean_db():
    """每个测试前清空表数据"""
    _clear_all_tables()
    yield
    _clear_all_tables()


@pytest.fixture
def db_session() -> Session:
    """测试函数独立的 DB session"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient，DB 依赖替换为每个请求新建 session（避免跨线程问题）"""
    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def test_user(db_session: Session):
    """创建一个测试用户并返回"""
    from backend.models.database import User
    user = User(
        email="test@example.com",
        password_hash=hash_password("testpass123"),
        name="Test User",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def auth_headers(client: TestClient, test_user):
    """已认证用户的请求头"""
    resp = client.post("/auth/login", json={
        "email": test_user.email,
        "password": "testpass123",
    })
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
