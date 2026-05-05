# BackendTestForge

多 Agent 后端质量检测系统。输入后端代码 → 自动测试 → 输出可视化报告 + AI 可读修复文档。

## 功能

- **代码自动解析** — 扫描项目目录，自动识别技术栈、API 端点、入口文件
- **阶梯压测** — 使用 k6 逐步增加并发（10→50→100→200→500 VUs），检测性能拐点
- **质量报告** — 综合评分（A/B/C/D）+ 压测曲线图 + 修复建议
- **修复文档** — 结构化 Markdown 文档，可直接发给 AI 进行代码优化
- **多启动模式** — 支持 direct / Docker Compose / manual 三种被测服务启动方式
- **多语言支持** — Python/FastAPI、Node.js/Express、Go/Gin 等

## 快速开始

### 前置要求

- Python 3.12+
- Node.js 18+（仅前端需要）
- Docker（Docker Compose 模式需要）
- k6（压测引擎，自动安装）

### 安装

```bash
# 1. 克隆项目
git clone https://github.com/your-username/BackendTestForge.git
cd BackendTestForge

# 2. 安装后端依赖
pip install -r backend/requirements.txt

# 3. 安装 k6
npm install -g k6

# 4. 安装前端依赖
cd frontend && npm install && cd ..
```

### 启动

```bash
# 终端1: 启动后端
python3 -m uvicorn backend.main:app --reload --port 8000

# 终端2: 启动前端
cd frontend && npx vite

# 浏览器打开 http://localhost:5173
```

### 配置 LLM API（可选，用于智能修复文档）

编辑 `backend/config.py` 或在环境变量中设置：

```bash
export LLM_PROVIDER=openai
export LLM_API_KEY=sk-xxx
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_MODEL=gpt-4o-mini
```

也支持兼容 OpenAI 格式的代理（如 MiniMax 的 ccswitch）：

```bash
export LLM_BASE_URL=https://api.minimaxi.com/anthropic
export LLM_API_KEY=your-minimax-token
export LLM_MODEL=MiniMax-M2.7
```

不带 LLM API Key 也能正常工作（使用基于模板的修复文档）。

## 使用方法

### 1. 创建测试任务

浏览器打开 `http://localhost:5173` → 填写：
- **任务名称**：给这个测试取个名字
- **项目路径**：被测后端的绝对路径（如 `/home/user/my-project/backend`）
- **启动模式**：
  - `direct` — 自动检测并启动
  - `docker_compose` — 查找 `docker-compose.yml` 并启动
  - `manual` — 你自行启动后提供 URL

### 2. 执行测试

点击"Start Execution" → 系统自动执行：

```
parse_code  →  run_load_test  →  build_report
  │               │                │
  分析代码        阶梯压测         生成报告
  提取路由        k6 引擎         修复文档
  识别技术栈      拐点检测         综合评分
```

### 3. 查看结果

- **代码分析**：技术栈、API 路由列表、关键文件清单
- **压测结果**：QPS、P50/P95/P99 延迟、最大安全并发
- **曲线图**：并发数 vs QPS/P99 的 ECharts 图表
- **修复文档**：Markdown 格式，可下载后发给 AI 进行优化

## 架构

```
┌──────────────────────────────────────────────┐
│  Frontend (Vue 3 + Element Plus + ECharts)   │
│  TaskCreate → TaskProgress → TaskReport      │
│              ↕ WebSocket + HTTP polling       │
├──────────────────────────────────────────────┤
│  Backend (FastAPI + SQLAlchemy + SQLite)      │
│                                               │
│  ┌────────────────────────────────────────┐   │
│  │  LangGraph Orchestrator                 │   │
│  │  parse_code → run_load_test →          │   │
│  │    → build_report                      │   │
│  └────────────────────────────────────────┘   │
│                                               │
│  Agents (决策层)     Services (执行层)        │
│  ┌──────────────┐   ┌──────────────────┐     │
│  │ CodeParser   │   │ ProjectManager   │     │
│  │ LoadTester   │   │ K6Runner         │     │
│  │ DocBuilder   │   │ LLMClient        │     │
│  └──────────────┘   └──────────────────┘     │
└──────────────────────────────────────────────┘
```

## 技术栈

| 层 | 技术 |
|----|------|
| 前端 | Vue 3 + Element Plus + ECharts |
| 后端 | FastAPI + SQLAlchemy (async) |
| 编排 | LangGraph (linear flow) |
| 压测 | k6 |
| 数据库 | SQLite |
| LLM | OpenAI 兼容 API（可切换） |

## 项目结构

```
BackendTestForge/
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置
│   ├── models.py            # SQLAlchemy 模型
│   ├── api/                 # API 路由
│   │   ├── task_routes.py
│   │   └── ws_manager.py
│   ├── agents/              # LangGraph Agent
│   │   ├── orchestrator.py
│   │   ├── code_parser.py
│   │   ├── load_tester.py
│   │   └── doc_builder.py
│   ├── services/            # 执行层
│   │   ├── project_manager.py
│   │   ├── k6_runner.py
│   │   └── llm_client.py
│   └── templates/k6/        # k6 脚本模板
├── frontend/                # Vue 3 前端
├── k6-scripts/              # 临时脚本
└── README.md
```

## API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/tasks | 创建任务 |
| GET | /api/tasks | 列出任务 |
| GET | /api/tasks/{id} | 查询任务详情 |
| POST | /api/tasks/{id}/run | 触发执行 |
| GET | /api/tasks/{id}/load-results | 获取压测结果 |
| PUT | /api/tasks/{id}/endpoints | 手动设置 API 端点 |
| WS | /api/ws/{task_id} | 实时进度推送 |
| GET | /api/health | 健康检查 |

## 后续规划

- 分布式压测（多节点 k6）
- 历史对比功能
- PDF 报告导出
- CI/CD 集成（GitHub Actions）
