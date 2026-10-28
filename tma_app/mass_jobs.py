"""GUI-polled mass lookups; slow SMB/Excel reads never wait on the GUI."""
from __future__ import annotations

import queue
import threading
import os
from collections import OrderedDict
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal, Slot


@dataclass(frozen=True)
class _WorkerFailure:
    message: str


@dataclass(frozen=True)
class _ResolvedSource:
    source: str


def lookup_worker(requests, source, cancelled, events, force=False, validate_source=False):
    from .diagnostics import record_event
    from .mass_lookup import lookup_record, configured_source, MassMatch
    resolve_source = source is None
    if resolve_source:
        source = configured_source()
        if not source:
            events.put(_WorkerFailure('未配置 m 数据源；已读取的重量仍可使用，缺失项请手动填写。'))
            return
        events.put(_ResolvedSource(source))
    elif validate_source and configured_source() != source:
        events.put(_WorkerFailure('m 数据源已变化，请重新读取并核对重量。'))
        return
    cache = {}
    for key, sample in requests:
        if cancelled.is_set(): break
        record_event('mass.lookup.start', sample=sample, source=source)
        if sample not in cache:
            try:
                cache[sample] = lookup_record(sample, source, force=True) if force and not cache else lookup_record(sample, source)
            except Exception: cache[sample] = MassMatch(message='m 数据源读取失败，请检查路径与访问权限', unavailable=True)
        record_event('mass.lookup.result', sample=sample, matched=cache[sample].value is not None)
        if (resolve_source or validate_source) and configured_source() != source:
            events.put(_WorkerFailure('m 数据源已变化，请重新读取并核对重量。'))
            return
        if not cancelled.is_set(): events.put((key, cache[sample]))


class MassLookupDispatcher:
    """Two pure daemon workers; one active lookup per source, eight pending jobs."""
    def __init__(self):
        self.condition=threading.Condition();self.pending=OrderedDict()
        self.active={};self.sources=set();self.threads=[]

    @staticmethod
    def source_key(source):
        if source is None:return ('configured-source',)
        text=str(source).strip()
        return text if text.startswith('cloud://') else os.path.normcase(os.path.abspath(text))

    def submit(self,key,requests,source,cancelled,events,force,state):
        source_key = ('configured-source',key) if source is None else self.source_key(source)
        request=(tuple(requests),source,cancelled,events,force,state,source_key)
        with self.condition:
            if len(self.pending)>=8:return False
            self.pending[key]=request
            if not self.threads:
                for index in range(2):
                    worker=threading.Thread(target=self.run,name=f'TMA-mass-lookup-{index+1}',daemon=True)
                    self.threads.append(worker);worker.start()
            self.condition.notify_all()
        return True

    def cancel(self,key,cancelled):
        cancelled.set()
        with self.condition:
            pending=self.pending.get(key)
            if pending is not None and pending[2] is cancelled:self.pending.pop(key)
            self.condition.notify_all()

    def take(self):
        with self.condition:
            while True:
                for key,request in list(self.pending.items()):
                    if request[2].is_set():self.pending.pop(key);continue
                    if request[-1] in self.sources:continue
                    self.pending.pop(key);self.active[key]=request[2];self.sources.add(request[-1])
                    return key,request
                self.condition.wait()

    def run(self):
        while True:
            key,request=self.take()
            requests,source,cancelled,events,force,state,source_key=request
            state['thread']=threading.current_thread()
            try:lookup_worker(requests,source,cancelled,events,force,state.get('validate_source',False))
            except Exception:
                # Preserve any rows already delivered and the existing weights
                # for remaining rows; do not turn failures into missing values.
                if not cancelled.is_set():
                    events.put(_WorkerFailure('m 后台查询失败，请重试；已读取的重量保留'))
            finally:
                events.put(None)
                with self.condition:
                    self.active.pop(key,None);self.sources.discard(source_key);self.condition.notify_all()
                key=request=requests=source=cancelled=events=force=state=source_key=None


DISPATCHER=MassLookupDispatcher()


class MassLookupJob(QObject):
    row_ready = Signal(str, object)
    finished = Signal()

    def __init__(self, requests, source, parent=None, *, force=False, validate_source=False):
        super().__init__(parent)
        self.requests = list(requests); self.source = source
        self.force = force
        self.error_message = ''
        self.resolved_source = None
        self.cancelled = threading.Event(); self.events = queue.Queue()
        self._dispatch_key=object();self._thread_state={'validate_source':validate_source};self._started=False
        self.timer = QTimer(self); self.timer.setInterval(30); self.timer.timeout.connect(self.drain)

    def start(self):
        if self.cancelled.is_set() or self._started:return
        self._started=True
        if not DISPATCHER.submit(self._dispatch_key,self.requests,self.source,self.cancelled,self.events,self.force,self._thread_state):
            self.error_message='m 后台查询队列已满，请稍后重试；已读取的重量保留'
            self.events.put(None)
        self.timer.start()

    @property
    def worker_thread(self):return self._thread_state.get('thread')

    def cancel(self):
        DISPATCHER.cancel(self._dispatch_key,self.cancelled);self.timer.stop()

    @Slot()
    def drain(self):
        for _ in range(32):
            if self.cancelled.is_set(): return
            try: value = self.events.get_nowait()
            except queue.Empty: return
            if isinstance(value, _ResolvedSource):
                self.resolved_source = value.source; continue
            if isinstance(value, _WorkerFailure):
                self.error_message = value.message; continue
            if value is None:
                self.timer.stop(); self.finished.emit(); return
            self.row_ready.emit(*value)
