"""
打分服务 - 先分类，再多LLM并行评分
  · 步骤1: 分类LLM判断PPT类型（4选1）
  · 步骤2: 3个维度各由独立的LLM同时评判（asyncio.gather 并行）
            - 维度A: 叙事铺垫（起点与困境）  30分
            - 维度B: 破局·成效·数据          50分
            - 维度C: 升华·流畅度              20分
  · 步骤3: 所有维度完成后，由汇总LLM生成 strengths/weaknesses/suggestions/summary
  · 维度提示词均感知 ppt_type，实现类型定制化评分
"""
import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import requests

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_LLM_LOGS_DIR = Path(__file__).resolve().parent.parent / "llm_logs"
_LLM_LOGS_DIR.mkdir(exist_ok=True)


def _label_to_role(label: str) -> str:
    """Map an LLM call label to a canonical role name."""
    if "分类" in label:
        return "classify"
    if "narrative_setup" in label:
        return "narrative_setup"
    if "solution_results" in label:
        return "solution_results"
    if "elevation_fluency" in label:
        return "elevation_fluency"
    if "汇总" in label:
        return "summary"
    return "other"


def _llm_log(label: str, kind: str, text: str) -> None:
    """
    Append reasoning or output to a per-role daily log file.
    kind: 'reasoning' | 'output'
    """
    role = _label_to_role(label)
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_path = _LLM_LOGS_DIR / f"{date_str}_{role}_{kind}.log"
    sep = "=" * 80
    ts  = datetime.now().strftime("%H:%M:%S")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n{sep}\n[{ts}] {label}\n{sep}\n{text}\n")


def _load_prompt(filename: str) -> str:
    p = _PROMPTS_DIR / filename
    if not p.exists():
        raise FileNotFoundError(f"提示词文件不存在: {p}")
    return p.read_text(encoding="utf-8").strip()


_SCORING_CONFIG_PATH = Path(__file__).resolve().parent.parent / "scoring_config.json"

_SCORING_CONFIG_DEFAULT = {
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
    "relevance": {"low_cap_pct": 0.30, "mid_cap_pct": 0.75,
                  "low_threshold": 40, "high_threshold": 70},
    "prompt_files": {
        "narrative_setup":   "dimA_narrative.md",
        "solution_results":  "dimB_solution.md",
        "elevation_fluency": "dimC_elevation.md",
    },
}


