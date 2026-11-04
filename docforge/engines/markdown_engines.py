# 职责：纯 Markdown 输出的基线引擎适配（markitdown / pymupdf4llm）。
#
# markdown -> 块 的剥离规则全部显式写在 markdown_to_blocks——
# 基线对比的公平性取决于「喂给指标的 plain text 怎么来的」，规则必须可审计：
# 表格行不进文本指标（由 TEDS 单独评）、#/**/_/` 等语法标记剥掉、链接只留锚文本。

from __future__ import annotations

import re
from abc import abstractmethod
from pathlib import Path

from docforge.config import PipelineConfig
from docforge.engines.base import BaseEngine, EngineResult, module_available
from docforge.models import BBox, Block, BlockType

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_SEPARATOR_RE = re.compile(r"^\|?[\s:|-]+\|?\s*$")


def _strip_inline_markdown(text: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\(([^)]*)\)", r"\1", text)  # 图片 -> alt
    text = re.sub(r"\[([^\]]*)\]\(([^)]*)\)", r"\1", text)  # 链接 -> 锚文本
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", text)
    text = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"\1", text)
    text = text.replace("`", "")
    return text


def _split_md_table_row(line: str) -> list[str]:
    return line.strip().strip("|").split("|")


def _md_table_to_html(rows: list[list[str]]) -> str:
    """markdown 表 -> 无跨行列语义的简单 HTML。th 归一为 td（见 benchmark/metrics/teds.py 约定）。"""
    if not rows:
        return ""

    def cells(r: list[str]) -> str:
        return "".join(f"<td>{_strip_inline_markdown(c.strip())}</td>" for c in r)

    return "<table>" + "".join(f"<tr>{cells(r)}</tr>" for r in rows) + "</table>"


def _is_table_start(line: str, next_line: str) -> bool:
    if not line.strip().startswith("|"):
        return False
    return _SEPARATOR_RE.match(next_line) is not None and "-" in next_line


def markdown_to_blocks(md: str) -> list[Block]:
    """markdown 文本 -> 块流。表格单独成块（不进文本指标），标题块带层级，顺序即块序。"""
    blocks: list[Block] = []
    lines = md.splitlines()
    i = 0
    order = 0

    def flush_para(para: list[str]) -> None:
        nonlocal order
        text = _strip_inline_markdown("\n".join(para)).strip()
        if text:
            blocks.append(
                Block(id=f"md-b{order}", page=0, bbox=_sentinel_bbox(order), type=BlockType.TEXT, text=text)
            )
            order += 1

    para: list[str] = []
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if i + 1 < len(lines) and _is_table_start(stripped, lines[i + 1]):
            flush_para(para)
            para = []
            tbl_lines = [stripped]
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith("|"):
                tbl_lines.append(lines[j].strip())
                j += 1
            rows = [_split_md_table_row(r) for r in tbl_lines]
            if len(rows) >= 2 and _SEPARATOR_RE.match(tbl_lines[1]):
                rows.pop(1)  # 去掉 |---|---| 分隔行
            html = _md_table_to_html(rows)
            blocks.append(
                Block(
                    id=f"md-t{order}",
                    page=0,
                    bbox=_sentinel_bbox(order),
                    type=BlockType.TABLE,
                    text=" ".join(c for r in rows for c in r),
                    table_html=html,
                    table_md="\n".join(tbl_lines),
                )
            )
            order += 1
            i = j
            continue
        m = _HEADING_RE.match(stripped)
        if m:
            flush_para(para)
            para = []
            blocks.append(
                Block(
                    id=f"md-h{order}",
                    page=0,
                    bbox=_sentinel_bbox(order),
                    type=BlockType.HEADING,
                    heading_level=len(m.group(1)),
                    text=_strip_inline_markdown(m.group(2)),
                )
            )
            order += 1
            i += 1
            continue
        if not stripped:
            flush_para(para)
            para = []
            i += 1
            continue
        para.append(line)
        i += 1
    flush_para(para)

    for k, b in enumerate(blocks):
        b.reading_order = k
    return blocks


def _sentinel_bbox(i: int) -> BBox:
    """基线引擎没有坐标信息；占位 bbox 只保证数据模型字段完整。"""
    return BBox(0.0, float(i), 0.0, float(i) + 1.0)


class _MarkdownEngineBase(BaseEngine):
    """共同骨架：依赖探测 + markdown -> 块适配。子类只实现 _to_markdown。"""

    module_name: str = ""

    def missing_dependency(self) -> str | None:
        return None if module_available(self.module_name) else self.module_name

    def parse(
        self,
        path: Path,
        cfg: PipelineConfig,
        image_out_dir: Path | None = None,
        *,
        password: str | None = None,
        pages_spec: str | None = None,
    ) -> EngineResult:
        del password, pages_spec  # 基线引擎不支持页选择/口令，签名对齐以统一调用
        md = self._to_markdown(path)
        return EngineResult(markdown=md, blocks=markdown_to_blocks(md), meta={"engine": self.name})

    @abstractmethod
    def _to_markdown(self, path: Path) -> str: ...


class MarkitdownEngine(_MarkdownEngineBase):
    name = "markitdown"
    module_name = "markitdown"
    supports_scanned = False

    def _to_markdown(self, path: Path) -> str:
        from markitdown import MarkItDown

        result = MarkItDown().convert(str(path))
        return result.text_content or ""


class Pymupdf4llmEngine(_MarkdownEngineBase):
    name = "pymupdf4llm"
    module_name = "pymupdf4llm"
    supports_scanned = False

    def _to_markdown(self, path: Path) -> str:
        import pymupdf4llm

        return pymupdf4llm.to_markdown(str(path))
