# 职责：端到端集成测试：程序化生成 PDF -> 自研引擎全链路 -> Markdown/JSON 断言；
# 以及评测链路（runner + 四指标 + 报告）在迷你种子集上的冒烟与阈值断言。

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docforge._pymupdf import fitz
from docforge.config import PipelineConfig
from docforge.engines import get_engine

# ---------- PDF 构造 ----------


def make_two_col_with_table_pdf(path: Path) -> None:
    doc = fitz.open()
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((72, 100), "测试文档标题", fontname="china-s", fontsize=17)
    page1.insert_textbox(fitz.Rect(72, 150, 280, 320), "左栏第一段内容，讲述阅读顺序的还原方法。", fontname="china-s", fontsize=10.5)
    page1.insert_textbox(fitz.Rect(72, 260, 280, 430), "左栏第二段内容，进一步展开细节。", fontname="china-s", fontsize=10.5)
    page1.insert_textbox(fitz.Rect(315, 150, 523, 320), "右栏第一段内容，与左栏并行排版。", fontname="china-s", fontsize=10.5)
    page1.insert_textbox(fitz.Rect(315, 260, 523, 430), "右栏第二段内容，验证分栏投影。", fontname="china-s", fontsize=10.5)

    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((72, 180), "表格示例", fontname="china-s", fontsize=13)
    xs = [72, 200, 350, 523]
    ys = [300, 330, 360, 390]
    # 网格：row0 的 col1-col2 合并（colspan）
    for y in ys:
        page2.draw_line(fitz.Point(xs[0], y), fitz.Point(xs[-1], y), color=(0, 0, 0), width=0.7)
    for j, x in enumerate(xs):
        if j == 0 or j == len(xs) - 1:
            page2.draw_line(fitz.Point(x, ys[0]), fitz.Point(x, ys[-1]), color=(0, 0, 0), width=0.7)
        else:
            start = ys[0] if j == 1 else ys[1]  # col1 边界从 row0 开始（含），col2 边界跳过 row0
            page2.draw_line(fitz.Point(x, start), fitz.Point(x, ys[-1]), color=(0, 0, 0), width=0.7)
    page2.insert_text((78, 320), "项目", fontname="china-s", fontsize=10.5)
    page2.insert_text((206, 320), "2024", fontname="china-s", fontsize=10.5)
    page2.insert_text((206, 350), "1000", fontname="china-s", fontsize=10.5)
    page2.insert_text((356, 350), "1200", fontname="china-s", fontsize=10.5)
    doc.save(str(path))
    doc.close()


# ---------- 全链路 ----------


def test_e2e_digital_pdf(tmp_path: Path):
    pdf = tmp_path / "sample.pdf"
    make_two_col_with_table_pdf(pdf)
    engine = get_engine("docforge")
    result = engine.parse(pdf, PipelineConfig(), image_out_dir=tmp_path / "images")

    md = result.markdown or ""
    assert "# 测试文档标题" in md  # 标题识别 + 层级
    assert "<table>" in md and 'colspan="2"' in md  # 表格结构还原
    assert ">2024<" in md
    # 阅读顺序：标题在最前
    assert md.index("测试文档标题") < md.index("左栏第一段")

    document = result.meta["document"]
    data = json.dumps(
        {b.id: b.reading_order for b in document.blocks if b.reading_order is not None},
        ensure_ascii=False,
    )
    assert data  # 所有进入阅读流的块都有顺序
    # JSON 导出可溯源
    from docforge.stages.export import to_json_dict

    exported = to_json_dict(document)
    assert exported["pages"][0]["width"] == 595
    table_blocks = [b for b in exported["blocks"] if b["type"] == "table"]
    assert len(table_blocks) == 1 and table_blocks[0]["confidence"] > 0.9


def test_e2e_encrypted_pdf_rejected(tmp_path: Path):
    pdf = tmp_path / "enc.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(str(pdf), encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="x", user_pw="x")
    doc.close()
    engine = get_engine("docforge")
    from docforge.errors import UnsupportedInputError

    with pytest.raises(UnsupportedInputError):
        engine.parse(pdf, PipelineConfig())


# ---------- 评测链路 ----------


def test_bench_runner_on_mini_dataset(tmp_path: Path, monkeypatch):
    """迷你种子集 -> run_bench -> 四指标产出且数字高于阈值（数字版路径确定性）。"""
    from benchmark.data.synthetic import generate as gen
    from benchmark.runner import run_bench

    dataset_dir = tmp_path / "ds"
    gen.generate(dataset_dir)

    report_path, results = run_bench(["docforge"], dataset_dir, tmp_path / "results", PipelineConfig())
    assert report_path.exists()
    agg = results[0]["aggregate"]
    # 数字版 + 精确 GT：文本与表格应接近满分；顺序允许标题/段落切分带来的小误差
    assert agg["text"]["mean"] is not None and agg["text"]["mean"] >= 0.95, f"text={agg['text']}"
    assert agg["table"]["mean"] is not None and agg["table"]["mean"] >= 0.9, f"table={agg['table']}"
    assert agg["order"]["mean"] is not None and agg["order"]["mean"] >= 0.85, f"order={agg['order']}"
    assert agg["heading"]["mean"] is not None and agg["heading"]["mean"] >= 0.7, f"heading={agg['heading']}"
    # 报告内容含合成集声明
    assert "合成种子集" in report_path.read_text(encoding="utf-8")

    # 榜单页可生成
    from benchmark.leaderboard import build_leaderboard

    lb = build_leaderboard(tmp_path / "results", tmp_path / "leaderboard" / "index.html")
    assert lb.exists() and "docforge" in lb.read_text(encoding="utf-8")


def test_bench_missing_dataset_raises(tmp_path: Path):
    from benchmark.runner import run_bench
    from docforge.errors import DatasetError

    with pytest.raises(DatasetError):
        run_bench(["docforge"], tmp_path / "nope", tmp_path / "out", PipelineConfig())
