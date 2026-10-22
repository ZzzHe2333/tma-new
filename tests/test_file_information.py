"""Native text edits preserve analyses; size edits atomically reread only their file."""
from copy import deepcopy
from pathlib import Path
import hashlib
import numpy as np
import pytest
from PySide6.QtWidgets import QDialog,QPushButton
from test_feature_ui import ui,imported
from tma_app.reader import read_dataset
from tma_app.file_information import validate_text_overrides,prepare_edit,effective_size
from tma_app.workspace import save_session,load_session


def real_import(ui,tmp_path,count=3):
    datasets=[]
    for index in range(count):
        path=tmp_path/f'real-{index}.001'
        header=f'Sample source-{index}\nSize 1.5 mm\nOperator original\nMethod heating\nComment source comment\nNsig 3\nSig1 Time (min)\nSig2 Temperature (°C)\nSig3 Dimension Change (µm)\nStartOfData\n'
        path.write_text(header+'\n'.join(f'{i}\t{100+i}\t{2*i*i}' for i in range(7)),encoding='utf-8-sig')
        datasets.append(read_dataset(path))
    ui.finish_import(datasets,[]);ui.show_normal();return ui.selected()


def test_native_text_only_edit_preserves_third_file_working_buffer_and_results(ui,tmp_path):
    curve=real_import(ui,tmp_path);doc=ui.active_document();source_bytes=curve.dataset.path.read_bytes()
    curve.working=curve.dataset.values[:,2]+3;curve.operations=['QA translated signal']
    entry=ui.start_point_measurement('signal_max');ui.confirm_measurement();saved=deepcopy(entry);working=curve.working
    ui.classic_actions['FileInformation1'].trigger();dialog=ui.dialogs['file_information']
    assert dialog.objectName()=='FileInfoForm' and (dialog.width(),dialog.height())==(490,326)
    assert dialog.fields['Sample'].geometry().getRect()==(96,76,381,21)
    assert dialog.findChild(QPushButton,'OK').geometry().getRect()==(220,292,81,25)
    assert dialog.labels['PointsRead'].text()==dialog.labels['PointsUsed'].text()=='7'
    dialog.fields['Sample'].setText('新版样品');dialog.fields['Operator'].setText('operator-2');dialog.fields['Comment'].setText('changed comment');dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted and ui.selected().uid==curve.uid and ui.active_document() is doc
    assert curve.sample_name=='新版样品' and curve.working is working and ui.results==[saved]
    assert curve.dataset.name=='source-2' and curve.dataset.path.read_bytes()==source_bytes
    assert any(t.get_text()=='样品: 新版样品' for t in ui.figure.texts)
    assert '新版样品' in ui.files.currentItem().toolTip(0)
    session=tmp_path/'file-info.tmas';save_session(session,ui.curves,ui.domain,ui.results,ui.plot_options)
    ui.close_all_documents();ui.restore_session(session)
    assert ui.results==[saved] and ui.curves[-1].sample_name=='新版样品'


def test_size_change_rereads_raw_all_peer_signals_removes_only_own_analyses(ui,tmp_path):
    curve=real_import(ui,tmp_path);ui.duplicate_curve();peer=ui.selected();ui.files.setCurrentItem(ui.files.topLevelItem(2));ui.show_normal()
    curve.working=curve.dataset.values[:,2]*3;curve.operations=['QA scale'];curve.checkpoint()
    entry=ui.start_alpha('alpha_fit');ui.confirm_measurement();assert ui.results==[entry]
    other=ui.curves[0];ui.files.setCurrentItem(ui.files.topLevelItem(0));other_entry=ui.start_point_measurement('signal_max');ui.confirm_measurement()
    ui.files.setCurrentItem(ui.files.topLevelItem(2));doc=ui.active_document();before=deepcopy(curve.dataset.metadata);raw=curve.dataset.values.copy();curve.data_indices=[1,2,3,4,5]
    dialog=ui.show_file_information();dialog.size_field.setText('2.75');dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted and ui.results==[other_entry]
    assert ui.active_document() is doc and ui.selected().uid==curve.uid
    assert curve.sample_size_mm==peer.sample_size_mm==2.75 and curve.working is peer.working is None
    assert curve.operations==[] and curve.history==[] and curve.data_indices==[1,2,3,4,5]
    assert curve.dataset.metadata==before and curve.dataset is peer.dataset
    np.testing.assert_array_equal(curve.dataset.values,raw)
    new=ui.start_alpha('alpha_fit');assert new['alpha']['reference_length_mm']==2.75
    ui.cancel_measurement()


