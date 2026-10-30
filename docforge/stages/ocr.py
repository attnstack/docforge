# 职责：OCR 适配层（可选依赖）。扫描页 -> 渲染位图 -> PaddleOCR 行级结果 -> Block。
#
# 面试点：适配器 + 运行时特性探测（capability probe）。PaddleOCR 3.x 把 2.x 的
# .ocr() 换成 .predict()、返回结构也变了；靠 hasattr 探测而不是固定 pin 一个大版本，
# 上游破坏性变更的影响被隔离在这一个文件里。

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from typing import Any, NamedTuple

from docforge.errors import OcrUnavailableError
from docforge.models import BBox

logger = logging.getLogger(__name__)


class OcrLine(NamedTuple):
    text: str
    bbox: BBox  # 像素坐标（调用方负责换算回 PDF pt）
    confidence: float


class BaseOcr(ABC):
    name: str = "base"

    @abstractmethod
    def recognize(self, image_path: str) -> list[OcrLine]:
        """识别一张图片，返回行级结果（像素坐标）。"""

    def warmup(self) -> None:  # 可选：模型预加载
        return None


class PaddleOcr(BaseOcr):
    """PaddleOCR 2.x/3.x 双代适配。懒加载：首次识别才 import + 载入模型。"""

    name = "paddle"

    def __init__(self, lang: str = "ch") -> None:
        self._lang = lang
        self._engine: Any = None
        self._mode: str | None = None  # "v2" | "v3"
        self._lock = threading.Lock()  # why：Paddle 非线程安全，批处理必须串行调用

    def warmup(self) -> None:
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._engine is not None:
                return
            try:
                from paddleocr import PaddleOCR  # noqa: F401 - 延迟导入，核心包不背 paddle 的安装体积
            except ImportError as exc:
                raise OcrUnavailableError("PaddleOCR 未安装") from exc
            logger.info("loading PaddleOCR model (lang=%s), first run downloads weights", self._lang)
            try:
                # 最小参数集：2.x/3.x 均兼容；方向分类等增强参数留给上游默认值
                self._engine = PaddleOCR(lang=self._lang)
            except Exception as exc:  # noqa: BLE001 - paddle 初始化失败形态不可枚举
                raise OcrUnavailableError(f"PaddleOCR 初始化失败: {exc}") from exc
            # 特性探测：3.x 提供 predict，2.x 只有 ocr
            self._mode = "v3" if hasattr(self._engine, "predict") else "v2"
            logger.info("PaddleOCR ready (api=%s)", self._mode)

    def recognize(self, image_path: str) -> list[OcrLine]:
        self._ensure_loaded()
        assert self._engine is not None and self._mode is not None
        with self._lock:
            if self._mode == "v3":
                return self._parse_v3(self._engine.predict(image_path))
            return self._parse_v2(self._engine.ocr(image_path, cls=True))

    def _parse_v2(self, raw: Any) -> list[OcrLine]:
        """2.x: [[ [box4pts, (text, conf)], ... ], [None], ...]"""
        lines: list[OcrLine] = []
        for page_result in raw or []:
            if not page_result:
                continue
            for box, (text, conf) in page_result:
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                if text and text.strip():
                    lines.append(OcrLine(text.strip(), BBox(min(xs), min(ys), max(xs), max(ys)), float(conf)))
        return lines

    def _parse_v3(self, raw: Any) -> list[OcrLine]:
        """3.x: list[OCRResult]，dict 风格字段 rec_texts / rec_scores / rec_polys。"""
        lines: list[OcrLine] = []
        for res in raw or []:
            texts = res.get("rec_texts") or []
            scores = res.get("rec_scores") or []
            polys = res.get("rec_polys") or res.get("rec_boxes") or []
            for i, text in enumerate(texts):
                if not text or not text.strip() or i >= len(polys):
                    continue
                poly = polys[i]
                xs = [float(p[0]) for p in poly]
                ys = [float(p[1]) for p in poly]
                conf = float(scores[i]) if i < len(scores) else 0.0
                lines.append(OcrLine(text.strip(), BBox(min(xs), min(ys), max(xs), max(ys)), conf))
        return lines


# OCR 引擎单例：进程内共享一个模型实例（显存/内存友好），调用串行化在类内部完成
_OCR: BaseOcr | None = None
_OCR_CREATE_LOCK = threading.Lock()


def get_ocr() -> BaseOcr:
    global _OCR
    if _OCR is None:
        with _OCR_CREATE_LOCK:
            if _OCR is None:
                _OCR = PaddleOcr()
    return _OCR


def lines_to_paragraphs(ordered_lines: list[Any], page_no: int, cfg_dpi_scale: float = 1.0) -> list[Any]:
    """把阅读序相邻的 OCR 行合并成段落块。

    合并条件（同时满足）：阅读序相邻、垂直间距 <= 0.8 x 行高、水平重叠 >= 25% 较窄行宽。
    why 先排序后合并：扫描页直接按 y 合并会在双栏页把左右栏的行串起来，
    必须先让阅读顺序还原用分栏约束排好序，再沿顺序合并。
    """
    from docforge.models import Block, BlockType

    if not ordered_lines:
        return []
    heights = sorted(b.bbox.height for b in ordered_lines)
    median_h = max(heights[len(heights) // 2], 1.0)
    merged: list[Block] = []
    for line in ordered_lines:
        if merged:
            prev = merged[-1]
            gap = line.bbox.y0 - prev.bbox.y1
            overlap = prev.bbox.x_overlap(line.bbox)
            narrow = min(prev.bbox.width, line.bbox.width)
            if gap <= 0.8 * max(prev.bbox.height, median_h) and overlap >= 0.25 * narrow:
                prev.bbox = prev.bbox.union(line.bbox)
                from docforge.textutil import smart_join

                prev.text = smart_join([prev.text, line.text])
                prev.confidence = (prev.confidence + line.confidence) / 2
                continue
        merged.append(
            Block(
                id=f"p{page_no}-o{len(merged)}",
                page=page_no,
                bbox=line.bbox,
                type=BlockType.TEXT,
                text=line.text,
                confidence=line.confidence,
                meta={"source": "ocr"},
            )
        )
    return merged
