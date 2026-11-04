"""docforge：中文文档解析引擎与公开 Benchmark。

多栏/复杂表格/扫描 PDF -> LLM-ready 分层 Markdown 与带 bbox 的可溯源 JSON。
"""

try:
    from importlib.metadata import version as _v

    __version__ = _v("docforge-zh")
except Exception:  # noqa: BLE001 - 未安装（源码直用）时回退
    __version__ = "0.2.0"
