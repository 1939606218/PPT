"""
数据库连接与会话管理
"""
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    """FastAPI Depends 注入用"""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    """应用启动时建表（若不存在），并确保 admin 账号存在"""
    import uuid
    import bcrypt
    from sqlalchemy import select
    from db.models import User, ScoringRecord, LLMReasoning  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 兼容旧数据库：若 audio_filename 列不存在则自动添加
        try:
            await conn.execute(
                __import__('sqlalchemy').text(
                    "ALTER TABLE scoring_records ADD COLUMN IF NOT EXISTS "
                    "audio_filename VARCHAR(256)"
                )
            )
        except Exception:
            pass  # 列已存在，忽略

        # 兼容旧数据库：确保 llm_reasoning 表存在
        try:
            await conn.execute(
                __import__('sqlalchemy').text("""
                    CREATE TABLE IF NOT EXISTS llm_reasoning (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        record_id UUID NOT NULL REFERENCES scoring_records(id) ON DELETE CASCADE,
                        role VARCHAR(64) NOT NULL,
                        reasoning_text TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    );
                    CREATE INDEX IF NOT EXISTS ix_llm_reasoning_record_id ON llm_reasoning(record_id);
                """)
            )
        except Exception as e:
            print(f"[init_db] llm_reasoning 表创建异常（可能已存在）: {e}")

    # 确保默认 admin 账号存在（username=admin, password=admin）
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        if result.scalar_one_or_none() is None:
            admin_id = uuid.uuid4()
            pw_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode()
            admin = User(
                id=admin_id,
                username="admin",
                email=f"admin_{str(admin_id)[:8]}@placeholder.local",
                password_hash=pw_hash,
                role="admin",
                is_active=True,
            )
            session.add(admin)
            await session.commit()
            print("[init_db] 默认 admin 账号已创建（账号: admin / 密码: admin）")
        else:
            print("[init_db] admin 账号已存在，跳过")
