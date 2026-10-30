# 职责：配置加载单测（环境变量覆盖 + 类型/范围校验启动期失败）。

from __future__ import annotations

import pytest

from docforge.config import ConfigError, load_config


def test_defaults():
    cfg = load_config(env={})
    assert cfg.dpi == 300 and cfg.max_workers == 4 and cfg.tables_format == "html"


def test_env_overrides():
    cfg = load_config(env={"DOCFORGE_DPI": "400", "DOCFORGE_MAX_WORKERS": "8", "DOCFORGE_TABLES_FORMAT": "md"})
    assert cfg.dpi == 400 and cfg.max_workers == 8 and cfg.tables_format == "md"


def test_bad_type_fails():
    with pytest.raises(ConfigError):
        load_config(env={"DOCFORGE_DPI": "abc"})


def test_out_of_range_fails():
    with pytest.raises(ConfigError):
        load_config(env={"DOCFORGE_DPI": "99999"})


def test_unknown_tables_format_fails():
    with pytest.raises(ConfigError):
        load_config(env={"DOCFORGE_TABLES_FORMAT": "latex"})
