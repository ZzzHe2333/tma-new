"""Serialize preference updates by logical profile, including Windows processes.

No filesystem access is needed to acquire the lock. GUI-side synchronous callers
fail promptly when busy; existing background save jobs can wait up to 30 seconds.
The independent in-memory snapshot lock is never held across this wait or disk I/O.
"""
from contextlib import contextmanager
import errno
import hashlib
import os
import threading
from weakref import WeakValueDictionary

_locks = WeakValueDictionary()
_guard = threading.Lock()


def _busy():
    return BlockingIOError(errno.EBUSY, '配置正在保存，请稍后重试；当前修改尚未保存。')


@contextmanager
def settings_transaction(primary):
    identity = os.path.normcase(os.path.abspath(primary))
    timeout = 0 if threading.current_thread() is threading.main_thread() else 30000
    if os.name != 'nt':
        with _guard:
            lock = _locks.get(identity)
            if lock is None:
                lock = threading.RLock()
                _locks[identity] = lock
        acquired = lock.acquire(blocking=False) if not timeout else lock.acquire(timeout=timeout / 1000)
        if not acquired:
            raise _busy()
        try:
            yield
        finally:
            lock.release()
        return

    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateMutexW
    create.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    create.restype = wintypes.HANDLE
    wait = kernel.WaitForSingleObject
    wait.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    wait.restype = wintypes.DWORD
    release = kernel.ReleaseMutex
    release.argtypes = (wintypes.HANDLE,)
    release.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    # The global namespace also coordinates instances in different Windows
    # sessions. Each logical profile still has its own default-security mutex.
    name = 'Global\\ZzzHeTMA.Settings.' + hashlib.sha256(identity.encode('utf-8')).hexdigest()
    handle = create(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    acquired = False
    try:
        result = wait(handle, timeout)
        if result == 0x102:
            raise _busy()
        if result not in (0, 0x80):
            raise ctypes.WinError(ctypes.get_last_error())
        acquired = True
        yield
    finally:
        if acquired:
            release(handle)
        close(handle)
