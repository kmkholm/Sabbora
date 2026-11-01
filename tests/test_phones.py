"""Phones and browsers: QR codes, the web pages, a browser student and the teacher remote.

The WebSocket side is driven with QWebSocket speaking exactly what the pages send.
Key presses for the remote are recorded, never injected into this PC.
"""
import io
import os
import sys
import time
import urllib.request
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PyQt5.QtCore import QCoreApplication, QUrl  # noqa: E402
from PyQt5.QtWebSockets import QWebSocket  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

from sabbora import common as C  # noqa: E402
from sabbora import qr  # noqa: E402
from sabbora import teacher as T  # noqa: E402

PORT = 47960
KEYS = []


def pump(cond, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


class Browser:
    """What the student / remote web pages do, minus the HTML."""

    def __init__(self, port):
        self.texts, self.frames = [], []
        self.ws = QWebSocket()
        self.ws.textMessageReceived.connect(lambda t: self.texts.append(C.jload(t)))
        self.ws.binaryMessageReceived.connect(self._bin)
        self.ws.open(QUrl(f"ws://127.0.0.1:{port}/"))
        assert pump(lambda: self.ws.state() == 3), "websocket did not open"   # ConnectedState

    def _bin(self, qba):
        data = qba.data()
        if data[0] == C.B_BROADCAST:
            self.frames.append(data[1:])
            self.send({"t": "ack_b"})

    def send(self, obj):
        self.ws.sendTextMessage(C.jdump(obj))

    def got(self, kind):
        return [m for m in self.texts if m and m.get("t") == kind]


@pytest.fixture(scope="module")
def room():
    app = QApplication.instance() or QApplication([])
    mp = pytest.MonkeyPatch()
    mp.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))

    class A:
        port = PORT
        server = ""
        code = ""
        name = ""
        auto = False

    tw = T.TeacherWindow(A)
    tw.chk_min.setChecked(False)
    tw.injector = SimpleNamespace(key=lambda vk, down, text="": KEYS.append((vk, down)))
    yield SimpleNamespace(app=app, tw=tw)
    if tw.caster.isRunning():
        tw.caster.stop()
    tw.server.close_all()
    tw.web.stop()
    for t in [t for t in tw.tiles.values() if (t.seat and t.seat.kind == "web") or t.info.get("kind") == "web"]:
        t.seat, t.online = None, False
        tw.remove_tiles([t])
    mp.undo()


def test_qr_codes_decode():
    cv2 = pytest.importorskip("cv2")
    import numpy as np
    det = cv2.QRCodeDetector()
    for text in ("http://192.168.1.10:47080/?c=4821", "http://10.20.30.40:47081/remote#pin=004215",
                 "http://172.16.254.1:47080/?c=99999999&extra=" + "x" * 60):
        val, _pts, _ = det.detectAndDecode(np.array(qr.qr_image(text)))
        assert val == text


def test_web_pages_are_served(room):
    tw = room.tw
    assert tw.web_port
    base = f"http://127.0.0.1:{tw.web_port}"
    page = urllib.request.urlopen(base + "/?c=1234", timeout=5).read().decode("utf-8")
    assert f"const WS_PORT = {tw.port}," in page and "Sabbora" in page
    remote = urllib.request.urlopen(base + "/remote", timeout=5).read().decode("utf-8")
    assert "role:\"remote\"" in remote
    icon = urllib.request.urlopen(base + "/icon.png", timeout=5).read()
    assert icon[:4] == b"\x89PNG"
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(base + "/../../etc/passwd", timeout=5)


def test_phones_dialog_qr(room):
    tw = room.tw
    tw.show_phones()
    dlg = tw.phones_dlg
    s_url, r_url = dlg.urls()
    assert f"?c={tw.code}" in s_url and f"#pin={tw.server.remote_pin}" in r_url
    assert dlg.qr_students.pixmap() is not None and not dlg.qr_students.pixmap().isNull()
    assert dlg.qr_remote.pixmap() is None or dlg.qr_remote.pixmap().isNull(), "remote code hidden by default"
    dlg.btn_reveal.setChecked(True)
    assert not dlg.qr_remote.pixmap().isNull()
    dlg.btn_reveal.setChecked(False)
    dlg.close()


