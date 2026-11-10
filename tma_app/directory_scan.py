"""Cancellable directory helpers. This module deliberately never imports Qt."""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

SCAN_IDLE_SECONDS = 30
_slots = threading.BoundedSemaphore(4)
_guard = threading.Lock()
_children = {}
_retired = {}


class _WindowsJob:
    def __init__(self, process):
        self.handle = None
        import ctypes as c
        from ctypes import wintypes as w
        class Basic(c.Structure):
            _fields_ = [('process_time', c.c_longlong), ('job_time', c.c_longlong),
                        ('flags', w.DWORD), ('minimum', c.c_size_t), ('maximum', c.c_size_t),
                        ('processes', w.DWORD), ('affinity', c.c_size_t),
                        ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class Counters(c.Structure):
            _fields_ = [(name, c.c_ulonglong) for name in ('read_ops', 'write_ops', 'other_ops',
                                                         'read_bytes', 'write_bytes', 'other_bytes')]
        class Extended(c.Structure):
            _fields_ = [('basic', Basic), ('io', Counters), ('process_memory', c.c_size_t),
                        ('job_memory', c.c_size_t), ('peak_process', c.c_size_t), ('peak_job', c.c_size_t)]
        kernel = c.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateJobObjectW; create.argtypes = [c.c_void_p, w.LPCWSTR]; create.restype = w.HANDLE
        configure = kernel.SetInformationJobObject
        configure.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]; configure.restype = w.BOOL
        assign = kernel.AssignProcessToJobObject; assign.argtypes = [w.HANDLE, w.HANDLE]; assign.restype = w.BOOL
        open_process = kernel.OpenProcess; open_process.argtypes = [w.DWORD, w.BOOL, w.DWORD]; open_process.restype = w.HANDLE
        self._close = kernel.CloseHandle; self._close.argtypes = [w.HANDLE]; self._close.restype = w.BOOL
        self.handle = create(None, None)
        if not self.handle: raise c.WinError(c.get_last_error())
        child = None
        try:
            info = Extended(); info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not configure(self.handle, 9, c.byref(info), c.sizeof(info)):
                raise c.WinError(c.get_last_error())
            child = open_process(0x0100 | 0x0001, False, process.pid)
            if not child or not assign(self.handle, child): raise c.WinError(c.get_last_error())
        except Exception:
            self.close(); raise
        finally:
            if child: self._close(child)

    def close(self):
        if self.handle:
            self._close(self.handle); self.handle = None

    def __del__(self):
        self.close()


def command(flag, *args):
    prefix = [sys.executable]
    if not getattr(sys, 'frozen', False): prefix.append(str(Path(__file__).resolve().parents[1] / 'run.py'))
    return [*prefix, flag, *map(str, args)]


