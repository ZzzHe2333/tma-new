"""Real-data multi-axis rendering, manual scales, exports and stable quantities."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from copy import deepcopy
import hashlib,json,tempfile
import numpy as np
from matplotlib.font_manager import findfont
from PySide6.QtWidgets import QApplication,QDialog
from PySide6.QtTest import QTest
from PIL import Image
from tma_app import __version__,preferences
from tma_app.classic import ClassicMainWindow,CLASSIC_STYLE
from tma_app.workspace import save_session,load_session
from tma_app.reader import read_dataset


def audit(w):
    w.canvas.draw();report={}
    for index,axis in w.axes.items():
        count=0;files=set()
        for coordinate in (axis.xaxis,axis.yaxis):
            for tick in coordinate.get_major_ticks()+coordinate.get_minor_ticks():
                for label in (tick.label1,tick.label2):
                    files.add(findfont(label.get_fontproperties()));count+=1
        if not files or not all(Path(p).name.casefold()=='times.ttf' for p in files):raise ValueError(f'Y{index+1} has fallback tick fonts: {files}')
        report[str(index)]=dict(tick_texts=count,font_files=sorted(files))
    return report


def main():
    root=Path(__file__).resolve().parents[1];out=root/'artifacts/classic-polish-verification';out.mkdir(parents=True,exist_ok=True)
    paths=sorted((root/'测试文件').glob('*.001'))[:3];hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(CLASSIC_STYLE)
    with tempfile.TemporaryDirectory(prefix='tma-classic-fonts-') as private:
        preferences.preferences_path=lambda:Path(private)/'preferences.json'
        w=ClassicMainWindow();w.resize(1920,1017);w.show();w.warn=lambda m:(_ for _ in ()).throw(ValueError(m))
        w.finish_import([read_dataset(p) for p in paths],[]);c=w.curves[1]
        w._show_document(str(c.dataset.path));w.refresh_curve(c.uid)
        w.start_peak_integration();w.confirm_measurement();w.start_running_integral();dialog=w.confirm_measurement();dialog.percent.setChecked(True);dialog.accept()
        derived=w.curves[-1];snapshot=deepcopy(derived.derived);stages={'normal_y4':audit(w)}
        w.grab().save(str(out/'normal-y4.png'))
        w.auto_configure_overlay().accept()
        options=w.show_overlay_options()
        for axis,uid in enumerate([curve.uid for curve in w.curves if curve.derived is None]):
            next(curve for curve in options.draft if curve.uid==uid).axis=axis
        options.populate();options.accept()
        assert options.result()==QDialog.Accepted,options.error.text()
        assert {c.axis for c in w.visible_curves()}=={0,1,2,3}
        before={c.uid:c.xy(w.domain) for c in w.curves};stages['four_axes']=audit(w)
        outer_right=next(c for c in w.curves if c.derived is None and c.axis==2)
        outer_right.visible=False;w.redraw();stages['three_axes']=audit(w)
        assert set(w.axes)=={0,1,3};w.grab().save(str(out/'three-axes.png'))
        outer_right.visible=True;w.redraw()
        rescale=w.manual_rescale(3)
        for axis,values in ((0,[-500,4000,1000,250,0]),(1,[-500,2500,500,125,0]),(2,[-500,4000,1000,250,0]),(3,[0,100,20,5,0]),('x',[50,300,50,12.5,0])):
            for field,value in zip(rescale.fields[axis],values):field.setText(str(value))
        rescale.accept();assert rescale.result()==QDialog.Accepted
        w.redraw();stages['manual_rescale']=audit(w)
        w.resize(1280,800);QTest.qWait(150);w.resize(1920,1017);QTest.qWait(150);stages['resize']=audit(w)
        assert w.grab().save(str(out/'four-axes-manual.png'))
        image=out/(c.dataset.path.stem+'.png');w.write_plot(image);stages['export']=audit(w)
        with Image.open(image) as png:assert png.info['Author']=='Power By ZzzHe' and png.info['Software']=='Power By ZzzHe'
        assert derived.derived==snapshot
        for curve in w.curves:
            for original,current in zip(before[curve.uid],curve.xy(w.domain)):np.testing.assert_array_equal(original,current)
        session=out/'four-axes.tmas';save_session(session,w.curves,w.domain,w.results,w.plot_options)
        restored,_,_,_=load_session(session,include_plot_options=True)
        assert next(d for d in restored if d.uid==derived.uid).derived==snapshot
        key=w.active_document().key
        w.close_all_documents();w.restore_session(session);app.processEvents()
        assert w.active_document().key==key and set(w.axes)=={0,1,2,3}
        stages['gui_session_restore']=audit(w)
        assert next(d for d in w.curves if d.uid==derived.uid).derived==snapshot
        assert w.grab().save(str(out/'restored-four-axes.png'))
        assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        summary=dict(status='passed',version=__version__,stages=stages,real_files=len(paths),source_sha256=hashes,
            derived_snapshot_unchanged=True,all_displayed_coordinates_unchanged=True,session=str(session),export=str(image),credit='Power By ZzzHe')
        (out/'fonts-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({k:v for k,v in summary.items() if k!='source_sha256'},ensure_ascii=True,indent=2))
        w.dirty=False;w.close()


if __name__=='__main__':main()
