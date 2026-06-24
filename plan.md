
---

## To-Do List：企业级高并发改造

### Phase 1 — 基础设施（必须先做）

- [ ] **引入 Redis**：docker-compose 加 Redis 服务，安装 `redis-py`、`celery[redis]`
- [ ] **引入 Celery**：创建 `backend/tasks/` 目录，配置 `celery_app`（broker/backend 均指向 Redis）
- [ ] **FastAPI 改为异步提交**：`POST /api/analyze` 立即返回 `task_id`（202），不再同步等待
- [ ] **进度查询接口**：`GET /api/task/{task_id}/stream` SSE 推送，读 Redis 中的 `task:{id}` hash，替代现有 `_progress` 全局字典

### Phase 2 — 三段任务队列拆分（核心）

- [ ] **VL 段任务**（`vl_tasks` 队列）：负责 ①②③A，完成后 chord 触发下一段
- [ ] **Audio 段任务**（`audio_tasks` 队列）：负责 ③B，与 VL 段并行，完成后汇合
- [ ] **LLM 段任务**（`llm_tasks` 队列）：负责 ④⑤⑥⑦⑧⑨，由 Celery chord 在 VL+Audio 都完成后自动触发
- [ ] **配置三个 Worker**：docker-compose 分别启动 `vl-worker`(concurrency=1)、`audio-worker`(concurrency=10)、`llm-worker`(concurrency=10)

### Phase 3 — 令牌桶限流

- [ ] 安装 `aiolimiter`
- [ ] `VL_LIMITER = AsyncLimiter(1, 1.0)`：VL 每次调用前 `async with VL_LIMITER`
- [ ] `LLM_LIMITER = AsyncLimiter(10, 1.0)`：LLM 每次调用前 `async with LLM_LIMITER`
- [ ] Audio 段无需限速（AssemblyAI 200并发远超使用量）

### Phase 4 — 幂等性保护

- [ ] **VL 分析**：Redis 记录已完成页码，重试时跳过已分析的页
- [ ] **报告生成**：检查 `outputs/report_{task_id}.pdf` 是否已存在
- [ ] **写库**：`ScoringRecord` 以 `task_id` 为唯一键，`INSERT IF NOT EXISTS`

### Phase 5 — 熔断 + 降级切换

- [ ] 安装 `pybreaker`
- [ ] **VL 熔断器**：失败 5 次触发 → 自动切换到备用 VL API（GPT-4o-mini 或其他）
- [ ] **LLM 熔断器**：失败 5 次触发 → 自动切换到 qwen-turbo
- [ ] **AssemblyAI 熔断器**：失败 3 次触发 → 读取 `.env` 中 `WHISPER_MODEL`，自动切本地 faster-whisper（接口已有，补熔断触发逻辑）
- [ ] `.env` 补充备用 API Key 配置项

### Phase 6 — 接入层背压 + Nginx

- [ ] FastAPI 接入层：队列深度 > 200 返回 503，响应体带 `queue_position` 和预计等待时间
- [ ] Nginx 配置：上传接口每 IP 限 1 req/s，全局 5 req/s，SSE 长连接关闭 `proxy_buffering`

### Phase 7 — 监控

- [ ] 部署 Flower（Celery 任务监控面板），加 Basic Auth
- [ ] 关键告警：VL 队列深度 > 50、任务失败率 > 5%、熔断器状态变为 OPEN

---

**当前已完成**：asyncio Semaphore(1) 全局锁、`_progress` 进度推送、`task_acks_late` 配置、AssemblyAI/Whisper 手动切换。Phase 1 是解锁后续所有步骤的前提，建议从 Redis + Celery 开始。
