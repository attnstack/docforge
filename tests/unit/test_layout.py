# 职责：版面语义标注单测：页眉页脚跨页剔除（含数字归一化）、标题层级判定。

from __future__ import annotations

from docforge.config import HeadingConfig, LayoutConfig
from docforge.models import BBox, Block, BlockType, PageResult
from docforge.stages.layout import detect_headings, remove_headers_footers


def page(no: int, blocks: list[Block]) -> PageResult:
    return PageResult(number=no, width=595, height=842, blocks=blocks)


def blk(i: int, x0: float, y0: float, x1: float, y1: float, text: str, size: float | None = None) -> Block:
    meta = {"font_size": size} if size else {"source": "ocr"}
    return Block(id=f"b{i}", page=0, bbox=BBox(x0, y0, x1, y1), type=BlockType.TEXT, text=text, meta=meta)


# ---------- 页眉页脚 ----------


def test_repeated_header_footer_removed():
    pages = []
    for pno in range(3):
        body = [blk(0, 72, 200, 523, 240, f"正文内容{pno}")]
        header = blk(1, 72, 40, 523, 60, "华信科技年度报告")
        footer = blk(2, 72, 800, 523, 820, f"第 {pno + 1} 页")
        pages.append(page(pno, body + [header, footer]))
    removed = remove_headers_footers(pages, LayoutConfig())
    assert removed == 6
    for pr in pages:
        types = {b.type for b in pr.blocks}
        assert BlockType.PAGE_HEADER in types and BlockType.PAGE_FOOTER in types


def test_one_page_doc_not_removed():
    """单页文档无法建立"跨页重复"证据：不剔除。"""
    pr = page(0, [blk(0, 72, 40, 523, 60, "可能是标题也可能是页眉")])
    assert remove_headers_footers([pr], LayoutConfig()) == 0


def test_unique_top_text_kept():
    """只在 1 页出现的页顶文本：保留（可能是正文首段）。"""
    pages = [
        page(0, [blk(0, 72, 40, 523, 60, "独有文字 A"), blk(1, 72, 200, 523, 240, "正文")]),
        page(1, [blk(2, 72, 40, 523, 60, "独有文字 B"), blk(3, 72, 200, 523, 240, "正文")]),
    ]
    assert remove_headers_footers(pages, LayoutConfig()) == 0


# ---------- 标题 ----------


def test_heading_levels_by_font_size():
    pr = page(
        0,
        [
            blk(0, 72, 80, 523, 110, "文档主标题", size=18),
            blk(1, 72, 140, 523, 165, "一级章节", size=14),
            blk(2, 72, 200, 523, 220, "小节标题", size=12),
            blk(3, 72, 260, 523, 400, "正文文本正文文本", size=10.5),
        ],
    )
    detect_headings([pr], HeadingConfig())
    assert pr.blocks[0].heading_level == 1
    assert pr.blocks[1].heading_level == 2
    assert pr.blocks[2].heading_level == 3
    assert pr.blocks[3].type == BlockType.TEXT


def test_sentence_ending_line_not_heading():
    """大字号但以句号收尾的长句：不是标题。"""
    pr = page(0, [blk(0, 72, 80, 523, 120, "这句话用大字排版但以句号结束。", size=18)])
    detect_headings([pr], HeadingConfig())
    assert pr.blocks[0].type == BlockType.TEXT


def test_ocr_blocks_skipped():
    """扫描页块无字号元数据：不参与标题判定。"""
    pr = page(0, [blk(0, 72, 80, 523, 120, "OCR文本", size=None)])
    detect_headings([pr], HeadingConfig())
    assert pr.blocks[0].type == BlockType.TEXT
