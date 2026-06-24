# PPT 评分系统 — 企业级高并发架构方案

> 适用场景：付费 API（qwen3-max 600 RPM / qwen-vl-plus-0710 60 RPM / AssemblyAI 200并发），日活用户 1000+
> 核心四板斧：**Redis 分布式令牌桶限流 + 任务队列（三段拆分）+ 幂等性 + 熔断降级**
>
> 📄 **推荐阅读 HTML 版本**：[enterprise-architecture.html](./enterprise-architecture.html) —— 带侧边栏目录导航、代码高亮、深色主题的完整排版

---

## 一、三个 API 的并发上限

| API                 | 用途               | 并发上限                               | 对应阶段 |
| ------------------- | ------------------ | -------------------------------------- | -------- |
| qwen-vl-plus-0710   | 逐页图像分析       | **60 RPM = 1 QPS** ← 全系统瓶颈 | ③-A     |
| qwen3-max           | 分类 + 评分 + 汇总 | 600 RPM = 10 QPS                       | ⑤⑥⑦   |
| AssemblyAI 异步转录 | 音频转文字         | **200 并发任务**（付费），非瓶颈 | ③-B     |

**VL 是唯一瓶颈**：一份 20 页 PPT 需要 20 次 VL 调用，在 1 QPS 下最少耗时 20 秒。
所有架构设计都以"不突破 VL 1 QPS"为约束条件展开。

---

## 二、为什么要把流水线拆成三段

**不拆分时**（当前架构，一个大任务）：

```
VL Worker (concurrency=1)

User A:  [①② 截图] [③A VL·VL·VL·VL·VL] [③B 音频] [④⑤⑥⑦ LLM] [⑧⑨ 报告入库]
User B:                                                               ← B 全程等待，VL Worker 空转
```

A 在跑 LLM 评分时，VL Worker 闲着，B 只能干等。

**拆分三段后**（推荐架构）：

```
VL Worker (concurrency=1)       Audio Worker          LLM Worker (concurrency=10)

User A:  [①② + ③A VL·VL·VL] ──完成──►               [④⑤⑥⑦⑧⑨ LLM评分报告入库]
                [③B 音频转录] ─────────────────────────►┘（两路汇合后触发LLM段）
User B:                   [①② + ③A VL·VL·VL] ──完成──►               [④⑤⑥⑦⑧⑨]
                          [③B 音频转录] ───────────────────────────────►┘
         ↑ A 的 VL 一结束，B 的 VL 立刻开始，互不等待 LLM 段
```

**三段之间用 Celery chord（扇出→汇合）连接**：

- **VL 段** 和 **Audio 段** 并行跑，都完成后自动触发 **LLM 段**
- 不同用户的 VL 段在同一个 `vl_tasks` 队列里排队，先到先得
- LLM 段因为 10 QPS 富裕，多用户的 LLM 段可以**真正并行**执行

---

## 三、整体架构图

```
用户浏览器
    │ HTTPS
    ▼
Nginx（接入限流：每IP上传 1 req/s，全局 API 5 req/s）
    │
    ▼
FastAPI 集群（无状态，2+ 实例）
  职责：接收文件 → 检查队列深度 → 写 Redis → 返回 task_id（202）
    │
    ▼
Redis
  ├── Celery Broker：三条任务队列（vl_tasks / audio_tasks / llm_tasks）
  └── task:{id}：进度 hash，TTL 24h
    │
    ├──────────────────────┬──────────────────────┐
    ▼                      ▼                      ▼
VL Worker              Audio Worker           LLM Worker
进程数: 1              进程数: 1              进程数: 1
并发数: 1              并发数: 10             并发数: 10
令牌桶: 1 req/s        令牌桶: 无需限速       令牌桶: 10 req/s
负责: ①②③A            负责: ③B              负责: ④⑤⑥⑦⑧⑨
    │                      │                      ▲
    └──────── chord ────────┘                      │
              （两段都完成后自动触发）──────────────┘
    │
    ▼
DashScope API（VL + LLM）  /  AssemblyAI API（音频）
    │
    ▼
PostgreSQL（主从：写主库，读从库）
```

---

## 四、Worker 配置表

| Worker       | 队列        | 进程数      | 并发数       | 令牌桶（Redis分布式） | 说明                             |
| ------------ | ----------- | ----------- | ------------ | --------------------- | -------------------------------- |
| VL Worker    | vl_tasks    | **1** | **1**  | 1 req/s               | 60 RPM 物理上限，加进程无意义    |
| Audio Worker | audio_tasks | **1** | **10** | 无                    | AssemblyAI 200并发，IO等待为主   |
| LLM Worker   | llm_tasks   | **1** | **10** | 10 req/s              | 600 RPM = 10 QPS，并发10正好打满 |

**LLM Worker 为什么并发 10、不是 3？**
高并发场景下，多个用户的 LLM 段同时执行。每个用户最多发 3 个并行评分请求（阶段⑥）。
3 个用户同时处于 LLM 段 = 最多 9 个并行请求，接近 10 QPS 上限。
设并发 10 正好把 10 QPS 配额打满，不浪费也不超限。

**LLM Worker 为什么只用 1 个进程？**
1 个进程 + concurrency=10（gevent 或 asyncio pool）已经能维持 10 路并发 API 调用。
LLM 调用是 IO 密集型，不是 CPU 密集型，不需要多进程。令牌桶已升级为 **Redis 分布式**，
若未来提额到 1200 RPM，只需改令牌桶 rate=20 + 加 LLM_WORKER_REPLICAS=2，
**无需重构代码**。

---

## 五、多用户并发执行时序（20页PPT举例）

```
时间轴 →  0s     20s          25s         45s
─────────────────────────────────────────────────────
User A:   [VL×20页 = 20s] [LLM⑤⑥⑦+报告 = 5s]
User B:          [VL×20页 = 20s]      [LLM⑤⑥⑦+报告 = 5s]
User C:                   [VL×20页 = 20s]      [LLM = 5s]

Audio A:  [AssemblyAI ≈5s]（与VL并行，不占VL Worker）
Audio B:          [AssemblyAI ≈5s]
```

- A 的 20 页 VL 跑完（20s），立刻释放 VL Worker → B 的 VL 立刻开始
- A 的 LLM 段和 B 的 VL 段**同时运行**，互不阻塞
- 音频转录在独立 Worker 并行执行，完全不占 VL 资源
- 总吞吐：每 20 秒可完成 1 个用户的 VL 分析（1 QPS 的物理上限决定的）

---

## 六、熔断 + 降级（API 故障时换备用 API）

熔断器状态：**正常（CLOSED）→ 连续失败 5 次 → 熔断（OPEN）→ 60s 后探测 → 恢复**

| 主 API       | 故障触发条件      | 降级方案（切备用 API）                                 | 最终兜底                             |
| ------------ | ----------------- | ------------------------------------------------------ | ------------------------------------ |
| qwen-vl-plus | 连续 5 次超时/5xx | 切换至**GPT-4o-mini**（视觉能力接近，更稳定）    | 跳过图像分析，仅用 PPT 文字内容评分  |
| qwen3-max    | 连续 5 次超时/5xx | 切换至**qwen-turbo**（速度更快，能力略低）       | 返回"评分服务暂时不可用，请稍后重试" |
| AssemblyAI   | 连续 3 次失败     | 切换至**本地 faster-whisper**（`.env` 已配置） | 跳过音频，进入纯 PPT 模式评分        |

> AssemblyAI 的降级你已经做了（`.env` 里有 `USE_ASSEMBLYAI_API=true/false` + `WHISPER_MODEL` 配置），只需加上熔断器自动触发切换，而不是手动改配置文件。

**降级不是"不做处理"，而是有序退化**：

```
qwen-vl-plus 挂了
    → 先切 GPT-4o-mini（用户无感知）
    → GPT-4o-mini 也挂了 → 跳过图像分析（用户感知：报告注明"图像分析不可用"）
```

---

## 七、幂等性（任务重试不重复执行）

`task_acks_late=True` 保证 Worker 崩溃时任务重回队列，但重试会重新执行所有步骤。
三个需要幂等保护的点：

| 步骤                  | 幂等方案                                                            |
| --------------------- | ------------------------------------------------------------------- |
| ③A VL 分析已完成的页 | Redis 中记录已完成页码，重试时跳过                                  |
| ⑧ 报告文件生成       | 检查 `outputs/report_{task_id}.pdf` 是否已存在，存在则跳过        |
| ⑨ 写库               | 以 `task_id` 为唯一键，`INSERT IF NOT EXISTS`，重复执行无副作用 |

---

## 八、队列背压 + 并行排队调度层（防止无限堆积）

VL 是 1 QPS 的物理串行瓶颈，但对用户侧不能暴露"串行"体验。
通过**调度层**对外提供"准并行"体验：

