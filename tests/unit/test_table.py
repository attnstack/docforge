# 职责：表格结构还原单测。recover_table 是纯函数——手工构造线段与词即可测，
# 覆盖：普通网格 / colspan / rowspan / 线段噪声 / L 形降级 / 网格不完整拒绝。

from __future__ import annotations

from docforge.config import TableConfig
from docforge.models import Seg, Word
from docforge.stages.table import cluster_1d, find_table_regions, recover_table

CFG = TableConfig()


def words_in_cells(cells: dict[tuple[int, int], str], xs: list[float], ys: list[float]) -> list[Word]:
    """按单元格中心偏移生成词，模拟 PDF 里的单元格文本。"""
    out = []
    for (r, c), text in cells.items():
        x = xs[c] + 6
        y = (ys[r] + ys[r + 1]) / 2 - 4
        out.append(Word(x, y, x + len(text) * 10, y + 10, text))
    return out


def h_segs_from(xs: list[float], ys: list[float], skip: set[tuple[int, int]] = set()) -> list[Seg]:  # noqa: B006
    """横线：逐列分段画（模拟真实 PDF 常见画法），skip[(row_boundary, col)] 表示该列无横线。"""
    out = []
    n_cols = len(xs) - 1
    for i, y in enumerate(ys):
        if i == 0 or i == len(ys) - 1:
            out.append(Seg(xs[0], y, xs[-1], y))
        else:
            for c in range(n_cols):
                if (i - 1, c) not in skip:
                    out.append(Seg(xs[c], y, xs[c + 1], y))
    return out


def v_segs_from(xs: list[float], ys: list[float], skip: set[tuple[int, int]] = set()) -> list[Seg]:  # noqa: B006
    out = []
    n_rows = len(ys) - 1
    for j, x in enumerate(xs):
        if j == 0 or j == len(xs) - 1:
            out.append(Seg(x, ys[0], x, ys[-1]))
        else:
            for r in range(n_rows):
                if (r, j - 1) not in skip:
                    out.append(Seg(x, ys[r], x, ys[r + 1]))
    return out


# ---------- cluster_1d ----------


def test_cluster_1d_snaps_close_values():
    clusters = cluster_1d([100.0, 100.9, 101.8, 200.0], tol=2.5)
    assert len(clusters) == 2
    assert abs(clusters[0][0] - 100.9) < 0.5
    assert clusters[0][1] == 3


def test_cluster_1d_empty():
    assert cluster_1d([], 2.5) == []


# ---------- 正常 ----------


def test_plain_grid():
    xs, ys = [72.0, 200.0, 330.0, 460.0], [300.0, 330.0, 360.0, 390.0]
    cells = {(0, 0): "指标", (0, 1): "目标", (0, 2): "实际", (1, 0): "A", (1, 1): "1", (1, 2): "2",
             (2, 0): "B", (2, 1): "3", (2, 2): "4"}
    struct = recover_table(h_segs_from(xs, ys), v_segs_from(xs, ys), words_in_cells(cells, xs, ys), CFG)
    assert struct is not None and (struct.n_rows, struct.n_cols) == (3, 3)
    assert struct.confidence > 0.99
    html = struct.to_html()
    assert html.count("<tr>") == 3 and html.count("<td>") == 9
    assert ">指标<" in html and "rowspan" not in html and "colspan" not in html


def test_colspan_and_rowspan():
    xs, ys = [72.0, 200.0, 350.0, 523.0], [300.0, 330.0, 360.0, 390.0, 420.0]
    cells = {
        (0, 0): "项目", (0, 1): "2024", (1, 0): "营收", (1, 1): "1000", (1, 2): "1200",
        (2, 1): "1100", (2, 2): "1300", (3, 0): "净利", (3, 1): "100", (3, 2): "150",
    }
    struct = recover_table(
        h_segs_from(xs, ys, skip={(1, 0)}),  # y=360 处 col0 无横线 -> rowspan
        v_segs_from(xs, ys, skip={(0, 1)}),  # x=350 处 row0 无竖线 -> colspan
        words_in_cells(cells, xs, ys),
        CFG,
    )
    assert struct is not None
    html = struct.to_html()
    assert 'colspan="2"' in html and 'rowspan="2"' in html
    assert ">2024<" in html  # colspan 锚点文本


