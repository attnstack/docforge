# 职责：文本工具。CJK 判定 + 智能拼接（中文之间不加空格，避免中文文本被空格碎片化）、
# 页眉页脚用的数字归一化。表格单元格拼词与导出阶段共用。

from __future__ import annotations

import re

# CJK 统一表意文字 + CJK 标点 + 全角形式。拼接时用于判断"是否补空格"。
_CJK_RANGES = (
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0x3000, 0x303F),   # CJK Symbols and Punctuation
    (0xFF00, 0xFFEF),   # Halfwidth and Fullwidth Forms
)


def is_cjk_char(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def smart_join(parts: list[str]) -> str:
    """拼接文本片段：两侧都是 CJK 时不加空格，否则加单个空格。

    why：PDF 分行/分词会打断中文连续性，直接空格连接会得到「营 收 增 长」式的碎片；
    全部不加空格又会把英文单词粘连。按边界字符类型区分是最小正确解。
    """
    out = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not out:
            out = part
        elif is_cjk_char(out[-1]) and is_cjk_char(part[0]):
            out += part
        else:
            out += " " + part
    return out


def normalize_digits(text: str) -> str:
    """页眉页脚分组键：数字替换为 #（页码逐页不同但模式相同）。"""
    return re.sub(r"\d+", "#", text).strip()
