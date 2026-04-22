from fastapi import FastAPI, File, UploadFile, HTTPException, Body, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from typing import Optional
import asyncio
import json
import time
import uvicorn
import os
import shutil
from pathlib import Path
from dotenv import load_dotenv
from services.pdf_analyzer import PDFAnalyzer
from services.audio_processor import AudioProcessor
from services.scoring_service import ScoringService
from services.report_generator import ReportGenerator
from models.schemas import AnalysisResult
from db.database import get_db, init_db
from db.models import User, ScoringRecord, LLMReasoning
from core.deps import get_current_user
from routers.auth import router as auth_router
from routers.history import router as history_router
from routers.admin import router as admin_router
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
import logging

_optional_oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_optional_user(
    token: Optional[str] = Depends(_optional_oauth2),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """JWT 存在且有效则返回 User，否则返回 None（不报错）"""
    if not token:
        return None
    try:
        from core.security import decode_token
        payload = decode_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return None
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        return user if (user and user.is_active) else None
    except (JWTError, Exception):
        return None

# ── 加载 .env
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PPT打分系统", version="1.0.0")

# ── 配置 CORS 跨域 ─────────────────────────────────────────────────────────────
env_origins = os.getenv("CORS_ORIGINS", "")

# 默认允许的本地地址
allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:18766",
    "http://127.0.0.1:18766"
]

