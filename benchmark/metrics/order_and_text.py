# 职责：文本指标（1 - CER）与阅读顺序指标（有序对准确率）。
#
# 顺序指标必须"先对齐再比较"——不同引擎切块粒度不同（你切 3 块，GT 是 1 块），
# 不对齐的顺序比较没有意义。对齐规则显式化：归一化精确匹配优先，剩余块按
# 相似度 >= 0.6 贪心唯一匹配（difflib.SequenceMatcher，确定性）。

from __future__ import annotations

from difflib import SequenceMatcher

from benchmark.normalize import char_error_rate, normalize_text


def text_similarity(gt_blocks: list[str], pred_blocks: list[str]) -> float:
    """1 - CER，GT 与 pred 全文（各块归一化后拼接）比较。"""
    gt_text = "\n".join(gt_blocks)
    pred_text = "\n".join(pred_blocks)
    return 1.0 - char_error_rate(gt_text, pred_text)


def align_blocks(gt_blocks: list[str], pred_blocks: list[str]) -> list[tuple[int, int]]:
    """返回 (gt_index, pred_index) 匹配对。精确匹配（按出现顺序配对）优先，余量贪心模糊匹配。"""
    gt_norm = [normalize_text(b) for b in gt_blocks]
    pred_norm = [normalize_text(b) for b in pred_blocks]

    matches: list[tuple[int, int]] = []
    used_pred: set[int] = set()
    # 1) 精确匹配：同一归一化文本在 GT/pred 中各出现 k 次时按下标顺序配对（避免重复块错配）
    gt_pos: dict[str, list[int]] = {}
    for i, t in enumerate(gt_norm):
        if t:
            gt_pos.setdefault(t, []).append(i)
    for j, t in enumerate(pred_norm):
        if not t:
            continue
        queue = gt_pos.get(t)
        if queue:
            i = queue.pop(0)
            matches.append((i, j))
            used_pred.add(j)

    # 2) 模糊匹配：未匹配的 GT 按顺序找最优剩余 pred，相似度 >= 0.6 才收
    matched_gt = {i for i, _ in matches}
    for i, gt in enumerate(gt_norm):
        if not gt or i in matched_gt:
            continue
        best_j, best_v = -1, 0.0
        for j, pred in enumerate(pred_norm):
            if j in used_pred or not pred:
                continue
            v = SequenceMatcher(None, gt, pred).ratio()
            if v > best_v:
                best_j, best_v = j, v
        if best_j >= 0 and best_v >= 0.6:
            matches.append((i, best_j))
            used_pred.add(best_j)
    return sorted(matches)


def pairwise_order_accuracy(gt_blocks: list[str], pred_blocks: list[str]) -> float | None:
    """有序对准确率：对齐后的块两两组合，相对顺序一致的比例。匹配 < 2 对返回 None。"""
    matches = align_blocks(gt_blocks, pred_blocks)
    if len(matches) < 2:
        return None
    agree = 0
    total = 0
    for a in range(len(matches)):
        gi_a, pi_a = matches[a]
        for b in range(a + 1, len(matches)):
            gi_b, pi_b = matches[b]
            total += 1
            if (gi_a - gi_b) * (pi_a - pi_b) > 0:
                agree += 1
    return agree / total if total else None
