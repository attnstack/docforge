# 职责：评测执行器。数据集 -> 引擎解析 -> 统一提交格式 -> 四指标打分 -> 结果 JSON + 报告。
#
# 对比公平性：所有引擎（含基线）经过同一个 blocks_to_submission_sample 适配，
# 喂给指标的 plain text 来源可审计。

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark.metrics.heading_tree import heading_tree_similarity
from benchmark.metrics.order_and_text import pairwise_order_accuracy, text_similarity
from benchmark.metrics.teds import teds_for_tables
from benchmark.schema import validate_submission
from docforge.config import PipelineConfig
from docforge.errors import DatasetError, DocforgeError
from docforge.models import Block, BlockType
from docforge.stages.export import merge_continuations

logger = logging.getLogger(__name__)

METRIC_KEYS = ("text", "order", "table", "heading")


@dataclass
class SampleSpec:
    id: str
    doc_type: str
    input_path: Path
    gt_path: Path


@dataclass
class Dataset:
    name: str
    synthetic: bool
    samples: list[SampleSpec]
    notes: str = ""
    annotation: str = ""


def load_dataset(dataset_dir: Path) -> Dataset:
    manifest_path = dataset_dir / "manifest.json"
    if not manifest_path.exists():
        raise DatasetError(f"数据集目录缺少 manifest.json: {dataset_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    samples: list[SampleSpec] = []
    for s in manifest.get("samples", []):
        input_path = dataset_dir / s["input"]
        gt_path = dataset_dir / s["gt"]
        if not input_path.exists():
            raise DatasetError(f"样本 {s['id']} 输入文件缺失: {input_path}", hint="重新运行 docforge gen-seed")
        if not gt_path.exists():
            raise DatasetError(f"样本 {s['id']} GT 文件缺失: {gt_path}")
        samples.append(SampleSpec(id=s["id"], doc_type=s.get("type", "unknown"), input_path=input_path, gt_path=gt_path))
    if not samples:
        raise DatasetError(f"数据集 {manifest_path} 中没有样本")
    return Dataset(
        name=manifest.get("name", dataset_dir.name),
        synthetic=manifest.get("synthetic", False),
        samples=samples,
        notes=manifest.get("notes", ""),
        annotation=manifest.get("annotation", ""),
    )


def blocks_to_submission_sample(sample_id: str, blocks: list[Block]) -> dict[str, Any]:
    """有序块流 -> 提交格式。续接块先合并（与 Markdown 导出同一套逻辑，保证打分对象=演示对象）。"""
    ordered = sorted((b for b in blocks if b.reading_order is not None), key=lambda b: (b.page, b.reading_order))
    ordered = [b for b in ordered if b.type not in (BlockType.PAGE_HEADER, BlockType.PAGE_FOOTER, BlockType.IMAGE)]
    ordered = merge_continuations(ordered)
    text_blocks = [b.text.strip() for b in ordered if b.type in (BlockType.TEXT, BlockType.HEADING) and b.text.strip()]
    tables = [b.table_html for b in ordered if b.type == BlockType.TABLE and b.table_html]
    headings = [[b.heading_level or 1, b.text.strip()] for b in ordered if b.type == BlockType.HEADING]
    return {"id": sample_id, "text_blocks": text_blocks, "tables": tables, "headings": headings}


def engine_result_to_submission(sample_id: str, result) -> dict[str, Any]:
    from docforge.engines.base import EngineResult

    assert isinstance(result, EngineResult)
    if result.blocks is None:
        raise ValueError(f"引擎未产出块结构，无法构造提交: {sample_id}")
    return blocks_to_submission_sample(sample_id, result.blocks)


def score_sample(gt_sample: dict[str, Any], pred_sample: dict[str, Any]) -> dict[str, float | None]:
    gt_blocks = gt_sample.get("text_blocks", [])
    pred_blocks = pred_sample.get("text_blocks", [])
    return {
        "text": text_similarity(gt_blocks, pred_blocks) if gt_blocks or pred_blocks else None,
        "order": pairwise_order_accuracy(gt_blocks, pred_blocks),
        "table": teds_for_tables(gt_sample.get("tables", []), pred_sample.get("tables", [])),
        "heading": heading_tree_similarity(gt_sample.get("headings", []), pred_sample.get("headings", [])),
    }


def _aggregate(per_sample: list[dict[str, Any]]) -> dict[str, Any]:
    agg: dict[str, Any] = {}
    for key in METRIC_KEYS:
        values = [s[key] for s in per_sample if s.get(key) is not None]
        agg[key] = {
            "mean": round(sum(values) / len(values), 4) if values else None,
            "coverage": f"{len(values)}/{len(per_sample)}",
        }
    available = [agg[k]["mean"] for k in METRIC_KEYS if agg[k]["mean"] is not None]
    agg["overall"] = round(sum(available) / len(available), 4) if available else None
    return agg


def run_engine(engine_name: str, dataset: Dataset, cfg: PipelineConfig, limit: int | None = None) -> dict[str, Any]:
    from docforge.engines import get_engine

    engine = get_engine(engine_name)
    per_sample: list[dict[str, Any]] = []
    for spec in dataset.samples[:limit] if limit else dataset.samples:
        t0 = time.perf_counter()
        try:
            result = engine.parse(spec.input_path, cfg)
        except DocforgeError as exc:
            # 单样本失败（如扫描页遇未装 OCR）不拖垮整个评测：记错误、指标置空、继续
            logger.warning("engine %s failed on %s: %s", engine_name, spec.id, exc)
            per_sample.append(
                {
                    "id": spec.id,
                    "type": spec.doc_type,
                    "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
                    "error": f"{type(exc).__name__}: {exc}",
                    **{k: None for k in METRIC_KEYS},
                }
            )
            continue
        duration_ms = (time.perf_counter() - t0) * 1000
        pred = engine_result_to_submission(spec.id, result)
        errors = validate_submission({"engine": engine_name, "dataset": dataset.name, "samples": [pred]})
        if errors:
            logger.error("engine %s produced invalid submission for %s: %s", engine_name, spec.id, errors)
        gt_doc = json.loads(spec.gt_path.read_text(encoding="utf-8"))
        gt_sample = gt_doc["samples"][0]
        scores = score_sample(gt_sample, pred)
        per_sample.append(
            {
                "id": spec.id,
                "type": spec.doc_type,
                "duration_ms": round(duration_ms, 1),
                **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in scores.items()},
            }
        )
        logger.info("scored %s/%s: %s", engine_name, spec.id, {k: v for k, v in scores.items()})
    return {
        "engine": engine_name,
        "dataset": dataset.name,
        "synthetic": dataset.synthetic,
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "aggregate": _aggregate(per_sample),
        "per_sample": per_sample,
    }


