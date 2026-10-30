# 职责：指标单测：归一化 / CER / 顺序对准确率 / 标题树相似度（正常/边界/异常）。

from __future__ import annotations

from benchmark.metrics.heading_tree import heading_tree_similarity, headings_to_tree
from benchmark.metrics.order_and_text import align_blocks, pairwise_order_accuracy, text_similarity
from benchmark.normalize import char_error_rate, levenshtein, normalize_text

# ---------- normalize / CER ----------


def test_normalize_nfkc_and_ws():
    assert normalize_text("ＡＢＣ １２３") == "abc123"  # 全角 -> 半角 + 小写
    assert normalize_text("营收 增长\n\t率") == "营收增长率"


def test_levenshtein_known_values():
    assert levenshtein("", "") == 0
    assert levenshtein("abc", "abc") == 0
    assert levenshtein("abc", "ab") == 1
    assert levenshtein("kitten", "sitting") == 3


def test_cer_exact_and_partial():
    assert char_error_rate("营收增长10%", "营收增长10%") == 0.0
    assert 0.0 < char_error_rate("营收增长10%", "营收增长20%") < 0.2
    assert char_error_rate("营收增长", "") == 1.0


def test_cer_empty_gt_empty_pred():
    assert char_error_rate("", "") == 0.0
    assert char_error_rate("", "something") == 1.0


def test_cer_caps_at_one():
    """pred 完全错误且更长：CER 封顶 1.0（1-CER 不出负分）。"""
    assert char_error_rate("短", "完全不同的长文本内容") == 1.0


# ---------- 文本指标 ----------


def test_text_similarity_identical_blocks():
    assert text_similarity(["第一段", "第二段"], ["第一段", "第二段"]) == 1.0


# ---------- 顺序指标 ----------


def test_order_perfect():
    gt = ["标题", "段落一", "段落二", "段落三"]
    assert pairwise_order_accuracy(gt, gt) == 1.0


def test_order_swapped_pair():
    gt = ["A", "B", "C"]
    pred = ["A", "C", "B"]  # B/C 交换：3 对中 2 对正确
    assert abs(pairwise_order_accuracy(gt, pred) - 2 / 3) < 1e-9


def test_order_two_column_interleaved():
    """双栏被逐行交错的典型错误：顺序得分应显著低于满分（可检出）但不至于归零。"""
    gt = ["标题", "L1", "L2", "L3", "R1", "R2", "R3"]
    pred = ["标题", "L1", "R1", "L2", "R2", "L3", "R3"]
    score = pairwise_order_accuracy(gt, pred)
    assert score is not None and 0.5 <= score < 0.95


def test_order_fragmented_block_still_aligned():
    """引擎把 GT 的一段切成两块：模糊对齐应把主块对上，指标仍有定义。"""
    gt = ["标题", "这是一个较长的完整段落讲述了一件复杂的事情"]
    pred = ["标题", "这是一个较长的完整段落讲述了一件复杂的事情的前半部分"]
    assert pairwise_order_accuracy(gt, pred) == 1.0


def test_order_too_few_matches_returns_none():
    assert pairwise_order_accuracy(["A"], ["A"]) is None
    assert pairwise_order_accuracy([], []) is None
    assert pairwise_order_accuracy(["A"], ["完全不同"]) is None


def test_align_exact_duplicates_in_order():
    """重复块按下标顺序配对，不错位。"""
    matches = align_blocks(["x", "y", "x"], ["x", "x", "y"])
    assert (0, 0) in matches and (2, 1) in matches and (1, 2) in matches


# ---------- 标题树 ----------


def test_heading_tree_identical():
    hs = [[1, "一、总览"], [2, "1.1 背景"], [2, "1.2 目标"]]
    assert heading_tree_similarity(hs, hs) == 1.0


def test_heading_tree_missing_subtree_penalized():
    gt = [[1, "一"], [2, "1.1"], [2, "1.2"], [2, "1.3"]]
    pred = [[1, "一"], [2, "1.1"]]
    score = heading_tree_similarity(gt, pred)
    assert score is not None and 0.5 < score < 0.95


def test_heading_tree_level_change_penalized():
    gt = [[1, "A"], [2, "B"]]
    pred = [[1, "A"], [3, "B"]]
    score = heading_tree_similarity(gt, pred)
    assert score is not None and score < 1.0


def test_heading_tree_both_empty_none():
    assert heading_tree_similarity([], []) is None


def test_headings_to_tree_nesting():
    root = headings_to_tree([[1, "a"], [2, "b"], [1, "c"]])
    assert len(root.children) == 2  # a 与 c 在根下
    assert root.children[0].children[0].label.endswith("b")
