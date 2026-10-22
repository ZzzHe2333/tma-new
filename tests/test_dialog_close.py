"""Title-bar close keeps reusable panels and discards unconfirmed drafts."""
from copy import deepcopy
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog
from test_point_interaction import ui


@pytest.mark.parametrize('key',['metadata','data','results','log'])
def test_panel_close_button_enabled_reopen_preserves_data(ui,key):
    before=list(ui.curves);results=deepcopy(ui.results);doc=ui.active_document();selected=ui.selected()
    ui.show_view(key);dialog=ui.dialogs[key];QApplication.processEvents()
    assert dialog.windowFlags() & Qt.WindowType.WindowCloseButtonHint
    assert not dialog.windowFlags() & Qt.WindowType.WindowContextHelpButtonHint
    panel=ui._panels[key]
    assert dialog.close();QApplication.processEvents()
    assert not dialog.isVisible() and dialog.result()==QDialog.DialogCode.Rejected
    ui.show_view(key);QApplication.processEvents()
    assert ui.dialogs[key] is dialog and panel.parentWidget() is dialog and dialog.isVisible()
    assert ui.curves==before and ui.results==results and ui.selected() is selected and ui.active_document() is doc
    dialog.close()


def test_property_panel_title_close_and_bottom_close_both_reject(ui):
    from PySide6.QtWidgets import QDialogButtonBox
    dialog=ui.show_signal_options();QApplication.processEvents()
    assert dialog.windowFlags() & Qt.WindowType.WindowCloseButtonHint
    box=dialog.findChild(QDialogButtonBox)
    box.button(QDialogButtonBox.StandardButton.Close).click()
    assert not dialog.isVisible() and dialog.result()==QDialog.DialogCode.Rejected
    ui.show_signal_options();assert dialog.isVisible();dialog.close()
    assert not dialog.isVisible()


def test_settings_title_close_discards_unsaved_paths(ui,tmp_path,monkeypatch):
    from tma_app import path_settings
    monkeypatch.setattr(path_settings,'config_path',lambda:tmp_path/'ZzzHeTMA/settings.json')
    dialog=ui.show_path_settings();dialog.paths.item(0,1).setText('unsaved.xlsx')
    assert dialog.windowFlags() & Qt.WindowType.WindowCloseButtonHint
    assert dialog.close() and path_settings.load_paths()['m']==''


def test_graph_options_title_close_discards_draft(ui):
    before=deepcopy(ui.plot_options)
    dialog=ui.show_curve_options();QApplication.processEvents()
    assert dialog.windowFlags() & Qt.WindowType.WindowCloseButtonHint
    assert dialog.close() and ui.plot_options==before
