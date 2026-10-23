"""GUI-polled mass lookups; slow SMB/Excel reads never wait on the GUI."""
from __future__ import annotations

import queue
import threading

from PySide6.QtCore import QObject, QTimer, Signal, Slot


def lookup_worker(requests, source, cancelled, events, force=False):
    from .diagnostics import record_event
    from .mass_lookup import lookup_record, MassMatch
    cache = {}
    try:
        for key, sample in requests:
            if cancelled.is_set(): break
            record_event('mass.lookup.start', sample=sample, source=source)
            if sample not in cache:
                try:
                    cache[sample] = lookup_record(sample, source, force=True) if force and not cache else lookup_record(sample, source)
                except Exception: cache[sample] = MassMatch(message='m 数据源读取失败，请检查路径与访问权限')
            record_event('mass.lookup.result', sample=sample, matched=cache[sample].value is not None)
            if not cancelled.is_set(): events.put((key, cache[sample]))
    finally:
        events.put(None)


class MassLookupJob(QObject):
    row_ready = Signal(str, object)
    finished = Signal()

    def __init__(self, requests, source, parent=None, *, force=False):
        super().__init__(parent)
        self.requests = list(requests); self.source = source
        self.force = force
        self.cancelled = threading.Event(); self.events = queue.Queue()
        self.timer = QTimer(self); self.timer.setInterval(30); self.timer.timeout.connect(self.drain)

    def start(self):
        self.worker_thread = threading.Thread(target=lookup_worker,
            args=(self.requests, self.source, self.cancelled, self.events, self.force), name='TMA-mass-lookup', daemon=True)
        self.timer.start(); self.worker_thread.start()

    def cancel(self):
        self.cancelled.set(); self.timer.stop()

    @Slot()
    def drain(self):
        for _ in range(32):
            if self.cancelled.is_set(): return
            try: value = self.events.get_nowait()
            except queue.Empty: return
            if value is None:
                self.timer.stop(); self.finished.emit(); return
            self.row_ready.emit(*value)
