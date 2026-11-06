# -*- coding: utf-8 -*-
"""
生成《工程勘察费预算/结算报告》(.docx)。

结构：
  封面标题 → 一、工程概况 → 二、计价依据 → 三、勘察工作量统计
  → 四、费用计算明细 → 五、费用统计表 → 六、编制说明
"""
import time

from . import label as LB
from .version import VERSION_LINE

try:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor
    HAS_DOCX = True
except Exception:          # 组件缺失时不影响主程序启动
    HAS_DOCX = False
    Document = None

FONT = "宋体"
HEAD_FILL = "E8EEF6"
SUB_FILL = "F4F6FA"
TOTAL_FILL = "FBEEDC"


# ---------------------------------------------------------------------------
# 基础排版工具
# ---------------------------------------------------------------------------
def _font(run, size=10.5, bold=False, name=FONT, color=None):
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.append(rf)
    rf.set(qn("w:eastAsia"), name)


def _shade(cell, color):
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), color)
    tcpr.append(shd)


def _align(cell, mode="left"):
    for p in cell.paragraphs:
        p.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT,
                       "center": WD_ALIGN_PARAGRAPH.CENTER,
                       "right": WD_ALIGN_PARAGRAPH.RIGHT}[mode]


def _cell(cell, text, size=10.5, bold=False, mode="left", color=None):
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(1)
    _font(p.add_run(str(text)), size=size, bold=bold, color=color)
    _align(cell, mode)


def _h(doc, text, size=13):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(5)
    _font(p.add_run(text), size=size, bold=True, color="1F3A5F")
    return p


def _p(doc, text, size=10.5, indent=True):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.35
    if indent:
        p.paragraph_format.first_line_indent = Cm(0.74)
    _font(p.add_run(text), size=size)
    return p


def _money(v):
    return "{:,.2f}".format(float(v or 0))


def _table(doc, cols, widths=None, aligns=None):
    t = doc.add_table(rows=1, cols=cols)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    if widths:
        t._kc_widths = widths
        _apply_widths(t.rows[0], widths)
    return t


def _apply_widths(row, widths):
    for i, w in enumerate(widths):
        if i < len(row.cells):
            row.cells[i].width = Cm(w)


def _head_row(t, titles, aligns=None):
    cells = t.rows[0].cells
    for i, title in enumerate(titles):
        _cell(cells[i], title, size=10, bold=True,
              mode=(aligns[i] if aligns else "center"))
        _shade(cells[i], HEAD_FILL)
    t.rows[0].height = Cm(0.75)
    if getattr(t, "_kc_widths", None):
        _apply_widths(t.rows[0], t._kc_widths)


