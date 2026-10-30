# docforge 一键运行镜像：CPU 模式，含自研引擎 + OCR（PaddleOCR）+ 基线 + server
# 构建后直接 demo：docker run --rm -v "$PWD:/data" docforge convert /data/in.pdf -o /data/out.md
FROM python:3.11-slim

# paddleocr 依赖链需要：libgomp1（paddle）、libgl1/libglib2.0-0（opencv）
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY docforge ./docforge
COPY benchmark ./benchmark

# PaddleOCR 模型文件不入镜像（几百 MB），首次运行自动下载到 ~/.paddleocr；
# 持久化：docker run -v docforge-models:/root/.paddleocr ...
RUN pip install --no-cache-dir ".[ocr,bench,server]"

ENTRYPOINT ["docforge"]
CMD ["--help"]
