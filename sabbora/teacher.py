"""Sabbora teacher console.

Broadcast the teacher's screen, watch every student's screen live, take
remote control, lock screens, send messages, links, programs and files, run
quick polls, take attendance and power the lab on or off.
"""
import argparse
import csv
import datetime
import json
import os
import random
import socket
import sys
import time

from PyQt5.QtCore import QEvent, QObject, QPoint, QRect, QSettings, QStandardPaths, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap
from PyQt5.QtNetwork import QAbstractSocket, QHostAddress, QNetworkInterface, QUdpSocket
from PyQt5.QtWebSockets import QWebSocketServer
from PyQt5.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout,
                             QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
                             QScrollArea, QShortcut, QSlider, QSpinBox, QSplitter, QVBoxLayout, QWidget)

from . import common as C
from . import icons
from .teacher_tools import AnnotationBar, AnnotationOverlay, PhonesDialog, PickDialog, WindowPicker, screen_for_monitor
from .webserver import WebServer

def quality_presets():
    return [
    (C.L("متوسط — مناسب لمعظم الشبكات", "Medium — suits most networks"), 1600, 65, False),
    (C.L("منخفض — شبكة لاسلكية ضعيفة", "Low — weak Wi-Fi"), 1280, 50, False),
    (C.L("عالٍ", "High"), 1920, 80, False),
    (C.L("نص حاد — شرائح وأكواد", "Sharp text — slides and code"), 1920, 85, True),
    (C.L("الدقة الأصلية", "Original resolution"), 0, 88, True),
    ]


def view_presets():
    return [
    (C.L("عالٍ", "High"), 1600, 70, False),
    (C.L("متوسط", "Medium"), 1280, 60, False),
    (C.L("نص حاد", "Sharp text"), 1920, 85, True),
    ]


def power_labels():
    return {"shutdown": C.L("إيقاف التشغيل", "Shut down"), "restart": C.L("إعادة التشغيل", "Restart"), "logoff": C.L("تسجيل الخروج", "Log off")}

