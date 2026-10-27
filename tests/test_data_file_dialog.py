"""Real timestamp order and process-local A -> B -> B, restart -> A."""
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QDialog,QFileDialog

from test_feature_ui import ui
from tma_app import data_file_dialog as picker,path_settings
from tma_app.batch_qa import wait_until


def files(folder):
    folder.mkdir()
    for name,stamp in (('a-new.001',1700000000),('m-old.001',1500000000),('z-middle.001',1600000000)):
        p=folder/name;p.write_text(name);os.utime(p,(stamp,stamp))


def visible_names(dialog):
    model=dialog.tree.model();root=dialog.tree.rootIndex()
    result=[]
    for row in range(model.rowCount(root)):
        index=model.index(row,0,root)
        source=dialog.headers.mapToSource(index)
        if dialog.headers.sourceModel().fileInfo(source).isFile():result.append(model.data(index))
    return result


def test_details_view_sorts_real_mtime_and_keeps_order_after_navigation(ui,tmp_path):
    a=tmp_path/'A';b=tmp_path/'B';files(a);files(b)
    dialog=picker.DataFileDialog(ui,'导入',str(a),'TMA (*.001)')
    try:
        dialog.show()
        for folder in (a,b):
            dialog.setDirectory(str(folder));wait_until(lambda:len(visible_names(dialog))==3)
            assert visible_names(dialog)==['a-new.001','z-middle.001','m-old.001']
            assert dialog.tree.header().sortIndicatorSection()==3
            assert dialog.tree.header().sortIndicatorOrder()==Qt.SortOrder.DescendingOrder
        assert dialog.viewMode()==QFileDialog.ViewMode.Detail
        assert dialog.tree.model().headerData(3,Qt.Orientation.Horizontal)=='修改时间'
    finally:dialog.close();dialog.deleteLater();QApplication.processEvents()


def test_accept_remembers_B_cancel_preserves_B_and_new_window_starts_A(ui,tmp_path,monkeypatch):
    from tma_app.classic import ClassicMainWindow
    a=tmp_path/'A';b=tmp_path/'B';c=tmp_path/'C';files(a);files(b);files(c)
    path_settings.save_paths({'m':'','open_folder':str(a),'particle_folder':str(c)})
    before=path_settings.config_path().read_bytes();seen=[]
    outcomes=iter(['B','cancel','cancel','cancel'])
    def execute(dialog):
        seen.append(Path(dialog.directory().absolutePath()))
        outcome=next(outcomes)
        if outcome=='B':dialog.setDirectory(str(b));dialog.selectFile(str(b/'a-new.001'));return QDialog.DialogCode.Accepted
        dialog.setDirectory(str(c));return QDialog.DialogCode.Rejected
    monkeypatch.setattr(picker.DataFileDialog,'exec',execute)
    selected,_=picker.get_data_files(ui,'导入','TMA (*.001)')
    assert Path(selected[0]).parent==b
    assert picker.get_data_files(ui,'导入','TMA (*.001)')[0]==[]
    assert picker.get_data_files(ui,'导入','TMA (*.001)')[0]==[]
    restarted=ClassicMainWindow()
    try:picker.get_data_files(restarted,'导入','TMA (*.001)')
    finally:restarted.close()
    assert seen==[a,b,b,a]
    assert path_settings.config_path().read_bytes()==before
    assert path_settings.particle_folder()==str(c)


def test_main_batch_report_and_modern_import_share_one_recent_directory(ui,tmp_path,monkeypatch):
    from tma_app.app import MainWindow
    a=tmp_path/'A';b=tmp_path/'B';files(a);files(b)
    path_settings.save_paths({'m':'','open_folder':str(a)})
    seen=[]
    def execute(dialog):
        seen.append(Path(dialog.directory().absolutePath()))
        if len(seen)==1:
            dialog.setDirectory(str(b));dialog.selectFile(str(b/'a-new.001'));return QDialog.DialogCode.Accepted
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(picker.DataFileDialog,'exec',execute)
    monkeypatch.setattr(ui,'import_files',lambda paths:None)
    ui.open_files()
    batch=ui.show_batch_analysis(popup=False);batch.choose_files()
    report=ui.show_single_report();report.choose_tma();report.close()
    MainWindow.open_files(ui)
    assert seen==[a,b,b,b]
