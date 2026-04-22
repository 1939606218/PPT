"""
PDF/PPT/PPTX 分析服务 - 使用 PyMuPDF 将 PDF 转为图片，再用通义千问VL模型分析每页内容
支持格式：.pdf / .pptx / .ppt（PPTX/PPT 通过 LibreOffice 先转为 PDF）
"""
import os
import base64
import json
import logging
import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List

import requests

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
#  提示词（从 prompts/ 目录读取，方便修改）                              #
# ------------------------------------------------------------------ #

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

def _load_prompt(filename: str) -> str:
    """从 prompts/ 目录读取提示词文件"""
    p = _PROMPTS_DIR / filename
    if not p.exists():
        raise FileNotFoundError(f"提示词文件不存在: {p}")
    return p.read_text(encoding="utf-8").strip()


SLIDE_ANALYSIS_PROMPT = _load_prompt("vl_slide_analysis.md")

SLIDES_SUMMARY_PROMPT = """根据以下PPT各页内容摘要，一次性返回三项整体评估，以JSON格式输出（只返回JSON，不要有任何其他内容）：
{slides_summary}

返回格式：
{{
    "layout_quality": {{
        "consistency": 布局一致性评分（0.0~1.0）,
        "balance": 视觉平衡评分（0.0~1.0）,
        "whitespace": 留白合理性评分（0.0~1.0）,
        "alignment": 对齐程度评分（0.0~1.0）
    }},
    "content_structure": {{
        "has_title_slide": true或false,
        "has_outline": true或false,
        "has_conclusion": true或false,
        "logical_flow": "选一个：poor/fair/good/excellent",
        "section_division": "选一个：unclear/fair/clear/very_clear"
    }},
    "visual_elements": {{
        "image_quality": "图片质量：high/medium/low",
        "chart_effectiveness": "图表有效性：excellent/good/fair/poor",
        "color_harmony": "配色协调性：excellent/good/fair/poor",
        "font_consistency": "字体一致性：excellent/good/fair/poor",
        "animation_usage": "动画使用：appropriate/excessive/insufficient/none"
    }}
}}"""


# 并发分析幻灯片时的最大同时请求数
VL_CONCURRENCY = 5


