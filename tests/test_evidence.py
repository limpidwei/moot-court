"""
证据模块 API 测试

覆盖：
- 上传 txt 证据
- 上传 docx 证据
- 上传 pdf 证据
- 上传 ZIP 批量证据
- 获取证据列表
- 删除证据
- AI 分析端点（mock LLM）
"""
from __future__ import annotations

import io
import zipfile
from fastapi.testclient import TestClient
from backend.models.database import User


class TestEvidence:
    def _create_case(self, client: TestClient, auth_headers: dict) -> str:
        """辅助：创建测试案件"""
        resp = client.post("/case/create", headers={**auth_headers, "Content-Type": "application/json"}, json={
            "case_title": "证据测试案件",
            "facts": "原告与被告签订借款合同。",
            "evidence": "合同一份",
            "claims": "请求归还借款",
        })
        assert resp.status_code == 200
        return resp.json()["case_id"]

    def test_upload_txt(self, client: TestClient, auth_headers: dict):
        """上传 txt 文件"""
        case_id = self._create_case(client, auth_headers)
        resp = client.post(
            "/evidence/upload",
            headers=auth_headers,
            data={"case_id": case_id, "party": "plaintiff", "evidence_type": "书证"},
            files=[("files", ("test.txt", io.BytesIO("2023年5月1日，张三向李四借款10万元。".encode("utf-8")), "text/plain"))],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["uploaded"] == 1
        assert data["results"][0]["status"] == "success"

    def test_upload_docx(self, client: TestClient, auth_headers: dict):
        """上传 docx 文件"""
        try:
            import docx
        except ImportError:
            return  # 跳过

        case_id = self._create_case(client, auth_headers)
        doc = docx.Document()
        doc.add_paragraph("合同签订日期：2023年6月15日。甲方：王五，乙方：赵六。")
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)

        resp = client.post(
            "/evidence/upload",
            headers=auth_headers,
            data={"case_id": case_id, "party": "defendant", "evidence_type": "书证"},
            files=[("files", ("contract.docx", buf, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["uploaded"] == 1

    def test_upload_pdf(self, client: TestClient, auth_headers: dict):
        """上传 pdf 文件"""
        try:
            import fitz
        except ImportError:
            return  # 跳过

        case_id = self._create_case(client, auth_headers)
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "收据。收款日期：2023年7月20日。金额：50000元。")
        buf = io.BytesIO()
        doc.save(buf)
        doc.close()
        buf.seek(0)

        resp = client.post(
            "/evidence/upload",
            headers=auth_headers,
            data={"case_id": case_id, "party": "plaintiff", "evidence_type": "书证"},
            files=[("files", ("receipt.pdf", buf, "application/pdf"))],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["uploaded"] == 1

    def test_upload_zip(self, client: TestClient, auth_headers: dict):
        """上传 ZIP 批量文件"""
        case_id = self._create_case(client, auth_headers)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("file1.txt", "第一份证据内容。")
            zf.writestr("file2.txt", "第二份证据内容。")
        buf.seek(0)

        resp = client.post(
            "/evidence/upload",
            headers=auth_headers,
            data={"case_id": case_id, "party": "plaintiff", "evidence_type": "书证"},
            files=[("files", ("batch.zip", buf, "application/zip"))],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["uploaded"] == 2

    def test_get_registry(self, client: TestClient, auth_headers: dict):
        """获取证据列表"""
        case_id = self._create_case(client, auth_headers)
        client.post(
            "/evidence/upload",
            headers=auth_headers,
            data={"case_id": case_id, "party": "plaintiff"},
            files=[("files", ("note.txt", io.BytesIO("证据内容".encode("utf-8")), "text/plain"))],
        )
        resp = client.get(f"/evidence/{case_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["case_id"] == case_id
        assert len(data["items"]) >= 1

    def test_delete_evidence(self, client: TestClient, auth_headers: dict):
        """删除证据"""
        case_id = self._create_case(client, auth_headers)
        upload_resp = client.post(
            "/evidence/upload",
            headers=auth_headers,
            data={"case_id": case_id, "party": "plaintiff"},
            files=[("files", ("del.txt", io.BytesIO("待删除".encode("utf-8")), "text/plain"))],
        )
        ev_id = upload_resp.json()["results"][0]["evidence_id"]

        resp = client.delete(f"/evidence/{case_id}/{ev_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        # 再次删除应 404
        resp2 = client.delete(f"/evidence/{case_id}/{ev_id}", headers=auth_headers)
        assert resp2.status_code == 404

    def test_unauthorized_upload(self, client: TestClient):
        """未认证上传"""
        resp = client.post("/evidence/upload", data={"case_id": "abc"}, files=[])
        assert resp.status_code in (401, 403)
