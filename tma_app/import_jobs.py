"""Cancellable imports: pure daemon I/O, with results polled on the Qt thread."""
from copy import deepcopy
import os
from pathlib import Path
import queue
import threading
import uuid

from PySide6.QtCore import QObject, QTimer, Signal, Slot


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
    from .mass_lookup import configured_source, lookup_record, MassMatch
    from .diagnostics import record_event
    while not cancelled.is_set():
        request=requests.get()
        if request is None or cancelled.is_set():return
        ticket,sample=request;source=''
        record_event('import.mass.start',sample=sample,ticket=ticket)
        try:
            source=configured_source()
            result=lookup_record(sample,source)
        except Exception as exc:
            result=MassMatch(message=f'm 数据源未读取：{exc}')
        if not cancelled.is_set():
            record_event('import.mass.result',sample=sample,ticket=ticket,matched=result.value is not None)
            events.put((ticket,sample,source,result))


class ImportMassJob(QObject):
    """Reusable queue independent of the file parser and its busy state."""
    mass_ready=Signal(str,str,str,object)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.cancelled=threading.Event();self.requests=queue.Queue();self.events=queue.Queue()
        self.pending=0;self.worker_thread=None
        self.timer=QTimer(self);self.timer.setInterval(30);self.timer.timeout.connect(self.drain)

    def enqueue(self,requests):
        if self.cancelled.is_set():return
        for request in requests:
            self.requests.put(tuple(request));self.pending+=1
        if not self.pending:return
        if self.worker_thread is None:
            self.worker_thread=threading.Thread(target=run_import_mass,
                args=(self.requests,self.cancelled,self.events),name='TMA-import-mass',daemon=True)
            self.worker_thread.start()
        self.timer.start()

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
            except queue.Empty:return
            self.pending-=1
            self.mass_ready.emit(*message)
            if not self.pending:self.timer.stop();return
