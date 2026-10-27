"""Core fast paths must retain exact values, strict parsing and owned arrays."""
from dataclasses import replace
import math
import re
from pathlib import Path
import threading

import numpy as np
import pytest

from tma_app import reader
from tma_app.reader import Dataset,Signal,ParseError
from tma_app.signal_processing import local_fit,typed_signal
from tma_app.workspace import Curve


def reference_fit(x,y,width,derivative):
    """Frozen 1.1.2 neighborhood search and least-squares operation order."""
    x,y=np.asarray(x,dtype=float),np.asarray(y,dtype=float)
    output=np.empty(len(x));degree=max(1,derivative)
    for i in range(len(x)):
        left,right=i,i+1
        while left>0 and abs(x[left-1]-x[i])<=width/2:left-=1
        while right<len(x) and abs(x[right]-x[i])<=width/2:right+=1
        while right-left<5:
            if left and (right==len(x) or abs(x[left-1]-x[i])<=abs(x[right]-x[i])):left-=1
            else:right+=1
        z=x[left:right]-x[i];span=float(np.max(np.abs(z)))
        if not math.isfinite(span) or span==0:raise ValueError(f'第{i+1}点附近自变量恒定，无法拟合；可改用时间导数')
        design=np.polynomial.polynomial.polyvander(z/span,degree)
        baseline=y[i];response=y[left:right]-baseline
        coefficients,_,rank,_=np.linalg.lstsq(design,response,rcond=None)
        if rank!=degree+1:raise ValueError(f'第{i+1}点附近拟合退化')
        output[i]=coefficients[derivative]*math.factorial(derivative)/np.float64(span)**derivative+(baseline if derivative==0 else 0.)
    return output


@pytest.mark.parametrize('mode',['up','down','holds','reversal','ties'])
@pytest.mark.parametrize('derivative',[0,1,2])
@pytest.mark.parametrize('width',[.5,7.,1000.])
def test_monotonic_window_scan_is_bitwise_identical_to_original(mode,derivative,width):
    rng=np.random.default_rng(157)
    x=np.cumsum(rng.uniform(.1,.4,87))
    if mode=='down':x=x[::-1]
    elif mode=='holds':x[20:24]=x[19]
    elif mode=='reversal':x[45:]=x[44]-np.arange(1,43)*.2
    elif mode=='ties':x=np.arange(87,dtype=float)/4
    y=1e5+np.sin(x)*17+x*x*.1
    try:b=reference_fit(x,y,width,derivative)
    except ValueError as exc:
        with pytest.raises(ValueError,match=re.escape(str(exc))):local_fit(x,y,width,derivative)
        return
    a=local_fit(x,y,width,derivative)
    np.testing.assert_array_equal(a.view('u8'),b.view('u8'))


@pytest.mark.parametrize('derivative',[0,1,2])
def test_window_boundary_rounding_retains_original_inclusive_ties(derivative):
    x=1e12+np.arange(35)*.125
    x[8]=np.nextafter(x[8],np.inf);x[21]=np.nextafter(x[21],-np.inf)
    y=np.sin(np.arange(35))*3
    for values in (x,x[::-1]):
        np.testing.assert_array_equal(local_fit(values,y,.75,derivative),reference_fit(values,y,.75,derivative))


HEADER='Nsig 3\nSig1 Time (min)\nSig2 Temperature (°C)\nSig3 Dimension Change (µm)\nStartOfData\n'


@pytest.mark.parametrize('mode',['clean','D','underscores','nan','overflow','columns','hash_comment','garbage','end','unicode'])
def test_bulk_text_matches_original_prefix_values_metadata_and_warnings(mode,monkeypatch):
    rows=[f'{i} {60+i/100:.17g} {math.sin(i/20):.17g}' for i in range(1700)]
    if mode=='D':rows=[row.replace(' ', 'D+00 ',1) for row in rows]
    elif mode=='underscores':rows[700]='7_00 67 1'
    elif mode=='nan':rows[700]='700 67 nan'
    elif mode=='overflow':rows[700]='700 67 1e309'
    elif mode=='columns':rows[700]='700 67 1 42'
    elif mode=='hash_comment':rows[700]='700 67 1 # ignore?'
    elif mode=='garbage':rows[700]='garbage'
    elif mode=='end':rows[700]=' eNDoFdAtA ';rows[701]='garbage'
    elif mode=='unicode':rows[700]='700\u200367\u20031';rows[702]='７０２ ６７ １'
    data=(HEADER+'\n'.join(rows)).encode('utf-8')
    actual=reader._read_text(data,'utf-8')
    def slow(*args,**kwargs):raise ValueError('force original line parser')
    monkeypatch.setattr(reader.np,'loadtxt',slow)
    expected=reader._read_text(data,'utf-8')
    np.testing.assert_array_equal(actual[1].view('u8'),expected[1].view('u8'))
    assert actual[0]==expected[0] and actual[2:]==expected[2:]


