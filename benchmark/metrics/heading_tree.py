# 职责：标题层级树相似度。GT 与 pred 的 [(level, text)] 各建一棵树，Zhang-Shasha 求相似度。
# 节点标签 = "L{level}:{归一化文本}"：层级或文本任一变化计 update 代价 1（保守但可解释）。

from __future__ import annotations

from benchmark.metrics.tree_edit import TreeNode, tree_edit_distance
from benchmark.normalize import normalize_text


def headings_to_tree(headings: list[list]) -> TreeNode:
    """虚拟根 + 按层级入栈建树。层级跳级（h1 直接接 h3）按实际层级嵌套，不惩罚。"""
    root = TreeNode(label="@root")
    stack: list[tuple[int, TreeNode]] = [(0, root)]
    for item in headings:
        level, text = int(item[0]), str(item[1])
        level = max(1, min(level, 6))
        label = f"L{level}:{normalize_text(text)}"
        node = TreeNode(label=label)
        while stack and stack[-1][0] >= level:
            stack.pop()
        (stack[-1][1] if stack else root).children.append(node)
        stack.append((level, node))
    return root


def heading_tree_similarity(gt_headings: list[list], pred_headings: list[list]) -> float | None:
    if not gt_headings and not pred_headings:
        return None
    t1 = headings_to_tree(gt_headings)
    t2 = headings_to_tree(pred_headings)
    if not t1.children and not t2.children:
        return None
    dist = tree_edit_distance(
        t1, t2, insert_cost=lambda _: 1.0, delete_cost=lambda _: 1.0, update_cost=_update
    )
    denom = max(t1.size(), t2.size())
    return max(0.0, 1.0 - dist / denom)


def _update(a: str, b: str) -> float:
    return 0.0 if a == b else 1.0
