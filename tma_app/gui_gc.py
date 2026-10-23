"""Keep cyclic garbage collection on the Qt GUI thread.

Shiboken wrappers can be in native destruction with the GIL released while
another Python thread allocates objects. Automatic GC on that worker can then
traverse a wrapper being destroyed (the 0.35.2 batch crash). Ordinary reference
counting remains active; a GUI-owned timer collects cycles instead.
"""
from __future__ import annotations

import gc

from PySide6.QtCore import QObject, QThread, QTimer, Slot


class GuiGarbageCollector(QObject):
    def __init__(self, application):
        if QThread.currentThread() != application.thread():
            raise RuntimeError("Install the garbage collector on the GUI thread")
        gc.disable()
        super().__init__(application)
        self.collections = 0
        self.last_thread = None
        self._collecting = False
        self._ticks = 0
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.collect_if_needed)
        self.timer.start()
        # Do not re-enable automatic GC at aboutToQuit: native Qt wrappers may
        # still be destroyed afterwards while daemon file-I/O workers return.
        application.aboutToQuit.connect(self.timer.stop)

    @Slot()
    def collect_if_needed(self):
        if QThread.currentThread() != self.thread():
            raise RuntimeError("Garbage collection must run on the GUI thread")
        if self._collecting:
            return
        self._ticks += 1
        counts, limits = gc.get_count(), gc.get_threshold()
        generation = 2 if self._ticks % 30 == 0 else 1 if counts[1] >= limits[1] else 0
        if generation == 0 and counts[0] < limits[0]:
            return
        self._collecting = True
        try:
            self.last_thread = QThread.currentThread()
            gc.collect(generation)
            self.collections += 1
        finally:
            self._collecting = False


def ensure_gui_gc(application):
    collector = getattr(application, "_tma_gui_gc", None)
    if collector is None:
        collector = application._tma_gui_gc = GuiGarbageCollector(application)
    return collector
