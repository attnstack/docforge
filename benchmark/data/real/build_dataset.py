# 职责：构建 docforge-zh-real-v0.1-rc（真实政府公文样本 + 人工核验 GT）。
#
# 数据来源（依《著作权法》第五条，国家机关公文不受著作权保护，可再分发）：
#   - 西乌珠穆沁旗 2024 年政府工作报告（xwq.gov.cn）
#   - 武汉市江夏区 2024 年区《政府工作报告》主要目标任务责任分解方案（jiangxia.gov.cn）
# 标注协议：单标注（GT 文本取自 PDF 文字层并逐块与原文核对；结构信息由标注员
# 读渲染图核定）；双人独立标注与一致性检验待补，发布名为 v0.1-rc。
# QA：每条 GT 文本块归一化后必须能在页面文字层中找到；GT 覆盖率 >= 0.95。

from __future__ import annotations

import json
import re
import shutil
import unicodedata
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[3] / "benchmark"
SRC = ROOT.parent / ".tmp" / "realpdf"
OUT = ROOT / "data" / "real-v0.1-rc"

_WS = re.compile(r"\s+")


def norm(s: str) -> str:
    return _WS.sub("", unicodedata.normalize("NFKC", s)).lower()


# ---------- GT 定义（文本逐块取自文字层转写；结构由标注员读渲染图核定） ----------

XWQ_P1_TEXT = [
    "会议文件（二十三）",
    "政府工作报告",
    "2024 年1 月26 日在西乌珠穆沁旗第十六届人民代表大会第四次会议上",
    "西乌珠穆沁旗人民政府旗长 姚宏刚",
    "各位代表：",
    "现在，我代表旗人民政府向大会报告工作，请予审议，并请旗政协各位委员和列席会议的同志提出意见。",
    "一、2023 年工作回顾",
    "刚刚过去的2023 年，是全面贯彻落实党的二十大精神的开局之年。一年来，我们坚持以习近平新时代中国特色社会主义思想为指导，深入贯彻落实习近平总书记对内蒙古重要指示精神，在盟委、行署和旗委坚强领导下，坚持把铸牢中华民族共同体意识作为各项工作的主线，全力以赴办好两件大事，凝心聚力抓发展、促改革、惠民生、增团结、保安全，较好完成了全年各项目标任务，重点工作综合排名全盟前列。",
    "（一）经济运行总体稳定向好。地区生产总值完成217 亿元，同比增长6.2%；固定资产投资完成63.1 亿元，同比增长30.5%；一般公共预算收入完成27.8 亿元，同比增长16.3%；城镇和牧区居民人均可支配收入分别完成50980 元和37774 元，分别增长",
]
XWQ_P1_HEADINGS = [[1, "政府工作报告"], [1, "一、2023 年工作回顾"]]

XWQ_P11_TEXT = [
    "今年政府工作的总体要求是：以习近平新时代中国特色社会主义思想为指导，全面贯彻党的二十大和二十届二中全会及中央经济工作会议精神，深入贯彻习近平总书记对内蒙古的重要指示精神，认真贯彻上级党委、政府决策部署和中共西乌旗第13 届委员会第11 次全体（扩大）会议暨全旗经济工作会议精神，锚定闯新路、进中游奋斗目标，坚持稳中求进、以进促稳、先立后破，将铸牢中华民族共同体意识作为各项工作的主线，以高质量落实“六个工程”为抓手，凝心聚力办好两件大事，统筹推进稳增长、促改革、调结构、惠民生、防风险、保稳定各项工作，推动各领域工作争名进位，奋力谱写现代化西乌旗建设新篇章。",
    "今年全旗经济社会发展主要预期目标是：地区生产总值增长6%左右；固定资产投资增长20%左右；一般公共预算收入增长4.7%；社会消费品零售总额增长6.6%；城乡居民收入增速高于经济增速；完成上级下达节能减排目标任务。",
    "为实现上述预期目标，重点做好以下七个方面工作：",
    "（一）坚定不移抓项目扩投资，推动经济持续稳定向好",
    "一要千方百计抓好招商引资。继续把招商引资作为“头号工程”，聚焦现代能源、循环经济、铝基及有色金属、绿色生态、现代文旅、现代畜牧业、泛口岸、现代流通、民生等9 条产业链，有针对性引进一批更高科技含量、更高附加值、更低能耗的优质项目，努力补齐产业链的短板弱项。坚持权责对等、优惠与产出相挂钩，突出投资强度、税收额度、建设时限等标准，加强合同",
]
XWQ_P11_HEADINGS = [[2, "（一）坚定不移抓项目扩投资，推动经济持续稳定向好"]]

