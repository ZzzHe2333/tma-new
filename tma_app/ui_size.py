"""Process-local whole-UI scaling, applied before QApplication is created."""
from __future__ import annotations

import math
import os
from pathlib import Path
import json
import hashlib
import sys

from .path_settings import config_path

PRESETS = (('standard', '标准 · 100%', 1.), ('large', '大 · 125%', 1.25), ('extra_large', '超大 · 150%', 1.5))


def fallback_path(primary):
    if not getattr(sys, 'frozen', False): return None
    # Different users and diagnostic profiles must not share appearance values.
    identity = os.path.normcase(os.path.abspath(primary)).encode('utf-8')
    key = hashlib.sha256(identity).hexdigest()[:16]
    package = Path(sys.executable).parent
    # Managed local releases live in <project>/dist-<version>/<app>. Keep
    # preferences beside the version folders so an update retains activation
    # and appearance even when the Windows profile is read-only for the EXE.
    base = package.parent.parent if package.name == 'ZzzHe TMA Analysis' and package.parent.name.startswith('dist-') else package
    return base / 'ZzzHeTMA' / key / Path(primary).name


def fallback_paths(primary):
    current = fallback_path(primary)
    if current is None: return []
    paths = [current]
    package = Path(sys.executable).parent
    if package.name == 'ZzzHe TMA Analysis' and package.parent.name.startswith('dist-'):
        # Read the old per-package location too; write only the stable path.
        try: releases = list(package.parent.parent.glob('dist-*'))
        except OSError: return paths
        for release in releases:
            paths.append(release / package.name / 'ZzzHeTMA' / current.parent.name / Path(primary).name)
    return paths


def saved_size(*, primary=None, data=None):
    try:
        profile = config_path() if primary is None else Path(primary)
        appearance = profile.with_name('appearance.json')
        candidates = [appearance, *fallback_paths(appearance)]
        existing = []
        for path in candidates:
            if path is None: continue
            try: existing.append((path.stat().st_mtime_ns, path))
            except OSError: continue
        for _, path in sorted(existing, key=lambda item: item[0], reverse=True):
            try:
                value = json.loads(path.read_text(encoding='utf-8')).get('size')
                if value in {key for key, _, _ in PRESETS}: return value
            except (OSError, ValueError, AttributeError): continue
        if data is None:
            from .path_settings import _read_settings
            data = _read_settings(primary=profile)[1]
        value = data.get('ui', {}).get('size', 'standard')
        return value if value in {key for key, _, _ in PRESETS} else 'standard'
    except (OSError, ValueError, AttributeError): return 'standard'


def save_size(key, *, path=None):
    from .diagnostics import record_event
    from .atomic_files import write_json
    if key not in {value for value, _, _ in PRESETS}: raise ValueError('请选择标准、大或超大')
    path = Path(path) if path is not None else config_path().with_name('appearance.json')
    data = {'version': 1, 'size': key}
    record_event('ui.size.save.write', preset=key)
    try:
        write_json(path, data)
        return path
    except OSError as exc:
        portable = fallback_path(path)
        record_event('ui.size.save.primary_failed', error=str(exc), fallback=str(portable))
        if portable is None or portable == path: raise
        write_json(portable, data)
        return portable


def active_size():
    value = os.environ.get('ZZZHE_TMA_UI_SIZE_ACTIVE', 'standard')
    return value if value in {key for key, _, _ in PRESETS} else 'standard'


def factor(): return next(scale for key, _, scale in PRESETS if key == active_size())


def active_icon_size():
    key = os.environ.get('ZZZHE_TMA_ICON_SIZE_ACTIVE', 'standard')
    return key if key in {item[0] for item in PRESETS} else 'standard'


def icon_factor():
    selected = next(scale for key, _, scale in PRESETS if key == active_icon_size())
    return max(factor(), selected)


def saved_icon_size(*, primary=None):
    path = (Path(primary) if primary is not None else config_path()).with_name('icon-appearance.json')
    candidates = []
    for candidate in [path, *fallback_paths(path)]:
        try: candidates.append((candidate.stat().st_mtime_ns, candidate))
        except OSError: pass
    for _, candidate in sorted(candidates, key=lambda item: item[0], reverse=True):
        try:
            key = json.loads(candidate.read_text(encoding='utf-8')).get('size')
            if key in {item[0] for item in PRESETS}: return key
        except (OSError, ValueError, AttributeError): pass
    return 'standard'


