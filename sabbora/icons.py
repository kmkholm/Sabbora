"""Vector icons (Material Design via qtawesome) that follow the active theme.

Button and menu texts in the code start with an emoji; iconify() swaps that
emoji for a crisp icon, so the label stays plain text in both languages.
"""
import os
import weakref

os.environ.setdefault("QT_API", "pyqt5")      # qtpy must not pick another binding

from PyQt5.QtCore import QSize                  # noqa: E402
from PyQt5.QtWidgets import QAbstractButton, QAction, QMenu, QWidget  # noqa: E402

from . import common as C                        # noqa: E402

try:
    import qtawesome as qta                      # noqa: E402
except Exception:                                # icons are optional; emoji stay
    qta = None

EMOJI = {
    "▶": "play", "⏸": "pause", "⏹": "stop", "🔒": "lock", "🔓": "lock-open-variant",
    "💬": "message-text-outline", "🌐": "web", "🚀": "rocket-launch-outline", "📁": "file-send-outline",
    "📊": "poll", "⏻": "power", "⋯": "dots-horizontal-circle-outline", "🖊": "draw", "⬜": "presentation",
    "⏱": "timer-outline", "🎲": "dice-5-outline", "📥": "inbox-arrow-down-outline",
    "📋": "clipboard-text-outline", "⛔": "cancel", "📂": "folder-open-outline", "✋": "hand-back-right-outline",
    "👇": "hand-back-left-outline", "🗑": "delete-outline", "🖱": "cursor-default-click-outline", "📺": "cast",
    "📸": "camera-outline", "🏠": "home-outline", "📢": "bullhorn-outline", "👁": "eye-outline",
    "✖": "close", "⚡": "flash-outline", "☑": "checkbox-multiple-marked-outline", "🧹": "broom",
    "ℹ": "information-outline", "📤": "upload-outline", "🖍": "marker", "↶": "undo", "🎨": "palette-outline",
    "🪟": "application-outline", "🎞": "microsoft-powerpoint", "🖥": "monitor", "👥": "account-group-outline",
}
_KEYS = sorted(EMOJI, key=len, reverse=True)
_registry = []          # (weakref to widget/action, icon name, role)


def _split(text):
    t = text or ""
    for k in _KEYS:
        if t.startswith(k):
            rest = t[len(k):].lstrip("️").lstrip()
            return EMOJI[k], rest
    return None, t


def _role(widget):
    w = widget
    while isinstance(w, QWidget):
        name = w.objectName()
        if name in ("Primary", "Danger"):
            return "light"
        if name == "Warn":
            return "warn"
        if name in ("HeaderBtn", "Bar"):
            return "light"
        w = w.parentWidget()
    return "normal"


def make(name, role="normal"):
    if qta is None:
        return None
    color = {"light": "#FFFFFF", "warn": C.T("warn_text")}.get(role, C.T("icon"))
    return qta.icon("mdi6." + name, color=color, color_on="#FFFFFF",
                    color_active=color, color_disabled=C.T("disabled_text"))


def _apply(obj, name, role):
    icon = make(name, role)
    if icon is not None:
        obj.setIcon(icon)


def iconify_button(btn):
    name, rest = _split(btn.text())
    if name is None or qta is None:
        return
    role = _role(btn)
    btn.setText(rest)
    btn.setIconSize(QSize(18, 18))
    _apply(btn, name, role)
    _registry.append((weakref.ref(btn), name, role))


def iconify_menu(menu):
    for act in menu.actions():
        if act.menu():
            iconify_menu(act.menu())
        name, rest = _split(act.text())
        if name is None or qta is None:
            continue
        act.setText(rest)
        _apply(act, name, "normal")
        _registry.append((weakref.ref(act), name, "normal"))


def iconify(root):
    """Replace leading emoji with icons on every button and menu under root."""
    for btn in root.findChildren(QAbstractButton):
        menu = btn.menu() if hasattr(btn, "menu") else None
        if menu:
            iconify_menu(menu)
        iconify_button(btn)
    for menu in root.findChildren(QMenu):
        iconify_menu(menu)
    for act in root.findChildren(QAction):
        name, rest = _split(act.text())
        if name and qta is not None:
            act.setText(rest)
            _apply(act, name, "normal")
            _registry.append((weakref.ref(act), name, "normal"))


def refresh_all():
    """Re-colour every icon after a theme change."""
    alive = []
    for ref, name, role in _registry:
        obj = ref()
        if obj is None:
            continue
        try:
            _apply(obj, name, role)
            alive.append((ref, name, role))
        except RuntimeError:            # Qt object already deleted
            pass
    _registry[:] = alive


def pixmap(name, size=20, color=None):
    if qta is None:
        return None
    return qta.icon("mdi6." + name, color=color or C.T("icon")).pixmap(size, size)
