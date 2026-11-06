# -*- coding: utf-8 -*-
"""
层号显示格式

界面录入用「数字」：主层编号 1、2、3…，亚层编号 1、2…（理正 TCZCBH / TCYCBH 口径）。
导出 Word / Excel 时按勘察报告惯例显示成圈码：①、①1、⑥1。

本模块只负责格式转换，不参与计算。
"""

CIRCLE = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def _circ(n):
    """1 -> ①；超出 20 用 (21)"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    return CIRCLE[n - 1] if n <= len(CIRCLE) else "(%d)" % n


def layer_no(code, sub=""):
    """主层编号 + 亚层编号 -> 报告用层号

    layer_no("1")        -> "①"
    layer_no("1", "1")   -> "①1"
    layer_no("6", "1-1") -> "⑥1-1"
    """
    code = str(code or "").strip()
    sub = str(sub or "").strip()
    return (_circ(code) or code) + sub


def parse(raw):
    """把各种来源的层号拆成 (主层编号, 亚层编号)

    支持 "1"、"1-1"、"①"、"①1"、"⑥1-1"、"1.1"
    """
    s = str(raw or "").strip()
    if not s:
        return "", ""
    if s[0] in CIRCLE:                 # 圈码开头：①、①1、⑥1-1
        main = str(CIRCLE.index(s[0]) + 1)
        rest = s[1:].strip()
    else:                              # 数字开头：1、1-1、1.1
        head = ""
        j = 0
        while j < len(s) and (s[j].isdigit() or s[j] in "-."):
            head += s[j]
            j += 1
        if not head:
            return s, ""
        parts = head.replace(".", "-").replace("--", "-").split("-")
        main = parts[0]
        rest = "-".join(parts[1:]) + s[j:]
    rest = rest.lstrip("-—. ").strip()
    return main, rest


def hole_layer_no(raw):
    """钻孔分层记录里的层号（理正原始 "6-1" / "①" 等）转报告层号"""
    main, sub = parse(raw)
    if not main:
        return ""
    return (_circ(main) or main) + sub
