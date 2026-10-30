# 职责：TEDS（Tree-Edit-Distance-based Similarity，PubTabNet 提出的表格树相似度）。
#
# 实现约定（与 PubTabNet 官方的差异都写在这里，可审计）：
#   1. 结构节点标签 = 标签名；th 归一为 td（markdown 表没有表头语义，避免平凡惩罚）；
#   2. td 内文本归一化后作为一个文本子节点（标签 = 归一化文本）；
#   3. insert/delete 代价 1；update：标签相同 0，文本节点 1 - 文本相似度，其余 1；
#      why 文本节点用部分相似度：给优化以连续梯度——错一个字不应把整格打成一比零错；
#   4. 相似度 = 1 - dist / max(|T1|, |T2|)，负值截断为 0。

from __future__ import annotations

import re
from html.parser import HTMLParser

from benchmark.metrics.tree_edit import TreeNode, tree_edit_distance
from benchmark.normalize import levenshtein, normalize_text

_VOID_OR_IGNORE = {"br", "hr", "img", "col", "colgroup", "thead", "tbody", "tfoot"}


class _TableTreeParser(HTMLParser):
    """把 <table> HTML 解析成树；th -> td；文本串成一个文本子节点。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root: TreeNode | None = None
        self._stack: list[TreeNode] = []
        self._text_buf: list[str] = []

    def _flush_text(self) -> None:
        text = normalize_text("".join(self._text_buf))
        self._text_buf = []
        if text and self._stack:
            self._stack[-1].children.append(TreeNode(label=f"#{text}"))

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        self._flush_text()
        tag = tag.lower()
        if tag == "th":
            tag = "td"
        node = TreeNode(label=tag)
        if self._stack:
            self._stack[-1].children.append(node)
        elif self.root is None:
            self.root = node
        self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        self._flush_text()
        tag = tag.lower()
        if tag == "th":
            tag = "td"
        if self._stack and self._stack[-1].label == tag:
            self._stack.pop()
        # 标签不匹配（畸形 HTML）：容错跳过，不抛异常——评测器必须比引擎更鲁棒

    def handle_data(self, data: str) -> None:
        self._text_buf.append(data)


def html_to_tree(html: str) -> TreeNode | None:
    parser = _TableTreeParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - 畸形输入按 0 分处理，不让评测器崩
        return None
    return parser.root


def _update_cost(a: str, b: str) -> float:
    if a == b:
        return 0.0
    if a.startswith("#") and b.startswith("#"):
        ta, tb = a[1:], b[1:]
        longer = max(len(ta), len(tb), 1)
        return 1.0 - (1.0 - levenshtein(ta, tb) / longer)
    return 1.0


def teds(gt_html: str, pred_html: str) -> float:
    """单表 TEDS。任一表解析失败或为空 -> 0.0。"""
    t1, t2 = html_to_tree(gt_html), html_to_tree(pred_html)
    if t1 is None or t2 is None:
        return 0.0
    if not t1.children and not t2.children:
        return 1.0
    dist = tree_edit_distance(
        t1, t2, insert_cost=lambda _: 1.0, delete_cost=lambda _: 1.0, update_cost=_update_cost
    )
    denom = max(t1.size(), t2.size())
    return max(0.0, 1.0 - dist / denom)


def teds_for_tables(gt_tables: list[str], pred_tables: list[str]) -> float | None:
    """多表评测：贪心最优匹配后按 GT 表数取均值（没匹配上的 GT 表记 0）。

    why 贪心而不是二分图最优匹配：表格数量少（<10），贪心与最优的差可以忽略，
    且 O(G*P) 的实现只有 20 行——为不重要的精度上复杂度不值得。
    """
    if not gt_tables and not pred_tables:
        return None
    if not gt_tables:
        return None  # GT 无表而引擎报了表：不计入（数据集不含该能力维度）
    scores = [[teds(g, p) for p in pred_tables] for g in gt_tables]
    used: set[int] = set()
    total = 0.0
    for row in scores:
        best_j, best_v = -1, 0.0
        for j, v in enumerate(row):
            if j not in used and v > best_v:
                best_j, best_v = j, v
        if best_j >= 0:
            used.add(best_j)
        total += best_v  # 没匹配上则该 GT 表贡献 0
    return total / len(gt_tables)


_WS_RE = re.compile(r"\s+")


def strip_table_for_compare(html: str) -> str:
    return _WS_RE.sub("", html)
