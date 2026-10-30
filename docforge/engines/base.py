# 职责：解析引擎抽象与注册表。自研引擎与基线引擎统一产出 EngineResult，
# benchmark 经同一适配层打分——保证对比公平；可选依赖懒加载（被选中才 import）。

from __future__ import annotations

import importlib.util
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from docforge.config import PipelineConfig
from docforge.errors import EngineNotFoundError
from docforge.models import Block


@dataclass
class EngineResult:
    markdown: str | None
    blocks: list[Block] | None  # 有结构信息的引擎填充；纯 markdown 引擎由适配层生成
    meta: dict[str, Any] = field(default_factory=dict)


class BaseEngine(ABC):
    name: str = "base"
    supports_scanned: bool = False

    @abstractmethod
    def parse(self, path: Path, cfg: PipelineConfig, image_out_dir: Path | None = None) -> EngineResult: ...

    def missing_dependency(self) -> str | None:
        """返回缺失的可选依赖名（pip 包名）；None = 就绪。"""
        return None


# 懒工厂注册表：name -> 工厂。工厂内部才 import 可选依赖，
# 未安装 markitdown 的环境依然能跑 docforge 引擎（安装体积与体验的平衡）。
_REGISTRY: dict[str, Callable[[], BaseEngine]] = {}


def register(name: str, factory: Callable[[], BaseEngine]) -> None:
    _REGISTRY[name] = factory


def _register_defaults() -> None:
    if "docforge" in _REGISTRY:
        return
    from docforge.engines.docforge_engine import DocforgeEngine

    register("docforge", DocforgeEngine)
    from docforge.engines.markdown_engines import MarkitdownEngine, Pymupdf4llmEngine

    register("markitdown", MarkitdownEngine)
    register("pymupdf4llm", Pymupdf4llmEngine)


def get_engine(name: str) -> BaseEngine:
    _register_defaults()
    factory = _REGISTRY.get(name)
    if factory is None:
        raise EngineNotFoundError(f"未知引擎: {name}", hint=f"可用引擎: {', '.join(sorted(_REGISTRY))}")
    engine = factory()
    missing = engine.missing_dependency()
    if missing:
        raise EngineNotFoundError(
            f"引擎 {name} 依赖未安装: {missing}",
            hint=f"pip install '{missing}' 后重试；或运行 `docforge engines` 查看全部引擎状态。",
        )
    return engine


def available_engines() -> dict[str, bool]:
    """引擎名 -> 依赖是否就绪。供 CLI 列举与测试跳过逻辑使用。"""
    _register_defaults()
    out: dict[str, bool] = {}
    for name, factory in sorted(_REGISTRY.items()):
        out[name] = factory().missing_dependency() is None
    return out


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None
