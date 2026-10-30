# 职责：版面语义标注——扫描页判定、页眉页脚剔除（跨页重复证据）、标题层级判定。

from __future__ import annotations

import logging
import math

from docforge.config import HeadingConfig, LayoutConfig
from docforge.models import Block, BlockType, PageResult
from docforge.textutil import normalize_digits

logger = logging.getLogger(__name__)


def is_scanned_page(page_raw, cfg: LayoutConfig) -> bool:
    """扫描页判定：文字层字符少 **且** 存在覆盖过半页面的图像。

    why 加图像条件：字符数阈值会把"大表格页"（矢量线多、文字少）误判成扫描页；
    扫描页的定义性物理特征是整页位图，二者结合才既不漏也不误杀。
    """
    if page_raw.char_count >= cfg.scan_char_threshold:
        return False
    page_area = page_raw.width * page_raw.height
    image_area = 0.0
    for b in page_raw.image_bboxes:
        image_area += max(b.width, 0) * max(b.height, 0)
    return image_area >= 0.5 * page_area


def remove_headers_footers(pages: list[PageResult], cfg: LayoutConfig) -> int:
    """跨页重复剔除页眉页脚。证据 = 同位置带 + 数字归一化后同文本，出现在足够多页。

    why 跨页重复而不是只看位置：正文首段也常落在页顶 10%，仅凭位置会误杀。
    数字归一化让「第 1 页/第 2 页/第 3 页」归为同一模式。
    """
    if len(pages) < 2:
        return 0
    margin = cfg.header_footer_margin
    counts: dict[tuple[str, str], set[int]] = {}
    for pr in pages:
        for b in pr.blocks:
            band = _band_of(b, pr, margin)
            if band is None or not b.text.strip():
                continue
            key = (band, normalize_digits(b.text))
            counts.setdefault(key, set()).add(pr.number)

    threshold = max(cfg.header_footer_min_pages, math.ceil(cfg.header_footer_page_ratio * len(pages)))
    removed = 0
    for pr in pages:
        for b in pr.blocks:
            band = _band_of(b, pr, margin)
            if band is None or not b.text.strip():
                continue
            key = (band, normalize_digits(b.text))
            if len(counts.get(key, set())) >= threshold:
                b.type = BlockType.PAGE_HEADER if band == "top" else BlockType.PAGE_FOOTER
                removed += 1
    if removed:
        logger.info("removed %d header/footer blocks (threshold=%d pages)", removed, threshold)
    return removed


def _band_of(b: Block, pr: PageResult, margin: float) -> str | None:
    if b.type != BlockType.TEXT:
        return None
    if b.bbox.y1 <= margin * pr.height:
        return "top"
    if b.bbox.y0 >= (1 - margin) * pr.height:
        return "bottom"
    return None


def detect_headings(pages: list[PageResult], cfg: HeadingConfig) -> None:
    """字号比例判定标题层级（仅数字页：扫描页块无字号元数据，自动跳过）。

    附加约束（缺一不可）：长度上限、不以句末标点收尾——防止"大号正文"误判为标题。
    """
    weighted: list[tuple[float, float]] = []
    for pr in pages:
        for b in pr.blocks:
            size = b.meta.get("font_size")
            if b.type == BlockType.TEXT and size:
                weighted.append((size, max(len(b.text), 1)))
    body = _body_size(weighted)
    if body <= 0:
        return
    logger.info("body font size = %.2fpt", body)
    for pr in pages:
        for b in pr.blocks:
            size = b.meta.get("font_size")
            if b.type != BlockType.TEXT or not size:
                continue
            ratio = size / body
            level = None
            if ratio >= cfg.h1_ratio:
                level = 1
            elif ratio >= cfg.h2_ratio:
                level = 2
            elif ratio >= cfg.h3_ratio:
                level = 3
            if level is None:
                continue
            t = b.text.strip()
            if not t or len(t) > cfg.max_heading_chars:
                continue
            if t[-1] in "。！？；，,.!?;：:":  # 句末/逗号收尾的不是标题
                continue
            b.type = BlockType.HEADING
            b.heading_level = level


def _body_size(pairs: list[tuple[float, float]]) -> float:
    """正文字号 = 按字符数加权的众数（0.5pt 分桶）。

    why 众数而不是中位数：标题行短但字号大，加权中位数可能恰好落在某个标题字号上，
    导致正文被判成标题；众数（字符数最多的字号桶）对标题数量不敏感。
    平票取更小字号——少报标题比多报标题安全（漏报只丢层级，误报污染正文流）。
    """
    if not pairs:
        return 0.0
    buckets: dict[float, float] = {}
    for size, weight in pairs:
        key = round(size * 2) / 2
        buckets[key] = buckets.get(key, 0.0) + weight
    best = min(buckets.items(), key=lambda kv: (-kv[1], kv[0]))
    return best[0]
