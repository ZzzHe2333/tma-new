from copy import deepcopy
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication,QDialog,QDialogButtonBox

from test_feature_ui import ui,imported
from tma_app import mass_normalization as mass
from tma_app.workspace import save_session,load_session
from tma_app.overlay_views import snapshot,validate_views


def activate(ui,key):
    ui._show_document(key)


def test_required_values_and_individual_confirmation_no_default_mass(ui,tmp_path):
    imported(ui,tmp_path,4)
    for curve,value,unit in zip(ui.curves[:3],[.46,.55,.0005],['mg','mg','g']):
        curve.dataset.metadata.update(LookupMass=[str(value)],LookupMassUnit=[unit])
    doc=ui.active_document();before=deepcopy(ui.plot_options)
    dialog=ui.show_mass_normalization()
    assert [e.text() for e in dialog.edits]==['0.46','0.55','0.5','']
    button=dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not button.isEnabled()
    for check in dialog.checks:check.setChecked(True)
    assert not button.isEnabled()
    dialog.accept();assert dialog.result()!=QDialog.DialogCode.Accepted
    assert ui.plot_options==before and all(c.mass_normalization_mg is None for c in ui.curves)
    dialog.edits[-1].setText('0.48');assert not dialog.checks[-1].isChecked()
    dialog.checks[-1].setChecked(True);assert button.isEnabled()
    dialog.edits[0].setText('nan');assert not button.isEnabled() and not dialog.checks[0].isChecked()
    dialog.edits[0].setText('0.46');dialog.checks[0].setChecked(True)
    dialog.accept();assert dialog.result()==QDialog.DialogCode.Accepted
    assert ui.active_document() is doc and doc.windowTitle()=='Tong1-Tma'


def test_pointwise_scale_direction_offsets_repeat_and_window_isolation(ui,tmp_path):
    imported(ui,tmp_path,2);doc=ui.active_document()
    original={c.uid:c.xy()[1].copy() for c in ui.curves}
    raw=[c.dataset.values.copy() for c in ui.curves]
    other=ui.copy_overlay(doc.key);activate(ui,doc.key)
    ui.curves[0].scale=2.;ui.curves[0].overlay_offset=12.
    masses=dict(zip([c.uid for c in ui.curves],[.46,.55]))
    mass.apply(ui,doc,masses)
    a,b=ui.curves
    np.testing.assert_allclose(a.xy()[1],original[a.uid]*2*.5/.46+12.)
    np.testing.assert_allclose(b.xy()[1],original[b.uid]*.5/.55)
    assert a.result_transform('temperature')['scale']==pytest.approx(2*.5/.46)
    once=[c.xy()[1].copy() for c in ui.curves]
    mass.apply(ui,doc,masses)
    for curve,y,source in zip(ui.curves,once,raw):
        np.testing.assert_array_equal(curve.xy()[1],y)
        np.testing.assert_array_equal(curve.dataset.values,source)
    activate(ui,other.key)
    assert all(c.mass_normalization_factor==1 for c in ui.curves)
    assert ui.plot_options[other.key]['title']!='Tong1-Tma'
    ui.show_normal();assert all(c.mass_normalization_factor==1 for c in ui.curves)
    activate(ui,doc.key);assert [c.mass_normalization_mg for c in ui.curves]==[.46,.55]
    assert a.xy()[1].max()>original[a.uid].max()*2


@pytest.mark.parametrize('bad',[None,0,-.5,float('nan'),float('inf'),True,1e-320])
def test_bad_mass_is_atomic_for_all_curves(ui,tmp_path,bad):
    imported(ui,tmp_path,2);doc=ui.active_document();before=deepcopy(ui.plot_options)
    states=[snapshot(c) for c in ui.curves]
    with pytest.raises(ValueError):mass.apply(ui,doc,{ui.curves[0].uid:.46,ui.curves[1].uid:bad})
    assert ui.plot_options==before and [snapshot(c) for c in ui.curves]==states


def test_title_export_restore_and_copy_preserve_independent_profiles(ui,tmp_path):
    imported(ui,tmp_path,2);doc=ui.active_document()
    ui.plot_options[doc.key].update(title='旧标题',window_name='旧窗口',export_title='旧导出')
    values={c.uid:.46 for c in ui.curves};mass.apply(ui,doc,values)
    assert ui.plot_options[doc.key]['export_title']=='Tong1-Tma'
    assert any(t.get_text()=='Tong1-Tma' for t in ui.figure.texts)
    ui.write_plot(tmp_path/'normalized.png');assert (tmp_path/'normalized.png').is_file()
    other=ui.copy_overlay(doc.key)
    mass.apply(ui,other,{c.uid:.55 for c in ui.curves})
    activate(ui,doc.key);assert all(c.mass_normalization_mg==.46 for c in ui.curves)
    dialog=ui.show_mass_normalization();dialog.restore_original()
    assert dialog.result()==QDialog.DialogCode.Accepted
    assert ui.plot_options[doc.key]['title']=='旧标题' and doc.windowTitle()=='旧窗口'
    assert ui.plot_options[doc.key]['export_title']=='旧导出'
    assert all(c.mass_normalization_factor==1 for c in ui.curves)
    activate(ui,other.key);assert all(c.mass_normalization_mg==.55 for c in ui.curves)


