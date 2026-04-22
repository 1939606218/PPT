"""
数据模型定义
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Optional


class SlideInfo(BaseModel):
    """单页幻灯片信息"""
    page_number: int
    text_content: str
    layout_type: str
    has_images: bool
    has_charts: bool
    color_scheme: str
    text_density: str
    visual_hierarchy: str


class LayoutQuality(BaseModel):
    """布局质量"""
    consistency: float
    balance: float
    whitespace: float
    alignment: float


class ContentStructure(BaseModel):
    """内容结构"""
    has_title_slide: bool
    has_outline: bool
    has_conclusion: bool
    logical_flow: str
    section_division: str


class VisualElements(BaseModel):
    """视觉元素"""
    image_quality: str
    chart_effectiveness: str
    color_harmony: str
    font_consistency: str
    animation_usage: str


class PDFAnalysisResult(BaseModel):
    """PDF分析结果"""
    slides: List[SlideInfo]
    layout_quality: LayoutQuality
    content_structure: ContentStructure
    visual_elements: VisualElements
    total_slides: int


class TranscriptionSegment(BaseModel):
    """转录分段"""
    start: float
    end: float
    text: str


class SpeechMetrics(BaseModel):
    """语音指标"""
    speech_rate: int = Field(description="语速（字/分钟）")
    pause_frequency: int = Field(description="停顿次数")
    average_pause_duration: float = Field(description="平均停顿时长（秒）")
    volume_variance: float = Field(description="音量变化")
    clarity: float = Field(description="清晰度评分")
    confidence_level: float = Field(description="识别置信度")


class TranscriptionResult(BaseModel):
    """转录结果"""
    full_text: str
    segments: List[TranscriptionSegment]
    duration: float
    speech_metrics: SpeechMetrics


class ScoreDetail(BaseModel):
    """评分详情"""
    score: float
    comment: str


class ScoringResult(BaseModel):
    """评分结果"""
    scores: Dict[str, ScoreDetail]
    total_score: float
    grade: str
    strengths: List[str]
    weaknesses: List[str]
    suggestions: List[str]
    summary: str


class AnalysisResult(BaseModel):
    """完整分析结果"""
    pdf_analysis: PDFAnalysisResult
    transcription: TranscriptionResult
    scoring: ScoringResult
    report_path: str
