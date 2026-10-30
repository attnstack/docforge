# 职责：阅读顺序还原算法单测（正常/边界/异常三类），纯数据构造、不依赖 PDF 文件。

from __future__ import annotations

from docforge.config import LayoutConfig
from docforge.models import BBox, Block, BlockType
from docforge.stages.reading_order import page_reading_order

CFG = LayoutConfig()


def mk(i: int, x0: float, y0: float, x1: float, y1: float, text: str = "") -> Block:
    return Block(
        id=f"b{i}",
        page=0,
        bbox=BBox(x0, y0, x1, y1),
        type=BlockType.TEXT,
        text=text or f"块{i}",
    )


def ids(blocks: list[Block]) -> list[str]:
    return [b.id for b in blocks]


# ---------- 正常 ----------


def test_single_column_top_down():
    blocks = [mk(0, 72, 100, 520, 140), mk(1, 72, 160, 520, 200), mk(2, 72, 220, 520, 260)]
    ordered, _cols = page_reading_order(blocks, 595, CFG)
    assert ids(ordered) == ["b0", "b1", "b2"]


def test_two_column_with_fullwidth_title():
    """通栏标题 + 双栏正文：标题 -> 左栏自上而下 -> 右栏自上而下。"""
    title = mk(0, 72, 50, 523, 80)  # 全宽
    l1, l2 = mk(1, 80, 120, 280, 200), mk(2, 80, 220, 280, 300)
    r1, r2 = mk(3, 320, 120, 520, 200), mk(4, 320, 220, 520, 300)
    ordered, _cols = page_reading_order([l1, title, r2, r1, l2], 595, CFG)
    assert ids(ordered) == ["b0", "b1", "b2", "b3", "b4"]


def test_fullwidth_separator_splits_segments():
    """双栏正文 - 通栏表格 - 双栏正文：表格插入阅读流的正确位置。"""
    l1, r1 = mk(0, 80, 100, 280, 180), mk(1, 320, 100, 520, 180)
    table = mk(2, 72, 260, 523, 340)  # 全宽
    l2, r2 = mk(3, 80, 400, 280, 480), mk(4, 320, 400, 520, 480)
    ordered, _cols = page_reading_order([l2, table, r1, l1, r2], 595, CFG)
    assert ids(ordered) == ["b0", "b1", "b2", "b3", "b4"]


def test_same_band_side_by_side_blocks():
    """栏内并排的两个块（图 + 侧注）：同一行带内按 x 排序。"""
    a = mk(0, 72, 100, 200, 200)
    b = mk(1, 220, 102, 320, 198)
    ordered, _cols = page_reading_order([b, a], 595, CFG)
    assert ids(ordered) == ["b0", "b1"]


def test_columns_reported():
    title = mk(0, 72, 50, 523, 80)
    l1 = mk(1, 80, 120, 280, 200)
    r1 = mk(2, 320, 120, 520, 200)
    _ordered, cols = page_reading_order([l1, title, r1], 595, CFG)
    # 主分栏应为两列（标题所在段只有 1 列，正文段 2 列）
    assert len(cols) == 2


# ---------- 边界 ----------


def test_empty_and_single_block():
    assert page_reading_order([], 595, CFG) == ([], [])
    single = mk(0, 72, 100, 520, 140)
    ordered, _ = page_reading_order([single], 595, CFG)
    assert ids(ordered) == ["b0"]


def test_degenerate_zero_size_blocks_filtered():
    good = mk(0, 72, 100, 520, 140)
    zero = mk(1, 72, 300, 72.2, 300.2)  # 近零尺寸块应被过滤
    ordered, _ = page_reading_order([zero, good], 595, CFG)
    assert ids(ordered) == ["b0"]


def test_narrow_gutter_not_split():
    """栏间空白 < 最小沟宽：不切栏，按行带处理。"""
    a = mk(0, 72, 100, 290, 140)
    b = mk(1, 296, 100, 523, 140)  # 沟 6pt < 10pt 阈值
    ordered, _ = page_reading_order([a, b], 595, CFG)
    assert ids(ordered) == ["b0", "b1"]  # 仍按 x 排序（同行带）


def test_uneven_block_heights_same_column():
    """右栏块高差异大（2 倍以上）：行带聚类不拆散本栏顺序。"""
    title = mk(0, 72, 50, 523, 80)
    l1 = mk(1, 80, 120, 280, 200)
    r1 = mk(2, 320, 120, 520, 320)  # 高块
    l2 = mk(3, 80, 220, 280, 300)
    ordered, _cols = page_reading_order([l1, title, r1, l2], 595, CFG)
    assert ids(ordered) == ["b0", "b1", "b3", "b2"]
