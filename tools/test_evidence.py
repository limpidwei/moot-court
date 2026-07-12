"""
多模态证据处理系统 -- 自动检查脚本（自带后端启动）
"""
import sys
import os
import time
import subprocess
import tempfile
import requests

PROJECT_DIR = os.path.dirname(os.path.dirname(__file__))
API_PORT = 8002
API_BASE = f"http://127.0.0.1:{API_PORT}"
TEST_EMAIL = "evidence_test@example.com"
TEST_PASSWORD = "test123456"
TEST_NAME = "EvidenceTest"

errors = []
warnings = []

def step(title):
    print(f"\n>> {title}")

def ok(msg):
    print(f"  [OK] {msg}")

def fail(msg):
    print(f"  [FAIL] {msg}")
    errors.append(msg)

def warn(msg):
    print(f"  [WARN] {msg}")
    warnings.append(msg)

# ============================================================
step("0. 启动后端")
# ============================================================
proc = None
try:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", str(API_PORT)],
        cwd=PROJECT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    print(f"  后端进程 PID: {proc.pid}")
    for _ in range(15):
        time.sleep(1)
        try:
            r = requests.get(f"{API_BASE}/docs", timeout=2)
            if r.status_code == 200:
                ok("后端启动成功")
                break
        except Exception:
            pass
    else:
        fail("后端启动超时")
        stdout, stderr = proc.communicate(timeout=5)
        if stderr:
            print(f"  错误输出: {stderr.decode('utf-8', errors='ignore')[:500]}")
        sys.exit(1)
except Exception as e:
    fail(f"启动后端异常: {e}")
    sys.exit(1)

# ============================================================
step("1. 后端连通性")
# ============================================================
try:
    r = requests.get(f"{API_BASE}/docs", timeout=5)
    ok("后端 /docs 可访问")
except Exception as e:
    fail(f"后端无法连接: {e}")

# ============================================================
step("2. 注册测试账号")
# ============================================================
try:
    r = requests.post(
        f"{API_BASE}/auth/register",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD, "name": TEST_NAME},
        timeout=10,
    )
    if r.status_code == 200:
        ok("注册成功")
    elif r.status_code == 400 and "already" in r.text.lower():
        ok("账号已存在")
    else:
        warn(f"注册返回 {r.status_code}")
except Exception as e:
    warn(f"注册异常: {e}")

# ============================================================
step("3. 登录认证")
# ============================================================
token = None
try:
    r = requests.post(
        f"{API_BASE}/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        timeout=10,
    )
    if r.status_code == 200:
        token = r.json().get("access_token")
        ok("登录成功，获取 Token")
    else:
        fail(f"登录失败: {r.status_code} {r.text}")
except Exception as e:
    fail(f"登录异常: {e}")

if not token:
    print("\n登录失败，后续测试跳过。")
    if proc:
        proc.terminate()
    sys.exit(1)

headers = {"Authorization": f"Bearer {token}"}

# ============================================================
step("4. 创建测试案件")
# ============================================================
case_id = None
try:
    r = requests.post(
        f"{API_BASE}/case/create",
        headers={"Content-Type": "application/json", **headers},
        json={
            "case_title": "证据系统测试案件",
            "facts": "原告张三与被告李四签订借款合同，约定借款10万元。",
            "evidence": "1. 借款合同（书证）",
            "claims": "请求判令被告归还借款10万元及利息。",
        },
        timeout=10,
    )
    if r.status_code == 200:
        case_id = r.json().get("case_id")
        ok(f"创建案件成功: {case_id}")
    else:
        fail(f"创建案件失败: {r.status_code} {r.text}")
except Exception as e:
    fail(f"创建案件异常: {e}")

if not case_id:
    if proc:
        proc.terminate()
    sys.exit(1)

# ============================================================
step("5. 数据库表检查")
# ============================================================
try:
    sys.path.insert(0, PROJECT_DIR)
    from backend.database import engine
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if "evidence_items" in tables:
        ok("evidence_items 表存在")
    else:
        fail("evidence_items 表不存在")
    if "conflict_reports" in tables:
        ok("conflict_reports 表存在")
    else:
        fail("conflict_reports 表不存在")
except Exception as e:
    fail(f"数据库检查异常: {e}")

# ============================================================
step("6. 证据上传测试")
# ============================================================
uploaded_evidence_ids = []

# txt
try:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("今借到张三人民币十万元整，约定2024年1月1日归还。\n借款人：李四\n2023年5月1日")
        tmp_path = f.name
    with open(tmp_path, "rb") as f:
        r = requests.post(
            f"{API_BASE}/evidence/upload",
            headers=headers,
            data={"case_id": case_id, "party": "plaintiff", "evidence_type": "书证"},
            files=[("files", ("借条.txt", f, "text/plain"))],
            timeout=30,
        )
    os.remove(tmp_path)
    if r.status_code == 200:
        result = r.json()
        ok(f"txt 上传成功: {result['uploaded']} 个文件")
        for item in result.get("results", []):
            if item.get("status") == "success":
                uploaded_evidence_ids.append(item["evidence_id"])
            else:
                warn(f"txt 上传项失败: {item}")
    else:
        fail(f"txt 上传失败: {r.status_code} {r.text}")
except Exception as e:
    fail(f"txt 上传异常: {e}")

