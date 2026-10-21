"""Measure the supplied WinUA screenshot without modifying the reference image.
Writes pixel measurements and per-icon template-match evidence only.
"""
from pathlib import Path
import json, hashlib
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
REFERENCE=Path(r'C:\Users\ADMINI~1\AppData\Local\Temp\codex-clipboard-15ff1a1f-40db-4c45-97a8-d5810ea2453b.png')
OUT=ROOT/'artifacts'/'screenshot-reference'
ICONS=ROOT/'tma_app'/'assets'/'classic'/'icons'

def ink_bbox(image,rect):
    x1,y1,x2,y2=rect
    a=image[y1:y2,x1:x2]
    yy,xx=np.where(np.min(a,axis=2)<100)
    return [int(xx.min()+x1),int(yy.min()+y1),int(xx.max()+x1),int(yy.max()+y1)]

def variants(path):
    icon=Image.open(path).convert('RGBA');a=np.array(icon);mask=a[:,:,3]>128
    bg=Image.new('RGBA',icon.size,(240,240,240,255));bg.alpha_composite(icon)
    yield 'normal',np.array(bg.convert('RGB'))
    shadow=np.full((17,17,3),240,np.uint8)
    shadow[1:,1:][mask]=255;shadow[:16,:16][mask]=160
    yield 'disabled_emboss_160',shadow[:16,:16]
    edge=np.zeros_like(mask);edge[1:,1:]=mask[:-1,:-1]
    inverted=np.full((16,16,3),105,np.uint8)
    inverted[mask]=240;inverted[edge&~mask]=255
    yield 'disabled_inverted_105',inverted

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    image=np.array(Image.open(REFERENCE).convert('RGB'))
    model=json.loads((ROOT/'tma_app/assets/classic/ui.json').read_text(encoding='utf8'))
    by_index={}
    for button in model['buttons']:by_index.setdefault(button['image_index'],[]).append(button['name'])
    templates=[(int(p.stem),state,data) for p in sorted(ICONS.glob('*.png')) for state,data in variants(p)]
    toolbar=[]
    for slot in range(31):
        x,y=6+24*slot,49;observed=image[y:y+16,x:x+16].astype(np.float64)
        scores=sorted((float(np.mean((observed-t.astype(float))**2)),idx,state) for idx,state,t in templates)
        mse,idx,state=scores[0]
        other=next(s for s in scores if s[1]!=idx)
        toolbar.append({'slot':slot,'image_index':idx,'button_candidates':by_index.get(idx,[]),'icon_bbox_xywh':[x,y,16,16],'button_bbox_xywh':[x-4,45,24,24],'state_pixel_model':state,'rgb_mse':mse,'rgb_rmse':mse**0.5,'next_different_index':other[1],'next_different_index_mse':other[0],'confidence':'high; identified by per-pixel comparison with all 160 source icons and disabled variants'})
    texts={name:{'observed_ink_bbox_inclusive':ink_bbox(image,rect),'method':'pixels with any RGB channel < 100 inside specified region; no OCR or font-name inference'} for name,rect in [('header_left',(0,70,450,130)),('header_right',(960,70,1912,130)),('y_tick_2500',(100,140,200,190)),('x_axis_title',(900,970,1110,1020)),('y_axis_title',(20,400,100,700)),('footer',(1700,970,1920,1020)),('menu_text',(20,23,440,43))]}
    data={'reference':str(REFERENCE),'sha256':hashlib.sha256(REFERENCE.read_bytes()).hexdigest(),'screenshot_size':[image.shape[1],image.shape[0]],'coordinates':'Absolute screenshot pixels. bbox x/y/width/height unless explicitly inclusive.','toolbar_image_index_order':[r['image_index'] for r in toolbar],'toolbar':toolbar,'observed_regions':{'application_caption':[0,0,1920,23],'menu_bar':[0,23,1920,21],'toolbar_band':[0,44,1920,26],'paper':[0,70,1920,951],'application_status':[0,1021,1920,19],'desktop_taskbar':[0,1040,1920,40]},'observed_colors':{'menu_toolbar_background_rgb':[240,240,240],'paper_rgb':[255,255,255],'plot_border_curve_core_rgb':[0,0,0],'toolbar_separator_rgb':[160,160,160],'disabled_gray_rgb':[160,160,160],'inverted_disabled_gray_rgb':[105,105,105]},'plot':{'border_inclusive':[217,167,1800,926],'border_thickness_px':1,'interior_gridlines':False,'major_x_ticks':[[217,50],[534,100],[850,150],[1167,200],[1484,250],[1800,300]],'major_y_ticks':[[167,2500],[293,2000],[420,1500],[547,1000],[673,500],[800,0],[926,-500]],'paper_relative_margins_px':{'left':217,'top':97,'right':119,'bottom':94},'curve_width_observed_px':1},'text_measurements':texts,'inferences':{'plot_font':'Serif Latin glyphs visually consistent with Times New Roman; CJK glyphs consistent with a Song-style serif fallback. Family cannot be proven from screenshot pixels alone.','plot_font_em_px_estimate':30,'font_size_warning':'Ink bbox heights are measured. Font em-size is an estimate; point size and original font settings are not recoverable with certainty from this screenshot.','button_hitbox_warning':'24 px button pitch and icon rectangles are confirmed. x=2+24*slot,y=45,24x24 hitboxes are inferred from a centered 16px glyph plus four-pixel insets.'},'occlusions':['Windows tray popup obscures part of paper/footer near x1536..1698,y920..1040.','Floating desktop decorative widgets overlay the title area.','Right edge has a floating shadow near x1912,y131..354.'],'source_untouched':True}
    (OUT/'measurements.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['# WinUA screenshot measurements','','The supplied screenshot was read without modification. All positions are original 1920 x 1080 screenshot pixels.','','## Confirmed toolbar','','31 visible buttons; icon top-left is x=6+24*slot, y=49. All glyphs are 16 x 16. Image indices:','','`'+', '.join(str(n) for n in data['toolbar_image_index_order'])+'`','','Each glyph was compared against all 160 original icons and two disabled render variants. Indices 34 and 49 match gray-160/white embossed disabled rendering; index 39 exactly matches an inverted disabled rendering with background 105, source mask 240, and one-pixel down/right white edges. JSON reports RGB mean square error and next-best different source index. Most ordinary icons differ by only small color-value quantization; disabled icons have exact zero error.','','## Confirmed geometry','','Menu bar y=23..43; toolbar band y=44..69; paper y=70..1020; status bar y=1021..1039; Windows taskbar y=1040..1079. Plot border is x=217..1800, y=167..926 inclusive, 1 px black, with no interior grid. Paper background is RGB 255,255,255; toolbar is RGB 240,240,240.','','Header ink y=75..102 is 28 px tall. Numeric 2500 tick ink y=158..177 is 20 px tall. X-axis title ink y=981..1011 is 31 px tall; footer Latin text y=985..1005 is 21 px tall. Font family and em size remain inferences; a roughly 30 px serif font with Song-style CJK fallback is consistent with these measurements.','','The JSON includes exact ink rectangles, tick coordinates, original-file hash, pixel errors, and explicit inference notes. Windows tray popup and desktop overlays must not be copied into the recreated application.']
    (OUT/'README.md').write_text('\n'.join(lines),encoding='utf8')
    print('toolbar',data['toolbar_image_index_order'])
    print('matches',[(r['image_index'],r['state_pixel_model'],round(r['rgb_mse'],4),round(r['next_different_index_mse'],2)) for r in toolbar])
    print('output',OUT/'measurements.json')
if __name__=='__main__':main()
