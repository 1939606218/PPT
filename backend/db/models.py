"""
数据库模型
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, Float, Text, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(
        SAEnum("user", "admin", name="user_role"), default="user", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    records: Mapped[list["ScoringRecord"]] = relationship(
        "ScoringRecord", back_populates="user", cascade="all, delete-orphan"
    )


class ScoringRecord(Base):
    __tablename__ = "scoring_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(256), nullable=False)   # 原始 PPT 文件名
    audio_filename: Mapped[str | None] = mapped_column(String(256), nullable=True)  # 音频文件名（可空）
    has_audio: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    grade: Mapped[str] = mapped_column(String(8), nullable=False)
    score_data: Mapped[dict] = mapped_column(JSONB, nullable=False)       # 完整 scoring_result JSON
    pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)     # 报告文件相对路径
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="records")


class LLMReasoning(Base):
    """每次评分中各 LLM 角色的推理过程（thinking mode 开启时写入）"""
    __tablename__ = "llm_reasoning"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scoring_records.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    # classify / narrative_setup / solution_results / elevation_fluency / summary
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    reasoning_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
