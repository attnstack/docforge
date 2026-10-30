# 职责：CLI 入口。子命令：convert / bench / leaderboard / annotate / gen-seed / engines / server / bench-agree。
# 错误约定：DocforgeError -> stderr + 退出码 2（用户可修复）；未预期异常 -> 栈 + 退出码 1（程序 bug）。

from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from docforge import __version__
from docforge.config import load_config
from docforge.errors import DocforgeError

logger = logging.getLogger("docforge.cli")


def _add_convert_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("input", nargs="?", help="输入 PDF/图片；--batch 时为目录")
    sp.add_argument("-o", "--out", help="输出路径（文件或目录）")
    sp.add_argument("--format", choices=["md", "json", "both"], default="md")
    sp.add_argument("--tables", choices=["html", "md"], default="html", help="表格输出格式（默认 html，保结构）")
    sp.add_argument("--batch", action="store_true", help="目录级批处理，失败样本落入 badcases/")
    sp.add_argument("--workers", type=int, default=None, help="批处理并发数（默认 DOCFORGE_MAX_WORKERS）")
    sp.add_argument("--dpi", type=int, default=None, help="扫描页渲染 DPI")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="docforge", description="中文文档解析引擎与公开 Benchmark")
    ap.add_argument("--json-logs", action="store_true", help="输出 JSON 日志（便于采集）")
    ap.add_argument("--log-level", default="INFO")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("convert", help="解析 PDF/图片为 Markdown / JSON")
    _add_convert_args(sp)

    sp = sub.add_parser("bench", help="在数据集上评测引擎并出报告")
    sp.add_argument("--engine", action="append", default=None, help="引擎名，可重复；默认 docforge")
    sp.add_argument("--dataset", default="benchmark/data/synthetic")
    sp.add_argument("--out", default="results")
    sp.add_argument("--limit", type=int, default=None, help="只跑前 N 个样本（冒烟用）")

    sp = sub.add_parser("leaderboard", help="从结果 JSON 生成静态榜单页")
    sp.add_argument("--results", default="results")
    sp.add_argument("--out", default="leaderboard/index.html")

    sp = sub.add_parser("annotate", help="生成预标注与 GT 模板（人工标注工作区）")
    sp.add_argument("input")
    sp.add_argument("--out", required=True)

    sp = sub.add_parser("bench-agree", help="双人标注一致性报告")
    sp.add_argument("gt_a")
    sp.add_argument("gt_b")

    sp = sub.add_parser("gen-seed", help="生成合成种子数据集")
    sp.add_argument("--out", default="benchmark/data/synthetic")

    sp = sub.add_parser("engines", help="列出解析引擎与依赖状态")

    sp = sub.add_parser("server", help="启动 HTTP 服务（需 pip install 'docforge[server]'）")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)

    sub.add_parser("version", help="打印版本")
    return ap


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    from docforge.logging_setup import setup_logging

    setup_logging(args.log_level, args.json_logs)
    try:
        cfg = load_config()
        if args.cmd == "convert":
            return _cmd_convert(args, cfg)
        if args.cmd == "bench":
            return _cmd_bench(args, cfg)
        if args.cmd == "leaderboard":
            return _cmd_leaderboard(args)
        if args.cmd == "annotate":
            return _cmd_annotate(args, cfg)
        if args.cmd == "bench-agree":
            return _cmd_bench_agree(args)
        if args.cmd == "gen-seed":
            return _cmd_gen_seed(args)
        if args.cmd == "engines":
            return _cmd_engines()
        if args.cmd == "server":
            return _cmd_server(args)
        if args.cmd == "version":
            print(f"docforge {__version__}")
            return 0
    except DocforgeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if exc.hint:
            print(f"hint: {exc.hint}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    return 0


# ---------- 子命令实现 ----------


def _cmd_convert(args, cfg) -> int:
    from docforge.engines import get_engine
    from docforge.stages.export import to_json_dict

    if not args.input:
        print("error: 需要输入路径（--batch 时为目录）", file=sys.stderr)
        return 2
    if args.tables:
        from dataclasses import replace

        cfg = replace(cfg, tables_format=args.tables)
    engine = get_engine("docforge")

    if args.batch:
        return _convert_batch(args, cfg, engine)

    result = engine.parse(Path(args.input), cfg, image_out_dir=_image_dir(args.out))
    if args.format in ("md", "both"):
        out_md = Path(args.out) if args.out else Path(args.input).with_suffix(".md")
        if args.format == "both" and out_md.suffix == ".json":
            out_md = out_md.with_suffix(".md")
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(result.markdown or "", encoding="utf-8")
        print(f"written: {out_md}")
    if args.format in ("json", "both"):
        out_json = (Path(args.out) if args.out else Path(args.input).with_suffix(".json"))
        if args.format == "both" and out_json.suffix != ".json":
            out_json = out_json.with_suffix(".json")
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(to_json_dict(result.meta["document"]), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"written: {out_json}")
    return 0


def _image_dir(out: str | None) -> Path | None:
    if out and Path(out).parent.name:
        d = Path(out).parent / "images"
        d.mkdir(parents=True, exist_ok=True)
        return d
    return None


def _convert_batch(args, cfg, engine) -> int:
    import shutil

    in_dir = Path(args.input)
    if not in_dir.is_dir():
        print(f"error: --batch 需要目录，收到 {in_dir}", file=sys.stderr)
        return 2
    out_dir = Path(args.out or "converted")
    out_dir.mkdir(parents=True, exist_ok=True)
    bad_dir = Path("badcases")
    files = sorted(p for p in in_dir.iterdir() if p.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg"))
    if not files:
        print(f"no convertible files in {in_dir}")
        return 0


    ok, failed = 0, 0

    def one(path: Path):
        out_md = out_dir / (path.stem + ".md")
        try:
            result = engine.parse(path, cfg)
            out_md.write_text(result.markdown or "", encoding="utf-8")
            return path, None
        except DocforgeError as exc:
            return path, exc
        except Exception as exc:  # noqa: BLE001 - 批处理吞掉单个失败继续跑，badcase 落盘
            logger.exception("unexpected failure on %s", path)
            return path, exc

    workers = args.workers or cfg.max_workers
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, p): p for p in files}
        for fut in as_completed(futures):
            path, err = fut.result()
            if err is None:
                ok += 1
                print(f"ok: {path.name}")
            else:
                failed += 1
                case_dir = bad_dir / path.stem
                case_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, case_dir / path.name)
                (case_dir / "error.json").write_text(
                    json.dumps({"error": str(err), "hint": getattr(err, "hint", ""), "file": str(path)}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"FAILED: {path.name} -> {case_dir} ({err})")
    print(f"batch done: {ok} ok, {failed} failed (badcases in {bad_dir}/)")
    return 0 if failed == 0 else 2


def _cmd_bench(args, cfg) -> int:
    from benchmark.runner import run_bench

    engines = args.engine or ["docforge"]
    report_path, _results = run_bench(engines, Path(args.dataset), Path(args.out), cfg, limit=args.limit)
    print(f"report: {report_path}")
    print(f"results dir: {Path(args.out).resolve()}")
    print("next: docforge leaderboard --results " + str(args.out))
    return 0


def _cmd_leaderboard(args) -> int:
    from benchmark.leaderboard import build_leaderboard

    out = build_leaderboard(Path(args.results), Path(args.out))
    print(f"leaderboard: {out}")
    return 0


def _cmd_annotate(args, cfg) -> int:
    from docforge.engines import get_engine

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    engine = get_engine("docforge")
    try:
        result = engine.parse(Path(args.input), cfg)
    except DocforgeError as exc:
        # 扫描页无 OCR 时依然要能产出预标注工作区：降级为空模板
        logger.warning("pre-annotation failed (%s); writing empty template", exc)
        result = None
    (out_dir / "pred.md").write_text(result.markdown if result else "", encoding="utf-8")
    template = {"id": Path(args.input).stem, "text_blocks": [], "tables": [], "headings": []}
    (out_dir / "gt.template.json").write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"annotate workspace: {out_dir}")
    print("  pred.md          预标注结果（可作为 GT 修正起点）")
    print("  gt.template.json GT 模板，按 docs/benchmark.md 填写")
    print("标注完成后运行: docforge bench-agree gt.json gt.b.json")
    return 0


