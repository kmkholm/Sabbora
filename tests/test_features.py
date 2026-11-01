"""Feature-by-feature check of a live teacher <-> student session over localhost.

Anything that would act on this computer (shut down, open a browser, run or
close programs, move the mouse, block the keyboard, Wake-on-LAN packets) is
intercepted and recorded instead of executed.
"""
import csv
import os
import sys
import tempfile
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PyQt5.QtCore import QCoreApplication, QEvent, QPoint, Qt  # noqa: E402
from PyQt5.QtGui import QKeyEvent, QMouseEvent  # noqa: E402
from PyQt5.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox  # noqa: E402

from sabbora import common as C  # noqa: E402
from sabbora import student as S  # noqa: E402
from sabbora import teacher as T  # noqa: E402

PORT = 47980
CALLS = []          # (what, args) recorded instead of really executed
ANSWERS = {}        # what the patched dialogs return


def pump(cond, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def wait(seconds):
    pump(lambda: False, seconds)


class FakeBlocker:
    active = False

    def start(self):
        self.active = True
        CALLS.append(("block", True))

    def stop(self):
        self.active = False


class FakeInjector:
    available = True

    def move_norm(self, mon, x, y):
        CALLS.append(("move", (round(x, 2), round(y, 2))))

    def button(self, b, down):
        CALLS.append(("button", (b, down)))

    def wheel(self, d):
        CALLS.append(("wheel", d))

    def key(self, vk, down, text=""):
        CALLS.append(("key", (vk, down)))


def called(what):
    return [a for w, a in CALLS if w == what]


@pytest.fixture(scope="module")
def room():
    app = QApplication.instance() or QApplication([])
    mp = pytest.MonkeyPatch()
    mp.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    mp.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (ANSWERS.get("text", "x"), True)))
    mp.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: (ANSWERS.get("multi", "x"), True)))
    mp.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: (ANSWERS.get("item", "x"), True)))
    mp.setattr(QInputDialog, "getInt", staticmethod(lambda *a, **k: (ANSWERS.get("int", 1), True)))
    mp.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (ANSWERS.get("open", ""), "")))
    mp.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (ANSWERS.get("save", ""), "")))
    # teacher and student share the same QDesktopServices class: one recorder for both
    mp.setattr(S.QDesktopServices, "openUrl", staticmethod(
        lambda url: CALLS.append(("open_folder" if url.isLocalFile() else "open_url", url.toString())) or True))
    mp.setattr(C, "run_program", lambda cmd: CALLS.append(("run", cmd)) or True)
    mp.setattr(C, "power_action", lambda a: CALLS.append(("power", a)) or True)
    mp.setattr(C, "kill_program", lambda n: CALLS.append(("kill", n)) or True)
    mp.setattr(C, "send_wake_on_lan", lambda mac, bcs=(): CALLS.append(("wol", mac)) or True)

    class A:
        port = PORT
        server = f"127.0.0.1:{PORT}"
        code = ""
        name = "Feature Tester"
        auto = False

    tw = T.TeacherWindow(A)
    tw.chk_min.setChecked(False)
    A.code = tw.code
    sw = S.StudentApp(A)
    sw.blocker = FakeBlocker()
    sw.injector = FakeInjector()
    r = SimpleNamespace(app=app, tw=tw, sw=sw, A=A, seat=None, tmp=tempfile.mkdtemp(prefix="sabbora_test_"))
    yield r
    sw.capturer.stop()
    if tw.caster.isRunning():
        tw.caster.stop()
    for v in list(tw.viewers.values()):
        v.close()
    tw.server.close_all()
    tw.web.stop()
    sw.tray.hide()
    sid = r.seat.sid if r.seat else None
    if sid in tw.tiles:
        tw.tiles[sid].seat = None
        tw.tiles[sid].online = False
        tw.remove_tiles([tw.tiles[sid]])
    sw.settings.clear()
    mp.undo()


# --------------------------------------------------------------------------- joining
def test_01_wrong_code_is_rejected(room):
    sw = room.sw
    sw.ed_host.setText(room.A.server)
    sw.ed_name.setText("Feature Tester")
    sw.ed_code.setText("0000" if room.A.code != "0000" else "1111")
    sw.join()
    assert pump(lambda: not sw.want and "❌" in sw.lbl_err.text())
    assert not room.tw.all_seats()