def _add(t, values, aligns=None, bold=False, fill=None, size=10):
    cells = t.add_row().cells
    for i, v in enumerate(values):
        _cell(cells[i], v, size=size, bold=bold,
              mode=(aligns[i] if aligns else "center"))
        if fill:
            _shade(cells[i], fill)
    if getattr(t, "_kc_widths", None):
        _apply_widths(t.rows[-1], t._kc_widths)
    return cells


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def export_report(state, result, path):
    if not HAS_DOCX:
        raise RuntimeError("缺少 python-docx 组件，无法生成 Word 报告")
    state = state or {}
    result = result or {}
    meta = state.get("meta") or {}
    sections = result.get("sections") or []
    totals = result.get("totals") or {}
    holes = result.get("holes") or []
    mode = state.get("mode") or "budget"
    mode_cn = "结算" if mode == "settle" else "预算"
    today = time.strftime("%Y年%m月%d日")

    doc = Document()
    sec = doc.sections[0]
    sec.left_margin = Cm(2.4)
    sec.right_margin = Cm(2.2)
    sec.top_margin = Cm(2.2)
    sec.bottom_margin = Cm(2.0)

    style = doc.styles["Normal"]
    style.font.name = FONT
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)

    # ---------------- 标题 ----------------
    # 第一行为项目名称，第二行为报告名称，二者同字号同字体
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(2)
    _font(p.add_run(meta.get("project") or "（未填写工程名称）"), size=20, bold=True, color="17365D")

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(2)
    _font(p.add_run("工程勘察费%s报告" % mode_cn), size=20, bold=True, color="17365D")

    # 版本行（封面，灰色小字）
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(14)
    _font(p.add_run(VERSION_LINE), size=9, color="7A8794")

    # ---------------- 一、工程概况 ----------------
    _h(doc, "一、工程概况")
    total_depth = sum(float(h.get("depth") or 0) for h in holes)
    max_depth = max([float(h.get("depth") or 0) for h in holes] or [0])
    info = [
        ("工程名称", meta.get("project") or "—", "建设单位", meta.get("owner") or "—"),
        ("勘察单位", meta.get("unit") or "—", "勘察等级", state.get("grade") or "甲级"),
        ("钻孔数量", "%d 个" % len(holes), "总进尺", "%.2f m" % total_depth),
        ("最深孔深", "%.2f m" % max_depth, "计价类别", "%s（%s）" % (mode_cn, "依据实测工作量" if mode == "settle" else "依据设计工作量")),
    ]
    t = _table(doc, 4, widths=[3.0, 5.4, 3.0, 4.6])
    for a, b, c, d in info:
        cells = t.add_row().cells
        _cell(cells[0], a, size=10, bold=True, mode="center")
        _shade(cells[0], SUB_FILL)
        _cell(cells[1], b, size=10)
        _cell(cells[2], c, size=10, bold=True, mode="center")
        _shade(cells[2], SUB_FILL)
        _cell(cells[3], d, size=10)
        _apply_widths(t.rows[-1], t._kc_widths)
    # 删掉首行空行
    t._tbl.remove(t.rows[0]._tr)

    # ---------------- 二、计价依据 ----------------
    _h(doc, "二、计价依据")
    rate = 0
    if sections and sections[0].get("techRate") is not None:
        rate = sections[0]["techRate"]
    _p(doc, "1. 国家计委、建设部《工程勘察设计收费标准》（2002 年修订本），计价格〔2002〕10 号。")
    _p(doc, "2. 收费基准价 = 实物工作收费 + 技术工作收费；实物工作收费 = 收费基价 × 工作量 × 附加调整系数。")
    _p(doc, "3. 附加调整系数按总则 1.0.8 采用「系数相加－系数个数＋1」合成，不连乘。")
    _p(doc, "4. 技术工作费比例：岩土工程勘察 %d%%（%s）；工程物探 22%%；室内试验 10%%；工程测量 22%%。"
       % (round(rate * 100), state.get("grade") or "甲级"))
    att = state.get("techAttach") or {}
    lab_m = (att.get("lab") or "survey") != "standalone"
    wave_m = (att.get("wave") or "survey") != "standalone"
    _p(doc, "5. 技术工作收费的计算口径（《使用手册》第 3 章、8.1 解释）：岩土工程勘察技术工作收费 ="
            "（工程地质测绘＋勘探＋取样＋原位测试＋勘探点定位测量＋钻孔波速测试＋室内试验）实物工作收费"
            "×岩土工程勘察技术工作费收费比例。各分部仍按本专业独立统计、独立列示，小计相加后计入基准价。")
    if lab_m or wave_m:
        parts = []
        if lab_m:
            parts.append("室内试验")
        if wave_m:
            parts.append("钻孔波速测试")
        _p(doc, "   本工程%s与勘察一并完成，未单独提交独立成篇报告，其技术工作费按勘察技术工作费比例 %d%% "
                "计取，但仍在各自分部内单独统计（不并入岩土工程勘察分部）；工程物探中的电法等其他物探仍按 22%% 计取。"
           % ("、".join(parts), round(rate * 100)))
    else:
        _p(doc, "   本工程室内试验、钻孔波速均按独立委托处理，分别按 10%%、22%% 单独计取技术工作费。")

    _c4 = {s.get("key"): s for s in sections}.get("other") or {}
    _c4_attach = bool(_c4.get("coordAttach", True))
    _p(doc, "6. 勘探点定位测量（总则 1.0.13 工程测量 1000 元/组日）列入「其他费用」分部单独统计，"
            "其技术工作费%s；该分部小计与其他分部一样计入基准价。"
       % ("默认按岩土工程勘察技术工作费比例 %d%% 计取" % round(rate * 100) if _c4_attach
          else "按工程测量 22% 单独计取"))

    _c5 = {s.get("key"): s for s in sections}.get("survey") or {}
    if float(_c5.get("real") or 0) > 0:
        _p(doc, "7. 工程测量按《标准》第二章计取：实物工作收费 = 收费基价 × 工作量 × 附加调整系数，"
                "复杂程度分简单／中等／复杂三档（表2.2-1、2.3-1、2.4-1、2.5-1）；"
                "技术工作费收费比例 %d%%（2.1），单列为「工程测量」分部并计入基准价。"
           % round(float(_c5.get("techRate") or 0.22) * 100))

    # ---------------- 三、勘察工作量统计 ----------------
    _h(doc, "三、勘察工作量统计")
    # 最后一层层底可为空（默认无穷，延伸至孔底），因此不能简单按 bottom>0 过滤
    raw_layers = list(state.get("layers") or [])
    layers = [L for L in raw_layers if float(L.get("bottom") or 0) > 0]
    if raw_layers and float(raw_layers[-1].get("bottom") or 0) <= 0 and (raw_layers[-1].get("name") or "").strip() \
            and raw_layers[-1] not in layers:
        layers = layers + [raw_layers[-1]]
    layers.sort(key=lambda L: float(L.get("bottom") or 0) or (max_depth + 1e6))
    spt_n = sum(float(x.get("count") or 0) for x in (state.get("spt") or []))
    dpt_m = sum(float(x.get("meters") or 0) for x in (state.get("dpt") or []))
    sm = state.get("sample") or {}
    und = sm.get("undist") or {}
    sample_n = float(und.get("count") or 0) + sum(float(sm.get(k) or 0) for k in ("disturb", "core", "coreSat", "point", "swell", "salt", "water"))
    lab_n = sum(float(i.get("qty") or 0) for i in ((state.get("lab") or {}).get("items") or []))
    geo = state.get("geo") or {}
    wv = geo.get("wave") or {}
    if (state.get("qtyMode") or "") == "lz":
        wave_h = len([x for x in (wv.get("holeNos") or []) if x])
    else:
        wave_h = int(float(wv.get("holes") or 0))
    elec_p = sum(float(e.get("qty") or 0) for e in (geo.get("elec") or []))
    oth = state.get("other") or {}
    sv = state.get("survey") or {}
    sv_n = len([x for x in (sv.get("items") or []) if float(x.get("qty") or 0) > 0])
    ot = state.get("otherTest") or []
    cpt_m = sum(float(x.get("qty") or 0) for x in ot if (x.get("kind") or "") == "cpt")
    pack_n = sum(float(x.get("qty") or 0) for x in ot if (x.get("kind") or "") == "packer")

    t = _table(doc, 4, widths=[4.2, 4.0, 4.2, 3.6])
    _head_row(t, ["项目", "数量", "项目", "数量"])
    rows = [
        ("标准地层层数", "%d 层" % len(layers), "钻孔数量", "%d 个" % len(holes)),
        ("总进尺", "%.2f m" % total_depth, "最深孔深", "%.2f m" % max_depth),
        ("标准贯入试验", "%g 次" % spt_n, "圆锥动力触探", "%g m" % dpt_m),
        ("取样", "%g 件" % sample_n, "室内试验", "%g 件" % lab_n),
        ("波速测试", "%d 孔" % wave_h, "电法勘探", "%g 点" % elec_p),
        ("静力触探", "%g m" % cpt_m, "压水/注水试验", "%g 段次" % pack_n),
        ("探井/探槽/平硐", "%d 项" % len(state.get("extraDig") or []),
         "其他费用项", "%d 项" % (len([k for k in oth if float(oth.get(k) or 0) > 0 and not k.endswith("_price")
                                      and k != "survey"])
                                 + len(oth.get("custom") or [])
                                 + (1 if float(oth.get("survey") or (state.get("coord") or {}).get("days") or 0) > 0 else 0))),
        ("工程测量项目", "%d 项" % sv_n, "工程测量技术费比例", "22%"),
    ]
    for r in rows:
        _add(t, list(r))

    # 标准地层：层号按报告惯例显示为圈码（①、①1、⑥1）
    named = [L for L in layers if (L.get("name") or "").strip()]
    if named:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(3)
        _font(p.add_run("标准地层一览"), size=10.5, bold=True)
        t = _table(doc, 6, widths=[2.0, 4.6, 2.0, 2.8, 2.4, 2.6])
        _head_row(t, ["层号", "岩土名称", "岩土类别", "层底深度(m)", "层厚(m)", "分层记录"],
                  aligns=["center", "left", "center", "right", "right", "right"])
        prev = 0.0
        for L in named:
            bot = float(L.get("bottom") or 0)
            unbounded = bot <= 0
            if unbounded:                       # 最后一层默认无穷：延伸至孔底
                bot = max_depth
            th = bot - prev if bot > prev else 0.0
            prev = bot if bot > prev else prev
            _add(t, [LB.layer_no(L.get("code"), L.get("sub")), L.get("name") or "",
                     ["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ", "Ⅵ"][min(5, max(0, int(float(L.get("cls") or 1)) - 1))],
                     "至孔底" if unbounded else ("%.2f" % bot), "%.2f" % th,
                     ("%d 条" % int(L.get("count"))) if L.get("count") else "—"],
                 aligns=["center", "left", "center", "right", "right", "right"], size=9.5)

    # ---------------- 四、费用计算明细 ----------------
    # 各分部明细合并为一张 A4 连续表：分部标题作为表内通栏行，避免拆成多张表
    _h(doc, "四、费用计算明细")
    AL = ["left", "left", "center", "right", "right", "center", "right"]
    sn = 0
    t = None
    for s in sections:
        lines = []
        for g in s.get("groups") or []:
            lines += g.get("lines") or []
        if not lines:
            continue
        sn += 1
        if t is None:
            t = _table(doc, 7, widths=[4.0, 4.0, 1.0, 1.6, 1.7, 1.4, 2.3])
            _head_row(t, ["项目", "规格 / 说明", "单位", "单价(元)", "工程量", "系数", "合计(元)"],
                      aligns=AL)
        # 分部标题行：通栏合并、浅底加粗
        title = (s.get("title") or "").lstrip("一二三四五六七八九十、")
        hrow = t.add_row()
        hcell = hrow.cells[0].merge(hrow.cells[-1])
        _cell(hcell, "%d. %s" % (sn, title), size=10.5, bold=True)
        _shade(hcell, SUB_FILL)

        for l in lines:
            name = l.get("item", "")
            if l.get("sub"):
                name += "（%s）" % l["sub"]
            _add(t, [name, l.get("spec", ""), l.get("unit", ""),
                     _money(l.get("price")), "{:,.2f}".format(float(l.get("qty") or 0)),
                     "%.2f" % float(l.get("coef") or 1), _money(l.get("total"))],
                 aligns=AL, size=9.5)

        # 各分部独立统计：实物工作费、技术工作费、分部小计依次列出，最后统一相加
        _add(t, ["实物工作费合计", "", "", "", "", "", _money(s.get("real"))],
             aligns=AL, bold=True, fill=SUB_FILL, size=9.5)
        tech_spec = ""
        if s.get("key") == "other" and float(s.get("coordReal") or 0) > 0:
            tech_spec = "仅勘探点定位测量计取；台班、验槽、报告费不计技术费"
        rparts = s.get("rateParts") or []
        if len(rparts) > 1:
            # 工程物探：波速按勘察比例、电法等按 22%，分项列出
            for part in rparts:
                _add(t, ["其中%s技术工作费" % part.get("name", ""),
                         part.get("label", ""), "", "", "", "",
                         _money(part.get("tech"))], aligns=AL, size=9.5)
            _add(t, ["技术工作费合计", "", "", "", "", "", _money(s.get("tech"))],
                 aligns=AL, bold=True, fill=SUB_FILL, size=9.5)
        else:
            tech_label = s.get("techLabel") or ("技术工作费（%d%%）" % round(float(s.get("techRate") or 0) * 100))
            _add(t, [tech_label, tech_spec, "", "", "", "",
                     _money(s.get("tech"))],
                 aligns=AL, bold=True, fill=SUB_FILL, size=9.5)
        _add(t, ["分部小计", "实物工作费＋技术工作费，计入基准价", "", "", "", "", _money(s.get("amount"))],
             aligns=AL, bold=True, fill=TOTAL_FILL, size=9.5)


    # 附加调整系数说明
    coefs = []
    try:
        from . import standards as ST
        book = {c["id"]: c for c in list(ST.COEF_SOIL) + list(ST.COEF_GLOBAL) + list(ST.COEF_GEO) + list(ST.SURVEY_COEF)}
        for key, label in (("coefSoil", "岩土工程勘察"), ("coefGlobal", "通用"), ("coefGeo", "工程物探")):
            sel = [book[i] for i in (state.get(key) or []) if i in book]
            if sel:
                coefs.append("%s：%s" % (label, "、".join("%s ×%.2f" % (c["name"], c["v"]) for c in sel)))
        ssel = [book[i] for i in ((state.get("survey") or {}).get("coefs") or []) if i in book]
        if ssel:
            coefs.append("工程测量（表2.2-3）：%s" % "、".join("%s ×%.2f" % (c["name"], c["v"]) for c in ssel))
    except Exception:
        pass
    _h(doc, "五、附加调整系数", size=12)
    _p(doc, "；".join(coefs) if coefs else "本工程未选用附加调整系数（综合系数 1.00）。")

    # ---------------- 六、费用统计表 ----------------
    _h(doc, "六、费用统计表")
    t = _table(doc, 5, widths=[1.3, 5.4, 3.1, 3.1, 3.1])
    _head_row(t, ["序号", "分部工程", "实物工作费(元)", "技术工作费(元)", "小计(元)"],
              aligns=["center", "left", "right", "right", "right"])
    shown = [s for s in sections
             if any(g.get("lines") for g in (s.get("groups") or [])) or float(s.get("amount") or 0) > 0.005]
    for i, s in enumerate(shown):
        nm = (s.get("title") or "").lstrip("一二三四五六七八九十、")
        _add(t, [str(i + 1), nm,
                 _money(s.get("real")),
                 _money(s.get("tech")),
                 _money(s.get("amount"))],
             aligns=["center", "left", "right", "right", "right"])
    _add(t, ["", "勘察费基准价合计", _money(sum(float(s.get("real") or 0) for s in sections)),
             _money(sum(float(s.get("tech") or 0) for s in sections)), _money(totals.get("base"))],
         aligns=["center", "left", "right", "right", "right"], bold=True, fill=SUB_FILL)

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(2)
    _font(p.add_run("注：五个分部各自独立统计实物工作费与技术工作费，小计相加即为基准价；"
                    "室内试验、钻孔波速、勘探点定位测量与勘察一并完成时，技术工作费按岩土工程勘察比例计取，"
                    "但仍在本分部内计算，不并入勘察分部。工程测量按第二章技术工作费 22% 单独计取。"), size=9, color="5C6B7C")


    extra = []
    if float(totals.get("discountPct") or 0) != 0:
        extra.append(("", "下浮优惠 %.0f%%" % float(totals["discountPct"]), "", "", ""))
    for e in extra:
        _add(t, list(e), aligns=["center", "left", "right", "right", "right"])

    _add(t, ["", "勘察费%s合计（合同价）" % mode_cn, "", "", _money(totals.get("final"))],
         aligns=["center", "left", "right", "right", "right"], bold=True, fill=TOTAL_FILL)

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    _font(p.add_run("勘察费%s合计：人民币 %s 元（大写：%s）"
                    % (mode_cn, _money(totals.get("final")), _rmb(totals.get("final")))), size=10.5, bold=True)

    _depth = float(totals.get("depth") or total_depth or 0)
    if _depth > 0:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(2)
        _font(p.add_run("折合综合单价：%s 元/m（合同价 ÷ 总进尺 %s m）"
                        % (_money(totals.get("unitPrice")), "{:,.2f}".format(_depth))), size=10.5)

    # ---------------- 七、编制说明 ----------------
    _h(doc, "七、编制说明")
    notes = [
        "1. 本报告工作量依据%s确定。" % ("勘察成果资料的实测数据" if mode == "settle" else "勘察纲要及设计钻孔布置"),
        "2. 钻孔按岩土类别与深度档分别计价，同层跨深度档时自动拆分；深度大于 100m 每增 20m 按前一档基价乘 1.2。",
        "3. 标准贯入试验不适用于Ⅳ~Ⅵ类土；静力触探按表3.3-4 单桥基价与触探深度分档，双桥探头乘 1.15、加测孔压乘 1.2；"
        "压水、注水试验按段次计（压水按试验深度分 D≤20 / D>20 两档）；钻孔波速测试按每孔测试深度所在档位计取"
        "（未填写时按本项目最深孔），不足 2 个组日按 2 个组日计。",
        "4. 本报告不含勘察成果审查费、施工配合费及税金，如需税前列支请另行计取。",
        "5. 勘探点定位测量按 1000 元/组日计入「其他费用」分部，技术工作费默认按岩土工程勘察比例计取；独立委托时按工程测量 22%。",
        "6. 标准地层最后一层层底不填时按无穷处理（延伸至孔底），钻孔分层按各孔孔深自动截取。",
        "7. 工程测量按第二章计取：控制测量按点／km、地形测量按 km²、水域与河道断面按 km²／km、"
        "地下管线与洞室按 km、其他测量按标准图幅／100cm²／组日；建筑群区地形测量在一般地区基价上乘 1.8（1:200）或 2.0（其余比例尺），"
        "滨海区水域乘 1.5；小型工程测量不足 3 个组日按 3 个组日计。",
        "8. 附加调整系数按表2.2-3 逐条匹配到对应测量项目，同一项目上叠加多条时按总则 1.0.8"
        "「系数相加－系数个数＋1」合成、不连乘；地形图修测的工程量按实际修测面积计，"
        "汇水面积测量的基价取地形测量基价乘 0.4。",
    ]
    for w in result.get("warnings") or []:
        notes.append("※ 本次计算提示：%s" % w)
    for n in notes:
        _p(doc, n)

    doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _font(p.add_run("编制单位（盖章）：%s" % (meta.get("unit") or "　　　　　　　")), size=10.5)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _font(p.add_run("日期：%s" % today), size=10.5)

    doc.save(path)
    return path


