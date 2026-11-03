# -*- coding: utf-8 -*-
"""
导出 Excel：费用计算书 + 工作量清单 + 分层明细
"""
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import engine as E
from .version import VERSION_TAG

THIN = Side(style="thin", color="9AA5B1")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEAD_FILL = PatternFill("solid", fgColor="DCE6F1")
SUB_FILL = PatternFill("solid", fgColor="F2F6FA")
TOTAL_FILL = PatternFill("solid", fgColor="FFF2CC")


def _style_header(ws, row, ncol):
    for c in range(1, ncol + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = Font(bold=True, size=10)
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER


def _cell(ws, r, c, v, fmt=None, bold=False, align="left", fill=None):
    cell = ws.cell(row=r, column=c, value=v)
    cell.border = BORDER
    cell.font = Font(bold=bold, size=10)
    cell.alignment = Alignment(horizontal=align, vertical="center", wrap_text=True)
    if fmt:
        cell.number_format = fmt
    if fill:
        cell.fill = fill
    return cell


def export(state, result, path):
    wb = Workbook()
    ws = wb.active
    ws.title = "费用计算书"

    meta = state.get("meta") or {}
    ws.merge_cells("A1:L1")
    ws["A1"] = "工程勘察费用计算书"
    ws["A1"].font = Font(bold=True, size=16)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    info = [
        ("工程名称：", meta.get("project", "")),
        ("建设单位：", meta.get("owner", "")),
        ("勘察单位：", meta.get("unit", "")),
        ("勘察等级：", state.get("grade", "甲级")),
        ("软件版本：", VERSION_TAG),
    ]
    r = 2
    for label, val in info:
        ws.cell(row=r, column=1, value=label).font = Font(size=10)
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=8)
        ws.cell(row=r, column=2, value=val).font = Font(size=10)
        r += 1

    hdr = ["序号", "勘察测试内容", "规格 / 深度", "计费单位", "单价(元)", "工程量", "小计(元)", "附加系数", "合计(元)"]
    r += 1
    head_row = r
    for i, h in enumerate(hdr, 1):
        ws.cell(row=r, column=i, value=h)
    _style_header(ws, r, len(hdr))
    r += 1

    no = 0
    for sec in result["sections"]:
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=9)
        c = ws.cell(row=r, column=1, value=sec["title"])
        c.font = Font(bold=True, size=11)
        c.fill = SUB_FILL
        c.border = BORDER
        r += 1
        for g in sec["groups"]:
            ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=9)
            c = ws.cell(row=r, column=2, value="  " + g["title"])
            c.font = Font(bold=True, size=10)
            c.border = BORDER
            r += 1
            for L in g["lines"]:
                no += 1
                _cell(ws, r, 1, no, align="center")
                _cell(ws, r, 2, L["item"] + (("·" + L["sub"]) if L.get("sub") else ""))
                _cell(ws, r, 3, L.get("spec", ""))
                _cell(ws, r, 4, L.get("unit", ""), align="center")
                _cell(ws, r, 5, L["price"], "#,##0.00", align="right")
                _cell(ws, r, 6, L["qty"], "#,##0.00", align="right")
                _cell(ws, r, 7, L["amount"], "#,##0.00", align="right")
                _cell(ws, r, 8, L.get("coef", 1), "0.00", align="center")
                _cell(ws, r, 9, L["total"], "#,##0.00", align="right", bold=True)
                r += 1
        # 小结
        labels = [("实物工作费", sec.get("real", 0))]
        if sec.get("techRate"):
            labels.append(("技术工作费（×%.2f）" % sec["techRate"], sec.get("tech", 0)))
        labels.append(("小计", sec.get("amount", 0)))
        for nm, val in labels:
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)
            _cell(ws, r, 1, nm, bold=True, align="right")
            _cell(ws, r, 9, val, "#,##0.00", bold=True, align="right", fill=TOTAL_FILL)
            r += 1

    t = result["totals"]
    r += 1
    rows = [("勘察费基准价（一+二+三+四）", t["base"])]
    if t["coord"]:
        rows.append(("主体勘察协调费（5%）", t["coord"]))
    rows.append(("浮动幅度 %+.0f%%" % t["floatPct"], t["afterFloat"]))
    if t["discountPct"]:
        rows.append(("下浮 %.0f%%" % t["discountPct"], t["final"]))
    for nm, val in rows:
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)
        _cell(ws, r, 1, nm, bold=True, align="right")
        _cell(ws, r, 9, val, "#,##0.00", bold=True, align="right")
        r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)
    _cell(ws, r, 1, "按合同计算总费用（元）", bold=True, align="right", fill=TOTAL_FILL)
    _cell(ws, r, 9, t["final"], "#,##0.00", bold=True, align="right", fill=TOTAL_FILL)
    r += 2
    ws.cell(row=r, column=1,
            value="注：本工程按国家计委、建设部《工程勘察设计收费标准》（2002年修订本）中有关规定计费。").font = Font(size=9, italic=True)

    for i, w in enumerate([6, 30, 26, 9, 12, 12, 14, 9, 14], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row=head_row + 1, column=1)

    # ---------------- 工作量清单 ----------------
    ws2 = wb.create_sheet("工作量清单")
    holes = result.get("holes") or []
    ws2.merge_cells("A1:K1")
    ws2["A1"] = "岩土工程勘察工作量清单"
    ws2["A1"].font = Font(bold=True, size=14)
    ws2["A1"].alignment = Alignment(horizontal="center")
    ws2.cell(row=2, column=1, value="工程名称：%s" % meta.get("project", "")).font = Font(size=10)

    # 汇总各类别/深度档工程量
    agg, _ = E.drill_work(holes)
    keys = sorted(agg.keys(), key=lambda k: (k[1], k[0]))
    cols = ["孔号", "孔类型", "孔深(m)"] + ["%s类 %s" % (["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ", "Ⅵ"][c - 1], E.bracket_label(pd)) for c, pd in keys] + ["合计(m)"]
    hr = 4
    for i, h in enumerate(cols, 1):
        ws2.cell(row=hr, column=i, value=h)
    _style_header(ws2, hr, len(cols))

    r = hr + 1
    for h in holes:
        _cell(ws2, r, 1, h["no"], align="center")
        _cell(ws2, r, 2, h["type"], align="center")
        _cell(ws2, r, 3, h["depth"], "#,##0.00", align="right")
        tot = 0.0
        for j, (c, pd) in enumerate(keys):
            m = 0.0
            for sg in h["segs"]:
                if sg["cls"] != c:
                    continue
                for s, e, up in E.split_span(sg["top"], sg["bot"], E.cuts_for([0, 10, 20, 30, 40, 50, 60, 80, 100], 100, 20, max(h["depth"], 100) + 40)):
                    if abs(up - pd) < 1e-9:
                        m += e - s
            tot += m
            _cell(ws2, r, 4 + j, round(m, 2) if m else None, "#,##0.00", align="right")
        _cell(ws2, r, 4 + len(keys), round(tot, 2), "#,##0.00", align="right", bold=True)
        r += 1

    # 汇总行
    _cell(ws2, r, 1, "总计", align="center", bold=True, fill=TOTAL_FILL)
    _cell(ws2, r, 2, "", fill=TOTAL_FILL)
    _cell(ws2, r, 3, round(sum(h["depth"] for h in holes), 2), "#,##0.00", align="right", bold=True, fill=TOTAL_FILL)
    for j, (c, pd) in enumerate(keys):
        _cell(ws2, r, 4 + j, round(agg.get((c, pd), 0), 2), "#,##0.00", align="right", bold=True, fill=TOTAL_FILL)
    _cell(ws2, r, 4 + len(keys), round(sum(agg.values()), 2), "#,##0.00", align="right", bold=True, fill=TOTAL_FILL)

    ws2.column_dimensions["A"].width = 12
    ws2.column_dimensions["B"].width = 10
    ws2.column_dimensions["C"].width = 10
    for i in range(4, 4 + len(keys) + 1):
        ws2.column_dimensions[get_column_letter(i)].width = 13

    # ---------------- 分层明细 ----------------
    ws3 = wb.create_sheet("分层明细")
    h3 = ["孔号", "孔深(m)", "层序号", "岩土名称", "岩土类别", "层顶(m)", "层底(m)", "层厚(m)"]
    for i, h in enumerate(h3, 1):
        ws3.cell(row=1, column=i, value=h)
    _style_header(ws3, 1, len(h3))
    r = 2
    for h in holes:
        for sg in h["segs"]:
            _cell(ws3, r, 1, h["no"], align="center")
            _cell(ws3, r, 2, h["depth"], "#,##0.00", align="right")
            _cell(ws3, r, 3, sg["code"], align="center")
            _cell(ws3, r, 4, sg["name"])
            _cell(ws3, r, 5, ["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ", "Ⅵ"][sg["cls"] - 1], align="center")
            _cell(ws3, r, 6, round(sg["top"], 2), "#,##0.00", align="right")
            _cell(ws3, r, 7, round(sg["bot"], 2), "#,##0.00", align="right")
            _cell(ws3, r, 8, round(sg["bot"] - sg["top"], 2), "#,##0.00", align="right")
            r += 1
    for i, w in enumerate([12, 10, 8, 22, 10, 10, 10, 10], 1):
        ws3.column_dimensions[get_column_letter(i)].width = w

    wb.save(path)
    return path
