# 职责：合成种子数据集生成器（v0.0）。
#
# why 存在：真实人工标注集需要数周；评测框架（指标/schema/榜单）第一天就要能自证。
# 程序化生成 PDF + 精确已知 GT = 评测系统的"黄金测试集"——指标实现的任何改动立刻可见。
# 边界（必须诚实声明）：这是构造分布，不是真实文档分布；数字不用于对外性能主张。
#
# 版面特征每类样本覆盖一个难点：单栏基线 / 标题层级 / 双栏 / 有框线表格（含跨行列合并）/ 页眉页脚 / 跨页续接 / 混合版式。

from __future__ import annotations

import json
from pathlib import Path

from docforge._pymupdf import fitz

PAGE_W, PAGE_H = 595, 842
MARGIN_X = 72
BODY_SIZE = 10.5

# ---------- 文本素材（GT 与 PDF 共用同一字符串，保证 GT 精确） ----------

S_SINGLE_TITLE = "项目进展季度综述"
S_SINGLE_PARAS = [
    "本季度项目按计划推进，核心流水线已完成端到端联调，覆盖文字提取、版面分析与结果导出三个阶段。",
    "在表格还原方向，团队完成了网格聚类算法的第一版实现，并对三种典型财报样例进行了验证。",
    "下一阶段的重点是无框线表格识别与扫描件的 OCR 链路打磨，同时扩充评测集的覆盖面。",
]

S_HEAD_TITLE = "数据平台建设方案"
S_HEAD_SECTIONS = [
    (1, "一、总体目标"),
    "数据平台需要统一接入业务库、日志与第三方数据源，形成可复用的指标体系。",
    (2, "1.1 接入层"),
    "接入层负责增量同步与 schema 演进管理，要求断点续传与幂等写入。",
    (2, "1.2 计算层"),
    "计算层以批流一体为原则，优先复用现有调度体系，避免重复建设。",
    (1, "二、里程碑"),
    "整体分为三个阶段：先打通链路，再补齐质量，最后优化成本与易用性。",
]

S_TWOCOL_TITLE = "深度模型在推荐系统中的实践"
S_TWOCOL_LEFT = [
    "召回阶段采用双塔结构，用户侧与物品侧分别编码，线上通过近似最近邻检索完成候选生成。",
    "粗排阶段引入轻量级交叉特征，在算力预算内将排序质量提升到可用水平。",
    "精排阶段使用多任务学习框架，同时优化点击率与转化率两个目标。",
]
S_TWOCOL_RIGHT = [
    "特征工程方面，序列特征按时间窗分桶，减少了长尾稀疏带来的过拟合风险。",
    "训练稳定性上，采用梯度裁剪与学习率预热的组合策略，收敛过程更加平滑。",
    "线上推理通过批量合并与量化压缩，将平均延迟控制在可接受范围内。",
]

S_TABLE_INTRO = "下表为合并利润表示例，包含跨行与跨列合并单元格。"
S_TABLE_CAPTION = "表1：合并利润表（单位：万元）"

T_PLAIN_001 = {
    "cells": {
        (0, 0): "指标",
        (0, 1): "目标值",
        (0, 2): "实际值",
        (1, 0): "解析成功率",
        (1, 1): "99.0%",
        (1, 2): "98.2%",
        (2, 0): "平均耗时",
        (2, 1): "3.0秒",
        (2, 2): "2.6秒",
    },
    "n_rows": 3,
    "n_cols": 3,
    "xs": [72, 200, 330, 460],
    "ys": [300, 330, 360, 390],
    "skip_v": [],
    "skip_h": [],
}
T_PLAIN_001_GT = (
    "<table><tr><td>指标</td><td>目标值</td><td>实际值</td></tr>"
    "<tr><td>解析成功率</td><td>99.0%</td><td>98.2%</td></tr>"
    "<tr><td>平均耗时</td><td>3.0秒</td><td>2.6秒</td></tr></table>"
)

