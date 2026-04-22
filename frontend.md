# 前端架构文档

---

## 目录

1. [技术栈](#1-技术栈)
2. [目录结构](#2-目录结构)
3. [路由设计](#3-路由设计)
4. [状态管理](#4-状态管理)
5. [API 层](#5-api-层)
6. [页面说明](#6-页面说明)
7. [开发环境启动](#7-开发环境启动)
8. [生产构建与部署](#8-生产构建与部署)
9. [代理配置说明](#9-代理配置说明)

---

## 1. 技术栈

| 依赖         | 版本 | 用途                                    |
| ------------ | ---- | --------------------------------------- |
| React        | 19   | UI 框架                                 |
| TypeScript   | ~6.0 | 类型安全                                |
| Vite         | 8    | 构建工具 + 开发服务器                   |
| Ant Design   | 6    | UI 组件库（表格、表单、上传、进度条等） |
| React Router | 7    | 客户端路由                              |
| Zustand      | 5    | 全局状态管理                            |
| axios        | 1.15 | HTTP 请求                               |
| dayjs        | 1.11 | 日期格式化                              |
| xlsx         | 0.18 | Excel 导出（管理员历史记录导出）        |

---

## 2. 目录结构

```
frontend-react/
├── src/
│   ├── main.tsx              # 应用入口，渲染 <App />
│   ├── App.tsx               # 路由总定义
│   ├── App.css / index.css   # 全局样式
│   ├── types.ts              # 全局 TypeScript 类型定义
│   │
│   ├── api/                  # HTTP 请求封装
│   │   ├── client.ts         # axios 实例（baseURL、JWT 拦截、401 跳转）
│   │   ├── auth.ts           # 认证相关接口（登录、注册、当前用户）
│   │   ├── history.ts        # 历史记录接口
│   │   └── admin.ts          # 管理后台接口（用户、提示词、LLM设置等）
│   │
│   ├── store/                # Zustand 全局状态
│   │   ├── authStore.ts      # 用户认证状态（token、user、login、logout）
│   │   ├── scoreStore.ts     # 评分任务状态（进度、结果）
│   │   └── batchStore.ts     # 批量评分状态
│   │
│   ├── components/           # 公共组件
│   │   ├── AppLayout.tsx     # 全局布局（导航菜单 + Outlet）
│   │   └── ProtectedRoute.tsx # 路由守卫（未登录跳登录页；requireAdmin 检查角色）
│   │
│   └── pages/                # 页面组件
│       ├── Login.tsx         # 登录页
│       ├── Register.tsx      # 注册页
│       ├── Score.tsx         # 单文件评分（核心页）
│       ├── BatchScore.tsx    # 批量评分
│       ├── History.tsx       # 个人历史记录
│       └── admin/
│           ├── AllHistory.tsx      # 管理员：所有记录 + Excel 导出
│           ├── UserManagement.tsx  # 管理员：用户启用/禁用、角色修改
│           ├── PromptEditor.tsx    # 管理员：提示词在线编辑
│           ├── ScoringConfig.tsx   # 管理员：各维度满分配置
│           └── LLMSettings.tsx     # 管理员：LLM 模型切换 + thinking 开关
│
├── public/                   # 静态资源
├── index.html                # HTML 模板
├── vite.config.ts            # Vite 配置（代理、端口、构建输出）
├── tsconfig.json             # TypeScript 配置
└── package.json
```

---

## 3. 路由设计

路由定义在 `src/App.tsx`，采用嵌套路由结构：

```
/login                      公开路由 - 登录页
/register                   公开路由 - 注册页

<ProtectedRoute>            需要登录（检查 authStore 中 token）
  <AppLayout>               全局导航布局
    /score                  单文件评分
    /batch                  批量评分
    /history                个人历史记录

    <ProtectedRoute requireAdmin>   需要 admin 角色
      /admin/history        所有用户历史
      /admin/users          用户管理
      /admin/prompts        提示词编辑
      /admin/llm-settings   LLM 设置
      /admin/scoring-config 评分配置

/* → 重定向到 /score
```

**路由守卫逻辑（`ProtectedRoute.tsx`）**：

- 未登录（无 token）→ 跳转 `/login`
- `requireAdmin=true` 且当前用户 role 不是 `admin` → 跳转 `/score`

---

## 4. 状态管理

使用 **Zustand** 管理全局状态，分三个 store：

### `authStore.ts` — 认证状态

```typescript
{
  token: string | null        // JWT token，持久化到 localStorage
  user: UserInfo | null       // 当前用户信息（id, username, role）
  login(token, user): void    // 登录：存 token + user
  logout(): void              // 登出：清空并跳转 /login
}
```

### `scoreStore.ts` — 单文件评分状态

存储当前评分任务的进度步骤、中间结果及最终评分结果，供 `Score.tsx` 页面读取并展示进度条和结果卡片。

### `batchStore.ts` — 批量评分状态

存储批量任务列表及各文件的评分状态。

---

## 5. API 层

所有 HTTP 请求通过 `src/api/client.ts` 的 axios 实例发出：

```typescript
// baseURL = '/api'，开发模式下由 Vite 代理到 http://localhost:18766
const client = axios.create({ baseURL: '/api', withCredentials: true })

// 请求拦截器：自动附加 JWT token
client.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 响应拦截器：401 时自动登出并跳转登录页
client.interceptors.response.use(res => res, err => {
  if (err.response?.status === 401) {
    useAuthStore.getState().logout()
    window.location.href = '/login'
  }
  return Promise.reject(err)
})
```

各模块 API 文件：

| 文件           | 主要函数                                                                                                                                          |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `auth.ts`    | `login()`, `register()`, `getMe()`                                                                                                          |
| `history.ts` | `getHistory()`, `getRecord()`, `deleteRecord()`                                                                                             |
| `admin.ts`   | `getAllHistory()`, `getUsers()`, `updateUserRole()`, `getPrompts()`, `updatePrompt()`, `getLLMSettings()`, `updateLLMSettings()` 等 |

### 评分接口（SSE 流式）

`Score.tsx` 中的评分进度通过 **Server-Sent Events（SSE）** 接收，使用原生 `EventSource` 或 `fetch` + `ReadableStream`，不通过 axios 发送，因为 SSE 需要保持长连接。

---

## 6. 页面说明

### `Score.tsx` — 单文件评分（核心页）

1. 用户选择 PPT/PDF 文件（必选）和音频文件（可选）
2. 点击"开始评分"，调用 `/api/analyze`（POST multipart/form-data）
3. 后端返回 SSE 流，前端实时更新进度步骤展示：
   - PDF 转换 → 视觉分析 → 语音转录 → 分类 → 维度A/B/C评分 → 汇总 → 生成报告
4. 分析完成后展示评分卡片：总分、等级、各维度分数、优点/不足/建议
5. 提供下载 PDF 报告按钮

### `History.tsx` — 个人历史记录

展示当前用户历史评分列表（表格），支持查看详情和下载 PDF 报告。

### `admin/AllHistory.tsx` — 管理员历史

展示所有用户的历史评分，支持按用户名/文件名筛选，支持导出 Excel（使用 xlsx 库）。

### `admin/PromptEditor.tsx` — 提示词在线编辑

从 `/api/admin/prompts` 获取所有提示词内容，在文本框中编辑后 PUT 保存。提供"恢复默认"按钮，调用 `/api/admin/prompts/{key}/reset`。

### `admin/LLMSettings.tsx` — LLM 设置

- 切换模型：`qwen3-max` / `qwen-long`
- 开关 `enable_thinking`（qwen3 的深度思考模式，开启后评分质量更高但耗时更长）

---

## 7. 开发环境启动

```powershell
cd PPT\frontend-react

# 首次安装依赖
npm install

# 启动开发服务器（端口 5174）
npm run dev
```

访问 **http://localhost:5174**

> 开发模式下所有 `/api/*` 请求由 Vite 代理转发到后端 `http://localhost:18766`，无需配置跨域。

---

## 8. 生产构建与部署

```powershell
cd Z:\pycharm\PPT\frontend-react
npm run build
```

构建产物输出到 `frontend-react/dist/`。

后端 `main.py` 已配置将 `dist/` 目录作为静态文件服务，访问 `http://localhost:18766` 即可使用完整应用，**无需单独运行前端服务器**。

```python
# main.py 中的静态文件挂载（已有配置）
app.mount("/", StaticFiles(directory="../frontend-react/dist", html=True), name="static")
```

---

## 9. 代理配置说明

`vite.config.ts` 中的代理配置：

```typescript
server: {
  port: 5174,
  proxy: {
    '/api': {
      target: 'http://localhost:18766',
      changeOrigin: true,
      timeout: 0,        // 不超时（analyze 接口耗时数分钟）
      proxyTimeout: 0,
    },
  },
}
```

**注意**：`timeout: 0` 和 `proxyTimeout: 0` 是必要的，否则 AI 分析过程中（几分钟）会被代理超时断开。
