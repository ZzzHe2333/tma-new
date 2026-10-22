"""Physical unit invariants, independent polynomial fits and native workflows."""
from copy import deepcopy
from dataclasses import replace
import numpy as np
import pytest
from PySide6.QtWidgets import QDialog
from test_feature_ui import ui,imported,source
from tma_app.workspace import Curve,save_session,load_session
from tma_app.dimension_units import affine,validate
from tma_app.data_limits import smoothed_state
from tma_app.reader import Signal


def options(**extra):return dict(dimension='source',offset='none',**extra)


@pytest.mark.parametrize('unit,factor',[('sec',60),('s',60),('min',1),('hr',1/60),('h',1/60),('day',1/1440),('d',1/1440),('ms',60000)])
def test_time_conversions_preserve_raw_and_physical_shift(tmp_path,unit,factor):
    c=Curve(source(tmp_path/'time.001'),unit_options=options(time=unit),x_shift=2)
    raw=c.dataset.values.copy()
    np.testing.assert_allclose(c.xy('time')[0],(np.arange(7)+2)*factor)
    np.testing.assert_array_equal(c.dataset.values,raw)
    assert c.x_unit('time')==unit


@pytest.mark.parametrize('unit,expected',[('°C',[0,100]),('°F',[32,212]),('K',[273.15,373.15])])
def test_absolute_temperature_and_delta_shift_are_distinct(tmp_path,unit,expected):
    ds=source(tmp_path/'temperature.001');ds.values[:2,1]=[0,100]
    c=Curve(ds,unit_options=options(temperature=unit))
    np.testing.assert_allclose(c.x_values()[:2],expected)
    c.x_shift=10
    delta=18 if unit=='°F' else 10
    np.testing.assert_allclose(c.xy()[0][:2],np.array(expected)+delta)
    np.testing.assert_array_equal(c.x_values(canonical=True),ds.values[:,1])


def test_source_kelvin_and_seconds_convert_back_to_celsius_minutes(tmp_path):
    ds=source(tmp_path/'other-units.001');ds.signals[0]=Signal('Time','sec');ds.signals[1]=Signal('Temperature','K')
    ds.values[:,0]*=60;ds.values[:,1]+=273.15
    c=Curve(ds,unit_options=options(time='min',temperature='°C'))
    np.testing.assert_allclose(c.x_values('time'),np.arange(7))
    np.testing.assert_allclose(c.x_values(),np.arange(7)+100)


@pytest.mark.parametrize('kind,factor',[('d_time',1/60),('d2_time',1/3600),('d_temperature',1/1.8),('d2_temperature',1/3.24)])
def test_processed_derivatives_use_source_denominator_exactly_once(tmp_path,kind,factor):
    c=Curve(source(tmp_path/'derivative.001'),y_type=kind,unit_options=options(time='sec',temperature='°F'))
    c.dataset.values[:,2]=3*c.dataset.values[:,0]+2 if kind.startswith('d_') else c.dataset.values[:,0]**2
    state=smoothed_state(c,'temperature',0.)
    for key,value in state.items():setattr(c,key,value)
    canonical=np.full(7,3.) if kind.startswith('d_') else np.full(7,2.)
    np.testing.assert_allclose(c.working,canonical,atol=1e-12)
    np.testing.assert_allclose(c.xy()[1],canonical*factor,atol=1e-12)
    expected='sec' if kind.endswith('time') else '°F'
    assert expected in c.plot_label and expected in c.result_label


def test_signal_x_derivative_has_numerator_and_denominator_scaling(tmp_path):
    c=Curve(source(tmp_path/'typed-x.001'),unit_options=options(time='sec',temperature='°F'),x_signal_index=1,x_signal_type='d_time')
    # Temperature rises1°C/min ->1.8/60°F/sec, without32°F origin.
    np.testing.assert_allclose(c.x_values('signal'),np.full(7,.03),atol=1e-12)
    np.testing.assert_allclose(c.x_values('signal',canonical=True),np.ones(7),atol=1e-12)
    assert c.x_unit_factor('signal')==pytest.approx(.03)


def test_time_reset_precedes_y_and_x_conversion(tmp_path):
    c=Curve(source(tmp_path/'reset.001'),y_index=0,data_indices=[2,3,4,5,6],reset_time=True,unit_options=options(time='sec'))
    x,y=c.xy('time');np.testing.assert_allclose(x,np.arange(5)*60);np.testing.assert_allclose(y,np.arange(5)*60)


