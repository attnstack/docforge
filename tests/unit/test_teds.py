# 职责：TEDS 与底层 Zhang-Shasha 树编辑距离单测（含手工计算的最小案例）。

from __future__ import annotations

import pytest

from benchmark.metrics.teds import html_to_tree, teds, teds_for_tables
from benchmark.metrics.tree_edit import TreeNode, tree_edit_distance


def dist(t1: TreeNode, t2: TreeNode) -> float:
    return tree_edit_distance(t1, t2, lambda _: 1.0, lambda _: 1.0, lambda a, b: 0.0 if a == b else 1.0)


# ---------- Zhang-Shasha 原语（已知最小案例） ----------


def test_zs_identical_single_node():
    assert dist(TreeNode("a"), TreeNode("a")) == 0


def test_zs_update_single_node():
    assert dist(TreeNode("a"), TreeNode("b")) == 1


def test_zs_delete_child():
    t1 = TreeNode("a", [TreeNode("b")])
    assert dist(t1, TreeNode("a")) == 1


def test_zs_two_children_vs_one():
    t1 = TreeNode("a", [TreeNode("b"), TreeNode("c")])
    t2 = TreeNode("a", [TreeNode("b")])
    assert dist(t1, t2) == 1


def test_zs_chain_vs_chain():
    t1 = TreeNode("a", [TreeNode("b", [TreeNode("c")])])
    t2 = TreeNode("a", [TreeNode("x", [TreeNode("y")])])
    assert dist(t1, t2) == 2  # 两次 update


def test_zs_symmetry():
    t1 = TreeNode("a", [TreeNode("b", [TreeNode("c"), TreeNode("d")])])
    t2 = TreeNode("a", [TreeNode("e", [TreeNode("d")]), TreeNode("f")])
    assert dist(t1, t2) == dist(t2, t1)


def test_zs_empty_trees():
    empty = TreeNode("@root")
    t = TreeNode("@root", [TreeNode("x")])
    assert dist(empty, empty) == 0
    assert dist(empty, t) == 1


# ---------- HTML 解析 ----------


def test_html_to_tree_structure():
    tree = html_to_tree("<table><tr><td>1</td><td>2</td></tr></table>")
    assert tree is not None and tree.label == "table"
    assert len(tree.children) == 1  # tr
    assert len(tree.children[0].children) == 2  # 2 td
    assert tree.children[0].children[0].children[0].label == "#1"


def test_html_th_normalized_to_td():
    tree = html_to_tree("<table><tr><th>H</th></tr></table>")
    assert tree.children[0].children[0].label == "td"


def test_malformed_html_returns_tree_or_none_not_crash():
    assert html_to_tree("<table><tr><td>unclosed") is not None  # 容错解析
    assert html_to_tree("") is None


# ---------- TEDS ----------


TABLE_GT = "<table><tr><td>项目</td><td>数值</td></tr><tr><td>A</td><td>1</td></tr></table>"


def test_teds_identical_table():
    assert teds(TABLE_GT, TABLE_GT) == 1.0


def test_teds_cell_text_typo_close_to_one():
    pred = TABLE_GT.replace("<td>1</td>", "<td>2</td>")
    score = teds(TABLE_GT, pred)
    assert 0.7 < score < 1.0


def test_teds_missing_cell_penalized():
    pred = "<table><tr><td>项目</td><td>数值</td></tr><tr><td>A</td></tr></table>"
    score = teds(TABLE_GT, pred)
    assert 0.5 < score < 1.0


def test_teds_vs_empty_table():
    assert teds(TABLE_GT, "<table></table>") < 0.5
    assert teds(TABLE_GT, "not html at all") == 0.0


def test_teds_structure_change_penalized():
    """行数差异（结构错误）应比单格文本错惩罚更重。"""
    typo = TABLE_GT.replace("<td>1</td>", "<td>2</td>")
    missing_row = "<table><tr><td>项目</td><td>数值</td></tr></table>"
    assert teds(TABLE_GT, missing_row) < teds(TABLE_GT, typo)


def test_teds_for_tables_matching_and_missing():
    gt = [TABLE_GT, "<table><tr><td>x</td></tr></table>"]
    pred = [TABLE_GT]  # 少报一张表
    score = teds_for_tables(gt, pred)
    assert score is not None and abs(score - 0.5) < 0.05


def test_teds_for_tables_both_empty_none():
    assert teds_for_tables([], []) is None


def test_teds_for_tables_gt_empty_pred_has_tables_none():
    """GT 无表而引擎报表：该维度不计入（返回 None），避免污染均值。"""
    assert teds_for_tables([], ["<table></table>"]) is None


@pytest.mark.parametrize(
    ("gt", "pred", "low", "high"),
    [
        (TABLE_GT, TABLE_GT, 0.999, 1.0),
        (TABLE_GT.replace("数值", "值"), TABLE_GT, 0.85, 1.0),
    ],
)
def test_teds_ranges(gt: str, pred: str, low: float, high: float):
    assert low <= teds(gt, pred) <= high