class PDFAnalyzer:
    """PDF内容分析器，使用通义千问VL模型识别和分析PDF"""

    def __init__(self):
        self.api_key = os.environ["VL_MODEL_API_KEY"]
        self.vl_endpoint = os.getenv(
            "VL_MODEL_ENDPOINT",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        )
        self.llm_endpoint = os.getenv(
            "LLM_API_ENDPOINT",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        )
        self.vl_model = os.getenv("VL_MODEL_NAME", "qwen-vl-plus")
        self.llm_model = os.getenv("LLM_MODEL", "qwen-plus")
        logger.info(f"PDF分析器已初始化，VL模型: {self.vl_model}")
    
    # ------------------------------------------------------------------ #
    #  公共入口：自动识别格式（PDF / PPTX / PPT）                          #
    # ------------------------------------------------------------------ #

    async def analyze_file(self, file_path: Path, progress_cb=None) -> Dict:
        """
        统一入口，自动处理 .pdf / .pptx / .ppt 格式。
        PPTX/PPT 会先通过 LibreOffice headless 转换为 PDF，再轰入分析流程。
        """
        suffix = file_path.suffix.lower()
        if suffix in (".pptx", ".ppt"):
            logger.info(f"检测到 {suffix.upper()} 文件，正在使用 LibreOffice 转换为 PDF...")
            pdf_path = await asyncio.to_thread(self._pptx_to_pdf, file_path)
            try:
                return await self.analyze_pdf(pdf_path, progress_cb=progress_cb)
            finally:
                # 删除临时 PDF
                try:
                    pdf_path.unlink(missing_ok=True)
                    pdf_path.parent.rmdir()  # 删除临时目录（若为空）
                except Exception:
                    pass
        else:
            return await self.analyze_pdf(file_path, progress_cb=progress_cb)

    # ------------------------------------------------------------------ #
    #  PPTX/PPT → PDF（LibreOffice headless）                              #
    # ------------------------------------------------------------------ #

    def _pptx_to_pdf(self, pptx_path: Path) -> Path:
        """
        调用 LibreOffice headless 将 PPTX/PPT 转换为 PDF。
        返回转换后的 PDF 路径（存放在临时目录中）。
        """
        tmp_dir = Path(tempfile.mkdtemp(prefix="ppt2pdf_"))
        cmd = [
            "libreoffice", "--headless", "--norestore",
            "--convert-to", "pdf",
            "--outdir", str(tmp_dir),
            str(pptx_path),
        ]
        logger.info(f"LibreOffice 转换命令: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(
                f"LibreOffice 转换失败 (code={result.returncode}): {result.stderr.strip()}"
            )
        pdf_path = tmp_dir / (pptx_path.stem + ".pdf")
        if not pdf_path.exists():
            # 部分版本输出文件名略有不同，搜尋任意 pdf
            found = list(tmp_dir.glob("*.pdf"))
            if not found:
                raise RuntimeError(f"LibreOffice 转换完成但找不到输出 PDF，临时目录: {tmp_dir}")
            pdf_path = found[0]
        logger.info(f"LibreOffice 转换完成: {pdf_path}")
        return pdf_path

    # ------------------------------------------------------------------ #
    #  主入口                                                              #
    # ------------------------------------------------------------------ #

    async def analyze_pdf(self, pdf_path: Path, progress_cb=None) -> Dict:
        """
        分析PDF文件，返回结构化分析结果。
        流程：PDF → 每页PNG(base64) → VL逐页分析 → LLM汇总
        """
        logger.info(f"开始分析PDF: {pdf_path}")
        try:
            # 步骤1：PDF 转图片
            images_b64 = self._pdf_to_images_base64(pdf_path)
            logger.info(f"PDF转图片完成，共 {len(images_b64)} 页")

            # 步骤2：VL 模型逐页分析
            slides_analysis = await self._analyze_slides(images_b64, progress_cb)

            # 步骤3：LLM 一次性汇总（布局/结构/视觉元素）
            slides_summary = json.dumps(
                [{"page": s["page_number"],
                  "text_density": s.get("text_density", ""),
                  "has_images": s.get("has_images", False),
                  "has_charts": s.get("has_charts", False),
                  "visual_content": s.get("visual_content", "")}
                 for s in slides_analysis],
                ensure_ascii=False, indent=2
            )

            summary = await self._analyze_slides_summary(slides_summary)
            layout_quality    = summary.get("layout_quality",    {})
            content_structure = summary.get("content_structure", {})
            visual_elements   = summary.get("visual_elements",   {})

            result = {
                "slides": slides_analysis,
                "layout_quality": layout_quality,
                "content_structure": content_structure,
                "visual_elements": visual_elements,
                "total_slides": len(slides_analysis)
            }
            logger.info(f"PDF分析完成，共 {len(slides_analysis)} 页")
            return result

        except Exception as e:
            logger.error(f"PDF分析失败: {e}", exc_info=True)
            raise

    # ------------------------------------------------------------------ #
    #  PDF → Base64 图片列表（PyMuPDF）                                    #
    # ------------------------------------------------------------------ #

    def _pdf_to_images_base64(self, pdf_path: Path, dpi: int = 150) -> List[str]:
        """
        使用 PyMuPDF 将 PDF 每页渲染为 PNG，返回 base64 编码列表。
        dpi=150 在清晰度和传输大小之间取得平衡。
        """
        import fitz  # PyMuPDF

        images = []
        doc = fitz.open(str(pdf_path))
        # fitz 默认坐标系为 72 dpi，scale = target_dpi / 72
        scale = dpi / 72.0
        mat = fitz.Matrix(scale, scale)

        for page_index, page in enumerate(doc):
            pix = page.get_pixmap(matrix=mat, alpha=False)
            png_bytes = pix.tobytes("png")
            b64 = base64.b64encode(png_bytes).decode("utf-8")
            images.append(b64)
            logger.debug(f"  第{page_index + 1}页转换完成，图片大小: {len(png_bytes) // 1024}KB")

        doc.close()
        return images

    # ------------------------------------------------------------------ #
    #  VL 模型逐页分析                                                     #
    # ------------------------------------------------------------------ #

    async def _analyze_slides(self, images_b64: List[str], progress_cb=None) -> List[Dict]:
        """并发调用 VL 模型分析幻灯片，最多 VL_CONCURRENCY 个同时请求"""
        semaphore = asyncio.Semaphore(VL_CONCURRENCY)
        total = len(images_b64)
        completed = 0

        async def analyze_one(i: int, b64: str) -> Dict:
            nonlocal completed
            async with semaphore:
                page_no = i + 1
                logger.info(f"  VL分析第 {page_no}/{total} 页...")
                slide_info = None
                last_err: Exception | None = None

                # ── 第一阶段：最多重试 3 次（重新调用 VL 模型 + 解析）──────────
                for attempt in range(1, 4):
                    try:
                        raw = await asyncio.to_thread(
                            self._call_vl_model_api, b64, SLIDE_ANALYSIS_PROMPT
                        )
                        slide_info = self._parse_json_strict(raw)
                        slide_info["page_number"] = page_no
                        if attempt > 1:
                            logger.info(f"  第{page_no}页VL分析第{attempt}次重试成功")
                        break
                    except Exception as e:
                        last_err = e
                        logger.warning(
                            f"  第{page_no}页VL分析第{attempt}次失败: {e}"
                            + ("，重试中..." if attempt < 3 else "，进入清洗阶段")
                        )
                        if attempt < 3:
                            await asyncio.sleep(1.0)  # 稍等再重试

                # ── 第二阶段：清洗控制字符后再解析（不再重新调用模型）──────────
                if slide_info is None:
                    try:
                        # raw 是最后一次模型返回的原始文本
                        slide_info = self._parse_json_response(raw)  # type: ignore[possibly-undefined]
                        slide_info["page_number"] = page_no
                        logger.info(f"  第{page_no}页VL分析清洗后解析成功")
                    except Exception as e:
                        logger.warning(f"  第{page_no}页VL分析彻底失败，使用默认值: {e}")
                        slide_info = self._default_slide_info(page_no)

                completed += 1
                if progress_cb:
                    progress_cb(completed, total)
                return slide_info

        results = await asyncio.gather(*[analyze_one(i, b64) for i, b64 in enumerate(images_b64)])
        # 按页码排序（gather 保序，但明确保证）
        return sorted(results, key=lambda s: s["page_number"])

    # ------------------------------------------------------------------ #
    #  LLM 汇总分析                                                        #
    # ------------------------------------------------------------------ #

    async def _analyze_slides_summary(self, slides_summary: str) -> Dict:
        """LLM 一次性评估布局质量、内容结构、视觉元素"""
        prompt = SLIDES_SUMMARY_PROMPT.format(slides_summary=slides_summary)
        try:
            raw = self._call_llm_api(prompt)
            return self._parse_json_response(raw)
        except Exception as e:
            logger.warning(f"页面汇总分析失败: {e}")
            return {
                "layout_quality":    {"consistency": 0.75, "balance": 0.75, "whitespace": 0.75, "alignment": 0.75},
                "content_structure": {"has_title_slide": True, "has_outline": False, "has_conclusion": False, "logical_flow": "fair", "section_division": "fair"},
                "visual_elements":   {"image_quality": "medium", "chart_effectiveness": "fair", "color_harmony": "fair", "font_consistency": "fair", "animation_usage": "none"},
            }

    # ------------------------------------------------------------------ #
    #  API 调用封装                                                         #
    # ------------------------------------------------------------------ #

    def _call_vl_model_api(self, image_b64: str, prompt: str) -> str:
        """调用通义千问 VL 模型（OpenAI 兼容接口）"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.vl_model,
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"}
                    },
                    {"type": "text", "text": prompt}
                ]
            }],
            "max_tokens": 2000
        }
        resp = requests.post(self.vl_endpoint, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _call_llm_api(self, prompt: str) -> str:
        """调用通义千问 LLM（OpenAI 兼容接口）"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 800
        }
        resp = requests.post(self.llm_endpoint, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    # ------------------------------------------------------------------ #
    #  工具方法                                                             #
    # ------------------------------------------------------------------ #

    def _parse_json_strict(self, text: str) -> Dict:
        """严格解析：提取 JSON 代码块后直接 json.loads，失败直接抛异常（供重试使用）"""
        text = text.strip()
        if "```json" in text:
            text = text[text.find("```json") + 7: text.rfind("```")].strip()
        elif "```" in text:
            text = text[text.find("```") + 3: text.rfind("```")].strip()
        return json.loads(text)

    def _parse_json_response(self, text: str) -> Dict:
        """兜底解析：先严格解析，失败则清洗控制字符后再尝试（用于重试全部失败后）"""
        import re
        text = text.strip()
        if "```json" in text:
            text = text[text.find("```json") + 7: text.rfind("```")].strip()
        elif "```" in text:
            text = text[text.find("```") + 3: text.rfind("```")].strip()
        # 第一次：严格解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # 第二次：清洗轻度控制字符（保留 \t \n \r）
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        # 第三次：清洗全部控制字符
        cleaned2 = re.sub(r'[\x00-\x1f]', ' ', text)
        return json.loads(cleaned2)

    def _default_slide_info(self, page_number: int) -> Dict:
        """分析失败时的默认页面信息"""
        return {
            "page_number": page_number,
            "text_content": "",
            "visual_content": "",
            "has_images": False,
            "has_charts": False,
            "text_density": "medium",
        }

