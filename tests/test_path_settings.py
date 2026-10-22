"""Config persistence, real spreadsheet formats and sample-name mass matching."""
from pathlib import Path
import hashlib
import pytest
from openpyxl import Workbook
from test_point_interaction import ui
from tma_app import path_settings as settings
from tma_app.mass_lookup import lookup_record, clear_cache
from tma_app.workspace import save_session, load_session


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'config_path', lambda: tmp_path/'ZzzHeTMA/settings.json')
    monkeypatch.delenv('TMA_MASS_XLSX', raising=False)
    clear_cache()
    yield
    clear_cache()


def write_table(path, sample='real sample', mass=12.5):
    rows = [['重量 (mg)', '样品名'], [mass, sample]]
    if path.suffix == '.xlsx':
        book=Workbook();sheet=book.active
        for row in rows:sheet.append(row)
        book.save(path);book.close()
    elif path.suffix == '.xls':
        xlwt=pytest.importorskip('xlwt');book=xlwt.Workbook();sheet=book.add_sheet('m')
        for i,row in enumerate(rows):
            for j,value in enumerate(row):sheet.write(i,j,value)
        book.save(str(path))
    else:
        path.write_text(f'重量 (mg),样品名\n{mass},{sample}\n',encoding='utf-8-sig')


@pytest.mark.parametrize('extension',['csv','xlsx','xls'])
def test_real_formats_header_detection_units_and_no_source_changes(tmp_path, extension):
    path=tmp_path/f'm.{extension}';write_table(path)
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    settings.save_paths({'m':str(path),'other':str(tmp_path/'other')})
    result=lookup_record('real sample')
    assert result.value==12.5 and result.unit=='mg' and str(path) in result.source
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    assert settings.load_paths()=={'m':str(path),'other':str(tmp_path/'other')}
    assert lookup_record('real').value is None


def test_folder_conflicts_missing_file_recovery_and_same_path_revision(tmp_path):
    folder=tmp_path/'tables';folder.mkdir();a=folder/'a.csv';b=folder/'b.xlsx'
    settings.save_paths({'m':str(folder)})
    assert lookup_record('real sample').value is None
    write_table(a);assert lookup_record('real sample').value==12.5
    write_table(b,mass=14);assert '不同重量' in lookup_record('real sample').message
    write_table(b,mass=12.5);assert lookup_record('real sample').value==12.5
    a.unlink();write_table(b,mass=17);assert lookup_record('real sample').value==17


@pytest.mark.parametrize('weight',['-1','nan','inf','0','abc123'])
def test_invalid_mass_never_becomes_a_weight(tmp_path,weight):
    path=tmp_path/'m.csv';write_table(path,mass=weight)
    assert lookup_record('real sample',path).value is None


def test_no_header_bc_layout_and_numeric_xls_style_batch(tmp_path):
    path=tmp_path/'m.csv';path.write_text('ignore,12345,2.75\n',encoding='utf-8')
    assert lookup_record('12345.001',path).value==2.75


def test_settings_save_cancel_match_sample_name_and_preserve_active_file(ui,tmp_path):
    path=tmp_path/'m.csv';write_table(path)
    curve=ui.selected();curve.dataset.metadata['Sample']=['real sample'];original=curve.dataset.values.copy();doc=ui.active_document()
    dialog=ui.show_path_settings();dialog.paths.item(0,1).setText(str(path));dialog.test_mass()
    assert '12.5 mg' in dialog.feedback.text()
    dialog.reject();assert settings.load_paths()['m']=='' and 'LookupMass' not in curve.dataset.metadata
    dialog=ui.show_path_settings();dialog.paths.item(0,1).setText(str(path));dialog.add_path()
    dialog.paths.item(1,0).setText('future');dialog.paths.item(1,1).setText(str(tmp_path/'future'));dialog.accept()
    assert settings.load_paths()['future']==str(tmp_path/'future')
    assert ui.selected() is curve and ui.active_document() is doc
    assert curve.dataset.metadata['LookupMass']==['12.5'] and curve.dataset.metadata['LookupMassUnit']==['mg']
    assert 'Mass' not in curve.dataset.metadata
    import numpy as np
    np.testing.assert_array_equal(original,curve.dataset.values)
    session=tmp_path/'mass.tmas';save_session(session,ui.curves,ui.domain,ui.results,ui.plot_options)
    assert load_session(session)[0][0].dataset.metadata['LookupMass']==['12.5']