def render_report(results: list[dict[str, Any]], dataset: Dataset) -> str:
    lines: list[str] = []
    lines.append(f"# docforge 评测报告 — {dataset.name}")
    lines.append("")
    if dataset.synthetic:
        lines.append("> ⚠️ 合成种子集：样本由程序生成、GT 精确已知。数字用于验证评测链路与引擎正确性，**不构成对真实文档的性能主张**。")
        lines.append("")
    if dataset.annotation:
        lines.append(f"- 标注方式：{dataset.annotation}")
    if dataset.notes:
        lines.append(f"- 说明：{dataset.notes}")
    lines.append(f"- 生成时间：{datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append(f"- 样本量：{len(dataset.samples)}")
    lines.append(f"- 类型分布：{dict((t, sum(1 for s in dataset.samples if s.doc_type == t)) for t in sorted({s.doc_type for s in dataset.samples}))}")
    lines.append("")
    lines.append("## 汇总")
    lines.append("")
    header = "| 引擎 | 文本 1−CER ↑ | 阅读顺序 ↑ | 表格 TEDS ↑ | 标题树 ↑ | 综合 ↑ |"
    sep = "|---|---|---|---|---|---|"
    lines += [header, sep]
    for r in sorted(results, key=lambda x: -(x["aggregate"]["overall"] or 0)):
        agg = r["aggregate"]
        cells = [r["engine"]]
        for k in METRIC_KEYS:
            m = agg[k]["mean"]
            cells.append("—" if m is None else f"{m:.4f} ({agg[k]['coverage']})")
        cells.append("—" if agg["overall"] is None else f"{agg['overall']:.4f}")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## 按类型分解")
    lines.append("")
    types = sorted({s["type"] for r in results for s in r["per_sample"]})
    for t in types:
        lines.append(f"### {t}")
        lines.append("")
        lines += [header, sep]
        for r in results:
            rows = [s for s in r["per_sample"] if s["type"] == t]
            cells = [r["engine"]]
            for k in METRIC_KEYS:
                vals = [s[k] for s in rows if s.get(k) is not None]
                cells.append("—" if not vals else f"{sum(vals) / len(vals):.4f} ({len(vals)}/{len(rows)})")
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    lines.append("## 逐样本明细")
    lines.append("")
    for r in results:
        lines.append(f"### {r['engine']}")
        lines.append("")
        lines.append("| 样本 | 类型 | 耗时 ms | text | order | table | heading |")
        lines.append("|---|---|---|---|---|---|---|")
        for s in r["per_sample"]:
            cells = [s["id"], s["type"], f"{s['duration_ms']:.0f}"]
            for k in METRIC_KEYS:
                v = s.get(k)
                cells.append("—" if v is None else f"{v:.4f}")
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines) + "\n"


def run_bench(
    engine_names: list[str],
    dataset_dir: Path,
    out_dir: Path,
    cfg: PipelineConfig,
    limit: int | None = None,
) -> tuple[Path, list[dict[str, Any]]]:
    """跑全部引擎，写 out_dir/<engine>.json 与 out_dir/report.md。返回报告路径与结果。"""
    dataset = load_dataset(dataset_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for name in engine_names:
        result = run_engine(name, dataset, cfg, limit=limit)
        out_path = out_dir / f"{name}.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append(result)
        logger.info("results written: %s", out_path)
    report_path = out_dir / "report.md"
    report_path.write_text(render_report(results, dataset), encoding="utf-8")
    return report_path, results