# 从环境变量加载额外的前端地址
if env_origins:
    allowed_origins.extend([o.strip() for o in env_origins.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # 🌟 这里变成了具体的列表
    allow_credentials=True,         # 🌟 保持为 True，允许接收 Cookie
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(history_router)
app.include_router(admin_router)


@app.on_event("startup")
async def startup():
    await init_db()
    logger.info("数据库初始化完成")

UPLOAD_DIR = BASE_DIR / os.getenv("UPLOAD_DIR", "uploads")
OUTPUT_DIR = BASE_DIR / os.getenv("OUTPUT_DIR", "outputs")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# 生产模式：指向 React build 产物；开发模式请访问 Vite dev server (port 5174)
FRONTEND_DIST = BASE_DIR.parent / "frontend-react" / "dist"
PROMPTS_DIR   = BASE_DIR / "prompts"

# 如果 React dist 已 build，挂载静态文件
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

# 5个提示词文件的 key → (文件名, 显示名, 默认备份文件名)
PROMPT_FILES = {
    "classify": ("llm_classify.md",  "分类LLM",                            "llm_classify.default.md"),
    "dimA":     ("dimA_narrative.md","维度A：结构与逻辑（Structure & Logic）","dimA_narrative.default.md"),
    "dimB":     ("dimB_solution.md", "维度B：内容与价值（Content & Value）",  "dimB_solution.default.md"),
    "dimC":     ("dimC_elevation.md","维度C：语言与呈现（Language & Delivery）","dimC_elevation.default.md"),
    "summary":  ("llm_summary.md",   "汇总评委",                            "llm_summary.default.md"),
}

pdf_analyzer    = PDFAnalyzer()
audio_processor = AudioProcessor()
scoring_service = ScoringService()
report_generator = ReportGenerator()

# ── 全局进度状态（单任务假设）──────────────────────────────────────────────
_progress = {
    "running": False,
    "step": 0,
    "total_steps": 4,
    "percent": 0,
    "message": "等待中",
    "detail": "",
    "vl_current": 0,
    "vl_total": 0,
    "audio_done": False,
    "audio_start_ts": 0,
    "audio_percent": 0,
}

# ── 最近一次评分结果（供批量导出使用）─────────────────────────────────────
_last_result: dict = {}

def set_progress(step: int, percent: int, message: str, detail: str = ""):
    _progress.update({"running": True, "step": step, "percent": percent,
                       "message": message, "detail": detail})
    logger.info(f"[进度 {percent}%] {message}")


@app.get("/api/progress")
async def get_progress():
    result = dict(_progress)
    ts = result.get("audio_start_ts", 0)
    if ts > 0 and not result.get("audio_done", False):
        result["audio_elapsed"] = int(time.time() - ts)
    else:
        result["audio_elapsed"] = 0
    return result


@app.get("/api/last-result")
async def get_last_result():
    """返回最近一次 /api/analyze 的完整评分 JSON（供批量导出 Excel 使用）"""
    if not _last_result:
        raise HTTPException(status_code=404, detail="暂无评分结果")
    return dict(_last_result)


@app.get("/api/last-report-pdf")
async def get_last_report_pdf():
    """返回最近一次生成的 PDF 报告文件（供批量模式下 POST 连接被防火墙中断时降级使用）"""
    report_path = _last_result.get("_report_path", "")
    if not report_path or not Path(report_path).exists():
        raise HTTPException(status_code=404, detail="暂无可下载的报告")
    pdf_filename = Path(report_path).name
    return FileResponse(
        path=report_path,
        filename=pdf_filename,
        media_type="application/pdf",
    )


@app.get("/api/progress/stream")
async def progress_stream(request: Request):
    """Server-Sent Events: 实时推送分析进度（每 0.4 秒推送一次）"""
    async def event_gen():
        seen_running = False  # 必须先见过 running=True，才允许因 complete 关闭，防止旧状态误关
        try:
            while True:
                if await request.is_disconnected():
                    break
                result = dict(_progress)
                ts = result.get("audio_start_ts", 0)
                result["audio_elapsed"] = (
                    int(time.time() - ts)
                    if ts > 0 and not result.get("audio_done")
                    else 0
                )
                yield f"data: {json.dumps(result)}\n\n"
                if result.get("running"):
                    seen_running = True
                # 只有先见过 running=True，才在完成时关闭流
                if seen_running and result.get("percent", 0) >= 100 and not result.get("running", True):
                    break
                await asyncio.sleep(0.4)
        except (asyncio.CancelledError, GeneratorExit):
            pass

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return HTMLResponse(content=index.read_text(encoding="utf-8"))
    # 开发模式：dist 尚未 build，给出提示
    return HTMLResponse(content="""
    <html><body style='font-family:sans-serif;padding:40px'>
    <h2>🚧 开发模式</h2>
    <p>前端正在 Vite dev server 运行，请访问：</p>
    <p><a href='http://localhost:5174' style='font-size:1.2em'>http://localhost:5174</a></p>
    <p style='color:#888'>如需让 18766 直接提供前端，请先执行 <code>npm run build</code>（在 frontend-react/ 目录）</p>
    </body></html>
    """, status_code=200)


# SPA fallback：让 React Router 的前端路由（如 /history, /admin）能正常刷新
@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    # API 路径不拦截
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404)

    # 优先：检查 dist/ 根目录下是否存在对应的静态文件（logo.png、favicon.svg 等）
    if full_path and FRONTEND_DIST.exists():
        static_file = FRONTEND_DIST / full_path
        if static_file.exists() and static_file.is_file():
            return FileResponse(str(static_file))

    # 兜底：返回 index.html（SPA 路由）
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return HTMLResponse(content=index.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404)


@app.post("/api/analyze", response_class=FileResponse)
async def analyze_presentation(
    pdf_file: UploadFile = File(...),
    audio_file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    try:
        has_audio = audio_file is not None and bool(audio_file.filename)
        logger.info(f"收到分析请求 - PDF: {pdf_file.filename}, 音频: {audio_file.filename if has_audio else '无（纯PPT模式）'}")
        # 立即重置进度状态，防止 SSE 读到上一次的旧数据
        _progress.update({
            "running": True, "step": 0, "percent": 2,
            "message": "收到请求，准备中...", "detail": "",
            "vl_current": 0, "vl_total": 0,
            "audio_done": not has_audio, "audio_start_ts": 0, "audio_percent": 0,
        })
        if not any(pdf_file.filename.lower().endswith(ext) for ext in ('.pdf', '.pptx', '.ppt')):
            raise HTTPException(status_code=400, detail="请上传 PDF 或 PPT/PPTX 文件")

        if has_audio:
            allowed_audio_extensions = ['.mp3', '.wav', '.m4a', '.ogg', '.flac', '.mp4', '.mov', '.mkv', '.webm']
            if not any(audio_file.filename.lower().endswith(ext) for ext in allowed_audio_extensions):
                raise HTTPException(status_code=400, detail="音频文件格式不支持")

        # 保存上传文件
        set_progress(0, 5, "正在上传并保存文件...")
        pdf_path = UPLOAD_DIR / f"temp_{pdf_file.filename}"
        with open(pdf_path, "wb") as f:
            shutil.copyfileobj(pdf_file.file, f)

        if has_audio:
            audio_path = UPLOAD_DIR / f"temp_{audio_file.filename}"
            with open(audio_path, "wb") as f:
                shutil.copyfileobj(audio_file.file, f)

        # ── 步骤 1：VL 分析（+ 音频转录，如有）────────────────────────────────
        _progress.update({"vl_current": 0, "vl_total": 0, "audio_done": not has_audio,
                          "audio_start_ts": 0, "audio_percent": 0})

        def vl_progress_cb(current: int, total: int):
            _progress["vl_current"] = current
            _progress["vl_total"]   = total
            _progress["percent"]    = int(10 + (current / total) * 50)

        if has_audio:
            set_progress(1, 10, "步骤 1/4：正在并行分析 PPT 与转录音频",
                         f"Qwen VL 逐页理解 {pdf_file.filename}（并发5页）& AssemblyAI 转录音频...")

            def audio_progress_cb(status: str, value: int = 0):
                if status == "start":
                    _progress["audio_start_ts"] = time.time()
                    _progress["audio_percent"]  = 0
                elif status == "progress":
                    _progress["audio_percent"] = value
                elif status == "done":
                    _progress["audio_done"]    = True
                    _progress["audio_percent"] = 100

            pdf_analysis, transcription = await asyncio.gather(
                pdf_analyzer.analyze_file(pdf_path, progress_cb=vl_progress_cb),
                audio_processor.transcribe_audio(audio_path, progress_cb=audio_progress_cb)
            )
            chars = len(transcription.get("full_text", ""))
            dur   = transcription.get("duration", 0)
            set_progress(1, 62, f"步骤 1/4：完成（PPT {pdf_analysis.get('total_slides',0)} 页 / 转录 {chars} 字 / {dur/60:.1f} 分钟）")
        else:
            set_progress(1, 10, "步骤 1/4：正在分析 PPT（纯PPT模式，无音频）",
                         f"Qwen VL 逐页理解 {pdf_file.filename}（并发5页）...")
            pdf_analysis = await pdf_analyzer.analyze_file(pdf_path, progress_cb=vl_progress_cb)
            transcription = {"full_text": "", "duration": 0, "speech_metrics": {}}
            set_progress(1, 62, f"步骤 1/4：完成（PPT {pdf_analysis.get('total_slides',0)} 页，无音频）")

        # 步骤 2：LLM 分类 + 步骤 3：LLM 评分（内部先分类再并行3维度）
        set_progress(2, 65, "步骤 2/4：正在识别 PPT 类型",
                     "使用 LLM 判断演讲类型：产品创新/问题解决/降本增效/方法工具...")
        set_progress(3, 70, "步骤 3/4：正在综合评分",
                     "分类LLM完成后并行启动3个维度评委进行评分...")
        scoring_result = await scoring_service.score_presentation(
            pdf_analysis=pdf_analysis, transcription=transcription, has_audio=has_audio)
        ppt_type = scoring_result.get("ppt_type", {})
        total = scoring_result.get("total_score", "?")
        grade = scoring_result.get("grade", "?")
        set_progress(3, 88, f"步骤 3/4：评分完成（类型: {ppt_type.get('type_name','?')} / {total} 分 / 等级 {grade}）")

        # 步骤 4：生成报告
        set_progress(4, 90, "步骤 4/4：正在生成 PDF 报告",
                     "Markdown → Puppeteer/Chrome → PDF...")
        report_path = await report_generator.generate_report(
            pdf_analysis=pdf_analysis,
            transcription=transcription,
            scoring_result=scoring_result,
            output_dir=OUTPUT_DIR
        )
        set_progress(4, 100, "完成！报告已生成，即将下载")

        # 清理临时文件
        try:
            os.remove(pdf_path)
            if has_audio:
                os.remove(audio_path)
        except Exception:
            pass

        _progress["running"] = False
        # 缓存最近一次评分结果（批量导出用）
        _last_result.update(scoring_result)
        _last_result["_pdf_filename"]   = pdf_file.filename
        _last_result["_audio_filename"] = audio_file.filename if has_audio else ""
        _last_result["_report_path"]    = str(report_path)  # 供 /api/last-report-pdf 使用

        # 写入历史记录（已登录用户）
        if current_user is not None:
            try:
                rel_path = Path(report_path).name  # 仅文件名，相对 outputs/
                record = ScoringRecord(
                    user_id=current_user.id,
                    filename=pdf_file.filename,
                    audio_filename=audio_file.filename if has_audio else None,
                    has_audio=has_audio,
                    total_score=float(scoring_result.get("total_score", 0)),
                    grade=scoring_result.get("grade", "-"),
                    score_data=scoring_result,
                    pdf_path=rel_path,
                )
                db.add(record)
                await db.commit()
                logger.info(f"打分记录已保存 (user={current_user.username}, score={record.total_score})")

                # Save LLM reasoning entries (only populated when thinking mode is on)
                reasoning = scoring_service.get_last_reasoning()
                if reasoning:
                    for role, text in reasoning.items():
                        if text:
                            db.add(LLMReasoning(
                                record_id=record.id, role=role, reasoning_text=text
                            ))
                    await db.commit()
                    logger.info(f"推理记录已保存 ({len(reasoning)} 个角色)")
            except Exception as db_err:
                logger.warning(f"写入历史记录失败（不影响报告下载）: {db_err}")

        return FileResponse(
            path=report_path,
            filename=f"评分报告_{pdf_file.filename}_{time.strftime('%Y%m%d_%H%M%S')}.pdf",
            media_type="application/pdf"
        )

    except asyncio.CancelledError:
        # 客户端断开连接时 uvicorn 可能取消请求协程，需重置进度状态
        _progress.update({"running": False, "message": "连接已断开", "percent": 0})
        raise
    except Exception as e:
        _progress.update({"running": False, "message": f"出错：{str(e)[:80]}", "percent": 0})
        logger.error(f"分析过程出错: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# ── 提示词管理接口 ────────────────────────────────────────────────────────────

@app.get("/api/prompts")
async def get_prompts():
    """返回全部6个提示词的内容"""
    result = {}
    for key, (filename, label, _) in PROMPT_FILES.items():
        p = PROMPTS_DIR / filename
        result[key] = {
            "label":   label,
            "content": p.read_text(encoding="utf-8") if p.exists() else "",
        }
    return result


@app.put("/api/prompts/{key}")
async def update_prompt(key: str, body: dict = Body(...)):
    """保存单个提示词"""
    if key not in PROMPT_FILES:
        raise HTTPException(status_code=404, detail=f"提示词 '{key}' 不存在")
    filename = PROMPT_FILES[key][0]
    content  = body.get("content", "")
    (PROMPTS_DIR / filename).write_text(content, encoding="utf-8")
    logger.info(f"提示词已更新: {key} ({filename})")
    return {"status": "ok", "key": key}


@app.post("/api/prompts/{key}/restore")
async def restore_prompt(key: str):
    """将提示词恢复为 .default.md 中的初始内容"""
    if key not in PROMPT_FILES:
        raise HTTPException(status_code=404, detail=f"提示词 '{key}' 不存在")
    filename, _, default_filename = PROMPT_FILES[key]
    default_path = PROMPTS_DIR / default_filename
    if not default_path.exists():
        raise HTTPException(status_code=404, detail=f"默认备份文件不存在: {default_filename}")
    content = default_path.read_text(encoding="utf-8")
    (PROMPTS_DIR / filename).write_text(content, encoding="utf-8")
    logger.info(f"提示词已恢复默认: {key} ({filename})")
    return {"status": "ok", "key": key, "content": content}


if __name__ == "__main__":
    uvicorn.run("main:app", host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", 18766)), reload=False)
