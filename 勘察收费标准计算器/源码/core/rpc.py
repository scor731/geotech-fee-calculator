# -*- coding: utf-8 -*-
"""
本地 HTTP 服务：既提供前端静态资源，也提供 JSON-RPC 接口。

之所以不用 pywebview 自带的 js_api 桥接：在 --onefile 打包环境下，
pywebview 把 Python 方法挂载到 window.pywebview.api 的时机不稳定（有时永不挂载），
表现为界面静态骨架能显示、但所有数据都必须依赖的那次启动调用拿不到 API。
改成同源 HTTP 之后，前端只要 fetch 就能用，不再有注入竞态。

只监听 127.0.0.1 的随机端口，外部无法访问；进程退出即释放。
"""
import json
import os
import threading
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

WEB_DIR = None
API = None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB_DIR, **kw)

    # 静音访问日志
    def log_message(self, fmt, *args):
        pass

    def end_headers(self):
        # 避免 WebView2 缓存旧版前端资源
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path in ("/", ""):
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] != "/rpc":
            self.send_error(404, "Not Found")
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            name = req.get("method") or ""
            args = req.get("args") or []
            fn = getattr(API, name, None)
            if name.startswith("_") or not callable(fn):
                raise ValueError("未知接口：%s" % name)
            payload = {"ok": True, "data": fn(*args)}
        except Exception:
            payload = {"ok": False, "error": _brief_error()}
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass


def _brief_error():
    tb = traceback.format_exc()
    lines = [l for l in tb.strip().splitlines() if l.strip()]
    return lines[-1] if lines else "调用失败"


def start(api, web_dir):
    """启动服务，返回 (端口, server)。失败时抛异常由调用方处理。"""
    global API, WEB_DIR
    API = api
    WEB_DIR = web_dir
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    t.start()
    return port, srv