```
调度层架构：

  用户A ──► 提交 ──► vl_tasks 队列
  用户B ──► 提交 ──► vl_tasks 队列     ──► VL Worker (concurrency=1, 物理串行)
  用户C ──► 提交 ──► vl_tasks 队列
                          │
                    调度层（Celery + Redis）
                    ├── 优先级队列：vl_tasks_high / normal / batch
                    ├── 背压控制：超阈值拒绝 503
                    ├── 排队预估：返回 position + ETA
                    └── 可视化：前端轮询 queue_position
```

> **面试话术**：
> VL 是**资源受限的串行瓶颈**（API 硬限制 1 QPS），但我们通过
> **任务队列 + 优先级调度 + 排队预估 + 背压控制**，
> 对外提供"准并行"体验——多用户可同时提交、并行排队。
> 这是**真实商用 API 受限场景的标准解法**。

### 8.1 背压控制

```
接入层检查队列深度
    ├── vl_tasks 深度 < 200  → 正常接收，返回 202
    ├── vl_tasks 深度 200~500 → 接收但告警，前端显示"预计等待 X 分钟"
    └── vl_tasks 深度 > 500  → 拒绝，返回 503
```

### 8.2 排队预估（ETA）

等待时间估算：`预计等待 = queue_position × 平均每任务VL耗时（20页约20s）`

```python
# 接入层返回给前端，用于排队可视化
queue_depth = await redis.llen("celery:vl_tasks_high") \
            + await redis.llen("celery:vl_tasks_normal") \
            + await redis.llen("celery:vl_tasks_batch")

eta_seconds = queue_depth * 20  # 20s per task average
return {
    "task_id": task_id,
    "queue_position": queue_depth + 1,
    "estimated_wait_seconds": eta_seconds,
    "estimated_wait_display": f"约 {eta_seconds // 60} 分 {eta_seconds % 60} 秒",
}
```

前端根据 `queue_position` 和 `estimated_wait_display` 字段展示当前排队位置和预计等待时间。

### 8.3 三级优先级队列

| 队列            | 适用用户 | 说明                 |
| --------------- | -------- | -------------------- |
| vl_tasks_high   | VIP 用户 | 优先出队，插队执行   |
| vl_tasks_normal | 普通用户 | 先到先得             |
| vl_tasks_batch  | 批量任务 | 最低优先级，闲时执行 |

Worker 按优先级依次消费：先取 high，high 空再取 normal，normal 空再取 batch。

---

## 九、降级与扩容路径

```
当前（魔塔免费API）         →   Phase 2（付费API，日活<500）   →   Phase 3（规模化，日活1000+）
────────────────────            ──────────────────────────────     ──────────────────────────────
asyncio Semaphore(1)        →   Celery + 三段任务队列              同左 + Redis Cluster
单进程 FastAPI              →   2x FastAPI + Nginx              →   N x FastAPI + 云LB
Redis 分布式令牌桶（Lua）    →   同左                            →   同左（令牌桶无需变，只调 rate）
无熔断                      →   pybreaker + 备用API配置         →   同左 + 自动告警
手动 bash start.sh          →   Docker Compose                  →   Kubernetes HPA 自动扩缩
AssemblyAI（手动切换）       →   熔断器自动切 faster-whisper      →   同左
```

**VL Worker 永远只开 1 个进程**（除非阿里云给你更高的 VL 配额），这是 60 RPM 物理上限，不是架构限制。
扩容时只需：提额申请 → 改 Redis 令牌桶 rate → 加 VL Worker replicas，**无需重构代码**。

## 一、评分流水线全景

用户每次提交触发以下 9 个阶段，每个阶段的高并发策略不同：

```
用户上传 PPT + 音频（可选）
    │
    ▼ [FastAPI 接入层：立即返回 task_id，不等待]
    │
    ▼ ① PPT → PDF（LibreOffice，仅 .pptx/.ppt 需要；PDF 直接跳过）
    │         耗时：5~30s，CPU 密集，在 Celery Worker 进程内执行
    │
    ▼ ② PDF → PNG 截图（PyMuPDF，每页一张）
    │         耗时：1~5s，内存操作，Worker 内执行
    │
    ▼ ③ 并行执行（asyncio.gather）
    │    ├─ 线路A：逐页调用 qwen-vl-plus 分析视觉内容
    │    │         【瓶颈】60 RPM = 1 QPS，令牌桶严格限速
    │    │         并发上限：1 req/s（不能更快，否则 429）
    │    └─ 线路B：音频转录（AssemblyAI API 或 faster-whisper）
    │              无需限速，独立执行
    │
    ▼ ④ 合并上下文（PPT文字+图表描述 + 演讲全文 + 语速/停顿指标）
    │         纯内存操作，无 IO
    │
    ▼ ⑤ 分类 LLM（qwen3-max）→ 判断 PPT 类型
    │         1次 LLM 调用，令牌桶：10 QPS 池中取 1 个令牌
    │
    ▼ ⑥ 3个维度 LLM 并行评分（asyncio.gather）
    │    ├─ 维度A：结构与逻辑（含 thinking 推理链）
    │    ├─ 维度B：内容与价值（含 thinking 推理链）
    │    └─ 维度C：语言与呈现（仅有音频时）
    │         3次并行 LLM 调用，从 10 QPS 池同时取 3 个令牌
    │
    ▼ ⑦ 汇总 LLM → 生成 strengths/weaknesses/suggestions/summary
    │         1次 LLM 调用，取 1 个令牌
    │
    ▼ ⑧ 生成 PDF 报告（reportlab）
    │         CPU 密集，Worker 内执行，无 API 调用
    │
    ▼ ⑨ 入库（scoring_records + llm_reasoning）+ 通知前端
              写 PostgreSQL 主库，SSE 推送 status=done
```

**各阶段 API 调用汇总**：

| 阶段 | API                  | 调用次数             | 限速约束                       |
| ---- | -------------------- | -------------------- | ------------------------------ |
| ③-A | qwen-vl-plus         | N 次（N=幻灯片页数） | **60 RPM = 1 QPS**，瓶颈 |
| ③-B | AssemblyAI / Whisper | 1 次                 | 无需限速                       |
| ⑤   | qwen3-max            | 1 次                 | 600 RPM = 10 QPS               |
| ⑥   | qwen3-max            | 2~3 次（并行）       | 600 RPM，同时消耗 3 个令牌     |
| ⑦   | qwen3-max            | 1 次                 | 600 RPM                        |

> **结论**：**VL 分析（阶段③）是整个流水线的唯一瓶颈**。
> 一份 20 页 PPT 需要 20 次 VL 调用，在 1 QPS 下至少需要 20 秒。
> 所有高并发设计都以"不超过 VL 1 QPS"为约束条件展开。

---

## 二、整体架构图

```
用户浏览器
    │ HTTPS
    ▼
┌───────────────────────────────────────────┐
│  Nginx（反向代理 + 接入限流）              │
│  · 每 IP 上传限流：1 req/s                │
│  · 全局 API 限流：5 req/s                 │
└───────────────┬───────────────────────────┘
                │
    ┌───────────┴────────────┐
    │                        │
┌───▼──────────┐      ┌──────▼──────────┐
│ FastAPI 实例1 │      │ FastAPI 实例2   │   ← 无状态，可横向扩展
│ (薄接入层)   │      │ (薄接入层)      │     只做：接收文件→写Redis→返回task_id
└───────┬──────┘      └──────┬──────────┘
        └──────────┬──────────┘
                   │ 提交任务 / 查询进度
                   ▼
┌──────────────────────────────────────────┐
│              Redis                        │
│  DB 0: Celery Broker（任务队列）          │
│  DB 1: Celery Backend（任务结果）         │
│  DB 2: task:{id} 进度 hash               │
│  DB 3: Redis 分布式令牌桶（全局限流）         │
└──────────┬────────────────────┬──────────┘
           │                    │
           ▼                    ▼
┌──────────────────┐   ┌────────────────────────┐
│  VL Worker       │   │  LLM Worker             │
│  并发: 1         │   │  并发: 10                │
│  令牌桶: 1 req/s │   │  令牌桶: 10 req/s        │
│  队列: vl_tasks  │   │  队列: llm_tasks         │
│                  │   │                          │
│  处理阶段 ①②③A  │   │  处理阶段 ⑤⑥⑦           │
│  ③B④合并 ⑧⑨    │   │  (③B④在VL Worker内完成) │
└────────┬─────────┘   └──────────┬─────────────┘
         └──────────┬──────────────┘
                    ▼
┌──────────────────────────────────────────┐
│         阿里云 DashScope API              │
│  qwen-vl-plus-0710: 60 RPM  / 1 QPS     │
│  qwen3-max:        600 RPM  / 10 QPS    │
└──────────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────┐
│  PostgreSQL（主从复制）                   │
│  主库: 写（评分记录、推理日志）            │
│  从库: 读（历史查询、报表统计）            │
└──────────────────────────────────────────┘
```

---

## 三、核心四板斧实现

### 板斧一：令牌桶限流

**为什么是令牌桶，不是漏桶？**

| 算法             | 特点                                 | 问题                             |
| ---------------- | ------------------------------------ | -------------------------------- |
| 计数器           | 实现最简单                           | 临界时间点可能突刺 2 倍流量      |
| 漏桶             | 严格匀速输出                         | 不允许任何突发，吞吐率低         |
| **令牌桶** | **平均速率受控，允许适度突发** | **✅ 最适合 API 限速场景** |
| 滑动窗口         | 精确统计，无突刺                     | 实现复杂，内存占用高             |