def test_02_join_with_code(room):
    sw, tw = room.sw, room.tw
    sw.ed_code.setText(room.A.code)
    sw.join()
    assert pump(lambda: len(tw.all_seats()) == 1 and sw.welcomed)
    room.seat = tw.all_seats()[0]
    assert room.seat.name == "Feature Tester"


def test_03_live_thumbnail(room):
    assert pump(lambda: room.tw.tiles[room.seat.sid].last_jpeg is not None)


# --------------------------------------------------------------------------- sharing
def test_04_share_screen_full_locked(room):
    tw, sw = room.tw, room.sw
    tw.cmb_mode.setCurrentIndex(0)
    tw.cmb_mon.setCurrentIndex(0)
    tw._source_activated(0)
    tw.start_cast()
    assert pump(lambda: sw.viewer.active and sw.viewer.mode == "full" and sw.viewer.pm is not None)
    assert sw.blocker.active, "keyboard should be blocked in locked full-screen mode"


def test_05_share_window_mode(room):
    tw, sw = room.tw, room.sw
    tw.cmb_mode.setCurrentIndex(1)
    assert pump(lambda: sw.viewer.mode == "window" and not sw.blocker.active)


def test_06_freeze(room):
    tw = room.tw
    tw.set_paused(True)
    wait(0.4)
    seq = tw.server.b_seq
    wait(1.0)
    assert tw.server.b_seq == seq, "frames must stop while frozen"
    tw.set_paused(False)
    assert pump(lambda: tw.server.b_seq > seq)


def test_07_share_one_window(room):
    tw, sw = room.tw, room.sw
    wins = C.list_windows()
    if not wins:
        pytest.skip("no desktop windows to share")
    hwnd = wins[0]["hwnd"]
    tw.cmb_mon.insertItem(tw.cmb_mon.count() - 1, "win", ("win", hwnd))
    tw.cmb_mon.setCurrentIndex(tw.cmb_mon.count() - 2)
    tw._cast_settings_changed()
    rect = C.visible_rect(hwnd) or C.window_rect(hwnd)
    assert pump(lambda: tw.caster.area is not None and tw.caster.area[2] == rect[2])
    want = rect[2] / rect[3]
    assert pump(lambda: sw.viewer.pm is not None
                and abs(sw.viewer.pm.width() / sw.viewer.pm.height() - want) < 0.02),         "student sees the window, not the whole screen"
    tw.cmb_mon.removeItem(tw.cmb_mon.count() - 2)


def test_08_share_powerpoint_mode(room):
    tw = room.tw
    ppt = next(i for i in range(tw.cmb_mon.count()) if (tw.cmb_mon.itemData(i) or ("",))[0] == "ppt")
    tw.cmb_mon.setCurrentIndex(ppt)
    tw._cast_settings_changed()
    assert tw.caster.source == ("ppt", None)
    seq = tw.server.b_seq
    assert pump(lambda: tw.server.b_seq > seq), "PowerPoint mode streams (slide show, editor, or screen if PowerPoint is closed)"
    tw.cmb_mon.setCurrentIndex(0)
    tw._cast_settings_changed()


def test_09_stop_sharing(room):
    room.tw.stop_cast()
    assert pump(lambda: not room.sw.viewer.active)