def start_process(arguments, directory):
    process = subprocess.Popen(arguments, cwd=directory, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if os.name == 'nt' and process.poll() is None:
        try:
            process._directory_job = _WindowsJob(process)
        except OSError:
            if process.poll() is None:
                process._directory_error = '目录读取进程的隔离保护未能建立。'
    return process


def _launch(request, report):
    return start_process(command('--directory-scan-worker', request, report), request.parent)


def _cleanup(folder):
    # Remove only this helper's known IPC files. Never recursively remove a directory.
    # Windows may briefly retain a terminating process's directory/file handles
    # after its process handle is signalled. Retry locally with a short bound.
    for attempt in range(4):
        for name in ('request.json', 'result.jsonl', 'probe.ready'):
            try: (folder / name).unlink(missing_ok=True)
            except OSError: pass
        try:
            folder.rmdir(); return
        except FileNotFoundError:
            return
        except OSError:
            if attempt < 3: time.sleep(.025 * 2 ** attempt)


def _close_job(process):
    job = getattr(process, '_directory_job', None)
    if job is not None: job.close()


def _reap_finished():
    with _guard:
        completed = [(pid, value) for pid, value in _retired.items() if value[0].poll() is not None]
        for pid, _ in completed: _retired.pop(pid); _children.pop(pid, None)
    for _, (process, folder) in completed:
        _close_job(process); _cleanup(folder); _slots.release()


def _read_rows(report, cancelled):
    rows, complete = [], False
    with report.open(encoding='utf-8') as stream:
        for line in stream:
            if cancelled.is_set(): return None
            value = json.loads(line)
            if not isinstance(value, list) or not value: raise ValueError('目录读取结果格式异常')
            if value[0] == 'error': raise ValueError(str(value[1]))
            if value[0] == 'done':
                complete = len(value) == 2 and type(value[1]) is int and value[1] == len(rows)
                if not complete: raise ValueError('目录读取结果不完整')
                break
            if (len(value) != 6 or value[0] != 'entry' or not isinstance(value[1], str)
                    or not isinstance(value[2], str) or type(value[3]) is not bool
                    or type(value[4]) is not int or value[4] < 0
                    or type(value[5]) not in (int, float) or not math.isfinite(value[5])):
                raise ValueError('目录条目格式异常')
            rows.append(tuple(value[1:]))
    if not complete: raise ValueError('目录读取未完成，请刷新重试。')
    return rows


def scan_directory(directory, cancelled, events):
    acquired, retired = False, False
    process, folder = None, None
    try:
        while not cancelled.is_set():
            _reap_finished()
            if _slots.acquire(timeout=.05): acquired = True; break
        if cancelled.is_set(): return
        folder = Path(tempfile.mkdtemp(prefix='ZzzHeTMA-scan-'))
        request, report = folder / 'request.json', folder / 'result.jsonl'
        request.write_text(json.dumps({'directory': str(directory)}, ensure_ascii=True), encoding='utf-8')
        if cancelled.is_set(): return
        process = _launch(request, report)
        with _guard: _children[process.pid] = process
        if getattr(process, '_directory_error', ''): raise OSError(process._directory_error)
        changed, checked, size = time.monotonic(), 0., -1
        while process.poll() is None:
            if cancelled.wait(.025): return
            now = time.monotonic()
            if now - checked >= .2:
                checked = now
                try: current = report.stat().st_size
                except FileNotFoundError: current = -1
                if current != size: size, changed = current, now
            if now - changed >= SCAN_IDLE_SECONDS:
                raise TimeoutError('目录响应超时，请切换路径或刷新重试。')
        if cancelled.is_set(): return
        if process.returncode != 0: raise ValueError(f'目录读取未完成（退出代码 {process.returncode}），请刷新重试。')
        rows = _read_rows(report, cancelled)
        if rows is not None and not cancelled.is_set(): events.put(('rows', rows))
    except Exception as exc:
        if not cancelled.is_set(): events.put(('error', f'目录未能读取：{exc}'))
    finally:
        if process is not None:
            if process.poll() is None:
                _close_job(process)
                try: process.kill()
                except OSError: pass
                try: process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    with _guard: _retired[process.pid] = (process, folder)
                    retired = True
            if not retired:
                _close_job(process)
                with _guard: _children.pop(process.pid, None)
        if not retired:
            if folder is not None: _cleanup(folder)
            if acquired: _slots.release()


def worker_main(request, report):
    request, report = Path(request), Path(report)
    if (request.name != 'request.json' or report.name != 'result.jsonl'
            or request.parent != report.parent or not request.parent.name.startswith('ZzzHeTMA-scan-')):
        return 2
    try:
        directory = json.loads(request.read_text(encoding='utf-8'))['directory']
        if not isinstance(directory, str) or not directory: return 2
        with report.open('x', encoding='utf-8', buffering=1) as output:
            def emit(value): output.write(json.dumps(value, ensure_ascii=True, allow_nan=False) + '\n')
            try:
                count = 0
                with os.scandir(directory) as entries:
                    for entry in entries:
                        try:
                            is_dir = entry.is_dir(follow_symlinks=False)
                            info = entry.stat(follow_symlinks=False)
                            emit(['entry', entry.name, entry.path, is_dir, info.st_size,
                                  info.st_mtime if math.isfinite(info.st_mtime) else 0.])
                            count += 1
                        except OSError: continue
                emit(['done', count])
            except OSError as exc: emit(['error', str(exc)])
        return 0
    except Exception:
        return 1


def wait_probe(marker):
    """Offline QA helper: a real child which the parent must terminate."""
    marker = Path(marker)
    if marker.name != 'probe.ready' or not marker.parent.name.startswith('ZzzHeTMA-scan-'): return 2
    with marker.open('x') as output: output.write(str(os.getpid()))
    time.sleep(60)
    return 0


class LatestScanWorker:
    """One scanner and one replaceable pending navigation per dialog."""
    def __init__(self, scanner):
        self.scanner = scanner
        self.condition = threading.Condition()
        self.pending = self.current = self.thread = None
        self.closed = False

    def submit(self, request):
        with self.condition:
            if self.closed: return
            if self.current is not None: self.current[1].set()
            if self.pending is not None: self.pending[1].set()
            self.pending = request
            if self.thread is None:
                self.thread = threading.Thread(target=self.run, name='TMA-file-list', daemon=True)
                try: self.thread.start()
                except RuntimeError:
                    self.thread = self.pending = None
                    request[2].put(('error', '目录任务未能启动，请刷新重试。'))
                    return
            self.condition.notify()

    def run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending is not None)
                if self.closed: return
                request = self.current = self.pending; self.pending = None
            try:
                self.scanner(*request)
            except Exception as exc:
                if not request[1].is_set(): request[2].put(('error', f'目录读取失败：{exc}'))
            finally:
                with self.condition: self.current = None

    def close(self):
        with self.condition:
            self.closed = True
            if self.current is not None: self.current[1].set()
            if self.pending is not None: self.pending[1].set()
            self.pending = None
            self.condition.notify()
