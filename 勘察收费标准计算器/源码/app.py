# -*- coding: utf-8 -*-
"""
工程勘察收费标准计算器（单机版）
依据：国家计委、建设部《工程勘察设计收费标准》（2002年修订本）计价格[2002]10号
"""
import base64
import json
import os
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from core import engine, exporter, lizheng, report, rpc, standards  # noqa: E402
from core import version as V  # noqa: E402


def res_path(*parts):
    base = getattr(sys, "_MEIPASS", HERE)
    return os.path.join(base, *parts)


def desktop_dir():
    d = os.path.join(os.path.expanduser("~"), "Desktop")
    return d if os.path.isdir(d) else os.path.expanduser("~")


def _safe_name(s):
    bad = '\\/:*?"<>|'
    for b in bad:
        s = s.replace(b, "_")
    return s.strip() or "未命名工程"


class Api:
    def __init__(self):
        self.win = None
        self.last_dir = desktop_dir()

    # ---------------- 基础数据 ----------------
    def get_standards(self):
        d = standards.to_json()
        d["version"] = {"version": V.APP_VERSION, "author": V.APP_AUTHOR,
                        "tag": V.VERSION_TAG, "title": V.WINDOW_TITLE}
        return d

    def calc(self, state):
        try:
            return {"ok": True, "data": engine.compute(state or {})}
        except Exception as e:
            return {"ok": False, "error": str(e), "trace": traceback.format_exc()}

    # ---------------- 目录/文件 ----------------
    def default_dir(self):
        return {"dir": self.last_dir or desktop_dir()}

    def pick_dir(self, current=None):
        try:
            import webview
            d = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG,
                                                      directory=current or self.last_dir)
            if d:
                p = d[0] if isinstance(d, (list, tuple)) else d
                self.last_dir = p
                return {"ok": True, "dir": p}
            return {"ok": False, "cancel": True, "dir": current or self.last_dir}
        except Exception as e:
            return {"ok": False, "error": str(e), "dir": current or self.last_dir}

    def open_path(self, path):
        try:
            p = path
            if os.path.isfile(p):
                p = os.path.dirname(p)
            if os.path.isdir(p):
                os.startfile(p)  # noqa
                return {"ok": True}
            return {"ok": False, "error": "路径不存在：%s" % path}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---------------- 导出 ----------------
    def export_excel(self, payload):
        try:
            state = payload.get("state") or {}
            folder = payload.get("dir") or self.last_dir
            name = payload.get("filename") or ""
            if not name:
                pname = (state.get("meta") or {}).get("project") or "工程勘察"
                name = "%s_勘察费用计算书_%s.xlsx" % (_safe_name(pname)[:40], time.strftime("%Y%m%d"))
            if not name.lower().endswith((".xlsx",)):
                name += ".xlsx"
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, name)
            res = engine.compute(state)
            exporter.export(state, res, path)
            self.last_dir = folder
            return {"ok": True, "path": path}
        except Exception as e:
            return {"ok": False, "error": str(e), "trace": traceback.format_exc()}

    # ---------------- 报告 ----------------
    def export_report(self, payload):
        try:
            state = payload.get("state") or {}
            folder = payload.get("dir") or self.last_dir
            name = payload.get("filename") or ""
            mode_cn = "结算" if state.get("mode") == "settle" else "预算"
            if not name:
                pname = (state.get("meta") or {}).get("project") or "工程勘察"
                name = "%s_勘察费%s报告_%s.docx" % (_safe_name(pname)[:40], mode_cn, time.strftime("%Y%m%d"))
            if not name.lower().endswith(".docx"):
                name += ".docx"
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, name)
            res = engine.compute(state)
            report.export_report(state, res, path)
            self.last_dir = folder
            return {"ok": True, "path": path}
        except Exception as e:
            return {"ok": False, "error": str(e), "trace": traceback.format_exc()}

    # ---------------- 项目存取 ----------------
    def save_project(self, payload):
        try:
            state = payload.get("state") or {}
            folder = payload.get("dir") or self.last_dir
            name = payload.get("filename") or ""
            if not name:
                pname = (state.get("meta") or {}).get("project") or "工程勘察"
                name = "%s_勘察计价_%s.kcsj" % (_safe_name(pname)[:40], time.strftime("%Y%m%d"))
            if not name.lower().endswith(".kcsj"):
                name += ".kcsj"
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, name)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=1)
            self.last_dir = folder
            return {"ok": True, "path": path}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def load_project(self, payload):
        try:
            b64 = payload.get("b64")
            raw = base64.b64decode(b64.split(",")[-1])
            state = json.loads(raw.decode("utf-8-sig"))
            return {"ok": True, "state": state}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---------------- 理正导入 ----------------
    def parse_lizheng(self, payload):
        tmp = None
        try:
            b64 = (payload.get("b64") or "").split(",")[-1]
            fname = payload.get("name") or "lizheng.dat"
            raw = base64.b64decode(b64)
            ext = os.path.splitext(fname)[1] or ".dat"
            fd, tmp = tempfile.mkstemp(suffix=ext)
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
            data = lizheng.parse(tmp, payload.get("nameClass"))
            data["ok"] = True
            return data
        except Exception as e:
            return {"ok": False, "error": str(e), "trace": traceback.format_exc()}
        finally:
            try:
                if tmp and os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def app_info(self):
        return {
            "version": V.APP_VERSION,
            "exe": sys.executable,
            "frozen": bool(getattr(sys, "frozen", False)),
            "dir": self.last_dir,
        }