def _load_scoring_config() -> dict:
    """Read scoring_config.json at call-time so admin changes take effect immediately."""
    try:
        return json.loads(_SCORING_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return _SCORING_CONFIG_DEFAULT


def _build_dimensions(cfg: dict, has_audio: bool) -> List[Tuple[str, str, int]]:
    """Build DIMENSIONS list from config for the current audio mode."""
    mode = "with_audio" if has_audio else "no_audio"
    pf   = cfg.get("prompt_files", _SCORING_CONFIG_DEFAULT["prompt_files"])
    dims = []
    for key, val in cfg.get(mode, _SCORING_CONFIG_DEFAULT[mode]).items():
        prompt_file = pf.get(key, f"{key}.md")
        dims.append((key, prompt_file, int(val["max_score"])))
    return dims


# ── PPT 类型枚举 ──────────────────────────────────────────────────────────────
PPT_TYPES = {
    "innovation":      "产品创新型",
    "troubleshooting": "问题解决型",
    "cost_reduction":  "降本增效型",
    "methodology":     "方法工具改进型",
}

# ── 维度配置（静态常量保持向后兼容，实际运行时用 _build_dimensions） ─────────
DIMENSIONS_WITH_AUDIO: List[Tuple[str, str, int]] = [
    ("narrative_setup",   "dimA_narrative.md", 45),
    ("solution_results",  "dimB_solution.md",  45),
    ("elevation_fluency", "dimC_elevation.md", 10),
]
DIMENSIONS_NO_AUDIO: List[Tuple[str, str, int]] = [
    ("narrative_setup",  "dimA_narrative.md", 50),
    ("solution_results", "dimB_solution.md",  50),
]
DIMENSIONS = DIMENSIONS_WITH_AUDIO


class ScoringService:
    """先分类，再多LLM并行评分"""

    def __init__(self):
        self.api_key      = os.environ["LLM_API_KEY"]
        self.api_endpoint = os.getenv(
            "LLM_API_ENDPOINT",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        )
        self.model = os.getenv("LLM_MODEL", "qwen-plus")
        # Per-request reasoning buffer: role → reasoning_text
        # Reset at the start of each score_presentation call
        self._reasoning_buffer: dict[str, str] = {}
        logger.info(f"打分服务已初始化（分类+3维度并行模式），模型: {self.model}")

    def get_last_reasoning(self) -> dict[str, str]:
        """Return reasoning texts collected during the last scoring run."""
        return dict(self._reasoning_buffer)

    # ──────────────────────────────────────────────────────────────────────────
    #  公共入口
    # ──────────────────────────────────────────────────────────────────────────

    async def score_presentation(self, pdf_analysis: Dict, transcription: Dict, has_audio: bool = True) -> Dict:
        result, _, _ = await self.score_presentation_debug(pdf_analysis, transcription, has_audio)
        return result

    async def score_presentation_debug(
        self,
        pdf_analysis: Dict,
        transcription: Dict,
        has_audio: bool = True,
    ) -> Tuple[Dict, Dict, Dict]:
        """
        返回 (final_result, context_dict, raw_responses_dict)

        流程：
          1. 构建基础上下文
          2. 分类LLM → 确定 ppt_type_key / ppt_type_name
          3. 将类型写入上下文
          4. 并行调用3个维度LLM（维度提示词感知类型）
          5. 调用汇总LLM
        """
        self._reasoning_buffer = {}  # reset for this request
        logger.info(f"开始评分流程（{'有音频' if has_audio else '纯PPT/无音频'}模式）：分类 → 并行维度 → 汇总")
        # Load config fresh so admin changes take effect without restart
        cfg        = _load_scoring_config()
        dimensions = _build_dimensions(cfg, has_audio)
        try:
            # 1. 构建基础上下文（不含 type，供分类LLM使用）
            ctx = self._build_context(pdf_analysis, transcription)

            # 2. 分类LLM：判断 PPT 属于哪种类型
            logger.info("调用分类LLM...")
            ppt_type = await self._classify_presentation(ctx)
            logger.info(
                f"PPT类型识别完成: {ppt_type['type_name']}（{ppt_type['type_key']}）"
                f"  理由: {ppt_type['reasoning'][:60]}..."
            )

            # 3. 将类型信息写入上下文，供维度LLM使用
            ctx["ppt_type_key"]  = ppt_type["type_key"]
            ctx["ppt_type_name"] = ppt_type["type_name"]

            # 4. 并行调用维度LLM
            logger.info(f"并行启动 {len(dimensions)} 个维度LLM...")
            tasks = [
                self._call_dimension(dim_key, prompt_file, max_score, ctx)
                for dim_key, prompt_file, max_score in dimensions
            ]
            dim_outputs = await asyncio.gather(*tasks, return_exceptions=True)

            # 5. 整理各维度结果，失败的用默认分数兜底
            scores: Dict[str, Dict] = {}
            raw_dim: Dict[str, str] = {}
            for i, (dim_key, _, max_score) in enumerate(dimensions):
                outcome = dim_outputs[i]
                if isinstance(outcome, Exception):
                    logger.error(f"维度 {dim_key} 评分失败: {outcome}")
                    scores[dim_key] = self._default_dim_score(max_score)
                    raw_dim[dim_key] = str(outcome)
                else:
                    scores[dim_key], raw_dim[dim_key] = outcome
            logger.info("各维度评分全部完成，开始汇总...")
            summary_prompt = self._build_summary_prompt(scores, ctx, has_audio, dimensions)

            # 6. 调用汇总LLM（串行，在所有维度完成后），最多重试3次
            summary_raw = ""
            summary_parsed: Dict = {}
            for attempt in range(1, 4):
                try:
                    summary_raw = await asyncio.to_thread(self._call_llm_sync, summary_prompt, f"汇总(第{attempt}次)")
                    summary_parsed = self._parse_json_strict(summary_raw)
                    if attempt > 1:
                        logger.info(f"汇总LLM第{attempt}次重试成功")
                    break
                except Exception as e:
                    logger.warning(f"汇总LLM第{attempt}次失败: {e}" + ("，重试中..." if attempt < 3 else "，尝试清洗解析"))
                    if attempt < 3:
                        await asyncio.sleep(1.0)
            else:
                try:
                    summary_parsed = self._parse_json(summary_raw)
                    logger.info("汇总LLM清洗后解析成功")
                except Exception as e:
                    logger.error(f"汇总LLM彻底失败: {e}，使用空汇总")
                    summary_parsed = {}

            # 7. 计算总分 & 等级
            total_score = sum(v["score"] for v in scores.values())
            grade = self._calc_grade(total_score)

            final = {
                "has_audio":         has_audio,
                "ppt_type":          ppt_type,
                "scores":            scores,
                "total_score":       total_score,
                "grade":             grade,
                "dimension_details": summary_parsed.get("dimension_details", {}),
                "strengths":         summary_parsed.get("strengths",   []),
                "weaknesses":        summary_parsed.get("weaknesses",  []),
                "suggestions":       summary_parsed.get("suggestions", []),
                "summary":           summary_parsed.get("summary",     ""),
            }
            logger.info(f"评分完成，类型: {ppt_type['type_name']}，总分: {total_score}，等级: {grade}")
            return final, ctx, {
                "classification": ppt_type,
                "dimensions":     raw_dim,
                "summary":        summary_raw,
            }

        except Exception as e:
            logger.error(f"评分失败: {e}", exc_info=True)
            raise

    # ──────────────────────────────────────────────────────────────────────────
    #  分类（步骤2）
    # ──────────────────────────────────────────────────────────────────────────

    async def _classify_presentation(self, ctx: Dict) -> Dict:
        """
        调用分类LLM，返回 {type_key, type_name, reasoning}，最多重试3次
        """
        template = _load_prompt("llm_classify.md")
        prompt = template
        for k, v in ctx.items():
            prompt = prompt.replace(f"{{{k}}}", str(v))

        last_err: Exception | None = None
        raw = ""
        for attempt in range(1, 4):
            try:
                raw = await asyncio.to_thread(self._call_llm_sync, prompt, f"分类(第{attempt}次)")
                parsed = self._parse_json_strict(raw)
                type_key = parsed.get("type_key", "").lower().strip()
                if type_key not in PPT_TYPES:
                    logger.warning(f"分类LLM返回未知类型 '{type_key}'，使用 innovation 作默认")
                    type_key = "innovation"
                if attempt > 1:
                    logger.info(f"分类LLM第{attempt}次重试成功")
                return {
                    "type_key":  type_key,
                    "type_name": PPT_TYPES.get(type_key, parsed.get("type_name", "产品创新型")),
                    "reasoning": parsed.get("reasoning", ""),
                }
            except Exception as e:
                last_err = e
                logger.warning(f"分类LLM第{attempt}次失败: {e}" + ("，重试中..." if attempt < 3 else "，尝试清洗解析"))
                if attempt < 3:
                    await asyncio.sleep(1.0)

        # 3次都失败后清洗兜底
        try:
            parsed = self._parse_json(raw)
            type_key = parsed.get("type_key", "innovation").lower().strip()
            if type_key not in PPT_TYPES:
                type_key = "innovation"
            logger.info("分类LLM清洗后解析成功")
            return {
                "type_key":  type_key,
                "type_name": PPT_TYPES.get(type_key, parsed.get("type_name", "产品创新型")),
                "reasoning": parsed.get("reasoning", ""),
            }
        except Exception as e:
            logger.error(f"分类LLM彻底失败: {e}，使用默认类型")
            return {
                "type_key":  "innovation",
                "type_name": "产品创新型",
                "reasoning": "分类失败，使用默认类型",
            }

    # ──────────────────────────────────────────────────────────────────────────
    #  构建上下文（共享数据）
    # ──────────────────────────────────────────────────────────────────────────

    def _build_context(self, pdf_analysis: Dict, transcription: Dict) -> Dict:
        """提取所有维度 Prompt 需要的公共变量（ppt_type 在分类后由调用方填入）"""
        slide_parts = []
        for s in pdf_analysis.get("slides", []):
            part = f"[第{s['page_number']}页] {s.get('text_content', '')}"
            vc = s.get("visual_content", "").strip()
            if vc:
                part += f"\n  （图表说明：{vc}）"
            slide_parts.append(part)

        metrics   = transcription.get("speech_metrics", {})
        full_text = transcription.get("full_text", "")

        return {
            "total_slides":  pdf_analysis.get("total_slides", 0),
            "slides_text":   "\n".join(slide_parts),
            "duration":      f"{transcription.get('duration', 0):.1f}",
            "speech_rate":   metrics.get("speech_rate", 0),
            "pause_freq":    metrics.get("pause_frequency", 0),
            "filler_count":  metrics.get("filler_word_count", 0),
            "full_text":     full_text,
            # 以下两个字段在分类完成后由调用方填入
            "ppt_type_key":  "unknown",
            "ppt_type_name": "未分类",
        }

    # ──────────────────────────────────────────────────────────────────────────
    #  单维度调用（async，内部用 to_thread 调同步 HTTP）
    # ──────────────────────────────────────────────────────────────────────────

    async def _call_dimension(
        self,
        dim_key: str,
        prompt_file: str,
        max_score: int,
        ctx: Dict,
    ) -> Tuple[Dict, str]:
        """
        返回 (parsed_dim_score_dict, raw_llm_response_str)
        """
        template = _load_prompt(prompt_file)

        # Load scoring config for sub-ratio and relevance caps
        cfg         = _load_scoring_config()
        _sub_dim_cfg = cfg.get("sub_dimensions", {}).get(dim_key, {})
        sub_ratio   = _sub_dim_cfg.get("ratio", [12, 11, 11, 11])
        rel_cfg     = cfg.get("relevance", {})
        low_cap_pct = float(rel_cfg.get("low_cap_pct", 0.30))
        mid_cap_pct = float(rel_cfg.get("mid_cap_pct", 0.75))

        # 计算子维度满分（按 sub_ratio 独立等比缩放到 max_score）
        ratio_total  = sum(sub_ratio)
        sub_maxes    = [round(r / ratio_total * max_score) for r in sub_ratio]
        # 将舍入误差全部吸收到 sub1，保证四项满分之和恰好等于 max_score
        sub_maxes[0] = max_score - sum(sub_maxes[1:])
        sub1, sub2, sub3, sub4 = sub_maxes

        # 锚点区间辅助变量（低/中/高分界）
        def _anchors(sub_max: int):
            """sub1 使用 5/12 和 9/12 临界比例"""
            low    = round(sub_max * 5 / 12)
            mid_lo = low + 1
            mid_hi = round(sub_max * 9 / 12)
            hi_lo  = mid_hi + 1
            return low, mid_lo, mid_hi, hi_lo

        def _anchors_sub(sub_max: int):
            """sub2/3/4 使用 3/11 和 8/11 临界比例（与原逻辑一致）"""
            low    = max(1, round(sub_max * 3 / 11))
            mid_lo = low + 1
            mid_hi = round(sub_max * 8 / 11)
            hi_lo  = mid_hi + 1
            return low, mid_lo, mid_hi, hi_lo

        s1_low, s1_mlo, s1_mhi, s1_hlo = _anchors(sub1)
        s2_low, s2_mlo, s2_mhi, s2_hlo = _anchors_sub(sub2)
        s3_low, s3_mlo, s3_mhi, s3_hlo = _anchors_sub(sub3)
        s4_low, s4_mlo, s4_mhi, s4_hlo = _anchors_sub(sub4)

        # 相关性分数上限（仅有音频时有效）
        dim_cap_mid = round(mid_cap_pct * max_score)
        dim_cap_low = round(low_cap_pct * max_score)

        # 低相关时各子维度强制得分（满分的 low_cap_pct，最低1分）
        sub1_forced = max(1, round(sub1 * low_cap_pct))
        sub2_forced = max(1, round(sub2 * low_cap_pct))
        sub3_forced = max(1, round(sub3 * low_cap_pct))
        sub4_forced = max(1, round(sub4 * low_cap_pct))

        # 构建相关性门控块（无音频时为空）
        has_audio = bool(ctx.get("full_text", "").strip())
        if has_audio:
            forced_total = sub1_forced + sub2_forced + sub3_forced + sub4_forced
            consistency_check_block = (
                f"==== ⚡【第一步：主题相关性判断 — 必须先完成，再决定后续操作】====\n\n"
                f"请现在对比上方【PPT幻灯片内容摘要】与【演讲原文】，判断两者**核心主题**是否指向同一件事。\n"
                f"（核心主题 = PPT标题+章节议题 vs 演讲者反复强调的中心对象）\n\n"
                f"---\n\n"
                f"🔴 **判断为【低相关】**（＜40%话题重叠，或两者讲述完全不同的对象）\n"
                f"  典型例子：PPT主题为《AI technology scouting / 竞品扫描》，演讲全程讲《某具体零件设计》\n\n"
                f"  **→ 立即按以下规则填写JSON，然后直接跳到【输出格式】，不得继续阅读后文任何内容：**\n"
                f"  - 子维度1得分 = {sub1_forced}（满分{sub1}的30%，固定值不得更改）\n"
                f"  - 子维度2得分 = {sub2_forced}（满分{sub2}的30%，固定值不得更改）\n"
                f"  - 子维度3得分 = {sub3_forced}（满分{sub3}的30%，固定值不得更改）\n"
                f"  - 子维度4得分 = {sub4_forced}（满分{sub4}的30%，固定值不得更改）\n"
                f"  - total_score = {forced_total}\n"
                f"  - content_relevance = \"低\"\n"
                f"  - relevance_reason = 一句话说明：PPT核心议题是X，而演讲核心讲的是Y\n"
                f"  - overall_comment = 必须包含：①指出PPT主题与演讲内容的具体差异；②说明此分数为\n"
                f"    强制技术性赋分，无法反映演讲本身质量；③建议演讲者重新准备匹配PPT的演讲稿\n\n"
                f"---\n\n"
                f"🟡 **判断为【中相关】**（40%～70%话题重叠，大方向一致但有明显偏离）\n"
                f"  → 继续阅读第二步评分标准，正常打分，但 **total_score 不得超过 {dim_cap_mid} 分**\n"
                f"  → overall_comment 需具体说明演讲与PPT的偏离情况\n\n"
                f"🟢 **判断为【高相关】**（≥70%话题重叠，演讲深度展开了PPT内容）\n"
                f"  → 继续阅读第二步评分标准，正常打分，total_score 上限 {max_score} 分\n\n"
                f"---\n"
            )
        else:
            consistency_check_block = ""

        # 注入 dim_max_score 及子维度满分变量，让提示词感知当前满分
        local_ctx = {
            **ctx,
            "dim_max_score":            str(max_score),
            "consistency_check_block":  consistency_check_block,
            "sub_max_1": str(sub1),
            "sub_max_2": str(sub2),
            "sub_max_3": str(sub3),
            "sub_max_4": str(sub4),
            # sub1 锚点（5/12、9/12 临界）
            "sub_max_1_low":    str(s1_low),
            "sub_max_1_mid_lo": str(s1_mlo),
            "sub_max_1_mid_hi": str(s1_mhi),
            "sub_max_1_hi_lo":  str(s1_hlo),
            # sub2 锚点（3/11、8/11 临界）
            "sub_max_2_low":    str(s2_low),
            "sub_max_2_mid_lo": str(s2_mlo),
            "sub_max_2_mid":    str(s2_mhi),
            "sub_max_2_hi":     str(s2_hlo),
            # sub3 锚点
            "sub_max_3_low":    str(s3_low),
            "sub_max_3_mid_lo": str(s3_mlo),
            "sub_max_3_mid":    str(s3_mhi),
            "sub_max_3_hi":     str(s3_hlo),
            # sub4 锚点
            "sub_max_4_low":    str(s4_low),
            "sub_max_4_mid_lo": str(s4_mlo),
            "sub_max_4_mid":    str(s4_mhi),
            "sub_max_4_hi":     str(s4_hlo),
        }
        prompt = template
        for k, v in local_ctx.items():
            prompt = prompt.replace(f"{{{k}}}", str(v))
            
        last_err: Exception | None = None
        raw = ""
        for attempt in range(1, 4):
            try:
                raw = await asyncio.to_thread(self._call_llm_sync, prompt, f"{dim_key}(第{attempt}次)")
                parsed = self._parse_json_strict(raw)
                if attempt > 1:
                    logger.info(f"维度{dim_key} LLM第{attempt}次重试成功")
                break
            except Exception as e:
                last_err = e
                logger.warning(f"维度{dim_key} LLM第{attempt}次失败: {e}" + ("，重试中..." if attempt < 3 else "，尝试清洗解析"))
                if attempt < 3:
                    await asyncio.sleep(1.0)
        else:
            # 3次均失败，清洗兜底
            try:
                parsed = self._parse_json(raw)
                logger.info(f"维度{dim_key} LLM清洗后解析成功")
            except Exception as e:
                logger.error(f"维度{dim_key} LLM彻底失败: {e}，使用空结果")
                parsed = {}

        # 提示词输出 total_score / overall_comment / sub_dimensions / content_relevance
        # 兼容旧格式 score / comment
        score = float(parsed.get("total_score", parsed.get("score", max_score * 0.6)))
        score = max(0.0, min(float(max_score), score))

        # Python 侧强制执行相关性约束（双重保险 + 子维度同步）
        relevance = parsed.get("content_relevance", "高")
        sub_dims  = parsed.get("sub_dimensions", {})
        if has_audio:
            if relevance == "低":
                # 低相关：总分 ≤ low_cap_pct，且强制每个子维度得分
                score = min(score, dim_cap_low)
                for sub_key, sub_val in sub_dims.items():
                    if isinstance(sub_val, dict):
                        sub_max = float(sub_val.get("max_score", max_score / 4))
                        sub_val["score"] = max(1, round(sub_max * low_cap_pct))
            elif relevance == "中":
                # 中相关：总分 ≤ mid_cap_pct
                score = min(score, dim_cap_mid)

        dim_result = {
            "score":              score,
            "max_score":          max_score,
            "comment":            parsed.get("overall_comment", parsed.get("comment", "")),
            "sub_dimensions":     sub_dims,
            "content_relevance":  relevance,
            "relevance_reason":   parsed.get("relevance_reason", ""),
        }
        return dim_result, raw

    # ──────────────────────────────────────────────────────────────────────────
    #  汇总 Prompt 构建
    # ──────────────────────────────────────────────────────────────────────────

    def _build_summary_prompt(self, scores: Dict[str, Dict], ctx: Dict,
                               has_audio: bool = True, dimensions: List[Tuple[str, str, int]] = None) -> str:
        if dimensions is None:
            cfg        = _load_scoring_config()
            dimensions = _build_dimensions(cfg, has_audio)
        else:
            cfg = _load_scoring_config()

        template = _load_prompt("llm_summary.md")

        # ── 计算满分变量（与 _call_dimension 保持一致） ────────────────────
        dim_max  = {key: max_s for key, _, max_s in dimensions}
        dimA_max = dim_max.get("narrative_setup",  45)
        dimB_max = dim_max.get("solution_results", 45)

        # 子维度满分（从 sub_dimensions 读取，dimA 用于 summary 模板变量）
        _sub_dim_A   = cfg.get("sub_dimensions", {}).get("narrative_setup", {})
        sub_ratio    = _sub_dim_A.get("ratio", [12, 11, 11, 11])
        ratio_total  = sum(sub_ratio)
        _sub_maxes_A = [round(r / ratio_total * dimA_max) for r in sub_ratio]
        _sub_maxes_A[0] = dimA_max - sum(_sub_maxes_A[1:])
        sub1  = _sub_maxes_A[0]
        sub234 = _sub_maxes_A[1]   # sub2 满分（summary 模板用近似值）

        # ── dimC 条件块 ────────────────────────────────────────────────────
        if has_audio:
            dim_c_data = scores.get("elevation_fluency", {})
            dimC_result_str = (
                f"得分：{dim_c_data.get('score', '?')} / {dim_c_data.get('max_score', '?')}\n"
                f"评委点评：{dim_c_data.get('comment', '无')}"
            )
            dimC_block = (
                f"\n【维度C · 语言与呈现（满分10分）】\n{dimC_result_str}\n"
            )
            dimC_json_block = (
                ',\n        "dimension_c": {\n'
                '            "name": "语言与呈现",\n'
                '            "total_score": "X/10",\n'
                '            "brief_comment": "综合专项评委C的意见，用50字左右概括该维度的表现"\n'
                '        }'
            )
            dimC_task_note = "，并结合 `dimC_result` 的得分"
        else:
            dimC_block     = ""
            dimC_json_block = ""
            dimC_task_note  = ""

        # ── 构建 dimA / dimB result 字符串（包含子维度分数）────────────────
        def _dim_result(key: str) -> str:
            d = scores.get(key, {})
            relevance = d.get("content_relevance", "")
            relevance_str = ""
            if relevance and relevance not in ("高", "无需评估"):
                relevance_str = f"\n⚠️ 内容相关性：{relevance}（{d.get('relevance_reason', '')}）"
            sub_dims = d.get("sub_dimensions", {})
            sub_lines = ""
            if sub_dims:
                lines = []
                for sk, sv in sub_dims.items():
                    if isinstance(sv, dict):
                        lines.append(f"    · {sk}：{sv.get('score', '?')} / {sv.get('max_score', '?')} 分")
                if lines:
                    sub_lines = "\n子维度得分：\n" + "\n".join(lines)
            return (
                f"总分：{d.get('score', '?')} / {d.get('max_score', '?')}{relevance_str}{sub_lines}\n"
                f"评委点评：{d.get('comment', '无')}"
            )

        fmt_vars = {
            "dim_count":    "3" if has_audio else "2",
            "dimA_max":     str(dimA_max),
            "dimB_max":     str(dimB_max),
            "sub_max_1":    str(sub1),
            "sub_max_234":  str(sub234),
            "dimC_block":   dimC_block,
            "dimC_json_block": dimC_json_block,
            "dimC_task_note":  dimC_task_note,
            # 基础上下文
            "total_slides":  str(ctx.get("total_slides", "")),
            "duration":      str(ctx.get("duration", "")),
            "speech_rate":   str(ctx.get("speech_rate", "")),
            "full_text":     ctx.get("full_text", ""),
            "ppt_type_key":  ctx.get("ppt_type_key", ""),
            "ppt_type_name": ctx.get("ppt_type_name", ""),
            # 维度评分结果
            "dimA_result":  _dim_result("narrative_setup"),
            "dimB_result":  _dim_result("solution_results"),
        }

        prompt = template
        for k, v in fmt_vars.items():
            prompt = prompt.replace(f"{{{k}}}", str(v))

        return prompt

    # ──────────────────────────────────────────────────────────────────────────
    #  LLM 调用（同步，供 asyncio.to_thread 使用）
    # ──────────────────────────────────────────────────────────────────────────

    def _call_llm_sync(self, prompt: str, label: str = "") -> str:
        """调用通义千问 LLM API（OpenAI 兼容接口，同步）"""
        # Read settings at call-time so admin changes take effect without restart
        _settings_path = Path(__file__).resolve().parent.parent / "llm_settings.json"
        try:
            with open(_settings_path, encoding="utf-8") as _f:
                _settings = json.load(_f)
            model = _settings.get("model", self.model)
            enable_thinking = _settings.get("enable_thinking", False)
        except Exception:
            model = self.model
            enable_thinking = False

        logger.info(f"[LLM] 调用中: {label or '未命名'} (model={model}, thinking={enable_thinking})")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是一位专业的演讲评委，擅长从内容、结构、视觉设计、演讲技巧等多维度"
                        "评估PPT演讲。请严格按照要求的JSON格式输出评分结果，不要输出JSON以外的内容。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }
        # Enable thinking mode only for qwen3-* models that support it
        # Thinking mode requires more response time, so use a larger timeout
        if enable_thinking and model.startswith("qwen3"):
            payload["enable_thinking"] = True
            timeout = 300
        else:
            timeout = 120
        resp = requests.post(self.api_endpoint, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        message_obj = resp.json()["choices"][0]["message"]
        # Log reasoning content if present
        reasoning = message_obj.get("reasoning_content", "")
        content = message_obj["content"]

        # Write to per-role file logs (reasoning + output only, no prompt)
        if reasoning:
            logger.info(f"[LLM 思考过程] {label}: {reasoning[:300]}...")
            _llm_log(label, "reasoning", reasoning)
            # Accumulate into per-request buffer (keyed by role, last write wins per role)
            role = _label_to_role(label)
            self._reasoning_buffer[role] = reasoning
        _llm_log(label, "output", content)

        logger.info(f"[LLM] 完成: {label or '未命名'}")
        return content

    # ──────────────────────────────────────────────────────────────────────────
    #  工具函数
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_json_strict(raw: str) -> Dict:
        """严格解析：提取代码块后直接 json.loads，失败直接抛异常（供重试使用）"""
        text = raw.strip()
        if "```json" in text:
            s = text.find("```json") + 7
            e = text.find("```", s)
            text = text[s:e]
        elif "```" in text:
            s = text.find("```") + 3
            e = text.find("```", s)
            text = text[s:e]
        return json.loads(text.strip())

    @staticmethod
    def _parse_json(raw: str) -> Dict:
        """兜底解析：严格解析 → 清洗轻度控制字符 → 清洗全部控制字符，最终失败返回 {}"""
        import re
        try:
            text = raw.strip()
            if "```json" in text:
                s = text.find("```json") + 7
                e = text.find("```", s)
                text = text[s:e]
            elif "```" in text:
                s = text.find("```") + 3
                e = text.find("```", s)
                text = text[s:e]
            text = text.strip()
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
            cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', text)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass
            cleaned2 = re.sub(r'[\x00-\x1f]', ' ', text)
            return json.loads(cleaned2)
        except json.JSONDecodeError as exc:
            logger.error(f"JSON解析失败: {exc}\n原文: {raw[:200]}")
            return {}

    @staticmethod
    def _calc_grade(total: float) -> str:
        if total >= 90:
            return "A"
        if total >= 75:
            return "B"
        if total >= 60:
            return "C"
        return "D"

    @staticmethod
    def _default_dim_score(max_score: int) -> Dict:
        return {
            "score":     round(max_score * 0.6, 1),
            "max_score": max_score,
            "comment":   "该维度评分时发生错误，使用默认分数。",
        }

    def _get_default_scoring(self) -> Dict:
        """兜底：全部失败时的默认结果"""
        return {
            "ppt_type": {
                "type_key":  "unknown",
                "type_name": "未分类",
                "reasoning": "评分系统遇到错误",
            },
            "scores": {k: self._default_dim_score(m) for k, _, m in DIMENSIONS},
            "total_score": 60.0,
            "grade": "C",
            "strengths":   ["评分系统遇到错误"],
            "weaknesses":  ["无法生成详细评分"],
            "suggestions": ["请检查系统配置"],
            "summary":     "评分系统遇到错误，无法生成详细评分，请联系管理员。",
        }