def test_browser_student_joins_and_sees_lecture(room):
    tw = room.tw
    b = Browser(tw.port)
    b.send({"t": "hello", "id": "web-test1", "name": "Phone Student", "code": tw.code, "host": "Android phone",
            "kind": "web", "ver": C.VERSION})
    assert pump(lambda: b.got("welcome"))
    seat = tw.server.students["web-test1"]
    assert seat.kind == "web"
    assert "📱" in tw.tiles["web-test1"].badges.text()
    room.browser, room.seat = b, seat
    # a still image (e.g. a phone photo) shown to the class reaches the browser
    from PIL import Image
    path = os.path.join(C.data_dir(), "test_slide.png")
    Image.new("RGB", (800, 450), "#0E7C86").save(path)
    tw.show_photo(path)
    assert pump(lambda: b.frames), "browser receives the shared image"
    os.remove(path)
    tw.stop_cast()
    assert pump(lambda: b.got("bstop"))


def test_browser_student_hand_vote_and_submission(room):
    tw, b, seat = room.tw, room.browser, room.seat
    b.send({"t": "hand", "up": True})
    assert pump(lambda: seat.hand)
    payload = os.urandom(C.FILE_CHUNK + 777)
    b.send({"t": "up_begin", "fid": 1, "name": "photo.jpg", "size": len(payload), "chunks": 2})
    pump(lambda: False, 0.2)
    b.ws.sendBinaryMessage(C.pack_chunk(C.B_UPLOAD, 1, 0, payload[:C.FILE_CHUNK]))
    b.ws.sendBinaryMessage(C.pack_chunk(C.B_UPLOAD, 1, 1, payload[C.FILE_CHUNK:]))
    assert pump(lambda: len(b.got("up_ack")) == 2)
    b.send({"t": "up_end", "fid": 1})
    assert pump(lambda: b.got("up_ok"))
    folder = tw.server.submissions_dir()
    got = [f for f in os.listdir(folder) if f.startswith("Phone Student")]
    with open(os.path.join(folder, got[-1]), "rb") as f:
        assert f.read() == payload
    for f in got:
        os.remove(os.path.join(folder, f))
    try:
        os.removedirs(folder)
    except OSError:
        pass
    tw.open_viewer(seat.sid)          # phones cannot be watched: must not crash or open a viewer
    assert seat.sid not in tw.viewers


def test_remote_wrong_pin_rejected(room):
    r = Browser(room.tw.port)
    r.send({"t": "hello", "role": "remote", "pin": "not-the-pin", "id": "r-bad"})
    assert pump(lambda: r.got("reject"))
    assert not room.tw.server.remotes


def test_remote_controls_the_lecture(room):
    tw = room.tw
    r = Browser(tw.port)
    r.send({"t": "hello", "role": "remote", "pin": tw.server.remote_pin, "id": "r-good"})
    assert pump(lambda: r.got("welcome_remote"))
    assert len(tw.server.remotes) == 1 and len(tw.all_seats()) == 1, "the remote is not a student"
    r.send({"t": "cmd", "c": "next"})
    r.send({"t": "cmd", "c": "prev"})
    assert pump(lambda: (0x27, True) in KEYS and (0x25, True) in KEYS), "slide keys pressed on the teacher PC"
    r.send({"t": "cmd", "c": "timer", "min": 3})
    assert pump(lambda: room.browser.got("timer"))
    assert room.browser.got("timer")[-1]["seconds"] == 180
    r.send({"t": "cmd", "c": "lock"})
    assert pump(lambda: room.browser.got("lock"))
    r.send({"t": "cmd", "c": "unlock"})
    assert pump(lambda: room.browser.got("unlock"))
    assert pump(lambda: r.got("state") and r.got("state")[-1]["online"] == 1), "live state on the phone"
    # photo taken on the phone is shown to the whole class
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (1200, 900), "#E11D48").save(buf, "JPEG")
    data = buf.getvalue()
    n_before = len(room.browser.frames)
    r.send({"t": "up_begin", "fid": 7, "name": "board.jpg", "size": len(data), "chunks": 1, "purpose": "show"})
    pump(lambda: False, 0.2)
    r.ws.sendBinaryMessage(C.pack_chunk(C.B_UPLOAD, 7, 0, data))
    assert pump(lambda: r.got("up_ack"))
    r.send({"t": "up_end", "fid": 7})
    assert pump(lambda: tw.photo_mode and len(room.browser.frames) > n_before), "students see the phone photo"
    assert pump(lambda: r.frames), "the phone previews what is shared"
    r.send({"t": "cmd", "c": "stop"})
    assert pump(lambda: not tw.server.b_active and not tw.photo_mode)
