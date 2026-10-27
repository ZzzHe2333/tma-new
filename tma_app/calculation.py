"""Independent numerical snapshots and one bounded, GUI-free daemon worker.

No live curves, callbacks, Qt wrappers or undo buffers enter the worker. Pending
work is coalesced per document and explicitly bounded across documents.
"""
from collections import OrderedDict
from concurrent.futures import CancelledError
from copy import deepcopy
from dataclasses import replace
import threading

import numpy as np

from .cancellation import check_cancelled
from .workspace import CURVE_FIELDS

BACKGROUND_POINTS = 2000


def _same(a, b):
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        return isinstance(a, np.ndarray) and isinstance(b, np.ndarray) and np.array_equal(a, b, equal_nan=True)
    if isinstance(a, dict):
        return isinstance(b, dict) and a.keys() == b.keys() and all(_same(v, b[k]) for k, v in a.items())
    if isinstance(a, (list, tuple)):
        return type(a) is type(b) and len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _metadata(dataset):
    # Asynchronous m lookups are independent of smoothing. Keep their new values
    # when a completed proposal is rebound to the live dataset.
    return {k: v for k, v in dataset.metadata.items() if not k.startswith('LookupMass')}


class CurveSnapshot:
    def __init__(self, curves):
        self.originals = list(curves)
        self.datasets = [c.dataset for c in curves]
        self.key = curves[0].dataset.document_key
        self.histories = [tuple(map(id, c.history)) for c in curves]
        # dataclasses.replace resets the disposable X cache; dropping history
        # avoids duplicating every historical working signal on the GUI thread.
        self.curves = deepcopy([replace(c, history=[]) for c in curves])
        for c in self.curves:
            for array in (c.dataset.values, c.working, c.smooth_source):
                if array is not None: array.flags.writeable = False

    def matches(self, curves):
        current = [c for c in curves if c.dataset.document_key == self.key]
        if len(current) != len(self.originals): return False
        checked = set()
        for live, original, saved, history, dataset in zip(current, self.originals, self.curves, self.histories, self.datasets):
            if live is not original or live.dataset is not dataset: return False
            # The saved object is distinct; compare every editable field, undo
            # membership and numeric array, including in-place external edits.
            if tuple(map(id, live.history)) != history: return False
            if any(not _same(getattr(live, k), getattr(saved, k)) for k in CURVE_FIELDS): return False
            if not _same(live.working, saved.working) or not _same(live.smooth_source, saved.smooth_source): return False
            dataset = live.dataset
            if id(dataset) not in checked:
                checked.add(id(dataset))
                old = saved.dataset
                if (dataset.path, dataset.sha256, dataset.signals, dataset.instance_id, dataset.opening_index) != (old.path, old.sha256, old.signals, old.instance_id, old.opening_index): return False
                if not _same(dataset.values, old.values) or not _same(_metadata(dataset), _metadata(old)): return False
        return True

    def worker_curves(self):
        # Private, read-only numerical buffers can be shared by the guard and
        # task. All mutable presentation/state containers belong to the task.
        return [replace(c, history=[], **deepcopy({k: getattr(c, k) for k in CURVE_FIELDS})) for c in self.curves]


def calculate(request, cancelled):
    check_cancelled(cancelled)
    curves = request['curves']
    if request['kind'] == 'smooth':
        from .data_limits import smoothed_state
        result = smoothed_state(curves[0], request['domain'], request['width'], use_saved_x=False, cancelled=cancelled)
    else:
        from .signal_proposal import build_proposal
        result = build_proposal(curves, curves[0].dataset, request['template'], cancelled=cancelled)
    check_cancelled(cancelled)
    return result


class CalculationDispatcher:
    """One active calculation, at most eight latest pending documents."""
    def __init__(self):
        self.condition = threading.Condition()
        self.pending = OrderedDict()
        self.active = None
        self.thread = None

    def submit(self, key, request, cancelled, events):
        with self.condition:
            previous = self.pending.pop(key, None)
            if previous is not None: previous[1].set()
            if self.active is not None and self.active[0] == key: self.active[1].set()
            if len(self.pending) >= 8:
                raise ValueError('后台计算队列已满，请稍后重试')
            self.pending[key] = (request, cancelled, events)
            if self.thread is None:
                self.thread = threading.Thread(target=self.run, name='TMA-numerical-worker', daemon=True)
                self.thread.start()
            self.condition.notify()

    def cancel(self, key, cancelled):
        cancelled.set()
        with self.condition:
            pending = self.pending.get(key)
            if pending is not None and pending[1] is cancelled: self.pending.pop(key)

    def run(self):
        while True:
            with self.condition:
                while not self.pending: self.condition.wait()
                key, (request, cancelled, events) = self.pending.popitem(last=False)
                self.active = (key, cancelled)
            try:
                value = calculate(request, cancelled)
                if not cancelled.is_set(): events.put(('result', value))
            except CancelledError:
                pass
            except Exception as exc:
                # Store only text, never an exception traceback retaining task
                # buffers, or a signal that could enter Qt from this thread.
                if not cancelled.is_set(): events.put(('error', str(exc) or type(exc).__name__))
            finally:
                with self.condition: self.active = None
                request = value = events = cancelled = key = None


DISPATCHER = CalculationDispatcher()
