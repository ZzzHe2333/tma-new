"""Native signal types, independent X domains, least squares and extra X ticks."""
from copy import deepcopy
import json
import numpy as np
import pytest
from PySide6.QtWidgets import QDialog, QApplication
from test_feature_ui import ui, imported, set_combo, source
from tma_app.signals_dialog import SignalsDialog
from tma_app.signal_processing import local_fit, typed_signal
from tma_app.secondary_axis import corresponding_values
from tma_app.workspace import save_session, load_session
from tma_app.preferences import load_defaults


def domain(dialog,value):next(b for b in dialog.x_modes.buttons() if b.property("mode")==value).click()


@pytest.mark.parametrize("reverse",[False,True])
def test_local_fits_preserve_linear_signal_and_quadratic_second_derivative(reverse):
    x=np.array([0,.2,.8,1.2,2.,3.,4.5,6.,9.])
    if reverse:x=x[::-1]
    np.testing.assert_allclose(local_fit(x,3*x+5,width=2),3*x+5,atol=1e-12)
    np.testing.assert_allclose(local_fit(x,3*x+5,width=2,derivative=1),3,atol=1e-12)
    np.testing.assert_allclose(local_fit(x,2*x*x-3*x+7,width=.4,derivative=2),4,atol=1e-11)


def test_physical_window_and_five_point_minimum_match_explicit_independent_ols():
    x=np.arange(15,dtype=float);y=x**3
    actual=local_fit(x,y,width=8,derivative=1)
    for i in (0,6,14):
        left,right=max(0,i-4),min(len(x),i+5)
        while right-left<5:
            if left:left-=1
            else:right+=1
        expected=np.linalg.lstsq(np.column_stack((np.ones(right-left),x[left:right]-x[i])),y[left:right],rcond=None)[0][1]
        assert actual[i]==pytest.approx(expected)
    with pytest.raises(ValueError):local_fit(np.ones(8),np.arange(8),derivative=1)
    with pytest.raises(ValueError):local_fit(np.arange(4),np.arange(4),derivative=2)
    np.testing.assert_array_equal(local_fit(np.arange(4),np.arange(4),0),np.arange(4))


def test_signal_dialog_none_and_second_derivative_preserve_raw_sources_and_other_file(ui,tmp_path):
    imported(ui,tmp_path)
    ui.show_normal();target=ui.selected().dataset
    other=[c for c in ui.curves if c.dataset.path!=target.path][0]
    original=target.values.copy();other_state=(other.y_index,other.working,other.normal_enabled)
    dialog=ui.show_native_signals();assert isinstance(dialog,SignalsDialog)
    assert len(dialog.signals)==4 and dialog.types[0].count()==10
    assert not dialog.types[0].model().item(1).isEnabled()
    set_combo(dialog.signals[0],None)
    set_combo(dialog.signals[1],target.signals[2].label);set_combo(dialog.types[1],"d2_time")
    dialog.accept();assert not dialog.error.text()
    assert ui.mdi.activeSubWindow().key==str(target.path)
    assert len(ui.visible_curves())==1 and ui.visible_curves()[0].axis==1
    curve=ui.visible_curves()[0]
    np.testing.assert_allclose(curve.xy(ui.domain)[1],typed_signal(target,2,"d2_time"))
    assert curve.operations.count("derivative:Time (min)")==2
    assert not ui.axes[0].yaxis.get_visible()
    ui.canvas.draw()
    bounds=ui.axes[1].yaxis.label.get_window_extent(ui.canvas.get_renderer())
    assert bounds.x0>=0 and bounds.x1<=ui.figure.bbox.width
    assert bounds.y0>=0 and bounds.y1<=ui.figure.bbox.height
    assert (other.y_index,other.working,other.normal_enabled)==other_state
    np.testing.assert_array_equal(target.values,original)


def test_time_derivative_does_not_change_when_display_x_changes(ui,tmp_path):
    imported(ui,tmp_path,1);ui.show_normal()
    dialog=SignalsDialog(ui);set_combo(dialog.types[0],"d_time");dialog.accept()
    curve=ui.visible_curves()[0];y=curve.xy(ui.domain)[1].copy();unit=curve.result_unit
    ui.domain_box.setCurrentIndex(1)
    assert ui.domain=="time" and curve.result_unit==unit
    np.testing.assert_array_equal(curve.xy("time")[1],y)
    ui.domain_box.setCurrentIndex(0)
    np.testing.assert_array_equal(curve.xy("temperature")[1],y)


