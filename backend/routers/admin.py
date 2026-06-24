"""
Admin 路由：全量历史记录 / 用户管理 / 提示词编辑 / LLM设置
"""
import uuid
import json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import datetime
from typing import Any

from db.database import get_db
from db.models import User, ScoringRecord
from core.deps import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])

BASE_DIR    = Path(__file__).resolve().parent.parent
OUTPUT_DIR  = BASE_DIR / "outputs"
PROMPTS_DIR = BASE_DIR / "prompts"
LLM_SETTINGS_PATH = BASE_DIR / "llm_settings.json"
SCORING_CONFIG_PATH = BASE_DIR / "scoring_config.json"

SUPPORTED_MODELS = ["qwen3-max", "qwen-long"]
LLM_SETTINGS_DEFAULT = {"model": "qwen3-max", "enable_thinking": False}

PROMPT_FILES = {
    "classify": ("llm_classify.md",   "分类LLM",                              "llm_classify.default.md"),
    "dimA":     ("dimA_narrative.md", "维度A：结构与逻辑（Structure & Logic）", "dimA_narrative.default.md"),
    "dimB":     ("dimB_solution.md",  "维度B：内容与价值（Content & Value）",   "dimB_solution.default.md"),
    "dimC":     ("dimC_elevation.md", "维度C：语言与呈现（Language & Delivery）","dimC_elevation.default.md"),
    "summary":  ("llm_summary.md",    "汇总评委",                              "llm_summary.default.md"),
}


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────

class RecordWithUser(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    username: str
    filename: str
    audio_filename: str | None = None
    has_audio: bool
    total_score: float
    grade: str
    has_pdf: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserInfo(BaseModel):
    id: uuid.UUID
    username: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── 全量历史记录 ───────────────────────────────────────────────────────────────

@router.get("/history", response_model=list[RecordWithUser])
async def all_history(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ScoringRecord, User.username)
        .join(User, ScoringRecord.user_id == User.id)
        .order_by(ScoringRecord.created_at.desc())
    )
    rows = result.all()
    return [
        RecordWithUser(
            id=r.id, user_id=r.user_id, username=username,
            filename=r.filename, audio_filename=r.audio_filename,
            has_audio=r.has_audio,
            total_score=r.total_score, grade=r.grade,
            has_pdf=bool(r.pdf_path and (OUTPUT_DIR / r.pdf_path).exists()),
            created_at=r.created_at,
        )
        for r, username in rows
    ]


# ── 用户管理 ───────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserInfo])
async def list_users(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return [UserInfo.model_validate(u) for u in result.scalars().all()]


@router.patch("/users/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    body: dict = Body(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """支持修改 is_active 和 role"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能修改自己的账号状态")

    if "is_active" in body:
        user.is_active = bool(body["is_active"])
    if "role" in body and body["role"] in ("user", "admin"):
        user.role = body["role"]

    await db.commit()
    return {"status": "ok", "user_id": str(user_id)}


# ── 提示词管理（迁移自 main.py） ──────────────────────────────────────────────

@router.get("/prompts")
async def get_prompts(_: User = Depends(require_admin)):
    result = {}
    for key, (filename, label, _default) in PROMPT_FILES.items():
        p = PROMPTS_DIR / filename
        result[key] = {"label": label, "content": p.read_text(encoding="utf-8") if p.exists() else ""}
    return result


@router.put("/prompts/{key}")
async def update_prompt(
    key: str,
    body: dict = Body(...),
    _: User = Depends(require_admin),
):
    if key not in PROMPT_FILES:
        raise HTTPException(status_code=404, detail=f"提示词 '{key}' 不存在")
    (PROMPTS_DIR / PROMPT_FILES[key][0]).write_text(body.get("content", ""), encoding="utf-8")
    return {"status": "ok", "key": key}


@router.post("/prompts/{key}/restore")
async def restore_prompt(key: str, _: User = Depends(require_admin)):
    if key not in PROMPT_FILES:
        raise HTTPException(status_code=404, detail=f"提示词 '{key}' 不存在")
    filename, _, default_filename = PROMPT_FILES[key]
    default_path = PROMPTS_DIR / default_filename
    if not default_path.exists():
        raise HTTPException(status_code=404, detail=f"默认备份文件不存在: {default_filename}")
    content = default_path.read_text(encoding="utf-8")
    (PROMPTS_DIR / filename).write_text(content, encoding="utf-8")
    return {"status": "ok", "key": key, "content": content}


# ── LLM 模型设置 ───────────────────────────────────────────────────────────────

class LLMSettingsBody(BaseModel):
    model: str
    enable_thinking: bool


@router.get("/llm-settings")
async def get_llm_settings(_: User = Depends(require_admin)):
    if LLM_SETTINGS_PATH.exists():
        return json.loads(LLM_SETTINGS_PATH.read_text(encoding="utf-8"))
    return LLM_SETTINGS_DEFAULT


@router.put("/llm-settings")
async def update_llm_settings(
    body: LLMSettingsBody,
    _: User = Depends(require_admin),
):
    if body.model not in SUPPORTED_MODELS:
        raise HTTPException(status_code=400, detail=f"不支持的模型: {body.model}")
    # thinking mode only valid for qwen3-* models
    enable_thinking = body.enable_thinking and body.model.startswith("qwen3")
    settings = {"model": body.model, "enable_thinking": enable_thinking}
    LLM_SETTINGS_PATH.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"status": "ok", **settings}