令牌桶的关键优势：阶段⑥ 3个维度并行评分时，可以同时"取走"3个令牌（突发），
只要总速率不超过 10 QPS，API 不会拒绝。漏桶做不到这点。

> **核心约束：API 配额是主账号全局共享的**。
> qwen-vl-plus-0710 = 60 RPM = 1 QPS，qwen3-max = 600 RPM = 10 QPS。
> 即使当前只部署 1 个 Worker，未来扩容（提额到 120 RPM = 2 QPS → 2个VL Worker）时，
> 本地令牌桶各自独立、合计超速→429。因此**必须从一开始就用 Redis 分布式令牌桶**
> 保证全局不超 API 配额。

#### 方案：Redis 分布式令牌桶（Lua 脚本原子扣令牌）

```python
# backend/core/distributed_rate_limiter.py
import time
import asyncio
from redis.asyncio import Redis

LUA_ACQUIRE_TOKEN = """
-- KEYS[1]: 令牌桶的 Redis key，如 "rate_limit:vl"
-- ARGV[1]: 每秒产生令牌数 (rate)
-- ARGV[2]: 当前时间戳 (秒)
-- ARGV[3]: 请求令牌数 (默认 1)
-- 返回: 1=获取成功, 0=无可用令牌

local key        = KEYS[1]
local rate       = tonumber(ARGV[1])
local now        = tonumber(ARGV[2])
local requested  = tonumber(ARGV[3]) or 1
local window     = 1.0  -- 1秒滑动窗口

-- 读取上一次请求时间和剩余令牌
local last_time  = tonumber(redis.call('HGET', key, 'last_time') or now)
local tokens     = tonumber(redis.call('HGET', key, 'tokens') or rate)

-- 按时间流逝补充令牌（最多不超过 rate）
local elapsed = math.min(now - last_time, window)
tokens = math.min(rate, tokens + elapsed * rate)

-- 扣令牌
if tokens >= requested then
    tokens = tokens - requested
    redis.call('HSET', key, 'tokens', tokens, 'last_time', now)
    redis.call('EXPIRE', key, 3)  -- 3秒无请求自动清理
    return 1
else
    redis.call('HSET', key, 'last_time', now)
    redis.call('EXPIRE', key, 3)
    return 0
end
"""


class DistributedTokenBucket:
    """Redis 分布式令牌桶 —— 所有 Worker 共享同一配额，保证全局不超 API 上限"""
  
    def __init__(self, redis: Redis, key: str, rate: float):
        self.redis = redis
        self.key = key
        self.rate = rate
        # 预加载 Lua 脚本到 Redis，避免每次 eval 传脚本文本
        self._script = self.redis.register_script(LUA_ACQUIRE_TOKEN)

    async def acquire(self) -> bool:
        """尝试获取 1 个令牌，成功返回 True"""
        now = time.time()
        result = await self._script(
            keys=[self.key],
            args=[self.rate, now, 1],
        )
        return result == 1

    async def wait_and_acquire(self, poll_interval: float = 0.1):
        """阻塞等待直到获取令牌（用在 async with 中）"""
        while not await self.acquire():
            await asyncio.sleep(poll_interval)

    async def __aenter__(self):
        await self.wait_and_acquire()
        return self

    async def __aexit__(self, *args):
        pass  # 令牌已消费，无需归还


# ── 全局限流器（启动时初始化一次） ─────────────────────────────────

VL_RATE_LIMITER  = None   # 运行时注入: DistributedTokenBucket(redis, "rate_limit:vl", 1.0)
LLM_RATE_LIMITER = None   # 运行时注入: DistributedTokenBucket(redis, "rate_limit:llm", 10.0)


# ── 与评分流水线的对应关系 ─────────────────────────────────────────────────

async def analyze_slide_page(b64: str, prompt: str):
    """阶段③-A：每页 VL 分析，经过 Redis 分布式令牌桶（全局 1 QPS）"""
    async with VL_RATE_LIMITER:       # 超过 1/s 时自动等待，绝不报 429
        return await asyncio.to_thread(_call_vl_api, b64, prompt)


async def run_classify_llm(context: str):
    """阶段⑤：PPT 类型分类，1 次 LLM 调用"""
    async with LLM_RATE_LIMITER:
        return await asyncio.to_thread(_call_llm_api, context)


async def run_dimension_scoring(context: str, dim: str):
    """阶段⑥：单个维度评分，3 个并行调用各自竞争令牌桶（允许同时取 3 个令牌，突发）"""
    async with LLM_RATE_LIMITER:
        return await asyncio.to_thread(_call_llm_api, context, dim)


async def run_summary_llm(scores: dict):
    """阶段⑦：汇总评分，1 次 LLM 调用"""
    async with LLM_RATE_LIMITER:
        return await asyncio.to_thread(_call_llm_api, scores)
```

> **单 Worker 场景下的简化方案**：
> 如果确定长期只跑 1 个 VL Worker 和 1 个 LLM Worker（不扩容），可以用 `aiolimiter.AsyncLimiter`
> 本地令牌桶替代。但 Redis 分布式方案零额外运维成本（Redis 已在架构中），建议默认使用。

---

### 板斧二：任务队列

**你的系统是任务队列，不是消息队列**：

|                      | 任务队列（你的系统）                    | 消息队列（如Kafka）   |
| -------------------- | --------------------------------------- | --------------------- |
| 每条消息的消费者数量 | 1个（一个用户的任务只由一个Worker处理） | N个（多下游同时消费） |
| 结果归属             | 返回给提交任务的用户                    | 广播给所有订阅者      |
| 适用中间件           | Redis + Celery ✅                       | Kafka / RabbitMQ      |

**选型：Redis + Celery**。Redis 已在 docker-compose 中存在，零额外运维成本。

```python
# backend/tasks/pipeline.py
from celery import Celery

celery_app = Celery("ppt_scorer",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/1",
)
celery_app.conf.update(
    task_acks_late=True,             # Worker 崩溃时任务自动重回队列，不丢失
    task_reject_on_worker_lost=True,
    worker_max_tasks_per_child=50,   # 防内存泄漏：每处理50个任务后 Worker 子进程重启
    task_serializer="json",
)


@celery_app.task(bind=True, max_retries=3, queue="vl_tasks",
                 name="tasks.run_full_pipeline")
def run_full_pipeline(self, task_id: str, pdf_path: str, audio_path: str | None):
    """
    完整9步流水线入口。
    Celery Worker 是同步进程，内部用 asyncio.run() 驱动异步逻辑。
    """
    try:
        asyncio.run(_async_pipeline(task_id, pdf_path, audio_path))
    except RateLimitExceeded as exc:
        # 触发 API 限速（令牌桶应该避免此情况，但保留作为最后防线）
        raise self.retry(exc=exc, countdown=60)
    except Exception as exc:
        _set_task_state(task_id, status="error", message=str(exc)[:300])
        raise


async def _async_pipeline(task_id: str, pdf_path: str, audio_path: str | None):
    """9步流水线的异步实现"""

    # ① PPT → PDF
    _set_task_state(task_id, percent=5,  message="转换 PPT 格式...")
    pdf_path = await convert_to_pdf(pdf_path)

    # ② PDF → PNG
    _set_task_state(task_id, percent=10, message="提取幻灯片截图...")
    images_b64 = await extract_slides_as_images(pdf_path)
    total_pages = len(images_b64)

    # ③ 并行：VL分析 + 音频转录
    _set_task_state(task_id, percent=15, message=f"分析 {total_pages} 页幻灯片...")
    slides_task  = _analyze_all_slides(task_id, images_b64)
    audio_task   = _transcribe_audio(audio_path) if audio_path else asyncio.sleep(0, result=None)
    slides_result, transcript = await asyncio.gather(slides_task, audio_task)

    # ④ 合并上下文
    _set_task_state(task_id, percent=70, message="合并分析结果...")
    context = build_context(slides_result, transcript)

    # ⑤ 分类
    _set_task_state(task_id, percent=72, message="判断 PPT 类型...")
    ppt_type = await run_classify_llm(context)

    # ⑥ 3个维度并行评分
    _set_task_state(task_id, percent=75, message="多维度评分（含推理链）...")
    dim_a, dim_b, dim_c = await asyncio.gather(
        run_dimension_scoring(context, "structure"),
        run_dimension_scoring(context, "content"),
        run_dimension_scoring(context, "presentation") if audio_path else asyncio.sleep(0, result=None),
    )

    # ⑦ 汇总
    _set_task_state(task_id, percent=90, message="生成综合评语...")
    summary = await run_summary_llm({"dim_a": dim_a, "dim_b": dim_b, "dim_c": dim_c, "type": ppt_type})

    # ⑧ 生成 PDF 报告
    _set_task_state(task_id, percent=95, message="生成 PDF 报告...")
    report_path = await generate_pdf_report(dim_a, dim_b, dim_c, summary, task_id)

    # ⑨ 入库
    await save_scoring_record(task_id, dim_a, dim_b, dim_c, summary, report_path)
    _set_task_state(task_id, percent=100, status="done",
                    message="完成！", report_url=f"/api/task/{task_id}/report")


async def _analyze_all_slides(task_id: str, images_b64: list[str]):
    """阶段③-A：逐页 VL 分析，通过令牌桶严格限速到 1 req/s"""
    results = []
    for i, b64 in enumerate(images_b64):
        page_no = i + 1
        _set_task_state(task_id, message=f"VL分析第 {page_no}/{len(images_b64)} 页...")
        slide_info = await analyze_slide_page(b64, SLIDE_ANALYSIS_PROMPT)
        results.append(slide_info)
    return results
```

