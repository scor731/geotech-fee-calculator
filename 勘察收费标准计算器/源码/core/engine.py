# -*- coding: utf-8 -*-
"""
计算引擎：把「标准地层 + 钻孔 + 试验/物探/其他」的工作量，按 2002 收费标准换算成费用。
所有金额单位：元；长度单位：m。
"""
from . import standards as S


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def num(v, default=0.0):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def combine_coef(values):
    """附加调整系数合成规则（总则1.0.8）：不能连乘。
    系数相加，减去系数个数，加上定值1。  即 1 + Σ(v-1)"""
    vals = [v for v in values if v and abs(v - 1) > 1e-9]
    if not vals:
        return 1.0
    return round(1 + sum(v - 1 for v in vals), 4)


def cuts_for(base, tail_start, tail_step, maxd):
    c = list(base)
    while c[-1] < maxd:
        c.append(c[-1] + tail_step)
    return c


def split_span(a, b, cuts):
    """把区间 (a,b] 按 cuts 切分，返回 [(s,e,price_depth)]"""
    out = []
    for i in range(len(cuts) - 1):
        s = max(a, cuts[i])
        e = min(b, cuts[i + 1])
        if e - s > 1e-9:
            out.append((s, e, cuts[i + 1]))
    if b > cuts[-1] + 1e-9:
        out.append((max(a, cuts[-1]), b, b))
    return out


# ---------------------------------------------------------------------------
# 钻孔：由标准地层 + 孔型 生成，或直接使用导入的实测分层
# ---------------------------------------------------------------------------
def wave_band(depth, table_id="wave"):
    """波速测试深度分档：返回 (档位说明, 单价倍数)。用于界面显示"费用落在哪一档"。"""
    import math
    t = S.TABLES[table_id]
    for r in t["rows"]:
        rng = r.get("rng")
        if rng and rng[0] < depth <= rng[1]:
            return r["label"], 1.0
    tail = t.get("tail")
    if tail:
        n = max(1, math.ceil((depth - tail["start"]) / tail["step"]))
        lo = tail["start"] + (n - 1) * tail["step"]
        hi = tail["start"] + n * tail["step"]
        return "%g<D≤%gm（×%.2f）" % (lo, hi, tail["factor"] ** n), tail["factor"] ** n
    return "", 1.0


def build_holes(state):
    """返回 [{no, type, depth, segs:[{code,name,cls,top,bot}]}]
    qtyMode: manual 用「标准地层 + 孔型」推算；lz（或老项目未标记但有实测孔）直接用导入的实测分层。"""
    holes = state.get("holes") or []
    qm = state.get("qtyMode") or ("lz" if holes else "manual")
    if qm != "lz":
        holes = []
    if holes:
        out = []
        for h in holes:
            segs = []
            top = 0.0
            for L in h.get("layers", []):
                bot = num(L.get("bottom"))
                if bot <= top:
                    continue
                segs.append({
                    "code": L.get("code", ""), "name": L.get("name", ""),
                    "cls": int(num(L.get("cls"), 1)), "top": top, "bot": bot,
                })
                top = bot
            out.append({"no": h.get("no", ""), "type": h.get("type", "钻孔"),
                        "depth": num(h.get("depth"), top), "segs": segs})
        return out

    layers = [L for L in (state.get("layers") or []) if num(L.get("bottom")) > 0]
    layers.sort(key=lambda x: num(x.get("bottom")))
    out = []
    for ht in state.get("holeTypes") or []:
        cnt = int(num(ht.get("count"), 0))
        depth = num(ht.get("depth"))
        if cnt <= 0 or depth <= 0:
            continue
        for i in range(cnt):
            segs = []
            top = 0.0
            for L in layers:
                bot = num(L.get("bottom"))
                if bot <= top:
                    continue
                e = min(bot, depth)
                if e - top > 1e-9:
                    segs.append({"code": L.get("code", ""), "name": L.get("name", ""),
                                 "cls": int(num(L.get("cls"), 1)), "top": top, "bot": e})
                top = bot
                if top >= depth - 1e-9:
                    break
            no = "%s-%d" % (ht.get("name", "孔"), i + 1)
            out.append({"no": no, "type": ht.get("name", "钻孔"), "depth": depth, "segs": segs})
    return out


