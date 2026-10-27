"""Frozen core comparison against arrays captured from the prior release."""
from pathlib import Path
import hashlib
import json
import threading
import time
import traceback

import numpy as np
from PySide6.QtWidgets import QApplication

from . import __version__,reader
from .workspace import Curve
from .signal_processing import local_fit


def verify(window,output,baseline,paths):
    output.parent.mkdir(parents=True,exist_ok=True)
    report={'status':'failed','version':__version__,'checks':[],'timings':{}}
    originals={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    release=threading.Event();old_copy=reader.deepcopy;threads=[]
    def exact(name,action,expected):
        start=time.perf_counter();actual=np.asarray(action())
        report['timings'][name]=time.perf_counter()-start
        np.testing.assert_array_equal(actual.view('u8'),expected[name].view('u8'))
        report['checks'].append(name+'_bitwise_equal_to_1_1_2')
    try:
        count=100000;t=np.arange(count,dtype=float)
        values=np.column_stack((t/60,60+t/1000,np.sin(t/1000)*100,.06+0*t,50+0*t))
        header='Module TMA Standard\nNsig 5\nSig1 Time (min)\nSig2 Temperature (°C)\nSig3 Dimension Change (µm)\nSig4 Force (N)\nSig5 Sample Purge Flow (mL/min)\nStartOfData\n'
        text=header+'\n'.join(' '.join(format(v,'.17g') for v in row) for row in values)
        ds=reader.Dataset(output.parent/'synthetic.001',[reader.Signal('Time','min'),reader.Signal('Temperature','°C'),reader.Signal('Dimension Change','µm'),reader.Signal('Force','N'),reader.Signal('Sample Purge Flow','mL/min')],values,{},[],'fixture')
        curve=Curve(ds,x_signal_index=2)
        x=np.linspace(20.,300.,6000);y=4*np.sin(x/40)+.02*x*x
        with np.load(baseline,allow_pickle=False) as expected:
            exact('text_100k',lambda:reader._read_text(text.encode('utf-8'),'utf-8')[1],expected)
            exact('signal_x_100k_30_reads',lambda:np.vstack([curve.x_values('signal') for _ in range(30)]),expected)
            exact('fit_6000_wide',lambda:local_fit(x,y,120,1),expected)
            exact('fit_6000_narrow',lambda:local_fit(x,y,1,1),expected)
            exact('real_cold_read',lambda:np.array([np.sum(reader.read_dataset(p).values) for p in paths]),expected)
        assert len(paths)>=2
        for p in paths[:2]:reader.read_dataset(p)
        entered=threading.Event();done=threading.Event();errors=[]
        def copy(value):
            if threading.current_thread().name=='qa-held-copy':entered.set();release.wait(5)
            return old_copy(value)
        def read(p,finished=None):
            try:reader.read_dataset(p)
            except Exception as exc:errors.append(str(exc))
            finally:
                if finished is not None:finished.set()
        reader.deepcopy=copy
        first=threading.Thread(target=read,args=(paths[0],),name='qa-held-copy',daemon=True);threads.append(first)
        first.start();assert entered.wait(3)
        second=threading.Thread(target=read,args=(paths[1],done),daemon=True);threads.append(second)
        second.start();assert done.wait(2),'Other reader blocked behind cached array copy'
        release.set()
        for thread in threads:thread.join(2)
        assert not errors and not any(thread.is_alive() for thread in threads)
        report['checks'].append('unrelated_reader_continues_while_large_clone_is_blocked')
        assert originals=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        report['source_files_unchanged']=True;report['source_sha256']=originals;report['status']='passed'
    except Exception:report['error']=traceback.format_exc()
    finally:
        release.set()
        for thread in threads:thread.join(2)
        reader.deepcopy=old_copy
        window.close();QApplication.processEvents()
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if report['status']!='passed':raise SystemExit(1)
