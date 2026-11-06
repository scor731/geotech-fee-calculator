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
    系数相加，减去系数个数，加上定值1。  即 1 + Σ(v-1)；
    收费不可能为负，合成结果以 0 为下限（防御性保护，正常勾选不会触发）。"""
    vals = [v for v in values if v and abs(v - 1) > 1e-9]
    if not vals:
        return 1.0
    return max(round(1 + sum(v - 1 for v in vals), 4), 0.0)


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

    # 最后一层默认「无穷」：层底深不填（0 / 空）表示该层延伸至孔底，不必逐层填深度。
    # 有限层按层底排序在前，无限层排在最后（只有第一个无限层会填充到孔底）。
    raw_layers = list(state.get("layers") or [])
    layers = [L for L in raw_layers if num(L.get("bottom")) > 0]
    layers.sort(key=lambda x: num(x.get("bottom")))
    layers += [L for L in raw_layers if num(L.get("bottom")) <= 0]
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
                unbounded = bot <= 0        # 最后一层：层底无穷
                if unbounded:
                    bot = depth
                if bot <= top:
                    continue
                e = min(bot, depth)
                if e - top > 1e-9:
                    # 层号带亚层：主层编号 + "-" + 亚层编号，导出时再转 ①1
                    code = str(L.get("code") or "")
                    sub = str(L.get("sub") or "").strip()
                    if sub:
                        code = (code + "-" + sub) if code else sub
                    segs.append({"code": code, "name": L.get("name", ""),
                                 "cls": int(num(L.get("cls"), 1)), "top": top, "bot": e})
                top = bot
                if unbounded or top >= depth - 1e-9:
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
    # 附加调整系数分两类作用范围（总则1.0.8「相应的实物工作收费」）：
    #   drill = 仅作用于钻探进尺（跟管钻进、斜孔等工艺系数，不放大取样/原位测试）
    #   field = 作用于现场实物工作（夜间、水上、地形复杂等作业条件系数）
    all_coefs = {c["id"]: c for c in S.COEF_SOIL}
    all_coefs.update({c["id"]: c for c in S.COEF_GLOBAL})
    soil_ids = list(state.get("coefSoil") or [])
    glob_ids = list(state.get("coefGlobal") or [])
    drill_ids = [i for i in soil_ids if all_coefs.get(i, {}).get("scope") == "drill"]
    field_ids = [i for i in soil_ids + glob_ids if i not in drill_ids]
    k_drill = combine_coef([all_coefs[i]["v"] for i in field_ids + drill_ids if i in all_coefs])
    k_field = combine_coef([all_coefs[i]["v"] for i in field_ids if i in all_coefs])
    k_soil = k_drill  # 勘探（钻孔/探井）用

    geo_coefs = {c["id"]: c for c in S.COEF_GEO}
    gsel = [geo_coefs[i]["v"] for i in (state.get("coefGeo") or []) if i in geo_coefs]
    k_geo = combine_coef(gsel)

    holes = build_holes(state)
    res["holes"] = holes

    # 技术工作费归属：survey = 与勘察一并完成（按勘察比例）；standalone = 独立委托
    att = state.get("techAttach") or {}

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
                      "coef": k_field, "total": round(price * cnt * k_field, 2)})
    for key, label, tid, unit in (("disturb", "扰动取土", "disturb", "件"),
                                  ("core", "取岩芯样（天然抗压）", "core", "件"),
                                  ("coreSat", "取岩芯样（饱和抗压）", "core", "件"),
                                  ("point", "取点荷载岩样", "point", "块"),
                                  ("water", "取水", "water", "件")):
        c = num(sm.get(key))
        if c > 0:
            price = S.row_price("sample_extra", tid, 0) or 0
            lines.append({"item": label, "sub": "", "spec": "", "unit": unit, "price": price,
                          "qty": c, "amount": round(price * c, 2), "coef": k_field,
                          "total": round(price * c * k_field, 2)})
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
                      "coef": k_field, "total": round(price * c * k_field, 2)})
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
                      "coef": k_field, "total": round(price * c * k_field, 2)})
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
            # 定档口径与界面 packSubOf 一致：有 ptype 时按 压水深度(D≤20/D>20) 或注水类型定档；
            # 旧项目只有 sub 的直接信任 sub（v2.1 以前保存的状态）
            ptype = it.get("ptype")
            if not ptype:
                sub = it.get("sub", "pack_le20")
            elif ptype == "inj_hole":
                sub = "inj_hole"
            elif ptype == "inj_pit":
                sub = "inj_pit"
            else:
                sub = "pack_gt20" if num(it.get("depth")) > 20 else "pack_le20"
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
                      "coef": k_field, "total": round(amt * k_field, 2)})
    if lines:
        sec1["groups"].append({"key": "insitu", "title": "原位测试", "lines": lines})
        detail += lines

    # 1.5 勘探点定位测量已移至「其他费用」分部（见第 4 节），
    #     仍是岩土工程勘察的实物工作，技术工作费默认按勘察比例计取。
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
    sec1["real"] = round(soil_real, 2)
    sec1["ownReal"] = round(soil_real, 2)
    sec1["tech"] = 0.0
    sec1["techRate"] = rate
    sec1["amount"] = round(soil_real, 2)
    sec1["coef"] = k_soil
    sec1["coefField"] = k_field
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
    if state.get("labInSite"):
        sec2["note"] = "移至现场进行的室内试验，附加调整系数1.3（表8.5）"
        lab_real = lab_real * 1.3
        for l in lines:
            l["coef"] = 1.3
            l["total"] = round(l["amount"] * 1.3, 2)
    sec2["real"] = round(lab_real, 2)
    sec2["workReal"] = round(lab_real, 2)
    sec2["tech"] = 0.0
    sec2["techRate"] = lrate
    sec2["amount"] = round(lab_real, 2)
    res["sections"].append(sec2)

    # ================= 3 工程物探 =================
    sec3 = {"key": "geo", "title": "三、工程物探", "groups": [], "amount": 0.0}
    lines = []
    geo = state.get("geo") or {}
    wv = geo.get("wave") or {}
    # 每孔测试深度的默认值＝本项目最深孔；用户填了值就按填写值定档（不一定是孔深）
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
        # 每孔测试深度：默认取本项目最深孔；用户填写后按填写值，深度档也随之按它判定
        test_len = num(wv.get("testLen")) or wdepth
        qty = n_hole * test_len
        spec_head = "%d孔×%.2fm" % (n_hole, test_len)
        if test_len > 0:
            wdepth = test_len
    if n_hole > 0 and wdepth > 0:
        if bands:
            for b in bands:
                lines.append({"item": "钻孔波速测试", "sub": "跨孔法" if method else "单孔法",
                              "spec": "%s（%d孔 %.2fm）" % (b["label"], b["holes"], b["meters"]),
                              "unit": "m", "price": b["price"], "qty": b["meters"],
                              "amount": b["amount"], "coef": k_geo,
                              "total": round(b["amount"] * k_geo, 2), "part": "wave"})
        else:
            price = S.price_at("wave", wdepth, method) or 0
            bands = [{"label": wave_band(wdepth)[0], "price": round(price, 2),
                      "holes": n_hole, "meters": round(qty, 2),
                      "amount": round(price * qty, 2), "nos": []}]
            lines.append({"item": "钻孔波速测试", "sub": "跨孔法" if method else "单孔法",
                          "spec": "%s；%s" % (spec_head, wave_band(wdepth)[0]),
                          "unit": "m", "price": round(price, 2), "qty": round(qty, 2),
                          "amount": round(price * qty, 2), "coef": k_geo,
                          "total": round(price * qty * k_geo, 2), "part": "wave"})
        res["waveDepth"] = round(wdepth, 2)
        res["waveBands"] = bands
        res["waveMeters"] = round(qty, 2)
        res["waveHoles"] = n_hole
        # 不足 2 个组日：按 2 个组日（2000 元）计取，差额补入实物工作费（表7.2-1 注）
        group_min = 2 * 1000
        wave_now = sum(l["total"] for l in lines)
        if wave_now < group_min and wv.get("minGroup", True):
            add = round(group_min - wave_now, 2)
            lines.append({"item": "钻孔波速测试", "sub": "最低 2 个组日补差",
                          "spec": "不足 2 个组日按 2 个组日计", "unit": "项",
                          "price": add, "qty": 1, "amount": add, "coef": 1.0,
                          "total": add, "part": "wave", "minAdd": True})
            res["waveMinAdd"] = add
            res["warnings"].append(
                "钻孔波速测试实物工作费 %.2f 元，不足 2 个组日，已补差 %.2f 元，按 2000 元计取。" % (wave_now, add))

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
    wave_lines = [l for l in lines if l.get("part") == "wave"]
    geo_lines = [l for l in lines if l.get("part") != "wave"]
    if wave_lines:
        sec3["groups"].append({"key": "wave", "title": "钻孔波速测试", "lines": wave_lines})
    if geo_lines:
        sec3["groups"].append({"key": "geo", "title": "物探项目", "lines": geo_lines})
    geo_all = sum(l["total"] for l in lines)
    wave_real = sum(l["total"] for l in wave_lines)
    res["waveReal"] = round(wave_real, 2)
    grate = S.TECH_RATE["工程物探"].get(state.get("grade", "甲级"), 0.22)
    sec3["real"] = round(geo_all, 2)
    sec3["workReal"] = round(geo_all, 2)
    sec3["waveReal"] = round(wave_real, 2)
    sec3["geoReal"] = round(geo_all - wave_real, 2)
    sec3["tech"] = 0.0
    sec3["techRate"] = grate
    sec3["amount"] = round(geo_all, 2)
    sec3["coef"] = k_geo
    res["sections"].append(sec3)

    # ================= 4 其他费用 =================
    sec4 = {"key": "other", "title": "四、其他费用", "groups": [], "amount": 0.0}
    oth = state.get("other") or {}
    grade = state.get("grade", "甲级")

    # 4.1 勘探点定位测量（总则1.0.13 工程测量 1000 元/组日）
    # 在本分部单独统计；技术工作费默认按岩土工程勘察比例计取
    # （《使用手册》第3章技术费公式中「勘探点定位测量」属勘察基数），
    # 独立委托时可切换为工程测量 22%。
    coord_lines = []
    coord_st = state.get("coord") or {}
    cdays = num(coord_st.get("days"))
    cprice = S.COORD_ITEM["price"]        # 总则1.0.13 固定 1000 元/组日，不接受用户改价
    if cdays <= 0:                     # 兼容旧项目：定点测量原放在「其他费用」里
        cdays = num(oth.get("survey"))
    if cdays > 0:
        coord_lines = [{
            "item": "勘探点定位测量", "sub": "", "spec": "工程测量（总则1.0.13）",
            "unit": "组日", "price": round(cprice, 2), "qty": round(cdays, 2),
            "amount": round(cprice * cdays, 2), "coef": 1.0,
            "total": round(cprice * cdays, 2),
        }]
        sec4["groups"].append({"key": "coord", "title": "勘探点定位测量", "lines": coord_lines})

    # 4.2 其他费用（台班 / 验槽 / 报告费 / 预留增项，不计技术工作费）
    lines = []
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

    coord_attach = (att.get("coord") or "survey") != "standalone"
    crate = sec1["techRate"] if coord_attach else S.TECH_RATE["工程测量"].get(grade, 0.22)
    coord_real = round(sum(l["total"] for l in coord_lines), 2)
    all_real = round(sum(l["total"] for l in coord_lines + lines), 2)
    sec4["real"] = all_real
    sec4["workReal"] = all_real
    sec4["coordReal"] = coord_real
    sec4["techRate"] = round(crate, 4) if coord_real > 0 else 0.0
    sec4["techBase"] = coord_real
    sec4["tech"] = round(coord_real * crate, 2) if coord_real > 0 else 0.0
    sec4["amount"] = round(all_real + sec4["tech"], 2)
    sec4["coordAttach"] = bool(coord_attach)
    if coord_real > 0:
        sec4["techBasis"] = ("勘探点定位测量随勘察委托，按勘察 %s 比例" % grade) if coord_attach \
            else "工程测量独立委托 22%"
        sec4["techLabel"] = ("技术工作费（勘探点定位测量，按勘察 %d%%）" % round(crate * 100)) if coord_attach \
            else ("技术工作费（勘探点定位测量独立委托，按工程测量 %d%%）" % round(crate * 100))
    res["sections"].append(sec4)

    # ================= 技术工作费：各分部各自计取，最后相加 =================
    # 依据《使用手册》第3章：与勘察一并完成的室内试验、钻孔波速、勘探点定位测量，
    # 技术工作费按「岩土工程勘察」技术工作费比例计取；但各分部独立统计、独立列示、
    # 独立计入基准价，不并入「岩土工程勘察」分部，避免出现分部小计为 0 的漏斗式汇总。
    # 只有独立委托、单独提交成篇报告时，才分别按室内试验 10%、工程物探 22% 单独计取。
    sr = sec1["techRate"]

    # 1 岩土工程勘察：仅按本分部实物工作费计取
    sec1["real"] = round(sec1["ownReal"], 2)
    sec1["techBase"] = sec1["real"]
    sec1["tech"] = round(sec1["real"] * sr, 2)
    sec1["amount"] = round(sec1["real"] + sec1["tech"], 2)
    sec1["techLabel"] = "技术工作费（%d%%）" % round(sr * 100)
    sec1["techBasis"] = "岩土工程勘察 %s，第一章 1.0.6 条" % grade

    # 2 室内试验：与勘察一并完成 → 按勘察比例；独立委托 → 10%
    lab_work = round(num(sec2.get("workReal")), 2)
    lab_attach = (att.get("lab") or "survey") != "standalone"
    lrate = sr if lab_attach else S.TECH_RATE["室内试验"].get(grade, 0.10)
    sec2["real"] = lab_work
    sec2["techBase"] = lab_work
    sec2["techRate"] = round(lrate, 4)
    sec2["tech"] = round(lab_work * lrate, 2)
    sec2["amount"] = round(lab_work + sec2["tech"], 2)
    sec2["attach"] = "survey" if lab_attach else "standalone"
    sec2["techLabel"] = ("技术工作费（按勘察 %d%% 计取）" % round(lrate * 100)) if lab_attach \
        else ("技术工作费（独立委托，按室内试验 %d%% 计取）" % round(lrate * 100))
    sec2["techBasis"] = ("室内试验随勘察一并委托，按勘察 %s 比例" % grade) if lab_attach else "室内试验独立委托"

    # 3 工程物探：钻孔波速（与勘察一并完成）按勘察比例，其他物探按 22%
    wave_work = round(num(sec3.get("waveReal")), 2)
    geo_work = round(num(sec3.get("geoReal")), 2)
    wave_attach = (att.get("wave") or "survey") != "standalone"
    grate = S.TECH_RATE["工程物探"].get(grade, 0.22)
    wrate = sr if wave_attach else grate
    wave_tech = round(wave_work * wrate, 2)
    geo_tech = round(geo_work * grate, 2)
    sec3["real"] = round(wave_work + geo_work, 2)
    sec3["techBase"] = sec3["real"]
    sec3["tech"] = round(wave_tech + geo_tech, 2)
    sec3["amount"] = round(sec3["real"] + sec3["tech"], 2)
    sec3["waveRate"] = round(wrate, 4)
    sec3["geoRate"] = round(grate, 4)
    sec3["waveTech"] = wave_tech
    sec3["geoTech"] = geo_tech
    sec3["attach"] = "survey" if wave_attach else "standalone"
    parts = []
    if wave_work > 0:
        parts.append({"key": "wave", "name": "钻孔波速测试", "real": wave_work,
                      "rate": round(wrate, 4), "tech": wave_tech,
                      "label": ("按勘察 %d%%" % round(wrate * 100)) if wave_attach
                               else ("独立委托 %d%%" % round(wrate * 100))})
    if geo_work > 0:
        parts.append({"key": "geo", "name": "其他物探", "real": geo_work,
                      "rate": round(grate, 4), "tech": geo_tech,
                      "label": "工程物探 %d%%" % round(grate * 100)})
    sec3["rateParts"] = parts
    sec3["techRate"] = parts[0]["rate"] if len(parts) == 1 else (
        round(grate, 4) if geo_work > 0 else round(wrate, 4))
    sec3["techLabel"] = "技术工作费" + (
        "（%s）" % "；".join("%s %s" % (p["name"], p["label"]) for p in parts) if parts else "")

    res["techAttach"] = {"lab": "survey" if lab_attach else "standalone",
                         "wave": "survey" if wave_attach else "standalone",
                         "coord": "survey" if coord_attach else "standalone",
                         "labRate": round(lrate, 4), "waveRate": round(wrate, 4),
                         "coordRate": round(crate, 4)}

    # ================= 5 工程测量 =================
    # 第二章：技术工作费比例 22%（2.1）；复杂程度分简单/中等/复杂三档（表2.2-1 等），
    # 附加调整系数按《使用手册》对表2.2-3 的解释逐条匹配到对应项目（序号1~2→三角(边)、
    # 3→房顶标志(三角)/墙上水准(水准)、4/6~7→导线、5→GPS、8~14→地形测量…），
    # 同一项目上叠加多条系数时按总则1.0.8「相加－个数＋1」合成，不连乘；总则系数作用于全部项目。
    # 本分部独立统计并计入基准价。
    sec5 = {"key": "survey", "title": "五、工程测量", "groups": [], "amount": 0.0}
    sv = state.get("survey") or {}
    sbook = {c["id"]: c for c in S.SURVEY_COEF}
    ssel = [i for i in (sv.get("coefs") or []) if i in sbook]

    def s_applied(fam):
        """某个测量项目族实际生效的系数条目（表2.2-3 按 to 匹配，总则系数 to=["*"] 作用于全部）"""
        return [sbook[i] for i in ssel
                if fam in (sbook[i].get("to") or []) or "*" in (sbook[i].get("to") or [])]

    def s_coef(fam):
        """该族的附加调整系数：生效条目按总则1.0.8 合成（相加－个数＋1，不连乘）"""
        return combine_coef([c["v"] for c in s_applied(fam)])

    sgroups = {}
    sorder = []
    for row in sv.get("items") or []:
        it = S.SURVEY_ITEM_MAP.get(row.get("id"))
        if not it:
            continue
        qty = num(row.get("qty"))
        price = num(row.get("price"))
        if qty <= 0:
            continue
        ci = min(max(int(num(row.get("complex"), 1)), 0), 2)
        if price <= 0:
            price = it["vals"][ci]
        spec = S.SURVEY_COMPLEX[ci]
        if it["id"] == "small" and qty < 3:      # 表2.6-1 序号4：不足3个组日按3个组日计
            res["warnings"].append("小型工程测量 %.2f 个组日，不足 3 个组日，已按 3 个组日计取。" % qty)
            qty = 3.0
            spec += "；不足3组日按3组日"
        fam = S.SURVEY_ITEM_FAM.get(it["id"], it["grp"])
        k = s_coef(fam)
        # 生效系数的工程量提示（如「修测按实际修测面积填」「汇水面积按汇水面积填」）写进规格，
        # 导出 Excel / Word 的「规格 / 说明」列可直接看到取价依据
        hints = [c["hint"] for c in s_applied(fam) if c.get("hint")]
        if hints:
            spec += "；" + "；".join(hints)
        line = {"item": it["name"], "sub": "", "spec": spec, "unit": it["unit"],
                "price": round(price, 2), "qty": round(qty, 2),
                "amount": round(price * qty, 2), "coef": k,
                "hint": "；".join(hints),
                "total": round(price * qty * k, 2)}
        if it["grp"] not in sgroups:
            gname = next((g["name"] for g in S.SURVEY_GROUPS if g["key"] == it["grp"]), it["grp"])
            sgroups[it["grp"]] = {"key": it["grp"], "title": gname, "lines": []}
            sorder.append(it["grp"])
        sgroups[it["grp"]]["lines"].append(line)

    for gk in sorder:
        sec5["groups"].append(sgroups[gk])
    sv_lines = [l for g in sec5["groups"] for l in g["lines"]]
    sv_real = round(sum(l["total"] for l in sv_lines), 2)
    srate = S.TECH_RATE["工程测量"].get(grade, 0.22)
    sec5["real"] = sv_real
    sec5["workReal"] = sv_real
    sec5["techBase"] = sv_real
    sec5["techRate"] = round(srate, 4)
    sec5["tech"] = round(sv_real * srate, 2)
    sec5["amount"] = round(sv_real + sec5["tech"], 2)
    sec5["techLabel"] = "技术工作费（工程测量 %d%%）" % round(srate * 100)
    sec5["techBasis"] = "工程测量，第二章 2.1 条"
    sec5["coefByFam"] = {f["id"]: round(s_coef(f["id"]), 4) for f in S.SURVEY_FAMILIES}
    sec5["itemCount"] = len(sv_lines)
    res["sections"].append(sec5)

    # ================= 汇总 =================
    # 五个分部（勘察 / 室内试验 / 工程物探 / 其他费用 / 工程测量）各自统计，小计相加即基准价
    base = sum(s["amount"] for s in res["sections"])
    coord = 0.0
    float_pct = num(state.get("float"))
    discount = num(state.get("discount"))
    after_float = (base + coord) * (1 + float_pct / 100.0)
    final = after_float * (1 - discount / 100.0)
    total_depth = round(sum(num(h.get("depth")) for h in holes), 2)
    res["totals"] = {
        "base": round(base, 2),
        "coord": round(coord, 2),
        "floatPct": float_pct,
        "afterFloat": round(after_float, 2),
        "discountPct": discount,
        "final": round(final, 2),
        "depth": total_depth,
        "unitPrice": round(final / total_depth, 2) if total_depth > 0 else 0.0,
    }
    res["grades"] = list(S.TECH_RATE["岩土工程勘察"].keys())
    return res
