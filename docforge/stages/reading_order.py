# 职责：阅读顺序还原——本流水线最难的算法点（纯几何法，语义仲裁 v0.2 再上）。
#
# 三层策略（顺序固定）：
#   1. 通栏分段：宽度 >= 80% 页宽的块视为"分隔符"，把页面切成上下文段；
#   2. 段内分栏：x 向投影找空白沟，沟宽达标才切栏（非参数化，不假设栏数）；
#   3. 栏内行带：按块中心 y 聚类成"行带"（容差 = 0.5 x 块高中位数），带内按 x 排序。
#
# 为什么先剥离通栏块再分栏？——通栏标题/表格参与 x 投影会把栏沟"封死"，
# 这是所有多栏解析器的经典坑；剥离后投影，栏沟才能暴露出来。

from __future__ import annotations

import logging

from docforge.config import LayoutConfig
from docforge.models import Block

logger = logging.getLogger(__name__)


def _split_columns(
    blocks: list[Block], x_min: float, x_max: float, cfg: LayoutConfig, page_width: float
) -> list[list[Block]]:
    """x 向区间合并找栏沟。返回按左到右排列的列（每列是块列表），至少一列。

    why 浮点区间合并而不是分桶投影：2pt 粒度的分桶会把 22pt 的真实栏沟
    量化成 20.04pt，贴着阈值时整栏失效；区间合并零量化误差，且分界点
    可以取沟的中点（比沟起点更合理的归属线）。
    """
    span = x_max - x_min
    if span <= 0 or len(blocks) < 2:
        return [sorted(blocks, key=lambda b: b.bbox.y0)] if blocks else []

    # why：宽度超过 70% 跨度的块不参与区间合并——段内准通栏块会把栏沟"封死"
    wide_limit = 0.7 * span
    intervals = sorted((b.bbox.x0, b.bbox.x1) for b in blocks if b.bbox.width <= wide_limit)
    merged: list[list[float]] = []
    for s, e in intervals:
        if merged and s <= merged[-1][1] + 1e-6:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    min_gutter = max(cfg.gutter_min_ratio * page_width, cfg.gutter_min_pt)
    boundaries = []  # 每项 = 一条沟的中点 x（列归属线）
    for (_s1, e1), (s2, _e2) in zip(merged, merged[1:]):  # noqa: B905 - pairwise 滑窗，长度差 1 是设计使然
        if s2 - e1 >= min_gutter:
            boundaries.append((e1 + s2) / 2)

    if not boundaries:
        return [blocks]

    import bisect

    columns: dict[int, list[Block]] = {}
    for b in blocks:
        col = bisect.bisect_left(boundaries, b.bbox.center_x)
        columns.setdefault(col, []).append(b)

    result = []
    for col in sorted(columns):
        result.append(columns[col])
    return result


def _band_order(blocks: list[Block], tol_factor: float) -> list[Block]:
    """栏内行带聚类：中心 y 相差 <= 容差 的块算同一视觉行，带内按 x0 排序。"""
    if len(blocks) <= 1:
        return sorted(blocks, key=lambda b: (b.bbox.y0, b.bbox.x0))
    ordered = sorted(blocks, key=lambda b: b.bbox.center_y)
    heights = sorted(b.bbox.height for b in blocks)
    median_h = heights[len(heights) // 2]
    tol = max(tol_factor * median_h, 2.0)
    bands: list[list[Block]] = []
    current: list[Block] = [ordered[0]]
    cur_y = ordered[0].bbox.center_y
    for b in ordered[1:]:
        if b.bbox.center_y - cur_y <= tol:
            current.append(b)
            cur_y = sum(x.bbox.center_y for x in current) / len(current)
        else:
            bands.append(current)
            current = [b]
            cur_y = b.bbox.center_y
    bands.append(current)
    out: list[Block] = []
    for band in bands:
        out.extend(sorted(band, key=lambda b: b.bbox.x0))
    return out


def page_reading_order(
    blocks: list[Block], page_width: float, cfg: LayoutConfig
) -> tuple[list[Block], list[tuple[float, float]]]:
    """返回按阅读顺序排列的块列表，以及主分栏的 x 范围（调试/OCR 联动用）。"""
    blocks = [b for b in blocks if b.bbox.width > 0.5 and b.bbox.height > 0.5]
    if not blocks:
        return [], []
    if len(blocks) == 1:
        return list(blocks), []

    sorted_blocks = sorted(blocks, key=lambda b: b.bbox.y0)
    # why 按内容跨度而不是页面宽度：正常文档有页边距，通栏标题只占页宽 ~76%，
    # 以页宽为基准的阈值（0.8）永远打不中，通栏分段会整体失效——这是实现期踩过的真 bug。
    content_x0 = min(b.bbox.x0 for b in blocks)
    content_x1 = max(b.bbox.x1 for b in blocks)
    fullwidth = cfg.fullwidth_ratio * (content_x1 - content_x0)

    result: list[Block] = []
    segment: list[Block] = []
    main_columns: list[tuple[float, float]] = []

    def flush() -> None:
        nonlocal segment, main_columns
        if not segment:
            return
        x_min = min(b.bbox.x0 for b in segment)
        x_max = max(b.bbox.x1 for b in segment)
        columns = _split_columns(segment, x_min, x_max, cfg, page_width)
        if len(columns) > len(main_columns):  # 记录块最多的分栏结构作为页面主分栏
            main_columns = [
                (min(b.bbox.x0 for b in col), max(b.bbox.x1 for b in col)) for col in columns
            ]
        for col in columns:
            result.extend(_band_order(col, cfg.band_tolerance))
        segment = []

    for b in sorted_blocks:
        if b.bbox.width >= fullwidth:
            flush()
            result.append(b)
        else:
            segment.append(b)
    flush()
    return result, main_columns