def test_general_native_dialog_smoothing_windows_and_file_selection(ui,tmp_path):
    imported(ui,tmp_path,2);ui.show_normal();curve=ui.selected();doc=ui.active_document()
    for key,value in smoothed_state(curve,'temperature',2.).items():setattr(curve,key,value)
    working=curve.working.copy();curve.x_shift=3
    dialog=ui.show_units();assert dialog.controls['GeneralGroup'].isEnabled()
    assert dialog.general['time'].isEnabled() and dialog.general['temperature'].isEnabled()
    # A source-only view shares an open overlay: incompatible X units are atomic.
    dialog.general['temperature'].setCurrentIndex(dialog.general['temperature'].findData('°F'));dialog.accept()
    assert dialog.result()!=QDialog.DialogCode.Accepted and 'X单位' in dialog.error.text()
    assert curve.unit_options is None and curve.smooth_width==2
    dialog.reject();ui.show_overlay();dialog=ui.show_units()
    dialog.general['time'].setCurrentIndex(dialog.general['time'].findData('sec'))
    dialog.general['temperature'].setCurrentIndex(dialog.general['temperature'].findData('°F'));dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted
    assert curve.smooth_width==pytest.approx(3.6) and curve.display_x_shift('temperature')==pytest.approx(5.4)
    np.testing.assert_array_equal(curve.working,working)
    # Recompute in the same physical window: buffer is still the source fit.
    values=smoothed_state(curve,'temperature',3.6)
    np.testing.assert_allclose(values['working'],working)
    ui._show_document(doc.key)
    assert ui.selected().uid==curve.uid


@pytest.mark.parametrize('unit',['°F','K'])
def test_alpha_stays_per_celsius_with_converted_cursor_units(ui,tmp_path,unit):
    imported(ui,tmp_path,1);curve=ui.selected();curve.sample_size_mm=2
    curve.dataset.values[:,2]=2*curve.dataset.values[:,1]+5
    curve.unit_options=options(temperature=unit);ui.redraw()
    for kind in ('alpha_at_x','alpha_secant','alpha_fit'):
        entry=ui.start_alpha(kind);assert entry is not None
        ui.confirm_measurement()
        assert entry['values']['alpha']==pytest.approx(1000)
        assert entry['values']['alpha_unit']=='µm/m/°C'
    text=' '.join(a.annotation.get_text() for a in ui._measurement_artists)
    assert unit in text


