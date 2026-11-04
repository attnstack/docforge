# 职责：v0.2 新功能测试——页范围选择、加密 PDF 口令、URL 输入、扫描页标题识别。

from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest

from docforge._pymupdf import fitz
from docforge.cli import fetch_url_to_temp
from docforge.config import PipelineConfig
from docforge.engines import get_engine
from docforge.errors import UnsupportedInputError
from docforge.pipeline import parse_pages_spec


def make_two_page_pdf(path: Path, encrypted: str | None = None) -> None:
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 120 + i * 40), f"第{i + 1}页内容标记", fontname="china-s", fontsize=14)
    if encrypted:
        doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw=encrypted, user_pw=encrypted)
    else:
        doc.save(str(path))
    doc.close()


# ---------- parse_pages_spec ----------


def test_pages_spec_basic():
    assert parse_pages_spec("1-3,5", 10) == [0, 1, 2, 4]
    assert parse_pages_spec("2", 10) == [1]
    assert parse_pages_spec("1，3", 10) == [0, 2]  # 全角逗号容错


def test_pages_spec_out_of_range():
    with pytest.raises(UnsupportedInputError):
        parse_pages_spec("1-11", 10)
    with pytest.raises(UnsupportedInputError):
        parse_pages_spec("0-2", 10)


def test_pages_spec_invalid():
    with pytest.raises(UnsupportedInputError):
        parse_pages_spec("5-2", 10)
    with pytest.raises(UnsupportedInputError):
        parse_pages_spec("abc", 10)
    with pytest.raises(UnsupportedInputError):
        parse_pages_spec("", 10)


# ---------- 页范围解析 + 加密 PDF ----------


def test_convert_page_range(tmp_path: Path):
    pdf = tmp_path / "two.pdf"
    make_two_page_pdf(pdf)
    engine = get_engine("docforge")
    result = engine.parse(pdf, PipelineConfig(), pages_spec="2")
    texts = [b.text for b in result.blocks if b.text.strip()]
    assert any("第2页" in t for t in texts)
    assert not any("第1页" in t for t in texts)


def test_convert_encrypted_password(tmp_path: Path):
    pdf = tmp_path / "enc.pdf"
    make_two_page_pdf(pdf, encrypted="secret123")
    engine = get_engine("docforge")
    # 无口令 -> 报错
    with pytest.raises(UnsupportedInputError):
        engine.parse(pdf, PipelineConfig())
    # 错误口令 -> 报错
    with pytest.raises(UnsupportedInputError):
        engine.parse(pdf, PipelineConfig(), password="wrong")
    # 正确口令 -> 成功
    result = engine.parse(pdf, PipelineConfig(), password="secret123")
    assert any("第1页" in b.text for b in result.blocks if b.text)


# ---------- URL 输入（本地 HTTP 服务，避免真实网络依赖） ----------


@pytest.fixture()
def http_server(tmp_path: Path):
    pdf = tmp_path / "remote.pdf"
    make_two_page_pdf(pdf)
    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kw):
            super().__init__(*args, directory=str(tmp_path), **kw)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/remote.pdf"
    server.shutdown()


def test_fetch_url_to_temp(http_server: str):
    p = fetch_url_to_temp(http_server, max_mb=50)
    try:
        assert p.exists() and p.suffix == ".pdf" and p.stat().st_size > 0
    finally:
        p.unlink(missing_ok=True)


def test_fetch_url_size_cap(http_server: str, tmp_path: Path):
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (2 * 1_000_000))
    with pytest.raises(UnsupportedInputError):
        fetch_url_to_temp(http_server.replace("remote.pdf", "big.bin"), max_mb=1)


def test_convert_url_end_to_end(http_server: str, tmp_path: Path, capsys):
    """CLI 级端到端：URL -> 下载 -> 解析 -> 写出 markdown。"""
    from docforge.cli import main

    out = tmp_path / "url_out.md"
    code = main(["convert", http_server, "-o", str(out)])
    assert code == 0
    md = out.read_text(encoding="utf-8")
    assert "第1页" in md
