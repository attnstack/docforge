# 职责：自研流水线的引擎封装。

from __future__ import annotations

from pathlib import Path

from docforge import __version__, pipeline
from docforge.config import PipelineConfig
from docforge.engines.base import BaseEngine, EngineResult
from docforge.stages import ocr


class DocforgeEngine(BaseEngine):
    name = "docforge"
    supports_scanned = True

    def parse(
        self,
        path: Path,
        cfg: PipelineConfig,
        image_out_dir: Path | None = None,
        *,
        password: str | None = None,
        pages_spec: str | None = None,
    ) -> EngineResult:
        # OCR 引擎未安装时 parse_document 只会在遇到扫描页时报错——数字版文档无需 OCR 依赖；
        # 不做 eager warmup：纯数字文档不应付出模型加载成本（模型在首次识别时才加载）
        try:
            engine = ocr.get_ocr()
        except ocr.OcrUnavailableError:
            engine = None
        doc = pipeline.parse_document(
            path, cfg, ocr_engine=engine, image_out_dir=image_out_dir, password=password, pages_spec=pages_spec
        )
        from docforge.stages.export import assemble_markdown

        return EngineResult(
            markdown=assemble_markdown(doc, tables_format=cfg.tables_format),
            blocks=doc.blocks,
            meta={"engine": "docforge", "version": __version__, "document": doc},
        )
