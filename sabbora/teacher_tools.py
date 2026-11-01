"""Teaching tools for the Sabbora teacher console: a pen/whiteboard overlay that
students see through the broadcast, and the random-student picker."""
from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QListView, QListWidget,
                             QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from . import common as C
from . import icons

PEN_COLORS = ["#E53935", "#1E88E5", "#43A047", "#FDD835", "#212121", "#FFFFFF"]
PEN_WIDTHS = [3, 6, 12]


class AnnotationOverlay(QWidget):
    """Full-screen layer for drawing over anything on the teacher's screen.
    It is a layered window, so the broadcaster captures it with layered=True."""

    def __init__(self, on_close):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.on_close = on_close
        self.strokes = []
        self.cur = None
        self.color = QColor(PEN_COLORS[0])
        self.width = PEN_WIDTHS[0]
        self.marker = False
        self.board = None          # None (transparent), "white" or "black"
        self.passthrough = False
        self.setCursor(Qt.CrossCursor)

    def open_on(self, screen, board=None):
        self.board = board
        self.create()
        if self.windowHandle():
            self.windowHandle().setScreen(screen)
        self.setGeometry(screen.geometry())
        self.show()
        self.raise_()
        self.activateWindow()
        self.update()

    def set_board(self, board):
        self.board = board
        self.update()

    def set_passthrough(self, on):
        """On: clicks go to the programs underneath (e.g. next slide) while the ink stays."""
        self.passthrough = on
        geo = self.geometry()
        self.setWindowFlag(Qt.WindowTransparentForInput, on)
        self.setGeometry(geo)
        self.show()

    def _pen(self, color, width, marker):
        c = QColor(color)
        if marker:
            c.setAlpha(110)
        pen = QPen(c, width * (3 if marker else 1))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        return pen

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.board == "white":
            p.fillRect(self.rect(), QColor("#FAFAF7"))
        elif self.board == "black":
            p.fillRect(self.rect(), QColor("#1E3B2F"))
        else:
            p.fillRect(self.rect(), QColor(0, 0, 0, 1))   # alpha 1 keeps mouse clicks on the layer
        for path, color, width, marker in self.strokes + ([self.cur] if self.cur else []):
            p.strokePath(path, self._pen(color, width, marker))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            path = QPainterPath(QPointF(e.pos()))
            path.lineTo(QPointF(e.pos()) + QPointF(0.1, 0.1))
            self.cur = (path, QColor(self.color), self.width, self.marker)
            self.update()
        elif e.button() == Qt.RightButton:
            self.undo()

    def mouseMoveEvent(self, e):
        if self.cur and e.buttons() & Qt.LeftButton:
            self.cur[0].lineTo(QPointF(e.pos()))
            self.update()

    def mouseReleaseEvent(self, e):
        if self.cur and e.button() == Qt.LeftButton:
            self.strokes.append(self.cur)
            self.cur = None
            self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.on_close()
        elif e.key() == Qt.Key_Z and e.modifiers() & Qt.ControlModifier:
            self.undo()

    def undo(self):
        if self.strokes:
            self.strokes.pop()
            self.update()

    def clear(self):
        self.strokes.clear()
        self.update()