@pytest.mark.parametrize('normal_active',[False,True])
def test_session_preserves_normalized_comparison_and_old_session_defaults(ui,tmp_path,normal_active):
    imported(ui,tmp_path,2);doc=ui.active_document()
    mass.apply(ui,doc,{c.uid:v for c,v in zip(ui.curves,[.46,.55])})
    expected={c.uid:c.xy()[1].copy() for c in ui.curves}
    if normal_active:ui.show_normal()
    path=tmp_path/'mass.tmas';save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    ui.close_all_documents();ui.restore_session(path);activate(ui,doc.key)
    for curve in ui.curves:np.testing.assert_array_equal(curve.xy()[1],expected[curve.uid])
    assert ui.active_document().windowTitle()=='Tong1-Tma'
    legacy={doc.key:{k:v for k,v in snapshot(ui.curves[0]).items() if k!='mass_normalization_mg'}}
    assert validate_views(legacy)[doc.key]['mass_normalization_mg'] is None


def test_button_overlay_only_and_preserves_plot_geometry(ui,tmp_path):
    imported(ui,tmp_path,2);doc=ui.active_document();QApplication.processEvents()
    assert doc.mass_normalize_button.isVisible()
    assert doc.mass_normalize_button.geometry().right()<doc.canvas.width()
    assert doc.mass_normalize_button.geometry().top()==32
    doc.mass_normalize_button.click();assert ui.dialogs['mass_normalization'].isVisible()
    ui.dialogs['mass_normalization'].reject();ui.show_normal();QApplication.processEvents()
    assert not ui.active_document().mass_normalize_button.isVisible()


@pytest.mark.parametrize('kind',['signal_max','dimension_change','curve_value_y'])
def test_confirmed_analysis_uses_scaled_height_and_roundtrips(ui,tmp_path,kind):
    imported(ui,tmp_path,2);doc=ui.active_document();curve=ui.curves[0]
    original=curve.xy()[1].copy()
    mass.apply(ui,doc,{c.uid:.46 for c in ui.curves})
    ui.files.setCurrentItem(ui.files.topLevelItem(0))
    entry=ui.start_point_measurement(kind);ui.confirm_measurement()
    if kind=='curve_value_y':ui.dialogs['label_point'].accept()
    assert entry in ui.results
    if kind=='signal_max':assert entry['values']['max_y']==pytest.approx(original.max()*.5/.46)
    elif kind=='dimension_change':
        a,b=entry['interactive']['indices']
        assert entry['values']['H']==pytest.approx((original[b]-original[a])*.5/.46)
    else:
        position=entry['interactive']['positions'][0]
        assert entry['values']['y']==pytest.approx(np.interp(position,np.arange(len(original)),original)*.5/.46)
    path=tmp_path/'measurement.tmas';save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    loaded,_,results=load_session(path)
    assert results[0]['values']==entry['values']


def test_missing_source_mass_never_uses_note_fallback_or_stale_sample(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.curves[0]
    curve.dataset.metadata.update(LookupMass=['.47'],LookupMassUnit=['mg'],LookupMassSample=['different'])
    assert mass.known_mass_mg(curve) is None
    curve.dataset.metadata.update(Mass=['0'])
    assert mass.known_mass_mg(curve) is None


def test_adding_unconfirmed_curve_invalidates_whole_comparison(ui,tmp_path):
    imported(ui,tmp_path,3);doc=ui.active_document();third=ui.curves[-1]
    doc.curve_uids.remove(third.uid)
    ui.plot_options[doc.key]['overlay_members']=list(doc.curve_uids)
    mass.apply(ui,doc,{c.uid:.46 for c in ui.curves[:2]})
    doc.curve_uids.append(third.uid)
    ui.plot_options[doc.key]['overlay_members']=list(doc.curve_uids)
    ui.redraw()
    assert all(c.mass_normalization_factor==1 for c in ui.curves)
    assert ui.plot_options[doc.key]['mass_normalization_titles'] is None
    assert doc.windowTitle()!='Tong1-Tma'


def test_reopen_distinguishes_read_mass_from_previously_entered_mass(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.curves[0]
    curve.dataset.metadata.update(LookupMass=['0.47'],LookupMassUnit=['mg'])
    mass.apply(ui,ui.active_document(),{curve.uid:.46})
    dialog=ui.show_mass_normalization()
    assert dialog.table.item(0,1).text()=='0.47'
    assert dialog.edits[0].text()=='0.46'
    assert not dialog.checks[0].isChecked()
    dialog.reject()
