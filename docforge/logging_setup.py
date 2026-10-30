# 职责：统一日志。默认人类可读，--json-logs 输出单行 JSON 便于采集；
# stage_timer 用于关键路径埋点（每个流水线阶段的耗时与规模指标）。

from __future__ import annotations

import json
import logging
import sys
import time
from contextlib import contextmanager
from typing import Iterator

_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO", json_logs: bool = False) -> None:
    if level.upper() not in _LEVELS:
        level = "INFO"
    handler = logging.StreamHandler(sys.stderr)
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, level.upper()))


@contextmanager
def stage_timer(logger: logging.Logger, name: str, **kv: object) -> Iterator[None]:
    """关键路径埋点：记录阶段耗时与规模（如 blocks=N），便于性能归因。"""
    start = time.perf_counter()
    try:
        yield
    finally:
        ms = (time.perf_counter() - start) * 1000
        extra = " ".join(f"{k}={v}" for k, v in kv.items())
        logger.info("stage=%s ms=%.1f %s", name, ms, extra)