class AnnotationBar(QWidget):
    """Pen toolbar; hidden from the broadcast so students only see the ink."""

    def __init__(self, overlay, on_close):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.overlay = overlay
        self._drag = None
        box = QFrame(self)
        box.setObjectName("Bar")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(4)
        grip = QLabel("⠿ 🖊")
        grip.setToolTip(C.L("اسحب لتحريك الشريط", "Drag to move the toolbar"))
        lay.addWidget(grip)
        self.color_btns = []
        for col in PEN_COLORS:
            b = QPushButton("")
            b.setCheckable(True)
            b.setFixedSize(26, 26)
            b.setStyleSheet(f"QPushButton{{background:{col}; border:2px solid #9FB3AA; border-radius:13px;}}"
                            "QPushButton:checked{border:3px solid #F2A541;}")
            b.clicked.connect(lambda _c, col=col, b=b: self._color(col, b))
            lay.addWidget(b)
            self.color_btns.append(b)
        self.color_btns[0].setChecked(True)
        self.width_btns = []
        for w, label in zip(PEN_WIDTHS, ("•", "●", "⬤")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setToolTip(C.L("سُمك القلم", "Pen size"))
            b.clicked.connect(lambda _c, w=w, b=b: self._width(w, b))
            lay.addWidget(b)
            self.width_btns.append(b)
        self.width_btns[0].setChecked(True)
        self.btn_marker = QPushButton(C.L("🖍 تظليل", "🖍 Marker"))
        self.btn_marker.setCheckable(True)
        self.btn_marker.toggled.connect(lambda on: setattr(overlay, "marker", on))
        self.btn_mouse = QPushButton(C.L("🖱 ماوس", "🖱 Mouse"))
        self.btn_mouse.setCheckable(True)
        self.btn_mouse.setToolTip(C.L("يبقى الرسم ظاهرًا وتعود النقرات للبرامج (مثل تقليب الشرائح)",
                                      "Ink stays visible while clicks go to programs (e.g. next slide)"))
        self.btn_mouse.toggled.connect(self._mouse)
        b_undo = QPushButton("↶")
        b_undo.setToolTip(C.L("تراجع (Ctrl+Z أو زر الماوس الأيمن)", "Undo (Ctrl+Z or right-click)"))
        b_undo.clicked.connect(overlay.undo)
        b_clear = QPushButton("🗑")
        b_clear.setToolTip(C.L("مسح الكل", "Clear all"))
        b_clear.clicked.connect(overlay.clear)
        self.board_btns = {}
        for key, label, tip in ((None, C.L("شفاف", "Clear"), C.L("شفاف فوق الشاشة", "Transparent over the screen")),
                                ("white", C.L("أبيض", "White"), C.L("سبورة بيضاء", "Whiteboard")),
                                ("black", C.L("أخضر", "Green"), C.L("سبورة خضراء", "Chalkboard"))):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.clicked.connect(lambda _c, key=key: self.set_board(key))
            self.board_btns[key] = b
        b_close = QPushButton(C.L("✖ إغلاق", "✖ Close"))
        b_close.clicked.connect(on_close)
        for w in (self.btn_marker, self.btn_mouse, b_undo, b_clear, *self.board_btns.values(), b_close):
            lay.addWidget(w)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)
        icons.iconify(self)

    def _color(self, col, btn):
        for b in self.color_btns:
            b.setChecked(b is btn)
        self.overlay.color = QColor(col)

    def _width(self, w, btn):
        for b in self.width_btns:
            b.setChecked(b is btn)
        self.overlay.width = w

    def _mouse(self, on):
        self.overlay.set_passthrough(on)
        self.raise_()

    def set_board(self, key):
        for k, b in self.board_btns.items():
            b.setChecked(k == key)
        self.overlay.set_board(key)
        if key and self.btn_mouse.isChecked():
            self.btn_mouse.setChecked(False)

    def show_on(self, screen):
        self.adjustSize()
        geo = screen.availableGeometry()
        self.move(geo.center().x() - self.width() // 2, geo.bottom() - self.height() - 16)
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


class PickDialog(QDialog):
    """Big name card for the random-student picker (visible in the broadcast)."""

    def __init__(self, parent, name, again):
        super().__init__(parent, Qt.WindowStaysOnTopHint | Qt.Dialog)
        self.setWindowTitle(C.L("🎲 اختيار عشوائي", "🎲 Random pick"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        top = QLabel("🎲")
        top.setAlignment(Qt.AlignCenter)
        top.setFont(QFont("Segoe UI Emoji", 40))
        self.name = QLabel(name)
        self.name.setAlignment(Qt.AlignCenter)
        self.name.setFont(QFont("Segoe UI", 28, QFont.Bold))
        self.name.setObjectName("Title")
        row = QHBoxLayout()
        b_again = QPushButton(C.L("🎲 اختيار آخر", "🎲 Pick again"))
        b_again.clicked.connect(again)
        b_ok = QPushButton(C.L("حسنًا", "OK"))
        b_ok.setObjectName("Primary")
        b_ok.clicked.connect(self.accept)
        row.addWidget(b_again)
        row.addStretch(1)
        row.addWidget(b_ok)
        lay.addWidget(top)
        lay.addWidget(self.name)
        lay.addLayout(row)
        icons.iconify(self)

    def set_name(self, name):
        self.name.setText(name)


class WindowPicker(QDialog):
    """Choose one open window to share (live thumbnails)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(C.L("اختر النافذة التي تريد بثّها", "Choose the window to share"))
        self.resize(900, 600)
        self.chosen = None
        lay = QVBoxLayout(self)
        hint = QLabel(C.L("يرى الطلاب هذه النافذة فقط، حتى لو فتحت فوقها نوافذ أخرى. "
                          "لعرض PowerPoint اختر «PowerPoint — يتبع العرض تلقائيًا» من القائمة.",
                          "Students see only this window, even if other windows cover it. "
                          "For PowerPoint choose «PowerPoint — follows the slide show» in the list."))
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        lay.addWidget(hint)
        self.list = QListWidget()
        self.list.setViewMode(QListView.IconMode)
        self.list.setIconSize(QSize(240, 140))
        self.list.setGridSize(QSize(270, 200))
        self.list.setResizeMode(QListView.Adjust)
        self.list.setMovement(QListView.Static)
        self.list.setWordWrap(True)
        self.list.itemDoubleClicked.connect(self._accept)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        b_ref = QPushButton(C.L("↶ تحديث القائمة", "↶ Refresh"))
        b_ref.clicked.connect(self.refresh)
        b_ok = QPushButton(C.L("▶ بث هذه النافذة", "▶ Share this window"))
        b_ok.setObjectName("Primary")
        b_ok.clicked.connect(lambda: self._accept(self.list.currentItem()))
        b_cancel = QPushButton(C.L("إلغاء", "Cancel"))
        b_cancel.clicked.connect(self.reject)
        row.addWidget(b_ref)
        row.addStretch(1)
        row.addWidget(b_cancel)
        row.addWidget(b_ok)
        lay.addLayout(row)
        icons.iconify(self)
        self.refresh()

    def refresh(self):
        self.list.clear()
        for w in C.list_windows():
            item = QListWidgetItem(f"{w['title'][:60]}\n{w['proc']}")
            item.setData(Qt.UserRole, (w["hwnd"], w["title"]))
            shot = C.grab_window(w["hwnd"])
            pm = C.jpeg_pixmap(C.encode_jpeg(shot[0], 240, 70)) if shot else None
            if pm is not None:
                item.setIcon(QIcon(pm))
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _accept(self, item):
        if item is not None:
            self.chosen = item.data(Qt.UserRole)
            self.accept()


class PhonesDialog(QDialog):
    """QR codes: students join from any phone/browser; the teacher's phone becomes a remote."""

    def __init__(self, win):
        super().__init__(win)
        from . import qr
        self._qr = qr
        self.win = win
        self.setWindowTitle(C.L("الهواتف والمتصفح", "Phones & browsers"))
        self.setMinimumWidth(820)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel(C.L("عنوان الشبكة:", "Network address:")))
        from PyQt5.QtWidgets import QComboBox
        self.cmb_ip = QComboBox()
        self.cmb_ip.currentIndexChanged.connect(self._render)
        top.addWidget(self.cmb_ip, 1)
        lay.addLayout(top)
        hint = QLabel(C.L("يجب أن تكون الهواتف متصلة بنفس شبكة الواي فاي التي عليها جهازك. لا يحتاج الطلاب لتثبيت أي شيء.",
                          "Phones must be on the same Wi-Fi as this PC. Students install nothing."))
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        lay.addWidget(hint)
        cards = QHBoxLayout()
        # students
        sbox = QFrame()
        sbox.setObjectName("Tile")
        sl = QVBoxLayout(sbox)
        st = QLabel(C.L("📱 الطلاب: امسح للدخول", "📱 Students: scan to join"))
        st.setObjectName("Title")
        self.qr_students = QLabel()
        self.qr_students.setAlignment(Qt.AlignCenter)
        self.url_students = QLabel()
        self.url_students.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.url_students.setAlignment(Qt.AlignCenter)
        sl.addWidget(st)
        sl.addWidget(self.qr_students)
        sl.addWidget(self.url_students)
        sl.addWidget(QLabel(C.L("يمكنك عرض هذا الرمز على البروجكتر ليمسحه الطلاب.",
                                "You can project this code so students scan it.")))
        cards.addWidget(sbox, 1)
        # teacher remote
        rbox = QFrame()
        rbox.setObjectName("Tile")
        rl = QVBoxLayout(rbox)
        rt = QLabel(C.L("🎮 هاتفك جهاز تحكم", "🎮 Your phone as a remote"))
        rt.setObjectName("Title")
        rl.addWidget(rt)
        rl.addWidget(QLabel(C.L("الشرائح التالية والسابقة، والبث، والقفل، والمؤقت،\nوصوّر بهاتفك واعرض الصورة على الصف.",
                                "Next/previous slide, sharing, lock, timer,\nand take a photo to show the class.")))
        self.qr_remote = QLabel()
        self.qr_remote.setAlignment(Qt.AlignCenter)
        self.lbl_pin = QLabel()
        self.lbl_pin.setAlignment(Qt.AlignCenter)
        self.lbl_pin.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.btn_reveal = QPushButton(C.L("👁 إظهار رمز التحكم (سري)", "👁 Show remote code (private)"))
        self.btn_reveal.setCheckable(True)
        self.btn_reveal.toggled.connect(self._render)
        rl.addWidget(self.qr_remote, 1)
        rl.addWidget(self.lbl_pin)
        rl.addWidget(self.btn_reveal)
        cards.addWidget(rbox, 1)
        lay.addLayout(cards)
        close = QPushButton(C.L("إغلاق", "Close"))
        close.clicked.connect(self.close)
        lay.addWidget(close, 0, Qt.AlignRight if C.LANG == "en" else Qt.AlignLeft)
        icons.iconify(self)

    def refresh(self):
        cur = self.cmb_ip.currentData()
        self.cmb_ip.blockSignals(True)
        self.cmb_ip.clear()
        for ip, name in self.win.lan_addresses():
            self.cmb_ip.addItem(f"{ip}   ({name})", ip)
        if cur:
            i = self.cmb_ip.findData(cur)
            if i >= 0:
                self.cmb_ip.setCurrentIndex(i)
        self.cmb_ip.blockSignals(False)
        self._render()

    def urls(self):
        ip = self.cmb_ip.currentData() or "127.0.0.1"
        port = self.win.web_port
        return (f"http://{ip}:{port}/?c={self.win.code}",
                f"http://{ip}:{port}/remote#pin={self.win.server.remote_pin}")

    def _render(self, *_):
        s_url, r_url = self.urls()
        self.qr_students.setPixmap(self._qr.qr_pixmap(s_url, scale=7))
        self.url_students.setText(f"<b>{s_url}</b><br>" + C.L("رمز الصف: ", "Class code: ") + f"<b>{self.win.code}</b>")
        show = self.btn_reveal.isChecked()
        C.exclude_from_capture(self, show)          # never broadcast the private remote code
        if show:
            self.qr_remote.setPixmap(self._qr.qr_pixmap(r_url, scale=6))
            self.lbl_pin.setText(C.L("الرمز السري: ", "PIN: ") + f"<b>{self.win.server.remote_pin}</b><br><small>{r_url}</small>")
        else:
            self.qr_remote.clear()
            self.qr_remote.setText(C.L("🔒 مخفي حتى لا يراه الطلاب", "🔒 Hidden so students cannot see it"))
            self.lbl_pin.setText("")


def screen_for_monitor(mon):
    """Match one of common.list_monitors() to a QScreen (same ordering rule)."""
    screens = list(QApplication.screens())
    primary = QApplication.primaryScreen()
    screens.sort(key=lambda s: (s is not primary, s.geometry().x(), s.geometry().y()))
    mons = C.list_monitors()
    try:
        return screens[mons.index(mon)]
    except (ValueError, IndexError):
        return primary


__all__ = ["AnnotationOverlay", "AnnotationBar", "PhonesDialog", "PickDialog", "WindowPicker", "screen_for_monitor"]
