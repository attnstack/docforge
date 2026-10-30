# 职责：PyMuPDF 导入兼容层。1.24+ 推荐顶层模块名 pymupdf，旧 wheel 只有 fitz。

from __future__ import annotations

try:
    import pymupdf as fitz  # noqa: F401  (re-export)
except ImportError:  # pragma: no cover - 仅旧版本触发
    import fitz  # type: ignore[no-redef]

__all__ = ["fitz"]
