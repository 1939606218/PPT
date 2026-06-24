import subprocess
import os
from pathlib import Path
from typing import Dict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# ── 路径 ──────────────────────────────────────────────────────────────────────
_BASE_DIR  = Path(__file__).resolve().parent.parent          # backend/
MD2PDF_BIN = _BASE_DIR.parent / "md2pdf" / "node_modules" / ".bin" / "md-to-pdf"
STYLE_CSS  = _BASE_DIR.parent / "md2pdf" / "style.css"
CHROME     = "/usr/bin/google-chrome"

# ── 评分维度元数据 ────────────────────────────────────────────────────────────
# 增加了 llm_key 用于与汇总 LLM 输出的 dimension_details 对应
# ── 评分维度元数据（有音频：A45+B45+C10） ────────────────────────────────────
DIMENSION_META_WITH_AUDIO = {
    "narrative_setup":   {"name": "维度A：结构与逻辑（Structure & Logic）", "max": 45},
    "solution_results":  {"name": "维度B：内容与价值（Content & Value）",   "max": 45},
    "elevation_fluency": {"name": "维度C：语言与呈现（Language & Delivery）","max": 10},
}

# ── 评分维度元数据（无音频：A50+B50） ────────────────────────────────────────
DIMENSION_META_NO_AUDIO = {
    "narrative_setup":  {"name": "维度A：结构与逻辑（Structure & Logic）", "max": 50},
    "solution_results": {"name": "维度B：内容与价值（Content & Value）",   "max": 50},
}

# 兼容旧代码引用
DIMENSION_META = DIMENSION_META_WITH_AUDIO

GRADE_LABEL = {"A": "优秀 🏆", "B": "良好 👍", "C": "合格 📋", "D": "待提升 📈"}

# ── 子维度中文名称映射 ─────────────────────────────────────────────────────────
SUB_DIMENSION_NAMES = {
    # 维度A
    "background_and_pain_points": "起点与困境（背景/痛点量化）",
    "solution_deduction":         "破局推演（方案逻辑连贯性）",
    "closed_loop_results":        "成效闭环（测试结果与验证）",
    "universal_value":            "通用价值提炼（经验复用）",
    # 维度B
    "data_and_evidence":          "客观数据与证据支撑",
    "business_relevance":         "业务相关性与落地深度",
    "clarity_for_non_experts":    "跨界理解友好度（降维表达）",
    "engineering_decision":       "工程系统思维（权衡/避坑）"
}