def _cmd_bench_agree(args, _cfg=None) -> int:
    from benchmark.normalize import char_error_rate

    a = json.loads(Path(args.gt_a).read_text(encoding="utf-8"))
    b = json.loads(Path(args.gt_b).read_text(encoding="utf-8"))
    sa, sb = a["samples"], b["samples"]
    if len(sa) != len(sb):
        print(f"error: 样本数不一致 ({len(sa)} vs {len(sb)})", file=sys.stderr)
        return 2
    rows = []
    for x, y in zip(sa, sb, strict=True):
        ta, tb = "\n".join(x.get("text_blocks", [])), "\n".join(y.get("text_blocks", []))
        cer = char_error_rate(ta, tb)
        rows.append((x.get("id", "?"), 1 - cer, len(x.get("text_blocks", [])), len(y.get("text_blocks", []))))
    print("| 样本 | 文本一致率 (1-CER) | 块数 A | 块数 B |")
    print("|---|---|---|---|")
    for rid, agree, na, nb in rows:
        flag = "" if agree >= 0.98 else "  <- 需仲裁"
        print(f"| {rid} | {agree:.4f}{flag} | {na} | {nb} |")
    mean = sum(r[1] for r in rows) / len(rows)
    print(f"\n平均一致率: {mean:.4f}（>=0.98 视为可发布；低分样本第三人仲裁）")
    return 0


def _cmd_gen_seed(args) -> int:
    from benchmark.data.synthetic.generate import generate

    generate(Path(args.out))
    return 0


def _cmd_engines() -> int:
    from docforge.engines.docforge_engine import DocforgeEngine
    from docforge.engines.markdown_engines import MarkitdownEngine, Pymupdf4llmEngine

    for engine_cls in (DocforgeEngine, MarkitdownEngine, Pymupdf4llmEngine):
        eng = engine_cls()
        missing = eng.missing_dependency()
        status = "ready" if missing is None else f"missing: {missing}"
        scanned = "支持扫描件" if eng.supports_scanned else "仅文字层"
        print(f"{eng.name:<14} {status:<28} {scanned}")
    print("\nOCR（PaddleOCR）为可选依赖: pip install 'docforge[ocr]'")
    return 0


def _cmd_server(args) -> int:
    try:
        import uvicorn
    except ImportError:
        print("error: uvicorn 未安装", file=sys.stderr)
        print("hint: pip install 'docforge[server]'", file=sys.stderr)
        return 2
    from docforge.server.app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
