"""Light checks: protocol helpers, then one teacher <-> student session over
localhost with offscreen Qt (no windows shown, a few seconds of CPU)."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PIL import Image  # noqa: E402

from sabbora import common as C  # noqa: E402


def test_helpers(tmp_path):
    assert C.parse_hostport("192.168.1.5") == ("192.168.1.5", C.WS_PORT)
    assert C.parse_hostport("ws://10.0.0.2:47003/") == ("10.0.0.2", 47003)
    assert C.parse_hostport("[fe80::1]:5") == ("fe80::1", 5)
    assert C.parse_hostport("host:abc") is None
    assert C.clean_ip("::ffff:192.168.1.9") == "192.168.1.9"
    assert C.safe_filename('..\\..\\evil/na<me>.txt') == "na_me_.txt"
    (tmp_path / "a.txt").write_text("x")
    assert C.unique_path(str(tmp_path), "a.txt").endswith("a (1).txt")
    body = C.pack_file_chunk(7, 3, b"abc")[1:]
    assert C.unpack_file_chunk(body) == (7, 3, b"abc")
    assert C.jload("[1]") is None and C.jload('{"t":"x"}') == {"t": "x"}
    assert len(C.wol_packet("AA:BB:CC:DD:EE:FF")) == 102 and C.wol_packet("zz") is None
    img = Image.new("RGB", (3200, 1800), (30, 90, 60))
    jpg = C.encode_jpeg(img, 1600, 70)
    assert jpg[:2] == b"\xff\xd8" and Image.open(__import__("io").BytesIO(jpg)).size == (1600, 900)
    assert C.list_monitors()[0][4] is True


def test_session():
    from PyQt5.QtCore import QCoreApplication
    from PyQt5.QtWidgets import QApplication

    from sabbora import student as S
    from sabbora import teacher as T

    app = QApplication.instance() or QApplication([])
    QApplication.setQuitOnLastWindowClosed(False)

    class A:
        port = 47950
        server = "127.0.0.1:47950"
        code = ""
        name = "Test Student"
        auto = False

    tw = T.TeacherWindow(A)
    assert tw.port == 47950
    A.code = tw.code
    sw = S.StudentApp(A)

    class NoHook:                     # never block this PC's real keyboard in tests
        active = False

        def start(self):
            self.active = True

        def stop(self):
            self.active = False

    sw.blocker = NoHook()
    sw.ed_host.setText(A.server)
    sw.ed_code.setText(A.code)
    sw.join()

    def pump(cond, timeout=8.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            QCoreApplication.processEvents()
            if cond():
                return True
            time.sleep(0.01)
        return False

    assert pump(lambda: len(tw.all_seats()) == 1), "student did not join"
    seat = tw.all_seats()[0]
    assert pump(lambda: tw.tiles[seat.sid].last_jpeg is not None), "no thumbnail"

    tw.do_lock([seat])
    assert pump(lambda: sw.locked and len(sw.locks) >= 1)
    tw.do_unlock([seat])
    assert pump(lambda: not sw.locked)

    tw.chk_min.setChecked(False)
    tw.start_cast()
    assert pump(lambda: sw.viewer.active and sw.viewer.pm is not None), "broadcast frame not shown"
    tw.stop_cast()
    assert pump(lambda: not sw.viewer.active)

    for f in os.listdir(sw.files_dir()):
        if f.startswith("sabbora_test"):
            os.remove(os.path.join(sw.files_dir(), f))
    tw.server.send_file([seat], "sabbora_test.bin", os.urandom(C.FILE_CHUNK * 3 + 17))
    assert pump(lambda: not seat.files and not sw.recv), "file not delivered"
    received = os.path.join(sw.files_dir(), "sabbora_test.bin")
    got = [f for f in os.listdir(sw.files_dir()) if f.startswith("sabbora_test")]
    assert len(got) == 1 and os.path.getsize(os.path.join(sw.files_dir(), got[-1])) == C.FILE_CHUNK * 3 + 17
    for f in got:
        os.remove(os.path.join(sw.files_dir(), f))
    assert not os.path.exists(received)

    sw._m_hand_down({})
    sw.btn_hand.setChecked(True)
    assert pump(lambda: seat.hand)

    tw.open_viewer(seat.sid)
    assert pump(lambda: seat.sid in tw.viewers and tw.viewers[seat.sid].view.pm is not None), "live view failed"
    tw.viewers[seat.sid].close()

    tw.poll = T.PollWindow(tw, 99, "Q?", ["a", "b"])
    tw.poll.show()
    tw.server.send_many([seat], {"t": "poll", "pid": 99, "q": "Q?", "opts": ["a", "b"]})
    assert pump(lambda: sw.poll is not None)
    sw.poll._vote(1)
    assert pump(lambda: tw.poll.counts() == [0, 1]), "vote lost"
    tw.poll.close()
    assert pump(lambda: not sw.poll.buttons[0].isEnabled())

    # ---- v1.1 tools
    tw.server.send_many([seat], {"t": "timer", "seconds": 90, "title": "T"})
    assert pump(lambda: sw.countdown.isVisible())
    tw.server.send_many([seat], {"t": "timer_stop"})
    assert pump(lambda: not sw.countdown.isVisible())
    tw.server.send_many([seat], {"t": "clip", "text": "print('hi')"})
    assert pump(lambda: QApplication.clipboard().text() == "print('hi')"), "clipboard"
    tw.server.send_many([seat], {"t": "kill", "name": "sabbora_no_such_program_xyz"})
    n_pop = len(sw.popups)
    tw.do_pick()
    assert pump(lambda: len(sw.popups) > n_pop and tw.pick_dlg.isVisible()), "pick"
    tw.pick_dlg.close()
    sw._report_window()
    assert pump(lambda: seat.win != ""), "active window not reported"
    tw.open_pen("white")
    assert tw.overlay.isVisible() and tw.caster.layered
    tw.close_pen()
    assert not tw.overlay.isVisible() and not tw.caster.layered

    import tempfile
    src = os.path.join(tempfile.gettempdir(), "sabbora_hw.bin")
    payload = os.urandom(C.FILE_CHUNK * 2 + 5)
    with open(src, "wb") as f:
        f.write(payload)
    sw.submit_file(src)
    assert pump(lambda: not sw.uploads), "submission not finished"
    folder = tw.server.submissions_dir()
    got = [f for f in os.listdir(folder) if f.endswith("sabbora_hw.bin")]
    assert len(got) == 1
    with open(os.path.join(folder, got[0]), "rb") as f:
        assert f.read() == payload
    os.remove(os.path.join(folder, got[0]))
    os.remove(src)
    try:
        os.removedirs(folder)
    except OSError:
        pass

    sw.leave()
    assert pump(lambda: not tw.all_seats())
    sw.capturer.stop()
    tw.server.close_all()
    tw.web.stop()
    sw.tray.hide()
    tw.remove_tiles([tw.tiles[seat.sid]])      # keep the real roster clean
    sw.settings.clear()


def test_english_ui():
    from PyQt5.QtWidgets import QApplication

    from sabbora import student as S
    from sabbora import teacher as T

    app = QApplication.instance() or QApplication([])  # noqa: F841 (keep a reference)
    C.set_lang("en")
    try:
        class A:
            port = 47970
            server = ""
            code = ""
            name = ""
            auto = False

        tw = T.TeacherWindow(A)
        sw = S.StudentApp(A)
        assert tw.btn_cast.text() == "Share my screen" and not tw.btn_cast.icon().isNull()
        assert sw.btn_join.text() == "Join lecture"
        assert T.power_labels()["restart"] == "Restart"
        assert "Developed by" in C.credit()
        sw.capturer.stop()
        sw.tray.hide()
        tw.server.close_all()
        tw.web.stop()
    finally:
        C.set_lang("ar")