def test_limit_dialog_displays_current_units_but_stores_source_bounds(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.selected();curve.unit_options=options(time='sec',temperature='°F');ui.redraw()
    from tma_app.limits_dialog import LimitBoundsDialog
    dialog=LimitBoundsDialog(ui,curve,'temperature')
    dialog.fields['start'].setText('213.8');dialog.fields['stop'].setText('221');dialog.fields['delay'].setText('60')
    dialog.accept();assert dialog.result()==QDialog.DialogCode.Accepted
    curve=ui.selected()
    assert curve.data_limit_spec['start']==pytest.approx(101) and curve.data_limit_spec['stop']==pytest.approx(105)
    assert curve.data_limit_spec['delay']==pytest.approx(1)
    assert curve.active_rows.tolist()==[1,2,3,4,5]
    reopened=LimitBoundsDialog(ui,curve,'temperature');assert float(reopened.fields['start'].text())==pytest.approx(213.8);reopened.reject()
    time=LimitBoundsDialog(ui,curve,'time');time.fields['start'].setText('120');time.fields['stop'].setText('300');time.reset.setChecked(True);time.accept()
    curve=ui.selected()
    assert curve.active_rows.tolist()==[2,3,4,5]
    np.testing.assert_allclose(curve.x_values('time'),[0,60,120,180])


def test_converted_marked_temperature_time_and_session_metadata(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.selected();curve.unit_options=options(time='sec',temperature='K');ui.redraw()
    entry=ui.start_point_measurement('curve_value');ui.confirm_measurement();ui.dialogs['label_point'].accept()
    values=entry['values'];position=entry['interactive'].get('positions',entry['interactive']['indices'])[0]
    assert values['time_at_point']==pytest.approx(position*60)
    assert values['temperature_at_point']==pytest.approx(373.15+position)
    assert values['time_unit']=='sec' and values['temperature_unit']=='K'
    saved=deepcopy(ui.results);path=tmp_path/'general.tmas';save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    restored,domain,results=load_session(path)
    assert results==saved and restored[0].unit_options==curve.unit_options
    np.testing.assert_allclose(restored[0].xy()[0],curve.xy()[0])


def test_units_validation_accepts_old_settings_rejects_unknown_and_wrong_types():
    assert validate({'dimension':'source','offset':'none'})==options()
    for value in (options(time='seconds'),options(temperature='C'),options(time=True),dict(options(),pressure='psi')):
        with pytest.raises(ValueError):validate(value)


def test_general_defaults_only_change_future_imports(ui,tmp_path):
    imported(ui,tmp_path,1);original=ui.selected();dialog=ui.show_units()
    dialog.general['time'].setCurrentIndex(dialog.general['time'].findData('sec'))
    dialog.general['temperature'].setCurrentIndex(dialog.general['temperature'].findData('K'))
    dialog.save();dialog.reject();assert original.unit_options is None
    ui.finish_import([source(tmp_path/'future.002')],[]);new=ui.selected()
    assert new.x_unit('time')=='sec' and new.x_unit('temperature')=='K'
    np.testing.assert_allclose(new.x_values('time'),np.arange(7)*60)
    np.testing.assert_allclose(new.x_values(),np.arange(7)+373.15)


def test_general_units_work_without_tma_dimension(ui,tmp_path):
    ds=source(tmp_path/'no-tma.001');ds.signals=ds.signals[:2];ds.values=ds.values[:,:2].copy()
    ui.finish_import([ds],[]);dialog=ui.show_units()
    assert not dialog.dimension.isEnabled() and dialog.general['temperature'].isEnabled()
    dialog.general['temperature'].setCurrentIndex(dialog.general['temperature'].findData('°F'));dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted and ui.selected().result_unit=='°F'
    np.testing.assert_allclose(ui.selected().xy()[1],1.8*ds.values[:,1]+32)


def test_generic_derivative_records_canonical_temperature_after_conversion(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.selected();curve.unit_options=options(temperature='°F')
    curve.dataset.values[:,2]=3*curve.dataset.values[:,1]+2;ui.redraw();ui.process('derivative')
    assert curve.operations==['derivative:Temperature (°C)']
    np.testing.assert_allclose(curve.working,3)
    np.testing.assert_allclose(curve.xy()[1],3/1.8)


def test_seconds_smoothing_preserves_same_physical_fit_after_recalculation(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.selected();ui.domain_box.setCurrentIndex(1)
    for key,value in smoothed_state(curve,'time',4.).items():setattr(curve,key,value)
    original=curve.working.copy();dialog=ui.show_units()
    dialog.general['time'].setCurrentIndex(dialog.general['time'].findData('sec'));dialog.accept()
    assert curve.smooth_width==pytest.approx(240)
    np.testing.assert_array_equal(curve.working,original)
    fresh=smoothed_state(curve,'time',240)
    np.testing.assert_allclose(fresh['working'],original)


def test_secondary_axis_matches_converted_primary_shift(ui,tmp_path):
    imported(ui,tmp_path,1);curve=ui.selected();curve.unit_options=options(time='sec',temperature='K');curve.x_shift=2
    ui.plot_options[ui.active_document().key]['secondary_x']=True;ui.redraw()
    secondary=next(a for a in ui.figure.axes if a.get_gid()=='tma-secondary-x')
    assert 'sec' in secondary.get_xlabel()
    from tma_app.secondary_axis import corresponding_values
    x=curve.x_values()+curve.display_x_shift('temperature')
    assert corresponding_values(x,curve.x_values('time'),[x[3]],curve.active_rows)==[180.]


def test_unit_transaction_rejects_overflowing_custom_x_width_without_commit(tmp_path):
    from tma_app.dimension_units import processing_state
    original=Curve(source(tmp_path/'wide-x.001'),x_signal_index=2,x_smooth_width=1.2e308)
    candidate=replace(original,unit_options=options(temperature='°F'))
    with pytest.raises(ValueError,match='X信号平滑窗口'):processing_state(original,candidate)
    assert original.unit_options is None and original.x_smooth_width==1.2e308


def test_source_temperature_alias_can_be_saved_in_native_choices(ui,tmp_path):
    ds=source(tmp_path/'alias.001');ds.signals[1]=Signal('Temperature','deg C')
    ui.finish_import([ds],[]);dialog=ui.show_units()
    assert dialog.general['temperature'].currentData()=='°C'
    dialog.save();dialog.reject()
    from tma_app.preferences import load_defaults
    assert load_defaults('units')['options']['unit_defaults']['temperature']=='°C'
