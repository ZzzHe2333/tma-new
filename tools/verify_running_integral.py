"""Independent real-file cumulative references plus source/frozen GUI gates."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hashlib,json
import numpy as np
from PySide6.QtWidgets import QApplication
from tma_app import __version__
from tma_app.classic import CLASSIC_STYLE
from tma_app.reader import read_dataset
from tma_app.workspace import Curve
from tma_app.peak_onset import defaults as peak_options
from tma_app.peak_integration import defaults as integration_options,profile
from tma_app.running_integral import calculate
from tma_app.running_integral_qa import verify_routes


def main():
    root=Path(__file__).resolve().parents[1];out=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'artifacts/running-integral-verification';out.mkdir(parents=True,exist_ok=True)
    files=sorted((root/'测试文件').glob('*.001'))
    if not files:raise ValueError('Missing real test files')
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files};comparisons=[];datasets=[]
    for path in files:
        ds=read_dataset(path);datasets.append(ds);curve=Curve(ds)
        e=dict(kind='peak_linear',domain='temperature',peak_onset=peak_options(),integration=integration_options())
        _,_,_,_,x,y,p,t,b,_,_=profile(curve,e,[.25,len(ds.values)-1.25])
        response=y-b;reference=np.r_[0.,np.cumsum((response[:-1]+response[1:])*.5*np.diff(t))]
        for baseline in ('parent','zero'):
            base=b if baseline=='parent' else np.zeros_like(b);r=y-base
            expected=np.r_[0.,np.cumsum((r[:-1]+r[1:])*.5*np.diff(t))]
            for mode in ('integral','percent'):
                for inverted in (False,True):
                    actual=calculate(t,y,base,mode=mode,inverted=inverted)['values']
                    wanted=expected if mode=='integral' else 100*expected/expected[-1]
                    if inverted:wanted=-wanted if mode=='integral' else 100-wanted
                    np.testing.assert_allclose(actual,wanted,rtol=1e-12,atol=1e-10)
        comparisons.append(dict(file=path.name,points=len(p),start_position=float(p[0]),stop_position=float(p[-1]),
                                signed_area=float(reference[-1]),eight_quantity_choices_match=True))
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(CLASSIC_STYLE)
    routes=verify_routes(datasets[:3],app,out/'real-files.json')
    assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    summary=dict(status='passed',version=__version__,real_files=len(files),comparisons=comparisons,native_routes=routes,
                 all_source_sha256_unchanged=True,source_sha256=hashes,original_exact_numeric_equivalence='unverified')
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in summary.items() if k!='source_sha256'},ensure_ascii=True,indent=2))


if __name__=='__main__':main()
