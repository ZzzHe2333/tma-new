"""Multi-curve robustness audit; source files are read-only, no algorithm tuning."""
from pathlib import Path
import hashlib, json, math, sys, time
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import matplotlib
matplotlib.use('Agg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from tma_app.reader import read_dataset
from tma_app.frequency_watermark import embed, detect


def audit(out):
    out.mkdir(parents=True,exist_ok=False)
    samples=[]; failures=[]; raw_hashes={}
    for path in sorted((ROOT/'测试文件').iterdir()):
        if path.suffix not in ('.001','.007'): continue
        raw_hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            ds=read_dataset(path)
            ti=ds.temperature_index
            yi=next((i for i,s in enumerate(ds.signals) if 'dimension' in s.name.lower()),2)
            if ti is None: raise ValueError('No temperature channel')
            samples.append((path.stem,ds.values[:,ti],ds.values[:,yi],'real',str(path)))
        except Exception as error: failures.append(dict(file=str(path),error=str(error)))
    # Synthetic curves are declared, never counted as independent physical samples.
    for index in range(max(8,30-len(samples))):
        x=np.linspace(30,300,2400)
        y=sum((30+index*170)/(peak+1)*np.exp(-((x-(100+peak*55+index*3))/(7+index*2))**2)
              for peak in range(1+index%4))-.05*x
        samples.append((f'synthetic-{index+1:02d}',x,y,'synthetic',''))
    sizes=[(1000,650),(1600,900),(2400,1400),(1280,960),(1800,1100)]
    results=[];manifest=[]
    started=time.monotonic()
    def check(sample,variant,image,path):
        image.save(path)
        begin=time.monotonic();value=detect(image)
        results.append(dict(sample=sample,variant=variant,file=str(path.relative_to(out)),
                            size=image.size,seconds=time.monotonic()-begin,**value))
    for index,(name,x,y,kind,source) in enumerate(samples):
        directory=out/f'{index+1:02d}'
        directory.mkdir()
        width,height=sizes[index%len(sizes)]
        figure=Figure(figsize=(width/100,height/100),dpi=100,facecolor='white')
        FigureCanvasAgg(figure)
        axis=figure.add_subplot()
        axis.plot(x,y,color='black',linewidth=.8)
        axis.set_xlabel('Temperature (C)');axis.set_ylabel('Dimension change (um)')
        span=max(float(np.nanmax(y)-np.nanmin(y)),1.)
        # Different vertical headroom, including intentionally sparse white plots.
        axis.set_ylim(float(np.nanmin(y))-.1*span,float(np.nanmax(y))+span*(.2 if index%3 else 3))
        figure.text(.02,.98,f'Sample {index+1:02d}',va='top')
        figure.savefig(directory/'unmarked.png');figure.clear()
        image=Image.open(directory/'unmarked.png').convert('RGB')
        white_fraction=float(np.mean(np.all(np.asarray(image)>245,axis=2)))
        marked=embed(image)
        difference=np.asarray(marked,dtype=float)-np.asarray(image,dtype=float)
        manifest.append(dict(id=index+1,name=name,kind=kind,source=source,size=image.size,
                             peak_height=float(np.nanmax(y)),white_fraction=white_fraction,
                             pixel_rmse=float(np.sqrt(np.mean(difference**2)))))
        check(index+1,'unmarked',image,directory/'negative.png')
        check(index+1,'original',marked,directory/'marked.png')
        for ratio in (.05,.10,.15,.20):
            box=(round(width*ratio),round(height*ratio),round(width*(1-ratio)),round(height*(1-ratio)))
            check(index+1,f'crop_each_edge_{int(ratio*100)}pct',marked.crop(box),directory/f'crop-{int(ratio*100)}.png')
        for label,keep in [('central_50pct_dimensions',.5),('central_50pct_area',math.sqrt(.5))]:
            margin=(1-keep)/2
            check(index+1,label,marked.crop((round(width*margin),round(height*margin),round(width*(1-margin)),round(height*(1-margin)))),directory/(label+'.png'))
        summary={variant:dict(total=sum(r['variant']==variant for r in results),
                    detected=sum(r['variant']==variant and r['detected'] for r in results),
                    complete=sum(r['variant']==variant and r['score']==1 for r in results))
                    for variant in sorted({r['variant'] for r in results})}
        report=dict(samples=manifest,source_failures=failures,results=results,summary=summary,
                    real_samples=sum(s['kind']=='real' for s in manifest),synthetic_samples=sum(s['kind']=='synthetic' for s in manifest),
                    elapsed_seconds=time.monotonic()-started,source_sha256=raw_hashes,
                    crop_definition='each edge removed by named percent; central area and dimensions tested separately')
        (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(index+1,len(samples),kind,summary,flush=True)
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest for path,digest in raw_hashes.items())
    return report


if __name__=='__main__':audit(Path(sys.argv[1]))
