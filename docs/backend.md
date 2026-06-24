# 后端架构文档

---

## 目录

1. [技术栈](#1-技术栈)
2. [目录结构](#2-目录结构)
3. [应用入口与中间件](#3-应用入口与中间件)
4. [数据库层](#4-数据库层)
5. [认证与权限](#5-认证与权限)
6. [路由层](#6-路由层)
7. [服务层](#7-服务层)
8. [AI 评分完整流程](#8-ai-评分完整流程)
9. [提示词管理](#9-提示词管理)
10. [环境变量说明](#10-环境变量说明)
11. [数据库连接与初始化](#11-数据库连接与初始化)
12. [日志与调试](#12-日志与调试)
13. [首次部署步骤](#13-首次部署步骤)
14. [二次开发要点](#14-二次开发要点)

---

## 1. 技术栈

| 依赖              | 版本      | 用途                    |
| ----------------- | --------- | ----------------------- |
| FastAPI           | 0.136     | Web 框架                |
| Uvicorn           | 0.45      | ASGI 服务器，端口 18766 |
| SQLAlchemy        | 2.0       | ORM（异步模式）         |
| asyncpg           | 0.31      | PostgreSQL 异步驱动     |
| PostgreSQL        | 16        | 数据库（Docker 容器）   |
| python-jose       | 3.5       | JWT 签发与验证          |
| passlib + bcrypt  | 1.7 / 5.0 | 密码哈希                |
| PyMuPDF           | 1.27      | PDF → PNG 截图         |
| reportlab         | 4.4       | 生成 PDF 评分报告       |
| faster-whisper    | 1.2       | 本地语音转录（可选）    |
| requests / httpx  | —        | 调用外部 AI API         |
| python-dotenv     | 1.2       | 加载 `.env` 配置      |
| pydantic-settings | 2.14      | 配置管理                |
| aiofiles          | 25.1      | 异步文件读写            |
| loguru            | 0.7       | 日志                    |

---

## 2. 目录结构

```
backend/
├── main.py                   # 应用入口：路由挂载、CORS、静态文件、启动事件
├── .env                      # 环境变量（含 API Key，勿提交 Git）
├── .env.example              # 环境变量模板
├── requirements.txt          # Python 依赖列表
├── llm_settings.json         # LLM 模型配置（运行时可改，无需重启）
├── scoring_config.json       # 各维度满分配置（运行时可改，无需重启）
│
├── core/
│   ├── deps.py               # Depends 注入：get_current_user / require_admin
│   └── security.py           # JWT create_access_token / decode_token
│
├── db/
│   ├── database.py           # 引擎创建、AsyncSession、init_db()
│   └── models.py             # ORM 模型：User / ScoringRecord / LLMReasoning
│
├── models/
│   └── schemas.py            # Pydantic 响应模型（AnalysisResult 等）
│
├── routers/
│   ├── auth.py               # /api/auth/* 认证路由
│   ├── history.py            # /api/history/* 个人历史
│   └── admin.py              # /api/admin/* 管理后台（需 admin 角色）
│
├── services/
│   ├── pdf_analyzer.py       # PDF 解析 + qwen-vl-plus 视觉分析
│   ├── audio_processor.py    # 语音转录（AssemblyAI 或 faster-whisper）
│   ├── scoring_service.py    # LLM 分类 + 3维度并行评分 + 汇总
│   └── report_generator.py   # 用 reportlab 生成 PDF 评分报告
│
├── prompts/                  # LLM 提示词（Markdown 文件）
│   ├── llm_classify.md           # PPT 类型分类
│   ├── llm_classify.default.md   # 上述的出厂默认版（用于"恢复默认"）
│   ├── dimA_narrative.md         # 维度A：结构与逻辑
│   ├── dimA_narrative.default.md
│   ├── dimB_solution.md          # 维度B：内容与价值
│   ├── dimB_solution.default.md
│   ├── dimC_elevation.md         # 维度C：语言与呈现
│   ├── dimC_elevation.default.md
│   ├── llm_summary.md            # 汇总评委
│   ├── llm_summary.default.md
│   └── vl_slide_analysis.md      # 视觉模型逐页分析
│
├── uploads/                  # 上传的 PPT / PDF / 音频文件（需定期清理）
├── outputs/                  # 生成的 PDF 报告
└── llm_logs/                 # LLM 调用日志（按日期+角色分文件）
```

---

## 3. 应用入口与中间件

**`main.py`** 是应用入口，主要职责：

### CORS 配置

默认允许的来源（本地开发端口 5173/5174/18766），额外来源通过环境变量 `CORS_ORIGINS`（逗号分隔）追加：

```python
allowed_origins = [
    "http://localhost:5173", "http://localhost:5174", "http://localhost:18766", ...
]
# + env CORS_ORIGINS 中的地址
```

### 路由挂载

```python
app.include_router(auth_router)     # /api/auth/*
app.include_router(history_router)  # /api/history/*
app.include_router(admin_router)    # /api/admin/*
```

核心 `/api/analyze` 接口直接定义在 `main.py` 中（因为涉及 SSE 流式响应，不适合放路由文件）。

### 静态文件

```python
app.mount("/", StaticFiles(directory="../frontend-react/dist", html=True))
```

生产模式下后端直接 serve 前端构建产物，无需单独运行前端服务器。

### 启动事件

```python
@app.on_event("startup")
async def startup():
    await init_db()   # 自动建表 + 创建默认 admin 账号
```

> 注：`on_event` 已废弃，将来应迁移到 `lifespan` 写法，目前不影响功能。

---

## 4. 数据库层

### 连接配置（`db/database.py`）

```python
DATABASE_URL = os.environ["DATABASE_URL"]
# 示例：postgresql+asyncpg://ppt_user:ppt_pass_2026@localhost:5433/ppt_scoring

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)
```

通过 FastAPI Depends 注入 Session：

```python
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
```

### ORM 模型（`db/models.py`）

**`User`** — 用户账号

| 字段          | 类型                 | 说明         |
| ------------- | -------------------- | ------------ |
| id            | UUID (PK)            | 主键         |
| username      | VARCHAR(64)          | 唯一，有索引 |
| email         | VARCHAR(128)         | 唯一，有索引 |
| password_hash | VARCHAR(256)         | bcrypt 哈希  |
| role          | ENUM('user','admin') | 角色         |
| is_active     | BOOLEAN              | 是否启用     |
| created_at    | TIMESTAMPTZ          | 创建时间     |

**`ScoringRecord`** — 评分记录

| 字段           | 类型             | 说明               |
| -------------- | ---------------- | ------------------ |
| id             | UUID (PK)        | 主键               |
| user_id        | UUID (FK→users) | 所属用户           |
| filename       | VARCHAR(256)     | 原始 PPT 文件名    |
| audio_filename | VARCHAR(256)     | 音频文件名（可空） |
| has_audio      | BOOLEAN          | 是否有音频         |
| total_score    | FLOAT            | 总分               |
| grade          | VARCHAR(8)       | 等级（A/B/C/D）    |
| score_data     | JSONB            | 完整评分结果 JSON  |
| pdf_path       | TEXT             | PDF 报告相对路径   |
| created_at     | TIMESTAMPTZ      | 创建时间           |

**`LLMReasoning`** — LLM 思维链记录

| 字段           | 类型                       | 说明                                                                            |
| -------------- | -------------------------- | ------------------------------------------------------------------------------- |
| id             | UUID (PK)                  | 主键                                                                            |
| record_id      | UUID (FK→scoring_records) | 关联评分记录，级联删除                                                          |
| role           | VARCHAR(64)                | LLM 角色（classify/narrative_setup/solution_results/elevation_fluency/summary） |
| reasoning_text | TEXT                       | thinking 模式输出的推理过程                                                     |
| created_at     | TIMESTAMPTZ                | 创建时间                                                                        |

### 数据库初始化（`init_db()`）

每次启动时执行，幂等：

1. `Base.metadata.create_all` — 根据 ORM 模型建表（已存在则跳过）
2. `ALTER TABLE scoring_records ADD COLUMN IF NOT EXISTS audio_filename` — 兼容旧数据库（无此列时自动加）
3. `CREATE TABLE IF NOT EXISTS llm_reasoning` — 兼容旧数据库
4. `CREATE INDEX IF NOT EXISTS ix_llm_reasoning_record_id` — 建索引
5. 查询是否存在 username=`admin` 的用户，不存在则创建（密码 `admin`，role=`admin`）

> **重要**：asyncpg 不支持单个 `execute()` 中含多条 SQL，每条 SQL 必须用独立的 `engine.begin()` 上下文块执行。

---

## 5. 认证与权限

### JWT 流程

1. 用户 POST `/api/auth/login`（OAuth2 Password 表单格式）
2. 后端验证密码后，`create_access_token({"sub": str(user.id)})` 签发 JWT
3. 客户端在后续请求头携带 `Authorization: Bearer <token>`
4. `get_current_user` Depends 解析 token → 查数据库 → 返回 User 对象

### Depends 注入链

```python
# 普通登录用户
get_current_user(token, db) -> User

# 管理员
require_admin(current_user: User = Depends(get_current_user)) -> User
# role != 'admin' 时抛出 403

# 可选用户（未登录也不报错，用于内网免密）
get_optional_user(token, db) -> User | None
```

### 内网免密登录

`auth.py` 的登录接口会检测请求来源 IP 是否在 `INTRANET_CIDRS` 配置的网段内，命中则自动创建/登录一个普通用户，无需密码。

---

## 6. 路由层

### `/api/auth/*`（`routers/auth.py`）

| 方法 | 路径                   | 说明                                                |
| ---- | ---------------------- | --------------------------------------------------- |
| POST | `/api/auth/register` | 注册，返回 Token + 用户信息                         |
| POST | `/api/auth/login`    | 登录（OAuth2 Password 格式），返回 Token + 用户信息 |
| GET  | `/api/auth/me`       | 获取当前用户信息（需 token）                        |

### `/api/history/*`（`routers/history.py`）

| 方法   | 路径                  | 权限 | 说明                             |
| ------ | --------------------- | ---- | -------------------------------- |
| GET    | `/api/history`      | user | 当前用户历史列表                 |
| GET    | `/api/history/{id}` | user | 单条记录详情（含 LLM reasoning） |
| DELETE | `/api/history/{id}` | user | 删除自己的一条记录               |

### `/api/admin/*`（`routers/admin.py`）

所有接口需 `admin` 角色。

| 方法 | 路径                               | 说明                                         |
| ---- | ---------------------------------- | -------------------------------------------- |
| GET  | `/api/admin/history`             | 所有用户历史（分页）                         |
| GET  | `/api/admin/users`               | 用户列表                                     |
| POST | `/api/admin/users/{id}/role`     | 修改用户角色                                 |
| POST | `/api/admin/users/{id}/active`   | 启用/禁用用户                                |
| GET  | `/api/admin/prompts`             | 获取所有提示词内容                           |
| PUT  | `/api/admin/prompts/{key}`       | 更新提示词（写入 `.md` 文件）              |
| POST | `/api/admin/prompts/{key}/reset` | 恢复提示词为默认（复制 `.default.md`）     |
| GET  | `/api/admin/llm-settings`        | 获取 LLM 设置                                |
| PUT  | `/api/admin/llm-settings`        | 更新 LLM 设置（写入 `llm_settings.json`）  |
| GET  | `/api/admin/scoring-config`      | 获取评分配置                                 |
| PUT  | `/api/admin/scoring-config`      | 更新评分配置（写入 `scoring_config.json`） |

### 核心接口（`main.py` 直接定义）

| 方法 | 路径                    | 说明                                            |
| ---- | ----------------------- | ----------------------------------------------- |
| POST | `/api/analyze`        | 上传 PPT + 音频，触发 AI 分析，SSE 流式返回进度 |
| GET  | `/outputs/{filename}` | 下载 PDF 报告（静态文件）                       |

---

## 7. 服务层

### `pdf_analyzer.py` — PDF 解析与视觉分析

1. 收到 PPT/PPTX 文件 → 调用 **LibreOffice headless** 转换为 PDF（直接上传 PDF 则跳过此步）
2. 用 **PyMuPDF** 将 PDF 每页渲染为 PNG 图片（分辨率适中，压缩后传输）
3. 对每张图片调用 **qwen-vl-plus**（阿里云 DashScope），最多 5 页并发，提取文字内容、图表描述、页面结构
4. 汇总所有页面的分析结果，返回结构化文本

> LibreOffice 需单独安装，Windows 上确保 `soffice` 命令可用。

### `audio_processor.py` — 语音转录

根据 `USE_ASSEMBLYAI_API` 环境变量选择转录方式：

**AssemblyAI 云端（现采用方式）**：

- 上传音频到 AssemblyAI，等待转录完成
- 支持中文，返回带词级时间戳的转录结果
- 需要 `ASSEMBLYAI_API_KEY`

**本地 faster-whisper**：

- 使用 `WHISPER_MODEL` 指定的模型（默认 `large-v3`，约 3GB）
- 首次使用需下载模型
- 有 GPU 时推理速度可接受，纯 CPU 下较慢
- 中文场景建议使用 `large-v3`

转录结果包含：完整文本 + 语速估算 + 停顿/口头禅频率分析。

### `scoring_service.py` — LLM 评分

**第一步：分类**

调用 `llm_classify.md` 提示词，让 LLM 将 PPT 归类为 4 种类型之一：

- `innovation`（产品创新型）
- `problem_solving`（问题解决型）
- `cost_reduction`（降本增效型）
- `methodology`（方法工具改进型）

PPT 类型会注入到后续各维度评分提示词中，实现差异化评分侧重。

**第二步：3 维度并行评分**

使用 `asyncio.gather` 并发调用 3 个 LLM（均为 qwen3-max）：

| 维度         | 提示词文件            | 有音频满分 | 无音频满分 |
| ------------ | --------------------- | ---------- | ---------- |
| A 结构与逻辑 | `dimA_narrative.md` | 45         | 50         |
| B 内容与价值 | `dimB_solution.md`  | 45         | 50         |
| C 语言与呈现 | `dimC_elevation.md` | 10         | —         |

每个 LLM 返回：分项得分 + 详细评语 + reasoning 链（thinking 模式开启时）。

**第三步：汇总**

调用 `llm_summary.md` 提示词，基于三个维度的评分结果生成：

- `strengths`（优点列表）
- `weaknesses`（不足列表）
- `suggestions`（改进建议列表）
- `summary`（综合评语）

**LLM 设置**（`llm_settings.json`，可在管理后台实时修改）：

```json
{
  "model": "qwen3-max",       // 可选：qwen3-max / qwen-long
  "enable_thinking": true      // 开启 qwen3 深度思考模式（质量更高，耗时更长）
}
```

### `report_generator.py` — PDF 报告生成

使用 **reportlab** 库生成包含以下内容的 PDF：

- 封面（项目标题、演讲者信息、日期）
- 总分与等级
- 各维度得分及子维度明细
- 优点 / 不足 / 改进建议
- AI 综合评语

生成的 PDF 保存在 `backend/outputs/` 目录，文件名含评分记录 ID。

---

## 8. AI 评分完整流程

```
POST /api/analyze（multipart/form-data: file + audio）
    │
    ├─ 参数验证（文件格式、大小）
    ├─ 保存上传文件到 uploads/
    │
    ▼ SSE 流式推送进度给前端
    │
    ① pdf_analyzer.PDFAnalyzer.analyze(ppt_file)
    │   ├─ .pptx/.ppt → LibreOffice → PDF
    │   ├─ PDF → PyMuPDF → PNG 列表
    │   └─ PNG 列表 → qwen-vl-plus（并发≤5）→ 页面内容文本
    │
    ② audio_processor.AudioProcessor.transcribe(audio_file)  [可选，有音频时执行]
    │   └─ AssemblyAI API 或 faster-whisper → 转录文本 + 语速指标
    │
    ③ scoring_service.ScoringService.score(ppt_content, transcript)
    │   ├─ 分类 LLM → ppt_type
    │   ├─ asyncio.gather(维度A LLM, 维度B LLM, 维度C LLM)
    │   └─ 汇总 LLM → strengths/weaknesses/suggestions/summary
    │
    ④ report_generator.ReportGenerator.generate(scoring_result)
    │   └─ reportlab → PDF 文件 → 保存到 outputs/
    │
    ⑤ 写数据库
    │   ├─ INSERT scoring_records（总分、等级、score_data JSON、pdf_path）
    │   └─ INSERT llm_reasoning（各角色的 reasoning_text，thinking 模式开启时）
    │
    ⑥ SSE 推送最终结果 → 前端展示评分卡片
```

---

## 9. 提示词管理

提示词文件存放在 `backend/prompts/`，每个提示词有两个版本：

| 文件               | 说明                                                                 |
| ------------------ | -------------------------------------------------------------------- |
| `xxx.md`         | 当前生效版本（管理后台可编辑，修改后立即生效）                       |
| `xxx.default.md` | 出厂默认版本（只读，管理后台"恢复默认"时将 `xxx.md` 替换为此内容） |

| 提示词 key   | 文件                  | 用途              |
| ------------ | --------------------- | ----------------- |
| `classify` | `llm_classify.md`   | PPT 类型 4 分类   |
| `dimA`     | `dimA_narrative.md` | 维度A：结构与逻辑 |
| `dimB`     | `dimB_solution.md`  | 维度B：内容与价值 |
| `dimC`     | `dimC_elevation.md` | 维度C：语言与呈现 |
| `summary`  | `llm_summary.md`    | 汇总评委          |

`vl_slide_analysis.md`（视觉模型分析提示词）目前未暴露给管理后台编辑，需直接修改文件。

---

## 10. 环境变量说明

文件：`backend/.env`（参考 `backend/.env.example`）

| 变量名                 | 必填     | 说明                             | 当前值                                                                     |
| ---------------------- | -------- | -------------------------------- | -------------------------------------------------------------------------- |
| `DATABASE_URL`       | ✅       | PostgreSQL asyncpg 连接串        | `postgresql+asyncpg://ppt_user:ppt_pass_2026@localhost:5433/ppt_scoring` |
| `VL_MODEL_API_KEY`   | ✅       | 阿里云 DashScope Key（视觉模型） | —                                                                         |
| `VL_MODEL_ENDPOINT`  | —       | VL API 地址                      | 阿里云默认                                                                 |
| `VL_MODEL_NAME`      | —       | VL 模型名                        | `qwen-vl-plus`                                                           |
| `LLM_API_KEY`        | ✅       | 阿里云 DashScope Key（评分 LLM） | 与上同 Key 即可                                                            |
| `LLM_API_ENDPOINT`   | —       | LLM API 地址                     | 阿里云默认                                                                 |
| `LLM_MODEL`          | —       | 默认 LLM 模型                    | `qwen3-max`                                                              |
| `USE_ASSEMBLYAI_API` | —       | 是否用 AssemblyAI 转录           | `true`                                                                   |
| `ASSEMBLYAI_API_KEY` | 条件必填 | AssemblyAI Key                   | —                                                                         |
| `WHISPER_MODEL`      | —       | 本地 Whisper 模型大小            | `large-v3`                                                               |
| `INTRANET_CIDRS`     | —       | 内网 IP 段，命中自动免密登录     | `10.0.0.0/8,192.168.0.0/16` 等                                           |
| `HOST`               | —       | 监听地址                         | `0.0.0.0`                                                                |
| `PORT`               | —       | 监听端口                         | `18766`                                                                  |
| `JWT_SECRET`         | —       | JWT 签名密钥                     | **生产环境务必修改**                                                 |
| `JWT_EXPIRE_MINUTES` | —       | JWT 有效期（分钟）               | `480`                                                                    |
| `UPLOAD_DIR`         | —       | 上传目录（相对 backend/）        | `uploads`                                                                |
| `OUTPUT_DIR`         | —       | 输出目录（相对 backend/）        | `outputs`                                                                |
| `CORS_ORIGINS`       | —       | 额外跨域来源（逗号分隔）         | —                                                                         |

---

## 11. 数据库连接与初始化

### Docker Compose 配置

```yaml
services:
  postgres:
    image: postgres:16
    container_name: ppt_postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: ppt_scoring
      POSTGRES_USER: ppt_user
      POSTGRES_PASSWORD: ppt_pass_2026
    ports:
      - "5433:5432"    # 宿主机 5433 → 容器 5432（避免与其他 PG 实例冲突）
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ppt_user -d ppt_scoring"]
      interval: 5s
      retries: 10
```

数据持久化在 Docker volume `postgres_data`，`docker compose down` 不会删除数据。

### 常用数据库操作命令

```powershell
# 启动容器
docker compose up -d

# 停止容器（数据保留）
docker compose stop

# 进入 psql 交互终端
docker exec -it ppt_postgres psql -U ppt_user -d ppt_scoring

# 查看所有表
\dt

# 查看用户列表
SELECT id, username, role, is_active FROM users;

# 修改管理员密码（在 psql 中无法直接改，需通过 API 或在 Python 中生成 bcrypt hash 后 UPDATE）
```

---

## 12. 日志与调试

### LLM 调用日志

每次 AI 调用后，`scoring_service.py` 的 `_llm_log()` 函数会将原始 LLM 输入输出追加到 `backend/llm_logs/` 下：

```
llm_logs/
├── 2026-04-22_classify_output.log
├── 2026-04-22_classify_reasoning.log
├── 2026-04-22_narrative_setup_output.log
├── 2026-04-22_narrative_setup_reasoning.log
├── ...
```

调试 LLM 输出格式问题时，先查这里的 `output.log`。

### 后端日志

```python
logging.basicConfig(level=logging.INFO)
```

服务启动信息、数据库初始化信息、错误栈都输出到 stdout。

---

## 13. 首次部署步骤

```powershell
# 1. 创建 conda 环境
conda create -n PPT python=3.11 -y
conda activate PPT

# 2. 安装依赖（直接用官方 PyPI，不用镜像站）
pip install -r requirements.txt

# 3. 配置环境变量
copy .env.example .env
# 编辑 .env，填写 API Key 和数据库连接串

# 4. 启动数据库
docker compose up -d

# 5. 启动后端
cd backend
python main.py
```

首次启动会自动建表并创建 `admin/admin` 账号。

---

## 14. 二次开发要点

### 新增 API 接口

1. 在 `routers/` 下对应文件添加路由函数（或新建文件）
2. 在 `main.py` 中 `include_router`
3. 用 `Depends(get_current_user)` 做认证，`Depends(require_admin)` 做鉴权

### 新增数据库表

1. 在 `db/models.py` 中定义新的 ORM 类，继承 `Base`
2. 重启后端，`init_db()` 会自动建表（`create_all` 幂等）
3. 若需修改已有表，在 `init_db()` 中添加 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`

### 修改评分维度

- 维度权重：修改 `scoring_config.json` 或在管理后台调整
- 评分逻辑：修改对应维度的 `prompts/dimX_xxx.md`
- 新增维度：需改 `scoring_service.py` 中的并行调用逻辑及 `scoring_config.json`

### 切换语音转录方案

- 环境变量 `USE_ASSEMBLYAI_API=false` 切换到本地 Whisper
- 修改 `audio_processor.py` 可对接其他 ASR API（如 OpenAI Whisper API）
