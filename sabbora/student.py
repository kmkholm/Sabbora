"""Sabbora student agent.

Finds the teacher on the network, shows the teacher's broadcast, sends live
screen thumbnails, and carries out the teacher's classroom commands. The
window always tells the student that the teacher can see the screen.
"""
import argparse
import getpass
import os
import platform
import socket
import sys
import time
import uuid

from PyQt5.QtCore import QLockFile, QRect, QSettings, QStandardPaths, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QDesktopServices, QFont, QLinearGradient, QPainter
from PyQt5.QtNetwork import QAbstractSocket, QHostAddress, QUdpSocket
from PyQt5.QtWebSockets import QWebSocket
from PyQt5.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QInputDialog,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QProgressBar,
                             QPushButton, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget)

from . import common as C
from . import icons


# ==========================================================================
# Capture thread: thumbnails normally, live frames when the teacher watches
# ==========================================================================
class Capturer(QThread):
    produced = pyqtSignal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active = False
        self.focus = False
        self.width = 1600
        self.quality = 70
        self.sharp = False
        self.fps = 12
        self.thumb_interval = 1.5
        self.thumb_width = 360
        self.awaiting = False
        self.sent_at = 0.0
        self.force = True
        self.monitor = None
        self._mon_at = 0.0
        self._running = True

    def stop(self):
        self._running = False
        self.wait(3000)

    def mon(self):
        if self.monitor is None or time.monotonic() - self._mon_at > 5:
            self.monitor = C.list_monitors()[0]
            self._mon_at = time.monotonic()
        return self.monitor

    def run(self):
        prev_raw, prev_small = None, None
        last_frame, last_thumb, last_thumb_sent = 0.0, 0.0, 0.0
        while self._running:
            if not self.active:
                time.sleep(0.2)
                continue
            try:
                now = time.monotonic()
                if self.focus:
                    if self.awaiting and now - self.sent_at < 3.0:
                        time.sleep(0.01)
                        continue
                    img = C.grab_monitor(self.mon())
                    raw = img.tobytes()
                    if self.force or raw != prev_raw or now - last_frame > 2.0:
                        self.force = False
                        prev_raw, last_frame = raw, now
                        data = C.encode_jpeg(img, self.width, self.quality, self.sharp)
                        self.awaiting, self.sent_at = True, time.monotonic()
                        self.produced.emit(C.B_FRAME, data)
                    time.sleep(max(0.005, 1.0 / max(1, self.fps) - (time.monotonic() - now)))
                else:
                    prev_raw = None
                    if self.force or now - last_thumb >= self.thumb_interval:
                        last_thumb = now
                        small = C.downscale(C.grab_monitor(self.mon()), self.thumb_width)
                        sraw = small.tobytes()
                        if self.force or sraw != prev_small or now - last_thumb_sent >= 10:
                            self.force = False
                            prev_small, last_thumb_sent = sraw, now
                            self.produced.emit(C.B_THUMB, C.encode_jpeg(small, 0, 55))
                    time.sleep(0.05)
            except Exception:
                time.sleep(1.0)


# ==========================================================================
# Full-screen windows
# ==========================================================================
def _place_fullscreen(widget, screen):
    widget.create()
    if widget.windowHandle():
        widget.windowHandle().setScreen(screen)
    widget.setGeometry(screen.geometry())
    widget.showFullScreen()