---

### 板斧三：幂等性

**场景**：Celery Worker 在阶段⑨写库后崩溃，任务因 `task_acks_late=True` 重回队列，
Worker 重新执行整个流水线，会不会重复写库、重复生成报告？

**解决方案**：以 `task_id`（UUID）为幂等键，每一步操作前先检查是否已存在：

```python
# ⑨ 入库时的幂等保护
async def save_scoring_record(task_id: str, ...):
    async with WriteSession() as db:
        # 先查，存在则跳过（重复执行不会重复写）
        existing = await db.execute(
            select(ScoringRecord).where(ScoringRecord.task_id == task_id)
        )
        if existing.scalar():
            logger.info(f"[{task_id}] 记录已存在，跳过写库（幂等）")
            return

        record = ScoringRecord(task_id=task_id, ...)
        db.add(record)
        await db.commit()


# ⑧ 生成报告时的幂等保护（避免重复生成大文件）
async def generate_pdf_report(task_id: str, ...):
    report_path = OUTPUT_DIR / f"report_{task_id}.pdf"
    if report_path.exists():
        logger.info(f"[{task_id}] 报告已存在，跳过生成（幂等）")
        return str(report_path)
    # ... 正常生成逻辑
```

**接入层的幂等**：相同的文件重复提交，每次生成不同的 `task_id`，不去重（每次提交都是合法的独立任务）。幂等保护只针对同一个 `task_id` 的重试。

---

### 板斧三增强：VL 单页缓存 + 断点续跑

> **动机**：VL 是串行瓶颈，20 页 PPT 需 20 秒。一旦 Worker 崩溃，已分析完的 19 页全部作废，必须从头重跑——浪费 API 配额且用户等待时间翻倍。

#### 断点续跑机制

利用 Redis 持久化每页 VL 结果，崩溃重启后自动跳过已完成页：

```
Redis Key 设计：
  task:{task_id}:pages          → Hash  {page_1: "{...VL结果JSON...}", page_2: "{...}"}
  task:{task_id}:pages_done     → Set   {1, 3, 5, 7, 9, 11}   ← 已完成的页码集合
  task:{task_id}:pages_total    → String "20"                  ← 总页数（用于前端进度条）
```

```python
# backend/tasks/vl_checkpoint.py

REDIS_PAGE_KEY    = "task:{task_id}:pages"         # Hash: 每页 VL 结果缓存
REDIS_DONE_KEY    = "task:{task_id}:pages_done"    # Set:  已完成页码


async def _analyze_all_slides_with_checkpoint(
    task_id: str, images_b64: list[str]
):
    """阶段③-A：逐页 VL 分析，支持断点续跑 + 单页缓存"""
    total_pages = len(images_b64)
    await redis.set(f"task:{task_id}:pages_total", total_pages)

    # 读取已完成的页码（崩溃恢复）
    done_pages = await redis.smembers(REDIS_DONE_KEY.format(task_id=task_id))
    done_set = {int(p) for p in done_pages} if done_pages else set()

    results = []
    for i, b64 in enumerate(images_b64):
        page_no = i + 1

        # 断点续跑：跳过已完成的页
        if page_no in done_set:
            cached = await redis.hget(
                REDIS_PAGE_KEY.format(task_id=task_id), f"page_{page_no}"
            )
            if cached:
                results.append(json.loads(cached))
                logger.info(f"[{task_id}] 跳过第{page_no}页（已缓存）")
                continue

        # 正常 VL 调用（经令牌桶限速）
        _set_task_state(task_id, message=f"VL分析第 {page_no}/{total_pages} 页...")
        slide_info = await analyze_slide_page(b64, SLIDE_ANALYSIS_PROMPT)

        # 写入 Redis 缓存（原子操作：先写结果，再标记完成）
        async with redis.pipeline() as pipe:
            pipe.hset(
                REDIS_PAGE_KEY.format(task_id=task_id),
                f"page_{page_no}",
                json.dumps(slide_info, ensure_ascii=False),
            )
            pipe.sadd(REDIS_DONE_KEY.format(task_id=task_id), str(page_no))
            pipe.expire(REDIS_PAGE_KEY.format(task_id=task_id), 86400)
            pipe.expire(REDIS_DONE_KEY.format(task_id=task_id), 86400)
            await pipe.execute()

        results.append(slide_info)

    return results
```

#### 单页缓存（相同图片复用）

模板 PPT 的封面页、目录页、结尾页往往相同。缓存以 `(image_hash, prompt_hash)` 为 key，避免重复调用：

```python
# 图片 MD5 作为缓存 key
async def analyze_slide_page_cached(b64: str, prompt: str):
    img_hash = hashlib.md5(b64.encode()).hexdigest()
    prompt_hash = hashlib.md5(prompt.encode()).hexdigest()
    cache_key = f"vl_cache:{img_hash}:{prompt_hash}"

    cached = await redis.get(cache_key)
    if cached:
        logger.info("VL 缓存命中，跳过 API 调用")
        return json.loads(cached)

    result = await analyze_slide_page(b64, prompt)
    await redis.setex(cache_key, 3600 * 72, json.dumps(result, ensure_ascii=False))  # 3天过期
    return result
```

> **面试话术**：
> VL 串行 20 页，崩溃从头来是不可接受的。
> 我们通过 Redis 记录每页完成状态，Worker 重启后自动跳过已完成页，**从断点继续**。
> 同时缓存相同图片的 VL 结果（如模板封面页），减少重复 API 调用，**降低成本**。
> 这是真实生产环境中串行瓶颈任务的**标准容错方案**。

---

### 板斧四：熔断

**场景**：DashScope API 发生故障，每次调用都超时或报 5xx。
如果不熔断，所有任务都在等待超时，Worker 被卡死，队列积压爆炸。

**熔断器状态机**：

```
正常 (CLOSED)
    │ 连续失败 5 次
    ▼
熔断 (OPEN) ──── 60秒后 ──► 半开 (HALF-OPEN)
                                │ 探测请求成功
                                ▼
                            正常 (CLOSED)
```

```python
# backend/core/circuit_breaker.py
from pybreaker import CircuitBreaker, CircuitBreakerError

# VL API 熔断器（60 RPM 限制的 API 更容易触发问题）
vl_breaker = CircuitBreaker(
    fail_max=5,           # 连续失败 5 次触发熔断
    reset_timeout=60,     # 熔断 60 秒后进入半开状态
    name="vl_api",
)

# LLM API 熔断器
llm_breaker = CircuitBreaker(
    fail_max=10,          # LLM 更稳定，容错更高
    reset_timeout=30,
    name="llm_api",
)


# 在令牌桶之后、API调用之前加熔断保护
async def analyze_slide_page(b64: str, prompt: str):
    async with VL_RATE_LIMITER:                     # Redis 分布式令牌桶（全局 1 QPS）
        try:
            return await asyncio.to_thread(
                vl_breaker(_call_vl_api),           # 熔断器包装 API 调用
                b64, prompt
            )
        except CircuitBreakerError:
            # 熔断器打开：快速失败，不等待，立即返回降级结果
            logger.warning("VL API 熔断器打开，返回默认幻灯片信息")
            return _default_slide_info()            # 降级：返回空白占位数据，不阻塞整个任务


async def run_classify_llm(context: str):
    async with LLM_RATE_LIMITER:
        try:
            return await asyncio.to_thread(llm_breaker(_call_llm_api), context)
        except CircuitBreakerError:
            # 降级：无法分类时默认使用最通用的评分 prompt
            return "methodology"
```

**降级策略**（熔断打开时做什么，而不是报错）：

| 阶段        | 熔断降级策略                           |
| ----------- | -------------------------------------- |
| ③-A VL分析 | 返回默认幻灯片结构（仅用文字内容评分） |
| ⑤ 分类     | 默认返回 `methodology`（最通用类型） |
| ⑥ 维度评分 | 返回 0 分 + 提示"评分服务暂时不可用"   |
| ⑦ 汇总     | 返回模板化文本，跳过 LLM 生成          |

### 板斧四增强：多 Key / 多账号轮询（API 配额突破）

> **动机**：单账号 qwen-vl-plus-0710 只有 60 RPM = 1 QPS。团队协作时，
> 可用多个子账号的 API Key 做轮询，**总配额 = N × 60 RPM**，线性提升吞吐。

