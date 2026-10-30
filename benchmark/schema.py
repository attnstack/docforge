# 职责：benchmark 提交文件的 JSON Schema 与校验。
# 榜单防作弊第一道闸：格式不合法直接拒绝。schema 公布即契约，改动必须升 dataset 版本。

from __future__ import annotations

from typing import Any

import jsonschema

SUBMISSION_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "docforge submission",
    "type": "object",
    "required": ["engine", "samples"],
    "properties": {
        "engine": {"type": "string", "minLength": 1},
        "dataset": {"type": "string"},
        "samples": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "text_blocks"],
                "properties": {
                    "id": {"type": "string"},
                    # 文本块：不含表格内容（表格由 tables 单独评），顺序 = 阅读顺序
                    "text_blocks": {"type": "array", "items": {"type": "string"}},
                    "tables": {"type": "array", "items": {"type": "string"}},  # HTML <table>...</table>
                    "headings": {
                        # [level(1-6), text] 二元组数组
                        "type": "array",
                        "items": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 2,
                            "items": [{"type": "integer", "minimum": 1, "maximum": 6}, {"type": "string"}],
                        },
                    },
                    "meta": {"type": "object"},
                },
            },
        },
    },
}


def validate_submission(obj: Any) -> list[str]:
    """返回人类可读错误列表（空列表 = 合法）。"""
    validator = jsonschema.Draft7Validator(SUBMISSION_SCHEMA)
    errors = []
    for err in sorted(validator.iter_errors(obj), key=lambda e: list(e.absolute_path)):
        path = ".".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"{path}: {err.message}")
    return errors