def test_double_borders_snapped():
    """双线边框（间距 1pt）：吸附后不应产生幻影行列。"""
    xs, ys = [72.0, 200.0, 330.0], [300.0, 330.0, 360.0]
    cells = {(0, 0): "a", (0, 1): "b", (1, 0): "c", (1, 1): "d"}
    h = h_segs_from(xs, ys)
    v = v_segs_from(xs, ys)
    # 每条线叠加一条偏移 1pt 的重影线
    h += [Seg(s.x0, s.y0 + 1.0, s.x1, s.y1 + 1.0) for s in h]
    v += [Seg(s.x0 + 1.0, s.y0, s.x1 + 1.0, s.y1) for s in v]
    struct = recover_table(h, v, words_in_cells(cells, xs, ys), CFG)
    assert struct is not None and (struct.n_rows, struct.n_cols) == (2, 2)


# ---------- 边界与异常 ----------


def test_grid_incomplete_returns_none():
    """只有两条横线 + 两条竖线（<2x2 网格）：拒绝，返回 None。"""
    h = [Seg(72, 300, 523, 300), Seg(72, 330, 523, 330)]
    v = [Seg(72, 300, 72, 330), Seg(523, 300, 523, 330)]
    assert recover_table(h, v, [], CFG) is None


def test_underline_noise_not_table():
    """单条横线（下划线）：连通分量没有网格，recover_table 返回 None。"""
    h = [Seg(72, 300, 200, 300)]
    assert recover_table(h, [], [], CFG) is None


def test_l_shaped_merge_falls_back_to_cells():
    """L 形合并（HTML 无法表达）：降级为逐格输出 + 置信度减半，不崩。

    构造：无 x=200 处 row0 竖线（横向合并）+ 无 y=330 处 col0 横线（纵向合并）
    但 (0,1)-(1,1) 之间有横线 -> 区域 {(0,0),(0,1),(1,0)} 为 L 形。
    """
    h = [Seg(72, 300, 350, 300), Seg(200, 330, 350, 330), Seg(72, 360, 350, 360)]
    v = [Seg(72, 300, 72, 360), Seg(200, 330, 200, 360), Seg(350, 300, 350, 360)]
    words = [Word(80, 305, 120, 320, "A"), Word(210, 305, 250, 320, "B"), Word(80, 335, 120, 350, "C"), Word(210, 335, 250, 350, "D")]
    struct = recover_table(h, v, words, CFG)
    assert struct is not None
    assert struct.confidence <= 0.5
    html = struct.to_html()
    assert "rowspan" not in html and "colspan" not in html  # 降级后无跨行列语义
    assert ">A<" in html and ">B<" in html and ">C<" in html


def test_words_outside_table_ignored():
    xs, ys = [72.0, 200.0, 330.0], [300.0, 330.0, 360.0]
    cells = {(0, 0): "内", (0, 1): "表", (1, 0): "格", (1, 1): "子"}
    words = words_in_cells(cells, xs, ys)
    words.append(Word(600, 300, 640, 310, "外部"))
    struct = recover_table(h_segs_from(xs, ys), v_segs_from(xs, ys), words, CFG)
    assert struct is not None and "外部" not in struct.plain_text


def test_find_table_regions_groups_components():
    """两张不相邻的表 + 一条远处下划线：只产生表格区域组，下划线单独成组。"""
    xs1, ys1 = [72.0, 200.0, 330.0], [300.0, 330.0, 360.0]
    xs2, ys2 = [72.0, 200.0, 330.0], [600.0, 630.0, 660.0]
    segs = h_segs_from(xs1, ys1) + v_segs_from(xs1, ys1) + h_segs_from(xs2, ys2) + v_segs_from(xs2, ys2)
    segs.append(Seg(400, 100, 470, 100))  # 下划线
    groups = find_table_regions(segs, CFG)
    assert len(groups) == 3
