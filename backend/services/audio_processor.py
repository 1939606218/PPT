"""
音频处理服务 - 使用本地 OpenAI Whisper 模型转录音频，并分析语音指标
模型：large-v3（支持中英文自动检测，效果最佳）
GPU：自动使用 CUDA（服务器有 4×RTX 4090）
"""
import asyncio
import os
import re
from pathlib import Path
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

# Whisper 模型大小：tiny / base / small / medium / large-v2 / large-v3
# large-v3 在 4090 上约 2~4 分钟/小时音频，中文效果最好
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL", "large-v3")

# ── AssemblyAI API 配置 ────────────────────────────────────────────────────────
# API Key（优先从环境变量读取，回退到硬编码）
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY", "41150be279c04720b104b2ca358dafc1")
# True = 前端上传的音频使用 AssemblyAI API 转录；False = 使用本地 Whisper
USE_ASSEMBLYAI_API = os.getenv("USE_ASSEMBLYAI_API", "true").lower() == "true"

# 口头禅关键词（用于流畅度分析）
FILLER_WORDS = ["那个", "然后", "就是", "这个", "嗯", "啊", "哦", "呃", "对对对", "好好好"]


class AudioProcessor:
    """音频处理器：本地 Whisper 转录 + 语音指标分析"""

    def __init__(self):
        self._model = None   # 懒加载，首次调用时才加载模型
        logger.info(f"音频处理器已初始化，Whisper 模型: {WHISPER_MODEL_SIZE}（首次使用时加载）")

    def _load_model(self):
        """懒加载 Whisper 模型（只加载一次，驻留内存）"""
        if self._model is None:
            import whisper
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(f"正在加载 Whisper {WHISPER_MODEL_SIZE} 模型，设备: {device} ...")
            self._model = whisper.load_model(WHISPER_MODEL_SIZE, device=device)
            logger.info("Whisper 模型加载完成")
        return self._model

    # ──────────────────────────────────────────────────────────────────────────
    #  主入口
    # ──────────────────────────────────────────────────────────────────────────

    async def transcribe_audio(self, audio_path: Path, progress_cb=None, use_api: bool = None) -> Dict:
        """
        转录音频文件，返回文本+时间戳+语音指标。

        use_api=True  → 使用 AssemblyAI 云端 API（前端默认模式，支持多语言自动检测）
        use_api=False → 使用本地 Whisper 模型（GPU 密集型，放入线程池避免阻塞）
        默认值由环境变量 USE_ASSEMBLYAI_API 控制（默认 True）。
        """
        if use_api is None:
            use_api = USE_ASSEMBLYAI_API

        logger.info(f"开始转录音频: {audio_path}，模式: {'AssemblyAI API' if use_api else '本地 Whisper'}")
        try:
            if progress_cb:
                progress_cb("start", 0)

            if use_api:
                # ── AssemblyAI API 转录（云端，前端默认）──────────────────────
                result = await asyncio.to_thread(self._run_assemblyai, audio_path)
            else:
                # ── 本地 Whisper 转录（原有方式，保留备用）───────────────────
                raw = await asyncio.to_thread(self._run_whisper, audio_path)
                speech_metrics = self._calc_speech_metrics(raw)
                result = {
                    "full_text": raw["text"].strip(),
                    "segments": [
                        {"start": s["start"], "end": s["end"], "text": s["text"].strip()}
                        for s in raw.get("segments", [])
                    ],
                    "duration": raw.get("duration", self._calc_duration(raw)),
                    "speech_metrics": speech_metrics,
                }

            logger.info(
                f"转录完成 | 时长: {result['duration']:.1f}s | "
                f"字数: {len(result['full_text'])} | 语速: {result['speech_metrics']['speech_rate']} 字/分"
            )
            if progress_cb:
                progress_cb("done", 100)
            return result

        except Exception as e:
            logger.error(f"音频转录失败: {e}", exc_info=True)
            raise

    # ──────────────────────────────────────────────────────────────────────────
    #  Whisper 推理（同步，在线程池中执行）
    # ──────────────────────────────────────────────────────────────────────────

    def _run_whisper(self, audio_path: Path) -> Dict:
        """调用本地 Whisper 模型转录，返回原始结果字典"""
        model = self._load_model()
        result = model.transcribe(
            str(audio_path),
            language=None,
            task="transcribe",
            verbose=False,
            word_timestamps=False,
            fp16=True,
            condition_on_previous_text=True,
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.4,
        )
        return result

    # ──────────────────────────────────────────────────────────────────────────
    #  AssemblyAI API 转录（云端，前端默认）
    # ──────────────────────────────────────────────────────────────────────────

    def _run_assemblyai(self, audio_path: Path) -> Dict:
        """
        调用 AssemblyAI API 转录本地音频文件，返回与 Whisper 兼容的结果格式。
        使用 universal-3-pro（英/西/德/法/意/葡）+ universal-2（其他语言）并自动检测语言。
        """
        import assemblyai as aai

        aai.settings.api_key = ASSEMBLYAI_API_KEY

        config = aai.TranscriptionConfig(
            speech_models=["universal-3-pro", "universal-2"],
            language_detection=True,
        )

        logger.info("正在上传音频到 AssemblyAI 并等待转录结果...")
        transcriber = aai.Transcriber(config=config)
        transcript = transcriber.transcribe(str(audio_path))

        if transcript.status == aai.TranscriptStatus.error:
            raise RuntimeError(f"AssemblyAI 转录失败: {transcript.error}")

        full_text: str = transcript.text or ""
        words = transcript.words or []

        # 计算总时长（毫秒 → 秒）
        duration = words[-1].end / 1000.0 if words else 0.0

        # 将 word 列表按时间间隔（>1s）或长度（>20词）分组为 segments
        segments: List[Dict] = []
        if words:
            seg_start = words[0].start / 1000.0
            seg_words: List[str] = []
            for i, word in enumerate(words):
                seg_words.append(word.text)
                is_last = (i == len(words) - 1)
                next_gap = ((words[i + 1].start - word.end) / 1000.0) if not is_last else 999.0
                if is_last or next_gap > 1.0 or len(seg_words) >= 20:
                    segments.append({
                        "start": seg_start,
                        "end": word.end / 1000.0,
                        "text": " ".join(seg_words),
                        "no_speech_prob": 0.0,
                    })
                    if not is_last:
                        seg_start = words[i + 1].start / 1000.0
                        seg_words = []

        # 复用现有的语音指标计算（传入兼容格式）
        speech_metrics = self._calc_speech_metrics({
            "text": full_text,
            "segments": segments,
            "duration": duration,
        })

        # AssemblyAI 返回实际使用的模型名（如 "universal-3-pro" / "universal-2"）
        detected_model = getattr(transcript, "speech_model", None)
        if detected_model is None:
            # 若 SDK 版本不返回该字段，根据 language_code 推断
            lang = getattr(transcript, "language_code", "") or ""
            en_langs = {"en", "es", "de", "fr", "it", "pt"}
            detected_model = "universal-3-pro" if lang.split("-")[0] in en_langs else "universal-2"
        logger.info(f"AssemblyAI 使用模型: {detected_model}")

        return {
            "full_text": full_text.strip(),
            "segments": [
                {"start": s["start"], "end": s["end"], "text": s["text"].strip()}
                for s in segments
            ],
            "duration": duration,
            "speech_metrics": speech_metrics,
            "speech_model": detected_model,
        }

    # ──────────────────────────────────────────────────────────────────────────
    #  语音指标计算
    # ──────────────────────────────────────────────────────────────────────────

    def _calc_speech_metrics(self, whisper_result: Dict) -> Dict:
        """
        基于 Whisper 转录结果计算语音指标：
        - 语速（字/分钟）：总字数 / 有效演讲时间
        - 停顿：相邻 segment 间隔 > 1.0s 计为一次停顿
        - 口头禅频次：检测常见中文口头禅
        - 清晰度：用平均 no_speech_prob 反推（越低越清晰）
        """
        segments: List[Dict] = whisper_result.get("segments", [])
        full_text: str = whisper_result.get("text", "").strip()

        # ── 时长 ──────────────────────────────────────────────────────────────
        duration = self._calc_duration(whisper_result)

        # ── 有效字数（去掉标点和空格）──────────────────────────────────────────
        clean_text = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", full_text)
        char_count = len(clean_text)

        # ── 语速 ──────────────────────────────────────────────────────────────
        speaking_minutes = duration / 60.0 if duration > 0 else 1.0
        speech_rate = round(char_count / speaking_minutes) if speaking_minutes > 0 else 0

        # ── 停顿分析（间隔 > 1.0s 视为一次停顿）─────────────────────────────
        pauses = []
        for i in range(1, len(segments)):
            gap = segments[i]["start"] - segments[i - 1]["end"]
            if gap > 1.0:
                pauses.append(gap)
        pause_frequency = len(pauses)
        avg_pause = round(sum(pauses) / len(pauses), 2) if pauses else 0.0

        # ── 口头禅检测 ────────────────────────────────────────────────────────
        filler_count = sum(full_text.count(w) for w in FILLER_WORDS)

        # ── 清晰度（基于 no_speech_prob，越低越清晰）─────────────────────────
        if segments:
            avg_no_speech = sum(s.get("no_speech_prob", 0.0) for s in segments) / len(segments)
            clarity = round(1.0 - avg_no_speech, 3)
        else:
            clarity = 0.8

        # ── 置信度（Whisper 无直接置信度，用清晰度代替）──────────────────────
        confidence_level = clarity

        return {
            "speech_rate": speech_rate,
            "pause_frequency": pause_frequency,
            "average_pause_duration": avg_pause,
            "filler_word_count": filler_count,
            "volume_variance": 0.0,      # 需要 librosa 才能计算，暂留
            "clarity": clarity,
            "confidence_level": confidence_level,
        }

    def _calc_duration(self, whisper_result: Dict) -> float:
        """从 segments 末尾推算音频时长"""
        segments = whisper_result.get("segments", [])
        if segments:
            return segments[-1]["end"]
        return 0.0
