# -*- coding: utf-8 -*-
"""
理正勘察数据库 / 导出表 导入。

支持：
  · .xlsx / .xls / .csv   —— 理正「输出到 Excel」的钻孔表、分层表、原位测试表
  · .mdb / .accdb         —— 理正 Access 备份库（需本机安装 Access 数据库引擎）
  · .zip                  —— 自动解压后读取其中第一个可识别文件
  · .bak                  —— SQL Server 备份，无法直接读取，给出导出指引

导入后自动识别：孔号 / 岩土名称 / 层底深度 / 孔深 / 试验深度 / 击数 等列，
并按「岩土名称→岩土类别」对照表给出初始类别，供界面修正。
"""
import csv
import io
import os
import re
import tempfile
import zipfile
from collections import Counter

from . import standards as S

HOLE_KEYS = ["孔号", "钻孔编号", "勘探点编号", "孔口编号", "钻孔号", "勘探点号", "zk编号", "编号"]
NAME_KEYS = ["岩土名称", "岩性", "土名", "地层名称", "岩土定名", "土层名称", "名称", "岩土描述"]
BOTTOM_KEYS = ["层底深度", "层底埋深", "底深度", "层底", "终止深度", "下限深度"]
CODE_KEYS = ["层号", "地层编号", "层序号", "地层代号"]
HDEPTH_KEYS = ["孔深", "终孔深度", "钻孔深度", "勘探深度", "孔深(m)", "终孔孔深"]
TDEPTH_KEYS = ["试验深度", "测试深度", "试验深度(m)", "测试点深度", "深度", "起始深度", "试段深度"]
TYPE_KEYS = ["试验名称", "试验类型", "测试项目", "原位测试类型", "试验项目", "项目名称"]
HOLE_TYPE_KEYS = ["勘探点类型", "孔类型", "钻孔类型", "孔别", "类型"]
BLOW_KEYS = ["击数", "实测击数", "校正击数", "n值", "n63.5", "锤击数"]
THICK_KEYS = ["层厚", "厚度", "分层厚度"]


def _norm(s):
    return re.sub(r"[\s\(\)（）:：\.]+", "", str(s or "")).lower()


def _find_col(header, keys):
    """在表头行里找第一个匹配的列号（精确优先，其次包含）"""
    hs = [_norm(h) for h in header]
    for k in keys:
        kn = _norm(k)
        for i, h in enumerate(hs):
            if h == kn:
                return i
    for k in keys:
        kn = _norm(k)
        for i, h in enumerate(hs):
            if kn and kn in h:
                return i
    return -1


def _to_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("，", ".").replace(",", "")
    m = re.search(r"-?\d+(\.\d+)?", s)
    return float(m.group(0)) if m else None


# ---------------------------------------------------------------------------
# 读取为「表格列表」
# ---------------------------------------------------------------------------
def read_tables(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".zip":
        tmp = os.path.join(os.path.dirname(path), "__lz_tmp__")
        os.makedirs(tmp, exist_ok=True)
        with zipfile.ZipFile(path) as z:
            z.extractall(tmp)
        for root, _, files in os.walk(tmp):
            for f in files:
                if os.path.splitext(f)[1].lower() in (".mdb", ".accdb", ".xls", ".xlsx", ".csv"):
                    return read_tables(os.path.join(root, f))
        raise ValueError("压缩包内没有找到可识别的数据库或表格文件")
    if ext in (".xlsx", ".xlsm"):
        return _read_xlsx(path)
    if ext == ".xls":
        return _read_xls(path)
    if ext == ".csv":
        return _read_csv(path)
    if ext in (".mdb", ".accdb"):
        return _read_access(path)
    if ext == ".bak":
        raise ValueError(
            "这是 SQL Server 备份文件（.bak），无法离线读取。\n"
            "请在理正勘察软件中打开该工程，使用「数据输出 / 导出到 Excel」导出"
            "钻孔表、分层表、原位测试表，再把导出的 .xls/.xlsx 拖入本软件。")
    raise ValueError("不支持的文件类型：%s" % ext)


def _read_xlsx(path):
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True, read_only=True)
    out = []
    for ws in wb.worksheets:
        rows = []
        for r in ws.iter_rows(values_only=True):
            rows.append(["" if c is None else c for c in r])
        if rows:
            out.append((ws.title, rows))
    wb.close()
    return out


