"""Public plot coordinates remain exact and independently owned."""
from pathlib import Path
from copy import deepcopy
import numpy as np
import pytest
from tma_app.reader import Dataset, Signal
from tma_app.workspace import Curve
from tma_app.dimension_units import convert, quantity
from test_feature_ui import ui,source


def previous_xy(curve,domain):
    """Released 1.1.4 expression, before any temporary-buffer reuse."""
    x=curve.x_values(domain)+curve.display_x_shift(domain)
    y=curve.base_y if curve.working is None else curve.working
    y=y.astype(float,copy=True) if curve.data_indices is None else y[curve.active_rows].astype(float,copy=False)
    if curve.derived is None and curve.reset_time and curve.y_index==curve.dataset.time_index and not any(op=='normalize' or op.startswith('derivative:') for op in curve.operations):y-=curve.time_origin
    spec=quantity(curve)
    return x,convert(y,spec)*curve.scale*curve.mass_normalization_factor+curve.offset*spec['factor']


@pytest.mark.parametrize('storage',['float64','float32','int64','strided','readonly'])
@pytest.mark.parametrize('domain',['time','temperature','signal'])
@pytest.mark.parametrize('selection',['full','contiguous','gaps'])
@pytest.mark.parametrize('processing',['normal','derivative','time_reset','mass','normalize'])
def test_coordinates_match_released_expression_bitwise_and_own_outputs(tmp_path,storage,domain,selection,processing):
    t=np.arange(17,dtype=float)
    values=np.column_stack((t,20+t*10,np.sin(t)*30))
    values[0,2]=-0.;values[1,2]=0.
    if storage=='strided':
        container=np.zeros((17,6));container[:,::2]=values;values=container[:,::2]
    elif storage=='readonly':values.flags.writeable=False
    else:values=values.astype(storage)
    ds=Dataset(Path(tmp_path/'source.001'),[Signal('Time','min'),Signal('Temperature','°C'),Signal('Dimension Change','µm')],values,{'Size':['1.25 mm']},[],'fixture')
    curve=Curve(ds,x_signal_index=1,scale=1.125,offset=-.35,x_shift=.125,
                unit_options={'dimension':'%','offset':'at25','time':'s','temperature':'K'})
    if selection!='full':curve.data_indices=list(range(2,15)) if selection=='contiguous' else [0,1,2,7,8,9,14,15,16]
    if processing=='derivative':curve.y_type='d_time';curve.working=np.cos(t);curve.operations=['derivative:Time (min)']
    elif processing=='time_reset':curve.y_index=0;curve.reset_time=True
    elif processing=='mass':curve.appearance_mode='overlay';curve.active_overlay_key='__overlay__::test';curve.mass_normalization_mg=.46
    elif processing=='normalize':curve.working=np.sin(t);curve.operations=['normalize']
    before=values.copy();working=None if curve.working is None else curve.working.copy()
    expected=previous_xy(curve,domain);actual=curve.xy(domain)
    for a,b in zip(actual,expected):
        np.testing.assert_array_equal(a.view('u8'),b.view('u8'))
        assert a.flags.writeable and not np.shares_memory(a,values)
        if curve.working is not None:assert not np.shares_memory(a,curve.working)
    actual[0][0]+=99;actual[1][0]-=99
    np.testing.assert_array_equal(values,before)
    if working is not None:np.testing.assert_array_equal(curve.working,working)


def test_processed_x_cache_is_owned_when_shifts_are_applied(tmp_path):
    t=np.arange(17,dtype=float)
    ds=Dataset(Path(tmp_path/'source.001'),[Signal('Time','min'),Signal('Temperature','°C'),Signal('Dimension Change','µm')],np.column_stack((t,20+t,t*t)),{},[],'fixture')
    curve=Curve(ds,x_signal_index=2,x_signal_type='d_time',x_shift=5)
    first=curve.xy('signal');cache=curve._x_cache[1].copy()
    first[0][:]=999
    np.testing.assert_array_equal(curve._x_cache[1],cache)
    np.testing.assert_array_equal(curve.xy('signal')[0],cache+5)


@pytest.mark.parametrize('field',['scale','offset','x_shift'])
@pytest.mark.parametrize('value',[np.float32(1.13),np.longdouble('1.0000000000000001'),np.complex128(1.2+.3j)])
def test_direct_api_scalar_promotion_matches_previous_expression(tmp_path,field,value):
    curve=Curve(source(tmp_path/'scalar.001'))
    setattr(curve,field,value)
    expected=previous_xy(curve,'temperature');actual=curve.xy('temperature')
    for a,b in zip(actual,expected):
        assert a.dtype==b.dtype
        np.testing.assert_array_equal(a.view('u8'),b.view('u8'))


@pytest.mark.parametrize('rows',[None,[0,1,2,3,4,5,6],[0,1,4,5,6]])
def test_line_vertices_preserve_gaps_and_do_not_alias_plot_buffers(ui,tmp_path,rows):
    ds=source(tmp_path/'line.001');ui.finish_import([ds],[]);ui.show_normal()
    curve=ui.selected();curve.data_indices=deepcopy(rows);curve.x_shift=.3
    ui.redraw()
    _,x,y=ui._plot_artists[0]
    gaps=np.flatnonzero(np.diff(curve.active_rows)!=1)+1
    line=next(line for line in ui.axes[0].lines if getattr(line,'_tma_curve_uid',None)==curve.uid)
    np.testing.assert_array_equal(line.get_xdata(),np.insert(x,gaps,np.nan))
    np.testing.assert_array_equal(line.get_ydata(),np.insert(y,gaps,np.nan))
    assert not np.shares_memory(line.get_ydata(orig=True),y)
    line.get_ydata(orig=True)[0]=12345
    assert y[0]!=12345 and curve.dataset.values[0,2]!=12345