T_SPAN_001 = {
    "cells": {
        (0, 0): "项目",
        (0, 1): "2024年度",
        (1, 0): "营业收入",
        (1, 1): "1000.00",
        (1, 2): "1200.00",
        (2, 1): "1100.00",
        (2, 2): "1300.00",
        (3, 0): "净利润",
        (3, 1): "100.00",
        (3, 2): "150.00",
    },
    "xs": [72, 200, 350, 523],
    "ys": [300, 330, 360, 390, 420],
    # 缺失的内部线：row0 的 col1-2 分隔（colspan）、col0 的 row1-2 分隔（rowspan）
    "skip_v": [(0, 1)],
    "skip_h": [(1, 0)],
}
T_SPAN_001_GT = (
    "<table><tr><td>项目</td><td colspan=\"2\">2024年度</td></tr>"
    "<tr><td rowspan=\"2\">营业收入</td><td>1000.00</td><td>1200.00</td></tr>"
    "<tr><td>1100.00</td><td>1300.00</td></tr>"
    "<tr><td>净利润</td><td>100.00</td><td>150.00</td></tr></table>"
)

T_SPAN_002 = {
    "cells": {
        (0, 0): "地区",
        (0, 1): "第一季度",
        (0, 2): "第二季度",
        (1, 0): "华东",
        (1, 1): "3200.00",
        (1, 2): "3400.00",
        (2, 0): "华南",
        (2, 1): "2800.00",
        (2, 2): "3100.00",
        (3, 0): "备注",
        (3, 1): "含税口径",
    },
    "xs": [72, 180, 330, 500],
    "ys": [300, 330, 360, 390, 420],
    "skip_v": [(3, 1)],  # 末行 col1-2 合并
    "skip_h": [],
}
T_SPAN_002_GT = (
    "<table><tr><td>地区</td><td>第一季度</td><td>第二季度</td></tr>"
    "<tr><td>华东</td><td>3200.00</td><td>3400.00</td></tr>"
    "<tr><td>华南</td><td>2800.00</td><td>3100.00</td></tr>"
    "<tr><td>备注</td><td colspan=\"2\">含税口径</td></tr></table>"
)

S_HF_HEADER = "华信科技有限公司年度报告"
# why 每页正文不同：页眉页脚样本若三页正文相同，引擎正确提取的重复文本
# 会被 GT（只记一份）误判为错误——这是数据设计问题，不是引擎问题。
S_HF_BODY_PAGES = [
    [
        "公司坚持研发投入，全年新增专利申请三十六项，其中发明专利占比超过六成。",
        "海外业务保持增长，东南亚市场收入同比提升明显，产品本地化能力持续增强。",
    ],
    [
        "供应链方面完成了双供应商策略落地，关键物料的交付周期缩短到四周以内。",
        "人才梯队建设推出新计划，核心岗位的内部晋升比例提高到百分之四十。",
    ],
    [
        "合规与数据安全体系通过年度审计，重点流程完成制度化和系统化改造。",
        "展望下一年度，公司将围绕国际化与平台化两大主题推进组织升级。",
    ],
]

S_LONG_TITLE = "跨页段落续接测试"
S_LONG_P1_PARA1 = "这是第一段完整的文字，句子在句号处结束。第二段将跨页续接，本页只写到"
S_LONG_P1_PARA2 = "独立成段的第三段在第一页结束，用于验证段间没有被错误合并。"
S_LONG_P1_TAIL = "而跨页的这段话在第一页结束时仍然没有说完，最后一个分句是"
S_LONG_P2_HEAD = "并且在这里完成收尾。跨页续接后应合并为一个逻辑段落。"
S_LONG_P2_PARA = "第二页的独立段落，前面不应被并续接标记影响。"

S_MIXED_TITLE = "季度经营分析"
S_MIXED_PARA = "本节包含标题、正文与带合并单元格的表格，用于验证混合版式的处理顺序。"


# ---------- PDF 构造工具 ----------


def _page(doc: fitz.Document) -> fitz.Page:
    return doc.new_page(width=PAGE_W, height=PAGE_H)


def _text(page: fitz.Page, x: float, y: float, s: str, size: float = BODY_SIZE) -> None:
    page.insert_text((x, y), s, fontname="china-s", fontsize=size)


def _para(page: fitz.Page, x: float, y: float, s: str, width: float = 300.0, size: float = BODY_SIZE) -> None:
    """写入一段文本（insert_textbox 自动折行）；矩形裁到页内，防止溢出丢字。"""
    rect = fitz.Rect(x, y - size, x + width, min(y + 40 * size, PAGE_H - 20))
    page.insert_textbox(rect, s, fontname="china-s", fontsize=size, lineheight=1.5)


