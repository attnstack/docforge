# 职责：Zhang & Shasha (1989) 有序带标签树编辑距离。TEDS（表格）与标题树相似度共用。
#
# 复杂度 O(n·m·min(depth_n, depth_m))，靠"最左叶子 + 关键根"分解达成；
# 朴素 (forest,forest) 记忆化是 O(n²m²)，表格节点上百时差一个数量级。
# 代价函数外置为回调：TEDS 与标题树的代价语义不同，算法只写一次。
# 实现约定：节点 1-based（下标 0 保留给空森林），fd 偏移矩阵按关键根对分配，
#           与 zss 库同构；单测覆盖已知最小案例（见 tests/unit/test_teds.py）。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class TreeNode:
    label: str
    children: list["TreeNode"] = field(default_factory=list)

    def size(self) -> int:
        return 1 + sum(c.size() for c in self.children)


InsertDeleteCost = Callable[[str], float]
UpdateCost = Callable[[str, str], float]


def _postorder(root: TreeNode) -> list[TreeNode]:
    out: list[TreeNode] = []

    def visit(node: TreeNode) -> None:
        for c in node.children:
            visit(c)
        out.append(node)

    visit(root)
    return out


def _maps(root: TreeNode, n: int) -> tuple[list[int | None], list[list[int]]]:
    """postorder 1-based 父指针与孩子表。parent[root] = None。"""
    parent: list[int | None] = [None] * (n + 1)
    children: list[list[int]] = [[] for _ in range(n + 1)]
    idx = 0

    def visit(node: TreeNode) -> int:
        nonlocal idx
        kid_idxs = [visit(c) for c in node.children]
        idx += 1
        me = idx
        for k in kid_idxs:
            parent[k] = me
            children[me].append(k)
        return me

    visit(root)
    if idx != n:
        raise ValueError(f"postorder size mismatch: {idx} != {n}")
    return parent, children


def _leftmost(i: int, children: list[list[int]]) -> int:
    while children[i]:
        i = children[i][0]
    return i


def tree_edit_distance(
    t1: TreeNode,
    t2: TreeNode,
    insert_cost: InsertDeleteCost,
    delete_cost: InsertDeleteCost,
    update_cost: UpdateCost,
) -> float:
    po1, po2 = _postorder(t1), _postorder(t2)
    n, m = len(po1), len(po2)
    if n == 0 and m == 0:
        return 0.0
    if n == 0:
        return sum(insert_cost(x.label) for x in po2)
    if m == 0:
        return sum(delete_cost(x.label) for x in po1)

    parent1, children1 = _maps(t1, n)
    parent2, children2 = _maps(t2, m)
    l1 = [_leftmost(i, children1) for i in range(1, n + 1)]
    l2 = [_leftmost(j, children2) for j in range(1, m + 1)]
    # 关键根：l(i) != l(parent(i))，即它是某条最左叶子链的第一个节点；根必是关键根
    kr1 = [i for i in range(1, n + 1) if parent1[i] is None or l1[i - 1] != l1[parent1[i] - 1]]
    kr2 = [j for j in range(1, m + 1) if parent2[j] is None or l2[j - 1] != l2[parent2[j] - 1]]

    td: dict[tuple[int, int], float] = {}  # 完整子树 (x,y) 的编辑距离

    for i in kr1:
        for j in kr2:
            li, lj = l1[i - 1], l2[j - 1]
            i_off, j_off = li - 1, lj - 1
            rows, cols = i - li + 2, j - lj + 2
            fd = [[0.0] * cols for _ in range(rows)]  # 森林距离，行 0/列 0 = 空森林
            for x in range(li, i + 1):
                fd[x - i_off][0] = fd[x - 1 - i_off][0] + delete_cost(po1[x - 1].label)
            for y in range(lj, j + 1):
                fd[0][y - j_off] = fd[0][y - 1 - j_off] + insert_cost(po2[y - 1].label)
            for x in range(li, i + 1):
                for y in range(lj, j + 1):
                    if l1[x - 1] == li and l2[y - 1] == lj:
                        fd[x - i_off][y - j_off] = min(
                            fd[x - 1 - i_off][y - j_off] + delete_cost(po1[x - 1].label),
                            fd[x - i_off][y - 1 - j_off] + insert_cost(po2[y - 1].label),
                            fd[x - 1 - i_off][y - 1 - j_off] + update_cost(po1[x - 1].label, po2[y - 1].label),
                        )
                        td[(x, y)] = fd[x - i_off][y - j_off]
                    else:
                        # 子树 (x,y) 不在当前关键根对的最左链上：整棵子树距离已算过，直接查表
                        fd[x - i_off][y - j_off] = min(
                            fd[x - 1 - i_off][y - j_off] + delete_cost(po1[x - 1].label),
                            fd[x - i_off][y - 1 - j_off] + insert_cost(po2[y - 1].label),
                            fd[l1[x - 1] - 1 - i_off][l2[y - 1] - 1 - j_off] + td[(x, y)],
                        )
    return td[(n, m)]
