# 职责：导出层。有序块流 -> 分层 Markdown / 带 bbox 的 JSON；
# 跨页段落续接合并（末块无句末标点 + 页缘位置 + 字号一致）在这里生效。

from __future__ import annotations

import logging

from docforge import __version__
from docforge.models import Block, BlockType, Document
from docforge.textutil import smart_join

logger = logging.getLogger(__name__)


def merge_continuations(blocks: list[Block]) -> list[Block]:
    """把 continues_prev 标记的块并入前一块（返回新列表，不修改输入）。

    Markdown 与 benchmark 提交共用此函数：保证「演示输出」和「被打分的对象」是同一个。
    """
    out: list[Block] = []
    for b in blocks:
        if out and b.continues_prev and b.type == BlockType.TEXT and out[-1].type == BlockType.TEXT:
            prev = out[-1]
            prev.bbox = prev.bbox.union(b.bbox)
            prev.text = smart_join([prev.text, b.text])
            prev.confidence = min(prev.confidence, b.confidence)
            continue
        out.append(b)
    return out


def assemble_markdown(doc: Document, tables_format: str = "html") -> str:
    blocks = [
        b for b in merge_continuations(doc.ordered_blocks()) if b.type not in (BlockType.PAGE_HEADER, BlockType.PAGE_FOOTER)
    ]
    parts: list[str] = []
    for b in blocks:
        if b.type == BlockType.HEADING:
            parts.append("#" * (b.heading_level or 1) + " " + b.text.strip())
        elif b.type == BlockType.TABLE:
            content = b.table_md if (tables_format == "md" and b.table_md) else (b.table_html or "")
            if content:
                parts.append(content)
        elif b.type == BlockType.IMAGE:
            parts.append(f"![image]({b.image_path or b.id + '.png'})")
        elif b.text.strip():
            parts.append(b.text.strip())
    return "\n\n".join(parts) + "\n"


def to_json_dict(doc: Document) -> dict:
    """带 bbox 的可溯源 JSON：每块含页码/坐标/类型/阅读序/置信度。"""
    pages = [
        {
            "number": p.number,
            "width": p.width,
            "height": p.height,
            "is_scanned": p.is_scanned,
            "columns": [list(c) for c in p.columns],
        }
        for p in doc.pages
    ]
    blocks = [
        {
            "id": b.id,
            "page": b.page,
            "type": b.type.value,
            "heading_level": b.heading_level,
            "bbox": [round(b.bbox.x0, 2), round(b.bbox.y0, 2), round(b.bbox.x1, 2), round(b.bbox.y1, 2)],
            "text": b.text,
            "reading_order": b.reading_order,
            "confidence": round(b.confidence, 4),
            "table_html": b.table_html,
            "table_md": b.table_md,
            "image_path": b.image_path,
            "continues_prev": b.continues_prev,
            "meta": b.meta,
        }
        for b in doc.blocks
    ]
    return {
        "file": doc.path,
        "engine": doc.meta.get("engine", "docforge"),
        "version": __version__,
        "stage_ms": {k: round(v, 1) for k, v in doc.stage_ms.items()},
        "meta": {k: v for k, v in doc.meta.items() if k != "engine"},
        "pages": pages,
        "blocks": blocks,
    }
