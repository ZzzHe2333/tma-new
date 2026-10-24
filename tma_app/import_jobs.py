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
    from .mass_lookup import lookup_record, MassMatch, configured_source
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
        for dataset in datasets:
            if cancelled.is_set(): return
            events.put(('progress',f'正在后台匹配 {dataset.name} 的 m…'))
            try: source=configured_source()
            except (ValueError,OSError): source=''
            result=lookup_record(dataset.name,source)
            if cancelled.is_set(): return
            events.put(('mass_ready',dataset._import_ticket,dataset.name,source,result))
    finally:
        events.put(('finished',))


class ImportWorker(QObject):
    completed=Signal(object,object)
    progress=Signal(str)
    mass_ready=Signal(str,str,str,object)
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
