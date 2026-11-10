"""Local CPU/LAN snapshot; bounded background collection, no public-IP lookup."""
from datetime import datetime
import ipaddress
import platform
import threading
import time


def cpu_model():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
            return str(winreg.QueryValueEx(key,'ProcessorNameString')[0]).strip()
    except (ImportError, OSError):
        return platform.processor().strip()


def lan_address():
    from .notifications import lan_ip
    value=lan_ip()
    try:
        address=ipaddress.ip_address(value)
        networks=('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')
        return str(address) if any(address in ipaddress.ip_network(n) for n in networks) else ''
    except ValueError: return ''


class Snapshot:
    def __init__(self):
        self.lock=threading.Lock()
        self.running=False
        self.updated=0.
        self.value={}

    def get(self):
        with self.lock:
            if not self.running and (not self.value or time.monotonic()-self.updated>300):
                self.running=True
                try:
                    threading.Thread(target=self.collect,name='TMA-local-environment',daemon=True).start()
                except RuntimeError:
                    self.running=False
            return dict(self.value) if self.value else {'cpu_model':'','lan_ip':'','status':'collecting'}

    def collect(self):
        value={}
        for name, function in (('cpu_model',cpu_model),('lan_ip',lan_address)):
            try: value[name]=function()
            except Exception: value[name]=''
        value.update(status='ready',sampled_at=datetime.now().astimezone().isoformat(timespec='seconds'))
        with self.lock:
            self.value=value;self.updated=time.monotonic();self.running=False


_snapshot=Snapshot()


def snapshot():
    return _snapshot.get()
