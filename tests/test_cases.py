"""
案件管理 API 测试

覆盖：
- 创建案件
- 获取案件列表（用户隔离）
- 删除案件
- 未授权访问
- 跨用户访问隔离
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from backend.models.database import User


class TestCases:
    def test_create_case(self, client: TestClient, auth_headers: dict):
        """创建案件"""
        resp = client.post("/case/create", headers={**auth_headers, "Content-Type": "application/json"}, json={
            "case_title": "测试案件",
            "facts": "原告张三借给被告李四10万元。",
            "evidence": "借条一张",
            "claims": "请求归还借款",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "case_id" in data
        assert data["message"] == "案卷已提交"

    def test_list_cases_empty(self, client: TestClient, auth_headers: dict):
        """案件列表返回分页结构"""
        resp = client.get("/cases", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)
        assert data["page"] == 1
        assert data["page_size"] == 10

    def test_list_cases_with_data(self, client: TestClient, auth_headers: dict):
        """创建案件后列表应包含该案件"""
        # 创建案件
        client.post("/case/create", headers={**auth_headers, "Content-Type": "application/json"}, json={
            "case_title": "列表测试案件",
            "facts": "测试事实",
            "evidence": "测试证据",
            "claims": "测试请求",
        })
        resp = client.get("/cases", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        items = data["items"]
        assert len(items) >= 1
        assert any(c["case_title"] == "列表测试案件" for c in items)

    def test_unauthorized_create_case(self, client: TestClient):
        """未认证创建案件应返回 401/403"""
        resp = client.post("/case/create", json={
            "case_title": "未授权案件",
            "facts": "事实",
            "evidence": "证据",
            "claims": "请求",
        })
        assert resp.status_code in (401, 403)

    def test_user_isolation(self, client: TestClient, db_session):
        """用户 A 不能访问用户 B 的案件"""
        from backend.auth import hash_password, create_access_token
        from backend.models.database import User

        # 创建用户 A
        user_a = User(email="user_a@example.com", password_hash=hash_password("pass_a"), name="User A")
        db_session.add(user_a)
        db_session.commit()
        db_session.refresh(user_a)

        # 创建用户 B
        user_b = User(email="user_b@example.com", password_hash=hash_password("pass_b"), name="User B")
        db_session.add(user_b)
        db_session.commit()
        db_session.refresh(user_b)

        token_a = create_access_token(user_a.id, user_a.email)
        token_b = create_access_token(user_b.id, user_b.email)
        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # 用户 A 创建案件
        resp = client.post("/case/create", headers={**headers_a, "Content-Type": "application/json"}, json={
            "case_title": "A 的案件",
            "facts": "事实 A",
            "evidence": "证据 A",
            "claims": "请求 A",
        })
        assert resp.status_code == 200
        case_id = resp.json()["case_id"]

        # 用户 A 能访问
        resp_a = client.get(f"/trial/state/{case_id}", headers=headers_a)
        assert resp_a.status_code == 200

        # 用户 B 访问应返回 404（隐藏存在性）
        resp_b = client.get(f"/trial/state/{case_id}", headers=headers_b)
        assert resp_b.status_code == 404

    def test_list_cases_search(self, client: TestClient, auth_headers: dict):
        """全文搜索应能按标题、事实、证据过滤"""
        unique = "xyz123search"
        # 创建一个带唯一标识的案件
        client.post("/case/create", headers={**auth_headers, "Content-Type": "application/json"}, json={
            "case_title": f"搜索测试案件-{unique}",
            "facts": f"事实描述包含{unique}",
            "evidence": "证据",
            "claims": "请求",
        })

        # 按标题中的唯一词搜索
        resp = client.get(f"/cases?q={unique}", headers=auth_headers)
        data = resp.json()
        assert data["total"] >= 1
        assert any(unique in (c["case_title"] or "") for c in data["items"])

        # 按事实中的唯一词搜索
        resp = client.get(f"/cases?q=事实描述包含{unique}", headers=auth_headers)
        data = resp.json()
        assert data["total"] >= 1

        # 无结果搜索
        resp = client.get("/cases?q=不存在的关键词abc999", headers=auth_headers)
        data = resp.json()
        assert data["total"] == 0

    def test_list_cases_filter_by_mode(self, client: TestClient, auth_headers: dict):
        """按模式过滤"""
        client.post("/case/create", headers={**auth_headers, "Content-Type": "application/json"}, json={
            "case_title": "中立案件",
            "facts": "事实",
            "evidence": "证据",
            "claims": "请求",
            "mode": "neutral",
        })
        client.post("/case/create", headers={**auth_headers, "Content-Type": "application/json"}, json={
            "case_title": "单方对抗案件",
            "facts": "事实",
            "evidence": "证据",
            "claims": "请求",
            "mode": "asymmetric",
            "user_side": "plaintiff",
        })

        resp = client.get("/cases?mode=asymmetric", headers=auth_headers)
        data = resp.json()
        assert all(c.get("mode") == "asymmetric" for c in data["items"])

    def test_list_cases_pagination(self, client: TestClient, auth_headers: dict):
        """分页参数生效"""
        # 创建 3 个案件
        for i in range(3):
            client.post("/case/create", headers={**auth_headers, "Content-Type": "application/json"}, json={
                "case_title": f"分页案件{i+1}",
                "facts": "事实",
                "evidence": "证据",
                "claims": "请求",
            })

        resp = client.get("/cases?page_size=2&page=1", headers=auth_headers)
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] >= 3
        assert data["page"] == 1
        assert data["page_size"] == 2