#### 轮询策略

```python
# backend/core/api_key_pool.py
import asyncio
from itertools import cycle
from typing import Optional

class APIKeyPool:
    """多 Key 轮询池，支持熔断标记和权重"""

    def __init__(self, keys: list[str]):
        self._keys = keys
        self._idx = 0
        self._lock = asyncio.Lock()
        # 标记被熔断/限流的 key，临时跳过
        self._disabled: dict[str, float] = {}  # key → 恢复时间戳

    async def get_key(self) -> Optional[str]:
        """Round-Robin 获取可用 Key，自动跳过故障 Key"""
        async with self._lock:
            now = time.time()
            # 清理已恢复的 key
            self._disabled = {k: v for k, v in self._disabled.items() if v > now}

            available = [k for k in self._keys if k not in self._disabled]
            if not available:
                # 全部不可用 → 触发最终降级
                logger.error("所有 API Key 不可用，进入全降级模式")
                return None

            key = available[self._idx % len(available)]
            self._idx = (self._idx + 1) % len(available)
            return key

    def disable_key(self, key: str, cooldown_seconds: int = 60):
        """标记 key 不可用（429 / 5xx 时调用），冷却后自动恢复"""
        self._disabled[key] = time.time() + cooldown_seconds
        logger.warning(f"API Key {key[:8]}... 已禁用，{cooldown_seconds}s 后恢复")


# ── 多模型降级链 ─────────────────────────────────────────────────

VL_FALLBACK_CHAIN = [
    {"model": "qwen-vl-plus-0710", "pool": APIKeyPool(keys_qwen_vl)},   # 主
    {"model": "gpt-4o-mini",        "pool": APIKeyPool(keys_openai)},   # 降级1
    {"model": "skip_image",         "pool": None},                       # 降级2：跳过图像
]

LLM_FALLBACK_CHAIN = [
    {"model": "qwen3-max",          "pool": APIKeyPool(keys_qwen_llm)},
    {"model": "qwen-turbo",         "pool": APIKeyPool(keys_qwen_llm)},
]
```

#### 多账号配置方式

```bash
# .env
# 主账号（必填）
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx

# 扩展账号（可选，用逗号分隔）
DASHSCOPE_EXTRA_KEYS=sk-yyyyyyyyyyyyyyyy,sk-zzzzzzzzzzzzzzzz

# 轮询开关
API_KEY_POOL_ENABLED=true
```

> **效果**：
>
> - 单账号 60 RPM → 3 个账号 = 180 RPM = 3 QPS → VL Worker 可扩展到 3 并发
> - 每个 key 独立熔断，一个被限流自动跳过
> - 面试加分项：体现**生产级容灾 + 资源弹性**意识

---

## 四、FastAPI 接入层（薄层设计）

接入层职责：**接收文件 → 检查队列 → 写 Redis → 返回 task_id**，绝不执行 LLM 调用。

```python
# backend/routers/analyze.py
MAX_QUEUE_SIZE = 200   # 全局排队上限，防止内存溢出

@router.post("/api/analyze", status_code=202)
async def submit_analyze(
    pdf_file: UploadFile = File(...),
    audio_file: UploadFile = File(None),
    current_user = Depends(get_optional_user),
):
    # 背压控制：队列满时拒绝新请求，而不是无限堆积
    queue_depth = await redis.llen("celery:vl_tasks")
    if queue_depth > MAX_QUEUE_SIZE:
        raise HTTPException(503, f"服务繁忙，当前排队 {queue_depth} 个任务，请稍后提交")

    task_id = str(uuid.uuid4())

    # 保存文件（本地磁盘或 OSS）
    pdf_path   = await save_upload(pdf_file,   task_id)
    audio_path = await save_upload(audio_file, task_id) if audio_file else None

    # 写入初始进度到 Redis（24小时过期）
    await redis.hset(f"task:{task_id}", mapping={
        "status": "queued", "percent": 0,
        "message": "排队等候中...",
        "pdf_filename": pdf_file.filename,
        "user_id": str(current_user.id) if current_user else "",
    })
    await redis.expire(f"task:{task_id}", 86400)

    # 根据用户等级选择队列（VIP 插队）
    queue = "vl_tasks_high" if getattr(current_user, "is_vip", False) else "vl_tasks_normal"
    run_full_pipeline.apply_async(
        args=[task_id, pdf_path, audio_path],
        queue=queue,
        task_id=task_id,
        expires=3600,     # 1小时内未被执行则丢弃（防积压）
    )

    return {
        "task_id": task_id,
        "queue_position": queue_depth + 1,
        "stream_url": f"/api/task/{task_id}/stream",
    }


@router.get("/api/task/{task_id}/stream")
async def task_progress_stream(task_id: str):
    """SSE 推送进度，替代同步轮询"""
    async def generator():
        while True:
            state = await redis.hgetall(f"task:{task_id}")
            if not state:
                yield f"data: {json.dumps({'status': 'expired'})}\n\n"
                break
            yield f"data: {json.dumps(state)}\n\n"
            if state.get("status") in ("done", "error"):
                break
            await asyncio.sleep(1.0)
    return EventSourceResponse(generator())
```

---

## 五、docker-compose.yml

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ppt_scoring
      POSTGRES_USER: ppt_user
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes: [postgres_data:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "ppt_user"]

  redis:
    image: redis:7-alpine
    command: redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru
    volumes: [redis_data:/data]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]

  api:
    build: ./backend
    command: uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
    ports: ["8000:8000"]
    environment:
      DATABASE_URL: postgresql+asyncpg://ppt_user:${DB_PASSWORD}@postgres:5432/ppt_scoring
      REDIS_URL: redis://redis:6379/0
      DASHSCOPE_API_KEY: ${DASHSCOPE_API_KEY}
    depends_on:
      postgres: {condition: service_healthy}
      redis:    {condition: service_healthy}
    deploy:
      replicas: 2

  # VL Worker：并发固定为 1（60 RPM 物理上限）
  # 扩容条件：阿里云提额到 120 RPM 以上 → 改 VL_WORKER_REPLICAS=2
  vl-worker:
    build: ./backend
    command: >
      celery -A tasks.pipeline worker
      --queues vl_tasks_high,vl_tasks_normal
      --concurrency ${VL_WORKER_CONCURRENCY:-1}
      --loglevel info
    environment:
      REDIS_URL: redis://redis:6379/0
      DASHSCOPE_API_KEY: ${DASHSCOPE_API_KEY}
    depends_on:
      redis: {condition: service_healthy}
    deploy:
      replicas: ${VL_WORKER_REPLICAS:-1}   # 默认 1；扩容需先提额+改Redis令牌桶rate

  # LLM Worker：并发 10（600 RPM = 10 QPS，正好打满配额）
  # 单进程 concurrency=10 已足够；配额提至 1200 RPM 可设 LLM_WORKER_REPLICAS=2
  llm-worker:
    build: ./backend
    command: >
      celery -A tasks.pipeline worker
      --queues llm_tasks
      --concurrency ${LLM_WORKER_CONCURRENCY:-10}
      --loglevel info
    environment:
      REDIS_URL: redis://redis:6379/0
      DASHSCOPE_API_KEY: ${DASHSCOPE_API_KEY}
    depends_on:
      redis: {condition: service_healthy}
    deploy:
      replicas: ${LLM_WORKER_REPLICAS:-1}   # 默认 1；扩 2 时令牌桶已是Redis分布式，无需改代码

  # Flower：Celery 任务监控面板（生产必备）
  flower:
    image: mher/flower:2.0
    command: celery flower --broker=redis://redis:6379/0 --port=5555
    ports: ["5555:5555"]
    environment:
      FLOWER_BASIC_AUTH: admin:${FLOWER_PASSWORD}
    depends_on: [redis]

  nginx:
    image: nginx:alpine
    ports: ["80:80", "443:443"]
    volumes:
      - ./nginx/ppt.conf:/etc/nginx/conf.d/default.conf
      - ./nginx/ssl:/etc/nginx/ssl
    depends_on: [api]

volumes:
  postgres_data:
  redis_data:
```

---

## 六、超时分层控制

每层设置独立超时，避免上游无限等待下游：

```
Nginx proxy_read_timeout:      10s   ← 只等接入层返回 task_id
FastAPI 文件保存 + 写Redis:     5s   ← 超时返回 503
Celery 整个任务 time_limit:   600s   ← 10分钟强杀，防死任务
  ├── ①② PPT转换+截图:        60s
  ├── ③-A 单页 VL 调用:        30s   ← httpx timeout=30
  ├── ③-B 音频转录:           120s
  ├── ⑤⑥⑦ 单次 LLM 调用:      60s   ← httpx timeout=60
  └── ⑧ 报告生成:              30s
