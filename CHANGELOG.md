# Changelog

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [0.2.0] - 2026-11-04

### 新增
- `convert --pages "1-3,7"`：页范围选择（1-based 闭区间，支持全角逗号），只解析所选页
- `convert --password`：加密 PDF 支持（口令错误/缺失给出明确错误与提示）
- `convert` 直接接受 http(s) URL 输入：流式下载（大小上限保护）后进入本地流水线
- 扫描页标题识别：OCR 行框高度作为字号代理 + 检测框压缩补偿；扫描页只判 H1/H2，
  文档标题由晋升规则定级（真实公文集两个扫描页实测正确）
- 英文版 README（README_EN.md）
- Dependabot（pip + GitHub Actions 每周检查）、CI 矩阵扩展到 Python 3.12
- 真实集重测：扫描页标题识别使标题树 0.8095 → 0.9524、综合 0.8321 → 0.8678（基线数字不变）

### 修复
- OCR 段落合并重建 Block 时丢失行块 meta（font_size 代理失效导致扫描页标题识别不生效）

## [0.1.0] - 2026-10-31

### 首个发布
- 数字版 PDF 全链路：提取/版面/阅读顺序/表格结构（rowspan/colspan）/导出
- Markdown 与带 bbox 可溯源 JSON 双输出
- 公开 Benchmark：CER / TEDS / 阅读顺序 / 标题树四项确定性指标 + 提交 Schema + 榜单生成
- 合成种子集（10 样本）与真实公文集 v0.1-rc（7 样本，两轮独立复核一致率 1.0000）
- 扫描件 OCR 可选依赖（PaddleOCR 2.x/3.x 双代适配；Windows 原生验证）
- CLI（convert/bench/leaderboard/annotate/bench-agree/gen-seed/engines/server）、Docker、FastAPI
