# 职责：HTTP 服务封装（可选依赖）。MVP 只提供同步 /convert；
# 方案中的异步 /parse + 轮询需要任务队列与落盘管理，v0.2 再做（README「不足」已声明）。

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from docforge import __version__
from docforge.config import PipelineConfig
from docforge.errors import DocforgeError

logger = logging.getLogger(__name__)

MAX_UPLOAD_MB = 200


def create_app():
    """FastAPI app 工厂。fastapi 未安装时抛 DocforgeError（CLI 层给出安装提示）。"""
    try:
        from fastapi import FastAPI, File, HTTPException, Query, UploadFile
        from fastapi.responses import JSONResponse, PlainTextResponse
    except ImportError as exc:  # pragma: no cover
        raise DocforgeError("fastapi 未安装", hint="pip install 'docforge[server]'") from exc

    app = FastAPI(title="docforge", version=__version__, description="中文文档解析引擎")
    upload_file = File(...)  # 模块级单例，避免函数默认参数在 import 期执行的歧义

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.post("/convert")
    async def convert(
        file: UploadFile = upload_file,
        format: str = Query("md", pattern="^(md|json|both)$"),
        tables: str = Query("html", pattern="^(html|md)$"),
    ):
        cfg = _cfg_with_tables(tables)
        data = await file.read()
        if len(data) > MAX_UPLOAD_MB * 1_000_000:
            raise HTTPException(status_code=413, detail=f"文件超过 {MAX_UPLOAD_MB}MB 上限")
        suffix = Path(file.filename or "upload.pdf").suffix or ".pdf"
        fd, tmp = tempfile.mkstemp(suffix=suffix)
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            from docforge.engines import get_engine

            result = get_engine("docforge").parse(Path(tmp), cfg)
            if format == "md":
                return PlainTextResponse(result.markdown or "")
            if format == "json":
                return JSONResponse(_doc_json(result))
            return JSONResponse({"markdown": result.markdown, "json": _doc_json(result)})
        except DocforgeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            try:
                Path(tmp).unlink()
            except OSError:
                logger.warning("temp upload %s not removed", tmp)

    return app


def _cfg_with_tables(tables: str) -> PipelineConfig:
    from dataclasses import replace

    return replace(PipelineConfig(), tables_format=tables)


def _doc_json(result):
    document = result.meta.get("document")
    from docforge.stages.export import to_json_dict

    return to_json_dict(document)


app = None  # 由 `docforge server` 调用 create_app()；模块级不实例化（懒加载）
