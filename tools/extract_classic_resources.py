"""Read-only extraction of Delphi DFM static UI evidence from installed WinUA."""
from pathlib import Path
import json, struct, hashlib, math, io, re
from PIL import Image, ImageOps, ImageDraw
ROOT=Path(__file__).resolve().parents[1]
EXE=Path(r'C:\Program Files (x86)\TA Instruments\Thermal Advantage\WinUA.exe')
OUT=ROOT/'artifacts'/'classic-reference'

class Reader:
    def __init__(self,data): self.b=data; self.p=0; self.blobs=[]
    def raw(self,n):
        if n<0 or self.p+n>len(self.b): raise ValueError(f'Out of bounds {self.p}+{n}')
        v=self.b[self.p:self.p+n]; self.p+=n; return v
    def unpack(self,fmt): return struct.unpack(fmt,self.raw(struct.calcsize(fmt)))[0]
    def byte(self): return self.unpack('<B')
    def sstr(self): return self.raw(self.byte()).decode('cp1252',errors='replace')
    def value(self):
        t=self.byte()
        if t in (0,13): return None
        if t==1:
            a=[]
            while self.b[self.p]!=0: a.append(self.value())
            self.p+=1; return a
        if t==2: return self.unpack('<b')
        if t==3: return self.unpack('<h')
        if t==4: return self.unpack('<i')
        if t==5:
            b=self.raw(10); sig=int.from_bytes(b[:8],'little'); exp=int.from_bytes(b[8:],'little')
            if exp&0x7fff==0: return 0.0
            return math.ldexp(sig/2**63,(exp&0x7fff)-16383)*(-1 if exp&0x8000 else 1)
        if t in (6,7): return ('#' if t==7 else '')+self.sstr()
        if t in (8,9): return t==9
        if t==10:
            n=self.unpack('<I'); pos=self.p; b=self.raw(n); idx=len(self.blobs); self.blobs.append((pos,b)); return {'binary_index':idx,'size':n,'offset':pos,'sha256':hashlib.sha256(b).hexdigest()}
        if t==11:
            a=[]
            while True:
                s=self.sstr()
                if not s: return a
                a.append(s)
        if t in (12,18,20):
            n=self.unpack('<I'); return self.raw(n*(2 if t==18 else 1)).decode({12:'cp1252',18:'utf-16le',20:'utf-8'}[t],errors='replace')
        if t==14:
            a=[]
            while self.b[self.p]!=0:
                marker=self.byte()
                index=None
                if marker in (2,3,4):
                    self.p-=1; index=self.value(); marker=self.byte()
                if marker!=1: raise ValueError(f'Collection marker {marker} at {self.p-1}')
                props=self.props()
                if index is not None: props['$index']=index
                a.append(props)
            self.p+=1; return a
        if t==15: return self.unpack('<f')
        if t==16: return self.unpack('<q')/10000
        if t in (17,21): return self.unpack('<d')
        if t==19: return self.unpack('<q')
        raise ValueError(f'Value type {t} at {self.p-1}')
    def props(self):
        out={}
        while True:
            name=self.sstr()
            if not name: return out
            out[name]=self.value()
    def component(self):
        pos=self.p; prefix=0; childpos=None
        if self.b[self.p]&0xf0==0xf0:
            prefix=self.byte()&0xf
            if prefix&2: childpos=self.value()
        cls=self.sstr(); name=self.sstr(); props=self.props(); children=[]
        while self.b[self.p]!=0: children.append(self.component())
        self.p+=1
        return {'class':cls,'name':name,'offset':pos,'prefix_flags':prefix,'child_position':childpos,'props':props,'children':children}

def walk(n):
    yield n
    for c in n['children']: yield from walk(c)

def image_list(blob, destination):
    """Decode the native IL stream's color/mask BMPs into 16x16 RGBA icons."""
    assert blob[:2]==b'IL'
    count,capacity,grow,width,height=struct.unpack_from('<HHHHH',blob,4)
    offsets=[]
    for pos in range(len(blob)-54):
        if blob[pos:pos+2]==b'BM' and struct.unpack_from('<I',blob,pos+14)[0]==40:
            offsets.append(pos)
    color=Image.open(io.BytesIO(blob[offsets[0]:])).convert('RGBA')
    mask=Image.open(io.BytesIO(blob[offsets[1]:])).convert('L')
    color.putalpha(ImageOps.invert(mask))
    destination.mkdir(parents=True,exist_ok=True)
    cols=color.width//width
    color.save(destination/'all-icons.png')
    contact=Image.new('RGB',(10*72,math.ceil(count/10)*42),'#e8e8e8')
    draw=ImageDraw.Draw(contact)
    for i in range(count):
        x=i%cols*width; y=i//cols*height
        icon=color.crop((x,y,x+width,y+height))
        icon.save(destination/f'icon-{i:03d}.png')
        x=i%10*72; y=i//10*42
        contact.paste(icon,(x+3,y+3),icon); draw.text((x+24,y+5),str(i),fill='black')
    contact.save(destination/'contact-sheet.png')
    return {'count':count,'capacity':capacity,'width':width,'height':height,'columns':cols,'source':'static Win32 ImageList binary; white mask pixels converted to transparent'}

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    exe=EXE.read_bytes(); resources=json.loads((ROOT/'analysis/winua_resources.json').read_text())
    report={'source':str(EXE),'source_sha256':hashlib.sha256(exe).hexdigest(),'evidence':'Static DFM only; runtime language changes, menu enablement, docking, themes, and window dimensions may differ.','forms':{}}
    for name in ['TUAFRAMEFORM','TUACHILDFORM']:
        res=next(r for r in resources if r['type']==10 and r['name']==name)
        data=exe[res['offset']:res['offset']+res['size']]; r=Reader(data); assert r.raw(4)==b'TPF0'
        try:
            tree=r.component(); result={'consumed':r.p,'size':len(data),'complete':r.p==len(data),'tree':tree}
            (OUT/f'{name}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            components=list(walk(tree)); report['forms'][name]={'complete':result['complete'],'consumed':r.p,'size':len(data),'component_count':len(components),'root_properties':tree['props']}
            selected=[n for n in components if 'Menu' in n['class'] or 'Tool' in n['class'] or 'SpeedButton' in n['class'] or n['name'].lower().endswith('panel')]
            (OUT/f'{name}-menus-toolbars.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2),encoding='utf-8')
            blobdir=OUT/name; blobdir.mkdir(exist_ok=True)
            for i,(pos,b) in enumerate(r.blobs):
                (blobdir/f'blob-{i:03d}-offset-{pos}.bin').write_bytes(b)
            if name=='TUAFRAMEFORM':
                image_node=next(n for n in components if n['name']=='ToolbarImages')
                blob=r.blobs[image_node['props']['Bitmap']['binary_index']][1]
                icons=image_list(blob,OUT/'toolbar-icons')
                menu=next(n for n in components if n['name']=='MainMenu')
                toolbar=next(n for n in components if n['name']=='MainToolBar')
                compact={'evidence':'static DFM; localized captions and runtime visibility unknown','main_menu':menu,'toolbar':toolbar,'toolbar_icons':icons}
                (OUT/'classic-ui.json').write_text(json.dumps(compact,ensure_ascii=False,indent=2),encoding='utf-8')
            print(name,report['forms'][name])
        except Exception as e:
            report['forms'][name]={'error':str(e),'position':r.p,'size':len(data)}
            print(name,report['forms'][name])
    (OUT/'extraction-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__': main()