def _read_xls(path):
    import xlrd
    b = xlrd.open_workbook(path)
    out = []
    for sh in b.sheets():
        rows = []
        for i in range(sh.nrows):
            rows.append([sh.cell_value(i, j) for j in range(sh.ncols)])
        if rows:
            out.append((sh.name, rows))
    return out


def _read_csv(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "gbk", "gb18030", "utf-16"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", "ignore")
    rows = [r for r in csv.reader(io.StringIO(text))]
    return [(os.path.basename(path), rows)]


def _read_access(path):
    """Access 通用读取（非理正库时的兜底），依赖 pyodbc + Access 驱动。"""
    try:
        import pyodbc
    except ImportError:
        raise ValueError("无法读取该 Access 数据库：内置解析器未能识别，且本机没有 pyodbc 组件。\n"
                         + ("原因：" + "；".join(_LZ_LAST) + "\n" if _LZ_LAST else "")
                         + "建议：在理正勘察中「数据输出 / 导出到 Excel」，再把导出的 .xls/.xlsx 拖入本软件。")
    errs = []
    for drv in ("Microsoft Access Driver (*.mdb, *.accdb)",
                "Microsoft Access Driver (*.mdb)",
                "Microsoft.ACE.OLEDB.12.0"):
        for tmpl in ("DRIVER={%s};DBQ=%s;", "Provider=%s;Data Source=%s;"):
            try:
                conn = pyodbc.connect(tmpl % (drv, path), readonly=True)
                cur = conn.cursor()
                tabs = [r.table_name for r in cur.tables(tableType="TABLE")]
                out = []
                for t in tabs:
                    try:
                        cur.execute('SELECT * FROM [%s]' % t)
                        cols = [d[0] for d in cur.description]
                        rows = [cols]
                        for rec in cur.fetchall():
                            rows.append(["" if v is None else v for v in rec])
                        if len(rows) > 1:
                            out.append((t, rows))
                    except Exception as e:
                        errs.append("%s: %s" % (t, e))
                conn.close()
                if out:
                    return out
            except Exception as e:
                errs.append(str(e))
    raise ValueError("无法打开 Access 数据库（本机可能未安装 Access 数据库引擎）。\n"
                     "建议：在理正勘察中导出 Excel 后再导入。\n技术信息："
                     + "; ".join(errs[:2])
                     + ("；内置解析器：" + "；".join(_LZ_LAST) if _LZ_LAST else ""))


# ---------------------------------------------------------------------------
# 理正 GICADBak 备份库（.mdb / .accdb）—— 纯 Python 解析，无需安装 Access
# 理正表结构：z_ZuanKong 钻孔表、z_g_TuCeng 分层表、z_y_BiaoGuan 标贯、
#             z_y_DongTan 动探、z_c_QuYang 取土（岩）样、z_c_ShuiZhi 水样
# 字段均为拼音缩写，文本按 ANSI(GBK) 存放，纯 Python 解析器会按 latin1 解成乱码，需还原。
# ---------------------------------------------------------------------------
LZ_T_ZK = "z_ZuanKong"
LZ_T_TC = "z_g_TuCeng"
LZ_T_BG = "z_y_BiaoGuan"
LZ_T_DT = "z_y_DongTan"
LZ_T_QY = "z_c_QuYang"
LZ_T_SZ = "z_c_ShuiZhi"

DPT_KIND = {1: "dpt_light", 2: "dpt_heavy", 3: "dpt_super"}
SAMPLE_KIND = {0: "undist", 1: "disturb", 2: "core", 3: "water"}

# 内置解析器最近一次失败原因：打包缺组件时不再静默回退成「结构不支持」
_LZ_LAST = []


def _fix_text(v):
    if not isinstance(v, str) or not v:
        return v
    try:
        return v.encode("latin1").decode("gbk")
    except Exception:
        pass
    try:
        return v.encode("latin1").decode("gb18030")
    except Exception:
        return v


def _dump_table(db, name):
    try:
        d = db.parse_table(name)
    except Exception:
        return []
    cols = list(d.keys())
    if not cols:
        return []
    n = max(len(d[c]) for c in cols)
    rows = []
    for i in range(n):
        rows.append({c: _fix_text(d[c][i]) if i < len(d[c]) else None for c in cols})
    return rows


def _num(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except Exception:
        return None


def _parse_access_lizheng(path, name_class=None):
    """读理正备份库；不是理正结构 / 无解析组件时返回 None，交给通用流程。"""
    del _LZ_LAST[:]
    try:
        from access_parser import AccessParser
    except Exception as e:
        _LZ_LAST.append("内置解析组件不可用（%s）" % e)
        return None
    try:
        db = AccessParser(path)
    except Exception as e:
        _LZ_LAST.append("打开备份库失败（%s）" % e)
        return None

    tabs = set(db.catalog.keys())
    if LZ_T_TC not in tabs or LZ_T_ZK not in tabs:
        _LZ_LAST.append("库内未见理正表 %s / %s" % (LZ_T_ZK, LZ_T_TC))
        return None

    log = []
    zk = _dump_table(db, LZ_T_ZK)
    tc = _dump_table(db, LZ_T_TC)
    # 一个备份库里可能存了多个工程，取钻孔最多的那个
    gcsy = None
    c = Counter(r.get("GCSY") for r in zk if r.get("GCSY") is not None)
    if c:
        gcsy = c.most_common(1)[0][0]

    def keep(r):
        return gcsy is None or r.get("GCSY") in (None, gcsy)

    # 钻孔：孔号 / 孔深 / 孔型
    hole_depth, hole_type = {}, {}
    for r in zk:
        if not keep(r):
            continue
        no = str(r.get("ZKBH") or "").strip()
        if not no:
            continue
        d = _num(r.get("ZKSD"))
        if d:
            hole_depth[no] = max(d, hole_depth.get(no, 0.0))
        t = str(r.get("ZKLX") or "").strip()
        if t:
            hole_type[no] = t
    log.append("钻孔表 %d 个孔" % len(hole_depth))

    # 分层：孔号 / 岩土名称 / 层底深度 / 层厚 / 层号
    def code_of(r):
        zc, yc = r.get("TCZCBH"), r.get("TCYCBH")
        try:
            zc = int(zc) if zc is not None else 0
        except Exception:
            zc = 0
        try:
            yc = int(yc) if yc is not None else 0
        except Exception:
            yc = 0
        if zc <= 0:
            return ""
        return "%d-%d" % (zc, yc) if yc > 0 else str(zc)

    holes, names, groups = {}, {}, {}
    for r in tc:
        if not keep(r):
            continue
        no = str(r.get("ZKBH") or "").strip()
        nm = str(r.get("TCMC") or "").strip()
        if not no or not nm:
            continue
        bot = _num(r.get("TCCDSD"))
        th = _num(r.get("TCHD"))
        h = holes.setdefault(no, {"no": no, "type": hole_type.get(no, "钻孔"),
                                  "depth": 0.0, "layers": []})
        if bot is None and th:
            prev = h["layers"][-1]["bottom"] if h["layers"] else 0.0
            bot = prev + th
        if bot is None:
            continue
        code = code_of(r)
        h["layers"].append({"code": code, "name": nm, "bottom": round(float(bot), 3),
                            "cls": guess_class(nm, name_class)})
        names[nm] = names.get(nm, 0) + 1
        # 按理正自己的层号（综合层号 TCZCBH + 亚层号 TCYCBH）归集，
        # 同名层不会被合并：本库就是 ①素填土 ②红黏土 ③红黏土 ④石灰岩 ⑤石灰岩 ⑥充填溶洞 ⑥1溶洞
        g = groups.setdefault(code, {"nm": Counter(), "sum": 0.0, "n": 0})
        g["nm"][nm] += 1
        g["sum"] += float(bot)
        g["n"] += 1
    log.append("分层表 %d 条记录" % sum(len(h["layers"]) for h in holes.values()))

    # 标准地层：严格按理正层号顺序排列，不按名称合并
    def code_key(c):
        p = str(c or "").split("-")
        try:
            return (int(p[0]), int(p[1]) if len(p) > 1 else 0)
        except Exception:
            return (999, 0)

    std_layers = []
    for c in sorted(groups.keys(), key=code_key):
        g = groups[c]
        nm = g["nm"].most_common(1)[0][0]
        zc, yc = code_key(c)
        std_layers.append({"code": str(c), "no": zc, "sub": yc, "name": nm,
                           "cls": guess_class(nm, name_class),
                           "bottom": round(g["sum"] / g["n"], 1), "count": g["n"]})
    # 层底按自上而下单调递增（平均层底可能交叉，保持柱状图与层厚可读）
    for i in range(1, len(std_layers)):
        if std_layers[i]["bottom"] < std_layers[i - 1]["bottom"] + 0.1:
            std_layers[i]["bottom"] = round(std_layers[i - 1]["bottom"] + 0.1, 1)
    if std_layers:
        log.append("标准地层 %d 层（按理正层号）：%s"
                   % (len(std_layers), " / ".join(x["code"] + x["name"] for x in std_layers)))

    # 整理分层（按层底升序、去掉不递增的重复层）
    for no, h in holes.items():
        hs = sorted(h["layers"], key=lambda x: x["bottom"])
        cleaned, last = [], 0.0
        for L in hs:
            if L["bottom"] > last + 1e-9:
                cleaned.append(L)
                last = L["bottom"]
        h["layers"] = cleaned
        h["depth"] = round(max([L["bottom"] for L in cleaned] or [0]), 3)
        if hole_depth.get(no, 0) > h["depth"]:
            h["depth"] = round(hole_depth[no], 3)
        if not h["type"] or h["type"] == "None":
            h["type"] = "钻孔"

    def layer_at(no, d):
        h = holes.get(no)
        if not h:
            return "", 1, ""
        for L in h["layers"]:
            if d <= L["bottom"] + 1e-9:
                return L["name"], L["cls"], L.get("code", "")
        if h["layers"]:
            return h["layers"][-1]["name"], h["layers"][-1]["cls"], h["layers"][-1].get("code", "")
        return "", 1, ""

    # 标贯：一条记录 = 一次试验，按 (孔号, 深度) 去重后计数
    bg = _dump_table(db, LZ_T_BG)
    seen, spt_agg = set(), {}
    for r in bg:
        if not keep(r):
            continue
        no = str(r.get("ZKBH") or "").strip()
        d = _num(r.get("BGDSD"))
        if not no or d is None:
            continue
        k0 = (no, round(d, 2))
        if k0 in seen:
            continue
        seen.add(k0)
        nm, cls, lc = layer_at(no, d)
        band = 0 if d <= 20 else (1 if d <= 50 else 2)
        k = (nm, cls, band, lc)
        spt_agg[k] = spt_agg.get(k, 0) + 1
    log.append("标贯 %d 次" % len(seen))

    # 动探：每条记录是一段（常见 0.1m 一锤击记录），按段长累加米数
    dt = _dump_table(db, LZ_T_DT)
    dpt_agg = {}
    for r in dt:
        if not keep(r):
            continue
        no = str(r.get("ZKBH") or "").strip()
        d = _num(r.get("DTDSD"))
        ln = _num(r.get("DTCD"))
        if not no or d is None:
            continue
        if not ln or ln <= 0:
            ln = 0.1
        try:
            kind = DPT_KIND.get(int(_num(r.get("DTLX")) or 2), "dpt_heavy")
        except Exception:
            kind = "dpt_heavy"
        nm, cls, lc = layer_at(no, d)
        band = 0 if d <= 10 else (1 if d <= 20 else (2 if d <= 30 else (3 if d <= 40 else 4)))
        k = (kind, nm, cls, band, lc)
        dpt_agg[k] = dpt_agg.get(k, 0.0) + float(ln)
    log.append("动探 %d 段" % len(dt))

    # 取样：0 原状 / 1 扰动 / 2 岩样 / 3 水样
    qy = _dump_table(db, LZ_T_QY)
    samples = {"undist": 0, "disturb": 0, "core": 0, "point": 0, "water": 0}
    for r in qy:
        if not keep(r):
            continue
        try:
            lx = int(_num(r.get("QYLX")) or 0)
        except Exception:
            lx = 0
        key = SAMPLE_KIND.get(lx, "undist")
        samples[key] += 1
    sz = [r for r in _dump_table(db, LZ_T_SZ) if keep(r)]
    if sz:
        samples["water"] = max(samples["water"], len(sz))
    if any(samples.values()):
        log.append("取样 原状%d/扰动%d/岩样%d/水样%d 件"
                   % (samples["undist"], samples["disturb"], samples["core"], samples["water"]))

    spt = [{"layerName": k[0], "cls": k[1], "band": k[2], "count": v, "layerCode": k[3]}
           for k, v in sorted(spt_agg.items(), key=lambda x: (x[0][2], x[0][0]))]
    dpt = [{"kind": k[0], "layerName": k[1], "cls": k[2], "band": k[3],
            "meters": round(v, 2), "layerCode": k[4]}
           for k, v in sorted(dpt_agg.items(), key=lambda x: (x[0][3], x[0][1]))]

    def natkey(s):
        return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s))]
    holes_list = [holes[k] for k in sorted(holes.keys(), key=natkey)]

    return {
        "holes": holes_list,
        "stdLayers": std_layers,
        "spt": spt,
        "dpt": dpt,
        "samples": samples,
        "names": [{"name": k, "count": v, "cls": guess_class(k, name_class)}
                  for k, v in sorted(names.items(), key=lambda x: -x[1])],
        "log": log,
        "source": "理正备份库（%d 张表）" % len(tabs),
        "sheets": [],
        "summary": {
            "holes": len(holes_list),
            "totalDepth": round(sum(h["depth"] for h in holes_list), 2),
            "layers": sum(len(h["layers"]) for h in holes_list),
            "spt": sum(x["count"] for x in spt),
            "dpt": round(sum(x["meters"] for x in dpt), 2),
            "samples": sum(samples.values()),
        },
    }


