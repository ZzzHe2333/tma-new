"""Independent actual-file OLS and native slope/delete workflows."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dataclasses import replace
import hashlib,json
import numpy as np
from PySide6.QtWidgets import QApplication
from tma_app import __version__
from tma_app.reader import read_dataset
from tma_app.workspace import Curve
from tma_app.slope import values,validate_snapshot
from tma_app.classic import CLASSIC_STYLE
from tma_app.running_integral_qa import verify_routes


def main():
    root=Path(__file__).resolve().parents[1];out=root/'artifacts/native-slope-verification';out.mkdir(parents=True,exist_ok=True)
    paths=sorted((root/'测试文件').glob('*.001'));hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    datasets=[];comparisons=[]
    for path in paths:
        ds=read_dataset(path);datasets.append(ds);curve=Curve(ds);positions=[.25,len(ds.values)-1.25];checks=[]
        for candidate,domain in ((curve,'temperature'),(curve,'time'),(replace(curve,unit_options=dict(dimension='mm',offset='none',time='sec',temperature='°F')),'temperature')):
            x,y=candidate.xy(domain);p=np.r_[positions[0],np.arange(1,len(x)-1),positions[1]]
            xx=np.interp(p,np.arange(len(x)),x);yy=np.interp(p,np.arange(len(x)),y)
            m,b=np.polyfit(xx,yy,1);v=values(candidate,dict(kind='slope',domain=domain),positions)
            assert np.isclose(m,v['slope'],rtol=1e-11,atol=1e-12) and np.isclose(b,v['intercept'],rtol=1e-11,atol=1e-10)
            np.testing.assert_array_equal(v['fit_profile']['x'],xx);np.testing.assert_array_equal(v['fit_profile']['y'],yy)
            validate_snapshot(v,len(x),positions);checks.append(dict(domain=domain,unit=v['slope_unit'],slope=v['slope'],r2=v['r2']))
        comparisons.append(dict(file=path.name,independent_fits=checks))
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(CLASSIC_STYLE)
    routes=verify_routes(datasets[:3],app,out/'real-native.json')
    assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report=dict(status='passed',version=__version__,real_files=len(paths),comparisons=comparisons,native_routes=routes,
                all_source_sha256_unchanged=True,source_sha256=hashes,native_average_formula='not specified by installed help; OLS equivalence unverified')
    (out/'slope-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='source_sha256'},ensure_ascii=True,indent=2))


if __name__=='__main__':main()