# ---------------------------------------------------------------------------
def _rmb(v):
    """金额转大写人民币（支持亿/万分组）"""
    try:
        v = round(float(v or 0), 2)
    except (TypeError, ValueError):
        return "—"
    D = "零壹贰叁肆伍陆柒捌玖"
    U = ["", "拾", "佰", "仟"]

    def group(n):
        """0<n<=9999 -> 中文（不含前导零）"""
        out, zero = "", False
        for i in range(3, -1, -1):
            d = (n // (10 ** i)) % 10
            if d == 0:
                if out:
                    zero = True
            else:
                if zero:
                    out += "零"
                    zero = False
                out += D[d] + U[i]
        return out

    neg = v < 0
    cents = int(round(abs(v) * 100))
    yuan = cents // 100
    jiao = (cents // 10) % 10
    fen = cents % 10

    if yuan == 0:
        s = "零元"
    else:
        yi, wan, ge = yuan // 100000000, (yuan // 10000) % 10000, yuan % 10000
        s = ""
        if yi:
            s += group(yi) + "亿"
        if wan:
            if s and wan < 1000:
                s += "零"
            s += group(wan) + "万"
        elif s and ge:
            s += "零"
        if ge:
            if s and ge < 1000 and not s.endswith("零"):
                s += "零"
            s += group(ge)
        s += "元"

    if jiao == 0 and fen == 0:
        s += "整"
    else:
        if jiao:
            s += D[jiao] + "角"
        elif fen:
            s += "零"
        if fen:
            s += D[fen] + "分"
    return ("负" if neg else "") + s