def canvas_point(canvas, point):
    """Qt context-menu points are logical; Matplotlib hit tests use pixels."""
    ratio = canvas.device_pixel_ratio
    return point.x()*ratio, canvas.figure.bbox.height-point.y()*ratio


def configure_environment():
    key = saved_size()
    os.environ['ZZZHE_TMA_ICON_SIZE_ACTIVE'] = saved_icon_size()
    try: base = float(os.environ.get('ZZZHE_TMA_BASE_QT_SCALE', os.environ.get('QT_SCALE_FACTOR', '1')))
    except ValueError: base = 1.
    if not math.isfinite(base) or not .25 <= base <= 8: base = 1.
    # Children inherit this original base, avoiding a second multiplication
    # when a diagnostic/verification process launches another copy.
    os.environ['ZZZHE_TMA_BASE_QT_SCALE'] = str(base)
    os.environ['ZZZHE_TMA_UI_SIZE_ACTIVE'] = key
    scale = next(scale for value, _, scale in PRESETS if value == key)
    if scale != 1 or 'QT_SCALE_FACTOR' in os.environ:
        os.environ['QT_SCALE_FACTOR'] = str(base * scale)
    return key


def change_from_menu(owner, key, *, icons=False):
    return size_controller(owner, icons=icons).request(key)


def _save_worker(key, path, events):
    from .diagnostics import record_event
    record_event('ui.size.save.start', preset=key)
    try:
        saved = save_size(key, path=path)
        events.put((True, key, str(saved or path)))
        record_event('ui.size.save.done', preset=key, path=str(saved or path))
    except Exception as exc:
        events.put((False, key, str(exc))); record_event('ui.size.save.failed', preset=key, error=str(exc))


def size_controller(owner, *, icons=False):
    attribute = '_icon_size_controller' if icons else '_ui_size_controller'
    existing = getattr(owner, attribute, None)
    if existing is not None: return existing
    import queue
    import threading
    from PySide6.QtCore import QObject, QTimer, Slot
    from PySide6.QtWidgets import QApplication
    class SizeController(QObject):
        def __init__(self):
            super().__init__(owner)
            self.selected = active_icon_size() if icons else active_size(); self.desired = None; self.writing = None; self.busy = False; self.actions = []
            self.request_revision = 0
            self.path = config_path().with_name('icon-appearance.json' if icons else 'appearance.json'); self.events = queue.Queue()
            self.dispatch = QTimer(self); self.dispatch.setSingleShot(True); self.dispatch.timeout.connect(self.begin)
            self.poll = QTimer(self); self.poll.setInterval(30); self.poll.timeout.connect(self.drain)
            self.notice = QTimer(self); self.notice.setSingleShot(True); self.notice.setInterval(5000)
            self.notice.timeout.connect(self.slow_notice)

        def request(self, key):
            if key not in {value for value, _, _ in PRESETS}: return
            self.request_revision += 1
            from .diagnostics import record_event
            record_event('ui.size.request', preset=key)
            self.desired = key
            owner.statusBar().showMessage('正在后台保存界面大小，当前界面不变；保存完成后重启生效。')
            if not self.busy: self.dispatch.start(30)

        @Slot()
        def begin(self):
            # Native QMenu activation must finish before starting any work.
            if QApplication.activePopupWidget() is not None:
                self.dispatch.start(30); return
            if self.busy or self.desired is None: return
            key = self.desired; self.desired = None; self.writing = key; self.busy = True
            self.worker_thread = threading.Thread(target=_save_worker,
                args=(key, self.path, self.events), name='TMA-ui-size-save', daemon=True)
            self.poll.start(); self.notice.start(); self.worker_thread.start()

        @Slot()
        def slow_notice(self):
            if self.busy:
                owner.statusBar().showMessage('字号配置写入超时，尚未确认保存；请勿按新字号重启。可继续使用其他功能。')

        @Slot()
        def drain(self):
            try: ok, key, detail = self.events.get_nowait()
            except queue.Empty: return
            self.busy = False; self.writing = None; self.poll.stop(); self.notice.stop()
            if ok:
                self.selected = key
                label = next(label for value, label, _ in PRESETS if value == key)
                extra = '（用户配置目录不可写，已存到程序目录）' if Path(detail) != self.path else ''
                scope = '图标倍率' if icons else '全部倍率'
                owner.statusBar().showMessage(f'{scope}已保存：{label}{extra}。关闭并重新打开程序后生效。')
            else:
                owner.statusBar().showMessage(f'界面大小保存失败：{detail}。旧设置保留。')
            if self.desired is not None: self.dispatch.start(30)

        def sync(self):
            # Memory only: no disk access inside aboutToShow/native menu loops.
            key = self.desired or self.writing or self.selected
            for action in self.actions: action.setChecked(action.data() == key)

    controller = SizeController()
    setattr(owner, attribute, controller)
    return controller


