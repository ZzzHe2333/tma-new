"""Observe imports in QApplication.exec(), using real configured weighing I/O."""
import gc
import hashlib
import json
from pathlib import Path
import time

from PySide6.QtCore import QTimer
from . import __version__


def start(window, application, output, paths, seconds=45):
    output = Path(output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    started = time.perf_counter(); rounds = [False, False]; heartbeats = []
    timer = QTimer(window); timer.setInterval(100)
    window._live_probe_timer = timer
    def tick():
        elapsed = time.perf_counter()-started
        dialog = getattr(window, 'batch_dialog', None)
        if not rounds[0]:
            rounds[0] = True; window.import_files(paths); return
        if not rounds[1] and elapsed >= 15 and window.worker is None and dialog.job is None:
            rounds[1] = True; window.import_files(paths); return
        rows = dialog.rows if dialog else []
        frame = {'seconds': elapsed, 'rows': len(rows), 'numerical_rows': sum(r.get('T1') is not None for r in rows),
                 'mass_rows': sum(r.get('M') is not None for r in rows), 'curves': len(window.curves),
                 'import_running': window.worker is not None, 'batch_running': bool(dialog and dialog.job),
                 'automatic_gc': gc.isenabled()}
        if not heartbeats or elapsed-heartbeats[-1]['seconds'] >= 1:
            heartbeats.append(frame)
            output.with_suffix('.heartbeat.json').write_text(json.dumps(frame, indent=2), encoding='utf-8')
        if elapsed < seconds: return
        timer.stop()
        good = all(rounds) and len(rows) == len(paths)*2 and frame['numerical_rows'] == len(rows) and len(window.curves) == len(rows)
        unchanged = all(hashlib.sha256(p.read_bytes()).hexdigest() == before[str(p)] for p in paths)
        idle = not frame['import_running'] and not frame['batch_running']
        report = {'status': 'passed' if good and unchanged and idle else 'incomplete', 'version': __version__,
                  'event_loop': 'QApplication.exec', 'seconds_observed': elapsed, 'rounds': sum(rounds),
                  'last': frame, 'heartbeat': heartbeats, 'inputs_unchanged': unchanged,
                  'gc_collections': application._tma_gui_gc.collections}
        output.write_text(json.dumps(report, indent=2), encoding='utf-8')
        if idle:
            window.dirty = False; window.close(); application.quit()
    timer.timeout.connect(tick); timer.start()
