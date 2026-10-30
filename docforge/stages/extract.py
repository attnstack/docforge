# 职责：从 PDF 页面提取原始素材——文字块（含字号/加粗）、词、矢量线段、图像块。
# 只提取不解释：语义判断（页眉页脚/标题/表格）全部在后续阶段。

from __future__ import annotations

from dataclasses import dataclass, field

from docforge._pymupdf import fitz
from docforge.models import BBox, Seg, Word


@dataclass
class RawSpan:
    text: str
    size: float
    bold: bool
    bbox: BBox


@dataclass
class RawLine:
    bbox: BBox
    spans: list[RawSpan]


@dataclass
class RawBlock:
    bbox: BBox
    lines: list[RawLine]
    max_font_size: float
    bold: bool


@dataclass
class PageRaw:
    width: float
    height: float
    char_count: int = 0  # 文字层总字符数：扫描页判定的依据
    text_blocks: list[RawBlock] = field(default_factory=list)
    image_bboxes: list[BBox] = field(default_factory=list)
    words: list[Word] = field(default_factory=list)
    segments: list[Seg] = field(default_factory=list)  # 水平/垂直线段（表格识别输入）


def _union_bbox(bboxes: list[BBox]) -> BBox:
    out = bboxes[0]
    for b in bboxes[1:]:
        out = out.union(b)
    return out


def _segments_from_drawings(page: fitz.Page) -> list[Seg]:
    """把 PDF 矢量绘图指令还原成轴对齐线段。

    why：表格框线在 PDF 里可能是 line 指令、也可能是 rect 指令（每边一条），
    甚至整表一个大 rect；三条路都要还原成统一线段，表格网格聚类才稳定。
    斜线（装饰/手写批注）直接丢弃。
    """
    segs: list[Seg] = []
    try:
        drawings = page.get_drawings()
    except Exception:  # noqa: BLE001 - 个别损坏页面的绘图流解析失败，降级为无线段
        return []
    for dr in drawings:
        for item in dr.get("items", []):
            op = item[0]
            if op == "l":
                p1, p2 = item[1], item[2]
                seg = Seg(p1.x, p1.y, p2.x, p2.y)
                if seg.is_horizontal or seg.is_vertical:
                    segs.append(seg)
            elif op == "re":
                r = item[1]
                segs.extend(
                    [
                        Seg(r.x0, r.y0, r.x1, r.y0),
                        Seg(r.x0, r.y1, r.x1, r.y1),
                        Seg(r.x0, r.y0, r.x0, r.y1),
                        Seg(r.x1, r.y0, r.x1, r.y1),
                    ]
                )
    return segs


def extract_page(page: fitz.Page) -> PageRaw:
    rect = page.rect
    raw = PageRaw(width=rect.width, height=rect.height)
    data = page.get_text("dict")
    for blk in data.get("blocks", []):
        if blk.get("type") == 1:  # 图像块
            raw.image_bboxes.append(BBox(*blk["bbox"]))
            continue
        lines: list[RawLine] = []
        max_size = 0.0
        any_bold = False
        for line in blk.get("lines", []):
            spans: list[RawSpan] = []
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text.strip():
                    continue
                raw.char_count += len(text.strip())
                bold = bool(span.get("flags", 0) & 16)  # bit4 = bold
                spans.append(RawSpan(text=text, size=span.get("size", 0.0), bold=bold, bbox=BBox(*span["bbox"])))
                max_size = max(max_size, span.get("size", 0.0))
                any_bold = any_bold or bold
            if spans:
                lines.append(RawLine(bbox=_union_bbox([s.bbox for s in spans]), spans=spans))
        if lines:
            raw.text_blocks.append(
                RawBlock(bbox=_union_bbox([ln.bbox for ln in lines]), lines=lines, max_font_size=max_size, bold=any_bold)
            )

    raw.words = [Word(x0, y0, x1, y1, t) for x0, y0, x1, y1, t, *_ in page.get_text("words")]
    raw.segments = _segments_from_drawings(page)
    return raw