class ReportGenerator:

    def __init__(self):
        logger.info("报告生成器已初始化")

    async def generate_report(
        self,
        pdf_analysis: Dict,
        transcription: Dict,
        scoring_result: Dict,
        output_dir: Path
    ) -> Path:
        timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
        md_path    = output_dir / f"评分报告_{timestamp}.md"
        pdf_path   = output_dir / f"评分报告_{timestamp}.pdf"

        logger.info("开始生成评分报告（Markdown → PDF）...")
        try:
            md_content = self._build_markdown(pdf_analysis, transcription, scoring_result)
            md_path.write_text(md_content, encoding="utf-8")
            logger.info(f"Markdown 已生成: {md_path}")

            self._md_to_pdf(md_path, pdf_path)
            logger.info(f"PDF 报告已生成: {pdf_path}")

            md_path.unlink(missing_ok=True)
            return pdf_path

        except Exception as e:
            logger.error(f"报告生成失败: {e}", exc_info=True)
            raise

    def _build_markdown(self, pdf_analysis: Dict, transcription: Dict, scoring_result: Dict) -> str:
        scores   = scoring_result.get("scores", {})
        total    = scoring_result.get("total_score", 0)
        grade    = scoring_result.get("grade", "D")
        ppt_type = scoring_result.get("ppt_type", {})
        has_audio = scoring_result.get("has_audio", True)
        metrics  = transcription.get("speech_metrics", {})
        duration = transcription.get("duration", 0)
        now      = datetime.now().strftime("%Y年%m月%d日 %H:%M")

        type_name = ppt_type.get("type_name", "未分类")
        type_reasoning = ppt_type.get("reasoning", "")

        # 根据模式选择维度元数据
        dim_meta = DIMENSION_META_WITH_AUDIO if has_audio else DIMENSION_META_NO_AUDIO

        # 获取维度详情数据
        _ = scoring_result.get("dimension_details", {})  # 保留兼容

        lines = [
            "# 🎤 技术分享演讲评审报告",
            "",
            f"> 🕒 生成时间：{now}　　📄 PPT 共 {pdf_analysis.get('total_slides', 0)} 页" +
            (f"　　⏱️ 时长：{duration/60:.1f} 分钟" if has_audio else "　　🔇 纯PPT模式（无音频）"),
            "",
            "---",
            "",
            "## 📊 总体得分与表现",
            "",
            "| 项目 | 结果 |",
            "|------|------|",
            f"| **评估类型** | **{type_name}** |",
            f"| **总得分** | **{total} / 100** |",
            f"| **综合评级** | **{grade} — {GRADE_LABEL.get(grade, grade)}** |",
        ]
        if has_audio:
            lines += [
                f"| 语速指标 | {metrics.get('speech_rate', 0)} 字/分钟 |",
                f"| 演讲流畅度 | 停顿 {metrics.get('pause_frequency', 0)} 次 / 口头禅 {metrics.get('filler_word_count', 0)} 次 |",
            ]
        else:
            lines += [
                "| 评分模式 | 纯PPT模式（维度A 50分 + 维度B 50分） |",
            ]
        lines += [
            "",
            f"> 📌 **类型匹配理由**：{type_reasoning}",
            "",
            "---",
            "",
            "## 📋 核心维项总览",
            "",
            "| 评估维度 | 得分 | 满分 | 进度条 |",
            "|---------|:----:|:----:|-------|",
        ]

        # 绘制进度条总览表
        for key, meta in dim_meta.items():
            d      = scores.get(key, {})
            score  = d.get("score", 0) if isinstance(d, dict) else 0
            max_s  = meta["max"]
            filled = int(score / max_s * 10)
            bar    = "█" * filled + "░" * (10 - filled)
            lines.append(f"| {meta['name'].split('（')[0]} | **{score}** | {max_s} | `{bar}` |")

        lines += ["", "---", "", "## 📝 三维度细分点评" if has_audio else "## 📝 两维度细分点评", ""]

        # 构建详细维度报告（子维度进度条表格 + 各子维度点评 + 整体点评）
        for key, meta in dim_meta.items():
            d               = scores.get(key, {})
            score           = d.get("score", 0) if isinstance(d, dict) else 0
            overall_comment = d.get("comment", "") if isinstance(d, dict) else str(d)
            sub_dims        = d.get("sub_dimensions", {}) if isinstance(d, dict) else {}

            lines += [f"### {meta['name']}　⭐ {score}/{meta['max']} 分", ""]

            # 1. 子维度得分进度条总览表
            if sub_dims:
                lines += [
                    "| 子项 | 得分 | 满分 | 进度条 |",
                    "|-----|:----:|:----:|--------|",
                ]
                for sub_key, sub_data in sub_dims.items():
                    sub_name = SUB_DIMENSION_NAMES.get(sub_key, sub_key)
                    s_score  = float(sub_data.get("score", 0))
                    s_max    = float(sub_data.get("max_score", 10))
                    filled   = int(round(s_score / s_max * 10)) if s_max > 0 else 0
                    bar      = "█" * filled + "░" * (10 - filled)
                    lines.append(f"| {sub_name} | **{s_score:.0f}** | {s_max:.0f} | `{bar}` |")
                lines.append("")

            # 2. 各子维度逐条点评
            if sub_dims:
                for sub_key, sub_data in sub_dims.items():
                    sub_name    = SUB_DIMENSION_NAMES.get(sub_key, sub_key)
                    sub_comment = sub_data.get("comment", "").strip()
                    if sub_comment:
                        lines += [f"**▸ {sub_name}**", "", sub_comment, ""]

            # 3. 整体点评
            if overall_comment:
                lines += ["**【整体点评】**", ""]
                formatted = "\n\n".join(line for line in overall_comment.splitlines() if line.strip())
                lines += [formatted, ""]

        lines += ["---", "", "## 🌟 主要优点", ""]
        for i, s in enumerate(scoring_result.get("strengths", []), 1):
            lines.append(f"{i}. {s}")
        lines.append("")

        lines += ["---", "", "## ⚠️ 需要提升的不足", ""]
        for i, s in enumerate(scoring_result.get("weaknesses", []), 1):
            lines.append(f"{i}. {s}")
        lines.append("")

        lines += ["---", "", "## 💡 评委行动建议", ""]
        for i, s in enumerate(scoring_result.get("suggestions", []), 1):
            lines.append(f"{i}. {s}")
        lines.append("")

        summary = scoring_result.get("summary", "")
        if summary:
            lines += ["---", "", "## 🎯 总结语", "", summary, ""]

        return "\n".join(lines)

    def _md_to_pdf(self, md_path: Path, pdf_path: Path):
        if not MD2PDF_BIN.exists():
            raise RuntimeError(f"md-to-pdf 未找到: {MD2PDF_BIN}")

        cmd = [
            "node", str(MD2PDF_BIN),
            "--launch-options",
            f'{{"executablePath":"{CHROME}","args":["--no-sandbox","--disable-setuid-sandbox"]}}',
            "--pdf-options",
            '{"format":"A4","margin":{"top":"20mm","bottom":"20mm","left":"15mm","right":"15mm"}}',
            "--stylesheet", str(STYLE_CSS),
            str(md_path),
        ]
        env    = {**os.environ, "PUPPETEER_EXECUTABLE_PATH": CHROME}
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)

        if result.returncode != 0:
            raise RuntimeError(f"md-to-pdf 失败: {result.stderr[:500]}")

        generated = md_path.with_suffix(".pdf")
        if generated.exists() and generated != pdf_path:
            generated.rename(pdf_path)