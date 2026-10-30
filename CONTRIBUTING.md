# Contributing

欢迎 PR。工程约定先读一遍，能省一轮 review。

## 开发环境

```bash
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -e ".[dev,bench]"
ruff check docforge benchmark
pytest
```

可选：OCR 能力 `pip install "docforge[ocr]"`（PaddleOCR 较重，CI 不装，本地测试扫描链路时自行安装）。

## 提交前检查

1. `pytest` 全绿——核心算法（阅读顺序/表格/指标）的改动必须带新单测，覆盖正常/边界/异常三类输入；
2. `ruff check` 无告警；
3. 若改了指标实现或归一化：跑 `docforge bench --engine docforge`，在 PR 里贴出前后对比——种子集上任何数字变化都要能解释；
4. 破坏性改动（schema、归一化规则、GT 格式）必须升数据集版本号。

## 加一个基线引擎

1. 在 `docforge/engines/` 新增引擎类，继承 `BaseEngine`，实现 `parse` 与 `missing_dependency`；
2. 纯 markdown 输出的引擎直接继承 `_MarkdownEngineBase`，只实现 `_to_markdown`；
3. 在 `engines/base.py::_register_defaults` 注册；
4. 用 `docforge bench --engine your-engine` 跑一遍，确认提交能过 schema 校验。

## 标注贡献

见 [docs/benchmark.md](docs/benchmark.md) 第 4 节与 [benchmark/data/human/README.md](benchmark/data/human/README.md)。标注两个样本起即可提 PR，一致性报告附在 PR 描述里。

## commit 风格

`<area>: <what>`（如 `table: fix colspan detection on partial borders`），正文说清 why。
