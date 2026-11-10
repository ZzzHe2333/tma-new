"""GUI requests waiting for preferences; bounded records, no disk reads here."""
from collections import deque
from dataclasses import dataclass
import weakref

from PySide6.QtCore import QObject, QTimer


@dataclass(frozen=True)
class Notice:
    event: str
    batch: str
    path: str
    fields: tuple
    separated: object
    startup: bool
    with_plot: bool
    plot: object
    profile: str

    @property
    def size(self):
        values = [self.event, self.batch, self.path, self.profile, *[v for pair in self.fields for v in pair]]
        if self.plot is not None:
            values.extend(self.plot[3].values())
        return sum(len(str(item).encode('utf-8')) for item in values)


class DeferredPreferences(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.notices = deque()
        self.retained_bytes = 0
        self.popup = None
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.drain)

    def enqueue(self, notice):
        size = notice.size
        if len(self.notices) >= 64 or self.retained_bytes + size > 1024 * 1024:
            from .diagnostics import record_event
            record_event('notification.deferred.dropped')
            return False
        if notice.startup: self.notices.appendleft(notice)
        else: self.notices.append(notice)
        self.retained_bytes += size
        self.timer.start()
        return True

    def await_popup(self, dialog):
        from .path_settings import config_path
        self.popup = (weakref.ref(dialog), dialog.popup_revision, str(config_path()))
        self.timer.start()

    def drain(self):
        from .path_settings import cached_settings, config_path, refresh_in_background
        if self.owner._closing:
            self.clear(); return
        snapshot = cached_settings()
        if snapshot is None:
            if self.owner._mcp_settings_job is None:
                refresh_in_background(min_interval=30)
            return
        profile = str(config_path())
        if self.popup is not None:
            reference, revision, requested_profile = self.popup
            self.popup = None
            dialog = reference()
            from shiboken6 import isValid
            ui = snapshot[1].get('ui', {})
            enabled = not isinstance(ui, dict) or ui.get('batch_popup', True) is not False
            if (enabled and requested_profile == profile and dialog is not None and isValid(dialog)
                    and dialog.popup_revision == revision and not dialog._shutdown):
                dialog.show(); dialog.raise_()
        if self.notices:
            notice = self.notices.popleft()
            self.retained_bytes -= notice.size
            if notice.profile == profile:
                self.owner.send_usage_notice(notice)
        if not self.notices and self.popup is None:
            self.timer.stop()

    def clear(self):
        self.timer.stop(); self.notices.clear(); self.retained_bytes = 0; self.popup = None
