# 职责：有框线表格结构还原（自研核心算法，v0.1 承诺范围：有框线表格）。
#
# 流程：线段连通分量 -> 一维聚类成网格 -> 边界覆盖率判定分隔 -> union-find 合并跨行列
#       -> 单元格文本归属 -> HTML(rowspan/colspan) / Markdown。
#
# 面试点 1：为什么不用 PyMuPDF 自带 find_tables？——它不输出 rowspan/colspan 语义、
#           无置信度、依赖内部启发式不可单测；这里自研 ~200 行纯函数换可控性，
#           词提取仍复用 PyMuPDF（不自研分词，不在无价值处重复造轮子）。
# 面试点 2：合并单元格用 union-find——局部"边界缺失"信息 -> 全局单元格区域，
#           复杂度 O(RC x alpha)，且天然支持行列同时合并。

from __future__ import annotations

import html as html_mod
import logging
from dataclasses import dataclass

from docforge.config import TableConfig
from docforge.models import Seg, Word
from docforge.textutil import smart_join

logger = logging.getLogger(__name__)


def cluster_1d(values: list[float], tol: float) -> list[tuple[float, int]]:
    """一维坐标聚类：排序后相邻差 <= tol 归一簇，返回 [(代表坐标, 元素数)]。

    why 用"相邻差"而不是"到均值距离"：PDF 里同一逻辑线常被画成首尾相接的
    多条短线（每格一条），链式吸附能把它们并到一条网格线。
    """
    if not values:
        return []
    vs = sorted(values)
    clusters: list[list[float]] = [[vs[0]]]
    for v in vs[1:]:
        if v - clusters[-1][-1] <= tol:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return [(sum(c) / len(c), len(c)) for c in clusters]


@dataclass
class MergedCell:
    r0: int  # 起始行（inclusive）
    c0: int
    r1: int  # 结束行（inclusive）
    c1: int
    text: str

    @property
    def rowspan(self) -> int:
        return self.r1 - self.r0 + 1

    @property
    def colspan(self) -> int:
        return self.c1 - self.c0 + 1


