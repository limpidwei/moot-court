# Moot Court — AI 模拟法庭

> 一款面向法律学习与实务训练的 AI 模拟法庭系统。用户创建案件后，AI 分别扮演原告、被告与法官，完整走完 8 阶段庭审流程，并支持证据上传、质证、策略选择、庭审复盘与报告导出。

---

## 功能特性

| 模块 | 功能 |
|------|------|
| **核心庭审** | 8 阶段完整流程：请求权分析 → 起诉 → 答辩 → 争议焦点 → 交叉询问 → 举证质证 → 最后陈述 → 判决 |
| **单方对抗模式** | 用户扮演原告或被告，AI 担任对手 + 法官 |
| **庭审流式输出** | SSE 推送，前端逐字展示 |
| **策略路线选择** | Phase 1/3 生成 2-3 条策略路线，用户选择后继续 |
| **证据系统** | 多模态上传（txt/docx/pdf/jpg/png），OCR 提取，AI 分析与冲突检测 |
| **RAG 知识库** | 16 部民事法规，庭审关键阶段自动注入检索结果 |
| **Agent V2** | Actor-Memory-Skill 架构，6 个内置 Legal Skill |
| **案件管理** | 创建 / 重命名 / 删除 / 全局搜索 / 只读分享 |
| **用量管理** | Token 追踪、日/月配额限制、用量看板 |
| **通知系统** | 庭审完成、证据分析完成触发站内通知 |
| **报告导出** | Markdown / PDF 庭审复盘报告 |

---

## 技术栈

- **前端**：Next.js 16 + React 19 + TypeScript + Tailwind CSS 4
- **后端**：FastAPI + Python 3.11+
- **工作流**：LangGraph
- **LLM**：OpenAI 兼容接口（DeepSeek 等）
- **RAG**：ChromaDB + sentence-transformers（`BAAI/bge-small-zh-v1.5`）
- **数据库**：PostgreSQL + SQLAlchemy
- **认证**：JWT + bcrypt
- **文档处理**：PyMuPDF / python-docx / pdfplumber / pytesseract

---

## 快速开始

### 后端

```bash
# 1. 安装依赖
pip install -r backend/requirements.txt

# 2. 配置环境变量
# 复制 backend/.env.example 为 backend/.env 并填写

# 3. 启动后端
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

### 前端

```bash
cd frontend-next

# 1. 安装依赖
npm install

# 2. 配置环境变量
# 复制 .env.example 为 .env.local 并填写

# 3. 本地开发
npm run dev
# 访问 http://localhost:3000
```

### Windows 一键启动

```bash
launcher.bat
```

---

## 目录结构

```
.
├── backend/              # FastAPI 后端
│   ├── agents/v2/        # V2 Agent 架构
│   ├── evidence/         # 多模态证据处理
│   ├── rag/              # RAG 检索与 Embedding
│   ├── orchestration/    # LangGraph 工作流
│   ├── services/         # 业务服务（Insights / PDF 导出等）
│   ├── routers/          # API 路由
│   ├── models/           # 数据模型
│   └── main.py           # 应用入口
├── frontend-next/        # Next.js 16 前端
│   ├── src/app/          # App Router 页面
│   ├── src/components/   # 组件
│   └── src/lib/          # 工具与 API 封装
├── data/                 # 运行时数据（ChromaDB、上传文件、Ontology）
├── models/               # 本地 Embedding 模型
├── tests/                # 测试套件
├── docs/                 # 文档
├── CLAUDE.md             # 项目协作指南
├── ROADMAP.md            # 产品路线图
├── TECH_SPEC.md          # 技术规范
└── launcher.bat          # Windows 启动脚本
```

---

## 文档索引

- 快速协作指南：[CLAUDE.md](./CLAUDE.md)
- 产品路线图：[ROADMAP.md](./ROADMAP.md)
- 技术规范：[TECH_SPEC.md](./TECH_SPEC.md)
- 变更日志：[docs/CHANGELOG.md](./docs/CHANGELOG.md)

---

## 测试

```bash
# 认证测试
py -m pytest tests/test_auth.py -v

# 回归测试（使用 mock LLM，无需真实 API）
py -m pytest tests/regression/ -v

# 全量核心测试
py -m pytest tests/test_auth.py tests/test_cases.py tests/test_evidence.py tests/test_ontology.py tests/test_agentic.py -v
```

---

## 注意事项

1. **大文件**：仓库包含 `models/bge-small-zh-v1.5/model.safetensors`（约 91 MB），首次 clone 较慢。
2. **本地数据**：`data/uploads/` 与 `data/chroma_db/` 包含运行时产生的测试数据与向量库。
3. **环境变量**：JWT 密钥、数据库密码、LLM API Key 等均通过 `.env` 管理，未提交到仓库。

---

## License

MIT