```

---

## 七、监控关键指标

### 7.1 核心告警指标

| 指标                           | 告警阈值 | 说明                                              |
| ------------------------------ | -------- | ------------------------------------------------- |
| VL 队列深度 `vl_tasks`       | > 50     | 积压严重，VL 是瓶颈                               |
| LLM 队列深度 `llm_tasks`     | > 20     | LLM Worker 不足                                   |
| 任务失败率 `FAILURE / total` | > 5%     | API 或 Worker 故障                                |
| `api_429_count`（5分钟窗口） | > 0      | **触发 API 限速 429，令牌桶失效或配额超限** |
| VL 熔断器状态                  | OPEN     | DashScope VL API 故障                             |
| LLM 熔断器状态                 | OPEN     | DashScope LLM API 故障                            |
| 任务 p95 耗时（20页）          | > 5min   | 20页 PPT 正常上限                                 |
| Redis 内存使用                 | > 80%    | 需扩容或清理过期 key                              |

### 7.2 队列可视化（前端展示）

前端 SSE/轮询拉取以下字段，用户实时感知排队状态：

```python
# GET /api/task/{task_id}/queue-status 返回
{
    "task_id": "abc123",
    "queue_position": 12,                          # 当前排队位置
    "queue_total": 200,                            # 总排队数
    "estimated_wait_seconds": 240,                 # ETA: 约 4 分钟
    "estimated_wait_display": "约 4 分钟",          # 前端直接展示
    "vl_pages_done": 7,                            # 已分析页数（断点续跑进度）
    "vl_pages_total": 20                           # 总页数
}
```

前端展示效果：`"您前面还有 12 个任务，预计等待约 4 分钟。当前进度：7/20 页"`

### 7.3 429 告警与自动恢复

```python
# 自定义 Prometheus Counter
from prometheus_client import Counter

vl_429_counter = Counter("vl_api_429_total", "VL API 429 count", ["api_key"])
llm_429_counter = Counter("llm_api_429_total", "LLM API 429 count", ["api_key"])

# 每次收到 429 时递增，Grafana 设置告警：
#   rate(vl_api_429_total[5m]) > 0 → 钉钉/企微告警
#   说明令牌桶配置有误或 API 配额被其他应用抢占
```

> **面试话术**：
> 我们监控覆盖三层——**生产指标**（429/P95/失败率）、
> **SRE 告警**（队列深度/熔断状态/内存）、
> **用户体验**（排队预估/ETA/断点进度）。
> 监控体系从 Day 1 就搭建，**不是事后补的**。

---

## 八、扩容路径

```
当前（魔塔免费API）      →    Phase 2（付费API上线）    →    Phase 3（规模化）
────────────────────         ─────────────────────         ─────────────────
asyncio Semaphore(1)     →   Celery + aiolimiter 令牌桶 →   Redis 分布式令牌桶
单进程 FastAPI           →   2x FastAPI + Nginx          →   N x FastAPI + 云LB
本地 PostgreSQL          →   云 RDS 主从               →   分库分表
无监控                   →   Flower + Prometheus        →   Grafana + Jaeger 全链路
手动 bash start.sh       →   Docker Compose             →   Kubernetes HPA 自动扩缩
```

> **VL Worker 永远只开 1 个进程**（除非升级到更高配额的 API），
> 这是 60 RPM 物理上限决定的，不是架构限制。

---

## 一、为什么不用 Kafka？

先回答这个问题，避免过度设计。

| 中间件                         | 适合场景                                                   | 不适合场景                           |
| ------------------------------ | ---------------------------------------------------------- | ------------------------------------ |
| **Redis Queue (Celery)** | 任务数 < 百万/天，需要重试、状态追踪                       | 消息需永久保留、多消费者订阅同一消息 |
| **Kafka**                | 日志流、事件溯源、多下游消费者（如审计+计费+分析同时消费） | 简单任务队列，运维成本极高           |
| **RabbitMQ**             | 复杂路由、优先级队列、消息确认语义强                       | 超高吞吐、持久化日志流               |

**结论**：PPT 评分是典型"任务队列"场景，不是"事件流"场景。
Kafka 的运维成本（ZooKeeper/KRaft、分区管理、消费组偏移量）在这里得不偿失。
**选型：Redis + Celery**，这是 Django/FastAPI 生态最成熟的组合。

---

## 二、整体架构图

```
                        ┌─────────────────────────────────────────────┐
                        │               用户浏览器                     │
                        └──────────────┬──────────────────────────────┘
                                       │ HTTPS
                        ┌──────────────▼──────────────────────────────┐
                        │           Nginx (反向代理 + 限流)            │
                        │   limit_req_zone: 每 IP 5 req/s             │
                        └──────────────┬──────────────────────────────┘
                                       │
                   ┌───────────────────┼───────────────────┐
                   │                   │                   │
        ┌──────────▼─────────┐ ┌───────▼──────────┐ ┌─────▼──────────┐
        │  FastAPI 实例 1    │ │  FastAPI 实例 2   │ │ FastAPI 实例 N  │
        │  (无状态，薄接入层) │ │  (无状态，薄接入层)│ │               │
        └──────────┬─────────┘ └───────┬──────────┘ └─────┬──────────┘
                   └───────────────────┼───────────────────┘
                                       │ 提交任务 / 查询状态
                        ┌──────────────▼──────────────────────────────┐
                        │              Redis Cluster                   │
                        │  ├── DB 0: Celery Broker (任务队列)          │
                        │  ├── DB 1: Celery Backend (任务结果)         │
                        │  ├── DB 2: 任务进度 hash (task:{id})         │
                        │  └── DB 3: Redis 分布式令牌桶（全局限流）         │
                        └──────┬────────────────────┬─────────────────┘
                               │                    │
              ┌────────────────▼────┐    ┌──────────▼──────────────────┐
              │   VL Worker Pool    │    │    LLM Worker Pool           │
              │   并发数: 1          │    │    并发数: 10                 │
              │   令牌桶: 1 req/s    │    │    令牌桶: 10 req/s           │
              │   队列: vl_tasks    │    │    队列: llm_tasks            │
              └────────────────┬────┘    └──────────┬──────────────────┘
                               │                    │
                        ┌──────▼────────────────────▼─────────────────┐
                        │         阿里云 DashScope API                 │
                        │   qwen-vl-plus:  60 RPM  / 1 QPS            │
                        │   qwen3-max:    600 RPM  / 10 QPS            │
                        └─────────────────────────────────────────────┘
                               │
                        ┌──────▼──────────────────────────────────────┐
                        │           PostgreSQL (主从复制)               │
                        │   主库: 写操作 (评分记录、用户数据)            │
                        │   从库: 读操作 (历史查询、报表)               │
                        └─────────────────────────────────────────────┘
```

---

## 三、各层详细设计

### 3.1 Nginx 接入层

```nginx
# /etc/nginx/conf.d/ppt.conf

# 全局限流：每个 IP 每秒最多 5 个请求
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=5r/s;

# 上传专用限流（更严格，防止恶意大文件）
limit_req_zone $binary_remote_addr zone=upload_limit:10m rate=1r/s;

upstream fastapi_backends {
    least_conn;                          # 最少连接负载均衡
    server 127.0.0.1:8001 weight=1;
    server 127.0.0.1:8002 weight=1;
    keepalive 32;
}

server {
    listen 443 ssl;
    server_name your-domain.com;

    client_max_body_size 100M;           # 允许最大 100M 上传

    location /api/analyze {
        limit_req zone=upload_limit burst=2 nodelay;
        proxy_pass http://fastapi_backends;
        proxy_read_timeout 10s;          # 接入层只等 10 秒（已改为异步，立即返回）
    }

    location /api/task/ {
        limit_req zone=api_limit burst=10 nodelay;
        proxy_pass http://fastapi_backends;
        # SSE 长连接需要关闭缓冲
        proxy_buffering off;
        proxy_cache off;
    }

    location / {
        limit_req zone=api_limit burst=20 nodelay;
        proxy_pass http://fastapi_backends;
    }
}
```

---

### 3.2 FastAPI 接入层（薄层，无业务逻辑）

接入层只做三件事：**接收文件 → 写 Redis → 返回 task_id**，不执行任何 LLM 调用。

```python
# backend/routers/analyze.py

import uuid
import json
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from fastapi.responses import JSONResponse
from ..tasks.analyze import analyze_task
from ..core.redis_client import redis_client

router = APIRouter()

MAX_QUEUE_SIZE = 200  # 全局排队上限，超出直接拒绝

@router.post("/api/analyze", status_code=202)
async def submit_analyze(
    pdf_file: UploadFile = File(...),
    audio_file: UploadFile = File(None),
    current_user = Depends(get_optional_user),
):
    # 1. 检查全局队列深度，防止雪崩
    queue_depth = await redis_client.llen("celery:vl_tasks")
    if queue_depth > MAX_QUEUE_SIZE:
        raise HTTPException(
            status_code=503,
            detail=f"服务繁忙，当前排队 {queue_depth} 个任务，请稍后提交"
        )

    # 2. 保存上传文件到持久化存储（本地或 OSS）
    task_id = str(uuid.uuid4())
    pdf_path = await save_upload(pdf_file, task_id)
    audio_path = await save_upload(audio_file, task_id) if audio_file else None

    # 3. 写入任务初始状态到 Redis
    await redis_client.hset(f"task:{task_id}", mapping={
        "status": "queued",
        "percent": 0,
        "message": "排队等候中...",
        "user_id": str(current_user.id) if current_user else "",
        "pdf_filename": pdf_file.filename,
        "created_at": time.time(),
    })
    await redis_client.expire(f"task:{task_id}", 3600 * 24)  # 24小时过期

    # 4. 提交到 Celery（立即返回，不等待）
    analyze_task.apply_async(
        args=[task_id, pdf_path, audio_path],
        queue="vl_tasks",           # 先进 VL 队列
        task_id=task_id,
        expires=3600,               # 任务1小时内未执行则丢弃
    )

    return {
        "task_id": task_id,
        "status": "queued",
        "queue_position": queue_depth + 1,
        "poll_url": f"/api/task/{task_id}/status",
        "stream_url": f"/api/task/{task_id}/stream",
    }