def _hline(page: fitz.Page, x0: float, y: float, x1: float) -> None:
    page.draw_line(fitz.Point(x0, y), fitz.Point(x1, y), color=(0, 0, 0), width=0.7)


def _vline(page: fitz.Page, x: float, y0: float, y1: float) -> None:
    page.draw_line(fitz.Point(x, y0), fitz.Point(x, y1), color=(0, 0, 0), width=0.7)


def _grid(page: fitz.Page, spec: dict) -> None:
    """按 spec 画表格线：全量网格减去 skip 的内部线。"""
    xs, ys = spec["xs"], spec["ys"]
    skip_v = set(spec["skip_v"])  # (row, col_boundary)：row 行在 x=xs[col_boundary] 处无竖线
    skip_h = set(spec["skip_h"])  # (row_boundary, col)：y=ys[row_boundary] 处 col 列无横线
    n_rows, n_cols = len(ys) - 1, len(xs) - 1
    for i, y in enumerate(ys):
        if i == 0 or i == len(ys) - 1:
            _hline(page, xs[0], y, xs[-1])
        else:
            boundary = i - 1  # 网格线 i 位于行 i-1 与行 i 之间
            for c in range(n_cols):
                if (boundary, c) not in skip_h:
                    _hline(page, xs[c], y, xs[c + 1])
    for j, x in enumerate(xs):
        if j == 0 or j == len(xs) - 1:
            _vline(page, x, ys[0], ys[-1])
        else:
            boundary = j - 1
            for r in range(n_rows):
                if (r, boundary) not in skip_v:
                    _vline(page, x, ys[r], ys[r + 1])


def _table_text(page: fitz.Page, spec: dict) -> None:
    xs, ys = spec["xs"], spec["ys"]
    for (r, c), s in spec["cells"].items():
        _text(page, xs[c] + 6, ys[r] + 20, s)  # 单元格内左偏移，避免压线


# ---------- 样本构造 ----------


def build_single(doc: fitz.Document) -> None:
    page = _page(doc)
    _text(page, MARGIN_X, 120, S_SINGLE_TITLE, size=18)
    y = 180.0
    for para in S_SINGLE_PARAS:
        _para(page, MARGIN_X, y, para, width=PAGE_W - 2 * MARGIN_X)
        y += 80


def build_headings(doc: fitz.Document) -> None:
    # 字号设计：正文 10.5 / 小节 13.5（1.29x -> H2）/ 章 16（1.52x -> H1）/ 文档题 20
    # 与 GT 的层级一一对应——种子集考核的是引擎，不考核启发式的临界判断
    page = _page(doc)
    _text(page, MARGIN_X, 100, S_HEAD_TITLE, size=20)
    y = 150.0
    for item in S_HEAD_SECTIONS:
        if isinstance(item, tuple):
            level, title = item
            _text(page, MARGIN_X, y, title, size=16 if level == 1 else 13.5)
            y += 46
        else:
            _para(page, MARGIN_X, y, item, width=PAGE_W - 2 * MARGIN_X)
            y += 70


def build_twocol(doc: fitz.Document, title: str, left: list[str], right: list[str]) -> None:
    page = _page(doc)
    _text(page, MARGIN_X, 110, title, size=17)
    y0 = 170.0
    col_w = 205.0
    for i, para in enumerate(left):
        _para(page, MARGIN_X, y0 + i * 90, para, width=col_w)
    for i, para in enumerate(right):
        _para(page, 315, y0 + i * 90, para, width=col_w)


def build_table(doc: fitz.Document, spec: dict, intro: str) -> None:
    page = _page(doc)
    _text(page, MARGIN_X, 180, intro)
    _text(page, MARGIN_X, 285, S_TABLE_CAPTION)
    _grid(page, spec)
    _table_text(page, spec)


def build_header_footer(doc: fitz.Document) -> None:
    for pno, body in enumerate(S_HF_BODY_PAGES):
        page = _page(doc)
        _text(page, MARGIN_X, 55, S_HF_HEADER)
        _text(page, MARGIN_X, 810, f"第 {pno + 1} 页")
        y = 140.0
        for para in body:
            _para(page, MARGIN_X, y, para, width=PAGE_W - 2 * MARGIN_X)
            y += 80


