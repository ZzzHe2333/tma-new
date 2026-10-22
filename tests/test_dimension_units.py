"""TMA units, acquired references, canonical buffers, view propagation and dialogs."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtWidgets import QDialog,QPushButton
from test_feature_ui import ui,imported,source
from tma_app.workspace import Curve,save_session,load_session
from tma_app.dimension_units import affine,quantity,validate
from tma_app.preferences import load_defaults


def options(unit='µm',offset='none'):return {'dimension':unit,'offset':offset}


@pytest.mark.parametrize('unit,factor',[('µm',1.),('mm',.001),('%',.05),('µm/m',500.),('ppm',500.)])
def test_five_dimension_units_have_explicit_scale_and_preserve_source(tmp_path,unit,factor):
    c=Curve(source(tmp_path/'units.001'),sample_size_mm=2.,unit_options=options(unit));raw=c.dataset.values.copy()
    x,y=c.xy();np.testing.assert_allclose(y,raw[:,2]*factor);np.testing.assert_array_equal(c.dataset.values,raw)
    assert c.result_unit==unit and affine(c,2)['factor']==factor


def test_absolute_zero_size_and_first_acquired_25_reference_with_gap_fallback(tmp_path):
    dataset=source(tmp_path/'reference.001');dataset.values=np.column_stack((np.arange(7),[20,25,30,25,20,25,30],[0,10,20,30,40,50,60]))
    c=Curve(dataset,sample_size_mm=2.,unit_options=options('µm','zero_size'))
    np.testing.assert_allclose(c.xy()[1],dataset.values[:,2]+2000);assert 'Dimension (' in c.result_label
    c.unit_options=options('%','at25');spec=affine(c,2)
    assert spec['reference_25']==10 and spec['reference_mm']==2.01
    np.testing.assert_allclose(c.xy()[1],(dataset.values[:,2]-10)*.1/2.01)
    c.data_indices=[0,2,4,6];spec=affine(c,2)
    assert spec['reference_25'] is None and 'unavailable' in spec['status']
    c.unit_options=options('ppm');c.sample_size_mm=0
    assert c.result_unit=='µm';np.testing.assert_allclose(c.xy()[1],dataset.values[c.active_rows,2])


def test_25_reference_interpolates_adjacent_samples_and_never_extrapolates(tmp_path):
    ds=source(tmp_path/'interp.001');ds.values[:,1]=np.array([10,20,30,40,50,60,70]);ds.values[:,2]=np.array([0,2,8,10,12,14,16])
    c=Curve(ds,sample_size_mm=1.,unit_options=options('µm','at25'));assert affine(c,2)['reference_25']==5
    c.data_indices=[3,4,5,6];assert affine(c,2)['reference_25'] is None


def test_derivative_and_physical_offsets_convert_without_modifying_working_data(tmp_path):
    c=Curve(source(tmp_path/'working.001'),sample_size_mm=2.,unit_options=options('µm/m','zero_size'))
    c.operations=['derivative:Temperature (°C)','ls_window:2.0'];c.y_type='d_temperature';c.working=np.arange(7,dtype=float);working=c.working.copy();c.offset=4;c.scale=2
    np.testing.assert_allclose(c.xy()[1],(working*2+4)*500)
    assert c.display_y_offset()==2000 and c.plot_label=='Alpha (µm/m/°C)'
    np.testing.assert_array_equal(c.working,working)
    c.operations=['normalize'];assert quantity(c)['factor']==1 and c.result_unit=='%'


def test_dimension_custom_x_shift_and_derivative_denominator_use_same_physical_scale(tmp_path):
    c=Curve(source(tmp_path/'x.001'),sample_size_mm=2.,unit_options=options('mm'),x_signal_index=2,x_shift=10)
    np.testing.assert_allclose(c.xy('signal')[0],(c.dataset.values[:,2]+10)*.001)
    np.testing.assert_allclose(c.x_values('signal',canonical=True),c.dataset.values[:,2])
    assert c.x_unit('signal')=='mm' and c.display_x_shift('signal')==.01
    c.operations=['derivative:Dimension Change (µm)'];c.working=np.ones(7)
    np.testing.assert_allclose(c.xy('signal')[1],np.ones(7))
    assert c.result_unit=='(mm)/(mm)'


def test_native_units_form_cancel_save_default_and_inert_other_controls(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.selected();ui.dirty=False;before=deepcopy(ui.plot_options)
    ui.classic_actions['Units1'].trigger();dialog=ui.dialogs['units']
    assert dialog.objectName()=='SigUnitsForm' and (dialog.width(),dialog.height())==(638,450)
    assert dialog.dimension.geometry().getRect()==(100,12,97,21)
    assert dialog.findChild(QPushButton,'OK').geometry().getRect()==(192,418,81,25)
    assert dialog.controls['TemperatureCombo'].isEnabled()
    assert not dialog.controls['FrequencyCombo'].isEnabled()
    dialog.dimension.setCurrentIndex(dialog.dimension.findData('ppm'));dialog.save();dialog.reject()
    assert curve.unit_options is None and not ui.dirty and ui.plot_options==before
    assert load_defaults('units')['options']['unit_defaults']==dict(options('ppm'),time='min',temperature='°C')
    dialog=ui.show_units();dialog.dimension.setCurrentIndex(dialog.dimension.findData('mm'));dialog.defaults()
    assert dialog.dimension.currentData()=='µm' and dialog.offset.currentData()=='none';dialog.reject()
    second=source(tmp_path/'new.001');ui.finish_import([second],[])
    assert ui.selected().unit_options==dict(options('ppm'),time='min',temperature='°C')


def test_normal_unit_change_preserves_canonical_buffers_removes_only_own_results_and_keeps_file(ui,tmp_path):
    imported(ui,tmp_path,3);ui.show_normal();curve=ui.selected();doc=ui.active_document();curve.sample_size_mm=2.
    curve.working=curve.dataset.values[:,2]*2;curve.operations=['QA scaling'];working=curve.working
    own=ui.start_point_measurement('signal_max');ui.confirm_measurement()
    ui.files.setCurrentItem(ui.files.topLevelItem(0));other=ui.start_point_measurement('signal_max');ui.confirm_measurement();ui.files.setCurrentItem(ui.files.topLevelItem(2))
    dialog=ui.show_units();dialog.dimension.setCurrentIndex(dialog.dimension.findData('mm'));dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted and ui.results==[other]
    assert curve.working is working and curve.operations==['QA scaling'] and ui.curves[0].unit_options is None
    assert ui.selected().uid==curve.uid and ui.active_document() is doc and curve.result_unit=='mm'
    np.testing.assert_allclose(curve.xy()[1],working*.001)


def test_shared_source_change_reconciles_other_overlays_instead_of_hiding_mixed_units(ui,tmp_path):
    imported(ui,tmp_path,3);overlay=ui.active_document();curve=ui.selected();ui.show_normal();doc=ui.active_document()
    dialog=ui.show_units();dialog.dimension.setCurrentIndex(dialog.dimension.findData('mm'));dialog.accept()
    ui._show_document(overlay.key)
    assert len(ui._plot_artists)==3 and {c.result_unit for c,x,y in ui._plot_artists}=={'µm','mm'}
    assert len({c.axis for c,x,y in ui._plot_artists})==2
    session=tmp_path/'mixed.tmas';save_session(session,ui.curves,ui.domain,ui.results,ui.plot_options)
    ui.close_all_documents();ui.restore_session(session);ui._show_document(overlay.key)
    assert len(ui._plot_artists)==3


def test_overlay_normalization_uses_each_size_and_separates_zero_size_fallback(ui,tmp_path):
    imported(ui,tmp_path,3);ui.curves[0].sample_size_mm=1.;ui.curves[1].sample_size_mm=2.;ui.curves[2].sample_size_mm=0
    dialog=ui.show_units();dialog.dimension.setCurrentIndex(dialog.dimension.findData('%'));dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted and len(ui._plot_artists)==3
    assert [c.result_unit for c in ui.curves]==['%','%','µm'] and ui.curves[0].axis==ui.curves[1].axis!=ui.curves[2].axis
    np.testing.assert_allclose(ui.curves[0].xy()[1],ui.curves[0].dataset.values[:,2]*.1)
    np.testing.assert_allclose(ui.curves[1].xy()[1],ui.curves[1].dataset.values[:,2]*.05)


def test_unit_change_draft_is_cancelled_and_other_document_cannot_commit(ui,tmp_path):
    imported(ui,tmp_path,3);ui.show_normal();curve=ui.selected();doc=ui.active_document()
    entry=ui.start_point_measurement('signal_max');dialog=ui.show_units();dialog.dimension.setCurrentIndex(dialog.dimension.findData('mm'))
    other=next(v for k,v in ui.documents.items() if k!=doc.key and not ui._is_overlay(k));ui.mdi.setActiveSubWindow(other);ui.document_activated(other);dialog.accept()
    assert dialog.result()!=QDialog.DialogCode.Accepted and dialog.error.text() and curve.unit_options is None and ui._pending_measurement is entry
    ui.mdi.setActiveSubWindow(doc);ui.document_activated(doc);dialog.accept();assert ui._pending_measurement is None and curve.unit_options==options('mm')


def test_normalized_alpha_and_size_snapshot_survive_later_missing_size_resolution(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.selected();curve.sample_size_mm=2.;curve.unit_options=options('%');ui.redraw()
    entry=ui.start_alpha('alpha_fit');ui.confirm_measurement()
    assert entry['values']['alpha']==pytest.approx(entry['values']['slope']*10000)
    saved=deepcopy(entry);curve.sample_size_mm=3.;ui.redraw()
    assert not ui._measurement_artists and ui.results==[saved]
    session=tmp_path/'old-reference.tmas';save_session(session,ui.curves,ui.domain,ui.results,ui.plot_options)
    assert load_session(session)[2]==[saved]


def test_y_offset_widgets_use_display_unit_and_keep_canonical_saved_values(ui,tmp_path):
    imported(ui,tmp_path,2);curve=ui.selected();curve.unit_options=options('mm');curve.offset=12;ui.selection_changed()
    assert ui.offset_box.value()==.012
    ui.offset_box.setValue(.02);assert curve.offset==pytest.approx(20)
    dialog=ui.show_overlay_options();dialog.axis_group.buttons()[curve.axis].click()
    curves=dialog.axis_curves();position=next(i for i,c in enumerate(curves) if c.uid==curve.uid)
    field=dialog.table.cellWidget(position,4)
    # Curves page columns: 0 index,1 line,2 symbol,3 color,4 Y offset.
    field.setValue(.03);assert next(c for c in dialog.draft if c.uid==curve.uid).overlay_offset==pytest.approx(30)
    dialog.reject()


def test_missing_size_prompt_reconciles_fallback_axis_without_hiding_neighbors(ui,tmp_path):
    imported(ui,tmp_path,4);ui.curves[0].sample_size_mm=1.
    dialog=ui.show_units();dialog.dimension.setCurrentIndex(dialog.dimension.findData('%'));dialog.accept()
    curve=ui.selected();assert curve.result_unit=='µm' and len(ui._plot_artists)==4
    ui.start_alpha('alpha_fit');size=ui.dialogs['sample_size'];size.field.setText('2');size.accept()
    assert size.result()==QDialog.DialogCode.Accepted and curve.result_unit=='%'
    assert len(ui._plot_artists)==4 and curve.axis==ui.curves[0].axis
    assert ui._pending_measurement['kind']=='alpha_fit'


def test_signal_smoothing_width_scales_with_dimension_units_but_buffer_stays_canonical(ui,tmp_path):
    from tma_app.data_limits import smoothed_state
    imported(ui,tmp_path,1);curve=ui.selected();curve.x_signal_index=2
    for key,value in smoothed_state(curve,'signal',8.).items():setattr(curve,key,value)
    working=curve.working.copy()
    dialog=ui.show_units();dialog.dimension.setCurrentIndex(dialog.dimension.findData('mm'));dialog.accept()
    assert curve.smooth_width==pytest.approx(.008)
    np.testing.assert_array_equal(curve.working,working)
    assert curve.operations[-1].startswith('ls_smooth:0.008:Dimension Change (mm)')


def test_dimension_x_generic_derivative_uses_canonical_variable_and_valid_display_units(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.selected();curve.dataset.values[:,2]=np.arange(7,dtype=float)*2+1
    curve.x_signal_index=2;curve.unit_options=options('mm');ui.domain_box.setCurrentIndex(2)
    ui.process('derivative');assert curve.operations==['derivative:Dimension Change (µm)']
    np.testing.assert_allclose(curve.xy('signal')[1],1)
    assert curve.result_unit=='(mm)/(mm)'


def test_mm_source_to_normalized_units_uses_mm_reference_exactly_once(tmp_path):
    from tma_app.reader import Signal
    dataset=source(tmp_path/'mm-source.001');dataset.signals[2]=Signal('Dimension Change','mm');dataset.values[:,2]/=1000
    c=Curve(dataset,sample_size_mm=2.,unit_options=options('µm/m'))
    np.testing.assert_allclose(c.xy()[1],dataset.values[:,2]*500000)


def test_large_right_axis_ticks_and_titles_do_not_intersect_secondary_spine(ui,tmp_path):
    imported(ui,tmp_path,3);ui.resize(1920,1017)
    for index,curve in enumerate(ui.curves):curve.axis=index;curve.unit_options=options('µm/m')
    ui.curves[0].sample_size_mm=2.;ui.curves[0].operations=['derivative:Time (min)'];ui.curves[0].working=np.arange(7,dtype=float)
    ui.curves[1].sample_size_mm=.000001;ui.curves[2].sample_size_mm=0
    ui.redraw();ui.canvas.draw();renderer=ui.canvas.get_renderer();base=ui.axes[0]
    label=ui.axes[1].yaxis.label.get_window_extent(renderer)
    position=ui.axes[2].spines['right'].get_position()[1];spine_x=base.bbox.x0+base.bbox.width*position
    assert label.x1+4<spine_x
    assert ui.axes[2].yaxis.label.get_window_extent(renderer).x1<ui.figure.bbox.x1


def test_legacy_cte_uses_displayed_mm_slope_with_correct_normalization(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.selected();curve.dataset.values[:,2]=np.arange(7,dtype=float)*2
    curve.unit_options=options('mm');ui.analysis_box.setCurrentIndex(ui.analysis_box.findData('cte'));ui.length_box.setValue(2)
    ui.run_analysis(bounds=(100,106));entry=ui.results[-1]
    assert entry['values']['slope']==pytest.approx(.002) and entry['values']['cte_ppm_per_k']==pytest.approx(1000)


def test_dimension_x_spacing_converts_with_display_coordinate_units(ui,tmp_path):
    imported(ui,tmp_path,3)
    for curve in ui.curves:curve.x_signal_index=2
    ui.domain_box.setCurrentIndex(2);key=ui.active_document().key;ui.plot_options[key]['axis_x_offsets'][0]=8.;ui.redraw()
    before=[x+ui.display_x_offset(c) for c,x,y in ui._plot_artists]
    dialog=ui.show_units();dialog.dimension.setCurrentIndex(dialog.dimension.findData('mm'));dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted and ui.plot_options[key]['axis_x_offsets'][0]==pytest.approx(.008)
    for (curve,x,y),expected in zip(ui._plot_artists,before):np.testing.assert_allclose(x+ui.display_x_offset(curve),expected*.001)


def test_mixed_normalized_dimension_x_is_rejected_atomically(ui,tmp_path):
    imported(ui,tmp_path,2)
    for curve in ui.curves:curve.x_signal_index=2
    ui.curves[0].sample_size_mm=2.;ui.domain_box.setCurrentIndex(2);before=deepcopy(ui.plot_options)
    dialog=ui.show_units();dialog.dimension.setCurrentIndex(dialog.dimension.findData('%'));dialog.accept()
    assert dialog.result()!=QDialog.DialogCode.Accepted and dialog.error.text()
    assert all(c.unit_options is None for c in ui.curves) and ui.plot_options==before


def test_style_change_does_not_round_away_small_physical_offsets(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.selected();curve.unit_options=options('mm');curve.x_signal_index=2
    curve.offset=.0005;curve.x_shift=.0005;ui.domain_box.setCurrentIndex(2);ui.selection_changed()
    assert ui.offset_box.value()==pytest.approx(.0000005) and ui.xshift_box.value()==pytest.approx(.0000005)
    ui.style_box.setCurrentIndex(ui.style_box.findData('--'))
    assert curve.offset==.0005 and curve.x_shift==.0005 and curve.style=='--'


def test_inherited_signal_domain_resets_manual_x_limits_after_conversion(ui,tmp_path):
    imported(ui,tmp_path,2)
    for curve in ui.curves:curve.x_signal_index=2
    ui.domain_box.setCurrentIndex(2);options_live=ui.plot_options[ui.active_document().key]
    options_live.update(x_domain=None,auto_x=False,x_limits=[-10.,10.])
    dialog=ui.show_units();dialog.dimension.setCurrentIndex(dialog.dimension.findData('mm'));dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted
    current=ui.plot_options[ui.active_document().key]
    assert current['auto_x'] and current['x_limits'] is None


def test_required_size_updates_automatic_range_when_normalized_unit_activates(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.selected();curve.unit_options=options('%');ui.redraw();old_upper=ui.axes[0].get_ylim()[1]
    ui.start_alpha('alpha_fit');dialog=ui.dialogs['sample_size'];dialog.field.setText('2');dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted and curve.result_unit=='%'
    assert ui.axes[0].get_ylim()[1]<old_upper/10


@pytest.mark.parametrize('bad',[{'dimension':'kg','offset':'none'},{'dimension':'µm','offset':False},{'dimension':'µm'}])
def test_strict_unit_configuration(bad):
    with pytest.raises(ValueError):validate(bad)