def add_size_menu(owner, settings_menu):
    from PySide6.QtGui import QActionGroup
    menu = settings_menu.addMenu('界面缩放')
    whole_menu = None
    for icons, title in ((False, '全部放大'), (True, '图标放大')):
        submenu = menu.addMenu(title)
        if not icons: whole_menu = submenu
        group = QActionGroup(submenu); group.setExclusive(True)
        controller = size_controller(owner, icons=icons)
        for key, _, scale in PRESETS:
            action = submenu.addAction(f'{scale:g}×'); action.setCheckable(True)
            action.setData(key); action.setChecked(controller.selected == key); group.addAction(action)
            controller.actions.append(action)
            action.triggered.connect(lambda checked=False, value=key, icon_only=icons: change_from_menu(owner, value, icons=icon_only))
        submenu.aboutToShow.connect(controller.sync)
    menu.addSeparator(); note = menu.addAction('重启后生效；图标使用两项中较大的倍率'); note.setEnabled(False)
    owner.ui_scale_menu = menu
    return whole_menu


def fit_window(widget):
    """Keep enlarged windows reachable on the current screen."""
    if factor() == 1: return
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QMainWindow, QWidget, QVBoxLayout, QScrollArea
    screen = widget.screen()
    if screen is None: return
    available = screen.availableGeometry()
    width = max(240, available.width()-20); height = max(180, available.height()-48)
    if isinstance(widget, QMainWindow):
        widget.setMinimumSize(min(widget.minimumWidth(), width), min(widget.minimumHeight(), height))
        if not widget.isMaximized(): widget.resize(min(widget.width(), width), min(widget.height(), height))
        return
    if not isinstance(widget, QDialog): return
    layout = widget.layout()
    minimum = layout.minimumSize() if layout is not None else widget.minimumSize()
    if layout is not None and not widget.property('tma-size-scroll') and (minimum.width() > width or minimum.height() > height):
        contents = QWidget(); contents.setLayout(layout)
        scroll = QScrollArea(widget); scroll.setObjectName('UiSizeScrollArea')
        scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.Shape.NoFrame); scroll.setWidget(contents)
        outer = QVBoxLayout(widget); outer.setContentsMargins(0, 0, 0, 0); outer.addWidget(scroll)
        widget.setProperty('tma-size-scroll', True)
        widget.setMinimumSize(0, 0)
        widget.setMaximumSize(16777215, 16777215)
    else:
        widget.setMinimumSize(min(widget.minimumWidth(), width), min(widget.minimumHeight(), height))
    widget.resize(min(widget.width(), width), min(widget.height(), height))
    frame = widget.frameGeometry()
    x = max(available.left(), min(frame.left(), available.right()-frame.width()+1))
    y = max(available.top(), min(frame.top(), available.bottom()-frame.height()+1))
    widget.move(x, y)


def install_runtime(application):
    if getattr(application, '_tma_size_filter', None) is not None: return
    from PySide6.QtCore import QObject, QEvent, QTimer
    from PySide6.QtWidgets import QDialog, QMainWindow, QToolBar, QAbstractButton, QToolButton
    from PySide6.QtCore import QSize
    from shiboken6 import isValid
    import weakref
    class SizeFilter(QObject):
        def eventFilter(self, target, event):
            relative = icon_factor() / factor()
            if relative > 1 and event.type() == QEvent.Type.Show and not target.property('tma-icons-scaled'):
                if isinstance(target, (QToolBar, QAbstractButton)):
                    target.setProperty('tma-icons-scaled', True)
                    target.setIconSize(QSize(round(16*relative), round(16*relative)))
                    if isinstance(target, QToolBar):
                        target.setFixedHeight(round(26*relative))
                    elif isinstance(target, QToolButton) and isinstance(target.parentWidget(), QToolBar):
                        target.setFixedSize(round(24*relative), round(24*relative))
            if factor() != 1 and event.type() == QEvent.Type.Show and isinstance(target, (QDialog, QMainWindow)):
                reference = weakref.ref(target)
                def settle():
                    window = reference()
                    if window is not None and isValid(window): fit_window(window)
                QTimer.singleShot(0, settle)
            return False
    application._tma_size_filter = SizeFilter(application)
    application.installEventFilter(application._tma_size_filter)
