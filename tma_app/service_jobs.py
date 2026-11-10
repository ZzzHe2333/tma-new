"""Small service I/O jobs; workers retain plain data, never Qt objects."""
import queue
import threading

from PySide6.QtCore import QObject, QTimer, Signal


def read_configuration(cancelled, primary):
    from .path_settings import _read_settings
    if cancelled.is_set():
        return None
    data = _read_settings(primary=primary)[1]
    from .ui_size import saved_size
    return {'settings': data, 'size': saved_size(primary=primary, data=data)}


def maintain_cloud(cancelled, schedule):
    from .path_settings import _settings_data
    if cancelled.is_set() or 'cloud' not in _settings_data():
        return {}
    from . import cloud_storage
    if cancelled.is_set():
        return {}
    result = {'cleanup': cloud_storage.cleanup()}
    if schedule and not cancelled.is_set():
        from .cloud_schedule import install_daily_task
        result['schedule'] = install_daily_task()
    return result


def _run(function, args, cancelled, events):
    try:
        value = {'value': function(cancelled, *args)}
    except Exception as exc:
        value = {'error': str(exc)}
    if not cancelled.is_set():
        events.put(value)


class ServiceJob(QObject):
    done = Signal(object)

    def __init__(self, function, args=(), parent=None):
        super().__init__(parent)
        self.function, self.args = function, args
        self.cancelled = threading.Event()
        self.events = queue.Queue()
        self.timer = QTimer(self)
        self.timer.setInterval(25)
        self.timer.timeout.connect(self.drain)
        self.started = False
        self.thread = None

    def start(self):
        if self.started or self.cancelled.is_set():
            return
        self.started = True
        self.timer.start()
        try:
            self.thread = threading.Thread(target=_run,
                args=(self.function, self.args, self.cancelled, self.events),
                name='TMA-service-config', daemon=True)
            self.thread.start()
        except RuntimeError:
            self.events.put({'error': '后台任务未能启动，请稍后重试。'})

    def drain(self):
        try:
            value = self.events.get_nowait()
        except queue.Empty:
            return
        self.timer.stop()
        if not self.cancelled.is_set():
            self.done.emit(value)

    def cancel(self):
        self.cancelled.set()
        self.timer.stop()
