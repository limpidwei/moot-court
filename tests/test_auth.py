"""
认证模块测试

覆盖：
- 用户注册
- 用户登录
- 获取当前用户信息
- 重复注册
- 错误密码
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from backend.models.database import User


class TestAuth:
    def test_register_success(self, client: TestClient, db_session):
        """正常注册"""
        resp = client.post("/auth/register", json={
            "email": "newuser@example.com",
            "password": "newpass123",
            "name": "New User",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["email"] == "newuser@example.com"
        assert data["user"]["name"] == "New User"
        assert "access_token" in data

    def test_register_duplicate_email(self, client: TestClient, test_user: User):
        """重复注册应返回 400"""
        resp = client.post("/auth/register", json={
            "email": test_user.email,
            "password": "somepass123",
            "name": "Duplicate",
        })
        assert resp.status_code == 400

    def test_register_invalid_email(self, client: TestClient):
        """无效邮箱格式"""
        resp = client.post("/auth/register", json={
            "email": "not-an-email",
            "password": "pass123",
            "name": "Bad",
        })
        assert resp.status_code == 422

    def test_login_success(self, client: TestClient, test_user: User):
        """正常登录"""
        resp = client.post("/auth/login", json={
            "email": test_user.email,
            "password": "testpass123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == test_user.email

    def test_login_wrong_password(self, client: TestClient, test_user: User):
        """密码错误"""
        resp = client.post("/auth/login", json={
            "email": test_user.email,
            "password": "wrongpassword",
        })
        assert resp.status_code == 401

    def test_login_user_not_found(self, client: TestClient):
        """用户不存在"""
        resp = client.post("/auth/login", json={
            "email": "nobody@example.com",
            "password": "anypass",
        })
        assert resp.status_code == 401

    def test_me_authenticated(self, client: TestClient, test_user: User, auth_headers: dict):
        """携带 Token 获取当前用户"""
        resp = client.get("/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == test_user.email
        assert data["name"] == test_user.name

    def test_me_unauthorized(self, client: TestClient):
        """未携带 Token 应返回 401 或 403"""
        resp = client.get("/auth/me")
        assert resp.status_code in (401, 403)

    def test_me_invalid_token(self, client: TestClient):
        """无效 Token"""
        resp = client.get("/auth/me", headers={"Authorization": "Bearer invalidtoken"})
        assert resp.status_code == 401
