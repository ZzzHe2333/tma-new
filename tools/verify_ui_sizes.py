"""Run each UI size in a fresh isolated process (DPI is fixed at startup)."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def verify(executable,output,inputs):
    output.mkdir(parents=True,exist_ok=True);reports=[]
    for key,factor in (('standard',1.),('large',1.25),('extra_large',1.5)):
        profile=output/(key+'-profile')/'ZzzHeTMA';profile.mkdir(parents=True,exist_ok=True)
        (profile/'settings.json').write_text(json.dumps({'paths':{'m':''},'ui':{'size':key,'batch_popup':False}}),encoding='utf-8')
        target=output/(key+'.json')
        env=os.environ.copy();env['LOCALAPPDATA']=str(profile.parent);env['QT_QPA_PLATFORM']='windows'
        for name in ('QT_SCALE_FACTOR','ZZZHE_TMA_BASE_QT_SCALE','ZZZHE_TMA_UI_SIZE_ACTIVE'):env.pop(name,None)
        command=[str(executable)] if executable else [sys.executable,str(ROOT/'run.py')]
        with (output/(key+'.log')).open('wb') as log:
            run=subprocess.run([*command,'--verify-ui-size',str(target),*map(str,inputs)],env=env,stdout=log,stderr=log,timeout=100,cwd=ROOT)
        report=json.loads(target.read_text(encoding='utf-8-sig'))
        assert run.returncode==0 and report['status']=='passed',report
        reports.append(report)
    baseline=reports[0]
    for report,factor in zip(reports,(1,1.25,1.5)):
        assert abs(report['dpr']/baseline['dpr']-factor)<.02
        assert abs(report['button_pixels'][1]/baseline['button_pixels'][1]-factor)<.02
        assert abs(report['font_pixels']/baseline['font_pixels']-factor)<.02
        assert abs(report['toolbar_icon_pixels']/baseline['toolbar_icon_pixels']-factor)<.02
    result={'status':'passed','version':baseline['version'],'presets':reports}
    (output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':'passed','version':baseline['version'],'dpr':[r['dpr'] for r in reports]},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--executable',type=Path)
    parser.add_argument('--output',required=True,type=Path);parser.add_argument('inputs',type=Path,nargs='+')
    args=parser.parse_args();verify(args.executable.resolve() if args.executable else None,args.output.resolve(),[p.resolve() for p in args.inputs])
