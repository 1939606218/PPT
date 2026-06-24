# BSH PPT 智能评分系统 — 工作交接文档

> 本文档面向接手该项目的开发人员，详细描述系统架构、环境搭建、日常运维及二次开发要点。

---

## 目录

1. [项目背景](#1-项目背景)
2. [系统架构](#2-系统架构)
3. [目录结构](#3-目录结构)
4. [技术栈](#4-技术栈)
5. [环境准备与首次启动](#5-环境准备与首次启动)
6. [日常启动与停止](#6-日常启动与停止)
7. [环境变量说明](#7-环境变量说明)
8. [数据库说明](#8-数据库说明)
9. [API 接口概览](#9-api-接口概览)
10. [前端页面说明](#10-前端页面说明)
11. [AI 评分逻辑](#11-ai-评分逻辑)
12. [提示词管理](#12-提示词管理)
13. [用户与权限](#13-用户与权限)
14. [常见问题与排错](#14-常见问题与排错)
15. [已知问题与待办事项](#15-已知问题与待办事项)

---

## 1. 项目背景

**项目名称**：BSH PPT 智能打分助手（BSH AI Presentation Scorer）

博西家电（BSH）研发团队定期举办内部技术分享会（Tech Talk），评委将演讲者的 **PPT 文件 + 演讲录音** 上传至本系统，由 AI 自动完成视觉解析、语音转录、多维度评分与 PDF 报告生成。

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

## 2. 系统架构

```
浏览器 (React + Vite)
    │  http://localhost:5174  （开发模式）
    │  http://localhost:18766 （生产模式，后端直接 serve 前端静态文件）
    │
    ▼ REST API + SSE
FastAPI 后端 (Python 3.11)
    │  port 18766
    ├─ /api/auth/*        认证（登录/注册/Token刷新）
    ├─ /api/history/*     个人历史记录
    ├─ /api/admin/*       管理后台（历史/用户/提示词/LLM设置）
    ├─ /api/analyze       核心：上传PPT+音频 → 触发AI分析流程
    └─ /outputs/*         PDF报告静态文件服务
         │
         ├─── qwen-vl-plus (阿里云 DashScope)  视觉解析PPT页面
         ├─── AssemblyAI / faster-whisper       语音转录
         └─── qwen3-max (阿里云 DashScope)      LLM 多维度评分
              │
PostgreSQL 16 (Docker)
    port 5433（宿主机）→ 5432（容器内）
    容器名: ppt_postgres
```

---

## 3. 目录结构

```
Z:\pycharm\PPT\
├── backend/                    # FastAPI 后端
│   ├── main.py                 # 应用入口，路由挂载，静态文件服务
│   ├── .env                    # 环境变量（包含 API Key，勿提交 Git）
│   ├── .env.example            # 环境变量模板
│   ├── requirements.txt        # Python 依赖
│   ├── llm_settings.json       # LLM 模型设置（可在管理后台修改）
│   ├── scoring_config.json     # 各维度满分配置（可在管理后台修改）
│   ├── core/
│   │   ├── deps.py             # FastAPI Depends：get_current_user / require_admin
│   │   └── security.py         # JWT 签发与验证
│   ├── db/
│   │   ├── database.py         # 数据库引擎、Session、init_db()
│   │   └── models.py           # ORM 模型：User / ScoringRecord / LLMReasoning
│   ├── models/
│   │   └── schemas.py          # Pydantic 响应模型
│   ├── routers/
│   │   ├── auth.py             # 注册/登录/当前用户
│   │   ├── history.py          # 个人历史记录
│   │   └── admin.py            # 管理后台路由
│   ├── services/
│   │   ├── pdf_analyzer.py     # PDF→PNG + 调用 qwen-vl-plus 分析每页
│   │   ├── audio_processor.py  # 音频转录（AssemblyAI 或 faster-whisper）
│   │   ├── scoring_service.py  # LLM 分类 + 3维度并行评分 + 汇总
│   │   └── report_generator.py # 生成 PDF 评分报告（reportlab）
│   ├── prompts/                # LLM 提示词文件（可在管理后台在线编辑）
│   │   ├── llm_classify.md         # PPT 类型分类提示词
│   │   ├── llm_classify.default.md # 上述提示词的出厂默认版本
│   │   ├── dimA_narrative.md       # 维度A评分提示词
│   │   ├── dimB_solution.md        # 维度B评分提示词
│   │   ├── dimC_elevation.md       # 维度C评分提示词
│   │   ├── llm_summary.md          # 汇总评语提示词
│   │   └── vl_slide_analysis.md    # 视觉模型逐页分析提示词
│   ├── uploads/                # 上传文件临时存储（PPT/PDF/音频）
│   ├── outputs/                # 生成的 PDF 报告存储
│   └── llm_logs/               # LLM 调用日志（按日期+角色分文件）
│
├── frontend-react/             # React 前端
│   ├── src/
│   │   ├── main.tsx            # 应用入口
│   │   ├── App.tsx             # 路由定义
│   │   ├── pages/
│   │   │   ├── Login.tsx       # 登录页
│   │   │   ├── Register.tsx    # 注册页
│   │   │   ├── Score.tsx       # 单文件评分（核心页面）
│   │   │   ├── BatchScore.tsx  # 批量评分
│   │   │   ├── History.tsx     # 个人历史记录
│   │   │   └── admin/
│   │   │       ├── AllHistory.tsx      # 管理员：所有记录
│   │   │       ├── UserManagement.tsx  # 管理员：用户管理
│   │   │       ├── PromptEditor.tsx    # 管理员：提示词在线编辑
│   │   │       ├── ScoringConfig.tsx   # 管理员：评分配置
│   │   │       └── LLMSettings.tsx     # 管理员：LLM模型设置
│   │   ├── api/                # axios 请求封装
│   │   ├── store/              # Zustand 全局状态（用户信息等）
│   │   └── types.ts            # TypeScript 类型定义
│   ├── vite.config.ts          # Vite 配置（开发代理到后端 18766）
│   └── package.json
│
├── docker-compose.yml          # PostgreSQL 数据库容器配置
├── start.sh                    # Linux 一键启动脚本（Windows 不用）
└── project_brief.md            # 产品需求文档
```

---

## 4. 技术栈

| 层次         | 技术              | 版本  | 说明                             |
| ------------ | ----------------- | ----- | -------------------------------- |
| 前端框架     | React             | 19    | + TypeScript                     |
| 前端构建     | Vite              | 8     | 开发 dev server 端口 5174        |
| UI 组件库    | Ant Design        | 6     |                                  |
| 前端状态管理 | Zustand           | 5     |                                  |
| 前端路由     | React Router      | 7     |                                  |
| 后端框架     | FastAPI           | 0.136 | Python 3.11                      |
| ASGI 服务器  | Uvicorn           | 0.45  | 端口 18766                       |
| ORM          | SQLAlchemy        | 2.0   | 异步模式（asyncpg）              |
| 数据库驱动   | asyncpg           | 0.31  |                                  |
| 数据库       | PostgreSQL        | 16    | Docker 容器                      |
| 认证         | JWT (python-jose) | —    | 有效期 480 分钟                  |
| 密码加密     | bcrypt (passlib)  | —    |                                  |
| PDF 解析     | PyMuPDF           | 1.27  | PDF→PNG 截图                    |
| PDF 生成     | reportlab         | 4.4   | 评分报告                         |
| 视觉 AI      | qwen-vl-plus      | —    | 阿里云 DashScope                 |
| 语音转录     | AssemblyAI API    | —    | 云端，可切换本地 Whisper         |
| 本地 Whisper | faster-whisper    | 1.2   | large-v3 模型（需 GPU 效果最佳） |
| 评分 LLM     | qwen3-max         | —    | 阿里云 DashScope，支持 thinking  |

---

## 5. 环境准备与首次启动

### 5.1 前置要求

- **Python 3.11**（推荐使用 conda 管理）
- **Node.js 18+**
- **Docker Desktop**（用于运行 PostgreSQL）
- **网络**：需能访问 Docker Hub（拉取 postgres:16 镜像）及阿里云 DashScope API

### 5.2 克隆项目

```powershell
git clone <仓库地址> Z:\pycharm\PPT
cd Z:\pycharm\PPT
```

### 5.3 启动数据库（Docker）

```powershell
# 在项目根目录执行
docker compose up -d
```

这会启动 `ppt_postgres` 容器，PostgreSQL 监听宿主机 **5433** 端口。

验证容器运行：

```powershell
docker ps | Select-String ppt_postgres
```

### 5.4 配置后端环境变量

```powershell
cd backend
copy .env.example .env
# 然后编辑 .env，填写以下关键参数（见第 7 节）
```

**必填项**：

- `DATABASE_URL`
- `VL_MODEL_API_KEY`（阿里云 DashScope Key）
- `LLM_API_KEY`（同上，可用同一个 Key）
- `ASSEMBLYAI_API_KEY`（或将 `USE_ASSEMBLYAI_API` 改为 `false` 使用本地 Whisper）

### 5.5 创建 Python 环境并安装依赖

```powershell
conda create -n PPT python=3.11 -y
conda activate PPT
pip install -r requirements.txt
```

> **注意**：如果 pip 下载缓慢，不要使用清华镜像（部分包版本不全），直接从官方 PyPI 安装，搭配代理即可。

### 5.6 启动后端

```powershell
conda activate PPT
cd Z:\pycharm\PPT\backend
python main.py
```

首次启动时，`init_db()` 会自动建表并创建默认管理员账号：

- 账号：`admin`
- 密码：`admin`

**请在生产部署前修改管理员密码！**

看到以下输出表示启动成功：

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:18766 (Press CTRL+C to quit)
```

### 5.7 启动前端（开发模式）

```powershell
cd Z:\pycharm\PPT\frontend-react
npm install
npm run dev
```

前端开发服务器启动在 **http://localhost:5174**，已配置代理，所有 `/api/*` 请求自动转发到后端 18766 端口。

### 5.8 生产部署（前端打包）

```powershell
cd Z:\pycharm\PPT\frontend-react
npm run build
```

构建产物在 `frontend-react/dist/`，后端 `main.py` 已配置将其作为静态文件服务，直接访问 **http://localhost:18766** 即可使用完整应用，无需单独运行前端服务器。

---

## 6. 日常启动与停止

### 启动顺序

```powershell
# 1. 启动数据库（如果容器未运行）
cd Z:\pycharm\PPT
docker compose up -d

# 2. 启动后端
conda activate PPT
cd Z:\pycharm\PPT\backend
python main.py

# 3. 启动前端（仅开发时需要）
cd Z:\pycharm\PPT\frontend-react
npm run dev
```

### 停止

```powershell
# 停止后端：在后端终端按 Ctrl+C

# 停止数据库容器（数据不丢失，存在 Docker volume 中）
cd Z:\pycharm\PPT
docker compose stop

# 完全移除容器（数据保留在 volume 中）
docker compose down
```

### 查看数据库容器状态

```powershell
docker ps -a | Select-String ppt_postgres
docker logs ppt_postgres
```

---

## 7. 环境变量说明

文件位置：`backend/.env`

| 变量名                 | 必填     | 说明                                            | 示例值                                                                     |
| ---------------------- | -------- | ----------------------------------------------- | -------------------------------------------------------------------------- |
| `DATABASE_URL`       | ✅       | PostgreSQL 连接串（asyncpg 格式）               | `postgresql+asyncpg://ppt_user:ppt_pass_2026@localhost:5433/ppt_scoring` |
| `VL_MODEL_API_KEY`   | ✅       | 阿里云 DashScope API Key（视觉模型）            | `sk-xxxxxxxxxxxx`                                                        |
| `VL_MODEL_ENDPOINT`  | —       | VL 模型 API 地址                                | 默认阿里云地址                                                             |
| `VL_MODEL_NAME`      | —       | VL 模型名称                                     | `qwen-vl-plus`                                                           |
| `LLM_API_KEY`        | ✅       | 阿里云 DashScope API Key（LLM评分）             | `sk-xxxxxxxxxxxx`（与上面同一 Key 即可）                                 |
| `LLM_API_ENDPOINT`   | —       | LLM API 地址                                    | 默认阿里云地址                                                             |
| `LLM_MODEL`          | —       | 默认 LLM 模型                                   | `qwen3-max`                                                              |
| `USE_ASSEMBLYAI_API` | —       | 是否使用 AssemblyAI 云端转录                    | `true`                                                                   |
| `ASSEMBLYAI_API_KEY` | 条件必填 | AssemblyAI API Key                              | `xxxxxxxxxx`                                                             |
| `WHISPER_MODEL`      | —       | 本地 Whisper 模型大小（关闭 AssemblyAI 时生效） | `large-v3`                                                               |
| `INTRANET_CIDRS`     | —       | 内网 IP 段（命中则免密自动登录）                | `10.0.0.0/8,192.168.0.0/16`                                              |
| `HOST`               | —       | 后端监听地址                                    | `0.0.0.0`                                                                |
| `PORT`               | —       | 后端监听端口                                    | `18766`                                                                  |
| `JWT_SECRET`         | —       | JWT 签名密钥（生产环境务必修改）                | 随机长字符串                                                               |
| `JWT_EXPIRE_MINUTES` | —       | JWT 有效期（分钟）                              | `480`                                                                    |
| `UPLOAD_DIR`         | —       | 上传文件目录（相对 backend/）                   | `uploads`                                                                |
| `OUTPUT_DIR`         | —       | 输出文件目录（相对 backend/）                   | `outputs`                                                                |
| `CORS_ORIGINS`       | —       | 额外允许的跨域来源（逗号分隔）                  | `http://192.168.1.100:18766`                                             |

---

## 8. 数据库说明

### 连接信息（docker-compose 默认）

| 参数       | 值            |
| ---------- | ------------- |
| 宿主机端口 | 5433          |
| 数据库名   | ppt_scoring   |
| 用户名     | ppt_user      |
| 密码       | ppt_pass_2026 |
| 容器名     | ppt_postgres  |

数据持久化在 Docker volume `ppt_postgres_data` 中，`docker compose down` 不会删除数据，只有 `docker compose down -v` 才会清除数据。

### 数据表

| 表名                | 说明                                                                                                   |
| ------------------- | ------------------------------------------------------------------------------------------------------ |
| `users`           | 用户账号（id, username, password_hash, role, is_active, created_at）                                   |
| `scoring_records` | 评分记录（id, user_id, filename, audio_filename, 各维度得分, total_score, grade, pdf路径, created_at） |
| `llm_reasoning`   | LLM 思维链日志（关联 scoring_record，存储每次调用的 reasoning_text）                                   |

### 表结构初始化

`init_db()` 在每次后端启动时自动执行，使用 SQLAlchemy `metadata.create_all` 建表（幂等操作，已存在则跳过）。无需手动执行 SQL 迁移脚本。

如果升级了 ORM 模型但表已存在旧结构，`init_db()` 中有 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 语句做兼容处理，目前覆盖 `audio_filename` 列和 `llm_reasoning` 表。

---

## 9. API 接口概览

所有接口前缀为 `/api`，认证接口返回 JWT Token，后续请求在 Header 中携带：

```
Authorization: Bearer <token>
```

### 认证（`/api/auth`）

| 方法 | 路径                   | 说明                                |
| ---- | ---------------------- | ----------------------------------- |
| POST | `/api/auth/register` | 注册（返回 Token）                  |
| POST | `/api/auth/login`    | 登录（OAuth2 表单格式，返回 Token） |
| GET  | `/api/auth/me`       | 获取当前用户信息                    |

### 核心功能（`main.py` 直接定义）

| 方法 | 路径                              | 说明                                              |
| ---- | --------------------------------- | ------------------------------------------------- |
| POST | `/api/analyze`                  | 上传 PPT + 音频，触发 AI 分析（SSE 流式返回进度） |
| GET  | `/api/analyze/status/{task_id}` | 查询分析任务状态                                  |
| GET  | `/outputs/{filename}`           | 下载 PDF 报告                                     |

### 历史记录（`/api/history`）

| 方法   | 路径                  | 说明                             |
| ------ | --------------------- | -------------------------------- |
| GET    | `/api/history`      | 当前用户的历史评分列表           |
| GET    | `/api/history/{id}` | 单条记录详情（含 LLM reasoning） |
| DELETE | `/api/history/{id}` | 删除一条记录（仅本人）           |

### 管理后台（`/api/admin`，需 admin 角色）

| 方法 | 路径                               | 说明                               |
| ---- | ---------------------------------- | ---------------------------------- |
| GET  | `/api/admin/history`             | 所有用户的历史记录                 |
| GET  | `/api/admin/users`               | 用户列表                           |
| POST | `/api/admin/users/{id}/role`     | 修改用户角色                       |
| POST | `/api/admin/users/{id}/active`   | 启用/禁用用户                      |
| GET  | `/api/admin/prompts`             | 获取所有提示词                     |
| PUT  | `/api/admin/prompts/{key}`       | 更新某个提示词                     |
| POST | `/api/admin/prompts/{key}/reset` | 恢复提示词为默认值                 |
| GET  | `/api/admin/llm-settings`        | 获取 LLM 设置                      |
| PUT  | `/api/admin/llm-settings`        | 更新 LLM 设置（模型/thinking开关） |
| GET  | `/api/admin/scoring-config`      | 获取评分维度配置                   |
| PUT  | `/api/admin/scoring-config`      | 更新评分维度配置                   |

---

## 10. 前端页面说明

| 路径                      | 页面               | 说明                                                |
| ------------------------- | ------------------ | --------------------------------------------------- |
| `/login`                | 登录               | 用户名密码登录                                      |
| `/register`             | 注册               | 新用户注册                                          |
| `/score`                | 单文件评分         | 上传 PPT + 音频，实时显示分析进度，展示结果         |
| `/batch`                | 批量评分           | 批量上传多个 PPT 进行评分                           |
| `/history`              | 个人历史           | 查看自己的评分记录，可下载 PDF                      |
| `/admin/history`        | 管理员：全部历史   | 查看所有用户的评分，可导出 Excel                    |
| `/admin/users`          | 管理员：用户管理   | 查看/禁用用户，修改用户角色                         |
| `/admin/prompts`        | 管理员：提示词编辑 | 在线编辑 LLM 提示词，可恢复默认                     |
| `/admin/scoring-config` | 管理员：评分配置   | 调整各维度满分分值                                  |
| `/admin/llm-settings`   | 管理员：LLM设置    | 切换模型（qwen3-max/qwen-long），开关 thinking 模式 |

---

## 11. AI 评分逻辑

### 完整流程

```
上传 PPT + 音频（可选）
    │
    ▼
① PPT → PDF（若为 .pptx/.ppt 需要 LibreOffice，PDF 直接跳过）
    │
    ▼
② PDF → PNG 截图（PyMuPDF，每页一张）
    │
    ▼
③ 并行执行：
    ├─ 线路A：逐页调用 qwen-vl-plus 分析视觉内容（并发≤5页）
    └─ 线路B：音频转录（AssemblyAI API 或本地 faster-whisper）
    │
    ▼
④ 合并上下文（PPT文字+图表描述 + 演讲全文 + 语速/停顿指标）
    │
    ▼
⑤ 分类 LLM（qwen3-max）→ 判断 PPT 类型
    （innovation / problem_solving / cost_reduction / methodology）
    │
    ▼
⑥ 3个维度 LLM 并行评分（asyncio.gather）
    ├─ 维度A LLM：结构与逻辑（含 thinking 推理链）
    ├─ 维度B LLM：内容与价值（含 thinking 推理链）
    └─ 维度C LLM：语言与呈现（仅有音频时）
    │
    ▼
⑦ 汇总 LLM → 生成 strengths / weaknesses / suggestions / summary
    │
    ▼
⑧ 生成 PDF 报告（reportlab）
    │
    ▼
⑨ 入库（scoring_records + llm_reasoning）+ 返回结果给前端
```

### 关键配置文件

- **`backend/llm_settings.json`**：控制使用的 LLM 模型名称及是否开启 `enable_thinking`（qwen3 thinking 模式）。可通过管理后台实时修改，无需重启。
- **`backend/scoring_config.json`**：控制各维度的最高分值。可通过管理后台实时修改，无需重启。

### PPTX 转 PDF 依赖

系统依赖 **LibreOffice**（headless 模式）将 `.pptx/.ppt` 转换为 PDF，再截图分析。

- **Linux/Mac**：安装 `libreoffice` 并确保可在命令行执行 `libreoffice --headless`
- **Windows**：需安装 LibreOffice 并将其加入 `PATH`，或修改 `pdf_analyzer.py` 中的 LibreOffice 路径
- 若只上传 PDF 格式，则不需要 LibreOffice

---

## 12. 提示词管理

提示词文件位于 `backend/prompts/`，每个提示词有两个版本：

- `xxx.md`：当前使用的版本（可在管理后台编辑）
- `xxx.default.md`：出厂默认版本（管理后台"恢复默认"按钮会将 `xxx.md` 替换为此内容）

| 文件                     | 用途                         |
| ------------------------ | ---------------------------- |
| `llm_classify.md`      | 判断 PPT 类型（4分类）       |
| `dimA_narrative.md`    | 维度A：结构与逻辑评分        |
| `dimB_solution.md`     | 维度B：内容与价值评分        |
| `dimC_elevation.md`    | 维度C：语言与呈现评分        |
| `llm_summary.md`       | 汇总评委：生成优点/不足/建议 |
| `vl_slide_analysis.md` | 视觉模型：逐页分析每张幻灯片 |

提示词中可使用模板变量，评分前会由 `scoring_service.py` 动态注入内容（PPT 文字、音频转录、PPT 类型等）。

---

## 13. 用户与权限

系统有两种角色：

| 角色                 | 权限                                                           |
| -------------------- | -------------------------------------------------------------- |
| `user`（普通用户） | 上传文件、查看自己的评分历史、下载 PDF 报告                    |
| `admin`（管理员）  | 以上所有权限 + 查看所有用户历史、用户管理、提示词编辑、LLM设置 |

**默认管理员账号**：

- 用户名：`admin`
- 密码：`admin`
- **生产环境部署前请立即修改密码！**

**内网免密登录**：若配置了 `INTRANET_CIDRS`，来自该网段的请求会自动以普通用户身份登录，无需输入密码（适合内网演示环境）。

---

## 14. 常见问题与排错

### Q1: 后端启动报 `relation "users" does not exist`

**原因**：数据库中表尚未创建，通常是 PostgreSQL 容器未启动。

**解决**：

```powershell
docker compose up -d
# 等待容器健康检查通过后再启动后端
```

### Q2: `cannot insert multiple commands into a prepared statement`

**原因**：`asyncpg` 不支持在单个 `execute()` 中执行多条 SQL。

**解决**：`backend/db/database.py` 中已修复，每条 SQL 用独立的 `engine.begin()` 块执行。

### Q3: Docker 拉取镜像失败

**原因**：国内 Docker Hub 镜像站已基本停服，需要代理。

**解决**：

- 在 Docker Desktop → Settings → Proxies 中配置代理地址
- 如果代理软件（如 Clash）运行在 Windows 上，Docker 守护进程在 WSL2 中，需使用局域网 IP（如 `http://192.168.x.x:7890`），不能用 `localhost`

### Q4: `npm run dev` 后访问接口报 404

**原因**：前端代理配置（`vite.config.ts`）将 `/api` 代理到 `http://localhost:18766`，需确认后端正在运行。

### Q5: PPT 上传后分析卡在"转换 PDF"步骤

**原因**：需要 LibreOffice 处理 `.pptx` 文件，但系统未安装或路径未配置。

**解决**：

- Windows：[下载 LibreOffice](https://www.libreoffice.org/) 并安装，确保 `soffice` 可在命令行调用
- 或直接将 PPT 自行转为 PDF 再上传

### Q6: 语音转录很慢或失败

**原因**：

- `USE_ASSEMBLYAI_API=true` 时：检查 `ASSEMBLYAI_API_KEY` 是否有效
- `USE_ASSEMBLYAI_API=false` 时：本地 `faster-whisper large-v3` 首次运行需下载模型（约 3GB），且无 GPU 时推理很慢

**建议**：有稳定网络时使用 AssemblyAI；本地测试时可改用 `WHISPER_MODEL=medium` 加速。

### Q7: LLM 返回内容解析失败

**原因**：LLM 输出格式不符合预期（JSON 解析错误）。

**排查**：查看 `backend/llm_logs/` 目录下当天的日志文件，找到对应角色的 `output.log` 查看原始返回内容。

---

## 15. 已知问题与待办事项

- `main.py` 中使用了 FastAPI 已废弃的 `@app.on_event("startup")` 写法，建议迁移到 `lifespan` 方式（不影响功能，仅有 DeprecationWarning）
- LibreOffice 在 Windows 上的路径可能需要手动配置，建议封装为可配置的环境变量
- `uploads/` 目录中的文件不会自动清理，长期运行需定期清理或增加自动清理逻辑
- 批量评分页面（BatchScore.tsx）功能相对基础，可扩展为队列化异步任务
- 无数据库迁移工具（如 Alembic），结构变更依赖 `init_db()` 中的手动兼容代码，建议长期引入 Alembic

---

*文档生成时间：2026年4月22日*