# docx
try:
    from docx import Document
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        tmp_path = f.name
    doc = Document()
    doc.add_paragraph("这是一份测试合同。甲方：王五，乙方：赵六。签约日期：2023年6月15日。")
    doc.save(tmp_path)
    with open(tmp_path, "rb") as f:
        r = requests.post(
            f"{API_BASE}/evidence/upload",
            headers=headers,
            data={"case_id": case_id, "party": "defendant", "evidence_type": "书证"},
            files=[("files", ("合同.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
            timeout=30,
        )
    os.remove(tmp_path)
    if r.status_code == 200:
        result = r.json()
        ok(f"docx 上传成功: {result['uploaded']} 个文件")
        for item in result.get("results", []):
            if item.get("status") == "success":
                uploaded_evidence_ids.append(item["evidence_id"])
            else:
                warn(f"docx 上传项失败: {item}")
    else:
        fail(f"docx 上传失败: {r.status_code} {r.text}")
except ImportError:
    warn("python-docx 未安装，跳过 docx 测试")
except Exception as e:
    fail(f"docx 上传异常: {e}")

# pdf
try:
    import fitz
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        tmp_path = f.name
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "测试PDF文件。收款日期：2023年7月20日。金额：50000元。")
    doc.save(tmp_path)
    doc.close()
    with open(tmp_path, "rb") as f:
        r = requests.post(
            f"{API_BASE}/evidence/upload",
            headers=headers,
            data={"case_id": case_id, "party": "plaintiff", "evidence_type": "书证"},
            files=[("files", ("收据.pdf", f, "application/pdf"))],
            timeout=30,
        )
    os.remove(tmp_path)
    if r.status_code == 200:
        result = r.json()
        ok(f"pdf 上传成功: {result['uploaded']} 个文件")
        for item in result.get("results", []):
            if item.get("status") == "success":
                uploaded_evidence_ids.append(item["evidence_id"])
            else:
                warn(f"pdf 上传项失败: {item}")
    else:
        fail(f"pdf 上传失败: {r.status_code} {r.text}")
except ImportError:
    warn("pymupdf 未安装，跳过 pdf 测试")
except Exception as e:
    fail(f"pdf 上传异常: {e}")

# ============================================================
step("7. 证据列表获取")
# ============================================================
try:
    r = requests.get(f"{API_BASE}/evidence/{case_id}", headers=headers, timeout=10)
    if r.status_code == 200:
        registry = r.json()
        ok(f"证据列表: {len(registry.get('items', []))} 条")
    else:
        fail(f"证据列表失败: {r.status_code}")
except Exception as e:
    fail(f"证据列表异常: {e}")

# ============================================================
step("8. AI 分析 + 冲突检测")
# ============================================================
if len(uploaded_evidence_ids) >= 2:
    try:
        print("   触发 AI 分析（约 10-30 秒）...")
        r = requests.post(f"{API_BASE}/evidence/{case_id}/analyze", headers=headers, timeout=120)
        if r.status_code == 200:
            result = r.json()
            ok(f"AI 分析完成: {result.get('analyzed_count', 0)} 条")
            ok(f"发现冲突: {result.get('conflict_count', 0)} 个")
            ok(f"时间线事件: {result.get('timeline_count', 0)} 个")
            if result.get('conflict_count', 0) > 0:
                ok("冲突检测正常")
            else:
                warn("未检测到冲突")
        else:
            fail(f"AI 分析失败: {r.status_code} {r.text}")
    except requests.exceptions.Timeout:
        fail("AI 分析超时（LLM 慢）")
    except Exception as e:
        fail(f"AI 分析异常: {e}")
else:
    warn("证据不足 2 条，跳过冲突检测")

# ============================================================
step("9. 导入庭审系统")
# ============================================================
if uploaded_evidence_ids:
    try:
        r = requests.post(f"{API_BASE}/evidence/{case_id}/import-to-trial", headers=headers, timeout=10)
        if r.status_code == 200:
            result = r.json()
            ok(f"导入庭审成功: {result.get('imported_count', 0)} 条")
        else:
            fail(f"导入庭审失败: {r.status_code}")
    except Exception as e:
        fail(f"导入庭审异常: {e}")

# ============================================================
step("10. 清理测试数据")
# ============================================================
for ev_id in uploaded_evidence_ids:
    try:
        r = requests.delete(f"{API_BASE}/evidence/{case_id}/{ev_id}", headers=headers, timeout=10)
        if r.status_code == 200:
            ok(f"清理证据: {ev_id}")
        else:
            warn(f"清理证据失败 {ev_id}: {r.status_code}")
    except Exception as e:
        warn(f"清理证据异常 {ev_id}: {e}")

try:
    r = requests.delete(f"{API_BASE}/cases/{case_id}", headers=headers, timeout=10)
    if r.status_code == 200:
        ok(f"清理案件: {case_id}")
    else:
        warn(f"清理案件失败: {r.status_code}")
except Exception as e:
    warn(f"清理案件异常: {e}")

try:
    from backend.database import SessionLocal
    from backend.models.database import User
    db = SessionLocal()
    user = db.query(User).filter(User.email == TEST_EMAIL).first()
    if user:
        db.delete(user)
        db.commit()
        ok("清理测试用户")
    db.close()
except Exception as e:
    warn(f"清理用户异常: {e}")

# 关闭后端
if proc:
    print("\n  关闭后端进程...")
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

# ============================================================
step("检查结果汇总")
# ============================================================
print(f"\n{'='*50}")
print(f"错误: {len(errors)} 个  |  警告: {len(warnings)} 个")
print(f"{'='*50}")

if errors:
    print("\n失败项:")
    for e in errors:
        print(f"  - {e}")
if warnings:
    print("\n警告项:")
    for w in warnings:
        print(f"  - {w}")

if not errors:
    print("\n所有核心检查通过！证据系统可正常使用。")
else:
    print("\n存在失败项，请根据上述信息排查。")