# --------------------------------------------------------------------------- watching
def test_10_live_view_and_remote_control(room):
    tw, sid = room.tw, room.seat.sid
    tw.open_viewer(sid, control=True)
    v = tw.viewers[sid]
    assert pump(lambda: v.view.pm is not None), "high-resolution frames"
    view = v.view
    view.resize(800, 450)
    r = view._rect()
    centre = QPoint(r.x() + r.width() // 2, r.y() + r.height() // 2)
    QApplication.sendEvent(view, QMouseEvent(QEvent.MouseButtonPress, centre, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    QApplication.sendEvent(view, QMouseEvent(QEvent.MouseButtonRelease, centre, Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
    QApplication.sendEvent(view, QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.NoModifier, "a"))
    assert pump(lambda: ("l", True) in called("button") and ("l", False) in called("button"))
    assert pump(lambda: any(k[0] == 0x41 for k in called("key")))
    assert (0.5, 0.5) in called("move")
    v.close()
    assert pump(lambda: not room.seat.focus)


def test_11_show_student_screen_to_class(room):
    tw, seat = room.tw, room.seat
    tw.start_demo(seat.sid)
    assert tw.server.b_exclude == seat.sid
    assert pump(lambda: tw.server.b_latest is not None), "student frames are relayed to the class"
    tw.stop_cast()
    assert not tw.server.b_active and not seat.focus


# --------------------------------------------------------------------------- control
def test_12_lock_and_unlock(room):
    tw, sw, seat = room.tw, room.sw, room.seat
    tw.do_lock([seat])
    assert pump(lambda: sw.locked and sw.locks and sw.blocker.active)
    tw.do_unlock([seat])
    assert pump(lambda: not sw.locked and not sw.locks and not sw.blocker.active)


def test_13_message(room):
    ANSWERS["multi"] = "Please open chapter 3"
    n = len(room.sw.popups)
    room.tw.do_message([room.seat])
    assert pump(lambda: len(room.sw.popups) > n)
    assert "chapter 3" in room.sw.popups[-1].findChildren(S.QLabel)[1].text()


def test_14_open_website(room):
    ANSWERS["text"] = "www.example.com"
    room.tw.do_url([room.seat])
    assert pump(lambda: "https://www.example.com" in called("open_url"))


def test_15_run_program(room):
    ANSWERS["text"] = "notepad"
    room.tw.do_run([room.seat])
    assert pump(lambda: "notepad" in called("run"))


def test_16_send_file(room):
    src = os.path.join(room.tmp, "lecture_notes.bin")
    payload = os.urandom(C.FILE_CHUNK * 3 + 99)
    with open(src, "wb") as f:
        f.write(payload)
    for f in os.listdir(room.sw.files_dir()):
        if f.startswith("lecture_notes"):
            os.remove(os.path.join(room.sw.files_dir(), f))
    ANSWERS["open"] = src
    room.tw.do_file([room.seat])
    assert pump(lambda: not room.seat.files and not room.sw.recv)
    got = os.path.join(room.sw.files_dir(), "lecture_notes.bin")
    with open(got, "rb") as f:
        assert f.read() == payload
    os.remove(got)


def test_17_quick_poll(room):
    tw, sw = room.tw, room.sw
    ANSWERS["text"] = "Is it clear?"
    ANSWERS["item"] = "Yes | No"
    tw.do_poll()
    assert pump(lambda: sw.poll is not None and len(sw.poll.buttons) == 2)
    sw.poll._vote(0)
    assert pump(lambda: tw.poll.counts() == [1, 0])
    tw.poll._share()
    assert pump(lambda: sw.poll.bars is not None)
    tw.poll.close()
    assert pump(lambda: not sw.poll.buttons[0].isEnabled())


def test_18_raise_hand_and_lower(room):
    tw, sw, seat = room.tw, room.sw, room.seat
    sw.btn_hand.setChecked(True)
    assert pump(lambda: seat.hand)
    tw.lower_hands([seat])
    assert pump(lambda: not sw.btn_hand.isChecked())


def test_19_student_chat(room):
    ANSWERS["multi"] = "I have a question"
    room.sw.chat()
    assert pump(lambda: "I have a question" in room.tw.log_list.item(0).text())


def test_20_power_and_wake(room):
    room.tw.do_power([room.seat], "shutdown")
    assert pump(lambda: "shutdown" in called("power"))
    room.tw.do_wake([room.tw.tiles[room.seat.sid]])
    assert called("wol"), "magic packet requested for the saved MAC"


# --------------------------------------------------------------------------- teaching tools
def test_21_timer(room):
    ANSWERS["int"] = 2
    ANSWERS["text"] = "Exercise 1"
    room.tw.do_timer()
    assert pump(lambda: room.sw.countdown.isVisible())
    assert "Exercise 1" in room.sw.countdown.lbl_title.text()
    room.tw.do_timer()                      # second press stops it
    assert pump(lambda: not room.sw.countdown.isVisible())


def test_22_clipboard(room):
    ANSWERS["multi"] = "for i in range(3): print(i)"
    room.tw.do_clip([room.seat])
    assert pump(lambda: QApplication.clipboard().text() == "for i in range(3): print(i)")


def test_23_close_program(room):
    ANSWERS["item"] = "chrome.exe"
    room.tw.do_kill([room.seat])
    assert pump(lambda: "chrome.exe" in called("kill"))


def test_24_random_pick(room):
    n = len(room.sw.popups)
    room.tw.do_pick()
    assert pump(lambda: len(room.sw.popups) > n and room.tw.pick_dlg.isVisible())
    assert room.tw.pick_dlg.name.text() == "Feature Tester"
    room.tw.pick_dlg.close()


def test_25_collect_and_submit_assignment(room):
    tw, sw = room.tw, room.sw
    ANSWERS["text"] = "Homework 1"
    n = len(sw.popups)
    tw.do_collect([room.seat])
    assert pump(lambda: len(sw.popups) > n), "assignment request reaches the student"
    src = os.path.join(room.tmp, "homework1.bin")
    payload = os.urandom(C.FILE_CHUNK + 1234)
    with open(src, "wb") as f:
        f.write(payload)
    sw.submit_file(src)
    assert pump(lambda: not sw.uploads)
    folder = tw.server.submissions_dir()
    got = [f for f in os.listdir(folder) if f.endswith("homework1.bin")]
    assert got
    with open(os.path.join(folder, got[-1]), "rb") as f:
        assert f.read() == payload
    for f in got:
        os.remove(os.path.join(folder, f))
    try:
        os.removedirs(folder)
    except OSError:
        pass


def test_26_active_window_on_tile(room):
    room.sw._report_window()
    assert pump(lambda: room.seat.win != "")
    assert "🪟" in room.tw.tiles[room.seat.sid].sub.text()


def test_27_pen_and_whiteboard(room):
    tw = room.tw
    tw.open_pen(None)
    assert tw.overlay.isVisible() and tw.caster.layered
    tw.annot_bar.set_board("white")
    assert tw.overlay.board == "white"
    tw.close_pen()
    assert not tw.overlay.isVisible() and not tw.caster.layered


# --------------------------------------------------------------------------- admin
def test_28_attendance_csv(room):
    path = os.path.join(room.tmp, "attendance.csv")
    ANSWERS["save"] = path
    room.tw.export_roll()
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert any("Feature Tester" in r for r in rows)


def test_29_snapshots(room):
    room.tw.save_shots([room.tw.tiles[room.seat.sid]])
    folders = called("open_folder")
    assert folders
    folder = folders[-1].replace("file:///", "")
    shots = [f for f in os.listdir(folder) if f.startswith("Feature Tester")]
    assert shots
    for f in shots:
        os.remove(os.path.join(folder, f))


def test_30_themes(room):
    for name in ("dark", "classic", "modern"):
        C.apply_theme(name)
        assert C.THEMES[name]["bg"] in QApplication.instance().styleSheet()


def test_31_auto_reconnect_after_teacher_restart(room):
    tw, sw = room.tw, room.sw
    tw.server.close_all()
    assert pump(lambda: not sw.welcomed)
    srv = T.ClassServer(tw.code, "Lecture")           # teacher program started again
    assert srv.listen(PORT) == PORT
    assert pump(lambda: len(srv.students) == 1, timeout=12), "student rejoins on its own"
    srv.close_all()
    assert pump(lambda: not sw.welcomed)
    sw.leave()


def test_32_kick(room):
    tw, sw = room.tw, room.sw
    srv = T.ClassServer(tw.code, "Lecture")
    assert srv.listen(PORT + 1) == PORT + 1
    sw.ed_host.setText(f"127.0.0.1:{PORT + 1}")
    sw.join()
    assert pump(lambda: len(srv.students) == 1)
    st = next(iter(srv.students.values()))
    srv.send(st, {"t": "kick"})
    assert pump(lambda: not sw.want and not srv.students)
    wait(4)
    assert not srv.students, "a kicked student does not reconnect"
    srv.close_all()
