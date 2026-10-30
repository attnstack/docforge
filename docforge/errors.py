# 职责：错误分类。可恢复（提示安装/跳过/重试）与不可恢复（输入非法/程序 bug）分开，
# CLI 据此决定打印 hint 返回退出码 2（用户错误）还是带栈返回 1（程序 bug）。

from __future__ import annotations


class DocforgeError(Exception):
    """docforge 可预期错误基类。message 面向用户，hint 给出可执行的下一步。"""

    hint: str = ""

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint or self.hint


class UnsupportedInputError(DocforgeError):
    """输入不受支持：加密 PDF、空文档、页数超限、文件过大等。"""


class OcrUnavailableError(DocforgeError):
    """页面是扫描件（无可提取文字层），但 OCR 引擎未安装。"""

    hint = "扫描件需要 OCR 引擎：pip install 'docforge[ocr]'（首次运行会自动下载模型），或改用含文字层的 PDF。"


class EngineNotFoundError(DocforgeError):
    """指定的解析引擎不存在或其依赖未安装。"""

    hint = "运行 `docforge engines` 查看引擎与安装状态；基线引擎需要 pip install 'docforge[bench]'。"


class DatasetError(DocforgeError):
    """benchmark 数据集缺失或损坏（缺 manifest、输入文件不存在等）。"""

    hint = "先运行 `docforge gen-seed` 生成合成种子数据集，或检查 manifest.json。"


class SchemaViolationError(DocforgeError):
    """benchmark 提交文件不符合公布 schema。"""
