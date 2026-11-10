"""V2 central, normalized DCT marker with bounded symmetric-crop alignment."""
import hashlib
import numpy as np
from PIL import Image
from scipy.fft import dctn, idctn

BITS = np.unpackbits(np.frombuffer(hashlib.sha256(b'ZZZTMA normalized DCT v2').digest()[:16], dtype=np.uint8))
_rng = np.random.default_rng(26061110)
_points = np.array([(y, x) for y in range(5, 25) for x in range(5, 25)])
_points = _points[_rng.permutation(len(_points))[:256]]
A, B = _points[:128], _points[128:]


def _bounds(image):
    # Work at a bounded size; ignore the unmarked white export padding.
    small = image.convert('RGB').copy()
    small.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
    data = np.asarray(small)
    mask = np.any(data < 245, axis=2)
    yy, xx = np.where(mask)
    if len(xx) < 20: return (0, 0, image.width, image.height)
    sx, sy = image.width/small.width, image.height/small.height
    return (round(xx.min()*sx), round(yy.min()*sy), round((xx.max()+1)*sx), round((yy.max()+1)*sy))


def _roi(bounds, padding=0.):
    x0, y0, x1, y1 = bounds
    inset = .2 - .6*padding
    return (round(x0+(x1-x0)*inset), round(y0+(y1-y0)*inset),
            round(x1-(x1-x0)*inset), round(y1-(y1-y0)*inset))


def _coefficients(image, box):
    gray = image if image.mode == 'L' else image.convert('L')
    values = np.asarray(gray.crop(box).resize((256,256), Image.Resampling.LANCZOS), dtype=np.float32)
    return values, dctn(values, norm='ortho')


def _embed_once(image):
    if min(image.size) < 256: return image.copy()
    box = _roi(_bounds(image))
    values, coefficients = _coefficients(image, box)
    signs = BITS.astype(float)*2-1
    difference = coefficients[A[:,0],A[:,1]]-coefficients[B[:,0],B[:,1]]
    adjustment = np.maximum(0, 64 - signs*difference)*signs/2
    coefficients[A[:,0],A[:,1]] += adjustment
    coefficients[B[:,0],B[:,1]] -= adjustment
    delta = idctn(coefficients,norm='ortho')-values
    delta_image = Image.fromarray(delta.astype(np.float32)).resize((box[2]-box[0],box[3]-box[1]),Image.Resampling.BICUBIC)
    rgb = np.asarray(image.convert('RGB'),dtype=np.float32).copy()
    x0,y0,x1,y1=box
    rgb[y0:y1,x0:x1] = np.clip(np.rint(rgb[y0:y1,x0:x1]+np.asarray(delta_image)[...,None]),0,255)
    output=Image.fromarray(rgb.astype(np.uint8),'RGB')
    if 'A' in image.getbands(): output.putalpha(image.getchannel('A'))
    return output


def embed(image):
    # Bright chart backgrounds clip positive perturbations. Recheck the actual
    # quantized pixels and correct a bounded number of times instead of assuming
    # the inverse transform survived clipping and integer rounding unchanged.
    output = image
    for _ in range(4):
        output = _embed_once(output)
    return output


def detect(image):
    if min(image.size)<128: return dict(detected=False,score=0.,scheme='normalized_dct_v2')
    bounds = [_bounds(image), (0,0,image.width,image.height)]
    image = image.convert('L')
    # A fixed search budget, not an unlimited scan; about 1% error tolerated.
    best = 0.
    best_padding = 0.
    for bound in bounds:
        for padding in np.arange(0,.1001,.0025):
            _, coefficients = _coefficients(image,_roi(bound,padding))
            bits = coefficients[A[:,0],A[:,1]] > coefficients[B[:,0],B[:,1]]
            score = float(np.mean(bits == BITS))
            if score > best: best, best_padding = score, float(padding)
            if score == 1.:
                return dict(detected=True,score=score,scheme='normalized_dct_v2',padding=float(padding))
    return dict(detected=best>=.94,score=best,scheme='normalized_dct_v2',padding=best_padding)
