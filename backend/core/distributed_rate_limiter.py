import time, asyncio
from redis.asyncio import Redis

LUA_ACQUIRE_TOKEN = """
-- KEYS[1]: 令牌桶的 Redis key，如 "rate_limit:vl"
-- ARGV[1]: 每秒产生令牌数 (rate)
-- ARGV[2]: 当前时间戳 (秒)
-- ARGV[3]: 请求令牌数 (默认 1)

local key        = KEYS[1]
local rate       = tonumber(ARGV[1])
local now        = tonumber(ARGV[2])
local requested  = tonumber(ARGV[3]) or 1
local window     = 1.0

local last_time  = tonumber(redis.call('HGET', key, 'last_time') or now)
local tokens     = tonumber(redis.call('HGET', key, 'tokens') or rate)

-- 按时间流逝补充令牌
local elapsed = math.min(now - last_time, window)
tokens = math.min(rate, tokens + elapsed * rate)

if tokens >= requested then
    tokens = tokens - requested
    redis.call('HSET', key, 'tokens', tokens, 'last_time', now)
    redis.call('EXPIRE', key, 3)
    return 1   -- 获取成功
else
    redis.call('HSET', key, 'last_time', now)
    redis.call('EXPIRE', key, 3)
    return 0   -- 无可用令牌
end
"""


class DistributedTokenBucket:
    """Redis 分布式令牌桶 —— 所有 Worker 共享同一配额"""

    def __init__(self, redis: Redis, key: str, rate: float):
        self.redis = redis
        self.key = key
        self.rate = rate
        self._script = self.redis.register_script(LUA_ACQUIRE_TOKEN)

    async def acquire(self) -> bool:
        now = time.time()
        result = await self._script(keys=[self.key], args=[self.rate, now, 1])
        return result == 1

    async def wait_and_acquire(self, poll_interval: float = 0.1):
        while not await self.acquire():
            await asyncio.sleep(poll_interval)

    async def __aenter__(self):
        await self.wait_and_acquire()
        return self

    async def __aexit__(self, *args):
        pass  # 令牌已消费，无需归还


# ── 全局限流器（启动时初始化一次）──
VL_RATE_LIMITER  = None   # DistributedTokenBucket(redis, "rate_limit:vl",  1.0)
LLM_RATE_LIMITER = None   # DistributedTokenBucket(redis, "rate_limit:llm", 20.0)


# ── 使用示例 ─────────────────────────────────────────────────
async def analyze_slide_page(b64: str, prompt: str):
    async with VL_RATE_LIMITER:        # Redis 分布式令牌桶，全局 1 QPS
        return await asyncio.to_thread(_call_vl_api, b64, prompt)

async def run_dimension_scoring(context: str, dim: str):
    async with LLM_RATE_LIMITER:       # 3 个并行调用各自竞争令牌桶
        return await asyncio.to_thread(_call_llm_api, context, dim)