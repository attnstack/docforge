# 职责：核心数据模型（Block/Seg/Word/Document）。全流水线的中间表示。
# 设计原则：与 PDF 库解耦——阅读顺序、表格还原、导出只依赖这里的纯数据结构，
# 因此可以脱离 PDF 文件直接做单元测试（这是可测性的根基）。

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class BlockType(str, Enum):
    TEXT = "text"
    HEADING = "heading"
    TABLE = "table"
    IMAGE = "image"
    PAGE_HEADER = "page_header"
    PAGE_FOOTER = "page_footer"


@dataclass
class BBox:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2

    def contains_point(self, x: float, y: float, margin: float = 0.0) -> bool:
        return self.x0 - margin <= x <= self.x1 + margin and self.y0 - margin <= y <= self.y1 + margin

    def union(self, other: "BBox") -> "BBox":
        return BBox(min(self.x0, other.x0), min(self.y0, other.y0), max(self.x1, other.x1), max(self.y1, other.y1))

    def x_overlap(self, other: "BBox") -> float:
        return max(0.0, min(self.x1, other.x1) - max(self.x0, other.x0))


@dataclass
class Seg:
    """轴线段（水平或垂直），表格识别的输入。斜线在提取阶段被过滤。"""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def is_horizontal(self) -> bool:
        return abs(self.y1 - self.y0) <= 0.5 and abs(self.x1 - self.x0) > 0.5

    @property
    def is_vertical(self) -> bool:
        return abs(self.x1 - self.x0) <= 0.5 and abs(self.y1 - self.y0) > 0.5

    @property
    def length(self) -> float:
        return max(abs(self.x1 - self.x0), abs(self.y1 - self.y0))

    @property
    def mid_y(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def mid_x(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class Word:
    """PDF 中的词（PyMuPDF words 语义）：用于表格单元格文本归属。"""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class Block:
    id: str
    page: int
    bbox: BBox
    type: BlockType = BlockType.TEXT
    text: str = ""
    heading_level: int | None = None
    reading_order: int | None = None
    confidence: float = 1.0
    table_html: str | None = None
    table_md: str | None = None
    image_path: str | None = None
    continues_prev: bool = False  # 跨页段落续接标记（导出/提交时据此合并）
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class PageResult:
    number: int  # 0-based
    width: float
    height: float
    blocks: list[Block]
    columns: list[tuple[float, float]] = field(default_factory=list)  # 主分栏 x 范围（调试/联动）
    is_scanned: bool = False


@dataclass
class Document:
    path: str
    pages: list[PageResult]
    blocks: list[Block]
    stage_ms: dict[str, float] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def ordered_blocks(self) -> list[Block]:
        """按阅读顺序返回全部已排序块（含页眉页脚，导出层负责剔除）。"""
        return sorted(
            (b for b in self.blocks if b.reading_order is not None),
            key=lambda b: (b.page, b.reading_order or 0),
        )