@dataclass
class TableStructure:
    n_rows: int
    n_cols: int
    cells: list[MergedCell]
    confidence: float

    @property
    def plain_text(self) -> str:
        return " ".join(c.text for c in self.cells if c.text)

    def to_html(self) -> str:
        anchors = {(c.r0, c.c0): c for c in self.cells}
        covered: set[tuple[int, int]] = set()
        for c in self.cells:
            for r in range(c.r0, c.r1 + 1):
                for cc in range(c.c0, c.c1 + 1):
                    if (r, cc) != (c.r0, c.c0):
                        covered.add((r, cc))
        out = ["<table>"]
        for r in range(self.n_rows):
            tds: list[str] = []
            for c in range(self.n_cols):
                if (r, c) in covered:
                    continue
                cell = anchors.get((r, c))
                if cell is None:  # 网格完整性兜底：理论上不应发生
                    tds.append("<td></td>")
                    continue
                attrs = ""
                if cell.rowspan > 1:
                    attrs += f' rowspan="{cell.rowspan}"'
                if cell.colspan > 1:
                    attrs += f' colspan="{cell.colspan}"'
                tds.append(f"<td{attrs}>{html_mod.escape(cell.text)}</td>")
            out.append("<tr>" + "".join(tds) + "</tr>")
        out.append("</table>")
        return "".join(out)

    def to_markdown(self) -> str:
        # Markdown 无跨行列语义：值放在锚点格，其余留空——有损降级，文档已声明
        grid: dict[tuple[int, int], str] = {(c.r0, c.c0): c.text.replace("|", "\\|") for c in self.cells}
        rows = []
        for r in range(self.n_rows):
            rows.append("| " + " | ".join(grid.get((r, c), "") for c in range(self.n_cols)) + " |")
        if self.n_rows >= 2:
            rows.insert(1, "|" + "---|" * self.n_cols)
        return "\n".join(rows)


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # 路径压缩
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def recover_table(
    h_segs: list[Seg], v_segs: list[Seg], words: list[Word], cfg: TableConfig
) -> TableStructure | None:
    """从轴线段 + 词还原表格结构。线段不足以构成网格时返回 None（调用方按正文处理）。"""
    tol = cfg.snap_tolerance_pt
    y_lines = [y for y, _ in cluster_1d([s.mid_y for s in h_segs], tol)]
    x_lines = [x for x, _ in cluster_1d([s.mid_x for s in v_segs], tol)]
    # 过滤过近的网格线（<3pt 会产生高度为 0 的幻影行/列）
    y_lines = _drop_close(y_lines, 3.0)
    x_lines = _drop_close(x_lines, 3.0)

    n_rows, n_cols = len(y_lines) - 1, len(x_lines) - 1
    if n_rows < cfg.min_rows or n_cols < cfg.min_cols:
        return None

    gx0, gy0, gx1, gy1 = x_lines[0], y_lines[0], x_lines[-1], y_lines[-1]
    inner_words = [
        w for w in words if gx0 - tol <= w.center_x <= gx1 + tol and gy0 - tol <= w.center_y <= gy1 + tol
    ]

    def h_sep(r: int, c: int) -> bool:
        """行 r 与 r+1 之间、列 c 的 x 范围上，是否有覆盖充分的横线。"""
        y = y_lines[r + 1]
        cx0, cx1 = x_lines[c], x_lines[c + 1]
        for s in h_segs:
            if abs(s.mid_y - y) > tol:
                continue
            if min(s.x1, cx1) - max(s.x0, cx0) >= cfg.border_coverage * (cx1 - cx0):
                return True
        return False

    def v_sep(r: int, c: int) -> bool:
        x = x_lines[c + 1]
        ry0, ry1 = y_lines[r], y_lines[r + 1]
        for s in v_segs:
            if abs(s.mid_x - x) > tol:
                continue
            if min(s.y1, ry1) - max(s.y0, ry0) >= cfg.border_coverage * (ry1 - ry0):
                return True
        return False

    # why 覆盖率 50% 而不是"存在即分隔"：跨列合并会留下半截分隔线，
    # 部分覆盖的线不能作为整格分隔依据，否则合并单元格被切碎。
    uf = _UnionFind(n_rows * n_cols)
    for r in range(n_rows):
        for c in range(n_cols):
            if c + 1 < n_cols and not v_sep(r, c):
                uf.union(r * n_cols + c, r * n_cols + c + 1)
            if r + 1 < n_rows and not h_sep(r, c):
                uf.union(r * n_cols + c, (r + 1) * n_cols + c)

    groups: dict[int, list[tuple[int, int]]] = {}
    for r in range(n_rows):
        for c in range(n_cols):
            groups.setdefault(uf.find(r * n_cols + c), []).append((r, c))

    regions: list[tuple[int, int, int, int]] = []
    rectangular = True
    for members in groups.values():
        r0 = min(r for r, _ in members)
        r1 = max(r for r, _ in members)
        c0 = min(c for _, c in members)
        c1 = max(c for _, c in members)
        if len(members) != (r1 - r0 + 1) * (c1 - c0 + 1):
            rectangular = False
        regions.append((r0, c0, r1, c1))

    if not rectangular:
        # HTML rowspan/colspan 只能表达矩形区域；L 形合并降级为逐格输出（有损，有日志）
        logger.warning("table has L-shaped merged region; falling back to per-cell output")
        regions = [(r, c, r, c) for members in groups.values() for r, c in members]

    cells: list[MergedCell] = []
    for r0, c0, r1, c1 in sorted(regions):
        rx0, rx1 = x_lines[c0], x_lines[c1 + 1]
        ry0, ry1 = y_lines[r0], y_lines[r1 + 1]
        cell_words = [
            w
            for w in inner_words
            if rx0 - tol <= w.center_x <= rx1 + tol and ry0 - tol <= w.center_y <= ry1 + tol
        ]
        cell_words.sort(key=lambda w: (w.center_y, w.center_x))
        cells.append(MergedCell(r0, c0, r1, c1, smart_join([w.text for w in cell_words])))

    # 置信度：内部边界上有真实线段支撑的比例（线条被页面噪声污染时下降）
    internal_h = max(n_rows - 1, 0) * n_cols
    internal_v = n_cols > 0 and max(n_cols - 1, 0) * n_rows or 0
    total = internal_h + internal_v
    if total == 0:
        return None
    supported = 0
    for r in range(n_rows - 1):
        for c in range(n_cols):
            supported += h_sep(r, c)
    for r in range(n_rows):
        for c in range(n_cols - 1):
            supported += v_sep(r, c)
    confidence = (supported / total) * (0.5 if not rectangular else 1.0)
    return TableStructure(n_rows=n_rows, n_cols=n_cols, cells=cells, confidence=confidence)


def _drop_close(lines: list[float], min_gap: float) -> list[float]:
    if not lines:
        return []
    out = [lines[0]]
    for v in lines[1:]:
        if v - out[-1] >= min_gap:
            out.append(v)
    return out


def find_table_regions(segments: list[Seg], cfg: TableConfig) -> list[list[Seg]]:
    """按连通性（膨胀 join_tolerance）把线段分组成候选表格区域。"""
    segs = [s for s in segments if (s.is_horizontal or s.is_vertical) and s.length >= cfg.min_line_len_pt]
    n = len(segs)
    if n == 0:
        return []
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    expand = cfg.join_tolerance_pt
    for i in range(n):
        for j in range(i + 1, n):
            a, b = segs[i], segs[j]
            ax0, ax1 = min(a.x0, a.x1) - expand, max(a.x0, a.x1) + expand
            ay0, ay1 = min(a.y0, a.y1) - expand, max(a.y0, a.y1) + expand
            bx0, bx1 = min(b.x0, b.x1), max(b.x0, b.x1)
            by0, by1 = min(b.y0, b.y1), max(b.y0, b.y1)
            if ax0 <= bx1 and bx0 <= ax1 and ay0 <= by1 and by0 <= ay1:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri

    groups: dict[int, list[Seg]] = {}
    for i, s in enumerate(segs):
        groups.setdefault(find(i), []).append(s)
    return list(groups.values())
