"""Thresholds, durable reset, nonblocking UI, and successful action wiring."""
import json
import queue
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication,QFileDialog,QInputDialog,QDialog,QMessageBox
from PySide6.QtCore import QTimer

from test_feature_ui import ui,source
from tma_app import achievements as rules
from tma_app.batch_qa import wait_until


@pytest.mark.parametrize('achievement',rules.CATALOG,ids=lambda a:a.key)
def test_each_material_threshold_is_exact_and_reset_is_fresh(achievement):
    state=rules.empty();last=0
    for tier in rules.TIERS:
        if tier.threshold-last>1:
            assert rules.advance(state,achievement.key,tier.threshold-last-1)==[]
        assert rules.advance(state,achievement.key)==[tier.key]
        assert achievement.key+':'+tier.key in state['earned'];last=tier.threshold
    assert rules.advance(state,achievement.key)==[]
    assert len(rules.validate(state)['earned'])==7
    assert rules.advance(rules.empty(),achievement.key)==['wood']


def test_worker_coalesces_persists_restart_and_corrupt_reset(tmp_path):
    path=tmp_path/'achievements.json'
    def run(commands):
        inputs=queue.Queue();events=queue.Queue()
        for c in [*commands,('stop',)]:inputs.put(c)
        rules.disk_worker([path],None,inputs,events)
        return list(events.queue)
    run([('record','images',100)])
    saved=json.loads(path.read_text());assert saved['counts']['images']==100 and len(saved['earned'])==3
    assert run([])[0][1]==saved
    run([('reset',1)]);assert json.loads(path.read_text())==rules.empty()
    path.write_text('damaged');events=run([('record','images',1)])
    assert path.read_text()=='damaged' and any(e[0]=='error' for e in events)
    run([('reset',1),('record','images',1)])
    assert json.loads(path.read_text())['counts']['images']==1


def test_successful_exports_preview_cancel_failure_and_note_do_not_wait(ui,tmp_path,monkeypatch):
    from tma_app import mass_lookup
    from tma_app.achievement_ui import record
    ui.finish_import([source(tmp_path/'a.001'),source(tmp_path/'b.001')],[])
    manager=ui.achievement_controller
    wait_until(lambda:manager.loaded and manager.state['counts']['imports']==2)
    calls=[]
    monkeypatch.setattr(ui,'write_plot',lambda path:calls.append(path))
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *args:('',''))
    ui.export_plot();QApplication.processEvents();assert manager.state['counts']['images']==0
    ui.write_plot(tmp_path/'preview.png');assert manager.state['counts']['images']==0
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *args:(str(tmp_path/'a.png'),''))
    ui.export_plot();wait_until(lambda:manager.state['counts']['images']==1)
    def fail(path):raise OSError('locked')
    monkeypatch.setattr(ui,'write_plot',fail);monkeypatch.setattr(ui,'warn',lambda message:None)
    ui.export_plot();QApplication.processEvents();assert manager.state['counts']['images']==1
    ui.show_overlay();wait_until(lambda:manager.state['counts']['overlays']>=1)
    before=manager.state['counts']['overlays'];ui.show_overlay();wait_until(lambda:manager.state['counts']['overlays']==before+1)
    # No remote mass function may be reached when opening a multiline note.
    monkeypatch.setattr(mass_lookup,'lookup_record',lambda *a,**k:(_ for _ in ()).throw(AssertionError('network lookup on GUI')))
    monkeypatch.setattr(QInputDialog,'exec',lambda self:QDialog.DialogCode.Rejected)
    started=time.monotonic();ui.add_note();assert time.monotonic()-started<1
    wall=ui.show_achievements();QApplication.processEvents()
    assert len(wall.cards)==9 and sum(len(c.badges) for c in wall.cards)==63
    assert wall.cards[0].badges[0].unlocked and not wall.cards[0].badges[1].unlocked
    # Cancel clear preserves all stats; accepted clear removes only achievements.
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.No)
    wall.clear_statistics();QApplication.processEvents();assert manager.state['counts']['images']==1
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.Yes)
    original_count=len(ui.curves);wall.clear_statistics();wait_until(lambda:sum(manager.state['counts'].values())==0)
    assert len(ui.curves)==original_count
    record(ui,'images');wait_until(lambda:manager.state['counts']['images']==1)


def test_note_uses_imported_mass_without_cache_disk_or_network(tmp_path,monkeypatch):
    from tma_app.mass_lookup import note_text_for_curve
    from tma_app.workspace import Curve
    curve=Curve(source(tmp_path/'a.001'))
    curve.dataset.metadata.update(LookupMass=['0.00047'],LookupMassUnit=['g'],LookupMassSample=[curve.sample_name])
    assert '0.47 mg' in note_text_for_curve(curve)
    curve.dataset.metadata['LookupMassSample']=['different']
    assert '0.50 mg' in note_text_for_curve(curve)


def test_directory_stall_never_blocks_gui_or_cancel(ui,tmp_path,monkeypatch):
    from tma_app import async_data_picker as picker
    release=threading.Event();entered=threading.Event()
    original=picker.os.scandir
    def stalled(path):
        if str(path).endswith('slow'):entered.set();release.wait(5)
        return original(tmp_path)
    monkeypatch.setattr(picker.os,'scandir',stalled)
    start=time.monotonic();dialog=picker.DataFileDialog(ui,'导入',str(tmp_path/'slow'),'TMA (*.001)')
    assert time.monotonic()-start<1
    try:
        dialog.show();wait_until(entered.is_set);beats=[]
        timer=QTimer();timer.setInterval(10);timer.timeout.connect(lambda:beats.append(1));timer.start()
        wait_until(lambda:len(beats)>=5);start=time.monotonic();dialog.reject();timer.stop()
        assert time.monotonic()-start<.5 and not dialog.isVisible()
    finally:release.set();dialog.stop();dialog.deleteLater()