JX_P1_TEXT = [
    "2024 年区《政府工作报告》主要目标任务责任分解方案",
    "一、全区经济社会发展的主要预期目标（以市级下达目标为参照，以区委组织部下达至各街道办事处、区直各单位的绩效目标为准）",
    "二、重点工作（共96 项）",
    "（一）大抓组团融圈，构筑高质量发展“新格局”",
    "——推动汤逊湖组团建设起势见效。（总牵头单位：江夏经济开发区管委会）",
    "1.深化开发区体制机制改革，争创国家级开发区。支持庙山建设汤逊湖科创中心，藏龙岛建设现代服务业集聚区、军民融合示范区，大桥建设绿电园区、新能源产业集聚区，金港打造新能源智能网联汽车示范基地。推进“工业上楼”，打造“立起来”的开发区。（牵头单位：江夏经济开发区管委会；责任单位：区委组织部、区委编办、区发改局、区科经局、区人社局、区自然资源和规划局、区国控集团）",
    "2.锚定“科技成果转移转化首选地、青年创新城”目标，统筹推进环汤逊湖大学创新带、汤逊湖科创小镇、花山吴人工智能小镇、金港汽车小镇等标志性项目，加速壮大组团实力。（牵头单位：区科经局；责任单位：江夏经济开发区管委会，区区校合作发展促进中心，区国控集团、区科投集团）",
]
JX_P1_HEADINGS = [
    [1, "2024 年区《政府工作报告》主要目标任务责任分解方案"],
    [1, "一、全区经济社会发展的主要预期目标（以市级下达目标为参照，以区委组织部下达至各街道办事处、区直各单位的绩效目标为准）"],
    [1, "二、重点工作（共96 项）"],
    [2, "（一）大抓组团融圈，构筑高质量发展“新格局”"],
    [3, "——推动汤逊湖组团建设起势见效。（总牵头单位：江夏经济开发区管委会）"],
]


def table_span_001_html() -> str:
    # 附表1：5 列 x 13 行；序号/责任事项两列各按组 rowspan=4（网格线坐标已从 PDF 矢量层核验）
    rows = ['<tr><td>序号</td><td>责任事项</td><td>工作措施</td><td>具体项目</td><td>完成时间（按月）</td></tr>']
    for g in (1, 2, 3):
        rows.append(f'<tr><td rowspan="4">{g}</td><td rowspan="4"></td><td>1.……</td><td></td><td></td></tr>')
        for k in ("2.……", "3.……", "4.……"):
            rows.append(f"<tr><td>{k}</td><td></td><td></td></tr>")
    return "<table>" + "".join(rows) + "</table>"


def table_span_002_html() -> str:
    # 附表3：4 列 x 6 行；末行备注 colspan=4
    rows = ["<tr><td>序号</td><td>责任事项</td><td>落实情况</td><td>工作进度（已完成、序时推进、滞后序时）</td></tr>"]
    for n in ("1", "2", "3", "……"):
        rows.append(f"<tr><td>{n}</td><td></td><td></td><td></td></tr>")
    rows.append('<tr><td colspan="4">备注：为便于统计，责任事项序号请按区《政府工作报告》目标任务责任分解方案确定的序号排序。</td></tr>')
    return "<table>" + "".join(rows) + "</table>"


JX_P24_TEXT = [
    "附表1",
    "XXX（单位）区《政府工作报告》办理方案",
    "单位：",
    "主要负责人（签字）：",
]
JX_P24_HEADINGS = [[2, "附表1"], [1, "XXX（单位）区《政府工作报告》办理方案"]]

JX_P26_TEXT = [
    "附表3",
    "XXX（单位）第X 季度工作目标完成情况",
    "单位：",
    "主要负责人（签字）：",
]
JX_P26_HEADINGS = [[2, "附表3"], [1, "XXX（单位）第X 季度工作目标完成情况"]]


SAMPLES = [
    {"id": "real-gov-001", "src": "xwq-p1.pdf", "type": "gov_text",
     "text_blocks": XWQ_P1_TEXT, "headings": XWQ_P1_HEADINGS, "tables": []},
    {"id": "real-gov-002", "src": "xwq-p11.pdf", "type": "gov_text",
     "text_blocks": XWQ_P11_TEXT, "headings": XWQ_P11_HEADINGS, "tables": []},
    {"id": "real-gov-003", "src": "jx-p1.pdf", "type": "gov_text",
     "text_blocks": JX_P1_TEXT, "headings": JX_P1_HEADINGS, "tables": []},
    {"id": "real-table-001", "src": "jx-p24.pdf", "type": "gov_table",
     "text_blocks": JX_P24_TEXT, "headings": JX_P24_HEADINGS, "tables": [table_span_001_html()]},
    {"id": "real-table-002", "src": "jx-p26.pdf", "type": "gov_table",
     "text_blocks": JX_P26_TEXT, "headings": JX_P26_HEADINGS, "tables": [table_span_002_html()]},
    # 扫描仿真样本：无文字层，GT 从数字版精确继承，QA 对照数字版原文
    {"id": "real-scan-001", "src": "xwq-p1-scan.pdf", "type": "gov_scan", "qa_src": "xwq-p1.pdf",
     "text_blocks": XWQ_P1_TEXT, "headings": XWQ_P1_HEADINGS, "tables": []},
    {"id": "real-scan-002", "src": "jx-p24-scan.pdf", "type": "gov_scan", "qa_src": "jx-p24.pdf",
     "text_blocks": JX_P24_TEXT, "headings": JX_P24_HEADINGS, "tables": [table_span_001_html()]},
]

