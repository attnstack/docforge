# 职责：流水线编排。数字页/扫描页分流；各阶段顺序有依赖约束：
#   表格还原要先行（把表格文本从正文里剥离，避免污染标题/阅读顺序），
#   页眉页脚剔除要先于阅读顺序（否则重复噪声参与分栏投影）。

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path

from docforge._pymupdf import fitz
from docforge.config import PipelineConfig
from docforge.errors import UnsupportedInputError
from docforge.models import BBox, Block, BlockType, Document, PageResult
from docforge.stages import extract, layout, ocr, reading_order, table
from docforge.stages.export import merge_continuations  # noqa: F401  (re-export 供 runner 复用)

logger = logging.getLogger(__name__)


def parse_document(
    path: str | Path,
    cfg: PipelineConfig,
    *,
    ocr_engine: ocr.BaseOcr | None = None,
    image_out_dir: Path | None = None,
) -> Document:
    """解析一个 PDF/图片文件 -> Document。可预期错误抛 DocforgeError 子类。"""
    p = Path(path)
    if not p.exists():
        raise UnsupportedInputError(f"文件不存在: {p}")
    size_mb = p.stat().st_size / 1_000_000
    if size_mb > cfg.max_file_mb:
        raise UnsupportedInputError(f"文件 {size_mb:.0f}MB 超过上限 {cfg.max_file_mb}MB（DOCFORGE_MAX_FILE_MB 可调）")

    stage_ms: dict[str, float] = {}
    t_all = time.perf_counter()

    with fitz.open(p) as doc:
        if doc.needs_pass:
            raise UnsupportedInputError("PDF 已加密，无法解析", hint="先解密，或让数据提供方输出无密码版本。")
        if doc.page_count == 0:
            raise UnsupportedInputError("空文档（0 页）")
        if doc.page_count > cfg.max_pages:
            raise UnsupportedInputError(
                f"页数 {doc.page_count} 超过上限 {cfg.max_pages}",
                hint="如确需处理超长文档，调高 DOCFORGE_MAX_PAGES 并自行评估耗时。",
            )

        pages: list[PageResult] = []
        t_page = time.perf_counter()
        for pno in range(doc.page_count):
            page = doc.load_page(pno)
            raw = extract.extract_page(page)
            scanned = layout.is_scanned_page(raw, cfg.layout)
            if scanned:
                blocks = _blocks_from_ocr(page, pno, ocr_engine, cfg)
                page_tables = []
            else:
                blocks = _blocks_from_text(raw, pno)
                page_tables = _table_blocks(raw, pno, cfg)
                blocks = _merge_tables(blocks, page_tables)
                _extract_images(page, blocks, pno, image_out_dir)
            pages.append(
                PageResult(number=pno, width=page.rect.width, height=page.rect.height, blocks=blocks, is_scanned=scanned)
            )
        stage_ms["pages"] = (time.perf_counter() - t_page) * 1000

        t_hf = time.perf_counter()
        removed_hf = layout.remove_headers_footers(pages, cfg.layout)
        stage_ms["header_footer"] = (time.perf_counter() - t_hf) * 1000

        t_reflow = time.perf_counter()
        layout.reflow_paragraphs(pages)
        stage_ms["reflow"] = (time.perf_counter() - t_reflow) * 1000

        t_head = time.perf_counter()
        layout.detect_headings(pages, cfg.heading)
        stage_ms["headings"] = (time.perf_counter() - t_head) * 1000

        t_order = time.perf_counter()
        counter = 0
        for pr in pages:
            flow_blocks = [b for b in pr.blocks if b.type not in (BlockType.PAGE_HEADER, BlockType.PAGE_FOOTER)]
            ordered, columns = reading_order.page_reading_order(flow_blocks, pr.width, cfg.layout)
            pr.columns = columns
            for b in ordered:
                b.reading_order = counter
                counter += 1
        stage_ms["reading_order"] = (time.perf_counter() - t_order) * 1000

        all_blocks = [b for pr in pages for b in pr.blocks]
        scanned_pages = [pr.number for pr in pages if pr.is_scanned]
        doc_obj = Document(
            path=str(p),
            pages=pages,
            blocks=all_blocks,
            stage_ms=stage_ms,
            meta={
                "engine": "docforge",
                "n_pages": doc.page_count,
                "scanned_pages": scanned_pages,
                "removed_headers_footers": removed_hf,
            },
        )
    stage_ms["total"] = (time.perf_counter() - t_all) * 1000
    doc_obj.stage_ms = stage_ms
    logger.info(
        "parsed %s pages=%d blocks=%d scanned=%s total_ms=%.1f",
        p.name,
        len(pages),
        len(all_blocks),
        scanned_pages or "-",
        stage_ms["total"],
    )
    return doc_obj