# ---------------------------------------------------------------------------
# 角色识别
# ---------------------------------------------------------------------------
ROLES = ("hole", "layer", "spt", "dpt")


def _analyse_sheet(name, rows):
    """返回 dict(role, header_idx, cols{...}) 或 None"""
    best = None
    for hi in range(min(12, len(rows))):
        hdr = rows[hi]
        c_hole = _find_col(hdr, HOLE_KEYS)
        c_name = _find_col(hdr, NAME_KEYS)
        c_bot = _find_col(hdr, BOTTOM_KEYS)
        c_depth = _find_col(hdr, HDEPTH_KEYS)
        c_td = _find_col(hdr, TDEPTH_KEYS)
        c_type = _find_col(hdr, TYPE_KEYS)
        c_blow = _find_col(hdr, BLOW_KEYS)
        c_code = _find_col(hdr, CODE_KEYS)
        c_th = _find_col(hdr, THICK_KEYS)

        if c_hole >= 0 and c_name >= 0 and (c_bot >= 0 or c_th >= 0):
            return {"role": "layer", "header": hi,
                    "cols": {"hole": c_hole, "name": c_name,
                             "bottom": c_bot, "thick": c_th, "code": c_code}, "title": name}
        if c_hole >= 0 and c_depth >= 0 and c_name < 0:
            cand = {"role": "hole", "header": hi,
                    "cols": {"hole": c_hole, "depth": c_depth,
                             "type": _find_col(hdr, HOLE_TYPE_KEYS)}, "title": name}
            if best is None:
                best = cand
        if c_hole >= 0 and (c_type >= 0 or c_blow >= 0) and (c_td >= 0 or c_depth >= 0):
            cand = {"role": "test", "header": hi,
                    "cols": {"hole": c_hole, "type": c_type,
                             "depth": c_td if c_td >= 0 else c_depth, "blow": c_blow},
                    "title": name}
            if best is None or best["role"] == "hole":
                best = cand
    return best


