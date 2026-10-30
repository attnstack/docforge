# 职责：全部可调参数集中于此。默认值即合理值，环境变量 DOCFORGE_* 可覆盖。
# 面试点：配置外置 + 加载期类型/范围校验——错误配置在启动时失败，而不是跑到第 N 页崩。

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class LayoutConfig:
    header_footer_margin: float = 0.10  # 页顶/底 10% 视为页眉页脚候选区
    header_footer_min_pages: int = 2    # 同文本（数字归一后）出现在 >= N 页才判页眉页脚
    header_footer_page_ratio: float = 0.5  # 或出现页数占比 >= 50%
    fullwidth_ratio: float = 0.8        # 块宽 >= 80% 页宽 -> 通栏块（分段分隔符）
    gutter_min_ratio: float = 0.025     # 分栏沟最小宽度（页宽占比；A4 约 15pt）
    gutter_min_pt: float = 8.0          # 分栏沟最小绝对宽度（pt）
    band_tolerance: float = 0.5         # 行带聚类容差 = 0.5 x 块高中位数
    scan_char_threshold: int = 25       # 文字层字符数 < 阈值 -> 视为扫描页


@dataclass(frozen=True)
class TableConfig:
    snap_tolerance_pt: float = 2.5   # 线段坐标吸附容差（PDF 浮点误差 / 双线边框）
    min_line_len_pt: float = 8.0    # 短于此的线段视为噪声（下划线等）
    border_coverage: float = 0.5     # 边界线覆盖相邻单元格 >= 50% 才算分隔
    join_tolerance_pt: float = 12.0  # 线段连通分量的拼接距离
    min_rows: int = 2
    min_cols: int = 2


@dataclass(frozen=True)
class HeadingConfig:
    h1_ratio: float = 1.5    # 字号 >= 1.5 x 正文中位数 -> H1
    h2_ratio: float = 1.25
    h3_ratio: float = 1.12
    max_heading_chars: int = 120


@dataclass(frozen=True)
class PipelineConfig:
    dpi: int = 300
    max_file_mb: int = 200
    max_pages: int = 500
    max_render_pixels: int = 40_000_000  # 单页渲染像素上限，防图像炸弹
    max_workers: int = 4
    tables_format: str = "html"  # html | md
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    table: TableConfig = field(default_factory=TableConfig)
    heading: HeadingConfig = field(default_factory=HeadingConfig)


# 环境变量名 -> (字段名, 类型)。子配置对象不支持环境变量覆盖，保持简单。
_ENV_TYPES: dict[str, type] = {
    "dpi": int,
    "max_file_mb": int,
    "max_pages": int,
    "max_render_pixels": int,
    "max_workers": int,
    "tables_format": str,
}

_RANGES: dict[str, tuple[float, float]] = {
    "dpi": (72, 600),
    "max_file_mb": (1, 4096),
    "max_pages": (1, 100_000),
    "max_render_pixels": (1_000_000, 500_000_000),
    "max_workers": (1, 64),
}


class ConfigError(ValueError):
    """配置非法（类型或范围）。"""


def load_config(env: dict[str, str] | None = None) -> PipelineConfig:
    """从环境变量构建 PipelineConfig；非法值抛 ConfigError（启动期失败）。"""
    source = os.environ if env is None else env
    overrides: dict[str, object] = {}
    for env_name, py_type in _ENV_TYPES.items():
        key = f"DOCFORGE_{env_name.upper()}"
        raw = source.get(key)
        if raw is None or raw == "":
            continue
        try:
            value = py_type(raw)
        except ValueError as exc:
            raise ConfigError(f"DOCFORGE_{env_name.upper()}={raw!r} 不是合法的 {py_type.__name__}") from exc
        if py_type is not str:  # 范围校验仅用于数值型；字符串枚举在后面单独校验
            lo, hi = _RANGES.get(env_name, (float("-inf"), float("inf")))
            if not lo <= value <= hi:
                raise ConfigError(f"DOCFORGE_{env_name.upper()}={value} 超出范围 [{lo}, {hi}]")
        overrides[env_name] = value

    cfg = PipelineConfig()
    if overrides:
        cfg = replace(cfg, **overrides)  # type: ignore[arg-type]
    if cfg.tables_format not in ("html", "md"):
        raise ConfigError(f"DOCFORGE_TABLES_FORMAT 只支持 html|md，收到 {cfg.tables_format!r}")
    return cfg
