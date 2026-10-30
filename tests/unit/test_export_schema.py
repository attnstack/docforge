# 职责：提交 schema 校验单测 + markdown 适配层单测 + 导出单测。

from __future__ import annotations

from benchmark.schema import validate_submission
from docforge.engines.markdown_engines import markdown_to_blocks
from docforge.models import BBox, Block, BlockType
from docforge.stages.export import assemble_markdown, merge_continuations, to_json_dict

# ---------- schema ----------


def test_valid_submission_passes():
    obj = {
        "engine": "docforge",
        "dataset": "x",
        "samples": [{"id": "s1", "text_blocks": ["a"], "tables": ["<table></table>"], "headings": [[1, "标题"]]}],
    }
    assert validate_submission(obj) == []


def test_missing_required_field_fails():
    obj = {"engine": "docforge", "samples": [{"id": "s1"}]}  # 缺 text_blocks
    errors = validate_submission(obj)
    assert errors and "text_blocks" in errors[0]


def test_bad_heading_shape_fails():
    obj = {"engine": "e", "samples": [{"id": "s", "text_blocks": [], "headings": [["1", "t"]]}]}
    errors = validate_submission(obj)
    assert errors


# ---------- markdown 适配 ----------


def test_markdown_to_blocks_headings_tables_text():
    md = "# 标题\n\n正文段落一。\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n正文段落二。"
    blocks = markdown_to_blocks(md)
    kinds = [b.type for b in blocks]
    assert kinds == [BlockType.HEADING, BlockType.TEXT, BlockType.TABLE, BlockType.TEXT]
    assert blocks[0].heading_level == 1 and blocks[0].text == "标题"
    assert "<table>" in blocks[2].table_html and "<td>a</td>" in blocks[2].table_html
    assert "a" not in blocks[1].text  # 表格内容不进文本块


def test_markdown_inline_stripped():
    md = "这是 **加粗** 与 [链接](http://x) 与 `代码` 的文本。"
    blocks = markdown_to_blocks(md)
    assert blocks[0].text == "这是 加粗 与 链接 与 代码 的文本。"


# ---------- 导出 ----------


def _doc(blocks: list[Block]):
    from docforge.models import Document, PageResult

    for i, b in enumerate(blocks):
        b.reading_order = i
    return Document(
        path="t.pdf",
        pages=[PageResult(number=0, width=595, height=842, blocks=blocks)],
        blocks=blocks,
    )


def test_assemble_markdown_order_and_heading():
    blocks = [
        Block(id="1", page=0, bbox=BBox(0, 0, 1, 1), type=BlockType.HEADING, text="标题", heading_level=2),
        Block(id="2", page=0, bbox=BBox(0, 0, 1, 1), type=BlockType.TEXT, text="正文"),
        Block(id="3", page=0, bbox=BBox(0, 0, 1, 1), type=BlockType.TABLE, text="t", table_html="<table></table>"),
        Block(id="4", page=0, bbox=BBox(0, 0, 1, 1), type=BlockType.PAGE_HEADER, text="页眉"),
    ]
    md = assemble_markdown(_doc(blocks))
    assert md.startswith("## 标题")
    assert "<table></table>" in md
    assert "页眉" not in md  # 页眉被剔除


def test_continuation_merge_cjk_no_space():
    a = Block(id="1", page=0, bbox=BBox(0, 0, 1, 1), type=BlockType.TEXT, text="句子还没结束，")
    b = Block(id="2", page=0, bbox=BBox(0, 0, 1, 1), type=BlockType.TEXT, text="续接在本页", continues_prev=True)
    merged = merge_continuations([a, b])
    assert len(merged) == 1
    assert merged[0].text == "句子还没结束，续接在本页"


def test_to_json_dict_shape():
    blocks = [Block(id="1", page=0, bbox=BBox(1, 2, 3, 4), type=BlockType.TEXT, text="x", reading_order=0)]
    data = to_json_dict(_doc(blocks))
    assert data["engine"] == "docforge"
    assert data["blocks"][0]["bbox"] == [1, 2, 3, 4]
    assert data["pages"][0]["height"] == 842