def build_long(doc: fitz.Document) -> None:
    p1 = _page(doc)
    _text(p1, MARGIN_X, 120, S_LONG_TITLE, size=16)
    _para(p1, MARGIN_X, 180, S_LONG_P1_PARA1, width=PAGE_W - 2 * MARGIN_X)
    _para(p1, MARGIN_X, 280, S_LONG_P1_PARA2, width=PAGE_W - 2 * MARGIN_X)
    # 页尾块：无句末标点，位置在页底 15% 内 -> 触发跨页续接
    _para(p1, MARGIN_X, 720, S_LONG_P1_TAIL, width=PAGE_W - 2 * MARGIN_X)
    p2 = _page(doc)
    _para(p2, MARGIN_X, 110, S_LONG_P2_HEAD, width=PAGE_W - 2 * MARGIN_X)
    _para(p2, MARGIN_X, 210, S_LONG_P2_PARA, width=PAGE_W - 2 * MARGIN_X)


def build_mixed(doc: fitz.Document) -> None:
    page = _page(doc)
    _text(page, MARGIN_X, 110, S_MIXED_TITLE, size=17)
    _para(page, MARGIN_X, 170, S_MIXED_PARA, width=PAGE_W - 2 * MARGIN_X)
    _text(page, MARGIN_X, 285, S_TABLE_CAPTION)
    _grid(page, T_PLAIN_001)
    _table_text(page, T_PLAIN_001)


# ---------- GT 定义 ----------


def _gt(entry_id: str, text_blocks: list[str], tables: list[str], headings: list[list]) -> dict:
    return {"id": entry_id, "text_blocks": text_blocks, "tables": tables, "headings": headings}


def gt_samples() -> list[dict]:
    out = []
    out.append(_gt("single-001", [S_SINGLE_TITLE, *S_SINGLE_PARAS], [], [[1, S_SINGLE_TITLE]]))
    out.append(
        _gt(
            "headings-001",
            [
                # 提交契约：text_blocks 含标题与正文（按阅读序），表格除外（TEDS 单独评）
                S_HEAD_TITLE,
                S_HEAD_SECTIONS[0][1],
                S_HEAD_SECTIONS[1],
                S_HEAD_SECTIONS[2][1],
                S_HEAD_SECTIONS[3],
                S_HEAD_SECTIONS[4][1],
                S_HEAD_SECTIONS[5],
                S_HEAD_SECTIONS[6][1],
                S_HEAD_SECTIONS[7],
            ],
            [],
            [
                [1, S_HEAD_TITLE],
                [1, S_HEAD_SECTIONS[0][1]],
                [2, S_HEAD_SECTIONS[2][1]],
                [2, S_HEAD_SECTIONS[4][1]],
                [1, S_HEAD_SECTIONS[6][1]],
            ],
        )
    )
    out.append(_gt("twocol-001", [S_TWOCOL_TITLE, *S_TWOCOL_LEFT, *S_TWOCOL_RIGHT], [], [[1, S_TWOCOL_TITLE]]))
    out.append(
        _gt(
            "twocol-002",
            [
                "中文长文档的版面恢复",
                "双栏版式在学术期刊中极为常见，几何方法需要正确处理栏间空白与通栏元素。",
                "阅读顺序还原的目标，是让输出顺序与人类阅读顺序一致，而不是与内部对象顺序一致。",
                "表格与插图的锚定关系也需要被保留，否则图文对应关系会丢失。",
                "本样本在右栏刻意加入更长的段落，用于验证行带聚类对块高不均的鲁棒性。",
                "当块高差异超过两倍时，简单阈值会把同一行带拆成两半，需要按列局部计算中位数。",
                "此外，栏沟宽度阈值应随版心宽度缩放，绝对像素阈值在不同纸张尺寸下不可移植。",
            ],
            [],
            [[1, "中文长文档的版面恢复"]],
        )
    )
    out.append(_gt("table-plain-001", [S_TABLE_INTRO, S_TABLE_CAPTION], [T_PLAIN_001_GT], []))
    out.append(_gt("table-span-001", [S_TABLE_INTRO, S_TABLE_CAPTION], [T_SPAN_001_GT], []))
    out.append(_gt("table-span-002", [S_TABLE_INTRO, S_TABLE_CAPTION], [T_SPAN_002_GT], []))
    out.append(_gt("header-footer-001", [p for page_body in S_HF_BODY_PAGES for p in page_body], [], []))
    out.append(
        _gt(
            "longtext-001",
            [
                S_LONG_TITLE,
                S_LONG_P1_PARA1,
                S_LONG_P1_PARA2,
                S_LONG_P1_TAIL + S_LONG_P2_HEAD,  # 跨页合并后的逻辑段
                S_LONG_P2_PARA,
            ],
            [],
            [[1, S_LONG_TITLE]],
        )
    )
    out.append(_gt("mixed-001", [S_MIXED_TITLE, S_MIXED_PARA, S_TABLE_CAPTION], [T_PLAIN_001_GT], [[1, S_MIXED_TITLE]]))
    return out


