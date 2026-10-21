"""Extract selected WinUA feature forms read-only; do not infer handler behavior."""
from pathlib import Path
import importlib.util,json,hashlib,re
ROOT=Path(__file__).resolve().parents[1]
module=importlib.util.spec_from_file_location('classic_resource_reader',ROOT/'tools/extract_classic_resources.py');m=importlib.util.module_from_spec(module);module.loader.exec_module(m)
OUT=ROOT/'artifacts/feature-reference'
NAMES=['TADDCURVESFORM','TDELETECURVESFORM','TAUTOCONFIGUREFORM','TAUTOPEAKFORM','TAUTOSIGNALCHANGEFORM','TANALYSISOPTIONSFORM','TOVERLAYOPTIONSFORM','TGRAPHOPTIONSFORM','TPLOTOPTIONSFORM','TSIGNALSFORM','TCURSORLIMITSFORM','TDATALIMITSFORM']

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 exe=m.EXE.read_bytes();resources=json.loads((ROOT/'analysis/winua_resources.json').read_text());summary={}
 for name in NAMES:
  record=next(r for r in resources if r['type']==10 and r['name']==name);data=exe[record['offset']:record['offset']+record['size']];r=m.Reader(data);assert r.raw(4)==b'TPF0';tree=r.component();nodes=list(m.walk(tree))
  result={'evidence':'Static Delphi DFM only. Handler names do not prove implementation; runtime labels/state may be changed.','consumed':r.p,'size':len(data),'complete':r.p==len(data),'tree':tree}
  (OUT/f'{name}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
  summary[name]={'complete':result['complete'],'size':len(data),'count':len(nodes),'controls':[{'name':n['name'],'class':n['class'],'props':n['props']} for n in nodes]}
 (OUT/'forms-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
 language={}
 for label in ['ENG','CHS']:
  path=m.EXE.parent/'Language'/f'WinUA_{label}.txt';lines=path.read_text(encoding='utf16').splitlines();language[label]={p[0]:p[1] for line in lines if len(p:=line.split('=',1))==2 and p[0].isdigit()}
 selected={k:{'english':v,'chinese':language['CHS'].get(k)} for k,v in language['ENG'].items() if re.search(r'Signal Max|Signal Change|Peak Max|Peak Top|Overlay|Add Curve|Delete Curve|Automatic Line|Auto Line|X1|X2|Base.*Line|Absolute|Relative|Maximum|Minimum',v,re.I)}
 (OUT/'language-matches.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2),encoding='utf8')
 print([(n,a['count'],a['complete']) for n,a in summary.items()])
 for name in NAMES:
  print('\n',name)
  for n in summary[name]['controls']:
   p=n['props'];pr={k:v for k,v in p.items() if k in ['Caption','Text','Items.Strings','Checked','ItemIndex','MinValue','MaxValue','Min','Max','Value','Columns','ColCount','RowCount','FixedRows','FixedCols','DefaultColWidth','DefaultRowHeight','Visible','Enabled','OnClick','OnDblClick','OnChange','OnMouseDown','OnMouseUp','OnSelectCell']}
   print(n['class'],n['name'],pr)
if __name__=='__main__':main()
