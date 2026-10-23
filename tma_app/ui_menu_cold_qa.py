"""Exercise size persistence on a cold normal Qt event loop, without imports."""
import json
import time
import traceback
import faulthandler

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest

from . import __version__, ui_size


def start(window, application, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed', 'version': __version__, 'checks': []}
    stack = output.with_suffix('.stack.txt').open('w')
    faulthandler.dump_traceback_later(6, file=stack)
    started = time.monotonic()
    requested = []
    ticks = []
    heartbeat = QTimer(window); heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: ticks.append(time.monotonic()))
    heartbeat.start()

    def finish(error=None):
        poll.stop(); heartbeat.stop(); faulthandler.cancel_dump_traceback_later(); stack.close()
        if error: report['error'] = error
        else: report.update(status='passed', checks=['cold_native_menu_size_saved_with_application_exec'])
        report.update(seconds=time.monotonic()-started, heartbeats=len(ticks))
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        window.dirty = False; window.close(); application.exit(0 if error is None else 1)

    def check():
        controller = window._ui_size_controller
        if requested and controller.selected == 'extra_large' and not controller.busy and not controller.dispatch.isActive():
            try:
                assert ui_size.saved_size() == 'extra_large'
                assert '已保存' in window.statusBar().currentMessage()
                finish()
            except Exception: finish(traceback.format_exc())
        elif time.monotonic()-started > 10: finish('Cold menu save did not finish in 10 seconds')

    poll = QTimer(window); poll.setInterval(50); poll.timeout.connect(check)

    def click():
        menu = window.ui_size_menu
        target = next(a for a in menu.actions() if a.data() == 'extra_large')
        target.triggered.connect(lambda: requested.append(True))
        poll.start()
        QTimer.singleShot(100, lambda: QTest.mouseClick(menu, Qt.MouseButton.LeftButton,
            pos=menu.actionGeometry(target).center()))
        menu.exec(window.mapToGlobal(window.rect().center()))

    QTimer.singleShot(500, click)
    window._cold_ui_size_qa = (poll, heartbeat, stack)
