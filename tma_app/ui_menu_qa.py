"""Native menu clicks before restart, including a deliberately stalled save."""
import json
import threading
import time
import traceback

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest

from . import __version__, ui_size
from .reader import read_dataset
from .batch_qa import wait_until


def verify(window, output, paths):
    output.parent.mkdir(parents=True, exist_ok=True)
    report={'version':__version__,'status':'failed','checks':[]}
    original=ui_size.save_size;entered=threading.Event();release=threading.Event()
    ticks=[];threads=[];timer=QTimer();timer.timeout.connect(lambda:ticks.append(time.monotonic()));timer.start(10)
    def choose(key):
        menu=window.ui_size_menu;action=next(a for a in menu.actions() if a.data()==key)
        QTimer.singleShot(60,lambda:QTest.mouseClick(menu,Qt.MouseButton.LeftButton,pos=menu.actionGeometry(action).center()))
        start=time.monotonic();menu.exec(window.mapToGlobal(window.rect().center()))
        assert not menu.isVisible();return time.monotonic()-start
    def blocked(key,**kwargs):
        threads.append(threading.get_ident());entered.set();release.wait(15);return original(key,**kwargs)
    try:
        window.finish_import([read_dataset(path) for path in paths],[]);window.show_overlay()
        ui_size.save_size=blocked
        report['native_menu_return_seconds']=choose('large')
        assert report['native_menu_return_seconds']<1
        wait_until(entered.is_set);baseline=len(ticks)
        wait_until(lambda:len(ticks)>baseline+20)
        assert window._ui_size_controller.busy and ui_size.active_size()=='standard'
        assert threads[0]!=threading.get_ident()
        # Other windows can be opened and closed while the setting write waits.
        dialog=window.show_path_settings();dialog.show();dialog.reject()
        window.grab().save(str(output.with_suffix('.pending.png')))
        report['checks'].append('native_menu_closes_and_gui_remains_responsive_during_stalled_write')
        release.set();wait_until(lambda:not window._ui_size_controller.busy)
        assert ui_size.saved_size()=='large'
        ui_size.save_size=original
        for key in ('extra_large','standard','large','standard'):
            assert choose(key)<1
            controller=window._ui_size_controller
            wait_until(lambda:not controller.busy and not controller.dispatch.isActive())
            assert ui_size.saved_size()==key
        assert ui_size.active_size()=='standard'
        report['checks']+=['repeated_native_large_extra_large_and_standard_choices_saved_before_restart',
                           'active_scale_unchanged_until_restart_and_worker_never_touches_qt']
        report.update(status='passed',gui_heartbeats=len(ticks))
    except Exception:report['error']=traceback.format_exc()
    finally:
        release.set();ui_size.save_size=original;timer.stop()
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        window.dirty=False;window.close()
    if report['status']!='passed':raise SystemExit(1)