@router.get("/api/task/{task_id}/status")
async def get_task_status(task_id: str):
    """轮询接口（前端每 2 秒调用一次）"""
    state = await redis_client.hgetall(f"task:{task_id}")
    if not state:
        raise HTTPException(404, "任务不存在或已过期")
    return state


@router.get("/api/task/{task_id}/stream")
async def task_stream(task_id: str):
    """SSE 推送进度（替代现有 /api/progress/stream）"""
    async def event_generator():
        while True:
            state = await redis_client.hgetall(f"task:{task_id}")
            if not state:
                yield f"data: {json.dumps({'status': 'expired'})}\n\n"
                break
            yield f"data: {json.dumps(state)}\n\n"
            if state.get("status") in ("done", "error", "cancelled"):
                break
            await asyncio.sleep(1.0)

    return EventSourceResponse(event_generator())
```

---

### 3.3 Celery Worker 层

#### 令牌桶限流器（核心 —— Redis 分布式令牌桶）

> API 配额是主账号全局共享的（qwen-vl-plus = 60 RPM = 1 QPS，qwen3-max = 600 RPM = 10 QPS）。
> 必须使用 **Redis 分布式令牌桶 + Lua 脚本原子扣令牌**，所有 Worker 共享同一计数，保证全局不超 API 上限。

```python
# backend/core/distributed_rate_limiter.py
# 详见 板斧一 章节的完整实现（DistributedTokenBucket 类 + Lua 脚本）

# 全局限流器（启动时初始化一次）
VL_RATE_LIMITER  = DistributedTokenBucket(redis, "rate_limit:vl",  rate=1.0)   # 1 req/s
LLM_RATE_LIMITER = DistributedTokenBucket(redis, "rate_limit:llm", rate=10.0)  # 10 req/s
```

> 单 Worker 场景可用 `aiolimiter.AsyncLimiter` 本地令牌桶简化，但建议默认使用 Redis 分布式方案（零额外运维成本）。

#### 任务定义

```python
# backend/tasks/analyze.py
from celery import Celery, Task
from celery.utils.log import get_task_logger
import asyncio, json, time

celery_app = Celery(
    "ppt_scorer",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/1",
)
celery_app.conf.update(
    task_serializer="json",
    result_expires=3600,
    worker_max_tasks_per_child=50,      # 每个 Worker 子进程处理50个任务后重启，防内存泄漏
    task_acks_late=True,                # 任务执行完才确认，Worker 崩溃后任务自动重入队列
    task_reject_on_worker_lost=True,    # Worker 丢失时任务重新入队
)

logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    queue="vl_tasks",
    name="tasks.analyze_presentation",
)
def analyze_task(self, task_id: str, pdf_path: str, audio_path: str | None):
    """任务入口（Celery 是同步的，内部用 asyncio.run 跑异步逻辑）"""
    try:
        asyncio.run(_async_analyze_pipeline(task_id, pdf_path, audio_path))
    except RateLimitError as exc:
        # 触发 API 限速，30 秒后重试
        logger.warning(f"[{task_id}] 触发限速，30秒后重试 (attempt {self.request.retries})")
        raise self.retry(exc=exc, countdown=30)
    except Exception as exc:
        # 其他错误写入 Redis，不重试（避免无意义消耗）
        _set_progress(task_id, status="error", message=f"分析失败: {str(exc)[:200]}")
        logger.error(f"[{task_id}] 分析失败", exc_info=True)
        raise


async def _async_analyze_pipeline(task_id: str, pdf_path: str, audio_path: str | None):
    """实际的异步分析流水线"""
    from ..core.distributed_rate_limiter import VL_RATE_LIMITER, LLM_RATE_LIMITER
    from ..services.pdf_analyzer import PDFAnalyzer
    from ..services.scoring_service import ScoringService

    _set_progress(task_id, status="running", percent=5, message="正在解析 PDF...")

    # Stage 1: VL 分析（受 60 RPM 限速，Redis 分布式令牌桶全局限流）
    analyzer = PDFAnalyzer()
    async def vl_call_with_limit(b64, prompt):
        async with VL_RATE_LIMITER:      # Redis 分布式令牌桶，全局限流
            return await asyncio.to_thread(analyzer._call_vl_model_api, b64, prompt)

    slides = await analyzer._analyze_slides_with_caller(vl_call_with_limit)
    _set_progress(task_id, status="running", percent=50, message="幻灯片分析完成，评分中...")

    # Stage 2: LLM 评分（受 600 RPM 限速，Redis 分布式令牌桶全局限流）
    scorer = ScoringService()
    async def llm_call_with_limit(prompt):
        async with LLM_RATE_LIMITER:
            return await asyncio.to_thread(scorer._call_llm_api, prompt)

    result = await scorer.score_with_caller(slides, llm_call_with_limit)
    _set_progress(task_id, status="running", percent=90, message="生成报告...")

    # Stage 3: 生成报告 & 写数据库
    report_path = await generate_report(result, task_id)
    await save_to_db(task_id, result, pdf_path)

    _set_progress(task_id, status="done", percent=100,
                  message="完成！", report_url=f"/api/task/{task_id}/report")


def _set_progress(task_id: str, **kwargs):
    """同步写 Redis（在 Celery Worker 里用同步 redis-py）"""
    from ..core.redis_client import sync_redis
    sync_redis.hset(f"task:{task_id}", mapping={k: str(v) for k, v in kwargs.items()})
```

---

### 3.4 优先级队列（VIP 用户插队）

```python
# 定义三级优先级队列
CELERY_TASK_QUEUES = (
    Queue("vl_tasks_high",   routing_key="vl.high"),    # VIP 用户
    Queue("vl_tasks_normal", routing_key="vl.normal"),  # 普通用户
    Queue("vl_tasks_batch",  routing_key="vl.batch"),   # 批量任务（最低优先级）
    Queue("llm_tasks",       routing_key="llm.normal"),
)

# 提交时根据用户等级选择队列
queue_name = "vl_tasks_high" if current_user.is_vip else "vl_tasks_normal"
analyze_task.apply_async(args=[...], queue=queue_name)
```

---

### 3.5 数据库层（读写分离）

```python
# backend/db/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# 写库（主库）
write_engine = create_async_engine(
    "postgresql+asyncpg://user:pass@primary-db:5432/ppt_scoring",
    pool_size=20, max_overflow=10,
)

# 读库（从库，历史查询走这里，不占主库连接）
read_engine = create_async_engine(
    "postgresql+asyncpg://user:pass@replica-db:5432/ppt_scoring",
    pool_size=30, max_overflow=20,
)

WriteSession = sessionmaker(write_engine, class_=AsyncSession)
ReadSession  = sessionmaker(read_engine,  class_=AsyncSession)
```

---

## 四、完整 docker-compose.yml

```yaml
version: "3.9"

