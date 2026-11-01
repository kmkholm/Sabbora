"""Tiny HTTP server inside the teacher console.

It serves two self-contained pages; everything after loading the page goes
over the class WebSocket (same protocol as the desktop student app):
  /         student page for phones, tablets and any browser (no install)
  /remote   teacher remote control (needs the private PIN)
"""
import io
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import common as C
from . import webpages

WEB_PORT = 47080


class _ExclusiveHTTPServer(ThreadingHTTPServer):
    """On Windows SO_REUSEADDR lets two servers share a port; never allow that."""
    allow_reuse_address = False

    def server_bind(self):
        import socket
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def _icon_png():
    from PIL import Image, ImageDraw
    s = 192
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((s * .04, s * .10, s * .96, s * .80), radius=s * .10, fill="#9A6A3A")
    d.rounded_rectangle((s * .11, s * .17, s * .89, s * .73), radius=s * .06, fill="#1E4D3A")
    d.line([(s * .20, s * .62), (s * .36, s * .44), (s * .50, s * .54), (s * .70, s * .30)],
           fill="#F4F1E8", width=int(s * .055), joint="curve")
    r = s * .07
    d.ellipse((s * .70 - r, s * .30 - r, s * .70 + r, s * .30 + r), fill="#F2A541")
    d.rectangle((s * .30, s * .80, s * .37, s * .94), fill="#9A6A3A")
    d.rectangle((s * .63, s * .80, s * .70, s * .94), fill="#9A6A3A")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class WebServer:
    def __init__(self, ws_port):
        self.ws_port = ws_port
        self.port = 0
        self._httpd = None
        self._icon = _icon_png()

    def start(self, port=WEB_PORT):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (http.server API)
                path = self.path.split("?")[0].split("#")[0]
                if path in ("/", "/index.html"):
                    body, ctype = outer.page(webpages.STUDENT_HTML), "text/html; charset=utf-8"
                elif path in ("/remote", "/remote.html"):
                    body, ctype = outer.page(webpages.REMOTE_HTML), "text/html; charset=utf-8"
                elif path in ("/icon.png", "/favicon.ico", "/apple-touch-icon.png"):
                    body, ctype = outer._icon, "image/png"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        for p in range(port, port + 20):
            try:
                self._httpd = _ExclusiveHTTPServer(("0.0.0.0", p), Handler)
            except OSError:
                continue
            self._httpd.daemon_threads = True
            self.port = p
            threading.Thread(target=self._httpd.serve_forever, name="sabbora-web", daemon=True).start()
            return p
        return 0

    def page(self, html):
        return (html.replace("%%WS_PORT%%", str(self.ws_port))
                    .replace("%%LANG%%", C.LANG)
                    .replace("%%VERSION%%", C.VERSION)).encode("utf-8")

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