SAMPLES: list[dict] = [
    {"id": "single-001", "builder": build_single, "type": "general"},
    {"id": "headings-001", "builder": build_headings, "type": "general"},
    {
        "id": "twocol-001",
        "builder": lambda d: build_twocol(d, S_TWOCOL_TITLE, S_TWOCOL_LEFT, S_TWOCOL_RIGHT),
        "type": "two_col",
    },
    {
        "id": "twocol-002",
        "builder": lambda d: build_twocol(
            d,
            "中文长文档的版面恢复",
            [
                "双栏版式在学术期刊中极为常见，几何方法需要正确处理栏间空白与通栏元素。",
                "阅读顺序还原的目标，是让输出顺序与人类阅读顺序一致，而不是与内部对象顺序一致。",
                "表格与插图的锚定关系也需要被保留，否则图文对应关系会丢失。",
            ],
            [
                "本样本在右栏刻意加入更长的段落，用于验证行带聚类对块高不均的鲁棒性。",
                "当块高差异超过两倍时，简单阈值会把同一行带拆成两半，需要按列局部计算中位数。",
                "此外，栏沟宽度阈值应随版心宽度缩放，绝对像素阈值在不同纸张尺寸下不可移植。",
            ],
        ),
        "type": "two_col",
    },
    {"id": "table-plain-001", "builder": lambda d: build_table(d, T_PLAIN_001, S_TABLE_INTRO), "type": "table"},
    {"id": "table-span-001", "builder": lambda d: build_table(d, T_SPAN_001, S_TABLE_INTRO), "type": "table"},
    {"id": "table-span-002", "builder": lambda d: build_table(d, T_SPAN_002, S_TABLE_INTRO), "type": "table"},
    {"id": "header-footer-001", "builder": build_header_footer, "type": "header_footer"},
    {"id": "longtext-001", "builder": build_long, "type": "general"},
    {"id": "mixed-001", "builder": build_mixed, "type": "mixed"},
]


def generate(out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    (out_dir / "inputs").mkdir(parents=True, exist_ok=True)
    (out_dir / "gt").mkdir(parents=True, exist_ok=True)
    gt_by_id = {g["id"]: g for g in gt_samples()}
    manifest_samples = []
    for spec in SAMPLES:
        doc = fitz.open()
        spec["builder"](doc)
        input_path = out_dir / "inputs" / f"{spec['id']}.pdf"
        doc.save(str(input_path))
        doc.close()
        gt = gt_by_id[spec["id"]]
        (out_dir / "gt" / f"{spec['id']}.json").write_text(
            json.dumps(
                {"engine": "ground-truth", "dataset": "docforge-zh-synthetic-v0.1", "samples": [gt]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        manifest_samples.append(
            {"id": spec["id"], "type": spec["type"], "input": f"inputs/{spec['id']}.pdf", "gt": f"gt/{spec['id']}.json"}
        )
    manifest = {
        "name": "docforge-zh-synthetic-v0.1",
        "synthetic": True,
        "description": "程序化生成的种子集：GT 精确已知，用于评测链路自证与回归。非真实文档分布。",
        "samples": manifest_samples,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"seed dataset written to {out_dir} ({len(manifest_samples)} samples)")
    return out_dir


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[3] / "benchmark" / "data" / "synthetic")
