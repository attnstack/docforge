# 职责：版面语义标注——扫描页判定、页眉页脚剔除（跨页重复证据）、标题层级判定。

from __future__ import annotations

import logging
import math
import re

from docforge.config import HeadingConfig, LayoutConfig
from docforge.models import Block, BlockType, PageResult
from docforge.textutil import normalize_digits

logger = logging.getLogger(__name__)

# 纯页码模式："-1-"、"— 24 —"、"第 3 页" 等。真实公文的页码没有跨页重复之外的
# 结构证据（单页样本无法建立重复性），按模式直接剔除——这是真实数据实测暴露的缺口。
# 公文页码常在版心下方约 84% 处，超出常规页边距带，因此对页码模式启用放宽位置带。
_PAGE_NO_RE = re.compile(r"^[-—–‐‒\s]*(第)?\s*\d+\s*(页)?[-—–‐‒\s]*$")


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
    页码模式规则不依赖页数（单页文档的页码无法建立重复证据，靠模式 + 放宽位置带判定）。
    """
    margin = cfg.header_footer_margin
    counts: dict[tuple[str, str], set[int]] = {}
    if len(pages) >= 2:
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
            text = b.text.strip()
            if not text:
                continue
            # 页码模式：放宽位置带（顶部 15% / 底部 20%），短文本 + 强模式即剔除
            pageno_like = _PAGE_NO_RE.match(text) is not None and len(text) <= 12 and _in_relaxed_band(b, pr)
            if pageno_like:
                b.type = BlockType.PAGE_HEADER if b.bbox.center_y < pr.height / 2 else BlockType.PAGE_FOOTER
                removed += 1
                continue
            band = _band_of(b, pr, margin)
            if band is None:
                continue
            key = (band, normalize_digits(b.text))
            if len(pages) >= 2 and len(counts.get(key, set())) >= threshold:
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


def _in_relaxed_band(b: Block, pr: PageResult) -> bool:
    """页码专用放宽带：顶部 15% 或底部 20%。"""
    return b.bbox.y1 <= 0.15 * pr.height or b.bbox.y0 >= 0.80 * pr.height


def reflow_paragraphs(pages: list[PageResult]) -> int:
    """数字页的行->段落回流：把被 PyMuPDF 拆成单行的段落重新合并。

    公文证据链（三条件同时满足才合并）：
      1. 当前行无首行缩进（x0 接近正文左边距众数）——公文每段首行缩进 2 字符，
         缩进行 = 新段落开始，这是比行距更强的段落边界信号（公文段距==行距）；
      2. 垂直间距 <= 1.0 x 行高中位数（行内距，不是段间距）；
      3. 字体相同（标题字体与正文标签行不同，防止把"单位："并进标题）。
    非公文文档（无首行缩进）的块本身就是段落级，此函数近似无操作。
    """
    from collections import Counter

    merged = 0
    for pr in pages:
        blocks = [b for b in pr.blocks if b.meta.get("source") == "text-layer" and b.type == BlockType.TEXT]
        if len(blocks) < 2:
            continue
        xs = Counter(round(b.bbox.x0 / 2) * 2 for b in blocks)
        body_x = xs.most_common(1)[0][0]
        heights = sorted(b.bbox.height for b in blocks)
        med_h = max(heights[len(heights) // 2], 6.0)
        indent_x = body_x + 1.2 * med_h

        ordered = sorted(blocks, key=lambda b: (b.bbox.y0, b.bbox.x0))
        paragraphs: list[Block] = []
        for b in ordered:
            indented = b.bbox.x0 >= indent_x
            prev = paragraphs[-1] if paragraphs else None
            if prev is not None and not indented:
                gap = b.bbox.y0 - prev.bbox.y1
                overlap = prev.bbox.x_overlap(b.bbox)
                same_font = str(prev.meta.get("font", "")) == str(b.meta.get("font", ""))
                if gap <= med_h and overlap >= 0.5 * min(prev.bbox.width, b.bbox.width) and same_font:
                    prev.text = prev.text.rstrip("\n") + "\n" + b.text
                    prev.bbox = prev.bbox.union(b.bbox)
                    if (b.meta.get("font_size") or 0) > (prev.meta.get("font_size") or 0):
                        prev.meta["font_size"] = b.meta.get("font_size")
                    pr.blocks.remove(b)
                    merged += 1
                    continue
            paragraphs.append(b)
    if merged:
        logger.info("reflowed %d lines into paragraphs", merged)
    return merged


# 公文/中文文档的"标题字体"信号：党政机关公文格式（GB/T 9704）正文用仿宋，
# 标题用黑体（一级）、楷体（二级）、方正小标宋等——加粗靠换字体实现，flags 的
# bold 位恒为 0（真实公文 PDF 实测）。字体名 token 命中即视为标题候选信号。
_HEADING_FONT_TOKENS = ("hei", "kai", "bold", "black", "heavy")


def _suggests_heading_font(meta: dict) -> bool:
    if meta.get("bold"):
        return True
    font = str(meta.get("font", "")).lower()
    return any(tok in font for tok in _HEADING_FONT_TOKENS)


def detect_headings(pages: list[PageResult], cfg: HeadingConfig) -> None:
    """标题层级判定（仅数字页），两条互补规则：

    1. 字号比例（通用文档）：>= 1.5/1.25/1.12 x 正文字号 -> H1/H2/H3；
    2. 加粗 + 公文编号模式（中文公文：标题与正文同字号、仅加粗）：
       "一、" -> H1，"（一）" -> H2，"——" 或 "1." 开头 -> H3；
       附加约束：<=60 字（公文一级标题可较长）、无句末标点、字号不低于正文。
    """
    weighted_all: list[tuple[float, float]] = []
    sizes_all: list[float] = []
    for pr in pages:
        for b in pr.blocks:
            size = b.meta.get("font_size")
            if b.type == BlockType.TEXT and size:
                weighted_all.append((size, max(len(b.text), 1)))
                sizes_all.append(size)
    # why 先按分位过滤再取众数：附表页等块数极少的页面上，大标题的字符数
    # 可能超过全部正文，众数会被污染成标题字号（真实数据实测踩坑）。
    # 取 0.6 分位（而不是 0.75）：小页面 n=3 时 0.75 分位就等于最大值，过滤失效；
    # 只需裁掉"可能赢下字符数竞争"的最大字号，标题占块数比例高时也不会误伤正文。
    if not weighted_all:
        return
    sizes_all.sort()
    cap = sizes_all[min(int(len(sizes_all) * 0.6), len(sizes_all) - 1)]
    weighted = [(s, w) for s, w in weighted_all if s <= cap] or weighted_all
    body = _body_size(weighted)
    if body <= 0:
        return
    logger.info("body font size = %.2fpt", body)
    best_title_ratio = 0.0
    best_title_block: Block | None = None
    for pr in pages:
        for b in pr.blocks:
            size = b.meta.get("font_size")
            if b.type != BlockType.TEXT or not size:
                continue
            t = b.text.strip()
            if not t or len(t) > cfg.max_heading_chars:
                continue
            if t[-1] in "。！？；，,.!?;：:":
                continue
            ratio = size / body
            is_ocr = b.meta.get("source") == "ocr"
            # why OCR 行高代理需要补偿 + 收窄判定：检测框紧贴字形，高度差异被压缩
            # （实测公文标题 1.38x 被压成 1.24x），按固定比例放大后再比阈值；
            # 但 H3 档（1.12-1.25）与正文行高的噪声区间重叠，误报实测过高，
            # 因此扫描页只判 H1/H2，H3 层级让位给"文档标题晋升"规则
            if is_ocr:
                ratio *= 1.15
                if len(t) > 30:
                    continue
            level: int | None = None
            if ratio >= cfg.h1_ratio:
                level = 1
            elif ratio >= cfg.h2_ratio:
                level = 2
            elif ratio >= cfg.h3_ratio and not is_ocr:
                level = 3
            # 公文附件/附表标签（"附表1""附件2"）：字号常小于正文，但结构上是标题
            if level is None and re.match(r"^附[表件录]\s*\d*$", t) and len(t) <= 10:
                level = 2
            if level is None and _suggests_heading_font(b.meta) and ratio >= 1.0 and len(t) <= 60:
                level = _gov_numbering_level(t)
            if level is None:
                continue
            b.type = BlockType.HEADING
            b.heading_level = level
            if ratio > best_title_ratio:
                best_title_ratio = ratio
                best_title_block = b

    # 文档标题晋升：全文档字号最大的标题若够不到 H1 阈值（如公文大标题 1.38x），
    # 晋升为 H1——文档主标题是"最大字号的唯一标题"，这是跨版式的通用结构先验。
    if best_title_block is not None and best_title_ratio < cfg.h1_ratio and best_title_ratio >= cfg.h2_ratio:
        best_title_block.heading_level = 1
        logger.info("promoted document title to H1 (ratio=%.2f)", best_title_ratio)


_GOV_L1 = re.compile(r"^(第[一二三四五六七八九十百\d]+[部分章节]|[一二三四五六七八九十]+、)")
_GOV_L2 = re.compile(r"^（[一二三四五六七八九十]+）")


def _gov_numbering_level(text: str) -> int | None:
    if _GOV_L1.match(text):
        return 1
    if _GOV_L2.match(text):
        return 2
    if text.startswith(("——", "--", "一要", "二要", "三要", "四要", "五要")) or re.match(r"^\d+[\.、]\s*\S", text):
        return 3
    return None


def _body_size(pairs: list[tuple[float, float]]) -> float:
    """正文字号 = 按字符数加权的众数（0.5pt 分桶）。

    why 众数而不是中位数：标题行短但字号大，加权中位数可能恰好落在某个标题字号上，
    导致正文被判成标题；众数（字符数最多的字号桶）对标题数量不敏感。
    返回值取桶内真实字号（最大值）而不是桶键——桶键 16.0 vs 实际 15.95 会让
    ratio=0.997，所有 >=1.0 的判据全部失效（真实数据实测踩过的坑）。
    平票取更小字号——少报标题比多报标题安全（漏报只丢层级，误报污染正文流）。
    """
    if not pairs:
        return 0.0
    buckets: dict[float, tuple[float, float]] = {}  # key -> (总权重, 桶内最大真实字号)
    for size, weight in pairs:
        key = round(size * 2) / 2
        total, max_raw = buckets.get(key, (0.0, 0.0))
        buckets[key] = (total + weight, max(max_raw, size))
    best = min(buckets.items(), key=lambda kv: (-kv[1][0], kv[0]))
    return best[1][1]
