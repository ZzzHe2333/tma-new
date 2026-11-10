"""Pastel shell colours with asynchronous, independent preference storage."""
import json
import re
from pathlib import Path

CHOICES = (('blue', '淡蓝', .57), ('pink', '淡粉', .91),
           ('yellow', '淡黄', .13), ('gray', '浅灰', 0.), ('red', '淡红', .01))
_active = 'pink'


def recolor(color, key):
    from PySide6.QtGui import QColor
    original = QColor(color)
    _, saturation, lightness, alpha = original.getHslF()
    if key == 'pink': return color
    hue = next(h for k, _, h in CHOICES if k == key)
    if lightness < .12 or saturation < .02: return color
    saturation = 0. if key == 'gray' else min(saturation, .55)
    return QColor.fromHslF(hue, saturation, lightness, alpha).name()


def stylesheet(source, key):
    return re.sub(r'#[0-9a-fA-F]{6}\b', lambda match: recolor(match.group(), key), source)


def _path():
    from .path_settings import config_path
    return config_path().with_name('theme.json')


def _load(cancelled, path):
    from .ui_size import fallback_paths
    files = []
    for item in [path, *fallback_paths(path)]:
        try: files.append((item.stat().st_mtime_ns, item))
        except OSError: pass
    for _, item in sorted(files, key=lambda row: row[0], reverse=True):
        try:
            key = json.loads(item.read_text(encoding='utf-8')).get('color')
            if key in {row[0] for row in CHOICES}: return key
        except (OSError, ValueError, AttributeError): pass
    return 'pink'


def _save(cancelled, path, key):
    from .atomic_files import write_json
    from .ui_size import fallback_path
    if cancelled.is_set(): return
    data = {'version': 1, 'color': key}
    try: write_json(path, data)
    except OSError:
        fallback = fallback_path(path)
        if fallback is None or fallback == path: raise
        write_json(fallback, data)
    return key


def apply(owner, key):
    global _active
    from PySide6.QtGui import QColor, QBrush, QPalette
    from PySide6.QtWidgets import QApplication
    from .theme import CUTE_STYLE, PastelMdiArea, cute_palette
    _active = key
    app = QApplication.instance()
    app.setStyleSheet(stylesheet(CUTE_STYLE, key))
    palette = cute_palette()
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
        for role in QPalette.ColorRole:
            if role in (QPalette.ColorRole.NoRole, QPalette.ColorRole.NColorRoles): continue
            palette.setColor(group, role, QColor(recolor(palette.color(group, role).name(), key)))
    app.setPalette(palette)
    for widget in app.topLevelWidgets():
        original = widget.property('tma-theme-original')
        if original is None:
            original = widget.styleSheet()
            widget.setProperty('tma-theme-original', original)
        widget.setStyleSheet(stylesheet(original, key))
        widget.setPalette(palette)
    for area in owner.findChildren(PastelMdiArea):
        area.setBackground(QBrush(QColor(recolor('#faf3fc', key))))
        area.viewport().update()


def add_menu(owner, settings):
    from PySide6.QtGui import QActionGroup
    from PySide6.QtCore import QTimer
    from .service_jobs import ServiceJob
    menu = settings.addMenu('界面颜色')
    group = QActionGroup(menu)
    actions = {}
    state = {'revision': 0, 'pending': None, 'job': None}
    path = _path()

    def sync(key):
        for value, action in actions.items(): action.setChecked(value == key)

    def begin_save():
        if state['job'] is not None or state['pending'] is None: return
        key = state['pending']; state['pending'] = None
        job = ServiceJob(_save, (path, key), owner)
        state['job'] = job
        def done(event):
            state['job'] = None
            if event.get('error'):
                owner.statusBar().showMessage('颜色保存失败：' + event['error'])
            else:
                owner.statusBar().showMessage('界面颜色已保存，下次启动自动使用。')
            job.deleteLater()
            begin_save()
        job.done.connect(done); job.start()

    def choose(key):
        state['revision'] += 1
        apply(owner, key); sync(key)
        state['pending'] = key
        QTimer.singleShot(0, begin_save)

    for key, label, _ in CHOICES:
        action = menu.addAction(label); action.setCheckable(True); action.setData(key)
        group.addAction(action); actions[key] = action
        action.triggered.connect(lambda checked=False, value=key: choose(value))
    sync(_active)
    load = ServiceJob(_load, (path,), owner)
    def loaded(event):
        if state['revision'] == 0 and not event.get('error'):
            key = event['value']; apply(owner, key); sync(key)
        load.deleteLater()
    load.done.connect(loaded)
    QTimer.singleShot(0, load.start)
    owner.color_theme_menu = menu
    return menu
