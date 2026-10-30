# 人工标注工作区

真实标注集（v0.1：50–100 页）的工作目录。每个样本一个子目录，结构：

```
human/
  <sample-id>/
    source.pdf      # 待标注原文（受版权约束的文档不入库，见 docs/benchmark.md 合规节）
    pred.md         # docforge 预标注结果（docforge annotate 生成）
    gt.json         # 标注员 A 的 GT（按 docs/benchmark.md 填写）
    gt.b.json       # 标注员 B 的独立标注（双人流程时）
    notes.md        # 争议点与仲裁记录
```

流程（详见 docs/benchmark.md）：

1. `docforge annotate source.pdf --out human/<sample-id>/` 生成预标注与 GT 模板；
2. 标注员 A/B 各自独立修正为 GT（不看对方结果）；
3. `docforge bench-agree human/<sample-id>/gt.json human/<sample-id>/gt.b.json` 出一致性报告；
4. 不一致样本第三人仲裁，结论写进 notes.md；
5. manifest 收录后随版本发布（`docforge-zh-human-v0.1`）。