def main():
    import logging
    import webview

    # pywebview 在非 UI 线程读取 WinForms 属性会打印大量 COM 告警，功能不受影响，这里降噪
    logging.getLogger("pywebview").setLevel(logging.CRITICAL)

    api = Api()
    # 前端资源与接口都由本地服务提供，避免 pywebview js_api 注入时机不稳的问题
    port, _srv = rpc.start(api, res_path("web"))
    url = "http://127.0.0.1:%d/index.html" % port

    # 依屏幕尺寸限定初始窗口，避免小屏溢出
    sw, sh = 1600, 1000
    try:
        sc = webview.screens[0]
        sw, sh = sc.width, sc.height
    except Exception:
        pass
    w = min(1500, int(sw * 0.94))
    h = min(940, int(sh * 0.92))

    window = webview.create_window(
        V.WINDOW_TITLE,
        url=url,
        js_api=None,
        width=w, height=h,
        min_size=(1080, 660),
        background_color="#F4F6FA",
    )
    api.win = window

    # 打包自检探针：设置 KCSJ_PROBE=<目录> 时，后台抓取前端运行状态并实测一次导出
    probe_dir = os.environ.get("KCSJ_PROBE")
    if probe_dir:
        import threading

        def _write(txt, mode="a"):
            try:
                with open(os.path.join(probe_dir, "probe.log"), mode, encoding="utf-8") as f:
                    f.write(txt + "\n")
            except Exception:
                pass

        def _probe():
            time.sleep(7)
            js = ("(function(){try{return JSON.stringify({log:window.__kc||[],"
                  "centerLen:((document.querySelector('#center')||{}).innerHTML||'').length,"
                  "asidLen:((document.querySelector('aside.right')||{}).innerHTML||'').length,"
                  "footLen:((document.querySelector('.foot')||{}).innerText||'').length,"
                  "bodyLen:document.body.innerText.length})}catch(e){return 'ERR '+e.message}})()")
            try:
                _write("[1] " + str(window.evaluate_js(js)))
            except Exception:
                _write("[1] ERROR " + traceback.format_exc(limit=2))

            # 用页面自身发起一次导出，验证 WebView2 → 本地服务的同源调用链
            pdir = probe_dir.replace("\\", "/")
            fire = ("window.__kcExp='pending';(function(){try{"
                    "api.export_excel({state:S,dir:'%s',filename:'ui_export.xlsx'})"
                    ".then(function(r){window.__kcExp=JSON.stringify(r);})"
                    ".catch(function(e){window.__kcExp='ERR '+(e&&e.message);});"
                    "api.export_report({state:S,dir:'%s',filename:'ui_report.docx'})"
                    ".then(function(r){window.__kcRep=JSON.stringify(r);})"
                    ".catch(function(e){window.__kcRep='ERR '+(e&&e.message);});"
                    "return 'fired';}catch(e){window.__kcExp='THROW '+e.message;return 'throw';}})()"
                    % (pdir, pdir))
            try:
                _write("[2] " + str(window.evaluate_js(fire)))
            except Exception:
                _write("[2] ERROR " + traceback.format_exc(limit=2))

            time.sleep(6)
            try:
                _write("[3] " + str(window.evaluate_js("String(window.__kcExp)")))
                _write("[3b] " + str(window.evaluate_js("String(window.__kcRep)")))
            except Exception:
                _write("[3] ERROR " + traceback.format_exc(limit=2))
            try:
                _write("[4] 导出文件存在=" + str(os.path.exists(os.path.join(probe_dir, "ui_export.xlsx")))
                       + " 报告存在=" + str(os.path.exists(os.path.join(probe_dir, "ui_report.docx"))))
            except Exception:
                pass

        threading.Thread(target=_probe, daemon=True).start()

    webview.start(gui="edgechromium", private_mode=False, storage_path=os.path.join(
        os.path.expanduser("~"), ".kcsj2002"))