# Qt key -> Windows virtual key, used when the native code is unavailable.
QT_TO_VK = {
    Qt.Key_Backspace: 0x08, Qt.Key_Tab: 0x09, Qt.Key_Backtab: 0x09, Qt.Key_Return: 0x0D, Qt.Key_Enter: 0x0D,
    Qt.Key_Shift: 0x10, Qt.Key_Control: 0x11, Qt.Key_Alt: 0x12, Qt.Key_Escape: 0x1B, Qt.Key_Space: 0x20,
    Qt.Key_PageUp: 0x21, Qt.Key_PageDown: 0x22, Qt.Key_End: 0x23, Qt.Key_Home: 0x24, Qt.Key_Left: 0x25,
    Qt.Key_Up: 0x26, Qt.Key_Right: 0x27, Qt.Key_Down: 0x28, Qt.Key_Insert: 0x2D, Qt.Key_Delete: 0x2E,
    Qt.Key_Meta: 0x5B, Qt.Key_CapsLock: 0x14,
}
QT_TO_VK.update({getattr(Qt, f"Key_F{i}"): 0x6F + i for i in range(1, 13)})
QT_TO_VK.update({getattr(Qt, f"Key_{c}"): ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"})


# ==========================================================================
# Teacher screen capture thread
# ==========================================================================
class ScreenBroadcaster(QThread):
    frame_ready = pyqtSignal(object)
    failed = pyqtSignal(str)
    window_lost = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fps = 10
        self.max_width = 1600
        self.quality = 65
        self.sharp = False
        self.monitor = None
        self.source = ("mon", None)      # ("mon", monitor) | ("win", hwnd) | ("ppt", None)
        self.area = None                 # last captured rect (x, y, w, h, primary)
        self._ppt = (0.0, None)
        self.pointer = True
        self.paused = False
        self.layered = False
        self._running = False
        self._force = True

    def request_keyframe(self):
        self._force = True

    def stop(self):
        self._running = False
        self.wait(3000)

    def _capture(self):
        kind, val = self.source
        if kind == "mon":
            mon = val or C.list_monitors()[0]
            return C.grab_monitor(mon, self.layered), mon
        hwnd = val
        if kind == "ppt":
            now = time.monotonic()
            if now - self._ppt[0] > 1.0:     # follow the slide show as it starts and ends
                self._ppt = (now, C.find_powerpoint())
            hwnd = self._ppt[1]
            if not hwnd:
                mon = C.list_monitors()[0]
                return C.grab_monitor(mon, self.layered), mon
        elif not C.is_window(hwnd):
            self.source = ("mon", None)
            self.window_lost.emit()
            mon = C.list_monitors()[0]
            return C.grab_monitor(mon, self.layered), mon
        res = C.grab_window_area(hwnd) if self.layered else C.grab_window(hwnd)
        return res if res else (None, None)

    def run(self):
        self._running = True
        self._force = True
        prev_raw, prev_pos = None, None
        while self._running:
            t0 = time.perf_counter()
            if not self.paused:
                try:
                    img, mon = self._capture()
                    if img is None:                  # window minimised: keep the last frame
                        time.sleep(0.2)
                        continue
                    self.area = mon
                    raw = img.tobytes()
                    pos = C.cursor_pos(mon) if self.pointer else None
                    if self._force or pos != prev_pos or raw != prev_raw:
                        self._force = False
                        prev_raw, prev_pos = raw, pos
                        if pos:
                            C.draw_pointer(img, mon, pos)
                        self.frame_ready.emit(C.encode_jpeg(img, self.max_width, self.quality, self.sharp))
                except Exception as exc:  # capture can fail briefly (UAC desktop, lock screen)
                    self.failed.emit(str(exc))
                    time.sleep(0.5)
            time.sleep(max(0.005, 1.0 / max(1, self.fps) - (time.perf_counter() - t0)))


# ==========================================================================
# Network side
# ==========================================================================
class Seat:
    """One connected student."""

    def __init__(self, sock):
        self.sock = sock
        self.sid = None
        self.name = ""
        self.host = ""
        self.user = ""
        self.os = ""
        self.mac = ""
        self.ip = C.clean_ip(sock.peerAddress().toString())
        self.alive = True
        self.hand = False
        self.locked = False
        self.watching = False
        self.b_waiting = False
        self.b_sent_seq = -1
        self.b_sent_at = 0.0
        self.focus = set()
        self.files = {}
        self.uploads = {}
        self.win = ""
        self.role = "student"           # or "remote" (teacher's phone)
        self.kind = "desktop"           # or "web" (phone / browser student)


class FileJob:
    def __init__(self, fid, name, data):
        self.fid = fid
        self.name = name
        self.data = data
        self.chunks = (len(data) + C.FILE_CHUNK - 1) // C.FILE_CHUNK


class ClassServer(QObject):
    joined = pyqtSignal(object)
    left = pyqtSignal(object)
    thumb = pyqtSignal(object, object)
    frame = pyqtSignal(object, object)
    notice = pyqtSignal(object, str, object)

    def __init__(self, code, course, parent=None):
        super().__init__(parent)
        self.code = code
        self.course = course
        self.port = 0
        self.ws = QWebSocketServer("Sabbora", QWebSocketServer.NonSecureMode, self)
        self.ws.newConnection.connect(self._on_new)
        self.pending = set()
        self.students = {}
        self.remotes = {}
        self.remote_pin = ""
        self.b_active = False
        self.b_mode = "full"
        self.b_latest = None
        self.b_seq = 0
        self.b_exclude = None
        self.bytes_out = 0
        self.thumb_interval = 1.5
        self.thumb_width = 360
        self._fid = 0

    def listen(self, port):
        for p in range(port, port + 20):
            if self.ws.listen(QHostAddress.Any, p):
                self.port = p
                return p
        return 0

    # ---------------------------------------------------------------- sockets
    def _on_new(self):
        while self.ws.hasPendingConnections():
            sock = self.ws.nextPendingConnection()
            st = Seat(sock)
            self.pending.add(st)
            sock.textMessageReceived.connect(lambda txt, st=st: self._on_text(st, txt))
            sock.binaryMessageReceived.connect(lambda data, st=st: self._on_binary(st, data))
            sock.disconnected.connect(lambda st=st: self._on_closed(st))
            QTimer.singleShot(10000, lambda st=st: st.sid is None and st.alive and st.sock.close())

    def _on_closed(self, st):
        if not st.alive:
            return
        st.alive = False
        self.pending.discard(st)
        for rec in st.uploads.values():          # unfinished submission
            try:
                rec["f"].close()
                os.remove(rec["path"])
            except OSError:
                pass
        st.uploads.clear()
        if st.role == "remote":
            if self.remotes.get(st.sid) is st:
                del self.remotes[st.sid]
                self.notice.emit(st, "remote_left", None)
        elif st.sid and self.students.get(st.sid) is st:
            del self.students[st.sid]
            self.left.emit(st)
        st.sock.deleteLater()

    def _on_text(self, st, txt):
        msg = C.jload(txt)
        if not msg:
            return
        t = msg.get("t")
        if st.sid is None:
            if t == "hello":
                self._hello(st, msg)
            return
        if st.role == "remote":
            if t == "ack_b":
                st.b_waiting = False
                self._push_broadcast(st)
            elif t == "cmd":
                self.notice.emit(st, "cmd", msg)
            elif t == "up_begin":
                self._up_begin(st, msg)
            elif t == "up_end":
                self._up_end(st, msg)
            return
        if t == "ack_b":
            st.b_waiting = False
            self._push_broadcast(st)
        elif t == "file_ack":
            self._file_ack(st, msg)
        elif t == "hand":
            st.hand = bool(msg.get("up"))
            self.notice.emit(st, "hand", None)
        elif t == "status":
            st.locked = bool(msg.get("locked", st.locked))
            st.watching = bool(msg.get("watching", st.watching))
            if "win" in msg:
                st.win = str(msg.get("win") or "")[:200]
            self.notice.emit(st, "status", None)
        elif t == "up_begin":
            self._up_begin(st, msg)
        elif t == "up_end":
            self._up_end(st, msg)
        elif t in ("chat", "vote", "file_ok"):
            self.notice.emit(st, t, msg)

    def _hello(self, st, msg):
        if msg.get("role") == "remote":
            self._hello_remote(st, msg)
            return
        st.kind = "web" if msg.get("kind") == "web" else "desktop"
        if str(msg.get("code", "")).strip() != self.code:
            self.send(st, {"t": "reject", "reason": "code"})
            QTimer.singleShot(400, st.sock.close)
            return
        sid = str(msg.get("id") or "")[:96] or f"anon-{st.ip}"
        old = self.students.get(sid)
        if old is not None and old is not st:
            del self.students[sid]
            old.alive = False
            self.left.emit(old)
            old.sock.close()
            old.sock.deleteLater()
        st.sid = sid
        st.name = str(msg.get("name") or C.L("طالب", "Student"))[:60]
        st.host = str(msg.get("host") or "")[:60]
        st.user = str(msg.get("user") or "")[:60]
        st.os = str(msg.get("os") or "")[:60]
        st.mac = str(msg.get("mac") or "")[:20]
        self.pending.discard(st)
        self.students[sid] = st
        self.send(st, {"t": "welcome", "course": self.course, "thumb_interval": self.thumb_interval,
                       "thumb_width": self.thumb_width})
        self.joined.emit(st)
        if self.b_active and sid != self.b_exclude:
            self.send(st, {"t": "bstart", "mode": self.b_mode})
            self._push_broadcast(st)

    def _hello_remote(self, st, msg):
        if not self.remote_pin or str(msg.get("pin", "")).strip() != self.remote_pin:
            self.send(st, {"t": "reject", "reason": "pin"})
            QTimer.singleShot(400, st.sock.close)
            return
        st.role = "remote"
        st.sid = "remote:" + str(msg.get("id") or st.ip)[:40]
        st.name = "remote"
        old = self.remotes.get(st.sid)
        if old is not None and old is not st:
            old.alive = False
            old.sock.close()
        self.pending.discard(st)
        self.remotes[st.sid] = st
        self.send(st, {"t": "welcome_remote", "course": self.course})
        self.notice.emit(st, "remote_join", None)
        if self.b_active:
            self._push_broadcast(st)

    def send_state(self, obj):
        obj = dict(obj, t="state")
        for r in list(self.remotes.values()):
            self.send(r, obj)

    def _on_binary(self, st, qba):
        data = qba.data() if hasattr(qba, "data") else bytes(qba)
        if st.sid is None or not data:
            return
        kind, body = data[0], data[1:]
        if kind == C.B_THUMB:
            self.thumb.emit(st, body)
        elif kind == C.B_FRAME:
            self.send(st, {"t": "ack_f"})
            if self.b_active and self.b_exclude == st.sid:
                self.publish(body)
            self.frame.emit(st, body)
        elif kind == C.B_UPLOAD:
            self._up_chunk(st, body)

    # ------------------------------------------------------- submissions
    def submissions_dir(self, dated=True):
        base = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or os.path.expanduser("~")
        folder = os.path.join(base, "Sabbora Submissions", C.safe_filename(self.course))
        if dated:
            folder = os.path.join(folder, datetime.date.today().isoformat())
        os.makedirs(folder, exist_ok=True)
        return folder

    def _up_begin(self, st, msg):
        try:
            fid, size = int(msg["fid"]), int(msg.get("size", 0))
        except (KeyError, TypeError, ValueError):
            return
        name = C.safe_filename(str(msg.get("name", "file")))
        if size > C.MAX_UPLOAD_BYTES:
            self.send(st, {"t": "up_reject", "fid": fid})
            return
        if st.role == "remote":
            folder = os.path.join(C.data_dir(), "phone_photos")
            os.makedirs(folder, exist_ok=True)
            path = C.unique_path(folder, name)
        else:
            path = C.unique_path(self.submissions_dir(), C.safe_filename(f"{st.name} - {name}"))
        try:
            f = open(path, "wb")
        except OSError:
            self.send(st, {"t": "up_reject", "fid": fid})
            return
        st.uploads[fid] = {"f": f, "path": path, "name": name, "n": 0, "size": size,
                           "purpose": str(msg.get("purpose", ""))}

    def _up_chunk(self, st, body):
        parsed = C.unpack_file_chunk(body)
        if not parsed:
            return
        fid, index, data = parsed
        rec = st.uploads.get(fid)
        if not rec or index != rec["n"]:
            return
        rec["f"].write(data)
        rec["n"] += 1
        self.send(st, {"t": "up_ack", "fid": fid, "n": rec["n"]})

    def _up_end(self, st, msg):
        try:
            fid = int(msg.get("fid"))
        except (TypeError, ValueError):
            return
        rec = st.uploads.pop(fid, None)
        if not rec:
            return
        rec["f"].close()
        self.send(st, {"t": "up_ok", "fid": fid, "name": rec["name"]})
        self.notice.emit(st, "upload", rec)

    # ---------------------------------------------------------------- sending
    def send(self, st, obj):
        if st.alive:
            self.bytes_out += st.sock.sendTextMessage(C.jdump(obj))

    def send_many(self, seats, obj):
        for st in seats:
            self.send(st, obj)

    def _send_bin(self, st, data):
        if st.alive:
            self.bytes_out += st.sock.sendBinaryMessage(data)

    def send_input(self, st, obj):
        obj = dict(obj)
        obj["t"] = "input"
        self.send(st, obj)

    def set_focus(self, st, reason, on, preset=None, fps=12):
        if on:
            st.focus.add(reason)
        else:
            st.focus.discard(reason)
        _label, width, quality, sharp = preset or view_presets()[0]
        self.send(st, {"t": "focus", "on": bool(st.focus), "width": width, "quality": quality,
                       "sharp": sharp, "fps": fps})

    # -------------------------------------------------------------- broadcast
    def start_broadcast(self, mode, exclude=None):
        if not self.b_active or exclude != self.b_exclude:
            self.b_latest = None
        self.b_active, self.b_mode, self.b_exclude = True, mode, exclude
        for st in self.students.values():
            st.b_waiting, st.b_sent_seq = False, -1
            self.send(st, {"t": "bstop"} if st.sid == exclude else {"t": "bstart", "mode": mode})
            self._push_broadcast(st)

    def stop_broadcast(self):
        self.b_active, self.b_latest, self.b_exclude = False, None, None
        for st in list(self.students.values()) + list(self.remotes.values()):
            self.send(st, {"t": "bstop"})

    def publish(self, jpeg):
        if not self.b_active:
            return
        self.b_seq += 1
        self.b_latest = bytes((C.B_BROADCAST,)) + jpeg
        for st in list(self.students.values()) + list(self.remotes.values()):
            self._push_broadcast(st)

    def _push_broadcast(self, st):
        """Latest-frame-wins: a slow student never queues stale frames."""
        if not (self.b_active and self.b_latest and st.alive) or st.sid == self.b_exclude:
            return
        now = time.monotonic()
        if st.b_sent_seq == self.b_seq or (st.b_waiting and now - st.b_sent_at < 4.0):
            return
        st.b_waiting, st.b_sent_seq, st.b_sent_at = True, self.b_seq, now
        self._send_bin(st, self.b_latest)

    # ------------------------------------------------------------------ files
    def send_file(self, seats, name, data):
        self._fid += 1
        job = FileJob(self._fid, name, data)
        for st in seats:
            st.files[job.fid] = [job, 0, 0]
            self.send(st, {"t": "file_begin", "fid": job.fid, "name": name, "size": len(data),
                           "chunks": job.chunks})
            self._pump_file(st, job.fid)
        return job

    def _pump_file(self, st, fid):
        rec = st.files.get(fid)
        if not rec:
            return
        job, nxt, acked = rec
        while nxt < job.chunks and nxt - acked < C.FILE_WINDOW:
            chunk = job.data[nxt * C.FILE_CHUNK:(nxt + 1) * C.FILE_CHUNK]
            self._send_bin(st, C.pack_file_chunk(fid, nxt, chunk))
            nxt += 1
        rec[1] = nxt
        if acked >= job.chunks:
            self.send(st, {"t": "file_end", "fid": fid})
            del st.files[fid]

    def _file_ack(self, st, msg):
        try:
            fid, n = int(msg.get("fid")), int(msg.get("n"))
        except (TypeError, ValueError):
            return
        rec = st.files.get(fid)
        if rec:
            rec[2] = max(rec[2], n)
            self._pump_file(st, fid)

    def close_all(self):
        for st in list(self.students.values()) + list(self.remotes.values()) + list(self.pending):
            self.send(st, {"t": "bye"})
            st.sock.flush()
            st.sock.close()
        self.ws.close()


# ==========================================================================
# Widgets
# ==========================================================================
class ThumbView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pm = None
        self.offline = True

    def set_pixmap(self, pm):
        self.pm = pm
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(C.T("thumb_bg")))
        if self.pm and not self.pm.isNull():
            sz = self.pm.size().scaled(self.size(), Qt.KeepAspectRatio)
            r = QRect((self.width() - sz.width()) // 2, (self.height() - sz.height()) // 2, sz.width(), sz.height())
            p.drawPixmap(r, self.pm)
        if self.offline:
            p.fillRect(self.rect(), QColor(20, 26, 24, 170))
            p.setPen(QColor("#E0E6E3"))
            p.drawText(self.rect(), Qt.AlignCenter, C.L("غير متصل", "Offline"))
        elif not self.pm:
            p.setPen(QColor("#9FB3AA"))
            p.drawText(self.rect(), Qt.AlignCenter, C.L("بانتظار الصورة...", "Waiting for image..."))


class StudentTile(QFrame):
    open_req = pyqtSignal(str)
    menu_req = pyqtSignal(str, QPoint)

    def __init__(self, sid, info):
        super().__init__()
        self.setObjectName("Tile")
        self.sid = sid
        self.seat = None
        self.info = dict(info)
        self.online = False
        self.last_jpeg = None
        self.last_frame_t = 0.0
        self.view = ThumbView()
        self.check = QCheckBox()
        self.check.toggled.connect(self._sel)
        self.name_lbl = QLabel()
        self.name_lbl.setStyleSheet("font-weight:600;")
        self.badges = QLabel()
        self.sub = QLabel()
        self.sub.setObjectName("Muted")
        self.sub.setStyleSheet("font-size:8pt;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 6)
        lay.setSpacing(4)
        lay.addWidget(self.view)
        row = QHBoxLayout()
        row.addWidget(self.check)
        row.addWidget(self.name_lbl, 1)
        row.addWidget(self.badges)
        lay.addLayout(row)
        lay.addWidget(self.sub)
        self.refresh()

    @property
    def name(self):
        return self.info.get("name", "?")

    def set_width(self, w):
        self.view.setFixedSize(w, int(w * 9 / 16))

    def _sel(self, on):
        self.setProperty("sel", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_online(self, on):
        self.online = on
        self.view.offline = not on
        self.view.update()
        self.refresh()

    def set_jpeg(self, data):
        pm = C.jpeg_pixmap(data)
        if pm is not None:
            self.view.set_pixmap(pm)
            self.last_jpeg = data

    def refresh(self):
        self.name_lbl.setText(self.name)
        st = self.seat
        win = st.win if (st and self.online) else ""
        short = win if len(win) <= 46 else win[:45] + "…"
        self.sub.setText(f"{self.info.get('host', '')} · {self.info.get('ip', '')}" + (f"\n🪟 {short}" if win else ""))
        self.sub.setToolTip(win)
        marks = []
        if st and st.hand:
            marks.append("✋")
        if st and st.locked:
            marks.append("🔒")
        if st and st.watching:
            marks.append("📺")
        if st and st.focus:
            marks.append("👁")
        if st and st.kind == "web":
            marks.append("📱")
        self.badges.setText(" ".join(marks) if self.online else "⚪")
        hand = "true" if (st and st.hand) else "false"
        if self.property("hand") != hand:
            self.setProperty("hand", hand)
            self.style().unpolish(self)
            self.style().polish(self)

    def flash(self, ms=5000):
        self.setProperty("pick", "true")
        self.style().unpolish(self)
        self.style().polish(self)
        QTimer.singleShot(ms, self._unflash)

    def _unflash(self):
        self.setProperty("pick", "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseDoubleClickEvent(self, _e):
        self.open_req.emit(self.sid)

    def contextMenuEvent(self, e):
        self.menu_req.emit(self.sid, e.globalPos())


class TileGrid(QWidget):
    def __init__(self):
        super().__init__()
        self.tiles = []
        self.tile_w = 300
        self._cols = 0
        self.lay = QGridLayout(self)
        self.lay.setSpacing(12)
        self.lay.setContentsMargins(12, 12, 12, 12)
        self.lay.setAlignment(Qt.AlignTop | Qt.AlignLeading)
        self.empty = QLabel(C.L("لا يوجد طلاب بعد.\nشغّل برنامج «سبّورة — الطالب» على أجهزة الطلاب، "
                            "وسيظهر كل جهاز هنا تلقائيًا بعد إدخال رمز الصف.", "No students yet.\nRun «Sabbora — Student» on the student PCs; each PC appears here automatically after entering the class code."))
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("font-size:12pt; padding:60px;")

    def add(self, tile):
        self.tiles.append(tile)
        tile.set_width(self.tile_w)
        self.relayout(True)

    def remove(self, tile):
        if tile in self.tiles:
            self.tiles.remove(tile)
            tile.setParent(None)
            tile.deleteLater()
            self.relayout(True)

    def set_tile_width(self, w):
        self.tile_w = w
        for t in self.tiles:
            t.set_width(w)
        self.relayout(True)

    def relayout(self, force=False):
        cols = max(1, (self.width() - 24) // (self.tile_w + 30))
        if cols == self._cols and not force:
            return
        self._cols = cols
        while self.lay.count():
            self.lay.takeAt(0)
        if not self.tiles:
            self.empty.show()
            self.lay.addWidget(self.empty, 0, 0)
            return
        self.empty.hide()
        ordered = sorted(self.tiles, key=lambda t: (not t.online, t.name.lower()))
        for i, t in enumerate(ordered):
            self.lay.addWidget(t, i // cols, i % cols)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()


class FrameView(QWidget):
    """Live student screen; forwards mouse and keyboard when control is on."""

    def __init__(self, send):
        super().__init__()
        self.send = send
        self.pm = None
        self.control = False
        self.offline = False
        self._pending = None
        self._last_sent = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(480, 270)
        self._mv = QTimer(self)
        self._mv.timeout.connect(self._flush_move)
        self._mv.start(35)

    def set_pixmap(self, pm):
        self.pm = pm
        self.update()

    def _rect(self):
        if not self.pm or self.pm.isNull():
            return QRect()
        sz = self.pm.size().scaled(self.size(), Qt.KeepAspectRatio)
        return QRect((self.width() - sz.width()) // 2, (self.height() - sz.height()) // 2, sz.width(), sz.height())

    def _norm(self, pos):
        r = self._rect()
        if r.isEmpty():
            return None
        x = (pos.x() - r.x()) / max(1, r.width())
        y = (pos.y() - r.y()) / max(1, r.height())
        if not (0 <= x <= 1 and 0 <= y <= 1):
            return None
        return round(x, 5), round(y, 5)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(C.T("thumb_bg")))
        r = self._rect()
        if not r.isEmpty():
            p.drawPixmap(r, self.pm)
        else:
            p.setPen(QColor("#9FB3AA"))
            p.drawText(self.rect(), Qt.AlignCenter, C.L("جارٍ الاتصال بشاشة الطالب...", "Connecting to the student's screen..."))
        if self.control:
            p.setPen(QPen(QColor("#F2A541"), 4))
            p.drawRect(self.rect().adjusted(2, 2, -2, -2))
        if self.offline:
            p.fillRect(self.rect(), QColor(16, 22, 20, 180))
            p.setPen(QColor("#FFFFFF"))
            p.drawText(self.rect(), Qt.AlignCenter, C.L("انقطع اتصال الطالب", "Student disconnected"))

    @staticmethod
    def _btn(b):
        return {Qt.LeftButton: "l", Qt.RightButton: "r", Qt.MiddleButton: "m"}.get(b)

    def _flush_move(self):
        if self.control and self._pending and self._pending != self._last_sent:
            self._last_sent = self._pending
            self.send({"k": "move", "x": self._pending[0], "y": self._pending[1]})

    def mouseMoveEvent(self, e):
        if self.control:
            self._pending = self._norm(e.pos())

    def mousePressEvent(self, e):
        self.setFocus()
        n = self._norm(e.pos())
        if self.control and n and self._btn(e.button()):
            self.send({"k": "down", "b": self._btn(e.button()), "x": n[0], "y": n[1]})

    mouseDoubleClickEvent = mousePressEvent

    def mouseReleaseEvent(self, e):
        n = self._norm(e.pos())
        if self.control and n and self._btn(e.button()):
            self.send({"k": "up", "b": self._btn(e.button()), "x": n[0], "y": n[1]})

    def wheelEvent(self, e):
        n = self._norm(e.pos())
        if self.control and n:
            self.send({"k": "wheel", "d": e.angleDelta().y(), "x": n[0], "y": n[1]})

    def _key(self, e, down):
        vk = e.nativeVirtualKey() if C.IS_WIN else 0
        if not vk:
            vk = QT_TO_VK.get(e.key(), 0)
        self.send({"k": "key", "vk": int(vk), "down": down, "text": e.text() if not vk else ""})

    def keyPressEvent(self, e):
        if self.control:
            self._key(e, True)
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if self.control:
            if not e.isAutoRepeat():
                self._key(e, False)
        else:
            super().keyReleaseEvent(e)

    def event(self, e):
        if self.control and e.type() in (QEvent.KeyPress, QEvent.KeyRelease) and e.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            (self.keyPressEvent if e.type() == QEvent.KeyPress else self.keyReleaseEvent)(e)
            return True
        return super().event(e)


class StudentViewer(QDialog):
    def __init__(self, win, seat, control=False):
        super().__init__(win)
        self.win = win
        self.seat = seat
        self.sid = seat.sid
        self.setWindowTitle(C.L(f"شاشة {seat.name} — {seat.host}", f"Screen of {seat.name} — {seat.host}"))
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)
        self.resize(1180, 760)
        self.view = FrameView(lambda obj: self.seat.alive and self.win.server.send_input(self.seat, obj))
        self.btn_ctl = QPushButton(C.L("🖱 تحكم عن بعد", "🖱 Remote control"))
        self.btn_ctl.setCheckable(True)
        self.btn_ctl.toggled.connect(self._toggle_control)
        self.btn_lock = QPushButton(C.L("🔒 قفل", "🔒 Lock"))
        self.btn_lock.setCheckable(True)
        self.btn_lock.setChecked(seat.locked)
        self.btn_lock.toggled.connect(lambda on: self.win.do_lock([self.seat]) if on else self.win.do_unlock([self.seat]))
        btn_demo = QPushButton(C.L("📺 اعرض شاشته على الصف", "📺 Show to class"))
        btn_demo.clicked.connect(lambda: self.win.start_demo(self.sid))
        btn_msg = QPushButton(C.L("💬 رسالة", "💬 Message"))
        btn_msg.clicked.connect(lambda: self.win.do_message([self.seat]))
        btn_shot = QPushButton(C.L("📸 لقطة", "📸 Snapshot"))
        btn_shot.clicked.connect(lambda: self.win.save_shots([self.win.tiles[self.sid]]))
        self.cmb_q = QComboBox()
        for label, *_ in view_presets():
            self.cmb_q.addItem(label)
        self.cmb_q.currentIndexChanged.connect(
            lambda i: self.win.server.set_focus(self.seat, "viewer", True, view_presets()[i]))
        self.hint = QLabel("")
        self.hint.setObjectName("Muted")
        top = QHBoxLayout()
        for w in (self.btn_ctl, self.btn_lock, btn_demo, btn_msg, btn_shot):
            top.addWidget(w)
        top.addStretch(1)
        top.addWidget(QLabel(C.L("الجودة:", "Quality:")))
        top.addWidget(self.cmb_q)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.hint)
        self.btn_ctl.setChecked(control)
        self._toggle_control(control)
        icons.iconify(self)

    def _toggle_control(self, on):
        self.view.control = on
        self.view.update()
        self.hint.setText(C.L("🖱 التحكم مفعّل: الماوس ولوحة المفاتيح تُرسل إلى جهاز الطالب (اضغط الزر مجددًا لإيقافه).", "🖱 Control is ON: your mouse and keyboard go to the student's PC (click the button again to stop).")
                          if on else C.L("وضع المشاهدة فقط. انقر نقرًا مزدوجًا على أي طالب لفتح شاشته.", "View only. Double-click any student to open their screen."))
        if on:
            self.view.setFocus()

    def show_jpeg(self, data):
        pm = C.jpeg_pixmap(data)
        if pm is not None:
            self.view.set_pixmap(pm)

    def set_offline(self, off):
        self.view.offline = off
        self.view.update()

    def rebind(self, seat):
        self.seat = seat
        self.set_offline(False)
        self.win.server.set_focus(seat, "viewer", True, view_presets()[self.cmb_q.currentIndex()])

    def done(self, r):
        self.win.viewer_closed(self.sid)
        super().done(r)


class FloatingBar(QWidget):
    """Small always-on-top control bar shown while broadcasting; it is hidden
    from the capture so students never see it."""

    def __init__(self, win):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.win = win
        self._drag = None
        box = QFrame(self)
        box.setObjectName("Bar")
        self.lbl = QLabel(C.L("● بث مباشر", "● Live"))
        self.btn_pause = QPushButton(C.L("⏸ تجميد", "⏸ Freeze"))
        self.btn_pause.setCheckable(True)
        self.btn_pause.toggled.connect(win.set_paused)
        b_stop = QPushButton(C.L("⏹ إيقاف", "⏹ Stop"))
        b_stop.clicked.connect(win.stop_cast)
        b_lock = QPushButton("🔒")
        b_lock.setToolTip(C.L("قفل كل الشاشات", "Lock all screens"))
        b_lock.clicked.connect(lambda: win.do_lock(win.all_seats()))
        b_unlock = QPushButton("🔓")
        b_unlock.setToolTip(C.L("فتح كل الشاشات", "Unlock all screens"))
        b_unlock.clicked.connect(lambda: win.do_unlock(win.all_seats()))
        b_home = QPushButton(C.L("🏠 اللوحة", "🏠 Dashboard"))
        b_home.clicked.connect(win.bring_back)
        self.count = QLabel("")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(10, 6, 10, 6)
        for w in (self.lbl, self.count, self.btn_pause, b_stop, b_lock, b_unlock, b_home):
            lay.addWidget(w)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)

    def show_bar(self, text):
        self.lbl.setText(text)
        self.adjustSize()
        if not self.isVisible():
            scr = QApplication.primaryScreen().availableGeometry()
            self.move(scr.center().x() - self.width() // 2, scr.top() + 8)
        self.show()
        self.raise_()
        C.exclude_from_capture(self, True)

    def mousePressEvent(self, e):
        self._drag = e.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._drag)

    def mouseReleaseEvent(self, _e):
        self._drag = None


class PollWindow(QDialog):
    def __init__(self, win, pid, question, options):
        super().__init__(win)
        self.win = win
        self.pid = pid
        self.options = options
        self.votes = {}
        self.setWindowTitle(C.L("تصويت سريع", "Quick poll"))
        self.resize(560, 300 + 40 * len(options))
        lay = QVBoxLayout(self)
        q = QLabel(question)
        q.setObjectName("Title")
        q.setWordWrap(True)
        lay.addWidget(q)
        self.bars = []
        for opt in options:
            row = QHBoxLayout()
            lbl = QLabel(opt)
            lbl.setMinimumWidth(140)
            bar = QProgressBar()
            bar.setFormat("%v")
            bar.setMaximum(1)
            row.addWidget(lbl)
            row.addWidget(bar, 1)
            lay.addLayout(row)
            self.bars.append(bar)
        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        lay.addWidget(self.summary)
        self.names = QListWidget()
        lay.addWidget(self.names, 1)
        row = QHBoxLayout()
        b_show = QPushButton(C.L("📢 اعرض النتيجة على الطلاب", "📢 Show results to students"))
        b_show.clicked.connect(self._share)
        b_end = QPushButton(C.L("⏹ إنهاء التصويت", "⏹ End poll"))
        b_end.setObjectName("Danger")
        b_end.clicked.connect(self.close)
        row.addWidget(b_show)
        row.addStretch(1)
        row.addWidget(b_end)
        lay.addLayout(row)
        icons.iconify(self)
        self._refresh()

    def counts(self):
        c = [0] * len(self.options)
        for _name, idx in self.votes.values():
            c[idx] += 1
        return c

    def add_vote(self, seat, idx):
        if 0 <= idx < len(self.options):
            self.votes[seat.sid] = (seat.name, idx)
            self._refresh()

    def _refresh(self):
        counts = self.counts()
        total = max(1, len(self.win.all_seats()))
        for bar, n in zip(self.bars, counts):
            bar.setMaximum(total)
            bar.setValue(n)
        self.summary.setText(C.L(f"أجاب {len(self.votes)} من {len(self.win.all_seats())} طالبًا متصلًا.", f"{len(self.votes)} of {len(self.win.all_seats())} connected students answered."))
        self.names.clear()
        for name, idx in sorted(self.votes.values()):
            self.names.addItem(f"{name}  ←  {self.options[idx]}")

    def _share(self):
        self.win.server.send_many(self.win.all_seats(), {"t": "poll_result", "pid": self.pid,
                                                          "opts": self.options, "counts": self.counts()})

    def done(self, r):
        self.win.server.send_many(self.win.all_seats(), {"t": "poll_end", "pid": self.pid})
        self.win.poll = None
        super().done(r)


# ==========================================================================
# Main window
# ==========================================================================
class TeacherWindow(QMainWindow):
    def __init__(self, args):
        super().__init__()
        self.settings = QSettings("Sabbora", "Teacher")
        self.course = self.settings.value("course", C.L("محاضرة", "Lecture"), str)
        self.code = self.settings.value("code", "", str) or self._random_code()
        self.settings.setValue("code", self.code)
        self.server = ClassServer(self.code, self.course, self)
        self.port = self.server.listen(args.port or C.WS_PORT)
        self.server.remote_pin = f"{random.randint(0, 999999):06d}"
        self.web = WebServer(self.port)
        self.web_port = self.web.start()
        self.injector = C.InputInjector()
        self.recent_chat = []
        self.photo_mode = False
        self.phones_dlg = None
        self.caster = ScreenBroadcaster(self)
        self.caster.frame_ready.connect(self.server.publish)
        self.caster.window_lost.connect(lambda: QTimer.singleShot(0, self._window_lost))
        self.caster.failed.connect(lambda m: self.statusBar().showMessage(C.L(f"تعذر التقاط الشاشة: {m}", f"Screen capture failed: {m}"), 3000))
        self.tiles = {}
        self.viewers = {}
        self.demo_sid = None
        self.poll = None
        self.roll = {}
        self.overlay = None
        self.annot_bar = None
        self.pick_dlg = None
        self.timer_end = None
        self._restarting = False
        self.monitors = C.list_monitors()
        self.roster_path = os.path.join(C.data_dir(), "roster.json")
        self._last_bytes, self._last_t = 0, time.monotonic()

        self.setWindowTitle(C.L(f"{C.app_title()} — لوحة المحاضر  |  {C.APP_NAME} Teacher {C.VERSION}", f"{C.APP_NAME} — Teacher console  |  {C.APP_NAME} Teacher {C.VERSION}"))
        self.resize(1400, 860)
        self._build_ui()
        self.bar = FloatingBar(self)
        icons.iconify(self)
        icons.iconify(self.bar)
        self._load_roster()

        self.server.joined.connect(self.on_joined)
        self.server.left.connect(self.on_left)
        self.server.thumb.connect(self.on_thumb)
        self.server.frame.connect(self.on_frame)
        self.server.notice.connect(self.on_event)

        self.udp = QUdpSocket(self)
        self._beacon_timer = QTimer(self)
        self._beacon_timer.timeout.connect(self._beacon)
        self._beacon_timer.start(2000)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(1000)
        QTimer.singleShot(0, self._beacon)
        QTimer.singleShot(300, lambda: self._apply_exclusion(self.chk_hide.isChecked()))
        if not self.port:
            QMessageBox.critical(self, C.L("خطأ", "Error"), C.L("تعذر فتح منفذ الشبكة. تأكد من عدم تشغيل نسخة أخرى من البرنامج.", "Could not open the network port. Make sure another copy of the program is not running."))

    # -------------------------------------------------------------- UI build
    def _build_ui(self):
        root = QWidget()
        root.setObjectName("Page")
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        header = QFrame()
        header.setObjectName("Header")
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 10, 18, 10)
        brand = QVBoxLayout()
        logo = QLabel()
        logo.setPixmap(C.app_icon().pixmap(44, 44))
        h.addWidget(logo)
        t = QLabel(C.app_title())
        t.setObjectName("Brand")
        credit = QLabel(C.L(f"لوحة المحاضر — {C.credit()}", f"Teacher console — {C.credit()}"))
        credit.setObjectName("Credit")
        brand.addWidget(t)
        brand.addWidget(credit)
        h.addLayout(brand)
        h.addStretch(1)
        info = QFrame()
        info.setObjectName("InfoBox")
        g = QGridLayout(info)
        g.setContentsMargins(14, 8, 14, 8)
        g.setHorizontalSpacing(12)
        self.ed_course = QLineEdit(self.course)
        self.ed_course.setMinimumWidth(200)
        self.ed_course.editingFinished.connect(self._course_changed)
        self.lbl_addr = QLabel()
        self.lbl_addr.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_code = QLabel(self.code)
        self.lbl_code.setObjectName("Big")
        b_code = QPushButton(C.L("رمز جديد", "New code"))
        b_code.clicked.connect(self._new_code)
        g.addWidget(QLabel(C.L("اسم المقرر:", "Course name:")), 0, 0)
        g.addWidget(self.ed_course, 0, 1)
        g.addWidget(QLabel(C.L("رمز الصف:", "Class code:")), 0, 2)
        g.addWidget(self.lbl_code, 0, 3)
        g.addWidget(b_code, 0, 4)
        g.addWidget(QLabel(C.L("عنوان المحاضر:", "Teacher address:")), 1, 0)
        g.addWidget(self.lbl_addr, 1, 1, 1, 4)
        h.addWidget(info)
        b_phone = QPushButton(C.L("📱 الهواتف والمتصفح", "📱 Phones & browsers"))
        b_phone.setObjectName("HeaderBtn")
        b_phone.setToolTip(C.L("رمز QR ليدخل الطلاب من هواتفهم، وجهاز تحكم لهاتفك",
                               "QR code so students join from their phones, and a remote for your phone"))
        b_phone.clicked.connect(self.show_phones)
        h.addWidget(b_phone)
        b_lang = QPushButton("🌐 English" if C.LANG == "ar" else "🌐 العربية")
        b_lang.setObjectName("HeaderBtn")
        b_lang.setToolTip(C.L("تغيير لغة البرنامج", "Change the program language"))
        b_lang.clicked.connect(self.switch_language)
        h.addWidget(b_lang)
        v.addWidget(header)

        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(12, 6, 12, 6)

        # --- broadcast group
        gb = QGroupBox(C.L("مشاركة الشاشة", "Screen sharing"))
        gl = QGridLayout(gb)
        self.btn_cast = QPushButton(C.L("▶ بث شاشتي للطلاب", "▶ Share my screen"))
        self.btn_cast.setObjectName("Primary")
        self.btn_cast.clicked.connect(self.start_cast)
        self.btn_pause = QPushButton(C.L("⏸ تجميد الصورة", "⏸ Freeze image"))
        self.btn_pause.setCheckable(True)
        self.btn_pause.toggled.connect(self.set_paused)
        self.btn_stop = QPushButton(C.L("⏹ إيقاف البث", "⏹ Stop sharing"))
        self.btn_stop.setObjectName("Danger")
        self.btn_stop.clicked.connect(self.stop_cast)
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem(C.L("ملء الشاشة — مقفل (لا يستطيع الطالب الخروج)", "Full screen — locked (students cannot leave)"), "full")
        self.cmb_mode.addItem(C.L("نافذة — يستطيع الطالب تصغيرها", "Window — students can minimise it"), "window")
        self.cmb_mon = QComboBox()
        self.cmb_mon.setMinimumWidth(260)
        for i, m in enumerate(self.monitors):
            self.cmb_mon.addItem(icons.make("monitor") or QIcon(), C.L(f"الشاشة {i + 1}  ({m[2]}×{m[3]}){' — الرئيسية' if m[4] else ''}", f"Screen {i + 1}  ({m[2]}×{m[3]}){' — primary' if m[4] else ''}"))
        self.cmb_q = QComboBox()
        for label, *_ in quality_presets():
            self.cmb_q.addItem(label)
        self.sp_fps = QSpinBox()
        self.sp_fps.setRange(1, 30)
        self.sp_fps.setSuffix(C.L(" إطار/ث", " fps"))
        self.chk_ptr = QCheckBox(C.L("مؤشر ليزر", "Laser pointer"))
        self.chk_hide = QCheckBox(C.L("إخفاء هذه اللوحة عن البث", "Hide this console from the broadcast"))
        self.chk_min = QCheckBox(C.L("تصغير اللوحة عند البدء", "Minimise console on start"))
        self._load_cast_settings()
        for w in (self.cmb_mode, self.cmb_q):
            w.currentIndexChanged.connect(self._cast_settings_changed)
        self.sp_fps.valueChanged.connect(self._cast_settings_changed)
        self.chk_ptr.toggled.connect(self._cast_settings_changed)
        self.chk_hide.toggled.connect(self._apply_exclusion)
        gl.addWidget(self.btn_cast, 0, 0)
        gl.addWidget(self.btn_pause, 0, 1)
        gl.addWidget(self.btn_stop, 0, 2)
        gl.addWidget(QLabel(C.L("الوضع:", "Mode:")), 0, 3)
        gl.addWidget(self.cmb_mode, 0, 4)
        self.cmb_mon.addItem(icons.make("microsoft-powerpoint") or QIcon(),
                             C.L("PowerPoint — يتبع العرض تلقائيًا", "PowerPoint — follows the slide show"), ("ppt", None))
        self.cmb_mon.addItem(icons.make("application-outline") or QIcon(),
                             C.L("نافذة محددة… (اختر)", "A specific window… (choose)"), ("pick", None))
        self._src_idx = 0
        self.cmb_mon.activated.connect(self._source_activated)
        gl.addWidget(QLabel(C.L("مصدر البث:", "Share:")), 0, 5)
        gl.addWidget(self.cmb_mon, 0, 6)
        gl.addWidget(QLabel(C.L("الجودة:", "Quality:")), 1, 3)
        gl.addWidget(self.cmb_q, 1, 4)
        gl.addWidget(self.sp_fps, 1, 5)
        opts = QHBoxLayout()
        for w in (self.chk_ptr, self.chk_hide, self.chk_min):
            opts.addWidget(w)
        gl.addLayout(opts, 1, 0, 1, 3)
        gl.addWidget(QLabel(""), 1, 6)

        # --- control group
        gc = QGroupBox(C.L("التحكم بالطلاب", "Student control"))
        cl = QHBoxLayout(gc)
        self.cmb_target = QComboBox()
        self.cmb_target.addItem(C.L("على: كل الطلاب", "Target: all students"), "all")
        self.cmb_target.addItem(C.L("على: المحدَّدين فقط", "Target: selected only"), "sel")
        cl.addWidget(self.cmb_target)
        actions = [
            (C.L("🔒 قفل الشاشات", "🔒 Lock screens"), "Warn", lambda: self.do_lock(self.targets())),
            (C.L("🔓 فتح", "🔓 Unlock"), "", lambda: self.do_unlock(self.targets())),
            (C.L("💬 رسالة", "💬 Message"), "", lambda: self.do_message(self.targets())),
            (C.L("🌐 فتح موقع", "🌐 Open website"), "", lambda: self.do_url(self.targets())),
            (C.L("🚀 تشغيل برنامج", "🚀 Run program"), "", lambda: self.do_run(self.targets())),
            (C.L("📁 إرسال ملف", "📁 Send file"), "", lambda: self.do_file(self.targets())),
            (C.L("📊 تصويت سريع", "📊 Quick poll"), "", self.do_poll),
        ]
        for text, obj, fn in actions:
            b = QPushButton(text)
            if obj:
                b.setObjectName(obj)
            b.clicked.connect(fn)
            cl.addWidget(b)
        b_power = QPushButton(C.L("⏻ الطاقة ▾", "⏻ Power ▾"))
        pm = QMenu(b_power)
        pm.addAction(C.L("⚡ تشغيل الأجهزة (Wake-on-LAN)", "⚡ Power on PCs (Wake-on-LAN)"), lambda: self.do_wake(self.target_tiles(include_offline=True)))
        pm.addSeparator()
        for key, label in power_labels().items():
            pm.addAction(label, lambda k=key: self.do_power(self.targets(), k))
        b_power.setMenu(pm)
        cl.addWidget(b_power)
        b_more = QPushButton(C.L("⋯ المزيد ▾", "⋯ More ▾"))
        mm = QMenu(b_more)
        mm.addAction(C.L("☑ تحديد الكل / إلغاء التحديد", "☑ Select / deselect all"), self.toggle_select_all)
        mm.addAction(C.L("✋ إنزال كل الأيدي", "✋ Lower all hands"), lambda: self.lower_hands(self.all_seats()))
        mm.addAction(C.L("📸 حفظ لقطات لكل الشاشات", "📸 Save snapshots of all screens"), lambda: self.save_shots([t for t in self.tiles.values() if t.online]))
        mm.addAction(C.L("📋 تصدير كشف الحضور (CSV)", "📋 Export attendance (CSV)"), self.export_roll)
        mm.addAction(C.L("🧹 إزالة الأجهزة غير المتصلة من القائمة", "🧹 Remove offline PCs from the list"), self.remove_offline)
        mm.addSeparator()
        mm.addAction(C.L("📂 فتح مجلد التسليمات", "📂 Open submissions folder"), self.open_submissions)
        mm.addAction(C.L("🌐 English / العربية", "🌐 العربية / English"), self.switch_language)
        self._theme_menu(mm, "Teacher")
        mm.addAction(C.L("ℹ حول البرنامج", "ℹ About"), self.about)
        b_more.setMenu(mm)
        cl.addWidget(b_more)
        cl.addStretch(1)

        top = QHBoxLayout()
        top.addWidget(gb, 3)
        bv.addLayout(top)
        bv.addWidget(gc)

        gt = QGroupBox(C.L("أدوات الشرح والتفاعل", "Teaching tools"))
        tl = QHBoxLayout(gt)
        self.btn_timer = QPushButton(C.L("⏱ مؤقت", "⏱ Timer"))
        tools = [
            (C.L("🖊 قلم على الشاشة", "🖊 Pen on screen"), lambda: self.open_pen(None)),
            (C.L("⬜ سبورة بيضاء", "⬜ Whiteboard"), lambda: self.open_pen("white")),
            (None, self.do_timer),
            (C.L("🎲 اختيار طالب عشوائي", "🎲 Random student"), self.do_pick),
            (C.L("📥 طلب تسليم واجب", "📥 Collect assignment"), lambda: self.do_collect(self.targets())),
            (C.L("📋 إرسال نص للحافظة", "📋 Send text to clipboard"), lambda: self.do_clip(self.targets())),
            (C.L("⛔ إغلاق برنامج", "⛔ Close a program"), lambda: self.do_kill(self.targets())),
            (C.L("📂 مجلد التسليمات", "📂 Submissions folder"), self.open_submissions),
        ]
        for text, fn in tools:
            b = self.btn_timer if text is None else QPushButton(text)
            b.clicked.connect(fn)
            tl.addWidget(b)
        tl.addStretch(1)
        bv.addWidget(gt)

        # --- grid + side panel
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.grid = TileGrid()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid)
        lv.addWidget(scroll, 1)
        zr = QHBoxLayout()
        self.lbl_count = QLabel()
        self.lbl_count.setObjectName("Muted")
        zr.addWidget(self.lbl_count)
        zr.addStretch(1)
        zr.addWidget(QLabel(C.L("حجم الصور:", "Thumbnail size:")))
        sl = QSlider(Qt.Horizontal)
        sl.setRange(180, 560)
        sl.setValue(int(self.settings.value("tile_w", 300)))
        sl.setFixedWidth(180)
        sl.valueChanged.connect(lambda w: (self.grid.set_tile_width(w), self.settings.setValue("tile_w", w)))
        self.grid.tile_w = sl.value()
        zr.addWidget(sl)
        lv.addLayout(zr)
        split.addWidget(left)

        side = QWidget()
        sv = QVBoxLayout(side)
        sv.setContentsMargins(6, 0, 0, 0)
        lt = QLabel(C.L("الأحداث ورسائل الطلاب", "Events and student messages"))
        lt.setObjectName("Section")
        sv.addWidget(lt)
        self.log_list = QListWidget()
        self.log_list.setWordWrap(True)
        self.log_list.itemDoubleClicked.connect(self._log_open)
        sv.addWidget(self.log_list, 1)
        br = QHBoxLayout()
        b1 = QPushButton(C.L("✋ إنزال الأيدي", "✋ Lower hands"))
        b1.clicked.connect(lambda: self.lower_hands(self.all_seats()))
        b2 = QPushButton(C.L("🗑 مسح", "🗑 Clear"))
        b2.clicked.connect(self.log_list.clear)
        br.addWidget(b1)
        br.addWidget(b2)
        sv.addLayout(br)
        split.addWidget(side)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        split.setSizes([1100, 300])
        bv.addWidget(split, 1)
        v.addWidget(body, 1)
        self.setCentralWidget(root)
        self._refresh_addr()

        QShortcut(QKeySequence("Ctrl+B"), self, self.start_cast)
        QShortcut(QKeySequence("Ctrl+E"), self, self.stop_cast)
        QShortcut(QKeySequence("Ctrl+L"), self, lambda: self.do_lock(self.targets()))
        QShortcut(QKeySequence("Ctrl+U"), self, lambda: self.do_unlock(self.targets()))
        QShortcut(QKeySequence("Ctrl+M"), self, lambda: self.do_message(self.targets()))
        QShortcut(QKeySequence("Ctrl+A"), self, self.toggle_select_all)

    def _load_cast_settings(self):
        s = self.settings
        self.cmb_mode.setCurrentIndex(int(s.value("mode_idx", 0)))
        self.cmb_q.setCurrentIndex(min(int(s.value("q_idx", 0)), len(quality_presets()) - 1))
        src = s.value("source", "mon:0", str)
        if src == "ppt":
            self.cmb_mon.setCurrentIndex(len(self.monitors))
        else:
            self.cmb_mon.setCurrentIndex(min(int(src.split(":")[-1] or 0), len(self.monitors) - 1))
        self._src_idx = self.cmb_mon.currentIndex()
        self.sp_fps.setValue(int(s.value("fps", 10)))
        self.chk_ptr.setChecked(s.value("pointer", "true") == "true")
        self.chk_hide.setChecked(s.value("hide", "true") == "true")
        self.chk_min.setChecked(s.value("minimize", "true") == "true")

    def _save_cast_settings(self):
        s = self.settings
        s.setValue("mode_idx", self.cmb_mode.currentIndex())
        s.setValue("q_idx", self.cmb_q.currentIndex())
        kind = (self.cmb_mon.currentData() or ("mon", 0))[0]
        s.setValue("source", "ppt" if kind == "ppt" else f"mon:{min(self.cmb_mon.currentIndex(), len(self.monitors) - 1)}")
        s.setValue("fps", self.sp_fps.value())
        s.setValue("pointer", "true" if self.chk_ptr.isChecked() else "false")
        s.setValue("hide", "true" if self.chk_hide.isChecked() else "false")
        s.setValue("minimize", "true" if self.chk_min.isChecked() else "false")

    # ----------------------------------------------------------- addresses
    @staticmethod
    def _ipv4_entries():
        out = []
        for iface in QNetworkInterface.allInterfaces():
            fl = iface.flags()
            if not (fl & QNetworkInterface.IsUp and fl & QNetworkInterface.IsRunning) or fl & QNetworkInterface.IsLoopBack:
                continue
            for e in iface.addressEntries():
                if e.ip().protocol() == QAbstractSocket.IPv4Protocol:
                    out.append((e.ip().toString(), e.broadcast().toString(), iface.humanReadableName()))
        out.sort(key=lambda x: (not x[0].startswith(("192.168.", "10.", "172.")), x[0].startswith("169.254.")))
        return out

    def _refresh_addr(self):
        ips = [ip for ip, _b, _n in self._ipv4_entries() if not ip.startswith("169.254.")]
        self.lbl_addr.setText("   ".join(f"{ip}:{self.port}" for ip in ips[:3]) or f"127.0.0.1:{self.port}")

    def broadcast_addrs(self):
        addrs = {"255.255.255.255"}
        for _ip, bc, _n in self._ipv4_entries():
            if bc and bc != "0.0.0.0":
                addrs.add(bc)
        return sorted(addrs)

    def _beacon(self):
        if not self.port:
            return
        payload = C.jdump({"tag": C.BEACON_TAG, "course": self.course, "port": self.port,
                           "teacher": socket.gethostname()}).encode("utf-8")
        for addr in self.broadcast_addrs():
            self.udp.writeDatagram(payload, QHostAddress(addr), C.DISCOVERY_PORT)

    # ---------------------------------------------------------- header edits
    @staticmethod
    def _random_code():
        return f"{random.randint(1000, 9999)}"

    def _new_code(self):
        if self.all_seats() and QMessageBox.question(
                self, C.L("رمز جديد", "New code"), C.L("الطلاب المتصلون سيبقون متصلين، والجدد يحتاجون الرمز الجديد. متابعة؟", "Connected students stay connected; new students need the new code. Continue?")) != QMessageBox.Yes:
            return
        self.code = self._random_code()
        self.server.code = self.code
        self.settings.setValue("code", self.code)
        self.lbl_code.setText(self.code)

    def _course_changed(self):
        self.course = self.ed_course.text().strip() or C.L("محاضرة", "Lecture")
        self.server.course = self.course
        self.settings.setValue("course", self.course)
        self._beacon()

    def _apply_exclusion(self, on):
        self.settings.setValue("hide", "true" if on else "false")
        ok = C.exclude_from_capture(self, on)
        for v in self.viewers.values():
            C.exclude_from_capture(v, on)
        if on and not ok and C.IS_WIN:
            self.statusBar().showMessage(C.L("نظامك لا يدعم إخفاء اللوحة عن البث؛ استخدم خيار تصغير اللوحة.", "Your Windows cannot hide the console from the broadcast; use the minimise option instead."), 6000)

    # ------------------------------------------------------------- roster
    def _load_roster(self):
        try:
            with open(self.roster_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        for sid, info in data.items():
            if isinstance(info, dict):
                self._tile_for(sid, info)

    def _save_roster(self):
        data = {sid: t.info for sid, t in self.tiles.items()}
        try:
            with open(self.roster_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except OSError:
            pass

    def _tile_for(self, sid, info):
        tile = self.tiles.get(sid)
        if tile is None:
            tile = StudentTile(sid, info)
            tile.open_req.connect(lambda s: self.open_viewer(s))
            tile.menu_req.connect(self.tile_menu)
            self.tiles[sid] = tile
            self.grid.add(tile)
        return tile

    # ---------------------------------------------------------- server events
    def on_joined(self, st):
        info = {"name": st.name, "host": st.host, "user": st.user, "ip": st.ip, "mac": st.mac, "os": st.os}
        tile = self._tile_for(st.sid, info)
        tile.info.update(info)
        tile.seat = st
        tile.info["kind"] = st.kind
        tile.set_online(True)
        if st.kind == "web":
            tile.view.set_pixmap(self._phone_placeholder())
        self.grid.relayout(True)
        self._save_roster()
        r = self.roll.setdefault(st.sid, {"first": datetime.datetime.now(), "seconds": 0.0, "since": None, "last_out": None})
        r.update(name=st.name, host=st.host, user=st.user, ip=st.ip, since=time.monotonic())
        self.log(C.L(f"🟢 انضم {st.name} ({st.host} · {st.ip})", f"🟢 {st.name} joined ({st.host} · {st.ip})"))
        v = self.viewers.get(st.sid)
        if v:
            v.rebind(st)

    def on_left(self, st):
        tile = self.tiles.get(st.sid)
        if tile and tile.seat is st:
            tile.seat = None
            tile.set_online(False)
            self.grid.relayout(True)
        r = self.roll.get(st.sid)
        if r and r.get("since") is not None:
            r["seconds"] += time.monotonic() - r["since"]
            r["since"] = None
            r["last_out"] = datetime.datetime.now()
        self.log(C.L(f"⚪ غادر {st.name}", f"⚪ {st.name} left"))
        v = self.viewers.get(st.sid)
        if v:
            v.set_offline(True)
        if self.demo_sid == st.sid:
            self.stop_cast()

    def on_thumb(self, st, data):
        tile = self.tiles.get(st.sid)
        if tile and tile.seat is st:
            tile.set_jpeg(data)

    def on_frame(self, st, data):
        v = self.viewers.get(st.sid)
        if v:
            v.show_jpeg(data)
        tile = self.tiles.get(st.sid)
        now = time.monotonic()
        if tile and now - tile.last_frame_t > 1.0:
            tile.last_frame_t = now
            tile.set_jpeg(data)

    def on_event(self, st, kind, msg):
        tile = self.tiles.get(st.sid)
        if kind == "hand":
            self.log(C.L(f"✋ {st.name} رفع يده", f"✋ {st.name} raised a hand") if st.hand else C.L(f"👇 {st.name} أنزل يده", f"👇 {st.name} lowered their hand"), st.sid)
            if st.hand:
                QApplication.alert(self)
        elif kind == "chat":
            self.log(f"💬 {st.name}: {str(msg.get('text', ''))[:1000]}", st.sid)
            self.recent_chat = (self.recent_chat + [f"{st.name}: {str(msg.get('text', ''))[:200]}"])[-6:]
            QApplication.alert(self)
        elif kind == "vote" and self.poll and msg.get("pid") == self.poll.pid:
            try:
                self.poll.add_vote(st, int(msg.get("i")))
            except (TypeError, ValueError):
                pass
        elif kind == "cmd":
            self._remote_cmd(msg)
            return
        elif kind == "remote_join":
            self.log(C.L("📱 اتصل جهاز التحكم (هاتف المحاضر)", "📱 Teacher remote connected (phone)"))
            return
        elif kind == "remote_left":
            self.log(C.L("📱 انقطع جهاز التحكم", "📱 Teacher remote disconnected"))
            return
        elif kind == "upload" and st.role == "remote":
            self.show_photo(msg["path"])
            return
        elif kind == "upload":
            kb = os.path.getsize(msg["path"]) / 1024 if os.path.exists(msg["path"]) else 0
            self.log(C.L(f"📥 {st.name} سلّم «{msg['name']}» ({kb:.0f} KB)",
                         f"📥 {st.name} submitted «{msg['name']}» ({kb:.0f} KB)"), st.sid)
            QApplication.alert(self)
        elif kind == "file_ok":
            self.log(C.L(f"📁 {st.name} استلم الملف «{msg.get('name', '')}»", f"📁 {st.name} received «{msg.get('name', '')}»"))
        if tile:
            tile.refresh()

    def log(self, text, sid=None):
        item = QListWidgetItem(f"{C.now_text()}  {text}")
        item.setData(Qt.UserRole, sid)
        self.log_list.insertItem(0, item)
        while self.log_list.count() > 500:
            self.log_list.takeItem(self.log_list.count() - 1)

    def _log_open(self, item):
        sid = item.data(Qt.UserRole)
        if sid:
            self.open_viewer(sid)

    def _update_status(self):
        now = time.monotonic()
        rate = (self.server.bytes_out - self._last_bytes) * 8 / 1e6 / max(1e-3, now - self._last_t)
        self._last_bytes, self._last_t = self.server.bytes_out, now
        online = len(self.all_seats())
        hands = sum(1 for s in self.all_seats() if s.hand)
        if self.demo_sid:
            cast = C.L(f"يُعرض الآن: شاشة {self.tiles[self.demo_sid].name}", f"Now showing: {self.tiles[self.demo_sid].name}'s screen")
        elif self.server.b_active:
            cast = C.L("البث: يعمل", "Sharing: on") + (C.L(" (مجمَّد)", " (frozen)") if self.caster.paused else "")
        else:
            cast = C.L("البث: متوقف", "Sharing: off")
        self.statusBar().showMessage(C.L(f"👥 متصل: {online} من {len(self.tiles)}   |   ✋ أيدٍ مرفوعة: {hands}   |   "
                                     f"{cast}   |   الإرسال: {rate:.1f} ميغابت/ث", f"👥 Online: {online} of {len(self.tiles)}   |   ✋ Hands up: {hands}   |   {cast}   |   Upload: {rate:.1f} Mbit/s"))
        if self.timer_end is not None:
            left = int(round(self.timer_end - now))
            if left <= 0:
                self.timer_end = None
                self.btn_timer.setText(C.L("⏱ مؤقت", "⏱ Timer"))
                icons.iconify_button(self.btn_timer)
                self.log(C.L("⏰ انتهى الوقت", "⏰ Time is up"))
            else:
                self.statusBar().showMessage(self.statusBar().currentMessage() + f"   |   ⏱ {left // 60:02d}:{left % 60:02d}")
        if self.server.remotes:
            left = int(round(self.timer_end - now)) if self.timer_end is not None else 0
            self.server.send_state({"course": self.course, "online": online,
                                    "hands": [s.name for s in self.all_seats() if s.hand],
                                    "chat": self.recent_chat, "sharing": self.server.b_active,
                                    "frozen": self.caster.paused, "photo": self.photo_mode, "timer_left": max(0, left)})
        self.lbl_count.setText(C.L(f"👥 {online} متصل", f"👥 {online} online"))
        self.bar.count.setText(f"👥 {online}")

    # ---------------------------------------------------------- targeting
    def all_seats(self):
        return [t.seat for t in self.tiles.values() if t.seat and t.seat.alive]

    def target_tiles(self, include_offline=False):
        tiles = [t for t in self.tiles.values() if include_offline or t.online]
        if self.cmb_target.currentData() == "sel":
            tiles = [t for t in tiles if t.check.isChecked()]
        return tiles

    def targets(self):
        seats = [t.seat for t in self.target_tiles() if t.seat and t.seat.alive]
        if not seats:
            self.statusBar().showMessage(C.L("لا يوجد طلاب متصلون ضمن الهدف المختار (الكل/المحدَّدون).", "No connected students in the chosen target (all/selected)."), 4000)
        return seats

    def toggle_select_all(self):
        tiles = list(self.tiles.values())
        state = not all(t.check.isChecked() for t in tiles) if tiles else False
        for t in tiles:
            t.check.setChecked(state)
        if state:
            self.cmb_target.setCurrentIndex(1)

    # ---------------------------------------------------------- broadcasting
    def _cast_params(self):
        _label, width, quality, sharp = quality_presets()[self.cmb_q.currentIndex()]
        self.caster.source = self._source()
        self.caster.max_width, self.caster.quality, self.caster.sharp = width, quality, sharp
        self.caster.fps = self.sp_fps.value()
        self.caster.pointer = self.chk_ptr.isChecked()

    def _source(self):
        data = self.cmb_mon.currentData()
        if data and data[0] == "ppt":
            return ("ppt", None)
        if data and data[0] == "win":
            return ("win", data[1])
        idx = self.cmb_mon.currentIndex()
        return ("mon", self.monitors[min(idx, len(self.monitors) - 1)])

    def _source_activated(self, idx):
        data = self.cmb_mon.itemData(idx)
        if data and data[0] == "pick":
            dlg = WindowPicker(self)
            if dlg.exec_() and dlg.chosen:
                hwnd, title = dlg.chosen
                label = C.L("نافذة: ", "Window: ") + (title if len(title) < 48 else title[:47] + "…")
                win_idx = self.cmb_mon.count() - 1
                prev = self.cmb_mon.itemData(win_idx - 1)
                if prev and prev[0] == "win":             # keep a single "window" entry
                    self.cmb_mon.removeItem(win_idx - 1)
                    win_idx -= 1
                self.cmb_mon.insertItem(win_idx, icons.make("application-outline") or QIcon(), label, ("win", hwnd))
                self.cmb_mon.setCurrentIndex(win_idx)
            else:
                self.cmb_mon.setCurrentIndex(self._src_idx)
                return
        self._src_idx = self.cmb_mon.currentIndex()
        self._cast_settings_changed()

    def _window_lost(self):
        self.statusBar().showMessage(C.L("أُغلقت النافذة المشتركة — يُبث الآن كامل الشاشة.",
                                         "The shared window was closed — now sharing the whole screen."), 6000)
        self.cmb_mon.setCurrentIndex(0)
        self._src_idx = 0

    def _cast_settings_changed(self, *_):
        self._save_cast_settings()
        self._cast_params()
        self.caster.request_keyframe()
        if self.server.b_active and self.server.b_mode != self.cmb_mode.currentData():
            self.server.start_broadcast(self.cmb_mode.currentData(), self.server.b_exclude)

    def start_cast(self, quiet=False):
        if not quiet and not self.all_seats() and QMessageBox.question(
                self, C.L("بث الشاشة", "Share screen"), C.L("لا يوجد طلاب متصلون حاليًا. هل تريد بدء البث على أي حال؟", "No students are connected yet. Start sharing anyway?")) != QMessageBox.Yes:
            return
        if self.demo_sid:
            self._end_demo()
        self.monitors = C.list_monitors()
        self._cast_params()
        self.caster.paused = False
        self.btn_pause.setChecked(False)
        self.server.start_broadcast(self.cmb_mode.currentData())
        if self.caster.isRunning():
            self.caster.request_keyframe()
        else:
            self.caster.start()
        self.bar.btn_pause.setEnabled(True)
        self.bar.show_bar(C.L("● بث شاشتك مباشر", "● Sharing your screen live"))
        self.log(C.L("▶ بدأ بث شاشة المحاضر", "▶ Teacher screen sharing started"))
        if self.chk_min.isChecked():
            QTimer.singleShot(250, self.showMinimized)

    def set_paused(self, on):
        self.caster.paused = on
        for b in (self.btn_pause, self.bar.btn_pause):
            if b.isChecked() != on:
                b.blockSignals(True)
                b.setChecked(on)
                b.blockSignals(False)
        if not on:
            self.caster.request_keyframe()

    def stop_cast(self):
        if self.caster.isRunning():
            self.caster.stop()
        if self.demo_sid:
            self._end_demo()
        self.photo_mode = False
        if self.server.b_active:
            self.server.stop_broadcast()
            self.log(C.L("⏹ توقف البث", "⏹ Sharing stopped"))
        self.bar.hide()

    def start_demo(self, sid):
        tile = self.tiles.get(sid)
        if not tile or not tile.seat or tile.seat.kind == "web":
            return
        if self.caster.isRunning():
            self.caster.stop()
        if self.demo_sid and self.demo_sid != sid:
            self._end_demo()
        self.demo_sid = sid
        self.server.set_focus(tile.seat, "demo", True, view_presets()[0])
        self.server.start_broadcast(self.cmb_mode.currentData(), exclude=sid)
        self.bar.btn_pause.setEnabled(False)
        self.bar.show_bar(C.L(f"● يُعرض على الصف: شاشة {tile.name}", f"● Showing to class: {tile.name}'s screen"))
        self.log(C.L(f"📺 عرض شاشة {tile.name} على الصف", f"📺 Showing {tile.name}'s screen to the class"))

    def _end_demo(self):
        tile = self.tiles.get(self.demo_sid)
        if tile and tile.seat:
            self.server.set_focus(tile.seat, "demo", False)
        self.demo_sid = None

    def bring_back(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # --------------------------------------------------------------- viewers
    def open_viewer(self, sid, control=False):
        tile = self.tiles.get(sid)
        if not tile or not tile.seat:
            self.statusBar().showMessage(C.L("هذا الجهاز غير متصل الآن.", "This PC is offline right now."), 3000)
            return
        if tile.seat.kind == "web":
            self.statusBar().showMessage(C.L("هذا الطالب يستخدم هاتفًا أو متصفحًا: لا يمكن رؤية شاشته أو التحكم بها.",
                                             "This student uses a phone/browser: its screen cannot be viewed or controlled."), 5000)
            return
        v = self.viewers.get(sid)
        if v:
            v.btn_ctl.setChecked(control or v.btn_ctl.isChecked())
            v.showNormal()
            v.raise_()
            v.activateWindow()
            return
        v = StudentViewer(self, tile.seat, control)
        if tile.last_jpeg:
            v.show_jpeg(tile.last_jpeg)
        self.viewers[sid] = v
        v.show()
        C.exclude_from_capture(v, self.chk_hide.isChecked())
        self.server.set_focus(tile.seat, "viewer", True, view_presets()[0])
        tile.refresh()

    def viewer_closed(self, sid):
        self.viewers.pop(sid, None)
        tile = self.tiles.get(sid)
        if tile and tile.seat:
            self.server.set_focus(tile.seat, "viewer", False)
            tile.refresh()

    def tile_menu(self, sid, pos):
        tile = self.tiles[sid]
        st = tile.seat
        m = QMenu(self)
        if st:
            one = [st]
            m.addAction(C.L("👁 مشاهدة الشاشة مباشرة", "👁 Watch screen live"), lambda: self.open_viewer(sid))
            m.addAction(C.L("🖱 تحكم عن بعد", "🖱 Remote control"), lambda: self.open_viewer(sid, control=True))
            m.addAction(C.L("📺 اعرض شاشته على كل الصف", "📺 Show their screen to the class"), lambda: self.start_demo(sid))
            m.addSeparator()
            m.addAction(C.L("🔒 قفل الشاشة", "🔒 Lock screen"), lambda: self.do_lock(one))
            m.addAction(C.L("🔓 فتح الشاشة", "🔓 Unlock screen"), lambda: self.do_unlock(one))
            m.addAction(C.L("💬 إرسال رسالة", "💬 Send message"), lambda: self.do_message(one))
            m.addAction(C.L("🌐 فتح موقع", "🌐 Open website"), lambda: self.do_url(one))
            m.addAction(C.L("🚀 تشغيل برنامج", "🚀 Run program"), lambda: self.do_run(one))
            m.addAction(C.L("📁 إرسال ملف", "📁 Send file"), lambda: self.do_file(one))
            m.addAction(C.L("✋ إنزال اليد", "✋ Lower hand"), lambda: self.lower_hands(one))
            m.addAction(C.L("📸 حفظ لقطة", "📸 Save snapshot"), lambda: self.save_shots([tile]))
            pw = m.addMenu(C.L("⏻ الطاقة", "⏻ Power"))
            for key, label in power_labels().items():
                pw.addAction(label, lambda k=key: self.do_power(one, k))
            m.addSeparator()
            m.addAction(C.L("✖ فصل الطالب", "✖ Disconnect student"), lambda: self.do_kick(one))
        else:
            m.addAction(C.L("⚡ تشغيل الجهاز (Wake-on-LAN)", "⚡ Power on this PC (Wake-on-LAN)"), lambda: self.do_wake([tile]))
            m.addAction(C.L("🗑 إزالة من القائمة", "🗑 Remove from list"), lambda: self.remove_tiles([tile]))
        icons.iconify_menu(m)
        m.exec_(pos)

    # --------------------------------------------------------------- commands
    def _refresh_tiles(self, seats):
        for st in seats:
            t = self.tiles.get(st.sid)
            if t:
                t.refresh()

    def do_lock(self, seats):
        if not seats:
            return
        text = self.settings.value("lock_text", C.L("انتبه للمحاضر من فضلك 👀", "Eyes on the teacher, please 👀"), str)
        self.server.send_many(seats, {"t": "lock", "text": text})
        for st in seats:
            st.locked = True
        self._refresh_tiles(seats)
        self.log(C.L(f"🔒 قفل {len(seats)} شاشة", f"🔒 Locked {len(seats)} screen(s)"))

    def do_unlock(self, seats):
        if not seats:
            return
        self.server.send_many(seats, {"t": "unlock"})
        for st in seats:
            st.locked = False
        self._refresh_tiles(seats)
        self.log(C.L(f"🔓 فتح {len(seats)} شاشة", f"🔓 Unlocked {len(seats)} screen(s)"))

    def do_message(self, seats):
        if not seats:
            return
        text, ok = QInputDialog.getMultiLineText(self, C.L("رسالة للطلاب", "Message to students"), C.L(f"نص الرسالة ({len(seats)} طالب):", f"Message text ({len(seats)} student(s)):"))
        if ok and text.strip():
            self.server.send_many(seats, {"t": "msg", "text": text.strip()[:4000]})
            self.log(C.L(f"💬 أُرسلت رسالة إلى {len(seats)} طالب", f"💬 Message sent to {len(seats)} student(s)"))

    def do_url(self, seats):
        if not seats:
            return
        url, ok = QInputDialog.getText(self, C.L("فتح موقع", "Open website"), C.L("رابط الموقع:", "Website address:"), text=self.settings.value("last_url", "https://", str))
        url = url.strip()
        if ok and url:
            if "://" not in url:
                url = "https://" + url
            self.settings.setValue("last_url", url)
            self.server.send_many(seats, {"t": "url", "url": url})
            self.log(C.L(f"🌐 فتح {url} على {len(seats)} جهاز", f"🌐 Opened {url} on {len(seats)} PC(s)"))

    def do_run(self, seats):
        if not seats:
            return
        cmd, ok = QInputDialog.getText(
            self, C.L("تشغيل برنامج", "Run program"), C.L("اسم البرنامج أو مساره على أجهزة الطلاب\n(مثال: notepad  أو  calc  أو  C:\\Program Files\\...\\app.exe):", "Program name or path on the student PCs\n(e.g. notepad, calc or C:\\Program Files\\...\\app.exe):"),
            text=self.settings.value("last_cmd", "notepad", str))
        if ok and cmd.strip():
            self.settings.setValue("last_cmd", cmd.strip())
            self.server.send_many(seats, {"t": "run", "cmd": cmd.strip()})
            self.log(C.L(f"🚀 تشغيل «{cmd.strip()}» على {len(seats)} جهاز", f"🚀 Started «{cmd.strip()}» on {len(seats)} PC(s)"))

    def do_file(self, seats):
        if not seats:
            return
        path, _ = QFileDialog.getOpenFileName(self, C.L("اختر ملفًا لإرساله للطلاب", "Choose a file to send to the students"))
        if not path:
            return
        size = os.path.getsize(path)
        if size > C.MAX_FILE_BYTES:
            QMessageBox.warning(self, C.L("ملف كبير", "File too large"), C.L("الحد الأقصى لحجم الملف 512 ميغابايت.", "The maximum file size is 512 MB."))
            return
        with open(path, "rb") as f:
            data = f.read()
        name = os.path.basename(path)
        self.server.send_file(seats, name, data)
        self.log(C.L(f"📁 إرسال «{name}» ({size / 1e6:.1f} MB) إلى {len(seats)} طالب — يُحفظ في «المستندات/Sabbora Files»", f"📁 Sending «{name}» ({size / 1e6:.1f} MB) to {len(seats)} student(s) — saved in «Documents/Sabbora Files»"))

    def do_poll(self):
        seats = self.all_seats()
        if not seats:
            self.statusBar().showMessage(C.L("لا يوجد طلاب متصلون.", "No students connected."), 3000)
            return
        q, ok = QInputDialog.getText(self, C.L("تصويت سريع", "Quick poll"), C.L("السؤال:", "Question:"))
        if not ok or not q.strip():
            return
        presets = [C.L("نعم | لا", "Yes | No"), C.L("أ | ب | ج | د", "A | B | C | D"), C.L("صح | خطأ", "True | False"), C.L("فهمت | لم أفهم | أحتاج مثالًا", "Got it | Lost | Need an example")]
        opts, ok = QInputDialog.getItem(self, C.L("تصويت سريع", "Quick poll"), C.L("الخيارات (افصل بينها بـ | ويمكنك الكتابة):", "Options (separate with | — you can type your own):"),
                                        presets, 0, True)
        options = [o.strip() for o in opts.split("|") if o.strip()][:8] if ok else []
        if len(options) < 2:
            return
        if self.poll:
            self.poll.close()
        pid = int(time.time() * 1000) & 0x7FFFFFFF
        self.poll = PollWindow(self, pid, q.strip(), options)
        self.server.send_many(seats, {"t": "poll", "pid": pid, "q": q.strip(), "opts": options})
        self.poll.show()
        self.log(C.L(f"📊 تصويت: {q.strip()}", f"📊 Poll: {q.strip()}"))

    def do_power(self, seats, action):
        if not seats:
            return
        label = power_labels()[action]
        if QMessageBox.question(self, label, C.L(f"تنفيذ «{label}» على {len(seats)} جهاز؟", f"Run «{label}» on {len(seats)} PC(s)?")) != QMessageBox.Yes:
            return
        self.server.send_many(seats, {"t": "power", "action": action})
        self.log(C.L(f"⏻ {label}: {len(seats)} جهاز", f"⏻ {label}: {len(seats)} PC(s)"))

    def do_wake(self, tiles):
        macs = [t.info.get("mac") for t in tiles if t.info.get("mac")]
        if not macs:
            self.statusBar().showMessage(C.L("لا توجد عناوين MAC محفوظة؛ يجب أن يتصل كل جهاز مرة واحدة أولًا.", "No MAC addresses saved yet; each PC must connect once first."), 5000)
            return
        bcs = self.broadcast_addrs()
        sent = sum(1 for mac in macs if C.send_wake_on_lan(mac, bcs))
        self.log(C.L(f"⚡ أُرسلت إشارة التشغيل إلى {sent} جهاز (يتطلب تفعيل Wake-on-LAN في BIOS)", f"⚡ Wake-up signal sent to {sent} PC(s) (Wake-on-LAN must be enabled in BIOS)"))

    def do_kick(self, seats):
        for st in seats:
            self.server.send(st, {"t": "kick"})
            QTimer.singleShot(300, st.sock.close)

    def lower_hands(self, seats):
        for st in seats:
            if st.hand:
                st.hand = False
                self.server.send(st, {"t": "hand_down"})
        self._refresh_tiles(seats)

    def save_shots(self, tiles):
        tiles = [t for t in tiles if t.last_jpeg]
        if not tiles:
            self.statusBar().showMessage(C.L("لا توجد صور بعد.", "No images yet."), 3000)
            return
        base = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or os.path.expanduser("~")
        folder = os.path.join(base, "Sabbora", datetime.datetime.now().strftime("%Y-%m-%d"))
        os.makedirs(folder, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%H-%M-%S")
        for t in tiles:
            with open(C.unique_path(folder, C.safe_filename(f"{t.name}_{stamp}.jpg")), "wb") as f:
                f.write(t.last_jpeg)
        self.log(C.L(f"📸 حُفظت {len(tiles)} لقطة في {folder}", f"📸 Saved {len(tiles)} snapshot(s) in {folder}"))
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def export_roll(self):
        if not self.roll:
            QMessageBox.information(self, C.L("الحضور", "Attendance"), C.L("لم يتصل أي طالب في هذه الجلسة بعد.", "No student has connected in this session yet."))
            return
        default = os.path.join(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation),
                               C.L(f"حضور_{C.safe_filename(self.course)}_{datetime.datetime.now():%Y-%m-%d_%H-%M}.csv", f"attendance_{C.safe_filename(self.course)}_{datetime.datetime.now():%Y-%m-%d_%H-%M}.csv"))
        path, _ = QFileDialog.getSaveFileName(self, C.L("حفظ كشف الحضور", "Save attendance"), default, "CSV (*.csv)")
        if not path:
            return
        now = time.monotonic()
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow([C.L("الاسم", "Name"), C.L("اسم الجهاز", "PC name"), C.L("مستخدم ويندوز", "Windows user"), "IP", C.L("أول دخول", "First join"), C.L("آخر خروج", "Last leave"), C.L("مدة الحضور (دقيقة)", "Attendance (minutes)"), C.L("الحالة الآن", "Status now")])
            for r in sorted(self.roll.values(), key=lambda r: r.get("name", "")):
                secs = r["seconds"] + (now - r["since"] if r.get("since") is not None else 0)
                w.writerow([r.get("name", ""), r.get("host", ""), r.get("user", ""), r.get("ip", ""),
                            r["first"].strftime("%Y-%m-%d %H:%M"),
                            r["last_out"].strftime("%H:%M") if r.get("last_out") else "",
                            f"{secs / 60:.1f}", C.L("متصل", "Online") if r.get("since") is not None else C.L("غير متصل", "Offline")])
        self.log(C.L(f"📋 حُفظ كشف الحضور: {path}", f"📋 Attendance saved: {path}"))

    def remove_tiles(self, tiles):
        for t in tiles:
            if t.online:
                continue
            self.tiles.pop(t.sid, None)
            self.grid.remove(t)
        self._save_roster()

    def remove_offline(self):
        self.remove_tiles([t for t in self.tiles.values() if not t.online])

    def about(self):
        QMessageBox.about(self, C.L("حول سبّورة", "About Sabbora"),
                          C.L(f"<h3>{C.app_title()} — {C.APP_NAME} {C.VERSION}</h3>"
                          "<p>إدارة القاعة الصفية: بث الشاشة، مراقبة الطلاب، التحكم عن بعد، القفل، الرسائل، "
                          "الملفات، التصويت، الحضور، والطاقة.</p>"
                          f"<p>{C.credit()}</p>", f"<h3>{C.APP_NAME} {C.VERSION}</h3><p>Classroom management: screen sharing, student monitoring, remote control, locking, messages, files, polls, timers, assignments, attendance and power.</p><p>{C.credit()}</p>"))

    # ------------------------------------------------------- teaching tools
    def open_pen(self, board=None):
        if self.overlay is None:
            self.overlay = AnnotationOverlay(self.close_pen)
            self.annot_bar = AnnotationBar(self.overlay, self.close_pen)
        kind, val = self._source()
        if kind == "mon":
            mon = val
        else:
            hwnd = val if kind == "win" else C.find_powerpoint()
            rect = (C.visible_rect(hwnd) or C.window_rect(hwnd)) if hwnd else None
            mon = C.monitor_of_rect(rect) if rect else self.monitors[0]
        scr = screen_for_monitor(mon)
        self.overlay.open_on(scr, board)
        self.annot_bar.set_board(board)
        self.annot_bar.show_on(scr)
        self.caster.layered = True
        self.caster.request_keyframe()
        if not self.server.b_active and self.all_seats():
            self.statusBar().showMessage(C.L("تلميح: ابدأ «بث شاشتي» ليرى الطلاب ما ترسمه.",
                                             "Tip: start «Share my screen» so students see your drawing."), 6000)

    def close_pen(self):
        if self.overlay:
            self.overlay.clear()
            if self.overlay.passthrough:
                self.annot_bar.btn_mouse.setChecked(False)
            self.overlay.hide()
            self.annot_bar.hide()
        self.caster.layered = False
        self.caster.request_keyframe()

    def do_timer(self):
        if self.timer_end is not None:
            if QMessageBox.question(self, C.L("المؤقت", "Timer"), C.L("إيقاف المؤقت الحالي؟", "Stop the running timer?")) == QMessageBox.Yes:
                self.server.send_many(self.all_seats(), {"t": "timer_stop"})
                self.timer_end = None
                self.btn_timer.setText(C.L("⏱ مؤقت", "⏱ Timer"))
                icons.iconify_button(self.btn_timer)
            return
        seats = self.targets()
        if not seats:
            return
        minutes, ok = QInputDialog.getInt(self, C.L("مؤقت", "Timer"), C.L("المدة بالدقائق:", "Duration in minutes:"),
                                          int(self.settings.value("timer_min", 5)), 1, 240)
        if not ok:
            return
        title, ok = QInputDialog.getText(self, C.L("مؤقت", "Timer"), C.L("عنوان النشاط (اختياري):", "Activity title (optional):"),
                                         text=self.settings.value("timer_title", C.L("نشاط صفي", "Class activity"), str))
        if not ok:
            return
        self.settings.setValue("timer_min", minutes)
        self.settings.setValue("timer_title", title)
        self._start_timer(seats, minutes, title)

    def _start_timer(self, seats, minutes, title):
        self.server.send_many(seats, {"t": "timer", "seconds": minutes * 60, "title": title.strip()[:80]})
        self.timer_end = time.monotonic() + minutes * 60
        self.btn_timer.setText(C.L("⏹ إيقاف المؤقت", "⏹ Stop timer"))
        icons.iconify_button(self.btn_timer)
        self.log(C.L(f"⏱ مؤقت {minutes} دقيقة: {title}", f"⏱ {minutes}-minute timer: {title}"))

    def do_pick(self):
        seats = self.targets()
        if not seats:
            return
        st = random.choice(seats)
        tile = self.tiles.get(st.sid)
        if tile:
            tile.flash()
        self.server.send(st, {"t": "pick"})
        self.log(C.L(f"🎲 وقع الاختيار على {st.name}", f"🎲 Picked {st.name}"), st.sid)
        if self.pick_dlg is None:
            self.pick_dlg = PickDialog(self, st.name, self.do_pick)
        self.pick_dlg.set_name(st.name)
        self.pick_dlg.show()
        self.pick_dlg.raise_()

    def do_clip(self, seats):
        if not seats:
            return
        text, ok = QInputDialog.getMultiLineText(self, C.L("إرسال نص", "Send text"),
                                                 C.L("النص (يُنسخ إلى حافظة الطلاب ليلصقوه بـ Ctrl+V):",
                                                     "Text (copied to the students' clipboard, paste with Ctrl+V):"))
        if ok and text.strip():
            self.server.send_many(seats, {"t": "clip", "text": text[:20000]})
            self.log(C.L(f"📋 أُرسل نص إلى حافظة {len(seats)} طالب", f"📋 Text sent to {len(seats)} clipboard(s)"))

    def do_kill(self, seats):
        if not seats:
            return
        common = ["chrome.exe", "msedge.exe", "firefox.exe", "WhatsApp.exe", "Telegram.exe", "Discord.exe", "steam.exe"]
        name, ok = QInputDialog.getItem(self, C.L("إغلاق برنامج", "Close a program"),
                                        C.L("اسم البرنامج على أجهزة الطلاب (يمكنك الكتابة):",
                                            "Program name on the student PCs (you can type):"), common, 0, True)
        if ok and name.strip():
            self.server.send_many(seats, {"t": "kill", "name": name.strip()})
            self.log(C.L(f"⛔ إغلاق «{name.strip()}» على {len(seats)} جهاز", f"⛔ Closing «{name.strip()}» on {len(seats)} PC(s)"))

    def do_collect(self, seats):
        if not seats:
            return
        title, ok = QInputDialog.getText(self, C.L("طلب تسليم", "Collect assignment"),
                                         C.L("عنوان الواجب:", "Assignment title:"),
                                         text=self.settings.value("collect_title", C.L("الواجب", "Assignment"), str))
        if ok and title.strip():
            self.settings.setValue("collect_title", title.strip())
            self.server.send_many(seats, {"t": "collect", "title": title.strip()[:120]})
            self.log(C.L(f"📥 طُلب تسليم «{title.strip()}» من {len(seats)} طالب — تُحفظ في {self.server.submissions_dir()}",
                         f"📥 Requested «{title.strip()}» from {len(seats)} student(s) — saved in {self.server.submissions_dir()}"))

    # ------------------------------------------------------ phones & remote
    def lan_addresses(self):
        """LAN IPv4 addresses, real network cards first (virtual adapters last)."""
        virtual = ("virtualbox", "vmware", "vethernet", "hyper-v", "loopback", "docker", "wsl", "bluetooth")
        out = []
        for ip, _bc, name in self._ipv4_entries():
            if ip.startswith("169.254."):
                continue
            out.append((any(v in name.lower() for v in virtual), ip, name))
        out.sort(key=lambda x: x[0])
        return [(ip, name) for _v, ip, name in out] or [("127.0.0.1", "localhost")]

    def show_phones(self):
        if self.phones_dlg is None:
            self.phones_dlg = PhonesDialog(self)
        self.phones_dlg.refresh()
        self.phones_dlg.show()
        self.phones_dlg.raise_()

    def _phone_placeholder(self):
        pm = QPixmap(320, 180)
        pm.fill(QColor(C.T("thumb_bg")))
        p = QPainter(pm)
        icon = icons.pixmap("cellphone", 72, "#9FB3AA")
        if icon is not None:
            p.drawPixmap(124, 34, icon)
        p.setPen(QColor("#9FB3AA"))
        p.drawText(QRect(0, 120, 320, 40), Qt.AlignCenter, C.L("هاتف / متصفح", "Phone / browser"))
        p.end()
        return pm

    def _key(self, vk):
        self.injector.key(vk, True)
        self.injector.key(vk, False)

    def _remote_cmd(self, msg):
        c = msg.get("c")
        if c == "next":
            self._key(0x27)              # Right arrow: next slide
        elif c == "prev":
            self._key(0x25)              # Left arrow: previous slide
        elif c == "black":
            self._key(0x42)              # B: black screen in PowerPoint
        elif c == "share":
            self.start_cast(quiet=True)
        elif c == "stop":
            self.stop_cast()
        elif c == "freeze":
            self.set_paused(not self.caster.paused)
        elif c == "lock":
            self.do_lock(self.all_seats())
        elif c == "unlock":
            self.do_unlock(self.all_seats())
        elif c == "pick":
            self.do_pick()
        elif c == "hands_down":
            self.lower_hands(self.all_seats())
        elif c == "timer":
            try:
                minutes = max(1, min(int(msg.get("min", 5)), 240))
            except (TypeError, ValueError):
                return
            seats = self.all_seats()
            if seats:
                self._start_timer(seats, minutes, C.L("نشاط صفي", "Class activity"))
        elif c == "timer_stop" and self.timer_end is not None:
            self.server.send_many(self.all_seats(), {"t": "timer_stop"})
            self.timer_end = None
            self.btn_timer.setText(C.L("⏱ مؤقت", "⏱ Timer"))
            icons.iconify_button(self.btn_timer)

    def show_photo(self, path):
        """Show a photo (e.g. taken with the teacher's phone) on every student screen."""
        from PIL import Image, ImageOps
        try:
            img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        except Exception:
            self.log(C.L("📷 تعذر فتح الصورة", "📷 Could not open the photo"))
            return
        jpeg = C.encode_jpeg(img, 1920, 85)
        if self.caster.isRunning():
            self.caster.stop()
        if self.demo_sid:
            self._end_demo()
        self.server.start_broadcast(self.cmb_mode.currentData())
        self.server.publish(jpeg)
        self.photo_mode = True
        self.bar.btn_pause.setEnabled(False)
        self.bar.show_bar(C.L("● تُعرض صورة من الهاتف", "● Showing a photo from the phone"))
        self.log(C.L("📷 عُرضت صورة من الهاتف على الصف", "📷 Photo from the phone shown to the class"))

    def open_submissions(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.server.submissions_dir(dated=False)))

    def _theme_menu(self, menu, app_key):
        sub = menu.addMenu(C.L("🎨 المظهر والألوان", "🎨 Theme and colours"))
        for key, th in C.THEMES.items():
            act = sub.addAction(C.L(th["name_ar"], th["name_en"]))
            act.setCheckable(True)
            act.setChecked(key == C.THEME)
            act.triggered.connect(lambda _c, key=key, sub=sub: self._set_theme(key, app_key, sub))
        return sub

    def _set_theme(self, key, app_key, sub):
        C.apply_theme(key, app_key)
        for act, k in zip(sub.actions(), C.THEMES):
            act.setChecked(k == key)
        self.update()
        for w in QApplication.topLevelWidgets():
            w.update()

    def switch_language(self):
        new = "en" if C.LANG == "ar" else "ar"
        msg = C.L("سيُعاد تشغيل البرنامج باللغة الإنجليزية، ويعود الطلاب للاتصال تلقائيًا خلال ثوانٍ. متابعة؟",
                  "The program will restart in Arabic; students reconnect automatically within seconds. Continue?")
        if QMessageBox.question(self, "🌐", msg) != QMessageBox.Yes:
            return
        C.save_lang("Teacher", new)
        self._restarting = True
        self.close()

    def closeEvent(self, e):
        if not self._restarting and self.all_seats() and QMessageBox.question(
                self, C.L("إغلاق", "Close"), C.L("سيتم فصل جميع الطلاب وفتح شاشاتهم. إغلاق البرنامج؟", "All students will be disconnected and their screens unlocked. Close the program?")) != QMessageBox.Yes:
            e.ignore()
            return
        self._save_cast_settings()
        if self.caster.isRunning():
            self.caster.stop()
        self.server.send_many(self.all_seats(), {"t": "unlock"})
        self.server.close_all()
        self.web.stop()
        if self.phones_dlg:
            self.phones_dlg.close()
        self.bar.close()
        if self.overlay:
            self.overlay.close()
            self.annot_bar.close()
        if self.pick_dlg:
            self.pick_dlg.close()
        e.accept()
        if self._restarting:
            C.relaunch()
            QApplication.quit()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sabbora teacher console")
    parser.add_argument("--port", type=int, default=0, help=f"WebSocket port (default {C.WS_PORT})")
    parser.add_argument("--selftest", action="store_true", help="check this PC and exit")
    args = parser.parse_args(argv)
    C.install_excepthook("teacher")
    C.load_prefs("Teacher")
    C.enable_dpi_awareness()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Sabbora Teacher")
    app.setLayoutDirection(C.layout_direction())
    app.setStyleSheet(C.style())
    app.setWindowIcon(C.app_icon())
    app.setFont(QFont("Segoe UI", 10))
    if args.selftest:
        return C.run_selftest("teacher")
    w = TeacherWindow(args)
    w.show()
    return app.exec_()