def test_equivalent_size_spelling_and_cancel_never_reload_or_clear_results(ui,tmp_path):
    curve=real_import(ui,tmp_path);entry=ui.start_point_measurement('signal_max');ui.confirm_measurement();dataset=curve.dataset
    dialog=ui.show_file_information();dialog.size_field.setText('1.500000');dialog.accept()
    assert curve.dataset is dataset and curve.sample_size_mm is None and ui.results==[entry]
    dialog=ui.show_file_information();dialog.fields['Sample'].setText('cancel');dialog.size_field.setText('9');dialog.reject()
    assert curve.dataset is dataset and curve.sample_name=='source-2' and ui.results==[entry]


@pytest.mark.parametrize('size',['-1','nan','inf','not-a-size'])
def test_invalid_size_draft_is_atomic(ui,tmp_path,size):
    curve=real_import(ui,tmp_path,1);dialog=ui.show_file_information();before=curve.dataset;dialog.fields['Sample'].setText('draft');dialog.size_field.setText(size);dialog.accept()
    assert dialog.result()!=QDialog.DialogCode.Accepted and dialog.error.text()
    assert curve.dataset is before and curve.file_info=={} and curve.sample_size_mm is None


def test_missing_or_modified_source_blocks_numeric_edit_but_text_stays_editable(ui,tmp_path):
    curve=real_import(ui,tmp_path,1);path=curve.dataset.path;original=path.read_bytes();before=curve.dataset
    path.write_bytes(original+b'\n')
    dialog=ui.show_file_information();dialog.fields['Sample'].setText('draft');dialog.size_field.setText('3');dialog.accept()
    assert dialog.result()!=QDialog.DialogCode.Accepted and dialog.error.text() and curve.dataset is before and curve.file_info=={}
    dialog.reject();path.unlink()
    dialog=ui.show_file_information();dialog.size_field.setText('3');dialog.accept()
    assert dialog.result()!=QDialog.DialogCode.Accepted and dialog.error.text();dialog.reject()
    dialog=ui.show_file_information();dialog.fields['Sample'].setText('offline text');dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted and curve.sample_name=='offline text'


def test_zero_explicit_size_overrides_positive_source_and_alpha_prompts_again(ui,tmp_path):
    curve=real_import(ui,tmp_path,1);dialog=ui.show_file_information();dialog.size_field.setText('0');dialog.accept()
    assert effective_size(curve)==0 and curve.dataset.metadata['Size']==['1.5 mm']
    ui.start_alpha('alpha_fit');assert ui._pending_measurement is None and ui.dialogs['sample_size'].isVisible()
    ui.dialogs['sample_size'].reject();session=tmp_path/'zero.tmas';save_session(session,ui.curves,ui.domain,[],ui.plot_options)
    assert load_session(session)[0][0].sample_size_mm==0


def test_file_dialog_cannot_commit_to_another_document(ui,tmp_path):
    curve=real_import(ui,tmp_path);dialog=ui.show_file_information();source_doc=ui.active_document();dialog.fields['Sample'].setText('source-only')
    other=next(doc for key,doc in ui.documents.items() if key!=source_doc.key and not ui._is_overlay(key))
    ui.mdi.setActiveSubWindow(other);ui.document_activated(other);dialog.accept()
    assert dialog.error.text() and curve.file_info=={} and dialog.result()!=QDialog.DialogCode.Accepted
    ui.mdi.setActiveSubWindow(source_doc);ui.document_activated(source_doc);dialog.accept();assert curve.sample_name=='source-only'


def test_text_native_limits_preserve_untouched_long_source_but_validate_edits(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.selected();curve.dataset.metadata['Sample']=['x'*50]
    dialog=ui.show_file_information();assert dialog.fields['Sample'].text()=='x'*50
    dialog.fields['Comment'].setText('one change');dialog.accept();assert curve.sample_name=='x'*50
    with pytest.raises(ValueError):validate_text_overrides({'Sample':'x'*33})
    with pytest.raises(ValueError):validate_text_overrides({'Operator':'x'*26})
    with pytest.raises(ValueError):validate_text_overrides({'Comment':'x'*65})
    with pytest.raises(ValueError):validate_text_overrides({'Sample':'bad\nname'})
    with pytest.raises(ValueError):validate_text_overrides({'Other':'unknown'})


def test_new_signal_and_csv_metadata_keep_current_info_separate_from_source(ui,tmp_path):
    curve=real_import(ui,tmp_path,1);dialog=ui.show_file_information();dialog.fields['Sample'].setText('display-name');dialog.accept()
    ui.duplicate_curve();assert ui.selected().file_info=={'Sample':'display-name'}
    path=tmp_path/'data.csv';ui.write_data(path,ui.selected())
    import json
    side=json.loads(path.with_suffix('.csv.meta.json').read_text(encoding='utf-8'))
    assert side['metadata']['Sample']==['source-0'] and side['file_information']['text']['Sample']=='display-name'
