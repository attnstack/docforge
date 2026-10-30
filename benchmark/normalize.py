# 职责：评测文本归一化。这是指标可信度的第一道闸：不统一归一化，CER 数字不可比。
#
# 规则刻意保持最小并写死在文档：NFKC -> 小写 -> 去全部空白 -> 去软连字符。
# markdown 语法剥离不在这里（在引擎适配层 markdown_engines 完成，规则可审计）。

from __future__ import annotations

import re
import unicodedata

_WS_RE = re.compile(r"\s+")
_SOFT_HYPHEN = "\u00ad"


def normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)  # 全角->半角、连字等视觉变体归一
    s = s.replace(_SOFT_HYPHEN, "")
    s = _WS_RE.sub("", s)
    return s.lower()


def levenshtein(a: str, b: str) -> int:
    """两行滚动的经典 DP，O(len_a*len_b) 时间、O(len_b) 空间。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def char_error_rate(gt: str, pred: str) -> float:
    """归一化字符错误率 CER = 编辑距离 / GT 长度。GT 为空时：pred 也空 -> 0，否则 -> 1。"""
    gt_n = normalize_text(gt)
    pred_n = normalize_text(pred)
    if not gt_n:
        return 0.0 if not pred_n else 1.0
    return min(levenshtein(gt_n, pred_n) / len(gt_n), 1.0)
