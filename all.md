# BSH PPT 智能评分系统

> 详细内容见 [前端架构](./frontend.md) 与 [后端架构](./backend.md)。

---

## 项目简介

博西家电（BSH）研发团队定期举办内部技术分享会（Tech Talk），本系统供评委将演讲者的 **PPT 文件 + 演讲录音** 上传，由 AI 自动完成视觉解析、语音转录、多维度评分与 PDF 报告生成。

### 评分框架

**工程故事 5 步法**：起点（Trigger）→ 困境（Baseline）→ 破局（Solution）→ 成效（Proof）→ 升华（Takeaway）

**3 个评分维度（满分 100 分）**：

| 维度 | 名称       | 有音频满分 | 无音频满分 | 考察点                                 |
| ---- | ---------- | ---------- | ---------- | -------------------------------------- |
| A    | 结构与逻辑 | 45         | 50         | 5步法覆盖度、逻辑连贯性、结论闭环      |
| B    | 内容与价值 | 45         | 50         | 数据硬度、业务相关性、跨界友好度       |
| C    | 语言与呈现 | 10         | —         | 时间把控、语速流畅度（仅有音频时评分） |

**等级划分**：A（≥90）/ B（≥75）/ C（≥60）/ D（<60）

---

## 系统架构总览

```
浏览器（React + Vite）
    │  开发模式：http://localhost:5174
    │  生产模式：http://localhost:18766（后端直接 serve 前端静态文件）
    │
    ▼ REST API + SSE
FastAPI 后端（Python 3.11，port 18766）
    │
    ├── qwen-vl-plus（阿里云 DashScope）   视觉解析 PPT 页面
    ├── AssemblyAI / faster-whisper        语音转录
    └── qwen3-max（阿里云 DashScope）      LLM 多维度评分
         │
PostgreSQL 16（Docker）
    宿主机 port 5433 → 容器内 5432
 
```

---

## 目录结构

```
Z:\pycharm\PPT\
├── backend/              # FastAPI 后端（详见 docs/backend.md）
├── frontend-react/       # React 前端（详见 docs/frontend.md）
├── docker-compose.yml    # PostgreSQL 容器配置
├── docs/
│   ├── README.md         # 本文件
│   ├── frontend.md       # 前端架构文档
│   └── backend.md        # 后端架构文档
├── start.sh              # Linux 一键启动脚本
└── project_brief.md      # 产品需求文档
```

---

## 快速启动

### 前置要求

- Python 3.11（推荐 conda 管理）
- Node.js 18+
- Docker

### 启动步骤

```powershell
# 1. 启动 PostgreSQL 容器
cd 
docker compose up -d

# 2. 启动后端
conda activate PPT
cd Z:\pycharm\PPT\backend
python main.py

# 3. 启动前端（开发模式）
cd Z:\pycharm\PPT\frontend-react
npm install   # 首次需要
npm run dev
```

访问 **http://localhost:5174**（开发）或 **http://localhost:18766**（生产模式，需先 `npm run build`）

### 默认管理员账号

| 账号  | 密码  |
| ----- | ----- |
| admin | admin |

> **生产环境部署前请立即修改管理员密码！**

---

## 用户与权限

| 角色      | 权限                                                        |
| --------- | ----------------------------------------------------------- |
| `user`  | 上传文件、查看自己的评分历史、下载 PDF 报告                 |
| `admin` | 以上所有 + 查看所有用户历史、用户管理、提示词编辑、LLM 设置 |

内网免密登录：配置 `INTRANET_CIDRS` 环境变量后，来自该网段的请求自动以普通用户身份登录（适合内网演示）。