SOURCES = [
    {
        "doc": "西乌珠穆沁旗人民政府 2024 年政府工作报告",
        "url": "https://www.xwq.gov.cn/xwzmqq/zwgk/zfgzbg/2024012911271246627/2024012911262617370.pdf",
        "license_note": "国家机关公文，依《中华人民共和国著作权法》第五条不适用著作权保护",
    },
    {
        "doc": "武汉市江夏区 2024 年区《政府工作报告》主要目标任务责任分解方案",
        "url": "http://www.jiangxia.gov.cn/xxgk_22343/zc/qtwj/qt_22356/202403/P020240329436367515351.pdf",
        "license_note": "同上",
    },
]


def main() -> None:
    (OUT / "inputs").mkdir(parents=True, exist_ok=True)
    (OUT / "gt").mkdir(parents=True, exist_ok=True)
    failures = []
    for s in SAMPLES:
        src_path = SRC / s["src"]
        shutil.copy2(src_path, OUT / "inputs" / s["src"])

        # QA 1：每条 GT 文本块必须能在原文文字层中找到（扫描件对照数字版原文，防转写错字）
        qa_text = norm(pymupdf.open(SRC / s.get("qa_src", s["src"]))[0].get_text())
        for block in s["text_blocks"]:
            if norm(block) not in qa_text:
                failures.append(f"{s['id']}: GT 块不在原文中: {block[:40]}...")
        # QA 1b：表格 GT 的每个非空单元格文本必须能在原文中找到
        for tbl in s["tables"]:
            for cell in re.findall(r"<td[^>]*>(.*?)</td>", tbl):
                if cell and norm(cell) not in qa_text:
                    failures.append(f"{s['id']}: 表格单元格不在原文中: {cell[:30]}...")
        # QA 2：纯文本页的 GT 覆盖率 >= 0.95（表格页正文少，覆盖率被表格内容稀释，改由 QA1b 把关）
        if not s["tables"]:
            page_lines = [ln for ln in pymupdf.open(SRC / s.get("qa_src", s["src"]))[0].get_text().splitlines() if ln.strip()]
            kept = [ln for ln in page_lines if not re.match(r"^[-—–\s]*(第)?\s*\d+\s*(页)?[-—–\s]*$", ln.strip())]
            gt_cov = len(norm("".join(s["text_blocks"]))) / max(len(norm("".join(kept))), 1)
            if gt_cov < 0.95:
                failures.append(f"{s['id']}: GT 覆盖率 {gt_cov:.3f} < 0.95")

        gt = {"engine": "ground-truth", "dataset": "docforge-zh-real-v0.1-rc",
              "samples": [{"id": s["id"], "text_blocks": s["text_blocks"], "tables": s["tables"], "headings": s["headings"]}]}
        (OUT / "gt" / f"{s['id']}.json").write_text(json.dumps(gt, ensure_ascii=False, indent=2), encoding="utf-8")

    if failures:
        print("QA FAILED:")
        for f in failures:
            print(" -", f)
        raise SystemExit(1)

    manifest = {
        "name": "docforge-zh-real-v0.1-rc",
        "synthetic": False,
        "annotation": "单标注 v0.1-rc：GT 文本取自 PDF 文字层并逐块与原文核对，结构（标题层级/表格跨行列/阅读顺序）由标注员读页面渲染图核定；双人独立标注与一致性检验进行中",
        "notes": "真实政府公文（依《著作权法》第五条可再分发）。数字页文字来自文字层（文本指标对文字层引擎区分度低，结构指标是主要区分维度）；gov_scan 为整页位图仿真扫描件（内容与数字版一致，GT 可精确继承），文本指标在该子集上衡量 OCR 质量",
        "sources": SOURCES,
        "samples": [{"id": s["id"], "type": s["type"], "input": f"inputs/{s['src']}", "gt": f"gt/{s['id']}.json"} for s in SAMPLES],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: {len(SAMPLES)} samples written to {OUT} (all QA passed)")


if __name__ == "__main__":
    main()