def test_custom_x_units_interactive_results_export_and_cross_file_session(ui,tmp_path):
    imported(ui,tmp_path);ui.show_normal();target=ui.selected().dataset
    dialog=SignalsDialog(ui);domain(dialog,"signal")
    set_combo(dialog.x_signal,target.signals[2].label);dialog.accept()
    assert not dialog.error.text() and ui.domain=="signal"
    curve=ui.visible_curves()[0]
    np.testing.assert_array_equal(curve.xy("signal")[0],target.values[:,2])
    assert "尺寸变化" in ui.axes[0].get_xlabel()
    entry=ui.start_point_measurement("signal_max");ui.confirm_measurement()
    assert entry["domain"]=="signal" and entry["transform"]["x_signal"]["index"]==2
    assert "µm" in ui._measurement_artists[0].annotation.get_text()
    other=next(c for c in ui.curves if c.dataset.path!=target.path)
    doc=ui.documents[str(other.dataset.path)];ui.mdi.setActiveSubWindow(doc);ui.document_activated(doc)
    assert ui.domain=="temperature"
    doc=ui.documents[str(target.path)];ui.mdi.setActiveSubWindow(doc);ui.document_activated(doc)
    assert ui.domain=="signal"
    out=tmp_path/"data.csv";ui.write_data(out,curve)
    assert json.loads((tmp_path/"data.csv.meta.json").read_text(encoding="utf-8"))["transform"]["x_signal"]["index"]==2
    path=tmp_path/"signals.tmas";save_session(path,ui.curves,ui.domain,ui.results,ui.plot_options)
    ui.close_all_documents();ui.restore_session(path)
    doc=ui.documents[str(target.path)];ui.mdi.setActiveSubWindow(doc);ui.document_activated(doc)
    assert ui.domain=="signal" and len(ui._measurement_artists)==1


def test_secondary_x_is_additional_axis_with_no_invented_loop_or_hold_times(ui,tmp_path):
    imported(ui,tmp_path,1);ui.show_normal()
    dialog=SignalsDialog(ui);domain(dialog,"time");dialog.show_temperature.setChecked(True);dialog.accept()
    extra=next(ax for ax in ui.figure.axes if ax.get_gid()=="tma-secondary-x")
    assert "温度" in extra.get_xlabel() and len(ui._plot_artists)==1
    ui.axes[0].set_xlim(1,4);ui.canvas.draw()
    assert extra.get_xlim()==pytest.approx((1,4))
    assert corresponding_values([0,1,1,2],[0,5,10,15],[.5,1,1.5])==[2.5,None,12.5]
    assert corresponding_values([0,2,0],[0,2,4],[1])==[None]


def test_cancel_invalid_fit_and_default_save_do_not_partially_mutate_current_graph(ui,tmp_path):
    imported(ui,tmp_path,1);ui.show_normal()
    before=[(c.uid,c.y_index,c.y_type,c.normal_enabled) for c in ui.curves];options=deepcopy(ui.plot_options)
    dialog=SignalsDialog(ui);set_combo(dialog.types[0],"d2_time");dialog.reject()
    assert before==[(c.uid,c.y_index,c.y_type,c.normal_enabled) for c in ui.curves] and options==ui.plot_options
    dialog=SignalsDialog(ui);domain(dialog,"time");dialog.save()
    assert load_defaults("graph")["options"]["signal_defaults"]["x"]["domain"]=="time"
    assert ui.domain=="temperature"
    dialog.defaults();assert dialog.x_modes.checkedButton().property("mode")=="temperature"
    dialog.reject()
    ui.finish_import([source(tmp_path/"new.002")],[])
    assert ui.domain=="time"
    current=ui.selected().dataset;current.values[:,0]=1
    before=[(c.uid,c.y_index,c.y_type,c.normal_enabled) for c in ui.curves]
    dialog=SignalsDialog(ui);set_combo(dialog.types[0],"d_time");dialog.accept()
    assert dialog.result()!=QDialog.DialogCode.Accepted and dialog.error.text()
    assert before==[(c.uid,c.y_index,c.y_type,c.normal_enabled) for c in ui.curves]
