"""Cancellable imports: pure daemon I/O, with results polled on the Qt thread."""
from copy import deepcopy
import os
from pathlib import Path
import queue
import threading
import uuid

from PySide6.QtCore import QObject, QTimer, Signal, Slot

_IMPORT_MASS_SLOTS = threading.BoundedSemaphore(2)


def run_import(paths, reader, cancelled, events):
    # No QObject or window is captured by this worker. A slow SMB read can
    # return after cancellation without accessing Qt or keeping the app open.
    from .mass_lookup import MassMatch
    datasets, failures, cache = [], [], {}
    try:
        for path in paths:
            if cancelled.is_set(): return
            events.put(('progress', f'正在读取 {Path(path).name}…'))
            try:
                key=os.path.normcase(os.path.abspath(path))
                if key not in cache: cache[key]=reader(path)
                if cancelled.is_set(): return
                dataset=deepcopy(cache[key])
                dataset._import_ticket=uuid.uuid4().hex
                dataset._mass_match=MassMatch(message='m 正在后台匹配')
                datasets.append(dataset)
            except Exception as exc:
                failures.append(f'{Path(path).name}: {exc}')
        if cancelled.is_set(): return
        events.put(('completed',datasets,failures))
    finally:
        events.put(('finished',))


class ImportWorker(QObject):
    completed=Signal(object,object)
    progress=Signal(str)
    finished=Signal()

    def __init__(self,paths,reader,parent=None):
        super().__init__(parent)
        self.paths=list(paths);self.reader=reader
        self.cancelled=threading.Event();self.events=queue.Queue()
        self.timer=QTimer(self);self.timer.setInterval(20)
        self.timer.timeout.connect(self.drain)

    def start(self):
        self.worker_thread=threading.Thread(target=run_import,
            args=(self.paths,self.reader,self.cancelled,self.events),name='TMA-import',daemon=True)
        self.timer.start();self.worker_thread.start()

    def cancel(self):
        self.cancelled.set();self.timer.stop()

    @Slot()
    def drain(self):
        for _ in range(32):
            if self.cancelled.is_set(): return
            try: message=self.events.get_nowait()
            except queue.Empty: return
            kind,*args=message
            if kind=='finished':
                self.timer.stop();self.finished.emit();return
            getattr(self,kind).emit(*args)


def run_import_mass(requests, cancelled, events):
    """A single daemon handles weights; it never owns datasets or Qt objects."""
    from . import mass_lookup
    from .path_settings import settings_revision
    from .diagnostics import record_event
    while not cancelled.is_set():
        try: request=requests.get(timeout=.25)
        except queue.Empty: return
        if request is None or cancelled.is_set():return
        ticket,sample=request;source='';revision=settings_revision();valid=False
        record_event('import.mass.start',sample=sample,ticket=ticket)
        try:
            source=mass_lookup.configured_source()
            result=mass_lookup.lookup_record(sample,source)
            valid=(mass_lookup.configured_source()==source and settings_revision()==revision)
        except Exception as exc:
            result=mass_lookup.MassMatch(message=f'm 数据源未读取：{exc}', unavailable=True)
        if not cancelled.is_set():
            record_event('import.mass.result',sample=sample,ticket=ticket,matched=result.value is not None)
            events.put((ticket,sample,source,result,revision,valid))


def _run_import_mass_bounded(requests, cancelled, events, slots):
    try: run_import_mass(requests, cancelled, events)
    finally: slots.release()


class ImportMassJob(QObject):
    """Reusable queue independent of the file parser and its busy state."""
    mass_ready=Signal(str,str,str,object)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.cancelled=threading.Event();self.requests=queue.Queue();self.events=queue.Queue()
        self.pending=0;self.worker_thread=None
        self.delivery_revision=None;self.delivery_valid=False
        self.timer=QTimer(self);self.timer.setInterval(30);self.timer.timeout.connect(self.drain)

    def enqueue(self,requests):
        if self.cancelled.is_set():return
        for request in requests:
            self.requests.put(tuple(request));self.pending+=1
        if not self.pending:return
        self._start_if_needed()
        self.timer.start()

    def _start_if_needed(self):
        if self.cancelled.is_set() or self.requests.empty(): return
        if self.worker_thread is not None and self.worker_thread.is_alive(): return
        slots = _IMPORT_MASS_SLOTS
        if not slots.acquire(blocking=False): return
        self.worker_thread=threading.Thread(target=_run_import_mass_bounded,
            args=(self.requests,self.cancelled,self.events,slots),name='TMA-import-mass',daemon=True)
        try: self.worker_thread.start()
        except BaseException:
            slots.release(); self.worker_thread=None
            raise

    def discard_queued(self, tickets):
        """Remove obsolete requests without disturbing a lookup already running."""
        tickets = set(tickets)
        if not tickets or self.cancelled.is_set(): return
        # Queue.get uses the same mutex, so a request is either removed here
        # or remains counted until its worker result is drained on the GUI.
        with self.requests.mutex:
            queued = self.requests.queue
            keep = [request for request in queued if request is None or request[0] not in tickets]
            removed = len(queued) - len(keep)
            queued.clear(); queued.extend(keep)
        self.pending -= removed
        if not self.pending: self.timer.stop()

    def cancel(self):
        self.cancelled.set();self.timer.stop();self.pending=0
        while True:
            try:self.requests.get_nowait()
            except queue.Empty:break
        self.requests.put(None)

    @Slot()
    def drain(self):
        for _ in range(32):
            if self.cancelled.is_set():return
            try:message=self.events.get_nowait()
            except queue.Empty:
                self._start_if_needed();return
            self.pending-=1
            ticket,sample,source,result,self.delivery_revision,self.delivery_valid=message
            self.mass_ready.emit(ticket,sample,source,result)
            self.delivery_revision=None;self.delivery_valid=False
            if not self.pending:self.timer.stop();return