services:
  # ── 数据库 ────────────────────────────────────────────────
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ppt_scoring
      POSTGRES_USER: ppt_user
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "ppt_user"]
      interval: 10s

  # ── 缓存 & 消息队列 ────────────────────────────────────────
  redis:
    image: redis:7-alpine
    command: redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s

  # ── FastAPI 接入层（可横向扩展） ───────────────────────────
  api:
    build: ./backend
    command: uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
    ports: ["8000:8000"]
    environment:
      DATABASE_URL: postgresql+asyncpg://ppt_user:${DB_PASSWORD}@postgres:5432/ppt_scoring
      REDIS_URL: redis://redis:6379/0
    depends_on:
      postgres: {condition: service_healthy}
      redis:    {condition: service_healthy}
    deploy:
      replicas: 2      # 生产环境跑 2 个 API 实例

  # ── VL Worker（串行，受 60 RPM 限速） ────────────────────
  # 扩容条件：提额到 120+ RPM → 改 VL_WORKER_REPLICAS=2 + Redis令牌桶 rate=2
  vl-worker:
    build: ./backend
    command: >
      celery -A tasks.analyze worker
      --queues vl_tasks_high,vl_tasks_normal,vl_tasks_batch
      --concurrency ${VL_WORKER_CONCURRENCY:-1}
      --loglevel info
      --hostname vl-worker@%h
    environment:
      REDIS_URL: redis://redis:6379/0
      DASHSCOPE_API_KEY: ${DASHSCOPE_API_KEY}
    depends_on:
      redis: {condition: service_healthy}
    deploy:
      replicas: ${VL_WORKER_REPLICAS:-1}

  # ── LLM Worker（并发 10，正好打满 600 RPM = 10 QPS） ────
  # 单进程 10 并发已打满配额；提额到 1200 RPM 可设 LLM_WORKER_REPLICAS=2
  llm-worker:
    build: ./backend
    command: >
      celery -A tasks.analyze worker
      --queues llm_tasks
      --concurrency ${LLM_WORKER_CONCURRENCY:-10}
      --loglevel info
      --hostname llm-worker@%h
    environment:
      REDIS_URL: redis://redis:6379/0
      DASHSCOPE_API_KEY: ${DASHSCOPE_API_KEY}
    depends_on:
      redis: {condition: service_healthy}
    deploy:
      replicas: ${LLM_WORKER_REPLICAS:-1}

  # ── Flower 任务监控面板 ────────────────────────────────────
  flower:
    image: mher/flower:2.0
    command: celery flower --broker=redis://redis:6379/0 --port=5555
    ports: ["5555:5555"]
    environment:
      FLOWER_BASIC_AUTH: admin:${FLOWER_PASSWORD}   # 生产必须加认证！
    depends_on: [redis]

  # ── Nginx 反向代理 ─────────────────────────────────────────
  nginx:
    image: nginx:alpine
    ports: ["80:80", "443:443"]
    volumes:
      - ./nginx/ppt.conf:/etc/nginx/conf.d/default.conf
      - ./nginx/ssl:/etc/nginx/ssl
    depends_on: [api]

volumes:
  postgres_data:
  redis_data:
```

### 4.1 Worker 扩缩容环境变量

```bash
# .env
# ── Worker 副本数（与 API 配额强绑定，扩缩容无需改 docker-compose）──

# VL Worker：必须 = 1（qwen-vl-plus-0710 = 60 RPM = 1 QPS）
# 仅当阿里云提额到 120+ RPM 时，可改为 2（需同步改 Redis 令牌桶 rate=2）
VL_WORKER_REPLICAS=1
VL_WORKER_CONCURRENCY=1

# LLM Worker：默认 1 个进程 10 并发（600 RPM = 10 QPS，正好打满）
# 提额到 1200 RPM 可改为 replicas=2（Redis 令牌桶 rate=20）
LLM_WORKER_REPLICAS=1
LLM_WORKER_CONCURRENCY=10

# ── 多账号轮询（可选）──
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx
DASHSCOPE_EXTRA_KEYS=   # 逗号分隔，如 sk-aaa,sk-bbb
API_KEY_POOL_ENABLED=false
```

> **设计理念**：Worker 数量**与 API 配额强绑定**，不是"越多越好"。
> 通过环境变量配置，面试时可以明确说：
> "架构预留了扩容空间，提额后只需改环境变量 + Redis 令牌桶 rate，**无需重构代码**。"

---

## 五、监控告警体系

```
指标采集                    可视化                  告警
Prometheus  ──────────►  Grafana Dashboard  ──►  钉钉/企微 Webhook
     ▲
     │ 采集
     ├── FastAPI: prometheus-fastapi-instrumentator
     ├── Celery:  celery-prometheus-exporter (flower /metrics)
     ├── Redis:   redis_exporter
     └── Postgres: postgres_exporter
```

### 5.1 必须监控的关键指标

| 指标                                    | 告警阈值     | 含义                                              |
| --------------------------------------- | ------------ | ------------------------------------------------- |
| `celery_tasks_total{state="FAILURE"}` | 5分钟内 > 10 | Worker 大量失败                                   |
| `redis_connected_clients`             | > 500        | 连接池耗尽                                        |
| `vl_queue_depth` (自定义)             | > 100        | VL 队列积压严重                                   |
| `llm_queue_depth` (自定义)            | > 50         | LLM 队列积压                                      |
| `task_p95_duration_seconds` (自定义)  | > 300        | 单任务耗时过长                                    |
| `api_429_count` (5分钟窗口，自定义)   | > 0          | **触发 API 限速 429，令牌桶失效或配额超限** |
| `api_request_duration_p99`            | > 5s         | 接入层响应慢                                      |
| `vl_circuit_breaker_open`             | = 1          | VL 熔断器打开                                     |
| `llm_circuit_breaker_open`            | = 1          | LLM 熔断器打开                                    |

### 5.2 前端排队可视化 API

```python
# GET /api/queue/status  → 返回全局排队信息，前端首页展示
{
    "vl_queue_depth": 42,
    "llm_queue_depth": 8,
    "vl_current_eta_seconds": 840,           # 新提交的 VL 任务预计等待 14 分钟
    "vl_current_eta_display": "约 14 分钟",
    "worker_status": {
        "vl": {"concurrency": 1, "busy": true},
        "llm": {"concurrency": 10, "busy_slots": 3}
    }
}
```

### 5.3 429 告警（Prometheus Counter）

```python
from prometheus_client import Counter, Gauge

vl_429_counter = Counter("vl_api_429_total", "VL API 429 count")
llm_429_counter = Counter("llm_api_429_total", "LLM API 429 count")
vl_queue_gauge = Gauge("vl_queue_depth", "VL queue depth")
llm_queue_gauge = Gauge("llm_queue_depth", "LLM queue depth")
task_p95_gauge  = Gauge("task_p95_duration_seconds", "Task P95 duration")

# Grafana 告警规则示例：
#   rate(vl_api_429_total[5m]) > 0  → 钉钉告警："VL API 触发限速 429"
#   vl_queue_depth > 100            → 钉钉告警："VL 队列深度 > 100，需扩容"
#   task_p95_duration_seconds > 300 → 钉钉告警："任务 P95 耗时超过 5 分钟"
```

> **面试话术**：监控覆盖三层——
> **生产指标**（429/P95/失败率/熔断状态）、
> **SRE 告警**（队列深度/连接池/内存）、
> **用户体验**（排队位置/ETA/断点进度）。
> 监控从 Day 1 搭建，不是事后补的。

---

## 六、关键设计原则

### 6.1 幂等性设计

每个任务用 `task_id`（UUID）标识，重试时不会重复计费或重复写库：

```python
# 写库前先检查
existing = await db.get(ScoringRecord, task_id)
if existing:
    return  # 已存在，跳过（幂等）
```

### 6.2 背压（Back Pressure）

队列深度超过阈值时，接入层主动拒绝新请求（返回 503），而不是无限堆积：

```python
if queue_depth > MAX_QUEUE_SIZE:
    raise HTTPException(503, "服务繁忙，请稍后重试")
```

### 6.3 熔断（Circuit Breaker）

API 连续失败 N 次后，停止调用，等待一段时间再恢复，避免故障扩散：

```python
# 使用 tenacity 或 pybreaker 库
from pybreaker import CircuitBreaker

dashscope_breaker = CircuitBreaker(fail_max=5, reset_timeout=60)

@dashscope_breaker
def call_vl_api(...):
    ...
```

### 6.4 超时分层控制

```
Nginx: 10s（只等接入层返回 task_id）
FastAPI: 5s（保存文件 + 写 Redis）
Celery task: 300s（整个分析任务最长 5 分钟）
单次 VL API call: 30s（单张幻灯片分析超时）
单次 LLM API call: 60s（评分超时）
```

---

## 七、各阶段扩容路径

```
Day 1 (开发/测试)          Day 30 (上线初期)         Day 180 (规模化)
─────────────────────      ──────────────────────    ─────────────────────
1x FastAPI (单进程)     →  2x FastAPI + Nginx      →  N x FastAPI + 云负载均衡
asyncio Semaphore       →  Celery + Redis           →  Celery + Redis Cluster
本地 PostgreSQL         →  云 RDS (主从复制)        →  分库分表 / 读写分离
无监控                  →  Prometheus + Grafana     →  全链路追踪 (Jaeger)
手动部署                →  Docker Compose          →  Kubernetes (HPA 自动扩缩)
```

---

## 八、为什么不选 Kafka

| 维度                     | Redis + Celery                    | Kafka                                                              |
| ------------------------ | --------------------------------- | ------------------------------------------------------------------ |
| 运维复杂度               | 低（Redis 已有）                  | 高（需 Kafka + ZooKeeper/KRaft）                                   |
| 学习成本                 | 低（Python 生态成熟）             | 高                                                                 |
| 消息持久化               | 有限（AOF/RDB）                   | 极强（磁盘顺序写，TB 级）                                          |
| 消息重放                 | ❌                                | ✅（任意时间点回放）                                               |
| 多消费者同时消费同一消息 | ❌                                | ✅                                                                 |
| 适合本项目的理由         | ✅ 任务队列，每条消息只需处理一次 | ❌ 无需事件流、无需多下游                                          |
| 引入 Kafka 的时机        | —                                | 需要审计日志 + 实时计费 + 数据分析**同时**消费同一评分事件时 |

---

*本文档描述的是目标架构，当前项目处于 Phase 1（asyncio Semaphore），按需逐步迁移。*
