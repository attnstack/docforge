# 职责：pytest 共享 fixture。所有 PDF 测试样本用 PyMuPDF 程序化生成，不依赖二进制资产。

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 保证直接以 `pytest tests/` 运行时也能 import 顶层包（editable 安装后本不需要，双保险）
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docforge.config import PipelineConfig  # noqa: E402


@pytest.fixture()
def cfg() -> PipelineConfig:
    return PipelineConfig()