class BroadcastViewer(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setWindowTitle(C.L("سبّورة — شاشة المحاضر", "Sabbora — Teacher's screen"))
        self.pm = None
        self.active = False
        self.mode = "window"
        self._sized = False

    def start(self, mode):
        self.active = True
        self.mode = mode
        if mode == "full":
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
            _place_fullscreen(self, QApplication.primaryScreen())
        else:
            self.setWindowFlags(Qt.Window)
            if not self._sized:
                self.resize(1280, 760)
                self._sized = True
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def stop(self):
        self.active = False
        self.pm = None
        self.hide()

    def show_jpeg(self, data):
        pm = C.jpeg_pixmap(data)
        if pm is not None:
            self.pm = pm
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#000000"))
        if self.pm and not self.pm.isNull():
            sz = self.pm.size().scaled(self.size(), Qt.KeepAspectRatio)
            p.drawPixmap(QRect((self.width() - sz.width()) // 2, (self.height() - sz.height()) // 2,
                               sz.width(), sz.height()), self.pm)
        else:
            p.setPen(QColor("#B8C7C0"))
            p.setFont(QFont("Segoe UI", 16))
            p.drawText(self.rect(), Qt.AlignCenter, C.L("بانتظار صورة شاشة المحاضر...", "Waiting for the teacher's screen..."))

    def closeEvent(self, e):
        e.ignore()
        if self.mode != "full":
            self.hide()

    def keyPressEvent(self, e):
        if self.mode == "window" and e.key() in (Qt.Key_F11, Qt.Key_Escape):
            if self.isFullScreen() or e.key() == Qt.Key_Escape:
                self.showNormal()
            else:
                self.showFullScreen()

    def mouseDoubleClickEvent(self, _e):
        if self.mode == "window":
            self.showNormal() if self.isFullScreen() else self.showFullScreen()


class LockOverlay(QWidget):
    def __init__(self, screen, text):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.text = text
        _place_fullscreen(self, screen)

    def set_text(self, text):
        self.text = text
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor(C.T("lock1")))
        g.setColorAt(1, QColor(C.T("lock2")))
        p.fillRect(self.rect(), g)
        p.setPen(QColor(C.T("accent")))
        p.setFont(QFont("Segoe UI Emoji", 64))
        p.drawText(QRect(0, self.height() // 2 - 210, self.width(), 120), Qt.AlignCenter, "🔒")
        p.setPen(QColor("#FFFFFF"))
        p.setFont(QFont("Segoe UI", 30, QFont.Bold))
        p.drawText(QRect(0, self.height() // 2 - 80, self.width(), 70), Qt.AlignCenter, C.L("الشاشة مقفلة من المحاضر", "Screen locked by the teacher"))
        p.setPen(QColor("#CFE3D8"))
        p.setFont(QFont("Segoe UI", 18))
        p.drawText(QRect(80, self.height() // 2, self.width() - 160, 160), Qt.AlignHCenter | Qt.TextWordWrap, self.text)
        p.setFont(QFont("Segoe UI", 9))
        p.setPen(QColor("#7FA493"))
        p.drawText(QRect(0, self.height() - 40, self.width(), 30), Qt.AlignCenter, f"{C.app_title()} — {C.credit()}")

    def closeEvent(self, e):
        e.ignore()

    def keyPressEvent(self, e):
        e.accept()


class Countdown(QWidget):
    """Small always-on-top timer started by the teacher."""

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.end = 0.0
        self.title = ""
        self.done_at = None
        box = QFrame(self)
        box.setObjectName("Bar")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(16, 8, 16, 10)
        self.lbl_title = QLabel()
        self.lbl_title.setAlignment(Qt.AlignCenter)
        self.lbl_time = QLabel()
        self.lbl_time.setAlignment(Qt.AlignCenter)
        self.lbl_time.setFont(QFont("Segoe UI", 26, QFont.Bold))
        lay.addWidget(self.lbl_title)
        lay.addWidget(self.lbl_time)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)
        self.tick = QTimer(self)
        self.tick.timeout.connect(self._tick)

    def start(self, seconds, title):
        self.end = time.monotonic() + seconds
        self.title = title or C.L("الوقت المتبقي", "Time left")
        self.done_at = None
        self.lbl_title.setText(f"⏱ {self.title}")
        self._tick()
        self.adjustSize()
        self.setMinimumWidth(220)
        geo = QApplication.primaryScreen().availableGeometry()
        self.move(geo.right() - self.width() - 24, geo.top() + 24)
        self.show()
        self.raise_()
        self.tick.start(500)

    def stop(self):
        self.tick.stop()
        self.hide()

    def _tick(self):
        left = int(round(self.end - time.monotonic()))
        if left > 0:
            self.lbl_time.setText(f"{left // 60:02d}:{left % 60:02d}")
            self.lbl_time.setStyleSheet("color:#FF6B5B;" if left <= 10 else "color:#FFFFFF;")
            return
        if self.done_at is None:
            self.done_at = time.monotonic()
            self.lbl_time.setText(C.L("⏰ انتهى الوقت", "⏰ Time's up"))
            self.lbl_time.setStyleSheet("color:#F2C14E;")
            self.adjustSize()
            QApplication.beep()
        elif time.monotonic() - self.done_at > 8:
            self.stop()


class Popup(QDialog):
    """Always-on-top, non-blocking message from the teacher."""

    def __init__(self, title, text):
        super().__init__(None, Qt.WindowStaysOnTopHint | Qt.Dialog)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        head = QLabel(f"📣 {title}")
        head.setObjectName("Title")
        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setStyleSheet("font-size:13pt; padding:8px 2px;")
        ok = QPushButton(C.L("حسنًا", "OK"))
        ok.setObjectName("Primary")
        ok.clicked.connect(self.accept)
        lay.addWidget(head)
        lay.addWidget(body)
        lay.addWidget(ok, 0, Qt.AlignLeft)


class PollDialog(QDialog):
    def __init__(self, app, pid, question, options):
        super().__init__(None, Qt.WindowStaysOnTopHint | Qt.Dialog)
        self.app = app
        self.pid = pid
        self.setWindowTitle(C.L("تصويت من المحاضر", "Poll from the teacher"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        q = QLabel(f"📊 {question}")
        q.setObjectName("Title")
        q.setWordWrap(True)
        lay.addWidget(q)
        self.buttons = []
        for i, opt in enumerate(options):
            b = QPushButton(opt)
            b.setCheckable(True)
            b.setMinimumHeight(40)
            b.clicked.connect(lambda _c, i=i: self._vote(i))
            lay.addWidget(b)
            self.buttons.append(b)
        self.note = QLabel(C.L("اختر إجابة واحدة؛ يمكنك تغييرها قبل انتهاء التصويت.", "Choose one answer; you can change it until the poll ends."))
        self.note.setObjectName("Muted")
        lay.addWidget(self.note)
        self.bars = None

    def _vote(self, i):
        for j, b in enumerate(self.buttons):
            b.setChecked(j == i)
        self.app.send({"t": "vote", "pid": self.pid, "i": i})
        self.note.setText(C.L("✅ وصلت إجابتك إلى المحاضر.", "✅ Your answer reached the teacher."))

    def show_result(self, options, counts):
        total = max(1, sum(counts))
        if self.bars is None:
            self.bars = []
            self.layout().addWidget(QLabel(C.L("النتيجة:", "Result:")))
            for opt in options:
                bar = QProgressBar()
                bar.setMaximum(total)
                self.layout().addWidget(bar)
                self.bars.append((opt, bar))
        for (opt, bar), n in zip(self.bars, counts):
            bar.setMaximum(total)
            bar.setValue(n)
            bar.setFormat(f"{opt}: {n}")

    def end(self):
        for b in self.buttons:
            b.setEnabled(False)
        self.note.setText(C.L("انتهى التصويت.", "The poll has ended."))


# ==========================================================================
# Main student window
# ==========================================================================
class StudentApp(QWidget):
    def __init__(self, args):
        super().__init__()
        self.args = args
        self.settings = QSettings("Sabbora", "Student")
        sid = self.settings.value("sid", "", str)
        if not sid:
            sid = uuid.uuid4().hex[:12]
            self.settings.setValue("sid", sid)
        self.sid = f"{socket.gethostname()}-{getpass.getuser()}-{sid}"
        self.sock = None
        self.gen = 0
        self.lost_gen = -1
        self.connected = False
        self.welcomed = False
        self.want = False
        self.target = None
        self.code = ""
        self.course = ""
        self.locked = False
        self.locks = []
        self.recv = {}
        self.classes = {}
        self.poll = None
        self.popups = []
        self.uploads = {}
        self._up_fid = 0
        self._last_win = None
        self.countdown = Countdown()
        self._auto_waiting = False
        self.injector = C.InputInjector()
        self.blocker = C.KeyboardBlocker()
        self.viewer = BroadcastViewer()
        self.capturer = Capturer(self)
        self.capturer.produced.connect(self._send_capture)
        self.capturer.start()

        self.setWindowTitle(C.L(f"{C.app_title()} — الطالب", f"{C.APP_NAME} — Student"))
        self.setMinimumWidth(520)
        self._build_ui()
        self._build_tray()
        icons.iconify(self)

        self.udp = QUdpSocket(self)
        self.udp.bind(QHostAddress.AnyIPv4, C.DISCOVERY_PORT, QUdpSocket.ShareAddress | QUdpSocket.ReuseAddressHint)
        self.udp.readyRead.connect(self._on_beacon)
        t = QTimer(self)
        t.timeout.connect(self._prune_classes)
        t.start(2000)
        self._raise_timer = QTimer(self)
        self._raise_timer.timeout.connect(self._keep_on_top)
        self._raise_timer.start(800)
        self._win_timer = QTimer(self)
        self._win_timer.timeout.connect(self._report_window)
        self._win_timer.start(2000)

        if args.name:
            self.ed_name.setText(args.name)
        if args.code:
            self.ed_code.setText(args.code)
        if args.server:
            self.ed_host.setText(args.server)
        if args.auto:
            QTimer.singleShot(1500, self._auto_connect)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        header = QFrame()
        header.setObjectName("Header")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(18, 12, 18, 12)
        t = QLabel(C.L(f"{C.app_title()} — الطالب", f"{C.APP_NAME} — Student"))
        t.setObjectName("Brand")
        cr = QLabel(C.credit())
        cr.setObjectName("Credit")
        top = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(C.app_icon().pixmap(36, 36))
        top.addWidget(logo)
        top.addWidget(t, 1)
        b_lang = QPushButton("🌐 English" if C.LANG == "ar" else "🌐 العربية")
        b_lang.setObjectName("HeaderBtn")
        b_lang.clicked.connect(self.switch_language)
        top.addWidget(b_lang)
        hl.addLayout(top)
        hl.addWidget(cr)
        outer.addWidget(header)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)

        # page 0: join
        p0 = QWidget()
        g = QGridLayout(p0)
        g.setContentsMargins(18, 14, 18, 14)
        g.setVerticalSpacing(8)
        self.ed_name = QLineEdit(self.settings.value("name", "", str))
        self.ed_name.setPlaceholderText(C.L("اكتب اسمك الكامل", "Type your full name"))
        self.lst = QListWidget()
        self.lst.setMinimumHeight(110)
        self.lst.itemClicked.connect(lambda it: self.ed_host.setText(it.data(Qt.UserRole)))
        self.lst.itemDoubleClicked.connect(lambda it: (self.ed_host.setText(it.data(Qt.UserRole)), self.join()))
        self.ed_host = QLineEdit(self.settings.value("host", "", str))
        self.ed_host.setPlaceholderText(C.L("يُملأ تلقائيًا — أو اكتب مثل 192.168.1.10", "Filled automatically — or type e.g. 192.168.1.10"))
        self.ed_code = QLineEdit(self.settings.value("code", "", str))
        self.ed_code.setPlaceholderText(C.L("الرمز الظاهر على شاشة المحاضر", "The code shown on the teacher's screen"))
        self.ed_code.setMaxLength(12)
        self.btn_join = QPushButton(C.L("دخول المحاضرة", "Join lecture"))
        self.btn_join.setObjectName("Primary")
        self.btn_join.setMinimumHeight(40)
        self.btn_join.clicked.connect(self.join)
        self.ed_code.returnPressed.connect(self.join)
        self.chk_start = QCheckBox(C.L("تشغيل تلقائي مع بدء ويندوز", "Start automatically with Windows"))
        self.chk_start.setChecked(self._startup_enabled())
        self.chk_start.toggled.connect(self._set_startup)
        self.lbl_err = QLabel("")
        self.lbl_err.setObjectName("Err")
        self.lbl_err.setWordWrap(True)
        g.addWidget(QLabel(C.L("اسمك:", "Your name:")), 0, 0)
        g.addWidget(self.ed_name, 0, 1)
        g.addWidget(QLabel(C.L("المحاضرات المتاحة على الشبكة:", "Lectures found on the network:")), 1, 0, 1, 2)
        g.addWidget(self.lst, 2, 0, 1, 2)
        g.addWidget(QLabel(C.L("عنوان المحاضر:", "Teacher address:")), 3, 0)
        g.addWidget(self.ed_host, 3, 1)
        g.addWidget(QLabel(C.L("رمز الصف:", "Class code:")), 4, 0)
        g.addWidget(self.ed_code, 4, 1)
        g.addWidget(self.btn_join, 5, 0, 1, 2)
        g.addWidget(self.lbl_err, 6, 0, 1, 2)
        g.addWidget(self.chk_start, 7, 0, 1, 2)
        self.stack.addWidget(p0)

        # page 1: in class
        p1 = QWidget()
        v = QVBoxLayout(p1)
        v.setContentsMargins(18, 14, 18, 14)
        self.lbl_course = QLabel()
        self.lbl_course.setObjectName("Title")
        self.lbl_course.setWordWrap(True)
        self.lbl_state = QLabel()
        self.lbl_state.setObjectName("Ok")
        notice = QLabel(C.L("👁 أثناء الاتصال يستطيع المحاضر رؤية شاشتك، ويمكنه قفلها أو التحكم بها لمساعدتك.", "👁 While connected, the teacher can see your screen and may lock or control it to help you."))
        notice.setObjectName("Muted")
        notice.setWordWrap(True)
        row = QHBoxLayout()
        self.btn_hand = QPushButton(C.L("✋ رفع اليد", "✋ Raise hand"))
        self.btn_hand.setCheckable(True)
        self.btn_hand.toggled.connect(self._hand)
        b_chat = QPushButton(C.L("💬 رسالة للمحاضر", "💬 Message the teacher"))
        b_chat.clicked.connect(self.chat)
        self.btn_show = QPushButton(C.L("📺 عرض شاشة المحاضر", "📺 Show teacher's screen"))
        self.btn_show.clicked.connect(lambda: self.viewer.active and self.viewer.start(self.viewer.mode))
        self.btn_show.setEnabled(False)
        for b in (self.btn_hand, b_chat, self.btn_show):
            b.setMinimumHeight(38)
            row.addWidget(b)
        self.btn_submit = QPushButton(C.L("📤 تسليم ملف للمحاضر", "📤 Submit a file to the teacher"))
        self.btn_submit.setMinimumHeight(38)
        self.btn_submit.clicked.connect(lambda: self.submit_file())
        self.lbl_up = QLabel("")
        self.lbl_up.setObjectName("Muted")
        row2 = QHBoxLayout()
        b_files = QPushButton(C.L("📂 الملفات المستلمة", "📂 Received files"))
        b_files.clicked.connect(self.open_files)
        b_leave = QPushButton(C.L("خروج من المحاضرة", "Leave lecture"))
        b_leave.setObjectName("Danger")
        b_leave.clicked.connect(self.leave)
        row2.addWidget(b_files)
        row2.addStretch(1)
        row2.addWidget(b_leave)
        v.addWidget(self.lbl_course)
        v.addWidget(self.lbl_state)
        v.addWidget(notice)
        v.addSpacing(8)
        v.addLayout(row)
        v.addWidget(self.btn_submit)
        v.addWidget(self.lbl_up)
        v.addStretch(1)
        v.addLayout(row2)
        self.stack.addWidget(p1)

    def _build_tray(self):
        self.tray = QSystemTrayIcon(C.app_icon(), self)
        self.tray.setToolTip(C.L(f"{C.app_title()} — الطالب", f"{C.APP_NAME} — Student"))
        m = QMenu()
        m.addAction(C.L("إظهار النافذة", "Show window"), self.bring_up)
        m.addAction(C.L("✋ رفع / إنزال اليد", "✋ Raise / lower hand"), lambda: self.btn_hand.setChecked(not self.btn_hand.isChecked()))
        m.addAction(C.L("💬 رسالة للمحاضر", "💬 Message the teacher"), self.chat)
        m.addAction(C.L("📂 الملفات المستلمة", "📂 Received files"), self.open_files)
        m.addAction(C.L("📤 تسليم ملف للمحاضر", "📤 Submit a file to the teacher"), lambda: self.submit_file())
        m.addAction("🌐 English / العربية", self.switch_language)
        self._theme_menu(m, "Student")
        m.addSeparator()
        m.addAction(C.L("إغلاق البرنامج", "Quit program"), self.quit_app)
        icons.iconify_menu(m)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: r == QSystemTrayIcon.Trigger and self.bring_up())
        self.tray.show()
        self._tray_menu = m

    def bring_up(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def notify(self, title, text):
        if self.tray.isVisible():
            self.tray.showMessage(title, text, QSystemTrayIcon.Information, 5000)

    # ------------------------------------------------------------ discovery
    def _on_beacon(self):
        while self.udp.hasPendingDatagrams():
            data, host, _port = self.udp.readDatagram(self.udp.pendingDatagramSize())
            try:
                msg = C.jload(data.decode("utf-8"))
            except UnicodeDecodeError:
                msg = None
            if not msg or msg.get("tag") != C.BEACON_TAG:
                continue
            ip = C.clean_ip(host.toString())
            port = int(msg.get("port") or C.WS_PORT)
            key = f"{ip}:{port}"
            self.classes[key] = (str(msg.get("course", ""))[:80], time.monotonic())
            self._refresh_classes()
            if getattr(self, "_auto_waiting", False) and not self.want:
                self._auto_waiting = False
                self.ed_host.setText(key)
                self.join()

    def _prune_classes(self):
        now = time.monotonic()
        stale = [k for k, (_c, t) in self.classes.items() if now - t > 7]
        for k in stale:
            del self.classes[k]
        if stale:
            self._refresh_classes()

    def _refresh_classes(self):
        current = self.lst.currentItem().data(Qt.UserRole) if self.lst.currentItem() else None
        self.lst.clear()
        for key, (course, _t) in sorted(self.classes.items()):
            it = QListWidgetItem(C.L(f"📚 {course or 'محاضرة'} — {key}", f"📚 {course or 'Lecture'} — {key}"))
            it.setData(Qt.UserRole, key)
            self.lst.addItem(it)
            if key == current:
                self.lst.setCurrentItem(it)
        if not self.ed_host.text().strip() and len(self.classes) == 1:
            self.ed_host.setText(next(iter(self.classes)))

    def _auto_connect(self):
        if self.ed_name.text().strip() and self.ed_code.text().strip():
            if self.ed_host.text().strip():
                self.join()
            else:
                self._auto_waiting = True
        else:
            self.bring_up()

    # ----------------------------------------------------------- connection
    def join(self):
        name = self.ed_name.text().strip()
        code = self.ed_code.text().strip()
        target = C.parse_hostport(self.ed_host.text())
        if not name:
            self.lbl_err.setText(C.L("اكتب اسمك أولًا.", "Type your name first."))
            return
        if not target:
            self.lbl_err.setText(C.L("لم يُعثر على المحاضر تلقائيًا؛ اكتب عنوانه كما يظهر على شاشته.", "The teacher was not found automatically; type the address shown on the teacher's screen."))
            return
        if not code:
            self.lbl_err.setText(C.L("اكتب رمز الصف الظاهر على شاشة المحاضر.", "Type the class code shown on the teacher's screen."))
            return
        self.lbl_err.setText(C.L("⏳ جارٍ الاتصال...", "⏳ Connecting..."))
        self._err_style("Muted")
        self.target, self.code, self.want = target, code, True
        self.btn_join.setEnabled(False)
        self._open()

    def _open(self):
        self.gen += 1
        gen = self.gen
        old, self.sock = self.sock, None
        if old is not None:
            old.abort()
            old.deleteLater()
        self.connected = False
        s = QWebSocket(parent=self)
        s.connected.connect(lambda g=gen: self._on_connected(g))
        s.disconnected.connect(lambda g=gen: self._on_lost(g))
        s.stateChanged.connect(lambda st, g=gen: st == QAbstractSocket.UnconnectedState and self._on_lost(g))
        s.textMessageReceived.connect(lambda txt, g=gen: g == self.gen and self._on_text(txt))
        s.binaryMessageReceived.connect(lambda d, g=gen: g == self.gen and self._on_binary(d.data()))
        self.sock = s
        host, port = self.target
        if ":" in host:
            host = f"[{host}]"
        s.open(QUrl(f"ws://{host}:{port}/"))
        QTimer.singleShot(7000, lambda g=gen: g == self.gen and not self.connected and self.sock and self.sock.abort())

    def _on_connected(self, gen):
        if gen != self.gen:
            return
        self.connected = True
        mon = C.list_monitors()[0]
        self.send({"t": "hello", "id": self.sid, "name": self.ed_name.text().strip(), "code": self.code,
                   "host": socket.gethostname(), "user": getpass.getuser(),
                   "os": f"{platform.system()} {platform.release()}", "mac": C.mac_address(),
                   "ver": C.VERSION, "screen": [mon[2], mon[3]]})

    def _on_lost(self, gen):
        if gen != self.gen or self.lost_gen == gen:
            return
        self.lost_gen = gen
        was_in = self.welcomed
        self.connected = False
        self._end_session()
        if self.want:
            if was_in:
                self.notify(C.L("انقطع الاتصال", "Connection lost"), C.L("جارٍ إعادة الاتصال بالمحاضر تلقائيًا...", "Reconnecting to the teacher automatically..."))
            self.lbl_state.setText(C.L("⏳ انقطع الاتصال — إعادة المحاولة...", "⏳ Connection lost — retrying..."))
            if self.stack.currentIndex() == 0:
                self.lbl_err.setText(C.L("⏳ تعذّر الوصول إلى المحاضر — إعادة المحاولة كل 3 ثوانٍ... "
                                     "(تأكد من العنوان ومن أنكما على نفس الشبكة)", "⏳ Cannot reach the teacher — retrying every 3 seconds... (check the address and that you are on the same network)"))
            QTimer.singleShot(3000, lambda g=gen: self.want and self.gen == g and self._open())
        else:
            self.btn_join.setEnabled(True)

    def _end_session(self):
        self.welcomed = False
        self.capturer.active = False
        self.capturer.focus = False
        self.viewer.stop()
        self.btn_show.setEnabled(False)
        self.unlock()
        for rec in self.recv.values():
            try:
                rec["f"].close()
                os.remove(rec["path"])
            except OSError:
                pass
        self.recv.clear()
        for rec in self.uploads.values():
            rec["f"].close()
        self.uploads.clear()
        self.lbl_up.setText("")
        self._last_win = None
        self.countdown.stop()
        if self.poll:
            self.poll.close()
            self.poll = None
        self._update_blocking()

    def leave(self):
        self.want = False
        if self.sock:
            self.sock.close()
        self._end_session()
        self.stack.setCurrentIndex(0)
        self.btn_join.setEnabled(True)
        self.lbl_err.setText("")
        self.tray.setToolTip(C.L(f"{C.app_title()} — غير متصل", f"{C.APP_NAME} — not connected"))

    def send(self, obj):
        if self.sock and self.connected:
            self.sock.sendTextMessage(C.jdump(obj))

    def _send_capture(self, kind, data):
        if self.sock and self.connected and self.welcomed:
            self.sock.sendBinaryMessage(bytes((kind,)) + data)
        elif kind == C.B_FRAME:
            self.capturer.awaiting = False

    # -------------------------------------------------------------- messages
    def _on_text(self, txt):
        m = C.jload(txt)
        if not m:
            return
        t = m.get("t")
        handler = getattr(self, f"_m_{t}", None)
        if handler:
            handler(m)

    def _on_binary(self, data):
        if not data:
            return
        kind, body = data[0], data[1:]
        if kind == C.B_BROADCAST:
            if self.viewer.active:
                self.viewer.show_jpeg(body)
            self.send({"t": "ack_b"})
        elif kind == C.B_FILE:
            self._file_chunk(body)

    def _m_welcome(self, m):
        self.welcomed = True
        self.course = str(m.get("course", ""))
        name = self.ed_name.text().strip()
        self.settings.setValue("name", name)
        self.settings.setValue("host", self.ed_host.text().strip())
        self.settings.setValue("code", self.code)
        self.capturer.thumb_interval = float(m.get("thumb_interval", 1.5))
        self.capturer.thumb_width = int(m.get("thumb_width", 360))
        self.capturer.focus = False
        self.capturer.force = True
        self.capturer.active = True
        self.lbl_course.setText(f"📚 {self.course}")
        self.lbl_state.setText(C.L(f"✅ متصل باسم «{name}»", f"✅ Connected as «{name}»"))
        self.lbl_err.setText("")
        self.stack.setCurrentIndex(1)
        self.btn_join.setEnabled(True)
        self.tray.setToolTip(C.L(f"{C.app_title()} — متصل: {self.course}\nالمحاضر يستطيع رؤية شاشتك", f"{C.APP_NAME} — connected: {self.course}\nThe teacher can see your screen"))
        if self.btn_hand.isChecked():
            self.send({"t": "hand", "up": True})

    def _m_reject(self, m):
        self.want = False
        self.btn_join.setEnabled(True)
        self._err_style("Err")
        self.lbl_err.setText(C.L("❌ رمز الصف غير صحيح. اكتب الرمز الظاهر على شاشة المحاضر.", "❌ Wrong class code. Type the code shown on the teacher's screen."))
        self.stack.setCurrentIndex(0)
        self.bring_up()

    def _m_kick(self, _m):
        self.leave()
        self.lbl_err.setText(C.L("أنهى المحاضر اتصالك.", "The teacher disconnected you."))
        self.bring_up()

    def _m_bye(self, _m):
        self._end_session()
        self.lbl_state.setText(C.L("⏸ أغلق المحاضر الجلسة — سيُعاد الاتصال تلقائيًا عند فتحها.", "⏸ The teacher closed the session — you will reconnect automatically when it reopens."))

    def _m_bstart(self, m):
        self.viewer.start("full" if m.get("mode") == "full" else "window")
        self.btn_show.setEnabled(self.viewer.mode == "window")
        self._update_blocking()
        self.send({"t": "status", "watching": True})

    def _m_bstop(self, _m):
        self.viewer.stop()
        self.btn_show.setEnabled(False)
        self._update_blocking()
        self.send({"t": "status", "watching": False})

    def _m_lock(self, m):
        self.lock(str(m.get("text", "")))

    def _m_unlock(self, _m):
        self.unlock()

    def _m_msg(self, m):
        QApplication.beep()
        self.popup(C.L("رسالة من المحاضر", "Message from the teacher"), str(m.get("text", "")))

    def _m_url(self, m):
        url = QUrl(str(m.get("url", "")))
        if url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)

    def _m_run(self, m):
        if not C.run_program(str(m.get("cmd", ""))):
            self.notify(C.L("تعذّر التشغيل", "Could not start"), str(m.get("cmd", "")))

    def _m_power(self, m):
        action = m.get("action")
        if action in ("shutdown", "restart", "logoff"):
            label = {"shutdown": C.L("إيقاف التشغيل", "Shut down"), "restart": C.L("إعادة التشغيل", "Restart"), "logoff": C.L("تسجيل الخروج", "Log off")}[action]
            self.popup(C.L("تنبيه", "Notice"), C.L(f"طلب المحاضر {label} لهذا الجهاز خلال ثوانٍ. احفظ عملك الآن.", f"The teacher requested {label} for this PC in a few seconds. Save your work now."))
            C.power_action(action)

    def _m_focus(self, m):
        on = bool(m.get("on"))
        if on:
            self.capturer.width = int(m.get("width", 1600))
            self.capturer.quality = int(m.get("quality", 70))
            self.capturer.sharp = bool(m.get("sharp", False))
            self.capturer.fps = int(m.get("fps", 12))
        self.capturer.awaiting = False
        self.capturer.force = True
        self.capturer.focus = on

    def _m_ack_f(self, _m):
        self.capturer.awaiting = False

    def _m_input(self, m):
        if not self.injector.available:
            return
        mon = self.capturer.mon()
        k = m.get("k")
        try:
            if k in ("move", "down", "up", "wheel") and "x" in m:
                self.injector.move_norm(mon, m["x"], m["y"])
            if k == "down":
                self.injector.button(str(m.get("b", "l")), True)
            elif k == "up":
                self.injector.button(str(m.get("b", "l")), False)
            elif k == "wheel":
                self.injector.wheel(int(m.get("d", 0)))
            elif k == "key":
                self.injector.key(int(m.get("vk", 0)), bool(m.get("down")), str(m.get("text", "")))
        except (TypeError, ValueError):
            pass

    def _m_hand_down(self, _m):
        self.btn_hand.blockSignals(True)
        self.btn_hand.setChecked(False)
        self.btn_hand.blockSignals(False)

    def _m_poll(self, m):
        opts = [str(o) for o in m.get("opts", [])][:8]
        if len(opts) < 2:
            return
        if self.poll:
            self.poll.close()
        self.poll = PollDialog(self, m.get("pid"), str(m.get("q", "")), opts)
        self.poll.show()
        self.poll.raise_()
        QApplication.beep()

    def _m_poll_result(self, m):
        if self.poll and self.poll.pid == m.get("pid"):
            self.poll.show_result([str(o) for o in m.get("opts", [])], [int(c) for c in m.get("counts", [])])

    def _m_poll_end(self, m):
        if self.poll and self.poll.pid == m.get("pid"):
            self.poll.end()

    # ----------------------------------------------------------------- files
    def _m_timer(self, m):
        try:
            seconds = max(1, min(int(m.get("seconds", 60)), 6 * 3600))
        except (TypeError, ValueError):
            return
        self.countdown.start(seconds, str(m.get("title", ""))[:80])

    def _m_timer_stop(self, _m):
        self.countdown.stop()

    def _m_clip(self, m):
        text = str(m.get("text", ""))
        QApplication.clipboard().setText(text)
        self.notify(C.L("📋 نص من المحاضر", "📋 Text from the teacher"),
                    C.L("نُسخ إلى الحافظة — الصقه بـ Ctrl+V", "Copied to your clipboard — paste with Ctrl+V"))

    def _m_kill(self, m):
        name = str(m.get("name", ""))
        if C.kill_program(name):
            self.notify(C.app_title(), C.L(f"أغلق المحاضر البرنامج {name}", f"The teacher closed {name}"))

    def _m_pick(self, _m):
        QApplication.beep()
        self.popup("🎲", C.L("وقع عليك الاختيار للإجابة!", "You have been picked to answer!"))

    def _m_collect(self, m):
        title = str(m.get("title", ""))[:120]
        QApplication.beep()
        dlg = Popup(C.L("طلب تسليم", "Assignment request"),
                    C.L(f"يطلب المحاضر تسليم: «{title}»\nاضغط الزر لاختيار ملفك.",
                        f"The teacher asks you to submit: «{title}»\nPress the button to choose your file."))
        b = QPushButton(C.L("📤 اختيار الملف وتسليمه", "📤 Choose file and submit"))
        b.setObjectName("Primary")
        b.clicked.connect(lambda: (dlg.accept(), self.submit_file()))
        icons.iconify_button(b)
        dlg.layout().insertWidget(2, b)
        self.popups.append(dlg)
        dlg.finished.connect(lambda _r, d=dlg: d in self.popups and self.popups.remove(d))
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    # ----------------------------------------------------------- submissions
    def submit_file(self, path=None):
        if not self.welcomed:
            self.notify(C.app_title(), C.L("ادخل المحاضرة أولًا.", "Join the lecture first."))
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, C.L("اختر الملف الذي تريد تسليمه", "Choose the file to submit"))
        if not path:
            return
        size = os.path.getsize(path)
        if size > C.MAX_UPLOAD_BYTES:
            self.popup(C.L("ملف كبير", "File too large"), C.L("الحد الأقصى للتسليم 200 ميغابايت.", "The submission limit is 200 MB."))
            return
        try:
            f = open(path, "rb")
        except OSError:
            return
        self._up_fid += 1
        fid = self._up_fid
        chunks = (size + C.FILE_CHUNK - 1) // C.FILE_CHUNK
        name = os.path.basename(path)
        self.uploads[fid] = {"f": f, "name": name, "size": size, "chunks": chunks, "next": 0, "acked": 0}
        self.send({"t": "up_begin", "fid": fid, "name": name, "size": size, "chunks": chunks})
        self._pump_upload(fid)

    def _pump_upload(self, fid):
        rec = self.uploads.get(fid)
        if not rec or not (self.sock and self.connected):
            return
        while rec["next"] < rec["chunks"] and rec["next"] - rec["acked"] < C.FILE_WINDOW:
            data = rec["f"].read(C.FILE_CHUNK)
            self.sock.sendBinaryMessage(C.pack_chunk(C.B_UPLOAD, fid, rec["next"], data))
            rec["next"] += 1
        pct = 100 * rec["acked"] // max(1, rec["chunks"])
        self.lbl_up.setText(C.L(f"📤 جارٍ تسليم «{rec['name']}»: {pct}%", f"📤 Submitting «{rec['name']}»: {pct}%"))
        if rec["acked"] >= rec["chunks"]:
            rec["f"].close()
            self.send({"t": "up_end", "fid": fid})

    def _m_up_ack(self, m):
        rec = self.uploads.get(int(m.get("fid", -1)))
        if rec:
            rec["acked"] = max(rec["acked"], int(m.get("n", 0)))
            self._pump_upload(int(m.get("fid")))

    def _m_up_ok(self, m):
        rec = self.uploads.pop(int(m.get("fid", -1)), None)
        if rec:
            self.lbl_up.setText(C.L(f"✅ سُلّم «{rec['name']}» بنجاح", f"✅ «{rec['name']}» submitted"))
            self.notify(C.L("✅ تم التسليم", "✅ Submitted"), rec["name"])

    def _m_up_reject(self, m):
        rec = self.uploads.pop(int(m.get("fid", -1)), None)
        if rec:
            rec["f"].close()
            self.lbl_up.setText(C.L(f"❌ رفض المحاضر استلام «{rec['name']}»", f"❌ The teacher could not accept «{rec['name']}»"))

    def _report_window(self):
        if not self.welcomed:
            return
        proc, title = C.foreground_window()
        text = f"{proc} — {title}" if title else proc
        text = text[:200]
        if text != self._last_win:
            self._last_win = text
            self.send({"t": "status", "win": text})

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
        C.save_lang("Student", new)
        if self.welcomed and "--auto" not in sys.argv:
            sys.argv.append("--auto")
        self.want = False
        if self.sock:
            self.sock.close()
        self._end_session()
        self.blocker.stop()
        self.capturer.stop()
        self.tray.hide()
        lock = QApplication.instance().property("sabbora_lock")
        if lock is not None:
            lock.unlock()
        C.relaunch()
        QApplication.quit()

    def files_dir(self):
        base = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or os.path.expanduser("~")
        path = os.path.join(base, "Sabbora Files")
        os.makedirs(path, exist_ok=True)
        return path

    def open_files(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.files_dir()))

    def _m_file_begin(self, m):
        try:
            fid = int(m["fid"])
        except (KeyError, TypeError, ValueError):
            return
        name = C.safe_filename(str(m.get("name", "file")))
        path = C.unique_path(self.files_dir(), name)
        try:
            f = open(path, "wb")
        except OSError:
            return
        self.recv[fid] = {"f": f, "path": path, "name": name, "n": 0}
        self.notify(C.L("استلام ملف", "Receiving file"), C.L(f"يرسل المحاضر الملف «{name}»...", f"The teacher is sending «{name}»..."))

    def _file_chunk(self, body):
        parsed = C.unpack_file_chunk(body)
        if not parsed:
            return
        fid, index, data = parsed
        rec = self.recv.get(fid)
        if not rec or index != rec["n"]:
            return
        rec["f"].write(data)
        rec["n"] += 1
        self.send({"t": "file_ack", "fid": fid, "n": rec["n"]})

    def _m_file_end(self, m):
        rec = self.recv.pop(int(m.get("fid", -1)), None)
        if not rec:
            return
        rec["f"].close()
        self.send({"t": "file_ok", "name": rec["name"]})
        self.notify(C.L("✅ تم استلام ملف", "✅ File received"), C.L(f"«{rec['name']}» في مجلد المستندات/Sabbora Files", f"«{rec['name']}» in Documents/Sabbora Files"))

    # ------------------------------------------------------ lock / blocking
    def lock(self, text):
        self.locked = True
        if not self.locks:
            self.locks = [LockOverlay(scr, text) for scr in QApplication.screens()]
        else:
            for w in self.locks:
                w.set_text(text)
        self._update_blocking()
        self.send({"t": "status", "locked": True})

    def unlock(self):
        was = self.locked
        self.locked = False
        for w in self.locks:
            w.hide()
            w.deleteLater()
        self.locks = []
        self._update_blocking()
        if was:
            self.send({"t": "status", "locked": False})

    def _update_blocking(self):
        want = self.locked or (self.viewer.active and self.viewer.mode == "full")
        if want and not self.blocker.active:
            self.blocker.start()
        elif not want and self.blocker.active:
            self.blocker.stop()

    def _keep_on_top(self):
        if self.locks:
            for w in self.locks:
                w.raise_()
            self.locks[0].activateWindow()
        elif self.viewer.active and self.viewer.mode == "full":
            self.viewer.raise_()
            self.viewer.activateWindow()

    # ---------------------------------------------------------------- misc
    def popup(self, title, text):
        dlg = Popup(title, text)
        self.popups.append(dlg)
        dlg.finished.connect(lambda _r, d=dlg: d in self.popups and self.popups.remove(d))
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _err_style(self, name):
        self.lbl_err.setObjectName(name)
        self.lbl_err.style().unpolish(self.lbl_err)
        self.lbl_err.style().polish(self.lbl_err)

    def _hand(self, up):
        self.btn_hand.setText(C.L("👇 إنزال اليد", "👇 Lower hand") if up else C.L("✋ رفع اليد", "✋ Raise hand"))
        icons.iconify_button(self.btn_hand)
        self.send({"t": "hand", "up": up})

    def chat(self):
        if not self.welcomed:
            return
        text, ok = QInputDialog.getMultiLineText(self, C.L("رسالة للمحاضر", "Message the teacher"), C.L("اكتب رسالتك أو سؤالك:", "Type your message or question:"))
        if ok and text.strip():
            self.send({"t": "chat", "text": text.strip()[:2000]})
            self.notify(C.L("تم الإرسال", "Sent"), C.L("وصلت رسالتك إلى المحاضر.", "Your message reached the teacher."))

    @staticmethod
    def _startup_command():
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}" --auto'
        pyw = sys.executable.replace("python.exe", "pythonw.exe")
        return f'"{pyw}" "{os.path.abspath(sys.argv[0])}" --auto'

    @staticmethod
    def _startup_enabled():
        if not C.IS_WIN:
            return False
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                winreg.QueryValueEx(k, "Sabbora Student")
                return True
        except OSError:
            return False

    def _set_startup(self, on):
        if not C.IS_WIN:
            return
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                                winreg.KEY_SET_VALUE) as k:
                if on:
                    winreg.SetValueEx(k, "Sabbora Student", 0, winreg.REG_SZ, self._startup_command())
                else:
                    winreg.DeleteValue(k, "Sabbora Student")
        except OSError:
            pass

    def closeEvent(self, e):
        if self.want:
            e.ignore()
            self.hide()
            self.notify(C.app_title(), C.L("البرنامج يعمل في الخلفية وما زلت متصلًا بالمحاضرة.", "The program keeps running in the background and you are still connected."))
        else:
            e.ignore()
            self.quit_app()

    def quit_app(self):
        if self.welcomed and QMessageBox.question(
                self, C.L("إغلاق", "Close"), C.L("أنت متصل بالمحاضرة الآن. هل تريد الخروج من البرنامج؟", "You are connected to the lecture. Quit the program?")) != QMessageBox.Yes:
            return
        self.want = False
        if self.sock:
            self.sock.close()
        self._end_session()
        self.blocker.stop()
        self.capturer.stop()
        self.tray.hide()
        QApplication.quit()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sabbora student agent")
    parser.add_argument("--server", default="", help="teacher address, e.g. 192.168.1.10 or 192.168.1.10:47000")
    parser.add_argument("--code", default="", help="class code")
    parser.add_argument("--name", default="", help="student name")
    parser.add_argument("--auto", action="store_true", help="connect automatically and start in the tray")
    parser.add_argument("--selftest", action="store_true", help="check this PC and exit")
    args = parser.parse_args(argv)
    C.install_excepthook("student")
    C.load_prefs("Student")
    C.enable_dpi_awareness()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Sabbora Student")
    app.setQuitOnLastWindowClosed(False)
    app.setLayoutDirection(C.layout_direction())
    app.setStyleSheet(C.style())
    app.setWindowIcon(C.app_icon())
    app.setFont(QFont("Segoe UI", 10))
    if args.selftest:
        return C.run_selftest("student")
    lock = QLockFile(os.path.join(C.data_dir(), "student.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, C.app_title(), C.L("برنامج سبّورة للطالب يعمل بالفعل (انظر أيقونته بجانب الساعة).", "Sabbora Student is already running (see its icon next to the clock)."))
        return 0
    app.setProperty("sabbora_lock", lock)
    w = StudentApp(args)
    if not (args.auto and w.ed_name.text().strip() and w.ed_code.text().strip()):
        w.show()
    rc = app.exec_()
    if lock.isLocked():
        lock.unlock()
    return rc