def drill_work(holes):
    """统计钻孔工程量：{(cls, bracketUpper): meters}"""
    if not holes:
        return {}, []
    maxd = max([h["depth"] for h in holes] or [0])
    cuts = cuts_for([0, 10, 20, 30, 40, 50, 60, 80, 100], 100, 20, maxd + 40)
    agg = {}
    for h in holes:
        for sg in h["segs"]:
            for s, e, pd in split_span(sg["top"], sg["bot"], cuts):
                k = (sg["cls"], pd)
                agg[k] = agg.get(k, 0.0) + (e - s)
    return agg, cuts


def bracket_label(pd):
    """由分档上界给出标签"""
    edges = [(0, 10), (10, 20), (20, 30), (30, 40), (40, 50), (50, 60), (60, 80), (80, 100)]
    for a, b in edges:
        if abs(pd - b) < 1e-9:
            return "D≤%d" % b if a == 0 else "%d<D≤%d" % (a, b)
    # 超出100m
    import math
    n = max(1, math.ceil((pd - 100) / 20))
    lo = 100 + (n - 1) * 20
    return "%d<D≤%d" % (lo, pd)


# ---------------------------------------------------------------------------
# 主计算
# ---------------------------------------------------------------------------
def compute(state):
    cls_list = [c["name"] for c in S.SOIL_CLASSES]
    res = {"sections": [], "holes": [], "warnings": []}

    # ---------- 系数 ----------
    all_coefs = {c["id"]: c for c in S.COEF_SOIL}
    all_coefs.update({c["id"]: c for c in S.COEF_GLOBAL})
    sel = [all_coefs[i]["v"] for i in (state.get("coefSoil") or []) if i in all_coefs]
    sel += [all_coefs[i]["v"] for i in (state.get("coefGlobal") or []) if i in all_coefs]
    k_soil = combine_coef(sel)

    geo_coefs = {c["id"]: c for c in S.COEF_GEO}
    gsel = [geo_coefs[i]["v"] for i in (state.get("coefGeo") or []) if i in geo_coefs]
    k_geo = combine_coef(gsel)

    holes = build_holes(state)
    res["holes"] = holes

    # ================= 1 岩土工程勘察 =================
    sec1 = {"key": "soil", "title": "一、岩土工程勘察", "groups": [], "amount": 0.0}
    detail = []   # 明细行

    # 1.1 钻孔
    agg, _ = drill_work(holes)
    lines = []
    for (cls, pd), m in sorted(agg.items(), key=lambda x: (x[0][1], x[0][0])):
        if m <= 1e-9:
            continue
        p = S.price_at("drill", pd, cls - 1)
        if p is None:
            continue
        lines.append({
            "item": "钻孔", "sub": cls_list[cls - 1], "spec": bracket_label(pd),
            "unit": "m", "price": round(p, 2), "qty": round(m, 2),
            "amount": round(p * m, 2), "coef": k_soil,
            "total": round(p * m * k_soil, 2),
        })
    g1 = {"key": "drill", "title": "钻孔", "lines": lines}
    sec1["groups"].append(g1)
    detail += lines

    # 1.2 探井 / 探槽 / 平硐
    for kind, tbl, unit in (("探井", "pit", "m"), ("探槽", "trench", "m³"), ("平硐", "adit", "m")):
        lines = []
        for it in state.get("extraDig") or []:
            if it.get("kind") != kind:
                continue
            qty = num(it.get("qty"))
            if qty <= 0:
                continue
            cls = int(num(it.get("cls"), 1))
            try:
                price = S.row_price(tbl, int(num(it.get("row"), 0)), cls - 1)
            except Exception:
                price = None
            if price is None:
                continue
            lines.append({
                "item": kind, "sub": cls_list[cls - 1], "spec": it.get("label", ""),
                "unit": unit, "price": price, "qty": round(qty, 2),
                "amount": round(price * qty, 2), "coef": k_soil,
                "total": round(price * qty * k_soil, 2),
            })
        if lines:
            sec1["groups"].append({"key": tbl, "title": kind, "lines": lines})
            detail += lines

    # 1.3 取样
    sm = state.get("sample") or {}
    lines = []
    # 原状/扰动取土：按取土器
    und = sm.get("undist") or {}
    cnt = num(und.get("count"))
    if cnt > 0:
        dev = und.get("device", "hammer")
        band = int(num(und.get("band"), 0))
        price = S.row_price("sample", dev, min(band, 1)) or 0
        label = next((r["label"] for r in S.TABLES["sample"]["rows"] if r["key"] == dev), dev)
        lines.append({"item": "取原状土样", "sub": label, "spec": "取样深度≤30m" if band == 0 else "取样深度>30m",
                      "unit": "件", "price": price, "qty": cnt, "amount": round(price * cnt, 2),
                      "coef": k_soil, "total": round(price * cnt * k_soil, 2)})
    for key, label, tid, unit in (("disturb", "扰动取土", "disturb", "件"),
                                  ("core", "取岩芯样", "core", "件"),
                                  ("point", "取点荷载岩样", "point", "块"),
                                  ("water", "取水", "water", "件")):
        c = num(sm.get(key))
        if c > 0:
            price = S.row_price("sample_extra", tid, 0) or 0
            lines.append({"item": label, "sub": "", "spec": "", "unit": unit, "price": price,
                          "qty": c, "amount": round(price * c, 2), "coef": k_soil,
                          "total": round(price * c * k_soil, 2)})
    if lines:
        sec1["groups"].append({"key": "sample", "title": "取样", "lines": lines})
        detail += lines

    # 1.4 原位测试
    lines = []
    # 标准贯入
    spt_total = 0.0
    for it in state.get("spt") or []:
        c = num(it.get("count"))
        spt_total += c
        if c <= 0:
            continue
        cls = int(num(it.get("cls"), 1))
        band = int(num(it.get("band"), 0))
        if cls > 3:
            res["warnings"].append("标准贯入试验不适用于%s类土（%s），已按Ⅲ类计取，请核对。" % (cls_list[cls - 1], it.get("layerName", "")))
            cls = 3
        price = S.row_price("spt", band, cls - 1) or 0
        lab = ["D≤20", "20<D≤50", "D>50"][band]
        lines.append({"item": "标准贯入试验", "sub": cls_list[cls - 1],
                      "spec": "%s  %s" % (it.get("layerName", ""), lab), "unit": "次",
                      "price": price, "qty": c, "amount": round(price * c, 2),
                      "coef": k_soil, "total": round(price * c * k_soil, 2)})
    # 动力触探
    for it in state.get("dpt") or []:
        c = num(it.get("meters"))
        if c <= 0:
            continue
        cls = int(num(it.get("cls"), 1))
        band = int(num(it.get("band"), 0))
        kind = it.get("kind", "dpt_heavy")
        tid = {"dpt_light": "dpt_light", "dpt_heavy": "dpt_heavy", "dpt_super": "dpt_super"}.get(kind, "dpt_heavy")
        cols = S.TABLES[tid]["cols"]
        cname = cls_list[cls - 1]
        if cname not in cols:
            res["warnings"].append("%s类土与%s动力触探基价表不匹配（%s），已按最近档计取。"
                                   % (cname, {"dpt_light": "轻型", "dpt_heavy": "重型", "dpt_super": "超重型"}[tid], it.get("layerName", "")))
            ci = 0 if cols[0] == "Ⅰ" else 0
        else:
            ci = cols.index(cname)
        price = S.row_price(tid, band, ci) or 0
        lab = S.TABLES[tid]["rows"][band]["label"]
        nm = {"dpt_light": "轻型动力触探", "dpt_heavy": "重型动力触探", "dpt_super": "超重型动力触探"}[tid]
        lines.append({"item": nm, "sub": cname, "spec": "%s  %s" % (it.get("layerName", ""), lab),
                      "unit": "m", "price": price, "qty": c, "amount": round(price * c, 2),
                      "coef": k_soil, "total": round(price * c * k_soil, 2)})
    # 静力触探 / 十字板 / 压水 / 载荷
    for it in state.get("otherTest") or []:
        c = num(it.get("qty"))
        if c <= 0:
            continue
        kind = it.get("kind")
        mult = 1.0
        spec = ""
        if kind == "cpt":
            cls = int(num(it.get("cls"), 3))
            depth = num(it.get("depth"), 10)
            price = S.price_at("cpt", depth, min(cls, 3) - 1) or 0
            t = it.get("tip", "single")
            if t == "double":
                mult = 1.15
                spec = "双桥探头"
            if it.get("pore"):
                mult *= 1.2
                spec += " 加测孔压"
            nm, unit = "静力触探", "m"
            spec = (cls_list[cls - 1] + " " + spec).strip()
        elif kind == "vane":
            depth = num(it.get("depth"), 10)
            price = S.price_at("vane", depth, 0) or 0
            nm, unit, spec = "十字板剪切试验", "点", ""
        elif kind == "packer":
            sub = it.get("sub", "pack_le20")
            price = S.row_price("packer", sub, 0) or 0
            nm = "压水/注水试验"
            unit = "段次"
            spec = next((r["label"] for r in S.TABLES["packer"]["rows"] if r["key"] == sub), "")
        elif kind == "plate":
            key = int(num(it.get("sub"), 100))
            ci = 1 if it.get("below") else 0
            price = S.row_price("plate", key, ci) or 0
            nm, unit = "载荷试验", "点"
            spec = "%dkN %s" % (key, "水位以下" if ci else "水位以上")
        else:
            continue
        amt = price * mult * c
        lines.append({"item": nm, "sub": "", "spec": spec, "unit": unit,
                      "price": round(price * mult, 2), "qty": c, "amount": round(amt, 2),
                      "coef": k_soil, "total": round(amt * k_soil, 2)})
    if lines:
        sec1["groups"].append({"key": "insitu", "title": "原位测试", "lines": lines})
        detail += lines

    soil_real = sum(l["total"] for l in detail)

    # 原位测试数量校验：标贯次数不大于钻孔总数 1/3 时提示
    n_holes = len(holes)
    spt_min = n_holes / 3.0
    res["sptCheck"] = {"total": spt_total, "holes": n_holes, "min": round(spt_min, 2),
                       "short": bool(n_holes and 0 < spt_total <= spt_min)}
    if res["sptCheck"]["short"]:
        res["warnings"].append(
            "标准贯入共 %g 次，不大于钻孔总数 %d 个的 1/3（%.1f 次），原位测试可能不满足 1/3 总数要求。"
            % (spt_total, n_holes, spt_min))

    rate = S.TECH_RATE["岩土工程勘察"].get(state.get("grade", "甲级"), 1.0)
    tech1 = soil_real * rate
    sec1["real"] = round(soil_real, 2)
    sec1["tech"] = round(tech1, 2)
    sec1["techRate"] = rate
    sec1["amount"] = round(soil_real + tech1, 2)
    sec1["coef"] = k_soil
    res["sections"].append(sec1)

    # ================= 2 室内试验 =================
    sec2 = {"key": "lab", "title": "二、室内试验", "groups": [], "amount": 0.0}
    lines = []
    lab = state.get("lab") or {}
    for it in lab.get("items") or []:
        c = num(it.get("qty"))
        if c <= 0:
            continue
        price = num(it.get("price"))
        if price <= 0:
            continue
        lines.append({"item": it.get("name", ""), "sub": it.get("sub", ""), "spec": it.get("spec", ""),
                      "unit": it.get("unit", "件"), "price": price, "qty": c,
                      "amount": round(price * c, 2), "coef": 1.0, "total": round(price * c, 2)})
    if lines:
        sec2["groups"].append({"key": "lab", "title": "室内试验项目", "lines": lines})
    lab_real = sum(l["total"] for l in lines)
    lrate = S.TECH_RATE["室内试验"].get(state.get("grade", "甲级"), 0.1)
    sec2["real"] = round(lab_real, 2)
    sec2["tech"] = round(lab_real * lrate, 2)
    sec2["techRate"] = lrate
    sec2["amount"] = round(lab_real * (1 + lrate), 2)
    if state.get("labInSite"):
        sec2["note"] = "移至现场进行的室内试验，附加调整系数1.3（表8.5）"
        sec2["real"] = round(lab_real * 1.3, 2)
        sec2["tech"] = round(lab_real * 1.3 * lrate, 2)
        sec2["amount"] = round(lab_real * 1.3 * (1 + lrate), 2)
        for l in lines:
            l["coef"] = 1.3
            l["total"] = round(l["amount"] * 1.3, 2)
    res["sections"].append(sec2)

    # ================= 3 工程物探 =================
    sec3 = {"key": "geo", "title": "三、工程物探", "groups": [], "amount": 0.0}
    lines = []
    geo = state.get("geo") or {}
    wv = geo.get("wave") or {}
    # 孔深不由用户填写，统一取本项目最深孔
    wdepth = max([h["depth"] for h in holes] or [0]) or num(wv.get("depth"))
    qm = state.get("qtyMode") or ("lz" if (state.get("holes") or []) else "manual")
    method = 1 if wv.get("method") == "cross" else 0
    bands = []   # 分档统计，回给界面显示
    if qm == "lz":
        # 导入模式：勾选实际做过波速的钻孔，按各孔自身孔深分档计价
        sel = [str(x) for x in (wv.get("holeNos") or [])]
        picked = [h for h in holes if str(h.get("no")) in sel]
        n_hole = len(picked)
        test_len = round(sum(num(h.get("depth")) for h in picked), 2)
        qty = test_len
        agg = {}
        for h in picked:
            d = num(h.get("depth"))
            if d <= 0:
                continue
            p = S.price_at("wave", d, method) or 0
            lab = wave_band(d)[0]
            it = agg.setdefault(lab, {"label": lab, "price": round(p, 2), "holes": 0,
                                      "meters": 0.0, "amount": 0.0, "nos": []})
            it["holes"] += 1
            it["meters"] = round(it["meters"] + d, 2)
            it["amount"] = round(it["amount"] + p * d, 2)
            it["nos"].append(str(h.get("no")))
        # 按单价从浅到深排列
        bands = sorted(agg.values(), key=lambda x: x["price"])
        spec_head = "勾选 %d 孔，按各孔孔深分档计价" % n_hole
    else:
        n_hole = int(num(wv.get("holes")))
        test_len = num(wv.get("testLen")) or wdepth
        qty = n_hole * test_len
        spec_head = "%d孔×%.2fm" % (n_hole, test_len)
    if n_hole > 0 and wdepth > 0:
        if bands:
            for b in bands:
                lines.append({"item": "钻孔波速测试", "sub": "跨孔法" if method else "单孔法",
                              "spec": "%s（%d孔 %.2fm）" % (b["label"], b["holes"], b["meters"]),
                              "unit": "m", "price": b["price"], "qty": b["meters"],
                              "amount": b["amount"], "coef": k_geo,
                              "total": round(b["amount"] * k_geo, 2)})
        else:
            price = S.price_at("wave", wdepth, method) or 0
            bands = [{"label": wave_band(wdepth)[0], "price": round(price, 2),
                      "holes": n_hole, "meters": round(qty, 2),
                      "amount": round(price * qty, 2), "nos": []}]
            lines.append({"item": "钻孔波速测试", "sub": "跨孔法" if method else "单孔法",
                          "spec": "%s；%s" % (spec_head, wave_band(wdepth)[0]),
                          "unit": "m", "price": round(price, 2), "qty": round(qty, 2),
                          "amount": round(price * qty, 2), "coef": k_geo,
                          "total": round(price * qty * k_geo, 2)})
        res["waveDepth"] = round(wdepth, 2)
        res["waveBands"] = bands
        res["waveMeters"] = round(qty, 2)
        res["waveHoles"] = n_hole
        # 不足 2 个组日
        group_min = 2 * 1000
        if sum(l["amount"] for l in lines) < group_min and wv.get("minGroup", True):
            res["warnings"].append("钻孔波速测试收费不足2个组日，按2个组日（%d元）计取。" % group_min)

    # 电法（两种计价方式：按电极距 L / 按测点距 L，各对应表7.2-1 的一张子表）
    for it in geo.get("elec") or []:
        pts = num(it.get("qty"))
        if pts <= 0:
            continue
        space = it.get("space") or "elec"
        sp = S.ELEC_SPACING.get(space) or S.ELEC_SPACING["elec"]
        tid = sp.get("table", "elec")
        row = int(num(it.get("row"), 0))
        ci = int(num(it.get("method"), 0))
        base = S.row_price(tid, row, ci)
        if base is None:
            res["warnings"].append(
                "电法勘探「%s %s」无对应收费基价（表7.2-1 该档为空格），已跳过该行。"
                % (sp["label"], sp["options"][row] if 0 <= row < len(sp["options"]) else ""))
            continue
        mult = 1.0
        notes = []
        if it.get("dense"):
            mult *= 0.8
            notes.append("高密度电法×0.8")
        if it.get("ip"):
            mult *= 2.4
            notes.append("激发极化×2.4")
        if it.get("charge"):
            mult *= 1.2
            notes.append("充电法×1.2")
        price = base * mult
        tbl = S.TABLES[tid]
        mname = tbl["cols"][ci] if 0 <= ci < len(tbl["cols"]) else ""
        olab = sp["options"][row] if 0 <= row < len(sp["options"]) else ""
        rlab = "%s %s" % (sp["label"], olab)
        lines.append({"item": "电法勘探", "sub": mname, "spec": " ".join([rlab] + notes),
                      "unit": "点", "price": round(price, 2), "qty": pts,
                      "amount": round(price * pts, 2), "coef": k_geo,
                      "total": round(price * pts * k_geo, 2)})
    # 其他物探（面波/雷达/瞬变电磁/测井/管线等）
    for it in geo.get("extra") or []:
        qty = num(it.get("qty"))
        if qty <= 0:
            continue
        price = num(it.get("price"))
        if price <= 0:
            continue
        lines.append({"item": it.get("name", "物探"), "sub": "", "spec": it.get("spec", ""),
                      "unit": it.get("unit", ""), "price": price, "qty": qty,
                      "amount": round(price * qty, 2), "coef": k_geo,
                      "total": round(price * qty * k_geo, 2)})
    if lines:
        sec3["groups"].append({"key": "geo", "title": "物探项目", "lines": lines})
    geo_real = sum(l["total"] for l in lines)
    grate = S.TECH_RATE["工程物探"].get(state.get("grade", "甲级"), 0.22)
    sec3["real"] = round(geo_real, 2)
    sec3["tech"] = round(geo_real * grate, 2)
    sec3["techRate"] = grate
    sec3["amount"] = round(geo_real * (1 + grate), 2)
    sec3["coef"] = k_geo
    res["sections"].append(sec3)

    # ================= 4 其他费用 =================
    sec4 = {"key": "other", "title": "四、其他费用", "groups": [], "amount": 0.0}
    lines = []
    oth = state.get("other") or {}
    for oi in S.OTHER_ITEMS:
        q = num(oth.get(oi["id"]))
        if q <= 0:
            continue
        pr = num(oth.get(oi["id"] + "_price"), oi["price"])
        lines.append({"item": oi["name"], "sub": "", "spec": "", "unit": oi["unit"],
                      "price": pr, "qty": q, "amount": round(pr * q, 2), "coef": 1.0,
                      "total": round(pr * q, 2)})
    for it in oth.get("custom") or []:
        q = num(it.get("qty"))
        pr = num(it.get("price"))
        if q <= 0 or pr <= 0:
            continue
        lines.append({"item": it.get("name", "增项"), "sub": "", "spec": "预留增项",
                      "unit": it.get("unit", "项"), "price": pr, "qty": q,
                      "amount": round(pr * q, 2), "coef": 1.0, "total": round(pr * q, 2)})
    if lines:
        sec4["groups"].append({"key": "other", "title": "其他费用", "lines": lines})
    sec4["real"] = round(sum(l["total"] for l in lines), 2)
    sec4["tech"] = 0.0
    sec4["techRate"] = 0.0
    sec4["amount"] = sec4["real"]
    res["sections"].append(sec4)

    # ================= 汇总 =================
    base = sum(s["amount"] for s in res["sections"])
    coord = 0.0
    float_pct = num(state.get("float"))
    discount = num(state.get("discount"))
    after_float = (base + coord) * (1 + float_pct / 100.0)
    final = after_float * (1 - discount / 100.0)
    res["totals"] = {
        "base": round(base, 2),
        "coord": round(coord, 2),
        "floatPct": float_pct,
        "afterFloat": round(after_float, 2),
        "discountPct": discount,
        "final": round(final, 2),
    }
    res["grades"] = list(S.TECH_RATE["岩土工程勘察"].keys())
    return res