@pytest.mark.parametrize('encoding',['utf-8-sig','utf-16','utf-16le','utf-16be'])
def test_large_text_decimal_rounding_signed_zero_and_encodings_exact(encoding):
    rng=np.random.default_rng(11)
    values=rng.uniform(-1,1,(1800,3))*np.power(10.,rng.integers(-300,300,(1800,3)))
    values[:3,0]=[0.,-0.,np.nextafter(0.,1.)]
    rows=[' '.join(format(v,'.17g') for v in row) for row in values]
    text=HEADER+'\n'.join(rows)
    signals,actual,metadata,warnings=reader._read_text(text.encode(encoding),encoding)
    expected=np.array([[float(v) for v in row.split()] for row in rows])
    np.testing.assert_array_equal(actual.view('u8'),expected.view('u8'))


@pytest.mark.parametrize('bad',['NaN','1e999','bad','#comment','0 1 2 3'])
def test_bulk_invalid_first_row_stays_rejected(bad):
    body=bad+'\n'+'0 60 1\n'*2000
    with pytest.raises(ParseError,match='数据无效'):reader._read_text((HEADER+body).encode(),'utf-8')


def curve_fixture():
    x=np.arange(80,dtype=float)
    ds=Dataset(Path('fixture.001'),[Signal('Time','min'),Signal('Temperature','°C'),Signal('Dimension Change','µm')],np.column_stack((x,x+60,x*x)),{},[],'fixture')
    return Curve(ds,x_signal_index=2)


@pytest.mark.parametrize('selected',[None,list(range(4,40)),[2,3,9,10,20,21]])
def test_all_curve_outputs_remain_independent_of_raw_working_and_other_calls(selected):
    c=curve_fixture();c.data_indices=selected;c.working=c.base_y.copy()+3
    raw=c.dataset.values.copy();working=c.working.copy();rows=c.active_rows
    for domain in ('temperature','time','signal'):
        for canonical in (False,True):
            value=c.x_values(domain,canonical=canonical)
            np.testing.assert_array_equal(value,(raw[:,2] if domain=='signal' else raw[:,1] if domain=='temperature' else raw[:,0])[rows])
            value[:]=999
        x,y=c.xy(domain);x[:]=999;y[:]=999
        np.testing.assert_array_equal(c.dataset.values,raw);np.testing.assert_array_equal(c.working,working)


def test_normal_signal_reads_current_values_and_filtered_derivative_cache_tracks_mutable_limits():
    c=curve_fixture();before=c.x_values('signal');c.dataset.values[0,2]=123
    assert c.x_values('signal')[0]==123 and before[0]==0
    c.x_signal_type='d_time';c.x_smooth_width=3;c.data_indices=list(range(3,35))
    first=c.x_values('signal');c.data_indices[:]=range(10,42)
    second=c.x_values('signal',canonical=True)
    expected=typed_signal(replace(c.dataset,values=c.dataset.values[c.data_indices]),2,'d_time',3)
    np.testing.assert_array_equal(second,expected);assert not np.array_equal(first,second)
    full=c.x_values('signal',full=True,canonical=True)
    np.testing.assert_array_equal(full,typed_signal(c.dataset,2,'d_time',3))
    c.x_signal_type='normal';c.x_smooth_width=0;c.x_values('signal')
    c.dataset.values[:,2]+=np.sin(c.dataset.values[:,0])
    c.x_signal_type='d_time';c.x_smooth_width=3
    np.testing.assert_array_equal(c.x_values('signal',full=True,canonical=True),typed_signal(c.dataset,2,'d_time',3))


@pytest.mark.parametrize('hit',[False,True])
def test_large_clone_does_not_hold_global_reader_lock(tmp_path,monkeypatch,hit):
    a=tmp_path/'a.001';b=tmp_path/'b.001'
    for p in (a,b):p.write_text(HEADER+'0 60 1\n1 61 2\n',encoding='utf-8')
    reader.read_dataset(b)
    if hit:reader.read_dataset(a)
    entered=threading.Event();release=threading.Event();done=threading.Event();errors=[]
    original=reader.deepcopy
    def clone(value):
        if threading.current_thread().name=='held-clone':entered.set();release.wait(5)
        return original(value)
    monkeypatch.setattr(reader,'deepcopy',clone)
    def read(path,finished=None):
        try:reader.read_dataset(path)
        except Exception as exc:errors.append(exc)
        finally:
            if finished is not None:finished.set()
    first=threading.Thread(target=read,args=(a,),name='held-clone');second=threading.Thread(target=read,args=(b,done))
    try:
        first.start();assert entered.wait(2);second.start()
        assert done.wait(2),'Unrelated cached reader blocked behind array clone'
    finally:
        release.set();first.join(5)
        if second.ident is not None:second.join(5)
    assert not errors and not first.is_alive() and not second.is_alive()
