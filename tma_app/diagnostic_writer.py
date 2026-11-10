"""One bounded daemon writes immutable event bytes; callers never perform I/O."""
from collections import deque
from datetime import datetime
import json
import threading


class EventWriter:
    def __init__(self, write, close, *, max_records=2048, max_bytes=8 * 1024 * 1024):
        self.write, self.close_handle = write, close
        self.max_records, self.max_bytes = max_records, max_bytes
        self.condition = threading.Condition()
        self.queue = deque()
        self.pending = self.retained_bytes = self.written = self.dropped = self.write_errors = 0
        self.drop_notice = 0
        self.writing = self.stopping = self.closed = False
        self.thread = threading.Thread(target=self._run, name='TMA-diagnostics', daemon=True)
        self.thread.start()

    def submit(self, data):
        data = bytes(data)
        size = len(data)
        with self.condition:
            if self.stopping:
                return False
            if size <= self.max_bytes:
                while self.queue and (self.pending >= self.max_records or self.retained_bytes + size > self.max_bytes):
                    previous = self.queue.popleft()
                    self.pending -= 1
                    self.retained_bytes -= len(previous)
                    self.dropped += 1
                    self.drop_notice += 1
                if self.pending < self.max_records and self.retained_bytes + size <= self.max_bytes:
                    self.queue.append(data)
                    self.pending += 1
                    self.retained_bytes += size
                    self.condition.notify()
                    return True
            self.dropped += 1
            self.drop_notice += 1
            self.condition.notify()
            return False

    def _write_all(self, data):
        try:
            view = memoryview(data)
            while view:
                count = self.write(view)
                if count is None or count <= 0:
                    raise OSError('Event log write made no progress')
                view = view[count:]
            return True
        except Exception:
            with self.condition:
                self.write_errors += 1
            return False

    def _run(self):
        try:
            while True:
                with self.condition:
                    self.condition.wait_for(lambda: self.queue or self.drop_notice or self.stopping)
                    if not self.queue and not self.drop_notice and self.stopping:
                        return
                    dropped, self.drop_notice = self.drop_notice, 0
                    data = self.queue.popleft() if self.queue else None
                    self.writing = True
                if dropped:
                    notice = {'time': datetime.now().astimezone().isoformat(), 'event': 'diagnostics.events_dropped',
                              'thread': threading.get_ident(), 'count': dropped}
                    self._write_all((json.dumps(notice) + '\n').encode('utf-8'))
                success = self._write_all(data) if data is not None else False
                with self.condition:
                    if data is not None:
                        self.pending -= 1
                        self.retained_bytes -= len(data)
                        if success:
                            self.written += 1
                    self.writing = False
                    self.condition.notify_all()
                # Release large records before waiting for another event.
                del data
        finally:
            try:
                self.close_handle()
            except Exception:
                with self.condition:
                    self.write_errors += 1
            with self.condition:
                self.closed = True
                self.condition.notify_all()

    def flush(self, timeout=.2):
        with self.condition:
            return self.condition.wait_for(lambda: not self.pending and not self.writing and not self.drop_notice, timeout)

    def close(self, timeout=.25):
        with self.condition:
            self.stopping = True
            self.condition.notify_all()
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout)
        return not self.thread.is_alive()

    def stats(self):
        with self.condition:
            return dict(pending=self.pending, retained_bytes=self.retained_bytes, written=self.written,
                        dropped=self.dropped, write_errors=self.write_errors, closed=self.closed)