def _blocks_from_text(raw: extract.PageRaw, pno: int) -> list[Block]:
    from docforge.textutil import smart_join

    blocks: list[Block] = []
    for i, rb in enumerate(raw.text_blocks):
        lines_text = []
        for line in rb.lines:
            # 行内多 span（样式切换被切开）按 CJK 边界拼接
            lines_text.append(smart_join([s.text for s in line.spans]))
        blocks.append(
            Block(
                id=f"p{pno}-b{i}",
                page=pno,
                bbox=rb.bbox,
                type=BlockType.TEXT,
                text="\n".join(lines_text),
                meta={"font_size": rb.max_font_size, "bold": rb.bold, "font": rb.font, "source": "text-layer"},
            )
        )
    for j, img_bbox in enumerate(raw.image_bboxes):
        blocks.append(
            Block(
                id=f"p{pno}-i{j}",
                page=pno,
                bbox=img_bbox,
                type=BlockType.IMAGE,
                meta={"source": "text-layer"},
            )
        )
    return blocks


def _table_blocks(raw: extract.PageRaw, pno: int, cfg: PipelineConfig) -> list[Block]:
    out: list[Block] = []
    for k, group in enumerate(table.find_table_regions(raw.segments, cfg.table)):
        h_segs = [s for s in group if s.is_horizontal]
        v_segs = [s for s in group if s.is_vertical]
        struct = table.recover_table(h_segs, v_segs, raw.words, cfg.table)
        if struct is None:
            logger.debug("region on page %d rejected as table (grid incomplete)", pno)
            continue
        xs0 = min(s.x0 for s in group)
        ys0 = min(min(s.y0, s.y1) for s in group)
        xs1 = max(s.x1 for s in group)
        ys1 = max(max(s.y0, s.y1) for s in group)
        out.append(
            Block(
                id=f"p{pno}-t{k}",
                page=pno,
                bbox=BBox(xs0, ys0, xs1, ys1),
                type=BlockType.TABLE,
                text=struct.plain_text,
                table_html=struct.to_html(),
                table_md=struct.to_markdown(),
                confidence=round(struct.confidence, 3),
                meta={"n_rows": struct.n_rows, "n_cols": struct.n_cols},
            )
        )
        logger.info(
            "page %d table %dx%d confidence=%.2f", pno, struct.n_rows, struct.n_cols, struct.confidence
        )
    return out


def _merge_tables(blocks: list[Block], tables: list[Block]) -> list[Block]:
    """表格区域内的正文块剔除（中心点判定），替换为 TABLE 块。

    why 中心点而不是相交：表格外紧贴边框的标题/备注只与表格 bbox 相切不重叠，
    中心点判定不会误杀；而表格内部的文本块中心必然落在 bbox 内。
    """
    if not tables:
        return blocks
    kept = [b for b in blocks if not any(t.bbox.contains_point(b.bbox.center_x, b.bbox.center_y) for t in tables)]
    return kept + tables


def _extract_images(page: fitz.Page, blocks: list[Block], pno: int, image_out_dir: Path | None) -> None:
    if not image_out_dir:
        return
    img_idx = 0
    for b in blocks:
        if b.type != BlockType.IMAGE:
            continue
        image_out_dir.mkdir(parents=True, exist_ok=True)
        out_path = image_out_dir / f"page-{pno + 1}-img-{img_idx}.png"
        pix = page.get_pixmap(clip=fitz.Rect(b.bbox.x0, b.bbox.y0, b.bbox.x1, b.bbox.y1))
        pix.save(str(out_path))
        b.image_path = str(out_path)
        img_idx += 1


def _blocks_from_ocr(page: fitz.Page, pno: int, ocr_engine: ocr.BaseOcr | None, cfg: PipelineConfig) -> list[Block]:
    if ocr_engine is None:
        raise ocr.OcrUnavailableError(f"第 {pno + 1} 页是扫描页（无可提取文字层）")
    dpi = _render_dpi(page, cfg)
    pix = page.get_pixmap(dpi=dpi)
    fd, png_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        pix.save(png_path)
        lines = ocr_engine.recognize(png_path)  # 类内部已串行化（Paddle 非线程安全）
    finally:
        try:
            Path(png_path).unlink()
        except OSError:  # 临时文件清理失败不影响主流程
            logger.warning("temp file %s not removed", png_path)

    scale = 72.0 / dpi
    line_blocks: list[Block] = []
    for i, ln in enumerate(lines):
        bbox = BBox(ln.bbox.x0 * scale, ln.bbox.y0 * scale, ln.bbox.x1 * scale, ln.bbox.y1 * scale)
        if bbox.width <= 0.5 or not ln.text.strip():
            continue
        line_blocks.append(
            Block(
                id=f"p{pno}-l{i}",
                page=pno,
                bbox=bbox,
                type=BlockType.TEXT,
                text=ln.text,
                confidence=ln.confidence,
                meta={"source": "ocr"},
            )
        )
    ordered, _columns = reading_order.page_reading_order(line_blocks, page.rect.width, cfg.layout)
    return ocr.lines_to_paragraphs(ordered, pno)


def _render_dpi(page: fitz.Page, cfg: PipelineConfig) -> int:
    w_in = page.rect.width / 72
    h_in = page.rect.height / 72
    pixels = (cfg.dpi * w_in) * (cfg.dpi * h_in)
    if pixels <= cfg.max_render_pixels:
        return cfg.dpi
    dpi = max(int(cfg.dpi * (cfg.max_render_pixels / pixels) ** 0.5), 72)
    logger.warning("page %.0fx%.0fpt: render dpi reduced %d -> %d (pixel bomb guard)", page.rect.width, page.rect.height, cfg.dpi, dpi)
    return dpi