if __name__ == "__main__":
    # 打包自检：设置 KCSJ_SELFTEST=<目录> 时，不启动界面，直接跑一遍导出并写日志
    _st = os.environ.get("KCSJ_SELFTEST")
    if _st:
        log = []
        try:
            api = Api()
            state = {
                "meta": {"project": "自检工程", "owner": "自检", "unit": "自检"},
                "grade": "甲级",
                "layers": [{"code": "1", "name": "素填土", "cls": 1, "bottom": 2},
                           {"code": "2", "name": "圆砾", "cls": 3, "bottom": 10},
                           {"code": "2", "sub": "1", "name": "溶洞", "cls": 3, "bottom": 0}],
                "holeTypes": [{"name": "控制孔", "count": 2, "depth": 18},
                              {"name": "鉴别孔", "count": 2, "depth": 12}],
                "coefSoil": ["pipe"], "sample": {"undist": {"count": 6, "device": "hammer", "band": 0},
                                                 "core": 3, "point": 4},
                "lab": {"items": [{"name": "常规土工样", "unit": "件", "price": 169, "qty": 6}]},
                "geo": {"wave": {"holes": 1, "depth": 18, "testLen": 15, "method": "single", "byDeepest": True}},
                "otherTest": [{"kind": "cpt", "cls": 2, "depth": 15, "tip": "double", "pore": True, "qty": 20},
                              {"kind": "packer", "sub": "pack_gt20", "qty": 2},
                              {"kind": "packer", "sub": "inj_hole", "qty": 1}],
                "coord": {"days": 2, "price": 1000},
                "other": {"kantan": 1, "yanzao": 2, "report": 2},
                "survey": {"items": [{"id": "gps_e", "complex": 1, "qty": 4, "price": 0},
                                     {"id": "terr_500_b", "complex": 1, "qty": 0.05, "price": 0},
                                     {"id": "tri_2", "complex": 2, "qty": 3, "price": 0}],
                           "coefs": ["sv_band"]},
            }
            log.append("standards=%d" % len(api.get_standards()["tables"]))
            r = api.export_excel({"state": state, "dir": _st, "filename": "selftest.xlsx"})
            log.append("export=%s" % json.dumps(r, ensure_ascii=False))
            r3 = api.export_report({"state": state, "dir": _st, "filename": "selftest.docx"})
            log.append("report=%s" % json.dumps(r3, ensure_ascii=False))
            r2 = api.calc(state)
            log.append("calc_ok=%s total=%s" % (r2.get("ok"), r2.get("data", {}).get("totals", {}).get("final")))
            # 可选：顺带验证理正备份库解析（KCSJ_SELFTEST_MDB 指向 .mdb 文件）
            mdb = os.environ.get("KCSJ_SELFTEST_MDB")
            if mdb and os.path.exists(mdb):
                with open(mdb, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                r4 = api.parse_lizheng({"name": os.path.basename(mdb), "b64": b64})
                log.append("mdb=%s" % json.dumps(
                    {"ok": r4.get("ok"), "summary": r4.get("summary"),
                     "error": r4.get("error")}, ensure_ascii=False))
        except Exception:
            log.append("ERROR\n" + traceback.format_exc())
        with open(os.path.join(_st, "selftest.log"), "w", encoding="utf-8") as f:
            f.write("\n".join(log))
        sys.exit(0)
    main()
