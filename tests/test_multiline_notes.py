"""Editable method-note defaults with Excel mass, fallback and session roundtrip."""
import hashlib
from copy import deepcopy
import pytest
from openpyxl import Workbook
from PySide6.QtWidgets import QInputDialog, QPlainTextEdit
from test_point_interaction import ui
from tma_app import path_settings
from tma_app.mass_lookup import clear_cache, default_note_text
from tma_app.workspace import save_session, load_session


@pytest.fixture(autouse=True)
def isolated_mass_config(tmp_path, monkeypatch):
    monkeypatch.setattr(path_settings, 'config_path', lambda: tmp_path/'ZzzHeTMA/settings.json')
    monkeypatch.delenv('TMA_MASS_XLSX', raising=False)
    clear_cache()
    yield
    clear_cache()


def weighing_table(tmp_path, value=.47, unit='mg'):
    path=tmp_path/'m.xlsx';book=Workbook();sheet=book.active
    sheet.append(['样品名', f'重量 ({unit})' if unit else '重量']);sheet.append(['point', value])
    book.save(path);book.close();path_settings.save_paths({'m':str(path)})
    return path


@pytest.mark.parametrize('value,unit',[(.47,'mg'),(.00047,'g'),(.47,'')])
def test_note_uses_excel_sample_mass_in_mg(tmp_path,value,unit):
    path=weighing_table(tmp_path,value,unit);before=hashlib.sha256(path.read_bytes()).hexdigest()
    text=default_note_text('point')
    assert text=='方法日志：30 ℃ 平衡，施加 0.06 N\n                    20 ℃/min加热至 250 ℃\n称取质量：0.47 mg'
    assert default_note_text('unmatched').endswith('称取质量：0.50 mg')
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before


def test_missing_source_uses_requested_fallback(tmp_path):
    assert default_note_text('point').endswith('0.50 mg')
    path_settings.save_paths({'m':str(tmp_path/'missing.xlsx')})
    assert default_note_text('point').endswith('0.50 mg')


def test_large_plain_text_note_accepts_newlines_and_roundtrips(ui,tmp_path,monkeypatch):
    weighing_table(tmp_path);curve=ui.selected();doc=ui.active_document();raw=curve.dataset.values.copy()
    def accept(dialog):
        assert dialog.findChild(QPlainTextEdit) is not None
        assert dialog.width()>=680 and dialog.height()>=380
        assert dialog.textValue().endswith('称取质量：0.47 mg')
        dialog.setTextValue(dialog.textValue()+'\n备注：保留多行')
        return QInputDialog.DialogCode.Accepted
    monkeypatch.setattr(QInputDialog,'exec',accept)
    ui.add_note();entry=ui.results[-1]
    assert entry['kind']=='note' and entry['values']['text'].count('\n')==3
    assert ui.selected() is curve and ui.active_document() is doc
    path=tmp_path/'note.tmas';save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    assert load_session(path)[2][-1]['values']['text']==entry['values']['text']
    ui.write_plot(tmp_path/'note.png')
    import numpy as np
    np.testing.assert_array_equal(raw,curve.dataset.values)


def test_cancel_does_not_add_or_modify_results(ui,monkeypatch):
    previous=deepcopy(ui.results);dirty=ui.dirty
    def cancel(dialog):
        assert dialog.textValue().endswith('0.50 mg')
        return QInputDialog.DialogCode.Rejected
    monkeypatch.setattr(QInputDialog,'exec',cancel)
    ui.add_note();assert ui.results==previous and ui.dirty==dirty
