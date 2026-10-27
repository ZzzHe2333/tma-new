"""GUI-owned polling bridge for pure numerical work."""
import queue
import threading
from copy import deepcopy
from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QWidget, QPushButton, QLineEdit, QComboBox, QCheckBox, QRadioButton
from .calculation import DISPATCHER, CurveSnapshot, _same


class CalculationJob(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, key, request, parent):
        super().__init__(parent)
        self.key, self.request = key, request
        self.cancelled = threading.Event()
        self.events = queue.Queue()
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.drain)

    def start(self):
        request, self.request = self.request, None
        DISPATCHER.submit(self.key, request, self.cancelled, self.events)
        self.timer.start()

    def cancel(self):
        DISPATCHER.cancel(self.key, self.cancelled)
        self.request = None
        self.timer.stop()
        # A worker may already be posting a result. Detach its old queue so
        # canceled dialogs never retain a late numerical buffer.
        self.events = queue.Queue()

    @Slot()
    def drain(self):
        if self.cancelled.is_set():
            self.cancel()
            self.failed.emit('本次计算已由同文件的新任务替代，请重新计算。')
            return
        try: kind, value = self.events.get_nowait()
        except queue.Empty: return
        self.timer.stop()
        if kind == 'result': self.completed.emit(value)
        else: self.failed.emit(value)


class CalculationDialogMixin:
    """Cancel/close semantics shared by the two numerical dialogs."""
    job = None

    def start_calculation(self, curves, request, apply):
        if self.job is not None: return
        self._calculation_guard = CurveSnapshot(curves)
        self._calculation_options = deepcopy(self.owner.plot_options.get(self._calculation_guard.key))
        self._calculation_domain = self.owner.domain
        candidates = self._calculation_guard.worker_curves()
        request['curves'] = [c for c in candidates if c.uid == request['uid']] if request['kind'] == 'smooth' else candidates
        self._calculation_apply = apply
        self._calculation_controls = []
        for widget in self.findChildren(QWidget):
            if not isinstance(widget, (QPushButton, QLineEdit, QComboBox, QCheckBox, QRadioButton)): continue
            if isinstance(widget, QPushButton) and widget.text() in ('取消', '帮助'): continue
            self._calculation_controls.append((widget, widget.isEnabled()))
            widget.setEnabled(False)
        self.error.setText('正在计算… 可点击取消')
        self.job = job = CalculationJob((id(self.owner), self._calculation_guard.key), request, self)
        job.completed.connect(self.calculation_completed)
        job.failed.connect(self.calculation_failed)
        try: job.start()
        except Exception as exc: self.calculation_failed(str(exc))

    def finish_calculation(self):
        if self.job is not None:
            self.job.cancel(); self.job.deleteLater(); self.job = None
        for widget, enabled in getattr(self, '_calculation_controls', []): widget.setEnabled(enabled)
        self._calculation_controls = []
        self._calculation_guard = None
        self._calculation_apply = None

    def calculation_completed(self, result):
        if self.job is None or self.job.cancelled.is_set(): return
        guard = self._calculation_guard
        valid = (not getattr(self.owner, '_closing', False) and guard.matches(self.owner.curves)
                 and self.owner.domain == self._calculation_domain
                 and _same(self.owner.plot_options.get(guard.key), self._calculation_options))
        apply = self._calculation_apply
        self.finish_calculation()
        if not valid:
            self.error.setText('文件或曲线已变化，本次结果未应用；请重新计算。'); return
        self.error.clear()
        try: apply(result)
        except (ValueError, OverflowError) as exc: self.error.setText(str(exc))

    def calculation_failed(self, message):
        self.finish_calculation()
        self.error.setText(message)
        self.error.setToolTip(message)

    def shutdown_calculation(self): self.finish_calculation()

    def reject(self):
        self.finish_calculation()
        super().reject()

    def closeEvent(self, event):
        self.finish_calculation()
        super().closeEvent(event)