def guess_class(name, name_class=None):
    """岩土名称 -> 类别序号"""
    if not name:
        return 1
    nm = str(name).strip()
    dic = name_class or S.DEFAULT_NAME_CLASS
    if nm in dic:
        return int(dic[nm])
    keys = sorted(dic.keys(), key=len, reverse=True)
    for k in keys:
        if k and k in nm:
            return int(dic[k])
    # 含岩石风化描述
    if "风化" in nm:
        if "全风" in nm or "强风" in nm:
            return 2
        if "中风" in nm:
            return 3
        return 4
    return 1


def parse(path, name_class=None):
    ext = os.path.splitext(path)[1].lower()
    # Access 备份库：先用内置解析器按理正表结构直读（无需安装 Access）
    if ext in (".mdb", ".accdb"):
        res = _parse_access_lizheng(path, name_class)
        if res:
            return res
    # 压缩包：解出内层文件后重走一遍
    if ext == ".zip":
        tmpdir = tempfile.mkdtemp(prefix="lz_")
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if os.path.splitext(n)[1].lower() in (".mdb", ".accdb", ".xls", ".xlsx", ".csv"):
                    return parse(z.extract(n, tmpdir), name_class)
        raise ValueError("压缩包内没有找到可识别的数据库或表格文件")

    tables = read_tables(path)
    log = []
    sheets = [_analyse_sheet(n, r) for n, r in tables]
    by_role = {}
    for t in tables:
        pass
    # 逐表归类
    layer_sheets, hole_sheets, test_sheets = [], [], []
    for (name, rows) in tables:
        info = _analyse_sheet(name, rows)
        if not info:
            log.append("跳过工作表「%s」：未识别到孔号/岩土名称等列" % name)
            continue
        info["rows"] = rows
        if info["role"] == "layer":
            layer_sheets.append(info)
        elif info["role"] == "hole":
            hole_sheets.append(info)
        else:
            test_sheets.append(info)

    if not layer_sheets:
        raise ValueError("未找到「分层表」（需要同时包含 孔号、岩土名称、层底深度/层厚 三列）。\n"
                         "已在文件中识别到的工作表：%s" % "、".join(n for n, _ in tables))

    # 孔深（来自钻孔表）
    hole_depth = {}
    hole_type = {}
    for info in hole_sheets:
        cols = info["cols"]
        for r in info["rows"][info["header"] + 1:]:
            if len(r) <= cols["hole"]:
                continue
            no = str(r[cols["hole"]]).strip()
            d = _to_float(r[cols["depth"]]) if cols["depth"] >= 0 and len(r) > cols["depth"] else None
            if no and d:
                hole_depth[no] = max(hole_depth.get(no, 0), d)
            if no and cols.get("type", -1) >= 0 and len(r) > cols["type"]:
                hole_type.setdefault(no, str(r[cols["type"]]).strip())

    # 分层
    holes = {}
    names = {}
    for info in layer_sheets:
        cols = info["cols"]
        for r in info["rows"][info["header"] + 1:]:
            try:
                no = str(r[cols["hole"]]).strip()
            except Exception:
                continue
            if not no or no in ("None", ""):
                continue
            nm = str(r[cols["name"]]).strip() if cols["name"] >= 0 and len(r) > cols["name"] else ""
            if not nm:
                continue
            bot = _to_float(r[cols["bottom"]]) if cols["bottom"] >= 0 and len(r) > cols["bottom"] else None
            th = _to_float(r[cols["thick"]]) if cols["thick"] >= 0 and len(r) > cols["thick"] else None
            code = str(r[cols["code"]]).strip() if cols["code"] >= 0 and len(r) > cols["code"] else ""
            h = holes.setdefault(no, {"no": no, "type": hole_type.get(no, "钻孔"),
                                      "depth": 0.0, "layers": []})
            if bot is None and th:
                prev = h["layers"][-1]["bottom"] if h["layers"] else 0.0
                bot = prev + th
            if bot is None:
                continue
            h["layers"].append({"code": code, "name": nm, "bottom": round(bot, 3),
                                "cls": guess_class(nm, name_class)})
            names[nm] = names.get(nm, 0) + 1

    for no, h in holes.items():
        hs = sorted(h["layers"], key=lambda x: x["bottom"])
        cleaned = []
        last = 0.0
        for L in hs:
            if L["bottom"] > last + 1e-9:
                cleaned.append(L)
                last = L["bottom"]
        h["layers"] = cleaned
        h["depth"] = round(max([L["bottom"] for L in cleaned] or [0]), 3)
        if no in hole_depth and hole_depth[no] > h["depth"]:
            h["depth"] = round(hole_depth[no], 3)
        h["type"] = h["type"] if h["type"] and h["type"] != "None" else "钻孔"

    # 原位测试：先按 (孔号, 深度) 去重，再按 (土层, 类别, 深度档) 汇总
    raw_spt, raw_dpt = [], []
    for info in test_sheets:
        cols = info["cols"]
        for r in info["rows"][info["header"] + 1:]:
            try:
                no = str(r[cols["hole"]]).strip()
            except Exception:
                continue
            if not no:
                continue
            d = _to_float(r[cols["depth"]]) if cols["depth"] >= 0 and len(r) > cols["depth"] else None
            if d is None:
                continue
            tname = ""
            if cols.get("type", -1) >= 0 and len(r) > cols["type"]:
                tname = str(r[cols["type"]])
            if ("标贯" in tname) or ("标准贯入" in tname) or ("SPT" in tname.upper()):
                grp = raw_spt
            elif ("动探" in tname) or ("动力触探" in tname) or ("DPT" in tname.upper()):
                grp = raw_dpt
            else:
                continue
            nm, cls = "", 1
            h = holes.get(no)
            if h:
                for L in h["layers"]:
                    if d <= L["bottom"] + 1e-9:
                        nm, cls = L["name"], L["cls"]
                        break
                if not nm and h["layers"]:
                    nm, cls = h["layers"][-1]["name"], h["layers"][-1]["cls"]
            grp.append({"hole": no, "depth": round(d, 2), "layerName": nm, "cls": cls})

    def _dedup(rows):
        seen, out = set(), []
        for r in rows:
            k = (r["hole"], r["depth"])
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
        return out

    spt_agg, dpt_agg = {}, {}
    for r in _dedup(raw_spt):
        band = 0 if r["depth"] <= 20 else (1 if r["depth"] <= 50 else 2)
        k = (r["layerName"], r["cls"], band)
        spt_agg[k] = spt_agg.get(k, 0) + 1
    for r in _dedup(raw_dpt):
        band = 0 if r["depth"] <= 10 else (1 if r["depth"] <= 20 else (2 if r["depth"] <= 30 else (3 if r["depth"] <= 40 else 4)))
        k = (r["layerName"], r["cls"], band)
        dpt_agg[k] = dpt_agg.get(k, 0) + 1

    spt = [{"layerName": k[0], "cls": k[1], "band": k[2], "count": v,
            "kind": "spt"} for k, v in sorted(spt_agg.items(), key=lambda x: (x[0][2], x[0][0]))]
    dpt = [{"layerName": k[0], "cls": k[1], "band": k[2], "meters": v,
            "kind": "dpt_heavy"} for k, v in sorted(dpt_agg.items(), key=lambda x: (x[0][2], x[0][0]))]

    def natkey(s):
        return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s))]
    holes_list = [holes[k] for k in sorted(holes.keys(), key=natkey)]
    return {
        "holes": holes_list,
        "spt": spt,
        "dpt": dpt,
        "names": [{"name": k, "count": v, "cls": guess_class(k, name_class)}
                  for k, v in sorted(names.items(), key=lambda x: -x[1])],
        "log": log,
        "sheets": [n for n, _ in tables],
        "summary": {
            "holes": len(holes_list),
            "totalDepth": round(sum(h["depth"] for h in holes_list), 2),
            "layers": sum(len(h["layers"]) for h in holes_list),
            "spt": sum(x["count"] for x in spt),
            "dpt": sum(x["meters"] for x in dpt),
        },
    }
