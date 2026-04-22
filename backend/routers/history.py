"""
历史记录路由：普通用户查自己，admin 查所有
"""
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel
from datetime import datetime
from typing import Any

from db.database import get_db
from db.models import User, ScoringRecord, LLMReasoning
from core.deps import get_current_user

router = APIRouter(prefix="/api/history", tags=["history"])

BASE_DIR    = Path(__file__).resolve().parent.parent
OUTPUT_DIR  = BASE_DIR / "outputs"


# ── Pydantic 输出模型 ─────────────────────────────────────────────────────────

class RecordSummary(BaseModel):
    id: uuid.UUID
    filename: str
    audio_filename: str | None = None
    has_audio: bool
    total_score: float
    grade: str
    has_pdf: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class RecordDetail(RecordSummary):
    score_data: Any


# ── 查询历史列表 ───────────────────────────────────────────────────────────────

@router.get("", response_model=list[RecordSummary])
async def list_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ScoringRecord)
        .where(ScoringRecord.user_id == current_user.id)
        .order_by(ScoringRecord.created_at.desc())
    )
    result = await db.execute(stmt)
    records = result.scalars().all()
    return [
        RecordSummary(
            id=r.id, filename=r.filename, audio_filename=r.audio_filename,
            has_audio=r.has_audio,
            total_score=r.total_score, grade=r.grade,
            has_pdf=bool(r.pdf_path and (OUTPUT_DIR / r.pdf_path).exists()),
            created_at=r.created_at,
        )
        for r in records
    ]


# ── 查询单条详情 ───────────────────────────────────────────────────────────────

@router.get("/{record_id}", response_model=RecordDetail)
async def get_record(
    record_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await _get_record_or_404(record_id, current_user, db)
    return RecordDetail(
        id=r.id, filename=r.filename, audio_filename=r.audio_filename,
        has_audio=r.has_audio,
        total_score=r.total_score, grade=r.grade,
        has_pdf=bool(r.pdf_path and (OUTPUT_DIR / r.pdf_path).exists()),
        created_at=r.created_at, score_data=r.score_data,
    )


# ── 下载 PDF ──────────────────────────────────────────────────────────────────

@router.get("/{record_id}/pdf")
async def download_pdf(
    record_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await _get_record_or_404(record_id, current_user, db)
    if not r.pdf_path:
        raise HTTPException(status_code=404, detail="该记录没有关联的 PDF 报告")

    pdf_file = OUTPUT_DIR / r.pdf_path
    if not pdf_file.exists():
        raise HTTPException(status_code=404, detail="PDF 文件已不存在，可能已被清理")

    return FileResponse(
        path=str(pdf_file),
        filename=f"评分报告_{r.filename}.pdf",
        media_type="application/pdf",
    )


# ── 删除记录 ──────────────────────────────────────────────────────────────────

@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record(
    record_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await _get_record_or_404(record_id, current_user, db)
    # 同时删除 PDF 文件
    if r.pdf_path:
        pdf_file = OUTPUT_DIR / r.pdf_path
        if pdf_file.exists():
            pdf_file.unlink(missing_ok=True)

    await db.execute(delete(ScoringRecord).where(ScoringRecord.id == record_id))
    await db.commit()


# ── 查询推理过程 ───────────────────────────────────────────────────────────────

@router.get("/{record_id}/reasoning")
async def get_reasoning(
    record_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_record_or_404(record_id, current_user, db)
    result = await db.execute(
        select(LLMReasoning)
        .where(LLMReasoning.record_id == record_id)
        .order_by(LLMReasoning.created_at)
    )
    entries = result.scalars().all()
    return [{"role": e.role, "reasoning_text": e.reasoning_text} for e in entries]


# ── 内部辅助 ──────────────────────────────────────────────────────────────────

async def _get_record_or_404(
    record_id: uuid.UUID, current_user: User, db: AsyncSession
) -> ScoringRecord:
    result = await db.execute(
        select(ScoringRecord).where(ScoringRecord.id == record_id)
    )
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="记录不存在")
    # 普通用户只能访问自己的记录
    if current_user.role != "admin" and r.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此记录")
    return r