# ── 评分配置 ───────────────────────────────────────────────────────────────────

_SCORING_DEFAULT = {
    "with_audio": {
        "narrative_setup":   {"label": "维度A · 结构与逻辑", "max_score": 45},
        "solution_results":  {"label": "维度B · 内容与价值", "max_score": 45},
        "elevation_fluency": {"label": "维度C · 语言与呈现", "max_score": 10},
    },
    "no_audio": {
        "narrative_setup":  {"label": "维度A · 结构与逻辑", "max_score": 50},
        "solution_results": {"label": "维度B · 内容与价值", "max_score": 50},
    },
    "sub_dimensions": {
        "narrative_setup": {
            "labels": ["背景与痛点铺垫", "方案推演的连贯性", "结果的闭环交代", "通用价值提炼"],
            "ratio": [12, 11, 11, 11],
        },
        "solution_results": {
            "labels": ["客观数据与证据支撑", "业务相关性与深度", "跨界理解友好度", "工程决策与系统思维"],
            "ratio": [12, 11, 11, 11],
        },
    },
    "relevance": {
        "low_cap_pct": 0.30, "mid_cap_pct": 0.75,
        "low_threshold": 40, "high_threshold": 70,
    },
    "prompt_files": {
        "narrative_setup":   "dimA_narrative.md",
        "solution_results":  "dimB_solution.md",
        "elevation_fluency": "dimC_elevation.md",
    },
}


@router.get("/scoring-config")
async def get_scoring_config(_: User = Depends(require_admin)):
    if SCORING_CONFIG_PATH.exists():
        return json.loads(SCORING_CONFIG_PATH.read_text(encoding="utf-8"))
    return _SCORING_DEFAULT


@router.put("/scoring-config")
async def update_scoring_config(
    body: dict = Body(...),
    _: User = Depends(require_admin),
):
    # Basic validation: with_audio scores must sum to 100
    wa = body.get("with_audio", {})
    na = body.get("no_audio", {})
    wa_total = sum(int(v["max_score"]) for v in wa.values())
    na_total = sum(int(v["max_score"]) for v in na.values())
    if wa_total != 100:
        raise HTTPException(status_code=400,
            detail=f"有音频模式满分合计必须为100，当前为 {wa_total}")
    if na_total != 100:
        raise HTTPException(status_code=400,
            detail=f"无音频模式满分合计必须为100，当前为 {na_total}")
    SCORING_CONFIG_PATH.write_text(
        json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"status": "ok"}
